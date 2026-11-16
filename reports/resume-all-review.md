# Resume all prior terminals: adversarial review of `reports/resume-all-plan.md`

Reviewed 2026-11-16 by the opus review agent, in worktree `.claude/worktrees/agent-upgrade`, against HEAD `fe8f580`
plus the uncommitted AU work in progress (`agent_cli.py`, `term_vt.upgrade_candidates`/`call_route`, the AU S7 block in
`ext_cr_dialogs.js`, which landed while I was reading). I read only. I ran no `git diff` over the tree and no `git stash`,
and I started no process. Every claim below was checked against the code with grep plus line-range reads.

**Verdict: the plan needs changes before implementation.** It is grounded far better than average: nearly every
symbol exists and does what the plan says. But the on-disk record can lose the list in two realistic cases (a
shutdown, and a second tracker started from the same checkout). The test-suite isolation it claims is false. One line
of prescribed server code breaks `make bundle`. And it forks two pieces of AU logic that it says it reuses.
Counts: **2 BLOCKER, 6 SHOULD-FIX, 11 NIT.**

## Grounding check (what is true)

| Claim | Verdict |
|---|---|
| Nothing persists open terminals today | **True.** `PTYS` lives in memory (`term_vt.py:1309`). Grep finds no `last_terms`/terminal record. `forks.json`, `SNAPSHOT_TTL_MIN` and `TERM_IDLE_TTL_MIN` are what the plan says they are. |
| Update and restart closes every pty | **True, at exec, not before it.** `_cloexec_all` (`update.py:329-344`) marks every fd ≥ 3 non-inheritable, so the kernel closes the masters at `os.execv` (`update.py:366`). The warning is `update.py:301-304`. |
| Manage terminals dialog | **True.** `renderManageTerminals` at `ext_cr_dialogs.js:2198` (HEAD numbering; now shifted by the AU S7 insert): empty state `:2220-2223`, footer `:2325-2329`, `update()` filter `:2341-2349`. Also used by the **cap dialog**: `_openCapDialog` (`ext_cr_term.js:677-700`) opens the same `'manage-terminals'` name (see S6). |
| Classic has an equivalent view | **True, and the plan names it:** `openManager`/`renderManagerBody` (`ext_vt.js:3257/3304`), button `#sidemanagetermbtn` (`ext_launch.js:100-110`), classic the default (`ext_cr_boot.js:229-230`). It is skipped by decision (b), not missed. |
| Upgrade button lives in Config → Agents | **True.** AU S7 `agentsBlock` at `ext_cr_dialogs.js:1322-1405` (live file). `agentWatchJob(id)` is at `:1309-1320`, and it has a single module timer (`if (_agentJobTimer) return;`). |
| open_pty slot math, peek, overflow, deferred start, swap | **True.** 429 at `term_vt.py:3162-3171` and `:3315-3317`; peek `:3148-3157`; claim/deferred `:3231-3280`; swap `:3307-3311`; overflow `:3313-3349`. |
| Idle reap holds only for `_claude_busy`/`_session_live` | **True** (`term_vt.py:1770-1780`). The `_session_live` window is `max(LIVE_WINDOW, TTL*60)` (`:4234`), so a just-killed session is held until its transcript is about 30 min old. |
| `--fork-session` retry happens after the 200 | **True** (`open_pty` docstring `:3023-3036`). `forked` in the response is always False. |
| Locks: `_AGENT_JOB_LOCK` blocks `update_apply`; `_APPLY` blocks agent jobs | **True** (`update.py:28, 267-271`; `agent_cli.py:341-345`). `_AGENT_JOB_LOCK` lives in `update.py`, not agent_cli. That is harmless. |
| `_local_caller` = no proxy header, same Origin, loopback peer, loopback Host w/o AUTH | **True** (`server.py:223-240`). `_readonly()` deny-all before the body is parsed (`server.py:632-633`). |
| "run() is the only caller of start_remember, so unit tests never write the real file" | **False.** See B2. |
| Line numbers in `term_vt.py` | Accurate at HEAD. They have since drifted under the AU edits (`_session_pty` 3516→3651, `term_list` 3862→3997, `_pty_session_ids` 3982→4195, `_session_live` 4003→4216, `_foreground_is_claude` 4030→4243). See N1. |

## Contract check, clause by clause

- **C1/C4 "prior terminals / last spawned sessions"**: "Claude sessions in tracker terminals when the tracker last
  stopped" is a defensible reading. No existing data gives a better one: Claude's own pid files
  (`~/.claude/sessions/<pid>.json`) describe only live processes, and `running_sessions()` drops dead pids
  (`claude.py:750`). Here is what the plan's record holds in each case:
  - **Clean `make stop`:** the live set, written in the SIGTERM `finally`. That write is the B1 hazard.
  - **Crash / `kill -9`:** the last periodic write (≤ 15 s stale). Correct.
  - **Update and restart:** the final write runs before `_cloexec_all` while the panes are still alive. Correct.
  - **Agent upgrade:** the tracker stays up, so `prior` is untouched and `terminals` follows the restarted panes.
    But a restart that the CLI turned into a `--fork-session` copy is **silently dropped**, because
    `_pty_session_ids` returns `()` for a forked pane (`term_vt.py:4206-4212`). See N9.
  - **Two quick restarts, the second with no terminals:** traced through `_terms_record`. `prior` survives, because
    an old record with empty `terminals` falls back to `old.prior`. **Correct as designed.**
  - **The overwrite the brief asked about:** `prior` *can* end up holding the wrong set or an older set, in B1 and S1.
- **C2 "alongside the upgrade version button"**: the plan re-reads this as "part of the same change". The literal
  reading, next to the Upgrade button, is not offered to the user. See S5.
- **C3 "in the manage terminals view itself"**: met for Control Room. Classic is left out by decision (b). The plan
  never states that the button also shows in the **cap** dialog (S6).
- **C5 "list the sessions which will be opened"**: met. The rows that will open and the rows that cannot, with
  reasons, come from the server.
