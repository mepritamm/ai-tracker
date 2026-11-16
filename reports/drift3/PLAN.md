# Drift round 3: technical implementation plan

- Code SHA: `76bd154`, worktree `.claude/worktrees/control-room-drift`, branch `worktree-control-room-drift`.
- Inputs: `reports/drift3/00`–`05`. I re-checked every planned finding with `grep -n` and `sed -n` at this SHA. Line numbers below are current.
- Precedence: **the docs win** (`7b87cce`). Later owner rulings take priority over the docs: SVG icons instead of emoji (`3455c4d`), green Working (`89c2267`), board cap 3–12 (`7b87cce`), heartbeat as the default progress view (`reports/heartbeat-panel.md:16,24`), session name as the detail h1 and keeping the Sessions pill (`5dea10f` message), and the Now card above the spine (`89c2267`).
- Hard constraints, from `CLAUDE.md` and `.claude/rules/conventions.md`:
  - stdlib only, no new dependencies;
  - edit `aitracker/web/*` and never `dist/`;
  - the server owns policy;
  - new fields go on the shared shape for both providers;
  - one assertion per non-trivial change;
  - `make check` stays green;
  - restart the server to see UI changes.
- Paths are under `aitracker/web/` unless they say otherwise.

---

## 1. Owner decisions needed (before any code)

No phase below depends on these answers. Phases 1–7 can land while the decisions are pending. Each decision becomes one small extra commit once it is answered.

### D1. Idle sessions on the board (02 N1, HIGH)
- **Question:** doc 02:188-197 says "Idle sessions never get a tile". The code backfills the cap with the most recent idle sessions (`ext_cr_board.js:343-358`, comment "as amended by the owner"). The only ruling is that code comment. `reports/board-tiles-rail-parity.md:42-46` parked it as an open question.
- **Options:**
  - (a) Doc wins: exclude idle when no filter is active, and show an empty-state card when nothing qualifies.
  - (b) Keep the backfill and record it as a ruling.
- **Recommendation: (b).** The backfill fixed a real blank board (957 idle sessions, `317db79`), and a board that is empty most of the day reads as broken.
- **Code under (a):**
  - In `boardTiles()` at `:405`, filter `state !== 'idle'` when `!filterKey`.
  - In the board render, replace the empty board with `emptyState({title:'Nothing needs you', body: N + ' sessions are idle — see the rail'})`.
  - Test in `tests/test_cr_board_order_and_empty.py`: 5 idle + 2 working sessions produce 2 tiles and `total` 7.
  - Update the existing backfill tests in the same file. They go red by design.
- **Code under (b):**
  - Add one paragraph to `reports/control-room-refinements.md`.
  - Change the code comment at `:344` to cite it.

### D2. "Show all N" lifts the cap (02 N4, MED)
- **Question:** doc 02:193-196 says "No 'show more' on the board". The cap footer toggles `showAll` (`ext_cr_board.js:3021-3027`, used at `:430`). It was added in `317db79` with no ruling.
- **Options:**
  - (a) Remove it, so the rail is the overflow.
  - (b) Keep it and record it.
- **Recommendation: (a)**, unless you use it. It is the one place where the board can exceed the cap you set, which undoes README decision 2.
- **Code under (a):**
  - Delete `:3021-3027`.
  - Pass `showAll` as false at the call sites (`:389`, `:2618`, `:3096`). Leave the `uiState` key unread rather than deleting it, so cross-view state stays compatible.
  - Test: the cap-footer source has no `'Show all '`, and `boardTiles(…, true)` still caps.
- **Code under (b):** record the ruling only.

### D3. Working colour is split (01 N4, MED)
- **Question:** the rail dot, orb pip and detail state pill are green (`--state-working`, `ext_cr.css:160,383`). Three things are still wheat:
  - the board tile's working dot and its pulse (`ext_cr_board.css:1624-1635`);
  - the tile state word (`:1618`, `--text-thinking`);
  - the agent-row dot (`ext_cr_detail.css:1307`, with the `crd-pulse` halo at `:727-731`).

  So one session shows two working colours.
- **Options:**
  - (a) Green everywhere for the session-state Working.
  - (b) Wheat everywhere, which reverts `89c2267`.
  - (c) Keep the split.
- **Recommendation: (a).** You asked for green, and the split looks like a bug. The progress-spine running segment and the agent gradient stay wheat: doc 03 gives them the agent colour, not the session state.
- **Code under (a):**
  - Point the working dot and the working state word at `var(--state-working)`.
  - Replace the hard-coded halo `rgba(217,184,85,…)` in both keyframes with a new `--pulse-working-rgb` token. Light value `28,145,99`, dark value `41,211,152`, both in `ext_cr.css`.
  - Test: extend `tests/test_state_color_parity_app.py` to assert that `.cr-tile-dot` in the working state and `.crd-state-dot.is-working` read `--state-working`. It is red before the change.

### D4. Timeline order (03 F5, MED)
- **Question:** doc 03 describes a chat with the oldest entry at the top and the newest at the bottom, stuck to the bottom. The code is newest-first (`mergeTimeline` `ext_cr_detail.js:768`, `timelineStuckLatest` with `scrollTop < 40`). There is no ruling in `reports/`.
- **Options:**
  - (a) Flip to the doc order.
  - (b) Keep newest-first and record it.
