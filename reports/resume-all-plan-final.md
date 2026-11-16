# Resume all prior terminals: final technical plan

Written 2026-11-16 by the opus plan agent, in worktree `.claude/worktrees/agent-upgrade` (branch `agent-upgrade`,
head `fe8f580` plus the uncommitted, implemented agent-upgrade feature, "AU" below). This is the review's Clean plan
(`resume-all-review.md`) with `resume-all-reconcile.md` applied exactly, including the main thread's reversal to ONE
merged history keyed by session id, and every accepted fix from `resume-all-review-final.md`. It is self-contained:
an implementer needs no other report. Line numbers were re-read after AU's later review fixes. **Line numbers drift
(other sessions edit these files): locate by symbol name, then re-read the region before editing (conventions
rule 12).**
**Status: plan only. No code until the user agrees (rule 8).**

## 1. Contract

User, verbatim (2026-11-16): "add a resume all prior terminals button alongside the upgrade version button, Put this
button in the manage terminals view itself, where it opens the last spawned sessions, list the sessions which will be
opened and open all of them in the background"

| # | Clause / decision (verbatim) | Verdict |
|---|---|---|
| C1 | "add a resume all prior terminals button" | not discharged |
| C2 | "alongside the upgrade version button" | not discharged |
| C3 | "Put this button in the manage terminals view itself" | not discharged |
| C4 | "where it opens the last spawned sessions" | not discharged |
| C5 | "list the sessions which will be opened" | not discharged |
| C6 | "and open all of them in the background" | not discharged |
| R-D1 | Which set is "prior terminals": "Also closed this run" | not discharged |
| R-D2 | Placement: "Manage terminals and Config" | not discharged |
| R-D3 | List longer than the free terminal slots: "Let me pick" | not discharged |
| R-D4 | Prompt after reopening: "No prompt" | not discharged |

How each is met:
- **C1/C4 + R-D1.** "Prior terminals" means the most recent Claude sessions (up to 32) that ran in a tracker terminal
  started from **this checkout**.
  - It includes ones whose pane was later closed, killed or idle-reaped, in this run or any earlier one.
  - It is **one merged history shared by every tracker from this checkout**, whatever port each used.
  - Closing a pane never removes a session. Only the size bound and a missing transcript do (§2).
- **C2/C3 + R-D2.** One button, "Resume all prior terminals", in two places:
  - the Control Room's ☰ Manage terminals dialog, in both the empty state and the list footer;
  - Config → Agents on the Claude row, next to **Upgrade**.

  It is not in the classic UI and not in the at-cap "free a slot" variant of the Manage dialog.
- **C5 + R-D3.** Pressing it shows a server-built list:
  - every openable session as a **checkbox**, pre-ticked newest-first up to the free slots;
  - the ones that cannot open, each with the server's reason and a hand command;
  - one line naming the ones already open.

  On confirm the server re-checks the slot cap against the ticked list. If it no longer fits, the server refuses
  with 409 and a fresh list.
- **C6 + R-D4.** On confirm a server job opens each ticked session with `open_pty` `mode: "resume"` through
  `call_route`, one at a time.
  - No modal opens and nothing takes focus.
  - **No `prompt` key is ever sent**, and `mode: "new"` is never used.
  - The new panes appear in Manage terminals.

## 2. The on-disk record: `aitracker/last_terms.json`

- **`aitracker/config.py`**, after `FORKS_FILE` (`config.py:61`), in the `PINS_FILE` style:
  ```python
  # {"<session id>": entry} -- the merged "Resume all prior terminals" history of every tracker run from this
  # checkout. Written only by term_vt.remember_terminals through store._update_json; read live.
  LAST_TERMS_FILE = os.path.join(_HERE, "last_terms.json")
  ```
  Every caller reaches it late-bound as `config.LAST_TERMS_FILE` (CLAUDE.md seam rule; tests redirect it).
- **`.gitignore`**, under "Personal / runtime data" after `forks.json.lock`, add `last_terms.json` and
  `last_terms.json.lock`.
- **Shape: one flat dict keyed by session id** (main-thread reversal of per-port keys). A tracker that comes back on
  another port, or two trackers at once, see one list.
  ```json
  {"<uuid>": {"cwd": "/path", "title": "My work", "seen": 1794811099.0, "cols": 120, "rows": 32}, ...}
  ```
  `seen` is the last time a tracker saw this session's Claude in the foreground of one of its panes. Nothing else is
  stored. There is no boot id, no port, no `prior` and no `opened`.
- **History semantics (R-D1).** The file *is* the history; there is no in-memory copy. Each computed tick merges the
  live Claude panes in:
  - a new session id is added;
  - a known one gets `cwd`, `title`, `cols` and `rows` replaced, and `seen = max(new, stored)` (newest wins, even
    across two trackers);
  - **nothing is removed because its pane closed.**
- **Bound and staleness.**
  - `LAST_TERMS_MAX = 32` entries in total. At merge time the oldest by `seen` are dropped, and only inside a write
    that adds a live entry.
  - At read time (`remembered_terminals`), an entry whose transcript is gone (`store._find_transcript(sid) == ""`,
    `store.py:382-386`) is **dropped silently** and not listed. The file is not rewritten for it.
  - There is deliberately no age bound: after a long break the last sessions are still the ones to offer. Each row
    shows how long ago it was seen.
- **"Never replace non-empty with empty."** `_merge_terms` returns False (do not write) whenever the tick has no
  live entry. So:
  - a run that never opens a Claude pane never touches the file;
  - a shutdown cannot write a gutted set, because there is no removal and no shutdown write;
  - every write contains at least the live entries.
- **When it is written.**
  1. The `term-remember` daemon thread wakes every `REMEMBER_EVERY = 15` s.
     - It returns at once when no pane is open.
     - It recomputes only when the pane fingerprint changed or `REMEMBER_FULL_EVERY = 60` s have passed. That
       catches an in-pane `/clear` or `/resume` relabel and moves `seen` forward.
     - It writes only when `_merge_terms` says so, so at most about once a minute while panes run.
  2. Once, forced, in `update.restart_in_place` right before `_cloexec_all()`, because the panes are about to close.
  3. **No** SIGTERM or `finally` write in `server.run` (B1). A crash or `make stop` loses at most the last tick.
- **Atomic, multi-process safe.** Every write is a locked read-modify-write through a new
  `store._update_json(path, mutate)`.
  - It generalises `store._update_forks` (`store.py:348-379`).
  - It takes a flock on `path + ".lock"` via `_lock_fh` (`store.py:337`) and saves atomically with `_save_json`
    (`store.py:18`).
  - Two trackers from one checkout therefore never lose each other's entries. flock locks per open file
    description, so two threads in one process exclude each other as well.
  - Reads use `store._load_json` (`store.py:10`).
- **Another tracker's open panes.** A session open right now in another tracker's pane is in the merged list. It is
  classified by the "running elsewhere" check (its pid file, host `tui`) and shown as "can't", never opened twice.

## 3. Exact files and signatures

### 3.1 `aitracker/store.py` (refactor, no behaviour change)
```python
def _update_json(path, mutate):
    """Locked read-modify-write of a JSON dict file (flock on path + ".lock"). mutate(d) edits d in place;
    returning False skips the save. A non-dict file counts as {}."""
def _update_forks(mutate):
    return _update_json(config.FORKS_FILE, mutate)      # body moved verbatim into _update_json
```
The path is read at call time (late-bound). Existing forks tests (`tests/test_fork_follow.py`) must stay green
unchanged.

