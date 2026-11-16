# Resume all prior terminals: adversarial implementation review

Reviewed 2026-11-16 in worktree `.claude/worktrees/agent-upgrade` (branch `resume-all`, base `9754d93`, all changes
uncommitted). I assumed the implementer's report was false and checked each claim against the code, along the live path:
button → `crCall` → `do_POST /api/terminals/resume-all` → `agent_plan_resume_all` / `agent_start_resume_all` →
`term_vt.resume_all_plan` → `_agent_launch` → `_agent_job_resume_all` → `_agent_resume` → `call_route(open_pty)` →
job items → `agentWatchJob` toast and `onDone`.

**Verdict: no BLOCKER, 4 SHOULD-FIX, 9 NIT.** The feature works as specified. Two problems remain:
- It costs a lot to run. The recorder reparses every live pane's full transcript at least once a minute, and the
  preview parses up to 32 transcripts inside the request.
- Its proof has gaps. Two lines on the live path have no test, and the job summary claims more than it observed.

**Tests run** (`unset TRACKER_AUTH; python3 -m unittest -q tests.<m>`). All green:
- the new modules `test_resume_all_record`, `test_resume_all_jobs`, `test_resume_all_routes`, `test_resume_all_ui`;
- the existing modules `test_update_restart`, `test_fork_follow`, `test_agent_cli_jobs`, `test_agents_ui`,
  `test_cr_manage_terminals_parity`, `test_cr_manage_terminals_poll`, `test_update_routes`, `test_agent_routes`,
  `test_term_vt_upgrade`.

**Probes**, as scripts in `/tmp/ra-probe/`, read-only, no Claude started:
1. **Mutation of T0a.** I made `_lock_fh` a no-op. Lost updates then appeared in 30 of 30 trials, so T0a is a real
   test.
