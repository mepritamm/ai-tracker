# Review E: adversarial re-review of plan v4.1 (terminal-at-root)

Reviewer: opus, 2026-11-16. Read-only on source. Scratch repo under `~/.claude/jobs/68c7528c/tmp/rvE` (git 2.54.0, Apple Git-157), deleted after.

## Ground truth checked

1. **`gitBranch` is recorded, and it follows cwd.** A real transcript
   (`~/.claude/projects/...pending-work-worker/8b05c822-....jsonl`) has `gitBranch` on every line: 21 x `main` while cwd = the repo
   root, 2132 x `worktree-pending-work-worker` after EnterWorktree. So "the latest `gitBranch`" is a valid primary source, provided
   L-S1 reads it from the same latest line as cwd. `_tail_scan` does not return it today; `claude.py:1830` reads it only in the full
   meta pass. The leg must add it to the tail fields, not reuse `meta` from a stale cache.
2. **The hand-deleted admin entry survives `rm -rf`.** After `rm -rf wt`, `.git/worktrees/wt/{gitdir,HEAD,logs/HEAD}` are all present,
   and the last `logs/HEAD` new-sha is the worktree's last commit. Rule 6(i) holds.
3. `git worktree add <path> feat` on a missing-but-registered path: `fatal: '../wt' is a missing but already registered worktree; use
   'add -f'`. The prune-first rule is needed and correct.
4. A second `add` on the same path after a winner: `fatal: '../wt' already exists`. The D3 re-check path is reachable.
5. **New:** while `wt` is missing-but-registered, `git branch -D feat` says `cannot delete branch 'feat' used by worktree at .../wt`. git
   still treats the dead registration as a checkout of `feat` (finding E1).

## D1-D7 status

| # | Fixed? | Note |
|---|---|---|
| D1 | Yes | The transcript `gitBranch` is primary and the fallback is the default tip, never the checkout HEAD. Verified against a real transcript (above). |
| D2 | Yes | Lookup by `gitdir` content is correct. Prune stays scoped to "target still registered". |
| D3 | Partly | It is inconsistent with the pre-add re-check (E3). |
| D4 | Yes | Path binding, no parent creation, allowlist, HMAC with single use, and the 403 gate are all present. |
| D5 | Partly | The suppressed-confirm path dead-ends (E2). |
| D6 | Partly | The timeout has an ordering race (E4). |
| D7 | Yes | |

## Findings

### E1 (major): the target's own dead registration is counted as "checked out elsewhere"
- **Defect.** Plan §A2 rules 4/5 (`reports/terminal-at-root.md` about lines 318-321) decide "B checked out in another live worktree"
  from `worktree list --porcelain`. In the main case the plan targets (a hand `rm -rf`), the target path is still registered on `B`.
  `worktree list` lists it with `prunable` and git refuses to treat `B` as free (repro 5).
  **Repro:** `worktree add -b feat ../wt`, commit, then `rm -rf ../wt`.
  - Actual: the plan reports `branch-tip` ("`feat` is checked out at `<the same path>`") and creates `feat-cont-xxxx`.
  - Expected: `base_kind=branch`, with `feat` re-attached after the prune.
- **Direction.** When classifying, exclude any porcelain entry whose `worktree` equals the target path or carries `prunable`. Do not
  change the prune rule or the allowlist.
- **Way.** In `term_gate.recreate_plan`, parse the porcelain blocks and skip a block if `realpath(worktree) == realpath(path)` or it
  has a `prunable` line, before testing `branch refs/heads/<B>`. Do the same filter in the in-lock re-check.
- **Test.** `test_hand_deleted_worktree_reuses_own_branch`: in a tmp repo, `rm -rf` the worktree, then expect
  `plan["base_kind"] == "branch"` and `new_branch is None`. It is red on v4.1 logic (branch-tip).

### E2 (major): a suppressed confirm leaves phone/PWA users unable to recreate at all
- **Defect.** §A2 Confirm wiring (about lines 410-416). Under 50 ms with false, the helper shows a toast of the server text and stops.
  On iOS standalone PWA, where confirm is always suppressed, every click repeats that toast, so recreate can never happen there. That
  breaks "every viewport".
  **Repro:** stub `window.confirm = () => false` so it returns instantly.
  - Actual: toast only, and `retry` is never callable.
  - Expected: a path to confirm.
