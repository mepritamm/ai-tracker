# Drift 3: adversarial review B (P4–P7, Dropped, D1/D2/D5/D6/D7)

- Reviewer: opus leg B. Code re-checked at **`adeb6fa`**, after the fast-forward from `76bd154` that added the pending-work worker, the scheduler and in-app update. Every line number below is current at `adeb6fa`. Where a number moved, the plan's figure is shown as "(plan: …)".
- Method: `grep -n` plus `sed -n` ranges, and one Python simulation of the CSS-comment case (P6.3). No code was edited, nothing was stashed, no server was started.
- Labels used: CONFIRMS-PLAN, PLAN-WRONG, OVERSTATED, OVERENGINEERED, MISSED-BY-BOTH.

---

## Phase 4: Help and Config honesty

### B1. P4.1: remote callers get basenames. This is correct, but the stated reason is wrong (OVERSTATED). The key list is wrong (PLAN-WRONG).

**What the plan gets right.**
- `_local_caller()` (`server.py:223`) is the right test.
- `/api/config` is on `_RO_GET_ALLOW` (`server.py:300`).
- `_readonly()` is false for a non-local caller when `TUNNEL_READONLY` is off. Gating on `_local_caller` rather than on `ro` therefore also covers a full-access tunnel. Good.
- The new routes in `adeb6fa` use the same boundary: `/api/pending` (`:467-471`) and `/api/update` / `/api/scheduler` (`:476-480`) are "this machine only". So P4.1 matches the newest precedent.

**The leak reason is overstated.** "Full paths would leak the home directory" is already true elsewhere:
- `/api/list` is allow-listed and returns `cwd`, the full absolute path, for every session (`providers/claude.py:952`, `auggie.py:371`).
- `/api/config` itself already returns `OPENROUTER_LAUNCHER` and `OPENROUTER_SLOTS_FILE` values, which are full paths when set (`config.py:216-219` EDITABLE, through `snapshot()` `:645`).

Basenames are still worth doing because they cost nothing, but the PR must not present them as closing a leak.

- **Fix direction:** keep basenames for non-local callers. Re-word the risky-spot note to: "consistent with `/api/update`; `cwd` in `/api/list` and the OpenRouter paths already reach remote viewers — known gap, unchanged."
- **What must NOT change:** the `cwd` field in `/api/list`. The rail tooltip and the tile title need it.

**The key list is wrong.**
- README `:214` names seven files: flags, titles, pins, notes, model_keep, **title_sync** and config.
- The plan's seven swap `title_sync` for `forks`.
- `adeb6fa` adds `config.PENDING_FILE` (`config.py:18`, `pending.json`, gitignored at `.gitignore:14`).
- Repro: the Data files tab lists no `title_sync.json` and no `pending.json`. Both are app-owned and read live.

**Fix (way):**
- In `server.py`, after `:499`, add:
  ```python
  files = {"flags": config.FLAGS_FILE, "titles": config.TITLES_FILE, "pins": config.PINS_FILE,
           "notes": config.NOTES_FILE, "model_keep": config.MODEL_KEEP_FILE,
           "title_sync": config.TITLE_SYNC_FILE, "forks": config.FORKS_FILE,
           "pending": config.PENDING_FILE, "config": config.CONFIG_FILE}
  local = _local_caller(self)[0]
  snap["DATA_FILES"] = {k: (v if local else os.path.basename(v)) for k, v in files.items()}
  ```
  That is nine keys. `os` is already imported (`server.py:1`). Never include `TOKEN_FILE` or `PORT_FILE`.
- Add `forks.json` and `pending.json` to README `:214` in the same commit.

**Client (way):** do not add a new `srv.dataFiles` field (OVERENGINEERED).
- `srv.cfg = cfg` is assigned in two places: `ext_cr_dialogs.js:1781`, and the re-fetch at about `:1404` (the `OPENROUTER_LAUNCHER` re-read).
- A second mirror field would go stale after the re-fetch.
- Instead, at `:1760`, read `var df = (srv.cfg && srv.cfg.DATA_FILES) || {};` and iterate the nine keys.
- With no data yet, show `'—'`.

