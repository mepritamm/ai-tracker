# Resume all prior terminals: adversarial review of the final plan

Reviewer: opus, second pass, 2026-11-16. Target: `reports/resume-all-plan-final.md` as it stood before this review.
Authority: `reports/resume-all-reconcile.md`, including the main thread's reversal of per-port keys. Everything was
checked against the worktree code by grep and range reads. The AU feature is uncommitted and other reviewers were
editing it during this review. `agent_cli.py` and `ext_cr_dialogs.js` changed while this review ran; every line
number below is from a re-read after those changes.

**Verdict:** the plan was not ready as written. It had one BLOCKER (the per-port record the main thread reversed) and
six SHOULD-FIX findings. All of them are now folded into `resume-all-plan-final.md`, which is ready to implement.
Counts: **1 BLOCKER, 6 SHOULD-FIX, 8 NIT.**

## Findings

### BLOCKER

**F1. The record is keyed by port, but the main thread reversed that.**
- Where: plan §2 and §3.2, the strings in §3.4, §7.7, tests T3/T4/T6/T7/T16, §10 and §12.3.
- Defect: `prior_terminals()` reads `d.get(_REMEMBER_PORT)`.
- Repro: a tracker on 8790 runs sessions A and B, then stops. `make serve` finds 8790 busy (CLAUDE.md: "or the next
  free port if busy") and binds 8791. `d.get("8791")` returns None, so the button says "Nothing to resume (port
  8791)". A and B, the sessions the button exists for, are not offered. Expected: A and B listed.
- Fix direction: one merged history shared by every tracker started from this checkout. It is a JSON dict keyed by
  session id. Each tick merges the live panes in, and the newest `seen` wins. Writes go through
  `store._update_json`, so two trackers never drop each other's entries. Drop `boot`, `saved_at`, `prior`,
  `_terms_record`, the generation rule, `LAST_TERMS_PORTS`, `_REMEMBER_PORT`, `_HISTORY`/`_HIST_LOCK`,
  `AGENT_RA_STOPPED`, `_agent_ra_age`, and `port`/`saved_at` in the HTTP body. Keep the 32-entry bound, dropping
  entries whose transcript is gone (at read time), the "never replace non-empty with empty" rule, and the
  `_update_json` locking.
- Way:
  - `term_vt._merge_terms(d, live) -> bool` is pure and mutates `d`. If `live` is empty it returns False: no write,
    nothing removed, nothing pruned. Otherwise it drops malformed values, sets `seen = max(new, old)` per session id,
    keeps the 32 newest by `seen`, and returns True.
  - `remember_terminals` calls `store._update_json(config.LAST_TERMS_FILE, lambda d: _merge_terms(d, live))`.
  - `remembered_terminals()` replaces `prior_terminals()`. It reads the file, which is the history, so no in-memory
    copy is needed.
  - Must NOT change: no shutdown write; closing a pane never removes an entry.
- Tests:
  - T2 `_merge_terms`: `{A}` merged with live `{}` returns False and leaves `{A}`. Red: rebuild from live only, and
    A is lost.
  - T3 two trackers: a file holding X written by another tracker, plus a tick with live Y, leaves `{X, Y}`. Red:
    write only `live`.
  - T7: a fresh run with no history of its own still lists the file's A and B. Red: the per-port read.

### SHOULD-FIX

**F2. `raParts()` breaks two existing node suites.**
- Where: plan §4, Manage terminals.
- Defect: `if (!ra && !crReadOnly() && payload.onRefresh)` evaluates `crReadOnly()` before the `onRefresh` gate.
  `tests/test_cr_manage_terminals_parity.py` (harness around `:100-125`) and `tests/test_cr_manage_terminals_poll.py`
  (`:99`) lift `renderManageTerminals` alone into a stub scope. That scope defines `h`, `timeAgo`, `cwdTail`,
  `sessionTitleFor` and `icon`, but not `crReadOnly` or `resumeAllWidget`.
- Repro: the empty branch or the footer calls `raParts()`, which throws `ReferenceError: crReadOnly is not defined`,
  and both suites go red. Plan §9 says existing tests stay green and does not list either suite.
- Fix: test `payload.onRefresh` first: `if (!payload.onRefresh || crReadOnly()) return null; if (!ra) ra =
  resumeAllWidget(...); return ra;`. The harness payloads carry no `onRefresh`, so neither name is touched.
- Test: both suites green unchanged. Red: the plan's original order.

**F3. The `agentWatchJob(id, onDone)` change is written against code that no longer exists.**
- Where: plan §4.
- Defect: AU now has `var _agentJobTimer = null, _agentToasted = null, _agentWatchId = null;`
  (`ext_cr_dialogs.js:1308`, asserted by `tests/test_agents_ui.py:48`). It restarts the timer when called with a new
  id and ignores failed polls (`:1309-1327`). The plan's "add `if (onDone) ...` before `if (_agentJobTimer)
  return;`" no longer matches. Written naively, switching ids would orphan the previous `onDone`, leaving that
  widget busy forever.
- Fix:
  - Keep AU's line as it is, whatever it says at implementation time, and put `var _agentJobDone = null;` on its own
    line after it.
  - Add `function _agentFireDone(j)`, which takes the stored callback, clears it, and calls it.
  - Same id while watching: store `onDone` and return.
  - Different id: clear the old timer, call `_agentFireDone(null)`, then store the new callback.
  - Stop paths: "job gone/replaced" calls `_agentFireDone(null)`. "Finished" calls `_agentFireDone(j)` after the
    toast. A failed poll fires nothing.
- Test (T15 node): `watch(1, cbA)` then `watch(2, cbB)` calls cbA once with null. Job 2 finishing calls cbB with
  job 2. A poll answering `ok: false` fires neither. Red: drop `_agentFireDone(null)` on the switch, and cbA is
  never called.

**F4. AU's new "reused" branch gives resume-all items Upgrade wording.**
- Where: `agent_cli.py:600-601`, `_agent_resume`.
- Defect: `code == 200 and obj.get("reused")` now marks the item failed with `AGENT_RESUME_REUSED` (`:58`):
  "another tracker terminal (%s) still runs this session ... press Upgrade again".
- Repro: a session is opened by hand between the confirm and its turn in the job. The resume-all summary then says
  "press Upgrade again".
- Fix: add a parameter `_agent_resume(job, tv, cand, busy, reused=AGENT_RESUME_REUSED)`; the default keeps AU
  unchanged. The resume-all job passes `AGENT_RA_REUSED = "already open in tracker terminal %s, so it was not
  opened again"`.
- Test: T12 case D, where `call_route` returns `(200, {"tty": "t4", "reused": True})`, gives an item failed with
  exactly `AGENT_RA_REUSED % "t4"`. Red: no parameter. AU's tests stay green with the default.

**F5. Dead data forces a change to AU's `upgrade_candidates`.**
- Where: plan §3.2.
- Defect: the plan adds a `"started"` key to `upgrade_candidates` (`term_vt.py:4155-4162`) only to fill
  `entry.opened`. Nothing reads `opened`: sorting, pre-ticking and display all use `seen`.
- Fix: cut `started` and `opened`, and leave `upgrade_candidates` untouched.
- Test: none needed. `tests/test_term_vt_upgrade.py` stays untouched.

**F6. The UI test T15 is too vague for a cheaper implementer.**
- Where: plan §9 T15.
- Defect: the widget's behaviour (checkboxes, double click, picker surviving `update`) cannot be tested with only
  `renderManageTerminals` lifted, which is the idiom the plan cites. The plan's way of reading the ticks is not
  specified, and a stub tree has no `querySelectorAll` or `dataset`.
- Fix:
  - Lift `resumeAllWidget`, `agentWatchJob` and `renderManageTerminals` with the suites' `_extract_function`.
  - Stub `h` (with `addEventListener`, `checked`, `disabled`, `hidden`), `crBtn`, `crCall` (a scripted queue of
    responses that records request bodies), `crReadOnly`, `toast`, `setInterval`/`clearInterval` (manual tick),
    `buildChrome`, `emptyState`, `errorState`, `icon`, `timeAgo`, `cwdTail` and `sessionTitleFor`, and declare the
    module vars.
  - In the widget, keep the checkboxes in a closure array of `{cb, sid}` that `paint()` rebuilds. Do not query the
    DOM.

### NIT

- **N1.** README and §7.1 say "`--fork-session` copies are not remembered". That is false: `upgrade_candidates`
  relabels through the pid file (`term_vt.py:4121-4122`, `sid = e["id"] if host == "tui"`), so a forked pane with a
  pid file is recorded under its new id. Fix: say only "plain shells are not remembered".
- **N2.** The `AGENT_RA_NOTE` parenthesis was left for the implementer to word. The real label is "Idle terminal
  TTL" (`ext_cr_dialogs.js`, Config → Terminal `serverRow('Idle terminal TTL', 'TERM_IDLE_TTL_MIN'`). Fix: fix the
  text as "(Config → Terminal → Idle terminal TTL)".
- **N3.** With a merged history, a session open in another tracker's pane is listed as a `tui` host. `RA_TUI` says
  "outside the tracker", which is wrong for that case. Fix: "running in another terminal (pid %d), outside this
  tracker's terminals; …".
- **N4.** `update.py:271` refuses an Update during any agent job with "an agent upgrade is running". During a
  resume-all job that is slightly wrong. Direction: no change here, because the text belongs to AU, which is under
  separate review. Mention it in the commit.
- **N5.** Duplicate ids in `confirm` produce duplicate failed items. Fix: `confirm = list(dict.fromkeys(confirm))`
  after validation. Test: T11, where `["A", "A"]` gives one item.
- **N6.** `REMEMBER_FULL_EVERY` forced `upgrade_candidates()` (`ps` forks) every 60 s even with no pane open. Fix:
  return early when `_pane_fingerprint() == ()`; this is in T4.
- **N7.** `_agent_ra_age`, `AGENT_RA_STOPPED` and `saved_at` exist only for the per-port design. Cut them with F1.
- **N8.** `tests/test_term_vt.py:3420-3427` calls `importlib.reload(config)`, which resets `LAST_TERMS_FILE` to the
  real path for the rest of that process. The real guard is the write gate `_REMEMBER_ON`, which is off unless
  `start_remember()` ran; the path redirect is only a second layer. Fix: state this in §3.7 so nobody relies on the
  path alone.

## Reuse claims, checked against the code now

| Claim | Status |
|---|---|
| `_agent_item`/`_AGENT_ITEM_KEYS` (`agent_cli.py:146`, `:97-98`), `_agent_set` `:154`, `_agent_push` `:159`, `_agent_snapshot` `:164`, `_agent_tv` `:178`, `agent_job_running` `:182`, `_agent_thread` `:376-383`, `_agent_fail` `:386` | hold; line numbers re-grounded in the plan |
| `_agent_launch` = the job-slot tail of `agent_start` (`:355-373`), with `global _AGENT_JOB, _AGENT_SEQ` moved into it | holds. `tests/test_agent_cli_jobs.py:380-406` (409, RuntimeError → 500, 400s) and `:308` (the "agent upgrade:" print, kept by `_agent_fail`'s default label) stay green |
| `_agent_resume` (`:592-606`) with `busy=False` sends no `prompt` | holds. It now **returns** the item and has a `reused` branch (F4) |
| `call_route` (`term_vt.py:3588`) through `_Internal` (Host 127.0.0.1) | holds |
| `upgrade_candidates` (`:4097`), with the pid-file relabel and dedupe | holds; the plan no longer changes it (F5) |
| `open_pty` 429s at the folder spawn (`~:3162`) and overflow (`~:3315`), the claim (`~:3231`), the daemon swap (`~:3307`) | hold; `_ra_need` mirrors them |
| `store._update_forks` (`store.py:348-379`) generalises to `_update_json(path, mutate)`; `_lock_fh` `:337`; `_save_json` atomic `:18` | holds; `tests/test_fork_follow.py` (which calls `_update_forks` at `:354`, `:407`) stays green |
| server `/api/agents/run` (`server.py:694-707`), `_local_caller` (`:224-241`), global `_readonly()` deny before the body (`:639`) | hold |
| `server.run` (`:1040-1069`), `start_worker()` at `:1052` | hold. `tests/test_update_routes.py` `RunWiring` patches `threading.Thread` globally and joins every thread it sees (5 s), so the `tests/__init__.py` stub of `start_remember` is required, not optional |
| `restart_in_place` (`update.py:347-373`), `_cloexec_all()` at `:365` | hold. Existing `tests/test_update_restart.py` tests are unaffected because `_REMEMBER_ON` is False under the suite |
| Manage dialog `update(p)` replaces `payload` (`ext_cr_dialogs.js:2468-2475`). `_openManageDialog` (`ext_cr_term.js:727-766`) and `_openCapDialog` (`:677-724`) share the dialog name | hold. Every `_openManageDialog` payload carries `onRefresh`, so the button survives repaints. A cap-dialog update hides it (intended) |
| `timeAgo`/`cwdTail` (`:2292`/`:2302`) in the same IIFE (`:24-3246`) as `agentsBlock` | holds |

Test modules to re-run after each refactor:
- R0 (`_update_json`, `_agent_launch`, `_agent_resume` `reused` parameter, `agentWatchJob`):
  - `test_fork_follow`
  - `test_agent_cli_jobs`, `test_agent_cli_parse`, `test_agent_cli_outside`
  - `test_agent_routes`, `test_agents_ui`
- R1 (record and hooks):
  - `test_update_restart`, `test_update_routes`, `test_pending_routes`
  - `test_term_vt_upgrade`, `test_claude_running`
  - `test_integration` (it lists `restart_in_place` at `:1762`)
- R5 (UI): `test_cr_manage_terminals_parity`, `test_cr_manage_terminals_poll`
- R6: `test_page_bundle`, `test_selfcheck`.

## Brief checklist (items 3 and 4)

- Atomic read-modify-write from two trackers: holds under merged history. Each tick takes the flock, reads, merges
  and writes atomically. In-process ticks are serialised by `_REMEMBER_LOCK`, and flock locks per open file
  description, so two threads exclude each other too.
- "Never replace non-empty with empty": holds. `_merge_terms` returns False on empty live, a write always adds at
  least one live entry, and pruning happens only inside such a write.
- The 32 bound is applied at merge and at read.
- Staleness: transcript-gone entries are dropped at read, and each row shows its age. There is deliberately **no age
  bound**: after a long break the last sessions are still the ones the user wants.
- Tests never write the real file: covered by the gate plus the path redirect (N8).
- No thread leak: `start_remember` is stubbed suite-wide, and T5 starts and joins the real one.
- Picker:
  - The server re-plans on confirm, picks only ids that are in its own record and openable, so a forged id never
    opens.
  - It re-checks `_ra_need` against the current free slots and answers 409 with a fresh list if the cap changed.
  - Two presses: the widget's `busy` flag is set before the POST, and the shared job lock turns a second tab's
    press into a 409.
  - During an agent upgrade: preview and confirm answer 409 "an agent job is already running".
  - During a tracker self-update: `_APPLY` gives a 409, and `update_apply` refuses while the job lock is held
    (`update.py:267-271`). Both sides acquire before checking, so they exclude each other.
  - The only body sent is `mode: "resume"`; there is no `prompt` key and `mode: "new"` never appears.

## Decisions

| # | Decision / verdict | Honoured in the plan now? | Section |
|---|---|---|---|
| R-D1 | "Also closed this run" | yes. Closing a pane never removes an entry; history is merged | §2 |
| R-D2 | Manage terminals and Config → Agents next to Upgrade | yes | §4 |
| R-D3 | "Let me pick": checkboxes, server re-checks the cap, 409 with a fresh list | yes | §3.3 step 4, §3.4 |
| R-D4 | No prompt | yes (`busy=False`, T12) | §3.4 |
| B1 | Never replace non-empty with empty; no shutdown write | yes (`_merge_terms` returns False on empty live) | §2 |
| B2 | Late-bound path, tests never write it, no thread leak | yes (plus the N8 note) | §3.7 |
| S1 | Per-port keys | **reversed** to the merged history (F1) | §2 |
| S2 | Bundle-safe import | yes (`sys.modules.get("aitracker.term_vt")`) | §3.5 |
| S3 | Record from `upgrade_candidates()` | yes, unmodified (F5) | §3.2 |
| S4 | Item schema | yes (T12 key-set check) | §9 |
| S5 | Share the job slot | yes (`_agent_launch`) | §3.4 |
| S6 | Not in the cap dialog | yes (`onRefresh` gate) | §4 |
| Main thread | Already-open sessions on one line; order by last seen; 32 bound | yes | §12 |

Needs the user: nothing new. One behaviour follows from the merged history and is worth knowing: a session open in
another tracker's pane appears as a "can't" row with its pid.

## Not examined

- Whether `open_pty`'s deferred folder start and the `--fork-session` backstop behave correctly when several resumes
  arrive back to back. The opens are sequential and AU uses the same path.
- `term_gate.guard` with `TRACKER_AUTH` set for `_Internal` callers. Trusted from AU's tests.
- The real cost of `resume_all_plan()` inside a request handler with 32 entries: about 32 `glob`, roster and
  transcript head/tail reads, plus `running_sessions`' `ps` forks. It was not measured.
- The classic UI, the Windows `msvcrt` path, and bundle runtime behaviour beyond "term_vt absent → feature absent".
