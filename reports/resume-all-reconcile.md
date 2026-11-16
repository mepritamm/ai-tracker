# Resume all prior terminals — reconciliation (main thread)

Side by side: plan v1 = `resume-all-plan.md` · review + clean plan = `resume-all-review.md` · this file = user
decisions and verdicts.

## Contract (verbatim, 2026-11-16)

"add a resume all prior terminals button alongside the upgrade version button, Put this button in the manage terminals
view itself, where it opens the last spawned sessions, list the sessions which will be opened and open all of them in
the background"

## User decisions (2026-11-16, given while the review of plan v1 was running — they supersede plan v1)

| # | Question | Answer | Effect on plan v1 |
|---|---|---|---|
| R-D1 | Which set is "prior terminals" | "Also closed this run" | The record must also keep terminals opened and then closed (or idle-reaped) during the CURRENT run, not only the set open at the last stop. Plan v1 kept only live panes + `prior`. |
| R-D2 | Placement | "Manage terminals and Config" | Button in the Control Room's Manage terminals dialog AND next to Upgrade in Config → Agents. Not the classic UI. |
| R-D3 | List longer than the free terminal slots | "Let me pick" | The dialog shows checkboxes; the user chooses which to open when not all fit. Plan v1 opened the newest that fit. The server must still enforce the cap on what is confirmed. |
| R-D4 | Prompt after reopening | "No prompt" | As planned. |

## Verdicts on the review

Judged on the review's summary and cited evidence; the main thread did not re-open the code.

| # | Finding | Verdict | Decision |
|---|---|---|---|
| B1 | Last write on SIGTERM can record an empty set; the run's list is lost | Confirmed, and largely dissolved by R-D1 | With R-D1 the record is a history of every Claude session opened in a tracker pane this run (closing a pane or idle-reap never removes it), so a shutdown with no live panes cannot erase it. Keep: never replace a non-empty record with an empty one. |
| B2 | Tests would start the recorder, write the real `aitracker/last_terms.json`, leak a thread | Confirmed | Accept: the path is late-bound via `config.NAME` (CLAUDE.md seam rule) and the tests that call `server.run()` point it at a temp dir; no thread outlives `run()`. |
| S1 | Two trackers from one checkout overwrite each other's record | Confirmed | Main-thread default (not asked): key the record by port inside the one file, so each tracker keeps and offers its own. |
| S2 | `__package__ + ".term_vt"` import breaks `make bundle` | Confirmed | Accept: use the import style agent_cli already uses. |
| S3 | Recorder re-implements the pane scan and loses the stale-label correction | Confirmed | Accept: build the record from `upgrade_candidates()`. |
| S4 | Job items don't match the agent-test item schema | Confirmed | Accept. |
| S5 | `agent_start` locking/job code copied, not shared | Confirmed | Accept: share the one job slot and its helpers. |
| S6 | Literal "alongside the upgrade version button" never offered; button also shows in the "free a slot" dialog | Resolved by R-D2; the second half confirmed | Button in Manage terminals and next to Upgrade in Config → Agents (R-D2). Not in the "free a slot" variant of the dialog. |
| N1-N11 | Nits | Confirmed | Accept unless they conflict with R-D1..R-D4. |

New design consequences of the user's decisions that the review did not see:
- R-D1 changes the record from "set open at last stop" to an ordered history (most recent first) of sessions opened
  this run, plus the previous run's history. It needs a bound (drop entries beyond a fixed count, and drop sessions whose
  transcript is gone).
- R-D3 needs checkboxes in the dialog, preselected newest-first up to the free slots; the server re-checks the cap on
  the confirmed list and refuses (409 with the fresh list) if it no longer fits.

Next: the plan is revised to a final plan by the opus plan agent with all of the above, then re-reviewed by opus.

## Main-thread verdict on the final plan (`resume-all-plan-final.md`), before its re-review

- **Per-port keys reversed (my S1 default was wrong).** CLAUDE.md: `make serve` starts "on PORT (default 8790), or the
  next free port if busy". A tracker that comes back on another port would then offer nothing — losing exactly the list
  the button exists for. Replace with ONE merged history shared by every tracker from this checkout: entries keyed by
  session id (dedupe, newest `last_seen` wins), written through the planned `store._update_json` read-modify-write so
  two trackers never drop each other's entries. A session open in another tracker's pane is already excluded by the
  "running elsewhere" check (pid file). The `ports` bound goes away; the 32-session bound stays.
- Other plan-final choices accepted as defaults: already-open sessions shown as one summary line; order by last seen
  running; 32-session bound.

## Re-review of the final plan (`resume-all-review-final.md`; fixes folded into `resume-all-plan-final.md` in place)

| # | Finding | Verdict | Note |
|---|---|---|---|
| F1 | Plan still kept one record per port | Confirmed (matches the main-thread reversal) | One shared history keyed by session id via `store._update_json`; a tick with no live panes never writes. |
| F2 | `raParts()` calls `crReadOnly()` before `onRefresh`, turning two existing Manage-terminals tests red | Confirmed | Order swapped. |
| F3 | `agentWatchJob` changed under the plan (`_agentWatchId`) | Confirmed | Re-grounded. |
| F4 | `_agent_resume`'s reused text says "press Upgrade again" | Confirmed | Text is a parameter; resume-all passes its own. |
| F5 | `started`/`opened` added to `upgrade_candidates` but never read | Confirmed — overbuild | Cut; the agent-upgrade function stays untouched. |
| F6 | UI test T15 too vague | Confirmed | Harness spelled out. |
| N1-N8 | Nits | Accepted | |

Status: plan ready for the user's sign-off. Implementation waits for the agent-upgrade fix verification, since it
builds on `_agent_resume` / `_agent_launch`.
