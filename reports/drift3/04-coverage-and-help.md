# Drift round 3 - doc 04 (coverage, modals, Help, Config)

Doc: `design_handoff_control_room/04-coverage-and-help.md`. Precedence applied: **docs win** (commit `7b87cce`, 2026-09-05, "the docs win ... prototype-wins ruling reversed, emoji excepted"; read via `git show --stat`), with later owner rulings in the README and `reports/control-room-refinements.md` winning where they explicitly override (board tiles 3-12, heartbeat panel, gateway/tunnel config). Code SHA: `76bd154`. Paths are under `aitracker/web/` unless noted.

## 1. Prior-finding status (round 1 `reports/drift/04`, round 2 `reports/drift2/04`)

| id | finding (short) | status now | evidence |
|---|---|---|---|
| R1-#1/#13 | agent:true + empty group dropped from board | CLOSED | `ext_cr_board.js:199` `isGroupedAgent = agent && group`; ungrouped agents stay in `individual` (`:396-407`) |
| R1-#6 | no top-bar "N live" pill | STILL OPEN | live filter exists in triage strip + rail pill (`ext_cr_board.js:1474-1487`); top bar (`:2296-2408`: Sessions, Classic, Flags, Alerts, Config, Help) has no live pill |
| R1-#7 / R2-#7 | flag text tooltip-only on tile | STILL OPEN (LOW) | `ext_cr_board.js:2772-2778` `title` only; text IS visible on the detail flag card (`ext_cr_detail.js:2537-2541`) and the flag list (`ext_cr_dialogs.js:1933`) |
| R1-#10 | search does not rank name matches first | STILL OPEN (LOW) | `ext_cr_board.js:1208-1210` plain `indexOf` filter |
| R1-#21 | stat chips removed | CLOSED | `ext_cr_detail.js:1019` `STAT_CHIP_MISSING = "--"`, row rendered |
| R1-#41 | "status not recorded" missing | CLOSED | `ext_cr_detail.js:2923-2935` |
| R1-#43 | PR title never rendered | STILL OPEN (LOW, parser limit) | `ext_cr_detail.js:2810-2818` renders `p.title` or "-"; `util.py` collector captures no title |
| R1-#52 | fork banner is a small bottom card | STILL OPEN (LOW) | `ext_cr_detail.js:1626-1630` `.crd-forkcard`, `renderForkBanner :2572` |
| R1-#55/#56, R2-B1 | model/effort/context mirror dead, then lying | CLOSED | `ext_cr_detail.js:3142-3170` buttons disabled unless real `term_tty`; handler `:2066-2084` drives the real tty; `registry.py:238-250` populates `term_attached`/`term_tty` |
| R1-#57 | header actions one row; "Resume" vs "Resume here" | STILL OPEN (LOW) | `ext_cr_detail.js:1380-1383` |
| R1-B7 | Board tiles slider 3-12 vs clamp 3-8 | CLOSED | slider `ext_cr_dialogs.js:1320` (3-12); clamp `ext_cr_board.js:269-274` (3-12) |
| R1-B10 | Terminal-enabled restart cost overstated | SUPERSEDED-BY-RULING | `config.py:208-219` keeps `TERMINAL` in `RESTART_REQUIRED` per the doc |
| R1-B11 | Auth read-only from UI | SUPERSEDED-BY-RULING (doc fallback allows) | `ext_cr_dialogs.js:1394-1396`, `config.py:108-113` |
| R1-B12 / A6 | Port/Host editable fields | CLOSED | `ext_cr_dialogs.js:1397-1405` `readonlyField` |
| R1-B13 | Data files lists 4 not config.json | STILL OPEN (worse, see N6) | `ext_cr_dialogs.js:1570-1575` |
| R1-B18 | degraded copy paraphrased | SUPERSEDED-BY-RULING (dynamic per provider) | `ext_cr_dialogs.js:189-200`, `PROVIDER_NOTES :617-622` |
| R1-B22 | terminal overlay had no focus trap | CLOSED | `ext_cr_term.js:69-72,377-378` reuses `trapFocus` + opener restore |
| R1-B3 | Help says 58 (doc stale) | SUPERSEDED-BY-RULING | derived from `CAPABILITIES.length` (`ext_cr_dialogs.js:663`), now 61; `tests/test_capability_table.py:248` pins 61 |
| R1-#32/#33 | mermaid and per-fence copy deferred | CLOSED | copy `ext_cr_detail.js:198-210`; mermaid `:206-217,819-824` |
| R2-B2 | Live window slider not 1-15 min | **STILL OPEN** | `ext_cr_dialogs.js:1330` `sliderCtlCommit(30, 1800, ..., 's')`: 30-1800 seconds; server accepts 5s-24h (`config.py:252`) |
| R2-B3 / R1-B21 | "something broke" empty had no signal | CLOSED | `providers/claude.py:1810-1823,2168` `parse_error`; `ext_cr_detail.js:3197-3217` `errorHtml("Couldn't read this session")`; `tests/test_cr_parse_error.py` |
| R2-B12 | flag card stale "not yet on /api/session" | CLOSED | `ext_cr_detail.js:2514-2541` |
| R2-#60 | spine camel/snake bug | CLOSED | `ext_cr_detail.js:552` `spineSegments` (README `:180` line is doc-stale) |
| R2-B4..B11 | Help tabs, cap dialog, theme, reduced motion, non-negotiables | CLOSED (re-sampled) | `ext_cr_dialogs.js:709-715,2009` |

