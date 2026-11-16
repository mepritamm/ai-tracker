# Resume all prior terminals: technical plan

Written 2026-11-16 by the opus plan agent. Branch `agent-upgrade`, worktree `.claude/worktrees/agent-upgrade`.
This builds on `reports/agent-upgrade-plan-final.md` ("AU" below; AU §5.3 = its term_vt section, and so on).
Every `file:line` was read in this worktree at head `fe8f580`, with the AU S1-S8 code still being written by other
agents. AU symbols that don't exist yet are marked **(AU Sn)**.
**Status: plan only. No code until the user agrees (rule 8).**

## 1. Contract (verbatim, split into clauses)

User: "add a resume all prior terminals button alongside the upgrade version button, Put this button in the manage
terminals view itself, where it opens the last spawned sessions, list the sessions which will be opened and open all
of them in the background"

| # | Clause (verbatim) | Verdict |
|---|---|---|
| C1 | "add a resume all prior terminals button" | not discharged |
| C2 | "alongside the upgrade version button" | not discharged |
| C3 | "Put this button in the manage terminals view itself" | not discharged |
| C4 | "where it opens the last spawned sessions" | not discharged |
| C5 | "list the sessions which will be opened" | not discharged |
| C6 | "and open all of them in the background" | not discharged |

How the clauses are read (each is a decision in §12):
- C1/C4: **"prior terminals" means the Claude sessions that were running in tracker terminals when the tracker last
  stopped.** That covers `make stop`, a crash, and the in-app **Update and restart**, which kills every terminal
  (`update.py:301-304` warns "N open terminals will close"; `_cloexec_all` at `update.py:329-345` closes every pty
  master before `os.execv`). Today nothing brings those sessions back.
- C2 + C3: the button goes **in the Control Room's ☰ Manage terminals dialog**. "Alongside the upgrade version
  button" is read as "part of the same change as the Upgrade feature, and in the same UI" (the Control Room), not
  "in the same Config section". The Upgrade and Update buttons exist only in Control Room → Config
  (`ext_cr_dialogs.js:1241-1242`; AU §5.6).
- C5: a confirmation box lists the sessions that **will** open and the ones that **can't**, each with its reason.
  The server writes every sentence.
- C6: the server opens each one through the existing `open_pty` route. No terminal modal opens, nothing takes focus,
  and no prompt is sent. The new panes show up in Manage terminals.

## 2. What exists today (findings)

### 2.1 The "manage terminals view"
There are two, one per UI:
- **Control Room:** `renderManageTerminals(payload)` (`aitracker/web/ext_cr_dialogs.js:2198-2350`), registered as
  `'manage-terminals'` (`ext_cr_dialogs.js:3067`). It is opened by `_openManageDialog()`
  (`aitracker/web/ext_cr_term.js:727-766`) from the pane menu's "☰ Manage terminals" (`ext_cr_term.js:176`) and the
  board's Terminals pill (`ext_cr_board.js:2347`, `ext_cr_boot.js:492`). Its parts:
  - the empty state returns early at `ext_cr_dialogs.js:2220-2223`. This is exactly what the dialog shows right
    after a restart, so the button must render there too;
  - the footer is `h('div', {class: 'cr-cfg-footer'}, …)` at `ext_cr_dialogs.js:2325-2329` (note, "Close all", and
    its inline confirm);
  - `update(p)` repaints on every re-open and ignores the poll broadcast (`ext_cr_dialogs.js:2341-2349`).
- **Classic (the default UI):** `openManager()` / `renderManagerBody()` (`aitracker/web/ext_vt.js:3257`, `:3304`).
  It is opened by the sidebar's `#sidemanagetermbtn` (`aitracker/web/ext_launch.js:100-110`). Classic is the default
  (`'tracker.ui'` defaults to `'classic'`, `ext_cr_boot.js:217-233`), and it has **no** Update or Upgrade button.
- **Server route for both:** `GET /api/term/list` → `term_list()` (`aitracker/term_vt.py:3862-3892`), which returns
  `{"terminals": _live_list(orl), "max": config.MAX_TERMS}` (`_live_list` is at `term_vt.py:2171`).

### 2.2 Is any record of open terminals kept across a restart? **No.**
- `PTYS` is an in-memory dict. Panes die with the process (`update.py:329-366`; a plain exit closes the masters too).
- `aitracker/forks.json` (`config.FORKS_FILE`, `config.py:61`) is fork lineage, keyed by parent session. It is not
  a record of open terminals.
- `SNAPSHOT_TTL_MIN` (`config.py:558-569`) is how old a cached session-detail snapshot may be in the SPA
  (`app.js:1333, 1499`). It has nothing to do with terminals.
