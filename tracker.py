#!/usr/bin/env python3
"""Live tracker for Claude Code sessions.

Run:  python3 tracker.py            # opens http://localhost:8787
Then paste a session id (or pick a recent one) and watch todos, files
touched, and activity update live while Claude Code works.

Zero dependencies — stdlib only. Reads ~/.claude/projects/*/<id>.jsonl.
"""
import difflib
import glob
import json
import os
import re
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

__version__ = "1.0.0"
PROJECTS = os.path.expanduser("~/.claude/projects")
_HERE = os.path.dirname(os.path.abspath(__file__))
FLAGS_FILE = os.path.join(_HERE, "flags.json")
TITLES_FILE = os.path.join(_HERE, "titles.json")  # user-set session titles (override)
AUGMENT_DIR = os.path.expanduser("~/.augment")     # Auggie (Augment CLI) local state
TASKS_DIR = os.path.expanduser("~/.claude/tasks")   # TaskCreate/TaskUpdate store (replaced TodoWrite)
EDIT_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}  # Write handled separately (= created)
LIVE_WINDOW = 300  # a session stays "live" for this many seconds after its last activity (5 min)
TEST_RE = re.compile(r"\b(pytest|jest|vitest|mocha|go test|cargo test|rspec|"
                     r"npm (run )?test|yarn test|pnpm test|mvn test|gradle test|"
                     r"phpunit|tox|nox|ctest|unittest)\b")
COMMIT_MSG_RE = re.compile(r"-m\s+(['\"])(.+?)\1", re.S)


def _dur(a, b):
    if not (a and b):
        return ""
    try:
        import datetime as _dt
        fmt = "%Y-%m-%dT%H:%M:%S"
        s = (_dt.datetime.strptime(b[:19], fmt) - _dt.datetime.strptime(a[:19], fmt)).total_seconds()
    except ValueError:
        return ""
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    return "%dh %dm" % (s // 3600, (s % 3600) // 60)


def _names(items, n=4):
    short = [os.path.basename(p) for p in items[:n]]
    extra = len(items) - n
    return ", ".join(short) + (" +%d more" % extra if extra > 0 else "")


_FILLER = re.compile(
    r"^(can|could|would|will)\s+(you|i|we)\b|"
    r"^(please|kindly|hey|hi|hello|so|ok|okay|now|also|just|lets|let's|"
    r"i\s+want\s+(you\s+)?to|i\s+would\s+like\s+(you\s+)?to|i'?d\s+like\s+(you\s+)?to|"
    r"help\s+me|we\s+need\s+to|i\s+need\s+(you\s+)?to)\b", re.I)


def _short_title(s, maxw=8, maxc=56):
    """Boil a long first prompt down to a short, title-like phrase."""
    s = " ".join((s or "").split())
    s = re.split(r"(?<=[.?!])\s", s)[0]          # first sentence only
    prev = None
    while prev != s:                              # peel leading filler ("Can you", "I want you to"…)
        prev = s
        s = _FILLER.sub("", s).strip(" ,:-")
    words = s.split()
    out = " ".join(words[:maxw])
    if len(out) > maxc:
        out = out[:maxc].rsplit(" ", 1)[0]
    if len(words) > maxw or len(out) < len(s):
        out = out.rstrip(" ,.;:") + "…"
    return (out[:1].upper() + out[1:]) if out else s[:maxc]


def _first_line(s, n=200):
    for ln in s.strip().splitlines():
        ln = ln.strip().lstrip("#").strip()
        if ln:
            return ln[:n]
    return ""


def build_overview(d, todos, files, cmds, commits, tests, agents, requests,
                   narrative, agents_bg, idle, t_first, t_last):
    """Concrete Goal / Now / So-far that a cold reader can understand at a glance."""
    c = d["counts"]
    m = d["meta"]
    span = _dur(t_first, t_last)
    where = os.path.basename(m.get("cwd", "") or "?")
    if m.get("gitBranch"):
        where += " · ⎇ " + m["gitBranch"]
    if span:
        where += " · %s active" % span

    goal = requests[-1]["text"] if requests else ""

    # what it's doing right now: running background agents win (the "shows idle"
    # bug was here), then in-progress task, then latest narration line
    running = [a for a in agents_bg if a["running"]]
    ip = next((t for t in todos if t.get("status") == "in_progress"), None)
    if running:
        lead = running[0].get("last") or running[0].get("task") or ""
        now = "⚙ %d background agent(s) working" % len(running)
        if lead:
            now += " — " + _first_line(lead, 140)
    elif ip:
        now = "▶ " + (ip.get("activeForm") or ip["content"])
    elif narrative and idle < LIVE_WINDOW:
        now = _first_line(narrative[-1]["text"])
    elif narrative:
        now = "Idle — last said: " + _first_line(narrative[-1]["text"], 140)
    else:
        now = ""

    # one-line synthesis of concrete work
    so = []
    if files:
        so.append("touched %d file(s) (%s)" % (len(files), _names([f["path"] for f in files], 5)))
    if cmds:
        det = []
        if c["commits"]:
            det.append("%d commit" % c["commits"])
        if c["tests"]:
            det.append("%d test%s" % (c["tests"],
                       " incl %d failed" % c["tests_failed"] if c["tests_failed"] else ""))
        if c["errors"]:
            det.append("%d errored" % c["errors"])
        so.append("ran %d command(s)%s" % (len(cmds), " — " + ", ".join(det) if det else ""))
    if agents:
        so.append("dispatched %d sub-agent(s)" % len(agents))
    if c["todos"]:
        so.append("%d/%d tasks done" % (c["done"], c["todos"]))
    sofar = "; ".join(so).capitalize() if so else "Nothing recorded yet."

    return {"where": where, "goal": goal, "now": now, "sofar": sofar,
            "commits": [cm["msg"] for cm in commits[:6]]}


def cmd_kind(c):
    if re.search(r"git\s+commit", c):
        return "commit"
    if TEST_RE.search(c):
        return "test"
    if re.search(r"\b(pip install|npm i\b|npm install|yarn add|pnpm add|poetry add|"
                 r"uv add|uv pip|brew install|apt-get|cargo add)\b", c):
        return "install"
    if re.search(r"\b(make|docker|build|compile|tsc|webpack|vite build)\b", c):
        return "build"
    if re.match(r"\s*git\b", c):
        return "git"
    return "cmd"


def find_session(sid):
    sid = sid.strip().replace(".jsonl", "")
    hits = glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl"))
    return hits[0] if hits else None


_META_CACHE = {}  # path -> (mtime, dict)


def _tail_fields(path, nbytes=96000):
    """aiTitle/customTitle/entrypoint live on metadata lines written as the
    session evolves — read the tail to get the current values cheaply."""
    ai = custom = entry = None
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as fh:
            if sz > nbytes:
                fh.seek(sz - nbytes)
            lines = fh.read().decode("utf-8", "ignore").splitlines()
        if sz > nbytes and lines:
            lines = lines[1:]  # drop the partial first line from mid-file seek
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ai = o.get("aiTitle", ai)
            custom = o.get("customTitle", custom)
            entry = o.get("entrypoint", entry)
    except OSError:
        pass
    return ai, custom, entry


def _session_meta(path):
    """cwd + best title (custom > ai > opening prompt) + entrypoint, cached by mtime."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {"cwd": "", "title": "", "source": ""}
    hit = _META_CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    cwd = prompt = entry_head = ""
    try:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i > 40:
                    break
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not cwd and o.get("cwd"):
                    cwd = o["cwd"]
                if not entry_head and o.get("entrypoint"):
                    entry_head = o["entrypoint"]
                if not prompt:
                    m = o.get("message")
                    if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                        s = " ".join(m["content"].split())
                        if s and not s.startswith("<") and not s.startswith("Caveat:"):
                            prompt = s[:140]
    except OSError:
        pass
    ai, custom, entry = _tail_fields(path)
    meta = {
        "cwd": cwd,
        "title": custom or ai or _short_title(prompt),
        "prompt": prompt,
        "source": entry or entry_head or "",
    }
    _META_CACHE[path] = (mt, meta)
    return meta


def list_sessions(limit=200):
    fs = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    fs.sort(key=os.path.getmtime, reverse=True)
    titles = load_titles()
    out = []
    for f in fs[:limit]:
        sm = _session_meta(f)
        sid = os.path.basename(f)[:-6]
        out.append({
            "id": sid,
            "project": os.path.basename(sm["cwd"]) if sm["cwd"] else os.path.basename(os.path.dirname(f)),
            "cwd": sm["cwd"],
            "title": titles.get(sid) or sm["title"],
            "prompt": sm["prompt"],
            "source": sm["source"],
            "mtime": _active_mtime(f),  # counts background-agent activity too
        })
    return out


def _augment_cwd():
    try:
        s = json.load(open(os.path.join(AUGMENT_DIR, "settings.json"), encoding="utf-8"))
        dirs = s.get("indexingAllowDirs") or []
        if dirs:
            return dirs[0]
    except (OSError, ValueError):
        pass
    return ""


_ASTATE = {"COMPLETE": "completed", "COMPLETED": "completed", "DONE": "completed",
           "IN_PROGRESS": "in_progress", "STARTED": "in_progress"}


def _auggie_all():
    """uuid -> task dict for every task file (roots + sub-tasks), with _mtime."""
    m = {}
    for f in glob.glob(os.path.join(AUGMENT_DIR, "task-storage", "tasks", "*")):
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


AUGGIE_SESSIONS = os.path.join(AUGMENT_DIR, "sessions")
_AUGGIE_LIST_CACHE = {}  # session-file path -> (mtime, list-entry fields)


def _iso_epoch(s):
    try:
        import datetime as _dt
        return _dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=_dt.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


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
    cwd = _augment_cwd()
    proj = os.path.basename(cwd) if cwd else "Augment"
    out = []
    for f in glob.glob(os.path.join(AUGGIE_SESSIONS, "*.json")):
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
                 "mtime": _iso_epoch(d.get("modified")) or mt}
            _AUGGIE_LIST_CACHE[f] = (mt, e)
        gid = "auggie:" + e["sid"]
        out.append({
            "id": gid, "project": proj, "cwd": cwd,
            "title": titles.get(gid) or e["title"],
            "prompt": e["prompt"], "source": "auggie", "mtime": e["mtime"],
        })
    return out


def parse_auggie(session_id):
    f = os.path.join(AUGGIE_SESSIONS, session_id + ".json")
    if not os.path.isfile(f):
        return None
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    requests, narrative, files = [], [], {}
    for m in d.get("chatHistory") or []:
        ex = m.get("exchange") or {}
        ts = m.get("finishedAt")
        r = ex.get("request_message")
        if isinstance(r, str) and r.strip() and not r.lstrip().startswith("<"):
            requests.append({"t": ts, "text": " ".join(r.split())[:300]})
        resp = ex.get("response_text")
        if isinstance(resp, str) and resp.strip():
            narrative.append({"t": ts, "text": resp.strip()[:900]})
        for cf in m.get("changedFiles") or []:
            p = cf if isinstance(cf, str) else (cf.get("path") or cf.get("filePath") or cf.get("file"))
            if p:
                fe = files.setdefault(p, {"path": p, "ops": 0, "created": False})
                fe["ops"] += 1
                fe["last"] = ts
    cwd = _augment_cwd()
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
    if todos:
        so.append("%d/%d tasks done" % (done, len(todos)))
    if requests:
        so.append("%d exchange(s)" % len(requests))
    return {
        "meta": {"cwd": cwd, "title": title, "source": "auggie", "entrypoint": "auggie",
                 "model": ((d.get("chatHistory") or [{}])[-1].get("exchange") or {}).get("model_id") or ""},
        "todos": todos,
        "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
        "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": requests, "agents": [], "agents_bg": [], "shells": [],
        "narrative": narrative[-16:][::-1],
        "message": latest[:2000],
        "tokens": {"in": 0, "out": 0},
        "counts": {"done": done, "todos": len(todos), "created": 0, "edited": len(files), "read": 0,
                   "commits": 0, "tests": 0, "tests_failed": 0, "errors": 0, "agents": 0, "searches": 0},
        "overview": {
            "where": os.path.basename(cwd) if cwd else "Augment",
            "goal": requests[-1]["text"] if requests else "",
            "now": ("▶ " + ip["content"]) if ip else (_first_line(latest) if latest else title),
            "sofar": "; ".join(so).capitalize() if so else "No activity recorded yet.",
            "commits": [],
        },
        "mtime": _iso_epoch(d.get("modified")) or os.path.getmtime(f),
        "now": time.time(),
    }


def _window(text, ql, pad=70):
    t = " ".join(text.split())
    i = t.lower().find(ql)
    if i < 0:
        return t[:160]
    s, e = max(0, i - pad), min(len(t), i + len(ql) + pad)
    return ("…" if s > 0 else "") + t[s:e] + ("…" if e < len(t) else "")


def _searchable_texts(o):
    """Yield (text, is_user_query) for the *real* content of a session line —
    user prompts, assistant replies, and tool inputs. Excludes system reminders,
    command wrappers, attachments, and tool output — the injected boilerplate
    (skill/tool lists) that otherwise made common words match nearly every session."""
    m = o.get("message")
    if not isinstance(m, dict):
        return
    role = m.get("role")
    c = m.get("content")
    if isinstance(c, str):
        s = c.lstrip()
        if role == "user" and not s.startswith("<") and not s.startswith("Caveat:"):
            yield (c, True)
    elif isinstance(c, list):
        for b in c:
            if not isinstance(b, dict):
                continue
            ty = b.get("type")
            if ty == "text":
                txt = b.get("text") or ""
                if not txt.lstrip().startswith("<"):
                    yield (txt, role == "user")
            elif ty == "tool_use":
                inp = b.get("input") or {}
                for k in ("command", "file_path", "notebook_path", "pattern",
                          "path", "url", "query", "prompt", "description"):
                    v = inp.get(k)
                    if isinstance(v, str):
                        yield (v, False)


def _match_content(data, ql):
    """Count real-content matches for ql in one session; return
    (count, best_snippet, hit_in_user_query). Boilerplate-only files score 0."""
    count = 0
    user_snip = any_snip = None
    for line in data.splitlines():
        if ql not in line.lower():
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        for text, is_user in _searchable_texts(o):
            tl = text.lower()
            if ql not in tl:
                continue
            count += tl.count(ql)
            if is_user and user_snip is None:
                user_snip = _window(text, ql)
            elif any_snip is None:
                any_snip = _window(text, ql)
    return count, (user_snip or any_snip or ""), user_snip is not None


def search_sessions(q, limit=500):
    """Search sessions for q (case-insensitive) in real conversation content —
    user prompts, replies, tool inputs — not the injected skill/tool boilerplate.
    Newest-first with a snippet, match count, and whether it hit a user prompt."""
    ql = q.lower().strip()
    if not ql:
        return []
    terms = ql.split()                       # keyword search: every word must be present
    titles = load_titles()
    fs = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    fs.sort(key=os.path.getmtime, reverse=True)
    out = []
    for f in fs[:limit]:
        try:
            data = open(f, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        dl = data.lower()
        sid = os.path.basename(f)[:-6]
        sm = _session_meta(f)
        title = titles.get(sid) or sm["title"]
        tl = (title or "").lower()
        title_match = all(t in tl for t in terms)          # all words in the title
        if not title_match and not all(t in dl for t in terms):  # fast reject
            continue
        # count matches per word in *real* content (excludes boilerplate); require all words
        per = [_match_content(data, t) for t in terms]
        real_all = all(c > 0 for c, _, _ in per)
        if not real_all and not title_match:
            continue
        count = sum(c for c, _, _ in per)
        in_query = any(iq for _, _, iq in per)
        if ql in dl:                                       # exact phrase present -> nicer snippet
            _, ph_snip, ph_iq = _match_content(data, ql)
            snippet = ph_snip or next((s for _, s, _ in per if s), "")
            in_query = in_query or ph_iq
        else:
            snippet = next((s for _, s, _ in per if s), "")
        out.append({
            "id": sid,
            "project": os.path.basename(sm["cwd"]) if sm["cwd"] else os.path.basename(os.path.dirname(f)),
            "title": title,
            "matches": count,
            "snippet": snippet,
            "inQuery": in_query,
            "titleMatch": title_match,
            "mtime": os.path.getmtime(f),
        })
    # rank: title matches first, then hits in the user's own prompt, then the rest
    # (stable sort preserves the newest-first order within each group)
    out.sort(key=lambda r: (not r["titleMatch"], not r["inQuery"]))
    return out


def _agent_files(path):
    # background agents (Task/Workflow) write to <session-id>/**/agent-*.jsonl
    base = path[:-6] if path.endswith(".jsonl") else path
    return glob.glob(os.path.join(base, "**", "agent-*.jsonl"), recursive=True)


def _active_mtime(path):
    """Newest activity across the main file AND any background-agent files —
    this is what tells us a session is live even when only sub-agents are working."""
    m = 0.0
    try:
        m = os.path.getmtime(path)
    except OSError:
        pass
    for af in _agent_files(path):
        try:
            m = max(m, os.path.getmtime(af))
        except OSError:
            pass
    return m


def parse_agents(path):
    """Parse background-agent transcripts: what each one is, doing, and whether it's live."""
    out = []
    newest = 0.0
    now = time.time()
    for af in sorted(_agent_files(path)):
        try:
            mt = os.path.getmtime(af)
        except OSError:
            continue
        newest = max(newest, mt)
        task = last_text = ""
        last_ts = None
        tools = 0
        try:
            with open(af, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        o = json.loads(line)
                    except ValueError:
                        continue
                    if o.get("timestamp"):
                        last_ts = o["timestamp"]
                    m = o.get("message")
                    if not isinstance(m, dict):
                        continue
                    c = m.get("content")
                    if not task and m.get("role") == "user" and isinstance(c, str):
                        s = " ".join(c.split())
                        if s and not s.startswith("<"):
                            task = s[:160]
                    if isinstance(c, list):
                        for b in c:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") == "tool_use":
                                tools += 1
                            elif b.get("type") == "text" and b.get("text", "").strip():
                                t = b["text"].strip()
                                if not t.startswith("<"):
                                    last_text = t
        except OSError:
            continue
        wf = next((p for p in af.split(os.sep) if p.startswith("wf_")), "")
        out.append({
            "id": os.path.basename(af)[6:-6][:10],  # strip "agent-" / ".jsonl"
            "aid": os.path.basename(af)[6:-6],       # full id, for the detail endpoint
            "wf": wf,
            "task": task,
            "last": _first_line(last_text) if last_text else "",
            "ts": last_ts,
            "tools": tools,
            "running": (now - mt) < LIVE_WINDOW,
        })
    out.sort(key=lambda a: (not a["running"], a["ts"] or ""), reverse=False)
    return out, newest


def _unified(old, new, cap=20000):
    """Unified diff between two strings, each capped to keep payloads sane."""
    old, new = (old or "")[:cap], (new or "")[:cap]
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(), "before", "after", lineterm=""))