**Copy is wrong for two files.**
- The shared hint "Read live — edits outside the app are picked up on the next poll" is false for `config.json`: `RESTART_REQUIRED` keys such as PORT, HOST and TERMINAL need a restart.
- It is also false for `pending.json`, which the worker writes and the user does not edit.
- Fix: a per-key hint map. `config` gets "Read on each Config open; Port/Host/Terminal need a restart". `pending` gets "Written by the pending-work scan; read-only".

**Tests:**
- `tests/test_cr_routes.py`: a local GET returns exactly the nine keys, every value is absolute, and no value's basename is `token` or `port`.
- The remote test belongs in **`tests/test_tunnel_readonly.py`**. Its `_RO.get(path, proxied=True)` (`:76`) is the real fixture. The plan named `test_cr_readonly_ui.py` / `test_tunnel.py`, which are wrong.
- Cover both read-only on (`self.ro(True)`) and read-only off. In both cases every value has no `/`.
- Red at HEAD: there is no `DATA_FILES` key.

### B2. P4.2: Help capability rows. CONFIRMS-PLAN, plus MISSED-BY-BOTH rows from `adeb6fa`

**The plan's rows are right.**
- `CAPABILITIES` ends at `[61,…]` (`ext_cr_dialogs.js:566`).
- The test pins 61 (`tests/test_capability_table.py:248`).
- No other test pins 61 (I grepped).
- The table renders only the **count** (`:663`) and the footer sentence (`:783`). Owner strings such as `'board+detail'` are never looked up in `OWNER_LABEL`, so compound owners are safe.

**MISSED-BY-BOTH.** `adeb6fa` shipped three user-facing capabilities that are not in the table:
- the Pending-work card and Scan now (board card at `ext_cr_board.js:2635`, rows at `ext_cr_dialogs.js:1515-1524`);
- Scheduled scan install/uninstall (`schedulerBlock` `:1173`);
- in-app Update and restart (`updateBlock` `:1218`).

**Fix (way):**
- Append three rows:
  - `[74,'Pending-work card + scan now','board+dialogs']`
  - `[75,'Scheduled scan install/uninstall','dialogs']`
  - `[76,'In-app update and restart','dialogs']`
- Pin **76** (or 74 if D6 drops rows 72 and 73). Update the docstring at `:19`.
- Test: the existing length assert. It is red until the rows land.
- Every new `config.EDITABLE` key has a control: `PENDING_INTERVAL` at `:1515` and `PENDING_CLEAN` at `:1520`. No other Config gap was found.

### B3. MISSED-BY-BOTH: Help's privacy claims are now false (MED)

- `ext_cr_dialogs.js:660` says: "Nothing is sent anywhere, and it never writes into a session."
- `:665` shows a "**0** bytes leaving" stat.
- After `adeb6fa`:
  - "Check for updates" runs `git fetch` against the upstream (`update.py:182`), so bytes leave the machine.
  - Safe-delete cleanup removes finished sessions' scratch folders and worktrees (copy at `:1521`).
  - A tunnel has always sent bytes.
- Repro: open Help, then Coverage. It reads "0 bytes leaving" while Config → Server offers "Check for updates".
- **Fix direction:** qualify the claim and keep the stat.
  - What must NOT change: the stat's position and the count derivation.
- **Way:**
  - The lede becomes: "It reads the session logs your tools already write. Nothing leaves this machine unless you press Check for updates (a git fetch of this checkout's upstream) or start a tunnel. It never writes into a session log."
  - Change the stat label to `bytes leaving unasked`.
- **Test:** add to `tests/test_capability_table.py`'s harness, or a source slice of `helpCoverageTab`: the text contains `git fetch` and does not contain `Nothing is sent anywhere`. Red at HEAD.
- Grep confirms that no test pins the old copy.

### B4. P4.3: Live-window slider at 1–15 min. CONFIRMS-PLAN, with one honesty correction (PLAN-WRONG, small)

- The slider is now at `ext_cr_dialogs.js:1502-1506` (plan: 1327-1331).
- The plan clamps the **display value** to 15.
- `sliderCtlCommit` prints `String(value)` (`:1081` area), so a stored `LIVE_WINDOW=3600`, which the validator allows up to 24 h, would print "15 min". That is the same invented-value fault P4.4 removes.
- **Fix (way):** pass the unclamped rounded minutes and let the range input clamp its own thumb. This matches how the SNAPSHOT_TTL slider already behaves with out-of-range values:
  ```js
  return sliderCtlCommit(1, 15, Math.max(1, Math.round((value != null ? value : 300) / 60)),
                         function (m) { onCommit(m * 60); }, ' min');
  ```
  Keep the plan's disclosure copy.
