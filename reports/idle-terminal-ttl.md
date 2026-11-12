# Idle terminal TTL overrun

Branch `worktree-term-idle-ttl`, base `personal/main` @ 0aecc02.

## Contract (verbatim)

1. "terminals running more than the terminal ttl" (screenshots: Config > Terminal, Idle terminal TTL = 10 min, Max terminals = 10)
2. "diagnose the issue and build a technical plan and then do adversial review and address all the review in the technical plan, all on an opus agent"
3. "then implement the technical plan with /tracker-gap"
4. "once the fix landed, do an adversial review and fix them via an opus agent post that /tracker-push, if any conflict during push using /branch-sync"

| Clause | Verdict |
|---|---|
| 1. TTL overrun resolved | fixed in code; live only after `make serve` on 8790, which closes every open terminal, so the user restarts it |
| 2. Diagnosis, plan, adversarial review, reconciled plan (opus) | discharged (this report) |
| 3. Implemented via /tracker-gap | discharged: commits 601b8b5 and 65352dd (were a489710 and 7e88d1a before the rebase) |
| 4. Post-fix adversarial review and fixes (opus), /tracker-push, /branch-sync on conflict | review and fixes done; /branch-sync rebased onto personal/main a2d9263 with no conflicts; post-sync gate failure was a timing flake (see review section); shipped by /tracker-push from this commit, landed when `git merge-base --is-ancestor <this commit> personal/main` holds |

## Diagnosis

Line numbers are `aitracker/term_vt.py` at 0aecc02 unless another file is named. Measured 2026-11-06, 22:02 to 22:22 IST. All probes were read-only against live server PID 37905; scripts are in `/Users/pritammondal/.claude/jobs/925e866e/tmp/`.

### What the running server is

- **It runs HEAD.** The primary checkout's last pull is `0aecc02` at 10:47:10 on Nov 5, the source and `.pyc` mtimes are 10:47:10, and the server started at 10:47:10. `term_vt.py`, `config.py` and `providers/claude.py` are byte-identical (`cmp`) between the primary checkout and this worktree. The stale-server theory is ruled out.
- **Effective config (`GET /api/config`): `TERM_IDLE_TTL_MIN=10`, `LIVE_WINDOW=900`.** So `_session_live`'s window is `max(900, 600)` = **15 min**, not 10. A transcript written in the last 15 min is a by-design hold (`_session_live`, 3938, decision D1 in `docs/ttl-external-session-plan.md`).

### Root cause per terminal

Three separate defects hold or strand terminals. The biggest one is the body-rows rule.

| Terminal | State | What holds it | Evidence |
|---|---|---|---|
| **746c** (`claude`, overflow, thin client of daemon job d9bfc6d0) | Overrun. Transcript 55.8 min idle at 22:21, past the 15 min window | **`_note_activity` body-rows touch (1688).** It sits on the agents board, whose "Working" spinners are body rows. | Byte-identical traffic to c362: 49475 vs 49478 bytes over 55s, 30906 vs 30909 over 34s. `_claude_work_children` is `[]`, REPL 21143 has no work children, stream rate does not match it. Live screen not read (constraint). |
| **c362** (`claude --resume 147b…`, overflow) | Overrun. Process argv is now literally `claude agents` | **Same.** | `ps`: `73632 … /Users/pritammondal/.local/bin/claude agents`. Same traffic as above. Its job retired at 22:06:52 (`daemon.log`), and the pane stayed. Its work children are `[]`, REPL is 0. |
| **e40** (`claude`, folder, parent of the daemon) | By-design hold at capture; overrun by 22:21 (transcript 20.3 min idle) | **`_claude_busy` (3900), permanently.** Its Claude is the parent of `claude daemon run`, which sits in its own process group, so it counts as tool work forever. | `_claude_work_children(71855)` is `[71881]`. `ps`: `71881 ppid=71855 pgid=71881 … claude daemon run --origin transient --spawned-by {…"pid":71855}`. Traffic is 147 B/s (footer only), so the body rule is not what holds it. |
| **58b** (`/bin/zsh -l`, folder) | **Not held. Already dead, but listed.** | **`Pty.finish()` blocking `os.waitpid(pid, 0)` (1582)** on a child stuck in the kernel's exit state. `done` never becomes True. | `ps`: `92749 ?Es (zsh)`, `92950 ?E (2.1.319)`. The server has 5 ptmx fds for 6 rows and 58b has none, so `finish()` already closed its fd. `sample 37905` shows one thread at `os_waitpid` → `__wait4` for the whole sample (742/742), alongside 5 readers in `select` and the main thread. Its fresh transcript belongs to job 31cd62a0 in REPL 99480, which is unrelated to this row. |
| **381c** (`claude --resume 4af1…`, folder, parked on job 4405110a) | Transcript 27.9 min idle at 22:21 | Parked client on a churning view, so the same body rule, and possibly a real viewer. | `sessions/93756.json`: `kind:interactive, parkedJobId:4405110a`. The one long-lived stream matches 381c or 2a01 (below). |
| **d2d6** | Not an overrun | `_session_live` by design, transcript 0.3 to 4.5 min idle. Left the list at about 22:21; the cause was not observed. | `state.py` output. |

### The mechanism, reproduced on the real path

`_note_activity` assumes that a change above the footer band is real work. The agents board breaks that: it animates a spinner in a **body** row for every session Working **anywhere on the machine**. So any pane left on the board stays alive for as long as any session is working.

Real `claude agents` through the real `term_vt.spawn()` → `_reader()` → `_note_activity()`, no HTTP:

