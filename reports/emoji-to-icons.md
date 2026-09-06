# Emoji → standard line-drawn icons

**Status:** complete — `make check` green (1350 tests, 0 failures, 0 errors, `selfcheck ok`)
**Worktree:** `.claude/worktrees/icons-svg` (branch `worktree-icons-svg`, based on local HEAD `aadcae5`)
**Started:** 2026-08-31

## The contract (verbatim)

> "I would like to change the emoji to a standard drawings for the app, use the standard
> symbols instead of the emojis for the new control room UI /tracker-gap /tracker-push
> read claude.md spin up multiple agents with cheaper models such that we arent burning
> much context in this session"

Clause-by-clause verdict is at the bottom; nothing is marked discharged until proven.

## What this is

Replace **emoji** (colour pictographs: 🚩 🤖 📌 …) with **standard line-drawn symbols**
(monochrome 24×24 inline SVG, `stroke=currentColor`) across the app, with the new Control
Room UI as the emphasis.

**Plain typographic symbols already in use are NOT targets** — `✓ ✗ ▾ ▸ ▶ ○ ◆ ⚙ ⎇ ✎ ⧉ ⇕ ↑ ↓
✕ ☰ ⌕ ＋ ⚠ ▍ ✦ ‹ › ⤒ ⤢ ◧`. Those already *are* standard symbols; the ask is emoji → symbols,
so touching them would be scope the user did not request.

## The key finding: the seam already exists

`aitracker/web/ext_cr_boot.js:59` defines `GLYPHS` — a name → SVG-path map, rendered by
`icon(name)` (:74) as 24×24 `fill=none stroke=currentColor stroke-width=1.75`. Its own comment
cites the design doc:

> "Glyphs — 01-foundations.md *'Glyphs needed (not emoji)'*"

So the Control Room was **designed** to be emoji-free and the remaining emoji are leftovers.
This is a completion of the existing design, not a new mechanism.

Existing glyph names (13): `spark search chevron check alert bell branch panel redo edit
clock stop send`.

A second, older pattern also exists: a hidden `<svg class=brandsprite>` in `index.html:17`
holding `<symbol id=brandMark>`, consumed by **both** UIs as `<use href="#brandMark"/>`.

### Chosen architecture — one drawing set, not two

The sprite wins as the shared substrate, because it is the only one reachable from **both**
static HTML (classic dashboard markup) and JS (`<use href="#i-name">`), and it is already the
established cross-UI pattern for the logo.

1. **One sprite** in `index.html` holds every icon as `<symbol id="i-NAME" viewBox="0 0 24 24">`.
2. **`window.ico(name, cls)`** in `app.js` → `<svg class=ico><use href="#i-NAME"></svg>`.
   Must live in `app.js`: `page.py:12-17` concatenates `app.js` **first**, then every `ext_*.js`
   in *sorted* order, into one `<script>` — so `app.js` is visible to every `ext_` file but not
   the reverse. (A new `ext_icons.js` would sort *after* `ext_cr_*.js` and be undefined.)
3. **`ext_cr_boot.js`'s `GLYPHS` is retired** into the sprite using its path data **verbatim**,
   so Control Room icons stay pixel-identical. `icon(name)` then emits a `<use>` reference.
   This is what stops us shipping two competing drawings of the same icon
   (`conventions.md` rule 4).

## Emoji → icon mapping

Four of the Control Room's nine emoji need **no new drawing** — a glyph already exists.

| emoji | icon | new drawing? |
|---|---|---|
| ✅ | `check` | no — exists |
| ⚠️ | `alert` | no — exists |
| 🔔 | `bell`  | no — exists |
| 🚩 | `flag` | yes |
| 🤖 | `agent` | yes |
| 📌 | `pin` | yes |
| 💬 | `chat` | yes |
| 🧩 | `puzzle` | yes |
| ⏳ | `hourglass` | yes (kept distinct from `clock`) |

