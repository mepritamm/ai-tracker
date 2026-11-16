# Drift round 3: overall clean plan (PLAN + REVIEW-A + REVIEW-B, reconciled)

- Code SHA: **`adeb6fa`** (branch `worktree-control-room-drift`). Every `file:line` below was re-derived at this SHA with `grep -n` / `sed -n`. Paths are under `aitracker/web/` unless they say otherwise.
- Inputs: `PLAN.md` (lines from `76bd154`), `REVIEW-A.md` (A1–A25), `REVIEW-B.md` (B1–B26), audits `00`–`05`. Per-finding verdicts: `FINDINGS-EVIDENCE.md`.
- Precedence is unchanged: the docs win (`7b87cce`), and later owner rulings win over the docs: SVG icons (`3455c4d`), green Working (`89c2267`), board cap 3–12 (`7b87cce`), heartbeat default, session name as h1 and the Sessions pill (`5dea10f`), Now card above the spine (`89c2267`), timeline newest-first (`aadcae5`), and the pending-work worker, scheduler and in-app Update (`reports/pending-work-worker.md` C3/C8/C9).
- **Design-bundle source (new, load-bearing):** two copies of the bundle are on disk. `~/Downloads/design_handoff_control_room/` is the **older** copy: its `01-foundations.md` dark block differs from the code in 25 tokens. The current one is `~/Downloads/app-ui-redesign-request 2/project/design_handoff_control_room/`. Against that copy, `ext_cr.css` matches 47/47 light and 47/47 dark tokens (re-run at `adeb6fa`). Docs 02–05 are byte-identical between the two copies. Every doc citation here refers to the current copy.
- Hard constraints: stdlib only; edit `aitracker/web/*` and never `dist/`; the server owns policy; shared shape for both providers; one assertion per non-trivial change; `make check` stays green; restart the server to see UI changes.

---

## 1. Owner decisions

None of Phases 1–7 depends on an answer. Each answer is one small follow-up commit, or it folds into the named phase if it arrives before that phase lands.

### D1. Idle sessions on the board (02 N1)
- **Question:** doc 02:194 says "Idle sessions never get a tile." The code backfills the cap with recent idle sessions (`ext_cr_board.js:345` comment "as amended by the owner"). No ruling is recorded outside that comment.
- **Options:**
  - (a) Doc: no idle tiles.
  - (b) Keep the backfill and record it.
- **Recommendation: (b).** The backfill fixed a blank board (`317db79`), and an empty board most of the day reads as broken.
- **Code (a):**
  - Filter `state !== 'idle'` in `renderBoard` (`:2618`) and in the `t` handler that mirrors the screen (`:3117`). Do **not** filter inside `boardTiles()`: `computeTriage` (`ext_cr_boot.js:1029`) and `stepSession` (`ext_cr_detail.js:2163`) rank across it (B21).
  - Set `total` to the non-idle count.
  - Add the empty-state card.
  - Test in `tests/test_cr_board_order_and_empty.py`: 5 idle + 2 working give 2 tiles.
- **Code (b):** one paragraph in `reports/control-room-refinements.md`, and cite it in the comment at `:345`.

### D2. "Show all N" lifts the cap (02 N4)
- **Options:**
  - (a) Remove it, so the rail is the overflow, as doc 02:193 says.
  - (b) Keep it and record it.
- **Recommendation: (a)**, unless you use it. It is the one **user** toggle that lets the board exceed the cap you set. The Pending-work card also sits outside the cap (`:2632-2635`), but that one is owner-ruled (B22).
- **Code (a):**
  - Delete the `showAll` parameter, so `:430` becomes `matched.slice(0, boardTileCap())`.
  - Delete the footer button (`:3040-3046`), the `|| showAll` condition and its read (`:3008`, `:3040`), the reset (`:2527-2529`), and the `uiState` handler (`:3220-3221`). The `t` handler's 4th argument (`:3117`) goes too.
  - Leave the `uiState` key unread.
  - Test: the cap-footer source has no `'Show all '`, and `boardTiles` has 3 parameters.
  - **Red by design:** `tests/test_cr_crossview.py:302-350` (the show-all toggle test). Delete it or invert it in the same commit.
- **Code (b):** a ruling paragraph only.

### D3. Working colour is split (01 N4). Scope corrected by REVIEW-A
- **Question:** the rail dot, the orb pip and the pill **glow** are green (`--state-working` / `--glow-working`). Everything else that says "this session is Working" is still wheat:
  - the tile dot `ext_cr_board.css:1628` and its pulse `:1633-1638`;
  - the reduced-motion outline of that dot (`:1640-1644`);
  - the tile state word (`:1618`, `--text-thinking`);
  - the triage Working count and its active underline (`ext_cr_board.css:1348,1375`);
  - the detail **state pill**: ink `--text-thinking`, border `--line-agent`, wheat `crd-pulse` halo (`ext_cr_detail.css:135-141`). Only its glow is green;
  - the phone orb (`ext_cr_detail.css:1980-1985`).
- **Options:**
  - (a) Green for every session-state Working surface.
  - (b) Wheat everywhere, which reverts `89c2267`.
  - (c) Keep the split.
- **Recommendation: (a).** You asked for green, and the split reads as a bug.
- **What stays wheat under (a):**
  - The spine running dot `.crd-seg-dot` (`ext_cr_detail.css:681-686`) and the `crd-pulse` keyframe (`:727-731`) it shares. Doc 03 gives the spine the agent colour.
  - **The agent-row dots `.crd-state-dot.is-working` (`ext_cr_detail.css:1307`).** They mark background-agent rows (`ext_cr_detail.js:3011,3018,3041`), which is agent state, not session state. Both the plan and REVIEW-A swept them in. Keep them wheat unless you say otherwise.
- **Code (a):**
  - **Tokens** in `ext_cr.css`, both palettes:
    - `--state-working-rgb`: `28,145,99` light and `41,211,152` dark. This mirrors classic's `--st-working-rgb` (`app.css:80-81`).
    - `--text-working`, an ink for words. `--state-working` light `#1C9163` is only 3.98:1 on `#FFFFFF`, which is below the 4.5:1 text floor (A23). Pick a light value of at least 4.5:1 on both `--surface-raised #FFFFFF` and `--surface-agent-quiet #FBF3DC`, the pill's ground. Dark can reuse `#29D398`.
  - **Dots and fills** move to `var(--state-working)`: tile dot, reduced-motion outline, triage underline, phone orb border.
  - **Words** move to `var(--text-working)`: tile word, triage count, pill ink. The pill border moves to `var(--state-working)`.
  - **Keyframes:**
    - Recolour `cr-board-pulse` **in place** with `rgba(var(--state-working-rgb), …)`. Its only consumer is `.cr-tile-dot.is-working` (`:1638`), so REVIEW-A's second board keyframe is unnecessary.
    - Add `@keyframes crd-pulse-working` in `ext_cr_detail.css` for the pill and the phone orb only. `crd-pulse` stays wheat.
