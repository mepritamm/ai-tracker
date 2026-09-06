# xterm as default + per-terminal renderer switch — working record

Branch `worktree-xterm-default-and-switch`, based on `8038cb2`.
Skills: `/tracker-gap`, `/tracker-push`.

## The contract, verbatim

> can we keep the xterm as default and the in-browser on-demand and whats the command from make file
> with make tunnel ?
> treat this session as orchestrator with multiple agents with cheaper models

| Clause | Verdict |
|---|---|
| xterm as default, grid on-demand | **discharged** — default flipped, plus a per-terminal toolbar switch so grid is one click away in both the modal and standalone views |
| `make tunnel` explained | **discharged** (below) |
| Orchestrate via fan-out to cheaper models | **discharged** — 10 agents, sonnet and haiku only, no opus leg |

## `make tunnel` — the answer

```
TRACKER_AUTH="user:pass" make tunnel
```

1. Refuses without `TRACKER_AUTH` (the URL is public) and without `cloudflared`.
2. Frees `TUNNEL_PORT` (default **8790**) and kills any previous `cloudflared` for it.
3. `TRACKER_AUTH=… PORT=8790 HOST=127.0.0.1 nohup python3 -m aitracker` → `/tmp/aitracker-tunnel.log`
4. `nohup cloudflared tunnel --url http://localhost:8790` → `/tmp/aitracker-cf.log`
5. Polls that log up to 40s for `https://….trycloudflare.com` and prints it.

`make stop` tears down both. It binds loopback and lets Cloudflare do the exposing — which is why
the terminal still works over it: `TRACKER_AUTH` is set, and that is the terminal's requirement for
anything reachable off-loopback.

## The decision, and why it needed asking

Flipping the default is one literal in `config.py`. But the investigation found it is **not** a
drop-in, and it contradicted a hard project rule — both worth the user's call rather than mine.

**xterm.js is genuinely better at:** wide characters (CJK/emoji — the grid emulator treats every
codepoint as exactly one display column, its own documented gap); **true colour** (the server parses
256-colour and RGB, but the grid client only styles the 16 ANSI colours — a real gap found during
this investigation and documented nowhere); native VT fidelity generally.

**xterm.js loses:**
- **repaint on attach/reconnect** — `/api/term/raw` only tees bytes emitted *after* the stream opens,
  so a second tab or a reconnect starts on a **blank pane** until the next write;
- server-backed scrollback, the "▼ new output" badge, the custom scrollbar;
- **mid-session server notices** — they ride the parsed `/api/term/screen` frame, and the raw path
  has no JSON envelope. **This gap was not in the existing "KNOWN GAPS" comment.** (The one-time
  notice at open time rides the POST response and is unaffected.)
- the mouse toggle is inert there (xterm owns its own mouse; drag-to-select still works);
- essentially all execution-level test coverage points at the grid path.

**User's decision:** flip the default **and** add a per-terminal toolbar switch, so grid is
on-demand and nobody is stuck behind a gap. Plus: fix the grid renderer's true-colour gap.

## Fan-out

| Leg | Model | Owns | State |
|---|---|---|---|
| flip `TERM_RENDERER` default + its tests | sonnet | `config.py`, `tests/test_term_vt.py` | running |
| per-terminal renderer switch in the shared toolbar | sonnet | `web/ext_vt.js`, `web/ext_vt.css`, `tests/test_term_vt_client.py` | running |
| docs + conventions rule 2 amendment | sonnet | `README.md`, `.claude/rules/conventions.md` | **done** |
| true colour in the grid client | — | `web/ext_vt.js` | queued behind the switch (same file) |

## Result — docs + rule 2 (sonnet) — LANDED

