# Adversarial review: usage-panel plan, security and server scope

Reviewer: opus adversarial pass, 2026-11-18. Scope: OpenRouter key storage and leak paths, the OpenRouter socket,
the Claude `/usage` run and its cache, rule-6 exception texts, overengineering. Auggie login, UI rendering, tests
and sequencing belong to the other reviewer. They appear here only where they carry a security defect.
Method: grep plus `sed -n` ranges against this worktree. Two harmless live probes against the running service
(`/etc/hosts` and the 403 contrast routes; config.json was never read through the server). One loopback-only urllib
experiment. Key names only, never values.

Severity: **1 blocker, 3 major, 11 minor.**

---

## B1 (blocker): `GET /api/file` returns `config.json` (and so the key) to a DNS-rebinding page

**Defect.** Plan §3.4, §6.1 and §6.3 all claim "no route ever returns it". That is false.
`server.py:571-584` (`/api/file`) opens **any** path the query names. It has no `_local_caller`, no
`_tunnel_route_ok` and no Host check. The only gates it passes are `_authok` (always true when TRACKER_AUTH is unset
and the request isn't via the tunnel, `server.py:383-389`) and `_readonly` (`server.py:342-354`). For a rebinding
Host, `_readonly` falls through to `resolve_tunnel_readonly`, which defaults to False (`config.py:784-795`), and
`TUNNEL_READONLY` is unset in the primary `config.json` today. A rebinding page sends `Origin == Host`, so
`origin_matches_host` passes as well.

**Repro (run live against the service on 8790 and 8787, using a harmless file):**
`curl -H 'Host: rebind.example:8790' -H 'Origin: http://rebind.example:8790' 'http://127.0.0.1:8790/api/file?path=/etc/hosts'`
→ **200** with the content. The same Host on `/api/agents` → 403, and on `/api/tunnel/reveal` → 403.
Swap the path for `<checkout>/aitracker/config.json` → 200 with `OPENROUTER_API_KEY` in the body (and `TUNNEL_PASS` already today).
Expected: 403.

**Fix direction.** Give `/api/file` the same rebinding guard the reveal route has. Do **not** change: the SPA's file
viewer (`app.js:2230`, same-origin from `localhost`/`t<tty>.localhost`), read-only refusal (`/api/file` stays out of
`_RO_GET_ALLOW`), or behaviour when a login is configured (the cookie is the protection there, and an authenticated
full-access tunnel user can already open a terminal and `cat` the file).

**Way.** `server.py:571`, first line of the `/api/file` branch:
```python
if not self._tunnel_route_ok():      # rebinding/CSRF guard: loopback Host + same Origin when no login is configured
    return self._json({"error": "refused: not a same-origin loopback request", "content": ""}, 403)
```
`_tunnel_route_ok` (`server.py:373-379`) already does exactly this. It is one line and needs no new helper. Then drop
"no route ever returns it" from §6.1/§6.3, or keep it only after this lands in step 2 (same commit as the key branch).

**Test (red before).** In `tests/test_openrouter_key_route.py`, add to the leak loop: GET
`/api/file?path=<config.CONFIG_FILE>` with `Host: rebind.example:<port>` → 403, sentinel absent. With
`Host: localhost:<port>` → 200 (unchanged). Today the first assertion fails with a 200 carrying the sentinel.

---

## M1 (major): the `_Bg` rules allow unbounded re-runs after a failure, and `fresh` bypasses the backoff and the 401 hold

**Defect.** Plan §3.1: "Start a run when there is no value, when `age >= ttl` (`fail_hold` after a failure), or when
`fresh` and `age >= floor`." Two gaps follow.
(a) A failure with **no previous good value** isn't defined as storing a value, so "there is no value" stays true.
Every 3 s client poll, or every cross-site `<img>`, starts a new 70 s `claude -p` (or an OpenRouter call) as soon as
the last one ends.
(b) `fresh and age >= floor` overrides `fail_hold`. So `?fresh=1` re-runs OpenRouter every 30 s during a 900 s backoff,
and **also after a 401**, which §3.5 says is "no retry until the key changes".
Both contradict the rule-6 bounds in §6.2 ("at most one run per 60 s") and §6.3 ("back off 30 s doubling to 15 min",
"a 401/403 is not retried").

**Repro.** Producer always raises. `get()` at t=0 starts run 1, which fails at t=1. `get()` at t=4 sees val None →
run 2. Expected: no run before t=1+fail_hold.
OpenRouter returns 401. `get(fresh=True)` at t=+31 s → second call. Expected: zero calls until `invalidate()`.

**Fix direction.** Every completed run, success or failure, stamps `at`. A failure with no good value stores the error
body as the value. A run started by `fresh` is allowed only when the **last run succeeded** and `age >= floor`. After a
failure, the only gate is the hold (`fail_hold`, the OpenRouter backoff, or infinity for `rejected`). Do **not** change:
keep-last-good with `stale: true`, the `gen` drop, single-flight.

**Way.** In `_Bg.get`:
`due = val is None and not ever_ran or (ok_last and (age >= ttl or (fresh and age >= floor))) or (not ok_last and age >= hold)`.
Have the producer return `(body, ok, hold)`. Claude: `hold=60`. OpenRouter: backoff `30*2**(n-1)` capped at 900, or
`float("inf")` for 401/403. Auggie: 5. This takes the OpenRouter-specific state out of `_Bg` (see m8). `invalidate()`
resets `ever_ran`, `ok_last` and `n`.

**Test (red before).** `tests/test_accounts_bg.py`:
- Always-failing producer, patched `time.monotonic`, `get()` at t=0 then t=4 → producer called once. At t=61 → twice.
- `tests/test_accounts_openrouter.py`: 401, then `get(fresh=True)` at +1000 s → exactly 1 opener call. After
  `invalidate()` → 2.
- Timeout at n=3, then `get(fresh=True)` at +31 s → no call (backoff 120 s).

---

## M2 (major): the bundle breaks: qualified `accounts.` references, and `urllib.request` is missing from the HEADER

**Defect.** Plan §2 says server.py does "Import `accounts`" and calls `accounts.invalidate(...)`/`accounts.X`.
`scripts/bundle.py:36-48` strips every top-level import and rewrites only `config.` and `tunnel.` prefixes. A bare
`accounts.claude_usage` in `dist/tracker.py` is a NameError. Separately, `bundle.py` HEADER (line 20) imports
`urllib.parse` but not `urllib.request`. Checked: with exactly the HEADER's imports, `'urllib.request' in sys.modules`
is False. The OpenRouter fetch would raise AttributeError, which the plan's fixed-string error handling turns into a
silent permanent `error` state.

**Repro.** `make bundle && python dist/tracker.py`, then GET `/api/usage/openrouter` with a key saved → 500/NameError
(qualified call), or `state: "error"` (urllib). Expected: same behaviour as the package.

**Fix direction.** Follow server.py's existing import convention (`from .gateway import ...`,
`server.py:9-16`). Do not add a third rewrite rule to the bundler.

