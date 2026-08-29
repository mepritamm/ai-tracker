# Control Room redesign — implementation record

Source handoff: `/Users/pritammondal/Downloads/design_handoff_control_room/`
Worktree: `.claude/worktrees/control-room` on branch `worktree-control-room`
2026-08-29. Run mode: unattended (`/head-out`). Orchestrated across 13 subagents
(sonnet, plus haiku for mechanical work and gate runs).

## Contract (verbatim from handoff README "Non-negotiables")

> - **Read-only toward sessions.** The tracker never writes into a session. The detail view's decision panel is view-only, and the copy says so.
> - **The 2-second poll and the existing result shape stay.** No new server round-trips per panel.
> - **Provider-agnostic.** Every panel must degrade honestly for a provider that lacks the data (see `04`, "Degraded providers"). No forked per-tool UI.
> - **The gate stays green.** `make check` must pass. Add a `--selfcheck` assertion for any new derived value.
> - **Colour never carries meaning alone.** Every state has a word next to it.

### Discharge, clause by clause

| Clause | Verdict | Evidence |
|---|---|---|
| Read-only toward sessions | **Discharged** | No write path into any session log. Writes are only to app-owned `flags.json` / `titles.json` / notes, via routes the classic UI already used. Decision panel is view-only. |
| 2s poll + existing result shape | **Discharged, with one disclosed exception** | No new endpoints. New fields ride the existing `/api/list` and `/api/session` payloads. Exception: `ctx.terminals.count()` does ONE cached, never-repeated `GET /api/term/list` to learn `MAX_TERMS`, which has no other exposure. |
| Provider-agnostic | **Discharged** | Capability landed once at the seam (`util.todo_summary`, `registry.parse_any`), inherited by Claude / Auggie / Augment-ext(×2). Where a provider genuinely lacks data it emits explicit `null` — see the spine note below. |
| Gate stays green | **Discharged** | `env -u TRACKER_AUTH make check` → 1187 tests, exit 0, `selfcheck ok`. Verified by an independent serial run after all agents finished. |
| Colour never alone | **Believed discharged, NOT independently audited** | Each module was briefed on it and reports compliance; no separate contrast/wording audit was run. See "Not verified". |

## What shipped

New UI: **8,487 lines** across 11 files in `aitracker/web/`, all auto-served by
`page.py`'s existing `ext_*` glob — no change to `page.py`.

| File | Lines | Contents |
|---|---|---|
| `ext_cr.css` | 311 | Design tokens, both themes |
| `ext_cr_board.js` / `.css` | 902 / 748 | Shell, top bar, rail, triage strip, 8-tile board |
| `ext_cr_boot.js` / `.css` | 828 / 173 | Mode switch, theme, `ctx`, polling, integration listeners |
| `ext_cr_detail.js` / `.css` | 1373 / 1113 | Detail view, all panels, progress spine, merged timeline |
| `ext_cr_dialogs.js` / `.css` | 1280 / 452 | Dialog system, Help, Config, empty/error/degraded states |
| `ext_cr_term.js` / `.css` | 901 / 406 | Terminal chrome, PTY pane, status bar |

Server side (all at the shared seam): `util.todo_summary()`; `todo_total` /
`todo_done` / `todo_current` on the list dict; `pinned` / `note_count` /
`open_flags` on the detail dict; per-todo `started_at` / `ended_at`;
`store.load_tasks()` now stamps the join key `id`.
`ext_vt.js` gained `ExtVT.mountInto()` (+304/−3) so the new chrome can host a PTY
inline. `index.html` changed by exactly **+2 lines**.

## Deliberate deviations from the handoff

1. **File layout.** PROMPTS.md prescribes appending into `app.css` / `app.js` /
   `index.html`. We ship separate `ext_cr*` files instead. Five agents cannot safely
   append to one file, and `page.py:8-10` already globs `ext_*` into the served page,
   so this needs zero server change and produces the same single inlined page.
2. **Token names / scope root.** The handoff README advertises an `--ads-*` token
   prefix; `01-foundations.md` (which the README says wins) actually uses plain names
   (`--surface-*`, `--text-*`) scoped to `.tracker-next` with an `.is-dark` class
   toggle. We followed the doc. `#nextRoot` carries BOTH `tracker-next` and `cr` so
   either scoping resolves.

## Assumptions taken without asking (user had left)

