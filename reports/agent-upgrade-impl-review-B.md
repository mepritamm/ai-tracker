# Agent upgrade — implementation review B (terminal tier, UI, docs, tests)

Reviewer B (opus, adversarial). Worktree `agent-upgrade`, uncommitted changes on `fe8f580`. Scope: `term_vt.py`
(`_with_prompt` in the resume arm, `upgrade_candidates`, `stop_for_upgrade`, `_agent_kids`, `_agent_sweep`,
`_Internal`, `call_route`, `AGENT_REASON_DUP`, `_fork_child`), `web/ext_cr_dialogs.js` Agents section, the UI field
check against `agent_cli.py`/`server.py`, README/CLAUDE.md, the `test_selfcheck.py` TestCase, and the quality of
`tests/test_term_vt_upgrade.py` and `tests/test_agents_ui.py`.

Method: `git diff -U0` hunk headers plus symbol greps and range reads; no whole-file diffs. Ran
`tests.test_term_vt_upgrade` and `tests.test_agents_ui` (29 tests, OK). One repro ran from a scratch script outside the
repo (`~/.claude/jobs/0f4ee7b4/tmp/revB/repro_dup.py`, subclasses the existing fixture). No product code or tests were edited.

**Verdict: no BLOCKER. 6 SHOULD-FIX, 9 NIT.** The signalling core (`stop_for_upgrade`, `_agent_sweep`, pid and
start-time guards) holds up on the live path. The defects are in what the user is told (the warning and the final
summary) and in tests that would stay green if the feature broke.

---

## SHOULD-FIX

### SF1. Dedupe treats "unknown session" as one shared target, so the warning promises a restart that never happens
1. **Defect.** `term_vt.py:4164-4170`: the dedupe keys on `r["target"]`, and every pane with no session id has
   `target == ""`. On this machine a bare `claude` opens the agent view, so two such panes are common. **Repro**
   (ran it): two unlabelled folder panes, no pid file → row 1 reason "the tracker cannot tell which session this
   terminal runs…", **row 2 reason "the same session as terminal a; restarted there"**. Expected: both rows carry
   the "cannot tell" reason. Nothing is restarted "there". This is the text the user consents to.
2. **Direction.** Skip empty targets in the dedupe. Do not change the order of the preflight checks or the text of
   the other reasons.
3. **Way.** In `upgrade_candidates`, change the dedupe loop to `for r in rows: if not r["target"]: continue; …`.
   The other preflights depend only on the target (`resume_argv`, `session_cwd`, the daemon short) or are global
   (`allowed`), so `""` is the only key that collides wrongly. Claude only. Auggie has no candidates.
4. **Test.** In `UpgradeCandidates`, add `test_unknown_panes_are_not_deduped`: `self.pane("a",100); self.pane("b",101)`
   → both reasons start with "the tracker cannot tell". It is red today (see the repro).

### SF2. A real duplicate pane, or any pane still claiming the target, makes the resume a silent no-op
1. **Defect.** `open_pty`'s resume arm returns `reused: True` with HTTP 200 and types nothing when
   `_session_pty(sid)` finds a live pane claiming the session (`term_vt.py:3148-3157`). `_agent_resume`
   (`agent_cli.py:522-526`) treats any 200 as resumed and never reads `reused`.
   - **Repro A.** Pane a has the `fg` claim X. Pane b runs a hand-typed `claude --resume X` (`fg` None, pid file X).
     In PTYS order b comes first, so b is stoppable and a gets `AGENT_REASON_DUP`. b is stopped. The resume of X hits
     pane a's live claim and returns `reused` with `tty_after = a`. The item reads "Resumed… / Resumed in a new
     terminal". Verify then finds X on a's **old** binary and reports `AGENT_VERSION_MISMATCH` ("another claude may be
     first on your shell's PATH; run Doctor"), which is the wrong diagnosis. a was never restarted.
   - **Repro B.** The order is reversed. a is stopped and resumed in a fresh shell, so two Claudes now run X. b stays
     on the old version while its row said "restarted there".
   - The plan's "restarted there" (S7) cannot be reached with open_pty's attach-to-existing rule.
2. **Direction.** Never report a reattach as a restart, and never half-restart a duplicated session. Keep the
   one-at-a-time order, and keep `_session_pty`'s attach semantics for normal opens.
