# Login terminal cleanup — durable plan file

Branch: `worktree-login-cleanup` (worktree `.claude/worktrees/login-cleanup`, base `personal/main` 418f132).

## Contract (verbatim, 2026-11-17)

> C1. "every login attempt is storing the terminal session in our managed terminal session from the home user"
> C2. "also for login, always select 'yes' to the trust this folder question itself"
> C3. "make sure that every login cache/terminal/overflow everything is removed/deleted once the login has been completed, however it can still show when the login has happened or was done last."

| Clause | Status |
|---|---|
| C1 login terminal not kept in Manage terminals / last_terms | implemented, pending review |
| C2 trust prompt auto-answered yes for login | implemented, pending review |
| C3 all login residue removed after completion; last-login time kept + shown | implemented, pending review |

## Findings (Explore, haiku)

- Spawn: `aitracker/term_vt.py` `open_pty()` :3130; login detection :3309-3316 (`lp.strip() == LOGIN_PROMPT` → `login_sid`, argv `claude --session-id <sid> /login`); cwd `~` from `web/ext_cr_dialogs.js:1654`. Always dedicated/overflow (:3350); `_spawn_dedicated()` :3516 sets `pt.spawned=login_sid`, `pt.overflow=True`; watcher thread :3545-3549.
- `_login_watch()` :3618-3654: polls `prov.login_transcript_state`, on "ok" feeds LOGIN_DONE_NOTE, settles, `stop_for_upgrade`, then `remove_login_transcript(sid)` once `pt.done`; clears sibling `spawned` latches. Never pops PTYS; `_reap()` :2384 drops overflow ptys only when done; `close_pty()` pops when done.
- Manage list: `term_list()` :4362 → `_live_list()` :2339 — no login filter. JS `ext_cr_term.js:746`, `ext_cr_dialogs.js` renderManageTerminals ~:2585.
- Persistence: `remember_terminals()` :4560 writes `last_terms.json` from `upgrade_candidates(light=True)` :4422 via `_entries` :4530 — no login filter, entries never removed. `remembered_terminals()` :4599 filters on transcript existence only.
- Trust: no auto-answer anywhere. `~/.claude.json` projects["/Users/pritammondal"].hasTrustDialogAccepted = False (home untrusted → prompt shown). Key injection exists (inject/keys routes ~:5683).
- Tests: `tests/test_login_session_cleanup.py` (LoginWatch :162…), `tests/test_pending_pty_prompt.py` :100-123, `tests/test_resume_pty_budget.py:150`, `tests/test_claude_login_settings_ui.py:162-214`, `tests/test_resume_all_record.py:178`.
- Governing rule: `.claude/rules/conventions.md` rule 6 "login-session cleanup" exception — any widened deletion must amend that text in the same commit.

## Plan (opus planner)

### 0. Evidence gathered (read-only)

- **`claude auth login` exists** (CLI 2.1.326, `~/.local/share/claude/versions/2.1.326`): `claude auth login [--claudeai (default) | --console | --sso | --email <e>]`. In the bundle it is a commander subcommand (`r.command("auth")…command("login")`) whose handler runs a readline flow: prints `Opening browser to sign in…` / `If the browser didn't open, visit: <url>`, sets the prompt `Paste code here if prompted > `, then on success writes `Login successful.` and `process.exit(0)`; any failure path `process.exit(1)` (SIGINT → 130). It never renders the REPL, so it has **no folder-trust dialog, no `--session-id`, no transcript, no `history.jsonl` line, no `session-env/<sid>/`, no `sessions/<pid>.json`**. It still needs a pty: the "paste code" fallback reads stdin when the localhost callback is unavailable. Supporting fact: the repo already runs the sibling `claude auth status --json` non-interactively from cwd `~` (`aitracker/gateway.py:107-137`) with no trust prompt.
- **Trust dialog (only relevant to the fallback)**: text `Quick safety check: Is this a project you created or one you trust? …`, options `Yes, I trust this folder` / `No, exit` (`cancelFirst:!0, focus:"cancel", hideIndexes:!0, typeAhead:!0`) — **default focus is "No, exit"**, digits don't select. Input is refused for `ND=150` ms after the dialog paints, and a refused key re-arms the guard. For `~` the CLI adds "This is your home folder, so Yes lasts for this session only." — so `hasTrustDialogAccepted` for home is never persisted by the CLI; writing it ourselves (option b) would be both a rule-6 violation and ineffective. Rejected.
- **What the current REPL `/login` leaves** (two past home logins, 2028e7c5…, e25c63ac…): `projects/-Users-pritammondal/<sid>.jsonl`, an empty `session-env/<sid>/`, a `history.jsonl` `/login` line (`display,pastedContents,project,sessionId,timestamp`), sometimes a sibling `projects/…/<sid>/custom-title.json`; 2028e7c5 is also a key in `aitracker/last_terms.json` and is offered by Resume all today (its transcript still exists, `remembered_terminals` :4638 only filters on existence).
- **Tracker-side state of a login pty**: `PTYS` entry + in-memory `Screen` (term_vt writes no scrollback/overflow file; its only file write is `last_terms.json` at :4613). Dropped from PTYS by `_reap` (:2384, overflow+done) or `close_pty` (:4267). `resolve_spawned` (:2235-2238) would latch ANY new `~` session onto a session-less `mode="new"` pty — the current code only escapes that because `pt.spawned=login_sid` is pre-set (:3573). `pt.rc` holds the exit status (:1650).

### 1. Approach

**Switch the Config login to `claude auth login`** (server-side argv swap; the wire contract `mode=new, gateway=anthropic, prompt="/login"` from `ext_cr_dialogs.js:1654` is unchanged). That discharges C2 by construction (no trust dialog exists on that path) and removes every `~/.claude` residue at the source (nothing to delete → the rule-6 deletion exception is **removed**, not widened). C1 is an explicit `Pty.login` flag filtered at the shared enumerations. C3's "show when it happened" is a new app-owned `last_login.json`, served on the existing `GET /api/claude/auth`.

| Clause | How |
|---|---|
| C1 | `pt.login=True`; excluded from `_live_list` (→ Manage terminals + 429 list), `upgrade_candidates` (→ last_terms recorder + agent upgrade), `resolve_spawned` (no latch). Legacy login transcripts filtered out of `remembered_terminals` (Resume all). |
| C2 | No REPL → no trust prompt. (Fallback §6 auto-answers it.) |
| C3 | Process exits by itself on success; watcher pops the pty from PTYS immediately (Screen freed), records `{at, outcome, ok_at}`; no transcript/session-env/history/pid file is ever created. Config shows "Last login: <ago>". |

### 2. Changes (files, signatures)

1. **`aitracker/config.py`** (after `LAST_TERMS_FILE` :66): `LAST_LOGIN_FILE = os.path.join(_HERE, "last_login.json")` with a comment "Config login outcomes {at, outcome, ok_at}; written only by term_vt._login_watch via store.record_login; read live".
2. **`aitracker/store.py`** (new, next to the other loaders):
   - `LOGIN_OUTCOMES = {"ok": "logged in", "failed": "login failed", "closed": "login cancelled", "timeout": "login timed out"}`
   - `def record_login(outcome, now=None) -> None` — `_update_json(config.LAST_LOGIN_FILE, mutate)`; mutate sets `d["at"]=now`, `d["outcome"]=outcome` (must be a key of LOGIN_OUTCOMES, else return False), and `d["ok_at"]=now` only when `outcome=="ok"` (a failed attempt keeps the previous `ok_at`). Never raises.
   - `def load_last_login() -> dict|None` — `_load_json(...)`; returns `{"at": float, "ok_at": float|None, "outcome": str, "label": LOGIN_OUTCOMES[outcome]}` only when the types validate, else None. Server owns the label (rule 5).
3. **`aitracker/term_vt.py`**
   - `Pty.__init__` (next to `self.overflow` ~:1470): `self.login = False  # a Config "Log in / Switch account" terminal (claude auth login): never listed, remembered, latched or resumed`.
   - `open_pty` :3315/:3331-3334: rename `login_sid` → `login = False`; in the LOGIN_PROMPT branch `login = True; argv = [argv[0], "auth", "login"]` (argv[0] is `gateway.launcher(ANTHROPIC)` = `"claude"`). Drop the `uuid` use there (keep the import if used elsewhere). :3378 `if login_sid:` → `if login:`; :3411-3412 pass `login=login`.
   - `_spawn_dedicated(spawn_cwd, argv, mode, sid, forked, cols, rows, held=False, login=False)` :3559: replace `pt.spawned = login_sid` with `pt.login = bool(login)` (set before `PTYS[pt.id] = pt`); thread `target=_login_watch, args=(pt,)`.
   - Constants :3623-3627: keep `LOGIN_PROMPT`, `LOGIN_WATCH_MAX = 1800.0`; `LOGIN_POLL = 0.5`; delete `LOGIN_SETTLE` and `LOGIN_DONE_NOTE`.
   - Replace `_login_watch(pt, sid)` :3630-3667 with `_login_watch(pt)`: loop `while not pt.done` sleeping `LOGIN_POLL`; at `LOGIN_WATCH_MAX` call `pt.kill()` once (its own process group only) and give up waiting after a further `CLOSE_CONFIRM_WAIT`; then `outcome = "ok" if pt.rc == 0 else "timeout" if killed_by_watch else "closed" if pt.closing else "failed"`; `store.record_login(outcome)`; `with _LOCK: if PTYS.get(pt.id) is pt: PTYS.pop(pt.id)`. Whole body in `try/except Exception: pass`. Deletes nothing; no `_provider()` use.
   - `_live_list` :2378: add `and not p.login` to the comprehension filter (one enumeration → Manage list and the 429 list). `_live_count()` is untouched, so the login pty still holds its slot.
   - `resolve_spawned` :2217-2219: `if p.done or p.login: continue`.
   - `upgrade_candidates` :4467: `panes = [p for p in PTYS.values() if not p.done and not p.closing and not p.login]` (keeps it out of last_terms AND the agent-upgrade restart list).
   - `remembered_terminals` :4648: after the existence filter, drop rows whose transcript is a legacy /login-only one: `c = _provider()` once; `if c is None or c.login_transcript_state(r["session"]) not in ("ok", "interrupted")`. Read-only; fixes the 2028e7c5 entry being offered today.