- `harness.py`: 37 touches in 40s. Rows 37, 38, 39 (the Working section) change every second. Band is 4 (footer correctly excluded), `_foreground_is_claude` True. About 900 B/s of steady traffic once the first paint is excluded, against 900 B/s live.
- `e2.py` with TTL 30s, code as shipped: **`done=False` after 75s, 68 touches.**
- `e2.py` with TTL 30s, plan's `_note_activity` monkeypatched in: **`done=True` after 30s, 0 touches, rc -9.**
- `e3.py`, a real local `claude --resume` on a scratch haiku session (torn down after): `sessions/<pid>.json` is `kind:interactive`. Touches were 13 in 15s during a turn and **0 in 20s when idle**. So the body rule is right for a local REPL and wrong only for clients.
- `e1.py`, a child that closes its tty fds and sleeps 25s: `fd closed at 0.1s, done at 25.1s`. This reproduces the `finish()` hang without needing a stuck kernel process.

### Ruled out

- **Viewers pinned, leaked stream, background SPA stream.** The only long-lived TCP connection in a 12 min watch (`conn.py`) is `:55799`, and it has a single request (1040 bytes in). `nettop` puts its output at 1947 then 1571 B/s. That matches 381c or 2a01 at about 1.36x (SSE base64), and it does not match 746c or c362 (about 1113 B/s) or e40 (about 198 B/s). All other connections lived under a second, and at 22:02 to 22:08 there were none. Both decrements are in `finally` (4105-4108, 4733-4737). `pt.viewers` itself was not read; this is inferred from TCP and byte rates.
- **Agent files feeding `session_last_active`.** The newest agent file is older than the transcript on all overrun terminals (746c 63.4 min, c362 79.8 min, 381c 115.8 min).
- **Daemon REPL work leg of `_session_live`.** `replkids=[]` for 746c, and REPL is 0 for c362 and 381c.
- **`touch()` elsewhere.** No `.touch()` call outside `term_vt.py`.
- **Grid vs xterm.** Both streams share `viewers`, and `_reader` always feeds the Screen.

### Docs vs code

The help text (`web/ext_cr_dialogs.js:1345`) says "never closes sooner than LIVE_WINDOW after its last write". That is true but incomplete: the code holds for `max(LIVE_WINDOW, TTL)`. Both the help text and README:98 also miss that screen activity counts. Neither says a Claude client's redraw is ignored, because today it is not.

## Technical plan

This is the first draft, before review. The reconciled plan below supersedes it.

1. `_note_activity`: a Claude foreground never counts as activity from screen changes. Rely on keystrokes, viewers, `_claude_busy` and `_session_live`.
2. `_claude_work_children`: exclude `claude daemon run`.
3. `Pty.finish`: bounded `waitpid`, then hand off to a daemon thread and set `done`.
4. Help text and README match the code.
5. Add `idle_s`, `viewers` and `last_hold` to the `/api/term/list` row.

## Adversarial review of the plan

Stance: the diagnosis and the draft are wrong. Each finding has defect, repro, direction, way and test, and was judged against the code.

**A1. Draft step 1 kills a local Claude mid-turn.**
- Defect: `_note_activity` (1688) with no body rule leaves only `_session_live`'s window (3956) protecting a local REPL's silent turn. The transcript is written at message end.
- Repro: TTL 5, LIVE_WINDOW 300, local `claude --resume X`, one 6 min thinking turn, no viewer. Actual: SIGKILL mid-turn. Expected: survives.
- Direction: keep the body rule for local REPLs, drop it only for clients. A client is safe to close because its conversation lives in a daemon job (`_swap_in`, 3410, already SIGTERMs them in production).
- Way: `providers/claude.py::repl_is_local(pid)` reads `sessions/<pid>.json`. E3 confirms `kind:interactive`; 22947, 73632 and 86769 have no file; 93756 has `parkedJobId`.
- Test: U3 and eval control.
- **Confirmed.**

**A2. `status == "busy"` as the real-work signal, instead of A1's split.**
- Defect it would add: stale busy. `sessions/93756.json` read `status:busy` for 21+ min while its job's `38229.json` read `idle`.
- Direction: do not use it. It would be a new forever-hold.
- **Overengineered fix, rejected.**

**A3. The band gate leaves a second forever path.**
- Defect: `band is not None and _foreground_is_claude` (1704) falls to raw `screen.v` when no input box is recognised. A client in a list-focused or dialog view has band None, so any redraw touches. `harness.py` saw band None during startup, and `_footer_anchor_band` needs a `─` rule directly above the prompt.
- Repro: fake Claude with a spinner, no rule row, fg True, no sessions file. Actual: never reaped. Expected: reaped at TTL.
- Direction: decide on the foreground, not the screen shape.
- Way: probe `_foreground_is_claude` whenever `v` changed. For a local REPL, `_body_rows_version` already handles band None with its floor.
- Test: U2, U4.
- **Confirmed.**

**A4. A3's fix forks `ps` on plain shells.**
- Defect: `test_plain_shell_activity_never_forks_ps` (test_term_vt:2072).
- Direction: an idle plain pty must not fork.
- Way: return early when `v` is unchanged, and take the first sample without a probe. A printing program pays one cached `ps` per `FG_CACHE_TTL` per pgid, the same as the existing `attached` poll.
- **Confirmed, fix narrowed.**

**A5. `_claude_busy`'s band gate now hides real work.**
- Defect: 3908 returns False on band None. Today a Claude in a dialog with a background shell is often kept alive only by accident, through the v-path that A3 removes.
- Repro: local Claude, permission dialog up, `run_in_background` server running, no viewer, transcript quiet. Actual after A3: reaped. Expected: kept (README: "a `run_in_background` server keeps it open").
- Direction: let a labelled pane reach the probe; a plain shell still must not fork (`test_plain_shell_reap_never_forks_ps`).
- Way: `if (band is None and not _pty_session_ids(pt)) or not _foreground_is_claude(pt.fd): return False`.
- Test: U8.
- **Confirmed.**

