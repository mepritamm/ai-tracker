# Adversarial review B of terminal-at-root plan v2

Reviewer: independent opus-class pass (reviewer B). Source read-only; `grep` + `sed -n` only. Line numbers are from this
tree (`term_vt.py` 4929 lines). Plan under review: `reports/terminal-at-root.md` (v2). User decisions treated as fixed.

Verdict: the architecture (shell at root, claude in a `cd`'d subshell with `exec`) holds. The lock claims in §B check out.
Four majors and a set of minors below; all are fixable inside the plan's own legs.

## Findings

### B1 (MAJOR) A fork or attach retry loses `run_dir` and types a bare `claude` into the root shell
- **Defect.** Plan §A says claims at 2411 (`_folder_retype`) and 3458 (`_swap_in`) "carry `run_dir` from the request or the
  previous claim". The previous claim is not reliable.
  - `_folder_retype` (`term_vt.py:2382`) waits for the refused claude to hand the prompt back, then builds a NEW claim at
    2411: `pt.fg = {"session": sid, ...}`.
  - Its own docstring says `_refresh_fg()` may already have cleared the old claim when the refused claude exited.
    `_refresh_fg` clears `fg` on prompt return once `fg_seen_child` is latched.
  - The retype therefore has no `fg["run_dir"]` to read. `_inject_argv` (1917) then sees `run_dir=None` and types plain
    `claude --resume <sid> --fork-session` into the ROOT shell, so claude runs in the primary checkout.
  - `_swap_in(fp, cand, sid, argv, forked, cols, rows)` (3449) has no `run_dir` parameter at all. Its caller at 3326 would
    have to thread one.
- **Repro.** Worktree session B, `bg` refusal on the resume: `_resume_backstop` -> `_retry_with_fork` -> `_folder_retype`.
  Actual: new claim without `run_dir`, bare line at root. Expected: `(cd <wt> && exec claude --resume B --fork-session)`.
  This is the exact "claude bare in root" hazard the plan's guarantee 9 forbids.
- **Direction.** Store the run directory on the `Pty`, not only on the claim dict. Do NOT rely on `pt.fg` surviving.
- **Way.**
  - Add `Pty.run_dir = ""`. Set it under `_LOCK` at every claim site: 3229 (open_pty), 3458 (`_swap_in`, which needs a new
    `run_dir` argument from the 3326 call), and leave it alone at 2411.
  - `_inject_argv` reads `pt.run_dir` instead of `(pt.fg or {}).get("run_dir")`.
  - Safe because a folder shell has one claim at a time, and `_folder_retype` already refuses when a different session holds
    the claim.
  - Clear `pt.run_dir` on the release paths (3215-3223 undo, `_deferred_folder_start` failure, `_swap_in.release`).
  - The same field serves `_run_dir(p)` for `resolve_spawned` and `record_fork`.
  - Keep the `_inject_argv(pt, argv, deferred=False)` signature so the `(pt, argv)` test stubs stay valid.
- **Test.** `test_folder_retype_keeps_run_dir`: claim with run_dir=wt; force `pt.fg = None` (simulating `_refresh_fg`);
  call `_retry_with_fork` on a folder pty; assert the captured typed line contains `cd <wt>`. RED when the field is
  claim-only. Add `test_swap_in_types_subshell` asserting the same for the takeover path.

### B2 (MAJOR) The plan's `cwd` and `new` deleted-worktree rows are unreachable: `open_pty` and `open_terminal` 404 first
- **Defect.**
  - `term_vt.py:3088-3091` calls `term_gate.session_cwd(sid)` WITHOUT `resume=True` for `cwd` and `new`. For a recorded cwd
    that no longer exists it returns `""`, so the handler returns 404 ("session not found or its cwd no longer exists").
  - Plan §A places `place()` "after the 404 at 3090" (and after 196 in `term_launch`).
  - So the table rows "`cwd` mode on a deleted worktree opens the root shell" and "`new` -> 409" can never run.
  - The test `test_deleted_worktree_resume_is_409_not_bare (and new too)` and the "cwd opens the root shell" assertion would
    fail or never reach `place`.
- **Repro.** Session whose worktree was removed, `POST /api/term/pty {session, mode:"cwd"}`. Actual: 404 today and after v2
  as written. Expected per plan: 200 with the root shell and the note.
- **Direction.** Decide deleted-worktree handling BEFORE the 404. Do not widen `session_cwd(resume=True)` to all modes: the
  existing one-arg `lambda` stubs in tests (comment at 3085) break.
- **Way.** In both routes, when `not cwd`, call `raw = term_gate.recorded_cwd(sid)` and `pl = term_gate.place(sid, "", mode)`.
  - `place` must accept `cwd=""` and fall to the deleted branch via `deleted_worktree_root(raw)`. Return `error` or a root
    shell as per the table.
  - Only if that also yields nothing, 404 as today.
  - Fake sids still skip it, because `recorded_cwd` returns "" for them.
- **Test.** `test_deleted_worktree_cwd_mode_opens_root_shell` and `..._new_mode_409` driven through `open_pty` itself (not
  through `place`). RED today (404).

### B3 (MAJOR, decision) The 409 blocks routine post-cleanup resumes, so the default should not be a hard refusal
- **Defect.**
  - The user's standing rule 7 is to clean merged worktrees routinely.
  - Every such session's Resume (board card, session list, external button) would now 409, where today it works.
    `claude --resume` finds the session by id from any existing directory (plan evidence, `session_cwd` docstring).
  - Today's walk lands on `<root>/.claude/worktrees` (the nearest EXISTING ancestor), NOT on the primary checkout. So today's
    behaviour does not violate the isolation the plan protects.
  - The plan's E1 offers "keep the ancestor walk" only as an alternative.
- **Repro.** Session whose worktree was removed after merge, click Resume. Actual (v2): 409 plus a `git worktree add`
  instruction. Expected: the conversation reopens.
- **Direction.**
  - Default: resume still works. Shell at the root, `run_dir` = today's nearest existing ancestor.
  - Refuse (409) only when that ancestor equals the root or lies outside the repo: that would place claude in the primary
    checkout or at `/`.
  - Keep the `git worktree add` hint as a note, not a refusal.
  - Do NOT change: plain removed folders, and the "never claude in the primary checkout" invariant.
- **Way.** `place()` deleted branch: `run = ancestor_from_walk(raw)`; `error` only if `realpath(run) == realpath(root)` (or
  the walk yields nothing). The shared walk code already exists in `session_cwd` lines 94-100; factor it, do not duplicate.
- **Test.** deleted wt under `<root>/.claude/worktrees/` -> `run == <root>/.claude/worktrees`, no error; deleted wt directly
  at `<root>/x` -> 409. RED against the v2 refusal table.

### B4 (MAJOR, test validity) The S2 test can pass with the fix reverted unless it uses the screen path
- **Defect.**
  - `_wait_for_quiescence` (`term_vt.py:4505`) has two clocks. With `pt.screen is None` it already uses `now - pt.last_output`
    (the very thing S2 wants to seed), so S2 changes nothing there.
  - With a Screen, which is the production case, `last_change = start` (4530) is the bug.
  - Plan `TestQuietSeed` ("seeded with now-10 -> < 0.2 s") does not say the fake pty has a `Screen`.
  - Also: `INJECT_MIN_WAIT` (0.3, line 4365) bounds the best case, so "< 0.2 s" needs `INJECT_MIN_WAIT` patched too. The plan
    patches "0.4/0.05" without naming the constants.
- **Repro.** `Pty` stub with `screen=None`, `last_output = now-10`, no kwarg: the old code returns quickly. The test is green
  before and after the fix.
- **Direction.** The fix is right (seed `last_change` from the quiet start in the screen branch only). The test must exercise
  the screen branch.
- **Way.** Build the pty with a real `Screen`, patch `INJECT_QUIET_WINDOW=0.4`, `INJECT_MIN_WAIT=0.05`. Seed
  `last_change = quiet_since if quiet_since else start`, screen branch only. `_inject_argv` passes `pt.last_output`.
- **Test.** screen pty, seed now-10 -> returns in < 0.2 s; unseeded -> >= 0.4 s. RED on revert (the kwarg disappears, or the
  old clock restarts at call time).

### B5 (minor) `(cd x && exec claude ...)` has three silent behaviour changes versus typing `claude ...`
- **Defect.**
  1. `exec` skips shell aliases and functions. `claude` typed bare expands a user's `alias claude=...` or wrapper function;
     `exec claude` does not (zsh does not alias-expand after `exec`). No `claude` alias exists in this user's rc files, so
     it is latent.
  2. In fish, `(...)` is command substitution, so the line does not run. The plan "assumes bash and fish are job-control"
     but never tests the syntax. `$SHELL` is arbitrary (`open_pty` 3118).
  3. The `cd` fires the shell's chpwd hooks (direnv, nvm) inside the subshell. That is arguably desirable, but it is new
     latency and noise.
- **Direction.** A shell-agnostic form keeps comm == `claude` and avoids the parse problem. Document the alias bypass.
- **Way.** Type `sh -c 'cd "$0" && exec "$@"' <wt> claude --resume <id>`, each token through `shlex.quote`. The shell forks
  `sh` as the job (pid == pgid), then `sh` execs claude, so the foreground leader's comm is `claude`. This is the same
  property L0(a) must measure. Fall back to `(cd ... && exec ...)` only if L0 shows `sh -c` mis-detects.
- **Test.** `_inject_argv` golden string; plus L0(a) re-run with `$SHELL=fish` if installed, and with an alias defined.

### B6 (minor) The SPA client-side dedupe silently stops matching; the labels now say "repo", not "worktree"
- **Defect.** `ext_vt.js:2925` and `:3851` match `t.cwd === targetCwd` where `targetCwd = slist[si].cwd` (the worktree).
  After the change `t.cwd` is the root, so the "peek an existing folder shell" shortcut never fires for worktree sessions.
  The server still dedupes, so the cost is one extra round trip, not a bug. Also `_term_title` (`term_vt.py:2149`) and
  `ext_cr_dialogs.js:2052/2069` label every worktree terminal with the repo-root basename.
- **Direction.** Do NOT "fix" the shortcut by comparing against the root on the client: it would peek a shell that is
  currently running ANOTHER worktree session's claude (the server's `taken` logic exists for exactly that). Drop the
  client shortcut for `mode==="cwd"`, or let the server own it.
