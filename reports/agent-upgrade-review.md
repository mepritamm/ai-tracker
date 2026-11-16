# Adversarial review: `reports/agent-upgrade.md` (plan v1)

Reviewer: separate `opus` agent, 2026-11-16. I assumed the plan was wrong until I had checked it myself.
Worktree `agent-upgrade` @ `76bd154`. Sibling branch read at its worktree, which is now at **`fe8f580`**.
The plan grounded itself on `2bca388`, one commit older. I changed no product code and made no commits.

## Verdict

**The plan is not ready to implement. It has 3 BLOCKERs, 8 SHOULD-FIXes and 9 NITs.**

The core design holds up against the code:
- Update first and stop second is right.
- The shared seam is right.
- Server-written text is right.
- Single-flight is right.
- Most of the file:line grounding is accurate.

Three things are wrong:
1. **Daemon-hosted sessions.** These are the sessions that are actually out of date on this machine today, and the plan
   hands the user a command that does not upgrade them.
2. **Stopping a busy session.** The plan SIGKILLs it and leaves its running tool processes orphaned. A gentler stop
   already exists in the repo.
3. **Stale corrections.** Two of the plan's "corrections" about the sibling branch are no longer true at its head. That
   makes the "copy verbatim" approach copy text that has since changed.

## Grounding check (claims verified, field names only, no transcript content)

| Plan claim | Result |
|---|---|
| `update.py`, `is_loopback_host`, `_with_prompt`, `crCall/crBtn/crReadOnly` are absent here | **True.** `ls aitracker/` has no `update.py`. A grep finds none of those names. `_local_caller` here (`server.py:219-228`) checks only the proxy headers and the peer. |
| 0.2 `_with_prompt` is called after a `return`, so it is dead code | **True at `2bca388`** (`term_vt.py:3126`, indented under the `except … return`). **False at the branch head `fe8f580`**: `term_vt.py:3128` is now at branch level and live. The helper also gained a control-character filter (`fe8f580 term_vt.py:2951-2959`). |
| 0.3 the `/api/update/*` routes have no Origin check | **True at `2bca388`** (no `Origin` in `server.py`). **False at `fe8f580`**: `util.origin_matches_host` (`util.py:715-720`) is called inside `_local_caller` (`server.py:230-231`) and inside `_same_origin_loopback` (`server.py:357-360`). |
| 0.4 transcripts carry a top-level `version` | **True.** In the 3 newest files, `version` is present on `user`, `assistant`, `system`, `attachment`, `api-request` and `api-request-shape` lines. It is absent on `last-prompt`, `custom-title`, `ai-title`, `queue-operation`, `session-owner`, `mode`, `file-history-*` and `api-request-blob` lines. Values seen: 2.1.325, 2.1.323 and 2.1.322. |
| 0.5 Auggie records no version | Not re-checked. Accepted. |
| 0.7 a running session keeps its binary | **True, and more is recorded than the plan found.** `~/.claude/sessions/<pid>.json` (`config.LIVE_SESSIONS_DIR`, already read by `claude.py:622-664`) carries `pid, procStart, sessionId, kind, entrypoint, jobId, version` for every live Claude process. Today 8 are live: 4 are `interactive` with `entrypoint: claude-desktop` on 2.1.321, and 4 are `bg` (2 on 2.1.323 and 2 on 2.1.325). The daemon roster `~/.claude/daemon/roster.json` workers also carry `cliVersion`. The installed version is 2.1.325. |
| 0.8 / registry `resumable` | `registry.py:31`, not 30. Trivial. |
| `_tail_scan` (89), `entry=` (168), return (234), `_session_meta` (247), meta `version` (1830), `app.js:1924` | All correct. |
| `open_pty` 2951, "resume is Claude-only" 3073, `resume_argv` 3107, `_inject_argv` 1917, backstop 2449, `close_pty` 3757, `_claude_busy` 3951, `_pty_session_ids` 3970, `_foreground_is_claude` 4018, `_background_target` 3365, `term_gate.guard` 57 | All correct. |
| `ext_cr_dialogs.js` `renderConfig` 1132, `sections` 1143, `toast` 273; `bundle.py` ORDER 11-15; README 7/84/231; selfcheck 1469 | All correct. |
| Pending branch "4 commits @ 2bca388" | It is **5 commits @ `fe8f580`** ("implementation-review fixes, security hardening"). |
| `auggie upgrade` takes no flags (descriptor `["upgrade"]`) | **Wrong.** `auggie upgrade --help` lists `--skip-confirmation  Skip confirmation prompt` (F5). |
| Killing a daemon-hosted pane "does nothing", so the session cannot be restarted | **Half true.** Killing the *client* does nothing (`term_vt.py:3341-3345`). But the CLI has `claude stop <id>`, whose help says "Its conversation is kept … `claude --resume` works once it is stopped". The CLI's own refusal text also says "`claude stop <short-id>` first to resume it here" (`term_gate.py:121-123`). |

## Contract, clause by clause

| # | Clause | Plan v1 | Judgement |
|---|---|---|---|
| 1 | Doctor or upgrade; name the sessions that will be stopped, "you might have to continue again with a prompt" | `UPGRADE_MESSAGE` contains the user's sentence and the `stop` list | **Met in text.** No wording is defined for an empty stop list or for Auggie (N5). |
| 2 | Every agent the tracker manages, as far as possible | Claude and Auggie; the Augment extensions are excluded | **Met, but the Auggie argv is wrong (F5).** The Claude-desktop sessions are not handled (F4). |
| 3 | Force all now, with a warning | Tracker panes are stopped, busy ones included. Unknown-id and daemon-hosted panes are excluded | **Partly met.** Unknown-id panes can mostly be resolved (F7). Busy sessions are SIGKILLed and their children orphaned (F2). The daemon exclusion is defensible only as clause 4, and then it needs the right command (F1). |
| 4 | Outside sessions: show only, out-of-date, with the command to run | Rows with mtime inside `LIVE_WINDOW`, version from the transcript tail, `claude --resume <id>` | **Not met.** The command is wrong for daemon-hosted and desktop sessions (F1, F4). Sessions that are idle but still open are missed (F4). |
| 5 | Always latest, `claude update` | Yes | Met. |
| 6 | Resume with "continue, re-read claude.md" and tell the user | Resume prompt, a server-written summary and a toast | **Partly met.** The toast only fires while the Config dialog stays open and polling (F8). The prompt capitalisation differs from the clause (N4). |
| 7 | Manual button only | Yes. The `--version` refresh is not an upgrade | Met. |
| 8 | Note that Claude Code auto-updates itself | `AUTO_UPDATE_NOTE` on the Claude row and in the warning | Met. |

## Findings (most severe first)

### F1 BLOCKER: daemon-hosted sessions are never upgraded, and the plan gives the user a command that does not upgrade them

