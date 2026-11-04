# Idle TTL must not kill a session that is still running elsewhere

Branch `ttl-external-session` (worktree `.claude/worktrees/ttl-external-session`), cut from `personal/main` 9e1bdde.
Prior work: `docs/terminal-one-per-session-plan.md` (idle TTL `TERM_IDLE_TTL_MIN`, `_note_activity`, `_claude_busy`).

## Contract (verbatim, 2026-11-02)
"the ttl is killing the session even though the claude session is running in other terminal session in bash, that edge case is not covered, get a plan with opus and adversial review for the plan and do the correction and implement the fix /tracker-gap"
(Screenshot: session "compaction large-message limit", worktree `goalline-clamp`, Claude CLI, Opus 5.5, WORKING, 32m; Terminals 4 of 10.)

| Clause | Status |
|---|---|
| TTL no longer kills a session that is running in another terminal | not discharged |
| Plan written by opus | not discharged |
| Adversarial review of the plan (opus) + correction (reconciled plan) | not discharged |
| Implemented via /tracker-gap (tests + eval + live proof) | not discharged |
| Worktree → /branch-sync → push the branch to `personal` | not discharged |
| `/tracker-push` "if it has moved use /branch-sync" (verbatim): land on `personal/main`, syncing first if main moved | not discharged |

## Pipeline
opus plan (root cause investigation) → opus adversarial review (review + design-fix + clean plan) → main-thread reconciliation (verdict table below) → sonnet implement → opus review → gate (haiku) → /branch-sync → push the branch.

## Original plan (opus planner, 2026-11-02)
### Root cause (evidence, read-only)
- Session 90202b74 (goalline-clamp) is **daemon-hosted**.
  - `~/.claude/jobs/90202b74/state.json` reads `backend: "daemon"`, `state: working`.
  - `~/.claude/daemon/roster.json` has worker 90202b74: pid 25160 (`claude bg-pty-host`), replPid 25195 (cwd goalline-clamp), under daemon 17162. Tool shells are children of 25195 in their own pgid.
  - The REPL never died (attempt 1, daemon up since 12:36Z).
- The tracker (pid 81919, :8790) folder pty `71999fd34e82` (cwd goalline-clamp, fg `{session: 90202b74, mode: resume}`) runs `claude --resume 90202b74`.
  - That is pid 72715, a **thin attach client**: attach-journal `{surface: "fleet", pid: 72715}`. Its only child is a zombie.
  - A second client attached from another terminal: attach-journal `{surface: "bg_cli", pid: 78949, 17:59:18Z}`.
- The live TTL is 10 min (overridden).
- The reaper judges only the pty:
  - `_claude_busy` checks children of the client 72715, finds none, and returns False.
  - `_note_activity` sees only the client's screen.
  - So when the client's screen is static (another terminal is driving, the picker is up, the client is displaced), the pty is reaped even though the transcript is live.
  - The user perceives "TTL killed the session".
- Scenarios:
  - (a) confirmed (generalised to daemon thin clients).
  - (b) a hand-typed claude is the same gap.
  - (c) refuted for in-pty REPLs; applies to daemon REPLs on long silent tools.
  - (d) refuted (kill signals stay in the client's/shell's groups).
- Could not verify: why the client's screen goes static; whether an earlier pty existed before 17:54Z.
- Latent risk (unverified, out of scope): daemon 17162 is a child of 12668, the REPL in tracker pty ttys004. It is protected today only because `_claude_work_children(12668)` counts the daemon as work. Whether a `--origin transient` daemon exits with its spawner is unknown.

### Plan
Invariant: an idle, viewer-less pty whose fg is Claude is not reaped while its session is live. Live means the transcript or agent files were written within `config.LIVE_WINDOW`, or its daemon REPL has tool work. Checked only at reap time.

Leg 1 — provider/registry seam:
- `providers/base.py` `Provider`: `last_active(sid) -> 0.0`, `host_pid(sid) -> 0` (defaults; Auggie inherits them).
- `providers/claude.py`:
  - `_daemon_repl_pid(sid)` after `_live_daemon_shorts` (~570): roster pids + sessionId only; supervisor alive; worker `sessionId == sid` and alive ⇒ `replPid` if alive, else 0; any exception ⇒ 0.
  - `ClaudeProvider.last_active` = `_active_mtime(find_session(sid))` or 0.0.
  - `ClaudeProvider.host_pid` = `_daemon_repl_pid`.
