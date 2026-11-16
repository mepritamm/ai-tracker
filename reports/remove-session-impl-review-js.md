# Remove-session: adversarial implementation review, front end (JS/CSS/T5)

Reviewer: opus, 2026-11-17. Scope: `aitracker/web/ext_cr_board.js` (new remove/undo block at `:2225-2291`, `railRow` `:2120` and `:2126`, `sessionTile` `:2993`, `buildShell` `:970-971`, `update()` `:3304`, `decorateSearchHits` `:1711`), `aitracker/web/ext_cr_board.css` (diff), `tests/test_cr_remove_session.py`. I edited no source or test file. Mutation runs used a throwaway copy in `/tmp/crmut.*`.

## Verdict

**No HIGH or MEDIUM defect.** The implementation matches v2 plus the v2 amendments F1-F6 and F8. The implementer's claim holds up. The sub-cases they had not red-proven (b, c, f, g, h, i, j, l, the `closest(UNDO_BLOCK_SEL)` clause) are **not vacuous**: each one goes RED when its feature is removed (table below). The gaps are in what the suite never tests, plus three cosmetic or defence-in-depth items.

## What I ran

| Check | Result |
|---|---|
| `node --check aitracker/web/ext_cr_board.js` | OK |
| CSS comment balance / brace depth (`ext_cr_board.css`) | 117 `/*` and 117 `*/`; brace depth 0 |
| `unset TRACKER_AUTH; python -m unittest tests.test_cr_remove_session` | 13 tests OK |
| `unset TRACKER_AUTH; python -m unittest tests.test_pending_ui_board` | 6 tests OK (the F1 ordering holds) |
| `test_cr_agent_map_entry`, `test_cr_board_resume_button`, `test_working_glow_board`, `test_cr_search_parity`, `test_cr_crossview` (one per process) | all OK |
| XSS sweep of the new code | clean. `h()` (`:787`) uses `setAttribute`/`createTextNode`. The new code interpolates no session id or title into `html:` or `innerHTML`. The toast title goes through `createTextNode` (`ext_cr_dialogs.js:283`). The ids reach only `JSON.stringify` bodies. |

### Mutation results (temp copy; each mutation applied alone, then `tests.test_cr_remove_session`)

| Mutation | Result |
|---|---|
| drop `e.stopPropagation()` in `removeBtn` | RED, b |
| drop the tile `!readOnly` gate | RED, c |
| drop the rail `!isReadOnly()` gate | RED, c |
| `rich &&` dropped | RED, a |
| `preventDefault()` moved before `undoLastRemove()` | RED, f |
| drop the stack `filter` on restore | RED, g |
| drop the R3 `sessionsSearchResults.forEach` flip | RED, h |
| drop `&& !known` | RED, i |
| drop the R5 `e.target === e.currentTarget` guard | RED, j |
| drop the F6 re-push | RED, l |
| drop the F6 error toast | RED, l |
| `closest(UNDO_BLOCK_SEL)` clause → `return false` | RED, e |
| drop the F5 dialog-layer line | RED, e |
| drop the F2 overlay in `update()` | RED, k |
| **drop `\|\| e.shiftKey`** | **green** |
| **drop `\|\| e.repeat`** | **green** |
| **drop `\|\| e.altKey`** | **green** |
| **drop `tag === 'TEXTAREA'`** | **green** |
| **drop `.vtpane` or `#vtmodal` from `UNDO_BLOCK_SEL`** | **green** |
| **drop the `nextRoot.hidden` early return** | **green** |

## Behaviour checks that held (no change)

- **Cmd+Z on macOS and Ctrl+Z on Linux/Windows both act.** The guard at `:2281` is `(e.metaKey || e.ctrlKey)`. Sub-case d covers `metaKey`+`'z'` and `ctrlKey`+`'Z'`.
- **Keys that must not act don't.** Cmd+Shift+Z and Ctrl+Shift+Z are refused by `shiftKey`. Ctrl+Y fails the `'z'/'Z'` key test. AltGr is ctrl+alt on Windows and is refused by `altKey`. Key repeat is refused by `e.repeat`. All of this is correct in the code, but none of it is tested (L1).
- **Terminals are excluded.**
  - Both terminal inputs are textareas: xterm's `.xterm-helper-textarea` and the grid renderer's `.vtinput`.
  - Every pane carries `.vtpane`: the grid pane (`ext_vt.js:805`), the xterm pane (`"vtpane vtxpane"`, `:1789`) and the probe panes.
  - The CR overlay lives in `#cr-term-root` (`ext_cr_boot.js:285`), and its focus is trapped inside it (`ext_cr_term.js:383-397`; the fallback focus target is the shell inside `#cr-term-root`).
  - In practice Ctrl+Z never reaches `undoLastRemove` from a terminal.
