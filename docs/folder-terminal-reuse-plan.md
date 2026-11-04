# Let a session reuse an open terminal in its folder

Branch `ttl-external-session` (same worktree as the idle-TTL fix; a separate commit). Status: plan under adversarial review; NOT implemented.

## Contract (verbatim, 2026-11-04)
- "if any session is running in the background let them fly in, utilising any other open session in the folder"
- Clarified by the user as: "Reuse another terminal in the folder" (when a background or live session needs a terminal, attach it into an already-open terminal in that folder instead of opening a new one).
- "for the last piece of response in my answer which introduces a new behavior, plan that out in a separate opus agent, do an adversial review for the same"

| Clause | Status |
|---|---|
| Separate opus plan | discharged (below) |
| Adversarial review of the plan (opus) | not discharged |
| Reconciled plan + user agreement | not discharged |
| Implementation | not discharged |

## Original plan (opus planner, 2026-11-04)
### Summary
Most of this already works. Three things are really new:
1. Switching an unwatched terminal from one background session's view to another (the only change that alters the common case).
2. Reusing idle spare shells (rarer).
3. Guards missing today: half-typed input, a shell that has `cd`'d away, a second REPL on a session running outside the tracker.

Cannot be done safely: a terminal running a plain standalone Claude cannot host another session (it would kill a live REPL), so a new terminal still opens. Two of the three terminals on :8790 at plan time were this kind.

### Findings that change the brief
- F1: `claude --resume <bg session>` turns itself into a thin client (CLI 2.1.318). Live: tty d086c3, zsh 88289, child 88524 runs `.local/bin/claude attach 3513f2df`, while the tracker row still says `cmd: claude --resume 3513…`, `fg.mode: resume`. Binary: `YPo` logs `resume_live_background_open`, runs `{args:["attach",e], …}`. Inferred, E5 confirms. Consequence: the `fg` label and `pt.cmd` cannot tell a pane is a thin client; only `ps -o args=` on the fg group can.
- F2: the CLI does not stop a second REPL on an INTERACTIVE session: holder check `hxe(e).find(i => i.kind !== "interactive")` (`E9`), so only background holders count. E6 confirms. Data: `~/.claude/sessions/<pid>.json` has `pid, sessionId, cwd, kind (bg|interactive), procStart, jobId, status`; the tracker never reads it.
- F3: a third refusal wording, `mxe`: `${title} is running in the background (${jobId}).…`, is not in `term_gate.BG_REFUSAL_MARKERS` (term_gate.py:113), so no recovery fires if the handoff fails.
- F4: half-typed input has no guard. `_fg_pgid == pid` and `_wait_for_quiescence` don't see it: `ls ` at the prompt plus a typed resume runs `ls claude --resume S`. Existing bug on the primary shell; reuse would widen it.
- F5: a shell that has `cd`'d is not checked. `p.cwd` is the spawn directory. `lsof -a -d cwd -p PID -Fn` took 34ms.

### Case table
| # | Situation | Today | After | Status |
|---|---|---|---|---|
| a | Background session, folder shell idle | Types `claude --resume S`; the CLI becomes `claude attach`; refusal → `_retry_with_attach` as backstop | Same; don't type `attach` proactively | Handled (add F3 marker) |
| b | Standalone session live in another tracker terminal | `_session_pty` hit, attaches | Same | Handled |
| b2 | Session is a hand-typed `claude` in a tracker shell | Primary shell: missed, second REPL. Spare: hit via `spawned` | Attach, matched on holder pid | Gap, new |
| b3 | Session live in a terminal outside the tracker | Silent second REPL (F2) | Refused with a message (Decision 2) | Gap, new |
| c1 | Folder shell busy with a different STANDALONE Claude or user job | Dedicated pty | Same unless an idle spare shell exists; never touched | Cannot reuse safely |
| c2 | Folder shell busy with a different session's THIN CLIENT | Dedicated pty | See g | New |
| d | Several terminals in the folder | Only the primary considered | Primary if idle → oldest idle spare → least recently active thin client → new pty | New for spare shells |
| d2 | Dedicated pty (`claude` exec'd directly) that exited | Reaped at once | Same; no shell, not reusable | N/A |
| d3 | Dedicated pty alive | Own terminal | Not reused, even a thin client (idle TTL reaps those harmlessly) | Out of scope |
| e | Session with no terminal open | Idle shell typed into, or new primary with deferred start | Same | Handled |
| f | Other cwd or worktree of the same repo | Exact-string match in `_folder_pty` | Same; a worktree is a different folder. Add the F5 check | Handled, guard new |
| g | Terminal showing thin client of A, nobody watching, open B | Dedicated pty | SIGTERM the client, type B's resume at the returned prompt. A keeps running; reopening A works the same way | New (core), Decision 1 |

"Spare shell" = the `mode="cwd"` overflow pty from `open_pty` when another session holds the primary (`argv = shell_argv`, ~3136). It is the only overflow pty with a shell.

Is g safe? E1: the REPL survives a killed client. E2: a tool finishes even after SIGKILL mid-tool. E3: clients are independent. Unmeasured: SIGTERM behaviour, whether a draft survives (E4 measures both before any swap code).

### What must never happen, and the guard for each
| Rule | Guard |
|---|---|
| Typing over a running job | `_fg_pgid == pid` at claim and again in `_inject_argv` (exists) |
| Typing over half-typed input | New `Pty.line_dirty`, checked at claim and just before the write |
| Displacing a live session | Only a process whose `ps` args are exactly `claude attach <short>` may be signalled; short must prefix the fg session; `daemon_repl_pid(session) > 0`. A standalone Claude never qualifies |
| Signalling the wrong process | Re-check `p.fg is old_fg` and `_fg_pgid(p) == pg` under `_LOCK` right before the signal; never signal `pg <= 0`, the shell's pid, or our own group |
| Two REPLs on one transcript | `_session_pty` + new `live_repl_pid` |
| Hijacking a watched pane | `viewers == 0` for spare shells and swaps. The primary keeps today's behaviour (a viewer's click may still reuse it) |
| Typing during startup | `startup_done` required for spare shells; `fg_pending` and `starting` false |

### Implementation (in order; each step shippable)
**Step 0: experiments** (scratch sessions, `mktemp -d`, plain pty harness):
- E4: `claude --bg --model haiku` session A, attach in a pty, type a draft unsent, `killpg(SIGTERM)`. Record: time to prompt, modes left on (alt screen, mouse), REPL alive, draft survives re-attach, transcript unchanged.
- E5: `claude --resume A` from a shell: same pid becomes `… attach <short>`; record the time.
- E6: two `claude --resume D` on an idle standalone session: is the second refused?
- Gates: E4 harms the REPL ⇒ drop Step 5 and report. SIGTERM ignored but REPL fine ⇒ SIGKILL + mode reset. E6 refusal ⇒ drop Step 4's refuse branch.

**Step 1:** `term_gate.py:113`: add `"is running in the background ("` to `BG_REFUSAL_MARKERS` (keep the `(`; the no-job form is common prose).