- `TERM_IDLE_TTL_MIN` (`config.py:544-555`, default 30) is the idle reap in `_reader` (`term_vt.py:1770-1780`). It
  keeps no history.
- `MAX_TERMS` (`config.py:607`, default 12, clamped 1-64) is only a live cap.
- The terminal modules keep no `localStorage` record either (only a comment hit at `ext_vt.js:331`).
- So the smallest record has to be designed (§4.1).

### 2.3 "Open in the background": what the existing open path can do
- `open_pty` (`term_vt.py:2962-3348`) only **creates** panes. A browser view attaches later through
  `/api/term/screen` or `/api/term/raw`. Called from the server through AU's `call_route(open_pty, body)` **(AU
  S3)**, it opens a pane that no browser is showing.
- `mode: "resume"` is Claude-only (`term_vt.py:3083-3084`). It resolves a parked session to its daemon job
  (`:3092-3094`) and 404s on a missing cwd (`:3099-3102`). Its argv is `[launcher, "--resume", sid]`
  (`:3116-3121`). If a pane already runs that session, it reuses that pane (`:3148-3156`). Otherwise it types the
  command into the cwd's folder shell when that shell is idle (`:3230-3296`; a shell spawned just now takes the
  deferred path at `:3258-3279`). When the shell is busy, it opens an overflow pty (`:3312-3348`).
- **The cap.** A new folder shell is refused at `_live_count() >= config.MAX_TERMS` with a 429
  (`term_vt.py:3161-3170`), and so is an overflow pty (`:3312-3316`). `_live_count` is at `term_vt.py:1821`. So:
  - each new cwd costs 1 slot (its folder shell);
  - each further session in the same cwd costs 1 slot (an overflow pty, because the first claimed the shell);
  - a cwd whose folder shell is already open and idle costs 0 for its first session.
- **No viewer means the idle clock runs.** `_reader` kills a pane with `viewers <= 0` once it has been idle longer
  than `TERM_IDLE_TTL_MIN`. It holds off only while Claude has tool work running (`_claude_busy`) or the session is
  live (`_session_live`, `term_vt.py:4011`). So a resumed session left at its prompt and never watched closes after
  30 minutes. That is existing policy, and the notice says so (§6).
- **The swap hazard.** `open_pty` takes over an *unwatched* folder pane that is showing another background
  session's `claude attach` client (`term_vt.py:3306-3310`). Opening two daemon-hosted sessions in one folder in
  the background would therefore SIGTERM the first one's client. This is why daemon-hosted sessions are listed as
  "can't" (§4.2).
- **Never `mode: "new"`.** A bare `claude` opens the agent view on this machine (AU §1).

## 3. The flow

1. Manage terminals (Control Room) → **Resume all prior terminals**.
2. `POST /api/terminals/resume-all {}` → the server builds the plan → `409 {needs_confirm: true, message, note,
   saved_at, open: [...], cannot: [...]}`. The plan has no side effects. The 409 mirrors AU's
   `/api/agents/run`.
3. An inline box in the dialog shows:
   - `message`;
   - the **will open** rows: title, folder, when the terminal was opened;
   - the **can't open** rows: title, reason, and the command to run by hand in `<code>`;
   - `note`;
   - the buttons **Resume these N** (hidden when `open` is empty) and **Cancel**.
4. Confirm → `POST /api/terminals/resume-all {confirm: [session ids shown]}` → `202 {job}`. A single background
   thread then works through the list:
   - it re-plans, and opens only the sessions that are both confirmed and still openable;
   - it opens them **one at a time** through `call_route(open_pty, {session, mode: "resume", cols, rows})`;
   - it never sends a prompt and never uses `mode: "new"`.
5. `agentWatchJob` **(AU S7)** polls `GET /api/agents` (its `job` field), shows a toast with the server's `summary`
   (what opened, and what failed with its reason), then repaints the Manage terminals dialog if it is still open.

## 4. Server design

### 4.1 The record: `aitracker/last_terms.json`
- **`aitracker/config.py`:** add `LAST_TERMS_FILE = os.path.join(_HERE, "last_terms.json")` next to `FORKS_FILE`
  (`config.py:61`), with a comment in the same style as `PINS_FILE` (`config.py:34`). Callers reach it late-bound
  as `config.LAST_TERMS_FILE`.
- **`.gitignore`:** add `last_terms.json` under "Personal / runtime data".
- **Shape** (atomic, written via `store._save_json` at `store.py:18` and read via `store._load_json` at
  `store.py:10`):
  ```json
  {"boot": "1794811083.040612", "saved_at": 1794811100.1,
   "terminals": [{"session": "<uuid>", "cwd": "/path", "opened": 1794811090.2, "cols": 120, "rows": 32}],
   "prior": {"boot": "...", "saved_at": ..., "terminals": [...]} }
  ```
  `terminals` holds this run's live set. `prior` holds the last earlier run that had at least one terminal.
