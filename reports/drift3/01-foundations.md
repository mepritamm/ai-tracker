# Drift round 3 - 01-foundations.md

Doc audited: `design_handoff_control_room/01-foundations.md`. Code SHA: `76bd154`.
Precedence applied: DOCS WIN (commit `7b87cce`, 2026-09-05, "the docs win ... emoji excepted"; it supersedes the 2026-08-29 "HTML wins" ruling). Later owner rulings that override the doc are marked SUPERSEDED-BY-RULING.
Method: a script parsed both fenced token blocks from the doc and every `--token:` in `ext_cr.css` (comments stripped) and diffed them; the rest was grep plus sed ranges.

## Headline
Every token the doc lists, light and dark, now equals the doc value exactly (scripted diff: zero differences). Light block `ext_cr.css:38-310`, dark block `ext_cr.css:313-420`. The round-1/2 HIGH and MED colour findings are all closed. What remains is small: the emoji recipe is gone by owner ruling (with one hole in the optional "emoji" icon style), the Working colour is split between wheat and green, the theme control differs from the doc's gesture, and a few LOW typography points.

## 2. Prior-finding status

Round 1 (`reports/drift/01-foundations.md`), round 2 (`reports/drift2/01-foundations.md`, `06-look-and-feel.md`), and section A of `control-room-drift-analysis.md`:

| id | finding | status now | evidence |
|---|---|---|---|
| R1 1.x | scoping `.tracker-next` / `.is-dark`, classic `:root` untouched | CLOSED (MATCH) | `ext_cr.css:38,313` |
| R1 2.x, 3.x | font stacks, type scale, spacing, radii, 2.4s | CLOSED (MATCH) | `ext_cr.css:207-209,293-297,304` |
| R1 4.4 / A5 detail | Failing word was generic "Failing" | CLOSED | `ext_cr_detail.js:978` `"fail: " + session.fail_cmd` |
| R1 4.5 / A5 board | no Failing tile state | CLOSED | `ext_cr_board.js:32` RANK has `failing`, `:86` `if (live && s.fail_cmd) return 'failing'`, `:2690` `'fail: ' + s.fail_cmd`; rail dot `.cr-rail-dot.is-failing` in `ext_cr_board.css` |
| R1 5.1-5.11 | emoji filter used grayscale+sepia, the doc's forbidden recipe | SUPERSEDED-BY-RULING | `reports/emoji-to-icons.md` (owner 2026-08-31: emoji become line SVG). Filters are gone; `ext_cr.css:473-488` now sets `color` only. No emoji literal remains in `ext_cr_*` code (scan clean apart from comments and the `✓ ok` / `✗ failed` text at `ext_cr_detail.js:3589`). See N5 for the leftover hole |
| R1 5.14 | aria-hidden on every emoji | CLOSED | `ext_cr_boot.js` `icon()` emits `aria-hidden="true"`; `ext_cr_board.js:834` `tn-emo` span has `aria-hidden` |
| R1 6.1/6.2 | pulse keyframe named `cr-board-pulse`/`crd-pulse`, not `tn-pulse`; two copies | STILL OPEN (cosmetic, LOW) | `ext_cr_board.css:1630`, `ext_cr_detail.css:727`; stops identical to doc |
| R1 6.3 | reduced-motion variant | CLOSED (MATCH) | `ext_cr_board.css:1636-1641`, `ext_cr_detail.css:688-690` |
| R1 7.x | theme resolution, localStorage, live listener | CLOSED (MATCH) | `ext_cr_boot.js:105-125,177` |
| R1 8.x | 13 glyphs, no icon font | CLOSED (MATCH) | `ext_cr_boot.js` `icon()` + `#i-<name>` sprite; no icon package |
| R1 9.6-9.14 / R2 #3 | 8 light surfaces off | CLOSED | `ext_cr.css:66-74` equal doc |
| R1 9.18, 9.20 / R2 #4, #5 | `--text-muted`, `--text-thinking` light | CLOSED | `ext_cr.css:81,84` = `#877866`, `#8A6D14` |
| R1 9.31, 9.32 / R2 #6, #7 | `--line-strong`, `--line-agent` light | CLOSED | `ext_cr.css:107,111` |
| R1 9.40-9.45 / R2 #8 | light state dots | CLOSED | `ext_cr.css:134-138,164` |
| R1 10.1-10.15 / A1 / A2 | dark surfaces, including the forbidden step-8 fills | CLOSED | dark `--surface-*` equal doc, `ext_cr.css:313-340` |
| R1 10.29-10.36 / A2 | dark `--line-*` wrong-column copies | CLOSED | scripted diff clean |
| R1 10.26 / R2 #11 | dark `--text-agent` override absent from doc | STILL OPEN as EXTRA, justified | `ext_cr.css:349` `#C6B29B` |
| R1 10.27, 10.28, 10.38, 10.39 / R2 #12, 06 #29 | `--text-dusk`, `--text-eyebrow`, `--line-dusk`, `--line-note` not in doc | STILL OPEN as EXTRA (LOW) | `ext_cr.css:94,99,121,126` light; `:356,357,369,370` dark |
| R1 10.47 / R2 #17 | `--fill-action-solid` missing | CLOSED, but token is unused | defined `ext_cr.css:394`; grep finds no consumer |
| R1 10.48-10.50 / R2 #13-15 | dark row-hover and shadow alphas | CLOSED | scripted diff clean |
| R2 #16 | dark glow tokens not overridden | CLOSED | dark block carries the doc's `.4/.3/16px` and `.22/12px` |
| R2 #21 | pulse keyframe lives outside `ext_cr.css` | CLOSED (values match) | see N6 for the naming |
| R2 #23 | focus ring 2px `--line-focus`, offset 2px | CLOSED (MATCH) | `ext_cr.css:450-453` |
| 06 #3 | summary labels used `--text-eyebrow` instead of muted | CLOSED | `ext_cr_detail.css:1182` |
| 06 #4 | `.crd-goal` 27px, under 29-32 | CLOSED on desktop | `ext_cr_detail.css:214` 29px; phone is 21px (N8) |
| 06 #5 | summary label weight 400 | CLOSED | `ext_cr_detail.css:1179` is 600 |

