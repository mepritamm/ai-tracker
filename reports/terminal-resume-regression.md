# Terminal: Open-terminal dropdown + Resume regression (ai-tracker)

Base: `e6acfe7` (personal/main). Worktree `.claude/worktrees/terminal-resume-regression`, branch `terminal-resume-regression`.
Process: plan-review chain via `/tracker-gap` + `/gap` (user, 2026-11-17).

## Contract (user ask, verbatim)

> "Open terminal button in the tracker app must hide behind a dropdown button beside the resume button in the tracker app, also the tracker app has started generating terminal and overflow when trying to resume any session, check the previous commits and the previous management of terminals is needed to be there, have enough tests/evals such that this kind of regression never occurs"

> "plan-review chain with /tracker-gap and /gap"

Screenshot: clicking Resume pops "Manage terminals — 2 of 10 running" (peek/kill rows, "Resume all prior terminals", "Close all").

| Clause | Verdict |
|---|---|
| C1 Open terminal hidden behind a dropdown beside Resume | not discharged |
| C2 Resume no longer spawns terminals / overflows | not discharged |
| C3 Restore the previous terminal management (from prior commits) | not discharged |
| C4 Enough tests/evals so this regression can't recur | not discharged |
| C5 Plan → adversarial review → reconcile → sign-off, via /tracker-gap + /gap | in progress |

## Investigation (sonnet root-cause + haiku locator, 2026-11-17)

**Buttons.** "Open terminal" + "Resume" sit side by side only in the Control Room detail header: `ext_cr_detail.js:1370-1381` (`SKELETON`, `span.crd-row1-actions`), handlers `ext_cr_detail.js:1915` (`terminal:open`) / `:1916-1921` (`session:resume`). Board tiles (`ext_cr_board.js:2976-3033`) show Resume *or* "Open terminal to answer" (Auggie), never both. Classic pane `ext_launch.js:424-472`, in-terminal bar `ext_cr_term.js:161-167`. No generic dropdown component exists (only `ext_vt.js:2210-2415` ContextBar switcher, `ext_vt.css:311-360`). Tests pinning buttons: `test_cr_detail_action_row_responsive.py:69-103`, `test_term_launch.py:595-606`, `test_cr_board_resume_button.py:176-227`.

**Regression (2026-11-16 terminal-placement series; not e6acfe7/8aeee07).**
1. `057a195` + `4da60f3`: worktree sessions' shell placed at the repo root (`term_gate.place`; `open_pty` uses `pl["shell"]`), session injected via `sh -c 'cd "$0" && exec "$@"'`. All worktree sessions of a repo compete for ONE root shell; when it's busy (`busy_what`, `term_vt.py` ~3480-3495) `open_pty` takes the overflow branch `term_vt.py:3505-3515` → `_spawn_dedicated` = a new pty per click. Same commits removed the client folder-shell peek-reuse in `ext_vt.js` `openVT` (~2951-2965, ~3873).
2. `cfe81d8` (L5/S3): cold open starts a dedicated claude AND warms a root shell (`term_vt.py:3349-3362`, `if cold:` ~3398-3405, `_slots_add(2 if warm else 1)`, `_warm_root`) → up to 2 ptys per Resume. Possible `_SLOTS_RESERVED` leak (unconfirmed).
3. `46c61ac` added "Resume all prior terminals" to the Manage dialog (explains its widgets, not its opening).

**Previous behaviour.** Resume reused: server `_session_pty(sid)` (unchanged) + client peek of a folder shell already running the session; Manage/cap dialog only on a real 429 (`term_vt.py:3353-3374, 3510`; client `ext_cr_term.js:509-511` `_openCapDialog`, `ext_vt.js:3067` `renderCapBlock`; dialog `ext_cr_dialogs.js:2621`, title `:2648`).