- **C6 "open all of them in the background"**: met. I checked that nothing in the SPA auto-opens a pane for a new
  tty: `bindRows` (`ext_vt.js:349-353`) only binds ids. `call_route` opens unwatched panes and no modal opens.

---

## Findings, most severe first

### B1. BLOCKER: the shutdown "final write" can record a gutted set, and the list is then lost or replaced by an older run's
- **Defect.** Plan §4.1 "When it is written" (2) wraps `srv.serve_forever()` (`server.py:1048`) in a `finally` that
  calls `remember_terminals(final=True)`. That walk keeps a pane only if `_foreground_is_claude(p.fd)` is True. At a
  system shutdown or logout, launchd sends SIGTERM to the tracker **and** to every Claude at the same moment. The
  Claudes exit first: they are simple, while the tracker runs `tunnel.stop()` and then this `ps`-forking walk. So
  the final write sees no Claude in the foreground and writes `terminals: []` for this boot. Then, by the plan's own
  `_terms_record` rule, the next boot takes `prior = old.prior`: **the run before last**. The list from the run that
  just died is gone. The dialog then offers the older sessions as "open when the tracker last stopped".
  The periodic 15 s tick has the same race at a lower probability (about 1 in 15 per shutdown).
  **Repro (unit level):** set `PTYS = {A, B}` with `_foreground_is_claude` → True and call `remember_terminals()`.
  Flip `_foreground_is_claude` → False (the Claudes died) and call `remember_terminals(final=True)`. Then call
  `_terms_record(old, "next-boot", [], now)`. Actual: `prior` = the older run, or `{}`. Expected: `prior.terminals ==
  [A, B]`.
- **Fix direction.**
  - Remove the SIGTERM `finally` write entirely, together with its T4 sibling test.
  - Make the periodic write **debounce removals**: a session leaves the record only once two consecutive computed
    ticks have not seen it. Additions apply at once.
  - Keep the `restart_in_place` final write. It is deterministic: the tracker itself is about to close the panes,
    and nothing else is dying. That write uses the plain live set, with no debounce.
  - Must NOT change: the generation rule in `_terms_record`. Its empty-run fallback is correct, and it is what
    makes two quick restarts safe.
- **Way.**
  - In `term_vt`, add a pure function `_debounced(recorded, prev_ids, live) -> list`. It returns `live + [e for e in
    recorded if e["session"] not in {l["session"] for l in live} and e["session"] in prev_ids]`.
  - `remember_terminals` keeps `_SEEN_PREV`, the set of session ids from the previous *computed* live. It records
    `live if final else _debounced(_REMEMBERED or [], _SEEN_PREV, live)` and then sets `_SEEN_PREV = ids(live)`.
  - `server.run`: no `try/finally`.
  - A deliberate close-all is therefore recorded one tick later. A shutdown never survives that long.
- **Test (red first).** `T2b` in `tests/test_resume_all.py`, on the pure function:
  - ticks `[A, B]` → `[]` → `[]` give records `[A, B]`, `[A, B]`, `[]`;
  - `[A]` → `[A, C]` gives `[A, C]` on the first tick.
  - Red: return `live` unchanged → the second record is `[]`.

### B2. BLOCKER: the test suite starts the recorder, writes the user's real `aitracker/last_terms.json`, and leaks a forever thread
- **Defect.** Plan §4.1 says "`run()` is the only caller of `start_remember`, so unit tests that import `term_vt`
  never write the real file". That is false. Existing tests call `server.run()` with `bind` stubbed:
  - `tests/test_pending_routes.py:93-103` (`test_run_calls_start_worker`);
  - `tests/test_update_routes.py:120-136` (`_run`, used by 3 tests).

  They stub `start_worker`, but nothing stubs `start_remember`. After R1, each of them sets `_REMEMBER_ON = True` and
  starts a daemon thread that rewrites `config.LAST_TERMS_FILE`, which is the **checkout's real** `aitracker/last_terms.json`,
  every 15 s for the rest of the test process. `test_update_routes._run` also wraps `threading.Thread` and calls
  `t.join(5)` on every thread it created. The remember loop never ends, so each of those 3 tests gains a dead 5 s.
  The writes use `boot = <test process>` and an empty live set. By `_terms_record`, that turns a live dashboard's
  current set into "prior" and pushes its real prior out. This happens whenever `make check` (or the commit hook)
  runs in the checkout a dashboard is serving from.
- **Fix direction.**
  - Isolate this once, for the whole suite, in `tests/__init__.py`. That is the existing idiom: it already replaces
    `term_vt._background_target` and keeps the original as `_real_background_target`.
  - Must NOT change: `server.run` still starts the recorder in production.
- **Way.** In `tests/__init__.py`, add:
  ```python
  import tempfile as _tf, os as _os
  from aitracker import config as _config
  _config.LAST_TERMS_FILE = _os.path.join(_tf.mkdtemp(prefix="ait-lastterms-"), "last_terms.json")
  _term_vt._real_start_remember = _term_vt.start_remember
  _term_vt.start_remember = lambda: False
  ```
  `server.run` must call it as `tv.start_remember()` through the module attribute, so the stub applies.
  T3 and T4 use `_real_start_remember` with their own tmp path.
- **Test (red first).** `T3b`:
  - assert `not config.LAST_TERMS_FILE.startswith(os.path.dirname(aitracker.__file__))`;
  - run `test_update_routes`-style `server.run` (bind stubbed, `serve_forever` raises);
  - assert no thread named `"term-remember"` is alive and that the real `aitracker/last_terms.json` mtime is
    unchanged.
  - Red: delete the two `tests/__init__.py` lines.

