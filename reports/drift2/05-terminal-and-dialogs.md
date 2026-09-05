# Adversarial re-audit — 05 · Terminal and dialogs

Scope: `aitracker/web/ext_cr_term.js`, `ext_cr_term.css`, `ext_cr_dialogs.js`, `ext_cr_dialogs.css`,
`ext_vt.js`, `ext_vt.css`, cross-checked against `term_run.py`, `term_vt.py`, `term_gate.py`,
`term_launch.py`. Doc: `05-terminal-and-dialogs.md` (100%), `04-coverage-and-help.md` (Help/Config
terminal-related rows, "Terminals at the cap").

Method: read the real code and followed every handler to its actual server round trip; comments
were not trusted as evidence.

## Area 1 — the full control set (per control)

| Control | Doc | Exists | Wired to | Verdict | Severity |
|---|---|---|---|---|---|
| Open terminal here | solid, primary | yes | `_openInline(sid,"cwd")` → `ExtVT.mountInto` → `/api/term/pty` (ext_cr_term.js:283,449-528) | MATCH | — |
| Resume terminal here | outline, hidden unless resumable | yes | same path, mode="resume"; hidden via `isClaudeId()` (ext_cr_term.js:284,877-878) | MATCH | — |
| ↗ External terminal | hidden off-localhost | yes | POST `/api/term/open` (ext_cr_term.js:540-550), route registered term_launch.py:229 | MATCH | — |
| ↗ External resume | hidden off-localhost, Claude-only | yes | same route, mode="resume"; gated `isClaudeId` (ext_cr_term.js:893) | MATCH | — |
| ⤢ New tab | disabled until attached | yes | builds `?tty=` URL, `window.open` (ext_cr_term.js:553-563) | MATCH | — |
| + New terminal | directory picker, mode cwd | yes | `_openDirectoryPicker("cwd")` → `/api/term/cwds` → `/api/term/pty` (ext_cr_term.js:566-623) | **see Area 4 — dialog itself is broken** | HIGH |
| + New Claude session | directory picker, mode new | yes | `_openDirectoryPicker("new")`, same pipe | **see Area 4** | HIGH |
| ☰ Manage terminals + badge | live count | yes | `/api/term/list`, badge synced every 2s poll (ext_cr_term.js:664-725) | MATCH (dialog content has a naming issue, see Area 4) | — |
| renderer segmented xterm/grid | | yes | `_setRenderer` → `handle.setRenderer` (ext_cr_term.js:728-745, ext_vt.js:3272-3278) | MATCH | — |
| ☀️ Theme | | yes | `_cycleTheme` → `ctx.theme.set` (ext_cr_term.js:756-766) | MATCH | — |
| Status: model pill | only while CLI foreground | yes | polls `/api/term/attached`, hidden by `!st.attached` (ext_cr_term.js:924,982-990) | MATCH | — |
| Status: effort pill | same gate | yes | same | MATCH | — |
| Status: ⧉ Copy | | yes | `handle.copyBuffer()` + clipboard w/ fallback (ext_cr_term.js:797-838) | MATCH | — |
| Status: ■ Kill | brick-tinted | yes | POST `/api/term/close` (ext_cr_term.js:842-850), CSS brick tint (ext_cr_term.css:366-370) | MATCH | — |
| Config / Help header pills | | yes | `ctx.dialog("config"/"help")` (ext_cr_term.js:281-282) | MATCH | — |
| Close (✕) | detaches, doesn't kill | yes | `close()` calls `handle.destroy()` only, never `/api/term/close` (ext_cr_term.js:390-411) | MATCH | — |

Nothing from the doc's control-bar table is missing or unreachable. One control (**+ New
terminal** / **+ New Claude session**) opens a dialog whose core list is non-functional — see Area 4.

## Area 4 — every dialog (per dialog)

