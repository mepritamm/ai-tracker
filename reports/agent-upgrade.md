# Agent CLI upgrade: Doctor and Upgrade buttons for the agents the tracker manages

Opened 2026-11-16. Branch `agent-upgrade` (worktree `.claude/worktrees/agent-upgrade`, cut from
`personal/main` @ `76bd154`). Status: **planning. No code until the user agrees to this plan (rule 8).**

## Contract (user's decisions, verbatim)

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

## 0. Corrections to the brief (found while grounding; these change the plan)

1. **`aitracker/update.py` is NOT on `personal/main`.** `git ls-tree personal/main aitracker/` has no
   `update.py`, and `.claude/rules/conventions.md` on main has no rule-6 exceptions at all
   (line 15 is the bare rule). `update.py`, `pending.py`, `schedule.py`, the `_local_caller`
   Host check, `util.is_loopback_host`, `term_vt._with_prompt` and the UI helpers
   `crCall`/`crBtn`/`crReadOnly` exist **only on the unlanded branch
   `personal/worktree-pending-work-worker`** (4 commits; its own durable file says every
   contract clause is "not discharged", and its live proofs are parked). The brief's repo map
   came from that branch.
2. **`_with_prompt` on that branch is dead code.** In its `open_pty`, the call
   `argv = _with_prompt(argv, body.get("prompt"))` sits **after the `return` inside
   `except gateway.GatewayError`** (branch `term_vt.py:3121-3126`), so it never runs. Its only
   test (`tests/test_pending_pty_prompt.py`) tests the helper, not the wiring, so the suite stays
   green. Report this to that branch's owner. This plan does not depend on it.
3. **The pending branch's `/api/update/*` POST routes have no Origin check** (no `Origin`
   anywhere in its `server.py`/`update.py`). `_local_caller` checks proxy headers, peer and Host,
   but a cross-site `fetch('http://127.0.0.1:8790/api/update/apply',{method:'POST',mode:'no-cors',body:'{}'})`
   from any web page arrives from loopback with a loopback Host and no auth. That branch's
   conventions text promises "same Origin". This plan adds the Origin check to its own routes
   (section 4). Report this to that branch too.
4. **A per-session Claude Code version IS recorded** (conventions rule 7, checked on real files).
   In the newest `~/.claude/projects/*/*.jsonl`, every `user`, `assistant`, `system`,
   `attachment` and `api-request` line has a top-level `"version": "2.1.323"`; metadata lines
   (`last-prompt`, `custom-title`, `queue-operation`, …) do not. **36 of the newest 300
   transcripts have more than one version** (e.g. `['2.1.322', '2.1.323']`,
   `['2.1.292', '2.1.295', '2.1.296']`). A resumed session appends to the same file under the
   binary it now runs on, so the inference "resume after update comes up on the new version"
   is strongly supported. It is still proved live in step V1 before the feature relies on it.
   The detail dict already carries it: `providers/claude.py:1830` copies `version` into
   `meta` (last value wins), and `web/app.js:1924` renders `v<version>`.
5. **Auggie records no version.** `~/.augment/sessions/*.json` top-level keys are `agentState,
   chatHistory, created, customTitle, modified, rootTaskUuid, sessionId, subAgentCostUsd,
   subAgentCreditsUsed, terminalId`. No version-like field anywhere in the 3 newest files.
   **Fallback:** live Auggie sessions are listed as "version unknown, restart to pick up the
   upgrade". The tracker never says they are out of date.
6. **`claude doctor` runs fine with no TTY.** `claude doctor </dev/null` in `/tmp` exited 0 in
   about 1 s and printed plain text: install method, path, auto-update channel and "Last update
   attempt: failed (install_failed) — 2026-11-15". On this machine the background auto-updater
   is failing, so Doctor is worth showing.
7. **Install facts on this machine.** `claude` → `~/.local/bin/claude` → symlink to
   `~/.local/share/claude/versions/2.1.325` (native install). The versions dir still holds
   2.1.321–2.1.325, and daemon processes run `…/versions/2.1.323` beside `…/2.1.325`, so a
   running session keeps its own binary across an update. `auggie` → `/opt/homebrew/lib/node_modules/@augmentcode/auggie/augment.mjs`
   (npm global). `claude --version` takes about 0.8 s and `auggie --version` about 2.8 s, too
   slow to run inside a request handler.
8. **Auggie cannot be resumed by the tracker.** `registry.py:30` sets `resumable = not p.prefix`,
   and `term_vt.open_pty` refuses `mode="resume"` for a non-Claude id
   (`term_vt.py:3072-3073`, "resume is Claude-only").

