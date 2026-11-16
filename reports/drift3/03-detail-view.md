# Drift round 3 - 03-detail-view.md vs the Control Room detail view

- Doc audited: `design_handoff_control_room/03-detail-view.md` (296 lines), read in full.
- Precedence applied: DOCS WIN (commit `7b87cce`, 2026-09-05, "the docs win"; it reverses the 2026-08-29 "HTML wins" ruling, emoji tint recipe excepted). Where the prototype and the doc disagree, the doc is the yardstick. Owner rulings made AFTER 7b87cce (heartbeat default, Now card above the spine, spine motion/zoom, job-summary headline) are honoured as SUPERSEDED-BY-RULING.
- Code SHA: `76bd154`. Files: `aitracker/web/ext_cr_detail.js` (3759 lines), `ext_cr_detail.css` (2283), `ext_cr_board.{js,css}` (orb rail), `ext_cr_boot.js`, `registry.py`. Line numbers for statements inside a function are given as the function's range where I did not re-grep the exact line.
- Read-only audit. Only this file was written.

## 2. Prior-finding status

Round 1 (`reports/drift/03-detail-view.md`, ids as in that file)

| id | finding | status now | evidence |
|---|---|---|---|
| 1.1 | back-line "N of M needing attention" never fed | CLOSED | `ext_cr_boot.js:1039,1048` `computeTriage`; `ext_cr_detail.js:2344-2354` |
| 1.2 | metaline drops cwd path, adds model | STILL OPEN (LOW) | `ext_cr_detail.js:2404` metaBits = project, branch, elapsed, tokens; model is a separate chip (`:1358`). Doc: "ai-tracker . ~/dev/ai-tracker . term-tiers . 41m" |
| 1.3 | `session.pinned` missing on detail dict | CLOSED | `registry.py:231`; `ext_cr_detail.js:1399,1224` (now an always-visible toggle, see Extras) |
| 1.4 | 7-chip stat row removed | CLOSED | `ext_cr_detail.js:1038-1062` statChipsHtml; `--` marker `:1019`. `N/A` branch absent by design (every field exists for both providers, comment `:1013`) |
| 1.5 | actions collapsed into ONE row | STILL OPEN (HIGH) | `ext_cr_detail.js:1377-1385` single `.crd-row1-actions` span |
| 1.6 | "Resume" not "Resume here" | STILL OPEN (LOW) | `ext_cr_detail.js:1381` |
| 1.7 | dark theme solid/outline = white | CLOSED (MATCH) | `.cr.is-dark .crd-btn-solid` rules in css |
| 1.8 | fork banner is a card at the bottom of Evidence | STILL OPEN (HIGH) | `ext_cr_detail.js:1633` (`evidenceBody.appendChild(forkCard)`), css `:549-564` |
| 1.9 | fork copy both directions | CLOSED as structure; copy see R2 1l | `ext_cr_detail.js:2572-2600` |
| 3.1-3.5 | grid, order, 1024-1279 two-col, <1024 one-col, per-column Expand/Collapse | CLOSED (MATCH) | css `:962` `.78fr 1.34fr .78fr`; `:1783-1794`; skeleton `:1497-1546` |
| 4.2 | PR panel shows no title | STILL OPEN (MED, data gap) | `renderPRs` `:2800` renders `—`; `util.py:165-187 collect_prs` never captures a title |
| 4.3-4.5, 4.8, 4.9 | Links, Summary, Plan, Agents, Run panels | CLOSED (MATCH) | `ext_cr_detail.js:2829-2893, 2982-3087` |
| 4.6 | Files: no basename emphasis | STILL OPEN (LOW-MED) | `renderFiles` `:2896-2917` (whole path in one span); css `:1251-1258` has no weight split |
| 4.7 | "42 . status not recorded" never produced | CLOSED (dormant for real data) | `renderCommands` `:2919-2935` |
| 4.10 | Terminal controls gated on a field nobody set (A4) | CLOSED | `registry.py:250` `d["term_attached"]`; `renderTerminalPanel` `:3133` |
| 4.11 | EXTRA panels | see section 4 | |
| 5.1-5.5 | collapsed by default except Timeline; persistence; tint; counts | CLOSED (MATCH), Heartbeat/Spine also open by default (ruled) | `ext_cr_detail.js:277-306, 325-328` |
| 6.1, 6.3 | merged timeline, entry anatomy | CLOSED (MATCH) | `mergeTimeline` `:768`; `entryHtml` `:3257-3347`; css radii `12px 12px 4px 12px` (~`:1455`), ask (~`:1611`) |
| 6.2 | four legend words are filter chips + pop-out | STILL OPEN (LOW) | skeleton `:1640-1662` (pop-out `:1658`) |
| 6.4 | newest-first timeline | STILL OPEN (MED) | `Detail.prototype.mount` `timelineStuckLatest` comment block (~`:1575-1585`) and its scroll handler (~`:1675-1700`): stuck = `scrollTop < 40` |
| 7.1-7.5, 7.7, 7.8 | spine existence, math, header, segments, footer, a11y | CLOSED, with role=group instead of role=img SUPERSEDED-BY-RULING (`reports/spine-motion-vs-design-docs.md` s4) | `spineSegments` `:552`; `renderSpine` `:2606` |
| 7.6 | collision nudge is 2 percentage points, not 10px | STILL OPEN (LOW) | `ext_cr_detail.js:732` |
| 8.1, 8.2 | decision panel view-only | CLOSED (MATCH) | `renderDecisions` `:2768` footer verbatim; no fetch |
| 9.1, 9.8 | fixed bottom bar, hit targets | CLOSED | css `.crd-phonebar` `:1698-1716` `position: fixed`; back chevron 44x44 (`:1928-1933`); 48px send (`:1740`) |
| 9.2 | phone spine compressed | STILL OPEN (LOW) | css `:2110-2113` hides labels only at <=480 |
| 9.4-9.7 | phone breadcrumb+7/11, presence orb, 21px narration, awaiting card | CLOSED | `renderPhoneHead/Presence/Awaiting` `:1120-1196`; css `:1965, 2017-2025` |
| 10.1-10.7 | provider degradation | CLOSED (MATCH) | `providerNote` `:3187`; `renderTimeline` `:3221`; agents degraded card `:3055-3068` |

