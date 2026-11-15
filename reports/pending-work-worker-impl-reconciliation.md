# Implementation review — reconciliation and fix brief (main thread, 2026-11-15)

Reviews (each finding there has defect + repro, fix direction, the way, the test): `pending-work-worker-review-E1.md` (pending.py, schedule.py), `-E2.md` (update, routes, security), `-E3.md` (web UI), `-F.md` (non-functional, with measurement plan M1-M11). Ids below are `<review>-<id>`. A fixer reads the named finding in its review for the four parts; where this file trims or overrides a fix, THIS FILE WINS.

Verdict key: C = confirmed/accepted as written; T = accepted, fix trimmed; D = dropped (reason); L = left alone, documented.

## Blockers
| Id | Verdict | Ruling |
|---|---|---|
| E2-F1 = E3-B1 `term_vt.py:3124` Resume never sends prompt (`_with_prompt` after a `return`) | C (found twice) | Dedent the call. Test must go through the `open_pty` route path, not the helper. |
| E1-F1 = E2-F2 `server.py:223` no Origin check in `_local_caller` | C (found twice) | Refuse when an `Origin` header is present and its host:port does not equal the request Host; absent Origin stays allowed (non-browser clients). Same rule with and without TRACKER_AUTH. One shared pure helper in util.py; `term_gate._origin_ok` may delegate but must not get looser. |
| E3-B2a/B2b `app.js:205,:292` fence break + mermaid style attribute injection | C | Both halves. New tests/test_md_fence_xss.py, red first. |

## pending.py — fixer G1 (safety/correctness), then G2 (state/perf); same file, strictly sequential
G1: E1-F2 C · E1-F3 C · E1-F4 C (red test FIRST — claim is from code reading) · E1-F5 C · E1-F6 C · E1-F7 C · E1-F9 C · E1-F11 C · E1-F12 C · E1-F15 C · E1-F16 C · E2-F5 C · F-F5 C · E3-S3 C · E3-S4 C · E1-F20 T: only "skip prune when the worktree's volume is missing"; drop the `-z` re-parse (any porcelain output already means dirty) · E1-F18 T: delete the session-id clause from `resume_prompt` (nothing fills it) — E2-N4 is then moot · NEW (missed by all): `resume_prompt` must return ONE line with no control characters (it is typed into a shell and E2-N3 rejects control bytes) — assert that in a test.
G2: E3-N1 = F-F1 C (`next_due` None when unscheduled; stable compare key) · E1-F10 = F-F2 T: the in-server worker does not scan from a linked-worktree checkout, a temp dir or a test run — reuse schedule.py's existing guards, no new config key · F-F3 C · F-F4 T: memoise the parsed report on (mtime, size) only; NO `?view=card` route · F-F6 T: `_under_rp` fast path only; no subprocess gating rework · F-F9 C · E3-N3 = F-F8 C: `card.as_of`, shown by both renderers (the web fixers add the render).
Dropped: F-F7 (perf nit, no repro). Left: E1-F17 = F-N1 (document in README known gaps).

## schedule.py — fixer G3
E1-F8 C (a direct test-file run must never reach a real install) · F-F12 C.

## update.py — fixer G4
E2-F4 C · E2-F6 C (`can_update` False on Windows; README says so) · F-F11 C · E2-N1 C · E2-N2 C · E2-N7 T: delete the dead env pop and the duplicate loopback helper, delegate to util. Dropped: E2-N6 (no test, cosmetic traceback).

## server.py + term_vt.py + util.py + term_gate.py — fixer G5
E1-F1 = E2-F2 (above) · E2-F3 C (`start_restart` in `finally`) · E2-F1 = E3-B1 (above) · E2-N3 C · E2-resid T (in scope by user decision H2 "fix all local-only routes"): `/api/tunnel/reveal` and `/api/tunnel/ctl` get the same no-login loopback-Host + Origin check; behaviour with TRACKER_AUTH set must not change. Left: F-N2, F-N3 (document).

## web/app.js + app.css + index.html — fixer G6
E3-B2a/B2b (above) · E3-S1 C · F-F10 T: defer the reload-after-restart while a text field has focus or unsent text; NO banner · E3-N5 C (fixer adds the test) · render `card.as_of`. Dropped: E3-N2 (the F-F1 fix removes the re-render that reset scroll), E3-N9 (no repro). Left: F-N5, F-N6.

## web/ext_cr_dialogs.js (+ ext_cr_board.js for `as_of`) — fixer G7
E3-S2 C (post unconfirmed; the server's 409 is the only source of the count) · E3-N4 C (a "Scan now" button in Settings so a scan can be started when no card shows) · E3-N7 C (one CSS rule) · render `card.as_of` on the board tile. Dropped: E3-N6 (no test, cosmetic).

## tests-only — fixer G8 (after G1-G7)
F-F13 C (T16: `/api/list`, `/api/session` and GET `/api/pending` never scan) · E1-F13 C · E1-F14 C · E3-N10 C · F-F15 C (cut pending/update test wall time without weakening a test). Docs: E1-F19 C (conventions D4 + README wording) · F-N4 L (README: first run scans for ~4 min in the background).

## Missed by all four reviews
1. `resume_prompt` single-line/no-control-chars invariant (in G1).
2. No end-to-end check that the bytes typed into the shell reproduce the prompt exactly under zsh quoting once E2-F1 is fixed — G5 adds a test at the `_inject_argv` level.
3. The H5 measurements (M1-M11) have never run — run after the fixes; record numbers in the durable file (F-F14).

## Parked for the user (not decided here)
- Landing on `personal/main`; installing and proving the real launchd job on this Mac.
- Widening the loopback-Host/Origin check to every route (current scope: local-only routes + the two tunnel routes).