- **`aitracker/term_vt.py`** (not bundled). These go next to `_live_list` (`term_vt.py:2171`):
  ```python
  _BOOT = "%.6f" % time.time()      # per process; an in-place restart re-imports the module
  REMEMBER_EVERY = 15.0             # s between rewrites of the live set
  _REMEMBER_ON = False              # set only by start_remember(): tests never write the user's file
  _REMEMBER_LOCK = threading.Lock()
  _REMEMBERED = None                # last list written by this process

  def _live_claude_sessions() -> list[dict]
  def _terms_record(old, boot, live, now) -> dict      # pure
  def remember_terminals(final=False) -> None          # never raises
  def start_remember() -> None                         # daemon thread "term-remember"
  def prior_terminals() -> dict                        # {"saved_at": float|None, "terminals": [...]}
  ```
  - **`_live_claude_sessions()`:**
    - Compute `orl` first. Then, under `_LOCK`: `_reap()` (`term_vt.py:2212`), then for each pane that is not done
      and not closing, `_refresh_fg(p)` (folder panes only), and snapshot `(p.folder, p.fd, p.cwd, p.started,
      cols/rows, _pty_session_ids(p))`. `p.started` is at `term_vt.py:1508`; `_pty_session_ids` at `:3982`.
    - **Outside the lock:** keep a folder pane's ids only if `_foreground_is_claude(p.fd)` (`term_vt.py:4030`). An
      idle folder shell whose Claude was exited is not a "prior terminal". Its stale `spawned` would otherwise be
      counted (`_pty_session_ids` falls back to `spawned` when `fg` is None).
    - Dedupe by session, keep at most 64 (the `MAX_TERMS` ceiling), and sort by `opened`, newest first.
  - **`_terms_record(old, boot, live, now)`:**
    - If `old.get("boot") == boot`, prior is `old.get("prior")`.
    - Otherwise prior is `old`'s own `{boot, saved_at, terminals}` when its `terminals` is non-empty, else
      `old.get("prior")`. A run that opened nothing does not wipe the previous one.
    - Return `{"boot": boot, "saved_at": now, "terminals": live, "prior": prior}`. Junk (a non-dict) counts as `{}`.
  - **`remember_terminals(final)`:**
    - Return at once unless `_REMEMBER_ON`.
    - Compute `live = _live_claude_sessions()`.
    - Under `_REMEMBER_LOCK`, if `final` or `live != _REMEMBERED`: read the old file, then
      `store._save_json(config.LAST_TERMS_FILE, _terms_record(old, _BOOT, live, time.time()))`, then set
      `_REMEMBERED = live`.
    - Wrapped in `try/except Exception: pass`.
  - **`start_remember()`:** sets `_REMEMBER_ON = True` and starts one daemon thread that loops
    `remember_terminals(); time.sleep(REMEMBER_EVERY)`. It is idempotent.
  - **`prior_terminals()`:**
    - Read the file. If its `boot != _BOOT`, the file still describes an earlier run: use its `terminals` when that
      is non-empty, else its `prior`.
    - Otherwise use `prior`.
    - Returns `{"saved_at", "terminals"}`, or `{None, []}`.
- **When it is written:**
  1. every 15 s while the server runs, but only when the set changed;
  2. a final write on `make stop` / SIGTERM / Ctrl-C;
  3. a final write right before the in-app update execs.

  A crash or `kill -9` loses at most the last 15 s.
- **`aitracker/server.py`, `run()`** (`server.py:1017-1048`):
  - After `start_worker()`, add `tv = sys.modules.get(__package__ + ".term_vt")`, then `if tv:
    tv.start_remember()`.
  - Wrap `srv.serve_forever()` (`server.py:1048`) in `try: … finally: tv and tv.remember_terminals(final=True)`.
    `_on_sigterm` raises `SystemExit` (`server.py:1000-1014`), so the `finally` runs for `make stop` and for
    Ctrl-C.
  - `run()` is the only caller of `start_remember`, so unit tests that import `term_vt` never write the real file.
- **`aitracker/update.py`, `restart_in_place`:** right before `_cloexec_all()` (`update.py:365`), add
  `tv = sys.modules.get("aitracker.term_vt")`, then `if tv: tv.remember_terminals(final=True)`. Same idiom as
  `_term_live` (`update.py:101-110`). The call never raises, so it can never block the exec.
- **How stale entries drop out:**
  - `prior` is replaced by the first write of any later run that had terminals;
  - an entry that no longer resolves (transcript or folder gone, already open, running elsewhere) is **shown with
    its reason**, never hidden;
  - the message states the record's age ("when the tracker last stopped, 3 h ago").

  There is no max-age purge and no "forget" button (§11).

