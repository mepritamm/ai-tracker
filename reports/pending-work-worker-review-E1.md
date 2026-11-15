# Review E1: pending-work worker (pending.py, schedule.py, seam, tests)

Reviewer: E1 (adversarial, opus), 2026-11-15. This was a read-only review: grep and sed ranges, plus pure probes against the real `aitracker/pending.json` from the R7 list-only run. No tests, servers, make targets or launchctl were run.

Scope: `aitracker/pending.py`, `aitracker/schedule.py`, `registry.all_cwds`, `ClaudeProvider.cwds`, `tests/test_pending_*.py`, `tests/pending_fixture.py`. The server routes were read only where they decide who can turn on `safe` or start a scan.

## Verdict on the central questions

| Question | Answer |
|---|---|
| Can `safe` remove uncommitted work? | **Yes, in one case (F4).** Tracked files marked `assume-unchanged` or `skip-worktree` are invisible to our `git status` and also to git's own `worktree remove` check. Every other case is covered: dirty, untracked and ignored files (`.env` included) block removal. So do unpushed commits, unless gh says MERGED on the exact head. git refuses nested gitlinks/submodules by itself (`validate_no_submodules`). Nested untracked repos show up as `??` or `!!`, and both block. |
| Can it remove in-use work? | Partly guarded. Live sessions are matched by cwd, which works for worktrees but **never for scratch** (F5). The idle grace can be bypassed when a worktree's `.git` file uses a relative `gitdir:` (F7). Anything a gap lets through is still clean and merged, so no commits are lost. |
| Can it touch a transcript, `state.json`, `tasks` or `file-history`? | No. The only rmtree targets are `JOBS_DIR/<id>/tmp` and `SCRATCH_ROOT/<slug>/<sid>`, checked with exact depth 2 by realpath and commonpath. |
| Can it reach outside its roots (symlinks, `..`, `/tmp` vs `/private/tmp`)? | Inner symlinks, slug escapes and `..` are handled because realpath is applied to both sides. **The root itself is trusted (F6):** if `/tmp/claude-<uid>` is a symlink planted by another local user, deletion follows it. `test_L_*` writes that behaviour in as expected. |
| Does dry-run truly delete nothing? | **Yes.** I checked every path. `clean` only appends to lists. `_prune_repo` returns before `worktree prune`. Every scan-stage git call is read-only (`--no-optional-locks`, `GIT_OPTIONAL_LOCKS=0`). The only writes are `pending.json` and the lock file. |
| Can a gh MERGED answer alone make something deletable? | **No.** MERGED stands in only for the ancestor/unpushed term, and only when `headRefOid == head`. Every other guard still applies, and the re-inspection checks that `head` is unchanged. The test that claims to prove this is weak (F13). |
| Does a scan miss pending work (C1)? | **Yes, two real misses on this machine.** (F3) Session cwds that are parent folders, not repos, are dropped, so 12 child repos under `VIDA20/` and `AIengg/` are never scanned. (F2) A repo with no commits yet reads as `unknown` and is left out of the card. Example: `VIDA20/theAppWorkspace` has 8 untracked entries and does not show. |
| Is "134 would delete" plausible? | **Yes.** It is 64 worktrees plus 70 tmp trees (69 job `tmp` dirs and 1 scratch dir). I re-checked all 64 worktrees independently against every guard: 0 violations. Minimum idle is 8 days. 56 are ancestors of the base and 8 are gh-merged. 1 gh-merged item has `unpushed>0` and keeps its branch ref, because `branch -d` refuses. 275 of the 279 "clean but not deletable" items are blocked by ignored files. |
| Do the tests exercise the guards? | Mostly. Two TOCTOU tests pass because of the idle grace, not the guard they name. The N3 test never puts a MERGED state on a guarded item. The scratch transcript and live guards have no test (F13, F14). |
| Can autoinstall run from a worktree checkout, a test run or the bundle? | Worktree checkout: no (the `.git`-file check and the `.claude/worktrees` substring check). Bundle: no (no `__init__.py`). `make check` and `python -m unittest`: no. **A direct `python3 tests/test_pending_routes.py` run from the primary checkout: yes (F8).** |

## Findings