- **Way.** Delete the `mode === "cwd" && targetCwd` clause in both copies (the server answers `reused:true` anyway), or
  extend the `GET /api/term/list` row with a server-computed `home`. For the label, let `_term_title` use
  `p.fg.get("run_dir")` basename while a claim is active.
- **Test.** Node harness: with a root folder row and a worktree session, `openVT` issues the POST rather than peeking. Plus a
  title assertion for a claimed row.

### B7 (minor) Root derivation edge cases
- **Relative gitdir.** Plan §A: `C = normpath(join(G, read(commondir)))`. If `gitdir:` is relative (git >= 2.48
  `--relative-paths`, or hand-edited), `G` must first be joined with `dirname(<wt>/.git)`. Add that, with a table test.
- **Symlinked paths.** `_folder_pty` matches `p.cwd == cwd` by string (1897). A main-checkout session recorded as
  `/tmp/repo` and a worktree whose commondir resolves to `/private/tmp/repo` give two "root" shells, defeating the sharing.
  Cheapest fix: in `place`, if `realpath(root)` equals the `realpath` of an existing folder pty's `cwd`, reuse that string.
  Test with a symlinked tmp root.
- **Unmapped layouts.** Bare-repo worktrees and `--separate-git-dir` main checkouts fall to "unmapped". The user decision was
  "ANY git worktree". State this limitation in `home_note` (one line) and in the PR notes; do not claim "any".
