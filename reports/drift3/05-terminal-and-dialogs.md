# Drift round 3 - 05 Terminal and dialogs

Doc audited: `design_handoff_control_room/05-terminal-and-dialogs.md` (all 74 lines), plus the terminal rows of doc 04 (Terminals at the cap, Config terminal rows).
Precedence applied: **docs win** (commit `7b87cce`, 2026-09-05: "docs beat the prototype everywhere except the emoji tint recipe"; later than the 2026-08-29 "HTML wins" ruling). I did not diff the prototype artboards for this slice; no doc-vs-prototype conflict surfaced in the code paths read.
Code SHA: `76bd154`. Method: read `ext_cr_term.{js,css}`, `ext_cr_dialogs.js` (manage, picker, ladder, lineage, config server rows) and the classic `ext_vt.js` (buildToolbar 515, ContextBar 2192, buildTermRow 2590, manager 3198, mountInto 3660), `ext_launch.js`, `ext_run.js`. Nothing was run in a browser; "(code only)" items need a browser check.
Later rulings read: `reports/control-room-terminal-parity.md` (one shared action seam `ExtVT.term`, chrome differs by design), `TERM-PEEK-BEFORE-SPAWN.md` (attach the running terminal, do not respawn), `XTERM-DEFAULT-AND-SWITCH.md` (xterm default, grid on demand, per-terminal switch), `terminal-name-suffix.md`, `FOLDER-TERMINAL.md`, `resume-terminal-attach-fix.md`.

## 1. Prior-finding status

| id | finding | status now | evidence |
|---|---|---|---|
| R1 1.1-1.8 | Control bar groups, status bar, header, notice banner present | CLOSED (still MATCH) | `ext_cr_term.js:134-200` (build), `:292-313` (_onAction) |
| R1 2.1 | Pane dark in both themes | CLOSED | `ext_cr_term.css:258-305` frozen literals; `ext_cr_term.js:366-368` |
| R1 2.4 / fix 3 | Terminal never calls `handle.focus()` on open or after renderer switch | STILL OPEN (LOW) | `focus()` in `ext_cr_term.js` appears only in a comment (`:330`) and the busy-confirm Yes button (`:844`) |
| R1 3.x, 4.1-4.8 | Secondary flows are dialogs; manage/cap/picker/model/effort/lineage exist | CLOSED | `ext_cr_dialogs.js:2009,2174,2325,2374`; REGISTRY `:2874` |
| R1 4b.7 | Config Auth read-only, doc allows set-from-UI | SUPERSEDED-BY-RULING (deliberate security tightening, comment at `ext_cr_dialogs.js:1395`; doc 04 permits read-only env rows) | `ext_cr_dialogs.js:1394-1396` |
| R1 4b.8 | Port/Host editable, doc says read-only | CLOSED | `ext_cr_dialogs.js:1402-1405` use `readonlyField` |
| R1 4c.2 | "58 capabilities" vs 60 rows | SUPERSEDED-BY-RULING (count derived from the list; doc is the stale side) | `ext_cr_dialogs.js:663` |
| R1 5.6 / fix 2 | Terminal overlay has `role=dialog` but no focus trap or opener restore | CLOSED | `ext_cr_term.js:371-380` (trap), `:404-425` (restore) |
| R1 6.x, 7.x, 8.x | lazy xterm, read-only, colour not alone | CLOSED (unchanged; `mount()` builds DOM only, engine attaches on user action) | `ext_cr_term.js:1254+`, `:469-500` |
| R2 #1 (HIGH) | Directory picker rendered `[object Object]` and POSTed it | CLOSED | `ext_cr_dialogs.js:2191-2205`; `ext_cr_term.js:605` |
| R2 #2 (MED) | Manage/cap rows named by raw session UUID | CLOSED | `ext_cr_dialogs.js:1999-2006,2043-2051` |
| R2 #3 (MED) | Config "Terminal enabled" lacked restart note | CLOSED | `aitracker/config.py:219` (`TERMINAL` in `RESTART_REQUIRED`); `ext_cr_dialogs.js:1218` |
| R2 #4 (LOW-MED) | Port/Host lacked restart flag | CLOSED | `ext_cr_dialogs.js:1403,1405` |
| R2 #5 (LOW) | Lineage body did not say which session you are on | CLOSED | `ext_cr_dialogs.js:2381-2385` |
| R2 note | `alert(` in classic `ext_vt.js` | CLOSED / n.a. (classic; none left in `ext_vt.js`) | grep |

