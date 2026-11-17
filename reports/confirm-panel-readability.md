# Confirm-panel & Config→Server readability — durable file

Branch: `worktree-resume-panel-format` (worktree `.claude/worktrees/resume-panel-format`, base `personal/main` e6acfe7)

## Contract (verbatim)
1. "fix the data sentence how it's displayed, use proper formatting and make much more readable" — screenshot: Manage terminals → "Resume all prior terminals" confirm panel.
2. "fix this formatting as well" — screenshot: Config → Server panel.
3. "run the plan-review chain with /gap and /tracker-gap -> /branch-sync -> /tracker-push as per claude.md"

| Clause | Status |
|---|---|
| 1 Resume-all panel readable | **discharged** — list card + actions; `test_panel_structure`; list card not browser-rendered (no prior terminals for the worktree checkout), empty state checked |
| 2 Config → Server readable | **discharged** — browser PASS at ~904px and 390px (Server/Agents/Tunnel) |
| 3 plan → review → reconcile → sign-off → implement → review → branch-sync → tracker-push | plan/review/reconcile/sign-off (user: every tab, wrap globally, ship)/implement/review (R1+R2 applied) done; ship in progress |

## Observed defects (from the user's screenshots)
### 1. Manage terminals → Resume all prior terminals (`aitracker/web/ext_cr_dialogs.js` `resumeAllWidget`, ~L1419)
- Panel classes `cr-update-confirm`, `cr-update-confirm-text`, `cr-resume-all-row` had **no CSS at all** → browser defaults: the server message paragraph renders at large default font, checkbox rows run inline into each other (`☑ title · folder · 51s ☑ title …`), only the footnote (`cr-cfg-row-sub`, 10px mono) is styled — tiny mono next to huge sans.
- Buttons "Resume 3 ticked" / "Cancel" left-aligned loose under the footnote.

**Draft already in the worktree (uncommitted, unreviewed — treat as a candidate, not a given):** rows grouped in `.cr-resume-all-list`, each row = checkbox + title (600 12.5px) + meta line (mono 10.5px `folder · age`); note → `.cr-resume-all-note`; buttons in right-aligned `.cr-resume-all-actions`; CSS appended at end of `aitracker/web/ext_cr_dialogs.css` styling `.cr-update-confirm` as a sunken card (also affects `.cr-agents-confirm` in Config → Agents, which shares the class). `tests/test_resume_all_ui.py` (11 tests) passes; `node --check` passes.

### 2. Config → Server panel (rows built with `cr-cfg-row` / `cr-cfg-row-name` / `cr-cfg-row-sub` / `cr-cfg-row-control`)
- Every row description is `cr-cfg-row-sub` = **10px monospace** — multi-line prose (Auth, Port, Claude Code login) is cramped and hard to read.
- Right-side values ("not set", "8790", "127.0.0.1") render in large mono (~15px), visually louder than the labels.
- "— takes effect on restart" note is inline orange mono glued to the prose.
- Update row: sub lines "main @ 02594b9 — test: pin make serve's PORT pass-through (TestMakeServeEnv) / 2 behind personal/main / (checked just now) / No local changes" wrap awkwardly in narrow mono; the confirm text "2 open terminals will close" renders large and inline beside "Update anyway"/"Cancel", squeezing the label column (the `cr-update-confirm-text` span at ~L1257).
- Background service row and Claude Code login row: same 10px mono prose.

## Plan
_Author: opus plan agent, 2026-11-17. Grounded on worktree HEAD e6acfe7 + the uncommitted draft. All line numbers are in the worktree's current files._

### 0. Ground truth that shapes the plan (read from the code)
- **Why the values are "large":** `readonlyField()` (`ext_cr_dialogs.js:969-971`) emits `span.cr-readonly.cr-mono`. `.cr-mono` (`ext_cr_dialogs.css:154`) sets only a font **family**; `.cr-readonly` (`:372`) sets only colour; `.cr-cfg-row-control` (`:371`) and `.cr-dialog` (`:42-53`) set no size. So "not set" / "8790" / "127.0.0.1" inherit the page's 16px default. One `font-size` fixes it.
- **Why the prose is cramped:** `.cr .cr-cfg-row-sub` (`css:362`) = `400 10px mono`. Every user of that class is in `ext_cr_dialogs.js` (no other web file uses it). I checked each one: `cfgRow()` descriptions (`:922`, which covers Interface, Board, Terminal, Server, Tunnel and Data files), the Scheduled-scan status (`:1193`), the Update status (`:1253`), the Background-service status (`:1351`), the Claude-login status and warning (`:1630-1631`), the Agents row sub, confirm, job and msg lines (`:1516-1581`), and the resume-all `line()` (`:1435`). Each one is a sentence or a `title · detail` status line. None of them is a bare path or command. The real values already have their own mono carriers: `readonlyField` → `.cr-mono`, commands → `<code>` (`cmdLines`, `cr-tunnel-cmd`), and env chips → `code.cr-envchip`. So the prose/value split already exists in the markup: **`cr-cfg-row-sub` is prose, and `.cr-mono`/`<code>` are values**. Only the base rule is wrong.
- **Why the Update confirm squeezes:** in `updateBlock.paint()` (`js:1255-1260`), the confirm `div.cr-update-confirm` (text **span** + 2 buttons) is appended **inside** `ctl` (`.cr-cfg-row-control`, `flex: none`). So a full server sentence becomes a non-shrinking flex item beside the label. While `confirmText` is set, Check/Update are already removed from `ctl` (`:1240`), so `ctl` is otherwise empty.
- **The draft's card CSS reaches three hosts:** the resume-all panel (`:1423`), the Agents upgrade confirm (`:1535`) and the Update-row confirm (`:1256`). All three share `.cr-update-confirm`. If the confirm stays inside `ctl`, the draft would turn the Update confirm into a sunken card inside the narrow control column, which is worse than today. So surface 2's Update fix is **required** for the draft to be safe.
- **Hidden-attribute trap:** `resumeAllWidget` toggles `panel.hidden` (`js:1424`, `:1441`). Any `display:` declaration on `.cr .cr-update-confirm` would override `[hidden]` and show an empty card. The draft sets none, and the plan keeps it that way (pinned by a test below).
- **Dark mode:** every token the plan uses (`--surface-sunken`, `--surface-raised`, `--line-subtle`, `--text-muted`, `--text-secondary`, `--text-primary`, `--text-awaiting`, `--font-sans`, `--font-mono`) is redefined in the dark block of `ext_cr.css` (`:319-363`). The fallbacks follow the file's `var(--x, #light)` pattern.
- **Widths:** Config uses `cr-dialog-wide` (`min(760px, 100vw-32px)`). At ≤720px the nav moves to the top (`css:614-617`), and at 390px the body is about 340px. The Update row's two buttons (about 260px) then leave the label about 70px, which is the squeeze at phone and tablet widths.

