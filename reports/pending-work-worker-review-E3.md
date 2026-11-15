# Implementation review E3: front end (pending card, list and item, Resume, Settings rows, Update, Scheduled scan)

Reviewer: E3 (adversarial; assumed every implementer report was false). Read-only. No tests, servers or `make` were run.
Probes run: `node --check` on every web JS file and on their concatenation in page order (app.js, then sorted ext_*.js), which passed. Two `node` probes ran the real `app.js` with the stub DOM from `tests/test_pending_ui_classic.py`, against the real `pending._fence` output. Both probes are quoted under B2.

Counts: **2 blockers, 4 should-fix, 10 nits.**

## What was checked and holds

These points were checked and hold, so they are not findings:

- **Field names match the server.** The JS reads the following, and each one exists in what the server returns:
  - From `GET /api/pending`: `card.show`, `card.title`, `card.summary`, `running`, `items`, `tmp`, and per item `id`, `label`, `path`, `branch`. Source: `pending.load_report` :898 and `build_card` :629.
  - From `GET /api/pending/item`: `title`, `when`, `md`, `resume.cwd`, `resume.prompt`. Source: `item_detail` :954.
  - From `GET /api/update`: `kind`, `branch`, `head`, `head_subject`, `behind`, `ahead`, `upstream`, `fetched_at`, `dirty`, `can_update`, `reason`, `restart_error`, `started_at`, `terminals`. Source: `update.py:120-123`.
  - From the apply call: `restarting`, `recover`, `needs_confirm`, `error`. Source: `update.py:258-300`.
  - From `GET /api/scheduler`: `installed`, `kind`, `last_exit`, `root`, `root_exists`, `supported`, `opted_out`, `error`. Source: `schedule.sched_status` and `server._sched_body` :260.
- **Load-order safety.** Every cross-file reference is a runtime `typeof` lookup inside a callback or click handler:
  - `pendingCache` / `openPendingList` in `ext_cr_board.js:2687` and `ext_cr_boot.js:1003`;
  - `window.ExtLaunch` in `app.js:2385`.

  The new top-level statements are a `let` (app.js:2327), function declarations and `window.*` assignments (app.js:2409, ext_launch.js:380). None of them throws.

  `loadSide` calls `loadPending` / `serverRestarted` only after `await fetch`, so the `let` TDZ (temporal dead zone) cannot be hit. The combined concatenation passes `node --check`.
- **Read-only visitors.**
  - `loadPending` (2329), `renderPendingSide` (2351), `openPendingList` (2360) and `openPendingItem` (2396) all check `trackerReadOnly`.
  - For a read-only visitor, the Control Room tile gets `pendingCache` as null.
  - `schedulerBlock` and `updateBlock` return null when `crReadOnly()`.
  - `trackerReadOnly` is set from `X-Read-Only` before the first `loadPending`.
  - The server refuses with 403 in every case (server.py:457-471, 647-670).
- **Text escaping on the card, list, tile and Settings.**
  - `renderPendingSide` passes through `esc()` and puts the result in element content only.
  - List rows use `textContent`.
  - The modal title and `when` use `textContent`.
  - Every Control Room and dialog `h()` child string becomes a text node, including dirty file names, `reason`, `restart_error` and the confirm text.
  - The one exception is `md`; see B2.
- **Live re-sync.** `_pendBodyReset` sets `curModal=null` and clears `#msgnav`, so `syncModal` (app.js:2274) leaves the pending modal alone. No Control Room code re-opens `#msgmodal` on a poll.
- **5 s poll cost.** `loadPending` returns early on 11 of every 12 polls. It fetches at most once every 60 s, or every 5 s while a scan runs. No other fetch was added to the poll. The only extra work is N1.
- **Tokens.** `--state-pending`, `--surface-pending` and `--line-pending` are defined in both theme blocks (ext_cr.css:178-180, :393-395). The rule is at ext_cr_board.css:1519-1520.
- **The `t` key** resolves the target by `focusedTileId`, not by DOM index (ext_cr_board.js:3112-3118).