### S1. SHOULD-FIX: two trackers from one checkout overwrite each other's record and each adopts the other's live set as "prior"
- **Defect.** CLAUDE.md documents `make serve` as "start on PORT, or the next free port if busy; does not stop a
  running one". Two instances from one checkout therefore share `aitracker/last_terms.json`.
  **Repro.**
  - X (8790) has `[A]` and real prior `P`.
  - Start Y (8791). Y's first write sees `old.boot == X != Y` with non-empty terminals, so Y sets `prior := X's live
    [A]`.
  - X's next change-write sees `old.boot == Y != X`, so X sets `prior := Y's record`, or `Y.prior` if that is empty.
  - `P` is now gone from the file for good.

  The planned shutdown `finally` (B1) makes `make stop; make serve` likelier to overlap, because the old process
  keeps port 8790 bound while it runs `ps` walks, so the new one lands on 8791.
  Safety still holds: Y's button lists `A` as "running … (pid)" (`running_sessions` host `tui`). Only the list is lost.
- **Fix direction.**
  - One recorder per record file.
  - Must NOT change: the file path, which stays per checkout (worktrees already get their own).
- **Way.**
  - `start_remember()` opens `config.LAST_TERMS_FILE + ".lock"` and takes
    `fcntl.flock(fh, LOCK_EX | LOCK_NB)`. On `OSError` it returns False, and the recorder and button stay off for
    this instance.
  - It keeps `fh` in `_REMEMBER_FH` for the process lifetime. Python opens it non-inheritable, so the re-exec'd
    process after Update and restart gets the lock back.
  - `agent_plan_resume_all` returns `409 {"error": AGENT_RA_NOT_OWNER}` when `tv._REMEMBER_ON` is False.
  - Add `last_terms.json.lock` to `.gitignore`.
- **Test (red first).** `T3c`:
  - `_real_start_remember()` returns True;
  - a second `fcntl.flock` on the same lock path from a fresh fd raises `BlockingIOError`;
  - with `_REMEMBER_ON` False the preview returns 409 `AGENT_RA_NOT_OWNER`.
  - Red: drop the flock → the second lock succeeds.

### S2. SHOULD-FIX: prescribed `server.py` code breaks `make bundle` and the bundled build
- **Defect.** Plan §4.1 adds `tv = sys.modules.get(__package__ + ".term_vt")` to `server.run`.
  - `scripts/bundle.py:93` asserts `"__package__" not in body` for `server.py` once it has stripped the loader, so
    `make bundle` fails its assertion.
  - Run standalone, `__package__` is `None` (the comment at `bundle.py:74`), so the same line is a `TypeError` at
    startup in `dist/tracker.py`.
- **Fix direction.**
  - Use the literal module name, as `update._term_live` (`update.py:104`) and `agent_cli._agent_tv`
    (`agent_cli.py:167-168`) already do.
  - Must NOT change: the bundle regex.
- **Way.** `tv = sys.modules.get("aitracker.term_vt")` in `server.run`, and the same literal in
  `update.restart_in_place`.
- **Test (red first).** The existing bundle test (`tests/test_page_bundle.py`) plus `python3 scripts/bundle.py`.
  Red with the `__package__` form.

### S3. SHOULD-FIX: the recorder forks AU's pane walk and inherits its stale-label bug; the foreground filter covers only folder panes
- **Defect.** Plan §4.1 `_live_claude_sessions` re-implements the first half of `upgrade_candidates()`
  (`term_vt.py:4098-4120`: reap, `_refresh_fg`, foreground filter, cols/rows). That breaks the conventions rule
  against two implementations of one thing. It also drops `upgrade_candidates`' relabel (`:4122-4124`): there the
  pane's real session comes from the procStart-verified pid file whenever the label is stale.
  - Labels go stale when the user runs `/clear` or `/resume <other>` inside a pane. `_pty_session_ids` says so itself
    (`:4196-4202`).
    **Repro:** pane opened on session X; the user runs `/clear` inside it, so Claude now runs Y. The record stores X,
    and after a restart the button resumes the pre-clear conversation X.
  - The plan also applies `_foreground_is_claude` to folder panes only. A dedicated overflow shell (`argv =
    shell_argv`, `:3221`) where the user typed `claude` and then exited still yields `(spawned,)` (`:4213`), so a
    finished session is recorded.
- **Fix direction.**
  - Build the record from `upgrade_candidates()` rows. They already filter every pane on `_foreground_is_claude`
    (`:4118`), relabel, dedupe, and carry `cwd`/`cols`/`rows`/`title`.
  - Bound the cost (`running_sessions()` forks `ps` per live Claude, `claude.py:731-778`) with a cheap fingerprint
    gate.
  - Must NOT change: what `upgrade_candidates` returns to AU, apart from one added key.
- **Way.**
  - Add `"started": (p.fg or {}).get("started") or p.started` to each `upgrade_candidates` row. That is one key; no
    test asserts the key set.
  - New `_pane_fingerprint()`: under `_LOCK`, call `_reap()`, then build
    `tuple(sorted((p.id, _fg_pgid(p) if p.folder else p.pid) for p in PTYS.values() if not p.done and not p.closing))`.
    That is syscalls only, with no `ps`.
  - `remember_terminals` recomputes only when the fingerprint changed, or when `REMEMBER_FULL_EVERY = 60` s have
    passed, or on `final`.
  - The record is `_entries(upgrade_candidates())`: keep rows with a non-empty `target`, dedupe on `target`, and map
    each to `{session: target, tty, cwd, opened: started, cols, rows, title}`. Sort newest first and cap at 64.
- **Test (red first).** T1, rewritten:
  - stub `upgrade_candidates` to return a relabelled row (`session` X, `target` Y). The record holds Y.
  - Stub the fingerprint unchanged and the clock under 60 s, then call twice: `upgrade_candidates` runs once.
  - Red: record `_pty_session_ids` → X; remove the gate → called twice.

### S4. SHOULD-FIX: job items break AU's tested item schema
- **Defect.** Plan §4.3 step 3 builds `{session, title, cwd, outcome, tty_after, detail}`. AU requires a complete
  item: `_agent_item` (`agent_cli.py:135-140`) with `_AGENT_ITEM_KEYS` (`:88-89`), asserted in
  `tests/test_agent_cli_jobs.py:453` and `tests/test_agent_cli_parse.py:65`. The plan's item has the extra key `cwd`
  and lacks `tty, target, daemon, command, forked, on_version, prompt_seen, size_before`.