Round 2 (`reports/drift2/03-detail-view.md`)

| id | finding | status now | evidence |
|---|---|---|---|
| 1a-1c, 1h-1j, 1m | identity row, goal, chips, dark, flag text, back-line, empty lineage | CLOSED (MATCH) except the goal source, see N1 | `renderHeader` `:2385-2470` |
| 1d | six actions in one row, not two | STILL OPEN (HIGH) | as 1.5 |
| 1e | Search/Flag icon-only | CLOSED at >=901px (labels `.crd-btn-label` shown, css `:434`); icon-only again <=900px by design (css `:1848-1850`), a partial regression | |
| 1f | "Resume" copy | STILL OPEN (LOW) | `:1381` |
| 1g | extra "Queue a note" button | STILL OPEN as EXTRA (LOW) | `:1382`, card `:1455-1459` |
| 1k | fork banner placement | STILL OPEN (HIGH) | as 1.8 |
| 1l | fork copy drops "Resume was refused ... background agent" | STILL OPEN (MED) | `renderForkBanner` `:2572-2600`: label "Forked", body "You're on the copy; the original - X - is still running." |
| 6b | extra kind filters | STILL OPEN (LOW) | as 6.2 |
| 6d | tool-call duration absent | STILL OPEN (LOW, data gap) | `entryHtml` tool branch `:3329-3338` has verb/target/agent/count only; no duration field in either provider |
| 6g | newest-first inverts chat metaphor | STILL OPEN (MED) | as 6.4; no owner ruling found in `reports/` |
| 7c | collision offset | STILL OPEN (LOW) | as 7.6 |
| 7d | spine click-to-jump dead | CLOSED | `scrollTimelineToTodo` `:2203-2222` matches by todo `started_at` (no-op when a todo has no timestamp, e.g. Augment-ext: honest) |
| phone | back chevron 28px; sticky not fixed; 481-600 band duplicated back-nav + missing compose bar; stop disabled | CLOSED (all four) | css `:1928`, `:1708`, `:2076-2092`; stop wired via `term_tty` (`renderPhoneStop` `:1158`, `phone-stop` case `:2109`) |
| phone | spine labels hidden only <=480 | STILL OPEN (LOW) | css `:2110-2113` |
| PR title | data gap | STILL OPEN (MED) | as 4.2 |
| Files | basename + `+N/-N` are op tallies | STILL OPEN (MED) | `renderFiles` `:2896-2917`: `created` shows `+ops`, otherwise `-ops` in brick. An edited file shows a brick "-3" that counts edit calls, not removed lines |
| Terminal ctx readout comma-grouped | CLOSED | `renderTerminalPanel` uses `fmtK` ("128k / 481k") |
| flag card stale "needs wiring" copy | CLOSED | `renderHeader` flag block: "No open flags on this session." |