4. **`aitracker/providers/claude.py`**: delete `remove_login_transcript` :1382-1398 (now unreferenced). Keep `login_transcript_state` (used by the Resume-all filter).
5. **`aitracker/server.py`** `/api/claude/auth` :509-516: `body = {k: st.get(k) for k in _CLAUDE_AUTH_KEYS if k in st}; body["last_login"] = load_last_login(); return self._json(body)` (import `load_last_login` on the store import line :16). `_CLAUDE_AUTH_KEYS` unchanged (that whitelist is for the CLI dict).
6. **`aitracker/web/ext_cr_dialogs.js`** `claudeLoginBlock.paint` :1627-1634: when `loginSt && loginSt.last_login`, append `h('div', {class: 'cr-cfg-row-sub cr-claude-login-last'}, ['Last login: ' + (ll.ok_at ? timeAgo(ll.ok_at) : 'never') + (ll.outcome !== 'ok' ? ' · last attempt ' + timeAgo(ll.at) + ': ' + ll.label : '')])` (`timeAgo` already exists :2595, in the same IIFE — confirm scope; else use `window.CR`'s `relTime`). Change the warn text "Opens Claude Code’s own /login in a terminal window over this page." → "Opens `claude auth login` in a terminal window over this page; nothing of it is kept once it ends." Name `Claude Code login (/login)` stays (tests pin it).
7. **`.gitignore`**: add `last_login.json` and `last_login.json.lock`. **`tests/__init__.py`** :33-37: redirect `_config.LAST_LOGIN_FILE` to a temp dir exactly like `LAST_TERMS_FILE`.
8. **`.claude/rules/conventions.md`** rule 6: **delete** the "login-session cleanup" exception and insert the text in §4 (same commit). **`CLAUDE.md`** "App-owned state" line: append `last_login.json` (written by `store.record_login`).

No new dependency; no new route; no client-side policy (labels, outcomes, filtering are all server-side).

### 3. Sequencing

1. store/config/.gitignore/tests-init (pure, testable alone) → 2. term_vt flag + filters (C1, independent of the argv swap) → 3. argv swap + new watcher + delete `remove_login_transcript` (C2/C3) → 4. server route + SPA line → 5. conventions/CLAUDE.md text → 6. `make check` (one module per process if OOM, `unset TRACKER_AUTH;`) → 7. restart (`make serve`) and the manual probe in §5. Steps 2 and 3 land in the same commit as the rule-6 edit.

### 4. conventions.md rule-6 amendment (verbatim; replaces the whole "Exception (login-session cleanup, …)" paragraph)

> *Exception (Config login terminal, user-requested 2026-11-17: "every login attempt is storing the terminal session in our managed terminal session from the home user", "always select 'yes' to the trust this folder question", "make sure that every login cache/terminal/overflow everything is removed/deleted once the login has been completed, however it can still show when the login has happened or was done last"): when a `POST /api/term/pty` asks for `mode=new` on the Anthropic gateway with prompt exactly `/login` (what Config's Log in / Switch account sends), `aitracker/term_vt.py` runs `claude auth login` — never the `/login` REPL command, so there is no session id, no transcript and no folder-trust dialog — in a dedicated terminal marked `Pty.login`. That terminal is never listed by `_live_list` (Manage terminals, the 429 list), never latched by `resolve_spawned`, never offered to agent upgrade and never written to `last_terms.json`; `remembered_terminals` also hides any older session whose transcript is /login-only. Its `_login_watch()` thread — and only it — once the terminal is done (or after it SIGKILLed that terminal's own process group at `LOGIN_WATCH_MAX`), records the outcome in the app-owned `aitracker/last_login.json` (`at`, `outcome` ∈ ok/failed/closed/timeout, `ok_at`) through `store.record_login` and drops the pty from `PTYS`. It deletes and edits nothing under `~/.claude` (the CLI writes its own credentials). The in-terminal /login control is unchanged and is not covered by this exception.*

### 5. Tests (all must be RED on 418f132, proved by reverting the hunk)

| File | Test | Asserts | Red before because |
|---|---|---|---|
| `tests/test_pending_pty_prompt.py` | rewrite `_assert_dedicated_login` :74-87 | spawned argv `== ["claude","auth","login"]`; `pt.login is True`; `pt.spawned == ""`; `pt.overflow`; `watch.call_args[0] == (pt,)` | argv carries `--session-id` |
| `tests/test_login_session_cleanup.py` | replace class `LoginWatch` :162-300 (keep `LoginTranscriptState`, `VanishedTranscript`; delete `RemoveLoginTranscript`) with: `test_exit_zero_records_ok_and_drops_pty`, `test_failed_keeps_previous_ok_at`, `test_closed_records_closed`, `test_timeout_kills_own_group_and_records_timeout` (patch `Pty.kill` to set `done`, `rc=-9`), `test_never_deletes_a_login_transcript` (a /login-only jsonl in the temp PROJECTS survives), `test_raise_is_swallowed` | `last_login.json` content (temp `LAST_LOGIN_FILE`), `pt.id not in PTYS` | `_login_watch(pt)` signature / no record |
| same file, new class `LoginPtyHidden` | `test_live_list_hides_login_pty_but_count_keeps_slot`, `test_resolve_spawned_never_latches_login_pty` (fresh transcript in its cwd, provider stubbed as in `tests/test_resolve_spawned.py`), `test_upgrade_candidates_skip_login_pty` (`_foreground_is_claude` patched True) | row absent / `spawned==""` / no row | no filter exists |
| `tests/test_resume_all_record.py` | `test_t8_remembered_hides_login_only_transcripts` | an entry whose transcript is a /login-only success is dropped; a normal one stays | only existence is checked |
| `tests/test_store_last_login.py` (new, small) | `test_record_and_load_roundtrip`, `test_unknown_outcome_not_written`, `test_bad_shape_loads_none` | shape + server label | functions don't exist |
| `tests/test_claude_auth_route.py` | extend `test_no_identifying_key_in_body` :82-86 to `set(OK) | {"last_login"}`; new `test_last_login_rides_the_auth_body` | `last_login` present and only `{at, ok_at, outcome, label}` | key absent |
| `tests/test_claude_login_settings_ui.py` | `test_last_login_line_rendered` (auth body with `last_login`), `test_no_last_login_no_line` | text contains `Last login:`; absent when null | no line rendered |

Manual (step 7, needs the user, because it signs in for real): press Config → Log in; confirm no trust prompt, the window closes on success with the "Logged in" toast, `Last login: 0s ago` shows, the terminal never appears in Manage terminals, and — by listing names only — no new file in `~/.claude/projects/-Users-pritammondal/`, no new `~/.claude/session-env/*` dir, and no new `/login` line in `~/.claude/history.jsonl`.

### 6. Risky spot and fallback

**Risk:** the claim that `claude auth login` writes no transcript/session-env/history and shows no trust dialog is read from the minified bundle, not observed (running it would sign in / open a browser). Also its pty UX: the window auto-closes ~2 s after exit, so a *failure* message on screen is not readable — mitigated by the recorded `outcome` label ("login failed") shown in Config.
**Fallback (only if the manual probe shows a prompt or residue):** revert the argv to `claude --session-id <uuid> /login` (keep `pt.login`, filters, last-login record — they are argv-independent), and (a) in `_login_watch`, while `not pt.done`, read the rows of `pt.screen.grid` under `pt.lock`; when a row contains `Yes, I trust this folder` and the text has been on screen ≥ 0.5 s, `os.write(pt.fd, b"\x1b[B")`, sleep 0.3 s, `os.write(pt.fd, b"\r")`, once per dialog appearance (default focus is "No, exit", digits are disabled, keys within 150 ms are refused); (b) restore `remove_login_transcript` and widen rule 6 to also `os.rmdir` (empty only) `~/.claude/session-env/<that uuid>/` and remove `<config.PROJECTS>/<dir>/<that uuid>/` only if it holds nothing but `custom-title.json`; `history.jsonl` stays untouched (shared, append-only — not ours to rewrite).

### 7. Decisions for the user

- **D1 — login method.** `claude auth login` defaults to the Claude subscription (`--claudeai`); the REPL `/login` let you pick Console/API billing. Plan: subscription only (matches "Switch account" for a claude.ai user). Overrule → add a second "Log in with Console" button that sends a server-whitelisted `method: "console"` → `--console`.
- **D2 — legacy residue.** The two pre-existing home login sessions (2028e7c5…, e25c63ac…: jsonl, empty `session-env` dirs, one sibling dir, two `history.jsonl` lines, one `last_terms.json` key) are only *hidden* from Resume all by the plan; nothing deletes them. Overrule → delete them by hand once (no code, no new exception); the plan does not add a sweep.

## Adversarial review (opus reviewer)

Reviewed against worktree HEAD 418f132 and the installed CLI `~/.local/bin/claude -> ~/.local/share/claude/versions/2.1.326` (Bun-compiled Mach-O; JS grepped in place with `grep -a -b` + `dd`). No code edited, no login run.

### R0. Core claim: `claude auth login` makes no session/transcript/trust prompt. **CONFIRMED.**

- Registration (byte ~305105700): `r.command("auth")…command("login")` with `--email/--sso/--console/--claudeai` (+ hidden `--gateway-json`) → `import("chunk-n2fe6sbj.js").authLogin`. It is a commander subcommand.
- Root `preAction` (byte ~304953900, fn `D0i`): `let ee=E===r&&…; … Uys({…, preparesSession:ee, …})`. `E===r` is true only for the root command, so **no subcommand prepares a session**. The folder-trust dialog and the transcript, `history.jsonl`, `session-env/` and `sessions/<pid>.json` writes all belong to the root REPL path. `auth login` never reaches them.
- Handler (byte ~314636000): `Opening browser to sign in…` / `If the browser didn't open, visit: …` / prompt `Paste code here if prompted > `; on success `process.stdout.write("Login successful.\n")` → `process.exit(0)` (both the OAuth and the `CLAUDE_CODE_OAUTH_REFRESH_TOKEN` paths). Failures → `exit(1)`; readline SIGINT → `exit(130)`; `PasteInputClosedError` → `exit(130)`. A managed-settings Cloud-gateway machine (`mP()==="gateway"`) renders an Ink `Login` with no trust dialog and exits 0 or 1. It cannot apply here.
- Env: `_fork_child` (term_vt.py:1768-1783) gives the child the server's own environment, changing only `TERM/COLUMNS/LINES`, `strip_git_env` and `-CLAUDE_CODE_CHILD_SESSION`. `gateway.launcher(ANTHROPIC)` is bare `"claude"` (gateway.py:40-48). No ANTHROPIC_BASE_URL or CLAUDE_CONFIG_DIR is injected, so `auth login` sees exactly the env the REPL `/login` saw. `IX()` ("cannot run inside a Claude Code session") guards only `--gateway-json`.
- The live residue shows why creating nothing beats cleaning up afterwards: `2028e7c5…` classifies **"ok"** and `e25c63ac…` **"interrupted"** (`login_transcript_state`, run read-only). Both are still on disk although the current watcher should have deleted them. That watcher is a daemon thread and dies on every `make serve` restart. `2028e7c5…` is also 1 of 12 keys in the live `aitracker/last_terms.json`.

### Findings

**F1 — MEDIUM — A cancelled or failed *Switch account* now toasts "Logged in", and the outcome record races the modal's close.**
- Defect: `ext_cr_dialogs.js:1646` toasts when `announce && r.body.logged_in`. Today a failed REPL `/login` keeps its pty alive, so the modal never sees a 404 and never announces. `claude auth login` *exits* on failure (`exit 1/130`). `/api/term/attached` then 404s (term_vt.py:4910, `pt.done`), `onDone(true)` fires, then `load(true, true)`, then `logged_in` is still true for the OLD account, and the "Logged in" toast shows.
- Also: the plan records the outcome from a watcher that polls `pt.done` every `LOGIN_POLL` (0.5 s). The modal can see the 404 and fetch `/api/claude/auth` before `last_login.json` is written.
- Repro: logged in as A → Switch account → Ctrl-C in the terminal (rc 130) → expected: no "Logged in" and "login cancelled" shown. Actual: "Logged in · <A's label>".
- Direction: write the outcome **before** `done` can be observed, and have the SPA toast "Logged in" only on the server's `outcome == "ok"`. Must NOT change the `attached` 404 contract or the modal's poll.
- Way:
  - `Pty.finish()` (term_vt.py:1665, just before `self.done = True`): `if self.login: _login_finished(self)`.
  - New module function `_login_finished(pt)`: `try: store.record_login(_login_outcome(pt)) except Exception: pass`.
  - `_login_outcome(pt)`: `"ok"` if `pt.rc == 0`; else `"timeout"` if `pt.login_timed_out`; else `"closed"` if `pt.closing or pt.rc is None or pt.rc == 130 or pt.rc < 0`; else `"failed"`. This also fixes the plan's mapping, which reports Ctrl-C and late-reaped children as "login failed".
  - `Pty.__init__`: add `self.login_timed_out = False` next to `self.login`.
  - `_login_watch(pt)` keeps only the timeout: sleep until `pt.done` or `LOGIN_WATCH_MAX`, then `pt.login_timed_out = True; pt.kill()`. It no longer records anything (and see F3: no pop).
  - SPA `load()`: `var ll = r.body && r.body.last_login; if (announce && r.ok && ll) { if (ll.outcome === 'ok' && r.body.logged_in) toast({title: 'Logged in', meta: r.body.label || ''}); else toast({title: ll.label}); }`. The label is the server's, so rule 5 holds.
- Tests (red before):
  - `test_claude_login_settings_ui.py`: new `test_failed_switch_no_logged_in_toast` (authSeq `[_auth(True), dict(_auth(True), last_login={…outcome:'failed', label:'login failed'})]`, attachedSeq `[200,404]`): "Logged in" absent, "login failed" present. It is red today because the current code toasts whenever `logged_in` is true.
  - Update `test_pty_exit_after_login_toasts_once`'s second auth to carry `last_login.outcome='ok'`. This is an expected change.
  - `test_login_session_cleanup.py`: `test_finish_records_before_done`. Patch `store.record_login` to assert `pt.done is False` at call time, then call `pt.finish()` on a `login=True` Pty with rc 0. It is red against the plan's watcher-records design.

**F2 — MEDIUM — Hiding the login pty in `_live_list` while `_live_count` still counts it brings back the dead-end 429 the code forbids.**
- Defect: `_live_list` feeds both `term_list` (term_vt.py:4389) and the three 429 bodies (:3384, :3399, :3554). The comment at :3391-3398 exists precisely so the 429 never lists fewer holders than hold slots. With the plan, a login pty holds a slot (`_live_count`) but is listed nowhere. It is orphaned when the browser tab is closed with the modal open (`onClose` never POSTs `/api/term/close`). `claude auth login` produces no output, so it lives until the 30-min idle TTL.
- Repro: `MAX_TERMS=2`, one terminal open, an orphaned login pty → the next open gets a 429 that lists 1 row for 2 slots, and nothing can be closed.
- Direction: hide the login pty from `GET /api/term/list`, which is every Manage-terminals, tab-bar and poller consumer. Keep it in the 429 bodies so its slot can be reclaimed. Must NOT change `_live_count`.
- Way: `def _live_list(orl=None, hide_login=False)`. The comprehension filter becomes `if not p.done and not (hide_login and p.login)`. Only `term_list` passes `hide_login=True`. Optional, for honesty: add `"login": p.login` to the row so the 429 dialog can render the server's `title`; the title already reads "~ - Anthropic models - Claude Code".
- Tests (red before): `LoginPtyHidden.test_term_list_hides_login_pty` (no row in the `GET /api/term/list` body) and `test_429_lists_login_pty` (`MAX_TERMS=1` with a login pty → the 429 `terminals` holds its tty). The second is red under the plan as written.

**F3 — LOW (overbuilt) — The watcher's `PTYS.pop` duplicates `_reap`.**
- `_reap()` (term_vt.py:2390-2396) drops every `done and overflow` pty on the next route call, and the login modal's own 2-s `/api/term/attached` poll is one (:4903). `close_pty` already pops overflow ptys at once.
- Direction: delete the pop and the `_LOCK` section from the new `_login_watch`. Nothing else changes.
- Test: none new. `test_exit_zero_records_ok_and_drops_pty` becomes "…records ok, and the next `_reap()` drops it".

**F4 — LOW — The `_login_watch` mock signature in `tests/test_pending_pty_prompt.py:64-65` is missed.**
- `side_effect=lambda pt, sid: …` raises TypeError inside the watcher thread under the new `(pt)` signature, so `self._watched.wait(2)` fails with a confusing message. The plan rewrites only :74-87.
- Way: change it to `lambda pt: self._watched.set()` in the same edit as `_assert_dedicated_login`.

**F5 — LOW — Docs drift.**
- `README.md:127` still says `claude --session-id <uuid> /login` and "deletes that one /login-only session transcript". The Config warn's first sentence ("choosing a different login method signs out the existing claude.ai login") is stale under D1 subscription-only. The plan changes only the second sentence.
- Way:
  - Rewrite README:127's middle to: "runs `claude auth login` in its own dedicated terminal in `~`; Claude Code creates no session, transcript or trust prompt for it, the terminal is never listed in Manage terminals or remembered, and Config shows the last login time and outcome."
  - Warn text: "Signs in for every Claude Code session on this machine with your Claude subscription. Opens `claude auth login` in a terminal over this page; nothing of it is kept once it ends."
- Test: the existing `test_name_warning_and_logged_out_button` still pins "every Claude Code session on this machine". Keep that phrase.

**F6 — LOW (overbuilt rule text) — The proposed rule-6 paragraph is mostly not a data-safety exception.**
- About half of §4 restates listing filters (C1 behaviour, which is not a write or a network exception). Running `claude auth login` in a user-visible terminal on the user's click is the same as any `claude` launched in a dashboard terminal. The only new tracker write is an app-owned file, which belongs on CLAUDE.md's App-owned-state line.
- Direction: still DELETE the "Exception (login-session cleanup, …)" paragraph (conventions.md:23) in the same commit, and replace it with the short text below. It records what the tracker writes and what it never deletes, so nobody re-adds a transcript sweep:
  > *Config login terminal (user-requested 2026-11-17; supersedes the former login-session cleanup exception): Config's Log in / Switch account (`POST /api/term/pty`, `mode=new`, Anthropic gateway, prompt exactly `/login`) runs `claude auth login` — never the `/login` REPL command — in a dedicated terminal in `~`, so Claude Code creates no session, transcript or folder-trust prompt for it. For a login the tracker deletes and edits nothing under `~/.claude`; its only write is the outcome (`at`, `outcome`, `ok_at`) in the app-owned `aitracker/last_login.json` through `store.record_login`, and at `LOGIN_WATCH_MAX` it may SIGKILL that terminal's own process group.*

**F7 — LOW (decision change) — D2: the legacy residue does not satisfy C3, and the `remembered_terminals` filter is code for a one-time state.**
- C3 says every login cache and terminal is removed once the login has completed. Both legacy logins *have* completed ("ok" and "interrupted") and are still on disk. Hiding them leaves them.
- Under the new argv no new login transcript or `last_terms` key can ever appear. So the filter, and the `login_transcript_state` it keeps alive (with `LOGIN_MAX_BYTES` and `_LOGIN_OK_TYPES`), exists only for those two ids.
- Direction (recommended): a one-time **manual** cleanup by the main thread after the user OKs this exact list. No code, no rule-6 text:
  - `rm ~/.claude/projects/-Users-pritammondal/{2028e7c5-d85d-4a86-8227-0edc7c62ff42,e25c63ac-8139-4654-8a22-9becca7a4d79}.jsonl`
  - `rmdir ~/.claude/session-env/{2028e7c5-…,e25c63ac-…}` (both verified empty)
  - `rm -r ~/.claude/projects/-Users-pritammondal/e25c63ac-…/` (holds only `custom-title.json`)
  - Drop key `2028e7c5-…` from the primary checkout's `aitracker/last_terms.json` via `store._update_json` (flock-safe against the live server).
  - Leave `history.jsonl` alone: it is a shared append-only log, and 98 of its lines contain "/login" from many sessions.
- Then remove the plan's `remembered_terminals` filter, `login_transcript_state`, `LOGIN_MAX_BYTES`, `_LOGIN_OK_TYPES` and the `LoginTranscriptState`/`VanishedTranscript` test classes, together with `remove_login_transcript`. That is net code deleted.
- If the user would rather keep the files, keep the filter exactly as planned (its cost is bounded: `login_transcript_state` stats first and returns "other" above 256 KB).
- Test: none for the manual step; verify by listing names afterwards. If the filter is kept, the plan's `test_t8_remembered_hides_login_only_transcripts` stands.

**Examined, no finding**
- `upgrade_candidates` filter: correct and cheap. It also covers `agent_cli.py:312/567` (Doctor/Upgrade restart), and even without it a session-less login pty has `target ""` and `_entries` skips it.
- `resolve_spawned` `p.login` skip: needed. Without `pt.spawned` preset, a `mode="new"` login pty in `~` would latch the next `~` transcript.
- remember/flag race: none. `pt.login` is set before `PTYS[pt.id] = pt` (under `_LOCK`), and `spawn()` registers nothing.
- `_session_ptys` (sid-keyed) and `_folder_pty` (folder only) never match the login pty.
- The in-terminal `/login` pill cannot appear on it: `mountInto` builds no `ContextBar`, and the pty is hidden from the tab bar.
- `timeAgo` is in the same IIFE (`ext_cr_dialogs.js:2595`, takes seconds).
- `.gitignore` bare-name patterns cover `last_login.json(.lock)`.
- `store._update_json` is the flock'd RMW helper.
- `_CLAUDE_AUTH_KEYS` stays the CLI-dict whitelist.
- Rule 5 holds: the label and outcome are server-side, and the client only formats the time.

### Overall clean plan (plan §2–§5 with F1–F7 folded in)

1. **config/store/.gitignore/tests init.** As in plan §2.1, §2.2 and §2.7, with one fix: `record_login(outcome, now=None) -> bool`, which writes only a known outcome and never raises. Add `LOGIN_OUTCOMES = {"ok": "logged in", "failed": "login failed", "closed": "login cancelled", "timeout": "login timed out"}` and `load_last_login()` with the server label.
2. **term_vt, C1.**
   - `Pty.__init__`: `self.login = False; self.login_timed_out = False`.
   - `_live_list(orl=None, hide_login=False)`; only `term_list` passes `hide_login=True`. The 429 bodies still list the login pty (F2). `_live_count` is unchanged.
   - `resolve_spawned`: `if p.done or p.login: continue`.
   - `upgrade_candidates`: `… and not p.login`.
3. **term_vt, C2/C3.**
   - `open_pty` LOGIN_PROMPT branch: `login = True; argv = [argv[0], "auth", "login"]`.
   - `_spawn_dedicated(…, login=False)` sets `pt.login` before registering and starts `_login_watch(pt)`.
   - `Pty.finish()` calls `_login_finished(self)` just before `self.done = True`, and `_login_outcome(pt)` maps the exit as in F1.
   - `_login_watch(pt)` does the timeout kill only: no record, no pop (F1, F3).
   - Delete `LOGIN_SETTLE`, `LOGIN_DONE_NOTE` and the old watcher body. Keep `LOGIN_PROMPT`, `LOGIN_WATCH_MAX` and a `LOGIN_POLL`.
   - `providers/claude.py`: delete `remove_login_transcript`. Under F7's recommended D2, also delete `login_transcript_state`, `LOGIN_MAX_BYTES` and `_LOGIN_OK_TYPES`, and do NOT add the `remembered_terminals` filter.
4. **server + SPA.**
   - `/api/claude/auth` adds `last_login`, as in plan §2.5.
   - `claudeLoginBlock.paint` adds the "Last login: …" line, as in plan §2.6.
   - Use F5's warn text.
   - `load()` toasts "Logged in" only on `last_login.outcome === 'ok' && logged_in`, else the server's `last_login.label` (F1).
5. **Text.**
   - conventions.md rule 6: delete the login-session-cleanup exception and insert F6's short paragraph.
   - CLAUDE.md App-owned state: add `last_login.json` (written by `store.record_login`).
   - README:127 per F5.
6. **Tests.** Plan §5 changed as follows:
   - The `LoginWatch` replacement tests `Pty.finish()` recording: `test_finish_records_before_done`, the outcome mapping for rc 0/1/130/-9/None with `closing` and `login_timed_out`, and `test_timeout_kills_own_group` (patch `Pty.kill`).
   - `LoginPtyHidden` gets `test_term_list_hides_login_pty` and `test_429_lists_login_pty` in place of the `_live_list` one, and keeps the `resolve_spawned` and `upgrade_candidates` tests.
   - `test_pending_pty_prompt.py`: fix the :64-65 lambda and :74-87 (F4).
   - SPA: add `test_failed_switch_no_logged_in_toast`, update `test_pty_exit_after_login_toasts_once`, and add the two last-login line tests.
   - Keep the auth-route and store tests.
   - `test_t8_…` only if D2 keeps the filter.
   - Every new test is proved red by reverting its hunk.
7. **Gate and manual check.** `unset TRACKER_AUTH; make check` (one module per process if OOM). Then `make serve` and plan §5's manual probe, adding: cancel a Switch account → "login cancelled" shows, with no "Logged in" toast.
8. **D2 (if approved).** The F7 manual deletion list, run by the main thread, then a by-name listing to verify.

**Decisions after review:**
- D1 is unchanged (subscription-only; F5 fixes the text to match).
- **D2 flips:** the recommended default is now "delete the listed legacy residue once by hand with the user's OK, and drop the filter and the dead `login_transcript_state`". Keeping the files plus the filter becomes the overrule.
- **New D3 (from F2):** keep the login pty visible in the 429 slot list (recommended, reclaimable), or exempt it from `MAX_TERMS` entirely. Exempting it would need a one-login-at-a-time guard, which is more code.

## Reconciliation (main thread)

| # | Finding | Verdict | Why |
|---|---|---|---|
| core | `claude auth login` makes no session/transcript/trust prompt | confirmed | reviewer re-derived from the 2.1.326 bundle (subcommands skip `preparesSession`); still needs the manual post-merge check |
| F1 | cancelled Switch account would toast "Logged in" | confirmed | `web/ext_cr_dialogs.js:1646` toasts on `logged_in`, which stays true after a cancelled switch; record outcome in `Pty.finish()`, toast only on `outcome=="ok"` |
| F2 | hiding in `_live_list` while `_live_count` counts it → 429 lists fewer than the held slots | confirmed | `term_vt.py:1932` counts all non-done PTYS; hide only in `term_list` |
| F3 | watcher `PTYS.pop` duplicates `_reap` | confirmed (overbuilt) | drop it |
| F4 | `tests/test_pending_pty_prompt.py:64-65` mock signature | confirmed | mechanical |
| F5 | README:127 + Config warning text stale | confirmed | Config text currently says "Opens Claude Code's own /login" |
| F6 | rule-6 replacement text too long | confirmed (overbuilt) | use reviewer's short text; old exception deleted same commit |
| F7 | old residue left → C3 not met; `remembered_terminals` filter is code for a one-time state | confirmed | one-time manual delete (user OK), drop the filter + `login_transcript_state` |
| D3 | keep login pty in the 429 slot list | accepted as default | no MAX_TERMS exemption → no extra guard |
| missed by both | none found beyond the above | — | — |

Implementation = reviewer's overall clean plan above, with D1/D2 per the user's answer.

### User decisions

- D1 (sign-in method): **Add a Console button** (user, 2026-11-17) — second Config button runs `claude auth login --console`. Design change → plan revision + opus re-review below.
- D2 (one-time delete of old login residue): **Delete once now** (user, 2026-11-17) — exact paths listed to the user first; history.jsonl untouched; then drop the `remembered_terminals` filter + `login_transcript_state`.

## Revision for D1 (opus planner)

This is a delta on the reviewer's "Overall clean plan" (steps 1–8). Anything not named here is unchanged. Read-only evidence only: no code edited, no login run.

### D1.0 Evidence: `claude auth login --console` (CLI 2.1.326, `~/.local/share/claude/versions/2.1.326`, read with `grep -a -b` + `dd`)

- **Registration, byte 305105917.** `.option("--console","Use Anthropic Console (API usage billing) instead of Claude subscription").option("--claudeai","Use Claude subscription (default)")` sits on the same `Je.command("login")` as the default. Both reach the same `authLogin({…, console: L, claudeai: V, …})`.
- **Handler, bytes 314637218–314645094 (fn `Ni`).**
  - Only one flag combination is refused: `--console` together with `--claudeai` (`exit(1)`, byte 314637218).
  - Byte 314639108: `let x=Y?Y==="claudeai":!R`. Here `R` is `--console`, `x` is `loginWithClaudeAi` and `Y=mP()` is a managed `forcedLoginMethod`.
  - With `--console` and no managed setting, the run is the same readline OAuth flow as the default, with `loginWithClaudeAi:false` (byte 314642751, `startOAuthFlow(…,{loginWithClaudeAi:x,…})`). It shows the same `Opening browser to sign in…` / `Paste code here if prompted > ` lines.
  - It ends the same way as the default path: success prints `Login successful.` and calls `process.exit(0)`. Failures call `exit(1)`. Readline SIGINT or input ending before a code calls `exit(130)` (byte 314645094, `process.exit(o instanceof M?130:1)`).
  - The reviewer's R0 proof (subcommands never get `preparesSession`) does not depend on the flag. So, as with the default path, there is no session, transcript or folder-trust dialog.
- **Afterwards, `auth status --json`** (byte ~314646280): a Console login stores a `/login managed key`, which becomes `authMethod:"api_key"`. The existing `gateway._AUTH_LABELS` (gateway.py:96) then shows **"Logged in · API key"**. No new status label is needed.
- **Known gap (no change; document it in the PR).** On a machine whose managed settings set `forceLoginMethod`, the CLI ignores `--console` (`x` follows `Y`). If that setting is `gateway`, the command exits 1 instead. Neither applies to this machine. In both cases the recorded outcome and the status label report what really happened.

### D1.1 Wire contract: a fixed table; the request picks a key

- **Shape: a second fixed prompt value, sent on the existing route.**
  - The client sends `prompt: "/login --console"` instead of `"/login"`. Nothing else in the request changes: `mode=new`, `gateway:'anthropic'`, the `tab:false` inline flag, and `ExtLaunch.openAt` all stay as they are.
  - `web/ext_launch.js` builds the body from a whitelist (`cwd/cols/rows/mode/prompt/session/recreate/gateway`, :338-342), so it needs no change.
  - Rejected: a new body field `login_method`. It would mean editing `ext_launch.js`'s whitelist and adding a second selector beside the prompt.
- **`aitracker/term_vt.py`**, at the constants (:3623). It must be defined at module level before `open_pty` uses it at call time; it already is, because calls happen after import.
  ```python
  LOGIN_PROMPT = "/login"                       # unchanged; tests import it
  LOGIN_CONSOLE_PROMPT = "/login --console"
  # Config login: the request's prompt only SELECTS a row; argv is code-derived (conventions rule 6).
  LOGIN_ARGV = {LOGIN_PROMPT: ("claudeai", ("auth", "login")),
                LOGIN_CONSOLE_PROMPT: ("console", ("auth", "login", "--console"))}
  ```
- **The `open_pty` mode=new branch (:3330-3336) replaces the clean plan's step-3 bullet.**
  ```python
  lp = body.get("prompt")
  row = LOGIN_ARGV.get(lp.strip()) if gw_eff == gateway.ANTHROPIC and isinstance(lp, str) else None
  if row is not None:
      login = row[0]                              # "claudeai" | "console"
      argv = [argv[0]] + list(row[1])             # argv[0] = gateway.launcher(ANTHROPIC) = "claude"
  else:
      argv = _with_prompt(argv, lp)
  ```
  Here `login = ""` replaces `login_sid = ""` (:3315), and `if login:` replaces :3378. `_spawn_dedicated(…, login="")` sets `pt.login = login`.
- **`Pty.login` is a string**: `""`, or a method key from `LOGIN_ARGV`, instead of the clean plan's bool.
  - Every filter in clean-plan step 2 tests its truth value, so none of them changes: `not p.login` in `_live_list(hide_login)`, `resolve_spawned`, `upgrade_candidates`, and the `if self.login:` in `Pty.finish()`.
  - Nothing else is added to `Pty`.
- **Validators the value passes, and where it is accepted.**
  - **Accepted only on the Anthropic gateway.** On the effective Anthropic gateway (the `gateway` override, else `config.GATEWAY`), an exact match after `.strip()` gives a dedicated login pty. Nothing else does.
  - **Everywhere else it is an ordinary prompt.** A near miss (`"/login  --console"`, `"/login --sso"`) or the OpenRouter gateway falls through to `_with_prompt` (:3123). `_with_prompt` accepts it (≤4000 chars, no control characters, starts with `/`, not `-`) and passes it as the REPL's positional prompt. The `/login` value behaves the same way today, so the request can never add a flag to `auth login`.
  - **No other check sees it.** `mode=resume` uses `_with_prompt` only, never the table. `server.py` does not inspect `prompt`. The in-terminal `/login` pill (`ext_vt.js:2489`, the inject route) is a separate path and stays as it is.

### D1.2 Outcome record: yes, record the method (the label stays server-owned)

- **`store.py`, extending clean-plan step 1.**
  - Add `LOGIN_METHODS = {"claudeai": "Claude subscription", "console": "Console (API billing)"}`.
  - The signature becomes `record_login(outcome, method="claudeai", now=None) -> bool`. It writes `d["method"] = method` only when `method in LOGIN_METHODS`. If `method` is not in `LOGIN_METHODS`, it writes nothing and returns False, which mirrors the unknown-outcome rule.
  - `load_last_login()` also returns `"method"` and `"method_label"` (`LOGIN_METHODS[method]`). Both are `None` when the key is absent, so a file written before this change still loads.
- **`term_vt._login_finished(pt)`** becomes `store.record_login(_login_outcome(pt), pt.login)`.
- **The route whitelist grows.** The `last_login` keys are now `{at, ok_at, outcome, label, method, method_label}`. `/api/claude/auth` still adds the `last_login` body. `_CLAUDE_AUTH_KEYS` is unchanged.

### D1.3 Config UI (`web/ext_cr_dialogs.js` `claudeLoginBlock`, :1621-1667)

- **`paint()` (:1636-1640).** After `b`, append a second button to the same `ctl`:
  - `var bc = crBtn('Log in with Console (API)', function () { login('console'); });`
  - Its label is constant: it does not change with `logged_in`.
  - `if (busy) bc.setAttribute('disabled','disabled');`
  - The first button becomes `crBtn(…, function () { login('claudeai'); })`. Today it passes `login` itself, which receives the click event.
- **`login(method)` (:1649-1667).**
  - `var pr = method === 'console' ? '/login --console' : '/login';`
  - That value is passed to `L.openAt('~','new', pr, …)`. Everything else stays as it is: `busy` is shared, so one click disables both buttons; the same modal `open('claude-login', …)`; the same `onDone → load(true, ended)`.
  - The client knows only the two wire keys, never argv.
  - Rejected: serving the keys from the server. It is overbuilt for two fixed rows.
- **F1 toast logic.** It already covers both buttons, because it reads only `last_login.outcome` and `label`. There is no per-method branch.
- **Last-login line (plan §2.6).** The text becomes `'Last login: ' + (ll.ok_at ? timeAgo(ll.ok_at) : 'never') + (ll.method_label ? ' · ' + ll.method_label : '') + (ll.outcome !== 'ok' ? ' · last attempt ' + timeAgo(ll.at) + ': ' + ll.label : '')`.
  - Caveat: `method` is the method of the **latest attempt**. Showing it next to `ok_at` is accurate only when the latest attempt succeeded. This is accepted: a failed attempt also shows its own "last attempt" suffix.
- **Warn text.** This replaces F5's text, keeping the pinned phrase: "Signs in for every Claude Code session on this machine. Log in uses your Claude subscription; Console uses Anthropic Console API billing, and switching method replaces the current login. Opens `claude auth login` in a terminal over this page; nothing of it is kept once it ends."
- **Kept as is.** The name `Claude Code login (/login)` stays, and so does the :1622 comment's wording, which says "runs `claude auth login` (or `--console`)".

### D1.4 Tests (each new one is red on 418f132; prove it by reverting its hunk)

| File | Test | Asserts | Red before because |
|---|---|---|---|
| `tests/test_pending_pty_prompt.py` | `test_console_login_prompt_spawns_console_argv` | body `{mode:new, gateway:anthropic, prompt:"/login --console"}` → `inj.assert_not_called()`; `self.spawned == [["claude","auth","login","--console"]]`; `pt.login == "console"`; overflow | today the value goes to `_with_prompt` and is injected into the folder shell |
| same | `test_login_argv_table_is_fixed` | `term_vt.LOGIN_ARGV == {"/login": ("claudeai", ("auth","login")), "/login --console": ("console", ("auth","login","--console"))}` | no attribute |
| same | `test_console_prompt_off_anthropic_or_near_miss_is_plain` (guard; green before and after) | openrouter + `"/login --console"` → `inj` argv `["/opt/or/claude-or","/login --console"]`; anthropic + `"/login --sso"` → injected, `self.spawned == []` | — (pins "only there") |
| same | update `_assert_dedicated_login` (clean-plan F4 edit) | `pt.login == "claudeai"` instead of `is True` | expected change |
| `tests/test_login_session_cleanup.py` | `test_finish_records_console_method` | a Pty with `login="console"` and rc 0, then `finish()` → `last_login.json` has `method == "console"` and `outcome == "ok"` | no record / no method |
| `tests/test_store_last_login.py` | `test_unknown_method_not_written`, `test_method_label_server_side`, `test_legacy_file_without_method_loads` | returns False and the file is unchanged; `method_label == "Console (API billing)"`; `method is None` and the rest is valid | functions don't exist |
| `tests/test_claude_auth_route.py` | `test_last_login_rides_the_auth_body` key set | `{at, ok_at, outcome, label, method, method_label}` | key absent |
| `tests/test_claude_login_settings_ui.py` | harness: `SCEN.clickIdx` (default 0) at :83; `btnDisabled` at :101 returns both buttons' disabled flags | — | — |
| same | `test_console_button_opens_console_login` | `buttons == ["Log in","Log in with Console (API)"]`; clicking index 1 → `opens == [["~","new","/login --console",{"gateway":"anthropic"}]]` | there is no second button |
| same | `test_busy_disables_both_buttons` | after the click (vt), both buttons are disabled | no second button |
| same | `test_last_login_line_names_method` | auth `last_login` with `method_label:"Console (API billing)"` → the line contains `Console (API billing)` | no line |
| same | update `buttons` in `test_name_warning_and_logged_out_button` :154, `test_logged_in_shows_switch_account` :160, `test_unknown_status_offers_log_in` :249 and `test_focus_refetches_fresh` :272 to include `"Log in with Console (API)"` | — | expected change |

### D1.5 Rule text that must name `--console`

- **conventions.md rule 6.** In F6's paragraph, replace "prompt exactly `/login`) runs `claude auth login`" with:
  > "prompt exactly `/login` or `/login --console`) runs `claude auth login` or `claude auth login --console` (the fixed table `term_vt.LOGIN_ARGV`; the request selects a row and never supplies argv text)"
- **Same paragraph, the recorded fields.** "(`at`, `outcome`, `ok_at`)" becomes "(`at`, `outcome`, `ok_at`, `method`)".
- **README:127 (F5 text).** Add: "a second Config button, Log in with Console (API), runs `claude auth login --console`."
- **No other changes.** CLAUDE.md's App-owned-state line already gains `last_login.json` (clean-plan step 5), and nothing else in CLAUDE.md changes.

### D1.6 Sequencing and risk

- **Sequencing.** All of this folds into clean-plan steps 1 (store), 3 (term_vt table and branch), 4 (SPA), 5 (text) and 6 (tests), in the same commits. It adds no step.
- **Risk.** The Console path is read from the bundle, not observed. Running it for real **replaces the current claude.ai login with a Console API key**.
- **Manual-probe fallback.** The step-7 manual probe tests the Console button only if the user agrees to that, then presses Log in afterwards to return to the subscription. Otherwise the probe stops at checking that the terminal opens and shows `Opening browser to sign in…`, and Esc closes it. That gives outcome `closed`, with the label "login cancelled" and no "Logged in" toast.

### D1.7 Decisions the user may want to overrule

- **Button label.** "Log in with Console (API)". It is constant, not "Switch to Console" when already signed in.
- **Recording the method.** `last_login.json` records `method` and the line shows it. The overrule is to leave it out (it drops `LOGIN_METHODS` and three tests). The cost is a Config line that cannot tell which button was last used.

## Re-review of D1 revision (opus reviewer)

Reviewed against worktree HEAD 418f132 and the installed CLI 2.1.326 (`grep -a -b` + `dd`). Read with grep and `sed -n` only. No code edited, no login run.

### Q1. Can a request get any argv past the two table rows? **No. The claim holds.**
- The table is consulted at one place only: the `mode == "new"` branch (term_vt.py:3329-3336), behind `gw_eff == gateway.ANTHROPIC and isinstance(lp, str)`. `row[1]` is a constant tuple, and `argv[0]` is `gateway.launcher(ANTHROPIC)` (bare `claude`). No request byte reaches the `auth login` argv.
- **Normalisation.** `str.strip()` trims surrounding whitespace, Unicode whitespace included, so `" /login --console\n"` still selects the console row. That is harmless, because it only selects a fixed row.
- **Near misses fall through to `_with_prompt` (:3123).** These are `"/LOGIN --console"`, `"/login  --console"`, `"/login --console --sso"`, an interior NBSP, and `"/login\t--console"`. A tab is a control character, so `_with_prompt` drops that prompt entirely. Every other near miss becomes one positional REPL prompt, quoted by `shlex.join`. That is the same path `"/login"` takes off-Anthropic today.
- **OpenRouter.** `gw_eff != ANTHROPIC`, so the request goes to the positional prompt, as today (test :120-126).
- **`mode=resume`** builds `term_gate.resume_argv` + `_with_prompt` (:3317-3321) and never reaches the table. **`mode=cwd`** sets `argv=None`.
- **The 429/held path** (:3378-3386) changes only `if login_sid:` → `if login:`. `login` is `row[0]`, which is always a non-empty string.
- **`server.py`** has no `prompt` reference. **`ext_launch.js:338-342`** whitelists the keys and passes `prompt` through as is.
- **Body with `session` + `mode=new` + `/login --console`.** The login runs in that session's placed folder instead of `~`. This was already true for `/login`. No argv is added, `pt.spawned` stays `""`, and `mode` is `"new"`, so `_session_ptys` (:3962-3976) never matches it. No finding; see G5 for the rule text.

### Q2. Is `Pty.login` safe as a string? **Yes, with one trap (G3).**
- No `Pty` is ever serialised as a whole: there are no `__dict__`, `vars(`, `__slots__` or `asdict` uses in `aitracker/`. No existing `.login` attribute or `"login"` key collides with it; grep finds only the in-terminal pill's `data-action="login"`.
- Every base-plan use is a truth test, and `"claudeai"` and `"console"` are both truthy:
  - `not (hide_login and p.login)`
  - `if p.done or p.login`
  - `… and not p.login`
  - `if self.login:` in `finish()`
- Do **not** add F2's optional `"login": p.login` row field. Nothing needs it, and it would put a string where a JS reader expects a bool.
- The trap: the clean-plan tests say "a `login=True` Pty". Under D1.2, `record_login(outcome, True)` refuses (`True not in LOGIN_METHODS`) and writes nothing. See G3.

### Q3. Is `--console` real? **Confirmed at all five cited offsets.**
- **305105917:** `.option("--console","Use Anthropic Console (API usage billing) instead of Claude subscription").option("--claudeai",…)`.
- **314637218:** `if(R&&m)…"--console and --claudeai can't be used together"…exit(1)`.
- **314639108:** `let x=Y?Y==="claudeai":!R`.
- **314642751:** `tengu_oauth_flow_start",{loginWithClaudeAi:x}`.
- **314645094:** `process.exit(o instanceof M?130:1)`.
- The status mapping `k==="/login managed key"` → `E="api_key"` is also present (~314646100).
- One extra path: `mP()==="gateway"` on a managed machine. Without a TTY it exits 1 with "run interactive /login". With a TTY (it has one in a pty) it renders the Ink `Login`, which exits 0 or 1. That is the known gap D1.0 already names. No change.

### Q4. F1 toast, busy state, and the existing UI tests
- **F1 toast.** It reads only `last_login.outcome` and `label`, so it covers both buttons. That holds only if this attempt's record was actually written; see G3.
- **Busy state.** `busy` is shared, so one click disables both buttons. Correct.
- **Button-list edits are expected changes, not regressions.** These are :154, :160, :249 and :272. One click test is unaffected: `test_click_opens_login_terminal_once` clicks `[0]`, and `function(){login('claudeai')}` still opens `/login`.
- **The harness edit is a regression (G1).**

### Q5. Is recording `method` needed? **No. C3 needs only "when". Recommend dropping it (G3).**

### Q6. Is the rule-6 text exact and minimal? **Nearly. Two wording fixes (G5).**

### Findings

**G1: MEDIUM. D1.4's harness change breaks two existing tests.**
- **Defect.** D1.4 says "`btnDisabled` at :101 returns both buttons' disabled flags". `test_pty_gone_auto_closes` (:181) and `test_open_throw_closes_pty_and_reenables` (:218) do `assertFalse(r["btnDisabled"])`. A list `[false, false]` is truthy, so both go red.
- **Second defect.** The proposed `test_busy_disables_both_buttons` "after the click (vt)" needs the modal still open. When the scenario ends on a 404 or a close, `onDone` has already reset `busy` before the harness reads the flags at :101.
- **Repro.** Apply D1.4's harness row as written, then run `python -m unittest tests.test_claude_login_settings_ui`. Two tests fail with `AssertionError: [False, False] is not false`.
- **Direction.** Keep `btnDisabled` exactly as it is (button `[0]`, scalar). Add a new key. Do NOT change the meaning of any existing key.
- **Way.**
  - In `_BODY` after :101, add `out.btnsDisabled = btn ? btn.querySelectorAll('button').map(x => !!x.attrs.disabled) : null;`.
  - At :83, change `[0]` to `[SCEN.clickIdx || 0]`.
  - Write `test_busy_disables_both_buttons` as `self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200], ticks=12)` and assert `r["btnsDisabled"] == [True, True]`. That scenario is a live pty, so `busy` is still true when the flags are read.
- **Test.** `test_busy_disables_both_buttons` is red on 418f132: there is one button, so it gets `[True]`. The two existing tests stay green.

**G2: LOW. Esc or close races the outcome record, so the "login cancelled" line can be missing. The D1.6 manual-probe expectation is unreliable.**
- **Defect.** `renderClaudeLogin.onClose` (`ext_cr_dialogs.js:1723-1727`) fires `crCall('/api/term/close')` without waiting for it, then calls `payload.onDone(false)` at once. `onDone` runs `load(true, false)`, which sends `GET /api/claude/auth?fresh=1` in parallel.
- **Why the record can be late.** `close_pty` waits for `pt.done` (CLOSE_CONFIRM_WAIT). F1 writes the record in `finish()`, before `done`. So the record exists by the time close *responds*, but not necessarily by the time the auth GET reads it. That is especially likely when the 5 s fresh floor (`AUTH_FRESH_FLOOR`) returns the cached CLI status at once.
- **Repro.** Press Log in, then press Esc within 5 s of the Server tab loading. Expected: `Last login: … · last attempt 0s ago: login cancelled`. Actual: often the previous line, with no cancelled suffix until the next focus refetch.
- **Direction.** Call `onDone` after the close POST settles, whether it succeeds or fails. Do NOT change the 404 auto-close path, the poll, or the close body.
- **Way.** In `onClose`:
  ```js
  var wasGone = gone; teardown();
  var fin = function () { if (payload.onDone) payload.onDone(wasGone); };
  if (wasGone) fin();
  else Promise.resolve(crCall('/api/term/close', 'POST', window.ExtVT.ttyBody(tty, {}, ''))).then(fin, fin);
  ```
- **Test.** In the harness, add `SCEN.closeDelay`. When it is set, the `/api/term/close` stub resolves only after `SCEN.closeDelay` × `realST` ticks. It pushes `'close-done'`, and the auth stub pushes `'auth'`, both into `const events = []`. Then expose `out.events = events`.
  - Add `test_close_waits_before_refetch`: the `escape=True` scenario with `closeDelay: 3` and `attachedSeq=[200]`. Assert that `events.indexOf('close-done') < events.lastIndexOf('auth')`.
  - It is red today, because `onDone` fires before close resolves.
  - `test_manual_close_posts_close_once` and `test_escape_in_terminal_closes_modal` stay green.

**G3: LOW (overbuilt, and coupled to F1). Recording `method` is not required, and as specified it can make F1 toast a stale "Logged in".**
- **Defect 1: not required.**
  - C3 asks only to "show when the login has happened or was done last".
  - The effective method is already on screen. `claude auth status` → `gateway._AUTH_LABELS` shows "Claude subscription" or "API key" in the status line (`ext_cr_dialogs.js:1627`), and that comes from the CLI itself, which is truer than our record.
  - The recorded method adds information only for a *failed* attempt. Cost: `LOGIN_METHODS`, `method`/`method_label` on the wire, three store tests, one finish test, a wider route whitelist, and a rule-text field.
- **Defect 2: coupling.** D1.2's `record_login` writes **nothing** when `method not in LOGIN_METHODS`.
  - Any `pt.login` value that is not a key leaves the previous record in place. That includes the clean plan's `login=True` test Pty, and any future caller.
  - Then F1's `load()` reads the *previous* `outcome:"ok"` and toasts "Logged in" after a cancelled attempt. That is exactly the bug F1 fixes.
- **Defect 3: wording.** `'Last login: never · Console (API billing)'` reads as a Console login that never happened. D1.3's own caveat admits that the method belongs to the latest attempt.
- **Repro.** Use the D1.2 code and a Pty with `login=True`, rc 0. Call `finish()`, and `last_login.json` is unchanged. Do the same with an earlier ok record and then a cancelled attempt with a bad method: the SPA toasts "Logged in".
- **Direction (recommended).** Drop method recording, which is D1.7's listed overrule.
  - `record_login(outcome, now=None)` stays as the clean plan specifies.
  - `Pty.login` stays a string (`"claudeai"`/`"console"`). It costs nothing and lets the argv-table test prove which row was chosen.
  - `_login_finished` calls `store.record_login(_login_outcome(pt))`.
  - Must NOT drop the second button or the table.
- **If the user keeps method anyway.**
  - Signature: `record_login(outcome, method=None, now=None)`. It refuses only an unknown **outcome**. It always writes `at`/`outcome` (plus `ok_at` on ok), and sets `d["method"] = method if method in LOGIN_METHODS else None`.
  - Line text: show `ll.method_label` next to `ok_at` only when `ll.outcome === 'ok'`, and otherwise inside the suffix as `' · last attempt ' + timeAgo(ll.at) + (ll.method_label ? ' (' + ll.method_label + ')' : '') + ': ' + ll.label`.
- **Test.**
  - If dropped: remove `test_unknown_method_not_written`, `test_method_label_server_side`, `test_legacy_file_without_method_loads`, `test_finish_records_console_method` and `test_last_login_line_names_method`. The route key set stays `{at, ok_at, outcome, label}`. Every test that builds a login Pty sets `pt.login = "claudeai"` (or `"console"`), never `True`.
  - If kept: add `test_unknown_method_still_records_outcome`. Call `record_login("closed", method=True)`; the file must hold `outcome == "closed"` and `method is None`. It is red against D1.2 as written.

**G4: LOW. Stale comments name the old argv.**
- **Defect.** `ext_cr_dialogs.js:1620-1622` says the button runs `claude "/login"`. `:1680-1682` says "the server stops claude and removes it when login completes". Both are false after the change.
- **Way.**
  - :1622 → "opens a terminal in ~ running `claude auth login` (or `--console`) through the normal launch path (ExtLaunch.openAt)".
  - :1681 → "404 = the pty is gone (`claude auth login` exits when it finishes, or the window was closed) -> close."
- **Test.** None (comments).

**G5: LOW. The rule-6 text overstates two invariants.**
- **Defect.**
  - "prompt exactly `/login` or `/login --console`": the code compares after `.strip()`, as the current text already does.
  - "in a dedicated terminal in `~`": the server accepts any `cwd`, or a session's placed folder. Only the Config client sends `~`.
  - The rule must not claim what the code does not enforce.
- **Way.** Use the exact paragraph in checklist step 9.
- **Test.** None (text).

**Examined, no finding**
- The non-inline (`tab` true) fallback, when `ExtVT.mountInto` is absent. It opens a tab for a pty that `term_list` hides. That is defensive only, because ext_vt.js always ships `mountInto` (ext_vt.js:1728). No change.
- `_login_ok` (:2311) would gate the in-terminal pill on for a `claude auth login` cmd. The modal mounts no ContextBar, so it is unreachable.
- `/api/term/attached` calls `_reap()` (:4902), so F3's no-pop design is confirmed.
- The `_REMEMBER`/`upgrade_candidates` and `agent_cli` restart paths are covered by `not p.login`, which is truthy-safe.
- The two D2 deletions leave no other users. `login_transcript_state`, `LOGIN_MAX_BYTES` and `_LOGIN_OK_TYPES` are used only by `_login_watch` and `remove_login_transcript` (grep over aitracker/, tests/ and scripts/). `login_ok`/`_login_ok` is a different feature (the in-terminal pill) and stays.

### FINAL implementation checklist
This follows the base clean plan with D1 and D2 as the user decided, and G1–G5 applied. Method recording is dropped as G3 recommends. If the user keeps it, apply G3's "If kept" block at steps 2, 5 and 7.

1. **`aitracker/config.py`** (after :66): add `LAST_LOGIN_FILE = os.path.join(_HERE, "last_login.json")` with the comment "Config login outcomes {at, outcome, ok_at}; written by term_vt via store.record_login; read live".
2. **`aitracker/store.py`**:
   - Add `LOGIN_OUTCOMES = {"ok": "logged in", "failed": "login failed", "closed": "login cancelled", "timeout": "login timed out"}`.
   - Add `record_login(outcome, now=None) -> bool`. It returns False for an unknown outcome, and otherwise calls `_update_json(config.LAST_LOGIN_FILE, mutate)`. `mutate` sets `at` and `outcome`, and sets `ok_at` only on ok, keeping the previous `ok_at` otherwise. It never raises.
   - Add `load_last_login() -> dict|None`. It returns `{at, ok_at, outcome, label}` only when the types validate.
3. **`.gitignore`**: add `last_login.json` and `last_login.json.lock`.
   **`tests/__init__.py`** (after :36): redirect `_config.LAST_LOGIN_FILE` to a mkdtemp file plus an atexit rmtree, exactly like `LAST_TERMS_FILE`.
4. **`aitracker/term_vt.py`**, C1:
   - `Pty.__init__` (near `self.overflow`): add `self.login = ""` and `self.login_timed_out = False`.
   - `_live_list(orl=None, hide_login=False)` (:2343). The filter becomes `if not p.done and not (hide_login and p.login)`. Only `term_list` (:4360) passes `hide_login=True`. The three 429 calls are unchanged, and so is `_live_count`.
   - `resolve_spawned` (:2132): skip with `if p.done or p.login: continue`.
   - `upgrade_candidates` (:4461): the panes filter adds `and not p.login`.
5. **`aitracker/term_vt.py`**, C2/C3 and D1:
   - Constants block (:3623). Keep `LOGIN_PROMPT = "/login"`. Add `LOGIN_CONSOLE_PROMPT = "/login --console"` and the comment-bearing `LOGIN_ARGV = {LOGIN_PROMPT: ("claudeai", ("auth", "login")), LOGIN_CONSOLE_PROMPT: ("console", ("auth", "login", "--console"))}`. Set `LOGIN_POLL = 0.5` and keep `LOGIN_WATCH_MAX = 1800.0`. Delete `LOGIN_SETTLE` and `LOGIN_DONE_NOTE`.
   - `_open_pty`. At :3315, `login = ""`. In :3329-3336, use D1.1's `row = LOGIN_ARGV.get(lp.strip()) if … else None` and, when there is a row, `login = row[0]; argv = [argv[0]] + list(row[1])`. Otherwise use `_with_prompt`. At :3378 use `if login:`, and at :3411-3412 pass `login=login`. Remove the `uuid` use here, but keep the import if anything else uses it.
   - `_spawn_dedicated(…, held=False, login="")` (:3559). Set `pt.login = login` before `PTYS[pt.id] = pt`, and delete the `pt.spawned = login_sid` lines. When `login` is set, start `_login_watch` with `args=(pt,)`.
   - New module functions next to the watcher:
     - `_login_outcome(pt)`: `"ok"` if `pt.rc == 0`; else `"timeout"` if `pt.login_timed_out`; else `"closed"` if `pt.closing or pt.rc is None or pt.rc == 130 or pt.rc < 0`; else `"failed"`.
     - `_login_finished(pt)`: `try: store.record_login(_login_outcome(pt)) except Exception: pass`.
   - `Pty.finish()` (:1631): immediately before `self.done = True` (:1665), add `if self.login: _login_finished(self)`.
   - Replace `_login_watch(pt, sid)` (:3630-3667) with `_login_watch(pt)`. It loops `while not pt.done` until `LOGIN_WATCH_MAX`, then sets `pt.login_timed_out = True; pt.kill()`, inside `try/except Exception: pass`. It records nothing and pops nothing.
6. **`aitracker/providers/claude.py`**: delete `LOGIN_MAX_BYTES`, `_LOGIN_OK_TYPES`, `login_transcript_state` and `remove_login_transcript` (:1325-1398). Do NOT add the `remembered_terminals` filter (D2).
7. **`aitracker/server.py`** `/api/claude/auth` (:509-516): build `body = {k: st.get(k) for k in _CLAUDE_AUTH_KEYS if k in st}`, then `body["last_login"] = load_last_login()`, then `return self._json(body)`. Import `load_last_login` on the :16 store import.
8. **`aitracker/web/ext_cr_dialogs.js`**:
   - `claudeLoginBlock.paint`:
     - Change the first button to `crBtn(…, function () { login('claudeai'); })`.
     - Add `bc = crBtn('Log in with Console (API)', function () { login('console'); })`, disabled when `busy`, and append it to the same `ctl`.
     - When `loginSt && loginSt.last_login`, add the line `'Last login: ' + (ll.ok_at ? timeAgo(ll.ok_at) : 'never') + (ll.outcome !== 'ok' ? ' · last attempt ' + timeAgo(ll.at) + ': ' + ll.label : '')` with class `cr-cfg-row-sub cr-claude-login-last`.
     - Warn text: "Signs in for every Claude Code session on this machine. Log in uses your Claude subscription; Console uses Anthropic Console API billing, and switching method replaces the current login. Opens `claude auth login` in a terminal over this page; nothing of it is kept once it ends."
   - `login(method)`: `var pr = method === 'console' ? '/login --console' : '/login';`, passed to `L.openAt('~','new', pr, …)`.
   - `load()`: when `announce && r.ok && ll`, toast `'Logged in'` (meta `r.body.label`) if `ll.outcome === 'ok' && r.body.logged_in`, else `{title: ll.label}`.
   - `renderClaudeLogin.onClose`: apply G2.
   - Comments :1622 and :1681: apply G4.
9. **`.claude/rules/conventions.md`**: delete the whole "Exception (login-session cleanup, …)" paragraph (line 23). In its place, insert:
   > *Config login terminal (user-requested 2026-11-17; supersedes the former login-session cleanup exception): Config's Log in / Switch account and Log in with Console (`POST /api/term/pty`, `mode=new`, Anthropic gateway, prompt `/login` or `/login --console`, surrounding whitespace ignored) runs `claude auth login` or `claude auth login --console` — never the `/login` REPL command — from the fixed table `term_vt.LOGIN_ARGV` (the request selects a row and never supplies argv text), in a dedicated terminal (Config opens it in `~`), so Claude Code creates no session, transcript or folder-trust prompt for it. For a login the tracker deletes and edits nothing under `~/.claude`; its only write is the outcome (`at`, `outcome`, `ok_at`) in the app-owned `aitracker/last_login.json` through `store.record_login`, and at `LOGIN_WATCH_MAX` it may SIGKILL that terminal's own process group.*

   **`CLAUDE.md`** App-owned state (:33): append "and `last_login.json` (written by `store.record_login`)".
   **`README.md:127`**: apply F5's rewrite, plus "a second button, Log in with Console (API), runs `claude auth login --console`".
10. **Tests.** Prove each new one red by reverting its hunk with a scoped Edit, never `git stash`.
    - **`tests/test_pending_pty_prompt.py`**:
      - :64-65 lambda → `lambda pt: self._watched.set()`.
      - Rewrite `_assert_dedicated_login` (:74-87) to check `argv == ["claude","auth","login"]`, `pt.login == "claudeai"`, `pt.spawned == ""`, `pt.overflow`, and `watch.call_args[0] == (pt,)`. Drop the `uuid` import if it becomes unused.
      - Add `test_console_login_prompt_spawns_console_argv`, `test_login_argv_table_is_fixed`, and `test_console_prompt_off_anthropic_or_near_miss_is_plain`. The last one also covers `"/LOGIN --console"` and `"/login --console --sso"` (both plain), and `" /login --console "` (dedicated, console).
    - **`tests/test_login_session_cleanup.py`**: delete `LoginTranscriptState`, `VanishedTranscript`, `RemoveLoginTranscript` and the old `LoginWatch`. Add the following; every Pty uses `login="claudeai"`/`"console"`, never `True`:
      - `test_finish_records_before_done`
      - the outcome mapping for rc 0, 1, 130, -9 and None, with `closing` and `login_timed_out`
      - `test_timeout_kills_own_group` (patch `Pty.kill`)
      - `test_never_deletes_a_login_transcript`
      - `test_raise_is_swallowed`
      - a `LoginPtyHidden` class with `test_term_list_hides_login_pty`, `test_429_lists_login_pty`, `test_resolve_spawned_never_latches_login_pty` and `test_upgrade_candidates_skip_login_pty`
    - **`tests/test_store_last_login.py`** (new): `test_record_and_load_roundtrip`, `test_unknown_outcome_not_written`, `test_bad_shape_loads_none`.
    - **`tests/test_claude_auth_route.py`**: at :82-86, change the assertion to `set(OK) | {"last_login"}`. Add `test_last_login_rides_the_auth_body`, which checks the keys `{at, ok_at, outcome, label}`.
    - **`tests/test_claude_login_settings_ui.py`**:
      - Harness changes per G1 (`clickIdx`, a new `btnsDisabled`, `btnDisabled` untouched) and G2 (`closeDelay`, `events`).
      - Update the `buttons` lists at :154, :160, :249 and :272 to add `"Log in with Console (API)"`.
      - In `test_pty_exit_after_login_toasts_once`, give the second auth `last_login={"at":1,"ok_at":1,"outcome":"ok","label":"logged in"}`.
      - Add `test_failed_switch_no_logged_in_toast`, `test_console_button_opens_console_login`, `test_busy_disables_both_buttons` (live-pty scenario), `test_close_waits_before_refetch`, `test_last_login_line_rendered` and `test_no_last_login_no_line`.
11. **Gate.** Run `unset TRACKER_AUTH; make check` (one module per process if it is OOM-killed). The commit hook runs the full gate, so give it a timeout over 2 min.
12. **Manual.** After `make serve`, run plan §5's probe plus D1.6 (Console only with the user's OK; otherwise Esc gives the line "last attempt …: login cancelled" and no toast). Then F7/D2's one-time deletion, by the main thread, with the list shown to the user first and verified afterwards by listing names.

