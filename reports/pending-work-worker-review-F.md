# Review F: non-functional behaviour of the pending-work worker and addendum A.1

Reviewer F (opus). Static review only. No tests, servers, `make` or CLI were run, because a full gate was in flight. Scope: the user's H5 instruction (slowness, sync-ness, speed, load on the app) checked against "### Non-functional plan (H5)" P1–P7 and the code as it stands in this worktree (uncommitted tree, 2026-11-15).

Facts gathered by read-only probes:
- The real report from the one list-only run is `aitracker/pending.json`. It is **921,159 B and 28,178 lines** (`_save_json` writes `indent=2`). It has 510 `kind:worktree` and 423 `kind:scratch` matches (these counts include the `would_delete` entries). Also `"duration_s": 243.568` and **`"scheduled_at": null`**.
- A synthetic 479 + 353 report with typical fields is 667 KB as compact JSON. So the `/api/pending` body (compact, without `gh_cache`) is about 0.6–0.9 MB.
- Machine: 77 `~/.claude/projects` dirs, 151 jobs, 16 live-session files, and 10,800 entries under `/tmp/claude-501`, so `_walk_tree` is cheap here.
- Page weight. This sums the `ls-tree -l personal/main` blob sizes against the current files, over `index.html`, `app.js`, `app.css`, `ext_cr.css`, `ext_cr_board.{js,css}`, `ext_cr_boot.js`, `ext_cr_dialogs.js` and `ext_launch.js`. The total is **+18,271 B**, against the H5 budget of ≤ +20 KB. That is within budget, but 91% of it is already used.
- Nothing new is on the `/api/list` path except the `X-Server-Started` header (`server.py:445`). `all_sessions()` and `registry`/`providers` do not touch pending, update or schedule. `is_loopback_host` (`util.py:715`) is a pure string and ipaddress parse with no DNS. `/api/session` is unchanged.
- H5 P1–P7 were never run. `scripts/perf_startup.py` and `scripts/perf_list.py` do not exist, and the Log has no numbers. The T16 guard tests are also missing (F13).

---

## Findings

### F1 — should-fix: `next_due` changes on every call, so the client re-renders everything every poll
1. **Defect.** `pending.py:919` sets `r["next_due"] = ... (r.get("scheduled_at") or time.time()) + secs`. When `scheduled_at` is null, the body of `GET /api/pending` is different on every call. That is the state of the real report today, and of any report produced only by Scan now or `--dry-run`, or after a scheduled run that failed or found the lock busy.
   - `app.js:2337` then computes `changed=JSON.stringify(j)!==JSON.stringify(pendingCache)`, which is always true. So every fetch runs `renderPendingSide()`, re-runs **all** `SIDE_EXT` hooks (a full CR board, dialogs and term rebuild, `ext_cr_boot.js:998`), and, if the Pending list modal is open, calls `openPendingList()`. That rebuilds about 830 rows and resets the modal's scroll position.
   - Repro: real report, interval 90d, open the list and scroll. It jumps to the top every 60 s, and **every 5 s while a scan runs** (`every=5000` when `running`).
   - Expected: no re-render when nothing changed.
   - The semantics are also wrong. With no `scheduled_at` the scan is due now, not 90 days from now. `next_due` has no consumer in `web/` and no test.
2. **Direction.** Make the body deterministic for an unchanged file. Do not change the cadence or the server-owned card.
3. **Way.**
   - In `load_report` set `sa = r.get("scheduled_at"); r["next_due"] = (sa + secs) if (secs is not None and isinstance(sa, (int, float))) else None`, and say in the docstring that None means "off, or due at the next check".
   - Belt, in `app.js` `loadPending`: compare a cheap key, ``const key=[j.generated_at,j.running,JSON.stringify(j.card||{}),(j.items||[]).length,(j.tmp||[]).length].join("|")``, instead of stringifying the whole report twice.
   - The CR board needs nothing extra, because it reads `pendingCache.card` through the same `SIDE_EXT` path.
4. **Test.**
   - `tests/test_pending_routes.py`: write a report with `scheduled_at: None` and the interval on. Two `load_report()` calls 1.1 s apart (or with `time.time` patched) must return equal dicts. This is red today.
   - `tests/test_pending_ui_classic.py` (node harness): call `loadPending` twice against an identical body. `renderPendingSide` and `openPendingList` must each run once. This is red today because of `next_due`.

### F2 — should-fix: every fresh or worktree checkout scans the whole machine 60 s after start; checkouts do not dedup each other
1. **Defect.** `config.py:18` makes `PENDING_FILE` per checkout (`_HERE`), while `PENDING_LOCK` (`:21`) is per user.
   - `run()` always calls `start_worker()` (`server.py:1015`). `_worker_loop` sleeps 60 s, then `tick()` sees no report, so `due()` is True and it runs a full `run_once` (`pending.py:852–882`).
   - Any `make serve` from a new worktree therefore starts a scan at T+60 s: about 4 min, ~3,800 niced git children and up to 20 gh network calls. That includes the test and UI-check servers that this repo's workflow starts in `.claude/worktrees/*`. It also overwrites that worktree's report.
   - Repro: `make serve` in a fresh worktree and wait 70 s. `ps` shows `nice git ... status --porcelain=v1 -z --ignored=matching` children, and the user's 8787 dashboard, if it runs this code, shows "scanning…".
   - Plan lines 603 and 861 claim "the second caller finds nothing due". That holds only inside one checkout: N checkouts mean N full scans per interval. The lock serialises the scans; it does not remove the duplicates.
   - `autoinstall_once` already refuses linked worktrees and temp dirs (`schedule.py`). The in-server worker has no such guard.
