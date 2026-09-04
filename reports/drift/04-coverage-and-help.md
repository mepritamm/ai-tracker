# Drift report — 04-coverage-and-help.md vs. shipped Control Room

Spec: `design_handoff_control_room/README.md` + `04-coverage-and-help.md` (234 lines, the capability
map + modals + Help/Config), cross-checked against `02-shell-and-board.md`, `03-detail-view.md`,
`05-terminal-and-dialogs.md` where a capability's "home" lives there. Where the prototype and this
documentation disagree, **the documentation wins** (README:21).

Implementation read in full: `ext_cr_board.js`(1930)/`.css`(1301), `ext_cr_boot.js`(1069)/`.css`(200),
`ext_cr_detail.js`(2292)/`.css`(1367), `ext_cr_dialogs.js`(1756)/`.css`(566), `ext_cr_term.js`(1022)/
`.css`(436), plus `registry.py`, `config.py`, `providers/*.py`, and the shipped project `README.md`
(itself a coverage claim: "every capability in the project README has a home in the new UI").

This audit was produced by three parallel sub-audits (board/rail/top-bar; detail view; dialogs) and
cross-checked against three **existing** drift reports already on disk for the adjacent docs —
`reports/drift/02-shell-and-board.md`, `03-detail-view.md`, `05-terminal-and-dialogs.md` — which carry
deeper component-level detail than this doc's scope requires. Where a doc-04 capability's true home is
one of those docs, this report cites the existing report rather than re-deriving it, and only pulls a
finding forward into Table A/B when it changes a doc-04 capability's reachability verdict.

Verdict legend — Table A: PRESENT / PARTIAL / MISSING. Table B: MATCH / DRIFT / MISSING / EXTRA.
Severity: HIGH / MED / LOW.

---

## Table A — Capability map (60 items)

### Board (replaces the sidebar)

