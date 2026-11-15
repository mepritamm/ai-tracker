# Adversarial review B — pending-work worker plan v1 (integration with the real code)

Reviewer: B (opus). Scope: plan §1, §2, §6, §7, §9, §10 and the C1–C7 clauses. Deletion-safety internals are out of scope (reviewer A has them); a few cross-scope pointers are listed at the end for A.
Method: grep/sed ranges against the worktree at b3d6230. No git diff, no servers, no make check. Every finding below was checked against the cited code.

Tally: **2 blockers, 12 should-fix, 13 nits.**

---

## Blockers

### B1. `make check` goes red: the bundle cannot handle `from . import pending` / an indented `from .pending import` (§2 server.py, cli.py, bundle.py rows)
1. **Defect.** `scripts/bundle.py:41-52` drops only *top-level* `^(import |from )` lines, and rewrites only `config.` and `tunnel.` attribute access into the single namespace.
   - The plan's server.py change (`from . import pending`, then `pending.start_worker()` / `pending.load_report()`) leaves bare `pending.X` references behind. In `dist/tracker.py`, `run()` raises `NameError: pending` at startup.
   - The plan's cli.py change (`if "--pending" in sys.argv: from .pending import cli_main`) is *indented*, so the bundler keeps it.
   - **Repro:** `make check` runs `tests/test_integration.py::TestBundle`.
     - `test_bundle_is_syntactically_valid_and_self_contained` asserts `"from ." not in src`. Actual: the line is present, so the test is red.
     - `test_bundle_readonly_gate_does_not_break_local_callers` actually runs the bundled `run()`. Actual: `NameError`, so the server never answers and the test is red.
2. **Fix direction.** Use *named, top-level* imports, which the bundler already handles. Do not change bundle.py's regexes, and do not add a `pending\.` rewrite.
3. **The way.**
   - server.py top: `from .pending import start_worker, load_report, item_detail, run_once`. Call the bare names.
   - cli.py top (next to `from .server import run`): `from .pending import cli_main`.
   - Inside pending.py, use `from .store import _load_json, _save_json` and `from .registry import all_sessions`. Never `store.X` or `registry.X`: those are not rewritten either. `config.X` is fine.
   - Put `"pending.py"` in ORDER **after `registry.py`** and before `server.py`.
   - None of the pending names collide with existing top-level defs (checked: `_git`, `clean`, `classify`, `due`, `run_once`, … are all unused).
4. **Test.** The existing `TestBundle` is the test. It is red with plan v1 as written and green with the named imports. Also add `self._run("--pending", "--dry-run")` returncode 0 to TestBundle, with `TRACKER_PENDING_INTERVAL=off` and a temp `HOME`, so the bundled CLI path is exercised.

### B2. C1 broken: `rev-parse --git-common-dir` is relative in a primary checkout, so different repos collapse into one key (§3 Discovery, used by §1/§2)
1. **Defect.** Plan §3: "Each cwd maps to its repo: `git -C <cwd> rev-parse --git-common-dir` … Repos are deduped by common dir."
   - git prints this path **relative to cwd when relative**. At a primary checkout's top level that is `.git`. From a linked worktree it is absolute; checked here, the worktree returns `/Users/…/ai-tracker/.git`.
   - **Repro:** session A has cwd `/x/repo1` and session B has cwd `/y/repo2`, both primary-checkout roots. Both map to key `".git"`, so repo2 is never scanned. Then `list_worktrees(".git")` runs `git -C .git` relative to the *server's* cwd, which is the wrong repo or an error.
   - Expected: two keys, `/x/repo1/.git` and `/y/repo2/.git`.
2. **Fix direction.** Always produce an absolute, realpath'd common dir. The dedupe logic stays the same.
3. **The way.** In `discover_repos`, use `_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")` (git ≥ 2.31; this machine has 2.54), then `os.path.realpath`. Fallback for older git: `os.path.realpath(os.path.join(cwd, out))`. `list_worktrees` should `-C` the common dir's parent for a non-bare repo.
4. **Test.** In `tests/test_pending.py`, build **two** temp repos and give `discover_repos` sessions whose cwd is each repo's top level. Assert two distinct absolute keys. This is red under plan v1: one key, `".git"`.

