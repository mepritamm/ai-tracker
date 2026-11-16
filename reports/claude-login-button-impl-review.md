# Claude Code login button: adversarial implementation review (opus)

Scope: the uncommitted diff on `claude-login-button` (base personal/main `adeb6fa`) against
`reports/claude-login-button.md` §4 (plan v2.1), both "User decisions" tables and the reconciliation.
I assumed every implementer report was false. I read the code only: no tests, servers or `make`
were run, because a haiku agent was running the gate. I ran three probes: `node --check` on the four
changed JS files (all OK), `origin_matches_host` on tunnel-shaped headers, and
`claude auth status --json` for its key names only. Its shape matches the parser: `loggedIn`,
`authMethod`, `subscriptionType` (a string that passes the regex), plus `email`, `orgId`, `orgName`
and other keys that are never read.

**Verdict:** 0 blockers, 2 should-fix (both are proof gaps: the code paths are right, but the
guard is not proven), 10 nits. The build does what was signed off. I found no way for an
unauthorised caller to reach the new surface, and no path that leaks identity.

---

## Answers to the questions

### (a) End to end: Settings button → `/login` in `~`. **Yes.**

The chain:

1. `ext_cr_dialogs.js:1342` calls `ExtLaunch.openAt('~','new','/login',{gateway:'anthropic'})`.
2. `ext_launch.js:381` hands it to `pickDirectory`.
3. `pickDirectory` (`:330-332`) builds the body `{cwd:'~', mode:'new', prompt:'/login', gateway:'anthropic'}` and sends `POST /api/term/pty`.
4. `term_vt.open_pty`, session-less branch: `cwd = os.path.expanduser(raw_cwd.strip())` (`term_vt.py:3127`), then an `isdir` check (`:3128`). So `~` becomes the real home folder. It is neither a literal folder name nor refused.
5. `mode == "new"`: `gw = body.get("gateway")` (`:3140`), then `gateway.launcher("anthropic")`, which returns `"claude"` (`gateway.py:43-44`). `config.GATEWAY` is not consulted, so an OpenRouter default does not change the launcher.
6. `_with_prompt` (`:2968-2976`, `:3145`) appends `/login`, giving argv `["claude","/login"]`. The app types it into an idle `~` folder shell, or spawns it in an overflow pty when that shell is busy.

"Switch account" and "Log in" are the same button, built with the same `login` handler (`ext_cr_dialogs.js:1322`). Only the label differs.

Caveats:

- Nothing executes `claude /login` for real except the plan's R1 probe and the human check.
- No test proves step 5's override when the default is OpenRouter (SF1).

### (b) In-terminal buttons

- **The inject route honours `require_claude`:** it reads the flag at `term_vt.py:4669` and checks it at `:4686`, after the quiescence wait. A shell in the foreground gets `{"ok":false,"reason":"claude not in foreground"}` and receives nothing. Both senders set the flag: `ext_vt.js:2489` and `ext_cr_term.js:995`.
- **`login_ok` (`term_vt.py:2157-2160`) is false in each case asked about:**
  - **Attach panes.** `pt.cmd` is `"claude attach <id>"` (spawned at `:2626` and `:2668`), so `argv[1:2]==["attach"]`.
  - **`cwd`-mode shells.** `cmd` is the shell's argv, so its basename is not `claude`.
  - **OpenRouter.** The launcher is matched by prefix, or by an argv[0] equality test (`:2147-2153`).
  - **A hand-typed `claude`.** `pt.cmd` stays the shell (gap (i)). The documented gap (v) still applies.
- **`attached()` ANDs the flag with the foreground probe** (`:4142-4143`).
- **`/api/term/attached` is still refused for read-only visitors.** It is not in `_RO_GET_ALLOW` (`server.py:299-304`), so `:427` refuses it before `EXTRA_GET`, and `term_gate.guard` (`term_vt.py:4123`) applies as well.
- **Neither renderer re-derives the gateway.** Control Room reads `jj.login_ok` (`ext_cr_term.js:1224`). The classic view reads `j.claude_attached && j.login_ok` (`ext_vt.js:2620`), a redundant AND (N4).

### (c) Status

- **No identity can reach the page.**
  - The result is rebuilt from three keys, each checked against a regex (`gateway.py:160-173`).
  - Errors are static strings, never `str(e)`, stdout or stderr.
  - The route applies a second key whitelist (`server.py:243`, `:491`).
  - Labels are composed from fixed tables.