Totals: 14 closed, 1 still open, 0 regressed, 2 superseded by ruling.

## 2/3. New drift

Classic-parity check first (task ask: any classic terminal control with no control-room equivalent).

| classic control | classic location | CR equivalent |
|---|---|---|
| Open/Resume here, External x2, New tab, + New terminal, + New Claude, Manage + badge | `ext_launch.js`, `ext_vt.js` | all present (`ext_cr_term.js:134-160`) |
| Renderer switch, theme flip | `ext_vt.js:515-700` | bar seg + Theme, AND the engine toolbar is still mounted in the pane (N1) |
| A- / A+ zoom, mouse-reporting toggle | `ext_vt.js:571-617` | no CR control; only via the engine toolbar inside the pane (N1) and Ctrl +/- |
| Model/effort dropdowns, update nudge, context readout with bar and Sigma | `ContextBar` `ext_vt.js:2192-2540` | pills + dialogs (`ext_cr_term.js:970-986`), nudge `ext_cr_dialogs.js:2300,2341`, readout `ext_cr_term.js:1160-1171` |
| Persistent "tty N - connected/reconnecting/disconnected" | `ext_vt.js:2838-2839,3018` | none after attach, only a 4 s toast (N5) |
| "fork" chip | `ext_vt.js:2068-2072,4081-4087` | notice banner only (N4) |
| Stacked notice banners (cap 3, seq dedupe) | `ext_vt.js:462-505` | single slot (N4) |
| Picker: Enter submits, inline error with picker staying open, full path under label | `ext_launch.js:214-262,299-317,319-370` | missing (N6, N7, N8) |
| Manager row tooltip, per-action aria-label, explainer head | `ext_vt.js:2655-2677,3321-3330` | missing (N9) |
| Run a command (Run/Stop) | `ext_run.js` | detail view + `run-output` dialog (`ext_cr_boot.js:717-760`, `ext_cr_dialogs.js:1762`); detail slice owns it, not audited here |