- **Test:** reuse the harness in `tests/test_cr_dialogs_config_exec.py` (its `El.fire('change')` pattern at `:83`). Assert:
  - min is 1 and max is 15;
  - firing `change` at 7 POSTs 420;
  - with `LIVE_WINDOW: {value: 3600}` the label reads `60 min`, not `15 min`.

  All three are red at HEAD.

### B5. P4.4: Server tab invents 8790 and 127.0.0.1. CONFIRMS-PLAN, but the real value is also wrong (MISSED-BY-BOTH)

- The literals are now at `ext_cr_dialogs.js:1590` and `:1592` (plan: 1402-1405). The `'—'` fallback is right.
- **What the plan left "not examined": the reported port is not the bound port.**
  - `cli.py:40` binds `os.environ PORT` and never reads `config.json`.
  - `run()` moves to the next free port when the asked port is busy (`server.py` `run`, "`({port}-{actual-1} were busy)`").
  - The row reports `config.resolve_port(overrides)`, which is config.json first, then env, then 8790.
  - The row's copy claims "this reflects what the server is running with now".
  - Repro: start a second tracker while 8790 is busy. It binds 8791, and Config → Server says 8790.
- **Fix direction:** the server reports the socket it actually bound. It does not echo the resolver.
  - What must NOT change: `config.snapshot`, and the POST validator for PORT and HOST.
- **Way:** in GET `/api/config` after `:499`, add:
  ```python
  bh, bp = self.server.server_address[:2]
  snap["PORT"] = dict(snap["PORT"], value=bp); snap["HOST"] = dict(snap["HOST"], value=bh)
  ```
- **Test:** in `tests/test_cr_routes.py`, `GET /api/config` → `PORT.value == self.port`. The test server binds an ephemeral port, so this is red at HEAD.

### B6. MISSED-BY-BOTH (LOW): a remote caller sees terminal copy on the Update and Scheduler blocks

- `updateBlock()` and `schedulerBlock()` hide only under `crReadOnly()` (`:1219`).
- A **full-access** tunnel caller still gets the block, and `/api/update` returns 403.
- The error text comes from `_local_caller()`: "refused: caller is not on this machine (…); this opens a terminal on the tracker's own Mac" (`_NOT_LOCAL`, `server.py:207`). The block paints that text verbatim, so it talks about a terminal on an Update panel.
- **Fix:** in the three local-only branches (`:470`, `:479`, `:662`), return `{"error": "available only on the tracker's own machine", "local_only": True}`, and leave `_local_caller()` alone.
- **Test:** add to `test_tunnel_readonly.py` with read-only off: proxied `GET /api/update` → 403, and the body's `error` does not contain `terminal`.

---

## Phase 5: board tiles

### B7. P5.1: a flagged tile shows flag text. CONFIRMS-PLAN

- `tileLine` is now at `ext_cr_board.js:2855` (plan: 2836).
- `flag_text` is set for every provider in `registry.py:97`.
- The inset CSS is `ext_cr_board.css:1695`.
- Doc 02:216 says "flag text in a `--surface-raised` inset". The docs win over the round-5 artboard reasoning in the code comment (`:2832-2846`). Update that comment in the same edit, or it will contradict the code.
- The change survives the 5 s list re-render, because the field is on the list shape.
- An awaiting session that also has flags stays awaiting, which is correct.
- **Test:** `tests/test_cr_board_order_and_empty.py` already has the real-DOM `_run_node` harness (`:110`). Add a flagged session with `flag_text:'Pushed note stuck'`, `now_line:'x'`, once with no `headline` and once with one. In both cases, assert that `.cr-tile-line` contains `Pushed note stuck`. Red at HEAD.

### B8. P5.2: the hero side rail. PLAN-WRONG (it does not match the doc) and OVERENGINEERED

