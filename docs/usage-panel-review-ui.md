# Adversarial review — Auggie login, UI, Auggie cost, tests, sequencing

Reviewer scope: plan §2 (term_vt/UI/bundle rows), §3.3, §4, §5, §8, §9. Key storage, the OpenRouter socket, the
Claude `/usage` exec and the rule-6 texts are reviewed elsewhere and only touched where a test or the sequence depends on them.
Every cite was re-read in this worktree on 2026-11-18. Findings: **0 blocker, 4 major, 9 minor**.

## Major

### M1 — Auggie 1.3 keeps its sessions in `~/.augment/sessions-v2/`, so the planned cost source may always read $0 (§3.3 "month cost", F6)
- **Defect.** The plan sums `~/.augment/sessions/*.json` (config.py:103, auggie.py:319) and treats `sessions-v2/` as an empty probe artefact (F6). The installed 1.3 bundle names `sessions-v2` as its own session directory: `ble="sessions-v2"` and `function h2n(){return zv(Rr(),ble)}`, next to `auth.json`/`settings.json` in the same accessor block (`/opt/homebrew/lib/node_modules/@augmentcode/auggie/auggie-v2.mjs`, grep `ble="sessions-v2"`). The legacy `.augment/sessions` path (`ckt()`) is still used, but only by a conversation-import path (`NUe`). On disk, the newest legacy file is `modified 2026-09-16` (88 files). The 1.3 build is dated 2026-11-16.
- **Repro.** Use Auggie 1.3 this month, then call `GET /api/usage/auggie` → actual `cost_text "$0.00", sessions 0`. Expected: this month's spend, or an honest "not readable on this Auggie version".
- **Fix direction.** Do not build a `sessions-v2` reader inside this plan. It would be a provider capability (rule 4: both list and detail), and its shape is unknown (rule 7). Add probe 0(f) and make the card name its source. What must NOT change: the user-approved label "Local session cost, not account balance".
- **Way.** §9 step 0 gets (f): the user runs one short `auggie -p "say hi"` in a scratch dir. Record where the transcript lands (`find ~/.augment -newer <marker> -type f`) and its billing field names and types only. Outcome A, a file appears in `sessions/`: implement as planned. Outcome B, it lands in `sessions-v2/`: keep `month_cost` on the legacy dir, and have `accounts.auggie_usage()` add to `note` the fixed string "Reads Auggie sessions saved in ~/.augment/sessions; sessions from Auggie 1.3+ (~/.augment/sessions-v2) aren't read yet." Open a separate `/tracker-gap` item for a v2 reader. Either way, F6's text changes from "probably created by the probe" to "Auggie 1.3's session store (bundle constant `sessions-v2`)".
- **Test.** `tests/test_auggie_month_cost.py::test_note_names_source`: with an empty fixture dir, the `auggie_usage()["note"]` contains `~/.augment/sessions`. Red before the note change.

### M2 — The standalone bundle breaks on the new code paths, and the gate wouldn't notice (§2 `scripts/bundle.py`, `server.py` "Import `accounts`", §3.4 `accounts.invalidate(...)`)
- **Defect.** `scripts/bundle.py:46-55` (`strip_module`) drops every top-level `import`/`from`. It rewrites only the `config.` and `tunnel.` prefixes, and HEADER (bundle.py:18-22) imports `urllib.parse` but not `urllib.request`. Checked with the exact HEADER import line: `hasattr(urllib, "request")` is `False`. Two consequences in `dist/tracker.py`:
  - (a) the planned `from . import accounts` / `accounts.invalidate("openrouter")` / `accounts.claude_usage(...)` in server.py becomes a `NameError`;
  - (b) the planned `urllib.request.build_opener(_NoRedirect)` in accounts.py becomes an `AttributeError`.
  The gate's bundle tests (tests/test_integration.py:1803-1848) run only `--version`, `--help` and `--selfcheck`, so both errors pass the gate. The existing code imports names, not modules (server.py:9-16 `from .gateway import …`).