| Dialog | Title | Body | Buttons / order | Handler followed | Verdict | Severity |
|---|---|---|---|---|---|---|
| Manage terminals | "Manage terminals — N of M running" | rows: title-fallback · project · age · peek · ✕ kill; footer note + Close all→inline confirm | peek→new tab, ✕ kill→POST `/api/term/close`, Close all→confirm→loop-POST close (ext_cr_dialogs.js:1471-1518) | Row label falls back to **raw session UUID**, not a resolved title — see finding #2 below | DRIFT | MEDIUM |
| Cap reached | "N of M running — free a slot", `--surface-failed` header | same list/renderer as above (alias) | same, but onKill also closes dialog + replays the original request (ext_cr_term.js:625-662) | same row-naming issue inherited | DRIFT | MEDIUM |
| **Directory picker** | "New terminal / New Claude session — choose a directory" | recent cwds list + free-text field | pick row → `onPick(p)` → `_pickDirectory` → POST `/api/term/pty` | Server returns `cwds:[{path,label,mtime}]` (term_vt.py:2420-2470); client renders each row with `text: p` and calls `onPick(p)` treating `p` as a plain string (ext_cr_dialogs.js:1527-1552, fed from ext_cr_term.js:580-596) — every recent-directory button shows **`[object Object]`** and, if clicked, POSTs cwd `"[object Object]"`, which cannot exist on disk and silently fails ("Failed to open a terminal there."). Only the free-text field works. | **DROPPED CONTROL (broken, not dropped in markup)** | HIGH |
| Model | ladder list | picks write `/model <name>` | `onPick`→`_injectSlash`→POST `/api/term/inject` (real route, term_vt.py:3008,3337) | Fully wired — contradicts the briefing's "disabled, no route" note; matches doc exactly | MATCH | — |
| Effort | ladder list | `/effort <level>` | same pipe | MATCH | — |
| Config (Terminal section only, in scope) | rows: renderer/max/enabled/app/allowlist | env chips render the real `TRACKER_TERM_*` names (ext_cr_dialogs.js:779-788) | writes via POST `/api/config` (real, config.py) | "Terminal enabled" never shows the doc-mandated "— takes effect on restart" note (doc 04 says **yes**) because server-side `RESTART_REQUIRED` only contains `PORT`/`HOST` (config.py:184-185) | DRIFT | MEDIUM |
| Config → Server (Port/Host rows) | mono read-only fields | | | `cfgRow('Port',...)` / `cfgRow('Host',...)` never pass the 5th `restart` arg (ext_cr_dialogs.js:1134-1137), so no restart note renders even though doc 04 marks both **yes** and the server's own `RESTART_REQUIRED` agrees | DRIFT | LOW-MEDIUM |
| Help (Terminal tab, in scope) | keyboard/copy/renderer/model-effort reference | | | Content matches doc's terminal behaviours verbatim (ext_cr_dialogs.js:565-574) | MATCH | — |
| Fork lineage | "Fork lineage", header context = session id | "This session continues as X." / "Continued from Y." | link → `onOpen(targetSid)` → navigate (ext_cr_term.js:855-867, ext_cr_dialogs.js:1613-1630) | Shows parent/copy links; "which one you are on" is only implied by the raw session-id string in the header, never stated in words in the body | DRIFT | LOW |

All dialogs share one focus-trap/Escape/backdrop/opener-restore implementation
(`CR.dialogs.open/close`, `trapFocus`, ext_cr_dialogs.js:328-431) — verified generic, applies to
every REGISTRY entry. The terminal overlay itself (a dialog outside that registry) reimplements
the same three mechanics directly and correctly: opener capture/restore, `CR.dialogs.trapFocus`
reuse, Escape listener, backdrop-mousedown-to-close (ext_cr_term.js:68-77, 228-231, 356-411).
**MATCH for every dialog including the terminal overlay.**

## Other checks

