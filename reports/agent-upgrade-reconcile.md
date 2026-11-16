# Agent upgrade — reconciliation (main thread)

Side by side: plan v1 = `agent-upgrade.md` · review + clean plan v2 = `agent-upgrade-review.md` · this file = verdicts
and the user decisions taken after v1. Verdicts are judged on the review's cited `file:line` evidence; the main thread
did not re-open the code. Items marked LIVE wait on the live check (V1-V4).

## User decisions taken after plan v1 (2026-11-16)

| # | Question | Answer | Effect on the plan |
|---|---|---|---|
| D1 | Base branch | "Wait for pending-work-worker" | No copied pieces. Build on main AFTER that branch lands. F3 moot; F10 simplifies. |
| D2 | Exceptions to "force all" | Selected "Already on new version", "Unknown session id" and "None — stop everything" | Read as: skip sessions already on the new version; unknown-id panes are an accepted exception; everything else in a tracker pane is stopped, INCLUDING daemon-hosted panes. Needs confirming at sign-off. |
| D3 | Live check (`claude update`, scratch session) | "Yes, on a scratch session" | Running. |
| D4 | Flaws on pending-work-worker | "Report only" | Moot: review F3 shows both are already fixed at that branch's head `fe8f580`. Nothing to report. |

## Verdict per finding

| # | Finding | Verdict | Decision |
|---|---|---|---|
| F1 | Daemon-hosted sessions never upgraded; `claude --resume` only reattaches to the old worker | Confirmed | Accept the correct command (`claude stop <job>` then `claude --resume <id>`) for background sessions with no tracker pane (clause 4, show only). Per D2, a tracker pane showing a daemon client is stopped and resumed by the tracker — gated on V6 proving `claude stop` + resume lands on the new version; if V6 fails, fall back to show-only. |
| F2 | Force = SIGKILL leaves a busy session's tool processes orphaned; gentle stop exists | Confirmed in design; orphan claim unmeasured (LIVE) | Accept `stop_for_upgrade` (SIGTERM, wait, SIGKILL fallback, reap work children). |
| F3 | Copies grounded on stale sibling commit | Confirmed, now moot (D1) | Drop all copies and corrections 0.2/0.3. Use the landed helpers directly. |
| F4 | Outside list misses idle-but-running sessions; desktop sessions mislabelled | Confirmed (field names LIVE, V3) | Accept `Provider.running()`; cut the `cli_version` list field. |
| F5 | `auggie upgrade` needs `--skip-confirmation` | Confirmed | Accept. |
| F6 | Session stopped then unresumable for knowable reasons | Confirmed | Accept preflight; never resume an unconfirmed stop. |
| F7 | Unknown-id panes resolvable through the pid file | Confirmed | Accept — narrows an exception the user already accepted. |
| F8 | Resume notification lost if the dialog is closed | Confirmed; fix overengineered | Keep the module-level poller + toast + server log line. Cut the page-load catch-up and `sessionStorage` bookkeeping. |
| F9 | Confirm keyed on tty alone | Confirmed | Accept (tty, session) pairs. |
| F10 | Cross-lock with the tracker's own Update depends on landing order | Overstated after D1 | `update.py` will exist: both sides check each other directly. No `sys.modules` probe, no merge TODO. |
| F11 | Verify uses a weak oracle, unbounded wait | Confirmed | Accept shared deadline, `running()` version, PATH-mismatch message. |
| N1-N9 | Wording, `_run` shape, cwd=HOME, empty-list text, selfcheck | Confirmed | Accept all; N4 stays `CLAUDE.md`. |
| Cuts | `cli_version` field, `util.run_argv`, `_same_origin`, per-session transcript polling | Confirmed | Cut. |

## Missed by both

- **M1 — auto-continue fires on idle sessions too.** Clause 6 sends "continue, re-read CLAUDE.md" to every resumed
  session. A session that was idle (finished, waiting for the user) when stopped would start an unrequested turn and
  spend tokens. Proposed: send the prompt only to sessions that were busy when stopped; idle ones are resumed and left
  waiting. User decision.
- **M2 — dependency on landing pending-work-worker.** D1 makes this feature wait on a branch whose own durable file has
  every clause "not discharged". Implementation cannot start until it is on main; the plan can be finished now.
- **M3 — a session waiting on a permission prompt** when stopped is neither "busy" (no work children) nor finished.
  It must count as busy for M1.

## Not examined by anyone

`make check` on this branch; `auggie upgrade` live; `scripts/bundle.py` import stripping; the classic UI; the
auth-cookie path in `do_POST`.

## Later user decisions (2026-11-16, after the review) — these SUPERSEDE D1/D2 above where they differ

