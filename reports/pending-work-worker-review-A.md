# Adversarial review A — pending-work worker plan v1 (sections 3, 4, 5, 8)

Reviewer A, opus, 2026-11-15. Scope: will the scanner find every pending worktree (C1), and can the cleaner delete unpushed or uncommitted work, or a live session's files (C6)? Config/UI/server wiring belongs to reviewer B.

Evidence came from read-only disk inspection (file reads and Python over `~/.claude/projects`, `~/.claude/jobs`, `~/.claude/sessions`, `/tmp/claude-501`), plus grep/sed on the worktree. The worktree guard blocked git commands outside this worktree, including a throwaway temp repo. Git-behaviour claims are therefore stated from git's documented behaviour, and each one has a test below that proves it on a temp repo.

**Count: 4 blockers, 8 should-fix, 5 nits.**

---

## Blockers

### B1. Discovery misses about 78% of repos (C1)
**Defect.** Plan §3 "Discovery" seeds repos from `registry.all_sessions()`. That has two limits:
- It calls `ClaudeProvider.list()` → `list_sessions(limit=200)` (`providers/claude.py:849,880`). Only the 200 newest of 238 transcripts are included.
- Each row's `cwd` is the transcript's **first** cwd only (`_session_meta`, `claude.py:269` `if not cwd and o.get("cwd")`).

148 of 238 transcripts change cwd mid-session. Orchestrators start in non-repo parent dirs (`.../AIengg`, `.../VIDA20`) and then `cd` into repos.

**Repro (measured).**

| Seed source | Repos found |
|---|---|
| Top-200 first cwds | 5 |
| Every cwd in every transcript | 23 |

The 18 missed repos are all of `VIDA20/repos/dw-*`, `theAppWorkspace/*`, `dw-vida-chat-ai`, and others. Expected: every repo with a worktree is listed.

A second miss: Claude Code prunes transcripts after 30 days (`cleanupPeriodDays` is unset, so the default applies). With an interval of up to 12 months, a repo whose sessions have aged out disappears.

**Fix direction.** Seed discovery from every cwd ever recorded, not from the list rows. Keep the list route untouched: `list_sessions` must not change.

**The way.**
1. Add a seam function `registry.all_cwds()`. It unions `p.cwds()` for providers that implement it; otherwise it falls back to `{r["cwd"] for r in p.list()}`.
2. Add `ClaudeProvider.cwds()`. It globs `config.PROJECTS/*/*.jsonl`, collects every distinct `"cwd"` value (substring prefilter on `'"cwd"'`), and caches by `(path, mtime)` in the module.
3. `pending.discover_repos` also unions:
   - `cwd`, `originCwd` and `worktreePath` from every `JOBS_DIR/*/state.json`;
   - `cwd` from every `LIVE_SESSIONS_DIR/*.json`;
   - the `git_roots` from `scan_tmp` (S5);
   - a **sticky** `repos[]` list persisted in `pending.json` from earlier runs. A repo is dropped only when its common dir no longer exists.
4. For a cwd that no longer exists, walk up to the nearest existing ancestor. Do not only strip `/.claude/worktrees/<x>`.

*Possibly wider than the defect.* The two-function seam addition is the minimal on-seam form. Reading transcripts directly inside `pending.py` would be smaller but forks the provider seam (conventions rule 3).

**Test.** In a temp `PROJECTS`, write one transcript whose first line has `cwd=<tmp>/parent` (not a repo) and whose later line has `cwd=<tmp>/parent/repo/.claude/worktrees/w`. `discover_repos()` must contain `realpath(<tmp>/parent/repo/.git)`. It is red on v1, because the first cwd is not a repo.

### B2. `--git-common-dir` is relative in a primary checkout, so repo dedupe collapses (C1)
**Defect.** Plan §3 resolves each cwd with `git -C <cwd> rev-parse --git-common-dir` and dedupes by the result. Run inside a primary (non-linked) checkout, git prints the relative `.git`. Inside a linked worktree it prints an absolute path, which matched what I saw in this worktree.

