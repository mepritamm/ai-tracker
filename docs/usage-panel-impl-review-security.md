# Usage panel — implementation review (security & server)

Reviewer: adversarial pass (opus), 2026-11-18. Branch `usage-panel`, base `5e4b62d`, head `2bc7edf`.
Scope: `aitracker/accounts.py`, `server.py` (usage routes, `SECRET_EDITABLE` POST branch, `/api/file` guard,
`_same_site`), `config.py`, `store.py` (`_save_json` mode), `gateway.py` (`claude_auth_cached`), `scripts/bundle.py`,
and the rule-6 exception texts. Spec: `docs/usage-panel-plan.md` rev 2, handover "Sign-off" and probe sections.

Method: read the diff per file, then **live probes** against the real `Server` on ephemeral ports (the repo's
`_ServerCase` / `_RemotePeer` harness, from scratch scripts outside the repo), a deterministic race repro for `_Bg`,
a real-socket redirect probe on the live `_acct_open()` opener, and an import of a freshly built `dist/tracker.py`
with stubs. Test modules run one per process with `TRACKER_AUTH` unset: `test_openrouter_key_route`,
`test_usage_routes`, `test_accounts_bg`, `test_accounts_openrouter`, `test_accounts_claude_usage`,
`test_save_json_mode`, `test_page_bundle`. All OK.

**Counts:** Blocker 0 · Major 1 · Medium 2 · Low 2 · Info 5.

---

## M1 (Major) — `/api/file` hands `config.json`, key included, to authenticated non-local callers

**Defect.** `aitracker/server.py:597-613`. The new guard (`:600`) is `_tunnel_route_ok()`, which returns `True`
whenever a credential is in force for the request (`server.py:382-387`). So an authenticated tunnel visitor (the
default: `resolve_tunnel_readonly` returns `False` when `TUNNEL_READONLY` is unset, `config.py:809-820`), or a LAN
caller with `TRACKER_AUTH`, passes the guard and reads any file, including `aitracker/config.json` with
`OPENROUTER_API_KEY`. Terminals are refused to those callers (`_local_caller`), so this is not "they had a shell
anyway". The rule-6 exception ("No route returns the key or any part of it") and the `config.py:131-142` comment
("/api/file refuses rebinding requests") both claim more than the code does. The test
`test_key_never_leaks_through_any_route` (`tests/test_openrouter_key_route.py:138`) never requests `/api/file`, and
`test_api_file_refuses_a_rebinding_host` (`:150`) checks only the no-credential rebinding case.

**Repro (live, real server).**
1. Local `POST /api/config {"key":"OPENROUTER_API_KEY","value":"sk-or-v1-LEAKSENTINEL0123456789"}` → 200.
2. Tunnel visitor: `GET /api/file?path=<CONFIG_FILE>` with `Cf-Ray`/`Cf-Connecting-Ip`, `Host: x.trycloudflare.com`,
   Basic auth = tunnel cred → **actual 200, body contains the key**. Expected: 403, no key.
3. LAN peer (`10.1.2.3`), `config.AUTH="u:p"`, Basic `u:p`, `Host: mybox.lan:8790` → **actual 200 with the key**.

(`/api/config`, `/api/usage/*` and the secret POST are correctly 200-without-key / 403 / 403 for the same visitor.)

**Fix direction.** `/api/file` must refuse the config file **for every caller** (the SPA never needs it through this
route). Keep the existing rebinding guard and the behaviour for every other file unchanged. Do not try to solve it
by forcing read-only or by widening `_tunnel_route_ok`.

**Way.** In the `/api/file` branch, after the `isfile` check and before `open(fp)`:
```python
elif _is_config_file(fp):
    self._json({"error": "refused: config.json holds credentials", "content": ""}, 403)
```
with a module-level helper
```python
def _is_config_file(fp):
    try:
        return os.path.exists(config.CONFIG_FILE) and os.path.samefile(fp, config.CONFIG_FILE)
    except OSError:
        return False
```
Use `os.path.samefile` (device + inode), **not** `realpath` equality. On case-insensitive APFS,
`realpath(".../CONFIG.JSON") != realpath(".../config.json")` while both open the same file (probed: exists=True,
realpath-equal=False). `samefile` also covers symlinks and hard links. Then correct the two texts: the rule-6
exception keeps "No route returns the key" (it becomes true), and `config.py`'s comment should say "/api/file refuses
config.json for every caller". There are no sibling arbitrary-file readers: `open(fp` appears only at `server.py:609`.

