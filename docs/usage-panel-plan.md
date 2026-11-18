# Technical plan: Config → Usage tab, Auggie login, OpenRouter key

Written 2026-11-18 by the plan agent; **revision 2** (same day) folds in the reconciled review. Worktree
`.claude/worktrees/usage-panel`, branch `usage-panel`.

Inputs:
- `docs/usage-panel-handover.md`: contract, user answers, probe shapes, and the verdict table under "## Plan → review → reconcile".
- `docs/usage-panel-research.md`.
- `docs/usage-panel-review-security.md` and `docs/usage-panel-review-ui.md`.

Every `file:line` cite was read in this worktree. No feature code exists yet.

## 0. Findings that shape the plan

| # | Finding (evidence) | Consequence |
|---|---|---|
| F1 | `config.EDITABLE` (config.py:229-232) is exactly the key set that `snapshot()` (config.py:669-681) publishes on `GET /api/config`. That route is in `_RO_GET_ALLOW` (server.py:316-321), so tunnel visitors can read it. | `OPENROUTER_API_KEY` must **not** join `EDITABLE`. It is written through `POST /api/config`, but by a separate branch with its own allowlist, `config.SECRET_EDITABLE`. The precedent is `TUNNEL_PASS`, a browser-typed password already stored in config.json (config.py:733, server.py:804-844). |
| F2 | `store._save_json` (store.py:18-31) writes a fresh temp file under the umask and `os.replace`s it, which discards any earlier chmod. `tunnel._save_cfg` (tunnel.py:54-63) and `POST /api/tunnel` (server.py:830-833) chmod 600 afterwards. `POST /api/config` (server.py:797-799) does not. | Any later ordinary settings write re-creates config.json at 644. Fix: `_save_json(path, obj, mode=None)` keeps the existing mode exactly (§3.4). |
| F3 | `auggie auth login` without `--headless` returns `continue-interactive` after success and starts the agent (auggie-v2.mjs:6359 `O3o` sets `n = headless \|\| AUGMENT_LOGIN_FAST_EXIT`; the return is at :6361). When a credential already exists, it first asks `Continue with reauthentication?` (y/N, fn `k3o`). The flow is a loopback callback plus a browser, with a 600 s OAuth timeout, which is under `LOGIN_WATCH_MAX` 1800 s. | The login argv is `auggie auth login --headless`. The help line warns about the y-confirm. |
| F4 | `auggie auth status` prints `Logged in.` with rc 0 (observed exactly `Logged in.\n`, 1.6 s). Logged out, it prints `Not logged in.` with rc 1. A read failure prints `Authentication status could not be read.` on stderr with rc 1 (`P3o`). There are no account fields. | Status = rc + **any** stdout line equal to the expected text. Auggie 1.3 reports **no account identity**, and the UI says so. |
| F5 | The Claude login is `claude auth login`, with no transcript and no cleanup (term_vt.py:3629-3634). `_login_finished` (term_vt.py:3650-3655) stamps `last_login.json` for **every** login pty. | An Auggie login must not stamp Claude's record, so `_login_finished` is gated by login kind. Auggie needs no transcript cleanup (F3, F6). |
| F6 | `sessions-v2` is Auggie 1.3's own session store (bundle constant `ble="sessions-v2"`; export path `sessions-v2/--path--/session.jsonl`). `auggie auth status` created `sessions-v2/<cwd-slug>/` (empty) and `~/.augment/auth.json` at 15:07 today. | See F12 for what is actually on disk. |
| F7 | The probe's `/usage` run took `total_duration_ms` 68 438. Four of the user's hooks fired, and MCP servers load. | The run is background-only, with a cache; routes never block (§3.1). |
| F8 | `urllib` copies `Authorization` onto a redirected request, even across hosts. The security review's loopback experiment confirmed it. | The OpenRouter opener refuses redirects. |
| F9 | Several places say "no outbound network" or "nothing leaves the machine": README.md:68, CLAUDE.md "What this is", conventions rule 6 (base sentence and the exception tails), and tests/test_links_liveness.py:23. | Each is amended (§6.5). |
| F10 | `GET /api/file` (server.py:571-584) opens any path with no `_tunnel_route_ok` or Host check. A DNS-rebinding page gets 200 when no login is configured (live repro by the security review). It can already read `TUNNEL_PASS` this way today. | `/api/file` gains `_tunnel_route_ok()` (server.py:373-379) in step 2, before a key can be stored. |
| F11 | The primary checkout's `aitracker/config.json` is `-rw-r--r--` and already holds `TUNNEL_PASS` (key names checked only). | User action now: `chmod 600` that file. The session does not touch the live checkout. |
| F12 | **On-disk check of `~/.augment/sessions-v2/` (2026-11-18): it holds no session file.** The only entry is the empty directory `--Users-…-worktrees-usage-panel--/` (created 15:07 by the probe). There is no `session.jsonl` anywhere under `~/.augment`. Legacy `~/.augment/sessions/` has 88 files, the newest modified Sep 16 19:21, and `prompt-history.jsonl` also stopped on Sep 16. So Auggie has not been used here since Sep 16, and no 1.3 session file exists to read. | The v2 record shape **cannot be confirmed from a real file today** (conventions rule 7). The bundle hints at the shape (`billing_metadata.cost_usd` → `usage.cost.total` as a Number, plus `model_cost_usd_micros`), but that is unconfirmed. So the v2 cost reader waits on probe 0(f) (§3.3, §9). |
| F13 | `aitracker/config.json` is **per checkout**: `config.CONFIG_FILE = <package dir>/config.json` (config.py:224). The 8790 service runs from the primary checkout, so a key saved there lands in `/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/aitracker/config.json`. A worktree-run server reads and writes its own file and sees no key. | The launcher snippet uses that absolute path. The key row says which file it saved to (§5, §7). |
| F14 | Under launchd, the server's PATH is whatever PATH the installer's shell had, frozen into the plist (`schedule._svc_env`, schedule.py:263). `agent_cli.agent_specs()` (agent_cli.py:215-223) resolves each tool's binary with `shutil.which(bin)` on that PATH, and the Agents panel shows the result. | `accounts.py` resolves `claude` and `auggie` through `agent_cli._agent_spec(id)["path"]`, the same resolution and the same answer the Agents panel shows. A missing binary says "not found on the server's PATH (Config → Agents shows the same); reinstall the service from a shell where it is on PATH". |

## 1. Design choices

| Area | Choice | Why |
|---|---|---|
| Module | New `aitracker/accounts.py` holds the Claude `/usage` run, the Auggie auth-status run, the OpenRouter fetch, and one small cache class `_Bg`. | All three are account-level, not session-level. The Provider seam is the session seam. |
| Imports | By name only: `from .update import _run`, `from .gateway import claude_auth_cached, or_launcher, openrouter_configured`, `from .agent_cli import _agent_spec`, `from .providers.auggie import month_cost`, `from .store import _load_json`. `config.X` stays (the bundler rewrites it). server.py uses `from .accounts import claude_usage, openrouter_usage, openrouter_peek, auggie_auth_status, auggie_usage, usage_invalidate`. Every top-level name in accounts.py is unique in the flat bundle (`_acct_*`, `usage_*`). | `scripts/bundle.py` strips imports and rewrites only the `config.`/`tunnel.` prefixes (bundle.py:36-48), so a qualified `accounts.` would be a NameError in `dist/tracker.py`. |
| Auggie cost | `providers/auggie.month_cost(since)`. Legacy `sessions/*.json` (shape known) is summed now. The `sessions-v2/*/session.jsonl` reader is added only after probe 0(f) records a real file's shape (F12). | Rules 1 and 7. |
| Cache | `_Bg(ttl, floor, producer)`: background thread only, no `sync` mode. Every run stamps its time. The producer returns `(body, ok, hold)`, so OpenRouter's backoff and 401 hold live in the producer and not in `_Bg`. | One code path. Bounded runs, so the rule-6 limits hold (§3.1). |
| Routes | Four separate GETs plus `?peek=1` for OpenRouter. Each section paints independently, and the Server tab never triggers a fetch. | F7, U-M3. |
| Server owns text | The server builds every label, amount string and message. The client formats only `resets_at` and `at` with `toLocaleString`. | Rule 5. |
| Placement | Registration (Claude login, Auggie login, OpenRouter key) goes in **Config → Server**. The **Usage** tab, after `Agents`, only displays. | D1. |