2. **Direction.** The automatic tick runs only from a checkout that may own the schedule. Scan now and the CLI must keep working everywhere, the bundle keeps its worker, and nothing changes for the primary checkout.
3. **Way.**
   - Move the predicate out of `autoinstall_once` into `schedule.auto_scan_ok()`: not a linked worktree, no `/.claude/worktrees/` in the root, not temp, not under test.
   - `autoinstall_once` keeps its separate bundle check. The bundle keeps the worker, because the standalone file is a real user path.
   - In `_worker_loop` (`pending.py:873`), call `tick` only when `auto_scan_ok()` is true, and otherwise sleep 3600. Reading it per loop keeps tests patchable.
   - Windows: `_is_linked_worktree` checks for the `.git` file, which works the same on Windows. The bundle needs no change.
   - Alternative, for the user to decide: move `PENDING_FILE` and `PENDING_LOG` under HOME, so every dashboard shares one report and one `scheduled_at`. That also fixes the inconsistency between two dashboards. But two checkouts with different `PENDING_CLEAN` would then race for one `scheduled_at`, so it is wider than the defect and **not** recommended.
4. **Test.** `tests/test_pending_tick.py`:
   - With `schedule._root` patched to a dir that has a `.git` *file*, `_worker_loop(sleep=fake, clock=...)` never calls the patched `tick`. With the primary-checkout root it calls `tick` once.
   - Red before the fix, because the loop ticks unconditionally.

### F3 — should-fix: a scan that keeps failing is retried every hour, forever
1. **Defect.** In `pending.py:873–882` the loop sets `wait = 3600` and then calls `tick()`. If `tick` raises, `wait` stays 3600.
   - Failure modes include `_save_json(PENDING_FILE)` raising OSError when `_HERE` is unwritable, the disk is full, or a package install dir is read-only, plus any unexpected exception in classify or `gh_merged`.
   - None of these move `scheduled_at`, so the worker repeats the 4-min scan and up to 20 gh calls every hour. That is about 6.7% duty of heavy IO, and about 480 gh calls a day. `_log` also writes into `_HERE`, so the failure is silent.
   - Repro: `chmod a-w aitracker/` with the interval on. A scan runs every hour.
2. **Direction.** Back off on consecutive failures. Do not change the success path: the 60 s boot delay and the 3600 s cap.
3. **Way.** Keep a local `fails` counter in `_worker_loop`.
   - On exception: `fails += 1; wait = min(86400, 3600 * 2 ** (fails - 1))`, and pass it as `sleep(max(60, wait))`, because the 3600 cap applies only after a success.
   - On success: `fails = 0` and the current `min(3600, ...)` formula.
4. **Test.** `tests/test_pending_tick.py`: a fake `tick` that always raises must give sleeps `[60, 3600, 7200, 14400, ...]`, capped at 86400. The existing `test_worker_loop_survives_exceptions_and_sleeps_at_least_60` asserts `s <= 3600` for every sleep and must be updated to the new cap. Red before the fix: the sleeps are all 3600.

### F4 — should-fix (gated on M3/M5): GET /api/pending reads and parses ~0.9 MB per call; the client keeps and compares the whole report
1. **Defect.**
   - Server: `server.py:462` calls `load_report()` → `_load_json` on the 921 KB file, plus a flock probe, a shallow copy and `json.dumps` of about 0.6–0.9 MB. That costs an estimated 15–25 ms of GIL-held CPU per call, against the H5 budget of p50 < 20 ms.
   - Client: `res.json()` plus two `JSON.stringify` calls of the whole report (`app.js:2337`), about 15–30 ms on the main thread. `pendingCache` keeps the parsed report alive in every tab, a few MB of heap.
   - Cadence: once a minute per tab, and every 5 s for the whole of a ~4-min scan (about 48 full transfers per tab per scan), even though the poll only uses `card` and `running`. `item_detail` (`pending.py:957`) parses the same file again on every item click.
2. **Direction.** Avoid re-parsing an unchanged file and avoid re-comparing the whole body. The server stays the owner of the card, and both views still read one `pendingCache`.
3. **Way.**
   - (a) In `pending.py`, add `_read_report()`, which memoises `_load_json(config.PENDING_FILE)` keyed on `(st_mtime_ns, st_size)`. Use it in `load_report` and `item_detail`, and keep `load_report`'s shallow `dict(r)` so the cache is never mutated.
   - (c) The client compare key from F1.
   - (b) Only if M3 or M5 still miss budget after (a) and (c): `GET /api/pending?view=card` returns `{card, running, generated_at, scheduled_at, mode, interval, duration_s, count}`. `loadPending` polls that. `openPendingList` fetches the full body when it opens, and again on change while it is open. `ext_cr_board.js:2687` then calls `openPendingList(null)`, which fetches. (b) is wider than the defect: flag it.