## 1. What is built (summary)

A new **Config → Agents** section with one row per agent CLI the tracker manages that is
installed: **Claude Code** and **Auggie**. Each row shows:
- the installed version, read in the background and cached;
- the note from clause 8, for Claude;
- a **Doctor** button, for Claude only, which runs `claude doctor` and shows its output;
- an **Upgrade** button, which runs `claude update` or `auggie upgrade`.

Upgrade always opens a warning first, and the server writes the warning text:
- the tracker-owned sessions it will stop (busy ones flagged);
- the clause-1 message;
- the auto-continue prompt;
- the outside sessions, shown only, each with the command to run.

On confirm, a background worker does the following, in this order:
1. **Update first.**
2. Verify the new version.
3. Stop and resume, one at a time, each confirmed session that is not already on the new
   version, using `claude --resume <id> "continue, re-read CLAUDE.md"`.
4. Check each resumed transcript for a line carrying the new version.
5. Report what was resumed, skipped and failed, in the panel and as a toast.

## 2. Ordering decision: update first, stop second (the risky spot)

Chosen order: **(1) read the old version → (2) run the update → (3) read the new version → (4) only
then stop and resume.** Why:
- A running session is not affected by the binary changing under it. Native install: each
  version lives in its own directory (fact 7), and `claude update` repoints the symlink. A
  session only picks up the new version when it restarts (established fact).
- So stopping before the update buys nothing, and an update that fails would leave every
  session dead on the old version for no reason.
- With update-first, **a failed update stops nothing**. Failed means rc ≠ 0, a timeout, a spawn
  error, or an unreadable `--version` afterwards. The job ends `failed`, with the update output
  tail and the hint "Run Doctor to see why". Every session keeps running.

There is one window that remains: the tracker process dies between stopping a session and
resuming it. Mitigations:
- Sessions are done **one at a time** (stop A → resume A → stop B …), so at most one session is
  down at any moment.
- Before each stop, the server logs
  `[ai-tracker] agent upgrade: stopping <sid>; if this dashboard dies, resume with: <resume_cmd>`.
- A tracker self-update cannot restart the process mid-job. This applies once the pending
  branch lands, because only that branch has `update.py`; see section 7, step S6.

npm-global installs replace files in place under a running process. That is the residual risk
for lazily loaded assets of a still-running old session. The doctor output shows the install
method. This is an accepted known gap, listed in section 10.

## 3. Per-agent handling: on the shared seam, not a Claude fork (conventions rules 3-5)

**Seam.** A new class attribute on `Provider` (`aitracker/providers/base.py`):
`agent_cli = None`. This is a data descriptor, so the routes still call only the registry.

```python
# providers/claude.py, class ClaudeProvider
agent_cli = {"id": "claude", "label": "Claude Code", "bin": "claude",
             "version": ["--version"], "doctor": ["doctor"], "update": ["update"],
             "restarts_sessions": True}
# providers/auggie.py, class AuggieProvider (line 938)
agent_cli = {"id": "auggie", "label": "Auggie", "bin": "auggie",
             "version": ["--version"], "doctor": None, "update": ["upgrade"],
             "restarts_sessions": False}
```
The Augment VS Code and Cursor providers (`augment_ext.py:350-378`) keep `None`. The editor
updates those extensions; there is no CLI.

`aitracker/agent_cli.py` iterates `registry.PROVIDERS` and treats every descriptor the same
way. The per-agent differences are data, not code:

| | Claude Code | Auggie | Augment VS Code / Cursor |
|---|---|---|---|
| Version shown | `claude --version` → `2.1.325` | `auggie --version` → `0.36.0` | not listed |
| Doctor | `claude doctor` | **not possible**: no documented doctor command, button hidden | — |
| Upgrade | `claude update` (latest) | `auggie upgrade` (latest in its channel) | — |
| Per-session version | transcript `version` (fact 4) | **not possible**: not recorded (fact 5) | — |
| Stop + resume tracker sessions | yes | **not possible**: the tracker cannot resume Auggie (fact 8), so it never stops one | — |
| Outside sessions | listed with `resume_cmd` | listed as "version unknown — restart Auggie in that terminal" (no command: Auggie resume is not supported here) | — |
| Auto-update note | clause-8 note | none (docs contradict themselves; we say nothing rather than guess) | — |