- Config's env-backed rows are **read-only with the reason stated**. No server write
  route exists and the handoff says to flag rather than build one. `TRACKER_AUTH` is
  shown only as set/not-set, never its value.
- `ext_vt.js` was not rewritten; the seam was added additively. Its 651 terminal
  tests pass unchanged.
- xterm.js stays lazy, loaded only from the terminal-open path.

## Parked — real gaps, deliberately not built

- **`cr:stop`** and **terminal model/effort switching**: no server route exists.
  Controls are disabled with honest copy rather than inert.
- **`cr:run-command`** reports start/finish via toast; there is no inline output pane.
- **Progress spine is time-proportional for Claude only.** Auggie/Augment-ext emit
  `null` because their `chatHistory` `task_id` lives in a different id space than the
  task-storage uuid — no reliable join. They degrade to equal-width segments.
- **Claude prunes its own task store.** Measured: 18 of 35 real task dirs were empty,
  every one older than ~2 days, so todo counts and spine timings are absent for most
  historical sessions even though the transcript retains the history. Honest
  degradation, not a bug — but it means the feature is quieter in practice than it
  looks. The durable source would be the transcript, not the task store.

## The bug the gate could not see

Late in the run, a stub-DOM execution of the **real served bundle** caught a
page-breaking defect that all 1187 tests and every `node --check` had passed over.

Three modules assigned `CR.detail = {…}` instead of `window.CR.detail = {…}`. Each
IIFE sets `window.CR` but declares no local `CR`, so the bare identifier threw
`ReferenceError: CR is not defined` on **every page load**. Because `page.py`
concatenates everything into ONE `<script>` tag, the first throw halted every file
after it in sorted order:

```
app.js -> ext_cr_board -> ext_cr_boot -> ext_cr_detail  X THROWS
                                          (never run:) ext_cr_dialogs, ext_cr_term,
                                                       ext_launch, ext_run, ext_vt
```

So it killed not only the new UI but the **classic dashboard's entire terminal
subsystem**. Only `CR.board` registered. Fixed (4 one-token edits); all four modules
now register with every expected method.

**Why the gate missed it:** nothing in the suite executes the assembled page, and
`node --check` validates syntax, not execution. A permanent regression test was added
(`tests/test_page_bundle.py`) that runs the real `build_page()` output under a stub DOM
and asserts the modules register, plus an instant static check for bare `CR.`
assignments. Anyone touching `aitracker/web/*.js` should keep that test green.

That test was itself adversarially verified — three independent fault injections (a
top-level `throw`, a removed `window.CR.term` registration, and a `ReferenceError`)
each drove it RED with a specific message, and the static grep test stayed green
through all three, confirming execution catches what regex cannot.
**Known blind spot:** the harness registers a global `unhandledRejection` no-op, so a
purely *asynchronous* failure arriving after the synchronous epilogue prints
`BUNDLE-OK` would not be caught. Load-time throws and failed registration are covered;
async rejection is not.

## Not verified — be aware before trusting this

- **No real browser load.** The Chrome extension was not connected, so the UI was
  never rendered in an actual browser. Substituted: a stub-DOM execution of the real
  served bundle, `node --check` on the concatenated bundle, and structural HTML checks.
  **Visual fidelity against the design was never checked by eye.**
- **No contrast/accessibility audit** against the doc's stated 4.5:1 / 3:1 floor.
- The "colour never carries meaning alone" clause rests on module self-reports.

## Verification actually performed

- `env -u TRACKER_AUTH make check` → **1187 tests, exit 0, `selfcheck ok`**, run
  serially after all agents finished (plus two corroborating agent runs).
- Every new selfcheck assertion proven RED-then-GREEN by breaking the implementation.
- `node --check` on each module and on the concatenated bundle in `page.py`'s order.
- `build_page()` → 823k chars, no `__CSS__` / `__JS__` left.
- Terminal suites 651/651 after the `ext_vt.js` seam.
- Adversarial review of the Python diff that **measured** cost rather than trusting
  reports: Auggie's per-session todo read ~9ms across 85 sessions vs ~860ms for the
  naive full-glob it replaced.

## Gotcha for the next session

`TRACKER_AUTH` is exported in the user's shell, so a plain `make check` yields ~33
bogus 401 failures while still printing `selfcheck ok`. Always gate with
`env -u TRACKER_AUTH make check`.