3. **Way.** Two small edits.
   - (a) `agent_cli._agent_resume`: on `code == 200 and obj.get("reused")`, record `outcome "failed"` with detail
     `AGENT_RESUME_REUSED % obj.get("tty")`. Suggested text: "another tracker terminal (%s) still runs this session,
     so it was not resumed — close one and press Upgrade again". Add the constant to the §6 string block.
   - (b) `term_vt.upgrade_candidates` dedupe: when a target repeats, mark **every** row of that target not stoppable
     with reason "runs in more than one terminal (%s) — close all but one and press Upgrade again" (the ttys joined).
     Do not stop the first one.
   - Then delete the now-wrong "restarted there" text from both copies (see N1). This changes the S7 decision, so
     flag it to the user. The alternative is to stop every duplicate pane before the single resume.
4. **Tests.**
   - `test_term_vt_upgrade.test_dedupe_same_target_s7`: both rows `stoppable False`, and the reason names "a" and
     "b". Red today, because r1 is stoppable.
   - New `test_agent_cli_jobs` case: the fake `call_route` returns `(200, {"tty": "t9", "reused": True})` → the item
     is `failed`, and the summary has no "Resumed".

### SF3. `cannot_stop` rows are reported as "not shown in the warning" in every summary
1. **Defect.** The UI confirm sends only the `stop` rows (`ext_cr_dialogs.js:1347`). `_agent_restart_all`
   (`agent_cli.py:432-435`) checks the confirm pairs **before** `c in cannot`. So every non-stoppable pane the user
   **was** shown (an agent-view pane, a dup, a missing folder) ends up as `not_shown`. The summary then says
   "Failed: X — not shown in the warning, not stopped; run `…`" (`agent_cli.py:583-585`). **Repro:** one
   agent-view pane plus one normal pane, press Upgrade and confirm → the summary claims the agent-view pane was not
   shown. Expected: "Failed: X — the tracker cannot tell which session…".
2. **Direction.** A row that is not stoppable is reported with its own reason, whether or not it was in the confirm.
   `not_shown` stays only for stoppable rows the user did not see. Nothing new gets stopped.
3. **Way.** In `_agent_restart_all`, keep the `current` checks first if desired, then test `c in cannot` before the
   pairs check: `if c in cannot: push(failed, reason)` → `elif pair not in pairs: not_shown` → …. Claude only.
4. **Test.** New `test_agent_cli_jobs` case: the fake tv returns one `stoppable False` candidate with reason R, and the
   confirm is `[]` → the item outcome is `failed` and its detail is R. It is red today (`not_shown`).

### SF4. A prompt that never landed is still announced as sent (clause 6 "notify the user about that as well")
1. **Defect.** `_agent_verify` (`agent_cli.py:564-565`) sets `prompt_seen=False` but writes no `detail`. The summary's
   "Not confirmed" part (`agent_cli.py:586`) only lists items that have a detail. The UI renders no field for
   `prompt_seen` (`ext_cr_dialogs.js:1360-1362`). **Repro:** the `--fork-session` backstop drops the prompt (a known
   limit, plan §5.3), or `user_line_has` stays False → the summary says "Resumed with “continue, re-read CLAUDE.md”…:
   A" and nothing tells the user it was not seen.
2. **Direction.** The server writes one sentence for an unseen prompt. The UI keeps rendering `detail` only. Rule 5
   holds (no client-side text).
3. **Way.** Add `AGENT_PROMPT_NOT_SEEN = "resumed, but “continue, re-read CLAUDE.md” was not seen in its transcript —
   type it yourself"`. In the final loop of `_agent_verify`, when setting `prompt_seen=False`, also set
   `detail=(it["detail"] + " " + AGENT_PROMPT_NOT_SEEN).strip()`. The summary and the job view then pick it up
   without further change.
4. **Test.** In `test_agent_cli_jobs`: patch `user_line_has` to always return False, use a busy candidate and a
   patched clock → the item detail contains "was not seen", and so does the summary. It is red today.

### SF5. Selfcheck assertion is in the wrong place, under a false comment
1. **Defect.** `tests/test_selfcheck.py:1483-1499` adds `class AgentUpgradeSelfcheck(unittest.TestCase)` with the
   docstring "_run() above is not collected by unittest". That is false: `tests/test_tracker.py:23` imports `_run`, and
   `TestSelfcheckSmoke.test_selfcheck_passes` (`test_tracker.py:69-74`) runs it. Conventions rule 9 and plan §11 both
   put the assertion in `_selfcheck()`/`_run()`, before `print("selfcheck ok")`.
