import datetime as _dt
import json, os, sqlite3, time
import urllib.parse
from ..config import LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import (_short_title, _git_branch, cmd_kind, COMMIT_MSG_RE,
                    collect_prs, note_pr_states, prs_sorted, pr_worked, push_when,
                    PR_CREATE_RE, unified, context_window)
from ..overview import build_overview
from ..store import load_titles, load_notes
from .base import Provider
# The search scorer is one capability, so it gets one implementation — importing Auggie's rather
# than copying it, which is how two subtly different rankings for the same query start. ponytail:
# it really belongs in util.py beside _window; move it there when something else needs it.
from .auggie import _score_segments


# --- the storage difference -------------------------------------------------------------
# Claude writes one JSONL per session, Auggie one JSON per session. opencode writes NOTHING
# per session: every session, message, part and todo of every project lives in ONE SQLite
# database (~/.local/share/opencode/opencode.db, WAL mode, 43MB here). So this provider has
# no glob and no file cache keyed on mtime — it has queries, and the two rules that fall out
# of sharing a live agent's database:
#   1. READ-ONLY, always: `file:<path>?mode=ro`. Verified — any write on this connection form
#      raises OperationalError("attempt to write a readonly database"), and a crafted directory
#      name attempting a mode=rw override is rejected too. The tracker must never be able to
#      corrupt the store of an agent that is mid-run. This is NOT the same as "leaves no trace
#      on disk": opening a WAL database, even read-only, makes SQLite create (or refresh)
#      opencode.db-shm / opencode.db-wal next to it, and they are left behind on close. No SQL
#      write is possible and the session data itself is never modified — but don't read this as
#      the provider being inert on the filesystem.
#   2. NEVER touch the `account` / `credential` tables. They hold live access_token /
#      refresh_token / secret values. Nothing in this file names them; nothing ever should.
# Every read is funnelled through _open()/_rows() so a locked, absent or corrupt db yields an
# empty result instead of an exception — one provider's storage must never sink
# registry.all_sessions(), which is what the whole sidebar hangs off.
# The connection is opened and closed PER CALL (the list endpoint polls every 2s); holding a
# global handle would pin a read txn against a database another process is actively writing.


def _open():
    """A read-only connection to the opencode db, or None if it isn't usable.
    `config.OPENCODE_DB` is read late (never from-imported) so tests and callers that
    repoint it see one source of truth."""
    db = config.OPENCODE_DB
    if not db or not os.path.isfile(db):
        return None
    try:
        # THE TRAP: sqlite3's URI mode percent-DECODES the path before opening it. Interpolating
        # the raw path means a db sitting at e.g. /tmp/pct/a%41b.db silently opens /tmp/pct/aAb.db
        # instead — os.path.isfile() above checked the literal name, SQLite would read a
        # different file. Escape %, #, ? (and the other URI-special bytes) before interpolating.
        return sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(db), uri=True, timeout=1.0)
    except (sqlite3.Error, OSError, ValueError):
        return None


def _close(conn):
    try:
        conn.close()
    except sqlite3.Error:
        pass


def _rows(conn, sql, args=()):
    """Guarded execute. A schema drift, a lock timeout or a corrupt page returns [] —
    the caller then renders an empty session, not a 500."""
    if conn is None:
        return []
    try:
        return conn.execute(sql, args).fetchall()
    except (sqlite3.Error, ValueError):
        return []


def _json(s):
    """part.data / message.data / session.model are all JSON *strings* in the db."""
    if isinstance(s, dict):
        return s
    try:
        o = json.loads(s or "")
    except (ValueError, TypeError):
        return {}
    return o if isinstance(o, dict) else {}


def _d(v):
    """v if it's a dict, else {} — the guard the `x.get("state") or {}` idiom below is NOT:
    `or {}` only catches a falsy value (None, "", 0, []), so a non-empty string or a list sails
    through it, and the very next `.get(...)` throws AttributeError. One malformed JSON value
    anywhere in one session's transcript (a stray string where `part.state`/`message.time`
    should be a dict) then raises out of list_opencode(), and registry.all_sessions() returns
    ZERO opencode sessions — every session vanishes, not just the malformed one. Real data on
    this machine is currently 100% well-formed (part.state dict 667/667, message.time dict
    2000/2000): this is schema-drift defence, not a fix for an observed live bug."""
    return v if isinstance(v, dict) else {}


