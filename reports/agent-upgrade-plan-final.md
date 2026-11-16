# Agent CLI upgrade: Doctor and Upgrade for the agents the tracker manages — final plan

Plan v3 written 2026-11-16 by the opus plan agent; this final version folds in D8-D10, the later live results and
every accepted fix of the second review (`agent-upgrade-review-v3.md`, findings B1-B2, S1-S8, N1-N11). Branch
`agent-upgrade`, worktree `.claude/worktrees/agent-upgrade`, head `fe8f580` (fast-forwarded onto
`worktree-pending-work-worker`, D7). Every `file:line` below was re-read in THIS worktree at that head.
**Status: plan only. No code until the user agrees (rule 8).**

This file replaces plan v1, v2 and v3. An implementer needs only this file.

## 1. Contract

| # | Clause (verbatim) | Verdict |
|---|---|---|
| 1 | Scope — user: "1 [Agent CLI version] but majorly allows only to run 'claude doctor' or upgrade the claude code version, if any sessions are in flight, then notify the user that the following sessions : <list them the sessions> will be stopped, you might have to continue again with a prompt once the upgrade lands. this kind message is needed" | not discharged |
| 2 | Agents — user: "whatever this tracker manages, and whatever is possible" | not discharged |
| 3 | Busy sessions — user chose "Force all now": "4 with a message or warning" | not discharged |
| 4 | Sessions started outside the dashboard — user chose "Show only": list them as out-of-date with the command to run; the tracker does not touch them. | not discharged |
| 5 | Target version — "Always latest": the button runs `claude update`. No version number in config. | not discharged |
| 6 | After upgrade — user: "3 [Resume and auto-continue] with 'continue, re-read claude.md' prompt itself, notify the user about that as well" | not discharged |
| 7 | Trigger — "Manual button only". | not discharged |
| 8 | Claude Code's own background auto-update — tracker leaves it alone; user: "Give that message to the user, as a note" (i.e. the UI shows a note that Claude Code also auto-updates itself in the background). | not discharged |
| D5 | Tracker panes showing a daemon-hosted background session — "Tracker stops and resumes them": the tracker runs `claude stop <job>` then resumes in a tracker pane. Gated on V6 passing on a scratch background session; if V6 fails, show-only with the two commands. Background sessions with NO tracker pane stay show-only (clause 4). | not discharged |
| D6 | Who gets "continue, re-read CLAUDE.md" — "Only busy ones": prompt only for sessions busy at stop (work children, or waiting on a permission prompt — M3). Idle ones are resumed and left waiting. The notification says which got the prompt. | not discharged |
| D7 | Base — "Build on top of it now": branch `agent-upgrade` is based on `worktree-pending-work-worker`. No copies; use its `_local_caller`, `origin_matches_host`, `_with_prompt`, `update._run`/`_APPLY` and UI helpers directly. Lands after that branch. | not discharged |
| D8 | CLI already latest, but sessions run an older version — "Restart the old sessions": Upgrade always ends with stop-and-resume of every tracker session whose running version differs from the installed one, whether or not anything was installed. Same warning first. | not discharged |
| D9 | Scratch tests for V5 and V6 — "Yes, go ahead": accept the trust prompt for the test's own empty scratch folder only; one scratch session, one scratch background job; torn down after. | V6 stop part done; rest at S0 |
| D10 | Auggie — "Include, test once for real": Auggie gets Upgrade (`auggie upgrade --skip-confirmation`); run once for real to verify no-terminal behaviour. | live test done (§3); feature not discharged |

How the clauses are read:
- Clause 6's prompt is the literal `continue, re-read CLAUDE.md`. The file is named `CLAUDE.md` (N4).
- Clause 3 together with D2 and D5: every tracker pane whose foreground is a Claude session gets stopped and resumed,
  busy ones included. The exceptions are:
  - a session already on the new version once the update finishes;
  - a pane whose session id stays unknown even after the pid-file lookup (F7);
  - a pane that fails a resume precondition (F6). Stopping it would lose it.
- Clause 4: anything **not running in a tracker pane** is show-only. That covers terminal sessions elsewhere, background
  sessions with no tracker pane, and Claude desktop-app sessions.
- D8: "differs" needs a known version. A session whose version is unknown (no pid file) is restarted only when the
  update actually changed the installed version; with nothing installed it is listed, not stopped. A failed update
  (rc ≠ 0, timeout, unreadable version) still stops nothing (§9).
- D5 on this machine is the **main** path, not an edge case: the live pid files show only background (`bg`) jobs and
  desktop sessions, and a tracker resume of a daemon-hosted id becomes a `claude attach <short>` thin client
  (`term_vt.py:3352-3358`). Restarting one moves the session out of the daemon into a terminal session in a tracker
  pane, which from then on ends when the tracker stops. The warning says so (§6 `AGENT_STATE_DAEMON_MOVE`).
- **The agent view (Consequence 4).** On this machine a bare `claude` under a pty opens Claude's agent-view TUI, and
  a prompt typed there becomes a background job (reconcile V5 row; `docs/folder-terminal-reuse-plan.md:606`). This
  feature never opens `mode: "new"` (whose argv is a bare `[launcher]`, `term_vt.py:3125`). Every restart opens
  `mode: "resume"`, whose argv is `[launcher, "--resume", <id>]` (`term_gate.py:300`, built at `term_vt.py:3118`) plus
  the prompt for a busy session, typed into the folder shell by `_inject_argv` (`term_vt.py:1953`) or exec'd in an
  overflow pty (`term_vt.py:3318`). It names a session, so it does not open the bare agent view. Two ways it can
  still land somewhere other than an interactive session on the new binary: (a) if the daemon still hosts the id,
  the CLI turns `--resume` into `claude attach <short>` on the old worker, and the backstop's `_retry_with_attach`
  (`term_vt.py:2862-2863`) does the same — prevented by confirming the worker's death first (§5.4 daemon path step
  4), and reported by verify as a version mismatch if it still happens; (b) whether `claude --resume <id> "<prompt>"`
  stays interactive on 2.1.325 with this config is measured at S0 (V2r requires `kind == "interactive"`).
- **Which session a pane runs.** For a pane whose foreground Claude has a live, procStart-verified pid file with
  `host == "tui"`, that file's `sessionId` is the session — not the pane's label, which is set once at open and never
  follows `/clear` or `/resume` typed inside Claude (`term_vt.py:1991-1992, 3990-3997`). The label is used only when
  there is no pid file (thin clients, parked panes resolve through the daemon).

## 2. What changed from v2 (and why)

1. **No copied helpers (D7).** These already exist and are called directly:
   - `util.origin_matches_host` and `util.is_loopback_host` (`util.py:715-747`);
   - `_local_caller` with its Origin check (`server.py:223-240`);
   - `term_vt._with_prompt` (`term_vt.py:2951-2959`);
   - `update._run` and `update._APPLY` (`update.py:27,62-80`);
   - `crReadOnly`, `crCall` and `crBtn` (`ext_cr_dialogs.js:1139-1160`).

   v2's `util` append, its `_local_caller` replacement, its JS copies and its private `agent_cli._run` are all dropped.
2. **D5 replaces v2 decision 1.** A tracker pane that shows a daemon-hosted session is restarted with
   `claude stop <short>` followed by a resume in the pane. V6 has PASSED for the stop (§3), so this path is built
   (S5); only its pane half, V6d, is still measured at S0 before S5 lands. Background sessions with no tracker pane
   stay show-only.
3. **D6/M1/M3: the prompt goes only to sessions that were busy when stopped.** "Busy" means:
   - work children, or
   - a pid-file `status` that is any non-empty string other than `idle` — `busy`, `waiting` (a permission prompt
     or a question), `shell` (measured: a job running a shell command), or any value not seen yet. No allow-list
     (Consequence 2), or
   - when no pid-file status exists, a transcript-tail fallback.

   Idle sessions are resumed with no prompt. The summary names who got the prompt, who did not, and who failed.
4. **F10 is now a direct two-sided lock check, with the edits in `update.py` named exactly (§5.2).** Both locks live
   in `update.py`, which avoids an import cycle (§9, item 1).
5. **F8 is cut down.** It keeps only the module-level poller, the toast and the server log line. There is no page-load
   catch-up and no `sessionStorage`.
6. **Three defects that v1 and v2 both missed are fixed here:**
   - **M4, bundle name collisions.** `scripts/bundle.py` flattens every bundled module into one namespace. v2's
     `agent_cli.status()` and `start()` would shadow `tunnel.status`/`tunnel.start` (`tunnel.py:181,309`), and its
     `_run` would shadow `update._run`. The existing `tests/test_integration.py:1751-1763` already asserts exactly one
     `def status` and one `_run`. Fix: every module-level name in `agent_cli.py` starts with `agent_`, `_agent_` or
     `AGENT_`, and it reuses `update._run`.
   - **M5, the internal route call would be refused.** `term_gate.guard` now refuses a request with no loopback Host
     when `TRACKER_AUTH` is unset (`term_gate.py:69-71`). With v2's `_Internal.headers = {}`, every internal
     `open_pty` call would answer 403. Fix: `headers = {"Host": "127.0.0.1"}`.
   - **M6, a stale `fg` claim after a graceful stop.** If `pt.fg` still names the session after its Claude exited,
     `open_pty` would take the "already running THAT session, peek" branch (`term_vt.py:3052-3053`, `_session_pty`) and
     type nothing. Fix: `stop_for_upgrade` refreshes `fg` under `_LOCK` and counts the stop as confirmed only when the
     claim is gone.
7. **The stop path no longer goes through `close_pty`.**
   - `close_pty` enforces `_pty_owned` (`term_vt.py:3814`), and that check rejects F7's resolved id on a hand-typed
     `claude` pane.
   - It also kills the folder shell, which loses the tty.
   - Instead, `stop_for_upgrade` checks the pane's identity by its foreground Claude **pid**, which is stronger than
     the id. It sends SIGTERM, then escalates to SIGKILL of that Claude's group only, so the shell and its tty survive.
8. **Outside rows come from the live pid files.** Title, cwd and model are read per session. There is no join against
   the 200-row `all_sessions()`, so a running session missing from that list is still shown.
9. **Final-review fixes** (`agent-upgrade-review-v3.md`): S0 never starts a bare `claude` (B1); the pid file's session
   id beats a stale pane label (B2); busy = anything but idle (S1); D8 is explicit in the warning and the flow (S2);
   D5 is built and its host change is stated (S3); the job is snapshotted under a lock with a fixed item schema
   (S4); the orphan sweep checks start times (S5); the daemon stop is confirmed on the worker's own pids (S6); a
   terminal slot is preflighted and duplicate panes are deduped (S7); S0 stays inside D9's scope (S8); plus N1-N11.
   Cut: `daemon_job_short` (the pid file already carries the short), the non-existent CSS rule, V6 step 5.

## 3. Live-check results, folded in

