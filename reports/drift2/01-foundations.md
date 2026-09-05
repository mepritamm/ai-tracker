# Adversarial re-audit — 01-foundations.md vs implementation

Scope: `aitracker/web/ext_cr.css`, `ext_cr_boot.js`, `index.html` (pulse keyframe / state
wording additionally traced into `ext_cr_board.css`/`.js` since the doc requires them and
they exist only there).

| # | Doc section | Doc says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 1 | Scoping | `.tracker-next` (light) / `.tracker-next.is-dark` (dark), classic `:root` untouched | `ext_cr.css` — every rule scoped `.tracker-next`/`.tracker-next.is-dark`, no bare `:root`/`body`/`html` (grep confirmed) | MATCH | — |
| 2 | Theme resolution | `localStorage['tracker.theme']` auto/light/dark; `resolveTheme()`/`applyTheme()`; live `matchMedia` change listener | `ext_cr_boot.js:93-107` (resolveTheme), `:128-162` (applyTheme, toggles `.is-dark`), `:163-168` (live change listener) | MATCH | — |
| 3 | Light surfaces: `--surface-note` `#F7F4EA`, `-provenance` `#EDF2F3`, `-agent-quiet` `#FBF3DC`, `-agent-active` grad `#FBF3DC…#EDF2F3`, `-awaiting` `#FDF0E4`, `-failed` `#FBEAE5`, `-done` `#EDF3EE`, `-flagged` `#FBEEE7` | doc lines 44-53 | `ext_cr.css:71-79` all re-hexed (`#F2E9DE`,`#E4EEF1`,`#F8E9BF`,`#F8E9BF…#E4EEF1`,`#F9E2CD`,`#F7D8CF`,`#DBEBE0`,`#F5DDD1`) | DRIFT (7 tokens) | MED |
| 4 | `--text-muted` light `#877866` | doc:59 | `ext_cr.css:89` → `#6E6253` | DRIFT | MED |
| 5 | `--text-thinking` light `#8A6D14` | doc:61 | `ext_cr.css:94` → `#826613` | DRIFT | LOW |
| 6 | `--line-strong` light `#A89C8B` | doc:72 | `ext_cr.css:121` → `#807360` | DRIFT | MED |
| 7 | `--line-agent` light `#D9B855` | doc:73 | `ext_cr.css:129` → `#927426` | DRIFT | MED |
| 8 | `--state-thinking`/`-awaiting`/`-flagged`/`-idle` light `#D9B855`/`#E58F3C`/`#C27950`/`#A89C8B` | doc:81-86 | `ext_cr.css:158-167` → `#9E7F1F`/`#B96719`/`#A6613A`/`#91816E` | DRIFT (4 tokens) | MED |
| 9 | Dark surfaces (15) | doc:115-131 | `ext_cr.css:288-302` — all 15 exact hex matches | MATCH | — |
| 10 | Dark ink (10 named), state dots (6), `--fill-action` | doc:134-143,156-162,165 | `ext_cr.css:305-315,337-342,345` — exact matches | MATCH | — |
| 11 | Dark: doc does not redefine `--text-agent` (should inherit light's `#6F6455`) | doc:133-143 (no entry) | `ext_cr.css:313` sets `--text-agent:#C6B29B` in `.is-dark` | EXTRA/DRIFT | MED |
| 12 | `--text-dusk`, `--text-eyebrow`, `--line-dusk`, `--line-note` — not in doc's fenced token list (light or dark) at all | doc has no such custom properties (only prose "dusk ink" in the contrast table) | `ext_cr.css:104,109,139,144` (light), `:320,321,333,334` (dark) | EXTRA | LOW |
| 13 | `--fill-row-hover` dark `rgba(251,250,247,.06)` | doc:167 | `ext_cr.css:346` → `rgba(255,255,255,.06)` | DRIFT | LOW |
| 14 | `--shadow-raised` dark `rgba(0,0,0,.5)` | doc:168 | `ext_cr.css:352` → `rgba(0,0,0,.45)` | DRIFT | LOW |
| 15 | `--shadow-overlay` dark `rgba(0,0,0,.66)` | doc:169 | `ext_cr.css:353` → `rgba(0,0,0,.60)` | DRIFT | LOW |
| 16 | `--glow-agent`/`--glow-agent-soft` dark: doc gives DIFFERENT dark values (`.4/.3` alpha, 16px/12px) than light (`.35/.28`, 14px/10px) | doc:170-171 | `ext_cr.css:348-351` — not redefined in `.is-dark`; comment claims "deliberately theme-invariant," which the doc contradicts | MISSING | HIGH |
| 17 | `--fill-action-solid` dark `#8FB187` | doc:166 | absent from `ext_cr.css` entirely; `grep -rn fill-action-solid` across `web/` returns nothing — token unused anywhere | MISSING | MED |
| 18 | Font stacks: Inter/Newsreader/IBM Plex Mono, doc's own fallback clause permits system-ui/`ui-serif,Georgia,serif`/`ui-monospace,Menlo,monospace` | doc:243-245 | `ext_cr.css:180-182` declares the doc's exact 3 stacks; `index.html:13-15` loads Source Sans 3 + JetBrains Mono for classic only, no Inter/Newsreader/Plex Mono link — resolves via doc's sanctioned fallback | MATCH | — |
| 19 | Type scale (8 roles), spacing scale, radii | doc:250-270 | `ext_cr.css:192-270` — every numeric value matches (exposed as `-min`/`-max` token pairs, doc gives ranges) | MATCH | — |
| 20 | Glyphs needed: spark/search/chevron/check/alert/bell/branch/panel/redo/edit/clock/stop/send, inline, no icon font | doc:320 | `ext_cr_boot.js:59-73` — all 13 present as inline SVG path data, rendered via `icon()` (`:74-80`); no icon-font/package added anywhere in repo | MATCH | — |
| 21 | Motion: `tn-pulse` keyframe (0%/70%/100%, `rgba(217,184,85,.5/0/0)`), reduced-motion → `outline:2px solid var(--state-thinking); outline-offset:2px` | doc:214-224 | Not in `ext_cr.css` (comment at `:272-276` explicitly defers it); actually implemented in `ext_cr_board.css:942-953` (`cr-board-pulse`, exact same 3 stops) and `ext_cr_detail.css:559/961` (`crd-pulse`) — values match doc exactly, different names | MATCH (elsewhere) | — |
| 22 | State vocabulary wording: "Waiting on you", "Working", "N flags open", "fail: <cmd>", "Landed" | doc:205-209 | `ext_cr_board.js:1560-1566` (`stateWord()`) — exact wording match | MATCH (elsewhere) | — |
| 23 | Contrast floor: 2px solid `--line-focus` outline, 2px offset | doc:324 | `ext_cr.css:387-390` | MATCH | — |

## Totals
- MATCH: 13 rows (1,2,9,10,18,19,20,21,22,23 — several bundling multiple tokens)
- DRIFT: 8 rows (3,4,5,6,7,8,11,13,14,15 — counted per row; several bundle multiple tokens)
- MISSING: 2 rows (16, 17)
- EXTRA: 2 rows (11 also EXTRA, 12)

(Net: light theme has ~15 individual hex values that don't match the doc's fenced light
block, all in the surfaces/ink/lines/state-dot families the doc gives literal hex for. Dark
theme's 15 surfaces + 6 state dots + core ink are exact; the drift there is narrower but
includes one HIGH item — glow tokens silently not overridden for dark despite the doc
specifying different dark values.)

## Fix list (ordered by severity)

**HIGH**
1. `ext_cr.css` `.tracker-next.is-dark` block (~line 348): add `--glow-agent: 0 0 0 1px rgba(217,184,85,.4), 0 2px 16px rgba(217,184,85,.3);` and `--glow-agent-soft: 0 0 12px rgba(217,184,85,.22);` — doc specifies these as dark-specific, not inherited from light. Also delete/correct the comment at `:348-351` claiming they're "deliberately theme-invariant."

**MED**
2. `ext_cr.css:71-79` (light `.tracker-next`): restore doc's exact hex for `--surface-note` (`#F7F4EA`), `--surface-provenance` (`#EDF2F3`), `--surface-agent-quiet` (`#FBF3DC`), `--surface-agent-active` (`#FBF3DC…#EDF2F3`), `--surface-awaiting` (`#FDF0E4`), `--surface-failed` (`#FBEAE5`), `--surface-done` (`#EDF3EE`), `--surface-flagged` (`#FBEEE7`) — or get the doc amended if the WCAG re-tint is meant to stand (it isn't in the settled-decisions list).
3. `ext_cr.css:89` restore `--text-muted: #877866` (or amend doc).
4. `ext_cr.css:121` restore `--line-strong: #A89C8B` (or amend doc).
5. `ext_cr.css:129` restore `--line-agent: #D9B855` (or amend doc).
6. `ext_cr.css:158-159,162` restore `--state-thinking:#D9B855`, `--state-awaiting:#E58F3C`, `--state-flagged:#C27950` (or amend doc).
7. `ext_cr.css:313` remove the dark-only `--text-agent` override (or add `#6F6455` as the light value too and get doc sign-off on the split).
8. `ext_cr.css:302` (dark) add `--fill-action-solid: #8FB187;` — currently missing and unused anywhere.

**LOW**
9. `ext_cr.css:94` restore `--text-thinking: #8A6D14` (light) or amend doc.
10. `ext_cr.css:167` restore `--state-idle: #A89C8B` (light) or amend doc.
11. `ext_cr.css:346` change dark `--fill-row-hover` to `rgba(251,250,247,.06)`.
12. `ext_cr.css:352` change dark `--shadow-raised` alpha `.45`→`.5`.
13. `ext_cr.css:353` change dark `--shadow-overlay` alpha `.60`→`.66`.
14. `ext_cr.css:104,109,139,144,320,321,333,334`: `--text-dusk`/`--text-eyebrow`/`--line-dusk`/`--line-note` are not in the doc's fenced token blocks — either get them added to 01-foundations.md (they do serve a real, doc-implied need — the contrast table's "dusk ink" row) or drop them if unused. Currently `--line-note` appears wholly unreferenced by the doc in any form; verify before keeping it.