4. **Test.**
   - `tests/test_pending_routes.py`: two `GET /api/pending` calls with the file unchanged give one `_load_json` call (patch to count it). Touching the file gives two. Red before the fix.
   - For (b): node harness, the poll fetches `?view=card` only, and opening the list fetches the full body.

### F5 — should-fix: /api/pending/item runs up to 4 × 10 s of git on a request thread and buffers unbounded output
1. **Defect.** `pending.py:976–983` runs `status --short`, `diff --stat`, `diff` and `log` through `_git` (timeout 10 s each, so up to 40 s worst case). `capture_output` loads the **entire** stdout before `_cap` trims it to lines.
   - Repro: a worktree with a large uncommitted text change (a regenerated `dist/tracker.py` of about 1 MB+, a lockfile, a data file). `git diff` streams megabytes into the server process, which decodes and splits them, and the item click stalls for seconds.
   - `git diff` also honours the user's `diff.external`, textconv and `color.ui=always`. An external diff tool can hang for 10 s or emit ANSI into the markdown.
   - Clicking items in several tabs while a scan runs adds git children beyond H5's "≤ 1 child at a time".
2. **Direction.** Bound bytes and time per item. Keep the 4 sections, the fencing and the line caps. No scan, no gh.
3. **Way.**
   - Add `_git_capped(cwd, max_bytes, *args)` in `pending.py`. Use `subprocess.Popen([*_nice(), "git", "--no-optional-locks", "-C", cwd, *args], stdout=PIPE, stderr=DEVNULL, env=...)`, read up to `max_bytes` (256 KB), kill when there is more, and use `wait(timeout=GIT_TIMEOUT)`. Use it for the four item-detail calls.
   - Add `--no-ext-diff --no-textconv --no-color` to both diffs and `--no-color` to `log`.
   - Optionally give the whole call a 15 s deadline.
   - This is POSIX and Windows-safe, because Popen/kill are portable and `_nice()` is already `[]` on Windows.
4. **Test.** `tests/test_pending_routes.py`:
   - A fixture worktree with a 5 MB uncommitted file: `item_detail` returns in under 3 s and `len(md) < 300_000`.
   - A fixture repo with `git config diff.external <script that sleeps 30>`: the call returns in under 3 s and the diff text is present.
   - Both are red before the fix.

### F6 — should-fix (cheap half now; process-split half gated on M4): the scan's Python work holds the server's GIL; IO is not throttled in the in-server path
1. **Defect.**
   - The scan runs in the server process: `run_async` → `run_once`, and the worker thread.
   - Its pure-Python parts hold the GIL against request threads: `build_ctx`, `_walk_tree` and the `json.dump` of about 1 MB. The worst part is the containment loops.
   - `_last_activity` (`pending.py:358–360`) iterates every `ctx["tx"]` cwd per worktree. `_job_busy` and `_live_under` (`:364–369`) iterate every job and every live cwd. Each calls `_under`, and each `_under` does **two `os.path.realpath`** calls, one lstat per path component, even though the ctx keys are already realpath'd.
   - That is about 510×77 + 510×151 + 423×16 ≈ 123k `_under` calls, or about 250k realpath calls: an estimated 5–15 s of GIL-held Python per scan, in the server process.
   - Git children are `nice -n 10` (CPU only). The launchd job is `ProcessType: Background` + `LowPriorityIO`, but the in-server path has neither. And the in-server worker, which checks every hour, is the path that normally wins the race to a due scan.
   - Expected: `/api/list` p95 during a scan ≤ 1.5× idle (H5). It is unmeasured.
2. **Direction.** Cut the redundant syscalls now. Keep `_under` (commonpath) unchanged for the deletion guards. Move the whole scan out of process only if M4 fails.
3. **Way.**
   - Cheap half: in `inspect_worktree`, compute `rp = _rp(path)` once. Add `_under_rp(child_rp, root_rp)`, which returns `child_rp == root_rp or child_rp.startswith(root_rp.rstrip(os.sep) + os.sep)`. Use it in `_last_activity`, `_job_busy` and `_live_under`, whose ctx keys are already `_rp`'d. Keep `_under` itself for `_reinspect`, the clean guards and `scan_tmp`'s depth checks.
   - Gated half, wider than the defect, so flag it: `run_async` and `_worker_loop` would spawn `[*_nice(), sys.executable, "-m", "aitracker", "--pending", "--dry-run"|"--if-due"]` with `cwd=_root()` (the bundle uses `[sys.executable, __file__, ...]`). `load_report`'s lock probe already reports another process's scan as `running`.
   - On darwin, consider prefixing `taskpolicy -b`. Its flag semantics need confirming by a researcher first; not verified here.
