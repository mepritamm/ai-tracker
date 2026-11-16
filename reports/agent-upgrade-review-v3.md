# Agent upgrade — adversarial review of plan v3 (second pass)

Reviewed 2026-11-16 by an opus reviewer, against worktree `.claude/worktrees/agent-upgrade` at `fe8f580`.
Target: `agent-upgrade-plan-v3.md`. Authority on decisions and measurements: `agent-upgrade-reconcile.md`
(D1-D10, "Live check results", "Consequences"). Every `file:line` below was read in this worktree. No product
code was touched, nothing was executed except read-only `ps`, `ls`, key-name reads of `~/.claude/settings.json`,
and enum-field reads (`kind/entrypoint/version/status`) of `~/.claude/sessions/*.json`.

Verdict: **not ready to implement as written.** Two BLOCKERs (S0 cannot run on this machine; a restart can act on
the wrong conversation), eight SHOULD-FIX, eleven NITs. All are folded into `agent-upgrade-plan-final.md`.

## What v3 got right (checked, no finding)

- **§5.2 `update.py` edits.** `_APPLY` is at `update.py:27`, `_run(argv, timeout, env=None)` at `update.py:62-80`
  (Popen at 67-68, no `cwd`), and the 409 insertion point right after `_APPLY.acquire` at `update.py:266-267` is
  correct and releases `_APPLY` before returning. Each side takes its own lock then checks the other: under the
  GIL at least one side sees the other, so both can never proceed.
- **"update cannot import agent_cli".** True. `scripts/bundle.py:41-43` strips only column-0 `import`/`from` lines,
  so a function-level `from .agent_cli import …` inside `update.py` would survive into `dist/tracker.py`, and
  `tests/test_integration.py:1739` asserts `"from ." not in src`. Putting both locks in `update.py` is right.
- **M4.** `tests/test_integration.py:1751-1763` does assert one `def status` and one `_run`; `tunnel.py` owns
  `status`/`start`. Real.
- **M5.** `term_gate.guard` refuses an empty Host when `TRACKER_AUTH` is unset (`term_gate.py:69-71`);
  `origin_matches_host` (`util.py:715-720`) passes with no Origin. `open_pty` touches only `handler._json` and
  (through `guard`) `handler.headers` — grep of `term_vt.py:2962-3349` finds 20 `handler._json` and nothing else.
  `headers = {"Host": "127.0.0.1"}` is the right fix.
- **M6** is **overstated**: `_session_ptys` already calls `_refresh_fg` and re-checks before counting a folder
  pane as a hit (`term_vt.py:3533-3536`). The `fg is None` check in `stop_for_upgrade` is still a cheap, correct
  confirmation — kept, but it is not a defect v1/v2 had.
- **Retained binaries.** `~/.local/share/claude/versions/` holds `2.1.321`, `2.1.322`, `2.1.323`, `2.1.325`;
  `~/.local/bin/claude` → `2.1.325`. The claim stands, with the two caveats in S8.
- **The resume arm.** `open_pty` builds `argv = term_gate.resume_argv(sid)` at `term_vt.py:3118`; adding
  `_with_prompt` there reaches every later use of `argv` (sync inject `term_vt.py:3288`, deferred start `3264-3266`,
  swap `3308`, overflow spawn `3318`). The fork/attach backstops rebuild argv and drop it, as v3 says.

## Findings (most severe first)

### B1 — BLOCKER: the S0 verify procedures start a plain `claude`, which opens the agent view on this machine

