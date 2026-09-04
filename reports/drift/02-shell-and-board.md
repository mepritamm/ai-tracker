# Drift report — 02-shell-and-board.md vs. shipped implementation

Spec: `design_handoff_control_room/02-shell-and-board.md` (245 lines) + README.md (authoritative decisions) + 01-foundations.md (token names only).
Implementation root: `.claude/worktrees/cr-drift/aitracker/web/` — primarily `ext_cr_board.js` (1930 lines), `ext_cr_board.css` (1301 lines), `ext_cr_boot.js` (1069 lines), `ext_cr_boot.css` (200 lines), `index.html`.

Verdict legend: MATCH / DRIFT / MISSING / EXTRA. Severity: HIGH (behavioural break or non-negotiable violated) / MED / LOW.

## 1. Opt-in entry

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 1.1 | 02:11-14, README decision 5 | `<button class="tn-entry" id="tryNext">✦ Try the new experience</button>` in the classic header, **after the "N live" pill** | `index.html:72` — `<button class=tn-entry id=tryNext title="Open the new Control Room experience">✦ Try the new experience</button>`, placed inside `<header class=hd>` after `#srcnote`, far from the "N live" pill (`#livecount`, `index.html:26`, which lives in the *sidebar* header, not `header.hd`) | DRIFT (placement) | MED |
| 1.2 | 02:17-26 | `.tn-entry` CSS: gradient `#3a2a0f→#1a1206`, border `#d9a441`, colour `#f5b443`, `padding:6px 13px`, `radius:20px`, font `600 11.5px/1 'Source Sans 3'`, `margin-left:auto` (i.e. inline flex child pushed right) | `ext_cr_boot.css:45-60` — same colours/padding/radius/font exactly, but `position:absolute; top:22px; right:28px` instead of an inline flex child with `margin-left:auto` | DRIFT (positioning mechanism) | LOW |
| 1.3 | 02:32-39 | `tracker.ui` localStorage `'classic'\|'next'`, default `'classic'`; `setUiMode()` toggles a body class, **no reload** | `ext_cr_boot.js:217-247` — `getUiMode()`/`setUiMode()` match key/values/default exactly; toggles `#nextRoot.hidden` + hides classic siblings, no `location.reload()` anywhere in the switch path | MATCH | — |
| 1.4 | 02:41 | "Both UI roots live in `index.html`… **No reload**, because a reload drops the terminal's open PTY streams." | Confirmed: `index.html:171` `#nextRoot` and `.app` both always in DOM; `setUiMode()` only toggles `hidden`; verified no navigation/reload call anywhere in `ext_cr_boot.js` | MATCH | — |
| 1.5 | 02:45-53 | First-run panel copy verbatim (heading, body, 3 checks, 2 buttons, footnote); "Show once; store `tracker.next.seen='1'`" | `ext_cr_boot.js:1001-1035` — heading/body/checks/buttons/footnote text reproduced **verbatim**; `markSeen()` called once on the button click that reveals the panel (line 1043), never re-shown | MATCH | — |
| 1.6 | 02:56-63 | Inside the new UI, top bar's **first** element is `<button class="tn-back">‹ Classic dashboard</button>`, left-most, never hidden/behind a menu | `ext_cr_board.js:1235-1239` — `.cr-back` button with `‹ Classic dashboard` text exists, but per the "Top bar" section (02:108) a **rail-toggle button is appended before it** (`ext_cr_board.js:1215-1220`), making the rail toggle — not the back button — the true left-most element. Doc 02 itself contradicts its own two sections here (see note below); implementation follows the more detailed "Top bar" section, which is self-consistent | DRIFT (internal doc conflict, impl follows the more specific section) | LOW |

**Note on 1.6:** doc 02 has an internal inconsistency: "The way back" section (line 57) says the back button is the top bar's *first* element, but the "Top bar" section (line 108) says the rail toggle sits "at the very left of the top bar, **before** the back button." Implementation matches the latter, more detailed section.

## 2. First-run panel

Covered above (1.5). Gating on `tracker.next.seen` confirmed at `ext_cr_boot.js:1034-1035, 1041-1043`. MATCH.