| # | Question | Answer | Effect |
|---|---|---|---|
| D5 | Tracker panes showing a daemon-hosted background session | "Tracker stops and resumes them" | The tracker runs `claude stop <job>` then resumes in a tracker pane. Gated on V6 passing on a scratch background session; if V6 fails, show-only with the two commands. Background sessions with NO tracker pane stay show-only (clause 4). |
| D6 | Who gets "continue, re-read CLAUDE.md" | "Only busy ones" | Prompt only for sessions busy at stop (work children, or waiting on a permission prompt — M3). Idle ones are resumed and left waiting. The notification says which got the prompt. |
| D7 | Base (replaces D1) | "Build on top of it now" | Branch `agent-upgrade` is based on `worktree-pending-work-worker`. No copies; use its `_local_caller`, `origin_matches_host`, `_with_prompt`, `update._run`/`_APPLY` and UI helpers directly. Lands after that branch. F3 moot, F10 = direct mutual check. |

| D8 | CLI already latest, but sessions run an older version | "Restart the old sessions" | Upgrade always ends with stop-and-resume of every tracker session whose running version differs from the installed one, whether or not anything was installed. Same warning first. (Given to the user AFTER plan v3 was briefed — fold in at re-review.) |
| D9 | Scratch tests for V5 (gentle stop, busy session) and V6 (`claude stop` + resume) | "Yes, go ahead" | Approved: accept the trust prompt for the test's own empty scratch folder only; one scratch session, one scratch background job; torn down after. |
| D10 | Auggie | "Include, test once for real" | Auggie gets Upgrade (`auggie upgrade --skip-confirmation`); run once for real to verify no-terminal behaviour. |

## Live check results (sonnet agent, scratch session, torn down)

| Check | Result | Evidence |
|---|---|---|
| V1 `claude update`, no terminal | PASS (no-op) | exit 0 in 3.0 s, no prompt; "Claude Code is up to date (2.1.325)" |
| `claude doctor`, no terminal | PASS | exit 0 in 1.4 s, 673 bytes of output |
| V2 transcript `version` field | PASS | top-level `version` on user/assistant/system lines |
| V2 resume lands on the NEW binary | UNPROVEN | no newer version existed; both runs 2.1.325 |
| V3 `~/.claude/sessions/<pid>.json` | PASS | fields include `pid, procStart, sessionId, version, kind, entrypoint, jobId, cwd, status`. Note: no file is written while a session sits at the trust prompt. |
| V4/V5 SIGTERM on a busy interactive session | NOT RUN | scratch dir hit the trust-folder prompt; SIGTERM at that prompt exited in 0.82 s, code 143 |
| V6 `claude stop <job>` + resume | NOT RUN | |

| Auggie `auggie upgrade --skip-confirmation`, no terminal (D10) | PASS | exit 0 in 28.4 s, no prompt; 0.36.0 → 0.37.1 (`auggie --version` 3.6 s, format `0.37.1 (commit …)`). npm global install under the Homebrew node prefix. Only flags: `--skip-confirmation`, `--help` (alias `update`). 4 auggie processes were running and untouched. "Already up to date" exit code NOT measured — compare `--version` before/after instead. |