- **The status is never on a poll.** The only fetch is `ext_cr_dialogs.js:1329`, on render and on window focus.
- **Concurrent fresh requests run one CLI process.** `_AUTH_LOCK` serialises them, and the cache check inside the lock sees `age < AUTH_FRESH_FLOOR` (`gateway.py:149-152`). The test covers six threads.
- **The focus listener does not double-load.** Each render registers one listener. A stale one removes itself on the next focus, via `isConnected === false` (`:1348`), before it can load. Opening the dialog renders the Server tab twice (`:1824`, plus the re-render at `:1835` from `fetchServerConfig`), so it makes two non-fresh GETs. Both are served from the server cache. Bounded (N7).
- **An unavailable status still shows "Log in" and the button works.** The label falls back to `st && st.logged_in`, which is falsy for errors, 403s and fetch failures (`:1319`).

### (d) Origin check on every POST

- **No POST is reachable before the check.** `Handler` is the only request handler (`server.py:308`). There is no `do_PUT`, `do_DELETE`, `do_PATCH` or `handle_one_request` override.
- **`do_POST`'s first statement after `urlparse` is the check** (`:638-639`). `EXTRA_POST` is dispatched later, at `:949-950`.
- **Every registration found:**
  - `term_vt.py:4948-4952`: pty, keys, resize, inject, close
  - `term_run.py:612-613`: run, kill
  - `term_launch.py:229`: open
- **update, pending, scheduler and tunnel routes** are inline branches of `do_POST` (`:671`, `:693`, `:738`, `:780`).
- **The login page still works.** It posts by same-origin `fetch` (`server.py:91`), so its Origin is the page's own. No `Referrer-Policy` or `<meta name=referrer>` exists (grep), so browsers send a real Origin, not `null`. The SPA has no `sendBeacon` and no absolute URLs.
- **Through the tunnel,** the probe shows the result depends on whether the Host header carries a port, and on letter case:

  | Host header | Origin header | Result |
  |---|---|---|
  | `x.trycloudflare.com` | `https://x.trycloudflare.com` | allowed |
  | `x.trycloudflare.com:443` | `https://x.trycloudflare.com` | refused |
  | `X.trycloudflare.com` (different case) | `https://x.trycloudflare.com` | refused |

  Browsers omit the default port and lowercase the host in both headers, so this only bites if `cloudflared` rewrites Host. The terminal routes have used this same helper (`term_gate._origin_ok`) over the tunnel. The routes newly covered (`/login`, flags, notes, config, title, pin) have never been proven live through the tunnel (SF2).

### (e) Load order

- `page.py:17` loads the `ext_*` files sorted: `ext_cr_dialogs` < `ext_cr_term` < `ext_launch` < `ext_vt`.
- Every new cross-file reference is looked up at call time, not at load: `window.ExtLaunch` in dialogs; `window.ExtVT.ttyBody` already existed.
- `LOGIN_TIP` is defined inside `ext_vt.js`'s IIFE (`:2192`) before `ContextBar` uses it.
- `node --check` passes on all four files.
- The CSS edit only adds a selector to a rule, with no stray `*/`.

### (f) Bundle

- **No name collisions.** I grepped each new top-level name, and each appears only in its own module: `AUTH_*`, `_AUTH_*`, `_auth_result`, `_auth_run`, `claude_auth_status` in gateway.py, `_CLAUDE_AUTH_KEYS` in server.py.
- **`gateway.`-qualified calls in `term_vt.py` do not matter for the bundle.** `term_vt.py` is not bundled at all (see the comment at `scripts/bundle.py:70-80`, and ORDER at `:11-16`).
- **`gateway.py` calls the bare `or_launcher()`,** which survives flattening.
- **The HEADER (`bundle.py:21`) has every new import:** `json`, `re`, `signal`, `subprocess`, `threading`, `time`.
- **`dist/tracker.py` has not been regenerated yet.** That is step 11, not a defect.

### (g) Tests: does each one go red without its guard?

| Test | Red without its guard? | Notes |
|---|---|---|
| `test_post_origin_guard` | Yes | `/api/pin` cross-origin with no auth would return 200. `tunnel/ctl` with a credential would call `stop` |
| `test_claude_auth_status` | Yes | Allowlist (sentinels), lock (6 threads, 1 run), floor and TTL, group kill, OSError path |
| `test_claude_auth_route` | Yes | The whitelist test injects extra keys; refused callers assert the stub is never called |
| `test_attached_login_ok` | Yes | attach, launcher with a space, shell, and the foreground-false AND |
| `test_cr_term_login_pill` | Mostly | The executed parts are real. `test_reset_clears_login_ok` is a source regex (weak, acceptable) |
| `test_claude_login_settings_ui` | Mostly | The focus-listener cleanup is unprovable here: the fake `removeEventListener` is a no-op and `isConnected` is undefined in the fake DOM (N8) |
| `test_pending_ext_launch` additions | Yes | They check forwarding and refusal of a bad gateway |
| `test_pending_pty_prompt` `test_login_prompt_pin_anthropic_launcher` | **No: vacuous for the gateway** | `gateway.launcher` is mocked to return `"claude"`, so it passes even if `open_pty` ignored `body.gateway` (SF1) |
| `test_term_vt_exec` ContextBar additions | Yes | Visibility, flip-with-attached-unchanged, exact inject body, toast |
| `test_session_isolation` / `test_term_vt` edits | Yes | Count bump and shape update |