Classic-UI emoji additionally need: `sun moon bell-off search compass note heart diagram
desktop file hammer folder eye unlock terminal trash plus link` and `face-1..face-5`
(a mermaid journey-diagram happiness score).

## Work units

| # | Unit | Files | Status |
|---|---|---|---|
| 1 | Inventory, classic UI | `index.html`, `app.js`, `app.css`, `*.py` | done — 61 glyphs, ~26 true emoji |
| 2 | Inventory, control room | `ext_cr_*.js/css`, `ext_*` | done — 17 sites, 9 distinct emoji |
| 3 | Sprite + `ico()` + `.ico` CSS | `index.html`, `app.js`, `app.css` | **done** — 42 symbols + `brandMark`, XML-verified |
| 4 | Theme-token discovery for the tint rewrite | `ext_cr*.css` | **done** |
| 5 | Retire `GLYPHS` → sprite | `ext_cr_boot.js` | **done** — one drawing set now |
| 6 | Control-room call sites | `ext_cr_board.js`, `ext_cr_detail.js`, `ext_cr_dialogs.js` | in progress |
| 7 | Kill the `filter: hue-rotate` tint hack → `color:` | `ext_cr_dialogs.css`, `ext_cr.css` | **done** — both copies, tokens verified |
| 8 | Classic-UI call sites | `index.html`, `app.js` | in progress |
| 9 | Python-emitted 🔓 on the login page | `server.py:77` | in progress |
| 10 | Test + gate + live page-load check | `tests/`, browser | pending |

### Decisions taken along the way

- **Sprite over a JS path map.** The sprite is the only form reachable from *both* static HTML
  (classic dashboard markup) and JS, and it was already the established cross-UI pattern for
  `#brandMark`. `GLYPHS`' path data moved in **verbatim** — no redrawing — so the Control Room
  is pixel-identical to before.
- **`icon()` no longer returns `''` for an unknown name**; it returns a `<use>` that resolves to
  nothing. Verified none of its callers depended on the falsy return.
- **Tints are muted on purpose.** `ext_cr_dialogs.css` carried an owner ruling — *"theme harmony
  now wins over glyph identity"*, role differentiation deliberately faint. The `color:` tokens
  chosen preserve that intent rather than introducing loud status colours.
- **Not every emoji can become an icon.** `title`/`aria-label`/`alt`/`placeholder` attributes and
  `prompt()`/`alert()` strings are plain text — SVG is impossible there, so the emoji is simply
  dropped and the wording kept. Each such site is reported rather than silently changed.

## Round 2 — scope widened by the owner (2026-09-05)

> "use the standard buttons used for any apps instead of those emojis, please and get them
> working across the new control-view tab /tracker-gap /tracker-push /head-out"

Two decisions taken by the owner when asked (one round of questions, then an unattended run):

1. **Style: Feather / Lucide** — thin 1.8 rounded strokes, open shapes, 24×24. This is what the
   sprite already used, so it cost no redraw of the existing icons.
2. **Scope: convert the plain typographic symbols too** (`✓ ✗ ▾ ▸ ▶ ✕ ☰ ⌕ ⧉ ⤢ ⇕ ◧ ⤒ ✎` …), not
   just the emoji. Reason: SVG icons and font glyphs were sitting side by side in the same rows,
   which renders inconsistently across platforms. This supersedes round 1's "plain symbols are not
   targets" rule — that rule was right for an emoji-only scope and is wrong for this one.

Sprite grew from 37 → **55 icons** (+ `brandMark`) with 18 additions: `x chevron-down chevron-left
play circle diamond copy expand-vertical arrow-up arrow-down menu plus jump-top expand layout
keyboard download return`.

### Still deliberately TEXT, not icons

Not an oversight — each would break if converted:

| What | Why it stays |
|---|---|
| `●○·` in the mermaid journey meter | Interpolated into mermaid's `["…"]` quoted-label DSL; an SVG's `"` ends the label and corrupts the diagram source |
| `▶ ⚙ ✓ ⧖` in `app.js`'s prefix regex | Matches the **server's** plain-text `now_line`, emitted by `providers/*.py` |
| `▍` | The live terminal cursor — real text, not chrome |
| `$` | Shell prompt marker |
| Emoji inside code comments | Not rendered; they document the history of these decisions |

