# Handover: two terminal safety gaps found while planning folder-terminal reuse

Status: open, deliberately left out of the reuse change (`docs/folder-terminal-reuse-plan.md`, which holds the opus review these findings come from). Each is a real gap on `personal/main`; neither has code yet.

Facts below were true at 3b7fb05 on Claude Code 2.1.318. Re-check them: the CLI auto-updates, and line numbers drift, so locate by symbol.

## Gap 1: typing over half-typed input
**Defect.** `open_pty` → `_inject_argv` (`aitracker/term_vt.py`) types `claude --resume <sid>` into an idle folder shell. Idle is judged by `_fg_pgid(p) == p.pid` and `_wait_for_quiescence`, and neither sees text sitting unsent at the prompt.

**Repro.**
1. In a folder terminal, type `ls ` and do not press Enter.
2. Open a session in that folder from the dashboard.
3. Actual: the shell runs `ls claude --resume <sid>`. Expected: the half-typed line is left alone and the session gets its own terminal.

**A plan already reviewed and REFUTED: don't repeat it.** A `Pty.line_dirty` flag set by parsing keystrokes in `keys()` failed review:
- It can hang a new terminal for 120s and then not start Claude: a stray key or an unmatched terminal reply during rc files marks it dirty, and `_inject_argv(deferred=True)` keeps failing until `FOLDER_STARTUP_WAIT`. Today the line is simply typed.
- False dirty on the path that works today: left arrow on an empty line, `a` then backspace, Ctrl-U, Ctrl-L, Tab, an SGR mouse click, a lone ESC and DCS replies all read dirty, and only Enter/^C clears it. One stray arrow means every later open gets a new terminal.
- It misses a continuation prompt (`echo "` then Enter reads clean).

Useful fact: all UI inject callers send `submit:true, clear_first:true`, and xterm `onData` goes through `postKeys`, so `keys()` is effectively the only human input path.

**Candidate directions (none chosen; decide with the user).**
- Read the screen, not the keystrokes: compare the cursor row on `Pty.screen` with the shell's prompt as it was when idle.
- Shell integration (OSC 133 prompt marks), which needs shell cooperation.
- Track printable count with backspace, Ctrl-U and history handling, gated to foreground == shell. This is the refuted idea done carefully, and the least attractive.

**Done means.** A test that is RED today covers the repro; a stray key during rc files never delays Claude; arrow keys on an empty line don't block reuse.

## Gap 2: a second copy of a session running outside the tracker
**Defect.** Opening a session that is live in the user's own Terminal or VS Code silently starts a second REPL on the same transcript. Binary: the CLI's holder check `E9` is `hxe(e).find(i => i.kind !== "interactive")`, so only background holders count. **This comes from reading the binary and is unproven at runtime: confirm it first** (two `claude --resume D` on an idle scratch session).

A related sub-case: a hand-typed `claude` in a tracker primary shell is missed by `_session_pty`, so a second REPL opens.

**Data available.** `~/.claude/sessions/<pid>.json`: `pid, sessionId, cwd, kind (bg|interactive), procStart, jobId, status, parkedJobId, spare`. The tracker doesn't read it today. Read only the fields needed.

**Traps the review already found (in a planned `live_repl_pid`).**
- `procStart` is UTC. Compare with `ps -o lstart= -p <pid>` run with env `LC_ALL=C TZ=UTC`, exactly as the CLI's `CQe` does. Without that the check rejects every holder on this machine, and a test that mocks `ps` stays green. Write one unmocked test: spawn `sleep`, write a fixture with the UTC lstart, run with `TZ=Asia/Kolkata`, expect the pid.
- Skip `parkedJobId` entries: `hxe` skips those, and such a session has moved to a background job.

**Product decision needed first.** Refusing with a 409 can block legitimate opens: a forgotten `claude` in tmux alive for days, or a session in a pty of a second tracker instance, which reads as "outside". Options: refuse with a message; warn and let the user continue; attach when the holder is one of our own ptys and otherwise warn.

**Done means.** The chosen behaviour is proven by a test with no mocked `ps`, and the hand-typed sub-case attaches to its own pty.

## Later: a hand-typed `claude` that gets parked (user asked to keep this as a note)
The terminal switch (`docs/folder-terminal-reuse-plan.md`) only reuses a parked pane the tracker opened itself, so it knows the session (`fg.session`). If `claude` was typed by hand in a tracker shell and then parked, `fg` is None and the pane stays ineligible: a background session opened in that folder gets a new terminal, as today. Nothing gets closed on a guess.

To include it later: infer the session from `~/.claude/sessions/<pid>.json` (`sessionId`, `parkedJobId`, `procStart` compared via `LC_ALL=C TZ=UTC ps -o lstart=`). That adds reliance on one more undocumented CLI detail, so it needs its own opus plan and adversarial review.

## Dropped: reusing spare shells
Not worth doing: 0 live overflow rows, and spares come from a picker tab that already has a viewer. Making them `folder=True` also regresses hand-typed Claude matching (`_session_ptys`' folder branch ignores `spawned`, so `registry._attached_pty` loses it). Don't revive this without new evidence.

## Pointer prompt (paste into a fresh session in ai-tracker)
> Read `docs/handover-terminal-input-guards.md`. Start with Gap 1 (half-typed input) using `/tracker-gap`. First step: in a new worktree off the latest `personal/main`, write the RED test for the repro in `tests/test_folder_terminal.py`, then have an opus agent plan the fix without repeating the refuted `line_dirty` design, and ask me to choose a direction before implementing.