### 1. Surface 1: Resume-all panel. **Keep the draft, with 3 amendments**
The draft's structure is right: a `.cr-resume-all-list` card, one `label.cr-resume-all-row` per session (checkbox + a title line + a `folder · age` meta line), a `.cr-resume-all-note`, and right-aligned actions. It renders every server sentence verbatim and keeps the button labels and order. Amendments:
- **A1 (JS `:1464-1471`):** rename the actions wrapper class `cr-resume-all-actions` → **`cr-confirm-actions`**, so the Update row (§2d) can reuse it. One shared rule, not two forks (conventions rule 4).
- **A2 (CSS, draft block at end of file):** delete `.cr .cr-update-confirm > .cr-cfg-row-sub { … }`. After §2a it duplicates the base rule. Rename the `.cr .cr-resume-all-actions` rule to `.cr .cr-confirm-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:6px; padding-top:2px; }`. `flex-wrap` is added so that "Resume N ticked" and "Cancel" wrap rather than overflow at about 340px.
- **A3 (CSS):** add a comment above the `.cr .cr-update-confirm` rule: "no `display:` here — resumeAllWidget toggles `[hidden]`". Keep `> * + * { margin-top: 8px }` and `> button + button { margin-left: 6px }`. The second rule is still needed by the Agents confirm, whose buttons are direct children (JS `:1530-1534`, left untouched).

### 2. Surface 2: Config → Server rows (CSS-first, two small JS edits)
**CSS: `aitracker/web/ext_cr_dialogs.css`, config-row block `:356-372`. Edit in place; do not append overrides:**
- **2a. Prose readable:** `.cr .cr-cfg-row-sub { font: 400 11.5px/1.45 var(--font-sans, sans-serif); color: var(--text-muted, #877866); margin-top: 2px; }`. Only the font changes from mono 10px to sans 11.5/1.45. Colour and margin stay the same.
- **2b. Calm values:** `.cr .cr-readonly { color: var(--text-muted, #877866); font-size: 12px; line-height: 1.4; }`. It stays mono through `.cr-mono`, because these are genuine values. `.cr-readonly` has exactly one producer (`readonlyField`), so nothing else changes size.
- **2c. Restart note on its own line:** `.cr .cr-restart-note { display: block; margin-top: 3px; font: 600 10.5px/1.3 var(--font-sans, sans-serif); color: var(--text-awaiting, #9A4F19); }`.
- **2d. Rows wrap instead of squeeze, and controls stay right-aligned:** add `flex-wrap: wrap;` to `.cr .cr-cfg-row` (`:356`). Change `.cr .cr-cfg-row-label { flex: 1 1 240px; min-width: 0; }`. Change `.cr .cr-cfg-row-control { flex: none; margin-left: auto; }`. On desktop (body about 570px) every current control fits beside a 240px label, so rows look the same as today. When the control no longer fits (phone or tablet, or two buttons), it drops onto its own line, right-aligned, and the label keeps its full width. This needs no media query and holds at any width.
- **2e. Update-row confirm as a full-width line under the row:** add `.cr .cr-cfg-row > .cr-update-confirm { flex: 1 1 100%; margin-top: 0; }`. This goes in the draft block after `.cr .cr-update-confirm`; the row's 12px `gap` already spaces it.
- **2f. (one line) Login status reads as status, not footnote:** `.cr .cr-claude-login-status { color: var(--text-secondary, #4A4237); }`. The warning sentence stays muted.

**JS: `aitracker/web/ext_cr_dialogs.js`:**
- **2g. `cfgRow()` `:924`:** change the literal `' — takes effect on restart'` → `'Takes effect on restart'`. The leading em-dash reads wrong once the note is on its own line. This is a client-side label, not a server sentence. No test pins it: only the docstring in `test_cr_registry_fields.py:739` mentions it.
- **2h. `updateBlock.paint()` `:1255-1261`:** build the confirm as a **sibling of `ctl`** and append it **after** `ctl` to `wrap`:
  ```js
  wrap.appendChild(ctl);
  if (confirmText) {
    wrap.appendChild(h('div', { class: 'cr-update-confirm', role: 'alertdialog' }, [
      h('div', { class: 'cr-update-confirm-text' }, [confirmText]),          // span -> div: own line
      h('div', { class: 'cr-confirm-actions' }, [
        crBtn('Update anyway', function () { confirmText = ''; applyNow(true); }, 'cr-btn-danger cr-update-yes'),
        crBtn('Cancel', function () { confirmText = ''; paint(); }, 'cr-update-no'),
      ]),
    ]));
  }
  ```
  The DOM order stays label → ctl → confirm. Button order, labels and classes are unchanged, and `confirmText` stays the server's 409 `error` sentence, verbatim.

### 3. What must NOT change
- No `.py` or server change. Every sentence (`rp.*`, `/api/update` and `/api/service` errors and reasons, `/api/claude/auth` label) stays server-owned and verbatim.
- Button labels and order stay the same: `Update anyway`/`Cancel`, `Resume N ticked`/`Cancel`, `Check for updates`/`Update and restart`, and Install/Reinstall/Uninstall.
- These classes and attributes stay, because tests pin them: `cr-update-confirm cr-agents-confirm` (`test_agents_ui.py:70`), `cr-resume-all`, `cr-resume-all-confirm`, `cr-update-block`, `cr-svc-block`, `cr-claude-login-block`/`-status`, `cr-cfg-row`, `cr-cfg-row-name`, `cr-agent-row` and `role="alertdialog"`.
- `readonlyField` stays read-only, with no `postConfigValue` wiring (the Port/Host comment at `js:2008-2012`).
- The Agents confirm JS (`:1513-1536`) is untouched. It only inherits the card CSS.
- `.cr-help-note` (11px mono on the Tunnel and Notifications tabs) is out of scope and untouched.
- `dist/tracker.py` is not edited. `.cr .cr-update-confirm` never gets a `display:` declaration.

