# Remove (hide) a session from the dashboard: technical plan

Worktree: `.claude/worktrees/remove-session`, branch `worktree-remove-session`, base `personal/main` @ `0c93bfc`.

## Contract (verbatim user ask)

> "can we have a button for each session in the sessions view and in the board view to remove sessions as well"

| Clause | Plan answer |
|---|---|
| a button for each session | One button per row and per tile, rendered by the shared renderers `railRow()` and `sessionTile()` |
| in the sessions view | `railRow()`, which the Sessions view uses (`renderSessionsView` -> `railRow(s, now, {rich:true})`). The rail uses it too, so the rail gets the button as well (Decision 1). |
| and in the board view | `sessionTile()` -> `tileHead()` head row, next to the agent-map / resume buttons |
| to remove sessions | **Removal hides the session from the dashboard. It never deletes anything.** Details below. |

## What "remove" means (conventions rule 6)

The tracker is read-only with respect to session logs. **Removing a session never deletes, moves or edits a `*.jsonl` transcript, an Auggie session file or anything under `~/.claude` / `~/.augment`.** It writes one entry to a new app-owned JSON file, `hidden.json`, which sits beside `pins.json` and is gitignored like it. `/api/list` then leaves that session out. Deleting `hidden.json` brings every removed session back, and the logs are untouched the whole time.

A removed session **comes back automatically when it shows new activity**: its list-dict `mtime` becomes newer than the hidden-at time. So removing a session that is later resumed, or that still has a background agent writing, can never hide live work.

## Verified seams (read in the worktree)

- `aitracker/config.py:34` `PINS_FILE = os.path.join(_HERE, "pins.json")`. `_HERE` is the `aitracker/` package dir. `.gitignore` entries are unanchored (`pins.json`, `forks.json.lock`, ...).
- `aitracker/store.py:10/18` `_load_json`/`_save_json`. `:55` `load_pins()`. `:353` `_update_json(path, mutate)` does a flock'd read-modify-write, always on a dict, with lock file `path + ".lock"`.
- `aitracker/registry.py:21` `all_sessions()`. Each provider's rows are collected into `out` (`:23-33`), annotated (`:89-130`), and sorted `:131` (pinned first, then `-mtime`). The import line `:11` must stay **one line** because `scripts/bundle.py` strips imports line by line (see the NOTE at `:8-10`).
- `mtime` is on every list row from every provider: claude.py `:1111` ("counts background-agent activity too"), auggie.py `:347/:373/:520`, augment_ext.py `:197/:304/:343`. Search hits carry `mtime` too (claude.py `:1245`, auggie.py `:816/:889`). This is the last-activity field.
- Callers of `all_sessions()`:
  - `server.py:483`: GET `/api/list`. This is the only user-facing list.
  - `registry.newest_models():159`: model-update nudge.
  - `agent_cli.py:364`: Agents panel, the live Auggie sessions to restart.
  - `term_vt.py:4106`: the New-terminal directory picker.
  - The last three are machine-facing. Hiding a session must not change them (an Auggie session still needs its upgrade restart, and its model still counts).
- Every SPA list surface reads the same `/api/list` array:
  - The classic sidebar uses app.js `sessions` (fetched `:1328`).
  - CR board, rail, triage and Sessions view: `ext_cr_boot.js:1019-1021` passes that same array into `CR.board.update({sessions: list})`, and `ext_cr_board.js:3229` stores it as `lastState`.
  - CR dialogs and term (`:1029/:1032`) get it too.
  - So filtering `/api/list` on the server makes every list and count agree, with no client re-derivation (rule 5).
- Search:
  - `registry.search_all():400` merges each provider's `search()`. It does **not** go through `all_sessions()`, so removed sessions stay searchable.
  - The Sessions view shows hits through `decorateSearchHits()` (`ext_cr_board.js:1690`, called `:1815`), which keeps hits that are not in the list.
  - The rail's `railRowsFor()` (`:1193`) intersects hits with the list, so removed sessions never show in the rail.
  - `parse_any()` is untouched, so opening a removed session still works.
- POST guards: `server.py:661-675` runs CSRF (`:663`), auth (`:667`) and read-only deny-all (`:669`) before any route. A route placed after them inherits all three. `/api/pin` is at `:885-893`. The server is `ThreadingHTTPServer` (`:2`, `:1022`), so concurrent POSTs really happen.
- Toast with an action already exists: `ext_cr_dialogs.js:273` `toast({title, meta, actionLabel, onAction, duration})`, reached through `ctx.emit('notify', payload)` (`:375`). The bus passes the payload object by reference (`ext_cr_boot.js:43-48`), so an `onAction` function survives.
- Row buttons: `railRow` `.cr-rail-actions` holds `[mapBtn, pin, rename]` (`ext_cr_board.js:2100-2117`). Tiles append buttons to `head` (`:2906-2921`) and `readOnly` is computed at `:2903`. CSS selector lists for the rail buttons are at `ext_cr_board.css:1061-1092` and for `.cr-tile-map` at `:1791-1813`.
- The icon set has `x` and `return` (app.js `:84-85` ICO tables). There is no trash icon, and none is needed.
- `dist/` is gitignored and generated, so it needs no edit. `make bundle` keeps working as long as the registry import stays on one line.

## Design

### JSON shape: `aitracker/hidden.json`

```json
{"<session id>": 1763380000.123, "auggie:<id>": 1763380100.0}
```