**Step 2: guards** in `term_vt.py`. `import re`; `self.line_dirty = False` after `self.shell_cmd` (~1492).
```python
_TERM_REPLY_RE = re.compile(rb"\x1b\[[?>=]?[\d;]*[cnRIOt]|\x1b\[\?[\d;]*\$y|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")

def _note_shell_input(pt, data):
    """Keystrokes vs the shell's line editor. keys() is the only human input path, so this is
    complete; False means the line is known empty. Errs towards dirty: that only costs a new terminal."""
    if not pt.folder or (pt.startup_done and _fg_pgid(pt) != pt.pid):
        return                     # a job is eating these; during rc files they are type-ahead
    rest = _TERM_REPLY_RE.sub(b"", data)   # xterm.js sends DA/DSR/focus replies through keys()
    if rest:
        pt.line_dirty = bool(re.split(rb"[\r\n\x03]", rest)[-1])

def _shell_cwd(pid):
    """The process's real cwd, or "" when unknown. Never raises. Forks: never under _LOCK."""
    try:
        return os.readlink("/proc/%d/cwd" % pid)
    except OSError:
        pass
    try:
        out = subprocess.run(["lsof", "-a", "-d", "cwd", "-p", str(pid), "-Fn"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""
    return next((l[1:] for l in out.splitlines() if l.startswith("n")), "")
```
- `keys()` (~3475): call `_note_shell_input(pt, data)` just before `os.write`.
- `_inject_argv` (~1875), after the prompt-wait loop, before the first `_inject_write`:
```python
if pt.line_dirty:
    return False, "unsent input at the prompt"
if not deferred:     # a .zshrc that cd's must not fail a deferred start for 120s
    real = _shell_cwd(pt.pid)
    if real and pt.cwd and os.path.realpath(real) != os.path.realpath(pt.cwd):
        return False, "the shell has moved to another folder"
```
- `open_pty` claim block (~3147), a branch BEFORE the claim:
```python
elif fg is None and settled and fp.line_dirty:
    busy_what = "unsent input at the prompt"
```
- `_refresh_fg`: set `pt.line_dirty = False` where it clears the label.

**Step 3: spare shells become reusable.** Make them `folder=True` rather than a second flag (17 `.folder` sites already behave right: fg-first kill, busy-close confirm, fg refresh, ownership).
- `_folder_pty` (~1848): add `and not p.overflow`, so it still means THE primary.
- Overflow section (~3232, after `pt.overflow = True`): when `argv is shell_argv`, set `pt.folder = True`, `pt.shell_cmd = pt.cmd`, `pt.startup_done = False`, start `_folder_settled` as ~3119 does (with its RuntimeError fallback). The final response returns `"folder": pt.folder`.
- Extract the body of `if busy_what is None:` (~3197) into `_type_claimed(p, argv, sid, mode, forked, cols, rows) -> (ok, why, starting)` (sets starting, types, starts the backstop, adds the grant; releases the claim on failure).
- New:
```python
def _idle_spare_shell(cwd):   # under _LOCK
    for p in sorted(PTYS.values(), key=lambda p: p.started):
        if (p.folder and p.overflow and p.cwd == cwd and p.viewers <= 0 and p.startup_done
                and not (p.done or p.closing or p.starting or p.fg_pending or p.line_dirty)):
            _refresh_fg(p)
            if p.fg is None and _fg_pgid(p) == p.pid:
                return p
    return None

def _reuse_terminal(cwd, sid, mode, argv, forked, cols, rows):
    """Any other terminal in this folder that can take this open, or None -> open a new one.
    Returns the response dict."""
```
- Call once, right before `# ---- overflow` (~3222):
```python
reply = _reuse_terminal(cwd, sid, mode, argv, forked, cols, rows)
if reply is not None:
    return handler._json(reply)
```
- Inside, under `_LOCK`, find the idle shell. `mode == "cwd"`: add the grant and answer; nothing typed. Otherwise claim as the existing block does, then `_type_claimed`. On failure continue to Step 5.
- Response shape: `{tty, renderer, forked, notice:None, starting, reused:True, folder:True}`.

**Step 4: second-REPL guard.** `config.py`: `LIVE_SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")` next to `DAEMON_ROSTER` (:72). `providers/claude.py` next to `daemon_repl_pid` (:602):
```python
def live_repl_pid(sid):
    """pid of a live INTERACTIVE Claude holding session `sid`, or 0. Background holders are not
    here: the CLI itself hands those off to `claude attach`. Never raises."""
```
Scans `*.json`: `kind == "interactive"`, matching `sessionId`, `_pid_alive(pid)`; if `procStart` is present it must equal `ps -o lstart= -p pid` (rejects a recycled pid); any failure = no holder for that file.

`open_pty`: compute `holder` next to `resolve_spawned` (~3062) via the `__import__` idiom, in `try`, default 0. Under `_LOCK`, after `_session_pty(sid)` misses:
```python
if holder:
    hit = next((p for p in PTYS.values() if not (p.done or p.closing) and _fg_pgid(p) == holder), None)
    if hit is None:
        return handler._json({"error": "This session is running in another terminal outside the "
                                       "tracker. Close it there first.", "running_elsewhere": True}, 409)
    # same grant and reused response as the _session_pty hit above
```
No client code: `_openVTFresh` already prints `res.j.error`.

**Step 5: thin-client swap** (`mode == "resume"` only; `new` must not displace a view):
```python
THIN_DETACH_WAIT = 3.0   # s for a signalled thin client to give the prompt back
VIEWER_GRACE = 0.5       # s for a just-closed pane's SSE to drop; streams poll _peer_gone every 0.05s

def _thin_client_short(pgid):
    """<short> when process `pgid` is exactly `claude attach <short>`, else "". Forks: never under _LOCK.
    Three tokens only: a path with spaces or a quoted name reads as "", which is the safe answer."""

def _swappable_thin_client(cwd, sid):
    """-> (p, old_fg, pgid) or None. Snapshot under _LOCK, least recently active first:
    p.folder, same cwd, not done/closing/starting/fg_pending, fg names a session != sid, not fg.forked.
    Then, unlocked, per candidate: wait up to VIEWER_GRACE for viewers == 0; pg = _fg_pgid(p), skip if == p.pid;
    short = _thin_client_short(pg); require fg session startswith short and daemon_repl_pid(session) > 0."""

def _swap_in(p, old_fg, pg, argv, sid, forked, cols, rows):
    """-> response dict or None."""
```
`_swap_in`:
1. Under `_LOCK`: bail unless `p.fg is old_fg`, `p.viewers <= 0`, not closing/done, `_fg_pgid(p) == pg`. Then set the claim (`fg_pending=True`), which also stops `_refresh_fg` touching it.
2. If `pg > 0`, `pg != p.pid`, `pg != os.getpgrp()`: `os.killpg(pg, signal.SIGTERM)`, catching OSError.
3. Poll `_fg_pgid(p) == p.pid` until `THIN_DETACH_WAIT`.
4. Timeout, under `_LOCK`: `p.fg = old_fg; p.fg_seen_child = True; p.fg_pending = False`; return None. Nothing typed.
5. Success: feed `b"\x1b[?1049l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1004l\x1b[?25h\x1b[0m"` to `p.screen` and `_tee_raw`, under `p.lock` as `_feed_note` does (a dead client may leave these modes on).
6. `_type_claimed(...)`. Failure: return None (A has no view, harmless; the open gets a dedicated pty).

`pt.cmd` stays misleading for a CLI-converted client; display only.

### Client changes
None. List rows for spare shells gain `folder:true` alongside `overflow:true`. `ext_vt.js:2891`/`:3811` scan rows oldest first, so the primary matches first. `ext_vt.js:2615` and `ext_cr_dialogs.js:2040` title them by what is running.

