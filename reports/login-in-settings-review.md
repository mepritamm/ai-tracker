> SUPERSEDED 2026-11-16 — written for a misreading of the request (dashboard TRACKER_AUTH login). The user meant Claude Code's own /login. See reports/claude-login-button.md. Nothing in this file was implemented.
# Login in Settings — adversarial plan review (reviewer: opus)

Reviewed: `reports/login-in-settings.md` (v1, 364 lines) against `personal/main` @ adeb6fa in the
`pending-work-worker` worktree (branch `login-in-settings`). Read-only: grep and `sed` ranges only,
plus tiny probes (`hashlib` timing, `hmac.compare_digest` on non-ASCII). No tests, no servers.

**Counts: 2 blockers, 9 should-fix, 10 nits.**

---

## 0. Interpretation (attack 1)

- Reading (A) is the most plausible one. The user was offered "cover every route (… an alias stops
  working unless a login is configured)" and answered "configure the login **as well**". That reads
  as: yes, cover every route, and also make the login settable so alias users can turn it on. So
  widening is close to what was asked, and the plan is right to keep it as decision #2 rather than
  assume it.
- **But the question covered "a foreign Host *or a cross-site Origin*"**, and step 7 widens only
  the Host half (B1).
- **The plan builds more than was asked:** per-source attempt limiting, `BoundedSemaphore(2)`, 429
  paths and text (part of step 9a), the iteration "tamper bound", and the tunnel `auth_set`
  override. None of these were requested. Today's env login has no attempt limiting at all, and two
  of these extras add defects (B2, S2, S4, S8).
- **Smallest change that meets C1–C5:**
  1. `login.py`, with record / check / set / clear / status.
  2. The seam: `_cred`, `_authok` and `_do_login`, plus the six "is a login on" reads.
  3. `POST /api/login` (set and remove; the current password is required once a login exists).
  4. The Settings Login row.
  5. Every-route Host check plus every-POST Origin check, if decision 1 is yes.
  6. Test isolation, `.gitignore`, bundle ORDER.
  7. A one-line recovery hint on the login page.

## Verified sound (not defects — checked so nobody re-litigates)

- **The step 7 `via_tunnel` exemption is spoofable but safe.** A DNS-rebinding page can add
  `Cf-Ray` itself. That request is then judged against `tunnel.cred()`, and with no staged tunnel
  credential `_authok` refuses it (`server.py:365-371`; pinned by `tests/test_tunnel.py:404`).
- **The login cannot be reached through `POST /api/config`.** It goes through the `EDITABLE`
  allowlist (`server.py:697`). `/api/tunnel/reveal` reads only `config.json` (`server.py:521`).
- **Today's cookie is HMAC-keyed by the plaintext `TRACKER_AUTH`** (`server.py:352`, `:412`). The
  plan's random per-record `key` is an improvement, and changing the login rotates it, which kills
  every old cookie.
- **`build_page()` runs on every `GET /`** (`server.py:431`; `page.py` reads `web/*` on each call).
  So `login_on()` in `page.py:23` is live, as the plan says.
- **`hashlib.scrypt` is absent** on `/usr/bin/python3` (3.9.6, LibreSSL 2.8.3; probed). PBKDF2 is
  the right choice.
- **Bundle:** `strip_module` (`scripts/bundle.py:38-50`) drops imports and rewrites `config.` to
  bare names. The only existing `login_*` name is `login_page` (`server.py:77`), so the planned
  `login_` prefix does not collide. `term_gate.py` and `page.py` are not bundled.
- **Change/remove from a tunnel or read-only visitor** is refused twice: `_readonly()`
  (`server.py:632`) and `_local_caller` (proxy headers).

---

## Findings

### B1 (blocker): step 7 widens only the Host half; cross-site Origin stays unchecked on every POST route

