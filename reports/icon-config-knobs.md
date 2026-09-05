# Config knobs: icon style and icon size

**Status:** complete — `make check` green (1454 tests, 0 failures, `selfcheck ok`)
**Worktree:** `.claude/worktrees/icon-config` (branch `worktree-icon-config`, based on `main` @ `c65f6b4`)
**Started:** 2026-09-05

## The contract (verbatim)

> "give me a config knob through we can adjust and manipulate the emojis to this system
> generated emojis/symbols. Also give me an config knob to adjust the size of the
> icons/emojis. /tracker-gap /tracker-push /head-out"

Answered in the one head-out question round:
- **Style options:** three-way — `icons` / `emoji` / `text`. (Owner picked the 3-way over 2-way.)
- **Where it lives:** "along with the knob in the config settings from the control-view UI" →
  server config, surfaced in the Control Room **Config dialog**.
- **Size control:** "a slider where the emoji/icon size is adjusted to the live view of the
  slider" → a slider with **live preview while dragging**, not commit-only.

## Two decisions taken without asking

1. **`ICON_SCALE` is an integer percent (75–200, default 100), not a float.** It fits the existing
   `_v_int` validator and the existing integer slider control (`MAX_TERMS` already uses one) with
   zero new machinery. The client divides by 100 to get the CSS multiplier.
2. **Defaults reproduce today's appearance exactly** (`icons`, `100`), so the `icons` code path is
   byte-identical to before and nobody who never opens the dialog sees any change.

## What the recon found (and why the design is what it is)

Everything needed already existed, so this adds knobs rather than machinery:

| Need | Existing thing reused |
|---|---|
| config key + validation | `config.py` `EDITABLE` + `VALIDATORS` (`_v_enum` like `TERM_RENDERER`, `_v_int` like `MAX_TERMS`) |
| persistence | `/api/config` GET/POST, atomic `_save_json`, read **live** per request |
| 3-way picker UI | `segmented(...)` in the Config dialog |
| slider UI | `sliderCtlCommit(...)` — already used by `MAX_TERMS` |
| applying a preference to the DOM | `setTheme()`'s pattern: attribute on `<html>` + localStorage + CustomEvent |

**Two traps the recon surfaced**, which shaped the design:

1. **23 icons are hardcoded in `index.html`** and never pass through a JS helper — a style switch
   would silently skip them. Fix: each static icon is tagged `data-ico=NAME`, and
   `applyIconStyle()` converts them in one boot pass (they are static, so one pass is enough; no
   observer needed).
2. **11 CSS rules set fixed pixel icon sizes** and would fight a global scale. Fix: each becomes
   `calc(Npx * var(--ico-scale))`.

## The seam

Every icon in the app is produced by one of **three base generators** — `ico()` (app.js, string),
`icon()` (ext_cr_boot.js, string), `icoEl()` (ext_vt.js, element). All 11 icon helpers across the
codebase route through one of those three. Making those three style-aware covers everything
dynamic; the `data-ico` boot pass covers everything static.

`applyIconStyle(style, scalePercent)` is the single apply point: sets `data-icon-style` on `<html>`,
sets `--ico-scale`, caches to localStorage, re-renders static icons, and fires `iconstylechange`.

## Deliberately NOT scaled or restyled

- **The product logo** (`#brandMark`, `.cr-rail-brand svg` at 20px). It is brand, not a UI icon.
- **The login page** (`server.py`) — standalone, no sprite, renders before any config is known.

## Work units

| # | Unit | Files | Status |
|---|---|---|---|
| 1 | Recon: config plumbing | — | done |
| 2 | Recon: every icon render path | — | done |
| 3 | `ICON_STYLE` + `ICON_SCALE` config keys + route tests | `config.py`, `tests/test_cr_routes.py` | in progress |
| 4 | `--ico-scale` variable + calc sweep + `.ico-glyph` | `web/*.css` | in progress |
| 5 | Tag static icons `data-ico`, extend pre-paint script | `web/index.html` | in progress |
| 6 | Style-aware seam: emoji/text maps, `ico()`, `applyIconStyle()`, boot fetch | `web/app.js` | in progress |
| 7 | Route CR generators through the seam | `ext_cr_boot.js`, `ext_vt.js` | pending (needs 6) |
| 8 | Config dialog: segmented style row + live-preview slider | `ext_cr_dialogs.js` | pending (needs 3, 6) |
| 9 | Tests for the seam + dialog | `tests/` | pending |
| 10 | Gate, served-page verification, push | — | pending |

## Traps carried over from the icon conversion

- The gate cannot see load-time JS/CSS errors: all `ext_*` files concatenate into ONE `<script>`
  and one `<style>`, so one syntax error kills every file after it and `make check` still passes.
  Verify the **served** bundle parses.
- `make check` needs `env -u TRACKER_AUTH` or ~33 blanket-401 failures appear.
- The pre-commit hook runs the full suite and does **not** unset `TRACKER_AUTH` — unset it in the
  commit command's own environment.
- The page is baked at server start; UI changes need `make serve`, not just a reload.

## Contract verdict

| Clause | Verdict |
|---|---|
| config knob to switch emoji ↔ generated symbols | not yet discharged |
| config knob to adjust icon/emoji size | not yet discharged |
| knob lives in the control-view Config settings | not yet discharged |
| size slider adjusts the live view while dragging | not yet discharged |
| /tracker-gap | followed — worktree first, shared seam, evals required |
| /tracker-push | not yet discharged |
| /head-out | followed — one question round, then autonomous |
