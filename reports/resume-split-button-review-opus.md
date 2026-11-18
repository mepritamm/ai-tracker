# Adversarial plan review: Resume split button (opus, 2026-11-18)

## Findings

**1. MAJOR: the board's real-bundle harness breaks.** `renderBoard` will now run termSplit, Set, Snapshot and Restore inside `makeReal` (tests/test_working_glow_board.py:155-267). That harness has four limits:
- `queryAllReal` matches a single class only.
- `closest()` always returns null.
- There is no `el.contains` and no `document.activeElement`.
- `addEventListener` keeps one listener per type, and `simulateClick` sends an event with no `target`, `preventDefault` or `altKey`.

Repro: an awaiting hero goes through `termSplitSet` with `querySelector('[data-tsplit-act="external"]')`, which returns null and throws a TypeError. That turns about 18 `_REAL_DOM_PREAMBLE` modules red. Unit 5's click and alt tests also cannot be driven.
- **Fix direction:** make the helpers harness-agnostic. Do not widen makeReal, which 18 files share.
- **The way:**
  - `termSplit` builds with `createElement` only and stores references: `split._ts={res,open,caret,list,iOpen,iExt,label,hint}`.
  - Set, On, Open, Close, Snapshot and Restore use `_ts` and never call a selector query.
  - `termSplitOn` binds per button. Read `e&&e.altKey`, and call `e.preventDefault` only if it exists.
  - Snapshot guards `document.activeElement` and `typeof x.contains==="function"`.
- **Test:** Unit 5 runs every `_REAL_DOM_PREAMBLE` module plus the 11 detail-mount modules. Mutant: Set using `querySelector` makes the hero harness throw (red).

**2. MAJOR: the gate goes red on "⌥".** U+2325 is in the Misc Technical range (tests/test_icons.py:193) and is not in `_KEPT_TYPOGRAPHIC` (:210-222). So `test_no_pictographic_emoji_outside_comments` fails, and the plan never lists test_icons.
- **Fix:** change `set("⌘")` to `set("⌘⌥")` and update its comment (Unit 1).
- **Test:** red before the edit, green after.

**3. MINOR: `.tsplit-open` is undefined.** The board CSS relies on `:has(.tsplit-open)`, but P1 never says what Open and Close toggle.
- **Fix (P1):** Open adds `tsplit-open`, sets `aria-expanded=true` and `list.hidden=false`. Close reverses all three. Snapshot reads the class.
- **Test:** shared case (3) asserts the class.

**4. MINOR: Escape on the caret while the menu is open is unspecified.** The base handles it, because `closest(".tsplit-menu[open]")` includes the summary. Under the plan it falls through, and in the toolbar the overlay closes.
- **Fix:** key the Escape branch on `t.closest(".tsplit.tsplit-open")`, covering both caret and list.
- **Test:** shared case (4): caret focused + menu open gives closed, stopped, overlay still open.

**5. MINOR: the hero split overflows.** The sidebar is `flex:0 0 124px` with 17px padding, leaving 107px. The split measures about 110px at 100% icon scale, and more at `--ico-scale` up to 2. Separately, `.tracker-next .cr-tile-action{align-self:flex-start}` defeats `.tsplit{align-items:stretch}`, so the caret and primary heights differ.
- **Fix:**
  - app.css: `.tsplit>button.tsplit-primary,.tsplit>button.tsplit-caret{align-self:stretch}` (0,2,1).
  - ext_cr_board.css: `.tracker-next .cr-tile-sidebar{flex:0 0 auto;min-width:124px}`. Do not add a caller caret rule.
- **Test:** CSS source check, plus a browser check at 100% and 150% icon scale.

**6. MINOR: classic double seam.** `.mini`'s right border plus the caret divider gives a 2px seam.
- **Fix:** add `border-right-width:0` to the joined-primary rule.
- **Test:** browser check.

**7. MINOR: the board hero's external item lags.** On a fresh page it appears only on the next 5s poll, because `heroSplit` has no `.then`.
- **Fix:** `if(ext===null)termExtProbe().then(function(){termSplitSet(sp,{resumable:canResume,ext:termExtAllowed()===true});})`.
- **Test:** board case: local host, flush, external visible with no second update.

**8. MINOR (base parity): an outside tap never closes the menu on iPhone.** iOS sends no document `click` for taps on non-clickable areas, and a null relatedTarget is ignored by focusout.
- **Fix:** do the outside-close on a `pointerdown` capture listener too.
- **Test:** shared case: `pointerdown` outside closes the menu.

