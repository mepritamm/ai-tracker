# Adversarial review A: terminal-at-root plan v2

Reviewer: opus, read-only. Line numbers were read in this worktree (`76bd154`). The user decisions are
treated as fixed. This review attacks how the plan meets them.

Severity count: **1 blocker, 4 major, 7 minor.**

---

## F1 (BLOCKER): `run_dir` lives in `pt.fg`, so `_refresh_fg` drops it before the fork/attach retry types its line

- **Defect.**
  - The plan keeps `run_dir` in the claim dict `pt.fg`. For `_folder_retype` (claim rebuilt at 2410) it
    says the value should be "carried from the request or the previous claim".
  - `_refresh_fg` clears `pt.fg = None` (1880) when the foreground job exits.
  - `_folder_retype`'s own docstring (around 2395) says this is the normal case: "`_refresh_fg()`
    cleared this retry's own `fg` when the refused `claude` exited".
  - `_retry_with_fork(pt, sid, cols, rows)` (2443) and the attach retry (2620) run on the backstop
    thread with no request in scope.
- **Repro.**
  1. Resume a background session whose cwd is worktree W through the shared root shell.
  2. The CLI refuses with the bg marker, and `claude` exits.
  3. `_refresh_fg` clears `fg`.
  4. The backstop calls `_retry_with_fork`, then `_folder_retype`, then `_inject_argv`.
  5. `run_dir` is None, so the typed line is a bare `claude --resume <sid> --fork-session` in the
     **root shell**, which is the primary checkout.
  - Expected: `(cd W && exec claude … --fork-session)`. This breaks the plan's own §B.9 guarantee, on the
    exact path that bg sessions (the takeover case) hit.
- **Direction.** `run_dir` must outlive the claim. Its key is the session, not the transient job. Do not
  change the claim/`fg_pending` semantics.
- **Way.**
  - Add `self.run_dirs = {}` (sid → dir) on `Pty` (near 1385).
  - Write `fp.run_dirs[sid] = run_dir` under `_LOCK` at the claim (3229) and in `_swap_in` (3458).
    `_refresh_fg` never clears it.
  - `_inject_argv(pt, argv, deferred=False, sid=None)` looks up `pt.run_dirs.get(sid or (pt.fg or
    {}).get("session"))`.
  - Pass `sid` explicitly from all four typed sites: 3276, 3615, 2428 (`_folder_retype` already has
    `sid`) and 3487.
  - A `new` claim (session "") keys on `""`.
- **Test.** `test_fork_retry_after_fg_cleared_still_cds`:
  1. Claim a root folder pty for sid S with `run_dir=W`.
  2. Set `pt.fg = None` (simulating `_refresh_fg`).
  3. Call `_retry_with_fork(pt, S, 80, 24)` with `_folder_wait_prompt` and `_wait_for_quiescence`
     stubbed True and `_inject_write` captured.
  4. Assert that the written bytes start with `(cd 'W' && exec `.
  - This is RED with the plan's fg-only storage.

## F2 (MAJOR): the longer typed line now crosses `INJECT_BRACKET_LEN_THRESHOLD` (200) and gets bracketed-paste markers typed into a shell

- **Defect.**
  - `_inject_argv` (1950) writes `_bracket_if_needed(line)`. That function (4561) wraps the line in
    `\x1b[200~…\x1b[201~` at ≥200 chars.
  - Today the line is roughly `claude --resume <uuid>` (about 45 chars).
  - The subshell line is `(cd '<abs wt path>' && exec <launcher path> --resume <uuid>)`. With
    `.claude/worktrees/<name>` paths and an OpenRouter launcher path it routinely goes past 200.
  - The fallback login shell is `/bin/bash` (`os.environ.get("SHELL", "/bin/bash")`). On macOS that is
    bash 3.2, whose readline does not understand bracketed paste.
  - zsh with `bracketed-paste-magic` or `url-quote-magic` widgets can also rewrite pasted text.
- **Repro.** Use `SHELL=/bin/bash` and a worktree path long enough that the line is ≥200 chars.
  - Actual: `\e[200~` reaches readline as key sequences. Expect stray `~`, a beep, or a mangled command,
    and the resume never starts.
  - Expected: a plain line, as today.