| # | doc section + line | doc says | code does (file:line) | verdict | sev |
|---|---|---|---|---|---|
| N1 | Layout, doc L52 "renderer switch and theme toggle sit in the terminal's own toolbar"; Behaviour L68 | one renderer switch and one theme toggle, owned by the CR bar | `mountInto` builds the classic `.vttoolbar` (theme, A-, A+, mouse, renderer) inside the pane (`ext_vt.js:791,1770`); no CR CSS hides it (no `vttoolbar` match in `ext_cr*.css`). The engine renderer button calls mount-internal `setRenderer` (`ext_vt.js:3703`), bypassing CR `_setRenderer` (`ext_cr_term.js:928-944`), so `st.renderer`, seg `aria-pressed`, footnote and blank notice go stale. The engine theme button calls classic `toggleTheme()` (flips the classic dashboard theme, not the CR theme). (code only) | DRIFT | MED |
| N2 | Behaviour L69 "switching to xterm shows a blank pane... say so in the UI" | say so; do not fake a repaint | `.cr-term-pane-blank` is an absolute `inset:0` overlay with `background: rgba(18,16,14,.82)` (`ext_cr_term.css:296-307`), hidden only by `_resetPaneChrome` or another manual switch (`ext_cr_term.js:940`, admitted at `:933-938`). After the next write, live xterm output sits under an 82% dark scrim indefinitely | DRIFT | MED |
| N3 | doc 04 modal contract; doc 05 L44 "nothing here navigates away from an open PTY" | a dialog opened over the PTY closes alone | terminal overlay registers its own `document` Escape listener with no check for an open dialog (`ext_cr_term.js:243-245`); `CR.dialogs.onDocKeydown` also fires (`ext_cr_dialogs.js:354-361,371`). Esc inside Manage/Model/Config/Picker closes the dialog AND detaches the terminal. (Esc with the terminal focused is safe: the engine stops propagation, `ext_vt.js:1138-1141`) | DRIFT | MED |
| N4 | "The fork notice" L58-60 | wheat banner says what happened + See lineage; if lineage cannot be established say nothing | `_syncNotice` shows banner and the "See lineage" button for ANY notice (`ext_cr_term.js:1182-1186`; button markup `:226-228`), including non-fork notices the server raises ("no prior transcript", "retry abandoned": `term_vt.py:2425,2833`). One slot: a new notice replaces the last (`:513-515`), and `onForked` then assigns `handle.notice \|\| null` (`:523`), wiping a notice streamed just before. `st.forked` is stored but never used for display (`:523,581`); classic shows a "fork" chip | DRIFT | MED |
| N5 | Layout "PTY pane" (nothing dropped) | connection state is part of the terminal | after attach, `onStatus` text ("reconnecting...", "disconnected - reopen this terminal") goes only to a 4 s toast (`ext_cr_term.js:489-491`, `:107-113`); classic keeps a status line (`ext_vt.js:2838-2839`). A dead pane leaves no lasting signal | DRIFT | MED |
| N6 | Directory picker L47 | recent dirs plus free-text field | Enter in the field does nothing: the input has no keydown handler (`ext_cr_dialogs.js:2253-2258`); classic submits on Enter (`ext_launch.js:259-261`) | DRIFT | LOW |
| N7 | Directory picker L47 (classic contract: failure keeps picker open with inline error) | start a terminal there | `_pickDirectory` toasts and returns normally on 403/404/other failures and on fetch failure (`ext_cr_term.js:644-662`); the promise resolves, so the picker calls `close()` (`ext_cr_dialogs.js:2218`). Typed path lost; error is a 4 s toast. Only an empty path rejects. Classic: `showPickerError` (`ext_launch.js:306-316`) | DRIFT | MED |
| N8 | Directory picker L47 | (classic shows label AND full path per row) | row text is `label` only, path only in `title` hover (`ext_cr_dialogs.js:2197-2201`); classic keeps the full path visible so same-named dirs are distinguishable (`ext_launch.js:228-236`) | DRIFT | LOW |
| N9 | Manage terminals L43 | rows: session, project, age, peek, kill | no row tooltip (tty, cmd, full cwd), no per-terminal aria-label on peek/kill (`ext_cr_dialogs.js:2054-2074` vs `ext_vt.js:2655-2677`); classic head explainer ("Peek opens... kill SIGKILLs the process group") reduced to a footer line (`:2158`) | DRIFT | LOW |
| N10 | Control bar, Right cluster L24 | renderer seg works | clicking the seg before a terminal is open only sets `st.renderer` (`ext_cr_term.js:928-931`); `_openInline` mounts with `{}` (`:487`), so the choice is dropped and `onForked` resets it to the server default (`:521`). Seg also starts as "xterm" pressed (`:176`, default `:93`) whatever `TERM_RENDERER` is | DRIFT | LOW |
| N11 | Status bar L29-35 | Copy and Kill live in the bar | bar hidden when there is no readout data and no Claude attached (`ext_cr_term.js:1177-1178`): a plain shell on a session with no context/token data has no Copy or Kill (Manage dialog still kills). `onForked` shows it (`:526`), the 2 s poll hides it again | DRIFT | LOW |
| N12 | Status bar L31 | `context 128,412 / cumulative 481,003` | numbers comma-grouped (MATCH, `:35-40`) but no " / " separator; cumulative is a separate span with margin (`ext_cr_term.js:1168-1171`) | DRIFT | LOW |
| N13 | Control bar, Primary L16 | Open/Resume always present | primary group hidden while a Claude CLI is foreground (`ext_cr_term.js:1152`); no doc or report authorises this | DRIFT | LOW |
| N14 | Config -> Server (doc 04) | server values not invented | Server tab falls back to `8790` and `127.0.0.1` when the server sends none (`ext_cr_dialogs.js:1403,1405`), conventions rule 5. Config belongs to slice 04; noted only | DRIFT | LOW |
| N15 | Status bar L29-35 | model white pill, effort ghost, Copy, Kill brick; model/effort only while Claude is foreground | MATCH `ext_cr_term.js:193-200,1150-1151,1213-1220`; `ext_cr_term.css:350-372` | MATCH | - |
| N16 | Everything secondary is a dialog L38-49 | eight dialogs via the modal host | MATCH: all `ctx.dialog(...)` (`ext_cr_term.js:295-296,589,727,971,982,1080`); no native `alert/confirm/prompt` in `ext_cr_term.js`/`ext_cr_dialogs.js` | MATCH | - |
| N17 | Manage / cap | `N of max`, Close all behind inline confirm, killing at cap reopens the asked terminal | MATCH `ext_cr_dialogs.js:2023-2032,2108-2160`; max is the server value, never invented; retry `ext_cr_term.js:677-725` | MATCH | - |
| N18 | Behaviour L65-67 | close detaches; dedupe on session+mode; banner owned by mount; pane dark | MATCH: `close()` only destroys the handle (`ext_cr_term.js:404-425`); dedupe is the shared `mountInto` list scan; `_applyDarkTheme` | MATCH | - |