| Check | Result | What it means for the plan |
|---|---|---|
| V1 `claude update` with no terminal | **PASS** (no-op): exit 0 in 3.0 s, no prompt, "Claude Code is up to date (2.1.325)" | Argv `[claude, "update"]` with stdin closed is safe. A real update is still proved at S9. |
| `claude doctor` with no terminal | **PASS**: exit 0 in 1.4 s, 673 bytes | `AGENT_DOCTOR_TIMEOUT = 60` is generous. |
| V2 transcript `version` field | **PASS**: top-level on user/assistant/system lines | Not used. The pid file is the version oracle. |
| V2-resume: resume lands on the NEW binary | **UNPROVEN** | Still to verify (V2r, §4). |
| V3 `~/.claude/sessions/<pid>.json` | **PASS**. Fields include `pid, procStart, sessionId, version, kind, entrypoint, jobId, cwd, status`. No file is written while a session sits at the trust prompt. | Basis of `running_sessions()`. A pane with no pid file gets a version of "" and is treated as needing a restart. |
| V4/V5 SIGTERM on a busy interactive session | **NOT RUN** twice. At the trust prompt SIGTERM exited in 0.82 s (code 143). The second try hit the agent view: a bare `claude` under a pty opens the agent-view TUI, a typed prompt dispatches a background job, no interactive pid file appeared; SIGTERM to that client group exited 143 in 1.45 s. The trust prompt defaults to "No, exit". | Still to verify (V5), on a session opened with `--resume` (§4). |
| V6 `claude stop <short>` + resume (D9 scratch job) | **PASS for the stop; resume proved via `-p`, not in a pane.** `claude --bg "<prompt>"` starts a job; its pid file has `kind=bg, jobId=<short>, version, status=idle`. `claude stop <short>` works; the FULL session id is rejected ("No job matching"). Stop ~2 s; the worker exits within 4 s; its pid file is removed; a busy job's `sleep 300` child died with it. `claude -p --resume <session id> "…"` then succeeded (~14 s) with new lines on the installed version. One "Hook cancelled" SessionEnd warning. | `claude stop` takes only the short id. S5 is built. V6d (the pane half) stays in S0 and gates S5 landing. Per `docs/folder-terminal-reuse-plan.md:542`, `claude stop` does NOT kill a job's `run_in_background` tool (it orphans to ppid 1): the sweep covers it. |
| V7 is "waiting on a permission prompt" detectable | **NOT RUN.** `status` values seen so far: `idle`, `busy`, `waiting` (with `waitingFor: "input needed"`), `shell` (while a job's shell command ran). | Busy = any status but `idle` (S1). V7 still measured at S0. |
| D10 `auggie upgrade --skip-confirmation`, no terminal | **PASS**: exit 0 in 28.4 s, no prompt, 0.36.0 → 0.37.1. `auggie --version` takes 3.6 s, format `0.37.1 (commit …)`. npm global install under the Homebrew node prefix. Only flags: `--skip-confirmation`, `--help`; alias `update`. 4 running auggie processes were untouched. The "already up to date" exit code was NOT measured. | Argv confirmed. Auggie is now on the latest version, so the S9 product run is a no-op that records that rc (V9). Before/after `--version` is the oracle, never the rc alone. |
| Side effect | One trust entry for the removed scratch path remains in `~/.claude.json` (not edited). | List it in the S0 teardown report too. |

Read during planning (key names and the three enum fields only; no other values):
- Today 10 pid files are live:
  - 4 `interactive`/`claude-desktop` on 2.1.321, all `status: idle`;
  - 1 `interactive`/`cli` on 2.1.325, `busy`;
  - 5 `bg` on 2.1.323/2.1.325, `busy` ×4 and `waiting` ×1. The `waiting` one also carries `waitingFor: "input needed"`.
- Re-read at the final review (enum fields only): 6 `bg` (2.1.323/2.1.325; `busy` ×5, `shell` ×1) and 4
  `interactive`/`claude-desktop` on 2.1.321, **no interactive CLI TUI** — so tracker panes here mostly show daemon
  thin clients (D5 is the main path).
- Installed: `~/.local/bin/claude` → `~/.local/share/claude/versions/2.1.325`.
- Retained old binaries: `2.1.321`, `2.1.322`, `2.1.323` (listed at the final review). V2r can therefore be proved
  **now**, without waiting for a release. Two caveats: run V2r before any real `claude update` (an update may prune
  old versions), and run the old binary with `DISABLE_AUTOUPDATER=1` in that one test command's environment so the
  test cannot start an install (`autoUpdatesChannel` is set in `~/.claude/settings.json`). The product never sets it
  (clause 8).

## 4. Verify before relying (S0)

The implementer runs these before S1, in this order, and writes each result into §13 of this file. They stay inside
D9's approval: **one scratch session (reused by V2r → V3b → V7 → V5) and one scratch background job (V6d)**.

**Safe-scratch protocol, used by every V-step:**
- Test server on a spare port: `PORT=8799 TRACKER_NO_BROWSER=1 python -m aitracker`, started in the background from
  this worktree. Record its PID. Stop it with `kill <PID>`. **Never `pkill -f aitracker`**: that kills the user's
  live dashboard.
- Scratch folder: `mktemp -d /tmp/agent-upgrade-v.XXXX`. Accept Claude's trust-folder prompt for that folder only,
  once, when the first interactive resume shows it (it defaults to "No, exit": press the key that selects "Yes",
  confirmed on screen first). This leaves one trusted-folder entry for that `/tmp` path; list it in the teardown
  report, next to the one the earlier live check left.
- **Never start a bare `claude` (or a bare old binary) in a pane.** On this machine it opens the agent view and a
  typed prompt becomes a background job (§1). Sessions are created with `-p` and opened with `--resume`, which is the
  product's own argv. Never type into a pane before its screen is confirmed.
- Record the one session id and the one job short. Teardown touches **only** those:
  - `claude stop <short>` for the job;
  - close the panes (POST `/api/term/close` with `force: true`);
  - delete `~/.claude/projects/<scratch-slug>/<id>.jsonl` (and the job's, if it wrote one) for the recorded ids only;
  - `rm -rf` the scratch folder;
  - stop the test server by PID.
- Read only key names plus `pid`, `sessionId`, `status`, `version`, `kind`, `parkedJobId` and `waitingFor` from pid
  files. Never print transcript content beyond the one prompt line being checked.

**The steps:**

- **V2r. A resume runs the installed binary, as an interactive session, on a transcript an older version wrote.**
  1. `cd <scratch> && DISABLE_AUTOUPDATER=1 ~/.local/share/claude/versions/2.1.323 -p "say ok" --output-format json`.
     Record only `session_id` (= `<id>`). Confirm its transcript lines carry `version` 2.1.323.
  2. Open a tracker folder pane on `<scratch>` (POST `/api/term/pty {cwd, mode: "cwd"}`) and type exactly
     `claude --resume <id> 'continue, re-read CLAUDE.md'` at its prompt (what `shlex.join` produces).
  3. **Pass needs all of:** a pid file with `sessionId == <id>`, `kind == "interactive"`, no `parkedJobId`,
     `version == 2.1.325`; its `pid` is the pane's foreground pgid; the transcript gains a `"type":"user"` line
     containing the prompt; the pane shows the conversation, not the agent view.
  4. **If it fails:** stop and resume are disabled. Upgrade only updates, and every session is listed "restart it
     yourself" with its command. Go back to the user before building S3-S5.
  5. **Runtime guard either way:** `_agent_verify` reports "resumed on vX, expected vY" from the pid file. Nothing
     assumes the version.
- **V3b. Does the pid file follow `/clear`?** In the V2r pane, at the idle prompt, type `/clear` and Enter. Read the
  pid file's `sessionId`. Record "follows" or "does not follow". The design (B2: pid file beats label) stands either
  way; "does not follow" adds the README gap in §12.
- **V7. How "waiting on a permission prompt" shows up (M3).**
  1. Exit the pane's Claude (`/exit`), then type `claude --resume <id> --permission-mode default` and ask it to run
     `ls` with the Bash tool. It stops at the permission prompt.
  2. Read the pid file's `status` and `waitingFor`.
  3. Read the transcript tail with `_tail_scan`: is the assistant `tool_use` line already written with no
     `tool_result` after it (`last == "assistant_tool"`)?
  4. Repeat once while plainly idle (answer "No" to the prompt, wait for the idle prompt).
  5. **Outcomes:**
     - `status` is anything but `idle` at the permission prompt: the design stands (busy = not idle).
     - `status` stays `idle` at the permission prompt: `claude.session_state` also returns `"waiting"` when the pid
       file says `idle` but the tail's `last == "assistant_tool"`. One extra condition in that one function (§5.1).
     - Neither signal shows it: say so in §13. Such a session is resumed with no prompt, and the summary lists it under
       "resumed without a prompt". This is a known gap, stated in the README.
- **V5. SIGTERM on a busy interactive Claude.**
  1. Exit again, then type `claude --resume <id> --allowedTools "Bash(sleep:*)"` and ask it to run `sleep 300` with
     the Bash tool.
  2. While it runs, send SIGTERM to the Claude's process group (the pane's foreground pgid).
  3. Measure:
     - the exit time, against the 8 s `PARKED_DETACH_WAIT`;
     - whether `sleep 300` survives (`ps -o pid,ppid,pgid -p <sleep pid>`);
     - whether every line of the transcript tail still parses as JSON;
     - whether the pid file is removed;
     - whether the folder shell is back at its prompt with the same tty.
  4. **What the runtime does if the assumption is false:**
     - No exit within 8 s: SIGKILL of that Claude's group.
     - `sleep` survives: the orphan sweep kills it (start-time checked, §5.3).
     - The transcript tail is corrupt: the resume may fail. It is reported as failed with its command, and **that one
       result goes back to the user before S3 lands.**
- **V6d. The pane half of V6 (gates S5 landing).** V6's stop half has passed (§3).
  1. `cd <scratch> && claude --bg "say ok"`; record the job short from its pid file (`jobId`) and the session id.
  2. Open it in a tracker pane through the product route: POST `/api/term/pty {session: <job session id>, mode:
     "resume"}`. Expect a `claude attach <short>` thin client (record what the pane shows).
  3. Record the worker's `pid`/`replPid` from `~/.claude/daemon/roster.json` (read only those two and `sessionId`).
     Run `claude stop <short>` from a plain shell with stdin `</dev/null`.
  4. **Pass needs all of:**
     - (c) within 8 s both recorded worker pids are gone, and the pane's client returns to its shell prompt by itself
       or after one SIGTERM to its group;
     - (d) `claude --resume <job session id> 'continue, re-read CLAUDE.md'` typed in the pane opens the conversation
       with no "running as a background session" refusal, and its pid file has `kind == "interactive"`, no
       `parkedJobId`, `version == installed`, and the prompt line lands in the transcript.
  5. **If V6d fails:** S5 does not land and `AGENT_RESTART_DAEMON = False`. Tracker panes that show a daemon session
     go to `cannot_stop` with `AGENT_REASON_DAEMON` and the two commands `claude stop <short>` /
     `claude --resume <id>`.
- **V8. `claude doctor` under `update._run` with `cwd=~`.** It must exit 0, and its output must not name the tracker
  checkout's settings.

Real `claude update` and `auggie upgrade --skip-confirmation` are run **once each, with the user's OK**, at S9 (V9:
record Auggie's rc when it is already on the latest version).

## 5. Files to add or change

### 5.1 Providers and registry (S1)

**`aitracker/providers/base.py`, class `Provider`:**
```python
agent_cli = None          # optional {id,label,bin,version,doctor,update,update_timeout,restarts_sessions}
def running(self):        # live agent processes: [{id,pid,version,kind,entrypoint,job,host,state,status_raw,cwd,title,model}]
    return []
```

**`aitracker/providers/claude.py`.** All of the following are module-level functions, placed next to
`parked_job_id` (`claude.py:637-664`), except where noted.

- `running_sessions() -> list[dict]`. Never raises.
  - For each `config.LIVE_SESSIONS_DIR/*.json` (`config.py:82`), read **only** these keys:
    `pid, procStart, sessionId, kind, entrypoint, jobId, parkedJobId, version, status, cwd`.
  - Keep an entry only when `type(pid) is int`, `_pid_alive(pid)` holds (`claude.py:562`), and
    `" ".join(procStart.split()) == _ps_lstart(pid)` (`claude.py:611`). This is the same fail-closed check as
    `parked_job_id` at `claude.py:655-657`.
  - Emit:
    - `id = sessionId` and `pid`;
    - `version` (str or "");
    - `kind` and `entrypoint`;
    - `job = jobId or parkedJobId or ""`, kept only if it matches `re.fullmatch(r"[0-9a-f]{4,64}", job)`;
    - `host`:
      - `"daemon"` if `kind == "bg"` or `parkedJobId` is set;
      - `"desktop"` if `entrypoint == "claude-desktop"`;
      - else `"tui"`;
    - `state = session_state(sessionId, status)`, and `status_raw` = the file's `status` when it is a str, else None;
    - `cwd` from the file;
    - `title = session_label(sessionId)` (`claude.py:708`);
    - `model = _session_meta(find_session(sessionId))["model"]` when the transcript exists, else "".
- `session_state(sid, status=None) -> "busy" | "waiting" | "idle" | ""`. This is **the** busy signal, decided in one
  place.
  - If `status` is a non-empty string: return `"idle"` for `idle`, `"waiting"` for `waiting`, and `"busy"` for
    **anything else** (`busy`, `shell`, any unseen value — Consequence 2; no allow-list).
  - Otherwise, the transcript fallback. First `path = find_session(sid)`; if it is None return `""` (`_tail_scan(None)`
    raises `TypeError` outside its `except OSError`, `claude.py:151-152`). Then `t = _tail_scan(path)`:
    - `t["waiting"]` true → `"waiting"`;
    - `t["last"]` in `("assistant_tool", "tool_result", "user_prompt")` → `"busy"`;
    - a transcript exists → `"idle"`;
    - else `""`.
  - V7-fail branch only: also return `"waiting"` when `status == "idle"` and `t["last"] == "assistant_tool"`.
- `_tail_scan` (`claude.py:89-236`): add `"last": last` to the returned dict (`claude.py:234`). That is one key, read
  from the existing local. No new I/O.
- (Cut: `daemon_job_short`. The bg worker's pid file already carries the short as `jobId`, which `running_sessions()`
  emits as `job`; callers take `job` from the `kind == "bg"` entry.)
- `transcript_size(sid) -> int`. `os.path.getsize(find_session(sid))`, or 0 when there is none. Never raises.
- `user_line_has(sid, text, since=0) -> bool`. True when any line **after byte offset `since`** (at most the last 96 KB)
  contains both `"type":"user"` and `json.dumps(text)[1:-1]`. The caller passes the size recorded just before the
  resume, so an identical prompt line from an earlier upgrade never counts. A raw substring check, like
  `_CONTINUED_MARK`. Never raises.
- On `ClaudeProvider` (`claude.py:2205`):
  ```python
  agent_cli = {"id": "claude", "label": "Claude Code", "bin": "claude",
               "version": ["--version"], "doctor": ["doctor"], "update": ["update"],
               "update_timeout": 600, "restarts_sessions": True}
  def running(self): return running_sessions()
  ```

**`aitracker/providers/auggie.py`, `AuggieProvider` (`auggie.py:938`):**
```python
agent_cli = {"id": "auggie", "label": "Auggie", "bin": "auggie",
             "version": ["--version"], "doctor": None, "update": ["upgrade", "--skip-confirmation"],
             "update_timeout": 300, "restarts_sessions": False}
```
`running()` stays the default `[]`. Auggie has no process registry; this is a known gap.

**`aitracker/providers/augment_ext.py`:** unchanged (`agent_cli = None`).

**`aitracker/registry.py`.** Extract the inline logic at `registry.py:283-287` into:
```python
def resume_cmd(sid, model):
    """`claude --resume <sid>` for a Claude session, through the OpenRouter launcher when its model ran there;
    None when that launcher is not configured."""
    if gateway_of(model) == "openrouter":
        lau, _err = or_launcher()
        return (shlex.quote(lau) + " --resume " + sid) if lau else None
    return "claude --resume " + sid
```
`parse_any` sets `meta["resume_cmd"] = resume_cmd(sid, meta.get("model"))` inside the existing `p.prefix == ""` branch.
The behaviour is identical: `meta["gateway"]` is `gateway_of(model)` through `model_meta` (`gateway.py:78-83`). The
existing selfcheck assertions on `resume_cmd` (`tests/test_selfcheck.py:~1465-1469`) guard the refactor.

### 5.2 `aitracker/update.py`: the exact edits (S2)

1. Next to `_APPLY` (`update.py:27`), add:
   ```python
   _AGENT_JOB_LOCK = threading.Lock()   # held by agent_cli for a whole Doctor/Upgrade job; update_apply refuses while held
   ```
2. `_run` (`update.py:62`). Change the signature to `def _run(argv, timeout, env=None, cwd=None):` and pass `cwd=cwd`
   to `subprocess.Popen`. Nothing else changes, and every existing caller passes no `cwd`.
3. `update_apply` (`update.py:266-267`). Right after `if not _APPLY.acquire(blocking=False): return 409, …`, insert:
   ```python
   if _AGENT_JOB_LOCK.locked():
       _APPLY.release()
       return 409, {"error": "an agent upgrade is running — try again when it finishes"}
   ```

The other side, in `agent_cli.agent_start`, acquires `_AGENT_JOB_LOCK` first and then refuses if `_APPLY.locked()`.
Each side takes its own lock and then checks the other's, so they can never both proceed.

### 5.3 `aitracker/term_vt.py` (Claude terminal tier; not bundled) (S3)

**Resume arm of `open_pty` (`term_vt.py:3116-3121`).** After the `try: argv = term_gate.resume_argv(sid) …` block and
before `forked = …`, add:
```python
argv = _with_prompt(argv, body.get("prompt"))     # agent upgrade resumes a busy session with its prompt
```
Change the docstring of `_with_prompt` (`term_vt.py:2952`) from "the optional `mode=new` body `prompt`" to "the
optional `mode=new`/`mode=resume` body `prompt`". The helper body is unchanged.

Known limit: the `--fork-session` backstop retry rebuilds argv from `resume_argv` (`term_vt.py:2449`) and drops the
prompt. Verify then reports the session as not on the new version, or `prompt_seen: false`.

**New `upgrade_candidates() -> list[dict]`**, placed next to `_claude_busy` (`term_vt.py:3963`). It forks `ps`, so it
is never called under `_LOCK`. Never raises.
1. Take a snapshot under `_LOCK`: `_reap()` (`term_vt.py:2212`), then
   `panes = [p for p in PTYS.values() if not p.done and not p.closing]`, then `_refresh_fg(p)` (`term_vt.py:1852`) for
   each folder pane.
2. `c = _provider()` (`term_vt.py:3369`); `run = {r["pid"]: r for r in c.running_sessions()}` if `c` else `{}`;
   `orl = gateway.or_launcher()[0]`.
3. For each pane where `_foreground_is_claude(p.fd)` (`term_vt.py:4030`):
   - `pg = _fg_pgid(p) if p.folder else p.pid` (`term_vt.py:1838`);
   - `label = (_pty_session_ids(p) or ("",))[0]` (`term_vt.py:3982`). `e = run.get(pg)`.
     **`sid = e["id"] if e and e["host"] == "tui" else label`** (B2: a live, procStart-verified interactive pid file
     beats the label, which never follows `/clear` or `/resume` typed inside Claude; this also covers F7, a
     hand-typed `claude` with no label). `relabelled = label if (label and sid != label) else ""`.
     `_pty_session_ids` itself is not changed (the idle reap uses it).
   - `bg = _background_target(sid) if sid else ""` (`term_vt.py:3377`). `daemon = bool(bg)`.
     `thin = bool(_thin_client_short(pg))` (`term_vt.py:3388`).
   - `target = bg or sid`. `entry` is the `run` entry with `id == bg and kind == "bg"` when `daemon`, else `e`.
     `version = entry["version"] if entry else ""`. `short = entry["job"] if daemon and entry else ""` (the worker's
     `jobId`, the short id `claude stop` takes — V6).
   - `cwd_to = term_gate.session_cwd(target, resume=True)`;
     `needs_slot = not any(q.folder and q.cwd == cwd_to for q in panes)` (S7: the resume opens in the folder shell for
     the SESSION's cwd, `term_vt.py:3099-3100, 3157`, which may not be this pane — e.g. the session moved into a
     worktree — and a new shell needs a free slot, `term_vt.py:3161-3170`).
   - `stoppable` and `reason`, checked in this order. The first failure sets `stoppable = False` with that reason:

     | Check | Reason |
     |---|---|
     | `not sid` | "the tracker cannot tell which session this terminal runs (for example Claude's agent view)" |
     | `not term_gate.allowed()` | "terminals are disabled here (TRACKER_TERMINAL=0, or a network bind without TRACKER_AUTH)" |
     | `term_gate.resume_argv(target)` raises `gateway.GatewayError` as `err` | `str(err)` |
     | `not cwd_to` | "its folder no longer exists" |
     | `daemon and not re.fullmatch(r"[0-9a-f]{4,64}", short)` | "could not find its background job" |

   - **Dedupe (S7).** After the loop, keep only the first candidate per `target` (PTYS order). Each later one becomes
     `stoppable: False`, reason `AGENT_REASON_DUP % first["tty"]` ("the same session as terminal %s; restarted
     there").

   - `command`: when `daemon`, `["claude stop " + short, "claude --resume " + bg]`. Otherwise
     `[shlex.join(term_gate.resume_argv(target))]`, or `[]` when `resume_argv` raised.
   - Emit:
     ```python
     {"tty": p.id, "session": sid, "relabelled": relabelled, "target": target, "pid": pg, "version": version,
      "status": (entry or {}).get("status_raw"), "cwd": p.cwd, "title": _term_title(p, orl),
      "cols": p.screen.cols if p.screen else DEFAULT_COLS, "rows": p.screen.rows if p.screen else DEFAULT_ROWS,
      "folder": p.folder, "thin": thin, "daemon": daemon, "job_short": short, "needs_slot": needs_slot,
      "stoppable": stoppable, "reason": reason, "command": command}
     ```
     `status_raw` is the pid file's own `status` string, which `running_sessions()` also emits (add it to the §5.1
     emit list next to `state`); it is what `session_state(target, status)` is called with at stop time.
   - When `relabelled` is set, the warning row (§5.6) shows "now runs <title> (the terminal was opened on
     <label[:8]>)".

