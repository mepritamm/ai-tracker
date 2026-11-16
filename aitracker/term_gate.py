"""Shared gate for the terminal features (Tiers 1-3).

These routes start processes on the host, and are enabled by default. `HOST=0.0.0.0 make serve`
(LAN/Tailscale — see cli.py's HOST env var) and `make tunnel` are both supported, documented ways
to expose this server beyond loopback, and both require TRACKER_AUTH before the terminal is
usable off-loopback — see allowed() below. A loopback-only `make serve` (the default) needs no
TRACKER_AUTH. Cross-origin requests are still rejected as a belt-and-braces protection.

IMPORTANT: On a server that IS reachable and has a password, anyone with TRACKER_AUTH gets an
unrestricted shell as this OS user.
"""
import ipaddress
import re
from urllib.parse import urlparse

from . import config
from .util import is_loopback_host, origin_matches_host

_LOOPBACK_NAMES = {"localhost"}


def _is_loopback(host):
    """True if `host` can only ever mean "this machine talking to itself". Evaluated against
    the server's *bind* address (config.BIND_HOST) — never a request's peer address, since a
    tunnel terminates locally and its requests also arrive from 127.0.0.1 even though the
    tunnel makes the server reachable from anywhere. Unknown/unparseable input is treated as
    NOT loopback: the safe default is to require auth, not to wave it through."""
    if not host:
        return False
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowed():
    """True if terminal routes may run at all. Terminal is ON by default; set
    TRACKER_TERMINAL=0 to disable. When the server is bound beyond loopback — HOST=0.0.0.0, a
    LAN/Tailscale IP, anything `make tunnel` fronts — TRACKER_AUTH is also required, since
    without it the terminal would hand an unauthenticated, unrestricted shell to anyone who can
    reach the server."""
    if not config.TERMINAL:
        return False
    return bool(config.AUTH) or _is_loopback(config.BIND_HOST)

def _origin_ok(handler):
    """Reject cross-site POSTs. The signed cookie is SameSite=Lax, which already blocks
    cross-site form POSTs, but this is the belt to that braces -- a shell is not a place to
    rely on one mechanism."""
    return origin_matches_host(handler.headers)   # absent Origin = same-origin fetch / curl

def guard(handler):
    """Call first in every terminal route. Returns True if the request may proceed;
    otherwise it has already written the response."""
    if not config.TERMINAL:
        handler._json({"error": "terminal disabled — unset TRACKER_TERMINAL or set it to anything other than 0"}, 403)
        return False
    if not allowed():
        handler._json({"error": "terminal disabled: this server is reachable on the network, so it needs TRACKER_AUTH"}, 403)
        return False
    if not _origin_ok(handler):
        handler._json({"error": "cross-origin refused"}, 403)
        return False
    # DNS-rebinding guard: with no login configured the terminal is allowed only because the
    # server is bound to loopback, and a rebinding page reaches it from loopback with an
    # attacker Host. With TRACKER_AUTH set, the login (a host-scoped cookie) is the protection
    # and tunnel/LAN Hosts are legitimate, so this check does not apply.
    if not config.AUTH and not is_loopback_host(handler.headers.get("Host", "")):
        handler._json({"error": "refused: Host is not loopback"}, 403)
        return False
    return True

def _existing_ancestor(cwd):
    """The nearest EXISTING ancestor directory of a missing `cwd` ("" if the walk reaches "/")."""
    import os
    ancestor = os.path.dirname(cwd)
    while ancestor and ancestor != "/" and not os.path.isdir(ancestor):
        ancestor = os.path.dirname(ancestor)
    return ancestor if ancestor and ancestor != "/" and os.path.isdir(ancestor) else ""


def _recorded(sid, meta=None):
    """(tail_scan_dict_or_None, cwd, branch) for a Claude sid. The cheap tail read is tried
    first; only when it has no cwd (no transcript, or one line > 96 KB) do we fall back to the
    full parse -- `meta` (when the caller IS parse_any) is used instead so it never re-enters."""
    from .providers import claude
    t = None
    path = claude.find_session(sid)
    if path:
        t = claude._tail_scan(path)
    if t and t.get("cwd"):
        return t, t["cwd"], t.get("gitBranch") or ""
    if meta is None:
        from .registry import parse_any
        try:
            meta = (parse_any(sid) or {}).get("meta") or {}
        except Exception:
            meta = {}
    branch = meta.get("gitBranch") or ""
    return t, meta.get("cwd") or "", "" if branch == "HEAD" else branch


def recorded_run_dir(sid, meta=None):
    """(raw, branch): where a Claude session last ran, preferring worktree evidence -- the
    latest `worktree-state` path, else the newest recorded cwd inside a linked worktree, else
    the latest cwd. A later bare-root cwd never beats earlier worktree evidence. Non-Claude
    sids give ("", "")."""
    from .registry import provider_for
    from .util import git_worktree_root
    p = provider_for(sid)
    if p is None or p.prefix != "":
        return "", ""
    t, cwd, branch = _recorded(sid, meta)
    if not cwd:
        return "", ""
    t = t or {}
    wt = t.get("wt")
    if t.get("wt_seen") and isinstance(wt, dict) and wt.get("worktreePath"):
        return wt["worktreePath"], branch
    if t.get("wt_seen"):                         # ExitWorktree: deliberately left
        return cwd, branch
    for d in t.get("cwds") or []:
        top = git_worktree_root(d)[1]
        if top:                                  # the worktree TOP, not a subdir of it
            return top, branch
    return cwd, branch