## Reconciliation of re-review (main thread)

| # | Verdict | Note |
|---|---|---|
| G1 btnDisabled list breaks :181/:218 | confirmed | separate `btnsDisabled` key |
| G2 Esc refetch races close POST | confirmed | onDone after close settles |
| G3 recording `method` | confirmed overbuilt → **dropped** | C3 asks only *when*; status line already shows subscription vs API key |
| G4 stale comments :1622/:1681 | confirmed | |
| G5 rule-6 wording | confirmed | use checklist step 9 text |

D2 one-time delete: **done 2026-11-17** by main thread (2 jsonl, e25c63ac sibling dir, 2 empty session-env dirs, last_terms key 2028e7c5; history.jsonl untouched). Code-side removals (`login_transcript_state`, `remembered_terminals` filter) remain in the checklist.

Implementation = the re-review's final checklist, method recording dropped.


## Implementation notes (sonnet implementer)

Files: config.py (LAST_LOGIN_FILE), store.py (record_login, load_last_login, LOGIN_OUTCOMES), term_vt.py (Pty.login/login_timed_out, LOGIN_ARGV, _login_outcome/_login_finished/_login_watch(pt), finish() hook, _live_list hide_login, resolve_spawned/upgrade_candidates skip), providers/claude.py (4 login-transcript symbols deleted), server.py (last_login on /api/claude/auth), web/ext_cr_dialogs.js (second button, last-login line, toast, G2, G4), .gitignore, tests/__init__.py, CLAUDE.md, README.md:127, conventions.md rule 6 (old exception replaced). Method recording dropped (G3).