**A6. Reaping e40 kills the daemon and every job on the machine.**
- Checked: `Pty.kill` (1539) signals only the foreground group and the shell's group. 71881 has its own pgid, is a session leader (`Ss`) and has no controlling tty, so neither the signal nor the hangup reaches it. `daemon.log` shows causes `idle_exit`, `upgrade`, `signal`, `shutdown_op`, none tied to a spawner, with uptimes of 164771s across sessions.
- Not proven by experiment: I did not SIGKILL a real spawner, because that risks the user's jobs.
- **Overstated. Residual risk named in the plan, with a fallback.**

**A7. `done=True` while the process survives hides it.**
- Defect: after step 3, a 58b-style row vanishes while the process is still there.
- Direction: acceptable, since it is already unkillable, the row was unclosable and it blocks `_folder_pty` (1849, `not p.done`). Add one `print`.
- Check: `_resume_backstop`'s `died` (2752) treats rc None as not failed. A refused resume exits in about 2.6s, inside the wait. `_retry_with_fork` assigns `pt.pid` afterwards and `finish` uses a local `pid`.
- **Confirmed, narrow.**

**A8. Tests can pass without the live path.**
- Defect: all unit tests mock `_foreground_is_claude` with a python child. A fix that misclassifies the real board would still go green.
- Direction: add a real-binary acceptance step. No mocks added to production.
- Way: rerun `e2.py` (`H_FIX=0`, since the fix is then in the code) and `e3.py`.
- **Confirmed.**

**A9. A hidden tab holding a stream pins a pane forever.**
- README says "an open viewer keeps it alive". Live evidence shows at most one stream, on a non-overrun pane. No `visibilitychange` handling in `ext_vt.js`.
- **Overstated: by design.** No change; surfaced as a decision.

**A10. `_claude_busy` touch means an overshoot of up to one extra TTL after work ends.**
- Bounded, and a test pins the once-per-TTL probe rate (`test_busy_probe_runs_once_per_ttl_not_every_second`).
- **Overstated. No change.** The help text says "while", which stays true within that bound.

**A11. A launcher whose comm is not `claude` fails the foreground gate, so its footer touches forever.**
- Already a listed known gap in `_session_live`, and the README's launcher contract is `exec claude`. No live instance.
- **False alarm for this fix. No change.**

**A12. A plain shell with an animated prompt, or `top`, never reaps.**
- `test_progress_under_rule_prompt_holds_off_reap` pins "non-Claude output is activity". No live instance.
- **Overstated. No change; known gap.**

**A13. A transient `ps` failure at reap time kills a local Claude with work.**
- `_foreground_is_claude` has a 1s timeout, and this machine swaps. It is pre-existing and not widened for local REPLs, and clients are safe to close.
- **Overstated. No change.**

**A14. Overflow, resumed, parked, folder paths.**
- All share `_reader`. Thin (746c), exec'd board (c362), parked (381c), attach (d2d6): only a local unparked REPL has a qualifying file. Spares never appear in `PTYS` (no `spare` in `term_vt.py`).
- `_retry_with_fork` replaces `pt.screen`, so `v` may fall; `_act_raw` only compares for equality, which is harmless.
- **False alarm.**

**A15. Existing tests encode the old rule.**
- `test_body_output_holds_off_reap` needs `_repl_is_local=True`. The full-key-set test (test_term_vt:1270) needs the new keys.
- **Confirmed.**

## Reconciled plan

### Verdicts

| # | Finding | Verdict | Action |
|---|---|---|---|
| A1 | No body rule kills a local mid-turn | confirmed | Keep the rule for local REPLs |
| A2 | `status==busy` signal | overengineered fix | Rejected, stale on parked panes |
| A3 | Band None leaves v-path touching | confirmed | Foreground-first |
| A4 | Foreground-first forks on plain shells | confirmed | Early return, first sample unprobed |
| A5 | `_claude_busy` band gate hides work | confirmed | Labelled panes reach the probe |
| A6 | Reaping e40 kills the daemon | overstated | Residual risk, fallback below |
| A7 | Survivor hidden after finish | confirmed, narrow | One `print` |
| A8 | Tests miss the live path | confirmed | Real-binary acceptance |
| A9 | Hidden tab viewer | overstated | By design, user decision |
| A10 | One-TTL overshoot | overstated | None |
| A11 | Launcher comm | false alarm | None |
| A12 | Animated prompt | overstated | None |
| A13 | `ps` failure | overstated | None |
| A14 | Other pane kinds | false alarm | None |
| A15 | Tests encode old rule | confirmed | Update two tests |

### What real work stays protected

- A local REPL mid-turn: body rows still touch.
- Tool or background shells of the pane's Claude, including in a dialog: `_claude_busy`.
- A session whose transcript or agent files were written within `max(LIVE_WINDOW, TTL)`, by anyone: `_session_live`.
- A daemon REPL with tool work: `_session_live`.
- A non-Claude program producing output: any screen change.
- An attached viewer, and keystrokes.

What stops counting: redraws from a Claude **client** (thin, `claude agents`, `claude attach`, parked), and footer-only redraws from a local REPL when no input box is recognised, plus `claude daemon run` as "work". A closed client does not stop its job.

### Changes (sequence: 1 and 2 are independent and smallest; 3 needs 4 in the same commit)

**1. `aitracker/term_vt.py`: `Pty.finish` (1571). Fixes 58b.**

Add near `SESSION_LIVE_RECHECK` (1260):

```python
FINISH_REAP_WAIT = 5.0   # s finish() waits for the child after closing the pty; past this the row is released
```

Replace the `if self.pid > 0:` block in `finish()`:

```python
if self.pid > 0:
    pid, end = self.pid, time.time() + FINISH_REAP_WAIT
    while True:
        try:
            got, status = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            break
        if got:
            self.rc = -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)
            break
        if time.time() >= end:      # stuck in the kernel's exit, or outlived its tty: never pin the row on it
            print("[ai-tracker] terminal %s: pid %d still not reaped %gs after its pty closed" % (self.id, pid, FINISH_REAP_WAIT))
            threading.Thread(target=_late_reap, args=(pid,), daemon=True).start()
            break
        time.sleep(0.05)
```