def session_cwd(sid, resume=False, fast=False):
    """The working directory for a session id, or "" if unknown/gone. Late import: registry
    pulls in every provider, and this module is imported from server at startup.

    S1: the cwd comes from the transcript TAIL (ms) when it has one; the full `parse_any`
    (seconds on a big transcript) is only the fallback.

    With resume=True, a recorded cwd that no longer exists (the session's worktree/folder was
    since removed) walks up via os.path.dirname to the nearest EXISTING ancestor directory and
    returns that instead of "". Verified empirically on claude 2.1.280: `claude --resume <sid>`
    looks the session up by id, not by cwd, so it resumes fine from ANY directory that merely
    exists -- the exact ancestor is cosmetic. Stops and returns "" if the walk's nearest
    existing ancestor is "/" (not a real place to land a shell); the home dir is fine.

    fast=True (the Resume-all preview only) never parses the transcript: it reads the last `cwd` in the
    file's 96 KB tail, else the first one in its head, for a Claude session id; any other id falls back to
    the full parse. open_pty and agent-upgrade keep the default and stay authoritative."""
    import os
    from .registry import provider_for
    try:
        cwd = ""
        if fast:
            from .providers import claude as _cl
            if (provider_for(sid) or object()).prefix == "":
                path = _cl.find_session(sid)
                cwd = (_cl._tail_scan(path).get("cwd") or _cl._session_meta(path).get("cwd")) if path else ""
                if not path:
                    return ""
            else:
                fast = False
        if not fast:
            cwd = _recorded(sid)[1]
    except Exception:
        return ""
    if not cwd:
        return ""
    if os.path.isdir(cwd):
        return cwd
    if not resume:
        return ""
    return _existing_ancestor(cwd)


_REMOVED = ("Worktree `%s` was removed. Open terminal or Resume will offer to recreate it and "
            "continue this same session there. Uncommitted changes from the old worktree "
            "cannot be recovered.")


def terminal_dir(raw):
    """Classify a recorded run dir with file reads only (no git): ("worktree", root, top) for an
    existing linked worktree, ("deleted", root, "") for a removed one, else ("plain", "", "")."""
    import os
    from .util import git_worktree_root, deleted_worktree_root
    if not raw:
        return "plain", "", ""
    if os.path.exists(raw):
        root, top = git_worktree_root(raw)
        return ("worktree", root, top) if root else ("plain", "", "")
    root = deleted_worktree_root(raw)
    return ("deleted", root, "") if root else ("plain", "", "")


def _raw_for(sid, cwd, meta):
    from .registry import term_home
    return term_home(sid, meta)[0] or cwd


def place(sid, cwd, mode, meta=None, token=None):
    """Where a terminal for `sid` lives -> {"shell", "run", "note", "error"} (+ "recreate" for a
    removed worktree). Order (row 12): resolve worktree -> existence check -> placement.
    `cwd` is what the route's session_cwd returned (maybe ""). A worktree session's shell is the
    main checkout root and `run` its worktree top (None for mode "cwd"); a removed worktree
    answers {"recreate": plan} with an error so the route can 409 (E1; nothing is launched, nothing
    written). With the confirmed `token` of that plan the worktree is recreated and the session is
    placed in it. Anything else is today's behaviour: shell = run = cwd."""
    import os
    raw = _raw_for(sid, cwd, meta)
    kind, root, top = terminal_dir(raw)
    if kind == "deleted" and os.path.isdir(root):
        lk = _path_lock(raw) if token else None
        if lk is not None and not lk.acquire(timeout=30):
            return {"shell": "", "run": None, "note": "",
                    "error": "another recreate of this path is still running -- try again"}
        try:
            if token:                      # a concurrent confirm may have just created it (D3)
                kind, root, top = terminal_dir(raw)
                if kind == "worktree":
                    return place(sid, cwd, mode, meta)
            plan, why = _plan(sid, raw, root, meta)
            if plan is None:
                return {"shell": "", "run": None, "note": "", "error": why}
            if token and _check_token(token, sid, plan["path"], plan["branch"], plan["new_branch"],
                                      plan["base"]):
                ok, res = recreate_worktree(plan)
                if not ok:
                    return {"shell": "", "run": None, "note": "", "error": res}
                pl = place(sid, cwd, mode, meta)
                if not pl.get("shell"):
                    return {"shell": "", "run": None, "note": "", "error": "worktree recreated but not usable"}
                from .util import _git_branch
                pl["note"] = "Recreated `%s` on branch `%s`." % (raw, _git_branch(raw))
                return pl
        finally:
            if lk is not None:
                lk.release()
        msg = _REMOVED % raw
        return {"shell": "", "run": None, "note": msg, "error": msg, "recreate": plan}
    if kind == "worktree":
        return {"shell": root, "run": None if mode == "cwd" else top, "note": "", "error": ""}
    if kind == "deleted":
        return {"shell": "", "run": None, "note": "",
                "error": "repository `%s` no longer exists -- resume by hand" % root}
    return {"shell": cwd, "run": cwd, "note": "", "error": ""}