### 3.2 `aitracker/term_vt.py`: the terminal record (new section placed right after `upgrade_candidates`, `:4097-4172`)
- `upgrade_candidates` is **not changed** (review F5: the `started` key only fed an unused `opened` field).
- No new import. Locking lives in `store._update_json`.
```python
LAST_TERMS_MAX = 32
REMEMBER_EVERY = 15.0          # s between fingerprint checks
REMEMBER_FULL_EVERY = 60.0     # s between forced recomputes
_REMEMBER_ON = False           # set only by start_remember(); False = never write (tests, bundle)
_REMEMBER_STOP = threading.Event()
_REMEMBER_LOCK = threading.Lock()  # serialises whole ticks (loop vs the restart thread)
_LAST_FP, _LAST_FULL = None, 0.0

def _pane_fingerprint() -> tuple
def _entries(rows, now) -> dict          # pure: {session id: entry}
def _merge_terms(d, live) -> bool        # pure: mutates d; False = do not write
def remember_terminals(final=False) -> None   # never raises
def start_remember() -> bool
def remembered_terminals() -> list       # [entry + "session"], newest seen first; never raises
```
- **`_pane_fingerprint()`**: under `_LOCK`, call `_reap()`, then return
  `tuple(sorted((p.id, _fg_pgid(p) if p.folder else p.pid) for p in PTYS.values() if not p.done and not p.closing))`.
  Syscalls only, no `ps`.
- **`_entries(rows, now)`**: works on `upgrade_candidates()` rows.
  - Skip rows with an empty `target`.
  - Dedupe on `target` (first wins).
  - Map each to `out[target] = {cwd: row["cwd"], title: row["title"], seen: now, cols: row["cols"], rows:
    row["rows"]}`.
  - This reuses AU's pane walk, its foreground filter and its pid-file relabel (S3) instead of a second walk.
- **`_merge_terms(d, live)`**:
  ```python
  if not live:
      return False                       # never write, never prune, without a live entry (B1)
  for k in [k for k, v in d.items() if not (isinstance(k, str) and isinstance(v, dict)
                                             and isinstance(v.get("seen"), (int, float)))]:
      d.pop(k, None)                     # malformed entries
  for sid, e in live.items():
      old = d.get(sid) or {}
      d[sid] = dict(e, seen=max(e["seen"], old.get("seen") or 0))
  for k in sorted(d, key=lambda k: d[k]["seen"], reverse=True)[LAST_TERMS_MAX:]:
      d.pop(k, None)
  return True
  ```
- **`remember_terminals(final=False)`**:
  ```python
  global _LAST_FP, _LAST_FULL
  if not _REMEMBER_ON: return
  try:
      with _REMEMBER_LOCK:
          now, fp = time.time(), _pane_fingerprint()
          if not fp: return                                  # no pane open: nothing to record (N6)
          if not final and fp == _LAST_FP and now - _LAST_FULL < REMEMBER_FULL_EVERY: return
          live = _entries(upgrade_candidates(), now)         # forks ps: never under _LOCK (it isn't)
          _LAST_FP, _LAST_FULL = fp, now
          store._update_json(config.LAST_TERMS_FILE, lambda d: _merge_terms(d, live))
  except Exception:
      pass
  ```
- **`start_remember()`**:
  - If `_REMEMBER_ON` is already set, return True.
  - Otherwise set `_REMEMBER_ON = True`, call `_REMEMBER_STOP.clear()`, and start a daemon thread
    `"term-remember"` running `while not _REMEMBER_STOP.wait(REMEMBER_EVERY): remember_terminals()`.
  - On `RuntimeError`, reset `_REMEMBER_ON = False` and return False.
  - Otherwise return True.
  - The stop event exists so tests can end the thread.
- **`remembered_terminals()`**: it is not gated by `_REMEMBER_ON`, since reading is harmless.
  - `d = store._load_json(config.LAST_TERMS_FILE, {})`; anything that is not a dict counts as `{}`.
  - Take the entries `dict(v, session=k)` for str keys with dict values and a numeric `seen`.
  - Sort them by `seen` desc.
  - Drop those where `store._find_transcript(k) == ""`.
  - Cap at `LAST_TERMS_MAX`.
  - Wrap the whole body in `try/except` and return `[]` on error.

### 3.3 `aitracker/term_vt.py`: the plan (right after the record section)
```python
RA_ONLY_CLAUDE = "only Claude Code sessions can be resumed in a tracker terminal"
RA_DAEMON = ("still running in Claude's background daemon; nothing was lost. Open it from its session row "
             "to watch it")
RA_DESKTOP = "open in the Claude desktop app"
RA_TUI = ("running in another terminal (pid %d), outside this tracker's terminals; resuming it here would run it "
          "twice. If you just restarted the tracker, wait a few seconds and press again")
RA_NO_CWD = "its transcript or its folder no longer exists"

def _ra_need(cwds, idle) -> int          # pure: slots a list of open cwds costs
def resume_all_plan() -> dict            # never raises; never under _LOCK (forks ps)
```
- **`_ra_need(cwds, idle)`**: start with `used, n = set(), 0`. For each cwd:
  - if `cwd in idle and cwd not in used`, do `used.add(cwd)`. The cost is 0, because the session is typed into that
    idle folder shell.
  - otherwise do `n += 1`: a new folder shell, or an overflow pty because the folder shell is busy or already
    claimed by an earlier row.

  This mirrors `open_pty`'s paths: the claim (`~:3231`) and the two 429s (`~:3162-3171` and `~:3315-3317`).
- **`resume_all_plan()`** returns `{"open": [row], "cannot": [row], "already": [title], "free", "max", "in_use",
  "idle": [cwd]}`, where `row = {session, title, cwd, seen, cols, rows, reason, command, checked}`:
  1. Gather inputs outside the lock:
     - `ents = remembered_terminals()`;
     - `c = _provider()` (`:3370`);
     - `hosts = {}`, and when `c` is set, `hosts.setdefault(r["id"], []).append(r)` for each
       `r in c.running_sessions()`, wrapped in try with `{}` on error.
  2. Under `_LOCK`:
     - call `_reap()`;
     - `in_use = _live_count()` (`:1821`);
     - `idle = {p.cwd for p in PTYS.values() if p.folder and not p.done and not p.closing and p.fg is None and
       _fg_pgid(p) == p.pid}`;
     - for each entry, note whether `_session_pty(sid)` (`:3650`) hits.
  3. Per entry, `title` is the first non-empty of `c.session_label(sid)` (when `c` is set), `entry["title"]`,
     `os.path.basename(cwd)`, or `sid[:8]`. The first failing check wins:

     | Check | Goes to | reason | command |
     |---|---|---|---|
     | `not _is_claude(sid)` (`:1339`) | cannot | `RA_ONLY_CLAUDE` | `[]` |
     | `_session_pty(sid)` hit | `already` (title only) | — | — |
     | any host `"daemon"` in `hosts[sid]`, or `_background_target(sid)` (`:3378`) | cannot | `RA_DAEMON` | `[]` |
     | host `"desktop"` | cannot | `RA_DESKTOP` | `[]` |
     | host `"tui"` | cannot | `RA_TUI % pid` | `[]` |
     | `term_gate.resume_argv(sid)` raises `gateway.GatewayError` as e | cannot | `str(e)` | `[]` |
     | `not (cwd2 := term_gate.session_cwd(sid, resume=True))` | cannot | `RA_NO_CWD` | `[]` |
     | otherwise | open | `""` | `[shlex.join(argv)]` |

     - Open rows carry `cwd = cwd2` (what `open_pty` will resolve, `~:3099`) and the entry's `cols`, `rows` and
       `seen`.
     - Daemon-hosted sessions are never opened, because an unwatched folder pane showing one would be swapped
       (`~:3307-3311`).
  4. **Pre-tick (R-D3):**
     - `free = max(0, config.MAX_TERMS - in_use)`;
     - walk `open` in order, newest `seen` first;
     - set `checked = _ra_need([cwd of ticked rows] + [row.cwd], idle) <= free`;
     - when that is True, add the row to the ticked set.
  5. Return with `idle` as a sorted list. agent_cli needs it for the re-check; it is stripped from the HTTP body.