- **Path hygiene.** `place()` must `realpath`-compare the derived root against the cwd to avoid mapping a main checkout's
  own subdirectory (it returns "" today, which is right; add a test).

### B8 (minor) Test hygiene in L2c and L2b
- **Wall-clock asserts.** "every handler returns within 1.0 s" will flake under the known OOM and load issues in memory. The
  property that matters is that no slow work runs under `_LOCK`. Swap `term_vt._LOCK` for an instrumented lock that records
  the max hold time, and assert < 50 ms. That is deterministic and RED if anyone adds a sleep or subprocess under it.
- **Do not assert which handler claims.** Waiters wake at `reserved.set()` (3198-3200), which is BEFORE the first handler's
  claim section, so any of the K can win the claim. Plan §B item 3 ("the first handler claims") is wrong, though harmless.
  Assert counts (1 claimant, K-1 overflows), not identity.
- **Guards, not RED-on-revert.** `test_same_session_twice_one_tty` and "byte-identical for non-worktree sessions" pass on
  today's code. Label them regression guards so nobody believes they prove the feature.
- **Bracketed paste.** `INJECT_BRACKET_LEN_THRESHOLD = 200` (4404). Today's ~52-char resume line is never bracketed. With
  longer worktree paths the subshell line can cross 200 chars and be typed as a bracketed paste. Add a golden test just under
  and just over 200, and exercise the over-200 case in L0(a) through the real `_inject_write` path, not by hand.

### B9 (minor) S1 tail fast path needs an explicit "no cwd in the tail" fallback
- `_tail_scan` reads the last 96 KB and drops the first partial line. A final giant line (a big `tool_result`) leaves no
  parseable record, so `cwd` is empty.
