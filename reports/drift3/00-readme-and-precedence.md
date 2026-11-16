# Drift round 3 - 00: bundle README, precedence, load-time robustness

Doc audited: `design_handoff_control_room/README.md` (11 decisions, 5 non-negotiables) plus cross-cutting precedence and page assembly.
Precedence applied: **docs win (commit 7b87cce, 2026-09-05), emoji tint excepted, plus later owner-directed deviations** (section 1).
Code SHA: `76bd154` (branch `worktree-control-room-drift`).

Paths are relative to `aitracker/web/` unless prefixed `tests/`, `reports/`, or `aitracker/`.

## 1. Precedence - which source wins today

**Answer: the docs win.** The 2026-08-29 "HTML wins" ruling was reversed by the owner on 2026-09-05 and no later ruling reverses it back.

- Old ruling, `reports/control-room-redesign.md:180-191`: "PRECEDENCE DECISION (owner, 2026-08-29) - the prototype wins ... Owner's ruling: go by the HTML. Round 5 is the latest and wins."
- Intermediate, `76e216f` (2026-09-05 01:16): "the owner's 'go by the HTML' ruling still stands everywhere except dark theme, and five findings that looked like drift (emoji filter, tile border/glow, non-hero sub-line, 31px counts, the separate ext_cr* files) are standing decisions". Mirrored in `reports/control-room-drift-analysis.md:10-30` (sections 0 and B).
- Reversal, `7b87cce` (2026-09-05 11:56): "the docs win ... The owner reversed the earlier 'prototype wins' ruling (emoji excepted), so the deviations that pass one preserved are now gone." It reverted: border + glow on every working tile, "project - tool" sub-line on every tile, triage counts 33px, entry button moved, 1024px breakpoint into the 2-column tier, board cap 3-12 (doc 04) with default 8, 7-chip stat row permanent.
- `5dea10f` (2026-09-05 13:41, after 7b87cce) does not restore HTML-wins. It records owner-specific overrides on top of docs-win: "the detail header shows the SESSION NAME, per the owner ... Doc 03:76 asks for the opposite; the owner's ruling wins", and the Sessions pill kept ("owner asked to keep them").
- Later `reports/*.md` (`board-tiles-rail-parity.md`, `board-rail-headline.md`, `spine-motion-vs-design-docs.md`, `emoji-to-icons.md`, `icon-config-knobs.md`, `control-room-refinements.md`): no new general precedence ruling. They add only feature-specific owner decisions (e.g. `board-rail-headline.md:76` "leave awaiting alone"; `emoji-to-icons.md:7-12` contract = emoji to SVG icons). `reports/control-room-redesign.md` was never annotated as superseded, which is why the contest persists.

**Fix (docs only):** add a one-line SUPERSEDED note under `reports/control-room-redesign.md:180` pointing at 7b87cce. Test: none (prose).

Working order for judging: (1) a specific owner decision in a report or commit message, (2) bundle docs 01-05 and README, (3) prototype Round 5. Standing owner deviations from the docs (NOT drift): session name as detail header (`5dea10f`); Sessions pill; SVG icons instead of emoji (`3455c4d`); working = green not wheat (`89c2267`, "Deliberate, documented departure ... the owner asked for green"); rail group-by and folder (`control-room-redesign.md` additional decisions 2-3); heartbeat as default progress view (`eb1e2bb`, `reports/heartbeat-panel.md`).

## 2. README: 11 decisions