### 4.2 `resume_all_plan()` in `aitracker/term_vt.py`
This goes next to AU's `upgrade_candidates` **(AU S3)**. Its reason strings live there too, like AU §5.3's reason
table. It forks `ps`, so it is never called under `_LOCK`. It never raises.
```python
def resume_all_plan() -> dict:
    # {"saved_at", "open": [row], "cannot": [row], "free": int, "max": int}
    # row = {session, title, cwd, opened, cols, rows, reason, command}
```
1. `pr = prior_terminals()`. Set `c = _provider()` (`term_vt.py:3369`). Set `run = {r["id"]: r for r in
   c.running_sessions()}` if `c` else `{}` **(AU S1)**. Then `free = config.MAX_TERMS - _live_count()`, read under
   `_LOCK` after `_reap()`.
2. The title of each row is `c.session_label(sid)` (`claude.py:708`), or the folder name of `cwd`, or `sid[:8]`.
3. Each entry is checked in this order. The first failure moves it to `cannot` with that reason:

   | Check | Reason (server text) | `command` |
   |---|---|---|
   | `not _is_claude(sid)` (`term_vt.py:1339`; Auggie ids) | "only Claude Code sessions can be resumed in a tracker terminal" | `[]` |
   | `_session_pty(sid)` under `_LOCK` (`term_vt.py:3516`) | "already open in terminal %s" % tty | `[]` |
   | `run.get(sid)` with `host == "daemon"`, or `_background_target(sid)` (`term_vt.py:3377`) | "still running in Claude's background daemon; nothing was lost. Open it from its session row to watch it" | `[]` |
   | `run.get(sid)` with `host == "desktop"` | "open in the Claude desktop app" | `[]` |
   | `run.get(sid)` with `host == "tui"` | "running in another terminal outside the tracker (pid %d); resuming it here would run it twice" | `[]` |
   | `term_gate.resume_argv(sid)` raises `gateway.GatewayError` as `e` | `str(e)` | `[]` |
   | `not term_gate.session_cwd(sid, resume=True)` | "its transcript or its folder no longer exists" | `[]` |
   | slot cost > free left (below) | "no free terminal slot (%d of %d in use): close a terminal or raise Max terminals in Config, then press Resume all prior terminals again" | `[shlex.join(resume_argv(sid))]` |

4. **Slot cost**, worked out in list order (newest first):
   - 0 if an idle folder shell for that cwd exists and no earlier row in this plan used it (`_folder_pty(cwd)`,
     `term_vt.py:1890`, with `p.fg is None`);
   - otherwise 1.

   Decrement `free` for each row that fits. The real cap is still `open_pty`'s own 429. The job reports one as
   `failed` with the 429's own error text.
5. Rows that pass go to `open`.

### 4.3 The job in `aitracker/agent_cli.py` **(AU S4)**
It reuses AU's job slot, locks, setters and poller instead of a second loop:
- the same `_AGENT_JOB` and `_AGENT_JOB_LOCK` (so it is mutually exclusive with Doctor/Upgrade and with
  `update_apply`, `update.py:269`);
- the same `_APPLY` check;
- `_pending_lock` for the open phase (the AU N9 pattern, `update.py:272-281`);
- `_agent_set`, `_agent_snapshot`, and `tv.call_route` **(AU S3)**.
```python
def agent_plan_resume_all() -> (int, dict)
def agent_start_resume_all(confirm) -> (int, dict)
def _agent_job_resume_all(job, confirm)
def _agent_ra_summary(items) -> str        # pure; §6
```
- **`agent_plan_resume_all()`:**
  - `tv` is None (the bundle) → `409 {"error": AGENT_RA_NO_TERMS}`;
  - `not term_gate.allowed()` → `409 {"error": AGENT_RA_DISABLED}`;
  - `agent_job_running()` → `409 {"error": "an agent job is already running"}`;
  - `_APPLY.locked()` → `409 {"error": "the tracker is updating itself — try again after it restarts"}`;
  - otherwise `409 {needs_confirm: True, message, note, saved_at, open, cannot}`, with `message`/`note` from §6.
- **`agent_start_resume_all(confirm)`:**
  - 400 "confirm must be a list of session ids" unless `confirm` is a list of at most 64 non-empty strings;
  - then the same locks as `agent_start` (AU §5.4), with the same 409 bodies;
  - the job dict carries AU's keys, so the AU job view renders it:
    `{id, agent: "claude", action: "resume_all", state: "running", step, started, finished: None, old: None,
    new: None, output: "", items: [], outside: [], summary: ""}`;
  - the thread is `"agent-resume_all"` and its `finally` releases `_AGENT_JOB_LOCK`, as in AU;
  - returns `202 {job}`.
