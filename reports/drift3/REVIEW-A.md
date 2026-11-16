# REVIEW-A: adversarial review of PLAN.md, P1, P2, P3, D3, D4, D8

- Code at `adeb6fa`. The worktree fast-forwarded from `76bd154` during this review. Line numbers below are current. `ext_cr_boot.js`, `ext_cr_dialogs.js` and `ext_cr_board.js` moved; the term, detail and vt files did not.
- Method: `grep -n` and `sed -n` slices only. No browser or server was run, so the findings about stacking and focus come from reading the code and need the browser check named in each one.
- Labels: CONFIRMS-PLAN 6 · PLAN-WRONG 10 · OVERSTATED 2 · OVERENGINEERED 0 · MISSED-BY-BOTH 7.

---

## Phase 1

### A1. P1.1 mechanism. CONFIRMS-PLAN
- **Listener order (current lines).** `ensureMounted` mounts `dialogs` first (`ext_cr_boot.js:956`), and that adds `document.addEventListener('keydown', onDocKeydown)` (`ext_cr_dialogs.js:371`). It mounts `term` next (`ext_cr_boot.js:957`): `CR.term.mount` → `_build()` (`ext_cr_term.js:1257`) → the document listener at `:243-245`. The board mounts after both (`ext_cr_boot.js:963`).
- **What happens on Esc.** All three listeners are on the same target and in the same bubble phase, so they fire in registration order. `onDocKeydown` (`ext_cr_dialogs.js:354-361`) pops the stack and calls `preventDefault()`. The terminal listener then sees `is-open` and closes. The audit's `topName()`-only fix is dead on arrival, as the plan says.
- **Capture versus bubble.** Moving the terminal listener to capture would make it run before the dialogs listener. `topName()` would still be non-null at that point, so the guard returns. The plan's two guards are therefore independent of order, and the second guard costs one line, so it is not overengineered.
- **Extra fact the browser check depends on.** The grid engine stops propagation of every key it handles, Escape included (`ext_vt.js:1138-1144`). xterm cancels the keys it handles. So Esc pressed with the PTY pane focused never reaches either document listener. Run the P1.1 browser check with focus on the Manage dialog, not the pane.
- **Test:** the plan's source slice goes red when the fix is reverted. Keep it.

### A2. Esc on a dialog over the board also clears the board's filter. MISSED-BY-BOTH
- **Defect:** the board's handler (`ext_cr_board.js:3079-3097`) runs after the dialogs listener and never checks `e.defaultPrevented`. Inside a dialog `isTypingTarget` (`:3051`) is false, because the target is a dialog button and not `#cr-term-root`.
- **Repro:** on the board, click the Working triage cell, open Help, press Esc. Actual: Help closes and the filter clears (`setFilter(activeFilter)` toggles it off), or the rail overlay closes. Expected: only Help closes.
- **Direction:** the board ignores keys a dialog already consumed. Do not change the board's own Esc behaviour when no dialog is open.
- **Way:** make `if (e.defaultPrevented) return;` the first line of that listener. Also add `ev.preventDefault()` in the terminal's Esc branch before `close()`, so later listeners can tell the key was consumed.
- **Test:** slice the `bindKeyboard` listener and assert `defaultPrevented` appears before `'Escape'`. Red at HEAD.

### A3. P1.2: the notice is hidden under the engine, not a scrim over live output. PLAN-WRONG
- **Defect:** the notice and the engine are stacked the wrong way round.
  - `mountInto` appends `.vttermwrap` to `el.pane` after the `.cr-term-pane-blank` node (`ext_vt.js:3667-3669`).
  - `ext_cr_term.css:309-312` positions the wrap absolutely with `inset:0`. Neither element has a `z-index`, so the later sibling paints on top.
  - The wrap's `.vtpane` is opaque (`background: var(--ring2)`, `ext_vt.css` around `:121`). The XtermTerminal constructor builds that pane synchronously (`ext_vt.js:1788-1791`).
  - So doc 05 L69 ("say so in the UI") is not met at all. The audit's "82% scrim over live output" was static reasoning without a stacking check.
