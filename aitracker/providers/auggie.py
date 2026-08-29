import glob, json, os, re, time
from ..config import LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import _dur, _names, _short_title, _first_line, _window, _iso_epoch, _git_branch, cmd_kind, TEST_RE, COMMIT_MSG_RE, collect_prs, note_pr_states, prs_sorted, pr_worked, push_when, PR_CREATE_RE, unified, safe_path_component, context_window, todo_summary
from ..overview import build_overview
from ..store import load_titles, load_tasks, load_notes
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


def _auggie_resolve(root, get, seen=None):
    """A root's subTasks are UUID references to other task files — flatten them
    (depth-first, cycle-safe) into todo dicts. `get(uuid)` fetches one task dict
    (or None); the two callers below differ only in how they fetch — a preloaded
    map for the full detail parse vs. a direct per-uuid file read for the list
    view — so this tree-walk/normalize logic exists exactly once."""
    seen = seen if seen is not None else set()
    out = []
    for ref in root.get("subTasks") or []:
        if not isinstance(ref, str) or ref in seen:
            continue
        seen.add(ref)
        st = get(ref)
        if not st:
            continue
        name = st.get("name") or st.get("description") or ""
        out.append({"content": name,
                    "status": _ASTATE.get((st.get("state") or "").upper(), "pending"),
                    "activeForm": name,
                    # No honest started_at/ended_at here (unlike Claude): the task-storage
                    # file's own "lastUpdated" is a single last-write instant, not a start/end
                    # pair, and the update_tasks/add_tasks tool calls in the session's own
                    # chatHistory key each task by a short per-call id that does NOT match this
                    # file's uuid (confirmed against a real session: update_tasks used ids like
                    # "63a4cp3bxdwD2oqwQ1pWLZ" while task-storage files are named by uuid) — so
                    # there is no reliable join back to THIS todo. Emit null, same shape as
                    # Claude's todos, rather than fabricate or guess from a weak proxy.
                    "started_at": None, "ended_at": None})
        out.extend(_auggie_resolve(st, get, seen))
    return out


def _load_task_file(uuid):
    """One task-storage file by its uuid (== its filename, confirmed against real
    files on disk). Used for the list-time cheap path below — NOT _auggie_all()'s
    glob-everything, which is fine once per detail parse but far too much (223
    files on this machine) to redo per session on every /api/list poll."""
    if not uuid:
        return None
    try:
        return json.load(open(os.path.join(config.AUGMENT_DIR, "task-storage", "tasks", uuid), encoding="utf-8"))
    except (OSError, ValueError):
        return None


_AUGGIE_LIST_CACHE = {}


def _auggie_first_request(chat):
    for m in chat or []:
        r = (m.get("exchange") or {}).get("request_message")
        if isinstance(r, str) and r.strip() and not r.lstrip().startswith("<"):
            return " ".join(r.split())[:200]
    return ""


def _auggie_state(chat):
    """(waiting, ended) for the sidebar — parity with Claude's _tail_fields. `waiting`:
    an ask-user is still unanswered. `ended`: the last exchange finished with an assistant
    response (Auggie's 'completed last run'). Answers to ask-user arrive as a later
    exchange's request_nodes tool_result_node."""
    open_asks, last_resp = set(), False
    for m in chat or []:
        ex = m.get("exchange") or {}
        for rn in ex.get("request_nodes") or []:
            trn = rn.get("tool_result_node") if isinstance(rn, dict) else None
            if isinstance(trn, dict):
                open_asks.discard(trn.get("tool_use_id"))     # the user answered -> closed
        for rn in ex.get("response_nodes") or []:
            call = rn.get("tool_use")
            if isinstance(call, dict) and call.get("tool_name") == "ask-user":
                open_asks.add(call.get("tool_use_id"))
        resp = ex.get("response_text")
        last_resp = isinstance(resp, str) and bool(resp.strip())
    waiting = bool(open_asks)
    return waiting, (not waiting) and last_resp


def _auggie_todos_for(root_uuid):
    if not root_uuid:
        return []
    allmap = _auggie_all()
    root = allmap.get(root_uuid)
    return _auggie_resolve(root, allmap.get) if root else []