**New `stop_for_upgrade(tty, sid, pid, thin=False) -> dict`**, placed next to `_swap_in` (`term_vt.py:3461`). It
returns `{"stopped", "graceful", "confirmed", "work_children", "orphans_killed", "error"}` and never raises.
1. **Under `_LOCK`:**
   - `_reap()`, then `pt = PTYS.get(tty)`.
   - If `pt` is None, `pt.done` or `pt.closing`, return `error: "its terminal closed"`.
   - Run `_refresh_fg(pt)`, then `pg = _fg_pgid(pt) if pt.folder else pt.pid`.
   - If `pt.folder and pg == pt.pid`, the pane is already at its prompt; `already = True`.
   - Else, if `pg != pid`, return `error: "a different program is now running in that terminal"`. Nothing is
     signalled (F9, by pid).
   - Refuse `pg <= 0` and `pg == os.getpgrp()`.
2. **Outside the lock:** `kids = _agent_kids(pg)`; `[]` if `already`. `_agent_kids(pid)` returns
   `[(k, _ps_lstart(k)) for k in _claude_work_children(pid)]` (`term_vt.py:3933`, non-strict; `_ps_lstart` from the
   provider module, `claude.py:611`) — the start time is captured now so the sweep can never signal a recycled pid
   (S5).
3. If not `already`, `os.killpg(pg, SIGTERM)`, ignoring `OSError`.
4. Wait up to `PARKED_DETACH_WAIT` (8 s, `term_vt.py:3361`):
   - a folder pane: `_folder_wait_prompt(pt, PARKED_DETACH_WAIT)` (`term_vt.py:1902`);
   - a dedicated pane: poll `pt.done` every `BACKSTOP_POLL`.

   `graceful` is the result.
5. If not graceful, `os.killpg(pg, SIGKILL)`, with the same guards as `Pty.kill` (`term_vt.py:1563-1568`): `pg > 0`,
   `pg != pt.pid` for a folder pane, and `pg != os.getpgrp()`. Then wait again, up to `CLOSE_CONFIRM_WAIT`
   (`term_vt.py:1282`). The folder shell and its tty are kept; a dedicated pane simply ends.
6. `confirmed` requires all of:
   - `os.kill(pid, 0)` raises `ProcessLookupError`;
   - a folder pane, after `with _LOCK: _refresh_fg(pt)`, has `pt.fg is None`, so the claim is gone (M6).
     `_refresh_fg` clears it once the prompt is back after a latched child (`term_vt.py:1874-1881`);
   - a dedicated pane has `pt.done`.
7. If `thin` and graceful, feed `_TERM_MODE_RESET` the way `_swap_in` does (`term_vt.py:3495-3498`).
8. **Orphan sweep: `orphans_killed = _agent_sweep(kids, pt.pid)`.** For each `(k, lstart)`: skip unless
   `lstart` is non-empty and `_ps_lstart(k) == lstart` (same process, not a recycled pid); take `g = os.getpgid(k)`
   (skip on `OSError`) and skip `g in (0, os.getpgrp(), shell_pid)`. Send `killpg(g, SIGTERM)`; after 2 s,
   re-check the start time and SIGKILL any survivor. Return the count. This also stops `run_in_background` shells
   the session started (a dev server, say); the warning says so (§6). The same helper is used by the daemon path
   (§5.4), with `shell_pid` = the pane's shell pid.
9. Return `work_children = len(kids)`.

**New `call_route(fn, body) -> (code, obj)`** with a stand-in handler:
```python
class _Internal:
    headers = {"Host": "127.0.0.1"}   # term_gate.guard's loopback-Host check (term_gate.py:69-71); no Origin = same-origin
    def __init__(self): self.reply = (500, {"error": "no reply"})
    def _json(self, obj, code=200, headers=None): self.reply = (code, obj)
def call_route(fn, body):
    h = _Internal(); fn(h, None, body); return h.reply
```
`open_pty` and `close_pty` use only `handler._json` and `handler.headers`; this was checked by grep. `TRACKER_TERMINAL=0`
and a network bind without AUTH are still refused (`term_gate.py:56-61`). That is correct, and the preflight already
excludes those cases.

### 5.4 `aitracker/agent_cli.py` (new, bundled; ~350 lines) (S4, plus S5)

**Imports.** Top-level only and no aliases, because `scripts/bundle.py` strips import lines:
```python
import json, os, re, shutil, sys, threading, time
from . import config
from .update import _run, _APPLY, _AGENT_JOB_LOCK
from .pending import _pending_lock
from .registry import PROVIDERS, all_sessions, resume_cmd
from .providers.claude import session_state, user_line_has, transcript_size, _live_workers
```
- Importing private names follows the precedent at `pending.py:22`.
- `term_vt` is reached only through `tv = sys.modules.get("aitracker.term_vt")`. It is absent from the bundle, where
  `stop`/`cannot_stop` are `[]` and Upgrade only updates and lists outside sessions.
- **Every module-level name starts with `agent_`, `_agent_` or `AGENT_` (M4).** Note that `providers/claude.py`
  already uses that prefix for subagent helpers (`_agent_group`, `_agent_files`, `_agent_cache_on`,
  `_agent_file_pass`, `_agent_entry`, `agent_detail`, all flattened into the bundle): none of the names below may
  equal one of those, and the bundle test (§11) checks every new name generically.

**Constants:**
```python
AGENT_RESUME_PROMPT = "continue, re-read CLAUDE.md"
AGENT_VERSION_TIMEOUT, AGENT_DOCTOR_TIMEOUT, AGENT_STOP_TIMEOUT = 15, 60, 30
AGENT_VERSION_TTL = 60          # s a cached --version is trusted
AGENT_VERIFY_WAIT = 90          # s, ONE shared deadline for all resumed sessions
AGENT_OUTPUT_CAP = 8000         # chars of ANSI-stripped output kept on the job
AGENT_RESTART_DAEMON = False    # S4 value; S5 sets it True once V6d passed (V6's stop half already passed)
AGENT_DAEMON_STOP_WAIT = 8      # s for both recorded worker pids to be gone after `claude stop`
```
The text constants are listed in §6 (all server-written).

**Functions** (signatures):
```python
def agent_specs() -> list[dict]                 # PROVIDERS with agent_cli: dict(desc, provider=p, path=shutil.which(bin))
def agent_parse_version(text) -> str | None     # first r"\d+\.\d+\.\d+" on the first non-blank line
def agent_status() -> dict                      # GET /api/agents body; never runs a subprocess itself
def agent_plan_upgrade(agent_id) -> dict | None # the warning (409 needs_confirm body); None for an unknown agent
def agent_start(agent_id, action, confirm) -> (int, dict)   # 202 | 400 | 409
def agent_job_running() -> bool                 # _AGENT_JOB is not None and _AGENT_JOB["state"] == "running"
def _agent_version(spec) -> (str | None, str)   # runs `<bin> --version`; job/refresh threads only
def _agent_refresh_versions()                   # daemon thread "agent-versions", single flight via _AGENT_VLOCK
def _agent_message(names, restarts) -> str      # pure; §6
def _agent_was_busy(state, work_children) -> bool   # pure: work_children > 0 or state in ("busy", "waiting")
                                                # (session_state already maps every non-idle status to one of those)
def _agent_version_text(version, installed) -> str  # pure: AGENT_VER_OLD / _CURRENT / _UNKNOWN (§6, D8)
def _agent_item(cand, outcome, detail="") -> dict   # pure: a COMPLETE item (schema below)
def _agent_set(obj, **kw)                       # with _AGENT_JLOCK: obj.update(kw) — the only way a job/item is written
def _agent_snapshot() -> dict | None            # with _AGENT_JLOCK: json.loads(json.dumps(_AGENT_JOB))
def _agent_split(cands) -> (stop, cannot_stop)  # applies AGENT_RESTART_DAEMON to daemon candidates
def _agent_outside(spec, installed, owned_pids, owned_ids) -> list[dict]
def _agent_job_doctor(job, spec)
def _agent_job_upgrade(job, spec, confirm)
def _agent_restart_one(job, spec, cand, new)            # a TUI pane
def _agent_restart_daemon_pane(job, spec, cand, new)    # S5 only
def _agent_verify(job, new, deadline)
def _agent_strip(b) -> str                      # decode, strip ANSI (CSI/OSC regex), cap to AGENT_OUTPUT_CAP
```