def home_note(sid, cwd, meta=None):
    """The server-owned removed-worktree message ("" otherwise). File reads only."""
    raw = _raw_for(sid, cwd, meta)
    return _REMOVED % raw if terminal_dir(raw)[0] == "deleted" else ""


# --- E1: recreate a removed worktree on one-click confirm (plan v4.2 A2) -------------------------
# The ONLY git writes this app makes; see .claude/rules/conventions.md rule 6 (exception). Everything
# below runs only from a confirmed POST, never on a poll, list or page load.
import hmac
import secrets
import subprocess
import threading
import time

_SECRET = secrets.token_bytes(32)          # per server process: another process's token just re-plans
_TOKEN_TTL = 600
_USED_TOKENS = {}                          # token -> exp, pruned of expired entries on insert
_RECREATE_LOCK = threading.Lock()          # guards _USED_TOKENS and _RECREATE_LOCKS
_RECREATE_LOCKS = {}                       # realpath(target) -> threading.RLock
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _git_allowed(a):
    """The exact argv allowlist (after `git -C <root>`); anything else is a programming error."""
    n = len(a)
    if a[:1] == ("rev-parse",):
        return n == 4 and a[1:3] == ("--verify", "--quiet") and a[3].startswith("refs/")
    if a[:2] == ("worktree", "list"):
        return a == ("worktree", "list", "--porcelain")
    if a[:2] == ("worktree", "prune"):
        return a == ("worktree", "prune")
    if a[:2] == ("worktree", "add"):
        if n == 4:
            return not a[2].startswith("-") and not a[3].startswith("-")
        return n == 6 and a[2] == "-b" and not any(x.startswith("-") for x in a[3:])
    if a[:1] == ("cat-file",):
        return n == 3 and a[1] == "-e" and a[2].endswith("^{commit}")
    if a[:1] == ("check-ref-format",):
        return n == 3 and a[1] == "--branch" and not a[2].startswith("-")
    if a[:1] == ("symbolic-ref",):
        return a == ("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    return False


def _git(root, *args):
    """(returncode, stdout, stderr) of `git -C root <args>` with the git env vars stripped and a
    30 s timeout. Only the allowlisted argv shapes run; there is never a force/delete/reset form."""
    assert _git_allowed(args), "git argv outside the recreate allowlist: %r" % (args,)
    import os
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return r.returncode, r.stdout, r.stderr


def _make_token(sid, path, branch, new_branch, base, exp):
    msg = "%s|%s|%s|%s|%s|%d" % (sid, path, branch, new_branch, base, exp)
    return "%d.%s" % (exp, hmac.new(_SECRET, msg.encode(), "sha256").hexdigest())


def _check_token(token, sid, path, branch, new_branch, base):
    """True (and the token is burned: single use) when `token` was issued by THIS process for exactly
    this plan and has not expired or been used."""
    try:
        exp = int(str(token).partition(".")[0])
    except ValueError:
        return False
    if exp <= time.time():
        return False
    if not hmac.compare_digest(str(token), _make_token(sid, path, branch, new_branch, base, exp)):
        return False
    with _RECREATE_LOCK:
        if token in _USED_TOKENS:
            return False
        now = time.time()
        for k in [k for k, e in _USED_TOKENS.items() if e <= now]:
            del _USED_TOKENS[k]
        _USED_TOKENS[token] = exp
    return True


def _valid_recreate_path(raw, root, sid, meta=None):
    """D4: the path to recreate is the realpath this session's transcript records, lies outside
    root's work tree (or inside root/.claude/worktrees/), has an existing parent, and is not
    `/`, $HOME or root itself."""
    import os
    from .util import _lenient_real
    if not raw or os.path.lexists(raw) or not os.path.isabs(raw):
        return False
    want = _lenient_real(raw)
    rec = recorded_run_dir(sid, meta)[0]
    if not rec or _lenient_real(rec) != want:
        return False
    rroot = os.path.realpath(root)
    if want in (os.sep, os.path.realpath(os.path.expanduser("~")), rroot):
        return False
    if want.startswith(rroot + os.sep) and not want.startswith(os.path.join(rroot, ".claude", "worktrees") + os.sep):
        return False
    return os.path.isdir(os.path.dirname(want))


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _remote_names(root):
    import os
    names = set()
    try:
        names.update(os.listdir(os.path.join(root, ".git", "refs", "remotes")))
    except OSError:
        pass
    for ln in _read(os.path.join(root, ".git", "packed-refs")).splitlines():
        parts = ln.split(" ", 1)
        if len(parts) == 2 and parts[1].startswith("refs/remotes/"):
            names.add(parts[1].split("/")[2])
    return sorted(names)


def _verified_sha(root, ref_or_sha):
    """The commit sha `ref_or_sha` names in the CURRENT repo, else "" (D7: stale shas drop out)."""
    if re.fullmatch(r"[0-9a-f]{40}", ref_or_sha or ""):
        sha = ref_or_sha
    else:
        rc, out, _ = _git(root, "rev-parse", "--verify", "--quiet", ref_or_sha)
        sha = out.strip() if rc == 0 else ""
    if not sha:
        return ""
    return sha if _git(root, "cat-file", "-e", sha + "^{commit}")[0] == 0 else ""


def _default_base(root):
    """(display name, sha) of the default-branch tip: origin/HEAD, else the first existing of
    refs/remotes/*/main, refs/heads/main|master|develop. Never the main checkout's HEAD (D1)."""
    cands = []
    rc, out, _ = _git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip().startswith("refs/"):
        cands.append(out.strip())
    cands += ["refs/remotes/%s/main" % r for r in _remote_names(root)]
    cands += ["refs/heads/main", "refs/heads/master", "refs/heads/develop"]
    for ref in cands:
        sha = _verified_sha(root, ref)
        if sha:
            return re.sub(r"^refs/(heads|remotes)/", "", ref), sha
    return "", ""


def _worktree_list(root):
    """[{"path", "branch", "prunable"}] from `git worktree list --porcelain` (E1: callers ignore the
    target's own entry and any prunable one)."""
    from .util import _lenient_real
    rc, out, _ = _git(root, "worktree", "list", "--porcelain")
    ents, cur = [], None
    for ln in (out if rc == 0 else "").splitlines() + [""]:
        if not ln:
            if cur:
                ents.append(cur)
            cur = None
        elif ln.startswith("worktree "):
            cur = {"path": _lenient_real(ln[9:]), "branch": "", "prunable": False}
        elif cur is not None and ln.startswith("branch refs/heads/"):
            cur["branch"] = ln[len("branch refs/heads/"):]
        elif cur is not None and ln.startswith("prunable"):
            cur["prunable"] = True
    return ents


def _last_reflog_sha(g):
    for ln in reversed(_read(g + "/logs/HEAD").splitlines()):
        parts = ln.split(" ", 2)
        if len(parts) > 1 and re.fullmatch(r"[0-9a-f]{40}", parts[1]):
            return parts[1]
    return ""


def _branch_ok(root, name):
    return bool(name) and _git(root, "check-ref-format", "--branch", name)[0] == 0


def _plan(sid, raw, root, meta=None):
    """(plan | None, reason). Git READS only; writes nothing."""
    import os
    from .util import _admin_dir_for, _lenient_real
    if not _valid_recreate_path(raw, root, sid, meta):
        return None, "cannot recreate `%s`: not the session's recorded folder, or its parent is missing" % raw
    rroot = os.path.realpath(root)
    target = _lenient_real(raw)
    g = _admin_dir_for(rroot, raw)
    branch = recorded_run_dir(sid, meta)[1]
    if branch == "HEAD":                                  # E5: detached = no branch
        branch = ""
    if not branch and g:
        head = _read(g + "/HEAD").strip()
        if head.startswith("ref: refs/heads/"):
            branch = head[len("ref: refs/heads/"):]
    if branch and not _branch_ok(rroot, branch):
        branch = ""
    ents = _worktree_list(rroot)
    prune_n = sum(1 for e in ents if e["prunable"]) if g else 0
    sid8 = re.sub(r"[^A-Za-z0-9]", "", sid)[:8] or "session"
    new_branch, base, kind, other, default = "", "", "", "", ""
    if branch and _git(rroot, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch)[0] == 0:
        # E1: the target's own (dead) entry and any prunable entry do not count as "in use".
        other = next((e["path"] for e in ents
                      if e["branch"] == branch and e["path"] != target and not e["prunable"]), "")
        kind = "branch-tip" if other else "branch"
        if other:
            base = _verified_sha(rroot, "refs/heads/" + branch)
    else:
        kind = "last-commit"
        base = _verified_sha(rroot, _last_reflog_sha(g)) if g else ""
        if not base:
            kind = "default-branch"
            default, base = _default_base(rroot)
            if not base:
                return None, "no base branch found for `%s` -- recreate the worktree by hand" % raw
    if kind != "branch":
        stem = "%s-cont-%s" % (branch or "worktree-" + os.path.basename(target), sid8)
        new_branch, n = stem, 1
        while (not _branch_ok(rroot, new_branch)
               or _git(rroot, "rev-parse", "--verify", "--quiet", "refs/heads/" + new_branch)[0] == 0):
            n += 1
            new_branch = "%s-%d" % (stem, n)
            if n > 50:
                return None, "no free branch name for `%s`" % raw
    b = branch or "worktree-" + os.path.basename(target)
    if kind == "branch":
        text = "Recreate on branch `%s` (your work on %s is intact)." % (b, b)
    elif kind == "branch-tip":
        text = ("`%s` is checked out at `%s`; recreate on new branch `%s` from %s's tip."
                % (b, other, new_branch, b))
    elif kind == "last-commit":
        text = ("Branch `%s` was deleted; recreate on new branch `%s` from its last commit `%s`."
                % (b, new_branch, base[:7]))
    else:
        text = ("Branch `%s` was deleted (likely after merge) and its last commit is not recoverable "
                "here; recreate on new branch `%s` from `%s` %s. Commits from %s are only present "
                "if they were merged into `%s`." % (b, new_branch, default, base[:7], b, default))
    if prune_n:
        text += (" Also clears %d stale worktree registration(s) (their old commit pointers are lost)."
                 % prune_n)
    exp = int(time.time()) + _TOKEN_TTL
    return {"path": raw, "root": rroot, "branch": branch, "new_branch": new_branch, "base": base,
            "base_kind": kind, "summary": text[:300], "prune": bool(g), "expires": exp,
            "token": _make_token(sid, raw, branch, new_branch, base, exp)}, ""


def recreate_plan(sid, raw, root, meta=None):
    """The plan dict {path, root, branch, new_branch, base, base_kind, summary, token, expires, prune}
    for recreating removed worktree `raw`, or None. Git READS only; nothing is written."""
    return _plan(sid, raw, root, meta)[0]


def _git_add(plan):
    """The one write: `worktree add <path> <B>` or `worktree add -b <new> <path> <base>`. -> (rc, err)."""
    if plan["new_branch"]:
        rc, _o, err = _git(plan["root"], "worktree", "add", "-b", plan["new_branch"], plan["path"], plan["base"])
    else:
        rc, _o, err = _git(plan["root"], "worktree", "add", plan["path"], plan["branch"])
    return rc, err


def _path_lock(path):
    """The per-path lock (re-entrant: place() holds it across plan + token + recreate_worktree)."""
    import os
    with _RECREATE_LOCK:
        return _RECREATE_LOCKS.setdefault(os.path.realpath(path), threading.RLock())


def recreate_worktree(plan):
    """Execute a plan whose token the caller already checked -> (True, path) or (False, err).
    Per-path lock; never writes into an occupied path; D3/E3: a live worktree of root at the path,
    on any branch, counts as success."""
    import os
    from .util import git_worktree_root, _admin_dir_for
    path, root = plan["path"], plan["root"]

    def live():
        return os.path.exists(path) and git_worktree_root(path)[0] == root

    lk = _path_lock(path)
    if not lk.acquire(timeout=30):
        return False, "another recreate of this path is still running -- try again"
    try:
        if live():
            return True, path
        if os.path.lexists(path):
            return False, "path occupied by a non-worktree directory; move it or resume elsewhere"
        if plan.get("prune") and _admin_dir_for(root, path):
            _git(root, "worktree", "prune")
        rc, err = _git_add(plan)
        if rc == 0 or live():
            return True, path
        return False, ("git worktree add failed: %s" % (err or "").strip())[:300]
    finally:
        lk.release()


def recreate_forbidden(handler):
    """True for a request that must never write to the repo: proxied/tunnel or read-only."""
    from . import server
    if server._proxy_header(handler):
        return True
    ro = getattr(handler, "_readonly", None)
    return bool(ro()) if callable(ro) else False


REFUSAL_MARKER = "is currently running as a background agent (bg)"
"""Substring of the CLI's OLD verbatim refusal (docs/claude-resume-command-matrix.md), kept
for backward compat -- existing tests reference this name directly, and an older `claude`
binary on another machine may still emit exactly this wording:

    Session <id> is currently running as a background agent (bg). Use `claude agents`
    to find and attach to it, or add --fork-session to branch off a copy.

Deliberately just this phrase, not the whole message: it never contains the resumed
`<id>` (which the caller doesn't have handy to interpolate) and isn't a plausible line-
wrap boundary, so it's safe to match on its own -- see looks_like_bg_refusal(). This was
the ONE seam that owned the exact wording -- see BG_REFUSAL_MARKERS below for why it's
no longer the only one."""

BG_REFUSAL_MARKERS = (
    REFUSAL_MARKER,
    "is running as a background session",
)
"""Every wording of the CLI's "still running elsewhere" refusal that `looks_like_bg_refusal()`
matches. REFUSAL_MARKER (above) is the LEGACY wording; the CURRENT `claude` CLI instead prints
(verbatim, from a real capture):

    Session <id> is running as a background session (<short-id>). Run `claude attach
    <short-id>` to open it, or `claude stop <short-id>` first to resume it here. Add
    --fork-session to branch off a copy instead.

This is not a cosmetic rewrite -- the two messages describe DIFFERENT recoveries. The legacy
CLI only offered `claude agents` (an interactive picker, no scriptable argv) or
`--fork-session`; the current CLI instead names a `claude attach <id>` command we CAN drive
non-interactively -- see attach_target()/attach_argv() below. Both strings are kept in this
tuple, not just swapped, because a wording change silently disables whichever backstop keyed
off the old string -- looks_like_bg_refusal()'s docstring predicted exactly this ("degrades to
no retry at all"), and that prediction came true (the backstop went silently dead) before it
was caught here. Matching a tuple of known wordings, instead of one pinned string, is the
mitigation: a NEXT wording change still degrades gracefully (no match, no retry, no crash),
but this file no longer bets its only recovery path on one exact sentence."""

MISSING_TRANSCRIPT_MARKER = "No conversation found with session ID:"
"""Verbatim prefix of the CLI's message when `--resume <sid>` can't find ANY transcript
for `sid` (docs/claude-resume-command-matrix.md). Unlike the bg-agent refusal, the CLI
does not exit here -- it prints this and then silently falls through into a BRAND-NEW
session in the current directory. So this is a warn-but-still-open signal, not a retry
trigger -- see looks_like_missing_transcript()."""


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?<>=]*[ -/]*[@-~]"     # CSI -- incl. the \x1b[<n>G cursor jumps below. The ':'
                                          # is required: ITU sub-parameter SGR (\x1b[38:2:255:0:0m,
                                          # \x1b[4:3m curly underline) is real output, and without
                                          # it the whole sequence spilled through as "38:2:255:0:0m".
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC  -- title sets etc.
    r"|\x1b[P^_X][^\x1b]*(?:\x1b\\|\x07)"   # DCS / PM / APC / SOS -- terminated strings
    r"|\x1b[ -/]*[0-~]"                   # Fp/Fs/Fe + charset escapes: ESC 7, ESC 8, ESC ( B, ...
                                          # (0x30-0x7E finals -- NOT just @-Z: ESC 7 / ESC 8 are
                                          # the first bytes a real `claude --resume` emits, and a
                                          # narrower class left a stray "7"/"8" behind that read as
                                          # printable text)
)

