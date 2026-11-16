# Drift round 3: 02-shell-and-board.md

- Doc audited: `design_handoff_control_room/02-shell-and-board.md` (245 lines).
- Precedence applied: **docs win** (commit `7b87cce`, 2026-09-05, "the docs win ... emoji excepted") over the 2026-08-29 "HTML wins" ruling, because it is later. Later owner rulings (refinements, tiles/rail parity, headline) are honoured over both and cited per row.
- Code SHA: `76bd154`. Files read: `aitracker/web/ext_cr_board.{js,css}`, `ext_cr_boot.{js,css}`, `index.html`.
- All `ext_cr_board.js` lines below are in the current file (3280 lines); several round-1/2 line numbers have moved.

## 2. Prior-finding status

Round 1 (`reports/drift/02-shell-and-board.md`) rows that were not MATCH, plus round 2 (`reports/drift2/02-shell-and-board.md`) rows. Round-2 rows 1, 8, 9 and 14 restate round-1 items 1.1, 3.4, 3.5, 4.3, 9.1 etc.; they are listed once.

| id | finding (short) | status now | evidence |
|---|---|---|---|
| R1 1.1 / R2 1 | `#tryNext` not "after the N live pill" | SUPERSEDED-BY-RULING (owner moved it into the classic main header `.htop`, wrapped with `#flagbtn` in `.tn-pair`) | `ext_cr_boot.css:41-67` (ruling comment + `.tn-pair`); `index.html:115`. `#livecount` is at `index.html:83`. 7b87cce moved it to the sidebar, a later change moved it again; the comment calls it "OWNER RULING". No report file records it (see Extras E1). |
| R1 1.2 | `position:absolute` instead of flex child, `margin-left:auto` | CLOSED | `ext_cr_boot.css:60-82`: inline-flex, no absolute; `margin-left:auto` is on `.tn-pair`. |
| R1 1.6 | rail toggle before the back button | SUPERSEDED-BY-RULING (doc's own line 108 says the toggle is leftmost) | `ext_cr_board.js:2300-2306` toggle, then `:2321` back. |
| R1 3.4 / R2 8 | 1024px lands in the 1-column tier | CLOSED | `ext_cr_board.css:1467-1472` (`max-width:1279` 2 col, `max-width:1023` 1 col); JS `ext_cr_board.js:1135` uses `>= 1024`, `bindResize` `<1024` underlay at `:1160`. |
| R1 3.5 / R2 9 | collapsed rail 48px vs 56px | CLOSED (48px board, 56px detail, per README decisions 1 and 6) | `ext_cr_board.css:619,626`. |
| R1 4.2 / 4.3 / R2 11 | extra "Sessions" destination pill | STILL OPEN (EXTRA, unruled) | `ext_cr_board.js:2341-2349` (`pillSessions`), `:1842` `openSessionsDestination`. Doc 02 names only Board and Terminals. The "requirement 3: Board, Sessions, Terminals" comment at `:2325` shows a request, but no report in `reports/` records it. |
| R2 14 | New session had no `title` | CLOSED | `ext_cr_board.js:2419` has `title` and `aria-label`. |
| R1 5.2 | `tracker.rail` key, `open/collapsed`, default `open` | STILL OPEN (LOW) | `ext_cr_board.js:601-608` key `tracker.rail.mode`, tri-state `auto/open/collapsed`, default `auto`. The 1024-1279 auto-collapse is what the doc's breakpoint table needs, so the third value is justified; the key name is still not the doc's. |
| R1 5.5 | search placeholder "Search" + separate `⌘K` kbd, not "Search · ⌘K" | STILL OPEN (LOW, cosmetic) | `ext_cr_board.js:999,1010`. |
| R1 6.3 | triage counts 31px | CLOSED | `ext_cr_board.css:1370` `font-size:33px`. (Below 1440 it drops to `--fs-triage-count-min`, `:1371-1373`; doc says 33px flat, see N8.) |
| R1 7.1 | cap configurable 3-8 | SUPERSEDED-BY-RULING (doc 04: 3-12, default 8; 7b87cce) | `ext_cr_board.js:269-274`. |
| R1 7.4 / A3 | ungrouped agent sessions dropped | CLOSED | `ext_cr_board.js:199` `isGroupedAgent` (agent AND group), used at `:405`; commit `317db79`. |
| R1 9.1 | "project . tool" sub-line only on the hero | CLOSED | `ext_cr_board.js:2911` for every tile. |
| R1 9.2 | working border and glow gated on bg agents | CLOSED | `ext_cr_board.css:1533-1566` region comment; unconditional per `:1481-1488`. Also `tests/test_working_glow_board.py`. |
| R1 9.3 | hero side rail lacks todo ticks, files, failing counts | STILL OPEN (MED). See N3. | `ext_cr_board.js:2927-2940`: notes count plus button only. |
| R1 9.4 | hero frame uses `--state-awaiting/--line-awaiting` instead of orange-2/orange-4 | STILL OPEN (LOW, tokens audit) | `ext_cr_board.css:1565`. |
| R1 A5 | no Failing state | CLOSED | `ext_cr_board.js:32` RANK has `failing`; `:50` `sessionState`. |
| R1 A8 | no scroll preservation on poll | CLOSED (per round 2 row 30; commit 317db79 `paneScroll`). Not re-run in a browser. | `ext_cr_board.js:3095-3099` region; round-2 `:1509,1524`. |
| R1 A11 | flag text not on tile | STILL OPEN as N2 (data now exists: `registry.py:97,235` `flag_text`, but the board tile never reads it). | `grep flag_text ext_cr_board.js` returns only the rail tooltip, `:1983`. |

Totals for prior rows: CLOSED 10, SUPERSEDED-BY-RULING 4, STILL OPEN 6 (Sessions pill, `tracker.rail` key, search label wording, hero sidebar, hero gradient tokens, A11 flag text), REGRESSED 0.

## 3. New drift

Sections walked in order: entry, mode switching, first-run, way back, shell, breakpoints, top bar, rail, ordering, triage, board, sort, tile anatomy, ticks, cap footer, keyboard.

| # | doc section + line | doc says | code does | verdict | sev |
|---|---|---|---|---|---|
| N1 | Board "Sort order", 188-197 (`filter(s.state !== 'idle')`; "Idle sessions never get a tile") | idle sessions are excluded from the board and only counted in the footer | `ext_cr_board.js:405-424`, comment `:343-356`: idle is NOT excluded, the cap backfills with the most recent idle sessions. Introduced by `317db79` (a bug fix for an empty board with 957 idle sessions). `reports/board-tiles-rail-parity.md:42-46,119-121` flagged this as "needs an owner ruling, NOT taken unilaterally"; no later report records the ruling, although the code comment says "as amended by the owner". | DRIFT (reversal of a doc rule, ruling only asserted in a code comment) | HIGH |
| N2 | Tile anatomy table, Flagged row, 216 | "flag text in a `--surface-raised` inset" | The inset exists (`ext_cr_board.css:1695-1700`) but its content is `s.now_line` (`ext_cr_board.js:2840-2847`), never `s.flag_text`, which the server now supplies (`registry.py:97`). The flag count is in the head label only. | DRIFT | MED |
| N3 | Tile table, Awaiting row, 213 | hero side rail: todo ticks + files/failing/notes counts | `ext_cr_board.js:2927-2940`: notes count and the button only. Todo ticks are in the main column. Files and failing counts were "not in the list dict" (comment `:2924`). `fail_cmd` is already in the list dict (used at `:50`), so a failing count is derivable. | DRIFT | MED |
| N4 | "The board" no show-more, 193-196 ("No 'show more' on the board"); app shell box line 78 | no "show more" control | Cap footer has "Show all N" / "Show fewer" (`ext_cr_board.js:3021-3027`), `showAll` lifts the cap (`:430`). Added in `317db79`; no ruling report. | EXTRA, contradicts a doc rule | MED |
| N5 | Triage strip, 153-170 | **four cells**: three counts + histogram | Five cells: a fourth count cell `PINNED` is inserted before the histogram (`ext_cr_board.js:2506-2507`). Round 1 row 6.2 matched this when there were three. Only `reports/control-room-drift-analysis.md` mentions it. | EXTRA, breaks "four cells" | LOW |
| N6 | Sort order, 180-189 | state rank, **then pinned**, then recency | Pinned removed from the board comparator (`ext_cr_board.js:407-423`). Code cites an owner ruling; `reports/board-rail-headline.md`/refinements do not contain it (the user's "tiles ordered by recent activity" ruling was reported in the task as a later ruling). Treated as ruled by the user brief, no file citation found. | SUPERSEDED-BY-RULING (cite missing) | LOW |
| N7 | App shell, 66-80 and rail table 120 | rail 232px open; top bar 54px single row | Rail is 300px (`ext_cr_board.css:605`, "OWNER RULING ... same width as classic sidebar"). Top bar wraps to two rows below 1280px with `height:auto` (`ext_cr_board.css:1467-1480` region at `:475-486`), which breaks "54px" and the single-row top bar. Owner-triggered overflow fix, pinned by `tests/test_cr_topbar_layout.py`. | DRIFT (ruled for the 300px; the 2-row wrap is a fix with no ruling) | LOW |
| N8 | Triage strip, 157-158 | counts 33px at all widths | `ext_cr_board.css:1371-1373`: below 1439px the size drops to `--fs-triage-count-min`. | DRIFT | LOW |
| N9 | Top bar, 110 | icon-only controls need `title` and `aria-label` from **the same string** | Back button: `title:'Classic dashboard'` vs `aria-label:'Back to classic dashboard'` (`ext_cr_board.js:2321-2323`). Rail toggle label text "Sessions" is visible at wide widths (`:2305`), but title and aria-label match. | DRIFT | LOW |
| N10 | Top bar item 3, 99 | Terminals pill shows "3 of 12" | MATCH (`ext_cr_board.js` `tc.open + ' of ' + tc.total`, per round 2 row 12) | MATCH | none |
| N11 | Cap footer, 226-232 | "8 of 23 - The board never shows more than 8 tiles. Everything else lives in the rail - pinned on top, newest first in each group. - Scroll for the rest" | Copy rewritten: "The board never shows more than N tiles - ranked by what needs attention first, then by most recent activity. Everything else lives in the rail. -" (`ext_cr_board.js:3005`). Prior ruling (redesign.md, decision 1) said "current copy is fine, leave it", and the new copy matches the changed sort. "Scroll for the rest" focuses the rail search input rather than the rail (`:3013`), close enough. | DRIFT (copy), SUPERSEDED-BY-RULING for the pin wording | LOW |
| N12 | Tile anatomy, 203-208 | non-awaiting title is the tile title | Title is `name - dir` for non-awaiting (`ext_cr_board.js:2806-2811`) | SUPERSEDED-BY-RULING (`reports/control-room-redesign.md` decision 3) | none |
| N13 | Session rail ordering/grouping, 130-143 | two groups, pinned then unpinned, newest first | `railOrder` is verbatim (`ext_cr_board.js:71-76`); a group-by control subdivides the unpinned bucket (`:101-130`, `:1035-1042`), pinned still leads | SUPERSEDED-BY-RULING (redesign.md decision 2) | none |
| N14 | Mode switching / first run / back / histogram aria / keyboard / 18 bars / sort RANK with `failing` / hero span 2 / agent groups last / todo ticks / sticky footer / ⌘K, j, k, Enter, Esc, t, ? | as written | MATCH (`ext_cr_boot.js:1205-1220`, `ext_cr_board.js:32,2513,2575-2587,3047-3090`, `ext_cr_board.css:1467-1472`). Esc clears the filter at `ext_cr_board.js:3073-3075`. Focus and scroll preservation after polling are not re-run in a browser this round. | MATCH | none |

## 4. Extras (no source in the bundle)

| id | behaviour | where | ruled? |
|---|---|---|---|
| E1 | Entry button lives in `.htop` main header beside "Flag an issue", wrapped in `.tn-pair` (not the sidebar pill) | `ext_cr_boot.css:33-67`, `index.html:115` | code comment says "OWNER RULING"; **unruled in reports** |
| E2 | Third top-bar destination "Sessions" with browse, search, pagination | `ext_cr_board.js:1842`, `:2341` | unruled |
| E3 | Idle backfill and "Show all N" cap-footer toggle (N1, N4) | `ext_cr_board.js:389-436`, `:3021` | `board-tiles-rail-parity.md` parked it as an open question; not ruled |
| E4 | PINNED triage cell (N5) | `ext_cr_board.js:2506` | unruled |
| E5 | Rail group-by select (directory/activeness/24h/7d/30d/none) | `ext_cr_board.js:101-130,1035` | ruled (`control-room-redesign.md` decision 2) |
| E6 | 300px rail, `--cr-rail-w` | `ext_cr_board.css:605` | ruled in code comment (owner "same width as classic"); `board-tiles-rail-parity.md` clause 2 covers it |
| E7 | Board tile cap slider 3-12 | `ext_cr_board.js:269` | ruled (doc 04 + 7b87cce) |
| E8 | Job-summary headline pill on tiles and rail | `ext_cr_board.js:2836-2859` | ruled (`board-rail-headline.md`) |
| E9 | Agent map button on tiles (`s.agent_map_n`), Resume button on awaiting tiles | `ext_cr_board.js:2895-2899`, `:2933` | agent map: unruled in this slice's reports; resume: unruled |
| E10 | Rail `Failing` state and `failing` tile state | `ext_cr_board.js:32,50` | ruled (A5 in the drift analysis) |
| E11 | Cross-view `uiState` shared store (sid, filter, showAll, query, scroll) | `317db79` | owner request quoted in the commit; no report |
| E12 | `?ui=next|classic` query override | `ext_cr_boot.js:1223-1230` | unruled |

## 5. Fixes for DRIFT/MISSING findings

**N1 idle backfill (HIGH).** Direction: get an owner decision first; both "idle never tiled" (doc) and "board never blank" (bug) are real. If the doc wins, keep idle excluded but show an empty-state card ("Nothing needs you. N sessions are idle, see the rail"), not a backfill. If the owner confirms backfill, record it in a report and change the doc-facing copy only. Must NOT change: filter-before-cap (the `317db79` fix is correct and separate). Way: `boardTiles()` `ext_cr_board.js:405` add `&& state !== 'idle'` when `filterKey` is absent (keep idle when a filter like `pinned` asks for it). Test: a `tests/test_cr_board_order_and_empty.py` case with 5 idle + 2 working sessions asserting 2 tiles and total 7 (red today: 7 tiles).

**N2 flag text (MED).** Direction: in `tileLine()` for `state === 'flagged'`, use `s.flag_text` before `now_line`. Not change: the head label. Way: `ext_cr_board.js:2840`, `var txt = state==='flagged' ? (s.flag_text || nowLine) : nowLine`. Test: unit in `tests/test_cr_board_order_and_empty.py` rendering a flagged session with `flag_text:'Pushed note stuck'`, assert the string is inside `.cr-tile-line`. Red today.

**N3 hero side rail (MED).** Direction: add files and failing counts to `.cr-tile-counts`, and a todo-ticks mini block. Not change: the Resume/Open terminal button. Way: `ext_cr_board.js:2927-2931`, add rows from `s.files_n` if the list dict has one (check `registry.py` first; if absent, add `files_n`/`fail_n` to the shared list shape in both providers) and `s.fail_cmd ? 1 : 0`. Test: a `tests/test_cr_registry_fields.py` assertion for the new fields on both Claude and Auggie, plus a JS-render case.

**N4 Show all (MED).** Direction: owner ruling needed. If doc wins, remove the toggle; the rail is the overflow. Way: delete `ext_cr_board.js:3021-3027` and the `showAll` argument path (`:389,430,2618,3096`). Test: assert the cap footer has no "Show all" text.

**N5 PINNED cell (LOW).** Direction: record a ruling or move "pinned" into the rail only. Way: `ext_cr_board.js:2507`. Test: assert `.cr-triage-cell` count is 3 plus histogram.

**N7/N8 (LOW).** Wrap tier: either document as an owner exception in `reports/control-room-refinements.md` or keep one row with icon-only compaction at all widths. N8: remove the `max-width:1439px` override at `ext_cr_board.css:1371-1373`, or document it. Test: `tests/test_cr_topbar_layout.py` style CSS assertions.

**N9 (LOW).** `ext_cr_board.js:2323`: set `aria-label` equal to `title` (both 'Classic dashboard'). Test: assert equality of the two attributes on `.cr-back`.

**N11 (LOW).** Restore "pinned on top, newest first in each group" wording in the rail sentence, or leave as ruled. Visual only.

**Open pieces from section 2:** Sessions pill (E2) needs a ruling to stay; `tracker.rail` key rename (`ext_cr_board.js:601`) needs a migration that reads both keys; search label (`:999`) set placeholder to "Search · ⌘K" and drop the kbd. Tests: string assertions in `tests/test_cr_rail_toggle.py`.

## 6. Top 5

1. N1: idle sessions now get tiles, reversing "Idle sessions never get a tile"; the only ruling is a code comment (`ext_cr_board.js:343`).
2. N4: the cap footer has a "Show all N" toggle that lifts the 8-tile cap, against "No show more on the board".
3. N2: flagged tiles show the status line, not the flag text, though the server now provides `flag_text`.
4. N3: the awaiting hero's side rail lacks files/failing counts and todo ticks.
5. N5/E2: a fifth triage cell (PINNED) and a third "Sessions" destination pill that the doc's "four cells" and "Board, Terminals" do not allow, both with no ruling report.