def _auggie_todos_for_list(root_uuid):
    """List-time equivalent of _auggie_todos_for: reads only the task files this
    session's own tree references (root + descendants, by direct uuid path) —
    bounded by that session's todo count, not by every task file on disk."""
    if not root_uuid:
        return []
    root = _load_task_file(root_uuid)
    return _auggie_resolve(root, _load_task_file) if root else []


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
            waiting, ended = _auggie_state(d.get("chatHistory"))
            e = {"sid": sid,
                 "title": d.get("customTitle") or (_short_title(req) if req else "Auggie session"),
                 "prompt": req,
                 "cwd": _auggie_ide_cwd(d),   # real per-session working dir (like Claude)
                 "waiting": waiting, "ended": ended,
                 "root": d.get("rootTaskUuid"),
                 "mtime": _iso_epoch(d.get("modified")) or mt}
            _AUGGIE_LIST_CACHE[f] = (mt, e)
        gid = "auggie:" + e["sid"]
        cwd = e.get("cwd") or default_cwd
        # Recomputed every call (not cached alongside `e`): a task's status can change without
        # touching this session's own file, so gating it on the session file's mtime would go stale.
        # _auggie_todos_for_list only reads this session's own task-tree files, so it's still cheap.
        todo_total, todo_done, todo_current, todo_current_index = todo_summary(_auggie_todos_for_list(e.get("root")))
        out.append({
            "id": gid, "project": os.path.basename(cwd) if cwd else "Augment", "cwd": cwd,
            "title": titles.get(gid) or e["title"],
            "prompt": e["prompt"], "source": "auggie", "mtime": e["mtime"],
            "agent": False, "group": "", "groupLabel": "", "parentId": "", "bg": 0, "first": 0,   # Auggie has no background-agent/SDK model
            "waiting": e.get("waiting", False), "ended": e.get("ended", False),
            "todo_total": todo_total, "todo_done": todo_done, "todo_current": todo_current,
            "todo_current_index": todo_current_index,
        })
    return out


def _tool_input(call):
    """A tool_use's input_json — Auggie writes it as a JSON *string* in real logs
    (a dict in older ones / fixtures). Always hand back a dict."""
    inp = call.get("input_json")
    if isinstance(inp, str):
        try:
            inp = json.loads(inp)
        except ValueError:
            inp = {}
    return inp if isinstance(inp, dict) else {}


def _edit_pairs(inp):
    """The (old, new) string pairs of one str-replace-editor call, in order.
    Auggie numbers multi-edits `old_str_1/new_str_1 … old_str_N/new_str_N`; some
    calls use the unnumbered `old_str/new_str`, and `command:"insert"` supplies
    only `new_str_N` (an insertion — nothing removed)."""
    pairs = []
    if "old_str" in inp or "new_str" in inp:
        pairs.append((inp.get("old_str") or "", inp.get("new_str") or ""))
    n = 1
    while ("old_str_%d" % n) in inp or ("new_str_%d" % n) in inp:
        pairs.append((inp.get("old_str_%d" % n) or "", inp.get("new_str_%d" % n) or ""))
        n += 1
    return pairs


def _abs(p, cwd):
    """Auggie logs most edit paths RELATIVE to the session's cwd (397 of 427
    str-replace-editor calls on this machine). Anchor them so the Files panel and
    its /api/file full-text lookup point at a real path, like Claude's absolute ones."""
    if not p:
        return p
    return p if os.path.isabs(p) else (os.path.join(cwd, p) if cwd else p)


def _touch(files, path, ts, created=False):
    """Record one edit on the shared files entry ({path, ops, created, last}) —
    the same shape parse_session() builds for Claude, so one renderer serves both."""
    e = files.setdefault(path, {"path": path, "ops": 0, "created": created})
    e["ops"] += 1
    e["last"] = ts
    if created:
        e["created"] = True
    return e


def _safe_session_id(session_id):
    """Thin alias for the shared seam sanitiser (aitracker.util.safe_path_component)
    — kept so the existing call sites/tests in this module read naturally. The real
    logic (and its rationale) lives at the seam so every provider shares one
    implementation instead of forking it."""
    return safe_path_component(session_id)