2. **Direction.** Move the assertion block, unchanged, into `_run()` just before `print("selfcheck ok")` (line 1481).
   Delete the TestCase and its comment. Do not duplicate the assertion. Its content is pure: no binary is run and no
   session is touched, which is safe under test_tracker's repointed globals.
3. **Way.** Make one edit in `tests/test_selfcheck.py`. The local imports `_ac`/`_AP` stay inside `_run()`.
4. **Test.** Prove it red: temporarily make `_agent_was_busy` return False → `tests.test_tracker` goes red at
   `TestSelfcheckSmoke`. Then restore it.

### SF6. Tests that stay green when the feature breaks
1. **Defect.**
   - (a) `test_agents_ui.test_section_listed_and_dispatched` asserts `"agentsBlock()" in s`. That string also matches
     the definition `function agentsBlock()` (`ext_cr_dialogs.js:1322`), so the test stays green with the dispatch
     at `:1697` deleted.
   - (b) `test_no_server_text_hardcoded` checks three phrases only. Any other client-written sentence passes, for
     example `'out of date'` at `:1341` today.
   - (c) No test pins the field contract between the UI and the server. Renaming `version_text`, `state_text`,
     `reason`, `how`, `summary`, `step` or `checking` server-side keeps every UI test green, and the UI silently
     renders blanks.
   - (d) No test pins the candidate row's keys between `upgrade_candidates` and `agent_cli`. The jobs tests use a
     hand-built fake tv, and `agent_cli._agent_resume` reads `cand["cols"]`/`cand["rows"]` **after** a confirmed stop
     (`agent_cli.py:517`). A renamed key there means a session stopped and never resumed, with every test green.
   - (e) `ResumePromptArgv` covers only the `_inject_argv` path. The overflow `spawn` path is unasserted.
   - (f) `UpgradeCandidates` never exercises a dedicated (non-folder) pane (`pg = p.pid`) or `thin=True`.
2. **Direction.** Strengthen the tests only. No product change.
3. **Way.**
   - (a) Use `assertRegex(s, r"active === 'Agents'\) \{\s*var agEl = agentsBlock\(\); if \(agEl\) body\.appendChild\(agEl\)")`.
   - (b) Extract every quoted literal in `_agents_code()` and assert each one is in an allow-list: button labels,
     'checking…', 'Loading…', 'request failed', class names, routes, 'GET'/'POST', 'doctor'/'upgrade'/'running',
     and the separators.
   - (c) In `test_agents_ui`, regex-collect `\b(a|c|o|i|j|job|plan)\.([a-z_]+)` from the agents code. Build a real
     `agent_status()` and an `agent_plan_upgrade("claude")`, the latter with a fake `aitracker.term_vt` whose
     `upgrade_candidates` returns one stoppable and one non-stoppable row, plus a finished job snapshot. Assert that
     each read name is a key of the matching emitted dict.
   - (d) In `UpgradeCandidates`, assert that `set(r)` equals the 20 plan §5.3 keys. Build the jobs-test fake candidate
     from that same tuple.
   - (e) Add an overflow-path case that patches `spawn` and asserts the argv ends with the prompt.
   - (f) Add a dedicated-pane case: `pt.folder=False`, pid-file match on `pt.pid`.
4. **Test.** Each new assertion must be proved red by its matching revert: delete the dispatch line, rename
   `version_text` in `agent_cli`, rename `cols` in `upgrade_candidates`, drop `_with_prompt` from the resume arm with
   the overflow path forced.

---

## NIT

- **N1. `AGENT_REASON_DUP` has two copies and no pin** (`term_vt.py:3462`, `agent_cli.py:51`). agent_cli never uses its
  copy; term_vt produces the reason. Direction: delete the agent_cli copy, which is dead. If kept, add
  `assertEqual(term_vt.AGENT_REASON_DUP, agent_cli.AGENT_REASON_DUP)` to `test_term_vt_upgrade`. After SF2(b) the text
  changes anyway, so make it one constant in term_vt.
- **N2. Client-written status text.** `ext_cr_dialogs.js:1341` writes `'out of date'` for the server boolean (rule 5:
  the server owns labels). The job view (`:1364`) drops out-of-date entirely, so the two views disagree. Direction:
  `_agent_outside` emits `out_of_date_text` (for example `"out of date (installed v%s)"`, or ""), and both views
  render that field. Test: the SF6(b) allow-list goes red on `'out of date'`. The separators, 'Loading…' and
  'request failed' are generic UI chrome, the same as `updateBlock`: no change.
