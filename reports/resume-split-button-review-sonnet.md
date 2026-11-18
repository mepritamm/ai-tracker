# Adversarial plan review (sonnet) - Resume split button

Verdict: contract clauses 2-8 are met on paper and no backend change sneaks in. The grounding (server `resumable` row flag in `registry.py:32`, the 403 probe, `ctx.readOnly`, global `sessions` at `app.js:1083`) is correct. Findings below.

## Findings

1. **MAJOR - board hero overflows the 124px sidebar (nowrap regression).**
   - Defect: `.tsplit{white-space:nowrap}` (P1 CSS) plus a caret (min-width 24px) inside `.cr-tile-sidebar` (`flex:0 0 124px`, `padding-left:17px`, so about 107px usable, `ext_cr_board.css:1748`). The Auggie/non-resumable hero primary "Open terminal" (14px padding each side, plus caret) is about 140px. The Resume primary is about 114px.
   - History: `test_cr_board_resume_button.py:204` exists because nowrap on the shared tile rule already overflowed this sidebar once. Repro: awaiting Auggie hero at desktop and 390px gives text spilling past the tile border; expected is no overflow.
   - FIX DIRECTION: let the hero primary shrink and wrap. Do not touch the shared `.tracker-next .cr-tile-action` rule (that test pins it), and do not widen the sidebar.
   - THE WAY: in `ext_cr_board.css` add `.tracker-next .cr-tile-sidebar .tsplit{max-width:100%;white-space:normal}`, `.tracker-next .cr-tile-sidebar .tsplit-primary{min-width:0;padding:7px 10px;text-align:left}`, and `.tracker-next .cr-tile-sidebar .tsplit-caret{padding:7px 6px}`.
   - THE TEST: a CSS-source test in `test_cr_board_resume_button.py` asserting those three scoped rules exist. Revert the CSS and it goes red. The browser check at 390px stays in the P3 end-to-end step.

2. **MAJOR - the `.tsplit-open` class used by a board CSS rule is never defined.**
   - Defect: P2 Unit 5 adds `.cr-tile:has(.tsplit-open)`, but P1 never says `termSplitOpen` sets that class. The rule is dead, so the menu can paint under the next grid tile.
   - FIX DIRECTION: key the rule on the state that already exists. Do not add a second state flag.
   - THE WAY: `.tracker-next .cr-tile:has(.tsplit-caret[aria-expanded="true"]){position:relative;z-index:3}`. Only keep it if tiles create a stacking context (none was found at `ext_cr_board.css:1478`; the z-index 80 list may already win, so verify in the browser and drop the rule if so).
   - THE TEST: a CSS-source test that every `.tsplit-*` state class named in a caller CSS file is also set in `app.js`.

3. **MAJOR - the plan's "must stay green" list is incomplete: 21 test files load the bundle through a fake DOM.**
   - Defect: the fake DOM is `_REAL_DOM_PREAMBLE`/`_bundle_js` from `test_working_glow_board.py`. Its `innerHTML` setter never parses (line ~246) and `closest()` returns null. If `termSplit` builds with `innerHTML`, or `termSplitSet` assumes `querySelector` hits, every harness that renders a hero tile, mounts the toolbar (`_build`) or the header (`mount`) throws.
   - Repro: the old string `termSplit` was safe in these harnesses; the new Element builder is not guaranteed to be.
   - FIX DIRECTION: build the split with `createElement` and `appendChild` only, and null-guard every lookup in `termSplitSet`/`termSplitOn`.
   - THE WAY: Unit 1 acceptance includes running every module from `grep -l "_REAL_DOM_PREAMBLE\|_bundle_js" tests/*.py`. Names missed by the plan include `test_cr_manage_terminals_parity`, `test_resume_all_ui`, `test_session_isolation`, `test_term_recreate`, `test_inject_reason_surface`, `test_model_update_nudge`, `test_cr_term_login_pill` and `test_cr_dialogs_poll_broadcast_seam`.
   - THE TEST: one case in `test_tsplit_shared.py` calls `termSplit` and `termSplitSet` against the `makeReal` stub and expects no throw.

