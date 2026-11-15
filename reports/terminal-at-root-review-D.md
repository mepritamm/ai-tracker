# Review D (opus): plan v4, terminal-at-root

Scope: what v4 adds (§A2 recreate, the confirm dialog, L5/S3) plus a check that C1–C5 are folded in. User decisions (2026-11-15/16) are treated as fixed.
Method: grep + `sed` ranges on the source, and one git experiment in a scratch repo (git 2.54, deleted afterwards).

**Verdict: NOT READY.** One blocker (D1) breaks the branch/base rule for the most common way a worktree gets removed. The rest are majors or nits with small fixes.

## Git experiment (evidence for D1)
Steps: `worktree add w1 -b b1`, `worktree add w2 -b b2`, then `rm -rf w1` and `git worktree remove w2`.
- After those steps, `.git/worktrees` holds only `w1`. **`git worktree remove` deletes the admin entry, including its `HEAD` and `logs/HEAD`, at once.**
- After `git worktree prune`, `.git/worktrees` is gone entirely.
- So the admin entry survives only for a worktree deleted by hand (`rm -rf`), and only until the next prune. That prune can come from any `worktree prune` or from `gc` (default `gc.worktreePruneExpire` 3 months, run by auto-gc).

## Findings

### D1 — BLOCKER: the admin-entry source of B (rule 1) and of the base SHA (rule 4) is missing on the normal removal path
- **Defect.** Plan §A2 rules 1 and 4 (`reports/terminal-at-root.md` ~285-300) read `G/HEAD` and `G/logs/HEAD` from the "unpruned admin entry". In this ecosystem a worktree is removed with `git worktree remove`:
  - the cleanup skill (rule 7);
  - the pending-work worker (conventions rule 6 exception: non-force `git worktree remove` / `git branch -d`);
  - Claude Code's ExitWorktree remove.

  All three delete the admin entry. The pending worker also `branch -d`s the branch.
- **Repro.** Worktree `wt-x` on branch `feat` is cleaned up (`worktree remove` + `branch -d`), then the user clicks Resume.
  - Rule 1 falls back to the transcript `gitBranch`, which is fine.
  - Rule 4 finds no reflog and falls back to "main checkout HEAD". That is whatever branch the primary checkout happens to be on, possibly an unrelated feature branch, not the base.
  - Expected: base = the branch's last commit, or an honest "unknown" with a sane base.
  - Actual: a silent wrong base, presented as "from main checkout HEAD". The plan's evidence never tested this, and its prose treats the admin entry as the normal source.
- **Direction.** Treat the admin entry as a *bonus* source, not the primary one. Add sources in this order:
  1. the admin reflog (hand-deleted worktrees only);
  2. `git -C <root> reflog show --format=%H refs/heads/B`. This does not work either: `branch -d` removes the branch reflog too, so drop it.
  3. a **SHA captured by the app before removal**. Not available either: the app is read-only on removal by others.
  4. the *default branch tip*: `refs/remotes/<remote>/HEAD`, else `main`/`master`/`develop`, never the primary checkout's arbitrary HEAD.

  Then state in the `summary` that the old commits are only reachable if merged ("branch was deleted after merge; new branch from <default> <sha7>").
  - Must not change: never guess a SHA, never use `-B`.
- **Way.**
  - `term_gate.recreate_plan`: replace the `HEAD of main checkout` fallback with `_default_base(root)`, which tries `git symbolic-ref --quiet refs/remotes/origin/HEAD`, else the first existing of `refs/remotes/*/main`, `refs/heads/main`, `master`, `develop`, using read-only probes already on the allowlist. Add `symbolic-ref --quiet` to the conventions allowlist.
  - Rewrite the A2 rule-1/rule-4 prose so "transcript `gitBranch`" is the primary source of B and the admin entry is optional.
  - In the token, include the base SHA (already there).