### (h) Built beyond the plan

All of these are harmless. Only N9 is worth a change.

- A distinct `available:false, "claude couldn't be started"` result for OSError. The plan said to use the generic "couldn't read" result.
- An `os.name == "nt"` branch, and an `AUTH_LOCK_EXTRA` constant.
- The `_cmd_argv` helper, with the Auggie branch moved onto it. I diffed it against HEAD's `_term_title`: the behaviour is identical.
- The classic view's client-side `claude_attached &&` (N4).
- Logged-in `auth_method` passes through any regex-valid method string. The logged-out branch filters to `_AUTH_LABELS` (N9).

---

## Findings

### SF1 (should-fix, test). No test proves `gateway:'anthropic'` beats an OpenRouter default

1. **Defect:** `tests/test_pending_pty_prompt.py:73-84` patches `term_vt.gateway.launcher` to return `"claude"` for the Anthropic case. Repro: delete `gw if gw in (...) else` at `term_vt.py:3142` so the line always uses `config.GATEWAY`. The test stays green. The signed-off decision ("plain `claude` launcher even when the default is OpenRouter") is unproven anywhere. `test_term_vt.py:6042-6088` only covers OpenRouter overrides and a bad value.
2. **Fix direction:** add a test. The code must not change: `open_pty`'s override is correct.
3. **The way:** in `OpenPtyRoutePrompt`, add a case with `mock.patch.object(config, "GATEWAY", "openrouter")` and `gateway.or_launcher` returning `("/opt/or/claude-or", "")`. Do not mock `launcher`. Post `{mode:"new", cwd, gateway:"anthropic", prompt:"/login"}` and assert `inj.call_args[0][1] == ["claude","/login"]`. Reuse `_open(body, or_launcher=...)`, which already skips the launcher mock.
4. **Test:** that case. It goes red if the override line falls back to `config.GATEWAY`.

### SF2 (should-fix, verify). The Origin check on the newly covered POSTs is unproven through the tunnel

1. **Defect:** `util.origin_matches_host` (`util.py:715-720`) compares `urlparse(Origin).netloc` with Host as exact strings. Repro (pure probe): Host `x.trycloudflare.com:443` with Origin `https://x.trycloudflare.com` gives False. Host differing only in case gives False. `/login`, `/api/flags`, `/api/notes*`, `/api/config` and the others were never Origin-checked through the tunnel before this change. If a proxy normalises Host differently, every tunnelled POST, including the dashboard login, now gets 403. The tests post only to `127.0.0.1`.
2. **Fix direction:** first prove it. Add a human-check line: through the tunnel, log in, then pin a session. Change code only if that fails. Do not loosen the `null` or mismatched-host refusal.
3. **The way:** in the human checklist §6, add "tunnel: dashboard login + one POST succeed". If it fails, normalise inside the one helper: lowercase both sides, and strip `:80` for http and `:443` for https. The fix stays in that function, so `term_gate._origin_ok` and `_local_caller` inherit it, and there is no second copy.
4. **Test:** add to `test_post_origin_guard` a unit test of the helper with `{"Host":"x.trycloudflare.com","Origin":"https://x.trycloudflare.com"}` (True) and with `evil.example` (False). Add the `:443` and case cases only if the normalisation is adopted. They are red before it.

### N1 (nit). `_login_ok` false negative when a `new` prompt starts with "attach"

1. **Defect:** `pt.cmd = " ".join(argv)` (`term_vt.py:1967`). A pending-Resume prompt such as "attach the logs and fix" makes `cmd` `claude attach the logs…`, so `argv[1:2]==["attach"]` and the button is hidden. Hiding is the conservative failure.
2. **Fix direction:** no change. Optionally tighten the check.
3. **The way:** require `len(argv) == 3` in `_login_ok`, to match `term_gate.attach_argv`'s exact shape. The ponytail upgrade (store the gateway and an attach flag on `Pty`) is wider than this defect.
4. **Test:** add the row `("claude attach the logs", True)` to `test_attached_login_ok.test_table` if the check is tightened.