- **Defect.** The contract question was "refuse a foreign Host **or a cross-site Origin** … on
  every route". `do_POST` (`server.py:626-640`) runs only `_authok` and `_readonly` before
  dispatching. `/api/config` checks Origin only for `PENDING_CLEAN=safe` (`:715-718`). It parses
  the body with `json.loads` whatever the `Content-Type`, so a `text/plain` simple request, which
  needs no CORS preflight, gets through. A plain cross-site page sends `Host: localhost:8790`, which
  passes step 7.
- **Repro (no login):**
  `curl -X POST -H 'Origin: http://evil.example' -H 'Content-Type: text/plain' -d '{"key":"LIVE_WINDOW","value":60}' http://127.0.0.1:8790/api/config`
  - Actual: 200, and `config.json` is written, both today and after step 7.
  - Expected: 403.
- **Also affected:**
  - `/api/title`, `/api/flags*`, `/api/notes*` and `/api/pin`.
  - `/login`: this is what enables B2.
  - With a login on, a page on any *other localhost port* is same-site, so the `SameSite=Lax`
    cookie is sent and the same CSRF works.
- **Fix direction.** Add one Origin check for every POST, independent of login state. An absent
  Origin stays allowed (curl, the drain hook). Do **not** add Origin checks to GET: cross-origin GET
  responses are unreadable anyway, and same-origin GETs carry no Origin. Do **not** remove the
  existing per-route checks.
- **The way.**
  - In `do_POST`, as the first statement after `p = urlparse(...)` and **before** the `/login`
    dispatch: `if not origin_matches_host(self.headers): return self._json({"error": "cross-origin refused"}, 403)`.
  - Through the tunnel this is safe: `term_gate.guard` already applies `origin_matches_host`
    unconditionally (`term_gate.py:63`), and terminals work through the tunnel (README:174).
  - Covers:
    - the classic view and the Control Room (both post same-origin);
    - `t<n>.localhost` tabs (Origin and Host are both `t<n>.localhost:port`);
    - the package and the bundle (same `server.py`);
    - with and without env `TRACKER_AUTH`.
  - Fold it into step 7 and rename step 7 "every-route Host + every-POST Origin".
- **Test** (`tests/test_login_routes.py`), red today:
  - POST `/api/config` and POST `/login` with `Origin: http://evil.example` → 403, and
    `config.json` is not created.
  - The same requests with `Origin: http://127.0.0.1:<port>` and with no Origin → not 403.

### B2 (blocker): the planned throttle gives any website a lock-out and CPU lever against the real user

- **Defect.**
  - Plan §4.2: the source is the peer address for direct requests, so it is `127.0.0.1` for the
    user's own browser **and** for every web page that browser loads.
  - `/login` is unauthenticated (`server.py:628-629`), and without B1 it takes cross-site
    `text/plain` POSTs.
- **Repro.** Any page the user visits fires 6 `fetch('http://localhost:8790/login', {method: 'POST', body: '{"user":"x","pass":"y"}'})`.
  - Each attempt costs a PBKDF2 run and holds one of the two semaphore slots.
  - After 5 failures, the real user's correct `/login` gets 429 for up to 30 s, rolling for as long
    as the page keeps firing.
  - Expected: the real user can always log in.
- **Fix direction.** Drop the throttle and the semaphore. PBKDF2 at roughly 0.5–3 s per guess is
  already the rate limit, and today's env login has none. The Origin check from B1 is then the only
  guard `/login` needs. If the user insists on throttling (decision 2), key it only on
  `Cf-Connecting-Ip` for genuinely tunnelled requests, never on `127.0.0.1`, and put it after B1's
  Origin check.
- **The way.** Delete `login_throttled`, `login_note` and the semaphore from §4.2, the
  `"throttled"` sentinel from §4.3, the 429 text from step 9a, and the throttle item from step 3's
  tests.
- **Test:** 6 cross-origin wrong `/login` POSTs → 403 each (from B1), then a same-origin correct
  `/login` → 200. Today the first half returns 401s. With the plan as written, the second half
  returns 429.