Red on unchanged code, then green: test_store_last_login (3), test_login_session_cleanup (LoginOutcome mapping/finish/swallow/never-deletes, LoginWatch x3, LoginPtyHidden x4 reds; test_429_lists_login_pty errored on the missing kwarg), test_pending_pty_prompt (argv table, console argv, near-miss plain, 3 rewritten dedicated-login tests), test_claude_auth_route (test_last_login_rides_the_auth_body, test_local_200, test_no_identifying_key_in_body), test_claude_login_settings_ui (busy_disables_both_buttons, close_waits_before_refetch, console_button_opens_console_login, failed_switch_no_logged_in_toast, last_login_line_rendered, plus the buttons-list updates). test_no_last_login_no_line is green on both (guards absence).

Green: those modules plus test_resume_pty_budget, test_resume_all_record, test_resolve_spawned, test_folder_terminal, test_open_pty_at_root, test_term_title, test_term_name_suffix, test_folder_swap, test_term_vt_client, test_update_settings_ui. Full `make check` and the manual probe (steps 11-12) NOT run.

Deviations: none of substance. Red/green was proven by running the new tests before implementing (not by per-hunk reverts). Left uncommitted.

## Implementation review (opus reviewer)

Reviewed the uncommitted worktree against `personal/main` 418f132. I used per-file `git diff`, grep and `sed -n` only. I edited no code except the temporary reverts listed below, each restored exactly; the diff stat is unchanged (term_vt.py 109, ext_cr_dialogs.js 41) and both modules are green again. I did not run a full `make check`, start a server or run a login.