## 3. New drift

| # | doc section + line | doc says | code does (file:line) | verdict | sev |
|---|---|---|---|---|---|
| N1 | Light and dark token blocks, 01 (the two fenced blocks) | exact values for every listed token | all equal, both themes (scripted diff) | MATCH | - |
| N2 | Theme resolution | key `tracker.theme`, `resolveTheme`, live `change` listener | `ext_cr_boot.js:105-125,177` | MATCH | - |
| N3 | Theme control paragraph under Theme resolution | "`auto` label plus a light/dark segmented pair; clicking the highlighted side again returns to auto" | three equal buttons Auto/Light/Dark; clicking the highlighted side keeps that side (`ext_cr_board.js:2452-2488`; comment at `:2425-2435` says deliberate, owner complaint "no way back to auto"). Auto is a real button, not a dimming label | DRIFT | LOW |
| N4 | State vocabulary table | Working = wheat, dot pulse 2.4s | Working is green on rail dot, orb pip and detail state pill (`--state-working`: `ext_cr.css:160,383`; `ext_cr_board.css:947,1230`; `ext_cr_detail.css:135`). The board TILE dot (`ext_cr_board.css:1628`) and detail spine/state dots (`ext_cr_detail.css:684,707,1307`) stay wheat with a wheat halo. The green is owner-directed (comment `ext_cr.css:141-152`), but it covers only some surfaces, so one session shows two working colours | DRIFT vs doc; inconsistent vs the owner's green ask | MED |
| N5 | Emoji tinting (decision 4) | emoji stay, tinted by saturate/hue-rotate filters per role, plus `.is-dark` variants | the config knob `icon style = emoji` swaps real emoji glyphs in (`ext_cr_boot.js` `icon()` via `window.icoChar`; `app.css:108` `.ico-glyph`). `.tn-emo*` only set `color` (`ext_cr.css:473-488`; `ext_cr_dialogs.css:119-128`), which does not tint a colour emoji. In emoji mode the doc recipe is entirely absent | DRIFT | LOW |
| N6 | Motion block | `@keyframes tn-pulse`, `.tn-dot.is-working` | same stops and 2.4s under other names, two copies (`ext_cr_board.css:1630`, `ext_cr_detail.css:727`) | DRIFT (naming) | LOW |
| N7 | Scale, "Floor: 10px, only for mono metadata" | nothing below 10px | 9px: `ext_cr_board.css:1139` (collapsed rail footer, not mono), `ext_cr_detail.css:405` (flag badge, mono), `:657,671,718` (spine segment text). 8px: `ext_cr_detail.css:746,761` (`.crd-mark`, `.crd-mark-word`); the 8px FAIL word is required by 03-detail-view.md:147, so that pair is a doc-vs-doc conflict, not drift | DRIFT | LOW |
| N8 | Scale, detail page title | 29-32px | desktop 29px OK (`ext_cr_detail.css:214`); phone tier 21px (`:2110`); the doc gives no phone size | MATCH desktop; NOTE phone | LOW |
| N9 | Typography rule | machine output is mono AND `tabular-nums` | 39 rules set `--font-mono` without `tabular-nums` (board 6, detail 12, dialogs 16, term 5; e.g. `.cr-tile-counts`, `.cr-tile-pr`, `.crd-cmd-status`, `.cr-toast-meta`, `.cr-term-pill`). Some hold words rather than numbers | DRIFT | LOW |
| N10 | Spacing: "gap, never margins between siblings" | flex/grid gap | not audited; no spot check failed | NOT EXAMINED | - |
| N11 | Intro: "never a raw hex in a component rule" | tokens only | bare hex/rgba outside `var()` fallbacks: `ext_cr_term.css` 25 lines (e.g. `:272,278,279,321,322`), `ext_cr_boot.css:74,75,77,83` (amber entry button in the classic sidebar), `ext_cr_detail.css:916,917` (shimmer rgba). Board and dialogs are clean | DRIFT | LOW |
| N12 | Contrast floor | 2px `--line-focus` outline, visible on every surface | global rule `ext_cr.css:450`; `outline: none` at `ext_cr_board.css:745` (rail search input) with no `:focus-within` ring found on its wrapper; `ext_cr_dialogs.css:54` (dialog container, programmatic focus) | DRIFT | LOW |
| N13 | Glyphs needed | 13 glyphs | present via sprite | MATCH | - |
| N14 | Emoji accessibility | every emoji `aria-hidden` | `icon()` and `ext_cr_board.js:834` | MATCH | - |
| N15 | Type scale, spacing, radii | ranges | `-min/-max` tokens, `ext_cr.css:211-300` | MATCH | - |
| N16 | Shadow plus glow on a working tile | glow-soft AND shadow-raised | belongs to doc 02 slice | not examined | - |