- **Direction.** The fallback must still offer the confirm action. Keep the token flow and the `stillCurrent` guard unchanged.
- **Way.** In `ExtVT.confirmRecreate`, the <50 ms branch renders the existing notify/toast with a "Recreate" action button whose
  handler runs `if (stillCurrent()) retry({recreate: token})`. If the toast helper has no action slot, use a minimal inline
  `<button>` in the terminal header note area (L4 already renders `term_home_note` there).
- **Test.** A Node test for `confirmRecreate` with confirm stubbed to instant false: assert that an action element exists, and that
  invoking it calls `retry` once with the token. It is red today (no action).

### E3 (minor): the pre-add and post-add "already a worktree" checks disagree on branch
- **Defect.** §A2 Execution: the in-lock re-check accepts *any* live worktree of `root` at `path` ("proceed with no git work"). The D3
  lost-race check accepts only `plan.branch`/`plan.new_branch`. Two sessions recorded in the same worktree (common) get different
  `new_branch` values (`-cont-<sid8>`).
  **Repro:** sessions S1 and S2 share deleted worktree W with B deleted.
  - Same server, S2 then S1: S1 silently resumes on `B-cont-<S2>`, which its confirm never named.
  - Two servers racing: S1 gets a raw git error for a worktree that is fine.
- **Direction.** Make one rule. Any live worktree of `root` at `path` is success in both checks, and the response reports the
  *actual* branch.
- **Way.** Factor `_live_wt_branch(root, path) -> str | None` and use it in both spots. On success, put
  `"note": "worktree already recreated on <branch>"` in the open response and toast it.
- **Test.** `test_lost_race_other_session_branch_is_success_with_note`: precreate W on `B-cont-aaaaaaaa`, run S1's plan whose `add`
  fails, and expect ok plus a note naming the actual branch. Replace `test_lost_race_wrong_branch_is_error` (it asserts the opposite).

### E4 (minor): the warm-shell timeout marks `startup_done` before deciding to kill
- **Defect.** §B 4 (about lines 480-484). On `False`, the existing `finally` sets `startup_done=True`, and only then is the
  close-if-wedged check made. In that window a resume opener sees a settled-looking idle-less shell, passes the
  `fp.startup_done` gate, and claims it. Then either it types into a wedged rc prompt, or the close kills the shell it just claimed.
  **Repro:** a fake shell that never prints a prompt, plus an opener released at the 120 s instant (inject a hook between `finally`
  and the close).
- **Direction.** The kill decision and the flag flip are atomic with respect to claimants.
- **Way.** In the warm thread, under `_LOCK`: if not settled and there are no viewers and `fp.claimed_by is None`, set
  `fp.closing=True` and remove it from `FOLDERS` before `startup_done=True`. Claim branches skip `closing`. Call `close_pty` after
  the lock is released. The slot itself is fine: `_SLOTS_RESERVED` is released at the fork, and `_live_count` drops on close.
- **Test.** `test_wedged_warm_shell_not_claimable_during_close`: monkeypatch `_folder_settled` to return False, and assert that an
  opener racing the flip gets a dedicated pty, not that shell.

### E5 (nit): detached HEAD gives `gitBranch:"HEAD"`
- **Defect.** Rule 3 takes `B="HEAD"`. `refs/heads/HEAD` does not exist, so the new branch would be `HEAD-cont-xxxx`.
- **Direction.** Treat `""`/`"HEAD"` as no branch, which falls to `worktree-<basename>-cont-<sid8>`.
- **Way.** One guard in `recreate_plan`.
- **Test.** `test_detached_head_branch_name`.

### No defect found
- **HMAC secret.** It is per process. A restart or the other server invalidates the token, which leads to a re-plan, never a write.
  This is correct and costs at most one extra click. Document "a restart re-asks".
- **The <50 ms heuristic.** A false positive (a human cannot answer that fast) only yields the toast, which E2 makes actionable. There
  is no unsafe direction.
- **Token consumed before a git failure.** The user re-clicks and gets a fresh plan. Acceptable.

## Verdict: READY WITH NITS
E1 and E2 must be folded into L2b/L4 before implementation. Both are local changes of a few lines with tests named above. E3-E5 can
be folded in the same legs.

## Not examined
`term_vt.py` claim code paths line by line (only the plan text was attacked), Auggie sessions, and Windows/WSL paths.