- **Recommendation: (b).** The Now card above the spine (`89c2267`, owner placement) already shows the latest state at the top. Flipping would mean the newest entry sits far from it, and the change is the largest in this plan: sort, scroll sentinel, paging direction, and the prev/next/latest handlers.
- **Code under (a):**
  - Sort ascending in `mergeTimeline`.
  - The sentinel becomes `scrollHeight - scrollTop - clientHeight < 40`.
  - Older pages are prepended with scroll compensation.
  - Swap the `convo-prev/next/latest` cases.
  - Test: `tests/test_cr_logic.py` asserts that `mergeTimeline` output is ascending.

### D5. Heartbeat default, and three panels open by default (00 decisions 7 and 9)
- **Question:** `OPEN_BY_DEFAULT = { timeline:1, heartbeat:1, spine:1 }` (`ext_cr_detail.js:325`) and the heartbeat default (`:309-315`) both come from the approved heartbeat contract (`reports/heartbeat-panel.md:24,153`). README decision 7 says only the timeline starts open.
- **Options:**
  - (a) Keep as is.
  - (b) Only the timeline starts open.
- **Recommendation: (a).** A progress panel that starts folded hides the one thing the panel exists to show.
- **Code under (b):** change the map at `:325` to `{ timeline: 1 }`. Test: `panelDefaultCollapsed` is true for every key except `timeline`.
- Audit 00 called the comment at `:308` stale. It is not: the code and the comment agree. See Dropped.

### D6. Unruled extras: keep and record, or remove
Each of these exists with no doc source and no ruling report:
- PINNED as a fifth triage cell (`ext_cr_board.js:2506-2507`). Doc 02:153 says "four cells". `5dea10f` built it as part of a "parity" pass but recorded no ruling.
- The agent map: header button, rail and tile buttons, and the dialog (`ext_cr_detail.js:1403`; `ext_cr_dialogs.js:2489-2715`; `2c35a29`).
- The model marker chip (`031c50c`).
- The `?ui=next|classic` override (`ext_cr_boot.js:1223-1230`).
- The Queue-a-note button, the timeline kind-filter chips and pop-out, the always-visible pin toggle, and the Evidence-panel model/effort switchers.
- Hiding Open/Resume in the terminal bar while a Claude CLI is attached (`ext_cr_term.js:1152`; 05 N13).
- The Sessions pill is already ruled ("owner asked to keep them", `5dea10f`). It only needs writing down.

**Options:** (a) keep all and record one ruling paragraph; (b) remove specific items.

**Recommendation: (a)** for all of them. Each is a functional superset, and the classic UI has the same capabilities.

**Code under (a):**
- One paragraph in `reports/control-room-refinements.md`.
- Phase 4 then adds the agent map and model chip to the Help table.

**Code under (b):** one small commit per item. Each needs its own deletion and test edits; none is planned here.

### D7. The classic `app.css` and `app.js` were changed (00 §3)
- **Question:** README says "Do not alter existing selectors". `89c2267`, `3455c4d`, `99a5954`, `6f21687`, `e32831f`, `317db79` and `a5bf172` changed them (one shared palette, icons instead of emoji). Each change was owner-directed, but none was recorded as an override of the README clause.
- **Options:** (a) record the override; (b) revert.
- **Recommendation: (a).** Reverting would split the palette again, and `tests/test_state_colors.py` and `tests/test_classic_reduced_motion.py` already pin the shared behaviour.
- **Code:** none. Add a note in `reports/control-room-redesign.md` (Phase 7, item 7.6).

### D8. Detail-view orb rail contents and orb size (03 F3, N2, N3, MED)
- **Question:** doc 03:28-50 asks the 56px detail rail for six things, none of which it has today:
  - a brand mark;
  - a pin micro-label;
  - an agents orb;
  - a dashed "+" orb;
  - a vertical "+N SCROLL" footer;
  - 34px orbs.

  Doc 02:123 says orbs are 28px, so the two docs conflict on size.
- **Options:**
  - (a) Build the doc 03 rail on the detail variant only, with 34px orbs there and 28px on the board.
  - (b) Defer.
- **Recommendation: (b) for now.** This is the largest UI build in the audits and has no correctness impact. Every function it adds is already one click away in the top bar.
- **Code under (a):**
  - `renderCollapsedOrbs` (`ext_cr_board.js:1854`) appends the agents orb and the "+" orb when `els.rail.classList.contains('cr-rail--detail')`.
  - Un-hide `.cr-rail-brand` under `.cr-rail--detail`.
  - Give the footer `writing-mode: vertical-rl`.
  - Use 34px orbs and a 9px top-right pip on the detail variant only.
  - Check it in a browser at 1280 and 1440.

### Decisions you may want to overrule in the phased work
- **P3.1** restores the doc's two action rows in the detail header, and **P3.2** moves the fork banner out of the Evidence column. Both reverse layouts built in the "HTML wins" era (the code comments say "FIX (design-audit drift 2/3): 5b collapses…"). `7b87cce` reversed that precedence, so I treat them as drift and not as rulings. If you prefer the one-row header, say so and P3.1 is dropped.
- **P6.1** makes the gate fail when `node` is missing. Any machine without node goes red.

---

## 2. Phased work (one commit per phase)

Test conventions used throughout:
- **Source-slice tests** follow `tests/test_cr_manage_terminals_parity.py`: brace-extract a function and assert on its text.
- **Node-exec tests** follow `tests/test_cr_logic.py` and the picker harness at `tests/test_cr_manage_terminals_parity.py:390-440`.
- **Proving red:** every test must fail once its fix is reverted with a scoped Edit, never `git stash`.

### Phase 1: terminal correctness bugs (highest user impact)

