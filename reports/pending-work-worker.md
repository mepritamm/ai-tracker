# Pending-work worker — durable plan file

Branch: `worktree-pending-work-worker` (worktree `.claude/worktrees/pending-work-worker`), base `personal/main` @ b3d6230.
Opened 2026-11-15. Status: **planning — no code until the user agrees the plan (CLAUDE.md rule 8).**

## Contract (verbatim)

> I want you to create a job/worker which runs and list all the pending work lying in the worktrees across all different sessions, the time for the worker must be adjusted in '__' days/months and that needs to be managed and controlled by the config setup, if any pending items list up and that piece of information must be displayed right into the main board, in a separate specific card with different color, since thats the intelligence of the app, clicking on that session will show the content which has pending work uncommitted or not pushed into the real code. And it comes up with a resume button which opens up a claude session from which the action can be performed utilise the 'cleanup' skill. and make sure that the worker is smartly deleting all the pending items/tmp files from disk for the sessions that dont need right now. For the deterministic part of the work have some scripts ready into the app, which runs regardless of the local claude session, the claude session only runs when the person really wants to take a look and getting it done

Follow-up: "If I want to implement this, how should I plan this"

## Clauses

| # | Clause | Verdict (code: none yet) | What v3.1 would discharge |
|---|---|---|---|
| C1 | Worker/job lists pending work in worktrees across all sessions | not discharged | v3 plans it: discovery from all transcripts, jobs, tmp and sticky repos; primary/locked work is shown; squash-merged branches are recognised via gh. Gap: first-cwd-only coverage is unmeasured. |
| C2 | Worker interval in days/months, controlled by config | not discharged | v3.1 plans it: `PENDING_INTERVAL` (default `90d`; `2w`/`3m`, …) governs the **whole run** (scan, gh, list, clean) for the thread, the OS job and the CLI. There is no daily refresh; Scan now and `make pending` refresh between runs. Deletion grace is decoupled (fixed 7d). |
| C3 | Pending items shown on main board as a separate, differently-coloured card | not discharged | v3 plans it for **both** views: a Control Room violet tile and a classic-sidebar violet card, from one server `card`. Server only (POSIX). |
| C4 | Clicking shows the uncommitted / unpushed content | not discharged | v3 plans it: live status, diff, unpushed log and gh PR state, in one shared modal. |
| C5 | Resume button opens a Claude session that uses the `cleanup` skill | not discharged | v3 plans it: worktree-cleanup then cleanup, through one shared Resume path (`ExtLaunch.openAt`). It depends on the step-0 proof (M3). |
| C6 | Worker safely deletes stale pending items / tmp files for sessions not needed | not discharged | v3 deletes **only once the user picks Safe delete** (default List only). Squash-merged worktrees are removed with the branch kept. Needs the D4 and D5 rule-6 exceptions. |
| C7 | Deterministic part = scripts in the app, runs without a Claude session; Claude only on demand | not discharged | v3.1 plans it: `pending.py` + CLI + server thread **and** an installed launchd/Task Scheduler job, both deduped by `tick()`; Claude runs only on Resume. The launchd run is proven only post-landing (step 17). The Windows CLI path is planned but untested, not discharged. |
| C8 | First `make serve` auto-installs the scheduler job (R6) | not discharged | Plan addendum A.1, part A: A2 (auto-install), A5 (`/api/scheduler`), A6 ("Scheduled scan" buttons, H4). The live proof (A7) is PARKED (H6). |
| C9 | In-app Update: a Settings section that runs git pull and restarts the dashboard (R6) | not discharged | Plan addendum A.1, part B: A3a, A3b, A5, A6, with the Host gate A8a/A8b (H2). The live proof (A7) is PARKED. |

## Status at end of implementation (main thread, 2026-11-16)

Legend: BUILT+TESTED = implemented, covered by tests proven red-first, and seen working in the live smoke check or the T15 end-to-end eval. NOT PROVEN LIVE = the real action has not been performed on this machine.

