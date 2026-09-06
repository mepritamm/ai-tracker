# Control Room ⟷ Dashboard: terminal control parity

**Contract (verbatim, from the user):**
> "can you do an adversial review on all the buttons for all the terminals and make sure that its
> accurately wired up to the current set of buttons that are actively working in the dashboard view.
> the end goal is to have the similar capability of the current manage terminals in the dashboard UI
> to the new control-view UI"
>
> "make sure all the control-room view should be wired to the current/existing shared functionality
> which is already there for the current/dashboard type UI, the only thing diff is the view and UI and
> the rest and the entire backend is similar or larger, and most of it needs to be in the shared. the
> idea is one shared-backend helping the entire app with 2 different views or UI"
>
> "do an adversial review and make sure that you address all the issues you found in there"

**Decisions taken (head-out, one question round):** review + fix + push; parity via the SHARED SEAM
(one policy, two chromes); a button wired to a non-existent/wrong target gets wired to the real one.

**Assumption stated:** the shared seam is the terminal ACTION POLICY (`window.ExtVT.term`), not the
dialog chrome. The two views legitimately render different chrome (body-level `.overlay` vs the CR
dialog stack); merging the chrome is a large risky refactor with no correctness payoff. What was
genuinely forked — and had already drifted — is the policy behind the buttons.

## Findings (adversarial pass, dashboard `ext_vt.js` vs control room `ext_cr_*.js`)

| # | Severity | Finding | Status |
|---|---|---|---|
| F1 | **CRITICAL** | "Close all" was a **silent no-op** in the Control Room. `ext_cr_dialogs.js` called `payload.onCloseAll()` with no arguments; `ext_cr_term.js`'s `_closeAllTerminals(terminals)` iterates `(terminals \|\| [])` → empty → resolved → killed nothing. The documented payload contract itself said `onCloseAll()`, so both sides agreed on a contract that could not work. | FIXED |
| F2 | HIGH | No 500ms arm guard on the confirm. Dashboard swallows the second click of a double-click (`_armGuardActive`); CR revealed the confirm in the box the first button just vacated with no guard → double-click kills everything with the warning never shown for a frame. | FIXED |
| F3 | HIGH | No `ev.repeat` keydown guard. A held Enter auto-repeats at ~30ms and activates the focused confirm — a timing guard alone only postpones the kill. | FIXED |
| F4 | MEDIUM | No latch during a kill. Dashboard disables every panel button for one destructive click at a time; CR allowed a double-tap to fire two kills at a list about to be redrawn. | FIXED |
| F5 | MEDIUM | No reap settle. A pty leaves `/api/term/list` when the reader thread notices EOF, not when `/api/term/close` returns. CR refreshed on the response, so the killed row persisted. | FIXED |
| F6 | MEDIUM | Killed rows never disappeared: `_refreshRunningList()` updates `st.running` + the badge only — it never repaints the open dialog. | FIXED |
| F7 | MEDIUM | Kill failures were silent. `onKill: _killTerminal` was passed raw; the returned promise had no `.catch` → unhandled rejection, no toast. Dashboard toasts "Couldn't close that terminal". | FIXED |
| F8 | MEDIUM | Close-all failures swallowed by a per-request `.catch(function () {})`. Dashboard reports "N of M failed". | FIXED |
| F9 | MEDIUM | **Fabricated server value** (conventions rule 5): `var max = payload.max \|\| terms.length` invented a cap when the server sent none, rendering "1 of 1 running — free a slot" and applying the red at-cap treatment for a cap that was not reached. | FIXED |
| F10 | LOW | Confirm text didn't say how many terminals would die, or that Claude sessions were inside them. | FIXED |
| F11 | LOW | Arming blew away focus without moving it to the control the warning asks about. | FIXED |
| F12 | MEDIUM | `_peekTerminal` was a hand-rolled third copy of the peek-URL builder — the exact drift `ext_vt.js`'s own comment warns about. | FIXED |
| G1 | HIGH | Cap-dialog `onKill` retries the original open **immediately** on the close response — no reap settle, no liveness/generation guard — so it races a pty that is still alive and can hijack whatever the user opened next. `ext_vt.js`'s `renderCapBlock` waits and re-checks. | FIXED |
| G2 | MEDIUM | CR drops the actionable half of the 403/404 errors ("set TRACKER_TERMINAL=1 and TRACKER_AUTH", "on this server"). | FIXED |
| G3 | LOW | `cols: 100, rows: 30` hardcoded twice (`ext_launch.js`, `ext_cr_term.js`). | FIXED |
| G4 | MEDIUM | Directory picker closes synchronously before its POST resolves — no busy state, double-submit possible, errors land as a toast after the context is gone. | FIXED |