**P1.1 Esc in a dialog over the terminal also detaches the terminal (05 N3, MED).**
- **Where:** the overlay listener `ext_cr_term.js:242-244`, inside `_build()` (`:116`).
- **Mechanism:**
  - The dialogs module mounts **before** the terminal module (`ext_cr_boot.js:955-956`), so its `onDocKeydown` (`ext_cr_dialogs.js:354-361`) runs first.
  - That handler pops the dialog and calls `e.preventDefault()`.
  - The terminal listener then sees no dialog and closes the terminal too.
  - The audit's fix (check `topName()`) therefore **does not work**: by the time the terminal listener runs, the stack is already empty.
- **Change:**
  ```js
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || ev.defaultPrevented || !overlay.classList.contains("is-open")) return;
    var d = window.CR && window.CR.dialogs;
    if (d && typeof d.topName === "function" && d.topName()) return;   // order-independent second guard
    close();
  });
  ```
- **Server:** none.
- **Test:** new `tests/test_cr_term_drift3.py::test_overlay_escape_yields_to_dialogs`. It slices the `_build` body and asserts the Escape listener references both `defaultPrevented` and `topName`. It is red at HEAD.
- **Browser check:** open a terminal, open Manage, press Esc. Manage closes and the terminal stays. Press Esc again and the terminal closes.
- **Risky spot:** the board's keydown handler (`ext_cr_board.js:3074`) does not call `preventDefault` on Escape, so nothing else suppresses the close by accident. I checked this with a grep for `Escape` across `ext_cr_*.js`.

**P1.2 After switching to xterm, the pane stays under an 82% dark scrim (05 N2, MED).**
- **Where:** CSS `ext_cr_term.css:294-307` (`.cr-term-pane-blank`), and `_setRenderer` at `ext_cr_term.js:928-945`.
- **Change:**
  - CSS: the scrim becomes a top-edge strip, `inset: 0 0 auto 0`, with the full-pane `rgba(18,16,14,.82)` background removed. Use `background: #1F1B16` (a frozen dark literal, like the rest of this file) and keep `pointer-events: none`.
  - JS, in `_setRenderer`: after setting `el.blank.hidden = next !== "xterm"`, add `clearTimeout(st.blankTimer); if (next === "xterm") st.blankTimer = setTimeout(function(){ el.blank.hidden = true; }, 8000);`.
  - JS, in `_build`: add `pane.addEventListener("keydown", hideBlank, true)` and the same for `pointerdown`.
  - `_resetPaneChrome` (`:427`) clears `st.blankTimer`.
  - Do not fake a repaint.
- **Test:** `test_blank_notice_is_not_a_full_pane_scrim` asserts the `.cr-term-pane-blank` block has neither `inset: 0;` nor `.82`. `test_blank_notice_clears_itself` asserts `_setRenderer` contains `setTimeout` and `_build` registers a capture listener that sets `blank.hidden = true`.
- **Browser check:** switch to xterm, type a key, and the strip goes.
- **Risky spot:** xterm stops some key events from propagating. The capture-phase listener sees them first, and the timeout is the backstop.

**P1.3 A failed spawn closes the picker and loses the typed path (05 N7, MED). Enter does nothing (05 N6, LOW).**
- **Where:** `_pickDirectory` `ext_cr_term.js:625-663`, and `renderDirectoryPicker` in `ext_cr_dialogs.js`: `submit` at `:2204-2211`, the input and Start button at `:2236-2241`, `release` at `:2252-2256`.
- **Change, `_pickDirectory`:**
  - Every non-429 failure throws `new Error(msg)` and does not toast. That covers the server message, 404, 403, other statuses, and network failures, where `.catch(function(e){ throw new Error("Failed to reach the server: " + e); })` replaces the toast.
  - The empty-path branch rejects with `new Error("Choose or type a directory first.")` and drops its toast.
  - The 429 branch is unchanged: it opens the cap dialog and resolves, so the picker closes because the cap dialog takes over.
- **Change, picker:**
  - `release(err)` renders the message into a `p.cr-help-note.cr-picker-error[role=alert]`, held as `errEl` outside `paint()` and re-appended on repaint, the same pattern as `busy`.
  - The input keeps its value: `release` does not repaint, so this already holds. Assert it.
  - Add `input.addEventListener('keydown', function(e){ if (e.key === 'Enter') { e.preventDefault(); go.click(); } })`.
- **Test:** extend the node harness in `tests/test_cr_manage_terminals_parity.py`, around `:420-440`:
  - an `onPick` that rejects with `Error('boom')` leaves the dialog open (no `close()` spy call) and shows `boom` in `.cr-picker-error`;
  - an Enter keydown with a value calls `onPick(value)`.
  - Add a source assertion that `_pickDirectory` has no `showToast(` followed by `return;` in the failure branch.
  - All three are red at HEAD.
- **Risky spot:** `_openCapDialog`'s retry already catches rejections (`:640`). Check that no other caller relied on `_pickDirectory` resolving on failure. A grep shows only the three `onPick` sites (`:595,611,621`).

**P1.4 The terminal never takes focus (05 R1 2.4, LOW, but keyboard users cannot type until they click).**
- **Where:** `onForked` at `ext_cr_term.js:516-529`, and `_setRenderer` at `:933`.
- **Change:** add `if (typeof handle.focus === "function") handle.focus();` after `_applyDarkTheme(handle)` in `onForked`, and the same for `st.engineHandle` after `setRenderer` in `_setRenderer`. `focus` is part of the `mountInto` handle (`ext_vt.js:3774`).
- **Test:** `test_focus_after_attach_and_switch` slices both bodies and asserts `.focus()`.
- **Browser check:** open a terminal and type without clicking.