| # | Decision | Verdict | Evidence |
|---|---|---|---|
| 1 | Board is home; detail keeps a collapsed 56px orb rail | MET | `ext_cr_board.css:604` (detail-orb 56px), `:619` collapsed 48px, `:621` detail default 56px |
| 2 | Board never renders more than 8 tiles; rest in rail | PARTIAL, ruled | Cap is 3-12, default 8 (`ext_cr_board.js:269-274`, `ext_cr_dialogs.js:1320`); `showAll` bypasses the cap (`ext_cr_board.js:389,430`). Ruled by 7b87cce (doc 04 slider beats README "never more than 8"). No code fix; note the README override in the PR. |
| 3 | Theme follows prefers-color-scheme, persistent override, Light/Dark | MET | `ext_cr_boot.js:114,176` (matchMedia + change listener); classic<->CR sync `:121-190` |
| 4 | Emoji stay, harmonised, beside a word | NOT MET to the letter, SUPERSEDED by owner request | `3455c4d` replaced emoji with monochrome SVG via `ico()`; `ext_cr_dialogs.css:119-121` colour tokens `.tn-emo*`; contract `reports/emoji-to-icons.md:7-12`. Words still sit beside every state. Fix: no code change; record in the PR that decision 4 is intentionally superseded. |
| 5 | Opt-in "Try the new experience" + one-click path back | MET | Button `index.html:115` (`#tryNext`), wired `ext_cr_boot.js:1210-1220`, first-run dialog `:1189-1195`; back path `ext_cr_board.js:2323-2325` ("Back to classic dashboard", always visible); `?ui=classic` override `ext_cr_boot.js:1223+`. Button sits in the main header (owner request, `5dea10f`). |
| 6 | Rail collapsible, open by default, 48px orbs | MET | `ext_cr_board.js:594-602` (auto/open/collapsed), `ext_cr_board.css:593,619` |
| 7 | Every detail card collapsed except the timeline; Expand/Collapse all | PARTIAL | `ext_cr_detail.js:325` `OPEN_BY_DEFAULT = { timeline:1, heartbeat:1, spine:1 }` so two more panels start open; fold default is pref `cr.cardsFolded` (`:296-302`). Fix: direction = owner decision (ask) whether heartbeat/spine stay open; if not, way = shrink the map at `:325` to `{ timeline:1 }`. Test: assertion in `tests/test_cr_logic.py` that `panelDefaultCollapsed` is true for every key except timeline (red before). |
| 8 | Narration + prompts one chat timeline | MET | `mergeTimeline` `ext_cr_detail.js:768`; newest-first `:1580` |
| 9 | Progress ring becomes spine (time-proportional + gutter) | PARTIAL | Spine exists (tests `tests/test_cr_spine_window.py`, `reports/spine-motion-vs-design-docs.md`) but the default progress view is `heartbeat` (`ext_cr_detail.js:308-314`: code returns "heartbeat" unless stored "spine"; comment at `:308` says the opposite). Auggie/augment-ext spine is equal-width (`reports/drift2/spine-auggie.md`). Fix: owner decision on heartbeat default (`eb1e2bb`); correct the stale comment at `:308`. Test: pin the default in `tests/test_cr_heartbeat_ui.py`. |
| 10 | Help and Config are dialogs, opened from header pills; Config exposes real params | MET | `renderHelp` `ext_cr_dialogs.js:796`; `renderConfig` `:978+` (`GET/POST /api/config` `:983-989`) |
| 11 | Nothing dropped from terminal; secondary flows are dialogs | MET (tests + prior audits) | `tests/test_cr_manage_terminals_parity.py`; per-doc audit is the doc 05 report, not this slice |

## 3. README: 5 non-negotiables

| Clause | Verdict | Evidence / fix |
|---|---|---|
| Read-only toward sessions | PARTIAL | No write path into session logs. But the control room POSTs into live terminals: `/api/term/inject` (`ext_cr_term.js:990`, `ext_cr_detail.js:3115`), `/api/term/kill`/`close` (`ext_cr_boot.js:885`, `ext_cr_detail.js:3127`), and `/api/title` which "reaches the Claude session" (`26425c1`; `ext_cr_boot.js:596`). Deliberate and owner-requested (`control-room-redesign.md` decision 5 "Stop-a-session: do not drop anything"; Evidence panel model/effort, `5dea10f`). The decision panels say "View-only" (`ext_cr_detail.js:1187,2789,3312`). Fix: no code change; amend the clause in the PR to "never writes the session LOG; terminal actions are explicit user clicks". Test: extend `tests/test_cr_readonly_ui.py` to enumerate the allowed POST routes (red when a new write route appears). |
| 2s poll + existing result shape; no new per-panel round-trips | PARTIAL | Main cycle reuses app.js `poll()`/`timer` (`ext_cr_boot.js:356-390`; 1s/5s pref); board/rail use app.js's 5s list poll (comment `:361-364`). Endpoints the CR calls that are NOT the shared `/api/session` / `/api/sessions`: `/api/search` (`ext_cr_board.js:1742`, on query), `/api/pin` (`ext_cr_board.js:2209`, `ext_cr_boot.js:643`), `/api/narration` (`ext_cr_detail.js:3379`, on-demand history paging), `/api/diff|output|agent|shell` (`ext_cr_boot.js:522-525`, drill-downs on click), `/api/title|flags|flags/resolve|flags/delete|notes|notes/delete` (`ext_cr_boot.js:596-703,917-919`), `/api/config`, `/api/tunnel`, `/api/tunnel/reveal`, `/api/tunnel/ctl` (`ext_cr_dialogs.js:983-1030`), `/api/model-keep` (`:2283`), `/api/term/{open,pty,list,cwds,run,stream,kill,inject,close,attached}` (`ext_cr_term.js:55-1213`, `ext_cr_boot.js:348-885`, `ext_cr_dialogs.js:1820-1847`). All are click-triggered except: one-shot `GET /api/term/list` probe (`ext_cr_boot.js:348`) and a **second recurring 2s poll while a terminal screen is open** (`ext_cr_term.js:1198-1224`: `/api/session`, `/api/term/attached`, `/api/term/list`; its comment concedes it is "the same extra round trip ... precedent"). Fix: direction = keep the terminal poll (live PTY state) but stop re-fetching `/api/session` there; way = in `_startPoll` reuse the response app.js `poll()` already cached, no new endpoint. Test: node-stub count of `fetch('/api/session')` over 5 ticks with a terminal open (red at 2 per tick). Severity LOW. |
| Provider-agnostic, honest degradation | MET | Fields land at the shared seam `aitracker/registry.py`; `tests/test_cr_registry_fields.py`, `tests/test_cr_parse_error.py`; no per-tool UI fork (single `SRC` map in app.js) |
| Gate green; `--selfcheck` assertion for new derived values | PARTIAL | `aitracker/cli.py:20` `_selfcheck` runs the unittest suite. Pinned: `boardTiles/sessionState/railOrder/agentGroups/triageCounts/spineSegments/mergeTimeline` (`tests/test_cr_logic.py:17-23`). The docstring there lists `deriveLinks`, `stateOf`, `firstEventTime` as exports but only the others are pinned. Fix: add assertions for those three in `tests/test_cr_logic.py` (red when the function is stubbed). |
| Colour never carries meaning alone | MET (audited once, not asserted) | Declared in `ext_cr_board.js:1999,2459`, `ext_cr_detail.js:1134`, `ext_cr_board.css:944`; round-1 audit "Now discharged" (`reports/control-room-drift-analysis.md` section E). No automated guard. Fix (LOW): node-stub test that each state's tile/orb markup contains its state word. |