- **`_agent_job_resume_all(job, confirm)`:**
  1. Take `_pending_lock` without blocking. If it is busy, fail with `AGENT_RA_FAIL_SCAN`; nothing is opened.
  2. `plan = tv.resume_all_plan()`. Each confirmed session now in `plan["cannot"]` becomes item `failed` with its
     reason. A row in `open` that was not confirmed is skipped and not reported.
  3. For each confirmed row in `open`, **one at a time**:
     - set the step: `AGENT_RA_STEP % (i, n, title)`;
     - `code, obj = tv.call_route(tv.open_pty, {"session": sid, "mode": "resume", "cols": row["cols"], "rows":
       row["rows"]})`. There is no `prompt` key and never `mode: "new"`;
     - **200** → item `{session, title, cwd, outcome: "opened", tty_after: obj["tty"], detail: obj.get("notice")
       or ""}`;
     - **anything else** → `outcome: "failed"`, `detail: obj.get("error") or "HTTP %d" % code`.
  4. Set `summary = _agent_ra_summary(items)` and `state = "done"`, and print `"ai-tracker: resume all: " +
     summary`. Any exception sets `state = "failed"` and `summary = AGENT_FAIL_INTERNAL % e`.
- It runs no external command, so it needs **no conventions rule-6 exception**. `open_pty` already runs
  `claude --resume`.

### 4.4 `aitracker/server.py` route
This goes in `do_POST`, next to AU's `/api/agents/run` **(AU S6)**. The global `_readonly()` deny has already run.
```python
if p.path == "/api/terminals/resume-all":
    ok, err = _local_caller(self)
    if not ok:
        return self._json({"error": err}, 403)
    if not isinstance(body, dict):
        return self._json({"error": "bad body: expected a JSON object"}, 400)
    code, out = (agent_plan_resume_all() if body.get("confirm") is None
                 else agent_start_resume_all(body.get("confirm")))
    return self._json(out, code)
```
Extend AU's `from .agent_cli import …` line with the two names.

## 5. UI design (Control Room only, per decision b)

**`aitracker/web/ext_cr_dialogs.js`:**
- Change AU's `agentWatchJob(id)` **(AU S7)** to `agentWatchJob(id, onDone)`. Keep the callback in a module
  variable and call it once, after the toast. With no callback it behaves exactly as before.
- In `renderManageTerminals` (`ext_cr_dialogs.js:2198`), add state **outside `paint()`**:
  `var raPlan = null, raBusy = false, raErr = '';`. The dialog repaints itself on every re-open (`update`,
  `:2341-2349`), so state inside `paint()` would drop the open confirm box. This is the same lesson as the
  directory picker's `busy` (`:2374-2379`).
- New `function resumeAllBlock()` in that closure. It returns null when `crReadOnly()` (`:1139`). It builds:
  - when nothing is pending: `crBtn('Resume all prior terminals', ask)` (`:1156`), disabled while `raBusy`, plus
    `raErr` in a `cr-cfg-footer-note`;
  - `ask` calls `crCall('/api/terminals/resume-all', 'POST', {})` (`:1144`):
    - 409 with `needs_confirm` → `raPlan = r.body`, then `paint()`;
    - any other non-OK reply → `raErr = r.body.error`, then `paint()`;
  - when `raPlan` is set: `h('div', {class: 'cr-inline-confirm cr-resume-all-confirm', role: 'alertdialog'}, …)`
    holding:
    - `raPlan.message`;
    - one row per `open` entry: title · `cwdTail(cwd)` · `timeAgo(opened)` (`:2165-2179`);
    - one row per `cannot` entry: title, `reason`, and each `command` in `<code>`;
    - `raPlan.note`;
    - **Resume these N** (only when `open.length`) and **Cancel**, which sets `raPlan = null` and repaints;
  - confirming POSTs `{confirm: raPlan.open.map(function (s) { return s.session; })}`:
    - 202 → `raPlan = null; raBusy = true; paint(); agentWatchJob(r.body.job.id, function () { raBusy = false;
      if (payload.onRefresh) payload.onRefresh(); else paint(); })`;
    - a 409 error → shown as `raErr`.
- Append `resumeAllBlock()`:
  - in the **empty-state branch**, before its `return` (`:2220-2223`). Right after a restart this is the state the
    dialog is in;
  - in the list branch, inside the existing `cr-cfg-footer` (`:2325-2329`), before `closeAllBtn`.

  It is not shown in the error branch.
- The JS holds only the button labels and counts. Every sentence comes from the server.