Phase 1 diff: about 70 lines of JS and CSS, plus about 90 lines of tests.

### Phase 2: terminal chrome honesty

**P2.1 The engine's own toolbar duplicates the CR renderer and theme controls and gets out of sync with them (05 N1, MED).**
- **Where:** new CSS in `ext_cr_term.css`. The classic toolbar is built inside the pane (`ext_vt.js:791,1770`). Its renderer button calls the mount-internal `setRenderer` (`:3703`), and its theme button calls the classic `toggleTheme()` (`:541`).
- **Change:** `.cr .cr-term-pane .vtrendererbtn, .cr .cr-term-pane .vtthemebtn { display: none; }`.
  - A− / A+ and the mouse toggle stay. They have no CR equivalent, and doc 05 keeps zoom and mouse reporting.
  - Do not edit `ext_vt.js`.
- **Test:** a CSS assertion that the rule exists in `ext_cr_term.css`.
- **Browser check:** A−/A+ are visible, and there is no second renderer button.

**P2.2 The status bar disappears on a plain shell; there is no lasting connection state (05 N11, N5, MED).**
- **Where:**
  - `_syncStatusBar` `ext_cr_term.js:1177-1178`;
  - the status-bar markup `:213-224`;
  - the `onStatus` attached branch `:493`;
  - `_resetPaneChrome` `:427`.
- **Change:**
  - `el.status.hidden = !st.tty;` and remove `hasAnything`.
  - Add `<span class="cr-term-conn cr-mono" data-el="conn" hidden></span>` at the start of `.cr-term-status-right`.
  - In `onStatus`: `if (st.tty) { el.conn.textContent = text; el.conn.hidden = false; showToast(text); return; }`.
  - `_resetPaneChrome` hides it.
- **Test:** `test_status_bar_shown_whenever_attached` asserts that `hasAnything` is gone and that the attached branch writes `el.conn`.

**P2.3 "See lineage" appears for every notice, and a streamed notice is wiped (05 N4, MED, the cheap part only).**
- **Where:** `_syncNotice` `:1182-1185`, the notice markup `:191-198`, `onForked` `:523`.
- **Change:**
  - Add `lineageBtn` to `el` (`:265`).
  - In `_syncNotice`: `el.lineageBtn.hidden = !st.forked;`.
  - In `onForked`: `st.notice = handle.notice || st.notice;`.
  - Do not infer lineage on the client.
- **Test:** source assertions that `_syncNotice` reads `st.forked` and that the literal `st.notice = handle.notice || null` is absent.
- **Deferred, LOW:** stacking up to three notices like classic (array state and a renderer, about 40 lines) and the classic "fork" chip.

**P2.4 The renderer chosen before open is dropped (05 N10, LOW).**
- **Where:** `_setRenderer` `:928-931`, the mount call `:487`.
- **Change:**
  - With no `st.engineHandle`, store `st.rendererUser = next`.
  - Mount with `_attachEngine(el.pane, {...}, st.rendererUser ? { renderer: st.rendererUser } : {})`. `mountInto` honours `opts.renderer` (`ext_vt.js:3664`).
  - `_resetPaneChrome` keeps `rendererUser`, since it is the user's choice.
- **Test:** the mount-opts slice references `rendererUser`.

**P2.5 Picker rows hide the path; Manage rows have no accessible names (05 N8, N9, LOW).**
- **Where:** picker rows `ext_cr_dialogs.js:2219-2226`; Manage rows `:2052-2073`.
- **Change:**
  - Each picker row gets children `[label, h('span',{class:'cr-mono cr-picker-path', text: path})]` when `label !== path`.
  - Manage row title gets `title: t.tty + ' · ' + (t.cmd || 'shell') + ' · ' + (t.cwd || '')`.
  - `peekBtn` gets `'aria-label': 'Peek ' + titleText` and `killBtn` gets `'aria-label': 'Kill ' + titleText`.
- **Test:** the node picker harness asserts the row's `textContent` contains the path. A source slice asserts `aria-label` in the Manage row builder.

Phase 2 diff: about 45 lines of JS and CSS, plus about 60 lines of tests.

### Phase 3: detail header and fork banner

**P3.1 Actions in two rows; "Resume here" (03 F1, F8; 1.5, 1d, N15, HIGH; 1.6, LOW).**
- **Where:** skeleton `ext_cr_detail.js:1377-1385`; CSS `ext_cr_detail.css:348-354`, `:1799`, `:1843-1860`.
- **Change:** keep `.crd-row1-actions` as the wrapper, so every existing descendant selector and `qsa(".crd-row1-actions .crd-iconbtn .crd-ico")` at `:2510` keeps matching. Add two inner rows:
  ```html
  <span class="crd-row1-actions">
    <span class="crd-actions-row crd-actions-a">[toggle-search][toggle-flag]</span>
    <span class="crd-actions-row crd-actions-b">[open-terminal][resume "Resume here"][toggle-note][external]</span>
  </span>
  ```
  - CSS: `.crd-row1-actions { flex-direction: column; align-items: flex-end; gap: 8px; }` and `.crd-actions-row { display:flex; gap:7px; flex-wrap:wrap; justify-content:flex-end; }`.
  - Remove `.cr .crd-row1-actions .crd-btn-label` from the `max-width: 900px` selector list (`:1848`), so Search/Flag keep their words above phone width. The Rename/Pin degrade (`.crd-id-row2 .crd-btn-label`) stays.
  - Do not rename any `data-act`.
