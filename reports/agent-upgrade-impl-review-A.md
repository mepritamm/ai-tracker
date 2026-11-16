# Agent upgrade: implementation review A (backend)

Reviewer A (opus, adversarial). Scope: `aitracker/agent_cli.py`, the agent routes in `server.py`, the `update.py`
edits, `providers/base.py`/`claude.py`/`auggie.py`, `registry.resume_cmd`, the conventions rule-6 exception,
`scripts/bundle.py` and the bundle checks, plus their tests. Calls into `term_vt.py` were traced only as far as
agent_cli depends on them. All changes are uncommitted on branch `agent-upgrade`. I started from the assumption that
every implementer claim was false.

What I ran:
- These single modules, all green: `tests.test_agent_cli_jobs` (32), `_outside` (8), `_parse` (7),
  `test_agent_routes` (14), `test_claude_running` (9), `test_update` (18),
  `test_integration.TestBundle`, and `test_selfcheck.AgentUpgradeSelfcheck`.
- Two probes in the job scratch dir, which change no product code or tests:
  - `~/.claude/jobs/0f4ee7b4/tmp/reviewA_probe_k.py`: swaps in a per-item verify deadline. Test (k) still passes.
  - `~/.claude/jobs/0f4ee7b4/tmp/reviewA_probe_confirm.py`: runs a job with exactly the confirm the UI sends
    (`ext_cr_dialogs.js:1347`).

**Verdict: no BLOCKER. 6 SHOULD-FIX, 14 NIT (each with a stated direction).** The core safety properties hold in the
code:
- the update runs first, and a failed update stops nothing;
- a session is stopped only with a (tty, session) confirm;
- the pane's identity is checked by pid;
- a stop that is not confirmed is never resumed;
- the daemon stop is confirmed on the worker's own recorded pids;
- the two locks exclude each other in both directions;
- no request string reaches an argv.

The defects are wrong user-facing outcome text, two narrow paths where a stopped session is not resumed, and tests
that pass without pinning the property they name.

---

## SHOULD-FIX

### A1. Every `cannot_stop` row the user saw is reported as "Failed: … not shown in the warning"
1. **Defect.**
   - The UI confirms only `plan.stop` rows (`ext_cr_dialogs.js:1347`: `(plan.stop || []).map(...)`).
   - `_agent_restart_all` (`agent_cli.py:433-435`) checks `(tty, session) not in pairs` **first**, so every
     `cannot_stop` candidate becomes `outcome "not_shown"` with `AGENT_NOT_SHOWN`. That includes a duplicate pane,
     a failed preflight, an agent-view pane, and a daemon pane when the flag is off.
   - `_agent_summary` (`:583-585`) then prints it as `Failed: …`.
   - The branch for a cannot_stop row with its real reason (`:440-441`) is reachable only when a client confirms a
     cannot_stop pair, which the UI never does.
   - **Repro** (`reviewA_probe_confirm.py`): candidates t1 = S1 stoppable, t2 = S1 duplicate (`AGENT_REASON_DUP`),
     t3 = S3 "its folder no longer exists"; confirm built exactly as the UI builds it. The actual summary:
     `… Resumed without a prompt (were idle): TS1. Failed: TS1 — not shown in the warning, not stopped; run `claude --resume S1`. Failed: TS3 — not shown in the warning, not stopped; …`
     - The one restarted session is reported as both resumed and failed.
     - Both rows **were** shown in the warning.
   - **Expected:** t2 is not listed as failed (its twin was restarted). t3 is listed with "its folder no longer
     exists" and its command.
2. **Fix direction.**
   - A candidate that is not stoppable at job time is reported by its own `reason`, whether or not it is in
     `confirm`.
   - A `AGENT_REASON_DUP` row whose first row was handled produces no "Failed" clause.
   - Do **not** change the rule that a stoppable pair missing from `confirm` is never stopped (F9).
3. **Way.** In `_agent_restart_all`, reorder the checks:
   ```python
   for c in stop + cannot:
       ver = c.get("version") or ""
       if c in cannot:                                     # not stoppable now: never stopped, report why
           if (c.get("reason") or "").startswith(AGENT_REASON_DUP.split("%")[0]):
               continue                                    # the twin row carries the outcome
           _agent_push(job, _agent_item(c, "failed", c.get("reason") or ""))
       elif (c["tty"], c["session"]) not in pairs: ...not_shown...
       elif ver and ver == new: ...current...
       elif not ver and old == new: ...current skipped...
       else: todo.append(c)
   ```
   - It is simpler to have `upgrade_candidates` set `"dup_of": f["tty"]` on duplicate rows (`term_vt.py:4170`) and
     test that key rather than the text.
   - A daemon row with the flag off (`AGENT_REASON_DAEMON`) keeps its two commands. That is already the case,
     through `_agent_item`'s `command`.