**Open question.** What opens "Manage terminals — 2 of 10" on Resume when not at cap? (MAX_TERMS default 12; user's is 10.)

**Test gap.** No test asserts "one Resume = ≤1 new pty", "second Resume of the same session reuses its pty", or "Resume never opens Manage when slots are free".

## Plan (opus)

### Step A: what opens "Manage terminals — 2 of 10" (closed)

**Resume does not open the dialog, and the cap is never hit. Confirmed.**
- **Evidence 1.** The screenshot shows "Resume all prior terminals". `renderManageTerminals` paints that widget only when `payload.onRefresh` is set (`ext_cr_dialogs.js:2627`).
  - Only `_openManageDialog` passes `onRefresh` (`ext_cr_term.js:777`).
  - The 429 cap path `_openCapDialog` (`:692-739`) never does.
  - `_openManageDialog` has exactly three callers: the overlay's ☰ Manage terminals (`:309`), the board's **Terminals** pill (`nav:terminals`, `ext_cr_board.js:2419` → `ext_cr_boot.js:492-498`), and `_repaintManage` (`:924`, only while that dialog is already on top).
  - So the user opened the list they were shown. It is not a cap refusal.
- **Evidence 2: no `_SLOTS_RESERVED` leak.** Every reservation is paired with a release.
  - The one `_slots_add(2 if warm else 1)` (`term_vt.py:3358`) is released by `_spawn_dedicated`'s `finally` (`:3543-3544`) and `_warm_root`'s `finally` (`:3586-3590`).
  - `_warm_root` runs in `open_pty`'s `finally` iff `reserved`, which is set iff `warm` (`:3359-3360`, `:3402-3404`).
  - `_live_count` (`:1928`) and `_live_list` (`:2380`) use the same `not p.done` filter, so the 429 check cannot disagree with the list count.
- **Evidence 3: what the two rows are.** A read-only `GET :8790/api/term/list` returned `max 10`, 2 rows, **both started in the same second**:
  - `claude --resume c57b10c7…`: `mode=resume`, `overflow=true`, run dir `…/worktrees/md-autodetect-copy`.
  - `/bin/zsh -l`: `folder=true`, at the repo root, no session, `viewers 0`.
  - That pair is what **one cold Resume** produces through cfe81d8's S3 branch: a dedicated claude plus a warmed root shell (`:3352-3362`, `:3398-3405`).
  - The "overflow" the user saw is the `overflow` flag that `_spawn_dedicated` sets (`:3528`).
- **How the implementer re-confirms.** Use DevTools Network on a cold Resume. Expect one `GET /api/term/list` and one `POST /api/term/pty` (200), no 429, and the list growing by 2. After the fix it grows by 1.

### Fix

**L1: Resume opens at most one pty, with no warm shell.** Server, `aitracker/term_vt.py` `open_pty(handler, parsed, body)`.
- Change `:3357` to `warm = mode != "resume" and fp is None and _FOLDER_SPAWNING.get(cwd) is None and free >= 3`.
- A cold Resume then reserves exactly 1 slot and spawns only `_spawn_dedicated`.
- The rest is the previous management, already in the code:
  - The session already runs in a tracker pty → `_session_pty` (`:3337-3345`) returns that pty. 0 new.
  - The client peeks first anyway (`mountInto` list scan, `ext_vt.js:3881-3893`).
  - An idle, settled root shell gets the line typed into it (`:3426-3443`). 0 new.
  - A busy root shell → one overflow pty (`:3507-3513`). Its next Resume hits `_session_pty`. 0 new.
- `_warm_root` stays for `mode="new"`, unchanged (D1).
- Worktree-at-root placement (057a195/4da60f3) **stays**. It is the user's own decision (`reports/terminal-at-root.md`, clauses 1 and 6). With warm gone, Resume can't add a second shell, and the busy-root case costs exactly one pty, once per session. No hunks are reverted. The cap dialog already opens only on a real 429 (`ext_cr_term.js:509`, `:653`). No change there; L3 pins it.

**L2: an "Open terminal" dropdown beside Resume.** `aitracker/web/ext_cr_detail.js` `SKELETON` (`:1379-1383`).
- Delete the standalone `open-terminal` button.
- Make Resume `crd-btn-solid`. It is now the row's primary action.
- Immediately after Resume, add:
  `<details class="crd-termmenu"><summary class="crd-btn crd-btn-outline crd-termmenu-caret" aria-label="More terminal actions" title="More terminal actions" aria-haspopup="menu"><span aria-hidden="true">▾</span></summary><div class="crd-termmenu-list" role="menu"><button type="button" class="crd-termmenu-item" role="menuitem" data-act="open-terminal">Open terminal</button></div></details>`
- Native `<details>` (ponytail ladder): no new component. Enter and Space toggle it for free.
- In the delegated click handler (`:1798`), `case "open-terminal"` also does `removeAttribute("open")`. The emit stays the same `terminal:open` (`:1914`).
- Add one `document` click listener in mount that closes an open menu when the target is outside it.
- In the existing node `keydown` (`:1757`), Escape closes the menu and focuses the `<summary>`.
- The `session:reset` handler (`:1776`) closes the menu.
- Read-only: no new client gate. Resume isn't gated either; the server guard answers. Conventions rule 5.
- "External" stays where it is (D2).
- CSS, `ext_cr_detail.css`:
  - `.crd-termmenu{position:relative}`; summary `list-style:none` plus `::-webkit-details-marker{display:none}`.
  - `.crd-termmenu-list{position:absolute;right:0;top:100%;z-index:…}`.
  - The caret gets the same compaction as `.crd-row1-actions .crd-btn` in the 901-1300 band (`:1821-1824`) and the ≤900 band (`:1845`).
  - Never `display:none` in any band.
- Classic pane (`ext_launch.js:424-472`) and the CR overlay toolbar (`ext_cr_term.js:161-162`): **unchanged**. The ask names the button "beside the resume button", which is only the CR detail header. The classic "…here" pair is pinned by `test_term_launch.py:595-606`.

### Tests (stdlib unittest; RED on e6acfe7 unless marked *guard*)

**New `tests/test_resume_pty_budget.py`.** It reuses the `_S3` harness (`tests/test_term_s3.py:14-57`: fake `spawn`, `go()`, `fill()`).

| Test | What it asserts | Red on e6acfe7 because |
|---|---|---|
| `test_cold_resume_spawns_exactly_one_pty` | `go("S","resume")` → `spawns == [(top, ["claude","--resume","S"])]`; no `folder` pty in `PTYS` | 2 spawns |
| `test_repeated_resume_same_session_adds_none` | 5× `go("S","resume")` → same `tty` each time; `_live_count()==1` | live count is 2 |
| `test_three_sessions_each_clicked_twice_three_ptys` | S, T, U each resumed twice → `_live_count()==3` | 4 |
| `test_busy_root_shell_repeat_resume_one_overflow` (*guard*) | settled `folder_pty` busy with `fg` = T; 3× Resume S → exactly 1 new spawn | — |
| `test_slots_back_to_baseline` (*guard*) | after a cold resume, an `OSError` spawn and a 429 → `_SLOTS_RESERVED == baseline` | — |
| `test_429_only_at_real_cap` (*guard*) | `MAX_TERMS=3`, `fill(2)` → Resume S 200; Resume T 429 with `terminals` | — |

**New `tests/test_cr_detail_terminal_menu.py`** (source text, like `test_cr_detail_action_row_responsive.py`):
- `test_no_standalone_open_terminal_button`: no `crd-btn…data-act="open-terminal"` directly in `crd-row1-actions`.
- `test_menu_sits_right_after_resume`: `data-act="resume"…</button><details class="crd-termmenu">`, holding a `role="menuitem" data-act="open-terminal"`.
- `test_menu_has_accessible_name`: summary `aria-label` and `aria-haspopup`.
- `test_menu_closes_on_escape_outside_and_pick`: the Escape branch, the document listener, and the close in `case "open-terminal"`.
- `test_menu_css_all_bands`: the caret is in both media blocks; no `display:none`.
- `test_resume_never_opens_manage` (*guard*):
  - `_openCapDialog(` appears only at `:511`/`:655`, inside the 429 branches.
  - `_openManageDialog(` appears only at its three sites.
  - The `session:resume` body (`ext_cr_boot.js:770-777`) has no `dialog(`, `openManage` or `nav:terminals`.

**Existing tests that change (expected: they pinned the warm-on-resume regression):**
- In `tests/test_term_s3.py`:
  - `test_cold_resume_execs_claude_now_and_warms_root` (`:60`) becomes `…_no_warm`: 1 spawn, no settle call.
  - `test_resume_of_session_in_dedicated_returns_same_tty` (`:135`): `len(spawns)==1`; drop the `sp2` line.
  - `test_settled_warm_shell_is_reused` (`:147`): seed the shell with `self.folder_pty()` (settled) instead of a warm.
- `tests/test_term_root_concurrency.py:153` already allows `≤1` shell; tighten it to `0`.
- Unchanged: the `mode="new"` warm tests (`test_term_vt.py:1542`, `:1641`), `TestWarmSettle`, and `test_cr_detail_action_row_responsive.py` (its regex still matches the menu `<button>`).
- `make check` must print `selfcheck ok`. Prove every RED row by reverting the one-line `warm` gate and the SKELETON hunk.

### Rule-8 details
- **Sequence:** L1 plus its tests (server, one line) → L2 plus its tests → `make check` → `make serve` restart (a page and server change) → the Network check above.
- **Risky spot.** With no warm, a repo gets a root shell only from Open terminal or New. Resumes of different sessions are then dedicated ptys, one per session, and don't share a shell.
  - That still satisfies "one terminal per Resume".
  - It does lose the "next Resume finds a warm shell" speed-up.
  - **Fallback:** if the user wants sharing back, warm only when no other pty of that repo exists. Not recommended.
- **Known gap, same as base, no change:** a fork-retried pty is never a `_session_pty` hit (`:3946`). Document it.

### Decisions for the user
- **D1.** Drop the warm shell only for Resume (recommended, one line), or also for "+ New Claude session"? The latter deletes `_warm_root` and `TestWarmSettle`.
- **D2.** Put "External" into the new dropdown too, or leave it as is? Recommendation: leave it. The ask names only Open terminal.

## Review (opus)

Adversarial pass, 2026-11-17, on `e6acfe7`. Method: grep/sed of the code; a read-only `GET :8790/api/term/list`; existing modules run on a **scratch copy** (`/tmp/trr-review`, with the plan's one-line `warm` gate applied); and a scratch probe test. No repo source was touched.

**Root cause: holds, but it is incomplete.**
- Step A is verified:
  - `_openManageDialog` has only the callers `ext_cr_term.js:309`, `:924` and `:1293` (the `nav:terminals` bridge).
  - `session:resume` (`ext_cr_boot.js:770-777`) opens no dialog.
  - `mountInto` (`ext_vt.js:3919-3980`) sends one POST per call.
  - Slots pair up (`term_vt.py:3358`, `:3543`, `:3590`).
- On the copy with the fix applied, exactly 3 tests fail, the 3 `test_term_s3` tests the plan lists. Every other `open_pty` module stays green: root_concurrency, folder_*, open_pty_at_root, pending_pty_prompt, resume_fork_session, term_recreate, resume_all_jobs, agent_cli_jobs, term_vt_upgrade, cr_registry_fields and term_vt.
- What the plan misses: cfe81d8 also removed the **in-flight dedupe for the same session** (F1).

| # | Sev | Finding |
|---|---|---|
| F1 | **High** | Two concurrent Resumes of one session spawn two `claude --resume S`, **even after the fix**. |
| F2 | Med | Read-only mode would leave an empty caret on screen. The plan's "Resume isn't gated" is false. |
| F3 | Med | The fix overrides user decision E3 and changes the Resume model without asking the user. |
| F4 | Med | Proposed guard tests are source-regex/line-number checks. No unmocked spawn → list-count eval. |
| F5 | Low | Two existing warm tests become vacuous for resume. |
| F6 | Low | Resume and the caret can wrap apart, and the menu can clip. |
| F7 | Low | ARIA `menu`/`menuitem` without the menu keyboard pattern. Escape must come before the early return. |
| F8 | Low | "Open terminal" also sits beside Resume in the CR overlay and in the classic pane. The plan says it is only in the header. |
| F9 | Low | Fork-retry gap (`term_vt.py:3955`). Same as base. |

**F1: duplicate claude for one session.**
- **Defect.** The cold branch (`term_vt.py:3348-3362`) and the busy-root overflow (`:3507-3513`) reserve nothing per session. `_session_pty` misses until `_spawn_dedicated` puts the pty in `PTYS`.
- **Repro.** On the fixed copy: 2 threads, each `open_pty({session:"S", mode:"resume"})`, fake spawn delay 0.3 s.
  - Actual: spawns `[claude --resume S]×2`, ttys `sp1`/`sp2`, live 2.
  - Expected: 1 spawn, both callers answered with `sp1`.
- **Previous management.** Before cfe81d8, the second opener did `pending.wait` on `_FOLDER_SPAWNING[cwd]` and then hit the claimed `fg.session == S`, so it peeked instead of spawning.
- **Why it matters.** A double-click, a second tab, or Resume while the first POST is still in `session_cwd`/`place` I/O each produce two claudes. The second one is refused and fork-retried, so the user gets yet another terminal.
- **Direction.** Add a per-session in-flight reservation for `mode == "resume"`.
  - Must NOT change: cwd/new behaviour, slot accounting, or the `_session_pty` hit path.
- **Way.**
  - Add a module-level `_RESUME_SPAWNING = {}` next to `_FOLDER_SPAWNING`.
  - In `open_pty`'s `while True` loop, under `_LOCK`, right after the `_session_pty` miss:
    - If `_RESUME_SPAWNING.get(sid)` exists and this request has not waited yet, keep it as `sid_pending`, leave the lock, `sid_pending.wait(FOLDER_SPAWN_WAIT)`, set the flag and `continue`. The re-loop then finds the first opener's pty.
    - Otherwise set `own = _RESUME_SPAWNING[sid] = threading.Event()`.
  - Wrap the rest of `open_pty` in a `try/finally`: under `_LOCK`, delete the entry if it is still `own`, then call `own.set()`. This covers the cold branch, the claim/inject branch and the overflow branch.
  - `_agent_resume` and resume-all inherit it, because they go through `open_pty`.
- **Tests** (new module).
  - `test_concurrent_same_session_resume_one_spawn`: the repro above. RED today and with the plan's fix alone.
  - `test_concurrent_same_session_resume_busy_root_one_overflow`: settled `folder_pty` with `fg = {"session": "T"}`, `tcgetpgrp` returning a non-shell pid. Expect 1 spawn.

**F2: read-only.**
- **Defect.** `ext_cr.css:521-522` already hides `[data-act="open-terminal"]` and `[data-act="resume"]` under `html.tracker-readonly`. The new `<details>`/`<summary>` has no `data-act`, so a viewer sees a lone ▾ that opens an empty list.
- **Way.** Add `html.tracker-readonly .tracker-next .crd-termmenu` to that selector list.
- **Test.** Extend `tests/test_cr_readonly_ui.py` to assert the selector sits in the `display: none` rule. RED before.

**F3: the E3 override.**
- `reports/terminal-at-root.md` clause 1 and E3 ("Include S3") made the warm shell the user's own design.
- After the fix, a cold Resume is a dedicated `overflow` pty that disappears when claude exits. No root shell exists unless the user picks Open terminal. That matches neither earlier model:
  - before 4da60f3: a worktree shell, with claude typed into it;
  - before cfe81d8: the root shell, with claude typed in after the rc files settle (11–13 s).
- **Direction.** No code change. Add **D3**:
  - (a) the plan's choice: fast, 1 pty, recommended;
  - (b) restore the pre-S3 typed-into-root behaviour: slower, but the shell is shared and persists.

**F4: tests that would have caught cfe81d8.**
- `test_resume_never_opens_manage` greps line numbers (`:511`/`:655`). It breaks on any edit and proves no behaviour.
- **Way.**
  1. A Node test in the style of `tests/test_cr_manage_terminals_poll.py`: load `ext_cr_term.js` with a stubbed `ExtVT.mountInto` and a fake `fetch`, then call `CR.term.open(sid, {mode: "resume"})`. Assert:
     - `mountInto` is called once with `{session, mode: "resume"}`;
     - `ctx.dialog` is never called with `"manage-terminals"`.
     Drive `ext_vt.js` `mountInto` with list `[]` and expect exactly 1 POST `/api/term/pty`.
  2. An eval in `tests/test_integration.py` `TestServerEndToEnd`, using the in-process server, real `spawn`, real `_warm_root` and real `_folder_settled`, with `SHELL=/bin/sh`:
     - patch `term_gate.resume_argv` to `[sys.executable, "-c", "import time; time.sleep(30)"]`;
     - patch `session_cwd`/`recorded_run_dir` to a tmp worktree;
     - POST resume, sleep 1.5 s, then `/api/term/list`. Expect 1 row; it is 2 on e6acfe7. Kill the ptys in `finally`.

**F5.** `test_warm_skipped_at_cap` and `test_warm_never_takes_the_last_slot_a_real_opener_needs` (`test_term_s3.py:104`, `:157`) drive `resume`. After the fix they pass because warm is gone, so they no longer test the slot logic. **Way:** switch both to `mode="new"`, so the warm path kept by D1 keeps its slot coverage.

**F6: layout.**
- `.crd-row1-actions` uses `flex-wrap: wrap`, and is `width: 100%` at ≤1024 (`ext_cr_detail.css:348-353`, `:1800`). The caret can wrap away from Resume.
- A `right:0` list on a caret at the start of a line overflows to the left, where `.crd`'s `overflow: hidden` (`:35`) clips it.
- **Way.**
  - Wrap Resume and the `<details>` in `<span class="crd-resume-split">` with `display:inline-flex; flex-wrap:nowrap; position:relative`.
  - Give the list `position:absolute; left:0; top:100%; z-index`, and do not make `details` relatively positioned.
  - The compaction is inherited, because the summary carries `.crd-btn`.
- **Test.** `test_menu_sits_right_after_resume` asserts both sit inside `.crd-resume-split`, and that the CSS has `flex-wrap: nowrap` for it.

**F7: ARIA and Escape.**
- Drop `role="menu"`, `role="menuitem"` and `aria-haspopup`. A native disclosure plus a `<button>` is correct as it is, and the test must not pin `aria-haspopup`.
- The Escape branch must go **before** the `Enter`/`Space` early return at `ext_cr_detail.js:1758`, and act only on `ev.target.closest(".crd-termmenu[open]")`.

**F8: other surfaces.**
- "Open terminal here" sits beside "Resume terminal here" in the CR overlay control bar (`ext_cr_term.js:161-162`) and in the classic pane (`ext_launch.js` ~433-438).
- **Direction:** no code change. Add **D4** (also apply the split to the CR overlay?), with the recommendation "header only". Note that in the header an Auggie session gets Resume as the primary action, though Resume is not gated for Auggie there. That is pre-existing; no change.

**F9: fork-retry gap.**
- `_session_ptys` skips `p.forked and not p.folder`. Repeated Resume of a session that is live elsewhere therefore forks again on every click.
- **Direction:** no change, same as base. Document it in the commit message as a follow-up.

**Nit.** Step A's Network check is wrong: `open()` also fires `_refreshRunningList()` and the poll. Expect exactly one POST `/api/term/pty` and the list growing by 1, with no fixed GET count.

### Overall clean plan

Deltas against the original plan:
- **L1:** the one-line `warm` gate, **plus** the F1 per-session reservation (`_RESUME_SPAWNING`, a try/finally release).
- **L2:** the split group `.crd-resume-split` (F6); no `menu` ARIA roles (F7); Escape placed before the early return (F7); the read-only selector (F2).
- **Tests:**
  - add F1 ×2 to `tests/test_resume_pty_budget.py`;
  - replace the regex guard with the F4 Node test;
  - add the F4 real-spawn eval to `test_integration.py`;
  - switch the F5 tests to `new`;
  - add the F2 assertion to `test_cr_readonly_ui.py`;
  - keep the plan's `test_term_s3` edits and the `root_concurrency:153` tightening (verified: those are the only breakages).
- **Decisions:** D1 and D2 as written, plus D3 (F3) and D4 (F8).

Steps:
1. Change the L1 `warm` gate and add the F1 reservation.
2. Server tests: `test_resume_pty_budget` (plan rows + F1), the S3/F5 edits, the root_concurrency tightening, and the F4 eval. Run each module in its own process.
3. L2 markup, CSS and handlers (F2, F6, F7).
4. UI tests: `test_cr_detail_terminal_menu` (source checks without line numbers), the F4 Node test, the F2 read-only assertion, and `test_page_bundle` (stray `*/`, load-time errors).
5. Prove RED: revert the `warm` gate, then the F1 reservation, then the SKELETON hunk, then the read-only selector. The matching rows must go red each time.
6. Run `make check` (with `unset TRACKER_AUTH`), restart with `make serve`, then do the Network and list check: one Resume adds 1 row, and a double-click still adds 1.

## Reconciled plan + verdicts (main thread, 2026-11-17)

Spot-checks: `ext_cr.css:520-523` read-only hide list confirmed (no `.crd-termmenu`); `_FOLDER_SPAWNING` (`term_vt.py:1316`) is the precedent F1 mirrors; board-tile Resume (`ext_cr_boot.js:827-860` `answerSession`) posts `/api/term/open` = **external OS window** (`term_launch.py:167`), not a tracker pty — out of this regression; `_session_ptys` (`term_vt.py:3956`) skips forks on purpose.

| # | Verdict | Reason / trim |
|---|---|---|
| Root cause (cfe81d8 warm on cold Resume = 2 ptys/click; Manage opened by ☰/pill, not Resume) | **confirmed** | live `/api/term/list` pair + caller trace by both agents |
| F1 double Resume → 2 claudes | **confirmed** | probe repro; mirror `_FOLDER_SPAWNING` exactly (Event + try/finally), resume mode only |
| F2 read-only empty caret | **confirmed** | one selector added to the existing list |
| F3 overrides earlier "Include S3" | **confirmed → D3** | a real product choice |
| F4 regex/line-number guards prove nothing | **confirmed, fix trimmed** | Node test + real-spawn eval accepted; eval polls `/api/term/list` until stable (≤5 s) instead of a fixed `sleep 1.5`; no line-number pins anywhere |
| F5 two S3 tests go vacuous | **confirmed** | switch to `mode="new"` |
| F6 caret wraps/clips | **confirmed** | `.crd-resume-split` inline-flex nowrap |
| F7 ARIA menu roles / Escape order | **confirmed** | plain disclosure; Escape before the early return |
| F8 other "Open terminal here" beside "Resume terminal here" | **confirmed → D4** | |
| F9 fork re-click forks again | **false alarm for this fix** | same as base and by design (a fork is a new session id); documented as a follow-up, no change |
| Missed by both | — | board-tile external Resume path (not a pty; unchanged). Network-check nit accepted (count POSTs, not GETs). |

### Reconciled plan
1. **L1 server** (`term_vt.py` `open_pty`): `warm = mode != "resume" and …` at `:3357`; add `_RESUME_SPAWNING` per-session in-flight Event beside `_FOLDER_SPAWNING`, set after the `_session_pty` miss, released in a `try/finally`; second opener waits ≤`FOLDER_SPAWN_WAIT` then re-loops into the `_session_pty` hit.
2. **L2 UI** (`ext_cr_detail.js` SKELETON + handlers, `ext_cr_detail.css`, `ext_cr.css`): delete standalone Open terminal; `<span class="crd-resume-split">` = Resume (solid) + `<details class="crd-termmenu">` caret (`aria-label`, no menu roles) holding `<button data-act="open-terminal">Open terminal</button>`; closes on pick / outside click / Escape / `session:reset`; read-only hides `.crd-termmenu`; never `display:none` in any band.
3. **Tests** (each proven RED by reverting its hunk): new `tests/test_resume_pty_budget.py` (cold resume = 1 spawn; 5× same session = 1 pty; S/T/U ×2 = 3; busy-root ×3 = 1 overflow; concurrent same-session = 1 spawn ×2 variants; slots back to baseline; 429 only at real cap); new `tests/test_cr_detail_terminal_menu.py` (markup, split group, close paths, CSS bands — no line numbers); Node behavioural test (`CR.term.open(sid,{mode:'resume'})` → `mountInto` once, 1 POST, never `manage-terminals`); real-spawn eval in `tests/test_integration.py` (one Resume → +1 row); `test_cr_readonly_ui.py` assertion; expected edits to 3 `test_term_s3.py` tests + F5 switch + `test_term_root_concurrency.py:153` → 0.
4. `make check` (unset TRACKER_AUTH, per-module if OOM) → opus impl review → `/branch-sync` → push `terminal-resume-regression` to `personal`.

### Decisions for the user
- **D1** warm root shell: drop for Resume only (rec.) / also for New.
- **D2** "External": leave in place (rec.) / move into the dropdown.
- **D3** what cold Resume opens: (a) one dedicated terminal, instant (rec.) / (b) restore pre-S3: claude typed into the shared repo-root shell after it settles (~11–13 s, shell persists after claude exits).
- **D4** scope of the dropdown: CR detail header only (rec., the literal ask) / also the CR overlay bar and classic pane "Open terminal here".

## User decisions (2026-11-17, sign-off round 1) — all four override the recommendation → re-plan loop
- **D3 = (b) "Restore older shared shell"**: cold Resume types claude into the shared repo-root shell after it settles (pre-S3 behaviour), not a dedicated pty.
- **D1 = "Resume and New"**: remove the warm root shell entirely (`_warm_root` and its tests).
- **D4 = "Everywhere"**: the Open-terminal dropdown beside Resume also on the CR overlay bar (`ext_cr_term.js:161-167`) and the classic pane (`ext_launch.js:424-472`).
- **D2 = "Move it into the dropdown"**: External goes into the dropdown too.

## Plan v2 (opus)

Grounded on `e6acfe7`; replaces L1/L2. **Invariant:** one Resume (or a double click / two tabs) of S ⇒ ≤1 terminal running S and no shell beyond the one root shell hosting it.

### What cfe81d8 changed in `open_pty`
- Added the S3 loop branch (`term_vt.py:3350-3362`: resume/new with no or an unsettled shell reserves `2 if warm else 1` slots, breaks `cold`) and `if cold:` (`:3386-3394`: `_spawn_dedicated(held=True)` + `_warm_root` in `finally`).
- **Deleted** the pre-S3 branch `if busy_what is None and not settled:` (claim `fp.fg`, `fp.starting`, `fp.deferred = Thread(_deferred_folder_start …)`) and `_deferred_folder_start` (settle → `_inject_argv(deferred=True)` → `_start_backstop`).
- Added `_warm_root`, `_slots_add/_release`, `_folder_settled(wedge_close=…)`, `_slow_start_note`. `d263707` set `free >= 3`; `8aeee07` put `login_sid` in the S3 condition (/login must stay dedicated).
- Still present from pre-S3: `_FOLDER_SPAWNING` reserve/wait (`:3363-3384`), claim (`:3443-3462`), peek (`:3471`), sync type, busy → overflow, `_inject_argv(deferred=True)` (`:2051`), `Pty.deferred` (`:1465`).

### S1 — server, `aitracker/term_vt.py` (D3 = b, D1)
1. Replace the S3 block with `if login_sid:` → existing `free < 1` 429 → `_slots_add(1)` → `dedicated_now = True; break`; after the loop `if dedicated_now: return handler._json(*_spawn_dedicated(…, held=True, login_sid=login_sid))`. `cold`, `warm` and the `_warm_root` `finally` go.
2. Restore `_deferred_folder_start(fp, argv, sid, mode, forked, cols, rows)` and the deferred branch (before `if busy_what is None:` `:3479`) verbatim from `cfe81d8^`.
3. Revert `_folder_settled` to `(fp, deadline, on_slow=None)`; the cwd settle thread (`:3414`) passes `(fp, deadline, _slow_start_note(fp))`.
4. Delete `_warm_root` (`:3562-3590`; sole caller `:3392`). `grep -rn _warm_root aitracker` must be empty.
5. Keep the cap guarantee: pre-S3 overflow/folder spawns checked the cap without reserving, so a burst overshot `MAX_TERMS` (`test_cold_burst_never_exceeds_cap` goes RED). Overflow (`:3510`): `_slots_add(1)` in the same `_LOCK` section + `held=True`. Folder reservation (`:3376`): `_slots_add(1)`, `_slots_release()` in its `finally` (`:3409`).
6. **F1 per-session reservation — still needed.** The restore alone dedupes no/settling/idle root shells (2nd opener waits on `_FOLDER_SPAWNING`, then the `_LOCK` claim picks one claimant and the other peeks, or `_session_ptys` `:3961` hits the pending claim). It does **not** dedupe a busy root (two overflow spawns) or `_swap_in`. So: `_RESUME_SPAWNING = {}` beside `_FOLDER_SPAWNING` (`:1316`); `mode=="resume"` only, after the `_session_pty` miss: another opener's Event and not yet waited → wait outside the lock `FOLDER_SPAWN_WAIT`, `continue`; else create `own` once; `try/finally` around the rest: delete if still `own`, `own.set()`.

**After the fix.** No root shell → one root `$SHELL -l` spawned and claimed, tty returned at once (`starting`), claude typed when it settles. Settled idle → typed now. Busy with another session → one overflow pty; its next Resume hits `_session_pty`. Already running → peek. /login → dedicated. cwd → unchanged. **"+ New Claude session" is pre-S3 too** (with warm gone, S3's dedicated cold New leaves no shared shell, which D3 rejected). Resume-all, K sessions/repo: 1 root + K−1 overflow (today K+1).

### S2 — dropdown on all three surfaces (D4, D2)
**Seam: one global helper + one CSS block, used by all three.** `page.build_page` puts `app.js` first and all CSS in one `<style>`; `app.js` already exports `window.ico` to the ext files (precedent). Three hand-rolled open/close/Escape copies would be the forked capability tracker-gap forbids. No framework.
- `app.js`: `termSplit(primaryHtml, itemsHtml, caretCls)` → `primaryHtml` alone when `itemsHtml` is empty, else `<span class="tsplit">primary<details class="tsplit-menu"><summary class="<caretCls> tsplit-caret" aria-label="More terminal actions" title="More terminal actions"><span aria-hidden="true">▾</span></summary><div class="tsplit-list">items</div></details></span>` (plain disclosure, no menu roles — F7). `termSplitSync(split)` hides the `<details>` when no list item is un-`[hidden]`; `termSplitClose(except)`. Two capture listeners on `document`: `termSplitOnClick` (item click closes its menu; outside click closes all) and `termSplitOnKey` (Escape with a menu open closes it, focuses its summary, `stopPropagation`+`preventDefault` so the overlay's Escape `ext_cr_term.js:246` and `app.js:2595` don't also fire; none open → no-op; F7's "Escape before `:1758`" is moot). Export on `window`.
- `app.css`: `.tsplit{display:inline-flex;flex-wrap:nowrap;position:relative}` (F6); `.tsplit-caret{list-style:none}` + `::-webkit-details-marker{display:none}`; `.tsplit-list{position:absolute;left:0;top:100%;z-index:40;display:flex;flex-direction:column;min-width:100%;…}`; `.tsplit-menu[hidden]{display:none}`.
- **CR header** (`ext_cr_detail.js` SKELETON `:1380-1383`): `termSplit(Resume crd-btn-solid, Open terminal + External[hidden] as crd-btn-bare tsplit-item, "crd-btn crd-btn-outline")`, then Queue a note. `data-act` handlers (`:1914-1921`) and `:2544` unchanged; `session:reset` calls `termSplitClose()`. The caret carries `.crd-btn` → both compaction bands. `.crd{overflow:hidden}` (`ext_cr_detail.css:35`): a `left:0` downward list stays inside.
- **CR overlay bar** (`ext_cr_term.js:160-168`): `primary` group = `termSplit(resume-here[hidden] + open-here, ext-terminal + ext-resume, "cr-term-btn cr-term-btn-outline")`; delete the `external` group and its divider; `el.split`/`el.splitList` at `:258`. New `_placeOpenHere(resumable)` beside `:1123`: resumable → `open-here` moves to the list top, `resume-here` solid; else (Auggie) Open terminal here stays primary; then `termSplitSync`. `_syncControlVisibility` (`:1136`) ends with `termSplitSync`; overlay `close()` calls `termSplitClose()`. `.cr-term-shell{overflow:hidden}` (`ext_cr_term.css:43`): the bar is the top row, the list drops into the frame (z-index above it).
- **Classic** (`ext_launch.js` `render` `:424-472`): `const openHtml`/`resumeHtml` before the `localOnly()` gate; `nativeHtml` unchanged (ids, `#extnative`); `const vtHtml = termSplit(resumable ? resumeHtml : openHtml, (resumable ? openHtml : "") + nativeHtml, "mini extlaunchbtn")`; `el.innerHTML = vtHtml + (homeNote…)`. **No Resume (Auggie) → primary is Open terminal here**; with no native buttons either, it renders alone (no caret). The 403 latch (`:76`) adds `termSplitSync(nat.closest(".tsplit"))`. The pane scrolls; verify live.
- **Read-only (F2):** add `html.tracker-readonly .tracker-next .crd-row1-actions .tsplit` to `ext_cr.css:520-539`. Overlay/classic have no read-only hides and their items stay visible → no empty caret; same as base.

### Tests (RED on `e6acfe7` unless *guard*; prove by reverting the hunk)
**New `tests/test_resume_pty_budget.py`** (`_S3` harness + 3 surviving S3 tests move here):
- `test_cold_resume_one_root_shell_claimed`: `spawns == [(root,[SHELL,"-l"])]`, `obj.folder`, `fp.fg.session=="S"`, `fp.deferred` alive (today: 2 spawns, not folder).
- `test_cold_resume_types_claude_after_settle`: join `fp.deferred`; typed line has `--resume S` + the `cd "$0"` wrapper (today: none).
- `test_repeated_resume_same_session_adds_none` (5× → same tty, live 1; today 2); `test_three_sessions_twice_three_ptys` (today 4); `test_cold_new_types_launcher_into_root_shell` (today dedicated + warm).
- `test_concurrent_same_session_resume_one_spawn` (2 threads, 0.3 s spawn → 1 spawn, same tty); `test_concurrent_same_session_busy_root_one_overflow` — RED on e6acfe7 **and** with S1.1-5 alone, proving S1.6.
- *Guards:* `test_slots_back_to_baseline` (OSError, 429, login), `test_429_only_at_real_cap`.

**New `tests/test_term_split_menu.py`** (Node brace-match idiom of `test_cr_manage_terminals_poll.py`, minimal fake DOM): markup; no `role="menu"`; empty items → primary alone; item/outside click closes; Escape closes + focuses summary + stops propagation; none open → propagation untouched; `termSplitSync` hides an all-hidden list. Source checks, no line numbers: each surface calls `termSplit(`; no `data-act="open-terminal"`/`data-group="external"` outside a `.tsplit-list`; `.tsplit` `flex-wrap: nowrap`, never `display:none` in the detail bands. **F4 Node test** (same file): `CR.term.open(sid,{mode:"resume"})` → `mountInto` once, never `dialog("manage-terminals")`; `ext_vt.js` `mountInto` with list `[]` → exactly 1 POST `/api/term/pty`.

**F4 real-spawn eval** (`test_integration.py` `TestServerEndToEnd`): `SHELL=/bin/sh`, `term_gate.resume_argv` → `[sys.executable,"-c","import time;time.sleep(30)"]`, `session_cwd` → tmp dir. POST, 2-thread double POST, second Resume → `/api/term/list` polled until stable (≤5 s) = 1 row, same tty (e6acfe7: 2). Kill ptys in `finally`.

**Existing tests that change — all expected (they pin the S3 contract D1/D3 reverse):**

| File | Change |
|---|---|
| `test_term_s3.py` | removed. Deleted (pin warm): `…execs_claude_now_and_warms_root`, `…during_warm…`, `…while_reserved…`, `test_warm_skipped_at_cap`, `test_settled_warm_shell_is_reused`, `test_warm_never_takes_the_last_slot…`, `TestWarmSettle` ×3. Rewritten: `test_resume_of_session_in_dedicated_returns_same_tty` (root claimed, 1 spawn). Moved unchanged: `test_cold_burst_never_overshoots_cap`, F7 `…foreground_job_goes_dedicated…`, `test_cwd_mode_cold_still_opens_shell` |
| `test_term_root_concurrency.py:153` | `test_k_simultaneous_resumes_cold` → 1 root + K−1 dedicated, bounded waits allowed. `test_cold_burst_never_exceeds_cap` unchanged = *guard* for S1.5 |
| `test_folder_terminal.py` | restore `TestFreshFolderShellQueuesInsteadOfOverflow` ×5 from `cfe81d8^`; revert `…goes_dedicated_without_typing` → `…defers_not_overflows`; `_settle` (`:1159`) drops `False,` |
| `test_term_vt.py` | `:1542`, `:1641` revert ("spawn only the shell, claude typed"); `TestGatewayLaunch._await_typed`/`_open` + tests at `:6187`, `:6202` revert. `:5690` unchanged |
| `test_pending_pty_prompt.py:64` | drop the `_warm_root` patch |
| `test_term_launch.py` | `…back_to_four_buttons`: assembly string `vtHtml +`, still 4 `<button`; `…built_before_the_localonly_gate` → `const openHtml =` |
| `test_cr_readonly_ui.py` | `test_new_selectors_hidden_only_under_readonly` adds `.crd-row1-actions .tsplit` |

Verified unchanged: `test_cr_detail_action_row_responsive.py` (regex matches the item `<button>`), `test_term_vt_client.py:281`, `test_folder_swap.py`, `test_open_pty_at_root.py`, `test_cr_board_resume_button.py`. Any other post-S1 failure is a rule-3 regression round, not assumed expected.

### Sequencing
1. S1.1-5 + server-test edits (one module per process). 2. S1.6 + F1 tests. 3. Eval. 4. S2 helper/CSS → surfaces → read-only → UI tests + `test_page_bundle`. 5. RED proofs: re-add S3 block; revert S1.5, S1.6, each surface hunk, the selector. 6. `unset TRACKER_AUTH; make check` → `make serve` → live: one Resume = +1 row/+1 POST; double click = +1.

### Risky spots + fallbacks
- **Cold Resume waits ~11–13 s for zsh rc files.** The user sees the root shell's tty at once (`starting` placeholder), then at 10 s "waiting for your shell's startup files (running: …) — claude starts at the prompt". Pre-S3; the trade D3(b) accepts.
- **Never settles in `FOLDER_STARTUP_WAIT` (300 s):** pre-S3 note "shell never reached its prompt — claude was not started", claim released; the next Resume types or overflows. Fallback (not planned): one dedicated pty on that give-up.
- **Root busy with another session:** one overflow pty; repeats hit `_session_pty`; double clicks covered by S1.6.
- **F5 moot** (warm deleted). **F9:** no change; commit follow-up.

### New decision
None required.

## Review v2 (opus)

Adversarial pass, 2026-11-17, on `e6acfe7`. Method: grep/sed; S1.1-5 (verbatim from `cfe81d8^`), then S1.6, applied to scratch copies (`$TMPDIR/trr-v2`, `trr-v2c`) with a scratch probe module; one module per process. No repo source touched.

**Server restoration: sound.**
- `cfe81d8..e6acfe7` touches `term_vt.py` only in d263707 (the `free >= 3` line, gone with the block), 46c61ac (`upgrade_candidates(light)`, `resume_all_plan`) and 8aeee07 (`login_sid`). It never touches `term_gate.py`.
  - 46c61ac's `needs_slot` and `_ra_need` (`term_vt.py:4624`) already assume a resume is typed into an idle folder shell. They match pre-S3.
  - 8aeee07 survives through `if login_sid:` → dedicated.
  - `_with_prompt` (`:3119`) drops control characters, so e6acfe7's pending-work prompt types safely.
- With S1.1-6 plus the edits v2 lists, every other `open_pty` module is green (folder_*, open_pty_at_root, pending_pty_prompt, resume_fork_session, term_recreate, resume_all_*, agent_cli_jobs, term_vt_upgrade, cr_registry_fields, login_session_cleanup, cr_routes, tunnel_readonly, term_vt_exec, integration, term_launch, term_vt_client, term_home, page_bundle).
- The pre-S3 `TestFreshFolderShellQueuesInsteadOfOverflow` / `TestUnsettled*` classes (13 tests), copied from `cfe81d8^`, pass unchanged.
- The `test_term_vt` failures are exactly the 4 that v2 lists (`:1507`, `:1619`, `:6175`, `:6194`).
- `test_cold_burst_never_exceeds_cap` is meaningful. With S1.5 reverted it goes RED (`6 not <= 4`).

**Invariant, measured on the scratch copy (S1.1-6):**

| Case | Result |
|---|---|
| No root shell, double click | 1 root shell spawned and claimed; both get `sp1` |
| Root starting (cwd open, unsettled) | claimed, 0 spawns, same tty |
| Root idle, settled | 1 line typed, 0 spawns |
| Root busy with T, double click | **2 claudes without S1.6 → 1 with it** |
| Second click during settle | `_session_pty` hits the pending claim (`attached:true`), 0 spawns. T during S's settle: 1 overflow; T again: a hit |
| Slots | back to baseline in every probe |

| # | Sev | Finding |
|---|---|---|
| R1 | **High** | The classic dropdown closes itself every ≤2 s. |
| R2 | Med | Overlay: External vanishes whenever a terminal is attached. |
| R3 | Med | CR header: an Auggie session gets a primary that always fails, and Open terminal is hidden behind the caret. |
| R4 | Med | S1.6's "way" can't be built as written. |
| R5 | Low | Two expected test breaks are missing from v2's table. |
| R6 | Low | Some RED/guard labels are wrong. |
| R7 | Low | The real-spawn eval is not hermetic. |
| R8 | nit | Two slow-start notes can appear. |

**R1 — classic re-render.**
- **Defect.** `ext_launch.js` `render` rewrites `el.innerHTML` (`:463`) on every poll: `app.js:1490` → `renderFor` (`:1585`) → `EXT.forEach` (`:2158`). An open `<details class="tsplit-menu">` is replaced by a closed one, and focus is lost.
- **Repro.** Open the caret on the classic pane, wait 2 s.
  - Actual: the menu closes.
  - Expected: it stays open until you pick, click outside or press Escape.
- **Direction.** Carry the open state across rebuilds. Must NOT change the ids or handlers.
- **Way.** In `render`:
  - Before the rebuild: `const was = !!el.querySelector(".tsplit-menu[open]"), foc = document.activeElement && document.activeElement.closest && document.activeElement.closest("#ext_launch .tsplit-caret");`
  - After it: `const m = el.querySelector(".tsplit-menu"); if (m && was) m.open = true; if (m && foc) m.querySelector("summary").focus();`
- **Test.** Node harness in the `test_page_bundle._HOME_NOTE_HARNESS` style. The fake `el` reports an open menu, then a fresh stub after the rebuild. Assert the fresh stub has `open === true`. RED on v2 as written.

**R2 — overlay External while attached.**
- **Defect.** `_syncStatusBar` sets `el.primaryGroup.hidden = st.attached` (`ext_cr_term.js:1176`). v2 puts `ext-terminal`/`ext-resume` into that group's split.
- **Repro.** Attached terminal, local host.
  - Actual: no External at all.
  - Expected (today): External terminal/resume stay visible (separate `external` group, `:165`).
- **Direction.** Hide only the two "…here" buttons when attached. Keep the split.
- **Way.**
  - Replace `:1176` with `el.openHere.hidden = el.openHere.hidden || st.attached` (ditto `resumeHere`; recompute the un-attached state from `_placeOpenHere`), then `termSplitSync(el.split)`.
  - `termSplit` gains a `soloLabel` argument. `termSplitSync` toggles `.tsplit-solo` when no primary is visible, which shows "External ▾" on the caret.
- **Test.** Node extract of `_syncStatusBar` + `termSplitSync` with `st.attached = true`. Assert `extTerminal` has no hidden ancestor and `openHere.hidden`. RED on v2.

**R3 — CR header, Auggie.**
- **Defect.** The header's Resume is ungated (`ext_cr_detail.js:1916-1921`), and the server answers 400 "resume is Claude-only" (`term_vt.py` open_pty preamble). v2 makes Resume the primary for every session. The overlay and classic handle Auggie; the header doesn't.
- **Direction.** Mirror the overlay: a non-Claude id gets Open terminal as its primary. Must NOT add a new policy. Reuse the same Claude-id rule the overlay and classic use (same as base).
- **Way.**
  - SKELETON primary = Resume + a second `crd-btn-solid data-act="open-terminal" hidden`.
  - The list holds the Open terminal item + External.
  - In the header render next to `:2544`, toggle: resumable → Resume shown, primary Open hidden; else the reverse, with the list Open item hidden. Then `termSplitSync`.
- **Test.** In `test_term_split_menu.py`, a Node extract of that toggle: an `auggie:` id → `[data-act=resume]` hidden and the primary open-terminal visible. RED on v2.

**R4 — S1.6 way.**
- **Defect.** The wait sits "inside the loop after the `_session_pty` miss". That point is mid-way through a `with _LOCK` block whose tail does the folder reserve and the 429s, so a `continue` there needs that block restructured. "try/finally around the rest" re-indents about 200 lines of `open_pty`.
- **Direction.** Same semantics, smallest hunk.
- **Way (proven on scratch).**
  - Make `open_pty` a wrapper: `own=[]; try: return _open_pty(handler, parsed, body, own)` / `finally:` for each `(k, ev)` in `own`, under `_LOCK` delete `_RESUME_SPAWNING[k]` if it is still `ev`, then `ev.set()`.
  - In `_open_pty`'s `if mode == "resume":` block, right after `resolve_spawned`: under `_LOCK`, `other = _RESUME_SPAWNING.get(sid)`. If there is none, create and register `own`. Outside the lock, `if other: other.wait(FOLDER_SPAWN_WAIT)`.
  - The loop's `_session_pty` then finds the first opener's pty or its pending claim.
  - Every exit (400/404/409/429/500, exceptions) releases.
- **Test.** `test_concurrent_same_session_busy_root_one_overflow`: 2 spawns → 1. Scratch P2.

**R5 — missed breaks.**
- `test_term_root_concurrency.TestGuards.test_same_session_twice_one_tty` (`:205-210`) pins 1 claude spawn; after S1 it gets 0. Rewrite: same tty, the only spawn is the root `[SHELL,"-l"]`, one `--resume S0` typed.
- `test_page_bundle._HOME_NOTE_HARNESS` (`:307-321`) injects the globals `render` uses. It must add a `termSplit` stub, or it throws once render calls it.

**R6 — labels.**
- `test_concurrent_same_session_resume_one_spawn` (cold) is GREEN with S1.1-5 alone (P1). It is RED on `e6acfe7` only. The busy-root test alone proves S1.6.
- The F4 Node tests (`mountInto` once, 1 POST, no manage dialog) are GREEN on `e6acfe7`. Mark them *guard*.
- S1.5's red proof is `test_cold_burst_never_exceeds_cap`. The moved `test_cold_burst_never_overshoots_cap` stays green without S1.5.

**R7 — eval hermeticity.**
- `SHELL=/bin/sh -l` sources the developer's `~/.profile`. Set `HOME` to a tmp dir and unset `ENV`.
- The real settle takes ≥1.5 s. Poll until the list is stable for 1 s, within ≤10 s (not 5; the gate is load-sensitive).

**R8 — two slow-start notes.** A Resume that claims a cwd shell opened less than 10 s earlier gets two notes: the cwd thread's `_slow_start_note` and the deferred `slow`. No change; it is cosmetic. Document it.

Checked and fine:
- Load order: `app.js` is concatenated before the `ext_*` files.
- No capture-phase keydown listeners exist, so the capture `stopPropagation` beats `:246` and `app.js:2595`.
- The shared helper is the right seam, not overengineered.

### Overall clean plan v2

Deltas against v2:
- **S1.6** uses R4's wrapper and pre-loop reservation.
- **S2 classic** carries the open menu and focus across the poll rebuild (R1).
- **S2 overlay** hides only the "…here" buttons when attached, plus a solo "External ▾" caret (R2).
- **S2 header** gets the Auggie primary swap (R3).
- **Tests:**
  - add the R1, R2 and R3 Node tests;
  - rewrite `test_same_session_twice_one_tty`;
  - add the `termSplit` stub to `_HOME_NOTE_HARNESS`;
  - fix the labels (R6);
  - make the eval hermetic (R7).
- No new user decision.

Steps:
1. S1.1-5 plus the listed server-test edits and `test_same_session_twice_one_tty`. Run each module in its own process.
2. S1.6 (R4) plus the F1 tests. RED proof: remove the wrapper and the reservation → the busy-root test fails.
3. The real-spawn eval (R7).
4. S2: the `app.js` helper and CSS → header (R3) → overlay (R2) → classic (R1) → the read-only selector → UI tests, `_HOME_NOTE_HARNESS` and `test_page_bundle`.
5. RED proofs:
   - re-add the S3 block;
   - revert S1.5 → `test_cold_burst_never_exceeds_cap`;
   - revert S1.6;
   - revert each surface hunk;
   - revert the selector.
6. `unset TRACKER_AUTH; make check` (per module if OOM) → `make serve` → live checks:
   - one Resume = +1 row and 1 POST;
   - a double click = +1;
   - the classic menu stays open for more than 2 s;
   - External stays reachable while attached.

## Reconciled plan v2 (main thread, 2026-11-17)

| # | Verdict | Note |
|---|---|---|
| Server restoration (pre-S3 deferred path, warm removed) | **confirmed** | scratch-applied; 13 pre-S3 tests green; post-cfe81d8 commits independent |
| R1 classic menu closes on 2 s poll | **confirmed** | carry `open`/focus across `render` |
| R2 overlay External hidden while attached | **confirmed** | hide only the "…here" buttons; solo "External ▾" caret |
| R3 header Auggie primary always 400 | **confirmed** | swap primary to Open terminal for non-Claude ids, reusing the existing Claude-id rule |
| R4 S1.6 not buildable as written | **confirmed** | thin `open_pty` wrapper + pre-loop reservation (proven on scratch) |
| R5 two missed test breaks | **confirmed** | |
| R6 wrong RED/guard labels | **confirmed** | |
| R7 eval reads ~/.profile | **confirmed** | tmp HOME, unset ENV, poll ≤10 s |
| R8 double slow-start note | **doc only** | cosmetic, same as pre-S3 |
| Missed by both | — | none found beyond v1's (board external Resume, unchanged) |

**Plan to implement = Plan v2 + "Overall clean plan v2" (Review v2).** No new user decision; D1–D4 stand as sign-off.
Implementation split (disjoint files, parallel, no commits by agents): **A server** = `term_vt.py` + server tests + real-spawn eval; **B UI** = `app.js`/`app.css` helper + header/overlay/classic + read-only CSS + UI tests.

## Implementation A (server) — 2026-11-17

**`aitracker/term_vt.py`** (no `term_gate.py` change)
- `open_pty` is now a thin wrapper over `_open_pty(handler, parsed, body, own)`; the wrapper releases `_RESUME_SPAWNING` (new dict beside `_FOLDER_SPAWNING`) on every exit (R4).
- S1.6: in `_open_pty`'s `mode == "resume"` block, after `resolve_spawned`: under `_LOCK` register `own` for the session if none, else wait `FOLDER_SPAWN_WAIT` outside the lock; the loop's `_session_pty` then finds the first opener's pty/claim.
- S1.1: the S3 cold block replaced by `if login_sid:` -> 429 check -> `_slots_add(1)` -> `dedicated_now`; after the loop `_spawn_dedicated(..., held=True, login_sid=...)`. `cold`/`warm`/`reserved`-warm and the `_warm_root` `finally` removed.
- S1.2: `_deferred_folder_start` and the `if busy_what is None and not settled:` deferred branch restored verbatim from `cfe81d8^`.
- S1.3: `_folder_settled(fp, deadline, on_slow=None)` restored (no `wedge_close`); cwd settle thread passes `_slow_start_note(fp)`; its docstring reworded.
- S1.4: `_warm_root` deleted (`grep _warm_root aitracker tests` is empty).
- S1.5: folder reservation `_slots_add(1)` + `_slots_release()` in its `finally`; overflow `_slots_add(1)` in the same `_LOCK` section + `held=True`.

**Tests**
- `tests/test_term_s3.py` -> `git mv` to new `tests/test_resume_pty_budget.py`, rewritten: 15 tests (cold resume claims one root shell; types claude after settle; cold `new` typed into root; 5x repeat adds none; 3 sessions twice = 3 ptys; same-tty rewrite of the dedicated test; F7 foreground job -> dedicated; cwd cold guard; /login stays dedicated guard; concurrent same-session cold; concurrent same-session busy-root; reservation released on error; cold burst cap; slots back to baseline; 429 only at real cap). Deleted: all warm tests and `TestWarmSettle` x3.
- `test_term_root_concurrency.py`: `test_k_simultaneous_resumes_cold` -> 1 root + K-1 dedicated, one typed line, bounded waits; R5 `test_same_session_twice_one_tty` rewritten (same tty, only spawn is `[SHELL,-l]`, one `--resume S0` typed); fake shells get `pid=SHELL`; `burst` joins deferred threads.
- `test_folder_terminal.py`: `TestFreshFolderShellQueuesInsteadOfOverflow` restored whole from `cfe81d8^`; young-shell test reverted to `..._defers_not_overflows`; `_settle` drops `False,`.
- `test_term_vt.py`: reverted the 2 `mode=new` fresh-folder tests and `TestGatewayLaunch` (`_await_typed`, `_open`, 2 inline spawns) to pre-S3; `:5690` untouched.
- `test_pending_pty_prompt.py`: dropped the `_warm_root` patch.
- `test_integration.py`: `test_resume_twice_real_spawn_yields_one_terminal` (R7: tmp HOME, SHELL=/bin/sh, ENV unset, real `/api/term/list` polled until stable 1 s within 10 s, ptys killed in `finally`).

**RED proofs** (scoped reverts, then restored)
| Revert | Went RED |
|---|---|
| S1.6 reservation (`if False and other is None`) | `test_concurrent_same_session_busy_root_one_overflow` |
| S1.5 overflow `_slots_add` removed | `test_term_root_concurrency...test_cold_burst_never_exceeds_cap` |
| S1.2 deferred branch disabled | `test_cold_resume_one_root_shell_claimed`, `test_cold_resume_types_claude_after_settle` |
| whole `term_vt.py` = `e6acfe7` | eval `test_resume_twice_real_spawn_yields_one_terminal` fails with 2 rows != 1 (all budget tests error: no `_RESUME_SPAWNING`) |
Not separately proven RED: the folder-reservation `_slots_add` pair (covered only by guard `test_slots_back_to_baseline`).

**Module results (one per process, all green):** resume_pty_budget 15, term_root_concurrency 7, folder_terminal 72, folder_swap 31, folder_redirect 11, open_pty_at_root 22, pending_pty_prompt 10, term_vt 380 (238 s, no flake), term_vt_exec 132, term_vt_upgrade 30, term_vt_client 281, term_recreate 32, resume_all_plan 7, resume_all_jobs 7, resume_fork_session 26, agent_cli_jobs 48, cr_registry_fields 62, cr_routes 35, tunnel_readonly 38, login_session_cleanup 30, term_home 13, term_launch 101 (B's, green with B's edits so far), integration 124.
Not run by A: B-owned UI modules (cr_readonly_ui, page_bundle, split_menu, ...). R8 (double slow-start note) is cosmetic, unchanged.

## Implementation B (UI)

**Changed (aitracker/web only).** `app.js`: `termSplit(primaryHtml, itemsHtml, caretCls, soloLabel)`, `termSplitSync`, `termSplitClose`, `termSplitOnClick`/`termSplitOnKey` (document capture listeners), exported on `window`. `app.css`: one `.tsplit*` block (nowrap, list absolute, `[hidden]` honoured, placed before the read-only block). `ext_cr_detail.js`: SKELETON uses `termSplit` (Resume primary + hidden `data-primary` Open terminal; list = Open terminal + External as `.tsplit-item`); header render toggles resume/primary-open by the Claude-id rule (R3) then `termSplitSync`; `session:reset` calls `termSplitClose()`. `ext_cr_detail.css`: list opens right-aligned, `.tsplit-item` styling, and the <=480px `.crd-btn-bare` hide now `:not(.tsplit-item)` (it would have hidden the dropdown on phones). `ext_cr_term.js`: overlay bar uses `termSplit` (external group + divider removed), `_placeOpenHere`/`_syncSplit` (called from `_syncStatusBar` and `_syncControlVisibility`; attached hides only the "here" buttons, solo "External" caret, R2), `close()` closes menus. `ext_cr_term.css`: z-index/row rules. `ext_launch.js`: `openHtml`/`resumeHtml` before the gate, `vtHtml = termSplit(...)`, open-state + focus carried across `render()` (R1), 403 latch calls `termSplitSync`. `ext_cr.css`: read-only hides `.crd-row1-actions .tsplit`.

**Tests.** New `tests/test_term_split_menu.py` (24: helper markup/sync/click/Escape, overlay R2/R3, header R3, classic R1, surface source checks, CSS bands, read-only, F4 `_openInline` guard). Changed (expected): `test_term_launch` (assembly now `termSplit(` + `vtHtml +`), `test_term_vt_client` (`const openHtml =`/`resumeHtml =` before gate; vtHtml now follows it), `test_cr_readonly_ui` (+`.crd-row1-actions .tsplit`), `test_page_bundle._HOME_NOTE_HARNESS` (`termSplit` stub, `querySelector`, `activeElement`), `test_cr_term_login_pill` harness (`_syncSplit` stub).

**RED proofs (hunk reverted -> failing test, then restored).** drop `e.stopPropagation()` -> `test_escape_closes_focuses_summary_and_stops_propagation`; drop `menu.open = true` carry -> `test_open_state_and_focus_carried` (R1); `el.split.hidden = st.attached` -> `test_attached_claude_hides_only_the_here_buttons_external_stays` (R2); `resume.hidden = false` -> `test_auggie_id_open_terminal_primary` (R3); remove readonly selector -> `test_readonly_hides_the_whole_split_in_the_header` + `test_cr_readonly_ui.test_new_selectors_hidden_only_under_readonly`; drop `:not(.tsplit-item)` -> `test_phone_band_bare_hide_excludes_split_items`; add `role="menu"` -> `test_markup_is_a_plain_disclosure_not_a_menu`.

**Results (one module per process, all OK).** test_term_split_menu, test_term_launch, test_cr_readonly_ui, test_cr_detail_action_row_responsive, test_page_bundle, test_cr_term_login_pill, test_term_vt_client, test_cr_manage_terminals_poll, test_page_css, plus ~60 other web-reading modules, test_cr_routes, test_update, test_term_vt_exec. Built bundle: `node --check` ok, full bundle runs to completion in a vm stub (no load-time throw), CSS `/*`==`*/` (481/481).

**Not done.** F4 guard "ext_vt.js mountInto with list [] -> exactly 1 POST" not written: `mountInto` depends on many IIFE-private helpers, not extractable; only the `_openInline` guard (mountInto once, no manage-terminals dialog) exists. No live browser check (no server started); list-clipping and phone/tablet layout verified by CSS review only. Deviation: header list is right-aligned (`right:0`), not `left:0`, because the row is right-aligned inside `.crd{overflow:hidden}`.

## Live UI check (sonnet)

Own server on :8811 (killed after). Widths emulated with same-origin iframes (window resize did not change viewport). Menu = `<details>` split; checks: Resume + caret adjacent, no standalone Open terminal/External, menu fully visible and on top, not clipped, open after 3 s poll, Escape and outside click close.

| Surface | 1400 | 1000 | 700 | 390 |
|---|---|---|---|---|
| CR session header | PASS | PASS | PASS | PASS |
| Classic detail pane | PASS | PASS | PASS | PASS |
| CR overlay bar (.cr-term-group tsplit) | SKIPPED (needs spawned terminal) | - | - | - |

Classic Escape/outside-click verified at desktop only; CR verified at all widths. No console errors on load.

## Impl review — server (opus)

Adversarial pass, 2026-11-17, on the uncommitted worktree vs `e6acfe7`. Method: AST-level diff of every restored function against `cfe81d8^`; a scratch copy (`$TMPDIR/irv/wt`) with a probe module (12 cases); `term_vt.py` swapped to `e6acfe7` on the scratch for the RED checks; one module per process. No repo file touched except this section.

**Verified sound (the report's claims hold):**
- **Verbatim restore.** `_deferred_folder_start`, `_folder_settled`, `_inject_argv`, `_start_backstop`, `_session_pty` are byte-identical to `cfe81d8^`. `_open_pty` vs pre-S3 `open_pty` differs only in: `login_sid` (8aeee07), the `_RESUME_SPAWNING` block, `+ _SLOTS_RESERVED` in both cap checks, the folder/overflow `_slots_add`, `_slow_start_note` on the cwd settle thread, and overflow via `_spawn_dedicated(held=True)` — which matches the pre-S3 inline overflow body field for field (`session/mode/forked/overflow/starting/grants/PTYS/backstop`). The deferred branch and the claim condition are verbatim.
- **Wrapper.** Releases on 400/409/429/500, on a `RuntimeError` from `spawn`, and on a `BrokenPipeError` from `_json` (probed). The wait is outside `_LOCK`; no lock cycle (the resume wait precedes every other reservation, and no `_FOLDER_SPAWNING` holder ever waits on `_RESUME_SPAWNING`). `server.EXTRA_POST` and `agent_cli`'s `call_route(tv.open_pty, …)` see the same signature/return. `cwd`/`new` never touch `_RESUME_SPAWNING`.
- **Slots.** Back to baseline after 409 (deleted worktree), spawn OSError (root and overflow), spawn RuntimeError, `_json` BrokenPipe, 429, /login.
- **Invariant matrix** (3 concurrent Resumes of S, 0.3 s fork): root missing → 1 spawn, 1 tty; root starting → 0 spawns, root tty; root idle (slow quiescence) → 0 spawns; busy with T → 1 overflow, 1 tty; busy with S → 0 spawns.
- **RED on `e6acfe7`.** The eval fails `['…','…'] != ['…']` (2 rows). With a `_RESUME_SPAWNING = {}` stub so setUp runs, 9/15 budget tests fail behaviourally, including `test_cold_resume_one_root_shell_claimed`, `test_cold_resume_types_claude_after_settle`, and both concurrent tests.
- **Deleted tests.** Every deleted test pins warm/wedge (moot). The pre-S3 class cfe81d8 deleted is fully restored. `TestSlowStartNoteOnSettleWatcher` keeps the same method names on a different function (not a duplicate).

| # | Sev | Finding |
|---|---|---|
| I1 | Low | The eval checks the row count only, so a resume that never starts still passes. |
| I2 | Low | The folder-reservation `_slots_add` has no RED test (the open item). Designed and proven here. |
| I3 | Low (doc) | README still describes S3. |
| I4 | nit | Stale S3 comments, plus a now-needless S3 precondition in the swap tests. |
| I5 | Low (by design) | `_RESUME_SPAWNING` dedupe is bounded by `FOLDER_SPAWN_WAIT`. |
| I6 | nit | Mislabelled guard. |

**I1 — eval asserts the count, not the start.**
- **Defect:** `tests/test_integration.py` `test_resume_twice_real_spawn_yields_one_terminal` asserts 1 row and 1 tty only.
- **Repro** (scratch): make `_deferred_folder_start` `return` at its top.
  - Actual: the eval stays green (the pending claim keeps it at 1 row) although nothing runs.
  - Expected: red.
- **Direction:** also assert the stand-in "claude" really started in the root shell. Must NOT relax the 1-row check.
- **Way:** after the poll loop, inside `try`:

  ```python
  fp = term_vt.PTYS[first["tty"]]
  end = time.time() + 20
  while time.time() < end and term_vt._fg_pgid(fp) == fp.pid:
      time.sleep(0.2)
  self.assertNotEqual(term_vt._fg_pgid(fp), fp.pid, "claude (the stand-in) was started in the root shell")
  self.assertEqual(fp.fg["session"], sid)
  ```

- **Test:** that assertion. Measured on scratch: green as is (fg = the python pgid, `fg.session == sid`); RED with the deferred start disabled (`28027 == 28027`).

**I2 — RED proof for the folder reservation `_slots_add` (`term_vt.py:3401`).**
- **Defect:** no test fails when it is removed. `test_cold_burst_never_overshoots_cap` uses one cwd, where the 2nd/3rd openers wait on `_FOLDER_SPAWNING` and never race the cap.
- **Repro:** two DIFFERENT cwds open cold at once with one slot left.
  - Actual with the line removed: `[200, 200]`, live 4 > cap 3.
  - Expected: `[200, 429]`, live ≤ 3.
- **Direction:** add the test. No code change.
- **Way:** in `tests/test_resume_pty_budget.py` `TestSlots`:

  ```python
  def test_two_cwds_cold_one_slot_left(self):   # RED without the folder _slots_add
      other = os.path.realpath(os.path.join(self.tmp, "other")); os.makedirs(other)
      config.MAX_TERMS = 3; self.fill(2); self.delay = 0.5
      # burst of {"session": "", "mode": "cwd", "cwd": self.root} and {"session": "", "mode": "cwd", "cwd": other}
      # through threads like TestConcurrent._burst (it takes bodies, not sids: generalise it, or inline 2 threads)
      self.assertLessEqual(self.live(), 3)
      self.assertEqual(sorted(codes), [200, 429])
      self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)
  ```

- **Test:** this one. Proven: green now; RED (`4 not <= 3`) with `:3401` replaced by `pass`. A sibling (cold-root Resume S + cwd open of another dir) is also RED without it.

**I3 — README describes S3.**
- **Defect:** `README.md:114` still says "On a cold open, when the root shell isn't ready, `claude` starts at once in a dedicated terminal while the root shell warms beside it (only when 3+ terminal slots are free …; a warm shell that never settles is closed)." That is false now.
- **Direction:** delete that sentence. The same paragraph already states the restored behaviour ("A freshly started folder shell runs its startup files first, and the command is typed once it reaches its prompt"). Keep the rest of the paragraph.
- **Way:** a single sentence removal.
- **Test:** none (doc). Optionally fold into an existing README source check: `assertNotIn("warms beside it", README)`.

**I4 — stale S3 text.**
- **Stale comments:**
  - `term_vt.py:1312-1313` (`_SLOTS_RESERVED`: "promised to cold openers … (open_pty's cold path)") and `:1937` (`_slots_add`: "(open_pty's cold path)"). Reword to "folder-shell, overflow and /login reservations".
  - `tests/test_term_vt.py:5692`: "cold open (S3): a dedicated claude first, then the warming root shell". Now: "cold resume: the root shell is spawned and claimed (sf1)".
- **Needless precondition:** `tests/test_folder_swap.py:403-405` `_settled_shell` docstring says a cold resume gets a dedicated claude. With the two `self._settled_shell()` calls (`:416`, `:437`) removed, `test_folder_swap` is 31/31 green on scratch.
- **Way:** drop the helper and both calls, which restores pre-S3 coverage of cold start → swap. Fallback: keep them and fix the docstring.
- **Test:** the two swap tests themselves.

**I5 — bounded dedupe** (`term_vt.py:3354-3362`).
- **Repro:** `FOLDER_SPAWN_WAIT=0.2`, busy root, overflow fork 0.6 s, 2 concurrent Resumes of S → 2 spawns. A waiter that wakes after the first opener failed (429/500) also proceeds without its own reservation, so a third concurrent opener can race it.
- **Direction:** no change. It is the same one-wait ponytail as `_FOLDER_SPAWNING`, and a fork/swap slower than 3 s is not a real case. Document it in the PR as a known bound.

**I6 — label.** `test_login_open_stays_dedicated` is marked `# guard`, but it is RED on `e6acfe7` (base warmed a root shell beside /login: `2 != 1`). Relabel the comment "RED on e6acfe7: /login no longer warms a root shell". No code change.

**Ordered fix list** (all small; no behaviour defect found in `term_vt.py`):
1. I2: add `test_two_cwds_cold_one_slot_left` to `TestSlots` (prove RED by replacing `term_vt.py:3401` with `pass`, then restore).
2. I1: add the started-in-root assertions to the eval (prove RED by early-returning `_deferred_folder_start`, then restore).
3. I3: delete the S3 sentence in `README.md:114`.
4. I4: reword `term_vt.py:1312-1313` and `:1937` and `tests/test_term_vt.py:5692`; drop `_settled_shell` and its 2 calls in `tests/test_folder_swap.py`.
5. I6: relabel `test_login_open_stays_dedicated`.
6. Note I5 in the PR body.

Then re-run `test_resume_pty_budget`, `test_integration`, `test_folder_swap`, `test_term_vt` (one per process).

**Verdict: ship after the fix list.** The server restoration, wrapper and slot accounting hold under every probe; the fixes are test/doc gaps.

## Impl review — UI (opus)

Adversarial pass, 2026-11-17, against the uncommitted worktree vs `e6acfe7`. Method: per-file `git diff`, grep/sed, node probes under `$TMPDIR/trr-ui-probe/`, mutants on a scratch copy (`$TMPDIR/trr-uireview-mut`), and the new test module run on a `git archive e6acfe7` copy. No repo source touched.

**Verified (claim holds):**
- Contract: no standalone Open terminal or External remains on the CR header (`ext_cr_detail.js:1383-1390`), the overlay bar (`ext_cr_term.js:163-170`, external group and its divider gone) or the classic pane (`ext_launch.js:466`). Claude: Resume is solid with the caret right beside it. Auggie: Open terminal is the primary on all three (header `:2555-2559`, overlay `_placeOpenHere`, classic `resumable ? resumeHtml : openHtml`).
- Handlers are unchanged. The header delegates via `closest("[data-act]")` (`:1806`), and `open-terminal`, `resume` and `external` emit the same events. The overlay binds `[data-action]` per button (`:293`), and moving `openHere` keeps its listener. The classic pane still binds by id. The click capture never calls `stopPropagation`. Escape with no menu open is untouched.
- R1: the classic open state and caret focus are carried across the rebuild. R2: when attached, only the "…here" buttons hide, and the caret shows "External ▾". R3: verified on the header and the overlay.
- Read-only: `.crd-row1-actions .tsplit` is hidden by class, never by host (`ext_cr.css:521`). The overlay and classic pane had no read-only hides before, and still have none.
- CSS:
  - comment delimiters are balanced per file (app 61/61, ext_cr 69/69, ext_cr_detail 104/104, ext_cr_term 30/30);
  - the ≤480 `.crd-btn-bare:not(.tsplit-item)` rule is right;
  - the tokens exist in light and dark (`--surface-raised` in ext_cr.css, with `--raised`/`--line3` as the classic fallback);
  - the list's z-index (60/80) sits under the dialogs (950) and the phonebar (960);
  - the header has no stacking context, so the right-aligned list stays inside `.crd{overflow:hidden}`.
- The assembled page (`page.build_page()`) passes a syntax check and runs to completion in a node vm with a Proxy DOM (`trr-ui-probe/run.js`): `termSplit`, `termSplitSync` and `termSplitClose` are functions and `ExtVT` exists. The base page also loads.
- `tests/test_term_split_menu.py` on `e6acfe7`: 20 of 24 go RED (19 F, 1 E). Green on base: the labelled guard, plus `test_closed_stays_closed_and_unfocused`, `test_no_band_hides_the_split_or_its_items` and `test_one_css_block_in_app_css`. Those three are unlabelled guards (nit: label them).

| # | Sev | Finding |
|---|---|---|
| U1 | **Med** | Escape is swallowed, and focus is stolen, when a menu was left open. |
| U2 | Low | R2's live path is untested, and `el.primaryGroup` is dead code that invites the regression. |
| U3 | Low | The F4 guard is missing, though it is buildable. |
| U4 | Low | Classic: focus on a list item is lost on every 2 s rebuild. |
| U5 | nit | The header's R3 regex is a 4th inline copy of the Claude-prefix rule. |

**U1 — Escape swallowed outside the menu.**
- **Defect.** `termSplitOnKey` (`app.js:138-147`) acts on *any* open menu, wherever focus is. A `<details>` stays open when keyboard focus Tabs away, and only a click closes it. Escape typed in the CR overlay's xterm (vim, Claude's own Esc-to-interrupt), the classic ExtVT or a dialog is then eaten (`stopPropagation` + `preventDefault`), and focus jumps to the caret.
- **Repro** (fake-DOM probe using the test harness). Open menu `a`, Escape event targeted at a textarea outside it.
  - Actual: `{stopped:true, prevented:true, caretFocused:true}`.
  - Expected: the event is untouched and focus stays in the textarea.
- **Direction.** Intercept Escape only when it originates inside the open menu. Must NOT change the in-menu behaviour (close, focus the summary, stop the overlay's own Escape).
- **Way.** In `termSplitOnKey`:
  ```js
  const m = e.target && e.target.closest ? e.target.closest(".tsplit-menu[open]") : null;
  if (!m) { termSplitClose(); return; }
  ```
  (closes stale menus silently, without stop, preventDefault or focus), then keep the existing body. No change on other surfaces.
- **Test.** `TestTermSplitHelper.test_escape_outside_the_menu_is_not_swallowed`. Menu open, `ev(textarea, {key:'Escape'})`. Assert `stopped`, `prevented` and `summary.focused` are all false, and `menu.open` is false. The existing test's `ev(null, …)` must become `ev(a.summary, …)`. RED on the current code.

**U2 — R2's live path is unguarded.**
- **Defect.** The R2 tests drive `_syncSplit` directly. The split now lives *inside* `[data-group="primary"]`, and `el.primaryGroup` survives unused (`ext_cr_term.js:259`; the stub is still at `test_cr_term_login_pill.py:41`).
- **Repro.** A mutant that re-adds `if (el.primaryGroup) el.primaryGroup.hidden = st.attached;` after `_syncSplit()` in `_syncStatusBar`.
  - Actual: `test_term_split_menu` (24), `test_cr_term_login_pill` (6) and `test_term_vt_client` (281) all stay green.
  - Expected: RED, because External is unreachable while attached.
- **Direction.** Remove the dead handle and pin the live caller. Must NOT change `_syncSplit`.
- **Way.**
  - Delete `primaryGroup:` from `el` (`:259`) and from the login-pill harness stub.
  - In `TestSurfacesUseTheSharedSplit`, assert `"primaryGroup" not in ext_cr_term.js`.
  - Also assert `"_syncSplit();" in _extract(src, "_syncStatusBar")`.
- **Test.** Those two assertions. RED with the mutant above.

**U3 — F4 guard ("mountInto with an empty list → exactly 1 POST /api/term/pty").**
- **Defect.** It was not written; it was judged non-extractable. It is buildable by loading the whole file, as `test_pending_ext_launch.py` already does for `ext_launch.js`.
- **Proof.** `trr-ui-probe/f4.js` loads all of `ext_vt.js` with `vm.runInContext`. It uses a Proxy DOM, `requestAnimationFrame` as a microtask, `getComputedStyle` returning zero paddings, and a fetch router: list → `{terminals:[]}`, pty → `{tty:'t1'}`, renderer → `grid`. It wraps `ExtVT.manage` with a counter, calls `ExtVT.mountInto(U(), {session:'S1', mode:'resume'}, {})` and drains 50 `setImmediate` ticks.
  - Result: `posts:1, manage:0`.
  - Mutant `spawn(); spawn();` gives `posts:2`.
- **Way.** Add `TestResumeOpensOneEngineGuard.test_mountinto_empty_list_one_pty_post` (*guard*, green on base), which embeds that harness. Assert exactly one `POST /api/term/pty`, `manage == 0`, and that the first call is `GET /api/term/list`.

**U4 — classic list-item focus.**
- **Defect.** `ext_launch.js:468-476` carries focus only when it is on the caret. If a keyboard user Tabs into "External terminal", focus drops to `<body>` within 2 s, while the menu stays open. The base also lost focus on every rebuild, so this is mostly the same as base, but the items are now one level deeper.
- **Direction.** Carry focus by id as well. Must NOT change the ids.
- **Way.** Before the rebuild: `const fid = ae && el.contains && el.contains(ae) ? ae.id : "";`. After the rebuild: `if (fid) { const f = document.getElementById(fid); if (f) f.focus(); }`. Keep the caret path for the summary, which has no id.
- **Test.** Extend `TestClassicPaneKeepsMenuOpenAcrossPoll._render` with `activeElement = {id:'extopenbtn', …}` and `getElementById('extopenbtn')` returning a focus spy. Assert it was focused. RED now.
- **Alternative.** No change, documented as same as base.

**U5 — the R3 rule is copied a 4th time** (`ext_cr_detail.js:2555`). Other copies: `ext_launch.js:49`, `ext_cr_term.js:46`, `ext_cr_boot.js:801`. The server already ships `resumable` on every list row (`registry.py:32`), and the board reads `s.resumable`. Also, an empty id counts as resumable here, but not in `isClaudeId`. **No change** — the spec (R3) mandated "same rule". Document it as a known duplication. A follow-up could prefer `session.resumable` when defined.

Not examined live (no server started): real-browser rendering of `<details>` as an inline-flex item in Safari and Chrome, and the phone layout. Out of scope and unchanged: the board tile shows *either* Resume *or* "Open terminal to answer" (`ext_cr_board.js:3024-3033`). It never shows both, so it is not a contract violation.

**Ordered fix list:**
1. U1: scope `termSplitOnKey` to Escape inside the open menu, plus its test, and update the existing Escape test's target.
2. U2: delete `el.primaryGroup` and its harness stub, and add the two `_syncStatusBar` assertions.
3. U3: add the whole-file `ext_vt.js` vm guard (recipe in `$TMPDIR/trr-ui-probe/f4.js`).
4. U4 (optional): carry list-item focus by id across `render()`.
5. Label the three base-green tests as *guard*.
6. Re-run `test_term_split_menu`, `test_cr_term_login_pill`, `test_term_vt_client` and `test_page_bundle`, one per process.

**Verdict: fix, then ship.** U1 is a real keyboard regression in the terminal. The rest is test hardening.

## Impl review reconciliation (main thread, 2026-11-17)

| # | Verdict | Action |
|---|---|---|
| I1 eval only counts rows | confirmed | assert the stand-in claude actually ran (add only if not already present) |
| I2 folder-slot reserve unproven | confirmed | add `test_two_cwds_cold_one_slot_left`, prove RED |
| I3 README:114 stale | confirmed | describe pre-S3 typed-into-root behaviour |
| I4 stale S3 comments / unneeded settle helper | confirmed | clean comments; leave test_folder_swap helper (harmless, out of scope) |
| I5 dedupe lasts only the 3 s wait | doc only | note in commit message |
| I6 guard label wrong | confirmed | relabel |
| U1 Escape swallowed outside the menu (xterm Esc-interrupt) | **confirmed, Med** | act only when the Escape target is inside an open `.tsplit` menu; otherwise close stale menus silently and let the key through; Node test RED before |
| U2 dead `el.primaryGroup`; R2 unpinned | confirmed | delete it; pin `_syncStatusBar` attached state |
| U3 F4 guard buildable | confirmed | port `$TMPDIR/trr-ui-probe/f4.js` into a test: empty list → exactly 1 POST |
| U4 classic item focus lost on rebuild | confirmed, small | carry focus by data-act/id |
| U5 4th inline copy of the Claude-id regex | overstated → conditional | use the server's `resumable` if the header's session object already carries it (conventions rule 5); else keep |

## Fixes applied — UI

- **U1** `app.js termSplitOnKey`: Escape acts only when `e.target.closest(".tsplit-menu[open]")`; otherwise stale menus close silently with no stop/preventDefault/focus move. Existing Escape tests now target `a.summary`; new `test_escape_outside_the_menu_is_not_swallowed`. RED proof (scoped revert to the old any-open-menu body): 1 FAIL; restored.
- **U2** deleted `el.primaryGroup` (`ext_cr_term.js`) and its stub in `test_cr_term_login_pill.py`. New `TestStatusBarAttachedKeepsExternalReachable` (source assertions + Node run of `_syncStatusBar` attached). RED with the `primaryGroup.hidden = st.attached` mutant: 2 FAIL.
- **U3** `TestMountIntoEmptyListOnePost`: whole `ext_vt.js` in a node vm (ported f4.js), empty list -> exactly 1 POST /api/term/pty, manage 0. Guard (green on base). `spawn(); spawn();` mutant -> FAIL (posts 2); a second test asserts the mutant is detected.
- **U4** `ext_launch.js render`: focus on a menu item carried by id across the rebuild; new test `test_focus_on_a_menu_item_is_carried_by_id`. RED with the branch disabled: 1 FAIL.
- **U5** left as is: the header's `session` object does not carry the server `resumable` flag (only list rows do). The 4th inline regex copy stays, a known duplication.

Modules (one per process): test_term_split_menu 30 OK, test_page_bundle 12 OK, test_term_launch 101 OK, test_term_vt_client 281 OK, test_cr_readonly_ui 10 OK, test_cr_detail_action_row_responsive 6 OK, test_cr_term_login_pill 6 OK. Assembled page: syntax OK and loads in a node vm without a throw; CSS comment markers balanced (app 61/61, ext_cr 69/69, ext_cr_detail 104/104, ext_cr_term 30/30).

## Fixes applied — server

- I1: eval had no start assertion; added (fg pgid leaves the shell, `fp.fg["session"] == sid`) in tests/test_integration.py. RED proof: `_deferred_folder_start` early-return -> "46354 == 46354 : claude (the stand-in) was started in the root shell"; restored.
- I2: added `TestSlots.test_two_cwds_cold_one_slot_left`. RED proof: folder-reserve `_slots_add(1)` -> `pass` gives "4 not less than or equal to 3"; restored.
- I3: README folder-terminals paragraph now says a cold Resume/+ New spawns one repo-root shell and types claude in once it settles (no warm shell).
- I4: comments reworded (term_vt.py `_SLOTS_RESERVED`, `_slots_add`; tests/test_term_vt.py cold-resume comment). test_folder_swap untouched.
- I6: `test_login_open_stays_dedicated` relabelled "RED on e6acfe7".
- Modules: test_resume_pty_budget 16 OK; test_term_root_concurrency 7 OK; test_integration 124 OK; test_term_vt see handback.
- test_term_vt: 380 tests; first run 1 failure (not identified, output was tail-truncated), rerun 380 OK (known load-sensitive flake).