- **Test:** new `tests/test_cr_detail_drift3.py`:
  - `toggle-search` and `toggle-flag` sit inside a `crd-actions-a` span that does not contain `open-terminal`;
  - the resume button text is `Resume here`;
  - the 900px block no longer hides `.crd-row1-actions .crd-btn-label`.
  - Re-run `tests/test_cr_detail_action_row_responsive.py`. Its regex `data-act="resume"[^>]*>([^<]*)</button>` still matches.
- **Browser check:** 1440, 1280, 1024 and 900 widths: two rows, and nothing clipped.

**P3.2 Fork banner: full-width, between the header and the Now card, with the doc copy (03 F2; 1.8, 1k, 1l, N6, HIGH).**
- **Where:**
  - delete the card block `ext_cr_detail.js:1622-1634` (`evidenceBody.appendChild(forkCard)`);
  - add `<div class="crd-forkbanner" hidden>…same four children…</div>` to the skeleton immediately before `'<div class="crd-now" hidden></div>'` (`:1466`);
  - `renderForkBanner` `:2572-2597` reads `qs(node, ".crd-forkbanner")` (keep `ui.forkCard` as the cached ref name);
  - CSS `ext_cr_detail.css:549-564` renames the class and restyles it.
- **Copy:**
  - On the copy (`continued_from`): label "Forked". Body: "Resume was refused — this session was running as a background agent, so it was forked. You're looking at the copy; the original is still running." Link: "Open the original".
  - On the parent (`continued_as`): body "A fork of this session continued the work — " + `forkSessionLabel(...)`. Link: "Open the copy".
  - The banner stays hidden when there is no lineage.
- **CSS:** `margin: 14px 26px 0; padding: 11px 15px; background: var(--surface-provenance); border: 1px solid var(--line-default); border-left: 2px solid var(--line-dusk); border-radius: 4px;`. The phone tier gets `margin: 10px 12px 0`.
- **Test:**
  - in the skeleton string, the index of `crd-forkbanner` is less than the index of `crd-now`;
  - `crd-forkcard` is absent;
  - the "Resume was refused" string is present.
- **Risky spot: the copy is accurate only if every recorded fork comes from the resume-refusal retry.** `store.record_fork` is called only from `_retry_with_fork` (`term_vt.py:2499,2556`), and its backstop watches for "the bg-agent refusal or the missing-transcript message" (`:2257-2259`). If the missing-transcript path can also fork, fall back to the neutral "Resume was refused, so it was forked." The implementer must read `term_vt.py:2256-2300` and choose.

**P3.3 Files row shows edit-call counts as removed lines (03 F7, LOW-MED, honesty).**
- **Where:** `renderFiles` `ext_cr_detail.js:2896-2917`.
- **Change:**
  - Split the path into `<span class="crd-file-dir">dir/</span><span class="crd-file-base">base</span>`.
  - Edited files show `<span class="crd-file-edited">N edits</span>` in neutral ink, with no `−`. Created files keep `+N` in forest.
  - CSS: `.crd-file-base { font-weight: 500 }`, and `.crd-file-edited { color: var(--text-secondary) }`.
- **Test:** assert `crd-file-base` is present and `'−' + (f.ops` is absent.

Phase 3 diff: about 60 lines of JS and CSS, plus about 50 lines of tests.

### Phase 4: Help and Config honesty

**P4.1 Data files never shows real paths and lists 4 of the 7 files (04 N6, LOW-MED).**
- **Server** (`server.py:410-428`, GET `/api/config`), after `AUTH_SET`:
  ```python
  local = _local_caller(self)[0]
  files = {"flags": config.FLAGS_FILE, "titles": config.TITLES_FILE, "pins": config.PINS_FILE,
           "notes": config.NOTES_FILE, "model_keep": config.MODEL_KEEP_FILE,
           "forks": config.FORKS_FILE, "config": config.CONFIG_FILE}
  snap["DATA_FILES"] = {k: (v if local else os.path.basename(v)) for k, v in files.items()}
  ```
  - Never include `TOKEN_FILE` or `PORT_FILE`.
  - **Risky spot:** `/api/config` is on the read-only tunnel allow-list (`server.py:251`). Full paths would leak the home directory to remote viewers, which is why remote callers get basenames.
  - The route path is unchanged. This is not a provider shape, so no provider change is needed.
- **Client** (`ext_cr_dialogs.js`):
  - in the `fetchServerConfig` callback (`:1590-1595`) add `srv.dataFiles = cfg.DATA_FILES || null;`;
  - at `:1570-1576` iterate the seven keys;
  - with no data yet, render `'—'` and not a guessed name.
- **Test** in `tests/test_cr_routes.py`:
  - a local GET `/api/config` returns `DATA_FILES` with exactly those seven keys, and no value contains `token`;
  - a non-local, read-only request gets basenames only.
  - Follow the existing local/remote fixtures in `tests/test_cr_readonly_ui.py` or `test_tunnel.py`.

**P4.2 Help's capability table omits post-September capabilities (04 N10, MED).**
- **Where:** append after `[61, …]` at `ext_cr_dialogs.js:566`. Rows 1–60 stay as in the doc.
- **New rows:**
  - `[62,'Model gateway: Anthropic / OpenRouter','terminal+dialogs']`
  - `[63,'Tunnel share + read-only remote','dialogs']`
  - `[64,'Idle terminal TTL','dialogs']`
  - `[65,'Session snapshot TTL','dialogs']`
  - `[66,'Header line: job summary / narration','dialogs']`
  - `[67,'Icon style and size','dialogs']`
  - `[68,'Job-summary headline on tiles, rail, header','board+detail']`
  - `[69,'Session cost chip + breakdown','detail']`
  - `[70,'Model-update nudge + keep','terminal']`
  - `[71,'Folder terminals, one per session','terminal']`
  - `[72,'Agent map','board+detail']` (subject to D6)
  - `[73,'Model marker chip','board+detail']` (subject to D6)