**Defect.**
- Plan §4b `_outside` gives `command = registry.resume_cmd(id)`, which is `claude --resume <id>`, for every live Claude row.
- Plan §4c and §11.2(c) put daemon-hosted panes in `cannot_stop` as "restart these yourself", with no command.
- On a daemon-hosted session, `claude --resume <id>` turns into `claude attach <short>` (`term_vt.py:3341-3343`; `term_gate.py:121-123`). That attaches a thin client to the **old** worker, so nothing restarts on the new binary.

**Repro (this machine, now).**
- The roster has 4 live workers: 2 with `cliVersion 2.1.323` and 2 with 2.1.325. The installed version is 2.1.325.
- Pressing Upgrade under plan v1 stops none of the 2.1.323 sessions.
- Those sessions either show under "outside" with `claude --resume <id>`, or under "restart these yourself" with no command.
- A user who runs `claude --resume <id>` attaches to the same 2.1.323 worker.
- Expected: each one is listed as out of date (2.1.323 < 2.1.325) with a command that really restarts it on the new binary.

**Fix direction.**
- Treat daemon-hosted sessions as **not started by the dashboard**. That is clause 4, show-only, which matches the user's own split. Show them with a correct command and their real version.
- The tracker must NOT run `claude stop` on them by default. Make that an explicit user decision (§11 below).
- Do not change the tracker-pane stop/resume path.

**Way.**
1. Version for every live Claude session comes from `Provider.running()` (F4), meaning `~/.claude/sessions/<pid>.json` `version`. It is cross-checked against the roster `cliVersion` when `kind == "bg"`.
2. `host` is set as follows:
   - `kind == "bg"`, or `parkedJobId` set, or `_background_target(sid)` non-empty → `"daemon"`;
   - `entrypoint == "claude-desktop"` → `"desktop"` (F4);
   - otherwise → `"tui"`.
3. The command depends on `host`:
   - `daemon`: `["claude stop <short>", "claude --resume <id>"]`. `<short>` is the pid file's `jobId` or the roster key. Show it as two lines under "stop it, then resume it in a terminal".
   - `tui`: `registry.resume_cmd(id, model)` under "exit it, then run".
4. A tracker pane that shows a daemon client goes into `cannot_stop` with the same two-line command. Its reason is "hosted by the Claude background daemon; the tracker does not stop background sessions".
5. Add V6: on a scratch bg session, check that `claude stop <short>` and then `claude --resume <id>` comes up with the pid file `version == installed`. Also record whether `claude stop` accepts the full session id as well as the short id.

**Test.** `tests/test_agent_cli_outside.py::test_daemon_row_command` stubs `running()` with a `kind: "bg", jobId: "ab12", version: "2.1.323"` entry and installed `2.1.325`. It asserts:
- `out_of_date is True`;
- `command == ["claude stop ab12", "claude --resume <id>"]`;
- `host == "daemon"`.

It is red under v1, where the command is `claude --resume <id>` and the version comes from the transcript tail.

### F2 BLOCKER: "Force" SIGKILLs a busy session and leaves its running tools orphaned, although a gentle stop exists in the repo

**Defect.**
- Plan §4b step 6 stops a session with `close_pty(force=True)`.
- `Pty.kill` (`term_vt.py:1560-1572`) SIGKILLs the foreground group and the shell's group only.
- A busy Claude's tool processes are by definition in **other** process groups: `_claude_work_children` keeps children with `pgid != claude_pid` (`term_vt.py:3945`), and `_claude_busy` is exactly "such children exist" (`term_vt.py:3967`).
- So they survive. A `make check` or `git commit` from the killed turn keeps running with no parent.
- The resumed session is then told "continue", re-runs the same work, and collides with it. Typical results are `.git/index.lock` and a doubled ~1300-test gate. The memory notes on this repo already record OOM kills from a single run.
- SIGKILL also skips Claude's SessionEnd hooks and its own child cleanup.
- The repo already has the gentle path: `_swap_in` sends SIGTERM, "never SIGKILL: the client must leave cleanly" (`term_vt.py:3475-3480`). `PARKED_DETACH_WAIT = 8.0` is measured with the note "a parked TUI exits gracefully and runs its SessionEnd hooks" (`term_vt.py:3349`). `_folder_wait_prompt` (`term_vt.py:1902`) waits for the shell prompt to return.

**Repro.**
1. In a tracker folder pane, have a session run `sleep 300` through Bash.
2. Run the v1 stop.
3. Actual: `close_pty` answers `confirmed: true` because its targets were the fg group and the shell, but `ps` still shows `sleep 300` with ppid 1.
4. Expected: nothing from that turn is left running.

**Fix direction.**
- Stop gently first, then fall back.
- Never leave work children behind.
- Keep the folder pane's tty where possible, so an open terminal modal stays bound.
- Do NOT add a second resume path: resume still goes through `open_pty`.

**Way.** New `term_vt.stop_for_upgrade(tty, sid) -> dict`, about 40 lines, next to `_swap_in`:
1. Under `_LOCK`, find `pt` and run `_refresh_fg(pt)`. Read `pg = _fg_pgid(pt)` for a folder pane, or `pt.pid` for a dedicated one. Refuse when `pg in (pt.pid if folder, os.getpgrp(), 0)`.
2. Outside the lock, snapshot `kids = _claude_work_children(pg)`.
3. `os.killpg(pg, SIGTERM)`.
4. Wait up to `PARKED_DETACH_WAIT`: `_folder_wait_prompt(pt, PARKED_DETACH_WAIT)` for a folder pane, `pt.done` for a dedicated one.
5. If it did not exit, `call_route(close_pty, {tty, session: sid, force: True})`. This is v1's path, now only the fallback.
6. For each pid in `kids` that is still alive, `killpg(getpgid(pid), SIGTERM)`, then after 2 s SIGKILL whatever survives.
7. Return `{stopped, graceful, confirmed, orphans_killed}`.

Then the existing `open_pty` resume runs. For a folder pane whose shell is now idle in the same cwd, it types the resume at that prompt, so the tty is kept (`term_vt.py:3035-3040`). For a dedicated pane it spawns a new one.

Add V5:
- Is SIGTERM to a **non-parked, busy** interactive TUI a clean exit within 8 s?
- Does it take its tool children down with it?
- Is the transcript tail valid JSONL afterwards?

Update the rule-6 exception wording to "SIGTERM, then `close_pty`'s SIGKILL as a fallback".

**Test.** `tests/test_term_vt_upgrade.py::test_stop_kills_work_children`:
1. Spawn a real folder pty (pattern: `tests/test_folder_terminal.py`).
2. Have its fg job start `sleep 300` in its own pgid, e.g. `sh -c 'set -m; sleep 300 & wait'`.
3. Call `stop_for_upgrade`.
4. Assert the sleep pid is gone.

Red under v1's `close_pty(force)`. Second test: on a stub fg that traps TERM and exits, `graceful is True` and the same `pt.id` is returned by the following `open_pty`.

### F3 BLOCKER: the corrections and the "verbatim copies" are grounded on a stale sibling commit, so copying them makes merge conflicts and drops a hardening