_ANSI_PARTIAL_TAIL_RE = re.compile(
    r"\x1b(?:\[[0-9;:?<>=]*[ -/]*"       # a CSI whose final byte hasn't arrived yet
    r"|\][^\x07\x1b]*"                  # an OSC still waiting for its BEL / ST
    r"|[P^_X][^\x1b]*"                   # a DCS/PM/APC/SOS still waiting for its ST
    r"|[ -/]*"                            # ESC + intermediates, final byte not here yet
    r")?$"
)
"""A TRAILING, still-incomplete escape sequence -- dropped before matching rather than left to be
half-eaten by _ANSI_RE.

This is the same defect as the one _ANSI_RE's ESC 7/ESC 8 comment describes, one level down, and
it is the reason it matters: **a pty master read is capped at 1024 bytes**, so Ink's init frame
never arrives as one chunk, and `_resume_backstop` re-scans its buffer after EVERY chunk. Whenever
a chunk boundary falls inside an escape sequence -- probability ~(N-1)/N for N-byte sequences, so
usually -- the partial tail survives stripping as printable junk: b'...\x1b[38' normalises to
'38', a buffer ending on a bare b'\x1b' normalises to '\x1b' (str.split() does NOT treat ESC as
whitespace). Measured: 26 of the 42 prefixes of the captured init burst normalised to non-empty.

That junk latched `_resume_backstop`'s settle clock at t~=0.06s instead of at first real text, so
`starting` cleared at ~0.57s and the refusal painted at 2.05s after all -- the exact bug the flag
exists to prevent, reproduced end to end. Stripping the partial tail makes normalisation a
function of the CONTENT rather than of where the reader happened to slice the stream."""
"""Every escape sequence stripped (to a SPACE, never to nothing) before marker matching.

MEASURED, not assumed: `claude --resume <bg-id>` on a real pty renders the refusal through
Ink, which does not emit spaces between words -- it jumps the cursor to each word's column.
The raw bytes are literally:

    Session\x1b[9G<id>\x1b[46Gis\x1b[49Gcurrently\x1b[59Grunning\x1b[67Gas\x1b[70Ga\r\r\n
    background\x1b[12Gagent\x1b[18G(bg).\x1b[24GUse ...

so REFUSAL_MARKER ("is currently running as a background agent (bg)") is NOT a substring of
those bytes at all, whitespace-collapsed or not -- the old normalisation only handled the
`\r\n` wraps, which is why the pinned plain-text capture in the tests passed while the live
terminal never once fired the backstop. Substituting a space keeps the words apart; deleting
the escapes would fuse "currently" and "running" into one token and fail just as silently."""