**Test (red before the fix).** In `tests/test_openrouter_key_route.py`, add
`test_api_file_refuses_config_json_to_every_caller`. Post the key, then `GET /api/file?path=<CONFIG_FILE>` as
(a) the tunnel visitor (`tunnel.cred` patched to `"tu:tp"`, CF headers, Basic auth), (b) the `_RemotePeer` server
with `config.AUTH="u:p"` and Basic auth, (c) a plain local caller, and (d) the local caller with an upper-cased
basename path (skip it when `os.path.exists` on the variant is False, i.e. a case-sensitive FS). Each must return
403 with the key absent. Today (a), (b), (c) and (d) all return 200 with the key. Also add `/api/file?path=<cfg>` to
`test_key_never_leaks_through_any_route`'s path list.

---

## M2 (Medium) — `_Bg.invalidate()` can wedge a cache in "loading / refreshing" forever

**Defect.** `aitracker/accounts.py:45-49`. `invalidate()` sets `self.running = self._th.is_alive()`. `_work`
(`:72-88`) clears `running` under the lock and then returns, but the thread stays `is_alive()` for a moment after it
releases the lock. If `invalidate()` takes the lock in that window, it sets `running = True`, and nothing will ever
clear it. Every later `get()` takes the `if self.running: due = False` branch (`:54-55`) and returns the placeholder
with `refreshing: True`. The cache stays stuck until another `invalidate()` lands while no thread is alive, or the
process restarts. Triggers: a key save (`server.py:822`) or a login finishing (`term_vt.py:3676-3677`) racing a
finishing run. The window is small, but the outcome is a panel stuck on "Checking…/loading" with no recovery.

**Repro (deterministic).** Wrap `bg._work` so that after the original `_work(gen)` returns, the thread waits on an
Event, so it is alive after the locked section. Then: `get()` → wait 0.2 s → `invalidate()` → release the Event →
`get()` three times over 0.6 s. **Actual:** each `get()` returns `{'state':'loading','refreshing':True}`, the
producer ran once, and `_th.is_alive()` is False. **Expected:** the next `get()` after the thread exits starts a new
run.

**Fix direction.** `running` must mean only "a thread was started and has not yet passed its locked section". It is
already maintained exactly under the lock by `get()` (set) and `_work()` (clear). `invalidate()` must leave it alone.
Keep everything else: the generation drop of a stale result, and single-flight while the old thread is still in the
producer.

**Way.** `accounts.py:45-49`:
```python
def invalidate(self):
    with self._lock:
        self._gen += 1
        running = self.running
        self._reset()
        self.running = running
```
(or drop `running` from `_reset()` and set it once in `__init__`). Drop the `is_alive()` use. It is the bug.

**Test (red before the fix).** In `tests/test_accounts_bg.py`, add `test_invalidate_after_locked_section_does_not_wedge`
with the exact repro above (Event-parked wrapper around `_work`). Assert that after the Event is set and the thread
is joined, the next `get()` starts a second producer call and, after a join, returns the producer's body with
`refreshing False`.

---

## M3 (Medium) — `_save_json` now calls `os.fchmod` on every existing file; Windows on Python < 3.13 has none

**Defect.** `aitracker/store.py:31-39`. When `path` exists, `mode` is always set from `os.stat`, so
`os.fchmod(fd, mode)` runs on **every** write of every existing app file (flags, titles, pins, notes, forks,
config, last_terms…). `os.fchmod` exists on Windows only from Python 3.13. `pyproject.toml` declares
`requires-python >=3.8`, and the codebase carries Windows paths (`store.py`'s `msvcrt` fallback, 29 `os.name == "nt"`
or `msvcrt` sites). On Windows with Python ≤ 3.12, every save to an existing file raises `AttributeError`, the write
is lost, and the fd plus `.<name>.<uuid>.tmp` file are leaked. The original version had none of these failures.

**Repro (simulated).** `_save_json(p, {"a":1})` (new file, OK) → `del os.fchmod` → `_save_json(p, {"a":2})` →
**actual:** `AttributeError: module 'os' has no attribute 'fchmod'`, the content is still `{"a":1}`, and one
`.flags.json.<hex>.tmp` is left behind. **Expected:** the write succeeds.

**Fix direction.** Keep the POSIX behaviour exactly as it is (0600 before data, exact mode kept). Where `fchmod` is
missing, fall back to plain behaviour, which is meaningless on Windows anyway. Never leak the fd or the tmp file on
an error.