**Way.**
- `server.py`: `from .accounts import claude_usage, openrouter_usage, auggie_auth_status, auggie_usage, invalidate as accounts_invalidate`.
- `term_vt.py` (not bundled) may keep `from . import accounts`.
- `bundle.py` HEADER: add `urllib.request` to the import line.
- `accounts.py` itself: `from .update import _run` and `from .gateway import ...`. No `update.`/`gateway.` qualified calls.

**Test (red before).** Add `tests/test_page_bundle.py::test_bundle_header_and_qualifiers`:
`assert "urllib.request" in bundle.HEADER`, and
`assert not re.search(r"(?<![\w.])accounts\.", open("aitracker/server.py").read())`.
No bundle build is needed in the gate.

---

## M3 (major; minor if D2 is accepted): any website can keep the heavy `/usage` run (and the user's hooks) going

**Defect.** Plan §3.6 accepts "the same posture as `/api/claude/auth`". But that route runs a 1 s `claude auth status`,
while this one runs a 70 s `claude -p` that **fires the user's 4 hooks and starts their MCP servers** (handover probe 1,
plan F7). A no-cors `<img src="http://localhost:8790/api/usage/claude?fresh=1">` sends no Origin, so it passes
`_local_caller` (`server.py:225-242`: no proxy header, Origin absent, loopback peer, loopback Host). Any open tab
on any site can then fire the user's hooks once a minute with unknown side effects, and burn one OpenRouter call per
30 s.