## Blockers

### B1: Resume never passes the prompt. `_with_prompt` is dead code after a `return` (C5 fails in both views)

1. **Defect.** At `aitracker/term_vt.py:3124-3126`, the line `argv = _with_prompt(argv, body.get("prompt"))` is indented inside the `except gateway.GatewayError` block, after its `return`:
   ```python
           except gateway.GatewayError as e:
               return handler._json({"error": str(e), "openrouter_configured": False}, 400)
               argv = _with_prompt(argv, body.get("prompt"))
   ```
   - **Repro:** click Resume on any item. `ExtLaunch.openAt(cwd, "new", prompt)` sends `{cwd, mode:"new", prompt}` (ext_launch.js:331). `open_pty` builds `argv = [launcher]` and never appends the prompt.
   - **Actual:** a bare `claude` starts, with no worktree-cleanup or cleanup instruction.
   - **Expected:** claude starts with the server's `resume_prompt`.

   Copy prompt still works, but the contract says the button "opens a Claude session that uses the cleanup skill". The only test, `tests/test_pending_pty_prompt.py`, unit-tests the pure helper `_with_prompt` and never the route, so the gate is green while the feature is unwired.
2. **Fix direction.** Dedent the call so it runs on the success path of `mode == "new"`. Do not change `_with_prompt`'s guards (4000-char cap, leading `-`), the resume branch or the `cwd` branch.
3. **The way.** In `open_pty`, move the line to the `elif mode == "new":` body after the `try/except`, at the same indent as `gw = ...`. There is no sibling path: `mode == "resume"` deliberately takes no prompt, and the Windows path has no `term_vt`. The bundle inlines `term_vt` unchanged, so the same edit covers it.
4. **Test.** Add a route-level case to `tests/test_pending_pty_prompt.py`:
   - Call `term_vt.open_pty` with a stub handler and body `{"cwd": <tmpdir>, "mode": "new", "prompt": "do it"}`.
   - Patch `gateway.launcher` to return `"claude"`.
   - Capture the argv at the point where the folder path consumes it: patch `term_vt._inject_argv`, or `spawn` and the injection.
   - Assert that the captured argv ends with `"do it"`. This is red today.

   Fallback if stubbing `open_pty` is too heavy: an `ast` test that asserts the `_with_prompt` call is not inside an `ExceptHandler` and does not follow a `Return` in its block.

### B2: Stored XSS from repository content in the item modal (fence break-out plus a mermaid attribute injection)

1. **Defect.** There are two links in the chain.
   - **(a) Fence break-out.** `item_detail` fences git output with `_fence()` (pending.py:928-931), which uses a fence longer than any backtick run inside. The client's `mdBlock`, however, closes a fence on **any** line matching `/^\s*```/` (app.js:205-206). It ignores the opener's length.
     - Diff context lines start with a space, so a context line ` ```` ` from any tracked Markdown file closes the server's fence. `git diff --stat` lines such as ` ```x | 1 +` close it too.
     - Everything after that line renders as Markdown. Links become live (`<a href=https://…>`), and a later context line ` ```mermaid` opens a diagram.
   - **(b) Attribute injection.** The hand-rolled mermaid flowchart renderer puts `classDef` values into a `style="…"` attribute through `esc()`. `esc()` escapes only `& < >`, not `"` (app.js:141, :292-295, :413-414).

   **Repro (run with the real code):** a worktree has an uncommitted change next to these lines of a tracked README:
   ```
    ```
    ```mermaid
    flowchart TD
      classDef x fill:red" onmouseover="alert(document.domain)
      A[hover me]:::x --> B
    ```
   ```
   Opening the item and hovering the node runs the script. The probe was `mdBlock("**git diff**\n" + pending._fence(diff))`.
   - Result: `CHAIN true`. The output contains `onmouseover="alert`.
   - Separately, `FENCE_BREAK … true`: a `[link](https://evil.example)` after a ` ```` ` context line became a live anchor.

   **Impact:** the script runs on the dashboard's origin. A same-origin page passes the `Origin` check on `POST /api/term/pty`, so the script can open a shell or a `claude` with any prompt it likes. That is code execution from a cloned repository's file plus one hover. The sink (b) was already reachable from narration. This feature adds a path from **third-party repository bytes** to that sink.
