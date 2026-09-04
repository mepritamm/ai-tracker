import glob, json, os, re, time
from ..config import EDIT_TOOLS, LIVE_WINDOW, NARRATION_CAP
from .. import config
from ..util import _dur, _names, _short_title, _first_line, _window, _iso_epoch, _ts_epoch, _git_branch, cmd_kind, TEST_RE, COMMIT_MSG_RE, collect_prs, note_pr_states, prs_sorted, pr_worked, pr_summary, push_when, PR_CREATE_RE, unified as _unified, safe_path_component, context_window, todo_summary, todo_times_approximate, now_phrase
from ..overview import build_overview
from ..store import load_titles, load_tasks, load_notes, _TSTATUS
from .base import Provider

# TaskCreate's tool_result is a plain confirmation string, e.g. "Task #7 created
# successfully: <subject>" -- confirmed against real transcripts. The number is the
# SAME ordinal load_tasks() reads off the task-store file's own stem (store.py's
# load_tasks docstring: taskId "20" <-> "20.json"), so it's the exact join key for
# reconstructing todos when ~/.claude/tasks/<sid>/*.json has been pruned.
_TASK_CREATE_ID_RE = re.compile(r"Task #(\d+) created successfully")


# Fixed prefixes/substrings Claude Code's OWN permission system, worktree-isolation guard,
# blocked-command guard, auto-mode classifier, and reject-this-tool-use flow write into a
# Bash tool_result's `content` when it refuses to run a command at all -- confirmed against
# every is_error Bash tool_result on this machine's real corpus (~950 sessions, reports/
# drift/): measured 116/957 real sessions carrying a fail_cmd before this filter, and EVERY
# ONE of them was one of these refusals, never a real command failure (the single most
# common by a wide margin: an unrelated automated bot's Bash calls denied under "don't ask"
# mode, printf'ing a JSON verdict it never got to write). A command Claude Code itself
# refused to run can't be what broke the user's work, so it must not set fail_cmd.
_BASH_REFUSAL_PREFIXES = (
    "Permission to use Bash",                    # "...has been denied because Claude Code is
                                                  # running in don't ask mode" / "...with command
                                                  # X\n...has been denied" -- never ran
    "This session is isolated in the worktree",  # bg-isolation guard -- never ran
    "Permission for this action was denied by the Claude Code auto mode classifier",
    "The user doesn't want to proceed with this tool use.",  # explicit user rejection
    "<tool_use_error>Blocked:",                  # command-blocking guard (e.g. a bare `sleep`)
    "<tool_use_error>Cancelled:",                # a parallel sibling call errored; this one
                                                  # was never actually run
)
# Model name varies ("claude-sonnet-5[1m]", "claude-opus-4-8", ...) so this can't be a
# fixed prefix -- matched as a substring instead: "<model> is temporarily unavailable, so
# auto mode cannot determine the safety of <Tool> right now" -- the auto-mode classifier
# itself is down, so the command was never even evaluated, let alone run.
_BASH_REFUSAL_SUBSTRING = "auto mode cannot determine the safety of"


def _is_real_bash_error(text):
    """True iff a Bash tool_result's content (already known `is_error`) reflects the
    command actually RUNNING and exiting nonzero -- not one of Claude Code's own
    never-ran-at-all refusals (see `_BASH_REFUSAL_PREFIXES` above). Non-string/empty
    content can't be classified either way -- treated as real (True) so an is_error
    result is never silently hidden just because its content couldn't be read.

    # ponytail: this is a textual match on Claude Code's own fixed refusal strings, not
    # a session-log field -- if a future Claude Code version rewords one of them, this
    # silently stops catching it (fail_cmd goes noisy again, never wrong the other way).
    # No structural field distinguishing "the command ran" from "the framework refused
    # it" was found on this corpus (checked: tool_use's own `caller` field is always
    # {"type": "direct"}, no hook/system variant appears in ~30k real tool_use blocks).
    # Upgrade path: re-grep a fresh corpus's is_error Bash content for new refusal
    # wording and add it to `_BASH_REFUSAL_PREFIXES`/`_BASH_REFUSAL_SUBSTRING` above.
    """
    if not isinstance(text, str) or not text:
        return True
    if text.startswith(_BASH_REFUSAL_PREFIXES):
        return False
    return _BASH_REFUSAL_SUBSTRING not in text


def find_session(sid):
    sid = sid.strip().replace(".jsonl", "")
    # sid is URL-sourced and lands straight in a glob.glob() pattern below — unlike a
    # plain path join, glob also honours `*`/`?`/`[...]`, so an unsanitised sid can
    # both traverse (`../../etc/passwd`) AND disclose an arbitrary sibling session
    # (sid="*" matches literally any session in any project dir). Real Claude
    # session ids are bare uuids, so this rejects nothing legitimate.
    sid = safe_path_component(sid)
    if sid is None:
        return None
    hits = glob.glob(os.path.join(config.PROJECTS, "*", sid + ".jsonl"))
    return hits[0] if hits else None


_META_CACHE = {}

# Wall-clock budget for _fill_pr() calls in one list_sessions() poll — see the call site.
# Time-boxed rather than count-boxed so a run of small transcripts drains more of the
# backlog in one poll while a few p95-sized (~6.6MB, ~28ms) ones still bail out in time.
_PR_SCAN_BUDGET_SECS = 0.05


