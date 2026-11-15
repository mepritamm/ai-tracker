# Pending-work worker — durable plan file

Branch: `worktree-pending-work-worker` (worktree `.claude/worktrees/pending-work-worker`), base `personal/main` @ b3d6230.
Opened 2026-11-15. Status: **planning — no code until the user agrees the plan (CLAUDE.md rule 8).**

## Contract (verbatim)

> I want you to create a job/worker which runs and list all the pending work lying in the worktrees across all different sessions, the time for the worker must be adjusted in '__' days/months and that needs to be managed and controlled by the config setup, if any pending items list up and that piece of information must be displayed right into the main board, in a separate specific card with different color, since thats the intelligence of the app, clicking on that session will show the content which has pending work uncommitted or not pushed into the real code. And it comes up with a resume button which opens up a claude session from which the action can be performed utilise the 'cleanup' skill. and make sure that the worker is smartly deleting all the pending items/tmp files from disk for the sessions that dont need right now. For the deterministic part of the work have some scripts ready into the app, which runs regardless of the local claude session, the claude session only runs when the person really wants to take a look and getting it done

Follow-up: "If I want to implement this, how should I plan this"

## Clauses

| # | Clause | Verdict (code: none yet) | What v2 would discharge |
|---|---|---|---|
| C1 | Worker/job lists pending work in worktrees across all sessions | not discharged | v2 plans it: discovery from all transcripts, jobs, tmp and sticky repos; primary/locked work is shown. Gap: first-cwd-only coverage is unmeasured (section 10). |
| C2 | Worker interval in days/months, controlled by config | not discharged | v2 plans it: `PENDING_INTERVAL` (`7d`/`2w`/`1m`); the CLI honours config.json. |
| C3 | Pending items shown on main board as a separate, differently-coloured card | not discharged | v2 plans it for the Control Room board (violet, server-owned `card`). Classic view gets no card. |
| C4 | Clicking shows the uncommitted / unpushed content | not discharged | v2 plans it: live status, diff and unpushed log in the modal. |
| C5 | Resume button opens a Claude session that uses the `cleanup` skill | not discharged | v2 plans it: the prompt invokes worktree-cleanup then cleanup. It depends on the step-0 proof (M3). |
| C6 | Worker safely deletes stale pending items / tmp files for sessions not needed | not discharged | v2 delivers deletion **only once the user picks Safe delete**; the default is dry-run. It needs the D4 rule-6 exception. |
| C7 | Deterministic part = scripts in the app, runs without a Claude session; Claude only on demand | not discharged | v2 plans it: `pending.py` + CLI + daemon thread; Claude runs only on Resume. |

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

## Technical plan (v2)

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

## Log
- 2026-11-15: worktree cut; 4 parallel haiku Explore legs launched to map board, config/jobs, worktree/resume/cleanup wiring, on-disk inventory.
- 2026-11-15: opus plan leg wrote "## Technical plan (v1)" (pending.py core + CLI + server thread, PENDING_INTERVAL/PENDING_CLEAN config, board card, open_pty prompt; D1-D3 recommendations). Awaiting user agreement before code.
- 2026-11-15: opus plan leg wrote "## Technical plan (v2)" from the A+B reconciliation (all confirmed/plausible rows as trimmed, M1-M3, D4 rule-6 exception). v1 marked superseded; the clause table gained a v2 column. Awaiting user agreement before code.