**Defect.**
- Plan §0.2, §0.3 and the Log ground on `2bca388`. The sibling worktree is at `fe8f580`, where:
  - (a) the `_with_prompt` call is live (`term_vt.py:3128`);
  - (b) `_local_caller` already checks Origin (`server.py:230`) through a new `util.origin_matches_host` (`util.py:715`);
  - (c) `_with_prompt` filters control characters (`term_vt.py:2955-2958`).
- Plan §4a, §4c and §4d copy the 2bca388 text and add a separate `_same_origin`. So:
  - `_local_caller` differs from the sibling's in the same hunk, which is a conflict.
  - `util.py` gets `run_argv` and `is_loopback_host` at its tail while the sibling adds `origin_matches_host` and `is_loopback_host` there, another conflict.
  - The `_with_prompt` def differs, a third conflict.
  - Plan §10's "conflicts are textual and trivial" is understated.
- The plan also tells the user to "report" two bugs that the sibling has already fixed.

**Repro.** Read `fe8f580 server.py:223-240` against plan §4d. `_local_caller` gains the Origin line at line 230, which plan v1 omits, and adds `_same_origin` instead.

**Fix direction.**
- Re-ground on `fe8f580`.
- Copy the **head** text byte for byte at the **same position**, so that identical hunks on both sides merge cleanly.
- Delete corrections 0.2 and 0.3, or mark them "fixed on the sibling at fe8f580; nothing to report".
- Do NOT fork a second Origin helper.

**Way.**
- `util.py`: append `origin_matches_host` and `is_loopback_host` exactly as at `fe8f580 util.py:715-747`, including the `from urllib.parse import urlparse` that it needs. Check the sibling's util.py imports when copying.
- `server.py`: import line `from .util import is_loopback_host, origin_matches_host`, exactly as `fe8f580 server.py:7`. Replace `_local_caller` with `fe8f580 server.py:223-240`. **Drop `_same_origin`**: the Origin check lives in `_local_caller`.
- `term_vt.py`: copy `_with_prompt` exactly as `fe8f580 term_vt.py:2951-2959`, docstring included, and add a one-line comment at the new resume call site instead of editing the docstring.
- `run_argv` moves into `agent_cli.py` as a private `_run`. Nothing is added to `util.py` beyond the copied helpers.
- §10 lists the real remaining conflicts:
  - `ext_cr_dialogs.js`: both branches insert before `renderConfig` (`fe8f580 ext_cr_dialogs.js:1134-1306`). Put `agentsBlock` after `renderConfig` instead, and put the three helpers just above it.
  - `conventions.md` rule 6: both branches append exception blockquotes.
  - `README`.
  - Both of these are small, manual resolutions.

**Test.** `tests/test_agent_routes.py::test_cross_origin_refused_everywhere`:
1. POST `/api/agents/run` with `Origin: http://evil.example` → 403.
2. Also POST to an existing `_local_caller` route, `term_launch` open (pattern: `tests/test_cr_routes.py`), with the same Origin → 403.

The second case is red under v1, because v1's `_local_caller` has no Origin check. Plus a byte-equality check in the implementer's notes (not a unit test): `_local_caller`'s body matches `fe8f580`.

### F4 SHOULD-FIX: the outside list misses sessions that are idle but still running, and mislabels Claude-desktop sessions; there is a better version oracle

**Defect.**
- Plan §4b `_outside` keeps rows with `time.time() - mtime < config.LIVE_WINDOW` (300 s). A Claude open in an iTerm tab that has been idle for 6 minutes is still running the old binary, but it is not listed.
- The version comes from the transcript tail, which is the last binary to *write*, not necessarily the one running now.
- `entrypoint: claude-desktop` sessions run the desktop app's bundled CLI. `claude update` does not touch them, and `claude --resume` in a terminal would move the session out of the app.

**Repro (now).** 4 live `interactive/claude-desktop` processes are on 2.1.321 against 2.1.325 installed.
- Under v1, those idle for more than 5 minutes are not listed.
- Those that are listed get `claude --resume <id>`.
- Expected: all 4 are listed as "runs inside the Claude desktop app; it updates with the app", with no terminal command.

**Fix direction.**
- Enumerate **running processes**, not recent files, from the registry Claude already writes.
- This replaces (cuts) the v1 `cli_version` list-row field.

**Way.**
- New seam method `Provider.running(self) -> list[dict]` in `base.py`, default `[]`.
- `ClaudeProvider.running()` (in `claude.py`, next to `parked_job_id`):
  - read each `LIVE_SESSIONS_DIR/*.json`;
  - keep it only when `pid` is an int, `_pid_alive(pid)`, and `" ".join(procStart.split()) == _ps_lstart(pid)` (the same fail-closed check `parked_job_id` uses at `claude.py:655-657`);
  - emit `{id: sessionId, pid, version, kind, entrypoint, job: jobId or parkedJobId or "", host}` (host as in F1);
  - read no other keys, because the file has sockets in it.
- Auggie keeps the default `[]`. Its live rows still come from `all_sessions()` mtime and are labelled "version unknown". This is a stated known gap.
- `_outside` builds Claude rows from `running()` minus the tracker-owned pids and ids. It joins `registry.all_sessions()` only for `title`, `cwd` and `model`.
- Drop the `_tail_scan` `version` harvest, `cli_version` on the row, and `setdefault` in `all_sessions` (see Overbuilding).

**Test.** `tests/test_claude_running.py`, with a temp `LIVE_SESSIONS_DIR` holding 3 files:
1. A live pid (`os.getpid()`, real procStart from `_ps_lstart`) → listed with its `version`.
2. A dead pid → excluded.
3. A live pid with a wrong `procStart` → excluded.

Plus a `_outside` test where a desktop entry gives `host == "desktop"` and `command is None`. Red under v1, which has no `running()` and uses an mtime filter.

### F5 SHOULD-FIX: `auggie upgrade` asks for confirmation; with stdin closed it either aborts or holds the job lock for 600 s

**Defect.**
- Plan §3 descriptor `"update": ["upgrade"]`, test §8 `Auggie update == ["upgrade"]`, the selfcheck assertion, and the rule-6 text `<auggie> upgrade`.
- `auggie upgrade --help` prints `--skip-confirmation  Skip confirmation prompt`.
- Plan V3 says "if it prompts, hide Upgrade for Auggie". That would drop a feature that is in fact possible (clause 2).

**Repro.** Run `auggie upgrade </dev/null` under `run_argv`. Expected behaviour is either a prompt read on EOF (rc ≠ 0, reported as "Update failed") or a hang until `UPDATE_TIMEOUT` = 600 s while `_JOB_LOCK` blocks Doctor and Upgrade for every agent. Not run: it would really upgrade.

**Fix direction.** Use the documented non-interactive flag. Keep Auggie Upgrade.

**Way.**
- Descriptor `"update": ["upgrade", "--skip-confirmation"]`.
- The rule-6 text lists `<auggie> upgrade --skip-confirmation`.
- V3 becomes: "run it once with the user's OK at S7; expect rc 0 and `--version` agrees".
- Also per agent, `UPDATE_TIMEOUT` stays 600 for Claude, which downloads about 100 MB, and is 300 for Auggie.