Add a module-level function after `_kill_group`:

```python
def _late_reap(pid):
    """finish() gave up waiting: keep the one waitpid, on a thread of its own, so it never becomes a zombie."""
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass
```

Update the `finish` docstring: bounded wait, still exactly one waitpid per child.

**2. `aitracker/term_vt.py`: `_claude_work_children` (3871). Fixes e40.**

Change the format to `"pid=,ppid=,pgid=,args="`. Parse with `parts = line.split(None, 3)`, `if len(parts) < 3: continue`, `pid, ppid, pgid = (int(x) for x in parts[:3])`. Three-field test fixtures stay valid. Condition: `ppid == claude_pid and pgid != claude_pid and not _is_claude_daemon(parts[3] if len(parts) > 3 else "")`.

```python
def _is_claude_daemon(args):
    """The background-session supervisor a Claude may have spawned: long-lived in its own group, but not this Claude's tool work."""
    toks = args.split(None, 3)
    return len(toks) >= 3 and toks[1:3] == ["daemon", "run"] and "claude" in toks[0]
```

Do not exclude anything else: long-lived background shells stay "work" (decision D3). This also fixes `_swap_candidate`'s strict check (3395). `args` must never be logged.

**3. `aitracker/providers/claude.py`: add after `parked_job_id` (622).** No fork; `config.LIVE_SESSIONS_DIR` late-bound; never raises.

```python
def repl_is_local(pid):
    """True when process `pid` hosts its conversation itself: LIVE_SESSIONS_DIR/<pid>.json says kind
    "interactive" and no parkedJobId. A thin client, `claude attach` and `claude agents` have no file,
    and a parked TUI has parkedJobId: their work lives in a daemon job, so closing them stops nothing.
    An unreadable file (mid-write) answers True: one extra touch beats closing a working Claude."""
    try:
        with open(os.path.join(config.LIVE_SESSIONS_DIR, "%d.json" % pid)) as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return False
    except Exception:
        return True
    return isinstance(d, dict) and d.get("kind") == "interactive" and not d.get("parkedJobId")
```

**4. `aitracker/term_vt.py`: `_note_activity` (1688). Fixes 746c, c362, 381c, and the band-None path.**

Add the field beside `_act_v` (1509): `self._act_raw = None   # last screen.v _note_activity sampled (reader-only)`.

```python
def _repl_is_local(pt):
    """Does the pty's foreground Claude host its conversation here? True when there is no provider
    (the flattened bundle), which keeps the body-rows rule. A dead pty is False."""
    c = _provider()
    if c is None:
        return True
    try:
        return c.repl_is_local(os.tcgetpgrp(pt.fd))
    except OSError:
        return False


def _note_activity(pt, now):
    """Idle clock: touch `pt` only when the screen changed in a way that means work. Any change for
    a non-Claude program. For a Claude that hosts its own conversation, a change above the footer
    band (`_body_rows_version`). For a Claude CLIENT (thin, `claude agents`, `claude attach`,
    parked), never: the agents board animates a body row for every session working anywhere on the
    machine, and closing a client does not stop its job. Sampled at most once a second; `_reader`
    calls this every loop. No `ps` unless the screen changed, and none on the first sample."""
    if now - pt._act_t < 1.0:
        return
    pt._act_t = now
    with pt.lock:
        raw = pt.screen.v
    if raw == pt._act_raw:
        return
    first, pt._act_raw = pt._act_raw is None, raw
    v = raw
    if not first and _foreground_is_claude(pt.fd):   # outside pt.lock
        if not _repl_is_local(pt):
            return
        v = _body_rows_version(pt)                   # takes pt.lock itself
    if v != pt._act_v:
        pt.touch()                       # touch BEFORE publishing _act_v: a waiter on _act_v then
        pt._act_v = v                    # never has its backdated last_active overwritten
```

**5. `aitracker/term_vt.py`: `_claude_busy` (3900).**

```python
if (band is None and not _pty_session_ids(pt)) or not _foreground_is_claude(pt.fd):   # probe outside pt.lock
    return False
```

Update the comment: a plain shell has no label, so it still never forks at reap.

**6. `aitracker/term_vt.py`: observability.** Earned: this diagnosis needed `lsof`, `nettop`, `sample` and a harness because the row exposes nothing, and these prove the fix after restart with one `curl`.

- `Pty.__init__`: `self.last_hold = ""   # reader-only: what the idle reap last deferred on: "busy", "live" or ""`.
- `_reader` (1733-1736): set `pt.last_hold = "busy"` after `pt.touch()`, and `pt.last_hold = "live"` after `pt.live_hold = …`.
- `_live_list` (2129): add `now = time.time()` and, per row, `"idle_s": int(now - p.last_active), "viewers": p.viewers, "last_hold": p.last_hold`. One sentence in its docstring. No SPA change, and nothing re-derived in JS.

**7. Docs (must match the code).**

- `_reader` docstring, and `Pty.last_active`'s comment (1508): add "or a screen change `_note_activity` counts".
- `_session_live` known gaps: leave the permission-dialog line.
- `aitracker/web/ext_cr_dialogs.js:1345`, help text becomes: `A terminal nobody is watching or typing into is closed after this many minutes. The slider covers 5–240; env TRACKER_TERM_IDLE_TTL_MIN or config.json accept 1–1440. A screen that only redraws does not count: a Claude client or the agents board closes even while its spinners move. A Claude is kept open while its tool or background shells run, and while its transcript was written within the larger of LIVE_WINDOW and this TTL, whether by another terminal or by this pane\'s own Claude.`
- `README.md:98`: after "an open viewer keeps it alive;" insert "a Claude client (thin, `claude attach`, parked, or the agents board) closes even while its spinners move, because its job lives in the daemon and keeps running;". Replace "so a Claude pane never closes sooner than `LIVE_WINDOW` after its last write" with "so a Claude pane stays open until `max(LIVE_WINDOW, TTL)` after its last write". Add: "A process stuck exiting no longer pins its row: the row is released after 5s."