def _load_auggie(session_id):
    session_id = _safe_session_id(session_id)
    if session_id is None:
        return None, None
    f = os.path.join(config.AUGGIE_SESSIONS, session_id + ".json")
    if not os.path.isfile(f):
        return None, None
    try:
        return json.load(open(f, encoding="utf-8")), f
    except (OSError, ValueError):
        return None, None


def _auggie_results(d):
    """tool_use_id -> tool_result_node. Auggie files every tool result under the
    NEXT exchange's `request_nodes`, and every one of them carries `is_error` and
    the verbatim `content` — the join that gives commands their ok flag and their
    output (Claude's `errors_by_id` equivalent)."""
    out = {}
    for m in d.get("chatHistory") or []:
        for rn in (m.get("exchange") or {}).get("request_nodes") or []:
            trn = rn.get("tool_result_node") if isinstance(rn, dict) else None
            if isinstance(trn, dict) and trn.get("tool_use_id"):
                out[trn["tool_use_id"]] = trn
    return out


def parse_auggie(session_id):
    d, f = _load_auggie(session_id)
    if d is None:
        return None
    requests, narrative, files, cmds, reads, commits = [], [], {}, [], {}, []
    agents = []       # sub-agent-* dispatches (~ Claude's Task) — {t, type, desc}
    errors_by_id = {} # tool_use_id -> True, from tool_result_node.is_error (~ Claude's map)
    ide_cwd = _auggie_ide_cwd(d)   # needed inside the loop to anchor relative edit paths
    asks = {}         # tool_use_id -> ask-user decision {t, open, answer, questions} (parity with Claude)
    prs = {}          # url -> entry : PR/MR links touched this session (parity with Claude)
    pr_states = {}    # num -> "merged"/"closed" : state signals seen in logs (overlaid at the end)
    pr_creates = []   # exchange indices where a PR-create ran — Auggie logs no output URL, so we
    pr_first_ex = {}  # url -> exchange it first appeared in → attribute "created" by order, below
    tok_in = tok_out = 0
    ctx_current = ctx_limit = None  # LATEST turn's occupancy + the session's own context-window size
    def _cprs(text, narr=False):  # collect PRs + note which exchange each URL first showed up in
        before = set(prs)
        collect_prs(prs, text, ts, narr=narr)
        note_pr_states(pr_states, text)               # `gh pr merge/close N`, merge-commit lines
        for u in prs:
            if u not in before:
                pr_first_ex.setdefault(u, i)
    for i, m in enumerate(d.get("chatHistory") or []):
        ex = m.get("exchange") or {}
        ts = m.get("finishedAt")
        for rn in ex.get("request_nodes") or []:              # every tool RESULT lands here
            trn = rn.get("tool_result_node") if isinstance(rn, dict) else None
            if not isinstance(trn, dict):
                continue
            if trn.get("is_error"):                           # Auggie DOES store exit status
                errors_by_id[trn.get("tool_use_id")] = True
            if trn.get("tool_use_id") in asks:                # the user's answer to a prior ask-user
                c = trn.get("content") or ""
                asks[trn["tool_use_id"]]["answer"] = re.sub(r"^User responded:\s*", "", c).strip()[:2000]
                asks[trn["tool_use_id"]]["open"] = False
        for rn in ex.get("response_nodes") or []:
            tu = rn.get("token_usage")
            if isinstance(tu, dict):                # tokens: mirror Claude (input + cache)
                tok_in += ((tu.get("input_tokens") or 0) + (tu.get("cache_read_input_tokens") or 0)
                           + (tu.get("cache_creation_input_tokens") or 0))
                tok_out += tu.get("output_tokens") or 0
                # this turn's occupancy (last one wins) + Auggie's own stated context-window
                # size, when present — unlike Claude's JSONL, Auggie's token_usage carries
                # max_context_tokens, so a real limit/pct is honestly derivable here.
                ctx_current = ((tu.get("input_tokens") or 0) + (tu.get("cache_read_input_tokens") or 0)
                               + (tu.get("cache_creation_input_tokens") or 0))
                mct = tu.get("max_context_tokens")
                if isinstance(mct, (int, float)) and mct > 0:
                    ctx_limit = mct
            call = rn.get("tool_use")               # commands/reads, from Auggie's tools
            if isinstance(call, dict):
                inp = _tool_input(call)
                name = call.get("tool_name")
                if name and "create_pull_request" in name:   # MCP PR creation in this exchange
                    pr_creates.append(i)
                if name and "merge_pull_request" in name:     # MCP merge → that PR is merged
                    pn = inp.get("pullNumber") or inp.get("pull_number")
                    if pn:
                        pr_states[str(pn)] = "merged"
                if name == "launch-process" and inp.get("command"):   # ~ Claude's Bash
                    c = inp["command"]
                    k = cmd_kind(c)
                    cmds.append({"id": call.get("tool_use_id"), "t": ts, "cmd": c[:200],
                                 "kind": k})    # `ok` joined from tool_result_node.is_error below
                    if PR_CREATE_RE.search(c):
                        pr_creates.append(i)
                    _cprs(c)                              # a command's PR ref alone isn't "worked on"
                    if k == "commit":
                        mm = COMMIT_MSG_RE.search(c)
                        commits.append({"t": ts, "msg": (mm.group(2) if mm else c)[:120]})
                elif name == "save-file" and inp.get("path"):          # ~ Claude's Write
                    _touch(files, _abs(inp["path"], ide_cwd), ts, created=True)
                elif name == "str-replace-editor" and inp.get("path"):  # ~ Claude's Edit/MultiEdit
                    _touch(files, _abs(inp["path"], ide_cwd), ts)
                elif name == "remove-files":                            # deleted files are touched files
                    for p in inp.get("file_paths") or []:
                        if isinstance(p, str) and p:
                            _touch(files, _abs(p, ide_cwd), ts)
                elif name and name.startswith("sub-agent-"):   # ~ Claude's Task
                    agents.append({"t": ts, "type": (name[len("sub-agent-"):] or "agent"),
                                   "desc": (inp.get("name") or inp.get("instruction") or "")[:80]})
                elif name == "view" and inp.get("path") and inp.get("type") != "directory":
                    reads[_abs(inp["path"], ide_cwd)] = ts   # ~ Claude's Read, anchored like `files`
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
    # annotate commands with pass/fail from the error map — same join as Claude's
    for c in cmds:
        c["ok"] = not errors_by_id.get(c["id"], False)
    # a created PR's URL only appears in a later narration line — so tie each
    # `gh pr create` to the first new PR URL at or after its exchange.
    for cx in sorted(pr_creates):
        cand = sorted((u for u, fx in pr_first_ex.items() if fx >= cx and not prs[u]["created"]),
                      key=lambda u: pr_first_ex[u])
        if cand:
            prs[cand[0]]["created"] = True
    cwd = ide_cwd or _auggie_cwd(list(files.keys()))   # real cwd, like Claude's
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
    if agents:
        so.append("dispatched %d sub-agent(s)" % len(agents))   # same line Claude's overview builds
    if todos:
        so.append("%d/%d tasks done" % (done, len(todos)))
    if requests:
        so.append("%d exchange(s)" % len(requests))
    return {
        "meta": {"cwd": cwd, "title": title, "source": "auggie", "entrypoint": "auggie",
                 "gitBranch": branch,
                 "model": ((d.get("chatHistory") or [{}])[-1].get("exchange") or {}).get("model_id") or ""},
                 # no "effort" key here: Auggie logs have no reasoning-effort concept
                 # (unlike model, which Auggie has but may be empty) — omit rather than fake
        "todos": todos,
        "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
        "reads": [{"path": p, "t": t} for p, t in
                  sorted(reads.items(), key=lambda kv: kv[1] or "", reverse=True)],
        "commands": cmds[-60:][::-1],
        "commits": commits[::-1],
        "tests": tests[::-1],
        "requests": requests, "agents": agents[::-1], "agents_bg": [], "agent_sessions": [], "shells": [],
        # open decisions first, then most-recent — parity with Claude's AskUserQuestion panel
        "decisions": sorted(asks.values(), key=lambda a: (a["open"], a["t"] or ""), reverse=True),
        "waiting": any(a["open"] for a in asks.values()),   # unanswered ask-user -> blocked on the user, not idle

        "prs": [p for p in prs_sorted(prs, pr_states) if pr_worked(p, cwd)],   # created or worked-on, not prompt-only references
        "narrative": narrative[::-1],   # full, newest-first; /api/session pages it, /api/narration serves the tail
        "message": latest[:2000],
        "tokens": {"in": tok_in, "out": tok_out},
        "context": context_window(ctx_current, ctx_limit),
        "counts": {"done": done, "todos": len(todos),
                   "created": sum(1 for x in files.values() if x.get("created")),
                   "edited": sum(1 for x in files.values() if not x.get("created")),
                   "read": len(reads), "commits": len(commits), "tests": len(tests),
                   "tests_failed": sum(1 for t in tests if not t["ok"]),
                   "errors": sum(1 for c in cmds if not c["ok"]),
                   "agents": len(agents), "searches": 0},
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
        "notes": load_notes().get("auggie:" + session_id, []),
        # ponytail: auggie has no hook of any kind (--queue needs --print), so nothing drains the
        # queue. Push still queues; pass True here the day a drain exists.
        "push_when": push_when(False, 0, 0),
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
            "agent": False,
            "matches": count, "snippet": snippet, "inQuery": in_query,
            "titleMatch": title_match,
            "mtime": _iso_epoch(d.get("modified")) or os.path.getmtime(f),
        })
    return out