**9. MINOR: two Unit 2 details.**
- Test (f) fails on the comment at ext_cr_detail.js:2471. Strip comments or scope the check to `renderHeader`.
- Pass `session.id||sid` (namespaced, registry.py:227) to `syncHeaderSplit`, as the base does, not a `meta.sessionId`-first sid.

**10. OVER-ENGINEERING: two cuts.**
- `termSplitAltName`'s "Alt" branch is dead code. External launch is macOS-only (`osascript`, term_launch.py:234) and loopback-only, so the hint only ever shows on a Mac. Use the constant "⌥".
- `_tsplit_dom.py` should be the existing `_FAKE_DOM`/`_helpers_js` (test_term_split_menu.py:57-124), moved and extended, not a fifth fake DOM.

**11. MINOR: test accounting.**
- Add `ext_cr_board.js` to `test_every_surface_calls_termsplit`.
- State that `test_header_reset_closes_the_menu` (:375) is kept.
- `test_readonly_css_only_under_class` (test_cr_readonly_ui.py) requires every app.css rule after the first `html.tracker-readonly` to be read-only-scoped. Pin "the read-only rule is the split block's last line, directly before app.css:670".
- The "fails on base" claims for Units 2–4 are vacuous, because the functions do not exist on base. Require one mutant per unit: header back to the regex, `here` ignored, no-op restore, and dropping `[role=menu]`.

**Sound (verified):**
- No Python change.
- `sessions` is shared to every caller (app.js:1083, ext_cr_boot.js:977).
- The 403 probe semantics hold (term_launch.py:167-181).
- app.js is first in the bundle (page.py), so its capture keydown runs before the overlay, board and dialog listeners.
- The trap's Tab handling and the `within()` filter are OK.
- The tile's Enter (`target===currentTarget`) and its button ignore list are OK.
- `test_cr_routes`, `test_cr_tunnel` and `test_integration` hostname-proximity are safe, because app.js has no `location.hostname` today and togglePin is about 1400 lines away.
- The `_tsplitFit` flip is needed: the shell is `overflow:hidden` (ext_cr_term.css:43).

## Overall clean plan delta

1. P1 builder stores `split._ts` references. Set, On and Snapshot use no selector queries. Listeners are per-button and tolerate a missing `target`/`preventDefault`/`altKey`. Snapshot guards `activeElement`/`contains`. (F1)
2. P1 defines the `tsplit-open` class plus `aria-expanded`. Escape keys on `.tsplit.tsplit-open`. Outside-close also on `pointerdown`. (F3, F4, F8)
3. Use the constant "⌥" and delete `termSplitAltName`. Unit 1 whitelists ⌥ in test_icons.py. (F2, F10)
4. CSS: an `align-self:stretch` override, a joined primary with `border-right-width:0`, a hero sidebar `min-width:124px;flex:0 0 auto`, and the read-only rule kept last. (F5, F6, F11)
5. heroSplit re-sets after the probe resolves. The header passes `session.id||sid`. (F7, F9)
6. Unit 6 additions: test_icons, the full `_REAL_DOM_PREAMBLE` set, the detail-mount set, the board in `test_every_surface_calls_termsplit`, and mutant REDs for Units 2–5. Build `_tsplit_dom.py` from the existing `_FAKE_DOM`. (F1, F10, F11)

## Re-review (revised plan)

**Folded rows: all applied, nothing contradicts them.** Checked against plan lines:

| Row | Where it landed |
|---|---|
| O1+S3 | P1 harness rules + case 14 + P3 must-stay-green |
| O2 | P1 "Same unit" |
| O3+S2 | `aria-expanded` is the only state; the `:has()` rule is conditional |
| O4 | keyboard Escape branch, case 4, toolbar (g) |
| O5+S1 | app.css `align-self`, Unit 5 scoped shrink, CSS test; `white-space:normal` accepted |
| O6 | joined-primary rule |
| O7+S7 | `heroSplit` `.then` |
| O8 | `pointerdown` listener + case 7 |
| O9 | header `syncHeaderSplit(node, String(session.id\|\|sid\|\|""))`, comment-stripped (f) |
| O10 | constant ⌥, `_tsplit_dom.py` from `_FAKE_DOM` |
| O11 | board added, read-only placement pinned, 4 mutants |
| S4 | the `(0,4,0)` caret rule |
| S5 | unhide before measuring (but see R4) |
| S6 | snapshot kept |

