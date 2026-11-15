# Adversarial review C — plan v3 deltas (U1, U6, U7, U8)

Reviewer C (opus), 2026-11-15. Scope: only what v3 changed from v2 for U1/U6/U7/U8, plus whether v3 silently dropped a reconciled fix. Assumed v3 is wrong.

How I checked: grep/sed ranges at the worktree HEAD. Evidence: `scripts/bundle.py:11-16,19-23,38-50`, `aitracker/tunnel.py:309`, `aitracker/server.py:437,248-253`, `aitracker/config.py:7,202`, `aitracker/page.py:20`, `aitracker/web/app.js:1055,1315-1334`, `aitracker/web/ext_cr_boot.js:228-237`, and `tests/test_page_bundle.py:206` (a JS-page test, not the Python bundle). I also read live machine state: `git remote -v` (one remote, `personal` = `git@github-personal:…`, an SSH alias); the env `launchctl print gui/<uid>/com.vida.stacksync` reports for an existing, working agent (no `TMPDIR`; PATH is explicit); and that agent's log path (`~/Library/Logs/…`).

Severity: **2 blockers, 7 should-fix, 10 nits.**

---

## Blockers

### C-B1 — `installed()` = "plist file exists" switches off the only scanner that is known to work
- **Defect.** v3 §3b `installed()` and §3 `start_worker()` ("no-op if … `schedule.installed()`"). Whenever the plist exists but the job never runs successfully, nothing scans and the card silently freezes. Ways to get there:
  - `bootstrap` fails after the plist is written. Install doesn't say it removes the file.
  - `sys.executable` moves, e.g. a Homebrew Python upgrade.
  - The checkout is moved or deleted.
  - TCC denies the job access to `~/Documents`.
  - The step-3 test writes the real plist (C-S4).

  **Repro:** write the plist, make ProgramArguments[0] a missing path, run `make serve`. Actual: no worker thread starts, the OS job exits non-zero every day, and `pending.json` is never refreshed. Expected: the server keeps scanning. U1 literally asked for "2 *and* launchd": both, not either-or.
- **Fix direction.** Drop the `installed()` gate. Let the server thread and the OS job both call `tick()`. `tick()` already dedups through the per-user lock and the on-disk `scheduled_at`/`generated_at`, so a second caller finds nothing due. Keep the rule that `PENDING_INTERVAL` alone decides. Must NOT change: lock semantics, or the "daily trigger only asks" rule.
- **The way.**
  - `pending.start_worker()`: delete the `schedule.installed()` clause.
  - `schedule.installed()` is then unused: delete it (smaller diff).
  - `tick()` must read `pending.json` fresh from disk on every call, never from a memory copy.
  - `schedule.status()` adds `"last_exit"` (parsed from the `last exit code = N` line of `launchctl print`) and `"root_exists"`, for `--scheduler-status`.
  - `install()`: if `bootstrap` fails, `os.remove(plist)` and return 1.
  - Requires C-S1. Otherwise the two callers take different locks.
- **Test.** `test_pending_tick.py`:
  - (a) With `schedule.status` patched to installed, `start_worker()` starts the thread. Red under v3.
  - (b) Call `run_once("dry-run")`, then `tick(now+5)`, and it returns `"idle"`: no double run.
  - (c) `test_pending_schedule.py`: an injected `run` returning rc 5 for bootstrap leaves no plist file.
- **Wider than the defect?** No. It removes code.

### C-B2 — `schedule.py` breaks the flattened bundle: `status` collides with `tunnel.status`, and `schedule.X` is never rewritten
- **Defect 1.** `scripts/bundle.py:38-50` flattens every module into one namespace. It drops all top-level imports and rewrites only `config.` and `tunnel.`. Meanwhile `tunnel.py:309` defines `def status()`, and `server.py:437` calls `tunnel.status()`, which becomes bare `status()` in the bundle. v3 §3b adds a second top-level `def status(run=…)`, and ORDER places `schedule.py` near `tunnel.py`. Whichever module is flattened later wins:
  - the tunnel dialog's `/api/config` gets a scheduler dict, or
  - `--scheduler-status` returns tunnel state.

  Neither is caught by `TestBundle --pending --dry-run`.