### The ⏳ that was hiding in the server

`providers/claude.py:431` and `providers/auggie.py:272` emitted `now_line = "⏳ waiting for your
answer"` — an emoji reaching the UI as text from the **Python** side, which every front-end scan
missed. Replaced with `⧖` (U+29D6, a mathematical symbol, same block as the already-kept `⧉`), and
`app.js`'s prefix-strip regex updated in lockstep. `tests/test_icons.py` whitelists `⧖` with a
comment pointing at that coupling.

## The one that mattered: an XSS invariant broken by the icon conversion

`tests/test_term_vt_client.py:2661`
`test_identity_reaches_the_row_only_through_textcontent_and_the_title_property`

The terminal-row code has a deliberate rule: a row's **identity** — session title, cwd, model,
effort, all user- or session-derived strings — may reach the DOM only via `textContent` or the
`.title` property, never `innerHTML`. That is what stops a crafted session title from injecting
markup.

Rendering an icon needs markup, and `ico()` returns a **string**, so the conversion sweep did the
obvious thing and switched those sites to `.innerHTML`. Two of them concatenated a live value
straight into HTML:

```js
modelBtn.innerHTML  = model  + " " + ico('chevron-down');   // injection vector
effortBtn.innerHTML = effort + " " + ico('chevron-down');   // injection vector
```

**The fix is not to edit the test.** `ext_vt.js` gets a local `icoEl(name)` that builds the icon as
a real DOM **element** via `createElementNS`, so each site sets its text with `textContent` and then
`appendChild`s the icon — markup for the icon, text for the value, invariant intact.

Worth stating plainly: a purely cosmetic change reached a security boundary, and the only thing that
caught it was an existing test asserting an invariant that no amount of looking at the diff would
have revealed. The failing assertion was the feature working.

## Bugs this change introduced, and how they were caught

Worth recording because all three share one root cause and one detection method.

1. **`icon()` no longer returns `''` for an unknown name.** That falsy return was load-bearing:
   `ext_cr_dialogs.js` relied on it to fall through to `fallbackGlyph()`, which held the close
   cross. With `icon()` always truthy, the fallback stopped firing and **every dialog close button
   rendered blank** — there is no `i-close` symbol. Fixed by adding `i-close` to the sprite using
   the project's own existing path data (`M6 6l12 12M18 6L6 18`).
2. **Invented icon names.** An agent converting `ext_cr_board.js` wrote `glyph('awaiting')`,
   `'landed'`, `'config'`, mistaking *state* names for *icon* names. None existed.
3. **`buildChrome('rename', …, '✎')`.** `✎` is a plain typographic symbol, so the rule "don't touch
   plain symbols" said leave it — but `buildChrome` stopped rendering its argument as a character
   and started treating it as an icon *name*, so `✎` became a dangling reference. A correct rule
   applied to a changed call site produced a wrong result.

**The common failure mode: a missing sprite name renders nothing at all** — no exception, no console
warning, no layout shift. It cannot be caught by reading a diff or by `make check`. The only reliable
detection is mechanical: extract every referenced name, extract every defined `<symbol>` id, and diff
the two sets. That is why unit 10 ships that check as a permanent test rather than a one-off command.

A fourth, different bug: the rewritten `icon()` initially stamped `class="cr-glyph"`, and
`ext_cr_dialogs.css:106` sets `.cr .cr-glyph{display:block}` — which would have silently turned every
inline icon into a block element. Reverted to a bare `<svg>`, matching what the call sites were
tuned against.

## Files the first inventory missed

