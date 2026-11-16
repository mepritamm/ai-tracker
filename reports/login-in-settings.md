> SUPERSEDED 2026-11-16 — written for a misreading of the request (dashboard TRACKER_AUTH login). The user meant Claude Code's own /login. See reports/claude-login-button.md. Nothing in this file was implemented.
# Login in Settings — plan (v1, plan author: opus)

Status: PLAN ONLY. No product code, no tests written. Grounded against `personal/main` @ adeb6fa
(read from the `pending-work-worker` worktree, which is at the identical SHA — the
`login-in-settings` worktree could not be created from the planning subagent: the harness refuses
`git worktree add` outside the agent's own worktree and refuses `EnterWorktree` creation from a
subagent. **The orchestrator must create it** — `git fetch personal` then
`git worktree add .claude/worktrees/login-in-settings -b login-in-settings personal/main` — and move
this file to `reports/login-in-settings.md` there.)

---

## 1. Contract (verbatim)

Question put to the user:
> "Local-only routes and the tunnel routes now refuse a foreign Host or a cross-site Origin. Should
> that check cover every route of the dashboard, including the read-only ones like the session
> list?" — options "Leave as is" and "Cover every route (… a hostname alias for the dashboard stops
> working unless a login is configured)"

The user's answer, instead of picking an option:
> configure the login as well into the config settings itself

Standing instruction from the same user:
> "everything happens with a button click instead of make command, the only command the user runs
> is first time with a make serve and then rest is managed by the app itself"

| # | Clause | Verdict |
|---|---|---|
| C1 | The dashboard login can be configured from the Settings (config) dialog itself | not discharged |
| C2 | "as well" — the every-route Host/Origin check question is still open and is answered alongside C1 | not discharged |
| C3 | Turning on / changing / removing the login is a button click, no `make`/env edit, no restart | not discharged |
| C4 | Nothing beyond the first `make serve` is needed — including recovery from a forgotten password | not discharged (see §5 Q3: recovery is "delete one file", not a command) |
| C5 (implied by brief) | Credential never readable in plaintext by a visitor, `GET /api/config`, page source, logs or the bundle | not discharged |

## 2. Interpretation

**Planned reading (A):** the dashboard's own login — today env-only `TRACKER_AUTH`
(`aitracker/config.py:113-122`) — becomes settable, changeable and removable from
**Settings → Server → Login**, stored as a salted hash in an owner-only file, applied live. Because
a login is then one click away, the original question is answered "Cover every route": with no
login set, a non-loopback Host is refused on *every* route; a user who wants a hostname alias / LAN
/ Tailscale access turns the login on in Settings.

