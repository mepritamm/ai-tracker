import glob, json, os, re, time
from ..config import LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import _dur, _names, _short_title, _first_line, _window, _iso_epoch, _git_branch, cmd_kind, TEST_RE, COMMIT_MSG_RE, collect_prs, prs_sorted, pr_worked
from ..overview import build_overview
from ..store import load_titles, load_tasks
from .base import Provider


def _augment_dirs():
    """Auggie's indexed workspace roots, longest (most specific) first."""
    try:
        s = json.load(open(os.path.join(config.AUGMENT_DIR, "settings.json"), encoding="utf-8"))
        return sorted([d for d in (s.get("indexingAllowDirs") or []) if isinstance(d, str)],
                      key=len, reverse=True)
    except (OSError, ValueError):
        return []


def _augment_cwd():
    dirs = _augment_dirs()
    return dirs[0] if dirs else ""


def _auggie_ide_cwd(d):
    """Auggie records the session's real working dir in each request's IDE state
    node — the analog of Claude's per-session `cwd`. Take the most recent one."""
    cwd = ""
    for m in d.get("chatHistory") or []:
        for rn in (m.get("exchange") or {}).get("request_nodes") or []:
            ide = rn.get("ide_state_node") if isinstance(rn, dict) else None
            if not isinstance(ide, dict):
                continue
            term = ide.get("current_terminal") or {}
            c = (term.get("current_working_directory")
                 or ide.get("repository_root") or ide.get("folder_root"))
            if isinstance(c, str) and c:
                cwd = c   # latest exchange wins
    return cwd


def _auggie_cwd(file_paths):
    """Fallback when a session has no IDE-state cwd: pick the indexed root that
    contains this session's changed files, else the default indexed root."""
    dirs = _augment_dirs()
    for fp in file_paths:
        for d in dirs:
            if isinstance(fp, str) and (fp == d or fp.startswith(d + os.sep)):
                return d
    return dirs[0] if dirs else ""


_ASTATE = {"COMPLETE": "completed", "COMPLETED": "completed", "DONE": "completed",
           "IN_PROGRESS": "in_progress", "STARTED": "in_progress"}


def _auggie_all():
    """uuid -> task dict for every task file (roots + sub-tasks), with _mtime."""
    m = {}
    for f in glob.glob(os.path.join(config.AUGMENT_DIR, "task-storage", "tasks", "*")):
        try:
            t = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(t, dict) and t.get("uuid"):
            t["_mtime"] = os.path.getmtime(f)
            m[t["uuid"]] = t
    return m


def _auggie_resolve(root, allmap, seen=None):
    """A root's subTasks are UUID references to other task files — flatten them
    (depth-first, cycle-safe) into todo dicts."""
    seen = seen if seen is not None else set()
    out = []
    for ref in root.get("subTasks") or []:
        if not isinstance(ref, str) or ref in seen:
            continue
        seen.add(ref)
        st = allmap.get(ref)
        if not st:
            continue
        name = st.get("name") or st.get("description") or ""
        out.append({"content": name,
                    "status": _ASTATE.get((st.get("state") or "").upper(), "pending"),
                    "activeForm": name})
        out.extend(_auggie_resolve(st, allmap, seen))
    return out


_AUGGIE_LIST_CACHE = {}


def _auggie_first_request(chat):
    for m in chat or []:
        r = (m.get("exchange") or {}).get("request_message")
        if isinstance(r, str) and r.strip() and not r.lstrip().startswith("<"):
            return " ".join(r.split())[:200]
    return ""


def _auggie_todos_for(root_uuid):
    if not root_uuid:
        return []
    allmap = _auggie_all()
    root = allmap.get(root_uuid)
    return _auggie_resolve(root, allmap) if root else []