**Verdict: PASS with two LOW findings.** The live path holds. Nothing blocks shipping, but the manual probe (checklist step 12) is still owed before C2 can be called *observed* rather than *read from the bundle*.

### Red proofs (scoped Edit → run → restore → green)

| Reverted line | Test that went RED |
|---|---|
| `term_vt.py:2224` `if p.done or p.login:` → `if p.done:` | `LoginPtyHidden.test_resolve_spawned_never_latches_login_pty` |
| `term_vt.py:4390` `_live_list(orl, hide_login=True)` → `_live_list(orl)` | `LoginPtyHidden.test_term_list_hides_login_pty` |
| `term_vt.py:4470` dropped `and not p.login` | `LoginPtyHidden.test_upgrade_candidates_skip_login_pty` |
| `ext_cr_dialogs.js:1737` G2 (`onDone` after close settles) → fire close POST then `fin()` at once | `test_close_waits_before_refetch` |

After the restore, `test_login_session_cleanup` and `test_claude_login_settings_ui` were green again.

These modules are green one per process: `test_login_session_cleanup`, `test_store_last_login`, `test_pending_pty_prompt`, `test_claude_auth_route`, `test_claude_login_settings_ui`, `test_resume_pty_budget`, `test_resume_all_record`, `test_resolve_spawned`, `test_cr_term_login_pill`, `test_pending_ext_launch` and `test_tracker` (29 tests, which carries the selfcheck `_run()`).