Rule 2 amended so the *intent* survives the change rather than being quietly contradicted. Retained:
zero Python dependencies, committed files never fetched or built at runtime, explicit approval to
add. Retired: "off by default" as the protection. Promoted in its place: **lazy loading** — a
vendored asset must be fetched only when the feature that needs it activates, never baked into every
page load. xterm.js is ~480KB and is still fetched only on first terminal open via
`_loadXtermAssets()`. A parenthetical records that the default flipped by explicit decision, so a
future reader does not read it as drift.

README: the prerequisites line, the terminal bullet and the repo-layout line all rewritten, with the
xterm-vs-grid trade-off stated honestly — including that switching *to* xterm shows a blank pane
until the next write. The agent correctly declined to restate the mouse-reporting spec it could not
independently verify, adding only the grid-only scoping note it was given as verified.

## Result — default flipped (sonnet) — LANDED

`aitracker/config.py:114-129`:

    TERM_RENDERER = os.environ.get("TRACKER_TERM_RENDERER", "xterm")
    if TERM_RENDERER not in ("grid", "xterm"):
        TERM_RENDERER = "grid"

The two cases used to be indistinguishable because both landed on the same literal. They are now
different questions, answered differently and deliberately:

- **unset** → `xterm`: "no opinion, give me the new best default".
- **garbage/typo** → `grid`: user or environment error, a different question, and it should not
  silently drop someone onto xterm's accepted gaps (no repaint on reconnect, no server-backed
  scrollback, no mid-session notices). It falls to the more defensive renderer instead.

The comment now carries the reasoning and a warning — *"This is a decision, not an accident: don't
'fix' it to match the unset default without re-reading this comment"* — and the stale justification
("so nothing changes for existing users until they opt in") is gone rather than left standing.

Tests renamed so they state the new truth instead of becoming landmines:
`test_default_is_grid_when_unset` → `test_default_is_xterm_when_unset`;
`test_garbage_value_falls_back_to_grid_rather_than_breaking` →
`test_garbage_value_falls_back_to_grid_not_the_new_default`, which doubles as the pin on the
decision above. RED check: `AssertionError: 'grid' != 'xterm'` against the pre-change config.
Suite: **983 tests, OK, `selfcheck ok`.**

## Result — per-terminal renderer switch (sonnet) — LANDED

| Site | What |
|------|------|
| `ext_vt.js:291` | `buildToolbar()` gains a 5th `rendererSwitch` param and builds one `.vtzoombtn.vtrendererbtn` (`role="switch"`, `aria-pressed`, keyboard-activatable) — the same shared-toolbar pattern as the mouse toggle, never duplicated per renderer |
| `ext_vt.js:1970` | `switchActiveRenderer()` — `activeTerm.destroy()`, rebuild `Cls` into a dedicated wrap against the SAME `activeTty`, then **re-wire** `activeBar.getInput` to the new terminal rather than recreating the ContextBar |
| `ext_vt.js:2265` | `mountRenderer()` — the standalone equivalent; `boot()` now builds the chrome once and calls it for both the first mount and every later switch |
| `ext_vt.css:237` | `.vttermwrap` exists because the constructors do `container.innerHTML = ""` — a wrap distinct from the modal body is what stops the ContextBar and notice/fork chrome being wiped on switch |

`openNewTab()` needed no change: it already reads the module-level `activeRenderer`, which the switch
updates, so a later "⤢ New tab" carries the currently active renderer. The initial-choice lines are
untouched — the server still owns the default and the client still never decides it.

The control's `title`/`aria-label` state the blank-pane asymmetry (to xterm: nothing until the next
write; to grid: instant repaint) — in the UI, not just a code comment. No host or viewport gate.

Tests: `TestRendererSwitchControl`, 11 tests; RED check 9/11 against the pre-change file (the other 2
are regression guards expected to hold either way). Suite: **994 tests, OK, `selfcheck ok`.**

**Smell worth recording:** the agent had to read the new interface via `arguments[2]` instead of a
named parameter, because ~20 pre-existing tests locate function bodies by the literal signature text
`function Terminal(container, ttyId) {`. That is tests dictating implementation shape — a mild
version of the same over-pinning problem this project keeps hitting from the other direction. Flagged
for the review pass; not blocking.