## 2. Files and symbols

| File | Change |
|---|---|
| `aitracker/accounts.py` (new) | `_Bg`, `claude_usage(fresh)`, `_acct_parse_usage_report(ur, sub)`, `openrouter_usage(fresh)`, `openrouter_peek()`, `_acct_parse_or_key(d)`, `_acct_or_producer()`, `auggie_auth_status(fresh)`, `auggie_usage()`, `usage_invalidate(name)`, `_acct_or_key()`, `_acct_open` (the opener factory, patched in tests), constants (§3). |
| `aitracker/gateway.py` | `def claude_auth_cached(): return _AUTH_CACHE["val"]` beside `claude_auth_status` (gateway.py:140). It never runs the CLI. |
| `aitracker/config.py` | The exception comment after `AUTH` (config.py:120-131, §6.1). Then `SECRET_EDITABLE = ("OPENROUTER_API_KEY",)`, `_v_or_key` and `SECRET_VALIDATORS` near `EDITABLE` (:229). `EDITABLE`, `snapshot` and `apply_overrides` are unchanged. |
| `aitracker/store.py` | `_save_json(path, obj, mode=None)` (store.py:18-31), §3.4. |
| `aitracker/server.py` | Name imports (above). Helper `_same_site(handler)` next to `_local_caller` (:225). GET branches for `/api/usage/claude`, `/api/usage/openrouter` (+`peek`), `/api/usage/auggie` and `/api/auggie/auth` beside `/api/claude/auth` (:509-518). `/api/file` (:571) gains `_tunnel_route_ok()`. A `SECRET_EDITABLE` branch between :774 and :775 of `POST /api/config`. `_RO_GET_ALLOW` is **unchanged**. |
| `aitracker/providers/auggie.py` | `month_cost(since)` and `_AUGGIE_BILL_CACHE` beside `list_auggie` (:314). |
| `aitracker/term_vt.py` | Constants `AUGGIE_LOGIN_PROMPT` and `AUGGIE_LOGIN_ARGS`; a branch before `gateway.launcher` (:3333). **`LOGIN_ARGV` is unchanged.** `_login_finished` (:3650) gets a kind gate and `usage_invalidate`. term_vt is not bundled, so `from .accounts import usage_invalidate` is fine. |
| `aitracker/web/ext_cr_dialogs.js` | `'Usage'` in `sections` (:1755); a branch in `renderSection` (:1855); `usageBlock()`, `auggieLoginBlock()` and `openrouterKeyBlock()` next to `claudeLoginBlock` (:1624); the Server branch (:2044) appends the latter two after `loginEl`; `renderClaudeLogin` (:1695) title becomes `payload.title \|\| 'Claude Code login'`. |
| `aitracker/web/ext_cr_dialogs.css` | `.cr-usage-*` rows and bars, using the existing severity tokens. |
| `scripts/bundle.py` | `ORDER` (:11-15): add `"accounts.py"` after `"agent_cli.py"`. The HEADER import line (:21) gains `ssl, urllib.error, urllib.request`. |
| `.claude/rules/conventions.md` | Rule 6 base sentence, the three new exceptions, and scoping the `/api/claude/auth` text (§6). |
| `README.md:68`, `CLAUDE.md`, `tests/test_links_liveness.py:23` | One-sentence amendments (§6.5). |
| tests | §8. **No existing test is edited** (the pinned `LOGIN_ARGV` test stays as it is). |

## 3. Server design

### 3.1 `_Bg` (accounts.py, about 35 lines)

```python
class _Bg:
    """Background single-flight cache. get() never blocks: it returns the last body (or a loading placeholder)
    with refreshing/stale/at, and starts at most one thread. Every finished run (ok or not) stamps _t; a failure
    with no earlier good body stores the error body. A run's result is dropped if usage_invalidate() ran meanwhile."""
    def __init__(self, ttl, floor, producer): ...   # producer() -> (body: dict, ok: bool, hold: float seconds)
    def get(self, fresh=False) -> dict
    def invalidate(self)                             # gen += 1; body = None; ran = False; ok_last = True; hold = 0
```
- **When a run is due:** `(not ran) or (ok_last and (age >= ttl or (fresh and age >= floor))) or (not ok_last and age >= hold)`. `fresh` never overrides a failure hold.
- **Clocks:** `age` uses `time.monotonic()` (`_t`). The body's `at = int(time.time())` is stamped at completion, for display.
- **On failure:** with a good body already held, keep it, set `stale: True` and copy `error`. With none, store the error body.

| Producer | ttl | floor | hold after a failure |
|---|---|---|---|
| Claude `/usage` | 300 | 60 | 60 |
| OpenRouter `/key` | 300 | 30 | `30*2**(n-1)` capped at 900; `float("inf")` for 401/403 until `usage_invalidate("openrouter")` |
| Auggie auth status | 60 | 5 | 5 |

### 3.2 Claude usage

| Item | Value |
|---|---|
| exe | `_agent_spec("claude")["path"]` (F14). Refused when it is missing or equals `or_launcher()[0]` (the gateway.py:155 check). |
| argv (Python list) | `[exe, "-p", "/usage", "--output-format", "stream-json", "--verbose", "--no-session-persistence"]`. If D2 is accepted, append `"--settings", '{"disableAllHooks":true}', "--strict-mcp-config"`, where the JSON is one raw list element with no shell quoting. |
| spawn | `_run(argv, 150, cwd=~)` (update.py:63-81) |
| parse | stdout lines → `json.loads` each, skipping bad lines. Use the first `type=="assistant"` object whose **top-level** `usage_report` is a dict. |
| account label | `claude_auth_cached()`: `label` and `subscription`, or `""` when cold. **It never runs `claude auth status`**. |
| never spread | The body is built from named fields. No stdout or stderr text is forwarded. Errors are fixed strings. |

`_acct_parse_usage_report(ur, sub)` returns `(limits, credits)`:

| Input | Output |
|---|---|
| `rate_limits.limits[]` | Each row becomes `{"kind","label","percent","resets_at","severity","active"}`. `label` is "Current session", "Current week (all models)", or "Current week (<name>)", where `<name>` = `scope.model.display_name` or `scope.surface.display_name`, printable, ≤40 chars. An unknown kind becomes `kind.replace("_"," ").capitalize()` + `" (<name>)"`. `percent` is a rounded number in 0-100, else `None`. `resets_at` is kept only if it is ISO-8601, else `None`. `severity` is one of normal/warning/critical, else normal. Rows keep the server's order and are rendered verbatim. |
| `extra_usage` absent, or `is_enabled is not True` (incl. `"true"` and `1`) | `credits = None`; nothing renders. This is the probed Max account. |
| `is_enabled is True` (**gated on probe 0(c), step 3b**) | `{"used_minor","limit_minor","utilization","currency","text","note"}`. Amounts are minor units (documented: cents for USD): USD → `"$%.2f" % (m/100)`, any other currency → `"%.2f %s"`. `text` = "$12.34 spent of $50.00 this month". When `monthly_limit` is `None`, `text` = "$12.34 spent this month · no monthly limit of its own". `note` = "your organisation's limits apply" when `sub` ∈ {team, enterprise}. **"Unlimited" is never emitted.** |