| V6 `claude stop` + resume on a scratch background job (D9) | PASS (resume via `-p`, not in a pane) | `claude --bg "<prompt>"` starts a job; pid file `kind=bg, jobId=<short>, version, status=idle`. `claude stop <short id>` works; the FULL session id is REJECTED ("No job matching"). Stop ~2 s, worker exits within 4 s, its pid file is removed, a busy job's `sleep 300` child died with it. `claude -p --resume <session id> "…"` then succeeded (~14 s), new lines on the installed version. A SessionEnd hook warning ("Hook cancelled") appeared once. |
| V5 SIGTERM on a busy INTERACTIVE session (D9) | NOT RUN | On this machine a plain `claude` under a pty opens the agent-view TUI, not a chat session; a typed prompt dispatches a background job. No interactive pid file or transcript appeared. SIGTERM to the client group: exit 143 in 1.45 s. The trust prompt defaults to "No, exit". |
| V7 is "waiting on a permission prompt" detectable | NOT RUN | Only `status` values seen: `idle`, `shell` (while a background job's shell command ran). |
| Side effect | — | One trust entry for the removed scratch path remains in `~/.claude.json` (not edited). |

Consequences: (1) plan must use the SHORT job id for `claude stop`; (2) `status` has at least a `shell` value the
plan's `idle/busy/waiting` list does not name — "busy" must be "anything other than idle", not an allow-list;
(3) V5/V7 are still unmeasured and must stay runtime-safe: gentle stop with hard-kill fallback, and an undetectable
permission wait is treated per the plan's stated fallback; (4) the plan must say how the tracker's own launches avoid
the agent-view TUI, or confirm they already do.

V2-resume, V5 and V6 remain verify-before-relying steps in the plan (S0). V2-resume can only be proven on a real
version bump; until then the feature must report "resumed on vX, expected vY" from `running()` rather than assume.

## Second review (plan v3 → `agent-upgrade-review-v3.md`, final plan `agent-upgrade-plan-final.md`)

Verdicts judged on the review's cited evidence and the live results; the main thread did not re-open the code.

| # | Finding | Verdict | Decision |
|---|---|---|---|
| B1 | S0 verify steps start a bare `claude`, which opens the agent view here | Confirmed (matches the live V5 result) | Accept: scratch sessions are created with `claude -p`, then opened through the product's resume path; `mode:"new"` never used by this feature. |
| B2 | Pane label goes stale after `/clear` or `/resume`; upgrade would stop the live session and prompt the old one | Confirmed | Accept: a verified pid file's `sessionId` beats the label; warning row shows the relabel. |
| S1 | Busy check was an allow-list; `shell` fell through | Confirmed | Accept: busy = anything other than `idle`. |
| S2 | D8 only implicit in the warning | Confirmed | Accept. |
| S3 | D5 is the main path here; restarted background session becomes a tracker-terminal session | Confirmed | Accept the wording; side effect goes to the user (decision). |
| S4 | Job dict mutated while the poll serializes it | Confirmed | Accept. |
| S5 | Orphan sweep can signal a recycled pid | Confirmed, small | Accept. |
| S6 | Daemon stop "confirmed" by a read that fails open | Confirmed | Accept. |
| S7 | Confirmed stop can still end unresumed (cap, other folder, duplicate panes) | Confirmed | Accept. |
| S8 | S0/S9 need more scratch sessions than D9 approved; old-binary run could auto-update | Confirmed | Needs a fresh user OK; `DISABLE_AUTOUPDATER=1` on the old-binary run. |
| N1-N11 | Nits and two cuts | Confirmed | Accept. |

Size check (main thread): the final plan is 1128 lines for one new ~350-line module plus edits in six files, nine
commits. That is large for "two buttons", but each piece traces to a contract clause or a measured failure path;
nothing further was found to cut.

## User decisions on the final plan's §15 (2026-11-16)

| # | Question | Answer |
|---|---|---|
| D11 | Unanswered question = busy? | "Yes, it gets the prompt" (as planned) |
| D12 | `claude update` fails, outdated sessions exist | "Stop nothing" (as planned) |
| D13 | D5 side effect (background → terminal session) | "Keep it, warn me" (as planned) |
| D14 | S9 live-proof scope (six scratch sessions/folders) | "Yes, approved" |
| — | Toast surviving a page reload; unknown-version session when nothing installed | Not asked: plan defaults stand (no catch-up; left running). User may overrule at sign-off. |

Status: final plan = `agent-upgrade-plan-final.md`. Awaiting the user's go-ahead to implement (no code before agreement).

## Implementation review (reviews A = backend, B = terminal/UI/tests), main-thread reconciliation (2026-11-16)

Gate before review: `make check` PASS (`selfcheck ok`), `node --check` clean on all 9 web files. An over-wide `CLAUDE_*`
env scrub added in S5 was reverted (the product already strips the one causal var, `CLAUDE_CODE_CHILD_SESSION`; the
wide scrub would have dropped `CLAUDE_CONFIG_DIR` etc. and overturned a tested decision) — confirmed clean by both.

User decision: **D15 — same session open in two tracker terminals: "Stop all copies, resume once."**
Main-thread decision (not asked; the warning text already promises it): **D16 — only sessions running an OLDER version
than the installed one are restarted; a newer one is listed "newer than the installed version; not restarted".**

| # | Finding | Verdict | Fix (owner) |
|---|---|---|---|
| B-SF1 | Agent-view panes (no session) share target `""` and get a false "restarted there" | Confirmed | Never dedupe on an empty target; such rows are not stoppable, reason "no session in this terminal (Claude's agent view)". (Y) |
| B-SF2 | Duplicate pane makes the resume a silent reattach reported as "Resumed", then blamed on PATH | Confirmed; design per D15 | Candidates carry the duplicate group; every copy is stopped, the session is resumed once in the primary terminal; `reused: True` from `open_pty` is a failure, never "Resumed". (X + Y, interface in fix brief) |
| A1 = B-SF3 | Every `cannot_stop` row reported "not shown in the warning"; tests confirm rows the UI never sends | Confirmed (both) | Report them as "Not restarted: <reason>"; tests send only what the UI sends. (X) |
| A5 = B-SF4 | Prompt never seen in the transcript still announced as sent | Confirmed (both) | New server string for "resumed; the prompt was not confirmed in the transcript". (X) |
| B-SF5 = A-N2 | Selfcheck assertion in a new TestCase under a false comment | Confirmed (both) | Move into `_run()`, delete the TestCase and comment. (Y) |
| B-SF6 | UI tests that stay green if the feature breaks; no UI↔server field check | Confirmed | Fix the dispatch assertion; add one field-fit test. (Y) |
| A2 | Daemon session in an overflow pane: client exits after `claude stop`, pane reaped, job records "failed" though stopped | Confirmed | A pane that closed after a confirmed `claude stop` counts as stopped; resume in a new terminal. (X) |
| A3 | Newer-than-installed session restarted on every press | Confirmed | D16. (X) |
| A4 | Test (k) vacuous (`AGENT_VERIFY_WAIT` patched to 0) | Confirmed | Make it bite. (X) |
| A6 | `needs_slot` counts a busy folder shell as free; stop then 429 | Confirmed | Busy shell is not a landing spot. (Y) |
| NITs | A 14, B 9 | Accepted unless they conflict with D15/D16 | Per owner file. |
| — | Plan §13 note on `CLAUDE_*` env never landed | No change | The product already strips the causal variable; the note described the scratch harness, not the product. |

## Fix verification (`agent-upgrade-fix-verify.md`), main-thread reconciliation

Result: 19 FIXED, 4 PARTLY, 2 REGRESSED, plus new findings. Gate after the fixes: RED on one test,
`tests.test_term_vt.TestIdleSessionLive.test_U9_hold_does_not_touch_idle_clock` (fails in isolation too) — diagnosis
running separately; all other 142 modules green.

| # | Finding | Verdict | Fix |
|---|---|---|---|
| NF1 (REGRESSED B-SF2) | `reused` also means "typed into an existing folder shell", so every normal folder-pane resume is reported failed | Confirmed (probe with the real `open_pty`) | As designed: new `attached` key on the two nothing-typed replies only; `_agent_resume` reads it; `reused` unchanged. |
| NF2 | Daemon session in two panes: worker stopped, second copy "job gone", nothing resumed | Confirmed (probe) | As designed: stop the worker once, clear each thin client, resume once. |
| NF3 | Group keeps stopping after a failure; a confirmed stop reported unconfirmed (test pins the wrong text) | Confirmed | As designed: primary first, halt on first failure, truthful per-copy text; fix the test. |
| NF4 | Warning promises stops a blocked group then refuses | Confirmed | As designed: blocked group's copies move to `cannot_stop` at plan time. |
| NF5 | "comes back once, in terminal <primary>" can name the wrong terminal | Confirmed; designed fix overbuilt | Simpler: the warning never names a terminal ("…comes back once, in a tracker terminal"); the after-the-fact detail already names the real landing tty. No change to primary selection. |
| README known-gap sentence | REGRESSED: product already strips the causal variable | Confirmed | Delete the sentence. |
| A1 (PARTLY) | Right reason, but labelled "Failed:" | Confirmed | Label "Not restarted:". |
| A-N9 (PARTLY) | Rule 6 says "other than the installed version" | Confirmed | Say "older than"; mention D15 copies. |
| B-N2 (PARTLY) | Job view ignores `out_of_date_text` | Confirmed | Render it there too. |
| NF6 | NITs | Accepted unless they widen scope | |

## Handover (usage limit hit, 2026-11-16)

State of worktree `agent-upgrade` (based on pending-work-worker @ fe8f580): ALL work uncommitted. Push is HELD by the
user ("hold the push for now"). Steps S0-S8 built; gate was green before the review fixes.

In flight when paused (their work so far is saved; resume each with SendMessage, do not respawn):
1. Fixer Y (terminal/UI, `fix-brief.md`) — STOPPED by the rate limit mid-run; last note "Now test_agents_ui and
   selfcheck". term_vt.py / ext_cr_dialogs.js edits may be partial: re-run `tests.test_term_vt_upgrade`,
   `tests.test_agents_ui`, `tests.test_selfcheck` and `node --check aitracker/web/ext_cr_dialogs.js` first.
2. Fixer X (agent_cli side) — was still running; check its report.
3. Resume-all plan re-review (opus) — was still running; output `reports/resume-all-review-final.md`, and it edits
   `reports/resume-all-plan-final.md` in place.

Then, in order: (a) full gate `unset TRACKER_AUTH; make check` (gate-runner haiku); (b) re-verify the review fixes
(opus, assume the fixers' reports are false); (c) S9 live proof per plan-final §10 (user approved D14); (d) commit
locally in the worktree (commit hook runs the full gate — >6 min timeout; message via `-F` file); (e) do NOT push.
Resume-all: after its re-review lands, reconcile it and take the final plan to the user for sign-off — no code before.

## Next

Plan v3 (same opus plan agent) = clean plan v2 + D1/D2 + the verdicts above + live-check results, then re-review.