def _num(v):
    """A tokens_* column, coerced to a number. SQLite is dynamically typed PER VALUE, not per
    column, so nothing stops one row from holding text in a column every other row holds an
    int — `(tok_in or 0) + …` would then raise TypeError and take the whole list down with it,
    same failure mode as the missing dict-guards above."""
    return v if isinstance(v, (int, float)) else 0


def _iso(ms):
    """opencode stores epoch MILLISECONDS; the shared shape's item `t` fields are ISO-8601
    strings (util._dur parses [:19] as "%Y-%m-%dT%H:%M:%S").

    THE TRAP: keep the trailing "Z". Claude's and Auggie's logs both hand the shared shape
    UTC stamps ("…T08:52:53.880Z") and the SPA feeds `t` straight to Date.parse — which reads
    a bare "…T08:52:53" as LOCAL time, so dropping the Z silently skews every "ago" label by
    the machine's UTC offset. Milliseconds are included for byte-parity with the siblings."""
    if not isinstance(ms, (int, float)) or ms <= 0:
        return ""
    try:
        return (_dt.datetime.fromtimestamp(ms / 1000.0, _dt.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (int(ms) % 1000))
    except (ValueError, OSError, OverflowError):
        return ""


def _epoch(ms):
    """…and `mtime` wants epoch SECONDS, not the ISO string."""
    return (ms / 1000.0) if isinstance(ms, (int, float)) and ms > 0 else 0.0


def _model(raw):
    """session.model is a JSON string {"id","providerID","variant"}, not a plain name."""
    m = _json(raw)
    return m.get("id") or (raw if isinstance(raw, str) and not raw.startswith("{") else "")


def _real_text(part, msg=None):
    """The text of a non-boilerplate text part, or "".

    THE TRAP: opencode emits type-"text" parts with `"synthetic": true` for system reminders
    and editor context (456 of 1321 on this machine). They are injected scaffolding, not
    something a human typed or the model said — let them through and the sidebar prompt and
    the whole narration panel fill with junk. Skip them everywhere, exactly once, here."""
    if part.get("type") != "text" or part.get("synthetic"):
        return ""
    t = part.get("text")
    return t.strip() if isinstance(t, str) and t.strip() else ""


_SESSION_COLS = ("id, parent_id, directory, title, agent, model, time_created, time_updated, "
                 "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write")


def _transcript(conn, sid):
    """Every part of one session, oldest-first, paired with ITS MESSAGE'S JSON.

    role lives on the message row, not the part — so a user prompt and an assistant
    narration line are indistinguishable without this join. Returns [(part, msg)] dicts."""
    out = []
    for pd, md in _rows(conn,
                        "SELECT p.data, m.data FROM part p JOIN message m ON m.id = p.message_id "
                        "WHERE p.session_id = ? ORDER BY p.time_created ASC, p.id ASC", (sid,)):
        out.append((_json(pd), _json(md)))
    return out


def _part_ts(conn, sid):
    """(first, last) part timestamps as ISO strings — the session's active span."""
    r = _rows(conn, "SELECT MIN(time_created), MAX(time_created) FROM part WHERE session_id = ?",
              (sid,))
    if not r:
        return "", ""
    return _iso(r[0][0]), _iso(r[0][1])


_LIST_CACHE = {}   # (db_path, sid) -> (cache_key, entry) — the per-poll cache, keyed the way the
                   # file providers key theirs on mtime.
                   #
                   # THE TRAP this replaced: the cache used to be keyed on session.time_updated
                   # alone, on the claim that it's bumped on every write to a session. Measured
                   # false on the real db: 67/77 sessions have a `part` newer than their
                   # session.time_updated (lag up to 16.8s), and 73/77 have a `message` newer
                   # still (lag up to ~3.9h). Concretely: a `question` part written after the
                   # session row's last bump left the sidebar showing waiting=False forever while
                   # opencode was actually blocked on the human — the cache never saw the write
                   # that would have flipped it, because time_updated never moved.
                   # So the key is max(time_updated, latest part, latest message) — real
                   # transcript activity, not the session row's own (unreliable) bookkeeping.
                   #
                   # It's also keyed on the resolved db path: config.OPENCODE_DB is explicitly
                   # repointable (TRACKER_OPENCODE_DB; the tests repoint it per test), and two
                   # different dbs can hold a session with the same id and the same activity
                   # timestamp — without the path in the key, the second db's list() would
                   # silently return the first db's cached entry.


def _list_state(conn, sid):
    """(prompt, waiting, ended) for the sidebar — the opencode analog of _auggie_state.

    `waiting`: ANY `question` tool call is still unresolved (opencode's ask-user; a resolved
    one lands on status completed/error) → blocked on the human, not idle. Tracked per callID,
    latest status wins per call — the same semantics parse_opencode's `asks` dict and its
    `any(a["open"] ...)` use (Claude's and Auggie's list states agree: any open ask = waiting).
    THE BUG this replaced: the old loop kept only the LAST question part seen and overwrote
    `waiting` on every iteration, so q1-unresolved-then-q2-answered read as waiting=False here
    while parse_opencode's detail view (any-of semantics) read the same session as waiting=True.
    `ended`: the session's last message is an assistant turn that reached time.completed."""
    prompt = ""
    open_asks = {}   # callID -> still open?
    for part, msg in _transcript(conn, sid):
        if part.get("type") == "tool" and part.get("tool") == "question":
            open_asks[part.get("callID")] = _d(part.get("state")).get("status") not in (
                "completed", "error")
            continue
        if prompt or msg.get("role") != "user":
            continue
        t = _real_text(part)
        if t:
            prompt = " ".join(t.split())[:200]
    waiting = any(open_asks.values())
    last = _rows(conn, "SELECT data FROM message WHERE session_id = ? "
                       "ORDER BY time_created DESC, id DESC LIMIT 1", (sid,))
    m = _json(last[0][0]) if last else {}
    ended = (m.get("role") == "assistant") and bool(_d(m.get("time")).get("completed"))
    return prompt, waiting, (not waiting) and ended


def _activity(conn):
    """sid -> latest real transcript timestamp, from `part` and `message` — see _LIST_CACHE for
    why this, not session.time_updated, is what a poll must key its cache on. One extra
    aggregate query per table, both indexed on session_id, so this stays cheap: see the
    D1 timing note in opencode.py's fix history for measured cost."""
    latest = {}
    for sid, ts in _rows(conn, "SELECT session_id, MAX(time_created) FROM part "
                               "GROUP BY session_id"):
        if ts and ts > latest.get(sid, 0):
            latest[sid] = ts
    for sid, ts in _rows(conn, "SELECT session_id, MAX(time_created) FROM message "
                               "GROUP BY session_id"):
        if ts and ts > latest.get(sid, 0):
            latest[sid] = ts
    return latest


def list_opencode():
    """One query for the session rows plus one activity query each over `part` and `message`;
    the transcript scan (prompt/waiting/ended) runs only for sessions whose real activity
    (not just the session row) moved since the last poll."""
    conn = _open()
    if conn is None:
        return []
    try:
        db = config.OPENCODE_DB
        titles = load_titles()
        activity = _activity(conn)
        out = []
        for (sid, parent, cwd, title, _agent, _model_raw, _tc, tu, *_tok) in _rows(
                conn, "SELECT " + _SESSION_COLS + " FROM session ORDER BY time_updated DESC"):
            key = max(tu or 0, activity.get(sid, 0))
            cache_id = (db, sid)
            hit = _LIST_CACHE.get(cache_id)
            if hit and hit[0] == key:
                prompt, waiting, ended = hit[1]
            else:
                prompt, waiting, ended = _list_state(conn, sid)
                _LIST_CACHE[cache_id] = (key, (prompt, waiting, ended))
            gid = "opencode:" + sid
            cwd = cwd or ""
            out.append({
                "id": gid, "project": os.path.basename(cwd) if cwd else "opencode", "cwd": cwd,
                "title": titles.get(gid) or title or _short_title(prompt) or "opencode session",
                "prompt": prompt, "source": "opencode", "mtime": _epoch(tu),
                # a session with a parent IS a sub-agent run (opencode's `task` tool spawns one),
                # so it nests under its parent in the sidebar exactly like Claude's sdk-cli sessions.
                "agent": bool(parent), "group": "", "groupLabel": "",
                "parentId": ("opencode:" + parent) if parent else "", "bg": 0, "first": 0,
                "waiting": waiting, "ended": ended,
            })
        return out
    finally:
        _close(conn)


def _touch(files, path, ts, created=False):
    """One edit on the shared files entry ({path, ops, created, last}) — the same shape
    Claude's and Auggie's parsers build, so one renderer serves all three."""
    e = files.setdefault(path, {"path": path, "ops": 0, "created": created})
    e["ops"] += 1
    e["last"] = ts
    if created:
        e["created"] = True
    return e


def _session_row(conn, sid):
    r = _rows(conn, "SELECT " + _SESSION_COLS + " FROM session WHERE id = ?", (sid,))
    return r[0] if r else None


def _todos(conn, sid):
    """opencode's todo table already speaks the tracker's own vocabulary
    (completed/in_progress/pending) — no state mapping needed, unlike Auggie's."""
    return [{"content": c or "", "status": s or "pending", "activeForm": c or ""}
            for (c, s) in _rows(conn, "SELECT content, status FROM todo WHERE session_id = ? "
                                      "ORDER BY position ASC", (sid,))]


def _child_sessions(conn, sid, parent_cwd):
    """The sub-agent sessions this one spawned (`task` tool → a child row whose parent_id is
    us). Shape matches Claude's agent_sessions cards; `id` is namespaced because the card's
    click calls pick(a.id) straight into the main view. opencode runs each dispatch as its own
    session rather than re-running one, so runs is always 1 — nothing to collapse."""
    now = time.time()
    out = []
    for (cid, _p, cdir, ctitle, _a, _m, _tc, tu, *_tok) in _rows(
            conn, "SELECT " + _SESSION_COLS + " FROM session WHERE parent_id = ? "
                  "ORDER BY time_updated DESC", (sid,)):
        mt = _epoch(tu)
        out.append({"id": "opencode:" + cid, "title": ctitle or cid,
                    # opencode sub-agents share the parent's cwd unless dispatched elsewhere;
                    # only a genuinely different directory is worth a chip.
                    "wt": os.path.basename(cdir) if cdir and cdir != parent_cwd else "",
                    "running": (now - mt) < LIVE_WINDOW, "mtime": mt, "runs": 1})
    return out


def parse_opencode(session_id):
    conn = _open()
    if conn is None:
        return None
    try:
        row = _session_row(conn, session_id)
        if row is None:
            return None
        (sid, parent, cwd, s_title, _agent, model_raw, t_created, t_updated,
         tok_in, tok_out, tok_cr, tok_cw) = row
        cwd = cwd or ""
        requests, narrative, files, cmds, reads, commits = [], [], {}, [], {}, []
        agents = []       # `task` dispatches (~ Claude's Task / Auggie's sub-agent-*)
        asks = {}         # callID -> `question` decision {t, open, answer, questions}
        prs, pr_states = {}, {}
        n_search = 0
        ctx_current = None   # LATEST assistant turn's occupancy
        for part, msg in _transcript(conn, sid):
            ts = _iso(part.get("time_created") or _d(msg.get("time")).get("created"))
            role = msg.get("role")
            if role == "assistant":
                tk = _d(msg.get("tokens"))
                cache = _d(tk.get("cache"))
                cur = (tk.get("input") or 0) + (cache.get("read") or 0) + (cache.get("write") or 0)
                # this turn's carried context (input + cache), latest wins — but only from a turn
                # that actually reported occupancy. opencode's compaction/aborted messages carry an
                # all-zero tokens block, and letting one of those land last reads as "0 context".
                if cur > 0:
                    ctx_current = cur
            text = _real_text(part)
            if text:
                if role == "user":
                    requests.append({"t": ts, "text": " ".join(text.split())[:300]})
                    collect_prs(prs, text, ts)          # a prompt's PR ref alone isn't "worked on"
                else:
                    narrative.append({"t": ts, "text": text[:NARRATION_CAP]})
                    collect_prs(prs, text, ts, narr=True)
                    note_pr_states(pr_states, text)
                continue
            if part.get("type") != "tool":
                continue        # step-start/step-finish/reasoning/compaction/patch: no shared field
            name = part.get("tool")
            st = _d(part.get("state"))
            inp = st.get("input") if isinstance(st.get("input"), dict) else {}
            ok = st.get("status") != "error"
            if name == "bash" and inp.get("command"):
                c = inp["command"]
                k = cmd_kind(c)
                cmds.append({"id": part.get("callID"), "t": ts, "cmd": c[:200], "kind": k, "ok": ok})
                collect_prs(prs, c, ts)
                note_pr_states(pr_states, c)
                # unlike Auggie, opencode keeps the command's CAPTURED OUTPUT right here — so a
                # `gh pr create`'s result URL is attributable directly, no exchange-index guessing.
                out = st.get("output")
                if isinstance(out, str) and out:
                    collect_prs(prs, out[:20000], ts, created=bool(PR_CREATE_RE.search(c)))
                    note_pr_states(pr_states, out[:20000])
                if k == "commit":
                    mm = COMMIT_MSG_RE.search(c)
                    commits.append({"t": ts, "msg": (mm.group(2) if mm else c)[:120]})
            elif name == "write" and inp.get("filePath"):
                _touch(files, inp["filePath"], ts, created=True)
            elif name == "edit" and inp.get("filePath"):
                _touch(files, inp["filePath"], ts)
            elif name == "read" and inp.get("filePath"):
                reads[inp["filePath"]] = ts
            elif name in ("grep", "glob"):
                n_search += 1                      # same two-tool definition Claude's counter uses
            elif name == "task":                   # opencode's sub-agent dispatch
                agents.append({"t": ts, "type": inp.get("subagent_type") or "agent",
                               "desc": (inp.get("description") or inp.get("prompt") or "")[:80]})
            elif name == "question":               # opencode's ask-user (~ AskUserQuestion)
                qs = []
                for q in inp.get("questions") or []:
                    if not isinstance(q, dict):
                        continue
                    qs.append({"q": (q.get("question") or "")[:500],
                               "header": (q.get("header") or "")[:40],
                               "options": [(o.get("label") or "")[:120]
                                           for o in (q.get("options") or []) if isinstance(o, dict)]})
                # the answer comes back inside the tool's own result: state.metadata.answers is
                # [[label], …] once the human picks; an unresolved call has neither.
                answers = _d(st.get("metadata")).get("answers") or []
                flat = [a for grp in answers if isinstance(grp, list) for a in grp if isinstance(a, str)]
                asks[part.get("callID")] = {
                    "t": ts, "open": st.get("status") not in ("completed", "error"),
                    "answer": "; ".join(flat)[:2000], "questions": qs}
        branch = _git_branch(cwd)
        tests = [c for c in cmds if c["kind"] == "test"]
        todos = _todos(conn, sid)
        done = sum(1 for x in todos if x["status"] == "completed")
        gid = "opencode:" + sid
        title = (load_titles().get(gid) or s_title
                 or (_short_title(requests[0]["text"]) if requests else "opencode session"))
        latest = narrative[-1]["text"] if narrative else ""
        t_first, t_last = _part_ts(conn, sid)
        t_first = t_first or _iso(t_created)
        t_last = t_last or _iso(t_updated)
        mtime = _epoch(t_updated) or _epoch(t_created)
        result = {
            "meta": {"cwd": cwd, "title": title, "source": "opencode", "entrypoint": "opencode",
                     "model": _model(model_raw), "gitBranch": branch},
            "todos": todos,
            "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
            "reads": [{"path": p, "t": t} for p, t in
                      sorted(reads.items(), key=lambda kv: kv[1] or "", reverse=True)],
            "commands": cmds[-60:][::-1],
            "commits": commits[::-1],
            "tests": tests[::-1],
            "requests": requests,
            "agents": agents[::-1],
            # opencode has no background/detached agent mode — a `task` dispatch is a CHILD SESSION
            # (see agent_sessions below), which the panel already renders. Exists-but-records-nothing.
            "agents_bg": [],
            "agent_sessions": _child_sessions(conn, sid, cwd),
            # opencode has no background-shell concept at all (no run-in-background flag, no harness
            # .output file): every bash call is synchronous and its output is already on the part.
            "shells": [],
            # open decisions first, then most-recent — parity with Claude's AskUserQuestion panel
            "decisions": sorted(asks.values(), key=lambda a: (a["open"], a["t"] or ""), reverse=True),
            "waiting": any(a["open"] for a in asks.values()),
            "prs": [p for p in prs_sorted(prs, pr_states) if pr_worked(p, cwd)],
            "narrative": narrative[::-1],   # full, newest-first; /api/session pages it
            "message": latest[:2000],
            # session-cumulative, straight off the session row's own aggregates (opencode maintains
            # them, so there's nothing to re-sum per message).
            "tokens": {"in": _num(tok_in) + _num(tok_cr) + _num(tok_cw), "out": _num(tok_out)},
            # opencode records NO context-window size anywhere — not on the session, not on a
            # message's tokens block. So limit/pct stay None rather than being invented from a
            # guessed denominator; callers already treat None as "unknown", not zero.
            "context": context_window(ctx_current, None),
            "counts": {"done": done, "todos": len(todos),
                       "created": sum(1 for x in files.values() if x.get("created")),
                       "edited": sum(1 for x in files.values() if not x.get("created")),
                       "read": len(reads), "commits": len(commits), "tests": len(tests),
                       "tests_failed": sum(1 for t in tests if not t["ok"]),
                       "errors": sum(1 for c in cmds if not c["ok"]),
                       "agents": len(agents), "searches": n_search},
            "mtime": mtime,
            "now": time.time(),
            "notes": load_notes().get(gid, []),
            # opencode fires no hook that drains /api/notes/next, so a pushed note queues and you
            # deliver it by hand. Pass True here the day a drain exists.
            "push_when": push_when(False, 0, 0),
        }
        result["overview"] = build_overview(result, todos, result["files"], cmds, commits,
                                            tests, agents, requests, narrative, [],
                                            time.time() - mtime, t_first, t_last)
        return result
    finally:
        _close(conn)


def search_opencode(q, limit=500):
    """One pass over the parts table, bucketed by session — the counterpart of
    search_sessions/search_auggie, returning the SAME result shape so search_all can rank
    Claude, Auggie and opencode hits together. Synthetic text is excluded here too, or every
    query would match the same injected system-reminder boilerplate in every session."""
    ql = q.lower().strip()
    if not ql:
        return []
    terms = ql.split()
    conn = _open()
    if conn is None:
        return []
    try:
        meta = {}
        for (sid, parent, cwd, title, _a, _m, _tc, tu, *_tok) in _rows(
                conn, "SELECT " + _SESSION_COLS + " FROM session ORDER BY time_updated DESC"):
            meta[sid] = (parent, cwd or "", title or "", _epoch(tu))
            if len(meta) >= limit:
                break
        segs = {}
        # THE TRAP this replaced: the old query joined part x message with NO WHERE and NO
        # LIMIT, then filtered `psid not in meta` in Python AFTER fetchall() had already pulled
        # every part's `data` blob out of the db — measured ~15.4MB per search request,
        # regardless of `limit`. `limit` only ever bounded the session-metadata dict above, so
        # search cost was linear in TOTAL db size, not in the `limit` the caller asked for.
        # Pushing `session_id IN (…)` into the query scopes the fetch to the same `limit`
        # sessions meta already picked, so the two bounds now move together.
        sids = list(meta)
        if sids:
            placeholders = ",".join("?" * len(sids))
            for psid, pd, md in _rows(
                    conn, "SELECT p.session_id, p.data, m.data FROM part p "
                          "JOIN message m ON m.id = p.message_id "
                          "WHERE p.session_id IN (%s) ORDER BY p.time_created ASC" % placeholders,
                    sids):
                t = _real_text(_json(pd))
                if t:
                    segs.setdefault(psid, []).append((t, _json(md).get("role") == "user"))
        titles = load_titles()
        out = []
        for sid, (parent, cwd, s_title, mt) in meta.items():
            gid = "opencode:" + sid
            these = segs.get(sid, [])
            title = (titles.get(gid) or s_title
                     or _short_title(these[0][0] if these else "") or "opencode session")
            title_match = all(t in title.lower() for t in terms)
            count, snippet, in_query = _score_segments(these, terms, ql)
            if not count and not title_match:
                continue
            out.append({"id": gid, "project": os.path.basename(cwd) if cwd else "opencode",
                        "title": title, "agent": bool(parent),
                        "matches": count, "snippet": snippet, "inQuery": in_query,
                        "titleMatch": title_match, "mtime": mt})
        return out
    finally:
        _close(conn)


def command_output(session_id, cmd_id):
    """Fetched on click: the full command for `cmd_id` and its captured output. opencode keeps
    both on the SAME tool part (state.input.command / state.output) — no result-node join like
    Auggie's, and an errored call carries state.error instead of output."""
    conn = _open()
    if conn is None:
        return None
    try:
        for part, _msg in _transcript(conn, session_id):
            if part.get("type") != "tool" or part.get("callID") != cmd_id:
                continue
            st = _d(part.get("state"))
            inp = st.get("input") if isinstance(st.get("input"), dict) else {}
            out = st.get("output") or st.get("error") or ""
            return {"cmd": (inp.get("command") or "")[:4000],
                    "out": (out if isinstance(out, str) else json.dumps(out))[:20000],
                    "ok": st.get("status") != "error"}
        return {"cmd": "", "out": "", "ok": True}
    finally:
        _close(conn)


def file_diffs(session_id, target):
    """Every edit to `target`, oldest-first. The tool inputs ARE the diff, as for the other
    providers: `write` = the full content written (a creation), `edit` = the one old/new pair
    it swapped. opencode logs absolute filePaths, so no cwd anchoring is needed here."""
    conn = _open()
    if conn is None:
        return None
    try:
        ops = []
        for part, _msg in _transcript(conn, session_id):
            if part.get("type") != "tool":
                continue
            st = _d(part.get("state"))
            inp = st.get("input") if isinstance(st.get("input"), dict) else {}
            if inp.get("filePath") != target:
                continue
            ts = _iso(part.get("time_created"))
            if part.get("tool") == "write":
                ops.append({"ts": ts, "kind": "created",
                            "diff": unified("", inp.get("content") or "")})
            elif part.get("tool") == "edit":
                ops.append({"ts": ts, "kind": "edited",
                            "diff": unified(inp.get("oldString") or "", inp.get("newString") or "")})
        return ops
    finally:
        _close(conn)


def agent_detail(session_id, aid):
    """Fetched on click: a sub-agent's task, narration, tool count and liveness. opencode's
    `task` dispatch IS a child session row, so this serves that child's transcript — the same
    {task, narration, tools, running} shape Claude's background-agent files produce. Only a
    genuine child of `session_id` is served, so a namespaced id can't be used to read a
    stranger's session through this route."""
    conn = _open()
    if conn is None:
        return None
    child = aid[len("opencode:"):] if aid.startswith("opencode:") else aid
    try:
        row = _session_row(conn, child)
        if row is None or row[1] != session_id:
            return {"task": "", "narration": "", "tools": 0, "running": False}
        task, texts, tools = "", [], 0
        for part, msg in _transcript(conn, child):
            if part.get("type") == "tool":
                tools += 1
                continue
            t = _real_text(part)
            if not t:
                continue
            if msg.get("role") == "user":
                if not task:
                    task = t[:8000]        # the full dispatch prompt, not the card blurb
            else:
                texts.append(t)
        return {"task": task, "narration": "\n\n".join(texts)[:40000], "tools": tools,
                "running": (time.time() - _epoch(row[7])) < LIVE_WINDOW}
    finally:
        _close(conn)


class OpencodeProvider(Provider):
    prefix = "opencode:"

    def available(self):
        return bool(config.OPENCODE_DB) and os.path.isfile(config.OPENCODE_DB)

    def list(self):
        return list_opencode()

    def parse(self, sid):
        return parse_opencode(sid[len(self.prefix):])

    def search(self, q):
        return search_opencode(q)

    def exists(self, sid):
        # cheap: one indexed PK lookup, not a full transcript parse
        conn = _open()
        if conn is None:
            return False
        try:
            return bool(_rows(conn, "SELECT 1 FROM session WHERE id = ? LIMIT 1",
                              (sid[len(self.prefix):],)))
        finally:
            _close(conn)

    # drill-downs — reached through registry.drill(), which has already checked exists()
    def output(self, sid, cmd_id):
        return command_output(sid[len(self.prefix):], cmd_id)

    def diff(self, sid, target):
        return file_diffs(sid[len(self.prefix):], target)

    # shell(): inherited default {"cmd":"","out":"","running":False} — opencode has no
    # background shells to tail, so the session exists and records nothing here.

    def agent(self, sid, aid):
        return agent_detail(sid[len(self.prefix):], aid)
