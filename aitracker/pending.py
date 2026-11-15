"""Pending-work worker: finds worktrees / tmp trees holding unfinished work and reports them.

Stages (plan v3.1 section 3): discover -> inspect -> gh -> classify -> clean -> report.
This part is READ-ONLY: git status/rev-list/merge-base, disk stat, and `gh pr list`. The clean
stage, tick/worker and CLI are added below by later steps. Every git/gh call has a timeout and
fails closed: an error means the item is kept / "unknown", never deletable."""
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time

from . import config
from .store import _load_json, _save_json
from .registry import all_cwds
from .providers.claude import _pid_alive, _session_meta
from .schedule import sched_install, sched_uninstall, sched_status

GIT_TIMEOUT = 10                 # s per git call; timeout -> verdict "unknown", not deletable
SCAN_ENTRY_CAP = 50_000          # dirents per tmp tree; exceeded -> keep
PENDING_GRACE = 7 * 86400        # deletion idle-grace; DECOUPLED from PENDING_INTERVAL
SLACK = 3600                     # due() tolerance (used by tick)
GH_TIMEOUT = 15                  # s per gh call
GH_MAX_CALLS = 20                # gh calls per scan, hard cap
GH_BUDGET_S = 120                # wall-clock budget for all gh calls in one scan
GH_NONE_TTL = 86400              # re-ask gh about a "no merged PR" answer after 24h
_DONE_STATES = ("done", "failed", "stopped")
_RUNNING = threading.Event()
_WORKER = []                     # the one worker thread, once started


# ---------------------------------------------------------------- primitives

class _GitErr(Exception):
    pass