4. **Tests.**
   - Correct `test_f_not_stoppable_never_stopped` and `test_n_restart_flag_off_is_cannot_stop` to confirm only the
     stoppable rows, i.e. build `confirm` from `ac.agent_plan_upgrade("claude")["stop"]` as the UI does. Today both
     pass only because `go(confirm="all")` includes the cannot_stop pairs.
   - Add `test_dup_row_not_reported_failed`. Probe shape: t1/t2 on the same target; assert there is no
     `"Failed: TS1"` in the summary and exactly one item for S1. It goes red on the current code.

### A2. A daemon session shown in an overflow (dedicated) pane can be stopped and then not resumed
1. **Defect.**
   - `_agent_restart_daemon_pane` (`agent_cli.py:488-511`) first runs `claude stop <short>` and confirms the
     worker pids are gone. Only then does it call `tv.stop_for_upgrade(...)`.
   - V6d measured that the `claude attach` client exits **by itself** about 0.6 s after the workers die (§13).
   - A finished overflow pty is dropped by `_reap()` at once (`term_vt.py:2218`: `t.done and (t.overflow or …)`).
     If the client has exited before the `_reap()` inside `stop_for_upgrade`, then `PTYS.get(tty)` is None and it
     returns `error: "its terminal closed"` (`term_vt.py:3513-3515`).
   - agent_cli records `failed` and **does not resume** (`:508-509`). The worker is already stopped, so the
     session is running nowhere.
   - **Repro (logic):** a daemon session opened while its folder shell was busy runs in an overflow pane
     (`term_vt.py:3312-3325`). Press Upgrade; the client exits before the pane stop. Actual: item `failed`,
     "its terminal closed", nothing resumed. Expected: resumed in a new pane.
   - It is a race, and the normal order (our poll is 0.2 s) usually wins. But this is D5's main path on this
     machine.
2. **Fix direction.**
   - In the daemon path only: once the worker pids are confirmed dead, a pane that is already gone counts as a
     confirmed client exit, and the resume goes ahead.
   - The TUI path keeps refusing on "its terminal closed": nothing was signalled there, and the user may have
     closed it.
3. **Way.**
   - `stop_for_upgrade` returns `out["closed"] = True` next to that error (`term_vt.py:3514`).
   - In `_agent_restart_daemon_pane`, replace
     `if r.get("error"): return …failed` with
     `if r.get("closed"): r = {"confirmed": True, "error": ""}` and then the existing checks.
   - `_agent_sweep(kids, getattr(tv.PTYS.get(...), "pid", 0))` already handles a missing pane.
   - The resume goes through `open_pty`, which opens a folder shell or a new pane (`needs_slot` was checked before
     the stop).
4. **Test.** `DaemonPaneTests.test_overflow_client_already_gone_is_resumed`: `self.tv.stop_res = {"t1": {"error":
   "its terminal closed", "closed": True, "confirmed": False}}` with `cand(..., folder=False)`. Assert one open with
   `session == "DMN"`. It goes red today (the item is `failed`).

### A3. A session on a NEWER version than the installed one is restarted on every Upgrade, and its warning text is false
1. **Defect.**
   - `_agent_restart_all` restarts any `ver != new` (`agent_cli.py:436-443`).
   - `_agent_version_text` maps `v > i` to `AGENT_VER_CURRENT`, "already on the installed v{i} — restarted only if
     a newer version installs" (`:125-127`).
   - **Repro:** the server's PATH resolves `claude` to 2.1.325, while the pane shell's PATH resolves 2.1.326 (the
     case `AGENT_VERSION_MISMATCH` exists for). Press Upgrade with nothing to install.
     - The warning says "already on the installed v2.1.325 — restarted only if a newer version installs".
     - The job then stops it anyway (2.1.326 != 2.1.325), interrupting a busy turn.
     - It resumes on 2.1.326 again (the shell PATH), and verify reports a mismatch.
     - Every later press repeats this.
   - D8's words were "sessions run an **older** version — restart the old sessions". The plan's "differs" goes
     further than D8.