Every finding below has four parts: (1) the defect and a repro, (2) the fix direction, (3) the way to make the fix, and (4) a test that is red before the fix.

### F1 [should-fix]: cross-site POST can turn on Safe delete (no Origin check)
1. **Defect.** `server._local_caller` (server.py:223–238) checks three things: no proxy header, a peer of 127.0.0.1, and a loopback Host. `do_POST` (server.py:623–624) runs `json.loads` on the body whatever its Content-Type is.
   - Repro: open any web page in the user's browser and run `fetch("http://localhost:8790/api/config", {method:"POST", mode:"no-cors", body:'{"key":"PENDING_CLEAN","value":"safe"}'})`. This is a simple `text/plain` request, so there is no preflight. Host is `localhost:8790` and the peer is loopback.
   - Actual: 200, and `safe` is written to config.json (server.py:701 passes).
   - Expected: 403.
   - The same page can POST `/api/pending/run` to start repeated scans with up to 20 gh calls each, and `/api/scheduler` to install or uninstall the job. `/api/update/apply` is outside my scope but has the same exposure, and that one may be a blocker.
   - Chrome's Local Network Access mitigates this. Safari and Firefox do not.
2. **Direction.** A browser request whose `Origin` is not loopback must be refused by every local-only route. Callers that send no `Origin` (curl, the CLI, tests) must still pass. The Host ruling stays as it is.
3. **The way.** In `_local_caller`, after the Host check:
   - read `o = handler.headers.get("Origin")`;
   - if `o` is set, refuse unless `is_loopback_host(urlparse(o).netloc)` is true;
   - also refuse when `Sec-Fetch-Site` is `cross-site` or `same-site`.
   Mirror the same check in `term_gate.guard`, the sibling gate.
4. **Test.** In `tests/test_local_host_routes.py`, POST `/api/config` with `{"key":"PENDING_CLEAN","value":"safe"}` three times:
   - with `Origin: http://evil.example`: expect 403 (red today);
   - with `Origin: http://localhost:<port>`: expect 200;
   - with no Origin: expect 200.

### F2 [should-fix]: a repo with no commits hides its uncommitted files (C1/C3)
1. **Defect.** `inspect_worktree` (pending.py:409) runs `rev-list --count HEAD`, which exits 128 on an unborn HEAD. That raises `_GitErr`, so the verdict becomes `unknown`. `build_card` (:633) counts only `pending` and `missing`, so the item never reaches the card.
   - Real case: `VIDA20/theAppWorkspace` has untracked=8 and ignored=9, but reads "unknown (git error; kept)".
   - `~/.claude/jobs/1974901a/tmp/base` is the same case.
2. **Direction.** An unborn HEAD should read as `pending` with the reason "no commits yet" plus the file counts. Separately, the card should count `unknown` items, because unverifiable work must not be invisible. Neither change may make anything deletable.
3. **The way.**
   - In `inspect_worktree`, after the status call: if `wt["head"]` is empty or all zeros, or `_git(path, "rev-parse", "-q", "--verify", "HEAD")[0] != 0`, then set `item["unborn"] = True` and `unpushed = 0`, skip the upstream, ancestor and head steps, and return the item.
   - In `classify`: if `unborn`, return verdict `pending` with deletable False.
   - In `build_card`: add `unknown = [i for i in items if i.get("verdict") == "unknown"]` to `count`, with a summary part "N could not be checked".
   - Both views render `card` as-is, so no JS change is needed.
4. **Test.**
   - `tests/test_pending_scan.py`: `git init` a repo, write one untracked file, add it to `fx.cwds`. Expect verdict `pending` (red today: `unknown`).
   - `tests/test_pending_classify.py`: an `unknown` item counts in `card["count"]` (red today).

### F3 [should-fix]: child repos of a parent-folder session cwd are never discovered (C1)
1. **Defect.** In `discover_repos` (pending.py:286–288), a seed whose `rev-parse --git-common-dir` fails is skipped.
   - Five distinct first cwds on this machine are not inside any repo. Two of them are parent folders: `AIengg/VIDA20` (11 child repos) and `AIengg` (7 child repos).
   - 12 of those 18 child repos are missing from `pending.json` `repos[]` (33 repos in total). Examples: `VIDA20/dw-IntegrationLayerAPI`, which has a linked worktree, `dw-VidaAdmin`, `bug-fixer`, `security-smasher`.
   - Any dirty or unpushed work in them is never listed.