**Repro.** `curl -H 'Sec-Fetch-Site: cross-site' -H 'Sec-Fetch-Mode: no-cors' 'http://127.0.0.1:<port>/api/usage/claude?fresh=1'` → a run starts.
Expected: 403 and no run.

**Fix direction.** Refuse a browser request that announces itself as cross-site. Leave CLI callers (no `Sec-Fetch-*`)
and the SPA (`same-origin`) unchanged. Leave the existing `/api/claude/auth` alone (out of scope; mention it as the
same known gap in the PR).

**Way.** In the four new GET branches, after `_local_caller`:
`if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"): return self._json({"error": "refused: cross-site request"}, 403)`.
That is one shared 3-line helper `_same_site(handler)` next to `_local_caller`. Do not fold it into `_local_caller`:
that would change ~20 existing routes.

**Test (red before).** `tests/test_usage_routes.py`: each route with `Sec-Fetch-Site: cross-site` → 403, and the stub
producer is never called. With `same-origin` → 200.

---

## Minor

**m1. `_save_json` mode fix: umask masks it, the new-file default changes other callers, and the first save leaks for a moment.** Plan §3.4.
- `os.open(tmp, ..., mode)` is ANDed with the umask, so "keeps the target's bits" is really "keeps or tightens".
- A new file gets `0o644` where today it gets `0o666 & ~umask`. For example, umask 002 gives 664 today, so the plan's
  "Nothing else changes" is false for flags/titles/pins under a non-022 umask.
- The first key save writes the key into a temp file with the **existing 0644 mode**, `os.replace`s it, and only
  then chmods to 600. Today the primary `config.json` **is** `-rw-r--r--` (checked).
- Cite errors: F2 says `tunnel.py` writes don't chmod, but `tunnel._save_cfg` (`tunnel.py:54-63`) does. §3.4 lists
  `pending.py` as a config.json writer, but it writes only `PENDING_FILE` (`pending.py:1089`).

Repro: umask 002, `_save_json(new_path, {})` → 0644 (was 0664). First key POST on a 0644 config.json → for one
syscall window, a 0644 file holds the key.

Direction: preserve exactly, and keep new files identical to today. Way: in `store._save_json(path, obj, mode=None)`:
```python
if mode is None:
    try: mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError: mode = None
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)
if mode is not None: os.fchmod(fd, mode)
```
The secret branch calls `_save_json(config.CONFIG_FILE, overrides, mode=0o600)` and keeps the post-chmod as a belt.
Test: under `os.umask(0o002)`, a new file → 0o664. An existing 0o600 file stays 0o600. A save with `mode=0o600` on an
existing 0o644 file → the temp is created 0o600 (patch `os.replace` to stat `src` before the swap).

**m2. "account label … read from the cache only (no forced run)" names an API that doesn't exist.** Plan §3.2.
`gateway.claude_auth_status()` (`gateway.py:140-183`) runs `claude auth status` whenever its cache is stale.
`_AUTH_CACHE` (`gateway.py:94`) is private. Calling it from `/api/usage/claude` or from the `_Bg` thread also extends
the existing rule-6 `/api/claude/auth` exception to a new trigger. Way: add
`def claude_auth_cached(): return _AUTH_CACHE["val"]` in gateway.py next to `claude_auth_status`. With None,
`account` is "". Test: patch `_auth_run` to raise and call `claude_usage()` → `_auth_run` is never called.

**m3. The `_OWN_PIDS` fallback (§10, row 4) can't be built on `update._run`.** `_run` (`update.py:63-81`) blocks and
never exposes `p.pid`. Way, if probe 0(a) shows a `~/.claude/sessions/<pid>.json`: record that file's `entrypoint`/`kind`
in the probe and filter on that field in `running_sessions`, or add `on_spawn=None` to `_run`
(`if on_spawn: on_spawn(p.pid)` after Popen; existing callers unaffected). The plan must say which.