### Tests (each RED on current code unless marked)

All in `tests/test_term_vt.py::TestIdleTimeout` (1970) unless named. Use `mock.patch.object(term_vt, "_repl_is_local", return_value=…, create=True)`, so the RED run fails on behaviour rather than on a missing attribute.

- **U1 `test_client_body_redraw_does_not_hold_off_reap`**: fg True, local False, `self._claude(body=True)`, TTL 0.05, `_drain(pt, 12).done`. RED: held.
- **U2 `test_client_without_input_box_is_reaped`**: new child constant, spinner in a body row, no rule row, band None; fg True, local False. RED: v-path.
- **U3 `test_body_output_holds_off_reap`** (existing): add local True. Stays green, the real-work guard.
- **U4 `test_local_dialog_footer_redraw_does_not_hold_off_reap`**: child with band None redrawing only the bottom rows; fg True, local True; reaped. RED: v-path. Also add local True to the existing `test_claude_footer_redraw_does_not_hold_off_reap`.
- **U5 `test_plain_shell_activity_never_forks_ps`, `test_progress_under_rule_prompt_holds_off_reap`, `test_plain_shell_reap_never_forks_ps`**: unchanged, must stay green.
- **U6 `TestReplIsLocal`** (`tests/test_folder_swap_parked.py`, using its `LIVE_SESSIONS_DIR` patch): missing False; interactive True; interactive with `parkedJobId` False; `kind:bg` False; garbage True; non-dict False.
- **U7 `test_claude_work_children_skips_the_daemon`**: stdout `" 100 1 100 claude\n 200 100 200 /x/bin/claude daemon run --origin transient\n 201 100 201 /bin/zsh -c sleep 9\n 202 100 100 node mcp\n"`, expect `[201]`. Also `docker daemon run` in its own group stays work. RED: `[200, 201]`.
- **U8 `test_work_in_a_dialog_keeps_labelled_pane`**: no-band child, `pt.mode, pt.session = "resume", SID`, fg True, `_claude_work_children=[1]`, TTL 0.05, not done after 6s. RED: reaped.
- **U9 `test_finish_does_not_pin_on_child_that_outlives_pty`**: child `import os,time; [os.close(i) for i in (0,1,2)]; time.sleep(20)`; `FINISH_REAP_WAIT = 0.3`; `_wait_for(lambda: pt.done, 3)`; `rc is None`; `addCleanup` kills the pid. RED: done at 20s.
- **U10 `test_finish_still_records_rc`**: `sh -c 'exit 3'` gives rc 3; a `kill()`ed `sleep` gives -9. Green before and after.
- **U11 `test_list_returns_live_terminals_with_full_key_set`** (1255): add `idle_s, viewers, last_hold`. Add `last_hold` "busy" and "live" assertions via `_live_list` in `test_claude_with_background_work_is_not_reaped` and `test_U9_hold_does_not_touch_idle_clock`.
- **Eval `test_client_pane_reaped_local_repl_kept`** (`tests/test_integration.py::TestTermIdleTtlEndToEnd`, next to 1609, same `_listed`, same save/restore plus `LIVE_SESSIONS_DIR`): register two fake-Claude ptys with `_CLAUDE_LAYOUT_CHILD % {"body": "True"}` in `PTYS`, `_foreground_is_claude` mocked True, TTL 0.02. One has `<pid>.json` with `kind:interactive`. Over the real `/api/term/list`: the client row disappears within 8s, the local row stays listed with `idle_s` under 3. Both killed and popped in `finally`. RED: client stays.

Run one module per process, prefixed `unset TRACKER_AUTH;`. The full gate is OOM-prone; memory has the details.

### Acceptance on the real binary (A8)

After the code lands, from `/tmp`, nothing to do with 8790:

- `H_FIX=0 python3 /Users/pritammondal/.claude/jobs/925e866e/tmp/e2.py`: expect `done=True` at about 30s, touches 0. (`H_FIX=0` runs the code as committed.)
- `python3 …/tmp/e1.py`: expect done at about 5s, not 25s.
- For `e3.py`: first make a scratch session (`cd /tmp/tt-scratch-925; claude -p "say ok" --model haiku --output-format json`, read the id), then run it. Expect touches > 0 in `turn`, 0 in `idle-after`. Then `rm -rf ~/.claude/projects/-private-tmp-tt-scratch-925 /tmp/tt-scratch-925`.
- Revert proof: comment out the `_repl_is_local` return, rerun U1 (RED), restore with a scoped Edit. No `git stash`.

### Restart

Python and `web/` both change, so `make serve` is needed. **Restarting 8790 closes every live terminal**, so leave that to the user, not the implementer. After it, `curl -s localhost:8790/api/term/list` shows `idle_s` climbing on a board pane, which then closes at 10 min unwatched. `58b`'s stuck processes stay in `ps` until the kernel lets them go.

### Risky spot and fallback

- **`repl_is_local` depends on Claude's `sessions/<pid>.json` shape.** If a CLI renames `kind`, or a local REPL writes no file, every local Claude reads as a client. Consequence: a silent turn is protected only by the window, not the body rule. Fallback: make `_repl_is_local` return True, a one-line change back to today's behaviour.
- **`_is_claude_daemon` lets e40-type panes close (A6).** If the daemon is ever seen dying with its spawner after this lands, remove only that exclusion.

### Decisions the user may want to overrule