## Result — true colour in the grid renderer (sonnet) — LANDED

Wire shape verified from the server rather than assumed: each run is
`[start, end_exclusive, sgr_param_string]` (`term_vt.py:395,469-495`), the string carrying resolved
params like `"38;5;208"` / `"38;2;255;0;0"` built by `Screen._recompute_code`
(`term_vt.py:999-1019`) from `Screen._sgr` (`:1056-1082`).

Client: `_byte255` (`ext_vt.js:132`) strict `/^\d+$/` + 0-255 range check; `_stdColorClass` (`:143`)
for indices 0-15; `_cubeLevel`/`_256Rgb` (`:150-158`) with the standard xterm formulas rather than a
256-entry table; `sgrRunClass` rewritten to an index-based loop so it can consume `38`/`48`'s
variable-width sub-params, returning `{cls, style}`; `_paintRow` emits `style` only when non-empty.

Suite: **1005 tests, OK, `selfcheck ok`, gate run twice with no flakes.**

## Adversarial review — colour + security (sonnet)

**Security HOLDS**, and it was attacked properly: quote/`<`/`>`/NUL/newline injection,
`38;5;1" onmouseover="alert(1)`, CSS-property injection shapes, **Arabic-Indic digits** `١٢٣`
(confirming by execution, not memory, that JS `\d` is ASCII-only), `+5`/`05`/`5.0`/`1e2`/`Infinity`/
`-1`/empty, and a **100,000-digit token** (0.1s, no hang). Every case produced escaped plain text or
a style built solely from fixed literals and range-checked integers. No attribute injection, no CSS
property injection.

Also confirmed by execution: the cube/greyscale palette matches xterm exactly for indices
16/21/51/196/231/232/243/255; the rewritten `sgrRunClass` is **byte-identical to the old one across
232 cases** (every classic code plus 200 seeded random combinations); variable-width `38`/`48`
consumption is correct including truncated and back-to-back sequences; and reverse video composes as
claimed (inline `style` overrides `color`, `.vtr` still supplies `background`).

**REFUTED — one real, common-case defect.** `_stdColorClass` emits `vtg100`..`vtg107` for bright
**backgrounds** (`48;5;N`, N in 8-15). **Those CSS rules do not exist**, so the background is
silently dropped: `_paintRow("hi", [[0,2,"48;5;9"]])` → `<span class="vtg101">hi</span>` renders with
no background at all. `48;5;9` is ordinary — delta/lazygit/tmux themes emit it routinely.
The audit also found `.vtg40/.vtg45/.vtg46/.vtg47` missing from the classic path (pre-existing).

Why it shipped: `test_256_colour_low_index_reuses_the_existing_ansi_class_path`
(`tests/test_term_vt_exec.py:1090`) exercises only **foreground** (`38;5;3`, `38;5;12`) and never
`48;5;N` for any N in 0-15. The neighbouring field — `isBg` — is never perturbed, so the test would
pass even if that whole branch were deleted. The same narrow-assertion shape this project keeps
finding.

Fix dispatched, and the important part is not the CSS patch: a **structural test** that enumerates
every class name the JS can emit and asserts each has a matching rule in `ext_vt.css`. That catches
the family, not the instance.

## Adversarial review — renderer switch lifecycle (sonnet): DO-NOT-SHIP as-is

**The leak, proven under Node with a mocked DOM / EventSource / ResizeObserver.**
`XtermTerminal.attach` (`ext_vt.js:1544-1551`) builds nothing synchronously — it defers everything
behind `_loadXtermAssets().then(function () { self._build(); })`. `_build()` (`:1553-1605`) is where
`this.term`, `this._ro` and the `window` resize listener are actually created. Neither `_build()` nor
`destroy()` (`:1643-1648`) has a "was I destroyed while waiting?" guard — **even though this file
already has exactly that pattern** in `ContextBar._destroyed` (`:1952/1955`).