4. **MINOR - header responsive rules defeat "no per-caller override".**
   - Defect: `ext_cr_detail.css:1831` and `:1852` (`.cr .crd-row1-actions .crd-btn`, specificity 0,3,0) tie with the caret's padding rule (0,3,0) and come later in source order. At 901-1300px and at 900px or narrower the caret padding becomes 10px, so it is wider than the other callers.
   - FIX DIRECTION: cosmetic only. Either accept it or raise the caret rule to 0,4,0.
   - THE WAY: `.tsplit:not(.tsplit-solo):not(.tsplit-nomenu)>.tsplit-caret` in `app.css`.
   - THE TEST: none needed beyond the browser check.

5. **MINOR - the alignment flip has an ordering trap.**
   - Defect: `_tsplitFit` measures `getBoundingClientRect()` on the list. The list is `hidden`, so it measures 0x0 unless it is unhidden first. In the board, the nearest non-visible-overflow ancestor is `.cr-board-scroll` (`overflow-y:auto`), so it flips against the wrong box.
   - FIX DIRECTION: unhide first, measure, then flip. Measure against the clipping `overflow:hidden` frames only (toolbar shell, classic frame).
   - THE WAY: in `termSplitOpen`, set `list.hidden=false` before the `_tsplitFit` call. In `_tsplitFit`, check only `overflow-x`.
   - THE TEST: case (9) must open a list with a nonzero rect, after `hidden` is cleared, and see `tsplit-start` added.

6. **MINOR - over-engineering: snapshot/restore for the classic pane.**
   - Defect: the classic pane rebuilds `el.innerHTML` only for the home note. A rebuilt split also loses a mousedown-to-click in flight.
   - FIX DIRECTION: in Unit 4 keep the split element across renders when `data-tsplit-key` is unchanged and only call `termSplitSet`. This removes the classic use of snapshot/restore and the test (a)/(b) mutants. Keep snapshot/restore for the board only, where the tile is genuinely rebuilt.
   - THE TEST: re-render with the same `cur` and assert the same node identity.

7. **MINOR - the board hero shows an unprobed external state.**
   - Defect: `termExtAllowed()` returns null on the first render, so `ext:false` is applied. Nothing re-renders until the next poll, so external and the alt-hint are missing for one poll interval.
   - FIX DIRECTION: in `heroSplit`, when the result is null, call `termExtProbe().then(...)` and re-run `termSplitSet` on the same node.
   - THE TEST: probe 400 resolves, then the external item becomes visible without a re-render.

8. **MINOR - Unit 6 list gaps.**
   - `test_cr_detail_agents_pill_and_markdown.py:166` only has a docstring mentioning `isLocalhost`, so it stays green.
   - `test_cr_board_resume_button.py:198` ("Open terminal to answer" text) is covered by Unit 5.
   - `test_term_split_menu.py` is covered.

## Sound
- The sequencing and parallel split of Units 2-5 over disjoint files.
- The Escape and `stopPropagation` design against the overlay's bubble-phase listener (`ext_cr_term.js:249`).
- `CR.dialogs.trapFocus` is safe, because hidden menuitems are filtered by `offsetParent`.
- The tile click guard `[role=menu]`.
- Hiding read-only viewers with the universal `html.tracker-readonly .tsplit` rule.

## Overall clean plan delta
1. Add scoped hero shrink/wrap CSS (finding 1) plus its CSS-source test.
2. Replace `.tsplit-open` with `.tsplit-caret[aria-expanded="true"]` (or drop the rule if not needed).
3. Build with `createElement` only, null-guard lookups, and run all 21 bundle-harness modules in Unit 1 and Unit 6.
4. `termSplitOpen` unhides the list before `_tsplitFit`, and measures only clipping `overflow-x` frames.
5. Classic pane reuses its split node by key. Snapshot/restore stays for the board only.
6. `heroSplit` re-syncs the external state when the probe resolves.
7. Optional: raise the caret padding specificity to 0,4,0 (finding 4).