def _tail_scan(path, nbytes=96000):
    """aiTitle/customTitle/entrypoint live on metadata lines written as the
    session evolves — read the tail to get the current values cheaply. The same
    pass yields the session's end-state for the sidebar: `waiting` (an
    AskUserQuestion is still unanswered) and `ended` (the last real turn was the
    assistant finishing — 'completed last run'). A waiting question always sits at
    the tail, so the 96 KB window sees it; a giant single turn is the only miss.

    Also harvests `last_text` — the most recent assistant narration snippet seen in
    this SAME bounded tail (capped short) — so the session-list `now_line` field
    (list_sessions, below) can derive a "what is it doing" phrase for a LIVE session
    with zero extra file access: this tail read already happens for every session to
    get waiting/ended, so folding the extra bookkeeping in here costs nothing beyond
    a few string ops per line. Returns a dict (not a tuple) so future fields can be
    added here without breaking `_tail_fields`'s existing positional callers below.

    Also harvests `model` — the LATEST `message.model` seen in this same bounded tail
    (last value wins, so a mid-session /model switch shows the CURRENT model, matching
    `last_text`/`now_line`'s "what's true right now" framing, not the session's first
    model). "<synthetic>" is a real value seen in the wild on synthetic/compaction
    messages, not a genuine model id — skipped so it never overwrites a real one and
    never surfaces alone. Honestly "" when no real model appears in the tail at all
    (e.g. a session with no assistant turn yet).

    Also harvests `fail_cmd` — the board's "failing" tile signal, off this SAME bounded
    tail (zero extra I/O): a Bash `tool_use` seen in the tail records its id -> command
    text; the matching `tool_result`'s `is_error` flag AND its content (checked below,
    is_error is the same join parse_session's `errors_by_id` does over the WHOLE file —
    content is the new part, see `_is_real_bash_error`) decide pass/fail. Latest REAL
    Bash result in the tail wins — a later PASS clears an earlier FAIL, same "what's
    true right now" rule as model/last_text — so `fail_cmd` is None unless the most
    recently completed Bash command in this tail actually ran and errored (a command
    Claude Code itself refused to run — a permission denial, a worktree guard, a user
    rejection — is not a real failure and is skipped; see `_is_real_bash_error`). A
    giant single command's tool_use can in principle fall outside the 96 KB window
    while its result is inside (same known limitation as the waiting-question miss
    above); that just means the id is unmatched and this stays honestly None, never
    a guess."""
    ai = custom = entry = None
    last_text = ""
    model = ""
    bash_cmds = {}   # tool_use_id -> command text[:60], Bash calls seen in this tail
    fail_cmd = None
    open_asks, last = set(), ""
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
            m = o.get("message")
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if o.get("type") == "assistant":
                mv = m.get("model")
                if isinstance(mv, str) and mv and mv != "<synthetic>":
                    model = mv
                blocks = c if isinstance(c, list) else []
                has_tool = False
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "tool_use":
                        has_tool = True
                        if b.get("name") == "AskUserQuestion" and b.get("id"):
                            open_asks.add(b["id"])          # opened; a matching tool_result answers it
                        elif b.get("name") == "Bash" and b.get("id"):
                            cmdtxt = (b.get("input") or {}).get("command")
                            if isinstance(cmdtxt, str) and cmdtxt:
                                bash_cmds[b["id"]] = cmdtxt[:60]
                    elif bt == "text":
                        t = (b.get("text") or "").strip()
                        if t and not t.startswith("<"):     # skip command/system echoes
                            last_text = t[:200]             # most recent assistant narration in this tail
                last = "assistant_tool" if has_tool else "assistant_text"
            elif m.get("role") == "user":
                if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    for b in c:                              # the user's answer closes the question
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            tid = b.get("tool_use_id")
                            open_asks.discard(tid)
                            if tid in bash_cmds:              # latest REAL Bash result in the tail wins
                                if b.get("is_error"):
                                    cc = b.get("content")
                                    rtext = cc if isinstance(cc, str) else (json.dumps(cc) if cc else "")
                                    if _is_real_bash_error(rtext):
                                        fail_cmd = bash_cmds[tid]
                                    # else: Claude Code's own guard refused the command before it
                                    # ever ran -- not a real failure, leave fail_cmd as it was (see
                                    # _is_real_bash_error)
                                else:
                                    fail_cmd = None
                    last = "tool_result"
                elif o.get("isMeta"):
                    pass                                     # injected system text (task-notification, skill reload) — not a turn
                else:
                    s = c.strip() if isinstance(c, str) else "\n".join(
                        b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip() if isinstance(c, list) else ""
                    if s and not s.startswith("<"):
                        last = "user_prompt"                 # user typed; assistant hasn't answered -> working
    except OSError:
        pass
    waiting = bool(open_asks)
    ended = (not waiting) and last == "assistant_text"
    return {"ai": ai, "custom": custom, "entry": entry, "waiting": waiting, "ended": ended,
            "last_text": last_text, "model": model, "fail_cmd": fail_cmd}


def _tail_fields(path, nbytes=96000):
    """Back-compat positional shape over _tail_scan (ai, custom, entry, waiting, ended) —
    kept because both _session_meta (below, now calls _tail_scan directly for last_text
    too) and the existing test suite unpack/slice this exact 5-tuple."""
    s = _tail_scan(path, nbytes)
    return s["ai"], s["custom"], s["entry"], s["waiting"], s["ended"]


def _session_meta(path):
    """cwd + best title (custom > ai > opening prompt) + entrypoint + sessionKind, cached by mtime."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {"cwd": "", "title": "", "source": "", "prompt": "", "first": 0, "waiting": False, "ended": False, "sessionKind": None,
                "pr_num": None, "pr_url": None, "pr_repo": None, "pr_state": "", "last_text": "", "model": "", "fail_cmd": None}
    hit = _META_CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    cwd = prompt = entry_head = first_ts = ""
    session_kind = None
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
                if session_kind is None and o.get("sessionKind"):
                    session_kind = o["sessionKind"]
                if not first_ts and o.get("timestamp"):
                    first_ts = o["timestamp"]          # session start — used to attribute agents to their live orchestrator
                if not prompt:
                    m = o.get("message")
                    if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                        s = " ".join(m["content"].split())
                        if s and not s.startswith("<") and not s.startswith("Caveat:"):
                            prompt = s[:140]
    except OSError:
        pass
    ts = _tail_scan(path)
    meta = {
        "cwd": cwd,
        "title": ts["custom"] or ts["ai"] or _short_title(prompt),
        "prompt": prompt,
        "source": ts["entry"] or entry_head or "",
        "first": _ts_epoch(first_ts),   # sub-second so same-second orchestrator/agent starts still order
        "waiting": ts["waiting"],       # an AskUserQuestion is unanswered -> sidebar ⏳
        "ended": ts["ended"],           # last real turn was the assistant finishing -> sidebar ✅ (completed)
        "sessionKind": session_kind,    # "bg" for real background agents (claude --bg)
        # Most recent assistant narration text seen in the SAME bounded tail read above (no
        # extra file access) -- the session-list `now_line` field's narration fallback when
        # this session is LIVE (see list_sessions). Never shown for an idle/ended session.
        "last_text": ts["last_text"],
        # Current model (latest wins, "<synthetic>" skipped) from the SAME bounded tail --
        # the session-list `model` field, unconditional (unlike now_line, shown for idle and
        # ended sessions too -- see list_sessions).
        "model": ts["model"],
        # Board "failing" tile signal -- the most recently completed Bash command's name
        # in this SAME bounded tail if it errored, else honestly None. See _tail_scan's
        # docstring for the join and its "latest wins" semantics.
        "fail_cmd": ts["fail_cmd"],
        # PR data is the expensive half — a full-file scan (collect_prs et al, ~1ms median but
        # ~28ms at the p95 file size) that this cheap 40-line/tail-only pass must not eat. Only
        # an ENDED session can ever render as a Landed tile (ext_cr_board.js's sessionState()),
        # so a session still mid-conversation gets these nailed to "none" for good — no scan,
        # no pending, no reconsideration until it changes again. An ended session gets this
        # placeholder plus `_pr_pending`; list_sessions() resolves it (budgeted, and only for
        # sessions still inside LIVE_WINDOW — the only ones a Landed tile could ever be) by
        # mutating this SAME cached dict in place, so the answer sticks at this mtime with no
        # second cache write.
        "pr_num": None, "pr_url": None, "pr_repo": None, "pr_state": "",
    }
    if ts["ended"]:
        meta["_pr_pending"] = True
    _META_CACHE[path] = (mt, meta)
    return meta


def _scan_created_prs(path):
    """Full-file scan for PRs THIS session created (`gh pr create` / GitHub MCP
    create_pull_request) — the same tracking parse_session's detail path does (matching a
    `gh pr create` Bash call or an MCP create_pull_request tool_use to ITS OWN tool_result,
    the only way to know a URL came from a creation rather than merely being mentioned), via
    the same primitives (collect_prs/note_pr_states/PR_CREATE_RE) — just narrower: skips
    narration/files/todos/agents, everything parse_session's detail dict needs beyond PRs.
    Malformed/unreadable input yields no PR, same as a session that genuinely created none."""
    prs, pr_states, pr_create_ids = {}, {}, set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                m = o.get("message")
                if not isinstance(m, dict):
                    continue
                content = m.get("content")
                if not isinstance(content, list):
                    continue
                ts = o.get("timestamp", "")
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "tool_use":
                        name, inp, bid = b.get("name"), b.get("input") or {}, b.get("id")
                        if name == "Bash":
                            c = inp.get("command", "")
                            if PR_CREATE_RE.search(c):       # its result URL is a created PR
                                pr_create_ids.add(bid)
                            note_pr_states(pr_states, c)     # `gh pr merge/close N`
                        elif name and "create_pull_request" in name:   # GitHub MCP
                            pr_create_ids.add(bid)
                        elif name and "merge_pull_request" in name:
                            pn = inp.get("pullNumber") or inp.get("pull_number")
                            if pn:
                                pr_states[str(pn)] = "merged"
                    elif bt == "tool_result":
                        rid = b.get("tool_use_id")
                        cc = b.get("content")               # command output: gh prints the PR URL here
                        rtext = cc if isinstance(cc, str) else (json.dumps(cc) if cc else "")
                        collect_prs(prs, rtext, ts, rid in pr_create_ids)
                        note_pr_states(pr_states, rtext)     # git-log "Merge pull request #N" etc.
    except OSError:
        pass
    return prs, pr_states


def _fill_pr(meta, path):
    """The expensive half of an ended session's PR data — deferred out of _session_meta (see
    its `_pr_pending` placeholder) so list_sessions() can budget how many of these run per
    poll, instead of a burst of sessions finishing together stalling the whole poll behind
    their full-file scans. Mutates `meta` in place; _META_CACHE stores this exact dict object,
    so the resolution persists at this mtime without a second cache write."""
    prs, pr_states = _scan_created_prs(path)
    meta["pr_num"], meta["pr_url"], meta["pr_repo"], meta["pr_state"] = pr_summary(prs, pr_states)
    meta["_pr_pending"] = False


def _is_bg_agent(sm):
    """True when a session's OWN TRANSCRIPT claims to be a background agent -- either a
    real `claude --bg` agent (sessionKind == "bg") or an SDK-spawned one (source ==
    "sdk-cli"). Drives ONLY the sidebar's 🤖 badge (list_sessions/search_sessions,
    below) -- a session that WAS a background agent should stay badged as one forever,
    which is exactly why this is transcript-based rather than live: a finished agent's
    transcript still says so long after `claude` itself has forgotten it.

    Do NOT reuse this to decide whether `claude --resume <sid>` needs --fork-session.
    It used to be reused for exactly that (via a since-removed ClaudeProvider.is_bg_agent
    / registry.is_bg_agent seam) and that was WRONG: this field stays true long after
    `claude agents --json` has stopped listing the session as forkable, so using it to
    fork pre-emptively handed the user a COPY under a new session id when a plain resume
    would have reopened their real conversation. See term_gate.resume_argv's docstring
    for what that decision relies on now instead."""
    return sm.get("sessionKind") == "bg" or sm.get("source") == "sdk-cli"


_WT_MARKER = os.sep + ".claude" + os.sep + "worktrees" + os.sep


def _agent_group(cwd, source):
    """An SDK-spawned session (entrypoint=sdk-cli) is a background *agent* session; the
    sidebar folds these under a collapsible per-repo group instead of listing each flat.
    Returns (groupKey, groupLabel): the repo it belongs under. Worktree agents ->
    the repo root (path before /.claude/worktrees/); temp cc-agentic sandboxes ->
    a shared 'sandbox' bucket; any other sdk-cli -> its own cwd. Non-agents -> ('','')."""
    if source != "sdk-cli":
        return "", ""
    cwd = cwd or ""
    if _WT_MARKER in cwd:
        repo = cwd.split(_WT_MARKER, 1)[0]
        return repo, (os.path.basename(repo) or repo)
    if "cc-agentic-" in cwd or "/T/" in cwd:              # ephemeral SDK sandbox
        return "sandbox", "sandbox"
    return cwd or "sandbox", (os.path.basename(cwd) or "sandbox")


def _worktree_name(cwd):
    """The worktree folder name for a worktree agent session, else ''."""
    return cwd.split(_WT_MARKER, 1)[1].split(os.sep)[0] if cwd and _WT_MARKER in cwd else ""


def _pick_parent(agent_first, humans):
    """Attribute an agent to its originating session: of the human sessions sharing its dir,
    the one whose start-time is the latest <= the agent's start (the orchestrator that was
    live when the agent spawned — correct across resume chains). Falls back to the earliest
    KNOWN-start human when the agent predates them all. humans: [(id, first_epoch), ...].
    Ties break by id, so the result is independent of the order humans are fed in — the
    sidebar (mtime order) and the detail panel (glob order) can't disagree. A first==0
    (start not yet written) is treated as unknown, never as 'earliest'."""
    if not humans:
        return ""
    real = [h for h in humans if h[1]]                       # humans with a parsed start
    if agent_first:
        prev = [h for h in real if h[1] <= agent_first]
        if prev:
            return max(prev, key=lambda h: (h[1], h[0]))[0]  # latest start; id tie-break => order-independent
    pool = real or humans
    return min(pool, key=lambda h: (h[1] or 0, h[0]))[0]     # earliest known start; id tie-break


def _same_dir_sessions(projdir):
    """(humans, agents) whose session file lives in this project dir. An orchestrator and the
    agents it spawned share the dir (the SDK writes each agent transcript beside the parent),
    even when their cwd *fields* differ — a repo-root orchestrator's file still lands in the
    worktree's project dir. humans=[(id, first)], agents=[(id, path, meta)]."""
    humans, agents = [], []
    for f in glob.glob(os.path.join(projdir, "*.jsonl")):
        sm = _session_meta(f)
        fid = os.path.basename(f)[:-6]
        if sm["source"] == "sdk-cli":
            agents.append((fid, f, sm))
        else:
            humans.append((fid, sm["first"]))
    return humans, agents