## The seam
`window.ExtVT.term` (ext_vt.js): `REAP_SETTLE_MS`, `peekUrl`, `peek`, `closeTty`, `killSeries`,
`armGuard()`. The dashboard manager and the Control Room dialog now both run this one policy.

## Second adversarial pass (two sonnet agents, independent areas)

| # | Severity | Finding | Status |
|---|---|---|---|
| H1 | MEDIUM | `_killCurrent()` hand-rolled its own `POST /api/term/close` instead of calling the exported `ExtVT.term.closeTty` — a second caller of the one route the seam exists to own. | FIXED |
| H2 | MEDIUM | `MODEL_LADDER` retyped in `ext_cr_term.js:26`, though `ext_vt.js` already exports `window.ExtVT.MODEL_LADDER` for exactly this reason. | FIXED |
| H3 | MEDIUM | `EFFORT_LADDER` likewise retyped at `ext_cr_term.js:27`. | FIXED |
| H4 | MEDIUM | `_matchLadderModel` was a byte-identical re-implementation of the exported `ExtVT._matchLadderModel`. | FIXED |
| H5 | MEDIUM | `_openLineageDialog()` ended in an empty `.catch(function () {})` — the dialog silently never opened, breaking the "never fail silently" convention both files state. | FIXED |
| H6 | LOW | `cols: 100, rows: 30` duplicated in `ext_launch.js` and `ext_cr_term.js`. | **ACCEPTED, not changed** — both spawn a new tab that measures and resizes on attach, so the seed value has no drift consequence. Changing a working dashboard path for a cosmetic dedupe is risk without payoff. |

### The load-order trap (why the ladder fix is lazy)
`page.py` inlines `web/ext_*.js` by **sorted glob**, so `ext_cr_term.js` is evaluated *before*
`ext_vt.js`: `window.ExtVT` does not exist at that file's module-eval time. Every rewire therefore
reads the export **lazily inside a function body** (`_vt()`, `modelLadder()`, `effortLadder()`).
A top-level `var MODEL_LADDER = window.ExtVT.MODEL_LADDER` would have thrown on every page load.

### Self-caught gap
The picker busy-guard only engages if `onPick` returns a promise; `_pickDirectory` did not return
its chain, which would have left the fix inert. Corrected in the same round.

## Existing tests the refactor touched (and why the edits are not a weakening)

Three assertions in `tests/test_term_vt_client.py` pinned dashboard behaviour by **source text**,
and the extraction moved that text. Behaviour is unchanged; the assertions now point at where the
logic actually lives, and each still fails if the invariant breaks.