### S1 (should-fix): `importlib.reload(config)` un-isolates `LOGIN_FILE`, recreating the blanket-401 trap the plan claims to remove

- **Defect.**
  - `tests/test_term_vt.py:3420` and `:3427` call `importlib.reload(config)`, which resets
    `config.LOGIN_FILE` to the real `aitracker/login.json`.
  - From then on, every test in that process runs as "login on" if the user has set a login in
    this checkout.
  - That process is the module run under `make check`, or the **whole suite** under
    `python -m aitracker --selfcheck` (`cli.py:25`, a single-process discover).
- **Repro:** create `aitracker/login.json`, then run `--selfcheck`.
  - Actual: modules after `test_term_vt` get 401s.
  - Expected: green.
- **Fix direction.** Make the isolation survive a reload. Do not move the other config paths.
- **The way.**
  - `config.py`:
    `LOGIN_FILE = os.environ.get("TRACKER_LOGIN_FILE") or os.path.join(_HERE, "login.json")`.
  - `tests/__init__.py`, as its first lines before any `aitracker` import:
    `os.environ.setdefault("TRACKER_LOGIN_FILE", os.path.join(tempfile.mkdtemp(), "login.json"))`.
  - Narrower alternative: restore `LOGIN_FILE` in that test's `tearDown`. It is fragile, because
    the next reload anywhere reopens the trap.
- **Test** (`test_login_store.py`): `importlib.reload(config)` and assert `config.LOGIN_FILE` is
  not under the package directory. Red with the plan's assignment-only isolation.

### S2 (should-fix): a truthy `"throttled"` sentinel from `_authok` is an auth bypass waiting for one missed call site

- **Defect.** Plan §4.3 has `_authok` return `"throttled"`. Both callers test
  `if not self._authok()` (`server.py:421`, `:630`), and a non-empty string is truthy, so it
  **passes**.
- **Repro:** throttle a source, then send `/api/list` with a wrong Basic header.
  - Actual: 200 if either site keeps the bare `not`.
  - Expected: 429 or 401.
- **Fix.** Moot if B2 is accepted. Otherwise `_authok` must stay strictly `bool`, and throttling
  becomes a separate `self._throttled` check before it.
- **Test:** throttled source plus a wrong Basic header → status is not 200.

### S3 (should-fix): `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII input

- **Defect.**
  - Probed: `hmac.compare_digest('é', 'é')` raises
    `TypeError: comparing strings with non-ASCII characters is not supported`.
  - Today `/login` (`server.py:404`) and Basic (`:381`) compare `str`. Any visitor typing a
    non-ASCII character raises inside the handler, so the request dies without a response.
  - The plan's username rule (§4.1: any characters except `:` and control characters) and its
    "any printable" password make non-ASCII input legitimate.
  - `/login` also concatenates `body.get("user")` unchecked, so a JSON number raises the same way.
- **Fix.** Compare `bytes` everywhere: `.encode("utf-8")` in `login_check` (both the env and the
  Settings branch) and in the tunnel branch of `_check`. Reject non-`str` `user` or `pass` with 401.
- **Test:** `/login` with `{"user": "é", "pass": "x"}` → 401 JSON, and Basic `é:x` → 401. Today the
  connection drops without a response.

### S4 (should-fix): the iteration "tamper bound" breaks the plan's own tests and protects nothing

- **Defect.**
  - §4.1 says verify accepts only `100_000 <= iter`, and that tests patch `login.LOGIN_ITERATIONS`
    down. A record written at 1000 iterations is then rejected, so every positive test fails.
  - The lower bound guards against nothing: whoever can write `login.json` (the owner) can replace
    the hash itself.
- **Fix.** Drop the lower bound. Keep an upper bound (for example `iter <= 2_000_000`) so a
  corrupted file cannot turn every login into a CPU stall. Anything out of range is treated as
  corrupt.
- **Test:** patch iterations to 1000, call `login_set`, then `login_check` → True. Red with the
  plan's bound.