- **Fix direction.**
  - Build every item with `_agent_item`.
  - Must NOT change: `_AGENT_ITEM_KEYS`.
- **Way.**
  - Build each item with `_agent_item({"session": sid, "target": sid, "title": title, "command": row["command"]},
    outcome, detail)`.
  - On a 200, `item.update(tty_after=obj.get("tty"), forked=bool(obj.get("forked")))`.
  - Outcomes are `"opened"` or `"failed"`.
- **Test (red first).** In T6, add `assertEqual(set(item), set(ac._AGENT_ITEM_KEYS))` for every item. Red with the
  plan's shape.

### S5. SHOULD-FIX: `agent_start_resume_all` copies `agent_start`'s lock/seq/job/thread block instead of sharing it
- **Defect.** Plan §4.3 says it uses "the same locks as `agent_start` … the thread is `agent-resume_all` and its
  `finally` releases `_AGENT_JOB_LOCK`, as in AU". That is a second copy of `agent_cli.py:341-359` (lock, `_APPLY`
  re-check, `_AGENT_SEQ`, job dict, `_AGENT_JOB` swap, thread start with RuntimeError rollback). Two copies of the
  job-slot protocol drift: a later fix to one, such as the RuntimeError rollback, will miss the other.
- **Fix direction.**
  - Extract the shared tail once.
  - Must NOT change: `agent_start`'s validation, its 400/409 bodies, or its job keys.
- **Way.**
  - Move `agent_cli.py:341-359` into `_agent_launch(agent, action, fn, args) -> (code, body)`.
  - `agent_start` calls `_agent_launch(agent_id, action, fn, args)`.
  - `agent_start_resume_all(confirm)` validates `confirm` (a list of 1 to 64 non-empty strings; an empty list is a
    400) and checks `_REMEMBER_ON`, then calls `_agent_launch("claude", "resume_all", _agent_job_resume_all,
    (confirm,))`.
  - The thread runs through `_agent_thread`, which already sets `finished` and releases the lock.
- **Test (red first).**
  - The existing `agent_start` tests stay green.
  - T7: with `_AGENT_JOB_LOCK` held → 409 `"an agent job is already running"`; `_APPLY` held → 409; a thread-start
    `RuntimeError` → 500 with the lock released.
  - Red: skip the release in `_agent_launch`.

### S6. SHOULD-FIX: placement. The literal reading of C2 is never offered, and the button also lands in the at-cap dialog
- **Defect (a).** "alongside the upgrade version button, Put this button in the manage terminals view itself" has a
  literal reading the plan does not list: the Resume all button sits *next to* an Upgrade button, inside Manage
  terminals. Decision (b) offers only "classic too" and "Config → Update too".
- **Defect (b).** `_openCapDialog` (`ext_cr_term.js:677-700`) opens the same `'manage-terminals'` renderer when an
  open hits the cap. The plan says "the button there works without `onRefresh`". At the cap every row would come back
  "no free terminal slot", so a button there is noise in the one dialog whose job is "free a slot".
- **Fix direction.**
  - (a) Add the literal reading as decision (b4), with the plan's placement as the recommendation.
  - (b) Show the button only in the Manage dialog.
  - Must NOT change: the empty-state rendering, which is the main case after a restart.
- **Way.**
  - §12 (b4): "also put a Claude **Upgrade** button in the Manage terminals footer, beside Resume all. It reuses
    `agentsBlock`'s run path, adds about 15 JS lines, and needs no server change."
  - In `renderManageTerminals`, `resumeAllBlock()` returns null unless `payload.onRefresh` is set. Only
    `_openManageDialog` passes it.
- **Test (red first).** T9 adds two checks: a payload without `onRefresh` renders no `cr-resume-all` button; with it,
  the button renders in both the empty state and the list footer. Red: drop the `onRefresh` gate.

### NITs (each with its direction)
- **N1. Line drift.** The `term_vt.py` and `ext_cr_dialogs.js` numbers are HEAD-accurate but have drifted under AU.
  **Direction:** the implementer locates by symbol name, never by number. No plan change is needed beyond a note.
- **N2. Age helper "if `util` has one".** None exists; grep for `time_ago|_ago|human_age` across `aitracker/*.py`
  finds nothing. **Direction:** pin it as `_agent_ra_age(sec)` in `agent_cli`: `"%d min"` under 1 h, `"%d h"` under
  48 h, else `"%d d"`. Test it in T6.
- **N3. Double-click on "Resume these N".** The second POST races the 202 and returns 409 "an agent job is already
  running", which then paints as `raErr` while the job runs. **Direction:** set `raBusy = true` and repaint
  *before* the POST, and clear it on a non-202. T9 asserts a single POST after two clicks.
- **N4. The message says "when the tracker last stopped"** even when the record falls back to an older run.
  **Direction:** word it from `saved_at`: "… were open in tracker terminals when the tracker stopped %s ago". This is
  a text change only.