`reports/drift2/spine-auggie.md`: CLOSED/SUPERSEDED. Auggie CLI todos carry real `started_at/ended_at` (time-proportional); Augment-ext keeps the honest equal-width fallback (`spineSegments` else-branch, `todo_times_approximate` hint in `renderSpine`). Nothing to change; the upstream data does not exist.

Analysis section A4 (Terminal controls permanently hidden): CLOSED (`registry.py:250`; panel `ext_cr_detail.js:3133`).

## 3. New drift

| # | doc section + line | doc says | code does | verdict | sev |
|---|---|---|---|---|---|
| N1 | Header row 2, L76 | h1 is the session summary's Goal, promoted; fallback to title | h1 always = session name (`ext_cr_detail.js:2486`); the line under it is the server `headline` (job summary or latest narration), 3-line clamp (`paintGoalLine` `:1242`). The summary Goal appears only inside the Summary panel (`:2852`). `reports/job-summary-header.md` rules the headline line, not the h1 | DRIFT | MED |
| N2 | Orb rail, L28-42 | brand mark 22px, divider, pin micro-label, pinned orbs, divider, unpinned orbs, agents orb, dashed "+" new-session orb, vertical mono "+14 SCROLL" | detail rail = `cr-rail--collapsed.cr-rail--detail` (`ext_cr_board.js` applyRailMode ~`:1139`); brand mark hidden (`ext_cr_board.css` ~`:1182`); no pin micro-label; divider only between pinned and unpinned (`:1856-1858`); NO agents orb; NO new-session orb; footer is a plain horizontal "+N" (`:1584`, css `:1134-1141`) | MISSING | MED |
| N3 | Orb, L46-50 | 34px; selected = agent gradient + `--glow-agent`, initials in text-thinking; pip 9px at top/right -1px | 28px (css `:1192-1207`, following doc 02:123, which conflicts with doc 03); selected = border + `--glow-agent-soft` only (`:1212`); pip 8px at bottom/right (`:1213-1221`) | DRIFT (docs 02 and 03 disagree on size) | LOW |
| N4 | Orb a11y, L52 | title + aria-label "<title> - <state word>" | `railOrb` sets both (`ext_cr_board.js:1900-1906`) | MATCH | - |
| N5 | Rail <1024, L54 | overlay drawer from the top bar | `ext_cr_board.js:1064-1070` | MATCH | - |
| N6 | Fork banner, L94-100 | full-width row between header and spine, margin `14px 26px 0`, left border 2px dusk, link "Open the original"; parent side links to the copy | small Evidence-column card; both directions and links exist (`:2572-2600`) but wrong place and wrong copy | DRIFT | HIGH |
| N7 | Command result entry, L255 | brick row: `fail`, command ellipsed, "2 of 14" | `fail` + command, no "N of M" (`entryHtml` `:3314-3322`) | DRIFT | LOW |
| N8 | Live entry, L259, L263 | pinned to the bottom of the timeline panel in the 2px agent-gradient frame | moved above the spine as `.crd-now` (skeleton `:1466`, css `:1567-1579`) | SUPERSEDED-BY-RULING (commit `89c2267` message: "THE NOW CARD MOVED ABOVE THE PROGRESS SPINE (owner's placement)") | - |
| N9 | Progress spine, L102-160 | the spine is THE progress UI | default is the Heartbeat panel; spine is behind `cr.progressView` (`:309-323`) and is a collapsible panel (skeleton `:1467-1493`) | SUPERSEDED-BY-RULING (`reports/heartbeat-panel.md` contract 2026-10-29) | - |
| N10 | Spine header, L110 | "PROGRESS SPINE", "7 of 11 . 41m elapsed", right hint | label + count + hint present (`renderSpine` `:2606+`) plus span chips All/15m/1h/6h/24h and drag-pan (`renderSpineSpans` `:2740`) | MATCH + EXTRA (chips ruled, `reports/spine-motion-vs-design-docs.md` s3) | - |
| N11 | Spine bar, L112-138 | 26px bar, time-proportional, 88% cap, 3% floor, "N earlier", running edge, RUNNING word | `spineSegments` `:552` (FLOOR 3, MAX_USED 88, GROUP_THRESHOLD 16); running label + edge in `renderSpine`; uppercase css `:675` | MATCH | - |
| N12 | Event gutter, L140-152 | 5 marker kinds, titles with timestamp, keep both on collision | `buildMarkers` `:692`, all five | MATCH (nudge: R1 7.6) | - |
| N13 | Footer + a11y, L154-160 | 3-part footer; `role="img"` + summary label | footer present; summary in `aria-live` sr span; role=group | SUPERSEDED-BY-RULING (spine-motion s4) | - |
| N14 | Stat chips, L78-84 | 7 chips; only `tests` changes colour; `--` / `N/A` | `--` used; `N/A` never emitted; row has 8 chips (extra `cost`, a button); hidden on phone except cost (css `:1894-1895`) | MATCH on the 7 | LOW |
| N15 | Actions, L86-92 | row 1 Search + Flag pills; row 2 Open terminal / Resume here / External; Search/Flag toggle a full-width card | cards exist (`:1432-1458`); layout is one row; at <=900px Search/Flag lose their words (css `:1848-1850`) | DRIFT | HIGH |
| N16 | Pinned pill, L76 | "Pinned" pill when pinned | always-rendered toggle button (`:1399`, `paintPinButton` `:1214`) | EXTRA (functional superset) | LOW |
| N17 | Columns, L162-168 | eyebrows; Expand/Collapse on State + Evidence only; Conversation head has marker + prev/next/latest | skeleton `:1497-1546` exactly | MATCH | - |
| N18 | Every panel, L170-180 | chevron/label/count; all collapsed except Timeline; persisted; count visible; tint survives | `makePanel` `:1292`, `panelDefaultCollapsed` `:326`, Decisions tint `:2776`, Commands count tint in `renderCommands` | MATCH | - |
| N19 | State column, L182-228 | Decisions, PRs, Links, Summary, Plan with listed copy | `STATE_PANELS` `:1554`; footer, "Decided earlier", Links two groups + footnote, Plan chips by `push_when` verbatim (`:2768-2893`) | MATCH (PR title: R2) | - |
| N20 | Conversation entries, L230-273 | 34px gutter; prompt right bubble 82%; plain narration; ask bubble; degraded hides filters; paging footer | css gutter/radii; `renderTimeline` degraded branch `:3221`; footer `:1670` | MATCH | - |
| N21 | Panel head, L242-245 | muted legend + all / talk only | see R1 6.2 | DRIFT | LOW |
| N22 | Evidence col, L275-285 | Files, Commands, Agents & shells, Run, Terminal; Terminal hidden when not attached | `EVIDENCE_PANELS` `:1561`; `display:none` when not attached (`:3135`) | MATCH (Files: R2) | - |
| N23 | Terminal controls, L285 | read-out chips | model/effort are working switchers, disabled without `term_tty` (`:3133-3186`) | EXTRA | LOW |
| N24 | Phone, L287-295 | detail screen pieces in order | all present (`:1120-1196`, `.crd-phonebar` css `:1698`); default progress panel on phone is the Heartbeat (ruled, N9) | MATCH / SUPERSEDED | - |
| N25 | Phone, L295 | all targets >= 44px | static read OK (css BLOCKER 2 block `:2145+`, cost chip `:1895`); not measured in a browser | MATCH (static) | - |