---

## Should-fix

### S1. C2 "controlled by the config setup" fails for the CLI/launchd path: it never reads config.json (§2 cli.py, §9 D1)
1. **Defect.** `config.py:540-549` seeds the `_PLAIN_ATTR_KEYS` globals from env/default only. config.json is folded in only by `apply_overrides()`, which is called from `server.run()` (`server.py:917`) and from `/api/config`. `cli_main` never calls it.
   - **Repro:** Settings → "Safe delete" (config.json `PENDING_CLEAN: "safe"`), then `make pending`. Actual: `config.PENDING_CLEAN == "dry-run"`. The reverse also holds for `PENDING_INTERVAL`, and for the README launchd snippet.
2. **Fix direction.** The CLI must resolve config exactly like the server. Do not make config.py read files; its no-filesystem invariant stays.
3. **The way.** First line of `pending.cli_main`: `config.apply_overrides(_load_json(config.CONFIG_FILE, {}))`.
4. **Test.** Write a temp `CONFIG_FILE` with `{"PENDING_CLEAN": "safe"}`, reset `config.PENDING_CLEAN = "dry-run"`, call `cli_main(["--json"])` with `run_once` patched. Assert it was called with the effective mode `"safe"`. Red without the line.

### S2. Card shows on every page, because primary checkouts are always items (§2 ext_cr_board.js row vs §6 Card)
1. **Defect.** §2 says "when `pendingReport && pendingReport.items.length`, prepend the tile". §6 says "only when items has any pending/missing … or tmp has any stale". These disagree, and §2's rule is always true: `git worktree list` returns the primary checkout of every repo as an item (verdict `keep`).
   - Also, `report.summary` is used in §6 but missing from §3's top-level schema.
   - Either way the JS is deriving a threshold, which breaks conventions rule 5.
2. **Fix direction.** The server decides whether the card shows and what it says. The JS reads only that.
3. **The way.** `run_once`/`load_report` add top-level `"card": {"show": bool, "title": str, "summary": str, "count": int}`. `pendingTile` renders only `if (p && p.card && p.card.show)`. Add `card` to the §3 schema and drop the `items.length` wording from §2.
4. **Test.** In test_pending: a report whose only item is a clean primary checkout gives `card.show is False`. Add one dirty worktree and it is `True`. A node board test: `update({sessions:[], now, pending:{card:{show:false}}})` renders no `[data-tile-id="pending"]`.

### S3. Pending work in a primary checkout or a locked worktree is hidden, because `keep` is decided before `pending` (§3 classify feeds C1/C3)
1. **Defect.** classify returns `keep` first for "locked, or it is the primary checkout". A primary checkout with 5 uncommitted files is therefore `keep`, never counted, and never on the card.
   - The contract: "list all the pending work lying in the worktrees". The primary checkout is a worktree, and is where the user's in-place WIP usually sits.
   - **Repro:** dirty the primary checkout. Actual: verdict `keep`, card absent. Expected: listed as pending, never deletable.
2. **Fix direction.** Separate *what to show* from *what may be deleted*. Keep all deletion guards exactly as they are.
3. **The way.**
   - `classify(wt)` returns the display verdict (`pending | reclaimable | missing | clean | unknown`) plus a separate `protected: bool` (locked / primary / own tracker).
   - `clean()` acts only on `verdict == "reclaimable" and not protected` (or `missing` for prune).
   - The label carries "(primary)" or "(locked)".
4. **Test.** A dirty primary gives `verdict == "pending", protected is True`, and `run_once("safe")` leaves it byte-for-byte.

### S4. Keyboard `t` opens the wrong session's terminal once the pending tile is prepended (`ext_cr_board.js:3084-3092`)
1. **Defect.** The `t` handler takes the **DOM** index (`currentTileEls()`, line 3051, which counts every `[data-tile-id]` including the new pending tile). It then indexes the **boardTiles** array with it: `var t = tiles[idx]` at :3091.
   - **Repro:** the pending card is present. Focus the first session tile (DOM idx 1) and press `t`. Actual: `terminal:open` fires for the *second* session. Expected: the first.