### S5 (should-fix): PBKDF2 at 600k runs on every `curl -u` request; the cache should be the default, not the fallback

- **Defect.**
  - Measured at 600k iterations: **0.50 s** on `/usr/bin/python3` 3.9.6, and **1.4–2.9 s** on
    python3.12 here (load average ~240, so the high end is inflated). The plan assumes 0.2–0.5 s.
  - Every Basic-authenticated request pays this. Browsers are unaffected: the 401s carry no
    `WWW-Authenticate`, so the SPA never sends Basic.
  - `/api/login` "change" runs 2 KDFs (verify the current password, hash the new one).
- **Fix.** Make the plan's §4.7 cache the primary path:
  - key: `hmac(record_key, header_value)` → expiry in 60 s; at most 64 entries; successes only.
  - Rotating the key on change invalidates it automatically.
  - It is not a timing oracle: only the exact header a legitimate user sent can hit.
  - The env and tunnel paths stay cheap plaintext compares, uncached.
- **Test:** patch `hashlib.pbkdf2_hmac` with a counter. Two Basic requests → 1 call. After
  `login_set` → a new call.

### S6 (should-fix): the recovery hint names the wrong path for the bundle and for a `uv` install, and Settings cannot show it when the file is corrupt

- **Defect.**
  - `_HERE` is the directory of `config.py` (`config.py:8`). In the bundle that is `dist/`; under a
    `uv` install it is site-packages. "Delete aitracker/login.json" is wrong in both.
  - With a corrupt file, `login_on()` is True and nothing can pass `_authok`, so the Settings
    dialog is unreachable. The plan's claim that "Settings says delete" cannot happen; only the
    login page can.
- **Fix.**
  - Render `config.LOGIN_FILE` with the home directory collapsed to `~`.
  - Show it only when `_local_caller(self)[0] and is_loopback_host(Host)`. The second clause
    matters: with a login on, `_local_caller` skips the Host check, so without it a rebinding page
    could read the path.
  - Drop the "Settings says" claim from §5 Q3.
- **Test:** the login page over loopback contains `login.json` and `~`. With `Cf-Ray`, or with
  `Host: evil.example` plus a login on, it does not.

### S7 (should-fix): the "parallel" steps are not file-disjoint, and four steps have no test file

- **Defect.**
  - Steps 1, 2, 3 and 8 all write `tests/test_login.py`, yet 1 ∥ 2 are marked parallel.
  - Steps 4, 5, 7 and 9a say "route block" without naming a file.
- **Fix.**
  - `tests/test_login_store.py` for steps 1 and 2.
  - `tests/test_login.py` for step 3.
  - `tests/test_login_routes.py` for steps 4, 5, 7 and 9a, run serially.
  - `tests/test_login_ui.py` for step 8, driving `ext_cr_dialogs.js` with the existing node harness
    (`tests/test_cr_dialogs_config_exec.py:108`) instead of a grep. It renders the off, on-here,
    env and not-editable states and checks that password fields are cleared.
- **Test:** n/a (structure).

### S8 (should-fix): the throttle (if kept) pollutes tests and changes tunnel behaviour

- **Defect.**
  - The in-memory failure counts persist across tests in one process. `test_integration.py` has
    17 `401` asserts and `test_cr_tunnel.py` 9, from `127.0.0.1` and `1.2.3.4`. Cumulative failures
    turn later expected 401s into 429s.
  - `_check` also wraps the **tunnel** credential, which is scope creep.
- **Fix.** Moot with B2. Otherwise add a reset in `tests/__init__.py` and leave the tunnel path
  untouched.

### S9 (should-fix): turning the login on or off on a non-loopback bind has consequences the form doesn't state

- **Defect.**
  - **Turning on** with `HOST=0.0.0.0` makes `term_gate.allowed()` (`term_gate.py:46`) True live.
    That means a shell for anyone on the network who knows a password that may be only 8
    characters.
  - **Turning off** under reading D (no step 7) opens the dashboard to the LAN with POST rights,
    because `_readonly` defaults to False for non-local peers (`server.py:323-335`). The plan's
    form warns only about losing access.