- **No other handler binds z.** `grep "key === 'z'|KeyZ|keyCode === 90"` across `aitracker/web/*.js` finds only the new line.
- **An open dialog blocks it.** The `.cr-dialog-layer[aria-hidden="false"]` check is at `:2286`. CR dialogs build that layer (`ext_cr_dialogs.js:367`).
- **`preventDefault` runs only when the handler acted** (`:2288-2289`).
- **Undo of an id already restored through search or the toast does nothing extra.** `postHidden(id,false)` filters the stack on success (`:2239`). A toast Undo on an id that Cmd+Z already restored re-POSTs `hidden:false`. The server's `mutate` returns False, so that is a harmless no-op.
- **The F2 overlay (`:3304`) hides only ids still on this page's stack.**
  - After an undo the id leaves the stack synchronously (pop), so the next poll shows the row if the server agrees.
  - After a reload the stack is empty and the server filter alone applies. That is correct.
- **Can the client hide a session the server says is visible?** Only in two cases, both accepted:
  - (a) Another tab restores it (an accepted edge, F2).
  - (b) The undo POST reaches the server but its response is lost, so the client re-pushes the id (F6) while the server has already un-hidden it. It stays hidden on this page until the next Cmd+Z (which re-POSTs and then succeeds) or a reload. It is self-healing and loses no data.
  - A failed un-hide POST re-pushes the id, and the server still has it hidden, so client and server stay consistent.
- **Toast text is exact.** The title is `'Session removed · ⌘Z / Ctrl+Z to undo'` = "Session removed · ⌘Z / Ctrl+Z to undo", and `actionLabel` is `'Undo'` (`:2249-2250`; asserted in b).
- **The button is correct.**
  - Labels: `aria-label` = `title` = "Remove from dashboard (log is kept)" or "Restore to dashboard".
  - `type="button"`, and `stopPropagation` runs on click.
  - It is JS-gated for read-only viewers in both the rail (`:2120`) and the tile (`:2993`).
  - It is absent from the compact rail, because `renderSessionRows` passes `rowOpts = null` (`:1331`).
  - It is present on every Board tile, and it turns into Restore on hidden search hits (`:1711` plus the R3 flip at `:2237`).
- **Load-order safety.** The JS parses. CSS comments and braces balance. There is no `*/` inside a string or a new comment that could close early. The new rule's comment at `:1813` is closed on the same line.
- **CSS.**
  - `.cr-rail-remove` is in all four rail-button lists.
  - The red hover rule sits after `.cr-tile-map:hover` (F8).
  - The tile button reuses the size, focus-visible and 32 px phone rules of `cr-tile-map`. No JS or test counts `.cr-tile-map`. The only test pin, `test_cr_agent_map_entry.py:254`, still matches.

## Findings

### L1 (LOW, test gap): the key-filter and blocklist guards are untested; deleting any of them stays green

- **Defect.** `tests/test_cr_remove_session.py:93-113` (sub-cases d and e) never dispatches `shiftKey`, `repeat`, `altKey`, a TEXTAREA, SELECT or contenteditable target, a target per `UNDO_BLOCK_SEL` entry, or a hidden `#nextRoot`.
  - The terminal probe at `:105` returns `{}` for any selector string that matches `/xterm|cr-term-root/`. It therefore passes as long as either of those two entries survives.
- **Repro.** Apply each mutation in the "green" rows above to `ext_cr_board.js:2281`, `:2272`, `:2276` or `:2285`. `tests.test_cr_remove_session` stays at 13 OK. In production that would mean:
  - Cmd+Shift+Z (redo) performs an undo;
  - a held Cmd+Z drains the whole stack;
  - Ctrl+Z in a terminal pane outside `.xterm`/`#cr-term-root` (classic `#vtmodal`, a `.vtpane` toolbar) is preventDefault'ed and restores a session.