1. **A pane left on the agents board or on a thin client closes at TTL, spinners or not.** The job keeps running and the pane can be reopened. This is the requested behaviour, but it is a change if anyone keeps a board pane as a dashboard.
2. **Keep `max(LIVE_WINDOW, TTL)`.** With `LIVE_WINDOW=900`, TTL=10, a Claude pane stays 15 min after its last write, not 10, and that overrun will still look like one. It is D1 from `docs/ttl-external-session-plan.md`, so I did not change it; docs now say so. Lowering Live window to 10 min gives exactly 10, but it changes what "live" means across the dashboard.
3. **A local Claude waiting on a permission prompt closes after the window.** Already listed as a known gap; removing the v-path makes it true where footer redraws may have hidden it. Its transcript survives and it can be resumed.
4. **A hidden browser tab with an open terminal still counts as watching.** Left as documented.

### Not verified

- The live screens of 746c and 381c (forbidden routes). 746c on the board is inferred from byte-identical traffic with c362, whose argv is `claude agents`.
- `pt.viewers` and `pt.last_active` in the live process. Inferred from TCP, byte rates and thread stacks. Stream `:55799` is on 381c or 2a01; byte rates do not separate those two.
- Why the kernel holds 92749 and 92950 in `E`, and who issued that kill (idle reap, `close_pty` or a swap). `_folder_pty` returning this undead row (1849) would force later opens in that folder into overflow, which fits c362 and 2a01 sharing its cwd, but the timing was not proven.
- Daemon survival when its spawner is SIGKILLed (A6): argued from process groups and logs, not tested.
- Whether a real dialog's footer actually redraws (A3, A5, decision 3).

## Main-thread reconciliation

Plan accepted as written, verdicts kept, with one change.

- **A6 reclassified from "overstated" to open risk.** Daemon survival on spawner SIGKILL is argued, not tested, and `claude daemon run --origin transient` hosts background sessions machine-wide, so a wrong answer costs far more than this verdict implies. The same exposure already exists through a manual close of such a pane, so this does not block implementation. The post-fix review must settle it from `daemon.log` history (read-only), and the plan's fallback (remove the `_is_claude_daemon` exclusion) applies if the daemon does die.
- **Claude-only `_note_activity` branch is not a seam violation (conventions rule 4).** Non-Claude providers' panes take the any-screen-change path unchanged, and the board spinner is Claude-specific.
- **Restart stays with the user.** Restarting 8790 closes every live terminal.

## Implementation evidence

Changes 1 to 7 applied as planned; no deviation of substance. Tests written first and run against unfixed code.

RED before the source change (with `create=True` mocks, so they fail on behaviour):
- U1 `test_client_body_redraw_does_not_hold_off_reap`: FAIL (held open).
- U2 `test_client_without_input_box_is_reaped`: FAIL.
- U4 `test_local_dialog_footer_redraw_does_not_hold_off_reap`: FAIL.
- U6 `TestReplIsLocal.test_cases`: ERROR (no `repl_is_local`).
- U7 `test_claude_work_children_skips_the_daemon`: FAIL.
- U8 `test_work_in_a_dialog_keeps_labelled_pane`: FAIL (reaped). First draft used a redrawing child and passed for the wrong reason (v-path held it); the child is now static (`_NO_BAND_STATIC_CHILD`).
- U9 `test_finish_does_not_pin_on_child_that_outlives_pty`: FAIL (still pinned at 3s).
- U11: `test_list_returns_live_terminals_with_full_key_set` FAIL; `test_claude_with_background_work_is_not_reaped` ERROR (no `last_hold`); `test_U9_hold_does_not_touch_idle_clock` ERROR.
- Eval `test_client_pane_reaped_local_repl_kept`: FAIL (client stays listed).
- Green before and after: U3 (`test_body_output_holds_off_reap`, local True), U5 trio, U10 `test_finish_still_records_rc`.

GREEN after: `tests.test_term_vt` 370 tests OK (195s); `tests.test_folder_swap_parked` 19 OK; `tests.test_integration.TestTermIdleTtlEndToEnd` 10 OK. Run one module per process.

Revert proof: commenting out the `_repl_is_local` return in `_note_activity` turns U1 RED again ("a Claude client's body redraws held the pane open"); restored by scoped Edit, no `REVERT` markers left.

Real-binary acceptance (A8), from /tmp, nothing on 8790:
- e2 (`H_FIX=0`, real `claude agents`, TTL 0.5 min): `done=True after 30s touches=0 rc=-9`.
- e1 (child outliving its pty): `done at 5.1s rc None`, with the "still not reaped 5s" line (was 25s).
- e3 (scratch haiku session, local REPL): `turn` touches 7 in 15s; `idle-after` touches 0 in 20s. sessions/<pid>.json showed `kind: interactive, parkedJobId: None`. Scratch session and `/tmp/tt-scratch-925` removed.

Not verified here: restart of 8790 (left to the user); A6 daemon survival (post-fix review).

## Post-fix adversarial review

Stance: the implementation report on a489710 is false. Probes are in `/Users/pritammondal/.claude/jobs/925e866e/tmp/` (`r1` to `r13`). The installed binary is 2.1.319; its JS was read with `r2` to `r10`. The live daemon and panes were only read, never signalled. Fixes are in the commit that adds this section.

### A6: the daemon survives its spawner. Exclusion kept.

Three independent lines of evidence:

1. **It happened during this review.** At 22:59:07 IST (17:29:07Z) somebody restarted 8790 from `ttys000`; this review did not. The new server is PID 38371. Every old pane went down with its pty, including 71855, the Claude that spawned the daemon. Afterwards:
   - `ps` shows `71881 PPID=1 PGID=71881 ?? Ss`, elapsed 06:48:27.
   - `daemon.log` keeps working after the death: `17:31:52Z bg retire 54e8d58b`, `17:31:53Z bg settled`.
   - 11 `bg-pty-host` workers were still alive, and jobs 99480 and 99644 kept running.