- **Defect 2.** `start_worker()` and `cli_main` call `schedule.installed()`, `schedule.install()` and so on: attribute access on a module object that does not exist in the bundle. This is a NameError. Since `start_worker()` runs inside `run()`, **the bundled server dies at startup.** This also silently re-violates the reconciled B-B1 rule (named imports, no `X.attr`).
- **Defect 3.** HEADER (`bundle.py:19-23`) has no `plistlib`, `getpass` or `tempfile`. v3's module-level `config.PENDING_LOCK = …tempfile…getpass…` makes **every** bundled command NameError at import time. TestBundle would catch this one, but step 10's file list never mentions HEADER, so the implementer is not told.
- **Fix direction.** Give schedule's public functions unique names and import them by name. Keep the bundle a single namespace; don't add a third rewrite regex.
- **The way.**
  - `schedule.py`: rename to `sched_install`, `sched_uninstall`, `sched_status` (and drop `installed` per C-B1).
  - `pending.py`: `from .schedule import sched_install, sched_uninstall, sched_status`.
  - `bundle.py` ORDER: `…"registry.py", "tunnel.py", "schedule.py", "pending.py", "server.py", "cli.py"`.
  - HEADER: add `plistlib`.
  - Drop `getpass`/`tempfile` from config per C-S1. If `getpass` stays anywhere, add it to HEADER as well.
- **Test.** In `tests/test_integration.py::TestBundle` (step 10):
  - assert `dist/tracker.py` has exactly one `^def status\(`;
  - run `python3 dist/tracker.py --pending --scheduler-status` with a temp HOME and expect rc 0;
  - start the bundle with `--version`, and with `run()` under `TRACKER_PENDING_INTERVAL=off`.

  Red before the rename.

---

## Should-fix

### C-S1 — The per-user lock is not per-user: `tempfile.gettempdir()` differs between launchd and a shell (voids reconciled A-S7)
- **Defect.** v3 §2 config: `PENDING_LOCK = join(tempfile.gettempdir(), "ai-tracker-pending-<user>.lock")`. A shell here has `TMPDIR=/var/folders/_b/…/T/`. The env that `launchctl print` reports for an existing user agent on this Mac has **no TMPDIR**, so Python's `gettempdir()` falls back to `/tmp`. A server started with a different TMPDIR (some sandboxes, or `TMPDIR=… make serve`) also diverges.

  **Repro:** run `python3 -c 'import tempfile;print(tempfile.gettempdir())'`, then the same with `env -u TMPDIR`. You get two different paths, so the OS job and the server thread can both hold "the" lock and clean at once, racing `_save_json` and `scheduled_at`.
- **Fix direction.** Use a lock path derived from HOME, which launchd, shells and Windows all agree on. Must NOT be per-checkout.
- **The way.** `config.PENDING_LOCK = os.path.join(os.path.expanduser("~"), ".ai-tracker-pending.lock")`. This also removes the `tempfile`/`getpass` imports from config (C-B2, defect 3).
- **Test.** `test_pending_tick.py`: compute `config.PENDING_LOCK` with `TMPDIR` set and unset (re-resolve via `importlib.reload` under a patched env) and assert both are equal. Red under v3.

### C-S2 — `PENDING_INTERVAL=off` means two different things depending on which scheduler runs
- **Defect.** Under the thread, `start_worker()` is a no-op when the interval is off, so nothing runs. Under the OS job, `tick()` runs `due()`, which returns False for a None interval, so it falls to the `elif` and **still runs a daily dry-run scan, gh included**. The settings copy (§2 `ext_cr_dialogs.js`) says '"off" stops it'.

  **Repro:** set `PENDING_INTERVAL=off` and run `ai-tracker --pending --if-due` with `generated_at` 2 days old. Actual: `"list"`, plus gh calls. Expected: `"off"`, and nothing runs.
- **Fix direction.** "off" stops all scheduled work, both list and clean, in both schedulers. Manual Scan now and bare `make pending` still work.
- **The way.** First line of `tick()`: `if interval_seconds(config.PENDING_INTERVAL) is None: return "off"`. `cli --if-due` prints it.
- **Test.** `test_pending_tick.py`: with the interval off and an old report, `tick()` returns `"off"` and a patched `run_once` is never called.

### C-S3 — A daily OS trigger against strict ≥86400 thresholds runs every other day
- **Defect.** launchd fires at 10:00:00. The previous run set `generated_at` (or `scheduled_at`) a few seconds or minutes after 10:00 the day before. So `now - generated_at` is 86400 − (run duration + jitter), which is below `LIST_REFRESH`, and `tick()` returns "idle". The same thing happens with `due()`: under the OS job alone, `1d` becomes 2 days and `7d` becomes 8. Windows `/SC DAILY` has the same problem.

  **Repro:** `report.generated_at = now - 86400 + 30` → `tick(now)` returns `"idle"`. Expected: `"list"`.