2. **Fix direction.** Restart only when the session's version tuple is **lower** than `new`. When it is higher,
   skip it as `current`, with a detail saying it runs a newer build than the tracker's `claude`. Unknown-version
   handling is unchanged. The warning text says the same thing.
3. **Way.**
   - In `_agent_restart_all` use `vt, nt = _agent_vtuple(ver), _agent_vtuple(new)`, and add
     `elif vt and nt and vt > nt: push current, detail=AGENT_VER_NEWER.format(v=ver, i=new)` before the restart
     branch.
   - In `_agent_version_text` add a `v > i` branch returning `AGENT_VER_NEWER`, e.g.
     `"runs v{v}, newer than the tracker's v{i} — left running (another claude may be first on your shell's PATH)"`.
   - Add the constant in §6 next to `AGENT_VER_CURRENT`.
   - This is a reading of D8: **say it to the user as a decision** ("restart only older" vs "any different").
4. **Tests.**
   - Jobs (p'): a candidate on "2.1.326" with new "2.1.325" → zero stops, `outcome current`, `AGENT_VER_NEWER` in
     the detail.
   - Parse: `_agent_version_text("2.1.326", "2.1.325") == AGENT_VER_NEWER…`.
   - Both go red today.

### A4. Test (k) does not pin the shared verify deadline
1. **Defect.**
   - `JobBase.setUp` patches `ac.AGENT_VERIFY_WAIT` to **0** (`test_agent_cli_jobs.py:107`).
   - `test_k` builds its deadline as `clk.time() + ac.AGENT_VERIFY_WAIT` (`:355`), so the loop exits on its first
     pass, and `assertLessEqual(elapsed, 0 + 2)` is trivially true.
   - **Repro** (`reviewA_probe_k.py`): replace `_agent_verify` with a version that gives each item its own full
     `AGENT_VERIFY_WAIT`, run sequentially. `test_k` still passes (`PER-ITEM VARIANT PASSES test_k: True`).
   - The implementer's claim that it "hangs rather than fails" applies only to deleting the deadline. It fails to
     detect the regression F11 is about.
2. **Fix direction.** Test only; product code unchanged.
3. **Way.**
   - In `test_k`, wrap the first part in `with mock.patch.object(ac, "AGENT_VERIFY_WAIT", 90):`.
   - Give `Clock.sleep` a guard (`if self.now - 1000 > 1000: raise AssertionError("verify did not stop")`) so a
     removed deadline fails rather than hangs.
   - Assert `90 <= clk.now - 1000 <= 92`, with 3 unsettled items (a per-item variant gives 270).
4. **Test.** The corrected `test_k` goes red under `reviewA_probe_k.py`'s variant and under a deleted deadline.

### A5. A prompt that never reached the transcript is reported as "Resumed with 'continue, re-read CLAUDE.md'"
1. **Defect.**
   - `_agent_verify` sets `prompt_seen = False` when the prompt line never lands (`agent_cli.py:564-565`), for
     example after the `--fork-session` backstop rebuilds argv without the prompt (plan §5.3, "known limit").
   - No user-facing string reads `prompt_seen`. `_agent_summary` (`:575-577`) still lists the item under
     "Resumed with “continue, re-read CLAUDE.md”", and `detail` stays empty.
   - Clause 6 says "notify the user about that as well". The notification states as fact something verify proved
     false.
   - **Repro:** in `JobBase`, patch `ac.user_line_has` to `lambda *a, **k: False` and run a busy candidate.
     Actual: the summary has "Resumed with …: TS1." and no caveat. Expected: a caveat for TS1.
2. **Fix direction.** When `prompt_seen` is False, append a server-written detail. The "Resumed with" classification
   is unchanged (the prompt was sent).
3. **Way.**
   - Add the constant `AGENT_PROMPT_NOT_SEEN = "the prompt was sent but is not in its transcript yet — check its
     terminal"` (§6).
   - In the final loop of `_agent_verify`, set
     `_agent_set(it, prompt_seen=False, detail=(it["detail"] + " " + AGENT_PROMPT_NOT_SEEN).strip())`.
   - `_agent_summary`'s "Not confirmed … yet" part (`:586-589`) then names it, because it picks up any detail.
4. **Test.** `test_c2_prompt_not_seen_is_reported`: patch `user_line_has` False; assert `AGENT_PROMPT_NOT_SEEN` is in
   the item's detail and in the summary. It goes red today.

### A6. `needs_slot` treats a BUSY folder shell on the session's cwd as a free landing spot (term_vt side; it decides agent_cli's outcome)
1. **Defect.**
   - `upgrade_candidates` sets `needs_slot = not any(q.folder and q.cwd == cwd_to for q in panes)`
     (`term_vt.py:4135`).
   - `open_pty` resume takes `_folder_pty(cwd)` whether or not it is busy (`:3158`). A busy shell then falls to the
     overflow spawn, which enforces `MAX_TERMS` (`:3312-3317`, a 429).
   - **Repro:**
     - `MAX_TERMS` panes are open.
     - Pane A (folder, cwd `/w/wt`) runs session S, whose recorded cwd is `/w`.
     - Pane B (folder, cwd `/w`) runs `npm run dev`.
     - Upgrade: `needs_slot` is False, so agent_cli skips its slot check (`agent_cli.py:448`) and stops S. The
       resume then gets 429.
     - Actual: S is stopped and not resumed (`failed`, "too many running terminals"). That is exactly the S7 failure
       mode. Expected: `AGENT_NO_SLOT`, and S is not stopped.
2. **Fix direction.** A folder pane counts as a landing spot only when it is the candidate's own pane or is at its
   prompt with no claim.
3. **Way.** At `term_vt.py:4135`:
   `needs_slot = not any(q.folder and q.cwd == cwd_to and (q is p or (q.fg is None and _fg_pgid(q) == q.pid)) for q in panes)`.
   `_fg_pgid` is a syscall, not a fork. This belongs to reviewer B's file; it is listed here because agent_cli's
   restart outcome depends on it.
4. **Test.** In `test_term_vt_upgrade.py`, a candidate pane plus a second folder pane on `cwd_to` whose `_fg_pgid` is
   patched to differ from its pid → `needs_slot True`. It goes red today.

---

## NIT (each with its direction)

| # | Defect (file:line, repro) | Direction / way | Test |
|---|---|---|---|
| N1 | The bundle name checks skip tuple-assigned names. `test_integration.py:1756-1759` (`names` count) and the new generic loop (`:1765-1769`) read only `ast.Name` targets. Eight agent_cli names are tuple-assigned: `AGENT_VERSION_TIMEOUT, AGENT_DOCTOR_TIMEOUT, AGENT_STOP_TIMEOUT, AGENT_STEP_OLD/UPDATE/NEW, AGENT_DOCTOR_DONE/FAILED` (checked with `ast`). Repro: a module defining `AGENT_STEP_NEW = …` would pass. | Both loops take `[t.id for tg in n.targets for t in ast.walk(tg) if isinstance(t, ast.Name)]`. | The existing test, after the change; it goes red if a collision is planted. |
| N2 | S8: the comment "_run() above is not collected by unittest" (`tests/test_selfcheck.py` new class docstring) is **false**: `tests/test_tracker.py:23` imports `_run` and `TestSelfcheckSmoke` runs it. | Delete `AgentUpgradeSelfcheck` and move the one assert into `_run()` just before `print("selfcheck ok")`, as plan §11 says. The assert is pure, so the shim's global repointing does not matter. | `test_tracker.TestSelfcheckSmoke` runs it; break `_agent_was_busy` and it goes red. |
| N3 | S3: `AGENT_REASON_DUP` exists twice (`term_vt.py:3462`, `agent_cli.py:51`). The agent_cli copy is **unused**, and no test pins the two equal (`test_term_vt_upgrade.py:180` checks only term_vt's). | Keep term_vt's (live). Either delete agent_cli's, or keep it as the §6 list entry and pin it. | `self.assertEqual(term_vt.AGENT_REASON_DUP, agent_cli.AGENT_REASON_DUP)` in `test_term_vt_upgrade.py`. |
| N4 | S1: the `path is None` guard in `session_state` (`claude.py:718-720`) cannot be shown red, because the outer `except` already gives "". | No change. Keep it: it documents the `_tail_scan(None)` TypeError hazard and saves a raise per call. Drop "or the None guard is removed" from plan §11's red column. | none |
| N5 | Dedupe also merges unrelated **empty-target** rows. `term_vt.py:4164-4170` keys on `target`, so a second agent-view pane (`target ""`) has its "cannot tell which session" reason overwritten with "the same session as terminal t1; restarted there". That text is false, and it shows in the warning. | `if not r["target"]: continue` at the top of the dedupe loop (term_vt, reviewer B). | Two panes with no sid → the second keeps the "cannot tell" reason. |
| N6 | The slot check counts a dedicated pane that its own stop will free. `agent_cli.py:448`: at the cap, a dedicated-pane TUI candidate gets `AGENT_NO_SLOT` although stopping it frees a slot. | `tv._live_count() - (0 if c.get("folder") else 1) >= config.MAX_TERMS`. The daemon path is the same. | (s'): a non-folder candidate at exactly the cap → stopped and resumed. |
| N7 | `_agent_strip` keeps the **head** of the output (`agent_cli.py:160`). An updater's error is usually at the end. | Keep the tail: `s[-AGENT_OUTPUT_CAP:]`. | Extend `test_strip_ansi_and_cap`: a marker at the end survives. |
| N8 | `AGENT_VERSION_MISMATCH % (e.get("version"), new)` renders "resumed on v, expected …" when the pid file has no version (`agent_cli.py:550-551`). | Use `e.get("version") or "an unknown version"`. Alternatively treat "" as unknown and not as a mismatch. | Verify with `run_version=""` → no "on v,". |
| N9 | Rule-6 wording against the code (`conventions.md:19`). (a) "on a version other than the installed one": an **unknown**-version session is also restarted when the update changed the version (`agent_cli.py:438-443`). (b) "loopback Host name": `_local_caller` checks Host only when `TRACKER_AUTH` is unset (`server.py:239`). | (a) Add "(or of unknown version, when the update changed the installed version)". (b) "loopback Host name when no login is configured". If A3 is accepted, also say "older". | none (docs) |
| N10 | The route test for the `_APPLY.locked()` preview skip (`server.py:699-700`) is missing. With `_APPLY` held, an upgrade with no confirm must give agent_start's 409 "updating itself", not a preview. | Add a test. | `test_apply_held_gives_updating_not_needs_confirm`. |
| N11 | S6: the read-only POST half (`test_agent_routes.py:89-90`) passes because of the pre-existing global deny-all (`server.py:639`), not the new route. The GET half does pin "not in `_RO_GET_ALLOW`": it checks `readonly: True`, which the route's own 403 lacks. | No change. That is acceptable for a deny-all gate; say it in the PR. | none |
| N12 | §13's S0 decision ("`open_pty` must not leak `CLAUDE_*` job vars … add a test/README note") is not discharged. `_fork_child` pops only `CLAUDE_CODE_CHILD_SESSION` (`term_vt.py:1671`; the diff touches no env lines, so S5's revert is confirmed clean), and there is no README note. With the server started inside a Claude background job, every upgrade resume writes no pid file or transcript, so verify says "not yet seen running" for all of them. | No product change (the wide scrub was reverted for a reason). Add the README known gap (reviewer B's file): "start the tracker from a normal terminal, not from inside a Claude background job". | none |
| N13 | S4 deviations I judged acceptable. (a) Auggie says "is already on X" when old == new (`agent_cli.py:570`); this is more honest than the plan. (b) A daemon outside row with no valid job id gets only `claude --resume <id>` (`:309`); that command reattaches to the old worker, but the job id is always hex in practice. | (a) No change. (b) No change; it is a known gap, document it in the PR. | none |
| N14 | `GET /api/agents` is local-caller only, so the section is invisible over the tunnel or a phone. | **Intended exception; no change.** The no-host-gating rule is about recorded session data. This route exposes machine control (binary paths, CLI versions, the start of a stop/resume). It is the same class as `/api/update`, `/api/scheduler` and `/api/pending` (`server.py:469, 484`), all local-only. The UI must hide the section on 403 rather than show an error (reviewer B). | none |

Minor, no change: a 60 s refresh thread that started before the update can cache the pre-update version after
the job wrote the new one (`agent_cli.py:206-217` vs `:403`). It is cosmetic and self-heals at the next TTL. The
preview calls `running()` twice (candidates, then outside). That costs some speed but is correct.

---

## Implementer claims, checked

| Claim | Finding |
|---|---|
| S1 None guard cannot be shown red | True. Keep it (N4). |
| S3 DUP duplicated; pinned? | Not pinned, and the agent_cli copy is unused (N3). |
| S4 cannot_stop row → `not_shown` | True, and it is wrong for the user (A1). |
| S4 `prompt_seen: False` has no string | True; SHOULD-FIX (A5). |
| S4 deadline test "hangs rather than fails" | Worse: the test is vacuous for a per-item deadline (A4). |
| S5 `_fork_child` back to popping only `CLAUDE_CODE_CHILD_SESSION` | Confirmed: no env lines in the term_vt diff (`term_vt.py:1668-1671` unchanged). |
| S5 `_agent_restart_daemon_pane` order | Confirmed `claude stop <short>` (logged before the pane stop, test n), then pid wait (`:491-506`), thin stop, sweep, resume. Gap: A2. |
| S6 read-only test exercises no new code | True for POST, false for GET (N11). |
| S8 `_run()` not collected | False (N2). |
| `_run(cwd=)`, `_AGENT_JOB_LOCK`, 409 | Confirmed `update.py:28, 63-69, 269-271`. Mutual exclusion: each side takes its own lock and then checks the other (`agent_cli.py:341-345`, `update.py:267-271`), so both cannot proceed. Tested both ways (`test_i`, `test_update`). |
| Bundle | ORDER puts `agent_cli.py` after `update.py` (`bundle.py`). `TestBundle` is green, including the bundled `--version` run, which executes agent_cli's module code. Gap: tuple names (N1). |

## Contract check

| Clause | Verdict | Evidence |
|---|---|---|
| 1 Doctor/Upgrade + "following sessions … will be stopped …" | Discharged (backend) | `agent_cli.py:26-31, 109-114, 378-425`; route `server.py:693-707` |
| 2 Agents the tracker manages | Discharged | descriptors `claude.py:2307`, `auggie.py:940`; `agent_specs` `:176` |
| 3 Busy → force with warning | Discharged | `AGENT_STATE_BUSY/WAITING` `:42-43`; busy rows are stopped like the rest (`:444-455`) |
| 4 Outside = show only | Discharged | `_agent_outside` `:290-321`; only `upgrade_candidates` rows are ever signalled |
| 5 Always latest | Discharged | `["update"]`, no version config |
| 6 Resume + prompt + notify | **Partly**: notification defects A1, A5 | `_agent_resume` `:516-528`, `_agent_summary` `:568-596` |
| 7 Manual only | Discharged | Jobs start only from POST; the version refresh is GET-driven (`:220-243`) |
| 8 Auto-update note | Discharged (server side) | `AGENT_AUTO_UPDATE_NOTE` `:23`, in status and plan |
| D2 unknown-id exception | Discharged | `term_vt.py:4137-4139` |
| D5 daemon panes stop + resume | Discharged, with gap A2 | `:473-513`, `AGENT_RESTART_DAEMON = True` `:20` |
| D6 prompt only for busy | Discharged | `:117-118, 518-519`; test (c) |
| D7 reuse, no copies | Discharged | imports `:10-13`; `_local_caller` reused in `server.py` |
| D8 restart old sessions even when nothing installs | Discharged, but it over-restarts newer builds (A3) | `:433-443`; test (p) |
| D9 scratch S0 | Not examined (live) | §13 results only |
| D10 Auggie upgrade | Feature discharged; V9 live run outstanding (§13 "—") | `auggie.py:940`; test (m) |
| D11 waiting = busy | Discharged | `claude.py:717`, `_agent_was_busy` |
| D12 failed update stops nothing | Discharged | `:395-400`; test (a) |
| D13 D5 side-effect warning | Discharged | `AGENT_STATE_DAEMON_MOVE` `:47, 274` |
| D14 S9 live proof | **Not discharged** (S9 not run) | §13 V9 "—" |
| §13 S0 decision (`CLAUDE_*` env note) | **Not discharged** | N12 |
| Rule-6 exception wording | Matches the code, except N9 (a) and (b) | `conventions.md:19` |

## Not examined

- `term_vt.py` beyond the shapes agent_cli uses: `open_pty` internals, the backstop retry, `_swap_in`, and the
  real-pty tests in `test_term_vt_upgrade.py`. I read only the cap and `_folder_pty` path for A6.
- `ext_cr_dialogs.js` and `test_agents_ui.py` (only line 1347 was read, for A1), README and CLAUDE.md. These belong
  to reviewer B.
- Live behaviour: no Claude or Auggie process was started, stopped or signalled.
- The full gate (`make check`), which another agent is running.
- The auth-cookie path with `TRACKER_AUTH` set, end to end.
- The classic UI.