| # | Capability (doc 04 wording) | Home in new UI (file:line) | Verdict | Severity |
|---|---|---|---|---|
| 1 | Every session, all tools, newest first | `ext_cr_board.js:217-237` `boardTiles()`, `:59-64` `railOrder()` — comparator matches doc byte-for-byte | **PARTIAL** | HIGH |
| | | **Real gap** (self-documented, `ext_cr_board.js:217-223`, per `reports/drift/02-shell-and-board.md` §7.4): an agent session with `agent:true` and an **empty** `group` string is excluded from the individual-tile list *and* never picked up by `agentGroups()` (which requires a truthy `group`) — it vanishes from the **board** entirely regardless of state. Code comment: "Verified live: 950 sessions, 1 working, 0 tiles." The rail (`railOrder()`) is unaffected — the session is still reachable there. | | |
| 2 | Source badge (7 sources) | `ext_cr_board.js:311-318` `toolLabel()` (lowercased "claude cli" form), used `:1604,1688` | PRESENT | — |
| 3 | Live dot + 5-minute live window | `ext_cr_board.js:23` `LIVE_WINDOW` (derived from shared `LIVE`, not re-declared), `sessionState()` `:50`; dot pulse scoped to `.is-working` | PRESENT | — |
| 4 | Waiting-on-answer end-state | `ext_cr_board.js:231-236` (`hero=true`, only on `tiles[0]` when awaiting), `:1660` `.cr-tile--hero.cr-tile--span2`; frame `ext_cr_board.css:872-908` | PRESENT | — |
| 5 | Just-completed end-state | `ext_cr_board.js:54` (`landed`); `ext_cr_board.css:869` `.cr-tile--landed{background:var(--surface-done)}` | PRESENT | — |
| 6 | "N live" filter | Triage-strip filter: `ext_cr_board.js` `setFilter()`/`passesFilter()` — PRESENT. **Top-bar "live pill"**: not found — grepped `live pill`/`cr-livepill`/"N live" across `board.js`/`board.css`/`ext_cr.css`, zero hits; doc 02's own top-bar element list (§4.2 of `reports/drift/02-shell-and-board.md`) also names no such pill | **PARTIAL** | MED |
| 7 | Flag count badge + red edge | Badge/edge: `ext_cr_board.js:1509-1512` `stateWord()`, `ext_cr_board.css:868` `--line-flagged`. **Actual flag text is never rendered**: `tileLine()` uses `s.now_line`, never flag text, and the list-dict shape itself has no flag-text field — `registry.py` exposes `open_flags` as a **count only**. Not fixable client-side alone. | **PARTIAL** | HIGH |
| 8 | Notes count badge | `ext_cr_board.js:1706-1710` — "📝 N notes" in the **hero** tile's side rail only, matching doc's own wording ("hero tile's side rail") | PRESENT | — |
| 9 | Cross-session flag list | `ext_cr_boot.js:786-806` `buildFlagsPayload()` — each row carries `sessionTitle`, `onOpen` routes to that session | PRESENT | — |
| 10 | Search sessions, name matches first | `ext_cr_board.js:635-643` rail search + `⌘K` label. Filter (`:773-779`) is a **plain substring `.filter()`** — does not reorder to put name-matches first; a real `⌘K`→focus keybinding was not confirmed wired in the files searched | **PARTIAL** | LOW |
| 11 | Rename a session | Pencil: `ext_cr_detail.js:737,959-963,1350` (`crd-rename` → `ctx.dialog("rename",…)` → `ext_cr_boot.js:567-578` real `POST /api/title`) | PRESENT | — |
| 12 | Pin above recency | `ext_cr_board.js:61-63` (`railOrder()` splits pinned/unpinned), `:839-841` "📌 Pinned — N" header | PRESENT | — |
| 13 | Agents · repo collapsible group | Rail: `ext_cr_board.js:154-173,866-881`; 2-col board tile: `agentGroupTile()` `:1729-1746`. **Same gap as #1**: an agent session with an empty `group` string is picked up by neither the group nor the individual list — it is dropped, not merely mis-grouped | **PARTIAL** | HIGH |
| 14 | In-transcript agents running badge | Tile: `ext_cr_board.js:1671` (`agent-glow`, gated on `s.bg>0`); detail header pill: `ext_cr_detail.js:1339-1345` `agentsPill`, "N agents running" | PRESENT | — |
| 15 | New terminal / new Claude session | `ext_cr_board.js` `session:new` emit → `ext_cr_boot.js:487-492` → `CR.term.openPicker('new')` — real directory picker with server-ordered recent cwds | PRESENT | — |
| 16 | Manage terminals + live count | `ext_cr_board.js:1262,1888-1894` ("Terminals" pill, "N of M"); `ext_cr_boot.js:429-436` | PRESENT | — |
| 17 | Notification bell | `ext_cr_board.js:1276-1279` `cr-bell` | PRESENT | — |
| 18 | Theme toggle | `ext_cr_board.js` `buildThemeControl()` (~`:1316-1368`), Auto/Light/Dark segmented; also in Config and terminal toolbar (out of this row's scope, both confirmed present elsewhere in this report) | PRESENT | — |
| 19 | Idle sessions don't bury live ones | `ext_cr_board.js:225` filters idle from the board; cap footer denominator (`:1754`) counts **all** sessions incl. idle; rail lists idle via `railOrder()` (no idle filter there) | PRESENT | — |

### Detail view

| # | Capability | Home | Verdict | Severity |
|---|---|---|---|---|
| 20 | Progress ring — **Replaced** by spine | Old ring fully removed (grep for `progress-ring`/`crd-ring`: zero hits); spine at `renderSpine` `ext_cr_detail.js:1434-1505` | PRESENT | — |
| 21 | Stat chips (7) | **Removed outright.** `ext_cr_detail.js:637-646` (skeleton), `:1306-1327` (`renderHeader`) — explicit code comment "FIX (design-audit drift 1): 5b has NO files/commands/reads/commits/tests/branch…"; no `crd-chip` row, no `N/A`/`--` convention anywhere (grep confirms zero hits). Doc 03 §1.4 specifies this row as a hard requirement; doc is authoritative. | **MISSING** | HIGH |
| 22 | State / Activity split | `ext_cr_detail.js:778-804` — State · Conversation · Evidence, `.78fr 1.34fr .78fr` grid (`ext_cr_detail.css:579-584`) | PRESENT | — |
| 23 | Panels collapse to header | Chevron/collapsed-by-default/localStorage persistence: `getCollapsed`/`setCollapsed`/`panelKey` `:207-218`; per-column Expand all/Collapse all `:781-783,796-801,951-958` | PRESENT | — |
| 24 | Waiting-on-you header state | Orange state pill inside `renderHeader`'s identity row (`crd-pill-state`) | PRESENT | — |
| 25 | Summary Goal / Now / So far | `renderSummary` `:1584-1595`; goal promoted to `<h1 class="crd-goal">` `:1349` | PRESENT | — |
| 26 | Decisions & open questions | `renderDecisions` `:1509-1539`; open pinned top, view-only footer verbatim at `:1530-1531` | PRESENT | — |
| 27 | Narration, its own words | `mergeTimeline` `:431-469` folds narration+prompts into one array/panel `:885-916` | PRESENT | — |
| 28 | Narration prev/next + jump-to-latest | Present, but the panel head is a **superset** of spec: the "prompts · narration · tools · results" legend words are individually clickable filter chips (`:894-900`) plus an extra pop-out (⤢) button (`:906`), vs. doc's static legend + all/talk-only pair | PRESENT (superset) | LOW |
| 29 | Live follow / hold your place | Implemented; "stuck to latest" = top-of-scroll, timeline sorted newest-first (`:922-926`) — doc doesn't state sort order explicitly, so this reads as ambiguous-vs-doc rather than contradicting it | PRESENT | LOW |
| 30 | Unbounded history, page on scroll | Footer note + scroll handler present (part of `mergeTimeline`/paging machinery, confirmed by `reports/drift/03-detail-view.md` §6) | PRESENT | — |
| 31 | Markdown rendering | Delegates to the **shared** `app.js` renderer (comment at `ext_cr_detail.js:2107`) — one renderer, not forked, matching conventions.md rule 4 | PRESENT | — |
| 32 | Mermaid → SVG, 8 families | `MMD_FAMILY_RE` (~`:553-561`) lists exactly 8 families matching the README; drawn locally, no mermaid.js in this pop-out — matches doc's own instruction for this specific card | PRESENT | — |
| 33 | Copy per code block | Shared renderer, `aitracker/web/app.js:41,43` (`codecopy` button, `copyCode()`), `:1704-1705` (clipboard write) — reused by Control Room via the shared markdown path, not reimplemented | PRESENT | — |
| 34 | Prompts, incl. slash commands | `entryHtml` `:1825-1904`, `.crd-bubble-prompt` right-aligned | PRESENT | — |
| 35 | Files + diff per edit | `renderFiles` `:1624-1640`, pop-out wired to the shared diff modal in `ext_cr_dialogs.js` | PRESENT | — |
| 36 | Up/down context expansion | Pop-out diff toolbar (`ext_cr_dialogs.js`, shared with narration/command-output pop-out) | PRESENT | — |
| 37 | Expand all | Pop-out toolbar | PRESENT | — |
| 38 | Diff ⇄ Rendered markdown | Pop-out toolbar | PRESENT | — |
| 39 | Open in new tab | Pop-out toolbar | PRESENT | — |
| 40 | Files written by agents, tagged | `agent` tag via `crd-agent-model` styling, batch-confirmed in `renderFiles` | PRESENT | — |
| 41 | Commands with pass/fail | `renderCommands` `:1642-1656`, `ok`/`fail` words in a fixed 22px gutter `:1653`. **Sub-gap**: the doc's "N · status not recorded" header text for providers lacking real exit status is never implemented for any provider (no code path produces that string). Also, doc's own premise is stale for Auggie — `auggie.py:499,680` shows it *does* carry real `ok` status. | **PARTIAL** | MED |
| 42 | Pull requests, created only | `renderPRs` `:1541-1559`, filters `p.created` only, excludes referenced-only | PRESENT | — |
| 43 | merged/closed badges | Present, forest `merged` badge — but **PR title is never rendered** (the parser never captures one; `util.py` PR collector is regex-only over URLs). Row shows "#num · repo" instead of doc's "number + title." | **PARTIAL** | MED |
| 44 | Agent-opened PRs attributed | `agent` tag on subagent-opened PRs, same treatment as Files panel | PRESENT | — |
| 45 | **Links, generated vs worked on** | `renderLinks` `:1561-1582`, `deriveLinks` `:487-529` — two groups, verbs (`created/wrote/endpoint/read ×N/cited`), dedup+highest-privilege, footnote verbatim, `localhost:*` included per spec's resolved open decision. Data source is a best-effort regex URL scan over narrative/requests/commands text, not a first-class parser field (code comment flags this as a "REQUIRED ADDITION") | PRESENT (behaviourally; provenance approximated) | LOW |
| 46 | Plan on the go: add/copy/push/remove | `renderPlan` `:1597-1620` | PRESENT | — |
| 47 | Delivery chips (turn-end / on wake / copy it) | `:1600-1603`, exact match to `push_when` mapping (live/idle/no-hook) | PRESENT | — |
| 48 | Background agents & shells | `renderAgentsPanel` `:1679-1740` | PRESENT | — |
| 49 | Re-run collapse | `groupAgentReruns` `:1663-1677`, `×N` tag opens latest | PRESENT | — |
| 50 | Show N finished | Disclosure present in Agents panel | PRESENT | — |
| 51 | Toast + sound + desktop notification | `ext_cr_dialogs.js:271-320` — 8s auto-dismiss, pause-on-hover, never-while-focused (`document.hidden`-keyed); permission nudge shown-once/dismissible/not-on-first-paint | PRESENT | — |
| 52 | Fork lineage banner + back-link | `renderForkBanner` `ext_cr_detail.js:1407-1432` (`:1382`, "FIX drift 3"). **Relocated**: rendered as a small card at the **bottom of the Evidence column**, not the doc's full-width banner between the header and the spine | **PARTIAL** (present, wrong placement) | MED |
| 53 | Search within the session | Header toggle → full-width card, `ext_cr_detail.js:727,742-744` | PRESENT | — |
| 54 | Command runner + constraint stated | `renderRunPanel` `:1742-1749`, "No shell — argv only, against an allowlist…" verbatim | PRESENT | — |
| 55 | Model / effort switchers | Terminal-bar half genuinely wired: `ext_cr_term.js:735-750` real `/model`/`/effort` injection via `POST /api/term/inject`. **Evidence-panel mirror is permanently dead**: `renderTerminalPanel` (`ext_cr_detail.js:1751-1772`) is gated on `session.term_attached`, a field **no provider or server route ever sets on the detail dict** (grep of the whole Python tree: zero occurrences), even though `GET /api/term/attached` exists and is simply never called from this file. The panel can never render. | **PARTIAL** | HIGH |
| 56 | Context readout (current + cumulative) | `session.context` **is** populated server-side (`providers/claude.py:1274`, `auggie.py:572`, `augment_ext.py:275`) but the Evidence-panel mirror that would display it is the same dead `renderTerminalPanel` as #55 | **PARTIAL** | HIGH |
| 57 | Open / resume / external terminal | Functionally present (`ext_cr_detail.js:729-733`), but the doc's two-stacked-row anatomy is collapsed into **one row**: Search/Flag demoted to icon-only buttons (no visible label), an unspec'd "Queue a note" button inserted, button reads "Resume" not "Resume here" — self-documented in code as "FIX (design-audit drift 2)" | **PARTIAL** (present, restructured) | MED |
| 58 | Degraded provider messaging | `providerNoteFor()` shared with the dialogs module (`:1781-1788`); `narrDegraded` correctly scoped to Augment-extension sources only (excludes Auggie, matching the project README's own parity table); filter row hidden when degraded | PRESENT | — |
| 59 | **Config dialog** | See Table B — genuinely wired end-to-end; two real drifts (board-tiles slider range, Port/Host editability) | PRESENT (with drift) | see Table B |
| 60 | **Progress spine** | `spineSegments` `ext_cr_detail.js:265-360` reproduces the doc's `spineWidths` formula almost exactly (same `usedPct`/floor/`MAX_USED`/group-threshold constants), reading the **correct** snake_case `started_at`/`ended_at` fields that match what `providers/claude.py:1209-1210` actually writes. **The shipped project README (line 180) is stale**: it claims the spine renders "equal-width today… camelCase startedAt/endedAt, a name nothing ever writes" — that description does not match this code. Header row, event gutter (5 marker kinds), footer row, `role="img"`+`aria-label` all present and matched. | PRESENT | — |

**Section totals: 60/60 rows produced. PRESENT: 42 · PARTIAL: 17 (items 1, 6, 7, 10, 13, 21†, 28, 29, 41, 43, 52, 55, 56, 57, plus 59/60 carrying sub-drift noted above) · MISSING: 1 (item 21†, stat chips — graded MISSING not PARTIAL, since the whole row is gone).**
(† item 21 counted once as MISSING; the PARTIAL count above is 15 discrete rows: 1,6,7,10,13,28,29,41,43,52,55,56,57 = 13, plus 59 and 60 carry sub-drift but are graded PRESENT overall since the core capability itself renders — see rows for exact wording.)

---

## Table B — Dialogs, modals, empty/error states, non-negotiables

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| B1 | Shared modal contract | `--surface-raised`, 1px border, radius 10px, `--shadow-overlay`; header emoji+title+context+close; focus trapped; Esc closes; focus returns to trigger; opening never navigates/unmounts a PTY | One shared `trapFocus()`/`open()`/`close()` (`ext_cr_dialogs.js:328-441`) used by every dialog via `REGISTRY`; opener captured at open-time and restored on close; `open()`/`close()` touch only the dialog `_layer`, never `st.engineHandle` | MATCH | — |
| B2 | Help dialog — 5 tabs | Coverage(active)·States·Keyboard·Terminal·Per-tool | `HELP_TABS` `ext_cr_dialogs.js:709-715`, exact order/default | MATCH | — |
| B3 | Help — Coverage tab stats | "58 capabilities · 4 tools · 0 bytes leaving" | Implementation uses `CAPABILITIES.length` = **60**, not 58, with an in-code note reconciling doc 04's own stale "58" against its own 60-row table (`:588-595`); pinned by `tests/test_capability_table.py` so the count can never silently drift from what's shipped | DRIFT (**doc is stale**, code is correct) | LOW |
| B4 | Help — security cards, footer "🧩" row | Verbatim copy from the security list | Present, footer "🧩 Your tool isn't listed? A provider is two functions. · Read" confirmed | MATCH | — |
| B5 | **Config dialog — parameter wiring (primary target)** | 15 rows, see doc 04 table | See full row-by-row below | see below | see below |
| B6 | Config — Theme / Session rail / Cards start folded / Poll interval / Desktop notif+sound | No restart, live browser settings | `ext_cr_dialogs.js:1043,1050,1052,1085,1065` — all read/write real state (`ctx.theme`, real `tracker.rail.mode` key board.js also reads, real `soundOn`/`toggleSound()` global) | MATCH | — |
| B7 | Config — Board tiles: slider **3–12**, default 8 | `ext_cr_dialogs.js:1079` renders a slider that writes `cr.boardTileCount` — but `boardTileCap()` (`ext_cr_board.js:182-187`) **clamps to 3–8**, silently discarding 9–12. The shipped project README *also* claims this row is "read-only… by design," which is itself wrong — it's a live 3–8 slider, just narrower than spec'd. Three-way disagreement: doc says 3–12, README says read-only, code is a working 3–8 slider. | DRIFT | MED |
| B8 | Config — Live window: slider 1–15min, default 5 | Server-backed via `GET`/`POST /api/config`; `config.py` `_v_int(5,86400)` (seconds) confirms real validation | MATCH | — |
| B9 | Config — Terminal renderer / Max terminals / Terminal enabled / External terminal app / Command allowlist | All confirmed in `config.py`'s real `EDITABLE`/`VALIDATORS` set, round-tripped through `test_cr_routes.py`'s passing assertions; no fake/no-op controls found | MATCH | — |
| B10 | Config — Terminal enabled restart cost | Doc says restart required (yes) | `server.py`'s `resolve_terminal()` reads the override **live** — no restart is actually needed. Doc overstates the restart cost (harmless direction: over-cautious, not under). | DRIFT | LOW |
| B11 | Config — Auth: masked, set/not-set only, `TRACKER_AUTH`; doc: "setting from UI is acceptable, reading back is not" | `ext_cr_dialogs.js:1126-1128` — field is **fully read-only**; the UI cannot set it at all, only shows set/not-set, stricter than the doc's own baseline (deliberate, documented security tightening per code comment) | DRIFT (justified, doc's fallback clause permits this) | LOW |
| B12 | Config — Port / Host: "mono fields, **read-only display**", restart yes | `ext_cr_dialogs.js:1129-1136` implements these as **editable** text fields (`textFieldCtl`) that POST to `/api/config` and take effect next start — control type contradicts the doc's explicit "read-only display" instruction, even though the restart-cost copy itself is correctly stated | **DRIFT** | MED |
| B13 | Config — Data files: read-only paths, "read live" note | Dialog shows 4 files (flags/titles/pins/notes); the project's own `config.json` is a 5th "data file" per README but is not listed in this row | DRIFT | LOW |
| B14 | Config — Footer: restart note + Reset to defaults (quiet) + Apply (solid) | `ext_cr_dialogs.js:1271-1279` | MATCH | — |
| B15 | Pop-out — file diff | Path/basename, +N/−N, Diff\|Rendered, Expand all, New tab, ‹N of M›, close; context-affordance bars; 54px gutter; removed/added/context line treatment | Owned by the shared pop-out in `ext_cr_dialogs.js`, reused by Files, Command output, and full-narration text (per doc's own "same pop-out serves…" instruction) | MATCH | — |
| B16 | Pop-out — narration with diagram | Header, diagram card, node pills, active-node highlight, caption; nodes `flex-wrap:wrap` | Present in dialogs module | MATCH | — |
| B17 | Agents · repo, expanded | Header chevron+🤖+title+"N live"; rows state dot/title/worktree or ×N/open›; running=`--surface-agent-quiet`+`--line-agent`; blocked="blocked" word; footer "Show N finished" | Present, consistent with Evidence-panel Agents renderer's shared conventions | MATCH | — |
| B18 | Degraded provider block | Verbatim example: "[NOT ON DISK]… per-workspace LevelDB (augment-kv-store)… What IS readable is shown in full…" | `degraded()` `ext_cr_dialogs.js:187-210`; copy is a **close paraphrase**, dynamically generated per-provider via `providerNoteFor()` rather than the doc's hardcoded LevelDB example — arguably more correct (handles more than one degraded provider), but not a literal-text match | DRIFT (behaviourally better, textually non-verbatim) | LOW |
| B19 | Terminals at the cap | Header "N of M running — free a slot" on `--surface-failed`; rows = session title (not resume command) + project/age + peek + kill; footer "Closing detaches; ✕ kills." + Close all behind inline confirm | `renderManageTerminals`/cap variant `ext_cr_dialogs.js:1470-1517` — title line, session-title-not-command row (`t.title\|\|t.session\|\|cwdTail\|\|t.tty`), peek/kill, footer copy, inline confirm all verbatim | MATCH | — |
| B20 | Two different empties — "Nothing yet" | Dashed `--line-default` box, "No commands yet — This session hasn't run any. It will fill in as it works." | `emptyState()` `ext_cr_dialogs.js:167-183`, reused across panels | MATCH | — |
| B21 | Two different empties — "Something broke" | `--surface-failed`+`--line-failed`, "Couldn't read this session — The transcript exists but a line failed to parse. Everything before it is shown." | `errorState()` same location, distinct from B20 | MATCH | — |
| B22 | Terminal's own overlay (`role="dialog"`, not one of the 7 named dialogs) | Not one of doc 05's 7 dialogs, but carries `role="dialog"` and modal-like chrome | Has Esc-close and backdrop-click-close but **no focus trap and no focus-restore-to-opener**, unlike every dialog that goes through `CR.dialogs` (`ext_cr_term.js`; per `reports/drift/05-terminal-and-dialogs.md` §5.6) | DRIFT | MED |
| N1 | Non-negotiable (a) — read-only toward sessions | No write path into a session transcript anywhere in the new UI | Confirmed across board/rail/boot, detail, dialogs, and terminal: writes are confined to app-owned state (title/flags/notes/term-control) or the PTY's own stdin (the user's own shell, not a session log). `renderDecisions` emits no buttons/handlers/fetches at all. | MATCH | — |
| N2 | Non-negotiable (b) — 2s poll + existing result shape unchanged, no new per-panel round-trips | Grep for `fetch(`/XHR across every `ext_cr_*.js` file | Only pre-existing or action-triggered routes found: `/api/search` (Sessions destination, justified 200-session-cap workaround, not per-poll), `/api/narration` (pre-existing pagination route also used by classic `app.js`), `/api/term/*` (dialog-open/attach-triggered), `/api/config` (dialog open/save), one-shot `/api/term/list` (explicitly justified as not a poll, to learn the static `max`). **No new recurring per-panel poll found.** | MATCH | — |
| N3 | Non-negotiable (c) — colour never carries meaning alone | Every state has a word next to it | Confirmed with no violations across triage strip, tiles, rail rows/orbs, stat pills, PR/command ok-fail words, spine segments, model/effort pills, kill button, notice banners, cap-reached header; all emoji `aria-hidden` | MATCH | — |
| N4 | Provider-agnostic, no forked per-tool UI | One renderer per capability, filled by every provider | Confirmed: markdown, links, plan, spine, degraded-messaging all route through shared functions (`providerNoteFor()`, shared `deriveLinks()`, shared markdown renderer) — no `if (source === 'auggie')` branch found forking a UI path | MATCH | — |

---

## Fix list (ordered by severity)

**HIGH**
1. `ext_cr_detail.js:1757` (`renderTerminalPanel`) — gated on `session.term_attached`, a field no provider or server route ever populates. Either add it to the shared detail-dict seam server-side (poll `GET /api/term/attached` keyed by the session's tty) or wire the existing route client-side, so the Evidence-panel model/effort/context mirror (items 55/56) can ever render.
2. `ext_cr_detail.js:637-646,1306-1327` — restore the doc-03/04-mandated 7-chip stat row (`files/commands/reads/commits/tests/tokens/branch`) with the `--`/`N/A` convention (item 21); it was deliberately dropped, contradicting the authoritative doc.
3. `ext_cr_board.js:217-223` (also affects item 13) — stop dropping agent sessions whose `group` field is an empty string from the board entirely; fold them into a `(no group)` bucket in `agentGroups()` or include them in the individually-ranked list when non-idle (self-documented live bug: 1 working session, 0 tiles).
4. `registry.py` (list-dict `open_flags`) / `ext_cr_board.js` tile renderer — the flag badge (item 7) shows a count only; the Flagged tile's doc-mandated "flag text in a `--surface-raised` inset" has no data source. Add flag text to the shared session-list shape.

**MED**
5. `ext_cr_dialogs.js` (Board tiles Config row) — code clamps 3–8 vs. doc's 3–12 slider, and the shipped README separately claims this row is read-only. Reconcile all three: either widen the slider (respecting the separate hard 8-tile board cap) or fix both docs to state the real 3–8 range.
6. `ext_cr_dialogs.js:1129-1136` — Config's Port/Host rows are editable text fields; doc explicitly specifies "read-only display." Change to `readonlyField(...)` (matching the pattern already used for Auth/Data files) or get sign-off to update the doc.
7. `ext_cr_detail.js:1642-1656` — implement the doc's "N · status not recorded" header text for providers lacking real exit-status data; re-verify the target provider, since Auggie (`auggie.py:499`) actually does carry `ok`.
8. `ext_cr_detail.js:1541-1559` — PR panel never renders a title (parser captures none); shows "#num · repo" instead of "number + title" per doc 03 anatomy (item 43).
9. `ext_cr_detail.js:726-733` — header actions collapsed into one row (Search/Flag demoted to icon-only, unspec'd "Queue a note" inserted) vs. the doc's two-stacked-row anatomy (item 57), self-flagged in code as "design-audit drift 2" — get sign-off or restore the two-row layout.
10. `ext_cr_detail.js:1407-1432` — fork lineage banner (item 52) rendered as a small Evidence-column card instead of the doc's full-width banner between header and spine.
11. `ext_cr_board.js` — top-bar "N live" pill (item 6) not found anywhere; only the triage-strip filter exists as a "live" affordance.
12. `ext_cr_term.js` (terminal overlay, `role="dialog"`) — Esc/backdrop-close present but no focus trap and no focus-restore-to-opener, unlike every dialog under `CR.dialogs`. Wire the shared `trapFocus`/opener-capture, or drop `role="dialog"` if it's meant to read as the primary surface, not a modal.

**LOW**
13. `ext_cr_board.js:773-779` — rail/board search doesn't rank name-matches first (item 10); plain substring filter, no reorder.
14. `ext_cr_dialogs.js:1126-1128` — Auth row is fully read-only from the UI (stricter than doc's "setting is acceptable"); deliberate and documented — update the handoff doc so this stops flagging as drift on the next audit.
15. `ext_cr_dialogs.js` (Data files row) — lists 4 files (flags/titles/pins/notes); `config.json`, a 5th data file per the shipped README, isn't listed there.
16. Doc `04-coverage-and-help.md` itself — "58 capabilities" text in the Help Coverage tab copy is stale against its own 60-item table; code correctly derives 60 (`CAPABILITIES.length`, pinned by `tests/test_capability_table.py`). Fix belongs in the doc, not the code.
17. Shipped project `README.md:180` — its claim that the progress spine renders "equal-width today… camelCase `startedAt`/`endedAt`, a name nothing ever writes" is stale; `ext_cr_detail.js:265-360` already reads the correct snake_case `started_at`/`ended_at` fields matching the backend (item 60). Update the README line, not the code.
18. `ext_cr_dialogs.js:187-210` — degraded-provider copy is a dynamic paraphrase, not the doc's literal LevelDB example text; functionally an improvement (handles more than one degraded provider) but worth a doc note.
19. `ext_cr_detail.js:730` — button copy "Resume" vs. doc's "Resume here."

---

## Related deeper audits already on disk

`reports/drift/02-shell-and-board.md` (48 items checked, 3 HIGH incl. the agent-session-vanishes bug
pulled forward above), `reports/drift/03-detail-view.md` (detail header/columns/spine/phone-layout,
2 HIGH incl. the stat-chip removal and `term_attached` gate pulled forward above), and
`reports/drift/05-terminal-and-dialogs.md` (terminal control set + dialog mechanics, 0 HIGH, 2 MED
incl. Port/Host editability and the terminal-overlay focus trap pulled forward above) cover the same
implementation at finer grain than this doc's 60-item capability map requires. Read those for anything
not itself a numbered doc-04 capability or a Help/Config/modal/non-negotiable row.