- **Direction.** Fall back to `parse_any` only on empty. Never return `""` meaning "unknown".
- **Way.** `recorded_cwd(sid)`: `c = tail["cwd"]; return c or <old parse_any path>`.
- **Mid-session cwd change.** The "latest cwd wins" semantics match `parse_session`'s "last value wins" (`claude.py:1831`).
  `_head_meta` (line 269) is FIRST-cwd-wins and is a different value, used by `newest_session_in_cwd` (507). Keep both
  as they are, and do not swap them.
- **Test.**
  - Fixture with cwd root then later cwd wt -> wt.
  - Fixture whose last line is > 96 KB -> the fallback is used (patch `parse_any` to count calls).
  - Fixture with a sid that has no transcript (a daemon job id) -> fallback.

### B10 (minor) Claim dict leaks `run_dir` to the wire
`_fg_public` (`term_vt.py:1884`) strips only `grants` and `forked`. If `run_dir` rides in `fg`, `/api/term/list` serves the
path to every viewer. With B1's `Pty.run_dir` field this goes away. If kept in `fg`, add it to the stripped set.

### B11 (minor) User-visible effects to state in the PR notes
- **A watched `Open terminal` shell is hijacked.** The idle-claim path (3229) does not check `viewers`. Resuming session B
  while session A's user watches the shared root shell types B's claude into A's tab. It is the sharing the user asked for,
  now cross-worktree, and A's grants are dropped (`_pty_owned`). Add a one-line `pt.add_notice` on A's viewer when a claim
  displaces a different session's viewer.
- **Echo and history.** The shell echoes `sh -c ...` or `(cd ... && exec ...)` and appends it to HISTFILE.
- **Exit behaviour.** On Claude exit the user lands at the root, not the worktree. That is the user's decision, but say so in
  `term_home_note`.

### B12 (minor) L0 spike gaps
- L0(c) before L2 exists launches two plain `claude --resume` processes. That never touches the server, so it does not
  test "multiple sessions at once".
- Make L0(c) a post-L2 check, and keep it small.
- Each L0 session costs a real `claude -p` call, so say that in the brief.

## Attack results (items you asked for)

1. **Subshell and the fg-process detection.**
   - `_foreground_is_claude` reads `ps -o comm=` of the pgid leader (4018-4075). `exec` keeps leader == claude, as the plan
     says.
   - The five-second `_FG_CACHE` caches a "zsh" reading only for the microsecond window before `exec`. Fine.
   - Ctrl-C and exit behave as for any foreground job: the prompt returns at the root and `_refresh_fg` clears the claim via
     the latched `fg_seen_child`.
   - `_swap_candidate` (3404) compares `_shell_cwd` with `cwd`. Since the parent shell stays at the root and `cwd` is the
     root, it works.
   - See B5 for quoting, fish and aliases; B8 for the 200-char bracketed paste; B1 for retypes.
2. **Root derivation.** See B7. Submodule (no `commondir`), non-git, bare and Auggie correctly return "". Nested worktrees
   work because the nearest `.git` file wins.
3. **Missed call sites.**
   - `_folder_retype` and `_swap_in` run_dir (B1).
   - The 404 ordering (B2).
   - The SPA `t.cwd === targetCwd` copies (B6) and the labels (B6).
   - `term_run.py:470` is correctly left in the worktree (its allowlisted commands should run where the session works).
   - Every other `.cwd` consumer in `term_vt.py` is accounted for by the plan: 1897, 2075-2123, 2149, 2203, 2499, 2508, 2556,
     2631.