### Classic `app.css`/`app.js` left unaltered: NOT MET as written (owner-directed)

README: "Do not alter existing selectors". Control-room-era edits that removed or restyled classic rules (from `git log -p -- aitracker/web/app.css`):
- `89c2267` (one state palette across both UIs): removed/restyled `.sitem.waiting`, `.sitem.done`, `.statusbadge.waiting/done`, `.sitem.flagged`, `.flagbadge`, `.dot.live`, `.nowbanner.done*`, `@keyframes pulseDot/pulseAmber` (133 added, 15 removed); classic gained reduced-motion handling.
- `3455c4d` (emoji to icons): removed `.card>h2::before` chevrons and rewrote about 25 emoji sites in `app.js` (`SRC`, row markup, md fences).
- `99a5954` (removed `.ico`/chevron vars), `6f21687` (removed `.sitem.pinned` bg; row markup), `e32831f` (`.sidetop .logo`), `317db79` (moved `cur/timer/sessions/liveOnly` declarations), `a5bf172` (`md()`, `SRC`), `5d02b48`.
- Other classic feature commits (`ee25e22`, `26425c1`, `950f746`, `52eef86`, `9552560`) are not CR-driven, so not drift.
- The sanctioned entry button is `index.html:115`.
Every deviation traces to an owner request ("one palette", icons) but none is recorded as an override of the README clause. Fix: direction = do NOT revert (it would re-split the palette); way = record the override in `reports/control-room-redesign.md` and the PR body. Test: existing `tests/test_classic_reduced_motion.py`, `tests/test_state_colors.py` already pin the new shared behaviour. Severity LOW.

### Tests covering control-room derived values
30+ `tests/test_cr_*.py` (logic, rail, board, detail, dialogs, routes, search, timeline, spine, topbar, tunnel, parse_error, registry fields, state uniformity, readonly UI), plus `tests/test_page_bundle.py`, `tests/test_page_css.py`, `tests/test_icons.py`, `tests/test_state_colors.py`, `tests/test_working_glow_*.py`, and CR asserts in `tests/test_selfcheck.py` (e.g. `:846`, `:1284-1311`). Gaps are those named above.

## 4. Round-1 section C: ruled since?

