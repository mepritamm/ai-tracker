import difflib, glob, json, os, re, time
from ..config import EDIT_TOOLS, LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import _dur, _names, _short_title, _first_line, _window, _iso_epoch, _git_branch, cmd_kind, TEST_RE, COMMIT_MSG_RE, collect_prs, prs_sorted, pr_worked, PR_CREATE_RE
from ..overview import build_overview
from ..store import load_titles, load_tasks
from .base import Provider


def find_session(sid):
    sid = sid.strip().replace(".jsonl", "")
    hits = glob.glob(os.path.join(config.PROJECTS, "*", sid + ".jsonl"))
    return hits[0] if hits else None


_META_CACHE = {}


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
    fs = glob.glob(os.path.join(config.PROJECTS, "*", "*.jsonl"))
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


def _searchable_texts(o):
    """Yield (text, is_user_query) for the *real* content of a session line —
    user prompts, assistant replies, and tool inputs. Excludes system reminders,
    command wrappers, attachments, and tool output — the injected boilerplate
    (skill/tool lists) that otherwise made common words match nearly every session."""
    m = o.get("message")
    if not isinstance(m, dict):
        return
    role = m.get("role")
    is_assistant = o.get("type") == "assistant"   # reliable regardless of message.role
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
                # only the assistant's own replies — a user-role list carries injected
                # skill/tool/attachment text, not conversation (would pollute search).
                if is_assistant and not txt.lstrip().startswith("<"):
                    yield (txt, False)
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
    fs = glob.glob(os.path.join(config.PROJECTS, "*", "*.jsonl"))
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
    agent_files = {}      # path -> file entry : edits made by background agents (worktrees etc.)
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
                                nm = b.get("name")
                                if nm == "Write" or nm in EDIT_TOOLS:   # agents write files too
                                    finp = b.get("input") or {}
                                    fp = finp.get("file_path") or finp.get("notebook_path")
                                    if fp:
                                        fe = agent_files.setdefault(
                                            fp, {"path": fp, "ops": 0, "created": False, "agent": True})
                                        fe["ops"] += 1
                                        if last_ts:
                                            fe["last"] = last_ts
                                        if nm == "Write":
                                            fe["created"] = True
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
    return out, newest, agent_files


def _unified(old, new, cap=20000):
    """Unified diff between two strings, each capped to keep payloads sane."""
    old, new = (old or "")[:cap], (new or "")[:cap]
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(), "before", "after", lineterm=""))


def file_diffs(path, target):
    """Reconstruct every Write/Edit to `target`, in order — from the main transcript
    AND the session's background-agent transcripts (so agent edits are diffable too).
    The tool inputs ARE the diff: Write=full content, Edit=old/new strings."""
    ops = []
    for src in [path] + _agent_files(path):
        try:
            fh = open(src, encoding="utf-8")
        except OSError:
            continue
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
    ops.sort(key=lambda o: o.get("ts") or "")       # interleave main + agent edits chronologically
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


ASSIGN_RE = re.compile(r'(\w+)=("?)(/[^"\s]+)\2')