New drift totals: HIGH 0, MED 6 (N1, N2, N3, N4, N5, N7), LOW 8 (N6, N8, N9, N10, N11, N12, N13, N14).

## 4. Extras

| extra | where | ruling |
|---|---|---|
| Shared action seam `ExtVT.term` (killSeries, closeTty, armGuard, peekUrl), reap-settle repaint, `CR.dialogs.topName()` | `ext_cr_term.js:772-910` | ruled: `reports/control-room-terminal-parity.md` |
| Busy-close confirm (409 `fg`), Close-all latch and arm guard | `ext_cr_term.js:816-870`, `ext_cr_dialogs.js:2110-2150` | ruled: same report |
| Row suffixes `-terminal`/`-resume`/`-new` | `ext_cr_dialogs.js:2051` | ruled: `reports/terminal-name-suffix.md` |
| Attach existing tty instead of spawning | mountInto find-or-spawn | ruled: `reports/TERM-PEEK-BEFORE-SPAWN.md` |
| xterm default, grid on demand | seg, footnote | ruled: `reports/XTERM-DEFAULT-AND-SWITCH.md` |
| Folder-shell rows (`t.folder`, `t.fg`) | `ext_cr_dialogs.js:2046-2049` | ruled: `reports/FOLDER-TERMINAL.md` |
| Model-update nudge, `model_label`, `model_slot`, `model_ladder`/`model_hints`, "up arrow" pill state | `ext_cr_term.js:970-980,1129-1157` | unruled in CR reports; mirrors classic ContextBar, low risk |
| Footnote line (renderer parity disclaimer) | `ext_cr_term.js:1188-1197` | unruled; reasonable reading of the layout's "footnote" row |
| In-pane toast element | `ext_cr_term.js:107,233-236` | unruled; replaces `alert()` per convention |
| Agent map, model marker chip, job-summary headline | other modules | not in this slice |

## 5. Fixes

Test style: this repo pins client behaviour by source-text slices (`tests/test_cr_manage_terminals_parity.py`, `tests/test_term_vt_client.py`). Put new assertions in a new `tests/test_cr_term_drift3.py`; prove each red by reverting its fix.

**N1 - engine toolbar duplicates and desyncs.** Direction: the CR bar is the only renderer/theme control; keep zoom and mouse toggle (they have no CR home; doc says font zoom and mouse reporting keep working). Do NOT edit `ext_vt.js` or the classic modal. Way: `ext_cr_term.css`, add `.cr .cr-term-pane .vtrendererbtn, .cr .cr-term-pane .vtthemebtn { display:none; }` and skin the remaining A-/A+/mouse buttons with the frozen dark literals. Alternative if the owner wants zoom/mouse in the bar: add two `.cr-term-btn` entries calling new additive `handle.zoom(+/-1)` / `handle.setMouse(bool)` on `mountInto`. Test: assert the CSS hides both selectors under `.cr-term-pane` (red before: absent). Browser check that A-/A+ still show.

**N2 - blank notice is a permanent 82% scrim.** Direction: say it once, never obscure live output; still do not fake a repaint. Way: restyle `.cr-term-pane-blank` as a top-edge strip (`inset:0 0 auto 0`, no full-pane background) and clear it on first keydown/pointerdown in `el.pane` or after about 8 s, wired in `_setRenderer` (`ext_cr_term.js:940`). A true first-write signal would need an additive `onOutput` on the handle. Test: assert the CSS block has no `inset: 0` with `rgba(...,.82)`, and `ext_cr_term.js` sets `el.blank.hidden = true` in an input handler.

**N3 - Esc closes dialog and terminal.** Direction: Esc closes the topmost dialog only; the overlay closes on Esc only with no dialog open. Way: `ext_cr_term.js:243` condition adds `&& !(window.CR.dialogs.topName && window.CR.dialogs.topName())` (`topName` already exported). Do not touch `CR.dialogs`. Test: slice the listener and assert it references `topName` (red before).