- **Direction.**
  - A shell prompt is not Claude's TUI, so `_inject_argv` should never bracket.
  - Refuse any line containing `\n`/`\r`: a path that contains a newline is rejected with
    `(False, "unsafe path")`.
  - `inject()`'s bracketing must stay unchanged.
- **Way.**
  - In `_inject_argv`, replace `_bracket_if_needed(shlex.join(argv))` with `line.encode("utf-8")`.
  - Add a guard `if "\n" in line or "\r" in line: return False, "unsafe path"`.
- **Test.** `test_inject_argv_never_brackets_long_shell_line`: argv plus a run_dir that gives a line of
  more than 250 chars. Assert that the captured bytes contain no `\x1b[200~`. RED today.
  - L0 should also run (a) once with `SHELL=/bin/bash`.

## F3 (MAJOR): `exec claude` bypasses the user's shell alias/function and fails in zsh if `claude` is only a function

- **Defect.** Today the folder shell types `claude …`, which resolves through aliases and functions. That
  covers wrapper functions and things like `alias claude=…` set in an rc file.
  - `exec` resolves only external commands.
  - In zsh, `exec <function-name>` gives "command not found". The subshell exits 127, nothing runs, and
    the backstop retries the same failing line.
  - `gateway.launcher` returns `claude` (a bare name) for Anthropic (3104).
- **Repro.** Put `claude() { command claude "$@"; }` (or an alias) in `.zshrc` and resume a worktree session.
  - Actual: `exec: claude: not found`, or the wrapper is silently skipped.
  - Expected: the same resolution as today.
- **Direction.** Keep the foreground leader equal to the claude binary without depending on how the
  shell resolves the name.
- **Way.**
  - When the line is wrapped, resolve `argv[0]` to an absolute path server-side (`shutil.which`, outside
    `_LOCK`, at the open-route point where `or_launcher` is already resolved), then
    `exec <abs> …`.
  - Document that wrapper functions are skipped for worktree sessions.
  - Alternative, if the user prefers: `(cd W && claude …)` without `exec`, plus teaching
    `_foreground_is_claude` to accept a child named claude. That is costlier, so it is not recommended.
  - L0(a) adds a `type claude` check in the user's real login shell.
- **Test.** `test_subshell_line_uses_resolved_launcher`: patch `shutil.which` to return `/x/claude` and
  assert the line contains `exec /x/claude --resume`. RED when the plan's `shlex.join(argv)` is used.

## F4 (MAJOR): "missed call sites": `forked_cwds`, labels and the list `cwd` key on the root

The plan names 2075-2123, 2499 and 2556. It misses or mis-specifies these:
- **2075 `forked_cwds.add(p.cwd)`.**
  - For a forked **folder** pty, `p.cwd` is now the root, so the guard protects the root, not W.
  - `pt.forked` stays True for the pty's life (2493 comment), while `fg.run_dir` vanishes (F1).
  - Result: a `new` latch in W can adopt the fork transcript, and every `new` at the root is wrongly
    blocked.
  - Way: add every value of `p.run_dirs` for forked ptys (from the F1 dict).
- **2149 `_label`/folder name and 2203 `_live_list` `cwd`.** Every worktree session's terminal row now
  reads "<repo> - Claude Code" with `cwd=<root>`, including in the 429 slot list (`ext_vt.js` 2769
  renders it). The user can no longer tell K worktree sessions apart in the manage list or cap block.
  - Way: `_label` and `_live_list` use `_run_dir(p)` (F1 dict lookup on the current fg session, else
    `p.cwd`) for the folder name and `cwd`. Add a `shell_cwd: p.cwd` key if the SPA needs it. It does
    not today.
- **2499/2556 `record_fork(sid, pt.cwd)`.** The 2548 comment says this must match the parent transcript's
  **first** `cwd` (store.py 397). `run_dir` from S1 is the **latest** cwd.
  - Way: pass `run_dir` only when it is non-empty, and note that a session that moved cwd mid-run keeps
    today's mismatch (no regression).
- **Test.** Two tests:
  - `test_resolve_spawned_forked_cwds_uses_run_dir`: a forked root folder pty with `run_dirs={S: W}`,
    plus a `new` pty in W. `newest_session_in_cwd` must not be called for W. RED under the plan.
  - `test_live_list_labels_worktree_not_root`.

## F5 (MAJOR): S1 latest-cwd semantics and the `run` directory