- `countRow()` does not exist. `glyph()` is at `:833`, and the sidebar builds `.cr-tile-counts` inline (`:2950`).
- Doc 02:214 asks for **todo ticks** in the side rail. The hero already renders `todoTicks(s)` in the *main* column (`:2932`).
- The plan adds a second, textual "3/5 todos" count, so the todos would show twice and the doc's ticks still would not be in the rail.
- **Fix direction:** **move** the ticks, do not duplicate them. Add only the failing count.
- **Way:**
  - In `sessionTile`, when `t.hero` is true, do not push `ticks` into `body`.
  - Build the sidebar as `[ticks, h('div',{class:'cr-tile-counts'},[glyph('note','tn-emo-n'), n+' notes']), s.fail_cmd ? h('div',{class:'cr-tile-counts'},[glyph('x','tn-emo-f'),'1 failing']) : null, button]`.
  - The `i-x` and `i-check` symbols exist in the sprite.
  - Note that the board shows `failing` only when live, through `sessionState` (`:86`). An awaiting hero with a stale `fail_cmd` would say "1 failing". Gate it on the same predicate: `live && s.fail_cmd`.
  - Fix the stale NOTE at `:2945`.
- **Deferred `files_n`:** agree, for the list-poll cost.
- **Test:** in the board harness, render a hero with `todo_total:3`. Assert the `.cr-todo-ticks` node is inside `.cr-tile-sidebar` and not inside `.cr-tile-main`. Assert a live session with `fail_cmd` shows `1 failing`. Red at HEAD.

### B9. P5.3: the back button's aria-label. CONFIRMS-PLAN

- `:2323`. Doc 02:110 requires the same string for both attributes.
- `'Back to classic dashboard'` appears only in `ext_cr_board.js`, so no test pins it.

---

## Phase 6: gate hardening

### B10. P6.1: fail when node is absent. CONFIRMS-PLAN on this machine, but the proof command is broken (PLAN-WRONG)

- On this machine:
  - `which node` gives `/opt/homebrew/bin/node` v25.2.1.
  - There is no `.github/`, so there is no CI.
  - `make check` runs `python3 scripts/run_tests_parallel.py` (`Makefile:37-38`).
  - The installed hook (`.git/hooks/pre-commit`) loops `python3 -m unittest` and inherits the caller's `PATH`.
  - So a commit from a terminal or from Claude's Bash stays green.
  - A commit from a GUI git client started with launchd's PATH (`/usr/bin:/bin:/usr/sbin:/sbin`) would be blocked. That is acceptable, and the message says why.
- 38 other modules keep their own `skipUnless(_HAS_NODE)`, so the result is one red test and not twenty, as planned.
- **Broken proof:** `PATH=/usr/bin:/bin python -m unittest …` exits 127, because there is no `python` on that PATH (verified). It goes red for the wrong reason.
- **Way:** `PATH=/usr/bin:/bin /usr/bin/python3 -m unittest tests.test_page_bundle`. `/usr/bin/python3` is 3.9.6, it imports `aitracker.page`/`server` fine (verified), and `pyproject` requires 3.8 or later.
- Optional, owner's call: an escape hatch `TRACKER_GATE_NO_NODE=1` that turns the new assert into a skip. Do not add it unless the owner commits from a GUI client.

### B11. P6.2: ExtVT exports in the bundle epilogue. CONFIRMS-PLAN

- `window.ExtVT.mountInto` is at `ext_vt.js:3912` and `ExtVT.term` at `:3936`.
- Both are consumed by `ext_cr_term.js:772` and `ext_cr_dialogs.js:2319`.
- `page.py:19` joins `app.js` and the sorted `ext_*.js` files into one script, and the harness wraps it in try/catch (`tests/test_page_bundle.py:174-181`). So the export check is the real remaining gap, as the plan says.
- **Known gap (no change, document it in the PR):**
  - The harness stubs `window.addEventListener` and `window.setTimeout` (`:135`, `:164`).
  - An error inside a deferred or listener-registered init is still invisible to the gate.

### B12. P6.3: stripping comments does not catch a selector swallowed by a stray `*/`. PLAN-WRONG

There are two cases.

**Case 1: a stray `*/`**, for example `/* … --surface-*/ rest */ .victim {…}`.
- The browser closes the comment early.
- ` rest */` becomes junk that prefixes the next selector, so the **following rule is dropped**.
- The victim's selector text is outside any comment, so it survives both a raw search and the plan's non-greedy `re.sub`.
- I simulated this: the stripped text still contains `.tracker-next .victim`.
- P6.3 cannot see it. `test_comments_are_balanced` (`tests/test_page_css.py:195`) does catch it (its depth goes negative), and so does `test_no_premature_comment_terminators` for the `-*/` form.