## 4. Extras

| item | where | status |
|---|---|---|
| Emoji replaced by line icons, plus `icon style` (icons/emoji/text) and size knob | `ext_cr_boot.js` `icon()`, `ext_cr.css:489` | ruled: `reports/emoji-to-icons.md`, `reports/icon-config-knobs.md`. Answers doc decision 4: "emoji stay" is superseded by the owner |
| `--state-working`, `--glow-working` (green) | `ext_cr.css:160,195,383,410` | ruled by in-code comment only ("owner's explicit, repeated ask"); no report file records it. Ask the owner to confirm |
| `--state-pinned` (alias of `--text-dusk`) | `ext_cr.css:177,389` | ruled by in-code comment ("pin - blue"); no report |
| `--scrim` | `ext_cr.css:204,416` | unruled, harmless (replaces three hard-coded backdrops) |
| dark `--text-agent` `#C6B29B` | `ext_cr.css:349` | unruled; self-justified (2.6:1 otherwise vs the doc's own 4.5:1 floor) |
| `--text-dusk`, `--text-eyebrow`, `--line-dusk`, `--line-note` | `ext_cr.css` as above | unruled; not in doc |
| `--fill-action-solid` defined, unused | `ext_cr.css:394` | unruled, dead token |
| Model chip `.cr-model-chip` | `ext_cr.css` after the emoji block | unruled beyond commit `031c50c`; uses tokens correctly |
| Read-only CSS hide list | `ext_cr.css` tail | ruled by commit `950f746` (read-only remote mode) |

## 5. Fixes

**N3 theme control.** Direction: restore the doc gesture without losing the visible way back to auto. Way: in `choose(v)` (`ext_cr_board.js`, inside `buildThemeControl`, about `:2480`) make Light/Dark toggle to `'auto'` when pressed while already the explicit preference; leave the Auto button. Do NOT remove the Auto button (the owner asked for it). Test: structural test that the `buildThemeControl` source contains the toggle-to-auto branch; otherwise browser check.

**N4 working colour.** Needs an owner decision; recommend green everywhere. Way: `ext_cr_board.css:1628` and `ext_cr_detail.css:684,707,1307` use `var(--state-working)`; change the halo rgba in both keyframes (`ext_cr_board.css:1630-1634`, `ext_cr_detail.css:727-731`) to a `--pulse-rgb` token (28,145,99 light, 41,211,152 dark). Do NOT touch `--state-thinking` (still used by `--line-agent` adjacency and the agent glow). Test: extend `tests/test_state_color_parity_app.py` to assert the tile dot and spine dot read `--state-working`; red before the fix.

**N5 emoji-mode tint.** Direction: apply the doc filters only when the style is emoji. Way: add rules for `.tn-emo*` descendants `.ico-glyph` carrying the five doc filters and the five `.is-dark` ones, one `filter` per rule. Do NOT put `filter` on the SVG (it uses `color`). Test: CSS assertion contains `saturate(.62) hue-rotate(-18deg) brightness(.82)`; red now.

**N6 keyframe name.** Direction: one keyframe. Way: define `@keyframes tn-pulse` once in `ext_cr.css`; delete `cr-board-pulse` and `crd-pulse`; update every `animation:` reference (`ext_cr_board.css:1635`, `ext_cr_detail.css:140,685,1307,1984`). Test: grep test that `@keyframes tn-pulse` occurs exactly once.

**N7 floor.** Direction: raise to 10px, leave the 8px FAIL word (03:147). Way: `ext_cr_board.css:1139`, `ext_cr_detail.css:405,657,671,718` to 10px (the 14px badge may need `min-width:16px`). Test: CSS scan asserting no `font-size` below 10px except `.crd-mark*`.

**N9 tabular-nums.** Direction: one shared rule, not 39 edits. Way: in `ext_cr.css` add `font-variant-numeric: tabular-nums` to a shared selector list for the mono users, or add it to each rule via a `--font-mono` helper class. Do NOT apply it to Inter text. Test: scan that every rule setting `--font-mono` also has `tabular-nums`, with an allow-list; red now.

**N11 raw hex.** Direction: move the PTY palette to tokens (`--term-bg`, `--term-fg`, `--term-bar`) in `ext_cr.css` and read them in `ext_cr_term.css`. Leave `#tryNext` (classic sidebar, classic palette). Test: scan for bare hex outside `ext_cr.css` with an allow-list for `#tryNext`.

**N12 focus.** Way: `ext_cr_board.css` near `:736`, add `.tracker-next .cr-rail-search:focus-within { outline: 2px solid var(--line-focus); outline-offset: 2px; }`. Test: visual-only, browser check (Tab onto the rail search).

**N8, N10, N6 note.** N8: no change unless the owner wants a phone size in the doc. N10: not examined, optional.

**Token regression guard (no finding open).** No test pins the doc hex values (grep for `3A2A18` finds nothing in `tests/`), which is how A1 and A2 shipped. Add one test embedding the doc's dark surfaces and light state dots, comparing against `ext_cr.css`. Red test: revert one value to `#6E3711`.

## 6. Top 5
1. All foundation colour tokens match the doc in both themes; A1 and A2 are closed and nothing HIGH remains in this doc.
2. Working colour is inconsistent: rail, orb and state pill are green, the tile dot and spine dot are wheat (N4); needs an owner call.
3. The emoji icon style has no tint recipe, so decision 4 is unmet in the one mode that still uses emoji (N5); otherwise emoji are ruled out in favour of line icons.
4. The theme control lacks the doc's click-the-highlighted-side-to-return-to-auto gesture; it has a visible Auto button instead (N3).
5. Type hygiene: 9px and 8px text under the 10px floor and 39 mono rules without tabular numerals (N7, N9), and no test guards the token values.
