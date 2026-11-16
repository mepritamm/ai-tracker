# Agent upgrade: verification of the implementation-review fixes (adversarial, opus, 2026-11-16)

Scope: the "Implementation review" verdict table in `agent-upgrade-reconcile.md` (B-SF1..6, A1..A6, NITs, D15, D16), the
D15 interface in `~/.claude/jobs/0f4ee7b4/tmp/fix-brief.md`, and the designed fixes in `agent-upgrade-impl-review-A.md` /
`-B.md`. I assumed every fixer report was false and traced each fix from the route to its effect.

What I ran (no product code or tests edited; no Claude/Auggie process touched):
- Single modules: `test_agent_cli_jobs` (45), `test_agent_cli_parse` (7), `test_agent_cli_outside` (9),
  `test_agent_routes` (15), `test_term_vt_upgrade` (27), `test_agents_ui` (11). All OK, except one unidentified failure in
  `test_agent_cli_jobs` on the first of 5 runs (the other 4 runs passed). Another agent was running `make check` at the
  same time, so treat it as a load flake until it recurs.
- Not run: `test_integration.TestBundle`, because it rewrites `dist/tracker.py` while `make check` is running. I checked the
  name-check change by reading it.
- Two probes in `~/.claude/jobs/0f4ee7b4/tmp/verify/`:
  - `probe_reused.py`: the real `term_vt.open_pty` via `call_route`, then the real `agent_cli._agent_resume`. This
    produced NF1.
  - `probe_daemon_group.py`: the jobs fixture, with the roster modelled the way `_live_workers` really behaves (an entry
    only while its pid is alive). This produced NF2.

## Verdict per finding