- **Repro.** `make bundle`, run `dist/tracker.py`, then `POST /api/config {"key":"OPENROUTER_API_KEY",…}` → 500 NameError. Expected: the same 200 as the package.
- **Fix direction.** Match the repo's import-by-name style and add the missing stdlib import to HEADER. Do not add another regex rewrite to `strip_module`.
- **Way.**
  - server.py: `from .accounts import claude_usage, openrouter_usage, auggie_auth_status, auggie_usage, usage_invalidate`.
  - accounts.py: `from .update import _run`, `from .gateway import claude_auth_status, or_launcher, openrouter_configured`, `from .providers.auggie import month_cost`, `from .store import _load_json`, `from .config import …` (or `config.X`, which is rewritten).
  - Rename `invalidate` to `usage_invalidate`: a generic name in a flat namespace is a future collision.
  - bundle.py HEADER: add `urllib.request, urllib.error` to the import line.
  - term_vt is not bundled, so its `accounts.` use is fine.
- **Test.** In `tests/test_integration.py`'s bundle class:
  - (1) `assertNotRegex(src, r"(?<![\w.])accounts\.")`;
  - (2) for each `rel` in `bundle.ORDER`, every top-level `import X[.Y]` of that module appears in HEADER's import line (parse both with `ast`);
  - (3) add `accounts.py` to the no-collision loop beside `agent_cli.py` (test_integration.py:1834-1841).
  (1) and (2) go red against the plan as written.

### M3 — Opening Config → Server makes an outbound call to openrouter.ai (§5 `openrouterKeyBlock`, D1)
- **Defect.** The key row reads `GET /api/usage/openrouter` to learn set/not-set (§5). When a key is saved, that route starts the `/api/v1/key` fetch whenever the cache is older than 300 s (§3.5). Server-tab renders happen for Port/Host/Update/Service reasons (ext_cr_dialogs.js:2031-2050), so viewing unrelated settings opens the dashboard's only outbound socket. The 6.3 text says the fetch runs only when the user reads usage.
- **Repro.** Key saved, cache cold. Open Config → Server → one HTTPS request to openrouter.ai. Expected: zero.
- **Fix direction.** The key row needs a no-network status. What must NOT change: the set flag never rides `/api/config` (F1), and the route stays local-only.
- **Way.** `GET /api/usage/openrouter?peek=1` returns `{"key_set": bool, "launcher_configured": bool}` from `_or_key()` and `gateway.openrouter_configured()` only. It never touches `_Bg`, and has the same `_local_caller` guard. `openrouterKeyBlock()` calls it with `?peek=1`. Only `usageBlock()` calls it without.
- **Test.** `tests/test_accounts_openrouter.py::test_peek_never_opens` (patch `accounts._open` and assert it is not called, key set). `tests/test_usage_ui.py`: the Server tab's GETs include `/api/usage/openrouter?peek=1` and never the bare path. Both are red before.

### M4 — Step 3 lands the usage-credits parser on an invented shape before probe 0(c) can confirm it (§3.2 credits row, §8 fixture B, §9)
- **Defect.** Fixture B (`monthly_limit 5000, used_credits 1234, utilization 24`) and the minor-units assumption (`m/100`) aren't from any probe. The only observed `extra_usage` is the disabled Max one (`monthly_limit: int = 10000`, handover:101-104), which can't tell cents from dollars. The §9 table puts all of step 3 after step 0, but 0(c) needs the user to switch accounts, and nothing says what proceeds if 0(c) is late. It's also unclear whether the credits account emits `usage_report` at all (§10 row 1).
- **Repro.** The credits account reports `monthly_limit: 50`, meaning $50 → the panel shows "$0.50". Expected: "$50.00".
- **Fix direction.** Fixture B must be copied from the 0(c) probe. The same run's plain-text line (the `/usage` text the probe already captures, handover:111-115) is the units oracle. Unblock everything that doesn't depend on it.
- **Way.** §9 step 0(c) also records the text report's usage-credits line, as amounts only. Step 3 splits:
  - 3a: `_Bg`, OpenRouter, Auggie auth, month_cost, and the Claude limits parser. These are unblocked by 0(a)/(b)/(d)/(e)/(f).
  - 3b: the credits branch and fixtures B/C. These wait for 0(c).
  Until 3b lands, `credits` is always `None`, so a disabled account renders correctly by construction. Currency formatting divides by 100 only for codes in a fixed two-decimal set (`{"USD","EUR","GBP","CAD","AUD"}`). Any other code → `text` "—" with no number.
