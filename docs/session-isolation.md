# Session isolation — no cross-session bleed

Branch `fix/session-isolation` (worktree `.claude/worktrees/session-isolation`), base `personal/main` @ 154147e.

## Contract (verbatim)

> in the app today, when I switch between 1 session to another, the prior session's context always flows into the newly selected session, theres an session bleed happening, how am I supposed to stop that from doing it ? what are the security measures I should take such that this type of context bleed never really happens
>
> this issue has been observed in both the control board view and in the dashboard view
>
> go ahead, strict mode, plan with opus and do an round of adversial review. Is there any possibility of caching the newly opened sessions such that we dont see anything stale or it always take 2s to poll. There shouldnt be any stale and each session needs to be idempotent with no data leakage between the sessions within the app.

| Clause | Verdict |
|---|---|
| C1 Stop bleed on switch — dashboard view | not discharged |
| C2 Stop bleed on switch — control board view | not discharged |
| C3 Security measures so it never recurs (server-enforced) | not discharged |
| C4 Strict mode: tty routes without a matching session are rejected | not discharged |
| C5 Plan authored by opus | not discharged |
| C6 One round of adversarial review | not discharged |
| C7 No 2s wait / nothing stale on open (sid-keyed cache answer) | not discharged |
| C8 Each session idempotent, zero data leakage between sessions | not discharged |

## Diagnosis (code-read by 6 haiku Explore agents; 3 core claims re-read in main thread)

Shared switch path: control board `go()` (ext_cr_boot.js:304) → `pick()` (app.js:1285) → `track()` (app.js:1386). `track()` resets nothing — only `cur` + poll restart.

1. Composer/draft text survives switch and is submitted to the new sid: `.crd-flag-input`/`.crd-note-queue-input`/`.crd-phone-input` (ext_cr_detail.js:1414/1425/1512, submit 1821/1839/2020 → `ui.sid`); `#noteinput` (app.js:2236); `#runcmd` (ext_run.js, sid from render-time module var, :140).
2. Terminal mis-binding: `_attached_pty` (registry.py:309) matches `p.session` (opener), not foreground session; model/effort picks inject into `ui.lastSession.term_tty` (ext_cr_detail.js:1998/2034), stale until B's first poll.
3. Server trusts any tty id: `/api/term/keys` (term_vt.py:3398), `inject` (4201), `raw_stream` (4319), `screen_stream` (3721), `scrollback` (3907), `close_pty` (3459) — `PTYS[tid]` only, no session check.
4. Unguarded fetches render into the new session: app.js `doDetailSearch` 1319, `moreNarr` 1848, `openDiff`/`/api/file` 1938-1941, `openCmd` 2105, `openShell` 2129, `openAgent` 2143; ext_cr_boot.js:549 `cr:drill-request`.
5. Per-session UI not torn down: `#diffmodal`/`#msgmodal`, CR dialog `_stack` (ext_cr_dialogs.js:32), `curModal` (app.js:2035), `curDiff*` (1926), `lastData` (1393, re-rendered by toggles 2112-2114), `ui.flagOpen/noteOpen` (ext_cr_detail.js:1565), `ui.lastSession/lastState` (2166), `ui.spineSession`.

Ruled out: server caches (per-file keyed), sid sanitising (`safe_path_component`), main `poll()` (seq+id guarded, app.js:1476), localStorage (no drafts; only `uiState.scroll` un-namespaced).

## Plan
_Authored by the opus plan agent against base 154147e. Every cited line was re-read with grep + `sed -n`; line numbers are approximate (±5) because other sessions edit these files._

### P0. Diagnosis check (what the cheap agents got right, wrong, or missed)