| test | why it broke | new assertion |
|---|---|---|
| `test_close_all_requires_a_confirmation_step_before_it_kills_anything` | the per-tty loop moved out of `closeAll()` into `killSeries()`, so the `closeAll` slice no longer contained `closeTty(t.tty)` | asserts `closeAll` delegates via `killSeries(terminals)` **and** that `killSeries` contains `closeTty(t.tty)` — the "no bulk route was invented" invariant is still pinned, in two places instead of one |
| `test_peek_url_carries_tty_and_sid_and_mode` | `window.open(url, …)` became `window.open(peekUrl(t), …)` | asserts the new call; the `?tty=`/`&sid=`/`&mode=` assertions were untouched and still pass, because `peekUrl` sits inside the same slice |
| `test_placement_relative_to_the_other_two_tiers` | it indexed the bare string `window.ExtVT`, and a **comment** added in `ext_cr_term.js` (inlined earlier) became the new first occurrence | indexes `window.ExtVT = {` — the actual definition. Strictly more precise: the test's stated intent is concatenation ORDER of the definition, which a mention in prose was never evidence of |

## Verification
- `tests/test_cr_manage_terminals_parity.py` — 4 new assertions, all green.
- **Proved by reverting**: restoring `payload.onCloseAll()` (no args) fails on "must receive the
  terminal LIST, not undefined"; removing `if (armed && armed()) return;` fails on "must consult
  the arm guard". Both restored, both green again.
- `tests.test_term_vt_client` — 258/258 green after the three assertion updates.
- `tests.test_cr_manage_terminals_poll` (4), `tests.test_cr_dialogs_poll_broadcast_seam` (6),
  `tests.test_term_vt_exec` (95), `tests.test_cr_routes` (20) — all green.
- Full concatenated bundle passes a JS syntax parse.

## Third pass — adversarial review of MY OWN fixes (two rounds, sonnet)

Round 1 refuted three sub-claims; round 2, run against the repairs, refuted two more. All five were
real. This is the part worth keeping: the first agent to map these files reported "no missing
handlers, no dead URLs" — every URL *did* resolve, and the button was still dead.

| # | Finding | Status |
|---|---|---|
| J1 | **"Close all" was never latched.** The latch covered the row kill buttons, not the confirm. The arm guard only spans ~500ms and `killSeries` is *sequential* (one round trip per terminal), so a real sweep outlasts it and the still-visible confirm could fire a second sweep across a half-drained list. Guard and latch cover different spans. | FIXED |
| J2 | **The picker's double-submit guard didn't survive a repaint.** `busy` was scoped inside `paint()`, and the dialog re-opens *itself* (`{loading:true}` → cwds), so its own load sequence wiped the flag. Reachable by typing a path and hitting Start before the directory list lands. | FIXED |
| J3 | **The everyday single kill had no repaint and no failure toast** — wired to the bare `_killTerminal`, which only touches `st.running` and the badge. I had marked this FIXED in an earlier revision of this report without having wired it. | FIXED |
| J4 | **`release()` reconciled a detached node.** It closed over the button the *click* started on; a repaint mid-flight left the on-screen Start button disabled and reading "Opening…" forever, with no further repaint to fix it. Now reconciles whichever controls are live. | FIXED |
| J5 | **The deferred repaint could re-open a dismissed dialog.** `open()`'s same-name dedupe folds into `update()` only while the dialog is topmost; otherwise it pushes a new one. Killing a terminal then closing the dialog inside the 250ms settle window made it spring back. | FIXED |

### One deliberate addition to the shared seam
`CR.dialogs.topName()` — a read-only accessor for the topmost dialog's name. J5 has no correct fix
without it: a dialog that repaints itself on a timer must be able to ask whether it is still on
screen. One line, no new state.

## Final verification
- `tests/test_cr_manage_terminals_parity.py` — **12 assertions across 3 classes**, all green.
- **Every fix proved by reverting it and watching the matching test go red**, then restored:
  dead button, arm guard, close-all latch, `busy` hoist, `onKill` wrapper, stale `release()`,
  `topName()` guard. Seven independent red-proofs.
- `python3 -m aitracker --selfcheck` → exit 0.
- `tests.test_term_vt_client` 258/258 · `test_term_vt_exec` 95 · `test_cr_routes` 20 ·
  `test_cr_manage_terminals_poll` 4 · `test_cr_dialogs_poll_broadcast_seam` 6 — all green.
- Full concatenated bundle parses as JS.