2. **Direction.** When an existing cwd seed is not a repo, also try its immediate child directories as seeds. Go only one level deep, never follow symlinks, and keep it bounded. Do not walk the whole home directory.
3. **The way.** In `discover_repos`, inside the loop where `rc != 0` and `is_cwd` and `os.path.isdir(d)`:
   ```python
   for n in sorted(os.listdir(d))[:200]:
       c = os.path.join(d, n)
       if not os.path.islink(c) and os.path.exists(os.path.join(c, ".git")):
           seeds.append((c, False))
   ```
   Append to a second list processed after the loop, or loop over the seeds by index. These seeds carry `is_cwd=False`, so `cwds` stays honest. Only seeds with `is_cwd=True` expand, so sticky and tmp seeds never fan out.
4. **Test.** In `tests/test_pending_scan.py` DiscoverTests, set `fx.cwds = {fx.root}` (the parent of `repo`). Expect `fx.repo` in the discovered tops (red today).

### F4 [should-fix]: `assume-unchanged` / `skip-worktree` edits are deleted by Safe delete
1. **Defect.** `git status`, both ours (pending.py:399) and the one inside `git worktree remove`'s `check_clean_worktree`, does not report a modified file that is flagged `--assume-unchanged` or `--skip-worktree`. `_remove_worktree` (:713) therefore removes the directory, and the local edit is lost.
   - Repro: in a merged, aged worktree, run `git update-index --assume-unchanged a.txt`, then edit `a.txt`, then run `clean(..., "safe")`.
   - Actual: the worktree is removed and the edit is gone.
   - Expected: kept.
   - I proved this from the code path, not by running it. The fixer must show the test red first.
2. **Direction.** Treat any index entry with one of these flags as "hidden local state" and never delete it. No other verdict changes.
3. **The way.** In `inspect_worktree`, only when `dirty == untracked == ignored == 0` (so the cost lands only on candidates), run `_git(path, "ls-files", "-v")`. Count lines whose first char is lowercase or `S`, and set `item["hidden"]`; rc != 0 raises `_GitErr`. In `classify`, add `and not it.get("hidden")` to `deletable`, and add the label part "N assume-unchanged/skip-worktree". `_reinspect` re-runs this through `inspect_worktree`, so the TOCTOU path is covered too. Sparse checkouts will no longer be reclaimed; that is fail-closed and acceptable.
4. **Test.** In `tests/test_pending_clean.py`, use the repro above. Expect `a.txt` edited content to survive and `deleted == []` (red today).

### F5 [should-fix]: the scratch "live session" guard can never fire
1. **Defect.** In `scan_tmp` (pending.py:494), `_live_under(path, ctx)` checks whether a live session's **cwd** lies under `/tmp/claude-<uid>/<slug>/<sid>`. A session's cwd is its project, never its scratch dir.
   - A live TUI session idle for more than 7 days (old transcript, old task outputs, no job) has its scratch, including `tasks/` output, marked `stale` and deleted while it is still running.
   - On this machine no live session's scratch is stale today, but only because of the transcript and job guards.
2. **Direction.** Match live sessions by `sessionId == sid`. Keep the cwd check.
3. **The way.**
   - In `build_ctx`, add `live_sids = {d["sessionId"] for alive session files with a str sessionId}` and return it.
   - In `scan_tmp`, before the transcript and mtime branches, add: `elif (sid and sid in ctx["live_sids"]) or (job and job.get("sessionId") in ctx["live_sids"]): reason = "live session"`.
4. **Test.** In `tests/test_pending_classify.py` TmpTests, create `SCRATCH_ROOT/slug/<sid>` aged 8 days and a session file `{"pid": os.getpid(), "sessionId": sid, "cwd": fx.repo}`. Expect verdict `keep`, reason "live session" (red today: `stale`).