Before step 3b lands, `credits` is always `None`. A disabled account renders correctly by construction.

`GET /api/usage/claude` → `{"state":"ok|no_report|unavailable|error|loading", "refreshing", "stale", "at", "account", "limits":[…], "credits":null|{…}, "message", "error"}`.
- `no_report` message: "Claude Code returned no plan usage for this login (API key, OpenRouter, setup-token or usage-based billing logins don't report it)."

### 3.3 Auggie

| Item | Value |
|---|---|
| auth | `_run([_agent_spec("auggie")["path"], "auth", "status"], 20, cwd=~)` with the default `_git_env()`. rc 0 and **any** stripped stdout line `== "Logged in."` → `logged_in: True`, label "Logged in · Augment (account name isn't reported by auggie)". rc 1 and any line `== "Not logged in."` → `logged_in: False`, label "Not logged in". Anything else → `error: "couldn't read auggie auth status"`. Exact equality, no prefix match. Goes through `_Bg` (async; the UI polls `refreshing`). |
| `GET /api/auggie/auth` | `{"available","logged_in","label","error","refreshing"}`, whitelisted like `_CLAUDE_AUTH_KEYS` (server.py:245) |
| `month_cost(since)` | → `{"usd","sessions","unpriced","sources"}`. **Legacy** `config.AUGGIE_SESSIONS/*.json`: skip files with mtime < since without opening them. Sum `float(rn.billing_metadata.cost_usd)` (a str) over `chatHistory[i].exchange.response_nodes[]`, keeping item `i` when `chatHistory[i].finishedAt` (ISO with ms and Z) ≥ since, else the file's `modified` decides. Sub-agent cost comes from the existing `_sub_agent_usd(d)` (auggie.py:527-530) and counts when `modified` ≥ since. A non-numeric value adds 0 and increments `unpriced`. The cache key is `(path, mtime, since)`. **v2** (`~/.augment/sessions-v2/*/session.jsonl`): implemented in step 3c only after probe 0(f) records a real file's shape. It adds field paths here with the same rules. Until then `sources` = `["~/.augment/sessions"]`. |
| window | Calendar month to date, UTC (D3). It is Augment's only documented reset. |
| `GET /api/usage/auggie` | `{"available","label":"Local session cost, not account balance","window":"This month (UTC, from Nov 1)","cost_text","sessions","note"}`. `note` names the source(s) read and adds "sub-agent cost counts in the month the session was last active". Before 3c, it also says "sessions from Auggie 1.3+ (~/.augment/sessions-v2) aren't read yet". Synchronous: local reads only. |

### 3.4 OpenRouter key storage

`config.py`:
```python
SECRET_EDITABLE = ("OPENROUTER_API_KEY",)
_OR_KEY_RE = re.compile(r"[A-Za-z0-9_.\-]{16,256}")
def _v_or_key(v):        # "" clears; otherwise 16-256 safe chars; no whitespace/CR/LF (blocks header injection)
    if not isinstance(v, str): return False, None
    v = v.strip()
    return (True, v) if v == "" or _OR_KEY_RE.fullmatch(v) else (False, None)
SECRET_VALIDATORS = {"OPENROUTER_API_KEY": _v_or_key}
```
`store._save_json(path, obj, mode=None)`:
```python
if mode is None:
    try: mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError: mode = None
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode)
if mode is not None: os.fchmod(fd, mode)         # exact, not masked by the umask
with os.fdopen(fd, "w", encoding="utf-8") as fh: json.dump(obj, fh, indent=2)
os.replace(tmp, path)
```
- A new file keeps today's `0o666 & ~umask`.
- An existing file keeps its exact mode, so 600 survives every writer: `POST /api/config`, `POST /api/tunnel`, `tunnel._save_cfg`.

`server.py` `POST /api/config`, between `key = body.get("key")` (:774) and the `EDITABLE` check (:775):
```python
if key in config.SECRET_EDITABLE:
    ok, err = _local_caller(self)
    if not ok: return self._json({"error": err}, 403)
    ok, v = config.SECRET_VALIDATORS[key](body.get("value"))
    if not ok: return self._json({"error": "invalid value for %s" % key}, 400)      # never echoes the value
    overrides = _load_json(config.CONFIG_FILE, {})
    if v: overrides[key] = v
    else: overrides.pop(key, None)
    _save_json(config.CONFIG_FILE, overrides, mode=0o600)    # the temp file is 600 before it holds the key
    try: os.chmod(config.CONFIG_FILE, 0o600)
    except OSError: pass
    usage_invalidate("openrouter")
    return self._json({"ok": True, "key": key, "set": bool(v), "file": config.CONFIG_FILE})   # path, never the value
```
- `do_POST` already refuses a mismatched Origin (server.py:665) and read-only visitors (:671-672) before parsing the body.
- `_acct_or_key()` re-reads and re-validates config.json at call time.
- **The key never enters `os.environ`**, so it can't reach the plist (schedule.py:258-266), a pty, or a log.

### 3.5 OpenRouter usage fetch

| Item | Value |
|---|---|
| request | `GET https://openrouter.ai/api/v1/key` (constant). Headers: `Authorization: Bearer <key>`, `Accept: application/json`, `User-Agent: ai-tracker`. |
| opener | `urllib.request.build_opener(_AcctNoRedirect)`: `redirect_request` returns `None`, so a 3xx raises. TLS uses the default verified context. The default `ProxyHandler` stays: the call goes directly or through the system's HTTPS proxy via CONNECT, and TLS stays end to end. `timeout=10` per socket operation. Reads at most 64 KiB. A caught `HTTPError` is `.close()`d. |
| producer `_acct_or_producer()` | Returns `(body, ok, hold)`. 401/403 → `state: "rejected"` with hold `inf`. Any other failure → `n += 1`, hold `30*2**(n-1)` ≤ 900. Success → `n = 0`. Errors are fixed strings. `ssl.SSLCertVerificationError` (directly or as a `URLError.reason`) → "TLS certificate check failed — this Python has no CA bundle". Nothing is logged. |
| parse | `data` must be a dict. Each number must be an int/float that isn't a bool, else "—". Rows: `usage_daily` "Today (UTC)", `usage_weekly` "This week (UTC, from Monday)", `usage_monthly` "This month (UTC)", `usage` "All time". `limit` `None` → "No limit on this key". `limit_remaining` is shown. `limit_reset` is kept if it matches `[a-z_]{1,16}`. `is_free_tier` is bool or `None`. **`label` is never read.** Amounts are USD, `"$%.2f"`. |
| `openrouter_peek()` | `{"key_set": bool, "launcher_configured": openrouter_configured(), "file": config.CONFIG_FILE}`. **It never touches `_Bg` and never opens a socket.** |

`GET /api/usage/openrouter` → `{"key_set","state":"ok|not_set|rejected|error|loading","refreshing","stale","at","rows":[…],"limit_text","remaining_text","limit_reset","free_tier","retry_in","error","launcher_configured"}`.
- `not_set` makes no network call.
- `?peek=1` → the `openrouter_peek()` body.

### 3.6 Route guards

`_same_site(handler)` is `handler.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")`. CLI callers send no `Sec-Fetch-*`, and the SPA sends `same-origin`.