**`aitracker/web/ext_cr_term.js`, `_openManageDialog`** (`:742-762`): add `onRefresh: _repaintManage,` to the
payload, so the list shows the new panes once the job ends. The cap dialog (`:681`, `:693`) is left unchanged, and
the button there works without `onRefresh` (it repaints only).

No CSS change. `cr-inline-confirm` already exists; `cr-resume-all-confirm` is the test hook.

## 6. Every user-facing string (server-written; `AGENT_RA_*` in `agent_cli.py`, reasons in `term_vt.py` §4.2)

```python
AGENT_RA_MESSAGE = ("%d session%s %s open in tracker terminals when the tracker last stopped (%s ago). "
                    "Resume all prior terminals reopens %s in the background with claude --resume, each in its "
                    "folder's terminal. No terminal window opens and no prompt is sent; they appear in this list.")
    # % (n_total, "" if n_total == 1 else "s", "was" if n_total == 1 else "were", age, "it" if n_open == 1 else "the ones below")
AGENT_RA_NONE = ("Nothing to resume: the tracker has no record of terminals that were open when it last stopped. "
                 "It starts keeping one from this version on.")
AGENT_RA_NONE_OPENABLE = "None of them can be reopened here; the reasons are below."     # appended when open == []
AGENT_RA_NOTE = ("Nobody is watching these terminals, so one that sits idle closes after %d minutes "
                 "(Config → Terminal → Idle terminal TTL). Peek or open one to keep it.")   # % config.TERM_IDLE_TTL_MIN
AGENT_RA_STEP = "Opening %d of %d: %s"
AGENT_RA_NO_TERMS = "This build has no in-browser terminals, so there is nothing to resume."
AGENT_RA_DISABLED = "Terminals are disabled here (TRACKER_TERMINAL=0, or a network bind without TRACKER_AUTH)."
AGENT_RA_FAIL_SCAN = "A pending-work scan is running; nothing was opened. Try again in a minute."
# _agent_ra_summary(items):
#   k opened of n:  "Resumed %d of %d prior terminal%s in the background: %s."   (titles, comma-joined)
#   k == 0:         "No prior terminal was resumed."
#   any failed:     + " Not opened: %s."   ("<title> (<detail>)", "; "-joined)
#   k > 0:          + " " + AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN
```
Age is formatted with the server's existing helper, if `util` has one; otherwise `"%d min"` / `"%d h"` / `"%d d"`
inline in `agent_cli`. The SPA never computes it.

## 7. The risky spot, and its fallbacks

1. **The record must reflect what was really running.** An idle folder shell, or a pane whose Claude has exited,
   must not be resumed.
   - Guard: the `_foreground_is_claude` filter (§4.1), plus a final write on every orderly stop.
   - Fallback: the periodic 15 s write bounds a crash to 15 s of staleness.
   - Residual: a Claude that the user exited in the last 15 s before a crash can come back. It is listed first, so
     the user can Cancel.
2. **"Running elsewhere" depends on AU S1's procStart-verified pid files.** A tracker-killed Claude has a dead pid,
   so it is correctly openable. A session open in Terminal.app on an old CLI with no pid file is not detected, and
   it would be resumed a second time.
   - Deliberately **no** "transcript written recently" check: every just-killed prior session was written seconds
     ago, so that check would block the main case.
   - Fallback: the user sees the list before confirming.
3. **Unwatched panes get idle-reaped after `TERM_IDLE_TTL_MIN`.** This is existing policy, stated in the note. A
   busy session is held by `_claude_busy`.
4. **The CLI refuses a resume** (it sees a background agent). The backstop retries with `--fork-session` *after*
   the 200 (`open_pty` docstring, `term_vt.py:3023-3036`), so the summary says "opened" for what became a forked
   copy. The pane carries the `⑂ fork` chip in the list. Known limit, same as AU §5.3's.
5. **Back-to-back opens into one folder shell.** These are serialized: one thread, one open at a time. A second
   session in the same cwd takes the overflow path, which costs a slot; the slot math (§4.2) counts it.
6. **Daemon-hosted sessions are "can't"**, to avoid the unwatched-pane swap (§2.3). Fallback: the row tells the
   user to open it from its session row, where a single attach is safe.

## 8. Sequencing (after AU S1-S8; each its own commit, `unset TRACKER_AUTH; make check` green before the next)