- **Fix direction.** Allow one hour of slack on both thresholds. Must NOT shorten the 7d deletion grace: that is a property of the item, not the cadence.
- **The way.** `SLACK = 3600`. In `due()`: `now - scheduled_at >= interval_s - SLACK`. In `tick()`: `now - generated_at >= LIST_REFRESH - SLACK`.
- **Test.** `test_pending_tick.py`: `generated_at = now-86370` returns `"list"`, and `scheduled_at = now-86370` with `1d` returns `"clean"`. Both are red under v3.

### C-S4 — Step-3 tests would write the real `~/Library/LaunchAgents/com.aitracker.pending.plist`
- **Defect.** §3b `install(run=…)` makes only the `launchctl` call injectable. The plist write goes to a hard-coded `~/Library/LaunchAgents`. Step 3 promises "install/uninstall call sequences … no real launchctl", but on this Mac the test leaves a real plist behind. Under v3's gate, the user's real server would then stop scanning (C-B1).
- **Fix direction.** Make the plist path late-bound and patchable.
- **The way.** `schedule.plist_path()` returns `os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LABEL + ".plist")`. Read it at call time. Tests patch `HOME` to a temp dir.
- **Test.** `test_pending_schedule.py`: snapshot the real `~/Library/LaunchAgents` listing before and after the install/uninstall tests and assert it is unchanged; assert the temp-HOME plist exists after install and is gone after uninstall.

### C-S5 — Step 16's launchd proof can't run as written, and wouldn't prove a run
- **Defect.** §7 step 16 runs `make pending-install` from the feature worktree. §3b's guard refuses installs from a linked worktree, and the primary checkout has no `schedule.py` until the branch lands. Even if install succeeded, `launchctl print` only proves the job is *loaded*, not that it *ran*.

  Unproven risks:
  - TCC on `~/Documents`, where both WorkingDirectory and `StandardOutPath` live (`config._HERE/pending-scheduler.log`). The working agent `com.vida.stacksync` here logs to `~/Library/Logs` and runs `/bin/bash`; Python is a different TCC subject.
  - gh keychain access under launchd.
- **Fix direction.** Move the live proof to after landing, run it from the primary checkout, and require evidence that a run actually happened. Put the scheduler log where this machine's working agents put theirs.
- **The way.**
  - Set `StandardOutPath = StandardErrorPath = ~/Library/Logs/ai-tracker-pending.log`, and update the `.gitignore` entry to match (it is no longer in the repo).
  - Post-landing checklist (Log entry), each item a pass condition:
    - `make pending-install`;
    - `launchctl kickstart -p gui/$UID/com.aitracker.pending`;
    - `launchctl print …` shows `last exit code = 0`;
    - `pending.json` `generated_at` has advanced;
    - the log has no `Operation not permitted`;
    - `make pending-uninstall`;
    - `launchctl print` then returns rc ≠ 0 and the plist is gone.
  - Record the TCC and gh results in §10.
- **Test.** No unit test can cover this. The checklist is the test. Add a §10 line: "launchd run under TCC: proven on <date> / not yet".

### C-S6 — Under the default `dry-run`, `PENDING_INTERVAL` does nothing observable; the worker really runs daily, gh included (U8 / C2)
- **Defect.** §3 `tick()`: the "clean" branch at the interval runs `run_once(config.PENDING_CLEAN="dry-run")`, which is identical to the daily list refresh. A user who sets `90d`, as asked, sees a card refreshed daily and ≤20 gh calls daily; changing the value has no effect until Safe delete is on. §9 D5 bounds gh "per scan", but never says scans are daily plus every Scan now, so the network bound per day is unstated. The C2 row says "the listing refreshes daily" but not that the interval is inert in the default mode.
- **Fix direction.** This is a decision, not a code bug. **Recommended:** keep the daily list, relabel the setting "Cleanup interval (only acts in Safe delete)", and state the daily gh cadence in D5. **Alternative to offer the user:** the daily list skips gh and uses `gh_cache` only, so gh runs at most once per `PENDING_INTERVAL` and on Scan now. That costs squash-merge labels lagging up to the interval.
- **The way.**
  - Text edits: §2 `ext_cr_dialogs.js` row copy, §9 D5 (add "a scheduled scan runs at most once a day, plus manual Scan now"), and the C2 clause row.
  - The alternative would be one parameter: `run_once(mode, gh=False)` from the list branch.