- **Repro:** open a grid terminal and click "xterm" in the segment control. Actual (per the code): no notice is visible. Expected: a short notice that says the pane is blank until the next write.
- **Direction:** make the notice visible, short-lived and out of the way. Still do not fake a repaint.
- **Way:**
  - CSS `.cr .cr-term-pane-blank`: add `z-index: 2`, which is below the toast's `z-index: 5`. Put the strip on the bottom edge (`inset: auto 0 0 0`). A top strip would cover the engine's A−/A+ toolbar, which the wrap puts first (`ext_vt.js:1770-1771`). Keep `pointer-events:none` and the `#1F1B16` background.
  - JS `_setRenderer` (`ext_cr_term.js:928-945`): show the notice only when the switch rebuilt a live engine: `el.blank.hidden = !(st.engineHandle && next === "xterm")`. Today it also shows over "No terminal open yet." when nothing is attached.
  - Keep the plan's 8 s timer, the capture-phase `keydown`/`pointerdown` listeners, and the clear in `_resetPaneChrome`.
- **Test:**
  - The blank CSS block contains `z-index` and does not contain `inset: 0;` or `.82`.
  - `_setRenderer`'s body references `st.engineHandle` on the line that sets `el.blank.hidden`.
  - The timer and listener assertions from the plan.
  - A browser check at 1280 is mandatory: the notice shows, then a key press clears it.

### A4. P1.3: the network `.catch` re-wraps the server's own message. PLAN-WRONG
- **Defect:** the plan throws `new Error(msg)` inside `.then` and keeps a trailing `.catch(e => { throw new Error("Failed to reach the server: " + e) })` (`ext_cr_term.js:661`). The trailing catch also catches the `.then`'s throw.
- **Repro:** POST returns 403. Actual: the picker shows "Failed to reach the server: Error: In-browser terminal is disabled — set …". Expected: the 403 text on its own.
- **Way:** attach the network handler to the fetch only: `post(...).catch(function (e) { throw new Error("Failed to reach the server: " + (e && e.message || e)); }).then(j).then(function (res) { … throw new Error(msg) … })`.
- **Test:** source slice: in `_pickDirectory`, the first `.catch(` comes before `.then(j)`. Red with the plan as written.

### A5. P1.3: the typed path IS lost. "release does not repaint" is false. PLAN-WRONG
- **Defect:** the picker repaints even though `release` does not.
  - `paint()` empties `chrome.body.innerHTML` and builds a new `input` (`ext_cr_dialogs.js:2389-2391,2426`).
  - The cwds response triggers `update()` → `paint()` while the spawn is still in flight.
  - The existing harness proves that sequence is reachable (`tests/test_cr_manage_terminals_parity.py:392-403`).
- **Repro:** type `/tmp/proj`, press Start, the cwds list arrives, then the spawn fails. Actual: the error shows and the field is empty. Expected: the field still reads `/tmp/proj`.
- **Way:**
  - Hold `var typed = ''` beside `busy`.
  - Build the input with `value: typed` and `oninput: function () { typed = input.value; }`.
  - Re-append `errEl` the same way the plan already plans.
- **Test:** in the harness, set the value, start, `update()` with cwds, then reject. Assert `findInput().value === '/tmp/proj'` and that `.cr-picker-error` holds the message. Red at HEAD.

### A6. P1.3: Enter must go through `h()`, or the harness breaks. PLAN-WRONG (detail)
- **Defect:** the harness's mock `h()` nodes have no `addEventListener` (`tests/test_cr_manage_terminals_parity.py:365-371`). `input.addEventListener(...)` would throw, and every picker test would go red for the wrong reason.
- **Way:** pass `onkeydown: function (e) { if (e.key === 'Enter') { e.preventDefault(); go.click(); } }` as an attribute. The real `h()` maps `on*` attributes to listeners (`ext_cr_dialogs.js:49`). Declare `go` before `input`, or call `submit(input.value.trim(), go)` directly. The mock has no `.click()`.
- **Test:** `findInput().attrs.onkeydown({key:'Enter', preventDefault(){}})` with a value set calls `onPick` once.

### A7. Every `_pickDirectory` toast is invisible when the picker was opened from the board. MISSED-BY-BOTH
- **Defect:** "+ New session" → `term.openPicker('new')` (`ext_cr_boot.js:501-505`) opens the picker without the terminal overlay. The overlay is `display:none` unless it has `.is-open` (`ext_cr_term.css:22-32`), and `showToast` (`ext_cr_term.js:107-113`) writes into it. That loses:
  - the success toast;
  - "Popup blocked — allow popups…" (`:659`). `window.open` runs after an async fetch, so a blocked popup is plausible;
  - any failure in the cap-retry, which the plan's `_pickDirectory(...).catch(function(){})` (`:640`) now swallows completely, because failures no longer toast.