**Case 2: an unclosed `/*`**, the plan's own proof edit.
- `test_comments_are_balanced` is **already red** at HEAD for this edit: the depth ends above 0.
- The plan's line "At HEAD the same edit stays green" is false.

**The plan's premise is half right.** The `:291` comment is wrong: a raw search does match text inside a comment. But the module's two counting tests already cover the realistic failures.

The one real hole is this. `test_comments_are_balanced` counts `/*` naively, as if comments nested. Browsers do not nest comments. So two defects can cancel out:
- an unclosed `/*` in file A;
- a stray `*/` later in file B.

The count balances, yet A's tail is swallowed.

- **Fix direction:** model the browser exactly, once. Drop the first/last-selector machinery (OVERENGINEERED).
  - What must NOT change: `test_no_premature_comment_terminators`, which gives a better error message for the common `-*/` typo.
- **Way:** in `test_comments_are_balanced`, replace the depth walk with:
  ```python
  clean = _strip_css_comments_and_strings(css)   # sequential, non-nesting = browser semantics
  self.assertNotIn('*/', clean, "stray */ outside any comment: the rule after it is dropped")
  ```
  Keep the unclosed check: `css.count('/*')` cannot be lower than the number of `*/`, or use the stripper's "unclosed → skip to end" branch to report an error.
  - HEAD has zero leftover `*/` (verified), so this is green today.
  - It does not disturb the new `test_pending_tile_rule_and_tokens_survive` (`:343`).
- **Test proof:**
  - Put `*/` after the first comment of `ext_cr_term.css`. The new assert goes red.
  - The cancelling pair: an unclosed `/*` at the end of `ext_cr_detail.css` plus a stray `*/` at the end of `ext_cr_term.css`. The old depth walk stays green and the new assert goes red.
- Fix the misleading comment at `:291`.

### B13. P6.4: pinning the doc tokens. CONFIRMS-PLAN, with small corrections

- The dark block is at `ext_cr.css:316` (plan: 313).
- There is a second `.tracker-next {` block at `:431`. It holds properties, not tokens, but the parser must merge every `.tracker-next {` block, so a later redefinition is caught.
- Add `RULED = {}`, a map from token name to an owner commit, so a future ruled change is one dict entry and not a fixture edit.
- The fixture copies data from the untrusted bundle. That is acceptable: it is copied verbatim as data and nothing executes it.

### B14. P6.5: pin the exported pure functions. OVERSTATED for `stateOf`, CONFIRMS-PLAN for `firstEventTime`

- `stateOf` (`ext_cr_detail.js:971`) returns `{word, cls}`. Its classes are `awaiting`, `flagged`, `failed`, `working`, `done` and `idle`.
- The plan's case list leaves out **`working`** (`detailIsWorking`).
- `failed` and `awaiting` are already pinned by `tests/test_cr_logic.py:1060` (board/detail agreement) and `tests/test_working_glow_detail.py`.
- **Way:** add only the missing `flagged`, `done` and `idle` cases, asserted on `.cls`. Use `NOW - LIVE_WINDOW - 1` for idle.
- For `firstEventTime` (`:482`), no test exists, so the plan stands.
  - The narrative and commands arrays are newest-first, so the fixture must put the oldest entry *last*.
  - Include a `decisions` entry that is the minimum.
- **Proof:** stub `return null`, and the test goes red.

### B15. P6.6: enumerating the write routes. PLAN-WRONG: the regex misses call shapes and new routes

- These call shapes all hide the URL from a `fetch('…', { method: 'POST'` regex:
  - `function post(url, body){ return fetch(url, {method:"POST"…}) }` (`ext_cr_term.js:54`);
  - `crCall(url, 'POST', {})` (`ext_cr_dialogs.js:1144`, `:1197`, `:1204`, `:1271`);
  - `post('/api/update/fetch')` → `crCall(url,'POST')` (`:1241`, `:1269`);
  - multi-line `fetch('/api/x', {\n method: 'POST'` (`ext_cr_boot.js:597` and others).