- `registry.py` (after `provider_for` ~143): `session_last_active(sid)`, `session_host_pid(sid)`; never raise.

Leg 2 — `term_vt.py`:
- `_pty_session_ids(pt)` (under `_LOCK`, pure), mirroring `_session_ptys` (3260):
  - folder fg ⇒ `(fg.session,)` unless empty or forked.
  - folder with no fg ⇒ `(spawned,)`.
  - dedicated forked ⇒ `()`.
  - dedicated otherwise ⇒ dedupe `(spawned, session if mode == resume)`.
  - never `pt.session` for a folder pty.
- `_session_live(pt)`, never raises:
  - fd/screen guard.
  - `_LOCK.acquire(timeout=1.0)` (contended ⇒ True), then `_refresh_fg` for folders and read the ids.
  - no ids ⇒ False.
  - lazy registry import.
  - any session within `LIVE_WINDOW` ⇒ `_foreground_is_claude(fd)`.
  - else host pids > 0 and fg is claude and any `_claude_work_children(host)`.
- `_reader` (1724): `if _claude_busy(pt) or _session_live(pt): pt.touch()`.
- README:98 gains one clause.

Tests (red first):
- U1–U7 in `TestIdleTimeout`: live session kept; stale reaped; forked reaped; fg not claude reaped; daemon tool work kept / none reaped; no session ⇒ registry not called; `_pty_session_ids` table.
- New `tests/test_session_liveness.py`:
  - P1: `last_active` takes the newer of the main file and the agent file.
  - P2: unknown or unsafe id ⇒ 0.
  - P3: `host_pid` matrix.
  - P4: registry wrappers for auggie and for a raising provider.
- Selfcheck asserts.
- Integration `TestTermIdleTtlEndToEnd.test_live_session_terminal_survives_ttl_until_quiet` (real server; the tty survives while the transcript is fresh, then is reaped once backdated).
- Live proof: a harness on a spare port with `/bin/cat` copied as `claude`; never restart :8790.

Risk: `_LOCK` taken from the reader thread. Re-grep that no `with _LOCK:` block sleeps or joins; `acquire(timeout=1.0)` bounds it. Fallback: an unlocked snapshot without `_refresh_fg`.

Decisions flagged:
1. Keep-alive scope: keep while the session is live anywhere (a stale real second REPL could linger).
2. Include daemon tool work (a long background loop pins the pty).
3. Window = `LIVE_WINDOW` 300s, not max(LIVE_WINDOW, TTL).

## Review (opus reviewer, 2026-11-03) — VERDICT: UNPROVEN
- F1 HIGH: mechanism unproven.
  - 72715 is not in the attach-journal (entries have no session id); nothing ties 78949 to 90202b74.
  - The planner's own pty 71999fd34e82 was never reaped (client CPU kept rising ⇒ still rendering).
  - No reap is recorded anywhere.
  - Real timeline: 17:34 commit gate starts → 17:41:05 "[Request interrupted by user for tool use]" → transcript silent → 17:54:13 new folder pty → 17:54:34 "continue please". So at any matching reap time the session was IDLE.
  - Fix: experiments E1–E3 before code.