### F6 [should-fix]: `SCRATCH_ROOT` itself is trusted, so a planted symlink redirects rmtree
1. **Defect.** `scan_tmp` (pending.py:456) lists `SCRATCH_ROOT` and checks `_under(path, root, 2)` with both sides resolved by realpath.
   - If `/tmp/claude-<uid>` is a symlink (or a directory owned by another user) pointing at, say, `~/work`, then every `~/work/<a>/<b>` with no `.git` that is idle for 7 days or more becomes `stale` and is rmtree'd in safe mode.
   - `/tmp` is world-writable, so on a multi-user Mac another account can create that path before Claude Code does.
   - `test_L_scratch_symlink_root_sibling_kept` (test_pending_clean.py:333) and `test_L_scratch_root_symlink_and_sibling` (test_pending_classify.py:211) both **assert** that the symlinked root is followed and its contents deleted.
2. **Direction.** Scan scratch only when the root's last path component is a real directory owned by this uid and not group- or world-writable. The `/tmp` → `/private/tmp` parent symlink must keep working.
3. **The way.** At the top of the scratch block in `scan_tmp`:
   ```python
   st = os.lstat(sr)
   if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
       skip  # log once
   ```
   `lstat` does not follow the last component, so `/tmp/...` still resolves through the parent link. This is POSIX-only; `SCRATCH_ROOT` is None on nt. The job-tmp branch is untouched.
4. **Test.** Flip both `test_L_*` cases. A symlinked `SCRATCH_ROOT` must yield no scratch entries and delete nothing (red today). Add one case where a real 0700 root works. **This intentionally changes existing test expectations.**

### F7 [should-fix]: a relative `gitdir:` defeats the idle grace
1. **Defect.** `_last_activity` (pending.py:346–349) joins `line[7:]` from the worktree's `.git` file directly.
   - With git ≥2.48 (`worktree.useRelativePaths` or `worktree add --relative-paths`; this machine has 2.54), that value is relative to the worktree. It ends up resolved against the server's cwd, the `HEAD`/`index`/`logs/HEAD` mtimes read as 0, and only the directory mtime counts.
   - A worktree committed to yesterday, whose root directory was untouched, reads as idle for 7 days or more.
2. **Direction.** Resolve the gitdir relative to the worktree path.
3. **The way.** Use `admin = os.path.normpath(os.path.join(path, line[7:].strip()))`. `join` leaves absolute paths unchanged.
4. **Test.** In `tests/test_pending_scan.py` `test_last_activity_*`, add a case that is skipped when `git worktree add --relative-paths` fails:
   - age the directory only;
   - touch the admin `HEAD` now;
   - expect `last_activity` within 60s of now (red today).

### F8 [should-fix]: autoinstall is reachable from a direct test-file run in the primary checkout
1. **Defect.** `test_pending_routes.test_run_calls_start_worker` (tests/test_pending_routes.py:91–101) calls the real `server.run()`, which starts `_autoinstall_thread` with the **real** `autoinstall_once`. That test does not patch it, and it does not patch HOME. `_under_test()` (schedule.py:94–98) recognises only `-m unittest`, pytest, `--selfcheck` and the env flag.
   - Repro: `python3 tests/test_pending_routes.py` from the primary checkout, with no opt-out file.
   - Result: a real `launchctl print`, then a real plist written to `~/Library/LaunchAgents`, then `launchctl bootstrap`.
   - `make check` is safe because `run_tests_parallel.py` uses `-m unittest`.
2. **Direction.** No test may reach the real `autoinstall_once`.
3. **The way.**
   - In that test, add `mock.patch.object(_server, "autoinstall_once", lambda: {"action": "skipped"})`, or `mock.patch.dict(os.environ, {"TRACKER_SCHEDULER_AUTOINSTALL": "0"})`.
   - In `_under_test`, also return True when `os.path.basename(argv[0]).startswith("test_")`.
   - Optional belt: `scripts/run_tests_parallel.py` sets `AITRACKER_NO_AUTOINSTALL=1` in the child env.
4. **Test.** In `tests/test_pending_schedule.py`, with `sys.argv` patched to `["tests/test_x.py"]`, expect `schedule._under_test()` to be True (red today).