- The allow-list leaves out `/api/pending/run`, `/api/scheduler`, `/api/update/fetch`, `/api/update/apply` and `/api/term/kill`.
- **Fix direction:** pin the CR modules' whole `/api` surface by **string literal**, not by call shape. Any new route has to appear as a literal: there are no concatenated route stems (verified), only `?q=` query tails.
- **Way:** in `tests/test_cr_readonly_ui.py`:
  ```python
  lits = set(re.findall(r"""['"](/api/[a-z_/-]+)""", js_without_line_comments))
  ```
  Run it across `ext_cr_*.js` and assert equality with a pinned set. At `adeb6fa` that set is: config, flags, flags/delete, flags/resolve, model-keep, notes, notes/delete, pending/run, pin, scheduler, title, tunnel, tunnel/ctl, tunnel/reveal, update, update/apply, update/fetch, term/{close,cwds,inject,kill,list,open,pty,run,stream,attached}, search, session, narration, diff, output, agent, shell. The implementer finalises it from the grep.
  - Mark the write subset in a comment.
  - Amend non-negotiable 1 in the PR to name update/apply (it rewrites the checkout) and pending/run with `safe` (it deletes worktrees).
- **Proof:** add the literal `'/api/dummy'`, and the test goes red.

---

## Phase 7: polish

### B16. 7.1: rail search focus ring. CONFIRMS-PLAN, and it needs a test

- `.tracker-next .cr-rail-search input { outline:none }` (`ext_cr_board.css:745`) has specificity 0,2,1.
- That beats the global `.tracker-next :focus-visible` rule (`ext_cr.css:456`) at 0,2,0, so there is no ring today. Confirmed.
- `:focus-within` on the wrapper also covers the Sessions search, which shares the class (`ext_cr_board.js:914`).
- Add a CSS-regex test, because a browser check alone does not stay pinned.

### B17. 7.2: phone spine labels. CONFIRMS-PLAN

- The rule is at `ext_cr_detail.css:2112-2114` in the 480px block. The 600px block is at `:1885`.
- Both selectors have equal specificity, and the media rule comes later, so it wins.

### B18. 7.3: the status-bar separator orphans. PLAN-WRONG (small)

- `.cr-term-ctxcum` is emitted even when `st.ctx` is absent (`ext_cr_term.js:1172-1174`).
- A bare `::before` would then render "/ cumulative N" with nothing before the slash.
- **Way:** `.cr .cr-term-ctxused ~ .cr-term-ctxcum::before { content: "/ "; }`.

### B19. 7.4: metaline cwd forks a helper. PLAN-WRONG

- There is no `home` field on the detail meta, so the plan's code reduces to `slice(-2)`.
- That is `shortDir()` (`ext_cr_board.js:561`), which is module-level and not exported. Copying it into the detail module forks it, against conventions rule 4.
- It would also duplicate `proj` (the same tail) in `metaBits` (`ext_cr_detail.js:2404`).
- **Way:**
  - Expose the helper with `window.CR.shortDir = shortDir` next to `:3300`.
  - In `metaBits`, replace `proj` with `(meta.cwd && CR.shortDir ? CR.shortDir(meta.cwd) : proj)`.
  - Auggie's empty `cwd` (`auggie.py:497`) falls back to `proj`.
- **Test:** a node assertion that a `meta.cwd` of `/a/b/c/d` produces a metaline containing `…/c/d`.

### B20. 7.5 and 7.6. CONFIRMS-PLAN (records only)

---

## Owner decisions

### B21. D1: idle backfill. CONFIRMS-PLAN (recommend (b)). Option (a) as written breaks j/k navigation (PLAN-WRONG)

- `boardTiles()` is also called by `computeTriage` and `stepSession` (comment at `ext_cr_board.js:377-388`).
- A `state !== 'idle'` filter inside it would make idle sessions unreachable by j/k.
- The plan's footer "total 7" would also advertise tiles that never show.
- If (a) is chosen: filter in `renderBoard` only (`:2618`), and set `total` to the non-idle count.
- The backfill comment is now at `:345` (plan: 344).

### B22. D2: "Show all". Option (a)'s test contradicts its code (PLAN-WRONG). Its rationale is stale

- The plan keeps the `showAll` parameter in `boardTiles` (`:389`, `:430`) and passes false at the call sites (`:2618`, `:3117`).
- Then "`boardTiles(…, true)` still caps" stays red forever.
- **Way under (a):**
  - Delete the parameter: `:430` becomes `matched.slice(0, boardTileCap())`.
  - Delete the footer button (`:3040-3046`), the `|| showAll` condition and the `:3008` read, the `:2527-2529` reset, and the `:3220` handler.
  - Leave the `uiState` key unread.