- **Test.** Fixture B built from 0(c). `test_credits_units_match_text_report`: the parser's `text` equals the amounts in the captured text line, so it's red if the unit is wrong. `test_unknown_currency_no_guess` (`currency "JPY"` → no `/100` amount), red before.

## Minor

### m1 — The Auggie row inside `LOGIN_ARGV` plus `LOGIN_EXE` is wider than the need, and leaves a latent `claude auth login --headless` (§4)
- **Defect.** term_vt.py:3338-3342 prefixes every `LOGIN_ARGV` row with the Claude launcher whenever the gateway is Anthropic. Putting `("auggie", ("auth","login","--headless"))` in that table is safe only while the special Auggie `if` stays above `gateway.launcher` (:3333). A reorder spawns `claude auth login --headless`. `LOGIN_EXE` is a one-entry dict. The plan also edits a pinned test (tests/test_pending_pty_prompt.py:139-142) that has no need to change.
- **Fix/Way.**
  - Keep `LOGIN_ARGV` Claude-only.
  - Add `AUGGIE_LOGIN_PROMPT = "auggie auth login"` and `AUGGIE_LOGIN_ARGS = ("auth", "login", "--headless")`.
  - In the `mode == "new"` branch before `argv = [gateway.launcher(gw_eff)]`: `if isinstance(lp, str) and lp.strip() == AUGGIE_LOGIN_PROMPT: exe = shutil.which("auggie"); if not exe: return 400; argv, login = [exe, *AUGGIE_LOGIN_ARGS], "auggie"`. Then skip the launcher and row lookup with an `else:` around the existing code.
  - Drop `LOGIN_EXE`. In 6.4, "from the fixed table `term_vt.LOGIN_ARGV`" becomes "the fixed constant `term_vt.AUGGIE_LOGIN_ARGS`".
  - Drop the pinned-table edit from §8.
- **Test.** `test_auggie_login_pty.py::test_argv_is_auggie_on_every_gateway` (anthropic, openrouter without a launcher, None) → `spawned[0][0] == which("auggie")` and `"claude" not in spawned[0]`. The existing `test_login_argv_table_is_fixed` stays as it is.

### m2 — "Switch account" goes through an interactive reauth prompt, and the closing toast can claim a switch that didn't happen (§4, §5 `auggieLoginBlock`)
- **Defect.**
  - When a credential exists, `auggie auth login` asks `Continue with reauthentication? The saved local session will be replaced after success.` (fn `k3o`, auggie-v2.mjs:6359). Declining exits 0 with "Authentication was not changed.". The plan's help line doesn't mention it.
  - With no outcome record, the plan toasts from `auth status` alone. A declined or aborted switch while logged in toasts "Logged in", which reads as success.
- **Fix/Way.**
  - Help line: "...Switching asks you to confirm in the terminal (y), then opens your browser."
  - In `onDone(ended)`, toast only when `ended` (the pty exited by itself), with the neutral text `'Auggie: ' + body.label`, so it never says "switched". A manual close re-reads silently.
- **Test.** `test_usage_ui.py`: closing the modal by hand → no toast. Pty gone with status logged-in → toast text equals `'Auggie: ' + label`. Red before.

### m3 — The `auggie auth status` parse relies on the first stdout line (§3.3)
- **Defect.** The observed stdout is exactly `Logged in.\n`, rc 0, 1.6 s (measured here; `od -c`), so today's shape is fine. Any banner or notice written to stdout first would turn a good login into `error`. The env var named by `T3o` (an `AUGMENT_SESSION_AUTH`-style inline session) also makes status say "Logged in." without `session.json`.
- **Fix/Way.**
  - Rule: rc 0 and any stripped stdout line `== "Logged in."` → logged in. rc 1 and any line `== "Not logged in."` → logged out. Anything else → error.
  - Keep the exact equality (no prefix match).
  - Run with `env=_git_env()`. That's the existing default; don't add vars.