- **Defect.**
  - `parse_any` meta.cwd is already "last value wins" (`providers/claude.py` 1830), so the S1 tail read
    matches. That part is right.
  - The latest cwd, though, is wherever Claude's Bash last `cd`'d: a subdir of W, or **the main checkout
    itself** if the agent ran `cd <root>`.
    - (a) `run = <W>/aitracker` resumes Claude in a subdir, which changes its project dir and slug.
    - (b) If the latest cwd is `<root>`, `git_worktree_root` returns "" and the session resumes bare in
      the primary checkout, even though it lived in W.
  - The 96 KB tail can also hold zero parseable lines (one giant tool_result). The plan says "fall back"
    but never defines the trigger.
- **Direction.**
  - `run` = the worktree top (the dir holding the `.git` file), not the raw cwd.
  - Prefer the transcript's latest **worktree** evidence over a later bare-root cwd, when one exists.
  - Fall back to `parse_any` whenever the tail yields `cwd == ""`.
- **Way.**
  - `git_worktree_root` also returns the wt top: `-> (root, wt_top)`.
  - `place` sets `run = wt_top`.
  - In `_tail_scan`, also harvest `last_wt_cwd` (the latest cwd containing `/.claude/worktrees/` or
    whose walk finds a `.git` file). This is cheap: string test only, with the walk done in `place`.
  - `recorded_cwd` returns `last_wt_cwd or cwd`, and falls back when both are empty.
- **Test.**
  - `TestTailScanCwd::test_latest_wins_and_wt_preferred`: fixture lines cwd=W, then W/sub, then root.
    Assert `cwd==root` and `last_wt_cwd==W/sub`, and `place` returns `run==W`. RED under the plan.
  - `test_tail_empty_falls_back`: a single 120 KB line, with `parse_any` stubbed to return a cwd. The
    cwd is returned.

## F6 (minor): relative `gitdir:` and symlinked paths in `git_worktree_root`

- **Defect.**
  - Git ≥2.48 `worktree.useRelativePaths` writes `gitdir: ../.git/worktrees/x`. The plan's
    `G/commondir` assumes G is absolute. `util._git_branch` (98) has the same bug, so the precedent is
    flawed too.
  - Transcript cwds can be non-canonical (`/var/...` vs `/private/var/...`), while git writes realpaths.
    `_folder_pty` matches by string equality (1897), so a sidebar-picked root and a derived root can
    produce two shells for one repo.
- **Way.**
  - `G = normpath(join(dirname(gitfile), G))` when G is not absolute.
  - Return `os.path.realpath(root)` and compare `realpath(run_dir) != realpath(pt.cwd)` in `_inject_argv`.
  - Leave `_git_branch` alone (out of scope), or fix it in one line.
- **Test.** Table rows for a relative gitdir and a symlinked tmp root. RED under the plan's absolute-only
  join.

## F7 (minor): row ordering in `place` for a deleted worktree

- **Defect.** With `resume=True`, `session_cwd` returns the existing ancestor, for example
  `<root>/.claude/worktrees`. Row 1 (`git_worktree_root(cwd)`) returns "", and only then does row 2 get
  checked. If an implementer writes "row 1 else row 3" with no `raw` check in between, Claude runs in
  `<root>/.claude/worktrees`, which is inside the primary checkout.
- **Direction and way.** Spell it out: evaluate `raw = recorded_cwd(sid)` whenever `not
  os.path.isdir(raw)`, before falling to row 3. Key the condition on `raw` missing, not on
  `cwd != raw`.