- **Repro:** from the board, start a session with popups blocked. Actual: nothing happens and no message appears. Expected: "Popup blocked…".
- **Way:**
  - `showToast(msg)`: `if (!st.open && ctx && typeof ctx.emit === "function") { ctx.emit("notify", { text: msg }); return; }`. Payload `{text}` is the bus convention (`ext_cr_dialogs.js:273-277`).
  - The cap-retry catch becomes `.catch(function (e) { showToast(e && e.message || String(e)); })`.
- **Test:** source slice: `showToast` references `st.open` and `"notify"`, and the retry `.catch` body is not empty. Red at HEAD.

### A8. P1.4: `handle.focus()` is a no-op for xterm, the default renderer. PLAN-WRONG
- **Defect:** the xterm terminal does not exist yet when the plan calls `focus()`.
  - `XtermTerminal.prototype.attach` builds only after `_loadXtermAssets().then(...)` (`ext_vt.js:1814-1820`). That is always async, even on a second open, because it is a promise `.then`.
  - `focus` is `if (this.term) …` (`:2009-2011`).
  - `mountInto`'s `finish()` calls `attachRenderer` and then `fireForked` synchronously (`:3812-3813`). So in `onForked`, and right after `setRenderer`, `this.term` is still null. Only grid works.
- **Repro:** open a terminal with renderer xterm and type without clicking. Actual: nothing is typed. Expected: the keys reach the PTY.
- **Way:** an additive change in `ext_vt.js` of about 2 lines, which also helps classic.
  - `XtermTerminal.prototype.focus`: `if (this.term) { … } else { this._wantFocus = true; }`.
  - At the end of `_build` after `term.open`: `if (self._wantFocus) { self._wantFocus = false; try { term.focus(); } catch (e) {} }`.
  - The CR side stays as the plan has it.
- **Test:** source slices: `XtermTerminal.prototype.focus` sets `_wantFocus`, and `_build` reads it. Both are red at HEAD.

### A9. P1.4 steals focus from an open dialog. MISSED-BY-BOTH
- **Defect:** `onForked` can arrive seconds after `open()`. A refused resume takes about 2.6 s (`term_vt.py` BACKSTOP docstring around `:2259`). If the user opens Config, Help or Manage meanwhile, `handle.focus()` moves focus behind the dialog into the PTY. Esc is then swallowed by the engine (A1), so the dialog cannot be closed with Esc, and typing lands in the shell.
- **Way:**
  - Focus only when `st.open && !(window.CR.dialogs && window.CR.dialogs.topName && window.CR.dialogs.topName())`.
  - Add `&& el.shell.contains(document.activeElement)` so it never pulls focus from outside the overlay.
  - Use the same guard in `_setRenderer`.
- **Test:** the plan's focus slice must also contain `topName`. Red without the guard.

## Phase 2

### A10. P2.1. CONFIRMS-PLAN
- The classes exist: `vtthemebtn` (`ext_vt.js:527`) and `vtrendererbtn` (`:654`).
- The renderer button calls the mount's `switchTo`, which bypasses CR's `_setRenderer`. `st.renderer`, the segment control, the footnote and the notice then all go stale.
- `display:none` also takes the buttons out of the tab order. A CSS-presence test is enough.

### A11. P2.2: "connected" pops a red error toast on every open and every switch. MISSED-BY-BOTH
- **Defect:** the connection status is toasted even when nothing is wrong.
  - `es.onopen` fires `"connected"` (`ext_vt.js:949,1968`) asynchronously, after `onForked` has set `st.tty`.
  - So the attached branch (`ext_cr_term.js:493`) toasts it. A switch to xterm also toasts "loading xterm.js…" and "connecting…".
  - `.cr-term-toast` is styled as a failure (`--surface-failed`/`--text-failed`, `ext_cr_term.css:410-415`).
  - The plan keeps `showToast(text)`.
- **Repro:** open any terminal. Actual: a red toast reading "connected". Expected: no toast, and the status chip reads "connected".
- **Way:** always write `el.conn`. Toast only for `/^(reconnecting|disconnected|failed)/.test(text)`. Those are the engine's own literals (`ext_vt.js:697-699,1818`).
- **Test:** slice the attached branch. It writes `el.conn`, and the `showToast` call sits behind that test. Red at HEAD.