## 4. Extras (no source in the bundle)

| extra | where | ruled? |
|---|---|---|
| Agent map: header row-3 "Open agent map" button with count, "map" link on agent rows, "View in agent map" link, `agent_sessions` "Sessions" sub-list in Agents & shells | `ext_cr_detail.js:1403, 2982-3070`; dialog `ext_cr_dialogs.js:2513-2715`; tests `test_cr_agent_map_entry.py`, `test_cr_agent_map_ui.py` | unruled (commit `2c35a29`, no report in `reports/`) |
| Model marker chip beside the metaline; model chip on agent rows | `ext_cr_detail.js:1358, 2404-2410, 2992` (commit `031c50c`) | unruled (agent-row chip logged EXTRA LOW in round 2) |
| Cost chip (clickable) + cost modal | `ext_cr_detail.js:1058-1061` | ruled (`reports/job-summary-header.md`, owner ask at line 21) |
| Job-summary headline with band pill, 3-line clamp, click to expand | `paintGoalLine` `:1242` | ruled (`reports/job-summary-header.md`) |
| Heartbeat panel + `cr.progressView` switch | `ext_cr_detail.js:350-480, 2335` | ruled (`reports/heartbeat-panel.md`) |
| Spine zoom chips, drag-pan, shimmer/pulse motion | `:514-550, 2740` | ruled (`reports/spine-motion-vs-design-docs.md`) |
| Now card above the spine | `:1466` | ruled (commit `89c2267`) |
| Timeline per-kind filter chips + pop-out | `:1640-1662` | unruled (self-labelled "FIX defect 2/3") |
| Search / Flag / Queue-a-note header cards; clickable "N agents running" pill | `:1432-1459, 1370` | unruled |
| Rename-note nudge, parse-error notice, refreshing/snapshot label | `paintTitleNote` `:1256`; `renderParseErrorNotice` `:3208`; `renderUpdate` `:2258` | parse-error notice follows doc 04 (commit `7b87cce`); the rest unruled |
| Pin toggle always visible; Rename text button | `:1399` | unruled |
| Terminal model/effort switchers wired to `/api/term/inject` | `:3092-3131` | unruled |

