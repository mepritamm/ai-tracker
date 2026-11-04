# Session-switch cache — technical plan

Branch `plan/session-switch-cache` (worktree `.claude/worktrees/session-isolation`), base `personal/main`. Plan only: no code until the user agrees.

## Contract (verbatim)

> I would like to understand is there any way of using the system cache where we store the recent session's data and that feeds into when we switch from 1 session to the another ?
>
> that means when we switch from 1 session to the other, the session shows stale data for the time being and then refreshed with the live data automatically
>
> using browser cache or system cache
>
> create a technical plan with some runs of adversial review with opus agent, and discuss the plan

Standing requirement from the same thread (session isolation work, `docs/session-isolation.md`):

> There shouldnt be any stale and each session needs to be idempotent with no data leakage between the sessions within the app.

| Clause | Verdict |
|---|---|
| C1 Plan covers using browser and/or system cache to feed a session switch | not discharged |
| C2 Plan states exactly what the user sees on a switch, including how stale | not discharged |
| C3 Opus-authored technical plan | not discharged |
| C4 More than one run of opus adversarial review | not discharged |
| C5 Plan discussed with the user before any code | not discharged |
| C6 No leakage between sessions; each session idempotent | not discharged |

## Known facts (measured or read 2026-11-04 on `personal/main` f43e04e)

- The switch cache today is a JS `Map` in page memory: `SESS_CACHE`, 8 entries, `app.js:1415`. Lost on reload, one per tab.
- The server keeps metadata and agent-file caches in process memory (`_META_CACHE`, `_AGENT_CACHE` in `providers/claude.py`). It does not cache the full session-detail result.
- `/api/session` sends no `ETag` or `Last-Modified`. `no-store` is only on the page HTML and login (`server.py:332, 378`).
- Only the selected session is polled, so a cached snapshot is as old as the user's last look at that session.
- Server parse time, 12 most recent sessions: first parse median 88ms, worst 1554ms; second parse median 31ms, worst 623ms. Payload median 47KB, worst 433KB. Network and render time were not measured.

## Plan
_Authored by the opus plan agent against f43e04e. Line numbers read with grep + `sed -n`; treat them as ±5 because other sessions edit these files._

### P0. The answer in plain words

1. **The biggest cost in a switch is not a cache miss.** In the dashboard view, `pick()` re-renders the whole sidebar (1006 sessions) synchronously, which blocks the browser for about 200ms on every switch, including cache hits. Fix that first.
2. **Add one server cache, in process memory, holding only what is a pure function of one transcript file's bytes.** Validate it against `stat` on every request and recompute everything else per request. An unchanged session then answers in single-digit milliseconds (the reviewer measured a hit at median 2.6ms, worst 19.7ms) with data that is really current, so nothing stale needs showing.
3. **Keep the page-memory `Map` and make its snapshot honest.** Give it an age limit and a visible label, and strip terminal handles from it. Separately, the server refuses a note action whose note has moved since the list on screen was drawn, which protects fresh data as well. It shows only when fresh data is slow, which is the changed-session or remote case.
4. **No browser persistence, no HTTP cache, no on-disk cache, no prefetching.** Each one costs more than it gives on the evidence below.

### P1. Measurements

Setup: real logs, 1006 sessions. Scratch servers ran on spare ports with no tunnel and no endpoint file, POST and `/api/term/*` refused, stopped by PID afterwards. Browser: headless Chromium through Playwright, in both real views, switching among the 5 most recent Claude sessions and 2 Auggie sessions, one warm-up pass first. Runs were sequential unless noted. The machine had 7 live sessions running, so numbers are noisy; read them as sizes, not benchmarks.

"Prototype cache" is a scratch monkeypatch: `parse_session` wrapped in a stat-keyed pickle. It shows the likely size of the win only, and **the control board rows are not a result**: the round-1 reviewer's board baseline came out at 72ms and 247ms medians, not 218ms, so the board gain is proven only by the step 4 re-measure (P6). It is **not** the design in P3 (it does not recompute live fields, so it must never ship). Its numbers are cache **hits**.

**Time to data on screen, ms, median / worst**

| Dashboard view | No snapshot: fresh data painted | Snapshot: first paint | Snapshot: fresh data painted |
|---|---|---|---|
| Today | 290 / 374 | **270** / 343 | 352 / 628 |
| + selection-only sidebar | 199 / 707 | **31** / 71 | 183 / 749 |
| + sidebar + prototype cache | **67** / 106 | 33 / 63 | 122 / 294 |

| Control board detail view | No snapshot: fresh data painted | Snapshot: first paint | Snapshot: fresh data painted |
|---|---|---|---|
| Today | 218 / 1006 | 106 / 185 | 187 / 1180 |
| + prototype cache | 125 / 193 | 98 / 192 | 120 / 226 |
| + sidebar + prototype cache | **70** / 177 | 60 / 127 | 89 / 156 |
| Today, emulated link (150ms, 10Mbit/s) | 265 / 1488 | 112 / 193 | 275 / 2093 |
| + prototype cache, same link | 225 / 494 | 101 / 176 | 245 / 700 |

**Where a switch goes today**

| | Dashboard (290ms) | Control board (218ms) |
|---|---|---|
| `renderSide()` inside `pick()`, blocks paint | 185–250ms, **about 68%** | 45–70ms, even though the sidebar is hidden |
| Server parse (time to first byte) | median 42ms, **about 14%** | median 157ms, **about 72%**, worst 954ms (one run; not reproduced in round 1) |
| Body transfer | 0.4ms on loopback; 140–200ms on the emulated link | same |
| Detail `render()` | median 19ms, worst 40ms | median 36ms, worst 104ms |

In the dashboard view the existing snapshot gives nothing today: it is painted into the DOM, then `renderSide()` holds the frame for 200ms, and the fresh response has usually arrived by then.

**Server side, 12 most recent Claude sessions, median / worst ms**

| | Result |
|---|---|
| First parse in a server's life | 121 / 4617, of which agent files 86 / 3202 (already cached after that by `_AGENT_CACHE`) |
| Later parse | 48 / 691 |
| of which the transcript loop | 30 / 428 |
| of which `parse_shells`, a **second full scan of the same file** | 17 / 248 |
| Everything a cache hit must still do (agents, tasks, jobs, sibling agents, shell output) | 3.8 / 11.4 |
| `pickle.loads` / `pickle.dumps` / `copy.deepcopy` of a full result | 0.11 / 0.40, 0.12 / 1.46, 0.42 / 2.00 |
| Pickle size | 33KB / 393KB; all 12 together 0.9MB |
| Auggie parse (largest three files, 12.7MB worst) | 66–183; recent sessions 20–48 |

**Other facts measured**