- **Test.** `test_auggie_auth.py`: stdout `"Update available\nLogged in.\n"` rc 0 → logged in, red with first-line parsing. `"Logged in as x"` → error. This keeps the plan's guard.

### m4 — Probe 0(d) looks in the wrong place (§9 step 0(d))
- **Defect.** It counts `~/.augment/sessions`. The observed side effects of the earlier probe were `~/.augment/auth.json` (created 15:07, mode 600) and `~/.augment/sessions-v2/<cwd-slug>/` (15:07). Run with the planned cwd `~`, status will create `sessions-v2/--Users-<you>--/`.
- **Fix/Way.** 0(d) becomes: `touch /tmp/m; (cd ~ && auggie auth status); find ~/.augment -newer /tmp/m`, recording names only. Its result feeds the 6.4 text, which the other reviewer owns.
- **Test.** None (probe).

### m5 — The proof that fixture A goes red uses the wrong mutation (§8 row 1)
- **Defect.** The guard reads "`is_enabled is not True` → credits None". Mutating it to `is not None` keeps A (`False is not None` → still None) green, and turns **B** red instead. Nothing proves the strict-`True` check either.
- **Fix/Way.** The mutation for A is "delete the `is_enabled` clause" (A renders credits → red). Add fixture A2 with `is_enabled: "true"` and A3 with `1`, both → `credits None`. Mutating `is not True` to `not …` turns A3 red.
- **Test.** As above.

### m6 — The 0600 test passes under a 077 umask whether or not the fix is in (§8 `test_openrouter_key_route.py`)
- **Defect.** "Revert `_save_json` mode (0600 red)" depends on the process umask. Under umask 077, the reverted `store._save_json` (store.py:27-31) still yields 600.
- **Fix/Way.** The test sets `old = os.umask(0o022)` and calls `addCleanup(os.umask, old)` before the second write.
- **Test.** The same test, now red on revert under any umask.

### m7 — `month_cost` cache key, sub-agent cost and duplicate parsing (§3.3 month cost)
- **Defect.**
  - The cache is keyed on `(path, mtime)` only. Tests or any caller with a different `since` get the previous window's sum.
  - `subAgentCostUsd` is a session-lifetime total (auggie.py:527-530), so a session spanning a month boundary counts its whole sub-agent spend in the new month.
  - Separately, a changed multi-MB file is `json.load`ed twice (`_AUGGIE_LIST_CACHE` in auggie.py:324-348 and the new cache). The largest observed file is 12.7 MB.
- **Fix/Way.**
  - Key the cache on `(path, mtime, since)`.
  - Read sub-agent cost through the existing `_sub_agent_usd(d)` (it already rejects str and bool).
  - Add to `note`: "sub-agent cost counts in the month the session was last active".
  - Accept the double parse. Merging into list_auggie's cache is wider than the defect.
- **Test.** `test_auggie_month_cost.py::test_since_change_recomputes`: same file, `since` = Nov 1 and then Oct 1 → different sums. Red with the plan's key.

### m8 — The key input's `autocomplete="off"` doesn't stop the browser's password manager, and failure handling is unspecified (§5 `openrouterKeyBlock`)
- **Fix/Way.**
  - Use `autocomplete="new-password"` and don't wrap the input in a `<form>`, so there's no submit and no save-password prompt.
  - On a 400, keep the input but clear it, and show the server's fixed error.
  - Never set `value` from any response.
- **Test.** `test_usage_ui.py`: the input's `autocomplete == "new-password"`; after a 400 response `input.value === ''` and the error text is shown.

### m9 — `at` mixes clocks, and there's no static check against HTML injection (§3.1, §5)
- **Defect.**
  - `_Bg` ages with `time.monotonic` (the §8 tests patch it), but `at` is displayed as an epoch. If `at` is stored from the same monotonic clock, the UI shows 1970.
  - `h()` (ext_cr_dialogs.js:39-58) is text-safe for strings, but its `html:` attribute goes through `innerHTML`. Nothing pins the new blocks to the safe path, and scope display names and labels are server strings.