### Checked, no finding
1. **Live path.**
   - The flow is: `ext_cr_dialogs.js:1663` prompt → `_open_pty` :3336-3341 `LOGIN_ARGV.get(lp.strip())`, only on the `mode == "new"` branch with `gw_eff == ANTHROPIC` → `_spawn_dedicated(login=…)` → `pt.login` set before `PTYS[pt.id]` → `finish()` :1669 records before `done` → `_reap` :2396 pops the done overflow pty → `/api/term/attached` returns 404 → the modal closes.
   - Every `PTYS` iteration was checked:
     - `term_list` hides the login pty.
     - The three 429 calls list it, by design, so the user can free the slot.
     - `resolve_spawned` skips it. Its `taken` scan is harmless, because `spawned`/`session` are empty or not matched.
     - `_session_ptys` (:3968) never yields it: mode is `new` and `spawned` is `""`. That makes `registry._attached_pty` safe.
     - `upgrade_candidates` skips it, which keeps it out of the restart lists at `agent_cli.py:312` and `:567`, and out of `remember_terminals` → `last_terms.json` → Resume all.
     - `_folder_pty`, the idle scan at :4692 and `_pane_fingerprint` are folder-only or harmless.
2. **Argv injection.** A request only selects a dict row. `argv[0]` is `gateway.launcher(ANTHROPIC)`. `mode=resume`/`cwd` and OpenRouter never reach the table. The near-miss tests are in `test_pending_pty_prompt`.
3. **Outcome mapping** (`_login_outcome` :3640). rc 0 → ok, even when closing. timeout is checked before closed. closing / None / 130 / <0 → closed. Anything else → failed. It is all covered by `test_outcome_mapping`. The watcher sets `login_timed_out` before `kill()`.
4. **Deleted symbols.** `login_transcript_state`, `remove_login_transcript`, `LOGIN_MAX_BYTES`, `_LOGIN_OK_TYPES`, `LOGIN_SETTLE`, `LOGIN_DONE_NOTE`, `login_sid` and "Login successful" have zero hits in `aitracker/` (incl. `web/`, `pending.py`, `agent_cli.py`), `scripts/`, `Makefile`, `README.md`, `CLAUDE.md` and `.claude/`. The only hits are the two `assertFalse(hasattr(...))` guards in `tests/test_login_session_cleanup.py:79-80`. `uuid` is still imported because `Pty.__init__` :1389 uses it.
5. **Unexpected edits.**
   - `CLAUDE.md` is one line on the App-owned-state bullet. It is checklist step 9, and it is minimal.
   - `tests/__init__.py` adds three lines that redirect `config.LAST_LOGIN_FILE` to a mkdtemp file plus an atexit rmtree, mirroring `LAST_TERMS_FILE`. That is checklist step 3. Without it, any test that `finish()`es a login pty writes the real `aitracker/last_login.json`, and none exists after the runs.
   - **`test_selfcheck` running 0 tests is pre-existing and by design.** The file is byte-identical to `personal/main`. `scripts/run_tests_parallel.py:57` lists it in `BENIGN_EMPTY_MODULES`, and its `_run()` executes from `tests/test_tracker.py`'s `test_selfcheck_passes` (`:20-23` and `:89-98` of the runner). That module is green, so discovery is not broken.
