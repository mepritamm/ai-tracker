# Drift analysis — `01-foundations.md` vs shipped implementation

Spec: `design_handoff_control_room/README.md` + `01-foundations.md` (authoritative; doc wins over prototype).
Implementation read at: `.claude/worktrees/cr-drift/aitracker/web/{ext_cr.css, ext_cr_boot.js, ext_cr_boot.css, index.html, app.css}`.

Legend — Verdict: MATCH / DRIFT / MISSING / EXTRA. Severity: HIGH / MED / LOW.

## 1. Scoping

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 1.1 | Scoping | Tokens under `.tracker-next` (light) / `.tracker-next.is-dark` (dark) | `ext_cr.css:38` `.tracker-next {`, `ext_cr.css:286` `.tracker-next.is-dark {` | MATCH | — |
| 1.2 | Scoping | Classic `:root` untouched | `app.css` — no `.tracker-next`/`--surface-*` rules found (grep clean); `app.js:743` only *reads* `.closest('.tracker-next')`, doesn't style it | MATCH | — |
| 1.3 | README "Files you will touch" | `app.css`: add token layer + component styles, don't alter existing selectors | `app.css` has zero `--ads-*`/`--surface-*`/font-stack additions; entry button styled entirely in `ext_cr_boot.css:45-65`, not `app.css` | MATCH | — |
| 1.4 | README | `index.html`: add new-experience root + entry button, keep classic markup intact | `index.html:72` adds `#tryNext` button, `index.html:171` adds `<div id=nextRoot class="tracker-next cr" hidden>`; no other line changed (git diff vs `main` empty) | MATCH | — |

## 2. Font stacks

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 2.1 | Typography | `--font-sans: 'Inter', system-ui, -apple-system, sans-serif;` | `ext_cr.css:180` identical | MATCH | — |
| 2.2 | Typography | `--font-serif: 'Newsreader', ui-serif, Georgia, serif;` | `ext_cr.css:181` identical | MATCH | — |
| 2.3 | Typography | `--font-mono: 'IBM Plex Mono', ui-monospace, Menlo, monospace;` | `ext_cr.css:182` identical | MATCH | — |
| 2.4 | Typography | Webfonts optional; system fallback acceptable | No `@font-face`/`fonts.googleapis` link anywhere in `web/` — stacks fall to the system fallback per the doc's own allowance | MATCH | — |

## 3. Type scale, spacing, radii, motion tokens

All present as `-min`/`-max` range tokens (a reasonable naming choice for a doc that gives ranges, not single values — not itself a drift).

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 3.1 | Scale table | Page title 29–32px/1.15/400 serif, ls -.02em | `ext_cr.css:193-197` `--fs-page-title-min:29px; -max:32px; --lh:1.15; --fw:400; --ls:-.02em` | MATCH | — |
| 3.2 | Scale table | Triage count 33–40px/1/400 serif, ls -.03em, tabular | `ext_cr.css:200-204` identical values | MATCH | — |
| 3.3 | Scale table | Section head (h2) 25–28px/1.2/400 serif | `ext_cr.css:207-210` identical | MATCH | — |
| 3.4 | Scale table | Tile title 14–16px/1.3/600 sans | `ext_cr.css:213-216` identical | MATCH | — |
| 3.5 | Scale table | Body 13–14px/1.5–1.6/400 sans | `ext_cr.css:219-223` identical | MATCH | — |
| 3.6 | Scale table | Row/control 12–12.5px/1.25–1.4/400–600 sans | `ext_cr.css:226-231` identical | MATCH | — |
| 3.7 | Scale table | Eyebrow 9.5–11px/1/600 sans, ls .06–.14em | `ext_cr.css:234-239` identical | MATCH | — |
| 3.8 | Scale table | Machine trace 10–12px/1.5/400 mono, tabular | `ext_cr.css:242-245` identical | MATCH | — |
| 3.9 | Scale table | Floor: 10px, mono metadata only | `ext_cr.css:248` `--fs-floor: 10px` | MATCH | — |
| 3.10 | Spacing | Page padding 22–34px x / 16–30px y | `ext_cr.css:251-254` identical | MATCH | — |
| 3.11 | Spacing | Panel padding 12–16px | `ext_cr.css:255-256` identical | MATCH | — |
| 3.12 | Spacing | Gaps: rail 3px, row 6–8, panel 11–16, section 20–26 | `ext_cr.css:257-263` identical | MATCH | — |
| 3.13 | Radii | 4px chips/rows, 8–10px panels/tiles, 999px pills, 0 unused | `ext_cr.css:266-270` identical | MATCH | — |
| 3.14 | Motion | Pulse duration 2.4s (only motion value given) | `ext_cr.css:277` `--motion-pulse-duration: 2.4s` | MATCH | — |