### F9 [should-fix, H5]: the safe-mode tmp re-check rescans every tmp tree once per candidate
1. **Defect.** `_remove_tmp` (pending.py:766) calls `scan_tmp(build_ctx(), now)`, a full walk of **all** tmp trees, once for **each** stale tree.
   - On this machine that is 70 stale trees × 353 trees walked, up to 50k entries each, about 2.5 GB.
   - Each of the 64 `_reinspect` calls also rebuilds a full ctx.
   - The dry-run alone took 243s. A safe run would hold the per-user lock for many minutes.
2. **Direction.** Re-check only the candidate itself, with a fresh ctx. Keep the guards identical.
3. **The way.**
   - Split the per-candidate body of `scan_tmp` into `_tmp_entry(path, root, sid, jid, ctx, now)`. `scan_tmp` keeps the listing loop and calls it.
   - `_remove_tmp` calls `_tmp_entry(t["path"], <root>, t["session"] if not t["job"] else None, t["job"], build_ctx(), now)`. The root comes from `t["job"]`: `JOBS_DIR` if set, else `SCRATCH_ROOT`.
   - The redundant second `_walk_tree` check then reuses the entry's own walk.
4. **Test.** In `tests/test_pending_clean.py`, create 3 stale job tmp trees, wrap `pending._walk_tree` with a counter, and run a safe clean. Expect at most 2 walks per tree (red today: 3 + 3×3).

### F10 [should-fix, H5]: every server, including worktree and spare-port servers, runs a full machine scan
1. **Defect.** `start_worker()` (pending.py:885, called at server.py:1015) always starts the worker. `scheduled_at` lives in `config.PENDING_FILE`, which sits under each checkout's `_HERE`. So "tick dedups through `scheduled_at`" holds only within one checkout.
   - Every dev or test server started from a worktree runs a complete scan 60s after start, its first run being due: about 4 minutes of git work and up to 20 gh calls.
   - The README advice (`TRACKER_PENDING_INTERVAL=off`) is easy to miss.
2. **Direction.** The scheduled worker runs by default only in a non-worktree checkout, the same rule as autoinstall. An explicit env interval re-enables it. The CLI and Scan now are unchanged. **This may be wider than the defect.** The minimal alternative is "no change; documented".
3. **The way.** In `start_worker`:
   ```python
   if (schedule._is_linked_worktree() or "/.claude/worktrees/" in _root() + "/") and "TRACKER_PENDING_INTERVAL" not in os.environ:
       return
   ```
   Import the guard by name (`from .schedule import _is_linked_worktree, _root`) so the bundle flattens it.
4. **Test.** In `tests/test_pending_tick.py`, patch `_is_linked_worktree` to True with no env. Expect `start_worker()` to leave `_WORKER` empty (red today). With the env set, expect the thread to start.

### F11 [nit]: `_walk_tree` silently skips unreadable subdirectories, so rmtree can partly delete an unverified tree
1. **Defect.** `os.walk` (pending.py:432) defaults to `onerror=None`, so an unreadable subdirectory is never checked for `.git` or mtime. rmtree then deletes the readable part before it fails. The result is reported as refused, but the files are already gone.
2. **Direction.** An unreadable entry means keep.
3. **The way.** Pass `onerror=errs.append`, and return `capped=True` (or a new flag) when `errs` is non-empty. `scan_tmp` then reports "unreadable entries".
4. **Test.** Create an aged job tmp with a `chmod 000` subdirectory. Expect `keep`, and a sibling file still present after the safe clean.

### F12 [nit]: an in-progress rebase/merge/bisect is lost with the admin dir
1. **Defect.** `git worktree remove` deletes `<common>/worktrees/<name>/`, which holds `rebase-merge/`, `MERGE_HEAD`, `BISECT_LOG` and per-worktree refs. A detached worktree stopped at an `edit` step on an already-pushed commit counts as reclaimable.
2. **Direction.** An operation in progress means not deletable.
3. **The way.** In `_last_activity`, which already resolves `admin`, or in `inspect_worktree`, set `item["op"]` if any of `rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG` exists under admin. `classify` adds `and not it.get("op")` to `deletable`.
4. **Test.** Create a merged, aged worktree and touch `<admin>/BISECT_LOG`. Expect `deletable` False.