6. **conventions.md rule 6.** The old "login-session cleanup" paragraph is gone. The new paragraph is a byte-exact match of checklist step 9 (checked by string containment), and no other line changed. `.gitignore` has `last_login.json` and `last_login.json.lock`.
7. **The server owns the label.** `store.LOGIN_OUTCOMES` → `load_last_login()["label"]` → `/api/claude/auth` `last_login`. JS only renders `ll.label` plus `timeAgo`. The body keys are `{at, ok_at, outcome, label}`, so no identity can leak.
8. **Header count.** `server._term_count()` → `_live_count()` still counts a running login pty, while Manage terminals hides it. The pty really holds a slot, and the 429 path lists it. No change; this is a known, intended asymmetry.

### Findings

**I1: LOW. "Logged in" can toast from a previous attempt's record (F1's "newer than the click" is not enforced).**
- **Defect.** `aitracker/web/ext_cr_dialogs.js:1650-1654` (`load`) toasts "Logged in" whenever `ll.outcome === 'ok' && r.body.logged_in`. It never checks that `ll` was written by *this* attempt.
- **When `onDone(true)` arrives without a new record.**
  - The server restarted mid-login. The pty is gone, so the poll gets a 404, but `finish()` never ran.
  - `store.record_login` failed. `_login_finished` swallows the error.
  - The I2 race.