**Shared list-shape field.** Add `cli_version` to the session-list dict:
- Claude: `_tail_scan` (`providers/claude.py:89`) harvests it, last value wins, with
  `version = o.get("version") or version` placed next to the `entry = …` line (around line 168),
  before the `message` check, because metadata-free lines still carry it. It is returned in the
  dict at line 233.
- It is copied through `_session_meta` (line 247) and onto the row (around line 984) as
  `"cli_version": sm.get("cli_version") or ""`.
- Every other provider: `registry.all_sessions()` (`registry.py:28-30`, next to `resumable`)
  does `r.setdefault("cli_version", "")`, so every row carries the key.
- The tail read is the existing cached one, so this adds no I/O.

**Shared resume command.** Extract the inline `resume_cmd` logic (`registry.py:269-274`) into
`registry.resume_cmd(sid, model) -> str | None`. `parse_any` calls it (unchanged behaviour), and
the outside list reuses it, so the OpenRouter launcher case is covered once.

## 4. Files, signatures and routes

### 4a. `aitracker/util.py` (bundled)
- **Add** `run_argv(argv, timeout, env=None) -> (rc | None, out_bytes, err_bytes)`, with
  `_kill_proc_group(p)`. This is the same body as the pending branch's `update._run` /
  `update._kill_proc_group`:
  - `subprocess.Popen(argv, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=env or dict(os.environ), start_new_session=True)`;
  - on `TimeoutExpired`, `os.killpg(p.pid, SIGKILL)` and return `(None, b"", b"timeout")`;
  - on `OSError`, return `(None, b"", str(e))`.

  No shell, ever. When the pending branch lands, `update._run` becomes a 1-line call to this.
- **Add** `is_loopback_host(host_header)`, verbatim from the pending branch's `util.py:715`. The
  text is identical, so whichever branch lands second merges trivially.

### 4b. `aitracker/agent_cli.py` (new, bundled, about 250 lines)
```python
RESUME_PROMPT = "continue, re-read CLAUDE.md"
VERSION_TIMEOUT, DOCTOR_TIMEOUT, UPDATE_TIMEOUT = 15, 60, 600      # s; update downloads ~100 MB
VERSION_TTL = 60          # s a cached --version is trusted before a background refresh
VERIFY_WAIT = 90          # s to wait for each resumed transcript to show the new version
OUTPUT_CAP = 8000         # chars of ANSI-stripped command output kept on the job
AUTO_UPDATE_NOTE = ("Claude Code also updates itself in the background; the tracker leaves that "
                    "alone. A new version only takes effect when a session restarts.")
UPGRADE_MESSAGE = ("The following sessions will be stopped: {list}. You might have to continue "
                   "again with a prompt once the upgrade lands. The tracker will resume each one "
                   "with the prompt “continue, re-read CLAUDE.md”. A session already on "
                   "the new version when the update finishes is left running.")

def specs() -> list[dict]                 # descriptors of PROVIDERS with agent_cli, + "path": shutil.which(bin)
def parse_version(text) -> str | None     # first r"\d+\.\d+\.\d+" in the first line
def status() -> dict                      # GET /api/agents body; never runs a subprocess itself
def plan_upgrade(agent_id) -> dict        # the warning: {stop, cannot_stop, outside, message, note, installed}
def start(agent_id, action, confirm) -> (int, dict)   # POST /api/agents/run; 202 | 400 | 409
def job_running() -> bool
def _job_doctor(job, spec) / _job_upgrade(job, spec, confirm) # worker-thread bodies
def _outside(spec, installed, owned_ids) -> list[dict]
def _cli_env() -> dict                    # os.environ minus GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE
```
- Every external command is `util.run_argv([spec["path"], *spec[<action>]], <timeout>, _cli_env())`.
- `spec["path"]` is `shutil.which(spec["bin"])` on the server's PATH, resolved per job.
- Nothing from the request reaches argv. `agent_id` must match a descriptor `id`, and `action`
  must be `"doctor"` or `"upgrade"`; anything else is a 400.
- Imports are top-level `from .util import run_argv` and `from . import config`, with **no import
  aliases**: `scripts/bundle.py` strips import lines, so an alias would be undefined in
  `dist/tracker.py`.
- `term_vt` is reached only through `sys.modules.get("aitracker.term_vt")`, the same idiom as the
  pending branch's `update._term_live`. In the bundle (no terminal tiers) there are no
  tracker-owned sessions, so Upgrade only updates and lists outside sessions.
- **Single flight:** `_JOB_LOCK = threading.Lock()` and `_JOB = None`. A second `start` while a
  job runs returns 409 `{error: "an agent job is already running", job}`. The last job is kept
  in memory (no file) and returned by `status()`.