4. **Concurrency §B: verified.** Checked every `with _LOCK` section on the open path (3133-3240, 3260-3290): `_reap` (pops
   only), `_live_list`/`_term_title` (shlex only), `_refresh_fg`/`_fg_pgid` (one syscall). No fork, subprocess or sleep under
   `_LOCK`. `spawn()` is outside it. The 3 s cap (`FOLDER_SPAWN_WAIT`, 1278) is bounded by spawn time, since `reserved.set()`
   fires in `finally`. No deadlock or starvation. K-1 overflows are independent. Slot use equals the old behaviour
   (K shells either way). The cross-worktree takeover is real; `_swap_candidate` still requires `viewers == 0`, so it only
   displaces unwatched clients. The "taken" path for `cwd` mode spawns one full login shell per extra opener (11-13 s of rc
   files each, contending on pyenv's lock per the `_inject_argv` docstring). That is not a regression, but it is the cold-burst
   cost to mention next to E3.
5. **409 and the SPA.** `ext_vt.js` 2985-2997 renders `res.j.error` for any non-ok status; `mountInto` (3880+) the same;
   `ext_launch.js:63-71` `alert(j.error)`; `ext_cr_term.js:563` toasts it. Phone and tablet use the same path. No SPA change
   is needed for the 409 itself. The real issue is B2/B3.
6. **S1 and S2.** See B9 and B4.
7. **Test RED-ness.** See B1, B4, B8. L1, L2a, L4, `TestOpenPtyAtRoot` (typed-line assertions) and the overflow cwd assertions
   do go RED on revert.
8. **Async inventory spot checks.**
   - True: #1 (71), #4 (3380 `ps`, 3397 `lsof`), #7 (osascript `timeout=10` at 212), #12 (5 s `setInterval`, `app.js:1454`),
     #20 (`tunnel.py` 266/272), #21 (`store.py:451`), #22 (no git/gh subprocess in the package).
   - Missed or under-stated:
     - `_background_target` (`term_vt.py:3365`, also `term_launch.py:191`): reads the daemon roster and a transcript tail
       synchronously on every resume handler. Unmeasured, so add a row.
     - #18 `resolve_spawned(new_only=True)`: it globs and stats EVERY transcript under `PROJECTS` per candidate
       (`newest_session_in_cwd`), so it is O(all sessions), not "ms". Mark as unmeasured.
     - `GET /api/term/list` also runs `resolve_spawned()` throttled on the 2 s poll, on the request thread.

## Overall clean plan (v2 plus accepted fixes)

Keyed to the plan's legs. Everything not mentioned stays as in v2.

- **Design A, `place()`.**
  - Handle `cwd=""` (B2): the routes call `recorded_cwd` and `place` BEFORE the 404 for `cwd` and `new`.
  - Deleted worktree, resume: run from the nearest existing ancestor, with the hint as a note. 409 only if that ancestor is the
    root or nothing (B3, replaces E1's default).
  - `git_worktree_root`: resolve a relative `gitdir:` against the `.git` file's directory; reuse an existing folder pty's
    `cwd` string when `realpath` matches (B7).
- **Design A, term_vt.**
  - `Pty.run_dir` is set at the 3229, 3458 and (kept) 2411 claims; `_swap_in` gains a `run_dir` argument (B1).
  - `_inject_argv` reads `pt.run_dir` and emits `sh -c 'cd "$0" && exec "$@"' <wt> argv...` (B5) when it differs from `pt.cwd`.
  - `run_dir` stays out of `_fg_public` (B10). Add a notice to a displaced viewer (B11).
  - Client: drop the `t.cwd === targetCwd` shortcut (B6). `_term_title` uses `run_dir` while claimed.
- **L1.** `recorded_cwd` falls back to `parse_any` on an empty tail result (B9). Add the three fixtures.
- **L2a/L2b.** Add the relative-gitdir, symlink, and unmapped-layout table rows (B7); the cwd/new deleted-worktree route tests
  (B2); the retype and swap_in tests (B1); the 199/201-char golden lines (B8).
- **L2c.** Instrumented-lock hold-time assertion instead of wall clock; counts not identity; label guard tests (B8).
- **L3.** The `TestQuietSeed` pty must have a `Screen`; patch `INJECT_MIN_WAIT` too (B4).
- **L0.** Run (a) through the real `_inject_write` path with >200-char and quoted-path cases, with a fish shell and an alias if
  available. Make (c) a post-L2 server check.
- **Inventory.** Add `_background_target`; re-label #18 as unmeasured O(all transcripts).
- **Decisions for the user.** E1 default becomes "resume from the nearest ancestor, refuse only at the root"; E2 unchanged; E3
  unchanged. The new decision: confirm that bare-repo layouts stay unmapped.

## Not examined
- `resume_argv`, `_start_backstop`/`_resume_backstop` body, `_retry_with_attach` internals (only the retype call), and the
  `Pty.__init__` field list beyond what the grep showed.
- The `store.record_fork`/`resolve_fork_child` use of cwd (the plan's `_run_dir` swap was taken as specified).
- Real zsh, bash and fish behaviour of `exec` in a subshell and `sh -c` job-control pgids: reasoned, not run (L0's job).
- Whether Claude Code re-enters a worktree on resume, and its `worktree-state` handling.
- Measured costs in the inventory (#10, #13, #14).
- `docs/`, the other prior terminal reports, and the Control Room `ext_cr_*` flows beyond the call sites cited.