### N2 (nit). Control Room fallback toasts for `/login` say "switch"

1. **Defect:** `ext_cr_term.js:1001` and `:1003` toast "the terminal didn't confirm the switch" and "the switch wasn't sent" for `/login` too. The classic view got login-specific text (`ext_vt.js:2495`, `:2498`).
2. **Fix direction:** make the wording neutral. Do not change the inject body.
3. **The way:** change both strings in `_injectSlash` to "the terminal didn't confirm it" and "the command wasn't sent". The function is shared by model, effort and login.
4. **Test:** extend `test_cr_term_login_pill`'s toast scenario with a reason-less non-ok reply, and assert the neutral text.

### N3 (nit). Stale docstring

1. **Defect:** `term_vt.py:4115` still says `-> {"claude_attached": bool}`.
2. **Fix direction:** add `"login_ok": bool`, with one clause on what makes it true.
3. **The way:** edit the docstring only.
4. **Test:** none (prose).

### N4 (nit). The classic view ANDs `claude_attached` in JS

1. **Defect:** `ext_vt.js:2620`: `!!(j && j.claude_attached && j.login_ok)`. The server already ANDs. This is harmless, but it re-derives policy (rule 5), and it differs from Control Room's render-only read.
2. **Fix direction:** read `j.login_ok` only.
3. **The way:** change that one expression.
4. **Test:** in `test_term_vt_exec`, add a case `resp(true,{claude_attached:false, login_ok:true})` that asserts the button is shown, matching CR's `shown_unattached`.

### N5 (nit). The Log in button when `claude` on PATH is the OpenRouter launcher

1. **Defect:** the status shows "claude on PATH is the OpenRouter launcher", but the button still types `claude /login`, which the shell resolves to that launcher.
2. **Fix direction:** no code change. The decision is that the button always works. Document it.
3. **The way:** add one bullet to the README "Known gaps" list.
4. **Test:** none.

### N6 (nit). The status tests patch the process-wide `time.monotonic` and `os.killpg`

1. **Defect:** `tests/test_claude_auth_status.py:52-54`. `gateway.time` is the `time` module, so the fake clock applies to every thread in the test process.
2. **Fix direction:** scope the patch to gateway.
3. **The way:** `mock.patch.object(gateway, "time", types.SimpleNamespace(monotonic=lambda: self.now[0]))`. Keep the `os.killpg` patch, because it has to intercept a real kill.
4. **Test:** the existing ones stay green.

### N7 (nit). Two status GETs on dialog open

1. **Defect:** the Server tab renders at `ext_cr_dialogs.js:1824`, then again at `:1835` after `fetchServerConfig`. That builds two blocks, sends two non-fresh GETs and leaves one stale listener. Both GETs are answered from the server cache, so at most one CLI run happens. `updateBlock` behaves the same way.
2. **Fix direction:** no change. It is bounded, and it is the existing pattern.
3. **The way:** none.
4. **Test:** none.

### N8 (nit). The focus-listener cleanup is untested

1. **Defect:** the harness stubs `removeEventListener` as a no-op, and its fake `El` has no `isConnected`. Deleting the self-removal at `:1348` stays green.
2. **Fix direction:** add a test.
3. **The way:** in `test_claude_login_settings_ui`, have `removeEventListener` record its calls. Close the dialog (`window.CR.dialogs.close()`), set `isConnected=false` on the detached block, fire focus, then assert one removal and no further `/api/claude/auth` GET.
4. **Test:** that scenario. It goes red without the `isConnected` branch.

### N9 (nit). A raw unknown `authMethod` reaches the page when logged in

1. **Defect:** `gateway.py:169` passes `method=m` for any regex-valid string. The logged-out branch (`:172`) filters to `_AUTH_LABELS`. It cannot identify anyone (the regex excludes `@` and `-`), but the two branches disagree.
2. **Fix direction:** filter both branches the same way.
3. **The way:** `method=m if m in _AUTH_LABELS else ""` on the logged-in branch too. The label is unchanged.
4. **Test:** in `test_labels`, assert that `auth_method == ""` for `authMethod:"weird"`.

### N10 (nit). README wording

1. **Defect:** the README says the terminal runs `claude "/login"`. What is typed is `claude /login`: `shlex.join` does not quote it.
2. **Fix direction:** match the README to the typed command.
3. **The way:** a one-word edit.
4. **Test:** none.