2. **Fix direction.** Resolve by tile id, not by position. j/k movement over DOM elements stays as is.
3. **The way.** Replace `var t = tiles[idx];` with `var t = tiles.filter(function (x) { return tileId(x) === focusedTileId; })[0];`. The existing `t.kind === 'session'` check already ignores the pending tile.
4. **Test.** Add a node board test (pattern: `tests/test_cr_board_order_and_empty.py`). Feed `update` 2 sessions plus a pending card with `show:true`, focus DOM element 1, dispatch `t`, and assert the emitted id is session[0]. Red under v1.

### S5. `grid-column: span 2` without the narrow-width reset breaks the single-column layout (§2 ext_cr_board.css row)
1. **Defect.** Below 1023px the board is `minmax(0,1fr)`, one column (`ext_cr_board.css:1470-1472`). The existing span-2 tiles are reset to `span 1` there (`:1484-1489`). The plan's new rule has no reset, so on a phone or narrow window an implicit second column appears and the page overflows horizontally.
2. **Fix direction.** Reuse the existing utility. Add no new span rule.
3. **The way.** Give the tile `class: 'cr-tile cr-tile--pending cr-tile--span2'` and drop `grid-column` from the `.cr-tile--pending` rule. Colour: follow the existing pairing convention (`--surface-X` plus `--line-X` per state, both theme blocks, `ext_cr.css:~135/~374`), i.e. `--state-pending`, `--surface-pending`, `--line-pending`. `color-mix` is used nowhere in `web/*.css` today.
4. **Test.** Add `.tracker-next .cr-tile--pending` to `tests/test_page_css.py::test_expected_selectors_survive`, and assert `cr-tile--span2` is in the rendered tile's class.

### S6. Fetching inside `board.update()` breaks the module's contract and its test harnesses (§2 `maybeFetchPending`)
1. **Defect.** The ext_cr_board.js header (:6-7) says: "all data arrives through `CR.board.update(state)`".
   - About ten test files drive `board.update` under node. Some have no `fetch` stub (`test_cr_board_order_and_empty.py`, `test_cr_rail_defects.py`). Node 18+ has a global `fetch`, so `fetch('/api/pending')` rejects with an invalid URL, giving unhandled rejections or noise.
   - Read-only tunnel viewers get a 403 every 60s. That is correct (the route is not in `_RO_GET_ALLOW`), but it is noise.
2. **Fix direction.** Fetch where fetching already lives, the boot poll hook, and pass the result in through `state`. The board stays a pure renderer.
3. **The way.**
   - In `ext_cr_boot.js`'s `SIDE_EXT.push` hook (~:999-1004): if `!ctx.readOnly()` and 60s have passed since the last fetch, `fetch('/api/pending')` → cache `pendingCache` (ignore non-OK). Then call `board.update({sessions, now, pending: pendingCache})`.
   - The board reads `state.pending`.
   - After a successful "Scan now", force the next fetch.
4. **Test.** Existing board tests stay green unchanged. This is the proof: under v1 they would gain a fetch. Add one boot test: with a read-only ctx there is no `/api/pending` fetch.

### S7. The worker loop can die or hot-spin (§3 `_worker_loop`, wired in §2 `run()`)
1. **Defect.** `sleep(min(3600, time to next due))`.
   - **Lock busy:** the CLI holds the lock, so `run_once` returns `{"running": True}` and writes nothing. Time-to-next-due is ≤ 0, so `time.sleep(negative)` raises `ValueError` and the daemon thread dies silently for the life of the server.
   - **Any exception inside `run_once`:** for example an `OSError` writing `pending.json` in a uv-installed read-only `_HERE`. Same death.
   - **Report never written:** if that is "fixed" by clamping to 0, it becomes a busy loop hammering git.