Totals: CLOSED 14, STILL OPEN 7 (all LOW; #6 and Data files at LOW-MED), REGRESSED 0, SUPERSEDED 4.

## 2. Capability map, all 61 items (every one has a reachable home)

P = present. Items 1-19 board, 20-60 detail, 61 added since the doc.

| # | Capability | Home (file:line) | V |
|---|---|---|---|
| 1 | Every session newest first | `ext_cr_board.js` boardTiles/`agentGroups :210`, rail `railOrder` | P |
| 2 | Source badge | `toolLabel()` in tile head | P |
| 3 | Live dot / window | `sessionState`, `LIVE_WINDOW` from page.py | P |
| 4 | Waiting hero | `ext_cr_board.js:2884-2937` (+resume) | P |
| 5 | Landed | `landed` state | P |
| 6 | "N live" filter + top-bar pill | triage + rail `:1474-1487`; no top-bar pill | PARTIAL |
| 7 | Flag badge, red edge, text | badge `stateWord`; text tooltip `:2772` | PARTIAL |
| 8 | Notes badge | `s.note_count` | P |
| 9 | Cross-session flag list | `ext_cr_dialogs.js:1933` | P |
| 10 | Search, name first | `ext_cr_board.js:1208`; no name-first rank | PARTIAL |
| 11 | Rename | `ext_cr_detail.js:1388` | P |
| 12 | Pin | rail group, `s.pinned` glyph `ext_cr_board.js:2791` | P |
| 13 | Agents group | `agentGroups :210`, rail expand | P |
| 14 | Agents running badge | tile now-line + header pill | P |
| 15 | New terminal / session picker | `ext_cr_dialogs.js:2166-2187` (`/api/term/cwds`) | P |
| 16 | Manage terminals | `ext_cr_dialogs.js:2009` | P |
| 17 | Bell | `bellGlyph` `ext_cr_board.js:2393` | P |
| 18 | Theme | Config `ext_cr_dialogs.js:1237-1241`, boot `tracker.theme` | P |
| 19 | Idle never buried | idle excluded from tiles, kept in rail | P |
| 20, 60 | Spine | `ext_cr_detail.js:552` | P |
| 21 | 7 stat chips | `:1019` | P |
| 22 | 3 columns | panel groups | P |
| 23 | Collapse/persist/expand all | `:287` `panelKey`; Config cardsFolded `ext_cr_dialogs.js:1290` | P |
| 24 | Waiting header pill | `stateOf` | P |
| 25 | Goal/Now/So far | `renderSummary :2852` | P |
| 26 | Decisions | `renderDecisions :2768` | P |
| 27-30 | Narration timeline, nav, follow, paging | `crd-timeline :1655+`, foot `:1670`, `/api/narration` | P |
| 31 | Markdown | shared `md()` | P |
| 32 | Mermaid | `ext_cr_detail.js:819` | P |
| 33 | Copy per fence | `:198-210` | P |
| 34 | Prompts/slash | timeline prompt entries | P |
| 35-39 | Files, diff, context expand, Expand all, Diff/Rendered, New tab | `renderFiles :2896` + diff pop-out (`ext_cr_dialogs.js`) | P |
| 40 | Agent-written files tagged | `renderFiles` | P |
| 41 | Commands pass/fail | `renderCommands :2919` | P |
| 42-44 | PRs created, merged/closed, agent tag | `renderPRs :2800-2818` | P (no title) |
| 45 | Links | `renderLinks :2829` | P |
| 46-47 | Plan, delivery chips | `renderPlan :2869` (`push_when`) | P |
| 48-50 | bg agents/shells, xN, show N finished | `renderAgentsPanel :2982`, `:3031` | P |
| 51 | Toast/sound/desktop | `toast ext_cr_dialogs.js:273`, nudge `:220-230`, Config `:1306` | P |
| 52 | Fork lineage | `renderForkBanner :2572` (card) | PARTIAL |
| 53 | Search in session | `:1378` | P |
| 54 | Command runner | `ext_cr_detail.js:2063`, `ext_cr_boot.js:724` | P |
| 55-56 | Model/effort + context | `ext_cr_detail.js:3142-3170`, terminal bar | P |
| 57 | Open/resume/external | `:1380-1383`; external hidden off localhost `:2544` | P |
| 58 | Degraded messaging | `degraded() ext_cr_dialogs.js:189` | P |
| 59 | Config dialog | `ext_cr_dialogs.js:1143-1640` | P |
| 61 | Heartbeat panel | `renderHeartbeat :2335`, Config `:1292` | P |

## 3. New drift

| # | doc section + line | doc says | code does | verdict | sev |
|---|---|---|---|---|---|
| N1 | Config table "Live window" | slider 1-15 min, default 5 | `ext_cr_dialogs.js:1330` 30-1800 s raw-second label (carry-over R2-B2); min 30 hides the 5-29 s the server allows | DRIFT | LOW |
| N2 | Config sections | Interface/Board/Terminal/Notifications/Server/Data files | `:1143` adds Tunnel (ruled, README `:174`); Notifications is a pointer note only `:1303-1307` | EXTRA | LOW |
| N3 | Poll interval | 1s/2s/5s | `:1322-1325` | MATCH | - |
| N4 | Config footer | Reset (quiet) + Apply (solid) | `:1624,1629`; Apply closes (rows live-save, copy explains) | MATCH | - |
| N5 | Command allowlist | textarea | `:1380-1383` | MATCH | - |
| N6 | Data files row | read-only paths for flags/titles/pins/notes + "read live" | `:1571-1575` reads `srv.dataFiles`, which **nothing populates** (`:1593` sets only `authSet`; `server.py:423-427` returns `AUTH_SET`, no data-file paths), so it shows bare `flags.json`. Lists 4 of the 7 files README `:214` names (`model_keep.json`, `title_sync.json`, `forks.json`, `config.json` missing) | DRIFT | LOW-MED |
| N7 | Auth | set/not set + security note | `:1394-1396` | MATCH | - |
| N8 | Config params vs `config.EDITABLE` (16 keys) | each editable | all 16 have a row: ICON_STYLE/SCALE `:1250-1280`, LIVE_WINDOW `:1328`, HEADER_LINE `:1334`, SNAPSHOT_TTL `:1339`, TERM_RENDERER/MAX_TERMS/IDLE_TTL/TERMINAL/TERM_APP/GATEWAY/OPENROUTER_*/TERM_ALLOW `:1344-1383`, PORT/HOST read-only `:1397-1405`. Tunnel keys (`TUNNEL_EDITABLE`) have the Tunnel tab. No key is UI-orphaned | MATCH | - |
| N9 | Slider ranges vs validators | consistent | Snapshot/Idle TTL sliders 5-240, server 1-1440; disclosed in row copy `:1339,1351` | MATCH (disclosed) | LOW |
| N10 | Help Coverage: generate table from the data the tests assert | derived | `CAPABILITIES` derived and pinned (61) but lists only doc 04's 60 rows + heartbeat. Absent: model gateway/OpenRouter, tunnel + read-only remote, idle/snapshot TTL, header line, icon style, agent map, model marker chip, cost chip, model-update nudge, folder terminals. Help under-reports what shipped | DRIFT | MED |
| N11 | Help "4 tools" | 4 | `PROVIDER_NOTES.length` = 4 (`:617-622`) | MATCH | - |
| N12 | Top bar live pill (#6) | pill | absent (R1-#6) | DRIFT | LOW |
| N13 | Toast (8s, hover pause, no dismiss while focused), nudge once and never on first paint | all | `toast :273`; nudge gated on `Notification.permission === 'default'` `:220-230`; timings not re-measured | MATCH (unmeasured) | - |
| N14 | Terminals at cap | "N of M running - free a slot", footer detach/kill, Close all inline confirm | `:2009+` near verbatim | MATCH | - |
| N15 | Two empties | dashed vs failed | `emptyState :167`, `errorState :179`, wired to real `parse_error` `ext_cr_detail.js:3197-3217` | MATCH | - |
| N16 | Degraded honesty, Claude vs Auggie vs Augment ext | explain, never hide | Claude has no degraded block (correct); Auggie: no bg-work note `:619`; Augment VS Code/Cursor: LevelDB block `:620-621`, `augment_ext.py:279-283` `parse_error: None` (honest); Auggie "doesn't record subagents" card replaces the agent map | MATCH | - |
| N17 | Shared modal contract | trap, Esc, restore, PTY untouched | one `trapFocus/open/close` `ext_cr_dialogs.js:328-441`; terminal overlay too `ext_cr_term.js:377` | MATCH | - |
| N18 | Help bound to `?` | yes | Help pill exists `ext_cr_board.js:2408`; `?` binding not re-verified | UNVERIFIED | LOW |

### 3b. README capabilities added since September: control-room home

| capability | CR home | classic-only? |
|---|---|---|
| Model gateway Anthropic/OpenRouter, launcher, slot file | Config > Terminal `ext_cr_dialogs.js:1359-1378` (server-owned "launcher not configured" `:1372`); gateway-aware terminal `ext_cr_term.js:92-94,972`, `ext_cr_detail.js:2084`; `tests/test_cr_board_gateway.py` | no |
| Launch (open/resume terminal, external, attach-first) | `ext_cr_board.js:2884-2937`, `ext_cr_detail.js:1380-1383`, picker `ext_cr_dialogs.js:2166` | no |
| Run (command runner, allowlist) | `ext_cr_detail.js:2063`, `ext_cr_boot.js:724`, Config allowlist | no |
| Tunnel on/off, rotate, credentials, read-only remote | Config > Tunnel `ext_cr_dialogs.js:1406-1580`; `test_cr_tunnel.py`, `test_cr_readonly_ui.py` | no |
| Idle terminal TTL, snapshot TTL, header line, icon style/size | Config rows above | no |
| Model-update nudge + keep | `ext_cr_dialogs.js:2279` (`/api/model-keep`); chip `ext_cr_detail.js:3157` | no |
| Session cost chip + modal | `ext_cr_detail.js:1065,1808` | no |
| Agent map | `ext_cr_board.js:2097,2895`; dialog `ext_cr_dialogs.js:2489-2643` | CR-only (README states) |
| Heartbeat panel | `ext_cr_detail.js:2335` | CR-only (README states) |
| Folder terminals, one terminal per session, parked takeover | server-side `term_vt.py`; CR surfaces via Manage terminals and overlay (`ext_cr_term.js:798` busy-409) | no |
| Model marker chip | CR tiles, rail, header | no |

No capability exists only in the classic UI. The real gaps are the Help table (N10) and Data files (N6).

## 4. Extras

| extra | ruling |
|---|---|
| Tunnel tab in Config | ruled (README `:174`) |
| Heartbeat default + Progress view setting + CAPABILITIES row 61 | ruled (README `:164`) |
| Icon style / size rows | ruled (`reports/icon-config-knobs.md`) |
| Header line, Snapshot TTL, Idle TTL, Gateway, OpenRouter rows | ruled in README `:160-175` only |
| Agent map, model marker chip, cost modal, model-update nudge | README only, no report in the bundle's set: treat as unruled by the owner reports |
| Notifications tab reduced to a pointer note | unruled (code comment cites doc "drift 4") |
| Config "Apply" just closes | unruled, harmless |

## 5. Fixes

- **N1 Live window**: direction: minutes, 1-15, default 5; do NOT change the stored unit (seconds) or the server validator. Way: `ext_cr_dialogs.js:1330` use `sliderCtlCommit(1, 15, Math.round((value != null ? value : 300) / 60), function (m) { onCommit(m * 60); }, ' min')`. Test: Node-exec test next to `tests/test_cr_dialogs_config_exec.py` asserting slider min 1, max 15, commit value is minutes times 60.
- **N6 Data files**: direction: real absolute paths for all live-read files; do not expose contents or the token file. Way: in `server.py` near `:426` add `snap["DATA_FILES"] = {flags: config.FLAGS_FILE, titles: config.TITLES_FILE, pins: config.PINS_FILE, notes: config.NOTES_FILE, model_keep: config.MODEL_KEEP_FILE, config: config.CONFIG_FILE}`; set `srv.dataFiles = cfg.DATA_FILES` at `ext_cr_dialogs.js:1593`; extend the key list at `:1572`. Test: `tests/test_cr_routes.py` asserts GET /api/config returns `DATA_FILES` with those six keys and no `TOKEN_FILE`.
- **N10 Help table**: direction: append post-September capabilities as ids 62+, leave doc rows 1-60 alone. Way: append entries at `ext_cr_dialogs.js:566`; bump the pinned count in `tests/test_capability_table.py:19,248`. Test: that length assertion, red before the append.
- **N12 top-bar live pill**: direction: pill toggling the SAME `liveOnly` uiState as the rail pill, no second filter. Way: `ext_cr_board.js` top-bar build near `:2353`, count with the same `LIVE_WINDOW` comparison as `:1474`. Test: add to `tests/test_cr_topbar_layout.py` (element exists, click toggles `liveOnly`).
- **R1-#10**: `ext_cr_board.js:1208-1210` stable-sort title matches before project/prompt matches; test in `tests/test_cr_search_parity.py`.
- **R1-#7, #43, #52, #57**: no change, known gaps (tooltip-plus-flag-card, parser has no PR title, fork card placement, one-row actions); document in the PR.

## 6. Top 5

1. Help's capability table (61) omits every post-September capability (gateway, tunnel, TTLs, agent map, cost chip), so it under-reports what the app can see (N10).
2. Config "Data files" never receives real paths and lists 4 of 7 data files (N6).
3. Live window slider is 30-1800 s in raw seconds, not 1-15 min (N1).
4. No top-bar "N live" pill, only triage and rail filters (N12).
5. Good news: all 61 capabilities and all 16 `config.EDITABLE` keys plus Tunnel have a control-room home, and both round-2 HIGHs ("something broke" state, model/effort mirror) are CLOSED.
