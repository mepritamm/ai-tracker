import datetime as _dt
import json, os, sqlite3, time
import urllib.parse
from ..config import LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import (_short_title, _git_branch, cmd_kind, COMMIT_MSG_RE,
                    collect_prs, note_pr_states, prs_sorted, pr_worked, pr_summary, push_when,
                    PR_CREATE_RE, unified, context_window, todo_summary, todo_times_approximate,
                    now_phrase)
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
                 "tokens_input, tokens_output, tokens_cache_read, tokens_cache_write, version")


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


def _last_message_ended(conn, sid):
    """True iff this session's LAST message (by time_created/id — not by part) is an
    assistant turn that reached time.completed. Factored out of _list_state so
    parse_opencode's meta["ended"] can share this EXACT rule instead of a second,
    possibly-drifting re-derivation."""
    last = _rows(conn, "SELECT data FROM message WHERE session_id = ? "
                       "ORDER BY time_created DESC, id DESC LIMIT 1", (sid,))
    m = _json(last[0][0]) if last else {}
    return (m.get("role") == "assistant") and bool(_d(m.get("time")).get("completed"))


def _list_state(conn, sid):
    """(prompt, waiting, ended, last_text, fail_cmd, pr_num, pr_url, pr_repo, pr_state) for
    the sidebar — the opencode analog of _auggie_state / claude.py's _tail_scan, all folded
    into ONE pass over the session's parts. This function only ever runs on a cache miss (see
    _LIST_CACHE below), so the extra work below only lands on a session whose activity
    actually moved since the last poll — never on every poll of every session.

    `waiting`: ANY `question` tool call is still unresolved (opencode's ask-user; a resolved
    one lands on status completed/error) → blocked on the human, not idle. Tracked per callID,
    latest status wins per call — the same semantics parse_opencode's `asks` dict and its
    `any(a["open"] ...)` use (Claude's and Auggie's list states agree: any open ask = waiting).
    THE BUG this replaced: the old loop kept only the LAST question part seen and overwrote
    `waiting` on every iteration, so q1-unresolved-then-q2-answered read as waiting=False here
    while parse_opencode's detail view (any-of semantics) read the same session as waiting=True.
    `ended`: see _last_message_ended.
    `last_text`: the most recent ASSISTANT narration snippet seen in this same scan — feeds
    the board tile's now_line narration fallback (list_opencode, below); same "what's true
    right now, latest wins" rule claude.py's _tail_scan uses for its own `last_text`.
    `fail_cmd`: the latest `bash` tool call's command (<=60 chars) if it errored, else None —
    same latest-wins rule. opencode has no Claude-Code-style "the harness refused to even run
    this" wrapper to filter out (see claude.py's _is_real_bash_error) — every bash tool part
    here genuinely ran, so status=="error" is always a real failure.
    `pr_num`/`pr_url`/`pr_repo`/`pr_state`: the one representative CREATED PR (util.pr_summary),
    scanned off each bash command + its already-captured output in this SAME pass — no extra
    query, unlike claude.py's budgeted _fill_pr (that budget exists because Claude's list-level
    tail read runs UNCONDITIONALLY every poll; this scan only runs on a cache miss, so it is
    already bounded to sessions whose transcript actually changed)."""
    prompt = ""
    last_text = ""
    fail_cmd = None
    open_asks = {}   # callID -> still open?
    prs, pr_states = {}, {}
    for part, msg in _transcript(conn, sid):
        ptype = part.get("type")
        if ptype == "tool" and part.get("tool") == "question":
            open_asks[part.get("callID")] = _d(part.get("state")).get("status") not in (
                "completed", "error")
            continue
        if ptype == "tool" and part.get("tool") == "bash":
            st = _d(part.get("state"))
            inp = st.get("input") if isinstance(st.get("input"), dict) else {}
            c = inp.get("command")
            if isinstance(c, str) and c:
                ts = _iso(part.get("time_created") or _d(msg.get("time")).get("created"))
                fail_cmd = c[:60] if st.get("status") == "error" else None
                collect_prs(prs, c, ts)
                note_pr_states(pr_states, c)
                out = st.get("output")
                if isinstance(out, str) and out:
                    collect_prs(prs, out[:20000], ts, created=bool(PR_CREATE_RE.search(c)))
                    note_pr_states(pr_states, out[:20000])
            continue
        role = msg.get("role")
        if role == "user":
            if prompt:
                continue
            t = _real_text(part)
            if t:
                prompt = " ".join(t.split())[:200]
        elif role == "assistant":
            t = _real_text(part)
            if t:
                last_text = " ".join(t.split())[:200]     # latest wins
    waiting = any(open_asks.values())
    ended = (not waiting) and _last_message_ended(conn, sid)
    pr_num, pr_url, pr_repo, pr_state = pr_summary(prs, pr_states)
    return prompt, waiting, ended, last_text, fail_cmd, pr_num, pr_url, pr_repo, pr_state


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