- **Version cache:** `_VERSIONS = {id: {"version", "checked_at", "error"}}`. `status()` starts
  one daemon thread `agent-versions` (single flight) when any entry is older than
  `VERSION_TTL`, and returns `checking: true` until it finishes. So no request ever waits on
  `--version`.

`_job_upgrade(job, spec, confirm)` steps. `job["step"]` is updated at each one so the panel can
show progress.
1. `old = version()`. If it is None, fail with "cannot run `<bin> --version`". Nothing is stopped.
2. `rc, out, err = run_argv([path, *spec["update"]], UPDATE_TIMEOUT, _cli_env())` and store the
   output tail. If `rc != 0` (None means timeout or spawn failure), fail: "Update failed; no
   session was stopped. Run Doctor to see why." **Return.**
3. `new = version()` (cache refreshed). If it is None, fail the same way. Nothing is stopped.
4. If `not spec["restarts_sessions"]`, jump to 8.
5. Candidates are `tv.upgrade_candidates()` (4c) **intersected with `confirm`**, the tty ids the
   user saw. A session that appeared after the warning is never stopped; it is reported as
   "started after you confirmed, not stopped".
   - Skip a candidate whose recorded version (`cli_version` of its list row) equals `new`
     ("already on vNEW").
   - An unknown version counts as needing a restart.
6. For each remaining candidate, in order:
   - log the recovery line (section 2);
   - stop it with `tv.call_route(tv.close_pty, {"tty": t, "session": sid, "force": True})` and
     record `killed` and `confirmed`;
   - resume it with `tv.call_route(tv.open_pty, {"session": sid, "mode": "resume", "cols": c,
     "rows": r, "prompt": RESUME_PROMPT})`, where cols and rows come from the old pane;
   - record the new `tty`, or `error` plus `command = registry.resume_cmd(sid, model)`.
7. **Verify** by polling each resumed session's transcript every 2 s, up to `VERIFY_WAIT`:
   `providers.claude._tail_scan(find_session(sid))["version"] == new`. If it matches, mark
   `on_version: new`. Otherwise mark `on_version: null`, "resumed, but no new-version line yet —
   open its terminal".
8. `job["outside"] = _outside(spec, new, owned_ids)`. Build the server-written `summary`, for
   example: "Claude Code 2.1.323 → 2.1.325. Resumed with “continue, re-read CLAUDE.md”: A, B.
   Already current: C. Failed: D (run `claude --resume …`). Not started here, left alone: 2."

`_outside(spec, installed, owned)`:
- Rows of `registry.all_sessions()` whose provider descriptor is `spec`, with
  `time.time() - mtime < config.LIVE_WINDOW`, and whose id is not in `owned`.
- Each row carries `{id, title, cwd, cli_version, out_of_date, command}`:
  - `out_of_date` is true when the version tuple of `cli_version` is lower than `installed`,
    and None when unknown;
  - `command` is `registry.resume_cmd(id, model)` for Claude ("exit it, then run:"), and None
    for Auggie.

### 4c. `aitracker/term_vt.py` (Claude-only terminal tier; not bundled)
- **`_with_prompt(argv, p)`**, about 6 lines next to `open_pty` (`term_vt.py:2951`). It appends
  `p` only when `p` is a str, non-blank, at most 4000 chars, and does not start with `-`. The
  logic is the same as the pending branch's helper. Apply it in the **resume** branch:
  `argv = _with_prompt(term_gate.resume_argv(sid), body.get("prompt"))` (`term_vt.py:3107`).
  `forked` is still computed after it. Folder shells type it via `_inject_argv` (`shlex.join`
  quoting, `term_vt.py:1917`), and dedicated ptys exec it directly.
  - Not applied to `mode=new`. No caller needs it there; the pending branch owns that.
  - Known limit: a `--fork-session` backstop retry rebuilds argv from `resume_argv`
    (`term_vt.py:2449`) and **drops the prompt**. Upgrade never resumes a daemon-hosted session
    (see below), so the refusal path is not expected. If it happens anyway, step 7 reports
    "prompt not confirmed".
- **`upgrade_candidates() -> list[dict]`**:
  - Snapshot under `_LOCK`: `_reap()`, take live, not-closing PTYS, and `_refresh_fg` each
    folder pty.
  - Outside the lock (it forks `ps`), keep those with `_foreground_is_claude(p.fd)` (line 4018).
  - For each, `sid = (_pty_session_ids(p) or ("",))[0]` (line 3970), and `busy = _claude_busy(p)`
    (line 3951).
  - Each dict: `{tty, session, cwd, title: _term_title(p, orl), busy, cols, rows, stoppable, reason}`.
  - `stoppable = bool(sid) and _is_claude(sid) and not _background_target(sid)` (line 3365).