def file_diffs(path, target):
    """Reconstruct every Write/Edit to `target` from the transcript, in order.
    The tool inputs ARE the diff: Write=full content, Edit=old/new strings."""
    ops = []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return ops
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ts = o.get("timestamp")
            m = o.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") or {}
                if (inp.get("file_path") or inp.get("notebook_path")) != target:
                    continue
                name = b.get("name")
                if name == "Write":
                    ops.append({"ts": ts, "kind": "created", "diff": _unified("", inp.get("content", ""))})
                elif name == "Edit":
                    ops.append({"ts": ts, "kind": "edited",
                                "diff": _unified(inp.get("old_string", ""), inp.get("new_string", ""))})
                elif name == "MultiEdit":
                    parts = [_unified(e.get("old_string", ""), e.get("new_string", ""))
                             for e in inp.get("edits", []) if isinstance(e, dict)]
                    ops.append({"ts": ts, "kind": "edited", "diff": "\n".join(p for p in parts if p)})
                elif name == "NotebookEdit":
                    ops.append({"ts": ts, "kind": "edited", "diff": _unified("", inp.get("new_source", ""))})
    return ops


def _result_text(c):
    """Flatten a tool_result's content (str or list of blocks) to plain text."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            if isinstance(b, str):
                out.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                out.append(b.get("text", ""))
        return "\n".join(out)
    return ""


def command_output(path, cmd_id):
    """Fetched on click: the full command for `cmd_id` and its captured output."""
    cmd, out, ok = "", "", True
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return {"cmd": "", "out": "", "ok": True}
    with fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            m = o.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("id") == cmd_id:
                    cmd = (b.get("input") or {}).get("command", "")
                elif b.get("type") == "tool_result" and b.get("tool_use_id") == cmd_id:
                    out = _result_text(b.get("content"))
                    ok = not b.get("is_error")
    return {"cmd": cmd[:4000], "out": out[:20000], "ok": ok}


SHELL_RE = re.compile(r"running in background with ID:\s*(\S+?)\.\s*"
                      r"Output is being written to:\s*(\S+\.output)")
TASKDONE_RE = re.compile(r"<task-id>([^<]+)</task-id>")


def parse_shells(path):
    """Background shells: a Bash run_in_background launch + its result naming the
    shell id and live .output file. A shell is running until a <task-notification>
    for its id appears (the harness' completion signal) — the .output file's mtime
    is NOT reliable, since commands often redirect their output to their own log."""
    launches, results, done = {}, {}, set()
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return []
    with fh:
        for line in fh:
            if "<task-notification>" in line:
                done.update(TASKDONE_RE.findall(line))
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ts = o.get("timestamp")
            m = o.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") == "Bash" and (b.get("input") or {}).get("run_in_background"):
                    inp = b["input"]
                    launches[b.get("id")] = {"cmd": inp.get("command", "")[:4000],
                                             "desc": inp.get("description", ""), "ts": ts}
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in launches:
                    mt = SHELL_RE.search(_result_text(b.get("content")))
                    if mt:
                        results[b["tool_use_id"]] = (mt.group(1), mt.group(2))
    out = []
    for lid, info in launches.items():
        shell_id, outpath = results.get(lid, ("", ""))
        last = ""
        if outpath and os.path.exists(outpath):
            try:
                lines = [l for l in open(outpath, encoding="utf-8", errors="ignore").read().splitlines() if l.strip()]
                last = lines[-1][:200] if lines else ""
            except OSError:
                pass
        out.append({"id": shell_id or (lid or "")[:10], "cmd": info["cmd"], "desc": info["desc"],
                    "ts": info["ts"], "running": (shell_id or "") not in done, "last": last, "out": outpath})
    out.sort(key=lambda s: (not s["running"], s["ts"] or ""))
    return out


ASSIGN_RE = re.compile(r'(\w+)=("?)(/[^"\s]+)\2')               # VAR=/abs/path
REDIR_RE = re.compile(r'(?:&>|\d*>>?|>)\s*("?)(\$\{?\w+\}?|/[^"\s]+)\1')  # > "$LOG" | > /abs


def _redirect_log(cmd):
    """Best-effort: many bg commands send output to their own log via `> "$LOG"`
    (with `LOG=/abs/path`) instead of the harness .output file. Resolve that path
    so we can still show output."""
    vars = {m.group(1): m.group(3) for m in ASSIGN_RE.finditer(cmd)}
    for m in REDIR_RE.finditer(cmd):
        tok = m.group(2)
        p = vars.get(tok.strip("${}")) if tok.startswith("$") else tok
        if p and os.path.isabs(p) and os.path.exists(p):
            return p
    return ""


def _read_tail(p, n=40000):
    try:
        return open(p, encoding="utf-8", errors="ignore").read()[-n:]
    except OSError:
        return ""


def shell_output(path, shell_id):
    """Fetched on click: the launching command + the tail of its output — the
    harness .output file, or the command's own redirect target if that's empty."""
    sh = next((s for s in parse_shells(path) if s["id"] == shell_id), None)
    if not sh:
        return {"cmd": "", "out": "", "running": False}
    out = _read_tail(sh["out"]) if sh["out"] and os.path.exists(sh["out"]) else ""
    if not out.strip():
        log = _redirect_log(sh["cmd"])
        if log:
            out = _read_tail(log)
    return {"cmd": sh["cmd"], "out": out, "running": sh["running"]}


def agent_detail(path, aid):
    """Fetched on click: a background agent's full narration, tool count, state."""
    for af in _agent_files(path):
        if os.path.basename(af)[6:-6] != aid:  # strip "agent-"/".jsonl"
            continue
        task, texts, tools = "", [], 0
        try:
            for line in open(af, encoding="utf-8"):
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                m = o.get("message")
                if not isinstance(m, dict):
                    continue
                c = m.get("content")
                if m.get("role") == "user" and isinstance(c, str) and not task:
                    s = " ".join(c.split())
                    if s and not s.startswith("<"):
                        task = s[:200]
                if isinstance(c, list):
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            tools += 1
                        elif b.get("type") == "text" and b.get("text", "").strip() and not b["text"].lstrip().startswith("<"):
                            texts.append(b["text"].strip())
        except OSError:
            break
        running = False
        try:
            running = (time.time() - os.path.getmtime(af)) < LIVE_WINDOW
        except OSError:
            pass
        return {"task": task, "narration": "\n\n".join(texts)[:40000], "tools": tools, "running": running}
    return {"task": "", "narration": "", "tools": 0, "running": False}


def parse_session(path):
    # ponytail: full re-parse per poll. Fine to a few MB; switch to
    # offset-tailing if session files ever get huge.
    todos = []
    files = {}            # path -> {ops, last, created}
    reads = {}            # path -> last ts
    cmds = []             # bash commands, each {id, t, cmd, kind}
    commits = []          # {t, msg}
    requests = []         # user asks {t, text}
    agents = []           # {t, type, desc}
    errors_by_id = {}     # tool_use_id -> True
    narrative = []       # Claude's own text, in order: the blow-by-blow
    meta = {}
    text_last = ""
    tok_in = tok_out = 0
    n_search = 0
    t_first = t_last = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            ts = o.get("timestamp")
            if ts:
                t_first = t_first or ts
                t_last = ts
            for k in ("cwd", "gitBranch", "version", "sessionId",
                      "entrypoint", "aiTitle", "customTitle"):
                if o.get(k):
                    meta[k] = o[k]  # last value wins
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            u = msg.get("usage") or {}
            tok_in += (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                       + u.get("cache_creation_input_tokens", 0))
            tok_out += u.get("output_tokens", 0)
            if msg.get("model"):
                meta["model"] = msg["model"]
            content = msg.get("content")
            # user prompts arrive as a plain string (tool results are lists)
            if msg.get("role") == "user" and isinstance(content, str):
                s = content.strip()
                if s and not s.startswith("<") and not s.startswith("Caveat:"):
                    requests.append({"t": ts, "text": s[:8000]})  # full prompt; list clamps preview
                continue
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text" and b.get("text", "").strip():
                    txt = b["text"].strip()
                    if not txt.startswith("<"):  # skip command/system echoes
                        text_last = txt
                        narrative.append({"t": ts, "text": txt[:12000]})  # full message; list clamps the preview
                elif bt == "tool_result" and b.get("is_error"):
                    errors_by_id[b.get("tool_use_id")] = True
                elif bt == "tool_use":
                    name = b.get("name")
                    inp = b.get("input") or {}
                    bid = b.get("id")
                    if name == "TodoWrite":
                        todos = inp.get("todos", todos)
                    elif name == "Write":
                        fp = inp.get("file_path")
                        if fp:
                            e = files.setdefault(fp, {"path": fp, "ops": 0, "created": True})
                            e["ops"] += 1; e["last"] = ts; e["created"] = True
                    elif name in EDIT_TOOLS:
                        fp = inp.get("file_path") or inp.get("notebook_path")
                        if fp:
                            e = files.setdefault(fp, {"path": fp, "ops": 0, "created": False})
                            e["ops"] += 1; e["last"] = ts
                    elif name == "Read":
                        fp = inp.get("file_path")
                        if fp:
                            reads[fp] = ts
                    elif name == "Bash":
                        c = inp.get("command", "")
                        k = cmd_kind(c)
                        cmds.append({"id": bid, "t": ts, "cmd": c[:200], "kind": k})
                        if k == "commit":
                            m = COMMIT_MSG_RE.search(c)
                            commits.append({"t": ts, "msg": (m.group(2) if m else c)[:120]})
                    elif name in ("Grep", "Glob"):
                        n_search += 1
                    elif name == "Task":
                        agents.append({"t": ts, "type": inp.get("subagent_type") or "agent",
                                       "desc": (inp.get("description") or "")[:80]})
    # annotate commands with pass/fail from the error map
    for c in cmds:
        c["ok"] = not errors_by_id.get(c["id"], False)
    tests = [c for c in cmds if c["kind"] == "test"]
    sid = meta.get("sessionId") or os.path.basename(path)[:-6]
    tasks = load_tasks(sid)  # newer sessions use the task store, not in-transcript TodoWrite
    if tasks:
        todos = tasks
    done_todos = [t for t in todos if t.get("status") == "completed"]
    agents_bg, newest_agent = parse_agents(path)
    shells = parse_shells(path)
    meta["title"] = (load_titles().get(sid) or meta.get("customTitle") or meta.get("aiTitle")
                     or (_short_title(requests[0]["text"]) if requests else ""))
    st = os.stat(path)
    result = {
        "meta": meta,
        "todos": todos,
        "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
        "reads": [{"path": p, "t": t} for p, t in
                  sorted(reads.items(), key=lambda kv: kv[1] or "", reverse=True)],
        "commands": cmds[-60:][::-1],
        "commits": commits[::-1],
        "tests": tests[::-1],
        "requests": requests,
        "agents": agents[::-1],
        "agents_bg": agents_bg,
        "shells": shells,
        "narrative": narrative[-16:][::-1],
        "message": text_last[:2000],
        "tokens": {"in": tok_in, "out": tok_out},
        "counts": {
            "done": len(done_todos), "todos": len(todos),
            "created": sum(1 for f in files.values() if f.get("created")),
            "edited": sum(1 for f in files.values() if not f.get("created")),
            "read": len(reads), "commits": len(commits),
            "tests": len(tests), "tests_failed": sum(1 for t in tests if not t["ok"]),
            "errors": sum(1 for c in cmds if not c["ok"]),
            "agents": len(agents), "searches": n_search,
        },
        "mtime": max(st.st_mtime, newest_agent),  # background agents keep it "live"
        "now": time.time(),
    }
    result["overview"] = build_overview(result, todos, result["files"], cmds, commits,
                                         tests, agents, requests, narrative, agents_bg,
                                         time.time() - result["mtime"], t_first, t_last)
    return result


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)