| # | Verdict | Evidence |
|---|---|---|
| B-SF1 (= A-N5): empty target deduped | **FIXED** | `term_vt.py:4166-4169` groups only a non-empty `target`. `test_unknown_panes_are_not_deduped` goes red without the `if r["target"]` guard: the old grouping would give both rows `dup_group ["a","b"]`. |
| B-SF2: a reattach reported as "Resumed" | **REGRESSED** | `agent_cli.py:601` treats `reused: True` as "nothing was resumed". But `open_pty` sets `reused = fp is not None` (`term_vt.py:3159`) and returns it on the **normal typed resume** into an existing folder shell (`:3295-3297`), on the deferred start (`:3278-3280`) and on `_swap_in` (`:3647`). So the main path is now reported failed. See NF1; the probe reproduces it. The tests miss it because `FakeTV.call_route` (`test_agent_cli_jobs.py:63`) never returns `reused` for a normal landing. |
| A1 = B-SF3: cannot_stop rows reported "not shown" | **PARTLY** | The reason is right now: `agent_cli.py:453-454` checks `bad` before `pairs`. `test_a1_…` uses the UI-shaped confirm and goes red on the old order. But the reconcile's fix says to report them as "**Not restarted:** <reason>". `_agent_summary` (`:663-665`) still prints "**Failed:** TS3 — its folder no longer exists", although nothing was attempted. **Way:** give these rows the outcome `"not_restarted"` (at `:454`). Add a summary clause `"Not restarted: %s — %s%s."` (name, reason, command) next to the `Failed:` loop, and include `"not_restarted"` in nothing else. **Test:** `test_a1_…` asserts `"Not restarted: TS3 — its folder no longer exists"` in the summary and `"Failed: TS3"` not in it. It is red today. |
| A5 = B-SF4: unseen prompt announced as sent | **FIXED** (with NIT NF6a) | `agent_cli.py:644-645` appends `AGENT_PROMPT_NOT_SEEN` to the detail. The summary picks it up (`:666-669`), the toast is the summary (`ext_cr_dialogs.js:1323`), and the job view renders the detail (`:1367`). `test_a5_…` goes red without `:645`, because the detail is otherwise `""` when `on_version` is True. |
| B-SF5 (= A-N2): selfcheck TestCase | **FIXED** | The assert is now inside `_run()` before `print("selfcheck ok")` (`tests/test_selfcheck.py:1481-1494`). The class and its false comment are gone. |
| B-SF6: tests that stay green when the feature breaks | **FIXED** (within the reconcile's scope: the dispatch assertion plus one field-fit test) | (a) `test_agents_ui.py:30` uses the dispatch regex. (c) `:72-123` exists and is real for `a/st/plan/c/o/i`. Its `job` half compares the UI's reads against a **hand-built** dict (`:107-109`), so renaming `"summary"` in `agent_start` (`agent_cli.py:362-364`) keeps it green. NIT: build `job` from `ac.agent_start` + `_agent_snapshot()` instead. (d) Row-key contract: `test_term_vt_upgrade.py:203`. (e) and (f) from review B were not done; the reconcile did not require them. |
| A2: daemon overflow pane closes after `claude stop` | **FIXED** | `stop_for_upgrade` sets `closed` (`term_vt.py:3513`). The live path reaches it: `_agent_stop_daemon` calls `tv.stop_for_upgrade` on the real module, and `:583-584` maps `closed` to confirmed. The sweep then gets shell pid 0, which is safe (`term_vt.py:3484`). A new terminal is the correct place to resume: the worker pids were already confirmed dead (`:566-581`), and the slot was checked before the stop, while the pane was still alive. The TUI path still refuses on "its terminal closed" (`:541-542`). `test_a2_…` goes red without `:583`. |
| A3 / D16: newer session restarted on every press | **FIXED** | Job: `agent_cli.py:459-460` (newer → current, `AGENT_VER_NEWER`). Warning: `_agent_version_text:137-138`. Text and action agree for all four cases (see the D16 row). Tests: `test_a3_…` and parse. |
| A4: test (k) vacuous | **FIXED** | `test_agent_cli_jobs.py:353-371` patches 90 s, adds a runaway guard in `Clock.sleep` and asserts 90–92 s with 3 unsettled items. A per-item deadline gives 270 s, which is red; a deleted deadline trips the guard. |
| A6: busy folder shell counted as a landing spot | **FIXED** | `term_vt.py:4134` requires `q is p` or (`fg is None` and the shell owns the foreground). `test_busy_folder_shell_is_not_a_landing_spot_a6` goes red on the old expression (`b.cwd == cwd_to` would give `needs_slot` False). |
| **D15**: stop all copies, resume once | **PARTLY** | Correct in the fakes: grouping (`term_vt.py:4166-4177`), `dup_text` (`agent_cli.py:290-292`), the UI sends every `stop[]` row including non-primary copies (`ext_cr_dialogs.js:1353`), a partial confirm stops none (`:479-481`), and a blocked copy stops none (`:476-478`). The live path is wrong in five places: NF1 (the folder landing is reported failed), NF2 (a daemon group is stopped and never resumed), NF3 (it keeps stopping after the first failure, and the false "could not confirm it stopped"), NF4 (the warning promises stops that a blocked group refuses) and NF5 (the primary is not where the resume lands). |
| **D16** | **FIXED** (NIT NF6c) | Unknown version: the warning says "restarted only if a newer version installs" and the job restarts iff `old != new` (`:461-462`). Equal: `current` both ways. Newer: "left running", `current`. Older: "restarted even if nothing new is installed", restarted. |
| A-N1: bundle tuple names | FIXED | `test_integration.py:1758-1773` walks tuple targets and checks every agent_cli top-level name. Read only, not run. |
| A-N3 / B-N1: `AGENT_REASON_DUP` twice | FIXED | It is gone from both files. Pinned at `test_term_vt_upgrade.py:185`. |
| A-N6 / B-N6: dedicated pane frees its own slot | FIXED | `agent_cli.py:494`, plus `test_n6_…`. |
| A-N7: keep the tail of output | FIXED | `agent_cli.py:172`. |
| A-N8: "resumed on v," | FIXED | `:626` sets `on_version` only for a known version, plus `test_n8_…`. |
| A-N9: rule-6 wording | **PARTLY** | It now says "loopback Host name when no login is configured" and "(or of unknown version, when the update changed…)". It still says "a version **other than** the installed one". Under D16 the code restarts only **older** sessions, and under D15 it also stops a copy on the installed (or a newer) version when another copy is older (`agent_cli.py:482-485`). **Way:** replace that clause in `.claude/rules/conventions.md` with "on a version older than the installed one (or of unknown version, when the update changed the installed version), together with every other tracker terminal running that same session, so that it is resumed once". Docs only, no test. |
| A-N10: `_APPLY` preview test | FIXED | `test_agent_routes.py:156`. |
| A-N12 / B "left alone": README note on `CLAUDE_*` | **REGRESSED** (docs) | See "README sentence" below. The reconcile row (`reconcile.md:147`) said **No change**, yet the sentence was added to `README.md:121`. |
| B-N2: client-written "out of date" | **PARTLY** | The warning renders the server's `out_of_date_text` (`ext_cr_dialogs.js:1347`). The job view still renders `[o.title, o.version, o.how]` (`:1370`), so the two views still disagree. **Way:** add `o.out_of_date_text` to `:1370`. **Test:** in `test_agents_ui`, assert that both `.join` lines that read `o.` include `o.out_of_date_text`. Red today. |
| B-N3: poller loses the toast | FIXED | `:1309-1326`: watch id, and `!r.ok` keeps polling. |
| B-N4: mode reset after a killed thin client | FIXED (no test) | `term_vt.py:3567`: `thin and confirmed`. |
| B-N5: thin client with no daemon found | FIXED | `term_vt.py:4152-4153`, plus `test_thin_client_without_its_daemon_is_not_stoppable`. |
| B-N8: README accuracy | FIXED | "resumed in a tracker terminal", "agents" in the Host check, the toast clause. |
| A-N4, A-N11, A-N13, A-N14, B-N7, B-N9 | no change (held) | As directed. |

**Counts: 19 FIXED, 0 NOT FIXED, 4 PARTLY (A1, D15, A-N9, B-N2), 2 REGRESSED (B-SF2, README A-N12).**

## Vacuity spot-check

I read each assertion against the code, as if the fix were reverted:
- Not vacuous: `test_k`, `test_a5_…`, `test_a2_…`, `test_busy_folder_shell_…_a6`, `test_confirm_naming_only_some_copies_stops_none` (without `:479-481` both copies are stopped), and `test_copy_that_cannot_be_stopped_blocks_the_group` (without `:476-478` t1 is stopped).
- **Pins a wrong contract:** `test_reused_pane_is_a_failure_never_resumed`. It encodes the misreading behind NF1.
- **Pins false text:** `test_unconfirmed_copy_resumes_none_and_fails_every_item` (`:474`) asserts that t1, which **was** confirmed stopped, reads "could not confirm it stopped" (NF3).
- Partly self-referential: the `job` half of `test_every_field_the_ui_reads_is_emitted_by_the_server`.

## README sentence: "start the tracker from a normal terminal, not from inside a Claude background job"

**It should go.** The product's own spawn path already strips the variable that causes the problem:
- `_fork_child` pops `CLAUDE_CODE_CHILD_SESSION` (`term_vt.py:1668-1671`).
- `tests/test_term_vt.py:2156-2172` (`test_pane_does_not_inherit_the_child_session_marker`) pins that, and its docstring cites the real-binary measurement: with that marker set, no `sessions/<pid>.json` is written.
- The S0 "trap" (`plan-final.md:1066`) was seen in a scratch pty harness that inherited the whole job environment, not through `open_pty`.
- The reconcile already ruled on this: "No change — the note described the scratch harness, not the product" (`reconcile.md:127, :147`).

Whether `CLAUDE_JOB_DIR`/`CLAUDECODE` alone suppress the pid file has never been measured. If the user wants certainty, one S9 live check settles it: start a tracker inside a background job, resume through it, and check that the pid file exists. Until then the sentence states an unproven hazard as a known gap. Delete the clause from `README.md:121`. No test (docs).

## New findings

### NF1 (BLOCKER): every resume into an existing folder shell is reported failed. This is the B-SF2 fix misreading `reused`.
- **Defect.** `agent_cli.py:601` reads `if code == 200 and obj.get("reused")` as "attached to a pane that still runs it". `open_pty`'s `reused` means "the folder shell already existed" (docstring `term_vt.py:3041-3042, 3070`). It is True on:
  - the typed resume (`:3289-3297`);
  - the deferred start (`:3278-3280`);
  - the daemon-client swap (`:3647`).

  That is the normal landing for an upgrade: `stop_for_upgrade` leaves a folder pane at its prompt (`:3560-3564`), and the resume is then typed into it. Only `_session_pty` hit (`:3152-3157`) and the peek (`:3252-3258`) type nothing.

  **Repro** (`probe_reused.py`, real `open_pty`): an idle settled folder pane `fo1`, with `{"session":"S","mode":"resume"}` → `200 {'tty':'fo1','reused':True,'folder':True}`, `typed: True`. Then `_agent_resume` → `failed | another tracker terminal (fo1) still runs this session, so it was not resumed — close it and press Upgrade again`.
  - Expected: `unprompted`, verified on the new version.
  - Actual: the session runs on the new binary, but the job, the summary and the toast all say it was not resumed. Verify skips it (`:614`). In a D15 group the closed copies are reported failed too (`:529-530`).
- **Fix direction.** Detect "nothing was typed" with a dedicated key. Do **not** change `reused`'s meaning: the SPA and the other clients read it.
- **Way.**
  - In `term_vt.open_pty`, add `"attached": True` to exactly the two nothing-typed replies: the `_session_pty` hit at `:3154-3157` and the peek at `:3257-3258`.
  - In `agent_cli._agent_resume:601`, test `obj.get("attached")` instead of `obj.get("reused")`.
  - Do not change any other reply.
- **Tests.**
  - (1) `test_term_vt_upgrade.CallRoute`: an idle folder pane plus a resume via `call_route` → `"attached"` not in the reply. A pane whose `fg` claims S → `attached` True.
  - (2) Turn `probe_reused.py` into a test: real `open_pty` → `_agent_resume` outcome `unprompted`. Red today.
  - (3) `FakeTV.call_route` returns `reused: True` by default, as the real folder landing does, and `attached: True` only when `self.reused`. Every folder-pane jobs test goes red on today's `:601`.

### NF2: a daemon session shown in two tracker panes is stopped and never resumed
- **Defect.** `_agent_restart_group` (`agent_cli.py:521`) calls `_agent_stop_daemon` once per copy.
  - The first copy runs `claude stop ab12` and waits for the worker pids to die.
  - The second copy then reads `_live_workers()`, which lists only live pids (`providers/claude.py:588-589`). It gets nothing and returns `failed AGENT_REASON_NOJOB` (`:558-559`).
  - With one copy failed, the group resumes none (`:522-525`).

  **Repro** (`probe_daemon_group.py`): two thin-client rows on target DMN, `job_short ab12`, `dup_group [t1,t2]` → `claude stop ab12` ran once, the worker is dead, pane stops `['t1']`, opens `[]`. t1 reads "could not confirm it stopped…" and t2 reads "its background job is gone from the daemon roster".
  - Expected: one `claude stop`, both panes cleared, one resume.
  - Actual: the session runs nowhere.
- **Fix direction.** For a daemon group, stop the worker once and then only clear each pane's thin client. The TUI group is unchanged.
- **Way.**
  - Split `_agent_stop_daemon` after the pid wait (`:580`) into `_agent_clear_thin(tv, cand)`, the tail at `:582-590`, where `closed` counts as confirmed.
  - In `_agent_restart_group`, when `prim["daemon"]`: call `_agent_stop_daemon(spec, prim)` (which includes the clear), then `_agent_clear_thin(tv, x)` for every other copy.
- **Test.** `DuplicateGroupTests.test_daemon_copies_stop_the_worker_once_and_resume_once`, the probe's shape. Assert one `|stop ab12` log line, `stops() == ['t1','t2']` and one open. Red today.

### NF3: the group keeps stopping after a copy fails, and reports a confirmed stop as unconfirmed
- **Defect.** `:521` stops **every** copy before it looks at any result. If the primary's stop errors (for example "a different program is now running…"), the other copies are still stopped, and the session ends up running nowhere.

  `:524` then reports every copy whose stop **was** confirmed (`bad is None`) as `AGENT_UNCONFIRMED`, "could not confirm it stopped, so it was not resumed".

  **Repro:** `test_unconfirmed_copy_resumes_none_and_fails_every_item`, with t2 unconfirmed → t1 (confirmed) reads "could not confirm it stopped". The test pins this at `:474`.
- **Fix direction.**
  - Stop in order (primary first) and stop at the first failure, so the remaining copies keep running.
  - Report each copy truthfully: stopped but not resumed, or not stopped.
- **Way.** In `_agent_restart_group`, loop over `order`; on the first `bad`:
  - push `bad` for that copy;
  - for each copy already stopped, push `failed` with a new `AGENT_DUP_NOT_RESUMED = "stopped, but not resumed: terminal %s could not be stopped and may still run it — resume it with the command below"`;
  - for each copy not yet tried, push `failed` with `AGENT_DUP_BLOCKED % <that tty>`;
  - return.

  Add the string to the §6 block.
- **Test.** Change `:467-474` as follows:
  - With t2 unconfirmed: t1's detail is `AGENT_DUP_NOT_RESUMED % "t2"`.
  - With t1 unconfirmed: `stops() == ["t1"]` (t2 is never stopped).

  Both are red today.

### NF4: the warning promises stops that a blocked group then refuses
- **Defect.** A group with one non-stoppable copy (for example "its folder no longer exists", or the thin-client-without-daemon case) still puts its stoppable copies in `stop[]`. The message reads "The following sessions: T, T will be stopped" (`agent_plan_upgrade:282-299`), and a non-primary copy even says "this terminal is stopped". The job then stops none of them (`:476-478`).

  **Repro:** `DuplicateGroupTests` with `cands[1].update(stoppable=False, …)` → `plan["stop"]` contains t1 and the message names it, but the job makes no calls.
- **Fix direction.** Make the warning equal the action: the stoppable copies of a blocked group are `cannot_stop` with the blocked reason.
- **Way.** In `_agent_split` (`:259-269`), after the split, move every `stop` row whose `dup_group` contains a `cannot` row's tty into `cannot` as `dict(c, stoppable=False, reason=AGENT_DUP_BLOCKED % that_tty)`. The `blocked` branch in `_agent_restart_all` then reduces to the existing `bad` path. Keep it as a guard, or delete it.
- **Test.** Extend `test_copy_that_cannot_be_stopped_blocks_the_group`: `plan["stop"] == []`, and t1 is in `cannot_stop` with `AGENT_DUP_BLOCKED % "t2"`. Red today.

### NF5: the primary is not where the resume lands, so `AGENT_DUP_WARN`'s "comes back once, in terminal <primary>" can be false
- **Defect.** The primary is the first stoppable copy in PTYS order (`term_vt.py:4174`). `_agent_resume` does not pass a tty, and `open_pty` types into `_folder_pty(session_cwd)` (`:3158`).

  **Repro:** copy a is a folder pane at `/w/wt` and copy b is a folder pane at `/w`, the session's cwd. The primary is a, and the warning says "comes back once, in terminal a". The resume lands in b, the terminal the warning said would be "left at its shell prompt".

  The brief's "resume ONCE into the primary's tty" is not implemented. Only the after-the-fact detail (`AGENT_DUP_CLOSED % tty_after`, `:529`) is honest.
- **Fix direction.** Choose as primary the copy `open_pty` will actually use. When there is no such copy, do not name a terminal.
- **Way.**
  - In `upgrade_candidates`, keep `cwd_to` per row in a local dict keyed by tty. Do not add a row key: row keys are the contract test.
  - Pick `first = next((x for x in g if x["stoppable"] and x["folder"] and x["cwd"] == cwd_of[x["tty"]]), None) or next((x for x in g if x["stoppable"]), None)`.
  - In `agent_plan_upgrade`, when the primary is not a folder pane on its `cwd_to`, use an `AGENT_DUP_WARN` variant ending "…the session comes back once, in a tracker terminal".
- **Test.** In `test_term_vt_upgrade`, two panes on X, a at `/other` and b with `cwd == session_cwd(X)` → b is primary. Red today.

### NF6 (NITs)
- (a) **Misleading heading.** A prompt-only caveat is listed under "Not confirmed on v<new> yet: X — resumed, but the prompt was not confirmed…" (`agent_cli.py:666-669`), which reads as if the version were unconfirmed. **Way:** put items whose `on_version is True` in a separate clause, "Prompt not seen yet: X — …". Test: a variant of `test_a5`.
- (b) **Partial confirm.** The copies the user **did** confirm are reported "not shown in the warning" (`:479-481`). This follows the brief, but the text is false for them. **Way:** for named copies, use a string such as "its other copy (terminal %s) was not confirmed, so neither was stopped".
- (c) **"Left running" is conditional.** `AGENT_VER_NEWER` says "left running" without a condition. If the update installs a version newer than the session's, the job restarts it (`:459` compares with `new`), and README "a newer one never" is then false. **Way:** append "unless the update installs a newer one" to both.
- (d) **Group exception path.** On an exception, the group pushes an item only for the primary (`:501-502`), so the other copies vanish from `items`. **Way:** push one item per member of `mem`.
- (e) **One-time flake.** One unidentified failure in `test_agent_cli_jobs` (1 of 5 runs, under concurrent `make check` load). Re-run it alone after the fixes. If it recurs, capture the failing test name.

## Final pass

Adversarial re-check (opus, 2026-11-16) of the round that fixed NF1-NF5 and the PARTLY rows A1, A-N9 and B-N2. I assumed
the fixer's report was false and traced each fix along the live path: route → agent_cli → term_vt → reply → item/summary/UI.

What I ran (no product code or tests edited; no Claude/Auggie process touched; no `make check`):
- Single modules: `test_agent_cli_jobs` (48), `test_term_vt_upgrade` (30), `test_agents_ui` (12), `test_agent_routes` (15),
  `test_agent_cli_parse` (7), `test_agent_cli_outside` (9). All OK.
- `probe_final.py` runs the real `term_vt.open_pty` through `call_route` and then the real `agent_cli._agent_resume`, one
  call per case:
  - (A) An idle settled folder pane gets `200 {reused: True, attached: None}`, the resume is typed, and the outcome is
    **`unprompted`**. The previous probe's failure is gone.
  - (B) A pane whose `fg` already claims S gets `attached: True`, nothing is typed, and the outcome is `failed
    AGENT_RESUME_REUSED`.
  - (C) Pane a is at `/other` and pane b is at the session's cwd. The resume lands in **b**.
- `probe_vacuity.py` re-executes each changed function inside the imported module with its fix reverted in the source,
  then runs that fix's tests. Every one goes red:
  - NF1 (`attached`→`reused`): 4 of 17 red.
  - NF2 (always `_agent_stop_one`): red.
  - NF3 (the old stop-all group): 2 of 2 red.
  - NF4 (blocker loop removed): red.
  - A1 (`not_restarted`→`failed`): red.
  - NF5 (the warning naming `t1` as the landing): red.
  - Baseline, unreverted: 23 of 23 green.
- B-N2's test reads the source and fails on the old `[o.title, o.version, o.how]` line. Both probe scripts were deleted
  afterwards.

| # | Verdict | Evidence |
|---|---|---|
| NF1 | **FIXED** | `attached: True` is set only on the `_session_pty` hit (`term_vt.py:3157`) and the peek (`:3259`). The cwd reply (`:3219`), the deferred start (`:3280`), the typed resume (`:3297`) and `_swap_in` (`:3648`) are unchanged, and `reused` keeps its meaning everywhere. No reader of the open_pty `reused` exists outside term_vt (I grepped `aitracker/` including `web/`; the SPA's `st.attached` comes from `/api/term/attached`'s `claude_attached`, `ext_cr_term.js:1217`). `_agent_resume` reads `attached` (`agent_cli.py:625`). Probe (A)/(B) as above. `FakeTV.call_route` now returns `reused: True` on every landing (`test_agent_cli_jobs.py:64`), so every jobs test exercises the real reply shape. |
| NF2 | **FIXED** | `agent_cli.py:535`: in a daemon group only the primary goes through `_agent_stop_one` → `_agent_stop_daemon`, which makes one `claude stop` call and clears the primary's thin client (`:600`). Every other copy gets `_agent_clear_thin` (`:603-614`), where a closed pane counts as cleared. The group then resumes once (`:544`). `test_nf2_…` (`test_agent_cli_jobs.py:196`) asserts one `\|stop` log line, `stops == [t1, t2]` and one open. It is red when reverted. |
| NF3 | **FIXED** (wording NIT, NF8) | `:532-542`: the primary goes first, and the first `bad` halts the group. Copies already stopped get `AGENT_DUP_NOT_RESUMED % <failing tty>`, and untried copies get `AGENT_DUP_BLOCKED % <failing tty>` and are never stopped. `test_failed_primary_stop_leaves_the_other_copies_running` (`stops == ["t1"]`) and the corrected `test_unconfirmed_copy_…_truthfully` are both red when reverted. |
| NF4 | **FIXED** | `_agent_split` `:273-276` moves every stoppable copy of a group that has a `cannot` member into `cannot` with `AGENT_DUP_BLOCKED % blocker`. The warning (`:288`) and the job (`:455`) share the same split, so warning == action. The job then reports those rows as `not_restarted` (`:461`). The `blocked` branch (`:483-485`) is now unreachable and is kept as a guard. The test asserts `plan["stop"] == []` and the `cannot_stop` reasons. Red when reverted. |
| NF5 | **PARTLY** (see NF7) | `AGENT_DUP_WARN` (`:55-56`) now ends "…comes back once, in a tracker terminal" and names no landing terminal. The after-the-fact `AGENT_DUP_CLOSED % item["tty_after"]` (`:547`) names the real landing tty. Primary selection is unchanged, as reconciled. But the same string still tells the non-primary copy "this terminal is stopped and **left at its shell prompt**", and in NF5's own repro that copy is the one the resume lands in (probe C). |
| A1 | **FIXED** | `:461` gives `not_restarted`, and the summary prints `Not restarted: … — <reason>; run \`cmd\`` (`:687-689`). `test_a1_…` asserts "Not restarted: TS3 — its folder no longer exists" and that "Failed: TS3" is absent. Red when reverted. |
| A-N9 | **FIXED** | `.claude/rules/conventions.md:19` now says "on a version older than the installed one (or of unknown version, when the update changed the installed version), together with every other tracker terminal running that same session so that it is resumed once". This matches `_agent_restart_all` `:464-469` and `:480-494`. |
| B-N2 | **FIXED** | The job view now reads `[o.title, o.version, o.out_of_date_text, o.how]` (`ext_cr_dialogs.js:1370`), the same as the warning (`:1347`). `test_b_n2_…` (`test_agents_ui.py:32`) requires both lines. |
| README known-gap sentence | FIXED (not in scope, checked in passing) | `grep "Claude background job\|normal terminal" README.md` finds nothing. |

**Callers.**
- `_agent_resume` is called from `_agent_restart_one` (`:524`, return value unused) and `_agent_restart_group` (`:544`).
- `_agent_split` is called from the warning (`:288`) and the job (`:455`).
- `_agent_restart_group` has one caller (`:507`).
- No other code consumes the open_pty `attached` key or the new `not_restarted` outcome. The SPA renders `i.detail`
  only, so it is outcome-agnostic.

I found nothing broken in these callers.

**Counts: 7 FIXED, 1 PARTLY (NF5), 0 NOT FIXED, 0 REGRESSED.** No vacuous test among the six fixes I reverted.

### NF7: the duplicate warning still says the non-primary copy is "left at its shell prompt"
- **Defect.** `AGENT_DUP_WARN` (`agent_cli.py:55`) is shown on every non-primary copy (`:298-299`), and it says "this
  terminal is stopped and left at its shell prompt". That is false in two cases:
  - (a) The copy is the folder pane at the session's cwd. `open_pty` types the resume into `_folder_pty(session_cwd)`
    (`term_vt.py:3158`), so the session comes back **in this terminal**.
  - (b) The copy is a dedicated (non-folder) pane. `stop_for_upgrade` confirms only once `pt.done` (`term_vt.py:3567`),
    so the pane closes. There is no shell prompt.
- **Repro.** Two folder panes run S: a at `/other` (first in PTYS order, so primary) and b at `session_cwd(S)`.
  - b's `dup_text` reads "the same session as terminal a — this terminal is stopped and left at its shell prompt; …".
  - Probe C shows the resume landing in b (`tty: 'b'`, typed).
- **Fix direction.** The warning must claim nothing about where any copy ends up. Do not change primary selection or the
  after-the-fact `AGENT_DUP_CLOSED` text.
- **Way.** One string, `agent_cli.py:55-56`: `AGENT_DUP_WARN = "the same session as terminal %s — this terminal is
  stopped too; the session comes back once, in a tracker terminal"`. No code change.
- **Test.** In `DuplicateGroupTests.test_warning_row_for_the_non_primary_copy`, add
  `self.assertNotIn("shell prompt", rows["t2"]["dup_text"])`. It is red today.

### NF8 (NITs, left to the main thread)
- (a) **"The command below" points at nothing in the job view.** `AGENT_DUP_NOT_RESUMED` ends "resume it with the
  command below". The job view renders items as `[i.title, i.detail]` only (`ext_cr_dialogs.js:1366-1368`). The command
  appears only in the summary, *above* the items, as "; run \`…\`".
  - **Way:** end the string "…may still run it — resume it with its command", or render `cmdLines(i.command)` for failed
    items.
  - **Test:** a `test_agents_ui` source check, or a string assert.
- (b) **Daemon groups.** After the primary's `claude stop` has confirmed the worker dead, a failure to clear a later
  thin client produces two false statements:
  - the primary reads that the failing copy "may still run it";
  - untried copies read that the session "also runs in terminal X".

  In fact the session runs nowhere. The halt itself is correct: a still-labelled thin-client pane would make the resume
  an `attached` hit.
  - **Way:** in `_agent_restart_group`'s `bad` branch, when `prim.get("daemon")` and the primary already stopped, use a
    daemon variant: "stopped (its background job ended), but not resumed: terminal %s still shows it — close it and
    resume with the command".
  - **Test:** `DaemonPaneTests` with `stop_res = {"t2": {"confirmed": False}}`: assert the primary's detail is the daemon
    variant.