- **Fix.** Add a server-owned `LOGIN.bind_public = not term_gate._is_loopback(config.BIND_HOST)` to
  `GET /api/config`. The row renders two warnings from it, per rule 5:
  - set: "this also enables the in-browser terminal for anyone on your network with this password";
  - remove: "anyone on your network can then …".
- **Test:** `BIND_HOST="0.0.0.0"` → `LOGIN.bind_public` is True. The UI harness shows both
  warnings.

### Nits

- **N1. Leave the tunnel `auth_set` alone.** §4.3 overrides `tunnel_public`'s `auth_set`, but
  nothing in `web/` reads it (grep: 0 hits). It means "`TRACKER_AUTH` is available as the tunnel
  fallback", which a Settings login is not. Drop the bullet.
- **N2. No PEP 604 annotations.** `dict | None` raises at def time on 3.8/3.9: `pyproject.toml:9`
  says `>=3.8`, and `/usr/bin/python3` is 3.9.6. The bundler drops every `^from` line
  (`bundle.py:41`), so `from __future__` cannot rescue it.
- **N3. Env-path Basic regression.** A `TRACKER_AUTH` with no colon (`secret`) matches Basic today
  (`server.py:381`). Splitting and re-joining gives `secret:` and breaks it. The env branch should
  keep comparing the raw decoded header (as bytes).
- **N4. One login read per request.** `login.json` is read about 4 times per request
  (`_readonly` → `_local_caller`, `_cred`, the page, `term_gate`), with a TOCTOU between them.
  Resolve it once (`self._login`) or cache by mtime.
- **N5. Cookie collision is not "the same as today".** Two checkouts with Settings logins sign
  `ai_auth` with different random keys, so they knock each other out. Same-password env logins
  sign identically. Document it; don't fix.
- **N6. Show a shadowed Settings login.** With both env and file set, the status should say "a
  Settings login is saved and applies when `TRACKER_AUTH` is unset", so a forgotten old password
  doesn't resurface silently.
- **N7. Stale status header.** The plan's header says the worktree could not be created. The branch
  `login-in-settings` exists and is checked out here.
- **N8. `login.json` is a bearer credential.** It holds the cookie-signing key, so reading it lets
  you forge a session. The conventions wording should say so, alongside "hashed".
- **N9. BrokenPipe guards (rule 8).** The new `Set-Cookie` response in `/api/login` and the step 7
  403 HTML page need the `BrokenPipeError`/`ConnectionResetError` guard.
- **N10. Stale UI strings.** "set TRACKER_TERMINAL=1 and TRACKER_AUTH" appears in
  `ext_vt.js:2995`, `:3289`, `:3887`, `ext_cr_term.js:649`, `ext_launch.js:346`, and the help at
  `ext_cr_dialogs.js:1748`. The plan touches only `:693`, `:1580` and `:1799`. Append "or turn on a
  login in Settings → Server"; no test pins these strings.

### Lock-out walk (attack 4), beyond the findings above

- **The page that sets the login:** fine. It gets the cookie in the same response, then reloads.
  Concurrent polls in that window may get a 401 (`app.js:1700` `authfail`), which is harmless.
- **Headless or remote host with `HOST=0.0.0.0` and no login, after step 7:** there is no remote
  way back in. `/api/login` requires peer `127.0.0.1`, so the user needs `ssh -L` or env
  `TRACKER_AUTH`. The 403 text should say exactly that.
- **Forgotten password:** recovery is deleting the file, live, with no restart. That is not a
  `make` command, but it is a manual filesystem step (decision 4).
- **A logged-in tunnel or LAN visitor with terminal access** can delete or overwrite `login.json`
  from the shell. This is inherent (a shell is the owner); it is not a plan defect.

---

## Clean-plan deltas

