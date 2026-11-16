# Adversarial re-review: Claude Code login button, plan v2 (reviewer: opus)

Reviewed: `reports/claude-login-button.md` ("Technical plan (v2)"), against `personal/main` @ adeb6fa in
this worktree, alongside v1's review `reports/claude-login-button-review.md`. I did not debate the
user's decisions (2026-11-16). This review attacks only how v2 implements them.

Method: read-only `grep -n` / `sed -n` and Read on line ranges. I ran no tests, servers, `make`,
login or logout. I did not run `claude auth status` (v1's key list was reused). External sources:
Cloudflare's tunnel docs, and the Claude Code interactive-mode page, used to verify the §2 R3 quote.

**Verdict.** v2 is close.

- The every-POST Origin check is sound, including through the tunnel (see the verdict below).
- The weak spots:
  - the status subprocess can wedge its lock;
  - the in-terminal policy is decided in JS rather than on the server, which leaves one cheap wrong-shown case;
  - the human checklist has one check that proves nothing and one instruction that risks a real side effect.

**Counts: 0 blocker, 3 should-fix, 7 nit.**

---

## Tunnel Host/Origin verdict (brief item 1): HOLDS. No X-Forwarded-Host change.

**Evidence:**

- **How the tunnel is spawned.** `tunnel.py:210` runs `cloudflared tunnel --url http://<host>:<port>` with no `--http-host-header`. Cloudflare's origin-parameters page lists `httpHostHeader` ("Sets the HTTP Host header on requests sent to the local service") with default `""`, i.e. no rewrite.
- **Vite precedent.** Cloudflare's own local-dev-tunnels page tells Quick-tunnel users to *"add `.trycloudflare.com` to `preview.allowedHosts`"*. Vite's allowedHosts check reads the `Host` header, so the origin receives the public `*.trycloudflare.com` name, not `127.0.0.1:<port>`.
- **The repo's own fixture.** `tests/test_term_launch.py:363-375` says it pins "the literal header set cloudflared puts in front of the origin server", and its header set includes `"Host": "some-name.trycloudflare.com"`.
- **The repo already depends on it.** `term_gate.guard` (`term_gate.py:55-75`) and `_local_caller` (`server.py:236-240`) already treat "tunnel/LAN Hosts are legitimate" under `TRACKER_AUTH`.

**So:**

- Browser `Origin: https://x.trycloudflare.com` has netloc `x.trycloudflare.com`, because the default :443 is omitted.
- cloudflared forwards `Host: x.trycloudflare.com`.
- `util.origin_matches_host` (`util.py:715-721`) returns True, so tunnelled POSTs pass step 1.
- The login page's `doLogin` (`server.py:83-87`) is a same-origin `fetch` POST, so it carries a matching Origin, locally and through the tunnel.

**How the code tells a tunnel request apart:** `tunnel.via_tunnel(headers)` (`tunnel.py:66-71`), which checks for `Cf-Connecting-Ip`/`Cf-Ray`. It is used by `Handler._cred()` (`server.py:342-350`). Honouring `X-Forwarded-Host` would be **wrong**: any client can forge it. No fix is needed. Only the H6 live check remains (see N6 for the fallback if it fails).

**`origin_matches_host` edge cases (no change needed):**

| Case | Behaviour |
|---|---|
| `Origin: null` | → False (refused), which is correct |
| Ports | Compared literally. Browsers and cloudflared both omit default ports, so there is no mismatch on any supported path |
| IPv6 | `[::1]:8790` vs `[::1]:8790` → equal |
| Case | Compared case-sensitively. Browsers lowercase both values; only non-browser clients could differ, and they send no Origin |
| Referrer policy | Nothing in `aitracker/web` or `server.py` sets `Referrer-Policy: no-referrer`. That setting would make same-origin POSTs send `Origin: null` (Fetch spec) |

**Route count.** The 13 newly covered routes are correct as listed (`server.py:628-936`). `EXTRA_POST` registrations come from three modules: `term_vt.py:4928-4932` (5 routes), `term_run.py:612-613` (2) and `term_launch.py:229` (1). `tunnel.py` registers none. One inaccuracy: see N1.

---

## Findings

### SF1 (should-fix). The status subprocess can wedge `_AUTH_LOCK` for good, and every later Settings render then hangs a thread

1. **Defect.** Plan §4.2 runs `subprocess.run([...], capture_output=True, timeout=15)` while holding `_AUTH_LOCK`.
   - `subprocess.run`'s timeout kills only the direct child, then calls `communicate()` again with no timeout. If anything the CLI spawned still holds stdout or stderr, that second wait never returns. The lock is then held forever.
   - Every later `GET /api/claude/auth` blocks its handler thread on `_AUTH_LOCK.acquire()` indefinitely. `ThreadingHTTPServer` with `daemon_threads` (`server.py:946-947`) leaks one thread per Settings render or focus.
   - The child also inherits the server's controlling tty, which is the `make serve` terminal.
   - **Repro (unit):** make `subprocess.run` hang past its timeout (a fake whose post-kill wait blocks on an Event). Actual: a second caller on another thread never returns. Expected: a generic error within about `AUTH_STATUS_TIMEOUT + 5` s.
   - The repo already solved this once: `update._run` (`update.py:62-80`) uses its own session (`start_new_session=True`, so no /dev/tty), `os.killpg(SIGKILL)` on timeout, and a bounded 5 s post-kill `communicate`.
2. **Fix direction.**
   - Spawn in its own session, kill the whole group on timeout, and bound the post-kill wait.
   - Acquire the lock with a timeout, so a stuck run degrades to an error instead of a hang.
   - Must NOT change the three-key allowlist, the TTL/floor, or `cwd="~"`.
   - Do not add `nice`: 0.15 s of CPU (v1 S3) does not need it.
3. **The way.**
   - In `gateway.claude_auth_status`, build it as `Popen([exe,"auth","status","--json"], stdin=DEVNULL, stdout=PIPE, stderr=PIPE, cwd=os.path.expanduser("~"), start_new_session=True)`, then `communicate(timeout=AUTH_STATUS_TIMEOUT)`.
   - On `TimeoutExpired`: `os.killpg(p.pid, SIGKILL)` (falling back to `p.kill()`), then `communicate(timeout=5)` in a `try`, then the generic error.
   - That is `update._run`'s exact shape. Either copy those ~10 lines, or add a `cwd=None` passthrough to `update._run` and import it. Copying keeps step 2 single-file.
   - Lock: `if not _AUTH_LOCK.acquire(timeout=AUTH_STATUS_TIMEOUT + 10): return {...generic "busy" error...}`, with `try/finally: release`.
   - **Re-check the cache *inside* the lock** (see N3).
   - Add `signal` to gateway.py's import line. It is already in the bundle HEADER (`scripts/bundle.py:21`).
   - Package and bundle behave identically. Classic and Control Room are unaffected (they share the route).
4. **Test** (`tests/test_claude_auth_status.py`), red against the v2 shape:
   - patch `gateway.subprocess.Popen` with a fake whose first `communicate` raises `TimeoutExpired` → assert `os.killpg` was called with the fake pid and the result is the generic error;
   - a second thread calling while a first holds the lock past the bound → returns the busy error, and the thread joins within the bound.

### SF2 (should-fix). The "Anthropic only" policy is decided in JS in two files, and the cheapest wrong-shown case (iii) is left in

1. **Defect.**
   - Plan §4.3 returns `gateway` from `/api/term/attached`. Both `ext_vt.js` and `ext_cr_term.js` then decide `attached && launchGw === "anthropic"`. That is policy re-derived client-side, twice, against conventions rule 5 ("Server owns policy; client renders it").
   - Case (iii), the `claude attach <id>` retry pane: `term_gate.attach_argv` (`term_gate.py:387-395`) always returns bare `["claude","attach",target]`, and `_retry_with_attach` sets `pt.cmd` from it (`term_vt.py:2609`, `:2651`). So an **OpenRouter** session's attach pane reads `anthropic`, and the button shows.
   - That case is detectable from `pt.cmd` alone, at zero cost.
   - **Repro:** an OpenRouter session that is running as a bg agent. "Resume terminal here" hits the refusal, and the backstop swaps in `claude attach abcd`. The poll returns `{claude_attached:true, gateway:"anthropic"}`. Actual: `/login` is visible. Expected per the user decision: hidden.
   - Also: the classic catch branch (`ext_vt.js:2576`) would leave a stale `launchGw`. This is harmless only because `.vtswitchers` is hidden too.
2. **Fix direction.**
   - The server returns one boolean, `login_ok`, and both clients render it.
   - Hide on attach panes (wrong-hidden beats wrong-shown, as the brief says).
   - Must NOT change `_term_title`'s output. Its existing tests and its documented gap (a) stay as they are. Do not expose `gateway` at all: nothing consumes it once `login_ok` exists.
3. **The way.**
   - `term_vt.py`, step 4: keep the extracted `_cmd_gateway(cmd, orl)` exactly as v2 specifies (the `_term_title` refactor stays behaviour-identical).
   - Add `def _login_ok(cmd, orl): argv = shlex-split-or-split(cmd); return _cmd_gateway(cmd, orl) == gateway.ANTHROPIC and argv[1:2] != ["attach"]`.
   - In `attached()`, after `_refresh_fg` under `_LOCK`, read `lo = _login_ok(pt.cmd, orl)`. Respond `{"claude_attached": fa, "login_ok": fa and lo}`, where `fa = _foreground_is_claude(pt.fd)`.
   - Clients:
     - `ext_vt.js`: `self._loginOk = !!(j && j.login_ok)`. Set it to false in the non-ok and catch branches. Then `loginBtn.style.display = self._loginOk ? "" : "none"`.
     - `ext_cr_term.js`: `st.loginOk = !!(jj && jj.login_ok)`. Set it to false in the catch branch and at the `:436` reset. Then `el.loginPill.hidden = !st.loginOk`.
   - Both views; Anthropic and OpenRouter; local and tunnelled alike. The bundle is moot: `term_vt` is stripped from it (`server.py` `_term_count` docstring; `scripts/bundle.py`).
4. **Test.**
   - `tests/test_attached_gateway.py` → rename it `test_attached_login_ok.py`. Use `_bare_pty`/`_FakeHandler` from `tests/test_term_vt.py:4055/:680`. The query must carry `session` matching `pt.session`, or `_req_session` returns 400 and `_pty_owned` gives a mismatch.

     | `pt.cmd` | `login_ok` |
     |---|---|
     | `"claude /login"` | True |
     | `"claude attach abcd"` | **False** (red under v2) |
     | the launcher path, including one with a space | False |
     | `"/bin/zsh -l"` | False |
     | any of the above with `_foreground_is_claude` patched False | False |

   - The `_term_title` parity cases stay.
   - JS tests (steps 6 and 7) drive `login_ok` instead of `gateway`.

### SF3 (should-fix). Human checklist: H4's OpenRouter case cannot fail, and H1 risks a real side effect

1. **Defect.**
   - **H4** checks the button is absent on "a '+ New Claude session' opened with the OpenRouter gateway". That terminal is session-less: `ext_launch.js:351-358` omits `sid`, and `ext_vt.js:4117` builds a ContextBar only with a `sid` (v1 N4). It never has a button, whatever the gateway, so the check passes even if the gateway logic is wrong.
   - **H1** says "If a trust prompt appears first, note it". It does not say *don't accept it*. Pressing Enter at the trust prompt trusts `~` for every future session, which is the real side effect v1 B1 warned about.
   - **H5** ("After a real login, or Esc") contradicts the "nothing changes" instruction at the top.
   - **H6** says "(with `TRACKER_AUTH`)". But a tunnelled request is judged against the *tunnel's* credential (`server.py:342-350`), not `TRACKER_AUTH`. The three POSTs also need `TUNNEL_READONLY` off; with it on, `_readonly()` refuses every POST before step 1 runs, so H6 would "fail" for the wrong reason.
   - Nothing says to tear down the stray `claude` left running in `~` after Esc.
2. **Fix direction.** Rewrite the checks so each one can fail, and so none of them logs in, trusts a folder, or leaves a process behind. No code change.
3. **The way:** replace §6 with the checklist in "Clean-plan deltas" item 5 below.
4. **Test.** Human only. Each check now has an observable that differs between correct and broken code.

### N1 (nit). `/api/tunnel/ctl` is not "already Origin-checked" when a credential is in force

`_tunnel_route_ok` (`server.py:354-360`) returns True as soon as `self._cred()` is truthy. Its Origin check runs only when there is no credential. So under `TRACKER_AUTH`, or through the tunnel, `/api/tunnel/ctl` is **newly** covered by step 1. That makes 14 newly covered routes with a credential, not 13.

- **Direction:** fix the §4.1 table text only. No code change.
- **Test:** add `/api/tunnel/ctl` with `AUTH="u:p"` and `Origin: http://evil.example` → 403 to `tests/test_post_origin_guard.py`. It is red today: `test_tunnel_routes_unchanged_with_login` (`tests/test_local_host_routes.py:104-114`) shows it passes with a credential.

### N2 (nit). Wrong-shown case (v) is understated

The plan says (v) lasts "within one poll (~2 s)". It actually lasts for **the whole life of the hand-typed job**.

- If the user exits the app-launched `claude` and types another job before any `_refresh_fg` call sees the shell at its prompt, `_refresh_fg` (`term_vt.py:1873-1881`) only sets `fg_seen_child = True` and returns. `pt.cmd` keeps reading `claude …` until that next job exits.
- The aliasing variant belongs with (iv): an interactive-shell `alias claude=…` applies to the typed line too.
- **Direction:** correct the §4.3 and README text. **No code.** Tracking the job's pgid would be wider than the defect: a wrongly shown button still does exactly what the user clicked, the machine-wide `/login` (§2 R3, v1 S4).
- **Test:** none (documentation).

### N3 (nit). Spell out the in-lock re-check and use a monotonic clock

The docstring promises "a concurrent caller waits and reads the result". That holds only if the age check is repeated *after* the lock is acquired. A check done only before the lock would let the waiter re-run the CLI.

- **Way:** under the lock: `age = time.monotonic() - _AUTH_CACHE["at"]`. If `val is not None and (age < AUTH_FRESH_FLOOR or (not fresh and age < AUTH_TTL))`, return the cached value. Otherwise run.
- `time.monotonic` avoids wall-clock jumps. Tests patch `gateway.time.monotonic`. `threading` binds its own clock at import, so patching it is safe.
- **Test:** the plan's two-thread case with **both** threads `fresh=True` → one run.

### N4 (nit). Status vs terminal environment parity, and `claude` being the launcher

- The status CLI runs in the server's environment: non-login, no rc files.
- A dashboard terminal's `claude` runs in a login shell: rc exports and aliases (`term_vt.py:3131`, `-l`).
- `authMethod` can therefore disagree with what a terminal's Claude uses (for example, an rc-exported `ANTHROPIC_API_KEY`).
- If `shutil.which("claude")` *is* the OpenRouter wrapper (same path as `gateway.or_launcher()[0]`), the status reports the wrapper's environment.
- **Way:** in `claude_auth_status`, if `exe == gateway.or_launcher()[0]`, return `{available: False, error: "claude on PATH is the OpenRouter launcher"}`. Add one README sentence: "status reflects the server's environment".
- **Test:** patch `which` and `or_launcher` to return the same path → `run`/`Popen` is never called.

### N5 (nit). The `subscriptionType` label is unspecified

The plan gives "Logged in · Claude Max subscription" but not the transform from the raw value.

- **Way:** `st = d.get("subscriptionType")`. Use it only if `isinstance(st, str) and re.fullmatch(r"[a-z0-9_]{1,24}", st)`; label `"Claude " + st.replace("_"," ").title() + " subscription"`. Otherwise fall back to `_AUTH_LABELS`. `re` is already in HEADER.
- **Test:** `"max"` → "Claude Max subscription"; `"<b>"` → the generic "Claude subscription".

### N6 (nit). §4.7 fallback and §2 R4 should reflect the tunnel evidence

§4.7 says the only fallback is "revert step 1". The evidence above settles R4's "believed to".

- **Fallback, if H6 shows `refused: cross-origin`:** normalise default ports in `origin_matches_host`. Compare the lowercased hostname plus the effective port (80 for http and 443 for https when omitted) on both sides.
- It must NOT honour `X-Forwarded-Host` (forgeable), and must not exempt `via_tunnel` requests.
- **Test for the fallback:** `{"Origin":"https://x.trycloudflare.com","Host":"x.trycloudflare.com:443"}` → True. `{"Origin":"https://x.trycloudflare.com","Host":"y.trycloudflare.com"}` → False.

### N7 (nit). GET `/api/claude/auth` can be triggered cross-site; accept it and document it

`_local_caller` cannot stop an `<img src="http://localhost:8790/api/claude/auth?fresh=1">` from any page: a GET carries no Origin, and with no `TRACKER_AUTH` the Host is loopback.

- The page cannot read the response (no CORS).
- It can force at most one CLI run per `AUTH_FRESH_FLOOR` (5 s).
- **Direction:** no code. The floor is the bound. Say so in the rule-6 exception text.
- **Test:** none beyond the existing floor test.

---

## Brief items answered without a separate finding

- **Status (item 2).**
  - The cache is per process: a module global plus a lock. Under `ThreadingHTTPServer` the lock is correct once N3 is applied.
  - The route is absent from `_RO_GET_ALLOW` (`server.py:297-302`), and `do_GET` refuses read-only visitors before routing (`:425`). `_local_caller` refuses tunnel and proxy callers (`_PROXY_HEADERS`, `server.py:210-211`, includes `CF-Connecting-IP`/`CF-Ray`).
  - The fresh-dict allowlist cannot leak a new key.
  - **Poll check:** the Server tab is never re-rendered by a timer. Only the Tunnel tab is re-rendered by `pollTunnel` (`ext_cr_dialogs.js:1350-1360`). `:1411` re-renders the active section after a failed config write; that hits the cache, not a new CLI run.
- **Flip (item 3).**
  - "Switch account" runs `/login`. The interactive-mode quote is verified verbatim: *"The conversation changes hands: you switch accounts with `/login`, …"*, under "Cancel the wait".
  - When the status is unknown (CLI missing, timeout, 403 or another error), `st.logged_in` is falsy, so the button reads **"Log in"** and still works. That is correct.
- **`pt.cmd` per mode (item 4).**

  | Terminal | `pt.cmd` |
  |---|---|
  | `new` | `[launcher] + prompt`, set after typing (`term_vt.py:1967`) or at the dedicated spawn |
  | `resume` | `[_launcher_for(sid), "--resume", sid]` (`term_gate.py:300-317`), so `claude` or the launcher |
  | fork retry | the same, plus `--fork-session` (`:2531`) |
  | `cwd` | the shell's argv |
  | attach retry | bare `claude attach` (`:2651`), see SF2 |
  | deferred folder start | the shell until the line is typed, so hidden |

  - No terminal survives a server restart: PTYs live in-process, and update-apply asks to close them. So there is no "restored" case.
  - Exposing `gateway` (or `login_ok`) leaks nothing. The route is not read-only-allowed, it sits behind `term_gate.guard` plus `_pty_owned`, and the value is one word with no launcher path.
- **Parallelism, load order, bundle (item 5).**
  - Steps 1 and 3 share `server.py`, and the order is stated ("after 1 (same file)").
  - No other pair collides: the test files are disjoint, and SF1's copy keeps step 2 inside `gateway.py`.
  - No new load-time reference. `window.ExtLaunch` is read at click time, and the ContextBar button is built inside the constructor.
  - No name collision: `_AUTH_*`, `AUTH_TTL`, `AUTH_FRESH_FLOOR`, `AUTH_STATUS_TIMEOUT`, `claude_auth_status`, `_cmd_gateway` and `_login_ok` are all absent from `aitracker/` and `scripts/`.
  - The bundle rewrites only `config.` and `tunnel.` prefixes (`scripts/bundle.py:45-49`). The new gateway code uses no `gateway.` self-prefix. HEADER has `json, os, re, shlex, shutil, signal, subprocess, threading, time`.
  - No existing test counts `.vtswitchers` children or `cr-term-status-right` pills (grep).
- **Beyond scope (item 6).** Nothing material.
  - The `_term_title` refactor is justified by conventions rule 4; keep it behaviour-identical (SF2).
  - The focus refresh is what makes the user's flip visible.
  - The conventions rule-6 exception is required by rule 6 itself.
  - v2's TIP and WARN text match the user's decision.
- **Popup timing.** `window.open` runs after `/api/term/pty` resolves (`ext_launch.js:367`), outside the click's user activation if that takes more than about 5 s. This is the same path pending Resume already proved live (adeb6fa). It is covered by an observation in H1, not by code.

---

## Not examined

- Real TUI behaviour (barred): the trust dialog in `~`, `/login` vs `/design-login` ranking, the CR resend.
- Whether the `claude` native binary spawns any child during `auth status` (SF1's hang needs one). The fix is cheap either way.
- I did not re-run `claude auth status`. The key list and the exit-1 JSON come from v1 and the CLI reference.
- `_deferred_folder_start` end to end, beyond its `pt.cmd` assignment.
- `closePicker()`/`showPickerBusy()` side effects when called from Settings with no picker open (shared with pending Resume).
- Live `cloudflared` headers. The evidence above is from docs and fixtures; H6 is the live proof.

---

## Clean-plan deltas

1. **§4.2 `claude_auth_status`:**
   - use own session plus group kill plus a bounded post-kill wait (SF1), with the lock acquired with a timeout;
   - re-check the cache inside the lock on `time.monotonic` (N3);
   - add the launcher-equals-`claude` guard (N4) and the `subscriptionType` charset/label rule (N5);
   - add `signal` to the import line.
2. **§4.3:**
   - replace the `gateway` field with `login_ok = claude_attached and _cmd_gateway(cmd)==ANTHROPIC and argv[1:2] != ["attach"]` (SF2);
   - clients render `login_ok` only (`ext_vt.js` `_loginOk`; `ext_cr_term.js` `st.loginOk`, reset at `:436` and in both failure branches);
   - move (iii) from "wrongly shown" to "hidden";
   - restate (v) as lasting the hand-typed job's lifetime, and add aliases to (iv) (N2).
3. **§4.1:** the `/api/tunnel/ctl` row moves to "newly covered when a credential is in force" (N1). Add the N1 case to `tests/test_post_origin_guard.py`.
4. **§2 R4 and §4.7:**
   - R4: the tunnel's `Host` is the public hostname, citing the evidence above;
   - §4.7 fallback becomes default-port normalisation in `origin_matches_host`, never `X-Forwarded-Host` (N6);
   - the rule-6 exception text gains "a cross-site GET can trigger at most one run per 5 s" (N7).
5. **§6 human checklist (SF3).** Replace it with the following.
   - **Setup:**
     - Use a logged-in machine.
     - **At Claude's login-method screen press Esc. Never pick a method.**
     - **If a folder-trust prompt appears, choose the "No"/exit option. Do NOT press Enter to trust `~`.** Record that it appeared.
     - After each check, `/exit` and close the terminal from Manage terminals.
   - **H1. Settings → Server.**
     - The label reads "Switch account" and the status line shows no email or org.
     - Click it. A new tab opens on `~` and shows the login-method screen: not a model reply, not "Unknown command", not `/design-login`. Press Esc.
     - Note any "Popup blocked" alert.
   - **H2. Classic overlay of an Anthropic session** ("Resume terminal here" on a session whose model is a Claude model).
     - `/login` shows while Claude is foreground.
     - Click it at an idle, empty prompt. The method screen waits for a choice. Press Esc.
   - **H3.** H2 in the Control Room terminal panel.
   - **H4. The button is absent on:**
     - (a) a plain-shell "Open terminal here";
     - (b) **"Resume terminal here" on a session whose model is an OpenRouter `vendor/model` id**, in both views;
     - (c) a `claude attach` pane, if one is reachable.
   - **H5.** After H1's Esc, return to the Settings tab. The status line re-reads on focus and stays "Switch account". No login took place.
   - **H6. Through the tunnel.** `TUNNEL_READONLY` must be off. Use the tunnel's share URL and its credential; `TRACKER_AUTH` is irrelevant here.
     - Sign in to the dashboard, flag a session and change one config value. All three must succeed.
     - Settings → Server shows "Login status is shown on this machine only".
     - Locally, `curl -X POST localhost:8790/api/pin -d '{"session":"x","pinned":false}'` (no Origin) → 200.
   - **H7.** Never test S1/S2 against a live permission prompt on real work.
6. **§4.6 step 4:** rename the test to `test_attached_login_ok.py` with the SF2 table, and note the `session` query and ownership requirement.

## Decisions the user must make

- **None new.** One choice follows from SF2. Hiding the button on `claude attach` panes also hides it on attach panes of *Anthropic* sessions, because an attach pane does not reveal its gateway. Recommendation: accept it, since a missing button is harmless. The user may overrule it, and the alternative is to leave case (iii) wrongly shown, as in v2.
- **Conditional (only if H1 shows a trust prompt):** the user's `~` cwd decision means every Settings click will face that prompt until `~` is trusted. Whether to trust the home folder once is the user's call, never the checker's.

---

Sources:
- [Cloudflare: origin parameters (`httpHostHeader`)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/origin-parameters/)
- [Cloudflare: local dev tunnels (Quick tunnel → `.trycloudflare.com` in allowedHosts)](https://developers.cloudflare.com/workers/local-development/local-dev-tunnels/)
- [Claude Code: interactive mode ("you switch accounts with `/login`")](https://code.claude.com/docs/en/interactive-mode)

---

## Closure check (v2.1)

Checked against `reports/claude-login-button.md` "plan v2.1" (732 lines) with `grep -n` and Read on line ranges. I assumed the planner's report was false.

**Result: 6 LANDED, 0 PARTIAL, 0 MISSING. 3 new nits.**

### Deltas

| # | Delta | Verdict | Where in v2.1 |
|---|---|---|---|
| 1 | §4.2 status subprocess: own session, group kill, bounded post-kill wait, lock with timeout, in-lock monotonic re-check, launcher guard, `subscriptionType` rule, `signal` import (SF1, N3, N4, N5) | **LANDED** | §4.2 :261, :281-331; tests in §4.6 step 2 :503-526 |
| 2 | §4.3 `login_ok` replaces `gateway`, both clients only render it, (iii) moved to hidden, (iv)/(v) restated (SF2, N2) | **LANDED** | §4.3 :366-417; tests in steps 4, 6 and 7 :535-581. grep finds no `launchGw`, `j.gateway` or `test_attached_gateway` |
| 3 | §4.1 `/api/tunnel/ctl` newly covered when a credential is in force, plus the red case (N1) | **LANDED** | §4.1 :227, :235; step 1 test :499 |
| 4 | §2 R4 settled, §4.7 fallback is port normalisation and never `X-Forwarded-Host`, rule-6 cross-site GET bound (N6, N7) | **LANDED** | R4 :141-145, §4.7 :625-629, step 9 :611 |
| 5 | §6 checklist (SF3) | **LANDED** | §6 :674-715 |
| 6 | Step 4 test renamed, with the `session` and ownership note | **LANDED** | §4.5 :473, §4.6 :535-550 |

### Step list

The parallel marks are real.

- Every step edits a different source file, except 1 and 3, which share `server.py`. That ordering is stated at :483.
- Test files are disjoint too: six new files and three distinct extended files.
- None of the six "new" test files exists yet (checked with `ls`).
- Every test can go red without a real login. Step 10 is a declared pin.
- Nothing contradicts the user's recorded decisions. The attach-pane consequence is surfaced as O2, not decided (:720).

### New defects (all nit)

**C1. §4.2 :295 writes `gateway.or_launcher()` inside `gateway.py`.**

1. **Defect.** `gateway.py` has no `gateway` name. Taken literally, this raises `NameError` on every status call that finds `claude`, in the package and in the bundle; the bundler rewrites only the `config.` and `tunnel.` prefixes (`scripts/bundle.py:45-49`). The `try/finally` releases the lock, but the route has no `try` around the call, so the handler thread dies and the Settings line shows a network error.
2. **Fix direction.** Call the module-level `or_launcher()` directly. Nothing else changes.
3. **The way.** Write `if exe == or_launcher()[0]:` in `claude_auth_status`. `mock.patch.object(gateway, "or_launcher", …)` still works, because the bare name resolves through module globals at call time.
4. **Test.** The existing step 2 N4 case (`which` and `or_launcher` return the same path → launcher error, no `Popen`) goes red with `NameError` if the prefix is written. No new test is needed.

**C2. The copied `update._run` shape drops its `OSError` branch.**

1. **Defect.** `update.py:69-70` returns an error when `Popen` raises `OSError`. The §4.2 :301-316 snippet has no such branch. Repro: `claude` is removed or made non-executable between `which` and `Popen` (or EACCES). The exception escapes `claude_auth_status`, and the handler crashes as in C1.
2. **Fix direction.** Treat it like any other failure: return and cache the generic error. Never include `str(e)`, which can contain a path.
3. **The way.** Wrap the `Popen(...)` call in `try: … except OSError: result = {available: True, logged_in: False, …, error: "couldn't read claude auth status"}`, then store it as usual.
4. **Test.** In `tests/test_claude_auth_status.py`, a fake `Popen` raising `OSError("x")` gives the generic error, with no `"x"` in `json.dumps(result)`. It is red against the :301 snippet, which raises.

**C3. A stale R4 line contradicts §6.**

1. **Defect.** §2 R4 :138 still says the trust prompt "is one Enter in the real terminal (human check H1)". §6 Setup :682 now says "Do NOT press Enter to trust `~`". A checker reading R4 first could accept the trust prompt.
2. **Fix direction.** Change the prose only.
3. **The way.** Replace the sentence with: "If it appears, do not accept it during checking (§6 Setup); whether to trust `~` is the user's call (§7 O3)."
4. **Test.** None (prose).