The new switch paths call `destroy()` synchronously and immediately construct the replacement,
without waiting for or cancelling a pending asset load. So: switch to xterm, switch back before the
~480KB bundle lands → `destroy()` is a clean no-op (everything is still `null`) → the deferred
`_build()` fires later **on the destroyed instance**:

    term1.term set (a live xterm.js instance on a destroyed object)? true
    term1._ro (ResizeObserver) set on the destroyed instance?        true
    window resize listeners LEAKED after destroy:                    1
    ResizeObserver instances LEAKED after destroy:                   1
    that leaked RO ever disconnected?                                false

One more of each per repetition, permanently, for the life of the tab — plus xterm.js's own
cursor-blink timer, never `dispose()`d.

**My default flip is what makes this ordinary rather than exotic.** xterm is now what a brand-new
session gets on its very first terminal open, so the async-load window is hit by essentially
everyone; the pane is documented to sit BLANK during it; and the switch button is right there for an
impatient user to tap again. The shipped suite is green and **would stay green with `destroy()`
deleted entirely** — `TestRendererSwitchControl` is pure source-text matching, and
`test_term_vt_exec.py` (the only module that executes anything) has **zero** references to
`XtermTerminal`, `switchActiveRenderer`, `mountRenderer` or `_loadXtermAssets`.

**Stale comments the flip invalidated** (`term_vt.py`, untouched by the diff): `:2712` still states
the default is `"grid"` — and that is the comment `config.py` points to as authoritative; `:2820-2824`
justifies lazy-loading the vendored assets *because* grid is the default, which is now backwards.
`bootStandalone`'s `.catch(() => boot("grid"))` also hard-codes the old default as its
network-failure fallback.

**Claims that HOLD, verified rather than restated:** ContextBar re-wiring (its only terminal
reference is `getInput`, read fresh in `_focusTerminal`; the model switcher goes through
`/api/term/inject` keyed by `ttyId`, not the terminal object at all); `.vttermwrap` containment (fork
chip and status live in the modal header, notice and bar are siblings of the wrap, so
`innerHTML=""` only ever hits the wrap); standalone first-mount, `?renderer=` and network fallback;
`arguments[2]` is the correct index for both constructors; no viewport gate on the control, and the
four toolbar buttons come to ~175px against a 375px viewport.

**On `arguments[2]`, the reviewer's opinion — which I share:** the tests are the problem, not the
workaround. ~20 assertions locate function bodies by the literal string
`function Terminal(container, ttyId) {`, coupling test infrastructure to source *formatting*, so an
ordinary refactor breaks dozens of tests none of which are about it. The extraction helper should
match a prefix or up to the first `{`.

## Result — background colours, and what the structural test immediately caught

The CSS patch was the small half. The **structural test** — enumerate every class the JS can emit,
assert each has a matching CSS rule — found a **second, independent** gap nobody had reported:

`sgrRunClass`'s direct-code branch only matched `40-47`, so **direct aixterm bright-background codes
`100`-`107` produced no class at all**. That is the *more common* real-world path: the server stores
those codes VERBATIM rather than normalising them to `48;5;N` (verified at `term_vt.py:1093`,
`Screen._sgr`). So bright backgrounds were invisible via two unrelated routes.

Fixes: `ext_vt.js:173-181` accepts `100-107`; `ext_vt.css:364-384` adds `--vt-black-bg` /
`--vt-violet-bg` / `--vt-cyan-bg` / `--vt-white-bg` tokens with a `:root` + `html.light` split
mirroring app.css, and `:406-413` defines all eight background families, bright paired with classic
and a comment saying the approximation is deliberate.

RED evidence, each half independently: CSS unfixed → the exact 12-class list
(`vtg100`-`vtg107`, `vtg40/45/46/47`); JS unfixed → *"produced NO class at all for
['100'…'107']"*.