## 5. Fixes for DRIFT / MISSING

Test home: new `tests/test_cr_detail_drift3.py` (stdlib unittest, static source assertions over `ext_cr_detail.{js,css}` in the style of `tests/test_cr_detail_action_row_responsive.py`), plus a browser check where noted. Each test must be proven red by reverting its fix.

**F1 (HIGH) Actions in two rows (1.5 / 1d / N15).** Direction: row 1 = Search pill + Flag pill; row 2 = Open terminal (solid), Resume here (outline), External (bare). Do NOT remove the Queue-a-note button without an owner call (keep it in row 2 after Resume); do NOT rename any `data-act` (handlers `:1873+` key off them). Way: in the skeleton (`:1377-1385`) split `.crd-row1-actions` into two rows inside one right-aligned column (`flex:0 0 auto; flex-direction:column; align-items:flex-end; gap:8px`); update `qsa(node, ".crd-row1-actions .crd-iconbtn .crd-ico")` in renderHeader (`:2510`) and the css at `:1819-1860`; keep Search/Flag words at all widths above 600px. Test: in the skeleton string, `toggle-search` and `toggle-flag` share a row element that excludes `open-terminal`.

**F2 (HIGH) Fork banner (1.8 / 1k / 1l / N6).** Direction: full-width row between header and progress panels; doc copy for the copy side, mirrored for the parent. Do NOT guess lineage (keep hidden when unknown). Way: add `<div class="crd-forkbanner" hidden>` to the skeleton after the header cards and before `.crd-now` (`:1466`); delete the `evidenceBody.appendChild(forkCard)` block (`~:1620-1634`); in `renderForkBanner` (`:2572`) set copy-side text to "Resume was refused - this session was running as a background agent, so it was forked. You're looking at the copy; the original is still running." with link "Open the original", and parent side "A fork of this session continued the work." with link "Open the copy"; css margin `14px 26px 0`, padding `11px 15px`, `--surface-provenance`, `1px solid --line-default`, `border-left: 2px solid` dusk, radius 4px. Test: skeleton order (forkbanner index < `crd-now` index) and the "Resume was refused" string.

**F3 (MED) Orb rail contents (N2 / N3).** Direction: in the detail view's 56px rail add the brand mark, a pin micro-label before the pinned group, an agents orb, a dashed "+" new-session orb, and the vertical "+N SCROLL" footer. Do NOT change the board's 48px collapsed rail (doc 02). Way: `renderCollapsedOrbs` (`ext_cr_board.js:1854`) appends the agents and "+" orbs only when `els.rail.classList.contains('cr-rail--detail')`; unhide `.cr-rail-brand` under `.cr-rail--detail` (css ~`:1182`); footer text `'+' + moreN + ' scroll'` with `writing-mode: vertical-rl` in the detail variant (`:1584`); selected orb gets `--surface-agent-active` + `--glow-agent`; pip 9px top/right -1px for the detail variant only. The 28 vs 34px conflict between docs 02 and 03 needs an owner call; recommend 34px in `--detail`, 28px on the board. Test: static greps for the agents/new orb classes inside the `--detail` branch; geometry is a browser check.