def _normalize_output(output) -> str:
    """`bytes` (or `str`) captured from a child's pty -> one whitespace-collapsed line with
    escape sequences replaced by spaces, so neither the terminal's own line-wrapping nor
    Ink's column-jump rendering (see _ANSI_RE) can hide a REFUSAL_MARKER/
    MISSING_TRANSCRIPT_MARKER match."""
    # None/absent output normalizes to "" rather than raising. Every caller here is a
    # `looks_like_*`/`attach_target` predicate on a best-effort read of a child's pty, and a
    # predicate that throws on "nothing arrived yet" would take down the backstop thread that
    # is the ONLY thing rescuing a refused resume -- the exact failure this seam exists to fix.
    if output is None:
        return ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    # Drop a trailing half-arrived escape FIRST -- see _ANSI_PARTIAL_TAIL_RE. Doing it after
    # _ANSI_RE would be too late: _ANSI_RE's last branch would already have eaten the ESC and
    # spilled the rest as text.
    output = _ANSI_PARTIAL_TAIL_RE.sub("", output)
    return " ".join(_ANSI_RE.sub(" ", output).split())


_BG_RUNNING_IN_BG_RE = re.compile(r"is running in the background \([0-9a-f]{4,}\)\.")
"""CLI 2.1.318's third wording: `${title} is running in the background (<job short>).` -- the title is
free text, so only the tail is matched, and only with a hex job id in parentheses and the full stop:
"the dev server is running in the background (PID 4242)." is ordinary prose and must not match."""