### A12. P2.3, second half: a streamed notice is never wiped. OVERSTATED
- `finish()` fires `fireForked` and then `fireNotice` synchronously (`ext_vt.js:3813-3814`). Notices streamed over SSE arrive later and go through `onNotice`.
- So `st.notice = handle.notice || null` in `onForked` cannot discard one.
- Drop that change and its test, which asserts a literal is absent and has no behaviour behind it. Keep `el.lineageBtn.hidden = !st.forked`. That one is a real fix: the missing-transcript notice (`term_vt.py:2831-2837`) is not a fork.

### A13. P2.4. CONFIRMS-PLAN, with one tweak
- `mountInto` honours `opts.renderer` on all three paths (`ext_vt.js:3664`, and the spawn path at about `:3893`).
- Tweak: set `st.rendererUser = next` on every `_setRenderer` call, not only when there is no engine. Otherwise a switch made mid-session is forgotten on the next open, which is inconsistent with "keeps the user's choice".

### A14. P2.5. CONFIRMS-PLAN, line numbers moved
- Picker rows are at `ext_cr_dialogs.js:2405-2418`, and Manage rows at `:2241-2262` (`peekBtn` at `:2243`, `killBtn` at `:2244`).
- `aria-label` goes through `setAttribute` (`:50`).

## Phase 3

### A15. P3.1: the two rows are in the wrong container. PLAN-WRONG
- **Defect:** the plan stacks the two rows inside `.crd-row1-actions`, which itself sits inside `.crd-id-row1` (`ext_cr_detail.js:1354-1385`), the eyebrow/meta/state-pill line. That line becomes two button rows tall and pushes the h1 down.
- **What the doc wants:** doc 03:65 has "two columns: identity (`flex:1`) and actions (`flex:0 0 auto`, right-aligned, two stacked rows)". The CSS for that is already in place: `.crd-header` is `display:flex; gap:16px` (`ext_cr_detail.css:67-73`), and below 1024px it becomes a column with `.crd-row1-actions{width:100%}` (`:1798-1799`).
- **Way:**
  - Close `.crd-id-row1` after `crd-pill-agents`.
  - Emit `<span class="crd-row1-actions">[row A][row B]</span>` as the second child of `.crd-header`, after `</div>` of `.crd-id`.
  - Keep the class name, so every selector and `qsa(".crd-row1-actions .crd-iconbtn .crd-ico")` (`:2510`) still match.
  - The click delegation is on `node` (`:1798`), so no handler moves.
  - Drop `margin-left:auto` from `.crd-row1-actions` (`:348-354`). Then add `flex-direction:column; align-items:flex-end; gap:8px`.
- **Test:** the skeleton text between `crd-id-row1` and `crd-id-row2` contains no `crd-row1-actions`. Plus the plan's row A/row B and "Resume here" assertions.

### A16. P3.1 CSS: labels lose their padding, and the phone tier has no rule. PLAN-WRONG
- **Defect:** the plan removes only part of the ≤900px block.
  - It removes `.crd-row1-actions .crd-btn-label` from the ≤900 block but leaves `.crd-row1-actions .crd-iconbtn { padding:0; gap:0 }` (`:1852-1855`). From 601 to 900px, "Search" and "Flag" would sit glued to their glyphs with no padding.
  - Nothing hides the labels on phone. The ≤480 touch-target rule (`:2152-2177`) assumes 28px icon-only circles 7px apart.
- **Way:** move both rules, the label hide and the iconbtn padding reset, from the ≤900 block into the `@media (max-width: 600px)` tier. Leave the `.crd-id-row2` Rename/Pin degrade at ≤900.
- **Test:** the ≤900 block contains neither `.crd-row1-actions .crd-btn-label` nor `.crd-row1-actions .crd-iconbtn`. A ≤600 block contains both. Browser check at 900, 600 and 390.

### A17. Doc label copy. MISSED-BY-BOTH (LOW, note only)
- Doc 03:88 labels the pills "Search this session" and "Flag an issue · N". The code says "Search" and "Flag".
- Record this for the owner. Do not change it inside P3.1.