- F2 HIGH: the window is wrong. Live config LIVE_WINDOW=900, TTL=10 (verified). With the default 300 the plan still reaps the incident. The user says "running", not "recently active". PRODUCT DECISION: (A) active within window / (B) host alive / (C) let thin clients reap + seamless re-attach. If (A): `max(LIVE_WINDOW, TTL)`.
- F3 HIGH-if-confirmed: the 17:41 abort may be reap-caused, if the daemon cancels a turn when a thin client is SIGKILLed. E2 decides.
- F4 MED: the daemon tool-work leg is needed. Bash tools are silent in the transcript for 383/414/389s (>300). Every tracker-typed claude here is a daemon thin client ⇒ `_claude_busy` is always False for tracker terminals.
- F5 LOW overengineered: `_LOCK`/`_refresh_fg` from the reader isn't needed; an unlocked snapshot is enough (`_foreground_is_claude` rejects a stale fg).
- F6 LOW overengineered: a Provider `host_pid` with no other implementers ⇒ module functions in providers/claude.py via the existing term_vt:2051 import idiom; refactor `_live_daemon_shorts` → `_live_workers()`.
- F7 LOW: folder fg with session "" should fall back to `pt.spawned`.
- F8 MED (tests): U2–U6 aren't red-first (prove them by mutation); the integration test must mock `_foreground_is_claude`, use temp PROJECTS/ROSTER, and wait >1 TTL after backdating. The live proof must use a real daemon thin client, not `/bin/cat`.
- F9: the transient daemon is not at risk (setsid'd; exits on last client). Known gap: a setsid'd daemon child counts as work.
- F10: holds — `_foreground_is_claude` works for the thin client.

Clean plan (reviewer):
- E1–E3 experiments → D1.
- `_live_workers`, `daemon_repl_pid`, `session_last_active` in providers/claude.py.
- `_pty_session_ids` (unlocked) and `_session_live` (window `max(LIVE_WINDOW, TTL)`; ids → stat → roster → ps) in term_vt.
- Reader: `_claude_busy or _session_live`.
- Tests: U1, U5a, U8 RED + mutation-checked guards + U7 table; test_session_liveness; the integration test; selfcheck; a live proof with a real daemon client.

## Reconciliation (main thread, verified against code/config)
| Finding | Verdict | Action |
|---|---|---|
| F1 mechanism unproven | **Confirmed** (the planner itself listed it as unverifiable; reviewer evidence holds) | Run experiments before coding |
| F2 window/meaning | **Confirmed** (live LIVE_WINDOW=900, TTL=10 verified via /api/config) | User decision D1/D2 |
| F3 reap may abort the in-flight turn | **Overstated until E2** (`Pty.kill` sends only SIGKILL to the client's group; abort-on-detach is unproven) | E2 decides; if true, keeping alive during tool work is mandatory |
| F4 daemon leg needed / `_claude_busy` blind for daemon clients | **Confirmed** (the B-F4 keep-alive shipped last time never fires for daemon thin clients) | Keep the daemon leg |
| F5 lock | **Confirmed overengineered** | Unlocked snapshot |
| F6 Provider pair | **Confirmed overengineered** (terminals are Claude-only; the 2051 precedent exists) | Module functions; no base-class change |
| F7 fg session "" | **Confirmed** | Fall back to `spawned` |
| F8 test design | **Confirmed** | Mutation-checked guards; realistic integration test |
| F9 transient daemon | **False alarm** for this change | Document the known gap |
| F10 | Holds | — |
| **Missed by both** | `providers/claude.py:2` imports `LIVE_WINDOW` at load (ignores the live override); `web/app.js:986` hard-codes `LIVE=300` while the server has 900 (conventions rule 5). Pre-existing. | Out of scope unless the user wants it folded in (one-PR rule) |

## User decisions (2026-11-03)
- D1: **(A) active within a window**: transcript written within `max(LIVE_WINDOW, TTL)`, or the daemon REPL has tool work.
- Experiments: **run E1–E3 before coding**.
- D3: long-lived background shells under a daemon REPL **do** keep the pane open (same as the in-pty B-F4 decision).
- LIVE drift: **fold in**. The provider reads `config.LIVE_WINDOW` at call time; the SPA reads LIVE from the server instead of hard-coding 300.

## Experiments (E1–E3), sonnet, claude 2.1.317, harness with real term_vt, TTL 1 min, no viewer
- Artifacts: scratchpad/exp/ (harness.py, harness.log, dumps).
- **Plain `claude` / `claude --resume` in a pty is STANDALONE** (no roster entry; its only child is `caffeinate` in its own pgid). Only `claude --bg` + `claude attach` produces a daemon thin client. The old roster entries were stale; the "shared daemon" wasn't actually running until `--bg` started a transient one.
- E1 idle:
  - A standalone claude at its prompt goes static within ~1s and is reaped at ~62s.
  - The transcript is intact and `--resume` works.
  - Daemon thin clients (T, U) are also static when idle and reaped at ~62s; the REPL survives (harmless).
- E2 kill mid-tool:
  - Standalone: the spinner/timer row keeps the body changing, so the TTL never fires mid-tool (and `_claude_busy`=True via the setsid'd tool). A SIGKILL of the client orphans the tool process and leaves a dangling `tool_use` (no result, no interrupt marker).
  - Daemon thin client: SIGKILL mid-tool does NOT abort; the tool finished, its `tool_result` was recorded, and the assistant continued. `_claude_busy` is always False for thin clients (tools live under the REPL).
- E3: a second client attached to the same session does not freeze the first; both render independently and both are reaped only after the session goes idle.
- Implications:
  - Reaping is harmful only for STANDALONE in-pty Claudes; it is harmless for daemon thin clients.
  - The harmful case is: an idle standalone Claude in a tracker pty, no viewer, reaped while the SAME session is still live elsewhere (another terminal/client writing the transcript). D1(A) covers this.
  - The daemon tool-work leg only protects a harmless view; keep or drop it per the revised plan.
  - Not tested: an unanswered permission/dialog prompt (static screen while waiting on the user).

## REVISED PLAN (opus planner, at cb71c66) — the implementation spec
Line numbers re-read at cb71c66. Moved since 9e1bdde: providers/claude.py and test_selfcheck.py. registry.py is untouched by this plan.

### Decisions folded in
- **Daemon tool-work leg kept** (~20 lines), only for D3: a session idle at its prompt whose daemon REPL still owns a background shell is quiet on screen and in the transcript; only this leg keeps that pane open. The first thing to delete if D3 is ever dropped.
- **Unanswered permission dialog:** no code. The `tool_use` write holds the pane for about one window; after that it counts as idle (known behaviour).
- **HOLD, not touch:** a kept pane re-checks every `SESSION_LIVE_RECHECK = 30`s and never moves `last_active`. An idle pane closes at `max(T_lastactive + TTL, T_lastwrite + window) + ≤30s`. Touching instead would double the idle time to ~2×TTL. Fallback: `touch()`, telling the user about the 2×TTL behaviour.

### Leg A — LIVE drift (first, independent)
A1. Every server consumer reads `config.LIVE_WINDOW` at call time.
- providers/claude.py:
  - line 2 → `from ..config import EDIT_TOOLS, NARRATION_CAP` (`from .. import config` is already on line 3)
  - bare `LIVE_WINDOW` → `config.LIVE_WINDOW` at 545, 663, 705, 934 (`_mtime_bg_n`), 1233, 1478; comments at 317/659 stay
- providers/auggie.py: line 2 → `from ..config import NARRATION_CAP`; line 363 → `config.LIVE_WINDOW`
- util.py: line 4 → `from . import config`; line 395 → `return "turn" if (now - mtime) < config.LIVE_WINDOW else "wake"`
- overview.py: line 3 → `from . import config`; line 34 → `idle < config.LIVE_WINDOW`
- server.py:6: drop `LIVE_WINDOW` from the import (415/607/888 are comments; re-grep)
- providers/augment_ext.py:191 is already correct
- config.py:172-178 comment → "Every consumer reads `config.LIVE_WINDOW` at call time, so a browser change applies on the next request; the SPA's `LIVE` is substituted into the page by `page.build_page()` on every page load."
- Bundle: scripts/bundle.py rewrites `config.X` → `X`, so this is safe.

A2. The SPA's `LIVE` is served by the server (server.py:370 calls `build_page()` on every GET /).
- web/app.js:986 → `const LIVE=300/*__LIVE_WINDOW__*/; // seconds a session stays "live"; page.py serves config.LIVE_WINDOW here on every page load (300 = default, and the bundle's value)`
- page.py:
  - add `from . import config` and `LIVE_MARK = "300/*__LIVE_WINDOW__*/"`
  - in `build_page()` (7-17): `js = (read("app.js") + read_ext(".js")).replace(LIVE_MARK, str(int(config.LIVE_WINDOW)))`, then substitute `js` for `__JS__`
  - The bundle's `inlined_page()` (scripts/bundle.py:53) leaves the marker, which is valid JS and evaluates to 300.
- ext_cr_board.js:14-23 and ext_cr_detail.js:76-85: comment only ("`const LIVE = 300`" → "server-served `LIVE` (page.py)").
- ext_cr_dialogs.js:1325 help text: append " Applies to the server at once; open pages pick it up on reload."

### Leg B — providers/claude.py module functions (base.py/registry.py untouched)
B1. Replace `_live_daemon_shorts` (578-593):
```python
def _live_workers():
    """short -> worker dict for workers alive under a live supervisor. Roster holds secrets: only
    pid/sessionId/replPid are read, nothing logged. {} on any missing/unparseable/wrong shape."""
    try:
        with open(config.DAEMON_ROSTER) as fh: ro = json.load(fh)
        if not isinstance(ro, dict) or not isinstance(ro.get("workers"), dict): return {}
        if not _pid_alive(ro.get("supervisorPid")): return {}
        return {k: w for k, w in ro["workers"].items()
                if isinstance(k, str) and isinstance(w, dict) and _pid_alive(w.get("pid"))}
    except Exception:
        return {}

def _live_daemon_shorts():
    """(unchanged docstring)"""
    return set(_live_workers())
```
B2. Add after it:
```python
def daemon_repl_pid(sid):
    """pid of the live Claude-daemon REPL hosting session `sid` (its tools are its children), or 0."""
    for w in _live_workers().values():
        if w.get("sessionId") == sid:
            rp = w.get("replPid")
            return rp if _pid_alive(rp) else 0
    return 0
```
B3. Add after `_active_mtime` (904-917):
```python
def session_last_active(sid):
    """Newest write across the session's transcript and its agent files (= the list's mtime), or 0.0."""
    try:
        path = find_session(sid)
        return _active_mtime(path) if path else 0.0
    except Exception:
        return 0.0
```

### Leg C — term_vt.py
C1. After line 1258: `SESSION_LIVE_RECHECK = 30.0   # s between re-probes while an idle pty is HELD by _session_live (no touch: the idle clock keeps running)`

C2. In `Pty.__init__` after `self._act_t` (1508): `self.live_hold = 0.0   # reader-only: the idle reap re-checks _session_live no sooner than this`

C3. Insert between `_claude_busy` (3689-3701) and `_foreground_is_claude` (3704):
```python
def _pty_session_ids(pt):
    """Session id(s) this pty runs, for the idle reap. UNLOCKED snapshot (F5): plain attribute
    reads, no _LOCK, no _refresh_fg; a stale label is rejected by the _foreground_is_claude gate.
    Mirrors _session_ptys (3260): a forked copy runs under an id we never learn -> ()."""
    fg, spawned = pt.fg, pt.spawned
    if pt.folder:
        if fg is not None:
            if fg.get("forked"):
                return ()
            s = fg.get("session") or spawned            # F7: a `new` job not resolved yet
            return (s,) if s else ()
        return (spawned,) if spawned else ()            # a `claude` typed by hand
    if pt.forked:
        return ()
    return tuple(dict.fromkeys(s for s in (spawned, pt.session if pt.mode == "resume" else "") if s))


def _session_live(pt, now):
    """D1/D3: the idle pty's foreground Claude runs a session whose transcript (or agent files) was
    written within max(LIVE_WINDOW, TTL), or whose Claude-daemon REPL still has tool work. Order:
    ids (free) -> stat -> roster -> ps. Never raises (a raise would kill the reader thread)."""
    try:
        if pt.fd < 0 or pt.screen is None:
            return False
        sids = _pty_session_ids(pt)
        if not sids:
            return False                                 # plain shells: no fs, no ps
        try:
            _claude = __import__("%s.providers.claude" % __package__, fromlist=["claude"])  # idiom: line 2051
        except Exception:
            return False
        window = max(config.LIVE_WINDOW, config.TERM_IDLE_TTL_MIN * 60)
        if any(now - _claude.session_last_active(s) < window for s in sids):
            return _foreground_is_claude(pt.fd)
        hosts = [h for h in (_claude.daemon_repl_pid(s) for s in sids) if h > 0]
        return bool(hosts) and _foreground_is_claude(pt.fd) and any(_claude_work_children(h) for h in hosts)
    except Exception:
        return False
```

C4. In `_reader`, replace the reap block (1723-1728) and update the `_reader`/`_claude_busy` docstrings:
```python
            now = time.time()
            if (pt.viewers <= 0 and now - pt.last_active > config.TERM_IDLE_TTL_MIN * 60
                    and now >= pt.live_hold):
                if _claude_busy(pt):
                    pt.touch()       # in-pty tool work counts as activity; re-probed one TTL later
                elif _session_live(pt, now):
                    pt.live_hold = now + SESSION_LIVE_RECHECK   # HOLD, not touch: reaped once the session goes quiet
                else:
                    pt.kill()
                    break
```

### Tests
**TestIdleTimeout fixture** (tests/test_term_vt.py:1970; `_drain` 698, `_wait_for` 706):
- save/restore `config.TERM_IDLE_TTL_MIN`, `LIVE_WINDOW`, `PROJECTS`, `DAEMON_ROSTER` and `term_vt.SESSION_LIVE_RECHECK`
- temp `PROJECTS` with `proj/<SID>.jsonl`; `DAEMON_ROSTER` = a missing temp path; `SESSION_LIVE_RECHECK=0.2`
- child `["sleep","30"]`, `pt.mode="resume"`, `pt.session=SID`
- patch `_foreground_is_claude=True` unless stated
- cleanup `pt.kill(); _drain(pt,5)`

| ID | Name | Setup | Assertion | Proof |
|---|---|---|---|---|
| U1 | `test_live_elsewhere_session_holds_off_reap` | TTL 0.001; a writer `os.utime`s the transcript every 0.3s; real provider lookup | not done after 2.5s | RED (main reaps at ~0.06s) |
| U2 | `test_quiet_session_is_reaped` | mtime = now − window − 5 | done within 5s | mutation: flip `<` / drop the window check |
| U3 | `test_forked_copy_ignores_parent_liveness` | U1 writer, (a) `pt.forked=True`; (b) folder pty with `fg={session:SID, mode:resume, started:now, forked:True}` | both reaped | mutation: delete the forked branches |
| U4 | `test_live_session_bare_shell_is_reaped` | U1 writer, fg=False | reaped | mutation: drop the fg gate |
| U5a | `test_daemon_repl_tool_work_holds_off_reap` | stale transcript; roster `{"supervisorPid": os.getpid(), "workers": {"x": {"pid": os.getpid(), "sessionId": SID, "replPid": os.getpid()}}}`; `_claude_work_children=lambda p: [1] if p == os.getpid() else []` | not done after 2.5s | RED |
| U5b | `test_daemon_repl_idle_is_reaped` | same, work children `[]` | reaped | mutation: drop the work condition |
| U6 | `test_sessionless_pty_never_probes` | `session=""`; patch `aitracker.providers.claude.session_last_active`/`daemon_repl_pid` (create=True) | reaped; both `assert_not_called` | mutation: probe before the ids check |
| U7 | `test_pty_session_ids_table` | bare `Pty()` objects | folder fg resume→(S,); fg ""+spawned X→(X,); fg forked→(); fg None+spawned→(X,); dedicated resume→(S,); dedicated new+spawned→(X,); dedicated forked→(); cwd nothing→() | RED (missing) |
| U8a | `test_window_uses_live_window` | LIVE_WINDOW=5, TTL 0.001, one write at t0 | not done at t0+3; done by t0+9 | RED |
| U8b | `test_window_uses_ttl_when_larger` | LIVE_WINDOW=1, TTL 0.1 (6s), write at t0+4 | not done at t0+7; done by t0+14 | mutation: LIVE_WINDOW-only window |
| U9 | `test_hold_does_not_touch_idle_clock` | U1 setup | `last_active` unchanged after 1.5s | mutation: touch instead of hold |

Each mutation is applied locally, the test watched fail, the mutation reverted, and the result logged in Progress.

**New tests/test_session_liveness.py** (temp PROJECTS/ROSTER, saved and restored):

| ID | What it checks | Proof |
|---|---|---|
| P1 | `session_last_active` returns the newer of the main file and `<sid>/subagents/agent-a.jsonl` | RED |
| P2 | unknown id, `"*"`, `"../x"` ⇒ 0.0 | — |
| P3 | `daemon_repl_pid` ⇒ `os.getpid()` for a matching live worker; 0 for a dead supervisor (999999), a dead replPid, a wrong sessionId, a missing roster, malformed JSON, a str replPid | RED |
| L1 | `_mtime_bg_n` on a 60s-old agent file: bg=1 at LIVE_WINDOW 300, bg=0 at 10 | RED |
| L2 | `util.push_when(True, now-60, now)` ⇒ "wake" at LIVE_WINDOW 10 | RED |
| L3 | source guard: regex `from \.+config import[^\n]*\bLIVE_WINDOW\b` matches nothing in util.py, overview.py, providers/claude.py, providers/auggie.py, server.py | RED |
| L4 | app.js contains LIVE_MARK exactly once; with LIVE_WINDOW=777, `build_page()` has `const LIVE=777` and no `__LIVE_WINDOW__` | RED |

The existing tests/test_jobs_waiting.py:122-152 (`_live_daemon_shorts`) must stay green.

**Selfcheck** (tests/test_selfcheck.py after 909):
- `_p=term_vt.Pty(); _p.mode="resume"; _p.session="S"` ⇒ `_pty_session_ids(_p)==("S",)`
- `_p.fd=0; _p.screen=object()`, patch `aitracker.providers.claude.session_last_active`(create=True)=`time.time()` and `_foreground_is_claude`=True ⇒ `_session_live(_p, time.time())`
- then `_p.forked=True` ⇒ False
- RED before the change.

**Integration** (test_integration.py::TestTermIdleTtlEndToEnd 1408; add LIVE_WINDOW/PROJECTS/DAEMON_ROSTER to `_saved`):
- I1 `test_live_session_terminal_survives_ttl_until_quiet`:
  - Setup: real server; temp PROJECTS transcript; missing roster; `sleep 60` with session=SID mode=resume in PTYS under `_LOCK`; patch only `_foreground_is_claude`=True; `SESSION_LIVE_RECHECK=0.3`; TTL 0.02 (1.2s).
  - A writer touches the transcript every 0.5s for 4s; assert the tty is still listed at 4s.
  - Backdate the transcript to now − (max(LIVE_WINDOW, 1.2) + 5), wait >1 TTL, then poll ≤8s until the tty is gone.
  - Teardown: kill and pop. RED.
- I2 `test_page_live_follows_live_window_override`: POST /api/config `{"key":"LIVE_WINDOW","value":120}`, then GET / ⇒ regex `const\s+LIVE\s*=\s*(\d+)` captures 120. RED.
- The existing `test_live_constant_matches_server` (1661) and `TestBundle` must stay green.

### Live proof (/tracker-gap)
Spare port 8799 (check it is free); never touch 8790/8787; stop by PID; harness in the implementer's own scratch dir.
1. Harness:
   - worktree on `sys.path`; strip `CLAUDE_CODE*`, `CLAUDECODE`, `CLAUDE_PID`, `TRACKER_TERM_APP` from env
   - `config.TERM_IDLE_TTL_MIN=1`, `config.LIVE_WINDOW=60`
   - `server.Server(("127.0.0.1",8799), server.Handler)` in a thread; no mocks
2. Scratch session: one `claude -p --model haiku --session-id <uuid> "ok"` in a trusted scratch dir.
3. Pane: `term_vt.spawn(dir, ["claude","--resume",SID], 120, 40)`, `mode="resume"`, `session=SID`, in PTYS, no viewer.
4. A writer `os.utime`s SID.jsonl every 20s for 3 min; curl `/api/term/list` every 10s.
   - Pass: the tty is listed between 62s and 180s.
   - Baseline on main: reaped at ~62s (E1).
5. Stop the writer.
   - Pass: the tty is gone ~60–95s later, the REPL pid is gone, the transcript is intact.
6. Optional D3 check: `--bg` + `attach` + a `run_in_background sleep 200`.

### Risks
- The reader loop: `_session_live` swallows every exception; fallback is `touch()` (2×TTL, tell the user).
- Call-time `LIVE_WINDOW`: grep tests for assignments and make sure each is restored.
- Unlocked snapshot: a stale fg is possible; the fg gate blocks bare shells. Known gap: a different hand-typed claude after the labelled one exits can be held by the old session.

### Known gaps to document
- F9 (a setsid'd child counts as work).
- An OpenRouter-launcher pane whose comm isn't `claude` fails the fg gate (as before).
- The bundle serves LIVE=300 and has no terminal tier.
- A pending permission dialog counts as idle after one window.

### Doc text
- README.md:98, after "an open viewer keeps it alive;": "a Claude whose tool/background shells are still running is kept open until they exit; so is a Claude whose session is still live elsewhere — its transcript written within `max(LIVE_WINDOW, TTL)` (e.g. driven from another terminal), or its Claude-daemon REPL still running tools — re-checked every 30s; only an idle Claude is closed."
- CLAUDE.md:34 → "**Liveness:** one constant — `LIVE_WINDOW` (config, default 300s, live-editable; every server consumer reads `config.LIVE_WINDOW` at call time). The SPA's `LIVE` is served by the server — `page.build_page()` substitutes it into `web/app.js` on every page load — never a second literal."
- .claude/rules/conventions.md:12, last sentence → "Liveness is one constant: `LIVE_WINDOW` (server, default 300s, read at call time); the client's `LIVE` is served by the server (page.py), never hard-coded."

### Sequencing
1. A + L-tests + I2
2. B + P-tests
3. C + U1–U9 + selfcheck + I1
4. docs
5. live proof
6. `make check` (`selfcheck ok`) + `node --check` web/*.js
7. commit → /branch-sync → push the branch (+ /tracker-push, per the user)

## Implementation review (opus, 2026-11-04) — VERDICT: HOLDS for the core
| Finding | Verdict | Action |
|---|---|---|
| F1 own writes count, so a Claude pane never closes sooner than `LIVE_WINDOW` after its last write | **Product decision, resolved** | Keep as built, document accurately (user: "if any session that is live and is going to kill the session then hold the session for the user") |
| F2 folder fg `session ""` falls back to a stale `spawned` | **Clear bug** | Use only `fg["session"]`; fix the docstring; U7 row expects `()` |
| F3 known gaps not documented | **Confirmed** | `_session_live` docstring + README clause |
| F4 30s rate limit unproven | **Confirmed test gap** | Add U10 |
| F5 U9 flake | **Confirmed** | Wait for `_act_v` before reading `before` |
| F6 L3 guard too narrow | **Confirmed, cheap** | Glob `aitracker/**/*.py` |

## New capability (user, 2026-11-04, verbatim)
"if any session is running in the background let them fly in, utilising any other open session in the folder, if any session that is live and is going to kill the session then hold the session for the user."
Clarified by the user as "Reuse another terminal in the folder": when a background or live session needs a terminal, attach it into an already-open terminal in that folder instead of opening a new one. Status: not discharged; opus plan in progress.

## Progress
- [x] Worktree from personal/main 9e1bdde
- [x] Leg A (LIVE drift): config.LIVE_WINDOW read at call time in claude/auggie/util/overview/server; page.LIVE_MARK substituted in build_page; app.js marker. L1-L4, I2 RED on pre-change code (L1 1!=0, L2 turn!=wake, L3 regex hit util.py, L4 no LIVE_MARK, I2 300!=120), green after.
- [x] Leg B: _live_workers/daemon_repl_pid/session_last_active in providers/claude.py (P1-P3 RED: AttributeError, green after); test_jobs_waiting still green.
- [x] Leg C: SESSION_LIVE_RECHECK, Pty.live_hold, _pty_session_ids, _session_live, _reader reap block. RED on pre-change: U1, U5a, U7, U8a, U8b, U9, I1 (term_vt hook disabled) all failed for the stated reason.
- Mutation proofs (mutation applied by scoped Edit, test failed, reverted):
  - U2: window check replaced by always-true -> FAIL
  - U3a/U3b: both forked branches deleted -> both FAIL
  - U4: fg gate dropped in the window branch -> FAIL
  - U5b: work-children condition dropped -> FAIL
  - U6: session_last_active probed before the ids check -> FAIL
  - U8b: window = LIVE_WINDOW only -> FAIL
  - U9: touch() instead of hold -> FAIL
  - selfcheck: _session_live window branch returns False -> AssertionError
- [x] Docs: README:98, CLAUDE.md liveness line, conventions rule 5.
- [x] node --check on every aitracker/web/*.js: 0 bad.
- [x] Live proof (harness /Users/pritammondal/.claude/jobs/3513f2df/tmp/live_ttl/harness.py, :8799, real server+term_vt, real claude --resume haiku scratch session, TTL 1 min, LIVE_WINDOW 60, writer utime every 20s for 180s): tty listed at all 25 polls from 0 to 240s; writer stopped at 180.2s; pane gone at 250.3s = 70.1s after stop (expected 60-95s); claude pid dead; transcript intact (486646 bytes unchanged). PASS. Baseline on main (E1): reaped at ~62s. Step 6 (D3 --bg) skipped. All harness processes stopped; :8799 free.
- [x] Review F2: `_pty_session_ids` folder+fg branch uses only fg["session"] (no `spawned` fallback); docstring corrected (stale-label guard is partial; differs from `_session_ptys` for fg None). U7 row flipped to `()`: RED before fix, green after.
- [x] Review F1+F3 (docs only): README idle-terminal bullet, 'Idle terminal TTL' help text (ext_cr_dialogs.js, serverRow line untouched, node --check ok) and `_session_live` "Known gaps" docstring state a Claude pane never closes sooner than LIVE_WINDOW after its last write (own-pane writes hold too; user decision: keep).
- [x] Review F4: U10 `test_session_live_probe_is_rate_limited` added; mutation (drop `and now >= pt.live_hold`) gave call_count 3 != 1 (RED); restored, green.
- [x] Review F5: U9 waits for `pt._act_v is not None` before reading last_active.
- [x] Review F6: test_session_liveness L3 globs aitracker/**/*.py excluding config.py; green.
- [x] Re-run alone: TestIdleSessionLive x3 (13 tests, OK), test_session_liveness (7 OK), test_term_vt_client (265 OK), test_integration (110 OK), selfcheck ok.