def looks_like_bg_refusal(output) -> bool:
    """True if `output` (raw bytes/str captured from a `claude --resume` child) contains
    ANY of BG_REFUSAL_MARKERS -- the ONE signal Option C's backstop (term_vt.py) uses to
    retry once with --fork-session. resume_argv() no longer guesses proactively at all
    (see its docstring), so this is now the ONLY thing that decides a fork for the
    in-browser PTY tier, not a safety net for a fast path that missed. This USED to match
    a single pinned string, and a CLI wording change silently degraded that to no retry at
    all -- that prediction came true (see BG_REFUSAL_MARKERS): the CLI switched from
    "is currently running as a background agent (bg)" to "is running as a background
    session", and the single-string match went silently dead. Matching the tuple is the
    mitigation, not a fix that rules out recurrence -- a THIRD wording still degrades the
    same way (a bare refusal shown to the user, no retry) rather than raising."""
    normalized = _normalize_output(output)
    return any(marker in normalized for marker in BG_REFUSAL_MARKERS) or bool(_BG_RUNNING_IN_BG_RE.search(normalized))


def looks_like_missing_transcript(output) -> bool:
    """True if `output` contains the CLI's "no conversation found" message -- see
    MISSING_TRANSCRIPT_MARKER. Used to warn the user that what just opened is a brand-new
    conversation, not the transcript they clicked Resume on."""
    return MISSING_TRANSCRIPT_MARKER in _normalize_output(output)