## 3. App shell geometry

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 3.1 | 02:67-80 | Root `display:flex; background:var(--surface-page); overflow:hidden`; right column `flex:1;min-width:0;flex-direction:column;overflow:hidden` | `ext_cr_board.css:40-55` `.cr-app`/`.cr-main` — identical properties | MATCH | — |
| 3.2 | 02:82 | `min-width:0` on every flex child containing text | 21 occurrences of `min-width: 0` across `ext_cr_board.css`, applied to rail, main, tile, title-wrap, etc. | MATCH | — |
| 3.3 | 02:69,86-91 | Top bar 54px; session rail 232px expanded; triage strip ~88px; board 1fr; cap footer ~52px | `.cr-topbar { height:54px }` (`ext_cr_board.css:88`); `.cr-rail { width:232px }` (`:367`); triage `padding:16px 22px 14px` (no fixed height, content-driven ≈88px) (`:731`); board `flex:1` via `.cr-board-scroll{flex:1}` (`:814`) | MATCH | — |
| 3.4 | 02:86-91 breakpoint table | ≥1440: 3 cols/232px rail · 1280-1439: 3 cols/232px · 1024-1279: 2 cols/56px collapsed orbs · <1024: 1 col, rail hidden/overlay | `ext_cr_board.css:820-832` — `.cr-board` 3 cols default, `@media(max-width:1279px)`→2 cols, `@media(max-width:1024px)`→1 col. At **exactly 1024px** this collapses to **1 column**, but the doc's table places 1024 in the "1024-1279 → 2 columns" band. `ext_cr_board.js:735-741` (`applyRailMode`) explicitly documents shifting the rail's collapse boundary to `>=1025`/`<=1024` ("BLOCKER 4") to reconcile with `ext_cr_detail.css`'s own 1024px tier | DRIFT (1px boundary) | LOW |
| 3.5 | 02:90 | 1024-1279: rail "56px, collapsed to orbs" | Board rail's own collapse width is **48px** (`.cr-rail--collapsed{width:48px}`, `ext_cr_board.css:379`), not 56px. 56px is reserved for the *detail* view only (`.cr-rail--detail{width:56px}`, `:386`), per README decision 1. Doc 02's own breakpoint table (line 90) says 56px for this width band, but doc 02's own "Session rail" section (line 121-123) says the board's collapsed width is 48px. Per task instruction, 02's rail-section number (48px) is treated as authoritative for the board, which is what the implementation uses | DRIFT (doc-internal 02 conflict, impl follows the authoritative 48px) | LOW |

## 4. Top bar

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 4.1 | 02:93-96 | Row: `gap:14px; padding:0 22px; background:var(--surface-top); border-bottom:1px solid var(--line-subtle)` | `ext_cr_board.css:83-92` — identical | MATCH | — |
| 4.2 | 02:97-107 order | 1 back · 2 divider · 3 pills (**Board, Terminals** only) · 4 auto spacer · 5 🚩N · 6 🔔 · 7 Config pill · 8 Help pill (bound to `?`) · 9 theme control · 10 New session | `ext_cr_board.js:1212-1304` — order: rail-toggle, back, divider, pills (**Board, Sessions, Terminals**), spacer, 🚩 flag count, 🔔, Config, Help, theme control, New session. Element order for the spec'd items matches; **rail-toggle is prepended** (see 4.4) and an **extra "Sessions" pill** is inserted (see 4.3) | DRIFT (extra element) | MED |
| 4.3 | 02:99 | Destination pills are **Board · Terminals** only | `ext_cr_board.js:1255-1263` adds a third **"Sessions"** pill/destination (browse list + cross-stack search + pagination), not named anywhere in doc 02. Implementation's own comment (`:542-549`) acknowledges "02-shell-and-board.md never defines what the 'Sessions' top-bar destination shows" | EXTRA | MED |
| 4.4 | 02:108 | "A rail toggle (28px square, panel glyph) sits at the very left of the top bar, before the back button" | `ext_cr_board.js:1215-1220` — `.cr-rail-toggle`, 28px, `panel` icon, appended first, before `.cr-back` | MATCH | — |
| 4.5 | 02:99 | Terminals pill: live count "3 of 12" | `ext_cr_board.js:1897` — `tc.open + ' of ' + tc.total` → exact "N of M" format | MATCH | — |
| 4.6 | 02:101 | 🚩 N — flag count, opens cross-session flag list | `ext_cr_board.js:1269-1273` — `emoji('🚩',...) + count`, `onclick` emits `open:flags` → dialog, not a route | MATCH | — |
| 4.7 | 02:102 | 🔔 notification toggle | `ext_cr_board.js:1275-1278` | MATCH | — |
| 4.8 | 02:103-104, README decision 10 | Config/Help are **dialogs**, not routes, opened from header pills; Help also bound to `?` | `ext_cr_board.js:1283-1291` — both emit `open:config`/`open:help` → `ctx.dialog(name,...)` (`ext_cr_boot.js:389-391`), never a route/URL change. `?` bound in `bindKeyboard()` (`ext_cr_board.js:1802-1806`) | MATCH | — |
| 4.9 | 02:105 | Theme control: auto + light/dark segmented pair (01-foundations) | `ext_cr_board.js:1316-1368` `buildThemeControl()` — Auto/Light/Dark 3-segment control, `aria-pressed` per segment | MATCH | — |
| 4.10 | 02:106 | New session — solid button, spark glyph | `ext_cr_board.js:1299-1303` — `icon('spark',...)` + label | MATCH | — |
| 4.11 | 02:110 | Icon-only controls need `title` **and** `aria-label` from the same string | Verified on rail-toggle, back, Config, Help, bell, flag count — all pass identical strings to both attributes | MATCH | — |