Other plausible readings (decision #1):
- **(B)** "Put the Host-check choice itself in Settings" — a toggle "Host check: local-only routes /
  every route", no login change. Cheap, but does not do what "configure the login" says.
- **(C)** Literal: make `TRACKER_AUTH` an `EDITABLE` key in `config.json`. Rejected: plaintext
  password on disk next to a tunnel, and it inverts a deliberate, test-pinned invariant
  (`tests/test_cr_routes.py:269-284`, `tests/test_selfcheck.py:893-896`).
- **(D)** = (A) without the Host widening — the user may have meant "do the login *instead of*
  deciding". Then C2 is discharged as "leave as is" and step 7 below is dropped.

## 3. What exists (grounded)

- `config.AUTH = os.environ.get("TRACKER_AUTH", "")` — `config.py:122`; the comment at `:113-121`
  says env-only forever; `:208-215` repeats it for `EDITABLE`.
- `config.py` imports only `os`, `re` (`:1-2`), never touches the filesystem (`:150-175` comment);
  `tests/test_term_vt.py` execs its source bare. ⇒ the new logic cannot live in config.py.
- Readers of `config.AUTH` **as a "login is on" flag**: `server._local_caller` `server.py:238`;
  `GET /api/config` `AUTH_SET` `server.py:498`; `publish_endpoint` `server.py:989-997`;
  `term_gate.allowed` `term_gate.py:46`; `term_gate.guard` `term_gate.py:70` (error text `:61`);
  `page.build_page` `page.py:23`; `config.tunnel_public` `auth_set` `config.py:783`.
- Readers of `config.AUTH` **as plaintext**: `Handler._cred` `server.py:344-352` (feeds Basic
  compare `:381` and `/login` compare `:404`, and is the HMAC cookie key `:45-55`, `:373`, `:412`);
  `publish_endpoint` signs TOKEN_FILE with it `server.py:995`; tunnel fallback split
  `config.resolve_tunnel_user/_pass` `config.py:743-752`; `tunnel.cred()` `tunnel.py:74-84`.
- Cookie: `ai_auth=<exp>.<hmac-sha256(exp, key)>; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200`,
  **host-only** (no `Domain=`) `server.py:410-413`; verify `_token_ok` `server.py:45-55`
  (`hmac.compare_digest`). Basic compare `hmac.compare_digest(dec, cred)` `server.py:381`.
- `/login` POST is the only unauthenticated route `server.py:628-629`; `_authok` runs first in
  `do_GET` `:421` and `do_POST` `:630`; `_readonly` `:323-335` after it.
- `_local_caller` `server.py:223-243`: no proxy header (`_PROXY_HEADERS` `:210`), matching Origin
  (`util.origin_matches_host` `util.py:715`), peer `127.0.0.1`, and — only when no login — a loopback
  Host (`util.is_loopback_host` `util.py:723`). `_tunnel_route_ok` `server.py:354-360`.
- Tunnel has its **own** credential, plaintext `TUNNEL_USER/TUNNEL_PASS` in `config.json` (0600),
  `tunnel.ensure_creds` `tunnel.py:87-104`, falls back to splitting `config.AUTH`
  (`config.py:743-752`). `/api/tunnel/reveal` returns it `server.py:515-522`. Untouched by this plan.
- POST `/api/config` `server.py:687-724`: allowlist `config.EDITABLE`; only `PENDING_CLEAN=safe`
  requires `_local_caller` (`:715-718`).
- `store._save_json` `store.py:18-31`: unique tmp + `os.replace`, tmp created with the umask
  (world-readable window). `_load_json` `store.py:10-15` (lenient).
- TOKEN_FILE `config.py:73`, written only at startup by `publish_endpoint` `server.py:973-999`
  (called from `run` `:1033`), read by `hooks/drain-notes.py:92-98`.
- Settings UI: `readonlyField` `ext_cr_dialogs.js:968`, `postConfigValue` `:990`, `serverRow`
  `:1389`, Server tab Auth row `:1580-1583`, `srv.authSet = !!cfg.AUTH_SET` `:1782`, footer
  "Auth stays env-only" `:1799-1806`, security help bullet `:693`. Sections list `:1318`.
- SPA handles 401 on polls as `authfail` `app.js:1700` (falls to the login page on reload).
- Bundle: `scripts/bundle.py:11-16` ORDER (no `page.py`, no `term_*`); HEADER `:21` already imports
  `hashlib, hmac, secrets`; `strip_module` `:38-50` drops imports and rewrites `config.`/`tunnel.`
  only ⇒ the new module must be reached by **named** imports and its top-level names must not
  collide (`login_page` already exists in server.py `:77` — don't reuse that name).
- `.gitignore` lists `config.json`, `token`, … — not yet `login.json`.
- `tests/__init__.py` already patches globals for every in-process test — the hook for isolating
  the new file.
- Does **not** exist: any hashed-credential store, any attempt limiting, any live re-publish of
  TOKEN_FILE, any per-port cookie name.

## 4. Technical plan

### 4.1 On-disk format and keys

New file `aitracker/login.json` (`config.LOGIN_FILE`, next to `TOKEN_FILE`), gitignored, mode
`0600`, written atomically with a `0600` temp:

```json
{"v": 1, "user": "alice", "kdf": "pbkdf2_sha256", "iter": 600000,
 "salt": "<32 hex = 16 random bytes>", "hash": "<64 hex>",
 "key": "<64 hex = 32 random bytes: cookie/TOKEN_FILE signing key>", "set_at": 1763300000}
```

- `hash = hashlib.pbkdf2_hmac("sha256", password.utf8, salt, iter)`. PBKDF2 over `scrypt` because
  `hashlib.scrypt` is absent on Pythons linked against old LibreSSL, and scrypt's 16 MB/attempt
  is a memory-DoS lever on a `ThreadingHTTPServer`. `iter` is stored so it can be raised later;
  verify accepts only `100_000 <= iter <= 5_000_000` (tamper bound). Tests patch
  `login.LOGIN_ITERATIONS` down.
- `key` is the HMAC key for the `ai_auth` cookie and TOKEN_FILE when the Settings login is in
  force. Regenerated on every set/change ⇒ every previously issued cookie and token dies.
- `user` stored plain (not a secret; compared with `hmac.compare_digest`). Validation:
  1–64 chars, no `:`, no control chars. Password: 8–256 chars, any printable (`:` allowed — Basic
  splits on the first colon). No strength meter.
- **No new `config.json` key and nothing in `EDITABLE`/`VALIDATORS`** — the
  `TRACKER_AUTH`-rejected tests stay true as written.

### 4.2 New module `aitracker/login.py` (stdlib: hashlib, hmac, secrets, os, time, threading)

Imports: `from . import config`, `from .store import _load_json, _save_json`. All names prefixed
`login_` / `_login_` (flattened bundle namespace).

```python
LOGIN_ITERATIONS = 600_000
def _login_record() -> dict | None        # shape-checked read of config.LOGIN_FILE; raises _LoginCorrupt on a present-but-bad file
def login_source() -> str                 # "env" if config.AUTH else "settings" if record else ""; corrupt file -> "settings" (fail closed)
def login_on() -> bool                    # bool(config.AUTH) or login_source() == "settings"
def login_sign_key() -> str               # config.AUTH (env, unchanged) | record["key"] | "" ; corrupt -> a fresh random per-process key (nothing verifies)
def login_check(user: str, password: str) -> bool   # env: compare_digest(user+":"+pw, config.AUTH); settings: compare_digest(user) & compare_digest(pbkdf2(...), hash); always runs the KDF (dummy record when user mismatches) so timing doesn't reveal the username
def login_set(user: str, password: str) -> str      # validates, writes record with new salt+key via _save_json(..., mode=0o600); returns new key
def login_clear() -> None                 # os.remove(config.LOGIN_FILE), FileNotFoundError ignored
def login_status() -> dict                # {"on": bool, "source": "env"|"settings"|"", "corrupt": bool}  -- never user/hash/salt/key
def login_throttled(src: str) -> bool     # True while src is in back-off
def login_note(src: str, ok: bool) -> None# record outcome; ok resets src
```

Throttle (Q6): in-memory dict `src -> (fails, until)`, lock-guarded, pruned to 1024 entries. After
5 consecutive failures, each further failure sets `until = now + min(2**(fails-5), 30)` seconds;
while throttled, `/login` and Basic return **429** without running the KDF. `src` = `Cf-Connecting-Ip`
for a tunnelled request (`tunnel.via_tunnel`), else the peer address. A global
`threading.BoundedSemaphore(2)` around the KDF caps CPU from parallel guessing. Max lock-out for
the legitimate user: 30 s, and only after someone else has failed 5+ times from the same source;
the local file-delete recovery always works.

### 4.3 `server.py` changes

- Imports (`server.py:1-14`): `from .login import login_on, login_sign_key, login_check, login_set,
  login_clear, login_status, login_throttled, login_note, login_source`.
- `Handler._cred()` `:344-352`: tunnel branch unchanged; direct branch returns `login_sign_key()`
  instead of `config.AUTH` (identical value when env is set ⇒ the 2 existing `_cred(` tests hold).
- New `Handler._check(user, pw) -> bool`: tunnel ⇒ `hmac.compare_digest(user+":"+pw, tunnel.cred())`
  (today's behaviour); direct ⇒ `login_check(user, pw)`. Wraps `login_throttled`/`login_note`.
- `_authok` `:362-383`: cookie path unchanged (`_token_ok(tok, self._cred())`); Basic path splits
  `dec` on the first `:` and calls `self._check`; returns `"throttled"` sentinel so `do_GET/do_POST`
  answer 429 instead of 401.
- `_do_login` `:397-417`: use `self._check`; 429 when throttled; cookie signed with `self._cred()`.
- `_local_caller` `:238`, `GET /api/config` `:498`: `config.AUTH` → `login_on()`.
- `publish_endpoint` `:973-999`: split out `_publish_token()` (writes TOKEN_FILE signed with
  `login_sign_key()` when `login_on()`, else removes it); `publish_endpoint` calls it; the new route
  calls it after every set/change/remove (TOKEN_FILE stays valid live — drain hook keeps working).
- `GET /api/tunnel` `:501-513` and the `/api/tunnel/ctl` response `:806`: set
  `d["auth_set"] = login_on()` after the merge (config.py cannot see the file).
- `GET /api/config` adds `snap["LOGIN"] = {**login_status(), "editable": login_source() != "env"
  and _local_caller(self)[0]}`; `AUTH_SET` kept (= `login_on()`) for compatibility.
- **New route `POST /api/login`** (after the `_authok`/`_readonly` gate, before `/api/config`):
  ```
  body: {"action": "set",    "user": str, "password": str, "current": str?}
        {"action": "remove", "current": str}
  ```
  1. `_local_caller(self)` must pass, else 403 `"login can only be changed from this Mac"` (covers
     proxied/tunnelled, cross-Origin, non-loopback peer, and — when no login — foreign Host).
  2. `login_source() == "env"` ⇒ 409 `"set by TRACKER_AUTH in the environment, which overrides Settings"`.
  3. A login already exists ⇒ `current` must pass `login_check(record.user, current)` (throttled
     like `/login`), else 403. (Being logged in via cookie is not enough — guards a walked-up
     browser or a stolen cookie.)
  4. `set`: `login_set` → `_publish_token()` → 200 `{"ok": true, "on": true, "reload": true}` with
     `Set-Cookie: ai_auth=<_make_token(new_key)>` (same attributes as `:412`) so **the page that set
     it stays logged in** (Q4). `remove`: `login_clear()` → `_publish_token()` → 200
     `{"ok": true, "on": false}` plus `Set-Cookie: ai_auth=; Max-Age=0`.
  5. Never echo user/password/hash; log nothing (`log_message` is already a no-op `:942`).
- `login_page()` `:77-95`: footer `:89` → "Login set in Settings or by TRACKER_AUTH ·
  constant-time"; add an optional `hint` arg rendered only for direct (non-tunnel) requests:
  "Forgot it? On this Mac, delete aitracker/login.json — no restart needed." `_serve_login` passes
  it when `not tunnel.via_tunnel(self.headers)`. 429 from `/login` shows "Too many attempts — wait
  a few seconds".
- Host widening (step 7, decision #2): at the top of `do_GET` (before `_authok`, `:421`) and
  `do_POST` (after `/login`, before `:630`):
  `if not login_on() and not tunnel.via_tunnel(self.headers) and not is_loopback_host(Host):`
  → `/api/*` 403 JSON `{"error": "refused: Host is not loopback — turn on a login in Settings → Server to use another hostname"}`;
  HTML → a small static 403 page with the same sentence. `_local_caller`'s own Host clause and
  `term_gate.guard`'s stay (defence in depth; cheap).

### 4.4 Other files

- `config.py`: `LOGIN_FILE = os.path.join(_HERE, "login.json")` beside `TOKEN_FILE` (`:73`); rewrite
  the AUTH comment `:113-121` and `:208-215` ("env-only" stays true for `TRACKER_AUTH`; the
  Settings login is a separate, hashed file owned by login.py; env wins). No logic change.
  `tunnel_public` `auth_set` left as env-only (server overrides it).
- `store.py` `_save_json(path, obj, mode=None)`: with `mode`, create the tmp via
  `os.open(tmp, O_WRONLY|O_CREAT|O_EXCL, mode)` and `os.chmod(path, mode)` after `os.replace`.
  Default path byte-identical.
- `term_gate.py` `:46`, `:70`: `config.AUTH` → `login_on()` (`from .login import login_on`); error
  text `:61` → "…so it needs a login (Settings → Server, or TRACKER_AUTH)" — keeps the
  `TRACKER_AUTH` substring `tests/test_term_gate.py:152` asserts.
- `page.py:23`: `config.AUTH` → `login_on()`. (Bundle has no page.py — unaffected.)
- `ext_cr_dialogs.js` Server tab `:1580-1583`: replace the read-only Auth row with a **Login** row:
  status text from `srv.cfg.LOGIN` ("off" / "on — set here" / "on — set by TRACKER_AUTH
  (environment); edit the environment to change it" / "login file unreadable — delete
  aitracker/login.json"); when `LOGIN.editable`: buttons **Turn on login** / **Change** /
  **Turn off**, each opening an inline form (username, password, confirm-password client-side,
  current password when on). New `postLogin(body, cb)` beside `postConfigValue` `:990`
  (same fetch shape, path `/api/login`). On `reload: true` → `location.reload()` (so the baked
  `TERM_TAB_HOSTS` flips off with the cookie already set). Inputs `type=password`,
  `autocomplete=new-password`/`current-password`; fields cleared after the call. When not
  editable from this caller, show "Change it from the Mac running the tracker". Update `srv.authSet`
  `:1782`, the footer note `:1799-1806` and the help bullet `:693` wording. Help text on the row:
  "Stored only as a salted hash in aitracker/login.json (owner-only). Forgot it? delete that file —
  applies immediately."
- `cli.py:15` HELP: add "or set a login in Settings → Server (TRACKER_AUTH wins when both)".
- `.gitignore`: add `login.json`.
- `scripts/bundle.py:11-16`: insert `"login.py"` after `"store.py"`.
- `tests/__init__.py`: `config.LOGIN_FILE = os.path.join(tempfile.mkdtemp(), "login.json")` — so a
  login the user sets on the live dashboard in *their* checkout can never turn `make check` into
  blanket 401s (the `TRACKER_AUTH` trap, `hooks/pre-commit:5`, all over again).
- `.claude/rules/conventions.md` + `CLAUDE.md` wording — §7.

### 4.5 Steps (each independently assignable)

| # | Step | Files | Test | Depends / parallel |
|---|---|---|---|---|
| 1 | `LOGIN_FILE` constant + comments; gitignore; test isolation | `aitracker/config.py`, `.gitignore`, `tests/__init__.py` | `tests/test_login.py::test_login_file_isolated_and_ignored` (LOGIN_FILE not under `aitracker/` during tests; `login.json` in `.gitignore`) | first; ∥ 2 |
| 2 | `_save_json(..., mode=)` | `aitracker/store.py` | `tests/test_login.py::test_save_json_mode_never_wider` (result 0600; patched `os.replace` sees a 0600 tmp) | ∥ 1 |
| 3 | `login.py` (record, KDF, check, set/clear, status, throttle) | `aitracker/login.py` (new) | `tests/test_login.py` unit block: no password bytes in file; 0600; check true/false/wrong-user; env precedence; corrupt ⇒ on + check false; iter bounds; throttle 5→429 window, reset on success, other src unaffected; `compare_digest` used (spy) | after 1,2 |
| 4 | Auth seam in server: `_cred`/`_check`/`_authok`/`_do_login`, flag reads, `_publish_token`, tunnel `auth_set` | `aitracker/server.py` | route block: Settings login ⇒ `/api/list` 401 w/o cookie, 200 with `/login` cookie and with Basic; 429 after 5 bad; TOKEN_FILE signed with record key opens `/api/notes/next`; existing `tests/test_integration.py:990-1100` and `tests/test_cr_tunnel.py` stay green | after 3; serial with 5,7,9a |
| 5 | `POST /api/login` + `GET /api/config` `LOGIN` | `aitracker/server.py` | set from local ⇒ 200 + Set-Cookie works; change w/o or wrong `current` ⇒ 403; remove ⇒ off + TOKEN_FILE gone; Cf-Ray / X-Forwarded-For / cross-Origin / foreign Host ⇒ 403; env set ⇒ 409; read-only tunnel ⇒ 403; old cookie 401 after change; `GET /api/config` bytes contain none of hash/salt/key/password | after 4 |
| 6 | Flag reads in terminal gate + page | `aitracker/term_gate.py`, `aitracker/page.py` | add to `tests/test_term_gate.py`: record set + `BIND_HOST=0.0.0.0` ⇒ `allowed()`; to `tests/test_page_bundle.py`: record set ⇒ `TERM_TAB_HOSTS = false` | after 3; ∥ 4,5 |
| 7 | Every-route Host check (only if decision #2 = widen) | `aitracker/server.py` | no login: `Host: evil.example` ⇒ `/` 403 page, `/api/list` 403; `localhost`, `127.0.0.1:port`, `t5.localhost` ⇒ 200; login on: alias Host ⇒ login page, cookie ⇒ 200; `Cf-Ray` request not Host-checked (judged by tunnel cred) | after 5 |
| 8 | Settings Login row + `postLogin` + wording | `aitracker/web/ext_cr_dialogs.js` | static test in `tests/test_login.py`: dialog source posts to `/api/login`, never sends `TRACKER_AUTH` to `/api/config`; `node --check` on the file (gate misses load-time JS errors); manual: `make serve`, turn on/change/off, page stays logged in | after 5's contract; ∥ 6,7 |
| 9a | Login page footer, forgot hint, 429 text | `aitracker/server.py` | `test_integration.py:990` still finds "Unlock dashboard", still no "Tunnel"/"Cloudflare"; hint absent with `Cf-Ray` | after 7 (same file) |
| 9b | HELP + docs | `aitracker/cli.py`, `README.md`, `docs/remote-access.md` | none (text) | ∥ anything |
| 10 | Bundle ORDER | `scripts/bundle.py` | existing `tests/test_integration.py` bundle tests (`:1716-1870`) + assert `def login_on` in `dist/tracker.py` and `--help` runs | after 3; ∥ 4-8 |
| 11 | Rules wording | `.claude/rules/conventions.md`, `CLAUDE.md` | none | ∥ anything |
| 12 | Re-word anchored existing tests (assertions unchanged) | `tests/test_cr_routes.py:269-276` docstring, `tests/test_selfcheck.py:893-896` comment, `tests/test_local_host_routes.py:1-2` docstring | they stay green | ∥ anything |

Gate: `unset TRACKER_AUTH; make check` (memory: one module per process if OOM).

### 4.6 Existing tests that anchor today's env-only behaviour

- `tests/test_cr_routes.py:269-284` — POST `/api/config` `TRACKER_AUTH` ⇒ 400. **Stays true**
  (login goes through `/api/login`, never `EDITABLE`); docstring rewording only.
- `tests/test_selfcheck.py:893-896` — `"TRACKER_AUTH" not in config.EDITABLE`. Stays.
- `tests/test_term_gate.py:145-153` — error contains "TRACKER_AUTH" and "network": new text keeps both.
- ~130 `config.AUTH = …` assignments across 25 test files (incl. `config.AUTH = True` ×38 as a
  flag) — **keep working unchanged** because `login_on()` is `bool(config.AUTH) or …` and the
  Settings path only engages when `config.AUTH` is falsy. This is why `config.AUTH` keeps its
  meaning rather than becoming the resolved login.
- `tests/test_page_bundle.py:308-326`, `tests/test_term_gate_default.py`, `tests/test_local_host_routes.py`,
  `tests/test_loopback_host.py`, `tests/test_pending_routes_matrix.py:161,173`, `tests/test_term_launch.py:366`
  — all expect 403 for foreign Hosts or set AUTH; step 7 should leave them green, but each must be
  run after step 7 (any test hitting `/` or `/api/list` with a non-loopback Host, no auth and no
  `Cf-*` header would flip to 403 — grep found none).

### 4.7 Risky spot and fallback

**Risk:** the auth seam (step 4) — `_cred()` is simultaneously the Basic plaintext and the cookie
HMAC key, and the tunnel path shares it. Splitting "verify a password" from "sign a cookie" is
where a bypass would hide (e.g. a falsy key for a corrupt file making `_authok` return True, or a
tunnel request judged by the local login). Guards: corrupt file ⇒ `login_on()` True with a random
signing key nothing can match (fail closed); `_authok`'s "no credential" branch keyed on
`login_on()`, not on the key's truthiness; tunnel branch untouched and tested.
**Fallback:** if the seam refactor turns red in ways that aren't quickly understood, ship steps
1-3 + 5 with `login_check` used only by `/login` and `/api/login`, and keep Basic auth env-only
(Settings login = cookie-only; `curl -u` documented as needing `TRACKER_AUTH`). Smaller surface,
same user-visible feature.

Second risk: PBKDF2 cost on every `curl -u` request (~0.2-0.5 s). Fallback: cache a successful
Basic verification keyed by `hmac(key, header)` for 60 s.

## 5. The seven security questions

1. **Storage.** Only `{user, salt, iter, hash, key}` in `aitracker/login.json`, 0600, atomic 0600
   temp, gitignored, outside `config.json` so `GET /api/config` and `/api/tunnel/reveal` cannot
   reach it; never in the page (`build_page` reads only `login_on()`), never logged, never in the
   bundle (runtime file). Verify with `hmac.compare_digest` on the PBKDF2 output.
   *Needs plaintext:* nothing for the Settings login — cookies use the random `key`, TOKEN_FILE
   likewise, and there is no reveal for it (forgot ⇒ delete). Things that still hold plaintext,
   unchanged and out of scope: `TRACKER_AUTH` itself (process env, compared as today), and the
   **tunnel's own** `TUNNEL_PASS` in `config.json`, which needs plaintext for its share URL and
   Show button (`config.py:855-869`). The tunnel's fallback to splitting `config.AUTH`
   (`config.py:743-752`) only works for the env login; with a Settings login, `ensure_creds()`
   mints the tunnel its own pair — which is already its default path.
2. **Who may set/change/remove.** Only `_local_caller` (no proxy header, matching Origin, peer
   127.0.0.1, loopback Host when no login) — which also excludes tunnelled and read-only callers.
   Change and remove require the **current password** even with a valid cookie. When `TRACKER_AUTH`
   is set: 409, the row is read-only. Removing it: the stricter checks that hang off "no login"
   come back on the very next request — `_local_caller`/`term_gate` Host checks, the every-route
   Host check (step 7), `term_gate.allowed()` refusing the terminal on a non-loopback bind — so an
   alias/LAN user loses access at once. The Turn-off form says so before confirming.
3. **Lock-out and recovery.** Wrong value: confirm field client-side; change needs the old one.
   Forgotten password: **delete `aitracker/login.json`** (Finder or `rm`) — read per request, so
   no restart; no CLI needed. Corrupt file: fail closed, Settings/login page say "delete
   aitracker/login.json". Env and file both set: **env wins**, file ignored, row says so (decision
   #3). Login set while a tunnel is up: no effect on tunnel visitors (their own credential).
   Issued cookies: there are none before a login exists; on change, the new `key` kills every old
   cookie and the TOKEN_FILE is re-published; other open browsers fall to the login page on their
   next poll (`app.js:1700`). Terminal tabs already open on `t<n>.localhost` hit the login page
   (host-only cookie, `page.py:21-23`) and must be reopened — documented, not fixed.
4. **Live or restart.** Live: `login.json` is read per request (like `config.json` in `_readonly`),
   TOKEN_FILE re-published by the route. The page that set it gets the new cookie in the same
   response and then reloads, so it never locks itself out mid-request; `remove` clears the cookie.
5. **Widen the Host check?** Recommend **yes** once this lands. Behaviour change: with no login,
   **every** route — `/`, `/api/list`, `/api/session`, `/api/narration`, `/api/search`,
   `/api/session_search`, `/api/diff`, `/api/file`, `/api/output`, `/api/shell`, `/api/agent`,
   `/api/flags`, `/api/config`, `/api/tunnel`, all `POST` routes (title, pin, model-keep, flags*,
   notes*, config, tunnel), and `EXTRA_GET`/`EXTRA_POST` term routes — refuses a non-loopback
   Host. Already protected: pending/update/scheduler, tunnel reveal/ctl, term/*. Exempt: tunnelled
   requests (always need the tunnel credential) and any request once a login is on. A user with a
   hostname alias, a LAN IP or a Tailscale name and no login sees: API ⇒ 403 JSON; browser ⇒ a
   one-line page "This dashboard only answers on localhost. To open it from another name, turn on
   a login in Settings → Server (on this Mac)." Also lost: `HOST=0.0.0.0` view-only LAN access with
   no login (with `TRACKER_TUNNEL_READONLY`) — needs a login now.
6. **Brute force/timing.** `hmac.compare_digest` everywhere; KDF always runs (dummy on user
   mismatch). Per-source back-off after 5 failures, capped at 30 s, reset on success, 429 without
   KDF while throttled; KDF concurrency capped at 2. Worst case for the real user: 30 s, never a
   permanent lock; the file-delete recovery always works.
7. **Conventions wording.** Yes — rule 6 says app-writable state is `flags.json`/`titles.json`.
   Draft for `.claude/rules/conventions.md` rule 6, appended:
   > The one credential store is `login.json` (`config.LOGIN_FILE`, owned by `login.py`): a salted
   > PBKDF2 hash plus a random cookie-signing key, mode 0600, written via `_save_json(…, mode=0o600)`,
   > gitignored, never served by any route. It is set, changed or removed only through
   > `POST /api/login` from a `_local_caller`, with the current password when one exists.
   > `TRACKER_AUTH` stays env-only, is never written to disk, and overrides `login.json`.
   > Never put a dashboard password in `config.json` or `EDITABLE`.

   And `CLAUDE.md` "App-owned state" line: add `login.json` (hashed, 0600) and "tests repoint
   `config.LOGIN_FILE` in `tests/__init__.py`".

## 6. Decisions for the user (recommendation first)

1. **Reading:** (A) login set from Settings, hashed, live + Host check widened — *recommended*;
   alternatives (B) only a Host-check toggle, (C) plaintext `TRACKER_AUTH` in config.json (not
   recommended), (D) login only, Host check left as is.
2. **Widen the Host check to every route when no login is set:** *yes* (step 7), accepting that
   alias/LAN/Tailscale access without a login stops working until a login is turned on. Overrule ⇒
   drop step 7.
3. **Precedence:** *`TRACKER_AUTH` (env) beats the Settings login* — keeps every existing test and
   the tunnel fallback, and an operator's explicit env choice wins. The other way would match
   `config.json > env`, but then an env login could be silently replaced by a browser.
4. **Recovery:** *delete `aitracker/login.json`, no command* — vs adding `ai-tracker --reset-login`
   (one more CLI surface the user said they don't want).
5. **Basic auth (`curl -u`) against the Settings login:** *supported* (PBKDF2 per request) — vs
   cookie-only (the §4.7 fallback).

Out of scope / known gaps, named so nobody assumes otherwise: tunnel `TUNNEL_PASS` stays plaintext
in `config.json` (needed for its share URL); the `ai_auth` cookie is shared by every tracker on
`localhost` regardless of port (logging into :8787 replaces :8790's cookie) — the same as today with
`TRACKER_AUTH`.