The value is the hidden-at time as epoch seconds (`time.time()`, the same clock as the providers' `os.path.getmtime`). A dict rather than a list (unlike pins) because the reappear rule needs the timestamp.

### Server policy (registry, the shared seam)

A session is hidden **iff** `hidden.get(id)` is a number **and** `row.mtime <= hidden_at`. Any newer activity makes it visible again. The stale entry is left in place and is inert. The list read never writes.

### Undo and recovery (recommendation)

1. **Undo toast**, almost free because `toast()` already supports `actionLabel`/`onAction`. It reads "Session removed", with meta "Comes back if it becomes active again", an **Undo** action, and the default 8 s duration (held while hovered).
2. **Restore from search.** `search_all()` marks each hit `hidden: bool` with the same predicate. The Sessions view then shows a removed session in search results, and its button turns into **Restore** (`return` icon), which POSTs `hidden:false`. This is the durable path after the toast has gone, with no new panel and no "show removed" toggle.

There is no `confirm()` dialog anywhere.

### Live sessions and the open detail view

- **Allowed.** A live or working session can be removed. If it writes again it comes straight back, which the toast text explains.
- If the removed session is open in the detail view, the detail view stays open: `parse_any` is unaffected. Only the row or tile goes. This needs no special case, because sessions already drop out of the list when they leave the 200 window.

## Files and changes (in landing order)

1. **`aitracker/config.py`**: below `PINS_FILE` (`:34`) add
   `HIDDEN_FILE = os.path.join(_HERE, "hidden.json")`. Other code reads it late-bound as `config.HIDDEN_FILE`.
2. **`.gitignore`**: add `hidden.json` and `hidden.json.lock` next to `pins.json`.
3. **`aitracker/store.py`**: after `load_pins()` (`:58`):
   ```python
   def load_hidden():
       """{session_id: hidden_at_epoch} -- sessions the user removed from the dashboard. Read live.
       Hiding never touches a transcript (conventions rule 6)."""
       d = _load_json(config.HIDDEN_FILE, {})
       return d if isinstance(d, dict) else {}

   def set_hidden(sid, hidden):
       """Record (hidden=True, stamped now) or clear one id, under _update_json's flock so rapid
       multi-row removals (concurrent POSTs on ThreadingHTTPServer) don't lose each other's write."""
       def mutate(d):
           if hidden:
               d[sid] = time.time()
           elif sid in d:
               d.pop(sid)
           else:
               return False
       _update_json(config.HIDDEN_FILE, mutate)
   ```
   `_update_json` is defined later in the file (`:353`). That is fine because the name is resolved at call time.
4. **`aitracker/registry.py`**:
   - Add `load_hidden` to the existing **single-line** `from .store import ...` (`:11`).
   - Add the module-level predicate:
     ```python
     def is_hidden(row, hidden):
         """Removed from the dashboard and NOT active since: hidden-at present and row mtime <= it."""
         at = hidden.get(row.get("id", ""))
         return isinstance(at, (int, float)) and (row.get("mtime") or 0) <= at
     ```
   - Change the signature to `def all_sessions(include_hidden=True):`. Right after the provider loop (`:33`, before the pins/forks work):
     ```python
     if not include_hidden:
         hidden = load_hidden()
         if hidden:
             out = [s for s in out if not is_hidden(s, hidden)]
     ```
   - The default is `True`, so `newest_models`, `agent_cli` and `term_vt` keep their current behaviour with no edits. Only the user-facing route opts in. If a future list surface forgets to opt in, the session shows (fail-visible), which is the safe direction.
   - In `search_all()`, after the sort: `hidden = load_hidden()`, then `for r in out: r["hidden"] = is_hidden(r, hidden)`. This is the shared seam, so every provider's hits get it.
5. **`aitracker/server.py`**:
   - `:483`: change to `self._json(all_sessions(include_hidden=False), headers=headers)`.
   - Add a new route directly after `/api/pin` (`:893`). It inherits the CSRF, auth and read-only guards:
     ```python
     if p.path == "/api/hide":
         # Remove-from-dashboard: app-owned hidden.json only -- never touches a session log (rule 6).
         sid = body.get("session")
         if not isinstance(sid, str) or not sid:
             return self._json({"error": "session required"}, 400)
         set_hidden(sid, bool(body.get("hidden")))
         self._json({"ok": True})
         return
     ```
     Add `set_hidden` to server.py's single-line `from .store import ...` (`:16`).
6. **`aitracker/web/ext_cr_board.js`**:
   - New `function toggleSessionHidden(s)`, next to `toggleSessionPin` (`:2204`):
     - If `typeof fetch !== 'function'`, return.
     - Set `next = !s.hidden` and POST `/api/hide` with `{session: s.id, hidden: next}`.
     - If the response is not ok, do nothing.
     - On ok with `next === true`: remember `idx`/`row`, set `lastState.sessions = lastState.sessions.filter(x => x.id !== s.id)` (a new array, not a splice into app.js's array), and call `renderRail(lastState); renderBoard(lastState); renderTriage(lastState); renderSessionsView(lastState)`. Then emit:
       ```js
       ctx.emit('notify', {
         title: 'Session removed',
         meta: 'Comes back if it becomes active again',
         actionLabel: 'Undo',
         onAction: function () { /* POST hidden:false; on ok re-insert row at idx and re-render */ }
       })
       ```
     - On ok with `next === false` (Restore from a search hit): set `s.hidden = false` and call `renderSessionsView(lastState)`. The next 5 s poll brings the row back.
   - Both new buttons get the `x` icon when hiding and `return` when restoring, with aria-label / title `'Remove from dashboard (log is kept)'` and `'Restore to dashboard'`.
   - `railRow` (`:2100`): append a fourth button to `.cr-rail-actions`, but not when read-only:
     ```js
     h('button', {
       class: 'cr-rail-remove', type: 'button',
       onclick: function (e) { e.stopPropagation(); toggleSessionHidden(s); }
     }, [glyph(s.hidden ? 'return' : 'x', '')])
     ```
   - `decorateSearchHits` (`:1690`): add `hidden: !!hit.hidden` to the returned object.
   - `sessionTile` (`:2921`, after the agent-map button): when `!readOnly`, `head.appendChild(...)` a button with `class: 'cr-tile-map cr-tile-remove'` (it reuses the map button's sizing and hover CSS), `'data-act': 'remove'`, and `stopPropagation` plus `toggleSessionHidden(s)` on click.
7. **`aitracker/web/ext_cr_board.css`**:
   - Add `.cr-rail-remove` to each rail-button selector list at `:1061-1092`: base, hover/focus-within reveal, `:hover`, and `@media (hover:none)`.
   - Optionally add `.cr-tile-remove:hover, .cr-rail-remove:hover { color: var(--text-failed); }`. That token already exists in `ext_cr.css`; never add a new colour literal.

Out of scope: the classic `app.js` `sessionRow`. A removed session disappears there too, because it is the same `/api/list`, but classic gets no button. The detail-view header gets no button either.

## Tests: one assertion per behaviour, each RED with its fix reverted

All tests go in **`tests/test_cr_routes.py`**, using the existing server harness:

- **Prerequisite:** add `"HIDDEN_FILE"` to `_PATHS` (`:36-38`) and `config.HIDDEN_FILE = tempfile.mktemp(suffix=".json")` in `_empty_env` (`:89-97`). Without these, tests would write the developer's real `aitracker/hidden.json`.

| # | Test | Assertion | Goes RED when reverted |
|---|---|---|---|
| T1 | `test_hide_route_round_trips` | `_write_claude("h1")`. POST `/api/hide {session:"h1", hidden:true}` returns 200 and `h1` is absent from GET `/api/list`. Then POST `hidden:false` and `h1` is present again. A bad body `{}` returns 400. | Revert the route and the POST hits the fall-through (no 200 and no filter). Revert the `/api/list` opt-in and `h1` stays listed. |
| T2 | `test_hidden_filter_spans_providers_and_keeps_internal_callers` | Write `_write_claude("h2")` and `_write_auggie("a2", "t")`, and write `config.HIDDEN_FILE` directly as `{"h2": now+60, "auggie:a2": now+60}`. Both are absent from `registry.all_sessions(include_hidden=False)` and both present in `registry.all_sessions()` (default). | Revert the filter and they are listed. Flip the default and the internal-caller half fails. |
| T3 | `test_hidden_session_reappears_on_new_activity` | `_write_claude("h3", mtime=now-100)`, then POST hide, then confirm absent. `os.utime(path, (now+5, now+5))` and it is listed again with no un-hide call. | Change the predicate to "id in hidden" (drop the mtime comparison) and the session stays hidden. |
| T4 | `test_search_marks_hidden_hits` | A hidden Claude session is still returned by `/api/search?q=<its prompt>` with `hidden: True`, and a non-hidden one has `hidden: False`. | Revert the `search_all` annotation and the key is missing. |
| T5 | `tests/test_cr_remove_session.py` (node, `_HAS_NODE` skip guard) | Copy the DOM-stub harness from `tests/test_cr_rail_row_parity.py` (`_read_page`, `_run_node`, `make_session`, recorded `addEventListener`). Mount the board with one session. Check: (a) the rail row contains `.cr-rail-remove` and the tile contains `[data-act="remove"]`; (b) clicking it calls a stubbed `fetch` with `/api/hide` and body `{session, hidden:true}`, and the row's own `openSession` click does **not** fire (stopPropagation); (c) with `ctx.readOnly()` true, neither button renders. | Remove the button, the stopPropagation or the readOnly gate, and the matching sub-assertion fails. |

Gate: `unset TRACKER_AUTH; make check` prints `selfcheck ok`. Per memory, run it one module per process if the full run gets OOM-killed, and the known flaky `term_vt` backstop is not this change. Each of T1-T5 is proven RED by reverting just its fix line with a scoped Edit (never `git stash`), then restored. This is a UI and server change, so restart with `make serve` to see it (rule 11).

**Regression watch:** `tests/test_cr_board_resume_button.py` and `tests/test_cr_agent_map_entry.py` inspect tile head buttons. If either pins an exact button count or order, update it as an expected consequence. A fourth rail action button is also expected.

## Risky spot and fallback

**Spurious reappearance or flicker caused by the `mtime` rule.**

- A Claude row's `mtime` includes background-agent writes (claude.py `:2486`), and Claude Code may append bookkeeping lines (title or summary) to an idle transcript. Either can bring a removed session back unasked.
- A `/api/list` poll that started before the POST finished can briefly re-show a removed row for one poll, because the rows are removed only after `r.ok`, the same way pin works.
- Both errors fail visible, never invisible. That is the deliberate direction for a dashboard of live work.
- **Fallback** if users find the reappearance noisy: compare against a grace period (`mtime > hidden_at + LIVE_WINDOW`), or ignore `mtime` for sessions that have `ended`. This is a one-line change to `is_hidden`, and T3 would be adjusted to match.

A secondary note, not a defect: each provider caps the list at 200 before the filter runs, so removing sessions leaves fewer than 200 visible. Older sessions do not backfill.

## Decisions the user may want to overrule

1. **Where the button shows.** `railRow` is shared, so the button appears in the **left rail as well as the Sessions view**: one implementation, parity with pin and rename. The alternative is to gate it to the Sessions view only (`opts.rich`), at a cost of one condition.
2. **Recovery and the reappear rule.** The plan uses an Undo toast plus Restore from search, and the session auto-reappears on new activity. The alternatives:
   - (a) Drop the search-restore. That saves about 6 lines, but after 8 s the only way back is hand-editing `hidden.json`.
   - (b) Make removal sticky even through new activity. That is simpler, but it can hide a resumed, working session.

## Adversarial review

Reviewer: opus, adversarial ("assume the plan is wrong"). Every claim was checked against the worktree with grep and `sed -n` ranges, plus read-only measurements of the real `~/.claude/projects/*.jsonl` and `~/.augment/sessions/*.json`. Nothing was written except this file.

### Claims that held up

- `config.PINS_FILE` (`config.py:34`) and the unanchored `.gitignore` entries are as the plan states. `store._update_json(path, mutate)` is at `store.py:353`. Lock = `path + ".lock"`. `mutate` returning `False` skips the save. `time` is already imported (`store.py:1`).
- The registry single-line import (`registry.py:11`) and the bundle line-strip (`scripts/bundle.py:41`) are real. The names `is_hidden`, `load_hidden`, `set_hidden` and `HIDDEN_FILE` collide with nothing in the flat bundle.
- `all_sessions()` callers are exactly `server.py:483`, `registry.py:159`, `agent_cli.py:364` and `term_vt.py:4101`.
  - Every CR surface (rail, board, triage, Sessions view, dialogs, term) is fed from app.js `sessions`, which is the `/api/list` body (`app.js:1328` → `ext_cr_boot.js:1019-1032`).
  - `board.update` has exactly one caller.
  - No SSE or second list path exists.
- POST guards (`server.py:663-669`) cover a new route. `toast()` supports `actionLabel`/`onAction` (`ext_cr_dialogs.js:273-290`), and the bus passes the payload by reference.
- Icons `x` and `return` exist in both ICO maps. `--text-failed` exists (`ext_cr.css:86/341`).
- `_PATHS` (`test_cr_routes.py:36-38`) and `_empty_env` (`:67-100`) are real names. `_write_claude(sid, prompt, cwd, mtime)` and `_write_auggie(sid, title, ...)` match the plan.
- Auggie list `mtime` is content-based. File mtime minus `modified` was 0 s on all 30 newest real Auggie sessions, in the same epoch-second units as `time.time()`.
- **Regression watch is a non-issue.**
  - `test_cr_board_resume_button.py` counts buttons by class only (`cr-tile-resume` / `cr-tile-action`, `:66-96`).
  - `test_cr_agent_map_entry.py:253-254` source-pins the map-button text. Inserting **after** the `if (s.agent_map_n > 0) {...}` block keeps both pins valid.
  - No test touches `.cr-rail-actions`.

### Findings (each with defect, fix direction, way, and the test that proves it)

| # | Sev | Finding | Verdict |
|---|---|---|---|
| R1 | **High** | The reappear rule keys on raw transcript `mtime`. Claude Code bumps that mtime with no activity at all, so removed sessions come back unasked. | confirmed (measured) |
| R2 | Med | Removing a **working** session does nothing lasting. It writes again within seconds and reappears on the next poll, and most Board tiles are live. | confirmed |
| R3 | Med | Restore from search, and Remove inside search results, never show their effect. `decorateSearchHits` rebuilds fresh objects every render, so `s.hidden = false` on the copy is lost. | confirmed |
| R4 | Low | The search `hidden` predicate uses a different `mtime` than the list (search hits use raw file mtime, the list includes agent files), so the two can disagree. | confirmed |
| R5 | Low | Pressing Enter on a focused rail Remove button also opens the session you just removed. The row's keydown has no target check. | confirmed (pre-existing for pin/rename) |
| R6 | Low | The Undo "re-insert at idx" is overbuilt, and the triage j/k nav keeps the removed id until the next poll. | overengineered |
| R7 | Nit | The "LIVE_WINDOW grace" fallback in the risk section does not address the real cause (see R1). | false remedy, drop it |
| R8 | Info | Hiding a parent leaves its agent child sessions in the Agents buckets and board group tiles. Group tiles get no button. | known gap, document it |

**R1. A raw-mtime reappear un-hides on Claude Code bookkeeping writes (High).**

- **Defect.** The plan has `registry.is_hidden` compare `row["mtime"]`. For Claude that is `_mtime_bg_n` → `os.path.getmtime` of the transcript (`claude.py:1308`, `:1111`). Claude Code appends **untimestamped** bookkeeping lines to idle transcripts: `cost-state`, `tools-used`, `last-prompt`, `mode`, `ai-title`.
- **Measured on this machine:**
  - 41 of the 60 newest transcripts have a file mtime more than 300 s after their newest timestamped line. One example: last event 12:11Z, mtime bumped at about 19:39Z, tail `cost-state`.
  - 48 transcripts share one identical mtime to the second (a bulk touch), and their last events were 164 to 3300 hours earlier.
  - Every line type that carries a `timestamp` is real activity: `user`, `assistant`, `attachment`, `queue-operation`, `system`, `api-request`, `pr-link`, `continued-in`.
  - None of the bookkeeping types carries one.
- **Repro.** Remove an idle session that is still open in a terminal, then close that terminal. Claude Code appends `cost-state`, the mtime becomes greater than `hidden_at`, and the session is back. Expected: it stays removed.
- **Fix direction.** Base "new activity" on the newest **timestamped** line, not the file mtime. Must NOT change:
  - `mtime` itself, which liveness, sorting and `now_line` all read;
  - the read-only rule;
  - the fail-visible fallback.
- **Way.**
  1. In `claude._tail_scan_raw` (`claude.py:117`), initialise `last_ts = ""`. In the line loop, right after `o = json.loads(line)`, add `t = o.get("timestamp"); if isinstance(t, str) and t > last_ts: last_ts = t`. Use max, not last, because hook rows can arrive out of order (`claude.py:1421`). Add `"last_ts": last_ts` to the return dict (`:278`).
  2. In `_session_meta` (`claude.py:331`), add `"active": _ts_epoch(ts["last_ts"]) if ts["last_ts"] else 0.0`, and add `"active": 0.0` to the OSError fallback dict (`:297`).
  3. In the `list_sessions` row (`claude.py:1111`), add `"active_at": sm.get("active") or mt`. The `mt` fallback keeps the result fail-visible.
  4. Make the predicate `(row.get("active_at") or row.get("mtime") or 0) <= at`. Auggie and the Augment extensions fall through to `mtime`, which is content-based and honest. One seam, no per-provider fork.
- **Test (RED with the old predicate).**
  - New **T3b `test_hidden_session_ignores_bookkeeping_bump`**: write a Claude session whose user line carries `"timestamp": iso(now-100)`, hide it, append `{"type":"cost-state"}` (no timestamp), run `os.utime(now+5)`, and assert it is still absent from `/api/list`.
  - Rewrite **T3** to append a `{"type":"user","timestamp": iso(now+5), ...}` line (real activity) and assert it is listed again.
  - T3b goes RED if the predicate is reverted to `mtime`.

**R2. Remove on a working session is a no-op (Medium).**

- **Defect.** `boardTiles` and `sessionState` (`ext_cr_board.js:82-90`) put working sessions on the Board. A working session writes timestamped lines every few seconds, so under either reappear rule a removed working tile is back on the next 5 s poll. The button promises something it cannot deliver.
- **Repro.** Click Remove on a "working" tile. The toast says "removed", and the tile is back within about 5 s.
- **Fix direction.** Do not offer Remove while `state === 'working'`. Keep it for awaiting, flagged, failing, landed and idle. Must NOT change the auto-reappear safety.
- **Way.**
  - `railRow` already has `var state = sessionState(s, now)` (`:1922`). Render the button only when `!readOnly && state !== 'working'`.
  - In `sessionTile`, `state` is `t.state` (`:2881`), so the same condition applies there.
- **Test.** T5(d): a working session (`mtime = NOW - 5`, `ended: false`) has no `.cr-rail-remove` and no `[data-act=remove]`. RED without the condition.
- **This is a user decision.** The alternative is to keep the button and accept "comes back immediately".

**R3. The search Restore and Remove state flip is lost on re-render (Medium).**

- **Defect.**
  - `renderSessionsView` (`:1815`) re-decorates from `sessionsSearchResults` on every render. Setting `s.hidden = false` on the decorated copy and re-rendering puts the button straight back to Restore.
  - Removing a non-hidden hit in search mode filters `lastState.sessions`, but search mode renders `sessionsSearchResults`, so nothing visible changes. A second click re-stamps it.
- **Repro.** Search for a removed session and click Restore: the button stays on Restore. Search for a visible session and click Remove: the row stays and keeps showing Remove.
- **Fix direction.** Flip the flag on the **source** search array. Must NOT re-fetch search.
- **Way.** In `toggleSessionHidden`, on `ok`, run `(sessionsSearchResults || []).forEach(function (r) { if (r.id === s.id) r.hidden = next; })` before re-rendering.
- **Test.** T5(e): stub `fetch` so `/api/search` returns `[{id:'h', hidden:true}]` and `/api/hide` returns `ok`. Drive the query, flush, click Restore, flush, and assert the row's button `aria-label` is now "Remove from dashboard (log is kept)". RED without the forEach.

**R4. Search `hidden` must not re-run the predicate (Low).**

- **Defect.** Claude search hits carry `mtime: os.path.getmtime(f)` (`claude.py:1245`). That excludes agent files and is not `active_at`, so `search_all` running `is_hidden` can say `hidden: true` for a row the list shows.
- **Fix direction.** The server reports only "the user removed this id", and the client shows Restore only when the hit is also absent from the current list. This combines two server facts and re-derives no threshold.
- **Way.**
  - `search_all` (`registry.py:410`): after the sort, `hidden = load_hidden()`, then `for r in out: r["hidden"] = r.get("id") in hidden`.
  - `decorateSearchHits` (`:1690`): add `hidden: !!hit.hidden && !known`.
- **Test.** Change T4 to: a hidden-and-active session (timestamped line after `hidden_at`) is listed, its search hit has `hidden: True`, and in T5 a hit that is also in `sessions` renders Remove, not Restore.

**R5. Enter on a rail button also opens the session (Low).**

- **Defect.** The rail row has `onkeydown: function (e) { if (e.key === 'Enter') openSession(s.id); }` (`ext_cr_board.js:2123`). Enter on a focused child `<button>` fires its click (Remove) and then bubbles keydown to the row (open). The tile already guards this case (`:2669`).
- **Repro.** Tab to Remove and press Enter. The session is removed, and the detail view of that same session opens.
- **Fix direction.** Make the row activate only when it is the target itself. Must NOT change what Enter does on the row.
- **Way.** Change that line to `if (e.key === 'Enter' && e.target === e.currentTarget) openSession(s.id);`. This also fixes the same latent bug for pin and rename.
- **Test.** T5(f): call the row's `_listeners.keydown({key:'Enter', target: removeBtn, currentTarget: row})` and assert no `go` was emitted. Then call it with `target: row` and assert one `go`. The first half goes RED without the guard.

**R6. Undo is overbuilt (Low).**

- **Defect.** Remembering `idx` and `row` and splicing the row back adds client bookkeeping that the next poll does anyway. Separately, `ext_cr_boot.js` triage and j/k read app.js `sessions` (the global), which still holds the removed id until the next `loadSide`.
- **Way.**
  - On remove `ok`, keep the optimistic `lastState.sessions = filter(...)` plus the re-renders for instant feedback, then call `if (typeof loadSide === 'function') loadSide();`. This follows the precedent at `ext_cr_boot.js:648`.
  - Undo becomes: POST `hidden:false`, then on `ok` call `loadSide()` (same guard).
  - Drop `idx` and the re-insert. `loadSide` is a no-op while a poll is in flight (`sideBusy`), and the next 5 s tick covers that.
- **Test.** No new test. T5(b) still checks the POST body.

**R7. Drop the "LIVE_WINDOW grace" fallback (Nit).** The measured gaps are hours to months, so `+300 s` would not stop a single one of the observed spurious reappearances. R1 replaces it.

**R8. Child sessions and group tiles (Info).** No change. Note in the PR that removing a parent does not remove its agent sessions from the Agents buckets or board group tiles, and that group tiles get no Remove button.

**Overengineering check (ponytail).**

- `include_hidden=True` param: fine. It is fail-visible for internal callers, and a route-side comprehension would be equivalent. Keep it.
- `_update_json` lock: keep. It reuses an existing helper at zero extra lines. `/api/pin`'s unlocked write is a pre-existing race, not a reason to copy it.
- Search-restore: keep. It is the only durable undo after the toast has gone, and R4 makes it smaller.
- Read-only: the JS gate on `ctx.readOnly()` is fine, and the tile already computes `readOnly`. The CSS list in `ext_cr.css:520-537` needs no entry.
- The `cr-tile-map cr-tile-remove` class reuse is OK. No JS or test queries `.cr-tile-map`.

## Clean plan (post-review)

This is the plan above with R1-R7 folded in. Unlisted steps are unchanged.

1. **`config.py`**: add `HIDDEN_FILE = os.path.join(_HERE, "hidden.json")` under `PINS_FILE`.
2. **`.gitignore`**: add `hidden.json` and `hidden.json.lock`.
3. **`store.py`**: add `load_hidden()` and `set_hidden(sid, hidden)` exactly as planned, using `_update_json`.
4. **`providers/claude.py`** (R1):
   - `_tail_scan_raw` harvests the max ISO `timestamp` into `last_ts` and returns it.
   - `_session_meta` adds `"active": _ts_epoch(last_ts) or 0.0`, plus `0.0` in its OSError fallback.
   - The `list_sessions` row gets `"active_at": sm.get("active") or mt`.
   - `mtime` is untouched.
5. **`registry.py`**:
   - Add `load_hidden` to the single-line import.
   - `is_hidden(row, hidden)`: `at = hidden.get(row.get("id",""))`, then `isinstance(at,(int,float)) and (row.get("active_at") or row.get("mtime") or 0) <= at`.
   - `all_sessions(include_hidden=True)` filters right after the provider loop when the flag is False.
   - `search_all` sets `r["hidden"] = r.get("id") in hidden`, membership only (R4).
6. **`server.py`**:
   - `/api/list` calls `all_sessions(include_hidden=False)`.
   - Add the `/api/hide` route after `/api/pin`.
   - Add `set_hidden` to the single-line store import.
7. **`web/ext_cr_board.js`**:
   - `toggleSessionHidden(s)` POSTs `/api/hide`. On `ok` it:
     - flips `r.hidden` on the matching `sessionsSearchResults` entry (R3);
     - when hiding, filters `lastState.sessions` and re-renders the rail, board, triage and Sessions view;
     - always calls a guarded `loadSide()` (R6);
     - when hiding, emits the Undo toast. Undo POSTs `hidden:false`, then calls `loadSide()`, with no splice.
   - `railRow`: add the 4th action button only when `!(ctx.readOnly && ctx.readOnly()) && state !== 'working'` (R2). Its glyph is `x` or `return`, it has an aria-label and title, and its click calls `stopPropagation`.
   - The row keydown gets the `e.target === e.currentTarget` guard (R5).
   - `decorateSearchHits` adds `hidden: !!hit.hidden && !known` (R4).
   - `sessionTile`: after the agent-map block, add `if (!readOnly && state !== 'working')` with a `cr-tile-map cr-tile-remove` button, `data-act="remove"`.
8. **`web/ext_cr_board.css`**: add `.cr-rail-remove` to the four rail selector lists (`:1061-1092`), plus an optional `:hover { color: var(--text-failed) }`.
9. **Tests.**
   - `tests/test_cr_routes.py`: add `HIDDEN_FILE` to `_PATHS` and `_empty_env`. Tests T1, T2, T3 (rewritten: a timestamped line means it is back), **T3b** (an untimestamped `cost-state` plus a utime bump means it stays hidden), and T4 (membership flag).
   - New `tests/test_cr_remove_session.py`: import `_HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node, make_session` from `tests.test_working_glow_board`, the same pattern as `test_cr_board_resume_button.py:18`. It covers:
     - (a) the buttons render;
     - (b) POST body plus `stopPropagation`;
     - (c) read-only renders no button;
     - (d) a working session renders no button;
     - (e) Restore from search flips to Remove;
     - (f) Enter on the button does not navigate.
   - Each test is proven RED by reverting only its fix with a scoped Edit, never `git stash`.
   - Gate: `unset TRACKER_AUTH; make check` prints `selfcheck ok`, run one module per process if the full run is OOM-killed. Restart with `make serve`, since this is a UI and parse change.
10. **Risk section**: replace the grace-period fallback with R1's timestamp rule. The remaining residual is a 96 KB tail with no timestamped line, which falls back to mtime (fail-visible). The PR documents R8.

**Decisions for the user:**

- (1) Should the rail get the button too? Recommendation: yes.
- (2) Should the button be hidden on working sessions (R2)? Recommendation: yes. The alternative is to show it and accept an immediate return.
- (3) Keep search-restore? Recommendation: yes.

## Reconciliation (main thread, 2026-11-17)

| # | Finding | Verdict | Note |
|---|---|---|---|
| R1 | mtime-based reappear fires on idle bookkeeping | **confirmed** | `providers/claude.py:1111` ("counts background-agent activity too") and `:2486` `max(st.st_mtime, newest_agent)`; no last-activity field exists on list rows today |
| R2 | removing a working session is undone next poll | confirmed (only under auto-reappear) | moot if user picks sticky removal |
| R3 | search Restore/Remove doesn't re-render | confirmed | accept the raw-results flip |
| R4 | search vs list hidden disagreement | overstated | keep only the cheap client check |
| R5 | Enter on rail button also opens session | confirmed, pre-existing | accept the one-condition guard — the new button would inherit the bug |
| R6 | Undo re-insert-at-index overbuilt | confirmed | `loadSide()` refresh instead |
| R7 | drop grace-window fallback | confirmed | superseded by R1 |
| R8 | hiding a parent leaves child agents; group tiles get no button | accepted as documented gap | PR note only |
| — | Missed by both | — | neither checked the classic `app.js` dashboard; it stays out of scope (it reads `/api/list`, so removed sessions vanish there too, no button) |

**Open decision for the user:** auto-reappear (reviewer's clean plan: new `active_at` = newest timestamped transcript line in the Claude provider, + no Remove on working sessions) **vs** sticky removal (no reappear logic at all; back only via Undo toast or Restore from search) — sticky drops R1/R2/R4 and the `active_at` parser change.

## Final plan (v2, post user decisions)

Author: opus plan agent, 2026-11-17. This section **supersedes** the Design, Files, Tests, Risky-spot and Clean-plan sections above wherever they disagree. Every symbol below was re-checked in this worktree with grep and `sed -n` ranges on 2026-11-17. Line numbers are current; several have moved since the original plan.

### User decisions (final, binding)

1. **Sticky removal.** A removed session stays hidden, even through new activity, until Undo or Restore. `is_hidden` means "the id is a key of hidden.json". There is no auto-reappear, no `active_at`, no mtime comparison and no working-state gate.
2. **Buttons** go on Sessions view rows (`railRow` only when `opts.rich`) and on the Board `sessionTile`. They do **not** go on the compact left rail, and they never render for read-only viewers.
3. **Undo is Cmd+Z / Ctrl+Z**, backed by an in-page stack of removed ids (newest first), plus the toast's "Undo" action.
4. **Restore from search** stays, with R3's raw-results flip and the client "not in current list" check.
5. Keep R5 (Enter-on-button guard) and R6 (refresh via `loadSide()`, no re-insert). R8 stays a documented gap.

### What becomes moot

| Item | Status under sticky removal |
|---|---|
| R1 (bookkeeping mtime bumps un-hide) | **Moot.** Hiding reads no mtime. `claude.py` is not changed at all: `_tail_scan_raw`, `_session_meta` and `list_sessions` stay as they are. |
| R2 (a working session comes straight back) | **Moot.** A removed working session stays removed, so the button is offered on every state, working included (see Decision 1 at the end). |
| R4 (search and list predicates disagree) | **Moot as a predicate problem.** Search uses membership, the same as the list. The client `!known` check stays only as a cheap guard for the window between a Restore POST and the next poll. |
| R7 (grace-window fallback) | Moot. There is no fallback of that kind any more. |
| Original T3 / T3b | Replaced by T3' (sticky): a timestamped line plus an mtime bump leaves the session hidden. |

### JSON shape: `aitracker/hidden.json` (app-owned, gitignored)

```json
{"<claude session id>": 1763380000.123, "auggie:<id>": 1763380100.0}
```

- The value is `time.time()` at removal. It is **metadata only**: nothing shows it and nothing reads it.
- A session is hidden iff its id is a key.
- Deleting the file brings everything back.
- No session log is ever touched (conventions rule 6).

### Files and changes, in landing order

**1. `aitracker/config.py`**, under `PINS_FILE` (`:34`):
```python
HIDDEN_FILE = os.path.join(_HERE, "hidden.json")   # {session_id: hidden_at_epoch}; app-owned, read live
```
Everything reads it late-bound as `config.HIDDEN_FILE`.

**2. `.gitignore`**: two unanchored lines next to `pins.json` (line 5):
```
hidden.json
hidden.json.lock
```

**3. `aitracker/store.py`**, after `load_pins()` (`:55-58`):
```python
def load_hidden():
    """{session_id: hidden_at_epoch} -- sessions the user removed from the dashboard. Read live.
    Sticky: membership alone hides; the timestamp is metadata. Never touches a transcript (rule 6)."""
    d = _load_json(config.HIDDEN_FILE, {})
    return d if isinstance(d, dict) else {}

def set_hidden(sid, hidden):
    """Add (stamped now) or drop one id under _update_json's flock, so concurrent POSTs
    (ThreadingHTTPServer) removing several rows in quick succession never lose a write."""
    def mutate(d):
        if hidden:
            d[sid] = time.time()
        elif sid in d:
            d.pop(sid)
        else:
            return False      # already visible: skip the rewrite
    _update_json(config.HIDDEN_FILE, mutate)
```
`_update_json(path, mutate)` is at `store.py:353`. Its lock file is `path + ".lock"`, and a `mutate` that returns `False` skips the save. `time` is already imported.

**4. `aitracker/registry.py`**
- Line `:11`: append `, load_hidden` to the existing **single-line** `from .store import ...`. It must stay on one line, because `scripts/bundle.py` strips imports line by line.
- Change `def all_sessions():` (`:21`) to `def all_sessions(include_hidden=True):`. Add to the docstring: "include_hidden=False drops ids the user removed (only /api/list asks for that)".
- Right after the provider loop (after `:34`, before `pins = set(load_pins())` at `:35`), add:
  ```python
  if not include_hidden:
      hidden = load_hidden()
      if hidden:
          out = [s for s in out if s.get("id") not in hidden]
  ```
  - A separate `is_hidden` helper is no longer needed, because membership is a single expression.
  - The default of `True` keeps the internal callers as they are: `newest_models()` (`registry.py:148`), `agent_cli.py:364` and `term_vt.py:4101`. An Auggie session still gets its upgrade restart, and the terminal directory picker still lists it.
- In `search_all(q)` (`:400-411`), between the sort (`:410`) and `return out`:
  ```python
  hidden = load_hidden()
  for r in out:
      r["hidden"] = r.get("id") in hidden
  ```
  This is the shared seam, so Claude, Auggie and Augment-extension hits all carry the flag.

**5. `aitracker/server.py`**
- `:16`: append `, set_hidden` to the single-line `from .store import ...`.
- `:483`: change to `self._json(all_sessions(include_hidden=False), headers=headers)`. This is the **only** caller that passes `False`.
- Add a new route directly after the `/api/pin` block (`:885-894`). It inherits the guards that run before every POST route: CSRF (`:663`), auth (`:667`) and read-only deny-all (`:669`).
  ```python
  if p.path == "/api/hide":
      # Remove from dashboard: app-owned hidden.json only, never a session log (rule 6).
      sid = body.get("session")
      if not isinstance(sid, str) or not sid:
          return self._json({"error": "session required"}, 400)
      set_hidden(sid, bool(body.get("hidden")))
      self._json({"ok": True})
      return
  ```

**6. `aitracker/web/ext_cr_board.js`**

Everything goes inside the board IIFE, which already owns `ctx`, `lastState`, `sessionsSearchResults` (`:770`) and `renderRail/renderBoard/renderTriage/renderSessionsView`.

6a. Module state, next to `sessionsSearchResults` (`:770`):
```js
var removedStack = [];   // ids this page removed, newest LAST (pop() = newest); page-lifetime only
```

6b. One POST helper and two thin verbs, next to `toggleSessionPin` (`:2204`):
```js
function postHidden(id, hidden) {
  if (typeof fetch !== 'function') return Promise.resolve(false);
  return fetch('/api/hide', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: id, hidden: hidden }),
  }).then(function (r) { return r.ok; }, function () { return false; }).then(function (ok) {
    if (!ok) return false;
    // R3: flip the SOURCE search array; decorateSearchHits rebuilds copies every render.
    (sessionsSearchResults || []).forEach(function (r) { if (r.id === id) r.hidden = hidden; });
    if (hidden) {
      lastState.sessions = (lastState.sessions || []).filter(function (x) { return x.id !== id; });
      renderRail(lastState); renderBoard(lastState); renderTriage(lastState);
    } else {
      removedStack = removedStack.filter(function (x) { return x !== id; });
    }
    renderSessionsView(lastState);
    if (typeof loadSide === 'function') loadSide();   // R6: refresh app.js `sessions` too (ext_cr_boot.js:648 precedent)
    return true;
  });
}
function removeSession(s) {
  postHidden(s.id, true).then(function (ok) {
    if (!ok) return;
    removedStack.push(s.id);
    ctx && ctx.emit && ctx.emit('notify', {
      title: 'Session removed · ⌘Z / Ctrl+Z to undo',
      actionLabel: 'Undo',
      onAction: function () { postHidden(s.id, false); },
    });
  });
}
function undoLastRemove() {          // returns true iff it acted
  var id = removedStack.pop();
  if (!id) return false;
  postHidden(id, false);
  return true;
}
```
- `filter` builds a new array. It never splices app.js's `sessions` array.
- `loadSide` is app.js's global (`app.js:1324`). It is a no-op while `sideBusy` is set, and the 5 s poll covers that case.
- The toast's Undo un-hides **that** id. On success, `postHidden(..., false)` also drops the id from `removedStack`, so a later Cmd+Z never re-POSTs an id that is already restored. A search Restore does the same.
- `toast()` (`ext_cr_dialogs.js:273`) renders `title` and the `actionLabel` button, and dismisses after `onAction`. The `notify` bus passes the object by reference (`ext_cr_dialogs.js:375`), so `onAction` survives.

6c. The button. One helper builds it, so the rail row and the tile cannot drift apart:
```js
function removeBtn(s, cls) {
  var restore = !!s.hidden;
  var label = restore ? 'Restore to dashboard' : 'Remove from dashboard (log is kept)';
  return h('button', {
    class: cls, type: 'button', 'data-act': restore ? 'restore' : 'remove',
    title: label, 'aria-label': label,
    onclick: function (e) { e.stopPropagation(); if (restore) postHidden(s.id, false); else removeSession(s); }
  }, [glyph(restore ? 'return' : 'x', '')]);
}
function isReadOnly() { return !!(ctx && typeof ctx.readOnly === 'function' && ctx.readOnly()); }
```
The icons `x` and `return` exist in both ICO maps (app.js `:84-85`).

6d. `railRow(s, now, opts)` (`:1916`; `rich` is already computed at `:1917`). In the `actions` array (`:2101-2117`), append after the rename button:
```js
(rich && !isReadOnly()) ? removeBtn(s, 'cr-rail-remove') : null,
```
- `h()` already skips `null` children; the same array passes `mapBtn` as `null` today.
- The compact rail never passes `opts`, so it never gets the button.
- Rich rows include the Sessions view's search-hit rows (`:1824`) and its agent-bucket rows (`:1453`).

6e. **R5**, at `:2123`:
```js
onkeydown: function (e) { if (e.key === 'Enter' && e.target === e.currentTarget) openSession(s.id); }
```
The tile already does this (`:2669`). The change also fixes the same latent bug for pin and rename.

6f. `decorateSearchHits` (`:1690-1711`): add one field to the returned object:
```js
hidden: !!hit.hidden && !known,
```

6g. `sessionTile(t, now)` (`:2880`). `readOnly` is already computed at `:2903`. Insert **after** the `if (s.agent_map_n > 0) {...}` block, which ends at `:2921`; inserting there keeps the source pins in `test_cr_agent_map_entry.py:253-254` valid.
```js
if (!readOnly) head.appendChild(removeBtn(s, 'cr-tile-map cr-tile-remove'));
```
- The button shows on every state, hero tiles included. Sticky removal makes Remove meaningful on working tiles too.
- `cr-tile-map` reuses the map button's size and hover CSS. No JS or test counts `.cr-tile-map` elements.

6h. **Cmd+Z / Ctrl+Z.** Add `bindUndoKey()` and call it from `mount()` right after `bindKeyboard()` (`:969`). It needs its own listener: `bindKeyboard`'s handler (`:3079`) returns early unless the **board** grid is the visible view (`isBoardActive()`, `:3064-3073`), and undo must also work in the Sessions view.
```js
// Never steal Cmd/Ctrl+Z from a text field or a terminal: in a PTY, Ctrl+Z is SIGTSTP.
var UNDO_BLOCK_SEL = '#cr-term-root, #vtmodal, #vtmgrmodal, .vtpane, .xterm';
function isUndoBlockedTarget(t) {
  if (!t) return false;
  var tag = t.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable) return true;
  return !!(typeof t.closest === 'function' && t.closest(UNDO_BLOCK_SEL));
}
function bindUndoKey() {
  document.addEventListener('keydown', function (e) {
    if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey || e.repeat) return;
    if (e.key !== 'z' && e.key !== 'Z') return;
    if (!root || !root.isConnected) return;
    var nr = document.getElementById('nextRoot');
    if (nr && nr.hidden) return;                 // Control Room not the visible mode
    if (isUndoBlockedTarget(e.target)) return;
    if (!undoLastRemove()) return;               // empty stack: browser default passes through
    e.preventDefault();
  });
}
```
- **Terminal containers (each verified in the source):**
  - `#cr-term-root` (`ext_cr_boot.js:285`) is the CR terminal host. `isTypingTarget` already uses it (`:3057`).
  - `#vtmodal` (`ext_vt.js:2055`) is the classic VT overlay.
  - `#vtmgrmodal` (`ext_vt.js:3284`).
  - `.vtpane` (`ext_vt.js:805`) is also the standalone `?tty=` pane.
  - `.xterm` is xterm.js's own root class.
- Both terminal inputs are `<textarea>` elements: `.vtinput` (`ext_vt.js:821`) and xterm's helper textarea. The tag check alone already blocks them. The `closest()` clause covers focus on a part of a pane that is not a textarea, such as the scrollbar or a toolbar button.
- **Conflict check: there is no existing Cmd/Ctrl+Z binding.** A grep for `'z'`, `"z"`, `KeyZ` and `keyCode === 90` across `aitracker/web/*.js` finds nothing.
  - The other document keydown handlers (`app.js:2591/2770/2772`, `ext_cr_board.js:3079`, `ext_cr_detail.js:2138`, `ext_cr_term.js:246`, `ext_launch.js:206`, `ext_cr_dialogs.js:371`, `ext_vt.js:2112/3318`) bind Escape, Enter/Space, the arrows, j/k/t/? and Cmd+K. None of them calls preventDefault on unrelated keys.
  - `ext_vt.js`'s `Terminal._onKeyDown` (`:1097`) and xterm stop propagation for the keys they handle. Ctrl+Z typed into a terminal normally never reaches `document` at all, so the target guard is a second layer of protection.
- `e.repeat` is ignored, so a held Cmd+Z cannot drain the whole stack.
- The pop is synchronous, so two quick presses restore two distinct ids even while the first POST is in flight.
- Optional, one line, untested: call `CR.dialogs.addHelpShortcuts([['⌘Z / Ctrl+Z', 'Restore the last removed session']])` from mount (`ext_cr_dialogs.js:640`; it has no callers today). Skip it if `CR.dialogs` is not reliably mounted before the board.

**7. `aitracker/web/ext_cr_board.css`**
- Add `.tracker-next .cr-rail-remove` to the four rail-button selector lists that name `.cr-rail-rename`:
  - base (`:1063`);
  - row hover/focus-within reveal (`:1084-1085`);
  - its own `:hover` (`:1088`);
  - `@media (hover:none)` (`:1091`).
- Add `.tracker-next .cr-rail-remove:hover, .tracker-next .cr-tile-remove:hover { color: var(--text-failed); }`. The token exists (`ext_cr.css:86/341`), so no new colour literal is needed.

Out of scope, unchanged from the reconciliation:
- the classic `app.js` `sessionRow` (a removed session vanishes there too, but gets no button);
- the detail-view header;
- agent group tiles (R8).

### Sequencing and why

1. config, `.gitignore` and the test-harness paths, so no test ever writes the real `aitracker/hidden.json`.
2. store, then registry, then server, with T1-T4. These are pure Python and fast to prove red and green.
3. JS (6a-6h) and CSS, with T5.
4. A `make bundle` sanity check (the registry import is still one line), then the full gate, then a restart with `make serve`, because this is a UI and server change (rule 11).

### Tests

Each test is proven RED by reverting only its fix with a scoped Edit, never `git stash`.

**Harness prerequisite (`tests/test_cr_routes.py`):**
- `_PATHS` (`:36-38`): add `"HIDDEN_FILE"` to the tuple, so `_snap()`/`_restore()` (`:45-58`) save and restore it.
- `_empty_env` (after `config.PINS_FILE = ...` at `:91`): `config.HIDDEN_FILE = tempfile.mktemp(suffix=".json")`.
- RED proof for the harness itself: without the `_empty_env` line, T1 writes `aitracker/hidden.json` in the worktree. T1 asserts that `os.path.exists(os.path.join(os.path.dirname(config.__file__), "hidden.json"))` has the same value after the test as before it.

| # | Test (file) | Assertion | RED when |
|---|---|---|---|
| T1 | `test_hide_route_round_trips` (test_cr_routes.py) | `_write_claude("h1")`. POST `/api/hide {session:"h1", hidden:true}` returns 200 `{ok:true}`, `h1` is absent from GET `/api/list`, and `config.HIDDEN_FILE` holds the key `h1` with a float. POST `hidden:false` and `h1` is listed again with the key gone. POST `{}` and `{session: 5}` each return 400. | The route is removed (fall-through, no 200, no file). The `/api/list` opt-in is reverted to `all_sessions()` (h1 stays listed). The `isinstance` check is removed (`{session:5}` gets 200). |
| T2 | `test_hidden_filter_spans_providers_and_keeps_internal_callers` | `_write_claude("h2")` and `_write_auggie("a2","t")`. Write `config.HIDDEN_FILE` = `{"h2": 1.0, "auggie:a2": 1.0}`. Both are absent from `registry.all_sessions(include_hidden=False)` and both present in `registry.all_sessions()`. | The filter is removed (both listed). The default is flipped to `False` (the internal-caller half fails). The filter is placed in the Claude provider instead of the seam (the Auggie half fails). |
| T3' | `test_removed_session_stays_hidden_through_new_activity` (sticky) | `_write_claude("h3", mtime=now-100)`, POST hide, confirm absent. Append a real timestamped line `{"type":"user","timestamp": iso(now+5), "message":{...}}` to the transcript, run `os.utime(path, (now+5, now+5))` and clear `_claude._META_CACHE`. It is still absent from `/api/list`. Then POST `hidden:false` and it is listed. | Any activity predicate is reintroduced (for example the original `mtime <= hidden_at`), and the session reappears. |
| T4 | `test_search_marks_hidden_hits` | Two Claude sessions share a prompt word, and one is hidden. `/api/search?q=<word>` returns both. The hidden one has `hidden: True` and the other `hidden: False`. | The `search_all` annotation is removed (the key is missing). |
| T5 | new `tests/test_cr_remove_session.py` (node, `@unittest.skipUnless(_HAS_NODE, ...)`) | Harness setup is described below this table. | See the sub-cases. |

**T5 harness setup:**
- Import `_HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node, make_session` from `tests.test_working_glow_board`, the same pattern as `test_cr_board_resume_button.py:18`.
- Before `mount()`, override `document.addEventListener` to collect **every** keydown listener into an array, and dispatch each synthetic event to all of them. (`test_pending_ui_board.py:24` keeps only the last listener, which is not enough here.) Set `root.isConnected = true`.
- ctx is `{emit, readOnly: () => ro, go: (v,id) => gone.push([v,id]), on(){}}`, the shape used at `test_cr_board_resume_button.py:48-49`.
- `window.fetch` records `[url, JSON.parse(body)]` and resolves `{ok:true, json: () => Promise.resolve(searchHits)}`.
- After mount, `setTimeout` runs synchronously (the pattern at `test_cr_search_parity.py:31-92`).
- Flush microtasks between steps.
- The stub DOM does not bubble events, so stopPropagation is proven with a spy on the event object, not through a parent handler.

**T5 sub-cases** (each a separate `__o[label]` capture with one assertion):

| Sub | Drive | Assert | RED when |
|---|---|---|---|
| a | `CR.board.update({sessions:[s1], now})`, then render the Sessions view | The rich row in `els.sessionsList` has `.cr-rail-remove`. The board tile has `[data-act="remove"]`. The compact `.cr-rail` row has **no** `.cr-rail-remove`. | `rich &&` is dropped (the compact rail gets the button), or the tile append is removed. |
| b | Click the tile's remove button with a stub event `{stopPropagation: spy}` | fetched == `[["/api/hide", {session:"s1", hidden:true}]]`; the spy was called. After a flush, a `notify` was emitted with title `'Session removed · ⌘Z / Ctrl+Z to undo'` and `actionLabel:'Undo'`. | `e.stopPropagation()` is removed (spy not called), or the body is wrong. |
| c | `ro = true`, then re-render | There is no `.cr-rail-remove` and no `[data-act=remove]` anywhere. | The `!isReadOnly()` / `!readOnly` gate is removed. |
| d | Remove s1, then s2 (flush after each). Dispatch keydown `{key:'z', metaKey:true, target: bodyStub, preventDefault: spy}`. | The last fetch is `["/api/hide", {session:"s2", hidden:false}]` (newest first) and `preventDefault` was called. A second Cmd+Z POSTs `{session:"s1", hidden:false}`. | `shift()` is used instead of `pop()` (s1 comes first), or `preventDefault` is not called. |
| e | With a non-empty stack, dispatch `{key:'z', ctrlKey:true, target: {tagName:'INPUT'}}`, then the same with target `{tagName:'DIV', closest: sel => /\.xterm|#cr-term-root/.test(sel) ? {} : null}` | No new fetch, `preventDefault` not called, and the stack is untouched (a following body-target Cmd+Z still pops). | The tag check is removed (the input case fires), or the `closest(UNDO_BLOCK_SEL)` clause is removed (the terminal case fires). |
| f | With an empty stack, dispatch a body-target Cmd+Z | No fetch, and `preventDefault` is **not** called. | `preventDefault()` is moved before the `undoLastRemove()` check. |
| g | Remove s1 and s2, then call the captured toast payload's `onAction()` for s1 | It POSTs `{session:"s1", hidden:false}`. The next Cmd+Z restores `s2` only, and a further Cmd+Z does nothing, because s1 already left the stack. | The stack `filter` in `postHidden(..., false)` is removed (the third Cmd+Z re-POSTs s1). |
| h | Restore flips to Remove: fetch returns `[{id:'hx', title:'t', hidden:true}]` for `/api/search`. `uiState.set('query','t')`, flush; the row's button has `data-act="restore"`. Click it, flush. | The button now has `data-act="remove"` and aria-label `'Remove from dashboard (log is kept)'`. fetched includes `{session:"hx", hidden:false}`. | The R3 `sessionsSearchResults.forEach` flip is removed (the button stays `restore`). |
| i | A search hit that **is** in `lastState.sessions` but carries `hidden:true` | It renders `data-act="remove"`. | `&& !known` is removed from `decorateSearchHits`. |
| j | Call the rich row's `_listeners.keydown({key:'Enter', target: removeBtnEl, currentTarget: rowEl})`, then `({key:'Enter', target: rowEl, currentTarget: rowEl})` | After the first call `gone` is empty. After the second, `gone == [['detail', id]]` (`openSession` calls `ctx.go('detail', id)`, `:2232-2236`). | The R5 guard is removed (the first call navigates). |

**Gate:**
- `unset TRACKER_AUTH; make check` must print `selfcheck ok`.
- Run one module per process if the full run is OOM-killed. The known `term_vt` backstop flake is unrelated to this change.
- Commit with a Bash timeout above 6 minutes, because the commit hook runs the full gate.
- Restart with `make serve` to see the change. It is a UI and server change, not a live-data change.

### Risky spot and fallback

**The risky spot is the Cmd/Ctrl+Z handler taking a keystroke it should not.** The worst cases:
- Ctrl+Z reaches the handler from inside a terminal and is preventDefault'ed. The user's SIGTSTP is silently lost, and a session they did not mean to restore comes back.
- Cmd+Z is swallowed while the user is undoing text in a field the guard does not recognise, such as a future contenteditable widget or a `<select>` in a dialog.

Mitigations already in the design:
- The handler acts only when the in-page stack is non-empty, so it does nothing after a reload or before any Remove.
- The target guard checks the tag, `isContentEditable` and `closest(UNDO_BLOCK_SEL)`.
- `e.repeat` is ignored.
- The terminals already stop propagation for the keys they own.

**Fallback if a conflict appears:** replace the blocklist with a one-line allowlist, so the shortcut fires only when focus is on `document.body` or inside the board or Sessions list:
`if (e.target !== document.body && !els.viewBoard.contains(e.target) && !els.sessionsList.contains(e.target)) return;`
The toast Undo button and search Restore stay as non-keyboard paths, so the shortcut could even be removed without losing recovery.

**A secondary risk, accepted with the sticky decision:**
- A removed session that the user later resumes stays hidden from the list, the Board and the Sessions view.
- It still shows in any tracker terminal running it, in the terminal directory picker, and in the Agents panel, because those use `include_hidden=True`.
- Once the toast and the page's undo stack are gone, the way back is search, then Restore. The PR states this.
- Provider lists are capped at 200 before the filter, so removals leave fewer than 200 visible rows. Older sessions do not backfill. This is unchanged.

**Documented gaps for the PR:**
- R8: removing a parent leaves its agent child sessions in the Agents buckets and the board group tiles, and group tiles get no button.
- The undo stack lasts only for the page's lifetime.
- The classic `app.js` view gets no button.

### Decisions the user may still want to overrule

1. **Remove on working tiles.** With sticky removal the button shows on every state, including a session that is working right now. The alternative is to hide it when `state === 'working'` (one condition), so live work cannot be removed by accident.
2. **Toast copy.** The requested text is used verbatim as the toast title, with no meta line. The alternative is the title "Session removed" with "⌘Z / Ctrl+Z to undo" as the meta line.

## Re-review (v2)

Adversarial re-review of **Final plan (v2)** only, by an opus reviewer on 2026-11-17. Every claim was checked against the worktree with grep and `sed -n` ranges, with no code edits. Severity scale: HIGH means the gate goes red or the feature is broken, MEDIUM means a visible defect or a test that cannot run as written, and LOW means polish or documentation.

### Findings

**F1 HIGH: `bindUndoKey()` after `bindKeyboard()` turns an existing test red.**
- **Defect.** `tests/test_pending_ui_board.py:23-24` keeps only the **last** keydown listener: `document.addEventListener = function (t, fn) { if (t === 'keydown') __kd = fn; }`. Lines `:61` and `:67` then dispatch `{key:'t'}` through `__kd` and expect a `terminal:open` emit.
- **Repro.** v2 §6h calls `bindUndoKey()` right after `bindKeyboard()` (`ext_cr_board.js:969`), so `__kd` becomes the undo listener. That listener returns at once when no modifier key is held. `termOpen` comes back `[]` when `[sid]` is expected, and the test fails.
- **Fix direction.** Change the registration order only. Neither handler acts on the other's keys, and neither stops propagation, so the order has no runtime effect. Do not edit `test_pending_ui_board.py`.
- **The way.** In `buildShell()` (`:968-970`), write `bindUndoKey(); bindKeyboard(); bindResize();`. The undo listener goes first, so `bindKeyboard`'s listener is still the last one registered.
- **Test.** The existing `test_pending_ui_board` is the red proof. Swap the two calls back and it fails.

**F2 MEDIUM: a poll already in flight brings a just-removed session back for up to 5 s.**
- **Defect.** `loadSide()` returns immediately while `sideBusy` is set (`app.js:1325`). Suppose a `/api/list` request was in flight when the hide POST landed, and the server built its rows (`registry.all_sessions`) before `hidden.json` was written. That response still contains the session. `SIDE_EXT` then calls `CR.board.update({sessions})` (`ext_cr_boot.js:1015-1021`). `update()` (`ext_cr_board.js:3228-3229`) replaces the `lastState` that `postHidden` had filtered, so the row comes back until the next 5 s poll.
- **Repro.** Click Remove while `/api/list` is slow (cold cache, about 950 sessions). The row disappears, reappears, then disappears again. To the user, it looks as if Remove failed.
- **Fix direction.** Treat this page's `removedStack` as a client overlay that `update()` applies on every poll. Do not splice or reassign app.js's `sessions` array. Do not add a timer or a second fetch.
- **The way.**
  - (a) In `update(state)`, right after `lastState = ...`, add:
    ```js
    if (removedStack.length) lastState = Object.assign({}, lastState, { sessions: (lastState.sessions || []).filter(function (x) { return removedStack.indexOf(x.id) < 0; }) });
    ```
    The existing `var sessions = lastState.sessions || []` line then reads the filtered list.
  - (b) Move `removedStack.push(id)` from `removeSession` into `postHidden`'s success branch: `if (hidden) { if (removedStack.indexOf(id) < 0) removedStack.push(id); } else { removedStack = removedStack.filter(...); }`.
  - (c) Replace the hand-rolled `lastState.sessions = ...filter...; renderRail; renderBoard; renderTriage` with `update(lastState);`, keeping `renderSessionsView(lastState)` and `loadSide()`. `update()` already renders the rail, triage and board, and it now filters.
  - (d) `removeSession` keeps only the toast: `postHidden(s.id, true).then(function (ok) { if (ok) ctx.emit('notify', ...); })`.
  - A Remove from a search-hit row now joins the stack as well. That is correct, because it is a removal made on this page.
- **Accepted edge (document it in the PR).** Suppose another tab restores an id that is on this page's stack. This page keeps hiding it until a Cmd+Z here, a reload, or a Restore here. Because removal is sticky, that is consistent.
- **Test: new T5 sub-case k.** Remove `s1` and flush. Then call `CR.board.update({sessions:[s1, s2], now})`, which simulates the stale poll. No tile carries `data-tile-id` for `s1`, and the compact rail has no `data-id="s1"` row. The test goes RED with (a) reverted.

**F3 MEDIUM: the T5 harness cannot run as written.**

Five gaps, each checked against `tests/test_working_glow_board.py`:
- **Attribute selectors.** `queryAllReal` matches **class selectors only** (`:155-165`), so `[data-act="remove"]` and `[data-act=remove]` always return `[]`. Sub-cases c and e would pass vacuously, and a and b would find nothing.
  - **Way.** Use the existing `findByAttr(root, 'data-act', 'remove')` helper (`:184-193`). Use `queryAllReal(el, '.cr-rail-remove')` for the class lookups.
- **No way to open the Sessions view.** With `on(){}`, nothing switches to it. `update()` renders it only when `currentView === 'sessions'` (`:3234`), and `currentView` changes only through `ctx.on('view:changed')` (`:3175-3181`).
  - **Way.** Give ctx `on: function (n, fn) { (H[n] = H[n] || []).push(fn); }`. After mount, fire `H['view:changed'].forEach(f => f({view: 'sessions'}))`.
- **Dispatching to every keydown listener throws.** v2 also sets `root.isConnected = true`, which arms `bindKeyboard`'s handler. For a body target, that handler reaches `isTypingTarget` → `document.getElementById('cr-term-root')`. That call returns `dummy`, and `dummy.contains` is undefined, so the handler throws a TypeError.
  - **Way.** Copy `test_pending_ui_board.py:25`: `dummy.contains = function () { return false; };`. Also wrap each listener call in `try {} catch (_) {}`, so a gap in one handler's stubs cannot mask the undo assertion.
- **The fetch stub.** v2's `JSON.parse(body)` throws for GETs, which pass no `opts`. Mount and update may also fetch other URLs.
  - **Way.** Record `[url, opts && opts.body ? JSON.parse(opts.body) : null]`, and assert only on entries whose url is `/api/hide`.
- **Flushing.** The preamble's `window.setTimeout` never runs its callback (`:296`). `postHidden` chains three `.then`s, plus one more in `removeSession`.
  - **Way.** Flush with `await new Promise(function (r) { setImmediate(r); })`, which Node's `setImmediate` leaves un-stubbed. For h, set `window.setTimeout = function (fn) { fn(); return 0; }` after mount, the same pattern as `test_cr_search_parity.py:72`.

**F4 LOW: the harness RED proof depends on the environment.**
- **Defect.** v2 has T1 assert "exists(real `aitracker/hidden.json`) is the same before and after". In a checkout where the user has already removed sessions, the file exists before and after. The test stays GREEN even with the `_empty_env` line deleted, and it writes `h1` into the user's real file.
- **Way.** Replace it with a deterministic check in T1: `self.assertTrue(os.path.realpath(config.HIDDEN_FILE).startswith(os.path.realpath(tempfile.gettempdir())))`. It goes RED when `config.HIDDEN_FILE = tempfile.mktemp(...)` is removed from `_empty_env`.
- The `_PATHS` change in v2 is correct as written: `_snap`/`_restore` at `:45-58` iterate `_PATHS`.

**F5 LOW: Cmd+Z acts behind an open CR dialog.**
- **Defect.** With the rename, agent-map or help dialog open and focus on one of its buttons (not an input), Cmd+Z restores a session behind the modal. `ext_cr_detail.js:2141` already guards its own keys with `document.querySelector('.cr-dialog-layer[aria-hidden="false"]')`.
- **Way.** Add `if (document.querySelector('.cr-dialog-layer[aria-hidden="false"]')) return;` to `bindUndoKey`, after the `nextRoot` check.
- **Test: sub-case e, third probe.** Temporarily set `document.querySelector = function (s) { return /cr-dialog-layer/.test(s) ? {} : null; }`. A body-target Cmd+Z must not fetch, and the stack must stay untouched. It goes RED without the line.

**F6 LOW: a failed POST is silent, and a failed undo loses its id.**
- **Defect.** `undoLastRemove` pops before the POST. If `/api/hide` fails (server restarting, or a 403 after a flip to read-only), the id is gone from the stack and nothing tells the user.
- **Way.**
  - In `undoLastRemove`, write `postHidden(id, false).then(function (ok) { if (!ok) removedStack.push(id); });`.
  - In `postHidden`'s `!ok` branch, add `ctx && ctx.emit && ctx.emit('notify', { title: 'Couldn’t update the session.' });`. This follows the pin precedent at `ext_cr_boot.js:647-651`.
- **Test: sub-case l.** Make fetch resolve `{ok:false}` for the restore. A second Cmd+Z then POSTs the same id again. It goes RED without the re-push.

**F7 LOW (documentation only): a removed session never raises a waiting-on-you alert.**
- `ext_cr_boot.js:1104` detects false→true waiting transitions across the `/api/list` payload. Under sticky removal, a hidden session that is resumed elsewhere and then waits on the user is silent.
- **No code change.** Add it to the PR's documented gaps, next to R8.

**F8 LOW: the hover colour rule has to come after `.cr-tile-map:hover`.**
- `.tracker-next .cr-tile-map:hover { color: var(--text-primary); }` (`ext_cr_board.css:1807`) has the same specificity as v2's new `.cr-tile-remove:hover` rule. If the new rule lands above `:1807`, the red hover never shows.
- **Way.** Place the new rule directly after `:1808`.
- **Test.** None. This is CSS; check it by eye after `make serve`.

### Verified with no change

- **No other global keydown handler double-acts on Cmd/Ctrl+Z or swallows it.**
  - Checked: `app.js:2591/2770/2772`, `ext_cr_board.js:3079` (its only modifier branch is `k`), `ext_cr_detail.js:2138` (j/k), `ext_cr_term.js:246`, `ext_launch.js:206` and `ext_cr_dialogs.js:354-371` (all Escape), and `ext_vt.js:2112/3318`.
  - There is no existing `z` or `KeyZ` binding.
- **Terminals.**
  - The legacy renderer maps Ctrl+letter to a control byte (`ext_vt.js:234-236`), then calls `preventDefault` and `stopPropagation` (`:1137-1144`).
  - xterm cancels the keys it handles.
  - Cmd+Z in the legacy renderer returns `null` from `keyToBytes` and bubbles up from the `.vtinput` textarea, which the tag check blocks.
  - **The exclusion list is complete.** Every mount point lies inside one of the listed selectors:
    - `#cr-term-root` (`ext_cr_boot.js:285`), which holds the CR overlay (`ext_cr_term.js:250`) and its `mountInto` panes;
    - `#vtmodal` (`ext_vt.js:2055`);
    - `#vtmgrmodal` (`:3284`);
    - `.vtpane` and `.vtpane.vtxpane` (`:805/1789`), and the probe panes at `:3032/3947`.
- **Mount runs once.** `ensureMounted()` is guarded by `mounted` (`ext_cr_boot.js:970-972`), so there is no duplicate listener.
- **The classic page.** It loads `ext_cr_board.js` in the same `__JS__` bundle (`index.html:246`). The listener exists only after the first next-mode mount, and it returns while `#nextRoot` is hidden.
- **Server.**
  - `/api/hide` inherits CSRF (`server.py:663`), auth (`:667`) and the read-only deny-all (`:669`), and the body-parse 400 (`:671-676`).
  - A non-dict JSON body would raise `AttributeError` on `.get`. That is already true of every POST route, so it is not new.
  - Every authenticated caller can reach the route, the same as `/api/pin`. That is consistent.
- **A corrupt `hidden.json`.** `_load_json` returns `{}` and `load_hidden` keeps only a dict, so every session shows. The next `set_hidden` runs `_update_json` (`store.py:376-380`), which resets the file to a dict. Hides that were already unreadable stay lost. That is acceptable and the same as pins.
- **`include_hidden=True` callers.**
  - Confirmed: `registry.py:159` (`newest_models`), `agent_cli.py:364` and `term_vt.py:4106`.
  - `server.py:483` is the only `/api/list` call.
  - No other module imports `all_sessions`.
- **The bundle.**
  - The `registry.py:11` and `server.py:16` imports stay on single lines.
  - `config.HIDDEN_FILE` is rewritten to `HIDDEN_FILE` by `scripts/bundle.py:45`.
  - A grep finds no existing `load_hidden`, `set_hidden`, `HIDDEN_FILE` or `/api/hide` anywhere, so there is no single-namespace collision.
- **Search hits are fresh dicts.** Each one is built by the provider's own search (for example `claude.py:1236-1246`), so annotating `r["hidden"]` cannot leak into a cache.
- **Icons and a11y.**
  - `i-x` and `i-return` exist in the sprite, in `ICO_EMOJI` and in `ICO_TEXT`.
  - The button has `title` and `aria-label`, and the glyph is `aria-hidden`.
  - Read-only CSS parity (`ext_cr.css:536`) is not needed: `applyReadOnly(res)` runs before `sessions` is assigned (`app.js:1334-1336`), so the JS gate is already correct on the first render.
- **The other T5 RED claims hold once F3 is applied:**
  - b: the click `stopPropagation` spy;
  - d: pop rather than shift;
  - f: `preventDefault` only when the handler acts;
  - g: the stack filter;
  - h: the R3 flip;
  - i: `&& !known`;
  - j: R5, through `_listeners.keydown`.
  - T1, T2 and T4 also go RED as claimed. `{session:5}` reaches `set_hidden`, which returns 200 without the `isinstance` check.
- **T3'.** It proves RED only by injecting a predicate, not by reverting a fix. Keep it: it costs about 10 lines and pins the user's binding sticky decision.
- **Non-Latin keyboard layouts.** There, `e.key` is not `z`. Matching only `e.key` is the norm in this codebase, so do not add `e.code`.

### v2 amendments (the only changes to apply on top of v2)

1. **F1.** In `buildShell()`, use `bindUndoKey(); bindKeyboard(); bindResize();`, so undo is registered **before** `bindKeyboard`.
2. **F2.** Four changes:
   - `update()` filters `lastState.sessions` by `removedStack`, using the one `Object.assign` line above.
   - `postHidden` success pushes to the stack on hide (de-duplicated) and filters it on restore.
   - `postHidden` then calls `update(lastState)` in place of the manual filter and the three renders.
   - `removeSession` only emits the toast.
   - Add sub-case k.
3. **F3.** Fix the T5 harness:
   - `findByAttr` for `data-act`;
   - a capturing `ctx.on`, then `view:changed` → `sessions`;
   - `dummy.contains = () => false`, and try/catch around each dispatched keydown listener;
   - a fetch recorder that guards a missing `opts.body` and filters on `/api/hide`;
   - a `setImmediate` flush, plus a synchronous `setTimeout` after mount for h.
4. **F4.** Replace the real-file existence assertion in T1 with `realpath(config.HIDDEN_FILE)` starting with `realpath(tempfile.gettempdir())`.
5. **F5.** Add the `.cr-dialog-layer[aria-hidden="false"]` early return in `bindUndoKey`, and a third probe in sub-case e.
6. **F6.** Re-push the id on a failed undo, show a `notify` error in `postHidden`'s `!ok` branch, and add sub-case l.
7. **F7.** Add "a removed session raises no waiting alerts" to the PR's documented gaps.
8. **F8.** Place the `.cr-rail-remove:hover, .cr-tile-remove:hover` colour rule after `ext_cr_board.css:1808`.

## Reconciliation of re-review (main thread)
F1 confirmed · F2 confirmed · F3 confirmed · F4 confirmed · F5 confirmed · F6 accepted minimal (re-push id + error toast; data-loss guard) · F7 PR note only · F8 confirmed. None changes user-visible design → implement v2 + `### v2 amendments`.
User decisions: sticky removal; Sessions view + Board only (not compact rail); undo = Cmd/Ctrl+Z stack + toast Undo + Restore from search; button shown on working sessions too (v2 default, not overruled).