| # | Clause | Status |
|---|---|---|
| C1 | Lists pending work in worktrees across all sessions | BUILT+TESTED. Real list-only scan: 479 worktrees/repos, 353 tmp trees; card shows 95 worktrees with unfinished work + 70 stale tmp trees. |
| C2 | Interval in days/months, controlled by config | BUILT+TESTED. `PENDING_INTERVAL` (`7d`/`2w`/`3m`/`off`, default `90d`), Settings row, live-editable. |
| C3 | Separate, differently coloured card on the main board | BUILT+TESTED in both views; seen in a real browser (classic card and violet Control Room tile). |
| C4 | Click shows uncommitted / unpushed content | BUILT+TESTED; seen in a real browser. Largest worktree's detail takes ~3 s (budget 2 s) — parked decision. |
| C5 | Resume opens a Claude session that runs the cleanup skills | BUILT+TESTED at route level (prompt reaches the injected command; worktree-cleanup then cleanup). NOT PROVEN LIVE: the Resume button was never pressed on this machine. |
| C6 | Safely deletes stale items / tmp files | BUILT+TESTED (T15 eval: only the merged idle worktree and a finished session's plain tmp are removed). Default is list-only; Safe delete has NOT been run on the real machine, by design. |
| C7 | Deterministic scripts, Claude only on demand | BUILT+TESTED: `python -m aitracker --pending`, in-server worker, launchd/Task Scheduler installer. NOT PROVEN LIVE: no real launchd job installed (parked for the user). Windows path untested. |
| C8 | First `make serve` auto-installs the scan job; managed by buttons | BUILT+TESTED with stubs. NOT PROVEN LIVE (never installs from a worktree checkout; needs the primary checkout). |
| C9 | In-app Update (pull + restart) from Settings | BUILT+TESTED; restart measured on a throwaway clone (new server up 1.16 s after the request). NOT PROVEN LIVE on a real checkout. Disabled on Windows. |

Evidence: reviews `pending-work-worker-review-E1/E2/E3/F.md`, verdicts in `pending-work-worker-impl-reconciliation.md`, numbers in `pending-work-worker-measurements.md` (9 of 11 measurements pass; M8 item-detail latency and M10 test wall-time fail).

Parked for the user: landing on `personal/main`; installing and proving the launchd job on this Mac; widening the Host/Origin check to every route; trimming the item view to meet 2 s; the added gate time from the new test modules; rotating the GITHUB_PAT that an agent's `launchctl print` exposed in its transcript.

## (superseded) Technical plan (v1)

Author: opus plan leg, 2026-11-15. Every symbol below was checked with grep/sed in this worktree at b3d6230; anything marked **(new)** does not exist yet.

### 1. Shape in one paragraph
One new stdlib module, `aitracker/pending.py`, is the whole deterministic core: **scan** (read-only git + disk inspection) → **classify** (pure) → **clean** (guarded deletion, mode-gated) → **write report** (`pending.json`). It runs three ways, all calling the same `pending.run_once()`: (a) a daemon thread inside the server, (b) `python -m aitracker --pending` / `make pending`, no server or Claude needed, (c) a "Scan now" button that calls `POST /api/pending/run`. The SPA only reads `GET /api/pending` and draws one extra board card in its own colour. Clicking the card opens a list. Clicking an item opens its detail, which the server builds. **Resume** opens a fresh Claude session in that worktree with a prompt the server wrote, using the existing session-less `POST /api/term/pty {cwd, mode:"new"}` plus one new optional `prompt` field. Claude only runs when the user presses Resume (C7).

### 2. Files to add / change (exact)

| File | Change |
|---|---|
| `aitracker/pending.py` **(new)** | The core (signatures in section 3). Imports only `config`, `store` (`_load_json`/`_save_json`), `registry.all_sessions`, plus stdlib `subprocess, os, shutil, fcntl, hashlib, threading, time, json`. It must **not** import `server`, so it has no cycle and the CLI does not need the server. |
| `aitracker/config.py` | Path constants next to `FLAGS_FILE` (:10): `PENDING_FILE = os.path.join(_HERE, "pending.json")`, `PENDING_LOCK = os.path.join(_HERE, "pending.lock")`, `PENDING_LOG = os.path.join(_HERE, "pending.log")`, `SCRATCH_ROOT = "/tmp/claude-%d" % os.getuid()`. Two new EDITABLE keys `PENDING_INTERVAL` and `PENDING_CLEAN`, each added to `EDITABLE` (:207), `VALIDATORS` (:251), `_ENV_NAME`, `_RESOLVERS` (:511), `_PLAIN_ATTR_KEYS` and the module-level seeds (next to `HEADER_LINE = resolve_header_line({})`). **Not** in `RESTART_REQUIRED` (:219), because the thread reads `config.PENDING_INTERVAL` on every tick. Add the pure helpers `_v_interval` and `interval_seconds` (section 4). config.py keeps its "no filesystem" invariant. |
| `aitracker/server.py` | (1) `from . import pending`. (2) do_GET: `elif p.path == "/api/pending"` and `elif p.path == "/api/pending/item"`. (3) do_POST: `if p.path == "/api/pending/run"`, gated by `_local_caller(self)` (:219), 403 otherwise. (4) In `run()` (:911), after `publish_endpoint(actual)`: `pending.start_worker()`. Do **not** add either GET path to `_RO_GET_ALLOW` (:248): worktree paths and diffs must never reach a read-only tunnel viewer. |
| `aitracker/term_vt.py` | In `open_pty` (:2951), `mode == "new"` branch (~:3112), after `argv = [gateway.launcher(...)]`: `p = body.get("prompt"); if isinstance(p, str) and p.strip() and len(p) <= 4000: argv.append(p)`. `_inject_argv` already uses `shlex.join`, so typing it into the folder shell is safe. Update the docstring's body contract with one line. Nothing else changes. |
| `aitracker/cli.py` | In `main()` (:30), before the serve fallthrough: `if "--pending" in sys.argv: from .pending import cli_main; sys.exit(cli_main(sys.argv[1:]))`. Add the HELP line `--pending [--dry-run] [--json]`. |
| `aitracker/web/ext_cr_board.js` | **(new)** `pendingTile(report)` modelled on `agentGroupTile` (:2950). `tileId` (:2599): `t.kind === 'pending' ? 'pending' : …`. `activateTile` (:2661): `if (t.kind === 'pending') return openPendingList();`. `renderBoard` (:2606): when `pendingReport && pendingReport.items.length`, **prepend** the tile ahead of the `tiles.forEach`. It sits outside `boardTiles`, so the cap and filters are untouched. `update()` (:3201) calls **(new)** `maybeFetchPending()`, which fetches `/api/pending` at most every 60s and caches it in the closure as `pendingReport`. Also **(new)** `openPendingList()` / `openPendingItem(id)` (section 6). |
| `aitracker/web/ext_cr_board.css` | `.tracker-next .cr-tile--pending { border-color: var(--state-pending); background: color-mix(in srgb, var(--state-pending) 10%, transparent); grid-column: span 2; }`, next to the `.cr-tile--agentgroup` rules (:1485/:1555). |
| `aitracker/web/ext_cr.css` | `--state-pending: #8A6FD1;` (violet, distinct from all six existing state colours), in **both** token blocks, next to `--state-awaiting` at :135 and :374. |
| `aitracker/web/ext_cr_dialogs.js` | Board tab (`active === 'Board'`, :1314), after the `SNAPSHOT_TTL_MIN` row: `serverRow('Pending-work scan', 'PENDING_INTERVAL', …, textFieldCtl(...trim))` and `serverRow('Pending-work cleanup', 'PENDING_CLEAN', …, segmented([['off','Off'],['dry-run','List only'],['safe','Safe delete']]))`. Add `_ENVCHIP` entries `TRACKER_PENDING_INTERVAL` and `TRACKER_PENDING_CLEAN`. |
| `.gitignore` | `pending.json`, `pending.lock`, `pending.log`. |
| `scripts/bundle.py` | Add `"pending.py"` to `ORDER` (:11), before `"server.py"`. |
| `Makefile` | `pending:` → `@python3 -m aitracker --pending`, and add it to `.PHONY` and `help`. |
| `README.md` | One section: what is scanned, the three modes, what is ever deleted, and the CLI. Mention an *optional* launchd snippet (see D1); do not ship a plist. |
| `tests/test_pending.py` **(new)**, `tests/test_selfcheck.py` | See section 8. |

### 3. `aitracker/pending.py` — signatures

```python
GIT_TIMEOUT = 10                        # s per git call; a timeout => item.error, verdict "unknown" (kept)
SCAN_ENTRY_CAP = 50_000                  # max dirents walked per tmp tree before giving up => "keep"

def run_once(mode=None, now=None) -> dict
    # mode: None -> config.PENDING_CLEAN; "off"|"dry-run"|"safe". Takes PENDING_LOCK with
    # fcntl.flock(LOCK_EX|LOCK_NB). If the lock is busy, returns {"running": True} and does nothing
    # (CLI and thread never overlap). scan -> classify -> clean -> _save_json(PENDING_FILE, report).
def due(report, now, interval_s) -> bool          # pure: interval_s None -> False; no report -> True
def start_worker() -> None                        # idempotent; one daemon threading.Thread
def _worker_loop(sleep=time.sleep, clock=time.time)   # injectable for tests
    # On boot: wait 60s (stays off the startup path). Then forever: if due(load_report(), clock(),
    # config.interval_seconds(config.PENDING_INTERVAL)): run_once(); sleep(min(3600, time to next due)).
    # Catch-up after a stopped server is automatic, because due() reads generated_at from disk.
def load_report() -> dict                          # _load_json(config.PENDING_FILE, {}) normalised
def item_detail(item_id) -> dict | None            # live: {title, when, md, resume:{cwd, prompt}}
def resume_prompt(item) -> str                     # server-owned text (D2)
def cli_main(argv) -> int                          # --dry-run forces mode "dry-run"; --json prints report

# scan (read-only)
def discover_repos(sessions) -> dict[str, list[str]]   # git common dir -> [session ids]
def list_worktrees(common_dir) -> list[dict]           # `git worktree list --porcelain`
def inspect_worktree(wt, base_ref) -> dict
def pick_base(repo) -> str | None   # first existing of refs/remotes/*/develop, */main, */master
                                    # (local refs only; NEVER fetch)
def scan_tmp(sessions, jobs, now, interval_s) -> list[dict]
def _git(cwd, *args) -> (rc, out)   # subprocess.run(["git","--no-optional-locks","-C",cwd,*args],
                                    #   capture_output, text, timeout=GIT_TIMEOUT,
                                    #   env={**os.environ, "GIT_OPTIONAL_LOCKS":"0", "GIT_TERMINAL_PROMPT":"0"})
# classify (pure)
def classify(wt) -> str             # "pending" | "reclaimable" | "missing" | "keep" | "unknown"
# clean (mode-gated)
def clean(report, mode) -> list[dict]   # returns deleted[] entries; appends one line each to PENDING_LOG
```

**Discovery.** `registry.all_sessions()` is the shared seam, so it covers Claude and every Auggie provider. It returns each distinct `cwd`, with the session ids for that cwd. Each cwd maps to its repo: `git -C <cwd> rev-parse --git-common-dir`. If the cwd no longer exists, strip any `/.claude/worktrees/<x>` suffix and retry on the parent. Repos are deduped by common dir. Then `git worktree list --porcelain` on each repo yields **every** worktree (with or without a session) and the `prunable` / `locked` markers. On top of that, `~/.claude/jobs/*/state.json` `worktreePath` / `worktreeBranch` add job-to-worktree links (`config.JOBS_DIR`, :71).

**Report item (the shared shape the SPA renders):**
```json
{"id": "<sha1(path)[:12]>", "kind": "worktree", "path": "...", "repo": "...", "branch": "qa",
 "base": "origin/qa", "upstream": "origin/qa", "dirty": 3, "untracked": 1, "files": ["M a.py", "..."],
 "ahead": 21, "behind": 0, "ancestor": false, "locked": false, "missing": false,
 "sessions": ["<sid>", "..."], "last_activity": 1763190000, "verdict": "pending",
 "label": "3 uncommitted · 21 unpushed", "reclaimable": false, "error": null}
```
Tmp entries use `"kind": "scratch"` with `path, session, bytes, age_s, verdict ("stale" | "keep"), reason`. Top level: `{generated_at, interval, mode, duration_s, items[], tmp[], deleted[], errors[], next_due}`. `label` and `verdict` are server-owned (conventions rule 5), so the JS never re-derives them.

**inspect_worktree commands** (all read-only, no network):
- `status --porcelain=v1 -z --untracked-files=normal` gives `dirty`, `untracked` and the first 50 `files`.
- `rev-parse --abbrev-ref --symbolic-full-name @{u}` gives `upstream`. If it exists, `rev-list --left-right --count @{u}...HEAD` gives behind / ahead. If not, `rev-list --count <base>..HEAD`.
- `merge-base --is-ancestor HEAD <base>` gives `ancestor`.
- `--no-optional-locks` stops `status` from rewriting `.git/index` in someone else's live worktree.
- "Unpushed" is measured against the **last-fetched** remote refs. The label says "as of last fetch".

**classify:**
- `missing` if the dir is gone (porcelain `prunable`).
- `keep` if `locked`, or it is the primary checkout (first porcelain entry), or `realpath` contains this tracker's own `_HERE`.
- `reclaimable` if `ancestor and ahead == 0 and dirty == 0 and untracked == 0` (the worktree-cleanup skill's triple test, verbatim).
- `pending` if `dirty or untracked or ahead > 0`.
- `unknown` on any git error or timeout (treated as keep).

### 4. Interval config — parser and validator (C2)
In `config.py`:
```python
_INTERVAL_RE = re.compile(r"^\s*(\d{1,3})\s*(d|w|mo|m)\s*$", re.I)    # m == mo == MONTH (30d), never minutes
_UNIT_S = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400, "mo": 30 * 86400}
def interval_seconds(s):          # "7d"->604800, "2w"->1209600, "1m"/"1mo"->2592000, "off"/"0"->None
def _v_interval(v):               # str only; "off" or "0" -> (True,"off"); match -> (True, "<n><unit>")
                                  # normalised lower-case, no spaces; 1d <= value <= 12 months else (False, None)
VALIDATORS["PENDING_INTERVAL"] = _v_interval
VALIDATORS["PENDING_CLEAN"]    = _v_enum(("off", "dry-run", "safe"))
def resolve_pending_interval(o):  # config.json > env TRACKER_PENDING_INTERVAL (run through _v_interval) > "7d"
def resolve_pending_clean(o):     # config.json > env TRACKER_PENDING_CLEAN > "dry-run"   (see D3)
```
Rejected inputs: `7` (no unit), `1y`, `-1d`, `1.5d`, `13m`, `True`, `""`. `POST /api/config` already returns 400 through `VALIDATORS` (server.py:597-601), so no new server code is needed for validation. `"off"` turns the thread off. The CLI and "Scan now" still work.

### 5. Deletion — the risky spot, and its fallback (C6)
**The unattended path never deletes anything unless all of these hold:**
1. **Mode.** `config.PENDING_CLEAN == "safe"`. In `dry-run` mode the full `deleted[]` list is computed as `would_delete[]` and nothing is touched.
2. **Worktrees.** Only a `reclaimable` item, re-inspected **immediately before** removal (TOCTOU), with no session in `LIVE_SESSIONS_DIR` (config :73) whose pid is alive. Removal is `git -C <repo> worktree remove <path>`, **never `--force`**, then `git -C <repo> branch -d <branch>`, **never `-D`**. A git refusal is the KEEP signal: log it and move on, no retry. `missing` items get `git -C <repo> worktree prune`, which drops admin metadata only; the branch survives. `ahead > 0` is never deleted, because squash-merge detection needs `gh`, which is network and not allowed here. Those items are listed with "may be squash-merged — Resume to check".
3. **Scratch / tmp.** Only `SCRATCH_ROOT/<slug>/<sid>/` and `JOBS_DIR/<id>/tmp/`, and only when all of these hold:
   - the job's `state` is in {`done`, `failed`, `stopped`} (**blocked = waiting on the user, kept**), or there is no job and no transcript newer than `interval_s`;
   - the newest mtime under the tree is older than `interval_s`;
   - no live pid;
   - `os.walk` (with `followlinks=False`) finds **no `.git` file or dir anywhere** (jobs/84ee6941/tmp/ctrl is exactly this case);
   - the walk finished under `SCAN_ENTRY_CAP`;
   - `os.path.realpath(path)` starts with one of the two allowed roots;
   - it is not a symlink.

   Removal is `shutil.rmtree`. Anything else is listed with its `reason`. `~/.claude/tasks`, `file-history` and transcripts are **never** touched (conventions rule 6: read-only for session logs).
4. **Audit.** Every deletion and every refusal goes as one line to `PENDING_LOG` and into the report's `deleted[]`.

**Fallback.** The default is `dry-run`, so the first release only *lists* deletions until the user flips the Settings segment to "Safe delete". Every guard fails closed: an error or timeout means keep. One misclassified item costs one Resume, never data.

### 6. Board card, click-through and Resume (C3, C4, C5)
- **Card** (`pendingTile`). It shows only when `items` has any `pending`/`missing` entry, or `tmp` has any `stale` entry. It uses class `cr-tile cr-tile--pending` and `tileBaseAttrs({kind:'pending'})`. Title: `Pending work · N worktrees`. Line: `report.summary`, server-built (e.g. "4 uncommitted, 2 unpushed, 1.2 GB reclaimable · scanned 3h ago"). It always comes first and does not count toward the cap.
- **List.** `openPendingList()` calls `openText('Pending work', when, '')` (app.js:2271) and then fills `#msgbody` with one `h()` row per item: `item.label`, `item.path`, `item.branch`. The modal resets `#msgbody` on every `openText`, so no stale DOM survives. A "Scan now" button in the body calls `POST /api/pending/run`. The same precedent exists: the cost modal at app.js:2305 reuses `openText`.
- **Item.** `openPendingItem(id)` calls `GET /api/pending/item?id=` → `{title, when, md, resume}`. The `md` is server-built and computed **live**: `git status --short`, `git diff --stat` (capped at 200 lines), and `git log --oneline <base>..HEAD` (capped at 50). It is rendered with `openText(title, when, md)`, and then a **Resume** button and a **Copy prompt** button are prepended into `#msgbody`.
- **Resume.** `post('/api/term/pty', {cwd: resume.cwd, cols:100, rows:30, mode:'new', prompt: resume.prompt})`, using the same call shape and 429/403 handling as `_pickDirectory` (ext_cr_term.js:625). The cleanest way is a **(new)** `window.CR.term.openAt(path, mode, prompt)` that wraps `_pickDirectory`. For a `missing` item, `resume.cwd` is the repo root.
- **Routes.** `GET /api/pending` returns `load_report()` plus `next_due`. `GET /api/pending/item?id=` returns 404 for an unknown id. `POST /api/pending/run {dry_run?}` refuses non-local callers with 403, starts `run_once` in a daemon thread, and returns `{started: true}` or `{running: true}`.

### 7. Sequencing (what lands first and why)
1. **config keys + `interval_seconds` / `_v_interval` + tests.** These are pure, everything reads them, and a bad parser is the cheapest thing to catch first.
2. **`pending.py` scan + classify + `cli_main` (dry-run only) + temp-git tests.** This is the deterministic core and C7 on its own; it is useful before any UI exists.
3. **`clean()` + its tests**, still default `dry-run`. Kept as a separate step so the risky code gets its own review pass.
4. **server routes + `start_worker()` in `run()` + route tests.**
5. **`open_pty` `prompt` field + test.** This is one small change in a 4.9k-line file, isolated on purpose.
6. **SPA**: CSS token → card → list/item modal → Resume → Settings rows. Run `node --check` on every touched `web/*.js` (memory: the gate misses load-time JS/CSS errors). Then `make serve` on a spare port and check by hand.
7. **README, bundle ORDER, Makefile, .gitignore.** Then `/branch-sync`, the gate, and push to `personal`.

### 8. Tests — `tests/test_pending.py` (skip if `shutil.which("git")` is None)
Fixture: a `tempfile.mkdtemp()` with a bare `remote.git` and a `repo`.
- Set up the repo: `git -c user.name=t -c user.email=t@t init -b main`, commit, add `origin`, push.
- Create four worktrees:
  - **A** branch merged into `origin/main` → `reclaimable`;
  - **B** with an uncommitted edit → `pending`, dirty 1;
  - **C** with a local commit not pushed → `pending`, ahead 1;
  - **D** created then `rm -rf`'d → `missing`.
- Patch `config.PENDING_FILE` / `PENDING_LOG` / `JOBS_DIR` / `SCRATCH_ROOT` / `LIVE_SESSIONS_DIR` to temp paths. config is late-bound, so this works.

Assertions:
1. Interval parser: the accepted / rejected tables from section 4. `due()` boundaries.
2. `classify` verdicts for A–D, plus `locked` → keep and primary checkout → keep.
3. `run_once("dry-run")` deletes nothing, and `would_delete` has A + D-prune.
4. `run_once("safe")`: A is gone (`git worktree list` no longer shows it, branch deleted), D is pruned, **B and C still exist byte-for-byte**.
5. Scratch:
   - a `done` job older than the interval → removed;
   - the same tree with a nested `.git` → kept, reason `"contains .git"`;
   - a `blocked` job → kept;
   - a symlink → kept;
   - a path outside the allowed roots → kept.
6. Lock: a second `run_once` while the lock is held → `{"running": True}`.
7. Routes:
   - `GET /api/pending` serves the temp report;
   - `POST /api/pending/run` from a non-loopback `client_address` → 403;
   - `/api/pending` is absent from `_RO_GET_ALLOW`.
8. `open_pty` `mode:"new"` with `prompt` → the argv ends with the prompt. Without it, the argv is unchanged.

**Plus one assertion in `tests/test_selfcheck.py`** (conventions rule 9): `PENDING_INTERVAL` and `PENDING_CLEAN` are in `EDITABLE` and not in `RESTART_REQUIRED`, and `interval_seconds("1m") == 2592000`. Red-proof: revert `classify`'s `ahead == 0` term, and assertion 4 must fail because C gets deleted.

### 9. Decisions for the user (recommendation first)
- **D1 Scheduler: in-server daemon thread + CLI. No launchd shipped.** The thread covers "runs regardless of a Claude session". `due()` reads `generated_at` from disk, so a stopped server catches up on its next start, and a days/months cadence never needs a second always-on process. The CLI (`make pending`) is the "script in the app" and works with the server down. A launchd agent is only a README snippet calling the CLI, because it would add an always-on process plus plist install/uninstall to a zero-dependency app for a job that runs weekly.
- **D2 Resume prompt: `worktree-cleanup` first, then `cleanup`.** `cleanup` explicitly forbids git and excludes worktrees, so on its own it cannot act on the very items the card shows. The server-built prompt: *"Use the worktree-cleanup skill on `<path>` (repo `<repo>`, branch `<branch>`; N uncommitted, M unpushed as of last fetch). Commit/push or discard as I decide, ask me before anything destructive. Then use the cleanup skill for stray processes and scratch files of session(s) `<sids>`."* This does not satisfy the contract word `cleanup` literally; overrule it if you want `cleanup` alone.
- **D3 Auto-delete scope: default `dry-run`.** `safe` deletes only: worktrees passing ancestor ∧ ahead=0 ∧ clean, via non-force `worktree remove` + `branch -d`; `worktree prune` for missing dirs; and scratch/jobs-tmp trees of done/failed/stopped, non-live sessions older than one interval that hold no `.git`. Never deleted: anything dirty, ahead>0 (possible squash-merge), locked, blocked jobs, transcripts, tasks or file-history. **The user may want to overrule two things:** whether `safe` should be the default (C6 reads as "delete"), and whether stale `file-history` (16M) should be in scope.

### 10. Known gaps (stated, not solved)
- Without `gh`, "unpushed" is judged only against last-fetched refs, and squash-merges look pending.
- The OpenRouter launcher must forward `"$@"` for the Resume prompt to arrive. If it does not, the Copy-prompt button is the fallback.
- One card for all items. A card per worktree is a one-line change in `renderBoard` if you want it instead.

## User decisions (2026-11-15, via AskUserQuestion — these override v2 where they differ)

| # | Question | User's answer (verbatim where free-text) | Differs from v2? |
|---|---|---|---|
| U1 | Scheduling | "2 and launchd job for mac, something similar for windows as well" — i.e. server thread + CLI, PLUS a shipped launchd job on macOS and an equivalent on Windows | **yes** (v2: README snippet only) |
| U2 | Resume skill | worktree-cleanup, then cleanup | no |
| U3 | Auto-delete default | List only by default; Safe delete is opt-in | no |
| U4 | Rule-6 exception for Claude tmp folders | Yes, narrow exception | no |
| U5 | Card layout | One card for everything | no |
| U6 | Views | **Both views** (Control Room board AND classic) | **yes** (v2: Control Room only) |
| U7 | Squash-merges | **Call gh during the scan** | **yes** (v2: no network). Needs a second written exception in conventions.md (rule 6 "no outbound network") |
| U8 | Default interval | "90 days / 3 months" | **yes** (v2: 7d). Note: v2 has grace = max(interval, 7d); with 90d that makes deletion grace 90d — planner to decouple or justify |

## User decisions, round 2 (2026-11-15)

| # | Question | User's answer |
|---|---|---|
| R1 | Sign-off on v3.1 | "Approved, continue". |
| R2 | Code written before sign-off | Keep it; all of it goes through the opus implementation review. |
| R3 | Gap skill | `/tracker-gap` for all remaining changes; written code covered by the implementation review. |
| R4 | Landing | Push the branch AND land on main via `/tracker-push` once the gate is green. |
| R5 | Windows | Ship untested, labelled in README. |
| R6 | launchd on this Mac | (verbatim) "2 and make serve on the first time, should always generate the launchd job when running for the first time also, have a separate update section right into the app from the config, which runs git pull and runs the dashboard is important such that someone doesnt have to refresh the dashboard everytime from the cli by stopping the current session and starting it again" — i.e. install and prove the job on this Mac; first `make serve` auto-installs it; plus a new in-app Update feature. |
| R7 | Real scan | One list-only run on the real machine, with gh, allowed. |
| R8 | OpenRouter | Resume always shows a Copy-prompt button as fallback. |

## User decisions, round 3 (2026-11-15, head-out)

| # | Question | User's answer |
|---|---|---|
| H1 | Addendum A.1 | "Approve both" (auto-install + in-app update). |
| H2 | Host check | Fix ALL local-only routes, including the existing terminal routes (supersedes AD6; it is now in scope). |
| H3 | Open terminals on Update | Confirm, then close them. |
| H4 | Auto-install | (verbatim) "1 but everything happens with a button click instead of make command, the only command the user runs is first time with a make serve and then rest is managed by the app itself" — i.e. install when missing and respect an opt-out, AND install / uninstall / reinstall are buttons in Settings (the opt-out is recorded by the Uninstall button; `make pending-install`/`-uninstall` may remain as thin aliases but are not the user's path). This REVERSES review D's F9 cut of the route and button: restore a local-only status + action route and a Settings "Scheduled scan" block (status, Install/Reinstall, Uninstall). |
| H5 | Landing | (verbatim) "test it throughly and review + plan if it affects any non-functional activities of the app, such as the slowneess, sync-ness, speed, slows the app and other aspects do a thorough review on those aspects as well" — not an authorisation to land; landing on main is PARKED for the user. |
| H6 | launchd proof on this Mac | Wait for the user (PARKED). |
| H7 | Flaky gate | Agents may fix the timing-sensitive tests that keep failing. |
| H8 | Tests | (verbatim) "update evals/tests and add new ones as well". |

## (superseded) Technical plan (v2)

Author: opus plan leg, 2026-11-15. v2 = v1 + every confirmed/plausible row of the Reconciliation table below (applied **as trimmed**) + M1–M3. It is self-contained: an implementer reads only this section. Symbols were checked by grep/sed at b3d6230. **(new)** marks things that do not exist yet. Finding ids in brackets, e.g. [A-B3], point to the reviews.

### 1. Shape in one paragraph
One new stdlib module, `aitracker/pending.py`, is the deterministic core: **discover** repos → **inspect** worktrees and tmp trees (read-only git and disk) → **classify** (pure; a display `verdict`, kept separate from `deletable`) → **clean** (mode-gated, fail-closed) → **write report** (`pending.json`).

It runs three ways, all through `run_once()`:
- (a) a daemon thread in the server, on the configured `PENDING_INTERVAL`, in the configured `PENDING_CLEAN` mode;
- (b) the CLI `python -m aitracker --pending` / `make pending`, with no server and no Claude needed;
- (c) a **"Scan now"** button. It is always `dry-run`, never deletes, and returns at once with 202 [B-S8, M1].

The SPA only receives `GET /api/pending` through the boot poll hook and draws one server-described card in its own colour [B-S2, B-S6]. Clicking the card opens a list. Clicking an item opens a server-built detail. **Resume** opens a fresh Claude session at the repo's **primary checkout**, not inside the worktree [B-S10]. It uses the existing session-less `POST /api/term/pty {cwd, mode:"new"}` plus one new optional `prompt` field. Claude only runs when the user presses Resume (C7).

### 2. Files to add / change (exact)

| File | Change |
|---|---|
| `aitracker/pending.py` **(new)** | The core (section 3). Imports are **named and top-level** so the bundler can flatten them [B-B1]: `from . import config`, `from .store import _load_json, _save_json`, `from .registry import all_cwds`, `from .providers.claude import _pid_alive` (claude.py:562) [A-N4], plus stdlib `subprocess, os, re, shutil, fcntl, hashlib, threading, time, json, glob`. Never write `store.X` / `registry.X` attribute access, and never import `server`. |
| `aitracker/registry.py` | **(new)** `all_cwds() -> set[str]`: for each available provider in `PROVIDERS`, `p.cwds()` if it defines one, else `{r["cwd"] for r in p.list() if r.get("cwd")}`. This is the shared seam (conventions rule 3); `list_sessions` is unchanged [A-B1 trimmed]. |
| `aitracker/providers/claude.py` | **(new)** `ClaudeProvider.cwds()`: `{_session_meta(f)["cwd"] for f in glob(config.PROJECTS/*/*.jsonl)} - {""}`. This is the **first cwd of every transcript, with no 200 limit** [A-B1/B-S11 trimmed]. `_session_meta` is already mtime-cached (claude.py:247). |
| `aitracker/config.py` | `import re` [A-N1/B-N2]. Path constants next to `FLAGS_FILE` (:10): `PENDING_FILE = os.path.join(_HERE, "pending.json")`, `PENDING_LOG = os.path.join(_HERE, "pending.log")`, **per-user** `PENDING_LOCK = "/tmp/ai-tracker-pending-%d.lock" % os.getuid()` [A-S7], `SCRATCH_ROOT = "/tmp/claude-%d" % os.getuid()`. Two EDITABLE keys, `PENDING_INTERVAL` and `PENDING_CLEAN`, each added to `EDITABLE` (:207), `VALIDATORS` (:251), `_ENV_NAME` (cosmetic, [B-N9]), `_RESOLVERS` (:511), `_PLAIN_ATTR_KEYS` and the module-level seeds. **Not** in `RESTART_REQUIRED`. Pure helpers `_v_interval`, `interval_seconds` (section 4). config.py stays filesystem-free. |
| `aitracker/server.py` | Top-level `from .pending import start_worker, load_report, item_detail, run_async` [B-B1]. do_GET: `/api/pending`, `/api/pending/item`. do_POST: `/api/pending/run`. In the `/api/config` branch, after the validator (≈:601): `if key == "PENDING_CLEAN" and coerced == "safe": ok, err = _local_caller(self); if not ok: return self._json({"error": "safe delete can only be enabled from this machine"}, 403)` [B-S12, B-N1]. In `run()` (:911), after `publish_endpoint(actual)`: `start_worker()`. Neither GET path goes into `_RO_GET_ALLOW` (:248). |
| `aitracker/term_vt.py` | `open_pty` (:2951), `mode == "new"` branch (~:3112), after `argv = [gateway.launcher(...)]`: `p = body.get("prompt"); if isinstance(p, str) and p.strip() and len(p) <= 4000 and not p.lstrip().startswith("-"): argv.append(p)` [B-N3]. One docstring line. A positional prompt reaches claude on all three `new` paths: `_inject_argv`/`shlex.join` :1953, `_deferred_folder_start` :3615, and overflow `spawn` :3306. Whether claude then stays **interactive** is proven first, in section 7 step 0 [M3]. |
| `aitracker/cli.py` | Top-level `from .pending import cli_main` (next to `from .server import run`, :6) [B-B1]. In `main()`, after `--help` and before serve: `if "--pending" in sys.argv: sys.exit(cli_main(sys.argv[1:]))` [B-N13]. HELP line: `--pending [--dry-run] [--json] [--if-due]`. |
| `aitracker/web/ext_cr_boot.js` | In the `SIDE_EXT.push` hook (:997–1004): if `!ctx.readOnly()` and either 60s have passed since the last fetch or `pendingDirty` is set, `fetch('/api/pending')` → `pendingCache` (ignore non-OK). Pass `board.update({sessions: list, now: now, pending: pendingCache})` [B-S6]. While `pendingCache.running` is true, refetch every 5s poll. |
| `aitracker/web/ext_cr_board.js` | **(new)** `pendingTile(p)` modelled on `agentGroupTile` (:2950), class `'cr-tile cr-tile--pending cr-tile--span2'` [B-S5]. It renders only `if (p && p.card && p.card.show && !activeFilter)`. `renderBoard` (:2606) prepends it before `tiles.forEach` and skips the empty copy when it is shown [B-N6]. `tileId` (:2599): `'pending'` for kind pending. `activateTile` (:2661): `if (t.kind === 'pending') return openPendingList(lastState.pending);`. **`t` key fix (:3091):** `var t = tiles.filter(function (x) { return tileId(x) === focusedTileId; })[0];` [B-S4]. **(new)** `openPendingList(p)` / `openPendingItem(id)` (section 6). The board makes no fetch other than the item detail and Resume, both on click. |
| `aitracker/web/ext_cr_term.js` | **(new)** `window.CR.term.openAt(path, mode, prompt)`, a thin wrapper of `_pickDirectory` (:625) that threads `prompt` into the POST body **and** into the 429-retry closure (:640) [B-N4]. |
| `aitracker/web/ext_cr_board.css` | `.tracker-next .cr-tile--pending { border-color: var(--line-pending); background: var(--surface-pending); }` next to :1484–1489. No `grid-column` (span2 utility) and no `color-mix` [B-S5]. |
| `aitracker/web/ext_cr.css` | `--state-pending`, `--surface-pending`, `--line-pending` in **both** theme blocks, next to `--surface-awaiting` (:71/:325), `--state-awaiting` (:135/:374) and `--line-awaiting` (:112/:364). Violet family: light `#8A6FD1` / `#F1ECFB` / `#C3B3EC`, dark `#A48BE6` / `#2A2340` / `#6E58B8`. |
| `aitracker/web/ext_cr_dialogs.js` | Board tab (`active === 'Board'`, :1314), after the `SNAPSHOT_TTL_MIN` row:<br>• `serverRow('Pending-work scan', 'PENDING_INTERVAL', 'How often the worker scans worktrees: e.g. 7d, 2w, 1m (m = month). "off" stops the schedule. A change applies within an hour.', textFieldCtl(...trim))` [B-N8]<br>• `serverRow('Pending-work cleanup', 'PENDING_CLEAN', …, segmented([['off','Off'],['dry-run','List only'],['safe','Safe delete']]))`<br>`_ENVCHIP` entries `TRACKER_PENDING_INTERVAL` and `TRACKER_PENDING_CLEAN`. |
| `.claude/rules/conventions.md` | Rule 6 gains the written exception [M2], wording in D4. |
| `.gitignore` | `pending.json`, `pending.log`. |
| `scripts/bundle.py` | `"pending.py"` in `ORDER` (:11) **after `registry.py`**, before `server.py` [B-B1]. No regex changes. |
| `Makefile` | `pending:` → `@python3 -m aitracker --pending`, plus `.PHONY` and `help`. |
| `README.md` | What is scanned, the three modes, the exact delete rules (section 5), the CLI, an optional launchd snippet calling `--pending --if-due`, and "run spare-port test servers with `TRACKER_PENDING_INTERVAL=off`" [B-N12]. |
| tests | `tests/test_pending.py` **(new)**, one assertion in `tests/test_selfcheck.py`, additions to `tests/test_integration.py::TestBundle` and `tests/test_page_css.py` (section 8). |

### 3. `aitracker/pending.py` — signatures and logic

```python
GIT_TIMEOUT = 10                 # s per git call; timeout -> verdict "unknown", deletable False
SCAN_ENTRY_CAP = 50_000          # dirents per tmp tree; exceeded -> keep
PENDING_GRACE_FLOOR = 7 * 86400  # grace = max(interval_s, floor)   [A-S6]
_RUNNING = threading.Event()     # set while an in-process run is active

def run_once(mode=None, now=None, scheduled=False) -> dict
    # mode None -> config.PENDING_CLEAN. fcntl.flock(PENDING_LOCK, LOCK_EX|LOCK_NB); busy -> {"running": True}.
    # discover -> inspect -> classify -> clean(mode) -> report. report["scheduled_at"] = now ONLY when
    # scheduled and mode == config.PENDING_CLEAN; otherwise the previous scheduled_at is carried forward [B-S8].
    # _save_json(PENDING_FILE, report).
def run_async(mode="dry-run") -> bool          # [M1] daemon thread -> run_once(mode); False if already _RUNNING
def due(report, now, interval_s) -> bool       # pure; reads report["scheduled_at"]; interval None -> False; none -> True
def start_worker() -> None                     # idempotent daemon thread; no-op when PENDING_INTERVAL is "off"
def _worker_loop(sleep=time.sleep, clock=time.time, once=None)   # `once` is the test hook
    # sleep(60) at boot, then forever:
    #   try: if due(...): run_once(scheduled=True)
    #   except Exception as e: _log("worker error", e)                         [B-S7]
    #   next_due = (load_report().get("scheduled_at") or clock()) + (interval_s or 3600)
    #   sleep(max(60, min(3600, next_due - clock())))
def load_report() -> dict    # _load_json(PENDING_FILE, {}), normalised; adds "running" (_RUNNING or lock busy)
                             # and recomputes card while running (summary "scanning…")
def item_detail(item_id) -> dict | None   # live: {title, when, md, resume: {cwd, prompt}}
def resume_prompt(item) -> str            # server-owned, per kind (section 6 / D2)
def cli_main(argv) -> int
    # FIRST LINE: config.apply_overrides(_load_json(config.CONFIG_FILE, {}))           [B-S1]
    # --if-due: return 0 unless due(load_report(), time.time(), interval_seconds(config.PENDING_INTERVAL))
    # --dry-run forces "dry-run"; scheduled=True only when neither --dry-run is given nor the mode is overridden
    # --json prints the report

# discover / inspect (read-only, never fetch, never network)
def discover_repos(now) -> dict[str, dict]     # abs realpath common dir -> {"top": primary path, "cwds": [...]}
def list_worktrees(repo) -> list[dict]         # `git -C <top> worktree list --porcelain`
def inspect_worktree(wt, repo, ctx) -> dict
def scan_tmp(ctx, now, grace) -> (list[dict], list[str])   # tmp entries, git_roots
def _under(path, root, depth=None) -> bool     # realpath vs realpath via commonpath; exact rel depth [A-S4]
def _git(cwd, *args) -> (rc, out)   # ["git","--no-optional-locks","-C",cwd,*args], capture_output,
                                    # text, timeout=GIT_TIMEOUT, env + GIT_OPTIONAL_LOCKS=0,
                                    # GIT_TERMINAL_PROMPT=0
# classify (pure) / clean
def classify(wt, ctx, now, grace) -> dict      # {"verdict", "deletable", "reason"}
def clean(report, mode, ctx, now, grace) -> list[dict]   # deleted / would_delete / refused entries; PENDING_LOG line each
```

**Discovery** [A-B1/B-S11 trimmed, A-B2, A-S5]. Repos only need finding once, because `git worktree list` on a repo enumerates **all** of its worktrees. The seed set is the union of four sources:
1. `registry.all_cwds()` (the first cwd of every transcript, no limit; plus every other provider's cwds);
2. `cwd`, `originCwd` and `worktreePath` of every `config.JOBS_DIR/*/state.json`;
3. the `git_roots` found by `scan_tmp`;
4. the sticky `repos[]` saved in the previous `pending.json`. An entry is dropped only when its common dir no longer exists.

For each seed:
- A seed that no longer exists walks up to its nearest existing ancestor.
- It is then resolved with `_git(seed, "rev-parse", "--path-format=absolute", "--git-common-dir")` and `os.path.realpath`. Non-repos are skipped.
- Repos are deduped by that absolute key. `top` = the first `worktree` line of `worktree list --porcelain`, the primary checkout.

**ctx** (built once per run):
- `jobs`: a list of `(realpath(worktreePath or cwd), state)` from every `state.json`;
- `live`: the realpath cwds from `config.LIVE_SESSIONS_DIR/*.json` whose `_pid_alive(pid)` is true;
- `tx`: a `{realpath cwd: newest transcript mtime}` map from the same transcript glob.

LIVE_SESSIONS_DIR is a **guard input only**, not a discovery seed [A-B1 trimmed].

**inspect_worktree.** All commands are read-only.
- `status --porcelain=v1 -z --untracked-files=normal` gives `dirty`, `untracked` and the first 50 `files`.
- `status --porcelain=v1 -z --ignored=matching --untracked-files=no` gives the `!!` entries: `ignored` (count) and `ignored_files` (first 20). There is **no regenerable allowlist** [A-B4 trimmed].
- `unpushed = rev-list --count HEAD --not --remotes` is **the** "not pushed" measure [A-S1]. It works offline and does not depend on the upstream.
- `upstream`, `ahead` and `behind` come from `@{u}` and are for display only.
- `base` = the first existing of `refs/remotes/*/develop`, `*/main`, `*/master` (local refs, no fetch). `ancestor = merge-base --is-ancestor HEAD <base>`.
- `last_activity` = the max of: the mtimes of `<common>/worktrees/<name>/{HEAD,index,logs/HEAD}`, the worktree top-dir mtime, and `ctx.tx` entries under the path [A-B3].
- For `prunable` entries (dir missing), take the porcelain `HEAD <sha>` and record:
  - `contained` = `for-each-ref --contains <sha> --count=1` is non-empty [A-S3];
  - `unpushed` = `rev-list --count <sha> --not --remotes`.

**Report item (the shared shape the SPA renders):**
```json
{"id": "<sha1(realpath)[:12]>", "kind": "worktree|repo", "path": "...", "repo": "<common>", "top": "<primary>",
 "branch": "qa", "detached": false, "base": "origin/develop", "upstream": "origin/qa",
 "dirty": 3, "untracked": 1, "ignored": 1, "files": ["M a.py"], "ignored_files": [".env"],
 "unpushed": 21, "ahead": 21, "behind": 0, "ancestor": false, "locked": false, "primary": false,
 "missing": false, "contained": true, "last_activity": 1763190000,
 "verdict": "pending", "deletable": false, "reason": "3 uncommitted",
 "label": "3 uncommitted · 21 unpushed (as of last fetch)", "error": null}
```
- Tmp entries: `{"kind": "scratch", "path", "session", "job", "bytes", "age_s", "verdict": "stale"|"keep", "deletable", "reason"}`.
- Top level: `{generated_at, scheduled_at, interval, mode, duration_s, repos[], items[], tmp[], deleted[], would_delete[], refused[], errors[], running, card: {show, title, summary, count}}` [B-S2].
- `card.count` = items with `verdict in {pending, missing}` plus tmp entries with `verdict == "stale"`, and `show = count > 0`. `summary` is server-built, e.g. "4 uncommitted · 2 unpushed · 1.2 GB reclaimable · scanned 3h ago".
- The JS never derives a threshold, verdict or label (conventions rule 5).

**classify** returns a display verdict plus `deletable` [A-S2/B-S3].

Display verdict, decided in this order:
1. `unknown` on any git error or timeout.
2. `missing` when the dir is gone. The label carries "N orphan commits" for a detached, not-`contained` entry, or "branch has N unpushed".
3. `pending` when `dirty or untracked or unpushed > 0`.
4. Otherwise `clean`, with reason "pushed; not merged into <base>" when not `ancestor`.

Ignored files do **not** make a worktree `pending`, because then nearly every Python worktree (`__pycache__`) would light the card. They only block deletion and appear in the label ("1 ignored local file: .env").

`deletable` is False when any of these hold:
- `primary`, bare or `locked`;
- **own tracker**: `os.path.realpath(config._HERE).startswith(os.path.realpath(path) + os.sep)` (v1's check was inverted, per B's pointer);
- `ignored > 0` [A-B4];
- verdict is `pending`, `missing` or `unknown`.

`reclaimable` (deletable `clean`) additionally requires all of these [A-B3]:
- `ancestor`;
- `unpushed == 0`;
- `now - last_activity >= grace`;
- no `ctx.jobs` entry at or under the path with `state ∉ {done, failed, stopped}`;
- no `ctx.live` cwd at or under the path.

### 4. Interval config — parser and validator (C2)
```python
_INTERVAL_RE = re.compile(r"^\s*(\d{1,3})\s*(d|w|mo|m)\s*$", re.I)   # m == mo == MONTH (30d), never minutes
_UNIT_S = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400, "mo": 30 * 86400}
_INTERVAL_MAX = 366 * 86400                                          # [A-N1]
def interval_seconds(s):   # "7d"->604800, "2w"->1209600, "1m"/"1mo"->2592000, "off"/"0"->None, invalid->None
def _v_interval(v):        # str only (bool/int rejected); "off"/"0" -> (True, "off");
                           # match with 86400 <= secs <= _INTERVAL_MAX -> (True, "<n><unit>" lower-case);
                           # else (False, None)
VALIDATORS["PENDING_INTERVAL"] = _v_interval
VALIDATORS["PENDING_CLEAN"]    = _v_enum(("off", "dry-run", "safe"))
def resolve_pending_interval(o):  # config.json > os.environ["TRACKER_PENDING_INTERVAL"] via _v_interval > "7d"
def resolve_pending_clean(o):     # config.json > os.environ["TRACKER_PENDING_CLEAN"] > "dry-run"
```
The resolvers read `os.environ` themselves, the same way `resolve_snapshot_ttl_min` does [B-N9].

| Accepted | Rejected |
|---|---|
| `7d`, `2w`, `1m`, `1mo`, `12m`, `365d`, `52w`, `off`, `0` | `7`, `1y`, `-1d`, `1.5d`, `13m`, `400d`, `True`, `""` |

`POST /api/config` already returns 400 through `VALIDATORS` (server.py:597–601).

### 5. Deletion — the risky spot, and its fallback (C6)
Nothing is deleted unless **every** condition below holds. Each one fails closed: any error or timeout means keep.

1. **Mode.**
   - Deletion happens only on a run whose mode is `safe`: the scheduled worker with `config.PENDING_CLEAN == "safe"`, or `make pending` in that config.
   - "Scan now" always calls `run_async("dry-run")`, so it never deletes [B-S8].
   - In `dry-run`, the deletions are computed into `would_delete[]` and nothing is touched.
   - `safe` can be **enabled** only by a local caller: `/api/config` returns 403 otherwise [B-S12].
2. **Clean worktrees.** Only `reclaimable` items (section 3: clean ∧ deletable ∧ ancestor ∧ unpushed=0 ∧ ignored=0 ∧ idle ≥ grace ∧ no unfinished job ∧ no live session).
   - Every term is re-inspected **immediately before** removal (TOCTOU).
   - Removal is `git -C <top> worktree remove <path>`, **never `--force`**.
   - Then `git -C <top> branch -d <branch>`, **never `-D`**. This is skipped for a detached HEAD [A-N3], and skipped when the branch's short name equals the base's short name (e.g. `develop`, `qa`) [A-N2].
   - A git refusal is the KEEP signal: log it to `refused[]`, no retry.
   - `ahead > 0` or `unpushed > 0` is never deleted. Squash-merge detection needs `gh` (network), which is not allowed here, so those items are listed as "may be squash-merged — Resume to check".
3. **Missing worktrees** [A-S3 trimmed]. `git -C <top> worktree prune` (no `--expire`) runs **only if every** `prunable` entry in that repo has `contained == True`. If even one detached entry is not contained, the whole repo's prune is skipped and that entry is listed as `missing` "N orphan commits".
4. **Scratch / tmp.** Only `SCRATCH_ROOT/<slug>/<sid>` (exact depth 2) and `JOBS_DIR/<id>/tmp` (exact depth `[id, "tmp"]`), checked with `_under` [A-S4]. All of these must hold:
   - realpath vs realpath via `os.path.commonpath` (`/tmp` → `/private/tmp` on macOS), so `<root>0/x` does not match;
   - not a symlink;
   - the job `state ∈ {done, failed, stopped}` (**blocked is kept**), or there is no job and no transcript newer than `grace`;
   - the newest mtime under the tree is `< now - grace`;
   - no `ctx.live` cwd under it;
   - `os.walk(followlinks=False)` finished under `SCAN_ENTRY_CAP` and found **no `.git` file or dir** [A-S5].

   Removal is `shutil.rmtree`. A tree with a `.git` is never rmtree'd. Its `.git` root goes to discovery instead: a linked worktree flows through rules 2–3, and a standalone repo becomes an item with `kind: "repo"` and `deletable: False`. Once git has removed the worktree, a later run sees no `.git` and the tree qualifies (two-phase).
5. **Never touched.** Transcripts (`*.jsonl`), `state.json`, `~/.claude/tasks`, `file-history`, shell-snapshots (D4 / M2).
6. **grace** = `max(interval_seconds(PENDING_INTERVAL), PENDING_GRACE_FLOOR)` everywhere above [A-S6].
7. **Single cleaner.** The per-user `PENDING_LOCK` means only one cleaner runs per user, across every tracker checkout and the CLI [A-S7].
8. **Audit.** Every delete and refusal goes as one line to `PENDING_LOG`. `deleted[]` covers the last run only.

**Fallback.** The default is `dry-run`, so release 1 only lists deletions until the user picks "Safe delete" locally. If a guard misclassifies, the cost is one Resume, never lost data.

### 6. Board card, click-through and Resume (C3, C4, C5)
- **Feed.** The boot hook fetches `/api/pending` every 60s, or every 5s while it reports `running`, and never in read-only. The result reaches the board as `state.pending` [B-S6].
- **Card.** `pendingTile(p)` renders only when `p.card.show` is true and no triage filter is active.
  - Classes: `cr-tile cr-tile--pending cr-tile--span2`.
  - Title: `p.card.title` ("Pending work · N").
  - Line: `p.card.summary`, which reads "scanning…" while running [M1].
  - It always comes first and does not count toward the cap.
- **List.** `openPendingList(p)`:
  - First `curModal = null` and clear `#msgnav`, so `syncModal()` (app.js:2258) cannot overwrite it [B-S9].
  - Then `openText('Pending work', when, '')` (app.js:2271), then fill `#msgbody` with one `h()` row per item (`item.label`, `item.path`, `item.branch`).
  - A **Scan now** button calls `POST /api/pending/run` and sets the boot hook's `pendingDirty`.
- **Item.** `openPendingItem(id)` calls `GET /api/pending/item?id=` → `{title, when, md, resume}`.
  - `md` is computed live and every git output in it is fenced [B-N5]. It contains: `git status --short`; `git diff --stat`; a capped `git diff` (≤ 400 lines, for "show the content"); and the unpushed list `git log --oneline HEAD --not --remotes` (≤ 50). The log uses the same definition as the label's `unpushed`, so the two always agree (this is A-S1's range, not B-N5's `@{u}..HEAD`).
  - Same `curModal`/`#msgnav` reset first. Then `openText(title, when, md)`, then **Resume** and **Copy prompt** buttons prepended into `#msgbody`.
- **Resume** [B-S10, B-N4]. At click time it resolves `window.CR.term && window.CR.term.openAt`, guarded, because ext_cr_board.js loads before ext_cr_term.js. It calls `openAt(resume.cwd, 'new', resume.prompt)`.
  - For worktree, repo and missing items, `resume.cwd` = the repo's primary checkout `top`.
  - For scratch items, `resume.cwd` = `$HOME`.
  - The prompt names the target and tells Claude to use `git -C <path>`, so the session never lives inside a tree it may remove.
- **Routes.**
  - `GET /api/pending` returns `load_report()`.
  - `GET /api/pending/item?id=` returns 404 for an unknown id.
  - `POST /api/pending/run` gates with `ok, err = _local_caller(self); if not ok: 403` [B-N1]. Then `run_async("dry-run")`, returning `202 {"running": true}`, with no blocking: 80+ worktrees × 10s timeout could otherwise hold the request [M1].

### 7. Sequencing (what lands first and why)
0. **Prove M3 before building Resume.** In a scratch dir, run `claude "say hi and wait"` once in a PTY. Pass condition: the TUI stays interactive after answering, and the process has not exited. Record the result in the Log. If it exits (print-like behaviour), Resume falls back to `mode:"new"` plus `POST /api/term/inject {tty, text: prompt}` after open, and `open_pty` does not change. This costs one manual run and decides one `term_vt.py` edit.
1. **config keys + `interval_seconds` / `_v_interval` + tests.** These are pure and everything reads them.
2. **`registry.all_cwds` / `ClaudeProvider.cwds` + `pending.py` discover/inspect/classify + `cli_main` in dry-run only + temp-git fixtures + the TestBundle `--pending --dry-run` run.** This is the deterministic core and C7 on its own. Also measure, once, the repos found from first cwds against all cwd lines on the real disk, and log the number (see section 10).
3. **`clean()` + its fixtures and red-proofs.** It defaults to `dry-run` and gets its own review pass.
4. **server routes + `/api/config` safe gate + `start_worker()` + route tests.**
5. **`open_pty` `prompt` field + test** (only if step 0 passed).
6. **SPA**, in this order:
   - CSS tokens;
   - the boot-hook fetch;
   - card + `t`-key fix;
   - list/item modal;
   - `openAt` + Resume;
   - Settings rows.

   Gate with `tests/test_page_bundle.py::test_bundle_executes` and `tests/test_page_css.py` (with the new selector added), not `node --check` [B-N7]. Never put `*/` or `</script>` in a `web/*` comment. Then `make serve` on a spare port with `TRACKER_PENDING_INTERVAL=off` and check by hand.
7. **conventions.md rule-6 text (D4), README, bundle ORDER, Makefile, .gitignore.** Then `/branch-sync`, the gate, and push to `personal`.

### 8. Tests
`tests/test_pending.py` is skipped if `shutil.which("git")` is None.
- **Fixture.** A `tempfile.mkdtemp()` holding a bare `remote.git` and a `repo`.
  - Set up the repo: `git -c user.name=t -c user.email=t@t init -b main`, commit, add `origin`, push.
  - Patch these to temp paths (config is late-bound): `config.PENDING_FILE`, `PENDING_LOG`, `PENDING_LOCK`, `JOBS_DIR`, `SCRATCH_ROOT`, `LIVE_SESSIONS_DIR`, `PROJECTS`, `CONFIG_FILE`.
  - Age a fixture with `os.utime` on the admin files and the dir.
- **Env rule.** Every test that calls `run()` or the bundled server sets `TRACKER_PENDING_INTERVAL=off` [B-N12].

Fixtures, one guard each. The red-proof removes exactly that guard and must turn the test red.

| Fx | Setup | Expected | Red-proof (remove → red) |
|---|---|---|---|
| A | merged into origin/main, clean, aged 8d | removed in `safe`; branch gone | — (positive control) |
| B | uncommitted edit | `pending`, kept | — (git refusal is a second layer) |
| C | local commit, never pushed | `pending`, unpushed 1, kept | `unpushed` term |
| D | branch worktree, dir rm'd, HEAD contained | `missing`, pruned | — |
| E | pushed to origin/e, upstream set, clean, not merged | `clean`, reason "pushed; not merged", kept | `ancestor` term |
| F | fresh worktree at base, mtime now | kept, reason "active < grace" | idle term [A-B3] |
| F2 | F aged 8d + job `state.json` `blocked` with its worktreePath | kept | unfinished-job term |
| G | A + `.gitignore: .env` + `A/.env` | not deletable; `.env` byte-identical | `ignored` term [A-B4] |
| H | `--detach` worktree, commit X, dir rm'd | `missing` "1 orphan commits"; repo prune skipped; `git cat-file -t X == commit` | contained check [A-S3] |
| I | dirty primary checkout | `pending`, `deletable False`, untouched | primary guard [A-S2] |
| J | branch with **local** upstream `main`, main 2 ahead of origin | unpushed 2, `pending` | `--not --remotes` [A-S1] |
| K | done job tmp holding a standalone repo with 1 unpushed | item `kind:"repo"`, tree survives | `.git` walk guard [A-S5] |
| L | `SCRATCH_ROOT` is a **symlink** to temp; done-job tree aged 8d; sibling `<root>0/x` | tree removed; sibling kept | `_under` realpath [A-S4] |
| M | own-tracker worktree (patched `config._HERE` inside it), clean + aged | kept | own-tracker guard |

More assertions:
1. **Interval.** The section 4 table; `due()` boundaries; with `PENDING_INTERVAL="1d"`, a done-job tmp aged 2d is kept and one aged 8d is removed [A-S6].
2. **Discovery.**
   - Two primary repos → two distinct absolute keys [A-B2/B-B2].
   - A `state.json` cwd not in any transcript → discovered [B-S11].
   - A sticky `repos[]` entry survives a run with no seeds.
   - A transcript first-cwd under a repo → discovered, with `PROJECTS` holding over 200 files [A-B1 trimmed].
3. **Modes.**
   - `run_once("dry-run")` deletes nothing and lists A and D in `would_delete`.
   - A dry-run after a safe run leaves `scheduled_at` unchanged [B-S8].
4. **Lock.** With the per-user lock held, `run_once` with a different `PENDING_FILE` → `{"running": True}` [A-S7].
5. **Worker.** `_worker_loop` with `run_once` patched to raise once and then return `{"running": True}` survives 3 iterations, and every fake sleep is ≥ 60 [B-S7].
6. **CLI.**
   - `CONFIG_FILE` `{"PENDING_CLEAN":"safe"}` with the global reset to `dry-run`: `cli_main([])` calls `run_once` with `safe` [B-S1].
   - `--if-due` with a fresh `scheduled_at` → returns 0 without running.
7. **Card.**
   - Report with only a clean primary → `card.show False`.
   - Plus a dirty worktree → True [B-S2].
8. **Routes.**
   - `GET /api/pending` serves the temp report, and is absent from `_RO_GET_ALLOW`.
   - `POST /api/pending/run`: non-loopback → 403; loopback → 202 with `running`, returning before a patched slow `run_once` finishes [M1].
   - In `safe` config, POST run deletes nothing [B-S8].
   - `POST /api/config {PENDING_CLEAN:"safe"}`: non-loopback → 403 with config.json unchanged; loopback → 200 [B-S12].
   - `item_detail(B)["resume"]["cwd"] == top`, and the prompt contains B's path [B-S10].
9. **open_pty.** `mode:"new"` + `prompt` → argv ends with the prompt. A `-x` prompt or no prompt → argv unchanged [B-N3].
10. **Board / boot** (node, the pattern of `test_cr_board_order_and_empty.py`).
    - `pending.card.show false` → no `[data-tile-id="pending"]`.
    - With a card plus 2 sessions: focus DOM tile 1, press `t` → session[0] emitted [B-S4].
    - The tile class contains `cr-tile--span2`.
    - With a `curModal.live` spy, `openPendingList` then `syncModal()` → the spy is not called [B-S9].
    - A read-only boot ctx makes no `/api/pending` fetch [B-S6].
11. **Bundle / CSS.**
    - `TestBundle`: add `self._run("--pending", "--dry-run")` returncode 0, with temp `HOME` and interval off [B-B1].
    - `test_page_css.py`: `.tracker-next .cr-tile--pending` survives [B-S5].
12. **Selfcheck** (`tests/test_selfcheck.py`, conventions rule 9): `PENDING_INTERVAL` and `PENDING_CLEAN` are in `EDITABLE` and not in `RESTART_REQUIRED`, and `interval_seconds("1m") == 2592000`.

### 9. Decisions for the user (recommendation first)
- **D1 Scheduler: in-server daemon thread + CLI.**
  - `due()` reads `scheduled_at` from disk, so a stopped server catches up at its next start.
  - The CLI (`make pending`) works with the server down.
  - launchd is offered only as an optional README snippet calling `--pending --if-due`, so it can never override `PENDING_INTERVAL`. No plist is shipped.
- **D2 Resume prompt: per kind** [B-N11].
  - **Worktree / repo / missing:** *"Use the worktree-cleanup skill on `<path>` (repo `<top>`, branch `<branch>`; N uncommitted, M unpushed as of last fetch; operate with `git -C <path>`, do not cd into it). Commit/push or discard only as I decide; ask before anything destructive. Then use the cleanup skill for stray processes and scratch files of session(s) `<sids>`."*
  - **Scratch:** *"Use the cleanup skill for session `<sid>` scratch at `<path>`."*
  - This invokes `cleanup` literally (C5). `worktree-cleanup` leads because `cleanup` forbids git and excludes worktrees.
- **D3 Auto-delete scope: default `dry-run`.**
  - `safe` deletes only what section 5 lists: reclaimable worktrees via non-force remove + `branch -d`; prune when nothing is orphaned; and stale, `.git`-free scratch/job-tmp trees of done/failed/stopped, non-live sessions older than `max(interval, 7d)`.
  - **You may want to overrule:** whether `safe` should be the default (C6 reads as "delete"), and the strict "any ignored file blocks deletion". That rule means worktrees holding only `__pycache__`/`node_modules` never auto-delete.
- **D4 Conventions rule-6 exception** [M2]. Rule 6 says "read-only w.r.t. session logs". The cleaner deletes Claude-owned files, which needs an explicit exception. Recommended text, appended to rule 6:

  > *"Exception (pending-work worker, user-requested): `aitracker/pending.py` may delete, only in `PENDING_CLEAN=safe` and only under the guards in its module docstring, (a) `~/.claude/jobs/<id>/tmp/` and `/tmp/claude-<uid>/<slug>/<sid>/` trees with no `.git`, and (b) git worktrees via non-force `git worktree remove` / `branch -d` / `worktree prune`. It never deletes or edits `*.jsonl` transcripts, `state.json`, `~/.claude/tasks`, `file-history` or shell-snapshots."*

  Decline it, and C6 shrinks to "list only".

### 10. Known gaps (stated, not solved)
- **Discovery coverage.** It uses the first cwd per transcript only, as the reconciliation trimmed it. An orchestrator that starts in a non-repo parent and `cd`s into a repo is found only via jobs, tmp or sticky repos, or once any other session starts in that repo. Review A measured 5 repos (top-200 first cwds) against 23 (every cwd line). The no-limit first-cwd number is unmeasured, so step 2 logs it. If the gap is material, widen `ClaudeProvider.cwds()` to every cwd line; that is a one-function change.
- **Transcript pruning.** Claude prunes transcripts after about 30 days. The sticky `repos[]` keeps known repos alive after that.
- **No `gh`.** "Unpushed" is judged against last-fetched refs, and squash-merges look like pending work.
- **Moved worktrees.** `mv` loses the admin dir and prune has no grace, so the index can be lost after a move. Use Resume → `git worktree repair`.
- **Non-Claude providers** have no live signal, so the idle guard is their only one [A-N5].
- **Git timeouts.** A timeout marks a worktree `unknown`. It stays listed but is never deleted.
- **Classic view** has no card [B-N10].
- **Interval changes** apply within an hour [B-N8].
- **OpenRouter launcher** must forward `"$@"` for the Resume prompt to arrive. The fallback is Copy prompt.
- **Cleanup-skill scratch rules.** The cleanup skill's "keep the scratchpad dir; lsof before deleting logs" rules (B's pointer to A) apply to *live* sessions. The worker touches only non-live trees older than grace. Not reconciled in the table; flagged for the main thread.

## Technical plan (v3.1)

Author: opus plan leg, 2026-11-15. **v3 = v2 + the "User decisions" overrides U1, U6, U7 and U8.** U2–U5 are unchanged from v2. **v3.1 amends v3 in place with review C's clean-plan deltas 1–10, as the "Reconciliation of review C" table trims them.** In particular, the v3 "daily list refresh" is **deleted**: one interval governs the whole run [C-S6]. [C-xx] marks the review C origin of a change.

v3 is self-contained: an implementer reads only this section. Symbols were checked with grep/sed at b3d6230. **(new)** marks things that do not exist yet. Brackets give the origin of each point: [A-xx]/[B-xx] are review findings, [M1–M3] are items both reviews missed, and [U1–U8] are user decisions.

### 1. Shape in one paragraph
One stdlib module, `aitracker/pending.py`, is the deterministic core. It runs these stages in order:
1. **Discover** repos.
2. **Inspect** worktrees and tmp trees: read-only git and disk access.
3. **Ask `gh`** whether a bounded set of candidate branches was squash-merged [U7].
4. **Classify** each item. This is pure, and the display `verdict` is kept separate from `deletable`.
5. **Clean**: mode-gated and fail-closed.
6. **Write the report** to `pending.json`.

A second small module, `aitracker/schedule.py`, installs and uninstalls an OS scheduler job: a launchd agent on macOS, a Task Scheduler task on Windows [U1].

Everything runs through one function, `pending.tick()`. Its callers:
- (a) the server's daemon thread, which always runs when the interval is not `off` [C-B1];
- (b) the installed OS job, which fires once a day but only does anything when `--if-due` says a run is due;
- (c) a manual `make pending`.

Both (a) and (b) may be active together. `tick()` dedups them through the per-user lock and the on-disk `scheduled_at`, so the second caller finds nothing due.

`PENDING_INTERVAL` (default 90d) is the single source of truth for **the whole run**: scan, gh, list refresh, and the clean in the configured mode [C-S6]. Between runs, the only refreshes are "Scan now" and `make pending`. There is no separate daily list refresh.

"Scan now" is a dry-run that returns at once [B-S8, M1]. The server owns a `card` field. Both views render it from **one** shared fetch: the Control Room board tile and a classic-sidebar card [U6]. Both views also share **one** list/detail modal and **one** Resume path.

Resume opens a fresh Claude session at the repo's primary checkout, with a prompt written by the server. Claude only runs when the user presses Resume (C7).

### 2. Files to add / change (exact)

| File | Change |
|---|---|
| `aitracker/pending.py` **(new)** | The core (section 3). Imports are **named and top-level**, so the bundler can flatten them [B-B1]: `from . import config`, `from .store import _load_json, _save_json`, `from .registry import all_cwds`, `from .providers.claude import _pid_alive` [A-N4]. `from .schedule import sched_install, sched_uninstall, sched_status` [C-B2]. Stdlib: `subprocess, os, re, shutil, hashlib, threading, time, json, glob`. No top-level `fcntl`; the lock is in section 3 (portability). Never write `store.X` / `registry.X` / `schedule.X` attribute access, and never import `server`. |
| `aitracker/schedule.py` **(new)** | OS scheduler glue [U1] (section 3b). It imports only `from . import config` plus stdlib `os, sys, subprocess, plistlib`. Its public names are unique in the flattened bundle: `sched_install`, `sched_uninstall`, `sched_status`. `tunnel.py:309` already defines `status` [C-B2]. |
| `aitracker/registry.py` | **(new)** `all_cwds() -> set[str]`. For each available provider it uses `p.cwds()` if the provider defines one, else `{r["cwd"] for r in p.list() if r.get("cwd")}`. `list_sessions` is unchanged. |
| `aitracker/providers/claude.py` | **(new)** `ClaudeProvider.cwds()` returns `{_session_meta(f)["cwd"] for f in glob(config.PROJECTS/*/*.jsonl)} - {""}`. That is the first cwd of **every** transcript, with no 200 limit. `_session_meta` (:247) is already mtime-cached. |
| `aitracker/config.py` | Add `import re` [A-N1/B-N2]. Path constants next to `FLAGS_FILE` (:10):<br>• `PENDING_FILE` = `_HERE/pending.json`<br>• `PENDING_LOG` = `_HERE/pending.log`<br>• `PENDING_LOCK = os.path.join(os.path.expanduser("~"), ".ai-tracker-pending.lock")`: per-user, HOME-derived, so launchd, shells and Windows agree. `gettempdir()` differs under launchd, which has no TMPDIR. No `tempfile`/`getpass` import [A-S7, C-S1]<br>• `SCRATCH_ROOT = "/tmp/claude-%d" % os.getuid() if hasattr(os, "getuid") else None`. Windows has no known scratch root, so the scratch scan is skipped there.<br>Two EDITABLE keys, `PENDING_INTERVAL` (default **`"90d"`** [U8]) and `PENDING_CLEAN` (default `"dry-run"` [U3]). Each goes into `EDITABLE` (:207), `VALIDATORS` (:251), `_ENV_NAME`, `_RESOLVERS` (:511), `_PLAIN_ATTR_KEYS` and the module-level seeds. Neither goes into `RESTART_REQUIRED`. Also add the pure helpers `_v_interval` and `interval_seconds` (section 4). |
| `aitracker/server.py` | Top-level `from .pending import start_worker, load_report, item_detail, run_async`.<br>do_GET gets `/api/pending` and `/api/pending/item`; do_POST gets `/api/pending/run`.<br>In the `/api/config` branch, after the validator (≈:601): `if key == "PENDING_CLEAN" and coerced == "safe": ok, err = _local_caller(self); if not ok: return self._json({"error": "safe delete can only be enabled from this machine"}, 403)` [B-S12, B-N1].<br>`run()` (:911), after `publish_endpoint(actual)`: `start_worker()`.<br>Neither GET path goes into `_RO_GET_ALLOW` (:248).<br>**Windows step only** (section 7, step 15): the term-module loader (:944) iterates `() if os.name == "nt" else ("term_launch", "term_run", "term_vt")`. |
| `aitracker/store.py` | **Windows step only.** Replace the top-level `import fcntl` (:1) with `try: import fcntl` / `except ImportError: fcntl = None`. The forks lock (:350/:361) then uses `msvcrt.locking` when `fcntl is None`. POSIX behaviour is unchanged. |
| `aitracker/term_vt.py` | In `open_pty` (:2951), `mode == "new"` branch (~:3112), after `argv = [gateway.launcher(...)]`: `p = body.get("prompt"); if isinstance(p, str) and p.strip() and len(p) <= 4000 and not p.lstrip().startswith("-"): argv.append(p)` [B-N3]. Add one docstring line. Do this only if step 0 proves `claude "<prompt>"` stays interactive [M3]. |
| `aitracker/cli.py` | Top-level `from .pending import cli_main`. In `main()`, after `--help` and before serve: `if "--pending" in sys.argv: sys.exit(cli_main(sys.argv[1:]))`. Add HELP lines for `--pending [--dry-run] [--json] [--if-due] [--install-scheduler] [--uninstall-scheduler] [--scheduler-status]`. |
| `aitracker/web/app.js` | **Shared, used by both views** [U6]. **(new)** pieces:<br>• `let pendingCache = null`.<br>• `loadPending()`: called at the end of `loadSide()` (:1318), which polls in **both** UI modes. Throttled to 60s, or 5s while `pendingCache.running`, or immediately when `pendingDirty`. Skipped when `trackerReadOnly`. Non-OK responses are ignored.<br>• `renderPendingSide()`: the **classic card**. It fills **(new)** `#pendside` when `pendingCache.card.show`, otherwise hides it.<br>• `openPendingList(p)`, `openPendingItem(id)` and `pendingResume(r)`: **one** implementation of each, called by both views (section 6). |
| `aitracker/web/index.html` | **(new)** `<div class=pendside id=pendside hidden></div>` directly above `<div class=slist id=slist>` (:98). |
| `aitracker/web/app.css` | `.pendside{margin:6px 8px;padding:8px 10px;border:1px solid var(--violet);border-radius:8px;cursor:pointer}` plus a title/line style. `--violet` already exists in both themes (app.css:1/:2), so no new token is needed. |
| `aitracker/web/ext_launch.js` | `pickDirectory(raw, mode)` (:319) becomes `pickDirectory(raw, mode, prompt)`, which adds `prompt` to the POST body and **returns** a promise of `{ok, error}`. Existing callers ignore the return value. Export `window.ExtLaunch = { openAt: function (p, m, pr) { return pickDirectory(p, m, pr); } }`. This is the **single** Resume path for both views. ext_launch.js is inlined in both modes (page.py sorted `ext_*` glob), its picker helpers are null-safe (:205/:299/:306), and the tab-open code (:357) does not depend on the view. The v2 plan for `CR.term.openAt` is **dropped**, so no second copy exists (conventions rule 4). |
| `aitracker/web/ext_cr_boot.js` | In the `SIDE_EXT.push` hook (:997–1004), pass `pending: (typeof pendingCache !== 'undefined') ? pendingCache : null` into `board.update(...)`. The hook does **no** fetch of its own. That keeps one data source and keeps the board a pure renderer [B-S6]. |
| `aitracker/web/ext_cr_board.js` | **(new)** `pendingTile(p)`, modelled on `agentGroupTile` (:2950), with class `'cr-tile cr-tile--pending cr-tile--span2'` [B-S5]. It renders only when `p && p.card && p.card.show && !activeFilter` [B-N6].<br>`renderBoard` (:2606) prepends it and skips the empty copy while it shows.<br>`tileId` (:2599) returns `'pending'` for it.<br>`activateTile` (:2661): `if (t.kind === 'pending') { if (typeof openPendingList === 'function') openPendingList(lastState.pending); return; }`.<br>The `t` key (:3091): `var t = tiles.filter(function (x) { return tileId(x) === focusedTileId; })[0];` [B-S4]. |
| `aitracker/web/ext_cr_board.css` | `.tracker-next .cr-tile--pending { border-color: var(--line-pending); background: var(--surface-pending); }`, next to :1484–1489. |
| `aitracker/web/ext_cr.css` | `--state-pending`, `--surface-pending` and `--line-pending` in both blocks, next to `--surface-awaiting` (:71/:325), `--state-awaiting` (:135/:374) and `--line-awaiting` (:112/:364). Light: `#8A6FD1` / `#F1ECFB` / `#C3B3EC`. Dark: `#A48BE6` / `#2A2340` / `#6E58B8`. |
| `aitracker/web/ext_cr_dialogs.js` | Board tab (:1314), after `SNAPSHOT_TTL_MIN`, add two rows:<br>• `serverRow('Pending-work scan', 'PENDING_INTERVAL', 'Scan every <interval>: e.g. 90d, 2w, 3m (m = month). Each scan refreshes the list, checks gh, and cleans per the mode below. Use Scan now on the card to refresh between scans. "off" stops all scheduled scans. A change applies within an hour.' [C-S6], textFieldCtl(...trim))`<br>• `serverRow('Pending-work cleanup', 'PENDING_CLEAN', …, segmented([['off','Off'],['dry-run','List only'],['safe','Safe delete']]))`<br>Add `_ENVCHIP` entries for both. |
| `.claude/rules/conventions.md` | Rule 6 gains the two written exceptions: D4 (Claude tmp deletion) and D5 (`gh`). |
| `.gitignore` | `pending.json`, `pending.log`. The scheduler log lives in `~/Library/Logs`, outside the repo [C-S5]. |
| `scripts/bundle.py` | `ORDER` (:11) becomes `… "registry.py", "tunnel.py", "schedule.py", "pending.py", "server.py", "cli.py"`. HEADER (:19–23) gains `plistlib` [C-B2]. No regex changes. |
| `Makefile` | `pending:` → `@python3 -m aitracker --pending`; `pending-install:` → `--pending --install-scheduler`; `pending-uninstall:` → `--pending --uninstall-scheduler`. Add all three to `.PHONY` and `help`. |
| `README.md` | Cover:
- what is scanned, and the ways the job runs;
- one interval governs the whole run, and Scan now / `make pending` refresh between runs;
- the first run happens about 60s after the first server start, because `due()` is True with no report, so a new install shows the card without waiting 90 days;
- the exact delete rules, and the gh use;
- scheduler install, uninstall and repoint;
- the OS job sees only PATH/PYTHONPATH and the **installed checkout's** `config.json`, so `TRACKER_PENDING_*` env vars and other checkouts' settings do not reach it [C-N6];
- "run spare-port test servers with `TRACKER_PENDING_INTERVAL=off`";
- the Windows status (section 3b). |
| tests | One new file per step (section 7), so steps that run in parallel never share a test file. Add one assertion to `tests/test_selfcheck.py`. |

### 3. `aitracker/pending.py` — signatures and logic

```python
GIT_TIMEOUT = 10                 # s per git call; timeout -> verdict "unknown", not deletable
SCAN_ENTRY_CAP = 50_000          # dirents per tmp tree; exceeded -> keep
PENDING_GRACE = 7 * 86400        # deletion idle-grace; DECOUPLED from PENDING_INTERVAL [U8, A-S6]
SLACK = 3600                     # due() tolerance, so a daily OS trigger is not skipped by seconds  [C-S3]
GH_TIMEOUT = 15                  # s per gh call                                            [U7]
GH_MAX_CALLS = 20                # gh calls per scan, hard cap
GH_BUDGET_S = 120                # wall-clock budget for all gh calls in one scan
GH_NONE_TTL = 86400              # re-ask gh about a "no merged PR" answer after 24h
_RUNNING = threading.Event()

def tick(now=None) -> str        # THE scheduler decision, shared by thread, OS job and CLI:
    # if interval_seconds(config.PENDING_INTERVAL) is None -> "off"                       [C-S2]
    # report = _load_json(PENDING_FILE) read FRESH from disk on every call (never a memory copy)  [C-B1]
    # if due(report, now, interval_s): run_once(config.PENDING_CLEAN, scheduled=True) -> "run"
    # else -> "idle"            (no separate list-refresh branch: one interval, whole run  [C-S6])
def run_once(mode=None, now=None, scheduled=False) -> dict
    # takes the per-user lock (busy -> {"running": True}), then:
    # discover -> inspect -> gh -> classify -> clean(mode) -> report.
    # scheduled_at = now only when scheduled and mode == config.PENDING_CLEAN; else carried forward [B-S8]
def run_async(mode="dry-run") -> bool          # [M1] daemon thread; False if already running
def due(report, now, interval_s) -> bool       # pure; interval None -> False; no scheduled_at -> True;
                                               # else now - scheduled_at >= interval_s - SLACK            [C-S3]
def start_worker() -> None
    # idempotent; no-op only if PENDING_INTERVAL is "off". It does NOT check for an installed OS job:
    # both may run, and tick() dedups through the lock and due()                               [C-B1]
def _worker_loop(sleep=time.sleep, clock=time.time)
    # sleep(60) at boot; then forever: try: tick() except Exception: _log(...)          [B-S7]
    #   sleep(max(60, min(3600, seconds until the next run is due)))
def load_report() -> dict    # _load_json(PENDING_FILE, {}) normalised; adds "running"; card summary "scanning…" while running
def item_detail(item_id) -> dict | None   # live: {title, when, md, resume: {cwd, prompt}}
def resume_prompt(item) -> str            # per kind (D2)
def cli_main(argv) -> int
    # FIRST: config.apply_overrides(_load_json(config.CONFIG_FILE, {}))                 [B-S1]
    # --install-scheduler / --uninstall-scheduler / --scheduler-status -> sched_install()/sched_uninstall()/sched_status()  [C-B2]
    # --if-due -> print(tick()); return 0          ("off" | "run" | "idle")
    # --dry-run -> run_once("dry-run"); bare --pending -> run_once(config.PENDING_CLEAN, scheduled=True)
    # --json prints the report

def discover_repos(now) -> dict[str, dict]     # abs realpath common dir -> {"top", "cwds"}
def list_worktrees(repo) -> list[dict]         # git -C <top> worktree list --porcelain
def inspect_worktree(wt, repo, ctx) -> dict
def gh_merged(items, report_cache, now) -> None   # fills item["gh"] in place, bounded   [U7]
def scan_tmp(ctx, now) -> (list[dict], list[str]) # tmp entries, git_roots
def classify(wt, ctx, now) -> dict                # {"verdict", "deletable", "reason"}
def clean(report, mode, ctx, now) -> list[dict]
def _under(path, root, depth=None) -> bool        # normcase(realpath) vs normcase(realpath) via commonpath; exact rel depth
def _alive(pid) -> bool                           # os.name == "nt" -> True (fail-closed); else _pid_alive(pid)
def _lock()                                       # context manager on config.PENDING_LOCK:
                                                  #   fcntl.flock(LOCK_EX|LOCK_NB), or msvcrt.locking(LK_NBLCK, 1) on nt
def _git(cwd, *args) -> (rc, out)   # ["git", "--no-optional-locks", "-C", cwd, *args], timeout=GIT_TIMEOUT,
                                    # env + GIT_OPTIONAL_LOCKS=0, GIT_TERMINAL_PROMPT=0
def _gh(cwd, *args) -> (rc, out)    # [shutil.which("gh"), *args], cwd=cwd, timeout=GH_TIMEOUT, env + GH_PROMPT_DISABLED=1,
                                    # GH_NO_UPDATE_NOTIFIER=1, GH_SPINNER_DISABLED=1, NO_COLOR=1; GH_REPO and GH_HOST
                                    # REMOVED from the child env [C-S7]; which() None -> (None, "")
```

**Discovery** [A-B1/B-S11 trimmed, A-B2, A-S5]. The seed set is the union of four sources:
- `registry.all_cwds()`;
- the `cwd`, `originCwd` and `worktreePath` fields of every `config.JOBS_DIR/*/state.json`;
- the `git_roots` found by `scan_tmp`;
- the sticky `repos[]` from the previous `pending.json`. An entry is dropped only when its common dir is gone.

Each seed is resolved like this:
1. If the seed no longer exists, walk up to the nearest existing ancestor.
2. Run `rev-parse --path-format=absolute --git-common-dir`, then `realpath`. Skip non-repos.
3. Dedupe on the result.
4. `top` is the first porcelain `worktree` entry.

**ctx** (built once per run):
- `jobs`: a list of `(realpath(worktreePath or cwd), state)`.
- `live`: the realpath cwds from `config.LIVE_SESSIONS_DIR/*.json` where `_alive(pid)`. This feeds the guards only, never seeding.
- `tx`: `{realpath cwd: newest transcript mtime}`.

**inspect_worktree.** All read-only:
- `status --porcelain=v1 -z --untracked-files=normal` gives `dirty`, `untracked`, and up to 50 `files`.
- `status --porcelain=v1 -z --ignored=matching --untracked-files=no` gives `ignored` and up to 20 `ignored_files`. There is no allowlist [A-B4 trimmed].
- `unpushed = rev-list --count HEAD --not --remotes` [A-S1].
- `@{u}` gives `upstream`, `ahead` and `behind`, for display only.
- `base` is the first existing of `refs/remotes/*/{develop,main,master}`.
- `ancestor` comes from `merge-base --is-ancestor HEAD <base>`.
- `head` is `rev-parse HEAD`.
- `last_activity` is the max of: the mtimes of `<common>/worktrees/<name>/{HEAD,index,logs/HEAD}`, the dir mtime, and `ctx.tx` under the path [A-B3].
- For `prunable` entries: `contained` (`for-each-ref --contains <sha> --count=1` is non-empty) and `unpushed` (from `<sha>`) [A-S3].

**gh squash-merge check** [U7].

The exact command is `gh pr list --head <branch> --state merged --json number,url,headRefOid,baseRefName,mergedAt --limit 5` [C-N2]. It runs with `cwd=<top>`, and gh infers the repository from that checkout's remotes. `GH_REPO` and `GH_HOST` are stripped from the child env, so a server-wide override can't redirect every worktree [C-S7]. Optionally, a later change could pin `-R <owner>/<repo>` from the branch's remote URL. That is **not** built in v3.1.

A PR merged into a non-base branch (a stacked PR) still counts as merged. This is safe: the worktree must be clean and the branch ref is kept. The label names the base: "squash-merged into develop (PR #12)" [C-N2].

A **merged** answer means any returned PR has `headRefOid == item.head`. The PR merged exactly the local tip, so no commit was made after the merge.

Candidates are bounded. Only worktree items that would be reclaimable *except* for the merge test are asked. All of these must hold:
- not detached, not primary, not locked, not own-tracker;
- `dirty == untracked == ignored == 0`;
- not `ancestor`;
- idle ≥ `PENDING_GRACE`;
- no unfinished job;
- no live session.

Calls are sequential, oldest `last_activity` first, and stop at `GH_MAX_CALLS` or `GH_BUDGET_S`. Results are cached in `report["gh_cache"]` under the **string** key `"\x00".join((repo, branch, head))`, so it is valid JSON. Entries whose repo is no longer in `repos[]` are dropped [C-N3]. The rules:
- `merged` is cached for good, because a merged PR for an exact sha is immutable;
- `none` is re-asked after `GH_NONE_TTL`, so repeated Scan now clicks within 24h don't re-call gh;
- errors are **not** cached.

Item field: `gh: {"state": "merged"|"none"|"error"|"unavailable"|"skipped", "pr": url|null, "checked_at": ts}`. The states mean:
- `unavailable`: `gh` is not on PATH. Every candidate gets this and **no calls are made**.
- `error`: a non-zero exit (e.g. 4 = not authenticated), a timeout, unparseable JSON, or an ambiguous-repo refusal from `GH_PROMPT_DISABLED`. The **first `error` of any kind** trips a per-run circuit breaker [C-N1]. That covers fast offline and rate-limit exit-1 failures as well as auth and timeouts. It stops all further gh calls this run, so a failing scan makes exactly one call.
- `skipped`: not a candidate, or over the cap.

Every state except `merged` leaves the item non-deletable. gh failure is **fail-closed**.

**Report item.** This is the shared shape both views render. v2 fields plus `head` and `gh`:
```json
{"id": "<sha1(realpath)[:12]>", "kind": "worktree|repo", "path": "...", "repo": "<common>", "top": "<primary>",
 "branch": "feat-x", "detached": false, "head": "<sha>", "base": "origin/develop", "upstream": null,
 "dirty": 0, "untracked": 0, "ignored": 0, "files": [], "ignored_files": [],
 "unpushed": 4, "ahead": 0, "behind": 0, "ancestor": false, "locked": false, "primary": false,
 "missing": false, "contained": true, "last_activity": 1763190000,
 "gh": {"state": "merged", "pr": "https://github.com/o/r/pull/12", "checked_at": 1763200000},
 "verdict": "clean", "deletable": true, "reason": "squash-merged (PR #12)",
 "label": "squash-merged (PR #12) · worktree reclaimable; branch kept", "error": null}
```
- Tmp entries carry `{kind: "scratch", path, session, job, bytes, age_s, verdict: "stale"|"keep", deletable, reason}`.
- Top level: `{generated_at, scheduled_at, interval, mode, duration_s, repos[], gh_cache{}, items[], tmp[], deleted[], would_delete[], refused[], errors[], running, card: {show, title, summary, count}}`.
- `card.count` counts items with `verdict in {pending, missing}` plus `stale` tmp entries. `show` is `count > 0`. The summary is server-built. The JS never derives a verdict or a threshold.

**classify** [A-S2/B-S3].

The display verdict is the first of these that applies:
1. `unknown` on a git error or timeout.
2. `missing`. The label then says "N orphan commits" or "branch has N unpushed".
3. `pending` if `dirty or untracked or (unpushed > 0 and gh.state != "merged")`.
4. Otherwise `clean`, with reason "pushed; not merged into <base>" or "squash-merged (PR #n)".

Ignored files show in the label only.

`deletable` is False when any of these hold:
- the item is primary, bare or locked;
- it is the tracker's own checkout: `os.path.realpath(config._HERE).startswith(os.path.realpath(path) + os.sep)`;
- `ignored > 0`;
- the verdict is not `clean`.

**reclaimable** means `deletable` and **every** one of:
- (`ancestor and unpushed == 0`) **or** (`gh.state == "merged"`, with `headRefOid == head` already enforced);
- `now - last_activity >= PENDING_GRACE`;
- no `ctx.jobs` entry at or under the path with a state outside `{done, failed, stopped}`;
- no `ctx.live` cwd at or under the path.

**A MERGED PR on its own never makes anything deletable.** It replaces only the ancestor/unpushed term. Every other guard still applies, and the TOCTOU re-inspect re-checks all of them, including `head` being unchanged.

### 3b. `aitracker/schedule.py` — the OS job [U1]

```python
LABEL = "com.aitracker.pending"                 # launchd label
TASK = r"ai-tracker\pending"                    # Task Scheduler name
def _root() -> str                              # dirname(config._HERE): the checkout holding the package
def _argv() -> list[str]                        # [sys.executable, "-m", "aitracker", "--pending", "--if-due"]
def plist_path() -> str                         # LATE-BOUND: os.path.join(os.path.expanduser("~"), "Library",
                                                #   "LaunchAgents", LABEL + ".plist"), read at call time  [C-S4]
def sched_log_path() -> str                     # ~/Library/Logs/ai-tracker-pending.log, late-bound      [C-S5]
def launchd_plist() -> bytes                    # pure; plistlib.dumps({...}) below
def schtasks_create_argv() -> list[str]         # pure; below
def sched_install(run=subprocess.run) -> int    # dispatch on sys.platform; `run` injectable for tests   [C-B2 names]
def sched_uninstall(run=subprocess.run) -> int
def sched_status(run=subprocess.run) -> dict    # {"kind": "launchd"|"schtasks"|None, "installed": bool,
                                                #  "last_exit": int|None, "root": str|None, "root_exists": bool}  [C-B1, C-N5]
```
There is **no `installed()`** gate. The server thread never checks for the OS job [C-B1]. `os.getuid()` (for `gui/<uid>`) is called only inside the darwin branch, never at module level [C-N7].

**Guards common to both platforms.** `sched_install()` refuses, exit 2 with a message, in two cases:
- When `_root()` is a **linked worktree**: its `.git` is a file. A worktree may be removed later, and the job would then point at nothing. "Install from the primary checkout."
- On any platform other than darwin or win32. The refusal prints the equivalent crontab line (`0 10 * * * cd <root> && <py> -m aitracker --pending --if-due`) for the user to add themselves.

**macOS (launchd).**
- The plist is written to `plist_path()` with mode 0644:
  ```
  Label = LABEL
  ProgramArguments = _argv()
  WorkingDirectory = _root()
  EnvironmentVariables = {PATH: os.environ["PATH"] (captured at install, so git and gh resolve), PYTHONPATH: _root()}
  StartCalendarInterval = {Hour: 10, Minute: 0}   # daily; launchd runs a missed slot at the next wake
  RunAtLoad = False
  ProcessType = "Background"
  LowPriorityIO = True
  StandardOutPath = StandardErrorPath = sched_log_path()   # ~/Library/Logs, like this Mac's working agents; outside ~/Documents (TCC)  [C-S5]
  ```
- **Install:**
  - If a plist already exists with a different `WorkingDirectory`, print "replacing job that pointed at <old root>" [C-N5]. There is one job per user.
  - Run `launchctl bootout gui/<uid>/com.aitracker.pending` (errors ignored), then `launchctl bootstrap gui/<uid> <plist>`.
  - **If bootstrap fails, `os.remove(plist)` and return 1**, so no plist is left that never runs [C-B1].
- **Uninstall** runs `bootout` and then `os.remove(plist)`. Both are idempotent.
- **Status** reads `launchctl print gui/<uid>/com.aitracker.pending`:
  - rc 0 means installed;
  - `last_exit` is parsed from the `last exit code = N` line;
  - `root` and `root_exists` come from the plist's `WorkingDirectory`.

**Windows (Task Scheduler).**
- **Create:** `["schtasks", "/Create", "/TN", TASK, "/SC", "DAILY", "/ST", "10:00", "/F", "/TR", 'cmd /c cd /d "<root>" && "<pythonw.exe>" -m aitracker --pending --if-due >> "%LOCALAPPDATA%\ai-tracker-pending.log" 2>&1']`.
  - Use `pythonw.exe` from `sys.executable`'s dir when it exists, so no console flashes; else `python.exe` [C-N7].
  - The log redirect is dropped if it would breach the cap.
  - `schtasks /Create` has no working-directory option, hence the `cd /d`.
  - `/TR` is capped at 261 chars. Install refuses with a message if the string is still longer.
  - The task runs only while the user is logged on.
- **Uninstall:** `schtasks /Delete /TN TASK /F`.
- **Status:** `schtasks /Query /TN TASK`, where rc 0 means installed.
- A missed trigger is caught up because `--if-due` reads `scheduled_at` on the next trigger.

**Two triggers, one decision** [C-B1].
- The server thread and the OS job may both be active; neither switches the other off.
- Both call `tick()`, which takes the HOME-derived per-user lock and reads `scheduled_at` fresh from disk. A second caller therefore finds nothing due.
- If the OS job is broken (moved Python, deleted checkout, TCC denial), the server thread keeps scanning, and `--scheduler-status` shows `last_exit` and `root_exists`.
- The daily OS trigger only *asks*. `PENDING_INTERVAL` (± `SLACK`) alone decides whether a run happens.

**Windows portability: the honest verdict.** **The app does not run on Windows today.** These blockers were found by grep:

| Where | Problem on Windows | Minimum stdlib fix | In v3? |
|---|---|---|---|
| `store.py:1` `import fcntl` (top-level) | ImportError, and `server`, `cli` and `pending` all import store | Guarded import + `msvcrt.locking` for the forks lock (:350/:361) | yes (step 15) |
| `server.py:944` loader imports `term_vt` / `term_run`, which import `pty` at the top level (`term_vt.py:177`, `term_run.py:36`) | `ModuleNotFoundError: pty` has `e.name == "pty"`, so the loader **re-raises**, and `cli.py:6` imports server | Skip the term modules when `os.name == "nt"` | yes (step 15) |
| `providers/claude.py:562` `_pid_alive` → `os.kill(pid, 0)` | On Windows `os.kill` with any signal other than CTRL_C/BREAK calls **TerminateProcess**. Probing liveness would **kill** the process | `pending._alive()` returns True on nt: fail-closed, so nothing is live-guarded into deletion. The real fix would be ctypes `OpenProcess` + `GetExitCodeProcess`, which is out of scope | yes (in pending.py) |
| `os.getuid` (config `SCRATCH_ROOT`; launchd `gui/<uid>`) | AttributeError | `PENDING_LOCK` is HOME-derived; `SCRATCH_ROOT = None` on nt; `getuid` only inside schedule's darwin branch | yes |
| `fcntl.flock` (pending lock) | missing | `_lock()` uses `msvcrt.locking` on nt | yes |
| `/tmp/claude-<uid>` scratch layout | Claude Code's Windows scratch location is **unknown and not checked** | Scratch scan skipped on nt | yes (gap) |
| Path compare | case-insensitive FS | `os.path.normcase` in `_under` | yes |
| `term_launch.py:212` `osascript`; `ps`/`lsof` in `term_vt.py:3380/3397/3930/4069` and `claude.py:615`; `os.killpg`/`signal.SIGKILL` (term_run, term_vt, tunnel) | macOS/POSIX only | none; out of scope | no |

What this limits: on Windows, **only the CLI and Task Scheduler path is in scope**. That covers scan, gh, clean and `pending.json`. The server and both cards are not; they run only on POSIX. Even with step 15, the server's other features stay POSIX-only, and **nothing is verified on Windows**: this machine is macOS and there is no Windows CI. The Windows code is covered only by pure unit tests of `schtasks_create_argv()`, `_alive`/`_lock` with `os.name` patched, and the `store` import fallback. Whether `~/.claude/projects`, `jobs` and `sessions` have the same layout on Windows is **not grounded**.

### 4. Interval config — parser and validator (C2)
```python
_INTERVAL_RE = re.compile(r"^\s*(\d{1,3})\s*(d|w|mo|m)\s*$", re.I)   # m == mo == MONTH (30d), never minutes
_UNIT_S = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400, "mo": 30 * 86400}
_INTERVAL_MAX = 366 * 86400
def interval_seconds(s)    # "90d"->7776000, "3m"/"3M"->7776000 (unit via _UNIT_S[m.group(2).lower()]  [C-N9]),
                           # "2w"->1209600, "off"/"0"->None, invalid->None
def _v_interval(v)         # str only; "off"/"0" -> (True, "off"); 1d <= secs <= _INTERVAL_MAX -> (True, normalised); else (False, None)
VALIDATORS["PENDING_INTERVAL"] = _v_interval
VALIDATORS["PENDING_CLEAN"]    = _v_enum(("off", "dry-run", "safe"))
def resolve_pending_interval(o)   # config.json > os.environ["TRACKER_PENDING_INTERVAL"] via _v_interval > "90d"   [U8]
def resolve_pending_clean(o)      # config.json > os.environ["TRACKER_PENDING_CLEAN"] > "dry-run"                [U3]
```
Accepted: `7d`, `2w`, `1m`, `1mo`, `3m`, `90d`, `12m`, `365d`, `52w`, `off`, `0`. Rejected: `7`, `1y`, `-1d`, `1.5d`, `13m`, `400d`, `True`, `""`. `POST /api/config` already returns 400 through `VALIDATORS` (server.py:597–601).

**Interval vs grace, decoupled** [U8]. v2 used grace = max(interval, 7d). With the new 90d default, that would make an item wait 90 days idle *and then* up to another 90 days for the next clean: up to about 180 days. That conflates two different things:
- **`PENDING_INTERVAL`** is *how often the whole worker runs*: scan, gh, list, and the clean in the configured mode. The user asked for it to be configurable in days or months.
- **`PENDING_GRACE`** is a fixed 7 days. It answers "how long must an item be untouched before it can be deleted". That is a safety property of the item, and a cadence knob must not shrink or stretch it. This also closes A-S6: a `1d` interval no longer shrinks the grace.

**One interval, no daily list refresh** [C-S6]. Between scheduled runs, the card shows the last run's report together with its age ("scanned N days ago"). To refresh sooner, use **Scan now** (a dry-run) or `make pending`. A new install is not stuck for 90 days: `due()` is True when no `scheduled_at` exists, so the first run happens about 60s after the first server start, or at the first OS trigger. If you meant "delete things untouched for 90 days", that is the D3 overrule below.

### 5. Deletion — the risky spot, and its fallback (C6)
Nothing is deleted unless **every** condition below holds. Each one fails closed: any error, timeout or gh failure means keep.

1. **Mode.**
   - Only a `tick()`/`run_once` in `safe` deletes. That means `config.PENDING_CLEAN == "safe"`, and the run is either scheduled or a bare `make pending`.
   - "Scan now" is always `run_async("dry-run")`.
   - `dry-run` fills `would_delete[]` and touches nothing.
   - `safe` can be **enabled** only by a local caller [B-S12].
2. **Worktrees.** Only `reclaimable` items (section 3), re-inspected **immediately before** removal: every term, plus `head` unchanged.
   - Remove with `git -C <top> worktree remove <path>`, **never `--force`**.
   - Then `git -C <top> branch -d <branch>`, **never `-D`**. Skip this for a detached HEAD, and when the branch name equals the base's short name [A-N2, A-N3].
   - For a **squash-merged** item, `branch -d` refuses because the branch is not merged locally. That refusal is expected: the branch **ref is kept**, so the commits survive, and it is listed as "branch kept (squash-merged; delete with `-D` yourself)". Removing the worktree loses no commits.
   - Any git refusal is the KEEP signal. It is logged to `refused[]` and never retried.
3. **Missing worktrees** [A-S3 trimmed]. `git -C <top> worktree prune` runs only if every `prunable` entry in that repo is `contained`. Otherwise the whole repo's prune is skipped, and the orphan entry is listed as "N orphan commits".
4. **Scratch / tmp.** Only `SCRATCH_ROOT/<slug>/<sid>` (exact depth 2; POSIX only) and `JOBS_DIR/<id>/tmp` (exact `[id, "tmp"]`), checked through `_under` (realpath + normcase + commonpath). All of these must hold:
   - not a symlink;
   - the job state is in `{done, failed, stopped}`, or there is no job and no transcript newer than `PENDING_GRACE`;
   - the newest mtime is `< now - PENDING_GRACE`;
   - no `ctx.live` entry under it;
   - the walk stayed under `SCAN_ENTRY_CAP`;
   - **no `.git` file or directory anywhere in the tree** (`followlinks=False`).

   Removal is `shutil.rmtree`. Any error goes to `refused[]`. A tree's `.git` roots go to discovery instead: a linked worktree flows through rule 2, and a standalone repo becomes `kind: "repo"`, never deletable. This is two-phase across runs.
5. **Never touched:** `*.jsonl` transcripts, `state.json`, `~/.claude/tasks`, `file-history`, shell-snapshots (D4).
6. **Single cleaner.** One cleaner per user, through the per-user `PENDING_LOCK`, across the thread, the OS job, the CLI and every checkout.
7. **Audit.** One line per delete or refusal goes to `PENDING_LOG`. `deleted[]` covers the last run.

**Fallback.** The default is `dry-run` [U3]: the first release only lists deletions until the user picks "Safe delete" locally. A misclassification costs one Resume, never data. A squash-merge removal keeps the branch ref.

### 6. Cards (both views), click-through and Resume (C3, C4, C5)
- **Feed: one source** [U6]. `app.js` `loadPending()` runs at the end of `loadSide()`, which polls in both UI modes, and fills the global `pendingCache`.
  - The classic view renders it via `renderPendingSide()`.
  - The Control Room receives it as `state.pending` through the boot hook.
  - Read-only viewers do not fetch.
- **Cards: two renderers of one server `card`.** Neither renderer has any logic of its own.
  - **Classic:** `#pendside` above `#slist`, with a violet border. It shows `card.title` and `card.summary`, and a click calls `openPendingList(pendingCache)`.
  - **Control Room:** `pendingTile`, a `span2` tile coloured with `--state-pending`. It comes first, and only when no filter is active. A click goes to the same `openPendingList`.
  - Both read only `card.show`, `card.title` and `card.summary`. The summary reads "scanning…" while a scan runs [M1], and otherwise carries the server-computed age of the last run ("scanned 12 days ago"), because scheduled runs are `PENDING_INTERVAL` apart [C-S6].
- **List** (`openPendingList`, app.js, shared).
  - First set `curModal = null` and clear `#msgnav` [B-S9].
  - Then `openText('Pending work', when, '')` (app.js:2271), and fill `#msgbody` with one `h()` row per item: `label`, `path`, `branch`.
  - A **Scan now** button calls `POST /api/pending/run` and then sets `pendingDirty`.
- **Item** (`openPendingItem`, shared). It calls `GET /api/pending/item?id=`, which returns `{title, when, md, resume}`. The `md` is computed live, with fenced git output:
  - `git status --short`;
  - `git diff --stat`;
  - a `git diff` capped at 400 lines;
  - `git log --oneline HEAD --not --remotes`, capped at 50;
  - the gh line (PR link or error state).

  Do the same `curModal` reset, then `openText(title, when, md)`, then prepend **Resume** and **Copy prompt** buttons.
- **Resume** (`pendingResume`, shared). It calls `window.ExtLaunch.openAt(resume.cwd, 'new', resume.prompt)`, resolved at click time and guarded. On `{ok: false}`, the error is shown in the modal. The standalone `dist/tracker.py` page inlines only app.js, so `window.ExtLaunch` is absent there. When it is missing, the modal shows "Resume unavailable in this build — use Copy prompt" and never fails silently [C-N10].
  - `resume.cwd` is `top` for worktree, repo and missing items, and `$HOME` for scratch [B-S10].
  - The prompt tells Claude to use `git -C <path>`.
- **Routes.**
  - `GET /api/pending` returns `load_report()`.
  - `GET /api/pending/item?id=` returns 404 for an unknown id.
  - `POST /api/pending/run` does `ok, err = _local_caller(self)`, returns 403 when not ok, otherwise `run_async("dry-run")` and `202 {"running": true}` [M1].

### 7. Sequencing — small, independently assignable steps
Each step lists its files and its test. **∥** marks steps that can run in parallel with the other ∥ steps of the same wave, because they touch disjoint files, test files included. Every step ends green on its own new test file plus the existing suite.

**Wave 0 (do first, alone)**
0. **Prove M3.** Run `claude "say hi and wait"` once in a PTY, in a scratch dir. Pass: the TUI stays interactive. Record it in the Log. **No files.** If it fails, step 4 is dropped, step 5's `openAt` uses "`mode:new` + `POST /api/term/inject`" instead, and `term_vt.py` is untouched.

**Wave 1 (all ∥)**
1. ∥ **Config keys + parser.**
   - Files: `aitracker/config.py`.
   - Tests: `tests/test_pending_config.py` (new), covering the section 4 table, the defaults `90d` and `dry-run`, and env/config precedence. Plus the one assertion in `tests/test_selfcheck.py`: both keys are in `EDITABLE`, neither is in `RESTART_REQUIRED`, and `interval_seconds("3m") == 7776000`.
2. ∥ **Discovery seam.**
   - Files: `aitracker/registry.py` (`all_cwds`), `aitracker/providers/claude.py` (`ClaudeProvider.cwds`).
   - Test: `tests/test_pending_cwds.py` (new). A temp `PROJECTS` with 250 transcripts must return every first cwd, and a provider without `cwds()` falls back to its `list()`.
3. ∥ **OS scheduler module.**
   - Files: `aitracker/schedule.py` (`sched_install`/`sched_uninstall`/`sched_status`, `plist_path`, `sched_log_path`).
   - Test: `tests/test_pending_schedule.py` (new), all pure or with an injected `run`, **no real launchctl/schtasks**, and `HOME` patched to a temp dir. It covers:
     - plist keys and argv, and the log path under `~/Library/Logs`;
     - schtasks argv (`pythonw`, log redirect) and the 261-char refusal;
     - refusal from a linked worktree;
     - install/uninstall call sequences;
     - a bootstrap rc 5 leaves **no** plist [C-B1];
     - a second install with a different root prints the old root [C-N5];
     - `sched_status` parses `last exit code`;
     - the non-darwin/win32 crontab message;
     - **the real `~/Library/LaunchAgents` listing is identical before and after the test** [C-S4].
4. ∥ **PTY prompt** (only if step 0 passed).
   - Files: `aitracker/term_vt.py`.
   - Test: `tests/test_pending_pty_prompt.py` (new). With a prompt, the argv ends with it; a `-x` prompt or no prompt leaves the argv unchanged.
5. ∥ **One Resume path.**
   - Files: `aitracker/web/ext_launch.js` (`pickDirectory` gains `prompt` and a returned promise; `window.ExtLaunch.openAt`).
   - Test: `tests/test_pending_ext_launch.py` (new, node). `openAt` POSTs `prompt`, resolves `{ok, error}`, and the existing picker test stays green.
6. ∥ **Docs and rules.**
   - Files: `.claude/rules/conventions.md` (the D4 and D5 text), `.gitignore`, `README.md`, `Makefile`.
   - Test: none beyond review. `make help` lists the new targets.

**Wave 2 (sequential: one file, `pending.py`)**

7a. **Fixture helper, discover and inspect (read-only)** [C-N8].
   - Files: `tests/pending_fixture.py` (new), `aitracker/pending.py` (`discover_repos`, `list_worktrees`, `inspect_worktree`, `_git`, `_under`, `_alive`, `_lock`).
   - Test: `tests/test_pending_scan.py` (new), fixtures B, C, E, I and J. Also measure first-cwd against all-cwd repo coverage on the real disk once, and log the number.
7b. **Classify, report and card.**
   - Files: `aitracker/pending.py` (`classify`, `scan_tmp`, report, `card` with the age summary).
   - Test: `tests/test_pending_classify.py` (new), the remaining fixtures A, D, F, F2, G, H, K, L, M, plus card show/hide.
8. **gh check.**
   - Files: `aitracker/pending.py` (`_gh` with `GH_REPO`/`GH_HOST` stripped, `gh_merged`, string-keyed `gh_cache`, breaker on any error, `baseRefName` label).
   - Test: `tests/test_pending_gh.py` (new), fixtures N1–N8, using a **fake `gh` script** on a patched PATH. Never the real gh. Also run once on the real disk and log the count of each `gh.state` [C-S7].
9. **Clean.**
   - Files: `aitracker/pending.py` (`clean`, TOCTOU re-inspect, prune rule, rmtree rule, log).
   - Test: `tests/test_pending_clean.py` (new): red-proofs per guard, plus the squash-merge "worktree removed, branch kept".
10. **tick, worker, CLI and bundle.**
    - Files: `aitracker/pending.py` (`tick`, `due` with `SLACK`, `run_once`, `run_async`, `start_worker`, `_worker_loop`, `cli_main`), `aitracker/cli.py`, `scripts/bundle.py` (ORDER **and** HEADER `plistlib`) [C-B2].
    - Tests: `tests/test_pending_tick.py` (new), plus `tests/test_integration.py::TestBundle` extended with:
      - `--pending --dry-run` and `--pending --scheduler-status` both rc 0, with a temp HOME and interval off;
      - `dist/tracker.py` has exactly one `^def status\(`;
      - bundled `--version` works [C-B2].

**Wave 3 (∥ after wave 2)**
11. ∥ **Server.**
    - Files: `aitracker/server.py` (routes, `/api/config` safe gate, `start_worker()` in `run()`).
    - Test: `tests/test_pending_routes.py` (new).
12. ∥ **Shared SPA plus the classic card.**
    - Files: `aitracker/web/app.js` (`pendingCache`, `loadPending`, `renderPendingSide`, `openPendingList`/`Item`, `pendingResume`), `aitracker/web/index.html` (`#pendside`), `aitracker/web/app.css`.
    - Test: `tests/test_pending_ui_classic.py` (new, node/page stub). It covers:
      - card hidden when `show` is false;
      - shown and clickable when true;
      - `syncModal` does not overwrite the list;
      - read-only does no fetch;
      - Resume calls `ExtLaunch.openAt` with the server prompt;
      - without `ExtLaunch`, Resume shows "Resume unavailable in this build — use Copy prompt" [C-N10];
      - `.pendside` survives `build_page()`.
13. ∥ **Control Room card.**
    - Files: `aitracker/web/ext_cr_boot.js` (pass `pendingCache`), `aitracker/web/ext_cr_board.js` (tile, `tileId`, `activateTile`, `t` fix), `aitracker/web/ext_cr_board.css`, `aitracker/web/ext_cr.css`.
    - Tests: `tests/test_pending_ui_board.py` (new, node), plus `tests/test_page_css.py` (selector `.tracker-next .cr-tile--pending`).
    - Contract with step 12: the global names `pendingCache` and `openPendingList`, guarded with `typeof`.
14. ∥ **Settings rows.**
    - Files: `aitracker/web/ext_cr_dialogs.js`.
    - Test: `tests/test_pending_settings.py` (new, node). Both rows render and post `PENDING_INTERVAL`/`PENDING_CLEAN`.

**Wave 4 (sequential; after 11, since both touch server.py)**

15. **Windows import blockers.**
    - Files: `aitracker/store.py` (guarded `fcntl` + `msvcrt` lock), `aitracker/server.py` (nt loader skip).
    - Test: `tests/test_pending_windows_shims.py` (new). With `fcntl` hidden from `sys.modules` and `os.name` patched, `store` imports and the loader skips the term modules. This is a unit test, not a Windows run.

**Wave 5**

16. **Finish.**
    - Gate on `tests/test_page_bundle.py::test_bundle_executes` and `tests/test_page_css.py`, then the full gate.
    - `make serve` on a spare port with `TRACKER_PENDING_INTERVAL=off`, and check both views by hand.
    - `/branch-sync`, re-run the gate, and push to `personal`.
    - **No launchd install from the worktree**: `sched_install` refuses linked worktrees by design.

**Wave 6 (after landing on `main`, from the primary checkout)** [C-S5]

17. **Live launchd proof.** No files except the Log and section 10. The checklist is the test, and every item is a pass condition:
    1. `make pending-install`;
    2. `launchctl kickstart -p gui/$UID/com.aitracker.pending`;
    3. `launchctl print …` shows `last exit code = 0`;
    4. `pending.json` `generated_at` advanced;
    5. `~/Library/Logs/ai-tracker-pending.log` has no `Operation not permitted` (TCC);
    6. the logged `gh.state` counts are not all `error` (gh keychain under launchd);
    7. `make pending-uninstall`;
    8. `launchctl print` then returns rc ≠ 0 and the plist is gone.

    Record the TCC and gh results in section 10.

### 8. Tests (fixtures; each guard has one red-proof)
`tests/test_pending_scan.py`, `_classify.py`, `_gh.py` and `_clean.py` share a helper `tests/pending_fixture.py` (new, written in step 7a). It builds:
- a `tempfile.mkdtemp()` holding a bare `remote.git` and a `repo`, created with `git -c user.name=t -c user.email=t@t init -b main`, committed and pushed;
- `config.PENDING_FILE`, `PENDING_LOG`, `PENDING_LOCK`, `JOBS_DIR`, `SCRATCH_ROOT`, `LIVE_SESSIONS_DIR`, `PROJECTS` and `CONFIG_FILE`, all patched to temp paths;
- aging via `os.utime`.

The whole file is skipped if `shutil.which("git")` is None. Any test that calls `run()` or runs the bundle sets `TRACKER_PENDING_INTERVAL=off` [B-N12].

| Fx | Setup | Expected | Red-proof |
|---|---|---|---|
| A | merged into origin/main, clean, aged 8d | removed in `safe`; branch gone | positive control |
| B | uncommitted edit | `pending`, kept | — |
| C | local commit, never pushed, gh `none` | `pending`, unpushed 1, kept | `unpushed` term |
| D | branch worktree rm'd, HEAD contained | `missing`; pruned | — |
| E | pushed to origin/e, upstream set, not merged, gh `none` | `clean` "pushed; not merged", kept | `ancestor` term |
| F | fresh worktree at base, mtime now | kept "active < grace" | idle term |
| F2 | F aged 8d + `blocked` job on its path | kept | job term |
| G | A + ignored `.env` | not deletable; `.env` byte-identical | `ignored` term |
| H | detached, commit X, rm'd | `missing` "1 orphan commits"; prune skipped; `cat-file -t X == commit` | contained check |
| I | dirty primary checkout | `pending`, not deletable, untouched | primary guard |
| J | branch tracking **local** main, main 2 ahead of origin | unpushed 2, `pending` | `--not --remotes` |
| K | done job tmp holding a standalone repo with 1 unpushed | `kind:"repo"`, tree survives | `.git` walk |
| L | `SCRATCH_ROOT` a symlink; done-job tree aged 8d; sibling `<root>0/x` | tree removed; sibling kept | `_under` realpath |
| M | own-tracker worktree (patched `config._HERE`), clean, aged | kept | own-tracker guard |

gh fixtures (`tests/test_pending_gh.py`). A fake `gh` is an executable Python script on a temp PATH. It logs its argv and replies from a JSON table.

| Fx | Setup | Expected | Red-proof |
|---|---|---|---|
| N1 | C-shaped (branch commits only local, remote branch deleted), aged 8d, gh `MERGED` with `headRefOid == HEAD` | `clean` "squash-merged"; `safe` removes the worktree; **branch ref still exists**; commits reachable | — (positive) |
| N2 | N1, but a commit is added after the merge (`headRefOid != HEAD`) | `pending`, kept | head-equality check |
| N3 | N1 + dirty file, gh `MERGED` | `pending`, kept | MERGED-alone-never-deletes |
| N4 | `gh` not on PATH | `gh.state == "unavailable"`, kept, 0 calls | fail-closed |
| N5 | fake gh exits 4 (auth) for the first candidate; variant: exits 1 (offline) | all candidates `error`/`skipped`, exactly 1 call (breaker on **any** error) in both variants, kept | breaker [C-N1] |
| N6 | fake gh sleeps > `GH_TIMEOUT` (patched to 1s) | `error`, kept, 1 call | timeout |
| N7 | 25 candidates | ≤ `GH_MAX_CALLS` calls; extras `skipped`; a second run makes 0 calls for cached `merged`; `json.dumps(report)` round-trips (string cache key) | cap + cache [C-N3] |
| N8 | `GH_REPO=x/y` and `GH_HOST=h` in `os.environ` | the fake gh's logged env has neither | env strip [C-S7] |

More tests:
- `test_pending_tick.py`:
  - `tick()` returns `run` when due and `idle` otherwise, with no list-refresh branch [C-S6]:
    - a report with `generated_at` 2 days old and `scheduled_at` 10 days old under `90d` gives `idle`, and a patched `run_once` is not called;
  - interval `off` with an old report gives `"off"`, and `run_once` is never called [C-S2];
  - `scheduled_at = now - 86370` with `1d` gives `run`, thanks to `SLACK` [C-S3];
  - a dry-run leaves `scheduled_at` unchanged;
  - `run_once` then `tick(now + 5)` gives `idle`, and tick reads the disk fresh: no double run between the thread and the OS job [C-B1];
  - `start_worker()` **starts** the thread even when `sched_status` is patched to installed [C-B1];
  - the worker survives an exception, and every sleep is ≥ 60;
  - `cli_main` honours config.json `safe`;
  - the per-user lock returns `{"running": True}` across two `PENDING_FILE`s;
  - `config.PENDING_LOCK` is equal with `TMPDIR` set and unset, re-resolved under a patched env [C-S1];
  - grace stays 7d with interval `1d` and with `90d` [U8];
  - `interval_seconds("3M") == 7776000` [C-N9].
- `test_pending_routes.py`:
  - `GET /api/pending` serves the report, and the path is absent from `_RO_GET_ALLOW`;
  - `POST /api/pending/run` returns 403 for non-loopback, and 202 before a slow patched `run_once` finishes;
  - in `safe` mode the run route deletes nothing;
  - `/api/config` `PENDING_CLEAN=safe` from non-loopback returns 403 with config.json unchanged;
  - `item_detail(...)["resume"]["cwd"] == top`.

Node UI tests are listed in steps 12–14.

### 9. Decisions (user answers folded in; remaining overrules flagged)
- **D1 Scheduler** [U1, decided]. The server thread **and** an installed OS job: launchd on macOS, Task Scheduler on Windows. They are installed by `--install-scheduler` and removed by `--uninstall-scheduler`. The OS job fires daily but only *asks* `tick()` (`--if-due`), so `PENDING_INTERVAL` stays the single source of truth for the whole run. **Both triggers run.** `tick()` dedups them through the HOME-derived lock and the on-disk `scheduled_at`, so a broken OS job never silences the server thread [C-B1].
- **D2 Resume prompt** [U2, decided]. Two forms:
  - **Worktree / repo / missing:** *"Use the worktree-cleanup skill on `<path>` (repo `<top>`, branch `<branch>`; N uncommitted, M unpushed as of last fetch; gh: `<state/PR>`; operate with `git -C <path>`, do not cd into it). Commit/push or discard only as I decide; ask before anything destructive. Then use the cleanup skill for stray processes and scratch files of session(s) `<sids>`."*
  - **Scratch:** *"Use the cleanup skill for session `<sid>` scratch at `<path>`."*
- **D3 Auto-delete** [U3, decided: List only by default, Safe is opt-in]. Section 5 is the full scope. **One overrule to confirm:** the grace is a fixed 7 days, decoupled from the 90-day interval. If "90 days" was meant as "delete things untouched for 90 days", set `PENDING_GRACE` = interval instead. That is a one-line change; the cost is that items can then wait up to about 180 days.
- **D4 Rule-6 exception: Claude tmp folders** [U4, decided yes]. Append to conventions rule 6:
  > *"Exception (pending-work worker, user-requested): `aitracker/pending.py` may delete, only in `PENDING_CLEAN=safe` and only under the guards in its module docstring, (a) `~/.claude/jobs/<id>/tmp/` and `/tmp/claude-<uid>/<slug>/<sid>/` trees containing no `.git`, and (b) git worktrees via non-force `git worktree remove` / `git branch -d` / `git worktree prune`. It never deletes or edits `*.jsonl` transcripts, `state.json`, `~/.claude/tasks`, `file-history` or shell-snapshots."*
- **D5 Rule-6 exception: outbound network for `gh`** [U7, decided: call gh]. Append to conventions rule 6:
  > *"Exception (pending-work worker, user-requested): `aitracker/pending.py` — and only it, never synchronously inside a request handler (the server's worker and Scan-now threads may) — may run the GitHub CLI read-only as `gh pr list --head <branch> --state merged --json number,url,headRefOid,baseRefName,mergedAt --limit 5`, from the repo's own checkout, with `GH_REPO`/`GH_HOST` removed from its environment, to detect squash-merged branches. Cadence: once per scheduled run (every `PENDING_INTERVAL`, default 90 days) plus each manual Scan now or `make pending`. Bounds: at most `GH_MAX_CALLS` (20) calls and `GH_BUDGET_S` (120 s) per scan, `GH_TIMEOUT` (15 s) each, with a circuit breaker on the first error of any kind. It contacts only the GitHub API host gh resolves for that repo, with gh's own credentials (stored login or `GH_TOKEN`). Any gh failure (missing, unauthenticated, offline, timeout, unparseable) leaves the item pending and never deletable, and a MERGED PR never makes a worktree deletable unless every other deletion guard also passes. No other outbound network call is allowed."*
- **Card layout** [U5, decided]: one card. **Views** [U6, decided]: both.

### 10. Known gaps (stated, not solved)
- **Windows** (section 3b): the app does not run there today. Only the CLI and Task Scheduler path is in scope; it is **planned but untested**, cannot be proven on this machine, and is **not discharged**. Details:
  - On nt, the live-session guard fails closed (assumes alive), and scratch cleanup is skipped.
  - The task runs only while the user is logged on.
  - Claude Code's on-disk layout on Windows is **not grounded**.
- **gh scope.**
  - gh decides the target repo from the checkout's remotes (`GH_REPO`/`GH_HOST` are stripped). The only remote here is an SSH alias (`github-personal`), and whether gh maps it to github.com is unverified; steps 8 and 17 log real `gh.state` counts.
  - Repos with several GitHub remotes can be refused under `GH_PROMPT_DISABLED`, which shows as `error` and is kept.
  - Non-GitHub remotes always show `error` or `unavailable`, so they are kept.
  - `-R` pinning is not built.
- **launchd under TCC and gh keychain:** **not yet proven.** Step 17 records the result here.
- **Between runs**, the card is as old as the last run (up to `PENDING_INTERVAL`). Scan now and `make pending` are the refresh [C-S6]. A new install runs about 60s after the first server start, because there is no `scheduled_at`.
- **OS job config reach** [C-N6]. The OS job sees only PATH and PYTHONPATH, so `TRACKER_PENDING_*` env vars don't reach it. It reads the **installed checkout's** `config.json`, so Settings saved from a server in another checkout don't apply to it. A second `--install-scheduler` repoints the single per-user job.
- **Squash-merged branches**: they stay as local branches after their worktree is removed. `branch -d` refuses by design, and `-D` is never used.
- **Discovery** uses the first cwd per transcript. Step 7a logs the real coverage. If the gap matters, widen `ClaudeProvider.cwds()` to every cwd line.
- **Stale reports in other checkouts**: the report is per checkout. The OS job writes the installed checkout's `pending.json`, so a server started from a different checkout shows that checkout's report, which can be stale.
- **Transcripts pruned after about 30 days** are covered by sticky `repos[]`.
- **Moved worktrees** can lose their index at prune. Use Resume → `git worktree repair`.
- **Non-Claude providers** have no live signal, so the idle guard is their only one.
- **A git timeout** leaves an item `unknown`: listed, never deleted.
- **Interval edits** apply within an hour.
- **The OpenRouter launcher** must forward `"$@"` for the Resume prompt to arrive; otherwise use Copy prompt.
- **The cleanup skill's live-session scratch rules** remain unreconciled (flagged in v2).

## Plan addendum A.1 (to v3.1)

Author: opus plan leg, 2026-11-15. This covers R6's two new requirements: C8 (auto-install the scheduler on first serve) and C9 (in-app Update). It also checks R8. **A.1 amends A in place** with review D's accepted deltas, as reconciled in "## Reconciliation of review D". [D-Fn] marks the origin of each change.

Every symbol below was grepped in this worktree. That includes the implementers' in-progress `aitracker/schedule.py`: `_root` :15, `_is_linked_worktree` :64, `sched_install` :80, `sched_uninstall` :118, `sched_status` :130. It also includes `aitracker/pending.py`, where `_RUNNING` is at :31. **(new)** marks anything that does not exist yet. Plan v3.1 stays in force; this only adds to it.

### What already exists (searched first)
- **No self-update, restart, re-exec or version-check code exists.**
  - grep for `os.execv` / `git pull` / `/api/update` / `restart` finds only `os.execvp` for PTY children (`term_run.py:384`, `term_vt.py:1672`) and "takes effect on restart" UI copy (`ext_cr_dialogs.js:912–921`).
  - `__version__ = "1.1.0"` is at `aitracker/__init__.py:1` and is printed by `cli.py:34`.
- **Building blocks to reuse:**
  - `server._on_sigterm` (:894): its logic is `tunnel.stop(keep_on=True)` then `SystemExit`, so `TUNNEL_ON` survives.
  - `tunnel.autostart(actual, host)` in `run()` (:921) brings a kept tunnel back.
  - `publish_endpoint(actual)` (:861) rewrites `config.PORT_FILE` (:67) and the token on every start.
  - `bind()` (:848) falls through to the next port if this one is busy.
  - `run(host, port, open_browser=True)` (:911), and `cli.main()` calls `run(host=host, port=port)`.
  - `_local_caller(handler)` (:219) returns `(ok, err)`.
  - The cross-origin check is `term_gate._origin_ok` (:47). server.py reaches term_gate only through `sys.modules.get("aitracker.term_gate")` (:123), because term_* are optional and absent from the bundle.
  - `_term_count()` (:94) gives the live in-browser terminal count.
  - `Handler.do_POST` already refuses read-only callers before parsing the body (:558).
  - The page is `no-store`, and `build_page()` re-reads `web/*` from disk on **every** `/` request (`page.py:11–24`, `server.py:371`). So the page is not baked at startup: a reload after a fast-forward serves new web files even from old Python [D-F4].
  - `pending._pending_lock()` (pending.py:98) is a per-user, non-blocking context manager. It is held across a scan or clean.
  - `term_vt._live_count()` (:1821) and `term_run._live_count()` (:422) count live terminals. `_term_count()` counts only `term_vt` and feeds the badge.
- **`make serve` does NOT free the port** (`Makefile:9–10`, `serve: @PORT=$(PORT) python3 -m aitracker`; commit 4165837 removed `serve: stop`). `CLAUDE.md:22`'s "frees the port first" is stale and is corrected in A4 [D-F13]. A restart relies on the old socket being closed at exec. Review D's probe confirmed this: the socket is non-inheritable and rebinds fine.
- **Settings surface.**
  - The only Settings UI is the Control Room dialog, `ext_cr_dialogs.js`, with sections `['Interface','Board','Terminal','Notifications','Server','Tunnel','Data files']` (:1143) and the Server tab at :1393.
  - The classic view has **no settings surface**. app.js:128 only reads `/api/config` for icon style. So C9's UI lives in the Control Room Server tab only; see decision AD4.
- **R8 is already in v3.1.** Section 6 prepends **Resume** *and* **Copy prompt** to every item. A1 makes it explicit that Copy prompt is unconditional.
- **`pty.fork()` masters are INHERITABLE** (`term_vt.py:1656`, `term_run.py:361`). Review D measured `inheritable: True` on Python 3.12.3, macOS, and no cloexec exists anywhere. A bare `execv` would therefore keep every terminal's master open in the new image, orphaning the Claude children [D-F1].

### Part A — auto-install the scheduler job on first serve (C8)

**Hook.** In `server.run()`, right after `start_worker()` (v3.1 §2), add `threading.Thread(target=autoinstall_once, daemon=True).start()`. It runs on a thread so a slow `launchctl` never delays `serve_forever()`. Hooking `run()` rather than the Makefile covers `make serve`, `python -m aitracker` and the uv `ai-tracker` command alike. The Makefile is unchanged.

**New functions in `aitracker/schedule.py`:**
```python
def _optout_path() -> str          # late-bound: os.path.join(os.path.expanduser("~"), ".ai-tracker-scheduler-optout")
def _under_test() -> bool          # return "unittest" in sys.modules -- patchable belt     [D-F8]
def autoinstall_once(run=subprocess.run) -> str
    # returns "skipped:<why>" | "installed" | "failed" -- for tests and the one log line
```
**State = only an explicit opt-out** [D-F9]. The opt-out is a per-user, HOME-derived file whose mere presence means "opted out". There is no "done once" marker, no adopt step and no retry bookkeeping.
- `sched_uninstall()` gains one line: create the opt-out file.
- `sched_install()` gains one line: remove it.

Both are called by `--uninstall-scheduler` / `--install-scheduler` (`make pending-uninstall` / `make pending-install`).

`autoinstall_once` checks these in order and returns at the first one that applies:
1. `sys.platform not in ("darwin", "win32")` → `skipped:platform`.
2. A test or a disabled run → `skipped:test`. That is any of:
   - `_under_test()`;
   - `os.environ.get("TRACKER_SCHEDULER_AUTOINSTALL") == "0"`;
   - `config.interval_seconds(config.PENDING_INTERVAL) is None`.

   Every test that calls `run()` also sets `TRACKER_PENDING_INTERVAL=off` (v3.1 §8). `--selfcheck` never calls `run()` (cli.py :39). Tests of the later guards patch `_under_test` to False [D-F8].
3. Not a package checkout: `not os.path.isfile(os.path.join(config._HERE, "__init__.py"))`, which is the flattened bundle → `skipped:bundle`.
4. `_is_linked_worktree()` (schedule.py:64) → `skipped:worktree`. This is the plist-pins-a-deletable-path case review C flagged. `sched_install` also refuses it (:86), but checking first keeps the log quiet.
5. `realpath(_root())` is under the realpath of any of `tempfile.gettempdir()`, `/tmp` or `/var/folders` → `skipped:temp` [D-F10]. On macOS `/tmp` is `/private/tmp`.
6. The opt-out file exists → `skipped:optout`.
7. `st = sched_status(run)`. If `st["installed"] and st["root_exists"]` → `skipped:present`.
8. Otherwise `rc = sched_install(run)`. This covers both cases:
   - **not installed**, including a hand-deleted plist: the job is regenerated;
   - **installed but its root is gone** (moved checkout): `sched_install` already prints "replacing job that pointed at <old>" (:97–98) and **repoints the job to the checkout actually being served**.

   rc 0 → `installed`. Otherwise `_log` one line and return `failed`. There is no state to write, so the next serve simply tries again.

Any exception is caught, logged as one line, and returns `failed`. **The server always starts**: the call runs on a daemon thread and is fully wrapped.

A second `make serve` on the next free port (F13) also calls this. That is harmless and idempotent: it hits `skipped:present`. A spare-port server started from a linked worktree hits `skipped:worktree`.

**Settings "Scheduled scan" block and its routes** [H4; reverses D-F9's cut]. The user's only command is the first `make serve`; everything after that is buttons. `make pending-install` / `make pending-uninstall` stay as thin aliases, but they are not the user's path.
- **`GET /api/scheduler`** → `{**sched_status(), "opted_out": os.path.exists(_optout_path()), "supported": sys.platform in ("darwin", "win32")}`. It is local-only through the shared Host gate (below) plus `_local_caller`, and is not in `_RO_GET_ALLOW`.
- **`POST /api/scheduler`** with body `{"action": "install"|"uninstall"}`, an **enum** (anything else → 400). No user string reaches a command.
  - `install` → `sched_install()`, which also removes the opt-out. This button doubles as **Reinstall**, since `sched_install` already replaces and repoints an existing job.
  - `uninstall` → `sched_uninstall()`, which writes the opt-out.
  - It returns the fresh `GET /api/scheduler` body. The gates are the same as the update POSTs (`_update_gate`).
- **The block** (`ext_cr_dialogs.js`, Board tab, under the two Pending-work rows of v3.1 step 14), headed "Scheduled scan":
  - a status line: "Installed (launchd) · last exit 0 · runs from `<root>`" / "Not installed" / "Turned off (you uninstalled it)" / "Points at a missing checkout";
  - an **Install** button when the job is not installed, or a **Reinstall** button when it is installed;
  - an **Uninstall** button when it is installed.
  - It is hidden when `!supported` or when `ctx.readOnly()`. The 403 is the real gate.

**Risky spot.** A plist pinned to a path that later vanishes. It is mitigated by guards 3–5 and `sched_install`'s own refusal, and it **self-heals**: the next serve from a live checkout repoints the job. The fallback: the server thread keeps scanning regardless (v3.1 C-B1), so a dead OS job costs only redundancy.

### Part B — in-app Update (C9)

**What Update means.** A fast-forward of the running checkout to its branch's upstream, followed by an in-place restart of the dashboard process. There are no channels, no timer and no version pinning.

**New module `aitracker/update.py`.** It uses named top-level imports for the bundle: `from . import config, __version__`, `from .store import _load_json, _save_json`. It also has `from .pending import _pending_lock` and `from . import tunnel`; `tunnel.` is already rewritten by the bundler. Stdlib: `os, sys, subprocess, signal, json, tarfile, tempfile, threading, time, io`. All function names are unique in the flattened bundle (`status` already exists in tunnel.py).
```python
FETCH_TIMEOUT = 60        # s, git fetch
PREFLIGHT_TIMEOUT = 90    # s, import + startup smoke test of the fetched tree
_APPLY = threading.Lock() # single-flight apply                                                   [D-F2]
_RESTART_ERROR = None     # str set when exec fails; surfaced in update_status()                  [D-F4]
_STARTED_AT = time.time() # module import = process start
def update_kind() -> str            # "git" | "bundle" | "package"
def update_status() -> dict         # no network
def update_fetch() -> dict          # git fetch of the upstream's remote only; then update_status()
def update_apply(confirm_terminals=False) -> (int, dict)   # HTTP code + body; never raises
def restart_in_place(port, held) -> None   # flush, recovery line, _cloexec_all, os.execv; on OSError restore
def _term_live() -> int             # term_vt._live_count() + term_run._live_count(), each via sys.modules.get(...),
                                    # 0 when absent; _term_count() (badge) is unchanged                [D-F1]
def _cloexec_all() -> None          # every fd >= 3 (os.listdir("/dev/fd"), fallback range(3, SC_OPEN_MAX))
                                    # -> os.set_inheritable(fd, False), OSError ignored              [D-F1]
def _g(*args, timeout=10) -> (rc, out)
    # Popen(["git", "-C", root, *args], start_new_session=True (no controlling tty -> ssh can't read /dev/tty),
    #       stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env + GIT_TERMINAL_PROMPT=0, GIT_OPTIONAL_LOCKS=0)
    # communicate(timeout); on TimeoutExpired: os.killpg(p.pid, SIGKILL) (pattern of tunnel.py:211/264) -> (None, "timeout")  [D-F5]
```

**`update_kind`.**
- `bundle` when `config._HERE` has no `__init__.py`.
- `git` when `_g("rev-parse", "--show-toplevel")` equals `realpath(dirname(config._HERE))`.
- Otherwise `package` (uv install).

**`update_status()` schema.** It is the body of `GET /api/update`:
```json
{"kind": "git", "version": "1.1.0", "root": "...", "branch": "main", "detached": false,
 "upstream": "personal/main", "head": "<sha>", "head_subject": "...", "behind": 3, "ahead": 0,
 "dirty": ["M aitracker/x.py"], "fetched_at": 1763200000, "started_at": 1763190000,
 "can_update": true, "reason": null, "terminals": 0, "pending_running": false, "restart_error": null}
```
How each field is computed:
- `behind` and `ahead` come from `rev-list --left-right --count @{u}...HEAD` against the **last fetch**.
- `fetched_at` is the mtime of `<git-dir>/FETCH_HEAD`.
- `dirty` comes from `status --porcelain --untracked-files=no`, first 10 entries. Untracked and ignored files (`config.json`, `flags.json`) do not block a fast-forward.
- `started_at` is `_STARTED_AT`.
- `terminals` is `_term_live()`.
- `pending_running` (`pending._RUNNING.is_set()`) is **display only**. The real guard is the lock in apply step 0 [D-F2].
- `restart_error` is `_RESTART_ERROR` [D-F4].
- `can_update` and `reason` are server-owned; the JS shows `reason` verbatim. The first failing check wins:
  1. `kind != git`;
  2. `detached`;
  3. no upstream ("set one with `git branch -u`");
  4. `dirty` ("commit or discard local edits first");
  5. `ahead > 0 and behind > 0` ("local commits — not fast-forwardable");
  6. `behind == 0` ("up to date").

**For `bundle` and `package`,** `can_update` is false. The reason says:
- bundle: "Standalone build — regenerate with `make bundle` from a clone";
- package: "Installed package (version X) — reinstall it with uv to update".

The section shows only the version line and that reason, with no buttons.

**`update_fetch()`** runs `_g("fetch", "--quiet", "--no-tags", <remote>, <branch-of-upstream>, timeout=FETCH_TIMEOUT)`. `<remote>` comes from `git config branch.<b>.remote`, which is `personal` for this repo's `main`, and the branch from `@{u}`. Both are **read from git config, never from the request**. It returns a fresh `update_status()`.

**`update_apply(confirm_terminals)`** runs these steps in order. Any failure releases what step 0 took, returns `(409, {error})` and changes nothing:
0. **Single-flight and scan exclusion** [D-F2]:
   - `_APPLY.acquire(blocking=False)`. If busy → `409 "update already in progress"`.
   - Then `cm = _pending_lock(); got = cm.__enter__()`. If `got` is false → `409 "scan in progress"`.
   - On success both stay **held until exec**. The flock fd is opened by `open()`, so it is non-inheritable and released at exec, and `_cloexec_all` covers it too. A scan or clean can therefore never start between the check and the exec, and two applies can't both get 202.
1. `update_fetch()`. Then `can_update` must be true.
2. **Resolve the target once** [D-F3]: `target = _g("rev-parse", "@{u}")`. Every later step uses `target`, never `@{u}`. `old = _g("rev-parse", "HEAD")`.
3. **Terminal check** [D-F1]. `pty.fork` masters are inheritable (measured), so `_cloexec_all()` runs before `execv`. The kernel then closes every master at exec, and the terminals' children get SIGHUP. Their conversations remain resumable from disk, and the SIGHUP'd children are reaped zombies under the new image (harmless) [D-F15]. If `_term_live()` > 0 and not `confirm_terminals`, return `(409, {"error": "N open terminals will close", "needs_confirm": true})`.
4. **Pre-flight, which is the rollback guard** [D-F7]. It tests `target` before touching the checkout:
   - run `git archive --format=tar <target>`;
   - extract it into a `tempfile.mkdtemp()` with stdlib `tarfile`, rejecting members with absolute paths or `..`;
   - run, with `env TRACKER_PENDING_INTERVAL=off TRACKER_SCHEDULER_AUTOINSTALL=0` and `timeout=PREFLIGHT_TIMEOUT`:
     `[sys.executable, "-I", "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); import aitracker.server, aitracker.cli; from aitracker import config, page; config.apply_overrides(json.load(open(sys.argv[2])) if sys.argv[2] else {}); page.build_page(); print(aitracker.__version__)", tmp, <config.CONFIG_FILE if it exists else "">]`
     This covers the import, the user's **real** `config.json` through the new validators, and building the page from the new `web/*`, which is what `run()` and `/` do before serving;
   - rc ≠ 0 → `409` with the last 20 stderr lines, and the checkout is untouched;
   - always `rmtree` the temp dir.
5. `_g("merge", "--ff-only", target)`. This is the only write. There is **never** `stash`, `reset`, `checkout`, `--force` or `pull --rebase`. A refusal → `409` with git's message.
6. Return `(202, {"restarting": true, "from": old, "to": target, "recover": "<recovery line>"})`. The route then starts `restart_in_place(port, held)` on a thread after `0.5s`, so the response is flushed first. There is no `update.json` and no `TRACKER_RESTARTED` [D-F12].

The **recovery line** is: "If the dashboard does not come back: `git -C <root> checkout --detach <old>` then `make serve` (you were on `<branch>` at `<old>`)."

**`restart_in_place(port, held)`** [D-F4]:
1. `tunnel.stop(keep_on=True)`, the same call `_on_sigterm` makes. `TUNNEL_ON` survives, and the new process's `run()` → `tunnel.autostart` brings it back. A quick tunnel gets a **new** trycloudflare URL, which remote viewers must re-open. This is acceptable: tunnel callers can't trigger an update.
2. Set `os.environ["PORT"] = str(port)` and `os.environ["TRACKER_NO_BROWSER"] = "1"`.
3. `argv = getattr(sys, "orig_argv", None)` (3.10+; `pyproject.toml` says ≥3.8), falling back to `[sys.executable, "-m", "aitracker", *sys.argv[1:]]`.
4. `sys.stdout.flush(); sys.stderr.flush(); print(recovery_line, flush=True)`. The recovery line lands in the `make serve` terminal, which survives a broken page [D-F7].
5. `_cloexec_all()`, then `os.execv(sys.executable, argv)`. Exec replaces the image and keeps the PID and cwd. The listening socket is non-inheritable, so it closes at exec. `HTTPServer.allow_reuse_address` is on, so the new `bind()` takes the same port (probe-confirmed).
6. **`except OSError as e`** (a moved `sys.executable`, ENOEXEC):
   - `tunnel.autostart(port, config.BIND_HOST)`;
   - `_RESTART_ERROR = str(e)`;
   - release `held` (`cm.__exit__`, `_APPLY.release()`).

   The server keeps serving. Note: from that point it is **old Python with new `web/*`**, because `build_page` re-reads from disk. The page shows `restart_error` at once and asks for a manual `make stop && make serve`.

**`cli.main()` change.** `run(host=host, port=port, open_browser=os.environ.get("TRACKER_NO_BROWSER") != "1")`, so a restart doesn't open a new browser tab.

**If the new process fails to start anyway** (pre-flight passed, but bind or runtime fails), the dashboard is down.
- The open page's reconnect loop times out after 60s and shows the `recover` line from the 202 body it already holds.
- The same line was printed to the `make serve` terminal, and README repeats the command.
- No automatic rollback is built. A rollback would need `checkout`/`reset`, which D6 forbids. The import + config + page-build pre-flight covers the common failures. This is AD3.

**Routes** (server.py, explicit branches like `/api/pending`):
- `GET /api/update` → `update_status()`. Not added to `_RO_GET_ALLOW` (:248), so tunnel read-only viewers get 403.
- `POST /api/update/fetch` → `update_fetch()`.
- `POST /api/update/apply`, with a body of `{"confirm_terminals": bool}` only; any other key is ignored. It calls `update_apply(confirm_terminals=body.get("confirm_terminals") is True)`.
- The scheduler routes are `GET`/`POST /api/scheduler` (Part A, H4), not part of `/api/update/*`.
- **(F11)** `/api/list` gains `headers["X-Server-Started"] = str(_STARTED_AT)` next to `X-Server-Now` (:398). The page reloads when the value changes, so every open tab picks up a restart, not just the tab that pressed Update [D-F11].

**Security** [D-F6]. Both POSTs go through **(new)** `_update_gate(handler)` in server.py, which returns `(ok, err)`:
```python
ok, err = _local_caller(h)                                    # peer loopback + no proxy headers (:219-229)
host = urlparse("//" + h.headers.get("Host", "")).hostname
tg = sys.modules.get("aitracker.term_gate")
ok = ok and host in ("localhost", "127.0.0.1", "::1") and tg is not None and tg._origin_ok(h)
```
- The **loopback Host check** blocks DNS rebinding: an `evil.example` page that rebinds to 127.0.0.1 still sends `Host: evil.example`.
- It **fails closed** when `term_gate` is absent, as in the bundle.
- `do_POST` already denies read-only callers before body parsing (:558).
- There is no shell (`subprocess` argv lists only), and the request supplies no argument: remote, branch and sha all come from git config and the once-resolved `target`.
- The same DNS-rebinding gap on every existing route is **fixed in this plan** per H2, by the shared Host gate below.

**Shared Host gate for all routes without a credential** [H2]. This answers which file owns the helper, which routes get it, and the test that proves it.
- **The helper.** `util.is_loopback_host(host) -> bool` **(new)**, in `aitracker/util.py`, which is always present and in the bundle. It holds the `_LOOPBACK_NAMES` set and the `ipaddress` check that are today private to `term_gate._is_loopback` (term_gate.py:21–35). `term_gate._is_loopback` becomes a one-line delegate to it, so there is one copy.
- **The gate**, at the top of `Handler.do_GET` and `Handler.do_POST` in server.py, right after `_authok()`:
  ```python
  host = urlparse("//" + self.headers.get("Host", "")).hostname
  if (host and not self._cred() and util.is_loopback_host(config.BIND_HOST)
          and not util.is_loopback_host(host)):
      return self._json({"error": "refused: Host is not this machine (DNS rebinding guard)"}, 403)
  ```
  Each condition has a reason:
  - **No credential** (`_cred()` empty, server.py:305). With `TRACKER_AUTH` or a tunnel credential, a rebinding page has no cookie and already gets 401. So authenticated LAN/Tailscale/tunnel use (Host = a real name) is untouched.
  - **Loopback bind.** A `HOST=0.0.0.0` no-auth LAN dashboard is the user's explicit choice, and terminals already refuse it (`term_gate.allowed`, :37–45).
  - **A missing Host** is allowed. HTTP/1.0 curl may omit it, and browsers, which are what a rebinding attack uses, always send it.
- **Routes covered.** Because the gate is in the two dispatchers, it covers **every** route, including the `EXTRA_GET`/`EXTRA_POST` routes (server.py:547/:829) that the term modules register. The local-only and terminal call sites it protects (grep of `_local_caller(`/`guard(`):
  - `term_launch.open_terminal` (:161/:163, `POST /api/term/open`);
  - term_vt: `open_pty` :3070, `term_cwds` :3704, `keys` :3734, `close_pty` :3801, `term_list` :3880, `resize_pty` :3900, `attached` :4104, `screen_stream` :4143, `term_scrollback` :4334, `inject` :4634, `renderer_info` :4730, `raw_stream` :4766;
  - term_run: `status` :448, `run` :459, `stream` :533, `kill` :599;
  - server.py: `GET /api/pending*` :411–413, `POST /api/pending/run` :595, the `/api/config` safe gate, and the new `/api/update*` and `/api/scheduler` routes.
- **The proof.** One table-driven test, `tests/test_host_gate.py`:
  - It enumerates every key of `server.EXTRA_GET` / `server.EXTRA_POST` after the term modules load, plus the explicit `p.path ==` routes of do_GET/do_POST.
  - Each is requested through a live loopback test server with `Host: evil.example:<port>`, no auth, and a loopback bind. Every one must answer 403 with the rebinding error.
  - The same requests with `Host: localhost:<port>` do not get that error.
  - With `TRACKER_AUTH` set, `Host: evil.example` falls to the existing 401 path.
  - Red-proof: remove the gate and at least `/api/term/pty` and `/api/session` stop returning 403.

`_update_gate` keeps its explicit loopback-Host check as a belt (and still fails closed without term_gate). The global gate is the fix.

**Page side** (`aitracker/web/ext_cr_dialogs.js`, Server tab, :1393), a **(new)** "Update" block:
- **Status line**, from `GET /api/update` on open: "`<branch>` @ `<short head>` — `<head_subject>`. N behind `<upstream>` as of `<fetched_at age>`." Plus `dirty` files, or the `reason`.
- **Check for updates** button → `POST /api/update/fetch` → re-render.
- **Update and restart** button, enabled only when `can_update`. It posts apply, and on 409 `needs_confirm` it shows a confirm ("N open terminals will close") and re-posts with `confirm_terminals: true`. On 202 it shows "Restarting…" and polls `GET /api/update` every 1s:
  - when `started_at` changes, it calls `location.reload()` (the page is `no-store` and built from disk);
  - when `restart_error` is non-null, it shows it at once;
  - after 60s it shows the `recover` line.
- The scheduler controls live in the Board tab's "Scheduled scan" block (Part A, H4), not here.
- **Read-only:** the block is hidden when `ctx.readOnly()` (ext_cr_boot.js :439). The server's 403 is the real gate.

**Network (rule 6).** `git fetch` is outbound network, so it needs a **third** written exception, D6, in `.claude/rules/conventions.md`. This is review D's narrower wording, verbatim:
> *"Exception (in-app Update, user-requested R6): `aitracker/update.py` may run `git fetch --quiet --no-tags <remote> <branch>` for the running checkout's own upstream, only when a local caller (loopback peer, loopback Host name, same Origin, not tunnelled, not read-only) presses Check for updates or Update and restart. Remote and branch come from git config, never from the request. The fetch runs with no controlling terminal and a timeout that kills its process group. There is no scheduled or automatic fetch. The only write is `git merge --ff-only <sha>`, where `<sha>` is the commit fetched and import/startup pre-flighted in that same request. It never stashes, resets, checks out, forces or rebases. No other outbound network call is allowed."*

### Sequencing — steps A1.. (each: files + test; ∥ = file-disjoint, can run in parallel)
Each step says which remaining v3.1 steps (11–15) it must come after. "Free" means it touches none of the v3.1 step 11–15 files (`server.py`, `app.js`, `index.html`, `app.css`, `ext_cr_*`, `store.py`).

**Wave A-1 (all ∥ with each other, and with v3.1 steps 11–15 unless noted)**
- **A2 ∥ — Auto-install** [D-F8, F9, F10].
  - Files: `aitracker/schedule.py` (`_optout_path`, `_under_test`, `autoinstall_once`; one line each in `sched_uninstall` (create the opt-out) and `sched_install` (remove it)).
  - After: v3.1 step 3 (done). **Free** of 11–15.
  - Test: `tests/test_scheduler_autoinstall.py` (new), with HOME patched to a temp dir, `run` injected, and `_under_test` patched False except in the test-guard case. It covers:
    - each skip in order: platform; test/env/off; bundle; linked worktree; temp root, including `/tmp/fake`; opt-out present; installed with root present (only the status call made);
    - not installed → install;
    - installed with `root_exists` False → install (repoint);
    - install rc 1 → `failed` with no state written;
    - an exception → `failed`;
    - `sched_uninstall` creates the opt-out and `sched_install` removes it;
    - the real `~/Library/LaunchAgents` listing is unchanged.
- **A3a ∥ — Update core: status, fetch, apply** [D-F2, F3, F5, F7, F14].
  - Files: `aitracker/update.py` (new: `update_kind`, `_g`, `update_status`, `update_fetch`, `update_apply`, `_term_live`), plus `tests/update_fixture.py` (new). The fixture is a temp bare remote with a **stub** `aitracker/` package (`__init__.py` with `__version__`, `server.py`, `cli.py`, `config.py` with `apply_overrides`, `page.py` with `build_page`, `web/`), a clone, and a second clone that pushes.
  - After: none (new files; it only *calls* `pending._pending_lock`). **Free** of 11–15.
  - Test: `tests/test_update.py` (new) covers:
    - `update_status` behind=1 after fetch;
    - `can_update` and `reason` for each refusal: detached, no upstream, dirty, diverged, up to date;
    - apply fast-forwards to exactly `target`, even when a patched pre-flight hook pushes and fetches Y mid-flight, so HEAD == X [F3];
    - a target with a raising `server.py`, with an `apply_overrides` that raises on the real `config.json` key, or with `web/app.css` deleted → each gives 409 and HEAD unchanged [F7];
    - the test holding `_pending_lock` → 409 "scan in progress";
    - while apply holds it, `pending.run_once()` returns `{"running": True}`;
    - a second concurrent apply → 409 [F2];
    - `term_run._live_count`=1 → `needs_confirm` [F1];
    - a fake `GIT_SSH_COMMAND` that opens `/dev/tty` gets ENXIO and is dead after the timeout [F5];
    - no `stash`/`reset`/`checkout`/`--force` in any recorded argv;
    - bundle/package reasons.

    Red-proofs:
    - skip the pre-flight → the merge happens;
    - drop the lock → the merge happens under a held scan lock;
    - drop `start_new_session` → the fake ssh survives.

**Wave A-2 (sequential after A3a, same file)**
- **A3b — Restart path** [D-F1, F4, F12].
  - Files: `aitracker/update.py` (`_cloexec_all`, `restart_in_place`, the exec-failure path).
  - After: A3a. **Free** of 11–15.
  - Test: `tests/test_update_restart.py` (new) covers:
    - `pty.fork` child `sleep 30` → `_cloexec_all()` → `os.get_inheritable(fd) is False`;
    - a subprocess script (pty.fork, `_cloexec_all`, `execv` printing `/dev/fd`) → the master fd is absent;
    - `os.execv` patched to raise OSError → `tunnel.autostart` called, `update_status()["restart_error"]` set, locks released;
    - `sys` without `orig_argv` → fallback argv;
    - the recovery line is printed and flushed before exec;
    - env has `PORT` and `TRACKER_NO_BROWSER`, and no `TRACKER_RESTARTED`.

**Wave A-3 (each after the named v3.1 step; file-disjoint from each other)**
- **A1 — Copy prompt unconditional (R8) + all-tab reload (F11, client half).**
  - Files: `aitracker/web/app.js`:
    - `openPendingItem` always prepends Copy prompt;
    - `loadSide()` at :1323 reads `X-Server-Started` and calls `location.reload()` when it differs from the first value seen.
  - After: **v3.1 step 12** (same file), or folded into it if step 12 is still open.
  - Test: `tests/test_pending_copy_and_reload.py` (new, node) covers:
    - Copy prompt is present with and without `ExtLaunch`;
    - two polls with different `X-Server-Started` → `location.reload` is called once.
- **A4 — Docs and rules.**
  - Files: `.claude/rules/conventions.md` (D6 verbatim), `README.md` (Update section with the recovery command; "commit or discard local edits first"; auto-install and opt-out; "Windows: untested" per R5), `CLAUDE.md:22` (changed to: "starts on PORT or the next free port; `make stop` first to replace a running one") [F13].
  - No `.gitignore` change [F12].
  - After: v3.1 step 6 (shares README/conventions). **Free** of 11–15.
  - Test: review only.
- **A5 — Server and CLI wiring.**
  - Files:
    - `aitracker/server.py`:
      - in `run()`, the `autoinstall_once` daemon thread after `start_worker()`;
      - `_update_gate`;
      - `GET /api/update`, `POST /api/update/fetch` and `POST /api/update/apply`;
      - `GET`/`POST /api/scheduler` (enum action) [H4];
      - the `X-Server-Started` header at :398;
    - `aitracker/cli.py`: `open_browser` from `TRACKER_NO_BROWSER`;
    - `scripts/bundle.py`: ORDER `… "schedule.py", "pending.py", "update.py", "server.py" …`.
  - After: **v3.1 steps 11 and 15**, because both edit server.py. Sequential with them, and after A3b.
  - Test: `tests/test_update_routes.py` (new) covers:
    - non-loopback → 403 on both POSTs;
    - `Host: evil.example:P` with a matching Origin → 403 [F6];
    - `term_gate` absent from `sys.modules` → 403 [F6];
    - `Host: localhost:P` with no Origin → passes;
    - read-only → 403;
    - GET absent from `_RO_GET_ALLOW`;
    - apply returns 202 before a patched `restart_in_place` runs;
    - extra body keys are ignored;
    - `POST /api/scheduler` with `action` not in {install, uninstall} → 400;
    - `install` calls `sched_install` and `uninstall` calls `sched_uninstall` (both patched);
    - non-loopback → 403;
    - `/api/list` carries `X-Server-Started`;
    - `run()` with `_under_test` patched False and `TRACKER_PENDING_INTERVAL=off` never calls `sched_install` [F8].

    Plus TestBundle: `--version` works, there is exactly one `^def status\(`, and `update_status` is present.
- **A6 — Settings Update block + "Scheduled scan" block [H4].**
  - Files: `aitracker/web/ext_cr_dialogs.js` (Server tab :1393 for Update; Board tab :1314 for Scheduled scan, under v3.1 step 14's rows).
  - After: **v3.1 step 14** (same file). ∥ with A5 (file-disjoint; built against this spec).
  - Test: `tests/test_update_settings_ui.py` (new, node) covers:
    - `reason` rendered verbatim;
    - the button is disabled when `!can_update`;
    - 409 `needs_confirm` → confirm → re-post with `confirm_terminals: true`;
    - a `started_at` change → `location.reload`;
    - a non-null `restart_error` is shown at once;
    - the 60s timeout shows `recover`;
    - hidden when read-only;
    - Scheduled scan: each of the four status texts renders;
    - Install shows when the job is not installed, and Reinstall + Uninstall show when it is installed;
    - each button posts its enum action and re-renders from the response;
    - the block is hidden when `!supported` or read-only.

**Wave A-3b (H2 Host gate)**
- **A8a ∥ — Loopback helper.**
  - Files: `aitracker/util.py` (`is_loopback_host`, `_LOOPBACK_NAMES` moved here), `aitracker/term_gate.py` (`_is_loopback` delegates in one line).
  - After: none. **Free** of 11–15.
  - Test: `tests/test_term_gate.py` (existing; its `_is_loopback` cases must stay green unchanged) plus `tests/test_util_loopback.py` (new): `localhost`, `127.0.0.1`, `::1` and `127.5.5.5` give True; `evil.example`, `0.0.0.0`, `""` and `192.168.1.2` give False.
- **A8b — Global Host gate.**
  - Files: `aitracker/server.py` (top of `do_GET`/`do_POST`, after `_authok`).
  - After: A8a, v3.1 steps 11 and 15, and A5 (all edit server.py; sequential).
  - Test: `tests/test_host_gate.py` (new; the table-driven every-route test described in Part B), including its red-proof.
- **A9 ∥ — Niced scan children** (AD8, if accepted).
  - Files: `aitracker/pending.py` (`_git`/`_gh` argv gets the prefix `["nice", "-n", "10"]` when `os.name == "posix"` and `shutil.which("nice")`).
  - After: v3.1 step 10 (done). **Free** of 11–15.
  - Test: `tests/test_pending_nice.py` (new). The recorded argv starts with `nice -n 10` on posix and has no prefix with `os.name` patched to `nt`.

**Wave P (measurements; after A8b, on the branch, before any landing)**
- **P1–P7** (see Non-functional plan). P1–P3 and P5–P6 are ∥ (read-only, spare ports). P4 runs alone. P7 runs after A3b and A5.

**Wave A-4 (after landing per R4, from the primary checkout; no code)**
- **A7 — Live proof on this Mac.** It merges with v3.1 step 17. Every item is a pass condition:
  1. First `make serve` → the plist appears.
  2. Delete the plist by hand, then `make serve` → it is regenerated.
  3. `make pending-uninstall`, then `make serve` → not reinstalled.
  4. `make pending-install`.
  5. With one in-browser terminal open, push a trivial commit from another clone, then Settings → Check → Update and restart:
     - the confirm appears;
     - after the restart the terminal's `claude` pid is **gone** (`ps`);
     - the same port answers, and a second open tab also reloads;
     - the tunnel (if on) comes back.
  6. Repeat with a dirty tracked file → the refusal text appears.

  Record the results in the Log and in v3.1 section 10.

### Tests summary
New files:
- `test_scheduler_autoinstall.py`;
- `update_fixture.py`, `test_update.py`, `test_update_restart.py`;
- `test_pending_copy_and_reload.py`;
- `test_update_routes.py`, `test_update_settings_ui.py`;
- `test_util_loopback.py`, `test_host_gate.py`, `test_pending_nice.py`;
- plus the T8–T16 files in the Test plan.

Addition: `TestBundle` (A5).

Every test that starts `run()` or the bundle sets `TRACKER_PENDING_INTERVAL=off` and `TRACKER_SCHEDULER_AUTOINSTALL=0`. No test touches the real `~/Library/LaunchAgents`, the real opt-out file, or a network remote; every remote is a temp bare repo.

### Risky spots and fallbacks
1. **Self-restart leaves no dashboard.** Mitigated by:
   - the import + real-config + page-build pre-flight of the exact `target` before the only write;
   - single-flight apply plus the held scan lock;
   - the recovery line printed to the serve terminal and held by the page;
   - the exec-failure path that restarts the tunnel and reports `restart_error`.

   Fallback: `make stop && make serve`, or the recovery command.
2. **Terminals on restart.** `_cloexec_all` guarantees they close instead of being orphaned. The user confirms the N terminals (counted by `_term_live`, which includes `term_run` jobs). Conversations stay resumable.
3. **Auto-install pins a vanishing path.** Mitigated by the worktree/temp/bundle/test guards, and it self-heals on the next serve from a live checkout. The server thread remains a working scanner regardless.
4. **A mid-apply scan cut off by exec.** Prevented by holding `_pending_lock` from apply step 0 to exec.
5. **The global Host gate breaks a legitimate caller.** Missing-Host and credentialed requests are exempt, and the gate applies only to loopback binds. Fallback: set `TRACKER_AUTH`. T6 sweeps the existing Host-sending tests.

### Decisions for the user
Decided by the user (round 3):
- **AD1 — Auto-install: decided (H4).** It installs when the job is missing or its root is gone, and respects an opt-out recorded by the Settings **Uninstall** button. Install, Reinstall and Uninstall are Settings buttons, and the make targets are thin aliases.
- **AD3 — No automatic rollback: accepted (H1).** Pre-flight plus recovery text.
- **AD4 — Update UI in the Control Room Settings only: accepted (H1).**
- **AD5 — Open terminals: decided (H3).** Confirm, then close them.
- **AD6 — DNS rebinding: decided (H2).** All routes get the shared Host gate, now in scope (A8a/A8b).
- **D6 — accepted (H1).**
- **Landing on main** (H5) and **the launchd proof** (H6) are **PARKED** for the user. A7 and v3.1 step 17 wait.

Still open for the user:
- **AD7 — Host-gate breadth.** H2 asked for all local-only routes. The plan puts the gate in the two dispatchers, so it covers **every** route (transcript GETs included, which a rebinding page could otherwise read) whenever there is no credential and the bind is loopback.
  - **Recommended: as planned.** The alternative is to call it only at the listed local-only and terminal call sites, which leaves `/api/session` etc. readable by a rebinding page.
- **AD8 — Scan priority.** **Recommended:** prefix the scan's git/gh children with `nice -n 10` on POSIX (argv prefix, not `preexec_fn`, which is unsafe with threads), and keep the scan strictly sequential, one child at a time. The alternative is no nicing.

### Not grounded / gaps
- **Cross-terminal master inheritance** (known gap, separate ticket) [D-F1]. Terminal B's child inherits terminal A's master across its own `execvp`, so closing A alone never hangs it up. `term_vt` masks this with `killpg`. `_cloexec_all` at update time closes everything, so the update path is unaffected.
- **Host gate vs unusual local setups.** A no-auth, loopback-bound server reached through a custom local hostname (an `/etc/hosts` alias, or a port-forward that rewrites Host) will now get 403. Users with that setup need `TRACKER_AUTH` or a loopback name. Not measured here.
- **uv reinstall command.** The exact command for a `package` install is not verified, so the copy says "reinstall it with uv" generically.
- **SSH under the server's env.** `start_new_session` removes `/dev/tty`, so a passphrase prompt fails fast rather than hanging. Whether the `github-personal` alias fetches non-interactively, with the key in the agent, is unverified until A7.
- **launchd behaviour** (TCC, gh keychain) is unproven until v3.1 step 17 / A7.
- **Old Python with new web files after a failed exec.** The server keeps running (by design), but `build_page` now serves the new `web/*`. `restart_error` tells the user to restart by hand.

### Non-functional plan (H5)
Grounded facts:
- The board/rail poll is 5s (`ext_cr_boot.js`, the `/api/list` interval).
- `GET /api/list` runs `all_sessions()` (`server.py:408`).
- `start_worker()` is a thread start (`pending.py:878–886`).
- `pending._git` and `pending._gh` are synchronous `subprocess.run` (`pending.py:45`, `:61`), so the scan runs **one child at a time**.
- `GET /api/pending` does `_local_caller` + `load_report()` (`server.py:411–417`).
- The inlined page script is about 1.17 MB today (`cat aitracker/web/*.js | wc -c` = 1,171,661).
- The real machine has 479 worktrees and 353 tmp dirs, and a full scan takes about 4 min (measured).

| Aspect | Risk this feature adds | Budget | Measured / tested by |
|---|---|---|---|
| Server start-up | worker thread start; auto-install's `launchctl print`/`bootstrap` | first `GET /` within +50 ms of base; launchctl runs only on its own daemon thread | P1 |
| 5s board poll / `GET /api/list` | none intended; the risk is any pending/scheduler/update call creeping into the list path | p50 and p95 unchanged within ±5% of base; **zero** pending/update/scheduler calls on the list path | P2 (timing) + T16 (patch `pending.scan`/`run_once`/`load_report`/`update_status`/`sched_status` to raise; `/api/list` still 200) |
| `GET /api/pending` | must read the JSON report only, never scan | p50 < 20 ms with a 479-item report; never calls `scan`/`run_once` | P3 + T16 |
| Real scan (about 4 min) | CPU/IO and git processes while the dashboard is in use; gh network | ≤ 1 git/gh child at a time (sequential by construction); children niced +10 (AD8); gh ≤ `GH_MAX_CALLS`=20 and ≤ `GH_BUDGET_S`=120s; `/api/list` p95 during a scan ≤ 1.5× idle p95; scheduled only every `PENDING_INTERVAL` (90d) plus Scan now | P4 |
| Report in the page | `pendingCache` holds the whole report, refetched every 60s (5s while running) | `pending.json` ≤ 1 MB on the real machine; `JSON.parse` ≤ 20 ms | P5 |
| Page-load weight | new code in app.js / ext_cr_board.js / ext_cr_dialogs.js / ext_launch.js inside the one inlined script | ≤ +20 KB total over base `build_page()` length; no new vendored asset | P6 |
| Update restart path | time with no dashboard; reconnect | 202 → new `started_at` visible ≤ 5 s after the pre-flight ends (pre-flight ≤ 90s cap, typically a few seconds) | P7 |
| Sync-ness | apply holds the scan lock; a scan blocks apply with 409 | no request thread ever waits on a scan or a fetch: Scan now, fetch and apply each run on a thread or return a 409 | T10, T13 |

Measurement steps. All run on a spare port with `TRACKER_PENDING_INTERVAL=off` unless noted. Each records base (personal/main) against branch, and writes its numbers to the Log.
- **P1 — start-up.** Script `scripts/perf_startup.py` **(new, dev-only)**: spawn `python -m aitracker` with `PORT=<spare>`, poll `GET /` until 200, 5 runs, print median ms. Run it on base and on branch.
- **P2 — list latency.** Script `scripts/perf_list.py` **(new)**: 50 × `GET /api/list` against the running spare server; print p50/p95. Base vs branch.
- **P3 — pending GET.** Generate a synthetic 479-item `pending.json` into a temp `PENDING_FILE`, then 50 × `GET /api/pending`; p50/p95.
- **P4 — real scan load** (R7 allows one list-only run with gh, from the primary checkout).
  - In one shell: `python -m aitracker --pending --dry-run --json > /tmp/scan.json`, wrapped in `/usr/bin/time -l`.
  - In parallel: `scripts/perf_list.py`, plus a 1 Hz `ps -o pid,comm` sample counting `git`/`gh` children.
  - Record: duration, user+sys CPU, max resident memory, the maximum concurrent git/gh count (must be ≤ 1), the gh call count (≤ 20), and `/api/list` p95 during the scan vs idle.
- **P5 — report size.** `wc -c` of the P4 report, plus a node one-liner timing `JSON.parse` of it.
- **P6 — page weight.** `python -c "from aitracker.page import build_page; print(len(build_page()))"`, base vs branch.
- **P7 — restart.** On the A3a/A3b fixture clone served on a spare port, run apply with a trivial commit. Time from the 202 to the first `GET /api/update` with a new `started_at`.

Cheaper agents (haiku gate-runner) run P1–P3 and P5–P6. P4 and P7 need sonnet, because they need judgment on the output. A budget miss is reported with its number; nothing is "fixed" without a re-plan.

### Test plan (H8)
The repo's evals live inside the unittest suite: `tests/test_tracker.py:2` ("Regression tests + evals") and `tests/test_integration.py:2` ("End-to-end evals across the seams…"). `Makefile:34` runs "unit + evals + server + selfcheck smoke". There is no separate evals directory.

**Existing tests to update.** Found by grep for each anchor this feature changes. Each must be re-run and adjusted only where it pins the old behaviour.
- **T1.** `config.EDITABLE`: `test_selfcheck.py`, `test_cr_routes.py`, `test_cr_tunnel.py`, `test_gateway.py`, `test_job_headline.py`, `test_pending_config.py`. Check none pins the exact key set or length; add the two keys where one does.
- **T2.** `X-Server-Now` / headers: `test_integration.py`, `test_liveness_clock.py`. Add `X-Server-Started`. TestBundle in `test_integration.py` gets ORDER (`schedule`, `pending`, `update`), one `def status`, and `--pending --dry-run`.
- **T3.** `pickDirectory`: `test_term_launch.py`, `test_term_vt_client.py`. These cover the new `prompt` param and the returned promise; existing call sites ignore the return.
- **T4.** `tileId` / `t` key: `test_cr_board_resume_button.py`, `test_cr_readonly_ui.py`. Covers the pending tile id and the `t` key resolved by `focusedTileId`.
- **T5.** `#slist` neighbours: `test_integration.py`, `test_uistate.py`. `#pendside` is inserted above `#slist`.
- **T6.** Host header and loopback: `test_term_gate.py`, `test_term_gate_default.py`, `test_cr_routes.py`, `test_page_bundle.py`, `test_term_launch.py`, `test_tunnel.py`. Any test that sends a non-loopback `Host` without a credential now gets the rebinding 403. Fix the test's Host, or set auth, where that is not the point of the test.
- **T7** (H7). The known load-sensitive `term_vt` backstop failure (memory: "make check flaky term_vt backstop"), and any other timing test that keeps failing in full runs. Replace fixed sleeps with bounded polling waits, keeping the assertion. Each fix is proven by 20 consecutive green runs of that module in isolation **and** 3 full gates.

**New end-to-end tests:**
- **T8 — route matrix** (`tests/test_pending_routes_matrix.py`). Routes: `/api/pending`, `/api/pending/item`, `POST /api/pending/run`, `/api/update`, `POST /api/update/fetch|apply`, `GET/POST /api/scheduler`. Callers:
  - local with no auth;
  - local with a `TRACKER_AUTH` cookie;
  - local without the cookie, when auth is set;
  - a tunnel caller (cf headers) with tunnel creds;
  - a read-only tunnel visitor;
  - a non-loopback `Host`.

  Assert the exact status code in each cell.
- **T9 — one `card`, two renderers** (node). Load app.js and ext_cr_board.js with the same `pendingCache`. The classic `#pendside` and the CR tile show identical title and summary, and `show:false` hides both.
- **T10 — Scan now.** `POST /api/pending/run` returns 202 in < 200 ms with a slow patched `run_once`. A second click while running → 202 `running`, and only one scan ran. In `safe` config nothing is deleted.
- **T11 — Resume + Copy prompt.** The item modal always has both buttons. Resume posts `/api/term/pty` with `cwd=top`, `mode:"new"`, and the server `prompt`. Without `ExtLaunch`, the fallback message appears.
- **T12 — scheduler buttons end to end.** `GET`/`POST /api/scheduler` with `sched_*` patched: the UI round-trips Install → Reinstall → Uninstall, and the opt-out file appears and disappears.
- **T13 — Update refusals over HTTP**, on the fixture clone:
  - dirty, diverged, detached, no upstream, up to date;
  - scan lock held;
  - concurrent apply;
  - terminals open → `needs_confirm`, then success with confirm (restart patched);
  - pre-flight failure → HEAD unchanged.
- **T14 — Host gate, every route.** `tests/test_host_gate.py` (A8b).
- **T15 — new eval** in `test_integration.py`. A realistic fixture machine: 3 repos; worktrees in every verdict; a jobs dir with done/blocked jobs; a scratch tree; a fake gh. A full `scan()` asserts the verdict distribution, `card.summary` text, `would_delete` membership, and that `json.dumps(report)` round-trips.
- **T16 — non-functional guards.** `/api/list` still 200 with pending/update/scheduler functions patched to raise. `GET /api/pending` still 200 with `scan`/`run_once` patched to raise.

## Reconciliation of reviews A + B (main thread, 2026-11-15)

Reviews: `reports/pending-work-worker-review-A.md` (deletion/scanner: 4B/8S/5N), `reports/pending-work-worker-review-B.md` (wiring: 2B/12S/13N). Spot-checked in code: `scripts/bundle.py:41,46` (only `from . import tunnel` special-cased), `providers/claude.py:849` (`list_sessions(limit=200)`), `ext_cr_board.js:3090` (`t` key indexes `boardTiles()` by DOM idx).

| Finding | Verdict | Note / trim |
|---|---|---|
| A-B1 / B-S11 discovery capped at 200 sessions, 1 cwd each | **confirmed** | **Fix trimmed:** repos only need discovering once — `git worktree list` per repo enumerates all its worktrees. So: first cwd of *every* transcript (no limit) ∪ jobs `state.json` cwd/originCwd/worktreePath ∪ `.git` roots found in tmp ∪ sticky `repos[]` from last report. Drop "all cwd lines" and LIVE_SESSIONS_DIR (already covered by transcripts). |
| A-B2 / B-B2 relative `--git-common-dir` | **confirmed** (duplicate) | `--path-format=absolute` + realpath. |
| A-B3 no idle guard | **confirmed** | idle ≥ grace AND no non-terminal job AND no live session under path. |
| A-B4 `worktree remove` deletes gitignored files (.env) | **confirmed** (git docs) | **Fix trimmed:** any ignored file ⇒ not deletable. Drop the "regenerable allowlist" — fail-safe until a real need shows (ponytail). |
| B-B1 bundle can't take `from . import pending` | **confirmed** | named top-level imports; ORDER after registry.py. |
| A-S1 unpushed vs `@{u}` | confirmed | `rev-list --count HEAD --not --remotes`. |
| A-S2 / B-S3 `keep` hides dirty primary/locked | confirmed (dup) | split `verdict` (display) from `deletable`. |
| A-S3 prune orphans detached commits | confirmed | **Fix trimmed:** prune only if every missing entry's HEAD is reachable from a ref, else list as pending; drop `--expire`. |
| A-S4 macOS `/tmp`→`/private/tmp` root check | confirmed | realpath vs realpath. |
| A-S5 git trees in tmp unlisted | confirmed | feed into discovery; never rmtree a tree containing `.git`. |
| A-S6 interval = grace | confirmed | grace = max(interval, 7d). |
| A-S7 lock per checkout | confirmed (many ai-tracker worktrees run) | per-user lock path. |
| A-S8 red-proof can't go red | confirmed | fixtures E–L, one red-proof per guard. |
| B-S1 CLI ignores config.json | confirmed | `apply_overrides(_load_json(CONFIG_FILE))` first. |
| B-S2 card always shows | confirmed | server-owned `card{show,title,summary,count}`. |
| B-S4 `t` key off-by-one | confirmed | resolve by focusedTileId. |
| B-S5 span-2 mobile | plausible | use existing `cr-tile--span2`. |
| B-S6 fetch in `update()` | plausible | SIDE_EXT hook, 60s, skipped read-only. |
| B-S7 worker can die/hot-spin | confirmed | try/except + clamp sleep. |
| B-S8 Scan-now deletes / dry-run postpones clean | confirmed | Scan now = dry-run; `scheduled_at` only on scheduled runs. |
| B-S9 modal re-sync overwrite | plausible | accept. |
| B-S10 Resume cwd inside removable worktree | confirmed | cwd = primary checkout / $HOME; prompt uses `git -C`. |
| B-S12 Safe enable-able via tunnel | confirmed (security) | 403 non-local `PENDING_CLEAN=safe`. |
| Nits A-N1..5, B-N1..13 | accepted | cheap; B's launchd `--if-due` kept only if the snippet ships. |

**Missed by both:**
- **M1** `POST /api/pending/run` must not block the HTTP request (≈80+ worktrees × up to 10s git timeout): kick the scan on a thread, return `202 {running:true}`; card shows "scanning…".
- **M2** The cleaner deletes Claude-owned files (`~/.claude/jobs/<id>/tmp`, `/tmp/claude-<uid>/…`) — a deliberate, user-requested exception to conventions rule 6 ("read-only w.r.t. session logs"). Must be written into `.claude/rules/conventions.md` and never extend to `*.jsonl`, `state.json`, tasks, or file-history.
- **M3** Not examined by either: whether `claude <prompt>` in the `new` PTY path starts an interactive session (vs `-p` print mode) — prove with a one-off manual run in step 1 before wiring the button.

## Reconciliation of review C (v3 delta; main thread, 2026-11-15)

Review: `reports/pending-work-worker-review-C.md` (2B/7S/10N). Its "Clean-plan deltas" 1-10 are the fix list.

| Finding | Verdict | Note / trim |
|---|---|---|
| C-B1 server thread off when plist exists | **confirmed** | Delta 1 as written: both run, `tick()` dedups via the lock + `due()`. |
| C-B2 `schedule.status` collides in the bundle | **confirmed** (bundle flattens; `tunnel.status` exists) | Delta 2 as written. |
| C-S1 lock dir differs launchd vs shell | confirmed | Delta 3: `~/.ai-tracker-pending.lock`. |
| C-S2 `off` means two things | confirmed | Delta 4. |
| C-S3 daily trigger vs strict ≥ threshold | confirmed | Delta 5, `SLACK` in `due()` only (see C-S6). |
| C-S4 tests write the real LaunchAgents plist | confirmed | Delta 6. |
| C-S5 launchd proof can't run as written | confirmed | Delta 7. |
| C-S6 interval does nothing under dry-run; scans run daily incl. gh | **confirmed — fix replaced (overengineered plan, not review)** | The "daily list refresh" was the planner's invention and contradicts the contract ("time for the worker ... in days/months ... controlled by the config") and the user's explicit 90d choice over a 1d option. **Delete the daily list refresh entirely.** One interval governs the whole run (scan + gh + list + clean-per-mode). Freshness between runs = the "Scan now" button and `make pending`. The OS job still fires daily but only executes `--if-due`. Drop delta 8's disclosure copy; Settings copy says "Scan every <interval>". |
| C-S7 gh repo resolution not pinned | confirmed | Delta 9; `-R` derivation stays optional (not built). |
| C-N1..N10 | accepted | as written. |

**Missed by review C:** a 90d default means a new install shows no card until the first run — `due()` already returns True when no report exists, so the first run happens ~60s after first server start; state this in README. Windows path remains planned-but-untested (cannot be proven on this machine) — recorded as a known gap, not discharged.

## Reconciliation of review D (addendum A; main thread, 2026-11-15)

Review: `reports/pending-work-worker-review-D.md` (F1–F15, "Clean-plan deltas" 1–15, and a narrower D6 wording).

| Finding | Verdict | Note / trim |
|---|---|---|
| F1 pty masters survive exec | confirmed (term_vt.py:1657 pty.fork; no cloexec anywhere) | delta 1 as written. |
| F2 scan/clean can start mid-apply | confirmed | delta 2 as written. |
| F3 @{u} resolved twice | plausible | accept, delta 3. |
| F4 exec failure leaves tunnel off | plausible | accept delta 4; `restart_error` is one status field, no new route. |
| F5 ssh can read a passphrase from the serve terminal / orphan ssh | plausible | accept delta 5. |
| F6 DNS rebinding passes both gates | confirmed (server.py:219-229 checks peer + proxy headers only; term_gate.py:47-55 passes when Origin is absent; no Host allowlist) | accept delta 6 for the update routes ONLY. The same hole on the existing terminal routes predates this work: record it under Known gaps and as decision AD6 for the user (fix all local-only routes now vs leave); do not widen this plan's scope unless the user says so. |
| F7 pre-flight skips config overrides and page build | plausible | accept delta 7. |
| F8 `"unittest" in sys.modules` always true | confirmed by logic | accept delta 8. |
| F9 marker misses deleted plist / moved checkout | confirmed — and the reviewer's version fits the user's words ("should always generate the launchd job") better | accept delta 9: store only an explicit opt-out; install when the job is missing or its root is gone; cut the marker, the route and the Reinstall button. This replaces AD1 and AD2; put the resulting behaviour to the user as one decision. |
| F10, F11, F12, F14, F15 | accepted as written. | |
| F13 CLAUDE.md:22 says serve frees the port | confirmed (Makefile:9-10) | accept: correct the CLAUDE.md line in step A4; leave the Makefile. |
| D6 | use the reviewer's narrower wording verbatim. | |

Missed by both: none found beyond AD6.

*Later superseded by round 3:* H2 puts AD6's fix in scope for all routes (A8a/A8b). H4 restores a scheduler status/action route and a Settings "Scheduled scan" block, reversing F9's cut of the route and button. F9's "store only an opt-out; install when missing or root gone" logic stands.

## Log
- 2026-11-15: worktree cut; 4 parallel haiku Explore legs launched to map board, config/jobs, worktree/resume/cleanup wiring, on-disk inventory.
- 2026-11-15: opus plan leg wrote "## Technical plan (v1)" (pending.py core + CLI + server thread, PENDING_INTERVAL/PENDING_CLEAN config, board card, open_pty prompt; D1-D3 recommendations). Awaiting user agreement before code.
- 2026-11-15: opus plan leg wrote "## Technical plan (v2)" from the A+B reconciliation (all confirmed/plausible rows as trimmed, M1-M3, D4 rule-6 exception). v1 marked superseded; the clause table gained a v2 column. Awaiting user agreement before code.
- 2026-11-15: opus plan leg wrote "## Technical plan (v3)" folding U1 (launchd + schtasks via schedule.py), U6 (classic card, shared fetch/modal/Resume), U7 (bounded fail-closed gh + D5), U8 (90d default, grace decoupled to fixed 7d). Windows portability table added. v2 marked superseded; clause table column now v3. Section 7 is 17 steps in 6 waves, with ∥ marks.
- 2026-11-15: opus plan leg amended v3 in place to "## Technical plan (v3.1)" with review-C deltas 1–10 per its reconciliation:
  - the daily list refresh is deleted (one interval, whole run);
  - both triggers run, deduped by `tick()`;
  - `sched_*` names and bundle HEADER `plistlib`;
  - HOME lock;
  - `off` → "off";
  - `SLACK` in `due()`;
  - late-bound plist path;
  - `~/Library/Logs` log;
  - post-landing launchd proof (step 17);
  - gh env strip;
  - nits C-N1..N10.

  Step 7 is split into 7a/7b; the clause table's C2/C7 rows are updated.
- 2026-11-15: opus plan leg recorded "User decisions, round 2" (R1–R8), added clauses C8/C9, and wrote "## Plan addendum A (to v3.1)":
  - part A: `schedule.autoinstall_once` from `run()`, remembered by `~/.ai-tracker-scheduler.json`;
  - part B: `update.py`, `/api/update*` routes, ff-only pull, import pre-flight, `os.execv` restart;
  - D6 network exception;
  - steps A1–A7;
  - decisions AD1–AD5.
- 2026-11-15: opus plan leg amended the addendum to "## Plan addendum A.1":
  - review D deltas 1–15, with the reconciliation table recorded;
  - "User decisions, round 3" (H1–H8) recorded;
  - H2: global loopback-Host gate in `do_GET`/`do_POST` + `util.is_loopback_host`, steps A8a/A8b, every-route test;
  - H4: `GET`/`POST /api/scheduler` + Settings "Scheduled scan" block;
  - Non-functional plan P1–P7 and Test plan T1–T16 added;
  - final steps A2, A3a, A3b, A1, A4, A5, A6, A8a, A8b, A9, P, A7;
  - landing and launchd proof PARKED (H5/H6).