**Same bug in the sibling file, found because the fixer looked.** `ext_run.js`/`ext_run.css` (the
Tier 2 "Run a command" view) had both halves too — `.a41`-`.a44` only, and the same `40-47`-only JS
branch. Fixed the same way, with the structural test **ported** to `tests/test_term_run.py` so both
files are protected. New tokens are `--rn-*`-prefixed so the two files' custom properties cannot
collide in the shared `:root`.

Suite: **1009 tests, OK.**

## Result — the destroy-race leak, closed

`ext_vt.js:1525-1532` sets `this._destroyed = false` in the constructor, mirroring
`ContextBar._destroyed` (`:1807`/`:1972`) rather than inventing a new pattern; `:1571-1574` bails out
at the top of `_build()`; `:1664-1673` sets the flag **first**, unconditionally, in `destroy()`.

What `destroy()` now guarantees:
- **build still pending** — the deferred `_build()` becomes a no-op, so no xterm.js `Terminal`, no
  `ResizeObserver` and no `window` listener is ever created for a destroyed instance;
- **build already ran** — unchanged, and now *confirmed by execution*: `es.close()`,
  `_ro.disconnect()`, `removeEventListener("resize", …)` and `term.dispose()` all fire.

New executed tests, `TestXtermSwitchDestroyRace` — the reviewer's exact repro, **10 repeated
switches with counters asserted at zero each time**, and the healthy build-then-destroy path. RED
check reproduced the original leak precisely (`term.term must stay null on a destroyed instance`;
`repetition 0 leaked a resize listener`).

The standalone `.catch(() => boot("grid"))` fallback was **kept** and documented: it fires only when
the server cannot be asked, and grid is the safer answer for the same reason `config.py` falls back
there — repaint on reconnect, server-backed scrollback, mid-session notices.

**Test infrastructure fixed rather than worked around.** `_function_body` now matches by prefix
(stripping a trailing `") {"`), which transparently repaired **16** existing call sites with no edits
to them; 5 raw `.index(...)` uses and 1 `assertIn` were updated directly. The
`Terminal`/`XtermTerminal` substring hazard was checked explicitly, not assumed. With the helper
relaxed, `arguments[2]` became a proper named `rendererSwitch` parameter in both constructors.

Worth recording: the agent disclosed **two bugs in its own mock** found during development — `_ro` is
`undefined` rather than `null` before `_build()`, and `removeEventListener` must key on the listener
reference rather than a counter to mirror real DOM semantics. Both were fixed *before* the RED check,
which is what makes that check worth anything.

## Verification ledger

**1012 tests, `selfcheck ok`.** Final gate running twice before push.

### What shipped

| | |
|---|---|
| **xterm is the default** | `config.py`; unset → xterm, garbage → grid (deliberately different questions, documented) |
| **Renderer switch per terminal** | shared toolbar, both mounts, ContextBar re-wired, blank-pane asymmetry stated in the control itself |
| **True colour / 256-colour** | grid renderer now honours what the server always parsed; XSS surface attacked and holds |
| **Bright backgrounds** | were invisible via **two** independent routes, in **two** files; both fixed, both now covered by a structural test |
| **Destroy-race leak** | closed, with the executed coverage the switch feature never had |
| **Docs + rule 2** | amended so lazy loading, not "off by default", is the binding invariant |

### Parked

1. The reviewer noted `.vttoolbar` has no `flex-wrap`/`overflow-x` safety net. Four buttons measure
   ~175px against a 375px viewport, so nothing clips today — but it is fragile rather than provably
   fine, and a fifth control would be the one to break it.
2. `tests/test_term_vt_exec.py` still has no coverage of `switchActiveRenderer`/`mountRenderer`
   themselves; the new tests cover the `XtermTerminal` lifecycle they depend on, not the switch
   orchestration.