### 4. Sequencing
1. CSS §2a–2f, plus the draft amendments A2–A3. This is pure styling, and it makes the draft safe for the Update host.
2. JS §2g, §2h and A1, followed by `node --check aitracker/web/ext_cr_dialogs.js`.
3. Tests (§5). Show each one red before its fix is reverted back in.
4. Run the gate per module (§5).
5. Visual check. Restart a **foreground** server from the worktree on a free port (`PORT=87xx python -m aitracker`; never `pkill -f aitracker`, and never touch the 8790 service). Check Config → Server and Manage terminals → Resume all at 1280, 720 and 390px, in light and dark. In the Update row, stub or force a 409 by having ≥1 terminal open, or rely on the executed test. Stop the server by PID.

### 5. Tests
**Add (3 assertions, each red before its fix):**
- `tests/test_page_css.py`, new `test_cfg_row_prose_sans_rows_wrap_confirm_not_display`. On the assembled CSS, take the first bare `\.cr\s+\.cr-cfg-row-sub\s*\{([^}]*)\}` and assert it contains `--font-sans` and not `--font-mono`. Assert `\.cr\s+\.cr-cfg-row\s*\{…\}` has `flex-wrap\s*:\s*wrap`. Assert `\.cr\s+\.cr-readonly\s*\{…\}` has `font-size`. Assert every `\.cr\s+\.cr-update-confirm\s*\{…\}` body has **no** `display\s*:` (the hidden-attribute guard). This is red on base (mono, no wrap, no size).
- `tests/test_update_settings_ui.py`: in `_BODY`'s `info()` add `confirmParent: (q(c) && q(c).querySelector('.cr-update-confirm')) ? q(c).querySelector('.cr-update-confirm').parentNode.className : null` and `confirmActions: (q(c) && q(c).querySelector('.cr-update-confirm')) ? q(c).querySelector('.cr-update-confirm').querySelectorAll('.cr-confirm-actions').length : 0`. The fake DOM's `parentNode` and single-class `querySelector` are enough. In `test_409_needs_confirm_then_reposts_confirmed_then_reload`, assert that `"cr-update-block"` is in `confirmParent` and `"cr-cfg-row-control"` is not, and that `confirmActions == 1`. This is red on base, where the parent is `cr-cfg-row-control`. The existing `buttons == ["Update anyway", "Cancel"]` and text assertions must stay green unchanged.
- `tests/test_resume_all_ui.py`: in the driver, after `OUT.panel_text`, add `OUT.list_n = all(panel, hasCls('cr-resume-all-list')).length; OUT.row_n = all(panel, hasCls('cr-resume-all-row')).length; OUT.actions_btns = all(all(panel, hasCls('cr-confirm-actions'))[0] || {children:[]}, function (x) { return x.tag === 'button'; }).map(function (b) { return b.textContent; });`. Add `test_panel_structure`: `list_n == 1`, `row_n == 2`, `actions_btns == ["Resume 1 ticked", "Cancel"]`. This is red with the draft JS hunk reverted. (`hasCls` matches whole tokens, so the existing `cr-resume-all` counts are not inflated by `cr-resume-all-row` or `cr-resume-all-list`.)

**Run (per module, never the full suite):** `unset TRACKER_AUTH; python -m unittest tests.<m>` for each of: `test_resume_all_ui`, `test_update_settings_ui`, `test_page_css`, `test_agents_ui`, `test_claude_login_settings_ui`, `test_cr_dialogs_config_exec`, `test_cr_readonly_ui`, `test_cr_registry_fields`, `test_cr_manage_terminals_parity`, `test_page_bundle`. All existing tests must stay green with no edits to existing assertions.

### 6. Risky spot + fallback
**§2d (global `flex-wrap` on `.cr-cfg-row`)** is the only change that reaches beyond the Server tab. A row whose control is wider than about 290px on desktop would newly wrap under its label instead of squeezing it. Candidates are the Tunnel URL row (`cr-tunnel-cmdrow`) and textarea rows (220px + badge). Verify these rows in the visual check at 1280px. **Fallback:** scope the wrap to the Server blocks plus narrow screens, i.e. `.cr .cr-update-block, .cr .cr-svc-block, .cr .cr-claude-login-block { flex-wrap: wrap; }` and `@media (max-width: 600px) { .cr .cr-cfg-row { flex-wrap: wrap; } }`, keeping the label at `flex: 1` elsewhere. Secondary risk: someone later adds `display:` to `.cr-update-confirm`. The new CSS test pins that.

### 7. Decisions the user may want to overrule
1. **The base `cr-cfg-row-sub` becomes sans everywhere** (this also reaches Interface, Board, Agents, Tunnel and Data files). That is safe because every consumer is prose or a status line, and values keep mono through `.cr-mono`/`<code>`. Even so, the Agents row's installed-version line and the Update row's `branch @ sha — subject` line become sans too. *Alternative:* add an opt-in `cr-cfg-row-desc` class on the Server-tab call sites only (about 6 JS edits) and leave the other tabs mono.
2. **Wrapping is global rather than Server-only (§2d).** *Alternative:* use the scoped fallback in §6, at the cost of some tabs still squeezing labels on phone.

## Review
_Reviewer: opus adversarial pass, 2026-11-17. Verified by grep plus `sed -n` ranges on the worktree, at e6acfe7 plus the uncommitted draft. No code was edited._

**Claims I confirmed against the code:**
- `readonlyField` is at `js:969-971`. Values are 16px because `.cr-mono` (`css:154`) sets only the family and nothing sets a size. The root is Source Sans at 16px (`app.css:84`).
- `.cr-cfg-row-sub` is 10px mono (`css:362`).
- In the Update row, the confirm is built inside `ctl` (`js:1255-1260`), and Check/Update are already dropped while `confirmText` is set (`js:1240`).
- All three hosts share `.cr-update-confirm`: `js:1256`, `js:1423` and `js:1535`.
- `panel.hidden` is toggled at `js:1424` and `js:1441`, and no author `display:` rule targets the card.
- No other web file uses `cr-cfg-row*`, `cr-readonly` or `cr-update-confirm`.
- The tests pin class strings only: `test_agents_ui.py:70`, and `test_cr_dialogs_config_exec.py:78` / `test_cr_dialogs_pending_rows.py:70` find rows by `.cr-cfg-row` plus `.cr-cfg-row-name`. Neither is affected.
- The fake DOM (`test_cr_dialogs_pending_rows.py:21-41`) has `parentNode` and a deep single-class `querySelectorAll`, so the proposed `confirmParent` probe works.
- All 3 proposed tests are genuinely red before the fix:
  - CSS: on base, `cr-cfg-row-sub` contains `--font-mono` and the row has no `flex-wrap`.
  - Update: on base, the parent is `cr-cfg-row-control`.
  - Resume: with the draft hunk reverted there is no `.cr-resume-all-list` and no `.cr-confirm-actions`, so `list_n` is 0 and `actions_btns` is `[]`.