**File sets: disjoint.**
- Units 2, 3, 4 and 5 share no file.
- Unit 1 owns app.js, app.css, ext_cr.css, test_icons.py, `_tsplit_dom.py` and test_tsplit_shared.py.
- Unit 6's `ext_cr_board.css` edit is sequential, after Unit 5, so it is not a conflict.

**R1. MAJOR (new): the test-run sequencing contradicts itself.**
- **Defect:** P4.1 and P1 ("Unit 1 and Unit 6 run EVERY module") tell Unit 1 to run the full `_REAL_DOM_PREAMBLE`/`_bundle_js` set. That set cannot be green while Units 2–4 have not landed.
- **Repro:** after Unit 1 lands, `ext_cr_detail.js` `SKELETON` (~1383) still calls `termSplit('<button…', '…', "crd-btn crd-btn-outline")` at module load.
  - The new `termSplit(o)` hits `undefined.replace` (key sanitising) and throws a TypeError at load.
  - Actual: every bundle module fails with "BUNDLE-THREW".
  - Expected (per plan): Unit 1 sees green.
- **Knock-on:** during the parallel units, Unit 5's `test_cr_board_resume_button.py` (bundle-based) also loads Units 2–4's half-edited files, so its result is noise.
- **Fix direction:** change only which tests run when. Do not add a legacy-signature shim.
- **The way:**
  - P1: change "Unit 1 and Unit 6 run every module" to "Unit 6 runs every module".
  - P4.1, Unit 1 runs only: test_tsplit_shared (case 14 must extract the helpers into `_REAL_DOM_PREAMBLE`, not load `_bundle_js`), test_icons and `node --check`.
  - P4.2: Units 2–5 run their extract-based modules + `node --check`. Unit 5's bundle test counts only after Units 2–4 report done, or in Unit 6.
- **Test:** none (process). Unit 6's full-set run is the proof.

**R2. MINOR: a caret click in the board harness throws.**
- **Defect:** the caret's own toggle listener does not stop propagation, which is correct in real browsers. In `makeReal`, `simulateClick(caret)` bubbles to the tile's `onclick`, and `e.target.closest(...)` (ext_cr_board.js:2737) runs on an undefined `target`, giving DRIVER-THREW.
- **Second trap:** `__btns(tile,'cr-tile-action')` now returns both primaries plus the caret. For Auggie, `[0]` is the hidden Resume primary.
- **Fix direction:** fix the test, not the shared listener.
- **The way:**
  - Unit 5 opens the menu with `caret._listeners.click({target: caret})`.
  - Unit 5 selects buttons by `_attrs['data-tsplit-act']` and `!hidden`.
- **Test:** the Unit 5 "open menu" case runs with no DRIVER-THREW.

**R3. MINOR: the board restore test is unpassable as written.**
- **Defect:** `makeReal` has no `isConnected`, `focus()` does nothing, and there is no `activeElement`.
  - A guard written as `if(!sp.isConnected)` makes restore a no-op in the harness.
  - "Keeps the focused item" cannot be observed there.
  - Separately, the `TSPLITS` prefix scan can return a stale, still-`aria-expanded` disconnected node first.
- **The way:**
  - Restore and Snapshot skip only `sp.isConnected === false`.
  - Unit 5 asserts open state only: the rebuilt caret has `aria-expanded="true"` and `list.hidden===false`.
  - Focus stays covered by shared case 9 and classic (a).
- **Test:** delete `termSplitRestore(tsnap)` and the Unit 5 case goes red.

**R4. MINOR: the `_tsplitFit` rationale is wrong, though the behaviour is correct.**
- **Defect:** when `overflow-y` is not `visible`, `overflow-x` computes to `auto`. So `.cr-board-scroll` (ext_cr_board.css:1460) IS measured. The plan says it is ignored.
- **Why it doesn't matter:** measuring it is correct. On the phone tier the hero sidebar stacks at the tile's left (ext_cr_board.css:2020), so the end-aligned list crosses that box and must flip.
- **The way:**
  - Delete the "correctly ignored" sentence.
  - Replace case 10's impossible "y-auto-only parent does not flip" sub-case with "a parent whose computed `overflowX` is `auto` flips when crossed".
- **Test:** case 10.

Sound: the Unit 5 CSS specificities (caret left/right 6px either way; primary 7px 10px wins over `.cr-tile-action`), `pointerdown`-owner logic (an open split's own caret/items are not closed by it), and header/toolbar/classic wiring.

**Verdict: BLOCKED: R1.** P1/P4 tell Unit 1 to expect the full bundle set green while the legacy callers still throw at load. This is a one-line sequencing edit; after it the plan is ready to implement. R2–R4 can be handed to the implementers as written.