def resume_argv(sid):
    """The argv for `claude --resume <sid>`. Deliberately does NOT append
    `--fork-session` proactively any more -- both terminal tiers (term_vt.open_pty uses
    the list directly; term_launch.open_terminal passes it into build_script) call this
    ONE function, so whatever it decides can't drift between them (conventions rule 4);
    what changed is what it decides.

    CORRECTED: this used to append --fork-session whenever the session's own TRANSCRIPT
    claimed to be a background agent (sessionKind == "bg" or entrypoint == "sdk-cli" --
    providers/claude.py's `_is_bg_agent`, which still drives the unrelated sidebar 🤖
    badge, just not this any more). That was measured live and found OVER-BROAD: a
    session keeps sessionKind == "bg" in its transcript forever, even long after `claude`
    itself has deregistered it as a background agent -- and once deregistered, a plain
    `claude --resume <sid>` opens it normally, no refusal at all. Forking pre-emptively in
    that case handed the user a COPY under a brand-new session id when a plain resume
    would have reopened their actual conversation -- silently losing continuity, which is
    worse than the refusal this file's backstops already recover from automatically.

    The signal that actually tracks the refusal is the LIVE `claude agents --json`
    registry (an id is forkable only while that command still lists it), not the
    transcript -- but timed on this machine, `claude agents --json` took 750-960ms per
    call across 5 consecutive runs, with no warm-start speedup between them. That is too
    slow to shell out for synchronously on EVERY `mode="resume"` open -- not just
    background-agent ones, since this function can't know which a session is without
    asking. So the proactive guess is dropped entirely; correctness now rests solely on
    the two backstops that already run unconditionally, independently of anything decided
    here:
      - term_vt.py's `_resume_backstop` (Tier 2, in-browser PTY): watches the just-
        spawned child's own output for REFUSAL_MARKER and retries once with
        --fork-session -- see looks_like_bg_refusal() below.
      - term_launch.py's `build_script` (Tier 3, external Terminal.app/iTerm): always
        wraps a resume argv lacking --fork-session in a shell-level
        `(<resume> || <resume> --fork-session)` fallback, so a refusal falls back with no
        ai-tracker process even watching.
    The cost of dropping the fast path is a visible refusal flash plus one respawn on a
    genuine background-agent resume, and NOTHING on every other session -- trading a
    recoverable, visible delay for never silently mis-forking a live conversation.

    `--fork-session` (whichever path appends it) branches a COPY of the agent's
    conversation -- it does not attach to the actually-running agent. Claude Code's
    refusal message also suggests `claude agents`, which WOULD attach to the live
    session, but that's an interactive picker with no argv that could drive it
    non-interactively. Between "refuse to open a terminal at all" and "open one on a
    deliberate copy", this picks the copy -- and callers should say so where they surface
    the result (a fork was the trade-off, not a mistake).

    GATEWAY: argv[0] follows the gateway the session LAST RAN ON (its latest recorded
    model, via gateway.gateway_of), NOT the configured default `config.GATEWAY` -- a session
    that ran through OpenRouter must resume via the configured OpenRouter launcher, and plain
    `claude` would break it. Raises gateway.GatewayError when that launcher isn't usable (callers
    report it; it never degrades to `claude`). A transcript lookup failure alone falls back to "claude"."""
    return [_launcher_for(sid), "--resume", sid]