- **Fix/Way.**
  - `_Bg` keeps `_t` (monotonic) for age and `at = int(time.time())` for display.
  - The usage, auggie-login and openrouter-key blocks use `h()` text children only.
- **Test.** `test_accounts_bg.py`: `abs(get()["at"] - time.time()) < 5` after a run. `test_usage_ui.py` static check: the three new functions' source contains no `html:` and no `innerHTML =` other than `= ''`. Run against a fixture limit whose label is `"<img src=x onerror=1>"`: the rendered text equals the literal and no `img` element exists.

## Verified OK
- `/api/term/pty` recognises a login prompt only on the Anthropic gateway: `LOGIN_ARGV.get(...) if gw_eff == gateway.ANTHROPIC` (term_vt.py:3338). The plan's Auggie branch has to sit before `gateway.launcher` (:3333). It does (§4).
- `_login_finished` stamps `last_login.json` for every login pty (term_vt.py:3650-3655), called from `Pty.finish` before `done` (:1669). The kind gate in the plan is needed and correct.
- `--headless` only sets fast-exit. `O3o`: `n=e.login.headless||!!…AUGMENT_LOGIN_FAST_EXIT` is at auggie-v2.mjs:**6359** (the plan cites 6361, which is where the `continue-interactive` return and `P3o` live). The same logic is repeated at :11606.
- The OAuth flow is unchanged under `--headless`: a loopback callback plus an attempt to open the browser on the server host, printing the URL as fallback. JSON paste happens only on SSH or Codespaces envs (`o3o`). The OAuth timeout is 600 s, under `LOGIN_WATCH_MAX` 1800 s (:3636), so the watch never pre-empts it. It works in a PTY.
- Logged-out status prints `Not logged in.` rc 1. A read failure goes to stderr as `Authentication status could not be read.` rc 1 (`P3o`). F4 is correct.
- Login ptys are hidden and never latched via truthy `p.login` (term_vt.py:2225, 2388, 4470), and `"auggie"` inherits that. No code compares `pt.login` to a specific kind except the planned gate.
- UI anchors: `sections` :1755, `renderSection` :1855, `claudeLoginBlock` :1624, `renderClaudeLogin` :1695 (the plan says :1694), Server branch :2031 with `loginEl` :2044. `crReadOnly` is at :1141.
- Polling stops on a tab change or close: `renderSection` sets `body.innerHTML = ''` (:1856), which detaches `wrap`, so `isConnected` goes false. The 60×3 s cap is 180 s, above `CLAUDE_USAGE_TIMEOUT` 150 s.
- `tests/test_agents_ui.py:28` (`'Terminal', 'Agents'` regex) still matches with `'Usage'` inserted after `'Agents'`. The claude-login node harness answers unknown URLs with `{}`, so new Server blocks don't break it. `test_closed_dialog_listener_removes_itself...` counts **all** `focus` listeners, so any focus listener in `auggieLoginBlock` has to self-remove the way claudeLoginBlock does (:1683-1688).
- auggie.py:607-610 sums `billing_metadata.cost_usd` per response node. `finishedAt` sits on each `chatHistory` item (:579), not on the exchange, as ISO with ms and a Z. It was present on 100% of the exchanges sampled. `cost_usd` is a str and `subAgentCostUsd` an int or float in all 5 newest files. The mtime skip is sound, because a file can't hold an exchange finished after its mtime.
- Copy sources exist: `test_claude_auth_status.py` (FakePopen), `test_claude_auth_route.py` (`_ServerCase` from test_cr_routes.py:169, `_RemotePeer` from test_pending_routes_matrix.py:49), `test_claude_login_settings_ui.py`, `test_agents_ui.py:79` (the field-fit test), and `test_pending_pty_prompt.py` (`_open` harness).
- CSS comment balance is already gated (tests/test_page_bundle.py:343), so a stray `*/` in `.cr-usage-*` goes red.
- Both Claude account fixtures (A Max/disabled, B enabled) and the key-never-leaks tests (route, opener, plist, environ, every GET) are listed in §8.
- `update._run(argv, timeout, env=None, cwd=None)` (update.py:63) matches the planned call shape.