1. **§2 / §6 #1:** state that C2 covers Host **and** Origin. Rename step 7 "every-route Host +
   every-POST Origin" and add B1's one line in `do_POST`, before `/login`.
2. **§4.2:** delete the throttle and the semaphore (`login_throttled`, `login_note`). Make the
   successful-Basic cache primary (S5). Drop the iteration lower bound and keep `iter <= 2_000_000`
   (S4). Compare bytes everywhere (S3). No PEP 604 annotations (N2).
3. **§4.3:**
   - Remove the `"throttled"` sentinel and all 429 paths; `_authok` stays bool (S2).
   - The env branch compares the raw decoded header (N3).
   - Drop the tunnel `auth_set` override (N1).
   - Add `LOGIN.bind_public` (S9).
   - The login-page hint shows `~`-collapsed `config.LOGIN_FILE`, only for loopback-Host
     `_local_caller` requests (S6).
   - BrokenPipe guards (N9).
4. **§4.4:** `LOGIN_FILE` honours `TRACKER_LOGIN_FILE`, and `tests/__init__.py` sets that env var
   before any import (S1). Add the N10 UI strings to step 8.
5. **§4.5:** test files per S7. Step 9a loses the 429 text. Step 3 loses the throttle tests and
   gains the S3 and S4 tests. Step 4 gains the S5 cache test. Step 7 gains the B1 Origin tests.
   Steps 1 and 2 stay parallel only with separate files.
6. **§5 Q3 and Q6:** correct the "Settings says delete" claim (S6). Replace the brute-force answer
   with "KDF cost is the limiter; Origin check on `/login`". Fix the cookie claim (N5). Restate the
   headless lock-out.
7. **§5 Q7 conventions draft:** add "`login.json` holds the cookie-signing key — a bearer
   credential like `token`" (N8). Add the every-POST Origin rule, and the every-route Host rule when
   no login is set, if decision 1 is yes.
8. **Header:** fix the stale worktree status (N7).

## Decisions the user must make

1. **Widen to every route: Host on all routes and Origin on all POSTs (when no login is set,
   for Host).** Recommend **yes, both**. Cost: alias, LAN and Tailscale access without a login
   gets 403 until a login is turned on, and a headless remote host needs `ssh -L` or env to recover.
   The Origin half breaks nothing legitimate that we found.
2. **Attempt limiting.** Recommend **none**: PBKDF2 is the limiter, which matches today's env login.
   Cost: a LAN attacker can try roughly 1–4 guesses a second against a weak password. Keeping it
   costs B2, S2 and S8 plus about 60 lines.
3. **Basic auth (`curl -u`) against a Settings login.** Recommend **supported, with a 60 s
   success cache**. Cost: about 20 lines and an in-memory digest. The alternative is cookie-only,
   with `curl -u` documented as env-only.
4. **Forgot-password recovery.** Recommend **delete the file at the path the login page shows**.
   Cost: one manual Finder or `rm` step. The alternative is an on-screen macOS confirm dialog
   launched from the login page: no file step, but darwin-only, and the route must require a
   loopback Host unconditionally.
5. **Precedence.** Recommend **env `TRACKER_AUTH` wins**, with Settings showing any shadowed saved
   login (N6). Cost: an operator's env choice can't be overridden from the browser, which is
   intended.

## Not examined

- The full `ext_cr_dialogs.js` render and harness, and `app.js`'s `authfail` UI beyond `:1700`.
- cloudflared's Host and Origin forwarding, inferred from `term_gate.py:63` working through the
  tunnel.
- Windows behaviour (the `os.open` mode is ignored there).
- Where stdout goes after the in-app restart (`update.py`).
- The individual gates of the `EXTRA_GET`/`EXTRA_POST` term routes.
- The `HOST`/`PORT` startup path (`cli.py:45` reads env; `config.resolve_host` not traced).
- README and `docs/remote-access.md` beyond the grepped lines.
- Every test outside those grepped for `TRACKER_AUTH`, `config.AUTH`, `Host` and `401`.