## 4. State vocabulary

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 4.1 | State table | "Waiting on you · <age>", orange, no motion | `ext_cr_detail.js:629` `{word:"Waiting on you", cls:"awaiting", age:...}`; `ext_cr_board.js:1517` same word | MATCH | — |
| 4.2 | State table | "Working", wheat, dot pulse 2.4s | `ext_cr_detail.js:632` `{word:"Working", cls:"working"}`; pulse wired (§6) | MATCH | — |
| 4.3 | State table | "N flags open", rust, no motion | `ext_cr_board.js:1509,1641` builds "N flags open" text | MATCH | — |
| 4.4 | State table | Failing: word is **"fail" + command name**, brick | `ext_cr_detail.js:631` `if (failing) return {word:"Failing", cls:"failed"}` — generic word, command name not interpolated | DRIFT (spec: `fail: <cmd>`, actual: static `"Failing"`) | MED |
| 4.5 | State table | Failing state exists as a distinct triage state | `ext_cr_board.js:46-48` own comment: rank/tile logic "never includes a 'failing' key" — no board tile ever renders the Failing state at all | MISSING (board-level; detail-level partially present per 4.4) | HIGH |
| 4.6 | State table | "Landed", forest, no motion | `ext_cr_detail.js:633` `{word:"Landed", cls:"done"}` | MATCH | — |
| 4.7 | State table | Idle: counted, not listed, grey | `ext_cr_board.js:95-96` has an `idle: 'Idle'` label alongside the others rather than purely a count — worth a closer look but not verified as a full violation within this file set | MATCH (word present; count-only rendering not disproved here) | — |
| 4.8 | Non-negotiable | "Colour never carries meaning alone" | Every state above pairs colour class with a literal word string | MATCH | — |

## 5. Emoji tinting recipe (item explicitly flagged as a likely drift site)

The doc's **current** (revised) recipe is a gentle `saturate()` + small `hue-rotate()` per role, explicitly *not* grayscale-then-recolour: *"Do not grayscale-and-resepia them: that made every emoji the same colour and destroyed the thing that makes an emoji readable at 10px."* (01-foundations.md:277)