**State:**
- `_AGENT_JOB = None`. The last job is kept in memory only, with no file.
- `_AGENT_JLOCK = threading.Lock()`. **Every** write to `_AGENT_JOB` or to an item goes through `_agent_set` (or an
  append under this lock); every read that leaves the module (GET body, 202 body) is `_agent_snapshot()`. Without it
  the 2 s poll's `json.dumps` can hit a dict gaining a key mid-iteration (`RuntimeError`) (S4).
- **Item schema — every key present from creation (`_agent_item`):**
  `{tty, session, target, title, daemon, outcome, detail: "", command: [...], tty_after: None, forked: False,
  on_version: None, prompt_seen: None, size_before: 0}`. `outcome` is one of `not_shown`, `current`, `failed`,
  `unconfirmed`, `prompted`, `unprompted`. Verify only updates existing keys.
- `_AGENT_VERSIONS = {}`, mapping each id to `{version, checked_at, error}`.
- `_AGENT_VLOCK = threading.Lock()`.
- `_AGENT_SEQ = 0`, the job id counter.

**`agent_status()`** returns:
```
{"agents": [{"id","label","path","installed","checked_at","checking","error",
             "can_doctor","can_upgrade","restarts_sessions","note"}], "job": _agent_snapshot()}
```
- The UI enables Upgrade only once `installed` is set (it shows "checking…" until then).
- `can_upgrade` is false with `error = "<bin> not found on the tracker's PATH"` when `path` is None.
- `note = AGENT_AUTO_UPDATE_NOTE` for Claude, else "".
- When any cached entry is older than `AGENT_VERSION_TTL`, it starts `_agent_refresh_versions` in a thread, unless one
  is already running, and reports `checking: true`.

**`agent_plan_upgrade(agent_id)`** returns:
```
{"needs_confirm": True, "agent", "installed", "message", "note", "stop": [...], "cannot_stop": [...], "outside": [...]}
```
- `installed` is the cached `_AGENT_VERSIONS[id]["version"]` (no subprocess in the request; None when not read
  yet).
- `cands = tv.upgrade_candidates() if tv else []`, split by `_agent_split`.
- `stop` holds the stoppable candidates. Each carries two server-written texts (§6):
  - `state_text` from `session_state(target, cand["status"])`: `AGENT_STATE_BUSY` / `_WAITING` / `_IDLE` /
    `_UNKNOWN`, plus `AGENT_STATE_DAEMON_MOVE` appended for a daemon candidate (S3);
  - `version_text = _agent_version_text(cand["version"], installed)` (D8): older than installed → "restarted even
    if nothing new is installed"; equal → "restarted only if a newer version installs"; unknown → the same as equal;
  - `relabelled_text = AGENT_RELABELLED % cand["relabelled"][:8]` when the candidate's `relabelled` is set (B2).
  For Auggie, `stop` and `cannot_stop` are `[]`.
- `outside = _agent_outside(spec, installed, {c["pid"] for c in cands}, {c["target"] for c in cands} | {c["session"] for c in cands})`.
- `message = _agent_message([c["title"] or c["session"][:8] for c in stop], spec["restarts_sessions"])`.

