# Terminal: peek an already-running terminal instead of spawning a second one

Worktree: `.claude/worktrees/terminal-peek-resume` (branch `worktree-terminal-peek-resume`, based on
local HEAD `31be4ce`; this repo has no `origin`, only `personal`).

## The contract (verbatim, as asked)

> For a session where the terminal is already running from the server and is coming up in the manage
> terminals sections I would want the app to do a peek on the earlier opened terminal session and not
> creating a new one for a new resume terminal here request.

Discharged: **yes** — see Verification. Both `▶ Open terminal here` and `⟲ Resume terminal here`
inherit the behaviour from one change (the ask named "resume terminal here"; the sibling button goes
through the same function, so gating it to one of the two would have been the forked implementation
conventions rule 4 forbids).

## The gap, framed

1. **Capability.** Clicking a session's terminal button must surface the terminal ALREADY running for
   that session, rather than spawning a second one against the same conversation.
2. **The asymmetry.** The "Manage terminals" panel already knew how to attach to a live pty (its
   `peek` button). The session detail pane's buttons did not — `openVT()` could only ever CREATE.
   Same capability, present on one path and absent on the other.
3. **Consumers.** Client-side only. The server already exposes everything needed:
   `GET /api/term/list` returns `session`/`mode` on every live row (`term_vt._live_list()`), and
   `peekTerm()` already builds the standalone `?tty=` URL. No new route, no new field, no new
   server-side policy — and therefore nothing re-derived client-side that the server owns.

## The change

`aitracker/web/ext_vt.js` only (33 lines).

- `openVT(sid, mode)` now claims its generation, fetches `GET /api/term/list`, and calls the
  **existing** `peekTerm(t)` when a live row matches on **both** `session === sid` **and**
  `mode === mode`. Matching on mode as well as session is deliberate: a plain shell (`cwd`) sitting in
  the session's directory is not a substitute for `claude --resume`, and reusing it would silently give
  the user the wrong thing.
- Everything else moved verbatim into `_openVTFresh(sid, mode, mount, gen)` — the former `openVT`
  body, renamed, taking `gen` as a parameter instead of declaring it.

### The defect found and fixed during verification

The first version tailed `.catch()` on the END of the promise chain. That also swallowed a throw from
`_openVTFresh`/`peekTerm` and re-invoked `_openVTFresh` — spawning the second pty this feature exists
to prevent, silently. The catch now sits on the fetch alone, so the fallback covers only "the route is
off / 404 / unreachable", which correctly degrades to the pre-existing always-spawn behaviour.

### Scope of the guarantee — what this does NOT fix

This closes **repeated opens within one page**. It does **not** make a double-spawn impossible in
general, and the code must not be read as if it did.

`openVT` is a check-then-act: `GET /api/term/list` → decide → `POST /api/term/pty`, with `openGen` as
the only interlock — and `openGen` is a per-page-load in-memory counter, so it only supersedes a later
click *in the same tab*. Two independent contexts (two browser tabs on the same session, or a tab plus
a freshly-opened standalone view) that both observe the pre-POST server state will both spawn.
Demonstrated by an adversarial reviewer, who instantiated the real `openVT` source in two independent
module scopes against one simulated server and got two `POST /api/term/pty` calls for the same
`session`+`mode`.

This is a property of the **server**, which today enforces no session+mode dedup at open time:
`open_pty()` (`aitracker/term_vt.py:2053-2110`) guards only the `MAX_TERMS` capacity check. It is
pre-existing, not introduced here. A real fix belongs server-side — under `_LOCK`, return the existing
live pty instead of spawning when one already matches `session`+`mode` — which would also change the
`POST /api/term/pty` contract (a caller could get back a tty it did not create). That is a deliberate
product decision and was left out of this change rather than guessed at.

No test in `TestOpenVTPeekBeforeSpawn` covers this: every test runs in one shared module scope, so the
suite cannot catch a cross-context race by construction. Stated here so the gap is visible rather than
implied to be covered.

## Verification

**Live, end-to-end** (server on :8799, deliberately off the user's 8787/8790; stopped by PID after):

- Spawned one `mode="cwd"` terminal for session `73e6cc28-89f5-4100-afc7-92b1ffcb1895`, then invoked
  the real `ExtVT.open(sid, "cwd")`. Result: `window.open` called once with
  `?tty=a315780304b3&sid=73e6cc28…&mode=cwd&forked=0` — the **existing** tty — and the live terminal
  count stayed at **1**. Pre-change behaviour would have made it 2.
- Mode mismatch (a `cwd` terminal live, user clicks `resume`): correctly did **not** peek.
- Cleanup: both test terminals closed, 0 remaining.

**Executed tests** — `tests/test_term_vt_exec.py`, class `TestOpenVTPeekBeforeSpawn`, 8 methods, driven
under node against the REAL `openVT`/`_openVTFresh`/`peekTerm` source sliced verbatim out of the
shipped file (this module's established pattern; the file's own docstring records why source-text-only
tests are considered insufficient here). Covers: match→peek; same session different mode; different
session same mode; empty list; list returns 403; list rejects; stale generation does neither; and
`_openVTFresh` throwing is invoked exactly once (the regression guard for the `.catch` defect above).

Proven to bite, twice and independently: reverting `openVT` to the old always-spawn body turns
`test_matching_session_and_mode_peeks_instead_of_spawning` red (`windowOpenCalls == 1` → 0, and
`rafScheduled == 0` → 1). An adversarial reviewer repeated this by stashing only `ext_vt.js` and
re-running the class, and found **3 of 8** go red — also
`test_openvtfresh_throwing_is_never_retried` and `test_stale_generation_does_neither_peek_nor_spawn`.

Full gate: `make check` → **1187 passed**, `selfcheck ok`, exit 0 (1179 before; the 8 new tests are
the delta).

### Known limit of the live check

The fresh-spawn `POST /api/term/pty` could not be exercised through the in-app browser pane: it sits
behind `requestAnimationFrame`, and the pane runs with `document.hidden === true`, which suspends rAF.
That gates **pre-existing, unchanged** code, not this change — `_openVTFresh` was confirmed to be
ENTERED correctly (overlay opens, title set, status "connecting…", probe pane appended, i.e. the whole
pre-rAF portion of the original `openVT`). The node tests cover the rest deterministically.

## Restart note

This is a **client-side** change baked into the page at server startup — `make serve` (restart) is
required to see it, a reload is not enough.

## Not done

No commit, no push, no PR — local worktree change only.