All four ruled:
- **C1 (7-chip stat row)**: `7b87cce` "the 7-chip stat row is permanent, not a preference -- the Config toggle is gone". Code `ext_cr_detail.js:1071` (`statChip(...)`).
- **C2 (tile cap 3-8 vs 8 vs 3-12)**: `7b87cce` "board tile cap 3-12 (doc 04) instead of a hard 8 (doc 02); default stays 8". Code `ext_cr_board.js:269-274`, `ext_cr_dialogs.js:1320`.
- **C3 (rail directory + grouping)**: `reports/control-room-redesign.md` "Owner's additional product decisions" items 2-3; code `ext_cr_board.js:115-120`; `76e216f` calls the contrary audit finding false ("six modes").
- **C4 (phone layout)**: built in `76e216f` ("back chevron + breadcrumb, presence orb, serif live narration, awaiting-question card"); code `ext_cr_detail.js:1113-1114,1171-1187,1343`.
Section B is SUPERSEDED by `7b87cce` (border/glow on all working tiles, sub-line everywhere, 33px counts are now doc-compliant). Section D deferred items were closed by `5dea10f` (run-command output pane, per-fence copy, mermaid, stop/model/effort; Auggie spine kept equal-width on evidence). Still unruled: the Sessions pill/browse view has no doc source (kept at owner request, `5dea10f`).

## 5. Load-time robustness (one script, one style tag)

Assembly, `aitracker/page.py:12-30`: `read_ext(suffix)` takes every `ext_*` file, `sorted()`, joins with newline; JS = `app.js + read_ext(".js")` into one `<script>`, CSS = `app.css + read_ext(".css")` into one `<style>`. Order: `ext_cr.css` (before `ext_cr_*`, "." < "_"), `_board`, `_boot`, `_detail`, `_dialogs`, `_term`, then `ext_launch`, `ext_run`, `ext_vt`. No per-file IIFE or try/catch. So a top-level throw in any `ext_cr_*.js` also kills `ext_launch`, `ext_run`, `ext_vt` (the classic terminal); a stray `*/` swallows CSS to the next terminator (history: `reports/control-room-redesign.md` browser-pass item 1, 659 rules dropped).

Guards now present (the memory note "make check misses both" is stale):
- `tests/test_page_bundle.py:206` runs the assembled JS in node with a stub DOM and requires `window.CR.{board,detail,dialogs,term}` to have `mount` and `update` (`:176-195`); also `:229` bare `CR.x =`, `:253` exactly 2 script blocks, `:276` no `</script>` in any `.js`.
- `tests/test_page_css.py:157` premature `*/`, `:195` comment balance, `:226` brace balance, `:264` one selector per `ext_cr_*.css` survives.

Residual gaps (each with fix):
1. **Skipped without node**: `tests/test_page_bundle.py:23,205` `skipUnless(_HAS_NODE)`, so the gate is green with no JS executed. Fix: fail loudly. Way: replace `skipUnless` with an always-run test asserting `_HAS_NODE` (or make `make check` fail when node is missing). Test: run with node off PATH, expect red.
2. **Only 4 modules asserted**; `CR.boot`, `ExtVT`, launch and run entry points (everything after the first throw) are not. A throw at the end of `ext_cr_term.js` would kill `ext_vt` with a green gate. Fix: add them to the epilogue list at `tests/test_page_bundle.py:176`. Test: append `throw new Error("x")` to `ext_cr_term.js`, expect red.
3. **CSS survival checks one selector per file** (`tests/test_page_css.py:264`); a stray `*/` mid-file stays green on that check (the `:157` terminator scan is the real defence). Fix: also sample each file's LAST class selector. Test: insert `*/` mid-file, expect red.
4. **Stub DOM, not a real browser**: runtime errors in `mount()` against a real DOM are uncovered (how "board rendered zero tiles" shipped). Visual-only, browser check.
5. **Per-file isolation at assembly**: do NOT add `try{}` wrappers in `page.py:read_ext`; top-level `let/const/function` would become block-scoped and break cross-file globals (`ico`, `track`, `poll`, `timer`, used at `ext_cr_boot.js:361-390`). Rely on gaps 1-3.

## 6. Extras (no README source)
Agent map, model marker chip, job-summary headline (`reports/job-summary-header.md`, `board-rail-headline.md`), heartbeat panel (`reports/heartbeat-panel.md`), terminal tiers, folder terminals, tunnel, idle TTL (own reports). All ruled by their own reports; only heartbeat touches README clauses (decisions 7 and 9).

## 7. Top 5
1. Precedence is settled only in commit messages; add a SUPERSEDED note at `reports/control-room-redesign.md:180`.
2. Bundle guard skips silently without node and omits `ExtVT`/launch/run/`CR.boot`; a throw in `ext_cr_term.js` would kill the classic terminal with a green gate.
3. Classic `app.css`/`app.js` were changed far beyond the entry button (palette, icons, markup); owner-directed but not recorded as overriding the README.
4. Terminal screen runs a second 2s poll (`ext_cr_term.js:1198-1224`) against "no new per-panel round-trips".
5. Detail opens heartbeat + spine by default and defaults to heartbeat versus decisions 7 and 9; needs an owner yes/no.