### F13 [nit]: some guard tests pass for the wrong reason
1. **Defect.**
   - `test_toctou_untracked_survives` (test_pending_clean.py:145): creating `notes.txt` bumps the directory mtime, so the idle grace refuses before the untracked guard is reached.
   - `test_toctou_head_moved_survives` (:153): the commit bumps `HEAD`/`logs`, and the new commit is unpushed. The `fresh["head"] != it["head"]` line (pending.py:711) is never the reason.
   - `test_N3_merged_alone_never_deletes` (test_pending_gh.py:58): it never gets `gh.state == "merged"` onto a guarded item, only `skipped`.
2. **Direction.** Each test should fail when its own guard is removed, and only then.
3. **The way.**
   - After each mutation, call `self.fx.age(wt, 8)`, and assert that the refusal reason names the guard.
   - For head-moved: move the branch to an older pushed commit (`git -C wt reset --hard HEAD~1`, where that commit is on origin), age it, and assert "HEAD or branch moved".
   - For N3: build an item dict with `gh={"state":"merged"}` and set ignored=1, live=True, busy_job=True, locked=True, or last_activity=now, one at a time. Assert `reclaimable` is False for each.
4. **Test.** The tests above. Prove each one by removing its guard and watching it go red.

### F14 [nit]: missing tests for the scratch transcript guard and a sid-level symlink
1. **Defect.** No test covers `tx_sid` ("recent transcript", pending.py:490) or `os.path.islink(path)` (:484) at the sid level.
2. **Direction.** Add the tests; no code change.
3. **The way.** Add both cases to TmpTests:
   - `projects/p/<sid>.jsonl` with mtime now, plus `SCRATCH_ROOT/slug/<sid>` aged 8 days: expect `keep` with reason "recent transcript".
   - `SCRATCH_ROOT/slug/sidL` as a symlink to `SCRATCH_ROOT/slug/real`: expect reason "symlink".
4. **Test.** The tests above. Prove them red by deleting each branch.

### F15 [nit]: `_git` inherits `GIT_DIR` / `GIT_INDEX_FILE` / `GIT_WORK_TREE`
1. **Defect.** `_git` (pending.py:50) copies `os.environ` as it is. The fixture scrubs `GIT_*` because the commit hook sets them. A server or CLI started from such an environment inspects every worktree against the wrong repo. Wrong-repo facts mostly read as dirty, so the result is mostly fail-closed.
2. **Direction.** Every scan-stage git call addresses only its `-C` path.
3. **The way.** In `_git`, pop `GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE GIT_PREFIX` from `env`. In `item_detail`'s `diff` calls, also add `--no-ext-diff --no-textconv`.
4. **Test.** In `tests/test_pending_scan.py`, set `GIT_DIR=<remote.git>` in `os.environ`. `inspect_worktree` on a clean worktree must still report dirty=0 with no error (red today).

### F16 [nit]: `branch -d` notes and base names
1. **Defect.**
   - `_remove_worktree` (pending.py:717) skips `-d` only when the branch equals the base's short name. A linked worktree on local `main`, when the base is `origin/develop`, gets `branch -d main`.
   - For squash-merged items with an upstream set, `-d` *succeeds*, which contradicts the plan's claim that the branch is kept. Commits are still on the remote, so nothing is lost.
2. **Direction.** Never delete `develop`, `main` or `master`. Make the note match what happened.
3. **The way.** Skip when `it["branch"] in ("develop", "main", "master") or == short`. When rc is 0 and the item was merged, set the note to "branch deleted (fully pushed to upstream)".
4. **Test.** A worktree on `main` with base `origin/develop`: expect no `("branch", "-d", "main")` call in the spy.

### F17 [nit, leave alone]: `load_report` takes the exclusive lock briefly on every poll
`load_report` (pending.py:909–911) can make a concurrent OS-job `run_once` see "busy" and skip. Both callers recover: the worker retries in 60s and the OS job retries the next day. **No change.** Document it next to `_pending_lock` if anyone touches that code.

### F18 [nit]: `resume_prompt` reads `item["sids"]`, which nothing sets
`resume_prompt` (pending.py:946) always prints "(any session that used it)". Direction: either fill `sids` in `inspect_worktree` from the transcripts whose cwd is under the path (ctx would need a sid→cwd map), or drop the clause. Test: `test_pending_routes`, assert the prompt names the session.