- No test or README pins the literal `' — takes effect on restart'`. README:214 says "takes effect on restart" descriptively, so it is unaffected.
- `dist/` is untracked.

### Findings

**M1. §2d's claim that "every current control fits beside a 240px label, rows look the same" is false on desktop. The Agents row and the live Tunnel URL row newly wrap.**
- **Where:** `css:356-371` (proposed), with controls from `js:1559-1570` and `js:2081-2087`.
- **Repro:** The body width is 760 − 2 − 32 (`.cr-dialog-body` padding, `css:107`) − 140 nav − 16 gap = **570px**. With `flex: 1 1 240px` plus the 12px gap, the control must be ≤ 318px.
  - The Claude Agents row's control is `Doctor` + `Upgrade` + `Resume all prior terminals` (crBtn: 600 12px Inter, 12px side padding). That is about 68 + 75 + 203 ≈ **346px**, so the row wraps at 1280px.
  - The live Tunnel URL row (`cr-tunnel-cmdrow`: a `white-space: pre` URL of about 45ch at 11.5px mono, plus Copy and Rotate URL) is about 480px, so it also wraps.
  - Expected per the plan: the same as today on desktop. Actual: two rows change shape on desktop. Wrapping is arguably better for Tunnel URL, whose label is squeezed to about 70px today, but it is unplanned and was not in the visual check.
- **Fix direction:** keep global wrapping (decision 2 stands), but lower the label basis so that ordinary 3-button rows stay on one line, and add Agents to the visual check. Do NOT scope the wrap per tab.
- **Way:** in `.cr .cr-cfg-row-label`, set `flex: 1 1 200px; min-width: 0;`. That allows a control up to about 358px, so Agents fits; Tunnel URL still wraps, which is intended. Add "Config → Agents (Claude row) and Tunnel (tunnel on)" at 1280px to the §4 step-5 visual check.
- **Test:** the CSS test asserts that `.cr .cr-cfg-row-label {…}` contains `flex: 1 1 200px`. It is red on base, where the value is `flex: 1`. The width itself is verified visually; it is not unit-testable here.

**M2. §2d's claim that "this holds at any width" is false: a control wider than the body still overflows at phone width.**
- **Where:** `css:371` (`.cr .cr-cfg-row-control { flex: none; }`, which the plan keeps).
- **Repro:** Open Tunnel with the tunnel on, at 390px (body about 326px). The control's max-content is about 480px. `flex: none` cannot shrink, so once it wraps onto its own line it is still 480px wide. `.cr-dialog { overflow: auto }` then scrolls horizontally, and the Rotate URL button is off-screen. Expected: the control fits within the body, and `cr-tunnel-cmdrow` (already `flex-wrap: wrap`, with the URL `min-width: 0; overflow-x: auto`, `css:446-457`) reflows. This is pre-existing, but the plan claims it is fixed.
- **Fix direction:** let the control shrink only when it is alone on its line. On a shared line, flex line-breaking uses the max-content hypothetical size, so desktop rows are unaffected. Do NOT add a media query.
- **Way:** set `.cr .cr-cfg-row-control { flex: 0 1 auto; min-width: 0; max-width: 100%; margin-left: auto; }`.
- **Test:** the CSS test asserts that the `.cr .cr-cfg-row-control {…}` body has `min-width\s*:\s*0` and `max-width\s*:\s*100%`. It is red on base.

**M3. Missed by both: adjacent buttons in every row control touch each other with zero gap.**
- **Where:** the button pairs at `js:1182-1187` (Scheduled scan), `js:1244-1246` (Check for updates + Update and restart), `js:1339-1341` (Reinstall + Uninstall) and `js:1559-1570` (Doctor, Upgrade, Resume all).
- **Cause:** `h()` (`js:39-55`) creates no whitespace text nodes, and no rule spaces `.cr-btn` siblings (grep for `cr-btn +` finds nothing). So the pill borders abut.
- **Repro:** In Config → Server → Update, "Check for updates" and "Update and restart" render as one fused pill pair. This sits in the very panel the user screenshotted, and the plan does not touch it.
- **Fix direction:** add spacing between sibling buttons in a row control only. Do NOT change the control's `display` (it hosts segmented controls, sliders, textareas and the cmdrow).
- **Way:** add one rule after `.cr .cr-cfg-row-control`: `.cr .cr-cfg-row-control > .cr-btn + .cr-btn { margin-left: 6px; }`.
- **Test:** the CSS test asserts that `\.cr\s+\.cr-cfg-row-control\s*>\s*\.cr-btn\s*\+\s*\.cr-btn\s*\{[^}]*margin-left` exists. It is red on base.

**L1. The hidden-attribute guard is done the hard way. The file's own precedent is an explicit `[hidden]` rule.**
- **Where:** plan A3 and §5 ("no `display:` in any `.cr .cr-update-confirm {}` body"). The precedent is `css:622` (`.cr .cr-amap-pane[hidden] { display: none; }`).
- **Repro:** the plan's guard forbids a future `display` rule rather than making one harmless. Someone adding `display:flex` to the card for spacing would turn the test red, which reads as a false negative, and would have to rediscover why.
- **Fix direction:** make `[hidden]` win by specificity, and pin that rule. Do NOT forbid `display` on the card.
- **Way:** add `.cr .cr-update-confirm[hidden] { display: none; }` (0,3,0, which beats the (0,2,0) card rule) directly after `.cr .cr-update-confirm {…}`. Drop the A3 comment, or shorten it to "hidden via [hidden] rule below". Replace the test's no-display assertion with an assertion that this rule exists with `display\s*:\s*none`.
- **Test:** the new assertion is red on base, where there is no such rule. To prove it, temporarily add `display:flex` to `.cr .cr-update-confirm`. The `[hidden]` rule still wins; that is a manual check, and no extra test is needed.