- Cycling 12 sessions through the 8-entry `Map` gave **0 hits out of 12** (sequential flooding of an LRU). Round 2 pointed out that this is an artefact of a fixed-order cycle, not evidence about real use, so the size stays at 8. 14 sessions had been written in the last 30 minutes.
- 7 of 1006 sessions were live, and 2 of the 12 most recent changed in one 60-second sample. That is a single sample, not a rate.
- A live session grew from 1MB to 5.9MB during this work and its parse went from about 25ms to 200–900ms (regex `findall` in the loop). A session that is being written always misses, so live sessions stay at today's cost. Garbage collection was tested as a cause and ruled out.
- Page reload to first detail: 1.3–1.9s on loopback, 2.8–4s on the emulated link. `start()` awaits `/api/list` (886KB) before `track()` (`app.js:1386-1389`).
- `JSON.parse`: 0.1ms at 47KB, 0.7ms at 433KB. IndexedDB read: 0.5–17ms at 47KB, 1.5–44ms at 433KB. sessionStorage read and parse: 0.2ms and 1.5ms.

**Not measured:** a real tunnel (I was told not to start one, and Cloudflare's edge compression may shrink the body time), a real phone, and the P3 split itself (a hit's server time of about 4–12ms is predicted from the parts above, not observed).

### P2. Layer verdicts

| Layer | Speeds up | Costs | Changes what the user sees? | Verdict |
|---|---|---|---|---|
| Sidebar update in `pick()` (not a cache) | Every switch: 200ms dashboard, 50ms board | Small diff | **Yes**, the largest single dashboard win, and it is what lets a snapshot paint at all | **Do first** |
| Page-memory `Map` | First paint on a revisit | Heap only; gone with the tab | **Yes**, on changed sessions and remote links | **Keep at 8 entries, harden** |
| Server pass cache, stat-validated, in memory | Parse time on any unchanged session, also the 2s poll and `/api/narration` | About 25 lines plus a mechanical split of `parse_session`; memory bound | **Yes**, predicted from the prototype; not claimed until the step 4 re-measure | **Do** |
| Server cache of the **full detail** dict | Same, minus about 4–12ms | Its inputs are a dozen-plus files plus the clock (P5), and checking them all costs about what it saves; one forgotten input is silent staleness | No more than the pass cache | **No** |
| IndexedDB | Reload only (saves part of 1.3–1.9s, and only after reordering boot) | Transcripts at rest in the browser; reverses decision P7.2 of `docs/session-isolation.md`; needs clearing, but no logout exists; multi-tab writes; schema versioning | Only on reload; the contract is about switching | **No** |
| sessionStorage | Reload in that one tab | Transcripts at rest; 5MB quota; synchronous | Same | **No** |
| localStorage | Reload, shared across tabs | The above, plus synchronous across all tabs | Same | **No** |
| HTTP cache, ETag/304 | Body bytes only: 0.4ms on loopback, about 140ms on the emulated link | `now` and agent durations change every response, so the ETag must exclude them or never match. It still parses unless backed by the pass cache. Keeps the body in the browser's disk cache, which JS cannot clear | Not on loopback. Small remotely, and the snapshot already covers that time | **No**, and send `no-store` (P4.5) |
| On-disk server cache | First parse after a restart only (121 / 4617ms); restarts are rare | **Conflicts with conventions rule 6** (app-writable state stays in `flags.json`/`titles.json`); a second copy of transcripts on disk; pickle files would be an unpickling risk; schema versioning | Only the first switch after a restart | **No** |
| Prefetching likely-next sessions | First visit in a tab | Background parses competing for the GIL for sessions never opened; to keep snapshots under the 5-minute limit it must re-fetch about 14 sessions continually; live sessions miss anyway | Marginally, after the pass cache | **Not now**; re-measure after P6 step 3 |

The user asked about "browser cache or system cache". The answer: **both, in memory only**. The browser keeps a bounded snapshot `Map` and the server keeps a pass cache.

### P3. Server design: the pass cache

**Why a pass, not the detail dict.** `parse_session` lines 1608–1878 read only `open(path)`, with no clock, no config and no other file (checked by grep and an `ast` walk, including the 9 helpers it calls transitively). Everything after line 1879 reads other files or the clock. Splitting there makes "which fields may be cached" true by construction, the same shape `_agent_file_pass` + `_agent_entry` already use (`claude.py:1116, 1258`).

**`aitracker/util.py`, new** (add `pickle, threading` to its imports):

```python
_PASS_CACHE = {}                    # (kind, path) -> (stat key, pickled bytes); dict order = LRU
_PASS_CACHE_LOCK = threading.Lock() # guards get/set/evict only, never a parse
_PASS_CACHE_BYTES = 0
PASS_CACHE_MAX_BYTES = 32 * 1024 * 1024

def file_pass(kind, path, fn):
    """fn(path) must be a pure function of this one file's bytes: no clock, no config, no other
    file. Returns a fresh object every call, so callers may mutate it. Raises what os.stat raises."""
```

Behaviour, in order:

1. `AITRACKER_NO_PASS_CACHE` set (read late, same as `_agent_cache_on`) → return `fn(path)`.
2. `st = os.stat(path)` **before** reading. A write during `fn` then leaves a key older than the data, so the next call misses. The reverse order would pin stale data until the next write.
3. Key: `(st.st_mtime_ns, st.st_size, st.st_ino)`. The inode catches a rewrite that preserves mtime and size.
4. Hit: touch LRU under the lock, `pickle.loads` outside it, return.
5. Miss: `out = fn(path)`, then `pickle.dumps(out, -1)`. On `(pickle.PicklingError, TypeError, AttributeError, RecursionError)`, return `out` uncached (fail open). The list is deliberately narrow (round-2 m3): a broad `except` would also swallow the `NameError` a bundle without `pickle` raises, and the cache would silently never work. Under the lock: pop any existing entry for `(kind, path)` and **subtract its length** from `_PASS_CACHE_BYTES`, insert the new one and add its length, then evict oldest until under the byte bound. Return `out`. Every change to the counter happens under the lock, in the same critical section as the dict change.

**Several tabs polling at once.** Each tab polls only its own selected session every 2s, so N tabs means at most N live entries, the same set a single tab builds by switching. Against the 32MB budget, the 12 most recent sessions took 0.9MB and the largest pickle was 393KB, so it takes roughly 80 tabs, each on a session as large as the largest, to fill it. If it does fill, LRU evicts and those polls re-parse: today's cost, no worse. The lock is held only for the dict and counter operations, never during `fn`, `pickle.dumps` or `pickle.loads`, so parallel polls never wait on each other's parse. Two tabs on the same **changing** session both miss and both parse, exactly as both do today; the later store replaces the earlier one, and the subtract-on-replace rule keeps the counter exact. Two tabs on the same unchanged session both hit. A per-path "parse in flight" lock to dedupe that double parse is not justified: today's behaviour is already a double parse. Peak transient memory per concurrent miss is one parsed object plus its bytes, the same object today's code already builds.

Why pickle bytes rather than holding the object: the assembly stage mutates what it receives (`e["ops"] += ae["ops"]`, `hb["turns"].extend`, `t["started_at"]=`, `meta[...]`). Bytes cannot be aliased, sizes are exact for the bound, and pickle preserves `tests` sharing dicts with `cmds`, which JSON would not. It only ever loads bytes this process wrote; nothing crosses a file or a socket.

**`aitracker/providers/claude.py`**

