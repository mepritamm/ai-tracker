# Claude Code login button: plan v2.1 (plan author: opus)

**Status: PLAN ONLY.** No product code, no tests, no commit.

- **Grounded against:** `personal/main` @ adeb6fa, in worktree `.claude/worktrees/pending-work-worker` (branch `claude-login-button`).
- **Installed CLI:** `2.1.325 (Claude Code)`.
- **v2 inputs:**
  - the adversarial review, `reports/claude-login-button-review.md`;
  - the main thread's hinge probe (2026-11-16);
  - the user's decisions (2026-11-16) below. Where these conflict with the review, the user's decisions win.
- **v2.1 inputs:** the re-review `reports/claude-login-button-review-v2.md` (0 blocker, SF1–SF3, N1–N7). All of its "Clean-plan deltas" are applied as written. See §5's reconciliation.

This plan supersedes `reports/login-in-settings.md` and `reports/login-in-settings-review.md`. Both now carry a SUPERSEDED header line, and nothing in them was implemented.

---

## 1. Contract (verbatim)

Original one-liner:

> "configure the login as well into the config settings itself"

The user's clarification, verbatim. Option "1" was a Login row in the Settings dialog (Server tab):

> "1(This login is basically the '/login' we do inside a claude code session to login to the Anthropic account which has the Claude plan running) + A Login button beside the terminal, which inside runs '/login' and the behavior is same like regular login"

The user's answer to every question about the dashboard password, verbatim:

> "Not applicable, this is a different login we are talkking about. NOT TRACKER AUTH login"

Standing instruction, verbatim:

> "everything happens with a button click instead of make command, the only command the user runs is first time with a make serve and then rest is managed by the app itself"