2. **History.** A transcript from 2026-11-03 captured `35947 PPID=1 … claude daemon run --origin transient --spawned-by {"label":"claude --bg"…` at age 00:23. `daemon.log` shows that daemon hosting job 309a7af3 for 9 more minutes, and it exited only with `idle 5s with no clients`, `cause=idle_exit, uptime=538s`, after the job was stopped.
3. **Mechanism.**
   - `os.getsid(71881)` was 71881, so the daemon has its own session. Its tty was `??` and TPGID 0, so it has no controlling terminal and no hangup can reach it.
   - Its stdio is `/dev/null` plus a stderr file (`lsof`), so there is no pipe to the parent.
   - `Pty.kill` signals only the pty's foreground group and the shell's group.
   - In the binary, `spawnedBy` is only stored in `daemon.lock`, shown in status text and sent in telemetry. Nothing checks its liveness.
   - `armOrphanCheck` returns early unless `process.stdin.isTTY`, and the daemon's stdin is `/dev/null`.
   - The transient daemon exits only when `leaseCount + liveHandleCount == 0`.

**Verdict: safe.** The fallback was not applied. e40-type panes now close at TTL, and the daemon reparents to launchd and keeps its jobs.

Limit: the spawner deaths observed were a pty hangup and a normal exit, not a SIGKILL of a real spawner. The kernel treats a child the same for any parent death, and the code has no liveness watch, so I do not count this as a gap.

### Live path: `tcgetpgrp` against `sessions/<pid>.json`

Real binary through the real `term_vt.spawn`/`_reader`, on a scratch haiku session (torn down):

| Launch | pg vs pid in file | fg Claude | `_repl_is_local` | Touches in a turn |
|---|---|---|---|---|
| `zsh -l` then `claude --resume` (`r12` B) | 59813 = 59813 | True | True | 15 in 15s, 1 when idle |
| `claude -p` typed in `zsh -l` (`r13`) | 67859 = 67859 | True | True (`kind: interactive`) | 2 in 10s |
| exec'd `claude --resume` (e3, earlier) | equal | True | True | 7 in 15s |
| `sh -c 'claude …; echo bye'`, no exec (`r12` E) | 60320 is `/bin/sh` | False | not asked | 11 in 15s: the any-change path, safe side |
| **inherited `CLAUDE_CODE_CHILD_SESSION`, before the fix** (`r12` C) | **no file** | True | **False** | **0 in 15s, on a working local REPL** |
| same env after the fix, plus other CLAUDE* vars (`r13`) | 64869 = 64869 | True | True | 5 in 15s, no "Transcript saving is off" |
| real `claude agents`, TTL 30s (e2 rerun) | no file | True | False | `done=True` at 30s, touches 0, rc -9 |

Read-only, before the restart: `claude`, `claude agents` and `claude attach` panes had no file (22947, 73632, 12322). The OpenRouter launcher `claude-or` ends in `exec "$claude_bin"`, so its pid is the Claude's pid.

### Findings

| # | Finding | Verdict | Action |
|---|---|---|---|
| P1 | Inherited child-session marker: a working local REPL reads as a client | **confirmed** | Fixed |
| P2 | No test tells `tcgetpgrp` from `pt.pid` | confirmed | Test added |
| P3 | Eval test and U9 have load-sensitive bounds | confirmed | Widened |
| P4 | `test_plain_shell_activity_never_forks_ps` docstring is false; the `ps` rate is untested | confirmed | Docstring and test |
| P5 | `create=True` left on the new mocks; `__main__` guard above `TestReplIsLocal` | confirmed, small | Removed and moved |
| P6 | Help text "a screen that only redraws does not count" contradicts the local-Claude rule | confirmed, small | Reworded |
| R1 | A local REPL's pgrp differs from its file pid in real launches | false alarm | Table above |
| R2 | Wrapper that does not exec | overstated | Safe side unless the wrapper's own comm is `claude`; no instance. Known gap |
| R3 | `CLAUDE_CONFIG_DIR` elsewhere puts the file out of reach | overstated | Not set on this machine; the tracker only reads `~/.claude`. Known gap |
| R4 | Other registration gates: diskless, teammate agent id, a failed write | overstated | None reach a pane on this path. Named risk, one-line fallback in the plan |
| R5 | Local Claude between file rewrites | false alarm | A miss costs one 1 Hz sample; unreadable answers True |
| R6 | Long silent turn, compaction | false alarm | The spinner is in a body row: 15 touches in 15s |
| R7 | `/resume` and other idle local screens | overstated | No work is running; this is decision 3 |
| R8 | A pane in a swap | false alarm | `_swap_in` touches first; shortest TTL is 1 min |
| R9 | A client whose only output is progress | by design | Decision 1 |
| R10 | `claude update`, `remote-control` and similar have no file, so their output no longer counts | overstated | Silent ones were already reaped. Known gap |
| R11 | Unlabelled local REPL in a dialog with a background shell | overstated | `_claude_busy` still answers False, as it did before the commit for a static dialog. Known gap |
| R12 | `ps` or `open` stalls the reader | overstated | `ps` has a 1s timeout and a 5s cache, one per pane per 5s (now tested); `open` is a local regular file |
| R13 | Still overruns: window, one-TTL overshoot, viewer, labelled client whose job keeps writing | by design | Documented |
| R14 | `finish()` | false alarm | See below |
| R15 | Row released at 5s misleads | overstated | `close_pty` still needs `os.kill(pid, 0)` to raise, so `confirmed` stays false. A healthy child that closed its tty (`exec nohup job`) loses its row and keeps running, and the print names it; killing it would be worse |
| R16 | New list keys, tunnel, bundle | false alarm | See below |
| R17 | **Pre-existing, found here:** the idle clock is wall time, so a sleeping laptop wakes with every pane past TTL | not fixed: pre-existing, not widened by this commit, and wider than this contract | Decision for the user |