**Repro.** Two sessions with cwd at two different primary checkouts. Actual: both keys are `".git"`, so one repo is dropped. Later `git -C .git worktree list` resolves against the server's cwd, not the repo. Expected: two distinct absolute keys.

**Fix direction.** Always use absolute, realpath'd common dirs.

**The way.** Change `_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")`. The flag needs git ≥ 2.31; this machine has 2.54. Then apply `os.path.realpath`. Every later call takes `-C <dirname(common)>` for a non-bare repo.

**Test.** Build two temp repos. Give sessions cwds at each primary. `len(discover_repos()) == 2`, and every key is absolute.

### B3. "Reclaimable" has no idle guard, so a fresh worktree under a live session or parked job is deleted (C6)
**Defect.** Plan §3 classify: `reclaimable` is `ancestor ∧ ahead==0 ∧ clean`. Plan §5.2 adds only "no live pid in `LIVE_SESSIONS_DIR`". A worktree just cut from base satisfies the triple test exactly. That is the state after `EnterWorktree`, after `Agent isolation:"worktree"`, and of any job worktree before its first edit.

The live guard cannot see:
- **subagent isolation worktrees.** They run inside the parent's pid, and the parent's `sessions/<pid>.json` `cwd` is the parent's dir.
- **parked or blocked jobs.** 57 jobs are `blocked`, and 24 `state.json` files carry a `worktreePath`. §5.3 protects `blocked` jobs only for scratch, not for worktrees.
- **non-Claude providers.**

`last_activity` is computed in the item shape but never used by `classify`.

**Repro.** This very worktree at creation time: HEAD `b3d6230` == `personal/main`, no upstream, no files yet. It reads as `ancestor` true, ahead 0, clean, so `reclaimable`. A subagent in `.claude/worktrees/agent-xyz` doing a 5-minute read before its first edit gets `git worktree remove`d. Expected: keep.

**Fix direction.** Add an idle and ownership test to `reclaimable`. Keep the skill's triple test verbatim; this adds terms, it does not replace them.