**m4. The Server tab triggers the OpenRouter socket just to show "set/not set".** §5 `openrouterKeyBlock` reads
`/api/usage/openrouter`, which starts a fetch whenever the cache has expired. That puts an outbound call behind Config →
Server, which §6.3's wording ("runs only when a local caller reads …") hides. Way: `?peek=1` returns
`{key_set, state, at, …}` from the cache without starting a run (`_Bg.get(start=False)`), and the Server tab uses it.
Test: `GET /api/usage/openrouter?peek=1` with an empty cache → opener never called, `key_set` correct.

**m5. Rule-6 text precision (§6.1-6.3).**
- §6.2 omits the post-failure re-run ("…or 60 s after a failed run").
- D2 must be resolved before the text lands (no bracketed conditionals in a rule).
- The D2 argv list element is the raw string `{"disableAllHooks":true}`. The shell quotes in §3.2 must not reach
  the list.
- The existing `/api/claude/auth` exception says "The dashboard opens no socket itself". Scope it ("…for this run")
  once §6.3 exists.
- Rule 6's base sentence and the existing exceptions' tails ("No other outbound network call is allowed",
  conventions.md gh/update/agent_cli exceptions) contradict §6.3 literally. Amend the base to "No outbound network,
  except as the exceptions below allow; each exception's 'no other call' covers its own module".
- §6.3 should name the proxy behaviour: `build_opener` keeps `ProxyHandler`, which honours `https_proxy` and macOS
  system proxies through CONNECT. TLS stays end-to-end, but "contacts only openrouter.ai" is literally false through a
  proxy. Either say "directly or through the system's configured HTTPS proxy", or pass `ProxyHandler({})`.
- §6.1 should cite the precedent honestly: `TUNNEL_PASS` is already a browser-typed password stored in config.json
  (`config.py:733`, `server.py:804-844`).

**m6. Password-manager capture of the key (security side of §5).** Chrome and Safari ignore `autocomplete="off"` on
`type=password`, and may offer to save the key, synced to the user's cloud account. Way: `autocomplete="new-password"`,
no `<form>` element, and `name`/`id` not containing "password". The static UI test asserts
`autocomplete="new-password"`.

**m7. Lost-update race on config.json (pre-existing, higher stakes now).** `tunnel.py:150-152` rewrites config.json from
cloudflared's reader thread with an `overrides` dict read before the secret POST. The secret branch can be silently
undone, and the launcher then says "No OpenRouter key saved". No change in this feature: it is a known gap, same as
base. Document it in the PR. A real fix means moving every config.json writer to `store._update_json`
(`store.py:373`), which is out of scope.

**m8. Overengineering: `_Bg(sync=True)` is a second code path.** §1's "one code path is tested" is false: inline
under-lock is a different path from the background thread. The OpenRouter backoff and permanent 401 hold also don't fit
`fail_hold` as a constant. Way: drop `sync`, so Auggie auth uses the async path too (the UI already polls on
`refreshing`). Producers return their own hold (M1), so `_Bg` stays at about 35 lines with ttl/floor/gen/keep-last-good
only. If the UI reviewer needs a synchronous Auggie status, copy the 20-line `claude_auth_status` lock shape instead of
adding a mode.

**m9. Probes must prove D2 and gate the credits account.** Probe 0(b) must record the `system/init` line's
`mcp_servers` (expected `[]`) and count `hook_*` lines (expected 0). Otherwise "skips their MCP servers" is unproven,
because claude.ai connectors may not obey `--strict-mcp-config`. Probe 0(c) is a **stop gate**, not a fallback: if the
credits account emits no `usage_report`, the user's verbatim requirement ("must show the usage and also usage credits,
whichever is true") is unmet, and the user decides before step 3.