4. **Test.**
   - Cheap half, `tests/test_pending_scan.py`: a fixture with 3 worktrees and 30 transcript cwds. Count `os.path.realpath` calls during `scan()`; the count must be ≤ 4 × (worktrees + tx + jobs + tmp). Red before the fix, which is about 2 × worktrees × tx.
   - The F6 classification results must be byte-identical before and after on the fixture.

### F7 — nit: `discover_repos` runs one git child per seed, with no dedup
1. **Defect.** `pending.py:263–298`: seeds are `all_cwds()`, plus 3 keys from each of the 151 job `state.json` files, plus the previous `repos[]`. They are not deduplicated, and each one runs `git rev-parse --git-common-dir`: hundreds of redundant niced git spawns, roughly 10–20 s of the 243 s.
2. **Direction.** Run one `rev-parse` per distinct existing dir. Keep `ent["cwds"]` exactly as it is now.
3. **Way.** Keep a `memo = {}` that maps `d` to `common` (or None). On a hit, skip the git calls but still run the `cwds` append branch.
4. **Test.** `tests/test_pending_scan.py`: 5 job `state.json` files that all point at the fixture repo should give exactly one `rev-parse --git-common-dir` for that dir (count via a wrapped `pending._git`). Red before the fix.

### F8 — nit: the card is stale between runs and says nothing about its age
1. **Defect.** After a worktree is cleaned through Resume, nothing updates the card until Scan now, or the next interval (90 d). The card (`build_card`, `pending.py:629`) has no "as of". The item modal does show live git, and "missing from disk".
2. **Direction.** Be honest about staleness without making the body time-dependent, because that would bring F1 back.
3. **Way.**
   - In `build_card`, add `"as_of": time.strftime("%Y-%m-%d", time.localtime(report["generated_at"]))`. The value is fixed at scan time.
   - Both renderers append "· scanned <as_of>": `renderPendingSide` (`app.js:2349`) and `pendingTile` (`ext_cr_board.js:2675`).
   - A per-item re-check route is deferred; say so in Known gaps.
4. **Test.** The T9-style node test: both renderers show the same `as_of` text, and `card.as_of` exists in the `scan()` output (`tests/test_pending_scan.py`).

### F9 — nit: any lock holder makes the card pop in for ~4 min, shifting the layout of other dashboards
1. **Defect.** `pending.py:908–916`: when `running` is true, the card gets `show=True, summary="scanning…"` even when the stored card is hidden.
   - The lock is per user, so a scan from another checkout's dashboard, the launchd job, or an Update apply holding the lock (`update.py:253+`) makes `#pendside` (above `#slist`) and the CR span2 tile appear. When the scan ends they vanish, which pushes the session list and board down and back up. This also happens on dashboards whose own report will not change.
2. **Direction.** Keep "scanning…" for a scan this process runs. Don't pop a hidden card in for a foreign lock holder.
3. **Way.** `if running: card = dict(card, summary="scanning…", show=card.get("show") or _RUNNING.is_set())`. The modal's Scan-now button keeps using `running`.
4. **Test.** `tests/test_pending_routes.py`:
   - Lock held through a second `_pending_lock()` and an empty report: `running` is True and `card.show` is False.
   - With `_RUNNING.set()`: `card.show` is True.
   - The first case is red before the fix.

### F10 — should-fix: every server restart hard-reloads every open tab, discarding typing and modals
1. **Defect.** `app.js:1342–1350`: `serverRestarted()` calls `location.reload()` as soon as `X-Server-Started` changes. Every `make serve` restart then reloads every tab within 5 s, and agents restart test servers often. The reload discards a half-typed rename or notes input, open modals and terminal scroll.
   - The baseline is taken from the first `/api/list`, not from the page. If the server restarts between page load and the first poll, the stale page is never reloaded.
2. **Direction.** Reload automatically only when the user is not editing; otherwise show a one-line "Dashboard restarted — reload" prompt. The Update path's explicit reload (`ext_cr_dialogs.js` `waitForRestart`) is unchanged.
3. **Way.**
   - In `serverRestarted`: when `document.activeElement` is an `input`, `textarea`, `[contenteditable]` or `.xterm` element, or a `#msgmodal` is open, set `restartPending=true`, show the banner and return false. On the next poll with no focus, reload.
   - Bake `_STARTED` into the page through a `page.py` marker, as `LIVE_MARK` is done, so the baseline is the page's own server. This needs `page.build_page` to accept it. Keep it optional.
   - Classic view and CR share this function, so one edit covers both.
4. **Test.** The node harness (as `tests/test_update_settings_ui.py` does): with activeElement set to a textarea and a changed header, `location.reload` is not called and the banner node exists. With no focus, it is called. Red before the fix.

### F11 — nit: Update fetch and apply block their own request thread for up to about 4.5 min; fetch is not single-flight
1. **Defect.**
   - `server.py:652–666` runs `update_fetch()` and `update_apply()` synchronously. Fetch takes up to 60 s. Apply runs fetch (60 s) + `git archive` (60 s) + preflight (90 s) + merge (60 s).
   - That contradicts the H5 sync-ness row ("fetch and apply each run on a thread or return a 409"). Other requests are unaffected (ThreadingHTTPServer), and the UI shows busy.
   - `update_fetch` has no single-flight guard. "Check for updates" in two tabs runs two `git fetch` processes on one repo, which can fail with ref-lock errors.