2. **Fix direction.** The loop must survive and pace itself. No new stop/Event machinery is needed; it is a daemon and SIGTERM still exits the process.
3. **The way.** `try: run_once() except Exception as e: _log(...)`. Then `sleep(max(60, min(3600, next_due - clock())))`, with `next_due = (generated_at or clock()) + interval_s`.
4. **Test.** `_worker_loop(sleep=fake, clock=fake)` with `run_once` patched to raise once and then return `{"running": True}`. Assert the loop keeps going (3 iterations) and every fake sleep is ≥ 60. Red under v1.

### S8. "Scan now" can delete, and dry-runs postpone the scheduled clean (§6 Routes, §3 `cli_main --dry-run`, `due()`)
1. **Defect.**
   - `POST /api/pending/run` calls `run_once` with `mode=None`, which means `config.PENDING_CLEAN`. In `safe` mode a button labelled "Scan now" deletes.
   - Separately, `due()` reads `generated_at`, which every run writes, dry-run included. **Repro:** interval `1m`, mode `safe`. The user clicks Scan now (or runs `make pending --dry-run`) every few weeks, and the scheduled safe clean never comes due.
2. **Fix direction.**
   - A user-initiated scan never deletes.
   - Only a run in the configured mode advances the schedule clock.
3. **The way.**
   - The route always calls `run_once("dry-run")`.
   - The report carries `scheduled_at`, written only when `mode == config.PENDING_CLEAN`. `due()` reads `scheduled_at`; `generated_at` stays for display.
4. **Test.** `run_once("dry-run")` after a `safe` run leaves `scheduled_at` unchanged, and `due()` stays False/True accordingly. A route test: POST run in `safe` mode deletes nothing.

### S9. The shared modal's live re-sync can overwrite the pending list or item (§6 List/Item reuse of `openText`)
1. **Defect.** `openText` (app.js:2271) does not reset `curModal`, and does not clear `#msgnav`. `syncModal()` (app.js:2258, called every poll from `render()` at :2131) re-opens whatever `curModal` last registered with `live:true`. Both classic narration and the CR timeline (`ext_cr_detail.js:3605`) register that way.
   - **Repro:** open a timeline entry, close it, then open Pending work. On the next poll the narration entry replaces the list, the Resume button disappears, and the nav shows a stale "3 / 12".
2. **Fix direction.** The pending modal must opt out of nav and live sync. Do not change `openText`.
3. **The way.** In `openPendingList`/`openPendingItem`, before `openText`: `curModal = null; var n = document.getElementById('msgnav'); if (n) n.textContent = '';`. Both scripts are inlined into one `<script>` (page.py), and `curModal` is a top-level `let` in app.js, so it is reachable.
4. **Test.** Add a node test with the page stub: set `curModal = {live:true, open: spy, …}`, call `openPendingList()`, run `syncModal()`, and assert spy not called. Red under v1.

### S10. Resume starts Claude *inside* the worktree it may remove (§6 Resume)
1. **Defect.** `resume.cwd` is the worktree path, and the prompt asks for worktree-cleanup on that same path. If the session decides to remove it, the session's own cwd vanishes. Every later Bash call in that Claude session then fails (cwd gone).
   - The new session also becomes a live session rooted in the worktree, so the next scan holds the worktree as "live".
2. **Fix direction.** Start the session at the repo's primary checkout and name the worktree in the prompt. `missing` items already use the repo root; this makes all worktree items consistent.
3. **The way.** `item_detail` sets `resume.cwd = <primary checkout>` (the first porcelain entry from `list_worktrees`) for `kind == "worktree"`. The prompt says "operate on `<path>` with `git -C`". Scratch items: `cwd = $HOME`.
4. **Test.** `item_detail(id_of_B)["resume"]["cwd"] == repo_root`, and the prompt contains B's path.