- **Tests:**
  - Extend `tests/test_state_color_parity_app.py`: CR `--state-working-rgb` equals the hex of `--state-working` in both palettes, modelled on `:301`.
  - Add a contrast check that `--text-working` reaches 4.5:1 or more on `#FFFFFF` and `#FBF3DC`, and on dark `--surface-raised`.
  - `.crd-seg-dot` still uses `crd-pulse`, which still contains `217,184,85`.
- **Red by design:** `tests/test_working_glow_detail.py:160` asserts the pill reuses `crd-pulse`. Retarget it to `crd-pulse-working`. Missed by both reviews.
- **Size:** about 30 lines CSS and 40 lines tests.

### D4. Timeline order: REMOVED, already ruled
`aadcae5` (2026-08-30) fixed an owner-reported defect, sent by screenshot: "It sorted OLDEST-first". It flipped the timeline to newest-first. `7b87cce` ranks docs over the prototype, not over owner reports. Record it as a ruling in 7.6. There is no code.

### D5. Three panels open by default (00 decisions 7, 9)
- **Recommendation:** keep (a), as is. A folded progress panel hides the thing the panel exists for.
- **Code (b):**
  - `OPEN_BY_DEFAULT = { timeline: 1 }` (`ext_cr_detail.js:325`).
  - The test must stub `localStorage` with `cr.cardsFolded` absent, because `defaultFolded()` (`:296-301`) returns false when it is set to `false` (B23).

### D6. Unruled extras: keep and record (a), or remove (b)
- **The items:**
  - PINNED as a fifth triage cell (`ext_cr_board.js:2509`).
  - The agent map: header, rail and tile buttons, and its dialog.
  - The model marker chip.
  - `?ui=next|classic` (`ext_cr_boot.js:1222-1226`).
  - Queue-a-note, the timeline chips and pop-out, the always-visible pin toggle, and the Evidence model/effort switchers.
  - Open/Resume hidden while a CLI is attached (`ext_cr_term.js:1153`).
  - The Sessions pill, which is already ruled by `5dea10f`.
- **Recommendation: (a).** One paragraph in `reports/control-room-refinements.md`.
  - Do **not** re-rule the Pending-work card, the scheduler or Update. Cite `reports/pending-work-worker.md` C3, C8 and C9 (B24).
  - Under (b), drop Help rows 72 and 73 in P4.2.

### D7. Classic `app.css`/`app.js` were changed
- **Recommendation:** (a) record the override. Reverting would split the palette again.
- Add the `adeb6fa` classic edits (the pending card in `app.js`, commits `2bca388` and `fe8f580`) to the list (B25).
- No code. Write the note in 7.6.

### D8. Detail orb rail contents and size (03 F3, N2, N3)
- **Recommendation: (b) defer.** It is the largest UI build here and has no correctness impact.
- If (a) is ever built:
  - pass `isDetail` into `renderCollapsedOrbs` (`ext_cr_board.js:1854`) instead of reading `.cr-rail--detail`, because that class is toggled separately at `:1139`;
  - keep the phone orb at 44px (`ext_cr_board.css:1990`) (A25).