### A18. P3.2 copy and placement. CONFIRMS-PLAN, and the plan's "implementer must choose" step is already answered
- **Copy:** lineage comes only from `forks.json` (`registry.py:62-88`). That file is written only by `store.record_fork`, which is called only from `_retry_with_fork` (`term_vt.py:2499,2556`). `_retry_with_fork` fires only after `looks_like_bg_refusal` (`:2838-2839`), or after an attach retry following that refusal fails (`:2893,2907`). The missing-transcript path only sets a notice (`:2831-2837`). So use the doc's copy verbatim.
- **Placement:** `.crd-now` is a top-level child, outside `.crd-columns` (`ext_cr_detail.js:1466` versus `:1498`), so "immediately before `crd-now`" is full width.
- **Wiring:** set `ui.forkCard = qs(node, ".crd-forkbanner")` where the card block is deleted (`:1622-1634`).

### A19. "The original is still running" is stated forever. MISSED-BY-BOTH (LOW, owner call)
- **Defect:** a fork from days ago still says the original is running, both at HEAD and in the doc copy. Doc 03:100 also says "never guess".
- **Way:** in `renderForkBanner`, keep the clause only when the parent's list row is live by the server's own state. Use the same `sessionState` that `ext_cr_board.js` exports for the rail dot. Otherwise drop the clause.
- **Test:** a node-exec test where the parent row is not live leaves out "still running".
- **Owner:** this needs a ruling, because the copy is the doc's verbatim text.

### A20. P3.3 fixes only half of the dishonest counts, and the ellipsis cuts the basename. PLAN-WRONG (partial)
- **Created rows also show the edit-call count.** `+N` on created files is `f.ops` too, the edit-call tally (`ext_cr_detail.js:764-767`; `claude.py:1988-1989`; `auggie.py:429`). A file created and then edited three times reads "+4" in the line-count position.
- **The ellipsis cuts the wrong end.** With dir and base spans inside one `nowrap; text-overflow:ellipsis` box (`ext_cr_detail.css:1251-1258`), the end, which is the basename, is cut first.
- **Way:**
  - Created rows: the word `created` in forest ink, plus ` · N edits` when `ops > 1`.
  - Edited rows: `N edit(s)` in `--text-secondary`.
  - Layout: `.crd-file-path { display:flex; min-width:0 }`, `.crd-file-dir { min-width:0; overflow:hidden; text-overflow:ellipsis }` and `.crd-file-base { flex:0 0 auto; font-weight:500 }`.
  - Both providers use the same `{path, ops, created}` shape, so there is nothing to add on the server.
- **Test:** `renderFiles` source contains neither `'+' + (f.ops` nor `'−' + (f.ops`, contains `crd-file-base`, and the CSS gives `.crd-file-base` `flex: 0 0 auto`.

## Decisions

### A21. D3(a): `crd-pulse` is shared, so recolouring it turns the spine green. PLAN-WRONG
- **Defect:** the halo the plan recolours (`ext_cr_detail.css:727-731`) is also used by `.crd-seg-dot` (`:681-686`). That dot is the spine's running segment, which the plan says stays wheat.
- **Way:**
  - Add `@keyframes crd-pulse-working` and `@keyframes cr-board-pulse-working`, using `rgba(var(--state-working-rgb), …)`.
  - Point only the session-state Working consumers at them.
  - Leave `crd-pulse` wheat.
  - Name the token `--state-working-rgb`, to mirror classic's `--st-working-rgb` (`app.css:80-81`).
- **Test:** `.crd-seg-dot` still animates `crd-pulse` and its keyframe still holds `217,184,85`. Extend `test_st_working_rgb_matches_st_working_hex` (`tests/test_state_color_parity_app.py:301`) to assert that the CR `--state-working-rgb` matches `--state-working` in both palettes.

### A22. D3: the split is wider than the plan lists, and the "pill is green" premise is false. MISSED-BY-BOTH
These session-Working surfaces are still wheat:
- **State pill:** `.crd-pill-state.crd-state-working` uses ink `--text-thinking`, border `--line-agent` and the `crd-pulse` halo. Only its glow is green (`ext_cr_detail.css:135-141`).
- **Phone orb:** `.crd-phone-orb.crd-state-working` (`:1980-1985`).
- **Triage Working cell:** the count and the active underline (`ext_cr_board.css:1348,1375`).
- **Reduced motion:** the tile-dot outline (`:1640-1644`).

Under (a), all of these move. `--line-agent` and `--glow-agent` stay on agent surfaces.