### Tests (new file tests/test_folder_reuse.py; `_FakeHandler`/`_stub_kill` patterns)
| Test | Why RED before |
|---|---|
| `test_bg_refusal_matches_current_cli_wording` | Marker missing |
| `test_keys_at_prompt_marks_dirty_and_enter_clears` | No `line_dirty` |
| `test_keys_while_job_in_foreground_stay_clean` | Same |
| `test_terminal_replies_do_not_mark_dirty` (DA, DSR, focus) | Same |
| `test_open_resume_with_half_typed_line_never_types` | `_inject_write` runs today |
| `test_inject_argv_refuses_line_dirtied_during_wait` | Writes today |
| `test_inject_argv_refuses_shell_that_left_its_folder` | Writes today |
| `test_deferred_inject_skips_cwd_check` | Pins the .zshrc exception; mutation-proved |
| `test_shell_cwd_parses_lsof_and_never_raises` | No function |
| `test_cwd_taken_shell_is_a_folder_shell` | `folder` False today |
| `test_folder_pty_ignores_spare_shells` | Red against Step 3's flag without the filter |
| `test_resume_uses_idle_spare_shell_instead_of_new_pty` | `spawn` called today |
| `test_cwd_taken_reuses_idle_spare_shell_without_typing` | `spawn` called today |
| `test_oldest_idle_spare_shell_is_chosen` | No selection |
| `test_spare_shell_not_reused_when` (viewer, dirty, busy, pending, starting, closing) | Mutation-proved after Step 3 |
| `test_dedicated_overflow_is_never_a_candidate` | Mutation: remove the `folder` check |
| `test_live_repl_pid` (interactive, bg ignored, dead pid, procStart mismatch, malformed JSON) | No function |
| `test_resume_held_outside_tracker_refuses_409` | Types today |
| `test_resume_attaches_to_pty_whose_foreground_is_the_holder` | Types a second REPL today |
| `test_thin_client_short_table` | No function |
| `test_resume_swaps_unwatched_thin_client` (killpg SIGTERM, typed line, no spawn) | `spawn` called today |
| `test_not_swapped_when` (viewer, standalone args, short mismatch, dead REPL, forked, starting, pending, mode new) | Mutation-proved |
| `test_swap_never_signals_when_foreground_changed` | Mutation: remove the re-check |
| `test_swap_restores_label_when_client_will_not_exit` | No function |

`_selfcheck` (tests/test_selfcheck.py after the `_session_live` lines): `_note_shell_input` marks and clears dirty; `_thin_client_short` with mocked `subprocess.run` accepts `/x/claude attach ab12cd34`, rejects `claude --resume ab12cd34`.

Integration: `TestFolderReuseEndToEnd` in tests/test_integration.py (server setup from `TestTermIdleTtlEndToEnd`, terminal auth from `TestTermCountBadge`). Real server, `/bin/sh`, pty and signals; a fake `claude` script first on PATH that logs args and sleeps; stub `term_gate.session_cwd`; `config.DAEMON_ROSTER` → temp file with live pids; only `_thin_client_short` mocked.
- `test_resume_flies_into_spare_shell`
- `test_resume_swaps_thin_client_same_tty`
- `test_half_typed_line_is_left_alone`

### Live proof
Worktree server on :8799 with `TRACKER_TERMINAL=1 TRACKER_AUTH=u:p`. Scratch folder, `--model haiku`. Never touch :8790/:8787. Stop by PID. Clean up with `claude stop`/`claude rm` for scratch sessions only.
- L1: open bg A, no viewer, open bg B: same tty; B's client in `ps`; A's REPL alive; transcript not truncated. Reopen A: same tty, list length 1.
- L2: hold `curl -N` on the screen stream, open B: new tty; A's client pid unchanged.
- L3: standalone C in the folder shell, open A: new tty; C's pid unchanged.
- L4: idle shell, POST keys `echo hi` without Enter, open A: different tty; `echo hi` still unsubmitted.
- L5: `claude --resume D` in an outside pty, open D: 409, no second process. Then hand-type it in a tracker shell: open D attaches to that tty.
- L6: close the spare's viewers, open again: spare reused.

Then `make check`. Update README:100 (stale: mentions a folder badge and an announcement), the "Folder terminal" part of `open_pty`'s docstring.

### Risk and fallback
- Riskiest: `_swap_in` signals a process in a shared shell. Mitigation: `ps` args check, prefix match, live REPL check, re-check under `_LOCK`, SIGTERM only, E4 first. Fallback: drop Step 5 alone; the feature reduces to idle-shell reuse plus guards, and the common case keeps opening a new terminal (tell the user plainly).
- Second: `folder=True` on spare shells changes close behaviour and ownership. Fallback: revert Step 3.

### Known gaps
- A continuation prompt (`echo "` then Enter) reads as clean.
- Primary closed while an idle spare exists: the next open spawns a new primary.
- In-flight `/api/term/inject` to A with no viewer can be cut by a swap (partial draft in A).
- A thin client navigated to agent view still reads as A (swapping is harmless).
- Tier 3 external terminals (`term_launch`) get no second-REPL guard.
- Hosting every tracker session in the daemon would make all terminals swappable, but changes where sessions run. Not planned.

### Decisions flagged for the user
1. May an unwatched terminal switch from one background session to another? Recommended: yes.
2. Opening a session already running outside the tracker: refuse with a message (recommended) vs keep allowing a second copy.

## Review (opus reviewer, 2026-11-04) — VERDICT: REFUTED
Facts: F1 holds (gated by remote flag `tengu_resume_open_live_bg`, default true). F2 is supported by the binary, unproven at runtime. F3 holds. F4/F5 are true by code read. `procStart` = `ps -o lstart=` is FALSE (the CLI runs it with `LC_ALL=C TZ=UTC`).