- **N5. `opened` uses `p.started`.** For a folder pane that is the shell's spawn time. **Direction:** use the claim
  time, `fg["started"]` (folded into S3's added `started` key).
- **N6. The "tui" reason right after Update and restart.** The closed panes' Claude can still be exiting for 1-3 s:
  SessionEnd hooks, measured at `PARKED_DETACH_WAIT`'s comment (`term_vt.py:3362`). **Direction:** append "If you
  just restarted the tracker, wait a few seconds and press again." to that reason.
- **N7. `remember_terminals` computes `live` outside `_REMEMBER_LOCK`.** A slower concurrent caller (the loop
  against the restart thread) can write the older snapshot last. **Direction:** compute inside the lock (the Clean
  plan does).
- **N8. Conventions rule 6.** Its text still names only `flags.json`/`titles.json`, though `pins`, `notes`, `forks`,
  `model_keep`, `title_sync` and `pending.json` all exist under the same helpers. **Direction:** no rule change. The
  new file is ordinary app-owned state: atomic `_save_json`, gitignored, ids, cwds and sizes only, no session log
  touched. Mention it in the commit message.
- **N9. Plain shells and forked copies are never remembered.** The pane runs an id the tracker never learns.
  **Direction:** document it in the README line. Not a dialog sentence, because nothing can be done about it.
- **N10. The Auggie check in §4.2 is unreachable.** The recorder keeps only Claude-foreground panes.
  **Direction:** keep it; one line defends against a hand-edited file.
- **N11. A `--fork-session` retry is reported as "opened".** **Direction:** no change; this is the known limit
  shared with AU §5.3. Keep §7.4's wording.

## What to cut (overbuilding)
- The SIGTERM `finally` write and its T4 sibling test (B1: it is the hazard, not a safeguard).
- `_live_claude_sessions` as a separate walk (S3: reuse `upgrade_candidates`).
- The separate `_BOOT` constant: `server._STARTED` (`server.py:243`) is already the per-process id, and `term_vt`
  already imports `server` (`term_vt.py:190`). Use `server._STARTED`.
- Nothing else. The rest is about the size of one button plus its preview.

---

## Clean plan

Status: plan only; no code before the user agrees (rule 8). This lands after AU S1-S8, on branch `agent-upgrade`.
"AU" means `reports/agent-upgrade-plan-final.md`.

### 1. Contract and readings
The user's words, verbatim: "add a resume all prior terminals button alongside the upgrade version button, Put this
button in the manage terminals view itself, where it opens the last spawned sessions, list the sessions which will be
opened and open all of them in the background".
- **C1/C4.** "Prior terminals" means the Claude sessions running in this checkout's tracker terminals when the
  tracker last stopped: after `make stop`, a crash, a reboot, or Update and restart. It does not include plain shells
  or forked copies, whose ids the tracker never learns.
- **C2/C3.** The button goes in Control Room → ☰ Manage terminals: in the empty state, and in the list footer
  before "Close all". It does not go in the at-cap dialog. Decision (b) carries the alternatives.
- **C5.** A preview lists the sessions that will open (title · folder · age) and the ones that can't, each with the
  server's reason and the command to run by hand.
- **C6.** On confirm, the server opens each session with `open_pty` `mode: "resume"` through `call_route`. No modal
  opens, nothing takes focus, no prompt is sent, and `mode: "new"` is never used. The new panes appear in the list.

### 2. The record: `aitracker/last_terms.json`
- **`config.py`:** add `LAST_TERMS_FILE = os.path.join(_HERE, "last_terms.json")` next to `FORKS_FILE`, with a
  one-line comment in the `PINS_FILE` style.
- **`.gitignore`** ("Personal / runtime data"): `last_terms.json` and `last_terms.json.lock`.
- **Shape** (via `store._save_json` / `store._load_json`):
  `{"boot": str, "saved_at": float, "terminals": [entry], "prior": {"boot", "saved_at", "terminals"} | {}}`, where
  `entry = {session, tty, cwd, opened, cols, rows, title}`.
- **`term_vt.py`** additions, placed after `upgrade_candidates`:
  ```python
  REMEMBER_EVERY = 15.0        # s between fingerprint checks
  REMEMBER_FULL_EVERY = 60.0   # s between forced recomputes (catches an in-pane /clear relabel)
  _REMEMBER_ON = False         # set only by start_remember (tests stub it: tests/__init__.py)
  _REMEMBER_FH = None          # flock handle on LAST_TERMS_FILE + ".lock", held for the process lifetime
  _REMEMBER_LOCK = threading.Lock()
  _REMEMBERED = None           # list last written by this process
  _SEEN_PREV = set()           # session ids in the previous computed live set
  _LAST_FP, _LAST_FULL = None, 0.0

  def _pane_fingerprint() -> tuple      # under _LOCK: _reap(); sorted (p.id, _fg_pgid(p) if p.folder else p.pid) of live, non-closing panes
  def _entries(rows) -> list            # upgrade_candidates rows -> entries; skip empty target; dedupe on target; newest first; cap 64
  def _debounced(recorded, prev_ids, live) -> list   # pure; B1
  def _terms_record(old, boot, live, now) -> dict    # pure; unchanged from the original plan §4.1
  def remember_terminals(final=False) -> None        # never raises
  def start_remember() -> bool                       # flock + daemon thread "term-remember"; idempotent
  def prior_terminals() -> dict                      # {"saved_at": float|None, "terminals": [...]}
  ```
  - **`upgrade_candidates`:** add one key to each row, `"started": (p.fg or {}).get("started") or p.started`.
  - **`_terms_record(old, boot, live, now)`:**
    - junk (a non-dict) counts as `{}`;
    - if `old.get("boot") == boot`, `prior = old.get("prior") or {}`;
    - otherwise `prior` is `{boot, saved_at, terminals}` taken from `old` when `old["terminals"]` is non-empty,
      else `old.get("prior") or {}`;
    - return `{"boot": boot, "saved_at": now, "terminals": live, "prior": prior}`.
  - **`remember_terminals(final)`:**
    - return at once unless `_REMEMBER_ON`;
    - all of the following runs inside `try/except Exception: pass` and under `_REMEMBER_LOCK`;
    - `now = time.time()`, `fp = _pane_fingerprint()`;
    - if not `final`, `fp == _LAST_FP` and `now - _LAST_FULL < REMEMBER_FULL_EVERY`, return;
    - `live = _entries(upgrade_candidates())`, then `_LAST_FP, _LAST_FULL = fp, now`;
    - `rec = live if final else _debounced(_REMEMBERED or [], _SEEN_PREV, live)`, then `_SEEN_PREV = {e["session"]
      for e in live}`;
    - if `final or rec != _REMEMBERED`: `old = store._load_json(config.LAST_TERMS_FILE, {})`, then
      `store._save_json(config.LAST_TERMS_FILE, _terms_record(old, server._STARTED, rec, now))`, then
      `_REMEMBERED = rec`.
  - **`start_remember()`:**
    - if `_REMEMBER_ON`, return True;
    - `fh = open(config.LAST_TERMS_FILE + ".lock", "a+")`, then `fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)`.
      On `OSError`, close `fh` and return False;
    - set `_REMEMBER_FH = fh` and `_REMEMBER_ON = True`;
    - start the daemon thread `"term-remember"`, which loops `remember_terminals(); time.sleep(REMEMBER_EVERY)`;
    - return True.

    Add `import fcntl`. `term_vt` is POSIX-only (it imports `pty`), so that is safe.
  - **`prior_terminals()`:** read the file.
    - If `boot != server._STARTED`: `terminals` when non-empty, else `prior.terminals`.
    - Otherwise: `prior.terminals`.
    - Return `{"saved_at", "terminals"}`, or `{"saved_at": None, "terminals": []}`.
- **When it is written:**
  - each 15 s tick, but only when the pane fingerprint changed or 60 s have passed, and only if the debounced set
    changed;
  - once, unconditionally and with no debounce, right before Update and restart execs.

  There is **no** SIGTERM / `finally` write. A crash or `make stop` loses at most about 15 s of opens. A removal
  takes effect after two computed ticks.
- **`server.run`:** after `start_worker()`, add `tv = sys.modules.get("aitracker.term_vt")`, then `if tv is not None:
  tv.start_remember()`. Use the literal name, never `__package__` (the bundle asserts on that). Nothing else changes.
- **`update.restart_in_place`:** right before `_cloexec_all()` (`update.py:365`), add
  `tv = sys.modules.get("aitracker.term_vt")`, then
  `if tv is not None: try: tv.remember_terminals(final=True) except Exception: pass`.
- **`tests/__init__.py`:** add the four lines in B2. They redirect `config.LAST_TERMS_FILE` to a `mkdtemp` path and
  stub `term_vt.start_remember` (the original stays as `_real_start_remember`).

### 3. `term_vt.resume_all_plan() -> dict`, next to the code above
- Never raises, and never runs under `_LOCK` (it forks `ps`).
- Returns `{"saved_at", "open": [row], "cannot": [row], "free": int, "max": int}`, where
  `row = {session, title, cwd, opened, cols, rows, reason, command}`.
1. Gather the inputs:
   - `pr = prior_terminals()`;
   - `c = _provider()`;
   - `run = {r["id"]: r for r in c.running_sessions()}` when `c` is set, else `{}`;
   - under `_LOCK`: `_reap()`, then `free = config.MAX_TERMS - _live_count()`.
2. `title = c.session_label(sid)`, or the entry's `title`, or the basename of `cwd`, or `sid[:8]`.
3. Run the checks in order. The first one that fails puts the row in `cannot` with that reason:

   | Check | Reason | `command` |
   |---|---|---|
   | `not _is_claude(sid)` | "only Claude Code sessions can be resumed in a tracker terminal" | `[]` |
   | `_session_pty(sid)` under `_LOCK` | "already open in terminal %s" % tty | `[]` |
   | `run[sid].host == "daemon"` or `_background_target(sid)` | "still running in Claude's background daemon; nothing was lost. Open it from its session row to watch it" | `[]` |
   | `run[sid].host == "desktop"` | "open in the Claude desktop app" | `[]` |
   | `run[sid].host == "tui"` | "running in another terminal outside the tracker (pid %d); resuming it here would run it twice. If you just restarted the tracker, wait a few seconds and press again" | `[]` |
   | `term_gate.resume_argv(sid)` raises `gateway.GatewayError` as e | `str(e)` | `[]` |
   | `not (cwd2 := term_gate.session_cwd(sid, resume=True))` | "its transcript no longer exists" | `[]` |
   | slot cost > `free` | "no free terminal slot (%d of %d in use): close a terminal or raise Max terminals in Config, then press Resume all prior terminals again" | `[shlex.join(resume_argv(sid))]` |

4. **Slot cost**, worked out in list order (newest first) with `cwd2`:
   - 0 when, under `_LOCK`, `fp = _folder_pty(cwd2)` exists, `fp.fg is None`, and no earlier row in this plan
     used `cwd2`;
   - otherwise 1.

   Every row that fits decrements `free`. `open_pty`'s own 429 stays the real cap.
5. Rows that pass every check go to `open`.

### 4. `agent_cli.py` (AU S4 file)
- **Refactor first:** move `agent_cli.py:341-359` into `_agent_launch(agent, action, fn, args) -> (code, body)`, and
  make `agent_start` call it. No behaviour change.
- **New strings:** the original plan §6 set, plus
  `AGENT_RA_NOT_OWNER = "Another tracker started from this folder keeps the terminal record, so this one can't resume prior terminals. Use that tracker, or stop it first."`
  - `AGENT_RA_MESSAGE` reads "… %s open in tracker terminals when the tracker stopped %s ago …";
  - the age comes from `_agent_ra_age(sec)`: `"%d min"` under 1 h, `"%d h"` under 48 h, else `"%d d"`.
- **`agent_plan_resume_all() -> (409, body)`.** Each case returns 409 with the body given:
  - `tv = _agent_tv()` is None → `{"error": AGENT_RA_NO_TERMS}`;
  - `not term_gate.allowed()` → `{"error": AGENT_RA_DISABLED}`;
  - `not tv._REMEMBER_ON` → `{"error": AGENT_RA_NOT_OWNER}`;
  - `agent_job_running()` → `{"error": "an agent job is already running"}`;
  - `_APPLY.locked()` → `{"error": "the tracker is updating itself — try again after it restarts"}`;
  - otherwise build `p = tv.resume_all_plan()` and return `{needs_confirm: True, message, note, saved_at, open,
    cannot}`. When `saved_at` is None, `message` is `AGENT_RA_NONE`. When `open == []`, `AGENT_RA_NONE_OPENABLE` is
    appended.
- **`agent_start_resume_all(confirm)`:**
  - 400 "confirm must be a list of session ids" unless `confirm` is a list of 1 to 64 non-empty `str`;
  - the same NO_TERMS, DISABLED and NOT_OWNER 409s as the preview;
  - then `return _agent_launch("claude", "resume_all", _agent_job_resume_all, (confirm,))`.
- **`_agent_job_resume_all(job, confirm)`:**
  1. `cm = _pending_lock(); got = cm.__enter__()`, with `cm.__exit__` in a `finally`. If `got` is false, call
     `_agent_fail(job, AGENT_RA_FAIL_SCAN)` and return.
  2. `plan = tv.resume_all_plan()`. Each confirmed sid found in `plan["cannot"]` becomes
     `_agent_push(job, _agent_item({...}, "failed", reason))`. Rows in `open` that were not confirmed are skipped.
  3. For each confirmed row in `open`, one at a time:
     - set the step to `AGENT_RA_STEP % (i, n, title)`;
     - `code, obj = tv.call_route(tv.open_pty, {"session": sid, "mode": "resume", "cols": row["cols"], "rows":
       row["rows"]})`, with no `prompt` key;
     - build the item with `_agent_item({"session": sid, "target": sid, "title": title, "command": row["command"]},
       "opened" if code == 200 else "failed", (obj.get("notice") or "") if code == 200 else str(obj.get("error") or
       "HTTP %d" % code))`;
     - on a 200, `item.update(tty_after=obj.get("tty"), forked=bool(obj.get("forked")))`;
     - `_agent_push` the item.

     An exception in one row becomes a `failed` item and the loop continues.
  4. `summary = _agent_ra_summary(job["items"])` (the original §6 format). Then `_agent_set(job, summary=summary,
     state="done")` and `print("ai-tracker: resume all: " + summary, flush=True)`.
- It runs no external command, so it needs no conventions rule-6 exception.

### 5. `server.py`
- In `do_POST`, next to `/api/agents/run`, after the global `_readonly()` deny:
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
- Extend the `from .agent_cli import …` line with the two names.

### 6. UI (Control Room only)
- **`ext_cr_dialogs.js`, `agentWatchJob(id, onDone)`:**
  - add the module variable `_agentJobDone = null`;
  - at entry: `if (onDone) _agentJobDone = onDone; if (_agentJobTimer) return;`;
  - on both stop paths (the job is gone or replaced, or it finished): `var cb = _agentJobDone; _agentJobDone = null;`,
    then the toast as today on the finished path, then `if (cb) cb(j || null);`.
  - Calling it with no `onDone` behaves exactly as before.
- **`renderManageTerminals`:**
  - add closure state outside `paint()`: `var raPlan = null, raBusy = false, raErr = '';`;
  - add `function resumeAllBlock()`. It returns null when `crReadOnly()` or when `!payload.onRefresh`. It renders:
    - with no plan pending: `crBtn('Resume all prior terminals', ask, 'cr-resume-all')`, disabled while `raBusy`,
      plus `raErr` in a `cr-cfg-footer-note`;
    - `ask` sets `raErr = ''` and calls `crCall('/api/terminals/resume-all', 'POST', {})`. A 409 with
      `needs_confirm` sets `raPlan = r.body`; any other reply sets `raErr = r.body.error || 'request failed'`. Then
      `paint()`;
    - with `raPlan` set: `h('div', {class: 'cr-inline-confirm cr-resume-all-confirm', role: 'alertdialog'}, …)`
      holding:
      - `raPlan.message`;
      - one row per `open` entry: `title · cwdTail(cwd) · timeAgo(opened)`;
      - one row per `cannot` entry: `title · reason`, plus each `command` in `<code>`;
      - `raPlan.note`;
      - **Resume these N** (only when `open.length`) and **Cancel** (`raPlan = null; paint()`).
  - Confirming runs `var ids = raPlan.open.map(function (s) { return s.session; }); raPlan = null; raBusy = true;
    paint();` and then POSTs `{confirm: ids}`:
    - 202 → `agentWatchJob(r.body.job.id, function () { raBusy = false; payload.onRefresh(); })`;
    - anything else → `raBusy = false; raErr = r.body.error || 'request failed'; paint()`.
  - Append `resumeAllBlock()` in the empty-state branch before its `return`, and in the list footer before
    `closeAllBtn`. It is not added in the error branch.
- **`ext_cr_term.js`, `_openManageDialog`:** add `onRefresh: _repaintManage` to the payload. `_repaintManage`
  already repaints only while the dialog is the top one (`ext_cr_term.js:899-910`). Leave `_openCapDialog` unchanged,
  so the button stays hidden there.
- No CSS change. Every sentence comes from the server; the JS holds only labels and counts.

### 7. Sequencing (each its own commit; `unset TRACKER_AUTH; make check` green before the next)

| Step | Lands | Tests |
|---|---|---|
| R0 | `tests/__init__.py` isolation lines (B2); `_agent_launch` extraction (S5, no behaviour change) | T3b; existing agent tests |
| R1 | `config.LAST_TERMS_FILE`, `.gitignore`, the `upgrade_candidates` `started` key, the record functions, `server.run` start, `restart_in_place` hook | T1, T2, T2b, T3, T3c, T4 |
| R2 | `resume_all_plan` and its reason texts | T5 |
| R3 | the `agent_cli` resume-all functions and strings | T6, T7 |
| R4 | the `server.py` route | T8 |
| R5 | the UI (`agentWatchJob(id, onDone)`, `resumeAllBlock`, `onRefresh`) | T9 |
| R6 | README line (incl. "plain shells and forked copies are not remembered"), CLAUDE.md app-state line, `_selfcheck` assertion on `_terms_record`; `make bundle` | bundle test |
| R7 | live proof (below), then AU S9's `/branch-sync`, full gate, push | — |

### 8. Tests (new `tests/test_resume_all.py`, unless noted; each proved red by reverting its fix)
- **T1 (S3):**
  - the record comes from `upgrade_candidates()` and uses `target` (relabelled);
  - rows with an empty target are skipped and duplicates collapse;
  - with the fingerprint unchanged and under 60 s, a second call does not call `upgrade_candidates`.
- **T2:** `_terms_record` generations, as in the original T2.
- **T2b (B1):** the `_debounced` sequences in B1.
- **T3:** `remember_terminals(final=True)` with `_REMEMBER_ON = False` writes nothing.
- **T3b (B2):** `config.LAST_TERMS_FILE` is outside the package dir; `server.run` (stubbed) starts no
  `term-remember` thread.
- **T3c (S1):** a second flock is refused, and the preview answers 409 `AGENT_RA_NOT_OWNER`.
- **T4** (in `tests/test_update_restart.py`): `remember_terminals(final=True)` is called before `os.execv`. There is
  no `server.run` finally test.
- **T5:** the plan classification over the nine entries of the original T5, with the exact §3 texts. The slot math
  uses `session_cwd(resume=True)`, not the recorded cwd.
- **T6 (S4):**
  - every `call_route` body has `mode == "resume"` and no `prompt` key;
  - every item's key set equals `_AGENT_ITEM_KEYS`;
  - the outcomes are A opened, B failed with the 429 text, C failed with its reason;
  - the summary is the exact string; `_agent_ra_age` covers its three bands.
- **T7 (S5):** the lock and validation cases, including `confirm = []` → 400, and a busy `_pending_lock` →
  `AGENT_RA_FAIL_SCAN` with zero `call_route` calls.
- **T8** (in `tests/test_agent_routes.py`): non-local → 403; read-only → 403; `{}` → 409 `needs_confirm`;
  `{confirm: [..]}` → 202; a non-dict body → 400.
- **T9** (new `tests/test_resume_all_ui.py`, using the node idiom of `tests/test_cr_manage_terminals_poll.py`):
  - the button shows in the empty state;
  - there is no button without `onRefresh`, and none when `crReadOnly()`;
  - the plan text renders verbatim;
  - the confirm box survives `update({terminals: [...]})`;
  - the confirm POSTs exactly the `open` ids;
  - a double click sends one POST.
- **`_selfcheck`:** one assertion on `_terms_record`'s prior-preservation rule.
- **Live proof (R7), with the user's OK and the safe-scratch protocol:**
  1. Open two scratch sessions through the dashboard on a test port, plus one in Terminal.app.
  2. Stop the test server by PID (never `pkill`) and start it again.
  3. Manage terminals is empty; press the button.
  4. Check that the two show under will-open and the Terminal.app one under can't, with its pid. Confirm: no modal
     opens, two rows appear, and `last_terms.json` holds the new live set with `prior` unchanged.
  5. Tear everything down.

### 9. Risky spots and fallbacks
1. **The record reflects what really ran.** `upgrade_candidates`' foreground filter and pid-file relabel; removals
   are debounced; there is one deterministic final write before exec. Residual: a Claude exited within about 30 s of
   a crash can be listed. The user sees the list and can Cancel.
2. **"Running elsewhere" depends on the procStart-verified pid files.** An old CLI without one can be resumed twice.
   No transcript-recency check, because it would block the main case.
3. **Unwatched panes are idle-reaped after `TERM_IDLE_TTL_MIN`.** That is existing policy; the note says so, and a
   reaped pane leaves the record after two ticks.
4. **A late `--fork-session` retry is reported as "opened".** Known limit, shared with AU.
5. **Same-folder opens are serialized** (one thread, one at a time). The second open overflows, and the slot math
   counts it.
6. **Daemon-hosted sessions are listed, not opened.** This avoids the unwatched-pane swap (`term_vt.py:3307-3311`).

### 10. Decisions for the user
- **(a) What "prior terminals" means.** Recommended: Claude sessions open in tracker terminals when the tracker last
  stopped. Alternatives:
  - (a2) also the sessions whose terminals closed during this run, which needs a closed-history list;
  - (a3) the last N sessions any terminal opened.
- **(b) Where the button goes.** Recommended: the Manage terminals dialog only, in the empty state and the footer,
  not the cap dialog. Alternatives:
  - (b2) also the classic sidebar's Manage terminals. Classic is the default UI; this costs about 50 lines and its
    own poller;
  - (b3) also Config → Update;
  - **(b4)** the literal reading of "alongside the upgrade version button": also put a Claude **Upgrade** button in
    the Manage terminals footer, beside Resume all. About 15 JS lines, no server change.
- **(c) Prompt.** None is sent; the sessions reopen at their input.
- **(d) More sessions than free slots.** Newest first, as many as fit; the rest are listed with a reason and their
  command. The alternative is to refuse the whole batch.
- **(e) Two trackers from one checkout.** Only the first one keeps the record; the other's button explains why (S1).
  The alternative is a record per port, which breaks when `make serve` falls through to the next free port.

## What I did NOT examine
- `Pty.kill`/`finish`, `_inject_argv`, `_deferred_folder_start` and `_resume_backstop` internals beyond their
  docstrings. I trusted the plan's and the docstrings' account of when a resume reports 200.
- Whether Claude Code actually exits on SIGHUP when the masters close, and how long that takes. N6 is based on the
  `PARKED_DETACH_WAIT` comment, not a measurement. The same goes for whether `/clear` mints a new session id. S3's
  repro assumes it, but the relabel fix is right either way, because `/resume <other>` inside a pane certainly does
  change the session.
- macOS shutdown signal ordering. B1's premise is that launchd SIGTERMs every process concurrently; I did not
  measure it.
- `term_gate.guard` with the `_Internal` handler (AU's `call_route`). I assumed AU's own review covered it.
- `test_page_bundle.py`'s exact assertions. S2 rests on `bundle.py:93`'s `assert`.
- The classic UI code beyond locating `openManager`/`renderManagerBody`. Windows, where the term modules are absent.
- AU S1-S8 code correctness in general. I read only the parts this plan reuses.