| Route | Guards (in order) | Read-only / tunnel | `_RO_GET_ALLOW` | `fresh` |
|---|---|---|---|---|
| `GET /api/usage/claude` | `_local_caller`, `_same_site` → 403 | 403 | No | `?fresh=1`, floor 60 s, never past a hold |
| `GET /api/usage/openrouter` (`?peek=1`) | same | 403 | No | floor 30 s, never past backoff or rejected |
| `GET /api/usage/auggie` | same | 403 | No | n/a |
| `GET /api/auggie/auth` | same | 403 | No | floor 5 s |
| `POST /api/config` `OPENROUTER_API_KEY` | `_local_caller` inside the branch | 403 (deny-all :671) | n/a | n/a |
| `GET /api/file` | **+ `_tunnel_route_ok()`** (F10) | unchanged (403) | stays out | n/a |
| `GET /api/config` | unchanged | unchanged | stays | never carries the key or a set flag |

These are stricter than `/api/claude/auth`: cross-site browser requests are refused. `/api/claude/auth` keeps its known gap (noted in the PR, out of scope).

### 3.7 Gateway interaction

`or_launcher()`, `openrouter_configured()` and `slots()` (gateway.py:23-75) are unchanged. The key doesn't make OpenRouter "configured": the launcher stays the only way sessions use OpenRouter, and the tracker never exports the key into a pty. The launcher reads the same config.json itself (§7). Its only in-tracker consumer is the `/key` read.

## 4. Auggie login (term_vt.py)

```python
AUGGIE_LOGIN_PROMPT = "auggie auth login"              # a selector only; never typed into anything
AUGGIE_LOGIN_ARGS = ("auth", "login", "--headless")
```
In the `mode == "new"` branch, **before** `argv = [gateway.launcher(gw_eff)]` (:3333):
```python
if isinstance(lp, str) and lp.strip() == AUGGIE_LOGIN_PROMPT:     # lp read first; any gateway
    spec = _agent_spec("auggie")                                   # F14: same PATH answer as Config → Agents
    if not spec or not spec["path"]:
        return handler._json({"error": "auggie not found on the server's PATH"}, 400)
    argv, login = [spec["path"], *AUGGIE_LOGIN_ARGS], "auggie"
else:
    ...existing launcher + LOGIN_ARGV lookup, unchanged...
```
- term_vt imports `_agent_spec` lazily inside the branch, so module import order stays the same.
- The terminal is the existing dedicated pty (:3386-3420) in `~`, hidden like any login pty (:2225, :2388, :4470), and `_login_watch` applies.
- `_login_finished(pt)` calls `store.record_login` only when `pt.login in ("claudeai", "console")`. It then calls `usage_invalidate("claude" if Claude kind else "auggie_auth")` inside the existing try.
- **No transcript cleanup.** `--headless` starts no agent. Auggie writes its own `session.json` and `auth.json`, and may create an empty `sessions-v2/<cwd-slug>/`. The tracker deletes and edits nothing under `~/.augment`. If a future v2 lister (U1) ever lists `sessions-v2/`, an empty slug directory holds no `session.jsonl`, so it lists nothing.
- There is no Auggie last-login record (§5 toast rule).

## 5. UI (ext_cr_dialogs.js)

All new blocks build DOM with `h()` text children only: no `html:` attribute, and no `innerHTML =` except `= ''`.

| Block | Behaviour |
|---|---|
| `sections` | `['Interface','Board','Terminal','Agents','Usage','Notifications','Server','Tunnel','Data files']` |
| `usageBlock()` | `if (crReadOnly()) return null;`. Three cards. Each calls `crCall('/api/usage/<x>')` and re-polls every 3 s while `refreshing` (at most 60 tries), stopping when `wrap.isConnected === false`. A 403 shows "Usage is shown on this machine only". Each card has a **Refresh** button (`?fresh=1`). The header shows `account` or `label`, then "as of <toLocaleString(at)>", plus "(last known)" when `stale`. |
| Claude card | Each `limits[]` row shows `label`, a bar at `percent`% with class `is-<severity>`, "N% used · resets <local time>", and an "active" tag. A **credits block only when `credits` is non-null**: `text`, a `utilization` bar, and `note`. Otherwise `message` or `error`. |
| OpenRouter card | `rows[]`, `limit_text`, `remaining_text`, `free_tier`. `not_set` → "No OpenRouter key saved — add it in Config → Server". `rejected` → "OpenRouter rejected the saved key — replace it in Config → Server". |
| Auggie card | `label` (bold), `window`, `cost_text`, `sessions`, `note`. |
| `auggieLoginBlock()` (Server, after `loginEl`) | Status from `GET /api/auggie/auth`, polling while `refreshing`. Button: "Log in" or "Switch account". It calls `ExtLaunch.openAt('~','new','auggie auth login', inline ? {gateway:'anthropic', tab:false} : {gateway:'anthropic'})`, with the non-inline fallback copied from claudeLoginBlock. Then `open('claude-login', {tty, renderer, title:'Auggie login', onDone})`. Help: "Opens `auggie auth login --headless` in a terminal over this page and signs in every Auggie session on this machine. Switching asks you to confirm in the terminal (y), then opens your browser." `onDone(ended)` re-reads with `?fresh=1`. **It toasts only when `ended`** (the pty exited by itself), with the text `'Auggie: ' + label`. A manual close re-reads silently. Any `focus` listener removes itself, like :1683-1688. |
| `openrouterKeyBlock()` (Server) | Reads **`/api/usage/openrouter?peek=1`** and shows "API key: set" or "API key: not set". Buttons: **Replace** (or **Set**) reveals `<input type="password" autocomplete="new-password" spellcheck="false">` (no `<form>`; `name`/`id` don't contain "password") with **Save**/**Cancel**, and **Clear** (with confirm). Save → `crCall('/api/config','POST',{key:'OPENROUTER_API_KEY', value})`. On success **and** on failure, `input.value = ''`. On a 400 the input stays and the server's fixed error is shown. `value` is never set from a response. Sub-text from the peek body: "Saved to <file> (owner-only), the config of the checkout this dashboard runs from. Never shown again. Your OpenRouter launcher reads it from there." |
| `renderClaudeLogin` | The title is `payload.title \|\| 'Claude Code login'`. Nothing else changes. |

## 6. Conventions text (verbatim drafts; D2 is resolved before step 1 lands, so no brackets reach the rule)

### 6.1 config.py, appended to the `AUTH` comment (config.py:120-130)
```
# Narrow exception (user-requested 2026-11-18: "enter key in the config ... never display or show the
# existing key"): OPENROUTER_API_KEY -- and only it, joining the TUNNEL_PASS precedent -- may be typed into
# Config and stored in config.json. It is in SECRET_EDITABLE, never in EDITABLE, so GET /api/config
# (reachable read-only through a tunnel) never carries it. Only POST /api/config's secret branch writes
# it, from a local caller; that write creates config.json's temp file at 0600, and store._save_json keeps
# that exact mode on every later write. No route returns it: the only status is "set"/"not set" from the
# local-only /api/usage/openrouter?peek=1, and /api/file refuses rebinding requests. It never enters
# os.environ, the launchd plist or a log. TRACKER_AUTH stays env-only.
```

### 6.2 Rule 6 base sentence and the existing `/api/claude/auth` exception
- Base: "Read-only w.r.t. session logs. **No outbound network, except as the exceptions below allow; each exception's 'no other … call' covers its own module.**"
- `/api/claude/auth` exception: "The dashboard opens no socket itself" → "The dashboard opens no socket **for this run**".

### 6.3 Exception: Claude `/usage` run
> *Exception (Claude plan usage, user-requested 2026-11-18: "Yes, run it."): `aitracker/accounts.py` — and only it, never synchronously inside a request handler (its own background thread may) — may run `<claude> -p /usage --output-format stream-json --verbose --no-session-persistence`<D2: ` --settings {"disableAllHooks":true} --strict-mcp-config`>. `<claude>` is the `claude` binary that `agent_cli` resolves on the server's own PATH, and is never the OpenRouter launcher. It runs through `update._run` (no shell, stdin closed, own session and process group, cwd `~`, a 150 s timeout that kills the group). A run starts only when a local, same-site caller reads `GET /api/usage/claude` (Config → Usage) and the last successful result is older than 300 s (60 s on a Refresh), or 60 s after a failed run. There is never more than one at a time, and never one on a schedule or a page load. Cross-site browser requests are refused. It reads only the stream's top-level `usage_report` and its lines' `type`/`is_error` fields, and forwards no CLI text. `--no-session-persistence` means it writes no transcript.<no-D2: The user's hooks and MCP servers load as in any `claude -p`.><D2: Hooks are disabled and only `--mcp-config` servers (none) start.> It bills no model tokens (observed: `num_turns` 0, cost 0). The CLI contacts Anthropic's usage endpoint with its own credentials; the dashboard opens no socket for it.*

### 6.4 Exception: OpenRouter socket and stored key
> *Exception (OpenRouter key usage, user-requested 2026-11-18: "enter key in the config", and the dashboard may call openrouter.ai): `aitracker/accounts.py` — and only it, never synchronously inside a request handler — may open one kind of outbound connection: `GET https://openrouter.ai/api/v1/key`. The URL is constant. The connection goes directly or through the system's configured HTTPS proxy (CONNECT; TLS verified end to end), refuses redirects so the header can't follow one, uses a 10 s socket timeout and reads at most 64 KiB. It sends `Authorization: Bearer <OPENROUTER_API_KEY from config.json>` and a generic `User-Agent: ai-tracker`, and nothing else about the user or machine. It runs only when a local, same-site caller reads `GET /api/usage/openrouter` (the Usage tab), a key is saved, and the last successful result is older than 300 s (30 s on a Refresh). Failures back off from 30 s, doubling to 15 min. A 401/403 is not retried until the key is replaced. A Refresh never overrides either. Config → Server reads `?peek=1`, which never connects. The key is typed only into Config → Server and written only by `POST /api/config`'s `SECRET_EDITABLE` branch from a local caller (never read-only, tunnelled or proxied). `config.json` is 0600 from that write onwards. No route returns the key or any part of it (the response's `label` is never read). It never enters `os.environ`, the launchd plist, a terminal's environment or a log. No other outbound network call is allowed from this module.*