The opening inventory pass covered `index.html`, `app.js`, `app.css` and the Python files, and a
second pass covered `ext_cr_*`. Both still missed live emoji, found only by a final repo-wide scan:
`ext_cr_term.js` (Config/Theme toolbar buttons, the theme toggle), `ext_vt.js` (theme toggle, mouse
on/off), `index.html:148` (`🔀 Pull requests`), and `app.js:568` (the mermaid journey face map).
Lesson: trust the mechanical scan over any agent's "done" report, including a scan you already ran.

## Traps recorded for this repo

- **The gate does not catch load-time JS/CSS errors.** All `ext_*` files are concatenated into
  ONE `<script>`/`<style>`; a throw or a stray `*/` in any one file silently kills every file
  after it and `make check` still passes. A real browser load check is mandatory here.
- `make check` needs `env -u TRACKER_AUTH` or it yields ~33 blanket-401 failures.
- One known-flaky `term_vt` backstop failure under full-run load; passes in isolation.
- The page is baked at server startup — UI changes need `make serve`, not just a reload.
- `git commit` here runs the full ~1300-test gate (180–380s); Bash needs a >2min timeout.

## Verification performed

The gate alone is not sufficient here — every `ext_*.js` is concatenated into ONE `<script>`, so a
syntax error in one file silently kills every file after it and `make check` still passes. So the
served page itself was checked:

| Check | Result |
|---|---|
| `env -u TRACKER_AUTH make check` | **1350 tests, 0 failures, 0 errors, `selfcheck ok`** |
| `node --check` on the **served** 811 KB bundle (app.js + all `ext_*.js` as the browser gets it) | parses |
| Dangling `#i-NAME` references across all sources | **none** (56 defined, 52 referenced) |
| Dangling references on the **served** page | **none** |
| Sprite XML well-formed, no duplicate ids | pass |
| CSS brace / comment balance across all 10 stylesheets | 1412/1412, 319/319 |
| Emoji in live code | none — 4 remain, all inside comments |
| Blank-button audit | no empty buttons; 17 empty spans are runtime-filled counters |
| Login page (separate, no sprite) | inline unlock SVG, zero emoji |

Browser check was **not** possible — the Chrome extension was not connected this session. The
served-bundle parse is the mechanical stand-in for it; a human should still eyeball the control room
once. See "Parked".

## Contract verdict

| Clause | Verdict |
|---|---|
| "change the emoji to a standard drawings for the app" | **discharged** — all live-code emoji replaced app-wide, incl. the Python-emitted `⏳` and the login page |
| "standard symbols instead of the emojis for the new control room UI" | **discharged** — control room drives off the shared sprite; `GLYPHS` retired into it |
| "use the standard buttons used for any apps" | **discharged** — Feather/Lucide style, chosen by the owner |
| "get them working across the new control-view tab" | **discharged** — `ext_cr_*` all converted; 3 blank-icon bugs found and fixed |
| "/tracker-gap" | followed — worktree first, landed at the shared seam, evals shipped (`tests/test_icons.py`) |
| "/tracker-push" | see push section below |
| "/head-out" | followed — one question round, then autonomous |
| "read claude.md" | done — worktree discipline + the no-fork rule drove the architecture |
| "multiple agents with cheaper models, don't burn context" | done — 27 subagents; haiku for mechanical sweeps, sonnet for implementation/tests, opus for SVG geometry and the security fix |

## Parked for the owner

1. **No browser verification.** The Chrome extension was not connected, so nothing was confirmed
   visually. Everything is proven mechanically (bundle parses, no dangling refs), but the icons have
   never actually been *seen*. Run `make serve` and look at the control room.
2. **`i-x` and `i-close` are the same drawing** under two names — kept for call-site readability
   (`x` = failed, `close` = dismiss). Collapse to one if that bothers you.
3. **Four emoji remain in code comments** (`📌 🔍 🚩 🤖`). Not rendered; they document the history of
   these decisions. Say the word and they go.
4. **`⧖` (U+29D6) font support.** It replaced `⏳` as the server's "waiting" prefix. It is a normal
   typographic symbol, but it is less universally present in fonts than the `▶ ⚙ ✓` beside it. If it
   shows as a box anywhere, swap it for a word.