### S11. C1 coverage: discovery rides `list_sessions(limit=200)` (§3 Discovery)
1. **Defect.** `registry.all_sessions()` calls Claude's `list()`, which returns the newest 200 rows (`providers/claude.py:849`); the brief measured 238 transcripts. A repo touched only by older sessions is never discovered, so its worktrees are never listed. That contradicts "across all different sessions".
2. **Fix direction.** Keep the shared seam as the primary source. Add the jobs index as a second **repo seed**, not just a link. Do not glob transcripts directly (the shared-seam rule).
3. **The way.** In `discover_repos`, union the cwds from `all_sessions()` with `cwd`, `originCwd` and `worktreePath` from `JOBS_DIR/*/state.json`. Document the remaining gap (old non-job sessions beyond 200) in §10.
4. **Test.** A temp `JOBS_DIR` with one `state.json` whose `cwd` is a temp repo not in the sessions list. Assert the repo is discovered.

### S12. Deletion can be enabled remotely even though "Scan now" is local-only (§2 server.py row, §4)
1. **Defect.** `POST /api/pending/run` is gated by `_local_caller`. `POST /api/config` (`server.py:590-618`) has no such gate, so an authenticated non-read-only tunnel caller can set `PENDING_CLEAN=safe` and `PENDING_INTERVAL=1d`, and the worker deletes unattended. The local gate protects the less dangerous of the two routes.
2. **Fix direction.** Gate *enabling* deletion, not scanning. With S8 applied, the run route never deletes and no longer needs the local gate.
3. **The way.** In the `/api/config` branch, after validation:
   ```python
   if key == "PENDING_CLEAN" and coerced == "safe" and not _local_caller(self)[0]:
       return self._json({"error": "safe delete can only be enabled from this machine"}, 403)
   ```
   - Then drop the `_local_caller` gate on `/api/pending/run`, or keep it if preferred; it is harmless.
   - Smaller alternative: no change, documented as the same trust level as `TERM_ALLOW` (also remotely writable today).
4. **Test.** A route test: non-loopback `client_address` posting `PENDING_CLEAN=safe` gets 403 and config.json is unchanged. Loopback gets 200.

---

## Nits

- **N1** (`_local_caller` shape). It returns `(ok, err)`, a tuple, which is always truthy (`server.py:219-229`). Write `ok, err = _local_caller(self); if not ok: return self._json({"error": err}, 403)`. A naive `if not _local_caller(self)` never refuses. Plan test 7 would catch it; state the shape in the plan anyway.
- **N2** (config.py imports). config.py imports only `os` (:1). `_INTERVAL_RE = re.compile(...)` needs `import re`. The bundle HEADER already has `re`.
- **N3** (prompt as flag, §2 term_vt row). A `prompt` starting with `-` is parsed by `claude` as a flag, e.g. `{"prompt": "--dangerously-skip-permissions"}`. This is not an escalation, since `mode:new` is already an unrestricted shell, but it is argv hygiene.
  - **Way:** add `and not p.lstrip().startswith("-")` to the acceptance test.
  - **Test:** a `-x` prompt leaves argv unchanged.
  - The plan's other claims hold. A positional prompt *does* reach claude on all three `new` paths: `_inject_argv` via `shlex.join` (`term_vt.py:1953`), `_deferred_folder_start` (:3615, same function), and the overflow `spawn(cwd, argv)` exec (:3306). The session latch is transcript-by-cwd (`resolve_spawned`, :1982), so the extra arg doesn't break binding.