- **Test:** `tests/test_capability_table.py:248` changes from 61 to 73. Update the docstring at `:19`. The test is red until the rows land.
- **Risky spot:** a row for a capability the owner removes under D6. Drop rows 72 and 73 in the same commit if needed.

**P4.3 Live window slider: 1–15 minutes (04 N1, R2-B2, LOW).**
- **Where:** `ext_cr_dialogs.js:1327-1331`.
- **Change:**
  ```js
  return sliderCtlCommit(1, 15, Math.max(1, Math.min(15, Math.round((value != null ? value : 300) / 60))),
                         function (m) { onCommit(m * 60); }, ' min');
  ```
  - Append to the row copy: "The slider covers 1–15 min; env or config.json accept 5 s–24 h." This matches the SNAPSHOT_TTL disclosure at `:1339`.
  - Stored unit (seconds) and the server validator (`config.py:252`) are unchanged.
- **Test:** a node test next to `tests/test_cr_dialogs_config_exec.py` asserts that the slider has min 1 and max 15, and that a change to 7 commits 420.
- **Risky spot:** a value that is not a whole minute (for example 45 s) displays as 1 min. It changes only if the user drags the slider, which the disclosure covers.

**P4.4 Server tab invents 8790 and 127.0.0.1 before config loads (05 N14, LOW).**
- **Where:** `ext_cr_dialogs.js:1402-1405`.
- **Change:** fall back to `'—'` and not to the literals.
- **Test:** the Server-tab source slice contains neither `: 8790` nor `'127.0.0.1'`.

Phase 4 diff: about 12 lines of Python, about 30 lines of JS, plus about 50 lines of tests.

### Phase 5: board tiles