def _todo_batch(conn):
    """sid -> [{"content","status","activeForm"}] for EVERY session's todos, one query for the
    whole list-poll instead of an N+1 SELECT per session — this is the gap that left
    todo_total/todo_done/todo_current/todo_current_index unset on the list dict: _todos()
    (below) exists but used to only ever be called from the (per-session, on-demand) detail
    path. Shape is the minimal one util.todo_summary() actually reads; the detail dict's
    fuller contract (desc/id/started_at/ended_at) lives on _todos() instead."""
    out = {}
    for sid, c, s in _rows(conn, "SELECT session_id, content, status FROM todo "
                                 "ORDER BY session_id, position ASC"):
        out.setdefault(sid, []).append({"content": c or "", "status": s or "pending",
                                        "activeForm": c or ""})
    return out


def _bg_batch(conn):
    """parent_id -> # of that parent's `task`-dispatch child sessions still running
    (LIVE_WINDOW) — the list dict's `bg` field (was hardcoded 0). One query for the whole
    list-poll instead of an N+1 SELECT per session, mirroring _todo_batch above: this used
    to be _bg_count(conn, sid), called once per session in the list_opencode loop below —
    77 individual parent_id lookups on this machine's corpus, the same N+1 shape _todo_batch
    was written to eliminate for todos."""
    now = time.time()
    out = {}
    for parent, tu in _rows(conn, "SELECT parent_id, time_updated FROM session "
                                  "WHERE parent_id IS NOT NULL"):
        if (now - _epoch(tu)) < LIVE_WINDOW:
            out[parent] = out.get(parent, 0) + 1
    return out