- **Red test.** In `tests/test_term_gate.py`:
  - Make a tmp repo, add worktree `w` on branch `f` with one commit, run `git worktree remove w`, `git branch -D f` (setup only), then `git checkout -b unrelated` in the main checkout plus a commit.
  - Assert `recreate_plan(...)['base']` == `main`'s SHA, not `unrelated`'s.
  - Red on v4 (it picks `unrelated`).
  - Add a second case with `rm -rf w` (admin entry kept): assert base == `f`'s last SHA (from `G/logs/HEAD`).

### D2 — MAJOR: locating the admin entry by basename is wrong, and a repo-wide `prune` destroys sibling sessions' only base source
- **Defect.** The admin dir name is not guaranteed to equal the worktree basename. git appends a number on collision (e.g. two worktrees named `api` in different parent dirs give `api` and `api1`). The plan writes `G` without saying how it is found.
- **Second defect.** `git worktree prune` (step "only when registered-but-missing") prunes **every** missing registration in the repo. Session A's recreate therefore deletes session B's hand-deleted admin entry, and with it B's reflog base. B's next plan silently degrades. The token re-plan catches the change, but the user only sees a different summary.
- **Repro.** Remove `w1` and `w2` by `rm -rf`, then confirm the recreate of `w1`. B's plan for `w2` goes from "from <sha> (last commit)" to the default-base fallback.
- **Direction.**
  - Find `G` by scanning `<common>/worktrees/*/gitdir` for content == `<path>/.git`.
  - Replace the repo-wide prune with a targeted unregister. Prefer `git worktree add` on a path whose registration is missing: git 2.54 accepts the path only when the stale entry is "missing but registered", in which case it requires `-f`, and `-f` is banned. Pruning is therefore unavoidable.
  - So the honest fix is: before pruning, **snapshot** every missing entry's `HEAD`/`logs/HEAD` last SHA into the app's state (`store._save_json` → a new `worktree_heads.json`, app-owned, gitignored), keyed by realpath, and read that snapshot in rule 4.
  - Simpler alternative (preferred, ponytail): accept the loss, document it in the PR notes, and make the summary say "base: default branch (reflog pruned)".
- **Way.**
  - `term_gate._admin_dir_for(root, path)`: scan the `gitdir` files.
  - L2 test notes: add "prune is repo-wide; sibling reflogs are lost" to PR notes, or add the snapshot (pick one at reconcile; I recommend the doc-only route).
- **Red test.**
  - Collision case: create two worktrees with basename `api` in different dirs, `rm -rf` the second, and assert `recreate_plan` reads `api1`'s reflog. Red with basename lookup.

### D3 — MAJOR: the per-path lock does not cover two server processes, or the external path racing the in-app path
- **Defect.** `_RECREATE_LOCKS` is in-process. The repo routinely runs two trackers: the user's live 8787 and `make serve` on 8790 (memory: tracker-server-lifecycle). Two tabs (one per server), or an external `/api/term/open` on one and an in-app `/api/term/pty` on the other, can both pass the "path missing" re-check.
- **What follows.** git itself makes the second `worktree add` fail ("already exists" / "is a missing but already registered worktree"), so nothing is corrupted. But the second click shows a raw git error instead of resuming.
  - For rule-3/4 plans there is a worse case: both run `worktree add -b <B>-cont-<sid8>`. The second fails on the existing ref and never retries with `-2`. That is fine, but it still errors.
- **Repro.** Two servers. Click Resume on both within ~200 ms. One gets a 500/409 with git stderr.
- **Direction.** Make "lost the race" success-shaped. After any failed `worktree add`, re-run the in-lock re-check once:
  - path now a live worktree of `root` → proceed to resume;
  - otherwise surface the error.

  Do not add a cross-process file lock (overbuilt). Within one process the external and in-app routes share `term_gate`, so they are already covered. State this explicitly in §B 9a.