def child_agent_sessions(sid, projdir):
    """The agent (sdk-cli) sessions this session originated — same project dir, and this session
    won the _pick_parent attribution. Surfaced in the parent's background-agents panel to jump
    straight into an agent. Scans just this one dir (agents live beside their orchestrator), so
    it uses the SAME candidate set list_sessions does — the two views can't disagree."""
    humans, agents = _same_dir_sessions(projdir)
    if not agents:
        return []
    titles = load_titles()
    # Collapse re-runs of the SAME agent: an orchestrator re-spawns a finding many times (one sdk-cli
    # session each), which inflated the count. Group by task (the agent's first prompt) so each distinct
    # agent is one entry — representative = the most recent run (the open target) — with runs=N executions.
    groups = {}
    for fid, f, sm in agents:
        if _pick_parent(sm["first"], humans) != sid:
            continue
        mt = _active_mtime(f)
        running = (time.time() - mt) < LIVE_WINDOW
        key = sm["prompt"] or sm["title"] or fid
        g = groups.get(key)
        if g is None:
            groups[key] = {"id": fid, "title": titles.get(fid) or sm["title"], "wt": _worktree_name(sm["cwd"]),
                           "running": running, "mtime": mt, "runs": 1}
        else:
            g["runs"] += 1
            g["running"] = g["running"] or running
            if mt >= g["mtime"]:                       # newest run represents the group
                g["mtime"] = mt; g["id"] = fid; g["title"] = titles.get(fid) or sm["title"]
    out = sorted(groups.values(), key=lambda r: r["mtime"], reverse=True)
    return out