### 3.4 `aitracker/agent_cli.py` (AU's module: reuse, don't copy)
**Reused as-is:**
- `_agent_item` (`:146-151`) with `_AGENT_ITEM_KEYS` (`:97-98`);
- `_agent_set` (`:154`), `_agent_push` (`:159`), `_agent_snapshot` (`:164`), `_agent_tv` (`:178`),
  `agent_job_running` (`:182`);
- `_agent_thread` (`:376-383`), which sets `finished` and releases `_AGENT_JOB_LOCK`;
- `_agent_resume` (`:592-606`), called with `busy=False` so its body has no `prompt` key (R-D4). It returns the item;
- `_pending_lock` (import `:11`), `_APPLY`/`_AGENT_JOB_LOCK` (import `:10`);
- through `tv`: `call_route` (`term_vt.py:3588`) and `open_pty`.

**Small refactors** (no behaviour change; the existing `tests/test_agent_cli_*.py` stay green):
- **`_agent_launch(agent, action, fn, args) -> (code, body)`** is the job-slot tail of `agent_start`
  (`agent_cli.py:355-373`), moved verbatim:
  - lock acquire, else 409 with the snapshot;
  - the `_APPLY` re-check, else 409;
  - `_AGENT_SEQ`;
  - the job dict with AU's keys;
  - the `_AGENT_JOB` swap under `_AGENT_JLOCK`;
  - the thread `"agent-" + action` on `_agent_thread`;
  - RuntimeError rollback, then 500.

  `global _AGENT_JOB, _AGENT_SEQ` moves into `_agent_launch`. `agent_start` keeps its validation, picks
  `fn, args`, and then calls `return _agent_launch(agent_id, action, fn, args)`.
- **`_agent_fail(job, summary, label="agent upgrade")`** (`:386`) prints `"ai-tracker: %s: %s" % (label, summary)`.
  The default keeps `tests/test_agent_cli_jobs.py:308` green.
- **`_agent_resume(job, tv, cand, busy, reused=AGENT_RESUME_REUSED)`** (review F4). The reused branch (`:600-601`)
  uses `reused % obj.get("tty")`. The default keeps AU unchanged; resume-all passes `AGENT_RA_REUSED`.

New strings (all user-facing text is server-written):
```python
AGENT_RA_MESSAGE = ("These Claude sessions ran in a tracker terminal from this checkout (newest first, closed ones "
                    "included) and are not open now. Resume opens the ticked ones in the background with claude "
                    "--resume, each in its folder's terminal. No terminal window opens and no prompt is sent; they "
                    "appear in Manage terminals.")
AGENT_RA_NONE = ("Nothing to resume: no Claude session that is not open now has run in a tracker terminal from "
                 "this checkout. The tracker keeps this record from this version on.")
AGENT_RA_NONE_OPENABLE = " None of them can be reopened here; the reasons are below."
AGENT_RA_PICK = ("Only %d terminal slot%s free (%d of %d in use), so the newest that fit are ticked; tick others "
                 "instead, or close a terminal first. Each new folder, and each further session in a folder whose "
                 "terminal is busy, takes a slot.")
AGENT_RA_ALREADY = "Already open in a terminal here, so not listed: %s."
AGENT_RA_NOTE = ("Nobody is watching these terminals, so one that sits idle closes after %d minutes "
                 "(Config → Terminal → Idle terminal TTL). Peek or open one to keep it.")
AGENT_RA_TOO_MANY = ("The %d you ticked need %d terminal slot%s, but only %d %s free now. Untick some or close a "
                     "terminal, then press Resume again. The list below is current.")
AGENT_RA_NONE_PICKED = "None of the sessions you ticked can be opened now. The list below is current."
AGENT_RA_GONE = "no longer in the list (it is open now, or its transcript is gone)"
AGENT_RA_REUSED = "already open in tracker terminal %s, so it was not opened again"
AGENT_RA_STEP = "Opening %d of %d: %s"
AGENT_RA_NO_TERMS = "This build has no in-browser terminals, so there is nothing to resume."
AGENT_RA_DISABLED = "Terminals are disabled here (TRACKER_TERMINAL=0, or a network bind without TRACKER_AUTH)."
AGENT_RA_FAIL_SCAN = "A pending-work scan is running; nothing was opened. Try again in a minute."
```
The `AGENT_RA_NOTE` parenthesis matches the real Config label "Idle terminal TTL" (`ext_cr_dialogs.js`,
`serverRow('Idle terminal TTL', 'TERM_IDLE_TTL_MIN', ...)`).

New functions:
```python
def _agent_ra_body(plan, error="") -> dict
def agent_plan_resume_all() -> (int, dict)
def agent_start_resume_all(confirm) -> (int, dict)
def _agent_job_resume_all(job, confirm)
def _agent_ra_summary(items) -> str      # pure
```
- **`_agent_ra_body(plan, error)`** returns `{needs_confirm: True, error, message, pick, already, note, open, cannot,
  free, max}`, without `idle`. Its fields:
  - `message` is `AGENT_RA_NONE` when `open` and `cannot` are both empty. Otherwise it is `AGENT_RA_MESSAGE`, plus
    `AGENT_RA_NONE_OPENABLE` when `open` is empty.
  - `pick` is `AGENT_RA_PICK % (free, "" if free == 1 else "s", in_use, max)` when any open row is unticked, else
    `""`.
  - `already` is `AGENT_RA_ALREADY % ", ".join(titles)`, or `""`.
  - `note` is `AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN` when `open` is non-empty, else `""`.
- **`agent_plan_resume_all()`**: every refusal is a 409, AU's preview convention. Check in this order:
  - `tv = _agent_tv()` is None: `{"error": AGENT_RA_NO_TERMS}`;
  - `not tv.term_gate.allowed()`: `AGENT_RA_DISABLED`;
  - `agent_job_running()`: `{"error": "an agent job is already running", "job": _agent_snapshot()}`;
  - `_APPLY.locked()`: `{"error": "the tracker is updating itself — try again after it restarts"}`;
  - otherwise return `_agent_ra_body(tv.resume_all_plan())`.