2. **Fix direction.**
   - (a) A fence closes only on a line made of at least as many backticks as its opener, per CommonMark.
   - (b) Mermaid style values must not be able to leave their attribute.

   Do not change the server `md` contract, `_fence`, or how ordinary 3-backtick fences render. Do not move the pending modal off `openText`.
3. **The way.**
   - **(a)** In `mdBlock` (app.js:205), capture the run with `const fm=l.match(/^\s*(`{3,})\s*([A-Za-z0-9_+-]*)/)`. Close with `new RegExp("^\\s*`{"+fm[1].length+",}\\s*$")` instead of `/^\s*```/`. `fm[1]` becomes `fm[2]` for the language. Apply the same rule to the fence toggle in `hasDraftQuote` (app.js:181), so both agree.
   - **(b)** In `_mmdStyle` (app.js:292-295), keep a value only if it matches `/^[#\w(),.%\s-]+$/`; otherwise drop the key. This covers `fill`, `stroke` and `color` at :413-414 in one place. This fix is wider than the pending surface, because it also closes the pre-existing narration path. That is deliberate: it is the actual sink, and the change is one function.
4. **Tests.** Add a new node-driven module `tests/test_md_fence_xss.py`, reusing the `_PRE` stub from `test_pending_ui_classic.py`:
   - **(i)** `mdBlock("**git diff**\n" + pending._fence(diff_with_context_fences))` produces exactly one `<pre class=mdpre>`, no `<a `, no `mmd-slot`, and no `onmouseover`.
   - **(ii)** `mermaidSvg('flowchart TD\n classDef x fill:red" onmouseover="x\n A:::x-->B')` contains no `onmouseover=`.
   - **(iii)** A regression check: an ordinary 3-backtick fence still renders as before.

   (i) and (ii) are red today.

## Should-fix

### S1: The new controls cannot be reached from the keyboard (classic card, list rows, Scan now, Resume, Copy prompt)

1. **Defect.**
   - `_pendBtn` (app.js:2357) makes a `<span>` with `onclick`. It cannot take focus and has no button semantics.
   - List rows (app.js:2375-2381) are `div`s with `onclick` only.
   - `#pendside` has `role=button tabindex=0` (index.html:98) but no `keydown`, so Enter or Space on it does nothing (app.js:2354).

   **Repro:** Tab to the classic card and press Enter. Nothing happens. In the Control Room the tile opens on Enter, but Tab inside the modal cannot reach Scan now, the rows, Resume or Copy prompt. So C4 and C5 cannot be used from the keyboard in either view.
2. **Fix direction.** Use real buttons and focusable rows. Keep the look and the `pendbtn` class. Do not touch the existing `.mbtn` header spans; that would be a drive-by.
3. **The way.**
   - `_pendBtn`: `document.createElement("button")`, `b.type="button"`.
   - Add `background:none;font:inherit` to `.pendbar .pendbtn` (app.css:649).
   - Rows: `r.tabIndex=0; r.setAttribute("role","button"); r.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openPendingItem(it.id);}}`.
   - In `renderPendingSide`, set `el.onkeydown` the same way, calling `openPendingList`.

   The Control Room shares this modal, so this one change covers both views.
4. **Test.** In `tests/test_pending_ui_classic.py`:
   - The Resume, Copy prompt and Scan now elements have `tagName === "BUTTON"`.
   - `$("pendside").onkeydown({key:"Enter",preventDefault(){}})` opens the list.
   - A row's `onkeydown` Enter fetches `/api/pending/item`.

   These are red today. The test's `find` by `textContent` still works on buttons.