def command_output(session_id, cmd_id):
    """Fetched on click: the full command for `cmd_id` and its captured output.
    Auggie keeps the command on the tool_use and the verbatim result text on the
    matching tool_result_node — the same join that gives a command its ok flag."""
    d, _ = _load_auggie(session_id)
    if d is None:
        return None
    cmd = ""
    for m in d.get("chatHistory") or []:
        for rn in (m.get("exchange") or {}).get("response_nodes") or []:
            call = rn.get("tool_use") if isinstance(rn, dict) else None
            if isinstance(call, dict) and call.get("tool_use_id") == cmd_id:
                cmd = _tool_input(call).get("command") or ""
    trn = _auggie_results(d).get(cmd_id) or {}
    return {"cmd": cmd[:4000], "out": (trn.get("content") or "")[:20000],
            "ok": not trn.get("is_error")}


def file_diffs(session_id, target):
    """Reconstruct every edit to `target`, oldest-first. The tool inputs ARE the
    diff, exactly as for Claude: save-file = full content written (a creation),
    str-replace-editor = the old/new string pairs it swapped."""
    d, _ = _load_auggie(session_id)
    if d is None:
        return None
    cwd = _auggie_ide_cwd(d)
    ops = []
    for m in d.get("chatHistory") or []:
        ts = m.get("finishedAt")
        for rn in (m.get("exchange") or {}).get("response_nodes") or []:
            call = rn.get("tool_use") if isinstance(rn, dict) else None
            if not isinstance(call, dict):
                continue
            name, inp = call.get("tool_name"), _tool_input(call)
            if name == "save-file" and _abs(inp.get("path") or "", cwd) == target:
                ops.append({"ts": ts, "kind": "created",
                            "diff": unified("", inp.get("file_content") or "")})
            elif name == "str-replace-editor" and _abs(inp.get("path") or "", cwd) == target:
                parts = [unified(o, n) for o, n in _edit_pairs(inp)]
                ops.append({"ts": ts, "kind": "edited",
                            "diff": "\n".join(p for p in parts if p)})
    return ops


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

    def exists(self, sid):
        # cheap: a sanitised file-existence check, not a full JSON parse
        session_id = _safe_session_id(sid[len(self.prefix):])
        return bool(session_id) and os.path.isfile(
            os.path.join(config.AUGGIE_SESSIONS, session_id + ".json"))

    # drill-downs — reached through registry.drill(), like Claude's
    def output(self, sid, cmd_id):
        return command_output(sid[len(self.prefix):], cmd_id)

    def diff(self, sid, target):
        return file_diffs(sid[len(self.prefix):], target)