### A23. D3: `--state-working` is not a text ink. PLAN-WRONG
- **Defect:** `#1C9163` was tuned to the 3:1 non-text floor (`tests/test_state_color_parity_app.py:226-245`). It is about 3.98:1 on white and about 3.2:1 on `#EFE8D8`. Both are below 4.5:1, the floor for the tile state word and the pill text at roughly 11px.
- **Way:**
  - Add a `--text-working` ink to both CR palettes for words. Light needs at least 4.5:1 on the tile surface; dark can reuse `#29d398`.
  - Keep `--state-working` for dots and fills.
- **Test:** a contrast assertion like the existing one. `--text-working` must reach at least 4.5:1 on the tile surface token in both themes.

### A24. D4 is not an open question: there is an owner ruling. OVERSTATED
- Commit `aadcae5` (2026-08-30): "the timeline the owner actually asked for… It sorted OLDEST-first". That was an owner-reported defect, sent by screenshot.
- `7b87cce`'s "docs win" says "docs beat the prototype". It does not override owner reports.
- Record newest-first as a ruling, citing `aadcae5`, and take D4 off the owner's list. Delete the code under option (a).

### A25. D8, defer. CONFIRMS-PLAN
- If (a) is ever built, pass `isDetail` into `renderCollapsedOrbs` (`ext_cr_board.js:1854`) instead of reading the `cr-rail--detail` class. That class is toggled in a separate path (`:1139`), so the first paint may race it.
- Keep the phone orb at 44px (`ext_cr_board.css:1990`).

---

## Clean plan for this scope (landing order)

**Phase 1, terminal correctness**
1. **P1.1:** the terminal Esc listener gets the plan's `defaultPrevented` + `topName()` guards and calls `ev.preventDefault()` before `close()`. The board listener returns on `e.defaultPrevented` (A2). Two source tests.
2. **P1.2:** `.cr-term-pane-blank` becomes a bottom strip with `z-index:2` and no full-pane background. `_setRenderer` shows it only when `st.engineHandle` exists and the target is xterm. Keep the 8 s timer, the capture-phase keydown/pointerdown clear, and the clear in `_resetPaneChrome` (A3). Browser check required.
3. **P1.3:** in `_pickDirectory`:
   - the network catch sits before `.then(j)` (A4);
   - non-429 failures throw;
   - the empty-path branch rejects with a message.

   In the picker:
   - `errEl` with `role=alert`;
   - `typed` carried across repaints (A5);
   - Enter through an `onkeydown` attribute (A6).

   In `showToast`: fall back to `ctx.emit('notify')` when `!st.open`, and have the cap-retry catch report its error (A7). Harness tests for the error text, the kept value, Enter, and the message without a "Failed to reach the server" wrapper.
4. **P1.4:** `handle.focus()` after `onForked` and after `_setRenderer`, guarded by `st.open`, no `topName()`, and focus already inside the shell (A9). In `ext_vt.js`, `XtermTerminal` gets `_wantFocus`, honoured in `_build` (A8). Source tests for both.

**Phase 2, terminal chrome**

5. **P2.1:** as planned.
6. **P2.2:** `el.status.hidden = !st.tty`. The `el.conn` chip is always written. Toast only on `reconnecting`, `disconnected` or `failed` (A11).
7. **P2.3:** `lineageBtn.hidden = !st.forked` only. Drop the `st.notice` change (A12).
8. **P2.4:** `st.rendererUser` is set on every switch and passed as `opts.renderer` (A13).
9. **P2.5:** as planned, at the current lines (A14).

**Phase 3, detail header**

10. **P3.1:** `.crd-row1-actions` moves to be the second child of `.crd-header` (A15), as a column holding row A (Search, Flag) and row B (Open terminal, "Resume here", Queue a note, External). The label hide and the iconbtn padding reset move from the ≤900 block to the ≤600 block (A16). Note the doc's label copy for the owner (A17).
11. **P3.2:** as planned, with the doc copy verbatim (A18). Raise A19 ("still running") with the owner separately.
12. **P3.3:** created rows show "created", edited rows "N edits", and neither shows a bare ±ops. Dir and base split so the dir is what gets ellipsed (A20).

**Decisions**

13. **D3(a), if approved:**
    - new tokens `--state-working-rgb` and `--text-working`;
    - dedicated `*-pulse-working` keyframes;
    - recolour the tile dot and its reduced-motion outline, the tile word, the triage count and underline, the state pill ink and border, the phone orb, and the agent-row dot;
    - the spine dot and `crd-pulse` stay wheat (A21-A23);
    - parity and contrast tests.
14. **D4:** record `aadcae5` as the ruling. No code (A24).
15. **D8:** defer (A25).