- **Result.** The previous `outcome:"ok"` record is re-announced.
- **Repro (harness).** `self.vt(attachedSeq=[200, 404], authSeq=[_auth(True, last_login=_LL_OK), _auth(True, last_login=_LL_OK)])`.
  - Actual: toasts `Logged in`.
  - Expected: no "Logged in" toast, because the record did not change.
- **Direction.** Announce only a record that is newer than the one on screen at click time. Compare server value to server value, never to `Date.now()`, which skews under the tunnel.
  - Must NOT change: the toast texts, the `ll.label` fallback toast, the G2 `onDone`-after-close ordering, the last-login line, or the server.
- **Way.** In `claudeLoginBlock`, add the closure var `var clickAt = null;`.
  - In `login(method)`, before `busy = true`: `clickAt = loginSt && loginSt.last_login ? loginSt.last_login.at : 0;`
  - In `load`: `if (announce && ll && ll.at !== clickAt) { …existing two-branch toast… }`.
  - Optionally, when `announce && (!ll || ll.at === clickAt)`, show nothing.
- **Test.** Add `test_stale_ok_record_no_logged_in_toast` to `tests/test_claude_login_settings_ui.py` with the repro above, and assert that no toast has title `Logged in`. It is red on the current tree. `test_pty_exit_after_login_toasts_once` (first auth carries no `last_login`, second carries `_LL_OK`) and `test_failed_switch_no_logged_in_toast` must stay green.

**I2: LOW. `pt.login` is assigned after `spawn()` has already started the reader thread.**
- **Defect.** `spawn()` starts `_reader` (`term_vt.py`, `def spawn` + 8 lines), and `_reader` calls `finish()` on EOF. `_spawn_dedicated` sets `pt.login = login` only afterwards, at :3579.
- **Repro.** A child that exits before the main thread reaches :3579 is finished with `pt.login == ""`, so `finish()` records nothing. Examples: exec failure → 127, or an instant `exit(1)` on the managed-gateway non-TTY path. The window is microseconds wide, and `finish()` also waits on `waitpid`, so it is rare. It is not a C1 leak: the pty is not yet in `PTYS`, so no list can see it unmarked. The cost is a missing outcome record (stale "Last login" line), which I1 would then mis-announce.
- **Direction.** Mark the Pty before its reader can run.
  - Must NOT change: `spawn()`'s behaviour for every other caller (default `""`), or where `pt.overflow`/`session` are set.
- **Way.** Change the signature to `def spawn(cwd, argv, cols, rows, login=""):`.
  - Set `pt.login = login` right after `pt = Pty(...)` and before `threading.Thread(target=_reader, …).start()`.
  - In `_spawn_dedicated`, call `spawn(spawn_cwd, argv, cols, rows, login=login)` and delete the later `pt.login = login` line, or keep it as a no-op.
- **Test.** Add `test_login_marked_before_reader_starts` to `tests/test_login_session_cleanup.py`:
  - Body: `seen = []; with mock.patch.object(term_vt, "_reader", side_effect=lambda pt: seen.append(pt.login)): pt = term_vt.spawn("/tmp", ["/usr/bin/true"], 80, 24, login="claudeai")`.
  - Then join briefly, `os.waitpid(pt.pid, 0)` in a try block, close `pt.fd`, and assert `seen == ["claudeai"]`.
  - It is red now: `TypeError` on the kwarg. Moving only the assignment would also go red, because `seen == [""]`.
  - Acceptable alternative if the user prefers no change: "known gap; I1's fix removes its visible consequence".

**I3: INFO (process, not code). Owed before ship.**
- The full gate (`unset TRACKER_AUTH; make check`, or one module per process) has not been run.
- The manual probe (step 12) has not been run. It is the only runtime proof of C2 (no trust prompt) and of "rc 0 on success inside a pty". Until then, C2 rests on the bundle read (R0/Q3).
- The implementer proved red test-first rather than by per-hunk revert. The four reverts above now cover the C1 filters and G2.

### Contract status after this review
| Clause | Status |
|---|---|
| C1 | discharged in code. Verified by the 3 red proofs: term_list, resolve_spawned, upgrade_candidates → last_terms/Resume all/agent restart. |
| C2 | discharged by construction (no REPL). Runtime observation pending (I3). |
| C3 | discharged: nothing under `~/.claude` is touched, the pty is reaped on exit, and `last_login.json` is shown. I1/I2 are LOW accuracy nits on the toast/record. |

## Reconciliation of implementation review (main thread)

| # | Verdict | Note |
|---|---|---|
| I1 stale ok record toasts "Logged in" | confirmed | same defect F1 targeted; snapshot `last_login.at` at click |
| I2 `pt.login` set after reader thread starts | confirmed | small race, small fix: `spawn(..., login=)` |
| I3 gate + manual probe owed | confirmed | gate running; probe needs the user (real sign-in) |

### I1/I2 applied
- I1: ext_cr_dialogs.js snapshots `last_login.at` into `clickAt` on click; `load` announces only when `ll.at !== clickAt`. Test `test_stale_ok_record_no_logged_in_toast` (red then green); two existing toast tests gained a third authSeq entry (harness consumes two loads before the click).
- I2: `term_vt.spawn(..., login="")` sets `pt.login` before the reader thread starts; `_spawn_dedicated` passes `login=login` and the late assignment is removed. Test `test_login_marked_before_reader_starts` (red then green); test fakes of `spawn` (pending_pty_prompt, resume_pty_budget, folder_terminal) now accept and honor `login`.
- Gate: login_settings_ui, login_session_cleanup, pending_pty_prompt, resume_pty_budget, term_vt, folder_terminal all green (one module per process); full make check not run.