REDIR_RE = re.compile(r'(?:&>|\d*>>?|>)\s*("?)(\$\{?\w+\}?|/[^"\s]+)\1')


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
                    s = c.strip()                              # keep paragraphs (.cmdcode is pre-wrap)
                    if s and not s.startswith("<"):
                        task = s[:8000]                        # full prompt, not the 160-char card blurb
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
    prs = {}              # url -> {url, repo, num, created, t} : PRs touched this session
    pr_create_ids = set() # tool_use_ids of `gh pr create` Bash calls (their result URL = created)
    asks = {}             # tool_use_id -> AskUserQuestion decision {t, open, answer, questions}
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
                    collect_prs(prs, s, ts)                        # a PR pasted into a prompt counts
                continue
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                # narration is the ASSISTANT's own words only — a user-role list carries
                # injected skill/command/tool text ("Base directory for this skill: …"),
                # which is not conversation and must not leak into the Narration panel.
                if bt == "text" and b.get("text", "").strip() and o.get("type") == "assistant":
                    txt = b["text"].strip()
                    if not txt.startswith("<"):  # skip command/system echoes
                        text_last = txt
                        narrative.append({"t": ts, "text": txt[:NARRATION_CAP]})  # modal shows full; list clamps preview
                        collect_prs(prs, txt, ts, narr=True)      # PR links Claude prints in its narration
                elif bt == "tool_result":
                    rid = b.get("tool_use_id")
                    if b.get("is_error"):
                        errors_by_id[rid] = True
                    cc = b.get("content")                          # command output: gh prints the PR URL here
                    rtext = cc if isinstance(cc, str) else (json.dumps(cc) if cc else "")
                    if rid in asks:                                # the user's answer to an AskUserQuestion
                        asks[rid]["answer"] = re.sub(r"^Your questions have been answered:\s*", "", rtext).strip()[:2000]
                        asks[rid]["open"] = False
                    collect_prs(prs, rtext, ts, rid in pr_create_ids)
                elif bt == "tool_use":
                    name = b.get("name")
                    inp = b.get("input") or {}
                    bid = b.get("id")
                    if name and "create_pull_request" in name:   # GitHub MCP: result URL is a created PR
                        pr_create_ids.add(bid)
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
                        if PR_CREATE_RE.search(c):       # its result URL is a created PR
                            pr_create_ids.add(bid)
                        collect_prs(prs, c, ts)                    # a command's PR ref alone isn't "worked on"
                        if k == "commit":
                            m = COMMIT_MSG_RE.search(c)
                            commits.append({"t": ts, "msg": (m.group(2) if m else c)[:120]})
                    elif name in ("Grep", "Glob"):
                        n_search += 1
                    elif name == "Task":
                        agents.append({"t": ts, "type": inp.get("subagent_type") or "agent",
                                       "desc": (inp.get("description") or "")[:80]})
                    elif name == "AskUserQuestion":                # a decision the session asked the user for
                        qs = [{"q": (q.get("question") or "")[:500], "header": (q.get("header") or "")[:40],
                               "options": [(o.get("label") or "")[:120] for o in (q.get("options") or [])
                                           if isinstance(o, dict)]}
                              for q in (inp.get("questions") or []) if isinstance(q, dict)]
                        asks[bid] = {"t": ts, "open": True, "answer": "", "questions": qs}
    # annotate commands with pass/fail from the error map
    for c in cmds:
        c["ok"] = not errors_by_id.get(c["id"], False)
    tests = [c for c in cmds if c["kind"] == "test"]
    sid = meta.get("sessionId") or os.path.basename(path)[:-6]
    tasks = load_tasks(sid)  # newer sessions use the task store, not in-transcript TodoWrite
    if tasks:
        todos = tasks
    done_todos = [t for t in todos if t.get("status") == "completed"]
    agents_bg, newest_agent, agent_files = parse_agents(path)
    # merge background-agent file edits into the shared files shape so they show in
    # the Files panel (and the counts) — e.g. an agent editing inside a worktree.
    for fp, ae in agent_files.items():
        existed = fp in files
        e = files.setdefault(fp, {"path": fp, "ops": 0, "created": ae["created"]})
        e["ops"] += ae["ops"]
        if ae.get("last") and (not e.get("last") or ae["last"] > e["last"]):
            e["last"] = ae["last"]
        if ae["created"]:
            e["created"] = True
        if not existed:
            e["agent"] = True                     # only the main session never touched it
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
        # open decisions first, then most-recent — so a pending question is at the top
        "decisions": sorted(asks.values(), key=lambda a: (a["open"], a["t"] or ""), reverse=True),
        "prs": [p for p in prs_sorted(prs) if pr_worked(p, meta.get("cwd"))],   # created or worked-on, not prompt-only references
        "narrative": narrative[::-1],   # full, newest-first; /api/session pages it, /api/narration serves the tail
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


class ClaudeProvider(Provider):
    prefix = ""

    def available(self):
        return os.path.isdir(config.PROJECTS)

    def list(self):
        return list_sessions()

    def parse(self, sid):
        path = find_session(sid)
        return parse_session(path) if path else None

    def search(self, q):
        return search_sessions(q)