- **Fix direction.** Test-only. Do **not** change `ext_cr_board.js`, because the code is correct.
- **The way.** Add a sub-case `m` to `_DRIVER` after `e`, with its own `await reset()`:
  1. Remove `s1` and flush, and record `n0 = fetched.length`.
  2. Dispatch each of these and collect the `pd` values:
     - `cmdZ(null,{shiftKey:true})`, `cmdZ(null,{repeat:true})`, `cmdZ(null,{altKey:true})`, `key({key:'y',ctrlKey:true,target:docBody})`;
     - `cmdZ({tagName:'TEXTAREA', className:'xterm-helper-textarea'})`, `cmdZ({tagName:'SELECT'})`, `cmdZ({tagName:'DIV', isContentEditable:true})`;
     - for each `X` in `['#cr-term-root','#vtmodal','#vtmgrmodal','.vtpane','.xterm']`, `cmdZ({tagName:'DIV', closest:function(sel){ return sel.split(',').map(function(s){return s.trim();}).indexOf(X) >= 0 ? {} : null; }})`.
  3. For the `nextRoot` probe, swap `document.getElementById` to return `{hidden:true}` for `'nextRoot'` and the original lookup otherwise, dispatch `cmdZ()`, then restore it.
  4. Assert that every `pd` is 0, `fetched.length === n0`, and a final plain `cmdZ()` returns 1 and POSTs `{session:'s1', hidden:false}` (so the stack was untouched).
- **Test that proves it.** Sub-case m itself. Each of the seven "green" mutations above turns it RED.

### L2 (LOW, defence in depth): the read-only CSS hide list omits the new buttons

- **Defect.** `aitracker/web/ext_cr.css:528-537` hides `.cr-rail-pin` and `.cr-rail-rename` (and other write controls) under `html.tracker-readonly`. The new buttons are gated only in JS at render time (`ext_cr_board.js:2120` and `:2993`).
- **Repro.** `trackerReadOnly` flips at `app.js:1322` on a `/api/list` response. Rows already rendered keep a Remove button until the next render. Clicking it gets a server 403 (the read-only deny-all) and the "Couldn't update the session." toast. No data changes.
- **Fix direction.** Add both classes to the existing list. Keep the JS gates. Do not add a new rule block.
- **The way.** In `ext_cr.css`, after `html.tracker-readonly .tracker-next .cr-rail-rename,` (`:536`), add `html.tracker-readonly .tracker-next .cr-rail-remove,` and `html.tracker-readonly .tracker-next .cr-tile-remove,`.
- **Test.** None needed (CSS, the same as its siblings). Alternatively, add a one-line source assertion in `test_cr_remove_session.py` that `ext_cr.css` contains `html.tracker-readonly .tracker-next .cr-tile-remove`.

### L3 (LOW, cosmetic): the error toast shows the success check glyph

- **Defect.** `ext_cr_board.js:2233` emits `{title:'Couldn’t update the session.'}` with no icon. `toast()` defaults to `glyph('check')` (`ext_cr_dialogs.js:281`), so a failure is shown with a green tick.
- This matches the `/api/pin` precedent (`ext_cr_boot.js:647`), which has the same flaw.
- **Fix direction.** Pass the existing alert icon on this one emit only. Do not touch the success toast or the pin precedent.
- **The way.** Use `ctx.emit('notify', { title: 'Couldn’t update the session.', icon: 'alert', iconClass: 'tn-emo-a' })`. This shape is already used at `ext_cr_dialogs.js:399`.
- **Test.** In sub-case l, capture `t.icon` of the error toast and assert `'alert'`. It is RED before the change.

### L4 (LOW, no change recommended): undo can act behind an open terminal overlay when focus is on `<body>`

- **What happens.** If a classic `#vtmodal` or `#vtmgrmodal` overlay is open and focus has dropped to `document.body` (for example after clicking non-focusable overlay chrome), Cmd/Ctrl+Z pops and restores a session out of sight.
- **Why it is low.** The keystroke would not have reached the PTY anyway, because the terminal is not focused, and the CR overlay traps focus inside `#cr-term-root`. Nothing is lost: the row reappears once the overlay closes.
- **Direction.** No change; document it. If it is ever reported, apply the plan's existing allowlist fallback ("Risky spot and fallback"): act only when `e.target === document.body || root.contains(e.target)`, and also return early when `document.querySelector('.cr-term-overlay.is-open')` matches or `#vtmodal`/`#vtmgrmodal` has `style.display === 'flex'`.

### INFO (no change)

- **A restore does not re-insert the row.** `postHidden(id,false)` calls `update(lastState)` on the already-filtered `lastState`, so the row returns only when `loadSide()` lands. That is immediate, or at most one 5 s poll while `sideBusy` is set. This is R6 as agreed.
- **Non-Latin layouts.** On a Cyrillic or Greek layout `e.key` is not `z`, so the shortcut does not fire. The toast Undo button and search Restore remain available. Adding `e.code === 'KeyZ'` would misfire on AZERTY and Dvorak, so no change.
- **The order-guard test is weak.** `test_bind_undo_key_registered_before_bind_keyboard` relies on `str.index` of the first `bindUndoKey();` and `bindKeyboard();`. Today each occurs exactly once (`:970-971`), so it holds. The real red proof is `test_pending_ui_board`, which still passes.