**N4 - notice banner and lineage.** Direction: lineage link only when a fork is known; show non-fork notices without the link; stack up to 3 with seq dedupe like classic; never drop a streamed notice at `onForked`; add the classic "fork" chip when `st.forked`. Do not infer lineage client-side. Way: `st.notice` becomes a short array rendered by `_syncNotice`; gate the lineage button on `st.forked`; `onForked` (`:523`) merges instead of assigning; one chip `<span>` in `.cr-term-head-info`. Test: assert `_syncNotice` gates the button on `st.forked` and `onForked` has no `st.notice = handle.notice || null`.

**N5 - persistent connection state.** Direction: a lasting line, toast kept for transitions. Way: add `data-el="conn"` in the status bar; post-attach `onStatus` writes it (`ext_cr_term.js:489-491`); cleared in `_resetPaneChrome`. Test: assert the `st.tty` branch writes the element, not only `showToast`.

**N6/N7/N8 - directory picker.** Direction: match the classic contract; keep the busy/latch logic. Way: (N6) `renderDirectoryPicker` adds `input` keydown Enter -> `go.click()` (`ext_cr_dialogs.js:2253`). (N7) `_pickDirectory` rejects with `Error(message)` on every failure path instead of toast+return (`ext_cr_term.js:644-662`; the 429 branch keeps resolving into the cap dialog), and the picker's `release` shows `err.message` in an inline `cr-help-note` slot. (N8) render each row as label plus a second `cr-mono` path span. Tests: N6 assert a keydown `Enter` handler in the picker source; N7 assert non-429 failure branches `reject`/`throw` rather than `showToast(...); return;`; N8 assert the row builder emits the path as text.

**N9 - manager row detail.** Direction: restore tooltip and accessible names; keep the footer. Way: in `renderManageTerminals` set `title` to `t.tty + ' - ' + (t.cmd||'shell') + ' - ' + (t.cwd||'')` on the row title; `aria-label` on peek and kill naming the terminal; one-line explainer above the list. Test: assert `aria-label` and `t.tty` in the row builder.

**N10 - renderer seg before open.** Direction: the pre-open choice applies or the seg is disabled until open. Way: in `_openInline` (`ext_cr_term.js:487`) pass `{ renderer: st.rendererUser }` when the user chose one, or `disabled` the seg until `st.tty`; seed the initial state from `GET /api/term/renderer`. Test: assert the mount opts carry `renderer`.

**N11 - Copy/Kill stranded.** Direction: render whenever a terminal is attached. Way: `ext_cr_term.js:1177` becomes `el.status.hidden = !st.tty;` (readout and pills self-hide). Test: assert the line no longer references `hasAnything`.

**N12 - separator.** Way: `.cr-term-ctxcum::before { content: "/ "; }` or the literal in `_syncStatusBar` (`:1168`). Visual-only.

**N13 - primary group hidden.** Direction: keep visible (disabled styling acceptable). Way: drop `el.primaryGroup.hidden = st.attached` (`ext_cr_term.js:1152`), or record an owner ruling in `reports/control-room-refinements.md`. Test: assert the line is gone.

**N14 - Config fallbacks.** Direction: show "unknown" when the server sends none. Way: `ext_cr_dialogs.js:1403,1405`. Test: assert `8790` and `'127.0.0.1'` are absent from the Server tab block. (Slice 04 owns it.)

**R1 2.4 focus (still open).** Direction: focus the pane after attach and after a renderer switch. Way: `handle.focus()` in `onForked` (`ext_cr_term.js:521`) and after `setRenderer` (`:935`). Test: assert `focus()` is called on the handle in `onForked`.

## 6. Top 5

1. N3 - Esc inside any terminal dialog (Manage, Model, Config, Picker) also detaches the terminal behind it.
2. N2 - after switching to xterm, the live pane stays under an 82% dark scrim until you switch back or close.
3. N7 - a failed "+ New terminal / + New Claude session" spawn closes the picker and loses the typed path; the error is a 4 s toast.
4. N1 - the engine's own toolbar (renderer and theme buttons) is still inside the pane and desyncs the CR renderer seg and footnote (verify in a browser).
5. N4/N5 - "See lineage" shows for every notice, one notice at a time, and "disconnected" only flashes as a toast.