def list_sessions(limit=200):
    fs = glob.glob(os.path.join(config.PROJECTS, "*", "*.jsonl"))
    fs.sort(key=os.path.getmtime, reverse=True)
    titles = load_titles()
    metas = {f: _session_meta(f) for f in fs}   # cached; cheap on repeat
    # candidate orchestrators per project dir, over ALL sessions (not just the top-N shown) so the
    # sidebar nesting and each session's agent_sessions panel attribute from the identical set.
    humans_by_dir = {}
    for f in fs:
        sm = metas[f]
        if sm["source"] != "sdk-cli":
            humans_by_dir.setdefault(os.path.dirname(f), []).append((os.path.basename(f)[:-6], sm["first"]))
    out = []
    # Budget for _fill_pr() below: wall-clock, not a file count, so a run of small transcripts
    # drains more of the pending backlog in one poll while a few p95-sized (~28ms) ones still
    # bail out in time — any left over just retry next poll (see _pr_pending in _session_meta).
    pr_deadline = time.time() + _PR_SCAN_BUDGET_SECS
    for f in fs[:limit]:
        sm = metas[f]
        sid = os.path.basename(f)[:-6]
        gkey, glabel = _agent_group(sm["cwd"], sm["source"])
        parent = ""
        if sm["source"] == "sdk-cli":
            cands = humans_by_dir.get(os.path.dirname(f))   # a repo-root orchestrator's file lives here too
            if cands:
                parent = _pick_parent(sm["first"], cands)
        mt, bg = _mtime_and_bg(f)
        # Only a session both ENDED and still inside LIVE_WINDOW can ever render as a Landed
        # tile (ext_cr_board.js's sessionState()) — an idle session's PR data would never be
        # shown, so it's left pending indefinitely rather than spending a scan on it. Bounded
        # by pr_deadline so a batch of sessions finishing together can't stall this poll.
        if sm.get("_pr_pending") and (time.time() - mt) < LIVE_WINDOW and time.time() < pr_deadline:
            _fill_pr(sm, f)
        # load_tasks() is a listdir + a handful of small JSON reads under ~/.claude/tasks/<sid>/
        # (0 cost via a single failed listdir for the many sessions with no task store at all;
        # measured ~5 files/session, ~170 total across this machine's whole history) — cheap
        # enough for every /api/list poll, unlike a full parse_session() re-read of the jsonl.
        # Sessions that predate the task store (still in-transcript TodoWrite-only) get 0/0/None
        # here: that would need a full transcript parse to recover, which the list path must not do.
        todo_total, todo_done, todo_current, todo_current_index = todo_summary(load_tasks(sid))
        # now_line: a short "what is it doing right now" phrase for the board tile — LIVE
        # sessions only (inside LIVE_WINDOW and not ended); everything else gets "" for free,
        # no extra file access. Priority mirrors overview.py's build_overview (running agents >
        # in-progress todo > latest narration), computed entirely off data this poll already
        # loaded: `bg` (the same _mtime_and_bg call above), `todo_current` (the same
        # load_tasks() call above), and sm["waiting"]/sm["last_text"] (the same bounded tail
        # read _session_meta already did for waiting/ended — see _tail_scan). Unlike
        # build_overview, a running background agent here can't afford its `lead` detail (that
        # needs a full parse_agents() scan of the agent transcripts — the expensive read this
        # field must not trigger), so it's just a count.
        now_line = ""
        if (time.time() - mt) < LIVE_WINDOW and not sm["ended"]:
            if sm["waiting"]:
                now_line = "⏳ waiting for your answer"
            elif bg:
                now_line = "⚙ %d background agent%s" % (bg, "" if bg == 1 else "s")
            elif todo_current:
                now_line = "▶ " + now_phrase(todo_current)
            elif sm.get("last_text"):
                now_line = now_phrase(sm["last_text"])
        out.append({
            "id": sid,
            "project": os.path.basename(sm["cwd"]) if sm["cwd"] else os.path.basename(os.path.dirname(f)),
            "cwd": sm["cwd"],
            "title": titles.get(sid) or sm["title"],
            "prompt": sm["prompt"],
            "source": sm["source"],
            "agent": _is_bg_agent(sm),               # background-agent session -> 🤖
            "group": gkey, "groupLabel": glabel,     # fallback bucket (repo/sandbox) for orphan agents
            "parentId": parent,                      # the originating session it nests under; "" -> bucket
            "bg": bg,                                # in-transcript background agents live now -> 🤖 sidebar badge
            "waiting": sm["waiting"],                # unanswered AskUserQuestion -> ⏳ sidebar highlight
            "ended": sm["ended"],                    # last turn was the assistant finishing -> ✅ completed
            "mtime": mt,  # counts background-agent activity too
            "todo_total": todo_total, "todo_done": todo_done, "todo_current": todo_current,
            "todo_current_index": todo_current_index,
            # the ONE representative PR this session created (util.pr_summary) — None/""
            # while unresolved (_pr_pending) or genuinely absent; a board tile only ever
            # wants "PR number if any", never the broader referenced-or-narrated set the
            # detail dict's `prs` field carries (see pr_worked).
            "pr_num": sm.get("pr_num"), "pr_url": sm.get("pr_url"),
            "pr_repo": sm.get("pr_repo"), "pr_state": sm.get("pr_state") or "",
            # short "what's happening now" phrase for the board tile — "" unless LIVE (see above)
            "now_line": now_line,
            # current model id (e.g. "claude-opus-5") off the same bounded tail read —
            # unconditional, not gated on liveness: "" only when the tail truly has no signal.
            "model": sm.get("model") or "",
            # board "failing" tile signal (ext_cr_board.js's sessionState()) — the failing
            # Bash command's name, off the SAME bounded tail read as waiting/ended/model
            # above (zero extra I/O); honestly None when nothing failed, never omitted.
            "fail_cmd": sm.get("fail_cmd"),
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
            "agent": _is_bg_agent(sm),               # 🤖 marker in search results too
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


_CMD_NAME_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S)
_CMD_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S)

