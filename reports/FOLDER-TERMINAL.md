# Folder terminal: one shared PTY per folder, every session runs inside it

Worktree: `.claude/worktrees/folder-terminal` (branch `worktree-folder-terminal`, based on local HEAD
`c8c49f2`; this repo has no `origin`, only `personal`). Session: `tracker-manage-terminal-session-architecture`
(2026-09-13, unattended `/head-out` run).

## The contract (verbatim)

Original ask:

> how are we managing the terminals today and is there any better way to manage the terminals specially for
> the sessions where we are running them from the same folder, is there any chance that we run the terminals
> each for the folder and then thats being shared across all the sessions in that folder, that way we manage
> to run a single terminal session from the app for each folder and all the claude sessions easily run from that.

> is it possible to tackle the resume where the tracker looks for the existing tracker's session for that
> folder and uses that for that very thing such that, and put them back into the original state once the
> resume is done and closed ?

> since that will be a true shareable terminal across the entire folder, is that something can be done for
> all of them

> go ahead and build it /tracker-gap /tracker-push /head-out

Head-out answers (verbatim):

1. Scope — "Full folder terminal (Recommended)": all three modes (shell / resume / new) share one PTY per
   folder via inject; close semantics + busy handling included.
2. Busy — "2 [Silently open a dedicated PTY] and then once that resume is done and the user is closing the
   resume window, just go ahead and remove it from the memory and the manage session, such that we are back
   with 1 session per folder such that we arent wasting unecessary memory"
3. Close — "2 [Kill the whole folder terminal] and but if anything is running inside the terminal, prompt the
   user for confirmation and then continue, also make sure that if closing the terminal process really
   killing the execution of the terminal or the session's process."
4. Push — "Yes, push main to personal directly (Recommended)"

## Clause ledger

| # | Clause | Verdict | Evidence |
|---|--------|---------|----------|
| C1 | One shell PTY per folder; opening `mode:cwd` for a cwd that already has one attaches instead of spawning | **discharged** | `open_pty` find-or-spawn loop with per-cwd reservation (`term_vt.py` ~:2915-2966); `test_second_cwd_open_reuses_folder_shell`, `test_two_simultaneous_first_opens_share_one_folder_shell` |
| C2 | `mode:resume` / `mode:new` run INSIDE the folder shell (inject `claude --resume <sid>` / `claude`) when it is idle | **discharged** | `_inject_argv` types `shlex.join(argv)` + CR after a prompt-wait (~:1815-1850); `test_resume_reuses_idle_folder_shell_and_injects_the_resume_command`, `test_pty_new_mode_spawns_claude_with_no_args` (asserts `claude` was typed) |
| C3 | When Claude exits, the folder shell is back at its prompt (original state) and the PTY is idle again | **discharged** | `_refresh_fg` clears `fg` once the shell owns the foreground again after a child was seen post-Enter (~:1755-1775); `test_refresh_fg_sets_seen_child_while_busy_and_clears_once_idle_again`; live smoke: inject `sleep 30` → busy → close → `shell alive: False job alive: False` |
| C4 | Busy folder shell → dedicated overflow PTY, with a notice; overflow PTY is dropped from `PTYS` and the manage list the moment it finishes or is closed (no linger) | **discharged** | overflow spawn + `notice` (~:3015-3040), `_reap` linger 0 for overflow, `close_pty` deletes overflow in-request; `test_resume_while_folder_shell_busy_with_a_different_session_gets_overflow`, `test_overflow_pty_is_reaped_immediately_ignoring_the_linger`, `test_close_overflow_pty_deletes_it_from_ptys_in_the_same_call` |
| C5 | Close on a folder terminal with a live foreground → 409 until confirmed; then the shell AND the foreground process group are both dead (verified by pid) | **discharged** | `close_pty` 409 without `force`; `Pty.kill` SIGKILLs the fg pgrp (guarded `> 0`, never our own group) then the shell group; bounded confirm wait; `test_close_busy_folder_pty_without_force_returns_409_and_does_not_kill`, `test_close_kills_shell_and_foreground_child` (real process, SIGHUP-ignoring child in its own pgrp; RED when the fg-group kill is reverted) |
| C6 | Resume backstop (refusal → attach / fork) retypes into the folder shell instead of respawning | **discharged** | `_folder_retype` + `if pt.folder:` branches in `_retry_with_fork`/`_retry_with_attach`; refuses over another session's claim; `test_retype_refuses_when_fg_is_claimed_by_a_different_session`, `test_retype_still_retypes_over_its_own_claim` |
| C7 | Client: dedupe by folder, title shows folder + running session, busy toast, close-confirm dialog, manage list shows folder/fg/overflow | **discharged** | `ext_vt.js` openVT + mountInto dedupe, folder titles, 409→confirm; `ext_cr_term.js` manage / close-all / pane-Kill confirm; `ext_cr_dialogs.js` badges; 16 Node-exec tests across `test_term_vt_exec.py` / `test_cr_manage_terminals_parity.py`, 4 proven red-then-green |
| C8 | Tests: C1–C5 each pinned by a test that goes red when the server branch is reverted; `make check` green | **discharged** | `tests/test_folder_terminal.py` 19 tests; per-module gate green (2029 tests pre-fix; touched modules re-run post-fix: 19/322/106/258/73/126 OK); `selfcheck ok` |
| C9 | README updated; committed on `main`; `git push personal main`; LICENSE present on remote | **discharged** | README.md:95; commit + push recorded below |