**Test.** `test_agent_cli_parse.py`: `_d["auggie"]["update"] == ["upgrade", "--skip-confirmation"]`. The jobs test with a stub `auggie` that exits 1 when `--skip-confirmation` is missing asserts the job succeeds. Red under v1.

### F6 SHOULD-FIX: a session can be stopped and then fail to resume for reasons that were knowable before the stop

**Defect.** Plan §4b step 6 kills, then calls `open_pty`. `open_pty` can then refuse in these cases:
- an OpenRouter session whose launcher is not configured: `GatewayError` → 400 (`term_vt.py:3108-3109`);
- a missing cwd → 404 (`term_vt.py:3090-3091`);
- `TRACKER_TERMINAL` changed live → 403 (`term_gate.py:60-62`);
- the cap → 429 (`term_vt.py:3149`, `3302`), when the killed pty is not yet `done`.

There is also a race: if `close_pty` answers `confirmed: false`, meaning the old Claude may still be alive, the resume can hit "running elsewhere". Then the fork backstop (`term_vt.py:2449-2457`) makes a COPY under a new id and drops the prompt.

**Repro.**
1. A tracker pane runs an OpenRouter session.
2. Unset the slot file.
3. Press Upgrade and confirm.
4. Actual: the session is killed, then the open gives 400, and it is reported as failed.
5. Expected: it is never killed, and it is listed in `cannot_stop` with "the OpenRouter launcher is not configured".

**Fix direction.**
- Preflight everything `open_pty` will check **before** the stop.
- Never resume unless the stop was confirmed.
- Do NOT duplicate `open_pty`'s logic: call the same functions it calls.

**Way.** In `upgrade_candidates` (and again just before each stop), set `stoppable = False` with a reason when any of these holds:
- `not term_gate.allowed()`;
- `term_gate.resume_argv(sid)` raises `GatewayError`;
- `not term_gate.session_cwd(sid, resume=True)`;
- `_background_target(sid)` is non-empty.

In `_job_upgrade`, if `stop_for_upgrade` returns `confirmed: False`, do not open. Report "could not confirm it stopped; open its terminal", with the command.

**Test.** `test_agent_cli_jobs.py::test_preflight_never_kills_unresumable`: the fake `term_vt` makes `resume_argv` raise for one candidate. Assert zero stop calls for it, plus a `cannot_stop` reason. And `test_unconfirmed_stop_not_resumed`: the stop returns `confirmed: False`, so assert zero open calls. Both red under v1.

### F7 SHOULD-FIX: "unknown session id" panes are mostly resolvable, so "Force all" excludes more than it has to

**Defect.**
- Plan §4c puts every pane with an empty `_pty_session_ids(p)` into `cannot_stop`. That covers fork copies (`term_vt.py:3981-3982`, `3986-3987`) and a hand-typed `claude` that is not yet latched.
- The fg pgid of such a pane is a Claude pid, and `LIVE_SESSIONS_DIR/<pid>.json` names its `sessionId`.
- Plan §11.2's argument that stopping (b) "loses the pane with no way to resume it" is therefore false for these.

**Repro.**
1. Open a pane.
2. Type `claude` by hand.
3. Within the latch window, press Upgrade.
4. Actual: the pane is listed under "restart these yourself".
5. Expected: it is stoppable, with its real id.

**Fix direction.** Resolve the id through `running()`. Only a pane whose id is still unknown after that stays in `cannot_stop`.

**Way.** In `upgrade_candidates`, when `_pty_session_ids(p)` is empty, set `pid = os.tcgetpgrp(p.fd)` and look it up in `{r["pid"]: r for r in claude.running()}`. If there is a hit with `host == "tui"`, set `sid = hit["id"]`. Same lazy provider import as `_provider()` (`term_vt.py:3357`).

**Test.** `test_term_vt_upgrade.py::test_unknown_id_resolved_via_pid_file`: a fake pty with an `fg` forked label, `tcgetpgrp` patched to 4242, and `running()` returning `{pid: 4242, id: "S", host: "tui"}`. Assert `stoppable is True` and `session == "S"`. Red under v1.

### F8 SHOULD-FIX: the user is not told that sessions were auto-resumed if the Config dialog was closed during the job

**Defect.**
- Plan §4e: "The panel then polls `GET /api/agents` every 1 s while the job runs … On completion it fires `toast`."
- The job can take `UPDATE_TIMEOUT` (600 s), plus N stop/resume cycles, plus `VERIFY_WAIT`. Users close dialogs.
- Clause 6 requires the notification.

**Repro.**
1. Press Upgrade and confirm.
2. Close the Config dialog.
3. The job finishes.
4. Actual: no toast; the summary is only visible if the dialog is reopened.
5. Expected: a toast naming the resumed sessions and the prompt.

**Fix direction.**
- The completion poll must outlive the dialog.
- The server still writes the text.
- No new route.

**Way.**
- In `ext_cr_dialogs.js`, keep a module-level `_agentJobTimer` started on 202. It is not owned by the dialog DOM. It polls `GET /api/agents` every 2 s until `job.state` is `done` or `failed`, then fires `toast({title: job.summary})` once, keyed on `job.id`, and clears itself.
- On page load, if `GET /api/agents` shows a job finished in the last 10 minutes that this tab has not toasted, toast it once. Remember the toasted job id in `sessionStorage`.
- The server also prints `job.summary` to its log.

**Test.** `tests/test_agents_ui.py`:
- the poller start is not inside `renderConfig`/`agentsBlock`;
- the poller is cleared only on job completion, not on dialog close;
- `toast(` is called with `job.summary`.

These are static source assertions, the repo's existing JS-test style. Red under v1.

### F9 SHOULD-FIX: confirm is keyed on the tty alone, so a different session that moved into a confirmed pane gets killed

**Defect.**
- Plan §4b step 5 intersects candidates with `confirm`, which is a list of tty ids.
- A folder pane's foreground can change between the warning and the confirm. The user can `/exit` and resume another session in the same shell.
- The worker would then stop a session the user never saw.

**Repro.**
1. The warning lists tty T running session A.
2. The user exits A in T and resumes B in T.
3. The user confirms.
4. Actual: B is stopped.
5. Expected: B is reported as "not shown in the warning, not stopped".

**Fix direction.** Confirm (tty, session) pairs.

**Way.**
- `confirm` is a list of `{tty, session}` objects. The server validates both as str.
- A candidate is stopped only when both match.

**Test.** `test_agent_cli_jobs.py::test_confirm_pair_mismatch_not_stopped`. Red under v1.

### F10 SHOULD-FIX: mutual exclusion with the tracker's own in-app Update depends on which branch lands first

**Defect.**
- Plan §7 S6 adds the cross-lock only "when the pending branch has landed".
- If this branch lands first, the lock never gets written by either side.
- A tracker self-update in the middle of a job execs the server, which kills the worker between a stop and a resume.

**Fix direction.** Write this side now, in a way that works whether or not `update.py` exists. Record the other side as a merge TODO.

