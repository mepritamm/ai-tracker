# Progress spine: what shipped vs. what the redesign docs specify

Source of truth for the "as designed" column:
`~/Downloads/app-ui-redesign-request 2/project/design_handoff_control_room/`
— `01-foundations.md` (tokens, motion) and `03-detail-view.md` (the spine, lines 102–160).

The user asked for **full motion** and for this delta to be written down. Everything
below is a deliberate deviation, not drift.

## 1. Motion — the big one

**Docs:** the spine has exactly **one** animation. `01-foundations.md:215–226` defines
`tn-pulse` (2.4s) and applies it to a single 7px dot on the running segment. The state
table at `01-foundations.md:205–209` gives every other state `Motion: none`. The running
segment's glow and its 2px wheat leading edge are described as **static**.

**Shipped:** the dot pulse is unchanged, plus four additions:

| Addition | What it does | Why it is safe |
|---|---|---|
| `crd-seg-in` | segments fade + scale in, staggered ~35ms | gated on the segment set actually changing (see §5) |
| `crd-shimmer` | 2.8s light sweep across the running segment | `pointer-events:none`, `z-index:0` so it never covers the label or blocks clicks; theme-aware via `--crd-shimmer` |
| `crd-edge-breathe` | the leading edge breathes | shares the `--motion-pulse-duration` (2.4s) clock |
| `crd-now-pulse` | the NOW tick + word pulse | same 2.4s clock |
| `transition` | `flex-basis` on segments, `left` on markers (0.4s) | suppressed while dragging, so a pan tracks the finger |

The three pulses deliberately share the doc's own 2.4s token so they read as **one
heartbeat**, not three competing rhythms.

**Cost:** this is a permanently animating page — the shimmer and the two pulses run
whenever a session is live. That is the trade the "full motion" choice buys. Every one
of them is switched off under `@media (prefers-reduced-motion: reduce)`, matching the
pattern the docs already set for the dot, and pinned by a test that fails if a future
animation is added without an off-switch.

## 2. The collapse caret — removed, where the docs kept it

**Docs:** `03-detail-view.md:110` puts a `▾` in the spine header, and `:172–181`
establishes that panels collapse — but the spine is explicitly **not** one of them; the
chevron is described as a disclosure triangle that is never toggled closed.

**Shipped:** removed outright. In the code it was a `<span class="crd-spine-chevron">`
with no `data-act` and no handler anywhere — a control that *looked* collapsible and did
nothing, which is worse than either having it work or not having it. Its orphaned CSS
rule went with it.

## 3. The time window — net new, not in the docs at all

**Docs:** no zoom, pan, scrub, or filter is specified anywhere for the spine. The time
range is fixed at the full session (`03-detail-view.md` header: "41m elapsed").

**Shipped:** span chips (`All · 15m · 1h · 6h · 24h`) plus drag-to-pan.

The docs' model works because they assume a ~41-minute session. It falls apart on a long
one: marker position is `(t - t0) / span`, so on a real 2192-hour session on this machine
(`63f5fe77`) **all five** recorded events landed below 4.75% and the 2%-collision nudge
stacked them into an illegible pile at the left edge. That is the defect in the
screenshot, reproduced.

Two honesty rules the window keeps, in the spirit of the existing equal-width fallback:
- The window rescales the **time axis** (markers) always, but only clips **bar
  segments** when per-todo timings actually exist. Without timings the bar has no time
  meaning, so it is left whole rather than filtered on a number nobody recorded.
- Pending todos disappear once the window is panned off the live edge — "to go" is a
  claim about the future, and what was pending two hours ago is not in the log.

## 4. Accessibility — corrected against the docs

**Docs:** `03-detail-view.md:158–160` says the spine is `role="img"` with a summary
`aria-label`, *and* that "individual segments remain focusable buttons".

Those two sentences contradict each other: `role="img"` makes assistive tech ignore the
subtree, so the segment buttons — and now the window chips — would be unreachable.

**Shipped:** `role="group"` with a static label, and the summary sentence moved into a
visually-hidden `aria-live="polite"` region. Same information announced, controls stay
reachable. On phone the chips meet the ≥44px hit-target rule this file already mandates.

## 5. The trap this design walks into, and the guard

The detail view re-renders **every 2 seconds** from the poll. An entry animation that
re-runs on every render turns "alive" into a strobe. `renderSpine` therefore stamps a
signature of the segment set on the bar and only restarts the animation when that
signature changes. There is a test asserting the guard exists.

The same 2s repaint is why the drag listeners are bound to a `.crd-spine-track` wrapper
rather than to the bar or gutter: those two have their `innerHTML` replaced on every
poll, and a listener or pointer capture held on a replaced child would die mid-drag.