- **N4** (`openAt` wiring). `openAt(path, mode, prompt)` must thread `prompt` into `_pickDirectory`'s 429 retry closure (`ext_cr_term.js:640`). ext_cr_board.js loads *before* ext_cr_term.js, so resolve `window.CR.term.openAt` at click time and guard it; never capture it at IIFE time.
- **N5** (C4 detail). When an upstream exists, the detail's "unpushed" log should be `git log --oneline @{u}..HEAD`. `<base>..HEAD` counts pushed-but-unmerged commits, so it disagrees with the label's ahead count. Wrap the git output in fenced code blocks in `md`, since file names can carry `|` or `*`. Optional: a capped `git diff` (≤400 lines) as well as `--stat`, if "show the content" means the patch.
- **N6** (empty copy and filters). renderBoard's empty branch (:2626-2630) prints "Nothing needs you right now." next to a prepended pending card. Render the pending card only when `!activeFilter`, and skip the empty copy when the card is shown.
- **N7** (§7 step 6 verification). `node --check` cannot see load-time throws. The real guards now are `tests/test_page_bundle.py::test_bundle_executes` and `tests/test_page_css.py`. Cite those, and never put `*/` or `</script>` in a web/* comment.
- **N8** (interval timing). "Not in RESTART_REQUIRED because the thread reads it every tick" is true, but a change takes effect within ≤1h because of the sleep cap. Say "within an hour" in the Settings row's sub-text.
- **N9** (`_ENV_NAME`). Adding `PENDING_*` to `_ENV_NAME` is cosmetic, because only `_env_backed` reads it (`config.py:305`). The resolvers must read `os.environ` themselves, as `resolve_snapshot_ttl_min` does (:506).
- **N10** (classic view). Classic view (`tracker.ui` defaults to `'classic'`, `ext_cr_boot.js:217`) gets no card. Add this to §10 known gaps.
- **N11** (D2 wording). The text is muddled. The prompt *does* invoke `cleanup` after worktree-cleanup, so C5 is discharged literally. Make the prompt per-kind: worktree → worktree-cleanup then cleanup; scratch → cleanup only.
- **N12** (multiple tracker instances). The lock and `pending.json` are per checkout (`_HERE`). Every `make serve` from a fresh worktree on a spare port (routine here) starts its own worker and does a full multi-repo scan 60s after boot. TestBundle's bundled `run()` is safe only because it exits within 60s.
  - **Way:** set `TRACKER_PENDING_INTERVAL=off` in TestBundle's env and in any test that calls `run()`. Document that spare-port servers should run with it off.
- **N13** (CLI dispatch order). `cli.py` already imports `.server` at top (:6), so the "CLI does not need the server" rationale is moot; harmless. Put the `--pending` branch after `--help` and before serve.

---

## Overbuilding check (anything the contract did not ask for)

- Little to cut. "Scan now" is **justified**: with a days-or-months interval the card would otherwise stay stale for a week after the user fixes things via Resume. It should be scan-only (S8).
- `PENDING_LOG` and `deleted[]` overlap. Keep the log as the audit trail; keep `deleted[]` for the last run only.
- `--json`, `duration_s`, `errors[]` and `next_due` are cheap; fine.
- The `window.CR.term.openAt` wrapper is needed: it is the only clean way to pass `prompt`.
- The README launchd snippet is optional. If kept, have it call the CLI with a `--if-due` guard (one line in `cli_main`: `if "--if-due" in argv and not due(...): return 0`). Otherwise a launchd StartInterval silently overrides `PENDING_INTERVAL`.
- None of my fixes add a module or a route. S2 adds one report field and S8 one report field. S12's one-line gate is optional (the alternative is to document it).

## Contract clauses — would plan v1 discharge them?

| # | Verdict under v1 | Why / what fixes it |
|---|---|---|
| C1 list pending across sessions | **Not discharged** | B2 (repos collapse), S3 (primary/locked WIP hidden), S11 (200-row cap) |
| C2 interval days/months via config | Partly | Parser and validator are sound and `_v_interval` fits `VALIDATORS`, but the CLI ignores config.json (S1) |
| C3 separate coloured card on main board | Partly | Card always shows (S2), `t` off-by-one (S4), mobile overflow (S5), fetch placement (S6). Classic view gets none (N10) |
| C4 click shows uncommitted / unpushed | Discharged | Minor: S9 (modal overwrite), N5 (unpushed range) |
| C5 Resume → Claude using `cleanup` | Discharged | The prompt includes cleanup. S10 (cwd), N3, N4 |
| C6 smart deletion of stale items | Discharged **only after the user flips to Safe**. The default dry-run lists only | State this in the clause table. Remote enable: S12. Scan-now deletion: S8. Internals: reviewer A |
| C7 deterministic scripts, Claude on demand | Partly | Design is right (CLI + thread + Resume-only Claude), but the bundle breaks (B1) and the thread can die (S7) |

## Cross-scope pointers for reviewer A (deletion internals; not scored here)
- §3 classify, "`realpath` contains this tracker's own `_HERE`", is **inverted**. `_HERE` is `<wt>/aitracker`, so the worktree path never *contains* it. The check must be `_HERE.startswith(os.path.realpath(wt) + os.sep)`. Otherwise a test server running from a clean, freshly cut worktree classifies its own worktree `reclaimable`.
- A freshly cut, unedited worktree (ancestor ∧ ahead=0 ∧ clean) is `reclaimable` the moment its session stops being live.
- The cleanup skill says "Keep the scratchpad DIRECTORY; empty it of scratch only" and "lsof before deleting any log". The plan's `rmtree(SCRATCH_ROOT/<slug>/<sid>/)` does neither.

---

## Clean-plan deltas (exact edits to plan v1 implied by accepted findings)

1. **§2 server.py / cli.py / bundle.py rows (B1).** Use `from .pending import start_worker, load_report, item_detail, run_once` at server.py top-level, and `from .pending import cli_main` at cli.py top-level. pending.py uses `from .store import …` and `from .registry import all_sessions`. ORDER: `pending.py` after `registry.py`, before `server.py`. §8: add a TestBundle `--pending --dry-run` run.
2. **§3 Discovery (B2, S11).** Use `rev-parse --path-format=absolute --git-common-dir` + realpath. Seed repos from jobs `state.json` `cwd/originCwd/worktreePath` as well as `all_sessions()`. §8: add the two-repo dedupe and jobs-seed tests. §10: add the 200-row gap.
3. **§3 cli_main (S1).** It calls `config.apply_overrides(_load_json(config.CONFIG_FILE, {}))` first.
4. **§3 schema and classify (S2, S3).** Add a top-level `card {show,title,summary,count}`. Split `verdict` (display) from `protected` (no-delete). §2/§6: render only on `card.show`.
5. **§3 `_worker_loop` (S7).** `try/except` around `run_once`. Sleep is `max(60, min(3600, next_due - now))`.
6. **§3 `due()` / §6 Routes (S8).** Add `scheduled_at`, written only by configured-mode runs. `POST /api/pending/run` always runs `"dry-run"`.
7. **§6 Resume (S10, N4, N11).** `resume.cwd` = primary checkout for worktree items and `$HOME` for scratch. The prompt uses `git -C <path>` and is per-kind. `openAt` threads `prompt` through the 429 retry and is resolved at click time.
8. **§2 ext_cr_board.js row (S4, S6, N6).** Fetch moves to the ext_cr_boot.js SIDE_EXT hook (60s, skipped when read-only) and arrives as `state.pending`. The `t` key resolves by `focusedTileId`. No card under an active filter; no empty copy beside the card.
9. **§2 CSS rows (S5).** Tile class adds `cr-tile--span2`; no own `grid-column`. Add `--surface-pending`/`--line-pending` beside `--state-pending` in both blocks; no `color-mix`.
10. **§6 List/Item (S9, N5).** Before `openText`: `curModal = null` and clear `#msgnav`. Unpushed log is `@{u}..HEAD` when an upstream exists. Fence the git output.
11. **§2 server.py /api/config (S12).** 403 for non-local `PENDING_CLEAN=safe`, or document it at the TERM_ALLOW trust level.
12. **§2 term_vt row (N3).** Also reject a prompt whose stripped form starts with `-`.
13. **§4 (N2).** Add `import re` to config.py.
14. **§6 Routes (N1).** Write the `ok, err = _local_caller(self)` shape explicitly.
15. **§7 step 6 (N7).** Verify with `tests/test_page_bundle.py` and `tests/test_page_css.py`, adding the new selector. Not `node --check`.
16. **§8 / tests (N12).** Set `TRACKER_PENDING_INTERVAL=off` in any test that calls `run()`.
17. **§10 (N10, N8).** Add: classic view has no card; an interval change applies within an hour. Clause table: C6 is discharged only once Safe is chosen.