def load_titles():
    return _load_json(TITLES_FILE, {})


_TSTATUS = {"completed": "completed", "complete": "completed", "done": "completed",
            "in_progress": "in_progress", "started": "in_progress", "pending": "pending"}


def load_tasks(sid):
    """Current tasks for a session from ~/.claude/tasks/<sid>/<n>.json — the
    TaskCreate/TaskUpdate store that replaced in-transcript TodoWrite. Files are
    updated in place, so this reflects live status. Sorted by numeric id."""
    d = os.path.join(TASKS_DIR, sid)
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
    except OSError:
        return []

    def key(f):
        try:
            return int(f[:-5])
        except ValueError:
            return 1 << 30
    out = []
    for f in sorted(files, key=key):
        try:
            t = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subj = isinstance(t, dict) and (t.get("subject") or t.get("content"))
        if not subj:
            continue
        out.append({"content": subj,
                    "status": _TSTATUS.get((t.get("status") or "").lower(), "pending"),
                    "activeForm": t.get("activeForm") or subj,
                    "desc": t.get("description") or ""})
    return out


def load_flags():
    try:
        with open(FLAGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_flags(flags):
    # ponytail: full rewrite, no locking — fine for a single-user local tool.
    _save_json(FLAGS_FILE, flags)


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # client closed the connection (normal: a newer 2s poll superseded
            # this one, or the tab closed). Nothing to send; don't crash.
            pass

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            body = PAGE.encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif p.path == "/api/list":
            both = list_sessions() + list_auggie()
            both.sort(key=lambda s: s.get("mtime", 0), reverse=True)
            self._json(both)
        elif p.path == "/api/flags":
            self._json(load_flags())
        elif p.path == "/api/search":
            self._json(search_sessions(parse_qs(p.query).get("q", [""])[0]))
        elif p.path == "/api/diff":
            qs = parse_qs(p.query)
            sid, fp = qs.get("id", [""])[0], qs.get("file", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json({"file": fp, "ops": file_diffs(path, fp)})
        elif p.path == "/api/file":
            # ponytail: local single-user tool — reads the file at the given path
            # (paths come from the session's own edits) with a size cap.
            fp = parse_qs(p.query).get("path", [""])[0]
            try:
                if not fp or not os.path.isfile(fp):
                    self._json({"error": "not found", "content": ""}, 404)
                elif os.path.getsize(fp) > 500_000:
                    self._json({"error": "file too large to render", "content": ""})
                else:
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        self._json({"path": fp, "content": fh.read()})
            except OSError as e:
                self._json({"error": str(e), "content": ""}, 500)
        elif p.path == "/api/output":
            qs = parse_qs(p.query)
            sid, cid = qs.get("id", [""])[0], qs.get("cmd", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(command_output(path, cid))
        elif p.path == "/api/shell":
            qs = parse_qs(p.query)
            sid, shid = qs.get("id", [""])[0], qs.get("shell", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(shell_output(path, shid))
        elif p.path == "/api/agent":
            qs = parse_qs(p.query)
            sid, aid = qs.get("id", [""])[0], qs.get("agent", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(agent_detail(path, aid))
        elif p.path == "/api/session":
            sid = parse_qs(p.query).get("id", [""])[0]
            if sid.startswith("auggie:"):
                data = parse_auggie(sid[len("auggie:"):])
                self._json(data if data else {"error": "auggie session not found", "id": sid},
                           200 if data else 404)
                return
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            try:
                data = parse_session(path)
            except OSError as e:
                self._json({"error": str(e)}, 500)
                return
            self._json(data)  # write errors handled inside _json, not as a 500
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except (ValueError, TypeError):
            self._json({"error": "bad body"}, 400)
            return
        if p.path == "/api/title":
            sid, t = body.get("session", ""), (body.get("title") or "").strip()
            titles = load_titles()
            if t:
                titles[sid] = t[:120]
            else:
                titles.pop(sid, None)  # empty = clear override, fall back to auto
            _save_json(TITLES_FILE, titles)
            self._json({"ok": True})
            return
        flags = load_flags()
        if p.path == "/api/flags":
            note = (body.get("note") or "").strip()
            if not note:
                self._json({"error": "empty note"}, 400)
                return
            flag = {
                "id": int(time.time() * 1000),
                "session": body.get("session", ""),
                "project": body.get("project", ""),
                "note": note[:1000],
                "context": (body.get("context") or "")[:500],
                "ts": time.time(),
                "resolved": False,
            }
            flags.append(flag)
            save_flags(flags)
            self._json(flag, 201)
        elif p.path == "/api/flags/resolve":
            for f in flags:
                if f["id"] == body.get("id"):
                    f["resolved"] = not f.get("resolved", False)
            save_flags(flags)
            self._json({"ok": True})
        elif p.path == "/api/flags/delete":
            save_flags([f for f in flags if f["id"] != body.get("id")])
            self._json({"ok": True})
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass  # quiet


PAGE = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Claude Code Tracker</title>
<link rel=preconnect href="https://fonts.googleapis.com">
<link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel=stylesheet>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:#0c0f15;color:#e6edf3;font-family:'Source Sans 3',system-ui,sans-serif}
.mono{font-family:'JetBrains Mono',monospace}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#2c333f;border-radius:6px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-track{background:transparent}
@keyframes pulseDot{0%{box-shadow:0 0 0 0 rgba(41,211,152,.55)}70%{box-shadow:0 0 0 7px rgba(41,211,152,0)}100%{box-shadow:0 0 0 0 rgba(41,211,152,0)}}
@keyframes pulseAmber{0%{box-shadow:0 0 0 0 rgba(245,180,67,.5)}70%{box-shadow:0 0 0 6px rgba(245,180,67,0)}100%{box-shadow:0 0 0 0 rgba(245,180,67,0)}}
@keyframes blink{0%,55%{opacity:1}56%,100%{opacity:.25}}
@keyframes spinIn{from{stroke-dashoffset:var(--circ)}}
.app{height:100vh;display:flex;overflow:hidden}

/* sidebar */
.side{width:300px;flex:0 0 300px;background:#0a0d12;border-right:1px solid #1c2330;display:flex;flex-direction:column}
.sidehead{padding:16px 16px 12px;border-bottom:1px solid #1c2330}
.sidetop{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.sidetop .ttl{font-weight:700;font-size:15px;letter-spacing:.01em}
.livebadge{font-family:'JetBrains Mono',monospace;font-size:11px;color:#29d398;background:#0f2a20;border:1px solid #1c4634;padding:2px 8px;border-radius:20px;cursor:pointer;user-select:none}
.livebadge:hover{border-color:#29d398}
.livebadge.on{background:#29d398;color:#04120c;border-color:#29d398;font-weight:600}
.searchbox{display:flex;align-items:center;gap:8px;background:#0f141c;border:1px solid #232a36;border-radius:8px;padding:6px 10px}
.searchbox input{flex:1;min-width:0;background:none;border:0;outline:0;color:#e6edf3;font-size:13px;font-family:'JetBrains Mono',monospace}
.searchbox input::placeholder{color:#5b6573}
.searchbox .ic{color:#5b6573;font-size:13px;cursor:pointer}
.slist{flex:1;overflow:auto;padding:8px}
.sitem{padding:11px 12px;border-radius:10px;margin-bottom:4px;cursor:pointer;background:transparent;border:1px solid transparent}
.sitem:hover{background:rgba(76,141,255,.06)}
.sitem.active{background:rgba(76,141,255,.10);border-color:#234063}
.srow1{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.srow1 .nm{font-weight:600;font-size:13.5px;color:#e6edf3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.ren{color:#5b6573;cursor:pointer;opacity:0;font-style:normal;flex:0 0 auto}
.sitem:hover .ren{opacity:.8}.ren:hover{color:#4c8dff}
.smeta{display:flex;align-items:center;gap:6px;color:#6b7585;font-size:11px;font-family:'JetBrains Mono',monospace;flex-wrap:wrap}
.smeta .proj{color:#7d8898}
.ssnip{color:#6b7585;font-size:11px;margin-top:6px;line-height:1.35;font-family:'JetBrains Mono',monospace;overflow-wrap:anywhere}
.ssnip b{color:#e6edf3;background:#1f6feb40;border-radius:2px}
.smatch{color:#29d398}
.sidefoot{padding:12px 14px;border-top:1px solid #1c2330;color:#5b6573;font-size:11px;font-family:'JetBrains Mono',monospace;display:flex;align-items:center;justify-content:space-between}

.dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:0 0 auto;background:#6e7681}
.dot.live{background:#29d398;animation:pulseDot 1.8s infinite}
.dot.amber{background:#f5b443;animation:pulseAmber 1.8s infinite}

/* main */
main{flex:1;min-width:0;overflow-y:auto;overflow-x:hidden;background:radial-gradient(1100px 380px at 70% -8%,#11203a 0%,#0c0f15 60%)}
header.hd{padding:22px 28px 18px;border-bottom:1px solid #1c2330}
.hero{display:flex;align-items:flex-start;gap:24px;flex-wrap:wrap}
.ring{position:relative;width:122px;height:122px;flex:0 0 auto}
.ring svg{transform:rotate(-90deg)}
.ringctr{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.ringpct{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;color:#e6edf3;line-height:1}
.ringpct span{font-size:13px;color:#8b949e}
.ringsub{font-size:10.5px;color:#8b949e;margin-top:2px}
.htitle{flex:1;min-width:240px}
.htop{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.htop h2{margin:0;font-size:20px;font-weight:700}
.activebadge{display:inline-flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#29d398;background:#0f2a20;border:1px solid #1c4634;padding:3px 9px;border-radius:20px}
.activebadge .dot{width:7px;height:7px}
.hmeta{margin-top:8px;color:#8b949e;font-size:12.5px;font-family:'JetBrains Mono',monospace;display:flex;flex-wrap:wrap;gap:6px 14px}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:14px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:4px 10px;border-radius:20px;background:#10141c;border:1px solid #2c333f;color:#c9d4e0}
.chip .lbl{color:#8b949e}
.chip b{font-family:'JetBrains Mono',monospace;color:#c9d4e0}
.chip.good{border-color:#21402b}.chip.good b{color:#3fb950}
.chip.blue{border-color:#1d3a5f}.chip.blue b{color:#4c8dff}
.chip.bad{border-color:#4a2323}.chip.bad b{color:#f85149}
.chip.clk{cursor:pointer}.chip.clk:hover{border-color:#4c8dff;background:#141b26}
@keyframes flashcard{0%{box-shadow:0 0 0 0 rgba(76,141,255,0)}18%{box-shadow:0 0 0 3px rgba(76,141,255,.4)}100%{box-shadow:0 0 0 0 rgba(76,141,255,0)}}
.flash{animation:flashcard 1.3s ease-out}.flash>h2{color:#4c8dff}
.nowbanner{margin-top:16px;display:flex;align-items:center;gap:12px;background:linear-gradient(90deg,#10243f,#0d1622);border:1px solid #1d3a5f;border-left:3px solid #4c8dff;border-radius:10px;padding:11px 14px}
.nowbanner .dot{width:9px;height:9px;background:#4c8dff;animation:pulseDot 1.8s infinite}
.nowbanner .lbl{font-size:10px;letter-spacing:.6px;text-transform:uppercase;color:#6f8db5}
.nowbanner .txt{font-size:14px;color:#dbe7f5;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cursor{animation:blink 1s steps(1) infinite}
.srcnote{margin-top:12px;padding:8px 12px;background:#1a1206;border:1px solid #3a2a0f;border-left:3px solid #d29922;border-radius:8px;color:#e3b341;font-size:12px}

.body{padding:18px 28px 32px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.body{grid-template-columns:1fr}}
.span2{grid-column:1/-1}
.card{background:#0e121a;border:1px solid #1c2330;border-radius:12px;display:flex;flex-direction:column;min-height:0;min-width:0}
.card h2{margin:0;padding:11px 16px;border-bottom:1px solid #1c2330;display:flex;align-items:center;justify-content:space-between;font-size:11.5px;letter-spacing:.5px;text-transform:uppercase;color:#8b949e;font-weight:700}
.card h2 .cnt{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:400}
.cbody{overflow:auto;max-height:46vh}
.mini{background:#10141c;border:1px solid #2c333f;color:#8b949e;font-size:11px;padding:3px 8px;border-radius:6px;cursor:pointer;font-family:inherit}
.mini:hover{border-color:#4c8dff}

/* background agents */
.bggrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:#1c2330;border-bottom-left-radius:12px;border-bottom-right-radius:12px;max-height:56vh;overflow:auto}
@media(max-width:900px){.bggrid{grid-template-columns:1fr}}
.agent{background:#0e121a;padding:13px 15px;min-width:0}
.disclosure{grid-column:1/-1;background:#0b0f16;color:#f5b443;padding:9px 15px;font-size:12px;cursor:pointer;user-select:none;text-align:center}
.disclosure:hover{background:#131a24;color:#ffcb6b}
.bggrid .empty{grid-column:1/-1;padding:14px 15px;color:#6b7585}
.agent .top{display:flex;align-items:center;gap:7px;margin-bottom:7px;min-width:0}
.agent .nm{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0}
.agent .last{color:#8b949e;font-size:12px;line-height:1.4;margin-bottom:8px;min-height:34px;overflow-wrap:anywhere;overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.agent .ft{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:#6b7585;display:flex;gap:10px;flex-wrap:wrap}
.tag{font-size:10px;padding:1px 6px;border-radius:4px;background:#161c27;color:#6b7585}

/* summary */
.ov{padding:16px}
.ovrow{display:flex;gap:14px;margin-bottom:10px}
.ovrow:last-child{margin-bottom:0}
.ovk{flex:0 0 56px;color:#6b7585;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;padding-top:2px}
.ovv{font-size:13.5px;color:#dbe7f5;word-break:break-word}
#ov_now{color:#f5b443;font-weight:600;font-size:13.5px}
#ov_sofar{font-size:13px;color:#8b949e}

/* todos */
.todo{display:flex;align-items:flex-start;gap:9px;padding:8px 9px;border-radius:8px}
.todo .ic{flex:0 0 auto;margin-top:1px;font-size:13px;font-family:'JetBrains Mono',monospace}
.todo .tx{font-size:13px}
.t-completed .ic{color:#3fb950}.t-completed .tx{color:#6b7585;text-decoration:line-through}
.t-in_progress .ic{color:#f5b443}.t-in_progress .tx{color:#f5b443}
.t-pending .ic{color:#5b6573}.t-pending .tx{color:#c9d4e0}

/* flags */
.flagwrap{padding:8px}
.flag{padding:10px 11px;border-radius:9px;background:#0e121a;border:1px solid #1c2330;margin-bottom:7px}
.flag.open{background:#1a1206;border-color:#3a2a0f}
.flag .note{font-size:13px;color:#e6edf3}
.flag.done .note{color:#6b7585;text-decoration:line-through}
.flag .ctx{color:#6b7585;font-size:11px;font-style:italic;margin-top:3px}
.flag .ft{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:#5b6573;margin-top:6px;display:flex;gap:9px}
.link{cursor:pointer}.link.blue{color:#4c8dff}.link.grey{color:#6b7585}.link:hover{text-decoration:underline}
.addflag{width:100%;margin-top:2px;background:#10141c;border:1px dashed #2c333f;color:#8b949e;padding:9px;border-radius:9px;font-family:'Source Sans 3',sans-serif;font-size:12.5px;cursor:pointer}
.addflag:hover{border-color:#f85149}

/* narration */
.narr{display:flex;gap:12px;padding:9px 9px;border-bottom:1px solid #161c27;cursor:pointer;border-radius:8px}
.narr:hover{background:rgba(76,141,255,.06)}
.narr .t{flex:0 0 56px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#5b6573;text-align:right;padding-top:1px}
.narr .x{flex:1;min-width:0;font-size:13px;color:#c9d4e0;line-height:1.45;white-space:pre-wrap;word-break:break-word;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.narr .chev{flex:0 0 auto;color:#5b6573;font-size:12px;align-self:center}
/* message modal — full text, readable */
.msgbody{padding:18px 22px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;font-size:14px;color:#dbe7f5}
.msgbody.cmdmode{white-space:normal}
.msgbody.mdmode{white-space:normal}
.msgbody .mdh{font-size:15px;font-weight:700;margin:18px 0 8px;color:#e6edf3}
.msgbody .mdh:first-child{margin-top:0}
.msgbody .mdp{margin:0 0 11px}
.msgbody .mdul{margin:0 0 11px;padding-left:22px}
.msgbody .mdul li{margin:3px 0}
.msgbody .mdpre{background:#0a0d12;border:1px solid #1c2330;border-radius:8px;padding:11px 13px;overflow:auto;margin:0 0 11px;white-space:pre}
.msgbody .mdpre code{background:none;border:0;padding:0;margin:0;color:#c9d4e0}
.msgbody .mdt{border-collapse:collapse;margin:4px 0 14px;font-size:13px;display:block;overflow-x:auto}
.msgbody .mdt th,.msgbody .mdt td{border:1px solid #2a3340;padding:6px 11px;text-align:left;vertical-align:top}
.msgbody .mdt th{background:#141a24;font-weight:600;color:#e6edf3}
.cmdcode{font-family:'JetBrains Mono',monospace;background:#0a0d12;border:1px solid #1c2330;border-radius:8px;padding:10px 12px;font-size:12.5px;color:#c9d4e0;word-break:break-all;margin-bottom:12px}
.cmdout{margin:0;background:#0a0d12;border:1px solid #1c2330;border-radius:8px;padding:10px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:#8b949e;white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:55vh}
/* clickable rows + 3-line previews, shared across panels */
.clk{cursor:pointer}.item.clk:hover,.todo.clk:hover,.agent.clk:hover{background:rgba(76,141,255,.04)}
.agent .top .chev{margin-left:auto;color:#5b6573;font-size:13px;flex:0 0 auto}
.clamp3{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.ovclk{cursor:pointer}.ovclk:hover{text-decoration:underline}
.nowbanner{cursor:pointer}

/* generic list items (requests/files/commands) */
.item{padding:9px 14px;border-bottom:1px solid #161c27;font-size:13px;overflow-wrap:anywhere}
.item:last-child{border-bottom:0}
.muted{color:#8b949e}
.fpath b{color:#e6edf3}.fpath{word-break:break-all}
.kind{font-size:10px;padding:1px 6px;border-radius:4px;background:#1f6feb33;color:#4c8dff}
.kind.new{background:#3fb95033;color:#3fb950}
.ok{color:#3fb950}.bad{color:#f85149}.cmd{word-break:break-all}
.empty{padding:14px;color:#6b7585;font-size:13px}
code{font-family:'JetBrains Mono',monospace;font-size:.9em;background:#161c27;color:#9fd1ff;padding:1px 5px;border-radius:4px;word-break:break-word}
strong{color:#e6edf3;font-weight:700}
em{font-style:italic}
a{color:#4c8dff}
.raw{margin:0;padding:12px 14px;max-height:42vh;overflow:auto;font-size:11px;color:#8b949e;white-space:pre-wrap;border-top:1px solid #1c2330;font-family:'JetBrains Mono',monospace}
.filerow{cursor:pointer}.filerow:hover{background:rgba(76,141,255,.06)}
.filerow .chev{float:right;color:#5b6573;font-size:11px}
/* diff modal */
.overlay{position:fixed;inset:0;background:rgba(4,6,10,.72);display:none;align-items:center;justify-content:center;z-index:50;padding:24px}
.modal{background:#0e121a;border:1px solid #1c2330;border-radius:12px;width:min(960px,100%);max-height:88vh;display:flex;flex-direction:column;overflow:hidden}
.modal .mh{padding:13px 16px;border-bottom:1px solid #1c2330;display:flex;align-items:center;gap:10px}
.modal .mh .fn{font-weight:700;font-size:14px}
.modal .mh .pp{color:#6b7585;font-size:11px;font-family:'JetBrains Mono',monospace;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.modal .mh .x{cursor:pointer;color:#8b949e;font-size:18px;line-height:1;padding:2px 6px;border-radius:6px}
.modal .mh .x:hover{background:#1c2330;color:#e6edf3}
.modal .mb{overflow:auto;padding:8px 0}
.mh .mdbtn{cursor:pointer;color:#8b949e;font-size:11px;border:1px solid #2a3340;border-radius:6px;padding:3px 9px;white-space:nowrap;flex:0 0 auto}
.mh .mdbtn:hover{color:#e6edf3;border-color:#4c8dff}
.diffop{margin:0 12px 12px}
.diffhd{display:flex;align-items:center;gap:8px;font-size:11px;color:#8b949e;margin:10px 2px 6px}
.diff{background:#0a0d12;border:1px solid #1c2330;border-radius:8px;overflow:auto;font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.5}
.dl{display:block;white-space:pre-wrap;word-break:break-word;padding:0 12px;min-height:1.5em}
.dl.dadd{background:#0f2a2033;color:#3fb950}
.dl.ddel{background:#3a161633;color:#f85149}
.dl.dat{color:#4c8dff}
.dl.dh{color:#5b6573}
@media(max-width:900px){.app{flex-direction:column}.side{width:100%;flex:none;max-height:38vh}}
.foot{text-align:center;padding:10px 12px 12px;border-top:1px solid #1c2330;font-size:10px;color:#8b949e;opacity:.4;letter-spacing:.03em}
.foot a{color:inherit;text-decoration:underline;text-underline-offset:2px}
.bell{cursor:pointer;font-size:14px;margin-left:8px;opacity:.85;user-select:none;line-height:1}
.bell:hover{opacity:1}
.toasts{position:fixed;right:18px;bottom:18px;display:flex;flex-direction:column;gap:10px;z-index:200;max-width:340px}
.toast{display:flex;gap:10px;align-items:flex-start;background:#111820;border:1px solid #26404a;border-left:3px solid #29d398;border-radius:10px;padding:11px 13px;box-shadow:0 8px 24px rgba(0,0,0,.45);cursor:pointer;opacity:0;transform:translateY(10px);transition:opacity .25s,transform .25s}
.toast.show{opacity:1;transform:none}
.toast .tk{color:#29d398;font-weight:700;font-size:14px;line-height:1.3;flex:0 0 auto}
.toast .tt{font-size:13px;font-weight:600;color:#e6edf3}
.toast .tsub{font-size:11.5px;color:#8b949e;margin-top:2px;overflow-wrap:anywhere;line-height:1.35}
</style></head><body>
<div class=app>
<aside class=side>
  <div class=sidehead>
    <div class=sidetop><div class=ttl>Sessions</div><div class=livebadge id=livecount onclick=toggleLiveOnly() title="Click to show live sessions only">0 live</div><span class=bell id=bell onclick=toggleSound() title="Completion sound: on">🔔</span></div>
    <div class=searchbox>
      <span class=ic onclick=doSearch()>⌕</span>
      <input id=q placeholder="search sessions…" autocomplete=off>
      <span class=ic id=qclear onclick=clearSearch() style=display:none>✕</span>
    </div>
  </div>
  <div class=slist id=slist><div class=empty>loading…</div></div>
  <div class=sidefoot><span id=hostlbl>localhost:8787</span><span style=color:#29d398>● connected</span></div>
</aside>
<main>
<header class=hd>
  <div class=hero>
    <div class=ring>
      <svg width=122 height=122 viewBox="0 0 122 122">
        <circle cx=61 cy=61 r=51 fill=none stroke="#1b2230" stroke-width=11></circle>
        <circle id=ring cx=61 cy=61 r=51 fill=none stroke="url(#g1a)" stroke-width=11 stroke-linecap=round stroke-dasharray=320.4 stroke-dashoffset=320.4></circle>
        <defs><linearGradient id=g1a x1=0 y1=0 x2=1 y2=1><stop offset=0 stop-color="#4c8dff"></stop><stop offset=1 stop-color="#29d398"></stop></linearGradient></defs>
      </svg>
      <div class=ringctr><div class=ringpct><span id=ringpct>0</span><span>%</span></div><div class=ringsub id=ringsub>0 of 0 tasks</div></div>
    </div>
    <div class=htitle>
      <div class=htop><h2 id=htitle>Pick a session</h2><span class=activebadge id=activebadge style=display:none><span class=dot></span>active</span></div>
      <div class=hmeta id=hmeta>Pick a recent session or search on the left.</div>
      <div class=chips id=chips></div>
    </div>
  </div>
  <div class=nowbanner id=nowbanner style=display:none onclick="openText('Now working on','',curOv.now||'')">
    <span class=dot></span>
    <div style=min-width:0>
      <div class=lbl>Now working on</div>
      <div class=txt id=nowtext></div>
    </div>
  </div>
  <div class=srcnote id=srcnote style=display:none></div>
</header>
<div class=body>
  <div class="card span2" id=bgpanel style=display:none>
    <h2><span>🤖 Background agents</span><span class=cnt id=bgc style=color:#f5b443></span></h2>
    <div class=bggrid id=bg></div>
  </div>
  <div class="card span2" id=shpanel style=display:none>
    <h2><span>⌨ Background shells</span><span class=cnt id=shc style=color:#f5b443></span></h2>
    <div class=bggrid id=sh></div>
  </div>
  <div class="card span2" id=card_summary>
    <h2>Session summary</h2>
    <div class=ov>
      <div class=ovrow><span class=ovk>Goal</span><span id=ov_goal class="ovv ovclk" onclick="openText('Goal','',curOv.goal||'')">—</span></div>
      <div class=ovrow><span class=ovk>Now</span><span id=ov_now class=ovclk onclick="openText('Now working on','',curOv.now||'')">—</span></div>
      <div class=ovrow><span class=ovk>So far</span><span id=ov_sofar class=ovclk onclick="openText('So far','',curOv.sofar||'')">—</span></div>
      <div class=ovrow id=ov_crow style=display:none><span class=ovk>Commits</span><span id=ov_commits class=ovv></span></div>
    </div>
  </div>
  <div class=card id=card_todos>
    <h2><span>Progress</span><span class=cnt id=todoc></span></h2>
    <div class=cbody style="padding:6px 8px;max-height:300px" id=todos><div class=empty>—</div></div>
  </div>
  <div class=card>
    <h2><span>🚩 Flags</span><span class=cnt id=flagc style=color:#f85149></span></h2>
    <div class=cbody style=max-height:300px>
      <div class=flagwrap id=flags><div class=empty>—</div></div>
      <button class=addflag onclick=addFlag()>🚩 Flag an issue or gap</button>
    </div>
  </div>
  <div class="card span2">
    <h2><span>Narration — what Claude is doing, in its own words</span><button class=mini onclick=toggleRaw()>&lt;/&gt; debug</button></h2>
    <div class=cbody style="padding:6px 8px;max-height:230px" id=narr><div class=empty>—</div></div>
    <pre id=raw class=raw style=display:none></pre>
  </div>
  <div class=card>
    <h2><span>Requests</span><span class=cnt id=reqc></span></h2>
    <div class=cbody id=reqs><div class=empty>—</div></div>
  </div>
  <div class=card id=card_files>
    <h2><span>Files</span><span class=cnt id=filec></span></h2>
    <div class=cbody id=files><div class=empty>—</div></div>
  </div>
  <div class="card span2" id=card_cmds>
    <h2><span>Commands</span><span class=cnt id=cmdc></span></h2>
    <div class=cbody id=cmds><div class=empty>—</div></div>
  </div>
</div>
</main></div>
<footer class=foot>Made with ❤️ in Bengaluru. Developed by <a href="https://tinyurl.com/pritamm93" target=_blank rel=noopener>Pritam</a>.</footer>
<div class=toasts id=toasts></div>
<div class=overlay id=diffmodal onclick="if(event.target===this)closeDiff()">
  <div class=modal>
    <div class=mh><span class=fn id=diffname>file</span><span class=pp id=diffpath></span><span class=mdbtn id=diffmd onclick=toggleDiffMd() style=display:none>◧ Rendered</span><span class=x onclick=closeDiff()>✕</span></div>
    <div class=mb id=diffbody></div>
  </div>
</div>
<div class=overlay id=msgmodal onclick="if(event.target===this)closeMsg()">
  <div class=modal>
    <div class=mh><span class=fn id=msgtitle>Narration</span><span class=pp id=msgwhen></span><span class=x onclick=closeMsg()>✕</span></div>
    <div class=msgbody id=msgbody></div>
  </div>
</div>
<input type=hidden id=sid>
<script>
let cur=localStorage.getItem("sid")||"", timer=null;
const $=id=>document.getElementById(id);
const esc=s=>(s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
// tiny inline markdown for narration/requests: escape first, then `code`,
// **bold**, *italic*, [text](url). No `_` italics — identifiers use underscores.
function md(s){
  let h=esc(s);
  h=h.replace(/`([^`]+)`/g,(m,c)=>`<code>${c}</code>`);
  h=h.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>");
  h=h.replace(/(^|[^*])\*(?!\s)([^*\n]+?)\*/g,"$1<em>$2</em>");
  h=h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target=_blank rel=noopener>$1</a>');
  return h;
}
// block-level markdown for the full-text modal: headers, tables, lists, code fences
function mdBlock(s){
  const L=(s||"").replace(/\r/g,"").split("\n"), out=[]; let i=0;
  const sep=l=>/^[\s|:-]+$/.test(l)&&l.includes("-")&&l.includes("|");
  const cells=l=>l.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(c=>c.trim());
  while(i<L.length){
    const l=L[i];
    if(/^\s*```/.test(l)){ i++; const b=[]; while(i<L.length&&!/^\s*```/.test(L[i])){b.push(L[i]);i++;} i++;
      out.push(`<pre class=mdpre><code>${esc(b.join("\n"))}</code></pre>`); continue; }
    const hm=l.match(/^(#{1,6})\s+(.*)$/);
    if(hm){ const lv=Math.min(hm[1].length,4)+1; out.push(`<h${lv} class=mdh>${md(hm[2])}</h${lv}>`); i++; continue; }
    if(l.includes("|")&&i+1<L.length&&sep(L[i+1])){
      const hd=cells(l); i+=2; const rs=[];
      while(i<L.length&&L[i].includes("|")&&L[i].trim()){ rs.push(cells(L[i])); i++; }
      out.push("<table class=mdt><thead><tr>"+hd.map(c=>`<th>${md(c)}</th>`).join("")+"</tr></thead><tbody>"+
        rs.map(r=>"<tr>"+r.map(c=>`<td>${md(c)}</td>`).join("")+"</tr>").join("")+"</tbody></table>"); continue; }
    if(/^\s*[-*+]\s+/.test(l)){ const it=[];
      while(i<L.length&&/^\s*[-*+]\s+/.test(L[i])){ it.push(`<li>${md(L[i].replace(/^\s*[-*+]\s+/,""))}</li>`); i++; }
      out.push("<ul class=mdul>"+it.join("")+"</ul>"); continue; }
    if(/^\s*\d+\.\s+/.test(l)){ const it=[];
      while(i<L.length&&/^\s*\d+\.\s+/.test(L[i])){ it.push(`<li>${md(L[i].replace(/^\s*\d+\.\s+/,""))}</li>`); i++; }
      out.push("<ol class=mdul>"+it.join("")+"</ol>"); continue; }
    if(!l.trim()){ i++; continue; }
    const p=[];
    while(i<L.length&&L[i].trim()&&!/^#{1,6}\s/.test(L[i])&&!/^\s*[-*+]\s+/.test(L[i])&&!/^\s*\d+\.\s+/.test(L[i])&&!/^\s*```/.test(L[i])&&!(L[i].includes("|")&&i+1<L.length&&sep(L[i+1]))){ p.push(L[i]); i++; }
    out.push(`<p class=mdp>${md(p.join(" "))}</p>`);
  }
  return out.join("");
}
function ago(sec){sec=Math.max(0,sec|0);if(sec<60)return sec+"s ago";if(sec<3600)return(sec/60|0)+"m ago";if(sec<86400)return(sec/3600|0)+"h ago";return(sec/86400|0)+"d ago"}
function base(p){return (p||"").split("/").pop()}
const SRC={"claude-desktop":"🖥 Desktop","cli":"⌨ CLI","claude-vscode":"⧉ VS Code","auggie":"◆ Auggie"};
const srcLabel=v=>SRC[v]||v||"";
const CIRC=2*Math.PI*51; // progress-ring circumference

let sessions=[], searchResults=null, liveOnly=false;
const LIVE=300; // seconds since last activity a session stays "live" (5 min)
function hl(text,q){
  const e=esc(text); if(!q)return e;
  const re=new RegExp("("+q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")+")","ig");
  return e.replace(re,"<b>$1</b>");
}
function renderSide(){
  const now=Date.now()/1000;
  if(searchResults!==null){       // search mode: show matches instead of the full list
    const q=$("q").value.trim();
    $("livecount").textContent=`${searchResults.length} match${searchResults.length==1?"":"es"}`;
    $("slist").innerHTML=searchResults.length?searchResults.map(s=>{
      const live=now-s.mtime<LIVE;
      return `<div class="sitem ${s.id===cur?'active':''}" onclick="pick('${s.id}')" title="${esc(s.title||'')}">`+
        `<div class=srow1><span class="dot ${live?'live':''}"></span><span class=nm>${esc(s.title||s.project||s.id.slice(0,8))}</span>`+
        `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename">✎</span></div>`+
        `<div class=smeta><span class=proj>${esc(s.project)}</span>${s.inQuery?' · <span class=smatch>your query</span>':''} · <span>${s.matches}×</span></div>`+
        (s.snippet?`<div class=ssnip>${hl(s.snippet,q)}</div>`:"")+
        `</div>`;
    }).join(""):`<div class=empty>no sessions match “${esc(q)}”</div>`;
    return;
  }
  const liveN=sessions.filter(s=>now-s.mtime<LIVE).length;
  const lc=$("livecount");
  lc.textContent=liveOnly?`${liveN} live ✕`:`${liveN} live`;
  lc.title=liveOnly?"Showing live only — click to show all":"Click to show live sessions only";
  lc.classList.toggle("on",liveOnly);
  const shown=liveOnly?sessions.filter(s=>now-s.mtime<LIVE):sessions;
  $("slist").innerHTML=shown.length?shown.map(s=>{
    const live=now-s.mtime<LIVE;
    const label=s.title||s.project||s.id.slice(0,8);
    const bits=[`<span class=proj>${s.title?esc(s.project):s.id.slice(0,8)}</span>`];
    if(s.source)bits.push(srcLabel(s.source));
    bits.push(ago(now-s.mtime));
    return `<div class="sitem ${s.id===cur?'active':''}" onclick="pick('${s.id}')" title="${esc((s.prompt||s.title||'(no prompt)')+'\n'+(s.cwd||''))}">`+
      `<div class=srow1><span class="dot ${live?'live':''}"></span><span class=nm>${esc(label)}</span>`+
      `<span class=ren onclick="renameSession(event,'${s.id}')" title="Rename this session">✎</span></div>`+
      `<div class=smeta>${bits.join(" · ")}</div></div>`;
  }).join(""):`<div class=empty>${liveOnly?"no live sessions":"no sessions"}</div>`;
}
function toggleLiveOnly(){liveOnly=!liveOnly;renderSide();}
async function loadSide(){
  try{sessions=await(await fetch("/api/list")).json();}catch(e){return}
  renderSide();
}
function pick(id){$("sid").value=id;track();renderSide();}
async function doSearch(){
  const q=$("q").value.trim();
  if(!q){clearSearch();return}
  $("qclear").style.display="";
  $("slist").innerHTML="<div class=empty>searching…</div>";
  try{searchResults=await(await fetch("/api/search?q="+encodeURIComponent(q))).json()}
  catch(e){searchResults=[]}
  renderSide();
}
function clearSearch(){searchResults=null;$("q").value="";$("qclear").style.display="none";renderSide();}
async function renameSession(e,id){
  e.stopPropagation();
  const s=sessions.find(x=>x.id===id)||{};
  const t=prompt("Rename session (leave blank for the auto title):", s.title||"");
  if(t===null)return;
  await fetch("/api/title",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:id,title:t})});
  await loadSide();
  if(id===cur)poll();  // refresh the main header title too
}
async function start(){
  await loadSide();
  // fall back to the newest session if nothing is stored or the stored id is stale
  if((!cur||!sessions.some(s=>s.id===cur))&&sessions[0])cur=sessions[0].id;
  if(cur){$("sid").value=cur;track();renderSide();}
  setInterval(loadSide,5000);
}
function track(){
  cur=$("sid").value.trim();localStorage.setItem("sid",cur);
  if(timer)clearInterval(timer);
  if(!cur)return;
  poll();timer=setInterval(poll,2000);
}
let lastData=null;
// ---- completion notifications: agent/shell running -> done ----
let soundOn=localStorage.getItem("soundOff")!=="1";
let notifSession=null, notifRunning=null, audioCtx=null;
function setBell(){const b=$("bell");if(b){b.textContent=soundOn?"🔔":"🔕";b.title="Completion sound: "+(soundOn?"on":"muted");}}
function toggleSound(){soundOn=!soundOn;localStorage.setItem("soundOff",soundOn?"0":"1");setBell();if(soundOn)beep();}
function beep(){
  try{
    audioCtx=audioCtx||new (window.AudioContext||window.webkitAudioContext)();
    if(audioCtx.state==="suspended")audioCtx.resume();
    const t=audioCtx.currentTime;
    [784,1175].forEach((f,i)=>{                     // two-tone "ding"
      const o=audioCtx.createOscillator(),g=audioCtx.createGain();
      o.type="sine";o.frequency.value=f;o.connect(g);g.connect(audioCtx.destination);
      const s=t+i*0.13;
      g.gain.setValueAtTime(0,s);g.gain.linearRampToValueAtTime(0.16,s+0.02);
      g.gain.exponentialRampToValueAtTime(0.001,s+0.22);
      o.start(s);o.stop(s+0.24);
    });
  }catch(e){}
}
function toast(msg,sub){
  const el=document.createElement("div");
  el.className="toast";
  el.innerHTML=`<span class=tk>✓</span><div><div class=tt>${esc(msg)}</div>${sub?`<div class=tsub>${esc(sub)}</div>`:""}</div>`;
  el.onclick=()=>el.remove();
  $("toasts").appendChild(el);
  requestAnimationFrame(()=>el.classList.add("show"));
  setTimeout(()=>{el.classList.remove("show");setTimeout(()=>el.remove(),300);},7000);
}
function checkCompletions(d){
  const items=[...(d.agents_bg||[]).map(a=>({id:"a:"+a.id,name:a.task||a.id,kind:"agent",run:a.running})),
               ...(d.shells||[]).map(s=>({id:"s:"+s.id,name:s.desc||s.cmd,kind:"shell",run:s.running}))];
  const running=new Set(items.filter(x=>x.run).map(x=>x.id));
  // reset baseline (no notify) on session switch or first poll
  if(notifSession!==cur||notifRunning===null){notifSession=cur;notifRunning=running;return;}
  for(const x of items){
    if(!x.run && notifRunning.has(x.id)){
      toast(x.kind==="shell"?"Background shell finished":"Background agent finished", (x.name||"").slice(0,90));
      if(soundOn)beep();
    }
  }
  notifRunning=running;
}
async function poll(){
  if(!cur)return;
  let d;try{d=await(await fetch("/api/session?id="+encodeURIComponent(cur))).json()}catch(e){return}
  if(d.error){$("hmeta").innerHTML=`<span class=dot></span> ${esc(d.error)}: ${esc(cur)}`;return}
  lastData=d;render(d);loadFlags();checkCompletions(d);
}
const KICON={commit:"⎇",test:"✓",install:"⬇",build:"🔨",git:"⎇",cmd:"$"};
function render(d){
  const idle=d.now-d.mtime, live=idle<LIVE;
  const m=d.meta||{}, c=d.counts||{};
  const title=m.title||m.customTitle||m.aiTitle||cur.slice(0,8);
  const src=srcLabel(m.entrypoint);
  if(title)document.title=title+" · tracker";

  // progress ring
  const pct=c.todos?Math.round(c.done/c.todos*100):0;
  const ring=$("ring");
  ring.setAttribute("stroke-dasharray",CIRC.toFixed(1));
  ring.setAttribute("stroke-dashoffset",(CIRC*(1-pct/100)).toFixed(1));
  $("ringpct").textContent=pct;
  $("ringsub").textContent=`${c.done||0} of ${c.todos||0} tasks`;

  // title + active badge
  $("htitle").textContent=title;
  $("activebadge").style.display=live?"inline-flex":"none";
  if(!live){
    $("activebadge").style.display="inline-flex";
    $("activebadge").innerHTML='<span class=dot></span>idle '+ago(idle);
    $("activebadge").style.color="#8b949e";$("activebadge").style.background="#10141c";$("activebadge").style.borderColor="#2c333f";
  }else{
    $("activebadge").innerHTML='<span class="dot live"></span>active';
    $("activebadge").style.color="#29d398";$("activebadge").style.background="#0f2a20";$("activebadge").style.borderColor="#1c4634";
  }

  // meta line
  const meta=[];
  if(m.cwd)meta.push("📁 "+esc(base(m.cwd)));
  if(m.gitBranch)meta.push("⎇ "+esc(m.gitBranch));
  if(src)meta.push("⌨ "+esc(src));
  meta.push(`${(d.tokens.in/1000|0)}k in / ${(d.tokens.out/1000|0)}k out`);
  if(m.version)meta.push("v"+esc(m.version));
  $("hmeta").innerHTML=meta.map(x=>`<span>${x}</span>`).join("");

  const chip=(n,v,cls,tgt)=>v?`<span class="chip ${cls||''} ${tgt?'clk':''}"${tgt?` onclick="flashTo('${tgt}')"`:''}><span class=lbl>${n}</span><b>${v}</b></span>`:"";
  $("chips").innerHTML=
    chip("✓ done",`${c.done}/${c.todos}`,"good","card_todos")+chip("＋ created",c.created,"blue","card_files")+chip("✎ edited",c.edited,"","card_files")+
    chip("👁 read",c.read,"","card_files")+chip("⎇ commits",c.commits,"","card_cmds")+chip("tests",c.tests,"","card_cmds")+
    chip("✗ failed",c.tests_failed,"bad","card_cmds")+chip("⚠ errors",c.errors,"bad","card_cmds")+
    chip("agents",c.agents,"","bgpanel")+chip("searches",c.searches);

  // background agents (click to read full narration)
  // background agents — running shown; finished tucked behind a disclosure
  const bg=d.agents_bg||[];
  curAgents=bg;
  $("bgpanel").style.display=bg.length?"flex":"none";
  if(bg.length){
    const runN=bg.filter(a=>a.running).length;
    $("bgc").textContent=runN?`${runN} running`:"all finished";
    const card=(a,i)=>
      `<div class="agent clk" onclick="openAgent(${i})"><div class=top><span class="dot ${a.running?'amber':''}"></span><span class=nm>${esc(a.task||a.id)}</span>`+
      (a.wf?` <span class=tag>${esc(a.wf.slice(0,12))}</span>`:"")+`<span class=chev>›</span></div>`+
      `<div class=last>${esc(a.last||"")}</div>`+
      `<div class=ft><span>${a.tools} tools</span><span>·</span><span style=color:${a.running?'#f5b443':'#6b7585'}>${a.running?'running':'done'}</span>`+
      `${a.ts?"<span>·</span><span>"+ago(d.now-Date.parse(a.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    bg.forEach((a,i)=>(a.running?run:done).push(card(a,i)));
    let html=run.length?run.join(""):"<div class=empty>No agents running right now.</div>";
    if(done.length){
      html+=`<div class=disclosure onclick=toggleAgentsDone()>${showAgentsDone?"▾ Hide":"▸ Show"} ${done.length} finished</div>`;
      if(showAgentsDone)html+=done.join("");
    }
    $("bg").innerHTML=html;
  }

  // background shells — same pattern (click a card to read full output)
  const shl=d.shells||[];
  curShells=shl;
  $("shpanel").style.display=shl.length?"flex":"none";
  if(shl.length){
    const shRun=shl.filter(s=>s.running).length;
    $("shc").textContent=shRun?`${shRun} running`:"all finished";
    const card=(s,i)=>
      `<div class="agent clk" onclick="openShell(${i})"><div class=top><span class="dot ${s.running?'amber':''}"></span><span class=nm>${esc(s.desc||s.cmd)}</span><span class=chev>›</span></div>`+
      `<div class="last mono" style=font-size:11px>${esc(s.last||s.cmd)}</div>`+
      `<div class=ft><span>${esc(s.id)}</span><span>·</span><span style=color:${s.running?'#f5b443':'#6b7585'}>${s.running?'running':'done'}</span>`+
      `${s.ts?"<span>·</span><span>"+ago(d.now-Date.parse(s.ts)/1000)+"</span>":""}</div></div>`;
    const run=[],done=[];
    shl.forEach((s,i)=>(s.running?run:done).push(card(s,i)));
    let html=run.length?run.join(""):"<div class=empty>No shells running right now.</div>";
    if(done.length){
      html+=`<div class=disclosure onclick=toggleShellsDone()>${showShellsDone?"▾ Hide":"▸ Show"} ${done.length} finished</div>`;
      if(showShellsDone)html+=done.join("");
    }
    $("sh").innerHTML=html;
  }

  $("srcnote").style.display=d.note?"block":"none";
  $("srcnote").textContent=d.note||"";

  // summary (markdown + click to read full)
  const ov=d.overview||{};
  curOv=ov;
  $("ov_goal").innerHTML=md(ov.goal||"—");
  $("ov_now").innerHTML="▶ "+md(ov.now||(live?"working…":"idle"));
  $("ov_sofar").innerHTML=md(ov.sofar||"—");
  const ocm=ov.commits||[];
  $("ov_crow").style.display=ocm.length?"flex":"none";
  $("ov_commits").textContent=ocm.join("  ·  ");

  // now banner (markdown + click to read full)
  $("nowbanner").style.display=ov.now?"flex":"none";
  $("nowtext").innerHTML="▶ "+md(ov.now||"")+'<span class=cursor>▍</span>';

  // narration
  const nr=d.narrative||[];
  curNarr=nr;
  $("narr").innerHTML=nr.length?nr.map((x,i)=>
    `<div class=narr onclick="openMsg(${i})" title="Read full message"><span class=t>${x.t?ago(d.now-Date.parse(x.t)/1000):""}</span><span class=x>${md(x.text)}</span><span class=chev>›</span></div>`).join(""):"<div class=empty>no narration yet</div>";

  // todos
  const td=d.todos||[];
  const order={completed:0,in_progress:1,pending:2};
  const sorted=[...td].sort((a,b)=>(order[a.status]??3)-(order[b.status]??3));
  const TICON={completed:"✓",in_progress:"▶",pending:"○"};
  $("todoc").textContent=td.length?c.done+"/"+td.length:"";
  curTodos=sorted;
  $("todos").innerHTML=td.length?sorted.map((t,i)=>
    `<div class="todo t-${t.status} clk" onclick="openTodo(${i})"><span class=ic>${TICON[t.status]||"○"}</span><span class=tx>${md(t.content)}</span></div>`).join(""):"<div class=empty>no todos in this session</div>";

  // requests (markdown + click to read full)
  curReqs=[...(d.requests||[])].reverse();
  $("reqc").textContent=curReqs.length||"";
  $("reqs").innerHTML=curReqs.length?curReqs.map((r,i)=>
    `<div class="item clk" onclick="openReq(${i})"><div class="mdtext clamp3">${md(r.text)}</div><div class="muted mono" style=font-size:11px;margin-top:3px>${r.t?ago(d.now-Date.parse(r.t)/1000):""}</div></div>`).join(""):"<div class=empty>—</div>";

  // files
  const fs=d.files||[];
  curFiles=fs;
  $("filec").textContent=fs.length||"";
  $("files").innerHTML=fs.length?fs.map((f,i)=>
    `<div class="item filerow" onclick="openDiff(${i})" title="View diff"><div class=fpath><span class="kind ${f.created?'new':''}">${f.created?'created':'edited'}</span> <b>${esc(base(f.path))}</b><span class=chev>diff ›</span></div>`+
    `<div class="muted mono" style=font-size:11px;margin-top:3px>${esc(f.path.replace("/"+base(f.path),""))} · ${f.ops}× · ${ago(d.now-Date.parse(f.last)/1000)}</div></div>`).join(""):"<div class=empty>no files written yet</div>";

  // commands (click to see output)
  curCmds=d.commands||[];
  $("cmdc").textContent=curCmds.length||"";
  $("cmds").innerHTML=curCmds.length?curCmds.map((x,i)=>
    `<div class="item clk" onclick="openCmd(${i})"><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> <span class=muted>${KICON[x.kind]||'$'}</span> `+
    `<span class="cmd mono">${esc(x.cmd)}</span> <span class=chev style=float:right;color:#5b6573>output ›</span></div>`).join(""):"<div class=empty>—</div>";
}
let curFiles=[], curDiffFile=null, curDiffOps=[], diffMode="diff";
const isMd=p=>/\.(md|markdown|mdx)$/i.test(p||"");
async function openDiff(i){
  const f=curFiles[i]; if(!f||!cur)return;
  curDiffFile=f; curDiffOps=[];
  diffMode=isMd(f.path)?"md":"diff";   // markdown files render by default
  $("diffname").textContent=base(f.path);
  $("diffpath").textContent=f.path;
  updateMdToggle();
  $("diffbody").innerHTML="<div class=empty>loading…</div>";
  $("diffmodal").style.display="flex";
  try{const d=await(await fetch(`/api/diff?id=${encodeURIComponent(cur)}&file=${encodeURIComponent(f.path)}`)).json();
      curDiffOps=(d.ops||[]).reverse();}   // newest edit first
  catch(e){curDiffOps=[];}
  renderDiffView();
}
function updateMdToggle(){
  const btn=$("diffmd"); if(!btn)return;
  btn.style.display=isMd(curDiffFile&&curDiffFile.path)?"":"none";
  btn.textContent=diffMode==="md"?"◧ Diff":"◧ Rendered";
}
function toggleDiffMd(){ diffMode=diffMode==="md"?"diff":"md"; updateMdToggle(); renderDiffView(); }
async function renderDiffView(){
  if(diffMode==="md"){ await renderMdView(); return; }
  const now=Date.now()/1000;
  $("diffbody").innerHTML=curDiffOps.length?curDiffOps.map(op=>
    `<div class=diffop><div class=diffhd><span class="kind ${op.kind==='created'?'new':''}">${op.kind}</span>`+
    `${op.ts?`<span>${ago(now-Date.parse(op.ts)/1000)}</span>`:""}</div>`+
    `<div class=diff>${renderDiff(op.diff)}</div></div>`).join(""):
    "<div class=empty>no recorded edits for this file</div>";
}
async function renderMdView(){
  $("diffbody").innerHTML="<div class=empty>rendering…</div>";
  let content="";
  try{const r=await(await fetch("/api/file?path="+encodeURIComponent(curDiffFile.path))).json();
      if(!r.error) content=r.content||"";}catch(e){}
  if(!content) content=reconstructAfter(curDiffOps);   // fallback: rebuild from the diff
  $("diffbody").innerHTML=content
    ? `<div class="msgbody mdmode" style=overflow:visible>${mdBlock(content)}</div>`
    : "<div class=empty>could not read the file to render</div>";
}
function reconstructAfter(ops){
  if(!ops.length)return "";
  return (ops[0].diff||"").split("\n")
    .filter(l=>!/^(@@|\+\+\+|---)/.test(l) && l[0]!=="-")
    .map(l=> (l[0]==="+"||l[0]===" ") ? l.slice(1) : l).join("\n");
}
function renderDiff(t){
  return (t||"").split("\n").map(l=>{
    let cls="dl";
    if(l.startsWith("+++")||l.startsWith("---"))cls="dl dh";
    else if(l.startsWith("@@"))cls="dl dat";
    else if(l[0]==="+")cls="dl dadd";
    else if(l[0]==="-")cls="dl ddel";
    return `<span class="${cls}">${esc(l)||" "}</span>`;
  }).join("");
}
function closeDiff(){$("diffmodal").style.display="none";}
let curNarr=[], curCmds=[], curReqs=[], curOv={};
const tago=t=>t?ago(Date.now()/1000-Date.parse(t)/1000):"";
// generic readable modal: title + optional time + markdown body
function openText(title,when,text){
  $("msgtitle").textContent=title;
  $("msgwhen").textContent=when||"";
  $("msgbody").className="msgbody mdmode";
  $("msgbody").innerHTML=mdBlock(text)||"<span class=muted>(empty)</span>";
  $("msgmodal").style.display="flex";
}
function openMsg(i){const n=curNarr[i]; if(n)openText("Narration",tago(n.t),n.text);}
function openReq(i){const r=curReqs[i]; if(r)openText("Request",tago(r.t),r.text);}
async function openCmd(i){
  const x=curCmds[i]; if(!x||!cur)return;
  $("msgtitle").textContent="Command";
  $("msgwhen").textContent=tago(x.t);
  $("msgbody").className="msgbody cmdmode";
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> ${esc(x.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;
  try{d=await(await fetch(`/api/output?id=${encodeURIComponent(cur)}&cmd=${encodeURIComponent(x.id)}`)).json()}
  catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode><span class="${x.ok?'ok':'bad'}">${x.ok?'✓':'✗'}</span> ${esc(d.cmd||x.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output captured</div>");
}
let curShells=[], curAgents=[], curTodos=[];
let showAgentsDone=false, showShellsDone=false;
function toggleAgentsDone(){showAgentsDone=!showAgentsDone; if(lastData)render(lastData);}
function toggleShellsDone(){showShellsDone=!showShellsDone; if(lastData)render(lastData);}
function openTodo(i){
  const t=curTodos[i]; if(!t)return;
  openText("Task",t.status,"**"+(t.content||"")+"**"+(t.desc?"\n\n"+t.desc:""));
}
async function openShell(i){
  const s=curShells[i]; if(!s||!cur)return;
  $("msgtitle").textContent="Shell · "+s.id;
  $("msgwhen").textContent=(s.running?"running":"done")+(s.ts?" · "+tago(s.ts):"");
  $("msgbody").className="msgbody cmdmode";
  $("msgbody").innerHTML=`<div class=cmdcode>${esc(s.cmd)}</div><div class=empty>loading output…</div>`;
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/shell?id=${encodeURIComponent(cur)}&shell=${encodeURIComponent(s.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=`<div class=cmdcode>${esc(d.cmd||s.cmd)}</div>`+
    (d.out?`<pre class=cmdout>${esc(d.out)}</pre>`:"<div class=empty>no output yet</div>");
}
async function openAgent(i){
  const a=curAgents[i]; if(!a||!cur)return;
  $("msgtitle").textContent="Agent";
  $("msgwhen").textContent=(a.running?"running":"done")+(a.ts?" · "+tago(a.ts):"");
  $("msgbody").className="msgbody";
  $("msgbody").innerHTML="<div class=empty>loading…</div>";
  $("msgmodal").style.display="flex";
  let d;try{d=await(await fetch(`/api/agent?id=${encodeURIComponent(cur)}&agent=${encodeURIComponent(a.aid||a.id)}`)).json()}catch(e){d={}}
  $("msgbody").innerHTML=(d.task?`<div class=cmdcode>${esc(d.task)}</div>`:"")+
    `<div class="muted mono" style=margin-bottom:10px>${d.tools||0} tool calls · ${d.running?'running':'done'}</div>`+
    (d.narration?md(d.narration):"<div class=empty>no narration recorded</div>");
}
function closeMsg(){$("msgmodal").style.display="none";}
function flashTo(id){
  const el=$(id); if(!el||el.style.display==="none")return;
  el.scrollIntoView({behavior:"smooth",block:"start"});
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  setTimeout(()=>el.classList.remove("flash"),1400);
}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeDiff();closeMsg();}});
let flags=[];
async function loadFlags(){try{flags=await(await fetch("/api/flags")).json()}catch(e){return}renderFlags()}
function renderFlags(){
  const mine=flags.filter(f=>f.session===cur).sort((a,b)=>(a.resolved-b.resolved)||b.ts-a.ts);
  const open=mine.filter(f=>!f.resolved).length;
  $("flagc").textContent=mine.length?`${open} open / ${mine.length}`:"";
  const now=Date.now()/1000;
  $("flags").innerHTML=mine.length?mine.map(f=>
    `<div class="flag ${f.resolved?'done':'open'}"><div class=note>${f.resolved?'✓ ':'🚩 '}${esc(f.note)}</div>`+
    (f.context?`<div class=ctx>while: ${esc(f.context)}</div>`:"")+
    `<div class=ft><span>${ago(now-f.ts)}</span>`+
    `<span class="link blue" onclick="resolveFlag(${f.id})">${f.resolved?'reopen':'✓ resolve'}</span>`+
    `<span class="link grey" onclick="delFlag(${f.id})">delete</span></div></div>`).join(""):
    "<div class=empty>no flags yet</div>";
}
async function addFlag(){
  if(!cur){alert("Pick a session first");return}
  const note=prompt("🚩 Flag an issue or gap to resolve:");
  if(!note||!note.trim())return;
  const s=sessions.find(x=>x.id===cur)||{};
  await fetch("/api/flags",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session:cur,project:s.project||"",note,context:($("nowtext").textContent||"").replace(/[▶▍]/g,"").trim()})});
  loadFlags();
}
async function flagAction(path,id){
  await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id})});
  loadFlags();
}
function resolveFlag(id){flagAction("/api/flags/resolve",id)}
function delFlag(id){if(confirm("Delete this flag?"))flagAction("/api/flags/delete",id)}
function toggleRaw(){const r=$("raw");
  if(r.style.display==="none"){r.textContent=lastData?JSON.stringify(lastData,null,2):"no data yet";r.style.display="block"}
  else r.style.display="none";
}
$("q").addEventListener("keydown",e=>{if(e.key==="Enter")doSearch();if(e.key==="Escape")clearSearch();});
setBell();
start();
</script></body></html>"""


def _selfcheck():
    import tempfile
    rows = [
        {"type": "user", "cwd": "/x/proj", "gitBranch": "main", "version": "1.0",
         "message": {"role": "user", "content": "build the thing"}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/foo</command-name>"}},
        {"type": "assistant", "timestamp": "2026-06-22T10:00:00.000Z",
         "message": {"usage": {"input_tokens": 100, "output_tokens": 20},
                     "content": [
                         {"type": "text", "text": "starting"},
                         {"type": "tool_use", "name": "TodoWrite",
                          "input": {"todos": [
                              {"content": "a", "status": "completed", "activeForm": "doing a"},
                              {"content": "b", "status": "in_progress", "activeForm": "doing b"}]}},
                         {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/proj/foo.py", "content": "line1\nline2\n"}},
                         {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/proj/foo.py", "old_string": "line1", "new_string": "LINE1"}},
                         {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/proj/bar.py"}},
                         {"type": "tool_use", "id": "t1", "name": "Bash",
                          "input": {"command": "pytest -q"}},
                         {"type": "tool_use", "id": "t2", "name": "Bash",
                          "input": {"command": "git commit -m \"add foo\""}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "boom"}]}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write("garbage not json\n")  # must be skipped, not crash
        path = f.name
    d = parse_session(path)
    df = file_diffs(path, "/x/proj/foo.py")  # before unlink — reads the file again
    co = command_output(path, "t1")
    os.unlink(path)
    c = d["counts"]
    assert len(d["todos"]) == 2 and c["done"] == 1, d["todos"]
    assert d["files"][0]["path"] == "/x/proj/foo.py" and d["files"][0]["ops"] == 2, d["files"]
    assert d["files"][0]["created"] is True, "Write should mark created"
    # per-file diffs reconstructed from the transcript (Write content, Edit old/new)
    assert len(df) == 2 and df[0]["kind"] == "created" and df[1]["kind"] == "edited", df
    assert "+line1" in df[0]["diff"], df[0]["diff"]
    assert "-line1" in df[1]["diff"] and "+LINE1" in df[1]["diff"], df[1]["diff"]
    # command output fetched on click: command text + its (failed) result output
    assert co["cmd"] == "pytest -q" and co["ok"] is False and "boom" in co["out"], co
    assert c["created"] == 1 and c["read"] == 1, c
    assert d["commits"][0]["msg"] == "add foo", d["commits"]
    assert c["tests"] == 1 and c["tests_failed"] == 1, "failed pytest via is_error link"
    assert [r["text"] for r in d["requests"]] == ["build the thing"], d["requests"]
    assert d["tokens"]["in"] == 100
    assert [n["text"] for n in d["narrative"]] == ["starting"], d["narrative"]
    ov = d["overview"]
    assert ov["goal"] == "build the thing", ov
    assert ov["now"] == "▶ doing b", ov
    assert "ouched 1 file(s) (foo.py)" in ov["sofar"], ov
    assert "ran 2 command(s)" in ov["sofar"] and "1 commit" in ov["sofar"], ov
    assert ov["commits"] == ["add foo"], ov
    assert d["meta"]["title"] == "Build the thing", d["meta"].get("title")

    # short-title derivation: strips filler, shortens, keeps it readable
    assert _short_title("Can you create a HTML tracker where I paste the session id and track it") \
        == "Create a HTML tracker where I paste the…", _short_title("Can you create a HTML tracker where I paste the session id and track it")
    assert _short_title("I want you to implement the create_contact tool") \
        == "Implement the create_contact tool", _short_title("I want you to implement the create_contact tool")

    # background-agent detection: agent files under <session-id>/ keep it "live"
    import tempfile as _tf
    sdir = _tf.mkdtemp()
    spath = os.path.join(sdir, "sess.jsonl")
    with open(spath, "w") as f:
        f.write(json.dumps({"type": "user", "cwd": "/x",
                            "message": {"role": "user", "content": "go"}}) + "\n")
    adir = os.path.join(sdir, "sess", "subagents", "workflows", "wf_abc123")
    os.makedirs(adir)
    with open(os.path.join(adir, "agent-deadbeef00.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "timestamp": "2026-06-22T10:00:00Z",
                            "message": {"role": "user", "content": "Audit the auth module"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Scanning auth.py for issues"},
            {"type": "tool_use", "name": "Read", "input": {}}]}}) + "\n")
    ags, newest = parse_agents(spath)
    assert len(ags) == 1 and ags[0]["task"] == "Audit the auth module", ags
    assert ags[0]["last"] == "Scanning auth.py for issues" and ags[0]["tools"] == 1, ags
    assert ags[0]["wf"] == "wf_abc123", ags
    assert _active_mtime(spath) >= os.path.getmtime(spath)
    ds = parse_session(spath)
    assert len(ds["agents_bg"]) == 1 and "background agent" in ds["overview"]["now"], ds["overview"]["now"]

    # live window: activity within 5 min counts as live; older does not
    af = os.path.join(adir, "agent-deadbeef00.jsonl")
    os.utime(af, (time.time() - 200, time.time() - 200))
    assert parse_agents(spath)[0][0]["running"] is True, "200s ago should still be live"
    os.utime(af, (time.time() - 400, time.time() - 400))
    assert parse_agents(spath)[0][0]["running"] is False, "400s ago should be stale"
    assert parse_agents(spath)[0][0]["aid"] == "deadbeef00", "agent detail id"

    # background shells: launch + result naming id/output file; live .output -> running
    outp = os.path.join(sdir, "srv.output")
    with open(outp, "w") as f:
        f.write("booting\nlistening on :8765\n")
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:01:00Z", "message": {"content": [
            {"type": "tool_use", "id": "bgL", "name": "Bash",
             "input": {"command": "python srv.py", "description": "Serve fixtures", "run_in_background": True}}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "bgL",
             "content": "Command running in background with ID: abcd1234. Output is being written to: %s. You will be notified." % outp}]}}) + "\n")
    shls = parse_shells(spath)
    assert len(shls) == 1 and shls[0]["id"] == "abcd1234" and shls[0]["desc"] == "Serve fixtures", shls
    assert shls[0]["last"] == "listening on :8765" and shls[0]["running"] is True, shls
    so = shell_output(spath, "abcd1234")
    assert so["cmd"] == "python srv.py" and "listening on :8765" in so["out"] and so["running"] is True, so
    # running until a <task-notification> for that id arrives — NOT output-file mtime
    os.utime(outp, (time.time() - 400, time.time() - 400))
    assert parse_shells(spath)[0]["running"] is True, "stale output file alone must NOT mark it done"
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user",
                "content": "<task-notification>\n<task-id>abcd1234</task-id>\n</task-notification>"}}) + "\n")
    assert parse_shells(spath)[0]["running"] is False, "task-notification -> done"

    # output fallback: command redirects to its own LOG, harness .output stays empty
    logf = os.path.join(sdir, "heal.log")
    with open(logf, "w") as f:
        f.write("driver started\nPASS 12/12\n")
    empty_out = os.path.join(sdir, "job2.output")
    open(empty_out, "w").close()  # harness file empty — output went to LOG
    assert _redirect_log('LOG=%s\npython x.py > "$LOG" 2>&1' % logf) == logf
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:02:00Z", "message": {"content": [
            {"type": "tool_use", "id": "bgL2", "name": "Bash",
             "input": {"command": 'LOG=%s\npython x.py > "$LOG" 2>&1' % logf, "run_in_background": True}}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "bgL2",
             "content": "Command running in background with ID: ef567890. Output is being written to: %s." % empty_out}]}}) + "\n")
    so2 = shell_output(spath, "ef567890")
    assert "PASS 12/12" in so2["out"], so2  # fell back to the LOG file

    # search: matches real content, prefers user prompts, and ignores boilerplate
    w = _window("the quick brown fox jumps over", "brown", pad=5)
    assert "brown" in w and w.startswith("…") and w.endswith("…"), w
    data = "\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": "fix the auth bug please"}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": "<system-reminder>skills: bitbucket-automation, auth bug helper</system-reminder>"}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the auth bug is in login"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "grep auth bug"}}]}}),
    ])
    cnt, snip, inq = _match_content(data, "auth bug")
    assert cnt >= 2 and inq is True and "auth bug" in snip.lower(), (cnt, snip, inq)
    # a term that lives ONLY in the injected skill list must NOT match
    assert _match_content(data, "bitbucket-automation")[0] == 0, "boilerplate leaked into search"

    # auggie (Augment CLI) sessions from ~/.augment/sessions + todos from task-storage
    global AUGMENT_DIR, AUGGIE_SESSIONS
    AUGMENT_DIR = tempfile.mkdtemp()
    AUGGIE_SESSIONS = os.path.join(AUGMENT_DIR, "sessions")
    os.makedirs(AUGGIE_SESSIONS)
    atd = os.path.join(AUGMENT_DIR, "task-storage", "tasks")
    os.makedirs(atd)
    _AUGGIE_LIST_CACHE.clear()
    with open(os.path.join(AUGMENT_DIR, "settings.json"), "w") as fh:
        json.dump({"indexingAllowDirs": ["/x/myrepo"]}, fh)

    def _wtask(u, **kw):
        with open(os.path.join(atd, u), "w") as fh:
            json.dump({"uuid": u, **kw}, fh)
    _wtask("root1", name="Current Task List", description="Root task for conversation Z", subTasks=["s1", "s2"])
    _wtask("s1", name="step one", state="COMPLETE", subTasks=[])
    _wtask("s2", name="step two", state="IN_PROGRESS", subTasks=[])
    with open(os.path.join(AUGGIE_SESSIONS, "sess1.json"), "w") as fh:
        json.dump({"sessionId": "sess1", "modified": "2026-06-27T05:48:03Z",
                   "customTitle": "List Home Dir", "rootTaskUuid": "root1",
                   "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                                    "exchange": {"request_message": "list the dir",
                                                 "response_text": "I'll list it."}}]}, fh)
    al = list_auggie()
    assert len(al) == 1 and al[0]["id"] == "auggie:sess1", al
    assert al[0]["source"] == "auggie" and al[0]["project"] == "myrepo", al
    assert al[0]["title"] == "List Home Dir", al                       # customTitle wins
    pa = parse_auggie("sess1")
    assert pa and pa["counts"]["done"] == 1 and pa["counts"]["todos"] == 2, pa   # todos via rootTaskUuid
    assert [r["text"] for r in pa["requests"]] == ["list the dir"], pa["requests"]
    assert pa["narrative"] and "list it" in pa["narrative"][0]["text"].lower()
    assert parse_auggie("missing") is None

    # task store (TaskCreate/TaskUpdate) — replaced in-transcript TodoWrite
    global TASKS_DIR
    TASKS_DIR = tempfile.mkdtemp()
    tdir = os.path.join(TASKS_DIR, "sess-x")
    os.makedirs(tdir)
    open(os.path.join(tdir, ".lock"), "w").close()  # must be skipped
    json.dump({"id": "2", "subject": "Second", "status": "in_progress", "description": "do it"},
              open(os.path.join(tdir, "2.json"), "w"))
    json.dump({"id": "1", "subject": "First", "status": "completed"},
              open(os.path.join(tdir, "1.json"), "w"))
    tl = load_tasks("sess-x")
    assert [t["content"] for t in tl] == ["First", "Second"], tl  # numeric-id order
    assert tl[0]["status"] == "completed" and tl[1]["status"] == "in_progress", tl
    assert tl[1]["desc"] == "do it", tl
    assert load_tasks("missing") == []

    # flags persistence round-trip
    global FLAGS_FILE
    FLAGS_FILE = tempfile.mktemp(suffix=".json")
    assert load_flags() == []  # missing file -> empty
    save_flags([{"id": 1, "session": "s", "note": "gap here", "resolved": False}])
    fl = load_flags()
    assert fl[0]["note"] == "gap here" and fl[0]["resolved"] is False
    fl[0]["resolved"] = True
    save_flags(fl)
    assert load_flags()[0]["resolved"] is True
    os.unlink(FLAGS_FILE)

    # user title override round-trip
    global TITLES_FILE
    TITLES_FILE = tempfile.mktemp(suffix=".json")
    assert load_titles() == {}
    _save_json(TITLES_FILE, {"sess-1": "My Custom Name"})
    assert load_titles()["sess-1"] == "My Custom Name"
    os.unlink(TITLES_FILE)
    print("selfcheck ok")


class Server(ThreadingHTTPServer):
    daemon_threads = True  # don't let in-flight polls block Ctrl-C

    def handle_error(self, request, client_address):
        # a client hanging up mid-response is expected with 2s polling — stay quiet
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        print("claude-tracker", __version__)
        return
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__.strip())
        print("\nUsage: python3 tracker.py [--selfcheck | --version | --help]")
        print("Env:   PORT  (default 8787)")
        return
    if "--selfcheck" in sys.argv:
        _selfcheck()
        return
    port = int(os.environ.get("PORT", 8787))
    url = f"http://localhost:{port}"
    print(f"Claude Code tracker → {url}  (Ctrl-C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    Server(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