## Clean plan deltas (Auggie/UI/tests)

1. **§0 F3:** change the cite to "auggie-v2.mjs:6359 (`O3o`), return at :6361". Add: "When already logged in, login first asks `Continue with reauthentication?` (y/N) in the terminal. The flow is loopback plus browser, and its 600 s timeout is under `LOGIN_WATCH_MAX`."
2. **§0 F6:** replace "probably created by the probe" with "Auggie 1.3's own session store (bundle constant `sessions-v2`). `auggie auth status` itself creates `sessions-v2/<cwd-slug>/` and wrote `~/.augment/auth.json`."
3. **§2:**
   - server.py row: "`from .accounts import claude_usage, openrouter_usage, auggie_auth_status, auggie_usage, usage_invalidate`".
   - accounts.py row: "imports by name (`from .update import _run`, `from .gateway import …`, `from .providers.auggie import month_cost`); `invalidate` → `usage_invalidate`".
   - bundle.py row: "+ HEADER imports `urllib.request, urllib.error`".
   - term_vt row: "`AUGGIE_LOGIN_PROMPT`/`AUGGIE_LOGIN_ARGS` constants; `LOGIN_ARGV` unchanged".
   - Remove the `test_pending_pty_prompt.py:139-142` edit.
4. **§3.1:** "`at` = `int(time.time())` at completion. Age uses `time.monotonic()`."
5. **§3.3:**
   - parse: "any stripped stdout line, exact equality".
   - month cost: "cache key `(path, mtime, since)`; sub-agent via `_sub_agent_usd`; note adds the sub-agent-month caveat. If 0(f) shows 1.3 writes `sessions-v2/`, the note adds the fixed 'sessions-v2 not read yet' sentence and a separate `/tracker-gap` item is opened."
6. **§3.5 / §3.6:** add `GET /api/usage/openrouter?peek=1` → `{key_set, launcher_configured}`. It makes no network call, never touches `_Bg`, and has the same guards.
7. **§3.2 credits (sequencing only):** "amounts divided by 100 only for currencies in a fixed two-decimal set, else '—'. Units are confirmed by 0(c)'s text line."
8. **§4:** replace the `LOGIN_ARGV`/`LOGIN_EXE` block with the separate-constant branch (m1). Keep `_login_finished`'s kind gate. Call `usage_invalidate`.
9. **§5:**
   - `auggieLoginBlock`: the help line mentions the y confirm. Toast only when the pty ended by itself, text `'Auggie: ' + label`. Any focus listener self-removes. Copy claudeLoginBlock's non-inline fallback (`tab` omitted when `ExtVT.mountInto` is missing).
   - `openrouterKeyBlock`: reads `?peek=1`. The input uses `autocomplete="new-password"` with no `<form>`, and is cleared on success and on failure.
   - All three blocks: `h()` text children only, no `html:`.
10. **§8:**
    - Fix the fixture-A mutation (m5) and add A2/A3.
    - B/C come from 0(c), plus `test_credits_units_match_text_report` and `test_unknown_currency_no_guess`.
    - Pin the umask in the 0600 test.
    - Add `test_since_change_recomputes`, `test_note_names_source`, `test_peek_never_opens`, the auggie-status banner case, `test_argv_is_auggie_on_every_gateway`, the UI no-`html:` and `<img>` literal check, the toast cases and the autocomplete check.
    - Add three bundle checks to `tests/test_integration.py`: no `accounts.` refs, every module import present in HEADER, and accounts.py in the collision loop.
11. **§9:**
    - Step 0: (d) becomes the `find ~/.augment -newer` diff run from `~`. Add (f), the Auggie 1.3 session-location probe run by the user. (c) also records the text report's usage-credits line.
    - Step 3 splits into 3a (`_Bg`, OpenRouter, Auggie auth, `month_cost`, Claude limits; needs 0(a)/(b)/(d)/(e)/(f)) and 3b (Claude credits + fixtures B/C; needs 0(c)).
    - Steps 1, 2 and 5 don't wait for any probe.
    - Step 7: drop the "`make bundle` smoke test" by hand. The new integration checks cover it in the gate.
