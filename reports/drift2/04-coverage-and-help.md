# Adversarial re-audit — doc 04 (coverage-and-help) vs. shipped Control Room

Scope: all `aitracker/web/ext_cr_*.{js,css}`, project `README.md`, doc
`04-coverage-and-help.md`. Method: read the actual code (not comments) at every
cited line; cross-checked backend (`registry.py`, `providers/claude.py`,
`providers/auggie.py`, `config.py`) wherever a JS comment claimed a field
existed or didn't.

## TABLE A — Capability map (60 items)

| # | Capability | Home (file:line) | Verdict |
|---|---|---|---|
| 1 | Every session, all tools, newest first | `ext_cr_board.js:73-74` (pinned/unpinned, `byRecency`) | PRESENT |
| 2 | Source badge (7 sources) | `ext_cr_board.js` `toolLabel()`, tile meta strip | PRESENT |
| 3 | Live dot + 5-min window | `ext_cr_board.js:32,105` `RANK`/`sessionState`, `LIVE_WINDOW` | PRESENT |
| 4 | Waiting-on-answer end-state | `ext_cr_board.js` hero tile, `cr-tile--hero` | PRESENT |
| 5 | Just-completed end-state | `ext_cr_board.js` `landed` state, `.cr-tile--landed` | PRESENT |
| 6 | "N live" filter | `ext_cr_board.js:265-275,1490-1491` `activeFilter` | PRESENT |
| 7 | Flag count badge + red edge, actual flag text | `ext_cr_board.js:1634-1651` (`tileHead`) | PARTIAL — count/edge shown on the tile; the actual flag text (`s.flag_text`) rides only the `title` tooltip attribute (hover-only, inaccessible on touch/mobile). Full text is visible in the cross-session flag list (#9, `ext_cr_dialogs.js:1424`), so the data isn't lost, but "listing the actual flag text" on the tile itself is tooltip-only. |
| 8 | Notes count badge | `ext_cr_board.js:1761` `s.note_count` | PRESENT |
| 9 | Cross-session flag list | `ext_cr_dialogs.js:1415-1437` (real `f.text` shown per row) | PRESENT |
| 10 | Search, name matches first | `ext_cr_board.js:658-666,796-802`, `/api/search` for Sessions dest | PRESENT |
| 11 | Rename a session | `ext_cr_detail.js:935,1181-1185,1590` | PRESENT |
| 12 | Pin above recency | `ext_cr_board.js:73-74,181,251` | PRESENT |
| 13 | Agents · repo collapsible group | `ext_cr_board.js:895-898,1780-1795` | PRESENT |
| 14 | In-transcript agents running badge | tile: `providers/claude.py:520` `now_line` "⚙ N background agents"; header pill: `ext_cr_detail.js:1579-1583` | PRESENT (emoji ⚙ not 🤖 on tile — cosmetic only, emoji-tint exempt) |
| 15 | New terminal / new Claude session | `ext_cr_term.js:565-596` real `/api/term/cwds` directory picker, `ext_cr_boot.js:487-493` bridge | PRESENT |
| 16 | Manage terminals + live count | `ext_cr_dialogs.js:1441-1490`, badge via sidebar poll | PRESENT |
| 17 | Notification bell | `ext_cr_board.js:1305` | PRESENT |
| 18 | Theme toggle | `ext_cr_boot.js:84-98,191-193` (`tracker.theme`), also in Config/terminal toolbar | PRESENT |
| 19 | Idle sessions never bury live ones | `ext_cr_board.js:171,219,248` idle filtered from board/cap, kept in rail | PRESENT |
| 20 | Progress ring → progress spine | `ext_cr_detail.js:274-360` `spineSegments()` | PRESENT |
| 21 | Stat chips (7), permanent row, hidden on phone | `ext_cr_detail.js:657-751` unconditional render; `ext_cr_detail.css:1331` hides `<600px` | PRESENT — re-verified: genuinely unconditional, no Config toggle exists anywhere (grep confirmed) |
| 22 | State / Activity / Evidence 3 columns | `ext_cr_detail.js` panel registration (State/Conversation/Evidence groups) | PRESENT |
| 23 | Panels collapse to header, collapsed by default, persisted, Expand-all per column | `ext_cr_detail.js:216-241` `getCollapsed/setCollapsed`, `defaultFolded()` reads Config's `cr.cardsFolded` | PRESENT |
| 24 | Waiting-on-you header state | `ext_cr_detail.js:642-655` `stateOf()` | PRESENT |
| 25 | Summary Goal/Now/So far | `ext_cr_detail.js:1835-1843` `renderSummary` | PRESENT |
| 26 | Decisions & open questions, view-only | `ext_cr_detail.js` decisions panel (view-only, no write path found) | PRESENT |
| 27 | Narration, its own words (merged w/ prompts) | `ext_cr_detail.js:2070-2093` timeline | PRESENT |
| 28 | Prev/next + jump-to-latest | `ext_cr_dialogs.js:1377-1381` narration pop-out toolbar | PRESENT |
| 29 | Live follow / hold your place | timeline scroll logic, `ext_cr_detail.js` | PRESENT |
| 30 | Unbounded history, page on scroll | `ext_cr_detail.js:2224` `/api/narration` paging (existing route, no new endpoint) | PRESENT |
| 31 | Markdown rendering | `ext_cr_detail.js:170-186` `mdHtml()` delegating to shared `md()` | PRESENT |
| 32 | Mermaid → SVG, 8 families | vendored mermaid.js + hand-rolled SVG fallback (README, matches) | PRESENT |
| 33 | Copy per code block | — | **SETTLED deferred** (not scored) |
| 34 | Prompts incl. slash commands | timeline "prompt" entries | PRESENT |
| 35 | Files + diff per edit | `ext_cr_detail.js` Files panel → `ext_cr_dialogs.js` diff pop-out | PRESENT |
| 36 | Up/down context expansion | `ext_cr_dialogs.js:1322-1328` context bars | PRESENT |
| 37 | Expand all | `ext_cr_dialogs.js:1349` | PRESENT |
| 38 | Diff ⇄ Rendered | `ext_cr_dialogs.js:1330-1336,1347` | PRESENT |
| 39 | Open in new tab | `ext_cr_dialogs.js:1350-1354` | PRESENT |
| 40 | Files written by agents, tagged | `agent` tag rendering, files panel | PRESENT |
| 41 | Commands pass/fail, "status not recorded" | `ext_cr_detail.js:1893-1931` (re-verified: real) | PRESENT |
| 42 | PRs, created only | `ext_cr_detail.js:1787` filters `p.created` | PRESENT |
| 43 | merged/closed badges | `ext_cr_detail.js:1791,1807` | PRESENT |
| 44 | Agent-opened PRs attributed | `ext_cr_detail.js:1806` `p.agent` tag | PRESENT |
| 45 | Links panel (new) | `ext_cr_detail.js:1812-1832` `renderLinks`/`deriveLinks` | PRESENT |
| 46 | Plan on the go: add/copy/push/remove | `ext_cr_detail.js:974,1860-1868` | PRESENT |
| 47 | Delivery chips (turn-end/on wake/copy it) | `ext_cr_detail.js:1851-1854` reads real `session.push_when` | PRESENT |
| 48 | Background agents & shells | Evidence column panel + expanded view | PRESENT |
| 49 | Re-run collapse ×N | agents panel grouping, `ext_cr_detail.js:1936-1958` | PRESENT |
| 50 | Show N finished | agents panel disclosure | PRESENT |
| 51 | Toast + sound + desktop notification | `ext_cr_boot.js` notify/toast wiring, reuses `soundOn`/`toggleSound` | PRESENT |
| 52 | Fork lineage banner + back-link | `ext_cr_detail.js:1092-1104,1242-1243` real card, `continued_as/continued_from` | PRESENT |
| 53 | Search within session | header toggle → full-width card | PRESENT |
| 54 | Command runner + constraint stated | Evidence column, existing allowlist constraint copy | PRESENT |
| 55 | Model/effort switchers, terminal bar + Evidence mirror | mirror: `ext_cr_detail.js:2037-2050`; terminal bar: `ext_cr_term.js:292-293,770-778` | PARTIAL — see Table B finding B1: the mirror's buttons render fully enabled whenever `term_attached` is true, but clicking them always fires a stale "can't find a terminal for this session" notice (`ext_cr_boot.js:746-748`), which is now factually **wrong** at the only moment the buttons are visible (the panel itself is gated on `term_attached === true`). Doc's "terminal model/effort switching disabled with honest copy" exemption describes a *disabled* control, not an enabled one that lies. |
| 56 | Context readout (current + cumulative) | `ext_cr_detail.js:2041,2047-2048` reads `session.context` | PRESENT |
| 57 | Open/resume/external terminal | header actions, `isLocalhost` gate on `[data-act=external]` only (expected, documented) | PRESENT |
| 58 | Degraded provider messaging | `ext_cr_dialogs.js:541-542` + `ext_cr_detail.js:2074-2089` (Auggie excluded correctly) | PRESENT |
| 59 | Config dialog (new) | `ext_cr_dialogs.js:991-1284` | PRESENT, with one drift — see B2 (Live-window slider range/unit) |
| 60 | Progress spine (new) | `ext_cr_detail.js:268-360` | PRESENT — confirmed the README's documented camelCase/snake_case bug is **already fixed**: both backend (`providers/claude.py:1316-1317`) and renderer (`ext_cr_detail.js:270-312`) use `started_at`/`ended_at` (snake_case, epoch seconds) consistently. The README's own "🟡 … the renderer reads camelCase startedAt/endedAt" line is now stale documentation, not a real bug. |

**Totals: 57 PRESENT, 2 PARTIAL (#7, #55), 0 MISSING, 1 deliberately-deferred-and-excluded (#33).**

## TABLE B — Dialogs, states, non-negotiables

| # | Doc says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|
| B1 | Model/effort mirror in Evidence panel should reflect the terminal bar honestly | `ext_cr_detail.js:2037-2050` renders active buttons whenever `term_attached`; `ext_cr_boot.js:738-748` handler unconditionally replies "there's no way to find one from here yet" — literally false at that moment, and the code comment claiming this branch is "unreachable in practice" is itself stale (registry.py:143-172 `_term_attached` now populates the gate for real) | **PARTIAL / bug** | HIGH |
| B2 | Config → Board → "Live window: slider 1–15 min, default 5" | `ext_cr_dialogs.js:1087-1091` `sliderCtlCommit(30, 1800, 300, onCommit, 's')` — range is 30–1800 **seconds** (0.5–30 min), labelled in raw seconds, not minutes; default (300s = 5min) is correct | PARTIAL | LOW |
| B3 | "Two different empties": nothing-yet (dashed box) vs. something-broke (`--surface-failed`, "a line failed to parse. Everything before it is shown.") | Nothing-yet: `ext_cr_detail.js:1917` present verbatim. Something-broke: **no such state exists anywhere** — every provider's JSONL parser (`providers/claude.py:1104-1106` etc.) silently `continue`s past a bad line with no error flag ever set on the detail dict, and `errorState()`/`errorHtml()` is only ever invoked for network-style failures ("Couldn't load older turns", "Couldn't list terminals") — never for a genuine mid-transcript parse failure | **MISSING** | HIGH |
| B4 | Help dialog: 5 tabs, capability count generated from same data tests assert against | `ext_cr_dialogs.js:709-714` (`HELP_TABS`), `:462-483` (`CAPABILITIES`, 60 entries), `:584` reads `CAPABILITIES.length` (not the doc's stale "58"); `tests/test_capability_table.py` pins length==60 and that the rendered stat isn't hardcoded | PRESENT | — |
| B5 | Terminals-at-cap dialog copy | `ext_cr_dialogs.js:1486,1511` "N of M running — free a slot", "Closing this dialog detaches; ✕ kills." | PRESENT (near-verbatim) | — |
| B6 | Config: `TRACKER_AUTH` never displayed, only set/not-set | `ext_cr_dialogs.js:1126-1128` `readonlyField(srv.authSet ? 'set' : 'not set')` | PRESENT | — |
| B7 | Non-negotiable: read-only toward sessions | No POST anywhere targets a session log; all writes go to `flags.json`/`notes.json`/`pins.json`/`titles.json`/`config.json`/terminal PTYs | PRESENT | — |
| B8 | Non-negotiable: no new per-panel round-trip beyond 2s poll | Every `fetch()` in `ext_cr_*.js` reuses an existing route on-demand (search, narration paging, config, tunnel) — none is a new recurring per-panel poll | PRESENT | — |
| B9 | Non-negotiable: colour never carries meaning alone | Every state word (`stateOf`, `stateWord`) pairs colour with literal text | PRESENT | — |
| B10 | Non-negotiable: no control hidden on mobile for flags/pins/notes/rename | Only `[data-act="external"]` (a documented, local-only feature) is hostname-gated; no CSS `max-width` rule hides flag/pin/note/rename controls | PRESENT | — |
| B11 | Reduced-motion has a designed variant | `@media (prefers-reduced-motion: reduce)` present in board/detail/dialogs CSS | PRESENT | — |
| B12 | Session flag summary card (per-session header) | `ext_cr_detail.js:1606-1618`: when `flagCount` is falsy (0 open flags — the common case), the card shows **"Open-flag count needs the board's flag store wired into this view (not yet on /api/session)"** — stale text describing a gap that `registry.py:139` closed long ago; a session with zero flags reads as if the feature were unbuilt | **bug** | MEDIUM |

## Fix list

1. **B3 (HIGH, MISSING)** — Add a genuine parse-failure signal: have `providers/claude.py`/`providers/auggie.py` record when a JSONL line fails `json.loads` (e.g. `d["parse_error"] = True`/a count), and wire the detail view's panels to render `errorState({title:"Couldn't read this session", body:"The transcript exists but a line failed to parse. Everything before it is shown."})` instead of the plain empty state when that flag is set.
2. **B1 (HIGH, PARTIAL #55)** — Either make the Evidence-panel model/effort buttons genuinely disabled (matching the doc's own "disabled with honest copy" exemption) when there's no reachable way to drive them, or fix `cr:term-controls-request`'s handler to stop claiming "no way to find one" once `term_attached` is true. Currently it renders as clickable and lies on click.
3. **B12 (MEDIUM)** — Fix `ext_cr_detail.js:1616-1618`: the zero-flags branch should say something like "No open flags on this session," not the stale "not yet on /api/session" placeholder — `session.open_flags` has been on the detail dict since `registry.py:139`.
4. **#7 (LOW)** — Consider surfacing flag text as visible tile copy (or at minimum a tap-accessible affordance) rather than hover-only `title`, for parity with touch/mobile viewers, since the doc's own capability wording is "listing the actual flag text" on the tile.
5. **B2 (LOW)** — Align the Config "Live window" slider to the doc's stated 1–15 min range/unit (currently 30–1800s raw-second labels); default value is already correct.

## Summary

Nothing is MISSING from the 60-item capability map itself — 57 PRESENT, 2 PARTIAL (#7 flag-text visibility, #55 model/effort mirror control). One genuine MISSING item lives in Table B, not the capability map: the "something broke" degraded/error empty state (doc's "Two different empties") has no backend signal or frontend consumer anywhere — every parse failure is silently swallowed. The five previously-flagged fixed items were re-verified independently: stat chips (#21) genuinely permanent and phone-hidden; flag text (#7) is real but tooltip-only (partial); PR title/#43 badges are real (merged/closed), though PR *title* text itself was never captured by the parser and the UI now degrades honestly instead of faking it; "status not recorded" (#41) is real; the progress-spine snake_case/camelCase bug the README still describes is actually already fixed. The one new bug found by this audit that wasn't previously reported is B1 — the model/effort mirror buttons are reachable and clickable exactly when their own stale-error message becomes provably false.