**Way.** `store.py:37-41`:
```python
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)
try:
    if mode is not None and hasattr(os, "fchmod"):
        os.fchmod(fd, mode)
    fh = os.fdopen(fd, "w", encoding="utf-8")
except BaseException:
    os.close(fd); os.unlink(tmp); raise
with fh:
    json.dump(obj, fh, indent=2)
os.replace(tmp, path)
```
(The tmp cleanup when `json.dump` fails is optional. It leaks the same way the original version did.)

**Test (red before the fix).** In `tests/test_save_json_mode.py`, add `test_existing_file_write_without_fchmod`:
create the file, then remove `os.fchmod` for the duration (`saved = os.fchmod; del os.fchmod` in try/finally that
restores it, because `mock.patch.object` cannot delete an attribute). Then `_save_json(p, {"a": 2})` must succeed,
the content must be `{"a": 2}`, and no `.*.tmp` may remain in the directory. Red today: `AttributeError`.

---

## L1 (Low) — a missing `Sec-Fetch-Site` header counts as same-origin, so older browsers can trigger runs cross-site

**Defect.** `aitracker/server.py:249-251` defaults an absent `Sec-Fetch-Site` to `"same-origin"`. A cross-site
`<img src="http://127.0.0.1:8790/api/usage/claude?fresh=1">` sends no `Origin` on a GET, has a loopback Host and a
loopback peer, so it passes `_local_caller`. Browsers without Fetch Metadata (Safari < 16.4, Firefox < 90) send no
`Sec-Fetch-Site`. The result is at most one `claude -p /usage` run per 60 s and one openrouter.ai fetch per 30 s.
The response can't be read (no CORS), so nothing leaks. The rule-6 text says "Cross-site browser requests are
refused", which is true only for Fetch-Metadata browsers.

**Repro (live).** `GET /api/usage/claude?fresh=1` with only `Host: 127.0.0.1:<port>` → 200, backend called. With
`Sec-Fetch-Site: cross-site` → 403. With `same-site` → 403.

**Fix direction.** Either (preferred, small) require a custom header that a cross-site no-cors request cannot set.
Or (no code) document the gap. Keep CLI callers working (they can send the header). Do not drop the
`Sec-Fetch-Site` check.

**Way.** `_same_site` returns
`handler.headers.get("Sec-Fetch-Site", "") in ("same-origin", "none") or handler.headers.get("X-AI-Tracker") == "1"`,
with `crCall` in `ext_cr_dialogs.js:1146-1151` always sending `X-AI-Tracker: 1`. That makes an absent
`Sec-Fetch-Site` with no custom header a 403. Alternatively, leave the code and change the rule-6 sentence to
"Cross-site requests from browsers that send Fetch Metadata are refused".

**Test.** `tests/test_usage_routes.py`: a GET with no `Sec-Fetch-Site` and no custom header → 403 and the backend
mock is not called (red today: 200). With the custom header → 200. Update `test_same_origin_and_none_are_allowed`
accordingly.

## L2 (Low) — a stale OpenRouter thread still changes the backoff counter after `usage_invalidate` reset it

**Defect.** `aitracker/accounts.py:262-265,301` changes the module-global `_ACCT_STATE["or_n"]` inside the producer,
before `_Bg._work`'s generation check drops the result. A run in flight with the old key, finishing after a key save
(`usage_invalidate` set `or_n = 0`), sets `or_n` to 1 (or back to 0). The new key's first failure is then held 60 s
instead of 30 s, or a live count is zeroed. The window is bounded and nothing leaks.

**Repro.** `_ACCT_STATE["or_n"]=0`, then `_acct_or_fail("x")` as the old thread would → `or_n == 1`.

**Fix direction / way.** Optional. Capture `g = _OR._gen` at the start of `_acct_or_producer` and change `or_n` only
`if g == _OR._gen` (read without the lock; a race only costs one hold step). Or: no change, a known small gap, noted
here. **Test:** in `test_accounts_openrouter.py`, start a run with a failing opener that blocks on an Event, call
`usage_invalidate("openrouter")`, release, join, then assert `or_n == 0`.

---

## Info (no code change unless noted)

- **I1** — `POST /api/config` with a JSON array body: `body.get` raises at `server.py:802`, the traceback goes to
  stderr and the connection drops. This was already true for every POST route. The traceback shows code lines only,
  never the value. No change, or a one-line `isinstance(body, dict)` guard at the top of `do_POST` if wanted.