| # | Clause | Verdict |
|---|---|---|
| L1 | A Login control in Settings (Server tab) that performs Claude Code's `/login`, the Anthropic account login for the Claude plan | **not discharged** |
| L2 | A Login button beside the terminal that runs `/login` inside it | **not discharged** |
| L3 | Behaviour identical to the regular `/login`: nothing reimplemented or intercepted. It is the real Claude Code flow in a real terminal | **not discharged** |
| S | Standing: a button click, never a `make` command. No restart, no CLI step for the user | **not discharged** (no step asks the user to run anything) |
| N | Negative: NOT `TRACKER_AUTH`. Nothing touches dashboard auth | **not discharged**. Step 1 adds an Origin check *in front of* `/login` (the dashboard's own login route), but does not change what `TRACKER_AUTH` means or how it is set |

## User decisions (2026-11-16)

| Topic | The user's decision (verbatim, or as relayed) | What the plan does |
|---|---|---|
| Status line in Settings | "Show login status too" | It keeps a read-only status from `claude auth status --json`, using only `loggedIn`, `authMethod` and `subscriptionType`. Email, org and account ids never reach the page or a log. The result is cached server-side for 60 s; on-demand refresh is floored at 5 s. The call is never on the board poll, and it is open to local callers only (§4.2). |
| Log out / switch | "When the logged in, flip that button to a Switch account button" | The one Settings control is labelled **"Log in"** when the status says not logged in, and **"Switch account"** when logged in. Both run `/login` (§2 R3 cites the docs). There is no separate Log out button. |
| Login terminal folder | home folder (`~`) | `openAt('~', 'new', '/login', {gateway:'anthropic'})` |
| In-terminal button | "Anthropic sessions only" (the user chose this despite review S4) | It is shown only when the server says the PTY's app-launched command is plain `claude` (§4.3). The residual gap is stated in §4.3. |
| Remote use | allowed wherever terminals are allowed today (same gates) | No new gate. `term_gate.guard` and `/api/term/inject`'s guards apply as today. The status route stays local-only, like `/api/update`. |
| Warning | one line under the Settings control and in the in-terminal button's tooltip (machine-wide; a different login method signs out the existing claude.ai login) | The exact text is in §4.3 and §4.4. |
| Known gaps S1/S2 | document in README and the tooltip ("use when Claude is idle at its prompt"); no code | The README section is in step 9. The tooltip text is in §4.3. |
| NEW scope, same branch | "Yes, check Origin on every POST" | Step 1, §4.1 |

## User decisions, round 2 (2026-11-16, sign-off)

| Topic | The user's decision (verbatim) | What the plan does |
|---|---|---|
| Sign-off on v2.1 | "Approved, build it" | Implementation proceeds per §4.5 |
| Attach panes | "Yes, hide on attach panes" | `login_ok` is false for `claude attach` panes, including Anthropic ones (§4.3; O2 resolved) |
| In-terminal label | "Keep it as '/login'" | A static `/login` label in both views (§4.3; O1 resolved) |
| Trust prompt | "select yes when trust this folder pops up" | The main thread reads this as: **the user** answers yes at the folder-trust prompt for `~` during the human check. **The dashboard never answers prompts** (§6 H1; O3 resolved) |

---

## 2. Research (evidence)

### R1. Starting `/login` without typing it: SETTLED by probe

**Probe (main thread, 2026-11-16, Claude Code 2.1.325):**

- `claude "/status"` started in a PTY dispatched the slash command. The Status panel opened, and there was no model reply.
- `claude "/definitely-not-a-command-xyz"` showed `Unknown command: …` at startup.

The positional prompt therefore goes through slash-command dispatch, and **`claude "/login"` runs `/login`**. Review fallback (b) (inject after startup) is deleted.

Docs that agree:

- CLI reference (https://code.claude.com/docs/en/cli-reference): `claude "query"` *"Start interactive session with initial prompt"*.
- Commands page (https://code.claude.com/docs/en/commands): *"A command is only recognized at the start of your message."*

**Documented alternative, NOT built:** `claude auth login`. Installed help:

```
--claudeai  Use Claude subscription (default)
--console   Use Anthropic Console (API usage billing) instead of Claude subscription
--email <email>
--sso
```

It has no in-TUI method picker, so it is not `/login` behaviour. Keep it only as a note for the case where pasting into the TUI fails. The troubleshoot page says: *"use `claude auth login` instead, which reads the pasted code from standard input"*.

**What the flow needs from the terminal.** Sources: authentication docs (https://code.claude.com/docs/en/authentication) and the troubleshoot page (https://code.claude.com/docs/en/troubleshoot-install).

- *"Claude Code opens a browser window for you to log in"*
- *"press `c` to copy the login URL"*
- *"paste it into the terminal at the `Paste code here if prompted` prompt"*
- *"the terminal shows `Login successful` and prompts you to press `Enter`"*
- Remote: *"the browser may open on the wrong machine. Copy the URL displayed in the terminal and open it in your local browser instead."*

A remote viewer therefore selects the URL in the pane, signs in on their own device, and pastes the code back. Whether `c` reaches a remote viewer's clipboard (OSC 52) is not established.

### R2. Read-only status: `claude auth status`

The CLI reference says:

> `claude auth status` | Show authentication status as JSON. … Exits with code 0 if logged in, 1 if not. … The JSON's `authMethod` field is one of `none`, `claude.ai`, `oauth_token`, `api_key`, `api_key_helper`, or `third_party`

- **Key set observed** (values redacted at capture): `loggedIn, authMethod, apiProvider, analyticsDisabled, projectsDirectory, configDirectory, loginExpiresAt, consoleProfileSignInOffered, email, orgId, orgName, subscriptionType, storedClaudeAiLogin, planTier`.
- **Cost:** about 1.16 s wall time, 0.15 s user time (review S3). Most of it is waiting, probably on the keychain.

**Network: no socket observed, so not proven offline.**

- `claude auth status --help` lists only `--json` / `--text`, and the docs say nothing about network.
- Sampling `lsof -nP -a -p <pid> -i` every 0.05 s found **0 sockets in 3 of 3 runs** (exit 0). The review's own run found 0 in 1.
- Not established: whether the CLI refreshes a near-expiry token over the network during `auth status`. Treat it as possible.
- Hence the conventions rule-6 exception text in step 9 (§4.6).

### R3. `/login` while logged in; switching account; other sessions (corrected per review S5)

**Switching account is documented as `/login`.** The interactive-mode page (https://code.claude.com/docs/en/interactive-mode) says:

> *"The conversation changes hands: you switch accounts with `/login`, …"*

No better documented command exists. `claude auth logout`/`/logout` sign out, and `CLAUDE_CONFIG_DIR` keeps separate accounts side by side. So **"Switch account" runs `/login`**, the same as "Log in".

**Renew.** Authentication docs: *"Run `/login` to renew."*

**The login is machine-wide (per config dir).** Authentication docs, "Credential management":

> *"credentials are stored in the encrypted macOS Keychain … keys the macOS Keychain entry to that directory too, so a session with a different `CLAUDE_CONFIG_DIR` reads a different entry."*

**One picker choice signs out the subscription.** Authentication docs, "Sign in without an API key":

> *"What it signs you out of: Claude Code signs you out of any claude.ai login stored on the machine"*

**Other running sessions.**

- Errors page (https://code.claude.com/docs/en/errors), "Not logged in": *"If you sign in with your claude.ai account in another Claude Code window that uses the same configuration directory, an interactive session showing this message starts using that login on its own."*
- Troubleshoot page: *"Parallel sessions on one machine share a saved login and coordinate its renewal."*
- Errors page: *"Before v2.1.318, Claude Code removed the stored login during that sign-in, before saving the new one."* The installed 2.1.325 is newer than that.
- **Still not documented:** exactly what an already-running, logged-in session does when another window logs in to a *different* account.

### R4. Not established

- Whether the folder-trust prompt appears in `~`. That depends on `~/.claude.json`, which was deliberately not read. If it appears, **the user** answers it themselves; per round-2 decision, they select yes during human check H1. The dashboard never answers prompts (review v2 C3).
- OSC 52 behaviour of `c`.
- The exact env the user's OpenRouter launcher exports.
- ~~Whether `cloudflared` preserves `Host`.~~ **Settled (review v2, "Tunnel Host/Origin verdict"):** the origin receives the public hostname as `Host`.
  - `tunnel.py:210` passes no `--http-host-header`, and Cloudflare's origin parameters give `httpHostHeader` a default of `""`, i.e. no rewrite.
  - Cloudflare's quick-tunnel docs tell users to allow `.trycloudflare.com` hosts.
  - The repo's own cloudflared header fixture (`tests/test_term_launch.py:363-375`) carries `Host: some-name.trycloudflare.com`.
  - So `Origin: https://x.trycloudflare.com` matches `Host: x.trycloudflare.com`. No `X-Forwarded-Host` handling (it is forgeable). H6 is the live proof.

---

## 3. What exists, verified (file:line)

**Terminal launch: `POST /api/term/pty` → `term_vt.open_pty`** (`term_vt.py:2962`)

- For `mode == "new"` (`:3122`), `argv = [gateway.launcher(body gateway or config.GATEWAY)]`, then `_with_prompt` (`:2951`) appends `prompt`. `"/login"` passes the validation.
- The argv is typed into the folder shell by `_inject_argv` (`:1917`), which sets **`pt.cmd = " ".join(argv)`** (`:1967`).
- The body's `gateway` override already exists.

**`pt.cmd` is the server's record of what the app launched.**

- It is set at `:1967`, `:2531` and `:2651`.
- `_refresh_fg` resets it to the shell (`:1881`) once the job exits.
- `_term_title` (`:2136-2168`) already derives the gateway from it: `claude` → "Anthropic models", the OpenRouter launcher → "OpenRouter models", anything else → "Terminal". Its own docstring lists the known gaps (a)–(d), and its ponytail note reads "upgrade = store the gateway on Pty".

**Attached route:** `term_vt.attached` (`:4097`) returns only `{"claude_attached": bool}`, after `_refresh_fg(pt)` (`:4117`).

**Inject route:** `term_vt.inject` (`:4583`) takes `{tty, session, text, submit, clear_first, require_claude}`.

- Its guards are quiescence plus `_foreground_is_claude` (`:4030`, `:4666`). That is how `/model` and `/effort` are typed today: `ext_vt.js:2424/2446` and `ext_cr_term.js:988`.

**POST handling** (`server.py:626` `do_POST`), in order:

1. `/login` → `_do_login` (it is reachable unauthenticated);
2. `_authok`;
3. `_readonly`;
4. body parse;
5. the inline routes;
6. `EXTRA_POST` (`:937`).

**Origin helper:** `util.origin_matches_host` (`util.py:715`) is False only when `Origin` is present and its netloc differs from `Host`. `Origin: null` counts as different. It is already imported in `server.py:7`.

**SPA**

- **ContextBar** (`ext_vt.js:2192`), in the classic overlay (`:3054`) and in the standalone tab with a `sid` (`:4122`).
  - `.vtswitchers` (`:2228-2233`) holds model and effort. `effortWrap` is appended at `:2291`.
  - `_setAttached` is at `:2542` and early-returns when nothing changed.
  - The poll is at `:2573-2576`.
- **Control Room status bar** (`ext_cr_term.js:217-224`), with these hooks:
  - `el` map `:272-273`
  - `_onAction` `:292-310`
  - `_injectSlash` `:988`
  - `_syncStatusBar` `:1146-1151`
  - attached poll `:1213-1219`
- **Settings → Server tab** (`ext_cr_dialogs.js:1580-1594`). The patterns to copy are `schedulerBlock` (`:1173`) and `updateBlock` (`:1218`), with the helpers `crReadOnly` (`:1139`), `crCall` (`:1144`) and `crBtn` (`:1156`). The classic view has no Settings dialog.
- **`ExtLaunch.openAt(p, m, pr)`** (`ext_launch.js:380`) calls `pickDirectory` (`:319`), which opens a new browser tab. It has no way to pass `gateway` today.

---

## 4. Technical plan (v2.1)

### 4.1 Origin check on every POST (new scope, step 1)

**`aitracker/server.py` `do_POST`** (`:626`). Make this the **first** statement after `p = urlparse(self.path)`, before the `/login` branch:

```python
if not origin_matches_host(self.headers):      # CSRF, every POST incl. /login; absent Origin (CLI) passes
    return self._json({"error": "refused: cross-origin request"}, 403)
```

- The same rule applies with and without `TRACKER_AUTH`.
- GET is untouched.
- The helper allows a missing Origin, so `curl` and other CLI tools keep working.

**POST routes NEWLY covered** (no Origin check today):

- `/login`
- `/api/title`
- `/api/config` (every key; before this, only the `PENDING_CLEAN=safe` branch hit `_local_caller` at `:716`)
- `/api/tunnel` (a field write that includes `TUNNEL_USER`/`TUNNEL_PASS`)
- `/api/pin`
- `/api/model-keep`
- `/api/flags`
- `/api/flags/resolve`
- `/api/flags/delete`
- `/api/notes`
- `/api/notes/push`
- `/api/notes/next`
- `/api/notes/delete`
- `/api/tunnel/ctl`, **when a credential is in force** (`TRACKER_AUTH`, or a tunnel credential). `_tunnel_route_ok` (`server.py:354-360`) returns True as soon as `self._cred()` is truthy, so its Origin check runs only when there is no credential (review v2 N1). That makes 14 newly covered routes with a credential, 13 without.

**Already Origin-checked** (now checked twice, harmlessly):

| Routes | Existing check |
|---|---|
| `/api/update/fetch`, `/api/update/apply`, `/api/scheduler` | `_local_caller` |
| `/api/pending/run` | `_local_caller` (`:682`) |
| `/api/tunnel/ctl`, only when **no** credential is set | `_tunnel_route_ok` (`:776`) |
| `EXTRA_POST`: `/api/term/pty`, `/keys`, `/resize`, `/inject`, `/close` | `term_gate.guard` → `_origin_ok` (registered at `term_vt.py:4928-4932`) |
| `EXTRA_POST`: `/api/term/run`, `/kill` | `term_gate.guard` (`term_run.py:612-613`) |
| `EXTRA_POST`: `/api/term/open` | `_local_caller` (`term_launch.py:163`, `:229`) |

**Existing tests that post a cross-origin or `Origin: null` request:**

- `tests/test_local_host_routes.py:74-91`: `test_cross_origin_refused_everywhere` and `test_same_origin_and_absent_origin_allowed`.
- `tests/test_pending_routes_matrix.py:164-168` (`test_cross_origin_refused`, including `Origin: null`) and `:171-180` (`test_safe_delete_cannot_be_enabled_remotely`, cross-origin case).

All of them assert **status only**, which stays 403. Only the error text changes, now from the earlier check, and none asserts text. So none changes outcome.

`tests/test_term_gate*.py` and `tests/test_loopback_host.py` call `guard()` or the helper directly, so they are unaffected.

**One behaviour change to note:** a cross-origin POST without auth now gets **403 instead of 401**. A grep finds no test that relies on the 401.

**The SPA is unaffected:**

- Every `fetch` in `web/*.js` uses a relative URL (grep: no absolute or cross-host fetch).
- The login page posts by same-origin `fetch` (`server.py:83`, `doLogin`).
- Per-tab hostnames post to their own host (`tests/test_term_gate.py:205-209`).

### 4.2 Status route with server-side cache (step 2: gateway.py; step 3: server.py)

**`aitracker/gateway.py`**

Extend the import line (`:4`) to `import json, os, re, shlex, shutil, signal, subprocess, threading, time`. All of these are in the bundle HEADER (`scripts/bundle.py:21`).

```python
AUTH_TTL, AUTH_FRESH_FLOOR, AUTH_STATUS_TIMEOUT = 60, 5, 15     # seconds
_AUTH_CACHE = {"at": 0.0, "val": None}
_AUTH_LOCK = threading.Lock()
_AUTH_LABELS = {"claude.ai": "Claude subscription", "oauth_token": "CLAUDE_CODE_OAUTH_TOKEN",
                "api_key": "API key", "api_key_helper": "apiKeyHelper script",
                "third_party": "cloud provider", "none": "not logged in"}

def claude_auth_status(fresh=False):
    """-> {"available", "logged_in", "auth_method", "subscription", "label", "error"} built FRESH from
    three keys of `claude auth status --json` (loggedIn/authMethod/subscriptionType) -- never spreads
    the CLI's dict, so email/orgId/orgName/planTier/paths/expiry and any key the CLI adds later can't
    leak. Cached AUTH_TTL s; `fresh` re-runs only when the cache is >= AUTH_FRESH_FLOOR s old. One
    run at a time (_AUTH_LOCK: a concurrent caller waits and reads the result). Logs nothing."""
```

How it runs (v2.1: SF1, N3, N4, N5):

**Lock with a timeout (SF1).**

- `if not _AUTH_LOCK.acquire(timeout=AUTH_STATUS_TIMEOUT + 10): return {available: True, logged_in: False, ..., error: "claude auth status is busy — try again"}`. Wrap the body in `try/finally: _AUTH_LOCK.release()`.
- A stuck run can never hang later requests.

**Cache check inside the lock, on a monotonic clock (N3).**

- `age = time.monotonic() - _AUTH_CACHE["at"]`.
- If `_AUTH_CACHE["val"] is not None and (age < AUTH_FRESH_FLOOR or (not fresh and age < AUTH_TTL))`, return the cached value.
- Otherwise run. A waiter that got the lock therefore reads the result the first caller just stored.

**Executable guards (N4).**

- `exe = shutil.which("claude")`. If it is missing, the result is `{available: False, error: "claude not found on the server's PATH"}`.
- If `exe == or_launcher()[0]` (the bare module-level function: `gateway.py` has no `gateway` name, and the bundle does not rewrite that prefix; review v2 C1), the result is `{available: False, error: "claude on PATH is the OpenRouter launcher"}`, and no process is started.
- Both results are cached too.

**The run (SF1, the same shape as `update._run`, `update.py:62-80`; copied, so step 2 stays inside `gateway.py`).**

```python
try:
    p = subprocess.Popen([exe, "auth", "status", "--json"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, cwd=os.path.expanduser("~"),
                         start_new_session=True)      # own session: no controlling tty, own process group
except OSError:                                        # update.py:69-70's branch, kept (review v2 C2)
    -> generic "couldn't read claude auth status" result (never str(e): it can hold a path); cache it as usual
try:
    out, _err = p.communicate(timeout=AUTH_STATUS_TIMEOUT)
except subprocess.TimeoutExpired:
    try:
        os.killpg(p.pid, signal.SIGKILL)               # the whole group, not just the direct child
    except OSError:
        p.kill()
    try:
        p.communicate(timeout=5)                       # bounded post-kill wait
    except Exception:
        pass
    -> generic error
```

**Parsing.**

- `json.loads(out)` must yield a dict.
- On any failure, return the generic `error: "couldn't read claude auth status"`, never stdout or stderr.
- Exit code 1 means logged out. It still prints JSON, per the CLI reference.
- Store `{"at": time.monotonic(), "val": result}`.

**The label is composed server-side (rule 5; N5 spells out the transform).**

- `st = d.get("subscriptionType")`. It is used only if `isinstance(st, str) and re.fullmatch(r"[a-z0-9_]{1,24}", st)`.
- `authMethod == "claude.ai"` and `st` valid → `"Logged in · Claude " + st.replace("_", " ").title() + " subscription"`. So `"max"` gives "Logged in · Claude Max subscription".
- `authMethod == "claude.ai"` and `st` invalid → `"Logged in · Claude subscription"`.
- Any other method → `"Logged in · " + _AUTH_LABELS.get(m, "another credential")`. Never echo a raw unknown method string.
- Not logged in → `"Not logged in"`.

**Environment parity (N4), documented in README:** the status reflects the **server's** environment (non-login, no rc files). A terminal's `claude` runs in a login shell with rc exports, so the two can disagree.

**`aitracker/server.py`, step 3**

Extend `from .gateway import openrouter_configured` (`server.py:9`) with `claude_auth_status`. Then, in `do_GET`, next to `/api/update` (`:476`):

```python
elif p.path == "/api/claude/auth":
    # the machine's Claude Code login state: this machine only (never in _RO_GET_ALLOW)
    ok, err = _local_caller(self)
    if not ok:
        return self._json({"error": err}, 403)
    return self._json(claude_auth_status(fresh=parse_qs(p.query).get("fresh") == ["1"]))
```

**When it runs:**

- Only when Settings → Server renders, and on that block's window-`focus` refresh.
- Never on the 2 s/5 s polls, and never in `/api/list` or `/api/session`.
- At most one CLI run per 60 s, plus one per 5 s on explicit refresh.

### 4.3 In-terminal button (L2), Anthropic sessions only

**Signal (server-owned): the command the app itself launched on this PTY.**

- `pt.cmd` holds the argv the server typed or spawned (`claude …` or the OpenRouter launcher path).
- It is known at spawn time, before the first turn, so review S4's "no model id before the first turn" does not apply.
- It is reset to the shell when the job exits.

In `aitracker/term_vt.py`, step 4:

- **Add `_cmd_gateway(cmd, or_launcher)`**, placed above `_term_title` (`:2136`). It returns `gateway.OPENROUTER` when `cmd` is or starts with `or_launcher + " "`, or when its `shlex` argv[0] equals it. It returns `gateway.ANTHROPIC` when `basename(argv[0]) == "claude"`, and `""` otherwise.
- **Refactor `_term_title`** to call it for those two branches. The behaviour is identical, so its existing tests are the safety net. This is one shared seam, not a second copy of the rule.
- **Add `_login_ok(cmd, or_launcher)`** next to it (SF2). This is the whole server-side policy:

  ```python
  def _login_ok(cmd, or_launcher):
      try:
          argv = shlex.split(cmd or "")
      except ValueError:
          argv = (cmd or "").split()
      return _cmd_gateway(cmd, or_launcher) == gateway.ANTHROPIC and argv[1:2] != ["attach"]
  ```

- **`attached()`** (`:4097`):
  - compute `orl = gateway.or_launcher()[0]` *before* `_LOCK` (it does filesystem I/O, the same as `open_pty` at `:3132`);
  - under the lock, after `_refresh_fg`, read `lo = _login_ok(pt.cmd, orl)`;
  - outside the lock, `fa = _foreground_is_claude(pt.fd)`;
  - respond with `{"claude_attached": fa, "login_ok": fa and lo}`.
- **No `gateway` field is exposed;** nothing would consume it.
- `_term_title`'s output is unchanged. Its existing tests and its documented gap (a) stay as they are.

**Residual gap (stated plainly). The button is NOT shown in these cases:**

- (i) `claude` typed by hand into a plain-shell terminal: `pt.cmd` is still the shell. This is `_term_title` gap (c), and the conservative direction.
- (ii) Terminals whose app-launched job has exited and been replaced by a hand-typed `claude`.
- (iii) **Every `claude attach` retry pane** (moved here from "wrongly shown", SF2). `term_gate.attach_argv` (`term_gate.py:387-395`) always yields bare `claude attach <id>`, so an attach pane cannot reveal its gateway. **Consequence for sign-off:** the button is also hidden on attach panes of *Anthropic* sessions (§7 O2).

**The button IS wrongly shown in these cases:**

- (iv) A plain `claude` whose env or command was pointed elsewhere by the user's shell: rc-exported `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`, or an interactive-shell `alias claude=…`, which also applies to the line the app types (N2). This is undetectable without reading the process env, which this plan refuses to do because it holds secrets.
- (v) **For the whole life of a hand-typed job** that the user starts right after an app-launched `claude` exits, before any `_refresh_fg` call has seen the shell at its prompt (N2). `_refresh_fg` (`term_vt.py:1873-1881`) then only sets `fg_seen_child`, and `pt.cmd` keeps reading `claude …` until that job exits. No code change: tracking the job's pgid would be wider than the defect, and a wrongly shown button still does exactly what it says, the machine-wide `/login`.

**Classic view and standalone tab: `aitracker/web/ext_vt.js` ContextBar** (step 6)

- After `switchers.appendChild(effortWrap)` (`:2291`), append `<button type="button" class="vtmodelbtn vtloginbtn">/login</button>`. Use the same `mousedown` `preventDefault` as the model button, and on click call `self._login()`.
- Its tooltip (`title`) is the **TIP** string below.
- It renders the server's `login_ok` only (SF2, rule 5); no gateway logic lives in JS. Set `this._loginOk = false`.
- In the poll callback (`:2573-2576`):
  - success: `self._loginOk = !!(j && j.login_ok)`;
  - non-ok response and `.catch` branch: `self._loginOk = false`;
  - then call `self._syncLoginBtn()`. This is a separate call, because `_setAttached` early-returns when `attached` is unchanged.
- `_syncLoginBtn` sets `this.loginBtn.style.display = this._loginOk ? "" : "none"`.
- Add `ContextBar.prototype._login`, a copy of `_pickEffort` (`:2446`). It sends `{text:"/login", submit:true, clear_first:true, require_claude:true}`, and on failure toasts `"Couldn't start login"` plus the reason.

**Control Room: `aitracker/web/ext_cr_term.js`** (step 7)

- Markup `:221`: add `<button type="button" class="cr-term-pill cr-term-pill-login" data-action="login" hidden data-el="loginpill" title="TIP">/login</button>`.
- `el` map: add `loginPill`.
- `_onAction`: add `case "login": _injectSlash("/login", "Couldn't start login"); return;`.
- Attached poll `:1213-1219`:
  - success: `st.loginOk = !!(jj && jj.login_ok)`;
  - catch branch: `st.loginOk = false`.
- Reset `st.loginOk = false` alongside `st.attached = false` at `:436`.
- `_syncStatusBar`: set `el.loginPill.hidden = !st.loginOk;` (SF2: render only).

**TIP (tooltip), both views:** "Types /login into Claude Code. Use when Claude is idle at its prompt. Signs in for every Claude Code session on this machine — choosing a different login method signs out the existing claude.ai login."

**What is typed:** Ctrl+E Ctrl+U (the existing `clear_first`), then `/login`, then CR. These are the same bytes `/model` uses today.

### 4.4 Settings block (L1)

**`aitracker/web/ext_launch.js`** (step 5)

- Change `pickDirectory(raw, mode, prompt, opts)`.
- After `:331`, add `if (opts && (opts.gateway === "anthropic" || opts.gateway === "openrouter")) body.gateway = opts.gateway;`.
- Change `openAt: function (p, m, pr, o) { return pickDirectory(p, m, pr, o); }`.
- `app.js:2406` (the three-argument call) is unchanged.

**`aitracker/web/ext_cr_dialogs.js`** (step 8)

Add `function claudeLoginBlock()` after `updateBlock`. Mount it in the Server tab at `:1592`, **before** `updateBlock`. It returns `null` when `crReadOnly()`.

```
name: "Claude Code login (/login)"                                  (review N5)
sub lines:
  status:  r.status === 403 ? "Login status is shown on this machine only"     (N6)
           : msg || (st ? (st.error || st.label) : "Loading…")
  WARN:    "Signs in for every Claude Code session on this machine — choosing a different login method
            signs out the existing claude.ai login. Opens Claude Code's own /login in a new terminal tab."
control:   crBtn(st && st.logged_in ? "Switch account" : "Log in", login)   (both -> /login)
load(fresh): crCall("/api/claude/auth" + (fresh ? "?fresh=1" : "")) -> st / msg; paint()
login():   busy; ExtLaunch.openAt("~", "new", "/login", {gateway: "anthropic"}) -> {ok,error}
           -> msg = ok === false ? "Log in failed: " + error : ""
refresh:   window "focus" -> if (!document.body.contains(wrap)) remove listener; else load(true)
```

- Coming back from the login tab refocuses the dialog's tab, so the label flips once the login completes.
- No Refresh button.
- No CSS change: it reuses `cr-cfg-row` and `cr-btn`.
- `openAt`'s own error text covers terminals being off (403), the Host check and the 429 cap.

**Answers:**

- The tab opens and switches, through `window.open`, the same as pending Resume.
- The cwd is `~` (user decision).
- If `claude` is not on PATH:
  - the terminal shows the shell's own `command not found`;
  - the status says `claude not found on the server's PATH`.
- Through the tunnel:
  - the buttons follow the existing terminal gates;
  - the status line shows "shown on this machine only".

### 4.5 Steps (each file belongs to exactly one step, so the parallel marks are real)

| # | Step | Files | Test (red first) | Parallel |
|---|---|---|---|---|
| 1 | Origin check on every POST | `aitracker/server.py` (do_POST top) | **new** `tests/test_post_origin_guard.py` | ‖ A |
| 2 | `claude_auth_status()` + cache | `aitracker/gateway.py` | **new** `tests/test_claude_auth_status.py` | ‖ A |
| 3 | `GET /api/claude/auth` route | `aitracker/server.py` (do_GET) | **new** `tests/test_claude_auth_route.py` | after 1 (same file) and 2 (import) |
| 4 | `_cmd_gateway` + `_login_ok`; `attached` → `login_ok` | `aitracker/term_vt.py` | **new** `tests/test_attached_login_ok.py` | ‖ A |
| 5 | `openAt` opts `{gateway}` | `aitracker/web/ext_launch.js` | extend `tests/test_pending_ext_launch.py` | ‖ A |
| 6 | ContextBar `/login` button | `aitracker/web/ext_vt.js` | extend `tests/test_term_vt_exec.py` (`_CONTEXT_BAR_MOCKS`, `:1969`) | ‖ A |
| 7 | Control Room `/login` pill | `aitracker/web/ext_cr_term.js` | **new** `tests/test_cr_term_login_pill.py` | ‖ A |
| 8 | Settings "Claude Code login (/login)" block | `aitracker/web/ext_cr_dialogs.js` | **new** `tests/test_claude_login_settings_ui.py` | ‖ A |
| 9 | Docs: README known gaps + conventions rule-6 exception | `README.md`, `.claude/rules/conventions.md` | none (prose) | ‖ A |
| 10 | Pin test for the `/login` launch argv | test only | extend `tests/test_pending_pty_prompt.py` | ‖ A |
| 11 | Integrate: `make bundle`, gate, branch-sync, push; human checklist | `dist/tracker.py` (generated) | `unset TRACKER_AUTH; make check` → `selfcheck ok` | last |

- **Group A runs in parallel:** steps 1, 2, 4, 5, 6, 7, 8, 9 and 10.
- **File overlap, in full:** steps 1 and 3 both edit `aitracker/server.py`, so they are **ordered** (1, then 3). Step 3 also imports step 2's function.
- No other pair of steps shares a file, including test files.
- **Step 11** runs after everything.
- Steps 6, 7 and 8 code against the contracts in §4.2 and §4.3 with stubbed `fetch`, so they do not need steps 2–4 to run.
- **Every test above can go red without a real login.** They stub `Popen`, `which` and `fetch`, use fake ptys, and patch `_foreground_is_claude`. Step 9 is prose. Step 10 is a declared pin, which is not red-first.

### 4.6 Tests and docs per step (no real login, no real `claude` process)

**Step 1: `tests/test_post_origin_guard.py`**

Use a real `server.Server` on an ephemeral port, as `tests/test_local_host_routes.py` does.

- Run it for `AUTH in ("", "u:p")`.
- POST `/api/pin` and `/login` with `Origin: http://evil.example` and with `Origin: null` → **403** with `"cross-origin"` in the error. Today `/api/pin` gives 200 and `/login` gives 200/401, so this is red.
- The same POST with a matching `Origin` or with no Origin → not 403.
- A GET with a bad Origin → unchanged.
- N1 case: `/api/tunnel/ctl` with `AUTH="u:p"` and `Origin: http://evil.example` → 403, with `tunnel.stop` patched. This is red today; `tests/test_local_host_routes.py:104-114` shows it passes with a credential.

**Step 2: `tests/test_claude_auth_status.py`**

Patch `gateway.shutil.which`, `gateway.subprocess.Popen` (a fake with `pid` and `communicate`), `gateway.os.killpg`, `gateway.or_launcher` and `gateway.time.monotonic`.

- Logged in: the JSON includes sentinel values for `email`, `orgId`, `orgName`, `planTier`, `newIdField`. No sentinel may appear in `json.dumps(result)`, and the label must be right.
- Logged out: exit 1 with JSON.
- `which` returns None: `Popen` is never called.
- N4: `which` and `or_launcher()[0]` return the same path → the OpenRouter-launcher error, and `Popen` is never called.
- Non-JSON output or a list: a generic error, with no stdout or stderr text.
- C2: a fake `Popen` raising `OSError("x")` → the generic error, and no `"x"` anywhere in `json.dumps(result)`.
- argv is exact, with `stdin=DEVNULL`, `start_new_session=True` and `cwd` set to the home directory.
- **SF1, timeout:** the fake's first `communicate` raises `TimeoutExpired`. Assert:
  - `os.killpg` was called with `(fake.pid, signal.SIGKILL)`;
  - the second `communicate` got `timeout=5`;
  - the result is the generic error.
  - Red against v2's `subprocess.run` shape.
- **SF1, busy lock:** thread A holds the lock (its `communicate` blocks on an Event), with `AUTH_STATUS_TIMEOUT` patched small. Thread B returns the busy error and joins within the bound. Then release A.
- **N5 labels:**
  - `"max"` → "Logged in · Claude Max subscription";
  - `"<b>"` → "Logged in · Claude subscription";
  - an unknown `authMethod` → "Logged in · another credential".
- **Cache (on the patched `monotonic`):**
  - two calls within 60 s → one `Popen`;
  - `fresh=True` at 3 s → still one;
  - `fresh=True` at 6 s → two;
  - at 61 s → re-runs.
- **N3 concurrency:** two threads, **both `fresh=True`**, with `communicate` blocking on an Event → exactly one `Popen`.

**Step 3: `tests/test_claude_auth_route.py`**

- Loopback → 200 with the dict, with `claude_auth_status` patched.
- `?fresh=1` passes `fresh=True`.
- `X-Forwarded-For` → 403.
- The path is not in `server._RO_GET_ALLOW`.

**Step 4: `tests/test_attached_login_ok.py`**

- Use `_bare_pty` (`tests/test_term_vt.py:4055`) and `_FakeHandler` (`:680`), and patch `_foreground_is_claude`.
- **The query must carry `session` matching `pt.session`.** Otherwise `_req_session` returns 400 and `_pty_owned` gives a mismatch.

| `pt.cmd` | `login_ok` |
|---|---|
| `"claude /login"` | True |
| `"claude attach abcd"` | **False** |
| the launcher path (including one with a space) | False |
| `"/bin/zsh -l"` | False |
| any of the above with `_foreground_is_claude` patched False | False |

- Plus the `_term_title` parity cases (output unchanged).
- The response has no `gateway` key.
- Red: the `login_ok` key is absent.

**Step 5: extend `tests/test_pending_ext_launch.py`**

- `{gateway:"anthropic"}` is forwarded.
- A three-argument call sends no key.
- `"bedrock"` is dropped.

**Step 6: extend `tests/test_term_vt_exec.py`**

The button is visible only when the queue gives `{claude_attached:true, login_ok:true}`. It is hidden for:

- `login_ok:false`;
- `login_ok` missing;
- a non-ok response;
- a rejected fetch, which also clears an earlier `true`.

And:

- A `login_ok` flip with `attached` unchanged updates the button (the early-return trap).
- A click → exactly one inject with the exact body.
- `{ok:false}` → the toast.
- The `title` equals TIP.

**Step 7: `tests/test_cr_term_login_pill.py`** (review N1 recipe)

- Extract `_onAction`, `_injectSlash` and `_syncStatusBar` with `tests/test_cr_manage_terminals_parity.py`'s `_extract_function`.
- Stub `st`, `el` (`modelPill`, `effortPill`, `loginPill`, `primaryGroup`, `status`, `ctxreadout`), `post`, `j`, `showToast`, `window.ExtVT.ttyBody`, and run under node.
- `_onAction("login")` posts the exact inject body.
- The pill is hidden unless `st.loginOk`.
- The catch branch and the `:436` reset clear it.
- The markup `title` equals TIP.

**Step 8: `tests/test_claude_login_settings_ui.py`**

Use `test_update_settings_ui.py`'s harness.

- The block name is "Claude Code login (/login)".
- The WARN line includes "every Claude Code session on this machine".
- A logged-out body → button "Log in". A logged-in body → "Switch account".
- A click calls `openAt('~','new','/login',{gateway:'anthropic'})` once.
- `{ok:false,error:'X'}` → `Log in failed: X`.
- 403 → "Login status is shown on this machine only".
- `readOnly()` → no block.
- A window `focus` → a GET with `?fresh=1`.

**Step 9: docs (prose)**

- **README.md:** add a "Claude Code login" subsection under `## Terminal — on by default` (`:84`). It covers:
  - what both buttons do;
  - that the login is machine-wide;
  - the known gaps:
    - S1: an open permission prompt receives the Enter;
    - S2: a multi-line draft gets sent with `/login` appended;
    - N2: `/login` vs `/design-login` in the menu;
    - N3: a CR resend may pre-pick a method;
    - N4: session-less terminals have no button;
    - the §4.3 signal gaps, including attach panes hidden, (iv) aliases, and (v) lasting the hand-typed job's lifetime;
  - "status reflects the server's environment" (review v2 N4).
- **`.claude/rules/conventions.md` rule 6:** append this exception:

> *Exception: `GET /api/claude/auth` runs the user's own `claude auth status --json` (local callers only, cached 60 s, at most one run per 5 s on refresh). The dashboard opens no socket itself. Observed runs of the CLI opened none, but the CLI may contact Anthropic on its own (e.g. to refresh a login). That traffic is the CLI's, exactly like any `claude` launched in a dashboard terminal. A cross-site GET (for example an `<img>` pointing at the route) can trigger at most one run per 5 s. It cannot read the response, because there is no CORS.*

**Step 10: extend `tests/test_pending_pty_prompt.py`**

- With `config.GATEWAY="openrouter"`, `open_pty({"mode":"new","cwd":tmp,"gateway":"anthropic","prompt":"/login"})` types `claude /login` and never the launcher.
- This is a pin, not red-first: the behaviour exists. Say so in the commit.

**Step 11: gate**

- Use a >2 min timeout. Run one module per process if the run is OOM-killed. Remember the known flaky `term_vt` backstop.
- Load the page once, since the gate misses load-time JS errors. Eyeball phone width (`ext_vt.css:405`) with the third button.

### 4.7 Risky spots and fallbacks

**The Origin check refuses POSTs through the tunnel.** This is not expected (R4 is settled), and H6 is the live proof.

- **Fallback, only if H6 shows `refused: cross-origin` (review v2 N6):** normalise default ports in `util.origin_matches_host`. Compare the lowercased hostname plus the effective port on both sides, taking 80 for http and 443 for https when the port is omitted.
- **Never** honour `X-Forwarded-Host` (it is forgeable), and never exempt `via_tunnel` requests.
- **Fallback test:** `{"Origin":"https://x.trycloudflare.com","Host":"x.trycloudflare.com:443"}` → True. `{"Origin":"https://x.trycloudflare.com","Host":"y.trycloudflare.com"}` → False.

**The 1.2 s status call.**

- It is bounded by the cache and the floor.
- After SF1, a hung CLI costs at most one thread for `AUTH_STATUS_TIMEOUT + 5` s. Waiters give up after `AUTH_STATUS_TIMEOUT + 10` s with the busy error, instead of hanging.

**The in-terminal signal gaps** (§4.3). The user accepted Anthropic-only. All the gaps either hide the button or are bounded, documented cases.

---

## 5. Review verdicts (review of plan v1)

The main thread reconciled every finding. All 12 are confirmed; S3 and S4 are overridden by user decision.

| Finding | Verdict | Resolution in v2 |
|---|---|---|
| B1 | confirmed | The probe was run first and dispatch was proven (R1). Fallback (b) is deleted, and `claude auth login` stays a note only |
| S1 | confirmed | Documented: TIP plus README (step 9). No code |
| S2 | confirmed | Documented: TIP plus README. No code |
| S3 | confirmed; **overridden by user** ("Show login status too") | Status kept with mitigations: 60 s cache, 5 s refresh floor, one run at a time, local only, never polled, three-key allowlist plus sentinel test, rule-6 exception text |
| S4 | confirmed; **overridden by user** ("Anthropic sessions only") | The signal moved from the session model id to the server's launched command (`pt.cmd`, known before the first turn). Residual gaps listed in §4.3 |
| S5 | confirmed | R3 corrected. The WARN line goes in Settings and TIP, with no confirm dialog |
| N1 | confirmed | Step 7 uses the extract-and-stub recipe |
| N2 | confirmed | Human check H2, plus README |
| N3 | confirmed | Human check H2, plus README |
| N4 | confirmed | Documented as a scope gap in README |
| N5 | confirmed | Block name "Claude Code login (/login)" |
| N6 | confirmed | 403 → "Login status is shown on this machine only" |

## Reconciliation of review v2 (main thread, 2026-11-16)
Main-thread verdict: every finding CONFIRMED and accepted as the review designs it. SF1 — the status subprocess gets its own session, a process-group kill on timeout, a bounded post-kill wait (reuse the shape of `update._run`), and the cache lock is acquired with a timeout so a stuck call can never hang later requests. SF2 — the "Anthropic only" policy moves to the server: one `login_ok` boolean per terminal, computed server-side, false for attach panes and for anything not launched with the Anthropic `claude` launcher; both renderers only read it (conventions rule 5). SF3 — the human checklist is corrected (H1: do not accept the folder-trust prompt for `~` — press Esc; H4 rewritten so it can actually fail; H6 names the tunnel's own credential and covers TUNNEL_READONLY). Nits: as the review designs them. Tunnel Host/Origin: verified compatible (cloudflared forwards the public hostname as Host) — no X-Forwarded-Host change. Consequence to put to the user at sign-off, not decided here: hiding the button on attach panes also hides it on Anthropic attach panes.
| Id | Verdict | Note |
|---|---|---|
| SF1 | confirmed | §4.2: `Popen(start_new_session=True)`, `os.killpg(SIGKILL)` on timeout, a bounded 5 s post-kill `communicate` (the shape of `update._run`), and `_AUTH_LOCK.acquire(timeout=…)` with a busy error. Tests in §4.6 step 2 |
| SF2 | confirmed | §4.3: server-side `_login_ok`. `/api/term/attached` returns `login_ok` (no `gateway` field), false for `claude attach` and for non-Anthropic launches. Both views render it only. Test file renamed `test_attached_login_ok.py` |
| SF3 | confirmed | §6 replaced with the review's checklist: Esc at the method screen, never trust `~`, H4 with an OpenRouter *session* resume, H6 with the tunnel credential and `TUNNEL_READONLY` off, teardown after each check |
| N1 | confirmed | §4.1: `/api/tunnel/ctl` is newly covered when a credential is in force (14 routes with a credential). Red case added to step 1 |
| N2 | confirmed | §4.3: (v) lasts the hand-typed job's lifetime, and aliases are added to (iv). README text. No code |
| N3 | confirmed | §4.2: cache re-check inside the lock, on `time.monotonic`. Test: two threads, both `fresh=True`, one run |
| N4 | confirmed | §4.2: the `which("claude") == or_launcher` guard, and README "status reflects the server's environment" |
| N5 | confirmed | §4.2: `subscriptionType` charset `[a-z0-9_]{1,24}` and the label transform. Tests `"max"` and `"<b>"` |
| N6 | confirmed | §2 R4 settled by the tunnel evidence. §4.7 fallback = default-port normalisation, never `X-Forwarded-Host` |
| N7 | confirmed | The rule-6 exception text names the cross-site GET bound (one run per 5 s). No code |

## 6. Human-click checklist (only a real click proves these)

This is review v2 SF3's checklist, verbatim in substance. Each check can fail, and none of them logs in, trusts a folder or leaves a process behind.

**Setup**

- Use a logged-in machine.
- **At Claude's login-method screen, press Esc. Never pick a method.**
- **If the folder-trust prompt for `~` appears, the user selects yes** (round-2 decision). The dashboard never answers it. Record that it appeared.
- After each check, `/exit` and close the terminal from Manage terminals.

**H1. Settings → Server**

- The label reads "Switch account", and the status line shows no email or org.
- Click it. A new tab opens on `~`.
- **Select yes at the trust prompt for `~` if it appears; press Esc at the login-method screen.**
- The screen you reach must be Claude's login-method screen. It must not be a model reply, "Unknown command" or `/design-login`.
- Note any "Popup blocked" alert.

**H2. Classic overlay of an Anthropic session** ("Resume terminal here" on a session whose model is a Claude model)

- `/login` shows while Claude is in the foreground.
- Click it at an idle, empty prompt. The method screen waits for a choice.
- **Press Esc.**

**H3.** H2 again, in the Control Room terminal panel. **Press Esc** at the method screen.

**H4. The button is absent on:**

- (a) a plain-shell "Open terminal here";
- (b) "Resume terminal here" on a session whose model is an OpenRouter `vendor/model` id, in both views;
- (c) a `claude attach` pane, if one is reachable.

**H5.** After H1's Esc, return to the Settings tab. The status line re-reads on focus and still says "Switch account". No login took place.

**H6. Through the tunnel**

- Preconditions: `TUNNEL_READONLY` is off. Use the tunnel's share URL and **the tunnel's own credential**; `TRACKER_AUTH` is irrelevant here.
- Sign in to the dashboard, flag a session and change one config value. All three must succeed.
- Settings → Server shows "Login status is shown on this machine only".
- Locally, `curl -X POST localhost:8790/api/pin -d '{"session":"x","pinned":false}'` (no Origin) → 200.

**H7.** Never test S1/S2 against a live permission prompt on real work.

**H8. Tunnel login and POST**

- Open the dashboard through the tunnel with its credential, log in through the login page, then do one POST action (e.g. pin a session). Both must work (no "cross-origin" 403).

## 7. Open items (all resolved at sign-off, round 2)

- **O1, resolved:** the in-terminal label stays a static `/login` ("Keep it as '/login'").
- **O2, resolved:** the button is hidden on all `claude attach` panes, Anthropic ones included ("Yes, hide on attach panes").
- **O3, resolved:** the user selects yes at the `~` folder-trust prompt during the human check ("select yes when trust this folder pops up"). The dashboard never answers prompts.
- D1–D5 of v1 were closed by the first user-decisions table. **Nothing is open.**

---

## 8. Housekeeping done

- `reports/login-in-settings.md`, line 1: the `> SUPERSEDED 2026-11-16 …` line.
- `reports/login-in-settings-review.md`, line 1: the same line.
- Nothing else in either file changed.