### 6.5 Exception: Auggie auth commands
> *Exception (Auggie login, user-requested 2026-11-18: "terminal login yes"): `GET /api/auggie/auth` (local, same-site callers only) runs `<auggie> auth status` in the background, where `<auggie>` is the binary `agent_cli` resolves. It goes through `update._run`, cwd `~`, with a 20 s timeout, cached 60 s, with at most one run per 5 s on refresh. It reads only the exit code and whether a stdout line is exactly `Logged in.` or `Not logged in.`. Config → Server's Auggie "Log in / Switch account" (`POST /api/term/pty`, `mode=new`, prompt exactly `auggie auth login`, surrounding whitespace ignored, any gateway) runs `<auggie>` with the fixed constant `term_vt.AUGGIE_LOGIN_ARGS` = `auth login --headless`. The request selects it and never supplies argv text. It runs in a dedicated terminal in `~`. `--headless` exits after authenticating instead of starting the agent, so no Auggie chat session is created. Auggie writes its own `~/.augment/session.json` and `auth.json`, and may create an empty `~/.augment/sessions-v2/<cwd>/`. The tracker deletes and edits nothing under `~/.augment`, records no Auggie login outcome, and may SIGKILL that terminal's own process group at `LOGIN_WATCH_MAX`. The CLI may contact Augment with its own credentials; the dashboard opens no socket for it.*

### 6.6 README.md:68, CLAUDE.md, tests/test_links_liveness.py:23
Append: "…except, once you save an OpenRouter key, one read of openrouter.ai's key-usage endpoint when you open Config → Usage."

## 7. Launcher snippet (the user edits their `OPENROUTER_LAUNCHER` script)

The key is saved by the **8790 service**, which runs from the primary checkout (F13). A worktree dev server writes its own `aitracker/config.json`, which this snippet never reads.
```bash
AITRACKER_CFG="/Users/pritammondal/Documents/Projects/AIengg/ai-tracker/aitracker/config.json"
OPENROUTER_API_KEY="$(python3 -I -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("OPENROUTER_API_KEY") or "")
except Exception: print("")' "$AITRACKER_CFG")"
# jq equivalent: OPENROUTER_API_KEY="$(jq -r '.OPENROUTER_API_KEY // empty' "$AITRACKER_CFG" 2>/dev/null)"
if [ -z "$OPENROUTER_API_KEY" ]; then
  echo "No OpenRouter key in $AITRACKER_CFG — save it in ai-tracker Config → Server (port 8790)" >&2; exit 1
fi
export ANTHROPIC_BASE_URL="https://openrouter.ai/api" ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY" ANTHROPIC_API_KEY=""
unset OPENROUTER_API_KEY
```
- Don't use `set -x` around these lines.
- Replace the launcher's previous key source, so there is one key for sessions and the panel. Don't add a fallback.

## 8. Tests (each non-trivial branch gets one assertion; `unset TRACKER_AUTH; make check` → `selfcheck ok`)

Every red proof is a scoped Edit revert, never `git stash`.