### F19 [nit, docs]: scratch candidates are any depth-2 directory, not only session ids
On this machine the depth-2 names include `aitracker`, `tests` and `m_M4_…` (agent mutation copies). That is wider than the D4 wording `<slug>/<sid>`, but deleting idle scratch copies is within the contract's intent. Direction: **no code change.** Amend conventions.md D4 and the README to say "any directory two levels under `/tmp/claude-<uid>`".

### F20 [nit]: porcelain parsing and pruning on missing volumes
- `worktree list --porcelain` is parsed without `-z`, so a path containing a newline breaks the parse. Use `-z` (git ≥2.36).
- `_prune_repo` prunes entries whose path's mount is gone (an unmounted `/Volumes/X`), which drops their index, and with it any staged-only changes.
- Direction: skip prune when the nearest existing ancestor of a prunable path is `/Volumes` or `/`.
- Test: a fake prunable path under a missing top-level directory leads to "prune skipped".

## Not examined
- Real Windows behaviour (`msvcrt` lock, schtasks `/TR` quoting, `pythonw` stdout); covered by pure tests only.
- Real launchd behaviour, including TCC denial for a checkout under `~/Documents` (parked as H6). I expect the OS job to exit non-zero there; the server thread is the working trigger.
- `update.py` holding the pending lock across a restart, plus every UI file (`app.js`, `ext_cr_*`).
- How Auggie's `list()` feeds `all_cwds`. Whether `_session_meta`'s cache is correct for transcripts that are rewritten.
- Whether `--ignored=matching` together with `--untracked-files=normal` reports every ignored file inside a non-ignored untracked directory. I relied on git docs; the untracked entry blocks deletion in that case anyway.
- The exact git behaviour behind F4. I traced it through `check_clean_worktree` from memory of the git source, not by running it.

## Fix list
- F1 · server.py `_local_caller` (+ `term_gate.guard`): refuse a non-loopback `Origin` and a cross-site `Sec-Fetch-Site`.
- F2 · pending.py `inspect_worktree`/`classify`/`build_card`: unborn HEAD is `pending` ("no commits yet"); the card counts `unknown`.
- F3 · pending.py `discover_repos`: a non-repo cwd seed also seeds its depth-1 child repos (no symlinks, capped at 200).
- F4 · pending.py `inspect_worktree`/`classify`: `ls-files -v` lowercase or `S` tags give `hidden>0`, so not deletable.
- F5 · pending.py `build_ctx`/`scan_tmp`: `live_sids`; keep scratch whose sid (or job sessionId) is live.
- F6 · pending.py `scan_tmp`: lstat `SCRATCH_ROOT` (real dir, own uid, not g/o-writable) or skip; flip the `test_L_*` expectations.
- F7 · pending.py `_last_activity`: resolve a relative `gitdir:` against the worktree path.
- F9 · pending.py `scan_tmp`/`_remove_tmp`: factor out `_tmp_entry` and re-check only the candidate.
- F10 · pending.py `start_worker`: no-op in linked-worktree checkouts unless `TRACKER_PENDING_INTERVAL` is set (optional; may be wider).
- F11 · pending.py `_walk_tree`: an `os.walk` onerror means keep.
- F12 · pending.py `inspect_worktree`/`classify`: an operation in progress in the admin dir means not deletable.
- F15 · pending.py `_git`/`item_detail`: strip `GIT_DIR`-family env; diff with `--no-ext-diff --no-textconv`.
- F16 · pending.py `_remove_worktree`: never `-d` develop/main/master; accurate note.
- F18 · pending.py `resume_prompt`/`inspect_worktree`: fill `sids` or drop the clause.
- F8 · schedule.py `_under_test` (+ tests/test_pending_routes.py patch autoinstall): `argv[0]` basename `test_*` counts as a test run.
- F13 · tests/test_pending_clean.py, tests/test_pending_gh.py: re-age after mutations; head-reset case; merged + each guard ⇒ not reclaimable.
- F14 · tests/test_pending_classify.py: scratch recent-transcript and sid-symlink cases.
- F19 · conventions.md / README: D4 wording "any dir at depth 2" (docs only).
- F20 · pending.py `_parse_porcelain`/`_prune_repo`: `-z` porcelain; skip prune when the volume is missing.
