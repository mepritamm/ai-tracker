# Handover: the resume line gets typed into an rc `read` prompt (F1b)

Status: open, deliberately not fixed in the "one session ⇒ one terminal" change (commit on branch
`worktree-term-one-per-session`; context in `docs/terminal-one-per-session-plan.md`). Pick this up
after that branch lands on `personal/main`.

## The defect
When the tracker opens a session in a **folder terminal** whose shell was just spawned,
`aitracker/term_vt.py` starts it in the background: `open_pty` → `_deferred_folder_start` →
`_folder_settled` (waits until the shell holds its OWN foreground continuously for
`INJECT_QUIET_WINDOW`) → `_inject_argv(fp, argv, deferred=True)`, which types
`claude --resume <sid>` + Enter.

If the user's rc file waits on a **shell builtin** prompt (e.g. oh-my-zsh's
`[oh-my-zsh] Would you like to update? [Y/n]`, or any `read -q` / `vared` / `read -r`), the foreground
stays on the shell and the screen goes quiet, which looks exactly like a ready prompt. So the line
`claude --resume <sid>` is typed as the ANSWER to that prompt. Meanwhile `Pty.starting=True` hides the
pane's rows, so the user can't see what happened. Claude never starts (or starts after a mangled answer).

Signals the current code has, and why each fails here:
- `_fg_pgid(fp) == fp.pid` — true for a builtin `read` (no child process).
- `_wait_for_quiescence` / `_body_rows_version` — quiet while it waits for input.

## Repro
1. In `~/.zshrc` (temporarily) add: `read -q "REPLY?continue? [y/N] " ; echo` near the top.
2. Close any folder terminal for a test repo; resume a session in it from the dashboard.
3. Expected: Claude starts (or the tracker shows the prompt and waits). Actual: the resume line is
   consumed by `read`, and the pane shows "starting…" until the backstop or timeout.

## Candidate directions (decide with the user; none chosen)
- **Prompt-shape guard:** before typing, inspect the cursor line on `fp.screen`. Refuse to type, and
  surface the pane (clear `starting`), if the line ends in a question-like pattern
  (`? `, `[Y/n]`, `[y/N]`, `(y/n)`). Cheap, but heuristic: it can misfire on a PS1 ending in `?`.
- **Prompt marker:** when the tracker spawns the folder shell, export an env var the user's prompt can
  echo (or use OSC 133 / shell-integration "prompt start" marks if the shell emits them), and type only
  after seeing the marker. Exact, but needs shell cooperation or zsh/bash precmd injection via
  `ZDOTDIR` / `--rcfile` wrapping.
- **Show, don't type:** on a fresh folder shell, don't hide rows (`starting=False`) until the line is
  typed, so a stray prompt is at least visible. This is a UX mitigation, not a fix.

## Files / symbols
- `aitracker/term_vt.py`: `_folder_settled`, `_deferred_folder_start`, `_inject_argv`
  (`deferred=` path), `Pty.starting`, `Screen` (cursor row).
- `tests/test_folder_terminal.py`: `_timeline_pgid`, `TestFreshFolderShellQueuesInsteadOfOverflow`
  (fixture style for a fake fresh shell).

## Done means
- A test that is RED today: a fake fresh folder shell whose screen cursor line is `continue? [y/N] `
  with fg == shell and quiet ⇒ the resume line must NOT be typed, and the pane is made visible.
- No regression in `tests.test_folder_terminal` / `tests.test_term_vt` (run one module per process
  with `unset TRACKER_AUTH;`).
- Work in a new worktree off the latest `main`; `/branch-sync` before pushing; `/tracker-push`.

## Pointer prompt (paste into a fresh session in ai-tracker)
> Read `docs/handover-rc-read-prompt.md` and fix F1b with `/tracker-gap`. First step: in a new
> worktree off latest main, add the RED test described under "Done means" to
> `tests/test_folder_terminal.py`, then ask me which candidate direction to take before implementing.