### S2: Update re-derives the terminal policy client-side from a stale count, then sends `confirm_terminals: true`

1. **Defect.** `startApply` (ext_cr_dialogs.js:1270-1276) reads `st.terminals` from the status loaded when the dialog opened. If that is greater than 0, it asks "N open terminals will close". On "Update anyway" it posts `confirm_terminals: true`, and the server then never asks again (update.py:290).
   - **Repro:** open Settings → Server with 1 terminal open. Open 3 more terminals, then press Update and confirm.
   - **Actual:** the confirm said "1 open terminal", and 4 terminals close.
   - **Expected:** the confirm carries the server's count at apply time.

   This also breaks rule 5 (server owns policy): the server already owns this decision through 409 `needs_confirm`, as the plan's A6 text specifies.
2. **Fix direction.** Always post `confirm_terminals: false` first, and let the 409 `needs_confirm` body (its `error` text carries the fresh count) drive the confirm. Do not change the 409 or 202 handling, the restart poll, or the server.
3. **The way.** Make `startApply` call `applyNow(false)` with no preconfirm. The `confirmText = r.body.error` branch at :1284 already renders the server's count.
4. **Test.** In `tests/test_update_settings_ui.py`, change `test_known_open_terminals_ask_before_posting`:
   - Use `_git(terminals=3)` with `applyReplies=[409 needs_confirm "3 open terminals will close"]`.
   - Assert that `posts == [["/api/update/apply", {"confirm_terminals": False}]]` and that the confirm shows the server's text.

   This is red today, because `posts == []`.

### S3: The list shows every worktree, clean ones included, in repo order, so the pending items the card counts are buried (C4)

1. **Defect.** `openPendingList` renders `items.concat(tmp)` in the order the report holds them (app.js:2373). That is discovery order by repo, and it includes every `clean` worktree and primary checkout (`classify`, pending.py:578-616). `build_card` counts only `pending`/`missing` items plus `stale` tmp entries.
   - **Repro:** a repo with 30 clean worktrees and 2 dirty ones.
   - **Actual:** the card says "2 worktrees with unfinished work", and the list shows 32 rows with the 2 dirty ones somewhere in the middle and no marker.
   - **Expected:** the items the card counts come first.
2. **Fix direction.** The server decides the order, or marks which items are hot. The JS must not sort or filter by verdict, because that would re-derive policy. Do not drop clean items; they are useful context, and the Resume prompt works on any of them.
3. **The way.**
   - In `pending.load_report` (pending.py:898-924), stable-sort `r["items"]` by rank `{"pending":0,"missing":1,"unknown":2}.get(verdict,3)`, then by `-last_activity`.
   - Sort `r["tmp"]` with `stale` first.
   - Optionally, set `it["hot"] = verdict in ("pending","missing")` so the client can add one CSS class (`.pendrow.hot{border-color:var(--violet)}`) without deciding anything.

   This covers both views, since the modal is shared.
4. **Test.** In `tests/test_pending_routes.py`, write a `pending.json` with clean, pending, clean items. `load_report()["items"]` must come back with pending first. This is red today.

### S4: Scan now can be silently skipped. The non-blocking lock probe in `load_report` races the scan's own lock

1. **Defect.**
   - `run_async` (pending.py:845-849) starts a thread and returns. `_RUNNING` is set only after the thread takes the lock (pending.py:826-829).
   - `load_report` probes the same non-blocking exclusive lock whenever `_RUNNING` is clear (pending.py:909-911).
   - The client fires `GET /api/pending` straight after the POST (app.js:2369-2370).

   **Repro (race, low probability, higher under GIL contention):** the GET's probe holds the lock while the scan thread runs `_pending_lock()`. `run_once` gets `got=False` and returns `{"running": True}`, so no scan happens. The GET answers `running:false`, the button returns to "Scan now", and no error is shown. The same probe can also make a scheduled `tick()` return `busy`.