- `def _transcript_pass(path) -> dict`: lines 1608–1878 moved verbatim, returning the 30 names that cross the split: `agents, asks, cmds, commits, ctx_current, fail_cmd, files, hb_calls, hb_desc, hb_iv, hb_turns, meta, n_search, narrative, parse_error, pr_states, prs, reads, requests, t_first, t_last, task_defs, task_order, task_status, task_times, tests, text_last, todos, tok_in, tok_out`.
- `parse_session(path)`: `t = file_pass("claude.transcript", path, _transcript_pass)`, unpack the 30 names, the rest unchanged from `sid = ...` on. The stale `ponytail: full re-parse per poll` comment goes.
- `def _shells_pass(path) -> (launches, results, done)`: the scan half of `parse_shells` (`claude.py:1476-1504`). `parse_shells` gets it through `file_pass("claude.shells", ...)`, keeps its existing `except OSError: return []`, then runs the per-launch `.output` reads as today. Those reads stay live.

**Auggie and Augment: no change.** They are 20–48ms normally and 183ms at worst, and `parse_auggie` is one function that mixes the walk with `load_tasks`. Conventions rule 4 is not broken: this is a speed optimisation behind `Provider.parse`, like `_AGENT_CACHE`, with the same shape from every provider. `file_pass` lives in `util.py` so Auggie can adopt it later without a second implementation.

**`scripts/bundle.py`**: add `pickle` to the `HEADER` import line (line 21). `strip_module` drops `util.py`'s import, so without this the bundle raises `NameError` on the first parse. `file_pass` and `_PASS_CACHE*` have no name collisions (grepped).