**L2. The Agents confirm keeps its two buttons as bare direct children. The plan keeps a special-case CSS rule just for that, so the three hosts end up with two different action shapes.**
- **Where:** `js:1529-1535` and draft `css` `.cr .cr-update-confirm > button + button`.
- **Repro:** In Config → Agents → Upgrade with open sessions, "Upgrade and restart these" / "Cancel" sit left-aligned. Each one also gets `margin-top: 8px` from `> * + *`, because they are inline-block siblings. Expected: the same right-aligned action row as Resume all and Update. Conventions rule 4 says one shape, not forks.
- **Fix direction:** wrap the two Agents buttons in `.cr-confirm-actions`, and delete the `> button + button` rule. Keep the button labels, order, classes, the `{tty, session}` mapping (`test_agents_ui.py:72-76` regex-pins it) and the class string `cr-update-confirm cr-agents-confirm` (`:70`).
- **Way:** in `confirmBox()`, replace the two `kids.push(crBtn(...))` calls with `kids.push(h('div', { class: 'cr-confirm-actions' }, [crBtn('Upgrade and restart these', function () {…unchanged…}, 'cr-btn-danger'), crBtn('Cancel', function () { plan = null; paint(); })]));`. Keep the inner function body byte-identical so that the `test_confirm_sends_every_shown_copy` regex still matches.
- **Test:** `test_agents_ui` gets a new source assertion, `self.assertRegex(_agents_code(_src()), r"class: 'cr-confirm-actions' \}, \[crBtn\('Upgrade and restart these'")`. It is red before the edit. The existing tests must stay green unchanged.

**L3. Long command and path tokens overflow the confirm card at phone width.**
- **Where:** `js:1458` (resume-all `cannot[].command`) and `js:1511` (`cmdLines`).
- **Repro:** A `cannot` row whose `command` is `shlex.join(argv)` (`term_vt.py:4494`), for example `claude --resume 5f0c…-uuid` or a long quoted path, viewed at 390px. The card's inner width is about 300px. `code` has `white-space: normal` but no break opportunity inside a long token, so it runs past the card's right border. Expected: it wraps inside the card.
- **Fix direction:** allow breaking only inside the confirm card's `code` and the resume-row meta. Do NOT touch `.cr-tunnel-cmd`, which deliberately uses `white-space: pre` with horizontal scroll.
- **Way:** add `.cr .cr-update-confirm code, .cr .cr-resume-all-row-meta { overflow-wrap: anywhere; }` to the draft block.
- **Test:** none is unit-testable in the fake DOM. Verify it in the 390px visual check, with a stubbed long `command`, or with a real resume-all plan that has a `cannot` row.

**L4. §2f is order-sensitive, and the plan does not say so.**
- **Where:** proposed `.cr .cr-claude-login-status`, which has the same (0,2,0) specificity as `.cr .cr-cfg-row-sub`.
- **Repro:** if the implementer puts 2f above line 362, the base rule's `color` wins and 2f silently does nothing.
- **Fix direction:** place 2f after the `.cr .cr-cfg-row-sub` rule.
- **Way:** put it on the line directly after `.cr .cr-restart-note`.
- **Test:** the CSS test asserts that the index of `.cr .cr-claude-login-status {` in the assembled CSS is greater than the index of the first `.cr .cr-cfg-row-sub {`. It is red if the rule is misplaced, and trivially red on base, where the rule is absent.

**L5. Test-spec precision: the Update probe must be read in the confirm state, not in `before` or after "Update anyway".**
- **Where:** proposed `tests/test_update_settings_ui.py` `info()` extension.
- **Repro:** after the "Update anyway" click, the confirm is gone and `confirmParent` is `null`, so an implementer asserting on the wrong key gets a vacuous pass or fail.
- **Fix direction / way:** assert on `r["after_Update and restart"]["confirmParent"]` and `r["after_Update and restart"]["confirmActions"]`, and additionally assert `r["after_Update anyway"]["confirmParent"] is None`.
- **Test:** this is the test; it is red on base (`cr-cfg-row-control`).

**I1. Missed by both (out of scope, leave alone): the Tunnel Username/Password rows say "Applies live… — no restart." and also carry the restart note.**
- **Where:** `maskedRow`, `js:2108` and `js:2129` (both pass `restart = true`). The comment at `js:2121-2123` confirms that credentials now apply live.
- **Repro:** Config → Tunnel. After §2c/§2g, the contradiction becomes more visible, as its own orange "Takes effect on restart" line under "no restart".
- **Direction:** no change in this PR. Contract clause 2 is the Server panel. Mention it in the PR body and offer it to the user as a one-word follow-up (`true` → `false` at both call sites).
- **Test:** none now.

**I2. Accepted as-is.**
- **Decision 1 (sans everywhere):** I checked every `cr-cfg-row-sub` producer. The only value-like fragments are the Update line's 7-char SHA, the Agents version, the service pid, port and paths (`js:1320-1330`) and the Agents stop-line `cwd` (`js:1517`). All are embedded in prose. They read fine in sans, and no bare path or command uses the class. No change.
- **`.cr-help-note` / `.cr-tunnel-block-note`:** they stay 11/10.5px mono prose on Tunnel and Notifications. That is out of scope; leave them and note it in the PR.
- **The plan's line "every token is redefined in the dark block":** this holds except for `--font-sans` and `--font-mono`. Those are defined once at `ext_cr.css:210-212` and need no dark value, so it does not matter.
- **Comment caution:** any new CSS comment must not contain `*/` mid-text. That is the known gate blind spot; `test_page_css` catches only some shapes of it.

### Overall clean plan
Everything is in `aitracker/web/ext_cr_dialogs.css`, `aitracker/web/ext_cr_dialogs.js` and 4 test files. No `.py` or server change, and no `dist/` edit. Every server sentence is rendered verbatim. Button labels and order are unchanged.

**CSS, the config-row block (`css:356-372`). Edit these rules in place:**
1. `.cr .cr-cfg-row`: add `flex-wrap: wrap;`, keeping `display: flex; align-items: center; gap: 12px; padding; border-bottom`.
2. `.cr .cr-cfg-row-label { flex: 1 1 200px; min-width: 0; }` (M1).
3. `.cr .cr-cfg-row-sub { font: 400 11.5px/1.45 var(--font-sans, sans-serif); color: var(--text-muted, #877866); margin-top: 2px; }` (§2a).
4. `.cr .cr-restart-note { display: block; margin-top: 3px; font: 600 10.5px/1.3 var(--font-sans, sans-serif); color: var(--text-awaiting, #9A4F19); }` (§2c).
5. Directly after it: `.cr .cr-claude-login-status { color: var(--text-secondary, #4A4237); }` (§2f; it must come after rule 3, per L4).
6. `.cr .cr-cfg-row-control { flex: 0 1 auto; min-width: 0; max-width: 100%; margin-left: auto; }` (M2).
7. New, right after it: `.cr .cr-cfg-row-control > .cr-btn + .cr-btn { margin-left: 6px; }` (M3).
8. `.cr .cr-readonly { color: var(--text-muted, #877866); font-size: 12px; line-height: 1.4; }` (§2b; it stays mono via `.cr-mono`).