- **I2** — If any agent session reads `aitracker/config.json` (for example `cat`), the key lands in that session's
  transcript, which `/api/session` and `/api/output` serve, including to read-only tunnel visitors. This is outside
  the tracker's control. Document it in the rule-6 exception: "agents must not read config.json".
- **I3** — The launcher check `exe == or_launcher()[0]` (`accounts.py:178`) compares paths without `realpath`, so a
  `claude` on PATH that is a symlink to the launcher slips through. This is the same as the `gateway.py`
  `claude_auth_status` precedent, and the risk is low.
- **I4** — `config.json` read-modify-write has no lock between the secret branch and the other writers, so a
  concurrent save can lose an update (the key gets dropped, or a cleared key comes back). This was already true for
  `TUNNEL_*`. Mode safety holds, because `_save_json` stats after the load.
- **I5** — `test_key_never_leaks_through_any_route` hits `/api/usage/openrouter` while the `_Bg` thread may still be
  running, so it can be checking the loading placeholder. The parser-level test
  `test_label_and_key_never_in_body` is the real guard. Folding `/api/file` into this test is M1's job.

## Verified OK

- `OPENROUTER_API_KEY` is not in `EDITABLE` or `_PLAIN_ATTR_KEYS`. `snapshot()` iterates `EDITABLE` only, and
  `apply_overrides` never reads it. Live tunnel `GET /api/config` returned 200 without the key.
- `tunnel_public` and `tunnel_reveal` return only named TUNNEL fields, never a spread of the overrides.
- `os.environ` is written only by `_env_backed` (TERM_APP/TERM_ALLOW) and by the service pid. The key is never in
  the environment or the plist (test covers `service_plist`).
- The update preflight passes the config.json *path* to a child that runs `apply_overrides`. The key is never
  processed there, and only stderr tails are returned.
- `log_message` is silenced. `_Bg._work` swallows producer exceptions into the fixed "internal error". Every
  OpenRouter error string is fixed, with no `str(e)`.
- Secret POST branch: `_local_caller` (proxy headers, Origin, loopback peer, loopback Host when no AUTH), after
  `do_POST`'s Origin check, `_authok` and the read-only deny-all. The value is validated (`[A-Za-z0-9_.\-]{16,256}`
  fullmatch, so no CR/LF header injection) and never echoed. Live tunnel POST → 403.
- `_save_json(mode=0o600)`: `O_EXCL` tmp created at 0600 plus an exact `fchmod` before any data. Later writers keep
  0600 because the mode is read after the load. `config.json` and `dist/` are gitignored (`git check-ignore`
  confirmed).
- `/api/usage/*` and `/api/auggie/auth` are not in `_RO_GET_ALLOW`. A tunnel visitor gets 403, and so do
  `cross-site` and `same-site` callers (live).
- The redirect refusal is wired into the opener used live: `_acct_open()` has `_AcctNoRedirect` and no default
  `HTTPRedirectHandler`. A real-socket 302 raises `HTTPError 302` and the Location target is never contacted.
  `ProxyHandler` is still default-built when a system or env proxy exists, and CONNECT forwards only
  `Proxy-Authorization`.
- The OpenRouter response body never carries the key. Probed with `label` = sentinel, the body has no `label` field.
- The Claude argv matches D2 exactly: `[exe,"-p","/usage","--output-format","stream-json","--verbose",
  "--no-session-persistence","--settings",'{"disableAllHooks":true}',"--strict-mcp-config"]`, run through
  `update._run` with timeout 150 and cwd `~` (captured via the bundle probe).
- `claude_auth_cached()` returns the cache without running the CLI. Its `label` is a plan/method string, never an
  identity.
- `dist/tracker.py` (fresh `make bundle`): imports cleanly. No flattened-namespace collisions for `_run`, `_Bg`,
  `_CLAUDE`, `_OR`, `_AUG` or `month_cost`. With stubs, `openrouter_peek`, `openrouter_usage` (not_set → loading → ok,
  sentinel absent), `claude_usage` (loading → ok with limits and credits), `auggie_auth_status`, `auggie_usage` and
  `usage_invalidate` all work. The new `ssl` and `urllib.*` imports are in the bundle header.
- `_Bg` single-flight and backoff: holds are respected, `fresh` never overrides a failure hold, and 401/403 holds
  `inf` until invalidate. The only defects are M2 and L2 above.