| New file (copied from) | Assertions | Proved red by |
|---|---|---|
| `tests/test_accounts_claude_usage.py` (FakePopen of `test_claude_auth_status.py`; patches `accounts._run`, `_agent_spec`) | exact argv list, including the raw D2 JSON element if accepted; `cwd=~`, timeout 150; **A** (the probed Max shape verbatim) → 3 rows with probe labels and percents, `credits None`; **A2** `is_enabled:"true"`, **A3** `1` → `credits None`; D (`extra_usage` absent) → None; E (no `usage_report`) → `no_report`; garbage lines skipped; `usage_report` a list → error; `is_error` → error; rc≠0 → fixed error, stderr sentinel absent; unknown kind + `scope.surface`; bad percent, severity or resets_at sanitized; `email` sentinel inside `usage_report` absent; launcher == claude, or no spec → unavailable; `gateway._auth_run` patched to raise → never called. **Step 3b, from probe 0(c):** **B** (credits on) → `text` exact; **C** (`monthly_limit null` + `team`) → "no monthly limit of its own" + note, and `"nlimited"` not in the JSON | Delete the `is_enabled` clause (A red); `is not True` → `not …` (A3 red); spread `usage_report` (sentinel red); drop the null branch (C red) |
| `tests/test_accounts_bg.py` | `get()` returns at once with `refreshing`; single-flight; ttl and floor (patched monotonic); always-failing producer: `get` at t=0 and t=4 → 1 call, t=61 → 2; `fresh` after a failure inside the hold → no call; failure keeps the good body with `stale`; `invalidate` mid-run drops the result; `abs(get()["at"] - time.time()) < 5` | Remove "failure stamps `_t`" (t=4 red); let `fresh` bypass the hold (red); remove the `gen` check (red) |
| `tests/test_accounts_openrouter.py` (fake opener via `_acct_open`) | URL exact; Bearer sentinel; `User-Agent == "ai-tracker"`; docs-shaped parse; bad numbers → "—"; `limit null`; `data` not a dict; `label` sentinel absent; 401 then `fresh` at +1000 s → 1 call, after `usage_invalidate` → 2; timeout at n=3 then `fresh` at +31 s → no call; success resets `n`; the real opener holds `_AcctNoRedirect` and a 302 raises; >64 KiB → error; `HTTPError.close` called; `SSLCertVerificationError` → the exact TLS string; key sentinel absent from every body and error; `not_set` and `peek` make no opener call (`test_peek_never_opens`) | Remove the no-redirect handler; drop the 401 hold; make peek call `get()` |
| `tests/test_openrouter_key_route.py` (`_ServerCase` + `_RemotePeer` of `test_claude_auth_route.py`) | local POST → 200 `{"ok","key","set","file"}` without the sentinel; file holds the key at mode 0o600; with `os.umask(0o022)` pinned (cleanup restores it), POST `LIVE_WINDOW` → still 0o600; GET `/api/config` lacks the sentinel and the key name; leak loop over `/api/config`, `/api/tunnel`, `/api/usage/*` (incl. `peek`), `/api/auggie/auth`, `/api/claude/auth`, `/api/agents` → sentinel absent; **`/api/file?path=<CONFIG_FILE>` with `Host: rebind.example:<port>` → 403, sentinel absent; with `Host: localhost:<port>` → 200**; remote, `X-Forwarded-For`, cross-origin, read-only → 403 and the file unchanged; bad values → 400 without echo; `""` clears; plist bytes and `os.environ` lack the sentinel; key not in `EDITABLE` | Add the key to `EDITABLE`; drop `_local_caller`; drop `/api/file`'s guard; revert `_save_json` (each red) |
| `tests/test_save_json_mode.py` | umask 0o002: new file → 0o664 (unchanged from today); existing 0o600 → stays 0o600; `mode=0o600` on an existing 0o644 file → the temp is 0o600 before the swap (patch `os.replace` to stat `src`) | Revert to the old `_save_json` |
| `tests/test_usage_routes.py` | each of the 4 GETs: local 200; remote, proxied or cross-origin → 403 and the stub never called; `Sec-Fetch-Site: cross-site` → 403 with no call; `same-origin` → 200; read-only → 403; none in `_RO_GET_ALLOW`; `fresh` passes through | Remove `_same_site` from one route |
| `tests/test_auggie_auth.py` (FakePopen) | argv via the spec path; `"Update available\nLogged in.\n"` rc0 → logged in; `"Logged in as x"` → error; rc1 `Not logged in.` → out; timeout or missing spec → error/unavailable; keys whitelisted | First-line parsing (banner red) |
| `tests/test_auggie_month_cost.py` (legacy fixtures from the observed shape) | this month summed; last month excluded within one file; old-mtime file never opened; non-numeric → `unpriced`; sub-agent counted via `_sub_agent_usd` when `modified` ≥ since; `test_since_change_recomputes` (Nov 1 vs Oct 1 → different sums); `test_note_names_source` (empty dir → note names `~/.augment/sessions` and the v2-not-read sentence); route body label verbatim. **Step 3c:** a v2 fixture copied from the probe 0(f) file shape | Drop the mtime skip; key the cache without `since` |
| `tests/test_auggie_login_pty.py` (`_open` harness of `test_pending_pty_prompt.py`) | `test_argv_is_auggie_on_every_gateway` (anthropic, openrouter without a launcher, None) → argv `[spec path,"auth","login","--headless"]`, `"claude"` absent, `pt.login == "auggie"`, never injected; missing auggie → 400 with no spawn; `_login_finished` on auggie → no `last_login.json` write and `usage_invalidate("auggie_auth")` called; existing Claude tests untouched | Drop `--headless`; remove the kind gate |
| `tests/test_usage_ui.py` (node runner of `test_claude_login_settings_ui.py` + static checks of `test_agents_ui.py`) | `'Usage'` listed and dispatched; A → 3 rows, no `.cr-usage-credits`; credits fixture → block with the server text; C → never "Unlimited"; `refreshing` polls then stops; 403 text; the Server tab GETs `/api/usage/openrouter?peek=1` and never the bare path; key input `type=password`, `autocomplete=new-password`, empty on open, `''` after success and after a 400 (error shown); POST body exact; Auggie toast only when the pty ended (text `'Auggie: ' + label`), none on manual close; focus listener self-removes; no `html:` / `innerHTML =` (except `''`) in the three new functions; a limit label `"<img src=x onerror=1>"` renders as literal text with no `img`; every field read is emitted by accounts.py; `node --check` | Hard-code a label; render credits unconditionally; read the bare path from the Server tab |
| `tests/test_page_bundle.py::test_bundle_header_and_qualifiers` (**one** static test) | `bundle.HEADER` imports `ssl`, `urllib.error`, `urllib.request`; `server.py` source has no `(?<![\w.])accounts\.` | Write `accounts.claude_usage` in server.py, or drop a HEADER import |

## 9. Sequencing (one commit each; gate green after each)

| Step | Lands | Waits on |
|---|---|---|
| 0 | **Probes.** An agent runs (a), (b) and (d) read-only; the user runs (c), (e) and (f). **(a)** `touch /tmp/m`, one `/usage` run, then `find ~/.claude/sessions ~/.claude/projects -newer /tmp/m` and `wc -l ~/.claude/history.jsonl` before and after (names only). **(b)** The same with the D2 flags: `usage_report` present? the `system/init` line's `mcp_servers` (expect `[]`)? count of `hook_*` lines (expect 0)? duration? **(c) Stop-and-ask gate:** the user logs into the usage-credits account and reruns handover probe 1. Record `extra_usage` (types and amounts only) and whether `usage_report` appears at all. If it doesn't, the user's requirement "usage and also usage credits, whichever is true" can't be met that way, and the user decides before step 3b. **(d)** `touch /tmp/m; (cd ~ && auggie auth status); find ~/.augment -newer /tmp/m` (names only). **(e)** The user runs handover probe 3 with their key (field names and types). **(f)** The user runs one short `auggie -p "say hi"` in a scratch dir. Then `find ~/.augment -newer <marker> -type f`, and record the `session.jsonl` record types, the cost field path and its type, and the timestamp field path and its type, with no content. | — |
| 1 | `_save_json(mode=)` + `test_save_json_mode.py`; conventions.md and the config.py texts (D2 resolved) | (b) for D2's wording |
| 2 | `/api/file` guard; `SECRET_EDITABLE`; the POST branch; `test_openrouter_key_route.py` without the `/api/usage/*` GETs | — |
| 3a | `accounts.py` (`_Bg`, Claude limits, OpenRouter + peek, Auggie auth); `claude_auth_cached`; `month_cost` (legacy); bundle ORDER + HEADER + the static test; unit tests | (a), (b), (d), (e) |
| 3b | Claude credits branch + fixtures B/C | **(c)** |
| 3c | `month_cost` v2 reader + v2 fixture; the note drops the "not read yet" sentence | **(f)** |
| 4 | the four GET routes + `_same_site` + `test_usage_routes.py`; extend the leak loop | 3a |
| 5 | term_vt Auggie branch, `_login_finished` gate + invalidation, `test_auggie_login_pty.py` | — (only `usage_invalidate` from 3a) |
| 6 | UI + CSS + `test_usage_ui.py` | 4, 5 |
| 7 | README, CLAUDE.md and test docstring lines; hand the §7 snippet to the user; restart (`make serve`); hand-check on both Claude accounts. The new static test replaces the manual bundle smoke test. | all |

Steps 1, 2 and 5 wait on no account probe, and steps 3b/3c don't block the rest. Before any of this, hand the user `chmod 600 /Users/pritammondal/Documents/Projects/AIengg/ai-tracker/aitracker/config.json` (F11).

## 10. Risky spots and fallbacks