**Rejected on the way:** caching `_session_meta` again (already cached), per-provider caches (a second implementation), offset-tailing of live files (this would help live sessions, but the loop's locals are not resumable; it is the next step only if measured need remains).

### P4. Client design: an honest snapshot

**P4.1 Sidebar (`app.js`).** Add `data-sid="${s.id}"` to both row templates (`app.js:1057, 1181`), then:

```js
function sideMarkActive(id){        // true when the row is already in the DOM
  const l=$("slist"), row=l&&l.querySelector('.sitem[data-sid="'+CSS.escape(id)+'"]');
  if(!row) return false;
  l.querySelectorAll(".sitem.active").forEach(e=>e.classList.remove("active"));
  row.classList.add("active");
  // the two pieces of renderSide's bookkeeping a skipped render would otherwise leave behind
  const found=sessions.find(s=>s.id===id); if(found) selEntry=found;   // app.js:1072
  // app.js:1102: the row is visible, so its container is already open. Not in search mode:
  // renderSide returns at app.js:1052 before auto-expand, so the expand must still run on exit.
  if(searchResults===null) autoExpandedFor=id;
  return true;
}
function pick(id){$("sid").value=id;track();sideMarkActive(id)||renderSide();closeDrawer();}
```

A missing row (collapsed agent group, top-N cap, live filter) falls back to `renderSide()`, so auto-expand still fires there. **Why the bookkeeping (round-1 F1, reproduced in a browser):** without `autoExpandedFor=id`, the next 5s `renderSide()` sees `cur!==autoExpandedFor` and re-opens the selected row's group, undoing a collapse the user made after picking it. Without `selEntry`, the selected row can drop off the list when a later poll filters it out. **Why not in search mode (round-2 m1):** a pick from search results would otherwise mark a group auto-expanded that never was, so clearing the search would leave the selected agent row hidden inside a collapsed group. `test_integration.py:1867` pins the literal `\nfunction pick(id)`: keep it.

**Known limit, left alone:** `pickToggle` (`app.js:1219`, the title of a row that has agent sessions) calls `_persistGroups()` first, whose subscriber runs a full `renderSide()` synchronously before `pick()`. Those clicks keep paying one full render. It is the right render, because the click changes which rows exist.

**P4.2 Snapshot seam (`app.js`, all inside the `let sessEpoch` … `resetSession` span so the test harness's `_block` extracts it).**

```js
const SESS_CACHE=new Map(), SESS_CACHE_MAX=8;   // unchanged size; sid -> {d, at}, at = Date.now() at landing
const SNAP_MAX_AGE=LIVE;                        // seconds; one constant, no new knob or page.py mark
const SNAP_GRACE_MS=50;
let sessSnapTimer=null, sessSnapLabel="";       // label text; read by ext_cr_boot.js at render time
function sessCachePut(sid,d)      // as today, stores {d, at:Date.now()}
function sessCacheGet(sid)        // the d, or null when absent, e.d.id!==sid, OR older than
                                  // SNAP_MAX_AGE (an expired entry is deleted here) -- the age
                                  // limit lives in this one function, so no caller can bypass it
function sessCacheAge(sid)        // seconds since landed, Infinity when absent (for the label)
function sessSnapshot(d,age){     // a COPY: the cached entry is never edited
  return Object.assign({},d,{now:d.now+age, term_tty:null, term_attached:false, waiting:false,
    overview:Object.assign({},d.overview,{now:"",now_kind:""}), snapshot_age:age});
}
function sessShown(id){ return !!(lastData && lastData.id===id); }   // something of id is painted
function sessSetLabel(text)       // sessSnapLabel=text; $("hmeta").dataset.snap=text, or delete when ""
function sessPaintSnapshot(t){    // returns bool
  if(!sessCurrent(t)) return false;
  const d=sessCacheGet(cur); if(!d) return false;
  const age=sessCacheAge(cur), m=document.querySelector("main");
  sessRefreshing=true; sessSetLabel(sessSnapText(age,false)); m.dataset.sess="refreshing"; // BEFORE paint
  if(renderFor(cur, sessSnapshot(d,age))) return true;
  sessRefreshing=false; sessSetLabel(""); m.dataset.sess="loading";                       // refused: undo
  return false;
}
function sessSnapCancel()         // clearTimeout + null; called from resetSession and sessLanded
function sessSnapText(age,failed) // "snapshot from 3m ago · updating…", or "data from 3m ago · can't refresh"
```

**Order inside `sessPaintSnapshot` (round-2 M1):** the board reads `sessRefreshing` and the label synchronously, inside `render()`, through the `EXT` hook (`ext_cr_boot.js:1046`). Setting them after `renderFor` would paint a snapshot with no label. So all three are set first and undone if `renderFor` refuses. `ext_cr_boot.js:1046` passes `snapLabel: (typeof sessSnapLabel!=='undefined' ? sessSnapLabel : "")` next to `refreshing:`.

`track()` on a real change: `resetSession` (which sets `sessRefreshing=false`), mark `loading`, then if `sessCacheGet(cur)` returns an entry, `sessSnapTimer=setTimeout(()=>sessPaintSnapshot(t),SNAP_GRACE_MS)`, then `poll()`. Fresh data landing inside the 50ms cancels the timer, so an unchanged session never shows anything old. This replaces today's synchronous paint.

**Two flags, two jobs (round-2 B1, correcting round 1's single predicate).**

- **`sessShown(id)`, i.e. `lastData && lastData.id===id`, decides error-or-keep and the event's `cached:` field.** `lastData` is set only by `renderFor` (`app.js:1442`) and nulled by `resetSession` (`:1467`), so it is true exactly when something of this session, fresh or snapshot, is on screen. That keeps round-1 F2's protection: an entry that exists but was never painted (too old, or still inside the grace) is not shown, so a failure cannot uncover session A's DOM under session B. Nothing reads `sessCacheGet` to decide this.
- **`sessRefreshing` drives the label only.** It is true while the data on screen is not known to be current: a snapshot, or fresh data whose latest poll failed. It is cleared by `resetSession` and by every successful landing. Today `track()` sets it from cache presence (`app.js:1402`); that line goes. The global name is kept because `ext_cr_boot.js:1046` reads it.

Round 1 used `sessRefreshing` for both jobs. It is false after every normal landing (`app.js:1459`), so a steady-state 500, 502 or network blip would have blanked a page that was showing fresh data.

**P4.3 Labels.**

- Dashboard: `sessSetLabel` writes `$("hmeta").dataset.snap`; `main[data-sess=refreshing] #hmeta::after{content:" · " attr(data-snap)}` replaces the fixed "refreshing…" (`app.css:626`). `render()` replaces `hmeta.innerHTML` but not its `dataset`, so the label survives a render.
- Dashboard badge: `render()` gets a first branch before `if(d.waiting)` (`app.js:1772`): `d.snapshot_age!=null` shows a muted "snapshot" badge, not live or idle.
- Control board: `renderUpdate` (`ext_cr_detail.js:2233`) sets `data-snap` on `.crd-header` from `state.snapLabel`; `.cr .crd.crd-is-refreshing .crd-header::after{content:attr(data-snap)}`. A new `window.CR.detail.stale(id, label)`, next to `error` (`ext_cr_detail.js` about 2208), sets the same class and attribute without a render, for the failure path in P4.4. **Today the board has no words at all**, only `opacity:.7`.
- Loading text must not flash during the grace: `animation:sessLoadShow 0s .15s both` on `main[data-sess=loading]::before` and `.crd-is-loading::after`.

**P4.4 Failures (`sessLanded`, `poll`).** `poll()` sets `d.gone` on 404 and `d.authfail` on 401 (read `r.status`; keep the seq/id guard and `finally` literals). A network failure now does something in `poll()`'s `catch`, so the `catch` gets **the same `seq!==pollSeq||id!==cur` guard as the success path, checked first** (round-1 F5). Without it, the `AbortError` that `resetSession` raises on every switch lands in the new session as "can't refresh". The guard covers it because `track()` has already called the new `poll()`, so `pollSeq` has moved, by the time the rejection runs as a microtask.

All failures go through one `function sessFailed(id, kind)` in the seam span, `kind` being `"gone"`, `"auth"` or `"other"`. On `"other"` (500, 502, network), a pending grace timer is cancelled and `sessPaintSnapshot` runs at once, so the branch below sees the final state. **The age is recomputed on every failed poll** from the cache entry's `at` (a raw `SESS_CACHE.get(id)`, which for fresh data is the time of the last good landing), so during an outage the label keeps counting and the view expires (round-2 M2). A missing entry counts as expired.

| Response | Today | Plan |
|---|---|---|
| 404, session deleted | Snapshot stays, **mark cleared, shown as if current**, for ever | `SESS_CACHE.delete(id)`, error state in both views |
| 401, auth lapsed | Same defect | `SESS_CACHE.clear()`, error state |
| Other failure, `sessShown(id)`, age ≤ `SNAP_MAX_AGE` (snapshot **or** fresh data) | Snapshot: 500 clears the mark; network leaves "refreshing…" with no age. Fresh: kept, but the error text overwrites the meta line | View kept; `sessRefreshing=true`, `data-sess=refreshing`, label "data from 2m ago · can't refresh"; the next good poll clears all three |
| Other failure, `sessShown(id)`, age > `SNAP_MAX_AGE` | Kept for ever | Error state |
| Other failure, nothing shown (no entry, or one too old to paint) | Mark cleared on a 500 when an entry exists, uncovering the previous session | Error state; the previous session's DOM stays hidden |

**Error state:** `sessRefreshing=false`, `sessSetLabel("")`, `data-sess=error`, `data-err`, and only here the `$("hmeta").innerHTML` error line that `poll()` writes today on every error (`app.js:1553`); on the kept-view path that write would erase the meta line under the label.

**The event:** `tracker:session-error` carries `{id, error, cached, snapLabel}`, where `cached` is true only on the kept-view row. The board listener (`ext_cr_boot.js:1054`) today returns when `cached` is true, so the board never says "can't refresh". It now calls `CR.detail.stale(dt.id, dt.snapLabel)` when `cached` is true, and `CR.detail.error` otherwise.

**Fresh data kept after a failure is not scrubbed.** Its `term_tty` is as old as the label says, at most `SNAP_MAX_AGE`. The terminal controls stay usable, because the user has already been looking at that data rather than being switched onto it, and the server still checks ownership and, for model and effort, that Claude is in the foreground (P4.5).

**P4.5 Actions on a snapshot.** No global click guard (round-1 F3: a capture listener misses property and listener handlers and keyboard actions, blocks navigation and read-only UI, and has no end while the server is unreachable), and no client guard on notes either (round-2 m4). Instead:

1. **Terminal actions:** the snapshot scrubs `term_tty:null, term_attached:false` (P4.2), so model, effort and stop are disabled through their existing `disabled` path (`ext_cr_detail.js:1153, 3117`).
2. **Actions that address a note by its position: checked on the server, not guarded in the client (round-2 m4).** The notes drain `/api/notes/next` (`server.py:771-786`) removes a note from the front of the stack between polls, so a position can point at the wrong note on fresh data too, not only on a snapshot. The fix:
   - **Server**, `/api/notes/push` and `/api/notes/delete` (`server.py:759, 788`): after the existing range check, `want = body.get("text")`; if `want` is a string and `stack[idx].get("text") != want`, return `self._json({"error": "notes changed", "notes": stack}, 409)` and change nothing. `text` stays optional, so a caller that does not send it, such as `curl`, behaves as today. Stored text is already cut to 2000 characters at create (`server.py:756`), and the senders send back exactly what they were given, so equal notes compare equal.
   - **The three position-addressed senders also send the note text** taken from the list on screen: classic `removeNote(idx)` and `pushNote(idx)` (`app.js:2337, 2345`) send `text: ((lastData&&lastData.notes)||[])[idx]?.text`; the board's `note-remove` click (`ext_cr_detail.js:1989`) adds `text` from `ui.lastSession.notes[idx]`, and its handler (`ext_cr_boot.js:699`) forwards `payload.text` into the body.
   - **On `"notes changed"`:** classic toasts "Notes changed — list refreshed" and calls `poll()`; the board notifies the same and calls `poll()` (today it polls only on success).
   - **Known gap, left alone:** the notes routes read and write `notes.json` without a lock, so two writes racing can still lose one. That predates this plan, and the text check narrows it.
3. **Everything else is left alone,** because it names its session explicitly and does the same thing on fresh data: pin, rename, flag, run, resume, open terminal, and the text-based note create (classic `addNote`, board `cr:note-push`). `copyNote(idx)` reads the list that is on screen, so it copies the note the user sees.

**`aitracker/term_vt.py`, `inject()`, opt-in `require_claude` (round-1 F4).** This is **a same-session wrong-target fix, not a leakage fix**: `_pty_owned` already stops one session addressing another's terminal. What it does not stop is a `term_tty` that still belongs to this session but whose foreground has fallen back to a bare shell after Claude exited, where `/model x` plus Enter runs as a shell command. The gap exists on fresh data too, between polls, so the fix is server-side and narrow:

- `require_claude = bool(body.get("require_claude", False))`, read with the other body fields;
- after the quiescence wait and the existing `still = _pty_owned(pt, sid)` re-check (`term_vt.py:4596-4599`), and before the first `_inject_write`: `if require_claude and not _foreground_is_claude(pt.fd): return handler._json({"ok": False, "reason": "claude not in foreground"})`. The probe runs outside `_LOCK`, as the other callers do (`term_vt.py:1704, 3908`).
- The four model/effort senders add `require_claude: true`: `_injectToTerminal` (`ext_cr_detail.js:3076`, only called for model/effort), `_injectSlash` (`ext_cr_term.js:987`, likewise), and `ContextBar._pickModel`/`_pickEffort` (`ext_vt.js` about 2401, 2423). Every one of them already shows `j.reason` in its failure toast.
- Other inject callers are unchanged: the server-side `/rename` sync (`server.py:192`) only runs after `_attached_pty` has confirmed Claude in the foreground, and terminal-tab sends type into whatever is there by design.

**`aitracker/server.py`:** `Handler._json` sends `Cache-Control: no-store` on every JSON response. One line, default-safe for new routes. `_RenameSyncCapture._json` (`server.py:155`) writes no headers and is unaffected.

### P5. Safety

**Every field, and where it may come from**

| Fields | Input | Server pass cache | On a client snapshot |
|---|---|---|---|
| `requests, narrative, commands, commits, tests, agents, decisions, tokens, context, reads, fail_cmd, parse_error, message`, `meta` from the log | Transcript bytes | **Yes** | Shown, labelled |
| `shells[].running` | Transcript (`done` set) | Yes | Shown, labelled |
| `shells[].last` | `.output` file | **Never** | Shown, labelled |
| `todos, counts.done/todos` | `~/.claude/tasks/<sid>/` plus transcript | Never (`load_tasks` re-runs) | Shown, labelled |
| `agents_bg` (`running, state, dur_s`), `files[].agent`, agent PRs, `heartbeat` | Agent files + clock (`_AGENT_CACHE` per file; time fields resolved per call) | Never | Shown, labelled |
| `agent_sessions` | Sibling session files + clock | Never | Shown, labelled |
| `files[].alive` | `os.path.exists` | Never | Shown, labelled |
| `meta.title, title_claude, title_local_only` | `titles.json`, `title_sync.json` | Never | Shown, labelled; live in the sidebar |
| `notes, note_count, pinned, open_flags, flag_text` | `notes.json`, `pins.json`, `flags.json` | Never | Shown; remove or push of a moved note refused by the server (P4.5) |
| `continued_as, continued_from` | `forks.json` | Never | Shown, labelled |
| `meta.model_label, model_update, gateway, model_ladder, model_hints, model_slot, resume_cmd` | Config, `model_keep.json`, `newest_models()` | Never | Shown, labelled |
| `meta.ended` | `_META_CACHE` tail scan | Never (own cache) | Shown, labelled |
| `mtime, now, push_when` | stat + clock | Never | `now` advanced by age; `push_when` shown |
| `waiting, overview.*` | Asks + `_blocked_jobs` + idle time | Never | `waiting:false`, `overview.now:""` |
| `term_attached, term_tty` | Live pty table | Never | **`false`, `null`** |

**Known gap, deliberately left:** while a snapshot shows, `agents_bg[].running` can read stale, and the dashboard's `ov_now` can say "working…" when `now-mtime` is inside the window. Both sit under the label for one round trip. Rewriting nested arrays for that window is not worth it.

**Actions on a snapshot, why P4.5 is needed.** `_pty_owned` only stops *cross-session* use. A stale `term_tty` that the session still owns passes, and `inject()` then types `/model x` plus Enter into whatever is in the foreground, a bare shell if Claude has exited (its docstring says so); `phone-stop` closes the terminal. The scrub disables both on a snapshot, and `require_claude` closes the wrong-target case on fresh data too. `removeNote(idx)`, `pushNote(idx)` and the board's note remove send a position taken from the list on screen, so if the drain or another tab changed the notes, the wrong one would be deleted or pushed into a live session; the server now refuses unless the note at that position still has the text the client saw. Enter-to-send in note and phone inputs stays allowed: it appends text and names its session explicitly, so a snapshot changes nothing. `checkCompletions` only runs after a real landing, so a snapshot cannot fire a false "finished" toast.

**Isolation.**

- Server key is `(kind, absolute path)`. There is no sid-to-data mapping to cross, `find_session` sanitises the id, `parse_any` stamps `d["id"]` per request. A forked copy with identical bytes has a different path.
- Auggie is not in the pass cache. `auggie:abc` and `abc` route to different providers through `provider_for`.
- Client: `sessCacheGet` refuses `d.id!==sid`; the snapshot passes through `renderFor` and the `sessCurrent(t)` token; the `Map` key is the full namespaced id. A switch during the grace cancels the timer, and the epoch guards it again.

**Data at rest.** Nothing new persists anywhere: the server cache is process memory holding what is already plaintext in `~/.claude`, and the browser `Map` dies with the tab. **No logout exists to hook** (no route, and the cookie is `HttpOnly`, so JS cannot see it), which is one more reason not to persist; the 401 path clears the `Map`. A persistent option would first need a logout route and `Clear-Site-Data`. `no-store` keeps transcripts out of the browser disk cache and any proxy, which matters most for a tunnel viewed on a shared device. `TRACKER_TUNNEL_READONLY`: `_RO_GET_ALLOW` is unchanged, no route is added, payloads do not vary by caller, so the cache holds nothing caller-specific. `TRACKER_AUTH`: `_authok` runs before the route, so a refused request never reaches `file_pass`.

**Invalidation.**

| Event | Result |
|---|---|
| Session file appended or rewritten | stat key changes → miss |
| Session file deleted | `find_session` → None → 404 → client purges; the server entry is unreachable and ages out by LRU |
| Server restart | Cache empty. In-process means **no schema versioning**: a code change needs a restart anyway (CLAUDE.md), and the page's `Map` is only ever read by the JS that wrote it |
| Title, flag, pin, note edits | Those files are read per request, untouched by the cache. Snapshot may show the old value for one round trip, labelled; another tab's edit likewise |
| `LIVE_WINDOW` changed in Config | Baked in at page load like `LIVE` |

**Multiple tabs.** Each tab has its own `Map` and polls its own selection, with no coordination needed. The server cache is shared; P3 "Several tabs polling at once" covers its byte budget and lock.

**Memory.** Client: 8 entries, as today. Worst case 8 × 433KB of JSON, about 3.5MB, is estimated at 10–15MB of heap (not measured). Server: 32MB of pickle bytes, strict LRU; the 12 most recent sessions took 0.9MB.

### P6. Sequencing

Everything goes on one feature branch and one set of commits, from a fresh worktree per conventions rule 13, each commit leaving `make check` green.

1. **Sidebar (P4.1).** Biggest dashboard win, no semantics change, nothing depends on it, and it unmasks whether a snapshot paints.
2. **Honest snapshot without the timer (P4.2 minus grace, P4.3, P4.4, P4.5 including its two server changes, `require_claude` and the note text check, and `no-store`).** Fixes real defects whether or not anything gets faster, and must land before snapshots get more common.
3. **Server pass cache (P3).** The only risky step, alone so it can be reverted or switched off.
4. **Grace timer.** The grace only makes sense once step 3 makes fresh data fast. Re-run the P1 measurements in both views and record them in the Log; this is the only place a speed claim, the board's above all, is allowed to come from. If the real hit is not within about 20ms of server time, stop and report rather than tune.

`make check` needs `unset TRACKER_AUTH;`, and the gate misses load-time JS and CSS errors, so also load the real page once in Playwright in both views. In the same Playwright pass, check F1 on the real sidebar: pick an agent child inside an open group, collapse the group, wait for one 5s `loadSide`, and confirm the group is still collapsed. Then do the same pick from search results and clear the search; the child's group must open (m1).

### P7. Tests (stdlib `unittest`; each red without its fix)

**`tests/test_pass_cache.py`, new.** Fixture idiom from `tests/test_agent_cache.py` (temp dir, `_write`, `_asst`, `_res`, clear the cache in `setUp`).

| Test | Red when |
|---|---|
| `test_hit_does_not_reread` (pass runs once over two calls) | No cache |
| `test_cold_equals_warm_with_agent_merges`: `AITRACKER_NO_PASS_CACHE=1`, then twice warm, all equal, fixture has agent files editing a shared path | `file_pass` returns the stored object (`ops` doubles each call) |
| `test_append_invalidates`, `test_same_size_new_mtime_invalidates`, `test_replace_same_mtime_new_inode_invalidates` | Key lacks size, mtime or inode respectively |
| `test_write_during_pass_is_not_pinned`: `fn` reads the whole file first, **then** appends to it, then returns, so the append lands after the read; the next call re-runs and sees the appended line | `os.stat` moved after `fn` |
| `test_live_inputs_seen_with_transcript_untouched`: through `parse_any`, change `titles.json`, `notes.json`, `flags.json`, a task file, an agent file, a shell `.output` | Mutation: cache all of `parse_session` |
| `test_time_fields_move`: patch `time.time` forward; `now`, `push_when`, agent `running` change | Same mutation |
| `test_identical_bytes_two_paths_stay_separate`: two sids, `d["id"]` and `meta` each their own | Key drops path |
| `test_byte_bound_evicts_oldest_and_hit_refreshes_lru` | No eviction, or no touch on hit |
| `test_replace_keeps_byte_count_exact`: store one path, append to it, store again; `_PASS_CACHE_BYTES == len(latest bytes)` | Replaced entry not subtracted (F6) |
| `test_concurrent_misses_keep_byte_count_exact`: 8 threads × 50 calls over 4 files that are appended to meanwhile; afterwards the counter equals the sum of stored lengths and is ≤ the bound. **A smoke test, not a red-before-fix test:** under the GIL it cannot reliably catch a counter update outside the lock; `test_replace_keeps_byte_count_exact` is the one that proves F6 | Gross accounting errors only |
| `test_unpicklable_fails_open` (a local `lambda` in the result) | No `except` around `dumps` |
| `test_other_errors_in_dumps_propagate`: patch `pickle.dumps` to raise `NameError`; it reaches the caller | `except` widened beyond the four types |
| `test_json_responses_are_no_store` on `/api/session`, `/api/narration`, `/api/list` (in-process `Server` idiom, `test_integration.py:280`) | Header missing |

**`tests/test_integration.py`, extend the bundle test (about line 1587):** it runs `dist/tracker.py` with `--version`, `--help` and a stubbed `--selfcheck`, none of which reach a parse, so a missing `pickle` in `HEADER` would pass today. Add a step that loads the bundle with `runpy` and calls `file_pass` twice on a temp file with a counting `fn`, asserting `fn` ran **once** (a real hit, not just "no crash"). Red when `pickle` is left out of `HEADER`: the narrowed `except` lets the `NameError` through, and a fail-open path would show up as two runs.

**`tests/test_session_isolation.py`, extend `TestSessionSeamExecuted`** (node, same `_block` harness). `_MOCKS` gains `var LIVE=300`, a settable `Date.now`, and a `render` that records the whole `d` plus `refreshing: sessRefreshing` and `snapLabel: sessSnapLabel` **at render time**. The harness also extracts `function pick(id)` and `function sideMarkActive(`, with `$("slist")` stubbed so `querySelector` returns a row stub or `null` on demand, and `sessions`, `selEntry`, `autoExpandedFor`, `searchResults`, `CSS.escape` and a counting `renderSide` in `_MOCKS`. That replaces round 1's real-page F1 test, which could not go red because the stub DOM matches class names only (round-2 m2).

| Test | Red when |
|---|---|
| `test_snapshot_strips_live_fields`: `term_tty, term_attached, waiting, overview.now`; cached entry itself unchanged | No scrub, or scrub edits the cache |
| `test_over_age_snapshot_not_painted` (backdate `.at`) | No age check |
| `test_fresh_inside_grace_paints_no_snapshot` | Paint is synchronous |
| `test_switch_during_grace_never_paints_old` | Timer not cancelled or token unchecked |
| `test_404_purges_and_errors`, `test_401_clears_everything` | Today's behaviour |
| `test_500_keeps_labelled_snapshot_then_clears` | Today's behaviour |
| `test_steady_state_500_and_network_error_keep_view`: land fresh A, then a 500, then a rejected fetch (`TypeError`), then a good landing. After each failure: no new render, mark `refreshing`, label contains "can't refresh", event `cached:true`; after the good landing all three are cleared | Error-or-keep keyed on `sessRefreshing` (B1) |
| `test_backdated_entry_and_500_stays_error`: cache B with `at` 301s ago, pick B from A, land a 500; mark is `error`, no render of B, event `cached:false` | Branch keyed on cache presence (F2) |
| `test_500_inside_grace_paints_then_keeps`: fresh entry, 500 lands before the timer; snapshot painted, mark stays `refreshing`, `cached:true` | Pending timer not flushed before the branch |
| `test_outage_reages_then_expires`: land fresh A at t0; failures at t0+60s and t0+120s give labels "1m ago" then "2m ago"; a failure at t0+301s gives mark `error` and `cached:false` | Age computed only at paint (M2) |
| `test_refused_paint_resets_label_and_mark`: make `renderFor` return false; after `sessPaintSnapshot`, `sessRefreshing` false, label `""`, mark `loading` | No undo (M1) |
| `test_abort_mid_flight_does_not_touch_new_session`: pick A, pick B while A's fetch is pending, reject A's fetch with an `AbortError`; B's mark and label unchanged, no event | No seq/id guard in `catch` (F5) |
| `test_position_note_senders_send_text`: `removeNote(1)` and `pushNote(1)` post `{session, index:1, text}` with the text of note 1 on screen | Text not sent (m4) |
| `test_prefixed_and_bare_ids_do_not_collide` (`auggie:abc`, `abc`) | Key strips the prefix |
| `test_pick_skips_full_sidebar_when_row_present`, `..._falls_back_when_absent` | Today's `pick`, or no fallback |
| `test_fast_pick_keeps_sidebar_bookkeeping`: row present; afterwards `autoExpandedFor===id`, `selEntry.id===id`, `renderSide` not called | F1 bookkeeping missing |
| `test_fast_pick_in_search_leaves_auto_expand_pending`: `searchResults=[…]`, row present; afterwards `autoExpandedFor` unchanged, `selEntry.id===id` | Set during search (m1) |

The collapse-stays-collapsed behaviour itself is checked in the P6 Playwright pass, on the real sidebar.

**`tests/test_session_isolation.py`, `TestControlRoomSessionReset`:** add `test_cached_error_event_labels_header`. Dispatching `tracker:session-error` with `cached:true, snapLabel:"data from 2m ago · can't refresh"` sets `crd-is-refreshing` and `.crd-header` `data-snap`, and does not add `crd-is-error`; with `cached:false` it shows the error. Red with today's `if (dt.cached) return;` (`ext_cr_boot.js:1056`).

**`tests/test_integration.py`, notes routes (in-process `Server` idiom, `config.NOTES_FILE` pointed at a temp file):** add `test_drain_then_stale_push_and_delete_are_refused`. Notes `[n0 pushed, n1, n2]`; `/api/notes/next` drains `n0`, leaving `[n1, n2]`; then `/api/notes/push` and `/api/notes/delete` with `{index:1, text:"n1"}`, the positions the client saw before the drain. Both return 409 `{"error":"notes changed"}` and `n2` is neither toggled nor deleted. With the right text (`{index:0, text:"n1"}`) both succeed, and with no `text` they behave as today. Red today: index 1 toggles and then deletes `n2`.

**`tests/test_inject_footer_quiet.py`, extend** (it already has `_spawn_script` and `_FakeHandler`):

| Test | Red when |
|---|---|
| `test_require_claude_refuses_a_bare_shell`: spawned script is not Claude; `inject(..., {"require_claude": True, ...})` returns `{ok:false, reason:"claude not in foreground"}` and the child receives nothing | No check |
| `test_require_claude_passes_when_claude_is_foreground`: patch `term_vt._foreground_is_claude` to `True`; `ok` | Check inverted or run before the wait |
| `test_without_flag_inject_is_unchanged`: same bare shell, no flag, text delivered | Flag made the default |

Static sweep: all four model/effort senders pass `require_claude: true`; the three position-addressed note senders (`removeNote`, `pushNote`, the board's `note-remove` and its `cr:note-remove` handler) carry `text`.

**Tests that must change, on purpose:** `test_cache_hit_paints_refreshing_miss_is_loading`: the paint now arrives after the grace; it keeps asserting `refreshing: True` at render time and also asserts a non-empty `snapLabel` then (M1). `test_cached_error_keeps_snapshot_and_next_land_clears_error`: the mark now stays `refreshing`, which is the defect being fixed. Static sweep: `ext_cr_boot.js` passes `snapLabel`; `sessLanded` and `sessFailed` contain no `sessCacheGet` call; no `localStorage`/`sessionStorage`/`indexedDB` write receives a detail dict.

### P8. Risky spot and fallback

**Highest risk: the `parse_session` split and aliasing.** A 270-line move plus 30 unpacked names; a missed name is a `NameError` at runtime, and a stored object mutated by the assembly would silently double counts. Mitigations: `pickle.loads` gives a fresh object by construction, the cold-equals-warm test covers it, and the crossing names come from an `ast` walk, not by eye. **Fallback:** `AITRACKER_NO_PASS_CACHE=1` restores today's behaviour without a revert; the client steps do not depend on it, only the grace timer loses its point.

**Second risk: `require_claude` refusing a real Claude.** `_foreground_is_claude` fails closed (False on any doubt, such as a `ps` failure), so a model or effort switch could be refused while Claude is really there. The user sees "claude not in foreground" in the existing toast and nothing is typed, which is the safe direction. **Fallback:** drop the flag from the four senders; the server default is unchanged.

**Third: 50ms is a judgement, not a measurement of perception.** Prototype hits were mostly 1–7ms to first byte on Claude sessions (occasionally 13–40ms), and uncached Auggie was 15–75ms, so some Auggie switches will show a snapshot where a Claude one would not. It is one constant.

### P9. Decisions you may want to overrule

**1. What a switch shows, and the "no stale" tension.** You asked for two things that pull apart: show stale data then refresh, and "there shouldn't be any stale". The plan reads them together as: never unlabelled, never acted on, never another session's, and not shown at all when fresh data can arrive at once.

| | Recommended: labelled snapshot | Alternative: strict, no old data ever |
|---|---|---|
| Unchanged session | Fresh as soon as the server answers (prototype: about 70ms, to be re-measured), nothing old shown | Same |
| Changed session (median 48ms parse, up to about 1s) or remote | Blank up to 50ms, then the snapshot if under 5 minutes old, labelled "snapshot from 3m ago · updating…", read-only, no terminal controls, replaced automatically | "Loading session…" until fresh, up to about 1s locally and about 1.5s on the emulated link |
| Snapshot over 5 minutes old | Loading state | Same |
| Server unreachable or erroring | Whatever is on screen, snapshot or fresh, stays, labelled "data from 2m ago · can't refresh" with the age counting, until it is 5 minutes old, then the error state | Fresh data: same. A snapshot is never shown, so a switch goes to the error state |
| Code | P4.2–P4.5 | Removes the snapshot paint; step 1, step 3, the failure handling and `require_claude` remain |

Other values for the limit are one line: 0 is the strict column, and removing the check means any age, always labelled.

**2. No persistence across a page reload.** Reload stays at 1.3–1.9s to first detail. Persisting would need IndexedDB, a new logout route, clearing, and would reverse your earlier decision that no transcript data sits at rest in the browser. If reload speed matters, moving `track()` ahead of `await loadSide()` in `start()` is probably the cheaper fix; that is a separate change, not in this plan.

## Adversarial review

### Round 1 (opus, fresh reviewer, told to assume the plan wrong): REFUTED

It ran: an AST audit of the `parse_session` split; a line-split copy of claude.py comparing cold and warm on 38 real sessions, including a 32MB one; headless Chromium in both views; a browser repro of F1. Held up: the split is clean (30 crossing names); cold equals warm except time-based or live fields; a hit costs median 2.6ms, worst 19.7ms; `renderSide` is 62% of a dashboard switch; rejecting ETag, IndexedDB and disk is sound; the bundler `HEADER` lacks `pickle`.

- F1 major (reproduced): the P4.1 fast path skips `renderSide`'s `autoExpandedFor`/`selEntry` bookkeeping, so a user's group collapse is re-opened.
- F2 blocker: `sessLanded` (`app.js:1451`) keys error-vs-keep off cache presence. With the planned age limit, an expired entry that wasn't painted would uncover A's DOM under B on a 500.
- F3 major: the P4.5 global click guard isn't default-deny (misses property and listener handlers and keys), blocks navigation and read-only UI, and is unbounded. Only the index-addressed note actions are unsafe.
- F4 major: `inject` checks ownership, not that claude is in the foreground. A stale `term_tty` can type a slash command into a bare shell. Not snapshot-specific.
- F5 minor: the new `catch` handling in poll also fires on a switch's `AbortError`.
- F6 minor: byte accounting doesn't subtract a replaced entry, so the counter inflates.
- F7 minor: the board breakdown didn't reproduce (72ms and 247ms medians); keep the re-measure gate.
- F8 minor: defect 3 is overstated for the classic view and real for the board. 8→16 reverses a prior decision.

### Round 2 (opus, a different fresh reviewer, on the revised plan): NOT SETTLED

Held up: F4 (the check sits after the quiet wait and the ownership re-check; `term_tty` only exists when the same probe passed, so a real model switch isn't newly refused), F5, F6; the purity of `parse_session` 1605–1878 (re-run AST walk); concurrency (a late store only costs a re-parse); Auggie skips the cache cleanly; read-only mode, auth and the kill switch are unaffected; no in-process code reload; `dist/` is untracked.

- B1 blocker: the round-1 "one predicate" (`sessRefreshing`) is false after every normal landing, so a steady-state 500, 502 or network blip would blank a page showing fresh data.
- M1 major: the board reads `sessRefreshing` and the label synchronously inside `render()`, so setting them after `renderFor` paints an unlabelled snapshot.
- M2 major: age is checked only at paint time, so during an outage a snapshot shows a frozen age and never expires. The board never says "can't refresh".
- m1: in search mode `renderSide` returns before auto-expand, so the F1 fast path would mark a group auto-expanded that never was.
- m2: the planned F1 page test can't go red (the stub matches class names only).
- m3: a broad `try` around `dumps` hides a missing `pickle` import in the bundle.
- m4: the notes drain (`server.py:771-786`) shifts positions between polls, so index-addressed note actions can hit the wrong note on fresh data too.
- m5: the concurrency test can't go red under the GIL; the write-during-pass test needs the append after the read.
- m6: 8→16 isn't supported (the 0-of-12 figure came from a fixed-order cycle); keep 8.

## Reconciliation

### Round 2 (main thread, judged against the code)

| # | Verdict | Note |
|---|---|---|
| B1 | **confirmed**: accepted, blocker | `app.js:1459` sets `sessRefreshing=false` on every landing. `lastData.id===id` (set in `renderFor` `:1442`, nulled in `resetSession` `:1467`) is the right "painted" test. This corrects the round-1 reconciliation's "one predicate" wording. Two flags: `shown` for error-or-keep, `sessRefreshing` for the label. |
| M1 | accepted | Set flag, label and mark before `renderFor`; reset if it refuses. |
| M2 | accepted | Re-age on every failure; expire to error past the limit; the board labels its header. |
| m1 | **confirmed**: accepted | `renderSide` search branch returns at `app.js:1052`. Set `autoExpandedFor` only outside search. |
| m2 | accepted | F1 test moves to the seam harness plus Playwright. |
| m3 | accepted | Narrow the `except`; the bundle test asserts a hit. |
| m4 | accepted: **replaces the client note guard** | The server checks the note's text before push or delete. Smaller, and it covers fresh data too. |
| m5 | accepted | Concurrency test stays as a smoke test; fix the append ordering. |
| m6 | accepted: **plan cut down** | Keep 8 entries; no reversal of `session-isolation.md` P7.2. |
| Correction | — | Round 1's table said 4 note handlers; the code has 3 (`cr:note-push` is text-based and names its session). |
| Disagreement | accepted | Plan agent keeps note `text` optional for back-compat (curl, external callers), with a static sweep forcing the three page senders to send it. |

### Round 2 re-check (same reviewer, on the revised plan): SETTLED

All of B1, M1, M2, m1–m6 closed. The optional note `text` leaves no real hole: only external callers omit it, read-only visitors can't POST, and in the page `text` is undefined only while the list is hidden mid-switch.

| # | Verdict | Note |
|---|---|---|
| N1 minor | **accepted: amendment to P4.3** | A hung fetch keeps `pollBusy` set (`app.js:1545`), so `sessFailed` never runs and the snapshot isn't re-aged or expired. In `poll()`, before the `pollBusy` return: if `sessRefreshing && sessShown(cur)`, re-compute the label from the entry's `at`, and past `SNAP_MAX_AGE` call `sessFailed(cur, "other")`. Test `test_hung_fetch_still_expires` (unresolved fetch, `Date.now` +301s, fire the interval → mark `error`, `cached:false`). |

### Round 1 (main thread, judged against the code)

| # | Verdict | Note |
|---|---|---|
| F1 | **confirmed**: accepted | `selEntry` (`app.js:1072`) and `autoExpandedFor` (`:1102`) are set only inside `renderSide`. Reviewer reproduced it. |
| F2 | **confirmed**: accepted, blocker | `app.js:1451` reads `!sessCacheGet(id)`. One predicate, "snapshot on screen", drives every branch. |
| F3 | confirmed: accepted, **plan cut down** | Drop the global guard; guard the 4 index-addressed note handlers only. Smaller and closes more. |
| F4 | **confirmed, overstated**: accepted as a small server fix | `inject` checks `_pty_owned` only (`term_vt.py:4584-4592`). It's the same session's own shell, so it's wrong-target, not cross-session leakage. Keep it narrow: an opt-in `require_claude` flag from model/effort. |
| F5 | confirmed: accepted | Seq/id guard before acting in `catch`. |
| F6 | confirmed: accepted | Subtract on replace; one test. |
| F7 | accepted | Keep the re-measure gate before claiming the board number. |
| F8 | accepted | Board label fix stays; 8→16 goes in the decisions list. |
| Missed by both | — | Neither covered what a second browser tab does to the server cache's byte budget under concurrent polls; flagged for round 2. |

## Log
- 2026-11-04 plan file opened.
- 2026-11-04 plan written (opus). Round 1 review (fresh opus): REFUTED, 8 findings, all accepted; plan revised by the same opus author. Round 2 review (a different fresh opus): NOT SETTLED, 1 blocker + 2 majors + 6 minors, all accepted (B1 corrected the round-1 reconciliation); plan revised again. Round 2 re-check: SETTLED, with one minor (N1, hung fetch) recorded as an amendment. C1–C4 discharged; C5 (discuss before code) in progress; C6 covered by the plan's safety section and both reviews. No code written.