**CSS, the draft block at the end of the file:**
9. Update the comment to: `/* Confirm panels (Resume all, Agents upgrade, Update row): a readable card. Hidden via the [hidden] rule below. */`. It must contain no `*/` except at its end.
10. Keep `.cr .cr-update-confirm {…}` as drafted, with no `display`.
11. Add `.cr .cr-update-confirm[hidden] { display: none; }` (L1).
12. Keep `.cr .cr-update-confirm > * + * { margin-top: 8px; }`.
13. **Delete** `.cr .cr-update-confirm > button + button {…}` (L2) and `.cr .cr-update-confirm > .cr-cfg-row-sub {…}` (A2).
14. Keep `.cr .cr-update-confirm-text`.
15. Add `.cr .cr-cfg-row > .cr-update-confirm { flex: 1 1 100%; margin-top: 0; }` (§2e).
16. Keep the `.cr-resume-all-list`, `-row`, `-row:last-child`, `-row:hover`, `-row input`, `-row-text`, `-row-title`, `-row-meta` and `-note` rules as drafted.
17. Add `.cr .cr-update-confirm code, .cr .cr-resume-all-row-meta { overflow-wrap: anywhere; }` (L3).
18. Rename `.cr .cr-resume-all-actions` to `.cr .cr-confirm-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 6px; padding-top: 2px; }` (A1/A2).

**JS (`ext_cr_dialogs.js`):**
19. `cfgRow()` at `:924`: change `' — takes effect on restart'` to `'Takes effect on restart'` (§2g).
20. `resumeAllWidget` at `:1464`: change `'cr-resume-all-actions'` to `'cr-confirm-actions'` (A1). Keep the rest of the draft hunk as is.
21. `updateBlock.paint()` at `:1255-1261`: run `wrap.appendChild(ctl);` first. Then, if `confirmText` is set, append to `wrap` a `div.cr-update-confirm[role=alertdialog]` that contains:
    - `div.cr-update-confirm-text` holding `confirmText`, and
    - `div.cr-confirm-actions` holding `[crBtn('Update anyway', …same handler…, 'cr-btn-danger cr-update-yes'), crBtn('Cancel', …same…, 'cr-update-no')]`.

    This is exactly the §2h code shape (§2h).
22. `agentsBlock.confirmBox()` at `:1529-1534`: wrap the two existing `crBtn(...)` calls, byte-identical inside, in a single `kids.push(h('div', { class: 'cr-confirm-actions' }, [ … , … ]));` (L2).
23. Run `node --check aitracker/web/ext_cr_dialogs.js`.

**Tests (each one shown red by reverting its fix, then green):**
24. `tests/test_page_css.py`, new `test_config_rows_and_confirm_card`. Run it on `_extract_style_content(_read_page())` and assert:
    - (a) The first `\.cr\s+\.cr-cfg-row-sub\s*\{([^}]*)\}` body has `--font-sans` and no `--font-mono`.
    - (b) The `\.cr\s+\.cr-cfg-row\s*\{` body has `flex-wrap\s*:\s*wrap`.
    - (c) The `\.cr\s+\.cr-cfg-row-label\s*\{` body has `flex\s*:\s*1 1 200px`.
    - (d) The `\.cr\s+\.cr-cfg-row-control\s*\{` body has `min-width\s*:\s*0` and `max-width\s*:\s*100%`.
    - (e) A `\.cr\s+\.cr-cfg-row-control\s*>\s*\.cr-btn\s*\+\s*\.cr-btn\s*\{[^}]*margin-left` rule exists.
    - (f) The `\.cr\s+\.cr-readonly\s*\{` body has `font-size`.
    - (g) A `\.cr\s+\.cr-update-confirm\[hidden\]\s*\{[^}]*display\s*:\s*none` rule exists.
    - (h) The index of `.cr .cr-claude-login-status {` is greater than the index of `.cr .cr-cfg-row-sub {`.