- **Test.** For the recommended text-only fix: none. For the alternative: `test_pending_gh.py` asserts the list branch of `tick()` makes 0 fake-gh calls.

### C-S7 — U7 may return nothing on the user's own repos: gh's repo resolution isn't pinned
- **Defect.** §3 `_gh` runs with `cwd=<top>` and lets gh infer the repo, and three things undermine that:
  - This repo's only remote is the SSH alias `git@github-personal:mepritamm/ai-tracker.git`. Whether gh maps that alias to github.com is unverified, and the gh account may be the EMU one.
  - Repos with 2+ remotes and no `gh repo set-default` are refused.
  - A `GH_REPO`/`GH_HOST` set in the server's environment overrides the cwd for **every** worktree.

  Each case fails closed, because `headRefOid == head` prevents a false MERGED. So there is no data risk, but U7 can silently deliver nothing, and no step measures it.
- **Fix direction.** Measure first. Strip the env overrides. Keep fail-closed.
- **The way.**
  - In `_gh`, remove `GH_REPO` and `GH_HOST` from the child env.
  - Step 8 gains "run once on the real disk; log the count of each `gh.state`", mirroring step 7's coverage measurement.
  - Optional, and flagged as possibly wider than the defect: pass `-R <owner>/<repo>`, parsed from `git remote get-url $(git config branch.<b>.remote)` with `[:/]([^/:]+)/([^/]+?)(\.git)?$`, when that remote's host is github.com or an alias whose ssh `HostName` is github.com.
- **Test.** `test_pending_gh.py` N8: with `GH_REPO=x/y` in `os.environ`, the fake gh's logged env has no `GH_REPO`. Red under v3.

---

## Nits
- **C-N1 Breaker scope.** Offline and rate-limit failures from gh exit 1 quickly; they are neither exit 4 nor a timeout. So the breaker never trips, and all 20 calls fail one by one. Direction: trip on *any* `error` (fail-closed, fewer calls). Way: in `gh_merged`, `if state == "error": break`. Test: N5 variant with fake exit 1, and exactly 1 call.
- **C-N2 Merged into what.** A PR merged into a non-base branch (a stacked PR) still counts as MERGED. This is safe: the worktree is clean, the branch ref is kept, and commits survive. Direction: no behaviour change. Add `baseRefName` to `--json` and the label ("squash-merged into develop (PR #12)").
- **C-N3 `gh_cache` key.** A `(repo, branch, head)` tuple can't be a JSON key. Use `"\x00".join(...)`, and drop entries whose repo is no longer in `repos[]`. Test: `json.dumps(report)` round-trips after N1.
- **C-N4 D5 wording.** Change "never the HTTP server's request path" to "never synchronously inside a request handler (the server's worker and Scan-now threads may)". Change "sends nothing beyond what that gh call sends to the repo's own GitHub remote" to "contacts only the GitHub API host gh resolves for that repo, with gh's own credentials (stored login or `GH_TOKEN`)". Add the daily cadence (C-S6).
- **C-N5 Same label from two checkouts.** A second `--install-scheduler` silently repoints the job, and `--uninstall-scheduler` from any checkout removes it. Direction: keep one per-user job. Way: install prints "replacing job that pointed at <old WorkingDirectory>" when the plist exists with a different root, and `status()` returns `root` and `root_exists`. Test: install twice with different `_root`; the second prints the old root.
- **C-N6 Env and config reach.** The OS job sees only PATH and PYTHONPATH, so `TRACKER_PENDING_*` env overrides never reach it. It also reads the *installed checkout's* `config.json` (`config.py:202`, which is per checkout), so settings saved from a server in another checkout don't apply to the OS job. Direction: document in README and §10; no code.
- **C-N7 Windows.** `os.getuid()` (used for `gui/<uid>`) must stay inside the darwin branch, never at module level; state it in §3b. `/TR` with `python.exe` flashes a console window daily, so prefer `pythonw.exe` from the same dir when it exists. The task has no log, so add `>> "%LOCALAPPDATA%\ai-tracker-pending.log" 2>&1` if the 261-char cap allows. The task runs only while the user is logged on. Otherwise §3b's honesty is adequate. Nothing new imports `fcntl` or `pty` at top level, and `os.kill` is avoided via `_alive`.
- **C-N8 Step 7 is too big for one sonnet leg.** It holds the fixture helper, discover, inspect, classify, report, card and 14 fixtures. Split it:
  - 7a: `tests/pending_fixture.py`, discover and inspect, with fixtures B, C, E, I, J;
  - 7b: classify, report and card, with the rest.

  Both stay sequential.