- **Lazy xterm invariant — MATCH.** `_loadXtermAssets()` (ext_vt.js:1632) is only reached via
  `XtermTerminal._build()` (ext_vt.js:1755), only constructed inside `mountInto`'s `attachRenderer`
  (ext_vt.js:3248-3270), only called from `finish()` after a real network resolution (list scan or
  spawn), only triggered by `CR.term.open()` on a user action. `CR.term.mount()` only builds DOM
  (ext_cr_term.js:1024-1032). No static `<script src=".../xterm...">` anywhere (index.html, page.py,
  server.py all grepped clean).
- **Native dialogs — zero in the new chrome.** `ext_cr_term.js`/`ext_cr_dialogs.js` grepped clean
  for `alert(/confirm(/prompt(`. Two `alert(` calls do exist, but in `ext_vt.js:2861` and
  `ext_vt.js:3114` — the **classic** modal's own `openNewTab()`/`peekTerm()`, pre-existing,
  unmodified, not reachable from the Control Room's own reimplementations of those actions (which
  use `showToast`, ext_cr_term.js:553-563,690-699). LOW — flagged for completeness since ext_vt.js
  was in scope, but out of the redesign per the handoff's own "classic dashboard is not modified"
  rule.
- **Read-only toward sessions — MATCH.** No write path to `~/.claude/**` or `~/.augment/**` in
  `term_run.py`/`term_vt.py`/`term_gate.py`/`term_launch.py` (only globs/reads for cwd/session
  resolution).
- **Colour never carries meaning alone — MATCH.** Every terminal status control (kill, model/effort
  pills, notice banner, badge) pairs colour with text.
- **Dedupe on session+mode, close-detaches-not-kill, notice-banner mount-point ownership, renderer
  blank-pane caveat — all MATCH**, verified against `mountInto`'s real resolution/finish logic and
  `ext_cr_term.js`'s `close()`/`_killCurrent()` split.
- **Briefing correction (not drift):** the settled-decision note that "terminal model/effort
  switching are DISABLED, no server route" does not hold for the terminal's own dialogs — they call
  a real, registered route (`/api/term/inject`, term_vt.py:3337) exactly as doc 05 specifies. The
  disabled `cr:model-pick`/`cr:effort-pick` bus fallbacks in `ext_cr_boot.js:758-763` are dead code
  for a *different*, unreachable call shape (`cr_detail.js`'s Evidence-panel mirror, which is never
  invoked because that panel stays hidden). Likewise `cr:stop` is wired to a real route
  (`/api/term/kill`, term_run.py:613). This is a MATCH against doc 05, not a gap — noted only
  because it contradicts the briefing.

## Fix list

1. **HIGH** — Directory picker: map `res.j.cwds` (`{path,label,mtime}`) to plain path strings
   before handing to the dialog, or render `p.label`/`p.path` and pass `p.path` to `onPick`.
   Files: `aitracker/web/ext_cr_term.js:583` (or 1538-1543/1527-1552 of `ext_cr_dialogs.js`).
2. **MEDIUM** — Manage terminals / Cap reached: resolve `t.session` against the app's live
   `sessions` list (title/project), falling back to a short id — same pattern already proven in
   `ext_vt.js:2500-2507` (`buildTermRow`) and `ext_cr_boot.js:796` (flags list) — instead of the raw
   uuid. Files: `ext_cr_dialogs.js:1496`, callers in `ext_cr_term.js:679-685,647-650`.
3. **MEDIUM** — Config → Terminal enabled: either add `TERMINAL` to `config.py`'s
   `RESTART_REQUIRED` if it genuinely needs one (matching doc 04), or, if it truly applies live
   (which the code's own comments claim), drop doc 04's "yes" instead of leaving the UI silently
   disagreeing with the spec. File: `aitracker/config.py:184-185`.
4. **LOW-MEDIUM** — Config → Port/Host rows: pass `restart=true` to `cfgRow(...)` for both, matching
   `RESTART_REQUIRED` and doc 04. File: `ext_cr_dialogs.js:1134-1137`.
5. **LOW** — Fork lineage: state explicitly in the body which session is the one open now (e.g. "You
   are on `<sid>`"), not only via the header's raw id. File: `ext_cr_dialogs.js:1613-1630`.