2. **Direction.** Accept the synchronous request and record it as a deliberate deviation in H5. Add single-flight to fetch only.
3. **Way.** `_FETCH = threading.Lock()` in `update.py`. In `update_fetch`, when `acquire(blocking=False)` fails, `return dict(update_status(), fetch_error="a fetch is already running")`, and release in `finally`.
4. **Test.** `tests/test_update.py`: two threads call `update_fetch` with a slow fake `_run` (an Event). Exactly one `fetch` argv is recorded, and the other result has `fetch_error`. Red before the fix.

### F12 — nit: launchctl and schtasks calls have no timeout
1. **Defect.** `schedule.py` calls `run([...], capture_output=True, text=True)` with no timeout in `sched_install`, `sched_uninstall` and `sched_status`. POST and GET `/api/scheduler` run them on a request thread, and GET runs on every Settings open. A hung `launchctl` pins that thread and the Settings block indefinitely. The autoinstall thread is daemon, so it is harmless there.
2. **Direction.** Add a 15 s bound. A timeout means "failed" or "not installed", never a raise.
3. **Way.** Pass `timeout=15` in every `run(...)` call in `schedule.py`, and catch `subprocess.TimeoutExpired`. Install returns 1; status reports `installed: False` with `error: "timeout"`. Cover the Windows `schtasks` calls too.
4. **Test.** `tests/test_pending_schedule.py`: a fake `run` raising `TimeoutExpired` makes `sched_status` return without raising, and `sched_install` return 1. Red before the fix (it raises).

### F13 — should-fix: the T16 non-functional guard tests are missing
1. **Defect.** Plan H8 T16 ("`/api/list` still 200 with pending/update/scheduler functions patched to raise; `GET /api/pending` still 200 with `scan`/`run_once` patched to raise") has no test. The only `/api/list` check is `test_list_carries_server_started` (`tests/test_update_routes.py:94`). Nothing prevents a future edit from putting a scan, a `launchctl` call or a git call on the 5 s list path.
2. **Direction.** Add the guards. Leave the code as it is.
3. **Way.** In `tests/test_pending_routes.py` (it has the `_Base` server), add two tests:
   - `test_list_path_never_touches_pending_update_scheduler`: patch `pending.scan`, `run_once`, `load_report`, `item_detail`, `server.update_status`, `server.sched_status` and `schedule.autoinstall_once` with `side_effect=AssertionError`. `GET /api/list` and `GET /api/session?id=...` (with a fixture session) must return 200.
   - `test_get_pending_never_scans`: patch `scan` and `run_once` to raise, then `GET /api/pending` must return 200.
4. **Red-proof.** Temporarily add `load_report()` into the `/api/list` branch (`server.py:451`). The first test goes red.

### F14 — nit: the H5 measurements were never taken
1. **Defect.** P1–P7 have no scripts and no numbers in the Log, so every budget in the H5 table is unverified.
2. **Direction.** Run the Measurement plan below and write the numbers to the Log. A miss is reported with its number and re-planned, not "fixed" on the spot.
3. **Way / 4. Test.** See M1–M11.

### F15 — nit: new tests are slow and leak processes
1. **Defect.**
   - `tests.test_update` takes about 100 s and `tests.test_pending_tick` about 30 s. Every test rebuilds its git fixture: a bare repo, clones and pushes, about 8–10 git spawns, in `pending_fixture.Fx` and `update_fixture.UFx`. Every scan git child in the pending tests is `nice -n 10`, so under a busy full gate it is starved, which is a plausible cause of the slow and load-sensitive behaviour.
   - `test_master_is_closed_in_the_exec_image` (`tests/test_update_restart.py:45–60`) leaves an orphaned `sleep 30` behind on each of its 2 runs, because the `finally` after a successful `execv` never runs.
2. **Direction.** Measure first (M10). Then make the cuts that keep isolation and every assertion.
3. **Way.**
   - (i) Build the fixture template once per class (`setUpClass`). `shutil.copytree(template, root, symlinks=True)` per test, then rewrite the remote URL. Worktree admin paths are absolute, so worktrees must still be created per test.
   - (ii) In `pending_fixture.Fx`, patch `pending._nice` to return `[]`. `tests/test_pending_nice.py` keeps covering `_nice`.
   - (iii) In the cloexec test, pass the sleeper pid to the probe as `argv[2]` and have the probe `os.kill(pid, 9)` before printing.
   - (iv) Lower `FETCH_TIMEOUT` in the timeout test from 3 to 1.
4. **Test.** `python -m unittest --durations 25 <module>` before and after (M10). The test count is unchanged, and the assertions are byte-identical.