**`agent_start(agent_id, action, confirm)`:**
- **400** when:
  - `agent_id` is not a spec id ("unknown agent");
  - `action` is not `"doctor"`/`"upgrade"` ("action must be doctor or upgrade");
  - `action == "doctor"` and the spec has no doctor;
  - `confirm` is neither None nor a list of at most 64 `{tty: str, session: str}` dicts ("confirm must be a list of
    {tty, session}").
- **409** `{"error": "<bin> not found on the tracker's PATH"}` when `path` is None.
- `if not _AGENT_JOB_LOCK.acquire(blocking=False): return 409, {"error": "an agent job is already running", "job": _agent_snapshot()}`
  (only an agent job ever holds this lock).
- `if _APPLY.locked(): _AGENT_JOB_LOCK.release(); return 409, {"error": "the tracker is updating itself — try again after it restarts"}`.
- Then build `job`:
  ```
  {id, agent, action, state: "running", step, started, finished: None, old: None, new: None,
   output: "", items: [], outside: [], summary: ""}
  ```
  Under `_AGENT_JLOCK` set `_AGENT_JOB = job`, then start `threading.Thread(target=…, name="agent-" + action,
  daemon=True)`. If `start()` raises `RuntimeError`, release `_AGENT_JOB_LOCK`, set state failed, return 500. The
  thread body ends in `finally: _agent_set(job, finished=time.time()); _AGENT_JOB_LOCK.release()`.
- Return `202, {"job": _agent_snapshot()}`.

**`_agent_job_doctor`:**
- `rc, out, err = _run([path, *spec["doctor"]], AGENT_DOCTOR_TIMEOUT, cwd=os.path.expanduser("~"))`.
- `job["output"] = _agent_strip(out + err)`.
- `state = "done" if rc == 0 else "failed"`.
- `summary` is `AGENT_DOCTOR_DONE` or `AGENT_DOCTOR_FAILED` (§6), and is printed to the log.

**`_agent_job_upgrade(job, spec, confirm)`.** It sets `job["step"]` (§6 texts) at every step.
1. `old, err = _agent_version(spec)`. If `old` is None: fail with `AGENT_FAIL_VERSION`. Nothing is stopped.
2. `rc, out, er = _run([path, *spec["update"]], spec["update_timeout"], cwd=~)`; store `_agent_strip(out + er)`. If
   `rc != 0` (None = timeout or spawn error): read `--version` once more for the summary, then fail with
   `AGENT_FAIL_UPDATE` (Claude) or `AGENT_FAIL_UPDATE_NODOC` (an agent without Doctor), plus "still on {old}" when
   the version is unchanged. **Return. Nothing is stopped** — D8's restarts happen only after a successful update
   run (§15 decision 3).
3. `new, err = _agent_version(spec)`. Refresh the cache. If `new` is None: fail with `AGENT_FAIL_VERSION`. Nothing is
   stopped.
4. If not `spec["restarts_sessions"]`, go to step 8.
5. Take the pending-work lock for the restart phase (N9): `cm = _pending_lock(); got = cm.__enter__()` (the
   `update.py:268-277` pattern). If not `got`, fail with `AGENT_FAIL_SCAN` — nothing is stopped; the update itself
   has landed and the summary says so. `cm.__exit__(None, None, None)` in a `finally` after step 7. Then re-read
   `cands = tv.upgrade_candidates()` and split them. Sort each candidate (D8 — the restart runs whether or not
   `old == new`):
   - **Not in the warning.** Keep one only if its `(tty, session)` pair is in `confirm`. Every other one becomes item
     `outcome: "not_shown"`, text `AGENT_NOT_SHOWN`.
   - **Already current.** Skip one whose `version == new` (`outcome: "current"`).
   - **Unknown version, nothing installed.** `version == ""` and `old == new` → `outcome: "current"`, detail
     `AGENT_VER_UNKNOWN_SKIPPED`, with its command. (When `old != new`, an unknown version is restarted.)
   - **Failed preflight.** A confirmed pair that is now `stoppable: False` becomes `outcome: "failed"` with its reason
     and command. It is never stopped.
6. For each remaining candidate, **one at a time**:
   - **Slot check, right before the stop (S7):** if `cand["needs_slot"] and tv._live_count() >= config.MAX_TERMS`,
     record `outcome "failed"`, detail `AGENT_NO_SLOT`, with its command. Nothing is stopped.
   - Otherwise call `_agent_restart_daemon_pane` if `cand["daemon"]` (only when `AGENT_RESTART_DAEMON`; otherwise
     `_agent_split` already put it in `cannot_stop`), else `_agent_restart_one`.
7. `_agent_verify(job, new, time.time() + AGENT_VERIFY_WAIT)`.
8. Finish the job:
   - `job["outside"] = _agent_outside(spec, new, …)`;
   - `job["summary"]` is built from §6;
   - `state = "done"`;
   - `print("ai-tracker: agent upgrade: " + summary, flush=True)`.

   Any exception becomes `state = "failed"`, with `summary = AGENT_FAIL_INTERNAL % e` plus whatever was already
   recorded.

**`_agent_restart_one(job, spec, cand, new)`:**
1. Read `st = session_state(cand["target"], <status_raw of the fresh running() entry with pid == cand["pid"]>)`
   **just before the stop**.
2. Log: `print("ai-tracker: agent upgrade: restarting %s (%s); if this dashboard dies, resume it with: %s" % (title, sid, cand["command"][0]), flush=True)`.
3. `r = tv.stop_for_upgrade(cand["tty"], cand["session"], cand["pid"], cand["thin"])`.
   - If `r["error"]`, record `outcome "failed"`, `detail = r["error"]`, and continue. Nothing was signalled.
   - If `not r["confirmed"]`, record `outcome "unconfirmed"` (text `AGENT_UNCONFIRMED`) with its command. **Do not
     resume.**
4. `busy = _agent_was_busy(st, r["work_children"])`.
5. `body = {"session": cand["target"], "mode": "resume", "cols": cand["cols"], "rows": cand["rows"]}` — always
   `mode: "resume"`, never `"new"` (§1, agent view). If `busy`, add `body["prompt"] = AGENT_RESUME_PROMPT`.
   Record `size_before = transcript_size(cand["target"])` on the item.
6. `code, obj = tv.call_route(tv.open_pty, body)`.
   - **200:** record `outcome = "prompted" if busy else "unprompted"`, `tty_after = obj["tty"]`, and `forked`. When
     `tty_after != cand["tty"]`, the summary says "resumed in a new terminal" for it.
   - **Anything else:** record `outcome "failed"`, `detail = obj.get("error")`, plus the command.

**`_agent_restart_daemon_pane(job, spec, cand, new)`.** This is S5 (D5; V6's stop half passed, V6d gates landing).
1. Find the fresh `running()` entry `w` with `id == cand["target"]` and `kind == "bg"`. `st = w["state"] if w else
   ""`. `wk = _live_workers().get(cand["job_short"]) or {}`; record `pids = [p for p in (wk.get("pid"),
   wk.get("replPid")) if type(p) is int and p > 0]` and `kids = tv._agent_kids(wk["replPid"]) if pids else []`. If
   `pids` is empty, record `outcome "failed"` with `AGENT_REASON_NOJOB`; nothing is touched.
2. Log the recovery line, using `cand["command"]` (both lines joined with " then ").
3. `rc, out, er = _run([path, "stop", cand["job_short"]], AGENT_STOP_TIMEOUT, cwd=~)` — the SHORT id; the full
   session id is rejected (V6). If `rc != 0`, record `outcome "failed"` with `AGENT_DAEMON_STOP_FAILED`. Nothing else
   is touched. The session keeps running in the daemon.
4. **Confirm on the recorded pids (S6):** wait up to `AGENT_DAEMON_STOP_WAIT` until `os.kill(p, 0)` raises
   `ProcessLookupError` for every `p` in `pids`. A roster that reads empty is NOT proof (`daemon_repl_pid` answers 0
   for an unreadable roster or a dead supervisor, `claude.py:581-591, 602-608`). If any is still alive, record
   `outcome "unconfirmed"`. **Do not resume.**
5. `r = tv.stop_for_upgrade(cand["tty"], cand["session"], cand["pid"], thin=True)`. This clears the pane's client; a
   client that already exited is the `already` case. If `not r["confirmed"]`, record `outcome "unconfirmed"`; do
   not resume.
6. `tv._agent_sweep(kids, <the pane's shell pid>)`: catches the `run_in_background` tools `claude stop` leaves
   orphaned (`docs/folder-terminal-reuse-plan.md:542`), start-time checked.
7. `busy = _agent_was_busy(st, len(kids))`.
8. Resume `cand["target"]` exactly as in `_agent_restart_one` steps 5-6. After the stop, `_background_target` returns
   "", so `open_pty` runs a plain `claude --resume <target>`. From here on the session is a terminal session in a
   tracker pane, not a daemon job (S3; stated in the warning).

**`_agent_verify(job, new, deadline)`:**
- Loop every 2 s over the items with outcome `prompted` or `unprompted` until each one is settled, or the **single
  shared** deadline passes. An item is settled when:
  - `on_version` is known: a `running()` entry with `id == target` exists; it is `True` when its `version == new`;
  - for `prompted` items only, `prompt_seen = user_line_has(target, AGENT_RESUME_PROMPT, since=item["size_before"])`
    is True (an identical line from an earlier upgrade never counts).
- A `running()` entry with `id == target` but `kind == "bg"` (the resume became a `claude attach` of a still-live
  worker) counts as `on_version` by its version and adds `AGENT_STILL_DAEMON` to `detail`.
- All writes go through `_agent_set`.
- A `running()` version that differs from `new` sets `detail = AGENT_VERSION_MISMATCH % (version, new)`.
- No entry before the deadline sets `detail = AGENT_NOT_CONFIRMED % new`.

**`_agent_outside(spec, installed, owned_pids, owned_ids)`:**
- **Claude:**
  - Take `spec["provider"].running()`, drop entries whose `pid` is in `owned_pids` or whose `id` is in `owned_ids`.
  - **Dedupe by `job`** when it is non-empty: a parked TUI elsewhere and its worker are one conversation, so keep the
    `kind == "bg"` entry.
  - Each row is:
    ```
    {id, title, cwd, version, host, state, out_of_date, how, command}
    ```
    - `out_of_date` compares the version tuples (`tuple(int(x) for x in v.split("."))`). It is `None` when either
      version is unknown, and always `None` for `host == "desktop"`.
    - `host == "tui"`: `how = AGENT_HOW_TUI`, `command = [resume_cmd(id, model)]`, or `[]` when that is None.
    - `host == "daemon"`: `how = AGENT_HOW_DAEMON`, `command = ["claude stop " + job, "claude --resume " + id]`.
    - `host == "desktop"`: `how = AGENT_HOW_DESKTOP`, `command = []`.
- **Auggie:**
  - Take the `all_sessions()` rows whose `id` starts with `spec["provider"].prefix` and where
    `time.time() - row["mtime"] < config.LIVE_WINDOW`.
  - Each row is `{id, title, cwd, version: "", host: "tui", out_of_date: None, how: AGENT_HOW_AUGGIE, command: []}`.

### 5.5 `aitracker/server.py` (bundled) (S6)

- Import `from .agent_cli import agent_status, agent_plan_upgrade, agent_start, agent_job_running`, next to the
  `update` import (`server.py:13`), and add `_APPLY` to that `update` import.
- **`do_GET`**, next to the `/api/update` branch (`server.py:476-481`):
  ```python
  elif p.path == "/api/agents":
      ok, err = _local_caller(self)
      if not ok:
          return self._json({"error": err}, 403)
      return self._json(agent_status())
  ```
  It is not added to `_RO_GET_ALLOW` (`server.py:297-302`), so read-only callers get 403 at `server.py:425-426`.
- **`do_POST`**, after the `/api/pending/run` branch (`server.py:681-686`). The global `_readonly()` deny-all at
  `server.py:632-633` has already run.
  ```python
  if p.path == "/api/agents/run":
      ok, err = _local_caller(self)
      if not ok:
          return self._json({"error": err}, 403)
      if not isinstance(body, dict):                # do_POST accepts any JSON value (server.py:636)
          return self._json({"error": "bad body: expected a JSON object"}, 400)
      agent, action, confirm = body.get("agent"), body.get("action"), body.get("confirm")
      if (action == "upgrade" and confirm is None and isinstance(agent, str)
              and not agent_job_running() and not _APPLY.locked()):   # busy -> agent_start's 409, never a stale preview
          plan = agent_plan_upgrade(agent)          # None for an unknown agent -> falls to agent_start's 400
          if plan is not None:
              return self._json(plan, 409)
      code, out = agent_start(agent, action, confirm)
      return self._json(out, code)
  ```
- `_local_caller` (`server.py:223-240`) already checks four things: no proxy header, same Origin, loopback peer, and a
  loopback Host when AUTH is unset. Nothing new is added.

### 5.6 `aitracker/web/ext_cr_dialogs.js` (S7)

- Add `'Agents'` to `sections` (`ext_cr_dialogs.js:1318`), after `'Terminal'`. Add a branch in the section dispatch
  after the Terminal branch (`ext_cr_dialogs.js:1527-1570`):
  ```js
  } else if (active === 'Agents') { var agEl = agentsBlock(); if (agEl) body.appendChild(agEl); }
  ```
- At IIFE scope, just above `function agentsBlock`, declare:
  ```js
  var _agentJobTimer = null, _agentToasted = null;
  function agentWatchJob(id) {
    if (_agentJobTimer) return;
    _agentJobTimer = setInterval(function () {
      crCall('/api/agents').then(function (r) {
        var j = r.ok && r.body.job;
        if (!j || j.id !== id) { clearInterval(_agentJobTimer); _agentJobTimer = null; return; }
        if (j.state === 'running') return;
        clearInterval(_agentJobTimer); _agentJobTimer = null;
        if (_agentToasted !== j.id) { _agentToasted = j.id; toast({ title: j.summary, duration: 30000 }); }
      });
    }, 2000);
  }
  ```
  The timer is not owned by the dialog DOM, so closing Config does not stop it (F8). There is no page-load hook and no
  `sessionStorage`.
- **`function agentsBlock()`**, placed after `updateBlock` (`ext_cr_dialogs.js:1218-1305`) and before
  `renderConfig`:
  - It returns null when `crReadOnly()`.
  - It fetches `crCall('/api/agents')` and repaints every 2 s while `job.state === 'running'`, but only while the block
    `isConnected`.
  - It renders one `cfg-row` per agent:
    - the label;
    - `installed`, or "checking…", or `error`;
    - the `note`;
    - **Doctor** (when `can_doctor`) and **Upgrade** (when `can_upgrade`), both built with `crBtn`. Both are disabled
      while a job runs.
  - **Upgrade** is enabled only when `installed` is set. It POSTs `{agent, action: 'upgrade'}`. On 409 with
    `needs_confirm`, it renders an inline box
    `h('div', {class: 'cr-update-confirm cr-agents-confirm', role: 'alertdialog'}, …)` containing:
    - `message`;
    - the `stop` list (title, cwd, `version`, `version_text`, `state_text`, and `relabelled_text` when present);
    - `cannot_stop` (title, `reason`, and the `command` lines in `<code>`);
    - `outside` (title, version, out-of-date text, `how`, and the `command` lines in `<code>`);
    - `note`;
    - the buttons **Upgrade and restart these** and **Cancel**.
  - Confirming re-POSTs `{agent, action: 'upgrade', confirm: stop.map(function (c) { return {tty: c.tty, session: c.session}; })}`.
  - On 202 it calls `agentWatchJob(r.body.job.id)`.
  - When the block's first GET shows a running job, it also calls `agentWatchJob(job.id)`. This covers reopening Config
    mid-job; it is not page-load catch-up.
  - The job view shows `job.step` while the job runs. Afterwards it shows `job.summary`, `job.output` in a `<pre>`,
    `job.items` (title plus `detail`) and `job.outside`.
  - **Doctor** POSTs `{agent, action: 'doctor'}` and then watches the job the same way.
- Every sentence comes from the server. The JS has only button labels ("Doctor", "Upgrade", "Upgrade and restart
  these", "Cancel") and the "checking…" placeholder.
- No CSS change. (`.cr-update-confirm` has no stylesheet rule anywhere — `grep -rn cr-update-confirm aitracker/web/`
  finds only `ext_cr_dialogs.js:1255-1256` — so there is nothing to copy; the box reuses that class for parity, and
  `cr-agents-confirm` is the test hook.)

### 5.7 Other files

- `scripts/bundle.py` ORDER (`bundle.py:11-16`): insert `"agent_cli.py"` **after `"update.py"`** and before
  `"server.py"`.
- `tests/test_integration.py:1761-1762`: add `"_AGENT_JOB_LOCK", "running_sessions", "session_state",
  "user_line_has", "transcript_size", "resume_cmd"` to the exactly-once list (`_run` and `status` are already in
  it), and add one generic check: parse `aitracker/agent_cli.py` with `ast`, and assert that every top-level
  def/class/assignment name in it appears exactly once in the bundle (N2). Pre-existing bundle duplicates
  (`file_diffs`, `command_output`, `_root`, `_git_env`) are out of scope and untouched.
- `.claude/rules/conventions.md`: the rule-6 exception (§7), added after line 18.
- `README.md`, `CLAUDE.md`: §11.
- No `config.py` change: the latest version is always used, and the trigger is manual only.

## 6. Every user-facing string (server-written, in `agent_cli.py`)

```python
AGENT_AUTO_UPDATE_NOTE = ("Note: Claude Code also updates itself in the background; the tracker leaves that alone. "
                          "A new version only takes effect when a session restarts.")
# _agent_message(names, restarts):
AGENT_MSG_STOP = ("The following sessions: {list} will be stopped, you might have to continue again with a prompt "
                  "once the upgrade lands. The tracker restarts each one on the new version as soon as the update "
                  "finishes. A session that is working, or waiting on you for a permission or an answer, when it is "
                  "stopped is resumed with the prompt “continue, re-read CLAUDE.md”; an idle one is resumed and "
                  "left waiting for you. A session already on the new version is left running. Even if nothing new "
                  "is installed, a session running an older version than the installed one is restarted onto it.")
AGENT_MSG_NO_STOP = "No session started from this dashboard will be stopped."
# version_text per stop row (D8):
AGENT_VER_OLD = "runs v{v}, older than the installed v{i} — restarted even if nothing new is installed"
AGENT_VER_CURRENT = "already on the installed v{i} — restarted only if a newer version installs"
AGENT_VER_UNKNOWN = "version unknown — restarted only if a newer version installs"
AGENT_VER_UNKNOWN_SKIPPED = "version unknown and nothing new was installed, so it was left running"
AGENT_RELABELLED = "now runs this session (the terminal was opened on %s)"
AGENT_MSG_NO_RESTART = ("Auggie sessions are not restarted by the tracker; restart them yourself once the upgrade "
                        "lands.")
# state_text per stop row (from session_state at warning time; the prompt decision is re-taken at stop time):
AGENT_STATE_BUSY = "working now — its current turn will be interrupted, then resumed with the prompt"
AGENT_STATE_WAITING = "waiting on you (a permission or a question) — that prompt will be cancelled, then resumed with the prompt"
AGENT_STATE_IDLE = "idle — resumed without a prompt"
AGENT_STATE_UNKNOWN = "state unknown — resumed with the prompt only if it is working when stopped"
AGENT_STATE_KIDS = " Commands it started (tool runs, background shells such as a dev server) are stopped too."  # appended to every state_text
AGENT_STATE_DAEMON_MOVE = (" It runs in Claude's background daemon now; it comes back as a session in this tracker "
                           "terminal, which ends if the tracker stops.")  # appended for daemon rows (S3)
# cannot_stop:
AGENT_REASON_DAEMON = "runs in the Claude background daemon; the tracker does not restart it — restart it yourself:"  # only if V6d fails
AGENT_REASON_DUP = "the same session as terminal %s; restarted there"
AGENT_REASON_NOJOB = "its background job is gone from the daemon roster"
AGENT_NO_SLOT = "no free terminal slot to resume it in, so it was not stopped — close a terminal and press Upgrade again"
AGENT_STILL_DAEMON = "it reattached to a background job that is still running"
AGENT_FAIL_SCAN = ("The update ran, but a pending-work scan is running, so no session was restarted — press Upgrade "
                   "again when it finishes.")
# outside `how`:
AGENT_HOW_TUI = "not started from this dashboard — exit it, then run:"
AGENT_HOW_DAEMON = "a background session — stop it, then resume it in a terminal:"
AGENT_HOW_DESKTOP = "runs inside the Claude desktop app; it updates with the app"
AGENT_HOW_AUGGIE = "version unknown — restart Auggie in that terminal once the upgrade lands"
# steps:
AGENT_STEP_OLD, AGENT_STEP_UPDATE, AGENT_STEP_NEW = ("Reading the installed version…", "Running {bin} {args}…",
                                                     "Checking the new version…")
AGENT_STEP_RESTART = "Restarting {title} ({n} of {m})…"
AGENT_STEP_VERIFY = "Checking the restarted sessions…"
# failures / per-item:
AGENT_FAIL_VERSION = "Could not run `{bin} --version`; nothing was changed and no session was stopped."
AGENT_FAIL_UPDATE = "{label} update failed; no session was stopped. Run Doctor to see why."
AGENT_FAIL_UPDATE_NODOC = "{label} update failed; no session was stopped. Its output is below."   # agents without Doctor (Auggie)
AGENT_STILL_ON = " Still on {old}."
AGENT_FAIL_INTERNAL = "The upgrade stopped on an internal error (%s); see the list below for what was already done."
AGENT_NOT_SHOWN = "not shown in the warning, not stopped"
AGENT_UNCONFIRMED = "could not confirm it stopped, so it was not resumed — open its terminal"
AGENT_DAEMON_STOP_FAILED = "`claude stop` failed; it is still running in the background"
AGENT_VERSION_MISMATCH = ("resumed on v%s, expected v%s — another claude may be first on your shell's PATH; "
                          "run Doctor")
AGENT_NOT_CONFIRMED = "resumed, but not yet seen running on v%s — open its terminal"
AGENT_DOCTOR_DONE, AGENT_DOCTOR_FAILED = "Doctor finished.", "Doctor exited with an error; see its output."
```
**Completion summary.** Built by joining the non-empty parts in this order. `{n}` is a title, or the first 8 characters
of the id when the title is empty.
1. `"{label} {old} → {new}."` (or `"{label} is already on {new}; nothing new was installed."` when `old == new`);
2. `"Resumed with “continue, re-read CLAUDE.md” (were working or waiting): A, B."`;
3. `"Resumed without a prompt (were idle): C."`;
4. `"Already on {new}, left running: D."`;
5. `"Failed: E — {detail}; run `{command}`."` (one clause per failed, unconfirmed or not-shown item);
6. `"Not confirmed on {new} yet: F."` (verify detail), and `"Resumed in a new terminal: G."` for items whose
   `tty_after` differs from their `tty`;
7. `"Not started here, left alone: {k} ({j} out of date)."`.

Auggie: `"Auggie {old} → {new}. " + AGENT_MSG_NO_RESTART`, plus part 7.

The summary is the toast title, the panel's headline, and the server log line `ai-tracker: agent upgrade: <summary>`.

## 7. Conventions rule-6 exception (exact wording; lands in S4, the same commit as `agent_cli.py`)

> *"Exception (agent CLI Doctor/Upgrade, user-requested): `aitracker/agent_cli.py` — and only it, never synchronously inside a request handler (its own job and version-refresh threads may) — may run, through `update._run` (no shell, stdin closed, its own session and process group, a timeout that kills the group, cwd `~`), exactly these argv: `<claude> --version`, `<claude> doctor`, `<claude> update`, `<claude> stop <short>`, `<auggie> --version`, `<auggie> upgrade --skip-confirmation`, where `<claude>`/`<auggie>` is `shutil.which` of that name on the server's own PATH and `<short>` is a hex job id read from a live Claude pid file and the daemon roster, never from the request. The request only picks the agent and the action from that fixed table. `--version` runs in the background at most once per `AGENT_VERSION_TTL` (60 s) while the Agents panel is polled; Doctor and Upgrade run only when a local caller (no proxy header, same Origin, loopback peer, loopback Host name, not read-only) presses the button — never on a schedule. `update`/`upgrade` (and `doctor`'s own checks) contact the vendor's servers with the CLI's own configuration; the tracker itself sends nothing. After an update run that exited 0 and whose `--version` is readable — whether or not it installed anything — the job may restart only sessions running in, or shown by, the tracker's own terminals: a Claude session with a known id, on a version other than the installed one, that passes every resume precondition and that the user confirmed by (terminal, session) in the warning. `aitracker/term_vt.py`'s `stop_for_upgrade` does the signalling: SIGTERM to that Claude's process group, SIGKILL of that group only if it has not exited within `PARKED_DETACH_WAIT`, then the session's own tool processes, each re-identified by its start time before it is signalled; for a terminal showing a Claude background-daemon session, `<claude> stop <short>` runs first. Each session is resumed through `term_vt.open_pty` as `claude --resume <id>` (never a bare `claude`), adding the prompt `continue, re-read CLAUDE.md` only for a session that was working or waiting on the user when it was stopped. It reads `~/.claude/sessions/<pid>.json` (pid, procStart, sessionId, kind, entrypoint, jobId, parkedJobId, version, status, cwd only) and, from the daemon roster, only a worker's pid, replPid and sessionId. It never stops, signals or edits a session that is not running in or shown by a tracker terminal (terminal, background-daemon and desktop-app sessions elsewhere are listed with the command to run), never edits a transcript, and never changes Claude Code's or Auggie's own auto-update settings. No other outbound network call is allowed."*

If V6d fails, delete `` `<claude> stop <short>`, ``, "and `<short>` is a hex job id … never from the request", "and,
from the daemon roster, only a worker's pid, replPid and sessionId", and the sentence part "; for a terminal showing a
Claude background-daemon session, `<claude> stop <short>` runs first". Then add "not hosted by the Claude daemon"
after "a known id".

## 8. Exact external commands

| Command | Where it runs | How |
|---|---|---|
| `[<claude>, "--version"]`, `[<auggie>, "--version"]` | `_agent_version`, called from the `agent-versions` thread or the job thread | `update._run(argv, 15, cwd=~)` |
| `[<claude>, "doctor"]` | job thread | `update._run(argv, 60, cwd=~)` |
| `[<claude>, "update"]` | job thread | `update._run(argv, 600, cwd=~)` |
| `[<auggie>, "upgrade", "--skip-confirmation"]` | job thread | `update._run(argv, 300, cwd=~)` |
| `[<claude>, "stop", <short>]` (S5; the SHORT id — the full session id is rejected, V6) | job thread | `update._run(argv, 30, cwd=~)` |
| `[<launcher>, "--resume", <id>]`, plus `"continue, re-read CLAUDE.md"` for a busy session; never a bare `[<launcher>]` (agent view, §1) | `open_pty` `mode: "resume"` | typed into the folder shell with `_inject_argv` (`shlex.join`, `term_vt.py:1953`), or exec'd in a dedicated pty (`term_vt.py:3318`) |
| SIGTERM / SIGKILL | `stop_for_upgrade`, `_agent_sweep` | `os.killpg`, with the `Pty.kill` guards; sweep targets re-identified by `ps -o lstart=` |
| `ps …` | existing helpers (`_claude_work_children`, `_ps_lstart`, `_thin_client_short`) | unchanged |

Notes on how `update._run` runs every row above:
- It uses `env = update._git_env()`: `os.environ` minus `GIT_DIR`/`GIT_INDEX_FILE`/`GIT_WORK_TREE`, plus three git
  no-prompt variables that are harmless to the agent CLIs.
- `rc is None` means a timeout or a spawn failure.
- `err` is always bytes (`update.py:70`).

## 9. The risky spot, and its fallbacks

**Update first, stop second.** The order is:
1. Read the old version.
2. Run the update.
3. Read the new version.
4. Only then, one session at a time: stop, resume.

A running session keeps its own binary. Each version lives in its own directory, and `claude update` repoints the
symlink. So stopping before the update buys nothing, and an update failure (rc ≠ 0, timeout, spawn error, unreadable
version) **stops nothing**. D8: when the update ran fine but installed nothing, the same flow restarts only sessions
whose known version differs from the installed one.

Every precondition that `open_pty` checks is checked before a session is stopped, and so is a free terminal slot
when the resume needs a new folder shell. A stop that is not confirmed (by pid, and for a daemon job by the worker's
own recorded pids) is never resumed. Before each stop, the server log has the session's resume command. If the
tracker dies mid-job, all of its panes die with it, as they always would; the one being restarted can be recovered
from that log line (N8). A session D5 moved out of the daemon now lives in a tracker pane and also ends when the
tracker stops — the warning says so.

| Risk | Fallback |
|---|---|
| Import cycle: agent_cli needs `update._run`/`_APPLY`, and update needs to see agent jobs | Both locks live in `update.py` (§5.2). `agent_cli` imports from `update`; `update` imports nothing new. The bundle cannot use function-level imports, so a lazy import is not an option. |
| V2r false (a resume runs on the old version) | S0 stops S3-S5. At runtime, verify reports the mismatch with Doctor advice. |
| V5: SIGTERM does not stop a busy Claude in 8 s | SIGKILL of its group (§5.3 step 5); the orphan sweep kills tool children. |
| V6d fails (the pane half; V6's stop half passed) | S5 does not land. Daemon panes go to `cannot_stop` with the two commands. |
| A resume reattaches to a still-live worker (`claude attach`, old version) | Prevented by the pid-based stop confirmation; if it still happens, verify reports `AGENT_VERSION_MISMATCH` + `AGENT_STILL_DAEMON`. Nothing lost. |
| A bare `claude` would open the agent view | The feature only ever opens `mode: "resume"` (§1); a test pins it. |
| The pane's label is stale after `/clear` or `/resume` | The live pid file's `sessionId` wins (§5.3). If V3b shows the file does not follow `/clear`, the README states the gap. |
| A tool child's pid is recycled before the sweep | Start time captured with the pid and re-checked before every signal (§5.3 step 8). |
| The resume needs a new folder shell and the terminal cap is reached | Checked right before the stop; the session is not stopped (`AGENT_NO_SLOT`). |
| A pending-work scan in the stop/resume window sees a worktree as unused (`pending.py:224-236`) | The restart phase holds `_pending_lock`; if a scan holds it, nothing is stopped (`AGENT_FAIL_SCAN`). |
| A newer `claude stop` against an older daemon supervisor | Not measured. Mixed-version workers coexist today (live 2.1.323 and 2.1.325 `bg` jobs). A non-zero rc leaves the session untouched. |
| V7: the permission prompt is invisible in the pid file | The tail fallback with `last == "assistant_tool"` (§5.1). If that is invisible too, the session is resumed without the prompt and listed as such. |
| `--resume` shows a picker, or the fork backstop fires and drops the prompt | Verify reports "not yet seen running on vX" or `prompt_seen: false`. The session is running, not lost. |
| `claude update` exits 0 but changed nothing | `--version` is the oracle. Sessions already on it are skipped. |
| Claude's own background auto-updater runs at the same moment | rc ≠ 0, so nothing is stopped. Doctor shows "Last update attempt". |
| The tracker's own Update is pressed mid-job, or the reverse | The two-sided lock check refuses with 409 and a clear reason. |
| An npm-global Auggie install replaces files under a running session | Known gap. Auggie sessions are not restarted; the README notes it. |

## 10. Sequencing (each step is its own commit, with `unset TRACKER_AUTH; make check` green before the next)

| Step | Lands | Why here |
|---|---|---|
| S0 | V2r, V3b, V7, V5 (one session), V6d (one job), V8, with results in §13. No code. | The design rests on V2r and V5. V6d gates S5. V7 fixes the busy rule. |
| S1 | `Provider.agent_cli`/`running`; `claude.running_sessions` (with `status_raw`), `session_state`, `_tail_scan["last"]`, `transcript_size`, `user_line_has(since=)`; both descriptors; `registry.resume_cmd`. Tests: `test_claude_running.py`. | Pure, read-only seams that everything else uses. |
| S2 | `update.py` edits (§5.2). Tests: added to `tests/test_update.py`. | A tiny change to a landed module; independent. |
| S3 | `term_vt`: `_with_prompt` in the resume arm, `upgrade_candidates` (pid file beats label, `needs_slot`, dedupe), `stop_for_upgrade`, `_agent_kids`, `_agent_sweep`, `call_route`. Tests: `test_term_vt_upgrade.py`. | Terminal-tier pieces, testable with the existing fake-pty patterns. |
| S4 | `agent_cli.py` without the daemon-pane path (`AGENT_RESTART_DAEMON = False`); **the rule-6 exception in the same commit**; bundle ORDER; the `test_integration` name list and generic check. Tests: `test_agent_cli_parse.py`, `test_agent_cli_jobs.py`, `test_agent_cli_outside.py`. | The first code that runs an outbound command lands with its rule. |
| S5 | **Once V6d passed** (V6's stop half already has): `AGENT_RESTART_DAEMON = True` and `_agent_restart_daemon_pane`. Jobs tests (n), (n'). This is the main path on this machine. | D5 stays separately revertible. |
| S6 | `server.py` routes. Tests: `test_agent_routes.py`. | Exposes S4 only once it is guarded. |
| S7 | `ext_cr_dialogs.js` Agents section and poller (no CSS change). Tests: `test_agents_ui.py`. | UI last; it renders server text only. |
| S8 | README, CLAUDE.md, the `_selfcheck` assertion. | Docs. |
| S9 | Live proof, then `/branch-sync`, the full gate, and pushing the branch to `personal`. | Proves the live path, not only the units. |

**S9 procedure.** It follows the §4 safe-scratch protocol.
1. With the user's OK (this needs more scratch sessions than D9 approved — ask), create each session with
   `claude -p "say ok" --output-format json` in its own scratch folder and open it through the dashboard's Resume
   (never a bare `claude`). Three scratch tracker panes:
   - one busy, running `sleep 300` through Bash;
   - one at a permission prompt;
   - one idle.
2. Open one scratch outside session in Terminal.app (also `claude --resume <id>`).
3. If S5 landed, add one scratch `claude --bg` job opened in a tracker pane (a thin client).
4. Press Upgrade twice: once when `claude update` has nothing to install (D8: sessions on an older retained version —
   start one with `DISABLE_AUTOUPDATER=1 ~/.local/share/claude/versions/2.1.323 -p …` then resume it — must restart;
   current ones must be left running), and once for real if a release exists. Check:
   - the warning text, including each row's `version_text` and, for the daemon row, the "comes back as a session in
     this tracker terminal" sentence;
   - no orphaned `sleep`;
   - the folder pane keeps its tty (or the summary says "resumed in a new terminal");
   - the pid-file version;
   - the prompt went to the busy and waiting panes only (transcript user line);
   - the idle pane got no prompt;
   - the toast still appears after closing Config;
   - the server log line;
   - the outside list shows each command per host.
5. Run Auggie Upgrade once with the user's OK. Auggie is already on the latest version (D10 run), so this records the
   "already up to date" rc and output in §13 (V9) and checks the summary is honest either way.
6. Tear everything down; the report lists every id, job short and trust entry created.

**Gate:** `unset TRACKER_AUTH; make check`. If it is OOM-killed, run one module per process. A commit runs the full gate
(180-380 s), so give Bash a timeout of more than 6 minutes. The known flaky `term_vt` backstop test is not a regression.

## 11. Tests (stdlib unittest; each proved red by reverting its fix)

| File | Case: assertion | Goes red when |
|---|---|---|
| `tests/test_claude_running.py` (S1) | Temp `LIVE_SESSIONS_DIR`: a live pid (`os.getpid()` with its real `_ps_lstart`) is kept with its `version`; a dead pid, a wrong `procStart` and a non-int pid are excluded. | the procStart check is removed |
| | Host mapping: `bg` → daemon (job = jobId); `parkedJobId` → daemon; `claude-desktop` → desktop; else tui. A non-hex job becomes "". | the mapping or the validation is reverted |
| | `session_state`: `"idle"` → idle, `"waiting"` → waiting, `"busy"`, `"shell"` and `"compacting"` → busy (S1). With no status, a tail fixture gives: unanswered AskUserQuestion → waiting; trailing `tool_use` → busy; final assistant text → idle; an unknown id (no transcript) → "" without raising (N5). | an allow-list is restored, the fallback or `_tail_scan["last"]` is reverted, or the None guard is removed |
| | A fixture with `"messagingSocketPath": "SECRET-X"`: no emitted value contains `SECRET-X`. `status_raw` is emitted. | the key whitelist is removed |
| | `user_line_has(sid, P, since=size)`: a transcript already holding a user line with P → False; after appending one → True (N6). `transcript_size("nope") == 0`. | `since` is ignored |
| | `Provider().running() == []`, Auggie `running() == []`; descriptors as in §5.1; `agent_cli` of both augment_ext classes is None. | a descriptor changes |
| | `registry.resume_cmd`: Anthropic model → `claude --resume X`; OpenRouter model with launcher set → quoted launcher; unset → None. | the extraction is wrong |
| `tests/test_update.py` (S2) | With `_AGENT_JOB_LOCK` held, `update_apply()` → 409 whose error contains "agent upgrade", and `_APPLY.locked()` is False afterwards. | the §5.2.3 check is removed |
| | `_run([sys.executable, "-c", "import os;print(os.getcwd())"], 10, cwd=tmp)` prints `realpath(tmp)`. | `cwd` is not passed |
| `tests/test_term_vt_upgrade.py` (S3) | `open_pty` `{mode: resume, prompt}`, following the `tests/test_pending_pty_prompt.py:29-70` pattern → injected argv `["claude", "--resume", "S", "continue, re-read CLAUDE.md"]`. Without a prompt → `["claude", "--resume", "S"]`. | the one resume-arm line is removed |
| | `upgrade_candidates`: a labelled pane → stoppable. A forked pane with `running_sessions` patched to `{pid: fg, id: "S", host: "tui"}` → `session == "S"`, stoppable (F7). `_background_target` patched → daemon True, `job_short` from the bg entry's `job`, with the two-line command. `resume_argv` raising `GatewayError` → stoppable False, reason = its message. `session_cwd` "" → False. `allowed()` False → False. | each preflight check is removed |
| | **B2:** a pane labelled "X" whose `running_sessions` entry at its fg pid is `{id: "Y", host: "tui"}` → `session == "Y"`, `relabelled == "X"`, command contains `Y`. A thin-client pane with no pid file keeps its label. | the label wins again |
| | **S7:** two panes with the same target → one stoppable, the other reason `AGENT_REASON_DUP`. A target whose `session_cwd` has no live folder pane → `needs_slot` True. | dedupe or `needs_slot` is removed |
| | **S5:** `_agent_sweep([(pid, "Mon Jan  1 00:00:00 2001")], shell)` for a live pid whose real start time differs → `os.killpg` (patched) never called; a matching start time → called. | the start-time check is removed |
| | `stop_for_upgrade` on a real folder pty (pattern `tests/test_folder_terminal.py`). The fg is a python child that starts `sleep 300` in its own session and exits 0 on TERM. Expect: graceful True, confirmed True, the sleep pid gone, the same `pt.id` still live, `pt.fg` cleared. | the orphan sweep or the `fg` refresh (M6) is removed |
| | A fg that ignores TERM → graceful False, confirmed True, the shell still alive. | the SIGKILL escalation is removed |
| | `pid` ≠ the pane's fg → `error` set, and `os.killpg` (patched) is never called. | the identity check is removed |
| | `call_route(open_pty, …)` with `config.AUTH = ""`, TERMINAL on and a loopback bind → not 403. | `_Internal.headers = {}` (M5) |
| `tests/test_agent_cli_parse.py` (S4) | `agent_parse_version` on "2.1.211 (Claude Code)", "0.36.0 (commit 7c61e5bb)" and junk. `agent_specs()` with a stub PATH resolves `path`. `_agent_message` gives the three texts in §6. `_agent_was_busy`: waiting/busy → True; idle with 0 children → False; idle with 2 children → True. | the parser, the message or the busy rule is reverted |
| `tests/test_agent_cli_jobs.py` (S4/S5) | Uses a stub `claude`/`auggie` on a temp PATH (logs argv and cwd; `--version` reads a state file; `update` writes a new version or exits per an env var), a fake `aitracker.term_vt` in `sys.modules`, and a patched `running_sessions`/`session_state`. | |
| | (a) update rc 1 → zero `stop_for_upgrade` calls, state failed, summary contains "no session was stopped" | the order is reversed |
| | (b) success → stop, then open, per candidate, strictly in sequence; every open body has `mode == "resume"`, and no body anywhere has `mode == "new"` (B1, agent view) | a bare launch is introduced |
| | (c) **D6**: a busy state → `prompt` in the open body; waiting → prompt; idle with `work_children 0` → **no `prompt` key**; idle with `work_children 2` → prompt. Summary has the "Resumed with" and "Resumed without a prompt" parts. | the prompt is always sent |
| | (d) a candidate with `version == new` is never stopped and is listed "Already on" | the skip is removed |
| | (e) a `(tty, session)` pair not in confirm is not stopped, and is listed `AGENT_NOT_SHOWN` (F9) | |
| | (f) `stoppable False` is never stopped (F6) | |
| | (g) stop `confirmed False` → no open; listed as unconfirmed | |
| | (h) open answers 400 → item failed, with its command in the summary | |
| | (i) a second start → 409 "already running"; `_APPLY` held → 409 "updating itself"; a job running → `update.update_apply()` → 409 (F10, both sides); `Thread.start` patched to raise → `_AGENT_JOB_LOCK` is released (N8) | |
| | (j) a bad agent, action or confirm → 400; the logged argv never contains request strings | |
| | (k) verify with a patched clock: total wait ≤ `AGENT_VERIFY_WAIT` for 3 sessions; a `running()` version "2.1.300" → `AGENT_VERSION_MISMATCH` (F11) | |
| | (l) doctor/update cwd == HOME (N3); output ANSI-stripped and capped | |
| | (m) Auggie argv `["upgrade", "--skip-confirmation"]`; the stub exits 1 without the flag; zero stop calls; `AGENT_MSG_NO_RESTART` in the summary. Stub `upgrade` exits 1 with an unchanged version → summary uses `AGENT_FAIL_UPDATE_NODOC` + "Still on", and contains no "Doctor" (N1) | |
| | (n) S5: a daemon candidate → logged argv `[path, "stop", "ab12"]` (the short) **before** `stop_for_upgrade`. `claude stop` rc 1 → no `stop_for_upgrade` and no open. Success → open `session == target`. With `AGENT_RESTART_DAEMON = False` → the candidate is in `cannot_stop` with `AGENT_REASON_DAEMON` and both commands. | |
| | (n') **S6:** `daemon_repl_pid`/roster patched to read empty while the recorded worker pid (a live `sleep` child of the test) is alive → no open, outcome unconfirmed | the confirmation goes back to the roster read |
| | (o) stdout captures `ai-tracker: agent upgrade: <summary>` | |
| | (p) **D8:** stub `update` leaves the version unchanged; candidates on 2.1.323, 2.1.325 and "" → only the 2.1.323 one is stopped; the "" one is `current` with `AGENT_VER_UNKNOWN_SKIPPED`; summary part 1 says "nothing new was installed". With the version changed, the "" one IS stopped. | the D8 rules are reverted |
| | (q) **D8:** the 409 body's stop rows carry `version_text` = `AGENT_VER_OLD` / `_CURRENT` / `_UNKNOWN` against the cached installed version | no `version_text` |
| | (r) **S4:** one thread mutates a running job's items through `_agent_set` in a loop while another calls `agent_status()` 500 times → no exception; every snapshot item has all 13 schema keys | snapshot or schema removed |
| | (s) **S7:** `config.MAX_TERMS` reached and `needs_slot` True → zero `stop_for_upgrade` calls; item failed with `AGENT_NO_SLOT` | the slot check is removed |
| | (t) **N9:** `_pending_lock` held elsewhere → zero stop calls; summary `AGENT_FAIL_SCAN` | the lock is not taken |
| `tests/test_agent_cli_outside.py` (S4) | A tui row → `[resume_cmd]`, including OpenRouter through the launcher. Daemon → two commands. Desktop → `[]`, `AGENT_HOW_DESKTOP`, `out_of_date None`. A parked TUI plus its worker → one row. Owned pid or id excluded. A live Auggie row → `AGENT_HOW_AUGGIE`, an old one excluded. Tuple compare: "2.1.1000" > "2.1.325". | each branch is reverted; a string compare is used |
| `tests/test_agent_routes.py` (S6, `_ServerCase` pattern at `tests/test_cr_routes.py:168`) | GET `/api/agents` 200 from loopback; 403 with `X-Forwarded-For`; 403 with `Host: evil.example` and no AUTH; POST 403 with `Origin: http://evil.example`; read-only tunnel → 403 for both. An upgrade with no confirm → 409 `needs_confirm` whose `message` contains "will be stopped" or `AGENT_MSG_NO_STOP`, `note` contains "updates itself in the background", and Auggie's message is `AGENT_MSG_NO_RESTART`. A daemon candidate's row `state_text` contains "comes back as a session in this tracker terminal" (S3). With a job running, an upgrade with no confirm → 409 "already running", not `needs_confirm` (N8). A JSON list body → 400 (N8). Doctor → 202 (`agent_start` patched). A bad confirm → 400. | a gate is removed |
| `tests/test_agents_ui.py` (S7) | `'Agents'` in `sections`. Both routes referenced. None of "will be stopped", "continue, re-read" or "updates itself" appears in the JS. `var _agentJobTimer` is declared before `function agentsBlock` (module scope, F8). `toast(` is called with `j.summary`. No `sessionStorage` in the agents code. `node --check` when node is on PATH. | the poller moves into the block, or text is hard-coded |
| `tests/test_integration.py` (S4) | Bundle: every top-level name parsed from `aitracker/agent_cli.py` appears exactly once, and so do `running_sessions`, `session_state`, `user_line_has`, `transcript_size`, `resume_cmd`, `_AGENT_JOB_LOCK`; `status` and `_run` still appear exactly once (M4, N2). | a name collides (e.g. renaming one to `agent_detail`) |

**`_selfcheck()` assertion.** One block covering Claude and Auggie, placed in `tests/test_selfcheck.py` `_run()` before
`print("selfcheck ok")` at line 1481:
```python
from aitracker import agent_cli as _ac
from aitracker.registry import PROVIDERS as _AP
_ad = {p.agent_cli["id"]: p.agent_cli for p in _AP if p.agent_cli}
assert (_ad["claude"]["update"] == ["update"] and _ad["auggie"]["update"] == ["upgrade", "--skip-confirmation"]
        and _ac.agent_parse_version("2.1.211 (Claude Code)") == "2.1.211"
        and _ac.agent_parse_version("0.36.0 (commit x)") == "0.36.0"
        and "will be stopped" in _ac._agent_message(["A"], True)
        and _ac.AGENT_RESUME_PROMPT in _ac._agent_message(["A"], True)
        and "not restarted by the tracker" in _ac._agent_message([], False)
        and _ac._agent_was_busy("waiting", 0) and not _ac._agent_was_busy("idle", 0)
        and __import__("aitracker.providers.claude", fromlist=["x"]).session_state("x", "shell") == "busy"), \
    "agent upgrade: descriptors / version parser / warning text / busy rule"
```

## 12. README and CLAUDE.md lines (S8)

**`README.md`:**
- **Line 7.** "Nothing is sent anywhere." becomes "Nothing is sent anywhere, except when you press a button that runs
  an updater: the tracker's own Update (a `git fetch`), or an agent's Doctor/Upgrade, which runs that agent's own CLI."
- **Under "## Terminal — on by default"** (line 84), add a new subsection `### Agents: Doctor and Upgrade`:
  > Config → **Agents** lists each agent CLI the tracker manages that is installed (Claude Code, Auggie) with its version. **Doctor** runs `claude doctor` and shows its output. **Upgrade** runs `claude update` (or `auggie upgrade --skip-confirmation`) — always the latest, only when you press it. Before anything happens you get a warning naming every session in a tracker terminal that will be stopped, with its version. After the update succeeds — even when nothing new was installed — each one running a version other than the installed one is stopped (SIGTERM, then SIGKILL if needed; the commands it started, background shells included, are stopped too) and resumed in a tracker terminal with `claude --resume`; sessions that were working or waiting on you get the prompt "continue, re-read CLAUDE.md", idle ones are just resumed. A tracker terminal showing a background session is stopped with `claude stop <job>` and resumed in that terminal *(only if V6d passed)* — it then runs as a terminal session, and ends if the tracker stops. Sessions not running in a tracker terminal — another terminal app, a background session with no tracker terminal, the Claude desktop app — are only listed, with their version and the command to run. A failed update stops nothing. When it finishes, a notification says which sessions were resumed, which got the prompt and which failed. Claude Code also updates itself in the background; the tracker leaves that alone, and a new version only takes effect when a session restarts. Known gaps: Auggie records no version and its sessions are not restarted (one in a tracker terminal is listed only if it wrote its log recently); a session whose permission prompt Claude Code does not report may be resumed without the prompt; the Claude background daemon itself is not restarted, so new background jobs may start on the old version until it restarts; *(only if V3b showed it)* after `/clear` inside a tracker terminal the tracker may resume the earlier conversation.
- **In "## Adding a tool"** (line 231), add the line: "Optional: set `agent_cli` (and `running()`) on the provider to
  get Doctor/Upgrade in Config → Agents."

**`CLAUDE.md` line 30.** "Add a tool = one module in `providers/` + one line in `PROVIDERS` + a `SRC` label in
`web/app.js`." gains " (+ an optional `agent_cli` descriptor / `running()` for Config → Agents)".

## 13. Verify results (filled in at S0)

| Step | Result | Decision |
|---|---|---|
| V2r (incl. `kind == "interactive"`, no agent view) | **PASS** (S0 run 2026-11-16). Transcript made by 2.1.323 (`-p`, lines `version` 2.1.323). `claude --resume <id> 'continue, re-read CLAUDE.md'` typed in a pty login shell: pid file `sessionId == <id>`, `kind=interactive`, `entrypoint=cli`, `version=2.1.325`, no `parkedJobId`; `pid` == the pane's foreground pgid; transcript gained the `user` prompt line (version 2.1.325) plus 2.1.325 assistant lines; pane showed the conversation (idle prompt), not the agent view. **Trap found:** a pane shell that inherits `CLAUDE_*` env (here `CLAUDE_JOB_DIR`, `CLAUDECODE`, from a background job) makes the resumed Claude write NO pid `.json` (only `<pid>.<hash>.key`) and no transcript lines. Shell startup here is also slow (pyenv rehash lock, 60+ s). | Resume lands on the new binary as an interactive session: S3-S5 proceed. `open_pty` must not leak `CLAUDE_*` job vars into pane shells (the tracker is normally not a job child; add a test/README note). |
| V3b (pid file follows `/clear`?) | **PASS: follows.** After `/clear` in the pane the pid file's `sessionId` changed to a new id (same pid, status idle) and a new transcript file appeared; the old id's transcript stayed behind. | B2 stands (pid file beats label). No README gap needed. |
| V5 | **PASS, with a caveat.** SIGTERM to the pane's foreground pgid (claude's pgid): leader exited in 2.39 s (< 8 s `PARKED_DETACH_WAIT`); pid file removed; shell back at its prompt on the same tty; transcript 0 unparseable lines, last line a complete assistant text; the tool child (`zsh -c` wrapper + `sleep 300`, in its OWN pgid, ppid = claude) gone within 1 s. Caveat: this environment blocks a foreground `sleep`, so Claude ran it as a `run_in_background` shell (Claude idle at its prompt, "1 shell still running"); a mid-turn foreground tool was not exercised. | SIGKILL fallback not triggered. Orphan sweep (§5.3) stays as the backstop and must not assume tool children share claude's pgid. |
| V6 (stop half) | PASS (reconcile, D9 scratch job): short id only; stop ~2 s; worker gone ≤ 4 s; pid file removed; tool child died | S5 built |
| V6d (pane half) | **PASS.** `claude --bg` job (kind=bg); pane `claude attach <short>` showed the thin client (reply `ok`, idle prompt). `claude stop <short>` from a plain shell, stdin `/dev/null`: rc 0 in 2.6 s; roster `pid` and `replPid` both gone by 4.9 s; the attach client exited to the shell by itself at 5.5 s (no SIGTERM needed). Then `claude --resume <job session id> 'continue, re-read CLAUDE.md'` in the pane opened the conversation, no background-session refusal: pid file `kind=interactive`, no `parkedJobId`, `version=2.1.325`, prompt line in the transcript. | S5 lands; `AGENT_RESTART_DAEMON` stays True. |
| V7 | **PASS.** Permission prompt (`--permission-mode default`, Bash `touch` in the scratch folder; plain `ls` is auto-allowed here so never prompts): pid file `status: "waiting"`, `waitingFor: "permission prompt"` (daemon jobs showed "input needed"). `_tail_scan` gave `last == "assistant_tool"`. After answering No: `status: idle`, `waitingFor` None. | Design stands: busy = any status but `idle` (`waiting` counts). The `session_state` tail fallback is not needed. |
| V8 | **PASS.** `claude doctor </dev/null` with cwd=`~`, scrubbed env: rc 0, 885 bytes. Output names no tracker checkout path or settings file; its only "Invalid settings" line concerns `~/.claude.json` (a missing MCP env var). | None. |
| V9 (S9: Auggie Upgrade — rc, output) | **PASS, but NOT "already latest".** Real `auggie upgrade --skip-confirmation` via the product route (`POST /api/agents/run`, warning had empty `stop`/`outside`): job `done`, `old` 0.37.1, `new` 1.2.1 (a major jump; `auggie --version` afterwards 1.2.1), 32 s. Output "Upgrade Information: Current version 0.37.1, Target version 1.2.1 … Upgrade complete!". Summary: "Auggie 0.37.1 → 1.2.1. Auggie sessions are not restarted by the tracker; restart them yourself once the upgrade lands." Server log line identical. | The §3 "Auggie already on latest" assumption was stale; the summary is honest either way. |

### S9 live proof (run 2026-11-16, scratch server on 127.0.0.1:8799, worktree HEAD working tree; driven only through the HTTP routes)

Setup: own server (PID recorded, stopped by PID), env scrubbed of `CLAUDE_*`, five tracker panes opened with `mode: "resume"` (busy: Bash `perl -e "sleep 550"` in the foreground; waiting: `--permission-mode default` + a Bash `touch`, pid file `status: waiting`, `waitingFor: permission prompt`; idle; one `claude --bg` job pane = a thin client; one older-binary pane), one session in Terminal.app, each in its own `s9-*` folder (trust prompt accepted for those folders only). Because this machine's default is auto mode, the waiting session needed a manual `claude --resume <id> --permission-mode default` in its pane. Older-binary sessions: a PATH shim in the pane shells (scratch ZDOTDIR) ran `DISABLE_AUTOUPDATER=1 .../versions/2.1.323` once per marker file; the tracker's own `claude --version` stayed 2.1.325.

| Check | Result | Evidence |
|---|---|---|
| Warning lists only my scratch sessions | PASS | `stop[]` held only `s9-*` cwds (4 current rows + 1 older row on press 1; 5 rows on press 2; 7 rows on press 3); `cannot_stop` empty on every press |
| Warning text | PASS | "The following sessions: <titles> will be stopped, you might have to continue again with a prompt once the upgrade lands. The tracker restarts each one on the new version as soon as the update finishes. A session that is working, or waiting on you for a permission or an answer, when it is stopped is resumed with the prompt “continue, re-read CLAUDE.md”; an idle one is resumed and left waiting for you. A session already on the new version is left running. Even if nothing new is installed, a session running an older version than the installed one is restarted onto it." |
| Row version_text | PASS | current: "already on the installed v2.1.325 — restarted only if a newer version installs"; older: "runs v2.1.323, older than the installed v2.1.325 — restarted even if nothing new is installed" |
| Row state_text | PASS (wording nit) | busy "working now — its current turn will be interrupted, then resumed with the prompt Commands it started …"; waiting "waiting on you (a permission or a question) — that prompt will be cancelled, then resumed with the prompt Commands …"; idle "idle — resumed without a prompt Commands …". Nit: no full stop before " Commands it started" (agent_cli.py `AGENT_STATE_*` lines 46-50 lack a trailing period; `AGENT_STATE_KIDS` starts with a space only). |
| Daemon row sentence | PASS (text only) | `daemon: true`, command `claude stop a05d57b3` then `claude --resume <id>`, state_text ends "It runs in Claude's background daemon now; it comes back as a session in this tracker terminal, which ends if the tracker stops." The daemon row was on the current version, so the actual stop-and-move was NOT RUN (outcome `current`, job untouched, pid 89066 unchanged). |
| D8: nothing new to install, older session still restarted, current ones left running | PASS | Presses 1-3: `claude update` output "Claude Code is up to date (2.1.325)", job `old == new == 2.1.325`, summary "nothing new was installed". Press 2 (shim removed): only the 2.1.323 session restarted (pid changed, pid-file `version` 2.1.325, same tty); busy/wait/idle/daemon pids unchanged and the busy session's `perl sleep` still alive. Press 3 (busy, wait, idle and old all on 2.1.323): those four restarted, the 2.1.325 daemon row left running. |
| Prompt only to busy + waiting | PASS | Transcript `type:user` lines containing "continue, re-read CLAUDE.md": busy 1, wait 1, idle 0, old 0 (before each press 0). Items: busy/wait `outcome: prompted, prompt_seen: true`; idle/old `unprompted`. Summary: "Resumed with “continue, re-read CLAUDE.md” (were working or waiting): s9-busy…, s9-wait…. Resumed without a prompt (were idle): s9-old…, s9-idle…. Already on 2.1.325, left running: s9-bgtrust…. Not started here, left alone: 11 (2 out of date)." |
| Pid-file version after resume | PASS | Each resumed session: `kind interactive`, no `parkedJobId`, `version 2.1.325`, `on_version: true` |
| tty kept | PASS | `tty_after == tty` for every restarted folder pane |
| Honest wrong-version report | PASS (rig artifact) | Press 1 with the shim still forcing 2.1.323 for `s9-old`: item `unprompted`, detail "resumed on v2.1.323, expected v2.1.325 — another claude may be first on your shell's PATH; run Doctor"; summary "Not confirmed on 2.1.325 yet: …" |
| No orphaned sleep | PASS | Old `perl -e sleep 550` pids (53908, 9399) gone after their session was stopped; the only `perl sleep` afterwards was the resumed busy session's own re-run of its tool (the prompt made it redo the turn) |
| Outside list | PASS | 11-12 rows with `host` daemon (command `claude stop <short>`, `claude --resume <id>`), `tui` ("not started from this dashboard — exit it, then run:" + `claude --resume <id>`), `desktop` ("runs inside the Claude desktop app; it updates with the app", no command); `out_of_date_text` "out of date (installed v2.1.325)". My Terminal.app session listed as `tui`, idle, never stopped (same pid and pid file at the end). A manually started `claude` in a session-less folder pane is `tui` outside, not a stop row (not claimed by a tracker resume). |
| D15 duplicate | PASS | Same session open in two tracker terminals (both pid files `version 2.1.323`; the second pane was labelled for another session). Warning rows carried `relabelled_text` "now runs this session (the terminal was opened on a7c5a441)" and `dup_text` "the same session as terminal 41062eeabce1 — this terminal is stopped; the session comes back once, in a tracker terminal". Result: both processes gone, one new pid (pid file `version 2.1.325`); items `unprompted` (primary) and `closed` "stopped; the session was resumed in terminal 41062eeabce1"; summary "…s9-dup2 …: stopped; the session was resumed in terminal 41062eeabce1." |
| Completion summary + server log | PASS | Server stderr carried "agent upgrade: restarting <title> (<id>); if this dashboard dies, resume it with: claude --resume <id>" per session and the identical summary line as `job.summary` |
| Real `claude update` installing a release | NOT RUN | No newer release existed: 2.1.325 before and after, every press |
| Toast after closing Config | NOT RUN | No browser driven; server-side job state only |
| Defects | none blocking | wording nit above; environment notes: a stale `~/.pyenv/shims/.pyenv-shim` lock (dated 12:58) made every login pane shell take 60 s plus the tracker's "shell never reached its prompt — claude was not started" notice (scratch ZDOTDIR used instead; the user's file untouched); a pane or Terminal.app shell inheriting `CLAUDE_*` writes no pid `.json` and so is invisible (V2r trap, reproduced in Terminal.app via osascript) |

## 14. Deliberately left out

- Version pinning, rollback, scheduling, auto-trigger and any config key (clauses 5 and 7).
- Touching Claude Code's auto-updater, or `DISABLE_AUTOUPDATER` (clause 8). Only the note is shown.
- Stopping anything not in a tracker pane: other terminals, background sessions without a tracker pane, and
  desktop-app sessions (clause 4).
- Auggie stop/resume, Auggie doctor, and the Augment VS Code/Cursor extensions (they have no CLI, and Auggie cannot be
  resumed: `term_vt.py:3083-3084`).
- **F8 extras: page-load catch-up and `sessionStorage` bookkeeping (cut by the reconcile).** The notification is the
  toast from the module poller plus the server log line.
- From v2: the `cli_version` list field, `util.run_argv`, `_same_origin`, per-session transcript polling for verify,
  and every copied helper (cuts and D7).
- An out-of-date chip on board tiles; the classic UI; a job state file; `_with_prompt` for anything beyond the resume
  arm.
- Merge TODOs or a `sys.modules` probe for `update.py` (F10 verdict).
- From the final review: `daemon_job_short` (the pid file's `jobId` is the short), a CSS rule (none exists to copy),
  V6 step 5 (answered: the full id is rejected), resuming a daemon session back into the daemon (no measured argv),
  restarting the Claude daemon supervisor, and the pre-existing bundle duplicates `file_diffs`/`command_output`
  (claude/auggie), `_root`, `_git_env`.

## 15. Decisions the user may still want to overrule

1. **What counts as "busy" for the prompt (D6).** The plan sends "continue, re-read CLAUDE.md" to a session that, at
   the moment it is stopped:
   - has tool work running, or
   - has any pid-file status other than `idle` (`busy`, `shell`, `waiting`, or one not seen yet).

   The `waiting` status means a permission prompt **or** an unanswered AskUserQuestion. The alternative is to treat an
   unanswered question as idle, so the session comes back with the question cancelled and no prompt. Recommended: keep
   it busy. It was mid-turn, and "continue" lets it re-ask.
2. **Notification when the page is reloaded mid-job.** With F8 cut down, a tab reloaded during the job gets no toast.
   The summary is still shown in Config → Agents (the last job is kept in memory), and it is in the server log. The
   page-load catch-up could be restored if the user wants the toast to survive a reload.
3. **D8 when `claude update` itself fails.** The plan stops nothing on a failed update run, even if some sessions run
   an older version than the one already installed. The alternative is to restart those onto the installed version
   anyway. Recommended: keep "a failed update stops nothing" — a failing updater can mean a half-written install, and
   pressing Upgrade again after a fix restarts them.
4. **D5's side effect.** Restarting a background (daemon) session in a tracker pane turns it into a terminal session
   that ends when the tracker stops or updates itself. On this machine that is most tracker panes. The alternative is
   show-only for daemon panes (the two commands). Recommended: keep D5 as decided; the warning states the change.
5. **Unknown version with nothing installed.** A session with no pid file (so no known version) is left running when
   the update installed nothing, and restarted when it did. The alternative (D2's "force all") restarts it every
   time. Recommended: leave it running — D8 says "differs", and there is no evidence it does.
6. **S9 scope.** S9's live proof needs more scratch sessions than D9 approved (three panes, one outside session, one
   old-version session, one job). It needs a fresh OK.

## Log

- 2026-11-16: plan v3 (opus plan agent). Grounded on this worktree at `fe8f580`. Real-file checks: pid-file key names
  and `status`/`waitingFor` values (§3); retained old binaries; `term_gate.guard` Host check; bundle collision test.
  Missed-by-both defects added: M4 (bundle names), M5 (internal Host), M6 (stale `fg`).
- 2026-11-16: final plan (opus adversarial reviewer, second pass). Folded in D8-D10, the V6/V5/D10 live results and
  Consequences 1-4 from `agent-upgrade-reconcile.md`, and every finding of `agent-upgrade-review-v3.md` (B1-B2,
  S1-S8, N1-N11). M6 judged overstated (`_session_ptys` already refreshes, `term_vt.py:3533-3536`); its check is kept.