- **Way.** `term_gate.recreate_worktree`: `ok = _git_add(...)`; `if not ok and git_worktree_root(path) == root_wt: ok = True`.
- **Red test.** Monkeypatch `_git_add` so it first creates the worktree for real (simulating the other process) and then returns failure. Assert `recreate_worktree` returns `(True, path)`. Red on v4.

### D4 — MAJOR: the conventions rule-6 exception text has gaps
1. It says "at the path the session last ran in" but does not bind the path to the repo. Add: *"`<path>` must be the realpath recorded for that session (transcript cwd / `worktree-state.worktreePath`), must be outside `<root>`'s own work tree, or inside its `.claude/worktrees/`, and its parent dir must already exist."* Otherwise a crafted transcript cwd (`/etc/x`, `~`) becomes a `worktree add` target.
2. "never writes into an existing non-worktree directory" also needs: **"never creates missing parent directories"**. `git worktree add` does `mkdir -p` on the parents.
3. The allowlist is missing `symbolic-ref --quiet` (D1) and the `gitdir` file reads (D2), which are file reads and fine but worth naming.
4. It must say that the token is **server-issued, bound to sid, and single-use / short-lived** (e.g. 10 min). Today "hash of the plan" is replayable forever by anyone with write access who saw the 409.
5. The tunnel/read-only gate is assumed ("routes are write-gated already"). Name it: "never from a read-only/tunnel-visitor request" (`test_tunnel_readonly.py` should assert a 403 for a recreate POST).

- **Way.** Edit the drafted blockquote in §A2. Add `_valid_recreate_path(path, root)` in `term_gate`. Make the token HMAC(server-secret, sid|path|branch|new|base|expiry).
- **Red tests.**
  - Transcript cwd `/tmp/x/y` with parent `/tmp/x` missing → `recreate_plan` returns no `recreate` key. Red on v4.
  - A tunnel visitor POSTs `{recreate: token}` → 403.
  - A token older than its TTL → 409 with a re-plan.

### D5 — MAJOR: confirm wiring across the 5 entry points is under-specified for status propagation
- **Defect.** Status handling differs per entry point:
  - `ext_cr_term.js:49` `j()` and `ext_cr_boot.js:785` `postTermOpen` already keep `status`, so they are fine.
  - `ext_launch.js:29` `post()` returns the raw Response. That is fine too, but `openTerm` (60) must read `.json()` on non-ok; the plan doesn't show it.
  - `_openVTFresh` (2932) / `mountInto` (3660) retries must go through the **same `openGen` supersede guard** (2880-2928). Otherwise a confirm that sits open while the user switches session retries against the old sid and mounts a stale pty into the new pane.
- **Also.** `window.confirm` is synchronous and blocks the poll loop (2 s polls queue up). That is acceptable. But on iOS standalone-PWA or in a cross-origin iframe preview it can return false without showing, which turns into a silent no-op.
- **Direction.**
  - Capture `gen` before the confirm and drop the retry if `gen !== openGen` after it.
  - If `confirm` returns false *and* took less than ~50 ms (auto-suppressed), show the server text via the existing `notify` toast instead.
  - Resolve `window.ExtVT` lazily at click time. `ext_vt.js` sorts last in `page.py:17`'s one script, so a module-scope capture in `ext_cr_*`/`ext_launch` would be `undefined`.
- **Way.** Inside `ExtVT.confirmRecreate(body, retry, stillCurrent)`, pass `stillCurrent = () => gen === openGen` from the two in-app sites and `() => true` from the external ones.
- **Red test.** Use the jsdom/static test pattern already in `tests/` (grep test for `ext_vt`): assert that the source of each of the 5 call sites contains `confirmRecreate(`, and that the in-app ones pass a 3rd arg. A behavioural test: stub `confirm` → true, flip `openGen` inside the stub, and assert there is no second fetch.