| # | Spec ref | Spec says (light) | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 5.1 | Emoji tinting | `.tn-emo{filter:saturate(.7) contrast(1.05)}` | `ext_cr.css:450` `.tn-emo{filter:grayscale(1) sepia(1) hue-rotate(0deg) saturate(1.4) brightness(.55) contrast(1.1)}` | DRIFT | HIGH |
| 5.2 | Emoji tinting | `.tn-emo-a{filter:saturate(1.05) hue-rotate(-6deg)}` | `ext_cr.css:451` `grayscale(1) sepia(1) hue-rotate(-13deg) saturate(1.4) brightness(.55) contrast(1.1)` | DRIFT | HIGH |
| 5.3 | Emoji tinting | `.tn-emo-f{filter:saturate(.85) hue-rotate(-12deg) brightness(.95)}` | `ext_cr.css:452` `grayscale(1) sepia(1) hue-rotate(-25deg) saturate(1.4) brightness(.55) contrast(1.1)` | DRIFT | HIGH |
| 5.4 | Emoji tinting | `.tn-emo-d{filter:saturate(.62) hue-rotate(-18deg) brightness(.82)}` | `ext_cr.css:453` `grayscale(1) sepia(1) hue-rotate(108deg) saturate(1.4) brightness(.55) contrast(1.1)` | DRIFT | HIGH |
| 5.5 | Emoji tinting | `.tn-emo-n{filter:saturate(.8) hue-rotate(-8deg) brightness(.95)}` | `ext_cr.css:454` `grayscale(1) sepia(1) hue-rotate(7deg) saturate(1.4) brightness(.55) contrast(1.1)` | DRIFT | HIGH |
| 5.6 | Emoji tinting (dark) | `.is-dark .tn-emo{filter:saturate(.8) contrast(1.05) brightness(1.15)}` | `ext_cr.css:462` `grayscale(1) sepia(1) hue-rotate(-6deg) saturate(1.5) brightness(1.35) contrast(1.05)` | DRIFT | HIGH |
| 5.7 | Emoji tinting (dark) | `.is-dark .tn-emo-a{...saturate(1.1) hue-rotate(-6deg) brightness(1.15)}` | `ext_cr.css:463` `hue-rotate(-4deg) saturate(1.5) brightness(1.35) contrast(1.05)` | DRIFT | HIGH |
| 5.8 | Emoji tinting (dark) | `.is-dark .tn-emo-f{...hue-rotate(-12deg) brightness(1.18)}` | `ext_cr.css:464` `hue-rotate(-24deg) saturate(1.5) brightness(1.35) contrast(1.05)` | DRIFT | HIGH |
| 5.9 | Emoji tinting (dark) | `.is-dark .tn-emo-d{...hue-rotate(-18deg) brightness(1.2)}` | `ext_cr.css:465` `hue-rotate(71deg) saturate(1.5) brightness(1.35) contrast(1.05)` | DRIFT | HIGH |
| 5.10 | Emoji tinting (dark) | `.is-dark .tn-emo-n{...hue-rotate(-8deg) brightness(1.2)}` | `ext_cr.css:466` `hue-rotate(8deg) saturate(1.5) brightness(1.35) contrast(1.05)` | DRIFT | HIGH |
| 5.11 | Emoji tinting non-negotiable | "Do not grayscale-and-resepia" — named anti-pattern | `ext_cr.css:450-466` literally opens every rule with `grayscale(1) sepia(1)` — the exact forbidden construction, applied to all 5 roles × 2 themes | DRIFT — violates the doc's explicit anti-pattern warning | HIGH |
| 5.12 | Emoji tinting | "One filter declaration per rule ... a second one overrides, doesn't compose" | Both old and new recipes in `ext_cr.css` obey this (single `filter:` per rule) | MATCH | — |
| 5.13 | — | Implementation's own in-file comment (`ext_cr.css:398-449`) claims this is a deliberate post-doc "owner override" superseding decision 4/doc 01 | Self-documented deviation, not silent — but per this task's mandate the doc is authoritative and the shipped filter does not match it | DRIFT (flagged per task instructions regardless of claimed authorization — unverifiable from the doc set given) | HIGH |
| 5.14 | Accessibility | Every emoji gets `aria-hidden="true"` | Confirmed on every `tn-emo*` usage grepped in `ext_cr_board.js`, `ext_cr_detail.js`, `ext_cr_dialogs.js`, `ext_cr_term.js` | MATCH | — |