- **Test.** `test_deleted_wt_ancestor_inside_repo_is_409` (already in the plan's §B list), with the
  ancestor being `<root>/.claude/worktrees`. Ensure that fixture shape is used.

## F8 (minor): S2 test constants

- **Defect.** `INJECT_MIN_WAIT = 0.3` (4365) also gates the return. The plan's "seeded now−10 → < 0.2 s"
  fails even with the fix unless `INJECT_MIN_WAIT` is patched as well.
- **Way.** Patch `INJECT_MIN_WAIT=0.05` in `TestQuietSeed`. Seed `last_change = min(start, quiet_since)`
  on the `has_screen` branch only, which is what the plan intends.
- **Test.** As in the plan, with that patch.

## F9 (minor): tests that cannot go RED

- `test_waiter_bounded_by_spawn_not_spawn_wait` passes on today's code. It is a regression guard, not a
  proof of any leg's fix. Label it as such. It does not satisfy the "RED when reverted" proof column.
- The concurrency test must stub `_start_backstop`, `_folder_settled` and the `bg` lookup. Otherwise
  overflow resumes spawn real backstop threads and the 1.0 s bound is flaky under load (see the memory
  note on load-sensitive term_vt tests). Add the stubs explicitly.

## F10 (minor): external `build_script` quoting

- `run_dir` must go through the same shlex then AppleScript escape pipeline (`term_launch.py` 81-85) as
  `cwd`.
- **Test.** A run_dir containing `'` and `"` round-trips through `build_script` and `shlex.split`.

## F11 (minor): a vanished worktree between `place` and typing

- If W disappears after `place`, `(cd W && …)` fails and nothing runs. That is safe: no bare run. The
  backstop then retries the same failing line.
- **Direction.** No code change. Note in the PR that the backstop gives up after its one retry. It does,
  per its one-shot design.

## F12 (minor): concurrency §B.3 wording

- Waiters woken from the `Event` race the first handler into the claim section. Any one of them can
  claim. The outcome (one claim, K−1 overflow) holds because the claim is under `_LOCK`.
- The test must assert "exactly one typed line", not that "the first opener's line" is the one typed.

## Spot-check of the async inventory (5 rows)

- Row 7 (`term_launch` 212, osascript timeout 10): correct.
- Row 10 (`server.py` 450 search): correct.
- Row 12 (405 list): correct.
- Row 8 (566 `/api/title`): the route is there. Its depth was not re-measured.
- `ThreadingHTTPServer` at 838: correct.

Missed blocking spot: `term_run.run` (`term_run.py` 470) also calls `session_cwd`, and S1 speeds it up as
well. That is a benefit, and it is not listed.

No false claims were found in the sampled rows.

## SPA, 409 path

- `ext_vt.js` 2988-2996 renders `res.j.error` for any non-ok status.
- `ext_launch.js` 63-71 alerts `j.error`.
- Both render a 409 without changes, on phone too, because they share the same modal path.
- `ext_vt.js` 694 already uses 409 for "the pane changed hands" on a different route, so there is no
  collision.
- No finding.

---

## Overall clean plan (v2 deltas)

- **L1.**
  - `_tail_scan` harvests `cwd`, `gitBranch` and `last_wt_cwd` (F5).
  - `recorded_cwd` = `last_wt_cwd or cwd`, falling back to `parse_any` on "" (F5).
- **L2a.**
  - `git_worktree_root` returns `(root, wt_top)`, resolves a relative gitdir and realpaths (F6).
  - `place.run = wt_top` (F5).
  - The deleted-worktree check is keyed on `raw` missing, before the non-worktree row (F7).
  - Add table rows for relative gitdir, symlinks, and latest-cwd-at-root.
- **L2b.**
  - Add `Pty.run_dirs {sid: dir}`, set at the claims 3229/3458/2410 and never cleared by `_refresh_fg`.
    `_inject_argv` gains `sid=` and looks it up (F1).
  - No bracketed paste in `_inject_argv`. A newline in the line is refused (F2).
  - Resolve the launcher to an absolute path for `exec` (F3).
  - `forked_cwds`, `_label` and `_live_list` use the run dir (F4).
  - `build_script` quotes `run_dir` through the same pipeline (F10).
  - Add the F1/F2/F3/F4 tests.
- **L2c.**
  - Stub `_start_backstop`, `_folder_settled` and the bg lookup (F9).
  - Assert exactly one typed line (F12).
  - Relabel the waiter test as a guard.
- **L3.** Patch `INJECT_MIN_WAIT` in `TestQuietSeed` (F8).
- **L0.** Add runs with `SHELL=/bin/bash`, a `type claude`/wrapper-function check, and a line longer than
  200 chars (F2, F3).
- **PR notes.**
  - F11.
  - A worktree session's row now shows its worktree, while the shell sits at the root.

## Not examined

- `_resume_backstop` body and its retry counter (2382-2950), beyond the claim and typed lines.
- `_swap_in`'s release/restore logic, beyond the claim site.
- `registry.parse_any` caching, and whether `home_note` stat calls run on cached responses.
- Auggie `meta.cwd` shape, which was not opened.
- `ext_cr_term.js` header markup for the L4 note.
- Real zsh job-control behaviour for `( … exec … )`. That is left to L0.