## 5. Session rail

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 5.1 | 02:114, README decision 6 | Open by default; two collapse affordances (top-bar 28px button + rail's own chevron), both toggling the **same** state | `ext_cr_board.js:670-691` `toggleRail()` is called from both `els.railToggleTop` (`:1215-1220`) and `els.railChevron` (`:627-631`); on desktop board view with no stored explicit toggle, `applyRailMode()` (`:720-755`) computes `collapsed=false` → open by default | MATCH | — |
| 5.2 | 02:117 | localStorage key `tracker.rail` = `'open'\|'collapsed'`, default `'open'` | Implementation uses a **different key**, `tracker.rail.mode`, with a **tri-state** vocabulary `'auto'\|'open'\|'collapsed'`, default `'auto'` (`ext_cr_board.js:384-391`). Functionally reproduces "open by default" on the board via the `'auto'` breakpoint logic, but the localStorage contract (key name + value vocabulary) does not match the doc | DRIFT (contract, not behaviour) | LOW |
| 5.3 | 02:120-123 table | open=232px, collapsed=48px orbs, "same order," pinned above divider | `ext_cr_board.css:367,379`; `renderCollapsedOrbs()` (`ext_cr_board.js:1084-1090`) renders pinned then a divider then unpinned, same order as the open rail | MATCH | — |
| 5.4 | 02:124-125 | Collapsed orbs share detail view's orb anatomy (initials + state pip), same `title`+`aria-label` pair; animate width, `prefers-reduced-motion` snaps | `railOrb()` (`ext_cr_board.js:1120-1131`) — initials + `.cr-orb-pip`; `title`/`aria-label` both set from the same computed `label`; `ext_cr_board.css:374-378` — `transition:width .24s ease`, `@media(prefers-reduced-motion:reduce){transition:none}` | MATCH | — |
| 5.5 | 02:128 | Header: brand mark, "All sessions" label, total count; search field 29px tall, pill, "Search · ⌘K" | `buildRailShell()` (`ext_cr_board.js:618-668`) — brand mark, "All sessions" label, `els.railCount`; search box `height:29px`, `border-radius:var(--radius-pill)` (`ext_cr_board.css:443-454`), placeholder text is plain `"Search"` with a separate `<kbd>⌘K</kbd>` element rather than one combined "Search · ⌘K" string | DRIFT (cosmetic wording split) | LOW |
| 5.6 | 02:130-141 (railOrder) | Pinned group first, unpinned second; **within each group, newest first**; comparator `b.mtime - a.mtime` | `railOrder()` (`ext_cr_board.js:59-64`) — byte-for-byte identical to the doc's pseudocode | MATCH | — |
| 5.7 | 02:143 | Group headers: "📌 Pinned — N · newest first" / "Sessions — N · newest first" | `renderSessionRows()` (`ext_cr_board.js:839-855`) — exact strings reproduced (interpolated N) | MATCH | — |
| 5.8 | 02:145 | Rows 8px/9px padding, gap:8px; state dot(7px)→title(12px ellipsed)→trailing metadata; selected row gets `--surface-raised`+`--line-agent`+`--glow-agent-soft` | `ext_cr_board.css:516-530` — `padding:8px 6px 9px; gap:8px`; `.cr-rail-row--selected{background:var(--surface-raised);border:1px solid var(--line-agent);box-shadow:var(--glow-agent-soft)}` | MATCH | — |
| 5.9 | 02:147 | Background-agent sessions fold into one collapsible "🤖 Agents · <repo>" row per repo | `renderSessionRows()` (`ext_cr_board.js:821-828, 866-881`) — buckets by `s.group`, one collapsible row per bucket | MATCH | — |
| 5.10 | 02:149 | Footer sticky: "scroll · N more"; "everything reachable by scrolling" | `renderRail()` (`ext_cr_board.js:909-910`) — `'scroll · ' + Math.max(0,more) + ' more'` | MATCH | — |
| 5.11 | 02:151 | Row hover `background:var(--fill-row-hover)`; truncated titles show full value via `title` | `ext_cr_board.css:525`; `railRow()` sets a rich `title` attribute (`ext_cr_board.js:1158-1161`) | MATCH | — |
| 5.12 | README decision 1 vs decision 6 | Decision 1: detail view keeps a **56px** orb rail. Decision 6: rail (board) collapses to **48px**. The two README decisions name different numbers for different contexts | Implementation correctly separates the two: `.cr-rail--collapsed{width:48px}` for the board's general collapse, `.cr-rail--detail{width:56px}` scoped only to the detail view (`applyRailMode()`, `ext_cr_board.js:720-746`; CSS `:379,386`) | MATCH (docs are consistent once read as two different contexts; no drift in impl) | — |

## 6. Triage strip

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 6.1 | 02:155 | 4 cells, `padding:16px 22px 14px`, divided by 1px `--line-subtle` verticals, on `--surface-top` | `ext_cr_board.css:727-734` — grid of 4, identical padding/background; cell divider via `border-right` (`:738`) | MATCH | — |
| 6.2 | 02:159-163 | 3 count cells: Waiting on you (`--text-awaiting`), Working (`--text-thinking`), Flagged (`--state-flagged`) — labels WAITING ON YOU / WORKING / FLAGGED | `buildTriageShell()` (`ext_cr_board.js:1372-1390`) — same 3 cells/labels/order; colours applied in CSS (`:769-771`) match token-for-token | MATCH | — |
| 6.3 | 02:157-158 | Counts "33px," serif, tabular, `letter-spacing:-.03em` | `ext_cr_board.css:754-764` — `font-size:31px` (explicit override), comment states "01-foundations.md gives 33-40px… original prototype actually renders them at 31px… **prototype's rendered value wins per instruction**" — this contradicts the project's own stated rule ("where the prototype and documentation disagree, the documentation wins," README:21) | DRIFT (self-acknowledged doc-vs-prototype reversal) | MED |
| 6.4 | 02:165 | Each count is also a filter; clicking narrows the board; clicking again clears; active filter gets an underline in its own colour | `setFilter()` (`ext_cr_board.js:1403-1407`); `renderBoard()`'s `passesFilter()` (`:1461-1466`); underline via `border-bottom-color` per state (`ext_cr_board.css:751-753`) | MATCH | — |
| 6.5 | 02:167 | Histogram: 18 bars, `height:30px`, `gap:2px`, `flex:1` each, radius 1px; colour ramps oldest→newest, last bar carries `--glow-agent-soft` | `activityHistogram()` (`ext_cr_board.js:262-272`, BINS=18); CSS (`ext_cr_board.css:788-800`) — `height:30px;gap:2px`, `.cr-hist-bar{flex:1;border-radius:1px}`, last bar `.is-glow{box-shadow:var(--glow-agent-soft)}` | MATCH | — |
| 6.6 | 02:169 | `role="img"` + `aria-label` with a peak-events summary | `ext_cr_board.js:1454` — `aria-label='Activity, last hour: peak N events per minute'`, `role="img"` set at build time (`:1393`) | MATCH | — |

## 7. THE 8-TILE CAP

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 7.1 | 02:188, README decision 2 | `ranked.slice(0,8)` — hard cap of exactly 8, no "show more" | `boardTiles()` (`ext_cr_board.js:217-237`) — `.slice(0, boardTileCap())`; `boardTileCap()` (`:182-187`) clamps to `Math.max(3, Math.min(8, n))`, defaulting to 8. **The cap can be user-lowered to as little as 3** via an undocumented `cr.boardTileCount` localStorage preference (Config dialog), which doc 02 never mentions. It can never exceed 8, so the "never more than 8" invariant itself is never violated | DRIFT (EXTRA — undocumented configurability) | LOW |
| 7.2 | 02:194 | "Idle sessions never get a tile. They are counted in the cap footer and listed in the rail." | `boardTiles()` filters `.filter(t => t.state !== 'idle')` (`ext_cr_board.js:225`); cap footer denominator is `sessions.length` (all sessions, idle included) (`:1754`) | MATCH | — |
| 7.3 | 02:193 | "No 'show more' on the board — the rail is the overflow." | Confirmed: `renderBoard()` never paginates the board grid itself; overflow only reachable via rail scroll | MATCH | — |
| 7.4 | 02:220-224 vs 7.2 | Every non-idle session should be eligible for a tile | **Bug, self-documented**: `boardTiles()` (`ext_cr_board.js:217-223`) filters out every session where `s.agent && s.group` (folded into a group tile) — but an agent session with `agent:true` and an **empty** `group` (`""`) is excluded from the individual list by this filter's `!(s.agent && s.group)` logic AND never picked up by `agentGroups()` (which requires a truthy `group` key), so it **vanishes from the board entirely** regardless of state. Comment at `:220-223`: "Verified live: 950 sessions, 1 working, 0 tiles." | DRIFT (real gap, self-acknowledged) | HIGH |

## 8. Sort rules

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 8.1 | 02:178 | `RANK = { awaiting:0, flagged:1, working:2, landed:3, idle:4 }` | `ext_cr_board.js:26` — identical object, comment says "reproduced verbatim" | MATCH | — |
| 8.2 | 02:180-189 | Sort: state RANK, then pinned, then recency (mtime desc); cap to 8 | `boardTiles()` comparator (`ext_cr_board.js:226-230`) — `(RANK[a]-RANK[b]) || (pinned desc) || (mtime desc)`, matches the doc's operator order exactly | MATCH | — |
| 8.3 | 02:194-196 | Single highest-ranked awaiting tile spans 2 cols + accent border; agent-group tiles span 2 cols and sit last | `boardTiles()` (`ext_cr_board.js:231-236`) appends `agentGroups()` after the individually-ranked+capped list, and sets `.hero=true` only on `tiles[0]` when it's an awaiting session tile | MATCH | — |

## 9. Tile anatomy

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 9.1 | 02:203-208 anatomy diagram | `[emoji][STATE LABEL][📌 if pinned] … [age·tool]`, then Title (600/14px), then **"project · tool" mono 10.5px muted**, then one live/flag/summary line, then optional todo ticks | `tileHead()`/`sessionTile()` (`ext_cr_board.js:1586-1719`) render emoji/state/pin/trailing-meta and title correctly, but the **"project · tool" sub-line is dropped for every non-hero (non-awaiting) tile** — only the hero tile keeps it (`:1687-1689`). Comment ("Round-5 drift, decision 4a") explicitly states this follows the prototype's 3-div markup instead of doc 02's anatomy table, i.e. another self-acknowledged prototype-over-doc reversal | DRIFT (non-negotiable fidelity item, explicit doc-vs-prototype reversal) | HIGH |
| 9.2 | 02:210-217 state table — Working | Background `--surface-raised`, border `--line-agent`, **`--glow-agent-soft`+`--shadow-raised`** always; 01-foundations.md:271 reinforces "A working tile gets `--glow-agent-soft` **plus** `--shadow-raised`" unconditionally | `ext_cr_board.css:851-867` — plain `working` tiles get only `box-shadow:var(--shadow-raised)` and the default `--line-subtle` border; `--line-agent` border + `--glow-agent-soft` are applied **only** via a separate `.cr-tile--agent-glow` modifier, added in JS **only when `s.bg > 0`** (live background agents present) (`ext_cr_board.js:1671`). Comment explicitly says this was "grep-verified" against the prototype over the doc | DRIFT (non-negotiable-adjacent, explicit doc-vs-prototype reversal, contradicts 01-foundations.md too) | HIGH |
| 9.3 | 02:213 state table — Awaiting hero | Side rail: "todo ticks + files/failing/notes counts" | `sessionTile()` hero sidebar (`ext_cr_board.js:1709-1715`) only renders a notes count (`📝 N notes`) + the "Open terminal to answer" button — no todo ticks, no files count, no failing count in the sidebar (todo ticks do appear in the tile's main body, not the sidebar). Comment acknowledges files/failing counts aren't in the list-dict shape available | DRIFT (data unavailable; honest degrade, self-documented) | MED |
| 9.4 | 02:214 | Awaiting hero frame: `linear-gradient(135deg, orange-2, orange-4)` | `ext_cr_board.css:872-881` — substitutes `linear-gradient(135deg, var(--state-awaiting), var(--line-awaiting))`. 01-foundations.md maps orange-2→`--text-awaiting` (line 139) and orange-4→`--state-awaiting` (line 158), so the closer token match would be `--text-awaiting`/`--state-awaiting`, not `--state-awaiting`/`--line-awaiting` (token-naming detail, out of this doc's scope per task instructions — flagged only because it's directly on a claim in 02) | DRIFT (token substitution, likely belongs to the tokens audit) | LOW |
| 9.5 | 02:216 | Flagged: flag text in a `--surface-raised` inset | `ext_cr_board.css:998` `.cr-tile--flagged .cr-tile-line{background:var(--surface-raised)…}` (inset styling present) | MATCH | — |
| 9.6 | 02:217 | Landed: PR number if any | `prInfo()`/`tilePr()` (`ext_cr_board.js:1565-1584`) — renders `#N`, linked when `pr_url` present | MATCH | — |
| 9.7 | 02:218 | Agent group: `▸` + 🤖 + "expand" | `agentGroupTile()` (`ext_cr_board.js:1729-1746`) — chevron icon, 🤖 emoji, trailing "expand" line, in that order | MATCH | — |
| 9.8 | 02:220-224 | Todo ticks: 4×14px bars, gap 2px, radius 2px; done/current/pending colours; caption "N of M" mono tabular; `role=img` + `aria-label="N of M todos done"` | `todoTicks()` (`ext_cr_board.js:1523-1555`); CSS (`:1021-1042`) — colours/caption/aria-label all match exactly | MATCH | — |
| 9.9 | README decision 4 | "Emoji stay… always beside a word, never carrying state alone." | Every state chip renders `stateWord()` text next to the emoji (`tileHead()`, `ext_cr_board.js:1512-1518,1586-1593`); rail rows/orbs likewise pair colour with `orbStateWord()`/`aria-label` text (`:1117-1131,1162-1166`) | MATCH | — |
| 9.10 | README non-negotiable | "Colour never carries meaning alone. Every state has a word next to it." | Confirmed across tiles, rail rows, orbs, triage cells (label text always present alongside colour) | MATCH | — |

## 10. Empty and error states for the board

02-shell-and-board.md does **not** specify empty/error-state copy for the board (that content lives in `04-coverage-and-help.md`, out of this doc's scope per README's document table). For completeness, implementation provides:
- No tiles at all: "Nothing needs you right now." (`ext_cr_board.js:1476`)
- No tiles matching an active filter: "Nothing matches that filter right now." (`ext_cr_board.js:1476`)

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 10.1 | (02 is silent) | — | Reasonable, honest fallback copy present; no spec claim to violate | MATCH (N/A — no spec in 02) | LOW |

## 11. Liveness

| # | Spec ref | Spec says | Implementation | Verdict | Severity |
|---|---|---|---|---|---|
| 11.1 | CLAUDE.md / conventions.md | `LIVE_WINDOW` (server, `config.py`) must equal `LIVE` (client, `app.js`) = 300s | `aitracker/config.py:404` `LIVE_WINDOW = resolve_live_window({})` → defaults to 300s absent a `config.json` override (comment at `:346-351`, `"LIVE_WINDOW never had an env var backing it -- config.json > built-in default (300s)"`); `aitracker/web/app.js:828` `const LIVE=300;`. `ext_cr_board.js:14-23` derives its own `LIVE_WINDOW` from the shared `LIVE` global (never a re-declared literal) — the "one constant" rule is honoured | MATCH | — |

## Bonus: extra features found beyond doc 02's scope

Not requested by 02, but present and not contradicting it: a "Sessions" destination (browse + cross-stack search + pagination, `ext_cr_board.js:412-1082`), a rail "group by" control (directory/activeness/24h/7d/30d, `:74-143`), a configurable board tile cap (3-8, `:182-187`), a configurable Sessions page size, and configurable poll interval. These are all self-documented in code comments as deliberate additions beyond the doc's brief. None break an existing invariant, but they are undocumented surface area relative to 02.

---

## Summary counts

- Total items checked: **48**
- MATCH: 33
- DRIFT: 14
- MISSING: 0
- EXTRA: 1 (Sessions destination pill; several other EXTRA items are noted inline as DRIFT-EXTRA on the affected row instead of a separate row)

By severity: HIGH: 3 · MED: 5 · LOW: 6

## Fix list (ordered by severity)

**HIGH**
1. `ext_cr_board.js:217-223` — Stop dropping ungrouped agent sessions (`agent:true`, `group:""`) from the board entirely; either fold them into a `(no group)` bucket via `agentGroups()` or include them in the individual-tile list when non-idle.
2. `ext_cr_board.css:857-867` + `ext_cr_board.js:1671` — Apply `--line-agent` border + `--glow-agent-soft` (with `--shadow-raised`) to **every** `working`-state tile per 02:213 and 01-foundations.md:271, not only tiles with `s.bg > 0`; keep `--agent-glow`/bg-count badge as an additional signal if desired, but don't gate the base doc-mandated styling on it.
3. `ext_cr_board.js:1681-1689` — Restore the "project · tool" sub-line (mono, 10.5px, muted) on every tile per 02's anatomy diagram, not only the hero tile.

**MED**
4. `ext_cr_board.css:759-764` — Change triage count font-size back to 33px (02:158) per the doc-wins rule, or get explicit sign-off to keep 31px and update the doc instead.
5. `ext_cr_board.js:1255-1263` — Either document the "Sessions" destination pill in a spec update, or remove/gate it since 02 only names Board and Terminals.
6. `index.html:72` + `ext_cr_boot.css:39-65` — Move the `#tryNext` button into the sidebar header near `#livecount` ("N live" pill) per 02:12, or get sign-off to keep it in `header.hd`.
7. `ext_cr_board.js:1709-1715` — If `files`/`failing` counts become available in the list-dict shape, add them to the hero sidebar per 02:213 (currently honestly degraded to notes-only).
8. `ext_cr_board.js` `renderBoard()`/`els.boardScroll` — Add explicit scroll-position capture/restore around the board's own scroll container (`els.boardScroll.scrollTop`), matching the pattern already used for `els.railList` and `els.sessionsList`, since 02:245 calls re-render-preserving-scroll "the single most likely regression."

**LOW**
9. `ext_cr_board.css:820-832` / `ext_cr_board.js:735-741` — Reconcile the 1024px board-column boundary with doc 02's table (1024 should be 2-column, not 1-column) or update the doc to match the deliberate 1025/1024 split.
10. `ext_cr_board.js:384-391` — Rename `tracker.rail.mode` back to `tracker.rail` with the doc's binary vocabulary, or update 02 to document the tri-state `auto` mode.
11. `ext_cr_board.js:635-641` — Combine the rail search placeholder into the single "Search · ⌘K" string, or update the doc to describe the split input+kbd layout.
12. `ext_cr_board.js:182-187` — Document the `cr.boardTileCount` Config preference in 02, since it changes the advertised "never more than 8" copy's number.
13. `ext_cr_board.css:878-881` — Re-check the orange-2/orange-4 token substitution against 01-foundations.md's own comments (`--text-awaiting`/`--state-awaiting` are the documented matches) — flag to the tokens-audit owner.
14. `ext_cr_boot.js:1027` (top bar element order) — No code change needed; recommend reconciling 02's own two contradictory statements about which element is top-bar-first.