**F4 (MED) Goal in the h1 (N1).** Direction: h1 = `session.overview.goal`, fallback to the title; headline line stays under it. Do NOT remove the job-summary headline (ruled). Way: `renderHeader` line `:2486` becomes `(session.overview && session.overview.goal) || sessionName`; check that rename still reads `meta.title` (`ui.lastTitle`, `:2263`). Owner call first: a long prompt-goal at 29px serif may be unusable; if refused, record the deviation as a ruling. Test: static assert of the `overview.goal` fallback chain.

**F5 (MED) Timeline order (6.4 / 6g).** Direction: owner decision needed (no ruling found). If the doc wins: oldest at top, newest at bottom, stuck-to-latest = pinned to bottom, older turns page in at the top. Flip both sentinels together. Way: `mergeTimeline` sort ascending (`:768`), the scroll listener in `mount`, `scrollTimelineToTodo`, the `convo-prev/next/latest` cases (`:1991+`). If newest-first is kept, record the ruling in `reports/control-room-refinements.md`. Test: ordering assertion on `mergeTimeline` output via the node harness used in `tests/test_cr_logic.py`.

**F6 (MED) PR title (4.2).** Direction: capture a title only where the source text has one (`gh pr create --title`, MCP create-PR args); never fabricate. Way: `util.py collect_prs` (`:165`) takes an optional `title` and sets `e["title"]`; pass it from the `created=True` call sites in `providers/claude.py` and `providers/auggie.py`; `renderPRs` already prints `p.title`. Test: Python unit on `collect_prs` with a title, asserting `acc[url]["title"]`.

**F7 (LOW-MED) Files row (R2 files).** Direction: basename at weight 500; `+N` forest only for created files; for edits show a neutral "N edits", never a brick `-N` that is an edit-call count. Way: split `f.path` into dir + `.crd-file-base` spans in `renderFiles` (`:2896`); css `.crd-file-base { font-weight: 500 }`. Test: static assert that `.crd-file-base` exists and the `"−" + ops` expression is gone.

**F8 (LOW) Resume here (1.6 / 1f).** Change the label at `:1381`. Test: string present in the skeleton.

**F9 (LOW) Collision nudge (7.6).** In `buildMarkers` (`:732`) replace the +2 pct bump with a stored `nudgePx = 10` applied as `transform: translateX(10px)` in the gutter markup inside `renderSpine`. Test: static assert on `translateX`/`nudgePx`.

**F10 (LOW) Fail row "N of M" (N7).** In `mergeTimeline` compute `k of N` over failing commands and render it as `.crd-tool-count` in the `command-fail` branch (`:3314`). Do NOT invent per-test counts. Test: static assert.

**F11 (LOW) Metaline cwd (1.2).** Add a home-relative, middle-ellipsed cwd to `metaBits` (`:2404`). Test: static assert on `meta.cwd` inside `metaBits`.

**F12 (LOW) Phone spine labels (R2).** Move the hide rule at css `:2110-2113` into the `max-width: 600px` block. Test: css regex asserts `.crd-spine-hint` is hidden inside a 600px block.

**F13 (LOW) Timeline chips / pop-out (6.2).** Keep (functional superset) unless the owner wants strict doc parity; if so, hide `.crd-timeline-kinds` and `.crd-timeline-popout` behind a Config knob rather than deleting. Visual-only.

## 6. Top 5

1. Header actions are one row of six controls, not the doc's two rows, and Search/Flag lose their words at 900px or narrower (F1).
2. The fork banner is still a small card at the bottom of the Evidence column, with copy that omits "Resume was refused ... forked" (F2).
3. The detail view's 56px orb rail lacks the brand mark, pin label, agents orb, new-session orb and "+N SCROLL" footer; its orbs are 28px, not 34px (F3).
4. The timeline renders newest-first, inverting the chat metaphor the doc describes, and no owner ruling covers it (F5).
5. Files rows show edit-call tallies as brick "-N" with no basename emphasis, and PR rows have no title (F7, F6).

Counts (rough, rows grouped as in section 2): about 31 prior rows CLOSED, 17 STILL OPEN, 1 partial regression (Search/Flag words at <=900px), 4 SUPERSEDED-BY-RULING. New drift beyond section 2: HIGH 2 (N6, N15, both restatements of open items), MED 2 (N1, N2), LOW 4 (N3, N7, N21, plus the N14/N16/N23 notes); N8, N9, N13 are ruled.