| # | Verdict | Evidence |
|---|---|---|
| 1 composer drafts | **confirmed, incomplete** | Also missed: `.crd-plan-input` (ext_cr_detail.js:2771), `.crd-run-input` (:2938), `.crd-search-input` (:1402), classic `#dq` (index.html:137). CR click handler reads `var sid = ui.sid` (:1748), which only moves on the next `renderUpdate` (:2165). |
| 1 `#runcmd` | **confirmed + worse** | ext_run.js:140 sets `sid=cur` at render; the panel only resets when `m.cwd !== cwd` (:141) — two sessions in the same repo **share one run pane and job stream**. |
| 2 `_attached_pty` | **confirmed + worse** | registry.py:285 (match at ~:313) uses `p.session == sid`. For a folder shell `p.session` is the *first opener* (term_vt.py:3082), so A's detail gets `term_tty` of the shell **while B's claude is in its foreground** → A's model/effort/stop act on B. Also wrong for a dedicated `mode="new"` pty opened from A (it runs a *new* session) and for forked ptys. |
| 3 unchecked tty routes | **confirmed, incomplete** | Also unchecked: `POST /api/term/resize` (term_vt.py:3542) and `GET /api/term/attached` (:3676). Internal caller `server.py:192` (rename sync) calls `term_vt.inject` with a bare tty. Full list of tty-addressed routes (term_vt.py:4470-4481): keys, resize, inject, close, attached, screen, scrollback, raw. `/api/term/pty`, `/list`, `/cwds`, `/renderer`, `/status`, `/open`, `/run`, `/stream?job=`, `/kill {job}` take no tty. |
| 4 unguarded fetches | **confirmed** | Plus `addNote/removeNote/pushNote` (app.js:2234-2258) write the response into `lastData` after an `await` — A's notes land in B's `lastData` on a mid-request switch. |
| 5 per-session UI | **confirmed** | The live leak path is `syncModal()` (app.js:2047): called from render, it runs `curModal.refresh()` → `openShell(i,true)` against **B's** `curShells[i]` inside A's still-open modal. |
| "main poll() ruled out" | **wrong for C7** | `poll()` is correctness-guarded (seq+id, app.js:1476) but `pollBusy` (:1469) makes `track()`'s immediate `poll()` a **no-op while A's poll is in flight**; B's first fetch then waits for the next 2s tick. This is the "always takes 2s". |
| missed | **new** | CR detail derives `ui.sid` from `session.meta.sessionId` (ext_cr_detail.js:2163). Auggie's parse is called with the prefix stripped (providers/auggie.py:920), so for Auggie that id is very likely un-prefixed → CR actions (note/flag/pin) target an id without `auggie:` (confirm against a real `~/.augment/sessions/*.json` before relying on it; the fix below makes it moot). |
| missed | **new** | `closeTty` (ext_vt.js:3440) treats **every** 409 from `/api/term/close` as `busy`; a new mismatch-409 would be shown as "close anyway?". |
| missed | **new** | `ext_vt.js` `openVT` (:2875-2877) attaches to an existing folder shell *from the list row* without POSTing `/api/term/pty`, so the server never learns that session B was handed the tty. Strict ownership must account for list-row provenance. |
| missed | **new** | `parse_qs` drops blank values, so `?tty=X&session=` reads as *absent*. GET routes need `keep_blank_values=True` to distinguish `""` from missing. |

Ruled-out items (server caches, sid sanitising, localStorage scroll) re-checked: agree.

### P1. Design in one paragraph

Two invariants. **Server:** a tty is only ever addressed as a `(session, tty)` pair, and the pair must satisfy one predicate `_pty_owned`; missing `session` is 400, a failing pair is 409 `{mismatch:true}`. **Client:** every session-scoped thing is torn down by **one** `resetSession(next, prev)` that `track()` calls on a change of selection — it bumps an epoch, aborts in-flight reads, and runs a **registry** (`SESSION_RESET`) that every per-session module (classic, CR detail, CR dialogs, run panel) hooks into; every async read goes through **one** guarded helper `sessJSON` that drops a response whose `(sid, epoch)` moved; and the cache is a sid-keyed `Map` whose entries are only rendered through `renderFor(sid, d)`, which refuses any `d.id !== sid`. The server stamps `d.id` (the namespaced request id) on every detail dict at the shared seam, so "which session is this payload" is never inferred client-side.

### P2. Server changes

#### P2.1 `aitracker/registry.py`

- `parse_any(sid)` (:155): add **one line** after the provider parse, `d["id"] = sid` — the full namespaced id the client asked for (Claude `""` prefix, Auggie `auggie:`). Shared seam, so every provider gets it.
- `_attached_pty(sid)` (:285) — replace the `p.session == sid` scan with the existing "what is RUNNING this session" lookup `term_vt._session_pty` (term_vt.py:3219: folder → `fg.session == sid` after `_refresh_fg`; dedicated → `spawned == sid or (mode=="resume" and session == sid)`; excludes done/closing/forked):

```python
    try:
        with term_vt._LOCK:
            p = term_vt._session_pty(sid)
        if p is not None and term_vt._foreground_is_claude(p.fd):
            return p
        return None
    except Exception:
        return None
```
  Behaviour change, intended: a folder shell reports `term_tty` to the session in its **foreground**, never to its first opener; a `mode="new"` or forked pty is no longer reported as the parent's terminal. `server.py:184`'s rename sync inherits the fix.

#### P2.2 `aitracker/term_vt.py` — ownership

