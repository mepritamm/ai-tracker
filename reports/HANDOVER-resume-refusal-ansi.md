# Resume terminal — refusal detection, readiness, port move

Branch: `worktree-resume-refusal-ansi` (worktree `.claude/worktrees/resume-refusal-ansi`)
Opened: 2026-08-25. Session ran unattended under `/head-out`.

## The contract (verbatim, from the /head-out question round)

> **Q: Where should the "wait until the terminal is really alive" live?**
> A: **Client waits on a ready signal (Recommended)** — POST /api/term/pty returns immediately as it
> does today, but the response gains a `starting` state and the screen stream emits a `ready` frame
> once the child is past the refusal/retry and painting real UI. The modal shows 'starting…' instead
> of a bare cursor until then.
>
> **Q: What should the pane show during that refusal→fork window?**
> A: **Hide the refusal, show 'starting…' (Recommended)** — suppress the CLI's refusal text from the
> pane entirely; show a starting/spinner state, then the forked session with the existing
> `[ai-tracker] note: … this is a COPY under a new session id` line.
>
> **Q: Should I restart your live dashboard on :8787 to deploy the fix?**
> A: **"restart the live dashboard but on 8790 not on 8787, move the port across the entire app to
> 8790 rather than 8787"**
>
> **Q: How far should /tracker-push go while you're out?**
> A: **"Push + PR + merge"**

Follow-up instruction, same session:
> "fix the issue after fixing the full suite failure. treat this session as an orchestrator run
> multiple agents with cheaper models as per Claude.md"

## Clause-by-clause verdict

| # | Clause | Status |
|---|--------|--------|
| 1 | Fix full-suite failure | **DISCHARGED** — was stale `.pyc`, not a regression. 790 tests OK. |
| 2 | Bug A: refusal never matched (ANSI) | **DISCHARGED** — see below. |
| 3 | Bug B: backstop window closed before exit | **DISCHARGED** — see below. |
| 4 | Client waits on a ready signal | **DISCHARGED** — `starting` on POST + every SSE frame. |
| 5 | Hide the refusal, show `starting…` | **DISCHARGED** — verified by the reviewer's own repro. |
| 6 | Port 8787 → 8790 app-wide | **DISCHARGED** — 17 files; verified independently (below). |
| 7 | Restart live dashboard on 8790 | **DISCHARGED** — with a caveat, see below. |
| 8 | `make check` green | **DISCHARGED** — 804 tests, `selfcheck ok`. |
| 9 | Push + PR + merge to `personal` | **DISCHARGED as a direct push** — PR impossible, see below. |

## What landed so far

