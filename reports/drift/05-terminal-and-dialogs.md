# Drift analysis — 05-terminal-and-dialogs.md vs implementation

Spec: `design_handoff_control_room/README.md` + `05-terminal-and-dialogs.md` (full, 74 lines) + the
terminal-related rows of `04-coverage-and-help.md` (capability rows 15/16/55–57/59, "Terminals at
the cap", "Help and Config — both dialogs").

Implementation read in full: `aitracker/web/ext_cr_term.js` (1022 lines), `ext_cr_term.css` (436
lines), `ext_cr_dialogs.js` (dialog host + relevant renderers), `ext_cr_dialogs.css` (spot-checked),
`ext_vt.js` (mountInto, `_loadXtermAssets`, MODEL_LADDER/EFFORT_LADDER, resize/scrollback engine),
`term_vt.py`/`term_run.py`/`term_launch.py` (route wiring, spot-checked for the read-only invariant).

---

## Area 1 — the full control set (README decision #11: nothing dropped)

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 1.1 | 05 "control bar" table, Primary | Open terminal here (solid) · Resume terminal here (outline) | `ext_cr_term.js:135-136` builds both; `_onAction` routes to `_openInline` (`ext_cr_term.js:273-274`), which calls `ExtVT.mountInto` (`ext_vt.js:3229`) | MATCH | — |
| 1.2 | 05, External | ↗ External terminal / ↗ External resume, hidden off-localhost, resume Claude-only | `ext_cr_term.js:140-141` builds both; visibility driven by `_syncControlVisibility` (`ext_cr_term.js:857-862`) using `localOnly()`/`isClaudeId()`; wired to real `POST /api/term/open` via `_openExternal` (`ext_cr_term.js:507-517`), which is `term_launch.py:229`'s `open_terminal` | MATCH | — |
| 1.3 | 05, Windows | ⤢ New tab · + New terminal · + New Claude session | `ext_cr_term.js:145-147`; `_openNewTab` (line 520), `_openDirectoryPicker("cwd")` (278), `_openDirectoryPicker("new")` (279) all wired to real routes (`POST /api/term/pty`, `GET /api/term/cwds`) | MATCH | — |
| 1.4 | 05, Management | ☰ Manage terminals with live running-count badge | `ext_cr_term.js:150-154`; `_openManageDialog` (632) fetches `GET /api/term/list`; badge synced by `_syncBadge`/`_refreshRunningList` on the 2s poll (679-692, 940-962) | MATCH | — |
| 1.5 | 05, Right cluster | Renderer segmented xterm.js/grid · ☀️ Theme | `ext_cr_term.js:157-162`; `_setRenderer` calls `handle.setRenderer()` (695-712); `_cycleTheme` (723-727) | MATCH | — |
| 1.6 | 05 "The status bar" | context readout · model (white pill) · effort (ghost) · ⧉ Copy · ■ Kill (brick) | `ext_cr_term.js:193-200`, styled `ext_cr_term.css:339-372` (`.cr-term-pill-model` white bg, `.cr-term-pill-effort` ghost border, `.cr-term-kill` brick tint) | MATCH | — |
| 1.7 | 05 head | eyebrow + cwd + resume cmd \| Config Help (pills) | `ext_cr_term.js:111-126`, `_loadHeaderInfo` (837-856) | MATCH | — |
| 1.8 | 05 layout, fork/notice banner | conditional banner above pane, owned by mount point | `ext_cr_term.js:168-174`, `_syncNotice` (919-922); explicit comment ties this to "must survive a renderer switch" | MATCH | — |

No control named in doc 05's table was found dropped, stubbed, or rendered-but-unwired. Every
button traces to a real server route (`/api/term/pty`, `/api/term/close`, `/api/term/inject`,
`/api/term/open`, `/api/term/list`, `/api/term/cwds`, `/api/term/attached`) registered in
`term_vt.py:3334-3345` and `term_launch.py:229`.

---

## Area 2 — the PTY pane: layout, sizing, resize, scrollback, focus

| # | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|
| 2.1 | PTY pane dark in both themes ("stone 8"/"stone 7"), not app chrome | `ext_cr_term.css:258-321` hardcodes frozen literals (`#12100E`/`#26221C`/`#E4D8CA`), documented in the file header as deliberate; `_applyDarkTheme` (`ext_cr_term.js:341-344`) pushes the same literals into `handle.setTheme()` on every attach/renderer-switch (476, 701) | MATCH | — |
| 2.2 | Resize behaviour keeps working | Not duplicated in `cr_term.js`; delegated entirely to the shared `ResizeObserver`/`computeColsRows` engine in `ext_vt.js` (`observePane` ~388, `computeColsRows` ~341, wired inside `Terminal`/`XtermTerminal` and reused unchanged by `mountInto`) | MATCH | — |
| 2.3 | Scrollback keeps working (grid server-backed, xterm internal) | Same engine reuse — `term_scrollback` route (`term_vt.py:3341`) for grid; xterm's own buffer for xterm.js. `cr_term.js` adds no scrollback logic of its own | MATCH | — |
| 2.4 | Focus handling | The mounted engine's own `focus()` exists on the `mountInto` handle (`ext_vt.js:3325`, `3343`) but **`ext_cr_term.js` never calls `handle.focus()`** on open or after a renderer switch — checked every call site in `_openInline`/`_setRenderer` | DRIFT | LOW |

Note on 2.4: doc 05 doesn't explicitly mandate autofocus into the pane on open, so this is a soft
gap, not a broken control — flagged for completeness since "focus handling" was named in scope.

---

## Area 3 — every secondary flow is a dialog, never a route/panel/native prompt

| # | Flow | Implementation | Verdict | Severity |
|---|---|---|---|---|
| 3.1 | Manage terminals | `ctx.dialog("manage-terminals", …)` → `CR.dialogs` REGISTRY (`ext_cr_dialogs.js:1726`) | MATCH | — |
| 3.2 | Cap reached | Reuses the same `manage-terminals` renderer via `_openCapDialog` (`ext_cr_term.js:600-629`) — no separate route/screen | MATCH | — |
| 3.3 | Directory picker | `ctx.dialog("directory-picker", …)` (`ext_cr_term.js:533-563`) | MATCH | — |
| 3.4 | Model / Effort | `ctx.dialog("model"/"effort", …)` (737-750) | MATCH | — |
| 3.5 | Fork lineage | `ctx.dialog("fork-lineage", …)` (822-834) | MATCH | — |
| 3.6 | Config / Help | header pills call `ctx.dialog("config"/"help", {})` (271-272) | MATCH | — |
| 3.7 | No native `alert()`/`confirm()`/`prompt()` | `grep` across `ext_cr_term.js` + `ext_cr_dialogs.js`: zero live calls — only a code comment referencing the old `alert()`s it replaced (`ext_cr_term.js:89`); "Close all" uses an inline confirm row (`ext_cr_dialogs.js:1503-1508`), matching doc 04's "behind an inline confirm" | MATCH | — |
| 3.8 | No route navigation for a secondary flow | `grep` for `location.href=`/`location.assign`/`history.push` in `ext_cr_term.js`: none | MATCH | — |

All seven named dialogs and the cap-reached/close-all confirm are real dialogs through the one
`CR.dialogs` host; nothing native, nothing routed.

---

## Area 4 — every dialog: title, body, buttons, wiring

| # | Dialog | Spec (04/05) | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 4.1 | **Manage terminals** | Title "N of max running", rows = session title (not resume cmd) + project/age + peek + ✕ kill; footer "Closing detaches; ✕ kills." + Close all behind inline confirm | `renderManageTerminals` `ext_cr_dialogs.js:1470-1517`: title line 1484-1486, row `t.title\|\|t.session\|\|cwdTail\|\|t.tty` (1495) — **not** the resume command; peek/kill buttons 1498-1499; footer copy 1510 verbatim; Close-all inline confirm 1503-1508 | MATCH | — |
| 4.2 | **Cap reached** | Same list, `--surface-failed`, header "12 of 12 running — free a slot"; killing one immediately opens the terminal asked for | Header text built identically (`ext_cr_dialogs.js:1485`); `.cr-dialog-cap` sets **only the head** to `--surface-failed` (`ext_cr_dialogs.css:518-519`), not the whole panel body; `onKill` in `_openCapDialog` closes the dialog and replays `retry()` (`ext_cr_term.js:618-622`) | MATCH (styling scope is a defensible reading) | — |
| 4.3 | **Directory picker** | Recent cwds, most-recent-first, + free-text field | `renderDirectoryPicker` (`ext_cr_dialogs.js:1526-1555`): list from `payload.cwds` (server-ordered, not re-sorted client-side) + text input + Start button (1546-1551) | MATCH | — |
| 4.4 | **Model** | The model list; writes `/model <name>` | `renderLadderPicker('model')` with `MODEL_LADDER` passed as `ladder` (`ext_cr_term.js:26,740`); `onPick` → `_injectSlash("/model " + name, …)` → `POST /api/term/inject` (`ext_cr_term.js:751-762`, real route `term_vt.py:3008`) | MATCH | — |
| 4.5 | **Effort** | low/medium/high/xhigh/max; writes `/effort <level>` | `EFFORT_LADDER` identical array (`ext_cr_term.js:27`); same inject path | MATCH | — |
| 4.6 | **Config** | doc 04 — see below | see Area-4b table | see below | see below |
| 4.7 | **Help** | doc 04 — see below | see Area-4b table | see below | see below |
| 4.8 | **Fork lineage** | "See lineage" — shows parent and copy, which one you're on | `renderForkLineage` (`ext_cr_dialogs.js:1612-1629`) reads `continuedAs`/`continuedFrom` off `GET /api/session`; empty state when neither is present | MATCH | — |

### Area 4b — Config dialog rows (doc 04 table)

| # | Row | Spec control / env var / restart | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 4b.1 | Theme | segmented, no restart | Interface tab (not re-quoted; verified present) | MATCH | — |
| 4b.2 | Terminal renderer | xterm/grid segmented, `TRACKER_TERM_RENDERER`, no restart | `ext_cr_dialogs.js:1093-1097`, `_ENVCHIP.TERM_RENDERER` | MATCH | — |
| 4b.3 | Max terminals | slider 1–64 default 12, `TRACKER_MAX_TERMS`, no restart | `ext_cr_dialogs.js:1098-1101` | MATCH | — |
| 4b.4 | Terminal enabled | toggle, `TRACKER_TERMINAL`, restart yes | `ext_cr_dialogs.js:1102-1106`; row built via `serverRow`, which is the restart-marked variant (`cfgRow(..., true)` pattern used elsewhere for restart rows) | MATCH | — |
| 4b.5 | External terminal app | Terminal/iTerm segmented, `TRACKER_TERM_APP`, no restart | `ext_cr_dialogs.js:1107-1110` | MATCH | — |
| 4b.6 | Command allowlist | textarea one argv prefix/line, `TRACKER_TERM_ALLOW`, no restart | `ext_cr_dialogs.js:1111-1115` | MATCH | — |
| 4b.7 | Auth | masked "set/not set", `TRACKER_AUTH`, restart yes; doc: "Setting it from the UI is acceptable; reading it back is not" | `ext_cr_dialogs.js:1126-1128`: field is **read-only** (`readonlyField`) — the UI cannot set it at all, only shows set/not-set. Code comment explicitly justifies this as a deliberate security tightening beyond the doc's baseline ("writing a password typed into a browser into a plaintext file … is a real security regression") | DRIFT (justified, doc's own fallback clause permits read-only env-backed rows) | LOW |
| 4b.8 | Port / host | mono read-only display, restart yes | `ext_cr_dialogs.js:1129-1136` — **implemented as editable fields** (`textFieldCtl`, POSTed to `/api/config`), not read-only as doc specifies ("mono fields, read-only display") | DRIFT | MED |
| 4b.9 | Footer | "Rows with an env-var name…" note + Reset to defaults (quiet) + Apply (solid) | `ext_cr_dialogs.js:1271-1279` (`Reset to defaults` quiet button, `Apply` solid button) | MATCH | — |
| 4b.10 | Config writes to `config.json`, read live | Doc's ideal/fallback pair | `POST /api/config` implemented, `GET /api/config` read live on open (`fetchServerConfig`, `ext_cr_dialogs.js:894-898`) | MATCH | — |