- **N3. The poller can lose the toast.** `agentWatchJob` (`:1309-1320`) clears itself on any failed poll (`!r.ok` →
  `j` falsy), and it refuses to start while an older job's timer is alive (`if (_agentJobTimer) return`). Confirm an
  Upgrade within 2 s of a Doctor finishing and the new job gets no watcher, so no toast. Direction: keep polling on
  `!r.ok`, and only clear on `r.ok` with a different or absent job. Track `_agentWatchId`, and when `id` differs,
  clear and restart. Test: a string assertion that `r.ok &&` guards the clear branch (static, as the other UI tests).
- **N4. Mode reset after a killed thin client.** `term_vt.py:3568` feeds `_TERM_MODE_RESET` only when `graceful`, but
  its own docstring (`:3366`) says it is for a **killed** client. Direction: feed it when `thin and out["confirmed"]`.
  Optionally also do it for any folder pane whose Claude was SIGKILLed, since a killed TUI leaves the alt screen on.
  Test: a fake thin pane with a SIGTERM-ignoring fg → assert `pt.screen` received `?1049l`.
- **N5. A thin client whose daemon lookup failed is treated as a TUI.** `upgrade_candidates` sets `daemon` only from
  `_background_target(sid)`, which returns "" on an unreadable roster. A pane with `thin=True` and `daemon=False` is
  then "restarted" by killing the viewer and `--resume`, which reattaches to the old worker. The outcome is honest
  (verify flags `AGENT_STILL_DAEMON`) but useless. Direction: `if thin and not daemon:` set it not stoppable with
  "could not find its background job". Test: patch `_thin_client_short` to return "ab12" with no bg → not stoppable.
- **N6. `needs_slot` for a dedicated pane at the cap.** The slot check (`agent_cli.py:448`) counts the dedicated pane
  that the stop itself would free, so it refuses with `AGENT_NO_SLOT` when stopping would actually fit. It is safe
  (nothing is stopped). Direction: no change, or subtract 1 when `not cand["folder"]`. Document it in the PR.
- **N7. The sweep's SIGKILL pass re-identifies by the leader only** (`term_vt.py:3493-3496`). If the group leader exits
  on SIGTERM but a member that traps SIGTERM survives, the member is never killed. Direction: no change. It is a
  known gap and fails safe. Mention it in the PR.
- **N8. README accuracy.** All in `README.md`.
  - "resumed in that terminal" (the daemon sentence) is not always true. The resume goes to the session-cwd folder
    shell, and the summary says "resumed in a new terminal". Say "in a tracker terminal".
  - Add "agents" to the local-only route list in the "Host check" bullet (line 293).
  - Add one clause saying the completion toast shows in the tab that started the job, or that has Config open (no
    reload catch-up, §15.2).
- **N9. Read-only shows an empty Agents tab.** `agentsBlock` returns null (`:1323`), but `'Agents'` stays in
  `sections` (`:1443`). Direction: no change, or omit the tab when `crReadOnly()`. This is cosmetic.

## Reviewed and left alone (direction stated)