| Risk | Fallback |
|---|---|
| The usage-credits account emits no `usage_report` (usage-based billing). | Probe 0(c) is a stop-and-ask gate. The honest default is `no_report`. A plain-text fallback (lines before "What's contributing" matching `^(Current [^:]{1,60}\|Usage credits[^:]{0,40}): .{1,120}$`) is only an option the user may choose then. |
| `usage_report` is experimental. | Every field is optional in the parser. An unrecognised shape gives `error: "unrecognised usage report"`. Fixture A pins today's shape. |
| A 70 s run with the user's hooks and MCP servers. | It runs only from the Usage tab, after TTL or a hold, and only for same-site callers. D2 removes the hooks and MCP servers if 0(b) proves it. |
| A `-p` run writes `~/.claude/sessions/<pid>.json`, so the Agents panel briefly lists it. | No hiding mechanism is planned (`update._run` exposes no pid). If 0(a) shows the file, record it as a known cosmetic gap in the PR and decide separately. |
| An outside `/login` leaves the panel showing the old account. | `account` label + "as of" + TTL 5 min + Refresh; Config logins invalidate at once. |
| **Lost update:** `tunnel.py`'s reader thread (tunnel.py:148-152) rewrites config.json from a dict read earlier, which can undo a key save. | **Known gap, same as base; documented in the PR.** The real fix (every writer through `store._update_json`, store.py:373) is out of scope. |
| The v2 Auggie session shape is unknown (F12). | Probe 0(f) and step 3c. Until then the card says plainly which source it reads. |
| The key leaks by redirect, exception text, `label`, rebinding `/api/file`, or a 644 config.json. | `_AcctNoRedirect`, fixed strings, `label` never read, F10 guard, `_save_json(mode=)`, plus the sentinel tests. |
| The service PATH lacks `claude` or `auggie` (F14). | Same resolution as Config → Agents, and the same message. |

## 11. Decisions for the user

| # | Decision | Plan default | Alternative |
|---|---|---|---|
| D1 | Key in a separate `SECRET_EDITABLE` allowlist through `POST /api/config` (not `EDITABLE`, F1). Registration rows in **Config → Server**. | as stated | the key row in the Usage tab |
| D2 | Add `--settings {"disableAllHooks":true} --strict-mcp-config` to the `/usage` command, only if probe 0(b) shows `usage_report`, `mcp_servers: []` and 0 hook lines. | add if the probe passes | the exact approved command |
| D3 | Auggie window: calendar month to date, UTC | as stated | last 30 days |
| U1 | **The Auggie provider's session listing also misses `sessions-v2`.** `list_auggie` globs only `config.AUGGIE_SESSIONS/*.json` (auggie.py:319), and so do `exists`, `parse` and search. Every Auggie 1.3 session (`sessions-v2/<slug>/session.jsonl`) will be invisible to the dashboard. None exist on this machine yet (F12), so nothing is hidden today. | **A separate `/tracker-gap` follow-up**, not part of this plan: list + detail from one v2 parser, after probe 0(f). | fold it into this branch (one PR per repo) |

## APIs that don't exist (stated, not assumed)

- Auggie 1.3 has no account identity, plan or balance source.
- There is no programmatic Claude usage-credits **balance** field.
- OpenRouter **account** credits need a management key.
- There is no `claude usage` subcommand.
- `gateway.claude_auth_cached()` doesn't exist today; this plan adds it (§2).
- No real Auggie 1.3 (`sessions-v2`) session file exists on this machine yet (F12).

## Revision log (revision 2)

| Finding | Plan section changed |
|---|---|
| S-B1 `/api/file` rebinding | F10; §2 server row; §3.6 row; §6.1; §8 leak loop; §9 step 2 |
| S-M1 `_Bg` re-runs and `fresh` bypass | §1 cache row; §3.1 rewritten (producer `(body, ok, hold)`); §3.5 producer; §8 `test_accounts_bg`/openrouter cases |
| S-M2 = U-M2 bundle | §1 imports row; §2 accounts/server/bundle rows; `usage_invalidate` rename; §8 **one** static test |
| S-M3 cross-site trigger | §3.6 `_same_site`; §6.3-6.5 "same-site"; §8 `test_usage_routes` |
| U-M1 sessions-v2 | F6/F12 (no v2 file on disk); §3.3 legacy now, v2 in 3c; §8; §9 0(f) and 3c; §11 U1 |
| U-M3 = S-m4 peek | §3.5 `openrouter_peek`; §5 key block; §6.4; §8 `test_peek_never_opens` |
| U-M4 credits (overstated) | §3.2 credits row gated on 0(c), cents kept as documented; §8 B/C in 3b; §9 3b |
| S-m1 `_save_json` | F2 cites fixed; §3.4 `mode=` + `fchmod`; §8 `test_save_json_mode.py` |
| S-m2 `claude_auth_cached` | §2 gateway row; §3.2; §8 `_auth_run` never called |
| S-m3 `_OWN_PIDS` dropped | §10 row 4 |
| S-m5 rule-6 wording | §6.2-6.4 (base sentence, scoped claude-auth text, refresh-never-overrides, proxy, socket timeout, raw D2 JSON, no brackets at landing) |
| S-m6 = U-m8 password manager | §5 key block |
| S-m7 tunnel race | §10 known PR gap, no change |
| S-m8 drop `sync` | §1, §3.1, §3.3 |
| S-m9 probe gates | §9 0(b) MCP/hooks proof, 0(c) stop-and-ask |
| S-m10 fetch hygiene | §3.5 (HTTPError close, TLS string, socket timeout); §8 |
| S-m11 config.json 644 | F11; §9 user action |
| U-m1 separate Auggie constants | §2 term_vt row; §4; §6.5; §8 (no pinned-test edit) |
| U-m2 reauth confirm and toast | F3; §5 auggieLoginBlock; §8 |
| U-m3 status parse | F4; §3.3; §8 banner case |
| U-m4 probe 0(d) | §9 0(d) |
| U-m5 fixture-A mutation | §8 A2/A3 and mutations |
| U-m6 umask in the 0600 test | §8 key-route test |
| U-m7 month_cost cache and sub-agent | §3.3; §8 `test_since_change_recomputes` |
| U-m9 clocks and HTML injection | §3.1 `at`; §5 header line; §8 |
| Missed: per-checkout config.json | F13; §3.4 response `file`; §3.5 peek `file`; §5 sub-text; §7 |
| Not examined: PATH under launchd | F14; §3.2, §3.3, §4 via `_agent_spec` |

## Self re-review (assume this revision is wrong)

| # | Attack | Verdict / still open |
|---|---|---|
| R1 | "The ruling says read `sessions-v2`; the plan reads legacy." | There is no v2 file on disk (F12, checked today), so rule 7 forbids writing a v2 parser now. Legacy is read now; v2 lands in 3c after probe 0(f). **Open: this contradicts the coordinator's premise that sessions-v2 "holds today's file". The main thread should re-check what it saw.** |
| R2 | `_agent_spec` lives in agent_cli, which imports registry, providers and pending. Can importing it from accounts and term_vt cause cycles? | accounts sits after agent_cli in ORDER, and server already imports agent_cli. term_vt imports it lazily inside the branch. **Open: confirm in 3a that `from .agent_cli import _agent_spec` at the top of accounts doesn't create an import cycle via `agent_cli → registry → providers.claude`** (accounts imports `providers.auggie` itself, not the other way round, so a cycle isn't expected). |
| R3 | `_agent_spec` calls `agent_specs()`, which calls `shutil.which` for every provider on each call. Is that cheap? | It's cheap: microseconds, called at most once per run. OK. |
| R4 | `_Bg`: `hold = inf` plus `age >= hold` is never true, so a 401 is held forever until invalidated. Does a server restart clear it? | Yes, the cache is in-process, so a restart resets it and the key is tried once more. Acceptable. |
| R5 | The `file` path in the POST/peek response reveals the checkout path. | The response is local-only, and `/api/config`'s Data files tab shows paths already. OK. |
| R6 | `_same_site` defaults to same-origin when the header is absent. An old browser without `Sec-Fetch-*` stays exposed. | Accepted. This is the review's own direction; the CLI must keep working. |
| R7 | The `_save_json` `mode=0o600` creates the temp at 600, but `os.replace` then gives the target the temp's inode. Is that correct for existing readers? | Yes: there's only one owner, and the service runs as the user. |
| R8 | Fixture B/C are deferred, so could the credits UI ship untested? | The UI test's "credits fixture" also waits for 3b. **Open: the step 6 UI test must use a 3b fixture. If 3b is still blocked at step 6, the credits-render UI assertion waits with it, and the PR states that.** |
| R9 | The Auggie login runs with any gateway, but the client still sends `gateway:'anthropic'`. Is that harmless? | Yes: the branch runs before `gateway.launcher`. |
| R10 | `month_cost` never looks at the augment_ext (VS Code) provider. | It is out of scope: the user asked for Auggie, and the card's note says "Auggie CLI sessions". |