- **C-N9 Validator case.** `re.I` accepts `3M`, so `_UNIT_S[m.group(2).lower()]`. Test: `interval_seconds("3M") == 7776000`.
- **C-N10 Standalone bundle has no `ext_*` JS.** `bundle.inlined_page` inlines only app.js, so `window.ExtLaunch` is absent there. `pendingResume`'s guard must show "Resume unavailable in this build — use Copy prompt" rather than fail silently. Test: a node stub without `ExtLaunch` gets the message.

## Checked and found sound (no finding)
- **U6 read-only.** `/api/pending*` are absent from `_RO_GET_ALLOW` (`server.py:248`). `loadPending` runs after `applyReadOnly(res)` inside `loadSide` (`app.js:1315-1334`), so a read-only viewer skips it after the first response, and the server refuses it regardless.
- **U6 load order.** `page.py:20` concatenates `app.js` and then the sorted `ext_*.js` into one `<script>`. `let pendingCache` (app.js) initialises before any ext code runs, so `typeof pendingCache` in `ext_cr_boot.js` has no TDZ.
- **U6 double card.** Control Room mode hides `.app` (`ext_cr_boot.js:228-237`), so the classic `#pendside` never shows next to the board tile.
- **U7 guards.** MERGED only replaces the ancestor/unpushed term. Dirty, untracked, ignored, idle, job, live and own-tracker all still gate, and `head` equality plus the TOCTOU re-inspect hold. Fork branch-name collisions (`--head` has no owner filter) are neutralised by `headRefOid == head`.
- **U8.** The validator table is consistent with the regex (`mo` before `m` in the alternation). The fixed 7d grace is decoupled and tested at `1d` and `90d`.
- **§7 parallel waves.** Wave 1 steps 1–6 and wave 3 steps 11–14 are file-disjoint, test files included (`test_page_css.py` only in step 13, `test_selfcheck.py` only in step 1). The only gap is C-B2's ORDER/HEADER edit, which belongs in step 10.
- **Reconciled fixes dropped by v3.** Two: **B-B1** (named imports) is re-violated by `schedule.X` (C-B2), and **A-S7** (per-user lock) is voided by `gettempdir` (C-S1). No other reconciled row is lost.

## Clean-plan deltas
1. §3 `start_worker()`: remove the `schedule.installed()` clause. §3b: delete `installed()`. `tick()` reads `pending.json` fresh. `install()` removes the plist when bootstrap fails. `status()` adds `last_exit`, `root` and `root_exists`. §1 caller (a) becomes "always, when the interval is not off". §9 D1: "both run; `tick()` dedups". [C-B1]
2. §3b: rename to `sched_install`/`sched_uninstall`/`sched_status`, imported by name into pending.py. §2 bundle row: ORDER `… tunnel.py, schedule.py, pending.py, server.py …`, and HEADER `+ plistlib`. Step 10 file list adds the HEADER edit and the TestBundle assertions. [C-B2]
3. §2 config: `PENDING_LOCK = ~/.ai-tracker-pending.lock`, and drop the `tempfile`/`getpass` imports. [C-S1]
4. §3 `tick()`: return `"off"` first when the interval is None. [C-S2]
5. §3: `SLACK = 3600` in `due()` and in the list-refresh check. [C-S3]
6. §3b: `plist_path()` late-bound from HOME. Step 3 test asserts the real LaunchAgents dir is untouched. [C-S4]
7. §3b log path becomes `~/Library/Logs/ai-tracker-pending.log`, with `.gitignore` updated to match. Step 16's launchd proof moves post-landing, with the kickstart / last-exit / generated_at / TCC checklist, and §10 records the result. [C-S5]
8. Settings copy, D5 and the C2 row disclose that the interval only acts in Safe delete and that scans run daily, gh included. Offer the user the gh-free daily list as an alternative. [C-S6]
9. `_gh` strips `GH_REPO`/`GH_HOST`. Step 8 logs the real-disk `gh.state` counts. `-R` derivation is optional. [C-S7]
10. Nits C-N1 to C-N10 as written: breaker on any error, `baseRefName`, string cache key, D5 wording, repoint message, env/config doc, Windows notes, split step 7, `.lower()`, bundle Resume message.