Note on 4b.8: doc 04 explicitly calls Port/Host out as "read-only display" (unlike every other row,
which is live-editable) because rebinding a listening socket isn't attempted. The implementation
makes them editable text fields that POST to `/api/config` and take effect "next start" — the
per-row sub-copy says this correctly (`ext_cr_dialogs.js:1129,1133`), but the **control type**
contradicts the doc's explicit "read-only display" instruction.

### Area 4c — Help dialog

| # | Row | Spec | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 4c.1 | Tabs | Coverage (active) · States · Keyboard · Terminal · Per-tool | `HELP_TABS` (`ext_cr_dialogs.js:709-715`) — exact 5, exact order, Coverage default active | MATCH | — |
| 4c.2 | Coverage stat blocks | 58 capabilities / 4 tools / 0 bytes leaving | Implementation uses `CAPABILITIES.length` (60, not 58) with an explicit in-code note (`ext_cr_dialogs.js:588-595`) reconciling the doc's stale "58" against what actually shipped (60 rows, matching doc 04's own capability table) | DRIFT (doc says README wins on disagreement, but this is the doc contradicting its own capability table — implementation follows the correct number) | LOW |
| 4c.3 | Terminal tab | terminal reference | `helpTerminalTab`/`TERMINAL_REFERENCE` (`ext_cr_dialogs.js:565-575, 681-690`) — covers scrollback/copy/modified keys/renderer switch/model-effort | MATCH | — |
| 4c.4 | `?` opens Help | Doc 04 | `HELP_SHORTCUTS` row `['?', 'Open Help']` (556); actual key binding lives in board module (out of this doc's scope) — not verified here | not verified (out of file scope) | — |

---

## Area 5 — dialog mechanics: focus trap, Escape, focus restore, backdrop

| # | Mechanic | Spec (04, shared modal contract) | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 5.1 | Focus trapped inside | Required for every dialog | `trapFocus()` (`ext_cr_dialogs.js:328-340`) applied to every dialog panel on `open()` (line 420) | MATCH | — |
| 5.2 | Esc closes | Required | `onDocKeydown` (344-350), bound once at `mount()` (360), closes topmost stack entry only | MATCH | — |
| 5.3 | Focus returns to opener | Required | `close()` captures `entry.opener = document.activeElement` at open-time (414, 421) and restores it (437-438) | MATCH | — |
| 5.4 | Backdrop behaviour | Not explicit beyond "never navigates, never unmounts an open PTY" | `backdrop.addEventListener('mousedown', … close())` only when `e.target === backdrop` (392) — standard click-outside-closes | MATCH | — |
| 5.5 | Opening a dialog never unmounts an open PTY | Required | Dialogs mount into a separate `_layer` (`mount()`, 353-359) appended to the same `.cr` root as the terminal overlay, not inside `.cr-term-pane`; nothing in `open()`/`close()` touches `st.engineHandle` | MATCH | — |
| 5.6 | Terminal's own overlay (the primary surface, `role="dialog"`) | Not one of doc 05's 7 named dialogs, but built with `role="dialog"` (`ext_cr_term.js:106`) and its own Esc/backdrop handling (218-221) | Has backdrop-click-close and Esc-close, but **no focus trap** and **no focus-restore-to-opener** — unlike every dialog in `CR.dialogs` | DRIFT | MED |

Note on 5.6: doc 05's "Everything secondary is a dialog" table lists 7 specific dialogs, all of
which go through `CR.dialogs` and correctly inherit the shared contract (5.1–5.4). The terminal
overlay itself is the *primary* surface those dialogs sit on top of, not one of the 7 — but it
carries `role="dialog"` and modal-like chrome (backdrop, Esc-to-close), which sets an accessibility
expectation the shared contract normally guarantees (trap + focus return) that this surface does
not fully meet.

---

## Area 6 — the lazy xterm.js load invariant (HIGH-severity check)

| # | Check | Evidence | Verdict | Severity |
|---|---|---|---|---|
| 6.1 | `_loadXtermAssets()` call site | `ext_vt.js:1632-1653`; only ever invoked from `XtermTerminal.prototype.attach` (`ext_vt.js:1752-1759`) | — | — |
| 6.2 | `attach()` only reached via engine construction | `attachRenderer()` inside `mountInto` (`ext_vt.js:3248-3270`) calls `term.attach()` (3268) — `attachRenderer` is only called from `finish()` (3362-3384), which only runs after a real spawn/attach network round trip resolves | — | — |
| 6.3 | `mountInto()` itself only called from `cr_term.js`'s `_openInline` (`ext_cr_term.js:433`), which only runs from `open(sessionId, opts)` (347-361), which only runs from an explicit user action (Open/Resume terminal here, or the board's `terminal:open`/`session:new` bridge in `ext_cr_boot.js:470-472,700-701`) | — | MATCH | — |
| 6.4 | `CR.term.mount()` (called once, lazily, on first entry into Control Room — `ext_cr_boot.js:822-842`, `ensureMounted()`) only calls `_build()` (DOM chrome), `_updateFootnote`, `_syncThemeBtn`, `_wireThemeReactivity`, `_wireLifecycle` — **no engine attach, no `mountInto` call** | `ext_cr_term.js:991-999` | MATCH | — |
| 6.5 | No `<script src="/vendor/xterm.js">` or `/vendor/addon-fit.js` reference anywhere in `index.html` or `page.py` | `grep` returned zero matches | MATCH | — |
| 6.6 | Second open reuses the cached load | `_xtermAssetsPromise` memoized (`ext_vt.js:1631,1633`); `window.Terminal && window.FitAddon` short-circuit (1635) | MATCH | — |