- `Pty.__init__` (:1377): new field `self.grants = set()` — every session id (including `""`) that `open_pty` has handed this tty to. Add-only, mutated under `_LOCK`, never cleared (a reused folder shell keeps every session that legitimately opened it).
- `open_pty` (:2886): at **each** of the six `handler._json({"tty": X.id, ...})` returns (:3049 resume-hit `hit`, :3104 folder `cwd`, :3135 busy-peek `fp`, :3154/:3169 deferred/typed `fp`, :3214 dedicated/overflow `pt`) add `X.grants.add(sid)` immediately before the return (inside the existing `with _LOCK:` at :3049; wrapped in `with _LOCK:` at the others). Verify the count with `grep -n '"tty": ' aitracker/term_vt.py` restricted to open_pty's range.
- New helpers, placed right after `_session_pty` (:3236):

```python
SESSION_MISMATCH = "terminal belongs to another session"


def _req_session(body=None, parsed=None):
    """The `session` a tty-addressed request names: a str -- "" included, meaning a session-less
    folder shell -- or None when it names none. Strict: every caller answers None with 400.
    keep_blank_values because `?session=` (the "" case) must not read as absent."""
    if body is not None:
        v = body.get("session")
    else:
        from urllib.parse import parse_qs
        vals = parse_qs(parsed.query, keep_blank_values=True).get("session")
        v = vals[0] if vals else None
    return v if isinstance(v, str) else None


def _pty_owned(p, sid):
    """THE one ownership rule every tty-addressed route checks. Call under _LOCK.
    `sid` may address `p` when the server handed `p` to `sid` (grants), when `sid` opened it
    (session), when `p` created `sid` (spawned -- the list row's own `session` field), or when
    `sid` is what the app typed into this folder shell's foreground (fg). The "" session (a
    Terminals-tab / launch-pad shell) may address only a pty that was opened session-less."""
    if sid in p.grants:
        return True
    if sid == "":
        return p.session == ""
    return (p.session == sid or p.spawned == sid
            or bool(p.folder and p.fg and p.fg.get("session") == sid))


def _mismatch(handler, tid):
    return handler._json({"error": SESSION_MISMATCH, "mismatch": True, "tty": tid}, 409)
```

  Why this and not "opener OR foreground" alone: a folder shell is **one per cwd shared by every session in that directory** (open_pty's `_folder_pty(cwd)`, :3058). Opener-only would 409 session B's own terminal the moment session A had opened the same repo first. `grants` is the precise form of "opener" for a shared shell; `spawned` covers list-row provenance (`_live_list` reports `spawned or session`, :2142). `fg` is deliberately **not** refreshed here (no syscall per keystroke); a stale `fg` can only widen access for the session that *was* running there.

- Route edits — identical shape for all eight; order of answers: 400 (no session) → 404 (no such tty, unchanged) → 409 (mismatch) → the route's own logic.

| Route (line) | Edit |
|---|---|
| `keys` (:3387), `resize_pty` (:3542), `inject` (:4144) | after the dict check: `sid = _req_session(body)`; `if sid is None: return handler._json({"error": "session required"}, 400)`. In the existing `with _LOCK:` after `pt = PTYS.get(tid)`: `owned = pt is None or _pty_owned(pt, sid)`. After the existing 404: `if not owned: return _mismatch(handler, tid)`. |
| `close_pty` (:3421) | same 400; inside the lock, right after `pt = PTYS.get(tid)` and **before** the busy check and `pt.closing = True`: `if pt is not None and not _pty_owned(pt, sid): return _mismatch(handler, tid)` (the busy 409 already answers under the lock, :3470 — same precedent). |
| `attached` (:3676), `term_scrollback` (:3893) | `sid = _req_session(parsed=parsed)`; same 400 / owned / 409. |
| `screen_stream` (:3699), `raw_stream` (:4285) | same 400; inside the lock compute `mismatch = pt is not None and not _pty_owned(pt, sid)` and change the increment guard to `if pt is not None and not busy and not mismatch:` so a refused viewer never takes a `_STREAMS` slot; after the lock: 404, then `if mismatch: return _mismatch(...)`, then 429. |

- `server.py:192` (rename sync): pass `"session": sid` in the `term_vt.inject(...)` body — `_attached_pty(sid)` now returns a pty that runs `sid`, which always satisfies `_pty_owned` (folder → fg; dedicated → spawned/session).

**Folder shells with no session (the explicit rule):** `session=""` is valid **only** for a pty whose `p.session == ""` or whose `grants` contains `""` — i.e. one opened session-less by the launch pad (ext_launch.js:327) or the CR Terminals tab (ext_cr_term.js:629). A bare bookmarked `?tty=X` standalone link (no `sid`) therefore still works for those, and 409s for a session-opened pty — honest, and the status line says why.

### P3. Client changes — the shared seam (`aitracker/web/app.js`)

Placed directly after `track()` (:1386), before `let lastData` (:1393):

```js
// ---- Session isolation seam: ONE teardown both views use (classic + control room) ----
let sessEpoch=0;                         // bumped on every selection change
let sessAbort=new AbortController();     // aborts every in-flight session-scoped READ on a switch
let sessRefreshing=false;                // true while the shown detail is a cached snapshot
const SESSION_RESET=[];                  // fn(next, prev) — per-session state MUST register here
const SESS_CACHE=new Map(), SESS_CACHE_MAX=8;   // sid -> detail dict (d.id===sid), in-memory LRU
const STALE=Object.freeze({stale:true}); // identity sentinel: the selection moved mid-request
function onSessionReset(fn){ SESSION_RESET.push(fn); }
function sessToken(){ return {sid:cur, epoch:sessEpoch}; }
function sessCurrent(t){ return !!t && t.sid===cur && t.epoch===sessEpoch; }
// The ONE guarded fetch: captures (sid, epoch) at request time; resolves to the parsed JSON, or
// STALE if either moved. GETs ride sessAbort (cancelled on switch); writes are never aborted —
// they carry their session explicitly in the body, only their RESPONSE is dropped.
async function sessJSON(url, opts){
  const t=sessToken(), o=Object.assign({}, opts||{});
  if(!o.method||o.method==="GET") o.signal=sessAbort.signal;
  let r, j;
  try{ r=await fetch(url,o); j=await r.json().catch(()=>({})); }
  catch(e){ if(!sessCurrent(t)) return STALE; throw e; }
  if(!sessCurrent(t)) return STALE;
  if(!r.ok && j && j.error==null) j.error="http "+r.status;
  return j;
}
function sessCachePut(sid,d){
  if(!sid||!d||d.error||d.id!==sid) return;
  SESS_CACHE.delete(sid); SESS_CACHE.set(sid,d);
  while(SESS_CACHE.size>SESS_CACHE_MAX) SESS_CACHE.delete(SESS_CACHE.keys().next().value);
}
function sessCacheGet(sid){ const d=SESS_CACHE.get(sid); return d&&d.id===sid?d:null; }
// The ONLY way a detail dict reaches render(): refuses a payload for any other session.
function renderFor(sid,d){
  if(!sid||sid!==cur||!d||d.id!==sid) return false;
  lastData=d; render(d); return true;
}
function resetSession(next, prev){
  sessEpoch++;
  try{ sessAbort.abort(); }catch(e){}
  sessAbort=new AbortController();
  pollBusy=false;          // the aborted poll must not block the new session's first fetch (C7)
  lastData=null;
  SESSION_RESET.forEach(f=>{ try{ f(next, prev); }catch(e){ console.error("session reset hook",e); } });
}
```

`track()` becomes (keeps its localStorage/uiState lines verbatim):

```js
function track(){
  const prev=cur;
  cur=$("sid").value.trim(); localStorage.setItem("sid",cur);
  uiState.set('sid',cur);
  if(timer)clearInterval(timer);
  if(cur!==prev){
    resetSession(cur, prev);                         // synchronous: nothing of prev survives this line
    const hit=cur&&sessCacheGet(cur);
    sessRefreshing=!!hit;
    document.querySelector("main").dataset.sess=hit?"refreshing":(cur?"loading":"");
    if(hit) renderFor(cur, hit);                     // B's OWN snapshot, marked refreshing
  }
  if(!cur)return;
  poll();timer=setInterval(poll,2000);               // fires NOW — pollBusy was cleared above
}
```

`poll()` (:1468): pass `{signal:sessAbort.signal}` to its fetch; keep the seq/id guard and `finally{pollBusy=false;}` verbatim (tests pin both literals); replace `lastData=d;render(d);` with
`sessCachePut(id,d); sessRefreshing=false; delete document.querySelector("main").dataset.sess; if(!renderFor(id,d))return;` then the existing `loadFlags();checkCompletions(d);`. (An aborted poll lands in its `catch(e){return}` — already correct.) The late `finally` of an aborted poll may clear `pollBusy` under the new poll; harmless, the seq guard still discards it.

**Same-session idempotency:** `pick(A)` while on A → `cur===prev` → no reset, no cache paint, just an immediate poll (or the in-flight one lands). A→B→A → two resets; A's cached snapshot paints marked refreshing, the fresh poll replaces it; render() is signature/accumulator-driven (`narrState` re-inits on `id` change, :1838) so the result equals a fresh load. **Definition used:** session *data*, drafts, open modals/dialogs, search, accumulators and in-flight work are per-session and reset; *view preferences* (show-finished toggles, timeline filter, cards-folded, per-sid panel collapse in localStorage) persist — they are not session data.

#### P3.1 Classic hooks + guarded fetches (app.js)

Register once, right after the seam:

```js
onSessionReset(function(){
  closeDiff(); closeMsg(); curModal=null;
  curFiles=[]; curDiffFile=null; curDiffOps=[]; diffExpand=[]; curDiffText=null; diffAllExpanded=false;
  curNarr=[]; curCmds=[]; curReqs=[]; curOv={}; curShells=[]; curAgents=[]; curTodos=[];
  narrState={id:null,items:[],total:0};
  clearDetailSearch(); dSid=null; const c=$("dsearchcard"); if(c)c.style.display="none";
  const n=$("noteinput"); if(n)n.value="";
  notifSession=null; notifRunning=null;          // re-baseline: never announce A's completions under B
  document.title="tracker";
});
```

Switch each unguarded read to `sessJSON` and return on `STALE` (all URLs unchanged):
`runDetailSearch` (:1319), `moreNarr` (:1848 — `if(j===STALE||j.error)return null;`), `openDiff` (:1938 and the `/api/file` read :1941 — two calls, each checked), `openCmd` (:2105), `openShell` (:2129), `openAgent` (:2143). Writes: `addNote/removeNote/pushNote` (:2234-2258) capture `const sid=cur` before the await, send `session:sid` (they already send `cur`), and use `sessJSON(...,{method:"POST",...})` so the response is applied to `lastData` only if still current. `addFlag` (:2328): capture `sid=cur` before `prompt()` and send it. The `toggle*Done` re-renders (:2112-2114) stay `if(lastData)render(lastData)` — safe because `lastData` is now only ever set by `renderFor`.

CSS (`aitracker/web/app.css`, ~6 lines): `main[data-sess=loading]>*{visibility:hidden}` with `#drawerBtn{visibility:visible}` and a `main[data-sess=loading]::before{content:"Loading session…"}`; `main[data-sess=refreshing] #hmeta::after{content:" · refreshing…"}`.

#### P3.2 Control room

- `ext_cr_boot.js`
  - Next to the `EXT.push` (:1023): `if (typeof onSessionReset === 'function') onSessionReset(function (next, prev) { if (window.CR.dialogs && window.CR.dialogs.closeSession) window.CR.dialogs.closeSession(next); emit('session:reset', { id: next, prev: prev }); });`
  - The `EXT.push` detail update passes the authoritative id and cache flag: `window.CR.detail.update({ session: d, sid: d.id, refreshing: (typeof sessRefreshing !== 'undefined' && sessRefreshing), now: d.now, triage: computeTriage(d) })`.
  - `cr:drill-request` (:543): first line `if (!payload || payload.sessionId !== cur) return;`; replace the `fetch(...).then(r.json)` chain with `sessJSON(urlFn(sid, arg)).then(function (d) { if (d === STALE) return; ... })`; every `dialog(name, {...})` result call adds `sessionId: sid`.
- `ext_cr_dialogs.js`
  - `open()` (:443): store `sid: (payload && payload.sessionId) || ''` on the stack entry.
  - New `closeSession(keepSid)` exported on `window.CR.dialogs` (:2482): walk `_stack` top-down and, for every entry with `entry.sid && entry.sid !== keepSid`, run the same teardown as `close()` (`untrap()`, `wrap.remove()`, emit `dialog:closed`), splice it out, and set `aria-hidden` when the stack empties. Session-less dialogs (help, config, flags, manage-terminals, directory-picker) stay open — the Flags list is often the thing you clicked a session *from*.
- `ext_cr_detail.js`
  - In `mount` next to the `ctx.on("cr:pref", …)` listener (:1735), add `ctx.on("session:reset", …)` that: sets `ui.sid = null; ui._boundSid = null; ui.lastSession = null; ui.lastState = null; ui.lastTitle = ""; ui.lastGoal = ""; ui.spineSession = null; ui.spineNowMs = null; ui.diagramEntries = []; ui.timelineSeen = 0; ui.timelineStuckLatest = true; ui.flagOpen = ui.noteOpen = ui.searchOpen = false;` hides `.crd-flagcard/.crd-notecard/.crd-searchcard`; clears `.value` of `.crd-flag-input, .crd-note-queue-input, .crd-phone-input, .crd-plan-input, .crd-run-input, .crd-search-input`; adds `crd-is-loading` to the `.crd` node.
  - `renderUpdate` (:2156): `var sid = state.sid || session.id || ...` (authoritative id first — fixes the Auggie un-prefixed id); remove `crd-is-loading`; toggle `crd-is-refreshing` from `state.refreshing`.
  - `terminal-model/effort` (:1998): capture `var snap = ui.lastSession, sidMe = ui.sid, ttyMe = snap && snap.term_tty;` (same snapshot ⇒ same session by construction); `onPick` checks `if (ui.sid !== sidMe) { ctx.emit("notify", {text: "Session changed — not sent."}); return; }` then calls `_injectToTerminal(ctx, sidMe, ttyMe, …)`. `phone-stop` (:2034) likewise `_killTerminal(ctx, sid, ttySt)`.
  - `_injectToTerminal(ctx, sid, tty, text, failLabel)` / `_killTerminal(ctx, sid, tty)` (:2968/:2980): bodies become `{ tty: tty, session: sid, … }`; a 409 surfaces `res.j.error` ("terminal belongs to another session").
  - CSS (`ext_cr_detail.css`): `.crd.crd-is-loading .crd-col-body, .crd.crd-is-loading .crd-head {visibility:hidden}` + a loading line; `.crd-is-refreshing` dims the header meta.
- `ext_run.js`: `if (typeof onSessionReset === 'function') onSessionReset(function () { closeStream(); job = null; cwd = null; sid = ""; clear #runout, #runcmd.value, setState(""), disable #runkill; });` (replaces the cwd-only reset as the trigger — the `m.cwd !== cwd` branch at :141 stays as a harmless second guard). `run()` (:88) sends `session: cur` read at click time.

#### P3.3 Terminal callers — every tty leaves the page with its session (`ext_vt.js` owns the binding)

`ext_vt.js` loads standalone too (tests load it alone), so the binding lives there and is exported on `window.ExtVT` (:3845):

```js
// tty -> the session this page obtained it FOR ("" = a session-less shell). Written only where a
// tty ENTERS the page; every tty-addressed call reads it. Unbound => session omitted => server 400.
var TTY_SESS = {};
function bindTty(tty, sid, onlyIfNew) { if (tty && !(onlyIfNew && tty in TTY_SESS)) TTY_SESS[tty] = sid || ""; return tty; }
function ttySession(tty) { return (tty in TTY_SESS) ? TTY_SESS[tty] : null; }
function ttyBody(tty, extra) { var b = Object.assign({ tty: tty }, extra || {}), s = ttySession(tty); if (s !== null) b.session = s; return b; }
function ttyQuery(tty) { var s = ttySession(tty); return "tty=" + encodeURIComponent(tty) + (s === null ? "" : "&session=" + encodeURIComponent(s)); }
```

Bind sites (where a tty enters): `_openVTFresh`'s `/api/term/pty` response → `bindTty(res.j.tty, sid)` (the session it POSTed); `peekTerm(t)` (:3401) and every `/api/term/list` / 429-`terminals` row → `bindTty(t.tty, t.session, true)` (row provenance); `mountInto` target `{tty, session}` → `bindTty(target.tty, target.session, true)`; standalone `?tty&sid` (:3952) → `bindTty(tty, sid)`; `ContextBar(container, sid, ttyId, …)` (:2145) → `bindTty(ttyId, sid, true)`. Use sites (swap literal bodies/URLs, nothing else): `postKeys` :315, `postResize` :321, `fetchScrollback` :327, screen `EventSource` :901, raw `EventSource` :1920, ContextBar inject :2381/:2403, attached :2525, close :2745, superseded close :2928 (bind first — it is the POSTed sid), `closeTty` :3434, spawned close :3747. `closeTty`'s 409 branch: `if (j && j.busy) { …existing busy err… } else throw new Error(j.error || "HTTP 409")`.
`ext_cr_term.js`: inject :983 → `window.ExtVT.ttyBody(st.tty, {text:…, submit:true, clear_first:true})`; attached :1206 → `"/api/term/attached?" + window.ExtVT.ttyQuery(st.tty)`; its own `/api/term/pty {cwd}` open (:629) → `window.ExtVT.bindTty(res.j.tty, "")`. `ext_launch.js:327` `/api/term/pty {cwd}` → `bindTty(res.j.tty, "")` (lazily via `window.ExtVT`).

### P4. Sequencing (each commit leaves `make check` green and the UI working)

1. **Server data, no enforcement:** `d["id"]` in `parse_any`; `_attached_pty` → `_session_pty`; `Pty.grants` + the six `grants.add`; `_req_session` / `_pty_owned` / `_mismatch` defined but unused. Safe alone — nothing rejects yet; fixes C3's mis-binding (term_tty) immediately.
2. **Strict pair — atomic, one commit:** the eight route edits + `server.py` rename-sync `session` + all of P3.3 (bind/ttyBody/ttyQuery, closeTty discrimination) + the existing-test churn below. Server strictness and client callers **must** land together: either half alone 400s every keystroke.
3. **Client seam (classic):** P3 + P3.1 + app.css. Depends on (1) for `d.id`.
4. **Control room:** P3.2 (boot hook, drill guard, `closeSession`, detail reset listener, `state.sid`, explicit-session model/effort/stop, ext_run reset) + CSS. Depends on (3) for `onSessionReset`/`sessJSON`/`STALE`.
5. `make bundle` is optional packaging — do **not** hand-edit `dist/tracker.py`.

### P5. Tests (stdlib unittest; each listed test must be RED with its fix reverted)

**New / extended**

| File | Test | Red without |
|---|---|---|
| `tests/test_term_vt.py` — new `class TestSessionOwnership` (copy `TestRoutes` setUp/tearDown, :1031) | for each of keys, resize, inject, close, attached, scrollback, screen, raw: (a) no `session` → 400 `"session required"`; (b) fake pty `session="A"`, request `session="B"` → 409 with `mismatch: True`; (c) request `session="A"` → not 400/409 (keys via an `os.pipe()` fd so the write succeeds; close on a `pid=0` fake → 200 no-op path); (d) `screen`/`raw` mismatch does **not** increment `term_vt._STREAMS` or `pt.viewers`; (e) `?session=` (blank) on a `session=""` pty is accepted (keep_blank_values) and on a `session="A"` pty → 409; (f) close mismatch on a busy folder pty answers `mismatch`, not `busy`, and sets no `closing` | the route edits / `_req_session` |
| `tests/test_folder_terminal.py` — new `class TestFolderOwnership` | folder fake pty `session="A"`: B after `grants.add("B")` → keys OK; C (no grant, not fg) → 409; `fg={"session":"C",…}` → C OK; `""` → 409 unless `grants` has `""`; `spawned="Z"` → Z OK. Plus an `open_pty` round-trip using this file's existing spawn-stubbing idiom: a second session's `mode="cwd"` open on the same cwd returns the same tty **and** lands in `grants` | `grants` / `_pty_owned` |
| `tests/test_folder_terminal.py` — `class TestAttachedPtyForeground` | folder pty `session="A"`, `fg={"session":"B",…}`, `fg_pending=True` (so `_refresh_fg` leaves it), `_foreground_is_claude` patched True → `registry._attached_pty("B") is pty` and `_attached_pty("A") is None`; dedicated `mode="new"`, `session="A"` → `_attached_pty("A") is None` | P2.1 |
| `tests/test_title_sync.py` | rename sync's inject body carries `"session": "s1"` | server.py edit |
| `tests/test_selfcheck.py` | one assertion (conventions rule 9, both providers): `parse_any(<claude fixture id>)["id"] == <id>` and the same for the Auggie fixture's `auggie:`-prefixed id | `d["id"]` |
| `tests/test_session_isolation.py` (new; node idiom from `test_integration.py`'s `_extract_js_block` :1794 + its `_MOCKS` fetch stub, copied, `skipUnless(node)`) | (1) `sessJSON` resolves `STALE` when `cur` changes mid-flight, and when A→B→A bumps the epoch with `cur` back to A; (2) GET gets a `signal`, POST does not; (3) `track()` with A's poll in flight issues B's `/api/session` fetch **synchronously** (C7); (4) `track()` same sid twice → `SESSION_RESET` hooks not called; change → called once with `(next, prev)`; (5) `renderFor` refuses `d.id !== sid` and `sid !== cur`; `sessCacheGet` never returns a mismatched-id entry; LRU evicts past 8; (6) cache hit paints before the fetch resolves with `dataset.sess === "refreshing"`, no hit → `"loading"` | the seam |
| `tests/test_session_isolation.py` (static sweep — the "future panels can't forget" guard, pattern of `test_inject_reason_surface.py`) | every `"/api/term/(keys|resize|inject|close)"` POST body in `aitracker/web/*.js` is `ttyBody(...)` or a literal containing `session`; every `"/api/term/(screen|raw|scrollback|attached)?` URL is built with `ttyQuery(`; every `fetch(` in app.js whose URL contains `encodeURIComponent(cur)` goes through `sessJSON`; ext_cr_detail.js's `session:reset` listener clears each of the six input selectors | P3.x |
| `tests/test_session_isolation.py` (full-bundle harness, `test_cr_crossview.py` idiom; use `test_cr_logic.py`'s tracked-DOM variant if values must be read) | after `CR.detail.update({session:A, sid:A})`, a typed `.crd-flag-input`, and an open `rename` dialog for A: `resetSession("B","A")` → input empty, `CR.dialogs.topName()` is not `rename`, a session-less `flags` dialog stays | P3.2 |

**Expected churn (existing tests that pin old literals — update, do not delete):** `test_term_vt.py` (~60 route calls) and `test_folder_terminal.py` (5) and `test_inject_footer_quiet.py` (6) need `"session": <the fake's session or "">` in bodies / `&session=` in queries — mechanical, one `sweeper` pass; `test_term_vt_exec.py` :2297/:2338 inject body expectations gain `session` (bind `tty42` in the harness), :4825 extracts the literal `var ttyMe = ui.lastSession && ui.lastSession.term_tty;` (re-anchor on the new capture line); `test_integration.py` `TestPollerInFlightGuardExecuted` fixtures need `id:"sess1"` (renderFor is strict), plus `_MOCKS` stubs for `sessAbort`, `renderFor`/`sessCachePut`, `sessRefreshing` and `document.querySelector("main")` (poll now touches them) — or keep poll's new lines behind one small `sessLanded(id,d)` helper so the mock set grows by one function; `test_cr_manage_terminals_parity.py` :790 force-retry body; `test_term_vt_client.py` string pins on `'"/api/term/raw?tty="'` (:678).

**Gate:** `unset TRACKER_AUTH; make check` (blanket 401s otherwise). The full gate can be OOM-killed (`Killed: 9`, no failures) — run one module per process: `unset TRACKER_AUTH; python -m unittest tests.test_term_vt` etc. `git commit` runs the full gate via hook: give Bash > 300s. A lone `term_vt` backstop flake under load passes in isolation. Never `git stash`; revert-to-prove-red with a scoped Edit.

### P6. Risky spot + fallback

**Risk 1 (highest): a terminal path that obtains a tty without going through a bind site** → its calls go out without `session` → 400, the terminal looks dead. Paths most likely to be missed: ext_cr_term.js's `mountInto` handle, the 429 capacity-list close, the superseded-open close (ext_vt.js:2928), bookmarked `?tty=` without `sid`. Mitigation: the static sweep test; the 400/409 body names the reason, and VT status lines surface it. Manual pass before push: classic "terminal here", "resume here", CR Terminals tab new folder shell, manage-list kill (busy confirm), launch pad, standalone tab, model/effort/stop from CR detail. **Fallback:** fix the missing bind site — never relax `_pty_owned` (strict mode is the contract).
**Risk 2:** `main[data-sess=loading]` hiding the column could hide something a hook doesn't repaint (e.g. a panel that only renders on change). Fallback: swap `visibility:hidden` for `opacity:.35; pointer-events:none` — old content then remains *visible but inert* for <1 poll, which still never accepts input for the wrong session because every action captures its sid.

### P7. Decisions you may want to overrule

1. **Ownership = grants ∪ opener ∪ spawned ∪ foreground**, not strictly "opener OR foreground". Reason: folder shells are shared per cwd, so opener-only breaks the second session's own terminal in any repo with more than one session. Consequence: two sessions in the same directory can both type into that shared shell (it is visibly the same terminal). Stricter alternative: no grants, and folder-shell sharing turns into one shell per (cwd, session) — a bigger behaviour change to term_vt.
2. **No-cache switch hides the old column (loading state) rather than dimming it; cache is 8 entries, in memory only** (never written to localStorage — no transcript data at rest in the browser). View preferences (show-finished, timeline filter, per-sid panel collapse) persist across switches; only session data/drafts/dialogs reset. Also: forked ptys no longer report `term_tty` for the parent session (they run a different session id).

## Adversarial review
_(opus reviewer — pending)_

## Reconciliation
_(pending)_

## Log
- 2026-11-02 worktree cut; diagnosis recorded.
- 2026-11-02 plan written by opus agent (C5 discharged). User chose strict mode. Implementation split: round 1 parallel — sonnet S (P2+P3.3+server tests, stages 1+2 atomic), sonnet C (P3+P3.1 classic seam + cache, stage 3); round 2 — sonnet D (P3.2 control room, stage 4 + sweep test). Agents don't commit; main thread commits per stage by explicit path.
- 2026-11-02 stages 1-3 committed 52eef86 (hook gate green). Main-thread fixes during integration: (a) session-switch CSS moved above the `html.tracker-readonly` tail block (test_cr_readonly_ui requires that block last); (b) `_attached_pty` regression — plan's `_session_pty` returned only the FIRST running pty, so a session with two resume ptys (first dropped to shell) read as unattached; added generator `term_vt._session_ptys(sid)`, `_attached_pty` checks every candidate (test_cr_registry_fields.test_multiple_ptys_one_attached_one_not); (c) test_cr_registry_fields fakes gained `mode="resume"` (opener-only no longer counts as running). Per-module gate: 88/88 + selfcheck ok. Stage 4 → sonnet D.