def list_opencode():
    """One query for the session rows plus one activity query each over `part` and `message`;
    the transcript scan (prompt/waiting/ended/last_text/fail_cmd/PRs, in _list_state) runs
    only for sessions whose real activity (not just the session row) moved since the last
    poll. Todos are read once for ALL sessions via _todo_batch (one query, not N+1); `bg` is
    read once for ALL sessions via _bg_batch (one query, not N+1)."""
    conn = _open()
    if conn is None:
        return []
    try:
        db = config.OPENCODE_DB
        titles = load_titles()
        activity = _activity(conn)
        todos_by_sid = _todo_batch(conn)
        bg_by_sid = _bg_batch(conn)
        out = []
        for (sid, parent, cwd, title, _agent, model_raw, _tc, tu, *_tok) in _rows(
                conn, "SELECT " + _SESSION_COLS + " FROM session ORDER BY time_updated DESC"):
            key = max(tu or 0, activity.get(sid, 0))
            cache_id = (db, sid)
            hit = _LIST_CACHE.get(cache_id)
            if hit and hit[0] == key:
                (prompt, waiting, ended, last_text, fail_cmd,
                 pr_num, pr_url, pr_repo, pr_state) = hit[1]
            else:
                (prompt, waiting, ended, last_text, fail_cmd,
                 pr_num, pr_url, pr_repo, pr_state) = _list_state(conn, sid)
                _LIST_CACHE[cache_id] = (key, (prompt, waiting, ended, last_text, fail_cmd,
                                                pr_num, pr_url, pr_repo, pr_state))
            gid = "opencode:" + sid
            cwd = cwd or ""
            mt = _epoch(tu)
            bg = bg_by_sid.get(sid, 0)
            todo_total, todo_done, todo_current, todo_current_index = todo_summary(
                todos_by_sid.get(sid, []))
            # "what's happening now" board-tile phrase — LIVE sessions only, mirroring
            # claude.py's list_sessions priority (waiting > running agents > in-progress todo >
            # latest narration). opencode has no background-shell concept at all, so that rung
            # of Claude's ladder is skipped outright (shells_running is always 0 below).
            now_line = ""
            if (time.time() - mt) < LIVE_WINDOW:
                if not ended and waiting:
                    now_line = "⧖ waiting for your answer"
                elif bg:
                    now_line = "⚙ %d background agent%s" % (bg, "" if bg == 1 else "s")
                elif not ended and todo_current:
                    now_line = "▶ " + now_phrase(todo_current)
                elif not ended and last_text:
                    now_line = now_phrase(last_text)
            out.append({
                "id": gid, "project": os.path.basename(cwd) if cwd else "opencode", "cwd": cwd,
                "title": titles.get(gid) or title or _short_title(prompt) or "opencode session",
                "prompt": prompt, "source": "opencode", "mtime": mt,
                # a session with a parent IS a sub-agent run (opencode's `task` tool spawns one),
                # so it nests under its parent in the sidebar exactly like Claude's sdk-cli sessions.
                "agent": bool(parent), "group": "", "groupLabel": "",
                "parentId": ("opencode:" + parent) if parent else "",
                "bg": bg, "first": 0,
                "waiting": waiting, "ended": ended,
                "todo_total": todo_total, "todo_done": todo_done, "todo_current": todo_current,
                "todo_current_index": todo_current_index,
                # the ONE representative PR this session CREATED (util.pr_summary) — None/""
                # while genuinely absent, never a guess.
                "pr_num": pr_num, "pr_url": pr_url, "pr_repo": pr_repo, "pr_state": pr_state or "",
                "now_line": now_line,
                # current model id, straight off session.model — verified in sync with the
                # session's own last assistant message on this machine's whole corpus (0/77
                # mismatches; see parse_opencode's meta["model"] for the same read).
                "model": _model(model_raw),
                "fail_cmd": fail_cmd,
                # opencode has no background-shell concept at all — genuinely, always 0,
                # never omitted (see the `shells: []` note in parse_opencode below).
                "shells_running": 0,
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
    (completed/in_progress/pending) — no state mapping needed, unlike Auggie's.

    `id`: the row's own `position` (stringified) — a stable, real per-session ordinal, not a
    guessed index. `desc`: opencode's todo table has no description column — honest "".
    `started_at`/`ended_at`: EPOCH SECONDS (the table stores MILLIseconds — via `_epoch`) off
    the row's OWN `time_created`/`time_updated` — REAL per-row timestamps, unlike Auggie's
    name-matched approximation (see the `todo_times_approximate` key on the result dict,
    below, in parse_opencode). Gated the same way Claude's task-store join gates
    started_at/ended_at: only a row that has actually reached in_progress/completed gets a
    started_at, and only one currently completed gets an ended_at — a stray content-only edit
    that merely bumped time_updated on a still-pending row must not read as "ended"."""
    out = []
    for c, s, tc, tu, pos in _rows(
            conn, "SELECT content, status, time_created, time_updated, position "
                 "FROM todo WHERE session_id = ? ORDER BY position ASC", (sid,)):
        status = s or "pending"
        out.append({
            "content": c or "", "status": status, "activeForm": c or "", "desc": "",
            "id": str(pos),
            "started_at": _epoch(tc) if status in ("in_progress", "completed") else None,
            "ended_at": _epoch(tu) if status == "completed" else None,
        })
    return out


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
         tok_in, tok_out, tok_cr, tok_cw, s_version) = row
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
        # last failing command's text (<=60 chars) — mirrors claude.py's detail-dict `fail_cmd`
        # (parse_session, ~1475): the most recent `ok=False` command in this session, honestly
        # None when nothing failed. `cmds` already carries `ok` per-entry (opencode's tool part
        # carries its own status directly — no separate tool_result join needed, unlike Claude).
        fail_cmd = next((c["cmd"][:60] for c in reversed(cmds) if not c["ok"]), None)
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
                     # session.model verified in sync with the session's own last assistant
                     # message across this machine's whole corpus (0/77 mismatches) — trusted
                     # unconditionally, same "last wins" intent as Claude's per-message read.
                     "model": _model(model_raw), "gitBranch": branch,
                     "sessionId": sid,
                     # exact same rule the sidebar's ✅ uses (_last_message_ended) — last
                     # message is an assistant turn that reached time.completed.
                     "ended": _last_message_ended(conn, sid),
                     "aiTitle": s_title or "",
                     # opencode's message rows carry no per-message model/variant/effort field
                     # at all — verified across every message on this machine (2000/2000, 0
                     # hits for "variant"/"effort"/"reasoningEffort"). Honest empty, not a guess.
                     "effort": "",
                     # session.version IS the real, non-guessed field here — session.metadata
                     # (the field the audit named) is empty JSON on every session on this
                     # machine (0/77 non-empty); the schema's separate `version` COLUMN carries
                     # the actual opencode app version (e.g. "1.18.18") and is the honest parity
                     # match for Claude's meta["version"] (also an app/CLI version).
                     "version": s_version or "",
                     # opencode has no second title slot — the session row's only title IS
                     # aiTitle/s_title above. Honest empty.
                     "customTitle": ""},
            "todos": todos,
            # opencode's todo table has REAL per-row time_created/time_updated (see _todos), not
            # a name-matched guess — so, unlike Auggie/Augment, this is EXACT (False). The shared
            # seam (util.todo_times_approximate) now knows this too, so it's called like every
            # other provider does rather than re-deriving the policy here.
            "todo_times_approximate": todo_times_approximate("opencode"),
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
            # board "failing" tile signal, SAME field name as the list dict — see fail_cmd's
            # computation above. Honestly None when nothing failed, never omitted.
            "fail_cmd": fail_cmd,
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
        # THE TRAP this fixes: with no SQL LIMIT, this fetched EVERY session row (and every
        # column _SESSION_COLS names) before the Python-side `break` below could ever bound
        # it — the break only stopped the loop, not the query's own cost. Push the bound into
        # the SQL itself so the two can't drift apart again.
        for (sid, parent, cwd, title, _a, _m, _tc, tu, *_tok) in _rows(
                conn, "SELECT " + _SESSION_COLS + " FROM session ORDER BY time_updated DESC "
                      "LIMIT ?", (limit,)):
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