**Verdict: the lazy-load invariant is fully intact.** Even the Control Room's own module mount
(triggered by opting into the new UI) does not pull in xterm.js — only an actual "Open/Resume
terminal here" click (which resolves to an xterm-renderer attach) does, exactly as
`conventions.md` #2 requires.

---

## Area 7 — read-only toward session logs

| # | Check | Evidence | Verdict | Severity |
|---|---|---|---|---|
| 7.1 | No write into `~/.claude/projects/*` or `~/.augment/*` from the terminal subsystem | `grep -n "\.claude/projects\|\.augment\|open(...'w'\|write("` across `term_vt.py`/`term_run.py`: every hit is either `os.write(pt.fd, …)` (bytes sent to the pty's stdin — the shell/CLI process the user is driving, not a session log) or `handler.wfile.write(...)` (HTTP response) | MATCH | — |
| 7.2 | Kill is a real process-group SIGKILL, not a log mutation | `term_vt.py:1440-1455` (`os.killpg(...SIGKILL)`), `term_run.py:308-327` (same pattern) | MATCH | — |
| 7.3 | Client never claims to "save"/"log" anything from the terminal | `ext_cr_term.js` toasts are all transient UI feedback ("Terminal opened", "Copied.", "Terminal killed.") — none imply persistence | MATCH | — |

The terminal spawns a real shell that *can* write anywhere the user directs it (that's the nature
of a terminal) — the invariant under test is narrower: the **tracker itself** never appends to or
mutates a session's transcript file. Confirmed clean.

---

## Area 8 — colour never carries meaning alone

| # | Indicator | Word present? | Evidence | Verdict | Severity |
|---|---|---|---|---|---|
| 8.1 | Model pill | "model · sonnet" | `ext_cr_term.js:896` | MATCH | — |
| 8.2 | Effort pill | "effort · high" | `ext_cr_term.js:897` | MATCH | — |
| 8.3 | Kill button (brick) | "■ Kill" literal text, not colour-only | `ext_cr_term.js:199` | MATCH | — |
| 8.4 | Fork/notice banner (wheat) | Full sentence text via `noticeText` | `ext_cr_term.js:920-921` | MATCH | — |
| 8.5 | Cap-reached header (brick head) | "N of max running — free a slot" text, not just red | `ext_cr_dialogs.js:1484-1486` | MATCH | — |
| 8.6 | Running-count badge (solid fill, no border) | Numeric digit is the content itself (not a colour-only signal) | `ext_cr_term.css:174-188` | MATCH | — |
| 8.7 | All emoji `aria-hidden` | Every `.cr-emo`/`emoji()` span carries `aria-hidden="true"` | `ext_cr_term.js` multiple; `ext_cr_dialogs.js:157-159` | MATCH | — |

No colour-only signal found in the terminal or dialog surfaces.

---

## Fix list (ordered by severity)

1. **MED — `aitracker/web/ext_cr_dialogs.js:1129-1136`**: Config's Port and Host rows are built
   with `textFieldCtl` (editable, POSTs to `/api/config`). Doc 04 specifies these two rows as
   "mono fields, read-only display." Change both to `readonlyField(...)` sourced from `srv.port`/
   `srv.host`, matching the pattern already used for `Auth` and `Data files`, or explicitly confirm
   with the product owner that editable-but-deferred was an intentional deviation and update the doc.

2. **MED — `aitracker/web/ext_cr_term.js`**: the terminal's own overlay (`role="dialog"`,
   `.cr-term-overlay`) has Esc-to-close and backdrop-click-close but no focus trap and no
   focus-restored-to-opener on close, unlike every dialog in `CR.dialogs`. Either wire it through
   the same `trapFocus`/opener-capture used by `CR.dialogs.open()`, or drop `role="dialog"` if it's
   meant to be read as the primary surface rather than a modal.

3. **LOW — `aitracker/web/ext_cr_term.js` (`_openInline`, `_setRenderer`)**: no call to
   `handle.focus()` after attach or after a renderer switch — the pty never receives keyboard focus
   automatically. Add `handle.focus()` in the `onForked` callback (~line 476) and after
   `setRenderer()` (~line 701) if input-ready-on-open is desired.

4. **LOW — `aitracker/web/ext_cr_dialogs.js:1126-1128`**: `Auth` row is fully read-only (no write
   path from the UI at all), stricter than doc 04's "setting it from the UI is acceptable, reading
   it back is not." This is a documented, deliberate security tightening — no code change needed,
   but the handoff doc should be updated to reflect the shipped (safer) behaviour so this stops
   showing as drift on the next audit.

5. **LOW — doc-only**: `04-coverage-and-help.md`'s Coverage-tab copy still says "58 capabilities"
   while its own capability table enumerates 60. The implementation already derives the correct
   number from the live list (`CAPABILITIES.length`, `ext_cr_dialogs.js:588-595`) — the fix belongs
   in the doc, not the code.