## 6. Motion — pulse keyframe

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 6.1 | Motion | `@keyframes tn-pulse{0%{box-shadow:0 0 0 0 rgba(217,184,85,.5)} 70%{...8px...0} 100%{...0...0}}` | `ext_cr_board.css:933-937` `@keyframes cr-board-pulse` — identical box-shadow stops/colours, different name; `ext_cr_detail.css:523-526` `@keyframes crd-pulse` — same identical stops, different name again (two separate keyframes, not the doc's one `tn-pulse`) | DRIFT (values match exactly; the doc's single reusable `.tn-dot`/`tn-pulse` name was forked into two component-local, differently-named keyframes instead of one shared rule) | LOW |
| 6.2 | Motion | `.tn-dot.is-working{animation:tn-pulse 2.4s infinite}` | `ext_cr_board.css:936` `.cr-tile-dot.is-working{animation:cr-board-pulse var(--motion-pulse-duration) infinite}`; `ext_cr_detail.css:490` `.crd-seg-dot{animation:crd-pulse 2.4s infinite}` | DRIFT (same duration/behaviour, different selector names — component-scoped instead of the doc's shared `.tn-dot`) | LOW |
| 6.3 | Motion | `prefers-reduced-motion`: `animation:none; outline:2px solid var(--state-thinking); outline-offset:2px` — "a designed variant, never a dead stop" | `ext_cr_board.css:938-942` and `ext_cr_detail.css:494-496` both reproduce this exact rule verbatim | MATCH | — |
| 6.4 | — | `ext_cr.css` itself | File only declares `--motion-pulse-duration`; the actual `@keyframes`/`.tn-dot` rule is explicitly deferred to component CSS per its own comment (`ext_cr.css:272-276`) | MATCH (consistent with the file's stated scope) | — |

## 7. Theme resolution

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 7.1 | Theme resolution | `localStorage['tracker.theme']` = `'auto'\|'light'\|'dark'`, default `'auto'` | `ext_cr_boot.js:93-100` `getThemePref()`/`setThemePref()` identical key/values/default | MATCH | — |
| 7.2 | Theme resolution | `resolveTheme()`: dark if pref==='dark' or (pref==='auto' && systemDark) | `ext_cr_boot.js:104-107` identical logic | MATCH | — |
| 7.3 | Theme resolution | `applyTheme()` toggles `.is-dark` on `.tracker-next` | `ext_cr_boot.js:128-150` toggles `is-dark` on every `.tracker-next` scope (defensive superset of the doc's single-element version, guarding against a shadowing bug) | MATCH (functionally equivalent, hardened) | — |
| 7.4 | Theme resolution | `matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme)` — "live, no reload" | `ext_cr_boot.js:163-168` registers `onSystemChange` (guarded to only re-apply when pref is `'auto'`) via `addEventListener`, with an `addListener` Safari<14 fallback | MATCH — listener verified present and wired | — |
| 7.5 | — | Segmented control semantics (auto label dims when a side is picked; clicking the highlighted side returns to auto) | Not verifiable from the files in scope (control markup lives in `ext_cr_board.js`, out of this file's primary scope) | Not evaluated | — |

## 8. Glyphs (not emoji)

| # | Spec ref | Spec says | Implementation (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 8.1 | Glyphs needed | `spark · search · chevron · check · alert · bell · branch · panel · redo · edit · clock · stop · send` (13 glyphs), 24px grid, `currentColor`, 1.5–2px stroke | `ext_cr_boot.js:59-73` `GLYPHS` object defines all 13 by exact name; `icon()` (line 74-80) emits `viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.75"` | MATCH (all 13 present, in range) | — |
| 8.2 | Assets | No icon font or icon package added | No `fontawesome`/`material-icons`/`feather` references anywhere in `web/`; only pre-existing approved vendor assets (`xterm`, `mermaid`) present | MATCH | — |

## 9. Light theme — colour/material tokens (`.tracker-next`, `ext_cr.css:38-278`)

### Surfaces (15)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 9.1 | `--surface-page` | `linear-gradient(180deg,#F1EEE0,#DFEAEC)` | same (`ext_cr.css:56`) | MATCH | — |
| 9.2 | `--surface-raised` | `#FFFFFF` | same (`:57`) | MATCH | — |
| 9.3 | `--surface-top` | `#FBFAF7` | same (`:58`) | MATCH | — |
| 9.4 | `--surface-sunken` | `#F4F1E8` | same (`:59`) | MATCH | — |
| 9.5 | `--surface-trace` | `#F4F1E8` | same (`:60`) | MATCH | — |
| 9.6 | `--surface-note` | `#F7F4EA` | `#F2E9DE` (`:71`) | DRIFT | MED |
| 9.7 | `--surface-provenance` | `#EDF2F3` | `#E4EEF1` (`:72`) | DRIFT | MED |
| 9.8 | `--surface-inverse` | `#1E1B17` | same (`:73`) | MATCH | — |
| 9.9 | `--surface-agent-quiet` | `#FBF3DC` | `#F8E9BF` (`:74`) | DRIFT | MED |
| 9.10 | `--surface-agent-active` | `linear-gradient(160deg,#FBF3DC,#FFFFFF 55%,#EDF2F3)` | `linear-gradient(160deg,#F8E9BF,#FFFFFF 55%,#E4EEF1)` (`:75`) | DRIFT | MED |
| 9.11 | `--surface-awaiting` | `#FDF0E4` | `#F9E2CD` (`:76`) | DRIFT | MED |
| 9.12 | `--surface-failed` | `#FBEAE5` | `#F7D8CF` (`:77`) | DRIFT | MED |
| 9.13 | `--surface-done` | `#EDF3EE` | `#DBEBE0` (`:78`) | DRIFT | MED |
| 9.14 | `--surface-flagged` | `#FBEEE7` | `#F5DDD1` (`:79`) | DRIFT | MED |
| 9.15 | `--surface-signal-fill` | `#F5DE9B` | same (`:80`) | MATCH | — |

*Implementation self-documents (`ext_cr.css:39-70`) that the light block was never shippped as measured hex in either prototype export, and was re-derived from the dark block for WCAG compliance — the 8 drifted values above are a deliberate, disclosed re-derivation rather than a silent slip. Still a DRIFT against the doc's literal light hex table.*

### Ink (13; doc's light table lists 11)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 9.16 | `--text-primary` | `#1E1B17` | same | MATCH | — |
| 9.17 | `--text-secondary` | `#4A4237` | same | MATCH | — |
| 9.18 | `--text-muted` | `#877866` | `#6E6253` (`:89`) | DRIFT (disclosed contrast fix) | MED |
| 9.19 | `--text-link` | `#3B5747` | same | MATCH | — |
| 9.20 | `--text-thinking` | `#8A6D14` | `#826613` (`:94`) | DRIFT (disclosed contrast fix) | LOW |
| 9.21 | `--text-awaiting` | `#9A4F19` | same | MATCH | — |
| 9.22 | `--text-failed` | `#8A2F1B` | same | MATCH | — |
| 9.23 | `--text-flagged` | `#7D3A28` | same | MATCH | — |
| 9.24 | `--text-agent` | `#6F6455` | same | MATCH | — |
| 9.25 | `--text-on-action` | `#FBFAF7` | same | MATCH | — |
| 9.26 | `--text-on-signal` | `#1E1B17` | same | MATCH | — |
| 9.27 | `--text-dusk` | not in doc's token list at all | `#395D6A` (`:104`) | EXTRA | LOW |
| 9.28 | `--text-eyebrow` | not in doc's token list at all | `#3B5747` (`:109`) | EXTRA | LOW |

### Lines (11 incl. 2 extras; doc's light table lists 9)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 9.29 | `--line-subtle` | `#E7E2D5` | same | MATCH | — |
| 9.30 | `--line-default` | `#CFC7B7` | same | MATCH | — |
| 9.31 | `--line-strong` | `#A89C8B` | `#807360` (`:121`) | DRIFT (disclosed) | MED |
| 9.32 | `--line-agent` | `#D9B855` | `#927426` (`:129`) | DRIFT (disclosed) | MED |
| 9.33 | `--line-awaiting` | `#E8B98A` | same | MATCH | — |
| 9.34 | `--line-failed` | `#E0A491` | same | MATCH | — |
| 9.35 | `--line-done` | `#B9CBBF` | same | MATCH | — |
| 9.36 | `--line-flagged` | `#E0B49F` | same | MATCH | — |
| 9.37 | `--line-focus` | `#3B5747` | same | MATCH | — |
| 9.38 | `--line-dusk` | not in doc | `#668A99` (`:139`) | EXTRA | LOW |
| 9.39 | `--line-note` | not in doc | `#6E8A75` (`:144`) | EXTRA | LOW |

### State dots (6)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 9.40 | `--state-thinking` | `#D9B855` | `#9E7F1F` (`:158`) | DRIFT (disclosed contrast fix) | MED |
| 9.41 | `--state-awaiting` | `#E58F3C` | `#B96719` (`:159`) | DRIFT (disclosed) | MED |
| 9.42 | `--state-done` | `#3B5747` | same | MATCH | — |
| 9.43 | `--state-failed` | `#C0553A` | same | MATCH | — |
| 9.44 | `--state-flagged` | `#C27950` | `#A6613A` (`:162`) | DRIFT (disclosed) | MED |
| 9.45 | `--state-idle` | `#A89C8B` | `#91816E` (`:167`) | DRIFT (disclosed) | LOW |

### Fills (2) and material (4)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 9.46 | `--fill-action` | `linear-gradient(180deg,#3B5747,#2E4438)` | same | MATCH | — |
| 9.47 | `--fill-row-hover` | `rgba(0,0,0,.04)` | same | MATCH | — |
| 9.48 | `--shadow-raised` | `1px 2px 5px rgba(30,27,23,.10)` | same | MATCH | — |
| 9.49 | `--shadow-overlay` | `2px 10px 30px rgba(30,27,23,.18)` | same | MATCH | — |
| 9.50 | `--glow-agent` | `0 0 0 1px rgba(217,184,85,.35), 0 2px 14px rgba(217,184,85,.28)` | same | MATCH | — |
| 9.51 | `--glow-agent-soft` | `0 0 10px rgba(217,184,85,.20)` | same | MATCH | — |

## 10. Dark theme — colour/material token overrides (`.tracker-next.is-dark`, `ext_cr.css:286-354`)

**Doc's own warning (01-foundations.md:104): using step-8 ink values `orange-8 #6E3711`, `brick-8 #642113`, `wheat-8 #52400F` as dark *fills* is explicitly named "the mistake to avoid — this one shipped once and had to be fixed."**

### Surfaces (15) — the worst block in the file

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 10.1 | `--surface-page` | `linear-gradient(180deg,#1E1B17,#24211C)` | `linear-gradient(180deg,#1E1B17,#243235)` (`:288`) | DRIFT (bottom stop; coincides with impl's own `--surface-provenance`) | MED |
| 10.2 | `--surface-raised` | `#2A251F` | `#302A23` (`:289`) | DRIFT | LOW |
| 10.3 | `--surface-top` | `#231F1A` | `#26221C` (`:290`) | DRIFT | LOW |
| 10.4 | `--surface-sunken` | `#1A1714` | `#1E1B17` (`:291`) | DRIFT | LOW |
| 10.5 | `--surface-trace` | `#1A1714` | `#1E1B17` (`:292`) | DRIFT | LOW |
| 10.6 | `--surface-inverse` | `#100E0C` | `#12100E` (`:295`) | DRIFT | LOW |
| 10.7 | **`--surface-awaiting`** | `#3A2A18` (orange wash) | **`#6E3711`** (`:298`) — this is **`orange-8`, the exact "mistake" hex the doc names and forbids as a dark fill** | DRIFT — reproduces the doc's own named anti-pattern | **HIGH** |
| 10.8 | **`--surface-failed`** | `#3A211A` (brick wash) | **`#642113`** (`:299`) — this is **`brick-8`, the exact "mistake" hex** | DRIFT — same anti-pattern | **HIGH** |
| 10.9 | `--surface-done` | `#22322A` | `#1F3227` (`:300`) | DRIFT | LOW |
| 10.10 | `--surface-flagged` | `#38241B` | `#5C2A1C` (`:301`) | DRIFT | MED |
| 10.11 | **`--surface-agent-quiet`** | `#322A16` (wheat wash) | **`#52400F`** (`:296`) — this is **`wheat-8`, the exact "mistake" hex** | DRIFT — same anti-pattern | **HIGH** |
| 10.12 | `--surface-agent-active` | `linear-gradient(160deg,#3D3218,#2A251F 58%,#24302B)` | `linear-gradient(160deg,#52400F,#302A23 55%,#24352F)` (`:297`) — gradient start reuses the same `wheat-8` mistake value | DRIFT | HIGH |
| 10.13 | `--surface-note` | `#262B22` (sage wash) | `#2A1E15` (`:293`) — impl uses a warm brown, doc specifies a green/sage tint | DRIFT (hue family changed, not just lightness) | MED |
| 10.14 | `--surface-provenance` | `#222E31` (dusk wash) | `#243235` (`:294`) | DRIFT | LOW |
| 10.15 | `--surface-signal-fill` | `#C9A33C` | `#E5CB79` (`:302`) — impl value equals the doc's own `--text-thinking` dark value, suggesting a copy from the wrong token | DRIFT | MED |

### Ink (13 incl. 3 extras; doc's dark table lists 10 — no `--text-agent` override given)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 10.16 | `--text-primary` | `#FBFAF7` | same | MATCH | — |
| 10.17 | `--text-secondary` | `#D8CFC2` | same | MATCH | — |
| 10.18 | `--text-muted` | `#A89C8B` | same | MATCH | — |
| 10.19 | `--text-link` | `#8FB187` | same | MATCH | — |
| 10.20 | `--text-thinking` | `#E5CB79` | same | MATCH | — |
| 10.21 | `--text-awaiting` | `#F5C98E` | same | MATCH | — |
| 10.22 | `--text-failed` | `#E0A491` | same | MATCH | — |
| 10.23 | `--text-flagged` | `#E5BFA5` | same | MATCH | — |
| 10.24 | `--text-on-action` | `#1E1B17` | same | MATCH | — |
| 10.25 | `--text-on-signal` | `#1E1B17` | same | MATCH | — |
| 10.26 | `--text-agent` | doc's dark block never redefines it (light value `#6F6455` would otherwise leak into dark) | `#C6B29B` (`:313`) | EXTRA (undocumented in doc, but plausibly a necessary fix for an apparent doc gap) | LOW |
| 10.27 | `--text-dusk` | not in doc | `#A8C0C9` (`:320`) | EXTRA | LOW |
| 10.28 | `--text-eyebrow` | not in doc | `#8FB187` (`:321`) | EXTRA | LOW |

### Lines (11 incl. 2 extras; doc's dark table lists 9)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 10.29 | `--line-subtle` | `#403A31` | `#4A4237` (`:324`) | DRIFT | LOW |
| 10.30 | `--line-default` | `#6E6354` | `#6F6455` (`:325`) | DRIFT (near-identical, still a mismatch) | LOW |
| 10.31 | `--line-strong` | `#7A6E5D` | `#A89C8B` (`:326`) | DRIFT | MED |
| 10.32 | `--line-agent` | `#A9862C` | same (`:327`) | MATCH | — |
| 10.33 | `--line-awaiting` | `#B4712C` | `#9A4F19` (`:328`) — equals light theme's `--text-awaiting` value; looks like a wrong-token copy | DRIFT | MED |
| 10.34 | `--line-failed` | `#B85A3F` | `#7F2B1A` (`:329`) | DRIFT | MED |
| 10.35 | `--line-done` | `#6E9478` | `#3B5747` (`:330`) — equals light theme's `--text-link`/`--fill-action` start colour; looks like a wrong-token copy | DRIFT | MED |
| 10.36 | `--line-flagged` | `#A9714E` | `#7D3A28` (`:331`) — equals light theme's `--text-flagged`; looks like a wrong-token copy | DRIFT | MED |
| 10.37 | `--line-focus` | `#8FB187` | same (`:332`) | MATCH | — |
| 10.38 | `--line-dusk` | not in doc | `#7E9AA6` (`:333`) | EXTRA | LOW |
| 10.39 | `--line-note` | not in doc | `#6E8A75` (`:334`) | EXTRA | LOW |

*Unlike the light-theme drifts (which carry explanatory comments), none of the dark `--line-*` mismatches above are annotated — several look like accidental copies of unrelated light-theme tokens rather than deliberate re-derivations.*

### State dots (6)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 10.40 | `--state-thinking` | `#D9B855` | same | MATCH | — |
| 10.41 | `--state-awaiting` | `#E58F3C` | same | MATCH | — |
| 10.42 | `--state-done` | `#8FB187` | same | MATCH | — |
| 10.43 | `--state-failed` | `#D2735A` | same | MATCH | — |
| 10.44 | `--state-flagged` | `#C27950` | same | MATCH | — |
| 10.45 | `--state-idle` | `#877866` | same | MATCH | — |

### Fills (2 + 1 missing) and material (4)

| # | Token | Spec value | Impl value (file:line) | Verdict | Severity |
|---|---|---|---|---|---|
| 10.46 | `--fill-action` | `linear-gradient(180deg,#8FB187,#6E8A75)` | same (`:345`) | MATCH | — |
| 10.47 | `--fill-action-solid` | `#8FB187` | not declared anywhere in `ext_cr.css` | MISSING | LOW |
| 10.48 | `--fill-row-hover` | `rgba(251,250,247,.06)` | `rgba(255,255,255,.06)` (`:346`) | DRIFT (minor — pure white vs. warm off-white) | LOW |
| 10.49 | `--shadow-raised` | `1px 2px 5px rgba(0,0,0,.5)` | `1px 2px 5px rgba(0,0,0,.45)` (`:352`) | DRIFT | LOW |
| 10.50 | `--shadow-overlay` | `2px 10px 30px rgba(0,0,0,.66)` | `2px 10px 30px rgba(0,0,0,.60)` (`:353`) | DRIFT | LOW |
| 10.51 | `--glow-agent` / `--glow-agent-soft` | Doc deliberately does NOT redefine these for dark — theme-invariant glow | Not redefined in `.tracker-next.is-dark` — correctly inherits the light-block value (`ext_cr.css:348-351` comment confirms this is intentional) | MATCH | — |

## Fix list (ordered by severity)

1. **HIGH** — `aitracker/web/ext_cr.css:296,298,299` (dark `--surface-agent-quiet`, `--surface-awaiting`, `--surface-failed`): replace `#52400F`/`#6E3711`/`#642113` (the doc's own named "mistake" ink values, `wheat-8`/`orange-8`/`brick-8`) with the doc's actual dark-surface values `#322A16`/`#3A2A18`/`#3A211A`. Also fix `ext_cr.css:297` `--surface-agent-active`'s gradient start (currently `#52400F`) to `#3D3218` per doc.
2. **HIGH** — `aitracker/web/ext_cr.css:450-466`: replace the `grayscale(1) sepia(1) hue-rotate(...) saturate(1.4/1.5) brightness(.55/1.35) contrast(1.1/1.05)` emoji filters (all 10 rules, light+dark) with the doc's current recipe (`saturate()` + small `hue-rotate()` per role, no `grayscale`/`sepia`) — the shipped recipe is the exact "grayscale-and-resepia" construction 01-foundations.md explicitly forbids by name.
3. **HIGH** — `aitracker/web/ext_cr_board.js:46-48` (board rank/tile logic): the Failing state has no board-tile representation at all; add it as a distinct triage state per the doc's six-state table.
4. **MED** — `aitracker/web/ext_cr_detail.js:631`: change the Failing-state word from the static `"Failing"` to `"fail: " + <command name>` per the doc's exact word format.
5. **MED** — `aitracker/web/ext_cr.css:298-302` dark surfaces `--surface-flagged` (`#5C2A1C`→`#38241B`), `--surface-note` (`#2A1E15`→`#262B22`, wrong hue family — should be sage-green not brown), `--surface-signal-fill` (`#E5CB79`→`#C9A33C`, currently duplicates `--text-thinking`'s dark value).
6. **MED** — `aitracker/web/ext_cr.css:328-331` dark `--line-awaiting`/`--line-done`/`--line-flagged`: these currently equal unrelated light-theme ink tokens (`#9A4F19`, `#3B5747`, `#7D3A28`); replace with the doc's actual values `#B4712C`/`#6E9478`/`#A9714E`.
7. **LOW** — `aitracker/web/ext_cr.css:288-295` remaining dark neutral surfaces (`--surface-page` bottom stop, `-raised`, `-top`, `-sunken`, `-trace`, `-inverse`, `-provenance`) and `ext_cr.css:324-330` remaining dark lines (`-subtle`, `-default`, `-strong`): align to doc's exact hex values — currently off by small but real amounts, all undocumented (no comment explaining the deviation, unlike the disclosed light-theme re-derivations).
8. **LOW** — `aitracker/web/ext_cr.css:346,352,353` dark `--fill-row-hover`/`--shadow-raised`/`--shadow-overlay`: tighten alpha/RGB to doc's exact values (`rgba(251,250,247,.06)`, `.5`, `.66`).
9. **LOW** — `aitracker/web/ext_cr.css`: add missing `--fill-action-solid: #8FB187` to the dark block.
10. **LOW** — Consider renaming `ext_cr_board.css`'s `cr-board-pulse`/`ext_cr_detail.css`'s `crd-pulse` to a single shared `tn-pulse` keyframe (values already match the doc exactly) to remove the duplication the doc's single-name design intended.