def _slash_prompt(s):
    """A slash-command invocation is logged as a `<command-name>/foo</command-name> …
    <command-args>bar</command-args>` wrapper string. Render it back to the `/foo bar` the
    user actually typed so it shows as a prompt — the alternative (drop everything starting
    with `<`) silently swallowed every slash command. Non-command `<...>` noise
    (task-notification, system-reminder) has no <command-name> and returns ""."""
    m = _CMD_NAME_RE.search(s)
    if not m:
        return ""
    name = m.group(1).strip()
    a = _CMD_ARGS_RE.search(s)
    args = a.group(1).strip() if a else ""
    return (name + (" " + args if args else "")).strip()


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


def _mtime_and_bg(path):
    """(_active_mtime, # background-agent files live right now). One glob+stat pass so the
    sidebar can badge a session with running in-transcript agents — those spawn no separate
    agent session, so parentId nesting never surfaces them."""
    m = os.path.getmtime(path) if os.path.exists(path) else 0.0
    now, bg = time.time(), 0
    for af in _agent_files(path):
        try:
            amt = os.path.getmtime(af)
        except OSError:
            continue
        m = max(m, amt)
        if now - amt < LIVE_WINDOW:
            bg += 1
    return m, bg


def parse_agents(path):
    """Parse background-agent transcripts: what each one is, doing, and whether it's live.
    Also harvests PRs the agents generated (a `gh pr create`/MCP in a subagent) + their state,
    so a PR opened by a background agent is attributed to the session — not lost with the subagent."""
    out = []
    agent_files = {}      # path -> file entry : edits made by background agents (worktrees etc.)
    agent_prs = {}        # url -> entry : PRs an agent created/worked (merged into the session's prs)
    agent_pr_states = {}  # num -> state : merge/close signals seen in agent transcripts
    newest = 0.0
    now = time.time()
    for af in sorted(_agent_files(path)):
        try:
            mt = os.path.getmtime(af)
        except OSError:
            continue
        newest = max(newest, mt)
        task = last_text = ""
        model = ""    # this agent's own current model -- may differ from its parent's (own separate transcript)
        last_ts = None
        tools = 0
        pr_ids = set()    # tool_use_ids of `gh pr create`/MCP-create in THIS agent → its result URL = created
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
                    mv = m.get("model")   # same "latest wins, skip the synthetic sentinel" rule as _tail_scan
                    if isinstance(mv, str) and mv and mv != "<synthetic>":
                        model = mv
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
                                elif nm == "Bash":                      # agents open PRs too
                                    ac = (b.get("input") or {}).get("command", "")
                                    if PR_CREATE_RE.search(ac):
                                        pr_ids.add(b.get("id"))
                                    collect_prs(agent_prs, ac, last_ts)
                                    note_pr_states(agent_pr_states, ac)
                                elif nm and "create_pull_request" in nm:   # GitHub MCP create in a subagent
                                    pr_ids.add(b.get("id"))
                                elif nm and "merge_pull_request" in nm:
                                    pn = (b.get("input") or {}).get("pullNumber") or (b.get("input") or {}).get("pull_number")
                                    if pn:
                                        agent_pr_states[str(pn)] = "merged"
                            elif b.get("type") == "tool_result":         # a `gh pr create` result carries the new URL
                                cc = b.get("content")
                                rtext = cc if isinstance(cc, str) else (json.dumps(cc) if cc else "")
                                collect_prs(agent_prs, rtext, last_ts, b.get("tool_use_id") in pr_ids)
                                note_pr_states(agent_pr_states, rtext)
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
            # this agent's OWN current model -- its own separate transcript, so it can (and
            # does, in the wild) differ from its parent session's model. "" if this agent's
            # transcript has no assistant turn with a real model id yet.
            "model": model,
        })
    for e in agent_prs.values():
        e["agent"] = True     # generated by a background agent — badge it in the panel
    out.sort(key=lambda a: (not a["running"], a["ts"] or ""), reverse=False)
    return out, newest, agent_files, agent_prs, agent_pr_states


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
    task_times = {}        # taskId (str, == the task-store file's stem) -> {"started": ts, "ended": ts}
                            # filled from TaskUpdate tool calls below — the transcript is already
                            # being walked line-by-line for everything else, so this costs nothing
                            # extra to collect. Confirmed against a real transcript: TaskUpdate's
                            # own `input.taskId` is the exact string load_tasks() now stamps as
                            # each todo's "id" (both trace back to the task-store file's stem, e.g.
                            # taskId "20" <-> 20.json). "started" = first time it went in_progress,
                            # "ended" = last time it went completed.
    task_creates = {}       # tool_use_id -> {"content","activeForm","desc"} awaiting its assigned id
                            # (only known once its tool_result names "Task #N")
    task_order = []         # ids in creation order — transcript-reconstructed todo list, used only
                            # when the task store (~/.claude/tasks/<sid>/*.json) has been pruned
    task_defs = {}          # id -> {"content","activeForm","desc"}, resolved from task_creates
    task_status = {}        # id -> latest normalized status, from TaskUpdate ("last update wins")
    files = {}            # path -> {ops, last, created}
    reads = {}            # path -> last ts
    cmds = []             # bash commands, each {id, t, cmd, kind}
    commits = []          # {t, msg}
    requests = []         # user asks {t, text}
    agents = []           # {t, type, desc}
    errors_by_id = {}     # tool_use_id -> True
    bash_cmd_text = {}    # tool_use_id -> command text[:60], Bash calls seen so far -- the SAME
                           # id->text tracking _tail_scan keeps over its 96KB tail, kept here over
                           # the WHOLE file so the detail dict's `fail_cmd` (below) reflects the
                           # true latest real failure, not just what the cheap list-level tail saw
    fail_cmd = None        # detail dict's `fail_cmd` -- same field, same filter (_is_real_bash_error)
                           # as the list's, just over the full transcript instead of a 96KB tail
    prs = {}              # url -> {url, repo, num, created, state, t} : PRs touched this session
    pr_states = {}        # num -> "merged"/"closed" : state signals seen in logs (overlaid at the end)
    pr_create_ids = set() # tool_use_ids of `gh pr create` Bash calls (their result URL = created)
    asks = {}             # tool_use_id -> AskUserQuestion decision {t, open, answer, questions}
    narrative = []       # Claude's own text, in order: the blow-by-blow
    meta = {}
    text_last = ""
    tok_in = tok_out = 0
    ctx_current = None    # occupancy off the LATEST usage block only — not summed, unlike tok_in/out
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
            if u:  # a real usage block (not the {} default) -> this turn's occupancy; last one wins
                ctx_current = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                               + u.get("cache_creation_input_tokens", 0))
            if msg.get("model"):
                meta["model"] = msg["model"]
            if o.get("effort"):  # top-level sibling of "message", not nested in it; last value wins
                meta["effort"] = o["effort"]
            content = msg.get("content")
            # user prompts arrive as a plain string, OR — when the message carries an
            # image/paste/slash-command — as a LIST of blocks (text + maybe image).
            # Skill/command expansions are separate user messages tagged isMeta; tool
            # returns are tool_result blocks. Capture the real typed text from either
            # shape; let tool_result lists fall through to the block loop below.
            if msg.get("role") == "user":
                is_toolresult = isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                if not is_toolresult:
                    # isMeta tags injected system text — skill reloads, /context output,
                    # command re-invocations — in EITHER string or list shape; never a prompt.
                    if o.get("isMeta"):
                        s = ""
                    elif isinstance(content, str):
                        s = content.strip()
                    elif isinstance(content, list):
                        s = "\n".join(b.get("text", "") for b in content
                                      if isinstance(b, dict) and b.get("type") == "text").strip()
                    else:
                        s = ""
                    if s.startswith("<") and "<command-name>" in s:   # slash command -> the "/foo args" typed
                        s = _slash_prompt(s)
                    if s and not s.startswith("<") and not s.startswith("Caveat:") \
                            and not s.startswith("[Request interrupted"):
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
                    if rid in bash_cmd_text:                       # latest REAL Bash result wins, whole-file version
                        if b.get("is_error"):
                            if _is_real_bash_error(rtext):
                                fail_cmd = bash_cmd_text[rid]
                            # else: Claude Code's own guard refused it -- not a real failure, see
                            # _is_real_bash_error; leave fail_cmd as it was
                        else:
                            fail_cmd = None
                    if rid in asks:                                # the user's answer to an AskUserQuestion
                        asks[rid]["answer"] = re.sub(r"^Your questions have been answered:\s*", "", rtext).strip()[:2000]
                        asks[rid]["open"] = False
                    if rid in task_creates:                    # resolve the id TaskCreate's own input never carries
                        d = task_creates.pop(rid, None)
                        m = _TASK_CREATE_ID_RE.search(rtext)
                        if m and d and m.group(1) not in task_defs:
                            task_defs[m.group(1)] = d
                            task_order.append(m.group(1))
                    collect_prs(prs, rtext, ts, rid in pr_create_ids)
                    note_pr_states(pr_states, rtext)          # git-log "Merge pull request #N" etc.
                elif bt == "tool_use":
                    name = b.get("name")
                    inp = b.get("input") or {}
                    bid = b.get("id")
                    if name and "create_pull_request" in name:   # GitHub MCP: result URL is a created PR
                        pr_create_ids.add(bid)
                    if name and "merge_pull_request" in name:     # GitHub MCP merge → that PR is merged
                        pn = inp.get("pullNumber") or inp.get("pull_number")
                        if pn:
                            pr_states[str(pn)] = "merged"
                    if name == "TodoWrite":
                        todos = inp.get("todos", todos)
                    elif name == "TaskCreate":
                        # the assigned id isn't in this input at all — only in the tool_result
                        # ("Task #N created successfully"), resolved in the tool_result branch above
                        subj = inp.get("subject") or inp.get("content")
                        af = inp.get("activeForm")
                        desc = inp.get("description")
                        subj = subj[:2000] if isinstance(subj, str) else ""
                        if subj:  # a create with no usable subject can't be replayed as a todo
                            task_creates[bid] = {
                                "content": subj,
                                "activeForm": af[:2000] if isinstance(af, str) else "",
                                "desc": desc[:4000] if isinstance(desc, str) else "",
                            }
                    elif name == "TaskUpdate":
                        tid, st = str(inp.get("taskId") or ""), (inp.get("status") or "").lower()
                        norm = _TSTATUS.get(st)
                        if tid and norm:
                            task_status[tid] = norm            # last TaskUpdate wins — reconstructed-todo status
                        if tid and st in ("in_progress", "completed"):
                            tt = task_times.setdefault(tid, {"started": None, "ended": None})
                            if st == "in_progress" and tt["started"] is None:
                                tt["started"] = ts             # first activation only
                            elif st == "completed":
                                tt["ended"] = ts               # latest completion wins
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
                        if c:
                            bash_cmd_text[bid] = c[:60]  # for fail_cmd above, same [:60] as _tail_scan's
                        if PR_CREATE_RE.search(c):       # its result URL is a created PR
                            pr_create_ids.add(bid)
                        collect_prs(prs, c, ts)                    # a command's PR ref alone isn't "worked on"
                        note_pr_states(pr_states, c)               # `gh pr merge/close N`
                        if k == "commit":
                            m = COMMIT_MSG_RE.search(c)
                            commits.append({"t": ts, "msg": (m.group(2) if m else c)[:120]})
                    elif name in ("Grep", "Glob"):
                        n_search += 1
                    elif name == "Task":
                        agents.append({"t": ts, "type": inp.get("subagent_type") or "agent",
                                       "desc": (inp.get("description") or "")[:80],
                                       # this is a DISPATCH record (the Task tool_use itself),
                                       # with no linkage to whichever transcript file the
                                       # spawned subagent actually wrote (unlike agents_bg,
                                       # which parses that file directly) and no model key in
                                       # its own tool input (confirmed against real transcripts)
                                       # -- honestly "", never a guess.
                                       "model": ""})
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
    # Reconstructed from the TaskCreate/TaskUpdate calls just walked above — the fallback for
    # when the task store has been pruned (Claude Code deletes ~/.claude/tasks/<sid>/*.json
    # after ~2 days) or is only partially populated. `id` matches the store's own file-stem
    # convention exactly (TaskUpdate's own taskId == the ordinal in "Task #N created
    # successfully", which is the same ordinal the store stamps as <n>.json), so the
    # started_at/ended_at join a few lines down (keyed on todo["id"]) works unchanged
    # whichever source `todos` ends up from.
    recon = [{"content": task_defs[tid]["content"],
              "status": task_status.get(tid, "pending"),
              "activeForm": task_defs[tid]["activeForm"] or task_defs[tid]["content"],
              "desc": task_defs[tid]["desc"],
              "id": tid}
             for tid in task_order if tid in task_defs]
    if len(recon) > len(tasks):
        todos = recon
    elif tasks:
        todos = tasks
    # A malformed TodoWrite can set `todos` to a non-list (seen: the string "[]") or a
    # list with stray non-dict entries; keep only dict todos so one bad session can't
    # crash the parse (which closed the socket -> a 502 through a tunnel on every poll).
    todos = [t for t in todos if isinstance(t, dict)] if isinstance(todos, list) else []
    # Time-proportional progress-spine segments (per todo): started_at/ended_at, epoch seconds,
    # from the TaskUpdate transitions collected above -- joined by the task-store id load_tasks()
    # now stamps on each todo. Claude Code prunes ~/.claude/tasks/<sid>/*.json after roughly two
    # days, so load_tasks() returns nothing for most older sessions -- both the todo list and its
    # timings go empty then, even though the transcript still has the full TaskCreate/TaskUpdate
    # history; this code path keys off the task store, not the transcript. ended_at is only
    # trusted while the todo's OWN current status still says completed, so a task that was
    # reopened after an earlier completion can't show a stale "ended" time for work that isn't
    # actually done.
    for t in todos:
        tt = task_times.get(t.get("id") or "")
        t["started_at"] = _ts_epoch(tt["started"]) if tt and tt["started"] and t.get("status") in ("in_progress", "completed") else None
        t["ended_at"] = _ts_epoch(tt["ended"]) if tt and tt["ended"] and t.get("status") == "completed" else None
    done_todos = [t for t in todos if t.get("status") == "completed"]
    agents_bg, newest_agent, agent_files, agent_prs, agent_pr_states = parse_agents(path)
    # merge PRs a background agent generated into the session's prs (created stickies, agent-flagged),
    # so a PR opened by a subagent shows in the panel instead of vanishing with the subagent.
    for url, ae in agent_prs.items():
        e = prs.get(url)
        if not e:
            prs[url] = ae
            continue
        if ae["created"]:
            e["created"] = True
        if ae.get("narr"):
            e["narr"] = True
        e["agent"] = True
        if ae["t"] and (not e["t"] or ae["t"] > e["t"]):
            e["t"] = ae["t"]
    for n, stt in agent_pr_states.items():
        if pr_states.get(n) != "merged":   # a main-session "merged" wins; else take the agent's signal
            pr_states[n] = stt
    # merge background-agent file edits into the shared files shape so they show in
    # the Files panel (and the counts) — e.g. an agent editing inside a worktree.
    for fp, ae in agent_files.items():
        e = files.setdefault(fp, {"path": fp, "ops": 0, "created": ae["created"]})
        e["ops"] += ae["ops"]
        if ae.get("last") and (not e.get("last") or ae["last"] > e["last"]):
            e["last"] = ae["last"]
        if ae["created"]:
            e["created"] = True
        e["agent"] = True     # a background agent created/updated it — mark it even if the main session also touched it
    shells = parse_shells(path)
    meta["title"] = (load_titles().get(sid) or meta.get("customTitle") or meta.get("aiTitle")
                     or (_short_title(requests[0]["text"]) if requests else ""))
    st = os.stat(path)
    result = {
        "meta": meta,
        "todos": todos,
        # Claude's started_at/ended_at above come from an exact taskId join (task-store
        # file stem == TaskUpdate's own taskId) -- authoritative, unlike Auggie/Augment's
        # name-matched approximation. Always a bool, even with no todos at all, so the UI
        # never has to special-case a provider to know whether to show an "approximate" label.
        "todo_times_approximate": todo_times_approximate("claude"),
        "files": sorted(files.values(), key=lambda x: x.get("last") or "", reverse=True),
        "reads": [{"path": p, "t": t} for p, t in
                  sorted(reads.items(), key=lambda kv: kv[1] or "", reverse=True)],
        "commands": cmds[-60:][::-1],
        "commits": commits[::-1],
        "tests": tests[::-1],
        "requests": requests,
        "agents": agents[::-1],
        "agents_bg": agents_bg,
        "agent_sessions": child_agent_sessions(os.path.basename(path)[:-6], os.path.dirname(path)),  # agents this session originated — click to open
        "shells": shells,
        # open decisions first, then most-recent — so a pending question is at the top
        "decisions": sorted(asks.values(), key=lambda a: (a["open"], a["t"] or ""), reverse=True),
        # an unanswered AskUserQuestion: the session isn't idle, it's blocked on the user.
        # Same signal the sidebar's ⏳ uses, off the whole transcript instead of the tail.
        "waiting": any(a["open"] for a in asks.values()),
        # board "failing" tile signal (ext_cr_board.js's sessionState()), SAME field name as
        # the list dict (see list_sessions/registry.all_sessions) so board and detail derive
        # "failing" off one field -- off the WHOLE transcript here instead of just the tail,
        # same filter (_is_real_bash_error) as the list-level derivation. Honestly None when
        # nothing really failed, never omitted.
        "fail_cmd": fail_cmd,
        "prs": [p for p in prs_sorted(prs, pr_states) if pr_worked(p, meta.get("cwd"))],   # created or worked-on, not prompt-only references
        "narrative": narrative[::-1],   # full, newest-first; /api/session pages it, /api/narration serves the tail
        "message": text_last[:2000],
        "tokens": {"in": tok_in, "out": tok_out},
        # current context occupancy (this turn), not cumulative — Claude's JSONL usage
        # blocks never state a context-window size, so `limit`/`pct` stay honestly None.
        "context": context_window(ctx_current, None),
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
        "notes": load_notes().get(os.path.basename(path)[:-6], []),
        # Claude Code's hooks can drain /api/notes/next — at a turn end while it's live, at the
        # next prompt/resume once it's idle. Which one is the server's call, not the client's.
        "push_when": push_when(True, max(st.st_mtime, newest_agent), time.time()),
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

    def exists(self, sid):
        # cheap: just the file lookup, not a full parse
        return find_session(sid) is not None

    # drill-downs — same lookup as parse(), reached through registry.drill()
    def output(self, sid, cmd_id):
        path = find_session(sid)
        return command_output(path, cmd_id) if path else None

    def diff(self, sid, target):
        path = find_session(sid)
        return file_diffs(path, target) if path else None

    def shell(self, sid, shell_id):
        path = find_session(sid)
        return shell_output(path, shell_id) if path else None

    def agent(self, sid, aid):
        path = find_session(sid)
        return agent_detail(path, aid) if path else None