def list_auggie():
    """Auggie CLI sessions live at ~/.augment/sessions/<id>.json (the local transcripts)."""
    titles = load_titles()
    default_cwd = _augment_cwd()
    out = []
    for f in glob.glob(os.path.join(config.AUGGIE_SESSIONS, "*.json")):
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        hit = _AUGGIE_LIST_CACHE.get(f)
        if hit and hit[0] == mt:
            e = hit[1]
        else:
            try:
                d = json.load(open(f, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sid = d.get("sessionId") or os.path.basename(f)[:-5]
            req = _auggie_first_request(d.get("chatHistory"))
            e = {"sid": sid,
                 "title": d.get("customTitle") or (_short_title(req) if req else "Auggie session"),
                 "prompt": req,
                 "cwd": _auggie_ide_cwd(d),   # real per-session working dir (like Claude)
                 "mtime": _iso_epoch(d.get("modified")) or mt}
            _AUGGIE_LIST_CACHE[f] = (mt, e)
        gid = "auggie:" + e["sid"]
        cwd = e.get("cwd") or default_cwd
        out.append({
            "id": gid, "project": os.path.basename(cwd) if cwd else "Augment", "cwd": cwd,
            "title": titles.get(gid) or e["title"],
            "prompt": e["prompt"], "source": "auggie", "mtime": e["mtime"],
        })
    return out


def parse_auggie(session_id):
    f = os.path.join(config.AUGGIE_SESSIONS, session_id + ".json")
    if not os.path.isfile(f):
        return None
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    requests, narrative, files, cmds, reads, commits = [], [], {}, [], {}, []
    asks = {}         # tool_use_id -> ask-user decision {t, open, answer, questions} (parity with Claude)
    prs = {}          # url -> entry : PR/MR links touched this session (parity with Claude)
    pr_creates = []   # exchange indices where a PR-create ran — Auggie logs no output URL, so we
    pr_first_ex = {}  # url -> exchange it first appeared in → attribute "created" by order, below
    tok_in = tok_out = 0
    def _cprs(text, narr=False):  # collect PRs + note which exchange each URL first showed up in
        before = set(prs)
        collect_prs(prs, text, ts, narr=narr)
        for u in prs:
            if u not in before:
                pr_first_ex.setdefault(u, i)
    for i, m in enumerate(d.get("chatHistory") or []):
        ex = m.get("exchange") or {}
        ts = m.get("finishedAt")
        for rn in ex.get("request_nodes") or []:              # the user's answer to a prior ask-user lands here
            trn = rn.get("tool_result_node") if isinstance(rn, dict) else None
            if isinstance(trn, dict) and trn.get("tool_use_id") in asks:
                c = trn.get("content") or ""
                asks[trn["tool_use_id"]]["answer"] = re.sub(r"^User responded:\s*", "", c).strip()[:2000]
                asks[trn["tool_use_id"]]["open"] = False
        for rn in ex.get("response_nodes") or []:
            tu = rn.get("token_usage")
            if isinstance(tu, dict):                # tokens: mirror Claude (input + cache)
                tok_in += ((tu.get("input_tokens") or 0) + (tu.get("cache_read_input_tokens") or 0)
                           + (tu.get("cache_creation_input_tokens") or 0))
                tok_out += tu.get("output_tokens") or 0
            call = rn.get("tool_use")               # commands/reads, from Auggie's tools
            if isinstance(call, dict):
                inp = call.get("input_json")
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except ValueError:
                        inp = {}
                inp = inp if isinstance(inp, dict) else {}
                name = call.get("tool_name")
                if name and "create_pull_request" in name:   # MCP PR creation in this exchange
                    pr_creates.append(i)
                if name == "launch-process" and inp.get("command"):   # ~ Claude's Bash
                    c = inp["command"]
                    k = cmd_kind(c)
                    cmds.append({"id": call.get("tool_use_id"), "t": ts, "cmd": c[:200],
                                 "kind": k, "ok": True})   # Auggie stores no exit status
                    if re.search(r"\bpr\s+create\b", c):
                        pr_creates.append(i)
                    _cprs(c)                              # a command's PR ref alone isn't "worked on"
                    if k == "commit":
                        mm = COMMIT_MSG_RE.search(c)
                        commits.append({"t": ts, "msg": (mm.group(2) if mm else c)[:120]})
                elif name == "view" and inp.get("path") and inp.get("type") != "directory":
                    reads[inp["path"]] = ts           # ~ Claude's Read
                elif name == "ask-user":              # Auggie's user-question tool (~ Claude's AskUserQuestion)
                    opts = [o[:120] for o in (inp.get("suggested_responses") or []) if isinstance(o, str)]
                    asks[call.get("tool_use_id")] = {"t": ts, "open": True, "answer": "",
                                                     "questions": [{"q": (inp.get("question") or "")[:500],
                                                                    "header": "", "options": opts}]}
        r = ex.get("request_message")
        if isinstance(r, str) and r.strip() and not r.lstrip().startswith("<"):
            requests.append({"t": ts, "text": " ".join(r.split())[:300]})
            _cprs(r)
        resp = ex.get("response_text")
        if isinstance(resp, str) and resp.strip():
            narrative.append({"t": ts, "text": resp.strip()[:NARRATION_CAP]})
            _cprs(resp, narr=True)                        # PR the assistant narrates about (shown if same-repo)
        for cf in m.get("changedFiles") or []:
            p = cf if isinstance(cf, str) else (cf.get("path") or cf.get("filePath") or cf.get("file"))
            if p:
                fe = files.setdefault(p, {"path": p, "ops": 0, "created": False})
                fe["ops"] += 1
                fe["last"] = ts
    # Auggie logs no command output, and a created PR's URL only appears in a later narration
    # line — so tie each `gh pr create` to the first new PR URL at or after its exchange.
    for cx in sorted(pr_creates):
        cand = sorted((u for u, fx in pr_first_ex.items() if fx >= cx and not prs[u]["created"]),
                      key=lambda u: pr_first_ex[u])
        if cand:
            prs[cand[0]]["created"] = True
    cwd = _auggie_ide_cwd(d) or _auggie_cwd(list(files.keys()))   # real cwd, like Claude's
    branch = _git_branch(cwd)
    tests = [c for c in cmds if c["kind"] == "test"]
    todos = _auggie_todos_for(d.get("rootTaskUuid"))
    done = sum(1 for x in todos if x["status"] == "completed")
    ip = next((x for x in todos if x["status"] == "in_progress"), None)
    gid = "auggie:" + session_id
    title = (load_titles().get(gid) or d.get("customTitle")
             or (_short_title(requests[0]["text"]) if requests else "Auggie session"))
    latest = narrative[-1]["text"] if narrative else ""
    so = []
    if files:
        so.append("touched %d file(s)" % len(files))
    if cmds:
        so.append("ran %d command(s)" % len(cmds))
    if todos:
        so.append("%d/%d tasks done" % (done, len(todos)))
    if requests:
        so.append("%d exchange(s)" % len(requests))
    return {
        "meta": {"cwd": cwd, "title": title, "source": "auggie", "entrypoint": "auggie",
                 "gitBranch": branch,
                 "model": ((d.get("chatHistory") or [{}])[-1].get("exchange") or {}).get("model_id") or ""},
        "todos": todos,
        "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
        "reads": [{"path": p, "t": t} for p, t in
                  sorted(reads.items(), key=lambda kv: kv[1] or "", reverse=True)],
        "commands": cmds[-60:][::-1],
        "commits": commits[::-1],
        "tests": tests[::-1],
        "requests": requests, "agents": [], "agents_bg": [], "shells": [],
        # open decisions first, then most-recent — parity with Claude's AskUserQuestion panel
        "decisions": sorted(asks.values(), key=lambda a: (a["open"], a["t"] or ""), reverse=True),
        "prs": [p for p in prs_sorted(prs) if pr_worked(p, cwd)],   # created or worked-on, not prompt-only references
        "narrative": narrative[::-1],   # full, newest-first; /api/session pages it, /api/narration serves the tail
        "message": latest[:2000],
        "tokens": {"in": tok_in, "out": tok_out},
        "counts": {"done": done, "todos": len(todos), "created": 0, "edited": len(files),
                   "read": len(reads), "commits": len(commits), "tests": len(tests),
                   "tests_failed": 0, "errors": 0, "agents": 0, "searches": 0},
        "overview": {
            "where": os.path.basename(cwd) if cwd else "Augment",
            "goal": requests[-1]["text"] if requests else "",
            "now": ("▶ " + ip["content"]) if ip else (_first_line(latest) if latest else title),
            "now_kind": "todo" if ip else ("narration" if latest else ""),   # panel the "now" click jumps to
            "sofar": "; ".join(so).capitalize() if so else "No activity recorded yet.",
            "commits": [cm["msg"] for cm in commits[:6]],
        },
        "mtime": _iso_epoch(d.get("modified")) or os.path.getmtime(f),
        "now": time.time(),
    }


def _score_segments(segs, terms, ql):
    """Count keyword hits across (text, is_user) segments; require every term.
    Returns (count, snippet, hit_in_user_prompt) — snippet prefers a user hit."""
    count = 0
    user_snip = any_snip = None
    seen = set()
    for text, is_user in segs:
        tl = text.lower()
        hit = [t for t in terms if t in tl]
        if not hit:
            continue
        for t in hit:
            count += tl.count(t)
            seen.add(t)
        w = _window(text, ql if ql in tl else hit[0])
        if is_user and user_snip is None:
            user_snip = w
        elif any_snip is None:
            any_snip = w
    if seen < set(terms):          # not every word appeared in real content
        return 0, "", False
    return count, (user_snip or any_snip or ""), (user_snip is not None)


def search_auggie(q, limit=500):
    """Auggie counterpart of search_sessions — scans each session's chatHistory
    (user prompts + assistant replies), returning the SAME result shape so
    search_all can rank Claude and Auggie hits together."""
    ql = q.lower().strip()
    if not ql:
        return []
    terms = ql.split()
    titles = load_titles()
    default_cwd = _augment_cwd()
    out = []
    for f in glob.glob(os.path.join(config.AUGGIE_SESSIONS, "*.json"))[:limit]:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sid = d.get("sessionId") or os.path.basename(f)[:-5]
        gid = "auggie:" + sid
        title = (titles.get(gid) or d.get("customTitle")
                 or _short_title(_auggie_first_request(d.get("chatHistory"))) or "Auggie session")
        segs = []  # (text, is_user)
        for m in d.get("chatHistory") or []:
            ex = m.get("exchange") or {}
            r = ex.get("request_message")
            if isinstance(r, str) and r.strip() and not r.lstrip().startswith("<"):
                segs.append((r, True))
            resp = ex.get("response_text")
            if isinstance(resp, str) and resp.strip():
                segs.append((resp, False))
        title_match = all(t in (title or "").lower() for t in terms)
        count, snippet, in_query = _score_segments(segs, terms, ql)
        if not count and not title_match:
            continue
        cwd = _auggie_ide_cwd(d) or default_cwd    # per-session folder, like list/detail
        out.append({
            "id": gid, "project": os.path.basename(cwd) if cwd else "Augment", "title": title,
            "matches": count, "snippet": snippet, "inQuery": in_query,
            "titleMatch": title_match,
            "mtime": _iso_epoch(d.get("modified")) or os.path.getmtime(f),
        })
    return out


class AuggieProvider(Provider):
    prefix = "auggie:"

    def available(self):
        return os.path.isdir(config.AUGGIE_SESSIONS)

    def list(self):
        return list_auggie()

    def parse(self, sid):
        return parse_auggie(sid[len(self.prefix):])

    def search(self, q):
        return search_auggie(q)