**Way.**
- `agent_cli.start`: `u = sys.modules.get("aitracker.update"); lk = getattr(u, "_APPLY", None)`. If `lk is not None and lk.locked()` → 409 "the tracker is updating itself".
- Expose `agent_cli.job_running()`.
- Add a line to this durable file and to the pending branch's durable file (by message to its owner, not by edit): "on merge, `update_apply` must 409 while `agent_cli.job_running()`".

**Test.** `test_agent_cli_jobs.py::test_refuses_while_tracker_updating` puts a fake module in `sys.modules` with a held `_APPLY` and expects a 409. Red under v1.

### F11 SHOULD-FIX: the verify step uses a weak oracle and has an unbounded total wait

**Defect.**
- Plan §4b step 7 polls each session's transcript tail for `version == new` every 2 s, up to `VERIFY_WAIT` (90 s). It does not say whether that is per session in sequence (N × 90 s) or shared.
- A transcript `version` line only appears when the new process writes. It says nothing about whether the prompt was submitted. Plan §10 relies on that ("prompt not confirmed").

**Fix direction.**
- `on_version` comes from `running()`: an entry with `id == sid` and `version == new`. That is available the moment the process starts.
- `prompt_seen` comes from a raw substring check for the prompt text in a `"type":"user"` line of the last 96 KB.
- Use one shared deadline.

**Way.** Add `agent_cli._verify(resumed, new, deadline)`, which loops over all resumed sessions together until each has both answers or the shared deadline passes. Also report a version mismatch: "resumed on vX, expected vY; another `claude` is first on your shell's PATH; run Doctor". This catches the case where the server's `shutil.which` differs from the login shell's PATH.

**Test.** `test_agent_cli_jobs.py::test_verify_shared_deadline_and_mismatch`, with a fake clock and two sessions. The total wait is ≤ `VERIFY_WAIT`, and a `running()` version of `2.1.300` is reported as a mismatch. Red under v1.

### NITs

| # | Defect | Direction / way | Test |
|---|---|---|---|
| N1 | §3 calls `agent_cli = None` "a data descriptor". It is a plain class attribute. | Fix the wording only. | none (doc) |
| N2 | §4a `run_argv` returns `str(e)` on `OSError`, but the sibling's `_run` returns `str(e).encode()`. It also drops the post-kill `communicate(timeout=5)` reap. | Copy `fe8f580 update.py:49-80` as `agent_cli._run`, with no env default to `_git_env`. | `test_agent_cli_jobs`: a missing binary gives `err` as bytes |
| N3 | `claude doctor` "Reads settings files in the current directory" (CLI help). The job inherits the server's cwd. | Pass `cwd=os.path.expanduser("~")` to `_run` for doctor and update. | stub records cwd == HOME |
| N4 | Clause 6 says "continue, re-read claude.md"; the plan uses `CLAUDE.md`. | No change. The file is `CLAUDE.md`. Record it as the deliberate reading in the contract table. | — |
| N5 | No message is defined for an empty stop list, or for an agent with `restarts_sessions: False`. | `plan_upgrade` picks the text: an empty list gives "No session started from this dashboard will be stopped."; Auggie gives "Auggie sessions are not restarted by the tracker; restart them yourself once it lands." | route test asserts both strings |
| N6 | The `_selfcheck` assertion only re-checks constants. | Keep one assertion, but make it exercise logic: `parse_version` on both formats plus `plan_upgrade` text containing "will be stopped" and "continue, re-read CLAUDE.md" when given stub candidates. | — |
| N7 | `plan_upgrade` runs in the request handler (`all_sessions`, a `ps` per pane, pid-file reads). | No change. Existing routes do the same (`term_list`). It runs no agent CLI. Note it in the rule-6 text as "no agent CLI in a handler". | — |
| N8 | The tracker dying mid-flow takes **every** tracker pane with it, not just "at most one". | No change to the design. Fix the §2 wording: "the one being restarted is logged with its resume command; the others die with the tracker as they always would". | — |
| N9 | The Log/§0 says "4 commits @ 2bca388". | Change it to "5 commits @ fe8f580". | — |

## Overbuilding: what to cut

- **`cli_version` on every session-list row**, the `_tail_scan` harvest and `setdefault` in `all_sessions`. They are used only by `agent_cli`, the payload grows on every 2 s poll, and F4's `running()` is the better oracle. The plan itself defers the chip. Cut.
- **`util.run_argv`**. Make it private in `agent_cli.py` (F3/N2). Folding `update._run` later is optional and does not belong in this contract.
- **`_same_origin`** in `server.py`. It is absorbed by the sibling's `_local_caller` (F3).
- **Per-session transcript polling for verify**. Replaced by `running()` plus one substring check (F11).
- Keep: the version cache thread (needed so no handler waits on a 0.8-2.8 s `--version`), `registry.resume_cmd` extraction (6 lines, removes a duplicate), the README/CLAUDE.md lines and the rule-6 text.

## Copy now vs wait for the sibling branch (§11.1)

**Copying is the smaller risk, but only from `fe8f580` and only at the same positions.** Waiting blocks this feature on a 5-commit branch whose own durable file has every clause "not discharged". The copied surface is small:
- `origin_matches_host`, `is_loopback_host` and `_local_caller`;
- `_with_prompt`;
- three 20-line JS helpers.

Exact merge conflicts, whichever branch lands second:
1. `server.py` import line and `_local_caller`. These are identical if copied from `fe8f580`, so they merge clean.
2. `util.py` tail. Identical if copied, so it merges clean.
3. `term_vt.py` `_with_prompt` def. Identical, so clean. The call sites are in different `if` arms 6 lines apart, so they should merge clean; check after the merge.
4. `ext_cr_dialogs.js`: both branches insert before `renderConfig`. That is a real conflict unless `agentsBlock` goes after `renderConfig`. The helpers are duplicated as identical function declarations, which is legal in a function body; delete one copy on merge.
5. `.claude/rules/conventions.md` rule 6: both append blockquotes. A trivial manual resolution.
6. `README.md`: different sections, so likely clean.

**The sibling is still moving**, as `fe8f580` showed. Re-diff the copied text against its head immediately before S1 and again before the push.

## Clean plan (v2): complete, folds in every finding above

### Contract

The contract is unchanged (8 clauses, verbatim, in the plan file). Clause 4 is read as: anything **not started from a tracker pane** is show-only. That includes Claude-daemon background sessions and Claude-desktop sessions. Clause 6's prompt is `continue, re-read CLAUDE.md`.

### What is built

Config gets an **Agents** section with one row per installed agent CLI (Claude Code, Auggie). Each row shows:
- the version, read in the background;
- the clause-8 note, for Claude;
- **Doctor**, for Claude only;
- **Upgrade**.

Upgrade always shows the server-written warning first. It has four parts:
- (a) tracker panes that will be stopped and resumed, with the busy ones flagged;
- (b) tracker panes that cannot be, each with its reason and command;
- (c) live sessions not started here, show-only, each with its running version, out-of-date status and the correct command for its kind (terminal / background daemon / desktop app);
- (d) the user's sentence, the auto-continue prompt and the auto-update note.

