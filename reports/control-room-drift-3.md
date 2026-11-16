# Control Room — drift round 3 (current code vs the 2026-08-30 handoff bundle)

Date opened: 2026-11-16
Branch: `worktree-control-room-drift` (base `personal/main` @ `76bd154`; fast-forwarded to `adeb6fa` (pending-work worker + in-app update) mid-review, on 2026-11-16. Audits 00–05 and PLAN.md cite `76bd154` lines; reviews A/B re-verify against `adeb6fa`. Untouched by the move: `ext_cr_term.*`, `ext_cr_detail.*`, `ext_vt.js`. Moved: `ext_cr_dialogs.js` +189, `server.py` +122, `config.py` +69, `ext_cr_board.js` +27, `ext_cr_boot.js` 1 line.)
Bundle: `~/Downloads/app-ui-redesign-request 2/` (extracted 2026-08-30; same bundle audited in rounds 1–2)
Prior rounds: `reports/control-room-drift-analysis.md` (round 1, 2026-08-31, per-doc tables in `reports/drift/`), `reports/drift2/` (round 2 adversarial re-audit). 52 commits have touched `aitracker/web/ext_cr*` since 2026-09-01.

## Contract (user ask, verbatim)

> run a full comparison for the new control room design. And identify the drift, run a full detailed drift analysis and plan to implement it

| Clause | Status |
|---|---|
| Full comparison of the control room design vs current code | not discharged |
| Identify the drift | not discharged |
| Full detailed drift analysis | not discharged |
| Plan to implement it | not discharged |

Implementation is NOT part of this ask: per rule 8, the plan goes to the user for sign-off before any code.

## Method

1. Five per-doc drift agents (sonnet), one per spec doc, plus one precedence/extras agent → `reports/drift3/*.md`
2. Plan (opus) → `reports/drift3/PLAN.md`
3. Adversarial review, split into two opus agents (because reviewers stall on large scopes) → `reports/drift3/REVIEW-A.md` (P1–P3, D3/D4/D8) and `REVIEW-B.md` (P4–P7, D1/D2/D5–D7, Dropped)
4. One overall clean plan (opus) merging both reviews → `reports/drift3/CLEAN-PLAN.md` (chain step 2 requires ONE)
5. Reconciliation (main thread; any code checks go to an agent) → this file
6. User sign-off on the reconciled plan + decisions. No code before it.