### Bug A — the refusal matcher could never fire (`aitracker/term_gate.py`)
`claude --resume` renders the bg-agent refusal through Ink, which does **not** emit spaces between
words — it jumps the cursor to each word's column. Real pty bytes:

    Session\x1b[9G<id>\x1b[46Gis\x1b[49Gcurrently\x1b[59Grunning\x1b[67Gas\x1b[70Ga\r\r\n
    background\x1b[12Gagent\x1b[18G(bg).\x1b[24GUse ...

So `REFUSAL_MARKER` was not a substring of what the backstop actually received. The old
`_normalize_output` only collapsed whitespace, which fixes `\r\n` wraps and nothing else.

Fix: `_ANSI_RE` strips CSI/OSC/2-char escapes **to a space** (deleting them would fuse
`currently`+`running` and fail just as silently) before the whitespace collapse.

Why no test caught it: the pinned capture in `tests/test_resume_fork_session.py` was the
*plain-text* rendering, not pty bytes. New test `PTY_REFUSAL` pins the real captured bytes.

### Bug B — the watcher gave up before the child exited (`aitracker/term_vt.py`)
Measured on a real pty against a genuine bg-agent id: refusal **prints at 2.05s**, **exit(1) at
2.61s**. `BACKSTOP_WINDOW` was **2.5s**, and `_retry_with_fork` requires `pt.done and pt.rc not in
(0, None)`. So the watcher expired ~0.1s before the state it waits for existed — the retry could
not fire even with a correct matcher.

Fix: `BACKSTOP_WINDOW` 2.5 → 8.0, plus `BACKSTOP_SCAN_BYTES = 65536` capping the re-scanned buffer
(the whole buffer is re-scanned every poll tick; the longer window would otherwise make a chatty
resume quadratic).

Both fixes proven by reverting each and watching its test go RED.

**Gotcha for whoever picks this up:** reverting `BACKSTOP_WINDOW` between two runs writes the same
byte count (`8.0` / `2.5`) inside the same mtime second, so Python reuses the stale `.pyc` and the
suite reports the OLD value. Clear `__pycache__` when a constant edit appears not to take.

## The readiness design (shipped)

Symptom chain, confirmed end to end: the refused child prints the refusal, exits(1), the server
closes the SSE stream, `EventSource.onerror` fires, and `ext_vt.js` writes `reconnecting…` into the
modal header. Nothing was broken *after* the refusal — the pane was showing a recovery in progress
as if it were a failure. (Note the browser terminal lives in **`aitracker/web/ext_vt.js`**, not
`app.js`.)

**Wire contract** — one new boolean, `starting`, on both the `POST /api/term/pty` response and every
`/api/term/screen` SSE frame. True only for `mode="resume"` panes still coming up.

**Server** (`term_vt.py`): while `starting`, `_screen_stream_body` sends `"rows": []` and — the load-
bearing detail — **does not advance the viewer's `since` cursor**. So when the flag clears, the very
next ordinary frame carries every withheld row for free. No second replay path was written.

**Clearing, first-of:** `_retry_with_fork` completing · a normal resume painting non-refusal
**printable** output after `BACKSTOP_SETTLE = 0.5s` · `_resume_backstop` returning for any reason
(`finally:`). **`finish()` deliberately does NOT clear it** — see defect #3 below; an earlier draft
of this design listed it here and that was wrong.

**Constraint that shaped it:** an ordinary, non-refused resume must not wait the full 8s window —
that would be a worse regression than the bug being fixed. Hence the settle-based early clear.

### Two traps recorded so the next person doesn't re-derive them

1. **Do NOT suppress in `_tee_raw()`.** The mapping pass proposed it and it is wrong:
   `_resume_backstop` detects the refusal by appending its own queue to `pt.raw_queues` and reading
   the child's output *through that same tee*. Suppressing there blinds the detector and disables
   the auto-fork entirely. Suppression lives only in the grid sender.
2. **`raw_stream()` / xterm is deliberately untouched.** It has no JSON envelope to carry the flag
   and no scrollback replay, so withholding bytes there would permanently lose a normal resume's
   opening paint. The grid/xterm asymmetry is a decision, not an oversight.

## Port move 8787 → 8790

Operative defaults changed in 17 files. Verified independently of the agent's own report — the only
surviving `8787` occurrences are in `docs/terminal-tiers-build-log.md` (3) and
`docs/terminal-tiers-plan.md` (2), both deliberately left as historical record. Confirmed effective
defaults: `cli.py:37` (`PORT` env fallback), `server.py:425/468` (`bind()`/`run()`), `Makefile:1-2`
(`PORT`/`TUNNEL_PORT`), `hooks/drain-notes.py:86`.

## Push identity — resolved, worth knowing

`git remote personal` is `git@github-personal:mepritamm/ai-tracker.git`. The **active** `gh` account
is `pmondal_a360`, which has only **READ** on that repo — `gh pr create` / `gh pr merge` fail under
it. A second `gh` account, `mepritamm`, is authenticated but inactive, and the `github-personal` SSH
host alias already resolves to `mepritamm`, so `git push` itself is fine.

Route the PR + merge through `/tracker-push` (CLAUDE.md: never a manual push) rather than switching
the global `gh` active account, which is shared machine state other sessions can observe.
Per stored memory, the advisor360 remote is archived — personal half only.

## Three live-path defects caught at INTEGRATION, after a green gate

All three passed 799 tests and would all have shipped broken. Recorded because each is the same
species of mistake: a unit test that models the shape of the data but not its **timing**.

1. **The settle clock started on the wrong bytes.** `first_output_at` was anchored on the first
   non-empty output. A real `claude --resume` emits a terminal-init escape burst
   (`\x1b7\x1b[r\x1b8\x1b[?25h\x1b[?2004h…`) at t≈0 — about **two seconds** before it prints
   anything readable (refusal at 2.05s). So the settle fired at ~0.5s, cleared `starting` while the
   child was alive and no refusal had printed, and the refusal painted anyway. Fixed by anchoring on
   the first **printable** output (`_normalize_output(text)` non-empty).

2. **`_ANSI_RE` did not cover `ESC 7` / `ESC 8`.** The two-character branch was `\x1b[@-Z\\-_]`
   (Fe finals, 0x40–0x5F). `ESC 7` (DECSC) and `ESC 8` (DECRC) are Fp escapes with finals in
   0x30–0x3F, so they were left half-stripped and their stray `7`/`8` read as printable text —
   which defeated fix #1 above. Broadened to the full standard form `\x1b[ -/]*[0-~]`.

3. **The SSE stream closed mid-recovery, and `finish()` revealed the refusal.**
   `_screen_stream_body` returned as soon as `pt.done`, so the refused child's exit(1) at 2.61s
   closed the connection — the browser's `EventSource.onerror` fired and painted `reconnecting…`,
   which is the exact symptom being fixed. And `Pty.finish()` cleared `starting` unconditionally,
   revealing the refusal at the moment the flag exists to hide it. Fixed: the stream now holds open
   while `starting` (`if done and not starting:`), and `finish()` deliberately leaves `starting`
   alone. Fail-open is unchanged in substance — it is now owned solely by `_resume_backstop`'s
   `finally`, which every `starting` pane has by construction.

**Resulting timeline for a refused resume** — one continuous stream, nothing false shown:
`t=0` starting, rows withheld · `t=2.05` refusal printed but withheld · `t=2.61` child exits, stream
HELD OPEN · `t≈2.7` backstop matches, fork retry swaps in the new child · `starting` clears · next
frame is a full snapshot of the live terminal.

## A fourth defect, introduced BY defect #3's fix

Making `Pty.finish()` stop clearing `starting` handed sole ownership of that clear to
`_resume_backstop` — which is started as a thread AFTER the pty is already registered in `PTYS`:

    with _LOCK: PTYS[pt.id] = pt
    if mode == "resume":
        threading.Thread(target=_resume_backstop, ...).start()   # <- can raise RuntimeError

If `Thread.start()` fails (thread exhaustion is genuinely reachable under the terminal cap), the
pane is registered `starting=True` with nothing that will ever clear it: a **permanently blank
terminal**, strictly worse than the refusal flash. The old code was accidentally safe here only
because `finish()` cleared the flag.

Guarded: the start is wrapped, and on `RuntimeError` the flag is undone, the response reports
`starting: False`, and the pane degrades to exactly the old behaviour (works, just without the
auto-fork recovery). Test: `test_backstop_thread_failing_to_start_does_not_wedge_the_pane`,
proven red on revert.

This is worth remembering as a pattern: **removing a redundant-looking fail-safe made a rare
failure permanent.** The redundancy was load-bearing for a path nobody was thinking about.

## The adversarial pass REFUTED the fix — and was right

An opus reviewer, told to assume the implementation was false, reproduced a fatal defect end to end
against a green 802-test gate. It is defect #1 again, one level down.

**A pty master read is hard-capped at 1024 bytes.** Ink's init frame therefore never arrives as one
chunk, and `_resume_backstop` re-scans its buffer after EVERY chunk. When a boundary lands inside an
escape sequence — probability ≈(N−1)/N, so the common case — the partial tail survived stripping as
printable junk: `b'...\x1b[38'` → `'38'`, and a buffer ending on a bare `b'\x1b'` → `'\x1b'`
(`str.split()` does not treat ESC as whitespace). 26 of 42 prefixes of the captured burst normalised
non-empty. Measured consequence: settle latched at t≈0.06s, `starting` cleared at 0.67s, refusal
**painted at 2.18s**, stream dropped at 2.61s. All three clauses of the claim failed at once.

Why the gate was green: `test_escape_only_output_does_not_start_the_settle_clock` — the test whose
docstring called itself "THE REGRESSION THIS CLASS EXISTS FOR" — fed the burst as **one chunk**. It
modelled the shape of the bytes and not their delivery, so it could not fail.

### Fixes

1. `_ANSI_PARTIAL_TAIL_RE` drops a trailing half-arrived escape BEFORE `_ANSI_RE` runs (after would
   be too late — `_ANSI_RE`'s last branch would already have eaten the ESC and spilled the rest).
   Normalisation is now a function of the CONTENT, not of where the reader sliced the stream.
2. `_ANSI_RE` gained `:` in the CSI parameter class (ITU sub-parameter SGR — `\x1b[38:2:255:0:0m`,
   `\x1b[4:3m` — is real output that used to spill through) and a DCS/PM/APC/SOS branch.
3. `_screen_stream_body` no longer rebuilds the whole grid 20×/second while starting
   (`snapshot(screen.v)` instead of a pinned `snapshot(since)`), which also stops it holding
   `pt.lock` against `_reader` for up to the full 8s window.

### Verification — the reviewer's own probes, re-run against the fixed code

    init burst ONE write        : refusal text reached the client: False
    init burst SPLIT mid-escape : refusal text reached the client: False   (was True at t=2.18)
    starting now clears at 2.75s / 2.84s — i.e. at the fork retry           (was 0.67s)
    frames during recovery: 3 / 3                                          (was 49 / 13)

Prefix coverage: **0 of 67** prefixes of the init burst normalise to text (was 26 of 42).
New tests assert over EVERY prefix, not one chunk — `test_no_prefix_of_the_init_burst_normalises_to_text`
and `test_escape_forms_the_cli_actually_emits_leave_no_residue`, both proven red on revert.

### What the reviewer could NOT break
`BACKSTOP_DONE_GRACE` racing the refusal branch (the refusal check is evaluated earlier in the same
iteration; `finish()` sets `rc` before `done`) · stuck-in-`starting` (all paths clear within
`BACKSTOP_WINDOW`, including the new `Thread.start()` guard) · thread/socket leak past `done` ·
lock-order inversion (only nesting anywhere is `_LOCK` → `pt.lock` in `_retry_with_fork`) · the
marker straddling the `BACKSTOP_SCAN_BYTES` truncation · the client wedging on a missing key.

## Shipping notes

**"PR + merge" became a direct push, and had to.** The `/tracker-push` skill documents that the
pushing account is an **Enterprise Managed User** and GitHub blocks EMU accounts from opening or
merging PRs on this repo — verified error: `GraphQL: Unauthorized: As an Enterprise Managed User,
you cannot access this content (createPullRequest)`. Direct push to `personal/main` is the only way
this account ships here. End state is the same: the work is on `main`. Commits `3c79e9b`
(the fix) and `9932d74` (README sync gate). `LICENSE ok` verified on the remote.

**The dashboard restart, and the caveat that matters.** 8787 turned out to be **LinkPage**, not
ai-tracker — ai-tracker was already on 8790 (pid 50847), running pre-fix code. Stopped by PID (never
`pkill -f aitracker`) and restarted on 8790, now serving the new page (`vtstarting` present,
`aitracker/port` = 8790). **It is running FROM THIS WORKTREE**, because worktree isolation forbids
touching the shared checkout — and that checkout had another session's uncommitted work at session
start, so forcing a pull there would have been the wrong call. **Action for you: `git pull` the main
checkout to `personal/main` and restart from there, then this worktree is free to remove.** Until
then, removing the worktree kills the dashboard.

## Open / parked
- **`TRACKER_TERM_RENDERER=xterm` gets none of this** — `_raw_stream_body` returns on bare `pt.done`
  and `openVT` only seeds `starting` for the grid renderer. Deliberate (no JSON envelope, no
  scrollback to replay), and `grid` is the default, so it does not affect the reported bug. Worth a
  decision if xterm ever becomes the default.