**P1 detail.**
- Defect: `term_vt.py::_fork_child` passes the server's environment to panes. `CLAUDE_CODE_CHILD_SESSION` is set in every Claude Bash tool (present in this agent's env). The memory note `tracker-server-lifecycle` tells agents to relaunch 8790 detached, so this path is real.
- Binary: `a_()` is `!diskless && no agent id && !R_t()`, and `R_t` is true when that marker is set in an interactive run. Registration then returns false: no `sessions/<pid>.json`, and the screen shows `Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION marker`.
- Repro: `r12` C. Actual: `_repl_is_local` False, 0 touches in a turn. With no transcript, `_session_live` cannot protect it either, so it is closed at TTL mid-turn. Expected: local, touched.
- Direction: remove only that marker from the pane's environment. Do not change `repl_is_local`, and do not strip other CLAUDE* vars.
- Way: one `os.environ.pop` in `_fork_child`. This also fixes the lost transcripts of such panes.
- Test: `test_pane_does_not_inherit_the_child_session_marker`.
- The current 8790 (from a terminal) has no CLAUDE* keys, so nothing is broken right now.

**P2.** Every unit and eval test used a dedicated pty, where pid equals pgid. `c.repl_is_local(pt.pid)` passed them all and would read every local Claude in a folder shell as a client. Added `test_repl_is_local_asks_the_foreground_group_not_the_shell`, with a real foreground job in its own group.

**P3.** The eval test ran at TTL 1.2s, with a 1 Hz sampler and a python child, so one stall on a loaded machine would reap `local`. It is now 6s, with a 20s budget. U9's 3s bound is now 10s, still under the child's 20s. Its cleanup now uses `_kill_group`, which never raises.

**P4.** The test's child is a silent `sleep`, so it says nothing about activity. A4's claim of one `ps` per `FG_CACHE_TTL` had no test. Added `test_printing_program_forks_ps_at_most_once_per_cache_ttl`.

**R14, `finish()`.**
- Exactly one successful `waitpid`: the polling loop or `_late_reap`, on a local `pid`, so `_retry_with_fork` reassigning `pt.pid` is safe.
- The rc mapping is unchanged.
- rc stays None only past the wait, and `_resume_backstop` treats None as not failed. A refused resume exits inside the wait.
- `_folder_pty` opening a new shell past a stuck row is the intended fix.
- `_reap`, `_live_count` and `_swap_in` only want the row gone.
- A `print` failing on a closed stdout during a stuck-child give-up would skip `done`. That needs two rare events together, so no change.

**R16.**
- `idle_s`, `viewers` and `last_hold` are additive, and nothing in `web/` reads them.
- `/api/term/*` is outside the read-only tunnel allow-list and behind `term_gate.guard`. The numbers are harmless where the terminal itself is already reachable.
- `scripts/bundle.py` writes and parses. `term_vt` is not in the bundle (`_repl_is_local` is absent, `repl_is_local` is present and unused), so `_provider()` returning None cannot happen on the bundled path.

**R17 detail, for the user.** `_reader` compares `time.time()` with `last_active`, and wall time includes sleep. This machine slept repeatedly during this review (`pmset -g log`), and two test runs failed on wall-clock `_drain` bounds until sleep was held off with `caffeinate`. They were green once it was: 52 tests OK, no code change. From the code, not tested: after a sleep longer than TTL, the first loop reaps any viewer-less pane that has no tool work and no recent transcript. That includes a local REPL frozen mid-turn. Moving the idle clock to a sleep-excluding source touches every `last_active` user, so it was left out.

### Proof

- RED with each fix reverted by scoped Edit, then restored (no `REVERT-PROOF` left):
  - `test_pane_does_not_inherit_the_child_session_marker`: `'marker=[] cc=[1]' not found in 'marker=[1] cc=[1]'`.
  - `test_repl_is_local_asks_the_foreground_group_not_the_shell` with `pt.pid`: `True is not false : the shell's file answered for its job`.
- GREEN: `tests.test_term_vt.TestIdleTimeout` + `tests.test_folder_swap_parked` + `tests.test_integration.TestTermIdleTtlEndToEnd`: 52 tests OK (sleep held off).
- Real binary on the final code: e2 `done=True after 30s touches=0 rc=-9`; e1 `done at 5.2s rc None`; `r13` as in the table. Scratch session, its transcript folder and `/tmp/tt-scratch-925r` were removed; roster has no entry for it.

### Not verified

- A SIGKILL of a real spawner (see A6). Hangup and normal exit were observed.
- `_foreground_is_claude` on a real `claude attach`: inferred from `claude agents`, which has the same argv shape and is proven by e2. The pane was gone after the restart.
- A real parked pane through `_note_activity`: file shape from the diagnosis only.
- A real run of the OpenRouter launcher: script read only; it is not configured here.
- **The fix is not live.** 8790 was restarted at 22:59 from the primary checkout, which does not contain this branch. The panes diagnosed above no longer exist. Push and restart remain.

**Gate flake: `test_inject_footer_quiet.test_body_redraw_still_blocks_inject` (not a regression).** One failure in a full gate after the rebase (`inject()` returned ok against a body redraw). Inject's quiescence (`_wait_for_quiet`, term_vt.py ~4531-4545) calls `_body_rows_version(pt)` directly and never reads `_act_v` or `last_active`, so `_note_activity` cannot affect it; the test's child is a plain python script, not a Claude foreground, so the new client rule is never reached. Inject's behaviour is unchanged for every pane, clients included. The test is timing-bound: the child redraws every 0.4 s and `INJECT_QUIET_WINDOW` is 1.5 s, so a >1.1 s scheduler stall (load average 20-32 while measured) lets inject see a quiet window. Isolated runs of the single test: HEAD 19 pass / 1 fail of 20 (module run: 1 of 5 modules runs failed), base `personal/main` 20 pass / 0 fail of 20 under similar load. Base's 0 of 20 does not distinguish 1-in-20 from 0, and no code on the path changed, so nothing was edited. Assertion left as is.