1. HIGH: Step 4's recycled-pid check rejects every holder on this machine (procStart is UTC, `ps` prints IST). Mocked test stays green. Fix: use `TZ=UTC` (moot if Step 4 is cut).
2. HIGH: `live_repl_pid` treats a parked REPL (`parkedJobId` present) as a holder; `hxe` skips those. Fix: skip them (moot if cut).
3. HIGH: on this machine the feature fires for nothing identified. 3 terminals, 3 folders. The likely real case (dw-vida-ai pane 7137c766afb2, pid 48357, parked) is misclassified as standalone; a parked pane's session has moved to a daemon job. Whether killing a parked TUI is safe is unmeasured. Fix: new E7, then decide.
4. HIGH: Step 2 can hang a fresh terminal for 120s and then not start Claude (a key or unmatched reply during rc marks dirty; `_inject_argv(deferred=True)` keeps failing). Fix: cut Step 2, file F4 separately.
5. MEDIUM: false dirty on the primary shell (arrow, backspace, Ctrl-U, Ctrl-L, Tab, mouse, ESC, DCS). One stray arrow means every later open gets a new terminal. Fix: same as 4.
6. HIGH overengineered: Step 3 has near-zero value (0 live overflow rows; spares come from a picker tab with a viewer) and a regression (`folder=True` routes spares into `_session_ptys`' folder branch, which ignores `spawned`, so a hand-typed Claude stops matching and `registry._attached_pty` loses it). Fix: cut.
7. MEDIUM product: Step 4's 409 isn't in the request and blocks legitimate opens (a forgotten tmux Claude; a session in a second tracker instance). Fix: cut; raise separately.
8. MEDIUM: E4 is idle-only; E2 was SIGKILL on 2.1.317. Fix: E4a idle, E4b SIGTERM mid-tool, E4c SIGTERM at a permission prompt; REPL alive 5 min later, transcript unchanged, re-attach shows the same state; record the CLI version; any harm drops the swap.
9. MEDIUM: "client changes: none" is false. A dropped viewer reconnects after a swap, `_pty_owned` is false ⇒ 409, EventSource closes, "reconnecting..." forever over a dead pane. Fix: `readyState === 2` ⇒ "disconnected -- reopen this terminal" in both renderers (grid handler to be read first); never auto-rebind to B.
10. MEDIUM product: the swap is silent and flipping gets slower (~3.5–5s per flip, estimated). Fix: `notice` naming A; L1 measures.
11. MEDIUM product: a non-background B can displace A, then the pane stops being swappable. Fix: thin replaces thin only (`daemon_repl_pid(sid) > 0`).
12. LOW: the F5 check runs after the kill. Fix: check `_shell_cwd` before any signal, in the candidate check.
13. LOW: Step 5's claim is ambiguous. Fix: set `p.fg` to B's label under `_LOCK` + `starting=True`, so a concurrent open of A doesn't peek at a dying client.
14. LOW overengineered: the mode reset. A scratch pty shows zsh/bash fine after a raw/alt child. Decide from E4; if kept, feed `p.screen` only.
15. LOW: `VIEWER_GRACE` comment wrong (raw loop polls 0.2s).
16. Tests: "No function" rows are RED only by AttributeError; `test_live_repl_pid` is green with the real bug; use one end-to-end test with generous polls; actually perform the mutations.
17. Live proof: `curl -N` can't prove close-before-POST, so a real browser A→B click is needed. The real daemon (pid 19353, not transient) is shared: capture each scratch short; `claude stop`/`rm` only those.

False alarms checked: races between unlocked checks and `_swap_in`; killpg scope; `H9` fallback; backstop retries; `_refresh_fg` during pending; idle TTL mid-swap; MAX_TERMS; zsh/bash after SIGTERM.

Clean plan (reviewer): scope = a resume targeting a background session, where the folder's primary shell shows a DIFFERENT background session's thin client, unwatched ⇒ swap; everything else as today. Cut Steps 2, 3, 4, `_type_claimed`, `_reuse_terminal`, E6. Keep the marker; `_thin_client_short`, `_shell_cwd`, `_swap_candidate`, `_swap_in` at one call site before `# ---- overflow`; the closed-stream status in the client; docs.

## Experiments E4, E5, E7 (sonnet, claude 2.1.318, scratch sessions only, all cleaned up)
Logs: ~/.claude/jobs/3513f2df/tmp/exp2/.
- E4a idle: SIGTERM is honoured; the `claude attach` client dies in 0.05s with no handler. The REPL stays alive, the transcript is byte-identical, and the draft survives (held by the REPL). **The client does no terminal cleanup**: alt screen, mouse 1003 + SGR and bracketed paste stay on, and the prompt draws on the alt screen. A mode reset IS needed (`?1049l ?1003l ?1006l ?25h`); this overturns review finding 14.
- E4b mid-tool: the tool completed, `tool_result` was recorded, no "[Request interrupted", REPL alive 5 min later, re-attach shows the finished state. The kill landed ~6s in. Anomaly: session A's result came ~4.5 min late ("running PostToolUse hooks 1/2 · 5m 49s"). The controlled repeat (D killed vs E not killed, 60s tool) gave 64.4s vs 63.8s, so the kill is not the cause. A's stall is unexplained, not reproduced.
- E4c permission dialog: harmless. REPL alive 5 min later, transcript unchanged, the same dialog on re-attach; approving it worked.
- E5: `claude --resume <live bg id>` keeps the same pid and its args become `.../claude attach <short>`. To conversion: 11.06s cold, 1.88s warm. To a readable screen: 11.97s cold, 2.78s warm.
- E7 parked: `/background` does NOT park (the client exits and the session moves to a worker). Left arrow at an empty prompt DOES park: `sessions/<pid>.json` gains `parkedJobId`, `kind` stays interactive, `ps` args are unchanged, and the job has its OWN sessionId in the roster (its `launch` points at the original transcript). SIGTERM to the parked pane: graceful exit in 2.56s, modes reset itself, SessionEnd hook printed "Hook cancelled", the job's worker and REPL stayed alive, the transcript gained 746 bytes of metadata only (`cost-state`, `last-prompt`, `permission-mode`), and `claude attach <job short>` works. `claude --resume <original id>` then started a STANDALONE client (no conversion), because the live job has a different id.
- Implications for the plan: the swap is safe for thin clients with a mode reset. Parked panes are safe to signal but need different eligibility (`parkedJobId`, not `ps` args) and a longer detach wait than 3.0s. A parked pane's `fg.session` does not name its job.

## REVISED SPEC (opus planner, at 3b7fb05, claude 2.1.318) — thin clients + parked panes; supersedes "Original plan"
User scope (2026-11-04): build for daemon thin clients + parked panes; background targets only; unwatched only; banner. Cut: `line_dirty`, spare shells, `live_repl_pid`/409, `_type_claimed`, `_reuse_terminal`, E6.

### Parked verdict
Safe enough to build, behind E8. Corrects the brief: the E7 trap is not two REPLs on one transcript but a stale branch. Parking FORKS: worker `48a30864` has `dispatch.source:"slash"`, `launch:{mode:resume, fork:true, restoresTranscript:true, sessionId:<path to 5c109d81….jsonl>}` and writes its own `48a30864-….jsonl`; the original last changed ~1h earlier (one sample; E8 re-verifies). So `--resume <original>` opens the pre-park conversation beside the live job.

Mapping: the original's transcript holds `{"type":"continued-in","sessionId":O,"continuedInSessionId":J}`; the CLI reads it from the tail (`yur`), and a later completed turn voids it.

| Question | Answer |
|---|---|
| Which row does the dashboard show? | Both: `5c109d81` "vida-sprint-board" and `48a30864` "vida-sprint-board (2)"; not linked today |
| What to type for a moved session? | `claude --resume <J>` (CLI converts to attach; if J ended it resumes J normally) |
| How does an original id find its job? | New `background_id(sid)`: `sid` if `daemon_repl_pid(sid)>0`, else J if the tail's `continued-in` names J and `daemon_repl_pid(J)>0`, else "" |
| Is a target known only by its original id "background"? | Yes, via that mapping; it runs as J |
| Change `_session_pty`/`daemon_repl_pid`? | No; `open_pty` resolves first and asks about both ids |

SessionEnd hooks: SIGTERM to a parked pane fires SessionEnd for the original id ("Hook cancelled" in E7). Hooks may be cut short (here: a `curl -m 2` POST to LinkPage and iTerm `cc-status`). No worse than today (✕ close and idle reap use SIGKILL, no hooks). Thin clients fire nothing. Document in README.

Reach: fires only while the displaced pane is alive and unwatched; thin panes are reaped by the TTL once quiet; parked panes too. Today: 3 terminals in 3 folders ⇒ nothing would swap right now.

### Case table (only what changes)
| # | Open | Terminal in that folder | Today | After |
|---|---|---|---|---|
| 1 | Background B | Primary shows thin client of background A, unwatched | Dedicated pty | SIGTERM A's client, modes reset, B typed, same tty, banner names A |
| 2 | Background B | Primary is a parked pane (job J), unwatched, no tool children | Dedicated pty | SIGTERM, graceful exit, B typed, same tty, banner names J |
| 3 | J itself | Primary is the parked pane for J, unwatched | Dedicated pty | Same swap, no banner |
| 4 | Original row O, J alive, no pane on O | Any | `--resume O` opens a stale standalone | Runs J (`_session_pty(J)` hit, typed, cases 1–2, or dedicated). **Decision 1** |
| 5 | Dropped viewer of A reconnects after a swap | | 409, "reconnecting…" forever | "disconnected — reopen this terminal", never rebinds |

Unchanged and pinned by tests: non-background target; watched pane; standalone Claude or user job; O while its parked pane is alive (peek); `new`/`cwd` modes; a shell that has `cd`'d away.

### Implementation
**Step 0: E8** (scratch, plain pty).
- E8a: scratch O with a long background Bash and a long tool, park with Left, SIGTERM the pane: does the tool survive; does `_claude_work_children(pid)` see it; exit time.
- E8b: `continued-in` written; J has its own file with `fork:true`; `--resume <J>` converts to attach after the pane is gone.
- E8c: `claude stop <J>`: `--resume O` is standalone; `background_id(O)` returns "".
- Gates: E8a harms undetectable work, or J shares O's file ⇒ thin-only (drop parked steps and cases 2–4). Exit >8s ⇒ raise `PARKED_DETACH_WAIT`.

**Step 1:** `term_gate.py:113`: add `"is running in the background ("` to `BG_REFUSAL_MARKERS`.

**Step 2:** `config.py:72`: `LIVE_SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")`.

**Step 3:** `providers/claude.py`, after `daemon_repl_pid` (602):
```python
_CONTINUED_MARK = b'"type":"continued-in"'

def _continued_in(path):
    """J when this transcript's newest conversational record is a `continued-in` marker, else "".
    Mirrors the CLI's `yur`: a later user/assistant line voids it. 96 KB tail. Never raises."""
    # read tail; return "" if mark absent; for raw in reversed(tail.split(b"\n")):
    #   mark in raw -> json parse; id if safe_path_component(id) else ""
    #   b'"type":"user"' or b'"type":"assistant"' in raw -> ""

def background_id(sid):
    """`sid`, or the job it continued in, when hosted by a live daemon REPL; "" otherwise."""

def parked_job_id(pid, label):
    """Job session id when `pid` is a parked TUI running session `label` whose job is live, else "".
    Reads LIVE_SESSIONS_DIR/<pid>.json. Requires: pid equal, kind "interactive", sessionId == label,
    parkedJobId a safe str in _live_workers() with a live replPid, and procStart matching
    `ps -o lstart= -p pid` run with env LC_ALL=C TZ=UTC (whitespace-normalised string compare,
    never parse dates; missing procStart -> ""). Reads only those fields. Never raises."""

def session_label(sid):
    """Title for a banner: load_titles().get(sid) or _session_meta(path)["title"], else ""."""
```
Do not edit `_live_workers`; the job comes from its keys.

**Step 4:** `term_vt.py` helpers above `_session_pty` (3262):
```python
THIN_DETACH_WAIT = 2.0     # measured 0.05s; no handler
PARKED_DETACH_WAIT = 8.0   # measured 2.56s graceful exit, and it runs SessionEnd hooks
VIEWER_GRACE = 0.5         # grid streams poll _peer_gone at 0.05s, raw at 0.2s
_TERM_MODE_RESET = b"\x1b[?1049l\x1b[?1003l\x1b[?1006l\x1b[?25h"

def _provider():            # __import__ idiom as _session_live; None in the bundle
def _thin_client_short(pgid):
    """<short> when `ps -o args= -p pgid` is exactly three tokens: */claude|claude, attach, <short>. Else ""."""
def _shell_cwd(pid):        # /proc readlink, else `lsof -a -d cwd -p pid -Fn`; "" when unknown; never raises
```
`_folder_wait_prompt(pt, wait=BACKSTOP_WINDOW)` (1860): add the parameter; no second polling loop.

`_swap_candidate(fp, sid, cwd) -> dict(fg, pg, kind, shown) or None` (`sid` = resolved target; forks ps/lsof, never under `_LOCK`). Any failure ⇒ None; all before any signal:
1. Wait up to `VIEWER_GRACE` for `fp.viewers <= 0`.
2. Under `_LOCK`: `_refresh_fg(fp)`; need `fp.fg` with `mode == "resume"`, truthy `session != sid`, not `forked`, `fp` not `done/closing/starting/fg_pending`.
3. `pg = _fg_pgid(fp)`; need `pg > 0`, `pg != fp.pid`.
4. `real = _shell_cwd(fp.pid)`; if known, realpaths must match `cwd`.
5. Thin: `short = _thin_client_short(pg)`, `len(short) >= 4`, `fg["session"].startswith(short)`, `daemon_repl_pid(fg["session"]) > 0` ⇒ `kind="thin", shown=fg["session"]`.
6. Else parked: `job = parked_job_id(pg, fg["session"])`, `not _claude_work_children(pg)` ⇒ `kind="parked", shown=job`.

`_swap_in(fp, cand, sid, run_sid, argv, forked, cols, rows) -> response dict or None`:
1. Under `_LOCK`: bail unless `fp.fg is cand["fg"]`, `fp.viewers <= 0`, not closing/done, `_fg_pgid(fp) == cand["pg"]`. Claim: `fp.fg = {"session": run_sid, "mode": "resume", "started": now, "grants": {sid, run_sid}}`, `fg_seen_child=False`, `fg_pending=True`, under nested `fp.lock` `starting=True`.
2. Signal only if `pg > 0`, `pg != fp.pid`, `pg != os.getpgrp()`: `os.killpg(pg, signal.SIGTERM)`, catching OSError. Never SIGKILL.
3. `_folder_wait_prompt(fp, THIN_DETACH_WAIT or PARKED_DETACH_WAIT)`. False ⇒ under `_LOCK`, if not closing: `fp.fg = cand["fg"]`, `fg_seen_child=True`, `fg_pending=False`, `starting=False`; return None.
4. Thin only, under `fp.lock`: `fp.screen.feed(_TERM_MODE_RESET)` and `_tee_raw(fp, _TERM_MODE_RESET)`, before typing. Parked panes reset themselves.
5. `ok, why = _inject_argv(fp, argv)`. Failure: release as ~3217 (`fg=None`, flags False, `starting=False`); return None.
6. Success: `starting = _start_backstop(fp, run_sid, forked, cols, rows)`, add `sid` to `fp.grants`. If `cand["shown"] != run_sid`, under `fp.lock`: `fp.notices.clear()`, `fp.add_notice('"<title>" (<short>) keeps running in the background. Reopen it from the dashboard.')` (fallback `session <short>`). Use `add_notice`, not the response `notice`.
7. Return `{tty, renderer, forked, notice: None, starting, reused: True, folder: True}`.

**Step 5:** `open_pty` (2906); `sid` stays the requester, `run_sid` is what runs:
| Line | Change |
|---|---|
| top of `if sid:` (~3013) | `bg, run_sid = "", sid`; if `mode == "resume"`: `bg = _background_target(sid)`; `run_sid = bg or sid` (wrapper around provider `background_id`, "" on failure). Same defaults for a session-less open |
| 3020 | `session_cwd(run_sid, resume=True)` for resume |
| 3038 | `resume_argv(run_sid)` |
| 3067 | `hit = _session_pty(sid) or (_session_pty(run_sid) if run_sid != sid else None)` (O's live parked pane wins: stays a peek) |
| 3158 | `"session": run_sid if mode == "resume" else ""`, `"grants": {sid, run_sid}` |
| 3162 | compare `fg.get("session") == run_sid` |
| 3183, 3208 | pass `run_sid` to the deferred start and backstop |
| 3232, 3248 | `pt.session = run_sid`; backstop gets `run_sid`; `pt.grants.add(sid)` stays |
| before `# ---- overflow` (3222) | call site below |
```python
if mode == "resume" and busy_what and bg:
    cand = _swap_candidate(fp, run_sid, cwd)
    reply = cand and _swap_in(fp, cand, sid, run_sid, argv, forked, cols, rows)
    if reply:
        return handler._json(reply)
```
Known residual: `_folder_retype` claims `grants {J}` only, so after a redirect that also hits a refusal, a viewer bound to O gets "disconnected"; reopening works.

**Step 6:** `web/ext_vt.js` 921 and 1955, one helper above `Terminal`:
```js
function _streamErrorStatus(es) {  // CLOSED: the browser will not retry (409 after the pane changed hands)
  return es && es.readyState === 2 ? "disconnected — reopen this terminal" : "reconnecting…";
}
```
`self.es.onerror = function () { if (self._onStatusChange) self._onStatusChange(_streamErrorStatus(self.es)); };`. Mounts 2797, 3646 already show the string and suppress it while `starting`.

**Step 7:** README:100 (also removes the stale folder-badge claim), `open_pty` docstring, hook note.

Sequence: E8, 1, 2, 3, 4+5 thin-only, then parked, 6, docs. Each commit keeps `make check` green.

### Tests (new tests/test_folder_reuse.py + integration; "mutation" = apply, watch fail, revert, record)
Fake CLI, real shell, real `ps`, real signals: temp `bin/claude` bash script first on PATH, temp `HOME`, `SHELL=/bin/bash`, temp `PROJECTS`/`DAEMON_ROSTER`/`LIVE_SESSIONS_DIR`.
- Thin mode, on `--resume X`: log args, print `\033[?1049h\033[?1003h\033[?1006h`, `exec -a "claude attach ${X:0:8}" cat` (verify on macOS; else mock only `_thin_client_short`).
- Parked mode: `trap 'sleep 2.6; exit 0' TERM`, loop on a short sleep, write `<pg>.json` with a real `LC_ALL=C TZ=UTC ps -o lstart=`.

Integration `TestFolderSwapEndToEnd` (real HTTP, polls ≤30s):
- `test_thin_client_swaps_in_same_tty` (same tty, one row, A's pid dead, log shows B, `fg.session==B`, Screen not alt, mouse off, notice names A). RED.
- `test_parked_pane_swaps_with_longer_wait` (mutate parked wait to 2.0: must fail). RED.
- `test_opening_original_runs_the_live_job` (log `--resume J`, `fg.session==J`, `_pty_owned(fp,O)`). RED.
- `test_old_viewer_gets_409_after_swap`. RED.

Provider `TestBackgroundIds`:
- `test_background_id_direct`
- `test_background_id_follows_continued_in`
- `test_continued_in_voided_by_later_turn`
- `test_background_id_empty_when_job_dead`
- `test_parked_job_id_real_ps_in_other_timezone` (real `sleep`, UTC lstart fixture, `TZ=Asia/Kolkata`, `ps` unmocked; mutation: remove `TZ=UTC`)
- `test_parked_job_id_rejects` (kind bg, no `parkedJobId`, label mismatch, pid mismatch, wrong/missing procStart, job not in roster, dead replPid, bad JSON, unsafe id)

`TestThinClientShort`: `test_thin_client_short_real_ps` (`exec -a`: accepts `claude attach ab12cd34`; rejects `claude --resume x`, four tokens, a dead pid).

`TestSwapGuards` (`os.killpg` asserted not called; mutation per check):
- `test_not_swapped_when` (viewer, standalone args, short mismatch, displaced REPL dead, forked, starting, pending, fg None, same session, shell moved, parked with work children)
- `test_non_background_target_never_swaps`
- `test_new_and_cwd_modes_never_swap`
- `test_viewer_grace_waits_for_a_closing_stream`
- `test_swap_never_signals_when_foreground_changed`
- `test_shell_moved_checked_before_signal`
- `test_swap_restores_same_label_when_client_will_not_exit`
- `test_type_failure_releases_claim_and_falls_through`
- `test_claim_names_target_during_detach`
- `test_mode_reset_only_for_thin`
- `test_no_banner_when_shown_equals_target`
- `test_swap_clears_old_notices_seq_stays_monotonic`
- `test_original_with_live_parked_pane_still_peeks`
- `test_bg_refusal_matches_current_cli_wording` (RED)

Client: `test_both_renderers_report_closed_stream` in tests/test_term_vt_client.py (source assertions). RED.

`_selfcheck` (tests/test_selfcheck.py after 919): `_continued_in` on a temp transcript (marker yes; marker then user no); `_thin_client_short` with mocked `subprocess.run`.

### Live proof on :8799
`TRACKER_TERMINAL=1 TRACKER_AUTH=u:p`, stop by PID, `mktemp -d` scratch folder, `--model haiku`. The daemon (pid 19353) is shared: capture each short; `claude stop`/`rm` only those; never `respawn` or daemon commands. Run L1 in both renderers.
- L1 real browser click: modal on A, click B. Same tty, banner names A, A's REPL pid unchanged, transcript not truncated; record flip time, flip 3 times (expected ~3–4s warm, 12–15s cold).
- L2 mid-tool flip: result recorded, no "[Request interrupted".
- L3 watched: second tab on A, open B: new tty; A's client pid unchanged.
- L4 standalone C in the shell, open A: new tty; C's pid unchanged.
- L5 non-background target D: new tty; A's client pid unchanged.
- L6 dropped viewer: close EventSource, flip via a second client, reconnect: "disconnected — reopen this terminal"; no bind to B.
- L7 parked: standalone O on :8799, POST Left arrow at the empty prompt via `/api/term/keys`, read J from `sessions/<pid>.json`, drop viewers, open B: same tty, pane pid gone, J's REPL alive, O gained metadata only, banner names J, record "Hook cancelled" if it appears.
- L8 original row: open O: `ps` shows `claude attach <J short>`, no standalone on O. Re-park a fresh scratch and open its J: same tty, no banner.
- L9 stopped job: `claude stop J`, open O: standalone, as today.

### Risk and fallback
- Riskiest: the parked leg (undocumented `parkedJobId`, `continued-in`, `ps` args; one fork sample; one idle SIGTERM measurement; CLI auto-updates). Worst case: a pane closed that had unseen work. Mitigation: E8, live-job and tool-children checks, SIGTERM only, unwatched only, fail-closed. Fallback: remove `parked_job_id` and the parked branch (one branch, one wait constant); thin swap stands alone; keep `background_id` if Decision 1 is yes.
- Second: the mode reset. If it misbehaves the pane looks wrong but no session is harmed; the next Claude redraws it.

Known gaps:
- An in-flight `/api/term/inject` to A with no viewer can leave a partial draft.
- A notice replays on a later re-open of the same tty.
- The `continued-in` check is slightly stricter than the CLI.
- O's row moves in the list after a parked exit (746 bytes of metadata).
- Input guards live in the handover doc.

### Decision for the user
Decision 1: clicking a session's old row after it moved to the background. Recommended: open the live one (J), so you can't branch by accident. Alternative: today's behaviour (the old row reopens the frozen copy as a separate conversation). This changes ordinary opens. If today's: drop `run_sid`; cases 1–3 are unaffected.

## Re-review of the revised spec (opus reviewer) + reconciliation (main thread)
Reviewer disclosures: it read 2061 transcripts in full with a script (printed lineage fields only; the brief said `grep -o`), and attempted one `pkill -P $$ sleep` (blocked; never ran). Verified directly: /api/term/list shows pane 7137c766afb2 `session=48a30864`, `fg=5c109d81`, `mode=resume`.

| Finding | Verdict | Action |
|---|---|---|
| A: opening O can return a pane O may not read (fg.grants lacks O) ⇒ healthy pane reads "disconnected" | **Confirmed by trace** | Removed by F; `_pty_owned` unchanged |
| B: idle reap can kill the shell mid-swap (held pane, re-probe during the quiet wait) | **Confirmed by trace**; window estimated | `fp.touch()` at the claim. Test `test_swap_touches_before_signal` |
| C: Manage-panel peek of a swapped pane 409s (`peekUrl` uses `t.session`; row keeps the opener) | **Confirmed** (row verified live) | `peekUrl` sends `(t.fg && t.fg.session) \|\| t.session`; `_live_list.session` unchanged |
| D: "no unseen work" guard fails open on `ps` failure | **Confirmed** | `_claude_work_children(pid, strict=False)`; `strict=True` returns None ⇒ no candidate. Reap path unchanged |
| E1: "nothing would swap right now" | **False; corrected.** The real pane is case 3: opening 48a30864 reuses the parked pane | Doc + told the user |
| E2: "cases 1–3 unaffected by Decision 1" | **Confirmed false**: after a parked swap, clicking O starts a stale standalone | Decision 1 |
| F: `run_sid` table is the wrong shape | **Confirmed overengineered** | Resolve once at the top: `j = _background_target(sid)`; `if j and j != sid and term_gate.session_cwd(j, resume=True): sid = j`; add `"session": sid` to the resume responses; client `bindTty(res.j.tty, res.j.session \|\| sid)` at ext_vt.js:2929, 3839. Own final commit |
| G: O can 404 where it works today | **Confirmed**, fixed by the F guard | Test `test_original_not_redirected_when_job_has_no_cwd` |
| H: one-hop mapping; "can't branch by accident" overclaims | **Accepted** | One hop; soften the text. 8/8 real markers have the claimed shape; J verified on only 2 |
| I: `starting` sticks on the closing path | **Confirmed by trace** | Clear on every False exit; restore the label only if not closing |
| J: `add_notice` + `notices.clear()` | **Overengineered** | Response `notice` reaches both open paths |
| K: mode reset too narrow | **Confirmed** | `\x1b[?1049l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1004l\x1b[?25h` |
| L: `mode=="resume"` blocks parked `new` panes | **Accepted, small** | Drop it; keep truthy session, not forked; hand-typed stays a gap (Decision 3) |
| M: E8 insufficient | **Confirmed** | Log children's pid/pgid/comm + guard verdict on an ordinary parked pane; SIGTERM while J is mid-tool; unpark/re-park. Harm = tool killed, missing `tool_result`, or "[Request interrupted". An ordinary parked pane reading as having work ⇒ tell the user, then thin-only or refine |
| N: live proof could stop a real job | **Confirmed; matters** | Before any stop, assert the worker's `dispatch.launch.sessionId` basename is the scratch O and its cwd is the `mktemp` dir; ttys only from :8799 responses |
| O: tests | **Accepted** | `exec -a … cat` is 3 tokens on macOS (poll for it; `sleep` adds a token); 2 real-signal integration tests; others at `_FakeHandler` level; stub `_background_target` in shared setup |
| **Not examined by the review** | The Control Room's own terminal path (`ext_cr_term.js`): whether it shows the banner and binds `res.j.session` | Implementer checks; live proof L1 uses the Control Room too |

Commit order:
1. E8 (extended)
2. marker
3. `LIVE_SESSIONS_DIR`, `parked_job_id`, `session_label`
4. thin swap (`_swap_candidate`/`_swap_in` take `sid` only; call site `daemon_repl_pid(sid)>0`)
5. parked branch
6. client status + `peekUrl`
7. docs
8. (if Decision 1 = yes) `_continued_in`, `background_id`, redirect per F+G

Fallback: remove the parked branch and thin swap stands; commit 8 reverts alone.

Decisions for the user:
1. Old row after a move: open the live one vs today's frozen copy.
2. Slower open for the real pane (~6s warm, ~15s cold, summed from measured pieces).
3. Hand-typed parked `claude`: no for now.

User decisions on these (2026-11-04):
1. Open the live conversation (final commit).
2. Yes, the slower open is acceptable.
3. Hand-typed parked panes stay out; "keep a separate note for that will look into that later" (note in `docs/handover-terminal-input-guards.md`).

## Progress
(implementer, claude 2.1.318, 2026-11-04; scratch dir ~/.claude/jobs/3513f2df/tmp/exp3, logs there)

### E8 (extended per finding M) — results; no gate tripped
- **Ordinary idle parked pane** (O replied "ok", Left arrow): `sessions/<pid>.json` gains `parkedJobId`; the pane's only child is `caffeinate` in the pane's OWN pgid; `_claude_work_children(pane)` = `[]` (reads clean). The job's roster row: `dispatch.launch.fork: true, mode: resume`, cwd = scratch, own sessionId, and `replPid`.
- **Busy case, honest limit**: Left does NOT park while a tool is in flight in the pane ("Infusing…" state: no `parkedJobId` after 8s); it parks during thinking/hooks, and the TOOLS THEN RUN UNDER THE JOB'S WORKER (`ppid` = worker, not the pane). So a parked pane never has tool children; the tool children guard only ever sees transient hook children (`it2`, `zsh` in their own pgids, during a PostToolUse hook): that reads as work for a moment = fail-closed (no swap), never a false "clean".
- **SIGTERM to a parked pane while J was mid-tool** (foreground `python3 -c "time.sleep(55); print('TOOLDONE_E8')"` plus a background `time.sleep(400)`): pane exit 0.96s–2.2s (three runs); the tool kept running under the worker, finished, J's transcript has 2 `tool_use` and 2 `tool_result` incl. `TOOLDONE_E8`, zero "[Request interrupted". No harm.
- A foreground tool shows how the harness deals with a `sleep N; echo` (blocked by a hook that wants Monitor): use `python3 -c` to get a real long tool.
- `continued-in` is written to O's transcript (`{"type":"continued-in",…,"continuedInSessionId":J}`) at park time. J has its OWN file (appears once J takes a turn), `fork:true`; O's file is not shared (O stayed 640731 bytes while J grew). `claude --resume <J>` after the pane is gone converted to `claude attach <J short>` in 2.0s. A turn typed in that client landed in J's file only.
- `claude stop <J>`: `--resume O` then starts a STANDALONE client on O (`claude --resume O`, no conversion, `parkedJobId` None). Stopping a job does NOT kill a `run_in_background` tool it started (orphaned `python3 time.sleep(400)` with ppid 1; killed by me after a cwd check).
- **Unpark (deviation from the spec's assumption)**: Enter (or Right) in the parked agent view returns to the original prompt, which is the TUI attached to the job IN-PROCESS (the binary's `a0e` unmounts the REPL, `KOo` attaches); the sessions file KEEPS `parkedJobId` (untouched, mtime = park time) and a second Left parks again with the same id. The file cannot tell the parked view from the returned view. Both are clients of the still-live job (SIGTERM-safe as measured), so the takeover treats them alike; the spec's "ineligible while unparked" cannot be implemented from the file and is not claimed.

### Commit (b) parked branch — mutation log
6 mutations on `term_vt.py` and 4 on `providers/claude.py` all RED, including `TZ=UTC` removal (caught by the plain real-`ps` test AND the explicit other-timezone test, since this machine runs IST). Logs: exp3/mut_b.log.

### Commit (c) redirect — notes
- Resolved once at the top of `open_pty` (`bg = _background_target(sid)`; `sid = bg` when `bg != sid`), responses carry `session`, the client binds `res.j.session || sid` in both open paths. The cwd stays the REQUESTED id's (see the deviation below); the takeover call site is `... and bg`, so a non-background original never displaces a pane. An original whose parked pane is still alive stays a PEEK (`_session_pty(req_sid)` is tried after the resolved id).
- Control Room (`ext_cr_term.js`, not examined by the review): its session-bound terminals ride `ExtVT.mountInto`, whose `finish()` fires the response `notice` (`onNotice` -> `st.notice` -> the notice strip) and whose POST path is the second `bindTty(res.j.tty, res.j.session || sid)`; its session-less open (`/api/term/pty` with `cwd`) shows `res.j.notice` and binds `""`. So one JS edit covers both; no separate fix needed. Pinned by `TestRedirectedSessionBinds`.
- **Deviation from the spec (guard G), found by the live proof**: a freshly parked job has NO transcript until its first turn, so `session_cwd(J)` is falsy and the spec's guard silently disabled the redirect for exactly the case it exists for (live L8: the old row opened a standalone `claude --resume O` beside the live job). The redirect now resolves the cwd from the REQUESTED id (J is a fork of it: same folder; a missing folder still 404s like today). Tests: `test_job_without_a_transcript_is_still_resumed_in_the_originals_folder`, `test_original_with_a_missing_folder_404s_like_today`.
- 4 mutations on `term_vt.py` (the 5th, `bg == sid` at the swap call site, became redundant once the redirect no longer depends on the job's cwd, so the condition is plain `bg`), 4 on `providers/claude.py`, 2 on `ext_vt.js`: all RED after adding two tests for the two the first pass missed (unresolved original displacing a pane; unbounded tail read). Logs: exp3/mut_c.log.

Live finding (L7): right after a park, the pane's own hooks (iTerm `it2`, osascript) appear as non-pgid children for 1-2s, so the strict work check refused a perfectly idle parked pane about half the time. `_swap_candidate` now samples for up to `PARKED_WORK_SETTLE` (3s) until the children are gone (None = unreadable `ps` still refuses at once). Mutations: single sample, fail-open None: both RED.

### Commit (a) thin swap — mutation log
11 mutations on `term_vt.py` all RED (viewer, short mismatch, standalone, displaced REPL dead, shell moved, foreground changed, no touch at claim, no mode reset, label not restored, target not background, no viewer grace); 3 on `ext_vt.js` all RED. Logs: exp3/mut_a.log, mut_js.log.

## Implementation review (opus, at 70b8a91) — DON'T LAND yet; reconciliation (main thread)
Verified directly: ext_vt.js:3820 returns the row with no `bindTty`; `looks_like_bg_refusal("…running in the background (PID 4242).")` is True.

| Finding | Verdict | Action |
|---|---|---|
| F1 after a swap, row binding is the displaced opener: Control Room open + Manage/cap kill get 409 | **Confirmed; land-blocker** | At ext_vt.js:3820 `bindTty(t.tty, sid)` when the user explicitly picks a row. `closeTty` takes an optional session; row callers pass `(t.fg && t.fg.session) \|\| t.session`, in `ext_vt.js` and `ext_cr_term.js`. `_pty_owned`, `_live_list.session` and `bindRows` unchanged |
| F2 redirect's production wiring untested (dead-redirect mutation stayed green) | **Confirmed** | Add the real-seam assertion in `test_background_target_reads_the_roster` |
| F3 new marker matches ordinary prose | **Confirmed** | Regex `is running in the background \([0-9a-f]{4,}\)\.`; keep older wordings |
| F4 doc errors (README:100, `open_pty` docstring, plan Progress, ~3032 comment) | **Confirmed** | Fix text |
| F5 stale cwd after J moves | **Accepted, one line** (sessions do move into worktrees here) | `session_cwd(sid, resume=True) or session_cwd(req_sid, resume=True)`; fresh-J case must keep working |
| F6 External resume on an old row still opens the frozen copy | **Follows the user's "old row opens the live conversation"** | Resolve through `background_id` in `term_launch.open_terminal`; test it |
| F7 real-signal test flake risk | **Confirmed** | Patch `THIN_DETACH_WAIT` to 15 in that class's setUp |
| Item 1: returned-view harm | **False alarm**; screen gate would be overengineered (binary: `a0e` unmounts the REPL; `KOo` = attach). In-memory "space to reply" drafts die with the pane: known gap | Prove live on a scratch session |
| Items 3, 4 | **False alarms** | None |
| Item 7 | (c) reverts clean; (b) needs conflict resolution | Say so in the plan |
| Live proofs required | Browser pass (session-row click, rendered banner, Control Room, both renderers) and a returned-view proof with a draft + mid-turn | Before landing |

## Reconciliation of the first review (main thread)
Verified directly: `looks_like_bg_refusal(<mxe wording>)` returns False; no `line_dirty` exists; /api/term/list shows 3 terminals in 3 different folders.

| Finding | Verdict | Action |
|---|---|---|
| 1, 2 Step 4 pid/parked bugs | **Confirmed**, moot once cut | Cut with Step 4 |
| 3 fires for nothing today; parked pane misclassified | **Confirmed** (3 terminals, 3 folders verified) | E7, then user decision |
| 4, 5 Step 2 hang + false dirty | **Confirmed by trace** | Cut Step 2; file F4 separately |
| 6 Step 3 | **Overengineered**, with a regression | Cut |
| 7 Step 4's 409 | **Overbuilt** beyond the request | Cut; separate item |
| 8 E4 too narrow | **Confirmed** | E4a/b/c |
| 9 dead pane after a dropped viewer | **Confirmed by code trace** (grid handler unread) | Client status fix |
| 10 silent swap | **Confirmed**; flip time is an estimate | Notice; measure in L1 |
| 11 non-background B | **Product** | User decision |
| 12, 13, 15 | **Confirmed**, small | Fold in |
| 14 mode reset | **Overengineered until E4 says otherwise** | Decide from E4 |
| 16, 17 | **Confirmed** | Fold in |
| User decisions (2026-11-04) | Experiments first, then decide (nothing built yet). If built: background sessions only. Cut items: handover in `docs/handover-terminal-input-guards.md` | — |
| **Missed by both** | Unwatched thin-client panes are themselves reaped at the idle TTL (harmless, per E1), so the swap only fires inside that window: at most `max(LIVE_WINDOW, TTL)` after the last write. Combined with finding 3, the feature's real-world reach is small | Tell the user plainly before building |

## Review fixes (implementer, one commit on top of 70b8a91)
- F1 `ext_vt.js`: `closeTty(tty, force, session)` + `ttyBody(tty, extra, session)` (optional override of the page's binding); every row caller (`closeOneFromManager`, its busy-confirm retry, `killSeries` x2, `ext_cr_term.js` `_killTerminal` x2) passes `(t.fg && t.fg.session) || t.session`; `mountInto`'s find-existing binds `bindTty(t.tty, sid)` for a `fg.session === sid` row. `_pty_owned`, `_live_list.session`, `bindRows` unchanged. `_killCurrent` (ext_cr_term.js) kills `st.tty`, whose binding is already right (it came through `mountInto`).
- F2 `test_background_target_reads_the_roster` asserts the real seam goes through `background_id` (RED with the old body). F3 regex `is running in the background \([0-9a-f]{4,}\)\.` (the bare "(" marker matched "…(PID 4242)."). F5 `cwd = session_cwd(J) or session_cwd(O)`. F6 `term_launch.open_terminal` resolves through `background_id` (External on an old row builds `--resume J`; provider failure = unchanged). F7 real-signal tests patch `THIN_DETACH_WAIT` to 15.
- Reverting: (c) reverts cleanly; (b) needs conflict resolution (`_swap_candidate` and `open_pty`'s call site were later touched by (c) and this commit).
- Known gap: an in-memory "space to reply" draft in the parked view dies with a taken-over pane.

### Live proofs for the review fixes (claude 2.1.318, :8799, scratch sessions)
- P1 real browser (claude-in-chrome), both renderers (xterm.js and grid): clicked the scratch rows A then B in the Control Room rail and "Resume": same tty, ONE terminal, the banner rendered in the dialog (screenshot) naming the displaced session, with a "See lineage" link. After a page reload, opening the displaced-to session from the Control Room is live (not "disconnected"; `ExtVT.ttySession(tty)` is the fg session, not the row's opener) - F1's repro. The Manage terminals dialog's kill of the switched row reached the server's busy confirm (not an ownership 409) and, confirmed, closed it (0 left), in both renderers. Not distinguished: whether the dialog used was the classic `ext_vt` manager or the Control Room's; both callers carry the fix.
- P2 returned view: park (Left), Enter returned to the conversation prompt, a typed unsent draft survived a takeover and was present on `claude attach <J>` afterwards (the job holds it). A takeover mid-generation (400 numbers) and mid-tool (`time.sleep(50)`, auto mode, no dialog) both let J's turn finish: tool_result recorded, ENDMARK/TOOLDONE present, no "[Request interrupted". Lost: only in-memory "space to reply" drafts of the parked view.
- Hazard noted: `mode:"new"` opens the AGENT VIEW (it lists the user's real sessions) on this config. Never type into a pane before its screen is confirmed; P2 gated every key on screen text.