- **Unknown-id and daemon-hosted panes are listed but never stopped.**
  - Unknown id: a `--fork-session` copy, or a hand-typed claude not yet latched.
  - Daemon-hosted: a `claude attach` client of a background session. Killing it stops nothing,
    because the daemon hosts the session.
  - They go into `cannot_stop` with the reason, so they appear under "restart these yourself".
- **`call_route(fn, body) -> (code, obj)`**, with a tiny `_Internal` stand-in handler:
  `headers = {}`, and `_json(obj, code=200, headers=None)` records the reply.
  - With `headers = {}`, `term_gate.guard` (term_gate.py:57) passes the Origin check, the same
    as curl. `TRACKER_TERMINAL=0`, and a non-loopback bind without `TRACKER_AUTH`, still refuse.
    That is right: an upgrade cannot resume what the user's terminal policy forbids.
  - This reuses `close_pty` (line 3757: SIGKILL of the fg group then the shell, with proof) and
    `open_pty` byte for byte. No second stop or resume path.

### 4d. `aitracker/server.py` (bundled)
- `_local_caller` (`server.py:219`) gains the pending branch's DNS-rebinding Host check,
  verbatim: `if not config.AUTH and not is_loopback_host(handler.headers.get("Host", ""))`.
  Every existing caller gets this; it is a strict tightening.
- New `_same_origin(handler)`: Origin absent, or `urlparse(Origin).netloc == Host`. It is the
  same rule as `term_gate._origin_ok`, written in `server.py` because `term_gate` is not
  bundled.
- **Routes** (inline in `do_GET`/`do_POST`, not EXTRA_*, because they must exist in the bundle):
  - `GET /api/agents` runs `_local_caller` and returns 403 if refused, else `agent_cli.status()`:
    ```
    {"agents":[{"id","label","path","installed","checked_at","checking","error",
                "can_doctor","can_upgrade","restarts_sessions","note"}],
     "job": {...}|null}
    ```
    `can_upgrade` is false when `path` is None, with `error = "<bin> not found on the
    tracker's PATH"`.
  - `POST /api/agents/run {agent, action, confirm?}`. The global `_readonly()` deny-all runs
    first (`server.py:558`), then `_local_caller`, then `_same_origin`; a refusal of either is a
    403.
    - `action == "upgrade"` without a `confirm` list returns
      **409 `{needs_confirm: true, ...agent_cli.plan_upgrade(agent)}`**. This is the same
      confirm-then-go shape as the pending branch's `update_apply(confirm_terminals)`.
    - `confirm` must be a list of str, or it is a 400.
    - Otherwise `agent_cli.start(...)` returns 202 `{job}`.
    - Doctor needs no confirm and returns 202 `{job}`.
- Add `"/api/agents"` to nothing else. It is **not** in a read-only allow-list.

### 4e. `aitracker/web/ext_cr_dialogs.js` (Control Room Config dialog)
- Add `crCall`, `crBtn`, `crReadOnly`, verbatim from the pending branch (its
  `ext_cr_dialogs.js:1139-1160`), placed just above `renderConfig` (`ext_cr_dialogs.js:1132`).
- Add `'Agents'` to `sections` (line 1143), after `'Terminal'`. A new `agentsBlock()`, modelled
  on the pending branch's `updateBlock()`, renders one `cfgRow` per agent:
  - label, installed version (or "checking…" / error), and `note`;
  - **Doctor** (when `can_doctor`) and **Upgrade** buttons, disabled while a job runs or
    `crReadOnly()`.
- Upgrade calls POST with no `confirm`. On 409 `needs_confirm` it shows an inline
  `role="alertdialog"` box with:
  - the server's `message` text;
  - the `stop` list: title, folder, and "working — its current turn will be interrupted" when
    `busy`;
  - `cannot_stop`, with each reason;
  - `outside`: title, "on vX, out of date" or "version unknown", and `command` in a `<code>`
    block;
  - the `note`;
  - **Upgrade and restart these** / **Cancel** buttons.
- Confirm re-POSTs with `confirm = stop.map(tty)`. The panel then polls `GET /api/agents` every
  1 s while the job runs. It shows `job.step`, then `job.summary`, the doctor or update `output`
  in a `<pre>`, and the resumed, failed and outside lists. On completion it fires
  `toast({title: job.summary})` (`ext_cr_dialogs.js:273`).