2. **Fix direction.** A Scan now accepted by the server must run. Do not make the lock blocking, and do not remove the cross-process probe.
3. **The way.**
   - In `run_async`, check and `_RUNNING.set()` under a small module lock **before** `Thread.start()`.
   - The thread target runs `run_once(mode)` in a `try/finally: _RUNNING.clear()`.
   - Inside `run_once`, keep `_RUNNING.set()`, which is idempotent.
   - The early-return path when the lock is held by another process must also clear the flag. The `finally` in the target covers that.
   - Optionally, retry `_pending_lock()` 3 times at 50 ms inside `run_once` before reporting busy.

   This is server-side (E1/E2 territory). It is listed here because the UI's immediate follow-up GET is the trigger.
4. **Test.** In `tests/test_pending_tick.py`:
   - Patch `run_once` with a stub that waits on an `Event`.
   - After `run_async()` returns, assert `pending._RUNNING.is_set()`.
   - Assert `load_report()["running"] is True` with `_pending_lock` patched to raise if called.

   This is red today.

## Nits

- **N1. `next_due` drifts, so the report always counts as changed.** In `load_report`, `next_due = (scheduled_at or time.time()) + secs` (pending.py:923). With no `scheduled_at`, every fetch differs, so `changed` (app.js:2337) is true each time. That re-renders an open list and fans out `SIDE_EXT`, rebuilding the whole board, every 60 s or every 5 s.
  - **Way:** in `loadPending`, compare `JSON.stringify(Object.assign({}, j, {next_due: 0}))` against the same for the cache.
  - **Alternative (server):** `next_due = None` when there is no `scheduled_at`.
  - **Test:** two identical reports except `next_due` trigger 0 re-renders.
- **N2. Refreshing an open list resets its scroll** (app.js:2341).
  - **Way:** save and restore `$("msgbody").scrollTop` around the `openPendingList` call, as `syncModal` does.
- **N3. The card summary does not carry "scanned N days ago" ([C-S6], plan §6).** The fix is server-only, in `build_card` (pending.py:642): append the age of `generated_at`. The client is unchanged.
  - **Test:** in `test_pending_routes`, the summary contains "scanned".
- **N4. With nothing pending (`card.show` false), Scan now has no entry point.** This includes `PENDING_INTERVAL=off`.
  - **Way:** add a "Scan now" `crBtn` to `schedulerBlock` (ext_cr_dialogs.js:1173) that posts `/api/pending/run` and calls `window.loadPending` if present.
  - **Test:** in `test_update_settings_ui`, the button posts.
- **N5. Scan now failures are silent** (app.js:2369, `.catch(()=>{})`, and the response status is ignored).
  - **Way:** on a non-OK response, set the button text to the server's `error`, or "scan refused".
- **N6. A failed scheduler POST discards the fresh status in its error body** (ext_cr_dialogs.js:1198-1200). `_sched_body(rc)` returns full status plus `error`.
  - **Way:** `if (r.body && 'installed' in r.body) st = r.body;`, then set `err`.
- **N7. `.cr-btn` has no disabled style**, so a disabled "Update and restart" looks clickable.
  - **Way:** add `.cr .cr-btn[disabled]{opacity:.5;cursor:not-allowed}` to ext_cr_dialogs.css.
- **N8. `serverRestarted` reloads every tab and drops unsent drafts** in the note box and the Control Room composer (app.js:1344-1350).
  - **Direction:** leave as is, since it is the A1 decision, and document it.
  - **Optional:** defer the reload while `document.activeElement` is a non-empty textarea or input.
- **N9. A late `openPendingItem` response can take over an unrelated modal** the user opened meanwhile (app.js:2398-2401).
  - **Way:** keep a module counter `pendTok`. Increment it in `openPendingItem` and `openPendingList`, and bail if it changed after the `await`.