- **`agent_start_resume_all(confirm)`**:
  1. Return 400 `{"error": "confirm must be a list of 1 to 64 session ids"}` unless `confirm` is a list of 1 to 64
     `str` values, each non-empty and at most 200 chars. Then dedupe: `confirm = list(dict.fromkeys(confirm))` (N5).
  2. Apply the NO_TERMS / DISABLED / job-running / `_APPLY` 409s as in the preview.
  3. **Server-side re-check (R-D3):**
     - `plan = tv.resume_all_plan()`;
     - `want = set(confirm)`;
     - `picked = [r for r in plan["open"] if r["session"] in want]`, in plan order. Only ids that are in the
       server's own record and openable now count, so a forged id never opens.
     - If nothing is picked, return `409, _agent_ra_body(plan, AGENT_RA_NONE_PICKED)`.
     - `need = tv._ra_need([r["cwd"] for r in picked], set(plan["idle"]))`. If `need > plan["free"]`, return
       `409, _agent_ra_body(plan, AGENT_RA_TOO_MANY % (len(picked), need, "" if need == 1 else "s", plan["free"],
       "is" if plan["free"] == 1 else "are"))`.
  4. `return _agent_launch("claude", "resume_all", _agent_job_resume_all, (confirm,))`.
- **`_agent_job_resume_all(job, confirm)`**:
  ```python
  tv = _agent_tv(); cm = _pending_lock(); got = cm.__enter__()
  try:
      if not got:
          return _agent_fail(job, AGENT_RA_FAIL_SCAN, "resume all")
      plan = tv.resume_all_plan()
      want = set(confirm)
      opn = {r["session"]: r for r in plan["open"]}; bad = {r["session"]: r for r in plan["cannot"]}
      todo = [r for r in plan["open"] if r["session"] in want]
      for sid in confirm:
          if sid not in opn:
              r = bad.get(sid) or {"session": sid, "title": sid[:8], "reason": AGENT_RA_GONE, "command": []}
              _agent_push(job, _agent_item(dict(r, target=sid), "failed", r["reason"]))
      for i, r in enumerate(todo, 1):
          _agent_set(job, step=AGENT_RA_STEP % (i, len(todo), r["title"]))
          cand = {"tty": "", "session": r["session"], "target": r["session"], "title": r["title"],
                  "command": r["command"], "cols": r["cols"], "rows": r["rows"]}
          try:
              _agent_resume(job, tv, cand, False, AGENT_RA_REUSED)   # mode "resume", no prompt key
          except Exception as e:
              _agent_push(job, _agent_item(cand, "failed", str(e)))
  finally:
      cm.__exit__(None, None, None)
  summary = _agent_ra_summary(job["items"])
  _agent_set(job, summary=summary, state="done")
  print("ai-tracker: resume all: " + summary, flush=True)
  ```
  The slot cap is not re-checked here. `open_pty`'s own 429 (`"too many running terminals (max N)"`) is the backstop,
  and it becomes a `failed` item via `_agent_resume`.
- **`_agent_ra_summary(items)`**: `ok` is the items with outcome `"unprompted"`; `bad` is those with `"failed"`. The
  summary is built in three parts:
  - When `ok` is non-empty: `"Resumed %d of %d prior terminal%s in the background: %s." % (len(ok), len(items),
    "" if len(items) == 1 else "s", ", ".join(_agent_name(i) for i in ok))`. Otherwise:
    `"No prior terminal was resumed."`
  - When `bad` is non-empty, append `" Not opened: %s." % "; ".join("%s (%s)" % (_agent_name(i), i["detail"]) for
    i in bad)`.
  - When `ok` is non-empty, append `" " + AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN`.
- **`agent_status()`** (`:231-`): add to each row `"can_resume_all": bool(spec["id"] == "claude" and tv is not
  None and tv.term_gate.allowed())`, reading `tv = _agent_tv()` once. No subprocess runs, so the docstring's promise
  holds.
- This code runs no external command, so no conventions rule-6 exception is needed (`open_pty` already runs
  `claude --resume`).

### 3.5 `aitracker/server.py`
- Import line `:14`: add `agent_plan_resume_all, agent_start_resume_all`.
- In `do_POST`, add the route right after the `/api/agents/run` block (`:694-707`). The global `_readonly()` deny
  (`:639`) has already run by then:
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
  Responses:

  | Request | Response |
  |---|---|
  | `{}` | 409 `{needs_confirm: true, ...}` or 409 `{error}` |
  | `{confirm: [ids]}` | 202 `{job}`; 409 `{needs_confirm: true, error, ...fresh list}`; 409 `{error}`; 400 |
  | non-local caller | 403 |
  | read-only | 403 (`_RO_BODY`) |
  | non-object body | 400 |
- **`run()`** (`:1040-1069`): after `start_worker()` (`:1052`), add:
  ```python
  tv = sys.modules.get("aitracker.term_vt")     # literal name: bundle.py asserts no __package__ in server.py
  if tv is not None:
      tv.start_remember()                        # via the module attribute, so tests/__init__.py's stub applies
  ```
  Nothing else changes in `run()`, and there is no `try/finally`.

### 3.6 `aitracker/update.py`
In `restart_in_place` (`:347-373`), right before `_cloexec_all()` (`:365`), use the same idiom as `_term_live`
(`:101-110`):
```python
tv = sys.modules.get("aitracker.term_vt")
if tv is not None:
    try:
        tv.remember_terminals(final=True)
    except Exception:
        pass
```
Under the suite, `_REMEMBER_ON` is False, so the existing `tests/test_update_restart.py` cases are unaffected.

### 3.7 `tests/__init__.py` (B2: the suite never writes the real record)
Append:
```python
import os as _os, tempfile as _tf
from aitracker import config as _config
_config.LAST_TERMS_FILE = _os.path.join(_tf.mkdtemp(prefix="ait-lastterms-"), "last_terms.json")
_term_vt._real_start_remember = _term_vt.start_remember
_term_vt.start_remember = lambda: False
```
`make check` runs each module as `tests.<name>` (`scripts/run_tests_parallel.py:39-49`), so this always runs first.
**The real guard is the write gate `_REMEMBER_ON`, which is off unless the real `start_remember()` ran.** The path
redirect is only a second layer: `tests/test_term_vt.py:3420-3427` calls `importlib.reload(config)`, which resets
`LAST_TERMS_FILE` for the rest of that process (review N8). The stub is required, not optional:
`tests/test_update_routes.py` `RunWiring` patches `threading.Thread` globally and joins every thread created in
`run()`.

## 4. The UI: both places, one widget (R-D2, R-D3)