The popup-blocked path returns `{ok:true}` (`ext_launch.js:375-376`), so Settings shows no message. That is existing Resume behaviour, and I recommend no change.

## Not examined

- A real click or live `/login` (human checklist H1), or the trust prompt in `~`.
- Whether `claude auth status` spawned by the server can raise a macOS Keychain dialog. If it does, the run hangs until the 15 s timeout and the status reads "couldn't read".
- `cloudflared`'s live Host header.
- Visual and CSS rendering, and the xterm renderer.
- Results of the test run (the haiku agent owns it).
- The full prose of README and `conventions.md` beyond the diff.
- `server.py`, `term_vt.py` and `ext_vt.js` outside the cited ranges.

---

## Fix list (grouped by file)

- **`aitracker/term_vt.py`**
  - N3: `attached` docstring.
  - Optional N1: `len(argv)==3` in `_login_ok`.
- **`aitracker/gateway.py`**
  - N9: filter `auth_method` on the logged-in branch.
- **`aitracker/util.py`**
  - SF2: only if the live tunnel check fails, normalise case and default port in `origin_matches_host`.
- **`aitracker/web/ext_vt.js`**
  - N4: read `j.login_ok` only.
- **`aitracker/web/ext_cr_term.js`**
  - N2: neutral fallback strings in `_injectSlash`.
- **`README.md`**
  - N5: known-gap bullet.
  - N10: `claude /login`.
- **`reports/claude-login-button.md` §6**
  - SF2: human check "tunnel: login + one POST".
- **`tests/test_pending_pty_prompt.py`**
  - SF1: an OpenRouter-default case with no launcher mock, asserting `["claude","/login"]`.
- **`tests/test_post_origin_guard.py`**
  - SF2: a tunnel-shaped helper case.
- **`tests/test_attached_login_ok.py`**
  - N1 row, if tightened.
- **`tests/test_term_vt_exec.py`**
  - N4 case.
- **`tests/test_cr_term_login_pill.py`**
  - N2 case.
- **`tests/test_claude_login_settings_ui.py`**
  - N8 listener-removal scenario.
- **`tests/test_claude_auth_status.py`**
  - N6: scope the clock patch.
  - N9 assertion.
- **Integration (step 11):** `make bundle`, the gate, `/branch-sync`, push.

## Main-thread verdicts (2026-11-16)
| Id | Verdict | Ruling |
|---|---|---|
| SF1 | confirmed | Add a pin case with `config.GATEWAY = "openrouter"` (or however the default gateway is configured — read gateway.py) and NO launcher mock: `gateway:'anthropic'` must still give argv `["claude","/login"]`. Must go red when the override at term_vt.py ~:3142 is removed (show it with a temporary scoped Edit, restore, md5-check). |
| SF2 | confirmed — fix now (overrides "only if the live check fails") | In `util.origin_matches_host` only: compare scheme-aware normalised host:port — lowercase both, treat `https` origin without port == Host `:443` and `http` origin without port == Host `:80` (and the reverse). Nothing else loosens: `null` and any other mismatch stay refused; absent Origin stays allowed. Red test first with tunnel-shaped pairs (`Origin: https://abc.trycloudflare.com` vs `Host: abc.trycloudflare.com`, `abc.trycloudflare.com:443`, `ABC.trycloudflare.com`) and negative pairs (other host, other port, `null`, `http` origin vs `:443` Host). `term_gate._origin_ok` delegates — re-run its tests. |
| N1 | dropped | No defect shown; do not tighten `_login_ok`. |
| N2 | confirmed | Neutral fallback strings in ext_cr_term.js `_injectSlash` so `/login` failures never say "switch"; test in test_cr_term_login_pill.py. |
| N3 | confirmed | `attached()` docstring in term_vt.py states both keys and that `login_ok` implies `claude_attached`. |
| N4 | confirmed | ext_vt.js reads `j.login_ok` only (server owns policy; `login_ok` already implies attached); test in test_term_vt_exec.py. |
| N5, N10 | confirmed | README: the known-gap bullet the review names; the command shown as `claude /login`. |
| N6 | confirmed | Scope the clock patch in test_claude_auth_status.py so it cannot leak into other tests. |
| N8 | confirmed | Listener-removal scenario test in test_claude_login_settings_ui.py (reopening the dialog never double-registers the focus listener). |
| N9 | confirmed | gateway.py: filter/allowlist `auth_method` on the logged-in branch as the review designs; assertion in test_claude_auth_status.py. |
| N7 and any finding not listed above | as the review designs it, if it is in your group's files; otherwise report it. |
Missed by the review: none identified.