## Addendum (2026-11-19): config.json chmod on Update and restart

**Ask (verbatim):** "it should also run when someone runs `Update and Restart`" — "it" = `store.secure_config_file()` (`aitracker/store.py:18`), called at the top of `server.run()` (`aitracker/server.py:1210`).

### How "Update and restart" restarts (evidence)
- Route: `POST /api/update/apply` (`server.py:736`) → `update_apply()` (`update.py:263`) → `_apply_locked()` does the only write, `git merge --ff-only <sha>` (`update.py:318`), returns 202. After the 202 is flushed, the handler calls `start_restart(port)` (`server.py:770-772`), a 0.5 s `threading.Timer` → `restart_in_place()` (`update.py:382-387`).
- `restart_in_place()` (`update.py:347-379`) **re-execs in place**: `os.execv(sys.executable, sys.orig_argv or [python, "-m", "aitracker", *argv[1:]])` (`update.py:356, 372`). Same PID, same argv. It does not exit for launchd to respawn, and it does not reload in-process. The exec runs a fresh interpreter, so it runs the newly merged code from `aitracker/__main__.py` → `cli.main()`.
- **(a) launchd service:** the plist argv is `[python, "-m", "aitracker", "--service"]` (`schedule.py:271`). The re-exec keeps that argv and PID, so launchd sees no exit and KeepAlive never fires. `cli.main()` reaches `run(..., service=True)` (`cli.py:89-90`) → `secure_config_file()` (`server.py:1210`).
- **(b) foreground:** `python -m aitracker` re-execs to `cli.py:90` → `run()`. A foreground `make serve` (`Makefile:10`, `--serve`, worktree or non-macOS) re-execs with `--serve`. `svc_install` again returns 2 ("refused", `schedule.py:302-308`) → falls through (`cli.py:74`) → `run()`. Edge case: if the service install could succeed on the re-exec, the process exits 0 (`cli.py:66-69`). The service it installed then starts through `--service` → `run()`. Either way, whichever process ends up serving has passed through `secure_config_file()`.
- Bundle/package kinds (`update.py:91-99`) cannot update in-app, so they are out of scope.
- **Exec failure** (`update.py:373-379`): the process stays up on the code it already had, so there is no restart to hook.

### Does the merge touch config.json? Is there a 0644 window?
- `aitracker/config.json` is gitignored (`.gitignore:16`, confirmed with `git check-ignore -v`). It is untracked, so `merge --ff-only` neither writes it nor changes its mode. One exception: git treats ignored files as expendable, so if an upstream commit ever *tracked* `aitracker/config.json`, the ff-merge would silently overwrite it with git's 0644. That would be a separate, much larger bug (secrets in git), and the re-exec's `run()` would still re-chmod it to 0600.
- No new window. Between the merge and the exec (~0.5 s plus the pre-exec steps), the file keeps whatever mode it had. If the running process is already post-5d34ac5, its own startup already made it 0600, and `_save_json` keeps that mode (`store.py:27-38`).
- **Key point:** the update that *first* brings in `secure_config_file` is applied by the *old* process's `update.py`, which has no chmod. Any call added to `update.py` would not run for that transition, and for later updates it would duplicate what the re-exec's `run()` already does. Only the new process's `run()` can cover the first upgrade, and it already does.

### Verdict: already covered, so no production code change
Every successful "Update and restart" path re-execs into `cli.main()` → `server.run()` → `secure_config_file()`. The change is **tests only**, pinning the link the existing tests don't cover: from the re-exec argv to the chmod. (`test_update_restart.py` already pins the argv, and `test_save_json_mode.py:78` pins `run()` → chmod. Nothing pins `cli.main()` with the re-exec argv → `run()` → chmod.)

### Exact change: `tests/test_save_json_mode.py`, class `SecureConfigFileTests` (`:60`)
Add two tests in the existing style: `self.p` is a temp `config.json` patched into `config.CONFIG_FILE` by `setUp`, `server.bind` is patched with `side_effect=RuntimeError("stop")`, and `server.signal.signal` is patched. Each test asserts the real file mode, not a mock call.
1. `test_update_reexec_as_service_secures_config`: `store._save_json(self.p, {"TUNNEL_PASS": "x"})`, `os.chmod(self.p, 0o644)`, then `mock.patch.object(sys, "argv", ["aitracker", "--service"])` and `mock.patch.dict(os.environ, {"PORT": "8791", "TRACKER_NO_BROWSER": "1", "TRACKER_SCHEDULER_AUTOINSTALL": "0"})` (the env `restart_in_place` sets, `update.py:354-355`). Call `cli.main()` inside `assertRaises(RuntimeError)` and assert `_mode(self.p) == 0o600`.
2. `test_update_reexec_foreground_serve_secures_config`: same setup, with argv `["aitracker", "--serve"]`, `mock.patch.object(cli, "svc_baked", return_value=None)`, `mock.patch.object(cli, "svc_install", return_value=2)` (the "refused" fallback, `schedule.py:303-308`) and `mock.patch.object(cli, "_port_busy", return_value=False)`. Assert 0600. This also pins that `--serve` falls through to `run()` and is not swallowed.
- Also patch `server.publish_endpoint`/`start_worker` only if the order changes. Today `bind` raises at `server.py:1213`, before either of them runs, so neither needs patching. No other file changes. Stdlib `unittest`/`mock` only.
- **Proof of red:** comment out `secure_config_file()` at `server.py:1210`, and both new tests fail with mode `0o644`. Separately, make `cli.main()` return before `run()` in the `--serve` fallback, and test 2 fails. Restore both and run `make check` (`unset TRACKER_AUTH;` first, per memory), which must be green.

### Risky spot and fallback
- **Risk:** `cli.main()` imports, and `run()` reached through it, have side effects beyond `bind`: `AITRACKER_SERVICE_PID` is set in `os.environ` (`server.py:1203-1204`), and `config.BIND_*`/`config.SERVICE` are mutated (`server.py:1200-1202`). Contain the env change with `mock.patch.dict(os.environ)`. Restore `config.BIND_HOST`/`BIND_PORT`/`SERVICE` in `addCleanup`, the same way `test_server_run_calls_it_before_binding` leaves them. If cross-test leakage shows up, also patch those three with `mock.patch.object`.
- **Fallback:** if `cli.main()` proves too entangled to drive under test, drop to a narrower pin. Assert `restart_in_place`'s fallback argv is `[sys.executable, "-m", "aitracker", ...]` (it already is, `test_update_restart.py:143`), then call `cli.main()` with only `server.run` patched to record that it was called. Together with the existing `test_server_run_calls_it_before_binding` (`:78`), that chain still pins re-exec → `run()` → chmod.

### Conventions
**No conventions change is needed.** The rule-6 Update exception text (`.claude/rules/conventions.md`) is untouched: no new git command, no new write, no new action. `secure_config_file` is a chmod of app-owned state that already exists and already runs at startup.
