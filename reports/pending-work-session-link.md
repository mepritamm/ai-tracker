# Pending work: link the session behind each worktree, and resume it with its state

Worktree: `.claude/worktrees/pending-work-session-link`. Branch: `worktree-pending-work-session-link`. Base: `personal/main` @ `9f15bc8`.

## Contract

User's request (verbatim):

> "for the 'pending work' can you also link the session which has created that worktree and upon clicking that worktree and resuming the work, it prompts the session of the work where it was left and what are the changes yet to push and merge, in the tracker app"

- [ ] not discharged

Clauses, so each can get its own verdict later:
- C1. Each Pending-work worktree links the session that created it (clickable into that session's view).
- C2. Opening a worktree item and pressing Resume resumes that session's work (not a new blank session).
- C3. The resumed session is prompted with where the work was left.
- C4. The same prompt says which changes are still to push and to merge.
- C5. All of this happens in the tracker app (classic view and Control Room both).

---

## 1. Original plan (opus planner)

### 1.0 What exists today (read from the code, not assumed)

- **The scan** (`aitracker/pending.py`): `scan()` → `build_ctx()` → `discover_repos()` → `list_worktrees()` → `inspect_worktree()` → `gh_merged()` → `classify()`. Each item dict already carries everything needed for "yet to push / merge": `dirty`, `untracked`, `unpushed` (`rev-list --count HEAD --not --remotes`), `upstream`, `ahead`/`behind` (`HEAD...@{u}`), `base` (`_base_ref`: first of `refs/remotes/*/{develop,main,master}`), `ancestor` (`merge-base --is-ancestor HEAD <base>`), `gh` (squash-merged PR), `missing`. The scan writes these to `pending.json`, and `load_report()` serves them on `GET /api/pending`.
- **Item detail** (`pending.item_detail(item_id)`, `GET /api/pending/item?id=`, local callers only, `server.py:486`): it runs 4 read-only git calls live through `_git_capped` (status, diff stat, diff, `log HEAD --not --remotes`) and returns `{title, when, md, resume:{cwd, prompt}}`. `resume.prompt` is `resume_prompt(item)`, the "Use the worktree-cleanup skill on …" text, sanitised to one line.
- **The Resume button** (`app.js` `openPendingItem` → `pendingResume(r, say)` → `window.ExtLaunch.openAt(r.cwd, "new", r.prompt)` → `ext_launch.js` `pickDirectory`) opens a NEW Claude session at the repo top. It does not resume the session that did the work. "Copy prompt" is always shown.
- **Server-side resume with a prompt already exists.** `term_vt.open_pty` takes `{session, mode:"resume", prompt}`. It builds `term_gate.resume_argv(sid)` and then `_with_prompt(argv, prompt)`. That covers the agent-upgrade path (`term_vt.py:3303`) and Claude only (`_is_claude`). A prompt is dropped if it is over 4000 chars, starts with `-`, or holds a control char. Placement uses `term_gate.place()`: the shell is the repo root and the session runs in the worktree. A removed worktree gets a **409 `{error, recreate:{summary, token}}`**, and the client confirms that through `window.ExtVT.confirmRecreate` (exported, `ext_vt.js:3996`) and re-POSTs with `{recreate: token}` (the `recreate_worktree` exception). If a pane already runs the session, the server returns that tty with `attached: true` and types nothing.
- **No worktree → session reverse map exists.** `term_gate.recorded_run_dir(sid)` maps session → dir, which is the wrong direction and is fed only by the 96 KB tail. `pending.build_ctx` keys `tx` by each transcript's HEAD cwd (`_session_meta(fp)["cwd"]`, first 40 lines) but throws the sid away. Its `jobs` / `job_by_sid` hold `state.json` `worktreePath`/`cwd` plus `sessionId`. Scratch items already use the key `"session"` (a sid string), so the new fields must not use that name.
- **Real log shape**, checked against 266 local transcripts: 65 of them carry `worktree-state` records for 70 distinct worktrees.
  ```json
  {"type":"worktree-state","worktreeSession":{"originalCwd":"…/ai-tracker","worktreePath":"…/ai-tracker/.claude/worktrees/terminal-tab-title","worktreeName":"terminal-tab-title","worktreeBranch":"worktree-terminal-tab-title","originalBranch":"main","originalHeadCommit":"cd8d…","sessionId":"dbf99e3a-…"},"sessionId":"dbf99e3a-…"}
  ```
  A session that **entered an existing** worktree carries `"enteredExisting": true` and no `originalHeadCommit`. A creating session has neither. `worktreeSession: null` means ExitWorktree. Each session repeats the record about 60 times, and the first one appears between line 4 and line 344 (outside `_session_meta`'s 40-line head, and not always inside the 96 KB tail). 10 of the 70 worktrees have more than one session. In 4 cases that is the **same sid stored in two project dirs** (Claude Code copies the transcript into the worktree's project dir), so dedupe by sid. In the other cases a second session later started inside the worktree, with its head cwd set to the worktree. 15 transcripts have a HEAD cwd inside `.claude/worktrees/` with no creation record of their own.
- **Cost check**: scanning every transcript's raw bytes for the substring `"worktree-state"` (814 MB, 266 files, warm page cache) took **1.6 s**. The scan already runs in the worker thread / CLI under `nice`.
- **Where it was left**: the shared detail shape from `registry.parse_any(sid)` (both providers) holds `overview.goal`, `overview.now` (`overview.build_overview`) and `todos`. Using it means no fork per provider.
- **Opening a session from the modal**: the classic view uses `pick(id)` (`app.js:1375`). Control Room uses `ctx.go('detail', id)` (`ext_cr_boot.js:304`), which `window` does not expose. The UI mode is `getUiMode()` (`localStorage 'tracker.ui'`, owned by ext_cr_boot.js).

### 1.1 Design in one paragraph

The **scan** attaches up to 3 linked sessions to every worktree/repo item: `item["sessions"]`, newest first, plus a server-built `item["session_note"]`. The evidence is (a) Claude `worktree-state` records, which also carry created vs entered, (b) any provider's session whose head cwd is inside the worktree, and (c) job `state.json` worktree/cwd → `sessionId`. **Item detail** shows those sessions as "Open session" buttons and adds one read-only git section, the commits not in the base branch. It reads "where it was left" through `parse_any` with a time bound. When a resumable (Claude) session is linked, it returns `resume:{cwd, prompt, session}` with a new work-resume prompt. **The client's** single Resume path (`ExtLaunch.openAt`) gains a `session` option. It then POSTs the existing `{session, mode:"resume", prompt}` form of `/api/term/pty` and handles the existing 409 recreate. With no Claude session linked, everything behaves exactly as today. There are no new routes, no new git writes, no new outbound calls and no conventions amendment (see 1.7).

### 1.2 Files and functions, with signatures

**A. `aitracker/providers/claude.py`** (the provider owns its log parsing)
```python
_WT_CACHE = {}   # path -> ((mtime_ns, size), result)

def worktree_states(path):
    """[(worktreePath, entered: bool)] in first-seen order, one entry per distinct path, from every
    `worktree-state` record in the WHOLE transcript (raw-bytes substring prefilter, json.loads only
    on hit lines). entered = worktreeSession.enteredExisting is truthy. `worktreeSession: null`
    is skipped (ExitWorktree). Memoised on (st_mtime_ns, st_size); [] on OSError."""
```
Implementation: `open(path, "rb")`. For each line, `if b'"worktree-state"' not in line: continue`. Then `json.loads(line.decode("utf-8", "replace"))`. Keep only `o.get("type") == "worktree-state"` with a dict `worktreeSession` that has a non-empty str `worktreePath`. If the same path shows up again, first-seen wins, except that `entered` becomes False if ANY record for that path says created. A session that created the worktree and was later resumed stays the creator.

**B. `aitracker/pending.py`**

1. `from .providers.claude import _pid_alive, _session_meta, worktree_states` (extends the existing import). Also `from .store import _load_json, _save_json, load_titles`.
2. New seam helper, so tests can patch it (the fixture already patches `all_cwds` for the same reason):
   ```python
   def _other_sessions():
       """Session-list rows of every available NON-Claude provider (registry.PROVIDERS, prefix != "").
       Claude evidence comes from build_ctx's own transcript walk (no 200-row limit)."""
       from .registry import PROVIDERS
       out = []
       for p in PROVIDERS:
           try:
               if p.prefix and p.available():
                   out += [r for r in p.list() if isinstance(r, dict) and r.get("id") and r.get("cwd")]
           except Exception:
               pass
       return out
   ```
3. `build_ctx()` gains `ctx["sess"]`: a list of evidence tuples `(rp, sid, how, mtime, first, title, resumable)`, where `how ∈ {"created", "entered", "cwd"}`. The existing loop over `config.PROJECTS` adds the following for each `.jsonl`, deduped by `sid = f[:-6]` and keeping the max mtime:
   - `meta = _session_meta(fp)` (already called). `title = load_titles().get(sid) or meta["title"] or sid[:8]`, loaded once before the loop. `first = meta["first"]`.
   - for `wp, entered in worktree_states(fp)`: `(_rp(wp), sid, "entered" if entered else "created", mt, first, title, True)`
   - if `meta["cwd"]`: `(_rp(meta["cwd"]), sid, "cwd", mt, first, title, True)`

   After the loop:
   - jobs: for `(jp, st)` in `jobs` with a str `st["sessionId"]`: `(jp, st["sessionId"], "cwd", tx_sid.get(sid, 0), 0, title-or-sid[:8], True)`
   - other providers: for each row `r` in `_other_sessions()`: `(_rp(r["cwd"]), r["id"], "cwd", int(r.get("mtime") or 0), 0, r.get("title") or r["id"], False)`. `resumable=False` because `open_pty` refuses resume for non-Claude ids.
4. New pure function, called in `scan()` right after the `for repo in repos.values()` loop (before `gh_merged`):
   ```python
   SESS_MAX = 3

   def attach_sessions(items, ctx):
       """Sets it["sessions"] = [{"id","title","role","resumable","last"}] (<= SESS_MAX, server-ranked) and
       it["session_note"] (one line, "" when none) on every worktree/repo item. Pure given ctx.
       An evidence path belongs to the DEEPEST item path containing it (so a session inside
       <repo>/.claude/worktrees/x is linked to x, never also to the primary <repo>)."""
   ```
   Rules (server policy, rule 5):
   - Ownership: `paths = sorted({_rp(i["path"]) for i in items}, key=len, reverse=True)`. A `created` or `entered` record matches only the item whose `_rp(path) == rp`. A `cwd` record goes to the first `p in paths` with `_under_rp(rp, p)`.
   - Per item, merge the candidates by sid: `created` = any created record, `entered` = any entered record, `last` = max mtime, `first` = min non-zero first.
   - **creator** = the candidate with `created`, earliest `first`. If there is none: for a non-primary item, the earliest-`first` candidate whose evidence is `cwd` (it started inside the worktree), with role "first session here". For the primary checkout there is no creator.
   - **latest** = the candidate with the newest `last`.
   - Rows: `[creator (role "created this worktree" | "first session here"), latest (role "last worked here")]`. If they are the same sid, one row with role "created this worktree · last worked here". If the latest is not resumable but some resumable candidate exists, append the newest resumable one (role "latest Claude session"), so Resume always has a target when one exists. Cap at `SESS_MAX`.
   - `session_note` = `" · ".join("%s: %s" % (role, title[:60]) for row)`. Example: `created this worktree: Fix resume refusal · last worked here: Pending link`.
   - Scratch items (`kind == "scratch"`) are untouched; they already carry `session`.
5. `item_detail(item_id)` changes, only for worktree/repo items (the scratch branch stays as is):
   - **Sessions block** (md, after `**Branch**`): one line per row, `**Session** <role>: <title> (`<id>`)`. Text only: the buttons come from `d["sessions"]` below.
   - **5th git section**, only when `os.path.isdir(path)` and `base` passes `_safe_ref(base)`:
     `("git log --oneline <base>..HEAD", ("log", "--no-color", "--oneline", "HEAD", "--not", base), 50)` appended to `jobs`.
     ```python
     _REF_OK = re.compile(r"[A-Za-z0-9._/-]+\Z")
     def _safe_ref(r):  # base comes from pending.json (app-writable): never let it parse as an option
         return isinstance(r, str) and bool(_REF_OK.match(r)) and not r.startswith("-") and ".." not in r
     ```
   - **Executor**: `max_workers=len(jobs) + 1`. Replace the `with` block with an explicit `ex = ThreadPoolExecutor(...)` / `ex.shutdown(wait=False)` so that the parse below can time out without blocking the response. The git calls are already bounded by `GIT_TIMEOUT` via `_git_capped`.
   - **Where it was left**: `sid = first resumable row id`, else the first row id. Submit `_where_left(sid)` to the same executor and wait with `fut.result(timeout=WHERE_TIMEOUT)`, where `WHERE_TIMEOUT = 5`:
     ```python
     def _where_left(sid):
         """{"goal", "now", "todos": [str]} from the shared detail shape (registry.parse_any), any provider.
         goal/now capped at 300 chars, open todos (status != completed) at 5 x 120. {} on any failure."""
     ```
     On a timeout or exception: `{}`, and the md says `**Where it was left** (session too large to read in time — open it to see)`. Otherwise md gets `**Where it was left** goal: … · now: … · open todos: …`.
   - **Live counts** from the sections already being run: `dirty/untracked` = the lines of `git status --short` (`??` → untracked), `unpushed` = the lines of `log HEAD --not --remotes`, `unmerged` = the lines of the new base section. Each is `None` when its git call failed, and the prompt then falls back to the report value.
   - **Return shape** (additive): `{title, when, md, sessions:[{id,title,role,resumable}], resume:{cwd, prompt, session}}`. `resume.session` = the first resumable row id, or `""`. When `session` is `""`, `prompt` stays `resume_prompt(it)` exactly as today and the existing integration assertions still hold. When it is set, `prompt = resume_work_prompt(it, row, left, live, when)`.
6. New prompt builder (server-owned text):
   ```python
   PROMPT_MAX = 3800   # under term_vt._with_prompt's 4000 cap (it silently DROPS a longer prompt)

   def resume_work_prompt(item, row, left, live, when):
       """One line, no control chars (same regex as resume_prompt), <= PROMPT_MAX: where-left fields
       are trimmed first, then the whole string. Never starts with '-'."""
   ```
   **Exact template.** Segments are joined with a single space, and `{…?}` segments are dropped when empty:
   ```
   Resuming from the tracker's Pending work: worktree {path} (repo {top}, branch {branch}); this session {role}.
   {Where you left off — goal: {goal}; last: {now}; open todos: {t1}; {t2}; ….?}
   Still to do as of {when}: {tree}; {push}; {merge}.
   Re-read CLAUDE.md, confirm with `git -C {path} status --short` and `git -C {path} log --oneline {base}..HEAD`, tell me where the work stands and what is left to commit, push and merge, then ask me before committing, pushing, merging or discarding anything.
   ```
   - `{tree}`: `"{d} uncommitted and {u} untracked files"`, or `"working tree clean"`. When `item.missing`: `"the worktree directory is missing (the tracker offers to recreate it on resume)"`.
   - `{push}`: with an upstream, `"{ahead} commits ahead of {upstream}"` (plus `", {behind} behind"` if behind > 0), or `"in sync with {upstream}"`. Without one, `"no upstream branch; {unpushed} commits on no remote"`. Uses the live `unpushed` when available.
   - `{merge}`: if `gh.state == "merged"`, `"squash-merged as PR #{n} into {gh.base}"`. Else if `ancestor`, `"merged into {base}"`. Else if base, `"not merged into {base} ({unmerged} commits)"`. Otherwise `"no base branch found"`.
   - When base is missing or unsafe, the second git hint becomes `git -C {path} log --oneline HEAD --not --remotes`.

**C. `aitracker/web/ext_launch.js`**: `pickDirectory(raw, mode, prompt, opts)`. The signature string is unchanged, because `test_term_launch.py:724` matches it.
- `if (opts && opts.session) body.session = opts.session;` and `if (opts && opts.recreate) body.recreate = opts.recreate;`. `cwd` stays in the body. The server ignores it on the session form, and the non-empty-path guard is unchanged.
- After the response: `if (res.status === 409 && res.j && res.j.recreate && window.ExtVT && window.ExtVT.confirmRecreate) { window.ExtVT.confirmRecreate(res.j, function (x) { pickDirectory(raw, mode, prompt, Object.assign({}, opts, x)); }); return { ok: false, error: res.j.error, recreate: true }; }` (before the generic error branch).
- `bindTty(res.j.tty, res.j.session || (opts && opts.session) || "")`. The tab URL appends `"&sid=" + encodeURIComponent(...)` when a session is set.
- `if (res.j.attached) toast("Session already open in a terminal", "the resume prompt was not typed — use Copy prompt");`. Otherwise the toast text is `mode === "resume" ? "Resuming session" : …`.

**D. `aitracker/web/app.js`** (the one pending client, shared by classic and Control Room)
- `openPendingList` row: add a third line `const n=document.createElement("div"); n.className="ps pendsess"; n.textContent=it.session_note;` when `it.session_note` is set. It uses `textContent` only.
- `openPendingItem`: for each `(d.sessions||[])` row, append `_pendBtn("Open session: "+row.title, ()=>pendingOpenSession(row.id))`. The label is set through `textContent` inside `_pendBtn`.
- `function pendingOpenSession(id){ closeMsg(); if(window.CR&&typeof window.CR.openSession==="function") window.CR.openSession(id); else pick(id); }`
- `pendingResume(r, say)`: `pr = r.session ? L.openAt(r.cwd, "resume", r.prompt, {session: r.session}) : L.openAt(r.cwd, "new", r.prompt);`. Everything else is unchanged. Copy prompt copies `r.prompt`, which is whichever prompt Resume sends.

**E. `aitracker/web/ext_cr_boot.js`**: one export next to `window.CR.answerSession`:
`window.CR.openSession = function (id) { if (getUiMode() === 'next') go('detail', id); else if (typeof pick === 'function') pick(id); };`

**F. `aitracker/web/app.css`**: `.pendsess` gets a muted, ellipsised style (one rule).

**G. `tests/pending_fixture.py`**: patch `pending._other_sessions` to `lambda: list(self.other)`, with `self.other = []`, and add `"TITLES_FILE"` to the patched config paths. The scan tests then never read the real `~/.augment` or `titles.json`.

**H. `README.md`**: one sentence under Pending work.

### 1.3 Session identification (clause C1)

| Evidence | Source | Role it can earn |
|---|---|---|
| `worktree-state` without `enteredExisting` | `claude.worktree_states(fp)` (full file, memoised) | creator |
| `worktree-state` with `enteredExisting: true` | same | worked here (latest) |
| HEAD cwd inside the worktree | `_session_meta(fp)["cwd"]` | "first session here" (fallback creator), latest |
| job `state.json` `worktreePath`/`cwd` | `build_ctx` `jobs` | latest |
| Auggie / Augment-ext row cwd inside the worktree | `_other_sessions()` via `registry.PROVIDERS` | link only (`resumable: false`) |

- **Several sessions on one worktree**: the creator is the earliest `created` record (by transcript `first` timestamp). The resume target is the **newest** resumable session (max transcript mtime), because that is where the work was actually left. Both are linked (D1).
- **Same sid in two project dirs**: dedupe by sid and keep the max mtime.
- **Primary checkout** items: only `cwd` evidence not claimed by a deeper worktree path. No creator.
- **Auggie**: linked and openable, never the resume target. With only Auggie evidence, `resume.session` is `""`, and Resume keeps today's new-session path.
- **Staleness**: links are as fresh as the last scan, the same as every other pending field. "Scan now" refreshes them. "Where it was left" and the git counts are read live at click time.

### 1.4 "Where left" and "yet to push / merge" (clauses C3, C4)

- **No new git call in the scan.** All push/merge facts already exist on the item (`unpushed`, `upstream`, `ahead`, `behind`, `base`, `ancestor`, `gh`).
- **One new read-only git call**, at click time in `item_detail`: `git --no-optional-locks -C <path> log --no-color --oneline HEAD --not <base>`. It goes through the existing `_git_capped` (`ITEM_GIT_BYTES` 256 KB, `GIT_TIMEOUT` 10 s, `nice`, a scrubbed `GIT_*` env, `GIT_OPTIONAL_LOCKS=0`). It runs in parallel with the 4 existing calls, inside the same request handler that already runs those 4. `base` is validated by `_safe_ref`.
- **Where left**: `registry.parse_any(sid)` → `overview.goal`, `overview.now`, open `todos`, bounded by a 5 s future timeout. No caching beyond the providers' own pass/meta caches.
- **The prompt**: the template in 1.2 B.6, at most 3800 chars, one line.

### 1.5 Resume flow end to end (clause C2)

1. Pending card or Board tile → `openPendingList` → row click → `openPendingItem(id)` → `GET /api/pending/item?id=` (`_local_caller` gate, unchanged) → modal with "Open session: …" buttons, Resume and Copy prompt.
2. Resume → `pendingResume(r)` → `ExtLaunch.openAt(r.cwd, "resume", r.prompt, {session})` → `POST /api/term/pty {session, mode:"resume", prompt, cwd, cols:100, rows:30}`.
3. `term_vt.open_pty`: `term_gate.guard` (TRACKER_TERMINAL + auth + origin), then `_is_claude`, `_background_target` (a parked session runs as its job), `session_cwd(resume=True)`, `term_gate.place`, `resume_argv(sid)`, `_with_prompt`, and finally the folder shell `_inject_argv` or a dedicated pty. The resume refusal backstop still forks if the session is live elsewhere. All of this is unchanged.
4. **Worktree missing**: `place` → 409 `recreate` → `ExtVT.confirmRecreate` → re-POST `{recreate: token}` → `term_gate.recreate_worktree()` (existing exception: one-shot HMAC token, never from a read-only or tunnel request because `recreate_forbidden` refuses it).
5. **Already open**: `attached: true` → that pane is shown, nothing is typed, and a toast points at Copy prompt.
6. A tab opens on `?tty=…&sid=…` through the existing standalone path. That works in both UI modes, as today.
7. **Read-only visitors** never see the modal (`trackerReadOnly` early return), and `/api/pending/item` is local-only.

### 1.6 Sequencing, tests, proof of red

Each step lands with its test. A test counts as proven only after the named line is reverted and the test goes red.

1. **`claude.worktree_states`** (no dependents yet). `tests/test_pending_sessions.py::WorktreeStates` uses a synthetic jsonl in a tempdir with 3 records: created path A, entered path B, `null`, plus a junk line.
   - Assert `[(A, False), (B, True)]`.
   - Then append a created record for B → B becomes `False`.
   - Bump the mtime → the memo refreshes.
   - Red: drop the `enteredExisting` read → the first assertion fails. Drop the memo key's size/mtime → the refresh assertion fails.
2. **`build_ctx` evidence + `attach_sessions` + fixture patch.** `tests/test_pending_sessions.py::Attach` (`@requires_git`, `make_fixture`) writes transcripts under `fx.paths["PROJECTS"]`:
   - (a) S1 created wt `feat`, and S2 is newer and entered it → `sessions[0]` is S1 "created this worktree", `[1]` is S2 "last worked here", and the note names both. Red: swap the order or drop the creator branch.
   - (b) S3's head cwd is in the primary repo and S4's head cwd is in `feat` → the primary item lists only S3, and `feat` lists S4. Red: replace deepest-path ownership with plain `_under_rp`.
   - (c) the same sid in two project dirs → one row. Red: remove the sid dedupe.
   - (d) an `fx.other = [{"id":"auggie:x","cwd":feat,...}]` row that is newer than S1 → an Auggie row with `resumable: false`, plus a "latest Claude session" row. Red: drop the resumable append.
   - (e) only job `state.json` evidence → a row appears. Red: drop the jobs loop.
3. **`item_detail` + `resume_work_prompt` + `_safe_ref`.** Extend `tests/test_pending_item_detail.py`:
   - the existing order test gains the 5th header after the 4 existing ones;
   - with a Claude row, `resume.session == sid`, the prompt is one line and ≤ 3800 chars, and it contains `not merged into origin/main (1 commits)` and `1 uncommitted` (a real fixture worktree with 1 commit and 1 edit);
   - `_where_left` patched to sleep 6 s → the response arrives in under 5.5 s and the md holds the "too large" line;
   - no session → `resume.session == ""` and the prompt equals `resume_prompt(it)` (guards `test_integration.py:2573-2581`);
   - `_safe_ref("-x")`, `_safe_ref("a..b")` and `_safe_ref("")` are all False, and `origin/main` is True.

   Red for each: revert the session branch / the cap / `shutdown(wait=False)` / the `_safe_ref` guard.
4. **`ext_launch.js`.** Extend `tests/test_pending_ext_launch.py` (real file under node):
   - `openAt('/tmp/p','resume','go',{session:'S'})` posts `session:'S'` and `mode:'resume'`;
   - a 409 `{recreate:{token:'T'}}` with a stub `ExtVT.confirmRecreate` that calls retry → a second POST with `recreate:'T'`;
   - `attached:true` → the toast is called.

   Red: remove each added line.
5. **`app.js` + `ext_cr_boot.js`.** Extend `tests/test_pending_ui_classic.py`. `ITEM` gains `sessions:[{id:"S1",title:"T",role:"created this worktree"}]` and `resume.session:"S1"`:
   - `launched == [["/w","resume","…",{session:"S1"}]]`;
   - an "Open session: T" button exists and clicking it calls a stubbed `pick("S1")`;
   - a row with `session_note` renders it via `textContent`;
   - the existing `resume.session` absent case still gives `[["/w","new",…]]`, so the old assertion keeps passing.

   Add an `ext_cr_boot` source assertion in `tests/test_pending_ui_board.py` that `window.CR.openSession` calls `go('detail'`. Red: revert the branch in `pendingResume`.
6. README, then `unset TRACKER_AUTH; make check` (one module per process if it gets OOM-killed), `/branch-sync`, re-green, push to `personal`.

The order is server parse → scan attach → detail/prompt → client launcher → client UI. Each layer's test only needs the one below it, so the scan data exists before anything renders it, and the client never ships ahead of a server field it reads.

### 1.7 Conventions check

- **Stdlib only**: yes. **Shared seam**: links come from every provider (Claude transcripts plus `registry.PROVIDERS` rows), and "where left" uses `parse_any`. **Server owns policy**: roles, ranking, note text, the prompt and the resume target are all server-side, and the SPA only renders them.
- **Read-only w.r.t. logs**: transcripts are only read. **Git**: one more read-only `log` in `pending.item_detail`, the same class as its 4 existing calls. No git write, no `gh`, no network. The resume launch reuses `open_pty` / `recreate_worktree` exactly as their existing exceptions describe. **No exception text needs amending.**
- **The restart rule**: this is a UI and parse change, so `make serve` must be restarted to see it.

### 1.8 Riskiest spot and fallback

**Attribution**: resuming the wrong session. Mitigations:
- the deepest-path ownership rule;
- the created/entered distinction from the real field;
- sid dedupe;
- the role is shown next to every link, so the user sees which session Resume targets before pressing it (the modal says `resume:` in the md line of the target row);
- if the target session has since moved to another worktree, the prompt still names this worktree and uses `git -C <path>`, so it cannot act on the wrong tree.

**Fallback**: with no evidence, behaviour is exactly as today: a new session plus the cleanup prompt, and Copy prompt. A second risk is the cost of the full-transcript `worktree-state` scan on a cold disk. It is memoised per process and runs only in the worker/CLI. If a scan's `duration_s` regresses by more than 3 s, the fallback is to read `_tail_scan(fp)["wt"]` (96 KB tail; its records repeat about 60 times per session) instead of the whole file. That loses only "created vs entered" for very long sessions.

### 1.9 Decisions for the user

- **D1. Resume target.** Recommended: the **newest** Claude session that worked in the worktree, because that is "where the work was left". The creating session is still linked. The literal alternative is to always resume the **creating** session, which means a one-line change in `attach_sessions` ranking.
- **D2. What happens to today's Resume.** For items with a linked Claude session, Resume (and Copy prompt) switch from "new session + worktree-cleanup skill" to "resume that session + work-state prompt". Items without one keep today's behaviour. The alternative is to keep a second button, "Clean up in new session", for the old flow, about 3 lines in `openPendingItem` plus `resume.cleanup_prompt`.

---

## 2. Adversarial review (opus reviewer)

Method: I assumed the plan was wrong and checked every claim against the code (grep plus `sed -n` ranges) and against this machine's real data: 266 transcripts (814 MB) under `~/.claude/projects`, 2,801 subagent transcripts, and the live `aitracker/pending.json` (512 items: 79 pending worktrees, 26 pending primary checkouts). The scripts are in `/tmp/rvw/wt*.py` and `/tmp/rvw/t_parse.py`.

**Claims that held up:** the symbols, routes and line numbers in 1.0 (`item_detail` runs 4 git calls with `max_workers=4`; `server.py:486` has the `_local_caller` gate; `open_pty` handles `{session, mode:"resume", prompt}` through `_with_prompt` with its 4000-char, leading-`-` and control-char rules (`term_vt.py:3119-3127`, `:3300-3305`); the 409 `recreate` branch; the `attached: True` response; `ExtVT.confirmRecreate` is exported at `ext_vt.js:3996`; `pick` is at `app.js:1375`; `go` is at `ext_cr_boot.js:304`; `getUiMode` is in `ext_cr_boot.js:229`; the `pickDirectory` signature is pinned at `test_term_launch.py:724`; scratch items already use the key `"session"` (`pending.py:566`)). The `worktree-state` shape holds too: `enteredExisting`, the `null` ExitWorktree record, `ws.sessionId == file sid` in 3,893 of 3,893 records, and no record that flips between created and entered. Every new git argv is read-only and none touches the enumerated exceptions, so no conventions amendment is needed. That verdict stands.

Severity count: **0 blocker, 4 major, 5 minor, 5 nit.**

**R1 (major): "Where it was left" via `parse_any` is slow and unsafe, and a resumed session does not need it.**
- *Defect.* 1.2 B.5 `_where_left(sid)` runs `registry.parse_any(sid)` inside the `/api/pending/item` request handler with a 5 s `fut.result(timeout=)` and `ex.shutdown(wait=False)`. I measured cold `parse_any` on real transcripts: 64 MB took 4.67 s, **29 MB took 10.05 s**, 26 MB took 3.91 s; warm runs take 0.01–0.04 s. Repro: open a pending worktree whose target session is that 29 MB transcript. Actual: the modal blocks for 5 s and then shows "too large to read in time", while the parse keeps running on an orphaned thread. Each further click before it finishes starts another full parse, and this repo has a history of OOM kills (memory: `full-gate-oom-killed`). The 6 s sleep test adds about 6 s to the gate and is load-sensitive. Content risk: `goal` is the user's last request and `todos`/`now` are imperatives (for example "▶ Push to main"). Retyping them as a fresh user turn ("Where you left off — goal: push and merge…") re-issues old instructions with new user authority. Redundancy: `claude --resume <sid>` (and the `--fork-session` copy) restores that session's whole history, so the session already knows where it left off.
- *Fix direction.* Remove the tracker-derived goal/now/todos from the prompt. The prompt instead tells the session to recap from its own history (C3 is met by the resumed session itself). For the human, the modal md shows one bounded line: the target's `last_text`, read from the mtime-memoised `_session_meta` (≤200 chars, tail-only, already warm from the `/api/list` poll at `claude.py:1007`). It goes in the md only, never in the prompt. Must NOT change: the 4 existing git sections, the `with ThreadPoolExecutor` block, `_git_capped` bounds.
- *Way.* Delete `_where_left`, `WHERE_TIMEOUT` and the executor rewrite. Keep `with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs))`. It must be `len(jobs)` and not the literal 4, because `test_parallel_and_same_output` asserts `dt < 0.6` with a 0.3 s stub, and 5 jobs on 4 workers takes 0.6 s. For the md line: `fp = find_session(sid)` (already glob-sanitised, `claude.py:67`), then `_session_meta(fp)["last_text"]`, wrapped in `_cap`/one line.
- *Test.* `test_pending_item_detail`: a fixture transcript whose user prompt is `SENTINEL-GOAL-PUSH`, created-record for the worktree. Assert `"SENTINEL-GOAL-PUSH" not in d["resume"]["prompt"]` and that the md contains the assistant `last_text`. Red: re-add the goal to the template. Run the existing `test_parallel_and_same_output` unchanged. Red: hard-code `max_workers=4`.

**R2 (major): primary checkouts get linked to arbitrary repo-root sessions.**
- *Defect.* 1.2 B.4 attaches `cwd` evidence to `kind == "repo"` items, so every session whose head cwd is the repo root gets attached. For ai-tracker that is most sessions, and "latest" is the newest root session, usually the live orchestrator. Repro: on this machine, open the `ai-tracker` primary-checkout item (26 such pending items exist). Actual: Resume targets the live session, which returns `attached` and types nothing, or forks a copy of it with a prompt about main's dirty files. Expected: the request is about "the session which has created **that worktree**", and a primary checkout has no creator.
- *Fix direction.* Link only `kind == "worktree"` items. `repo` and `scratch` items keep today's exact output (`resume_prompt`, `"new"`). Keep the deepest-path rule, which now only matters for nested worktrees.
- *Way.* In `attach_sessions`, `targets = [i for i in items if i.get("kind") == "worktree"]`, and `paths` is built from `targets` only. In `item_detail`, the session branch runs only when `it.get("kind") == "worktree"`.
- *Test.* Pure `attach_sessions` test: evidence with a newest `cwd` at the repo root plus the repo item. Assert the repo item has no `"sessions"` and `item_detail(repo)["resume"]["session"] == ""`. Red: drop the kind filter.

**R3 (major): links go stale with a 90-day scan, so D1 "newest" resumes the wrong session.**
- *Defect.* `PENDING_INTERVAL` defaults to `"90d"` (`config.py:504`), and links are computed only at scan time (1.3, "Staleness"). Repro: scan, then keep working in worktree W from a new session S2, then open W. Actual: Resume targets S1, the newest session as of the scan. Expected (D1): S2, where the work was actually left. The creator, by contrast, never changes once found, because it existed before the scan saw the worktree.
- *Fix direction.* Keep the full-file creator evidence at scan time. Recompute the latest session at click time from tail-only evidence, which is already memoised and warm: `_session_meta` plus `_tail_scan`, whose tail `wt` holds the latest worktree-state in **65 of 65** files I measured. Use the same pure ranking function for both. Never run the full-file walk in the request handler.
- *Way.* Add `session_evidence(full)` (see 3.2 B.2). `scan()` calls it with `full=True`. `item_detail` calls it with `full=False`, adds the stored creator row back as a `"created"` tuple, and runs `attach_sessions([dict(it)], ev, paths=<all worktree paths in the report>)`.
- *Test.* `item_detail` freshness: scan a fixture with S1 created in W. Then write S2's transcript (newer mtime, head cwd inside W) without rescanning. Assert `d["resume"]["session"] == S2` and that S1 is still listed as "created this worktree". Red: use only `it["sessions"]` from the report.

**R4 (major): coverage is low, the plan does not say so, and it ignores free evidence.**
- *Defect.* Against the live report, only **8 of the 79 pending worktrees** have any `worktree-state` record, and HEAD-cwd evidence adds 0. Record-level cwd evidence anywhere in a transcript reaches 13, and the union of every source I tried (worktree-state, record cwd, Bash `git worktree add`) is **14/79**. The other 65 have no transcript evidence: transcripts are pruned (the oldest is 108 days), or the worktrees were made outside Claude's worktree tools. The plan reads only HEAD cwd (`_session_meta`, 40 lines), although `_tail_scan` already returns `cwds`, the record-level cwd history (`claude.py:282-289`), at no extra I/O. Repro: a session started at the repo root that later runs inside W, with no EnterWorktree, gets no link.
- *Fix direction.* Add tail `cwds` as `"cwd"` evidence. When no rows exist, the modal says so plainly and Resume keeps today's flow. State the coverage expectation in the README sentence.
- *Way.* In `session_evidence`, for each `d in _tail_scan(fp)["cwds"]`, add `(_rp(d), sid, "cwd", …)`. In the md, with no rows, write `**Sessions** none found in this machine's transcripts (older ones are pruned) — Resume starts a new session.`
- *Test.* A transcript whose head cwd is the repo root and whose last record has `cwd` inside W. Assert W is linked with role "last worked here". Red: drop the tail-`cwds` loop.

**R5 (minor): putting evidence in `build_ctx` repeats the work on every clean step.**
- *Defect.* `build_ctx()` is also called from `_reinspect` (`pending.py:806`), `_prune_repo` (`:853`) and `_remove_tmp` (`:889`), once per removal candidate in `safe` mode. The plan's 1.2 B.3 puts the full-file walk and `_other_sessions()` (each Auggie `list()`) inside it. Active transcripts change between calls, so the memo misses and each re-reads 20–60 MB.
- *Fix direction.* Leave `build_ctx` unchanged and call a separate `session_evidence(full=True)` once from `scan()`.
- *Way.* See 3.2 B.2/B.4.
- *Test.* Patch `pending.worktree_states` with a counter. Run `scan()` once (counter = number of fixture transcripts), then `clean(report, "safe")` with a reclaimable worktree, and assert the counter is unchanged. Red: call it from `build_ctx`.

**R6 (minor): the creator pick is not deterministic for fork lineages.**
- *Defect.* On real data, 2 of 70 worktrees (`job-summary-header`, `agent-map`) have two distinct sids that both carry a *created* record with the same `originalHeadCommit`. That is a fork: Claude copies the records and rewrites `sessionId`. The copied records keep their timestamps, so `first` can tie, and "earliest `first`" then depends on `listdir` order.
- *Fix direction.* Order by `(first or inf, mtime, sid)`, so the older file is the creator.
- *Way.* The `min(...)` key in `attach_sessions`.
- *Test.* Two created tuples with equal `first` and different `mtime`, passed in both orders. Assert the older mtime is the creator. Red: key on `first` only.

**R7 (minor): the prompt mixes stale and live numbers and can promise something that will not happen.**
- *Defect.* 1.2 B.6 combines `ahead/behind/upstream/ancestor` from the scan (possibly 90 days old) with live `unpushed`. For a missing worktree it says "the tracker offers to recreate it on resume". But `place()` uses the target session's own recorded run dir (`term_gate.recorded_run_dir`, `:105-128`, latest worktree-state first). If that session later moved to worktree Y, no recreate is offered for W, so the prompt's claim is false.
- *Fix direction.* Take every count from the 5 live git sections: tree from status, push from `HEAD --not --remotes`, merge from the new `HEAD --not <base>`. Use scan values only when the directory is missing, and label the gh squash-merge "(as of the last scan)". Drop `ahead/behind`. The missing text is just "the worktree directory is missing".
- *Way.* `resume_work_prompt(item, row, live, when)` per 3.2 B.6. `live` holds `None` for a failed call, which falls back to the item.
- *Test.* A fixture worktree with 1 commit pushed to `origin/feat` but not merged. Assert the prompt contains `0 commits on no remote` and `1 commits not merged into` `` `origin/main` ``. Red: read `item["ahead"]`.

**R8 (minor): the prompt can be lost when the session forks or is already open (known gap).**
- *Defect.* `_retry_with_fork` (`term_vt.py:2606-2625`) rebuilds argv from `resume_argv(sid)` without `_with_prompt`. A bg-agent refusal or an in-use fallback therefore opens a copy with no prompt, and `attached: True` types nothing. The agent-upgrade resume has the same gap today.
- *Fix direction.* No `term_vt` change; it would widen the diff into shared terminal code. Document it: the client toast on `attached`, and one md line, "If the terminal opens a copy or an already-open session, paste the prompt with Copy prompt."
- *Way.* The `ext_launch.js` attached toast is already in 1.2 C. Add the md line in `item_detail`.
- *Test.* None (documentation). Note it in the PR as a known gap shared with the agent-upgrade path.

**R9 (minor): agent-isolation worktrees are never linked (known gap).**
- *Defect.* `.claude/worktrees/agent-*` (7 pending here) have no `worktree-state` in any of 2,801 subagent transcripts. The parent records only `toolUseResult.worktreePath`.
- *Fix direction.* No change in this PR. They show "none found". Document it.
- *Way / test.* None. A PR note.

**R10 (nit): git-sourced strings go into the prompt with no data framing.**
- *Defect.* `{path}/{branch}/{upstream}/{base}` are free text. Branch names may legally contain backticks, quotes, `$` and `;`. They are shell-safe (`shlex.join` in `_inject_argv`) but unframed for the model.
- *Fix direction.* Wrap each in backticks with backticks stripped, cap each at 200 chars, and add one sentence saying these values are data. Never put commit subjects in the prompt; the plan already avoids that, so keep it that way.
- *Way.* `_tick(s) = "`" + str(s).replace("`", "'")[:200] + "`"`.
- *Test.* A branch name containing a backtick appears in the prompt without it. Red: drop the replace.

**R11 (nit): extras beyond the request.**
- *Defect.* The job `state.json` evidence is redundant, because a job's sid has its own transcript, and a job with no transcript has nothing to resume. `SESS_MAX` is unneeded, since there are ≤3 rows by construction. The separate "latest Claude session" third row duplicates the resume target, and the new `.pendsess` CSS rule is not needed.
- *Fix direction.* Drop all four. The rows are the distinct values of {creator, latest Claude session = resume target, newest other-provider link}. The list-row note reuses class `ps`, so `app.css` is untouched.
- *Way / test.* Covered by the Attach tests in 3.4.

**R12 (nit): `_other_sessions` duplicates the registry seam.**
- *Defect.* `pending.py` would loop over `registry.PROVIDERS` itself, beside `registry.all_cwds()`, which already does that loop.
- *Fix direction.* Add `registry.other_sessions()` next to `all_cwds()`. `pending` imports it, and the fixture patches `pending.other_sessions`.
- *Test.* The existing `test_pending_cwds` style: a fake provider row with prefix `auggie:` is returned and the Claude provider is skipped.

**R13 (nit): factual slips and one inconsistency.**
- The first worktree-state record appears as late as line **1246**, not 344.
- Only 2 of 70 worktrees have more than one sid in worktree-state records. "10" holds only once cwd evidence is counted.
- 8 (path, sid) pairs are duplicated across project dirs, not 4.
- 1.8 says the target row is marked "resume:", but B.5's md format does not mark it.
- None of these changes the design. *Fix:* mark the target row with ` — Resume target`.

**R14 (nit): more tests pin the old flow.**
- `test_pending_web_contract.py:167` (`launched == [[cwd, "new", prompt]]`) and `test_pending_routes.py:204-207` (`"worktree-cleanup" in prompt`) stay green only because the fixture's `PROJECTS` is empty. Keep it empty in those tests and list them as guards next to `test_integration.py:2573-2581`.
- The classic UI harness finds the Resume/Copy buttons among `bar.children`. Check how it finds them before adding the "Open session" buttons; put those buttons after Copy prompt.

---

## 3. Clean plan (opus reviewer)

### 3.0 Scope
- Links and the session resume apply to **worktree items only** (`kind == "worktree"`).
- `repo` and `scratch` items are byte-for-byte unchanged.
- No new routes, no git writes, no new outbound calls, no conventions amendment. The only new git argv is a read-only `log` in `item_detail`.

### 3.1 Data flow
1. The **scan** (worker or CLI) stores, per worktree item, `item["sessions"]` and `item["session_note"]` from **full-file** evidence. This is where the creator comes from.
2. **Click time** (`item_detail`) re-ranks the same item using the stored rows plus **tail-only** evidence. Tail evidence is memoised and already warm from the `/api/list` poll, so the latest session is always current.
3. The **resume prompt** carries only git state, never transcript text. The resumed session recaps where it left off from its own history.

### 3.2 Files and signatures

**A. `aitracker/providers/claude.py`**
```python
_WT_CACHE = {}   # realpath -> ((st_mtime_ns, st_size), [(worktreePath, entered)])
def worktree_states(path):
    """[(worktreePath, entered)] first-seen order, one per distinct path, over the WHOLE file:
    raw-bytes prefilter b'"worktree-state"', json.loads only on hit lines; worktreeSession null or
    non-dict skipped; entered = bool(enteredExisting), and False if ANY record for that path is a
    create. Memoised on (st_mtime_ns, st_size); [] on OSError."""
```

**B. `aitracker/pending.py`**
1. Imports:
   - `from .providers.claude import _pid_alive, _session_meta, _tail_scan, worktree_states, find_session`
   - `from .store import _load_json, _save_json, load_titles`
   - `from .registry import all_cwds, other_sessions`
2. Evidence:
   ```python
   def session_evidence(full):
       """[(rp, sid, how, mtime, first, title, resumable)], how in {"created","entered","cwd"}.
       Claude: every PROJECTS/*/*.jsonl (same listing as build_ctx), sid = f[:-6], deduped by
       (rp, sid, how) keeping max mtime. full=True adds worktree_states(fp) (scan only);
       always: tail wt (_tail_scan(fp)["wt"], created/entered by enteredExisting), head cwd
       (_session_meta(fp)["cwd"]) and tail cwds (_tail_scan(fp)["cwds"]) as "cwd".
       title = load_titles().get(sid) or meta["title"] or sid[:8] (titles loaded once).
       Other providers: other_sessions() rows -> (_rp(cwd), id, "cwd", mtime, 0, title, False)."""
   ```
   `build_ctx` is **unchanged**.
3. Ranking (pure):
   ```python
   def attach_sessions(items, ev, paths=None):
       """Sets it["sessions"] = rows and it["session_note"] on kind=="worktree" items only."""
   ```
   - **Ownership.** `paths` (default: `_rp` of the worktree items' paths) is sorted longest-first. A `created`/`entered` tuple matches the item whose `_rp(path) == rp` exactly. A `cwd` tuple goes to the first path `p` with `_under_rp(rp, p)`.
   - **Candidates** per item are merged by sid: `created`, `entered`, `last = max mtime`, `first = min non-zero first`, `resumable`.
   - **creator** = the `min` of the created candidates by key `(first or inf, last, sid)`, role "created this worktree". If there is none, the same key over the `cwd` candidates gives role "first session here".
   - **target** (D1) = the resumable candidate with the newest `last`, role "last worked here". With D1 = creator, it is the creator if that is resumable.
   - **other** = the newest non-resumable candidate, if it is newer than the target, role "worked here (Auggie)" or that provider's source label.
   - **Rows** are the distinct values of [creator, target, other]. Each row is `{id, title, role, resumable, first, last, target: bool}`. When creator and target are the same sid, the roles are joined with " · ".
   - **`session_note`** = `" · ".join("%s: %s" % (role, title[:60]))`.
4. `scan()`: right after the inspect loop, before `gh_merged`, call `attach_sessions(items, session_evidence(full=True))`.
5. `item_detail(item_id)`. The scratch and repo branches are unchanged. For `kind == "worktree"`:
   - **Fresh rows.**
     - `ev = session_evidence(full=False)`, plus one tuple per stored row: `"created"` for a creator row, else `"cwd"`, carrying the row's own first/last and `rp = _rp(path)`.
     - `cur = dict(it)`; `attach_sessions([cur], ev, paths=[_rp(i["path"]) for i in r["items"] if i.get("kind") == "worktree"])`.
     - `rows = cur.get("sessions") or []`, `tgt = next(row for row in rows if row["target"] and row["resumable"])` or None.
   - **md** (after `**Branch**`):
     - One `**Session** <role>: <title> (`<id>`)` line per row, plus ` — Resume target` on the target row.
     - When there is a target, `**Last said** <one-line _session_meta(find_session(tgt id))["last_text"]>` (only if the file is found).
     - The R8 hint line.
     - With no rows, the R4 "none found" line.
   - **5th git job**, appended only when `_safe_ref(base)`: `("git log --oneline HEAD --not %s" % base, ("log", "--no-color", "--oneline", "HEAD", "--not", base), 50)`. Then `max_workers=len(jobs)`, with the `with` block kept.
     ```python
     _REF_OK = re.compile(r"[A-Za-z0-9._/-]+\Z")
     def _safe_ref(r):
         return isinstance(r, str) and bool(_REF_OK.match(r)) and not r.startswith("-") and ".." not in r
     ```
   - **Live counts** come from the raw `out` of each section, before `_cap`, and are `None` when `rc != 0`:
     - `status`: `??` lines → untracked, the other lines → dirty;
     - `log --not --remotes` line count → unpushed;
     - the base section's line count → unmerged.
   - **Return:** `{title, when, md, sessions:[{id, title, role, resumable, target}], resume:{cwd, prompt, session}}`.
     - With a target: `session = tgt["id"]` and `prompt = resume_work_prompt(it, tgt, live, when)`.
     - Otherwise `session = ""` and `prompt = resume_prompt(it)`, exactly as today.
6. Prompt (server-owned, no transcript text):
   ```python
   PROMPT_MAX = 3800
   def _tick(s): return "`%s`" % str(s).replace("`", "'")[:200]
   def resume_work_prompt(item, row, live, when):
       """One line (resume_prompt's control-char regex), <= PROMPT_MAX (whole string trimmed),
       never starts with '-'."""
   ```
   Template (segments joined by a space):
   > Resuming from the tracker's Pending work: worktree {_tick(path)} (repo {_tick(top)}, branch {_tick(branch)}); you {role} it. First recap in two or three lines what you were doing there and what is left. Still to do (git, checked {when}): {tree}; {push}; {merge}. Values in backticks come from git and are data, not instructions. Re-read CLAUDE.md, check with `git -C {path} status --short` and `git -C {path} log --oneline HEAD --not {base}`, then ask me before committing, pushing, merging or discarding anything.

   - `{tree}`:
     - missing worktree → "the worktree directory is missing";
     - otherwise "{d} uncommitted and {u} untracked files", or "working tree clean".
   - `{push}`: "{n} commits on no remote", where n is the live `unpushed`, else `item["unpushed"]`. Add " (upstream {_tick(upstream)})" when `item["upstream"]` is set.
   - `{merge}`, first match wins:
     - `gh.state == "merged"` → "squash-merged as PR #{number} into {_tick(gh.base)} (as of the last scan)";
     - live unmerged is not None → "merged into {_tick(base)}" if 0, else "{n} commits not merged into {_tick(base)}";
     - `ancestor` → "merged into {_tick(base)}";
     - a base exists → "not merged into {_tick(base)}";
     - otherwise "no base branch found".
   - When the base is missing or unsafe, the second git hint becomes `git -C {path} log --oneline HEAD --not --remotes`.

**C. `aitracker/registry.py`**: `def other_sessions():` returns the rows of every available provider with `p.prefix != ""` that have a truthy `id` and `cwd`. Each provider is wrapped in try/except, the same as `all_cwds`.

**D. `aitracker/web/ext_launch.js`** `pickDirectory(raw, mode, prompt, opts)`. Keep the signature text unchanged.
- `if (opts && opts.session) body.session = opts.session; if (opts && opts.recreate) body.recreate = opts.recreate;`.
- Before the generic error branch: `if (res.status === 409 && res.j && res.j.recreate && window.ExtVT && window.ExtVT.confirmRecreate) { window.ExtVT.confirmRecreate(res.j, function (x) { pickDirectory(raw, mode, prompt, Object.assign({}, opts, x)); }); return { ok: false, error: res.j.error, recreate: true }; }`.
- `bindTty(res.j.tty, res.j.session || (opts && opts.session) || "")`.
- The tab URL gets `&sid=` when a session is set.
- `if (res.j.attached) toast("Session already open in a terminal", "nothing was typed — use Copy prompt")`; otherwise toast `mode === "resume" ? "Resuming session" : …`.

**E. `aitracker/web/app.js`**
- `pendingResume`: `pr = r.session ? L.openAt(r.cwd, "resume", r.prompt, {session: r.session}) : L.openAt(r.cwd, "new", r.prompt);`.
- `openPendingItem`: after Copy prompt, one `_pendBtn("Open session: " + row.title, () => pendingOpenSession(row.id))` per `d.sessions` row.
- `function pendingOpenSession(id){ closeMsg(); if(window.CR&&typeof window.CR.openSession==="function") window.CR.openSession(id); else pick(id); }`.
- `openPendingList` row: a third `div` with `className="ps"` and `textContent=it.session_note` when it is set.

**F. `aitracker/web/ext_cr_boot.js`**: next to `window.CR.answerSession`, `window.CR.openSession = function (id) { if (getUiMode() === 'next') go('detail', id); else if (typeof pick === 'function') pick(id); };`.

**G. `tests/pending_fixture.py`**: patch `pending.other_sessions` to `lambda: list(self.other)` (`self.other = []`) and add `"TITLES_FILE"` to the patched config paths.

**H. `README.md`**, one sentence under Pending work: "A worktree's item links the Claude session that created it and the one that last worked there (when this machine still has their transcripts). Resume reopens that session with what is left to commit, push and merge."

**Dropped from section 1:**
- `_where_left` / `WHERE_TIMEOUT` and the executor rewrite;
- job `state.json` evidence;
- `SESS_MAX`, the "latest Claude session" third row, and the `.pendsess` CSS (`app.css` is untouched);
- linking repo items;
- evidence inside `build_ctx`.

### 3.3 Sequencing
1. `claude.worktree_states`.
2. `registry.other_sessions`.
3. `pending.session_evidence` + `attach_sessions` + the `scan()` call + the fixture patch.
4. `item_detail` + `_safe_ref` + `resume_work_prompt`.
5. `ext_launch.js`.
6. `app.js` + `ext_cr_boot.js`.
7. README.

Then `unset TRACKER_AUTH; make check` (one module per process if it gets OOM-killed), `/branch-sync`, re-green, and push to `personal`. Each layer reads only fields that the layer below has already shipped.

### 3.4 Tests: each is proved by reverting the named line and watching it go red

1. **`tests/test_pending_sessions.py::WorktreeStates`** (as in 1.6 step 1). Red: drop the `enteredExisting` read, or drop size/mtime from the memo key.
2. **`::Attach`** (pure: synthetic `ev` tuples and item dicts, so no git and fast). Red for each in brackets:
   - (a) creator S1 plus a newer entered S2 give roles and order as in 1.6 (a) [swap the order];
   - (b) a newest root `cwd` gives the repo item no rows (R2) [drop the kind filter];
   - (c) a `cwd` under a nested worktree goes to the deepest one [plain `_under_rp`];
   - (d) the same sid twice gives one row [remove the dedupe];
   - (e) fork tie: equal `first`, the older mtime wins in both input orders (R6) [key on `first` only];
   - (f) an `auggie:x` row newer than the target becomes a link-only row with `resumable: false`, and the target stays Claude [drop the resumable filter on the target].
3. **`::Evidence`** (`make_fixture`, transcripts under `fx.paths["PROJECTS"]`). Red for each in brackets:
   - a later-record `cwd` inside W links W (R4) [drop the tail `cwds` loop];
   - `session_evidence(full=False)` never calls `worktree_states` [call it unconditionally];
   - `clean(report, "safe")` leaves the `worktree_states` counter unchanged (R5) [move the call into `build_ctx`].
4. **`tests/test_pending_item_detail.py`**. Red for each in brackets:
   - the order test gains the 5th header after the 4 existing ones, and `test_parallel_and_same_output` stays green [hard-code `max_workers=4`];
   - a created transcript gives `resume.session == sid`, a one-line prompt of ≤3800 chars, and the prompt contains `1 uncommitted` and `not merged into` [revert the session branch];
   - `SENTINEL-GOAL-PUSH` is not in the prompt, and `last_text` is in the md (R1);
   - freshness: a newer S2 written after the scan becomes the target without a rescan (R3) [use stored rows only];
   - pushed-but-unmerged gives `0 commits on no remote` and `1 commits not merged` (R7) [read `item["ahead"]`/`ancestor`];
   - a backtick in the branch is stripped (R10);
   - no session gives `resume.session == ""` and `prompt == resume_prompt(it)`;
   - a repo item gives `resume.session == ""` (R2);
   - `_safe_ref` is False for `-x`, `a..b` and `""`, and True for `origin/main`.
   - Guards that must stay green unchanged: `test_integration.py:2573-2581`, `test_pending_routes.py:204-207`, `test_pending_web_contract.py:167`.
5. **`tests/test_pending_ext_launch.py`** (as in 1.6 step 4): the session POST, the 409 → retry with `recreate:'T'`, the `attached` toast. Red: remove each added line.
6. **`tests/test_pending_ui_classic.py` / `test_pending_ui_board.py`** (as in 1.6 step 5, minus the CSS): a resume launch with `{session:"S1"}`, the Open session button calling a stubbed `pick`, the note rendered via `textContent`, and the old `"new"` case unchanged; plus a source assertion that `window.CR.openSession` calls `go('detail'`. Red: revert the `pendingResume` branch.

### 3.5 Riskiest spot and fallback
- **Attribution (resuming the wrong session).** Mitigations: worktree items only; created/entered taken from the real field; the R6 tie-break; the latest session computed at click time; the target row labelled "Resume target" before the user presses Resume; `git -C <path>` in the prompt, so a session that has moved elsewhere still acts on this tree. Fallback: with no rows, the behaviour is exactly as today.
- **Click-time cost.** `session_evidence(full=False)` is about 266 stats plus memo hits in a warm server. On a cold process (no `/api/list` poll yet), the first call parses heads and tails: about 25 MB, well under a second. Fallback: if this is ever measured above 1 s, `item_detail` uses the stored rows only (one `if`). `duration_s` covers the scan-time full walk (1.6–1.8 s warm, measured).

### 3.6 Decisions for the user, after review
- **D1 is unchanged.** Recommended: the newest Claude session that worked in the worktree, now computed at click time (R3), so it is genuinely where the work was left. The creator is still linked. Alternative: always resume the creator. That is the literal reading of the request; it is a one-line change to the `target` choice.
- **D2 is unchanged.** It is still the switch to "resume that session + work-state prompt" for items with a linked session.
- **New, for sign-off:**
  - **D3. Where-left content.** Recommended: the prompt asks the resumed session to recap from its own history, and the modal shows the target's last line (R1). Alternative: section 1's tracker-built goal/now/todos digest, at the cost of a 4–10 s cold parse and old instructions being re-issued.
  - **Scope.** Primary checkouts are not linked (R2).
  - **Coverage.** Only about 14 of 79 current pending worktrees have transcript evidence on this machine (R4).

---

## 4. Reconciliation (main thread)

Spot-checked against the code: `config.py:504` returns `"90d"` (R3); `build_ctx()` is called at `pending.py:765/806/853/889` (R5); `_retry_with_fork` builds its argv from `resume_argv(sid)` with no `_with_prompt` (R8). The reviewer's measurements (cold `parse_any` 4–10 s; 8 of 79 worktrees have a worktree-state record, 14 of 79 with every evidence source combined) are accepted as measured on this machine.

| # | Verdict | Note |
|---|---|---|
| R1 | **confirmed** | The resumed session has its own history, so a tracker-built digest is slow and re-issues old instructions. Drop it (D3). |
| R2 | **confirmed** | A primary checkout has no creator. Link worktree items only. |
| R3 | **confirmed**, fix depends on D1 | Needed only if D1 = newest. If D1 = creator, the creator never changes and the click-time re-rank can be dropped (smaller diff). |
| R4 | **confirmed** | Tail `cwds` costs no extra I/O. The "none found" line is required because coverage is low. |
| R5 | **confirmed** | Verified 4 call sites. Keep `build_ctx` unchanged. |
| R6 | **confirmed** | One sort-key change. |
| R7 | **confirmed** | Live counts beat scan-time counts, which can be up to 90 days old. |
| R8 | **confirmed; known gap, no change** | Shared with the agent-upgrade resume. Document it in the PR and in the modal hint. |
| R9 | **confirmed; known gap, no change** | Agent-isolation worktrees show "none found". |
| R10 | **confirmed** (nit) | Backtick framing is cheap prompt-injection hygiene. |
| R11 | **confirmed** | Drop job evidence, `SESS_MAX`, the third row and the new CSS. |
| R12 | **confirmed** (nit) | The provider loop belongs in `registry`. |
| R13 | **confirmed** (nit) | Factual slips; the design is unchanged. |
| R14 | **confirmed** (nit) | Keep the fixture `PROJECTS` empty in the old-flow guards. |

**Overengineered fixes cut:** none beyond R3's conditional above. `ext_cr_boot.js` `CR.openSession` stays, because Pending work also opens from the Control Room UI, and a button that does nothing there would be a bug.
**Missed by both:** nothing material. One note: the prompt's "ask me before committing, pushing, merging or discarding" is a deliberate safety line, not part of the request. It is kept, and the user may drop it.

**Implementation basis:** section 3 (the clean plan), with the D1/D2/D3 answers applied. If D1 = creator: in `item_detail`, use the stored `it["sessions"]` and skip `session_evidence(full=False)`; the R3 freshness test is dropped and replaced by "the creator is the target".

### Sign-off status
- [ ] D1 resume target: newest session (recommended) / creator
- [ ] D2 replace "new session + worktree-cleanup" for linked items (recommended) / keep both buttons
- [ ] D3 prompt asks the session to recap (recommended) / tracker-built digest
- No code until signed off (rule 8).

## 5b. Implementation review — client (opus)

Scope: `ext_launch.js` pickDirectory, `app.js` pendingResume / openPendingItem / pendingOpenSession / openPendingList, `ext_cr_boot.js` CR.openSession, and the three client test modules. Counts: 0 blocker, 1 major, 3 minor, 4 nit.

**Checked and clean (no finding):**
- XSS: session titles, roles and `session_note` reach the DOM only through `textContent` (`_pendBtn`, the new `.ps` div). The md goes through `mdBlock` → `md()` → `esc()` first.
- No unbounded 409 loop: every retry needs a fresh user confirm, and a stale token makes `term_gate.place` return a new plan, not a silent loop.
- The recreate token, session, prompt and mode are all forwarded through `Object.assign({}, opts, x)`.
- `bindTty` prefers the server's `res.j.session`, which is the bound or job id and matches the grants that `term_vt` adds on both `attached` paths (`term_vt.py:3343-3347`, `3469-3475`).
- Existing callers are unaffected: the sidebar picker (`ext_launch.js:261/266/268`, opts undefined), the Log in dialog (`ext_cr_dialogs.js:1647`, gateway/tab), and `ext_cr_term.js`, which has its own `_pickDirectory`. The signature text is intact (`test_term_launch` 101/101).
- `node --check` passes on all three files and on the concatenated `app.js` + sorted `ext_*.js` bundle.
- Open session is not host-gated, and it routes in both UI modes.
- The client reads exactly what `pending.py:1371-1373` returns: `sessions[{id,title,role,resumable,target}]` and `resume{cwd,prompt,session}`. Scratch and repo items carry no `session`, so they fall through to today's `openAt(cwd,"new",prompt)`.
- Test modules pass one per process: ext_launch 1/1, ui_classic 15/15, ui_board 7/7.

**C1 (major): a 409 recreate during Resume shows "Resume failed", and the retry's outcome is dropped.**
- *Defect.*
  - `ext_launch.js:353-356` returns `{ok:false, error, recreate:true}` right after `confirmRecreate` and discards the promise of the retry `pickDirectory(...)`.
  - `app.js:2408` treats any `ok===false` as a failure.
- *Repro.*
  - Setup: a pending worktree item whose directory is missing (prunable) and has a linked Claude target.
  - Resume makes the server 409 with `{recreate}`, and the confirm dialog appears.
  - The user presses OK. The worktree is recreated (a git write) and a tab opens.
  - Actual: the modal still reads "Resume failed: Worktree `…` was removed…". If the retry itself fails (429 too many terminals, "worktree recreated but not usable", a 403 recreate on read-only), nothing is shown at all, because `showPickerError` (`ext_launch.js:314`) is a no-op without `#cwderrmsg`.
  - Expected: no "failed" message while the confirm is pending, and the retry's real result shown in the modal.
- *Fix direction.*
  - The caller must learn the retry's result.
  - Do NOT change the `pickDirectory(raw, mode, prompt, opts)` signature text, the return shape `{ok:false,error,recreate:true}` (pinned by the test), or `ExtVT.confirmRecreate`.
- *Way.*
  - `ext_launch.js:354`: `function (x) { var p = pickDirectory(raw, mode, prompt, Object.assign({}, opts, x)); if (opts && typeof opts.onResult === "function") p.then(opts.onResult); }`. `onResult` is never copied into `body`, and nested 409s recurse with it.
  - `app.js:2407-2408`: pass `{session:r.session, onResult:x=>{ if(x&&x.ok===false&&!x.recreate) say("Resume failed: "+(x.error||"unknown error")); else if(x&&x.ok) say(""); }}`.
  - In the `.then`, handle `x&&x.recreate` first with `say("Confirm recreating the worktree to resume")` before the `ok===false` branch.
- *Test.*
  - `test_pending_ext_launch.py`: pass `onResult` in the 409 call, set the retry reply to `{status:429, j:{error:'too many'}}`, call `out.retry({recreate:'T'})`, and assert that `onResult` got `{ok:false, error:'too many'}`. Red today: it is never called.
  - `test_pending_ui_classic.py`: mock `openAt` to resolve `{ok:false, recreate:true, error:'gone'}` and assert that the `.pendmsg` text does not start with "Resume failed". Red today.

**C2 (minor): the "already open, nothing was typed" notice (R8's mitigation) is invisible in Control Room mode.**
- *Defect.* `ext_launch.js:369` reports `attached` only through `toast()`. `toast()` writes into `#toasts` (`app.js:1647`), which `setUiMode('next')` hides (`ext_cr_boot.js:228` CLASSIC_SIBLINGS, `ext_cr_boot.css:158` `display:none !important`; also noted at `ext_cr_boot.js:1137`).
- *Repro.* In 'next' mode, take a pending item whose target session is already in a tracker terminal and press Resume. The server answers `attached:true` and the tab opens with no prompt typed. Actual: no message anywhere, since `pendingResume` sees `{ok:true}`. Expected: a visible "nothing was typed — use Copy prompt".
- *Fix direction.* Surface `attached` in the modal's own `.pendmsg`, which is visible in both modes. Keep the toast. Do NOT change the `{ok:true}` shape for non-attached opens (the existing test asserts `{"ok": True}` exactly).
- *Way.*
  - `ext_launch.js:388`: `return res.j.attached ? { ok: true, attached: true } : { ok: true };`.
  - `app.js:2408` `.then`: `if(x&&x.attached) say("Session already open in a terminal — nothing was typed; use Copy prompt");`.
- *Test.*
  - ext_launch harness: capture the attached call's result and assert `{ok:true, attached:true}`.
  - Classic harness: mock `openAt` to resolve `{ok:true, attached:true}` and assert the `.pendmsg` text contains "nothing was typed".
  - Both are red today.

**C3 (minor): the retry test passes when the retry drops the prompt and mode.**
- *Defect.* `test_pending_ext_launch.py:113-115` asserts only `recreate` and `session` on `calls409[1]`.
- *Repro (run).* Replace `ext_launch.js:354` with `pickDirectory(raw, "new", null, …)` in a copy and run `OpenAt` against it: OK, the mutant survives.
- *Fix direction.* Test only.
- *Way.* Add `self.assertEqual(o["calls409"][1]["prompt"], "go")`, `self.assertEqual(o["calls409"][1]["mode"], "resume")`, and `self.assertNotIn("recreate", o["calls409"][0])`.
- *Test.* The mutant above goes red.

**C4 (minor): the Open-session buttons overflow the bar in a narrow window and push the status message out of view.**
- *Defect.* `app.css:644` `.pendbar{display:flex}` has no `flex-wrap`, and `.pendbtn` is `white-space:nowrap` (`app.css:649`). The flex items' `min-width:auto` keeps them at their full text width.
- *Repro.* `app.js:2428` adds up to three "Open session: <full title>" buttons; titles come from titles.json or the AI/custom title and are unbounded. At a window width under about 700px, Resume, Copy prompt and two titled buttons exceed the width of `.msgbody`. `.msgbody` scrolls horizontally (`overflow:auto`, `app.css:388`), and `.pendmsg` (where "Resume failed…" appears) sits off-screen. The route is loopback-only, so this affects narrow and split desktop windows, not phones.
- *Fix direction.* Let the bar wrap and bound the label. Do NOT change the button order (Resume, Copy prompt, Open session…, msg) or the `"Open session: "+title` prefix the harness finds.
- *Way.*
  - `app.css:644`: add `flex-wrap:wrap`.
  - Optionally, in `app.js:2428`, cap the label at 40 characters with "…" and set `b.title` to the full title.
- *Test.* `test_pending_ui_classic.py`: `re.search(r"\.pendbar\{[^}]*flex-wrap:\s*wrap", app_css)`. Red today.

**C5 (nit): the Open-session buttons don't say which role each one is.**
- *Defect.* `app.js:2428` labels with the title only. A creator and a "last worked here" session with the same title (a fork, or identical AI titles) give two identical "Open session: T" buttons, and nothing in the bar marks which one is the Resume target.
- *Fix direction.* Expose the role without changing the label prefix.
- *Way.* After `_pendBtn(...)`, set `btn.title = row.role + (row.target ? " — Resume target" : "")`. This is the `title` attribute (textContent-safe), not innerHTML.
- *Test.* Classic harness: assert that the "Open session: T" element's `title` is "created this worktree — Resume target".

**C6 (nit): the CR.openSession test is a regex that pins neither branch.**
- *Defect.* `test_pending_ui_board.py:141-144` only asserts that `go('detail'` appears. The mutants `getUiMode() !== 'next'` and dropping the `pick(id)` fallback both pass.
- *Fix direction.* Test only.
- *Way.* Also assert `"getUiMode() === 'next'"` and `"pick(id)"` in `m.group(0)`.
- *Test.* Both mutants go red.

**C7 (nit): stale comments in `ext_launch.js` now contradict the code.**
- *Defect.* These comments are out of date:
  - `:323-326` says mode is "cwd" or "new" (session-less only);
  - `:339` says "first prompt for a `new` session";
  - `:373-376` says "`sid` is deliberately omitted", but `:384` now adds it;
  - `:397-398` says "open a session-less terminal".
- *Fix direction.* Comments only.
- *Way.* Say that a `session` in opts switches to the session-scoped form (the server ignores `cwd`), and that `&sid=` is added when a session is set.
- *Test.* None.

**C8 (nit, cross-scope, for §5a): the prompt says the worktree is missing even when this Resume recreates it.**
- *Defect.* `resume_work_prompt` writes "the worktree directory is missing" when it is built, but C1's confirm path then recreates that directory before claude starts.
- *Repro.* A prunable item with a target, Resume, then OK. The resumed session is told that a now-existing directory is missing.
- *Fix direction.* Wording only, in `pending.py`'s `{tree}` branch.
- *Way.* Use "the worktree directory was missing at {when} (Resume may have recreated it — check `git status`)".
- *Test.* In `test_pending_item_detail`, assert the new phrase for a missing-path item.

## 5a. Implementation review — server (opus)

Scope: `providers/claude.py` (`worktree_states`, `_WT_CACHE`), `registry.other_sessions`, `pending.py` (`session_evidence`, `attach_sessions`, the `scan()` call, `_safe_ref`, `_tick`, `resume_work_prompt`, `item_detail`), the fixture and the server tests. Every finding below was reproduced. Throwaway repros are in `~/.claude/jobs/78d1ccfd/tmp/rv-server/` (`test_rv.py` A–G, `test_rv2.py` H, `t1.py` timing, `t_wt.py`, `t_vac.py`). They fail today as quoted.
Green as shipped (one module per process): `tests.test_pending_sessions` (11), `tests.test_pending_item_detail` (11), `tests.test_integration.TestPendingWorkEndToEnd`. The R5 guard `test_clean_does_not_walk_transcripts` is not vacuous: a mutant `build_ctx` that calls `worktree_states` turns it red (3 != 2).
Checked and clean:
- No transcript text reaches the prompt. Only `role`'s "created" substring is used, never the title or `last_text`.
- The prompt is one line, and nothing in it can start with '-'.
- Argv stays inside the conventions. The only new argv is the read-only `log … --not <base>`, gated by `_safe_ref`.
- The fork tie, nested deepest-owner, kind filter, dedupe and Auggie link-only row behave as specified. On real data, `job-summary-header` (two creators with equal `first`) picks the older mtime.
- The `/api/term/pty` resume path ignores `cwd` when `session` is set, and it returns `attached` and the 409 `recreate` that the client relies on.

**S1 — major — a stored row whose transcript has since been deleted is still the Resume target.**
- *Defect.* `pending.py:1316-1321` re-adds every stored `it["sessions"]` row with its scan-time `resumable`. `attach_sessions` then picks it as the target although the file is gone. Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default), while the scan runs every 90 days, so this happens often.
- *Repro.* `test_rv.py::test_A`: scan with S1, `os.remove(S1.jsonl)`, then `item_detail`. Actual: `resume.session == "S1"`. The client posts `mode=resume`, `term_gate.session_cwd` returns "", and `/api/term/pty` answers 404 "session not found". The user loses both the resume and the old cleanup flow that D2 replaced. Expected: `session == ""` and `prompt == resume_prompt(it)`, with no row for S1.
- *Fix direction.* At click time, only a Claude session whose transcript exists can be a row or the target. Do NOT change `attach_sessions` (it is pure), and do not touch non-Claude rows.
- *Way.* In the stored-row loop at `pending.py:1316`, `continue` when `":" not in str(row["id"]) and find_session(row["id"]) is None`. That is at most 3 globs, so it is cheap.
- *Test.* In `test_pending_item_detail`, add `test_deleted_transcript_falls_back_to_old_flow` (the repro above). Assert `out["sessions"] == []` and the old prompt. It is red today.

**S2 — major — every click re-reads all 266 transcript tails and evicts the `/api/list` poll's tail memo.**
- *Defect.* `pending.py:286` calls `_tail_scan(fp)` for every `PROJECTS/*/*.jsonl` on the request path. `_TAIL_MEMO` is a FIFO capped at `_TAIL_MEMO_MAX = 256` (`claude.py:99`). This machine has 266 transcripts, and cycling 266 keys through a 256-slot FIFO gives a 0 % hit rate. So the plan's "≈266 stats plus memo hits" does not hold, and each click also flushes the entries that the 2 s list poll needs.
- *Repro.*
  - `t1.py` against the real `~/.claude`: `session_evidence(full=False)` takes 2.28 s cold, then 0.39 / 0.52 / 0.40 s warm. Counting `_tail_scan_raw` calls on a warm run gives **266**.
  - `test_rv.py::test_C`: with `_TAIL_MEMO_MAX` patched to 2 and 3 transcripts, the second unchanged call does 3 raw reads (expected 0).
- *Fix direction.* Give the evidence its own per-file memo, keyed on `(st_mtime_ns, st_size)`, so an unchanged transcript costs one stat. Do NOT raise `_TAIL_MEMO_MAX` (it moves the cliff), and do not change `_tail_scan`.
- *Way.* In `pending.py`, add `_EV_MEMO = {}  # fp -> (sig, (cwd, tuple(cwds), wt_or_None, first, meta_title))` and `def _tx_evidence(fp)`. It does `os.stat`, returns the cached tuple when the sig matches, and otherwise calls `_session_meta` and `_tail_scan` once and stores the tuple. `session_evidence` calls it in place of lines 286-292's direct reads. After the walk, drop the keys that were not seen in this listing, so the memo stays bounded by the real file count. `titles.json` stays read per call.
- *Test.* `test_pending_sessions::Evidence::test_unchanged_transcripts_cost_no_tail_read` is `test_C`: patch `claude._TAIL_MEMO_MAX = 2` and wrap `claude._tail_scan_raw` with a counter. The second `session_evidence(full=False)` must make 0 calls. It is red today (3).

**S3 — minor — a squash-merged prompt says "PR #?" and the wrong base.**
- *Defect.* At `pending.py:1268` the code reads `gh["pr"]` as a dict. `gh_merged` (`pending.py:763-764`) stores `{"state":"merged","pr":<url str>,"number":N,"base":baseRefName}`, so the result is always `#?`, and the base falls back to the item's base.
- *Repro.* `test_rv.py::test_B`: `gh={"state":"merged","pr":"https://x/pull/42","number":42,"base":"main"}`. Actual: "squash-merged as PR #? into `origin/main`". Expected: "PR #42 into `main`".
- *Fix direction.* Read the real shape. Keep the dict branch only if an older report could carry one; nothing writes one.
- *Way.* `merge = "squash-merged as PR #%s into %s (as of the last scan)" % (gh.get("number") or "?", _tick(gh.get("base") or base or "?"))`.
- *Test.* In `test_pending_item_detail`, add `test_squash_merged_prompt_names_pr` (test_B). It is red today.

**S4 — minor — repo (primary checkout) items now run and show a 5th git section.**
- *Defect.* At `pending.py:1344` the `_safe_ref(base)` job is outside the `kind == "worktree"` branch. A repo item's md gains `**git log --oneline HEAD --not origin/main**` and an extra subprocess. This contradicts §3.0 ("repo items byte-for-byte unchanged") and §3.2 B.5, which scopes the job to `kind == "worktree"`.
- *Repro.* `test_rv.py::test_D`: the repo item's md contains that header.
- *Fix direction.* Gate on the kind. Worktree items keep the job.
- *Way.* `if it.get("kind") == "worktree" and _safe_ref(it.get("base")):`.
- *Test.* `ItemDetailSessionResume::test_repo_item_never_gets_a_session` additionally asserts `"--not origin/main**" not in out["md"]`. It is red today.

**S5 — minor — the prompt stamps live git counts with the scan's date.**
- *Defect.* `resume_work_prompt(it, tgt, live, when)` at `pending.py:1370` receives `when` = `report.generated_at`, which can be up to 90 days old. "(git, checked {when})" then labels counts that were computed seconds ago. The resumed session is told the state is stale when it is not, or it trusts an old date. The plan's template has the same slip, so both missed it.
- *Repro.* `test_rv2.py::test_H`: `generated_at = 400 days`, then an untracked file is added. Actual: "checked 1971-02-05 05:30): 0 uncommitted and 1 untracked files". The 1 untracked is live.
- *Fix direction.* Stamp the time the counts came from. The gh clause already says "as of the last scan" and stays as it is.
- *Way.* In `item_detail`, pass `time.strftime("%Y-%m-%d %H:%M") if live else when`. `resume_work_prompt` is unchanged. This composes with §5b's missing-dir wording, which uses `when` for the missing case.
- *Test.* test_H in `test_pending_item_detail` asserts the scan year is not in the prompt. It is red today.

**S6 — minor — a truncated `_git_capped` output undercounts live counts, and the undercount beats the correct scan count.**
- *Defect.* `pending.py:1360-1367` counts lines of output that `_git_capped` cut at `ITEM_GIT_BYTES` (256 KB), and it still returns rc 0. For a local-only repo, `HEAD --not --remotes` is the whole history, so a branch with more than about 4k commits, or more than about 5k status entries, reports a smaller live number than `item["unpushed"]`.
- *Repro.* `test_rv.py::test_F`: `ITEM_GIT_BYTES` patched to 200, with 31 unpushed commits. Actual: "12 commits on no remote". Expected: 31 (the scan count).
- *Fix direction.* When the output may be truncated, use no live count, so the scan value is used. Do not add a new git argv.
- *Way.* At the top of the `if rc == 0:` block, `if len(out.encode("utf-8", "replace")) >= ITEM_GIT_BYTES: continue`. Leaving the count as None falls back to the item.
- *Test.* `test_F` in `test_pending_item_detail`. It is red today.

**S7 — minor — the `worktree_states` memo thrashes past 512 transcripts and re-reads every whole file on every scan.**
- *Defect.* At `claude.py:335` the cache is a FIFO with 512 slots. With N > 512 transcripts, each cyclic walk misses on every file. That is a full read of every byte: 3.4 GB in `~/.claude/projects` here, at 266 files today.
- *Repro.* `t_wt.py`: 513 files, then a second unchanged pass re-opens **513** files. The expected count is 0.
- *Fix direction.* Bound the cache by the files that exist, not by a constant.
- *Way.* Drop the 512 pop. In `session_evidence(full=True)`, after the walk, prune the `claude._WT_CACHE` keys that are not in the current listing's realpaths. This is the same prune as S2's `_EV_MEMO`.
- *Test.* In `test_pending_sessions::WorktreeStates`, write 513 tiny files, call twice, and count `open` on the second pass: it must be 0. It is red today.

**S8 — nit — a base ref that is also a path in the worktree makes the 5th job fail.**
- *Defect.* At `pending.py:1346`, `git log … --not origin/main` exits 128 ("ambiguous argument: both revision and filename") when the worktree holds `origin/main` as a path. The section shows "(git failed)", and the live unmerged count is lost.
- *Repro.* `test_rv.py::test_G`.
- *Fix.* Append `"--"` to that argv tuple only. The header text and the other four jobs are unchanged.
- *Test.* test_G. It is red today.

**S9 — nit — the command hints embed the raw path, unquoted and with backticks kept.**
- *Defect.* At `pending.py:1279` and in the template, `git -C %s` uses the raw `path`. A space breaks the suggested command, and a backtick breaks the "values in backticks are data" framing (R10).
- *Repro.* `test_rv.py::test_E`: path `/tmp/a b\`c` gives "`git -C /tmp/a b\`c status --short`".
- *Fix.* Use `qp = shlex.quote(str(path).replace("`", "'"))` in both hints. `_tick(path)` stays the display.
- *Test.* test_E. It is red today.

**S10 — nit — a NUL in a later-record `cwd` or a `worktreePath` makes the whole scan raise.**
- *Defect.* `_rp()` raises `ValueError: embedded null byte` (`os.path.realpath`) at `pending.py:293-297`, and nothing catches it, so `scan()` dies. A NUL in the head `cwd` already crashes `build_ctx` (same as base). The new surface is the tail `cwds` and `worktreePath`.
- *Fix.* `continue` on any string containing "\x00" before `add(_rp(...))`, in both loops.
- *Test.* A transcript whose second record has `"cwd": "/a\u0000b"`. `session_evidence(full=True)` must not raise. It is red today.

**S11 — nit, no change — the old-flow integration guard was edited.**
- *Finding.* §3.4 listed `test_integration.py:2573-2581` as "must stay green unchanged". It now asserts `session == "sess-unpushed"` / "1 commits on no remote" instead of "1 unpushed". This is an expected consequence: that fixture has a transcript in the worktree, so D2 applies.
- *Coverage.* The no-session old flow keeps unit coverage through `test_no_session_keeps_the_old_prompt`.
- *Direction.* No change. Note it in the PR.
- *Related nit.* `WorktreeStates` proves only the size half of the memo key; an mtime-only change is untested. Add one `os.utime` bump with the same size.

Counts: 0 blocker, 2 major (S1, S2), 5 minor (S3–S7), 4 nit (S8–S11).

---

## 6. Reconciliation of the implementation review (main thread)

The gate before the fixes: 164 of 165 modules were green. `tests/test_term_vt_client.py:2936` pinned the old `bindTty(res.j.tty, "")` text in `ext_launch.js`. That is an **expected** consequence: the call now binds `res.j.session || (opts && opts.session) || ""`, the same pattern `ext_vt.js` uses. The guard's expected text was updated, and its module now passes (4/4).

| # | Verdict | Fixer note |
|---|---|---|
| S1 | confirmed (major) | Apply as written. |
| S2 | confirmed (major) | Apply the separate `_EV_MEMO` in `pending.py`. Do NOT change `_TAIL_MEMO_MAX`, because the list poll's cache must stay its own. |
| S3–S6 | confirmed | Apply as written. |
| S7 | confirmed | Prune to the files that exist; drop the 512 pop. |
| S8–S10 | confirmed (nit) | Apply as written. |
| S11 | confirmed, no change | Note it in the PR or commit body. |
| C1 | confirmed (major) | Apply the `opts.onResult` way. |
| C2–C3 | confirmed | Apply as written. |
| C4 | confirmed | One `flex-wrap` rule in `app.css` is allowed, overriding §3's "app.css untouched", because this is a real overflow. |
| C5–C7 | confirmed (nit) | Apply as written. |
| C8 | confirmed | The server fixer owns it, because it changes the prompt text in `resume_work_prompt`. |

Overengineered fixes cut: none. Missed by both: none found.