### Left alone deliberately (direction stated)
- **N1 — Lock-probe race.** `load_report`'s non-blocking flock probe can, for about 100 µs, make a concurrent `run_once` (a Scan-now or scheduled tick) see "busy" (`pending.py:910`). Probability is about 1e-6 per poll. A scheduled tick retries in 60 s. A lost Scan-now click is visible, because the button returns. **No change**; note it in Known gaps.
- **N2 — SIGTERM mid-scan.** The handler runs on the main thread, `SystemExit` leaves `serve_forever` within the 0.5 s poll, and the scan and worker threads are daemon. A running git child is orphaned for ≤ 10 s, niced, and harmless. A kill during `_save_json` can leave a `.pending.json.<uuid>.tmp`; `os.replace` keeps `pending.json` itself intact. **No change**; M9 confirms it.
- **N3 — In-app restart blind window.** `execv` closes the listener (cloexec, `update.py:304`). The new interpreter re-imports and re-binds with SO_REUSEADDR. Requests in that window get ECONNREFUSED, which `loadSide` swallows. `waitForRestart` polls at 1 Hz. Estimated ≤ 2 s blind; budget ≤ 5 s. **No change**; M7 measures it.
- **N4 — First run.** The first `make serve` on the primary checkout scans 60 s after start, for about 4 min with gh calls. This is by design (U-decisions). **Document it in the README**; no change.
- **N5 — Remote tabs.** A tunnel or LAN tab with auth that is not read-only gets a 403 from `/api/pending` every 60 s. Harmless. Optional one-liner: in `loadPending`, set `pendingOff=true` on a 403.
- **N6 — Page weight.** +18.3 KB, within the 20 KB budget. **No change**; keep M6 in the gate notes.
- **N7 — Launchd plus server thread in one checkout.** These dedup correctly: the shared `scheduled_at` plus the lock, and the loser retries in 60 s, which costs only a flock probe.