2. **`resume_all_plan()` on a temp record** holding 3 real session ids. It returned 2 open and 1 cannot ("open in the
   Claude desktop app", which is correct). Both open rows were pre-ticked, with free=12. It took 1.78 s.
3. **Parse cost.** `term_gate.session_cwd` on the 6 largest transcripts (12 to 61 MB) took 22.4 s cold, and 0.24 s
   once each transcript was cached at its current size and mtime. `providers.claude._session_meta` on the same 6 files
   took 0.03 s.

---

## SHOULD-FIX

### S1. The recorder tick fully reparses every live Claude pane's transcript, at least once a minute
- **Defect.** `term_vt.py:4389`: `remember_terminals` builds the record from `upgrade_candidates()`. For every Claude
  pane, that function runs:
  - `term_gate.session_cwd(target, resume=True)` (`term_vt.py:4281`), which runs `parse_any` and then `parse_session`
    over the whole file;
  - `term_gate.resume_argv` (`:4293`);
  - `_thin_client_short(pg)`, which forks `ps` (`:4274`).

  `parse_session` is cached by `util.file_pass`, keyed on `(mtime, size, ino, ctime)`. The transcript of a live session
  grows with every turn, so the cache misses every time and the file is reparsed in full. `REMEMBER_FULL_EVERY = 60`
  forces a recompute every minute, and any pane change triggers one sooner.

  Before this change, `upgrade_candidates()` ran only when someone pressed Upgrade. Now it runs in the background
  whenever any pane is open, which is the normal state.
- **Repro.** Open 3 Claude panes on sessions whose transcripts are 20 to 60 MB (this machine has several, for example
  the VIDA stack sessions). Let them work.
  - Expected: a recorder tick costs milliseconds.
  - Actual: each tick costs about 1.3 to 10 s of pure-Python parse per active pane (probe 3), holding the GIL against
    the dashboard's 2-second polls.
  - The same work runs inside `restart_in_place` before `execv`, which delays a self-update restart. The client gives
    up after 60 s (`ext_cr_dialogs.js` `waitForRestart`).
- **Fix direction.** The record needs only `target`, `cwd`, `title`, `cols` and `rows`. Keep reusing the pane walk, the
  foreground filter, the pid-file relabel and `_background_target` (S3 of the plan review), but skip the
  upgrade-only work.
  - **Must NOT change:** the rows AU gets from `upgrade_candidates()`, and its `needs_slot`, `stoppable` and
    `command`.
- **Way.**
  - `term_vt.upgrade_candidates(light=False)`. When `light` is True, skip `thin`, `cwd_to`, `needs_slot`, the
    `stoppable`/`argv` block and `command`. Emit `thin=False`, `needs_slot=False`, `stoppable=False`, `reason=""` and
    `command=[]`, so the row shape stays the same.
  - The `groups` and `dup_group` tail can stay.
  - `remember_terminals` calls `upgrade_candidates(light=True)`.
  - Nothing in `agent_cli` changes.
- **Test (red before the fix).** In `tests/test_resume_all_record.py`:
  - Reuse the fake-pane harness from `tests/test_term_vt_upgrade.py` (`:142` region), with one Claude pane.
  - Patch `term_vt.term_gate.session_cwd` and `term_vt._thin_client_short` with `mock.Mock(side_effect=AssertionError)`.
  - Set `_REMEMBER_ON = True` and call `remember_terminals(final=True)`.
  - Assert that both mocks were never called and that the entry was written. Today `session_cwd` is called, so the
    test is red.
  - Re-run `test_term_vt_upgrade` and `test_agent_cli_*` unchanged.

### S2. The preview parses up to 32 full transcripts synchronously in the POST handler
- **Defect.** `term_vt.py:4498`: `resume_all_plan` calls `term_gate.session_cwd(sid, resume=True)` for every
  remembered entry, which runs a full `parse_any`.
  - It runs three times per use: in the preview (in the request thread), in the confirm re-check and in the job.
  - The sessions in the record are mostly closed ones that no view has parsed in this process, so the first press is
    cold.
- **Repro.** Use a record holding 6 of the largest local transcripts and press the button.
  - Expected: the list appears in under a second.
  - Actual: about 22 s (probe 3), during which the button is only disabled and nothing tells the user it is working.
  - With 32 entries it can pass a minute. `crCall` has no timeout, so the widget can look dead.
- **Fix direction.** Resolve the plan's cwd cheaply. `open_pty` stays authoritative: it still calls the full
  `session_cwd` when it opens, and its 429 covers any slot estimate that turns out off.
  - **Must NOT change:** `term_gate.session_cwd`'s default behaviour, which `open_pty` and `upgrade_candidates` use.
- **Way.**
  - Add `term_gate.session_cwd(sid, resume=False, fast=False)`. With `fast=True`:
    - find the path with `providers.claude.find_session(sid)`;
    - read the cwd from the last `cwd` in the 96 KB tail (add `"cwd"` to `_tail_scan`'s harvested keys), falling back
      to `_session_meta(path)["cwd"]`;
    - then apply the same ancestor walk.
  - Parse "last cwd wins" (`claude.py:1929-1932`); `_session_meta` keeps the first one, hence the tail first.
  - Use `fast=True` only at `term_vt.py:4498`.
- **Test (red before the fix).** In `tests/test_resume_all_plan.py`, once the other agent has finished with that file:
  - Use a record of 3 ids. Patch `providers.claude.parse_session` with `Mock(side_effect=AssertionError)`, with
    `find_session` and `_tail_scan` stubbed.
  - Assert that `resume_all_plan()` returns 3 open rows with the expected cwd. Today the parse is called, so the test
    is red.

### S3. Two lines on the live path have no test (vacuous coverage)
- **Defect.** Deleting either of these leaves the whole suite green while the feature silently stops working:
  1. **`server.py:1063-1065`**, `tv.start_remember()` in `run()`. `tests/__init__.py` replaces it with a stub, and no
     test asserts that `run()` calls it. If the line goes, nothing is ever recorded, and every press answers
     `AGENT_RA_NONE` forever.
  2. **`ext_cr_term.js:761`**, `onRefresh: _repaintManage`. `test_resume_all_ui.py:98` passes `onRefresh` itself, and
     `raParts()` gates on it. If the line goes, the button never shows in Manage terminals.
- **Repro.** Delete either line and run the four `test_resume_all_*` modules plus `test_update_routes`. Everything is
  green.
- **Fix direction.** Add tests only. **Must NOT change** the stub in `tests/__init__.py`; it stays the guard (B2).
- **Way.**
  - **(a)** In `tests/test_update_routes.py` `RunWiring`, inside its existing patched-`run()` block, add
    `mock.patch.object(term_vt, "start_remember")` and assert `called_once`.
  - **(b)** In `tests/test_resume_all_ui.py`:
    - use `_extract_function` on `ext_cr_term.js` for `_openManageDialog` and `_openCapDialog`;
    - assert that `"onRefresh: _repaintManage"` is in the first and `"onRefresh"` is not in the second, which also
      pins S6: no button in the cap dialog.
- **Test.** These are the tests. Each one goes red when its line is deleted.

### S4. "Resumed N" is claimed from the 200 alone: a fork or a start that never happened still counts as resumed
- **Defect.** `agent_cli.py:514` `_agent_ra_summary` counts every `unprompted` item as "Resumed", and that outcome
  comes from a 200 `open_pty` reply. Two cases end differently after the 200:
  - **The CLI refuses the resume.** `forked` is always False in that reply (`term_vt.py:3125-3127`, and `:3214`).
    `_resume_backstop` sees the refusal seconds later and retries with `--fork-session` (`pt.forked = True`,
    `:2596`/`:2632`). Nobody reads that back.
  - **The resume never starts.** A typed resume that never starts, like the rc-lock case fixed in `bc0f44e`, also stays
    "Resumed".

  The brief asked whether a fork is reported honestly. It is not, and the user ends up with a copy under a new id.
- **Repro.** Use a session that the CLI refuses as a background agent.
  - Expected: the summary says it opened as a copy.
  - Actual: "Resumed 1 of 1 prior terminal in the background: X."
- **Fix direction.** After all opens, read back each opened pane within a bound. **Must NOT change** `_agent_resume`,
  `_agent_verify` or AU's summary.
- **Way.**
  - In `_agent_job_resume_all`, after the loop, poll up to `tv.BACKSTOP_WINDOW` (one shared deadline, 0.5 s steps) for
    each item with `tty_after`. Under `tv._LOCK`, read `p = tv.PTYS.get(tty)`.
  - Done when `p is None`, `p.done` or `not p.starting`. Then set `item["forked"] = bool(p and p.forked)`. If `p` is
    None or `p.done`, set `outcome="failed"` and `detail=AGENT_RA_EXITED` (new server string: "its terminal closed
    right after starting").
  - In `_agent_ra_summary`, name forked items as `"%s (as a copy, --fork-session)"`.
  - **Cheapest acceptable alternative:** keep the code and change the verb to "Started resuming" in the summary and in
    `AGENT_RA_MESSAGE`.
- **Test (red before the fix).** In `tests/test_resume_all_jobs.py`, give `FakeTV` a `PTYS` dict, a `_LOCK` and
  `BACKSTOP_WINDOW = 0.1`. Make the A reply's pane `forked=True, starting=False`. Assert that the summary contains
  "as a copy" and that `item["forked"]` is True.

---

## NIT

- **N1.** `store.py:354`: the `_update_json` docstring still says "Read-modify-write forks.json". Make it generic.
  - Must not change: the lock code.
  - Test: none (docstring).
- **N2.** `tests/__init__.py:36`: the `ait-lastterms-` mkdtemp is never removed, so one temp dir leaks per test process
  (`make check` runs one process per module).
  - Fix: `_atexit.register(_shutil.rmtree, _os.path.dirname(_config.LAST_TERMS_FILE), True)`, in the same shape as
    `_ZDOTDIR` (`:31`).
  - Test: none.
- **N3.** `resume_all_plan`'s outer `except Exception` (`term_vt.py:4513`) turns any internal error into an empty plan.
  The UI then shows `AGENT_RA_NONE` ("Nothing to resume …"), which is false.
  - Fix:
    - wrap the per-entry body in its own try, so an error becomes a `cannot` row with reason
      `"could not check this session: %s" % e` (new `RA_ERROR`);
    - make the outer except print one `ai-tracker: resume all:` line.
  - Test: patch `term_gate.resume_argv` with `side_effect=ValueError("x")` for one of 2 ids, and assert 1 open row and
    1 cannot row.
- **N4.** Every `cannot` row has `command: []` (`term_vt.py:4477` onward), yet plan §1 C5 and the README promise "a
  hand command".
  - Fix: either drop that promise from the README and the plan, or set `command` for `RA_TUI`/`RA_DAEMON` (for
    example `"claude --resume <sid>"` to run by hand once the other copy stops).
  - Test: assert the chosen shape in T9.
- **N5.** On a stale-confirm 409, the widget's ticks are replaced by the server's default pre-ticks
  (`ext_cr_dialogs.js` `go()`, `rp = r.body`), so the user's choice is lost.
  - Fix: before `rp = r.body`, keep `prev = ids` and re-apply `checked` to the rows whose `session` is in `prev`. This
    is the user's choice, not server policy.
  - Test: in the UI harness, assert that a stale reply after ticking `s2` keeps `s2` ticked.
- **N6.** Two messages name the wrong job. No change in this PR, as with AU; mention both in the commit.
  - `update.py:271` refuses an Update during a resume-all job with "an agent upgrade is running" (the known gap from
    plan §5).
  - `AGENT_RA_FAIL_SCAN` says "pending-work scan" when what holds the per-user `PENDING_LOCK` is another tracker's AU
    job.
- **N7.** `agent_cli.py:272`: the line is over 120 characters, and `hasattr(tv, "term_gate")` is redundant beside the
  rest of the module. Split the line; no behaviour change.
- **N8.** Manage terminals shows no progress and no result inside the dialog: `rp = null` hides the panel, and only the
  30 s toast carries the summary. The job step shows only in Config.
  - Accept, or set `err = j.summary` in the `onDone` callback so the panel keeps the result.
  - Test: the UI harness asserts the summary text in the panel after done.
- **N9.** Conventions rule 6 names only `flags.json` and `titles.json` as app-writable state. `last_terms.json`
  follows the precedent of pins, notes and forks, which are not named there either.
  - No exception text is needed: the feature makes no network call and writes no session log.
  - Optionally add it to that list. CLAUDE.md is already being updated by the other agent.

## Probes that came back clean (claims verified against the code)

- **Two trackers at once.** The record is a locked read-modify-write through `store._update_json`, with a flock on
  `last_terms.json.lock` and an atomic `_save_json`. Probe 1 confirmed that T0a fails without the lock. Entries are only
  added or refreshed, so neither tracker drops the other's.
- **Crash or clean stop.** There is no shutdown write, so a crash or a stop cannot write a gutted set. `_merge_terms`
  returns False when nothing is live (`:4366`) and no file is written (T2, T4). A session that ran for less than one
  15 s tick is lost, as designed (§7.1).
- **Self-update restart.** `update.py:365-371` writes `remember_terminals(final=True)` before `_cloexec_all`, and a
  failure there cannot block the exec (T7b). In the suite it is gated by `_REMEMBER_ON`.
- **Empty run.** A run with no pane open returns at the empty fingerprint, and nothing is written (T4).
- **The 32 bound.** It is enforced at merge (T2) and again at read. An entry whose transcript is gone is dropped at
  read (T7). Such an entry still holds a bound slot in the file until newer ones push it out, which is acceptable.
- **No leaked thread and no real file in tests.** `start_remember` is stubbed and `LAST_TERMS_FILE` is redirected.
  `importlib.reload(config)` in `test_term_vt` resets the path, but the write gate `_REMEMBER_ON` stays False. T5
  starts the real thread and joins it.
- **Server-side re-check.**
  - It re-plans on confirm. A forged or now-unopenable id never counts (T11).
  - `_ra_need` mirrors `open_pty`: an idle folder shell is claimed at no cost, and every further session in a cwd
    takes an overflow slot (`term_vt.py:3261`, `:3330`, `:3415`).
  - A changed `MAX_TERMS` is read at call time. Two presses or an agent job give 409 (gate, plus the non-blocking
    lock acquire in `_agent_launch`). A self-update in progress gives 409 through `_APPLY.locked()`, and an Update
    during the job gives 409 through `_AGENT_JOB_LOCK`.
- **Already open.** In this tracker, `_session_pty` puts the session in "already". In another tracker, its pid file
  makes it a `RA_TUI` "can't" row. An Auggie id gives `RA_ONLY_CLAUDE`. Desktop and daemon sessions give "can't"
  rows (probe 2 saw the desktop case live).
- **Opened in the background, with no prompt.** The job calls `call_route(open_pty, {session, mode: "resume", cols,
  rows})` from its thread. No client call opens a terminal modal, and there is no `prompt` key (T12 asserts both).
  Afterwards Manage repaints through `onRefresh`, which reopens only while Manage is the top dialog.
- **Refactors leave AU unchanged.** `_agent_launch` is moved verbatim (`agent_id` is now `agent`). `_agent_fail`'s
  default label is the old text. `_agent_resume`'s `reused=` defaults to `AGENT_RESUME_REUSED`. `agentWatchJob`
  without `onDone` behaves as before. AU's suites are green.
- **Rule 5 (server-written text).** The JS holds only the labels "Resume all prior terminals", "Resume N ticked",
  "Cancel" and "request failed". `test_no_server_sentence_in_js` enforces it.

## Contract check

| # | Clause | Verdict | Evidence |
|---|---|---|---|
| C1 | "add a resume all prior terminals button" | discharged | `resumeAllWidget` (`ext_cr_dialogs.js` ~1336); T15 |
| C2 | "alongside the upgrade version button" | discharged | `agentsBlock` row loop, after Upgrade (`if (a.can_resume_all) …`); `test_config_host` |
| C3 | "Put this button in the manage terminals view itself" | discharged, but untested at the wiring line | `renderManageTerminals` `raParts()`, in the empty state and the footer. Depends on `ext_cr_term.js:761` `onRefresh` (S3b) |
| C4 | "where it opens the last spawned sessions" | discharged, at a cost | The record is written by the `term-remember` tick and the restart write; `remembered_terminals`. Cost: S1. The start in `run()` is untested (S3a) |
| C5 | "list the sessions which will be opened" | discharged | 409 picker body; open, cannot and already rows. Slow on a cold first press (S2). Hand command promised but absent (N4) |
| C6 | "and open all of them in the background" | discharged, but the summary over-claims | A server job runs `open_pty` `mode: "resume"`; no modal. "Resumed" is claimed from the 200 alone (S4) |
| R-D1 | "Also closed this run" | discharged | One history of up to 32 entries, never pruned when a pane closes (`_merge_terms`); T2 and T3 |
| R-D2 | "Manage terminals and Config" | discharged | Both hosts; not in `_openCapDialog` (no `onRefresh`) |
| R-D3 | "Let me pick" (server re-checks the cap) | discharged | Checkboxes pre-ticked by `_ra_need`; `agent_start_resume_all` re-plans and refuses with 409 and a fresh list; T11 |
| R-D4 | "No prompt" | discharged | `_agent_resume(…, False, …)`: no `prompt` key; T12 |
| Main-thread reversal | One merged history keyed by session id | discharged | One flat dict, `seen = max`, `_update_json`; no port key |

## Not examined

- `tests/test_resume_all_plan.py`, `tests/test_selfcheck.py`, README.md and CLAUDE.md. Another agent is editing them.
  As a result, I did not check `resume_all_plan`'s own test coverage (T8, T9).
- `make bundle` / `test_page_bundle`. By design the bundle has no terminals, and `_agent_tv()` returns None there.
- A real pty run. No shell or Claude was spawned, so `_pane_fingerprint` and `idle` are verified by reading the code
  only.
- Whether a pane whose fg label is stale (an in-pane `/resume` to another id) makes that other id show as `RA_TUI`
  ("another terminal") rather than "already". It is safe either way, since the session is never opened twice, but the
  text may be wrong.
- Whether the SPA opens a modal by itself when a pane for the session on screen appears. I found no such code path in
  `ext_cr_term.js` or `ext_vt.js`, but I did not search the classic UI.

## Fix verification

Verified 2026-11-16 on the uncommitted `resume-all` tree. I assumed the fixer's report was false and traced each fix
along the live path. Modules run (`unset TRACKER_AUTH; python3 -m unittest -q tests.<m>`), all OK:
`test_resume_all_record` (10), `test_resume_all_plan` (7), `test_resume_all_ui` (11), `test_resume_all_jobs` (7),
`test_resume_all_routes` (3), `test_update_routes`, `test_term_vt_upgrade` (30), `test_agent_cli_jobs` (48),
`test_cr_registry_fields` (62), `test_gateway` (29). I edited no product code and no tests. The one probe script was
read-only and has been deleted.

| # | Verdict | Evidence |
|---|---|---|
| S1 | FIXED | `term_vt.py:4245` `upgrade_candidates(light=False)`. Light mode skips `_thin_client_short` (`:4276`), `session_cwd` and `needs_slot` (`:4283-4285`), the `stoppable`/`resume_argv` block (`:4287`) and `command` (`:4306`). It keeps the `running_sessions` pid file over the pane label (`:4270-4273`) and `_background_target` (`:4274`). The row keys are unchanged. The only light caller is `remember_terminals` (`:4395`), and the self-update restart reaches it through that function. Agent Upgrade's callers (`agent_cli.py:312`, `:567`) call it without arguments and get full rows. Tests: `test_resume_all_record.py` `LightRows` raises on all three heavy calls and asserts the stale label X gives session Y and the same row shape. `test_s1_recorder_asks_for_the_light_rows` (`:152-156`) asserts the recorder passes `light=True`. Both go red if their line reverts. |
| S2 | FIXED (acceptable residual, see F1) | `term_gate.py:75-115`. `fast=True` runs `find_session`, takes the last cwd from `_tail_scan`, falls back to `_session_meta`'s first cwd, then runs the same ancestor walk. Its only caller is `term_vt.py:4506`. `open_pty` (`term_vt.py:3198`), `term_launch.py:194`, `term_run.py:470` and `upgrade_candidates` (`:4283`) keep the full parse. `_tail_scan` harvests from the same lines that `parse_session`'s meta loop reads (`claude.py:170-171` vs `:1932`), with the same last-wins rule. Live probe on 255 recent real transcripts: fast cwd differed from the full-parse last cwd in 0 of them, and 1 had a tail with no cwd line. |
| S3 | FIXED | (a) `test_update_routes.py:144-148` patches `term_vt.start_remember` and asserts it was called once. `server.py:1063-1065` resolves `tv.start_remember` through the module attribute at call time, so deleting the line turns the test red. (b) `test_resume_all_ui.py:35-44` checks the text of `_openManageDialog` (`ext_cr_term.js:727-772`; the next `\n  function ` is at `:773`) for `onRefresh: _repaintManage`, which exists only at `:762`, so deleting it turns the test red. `_openCapDialog` (`:677-726`) is asserted to have no `onRefresh`. |
| S4 | FIXED (the cheapest acceptable alternative, as the reconcile chose) | `agent_cli.py:518-521` now says "Started resuming N of M …" or "No prior terminal started resuming." An item with `forked` gets "(opened as a copy, --fork-session)". `forked` comes from the open reply (`:758`, unchanged from before). All the text is server-written, and JS has no "Resumed" string. There is no polling loop: the diff adds no sleep, `PTYS` read or `BACKSTOP_WINDOW` use, and the sleeps at `:727` and `:794` were already there. `test_resume_all_jobs.py:180-190` asserts the verb, no "Resumed", and the copy suffix. |
| N1 | FIXED | The `store.py:354` docstring now reads "(forks.json, last_terms.json, ...)". The lock code is untouched. |
| N2 | FIXED | `tests/__init__.py:37` adds `_atexit.register(_shutil.rmtree, dirname(LAST_TERMS_FILE), True)`, in the same shape as `_ZDOTDIR` (`:30`). |
| N3 | FIXED | `term_vt.py:4480-4516`: each entry runs in its own try, and an error becomes a `cannot` row with `RA_ERROR` (`:4443`) and the same keys as a normal row. The outer except prints `ai-tracker: resume all: plan failed:` (`:4526`). `test_n3_…` (`test_resume_all_plan.py:100-108`) gives 2 open rows and 1 error row. |
| N5 | FIXED | `ext_cr_dialogs.js:1396` saves `seen` before `rp = null`. At `:1406` the user's ticks are re-applied to the rows that were on screen, and new rows keep the server's pre-tick. The test (`test_resume_all_ui.py:147-154`, `:219`) ticks s2, which the server leaves unticked, and expects `[True, True]`. Without the fix it gets `[True, False]`, because the change handler (`paintConfirm`) never writes to the fixture. |
| N7 | PARTLY | `agent_cli.py:272-273`: the line is split and behaviour is unchanged, but the redundant `hasattr(tv, "term_gate")` is still there. It does no harm, so no change is needed. |
| `_tail_scan` returns `cwd` | No regression | The new key is added (`claude.py:151`, `:239`), and the `OSError` path still returns the full dict. Every consumer indexes a named key and none compares the key set: `_tail_fields` (`:246`), `_session_meta` (`:288`), `session_state` (`:724`), `term_gate._launcher_for` (`:327`), and the tests in `test_selfcheck`, `test_cr_registry_fields`, `test_claude_running` and `test_gateway`. All of these pass. |

### S2 judgement: can the preview's cwd differ from where `open_pty` lands?
Only when the transcript's last 96 KB holds no line with a `cwd`. That happens when the final line alone is larger than
96 KB, because the partial first line is dropped. The fallback is then `_session_meta`'s **first** cwd, while
`open_pty` uses the **last** one. A mid-session `EnterWorktree` makes those two differ. What the user sees:
- the row shows the old folder;
- `_ra_need` may count the session as free (typed into an idle shell in the old folder) when `open_pty` actually needs
  a new slot.

At the cap, that last item gets `open_pty`'s 429 and is reported under "Not opened" with the server's reason. No
session opens twice, nothing is lost, and the summary stays honest. The probe found 0 of 255 real transcripts affected,
so this is acceptable and not a SHOULD-FIX.

### New findings
- **F1 (NIT). The fast-cwd test never runs the head fallback, and its comment says the opposite.**
  - **Defect.** `tests/test_resume_all_plan.py:142-145`. The comment says "tail has none", but the rewritten file is
    one short line that holds a cwd, so `_tail_scan` returns it. The `_session_meta` branch in `term_gate.py:97` never
    runs.
  - **Repro.** Change `term_gate.py:97` to `cwd = _cl._tail_scan(path).get("cwd")` (no fallback). The test stays
    green.
  - **Fix direction.** Change the test only; leave product code as it is. Optionally, to close the S2 residual
    completely, replace the head fallback with the full `parse_any` when the tail has no cwd. That case is rare (0 of
    255), so the cost is paid almost never, and the preview then always agrees with `open_pty`.
  - **Way.** In the second half of `test_s2_fast_cwd_reads_tail_then_head_and_never_parses`:
    - write the head cwd line, then one line longer than 96 KB with no `cwd` (for example
      `json.dumps({"x": "a" * 100000})`);
    - assert the walked-up head cwd, or `boom.assert_called` if the full-parse fallback is chosen instead.
  - **Test.** That case. It is red against the mutation above.
- **F2 (NIT, comment only).** The comment at `term_vt.py:4395` still says "forks ps". In light mode the `ps` for
  `thin` is gone; only `_foreground_is_claude`'s cached `ps` and `running_sessions` remain. Reword it to "may fork ps
  (fg probe)", or leave it. No test needed.