On confirm, a background job does the following:
1. Update.
2. Verify the version.
3. For each confirmed (tty, session) not already on the new version, one at a time:
   - stop it gently (SIGTERM, wait, SIGKILL fallback, kill orphaned work children);
   - resume it through `open_pty` with the prompt.
4. Verify each resumed session through the live-process registry.
5. Write a summary. The SPA toasts it even if the dialog was closed.

### Ordering (the risky spot)

1. Read the old version.
2. Run the update.
3. Read the new version.
4. Only then stop and resume.

An update failure (rc ≠ 0, timeout, spawn error, unreadable version) stops nothing. Every per-session precondition `open_pty` checks is checked **before** that session is stopped. A stop that is not confirmed is never resumed. The tracker dying mid-job kills all of its own panes, as it always would; the one being restarted is logged with its resume command first.

### Seams (shared, not a Claude fork)

**`providers/base.py`.** Two new members:
- `agent_cli = None`, a class attribute;
- `def running(self): return []`: live agent processes, each `{id, pid, version, kind, entrypoint, job, host}` with `host` ∈ `tui|daemon|desktop`.

**`providers/claude.py`.**
- `ClaudeProvider.agent_cli = {"id": "claude", "label": "Claude Code", "bin": "claude", "version": ["--version"], "doctor": ["doctor"], "update": ["update"], "update_timeout": 600, "restarts_sessions": True}`.
- `ClaudeProvider.running()`:
  - reads `config.LIVE_SESSIONS_DIR/*.json` (keys `pid, procStart, sessionId, kind, entrypoint, jobId, parkedJobId, version` only);
  - keeps an entry when `_pid_alive(pid)` and the normalised `procStart == _ps_lstart(pid)`;
  - sets `host = "daemon"` if `kind == "bg"` or `parkedJobId` is set, `"desktop"` if `entrypoint == "claude-desktop"`, else `"tui"`;
  - fills `job = jobId or parkedJobId or ""`;
  - never raises.

**`providers/auggie.py`.** `AuggieProvider.agent_cli = {"id": "auggie", "label": "Auggie", "bin": "auggie", "version": ["--version"], "doctor": None, "update": ["upgrade", "--skip-confirmation"], "update_timeout": 300, "restarts_sessions": False}`. `running()` stays the default `[]`, a known gap: Auggie has no process registry.

**Augment extensions.** Unchanged (`None`).

**`registry.py`.** Extract `resume_cmd(sid, model) -> str | None` from `registry.py:269-274`. `parse_any` calls it, so behaviour is unchanged.

### `aitracker/util.py` (bundled)

Append `origin_matches_host` and `is_loopback_host` **byte for byte from `fe8f580 util.py:715-747`**, plus any import they need, copied as the sibling has it. Nothing else.

### `aitracker/agent_cli.py` (new, bundled; add it to `scripts/bundle.py` ORDER after `tunnel.py`, before `server.py`)