## Not examined
- `store.py` and `util.py` diffs, apart from `is_loopback_host`.
- `term_gate.py` and `term_vt.py` changes (beyond the brief's note that the Host check sits inside `guard`).
- The `ext_launch.js` `openAt` and `pickDirectory` changes.
- CSS for layout cost.
- `scripts/bundle.py` ORDER, and bundle import time.
- Windows runtime behaviour (static only).
- `clean()`/`_reinspect` cost in `safe` mode: `build_ctx()` runs per deletable item, about 100× in a large clean. That is likely a few seconds; measure it if `safe` is ever the default.
- Whether macOS `taskpolicy -b` is the right IO throttle (needs a researcher).
- Whether `git status --ignored=matching` is the dominant per-worktree cost (M4 trace2 answers this).

---

## Measurement plan

Run this once the gate is idle. Agents: haiku `gate-runner` for M1–M3, M5, M6 and M10; sonnet for M4, M7, M8, M9 and M11.

Rules for every step:
- Ports **8811** (branch) and **8812** (base); M7 uses **8813**. Never 8787 or 8790.
- Start servers in the background, write their PID files, and stop them with `kill $(cat <pidfile>)`. **Never `pkill -f aitracker`.**
- Prefix commands with `unset TRACKER_AUTH;`.
- No `git stash`.
- Write every number to the "## Log" of `reports/pending-work-worker.md`.

**Setup S0 (once)**
```
W=/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/.claude/worktrees/pending-work-worker
B=/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/.claude/worktrees/f-perf-base
git -C $W fetch personal
git -C $W worktree add --detach $B personal/main
mkdir -p /tmp/f-perf /tmp/f-nogh && printf '#!/bin/sh\nexit 1\n' > /tmp/f-nogh/gh && chmod +x /tmp/f-nogh/gh
```
The gh shim makes every gh call fail fast, so the circuit breaker trips after 1 call and there is **no network**.

Write `/tmp/f-perf/lat.py`:
```python
import http.client, sys, time, statistics
port, path, n = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
ts, size = [], 0
for i in range(n + 5):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30); t = time.perf_counter()
    c.request("GET", path, headers={"Host": "localhost:%d" % port}); r = c.getresponse(); b = r.read(); c.close()
    if i >= 5: ts.append((time.perf_counter() - t) * 1000); size = len(b)
ts.sort(); print("n=%d p50=%.1fms p95=%.1fms max=%.1fms bytes=%d status=%d" % (n, statistics.median(ts), ts[int(.95*len(ts))-1], ts[-1], size, r.status))
```

Server start template (`<DIR>` = $W or $B, `<P>` = port):
```
cd <DIR> && unset TRACKER_AUTH; PORT=<P> TRACKER_NO_BROWSER=1 TRACKER_PENDING_INTERVAL=off TRACKER_SCHEDULER_AUTOINSTALL=0 nohup python3 -m aitracker > /tmp/f-perf/srv<P>.log 2>&1 & echo $! > /tmp/f-perf/srv<P>.pid
```
Confirm the bound port in the log ("Starting AI session tracker on http://localhost:<P>"). If it walked to another port, use that one.

**M1 — start-up (P1).** For each of base and branch, 5 runs. Start the server, poll `curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost:<P>' http://127.0.0.1:<P>/` every 20 ms until 200, record ms from spawn, then stop it by PID.
- Record the medians.
- **Pass:** branch median ≤ base + 50 ms.
- **Also pass:** `ps -o pid,comm -g $(cat pid)` within the first 5 s shows no `launchctl` or `git` child (autoinstall is off; the worker sleeps for 60 s).

**M2 — `/api/list` latency (P2).** Both servers up. Run `python3 /tmp/f-perf/lat.py <P> /api/list 200` on base and branch, alternating twice.
- **Pass:** branch p50 and p95 within ±5% of base, or within 3 ms when base p50 < 60 ms, since noise dominates there.

**M3 — `/api/pending` cost (P3).** On the branch server, with the real 921 KB `aitracker/pending.json` in place:
- Run `python3 /tmp/f-perf/lat.py 8811 /api/pending 100`.
- Record p50, p95 and bytes.
- **Pass:** p50 < 20 ms and p95 < 40 ms.
- Repeat while the M2 loop runs on `/api/list` in parallel, and record whether `/api/list` p95 moves more than 10%.

**M4 — scan load, in process (P4; the GIL and IO question).**
1. Restart the branch server with `PATH=/tmp/f-nogh:$PATH GIT_TRACE2_EVENT=/tmp/f-perf/trace2.json` added to its env.
2. Take an idle baseline: `lat.py 8811 /api/list 100`.
3. Start the scan: `curl -s -X POST -H 'Host: localhost:8811' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8811/api/pending/run`. This must return 202 in under 200 ms; record it.
4. While `GET /api/pending` reports `running: true`:
   - (a) Every 1 s, time one `/api/list` request with a loop around `lat.py 8811 /api/list 1`, or use an inline loop.
   - (b) Every 1 s, run `ps -A -o ppid=,comm= | awk -v p=$(cat /tmp/f-perf/srv8811.pid) '$1==p'` and count `git`, `nice` and `gh` children.
   - (c) Every 5 s, run `ps -o rss=,time= -p <pid>`.
5. Record:
   - scan duration (the report's `duration_s`);
   - the server's CPU time delta and max RSS;
   - the maximum concurrent git/gh/nice children;
   - `/api/list` p95 during the scan against idle;
   - from trace2, the git child count and total and mean wall time grouped by the first git subcommand (`jq` on `"event":"exit"` with `t_abs`).
6. **Pass:**
   - `/api/list` p95 during the scan ≤ 1.5× idle;
   - max children ≤ 1 git (a `nice` parent plus its git child counts as 1);
   - gh calls ≤ 1, because of the shim;
   - RSS growth ≤ 150 MB.
7. **A miss triggers F6's gated half.**

**M5 — report size and client parse (P5).** `wc -c aitracker/pending.json`, then save the `/api/pending` body to `/tmp/f-perf/p.json` with curl. Then:
```
node -e 'const s=require("fs").readFileSync("/tmp/f-perf/p.json","utf8");let t=process.hrtime.bigint();const j=JSON.parse(s);let a=Number(process.hrtime.bigint()-t)/1e6;t=process.hrtime.bigint();JSON.stringify(j)===JSON.stringify(j);let b=Number(process.hrtime.bigint()-t)/1e6;console.log("bytes",s.length,"parse_ms",a.toFixed(1),"2xstringify_ms",b.toFixed(1))'
```
- **Pass:** file ≤ 1 MB, `parse_ms` ≤ 20, `2xstringify_ms` ≤ 20. If the stringify misses, F4(c) is mandatory.

**M6 — page weight (P6).** In each of $W and $B, run `python3 -c "from aitracker.page import build_page; print(len(build_page().encode()))"`.
- **Pass:** branch − base ≤ 20,480 B.
- Also check that `grep -c "xterm" ` against the served `/` shows no new vendored asset inlined.

**M7 — in-app restart (P7).** Run this after the in-flight commit lands.
1. Build the fixture:
   - `git clone --bare $W /tmp/f-perf/up.git`
   - `git clone /tmp/f-perf/up.git /tmp/f-perf/app`
   - `git clone /tmp/f-perf/up.git /tmp/f-perf/pusher`
   - In the pusher clone, commit a README one-liner and push.
   - Serve `/tmp/f-perf/app` on 8813 with the S0 template. Temp dirs skip autoinstall.
2. Run a 10 Hz poller of `GET /api/list` that logs each time and status, with connection-refused counted as a gap.
3. Then:
   - `curl -X POST /api/update/fetch`;
   - `t0=now; curl -X POST -d '{"confirm_terminals":true}' /api/update/apply`, recording the apply request duration (the pre-flight time) and `t202`;
   - poll `GET /api/update` every 100 ms until `started_at` changes, giving `t_new`.
4. **Pass:**
   - `t_new − t202` ≤ 5 s;
   - the longest list gap ≤ 3 s;
   - the apply request ≤ 90 s;
   - the new PID is the same as the old one (execv).
5. Stop the server by PID afterwards, and `rm -rf /tmp/f-perf/{up.git,app,pusher}`.

**M8 — item detail.** On the branch server with the real report, pick the 5 ids with the largest `dirty+untracked` using `jq '.items|sort_by(-(.dirty+.untracked))|.[0:5][].id'`. Time each `GET /api/pending/item?id=<id>` 3 times.
- Record p95 and response bytes.
- **Pass:** p95 ≤ 2 s and bytes ≤ 300 KB. A miss confirms F5.

**M9 — SIGTERM mid-scan.** Start the M4 scan. After 15 s, record `date +%s.%N`, run `kill -TERM $(cat srv8811.pid)`, and poll `kill -0` until the process is gone.
- **Pass:** exit ≤ 2 s.
- **Pass:** 11 s later, `ps -A -o ppid=,comm=` shows no `git` whose ppid is 1 and whose cwd is under the scanned worktrees. Use `pgrep -f "no-optional-locks"`; that pattern is distinct from aitracker.
- Record any `aitracker/.pending.json.*.tmp` left behind.

**M10 — test time.** One module per process (OOM rule), in $W and in $B where the module exists:
```
unset TRACKER_AUTH; python3 -m unittest --durations 15 tests.test_update tests.test_update_restart tests.test_update_routes tests.test_pending_tick tests.test_pending_scan tests.test_pending_clean tests.test_pending_routes tests.test_local_host_routes
```
- Record the wall time of each module and the top 15 test durations.
- **Budget:** all new pending and update modules together ≤ 90 s on an idle machine.
- **Pass after F15:** at least a 40% cut with the same test count.
- After the run, check `pgrep -x sleep` for leftovers from `test_update_restart` (F15 iii).

**M11 — client re-render (F1 / F4 proof, sonnet with claude-in-chrome, or the node harness).**
1. Load `http://localhost:8811/` with the real report (`scheduled_at: null`).
2. Open the Pending list.
3. In the console, wrap `window.openPendingList` and `renderPendingSide` with counters.
4. Wait 3 minutes.
- **Today:** at least 3 calls each, and the list scroll resets.
- **Pass after F1:** 0 calls, and the scroll is kept.
- Also record the Performance-panel long tasks over 50 ms per `loadPending` (budget: none).

**Teardown.**
- Stop every server you started, by PID.
- `git -C $W worktree remove $B`. The tree is clean, so no `--force` is needed; if the removal is refused, report it and stop.
- `rm -rf /tmp/f-perf /tmp/f-nogh`.
- Restore `aitracker/pending.json` if M4 overwrote it: `cp` a backup taken before M4 into place, or note that the new dry-run report replaced it.

---

## Fix list
- F1 — `aitracker/pending.py` `load_report`: `next_due` = `scheduled_at + secs` or None; never based on `time.time()`.
- F9 — `aitracker/pending.py` `load_report`: when running, keep `card.show` unless `_RUNNING.is_set()`.
- F4a — `aitracker/pending.py`: `_read_report()` memo on `(mtime_ns, size)`, used by `load_report` and `item_detail`.
- F5 — `aitracker/pending.py` `item_detail`: `_git_capped` (256 KB, kill), plus `--no-ext-diff --no-textconv --no-color`.
- F3 — `aitracker/pending.py` `_worker_loop`: exponential back-off on consecutive exceptions, capped at 86400.
- F2 — `aitracker/pending.py` `_worker_loop`: tick only when `schedule.auto_scan_ok()`.
- F6a — `aitracker/pending.py`: `_under_rp` string-prefix fast path in `_last_activity`, `_job_busy` and `_live_under`, with one `_rp` per worktree.
- F7 — `aitracker/pending.py` `discover_repos`: memo `d -> common` before `rev-parse`.
- F8 — `aitracker/pending.py` `build_card`: add a fixed `as_of` date.
- F2 — `aitracker/schedule.py`: extract `auto_scan_ok()` (linked worktree, `.claude/worktrees`, temp, under test), shared with `autoinstall_once`.
- F12 — `aitracker/schedule.py`: `timeout=15` and catch `TimeoutExpired` on every `run(...)`.
- F11 — `aitracker/update.py` `update_fetch`: non-blocking `_FETCH` lock; return `fetch_error` when it is busy.
- F1/F4c — `aitracker/web/app.js` `loadPending`: stable compare key instead of a double `JSON.stringify`.
- F8 — `aitracker/web/app.js` `renderPendingSide`: append "· scanned <as_of>".
- F10 — `aitracker/web/app.js` `serverRestarted`: defer the reload while editing or a modal is open, and show a banner.
- F8 — `aitracker/web/ext_cr_board.js` `pendingTile`: append "· scanned <as_of>".
- F13 — `tests/test_pending_routes.py`: T16 guards (list and session never touch pending, update or scheduler; GET pending never scans).
- F15 — `tests/pending_fixture.py` and `tests/update_fixture.py`: a per-class template plus copytree; `_nice` patched to `[]`.
- F15 — `tests/test_update_restart.py`: the probe kills the `sleep 30` sleeper.
- F14 — `reports/pending-work-worker.md` Log: M1–M11 numbers.
- (gated on M3/M5) F4b — `aitracker/server.py` and `aitracker/web/app.js`: `GET /api/pending?view=card` for the poll; full body only when the list opens.
- (gated on M4) F6b — `aitracker/pending.py` `run_async` and `_worker_loop`: run the scan as a niced child process.
