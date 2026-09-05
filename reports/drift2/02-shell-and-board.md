# Adversarial drift audit — 02-shell-and-board.md

Scope: `aitracker/web/ext_cr_board.js`, `ext_cr_board.css`, `ext_cr_boot.js`, `ext_cr_boot.css`, `index.html`.
Method: read the real code (not comments) for every claim; verified sort/cap/state derivations line-by-line against doc pseudocode.

| # | Doc section | Doc says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 1 | Opt-in entry, placement | Button lives "in the classic header, **after the 'N live' pill**" (inline, in `.sidetop2` beside `#livecount`) | `index.html:72` puts `#tryNext` as the **last child of `<header class=hd>`** (the main content header, not the sidebar); `ext_cr_boot.css:45-48` makes it `position:absolute; top:22px; right:28px` of that header — nowhere near `#livecount` (`index.html:26`, sidebar) | DRIFT | MED |
| 2 | Opt-in entry, copy | "✦ Try the new experience" | `index.html:72` — exact text | MATCH | — |
| 3 | Opt-in entry, styling | Classic-palette gradient/border/colour, literal not tokens | `ext_cr_boot.css:45-62` — byte-identical gradient/border/font/colour to the doc's CSS block | MATCH | — |
| 4 | Mode switching | `tracker.ui`='classic'\|'next', toggle `hidden`, **no reload** | `ext_cr_boot.js:216-247` `setUiMode()` — toggles `hidden`, no reload anywhere | MATCH | — |
| 5 | First-run panel | Verbatim heading/body/3 checks/2 buttons/footnote; shown once via `tracker.next.seen` | `ext_cr_boot.js:1035-1046` (copy, byte-identical) + `1058-1069` (`markSeen`/`seenFirstRun`, shown once) | MATCH | — |
| 6 | The way back | "‹ Classic dashboard" leftmost, `--text-link`, 600/11.5px, never hidden | `ext_cr_board.css:110-118` (`.cr-back` — exact colour/weight/size); `ext_cr_board.js:1262-1266`. Placed **after** the rail toggle, per doc's own separate note ("a rail toggle sits at the very left... before the back button") — reconciles the doc's own numbered-list vs. prose contradiction correctly | MATCH | — |
| 7 | App shell | Root `flex`, `--surface-page`, `overflow:hidden`; right col `flex:1`; `min-width:0` on text-bearing flex children | `ext_cr_board.css:38-44` (`.cr-app`), `:47-53` (`.cr-main`), `:60-68` (`.cr-content`) — all present; spot-checked `min-width:0` on `.cr-tile-state/.cr-tile-title/.cr-rail-title/.cr-main/.cr-content` | MATCH | — |
| 8 | Breakpoints | 1024–1279px: 2 cols, 56px collapsed rail; <1024: 1 col, rail hidden/overlay | Board grid uses `max-width:1279`→2col, `max-width:1024`→1col (`ext_cr_board.css:826-831`); rail overlay uses `max-width:1024` (`:668, :783`). At **exactly 1024px** the doc's own table places it in the "1024–1279" tier (2 col, collapsed rail in-flow); the code's `<=1024` boundary (deliberately, per its own "BLOCKER 4" comments) puts 1024px in the "<1024" tier instead (1 col, hidden overlay rail) | DRIFT | LOW |
| 9 | Session rail / Breakpoints, collapsed width | Doc 02's own two tables disagree: "Rail" table (§Session rail) says collapsed=**48px**; breakpoint table (§App shell) says the 1024–1279 tier collapses to **56px**. README decisions #1 (detail=56px) vs #6 (rail=48px) carry the same split | `ext_cr_board.css:379` (`.cr-rail--collapsed{width:48px}`, used for the board's own auto-collapse at 1025-1279px) vs `:386` (`.cr-rail--detail{width:56px}`, used only when `currentView==='detail'`, `ext_cr_board.js:744-769`) — resolves the doc's internal contradiction by following the more specific README decisions rather than 02's breakpoint-table number | MATCH (doc self-contradiction, reconciled correctly) | LOW (informational) |
| 10 | Top bar order | 1 rail-toggle¹ → back → divider → pills → auto-spacer → 🚩 → 🔔 → Config → Help → theme → New session (¹stated separately as "very left, before back") | `ext_cr_board.js:1242-1330` `buildTopBar()` — builds in exactly this order | MATCH | — |
| 11 | Top bar, destination pills | Only **Board** and **Terminals** (`"3 of 12"` live count) | `ext_cr_board.js:1278-1291` adds an undocumented third **"Sessions"** pill/view (`openSessionsDestination`, full browse+search+pagination UI) — not in README, not in doc 02, not in the task's settled-decisions allowlist | EXTRA | MED |
| 12 | Top bar, Terminals live count | Format `"3 of 12"` | `ext_cr_board.js:1946-1949` → `tc.open + ' of ' + tc.total` | MATCH | — |
| 13 | Icon-only controls | `title` **and** `aria-label`, same string | Bell/Config/Help/rail-toggle/back all set both, identical strings (`ext_cr_board.js:1242-1318`) | MATCH | — |
| 14 | Icon-only controls (cont.) | Same rule | "New session" collapses to **icon-only** at ≤480px (`ext_cr_board.css:359` hides its `.cr-topbar-label`) but the button (`ext_cr_board.js:1326-1330`) sets only `aria-label`, no `title` | MISSING | LOW |
| 15 | Session rail, collapsible | Open by default; two affordances (top-bar 28px `panel` button + rail chevron) toggle the same state | `ext_cr_board.js:414` (`railMode` default `'auto'`≈open), `:641-654` chevron, `:1242-1247` top-bar toggle, both call `toggleRail()` | MATCH | — |
| 16 | Rail ordering | `railOrder()` pseudocode verbatim | `ext_cr_board.js:71-76` — byte-identical logic | MATCH | — |
| 17 | Rail rows | 8px/9px padding, gap 8px, 7px dot, 12px ellipsed title, selected = raised+line-agent+glow, hover = fill-row-hover | `ext_cr_board.css:516-539,554-561` — all values match | MATCH | — |
| 18 | Rail group headers | `"📌 Pinned — N · newest first"` / `"Sessions — N · newest first"` | `ext_cr_board.js:863-864, 876-877` — verbatim | MATCH | — |
| 19 | Rail footer | Sticky "scroll · N more" | `ext_cr_board.css:589-599` (`position:sticky;bottom:0`), `ext_cr_board.js:933` | MATCH | — |
| 20 | Triage strip | 4 cells, order Waiting/Working/Flagged/histogram; each count a toggle-filter with underline in its own colour; 33px counts (recently changed) | `ext_cr_board.js:1414-1416` cell order; `ext_cr_board.css:750-752` active-filter border-bottom in state colour; `:757-763` **33px**, confirmed landed (not the old 31px) | MATCH | — |
| 21 | Histogram | 18 bars, 30px height, 2px gap, role=img + summary aria-label | `ext_cr_board.js:286` (`BINS=18`), `ext_cr_board.css:783-788` (`height:30px;gap:2px`), `ext_cr_board.js:1420,1481` aria-label | MATCH | — |
| 22 | Board grid | 3 cols, gap 13px, padding 16px 22px 12px | `ext_cr_board.css:819-825` — exact | MATCH | — |
| 23 | Sort comparator | `RANK` → pinned → recency, verbatim | `ext_cr_board.js:32` (RANK, `failing` inserted per settled 6-state vocabulary), `:249-253` — logic identical to doc pseudocode | MATCH | — |
| 24 | Cap | Hard cap (settled: 3–12, default 8) | `ext_cr_board.js:194-199,255` — landed correctly, not reported per task instructions | MATCH | — |
| 25 | Idle sessions | Never tiled | `ext_cr_board.js:248` `.filter(state!=='idle')` | MATCH | — |
| 26 | Hero / agent-group | Highest-ranked awaiting spans 2 cols + accent frame; agent groups span 2 cols, sit last | `ext_cr_board.js:256-258` hero flag; `ext_cr_board.css:869-874` gradient frame; groups appended after individual (`:254-255`), CSS `grid-column:span 2` (`:845-846`) | MATCH | — |
| 27 | Tile anatomy | emoji+state+pin, trailing age·tool, title, **project·tool sub-line (recently made universal)**, one live/flag/summary line, todo ticks — order and fields | `ext_cr_board.js:1731-1746` — confirmed **every** tile (not hero-only) gets `.cr-tile-sub`; border+glow on **every** working tile unconditional (`ext_cr_board.css:855-859`, no `s.bg>0` gate) — both "recently changed" items landed correctly | MATCH | — |
| 28 | Todo ticks | 4×14px, gap 2px, radius 2px, done/current/pending colours, "N of M" mono caption, aria-label | `ext_cr_board.css:1035-1050`, `ext_cr_board.js:1571-1603` | MATCH | — |
| 29 | Cap footer | "N of M — never more than {cap} tiles... — Scroll for the rest" (mono count, click focuses rail) | `ext_cr_board.js:1799-1812` | MATCH | — |
| 30 | Keyboard | ⌘K/Ctrl+K, j/k, Enter, Esc, t, ?; focus/scroll preserved across 2s re-render | `ext_cr_board.js:1843-1883` all bound; `renderBoard`/`renderRail` explicitly snapshot/restore `scrollTop` and refocus (`:1509,1524,915,935`) | MATCH | — |
| 31 | Liveness | `LIVE_WINDOW` (config, 300 default) == `LIVE` (client, 300) | `config.py:354` (`resolve_live_window` → 300 default) == `web/app.js:828` (`const LIVE=300`) == `ext_cr_board.js:23` (`LIVE_WINDOW` derived from the real `LIVE` global, not re-declared) | MATCH | — |
| 32 | Empty/error states | Not specified by doc 02 (owned by doc 04, out of this audit's scope) | `ext_cr_board.js:1512-1514` shows an honest placeholder | N/A | — |

## Totals

- MATCH: 25
- DRIFT: 2 (placement of entry button — MED; 1024px breakpoint boundary — LOW)
- EXTRA: 1 (undocumented "Sessions" destination pill/view — MED)
- MISSING: 1 (New session button's `title` attribute at icon-only phone width — LOW)
- N/A: 1 (out-of-scope doc territory) — informational note: 1 (doc self-contradiction, correctly reconciled)

Nothing in the recently-changed list (working-tile border/glow, universal "project · tool" sub-line, 31→33px triage counts, cap 8→12) is broken — all four verified landed correctly by reading the real CSS/JS, not comments.

## Fix list

1. Move `#tryNext` into the sidebar's `.sidetop2` row, immediately after `#livecount`, and drop the `position:absolute` hack in `ext_cr_boot.css:45-48` — match doc's literal placement "after the N live pill."
2. In `ext_cr_board.js`'s `applyRailMode()`/`bindResize()`/CSS media queries, either move the compact-tier boundary back to `<1024` (not `<=1024`) so 1024px itself gets the "1024–1279" 2-col/56px-collapsed treatment doc's table specifies, or explicitly document the deliberate 1px shift as a ruling (like the cap-ceiling exception) so it stops reading as an oversight.
3. Remove the undocumented "Sessions" destination pill (`ext_cr_board.js:1282-1291,1095-1105` `openSessionsDestination`/`els.pillSessions`) or get it added to the settled-decisions allowlist — doc 02 names only Board and Terminals.
4. Add `title: 'New session'` alongside the existing `aria-label` on the New-session button (`ext_cr_board.js:1326-1330`) so it satisfies "icon-only controls need title and aria-label" once its label hides at ≤480px.