- **Every sentence is server text** (`message`, `note`, `reason`, `summary`). The client only
  lays it out (conventions rule 5).

### 4f. Other files
- `scripts/bundle.py` ORDER (line 11-15): add `"agent_cli.py"` after `"tunnel.py"`, before
  `"server.py"`.
- `providers/base.py`, `providers/claude.py`, `providers/auggie.py`, `registry.py`: see section 3.
- `.claude/rules/conventions.md` rule 6: the new exception (section 5).
- `README.md`:
  - under "## Terminal" (line 84), add a short "### Agents: Doctor and Upgrade" subsection;
  - in "## Adding a tool" (line 231), add one line: "set `agent_cli` on the provider to get
    Doctor/Upgrade";
  - qualify line 7 ("Nothing is sent anywhere"): "…except when you press Upgrade or Doctor,
    which run the agent's own updater".
- `CLAUDE.md`: in the "Add a tool =" line, add "+ an optional `agent_cli` descriptor".
- **No `config.py` change.** No key is needed: always latest, manual only.

## 5. New conventions rule-6 exception (exact wording, to be added under rule 6)

> *"Exception (agent CLI Doctor/Upgrade, user-requested): `aitracker/agent_cli.py` — and only it, never synchronously inside a request handler (its own job and version-refresh threads may) — may run, with no shell, stdin closed, its own process group and a timeout that kills the group, exactly these argv: `<claude> --version`, `<claude> doctor`, `<claude> update`, `<auggie> --version`, `<auggie> upgrade`, where `<claude>`/`<auggie>` is `shutil.which` of that name on the server's own PATH. Argv is fixed in code; the request only picks the agent and the action from that fixed table. `--version` runs in the background at most once per `VERSION_TTL` (60 s) while the Agents panel is polled; Doctor and Upgrade run only when a local caller (loopback peer, loopback Host name, same Origin, not tunnelled, not read-only) presses the button — never on a schedule. `update`/`upgrade` (and `doctor`'s own checks) contact the vendor's update servers with the CLI's own configuration; the tracker itself sends nothing. After an `update` that exited 0 and whose `--version` is readable, it may stop — through `term_vt.close_pty` (SIGKILL of the pane's process groups) — only the tracker's own terminals whose foreground is a Claude session with a known id not hosted by the Claude daemon, that the user confirmed in the warning, and resume each through `term_vt.open_pty` as `claude --resume <id> "continue, re-read CLAUDE.md"`. It never stops, signals or edits a session the tracker did not start, never edits a transcript, and never changes Claude Code's or Auggie's own auto-update settings. No other outbound network call is allowed."*

## 6. Verify before relying (step 0, run by the implementer; no feature code depends on an unproven fact)