- **Defect.** V2r step 1 runs `~/.local/share/claude/versions/2.1.323` bare, V5 step 1 runs
  `claude --allowedTools …` bare, V6 step 1 and V7 step 1 run `claude` bare, all in a tracker pane
  (plan-v3 §4). Reconcile V5 row: "On this machine a plain `claude` under a pty opens the agent-view TUI, not a chat
  session; a typed prompt dispatches a background job. No interactive pid file or transcript appeared." The same
  hazard is recorded in `docs/folder-terminal-reuse-plan.md:606` ("`mode:"new"` opens the AGENT VIEW … on this
  config"). Repro: run V2r as written → "say ok" dispatches a **background** job; `/exit` leaves the agent view;
  step 3's `claude --resume <id>` then targets a live daemon job and converts to `claude attach <short>`
  (`docs/folder-terminal-reuse-plan.md:542`), so the pid-file check reads the old worker or nothing. Actual: no
  measurement of the interactive path at all. Expected: an interactive scratch session on the old version, resumed
  on the new one. V5 and V7 fail the same way. Consequence (4) ("the plan must say how the tracker's own launches
  avoid the agent-view TUI") is not addressed anywhere in v3.
- **Check 3 — how the tracker's own resume behaves.** The upgrade only ever opens `mode: "resume"`; its argv is
  `[launcher, "--resume", sid]` (`term_gate.py:300`, built at `term_vt.py:3118`), plus the prompt after the fix,
  typed into the folder shell by `_inject_argv` (`shlex.join`, `term_vt.py:1953`) or exec'd in an overflow pty
  (`term_vt.py:3318`). It names a session, so it does not open the bare agent view — that is `mode: "new"`'s
  `[gateway.launcher(...)]` (`term_vt.py:3125`), which the upgrade never sends. It **can** land somewhere other than
  an interactive TUI on the new binary in two ways: (a) when the daemon still hosts the id, the CLI turns
  `--resume` into `claude attach <short>` on the old worker, and the backstop's `_retry_with_attach`
  (`term_vt.py:2862-2863`, argv `term_gate.py:395`) does the same — both drop the prompt; (b) whether
  `claude --resume <id> "<prompt>"` on 2.1.325 with this config stays interactive or is dispatched to the daemon
  like an agent-view prompt is **unmeasured**; V2r's pass criteria (sessionId + version) would pass in both cases.
- **Fix direction.** Change only the S0 procedures and V-step pass criteria; product code paths stay. Never start a
  bare `claude`/old binary in a pane. Never add `mode: "new"` anywhere in this feature.
- **Way.** §4: create the one scratch session non-interactively — `cd <scratch> && DISABLE_AUTOUPDATER=1
  ~/.local/share/claude/versions/2.1.323 -p "say ok" --output-format json` (read only `session_id`) — then open it
  in a tracker pane with the product path (`claude --resume <id> "<prompt>"` typed at the folder prompt, the exact
  string `shlex.join` produces). Add pass criterion `kind == "interactive"`, no `parkedJobId`, `version == 2.1.325`,
  and the pane's foreground pgid == that pid-file's `pid`. V5/V7 reuse the same session (`claude --resume <id>
  --permission-mode default` for V7; `--allowedTools "Bash(sleep:*)"` for V5). V6d uses the `claude --bg` job V6
  already proved. New §1 "How the clauses are read" bullet and §9 row stating (a)/(b) and the fallback (verify
  reports `AGENT_VERSION_MISMATCH` / `prompt_seen: false`; nothing is lost).
- **Test.** S0 itself: V2r fails unless `kind == "interactive"` (it would pass on a dispatched job today — red
  before). Unit: `test_agent_cli_jobs` (b) also asserts every `open_pty` body has `mode == "resume"` and no `mode ==
  "new"`, and `test_agents_ui`/`agent_cli` source grep finds no `"new"` mode literal.

### B2 — BLOCKER: the restart acts on the pane's label, which goes stale after `/clear` or `/resume` inside Claude

- **Defect.** `upgrade_candidates` takes `sid = (_pty_session_ids(p) or ("",))[0]` and consults the pid file only
  when that is empty (plan-v3 §5.3 step 3, F7). `_pty_session_ids` returns the claim's `fg["session"]`
  (`term_vt.py:3990-3997`), set once at open, and `resolve_spawned` never relabels a resume open ("A `resume` open is
  never a candidate", `term_vt.py:1991-1992`). Repro: resume X in a pane; inside it type `/clear` (or `/resume Y`);
  the process now runs Y (its pid file's `sessionId` is the live truth — V3) while the label still says X. Press
  Upgrade: the identity check passes (it is by pid, `pg == pid`), Y's process is killed, and `claude --resume X
  "continue, re-read CLAUDE.md"` starts an **unrequested turn in the old conversation X**. Y is not resumed. Expected:
  Y is resumed, X is untouched.
- **Fix direction.** For a pane whose foreground Claude has a live, procStart-verified pid file with `host == "tui"`,
  that file's `sessionId` wins over the label. The label is used only when there is no pid file (thin clients,
  `claude attach`) — those are daemon sessions whose id comes from the label + roster, unchanged. Do not change
  `_pty_session_ids` (the idle reap uses it).
- **Way.** §5.3 step 3: `e = run.get(pg)`; `sid = e["id"] if e and e["host"] == "tui" else label`; when
  `label and sid != label`, set `relabelled = label` on the candidate and show it in the warning row ("now runs
  <title Y> (was <title X>)"). The `session` field the confirm echoes is the resolved `sid`. Parked TUIs keep
  `host == "daemon"` and stay on the label path. S0 adds V3b: in the scratch session type `/clear`, read the pid
  file's `sessionId`. If it does NOT change, record that in §13 and state the gap in the README ("after `/clear`
  the tracker may resume the earlier conversation"); the fix above still covers `/resume` and any case where the
  file does follow.
- **Test.** `test_term_vt_upgrade`: a labelled folder pane with label "X" and `running_sessions` patched to
  `{pid: fg, id: "Y", host: "tui"}` → candidate `session == "Y"`, `relabelled == "X"`, command contains `Y`. Red on
  v3 (it yields "X").

### S1 — SHOULD-FIX: `session_state` is an allow-list; the measured `shell` status falls through (Consequence 2)

- **Defect.** Plan-v3 §5.1: `if status in ("busy", "waiting", "idle"): return it`, else the transcript fallback.
  Reconcile: a background job running a shell command reports `status: "shell"` (one live pid file reads `shell`
  right now). Repro: `session_state(sid, "shell")` with a transcript whose last line is assistant text → `"idle"` →
  `_agent_was_busy` False → the session is resumed **without** the prompt although it was mid-command.
- **Fix direction.** Any non-empty string status other than `idle` is busy; `waiting` stays `waiting`. Only a
  missing/non-string status uses the transcript fallback. No allow-list anywhere.
- **Way.** `session_state`: `if isinstance(status, str) and status: return status if status in ("idle", "waiting")
  else "busy"`. Same rule feeds `state_text`. Applies to TUI and daemon entries (both go through
  `session_state`).
- **Test.** `test_claude_running`: `session_state("S", "shell") == "busy"`, `session_state("S", "compacting") ==
  "busy"`, `"idle"` → idle, `"waiting"` → waiting. Red on v3.

### S2 — SHOULD-FIX: D8 is only implicit — the warning does not say who is restarted when nothing new installs

- **Defect.** D8 (after v3): Upgrade always ends by restarting every tracker session whose running version differs
  from the installed one, even when nothing was installed; same warning first. v3's flow happens to proceed when
  `old == new` (§5.4 step 5 skips only `version == new`), but (a) the warning lists every stoppable session as
  "will be stopped", including ones already on the installed version that will be left running — the user cannot
  tell which will actually restart; (b) a candidate with version `""` (no pid file) is always restarted, so pressing
  Upgrade with nothing to install restarts sessions with no evidence that they differ; (c) §2/§9/§15 never mention
  D8. Repro: installed 2.1.325, pane A on 2.1.323, pane B on 2.1.325 → warning says both "will be stopped"; only A is.
- **Fix direction.** Keep update-first and "a failed update stops nothing". Add a per-row server-written
  `version_text` and split the message; unknown version is restarted only when the update actually changed the
  version. Do not add a second button or a config key.
- **Way.** §5.4 `agent_plan_upgrade`: per `stop` row, `version_text` = `AGENT_VER_OLD` (known and ≠ cached
  installed), `AGENT_VER_CURRENT` (== installed), or `AGENT_VER_UNKNOWN`. `_agent_job_upgrade` step 5: a
  candidate with `version == ""` and `old == new` → `outcome "current"`, detail `AGENT_VER_UNKNOWN_SKIPPED`, with its
  command. Summary part 1 when `old == new`: `"{label} is already on {new}; nothing new was installed."` §6 adds the
  texts. Auggie unaffected (`restarts_sessions False`).
- **Test.** `test_agent_cli_jobs` (p): stub update leaves the version unchanged; candidates on 2.1.323, 2.1.325 and
  "" → only the 2.1.323 one is stopped; summary says "nothing new was installed". (q): the 409 body rows carry the
  three `version_text`s. Red on v3 (the "" one is stopped; no `version_text`).

### S3 — SHOULD-FIX: D5 is the main path here, V6 has passed, and the restart changes where the session lives

- **Defect.** Live pid files now: 6 `bg` jobs and 4 desktop sessions, zero interactive CLI TUIs; tracker panes on
  this machine mostly show `claude attach` thin clients of daemon jobs (a `--resume` of a hosted id converts to
  attach, `term_vt.py:3352-3358`). v3 treats S5 as optional ("only if V6 passed") and still carries V6 steps 3-5 as
  open; V6 has passed for `claude stop <short>` + resume (reconcile), and the full id is known to be rejected. And
  D5's restart resumes a **background** session as an interactive TUI in a tracker pane: after it, the session dies
  with the tracker (or the tracker's own Update, `update.py:343-362` execs and closes every pty) — a durable change
  the warning never states.
- **Fix direction.** S5 is built (AGENT_RESTART_DAEMON = True). Only V6(c)/(d) — the pane part — stays in S0 and
  still gates S5 landing. The warning row for a daemon candidate says it comes back as a terminal session. Do not
  add a "resume back into the daemon" path (no measured argv for it).
- **Way.** §3 V6 row = PASS (stop by short id; full id rejected; stop ~2 s, worker gone ≤ 4 s, foreground tool
  child dies, pid file removed). §4 V6 reduced to (c)+(d) on the D9 job. §5.4 `state_text` for daemon rows appends
  `AGENT_STATE_DAEMON_MOVE`. Delete V6 step 5 and §7's "If V6 fails" paragraph keeps only the (c)/(d) case.
- **Test.** `test_agent_routes`: a daemon candidate's 409 row `state_text` contains "terminal session". Jobs (n) as
  in v3. Red on v3 (no such text).

### S4 — SHOULD-FIX: the shared job dict is mutated while another thread serializes it; item shape is unspecified

- **Defect.** `_AGENT_JOB` is returned by `agent_status()` (GET every 2 s) and in the 202 body, while the job
  thread sets `job["step"]`, appends to `job["items"]`, and `_agent_verify` adds new keys (`on_version`,
  `prompt_seen`, `detail`) to existing item dicts (plan-v3 §5.4). `json.dumps` iterating a dict that gains a key
  raises `RuntimeError: dictionary changed size during iteration` → a 500 to the poller, and a cheaper implementer
  has no item schema to pre-declare.
- **Fix direction.** Snapshot under a lock; fixed item schema with every key present from creation.
- **Way.** `_AGENT_JLOCK = threading.Lock()`; every write to `_AGENT_JOB` or an item goes through
  `with _AGENT_JLOCK:`; `agent_status()`/`agent_start()` return `json.loads(json.dumps(job))` taken under it.
  Item = `{tty, session, target, title, daemon, outcome, detail, command, tty_after, forked, on_version, prompt_seen,
  size_before}` (None/""/[]/0 defaults) created complete.
- **Test.** `test_agent_cli_jobs` (r): a thread mutating items in a loop while another calls `agent_status()` 500
  times → no exception, every snapshot has all 13 item keys. Red on v3 (KeyError on missing keys; intermittent
  RuntimeError).

### S5 — SHOULD-FIX: the orphan sweep signals pids captured seconds earlier; a recycled pid is someone else

- **Defect.** `stop_for_upgrade` step 8 and `_agent_restart_daemon_pane` step 6 take `kids` (pids only, from
  `_claude_work_children`, `term_vt.py:3933-3960`) before an up-to-8 s + 2 s wait, then `killpg(getpgid(pid))` for
  any pid "still alive". A tool child that exited in that window can have its pid reused; the sweep then
  SIGTERMs/SIGKILLs an unrelated process group.
- **Fix direction.** Kill only a pid whose start time is unchanged; never widen the sweep.
- **Way.** Capture `kids = [(pid, claude._ps_lstart(pid)) …]` (`claude.py:611`) right after `_claude_work_children`;
  before each signal require `_ps_lstart(pid) == lstart != ""`. One helper `_agent_sweep(kids)` in `term_vt` used by
  both paths, keeping the `g not in (0, os.getpgrp(), pt.pid)` guards.
- **Test.** `test_term_vt_upgrade`: a kid entry whose recorded lstart differs from the live one → `os.killpg`
  (patched) never called. Red on v3.

### S6 — SHOULD-FIX: the daemon stop is "confirmed" by a read that fails open

- **Defect.** `_agent_restart_daemon_pane` step 4 waits for `daemon_repl_pid(target) == 0`. `daemon_repl_pid`
  returns 0 when the roster is missing, mid-write/unparseable, or the supervisor pid reads dead
  (`claude.py:581-591, 602-608`). Repro: roster rewrite during the wait → 0 → "stopped" → resume while the worker
  lives → the CLI converts to `claude attach` on the old worker (B1a); prompt dropped.
- **Fix direction.** Confirm on the worker's own pids, captured before `claude stop`.
- **Way.** Before stop: `w = _live_workers()[short]`; record `w["pid"]` and `w["replPid"]`. Confirmed = both raise
  `ProcessLookupError` on `os.kill(p, 0)` within 8 s. Roster read stays as a second check only.
- **Test.** Jobs (n'): `daemon_repl_pid` patched to 0 while the recorded worker pid (a live `sleep`) is alive → no
  open, outcome unconfirmed. Red on v3.

### S7 — SHOULD-FIX: a confirmed stop can still end unresumed (slot cap, other folder, duplicate panes)

- **Defect.** (a) `open_pty` resumes in the folder shell for `session_cwd(target)`, not the stopped pane
  (`term_vt.py:3099-3100, 3157`). A session that moved into a worktree (common here) gets a new folder shell; if
  `_live_count() >= config.MAX_TERMS` that open answers 429 (`term_vt.py:3161-3170, 3314-3316`) — stopped, not
  resumed, and the preflight never checked. (b) Two panes showing the same daemon session are two candidates; the
  second `claude stop` fails ("No job matching") and is reported "still running in the background", which is false.
- **Fix direction.** Preflight the slot; dedupe by target. Keep "failed → listed with its command".
- **Way.** `upgrade_candidates`: per candidate `cwd_to = term_gate.session_cwd(target, resume=True)`;
  `needs_slot = not any(p.folder and p.cwd == cwd_to for p in panes)`. `_agent_restart_one`/daemon path re-check just
  before the stop: `needs_slot and tv._live_count() >= config.MAX_TERMS` → outcome failed `AGENT_NO_SLOT`, nothing
  stopped. `_agent_split` keeps the first candidate per `target`; others `cannot_stop` with `AGENT_REASON_DUP`.
  Summary shows `tty_after` when it differs ("resumed in a new terminal").
- **Test.** Jobs (s): `MAX_TERMS` reached, `needs_slot` True → zero `stop_for_upgrade` calls. `test_term_vt_upgrade`:
  two panes with the same target → one stoppable. Red on v3.

### S8 — SHOULD-FIX: S0 exceeds D9's approved scope, and the old-binary run can change the install

- **Defect.** D9 approved "one scratch session, one scratch background job". v3 S0 creates a session for V2r, one
  for V5, one for V7, a parked job for V6 and a second job for V6 step 5. Also running an old binary with
  `autoUpdatesChannel: latest` (settings key present) can kick off the background auto-updater, and a later
  `claude update` may prune the retained versions V2r needs.
- **Fix direction.** One session reused sequentially (V2r → V3b → V7 → V5), one `claude --bg` job for V6d; old binary
  run with `DISABLE_AUTOUPDATER=1` in that one command's env only (the product never sets it — clause 8). S0 runs
  before S9's real update.
- **Way.** §4 rewritten as one ordered script (final plan §4).
- **Test.** Teardown report lists exactly one session id and one job short.

### N1 — NIT: Auggie (D10) results not folded; failure text points at a Doctor Auggie lacks

- **Defect.** v3 §3 lacks the D10 row (0.36.0 → 0.37.1, 28.4 s, `--version` 3.6 s, alias `update`, "already up to
  date" rc unmeasured). `AGENT_FAIL_UPDATE` says "Run Doctor to see why" for Auggie (`doctor: None`).
- **Fix.** Fold the row; `AGENT_FAIL_UPDATE_NODOC` for agents without Doctor ("see its output below"); if rc ≠ 0 and
  the version is unchanged, the summary says "still on {old}". S9 runs Auggie Upgrade once (now a no-op) and records
  the rc in §13 (V9). Test: jobs (m) asserts Auggie failure text has no "Doctor".

### N2 — NIT: the `agent_` prefix is already claude.py's subagent namespace

- **Defect.** `providers/claude.py` defines `_agent_group` (411), `_agent_files` (1109), `_agent_cache_on` (1231),
  `_agent_file_pass` (1244), `_agent_entry` (1388), `agent_detail` (1702), all flattened into the bundle. Today no
  name in v3's list collides, but the test only checks listed names. Pre-existing duplicates in the bundle today:
  `file_diffs`, `command_output` (claude/auggie), `_root` (schedule/update), `_git_env` (pending/update).
- **Fix.** Keep the names; make the test generic: parse `agent_cli.py` and the new names added to `claude.py`/
  `registry.py`, and assert each appears exactly once in the bundle. Red if any new name shadows another.

### N3 — NIT (cut): `daemon_job_short` duplicates data `running_sessions()` already emits

- The bg worker's pid file carries `jobId` (the short, V6); `running_sessions()` emits it as `job`. Use the
  `entry["job"]` of the `kind == "bg"` entry. Cut the helper and its test.

### N4 — NIT (cut): there is no `.cr-update-confirm` CSS rule to copy

- `grep -rn cr-update-confirm aitracker/web/` finds it only in `ext_cr_dialogs.js:1255-1256`. Drop the CSS step;
  give the box both classes `cr-update-confirm cr-agents-confirm` (the test keys off the second).

### N5 — NIT: `session_state` raises when there is no transcript

- `_tail_scan(None)` → `os.path.getsize(None)` raises `TypeError`, outside its `except OSError`
  (`claude.py:151-152, 228`). Guard: `path = find_session(sid); if not path: return ""`. Test: `session_state("nope")
  == ""`.

### N6 — NIT: `prompt_seen` can be true from an earlier upgrade's identical line

- Record the transcript size just before the open; `user_line_has(sid, text, since=size)` scans only bytes after it.
  Test: a transcript already containing the prompt line → False until a new line is appended.

### N7 — NIT: the rule-6 exception names the wrong module and contradicts F7/D5

- The signalling lives in `term_vt.stop_for_upgrade`, not `agent_cli`; and "never stops … a session the tracker did
  not start" contradicts stopping a hand-typed `claude` (F7) and `claude stop` of a daemon job (D5). Reword to
  "only the sessions running in, or shown by, the tracker's own terminals" and name both modules (final plan §7).

### N8 — NIT: route and start edge cases

- The route builds the 409 preview even while a job runs (a second tab sees a stale warning) → skip the preview when
  `agent_job_running()` or `_APPLY.locked()`. `agent_start`'s "the tracker is updating itself" branch on its OWN lock
  is unreachable as stated — the only holder is a job → one message. If `Thread.start()` raises, release the lock.
  `body` can be a non-dict JSON value (`server.py:636`) → 400 before `.get`.

### N9 — NIT: a pending-work scan can see a stopped session's worktree as unused

- `pending.py:224-236` counts a worktree as live from live pid files' `cwd`; between stop and resume that file is
  gone. Hold `_pending_lock()` (as `update_apply` does, `update.py:268-277`) for the restart phase; if it cannot be
  taken, 409 "a pending-work scan is running — try again shortly". Test: lock held → 409.

### N10 — NIT: reason text for a pane in the agent view

- A pane where the user typed bare `claude` shows the agent view: Claude in the foreground, no label, no pid file →
  "the tracker cannot tell which session this terminal runs". Text: add "(for example Claude's agent view)".

### N11 — NIT: the warning does not say background shells the session started are stopped

- The orphan sweep kills `run_in_background` children too (a dev server Claude started). `AGENT_STATE_*` texts gain
  "commands it started are stopped too".

## Check 1 — decisions and Consequences

| Item | Status in v3 | Where / why |
|---|---|---|
| D1 wait for pending-work-worker | superseded by D7 | §2.1 |
| D2 skip current, unknown-id accepted, stop everything else incl. daemon panes | honoured | §1 reading, §5.3 table, S5 |
| D3 live check on scratch | done | §3 |
| D4 report only | moot | — |
| D5 tracker stops and resumes daemon panes | honoured, but treated as optional and the host change unstated | §5.4 S5 — S3 |
| D6 prompt only busy ones | honoured except `shell` | §5.1 — S1 |
| D7 build on pending-work-worker | honoured | §2.1 |
| D8 always restart outdated sessions, even with nothing installed; warning first | partly honoured (flow proceeds) — warning, unknown version and text not | §5.4 step 5 — S2 |
| D9 scratch scope: one session, one bg job | not honoured | §4 — S8 |
| D10 Auggie Upgrade, tested once | honoured in design; result not folded | §3 — N1 |
| Consequence 1 short job id | honoured (roster key) — V6 step 5 now moot | §5.3, §4 |
| Consequence 2 busy = anything but idle | contradicted (allow-list) | §5.1 — S1 |
| Consequence 3 V5/V7 runtime-safe | honoured | §5.3 steps 4-5, §4 V7 outcomes |
| Consequence 4 say how launches avoid the agent view | not honoured; S0 itself opens it | §4 — B1 |
| V2-resume "report resumed on vX, expected vY" | honoured | `AGENT_VERSION_MISMATCH` |

## Check 4 — failure paths on the v3 text

| Path | v3 behaviour | Verdict |
|---|---|---|
| Stopped, never resumed | Unconfirmed stop is never resumed; failed open is listed with its command; recovery line logged before each stop | OK, plus S6 (fail-open confirm) and S7 (slot / other folder) |
| Two presses | `_AGENT_JOB_LOCK` → 409 | OK, plus N8 (stale preview) |
| Server dies mid-job | Every pane dies as always; the one mid-restart is in the log line | OK. Note (final §9): a D5 session resumed into a pane now dies with the server — S3 |
| One agent succeeds, the other fails | Jobs are per agent, one at a time | OK; N1 for Auggie text |
| D8 restart with nothing installed | Proceeds, warning shown first | Partly — S2 |
| Auggie: upgrade only, listed, never stopped | `restarts_sessions False`, stop lists empty | OK. Known gap kept: an Auggie session in a tracker pane is listed only if its log was written within `LIVE_WINDOW` |

## Wider than the contract (cut in the final plan)

`daemon_job_short` (N3); the CSS step (N4); V6 step 5 (answered); the "If V6 fails" machinery is reduced to the
pane part (S3). Nothing else is wider than needed.

## Not examined

- `make check` on this branch; `scripts/bundle.py` was read, not run.
- Whether the pid file's `sessionId` follows `/clear` (B2 makes it an S0 step, V3b).
- Interactive `claude --resume <id> "<prompt>"` on 2.1.325 with this config (B1b; S0 V2r).
- A newer `claude stop` against an older daemon supervisor. Mixed-version workers coexist today (live pid files show
  2.1.323 and 2.1.325 `bg` jobs), so a version-mismatch daemon restart is not observed; a non-zero rc leaves the
  session untouched.
- The OpenRouter launcher passing a trailing positional prompt through.
- `ext_cr_dialogs.js` beyond the helper signatures (`crCall`, `crBtn`, `crReadOnly`, `toast` with `duration`,
  `sections` at 1318); the classic UI; `term_launch`/`term_run` tiers.
- `_resume_backstop` internals beyond the attach/fork retry sites.