- **`_fork_child`:** back to base. The term_vt diff has exactly four hunks (`_with_prompt` docstring, the resume-arm
  line, the 134-line block at 3462, the 78-line block at 4098). `CLAUDE_CODE_CHILD_SESSION` is the only `CLAUDE_`
  name in the file, the same as base `fe8f580:1671`. No change.
  - **But** the plan §13 V2r decision ("open_pty must not leak CLAUDE_* job vars into pane shells (add a test/README
    note)") is **not discharged**. Neither a README note nor a test landed. A tracker started from inside a Claude
    job (`CLAUDE_JOB_DIR`, `CLAUDECODE` inherited) gives resumed panes that write no pid file. Upgrade then reads
    every version as unknown, and verify reports "not yet seen running".
  - Direction: add a README known-gap clause ("start the tracker from a plain terminal, not from inside a Claude
    session or background job"). Whether to pop exactly `CLAUDE_JOB_DIR` and `CLAUDECODE` in `_fork_child` is a
    user decision. The over-wide scrub was reverted for a reason this review did not see.
  - Count this as part of SF5's doc pass if preferred.
- **GET `/api/agents` is local-caller only** (`server.py:479-484`). This is the intended exception. The no-host-gating
  rule is about the client reading `location.*` to hide recorded data (`docs/terminal-tiers-build-log.md:38`). The
  agents code reads no `location`. The server gate is the same `_local_caller` that `/api/update` and
  `/api/pending/run` use. A remote client sees the server's own 403 text. No change, beyond the README line in N8.
- **The UI polls while `checking`** (`:1407`). This is correct. Without it, "checking…" never resolves and Upgrade
  stays disabled until Config is reopened. It is bounded by the refresh. No change.
- **`stop_for_upgrade` identity and pid reuse.**
  - The identity check is the pgid under `_LOCK` (`:3510-3524`), and `_agent_sweep` re-checks `lstart` before every
    signal.
  - The 0, own and shell groups are refused, and SIGKILL never hits the shell (`:3541`).
  - The folder tty is reused after a stop, because the claim is cleared via `_refresh_fg` (`:3562-3565`, test green).
  - `call_route` reaches only `handler._json`/`headers` (grep: 20× `_json`, guard reads only `headers`). With
    `TRACKER_AUTH` set the guard does not check Host, so the resume is not 403.
  - No change.
- **The stale label is corrected (B2)** at `:4122-4124` and tested. A resume never uses `mode: "new"`: it is hardcoded
  at `agent_cli.py:517`, and jobs test (b) pins it. No change.

## Contract check (plan §1 and D1-D14)

| Clause | Verdict | Evidence |
|---|---|---|
| 1 Doctor/Upgrade + "will be stopped… continue again with a prompt" message | Discharged (code) | `agent_cli.py:26-31,109-114`; UI `ext_cr_dialogs.js:1330`; SF1 false row text |
| 2 Agents the tracker manages | Discharged (code) | `agent_specs` `agent_cli.py:176`; Claude + Auggie in selfcheck |
| 3 Force all busy, with warning | Discharged | `stop_for_upgrade` `term_vt.py:3502`; `state_text` `agent_cli.py:274` |
| 4 Outside sessions show-only | Discharged | `_agent_outside` `agent_cli.py:290`; UI `:1339-1343` (N2) |
| 5 Always latest | Discharged | `update == ["update"]` (selfcheck) |
| 6 Resume + prompt + notify | **Partly** | prompt `term_vt.py:3121`, `agent_cli.py:518`; notification wrong for unseen prompt (SF4) and reattach (SF2) |
| 7 Manual only | Discharged | buttons only; no scheduler |
| 8 Auto-update note | Discharged | `agent_cli.py:23`; UI `:1344,:1387` |
| D1-D4 | Superseded (D5-D7) / moot | reconcile |
| D2 unknown-id exception | Discharged | `term_vt.py:4137-4139` |
| D5 daemon panes stopped + resumed | Discharged (code) | `agent_cli.py:473-513`; `stop_for_upgrade(thin=True)` |
| D6 prompt only for busy | Discharged | `_agent_was_busy` `agent_cli.py:117`; summary parts `:575-579` |
| D7 build on landed helpers | Discharged | `_run/_APPLY` imports `agent_cli.py:10`; `_local_caller` `server.py:481`; `_with_prompt` reused |
| D8 restart old even if nothing installed | Discharged | `agent_cli.py:428-443`; `version_text` `:121` |
| D9 / D14 scratch live proof | Not examined | S9 live results not in scope |
| D10 Auggie upgrade, no restart | Discharged (code) | `restarts_sessions` gate `agent_cli.py:407` |
| D11 waiting = busy | Discharged | `agent_cli.py:118` |
| D12 failed update stops nothing | Discharged | `agent_cli.py:395-400` |
| D13 warn on daemon → terminal move | Discharged | `AGENT_STATE_DAEMON_MOVE` appended `agent_cli.py:274` |
| §13 V2r "test/README note" on CLAUDE_* leak | **Not discharged** | no README/test line (see "left alone") |

## Not examined

- `agent_cli.py` internals beyond the shapes and the restart/verify paths cited: version cache, Auggie outside rows,
  `_agent_strip`, bundle names.
- `server.py` route gates beyond the diff.
- `update.py`, the providers (`running_sessions`, `session_state`, S1's None-guard), `test_agent_cli_*`,
  `test_agent_routes`, `test_claude_running`.
- The conventions rule-6 text, and the S9 live proof.
- The `_swap_in` interaction when a resume's session-cwd folder pane is itself a later candidate's thin client.
- Real-pty behaviour of `stop_for_upgrade` on a dedicated (overflow) pane, which is reasoned from `Pty` finish
  (`:1608`), not run.
- No revert-to-red was performed (edits were forbidden). The red/green judgements are by reading.