- **N10. `test_boot_hook_passes_pending` is a source grep for `"pending:"`** (tests/test_pending_ui_board.py:137). It passes on any substring and does not prove the hook hands `pendingCache` to the board.
  - **Way:** in the bundle harness, set `pendingCache` and run `SIDE_EXT.forEach(f=>f())` with uiMode `next`, then assert the tile appears.

## Not examined

- Theming of `.pendbtn` / `.pendrow` inside the Control Room dark `#msgmodal` bridge (ext_cr_boot.css:163-205), which uses classic tokens.
- Line-by-line content of `tests/test_cr_dialogs_pending_rows.py` (only the case name was read), and the harness internals of `test_update_settings_ui.py`.
- How the standalone `dist/tracker.py` page behaves live (it was only reasoned from the `ExtLaunch` guard), and how the Resume new tab interacts with popup blockers in Safari, given `window.open` after an async fetch (pre-existing path).
- How `_inject_argv` quotes the prompt under zsh once B1 is fixed.
- Mobile/drawer layout of `#pendside`.
- Whether Settings server rows (PENDING_*) should be hidden for read-only visitors. This follows the existing pattern; the 403 is the gate.
- Every other renderer that inserts `esc()` output into attribute values besides the mermaid style. Only `_mermaidSvgFlow` :413-414 was confirmed.

## Fix list

The list is ordered so that fixes to the same file are adjacent.

- **B2a** `aitracker/web/app.js`: `mdBlock` / `hasDraftQuote` close a fence only on a backtick run at least as long as its opener.
- **B2b** `aitracker/web/app.js`: `_mmdStyle` drops values not matching `/^[#\w(),.%\s-]+$/`.
- **S1** `aitracker/web/app.js`: `_pendBtn` becomes `<button type=button>`; rows and `#pendside` get tabindex, role and Enter/Space keydown.
- **N1** `aitracker/web/app.js`: `loadPending` change detection ignores `next_due`.
- **N2** `aitracker/web/app.js`: preserve `#msgbody` scrollTop on the list refresh.
- **N5** `aitracker/web/app.js`: Scan now shows the server's refusal or error.
- **N9** `aitracker/web/app.js`: token-guard the async `openPendingItem`.
- **S1** `aitracker/web/app.css`: `.pendbar .pendbtn` gets `background:none;font:inherit`.
- **S2** `aitracker/web/ext_cr_dialogs.js`: `startApply` posts `confirm_terminals:false` first, with no client preconfirm.
- **N4** `aitracker/web/ext_cr_dialogs.js`: a Scan now button in `schedulerBlock`.
- **N6** `aitracker/web/ext_cr_dialogs.js`: keep the status from the scheduler error body.
- **N7** `aitracker/web/ext_cr_dialogs.css`: `.cr .cr-btn[disabled]` style.
- **S3** `aitracker/pending.py`: `load_report` sorts items pending/missing/unknown/clean, then by recency, and tmp stale first (optional `hot` flag).
- **S4** `aitracker/pending.py`: `run_async` sets `_RUNNING` before the thread starts and clears it in the thread's finally.
- **N3** `aitracker/pending.py`: `build_card` summary appends "scanned N days ago".
- **B1** `aitracker/term_vt.py`: dedent `argv = _with_prompt(...)` out of the `except` block in `open_pty`.
- **B1** `tests/test_pending_pty_prompt.py`: route-level test that `open_pty` appends the prompt.
- **B2** `tests/test_md_fence_xss.py` (new): fence break-out and mermaid attribute-injection cases.
- **S1, N4** `tests/test_pending_ui_classic.py` and `tests/test_update_settings_ui.py`: BUTTON tagName and keydown cases; the Scan now button posts.
- **S2** `tests/test_update_settings_ui.py`: rewrite `test_known_open_terminals_ask_before_posting`.
- **S3** `tests/test_pending_routes.py`: order assertion.
- **S4** `tests/test_pending_tick.py`: `_RUNNING` is set synchronously.
- **N10** `tests/test_pending_ui_board.py`: drive `SIDE_EXT` instead of the source grep.