def _git(cwd, *args):
    """(rc, stdout) of `git -C cwd args`. rc is None on timeout / spawn failure (fail closed)."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(["git", "--no-optional-locks", "-C", cwd, *args], capture_output=True,
                           timeout=GIT_TIMEOUT, env=env)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None, ""
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _gh(cwd, *args):
    """(rc, stdout) of `gh args` run in cwd. rc None on timeout / spawn failure / gh missing.
    GH_REPO and GH_HOST are removed so a server-wide override cannot redirect every worktree."""
    exe = shutil.which("gh")
    if not exe:
        return None, ""
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    env.update(GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", GH_SPINNER_DISABLED="1", NO_COLOR="1")
    try:
        p = subprocess.run([exe, *args], capture_output=True, cwd=cwd, timeout=GH_TIMEOUT, env=env)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None, ""
    return p.returncode, p.stdout.decode("utf-8", "replace")


def _need(cwd, *args):
    """stdout of a git call that must succeed, else _GitErr."""
    rc, out = _git(cwd, *args)
    if rc != 0:
        raise _GitErr("git %s: %s" % (args[0], "timeout/spawn failure" if rc is None else "exit %s" % rc))
    return out


def _rp(p):
    return os.path.normcase(os.path.realpath(p))


def _under(path, root, depth=None):
    """True iff realpath(path) is at/under realpath(root) (commonpath, so `/a/b0` is NOT under `/a/b`).
    depth given -> the relative depth must be exactly that."""
    try:
        rp, rr = _rp(path), _rp(root)
        if os.path.commonpath([rp, rr]) != rr:
            return False
    except (ValueError, OSError, TypeError):
        return False
    if depth is None:
        return True
    rel = os.path.relpath(rp, rr)
    return rel != "." and len(rel.split(os.sep)) == depth


def _alive(pid):
    return True if os.name == "nt" else _pid_alive(pid)    # nt: unknown -> alive (fail closed)


@contextlib.contextmanager
def _pending_lock():
    """Per-user non-blocking lock on config.PENDING_LOCK. Yields True when held, False when busy."""
    fh = None
    got = False
    try:
        fh = open(config.PENDING_LOCK, "a+")
        if os.name == "nt":
            import msvcrt
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                got = True
            except OSError:
                got = False
        else:
            import fcntl
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
            except OSError:
                got = False
    except OSError:
        got = False
    try:
        yield got
    finally:
        if fh is not None:
            try:
                if got:
                    if os.name == "nt":
                        import msvcrt
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fh, fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()


def _item_id(path):
    return hashlib.sha1(_rp(path).encode("utf-8", "replace")).hexdigest()[:12]


def _mtime(p):
    try:
        return os.lstat(p).st_mtime
    except OSError:
        return 0


# ---------------------------------------------------------------- context

def build_ctx():
    """Built once per run: unfinished/finished jobs, live session cwds, transcript mtimes."""
    jobs, job_by_id, job_by_sid = [], {}, {}
    try:
        names = os.listdir(config.JOBS_DIR)
    except OSError:
        names = []
    for jid in names:
        st = _load_json(os.path.join(config.JOBS_DIR, jid, "state.json"), None)
        if not isinstance(st, dict):
            continue
        job_by_id[jid] = st
        if isinstance(st.get("sessionId"), str):
            job_by_sid[st["sessionId"]] = st
        p = st.get("worktreePath") or st.get("cwd")
        if isinstance(p, str) and p:
            jobs.append((_rp(p), st))
    live = set()
    try:
        sess = os.listdir(config.LIVE_SESSIONS_DIR)
    except OSError:
        sess = []
    for n in sess:
        if not n.endswith(".json"):
            continue
        d = _load_json(os.path.join(config.LIVE_SESSIONS_DIR, n), None)
        if isinstance(d, dict) and isinstance(d.get("cwd"), str) and d["cwd"] and _alive(d.get("pid")):
            live.add(_rp(d["cwd"]))
    tx, tx_sid = {}, {}
    try:
        projs = os.listdir(config.PROJECTS)
    except OSError:
        projs = []
    for proj in projs:
        d = os.path.join(config.PROJECTS, proj)
        try:
            files = [f for f in os.listdir(d) if f.endswith(".jsonl")]
        except OSError:
            continue
        for f in files:
            fp = os.path.join(d, f)
            mt = _mtime(fp)
            tx_sid[f[:-6]] = max(mt, tx_sid.get(f[:-6], 0))
            cwd = _session_meta(fp).get("cwd")
            if cwd:
                k = _rp(cwd)
                tx[k] = max(mt, tx.get(k, 0))
    return {"jobs": jobs, "job_by_id": job_by_id, "job_by_sid": job_by_sid, "live": live,
            "tx": tx, "tx_sid": tx_sid, "bases": {}}


# ---------------------------------------------------------------- discovery

def _parse_porcelain(out):
    wts, cur = [], None
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                wts.append(cur)
            cur = None
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = {"path": val, "head": "", "branch": None, "detached": False, "bare": False,
                   "locked": False, "prunable": False, "primary": not wts}
        elif cur is not None:
            if key == "HEAD":
                cur["head"] = val
            elif key == "branch":
                cur["branch"] = val[11:] if val.startswith("refs/heads/") else val
            elif key == "detached":
                cur["detached"] = True
            elif key == "bare":
                cur["bare"] = True
            elif key == "locked":
                cur["locked"] = True
            elif key == "prunable":
                cur["prunable"] = True
    return wts


def list_worktrees(repo):
    """Porcelain worktree list of a repo ({"top": ...} dict from discover_repos, or a path).
    First entry is the primary. Raises _GitErr on a git failure (caller keeps the repo, reports error)."""
    top = repo["top"] if isinstance(repo, dict) else repo
    return _parse_porcelain(_need(top, "worktree", "list", "--porcelain"))


def _nearest_existing(p):
    p = os.path.abspath(p)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    return p


def discover_repos(now=None, extra_seeds=(), prev=None):
    """{realpath common dir: {"common", "top", "cwds"}}. Seeds: registry cwds, job state.json cwd /
    originCwd / worktreePath, `extra_seeds` (git_roots from scan_tmp) and the previous report's repos[]
    (dropped only when their common dir is gone). Vanished cwds walk up to the nearest existing dir."""
    seeds = []                                   # (seed, is_cwd)
    try:
        seeds += [(c, True) for c in all_cwds()]
    except Exception:
        pass
    try:
        names = os.listdir(config.JOBS_DIR)
    except OSError:
        names = []
    for jid in names:
        st = _load_json(os.path.join(config.JOBS_DIR, jid, "state.json"), None)
        if isinstance(st, dict):
            seeds += [(st[k], True) for k in ("cwd", "originCwd", "worktreePath") if isinstance(st.get(k), str) and st[k]]
    seeds += [(s, False) for s in extra_seeds]
    if prev is None:
        prev = _load_json(config.PENDING_FILE, {})
    for r in (prev.get("repos") if isinstance(prev, dict) else None) or []:
        if isinstance(r, dict) and r.get("common") and os.path.isdir(r["common"]):
            seeds.append((r.get("top") or r["common"], False))
    repos = {}
    for seed, is_cwd in seeds:
        d = _nearest_existing(seed) if isinstance(seed, str) else None
        if not d:
            continue
        rc, out = _git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc != 0 or not out.strip():
            continue
        common = os.path.realpath(out.strip())
        ent = repos.get(common)
        if ent is None:
            rc, wt = _git(d, "worktree", "list", "--porcelain")
            wts = _parse_porcelain(wt) if rc == 0 else []
            if not wts:
                continue
            ent = repos[common] = {"common": common, "top": wts[0]["path"], "cwds": []}
        if is_cwd and seed not in ent["cwds"]:
            ent["cwds"].append(seed)
    return repos


# ---------------------------------------------------------------- inspection

def _status_entries(out):
    """-z porcelain v1 -> [(XY, path)], consuming the extra field of renames/copies."""
    parts = out.split("\0")
    res, i = [], 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy = e[:2]
        res.append((xy, e[3:]))
        if "R" in xy or "C" in xy:
            i += 1
    return res


def _base_ref(cwd, ctx):
    """First existing of refs/remotes/*/{develop,main,master} (name order, `origin` first), else None."""
    top_key = cwd
    if top_key in ctx["bases"]:
        return ctx["bases"][top_key]
    base = None
    rc, out = _git(cwd, "for-each-ref", "--format=%(refname:short)", "refs/remotes")
    if rc == 0:
        refs = sorted(r for r in out.split() if "/" in r and not r.endswith("/HEAD"))
        for name in ("develop", "main", "master"):
            cand = [r for r in refs if r.split("/", 1)[1] == name]
            cand.sort(key=lambda r: (not r.startswith("origin/"), r))
            if cand:
                base = cand[0]
                break
    ctx["bases"][top_key] = base
    return base


def _last_activity(wt, repo, ctx):
    """max mtime of the worktree's admin files + dir + newest transcript whose cwd is under it."""
    path = wt["path"]
    t = _mtime(path)
    admin = None
    if wt["primary"]:
        admin = repo["common"]
    else:
        try:
            with open(os.path.join(path, ".git"), encoding="utf-8") as fh:
                line = fh.read().strip()
            if line.startswith("gitdir:"):
                admin = line[7:].strip()
        except OSError:
            admin = None
        if not admin:
            admin = os.path.join(repo["common"], "worktrees", os.path.basename(path.rstrip(os.sep)))
    for f in ("HEAD", "index", os.path.join("logs", "HEAD")):
        t = max(t, _mtime(os.path.join(admin, f)))
    for cwd, mt in ctx["tx"].items():
        if _under(cwd, path):
            t = max(t, mt)
    return int(t)


def _job_busy(path, ctx):
    return any(_under(jp, path) and st.get("state") not in _DONE_STATES for jp, st in ctx["jobs"])


def _live_under(path, ctx):
    return any(_under(c, path) for c in ctx["live"])


def inspect_worktree(wt, repo, ctx):
    """Read-only facts about one worktree entry (a dict from list_worktrees). Never raises: a git
    failure sets item["error"] (classify -> "unknown", not deletable)."""
    path = wt["path"]
    item = {"id": _item_id(path), "kind": "repo" if wt["primary"] else "worktree", "path": path,
            "repo": repo["common"], "top": repo["top"], "branch": wt["branch"], "detached": wt["detached"],
            "head": wt["head"], "base": None, "upstream": None, "dirty": 0, "untracked": 0, "ignored": 0,
            "files": [], "ignored_files": [], "unpushed": 0, "ahead": 0, "behind": 0, "ancestor": False,
            "locked": wt["locked"], "primary": wt["primary"], "bare": wt["bare"], "missing": False,
            "contained": True, "last_activity": 0, "busy_job": False, "live": False,
            "gh": {"state": "skipped", "pr": None, "checked_at": 0},
            "verdict": "unknown", "deletable": False, "reason": "", "label": "", "error": None}
    try:
        item["busy_job"] = _job_busy(path, ctx)
        item["live"] = _live_under(path, ctx)
        item["last_activity"] = _last_activity(wt, repo, ctx)
        if wt["bare"]:
            return item
        if wt["prunable"] or not os.path.isdir(path):
            item["missing"] = True
            sha = wt["head"]
            item["contained"] = bool(_need(repo["top"], "for-each-ref", "--contains", sha, "--count=1",
                                           "--format=%(refname)").strip())
            item["unpushed"] = int(_need(repo["top"], "rev-list", "--count", sha, "--not", "--remotes").strip() or 0)
            return item
        out = _need(path, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=normal")
        ents = _status_entries(out)
        ign = [p for xy, p in ents if xy == "!!"]
        ents = [(xy, p) for xy, p in ents if xy != "!!"]
        item["untracked"] = sum(1 for xy, _ in ents if xy == "??")
        item["dirty"] = len(ents) - item["untracked"]
        item["files"] = [p for _, p in ents][:50]
        item["ignored"] = len(ign)
        item["ignored_files"] = ign[:20]
        item["unpushed"] = int(_need(path, "rev-list", "--count", "HEAD", "--not", "--remotes").strip() or 0)
        rc, up = _git(path, "rev-parse", "--abbrev-ref", "@{u}")
        if rc == 0 and up.strip():
            item["upstream"] = up.strip()
            rc, lr = _git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
            if rc == 0 and len(lr.split()) == 2:
                item["ahead"], item["behind"] = (int(x) for x in lr.split())
        base = _base_ref(repo["top"], ctx)
        item["base"] = base
        if base:
            rc, _o = _git(path, "merge-base", "--is-ancestor", "HEAD", base)
            if rc not in (0, 1):
                raise _GitErr("git merge-base: %s" % ("timeout/spawn failure" if rc is None else "exit %s" % rc))
            item["ancestor"] = rc == 0
        item["head"] = _need(path, "rev-parse", "HEAD").strip()
    except (_GitErr, ValueError, OSError) as e:
        item["error"] = str(e) or e.__class__.__name__
    return item


# ---------------------------------------------------------------- tmp / scratch

def _walk_tree(root):
    """(newest mtime, bytes, entries, capped, git_roots) of a tree; never follows symlinks and does
    not descend into `.git`. git_roots: dirs holding a `.git` file or directory."""
    newest, size, n, capped, gits = _mtime(root), 0, 0, False, []
    for dp, dns, fns in os.walk(root, followlinks=False):
        if ".git" in dns or ".git" in fns:
            gits.append(dp)
            dns[:] = [d for d in dns if d != ".git"]
        for nm in dns + fns:
            n += 1
            if n > SCAN_ENTRY_CAP:
                capped = True
                return newest, size, n, capped, gits
            try:
                st = os.lstat(os.path.join(dp, nm))
            except OSError:
                continue
            newest = max(newest, st.st_mtime)
            size += st.st_size
    return newest, size, n, capped, gits


def scan_tmp(ctx, now=None):
    """([tmp entry dicts], git_roots). Candidates: SCRATCH_ROOT/<slug>/<sid> (depth 2, POSIX) and
    JOBS_DIR/<id>/tmp (depth 2). An entry is `stale` (== deletable) only when every guard holds;
    anything uncertain is `keep`. Never deletes."""
    now = time.time() if now is None else now
    cands = []                                   # (path, root, session, job_id)
    sr = config.SCRATCH_ROOT
    if sr and os.path.isdir(sr):
        try:
            slugs = os.listdir(sr)
        except OSError:
            slugs = []
        for slug in slugs:
            try:
                sids = os.listdir(os.path.join(sr, slug))
            except OSError:
                continue
            for sid in sids:
                cands.append((os.path.join(sr, slug, sid), sr, sid, None))
    try:
        jids = os.listdir(config.JOBS_DIR)
    except OSError:
        jids = []
    for jid in jids:
        tp = os.path.join(config.JOBS_DIR, jid, "tmp")
        if os.path.isdir(tp):
            cands.append((tp, config.JOBS_DIR, None, jid))
    out, roots = [], []
    for path, root, sid, jid in cands:
        if not os.path.isdir(path) or not _under(path, root, 2):   # SCRATCH_ROOT/<slug>/<sid>; JOBS_DIR/<id>/tmp
            continue
        reason = None
        newest, size, _n, capped, gits = _walk_tree(path)
        roots += gits
        job = ctx["job_by_id"].get(jid) if jid else ctx["job_by_sid"].get(sid)
        if os.path.islink(path):
            reason = "symlink"
        elif gits:
            reason = "holds a git repo"
        elif capped:
            reason = "too many entries to verify"
        elif job is not None and job.get("state") not in _DONE_STATES:
            reason = "job %s" % job.get("state")
        elif job is None and ctx["tx_sid"].get(sid or "", 0) > now - PENDING_GRACE:
            reason = "recent transcript"
        elif newest >= now - PENDING_GRACE:
            reason = "active < grace"
        elif _live_under(path, ctx):
            reason = "live session"
        out.append({"id": _item_id(path), "kind": "scratch", "path": path, "session": sid or (job or {}).get("sessionId"),
                    "job": jid, "bytes": size, "age_s": int(now - newest),
                    "verdict": "keep" if reason else "stale", "deletable": reason is None,
                    "reason": reason or "stale tmp tree"})
    return out, roots


# ---------------------------------------------------------------- gh

def _gh_key(item):
    return "\x00".join((item["repo"], item["branch"] or "", item["head"]))


def _is_candidate(it, now):
    """Would be reclaimable EXCEPT for the merge test (plan section 3, gh candidates)."""
    return (it["kind"] in ("worktree", "repo") and not it["primary"] and not it["detached"] and not it["locked"]
            and not it["bare"] and not it["missing"] and not it["error"] and not _own_tracker(it)
            and it["branch"] and it["dirty"] == it["untracked"] == it["ignored"] == 0 and not it["ancestor"]
            and now - it["last_activity"] >= PENDING_GRACE and not it["busy_job"] and not it["live"])


def gh_merged(items, report_cache, now):
    """Fills item["gh"] in place for every worktree item; bounded (GH_MAX_CALLS, GH_BUDGET_S), sequential,
    oldest first, one circuit breaker (first error of any kind stops all further calls this run).
    report_cache is report["gh_cache"] (string keys, JSON-safe); mutated. Returns the number of gh calls."""
    live_repos = {i["repo"] for i in items}
    for k in [k for k in report_cache if k.split("\x00", 1)[0] not in live_repos]:
        del report_cache[k]
    for it in items:
        it["gh"] = {"state": "skipped", "pr": None, "checked_at": now}
    cands = sorted((i for i in items if _is_candidate(i, now)), key=lambda i: i["last_activity"])
    if not cands:
        return 0
    if not shutil.which("gh"):
        for it in cands:
            it["gh"] = {"state": "unavailable", "pr": None, "checked_at": now}
        return 0
    calls, tripped, t0 = 0, False, time.monotonic()
    for it in cands:
        key = _gh_key(it)
        hit = report_cache.get(key)
        if hit and (hit.get("state") == "merged" or now - hit.get("checked_at", 0) < GH_NONE_TTL):
            it["gh"] = dict(hit)
            continue
        if tripped or calls >= GH_MAX_CALLS or time.monotonic() - t0 > GH_BUDGET_S:
            continue                              # stays "skipped"
        calls += 1
        rc, out = _gh(it["top"], "pr", "list", "--head", it["branch"], "--state", "merged", "--json",
                      "number,url,headRefOid,baseRefName,mergedAt", "--limit", "5")
        prs = None
        if rc == 0:
            try:
                prs = json.loads(out)
                if not isinstance(prs, list) or not all(isinstance(p, dict) for p in prs):
                    prs = None
            except ValueError:
                prs = None
        if prs is None:
            tripped = True
            it["gh"] = {"state": "error", "pr": None, "checked_at": now}     # errors are never cached
            continue
        match = next((p for p in prs if p.get("headRefOid") == it["head"]), None)
        if match:
            res = {"state": "merged", "pr": match.get("url"), "number": match.get("number"),
                   "base": match.get("baseRefName"), "checked_at": now}
        else:
            res = {"state": "none", "pr": None, "checked_at": now}
        report_cache[key] = res
        it["gh"] = dict(res)
    return calls


# ---------------------------------------------------------------- classify / card / report

def _own_tracker(it):
    return _under(config._HERE, it["path"])


def classify(wt, ctx, now):
    """wt = an inspected item. -> {"verdict", "deletable", "reason", "label"}. Pure given the item.
    verdict: unknown | missing | pending | clean. A MERGED gh answer only replaces the
    ancestor/unpushed term; it never makes anything deletable on its own (see reclaimable)."""
    it = wt
    gh = it.get("gh") or {}
    merged = gh.get("state") == "merged"
    if it["error"]:
        return {"verdict": "unknown", "deletable": False, "reason": "git error: %s" % it["error"],
                "label": "unknown (git error; kept)"}
    if it["bare"]:
        verdict, reason = "clean", "bare repository"
    elif it["missing"]:
        n = it["unpushed"]
        reason = ("%d orphan commits" % n if not it["contained"] else
                  "branch has %d unpushed" % n if n else "worktree directory gone")
        return {"verdict": "missing", "deletable": False, "reason": reason, "label": reason}
    elif it["dirty"] or it["untracked"] or (it["unpushed"] > 0 and not merged):
        bits = []
        if it["dirty"]:
            bits.append("%d uncommitted" % it["dirty"])
        if it["untracked"]:
            bits.append("%d untracked" % it["untracked"])
        if it["unpushed"] > 0 and not merged:
            bits.append("%d unpushed" % it["unpushed"])
        verdict, reason = "pending", ", ".join(bits)
    elif merged:
        verdict = "clean"
        pr = gh.get("number") or (gh.get("pr") or "").rsplit("/", 1)[-1]
        reason = "squash-merged%s (PR #%s)" % (" into %s" % gh["base"] if gh.get("base") else "", pr)
    elif it["ancestor"]:
        verdict, reason = "clean", "merged into %s" % it["base"]
    else:
        verdict, reason = "clean", "pushed; not merged into %s" % (it["base"] or "any base")
    deletable = (verdict == "clean" and not it["primary"] and not it["bare"] and not it["locked"]
                 and it["ignored"] == 0 and not _own_tracker(it))
    label = reason + (" · %d ignored files" % it["ignored"] if it["ignored"] else "")
    if deletable and reclaimable(dict(it, verdict=verdict, deletable=True), now):
        label += " · worktree reclaimable" + ("; branch kept" if merged else "")
    return {"verdict": verdict, "deletable": deletable, "reason": reason, "label": label}


def reclaimable(it, now):
    """Deletable AND (ancestor with nothing unpushed, or a gh-merged exact head) AND idle >= grace
    AND no unfinished job AND no live session. Pure on the inspected item (busy_job/live are
    captured at inspect time); the clean stage re-inspects right before removal."""
    if not it.get("deletable") or it["verdict"] != "clean":
        return False
    merged_ok = (it["ancestor"] and it["unpushed"] == 0) or (it.get("gh") or {}).get("state") == "merged"
    return bool(merged_ok and now - it["last_activity"] >= PENDING_GRACE and not it["busy_job"] and not it["live"])


def build_card(report, now=None):
    """Server-built card: counts verdict pending/missing items plus stale tmp entries; the SPA never
    derives a verdict or threshold."""
    now = time.time() if now is None else now
    hot = [i for i in report.get("items", []) if i.get("verdict") in ("pending", "missing")]
    stale = [t for t in report.get("tmp", []) if t.get("verdict") == "stale"]
    count = len(hot) + len(stale)
    parts = []
    if hot:
        oldest = max(max(0, now - i["last_activity"]) for i in hot) // 86400
        parts.append("%d worktree%s with unfinished work (oldest idle %dd)" % (len(hot), "" if len(hot) == 1 else "s", oldest))
    if stale:
        parts.append("%d stale tmp tree%s" % (len(stale), "" if len(stale) == 1 else "s"))
    return {"show": count > 0, "title": "Pending work", "summary": "; ".join(parts), "count": count}


def scan(now=None):
    """Read-only run of discover -> inspect -> gh -> classify -> tmp -> card. Returns the report dict
    (deleted/would_delete/refused empty; scheduled_at/mode/duration_s/interval are set by run_once;
    `clean` fills the rest and may call build_card again)."""
    now = time.time() if now is None else now
    t0 = time.monotonic()
    prev = _load_json(config.PENDING_FILE, {})
    prev = prev if isinstance(prev, dict) else {}
    ctx = build_ctx()
    tmp, roots = scan_tmp(ctx, now)
    repos = discover_repos(now, extra_seeds=roots, prev=prev)
    items, errors = [], []
    for repo in repos.values():
        try:
            wts = list_worktrees(repo)
        except _GitErr as e:
            errors.append({"repo": repo["common"], "error": str(e)})
            continue
        for wt in wts:
            items.append(inspect_worktree(wt, repo, ctx))
    cache = prev.get("gh_cache") if isinstance(prev.get("gh_cache"), dict) else {}
    gh_merged(items, cache, now)
    for it in items:
        it.update(classify(it, ctx, now))
    report = {"generated_at": now, "scheduled_at": prev.get("scheduled_at"), "interval": None, "mode": None,
              "duration_s": round(time.monotonic() - t0, 3),
              "repos": sorted(repos.values(), key=lambda r: r["common"]), "gh_cache": cache, "items": items,
              "tmp": tmp, "deleted": [], "would_delete": [], "refused": [], "errors": errors, "running": False}
    report["card"] = build_card(report, now)
    return report


# ---------------------------------------------------------------- clean (the only code that deletes)

def _log(line):
    try:
        with open(config.PENDING_LOG, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), line))
    except OSError:
        pass


def _reinspect(it, now):
    """Fresh facts about one item right before removal: a NEW ctx (live sessions / jobs / transcripts)
    and a NEW inspection. Returns the re-classified item, or None when the worktree is gone/changed."""
    repo = {"common": it["repo"], "top": it["top"]}
    match = [w for w in list_worktrees(repo) if _rp(w["path"]) == _rp(it["path"])]
    if len(match) != 1:
        return None
    ctx = build_ctx()
    fresh = inspect_worktree(match[0], repo, ctx)
    fresh["gh"] = dict(it.get("gh") or {})
    fresh.update(classify(fresh, ctx, now))
    return fresh


def _remove_worktree(it, now, report):
    """Remove one worktree + try `branch -d`. Everything fails closed into report["refused"]."""
    def refuse(why):
        report["refused"].append({"id": it["id"], "path": it["path"], "reason": why})
        _log("REFUSED worktree %s: %s" % (it["path"], why))
    try:
        fresh = _reinspect(it, now)
        if fresh is None:
            return refuse("worktree changed or vanished since the scan")
        if not reclaimable(fresh, now):
            return refuse("no longer reclaimable on re-inspection (%s)" % (fresh["reason"] or fresh["verdict"]))
        if fresh["head"] != it["head"] or fresh["branch"] != it["branch"]:
            return refuse("HEAD or branch moved since the scan")
        rc, _o = _git(it["top"], "worktree", "remove", it["path"])      # never --force
        if rc != 0:
            return refuse("git worktree remove refused (%s)" % ("timeout" if rc is None else "exit %s" % rc))
        rec = {"id": it["id"], "kind": "worktree", "path": it["path"], "branch": it["branch"],
               "branch_deleted": False, "note": ""}
        short = (fresh["base"] or "").split("/", 1)[-1]
        if it["branch"] and not it["detached"] and it["branch"] != short:
            rc, _o = _git(it["top"], "branch", "-d", it["branch"])      # never -D
            rec["branch_deleted"] = rc == 0
            if rc != 0:
                rec["note"] = ("branch kept (squash-merged; delete with -D yourself)"
                               if (it.get("gh") or {}).get("state") == "merged" else "branch kept (git branch -d refused)")
        report["deleted"].append(rec)
        _log("DELETED worktree %s branch=%s branch_deleted=%s %s" % (it["path"], it["branch"], rec["branch_deleted"], rec["note"]))
    except Exception as e:                      # any exception => keep
        refuse("error: %s" % e)


def _prune_repo(repo_common, top, report, safe):
    """`worktree prune` only when EVERY prunable entry of the repo is contained (its commits are on a ref)."""
    repo = {"common": repo_common, "top": top}
    try:
        prunable = [w for w in list_worktrees(repo) if w["prunable"]]
        if not prunable:
            return
        ctx = build_ctx()
        for w in prunable:
            f = inspect_worktree(w, repo, ctx)
            if f["error"] or not f["contained"]:
                report["refused"].append({"id": f["id"], "path": f["path"], "reason": "prune skipped: %s" % (
                    f["error"] or "%d orphan commits" % f["unpushed"])})
                return
        if not safe:
            report["would_delete"].append({"id": _item_id(top), "kind": "prune", "path": top,
                                           "reason": "%d missing worktree entries" % len(prunable)})
            return
        rc, _o = _git(top, "worktree", "prune")
        if rc == 0:
            report["deleted"].append({"id": _item_id(top), "kind": "prune", "path": top,
                                      "note": "%d missing worktree entries pruned" % len(prunable)})
            _log("PRUNED %d missing worktree entries in %s" % (len(prunable), top))
        else:
            report["refused"].append({"id": _item_id(top), "path": top, "reason": "git worktree prune failed"})
    except Exception as e:
        report["refused"].append({"id": _item_id(top), "path": top, "reason": "prune error: %s" % e})


def _remove_tmp(t, now, report):
    def refuse(why):
        report["refused"].append({"id": t["id"], "path": t["path"], "reason": why})
        _log("REFUSED tmp %s: %s" % (t["path"], why))
    try:
        fresh = {e["path"]: e for e in scan_tmp(build_ctx(), now)[0]}.get(t["path"])
        if fresh is None or not fresh["deletable"]:
            return refuse("no longer stale on re-scan (%s)" % (fresh or {}).get("reason", "gone"))
        if os.path.islink(t["path"]) or any(_walk_tree(t["path"])[4]):
            return refuse("symlink or contains a git repo")
        errs = []
        shutil.rmtree(t["path"], onerror=lambda f, p, e: errs.append(p))
        if errs or os.path.exists(t["path"]):
            return refuse("rmtree incomplete (%d paths)" % len(errs))
        report["deleted"].append({"id": t["id"], "kind": "scratch", "path": t["path"], "bytes": t["bytes"], "note": ""})
        _log("DELETED tmp %s (%d bytes)" % (t["path"], t["bytes"]))
    except Exception as e:
        refuse("error: %s" % e)


def clean(report, mode, now=None):
    """Mode-gated, fail-closed. "dry-run" lists would_delete and touches nothing; "off" does nothing;
    only "safe" removes, and only items that pass `reclaimable` again on a fresh re-inspection."""
    now = time.time() if now is None else now
    report["deleted"], report["would_delete"], report["refused"] = [], [], []
    if mode not in ("dry-run", "safe"):
        return report["deleted"]
    safe = mode == "safe"
    for it in list(report["items"]):
        if it["kind"] == "worktree" and reclaimable(it, now):
            if safe:
                _remove_worktree(it, now, report)
            else:
                report["would_delete"].append({"id": it["id"], "kind": "worktree", "path": it["path"], "reason": it["label"]})
    for repo in report["repos"]:
        _prune_repo(repo["common"], repo["top"], report, safe)
    for t in list(report["tmp"]):
        if t.get("deletable"):
            if safe:
                _remove_tmp(t, now, report)
            else:
                report["would_delete"].append({"id": t["id"], "kind": "scratch", "path": t["path"], "reason": t["reason"]})
    gone = {d["path"] for d in report["deleted"] if d.get("kind") != "prune"}
    report["items"] = [i for i in report["items"] if i["path"] not in gone]
    report["tmp"] = [t for t in report["tmp"] if t["path"] not in gone]
    report["card"] = build_card(report, now)
    return report["deleted"]


# ---------------------------------------------------------------- run / schedule / worker

def due(report, now, interval_s):
    if interval_s is None:
        return False
    sa = report.get("scheduled_at") if isinstance(report, dict) else None
    if not isinstance(sa, (int, float)):
        return True
    return now - sa >= interval_s - SLACK


def run_once(mode=None, now=None, scheduled=False):
    """discover -> inspect -> gh -> classify -> clean(mode) -> pending.json, under the per-user lock
    (busy -> {"running": True}). scheduled_at moves only for a scheduled run in the configured mode."""
    mode = mode or config.PENDING_CLEAN
    now = time.time() if now is None else now
    with _pending_lock() as got:
        if not got:
            return {"running": True}
        _RUNNING.set()
        try:
            t0 = time.monotonic()
            report = scan(now)
            report["mode"], report["interval"] = mode, config.PENDING_INTERVAL
            if scheduled and mode == config.PENDING_CLEAN:
                report["scheduled_at"] = now
            clean(report, mode, now)
            report["duration_s"] = round(time.monotonic() - t0, 3)
            report["running"] = False
            _save_json(config.PENDING_FILE, report)
            return report
        finally:
            _RUNNING.clear()


def run_async(mode="dry-run"):
    if _RUNNING.is_set():
        return False
    threading.Thread(target=lambda: run_once(mode), daemon=True, name="pending-scan").start()
    return True


def tick(now=None):
    """THE scheduler decision (worker thread, OS job, CLI): "off" | "run" | "busy" | "idle". Reads the
    report fresh from disk so the thread and the OS job never double-run."""
    now = time.time() if now is None else now
    secs = config.interval_seconds(config.PENDING_INTERVAL)
    if secs is None:
        return "off"
    if not due(_load_json(config.PENDING_FILE, {}), now, secs):
        return "idle"
    r = run_once(config.PENDING_CLEAN, now, scheduled=True)
    return "busy" if "items" not in r else "run"


def _next_wait(now):
    secs = config.interval_seconds(config.PENDING_INTERVAL)
    sa = (_load_json(config.PENDING_FILE, {}) or {}).get("scheduled_at")
    if secs is None or not isinstance(sa, (int, float)):
        return 3600 if secs is None else 60
    return sa + secs - SLACK - now


def _worker_loop(sleep=time.sleep, clock=time.time):
    sleep(60)
    while True:
        wait = 3600
        try:
            tick(clock())
            wait = _next_wait(clock())
        except Exception as e:
            _log("worker error: %s" % e)
        sleep(max(60, min(3600, wait)))


def start_worker():
    """Idempotent. No-op only when PENDING_INTERVAL is off; the OS job does not stop it (tick dedups)."""
    if config.interval_seconds(config.PENDING_INTERVAL) is None:
        return
    if _WORKER and _WORKER[0].is_alive():
        return
    t = threading.Thread(target=_worker_loop, daemon=True, name="pending-worker")
    _WORKER[:] = [t]
    t.start()


def cli_main(argv):
    config.apply_overrides(_load_json(config.CONFIG_FILE, {}))
    if "--install-scheduler" in argv:
        return sched_install()
    if "--uninstall-scheduler" in argv:
        return sched_uninstall()
    if "--scheduler-status" in argv:
        print(json.dumps(sched_status()))
        return 0
    if "--if-due" in argv:
        print(tick())
        return 0
    if "--dry-run" in argv:
        report = run_once("dry-run")
    else:
        report = run_once(config.PENDING_CLEAN, scheduled=True)
    if "items" not in report:
        print("pending-work: another run holds the lock")
        return 0
    if "--json" in argv:
        print(json.dumps(report))
    else:
        print("pending-work [%s]: %d worktrees/repos, %d tmp, %d deleted, %d would delete, %d refused, %.1fs"
              % (report["mode"], len(report["items"]), len(report["tmp"]), len(report["deleted"]),
                 len(report["would_delete"]), len(report["refused"]), report["duration_s"]))
    return 0