**`aitracker/web/ext_cr_dialogs.js`**
- **`agentWatchJob(id, onDone)`** (`:1309-1327`, re-grounded on AU's current version, review F3). AU already has
  `var _agentJobTimer = null, _agentToasted = null, _agentWatchId = null;` (asserted verbatim by
  `tests/test_agents_ui.py:48`). It restarts on a new id and ignores failed polls (`if (!r.ok) return;`).
  - Leave that line exactly as AU has it, and add `var _agentJobDone = null;` on its own line right after it.
  - Add `function _agentFireDone(j) { var cb = _agentJobDone; _agentJobDone = null; if (cb) cb(j); }`.
  - At entry:
    - if `_agentJobTimer && _agentWatchId === id`: `if (onDone) _agentJobDone = onDone; return;`
    - else if `_agentJobTimer`: clear it as AU does, then `_agentFireDone(null);`
    - then `if (onDone) _agentJobDone = onDone;` and continue as AU does.
  - On the "job gone/replaced" stop path, call `_agentFireDone(null)`. On the "finished" path, call
    `_agentFireDone(j)` after the toast. A failed poll fires nothing.
  - With no `onDone` it behaves exactly as before.
- **New module-scope `function resumeAllWidget(hooks)`**, placed right after `agentWatchJob`. That puts it inside the
  `_agents_code` slice that `tests/test_agents_ui.py` scans, so it must hold no server sentence.
  - It returns `{btn, panel, lock(on)}`. Both nodes are created once and keep their state across a host's repaint;
    a host just re-appends them. `hooks = {onStarted(job), onDone()}`, both optional.
  - State: `var plan = null, busy = false, err = '', locked = false, boxes = [];` where `boxes` holds `{cb, sid}`
    pairs rebuilt by `paint()`. Ticks are read from `boxes`, never by querying the DOM.
  - `btn = crBtn('Resume all prior terminals', ask, 'cr-resume-all')`.
    - `paintBtn()` sets `disabled` while `busy || locked`.
    - `lock(on)` sets `locked` and repaints the button. The Config host locks it while an agent job runs.
  - `ask()` does `err = ''; busy = true; paint();`, then calls `crCall('/api/terminals/resume-all', 'POST', {})`:
    - a 409 with `needs_confirm` sets `plan = r.body`;
    - anything else sets `err = (r.body && r.body.error) || 'request failed'`;
    - then `busy = false; paint()`.
  - `paint()` rebuilds `panel` only: `panel.innerHTML = ''`, `boxes = []`, class
    `cr-update-confirm cr-resume-all-confirm`, `role: 'alertdialog'`, and `panel.hidden = !(plan || err)`. It
    contains, in order:
    1. `err` (or `plan.error`) in a `cr-cfg-row-sub` error line;
    2. `plan.message`, then `plan.pick` when non-empty;
    3. per `plan.open` row, `h('label', {class: 'cr-resume-all-row'}, [cb, ' ', [s.title, cwdTail(s.cwd),
       timeAgo(s.seen)].filter(Boolean).join(' · ')])`:
       - `cb = h('input', {type: 'checkbox'})` and `cb.checked = !!s.checked`;
       - `boxes.push({cb: cb, sid: s.session})`;
       - a `change` listener repaints only the confirm button's label;
    4. `plan.already` when non-empty;
    5. one `cr-cfg-row-sub` per `plan.cannot` row: `title · reason`, then each `command` as `<div><code>`;
    6. `plan.note` when non-empty;
    7. when `plan.open.length`, a confirm button labelled `'Resume ' + n + ' ticked'` (n = ticked boxes; disabled
       when 0); and always **Cancel**, which does `plan = null; err = ''; paint()`.
  - Confirm runs `var ids = boxes.filter(checked).map(sid); plan = null; busy = true; paint();`. `busy` is set
    **before** the POST, so a double click sends one request (N3). Then `crCall(..., 'POST', {confirm: ids})`:
    - 202 with `r.body.job`: `if (hooks.onStarted) hooks.onStarted(r.body.job); agentWatchJob(r.body.job.id,
      function () { busy = false; paint(); if (hooks.onDone) hooks.onDone(); });`
    - 409 with `needs_confirm`: `busy = false; plan = r.body; paint();`, which shows the fresh list with the
      server's `error`;
    - anything else: `busy = false; err = (r.body && r.body.error) || 'request failed'; paint();`.
  - `timeAgo` and `cwdTail` are the IIFE-scope function declarations at `:2292`/`:2302`. They are hoisted, so they
    are reused, not copied.
- **Config → Agents** (`agentsBlock`, `:1329-`):
  - After `if (crReadOnly()) return null;`, create `var ra = resumeAllWidget({onStarted: function (job) { st = st ||
    {}; st.job = job; paint(); load(false); }, onDone: function () { load(false); }});`.
  - In `paint()`'s row loop, after the Upgrade button: `if (a.can_resume_all) { ra.lock(running);
    ctl.appendChild(ra.btn); }`.
  - After the rows, before `if (plan) ...confirmBox()`: `if (st && (st.agents || []).some(function (a) { return
    a.can_resume_all; })) wrap.appendChild(ra.panel);`.
  - The finished job then shows in AU's existing `jobView` (the summary plus one "title — detail" line per item).
- **Manage terminals** (`renderManageTerminals`, `~:2325-2477`). In the closure, outside `paint()` (review F2: gate
  on `onRefresh` **first**, because the parity and poll harnesses define neither `crReadOnly` nor
  `resumeAllWidget`):
  ```js
  var ra = null;
  function raParts() {
    if (!payload.onRefresh || crReadOnly()) return null;
    if (!ra) ra = resumeAllWidget({ onDone: function () { if (payload.onRefresh) payload.onRefresh(); } });
    return ra;
  }
  ```
  - Empty-state branch (`~:2347-2350`), before its `return`: `var r0 = raParts(); if (r0) {
    chrome.body.appendChild(h('div', {class: 'cr-cfg-footer'}, [r0.btn])); chrome.body.appendChild(r0.panel); }`.
  - List branch footer (`~:2452-2456`): `var r1 = raParts();`. When it is set, put `r1.btn` before `closeAllBtn`
    and append `r1.panel` after the footer.
  - Not in the error branch.
  - Because `ra` lives outside `paint()`, an open picker survives `update({terminals})` (`~:2470-2475`).
- No CSS change: `cr-update-confirm`, `cr-cfg-row-sub` and `cr-cfg-footer` already exist, and `cr-resume-all*` are
  test hooks. The JS holds only button labels and counts.

**`aitracker/web/ext_cr_term.js`**:
- In `_openManageDialog`'s payload (`:742-762`), add `onRefresh: _repaintManage,`. `_repaintManage` (`:899-910`)
  repaints only while Manage is the top dialog.
- `_openCapDialog` (`:677-724`) is left unchanged, so the button never shows in the at-cap dialog (S6). A cap-dialog
  update replaces the payload, which hides the button; that is intended.

## 5. Every user-facing string
- **Server, `agent_cli.py`:**
  - `AGENT_RA_MESSAGE`, `AGENT_RA_NONE`, `AGENT_RA_NONE_OPENABLE`, `AGENT_RA_PICK`, `AGENT_RA_ALREADY`;
  - `AGENT_RA_NOTE`, `AGENT_RA_TOO_MANY`, `AGENT_RA_NONE_PICKED`, `AGENT_RA_GONE`, `AGENT_RA_REUSED`;
  - `AGENT_RA_STEP`, `AGENT_RA_NO_TERMS`, `AGENT_RA_DISABLED`, `AGENT_RA_FAIL_SCAN`;
  - the `_agent_ra_summary` sentences and the 400 text;
  - the reused AU texts: "an agent job is already running" and "the tracker is updating itself — try again after it
    restarts".
- **Server, `term_vt.py`:** `RA_ONLY_CLAUDE`, `RA_DAEMON`, `RA_DESKTOP`, `RA_TUI`, `RA_NO_CWD`, plus `GatewayError`
  text and `open_pty`'s own error texts.
- **JS, labels only:** "Resume all prior terminals", "Resume N ticked", "Cancel", and the generic fallback "request
  failed" (already used by AU).

All exact texts are in §3.3 and §3.4.

**Known wording gap, not changed here:** `update.py:271` refuses an Update during any agent job with "an agent
upgrade is running", and that includes a resume-all job. The text belongs to AU; mention it in the commit.

## 6. The flow
1. Manage terminals (or Config → Agents) → **Resume all prior terminals** sends `POST /api/terminals/resume-all {}`.
2. The server runs `agent_plan_resume_all`, which calls `term_vt.resume_all_plan()` over `remembered_terminals()` and
   answers 409 `{needs_confirm, message, pick, already, note, open (with checked), cannot, free, max}`. There are no
   side effects.
3. Picker: the user keeps or changes the ticks, then presses **Resume N ticked**, which sends
   `POST {confirm: [ids]}`.
4. The server re-plans and re-checks the slot need of the ticked set (`_ra_need`).
   - If it no longer fits, or nothing ticked is openable, it answers 409 with a fresh list.
   - Otherwise it answers 202 `{job}`. The job uses the shared AU job slot, so it is mutually exclusive with
     Doctor/Upgrade and with Update.
5. The job thread:
   - takes the pending lock and re-plans;
   - reports confirmed-but-now-unopenable sessions as `failed`;
   - for each ticked openable row, one at a time, calls `_agent_resume(job, tv, cand, False, AGENT_RA_REUSED)`,
     which runs `call_route(open_pty, {session, mode: "resume", cols, rows})`;
   - sets and prints the summary.
6. `agentWatchJob` polls `GET /api/agents`, toasts the summary and calls `onDone`. Manage terminals then repaints
   with the new panes listed, or Config reloads its job view.
7. Meanwhile the recorder refreshes the reopened sessions' `seen` as their panes show Claude.

## 7. The risky spot and its fallbacks
1. **The record's truth (main risk).** History comes from `upgrade_candidates()` every 60 s or less (sooner on a
   pane change).
   - A session whose Claude ran for less than one 15 s tick is never recorded.
   - Plain shells are never recorded. A `--fork-session` copy is recorded under its new id only when Claude's pid
     file names it (`term_vt.py:4121-4122`).
   - By R-D1's design, a session the user finished on purpose is offered again.

   **Fallback:** the list is shown before anything opens, newest-first, with checkboxes, and the user unticks.
   Nothing opens without a confirm.
2. **Running elsewhere.** It is detected from Claude's procStart-verified pid files (`running_sessions`). This covers
   another tracker's panes too, which appear as "can't" rows with their pid.
   - An old CLI with no pid file, open in Terminal.app, is not detected and would run twice.
   - There is no transcript-recency check, because it would block the main case: every just-killed session was
     written seconds ago.

   **Fallback:** the list.
3. **Slot race.** The re-check runs at confirm time. A pane opened by anyone between that check and the job's open
   gets `open_pty`'s own 429, which becomes a `failed` item with its text. A session opened by hand meanwhile gives a
   `reused` 200, which becomes a `failed` item with `AGENT_RA_REUSED`. No slot is freed to make room, and nothing is
   queued.
4. **Unwatched panes are idle-reaped** after `TERM_IDLE_TTL_MIN` (`_reader`); this is existing policy and
   `AGENT_RA_NOTE` says so. A reaped pane stays in the history (R-D1), so the button can bring it back.
5. **The CLI refuses a resume** (it sees a background agent). `open_pty`'s backstop retries with `--fork-session`
   after the 200 (see the `open_pty` docstring), so the summary says "Resumed" for what became a fork. This is a
   known limit shared with AU.
6. **Same-folder opens** are serialised: one thread, one open at a time. The second one overflows, and `_ra_need`
   counts it. Daemon-hosted sessions are listed as "can't" and never opened, because of the swap hazard
   (`term_vt.py:~3307-3311`).
7. **Two trackers from one checkout** share the list. Each tick is a locked read-modify-write that only adds or
   refreshes entries, so neither tracker drops the other's. A tracker that comes back on a different port sees the
   whole list.

## 8. Sequencing
Each step is a separate commit, and `unset TRACKER_AUTH; make check` must be green before the next. The commit hook
runs the full gate, so give `git commit` a Bash timeout over 6 min, and commit with `-F <file>`.

| Step | Lands | Tests (plus re-run) |
|---|---|---|
| R0 | `store._update_json` (with `_update_forks` delegating to it), `agent_cli._agent_launch` (with `agent_start` on it), `_agent_fail(..., label)`, `_agent_resume(..., reused=)`, `agentWatchJob(id, onDone)` with `_agentJobDone`/`_agentFireDone` | T0a, T0b; re-run `test_fork_follow`, `test_agent_cli_jobs`, `test_agent_cli_parse`, `test_agent_cli_outside`, `test_agent_routes`, `test_agents_ui` unchanged |
| R1 | `config.LAST_TERMS_FILE`, `.gitignore`, the record section in `term_vt`, the `server.run` start, the `restart_in_place` hook, `tests/__init__.py` isolation | T1-T5, T7, T7b; re-run `test_update_restart`, `test_update_routes`, `test_pending_routes`, `test_term_vt_upgrade`, `test_claude_running`, `test_integration` |
| R2 | `term_vt.RA_*`, `_ra_need`, `resume_all_plan` | T8, T9 |
| R3 | the `agent_cli` resume-all strings and functions, `agent_status` `can_resume_all` | T10-T13 |
| R4 | the `server.py` route and import | T14 |
| R5 | `resumeAllWidget`, both hosts, `onRefresh` in `_openManageDialog` | T15; re-run `test_cr_manage_terminals_parity`, `test_cr_manage_terminals_poll`, `test_agents_ui` |
| R6 | README line, CLAUDE.md app-owned-state line, `_selfcheck` assertion, `make bundle` | T16, `test_page_bundle`, `test_selfcheck` |
| R7 | live proof (end of §9), then `/branch-sync`, the full gate, and pushing the branch to `personal` | — |

R1 should land as early as the user accepts, because the record only exists from the first run that has R1.

## 9. Tests
All tests are stdlib unittest. Each is proved red by reverting its fix, and no test writes the real record.

Every new test that touches the record patches `config.LAST_TERMS_FILE` to its own `tempfile.mkdtemp()` path, on top
of `tests/__init__.py`'s suite-wide redirect. It saves and restores `term_vt._REMEMBER_ON`, `_LAST_FP` and
`_LAST_FULL`. Fake panes use the `tests/test_term_vt_upgrade.py` idiom (`_Base`, `term_vt.Pty(tid=, pid=, fd=,
cwd=)`, `tests.test_folder_terminal._stub_kill`/`_FakeHandler`). No real `claude` runs, and `call_route` is stubbed
in the job tests.

New `tests/test_resume_all_record.py`:
- **T0a `store._update_json`:** two threads each apply 10 mutations to one temp path, and all survive. A mutate
  returning False writes nothing (mtime unchanged). Red: drop the lock, and updates are lost (same shape as the
  existing forks test).
- **T1 `_entries`/S3:**
  - A row with `session` X and `target` Y gives key Y.
  - An empty target is skipped.
  - A duplicate target collapses to the first.
  - The entry keys are exactly `{cwd, title, seen, cols, rows}`.

  Red: key on `session` instead of `target`.
- **T2 `_merge_terms` (R-D1, B1):**
  - `d = {A}` with live `{}` returns False and leaves `d` unchanged.
  - Live `{B}` returns True and gives `{A, B}`.
  - Live `{A'}` with an older `seen` than stored keeps the stored `seen` and takes the new `title`.
  - A junk value (`"x": 5`) is dropped.
  - 40 distinct entries are capped at 32, dropping the oldest `seen`.

  Red: rebuild from live only, and A vanishes; drop the empty guard, and an empty tick prunes or writes.
- **T3 two trackers (the merged-history reversal):** the temp file holds X, written directly as another tracker
  would. With `_REMEMBER_ON = True` and stubbed `upgrade_candidates`/`_pane_fingerprint` giving live Y,
  `remember_terminals(final=True)` leaves `{X, Y}`. With live X carrying a newer `seen`, X's `seen` moves forward.
  Red: write `live` alone, and X is lost.
- **T4 gate and write:** use the same stubs and count the `upgrade_candidates` calls.
  - Two calls with the same fingerprint under 60 s make one call.
  - `final=True` forces a second.
  - A fingerprint of `()` makes zero calls and creates no file.

  Red: remove the gate or the empty-fingerprint return.
- **T5 not recording / isolation (B2):**
  - With `_REMEMBER_ON = False`, `remember_terminals(final=True)` creates no file.
  - `config.LAST_TERMS_FILE` is not under `os.path.dirname(aitracker.__file__)`.
  - `term_vt.start_remember()`, which is the suite stub, returns False, and no thread named `term-remember` is alive.
  - `_real_start_remember()` starts one, and `_REMEMBER_STOP.set()` ends it (joined).

  Red: delete the `tests/__init__.py` lines, and the path and thread assertions fail.
- **T7 `remembered_terminals`:**
  - The file holds A (seen 3), B (seen 2) and C (seen 1), plus junk, and `store._find_transcript` is stubbed to
    return "" for B. The result is `[A, C]`, each with a `session` key.
  - It works with `_REMEMBER_ON = False`, as a fresh run on another port would.

  Red: skip the transcript filter, and B is listed.

New `tests/test_resume_all_plan.py`:
- **T8 `_ra_need`:** `(["/a"], {"/a"})` gives 0; `(["/a", "/a"], {"/a"})` gives 1; `(["/b", "/b"], set())` gives 2.
  Red: count an idle cwd as 1.
- **T9 classification and pre-tick:** stub `remembered_terminals` with nine entries:
  - an Auggie id;
  - one already open via a fake pane with `fg.session`;
  - one with a `daemon` host;
  - one with a `desktop` host;
  - one with a `tui` host, pid 77;
  - one where `resume_argv` raises `GatewayError("x")`;
  - one where `session_cwd` returns "";
  - three openable ones.

  Set `MAX_TERMS - live == 2`, with an idle folder pane for the third openable's cwd. Expect:
  - each failing entry in `cannot` with its exact `RA_*` text (the tui one contains "pid 77");
  - the open one in `already`;
  - all three openable in `open`, all `checked`, because the idle shell costs 0.

  With no idle shell, the oldest openable is in `open` with `checked: False`. Red: removing any one check moves its
  row into `open`; removing the pre-tick ticks all.

New `tests/test_resume_all_jobs.py` (agent_cli). `_agent_tv` is patched to a fake tv exposing `resume_all_plan`,
`_ra_need`, `call_route`, `open_pty` and `term_gate`:
- **T0b `_agent_launch`:**
  - `_AGENT_JOB_LOCK` held gives 409 "an agent job is already running".
  - `_APPLY` held gives 409, and the lock is released.
  - `threading.Thread.start` raising `RuntimeError` gives 500, with the lock released.

  Red: skip a release.
- **T10 preview:**
  - tv None gives 409 NO_TERMS.
  - `term_gate.allowed()` False gives DISABLED.
  - A running job gives a 409 error.
  - An empty plan gives `message == AGENT_RA_NONE`.
  - A plan with one unticked open row sets `pick`.
  - `idle`, `port` and `saved_at` are not in the body.

  Red: drop a guard.
- **T11 confirm validation and re-check (R-D3):**
  - `confirm` set to `"x"`, `[]`, 65 items or `[1]` gives 400.
  - A ticked set whose `_ra_need` exceeds free gives 409 with `needs_confirm` and an `error` starting "The 2 you
    ticked need 2 terminal slots", and no job starts.
  - Nothing ticked openable gives 409 `AGENT_RA_NONE_PICKED`.
  - A forged id outside the record alone also gives 409 `AGENT_RA_NONE_PICKED`.
  - `["A", "A"]` starts a job whose `confirm` is `["A"]`.

  Red: remove the need check, and the response is 202.
- **T12 job (R-D4, S4, F4):** `call_route` records the bodies it gets and answers:
  - 200 `{tty: "t9"}` for A;
  - 429 `{"error": "too many running terminals (max 2)"}` for B;
  - 200 `{tty: "t4", reused: True}` for D.

  Confirm `[A, B, C, D]`, where C is now in `cannot`. Expect:
  - every body has `mode == "resume"` and no `"prompt"` key;
  - item A is `unprompted` with `tty_after` "t9";
  - item B is `failed` with the 429 text;
  - item C is `failed` with its reason;
  - item D is `failed` with exactly `AGENT_RA_REUSED % "t4"`;
  - every item's key set equals `set(ac._AGENT_ITEM_KEYS)`;
  - the summary equals the exact `_agent_ra_summary` string.

  A busy `_pending_lock` gives state failed, summary `AGENT_RA_FAIL_SCAN`, and zero `call_route` calls. Red: pass
  `busy=True`, and a prompt key appears; drop the `reused` argument, and D says "press Upgrade again".
- **T13 `agent_status`:** the claude row has `can_resume_all` True with a fake tv whose `term_gate.allowed()` is
  True, and False with tv None. Red: drop the key.

`tests/test_update_restart.py`:
- **T7b:** patch `os.execv` to raise a sentinel, put a recorder at `sys.modules["aitracker.term_vt"]`, and stub
  `tunnel`. `restart_in_place(1, {})` calls `remember_terminals(final=True)` before `execv`, and a recorder that
  raises does not stop the exec attempt. Red: remove the call.

`tests/test_agent_routes.py` (AU's `_Routes`, `:28-59`):
- **T14 `/api/terminals/resume-all`:**
  - a proxied header gives 403;
  - `{}` gives 409 `needs_confirm`, with the plan function patched on `_server`;
  - `{confirm: ["S1"]}` gives 202, with the start function patched;
  - a `[1]` body gives 400;
  - read-only (`_readonly` patched True) gives 403.

  Red: remove `_local_caller`, and the proxied request passes.

New `tests/test_resume_all_ui.py` (static source plus node; review F6 spells out the harness):
- **Static checks:**
  - the button text appears;
  - `'/api/terminals/resume-all'` is referenced;
  - none of the `AGENT_RA_*`/`RA_*` sentences appear in the JS (import them from `agent_cli`/`term_vt` and assert
    `not in`).
- **Node harness:**
  - Lift `resumeAllWidget`, `agentWatchJob` and `renderManageTerminals` with `_extract_function` from
    `tests/test_cr_manage_terminals_poll.py`.
  - Declare `var _agentJobTimer = null, _agentToasted = null, _agentWatchId = null, _agentJobDone = null;` and
    `_agentFireDone`.
  - Stub `h`, giving nodes `addEventListener`, `checked`, `disabled`, `hidden` and `innerHTML`.
  - Stub `crBtn` and `crCall`. `crCall` is a scripted response queue that records `{url, body}`.
  - Also stub `crReadOnly` (toggleable), `toast` (recorder), `setInterval`/`clearInterval` (manual `tick()`),
    `buildChrome`, `emptyState`, `errorState`, `icon`, `timeAgo`, `cwdTail` and `sessionTitleFor`.
- **T15 cases:**
  - `renderManageTerminals` with `onRefresh` and `terminals: []` renders `.cr-resume-all` in the empty state, and
    with one terminal renders it in the footer.
  - Without `onRefresh` (the cap dialog) there is none, and `crReadOnly` is never called.
  - With `crReadOnly()` true there is none.
  - A 409 plan renders `message`, `pick`, `reason` and `note` verbatim, with one checkbox per `open` row, checked per
    `checked`.
  - `update({terminals: [...]})` keeps the picker.
  - Confirm POSTs exactly the ticked ids, and two clicks send one POST.
  - `agentWatchJob(1, cbA)` then `agentWatchJob(2, cbB)` calls cbA once with null. Job 2 finishing calls cbB, and a
    poll with `ok: false` fires neither.
  - `agentsBlock` with `can_resume_all` shows the button in the Claude row.

  Red: move the widget's creation inside `paint()`, and the picker is lost on update; drop the `onRefresh` gate, and
  the cap dialog shows it; drop `_agentFireDone(null)` on the id switch, and cbA never fires.
- `tests/test_agents_ui.py` stays green as is (its `:48` regex and `:37` phrase list).
- `tests/test_cr_manage_terminals_parity.py` and `tests/test_cr_manage_terminals_poll.py` stay green unchanged
  (review F2).

`tests/test_selfcheck.py` `_run()`: **T16, the `_selfcheck` assertion** (conventions rule 9, non-trivial logic):
```python
E = {"cwd": "/x", "title": "", "seen": 1, "cols": 80, "rows": 24}
_d = {"a": dict(E)}
assert term_vt._merge_terms(_d, {}) is False and _d == {"a": E}, "an empty tick never rewrites the history"
assert term_vt._merge_terms(_d, {"b": dict(E, seen=2)}) and set(_d) == {"a", "b"}, "closed sessions stay listed"
```
Claude-only: Auggie never runs in a tracker terminal, because of the `_is_claude` gate on resume.

**Live proof (R7).** This needs the user's OK and follows the safe-scratch protocol: tear down only with proof of
ownership, never `pkill -f aitracker`, and stop test servers by PID.
1. Start a test server on a spare port from the worktree. Open two scratch sessions through its dashboard, then
   close one pane; it must still be listed (R-D1). Open one scratch session in Terminal.app.
2. Stop the test server by PID. Start it again on a **different** spare port (the merged history must still offer
   both). Open Control Room → Manage terminals, which is empty.
3. Press the button.
   - Both scratch sessions are listed and ticked. The Terminal.app one is under "can't" with its pid.
   - Set Max terminals to 1 and press again. One is ticked and `pick` is shown.
   - Tick both and confirm. Expect a 409 with the fresh list and the "need 2 terminal slots" error.
   - Restore the cap and confirm. No modal opens, two rows appear, and the toast matches the job summary.
     `last_terms.json` holds both session ids with fresh `seen`.
4. Repeat once from Config → Agents.
5. Tear down every scratch session, transcript, pane and test server this created.

## 10. README and CLAUDE.md (R6)
- **README.md**, in the section "## Terminal — on by default", after the "Folder terminals" bullet:
  > - **Resume all prior terminals**: in Control Room → ☰ Manage terminals, or in Config → Agents next to Upgrade.
  >   It lists the most recent Claude sessions (up to 32) that ran in a tracker terminal from this checkout,
  >   including ones you closed and ones from earlier runs. It ticks the newest that fit in the free terminal
  >   slots, says which can't be reopened and why, and resumes the ticked ones with `claude --resume` in the
  >   background. No window opens and no prompt is sent. The record is `aitracker/last_terms.json`, one list shared
  >   by every tracker started from this checkout. Plain shells are not remembered.
- **CLAUDE.md**, on the "App-owned state" line: add `last_terms.json` (written by `term_vt.remember_terminals` via
  `store._update_json`) next to `flags.json`/`titles.json`.
- The commit message notes conventions rule 6. The new file is ordinary app-owned state: atomic, gitignored, and
  holding only ids, cwds, titles, sizes and last-seen times. No session log is read or written beyond the existing
  `_find_transcript` existence check.

## 11. Deliberately left out
- The classic dashboard's Manage terminals (`ext_vt.js` `renderManagerBody`). R-D2 names only Manage terminals
  (Control Room) and Config.
- The at-cap "free a slot" dialog (`_openCapDialog`), per S6.
- Any prompt to resumed sessions, per R-D4.
- Opening daemon-hosted, desktop or Auggie sessions. They are listed with a reason and never opened.
- A shutdown (SIGTERM or `finally`) write, and debouncing of removals. With history semantics neither is needed (B1
  dissolved).
- Per-port keys, a boot/generation rule, an in-memory history copy, and a flock "owner" per checkout. All are
  replaced by the merged history (main-thread reversal).
- An `opened` timestamp, and any change to `upgrade_candidates` (review F5).
- An age-based purge, and a "Forget" button. The list is bounded by `LAST_TERMS_MAX` and transcript existence.
- Recording at `open_pty` time, which would catch sessions shorter than one tick. It would be a second recording
  path, and the tick is enough.
- Auto-resume on startup, and restoring scrollback, focus or tab order.
- Reporting a late `--fork-session` retry as a fork in the summary.
- Rewording `update.py:271` (AU's text; see §5).

## 12. Decisions the user may still want to overrule
1. **Already-open sessions are one line** ("Already open in a terminal here, so not listed: …"), not rows. With R-D1,
   every pane open now is also in the history, and listing each as a "can't" row would bury the list. Alternative:
   list them as "can't" rows. (Accepted by the main thread as a default.)
2. **Order and pre-tick by last seen running** (newest first), so the sessions alive when the tracker stopped come
   first and are pre-ticked. Alternative: order by when each was first opened. (Accepted as a default.)
3. **One merged list per checkout** (main-thread reversal). A session open right now in another tracker from the
   same checkout appears as a "can't" row with its pid. No age bound: the last 32 are offered however old.
4. **Bound:** 32 sessions in total. Smaller or larger is a one-constant change.

## Revision log
- 2026-11-16, opus second-pass reviewer (`resume-all-review-final.md`):
  - Folded in the main-thread reversal: one merged history keyed by session id via `store._update_json`.
  - Removed per-port keys, boot/prior/saved_at, `_HISTORY`, `LAST_TERMS_PORTS`, `_agent_ra_age`, `AGENT_RA_STOPPED`
    and the `upgrade_candidates` `started` key (F1, F5, N7).
  - Gated `raParts` on `onRefresh` first (F2).
  - Re-grounded `agentWatchJob(id, onDone)` on AU's current `_agentWatchId` version (F3).
  - Added the `_agent_resume` `reused` parameter and `AGENT_RA_REUSED` (F4).
  - Specified the T15 node harness and the `boxes` array (F6).
  - Exact `AGENT_RA_NOTE` label, `RA_TUI` wording, deduped `confirm`, an empty-fingerprint early return, and the
    `_REMEMBER_ON` gate stated as the real test guard (N2, N3, N5, N6, N8).
  - Fixed the fork-copy claim (N1).
  - Re-grounded the `agent_cli.py` line numbers after AU's review fixes.