**The way.** In `classify(wt, ctx)`, `reclaimable` also requires all three of these:
1. **Idle.** `now - last_activity >= grace`, where `grace = max(interval_s, PENDING_GRACE_FLOOR)` (S6). `last_activity` is the max of:
   - the mtimes of `<common>/worktrees/<name>/{HEAD,index,logs/HEAD}` (git writes these on checkout, commit and add; `status --no-optional-locks` does not);
   - the worktree top-dir mtime;
   - the newest transcript any of whose cwds realpath under the worktree (from B1's cwd map).
2. **No unfinished job.** No `JOBS_DIR/*/state.json` with `realpath(worktreePath|cwd)` equal to or under the path has `state ∉ {done, failed, stopped}`.
3. **No live session.** No `LIVE_SESSIONS_DIR/*.json` with `claude._pid_alive(pid)` has `realpath(cwd)` under the path.

Re-check all three in the TOCTOU re-inspect.

**Test.**
- A fresh worktree at base → `keep`, reason `"active <grace"`.
- The same worktree after `os.utime` of the admin files and dir to `now - 8d` → `reclaimable`.
- The same plus a temp job `state.json` with `state:"blocked"` and that `worktreePath` → `keep`.

Red-proof: drop the idle term, and the fresh worktree is removed by `run_once("safe")`.

### B4. `git worktree remove` without `--force` silently deletes gitignored files (C6)
**Defect.** Plan §3 measures cleanliness with `status --porcelain=v1 --untracked-files=normal`, which hides ignored files. Plan §5.2 relies on `worktree remove` refusing unclean trees. Git's definition of clean is "no untracked files and no modification in tracked files", and ignored files are not "untracked". So they are deleted with no refusal.

**Repro (measured).** 36 of the 54 `dw-vida-ai` worktrees hold a gitignored `.env`. Memory notes say vida worktrees boot from their own `.env`, and some carry creds or config. The same applies to local eval outputs, `config.json`/`flags.json` in tracker checkouts, and similar files. If such a worktree is otherwise reclaimable, actual: `.env` is gone. Expected: listed, kept.

**Fix direction.** Ignored, non-regenerable files make a worktree pending, not reclaimable. Do not add `--force` anywhere, and do not delete ignored files selectively.

**The way.**
1. In `inspect_worktree`, add `status --porcelain=v1 -z --ignored=matching --untracked-files=normal`. Collect the `!!` entries and drop a small regenerable set: `node_modules/`, `__pycache__/`, `.venv/`, `venv/`, `.pytest_cache/`, `.mypy_cache/`, `.DS_Store`, `*.pyc`.
2. Store `ignored: n` and `ignored_files: [first 20]`.
3. `pending` if `ignored > 0`, with the label `"1 local ignored file (.env)"`. `reclaimable` requires `ignored == 0`.

*Note.* The 36 vida worktrees then never auto-delete; Resume is the route. That is the correct fail-closed state, and the user may choose to widen the allowlist.

**Test.** Fixture A (merged, clean) plus `.gitignore` with `.env`, plus `A/.env`. `classify` returns `pending`. After `run_once("safe")`, `A/.env` is byte-identical. Red-proof: drop the ignored term, and `.env` is gone.

---

## Should-fix

### S1. "Unpushed" is measured against `@{u}` or `base`, which misses real unpushed commits (C1)
**Defect.** §3 inspect: if `@{u}` exists, `ahead = rev-list @{u}...HEAD`, else `base..HEAD`. When the upstream is a **local** branch (`branch.<b>.remote = .`, e.g. `--set-upstream-to=main` or `worktree add --track -b x p main`), and local `main` itself has unpushed commits, `ahead` reads 0 while the commits exist only on this machine. With several remotes, `base` is ambiguous (`refs/remotes/*/main`).

**Repro.** Branch `l` with upstream local `main`; `main` is 2 commits ahead of `origin/main`; `l == main`. Actual: ahead 0, so not pending. Expected: 2 unpushed.

**Fix direction.** "Not pushed" means "not reachable from any remote-tracking ref". That definition is offline, handles detached HEAD, and is upstream-agnostic. Keep ahead/behind against `@{u}` for display only.

**The way.** Add `unpushed = int(_git(p, "rev-list", "--count", "HEAD", "--not", "--remotes"))`. Classify `pending` on `dirty or untracked or ignored or unpushed > 0`. `reclaimable` additionally keeps `ancestor` (the skill's test). The label reads `"N unpushed (as of last fetch)"`.

**Test.** The local-upstream fixture above: `unpushed == 2` and verdict `pending`.

### S2. `classify` has no terminal case, and `keep` shadows a dirty primary checkout (C1)
**Defect.** §3 classify has two gaps.
- **No terminal case.** A clean worktree with no unpushed commits that is **not** an ancestor of base gets no verdict: no rule matches. This covers a pushed-but-unmerged feature branch, a squash-merged-and-pushed branch, or `qa` ahead of `develop`.
- **Wrong order.** `keep` (primary checkout or locked) is tested before `pending`, so uncommitted WIP in the primary checkout (where in-place sessions work) or in a locked worktree is never shown. C1 says "all … worktrees".

**Repro.**
- Primary checkout with 3 modified files → `keep`, not shown. Expected: shown as pending, never deletable.
- Clean feature branch on `origin/feat` → `None`.

**Fix direction.** Separate *what to show* from *what may be deleted*.

**The way.**
- `classify` returns `verdict ∈ {pending, missing, clean, unknown}` plus `deletable: bool` and `reason`.
- `deletable` is False for primary, bare, locked and the tracker's own `_HERE`, whatever the verdict.
- The final `else` is `clean` with reason `"pushed; not merged into <base>"` and `deletable=False`.
- `reclaimable` becomes `verdict == "clean" and deletable and ancestor and idle…` (B3).

**Test.**
- Primary checkout with an edit → `verdict == "pending"` and `deletable is False`.
- Fixture E (below) → `verdict == "clean"` and `deletable is False`.

### S3. `worktree prune` can orphan commits, and it is repo-wide (C6)
**Defect.** §5.2: "`missing` items get `git worktree prune`, which drops admin metadata only; the branch survives". That holds only for a branch checkout. There are three problems:
1. **Detached HEAD.** For a detached-HEAD worktree whose dir was deleted, the only refs to its commits are `<common>/worktrees/<n>/HEAD` and its reflog. Prune deletes both, so the commits become unreachable and `gc` later destroys them.
2. **Repo-wide.** `prune` touches *every* missing entry in the repo, not only the inspected one.
3. **Moved, not deleted.** A worktree that was `mv`'d loses its admin dir, including its **index** (staged changes). `git worktree repair` is the correct operation there.

Missing items also never report the branch's unpushed commits, which is a C1 gap: they are "worktree gone, but 5 commits unpushed".

**Repro.** `worktree add --detach W main`, commit X in W, `rm -rf W`, run in `safe` mode. Actual: X is unreachable. Expected: kept and listed.

**Fix direction.** Prune only when every missing entry in that repo has its HEAD contained in some ref.

**The way.**
1. For each `prunable` porcelain entry, take its `HEAD <sha>`.
2. Compute `contained = _git(repo, "for-each-ref", "--contains", sha, "--count=1")` is non-empty, and `unpushed = rev-list --count sha --not --remotes`.
3. A detached entry with `not contained` gets `verdict=pending`, label `"worktree gone · N orphan commits"`, and blocks prune for that repo.
4. Otherwise run `git worktree prune --expire=<grace>.seconds.ago`, so a just-moved worktree survives a grace window.
5. A branch entry with `unpushed > 0` is labelled `"worktree gone · branch has N unpushed"`.

**Test.** The detached repro: after `run_once("safe")`, `git cat-file -t X == "commit"`, and `worktree list --porcelain` still shows W.

### S4. The allowed-root check never matches on macOS, so scratch is never cleaned (C6 undelivered)
**Defect.** §2/§5.3 set `SCRATCH_ROOT = "/tmp/claude-%d"`, and the rule is "`os.path.realpath(path)` starts with one of the two allowed roots". On this machine `/tmp -> private/tmp`, so `realpath` gives `/private/tmp/claude-501/...` and never starts with `/tmp/claude-501`. Bare `startswith` also accepts `/tmp/claude-5010/...`. The §8 test hits the same trap: `mkdtemp` lives under `/var -> /private/var`.

**Repro.** A done job's scratch `/tmp/claude-501/<slug>/<sid>`. Actual: `kept: outside roots`, which is fail-closed but delivers no C6. Expected: removed.

**Fix direction.** Compare realpath to realpath on path boundaries, and pin the exact depth.

**The way.** Add `_under(path, root)`:
- `rp, rr = map(os.path.realpath, (path, root))`;
- `return rp != rr and os.path.commonpath([rp, rr]) == rr`;
- also require `os.path.relpath(rp, rr).split(os.sep)` to be exactly `[slug, sid]` for scratch, or `[id, "tmp"]` for jobs.

**Test.** Point `SCRATCH_ROOT` at a **symlink** to a temp dir. A done-job tree is removed. A sibling `<root>0/x` is kept.

### S5. Git trees inside tmp are kept but never listed (C1), and pin their job tmp forever (C6)
**Defect.** §5.3 keeps any tmp tree containing `.git`, which is right, but nothing feeds those repos into discovery. Measured: **50** git trees under `JOBS_DIR/*/tmp`. Most are linked worktrees, e.g. `jobs/84ee6941/tmp/ctrl` → `dw-vida-ai/.git/worktrees/ctrl`. **9 standalone repos** are reachable from no other source: `jobs/495e16aa/tmp/orpoc`, `c711bfa2/tmp/{a360-kb,oppapi,…}`, `ffd3fc52/tmp/gitproof/{up,down}`, `1974901a/tmp/base`, `aab75f6e/tmp/ac`. Scratch also has one: `/tmp/claude-501/.../scratchpad/ortest`.

The result:
- unpushed work in those trees is invisible (C1);
- a done job whose tmp holds one clean, merged linked worktree is never reclaimed (C6).

**Fix direction.** Report tmp git trees as items. Delete the tmp tree only after git has removed the worktree (two-phase across runs). Never `rmtree` a tree that holds a `.git` *dir*.

**The way.**
1. `scan_tmp` returns `git_roots[]`: for a `.git` file, the `gitdir:` → `commondir`; for a `.git` dir, the dir itself.
2. `discover_repos` adds them (B1). A linked worktree then flows through the normal worktree path (B3/B4 guards, non-force remove).
3. A standalone repo becomes an item `kind:"repo"`, `deletable=False`.
4. The next run sees no `.git` in the tmp tree, so the tree qualifies.

**Test.** A done job's tmp contains a standalone repo with 1 unpushed commit. `items` includes it with `unpushed == 1`, and the tree survives `safe`.

### S6. The scan interval doubles as the deletion grace period (C6)
**Defect.** §5.3 deletes scratch whose newest mtime is older than `interval_s`. Setting the scan to `"1d"` then makes a done job's tmp from yesterday deletable. After B3 the same applies to worktrees. A cadence knob silently shrinks the safety window.

**Fix direction.** Keep the coupling the user asked for, but give it a floor. Add no new config key.

**The way.** In `pending.py`, `PENDING_GRACE_FLOOR = 7 * 86400` and `grace = max(interval_s, PENDING_GRACE_FLOOR)`. Use `grace` everywhere §5 says `interval_s`.

**Test.** With `PENDING_INTERVAL="1d"`, a done-job tmp aged 2d is kept and one aged 8d is removed.

### S7. The lock is per checkout, so several cleaners can run at once (C6, low)
**Defect.** §2: `PENDING_LOCK = _HERE/pending.lock`. Every ai-tracker checkout has its own lock and `config.json`: the primary on 8787, the ~6 worktrees that run `make serve` test servers, and the CLI from any worktree. Two `safe` runs can interleave the §5.2 "re-inspect → remove" sequence over the same repos.

Git refusals and `rmtree` errors keep this mostly fail-closed, so it is should-fix rather than blocker.

**Fix direction.** The clean phase takes a single per-user lock. `pending.json` stays per checkout.

**The way.** Set `PENDING_LOCK = "/tmp/ai-tracker-pending-%d.lock" % os.getuid()`, or `~/.cache/ai-tracker/pending.lock`, and take it in `run_once`.

*Note for reviewer B.* Consider not calling `start_worker()` on non-default test ports.

**Test.** Two `run_once` calls with different `PENDING_FILE` but the default lock held → the second returns `{"running": True}`.

### S8. The §8 red-proof cannot go red, and the fixture misses the cases that matter
**Defect.** §8 says: "Red-proof: revert `classify`'s `ahead == 0` term → assertion 4 fails because C gets deleted." C has a local commit and no upstream, so `ancestor` is False and C stays non-reclaimable without the `ahead` term. Separately, B (dirty) is protected by git's own refusal. The test stays green, so it proves nothing.

The fixture also lacks every case in this review:
- pushed-unmerged branch;
- local upstream;
- ignored `.env`;
- fresh worktree;
- blocked job;
- detached missing worktree;
- dirty primary checkout;
- tmp standalone repo;
- symlinked root.

**Fix direction.** Every guard gets a fixture where *only that guard* stands between the tree and deletion. Its red-proof removes that guard.

**The way.** Add fixtures:
- **E**: pushed to `origin/e`, upstream set, clean, not merged. Only `ancestor` protects it, and `branch -d` would succeed because e is merged into its upstream.
- **F**: fresh worktree at base, mtime now (B3).
- **G**: A plus an ignored `.env` (B4).
- **H**: detached missing with an orphan commit (S3).
- **I**: dirty primary checkout (S2).
- **J**: local-upstream branch (S1).
- **K**: tmp standalone repo (S5).
- **L**: symlinked `SCRATCH_ROOT` (S4).

Red-proofs:
- drop `ancestor` → E is removed;
- drop idle → F is removed;
- drop ignored → `.env` is lost;
- drop the orphan check → `cat-file X` fails.

---

## Nits
- **N1. Interval upper bound.** §4 caps at "12 months" = 360d, so `"365d"` and `"52w"` (364d) are rejected. Use `<= 366 * 86400`. Also, `config.py` imports only `os` (`:1`); the plan must add `import re`. Test: `_v_interval("365d") == (True, "365d")`.
- **N2. Long-lived branches.** §5.2 `branch -d` after removing a worktree checked out on a shared long-lived branch (`develop`, `qa`) deletes the local branch, because it is merged into its upstream. No data is lost, but it surprises. Skip `branch -d` when the branch name equals `base`'s short name. Test: a worktree on `main` == `origin/main` is removed, and local `main` survives.
- **N3. Detached HEAD.** Skip `branch -d` when porcelain shows `detached`. The re-inspect right before `worktree remove` must re-run `unpushed` (S1). A detached commit made after that check is a documented ms-window residual.
- **N4. Reuse existing helpers.** Use `claude._pid_alive` (`claude.py:562`: rejects bool and non-positive pids, handles EPERM) and `claude.job_for` (`:787`: resumed-job mapping) instead of re-deriving liveness and job lookup in `pending.py`.
- **N5. Other providers.** Auggie and other providers have no live signal, so B3's idle term is their only guard. Document it.

## Not examined
- Windows/Linux paths.
- Repos on network or removable volumes (locked worktrees are kept, which covers them).
- `git status` cost on very large untracked trees: the 10s timeout makes those `unknown`/keep, which is safe but can permanently hide a worktree.
- Server/UI wiring: reviewer B.

---

## Clean-plan deltas (edits to plan v1)
1. **§3 Discovery.** Replace the `all_sessions()` seeding with `registry.all_cwds()`, backed by a new `ClaudeProvider.cwds()` over all transcripts and all cwd lines. Union in jobs `state.json` (`cwd`/`originCwd`/`worktreePath`), `LIVE_SESSIONS_DIR` cwds, `scan_tmp` `git_roots`, and sticky `repos[]` in `pending.json`. Resolve a missing cwd by walking up to an existing ancestor. (B1, S5)
2. **§3.** Use `rev-parse --path-format=absolute --git-common-dir` plus `realpath` for every repo key. (B2)
3. **§3 inspect.** Add `unpushed = rev-list --count HEAD --not --remotes`, and keep ahead/behind for display only. Add an `--ignored=matching` pass producing `ignored`/`ignored_files`, with a small regenerable allowlist. Add `last_activity` from the admin-dir mtimes, the dir mtime and the newest transcript cwd under the path. (S1, B4, B3)
4. **§3 classify.** Return `verdict ∈ {pending, missing, clean, unknown}` plus `deletable` and `reason`. Primary, locked, bare and own-`_HERE` set `deletable=False` but are still listed. The final `else` is `clean`, with reason "pushed; not merged". `reclaimable` = `clean ∧ deletable ∧ ancestor ∧ unpushed==0 ∧ ignored==0 ∧ idle≥grace ∧ no non-terminal job ∧ no live session under the path`. (S2, B3, B4)
5. **§5.2 missing items.** Prune only if every missing entry's HEAD is contained in a ref, and use `--expire=<grace>`. A detached orphan becomes pending "N orphan commits". Label "branch has N unpushed". Skip `branch -d` for a detached HEAD or a branch named like the base. (S3, N2, N3)
6. **§5.3.** Use realpath-vs-realpath `commonpath` with exact depth (`slug/sid`, `id/tmp`). Feed `.git` roots to discovery, and never `rmtree` a `.git` dir. Use `grace = max(interval_s, 7d)` in place of `interval_s`. (S4, S5, S6)
7. **§2.** Move `PENDING_LOCK` to a per-user path (`/tmp/ai-tracker-pending-<uid>.lock`). Add `import re` to `config.py`. The §4 cap becomes ≤ 366d. (S7, N1)
8. **§8.** Add fixtures E–L with one red-proof per guard (ancestor → E, idle → F, ignored → G, orphan → H). Replace the bogus `ahead == 0` red-proof. (S8)
9. **§10 Known gaps.** Add: no live signal for non-Claude providers (the idle guard only); moved worktrees are protected only by the prune grace; a git timeout hides a worktree as `unknown`.