| Step | Lands | Needs |
|---|---|---|
| R1 | `config.LAST_TERMS_FILE`, `.gitignore`, `term_vt` record (`_live_claude_sessions`, `_terms_record`, `remember_terminals`, `start_remember`, `prior_terminals`), `server.run` start + `finally`, the `update.restart_in_place` hook. Tests T1-T4. | AU S2 (touches `update.py`) |
| R2 | `term_vt.resume_all_plan` + reason texts. Test T5. | AU S1 (`running_sessions`), S3 (`call_route`, next to `upgrade_candidates`) |
| R3 | `agent_cli` resume-all functions + `AGENT_RA_*`. Tests T6-T7. | AU S4 |
| R4 | `server.py` route. Test T8. | AU S6 |
| R5 | `ext_cr_dialogs.js` (`agentWatchJob(id, onDone)`, `resumeAllBlock`), `ext_cr_term.js` `onRefresh`. Test T9. | AU S7 |
| R6 | README line, CLAUDE.md app-owned-state line, `_selfcheck` assertion. | AU S8 |
| R7 | Live proof (§9 end), then it joins AU S9's `/branch-sync`, full gate and push. | — |

**R1 should run as early as the user can accept.** The record only exists from the first run that has R1, so the
button has nothing to show until one restart *after* R1 is running.

## 9. Tests (stdlib unittest; each proved red by reverting its fix)

New file `tests/test_resume_all.py`. Every test redirects `config.LAST_TERMS_FILE` to a tmp dir and saves and
restores `term_vt._REMEMBER_ON`, `_BOOT` and `_REMEMBERED`.
- **T1 the record keeps only live Claude.**
  - Setup: stub `PTYS` with a dedicated resume pane A, a folder pane B whose `_foreground_is_claude` → True, an idle
    folder pane C with a stale `spawned` (`_foreground_is_claude` → False), and A duplicated.
  - Expect: `[A, B]`, newest first.
  - Red: drop the `_foreground_is_claude` filter → C appears.
- **T2 generations (`_terms_record`, pure).**
  - Setup: an old record `{boot: "x", terminals: [A]}` and a new boot `"y"` with live `[]`.
  - Expect: `prior.terminals == [A]`. A third boot `"z"` with live `[]` still has `prior.terminals == [A]`; boot
    `"z"` with live `[B]` and old `{boot: "y", terminals: [], prior: A}` keeps prior A, and the next boot makes B
    the prior.
  - Red: drop the "keep the old prior when the old terminals are empty" branch → prior lost.
- **T3 there is no write unless started.**
  - `remember_terminals(final=True)` with `_REMEMBER_ON = False` creates no file.
  - Red: remove the guard → the file appears. This protects the user's real file from the test suite.
- **T4 the final write runs before the exec.** This goes in `tests/test_update_restart.py`.
  - Setup: patch `os.execv` to raise a sentinel and stub `sys.modules["aitracker.term_vt"]` with a recorder.
  - Expect: `remember_terminals(final=True)` is called before `execv`.
  - Red: remove the call. A sibling test calls `server.run` with `bind`/`serve_forever` stubbed so that
    `serve_forever` raises `SystemExit`, and asserts the `finally` write. Red: remove the `finally`.
- **T5 plan classification.**
  - Setup: prior has nine entries:
    - Auggie id;
    - already open (stub `_session_pty`);
    - daemon (`running_sessions` `host: "daemon"`);
    - desktop;
    - tui elsewhere;
    - `resume_argv` raises `GatewayError`;
    - `session_cwd` → "";
    - three openable, with `MAX_TERMS - live == 2` and an idle folder shell for the third one's cwd.
  - Expect: each lands in `cannot` with its exact §4.2 text, and all three openable rows land in `open` (the idle
    shell costs 0). The same setup with no idle shell puts the oldest in `cannot` with the no-slot text.
  - Red: removing any one check moves that row into `open`.
- **T6 the job opens with resume only, with no prompt.**
  - Setup: stub `tv.call_route` to record its bodies and return 200 for A and 429 `{"error": "too many running
    terminals (max 2)"}` for B. Confirm `[A, B, C]`, where C is now in `cannot`.
  - Expect: the items are A `opened`, B `failed` with the 429 text, C `failed` with its reason. Every body has
    `mode == "resume"` and no `prompt` key. The summary equals `_agent_ra_summary` (exact string).
  - Red: send `mode: "new"` or add a prompt → the assertion fails.
- **T7 locks and validation.**
  - 409 while `_AGENT_JOB_LOCK` is held or `_APPLY` is locked;
  - 400 for `confirm = "x"`, a list of 65 items, or a list holding a non-string;
  - a busy `_pending_lock` → `failed` with `AGENT_RA_FAIL_SCAN` and zero `call_route` calls.
  - Red: remove each guard.