- **V1. Resume lands on the new version, and `--resume <id> "<prompt>"` submits the prompt.**
  1. In a scratch dir, run `~/.local/share/claude/versions/<older, e.g. 2.1.323> -p "say ok"`.
     This creates a session that the old binary records.
  2. In a tracker PTY, run `claude --resume <id> "continue, re-read CLAUDE.md"` interactively.
     A plain shell also works, but the tracker PTY tests the real path.
  3. Pass means the transcript gains a `user` line with that text and a `version` equal to the
     installed one.
  4. Tear the scratch session and its transcript down afterwards (memory: "tear down scratch
     sessions").

  If it fails, the feature ships Doctor, Upgrade and the lists, but with **stop/resume
  disabled**. The warning then says "restart these yourself" for every session. Back to the
  user before that change.
- **V2. `claude doctor` with no TTY.** Already done in planning (fact 6). Re-run once in the
  worker under `run_argv`.
- **V3. `auggie upgrade` with no TTY.** Check `auggie upgrade --help` (no upgrade) for a
  non-interactive flag or prompt. If it prompts, Upgrade for Auggie is hidden (`update: None`)
  and that is recorded here.
- **V4. `claude update` with no TTY.** It can only be proved by updating. Run it once, **with
  the user's OK**, at S7. It is acceptable if it reports "up to date". Expect rc 0, and check
  that `--version` agrees.

## 7. Sequencing (each step is its own commit, green before the next)

| Step | Lands | Why this order |
|---|---|---|
| S0 | V1–V3 above, results written into this file | the design rests on V1 |
| S1 | `util.run_argv` + `util.is_loopback_host`; `Provider.agent_cli` + both descriptors; `_tail_scan` `version` → `cli_version` on list rows + `setdefault` in `all_sessions`; `registry.resume_cmd` extraction | pure, read-only seams; everything later uses them |
| S2 | `term_vt._with_prompt` in the resume branch, `upgrade_candidates`, `call_route` | terminal-tier pieces, testable with the existing `_FakeHandler` patterns |
| S3 | `agent_cli.py` (jobs, plan, outside) **+ the conventions rule-6 exception in the same commit** + bundle ORDER | the first code that runs an outbound command must land with its rule |
| S4 | `server.py` routes + `_local_caller` Host check + `_same_origin` | exposes S3 only once it is guarded |
| S5 | `ext_cr_dialogs.js` Agents section (+ CSS in `ext_cr_dialogs.css` if needed) | UI last; renders server text only |
| S6 | README, CLAUDE.md, `_selfcheck` assertion; when the pending branch has landed, `update._run` → `util.run_argv` and mutual exclusion (`update_apply` → 409 while `agent_cli.job_running()`, `agent_cli.start` → 409 while `update._APPLY.locked()`) | docs, plus the cross-feature lock that only exists once `update.py` exists |
| S7 | Live proof: restart the test server on a spare port (never `pkill -f aitracker`); open two scratch tracker sessions (one busy), and leave one outside session open; press Upgrade; check the warning text, the stop/resume, the transcript version, the toast and the outside list. Then tear down. | proves the live path, not just the units |

## 8. Tests (stdlib unittest; each proved RED by reverting its fix)

| Test (new file) | Asserts | Red when reverted |
|---|---|---|
| `tests/test_agent_cli_parse.py` | `parse_version("2.1.211 (Claude Code)") == "2.1.211"`, `"0.36.0 (commit 7c61e5bb)"` → `"0.36.0"`, junk → None; descriptors: Claude `update == ["update"]`, `doctor == ["doctor"]`; Auggie `update == ["upgrade"]`, `doctor is None`; Augment ext `None`; base `None` | parser / descriptor |
| `tests/test_agent_cli_jobs.py` | Uses a stub `claude` script on a temp PATH that logs argv and reads its "installed version" from a state file, plus a fake `aitracker.term_vt` in `sys.modules` that records `call_route`. **(a) update rc 1 → zero close calls, job `failed`, output tail kept** (the risky spot); (b) success → close then open per candidate, in order; open body has `prompt == RESUME_PROMPT` and `mode == "resume"`; (c) a candidate already on the new version is skipped; (d) a pty not in `confirm` is never closed; (e) `stoppable: False` entries are never closed; (f) a second `start` → 409; (g) unknown agent/action → 400, and argv never contains request text | stop-before-update order; confirm filter; skip rule |
| `tests/test_agent_cli_outside.py` | stubbed `all_sessions` rows: live Claude row on `2.1.300` with installed `2.1.325` → `out_of_date True`, `command == "claude --resume <id>"`; OpenRouter row uses the launcher (via `resume_cmd`); live Auggie row → `out_of_date None`, `command None`; tracker-owned id excluded; stale `mtime` excluded | outside filter |
| `tests/test_term_vt_upgrade.py` | `_with_prompt` accept/reject table; `open_pty` resume with `prompt` builds `[launcher, "--resume", sid, prompt]` (patch `spawn`/`_inject_argv` as `tests/test_resume_fork_session.py` does); `upgrade_candidates` marks a daemon-hosted / unknown-id pane `stoppable False`; `call_route` returns `(code, obj)` | resume-branch wiring (guards against the dead-code bug found on the pending branch) |
| `tests/test_claude_cli_version.py` | `_tail_scan` on a fixture with versions `2.1.1` then `2.1.2` → `"2.1.2"`; list row has `cli_version`; an Auggie row has `cli_version == ""` | tail harvest / setdefault |
| `tests/test_agent_routes.py` (pattern: `tests/test_cr_routes.py` `_ServerCase`) | GET `/api/agents` 200 from loopback; 403 with `X-Forwarded-For`; 403 with `Host: evil.example` and no AUTH; POST `/api/agents/run` 403 with `Origin: http://evil.example`; upgrade without `confirm` → 409, `needs_confirm`, `message` contains "will be stopped" and "continue, re-read CLAUDE.md", `note` contains "updates itself in the background"; doctor → 202; tunnel read-only → 403 | Host / Origin / confirm gates |
| `tests/test_agents_ui.py` | `ext_cr_dialogs.js` has `'Agents'` in `sections`, calls `/api/agents` and `/api/agents/run`, and renders `message`/`note`/`summary` from the response (asserts the literal sentences are **absent** from the JS); `node --check` on the file when `node` is on PATH (memory: the gate misses load-time JS errors) | UI wiring |

**`_selfcheck()` assertion** (`tests/test_selfcheck.py`, inside `_run()`, before
`print("selfcheck ok")` at line 1469). It covers Claude and Auggie (rule 9):

```python
from aitracker import agent_cli as _ac
from aitracker.registry import PROVIDERS as _P
_d = {p.agent_cli["id"]: p.agent_cli for p in _P if p.agent_cli}
assert _d["claude"]["update"] == ["update"] and _d["auggie"]["update"] == ["upgrade"]
assert _ac.parse_version("2.1.211 (Claude Code)") == "2.1.211" and _ac.parse_version("0.36.0 (commit x)") == "0.36.0"
assert _ac.RESUME_PROMPT == "continue, re-read CLAUDE.md"
```

**Gate:** run `unset TRACKER_AUTH; make check`, or one module per process if the full run is
OOM-killed (memory). The known flaky `term_vt` backstop test is not a regression. A commit runs
the full gate, so give Bash a timeout over 6 minutes.

## 9. Deliberately left out (simplicity)

- Version pinning, rollback, scheduling, auto-trigger, and any config key (clauses 5 and 7).
- Touching Claude Code's auto-updater or `DISABLE_AUTOUPDATER` (clause 8). Only the note is
  shown.
- Stopping or restarting **daemon-hosted background sessions**. The Claude daemon owns them;
  they are listed under "restart these yourself".
- Auggie stop/resume, Auggie doctor, and the Augment VS Code/Cursor extensions (sections 3 and 0).
- An "out of date" chip on board tiles and session lists. `cli_version` lands on the shape, so it
  is a one-line follow-up, but the contract only asks for the Agents panel list.
- The classic (non-Control-Room) UI. Config lives in the Control Room dialog.
- A job state file. The last job is in memory; the recovery lines go to the server log.
- `_with_prompt` for `mode=new`. That belongs to the pending branch.

## 10. Risks and fallbacks

| Risk | Fallback |
|---|---|
| V1 fails (resume does not pick up the new binary, or the positional prompt is ignored) | ship with stop/resume disabled; every session is listed "restart yourself"; go back to the user |
| Claude Code shows a picker on `--resume` of a long session (summary or full), so the prompt is not submitted | step 7 reports "resumed, prompt not confirmed: open its terminal"; the session is running, not lost |
| `claude update` exits 0 but did nothing | `--version` is the oracle; sessions already on it are skipped; nothing is stopped needlessly |
| The tracker dies mid stop/resume | one session at a time, so at most one is down; the server log has its `resume_cmd` |
| npm-global install replaces files under a still-running session | known gap; the doctor output names the install method; noted in README |
| The Claude background auto-updater runs at the same moment (lock contention) | rc ≠ 0 → nothing stopped; Doctor shows "Last update attempt" |
| Pending-work branch lands later and conflicts on `_local_caller`, `is_loopback_host`, `crCall`/`crBtn`/`crReadOnly` | the code is copied verbatim, so conflicts are textual and trivial; S6 then folds `update._run` into `util.run_argv` |

## 11. Decisions the user may want to overrule

1. **Base branch.** The plan builds on `personal/main` now, copying the 3 small shared pieces
   verbatim from the unlanded `worktree-pending-work-worker`: the Host check, `crCall`/`crBtn`,
   and the `run_argv` body. The alternative is to wait for that branch to land and reuse
   `update.py` directly. Waiting blocks this feature on an 8.6k-line branch whose contract is
   still undischarged.
2. **Who gets stopped.** The plan does not stop these three kinds of session:
   - (a) a session already on the new version once the update finishes;
   - (b) a tracker pane whose session id is unknown (a fork copy, or an unlatched hand-typed
     claude);
   - (c) a daemon-hosted `claude attach` pane.

   (b) and (c) are listed as "restart these yourself". "Force all now" read literally would
   kill (b) as well, which loses the pane with no way to resume it, and killing (c) does nothing.

## 12. Reviews and reconciliation

(Adversarial review by a separate `opus` agent goes here, followed by the main thread's verdict
table. Not started.)

## Log

- 2026-11-16: plan v1 written (opus plan agent). Grounded on `personal/main` @ `76bd154` and on
  `personal/worktree-pending-work-worker` @ `2bca388` (read-only). Real-file checks: transcript
  `version` field (fact 4), Auggie session keys (fact 5), `claude doctor` with no TTY (fact 6),
  install paths and timings (fact 7).