**P5.1 A flagged tile shows the status line, not the flag text (02 N2, 04 R1-#7, MED).**
- **Where:** `tileLine` `ext_cr_board.js:2836-2848`. The server already sends `flag_text` on the list shape for every provider (`registry.py:97`).
- **Change:** at the top of `tileLine`, add `var nowLine = (state === 'flagged' && s.flag_text) ? String(s.flag_text).trim() : ((typeof s.now_line === 'string') ? s.now_line.trim() : '');`. Use `nowLine` in both the no-headline branch (`:2840`) and the headline `sub` (`:2846`). The flagged inset CSS (`ext_cr_board.css:1695-1700`) already styles `.cr-tile-line`.
- **Test:** in `tests/test_cr_board_order_and_empty.py`, or in the node harness of `tests/test_cr_agent_map_entry.py`, which already reaches `sessionTile`: render a flagged session with `flag_text: 'Pushed note stuck'` and `now_line: 'x'`, and assert the text is inside `.cr-tile-line`. It is red at HEAD.

**P5.2 The awaiting hero's side rail lacks todo and failing counts (02 N3, MED, partial).**
- **Where:** sidebar `ext_cr_board.js:2926-2931`.
- **Change:** before the notes row, add `s.todo_total ? countRow('check', s.todo_done + '/' + s.todo_total + ' todos') : null` and `s.fail_cmd ? countRow('x', '1 failing') : null`. Both fields are on the list shape for Claude and Auggie (`auggie.py:377`, `claude.py:968`; `fail_cmd` is used at `ext_cr_board.js:86`). Use the existing `glyph()` and `.cr-tile-counts` classes.
- **Deferred:** the files count. `files_n` is not on the list shape, and adding it needs file-op parsing in `list()` for both providers, which is a list-poll cost.
- **Test:** the hero-tile render includes `todos` when `todo_total > 0`.

**P5.3 Back button title and aria-label differ (02 N9, LOW).**
- **Where:** `ext_cr_board.js:2323`.
- **Change:** `'aria-label': 'Classic dashboard'`.
- **Test:** a source assertion that the two strings are equal.

Phase 5 diff: about 15 lines of JS, plus about 40 lines of tests.

### Phase 6: gate hardening

**P6.1 The bundle test skips silently without node (00 §5 gap 1).**
- **Where:** `tests/test_page_bundle.py:24,205`.
- **Change:** add `def test_node_available(self): self.assertTrue(_HAS_NODE, "node is required for the JS gate; install it or the bundle and logic tests silently skip")`. Leave the existing `skipUnless` decorators, so one clear red and not twenty.
- **Proof:** `PATH=/usr/bin:/bin python -m unittest tests.test_page_bundle` goes red.
- **Risky spot:** a machine without node goes red. That is the point (see the overrule callout).

**P6.2 Bundle epilogue: assert the classic terminal's exports (00 gap 2, overstated).**
- The bundle already runs inside `try { … } catch → exit(1)` (`:174-181`), so any synchronous top-level throw is already red. The real gap is a missing or renamed export.
- **Change:** in `_JS_EPILOGUE` (`:176-195`) also require `window.ExtVT && typeof ExtVT.mountInto === 'function' && ExtVT.term`.
- `ext_launch.js` and `ext_run.js` are IIFEs with no exports, so there is nothing to assert for them.
- **Proof:** temporarily rename `window.ExtVT.mountInto =` at `ext_vt.js:3912`, and the test goes red.

**P6.3 The CSS survival check reads raw CSS, so a selector swallowed by a comment still "survives" (finding missed by the audits).**
- **Where:** `tests/test_page_css.py:264-301`. The comment at `:291` says it searches raw CSS "so we catch cases where the selector is in a comment". That is backwards: text inside a comment still matches a raw search.
- **Change:**
  - Strip comments from the assembled CSS with a non-greedy `re.sub(r"/\*.*?\*/", "", css, flags=re.S)`, which is how a browser pairs comment delimiters.
  - Then check both the **first** and the **last** class selector of each `ext_cr_*.css` file. Add `_extract_last_selector_from_file`.
- **Proof:** insert `/*` (no close) before the last rule of `ext_cr_term.css` and the test goes red. At HEAD the same edit stays green.

**P6.4 Pin the doc token values.**
- **Where:** new `tests/fixtures/cr_tokens_doc.css`, holding the two fenced blocks copied verbatim from bundle doc `01-foundations.md:37-98` and `:112-173`, plus new `tests/test_cr_tokens_doc.py`.
- The test parses `--name: value;` pairs from the fixture's `.tracker-next {` and `.tracker-next.is-dark {` blocks, and from the same selectors in `ext_cr.css` (`:38`, `:313`). It asserts that every doc token is equal, after whitespace and case normalisation.
- Extras such as `--state-working` are allowed.
- **Proof:** change `--surface-*` in the dark block to `#6E3711` and the test goes red. Audit 01's scripted diff says HEAD is green.

**P6.5 Pin the remaining exported pure functions (00 non-negotiable 4).**
- **Where:** `tests/test_cr_logic.py`, which already has the harness.
- **New asserts:**
  - `stateOf`: waiting → `awaiting`, open flags → `flagged`, live with `fail_cmd` → `failed`, live → `done`, not live → `idle`. Use `LIVE_WINDOW` from the page.
  - `firstEventTime`: returns the minimum of the request, oldest-narration, command, commit and decision times, and null when all are empty.
  - `deriveLinks` lives in `app.js` and is already covered by `tests/test_classic_markdown_and_links.py`, so it is not repeated.
- Correct the docstring at `:17-23`.
- **Proof:** stub `firstEventTime` to `return null` and the test goes red.

**P6.6 Enumerate the CR write routes (00 non-negotiable 1).**
- **Where:** `tests/test_cr_readonly_ui.py`.
- Regex every `fetch('…', { method: 'POST'` or `post("…"` literal across `ext_cr_*.js`.
- Assert the set equals an allow-list: `/api/term/{inject,kill,close,pty,open,run}`, `/api/title`, `/api/pin`, `/api/flags*`, `/api/notes*`, `/api/config`, `/api/tunnel/ctl`, `/api/model-keep`. The implementer finalises the set from the grep.
- **Proof:** add a dummy POST and the test goes red.

Phase 6 diff: about 150 lines of tests and fixture. No product code.

### Phase 7: LOW polish (each a few lines)

- **7.1 Rail search has no focus ring (01 N12).**
  - Add `.tracker-next .cr-rail-search:focus-within { outline: 2px solid var(--line-focus); outline-offset: 2px; }` near `ext_cr_board.css:738`.
  - Browser check: Tab to the rail search.
- **7.2 Phone spine labels hidden only at 480px and below (03 F12).**
  - Move `.crd-spine-hint, .crd-seg-elapsed, .crd-seg-running-elapsed { display:none }` from the `max-width: 480px` block (`ext_cr_detail.css:2103-2113`) into a `max-width: 600px` block.
  - Test: a CSS regex asserts the rule sits inside a 600px block.
- **7.3 Status-bar separator (05 N12).**
  - Add `.cr .cr-term-ctxcum::before { content: "/ "; }`, which gives "context 128,412 / cumulative 481,003".
  - Visual-only.
- **7.4 Metaline cwd (03 F11).**
  - Add a home-relative cwd to `metaBits` (`ext_cr_detail.js:2404`), using `meta.cwd`, with a `~` replacement only when the server sends a `home` field. Otherwise use the basename-free tail `cwd.split('/').slice(-2).join('/')`. Do not guess `$HOME` on the client.
  - Test: a source assertion that `meta.cwd` is in `metaBits`.
- **7.5 Mark the old precedence ruling as superseded (00 §1).**
  - Add one line under `reports/control-room-redesign.md:180`: "SUPERSEDED 2026-09-05 by 7b87cce: the docs win (emoji excepted)."
- **7.6 Record D6 and D7 rulings** in the same reports file, once answered.

Phase 7 diff: about 25 lines.

### Deferred, LOW (with reason)
- **01 N5** emoji-mode filter tints: optional icon style only. **01 N6** keyframe names: fold into D3 if (a). **01 N7** 10px floor: the 8px FAIL word is required by doc 03:147; needs a browser fit check. **01 N9** `tabular-nums` on 39 rules: four files, small effect. **01 N11** raw hex in `ext_cr_term.css`: deliberate frozen dark literals.
- **02** R1 5.2 (`tracker.rail` key, needs a dual-read migration), R1 5.5 (placeholder wording), R1 9.4 (hero gradient tokens), N7/N8 (owner-asked overflow fixes in `5dea10f`, pinned by `tests/test_cr_topbar_layout.py`), N11 (copy ruled fine).
- **03** F6 PR title (Claude-only parser change in `util.py:165`; Auggie has no PR extraction; a data feature for its own change), F9 nudge px, F10 "N of M", F13/N14/N16/N23 (D6).
- **04** N12 top-bar live pill (no room in the compacted top bar), R1-#10 name-first ranking. **05** N4 stacking and fork chip, N13 (D6).
- **00** the terminal screen's second 2s `/api/session` fetch: it can show a session other than `cur`, so reusing app.js's response needs an id check; cost is one request every 2s while open. The colour-not-alone node test is already audited.

---

## 3. Sequencing and why

| Phase | Why here | Diff size |
|---|---|---|
| 1 Terminal bugs | Data and work loss: Esc kills the terminal behind a dialog, and a failed spawn loses the path. Users hit these every day. Isolated to `ext_cr_term.js` and the picker. | about 160 lines (half tests) |
| 2 Terminal chrome | Same files as phase 1, so the context is already loaded. Desync and honesty, no data loss. | about 105 lines |
| 3 Detail header and fork banner | The two HIGH layout drifts. Larger visual blast radius, so it lands after the terminal work is stable. Needs a browser pass. | about 110 lines |
| 4 Help/Config | One small server change (`/api/config` field), behind an auth-aware check. Copy and counts. | about 90 lines |
| 5 Board tiles | Uses existing list fields only, no server change. | about 55 lines |
| 6 Gate hardening | Tests only. Lands after the product phases so its new guards (node required, comment-aware CSS) do not block them. Could move first if you prefer. | about 150 lines |
| 7 Polish and rulings | Independent, lowest risk. | about 25 lines |

D1–D8 land as small follow-ups once answered. D3 and D2 are about 10–20 lines each. D4 is about 60 lines. D8 is about 80 lines.

All phases go on this one branch (rule 9), as seven commits.

---

## 4. Verification plan

1. **Gate, per phase.**
   - Run the changed modules first: `unset TRACKER_AUTH; python -m unittest tests.test_cr_term_drift3 tests.test_cr_manage_terminals_parity -v`. Without `unset TRACKER_AUTH` you get about 33 blanket 401s.
   - Then the full gate, one module per process to avoid the OOM kill (`Killed: 9` with no failures is memory pressure, not a red build): `unset TRACKER_AUTH; for f in tests/test_*.py; do python -m unittest "tests.$(basename "$f" .py)" || echo "FAIL $f"; done`. Run it from a script file if the worktree guard refuses the loop. Never pipe it through `| tail`.
   - `make check` must print `selfcheck ok`.
   - `git commit` runs the full gate through the hook (180–380 s), so give Bash a timeout of at least 400000 ms.
   - Known flake: one load-sensitive `term_vt` backstop test fails in a full run and passes in isolation.
2. **Red proof per test.**
   - For every new or changed assertion, revert its fix with a scoped Edit (never `git stash`), run that single test, and record it RED.
   - Restore the fix and record it GREEN.
   - Log each pair in the phase's commit message body, as test name → red/green.
3. **Browser pass** for visual items P1.1–P1.4, P2.1, P2.2, P3.1, P3.2 and P7.1–7.3.
   - Use a test server on a spare port (for example `python -m aitracker --port 8795` from the worktree). Never 8787 or 8790, and never `pkill -f aitracker`. Stop it by its own PID when finished.
   - Restart it after each phase, because the page is baked at startup.
   - Check both themes at 1440, 1280, 1024, 900 and 390 widths.
   - Zero console errors, and no horizontal scroll.
4. **Bundle sanity after every phase:** `python -m unittest tests.test_page_bundle tests.test_page_css`. A load-time throw or a stray `*/` in any `ext_*` file silently kills every file after it.
5. **Ship:** `/branch-sync` in the worktree, re-run the gate green, then push the branch to `personal` (never `main`).

---

## 5. Dropped and not examined

### Dropped (with reason)
- **03 N1, h1 = Goal:** already ruled. `5dea10f`: "the detail header shows the SESSION NAME, per the owner … Doc 03:76 asks for the opposite; the owner's ruling wins." Audit 03 missed the ruling.
- **01 N3, theme control re-click to auto:** deliberate. `ext_cr_board.js:2472-2480` explains it: with a real Auto button, re-clicking Dark should stay Dark. The owner's "no way back to auto" complaint is answered by that button.
- **00 decision 9, the "stale comment" at `ext_cr_detail.js:308`:** the comment says anything but an exact `"spine"` is the heartbeat default, which is what the code does.
- **00 §5 gap 2 as worded** ("a throw at the end of `ext_cr_term.js` would kill ext_vt with a green gate"): false. The harness wraps the bundle in try/catch and exits 1 (`tests/test_page_bundle.py:174-181`). It is replaced by P6.2's export check.
- **00 §5 gap 3's fix as worded** (also check the last selector): not enough on its own, because the check searches raw CSS. P6.3 replaces it.
- **05 N3's fix as worded** (`topName()` only): does not work, because the dialogs listener runs first and empties the stack (see P1.1).
- **02 E2 / R1 4.2, the Sessions pill:** ruled by `5dea10f` ("owner asked to keep them"). It is only recorded under D6.
- **04 N18, `?` opens Help:** verified at `ext_cr_board.js:3069-3072`.

### Not examined
- 01 N10 (gap, never margins) and 01 N16 (shadow plus glow on a working tile): not audited by anyone.
- Focus and scroll preservation across polls on the board (02 N14, R1 A8): not re-run in a browser.
- Toast timings (04 N13) and phone hit-target sizes (03 N25): static reads only.
- Whether `config.get("PORT")` reflects the bound port when `config.json` changed without a restart (affects P4.4's honesty). Not checked.
- Prototype Round 5 artboards: not diffed in this round (docs win).
- The 12 native dialogs in the classic dashboard: out of scope per README.