### D6 — MAJOR: L5/S3 slot accounting and the "warm shell finishes" hand-off
- **Defect 1.** The `_live_count() + 2 <= MAX_TERMS` check is not atomic with the spawn. K cold openers each read the count outside `_LOCK` and each pass it. Only one of them reserves `_FOLDER_SPAWNING[root]`, so only one warm shell spawns, which is fine. But K dedicated claudes plus 1 shell can overshoot 12, because each dedicated spawn is checked separately. Verify that the dedicated spawn goes through the existing 429 path. The plan doesn't say.
- **Defect 2.** When the warm shell settles, nothing ever claims it until the next opener arrives. That is fine. But the dedicated overflow claude for session S is still alive, so a later Resume of S must hit `_session_pty` and return the overflow tty, not type into the warm shell. Item 6 covers this only if `_session_pty` indexes overflow ptys by sid. Confirm that it does, and add a test.
- **Defect 3.** A warm shell that fails startup (`startup_done` never set) keeps `_FOLDER_SPAWNING[root]` reserved until `finally`. If the fork hangs, every opener keeps going dedicated forever. That is graceful, but there is no reap of a never-settled shell. Add the existing settle timeout and mark it `startup_done` or kill it.
- **Direction.** Count and spawn under one `_LOCK` critical section that reserves a slot (`_RESERVED += 1`), with the fork outside it. Assert the overflow→sid mapping.
- **Way.** Edit the `term_vt` lookup block (~3133-3240), using the same reserve pattern as `_FOLDER_SPAWNING`.
- **Red tests.**
  - With 11 live terms, start 3 cold openers concurrently (threads, fake spawn sleeping 0.5 s): assert ≤12 live and the rest 429.
  - Open S cold (dedicated), let the warm shell settle, open S again: assert the same tty and no typed line in the root shell.

### D7 — MINOR: the repo-gone branch should also cover "root exists but is no longer a repo / is a different repo"
- **Defect.** The clone was deleted and re-cloned at the same path, so `root` exists but the branch doesn't, or the commondir differs.
- **Direction.** Recompute `git_worktree_root` / commondir for `root` inside the plan and compare it with the transcript's.
- **Way.** `recreate_plan`.
- **Red test.** Re-init the tmp repo at the same path and assert rule 4 with a default base, not the stale reflog SHA (the `cat-file -e` already guards this; a test only).

## C1–C5 folded?
- C1 (no `shutil.which`, keep `argv[0]`): stated in the reconciliation table. The §A design body should restate it at the typed-line builder. Nit.
- C2 (`meta=` param, no recursion): folded.
- C3 (`p.cwd` when there is no sid and no claim): folded.
- C4 (0.5 s fake spawn, < 0.2 s hold): folded.
- C5 (`_foreground_is_claude` with `sh -c`): folded in L0a.

The v4 recreate path adds new fg-detection cases: `sh -c` + `exec` after a `cd` into a *just-created* dir. Covered by C5's test. OK.

## Overall clean plan (delta to v4)
- **A2 rules 1/4:** the transcript `gitBranch` is primary. The admin entry is located by `gitdir` content and is optional. The fallback base is the default branch tip (`_default_base`), never the primary checkout's HEAD (D1, D2).
- **Prune loss of sibling reflogs:** document it in the PR notes (D2).
- **`recreate_worktree`:** a failed `add` re-checks once and treats "now a live worktree" as success (D3).
- **Path validation:** `_valid_recreate_path`. The token becomes an HMAC with expiry. The rule-6 text gets the five additions (D4).
- **`ExtVT.confirmRecreate`:** add the `stillCurrent` guard, the suppressed-confirm toast fallback and the lazy `window.ExtVT` lookup (D5).
- **S3:** atomic slot reservation, an overflow-by-sid lookup test and a warm-shell settle timeout (D6).
- **Re-clone case:** a test (D7).

## Not examined
- The `sh -c` line under fish/nushell login shells.
- Bare/`--separate-git-dir` layouts (declared out of scope).
- The actual `_session_pty` overflow indexing (only flagged in D6).
- Phone layout of `window.confirm` text length (the summary may be long; consider truncating to 300 chars).