**m10. OpenRouter fetch hygiene.**
- Call `e.close()` on a caught `HTTPError` (it holds the socket).
- Map `ssl.SSLCertVerificationError` to a distinct fixed string ("TLS certificate check failed — this Python has no
  CA bundle"). python.org builds on macOS often lack certificates, and a generic "error" hides the cause.
- `timeout=10` is per socket operation, not a total deadline. Acceptable, because the call is off-request and
  single-flight, but §6.3 must not call it a 10 s bound. Say "10 s socket timeout".

Test: an opener that raises `ssl.SSLCertVerificationError` → that exact string, and the key sentinel is absent.

**m11. Live finding, outside the plan.** The primary `aitracker/config.json` is `-rw-r--r--` and **already holds
`TUNNEL_PASS`** (key names checked, no values read). That is F2's bug in production: a later `POST /api/config`
re-created the file at 0644 after the tunnel's chmod. Direction: tell the user. A one-off
`chmod 600 aitracker/config.json` in the primary checkout fixes it now, and m1/§3.4 stops recurrence.

---

## Verified OK

- F1: `EDITABLE` (`config.py:229-232`) equals the `snapshot()` key set (`config.py:669-681`), and `/api/config` is in
  `_RO_GET_ALLOW` (`server.py:316-321`). Keeping the key out of EDITABLE is correct.
- F2: `_save_json` (`store.py:18-31`) creates a fresh inode under the umask, and `os.replace` discards an earlier
  chmod. Proven by m11.
- F8: urllib copies `Authorization` across a redirect. Loopback experiment: `[('/a','Bearer S'),('/b','Bearer S')]`.
- `_NoRedirect` (an `HTTPRedirectHandler` subclass whose `redirect_request` returns None) makes a 302 raise
  `HTTPError(302)` with no second request (same experiment). The mechanism is correct.
- Default TLS verification applies with `build_opener()` (PEP 476 default context).
- `apply_overrides` (`config.py:643-654`) iterates only `_PLAIN_ATTR_KEYS`. The key never becomes a module global or
  enters `os.environ`.
- `tunnel_public`/`tunnel_reveal` (`config.py:798-891`) return named keys only. No route spreads `overrides`
  (server.py, tunnel.py greps), except B1.
- `schedule._svc_env` (`schedule.py:257-265`) copies only non-secret `TRACKER_*` plus locale/PATH. The key can't reach
  the plist.
- `dist/` and `config.json` are gitignored (`git check-ignore` for `aitracker/config.json` and `dist/config.json`). The
  bundle never embeds config.json.
- `update._preflight` (`update.py:194-198,223-243`) passes config.json's path, not its content. A failure tail is a
  traceback, not values.
- `log_message` is a no-op (`server.py:1028-1029`). `traceback.print_exc` prints frames, not locals. Nothing logs the
  POST body.
- The secret POST's CSRF posture: `do_POST` refuses a mismatched Origin first (`server.py:665`), then read-only
  (`:671-672`). `_local_caller` adds the proxy, peer and Host checks. A cross-site form POST carries Origin and is refused.
- `_v_or_key`'s regex `[A-Za-z0-9_.\-]{16,256}` accepts `sk-or-v1-<hex>` and rejects CR/LF/space, so header injection
  is blocked. The 400 doesn't echo the value.
- `update._run` (`update.py:63-81`): no shell, stdin DEVNULL, `start_new_session`, killpg on timeout. Correct for both
  CLI runs.
- `claude --help` lists `--no-session-persistence`, `--settings <file-or-json>` and `--strict-mcp-config`.
- Parsing the first `assistant` line's **top-level** `usage_report` matches the recorded probe (handover lines 76-82).
- Credits only when `extra_usage.is_enabled is True` matches the user's "whichever is true". The probed Max account has
  `extra_usage` present with `is_enabled=False` and `monthly_limit=10000`, so "present" alone would wrongly render
  credits on Max.
- The "never spread, fixed error strings" rule for Claude and OpenRouter output: correct, and it mirrors
  `gateway.py:140-183`.
- The insertion point between `server.py:774` and `:775` is correct. The `PENDING_CLEAN` `_local_caller` precedent is
  at `:793-796`.

---

## Clean plan deltas (security/server)

1. **§0 F2**: fix the cites ("`tunnel._save_cfg` chmods; `POST /api/config` doesn't"; drop `pending.py`). Add F10:
   "`GET /api/file` (server.py:571-584) serves any path to a DNS-rebinding page when no login is configured; it gets
   `_tunnel_route_ok`" (B1). Add F11: "primary config.json is 0644 and holds TUNNEL_PASS today" (m11).
2. **§2 files**:
   - server.py: "`from .accounts import …` (no qualified `accounts.`); `/api/file` gains `_tunnel_route_ok`; helper
     `_same_site()`".
   - bundle.py: "HEADER gains `urllib.request`" (M2).
   - gateway.py: "`claude_auth_cached()`" (m2).
   - store.py: "`_save_json(path, obj, mode=None)` per m1".
3. **§3.1 `_Bg`**: replace the rules with M1's. Every run stamps `at`. A failure stores its body. `fresh` only after
   a success. The producer returns `(body, ok, hold)`. Drop `sync` (m8). Add `get(start=False)` for peek (m4).
4. **§3.2**:
   - Account label from `gateway.claude_auth_cached()`.
   - D2 argv written as a Python list with the raw JSON string.
   - Each new GET route also applies `_same_site` (M3).
5. **§3.4**:
   - The secret branch calls `_save_json(config.CONFIG_FILE, overrides, mode=0o600)` and keeps the chmod belt.
   - `_save_json` per m1 (exact preservation via `fchmod`, `0o666` for new files).
   - Remove "no caller relies on the old umask mode".
6. **§3.5**:
   - The OpenRouter producer owns backoff (30 s doubling, 900 s cap) and `rejected` (hold infinity until `invalidate`).
     `fresh` never overrides either.
   - Close `HTTPError`.
   - Distinct TLS-verify string.
   - "10 s socket timeout".
   - State the proxy behaviour (m5/m10).
7. **§3.6**: add the `_same_site` column (all four GET routes). Add a row: `GET /api/file` → `_tunnel_route_ok`.
   Replace "same posture as /api/claude/auth" with "stricter: cross-site browser requests are refused; `/api/claude/auth`
   keeps its known gap".
8. **§5 openrouterKeyBlock**: read `/api/usage/openrouter?peek=1`. Input `autocomplete="new-password"`, no `<form>` (m6).
9. **§6.1**: cite the TUNNEL_PASS precedent. "No route returns it" stays only with B1 landed in the same commit (step 2).
10. **§6.2**:
    - Add "or 60 s after a failed run".
    - Resolve the D2 brackets before landing.
    - "cross-site browser requests are refused".
11. **§6.3**:
    - "a Refresh never overrides a backoff or a rejected key".
    - "directly or via the system HTTPS proxy (CONNECT; TLS end-to-end)".
    - "10 s socket timeout".
    - The Server tab peeks and never triggers a fetch.
12. **Rule 6 base sentence**: "No outbound network, except as the exceptions below allow". Scope the
    `/api/claude/auth` exception's "opens no socket itself" to that run.
13. **§8 tests**:
    - Leak loop adds `/api/file?path=CONFIG_FILE` with a rebinding Host → 403 (B1).
    - `_Bg` failure-with-no-value and fresh-after-failure cases (M1).
    - OpenRouter 401 + `fresh` at +1000 s → 1 call (M1).
    - Bundle HEADER/qualifier static test (M2).
    - `Sec-Fetch-Site: cross-site` → 403, no producer call (M3).
    - umask/`mode=` cases for `_save_json` (m1).
    - `claude_usage` never calls `_auth_run` (m2).
    - `peek=1` makes no call (m4).
    - TLS string (m10).
14. **§9 sequencing**:
    - Step 1 adds m1's `_save_json`.
    - Step 2 adds B1's `/api/file` guard (before any key can be stored).
    - Step 0(b) records `init.mcp_servers` and hook-line count.
    - Step 0(c) is a stop-and-ask gate (m9).
    - Step 3's bundle change includes the HEADER import (M2).
15. **§10 row 4**: replace `_OWN_PIDS` with "filter on the probed session-file field, or `_run(on_spawn=)`" (m3).
    Add a row for m7: "config.json lost-update with tunnel.py's thread — known gap, same as base, in PR".
16. **Hand to the user now**: `chmod 600` the primary `aitracker/config.json` (m11).