**Constants:**
- `RESUME_PROMPT = "continue, re-read CLAUDE.md"`;
- `VERSION_TIMEOUT = 15`, `DOCTOR_TIMEOUT = 60`;
- `VERSION_TTL = 60`, `VERIFY_WAIT = 90` (one shared deadline), `OUTPUT_CAP = 8000`;
- `AUTO_UPDATE_NOTE`, as in v1;
- `UPGRADE_MESSAGE` (the user's sentence + the prompt + "a session already on the new version is left running"), `NO_STOP_MESSAGE` and `NO_RESTART_MESSAGE` (N5).

**Functions:**
- `_run(argv, timeout, cwd)`: a copy of `fe8f580 update._run` and `_kill_proc_group`. stdin `DEVNULL`, `start_new_session=True`, timeout → `killpg(SIGKILL)` → `(None, b"", b"timeout")`, `OSError` → `(None, b"", bytes)`. env is `_cli_env()`, meaning `os.environ` minus `GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE`. cwd is `~`.
- `specs()`: the descriptors of `PROVIDERS` that have `agent_cli`, plus `path = shutil.which(bin)` and `provider`.
- `parse_version(text)`: the first `\d+\.\d+\.\d+` in the first line.
- `status()`: the GET body. It never runs a subprocess itself. It starts the single-flight `agent-versions` daemon thread when an entry is older than `VERSION_TTL`.
- `plan_upgrade(agent_id) -> {stop, cannot_stop, outside, message, note, installed}`:
  - `stop` and `cannot_stop` come from `tv.upgrade_candidates()`, or `[]` when `sys.modules.get("aitracker.term_vt")` is None (the bundle);
  - `outside` comes from `_outside`.
- `_outside(spec, installed, owned_pids, owned_ids)`:
  - Claude: `spec.provider.running()` minus the owned ones, joined to `all_sessions()` rows for title, cwd and model. `out_of_date` = version tuple < installed.
  - `command` by host: `tui` → `[resume_cmd(id, model)]`; `daemon` → `["claude stop <job>", "claude --resume <id>"]`; `desktop` → `None`, with the reason "runs inside the Claude desktop app; it updates with the app".
  - Auggie: `all_sessions()` rows of that provider inside `LIVE_WINDOW`, "version unknown, restart Auggie in that terminal", `command None`.
- `start(agent_id, action, confirm) -> (code, body)`:
  - 400 on an unknown agent or action, or when confirm is not a list of `{tty: str, session: str}`;
  - 409 when a job runs, or when `sys.modules.get("aitracker.update")._APPLY` is held;
  - otherwise 202 `{job}`;
  - single flight with `_JOB_LOCK`; the last job is kept in memory.
- `job_running()`.
- `_job_doctor`: `_run([path, "doctor"], DOCTOR_TIMEOUT)`, output ANSI-stripped and capped.
- `_job_upgrade(job, spec, confirm)`:
  1. `old = version()`, or fail.
  2. `_run([path, *spec["update"]], spec["update_timeout"])`. rc ≠ 0 → fail, "Update failed; no session was stopped. Run Doctor to see why."
  3. `new = version()`, or fail.
  4. If not `restarts_sessions`, go to 8.
  5. Candidates are `tv.upgrade_candidates()` whose `(tty, session)` is in `confirm` and that are `stoppable`. Skip one whose `version == new`. A pair that has appeared or changed since the warning is reported as "not shown in the warning; not stopped".
  6. For each candidate, one at a time:
     - re-run the preflight (F6);
     - log `[ai-tracker] agent upgrade: restarting <sid>; if this dashboard dies, resume with: <cmd>`;
     - `r = tv.stop_for_upgrade(tty, sid)`; if `not r["confirmed"]`, report and continue;
     - `code, obj = tv.call_route(tv.open_pty, {session, mode: "resume", cols, rows, prompt: RESUME_PROMPT})`;
     - record the new tty, or the error plus the command.
  7. `_verify(resumed, new, time.time() + VERIFY_WAIT)`: `on_version` from `running()`, `prompt_seen` from a raw tail substring, and a PATH mismatch reported.
  8. `job.outside = _outside(...)`. `job.summary` is server text, e.g. "Claude Code 2.1.323 → 2.1.325. Resumed with “continue, re-read CLAUDE.md”: A, B. Already current: C. Failed: D (run …). Not started here, left alone: 3 (2 out of date)."

  The summary is also printed to the log.
- Imports are top level with no aliases (the bundle strips import lines).

### `aitracker/term_vt.py` (not bundled)

- `_with_prompt`: byte for byte from `fe8f580 term_vt.py:2951-2959`. Applied in the **resume** arm only: `argv = _with_prompt(term_gate.resume_argv(sid), body.get("prompt"))`, computed before `forked`. Comment: "also used by agent upgrade's resume". Known limit: the fork backstop drops it, and verify reports `prompt_seen: false`.
- `upgrade_candidates() -> list[dict]`:
  - under `_LOCK`: `_reap()`, the live not-closing PTYS, and `_refresh_fg` on each folder pane;
  - outside the lock: keep the panes where `_foreground_is_claude(p.fd)`;
  - `sid = (_pty_session_ids(p) or ("",))[0]`, or the pid-file lookup of `os.tcgetpgrp(p.fd)` in `claude.running()` (F7);
  - version from that `running()` entry;
  - `busy = _claude_busy(p)`;
  - preflight: `stoppable` is false with a reason when the id is unknown, the session is daemon-hosted (with the F1 two-line command), `not term_gate.allowed()`, `resume_argv` raises, or `session_cwd(sid, resume=True)` is empty;
  - dict `{tty, session, pid, version, cwd, title, busy, cols, rows, folder, stoppable, reason, command}`.
- `stop_for_upgrade(tty, sid) -> {stopped, graceful, confirmed, orphans_killed}`: as in F2:
  1. snapshot the fg pgid and `_claude_work_children`;
  2. SIGTERM the fg group (never `0`, our own group or the shell);
  3. wait `PARKED_DETACH_WAIT` (folder: `_folder_wait_prompt`; dedicated: `pt.done`);
  4. else `call_route(close_pty, {tty, session, force: True})`;
  5. then SIGTERM, and after 2 s SIGKILL, the surviving captured children's groups.
- `call_route(fn, body) -> (code, obj)` with `_Internal` (`headers = {}`, and `_json(obj, code=200, headers=None)` records the reply).

### `aitracker/server.py` (bundled)

- Import `from .util import is_loopback_host, origin_matches_host`, as at `fe8f580 server.py:7`.
- Replace `_local_caller` with `fe8f580 server.py:223-240`: proxy headers → Origin → loopback peer → loopback Host when there is no AUTH. This is a strict tightening for `term_launch` and `_readonly`.
- `GET /api/agents`: `_local_caller`, 403 if refused, else `agent_cli.status()`. Not in `_RO_GET_ALLOW`.
- `POST /api/agents/run {agent, action, confirm?}`:
  - `_readonly()` deny-all first (`server.py:558`), then `_local_caller` → 403;
  - an upgrade without `confirm` → 409 `{needs_confirm: true, ...plan_upgrade(agent)}`;
  - otherwise `agent_cli.start` → 202, 400 or 409;
  - doctor → 202.

### `aitracker/web/ext_cr_dialogs.js`

- `crReadOnly`, `crCall` and `crBtn` are copied byte for byte from `fe8f580 ext_cr_dialogs.js:1139-1160` and placed **after** `renderConfig`'s closing brace, together with `agentsBlock()`. This avoids the sibling's insertion hunk.
- `'Agents'` goes into `sections` after `'Terminal'`.
- Each row shows the version (or "checking…" / the error), the `note`, and the Doctor and Upgrade buttons. The buttons are disabled while a job runs or when `crReadOnly()`.
- Upgrade → 409 → an inline `role="alertdialog"` with `message`, `stop` (with "working — its current turn will be interrupted" when busy), `cannot_stop` (reason + command), `outside` (version, out of date / unknown, `command` lines in `<code>`), the `note`, and **Upgrade and restart these** / **Cancel**.
- Confirm → re-POST `confirm = stop.map({tty, session})`.
- A module-level `_agentJobTimer` polls every 2 s until the job is done, then toasts `job.summary` once per `job.id`. On page load, any recent un-toasted job is toasted once.
- Every sentence on screen comes from the server.

### Docs and rules

- `README.md`:
  - "### Agents: Doctor and Upgrade" under Terminal, including that background-daemon and desktop-app sessions are shown, not restarted;
  - one line in "Adding a tool" (`agent_cli` + optional `running()`);
  - qualify line 7.
- `CLAUDE.md`: the "Add a tool" line gains "+ optional `agent_cli` / `running()`".
- Conventions rule-6 exception (lands in the same commit as `agent_cli.py`):

> *"Exception (agent CLI Doctor/Upgrade, user-requested): `aitracker/agent_cli.py` — and only it, never synchronously inside a request handler (its own job and version-refresh threads may) — may run, with no shell, stdin closed, cwd `~`, its own process group and a timeout that kills the group, exactly these argv: `<claude> --version`, `<claude> doctor`, `<claude> update`, `<auggie> --version`, `<auggie> upgrade --skip-confirmation`, where `<claude>`/`<auggie>` is `shutil.which` of that name on the server's own PATH. Argv is fixed in code; the request only picks the agent and the action from that table. `--version` runs in the background at most once per `VERSION_TTL` (60 s) while the Agents panel is polled; Doctor and Upgrade run only when a local caller (no proxy header, same Origin, loopback peer, loopback Host name, not read-only) presses the button — never on a schedule. `update`/`upgrade` (and `doctor`'s own checks) contact the vendor's servers with the CLI's own configuration; the tracker itself sends nothing. After an update that exited 0 and whose `--version` is readable, it may stop only the tracker's own terminals whose foreground is a Claude session with a known id, not hosted by the Claude daemon, that pass every resume precondition and that the user confirmed by (terminal, session) in the warning — by SIGTERM to that Claude's process group, then `term_vt.close_pty`'s SIGKILL only if it has not exited within `PARKED_DETACH_WAIT`, then the turn's own orphaned tool processes — and resume each through `term_vt.open_pty` as `claude --resume <id> "continue, re-read CLAUDE.md"`. It reads `~/.claude/sessions/<pid>.json` (pid, procStart, sessionId, kind, entrypoint, jobId, parkedJobId, version only). It never stops, signals or edits a session the tracker did not start (background-daemon and desktop-app sessions are listed with the command to run), never edits a transcript, and never changes Claude Code's or Auggie's own auto-update settings. No other outbound network call is allowed."*

### Verify before relying (S0; results written into the plan file)

- **V1.** Create an old-binary session in a scratch dir (`~/.local/share/claude/versions/2.1.323 -p "say ok"`). Resume it in a tracker PTY with `claude --resume <id> "continue, re-read CLAUDE.md"`. Pass when:
  - its `~/.claude/sessions/<pid>.json` has `sessionId == id` and `version == installed`;
  - the transcript gains a user line with the prompt.

  Tear the session down afterwards. If V1 fails, ship with stop/resume disabled, and go back to the user.
- **V2.** `claude doctor` under `_run` with cwd `~`.
- **V3.** `auggie upgrade --skip-confirmation` with no TTY, run once at S7 with the user's OK.
- **V4.** `claude update` with no TTY, run once at S7 with the user's OK.
- **V5.** SIGTERM to a busy, non-parked interactive Claude in a folder pane (Bash `sleep 300` running). Measure:
  - the exit time, against the 8 s budget;
  - whether the sleep survives;
  - whether the transcript tail is valid;
  - whether SessionEnd hooks run.

  This sets whether the orphan sweep is needed or merely a backstop.
- **V6.** On a scratch background session: does `claude stop <job>` and then `claude --resume <id>` come up on the installed version? Does `claude stop` also accept the full session id? Fix the displayed command from the result.

### Sequencing (each step its own commit, green before the next)

| Step | Lands |
|---|---|
| S0 | V1, V2, V5, V6. Re-diff the copied sibling text against its head. |
| S1 | Copied `util` helpers; `Provider.agent_cli` + `running()` + both descriptors; `ClaudeProvider.running()`; `registry.resume_cmd`. |
| S2 | `term_vt._with_prompt` (resume arm), `upgrade_candidates`, `stop_for_upgrade`, `call_route`. |
| S3 | `agent_cli.py` + the rule-6 exception + bundle ORDER. |
| S4 | `server.py` `_local_caller` (copied) + routes. |
| S5 | `ext_cr_dialogs.js` Agents section + module poller. |
| S6 | README, CLAUDE.md, the `_selfcheck` assertion, the merge-TODO line for the sibling. |
| S7 | Live proof on a spare port (never `pkill -f aitracker`). Two scratch tracker sessions (one busy with `sleep`) and one outside terminal session. With the user's OK, press Upgrade. Check: the warning text, the gentle stop (no orphaned `sleep`), the same tty for the folder pane, the pid-file version, `prompt_seen`, the toast after closing the dialog, and the outside list with its command per host. Run V3/V4 here. Tear everything down. |

### Tests (stdlib unittest; each proved red by reverting its fix)

| File | Asserts |
|---|---|
| `test_agent_cli_parse.py` | `parse_version` on both formats and junk; the descriptors, including Auggie `["upgrade", "--skip-confirmation"]`; the extensions and base are `None`; base `running() == []`. |
| `test_claude_running.py` | pid-file filter: live/real procStart kept, dead excluded, wrong procStart excluded; the host mapping bg/parked/desktop/tui; only whitelisted keys read. |
| `test_agent_cli_jobs.py` | Uses a stub CLI on a temp PATH and a fake `aitracker.term_vt`. Cases: (a) update rc 1 → zero stops; (b) stop → open order, one at a time, open body has `prompt == RESUME_PROMPT`; (c) already-current skipped; (d) (tty, session) mismatch not stopped (F9); (e) `stoppable: False` never stopped; (f) preflight failure never stopped (F6); (g) unconfirmed stop not resumed (F6); (h) a second start → 409; tracker-update lock → 409 (F10); (i) bad agent/action/confirm → 400, request text never in argv; (j) verify uses a shared deadline and reports a version mismatch (F11); (k) a missing binary gives bytes `err` (N2); doctor/update cwd is HOME (N3). |
| `test_agent_cli_outside.py` | tui row → `resume_cmd`, with the OpenRouter launcher via `resume_cmd`; daemon row → the two-line command (F1); desktop row → `command None` (F4); an idle-but-running row is listed (F4); owned rows excluded; Auggie row → version unknown. |
| `test_term_vt_upgrade.py` | `_with_prompt` table, including control characters; the resume arm builds `[launcher, "--resume", sid, prompt]`; `upgrade_candidates` resolves an unknown id via the pid file (F7) and marks daemon / unresumable panes; `stop_for_upgrade` kills a work child in its own pgid (F2) and keeps the folder tty on a graceful exit; `call_route` returns `(code, obj)`. |
| `test_agent_routes.py` | GET 200 from loopback; 403 with a proxy header or a bad Host; POST 403 with a foreign Origin on `/api/agents/run` **and** on the existing `term_launch` route (F3); upgrade without confirm → 409 with "will be stopped", the prompt and the note; Auggie/empty messages (N5); doctor 202; tunnel read-only 403. |
| `test_agents_ui.py` | `'Agents'` in `sections`; both routes called; no server sentences in the JS; the poller is outside the dialog and toasts `job.summary` (F8); `node --check` when node is on PATH. |

**`_selfcheck()`** (`tests/test_selfcheck.py`, before line 1469): one assertion block covering Claude and Auggie:
- the descriptors' update argv;
- `parse_version` on both formats;
- `plan_upgrade` with stubbed candidates yields a message containing "will be stopped" and `RESUME_PROMPT`.

**Gate:** `unset TRACKER_AUTH; make check`, one module per process if it is OOM-killed. A commit runs the full gate, so give Bash a timeout over 6 minutes.

### Deliberately left out

- Pinning, rollback, scheduling and any config key.
- Touching the auto-updater.
- Stopping daemon-hosted or desktop sessions (they are listed with their command).
- Auggie stop/resume and Auggie doctor.
- An out-of-date chip on tiles.
- The classic UI.
- A job state file.
- `_with_prompt` for `mode=new` (that belongs to the sibling).

### Decisions for the user

1. **Daemon-hosted background sessions.** Default is show-only with `claude stop <job>` + `claude --resume <id>`, read as clause 4. The alternative, read as "Force all now", is that the tracker runs `claude stop` and then resumes them in a tracker pane. That moves each one out of the background into a pane, and only V6 tells us it works.
2. **Base.** Copy the small shared pieces from the sibling at `fe8f580` now (recommended), or wait for it to land.

## What I did NOT examine

- I did not run `make check`, `claude update`, `auggie upgrade` or `auggie --version`. No V-step was executed.
- I did not measure how Claude behaves on SIGTERM when busy and not parked (V5), or `claude stop` (V6). F2's orphan claim follows from the code's own pgid filter, not from a live run.
- `scripts/bundle.py` import stripping, the `ext_cr_dialogs.css` needs, and the classic UI.
- The auth-cookie path in `do_POST` ahead of the routes.
- `term_launch.open_terminal` (the second `_local_caller` caller), beyond confirming that it calls it.
- The sibling branch beyond the specific hunks cited (`update.py:1-130`, `server.py:1-12,223-240`, `util.py:715-747`, `term_vt.py:2951-2959,3095-3140`, `ext_cr_dialogs.js:1124-1165`).
- Whether `open_pty`'s folder branch types into the idle shell after `stop_for_upgrade`, or peeks because of a stale `fg` claim. `_refresh_fg` should clear it (`term_vt.py:1877-1881`), but this needs the F2 test to prove it.
- Auggie session files (I accepted plan fact 5).