def _launcher_for(sid):
    """argv[0] for resuming `sid`, from its LATEST real model: the 96 KB tail first (O(1)); a full
    parse only when the tail holds no assistant turn. Never the capped list. gateway.GatewayError
    propagates (the caller reports it) -- it must never degrade to plain `claude`, which would
    resume an OpenRouter session on Anthropic."""
    from . import gateway
    try:
        from .providers import claude as _claude
        path = _claude.find_session(sid)
        model = (_claude._tail_scan(path).get("model") or "") if path else ""
        if path and not model:
            model = ((_claude.parse_session(path) or {}).get("meta") or {}).get("model") or ""
    except Exception:
        return "claude"                    # lookup failure only; never reached for a gateway error
    return gateway.launcher(gateway.gateway_of(model))   # may raise gateway.GatewayError


_ATTACH_HINT_RE = re.compile(r"claude attach ([0-9a-fA-F]{4,})")
"""Pulls candidate short session ids out of the CURRENT CLI's own refusal hint (see
BG_REFUSAL_MARKERS) -- e.g. "Run `claude attach e30d3b6a` to open it" normalizes (per
_normalize_output(), which leaves backticks untouched -- they aren't an escape sequence,
so `claude attach e30d3b6a` survives normalization character-for-character; verified by
calling _normalize_output() on a real capture rather than assumed) to a plain substring
containing "claude attach e30d3b6a", which this matches directly.

Constrained to `[0-9a-fA-F]{4,}` -- hex only -- because real session ids (confirmed
against actual filenames under `~/.claude/projects/*/*.jsonl`, e.g.
"e30d3b6a-046e-483b-b0f5-e0a1d692abfa.jsonl") are lowercase-hex UUIDs, and their short
form is just a hex prefix. A looser `[0-9a-zA-Z_-]*` class previously let this regex
absorb ANY word after "claude attach" -- e.g. "Run claude attach my-session-name-here
now" parsed out "my-session-name-here" as if it were a real id. Hex-only closes that.

This regex alone does NOT decide the attach target any more -- a MATCH here is only a
CANDIDATE. See attach_target()'s cross-check: the pane this is scraped from is a
terminal replaying a live Claude session, and that session's own transcript can itself
contain text that QUOTES a refusal for a totally different session (e.g. a prior
attach attempt shown in scrollback, or the assistant discussing this very feature).
Trusting the first hex token found after "claude attach" -- with no check against what
the user actually clicked -- let a replayed/quoted refusal for session A silently attach
the user into session B's live agent while the UI showed no signal anything was
wrong (no `⑂` chip on the attach path). The fix is entirely in attach_target(): only a
token that is a genuine prefix of the clicked `sid` is ever accepted."""


def attach_target(output, sid="") -> str:
    """The short session id to hand to `claude attach`, or "" if none can be determined
    or verified.

    SECURITY: `output` is scraped from a pane showing a live terminal, which is a Claude
    session that can itself print or replay text quoting a `claude attach <token>` hint
    for a DIFFERENT session (scrollback, a pasted transcript, the assistant discussing
    this feature, ...). A scraped token is therefore never trusted on its own -- it is
    accepted ONLY when it cross-checks against `sid`, the session id the user actually
    clicked:

      1. If `sid` is non-empty, scan ALL `_ATTACH_HINT_RE` matches in the normalized
         `output` (not just the first -- a later match can be the CORRECT one when an
         earlier one is a stale/unrelated hint) and return the first token that is a
         case-insensitive prefix of `sid` (`sid.lower().startswith(token.lower())`;
         session ids are hex-ish UUIDs whose short form is a hex prefix of the full id,
         so this is exactly the relationship a genuine hint has to its session).
      2. If no candidate passes that check, fall back to `sid[:8]` -- the same short
         form the CLI itself prints alongside the full id in a genuine refusal for THIS
         session, e.g. "(e30d3b6a)" for full id "e30d3b6a-046e-...".
      3. If `sid` is empty/None, there is nothing to cross-check a scraped token
         against, so an unverifiable hint is REFUSED rather than trusted -- return "".
         The caller falls back to plain --fork-session in that case, which is safe (it
         only ever produces a copy of the session the user asked for, never someone
         else's live agent); attaching to an unverified scraped id is not.

    Returns "" -- never raises -- when nothing can be verified (e.g. `output` is the
    LEGACY refusal, which carries no attach hint at all, and no `sid` was supplied
    either)."""
    normalized = _normalize_output(output)
    if sid:
        sid_lower = sid.lower()
        for match in _ATTACH_HINT_RE.finditer(normalized):
            token = match.group(1)
            if sid_lower.startswith(token.lower()):
                return token
        return sid[:8]
    return ""


def attach_argv(target):
    """The argv for `claude attach <target>`, mirroring resume_argv() above -- both are
    bare `"claude"` (attach targets an already-running process, so the launcher/gateway
    never applies). Returns [] if `target` is falsy, so
    a caller that got "" from attach_target() can check truthiness of ONE thing (the argv)
    rather than re-checking the target it already asked for."""
    if not target:
        return []
    return ["claude", "attach", target]