**Binding on implementation (chain step 6):** every phase runs through `/tracker-gap` (this repo's `gap`) first, on cheaper agents per rule 3 (sonnet implements, haiku runs the gate); every new test is proved red by reverting the fix; then a separate opus adversarial review of the implementation, `/branch-sync`, re-run the gate, and push `worktree-control-room-drift` to `personal` (rule 5). All phases fold into this one branch (rule 9).

## Findings summary

Precedence (audit 00): **docs win**. Commit `7b87cce` (2026-09-05) reversed the 2026-08-29 "HTML wins" ruling, with emoji excepted; later owner rulings (emoji→SVG icons, green Working, cap 3–12, heartbeat) override the doc. The 08-29 text in `control-room-redesign.md:180` was never marked superseded.

| Doc | Prior closed | Still open | Regressed | Superseded | New drift (H/M/L) | Top issue |
|---|---|---|---|---|---|---|
| 00 README / precedence | — | — | — | — | 3 non-negotiables PARTIAL; classic app.css/app.js touched (owner-directed, unrecorded) | Bundle test skips without node; covers 4 CR modules, not ExtVT/launch/run/boot |
| 01 foundations | 24 | 3 | 0 | 1 | 0/1/7 | Tokens match the doc exactly in both themes; Working colour split (green rail/pill vs wheat tile/spine dot) |
| 02 shell & board | 10 | 6 | 0 | 4 | 1/3/6 | Idle sessions now get tiles (doc: never), ruled only in a code comment; "Show all" lifts the cap |
| 03 detail view | ~31 | 17 | 1 partial | 4 | 2/2/~4 | Header actions in one row, not two; fork banner is still a small card; timeline newest-first |
| 04 coverage & help | 14 | 7 | 0 | 4 | 0/1/5 | All 61 capabilities homed; Help table omits post-Sept features; Config Data files never populated |
| 05 terminal & dialogs | 14 | 1 | 0 | 2 | 0/6/8 | Esc in a terminal dialog detaches the terminal; xterm stays under an 82% overlay; failed spawn loses the path |

Per-doc detail: `reports/drift3/0N-*.md`.

## Plan, review, clean plan (side by side)

| Artifact | Path | Author |
|---|---|---|
| Original plan | `reports/drift3/PLAN.md` (lines at `76bd154`) | opus planner |
| Review A: P1–P3, D3/D4/D8 (25 findings) | `reports/drift3/REVIEW-A.md` | opus reviewer |
| Review B: P4–P7, Dropped, D1/D2/D5–D7 (26 findings) | `reports/drift3/REVIEW-B.md` | opus reviewer |
| **Clean plan: the one to implement** | `reports/drift3/CLEAN-PLAN.md` (lines at `adeb6fa`) | opus merger |

The merger re-checked all 51 review findings at `adeb6fa`: 44 hold, 7 hold in part (A5, A8, A9, A21, A22, B3, B19), none fails. Its evidence table was returned as text (the harness refused the subagent write) and is summarised in the verdicts below rather than transcribed. An independent haiku spot-check of the six highest-leverage claims (A1, A2, A3, A24, B3, B22 plus the A23 contrast) agreed except where noted.

## Reconciliation: main-thread verdicts

| Verdict | Findings | Judgment |
|---|---|---|
| **Confirmed** | A1, A4, A6, A10, A13–A16, A18, A20, A23, A25; B2, B4, B7, B9–B13, B15–B18, B20–B26 | Fold in as the clean plan has them. A1 and A2 spot-checked: mount order `ext_cr_boot.js:956→957→963`, unguarded Esc `ext_cr_term.js:243-245`. |
| **Confirmed, with the narrower fix** (overengineered fix cut) | A8 (CR-side focus on "connected", no `ext_vt.js` edit); A21 (recolour `cr-board-pulse` in place, not a new shared keyframe); B8 (move todo ticks into the side rail, not a second count); B19 (export `shortDir` on the `CR.board` return object, not a new global) | The clean plan already takes the narrow versions. |
| **Overstated** | A12 (the `st.notice` change is dropped; the notice is already set before `fireForked`); A24 (timeline order is already owner-ruled in `aadcae5`, so D4 drops out of the decision list); B1 (basename-for-remote is right, but it closes no leak: `/api/list` already sends full `cwd`); B14 (only the untested `stateOf` classes need pins) | Keep the fix where it still has value; correct the stated reason. |
| **Partly holds: verify before fixing** | A3 (xterm notice invisible under the engine wrap): the spot-check did not reproduce the DOM-order claim (`ext_vt.js:3668` appends the wrap; notices are inserted before it at about `:490`), though the missing `z-index` holds (`ext_cr_term.css:294-312`). A5 (the picker loses the typed path) needs the harness tweak before its test can go red. A9 (no 2.6s delay exists), but the asset-load-window focus guard is still needed. | **P1.2 starts with a browser repro.** If the notice is visible, P1.2 reduces to "show only when an engine is attached". |
| **False alarm** | none | — |
| **Missed by plan and audits, found by reviews** | A2 (board Esc clears triage under a dialog); A7 (picker toasts invisible from the board); A11 (red "connected" toast on every open); A17 (doc's long action labels); A19 (fork banner says "still running" forever); A22 (Working split wider than listed); B3 (Help privacy copy false after `adeb6fa`); B5 (Server tab shows the configured port, not the bound one); B6 (`_NOT_LOCAL` text mentions a terminal) | Placed in phases, or as decisions D9–D11. |
| **Missed by both reviews, found by the merger** | `j`/`k`/`t` act on the board behind a dialog; the scheduled `gh` scan also makes review B's proposed Help copy false (spot-checked: `pending.py:778` inside `scan()`, scheduled via `:954`/`:1000`); two tests go red **by design** under D2(a) and D3(a); a stale bundle copy at `~/Downloads/design_handoff_control_room` (25 dark tokens differ), so P6.4 must copy from `app-ui-redesign-request 2`; `config.json` PORT/HOST never read at startup (deferred) | Folded in. |
| **Examined by nobody** | Everything visual or timing-dependent in a real browser: focus and scroll across the 2s poll, phone 44px hit targets, the xterm notice, both themes rendered, Auggie sessions rendered (static reads only) | Covered by the browser pass in the implementation protocol, not by this plan. |

## Decisions for the owner (from CLEAN-PLAN.md; D4 removed as already ruled)

| # | Question | Recommendation |
|---|---|---|
| D1 | Idle sessions backfill board tiles (doc: "Idle sessions never get a tile") | Keep and record. If reversed: filter in `renderBoard` and the `t` handler only. |
| D2 | "Show all N" lifts the 8-tile cap (doc: "No show more") | Remove. `test_cr_crossview.py:302-350` goes red by design and gets rewritten. |
| D3 | Working colour is split (green rail vs wheat pill, tile dot, triage) | Green everywhere except the spine dot and agent-row dots; add `--text-working` ink (green `#1C9163` is only 3.98:1 as text). |
| D5 | Heartbeat default + panels open by default (doc: spine; all collapsed) | Keep. Already in the heartbeat contract. |
| D6 | Unruled extras: PINNED cell, agent map, model chip, `?ui=`, Queue-a-note, timeline chips | Keep all and record them as rulings. |
| D7 | Classic `app.css`/`app.js` were changed despite "do not alter" | Record the override; do not revert. |
| D8 | Detail orb rail size (docs 02 and 03 disagree: 28 vs 34px) | Defer. |
| D9 | Help says "Nothing is sent anywhere", now false (`git fetch` for Update; scheduled `gh pr list`) | Rewrite the copy to name both calls and when they run. |
| D10 | Fork banner says "the original is still running" forever | Show the clause only while the parent session is live. |
| D11 | Doc labels "Search this session" / "Flag an issue · N" vs the short labels | Adopt the doc labels (LOW). |

## Phases (CLEAN-PLAN.md; one commit each, all on this branch)

P1 terminal correctness (4) → P2 terminal chrome (5) → P3 detail header, fork banner, files row (3) → P4 Help/Config honesty (6) → P5 board tiles (3) → P6 gate hardening (6) → P7 polish and records (6). About 20 LOW items are deferred with reasons.

## Contract status

| Clause | Status |
|---|---|
| Full comparison of the control room design vs current code | **discharged**: six per-doc audits, `reports/drift3/00..05` |
| Identify the drift | **discharged**: findings summary above, plus per-doc tables |
| Full detailed drift analysis | **discharged**: audits, two adversarial reviews, merger re-check, spot-check, reconciliation |
| Plan to implement it | **discharged, pending owner sign-off**: `CLEAN-PLAN.md` + decisions D1–D11 |
