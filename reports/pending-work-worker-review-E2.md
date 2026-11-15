# Adversarial implementation review E2: update / routes / gates / bundle

Reviewer: E2 (opus), 2026-11-15. I did not edit any source file and ran no tests, servers or make targets. The only probes were an AST walk of `term_vt.py`, a pure-function probe of `util.is_loopback_host` (function body exec'd in isolation), and a name-collision AST probe over bundle ORDER.

Scope: `aitracker/update.py`; the new and changed routes and gates in `aitracker/server.py`; `term_gate.guard`; `util.is_loopback_host`; `term_vt._with_prompt`; `cli.py`; `store._lock_fh`; config `PENDING_*`; `scripts/bundle.py`; and the tests named in the brief.

Counts: **blocker 2 · should-fix 4 · nit 7**.

---

## F1 — BLOCKER: Resume never passes its prompt to Claude (`_with_prompt` is dead code)

**Defect.** In `aitracker/term_vt.py:3122-3126`, inside `open_pty`, the `mode == "new"` branch reads:
```python
        try:
            argv = [gateway.launcher(gw if gw in (gateway.ANTHROPIC, gateway.OPENROUTER) else config.GATEWAY)]
        except gateway.GatewayError as e:
            return handler._json({"error": str(e), "openrouter_configured": False}, 400)
            argv = _with_prompt(argv, body.get("prompt"))      # <- after `return`, inside except: unreachable
```
An AST probe confirms it: "dead code after return in except at line 3126". This is the live Resume path. `app.js:2387` `pendingResume` calls `ExtLaunch.openAt(r.cwd, "new", r.prompt)`, then `ext_launch.js:330-331` posts `{cwd, mode:"new", prompt}` to `/api/term/pty`.
- **Repro:** press Resume on any pending item.
- **Actual:** a bare `claude` opens with no prompt. C5's "uses worktree-cleanup then cleanup" never happens.
- **Expected:** `claude '<resume prompt>'`.
- `tests/test_pending_pty_prompt.py` unit-tests `_with_prompt` only. Its tests pass while the route never calls it.

**Fix direction.** Dedent the call one level so it runs after a successful `try`. Change nothing else in the branch.

**The way.** In `term_vt.py`, inside `elif mode == "new":`:
```python
        try:
            argv = [gateway.launcher(...)]
        except gateway.GatewayError as e:
            return handler._json({...}, 400)
        argv = _with_prompt(argv, body.get("prompt"))
```
Both views share this path (classic `pendingResume`; Control Room through the same `ExtLaunch.openAt`). The bundle has no term_vt, so there is nothing there.

**Test.** Add a route-level case to `tests/test_pending_pty_prompt.py`:
- Patch `term_vt.spawn` and `term_vt._inject_argv` to record argv.
- Drive `open_pty(handler, parsed, {"cwd": tmpdir, "mode": "new", "prompt": "do it"})` with a fake handler (or a guarded test server).
- Assert the typed/spawned argv ends with `"do it"`. This is red today.

---

## F2 — BLOCKER: no Origin check on the new local-only POSTs, so a cross-site page can drive them (CSRF)

**Defect.** `server._local_caller` (`server.py:223-238`) checks three things: proxy headers, peer `127.0.0.1`, and (when there is no AUTH) a loopback Host. It never checks `Origin`. `do_POST` parses any body with `json.loads` whatever its Content-Type (`server.py:622-627`). Plan A.1 required `tg._origin_ok(h)` and fail-closed behaviour (report lines ~1356-1364), but the implementation dropped it. The terminal routes have it (`term_gate.guard` → `_origin_ok`, `term_gate.py:67`); the new routes do not.

**Repro (default, no TRACKER_AUTH).** Any web page the user visits runs:
```js
fetch("http://127.0.0.1:8790/api/update/apply",{method:"POST",mode:"no-cors",body:'{"confirm_terminals":true}'})
```
This is a text/plain simple request, so there is no preflight. The browser sends `Host: 127.0.0.1:8790` from a loopback peer with no proxy headers, so `_local_caller` returns ok.
- **Effect:** the checkout fast-forwards, the dashboard restarts, and **every open terminal is closed (SIGHUP to running Claude sessions)** without the H3 confirmation.
- The same request shape can:
  - set `{"key":"PENDING_CLEAN","value":"safe"}` via `/api/config`, defeating the "safe delete only from this machine" gate at `server.py:701-704`;
  - install or uninstall the launchd job via `/api/scheduler`;
  - trigger scans and gh calls via `/api/pending/run`.
- **With TRACKER_AUTH:** the `ai_auth` cookie is `SameSite=Lax`, and SameSite ignores ports. So a page on another localhost port (any local dev server, `http://localhost:3000`) is *same-site*, its fetch carries the cookie, and the attack still works.
- Chrome's Local Network Access prompt is Chrome-only and does not cover same-site localhost pages. Firefox and Safari have no equivalent.
- **Absent Origin:** browsers send `Origin` on every cross-origin POST (fetch and form), so treating an absent Origin as "curl / same-origin" is acceptable. `Origin: null` (sandboxed iframe, data: URL) must be refused; `urlparse("null").netloc == ""` already does that.

**Fix direction.** Make `_local_caller` refuse a present `Origin` whose netloc differs from `Host`.
- Do not change the existing proxy, peer or Host checks.
- Do not require Origin to be present.
- Keep one copy of the comparison.

**The way.**
- Add `util.origin_matches_host(headers) -> bool` in `aitracker/util.py`. util is always present and in the bundle; term_gate is absent from the bundle. Body:
  ```python
  o = headers.get("Origin", "")
  return not o or urlparse(o).netloc == headers.get("Host", "")
  ```
  (`urlparse` is already imported in util.)
- Make `term_gate._origin_ok(handler)` delegate to it with one line.
- In `server._local_caller`, after the proxy check:
  ```python
  if not origin_matches_host(handler.headers):
      return False, "refused: cross-origin request" + _NOT_LOCAL
  ```
- This covers all callers of `_local_caller`: GET/POST `/api/pending*`, `/api/update*`, `/api/scheduler`, the PENDING_CLEAN=safe gate, and `_readonly()`.
- For `_readonly()` the change only makes a cross-origin request "non-local", which is tighter. The SPA is same-origin, including the `t<tty>.localhost` tabs, whose Origin equals their Host, so it is unaffected.
- **Possibly wider than the defect:** it also applies to GETs. That is harmless, because same-origin GETs carry no Origin or a matching one.

**Test.** Add to `tests/test_local_host_routes.py`, case `test_cross_origin_refused`:
- Each of POST `/api/update/apply`, `/api/update/fetch`, `/api/scheduler`, `/api/pending/run`, and `/api/config` with PENDING_CLEAN=safe.
- Send `Host: 127.0.0.1:P` with `Origin: http://evil.example` → 403, and config.json is unchanged.
- Same with `Origin: null` → 403.
- Same with `Origin: http://localhost:3000` → 403.
- `Origin: http://127.0.0.1:P` → passes.
- No Origin → passes.
- These are red today.

---

## F3 — SHOULD-FIX: a 202 whose response write raises leaves both locks held and no restart

**Defect.** `server.py:660-664`:
```python
self._json(out, code)
if code == 202:
    start_restart(...)
```
`_json` swallows only `BrokenPipeError` and `ConnectionResetError`. Any other socket error skips `start_restart`. Examples: `ConnectionAbortedError`, a socket timeout, macOS `OSError: [Errno 41] Protocol wrong type for socket` on a peer that is closing. The user can cause this by closing the tab during a pre-flight of up to 90 s.

State after that happens:
- The checkout is already fast-forwarded.
- The process keeps running old Python while serving new `web/*`.
- `_APPLY` and the per-user pending **flock** stay held until a manual restart.

Consequences:
- Every later Update returns 409 "update already in progress".
- Every scan, in-process or from the launchd job (the flock is per-user), returns "busy".
- The card shows "scanning…" forever.

**Fix direction.** Schedule the restart whatever happens to the write. Do not change the order "response first, then exec".

**The way.**
```python
try:
    self._json(out, code)
finally:
    if code == 202:
        start_restart(...)
```
The Timer delay (0.5 s) still lets a successful write flush first.

**Test.** Add to `tests/test_update_routes.py`:
- Patch `Handler._json` to raise `ConnectionAbortedError` on the apply route.
- Patch `update_apply` to return 202 and `start_restart` with a mock.
- Assert `start_restart` was called once. Red today.

---

## F4 — SHOULD-FIX: `restart_in_place` handles only `OSError` from `execv`; anything raised earlier kills the thread with the locks held

**Defect.** In `update.py:322-349`, these calls run outside any `try`:
- `tunnel.stop(keep_on=True)`: `os.getpgid` can raise `PermissionError`, which is not caught at `tunnel.py:262-274`.
- `print(recover, flush=True)`: stdout may be a revoked tty or a closed pipe, giving EIO or BrokenPipe.
- `_cloexec_all()`.

If one of them raises, the Timer thread dies:
- There is no exec and no `restart_error`.
- The tunnel is down.
- `_HELD` is never released.

The end state is the same as F3: the checkout is merged and old code keeps running with both locks held indefinitely. The UI then times out with "did not come back" while the server is actually alive.

**Fix direction.** Everything from `tunnel.stop` to `execv` must end in exactly one of two outcomes: a successful exec, or recorded error + tunnel restored + locks released. Do not change the success path.

**The way.** Wrap the whole body after `recover = ...` like this:
```python
try:
    ...existing steps through os.execv...
except BaseException as e:
    _RESTART_ERROR = str(e) or type(e).__name__
    try:
        tunnel.autostart(port, config.BIND_HOST)
    except Exception:
        pass
    _release_held()
```
Keep `print` inside its own `try`, so a dead stdout does not block the exec at all.

**Test.** Add to `tests/test_update_restart.py`:
- Patch `tunnel.stop` to raise `PermissionError`, with `os.execv` mocked.
- Assert `update_status()["restart_error"]` is set.
- Assert `pending._pending_lock()` can be acquired.
- Assert `update._APPLY.acquire(blocking=False)` is True.
- Red today.

---

## F5 — SHOULD-FIX: item detail omits staged changes (contract C4)

**Defect.** `pending.item_detail` (`pending.py:~976-981`) shows `git diff --stat` and `git diff`. Both compare the **working tree to the index**, so staged-but-uncommitted content never appears.
- **Repro:** in a worktree, edit a file and run `git add` on it, then open the item.
- **Actual:** "git diff" is empty; `git status --short` shows only the name.
- **Expected (C4):** "clicking shows the content which has pending work uncommitted".

Sessions often stage before committing, so this is a common case.

**Fix direction.** Show staged and unstaged changes together. Keep the caps, the fencing, and read-only behaviour.

**The way.**
- Use `("diff", "HEAD", "--stat")` and `("diff", "HEAD")`.
- Fall back to `("diff", "--cached")` plus `("diff",)` when `rev-parse --verify -q HEAD` fails (unborn branch).
- While on this line, add `--no-ext-diff --no-textconv --no-color`. Otherwise a user's `diff.external` (for example difftastic) runs and fills the modal with tool output (see N5).
- The renderer is shared by both views; the bundle inherits the change.

**Test.** Add to `tests/test_pending_routes.py`:
- Make a temp repo, stage a change to `f.txt` containing `STAGED_MARK`, and write a pending.json item for it.
- Assert `item_detail(id)["md"]` contains `STAGED_MARK`. Red today.

---

## F6 — SHOULD-FIX: on Windows, Update execs a process that is not "in place" and can break

**Defect.** `update.py:342` calls `os.execv(sys.executable, sys.orig_argv)`, and `update_kind()` returns `"git"` on Windows too, so the button is offered there. On Windows, `os.execv` behaves differently:
- It spawns a new PID and exits the old one, so the console and `make` session see the server exit.
- It does **not quote** arguments, so a `sys.executable` under `C:\Program Files\...` is split into words. Python then tries to run `Files\...\python.exe` as a script, and the dashboard stays dead after the merge has already landed.

R5 allows "ship untested, labelled", but this path predictably leaves the dashboard dead.

**Fix direction.** Do not offer exec-restart on Windows. Keep status and fetch working there.

**The way.** In `update_status()`, after the `kind == "git"` branch fills its fields:
```python
if os.name == "nt" and st["can_update"]:
    st["can_update"] = False
    st["reason"] = "Windows: in-app restart is not supported — `git pull` and restart manually"
```
- **Possibly wider than the defect:** this disables apply on Windows.
- The narrower alternative is to quote `argv` with `subprocess.list2cmdline` per element. That still leaves the new-PID / console-exit behaviour.
- Document the choice in the README's "Windows: untested" line.

**Test.** Add to `tests/test_update.py`:
- With `mock.patch.object(update.os, "name", "nt")` and a behind-by-1 fixture, assert `can_update` is False and the reason mentions Windows.
- Assert `update_apply()[0] == 409`.
- Red today.

---

## Nits

- **N1 — TOCTOU across the ≤90 s pre-flight** (`update.py:288-297`). Terminals, HEAD, branch and dirty state are checked before `_preflight`, not again before `merge`.
  - A terminal opened during the pre-flight is closed without the H3 confirmation.
  - A branch switch during the pre-flight can fast-forward a different branch to `target`.
  - No work is lost, because git refuses to overwrite local edits.
  - **Fix:** just before `merge`, re-run `symbolic-ref`, `rev-parse HEAD` and `status --porcelain --untracked-files=no`, plus `_term_live()`. Return 409 if any of them changed (or the terminal count rose without confirmation).
  - **Test:** in `test_update.py`, have `_preflight` patched to create a commit; expect 409 and HEAD unchanged.
- **N2 — merge rc ≠ 0 after a completed merge** (`update.py:295-297`). A slow post-merge hook hits the 60 s timeout: `rc` is None, the route returns 409 "refused", there is no restart, and HEAD is already `target`.
  - **Fix:** on rc ≠ 0, check whether `rev-parse HEAD` equals `target`; if it does, continue to 202.
  - **Test:** patch `_g` so `merge` returns `(None, "timeout")` after really merging.
- **N3 — control characters in `_with_prompt`** (`term_vt.py:2951-2957`). The prompt is typed into a login shell via `_inject_argv`. `shlex.join` does not neutralise bytes such as `^U` / `^C`, or a `\x1b[201~` that ends bracketed paste early. The server-built resume prompt embeds disk-derived paths, and directory names can contain such bytes.
  - **Fix:** return `argv` unchanged when `any(ord(c) < 32 or c == "\x7f" for c in p)`.
  - **Test:** `_with_prompt(["claude"], "a\x15rm -rf ~")` → `["claude"]`.
- **N4 — resume prompt can exceed the 4000-character cap.** With many session ids, `pending.resume_prompt` passes 4000 characters and `_with_prompt` silently drops it.
  - **Fix:** cap `sids` in `resume_prompt` (first 10 + "and N more").
  - **Test:** 200 fake sids → `len(prompt) <= 4000`.
- **N5 — unbounded line length in item detail** (`pending.py` `_cap`). The cap is per line count only, so one minified line can be megabytes.
  - **Fix:** in `_cap`, truncate each line to about 2000 characters.
  - The `--no-ext-diff` part is folded into F5.
- **N6 — pre-flight reads config.json strictly** (`update.py:185-189`). `json.load(open(cfg))` makes every Update fail with a traceback when config.json is corrupt, while the running server tolerates it via the lenient `_load_json`.
  - **Fix:** in the pre-flight code, use `from aitracker.store import _load_json; config.apply_overrides(_load_json(sys.argv[2], {}) if sys.argv[2] else {})`.
- **N7 — dead or misleading lines.**
  - `os.environ.pop("TRACKER_RESTARTED", None)` (`update.py:331`) refers to an env var nothing else uses; delete it.
  - `TRACKER_PENDING_INTERVAL=off` in the pre-flight env is overridden by config.json precedence. It is harmless because the pre-flight never calls `run()`; fix the comment or drop it.
  - `term_gate._is_loopback` still holds its own `_LOOPBACK_NAMES` / `ipaddress` copy, although plan A.1 said it would delegate to util. There is no behaviour bug; optionally delegate.

## Checked and OK (no finding)

- **`is_loopback_host`.** Probed and refused correctly: `localhost.evil.example`, `127.0.0.1.evil.example`, `localhost.`, `127.0.0.1.`, `user@localhost`, `localhost@evil.com`, bare `::1`, `[::1]:`, `localhost:`, `127.1`, `2130706433`, `0.0.0.0`, and `[fe80::1%lo0]`. Accepted: `localhost[:p]`, `127/8`, `[::1][:p]`, and `*.localhost` (as ruled).
  - It also accepts raw-client-only junk such as `evil.com/.localhost` and `a b.localhost`. A browser never sends these, and a raw client is already local, so I recommend no change.
- **Tunnel, read-only and non-local callers.** Refused on every new route:
  - tunnel callers by the proxy headers;
  - read-only callers by `_RO_GET_ALLOW` and the deny-all POST;
  - LAN peers by the peer check.
- **DNS rebinding.** Without auth it is refused by the Host check. With auth it gets 401, because the cookie is host-only and Basic auth is unknown to the attacker.
- **Request values.**
  - `id` is used only for an equality lookup.
  - `confirm_terminals` must be `is True`.
  - `action` is an enum.
  - The fetch ignores the body.
  - Remote, branch and sha come from git config and `rev-parse`; only a 40-hex sha is merged.
  - No shell is used anywhere in update.py.
- **Same sha.** The same `target` sha is archived, pre-flighted and merged, and the merge is `--ff-only`. The dirty check rejects tracked edits; untracked collisions are refused by git itself.
- **No hang on prompts.** Fetch and other git calls run in their own session with stdin from DEVNULL, `GIT_TERMINAL_PROMPT=0` and `GCM_INTERACTIVE=never`, and a timeout that kills the process group. An SSH prompt cannot hang the server on POSIX.
  - Windows `_run` kills only git, but the post-kill `communicate` is bounded at 5 s and its exception is swallowed, so the wait is bounded.
- **Lock release on non-202.** Every non-202 outcome releases both locks: busy, a failed `__enter__`, an exception, and an exec `OSError`.
- **`_cloexec_all`.** It covers the inheritable pty masters, and the listening socket is non-inheritable.
- **`_safe_extract`.** It rejects absolute paths, `..`, escaping links and device nodes.
- **Bundle.**
  - Only one top-level name collides: `_root`, in `schedule.py` and `update.py`, and the two bodies are identical.
  - `stop` / `autostart` are not shadowed.
  - The header has `io`, `tarfile`, `tempfile` and `contextlib`.
  - `update_kind()` returns "bundle", so apply returns 409 there.
  - `config.` is also rewritten inside `_PREFLIGHT_CODE`'s string, but that code is unreachable in the bundle.
  - The bundle header's unconditional `fcntl` import pre-dates this work (base `b3d6230`).
- **`store._lock_fh`.** The msvcrt fallback is OK; unlock runs only after a successful acquire.
- **Reachability.** `start_worker()`, the autoinstall thread (honours `TRACKER_SCHEDULER_AUTOINSTALL=0`, never raises), `_term_modules()` (returns `()` on nt) and `X-Server-Started` (consumed by `app.js:1333/1344`) are all reachable.

## Residual exposure under the main thread's ruling (direction: no change in this PR; record it)

Because the Host check lives only in `_local_caller` and `guard`, a no-auth DNS-rebinding page can still:
- read every transcript (`/api/session`, `/api/search`, …);
- call `GET /api/tunnel/reveal` or `POST /api/tunnel/ctl {"action":"rotate_creds"|"start"}` and **read back the tunnel credentials**, since the response is same-origin to the rebinding page.

That second point turns a local rebinding into a remote foothold, read-only or full depending on TUNNEL_READONLY. If the main thread wants to close it, the narrowest fix is to gate `/api/tunnel/reveal` and `/api/tunnel/ctl` with `_local_caller`. That is wider than this review's scope; flagged for a decision.

## Not examined

- The SPA's markdown renderer escaping of `item_detail` md: path or branch text inside inline code, possible HTML injection.
- `schedule.py` internals: `sched_status` / `sched_install` call `launchctl` / `schtasks` without a timeout on the request thread.
- `pending.py` scan, classify and clean.
- The Control Room / classic UI code beyond the Resume and Update call paths.
- `tests/test_pending_windows_shims.py` and `tests/test_pending_config.py` beyond their test names.
- Whether `execv` from a non-main thread is safe on this exact macOS build. The plan says it was probe-confirmed; I did not re-run that.

## Fix list

- F2 · `aitracker/util.py` — add `origin_matches_host(headers)` (absent Origin → True, else netloc == Host).
- F2 · `aitracker/term_gate.py` — `_origin_ok` delegates to `util.origin_matches_host`.
- F2 · `aitracker/server.py` — `_local_caller`: refuse a mismatched Origin right after the proxy-header check.
- F3 · `aitracker/server.py` — apply route: `try: self._json(out, code) finally: if code == 202: start_restart(...)`.
- F4 · `aitracker/update.py` — `restart_in_place`: wrap everything before and including `execv` in `try/except BaseException` → set `_RESTART_ERROR`, call `tunnel.autostart`, `_release_held()`.
- F6 · `aitracker/update.py` — `update_status`: on `os.name == "nt"`, `can_update=False` with a Windows reason.
- N1 · `aitracker/update.py` — `_apply_locked`: re-check HEAD, branch, dirty state and terminal count right before `merge`.
- N2 · `aitracker/update.py` — `_apply_locked`: merge rc ≠ 0 but HEAD == target → continue to 202.
- N6 · `aitracker/update.py` — `_PREFLIGHT_CODE`: load config via `store._load_json`.
- N7 · `aitracker/update.py` — drop the `TRACKER_RESTARTED` pop; fix the pre-flight env comment.
- F1 · `aitracker/term_vt.py` — dedent `argv = _with_prompt(...)` out of the `except` block.
- N3 · `aitracker/term_vt.py` — `_with_prompt`: reject prompts containing control characters.
- F5 · `aitracker/pending.py` — `item_detail`: `diff HEAD` (with an unborn-branch fallback) plus `--no-ext-diff --no-textconv --no-color`.
- N4 · `aitracker/pending.py` — `resume_prompt`: cap the listed sids.
- N5 · `aitracker/pending.py` — `_cap`: truncate long lines.
- Tests:
  - `test_pending_pty_prompt.py`: the route-level argv case.
  - `test_local_host_routes.py`: the cross-origin cases.
  - `test_update_routes.py`: write raises → restart still scheduled.
  - `test_update_restart.py`: `tunnel.stop` raises → locks released.
  - `test_update.py`: the nt case, N1 and N2.
  - `test_pending_routes.py`: staged diff shown.