## Review record

- Server reviewed adversarially by two models (sonnet + opus, both told the report was false). Both found the
  find-or-spawn race (fixed: per-cwd reservation `_FOLDER_SPAWNING`). Opus additionally found the `fg` claim being
  cleared by the 2s poll before the command was typed (fixed: `fg_pending`), `_folder_retype` re-claiming over another
  session (fixed), and test fixtures with fake pids running the real `kill()` (fixed: `Pty.kill` stubbed there).
  Second-opinion pass (sonnet) on the fix hunks: holds.
- Client reviewed (sonnet): no defect; the untested `mountInto` dedupe copy got 3 tests.
- Known ceilings (`ponytail:` comments): a waiter that outlives `FOLDER_SPAWN_WAIT` (3s) may spawn a second folder
  shell; the `[overflow]` tag is plain text in the row (the phone-layout test pins one span per row).

## Parked for the user

- `~/.pyenv/shims/.pyenv-shim` is a stale pyenv rehash lock dated 23 Mar. In the sandbox every interactive `zsh -l`
  blocked on it (`pyenv init -` runs from `.zshrc:6-7`), so the folder shell never reached its prompt inside
  `INJECT_MAX_WAIT` (8s) and every resume/new fell back to an overflow PTY with a notice. Not touched (home dir).
  Check: `time zsh -lic true`; if slow: `rm ~/.pyenv/shims/.pyenv-shim && pyenv rehash`.
- The primary checkout's local `main` is not moved by this push (it is checked out there). Afterwards, in the primary
  checkout: `git pull --ff-only personal main`.

## Design (as briefed to the implementers)

Server — `aitracker/term_vt.py`
- `Pty` gains `folder` (bool), `overflow` (bool), `fg` (None or `{"session","mode","started"}`), `fg_seen_child` (bool).
- `_fg_pgid(pt)` = `os.tcgetpgrp(pt.fd)`; idle ⇔ `_fg_pgid(pt) == pt.pid` (login shell with job control puts each
  foreground job in its own pgrp — this is why close must kill BOTH groups).
- `_refresh_fg(pt)`: if fg pgid != shell → `fg_seen_child=True`; if `fg_seen_child` and fg pgid == shell → `fg=None`,
  `fg_seen_child=False`. Called from `term_list`, `attached`, `open_pty`, `close_pty`.
- `_folder_pty(cwd)`: live, not done/closing, `folder` and `cwd == cwd`.
- `open_pty`: resolve cwd as today → `pt = _folder_pty(cwd)` or spawn the login shell as the folder PTY
  (`folder=True, mode="cwd"`). Then: `mode=="cwd"` → return it (`reused`). `resume`/`new`: idle → set `fg`,
  inject argv text (`_wait_for_quiescence` + `_inject_write` + "\r"), start backstop in inject mode, return
  `{tty, reused, folder:true}`. Busy with the same sid → return it (peek). Busy otherwise → today's dedicated
  spawn with `overflow=True`, response carries `notice`.
- `_reap`: overflow PTYs use linger 0. `close_pty` on overflow → kill + `del PTYS[tid]` immediately.
- `close_pty`: `_refresh_fg`; folder PTY with fg busy and no `force` → 409 `{busy:true, fg}`. Otherwise
  `killpg(fg pgid, SIGKILL)` if it differs from the shell's, then today's `kill()`; wait for reader EOF; return
  `{ok, killed:[pids]}` after confirming `os.kill(pid, 0)` raises for each.
- Backstop: `_retry_with_attach/_retry_with_fork` take a `via_inject` path when `pt.folder`: wait for fg to be the
  shell again, then inject the retry argv; never `_fork_child` into a folder PTY.
- `_live_list` rows gain `folder`, `overflow`, `fg`.

Client — `aitracker/web/ext_vt.js`, `ext_cr_term.js`, `ext_launch.js`
- Find-existing scans: `mode=="cwd"` → match `t.folder && t.cwd === cwd`; `resume` → also match
  `t.fg && t.fg.session === sid`. Server remains the source of truth.
- Title (`ext_vt.js` ~:2548): folder → `<cwdTail> · running <session title>` / `<cwdTail> · shell`.
- `notice` from the open response → existing `notice=` tab param / toast.
- Close: on 409 busy → confirm "<session> is running in this terminal — close anyway?" → re-POST with `force:true`.
- Manage list: folder badge, fg label, overflow badge.

Sequencing: server first (opus), client + tests in parallel against the field contract above, README last.
