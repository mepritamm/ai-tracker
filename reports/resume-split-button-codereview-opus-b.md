# Code review B (opus): classic pane, board hero, read-only CSS, README

Scope: `ext_launch.js`, `ext_cr_board.js`, `ext_cr_board.css`, `ext_cr.css` and their tests. Mutants were run on a /tmp copy. No repo file was edited.

## Findings

**1. major: the hero split overflows the sidebar at icon scale ≥~140%. The browser check was never run.**
- Where: `ext_cr_board.css:1779-1781`. The content box is 124−17−1 = 106px (`:1748`, border-box).
- Repro, widths estimated (primary 10+12·scale+5+~42+10, caret 24):

  | `--ico-scale` | Split width |
  |---|---|
  | 1.0 | ≈103px |
  | 1.5 | ≈109px |
  | 2.0 (Config allows 200%) | ≈115px |

- Actual: the "Resume" text span can't shrink, so it spills 3–9px into the caret. The base button fit at every scale.
- The Implementation log marks the planned 100/150% browser check "NOT done".
- FIX DIRECTION: clip inside the primary. Do NOT widen the sidebar. Do NOT touch the shared `.tracker-next .cr-tile-action` rule.
- WAY: add after `:1781`:
  - `.tracker-next .cr-tile-sidebar .tsplit-primary{overflow:hidden}`
  - `.tracker-next .cr-tile-sidebar .tsplit-txt{min-width:0;overflow:hidden;text-overflow:ellipsis}`

  Then run the browser check at 100/150/200% and confirm `split.scrollWidth <= sidebar.clientWidth`.
- TEST: extend `test_hero_css_shrinks_the_split_inside_the_sidebar` to assert both rules. It is red now.

**2. minor: README is stale on the board.**
- `README.md:202`: "Auggie sessions keep **Open terminal to answer**" is wrong. The code shows "Open terminal" + "Open externally ↗", and `test_auggie_hero_keeps_open_terminal` asserts it. The same line has the typo "; The hero tile".
- `README.md:120`: "board tiles use the same native launcher" has been false since 40c5665. Only the hero's external item is native.
- FIX: wording only. L202: "…in the in-app terminal. The hero tile is …; an Auggie hero gets Open terminal + Open externally ↗." L120: "the board's hero tile offers it as its external item." TEST: none.

**3. minor: stale comments and a dead function in `ext_launch.js`.**
- `:1`, `:72` and `:381-400` still describe the "…here"/"↗ External …" buttons and "localOnly() + probe-and-latch, unchanged".
- `localOnly()` (`:11`) has no caller.
- `test_term_vt_client.py:112` indexes `"function localOnly"`, which first matches `ext_cr_term.js`, so it is already vacuous.
- FIX: re-point the comments to `trackerIsLocal`/`termExtAllowed`/`termExtDeny` (app.js) and delete `localOnly()`. No behaviour change.
- WAY: point that assertion at `"window.ExtLaunch = {"`.
- TEST: that edited assertion. It goes red if ext_launch.js lands after ext_vt.js.

**4. minor (same as base): the probe re-render uses a stale `d`.**
- Where: `ext_launch.js:425` `.then(() => render(d))`.
- Repro: a probe slower than one 2 s poll redraws the older note.
- WAY: `.then(() => render(lastD))`.
- TEST: in `test_tsplit_classic`, with the probe held pending, call `render({})` then `render({meta:{term_home_note:"new"}})` and resolve. Expect `pane._home` to contain "new". Optional.

**5. minor (known gap): a click that straddles a rebuild can be lost on the board too.** `renderBoard` rebuilds the hero split on every update. FIX: no code. The PR body names both board and classic.

## Sound
- **No backend change:** no `aitracker/*.py` in status.
- **Classic pane:**
  - The rebuild runs snapshot → innerHTML → build → restore. Menu and focus survive, and a changed `cur` is not restored.
  - A 403 calls `termExtDeny()` and re-renders without the external item. In-browser Resume/Open stay.
  - The external item uses resume/cwd by resumability. The 409 recreate path is unchanged.
- **Board:**
  - Resume emits `session:resume` and stops propagation.
  - The probe `.then` re-sets the same node.
  - `[role=menu]` is in the ignore list.
  - Read-only shows no split: the JS skip plus `html.tracker-readonly .tsplit`.
  - The capture-phase keydown stop keeps arrows and Escape from the board's j/k/Escape handler.
- **The `closest()` patch is not tautological.** It walks the real `tileBaseAttrs` selector string. Each of these mutants went RED:
  - Board: drop `[role=menu]`, drop `termSplitRestore(tsnap)`, disable the probe `.then`, drop `stopPropagation`.
  - Classic: no-op restore, no `render(lastD)`, no probe re-render, external always `resume`.
- **Rendering:** tiles have no stacking context, so the list paints over the next tile. The tokens have fallbacks in both themes.
- All 5 modules are green.

FIX FIRST: 1