- **T8 the route** (in AU's `tests/test_agent_routes.py`).
  - Expect: a non-local caller gets 403 (red: remove `_local_caller`); read-only gets 403; `{}` gets 409
    `needs_confirm`; `{confirm: [..]}` gets 202; a non-dict body gets 400.
- **T9 the UI** (new `tests/test_resume_all_ui.py`). It uses the brace-extract plus node idiom of
  `tests/test_cr_manage_terminals_poll.py`, under `renderManageTerminals`.
  - The button renders in the **empty** state. Red: append it only in the list branch.
  - The 409 plan renders the `message`, `reason` and `note` text verbatim.
  - **The confirm box survives `update({terminals: [...]})`.** Red: move `raPlan` inside `paint()`.
  - Confirm POSTs exactly the `open` session ids.
  - `crReadOnly()` → no button.

**`_selfcheck`:** yes, one assertion in `tests/test_selfcheck.py` on `_terms_record`'s prior-preservation rule
(conventions rule 9: non-trivial logic). It is Claude-only: Auggie never runs in a tracker terminal
(`_term_title` docstring (d), `term_vt.py:2146-2147`).

**Live proof (R7)**, per the safe-scratch protocol (AU §4), with the user's OK:
1. Open two scratch sessions through the dashboard's Resume, plus one scratch session in Terminal.app.
2. `make stop`, then `make serve` on a test port (never `pkill`).
3. Open Control Room → Manage terminals (it is empty). Press the button.
4. Check:
   - the two sessions are listed under will-open;
   - the Terminal.app one is under can't, with its pid;
   - confirm → no modal opens, two rows appear, the toast text matches, and `last_terms.json` holds the new live
     set with `prior` unchanged.
5. Tear everything down.

## 10. README and CLAUDE.md (R6)

- **README.md**, under "## Terminal — on by default" (`README.md:84-105`), after the "Folder terminals" bullet:
  > - **Resume all prior terminals** — Control Room → ☰ Manage terminals → **Resume all prior terminals** lists the
  >   Claude sessions that were open in tracker terminals when the tracker last stopped (including an in-app
  >   **Update and restart**), says which can't be reopened and why, and on confirm resumes the rest with
  >   `claude --resume` in the background — no window opens and no prompt is sent. The record is
  >   `aitracker/last_terms.json`, rewritten every 15 s while the tracker runs.
- **CLAUDE.md** "App-owned state" line: add `last_terms.json` (written by `term_vt.remember_terminals`) next to
  `flags.json`/`titles.json`.

## 11. Deliberately left out

- **The classic dashboard's Manage terminals** (`ext_vt.js:3304`). Decision (b). It would cost about 50 lines and
  its own poller, because `agentWatchJob` is private to `ext_cr_dialogs.js`.
- **A copy of the button in Config → Update or Agents.** Decision (b).
- **Sessions closed during the current run** (killed, or idle-reaped). Decision (a).
- **Any prompt to resumed sessions.** Decision (c).
- **Daemon-hosted sessions** (the swap hazard, §2.3), Auggie, and desktop sessions: listed, not opened.
- **Max-age purge or a "Forget this list" button.** The record is replaced by the next run that had terminals.
- **Auto-resume on startup.** The user asked for a button.
- **Reporting a late `--fork-session` retry in the summary** (§7.4).
- **Restoring pane sizes beyond `cols`/`rows`, scrollback, or which tab had focus.**

## 12. Decisions for the user

- **(a) What "prior terminals / last spawned sessions" means.** The plan uses the Claude sessions running in
  tracker terminals when the tracker last stopped, kept in the new `last_terms.json`. The alternatives are:
  - (a2) also include the sessions whose terminals closed during *this* run (killed, or idle-reaped). This needs a
    closed-history list, about 20 more lines;
  - (a3) "the last N sessions any terminal opened", whether or not they were still running. This is the widest
    reading and the most likely to reopen sessions the user had finished.
- **(b) Where the button goes.** The plan puts it in the Control Room's Manage terminals dialog only, both in the
  empty state and in the footer next to "Close all". The reasons: that is the same UI as the Upgrade and Update
  buttons ("alongside"), and the dialog itself ("in the manage terminals view itself"). The options are:
  - (b2) also add it to the classic sidebar's Manage terminals panel. Classic is the default UI;
  - (b3) also add a twin in Config → Update, next to "Update and restart".
- **(c) Prompt.** No prompt is sent; sessions reopen waiting at their input. The upgrade feature's "continue,
  re-read CLAUDE.md" exists because *it* interrupted busy work. Here the stop was the tracker's, and the plan
  cannot tell what each one was doing.
- **(d) More sessions than free slots.**
  - Newest first, as many as fit. The rest are listed as "no free terminal slot (N of M in use): close a terminal
    or raise Max terminals in Config, then press again", each with its command.
  - Nothing is closed to make room, and nothing is queued.
  - The alternative is to refuse the whole batch unless everything fits.

## Log
- 2026-11-16: plan written by the opus plan agent. No code.