- **Rationale:** "the one place the board can exceed the cap" is false since `adeb6fa`. The owner-commissioned Pending-work card is prepended outside the cap (`:2633-2635`). Re-word it as "the one *user* toggle that exceeds the cap".

### B23. D5: panels open by default. CONFIRMS-PLAN (recommend (a)). Option (b)'s test needs a fixture

- `panelDefaultCollapsed` falls back to `defaultFolded()` (`ext_cr_detail.js:296`). That function returns false when `cr.cardsFolded` is `false`.
- So the (b) test must stub `localStorage` with the key absent.

### B24. D6: unruled extras. CONFIRMS-PLAN, with stale lines and one addition

- The cited lines have moved:
  - the dialogs agent map is about +189 lines from the plan's figure;
  - the `?ui=` override is now `ext_cr_boot.js:1222-1226`;
  - PINNED is at `ext_cr_board.js:325`.
- The Pending-work card, the scheduler and update are **ruled** by `reports/pending-work-worker.md` (owner contract, C1 and later clauses). The D6 paragraph should cite that file, not re-rule them.

### B25. D7: classic file edits. CONFIRMS-PLAN

- No code. `tests/test_state_colors.py` and `tests/test_classic_reduced_motion.py` pin the shared palette.
- `adeb6fa` also edits classic `app.js` (its pending card at `:2333-2417`). Add it to the D7 list of overrides.

---

## Dropped section

### B26. Dropped. CONFIRMS-PLAN on all eight entries

- 03 N1: confirmed by the `5dea10f` message, lines 52-53.
- 01 N3: confirmed by the Auto button at `ext_cr_board.js:2453`. The plan's cite `:2472-2480` is wrong.
- 00 decision 9: the comment at `ext_cr_detail.js:306-307` matches the code.
- 00 gap 2: the try/catch is at `test_page_bundle.py:174-181`.
- 00 gap 3: correctly dropped. Its replacement, P6.3, is itself wrong (see B12).
- 02 E2: "owner asked to keep" is in the `5dea10f` message, line 65.
- 04 N18: the `?` key handler is at `ext_cr_board.js:3088` (plan: 3069).
- 05 N3: belongs to P1.1 (review A's scope). Not re-derived here.

---

## Clean plan for this scope (landing order)

1. **P4, Help and Config** (one commit):
   - `DATA_FILES` with nine keys (title_sync and pending added), basename for non-local callers, read on the client from `srv.cfg`, per-key hint copy, README `:214` updated (B1).
   - Capability rows 62–76, test pinned at 76 (B2).
   - Help lede and stat qualified for git fetch, tunnel and cleanup (B3).
   - Live-window slider at 1–15 with an unclamped label (B4).
   - Port and Host from `self.server.server_address`, `'—'` fallback (B5).
   - Local-only error copy for update, scheduler and pending (B6).
   - Tests: `test_cr_routes`, `test_tunnel_readonly`, `test_capability_table`, `test_cr_dialogs_config_exec`.
2. **P5, Board tiles:**
   - Flag text in `tileLine` and the comment updated (B7).
   - Hero side rail: move the ticks, add `1 failing` gated on `live && fail_cmd`, fix the stale NOTE (B8).
   - Back-button aria-label (B9).
3. **P6, Gate:**
   - Node-required assert, with the proof run through `/usr/bin/python3` (B10).
   - ExtVT export epilogue (B11).
   - Browser-semantics stray-`*/` assert replacing the depth walk. No first/last-selector machinery (B12).
   - Doc-token fixture: merge the blocks, add the `RULED` map (B13).
   - `firstEventTime` plus the missing `stateOf` classes (B14).
   - `/api` literal-surface pin, with the PR amending non-negotiable 1 (B15).
4. **P7, Polish:**
   - 7.1 with a CSS test (B16); 7.2 (B17).
   - 7.3 with the sibling selector (B18).
   - 7.4 through an exported `shortDir`, replacing `proj` (B19).
   - 7.5 and 7.6 (B20).
5. **Decisions, once answered:**
   - D1(b) (B21).
   - D2(a), with the parameter removed and the rationale re-worded (B22).
   - D5(a) (B23).
   - D6(a), citing `pending-work-worker.md` (B24).
   - D7(a), with the `adeb6fa` app.js edits added (B25).