### D9 (new). Help's privacy copy is false (B3, scope widened here)
- **Question:** `ext_cr_dialogs.js:660` says "Nothing is sent anywhere, and it never writes into a session." `:665` shows "**0** bytes leaving". `README.md:7` repeats "Nothing is sent anywhere." At `adeb6fa` bytes do leave:
  - "Check for updates" and Update run `git fetch` (`update.py:170-182`, and `:290` inside apply). This happens only on a press, per conventions rule 6's exception.
  - **The pending-work scan runs `gh pr list` against the GitHub API automatically.** That covers every scheduled run (`PENDING_INTERVAL`, default 90 days), plus Scan now and `make pending`, with at most 20 calls (`pending.py:32,622-660`; conventions rule 6's first exception). REVIEW-B missed this, so its proposed copy ("nothing leaves … unless you press Check for updates … or start a tunnel") is also false.
  - A tunnel serves the dashboard, session content included, to remote viewers.
  - "Never writes into a session" is also loose: Queue a note and the terminal inject into a live session. They never write the session **log**.
- **Options:**
  - (a) An accurate lede, with the stat relabelled.
  - (b) An accurate lede, with the stat removed.
- **Recommendation: (a).** It keeps the doc's stat row and makes it true.
- **Code (a):**
  - Lede: "It reads the session logs your tools already write and never edits them. Session content leaves this machine only if you start a tunnel. Two things contact the network: Check for updates (a `git fetch` of this checkout's upstream, only when you press it) and the pending-work scan (a few read-only `gh pr list` calls to GitHub per scan)."
  - Stat label: `bytes of session logs sent (no tunnel)`.
  - `README.md:7`: the same qualification in one sentence.
  - Test: a source slice of `helpCoverageTab` contains `git fetch` and `gh pr list`, and does not contain `Nothing is sent anywhere`. Red at HEAD. No test pins the old copy (grepped).
  - Lands in **P4.3** if answered before Phase 4.

### D10 (new). Fork banner says "the original is still running" forever (A19)
- **Question:** the doc copy (doc 03:97) and HEAD (`ext_cr_detail.js:2589-2590`) both state it unconditionally. Doc 03:99 says "never guess".
- **Options:**
  - (a) The doc copy verbatim, always.
  - (b) Keep the clause only while the parent's list row is live; otherwise say "the original has since stopped".
- **Recommendation: (b).** It is the doc's own "never guess" rule applied to the doc's own copy.
- **Code (b):**
  - In `renderForkBanner`, look up the parent in the same `sessions` list that `forkSessionLabel` already scans (`:2565-2570`).
  - Live means `(now - row.mtime) < LIVE_WINDOW`, the same predicate as `sessionState` (`ext_cr_board.js:82-83`) and the server-served `LIVE_WINDOW`. Do not re-derive any other threshold.
  - Node test: a non-live parent row leaves out "still running".
  - Lands in **P3.2**.

### D11 (new, LOW). Header pill labels (A17)
- **Question:** doc 03:88 labels them "Search this session" and "Flag an issue · N". The code says "Search" and "Flag" (`ext_cr_detail.js:1378-1379`). The `title` and `aria-label` already carry the long form.
- **Options:**
  - (a) Doc copy.
  - (b) Keep short.
- **Recommendation: (a).** P3.1 gives Search and Flag a row of their own, so the room exists. The `· N` is the existing `.crd-flag-badge`.
- **Code (a):** change the two `.crd-btn-label` texts. Test: the source contains `>Search this session<`. Lands in P3.1.

### Calls you may want to overrule in the phased work
- **P3.1** restores the doc's separate actions column with two rows. **P3.2** moves the fork banner out of Evidence. Both reverse "HTML-wins" layouts that `7b87cce` superseded.
- **P6.1** makes the gate fail without `node`. A commit from a GUI git client with launchd's PATH would be blocked. An escape hatch (`TRACKER_GATE_NO_NODE=1`) is offered only if you commit that way (B10).

---

## 2. Phases (one commit each)

Test conventions:
- Source-slice tests follow `tests/test_cr_manage_terminals_parity.py`.
- Node-exec tests follow `tests/test_cr_logic.py` and the picker harness at `tests/test_cr_manage_terminals_parity.py:355-440`.
- Every test is proved RED by reverting its fix with a scoped Edit.

### Phase 1: terminal correctness

**P1.1 Esc and keys pass through a dialog to the terminal and the board.** Closes 05 N3; A1, A2, plus one gap missed by both.
- **Mechanism (A1, confirmed):**
  - `ensureMounted` mounts dialogs (`ext_cr_boot.js:956`), then term (`:957`), then board (`:963`).
  - All three keydown listeners are on `document`, in bubble phase.
  - `onDocKeydown` (`ext_cr_dialogs.js:354-361`) pops the dialog and calls `preventDefault()`.
  - The terminal listener (`ext_cr_term.js:243-245`) then closes the terminal.
  - The board listener (`ext_cr_board.js:3078-3097`) then clears the active filter or closes the rail overlay.
- **Missed by both:** with a dialog open, `j`, `k` and `t` still reach the board. Dialog buttons are not `isTypingTarget` (`:3051-3058`), so `j` moves focus out of the dialog to a tile behind it, and `t` opens a terminal.
- **Code, terminal (`ext_cr_term.js:243-245`):**
  ```js
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape" || ev.defaultPrevented || !overlay.classList.contains("is-open")) return;
    var d = window.CR && window.CR.dialogs;
    if (d && typeof d.topName === "function" && d.topName()) return;
    ev.preventDefault();
    close();
  });
  ```
- **Code, board (`bindKeyboard`, `:3079`):** the first lines are
  ```js
  if (e.defaultPrevented) return;
  var dlg = window.CR && window.CR.dialogs;
  if (dlg && dlg.topName && dlg.topName()) return;
  ```
  `defaultPrevented` covers Esc, because the stack is already empty by then. `topName()` (`ext_cr_dialogs.js:3109`) covers the other keys.
- **Tests:** new `tests/test_cr_term_drift3.py`.
  - `test_overlay_escape_yields_to_dialogs`: the `_build` slice has `defaultPrevented`, `topName` and `preventDefault` in the Escape listener.
  - `test_board_keys_yield_to_dialogs`: in the `bindKeyboard` slice, `defaultPrevented` and `topName` come before `'Escape'` and `'j'`.
  - Both are red at HEAD.
- **Browser:** run with focus on the dialog, not the pane. The engines swallow keys while the pane is focused (`ext_vt.js:1138-1144`).
  - Terminal, then Manage, then Esc: only Manage closes. Esc again closes the terminal.
  - Board with the Working filter, then Help, then Esc: Help closes and the filter stays.
  - Help open, press `j`: focus stays in Help.
- **Risky spot:** a dialog whose `onEscape` returns true still calls `preventDefault` (`:358`), so the terminal yields correctly there too.

**P1.2 The xterm notice is invisible under the engine.** Closes 05 N2; A3.
- **Defect:**
  - `mountInto` appends `.vttermwrap` after `.cr-term-pane-blank` (`ext_vt.js:3666-3668`). The blank node is built first, at `ext_cr_term.js:207`.
  - Both are absolutely positioned at `inset: 0` (`ext_cr_term.css:294-312`) and neither has a z-index.
  - The opaque `.vtpane` (`background: var(--app)`, `ext_vt.css:94`) paints over the notice.
  - The notice also shows when no engine exists at all (`ext_cr_term.js:943`).
- **Code:**
  - CSS `.cr .cr-term-pane-blank`:
    - `inset: auto 0 0 0` (a bottom strip; the top holds the engine's A−/A+ toolbar);
    - `z-index: 2` (the toast is at 5, `:415`);
    - `background: #1F1B16`, dropping `rgba(18,16,14,.82)`;
    - keep `pointer-events: none`.
  - `_setRenderer` (`ext_cr_term.js:928-945`): `el.blank.hidden = !(st.engineHandle && next === "xterm");`, then `clearTimeout(st.blankTimer)`, and when shown, `st.blankTimer = setTimeout(function(){ el.blank.hidden = true; }, 8000)`.
  - `_build`: add `pane.addEventListener("keydown", hideBlank, true)` and the same for `pointerdown`.
  - `_resetPaneChrome` (`:427`) clears the timer.
  - Rewrite the stale NOTE at `:938-942`.
- **Tests:**
  - `test_blank_notice_is_a_strip_above_the_engine`: the CSS block has `z-index` and has neither `inset: 0;` nor `.82`.
  - `test_blank_notice_only_with_engine_and_clears`: the `_setRenderer` line that sets `el.blank.hidden` references `st.engineHandle`, the body has `setTimeout`, and `_build` registers a capture listener.
- **Browser (mandatory, 1280):** grid → xterm shows the strip, and a key clears it.

**P1.3 A failed spawn closes the picker and loses the path; Enter does nothing.** Closes 05 N7, N6; A4, A5, A6, A7.
- **`_pickDirectory` (`ext_cr_term.js:625-662`):**
  - Attach the network handler to the fetch only: `post(...).catch(function (e) { throw new Error("Failed to reach the server: " + (e && e.message || e)); }).then(j).then(function (res) { … })`. The trailing catch at `:661` would otherwise wrap the server's own message (A4).
  - Every non-429 failure does `throw new Error(msg)` instead of `showToast(…); return;` (`:649-653`).
  - The empty-path branch (`:630`) rejects with `new Error("Choose or type a directory first.")` and does not toast.
  - 429 stays as it is.
  - The cap-retry catch (`:640`) becomes `.catch(function (e) { showToast(e && e.message || String(e)); })`.
- **`showToast` (`:107-113`):** `if (!st.open && ctx && typeof ctx.emit === "function") { ctx.emit("notify", { text: msg }); return; }`. From the board's "+ New session" (`ext_cr_boot.js:501-505`) the overlay is `display:none` (`ext_cr_term.css:22-32`), so the success toast, "Popup blocked" (`:660`) and retry failures were invisible (A7).
- **Picker (`renderDirectoryPicker`, `ext_cr_dialogs.js:2363-2452`):**
  - `var typed = ''` and `var errEl = null` live beside `busy` (`:2381`), outside `paint()`. `paint()` empties the body and rebuilds the input (`:2391`, `:2426`), and the cwds re-open runs it mid-flight, so the value is lost today (A5).
  - The input is `h('input', {…, value: typed, oninput: function () { typed = input.value; }, onkeydown: function (e) { if (e.key === 'Enter') { e.preventDefault(); var v = input.value.trim(); if (v) submit(v, go); } } })`. Use `on*` attributes because the harness mock `h()` has no `addEventListener` (A6). Declare `go` before `input`, or resolve it lazily inside the handler.
  - `submit(path, …)` also sets `typed = path`.
  - `release(err)` builds or updates `errEl = h('p', {class:'cr-help-note cr-picker-error', role:'alert'}, [err && err.message || String(err)])` and appends it to the current body. `paint()` re-appends `errEl` when it is set.
- **Tests:** extend the node harness at `tests/test_cr_manage_terminals_parity.py:355-440`.
  - **Harness tweak (missed by both):** the mock `h()` (`:365-371`) must copy `attrs.value` to `node.value`, or the kept-value assertion cannot pass even with the fix.
  - Type `/tmp/proj` and fire `attrs.oninput()`, Start, `update()` with cwds, then reject with `Error('boom')`. Assert:
    - `closed === 0`;
    - `findInput().value === '/tmp/proj'`;
    - a `cr-picker-error` node holds `boom`.
  - `findInput().attrs.onkeydown({key:'Enter', preventDefault(){}})` with a value set calls `onPick` once.
  - Source slices:
    - in `_pickDirectory`, the first `.catch(` comes before `.then(j)`;
    - `showToast` references `st.open` and `"notify"`;
    - the retry `.catch` body is not empty.
  - All red at HEAD.
- **Risky spot:** only the three `onPick` sites call `_pickDirectory`. Grep before landing.

**P1.4 The terminal never takes focus.** Closes 05 R1 2.4; A8 (mechanism confirmed, fix replaced) and A9 (mechanism wrong, guard kept).
- **Facts:**
  - xterm builds asynchronously (`ext_vt.js:1814-1820`), and its `focus` is a no-op until `this.term` exists (`:2009-2011`).
  - `onForked` fires synchronously in `finish()` (`:3812-3813`), so calling `handle.focus()` there does nothing for xterm.
  - A9's "2.6 s refused-resume delay" is wrong. `/api/term/open` answers immediately (`term_vt.py:3346`) and the backstop runs on a thread (`:3651`).
  - The real late window is the asset load, which is also when a user could open a dialog.
- **Code (CR-side only, no `ext_vt.js` edit):** both engines emit `"connected"` once the stream is open and the term exists (`ext_vt.js:949,990,1968`).
  - In the attached branch of `onStatus` (`ext_cr_term.js:491-493`): `if (text === "connected" && !st.focusDone) { st.focusDone = true; _focusPty(); }`.
  - `_focusPty()`: `if (!st.open || !st.engineHandle) return; var d = window.CR && window.CR.dialogs; if (d && d.topName && d.topName()) return; if (document.activeElement && !el.shell.contains(document.activeElement) && document.activeElement !== document.body) return; st.engineHandle.focus();`
  - Reset `st.focusDone` in `_resetPaneChrome` and in `_setRenderer`. A switch rebuilds the engine, which emits `connecting…` and then `connected` again.
- **Test:** the attached-branch slice contains `"connected"` and `_focusPty`, and `_focusPty` contains `topName` and `activeElement`. Red at HEAD.
- **Browser:** open with each renderer and type without clicking. Open Config during an xterm first load: focus stays in Config.
- **Risky spot:** if the grid switch does not re-emit `connected`, call `_focusPty()` directly after `setRenderer` for `next === "grid"`. Grid builds synchronously.

Phase 1 diff: about 95 lines JS and CSS, plus about 120 lines of tests.

### Phase 2: terminal chrome honesty

**P2.1 Hide the engine's duplicate renderer and theme buttons.** Closes 05 N1; A10.
- Add `.cr .cr-term-pane .vtrendererbtn, .cr .cr-term-pane .vtthemebtn { display: none; }` to `ext_cr_term.css`. The classes come from `ext_vt.js:527,654`.
- A−/A+ and mouse stay. No `ext_vt.js` edit.
- Test: the CSS rule exists.

**P2.2 The status bar stays while attached; the connection state is a chip, not a red toast.** Closes 05 N11, N5; A11.
- **Code:**
  - `_syncStatusBar` (`:1177-1178`): `el.status.hidden = !st.tty;`, and drop `hasAnything`.
  - Add `<span class="cr-term-conn cr-mono" data-el="conn" hidden></span>` first in `.cr-term-status-right` (`:219`), with its ref in `el` (`:249`).
  - Attached branch (`:493`): `el.conn.textContent = text; el.conn.hidden = false; if (/^(reconnecting|disconnected|failed)/.test(text)) showToast(text); return;`. The toast is failure-styled (`ext_cr_term.css:410-415`), and "connecting…" and "connected" toast on every open today.
  - Then apply P1.4's `connected` hook.
  - `_resetPaneChrome` hides the chip.
- **Test:** the attached-branch slice writes `el.conn`, `showToast` is behind the regex, and `hasAnything` is absent. Red at HEAD.

**P2.3 "See lineage" only for a real fork.** Closes 05 N4 (cheap part); A12.
- Add `lineageBtn: notice.querySelector('[data-action="lineage"]')` (markup `:197`) to `el`.
- `_syncNotice` (`:1182-1185`) gains `el.lineageBtn.hidden = !st.forked;`. The missing-transcript notice (`term_vt.py:2831-2837`) is not a fork.
- **Dropped:** the plan's `st.notice = handle.notice || st.notice`. `handle.notice` is set before `fireForked` (`ext_vt.js:3811-3814`), so nothing is wiped. The test for it asserted a literal with no behaviour behind it.
- Test: `_syncNotice` references `st.forked`.

**P2.4 Keep the user's renderer choice.** Closes 05 N10; A13.
- `_setRenderer` sets `st.rendererUser = next` on **every** call.
- The mount (`:487`) passes `st.rendererUser ? { renderer: st.rendererUser } : {}`. `mountInto` honours it (`ext_vt.js:3664,3893`).
- `_resetPaneChrome` keeps it.
- Test: the mount slice references `rendererUser`, and so does the `_setRenderer` body outside any `engineHandle` guard.

**P2.5 Picker rows show the path; Manage rows have names.** Closes 05 N8, N9; A14.
- Picker rows (`ext_cr_dialogs.js:2405-2418`) get children `[label, h('span',{class:'cr-mono cr-picker-path', text: path})]` when `label !== path`.
- Manage rows (`:2241-2262`):
  - the title gets `t.tty + ' · ' + (t.cmd || 'shell') + ' · ' + (t.cwd || '')`;
  - `peekBtn` (`:2243`) gets `'aria-label': 'Peek ' + titleText`;
  - `killBtn` (`:2244`) gets `'aria-label': 'Kill ' + titleText`.
- Tests: in the harness, the row's children include the path. A source slice finds `aria-label` in the Manage builder.

Phase 2 diff: about 45 lines, plus about 60 lines of tests.

### Phase 3: detail header, fork banner, files

**P3.1 Actions become their own column with two rows.** Closes 03 F1, F8, N15; A15, A16; D11 if (a).
- **Skeleton (`ext_cr_detail.js:1352-1386`):**
  - Close `.crd-id-row1` after `crd-pill-agents` (`:1368`).
  - Emit `<span class="crd-row1-actions">` as the **second child of `.crd-header`**, after `.crd-id`'s `</div>` and after `.crd-id-row2`. It holds two rows:
    - `<span class="crd-actions-row crd-actions-a">` with toggle-search and toggle-flag;
    - `<span class="crd-actions-row crd-actions-b">` with open-terminal, resume "Resume here", toggle-note and external.
  - Keep the class name, so `qsa(".crd-row1-actions .crd-iconbtn .crd-ico")` (`:2510`) and the click delegation still match.
  - Delete the stale "FIX (design-audit drift 2)" comment (`:1369-1376`).
  - No `data-act` is renamed.
- **CSS (`ext_cr_detail.css`):**
  - `.crd-row1-actions` (`:348-354`): drop `margin-left:auto`; add `flex-direction: column; align-items: flex-end; gap: 8px; flex: 0 0 auto`.
  - Add `.crd-actions-row { display:flex; gap:7px; flex-wrap:wrap; justify-content:flex-end }`.
  - From the ≤900 block (`:1843-1862`), **move both** `.crd-row1-actions .crd-btn-label {display:none}` and `.crd-row1-actions .crd-iconbtn {padding:0; gap:0}` into the ≤600 block (`:1885`). Leave the `.crd-id-row2` Rename/Pin degrade at ≤900.
  - The ≤1024 rule `.crd-row1-actions { width:100% }` (`:1799`) already stacks it under the identity. Add `align-items: flex-start` there.
- **Tests:** new `tests/test_cr_detail_drift3.py`.
  - The skeleton text between `crd-id-row1` and `crd-id-row2` has no `crd-row1-actions`.
  - `crd-actions-a` contains toggle-search and toggle-flag but not open-terminal.
  - The resume text is `Resume here`.
  - The ≤900 block has neither moved rule, and a ≤600 block has both.
  - Re-run `tests/test_cr_detail_action_row_responsive.py`. It still passes, because "Resume" is a substring of "Resume here" (`:103`).
- **Browser:** 1440, 1280, 1024, 900, 600 and 390. Two rows, nothing clipped, and the h1 is not pushed down.

**P3.2 Fork banner, full width, above the Now card.** Closes 03 F2 (1.8, 1k, 1l, N6); A18; D10.
- **Code:**
  - Delete the card block (`ext_cr_detail.js:1625-1634`).
  - Add `<div class="crd-forkbanner" hidden>…same four children…</div>` to the skeleton just before `'<div class="crd-now" hidden></div>'` (`:1466`). That is outside `.crd-columns` (`:1498`), so it is full width.
  - Set `ui.forkCard = qs(node, ".crd-forkbanner")`.
  - `renderForkBanner` (`:2572-2597`) falls back to `.crd-forkbanner`.
- **Copy:** the doc copy, verbatim, is safe. Lineage comes only from `store.record_fork`, which is called only from `_retry_with_fork` after the background-agent refusal (`term_vt.py:2499,2556,2838-2839`). So there is no fallback branch.
  - Copy side: "Resume was refused — this session was running as a background agent, so it was forked. You're looking at the copy; the original is still running." Link: "Open the original". The last clause follows D10.
  - Parent side: "A fork of this session continued the work — " + `forkSessionLabel(…)`. Link: "Open the copy".
- **CSS:**
  - Rename `.crd-forkcard` (`ext_cr_detail.css:549-564`) to `.crd-forkbanner`, with `margin:14px 26px 0; padding:11px 15px; background:var(--surface-provenance); border:1px solid var(--line-default); border-left:2px solid var(--line-dusk); border-radius:4px`.
  - Phone (≤600): `margin:10px 12px 0`.
- **Tests:**
  - The skeleton index of `crd-forkbanner` is lower than that of `crd-now`.
  - `crd-forkcard` is absent from the JS.
  - "Resume was refused" is present.
  - The D10 node test.
  - No existing test pins the old copy (grepped).

**P3.3 Files row: honest counts, and the basename is never cut.** Closes 03 F7; A20.
- `renderFiles` (`ext_cr_detail.js:2896-2917`):
  - Created rows show `created`, plus ` · N edits` when `ops > 1`.
  - Edited rows show `N edit(s)`.
  - No bare `±ops` anywhere. `ops` is an edit-call tally (`:764-767`; `claude.py:1988-1989`; `auggie.py:429`), the same shape for both providers.
  - The path becomes `<span class="crd-file-dir">dir/</span><span class="crd-file-base">base</span>`.
- CSS (`:1251-1260`):
  - `.crd-file-path { display:flex; min-width:0 }`;
  - `.crd-file-dir { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }`;
  - `.crd-file-base { flex:0 0 auto; font-weight:500 }`;
  - `.crd-file-edited` moves from `--text-failed` to `--text-secondary`.
- Test: the `renderFiles` source has neither `'+' + (f.ops` nor `'−' + (f.ops` and does have `crd-file-base`. The CSS gives `.crd-file-base` `flex: 0 0 auto`.

Phase 3 diff: about 80 lines, plus about 60 lines of tests.

### Phase 4: Help and Config honesty

**P4.1 Data files shows the real files.** Closes 04 N6; B1.
- **Server** (`server.py`, the GET `/api/config` branch `:482-500`, before `self._json(snap)`):
  ```python
  files = {"flags": config.FLAGS_FILE, "titles": config.TITLES_FILE, "pins": config.PINS_FILE,
           "notes": config.NOTES_FILE, "model_keep": config.MODEL_KEEP_FILE,
           "title_sync": config.TITLE_SYNC_FILE, "forks": config.FORKS_FILE,
           "pending": config.PENDING_FILE, "config": config.CONFIG_FILE}
  local = _local_caller(self)[0]
  snap["DATA_FILES"] = {k: (v if local else os.path.basename(v)) for k, v in files.items()}
  ```
  - Never include `TOKEN_FILE` or `PORT_FILE` (`config.py:67,73`).
  - Basenames for remote callers are consistent with `/api/update`. Do **not** call this closing a leak: `cwd` in `/api/list` (`claude.py:952`, `auggie.py:371`) and the OpenRouter paths already reach remote viewers. That is a known gap, unchanged.
- **Client** (`ext_cr_dialogs.js:1759-1764`):
  - Replace the dead `srv.dataFiles` read (it is never assigned) with `var df = (srv.cfg && srv.cfg.DATA_FILES) || {};`. `srv.cfg` is set at `:1404` and `:1781`, so no new mirror field is needed.
  - Iterate the nine keys. Use `'—'` when there is no data, never a guessed name.
  - Per-key hints: `config` gets "Read on each Config open; Port/Host/Terminal need a restart"; `pending` gets "Written by the pending-work scan; read-only"; the rest keep "Read live …".
- **README `:214`:** add `forks.json` and `pending.json`.
- **Tests:**
  - `tests/test_cr_routes.py`: a local GET returns exactly the nine keys, every value is absolute, and no basename is `token` or `port`.
  - `tests/test_tunnel_readonly.py`, using `_RO.get(path, proxied=True)` (`:76`), with `ro(True)` and `ro(False)`: every value has no `/`.
  - Red at HEAD.

**P4.2 Capability table rows 62–76.** Closes 04 N10; B2.
- Append the plan's rows 62–73, plus:
  - `[74,'Pending-work card + scan now','board+dialogs']`
  - `[75,'Scheduled scan install/uninstall','dialogs']`
  - `[76,'In-app update and restart','dialogs']`
- Append them after `[61,…]` at `ext_cr_dialogs.js:566`. Compound owners are safe because the table renders only counts.
- `tests/test_capability_table.py:248` becomes 76 (74 if D6(b) drops 72 and 73). Update its docstring.

**P4.3 Help privacy copy.** Closes B3 and the `gh` gap. This is D9(a). If D9 is still open when Phase 4 lands, ship it as the D9 follow-up.

**P4.4 Live-window slider: 1–15 min.** Closes 04 N1; B4.
- `ext_cr_dialogs.js:1502-1506`: `sliderCtlCommit(1, 15, Math.max(1, Math.round((value != null ? value : 300) / 60)), function (m) { onCommit(m * 60); }, ' min')`. The label is unclamped, so a stored 3600 reads "60 min", not an invented "15 min" (`sliderCtlCommit` prints `String(value)`, `:1083`).
- Copy: append "The slider covers 1–15 min; env or config.json accept 5 s–24 h."
- Test: in the `tests/test_cr_dialogs_config_exec.py` harness (the `fire('change')` pattern, `:83`):
  - min is 1 and max is 15;
  - change to 7 POSTs 420;
  - `LIVE_WINDOW:{value:3600}` gives the label `60 min`.
  - Red at HEAD.

**P4.5 Server tab: the bound port and host, never literals.** Closes 05 N14; B5.
- Server (after `snap["OPENROUTER_CONFIGURED"]`): `bh, bp = self.server.server_address[:2]; snap["PORT"] = dict(snap["PORT"], value=bp); snap["HOST"] = dict(snap["HOST"], value=bh)`. `run()` moves to the next free port (`server.py:1019-1040`), and `cli.py:42-43` binds from env, so `resolve_port()` is not what is running.
- Client (`ext_cr_dialogs.js:1590,1592`): fall back to `'—'` instead of `8790` and `'127.0.0.1'`.
- Tests:
  - `tests/test_cr_routes.py`: `PORT.value == self.port`. The port is ephemeral (`:180`), so this is red at HEAD.
  - A source slice of the Server tab has neither `: 8790` nor `'127.0.0.1'`.

**P4.6 Local-only refusals talk about the panel, not a terminal.** Closes B6.
- `server.py:470`, `:479` and `:662`: return `{"error": "available only on the tracker's own machine", "local_only": True}` with status 403. Leave `_local_caller()` and `_NOT_LOCAL` (`:212`) alone, because the terminal routes rely on them.
- Test: `test_tunnel_readonly.py` with `ro(False)`: proxied `GET /api/update` gives 403, and `error` has no `terminal`.

Phase 4 diff: about 25 lines Python, about 45 lines JS, plus about 90 lines of tests.

### Phase 5: board tiles

**P5.1 A flagged tile shows the flag text.** Closes 02 N2, 04 R1-#7; B7.
- `tileLine` (`ext_cr_board.js:2855-2867`): `var nowLine = (state === 'flagged' && s.flag_text) ? String(s.flag_text).trim() : ((typeof s.now_line === 'string') ? s.now_line.trim() : '');`. Use it in both the no-headline branch (`:2859`) and the headline `sub` (`:2864`).
- `flag_text` is on the list shape for every provider (`registry.py:97`).
- Rewrite the round-5 comment (`:2832-2847`), which says the opposite.
- Test: in the `tests/test_cr_board_order_and_empty.py` real-DOM harness, a flagged session with `flag_text:'Pushed note stuck'` and `now_line:'x'` puts the flag text in `.cr-tile-line`, both without and with a `headline`. Red at HEAD.

**P5.2 Hero side rail: ticks move there, and a failing count is added.** Closes 02 N3 (partial); B8.
- In `sessionTile` (`:2880-2965`):
  - When `t.hero` is true, do not push `ticks` (`:2932-2933`) into `body`. Put it first in the sidebar (`:2949`).
  - Add `(live && s.fail_cmd) ? h('div',{class:'cr-tile-counts'},[glyph('x','tn-emo-f'),'1 failing']) : null`, with `var live = (now - (s.mtime || 0)) < LIVE_WINDOW`. That is the same predicate as `sessionState` (`:82-85`).
  - Replace the stale NOTE (`:2945-2948`) with the deferred `files_n` note.
- `countRow()` does not exist, so it is not used.
- Test: in the harness, a hero with `todo_total:3` has `.cr-todo-ticks` inside `.cr-tile-sidebar` and not inside `.cr-tile-main`. A live hero with `fail_cmd` shows `1 failing`. Red at HEAD.

**P5.3 The back button's title and aria-label match.** Closes 02 N9; B9.
- `:2323`: `'aria-label': 'Classic dashboard'`. No test pins the old string.

Phase 5 diff: about 25 lines, plus about 50 lines of tests.

### Phase 6: gate hardening (tests only)

**P6.1 Fail when node is absent.** Closes 00 §5 gap 1; B10.
- Add `test_node_available` to `tests/test_page_bundle.py`, next to `:24`. Keep the existing `skipUnless` decorators.
- Proof: `PATH=/usr/bin:/bin /usr/bin/python3 -m unittest tests.test_page_bundle`. There is no `python` on that PATH.

**P6.2 Assert the ExtVT exports.** Closes 00 gap 2; B11.
- `_JS_EPILOGUE` (`tests/test_page_bundle.py:176-195`) also requires `window.ExtVT && typeof ExtVT.mountInto === 'function' && ExtVT.term` (`ext_vt.js:3912,3936`).
- Proof: rename `:3912` and the test goes red.
- Known gap, document it in the PR: errors in listener-registered or deferred init stay invisible, because the harness stubs `addEventListener` and `setTimeout`.

**P6.3 The CSS comment check follows browser semantics.** Closes 00 gap 3, P6.3; B12. Replaces the plan's first/last-selector approach.
- In `test_comments_are_balanced` (`tests/test_page_css.py:195-224`), replace the nesting depth walk with:
  - `clean = _strip_css_comments_and_strings(css)` (sequential, non-nesting, `:44`);
  - `assertNotIn('*/', clean)`;
  - plus an unclosed check: a `/*` with no later `*/`, using the stripper's skip-to-end branch.
- HEAD has zero leftover markers (verified), so it is green today.
- Fix the misleading comment at `:291`.
- Leave `test_no_premature_comment_terminators` (`:157`).
- Proof:
  - a stray `*/` in `ext_cr_term.css` goes red;
  - the cancelling pair (an unclosed `/*` at the end of `ext_cr_detail.css` plus a stray `*/` at the end of `ext_cr_term.css`) is green on the old walk and red on the new one.

**P6.4 Pin the doc tokens.** Closes 00 non-negotiable; B13, plus the bundle-copy finding.
- New `tests/fixtures/cr_tokens_doc.css`: the two fenced blocks copied verbatim from **`~/Downloads/app-ui-redesign-request 2/project/design_handoff_control_room/01-foundations.md`**, `.tracker-next {` at `:38` and `.tracker-next.is-dark {` at `:113`. **Not** from the older `~/Downloads/design_handoff_control_room/` copy, which differs from the code in 25 dark tokens and would make the test red against correct code.
- New `tests/test_cr_tokens_doc.py`:
  - merge **every** `.tracker-next {` block in `ext_cr.css` (`:38`, `:431`) and the `.tracker-next.is-dark {` block (`:316`);
  - assert every doc token is equal after whitespace and case normalisation;
  - extras are allowed;
  - add a `RULED = {}` map from token to owner commit.
- Proof: set the dark `--surface-raised` to `#6E3711` and the test goes red.
- Re-run at `adeb6fa`: 47/47 and 47/47 equal.

**P6.5 Pin the remaining pure functions.** Closes 00 non-negotiable 4; B14.
- In `tests/test_cr_logic.py`:
  - `stateOf` (`ext_cr_detail.js:971`): add only the unpinned `flagged`, `done` and `idle` cases, asserted on `.cls`. Idle is `NOW - LIVE_WINDOW - 1`. `failed` and `awaiting` are already pinned (`:435-445`, `:1060`), and so is `working` (`tests/test_working_glow_detail.py`).
  - `firstEventTime` (`:482`): returns the minimum, with the oldest entry placed last in newest-first arrays and a `decisions` entry as the minimum; returns null when everything is empty.
  - Fix the docstring at `:17-23`.
- Proof: stub `firstEventTime` with `return null`.

**P6.6 Pin the CR `/api` surface by literal.** Closes 00 non-negotiable 1; B15.
- In `tests/test_cr_readonly_ui.py`: `set(re.findall(r"""['"](/api/[a-z_/-]+)""", js_without_line_comments))` across `ext_cr_*.js` equals a pinned set. The set is **34** literals at `adeb6fa` (re-run): agent, config, diff, flags, flags/delete, flags/resolve, model-keep, narration, notes, notes/delete, output, pending/run, pin, scheduler, search, session, shell, term/{attached, close, cwds, inject, kill, list, open, pty, run, stream}, title, tunnel, tunnel/ctl, tunnel/reveal, update, update/apply, update/fetch.
- Mark the write subset in a comment.
- In the PR, amend non-negotiable 1 to name `update/apply` and `pending/run`.
- Proof: add `'/api/dummy'` and the test goes red.

Phase 6 diff: about 170 lines of tests and fixture.

### Phase 7: LOW polish and records

- **7.1 Rail search focus ring** (01 N12; B16).
  - `.tracker-next .cr-rail-search:focus-within { outline: 2px solid var(--line-focus); outline-offset: 2px; }` near `ext_cr_board.css:740`. The input's `outline:none` (`:744`, specificity 0,2,1) beats the global `:focus-visible` (`ext_cr.css:456`).
  - It also covers the Sessions search (`ext_cr_board.js:914`).
  - CSS-regex test.
- **7.2 Phone spine labels at ≤600** (03 F12; B17).
  - Move `.crd-spine-hint, .crd-seg-elapsed, .crd-seg-running-elapsed {display:none}` from the 480 block (`ext_cr_detail.css:2112-2114`) to the 600 block (`:1885`).
  - CSS-regex test.
- **7.3 Status-bar separator** (05 N12; B18).
  - `.cr .cr-term-ctxused ~ .cr-term-ctxcum::before { content: "/ "; }`. `ctxcum` is emitted without `ctxused` (`ext_cr_term.js:1172-1174`).
  - CSS test.
- **7.4 Metaline cwd** (03 F11; B19).
  - Export `shortDir` (`ext_cr_board.js:561`) on the existing `CR.board` return object (`:3257`), beside `toolLabel`. This is narrower than REVIEW-B's new `window.CR.shortDir`.
  - In `metaBits` (`ext_cr_detail.js:2404`), replace `proj` with `(meta.cwd && CR.board && CR.board.shortDir) ? CR.board.shortDir(meta.cwd) : proj`. Auggie's empty `cwd` (`auggie.py:497`) falls back.
  - Node test: `/a/b/c/d` gives `…/c/d`.
- **7.5** One SUPERSEDED line under `reports/control-room-redesign.md:180` that points at `7b87cce`.
- **7.6 Rulings paragraph** in `reports/control-room-refinements.md`:
  - D4 (`aadcae5`);
  - D6 as answered, citing `pending-work-worker.md`;
  - D7, with the `adeb6fa` app.js edits;
  - D1, D2 and D5 as answered;
  - the bundle-copy note (which copy is current).

Phase 7 diff: about 35 lines, plus about 30 lines of tests.

---

## 3. Sequencing

| Phase | Why here | Diff estimate |
|---|---|---|
| 1 Terminal correctness | Daily data and work loss: Esc kills the terminal and leaks into the board, the typed path is lost, toasts are invisible from the board | ~215 lines (about 55% tests) |
| 2 Terminal chrome | Same files, context already loaded. Desync and honesty | ~105 |
| 3 Detail header, fork banner, files | The two HIGH layout drifts. Needs a browser pass. After the terminal work is stable | ~140 |
| 4 Help/Config | One small `/api/config` change (data files, bound port), copy, counts | ~160 |
| 5 Board tiles | List fields only, no server change | ~75 |
| 6 Gate | Tests only. Lands after the product phases so its new guards do not block them | ~170 |
| 7 Polish and records | Independent | ~65 |

- Decisions land as follow-ups. Sizes: D1(a) ~30, D2(a) ~25 with the test removal, D3(a) ~70, D9 ~15, D10 ~20, D11 ~5, D8 not planned.
- All seven commits go on this one branch (rule 9).

---

## 4. Implementation protocol (binding)

1. **Each phase starts with `/tracker-gap`**, which confirms the capability lands at the shared seam for both providers.
2. **A `sonnet` agent implements** the phase from this file. The brief bans `git stash`, whole-file reads of the 3000-line files, and broad `git diff`.
3. **A `haiku` gate-runner runs per module**, never the whole suite in one process:
   - `unset TRACKER_AUTH; python3 -m unittest tests.<module> -v` for each changed module;
   - then one module per process across `tests/test_*.py`, from a script file. Never pipe through `| tail`. `Killed: 9` with no failures means OOM, not red;
   - then `unset TRACKER_AUTH; make check`, which must print `selfcheck ok`;
   - the known flake is one `term_vt` backstop test: re-run it in isolation.
4. **Each new test is proved RED** by reverting its fix with a scoped Edit (never a stash), running that one test, then restoring. Record each test name → red/green pair in the commit body.
5. **Browser pass for the visual items:** P1.1–P1.4, P2.1, P2.2, P3.1–P3.3, P5.1, P5.2, P7.1–P7.3, and D3 if built.
   - Use a test server from the worktree on a spare port, for example `python3 -m aitracker` with `PORT=8795 TRACKER_NO_BROWSER=1`. Never 8787 or 8790, never `pkill`. Stop it by its own PID.
   - Restart it after every phase.
   - Check both themes at 1440, 1280, 1024, 900, 600 and 390.
   - Zero console errors, no horizontal scroll.
6. **Bundle sanity after every phase:** `python3 -m unittest tests.test_page_bundle tests.test_page_css`.
7. **Commit.** The hook runs the full gate, so give Bash a timeout of at least 400000 ms (over 5 min). Prefix with `unset TRACKER_AUTH;`. Use `git commit -F <file>`.
8. **After the last phase:**
   - an `opus` adversarial implementation review, told to assume the report is false, with a designed fix per finding;
   - a cheaper agent applies the fixes, and they are re-verified;
   - `/branch-sync`;
   - the gate green again;
   - push the branch to `personal`, never `main`.

---

## 5. Deferred (LOW) with reasons

- **01:**
  - N5 emoji-mode filter tints: optional icon style only.
  - N6 keyframe names: covered by D3.
  - N7 10px floor: the 8px FAIL word is doc-required, and it needs a browser fit check.
  - N9 `tabular-nums`: small effect across four files.
  - N11 raw hex in `ext_cr_term.css`: deliberate frozen dark literals.
- **02:**
  - R1 5.2 `tracker.rail` key: needs a dual-read migration.
  - R1 5.5 and R1 9.4.
  - N7 and N8: owner-asked, pinned by `tests/test_cr_topbar_layout.py`.
  - N11.
- **03:**
  - F6 PR title: a Claude-only parser change (`util.py`), and Auggie has no PR extraction.
  - F9, F10, and F13/N14/N16/N23 (D6).
- **04:** N12 live pill (no room); R1-#10 name-first ranking.
- **05:**
  - N4 notice stacking and the "fork" chip: about 40 lines of array state.
  - N13: D6.
- **P5.2's `files_n`:** not on the list shape. Adding it means a list-poll file-op parse in both providers.
- **`config.json` PORT/HOST overrides are never read at startup (new).** `cli.py:42-43` binds from env only, yet `config.RESTART_REQUIRED` (`config.py:229`) and the Data-files hint promise they apply after a restart. P4.5 makes the displayed value honest. Fixing the startup read is its own small change and needs an owner call on precedence.
- **B10 escape hatch `TRACKER_GATE_NO_NODE`:** only if the owner commits from a GUI client.
- **00:** the terminal screen's second 2 s `/api/session` fetch. Reusing app.js's response needs an id check.

## 6. Not examined

- **Not run in a browser in this round:**
  - A3's stacking: the code shows the wrap after the notice with no z-index.
  - P1.4's `connected` re-emit on a grid switch: its fallback is stated.
  - A9's dialog-during-asset-load timing.
- **Agent-map dialog line numbers (D6):** not re-derived. Cite them by grep.
- **Strings changed here and pinned by tests outside the files named:** "Search", fork copy, file counts. Grepped for the main literals and found none, but the implementer re-greps each changed string.
- **Not re-run:** 01 N10 (gap, never margins), 01 N16 (shadow plus glow), 02 N14 / R1 A8 (focus and scroll across polls), 04 N13 (toast timings), 03 N25 (phone hit targets).
- **Out of scope per the README:** the prototype Round 5 artboards (docs win) and classic's 12 native dialogs.