25. `tests/test_update_settings_ui.py`:
    - Extend `info()` with `confirmParent` (the className of the `.cr-update-confirm`'s `parentNode`, or `null`) and `confirmActions` (the count of `.cr-confirm-actions` inside it).
    - In `test_409_needs_confirm_then_reposts_confirmed_then_reload`, assert that `"cr-update-block"` is in `r["after_Update and restart"]["confirmParent"]`, that `"cr-cfg-row-control"` is not in it, and that `confirmActions == 1`.
    - Also assert `r["after_Update anyway"]["confirmParent"] is None`.
    - The existing `buttons == ["Update anyway", "Cancel"]` assertion stays unchanged.
26. `tests/test_resume_all_ui.py`: add `OUT.list_n`, `OUT.row_n` and `OUT.actions_btns` (on `cr-confirm-actions`) after `OUT.panel_text`, plus `test_panel_structure` asserting `1`, `2` and `["Resume 1 ticked", "Cancel"]`.
27. `tests/test_agents_ui.py`: add an assertion to `test_confirm_flow` for `class: 'cr-confirm-actions' }, [crBtn('Upgrade and restart these'`.

**Gate:** run `unset TRACKER_AUTH; python -m unittest tests.<m>` per module, for each of `test_page_css`, `test_update_settings_ui`, `test_resume_all_ui`, `test_agents_ui`, `test_claude_login_settings_ui`, `test_cr_dialogs_config_exec`, `test_cr_dialogs_pending_rows`, `test_cr_readonly_ui`, `test_cr_registry_fields`, `test_cr_manage_terminals_parity` and `test_page_bundle`. Then run `make check` before the push, one module per process if it gets OOM-killed. No existing assertion is edited.

**Visual check:** run a foreground server from the worktree on a free port (never `pkill`, never touch the 8790 service), and stop it by PID afterwards. Check at 1280, 720 and 390px, in light and dark:
- Config → Server (all rows).
- Config → Agents, the Claude row: at 1280px it should be on one line.
- Config → Tunnel with the tunnel on, the Tunnel URL row: it wraps under the label at 1280px, and at 390px it has no horizontal scroll.
- Config → Board, the Scheduled scan buttons, which should be spaced.
- Manage terminals → Resume all prior terminals.

**Risky spot and fallback:**
- **Risk:** global wrapping (rules 1, 2 and 6). If any desktop row other than Tunnel URL wraps in the visual check, first lower the label basis to `180px`.
- **Fallback if that is not enough:** the plan's §6 scoped wrap, applied to Server blocks plus `@media (max-width: 600px)`. Keep M2 and M3 regardless, because they are independent.

**Unchanged decisions:** decision 1 (sans everywhere) stands. Decision 2 (global wrapping) also stands, with the M1 basis and M2 shrink folded in.

**New optional decision:** I1, fixing the masked-row restart contradiction on the Tunnel tab. It is out of the contract, so the default is to leave it.

## Reconciliation
_Main thread, 2026-11-17. Judged against the code (`css:134-142` `.cr-btn` has no margin; `css:371` control is `flex: none`; `css:622` `[hidden]{display:none}` pattern exists)._

| # | Finding | Verdict | Action |
|---|---|---|---|
| M1 | Agents (3 buttons) / Tunnel URL rows wrap on desktop with a 240px label basis | **confirmed** | label `flex: 1 1 200px`; both rows in the visual check |
| M2 | `flex: none` control can't shrink → Tunnel URL overflows at 390px | **confirmed** | control `flex: 0 1 auto; min-width: 0; max-width: 100%; margin-left: auto` |
| M3 | adjacent row buttons touch | **overstated** (screenshot shows some pairs already spaced) — fix is one harmless line | keep `.cr-cfg-row-control > .cr-btn + .cr-btn { margin-left: 6px }` |
| L1 | "no `display:`" guard is a comment, not a rule | **confirmed** | add `.cr .cr-update-confirm[hidden] { display: none; }` (file's own pattern) |
| L2 | move Agents confirm buttons into `.cr-confirm-actions` | **overengineered fix** — rewires Agents JS outside the contract | **dropped**; keep `> button + button { margin-left: 6px }` |
| L3 | long commands overflow the card | **confirmed** | `overflow-wrap: anywhere` on `.cr-update-confirm` |
| L4 | login-status colour rule must follow `.cr-cfg-row-sub` | **confirmed** | order it after the base rule |
| L5 | Update test must assert the confirm state, not post-click | **confirmed** | as stated |
| I1 | Tunnel Username/Password show "takes effect on restart" though they apply live | **out of scope** | leave; note in the commit message |

**Missed by both:** none found that changes the plan. Tests can't see real rendering → a browser check at desktop + 390px on a throwaway port is part of the gate.

**Reconciled plan = reviewer's `### Overall clean plan` minus L2 (Agents confirm JS untouched).**

**Decisions for the user (defaults in bold):**
1. Config row descriptions sans 11.5px on **every Config tab (default)** vs Server tab only.
2. Rows **wrap globally, with the M1/M2 fixes (default)** vs Server blocks only + all rows at ≤600px.


## Implementation
_Sonnet implementer, 2026-11-17. Not committed, not pushed. Reconciled plan minus L2._

**Files changed**
- `aitracker/web/ext_cr_dialogs.css`: config-row block (~L356-376: row `flex-wrap`, label `1 1 200px`, sub sans 11.5/1.45, restart-note block, login-status colour after sub, control `0 1 auto`/min-width 0/max-width 100%/margin-left auto, `.cr-btn + .cr-btn` margin, readonly 12px); confirm-card block at end (comment, `[hidden]` rule, `.cr-cfg-row > .cr-update-confirm` full width, `.cr-confirm-actions` rename + flex-wrap, `code`/meta `overflow-wrap: anywhere`; the `> .cr-cfg-row-sub` draft rule deleted).
- `aitracker/web/ext_cr_dialogs.js`: `cfgRow()` restart note text -> `Takes effect on restart` (~L924); `updateBlock.paint()` confirm now a sibling appended after `ctl` with `.cr-confirm-actions` (~L1255); `resumeAllWidget` actions class -> `cr-confirm-actions` (~L1470).
- Tests: `tests/test_page_css.py` `test_config_rows_and_confirm_card`; `tests/test_update_settings_ui.py` (`info()` gains `confirmParent`/`confirmActions`, asserts added in the 409 test); `tests/test_resume_all_ui.py` `test_panel_structure`.

**RED -> GREEN proofs (scoped revert, then restored byte-identical)**
- sub back to mono: `test_config_rows_and_confirm_card` fails `'--font-sans' not found`.
- `[hidden]` rule removed: same test fails (regex for `.cr-update-confirm[hidden] {display:none}` not found).
- Update confirm moved back into `ctl`: `test_409_needs_confirm_...` fails `'cr-update-block' not found in 'cr-cfg-row-control'`.
- Resume actions class reverted: `test_panel_structure` fails `[] != ['Resume 1 ticked', 'Cancel']`.

**Gate (one module per process, all OK):** test_page_css 7, test_update_settings_ui 16, test_resume_all_ui 12, test_agents_ui 12, test_claude_login_settings_ui 22, test_cr_dialogs_config_exec 1, test_cr_dialogs_pending_rows 1, test_cr_readonly_ui 10, test_cr_registry_fields 62, test_cr_manage_terminals_parity 19, test_page_bundle 12. `node --check` OK; CSS comment open/close counts balanced (36/36).

**Deviations**
- L2 dropped per reconciliation: Agents confirm JS untouched, `.cr-update-confirm > button + button` kept; no `test_agents_ui` assertion (item 27) added.
- Not done: browser visual check at 1280/720/390px (not run by this agent). Do it before push; if a desktop row other than Tunnel URL wraps, lower the label basis to 180px.
- I1 (Tunnel restart note on live-applied fields) left alone; mention in commit message.

## Implementation review
_Opus adversarial pass, 2026-11-17. I assumed the implementer's report was false. I checked it with `git diff -- <file>` one file at a time, plus grep and `sed -n` ranges. No code was edited. Every revert I made for a red proof was restored, and the `git diff | shasum` checksum was `4a4bf903…` both before and after._

**Verdict: clean against the reconciled plan (the Overall clean plan minus L2).** I found two low findings and one note on visual evidence. None of them blocks the push.

**What I verified myself:**
- **Plan coverage.** Each CSS item (1–8 and 9–18, with L2's deletion of `> button + button` correctly not done) is present in `aitracker/web/ext_cr_dialogs.css`:
  - L357: row `flex-wrap`
  - L360: label `1 1 200px`
  - L362: sub `400 11.5px/1.45` sans
  - L363: restart-note block
  - L364: login-status colour, placed after the sub rule (L4)
  - L372–373: control `0 1 auto` / `min-width: 0` / `max-width: 100%` / `margin-left: auto`, and the `.cr-btn + .cr-btn` margin
  - L374: readonly 12px
  - the end-of-file block, with the comment balanced, the `[hidden]` rule, `.cr-cfg-row > .cr-update-confirm`, `.cr-confirm-actions`, and `overflow-wrap: anywhere`
- **JS items.** JS items 19, 20 and 21 are present. Item 22 (Agents) is correctly untouched. I found no drive-by edits in either source file.
- **Update row.** The button labels, order, classes and both click handlers are byte-identical to base; only the indentation changed. `confirmText` still renders verbatim. The confirm is now a child of `.cr-cfg-row.cr-update-block`, after `ctl`.
- **`[hidden]` rule.** `.cr .cr-update-confirm[hidden]` has specificity (0,3,0). No rule sets `display` on `.cr-update-confirm`, `.cr-resume-all-confirm`, `.cr-agents-confirm` or `[role=alertdialog]`, in any web CSS file (grep). `.cr .cr-cfg-row > .cr-update-confirm` (0,3,0) sets no `display`. The Agents confirm and `ra.panel` mount on `.cr-agents-block`, not on a `.cr-cfg-row`, so the full-width rule reaches only the Update confirm.
- **Load-time safety.** `node --check` passes. In the CSS, `/*` and `*/` both count 36, and `{` and `}` both count 270.
- **Tokens and dark mode.** Every token used is defined in the light `.tracker-next` block and redefined in `.tracker-next.is-dark` (`ext_cr.css:57-102` and `:319-363`), and each use has a fallback. `--radius-md-min` is defined once (`:297`), the same as at its other uses.
- **Red proofs I ran myself.** I made each revert with a scoped Edit, then restored it exactly:
  - (1) The Update confirm moved back into `ctl`: `test_409_needs_confirm…` fails with `'cr-update-block' not found in 'cr-cfg-row-control'`.
  - (2) The control rule reverted to `flex: none`: `test_config_rows_and_confirm_card` fails because `min-width\s*:\s*0` is not in `' flex: none; '`.
  - (3) The `.cr-cfg-row-control > .cr-btn + .cr-btn` rule removed: the same test fails on that regex.
- **Gate.** I ran each module in its own process, with `TRACKER_AUTH` unset. All were OK: `test_page_css`, `test_update_settings_ui`, `test_resume_all_ui`, `test_agents_ui`, `test_claude_login_settings_ui`, `test_cr_dialogs_config_exec`, `test_cr_dialogs_pending_rows`, `test_cr_readonly_ui`, `test_cr_registry_fields`, `test_cr_manage_terminals_parity` and `test_page_bundle`.
  - Nothing in `tests/` pins `' — takes effect on restart'` or `cr-resume-all-actions`. `test_cr_registry_fields.py:739` mentions the text only in a docstring.
- **Rendering evidence (headless Chrome).** I used the CSS that `page.build_page()` assembles, applied to a static mock of `.tracker-next > .cr > .cr-dialog-wide > .cr-cfg-main` holding the Agents, Update (with confirm) and Port rows. This is not the live SPA.
  - At 1280px, the Agents row (Doctor + Upgrade + Resume all prior terminals) does **not** wrap: label 223px, control 335px of the 570px body. M1 holds even with M3's added margins.
  - The Update confirm is 570px wide, below the label.
  - The restart note has `display: block`.
  - The `hidden` card computes `display: none`, and the shown card computes `display: block`.
  - A 75-char `code` token stays inside the card (L3).
  - In dark mode, the card background is `#1A1714` and the text is `#FBFAF7`.
  - At the headless minimum viewport (500px), `dialog.scrollWidth == clientWidth` (466px), so there is no horizontal scroll, and the Agents control wraps under its label.
  - **Not covered:** the real Tunnel URL row, exactly 390px, and real data. That part of the browser check is still owed.

### Findings

**R1 (low): the §2f colour rule leaks into the Claude login modal.**
- **Defect.** `.cr .cr-claude-login-status` (`ext_cr_dialogs.css:364`) also matches `statusEl` in the login dialog (`ext_cr_dialogs.js:1693`, `h('div', { class: 'cr-claude-login-status' }, ['Complete the login in the terminal below…'])`). The plan assumed this class only marks the Config row's status line (`js:1632`).
- **Repro.** Config → Server → Log in. Actual: the modal's status sentence turns `--text-secondary` (`#4A4237` light) instead of inheriting the dialog's text colour. Expected: the modal is unchanged, since it is outside the contract.
- **Fix direction.** Scope the rule to the Config row. Do NOT change the modal's markup or the row's class string (`test_claude_login_settings_ui` pins `cr-claude-login-status`).
- **The way:**
  - Change `css:364` to `.cr .cr-cfg-row-sub.cr-claude-login-status { color: var(--text-secondary, #4A4237); }`. The specificity becomes (0,3,0), so it beats the base rule regardless of order, which also retires L4's order hazard.
  - In `tests/test_page_css.py:371`, replace the index comparison with `self.assertRegex(css, r"\.cr\s+\.cr-cfg-row-sub\.cr-claude-login-status\s*\{[^}]*--text-secondary")`.
- **Test.** That regex is red on the current tree, where the selector is unscoped, and green after the edit.

**R2 (low, plan deviation): the test keeps the "no `display:`" guard that L1 replaced.**
- **Defect.** `tests/test_page_css.py:372-373` loops over every `.cr .cr-update-confirm {…}` body and asserts it has no `display:`. Reconciled item 24 lists only (a)–(h). L1 (confirmed) said to *replace* that guard with the `[hidden]` rule assertion, because the `[hidden]` rule (`css:671`) already makes a future `display` declaration harmless.
- **Repro.** Add `display: flex;` to `.cr .cr-update-confirm`. Actual: the test goes red, a false negative, even though `[hidden]` still wins. I confirmed in headless Chrome that `[hidden]` computes `display: none`. Expected: green.
- **Fix direction.** Delete the two lines. Keep assertion (g), the `[hidden]` regex at `:370`.
- **The way.** Remove `for m in re.finditer(r"\.cr\s+\.cr-update-confirm\s*\{([^}]*)\}", css):` and its `assertNotRegex` line.
- **Test.** Assertion (g) is the test. It was already shown red (implementer: `[hidden]` rule removed → fails). After the deletion, `test_page_css` stays green.

**R3 (no change): the empty `ctl` still takes a 12px gap while the Update confirm is shown.**
- **Defect.** In `js:1255`, `ctl` is appended even when `confirmText` empties it. Measured effect: label 558px instead of 570px, which is not visible.
- **Direction.** Leave it as is. Appending `ctl` unconditionally keeps `paint()` simple, and the tests read `.cr-cfg-row-control` for the buttons.

**Owed before push (not a code defect):** the real browser check in the reconciled plan. Run a foreground server on a free port and check Config → Tunnel with the tunnel on (the URL row), Config → Board (scheduled-scan buttons) and 390px. Then run `/branch-sync`, run the gate again, and push.
