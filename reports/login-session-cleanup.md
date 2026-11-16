# Remove the /login session once login / switch-account completes

Branch: `worktree-login-session-cleanup` (base `personal/main` 0c93bfc)

## Contract (verbatim, user 2026-11-17)
> "for claude code login in this app, its working all good, I am able to login and also switch account as well, now when the login has happened can you remove that very session once the login/switch account has been completed"

| Clause | Verdict |
|---|---|
| After login / switch account completes, remove the session the login button created | not discharged |
| Existing login + switch flow keeps working | not discharged |

## Facts established (main thread)
- Button: `aitracker/web/ext_cr_dialogs.js` `claudeLoginBlock()` (~L1615) → `ExtLaunch.openAt('~', 'new', '/login', { gateway: 'anthropic' })` (`aitracker/web/ext_launch.js` ~L339/L389) → a terminal in `~` running `claude "/login"`.
- That creates a real Claude session transcript under `~/.claude/projects/-Users-pritammondal/<sid>.jsonl` (~14 lines). Real shape, confirmed on 2028e7c5-…jsonl: user records `<local-command-caveat>…`, `<command-name>/login</command-name>…`, then on success `<local-command-stdout>Login successful</local-command-stdout>`. A cancelled/in-progress one (e25c63ac-…) lacks the stdout line.
- Terminal close route exists: `POST /api/term/close {tty}` → `term_vt.close_pty` (~L4162).
- No existing "hide/remove session" feature. Rule 6 (`.claude/rules/conventions.md`) makes session logs read-only; deleting a transcript needs a new, narrow, user-requested exception.

## Plan
_(opus plan agent, 2026-11-17; grounded on base 0c93bfc)_

### 0. Facts the plan rests on (checked in code / on disk)
- **Two launch paths today.** `term_vt.open_pty` mode `new` with `{cwd}` either (a) goes *cold* → `_spawn_dedicated()` (an `overflow` pty whose child IS `claude "/login"`) when there's no settled folder shell for `~`, or (b) *types* `claude /login` into the shared `~` folder shell (`_inject_argv`, `Pty.fg = {mode:"new"}`) when one is idle. Path (b) means "close the terminal" would kill the user's shared `~` shell — so login opens must always take path (a) (§2).
- **Session id link today is a guess.** The pty only learns its transcript via `resolve_spawned()` (`newest_session_in_cwd(~, pt.started)`), driven by client polls of `GET /api/term/list`. Not reliable enough to delete on. **Installed `claude` 2.1.326 supports `--session-id <uuid>`** ("Use a specific session ID for the conversation") — so the server can pick the id itself: zero guessing.
- **Transcript shape** (real files in `~/.claude/projects/-Users-pritammondal/`): non-user records (`last-prompt`, `mode`, `permission-mode`, `session-owner`, `tools-used`, `file-history-snapshot`, `attachment`, `custom-title`, `agent-name`, `cost-state`) + exactly three `type:"user"` records: `isMeta:true` `<local-command-caveat>…`, `<command-name>/login</command-name>…`, `<local-command-stdout>Login successful</local-command-stdout>` (success, 2028e7c5) or `…Login interrupted…` (cancel, e25c63ac). No assistant record.
- **What else Claude writes per session:** `~/.claude/session-env/<sid>/` (empty dir), one `~/.claude/history.jsonl` line (`"display":"/login"`), sometimes `projects/<dir>/<sid>/custom-title.json`. No `sessions/<pid>.json` survives exit, no `file-history/<sid>`. The dashboard (`claude.list_sessions`/`search_sessions`/`find_session`) and `claude --resume` both enumerate only `projects/*/*.jsonl`, so **deleting the one `.jsonl` is enough**; `term_vt.remembered_terminals()` already drops entries whose transcript is gone (`store._find_transcript`). Residue left on purpose: the empty `session-env/<sid>/` and the history line (Claude's own files; never edited).
- **Existing primitives reused:** `stop_for_upgrade(tty, sid, pid)` (SIGTERM → `PARKED_DETACH_WAIT` → SIGKILL, confirmed; works for a dedicated pty with `pid == pt.pid`), `_feed_note(pt, text)` (banner + line in the tab, both renderers, no client change), `_reap()` (drops a done `overflow` pty immediately → the terminal row vanishes), `claude.find_session(sid)` (sanitised).
- **Out of scope:** the in-terminal `/login` pill (`GET /api/term/attached` → `login_ok`) injects `/login` into an *existing* session — that session must never be removed. Only the Config → Server button's fresh session is.

### 1. Design (default: close + delete)
Server owns everything; **no client change, no new route**. When `POST /api/term/pty` is a *login open* — `mode=="new"`, effective gateway `anthropic`, `prompt.strip()=="/login"` — the server:
1. mints `login_sid = str(uuid.uuid4())`, runs `[launcher, "--session-id", login_sid, "/login"]` in a **dedicated** pty, pre-sets `pt.spawned = login_sid` (row named at once; `resolve_spawned`'s `claimed` set excludes it);
2. starts one daemon thread `_login_watch(pt, login_sid)` that polls the transcript every `LOGIN_POLL` (2 s) for up to `LOGIN_WATCH_MAX` (1800 s):
   - state `"other"` (anything beyond the /login records — user typed a real prompt, assistant reply, sidechain) → return, touch nothing;
   - state `"ok"` → `_feed_note(pt, LOGIN_DONE_NOTE)` then `stop_for_upgrade(pt.id, login_sid, pt.pid)`; if not `confirmed` → return (never delete under a live process);
   - `pt.done or pt.closing` (user closed it / claude exited) → fall through to the final check;
   - timeout → return, touch nothing.
3. after the process is gone (`pt.done`, bounded wait `CLOSE_CONFIRM_WAIT`), calls `claude.remove_login_transcript(login_sid)`, which **re-reads** and unlinks only if the state is still `"ok"`. `_reap()` then drops the overflow row; the next sidebar poll no longer lists the session.

### 2. Exact changes
**`aitracker/providers/claude.py`** (Claude-only capability: login exists only for Claude, so no Auggie twin — rule 4 n/a)
```python
LOGIN_MAX_BYTES = 262144
def login_transcript_state(sid) -> str:      # "ok" | "pending" | "other"; never raises
    # path = find_session(sid); None -> "pending" (not written yet); size > LOGIN_MAX_BYTES -> "other".
    # Per line: json.loads; a bad LAST line -> "pending" (mid-write), a bad earlier line -> "other".
    # d["isSidechain"] truthy or d["type"]=="assistant" -> "other". Non-"user" types -> skip.
    # user text = content str, or "".join(text parts) of a list (a tool_result part -> "other").
    #   isMeta and text.startswith("<local-command-caveat>")   -> skip
    #   _slash_prompt(text) == "/login"                          -> saw_cmd = True
    #   text.startswith("<local-command-stdout>") and saw_cmd    -> ok |= "Login successful" in text
    #   anything else                                            -> "other"
    # return "ok" if ok else "pending"
def remove_login_transcript(sid) -> bool:    # never raises
    # path = find_session(sid); require realpath(path) under realpath(config.PROJECTS) and
    # basename == sid + ".jsonl"; require login_transcript_state(sid) == "ok"; os.unlink(path);
    # _META_CACHE.pop(path, None); return True. Anything else -> False.
```
**`aitracker/term_vt.py`**
- Constants near `PARKED_DETACH_WAIT`: `LOGIN_PROMPT = "/login"`, `LOGIN_POLL = 2.0`, `LOGIN_WATCH_MAX = 1800.0`, `LOGIN_DONE_NOTE = "Login complete — closing this terminal and removing its /login session. You can close this tab."`
- `open_pty`, `elif mode == "new":` arm: `gw_eff = gw if gw in (ANTHROPIC, OPENROUTER) else config.GATEWAY`; `login_sid = str(uuid.uuid4()) if gw_eff == gateway.ANTHROPIC and isinstance(body.get("prompt"), str) and body["prompt"].strip() == LOGIN_PROMPT else ""`; if set, `argv = [argv[0], "--session-id", login_sid, LOGIN_PROMPT]` instead of `_with_prompt`. Initialise `login_sid = ""` before the mode branches.
- `open_pty` cold test: `if mode != "cwd" and (fp is None or not fp.startup_done):` → `if mode != "cwd" and (login_sid or fp is None or not fp.startup_done):` and pass `login_sid=login_sid` to that branch's `_spawn_dedicated(...)` call. (One-token change; the existing `warm` root-shell logic is untouched.)
- `_spawn_dedicated(spawn_cwd, argv, mode, sid, forked, cols, rows, held=False, login_sid="")`: before `PTYS[pt.id] = pt`, `pt.spawned = login_sid` when set; after registration, `threading.Thread(target=_login_watch, args=(pt, login_sid), name="login-watch-%s" % pt.id, daemon=True).start()` (a `RuntimeError` just skips the watch — login still works, nothing is removed).
- New `_login_watch(pt, sid)` (≈30 lines, §1 step 2–3). Provider reached with the same guarded `__import__("%s.providers.claude" % __package__, fromlist=["claude"])` idiom as `resolve_spawned` (bundle-safe: in `dist/tracker.py` it simply returns). Never raises (whole body in `try/except Exception: return`).

**`.claude/rules/conventions.md`** — add under rule 6 (wording in §5).

Data shapes: no wire change. The POST response is unchanged (`session` stays `""` as for every cwd open; the row's `session` becomes `login_sid` via `spawned`). `pt.cmd` becomes `claude --session-id <uuid> /login`; `_login_ok`/`_term_title` still read it correctly (`argv[1:2] != ["attach"]`, argv[0] basename `claude`).

### 3. Failure paths
| Case | Behaviour |
|---|---|
| Login cancelled / fails (`Login interrupted`, or nothing) | state stays `pending`; user closes tab/terminal → final check not `ok` → nothing deleted; untouched terminal is reaped by the normal idle TTL. |
| User types a real prompt in that session | state `other` → watcher exits; session is a normal session, never removed. |
| User closes the terminal manually (✕ / close_pty) before success | `pt.closing` → final check → not `ok` → kept. After success but inside the 2 s poll → `ok` → removed (it is the session the user asked to remove). |
| Server restart mid-login | the pty and the watcher die with the server; the transcript is left as is (an ordinary row). Known gap, no startup sweep (it would have to guess which transcript the old process launched). |
| Two presses | two uuids, two dedicated ptys, two independent watchers; each removes only its own id. |
| `stop_for_upgrade` not `confirmed` | no deletion; notice already shown; terminal remains for the user to close. |
| OpenRouter gateway / other prompt / `/login` typed by hand | not a login open → current behaviour byte-for-byte. |

### 4. Tests — new `tests/test_login_session_cleanup.py` (stdlib unittest; each red if its logic is reverted)
1. `LoginTranscriptState` — temp `config.PROJECTS` (patched, late-bound) with fixture jsonl built from the real shape: success → `"ok"`; `Login interrupted` → `"pending"`; success + an extra `{"type":"user","message":{"content":"hi"}}` → `"other"`; success + an `assistant` record → `"other"`; missing file → `"pending"`; truncated last line → `"pending"`.
2. `RemoveLoginTranscript` — `ok` file is unlinked & returns True; `pending` and `other` files survive & return False; a sibling `<sid>/` dir and another `.jsonl` in the same dir are untouched.
3. `OpenPtyLoginArgv` — `open_pty(h, None, {"cwd": td, "mode": "new", "prompt": "/login", "gateway": "anthropic"})` with `spawn` mocked (pattern of `tests/test_open_pty_at_root.py`), `gateway.launcher → "claude"`, `_login_watch` patched: argv == `["claude", "--session-id", U, "/login"]` with `U` a valid uuid; the pty is `overflow`; `pt.spawned == U`; `_login_watch` called once with `(pt, U)`; **an idle, settled folder pty already registered for `td` is NOT typed into** (`_inject_write` not called). Control: `prompt: "hi"` and `gateway: "openrouter"` + `/login` → old argv, no watcher.
4. `LoginWatch` — fake pty object (`id`, `pid`, `done`, `closing`), `LOGIN_POLL` patched to 0.01, `stop_for_upgrade` mocked to set `pt.done = True` and return `{"confirmed": True}`, `_feed_note` mocked: `ok` file → stop called with `(pt.id, U, pt.pid)` and file gone; `pending` + `pt.closing = True` → stop not called, file kept; `other` → returns, stop not called, file kept; `confirmed: False` → file kept.

Gate: run this module alone, then `tests/test_term_vt.py`, `tests/test_open_pty_at_root.py`, `tests/test_term_vt_upgrade.py`, `tests/test_attached_login_ok.py` one per process (`unset TRACKER_AUTH;`), then the full `make check` before push. **Restart required** (server-side change; no `web/` change). Manual check: Config → Server → Log in → finish → tab shows the notice and the process exits, the terminal row and the sidebar session are gone, `ls ~/.claude/projects/-Users-pritammondal/` no longer has that uuid; repeat with a cancelled login → file stays.

### 5. Rule-6 exception to add to `.claude/rules/conventions.md`
> *"Exception (login-session cleanup, user-requested 2026-11-17: \"when the login has happened can you remove that very session once the login/switch account has been completed\"): `aitracker/term_vt.py` `_login_watch()` — and only it — may act on the one session the tracker itself starts for Config → Server's Log in / Switch account: a `POST /api/term/pty` with `mode=new`, the Anthropic gateway and prompt exactly `/login`, which the server runs in a dedicated terminal as `claude --session-id <uuid4 it generated> /login`. Once that transcript records `Login successful`, it may stop that terminal's Claude through `stop_for_upgrade`, and, only after the process has exited, delete exactly one file — `<config.PROJECTS>/<dir>/<that uuid>.jsonl` — through `providers/claude.remove_login_transcript()`, which first re-reads it and refuses unless its only user records are the `/login` command, its `<local-command-caveat>` and its `<local-command-stdout>` lines, with no assistant or sidechain record. It never deletes any other transcript, the session's sibling directory, `~/.claude/session-env`, `history.jsonl` or anything else under `~/.claude`; a cancelled, abandoned or continued login session, and any session reached through the in-terminal /login control, is left untouched."*

### 6. Alternative: "hide only" (no deletion, no rule-6 exception)
Same §2 launch + watcher, minus `remove_login_transcript`: on `ok` stop the terminal, and filter login-only sessions from the Claude provider instead — add `login_only` to `_session_meta` (classify only files < `LOGIN_MAX_BYTES`, reuse `login_transcript_state`'s scanner on the cached path) and skip them in `list_sessions`, `search_sessions` and `newest_session_in_cwd`. **Cost:** a larger diff than deleting (three filter sites + a meta field + its cache invalidation), one extra classification per small file per list poll (mtime-cached); it also hides `/login` sessions the user started by hand; `claude --resume` keeps listing every login session forever; transcripts accumulate (~17 KB each). Benefit: nothing is ever deleted. Recommendation: **delete** (smaller, matches "remove that very session").

### 7. Sequencing
1. `providers/claude.py` helpers + tests 1–2 (pure, no ptys). 2. `term_vt.py` constants, `_login_watch`, `_spawn_dedicated` kwarg, `open_pty` hook + tests 3–4. 3. conventions.md exception (same commit as the deletion code). 4. Gate, restart, manual check, `/branch-sync`, push.

### 8. Riskiest spot + fallback
**`claude --session-id <uuid> "/login"` must write its transcript under that exact id.** The flag is in 2.1.326's `--help`, but its interaction with a slash-command first prompt is unverified until the manual check. If it doesn't hold, the watcher only ever sees `pending` and times out — **nothing is stopped or deleted** (safe failure). Fallback design: drop `--session-id`, leave `pt.spawned` empty, and let the watcher read the id from `pt.spawned` after calling `resolve_spawned(throttle=0, new_only=True)` (the existing atomic latch); the `login_transcript_state == "ok"` check then remains the guard against a mis-latch. Second risk: a future Claude wording change of `Login successful` → same safe failure (nothing removed).

### Decisions for the user
- **D1 — delete vs hide** (§1 vs §6). Recommended: delete the one transcript.
- **D2 — login always in its own dedicated terminal** (never typed into the shared `~` folder shell), so "close that terminal" closes exactly that pty and never your `~` shell. Recommended: yes. (Not auto-closing the browser tab itself — the tab shows the notice and the ended process; closing the tab from JS would be a client change.)

## Adversarial review
_(opus reviewer, 2026-11-17; checked against base 0c93bfc and real files under `~/.claude/projects/-Users-pritammondal/`; no code edited, no suite run, no `claude` session started)_

### What held up (re-derived, not taken on trust)
- **Path.** `openAt('~','new','/login',{gateway:'anthropic'})` → body `{cwd:'~',mode:'new',prompt:'/login',gateway:'anthropic',cols:100,rows:30}` (`web/ext_launch.js` ~L338-340) → session-less arm (`term_vt.py` ~L3285) → `argv = ["claude","/login"]` (~L3304-3309) → cold branch (~L3343) or typed into the idle `~` folder shell (~L3414/L3460). The plan's hook point and its `gw_eff` mirror of L3306 are right.
- **`stop_for_upgrade(pt.id, sid, pt.pid)`** (`term_vt.py:3725`) works for a dedicated pane: `pg = pt.pid`, so `pg != pid` is false; SIGTERM, wait `PARKED_DETACH_WAIT` for `pt.done`, SIGKILL fallback; `Pty.finish()` waitpids (L1629-1650), so `os.kill(pid,0)` raises and `confirmed = gone and pt.done` can be True.
- **`--session-id <uuid>`** is in installed 2.1.326's `--help` ("Use a specific session ID for the conversation (must be a valid UUID)"). There is **no use of it anywhere in the repo** (grep of `aitracker/ tests/ scripts/`), so how it combines with a slash-command first prompt is unproven (F9).
- **Transcript timing (new evidence).** `2028e7c5….jsonl` was created at 20:09:14 local, the same second as its three `/login` user records (`14:39:14.545Z`). Its mtime is 20:10:12, 58 s later, which matches `cost-state.totalDuration = 58128`. So the file **does not exist until `/login` finishes**, and `last-prompt`/`cost-state` are appended **at exit**. "pending while in progress" holds, and the final check after exit sees those extra records (F3 must allow them).
- **Watcher vs `_reap`/`close_pty`.** The watcher keeps its own `pt` reference, so popping it from PTYS is harmless. `stop_for_upgrade` returns `closed` on a closing pane, which falls through to the final check correctly.
- **remember_terminals / Resume all.** Pre-setting `spawned` makes the login pane recordable in `last_terms.json`, but `remembered_terminals()` filters out ids with no transcript (L4542). Login sessions are already recorded today (as live junk), so this is not a regression. No change.

### Findings

**F1 — HIGH — existing tests break, and the broken tests would exec a REAL `claude /login`.**
- Defect: `tests/test_pending_pty_prompt.py:73-91`. `test_login_prompt_pin_anthropic_launcher` (both `gw` iterations; `config.GATEWAY` defaults to anthropic) and `test_login_prompt_anthropic_override_beats_openrouter_default` drive `open_pty` with `prompt:"/login"` against a settled fake folder pty and assert `_inject_argv` got `["claude","/login"]`. Under the plan, `login_sid` forces the cold branch, so `_inject_argv` is never called and `inj.call_args` is `None`, which raises TypeError. Worse, `_open()` (L46-60) does **not** mock `spawn`, so `_spawn_dedicated` really forks `claude --session-id <uuid> /login` in a tmpdir and starts a real `_login_watch` thread during `make check`. The plan's gate list (§4) omits this module.
- Fix direction: rewrite these two pins to the new contract. Keep `test_login_prompt_pin_openrouter_launcher` and the non-login cases exactly as they are (they still type into the shell). Do NOT weaken the assertions to "anything".
- Way: in `OpenPtyRoutePrompt._open`, always patch `term_vt.spawn` with a `side_effect` that returns a fake `Pty(tid="dd1", pid=42425, fd=98, cwd=tmp)` and records argv. Patch `term_vt._login_watch` and `term_vt._warm_root` too. For the two login pins, assert `inj` was not called, recorded argv == `["claude","--session-id",U,"/login"]` with `uuid.UUID(U).version == 4`, the response `folder is False`, and `PTYS["dd1"].overflow and PTYS["dd1"].spawned == U`.
- Test that proves it: the rewritten pins are red on the base (argv lacks `--session-id`) and green after. Also add the module to the §4 gate list.

**F2 — MEDIUM — a transcript vanishing mid-poll empties the whole Claude list for that poll.**
- Defect: `providers/claude.py:995` (`list_sessions`) and `:1207` (`search_sessions`) do `fs.sort(key=os.path.getmtime)` right after `glob`, and `:1245` calls `os.path.getmtime(f)` unguarded. If the watcher unlinks the login file between the glob and the sort, FileNotFoundError propagates. `registry.all_sessions` (L25-34) swallows it, so every Claude row disappears for that poll and the sidebar flashes empty. Search raises the same way. Until now the app never deleted transcripts, and every client polls every ~2 s.
- Repro: patch `glob.glob` to return `[real.jsonl, "/nonexistent/x.jsonl"]`. Actual: `list_sessions()` raises. Expected: it returns the real row.
- Fix direction: make only the mtime reads tolerant. Do NOT change ordering or caching.
- Way: add one helper `def _mtime0(f): try: return os.path.getmtime(f) except OSError: return 0.0`. Use `key=_mtime0` at L995 and L1207, and `"mtime": _mtime0(f)` at L1245. `_session_meta` already handles OSError.
- Test: `test_list_sessions_tolerates_vanished_file` and `test_search_sessions_tolerates_vanished_file` (red before, green after).

**F3 — MEDIUM — "skip every non-user record" deletes sessions that moved on.**
- Defect: §2 `login_transcript_state` skips every record whose type is not `user`. Several such records mean the session did something else. A `continued-in` marker (`providers/claude.py:712-737`) is written when the user parks the TUI into a daemon job (Left arrow at an empty prompt). Other examples are `system` records and `queue-operation`, and an `attachment` can carry user input. Repro: success file + `{"type":"continued-in","continuedInSessionId":J}`. Actual: `"ok"`, so the file is deleted and J's parent link is orphaned. Expected: `"other"`, so it is kept.
- Fix direction: allow only the record types actually observed in login-only transcripts, and classify anything unknown as `"other"`. A future Claude record type then fails safe (the file is kept). Do NOT loosen the user-record rules.
- Way: `_LOGIN_OK_TYPES = frozenset({"last-prompt","mode","permission-mode","session-owner","tools-used","file-history-snapshot","custom-title","agent-name","cost-state"})`. Allow `attachment` only when `str((d.get("attachment") or {}).get("type","")).startswith("hook_")`. The real files hold only `hook_success` from SessionStart. Every other non-user type returns `"other"`.
- Test: in `LoginTranscriptState`, success + `continued-in` → other; success + `{"type":"system"}` → other; success + attachment `queued_command` → other; success + attachment `hook_success` + `cost-state` → ok. Use the real 2028e7c5 record order as the base fixture. Red before.

**F4 — LOW — the stop fires up to 2 s after `Login successful`, with no settle or re-check.**
- Defect: §1 step 2 goes from `"ok"` to `_feed_note` and `stop_for_upgrade` on the same tick. The user barely sees the result. A prompt typed in that window (UserPromptSubmit hook still running, record not yet written) gets SIGTERM'd. Claude may also still be writing its own config after the command result.
- Fix: `LOGIN_SETTLE = 3.0`. On the first `"ok"`, feed the note, sleep `LOGIN_SETTLE`, then re-check that the state is still `"ok"` and that the pane is neither `done` nor `closing`. Only then call stop. Do NOT add any auth-status probe (overbuilt).
- Test: in `LoginWatch`, state returns `"ok"` and then `"other"` after the settle, so stop is never called and the file is kept. Red before.

**F5 — LOW-MEDIUM — a `~` folder shell can permanently latch the deleted id.**
- Defect: `resolve_spawned` (`term_vt.py:2205-2208`) skips `done` ptys when it builds `claimed`. Between the login pane's `done` and the unlink (ms, or ≥2 s when `_agent_sweep` sleeps, L3713-3714), a `~` cwd shell's probe can latch `login_sid`. That shell is often the warm root shell this same open spawned (L3346). Its start precedes the transcript, so it passes `newest_session_in_cwd`. `spawned` is a permanent latch, so that row then shows a deleted id and never renames to the user's real first session.
- Fix: after a successful unlink, clear any other latch on that id. Do NOT change `resolve_spawned`.
- Way: in `_login_watch`, after `remove_login_transcript(sid)` returns True: `with _LOCK: for q in PTYS.values(): if q is not pt and q.spawned == sid: q.spawned = ""` and `if q.folder and q.fg and q.fg.get("session") == sid: q.fg["session"] = ""`. Each line is a plain attribute store, with no I/O under the lock.
- Test: register a fake folder pty with `spawned = U`, run the watcher to removal, assert `spawned == ""`. Red before.

**F6 — LOW — never unlink a transcript a live Claude still holds.**
- Defect: the final check only re-reads the file. An agent-CLI Upgrade during the login window (`upgrade_candidates` lists the pane with target `login_sid`) or a hand-typed `claude --resume <login_sid>` elsewhere leaves a live process on the file. The unlink then happens under it, and its next append re-creates a headless fragment.
- Fix: in `remove_login_transcript` (or the watcher just before it), refuse when `any(r.get("id") == sid for r in running_sessions())`. In the watcher, also refuse when `any(q is not pt for q in _session_ptys(sid))` under `_LOCK`.
- Test: patch `running_sessions` to return `[{"id": U, "pid": 1}]`, so the file is kept. Red before.

**F7 — LOW (design accuracy, no code) — D2's reason is overstated.**
`stop_for_upgrade` handles folder panes without killing the shell (L3762-3763, "A folder pane keeps its shell and tty"). So typing into the `~` shell would *not* kill it. Dedicated is still the right choice, because the pid is known at spawn and `pt.done` is the exit signal. With a folder pane the watcher would have to track `fg` instead. Keep D2 and fix the stated reason. Also disclose to the user: login no longer runs in the `~` shell's tab, and with no `~` shell and ≥3 free slots the existing S3 cold path still warms a `~` root shell beside it.

**F8 — LOW — make the rule-6 exception match the code.**
The draft scopes it to "Config → Server's Log in / Switch account", but the trigger is the body shape, so any caller sending `mode=new` + Anthropic + `/login` qualifies. Reword it to the shape. Also state:
- it acts only from the `_login_watch` thread, never inside a request handler;
- the only signal is `stop_for_upgrade` on that pane's own process group;
- the record-type allowlist (F3);
- the live-holder refusal (F6).
Exact text is in the Clean plan §5.

**F9 — LOW probability, HIGH impact — `--session-id` + `/login` is unverified, and failure is NOT safe.**
§8 calls this a safe failure. That covers only the case where the flag is accepted but writes elsewhere. If claude rejects the combination or exits, **login itself breaks**, and clause 2 ("existing login + switch flow keeps working") regresses. Fix: move the check to Step 0, before any code. The user runs in their own terminal `U=$(uuidgen | tr A-Z a-z); claude --session-id "$U" /login`, presses Esc at the method picker, quits, and confirms that `ls ~/.claude/projects/-Users-pritammondal/$U.jsonl` exists and holds `Login interrupted`. If it fails, use the §8 fallback (no `--session-id`; latch via `resolve_spawned(throttle=0,new_only=True)`).

**Considered and dropped:**
- `last_terms.json` stale entries: filtered on read, and login sessions are already recorded today, so not a regression.
- Wrong-file deletion via uuid collision: a uuid4 plus `find_session`'s `safe_path_component` plus the basename/realpath check make it negligible.
- `_feed_note` garbling the TUI: the structured `notices` channel carries the banner regardless.
- Server restart mid-login: the known gap stays as stated in the plan.

### Verdict table
| # | Severity | Verdict | Fold into clean plan |
|---|---|---|---|
| F1 | High | confirmed, missed by plan | yes |
| F2 | Medium | confirmed | yes |
| F3 | Medium | confirmed | yes |
| F4 | Low | confirmed | yes (3 s settle) |
| F5 | Low-Med | confirmed (timing-dependent) | yes |
| F6 | Low | confirmed (edge) | yes |
| F7 | Low | overstated rationale | doc only |
| F8 | Low | confirmed | yes |
| F9 | Low-prob / High-impact | confirmed | yes (Step 0) |

## Clean plan
_(supersedes §1-§8 above wherever they differ)_

### Step 0 — prove the flag (user, by hand, before any code)
In the user's own terminal: `U=$(uuidgen | tr A-Z a-z); claude --session-id "$U" /login`. Press Esc at the method picker and quit. Expect `~/.claude/projects/-Users-pritammondal/$U.jsonl` to exist and to contain `<local-command-stdout>Login interrupted`. If this fails, switch to the §8 fallback before continuing.

### 1. Behaviour
`POST /api/term/pty` is a **login open** when `mode=="new"`, the effective gateway is Anthropic (`gw if gw in (ANTHROPIC, OPENROUTER) else config.GATEWAY`), and `prompt.strip()=="/login"`. For a login open the server:
1. mints `login_sid = str(uuid.uuid4())`;
2. always spawns a **dedicated** overflow pty running `["claude", "--session-id", login_sid, "/login"]`;
3. presets `pt.spawned = login_sid`;
4. starts `_login_watch(pt, login_sid)`.

The watcher polls every `LOGIN_POLL` (2 s) for up to `LOGIN_WATCH_MAX` (1800 s):
- `"other"` → return, touch nothing;
- `pt.done or pt.closing` → go to the final step;
- timeout → return, touch nothing;
- first `"ok"` → `_feed_note(pt, LOGIN_DONE_NOTE)`, sleep `LOGIN_SETTLE` (3 s), re-check (still `"ok"`, not done/closing; otherwise return or go to the final step). Then call `stop_for_upgrade(pt.id, login_sid, pt.pid)`. If not `confirmed`, return.

**Final step:** wait for `pt.done` (bounded `CLOSE_CONFIRM_WAIT`). Refuse if any other live pty runs `login_sid` (`_session_ptys`, under `_LOCK`). Then call `claude.remove_login_transcript(login_sid)`. On True, clear any other pty's `spawned`/folder `fg["session"]` equal to `login_sid` (under `_LOCK`, no I/O). The whole body is wrapped in `try/except Exception: return`. No client change, no new route, no wire change.

### 2. Exact changes
**`aitracker/providers/claude.py`**
- `def _mtime0(f)` returns `os.path.getmtime(f)` or `0.0` on OSError. Use it at L995 and L1207 (`fs.sort(key=_mtime0, ...)`) and L1245 (`"mtime": _mtime0(f)`). (F2)
- `LOGIN_MAX_BYTES = 262144`
- `_LOGIN_OK_TYPES = frozenset({"last-prompt","mode","permission-mode","session-owner","tools-used","file-history-snapshot","custom-title","agent-name","cost-state"})`
- `def login_transcript_state(sid) -> "ok"|"pending"|"other"` (never raises):
  - `path = find_session(sid)`; None → `"pending"`; size > `LOGIN_MAX_BYTES` → `"other"`.
  - Per line, `json.loads`; a bad **last** line → `"pending"`, a bad earlier line → `"other"`.
  - A truthy `isSidechain` → `"other"`.
  - `type == "attachment"` → skip only if `attachment.type` starts with `"hook_"`, else `"other"`.
  - `type in _LOGIN_OK_TYPES` → skip; any other non-`user` type (assistant, system, continued-in, queue-operation, …) → `"other"`.
  - For `user` records: text = the content str or `"".join` of the text parts (any non-text part → `"other"`):
    - `isMeta` and `text.startswith("<local-command-caveat>")` → skip;
    - `_slash_prompt(text) == "/login"` → `saw_cmd = True`;
    - `text.startswith("<local-command-stdout>")` and `saw_cmd` → `ok |= "Login successful" in text`;
    - anything else → `"other"`.
  - Return `"ok" if ok else "pending"`. (F3)
- `def remove_login_transcript(sid) -> bool` (never raises). Requires all of:
  - `path = find_session(sid)`;
  - `realpath(path)` under `realpath(config.PROJECTS)`;
  - `basename == sid + ".jsonl"`;
  - `login_transcript_state(sid) == "ok"`;
  - `not any(r.get("id") == sid for r in running_sessions())`. (F6)

  Then `os.unlink(path)`, `_META_CACHE.pop(path, None)`, return True. Anything else returns False.

**`aitracker/term_vt.py`**
- Constants next to `PARKED_DETACH_WAIT`: `LOGIN_PROMPT="/login"`, `LOGIN_POLL=2.0`, `LOGIN_SETTLE=3.0`, `LOGIN_WATCH_MAX=1800.0`, `LOGIN_DONE_NOTE="Login complete — closing this terminal and removing its /login session. You can close this tab."` (`uuid` is already imported, L188.)
- `open_pty`: set `login_sid = ""` before the mode branches. In the `elif mode == "new":` arm (L3304), when the login-open test holds, `login_sid = str(uuid.uuid4())` and `argv = [argv[0], "--session-id", login_sid, LOGIN_PROMPT]` instead of `_with_prompt`.
- `open_pty` cold test (L3343): `if mode != "cwd" and (login_sid or fp is None or not fp.startup_done):`. That branch's call (L3366) gets `login_sid=login_sid`. Nothing else in the warm-root logic changes.
- `_spawn_dedicated(..., held=False, login_sid="")`:
  - before `PTYS[pt.id] = pt`, set `pt.spawned = login_sid` when it is set;
  - after registration, `threading.Thread(target=_login_watch, args=(pt, login_sid), name="login-watch-%s" % pt.id, daemon=True).start()`;
  - on `RuntimeError`, skip the watch (login still works and nothing is removed).
- New `_login_watch(pt, sid)` per §1. Reach the provider through `_provider()` (L3594) and return when it is None (the bundle).

**`.claude/rules/conventions.md`** — add the §5 exception under rule 6 in the same commit as the deletion code.

### 3. Failure paths
The §3 table above still applies, plus:
- Session parked or otherwise moved on → `"other"`, kept (F3).
- Prompt typed during the settle → `"other"`, no stop (F4).
- Live holder elsewhere → kept (F6).
- A vanished file during a list poll → the list stays intact (F2).

### 4. Tests (one module per process, `unset TRACKER_AUTH;`)
- New `tests/test_login_session_cleanup.py`:
  - `LoginTranscriptState`: the plan's cases plus the F3 cases. Base fixture in the real 2028e7c5 order, with `last-prompt` and `cost-state` at the end.
  - `RemoveLoginTranscript`: the plan's cases plus a `running_sessions` holder → kept (F6).
  - `OpenPtyLoginArgv`: as in the plan.
  - `LoginWatch`: the plan's cases with `LOGIN_POLL` and `LOGIN_SETTLE` patched to 0.01, plus settle-flip → no stop (F4) and the cleared sibling latch (F5).
  - `VanishedTranscript`: `list_sessions` and `search_sessions` (F2).
- **Rewrite** `tests/test_pending_pty_prompt.py` `OpenPtyRoutePrompt`: `_open` always mocks `spawn`, `_login_watch` and `_warm_root`. The two Anthropic `/login` pins assert the dedicated argv (F1). The OpenRouter `/login` pin and the non-login cases stay byte-for-byte.
- Prove each new or rewritten test RED by reverting its fix.
- Gate: the new module, then `test_pending_pty_prompt`, `test_term_vt`, `test_open_pty_at_root`, `test_term_vt_upgrade`, `test_attached_login_ok`, `test_folder_terminal`, then the full `make check`. **Restart required** (server-side only).
- Manual check: Log in → finish → the note shows, the process exits about 3 s later, the terminal row and the sidebar session are gone, the uuid file is gone. Repeat with Esc: the file stays. Switch account: same as Log in.

### 5. Rule-6 exception (replaces the §5 draft)
> *"Exception (login-session cleanup, user-requested 2026-11-17: \"when the login has happened can you remove that very session once the login/switch account has been completed\"): when a `POST /api/term/pty` asks for `mode=new` on the Anthropic gateway with prompt exactly `/login` (what Config → Server's Log in / Switch account sends), `aitracker/term_vt.py` runs it in a dedicated terminal as `claude --session-id <uuid4 the server generated> /login`, and its `_login_watch()` thread — and only it, never a request handler — may, once that transcript records `Login successful`, stop that terminal's own process group through `stop_for_upgrade` and, only after that process has exited, delete exactly one file, `<config.PROJECTS>/<dir>/<that uuid>.jsonl`, through `providers/claude.remove_login_transcript()`. That function first re-reads the file and refuses unless every record is of a known login-only type (last-prompt, mode, permission-mode, session-owner, tools-used, file-history-snapshot, custom-title, agent-name, cost-state, or a `hook_*` attachment) or one of the `/login` command's own user records (its `<local-command-caveat>`, its `<command-name>/login`, its `<local-command-stdout>`), with no assistant, sidechain or other record, and refuses while any live Claude process or other tracker terminal holds that session. It never deletes any other transcript, the session's sibling directory, `~/.claude/session-env`, `history.jsonl` or anything else under `~/.claude`; a cancelled, abandoned, parked or continued login session, and any session reached through the in-terminal /login control, is left untouched."*

### 6. Sequencing
0. Step 0 (user, by hand).
1. `providers/claude.py`: `_mtime0` + state/remove helpers, with their tests.
2. `term_vt.py`: constants, `_login_watch`, the `_spawn_dedicated` kwarg, the `open_pty` hook, with their tests and the `test_pending_pty_prompt` rewrite.
3. conventions.md exception, in the same commit as step 2.
4. Gate, restart, manual check, `/branch-sync`, push.

### Decisions for the user
- **D1 — delete vs hide.** Recommendation: delete (unchanged).
- **D2 — always a dedicated terminal for login.** Recommendation: yes. The real reason is that the pid is known and its exit is observable; the shared shell would not be killed either way (F7).
- **D3 (new, optional) — should the login tab close itself after removal?** This would be a small client change (`window.close()` on that notice in a `?tty=` tab opened by `window.open`). Default: no, the tab shows the notice.

## Reconciliation (main thread, 2026-11-17)
| # | Finding | Verdict | Note |
|---|---|---|---|
| F1 | `tests/test_pending_pty_prompt.py:73-91` login tests assert the injected `["claude","/login"]`; would go red and spawn a real claude | **confirmed** (read the lines) | Update those tests to the new dedicated argv; mock `spawn`/`_login_watch` |
| F2 | `claude.py:995/1207` `fs.sort(key=os.path.getmtime)` raises on a file deleted between glob and sort | **confirmed** (read the lines) | Tiny `_mtime_or_0` helper; same in `:1245` |
| F3 | Non-user record types ignored → a parked/continued or `system`-bearing session counts as login-only | **confirmed** | Allowlist the record types seen in real login transcripts; anything else = keep |
| F4 | Settle ~3 s and re-check before stopping | confirmed, minor | One re-read; no new machinery |
| F5 | Clear the deleted sid from any other pty that latched it | confirmed, minor | Only if a one-loop change; else drop |
| F6 | Don't delete while another live claude has the sid open | **overstated** | Only the dedicated pty (`pt.done`) runs that sid; keep the plan's `pt.done` gate, no extra process scan |
| F7 | Rationale for dedicated terminal is pid + visible exit, not shell-kill | false alarm on design | Wording only; design unchanged |
| F8 | Reword the rule-6 exception to the real trigger | confirmed | Wording |
| F9 | `--session-id` + `/login` first prompt is unproven; if rejected, login itself breaks | **confirmed — gate** | Step 0 manual check before implementation |

Missed by both: nothing found beyond the above; the in-session `/login` pill stays out of scope.

## User decisions (2026-11-17, verbatim answers)
- Step 0: "File exists, interrupted" → `claude --session-id <U> /login` writes `<U>.jsonl` (F9 discharged).
- D1: "Delete it (Recommended)".
- D2: "1 and open with a modal such that it doesnt takes me to another screen" → always a dedicated terminal, AND it opens in a modal over the current (Config) screen instead of navigating to the terminal view.
- D3: "Yes, auto-close" → the login terminal UI closes itself once the server reports the session removed.

Design changed by D2/D3 (client side now in scope) → re-plan + re-review per rule 3.

## Revised plan (v2)
_(opus plan agent, 2026-11-17; grounded on base 0c93bfc. **This section supersedes the Plan and the Clean plan wherever they differ.** It keeps the Clean plan's server design as amended by the Reconciliation: F6 dropped (no `running_sessions()` scan, no `_session_ptys` refusal); F7 is wording only; F9 is discharged by Step 0 ("File exists, interrupted"). It adds the client scope from D2 and D3.)_

### 0. What the client does today, and what v2 reuses (read in code)
- **Today.** `claudeLoginBlock().login()` (`web/ext_cr_dialogs.js:1641-1651`) calls `ExtLaunch.openAt('~','new','/login',{gateway:'anthropic'})`. `pickDirectory` (`web/ext_launch.js:327-386`) POSTs `/api/term/pty` with 100x30 and calls `ExtVT.bindTty(tty,"")`. It then **`window.open`s a `?tty=` standalone tab** (L370-378). That tab is the "takes me to another screen" behaviour D2 rejects.
- **Terminal into any container: already exists.** `ExtVT.mountInto(container, {tty}, {renderer})` (`web/ext_vt.js:3743-3986`, exported at L3995) attaches a self-contained `Terminal`/`XtermTerminal` to an already-running pty, in any element. It owns its own wrap, its own SSE/raw stream and a `destroy()`. It does not touch the classic overlay singleton. `ext_cr_term.js:351-355` already uses it for the CR inline pane. xterm stays lazy: `XtermTerminal` calls `_loadXtermAssets()` (L1694, L1817) only when it is built, so the ~480KB load happens only when the login modal opens with renderer `xterm` (rule 2 holds).
- **Modal over Config: already exists.** `CR.dialogs.open(name, payload)` (`ext_cr_dialogs.js:448-473`) **stacks** a new REGISTRY dialog on top of the open Config dialog. It moves the focus trap onto the new dialog, and `close()` (L476-486) pops back to Config. `buildChrome(name,title,emo,ctx,wide)` (L407-428) gives the header, the ✕ and backdrop-close. The one gap: a stack entry has no teardown hook (`close()` only removes DOM), and the login modal must close its pty when dismissed. v2 adds `onClose`, beside the existing `onEscape` (L358, L466).
- **Escape.** `onDocKeydown` (L354-361) closes the topmost dialog on any Escape that bubbles to `document`. The grid renderer stops Escape from propagating (`ext_vt.js:1138-1144`), and xterm.js cancels the keys it handles. v2 still does not rely on that: the login dialog's `onEscape` returns `true` (swallow, do not close) while focus is inside the terminal, because Esc is how the user cancels Claude's login method picker.

### 1. Behaviour (server + client)
1. Config → Server → **Log in / Switch account**.
   - The client calls `ExtLaunch.openAt('~','new','/login',{gateway:'anthropic', tab:false})`. The server's login-open test (Clean plan §1) mints `login_sid`, spawns the **dedicated** pty `[launcher,"--session-id",login_sid,"/login"]` and starts `_login_watch`. It also records `LOGIN_OUTCOMES[tty] = "watching"` before the response goes out.
   - `openAt` returns `{ok, tty, renderer, notice}` and opens no tab.
2. The client opens a stacked dialog `claude-login` over Config and mounts the terminal in it: `ExtVT.mountInto(termEl, {tty}, {renderer})`. The user completes `/login` inside the modal.
3. The modal polls **`GET /api/term/login?tty=<tty>`** every 2 s.
   - The server's watcher moves the state `watching → stopping → removed | kept`.
   - On `removed`, the modal destroys its mount and closes itself.
   - Then it calls the login block's `load(true)` (`/api/claude/auth?fresh=1`), so the row shows the new account.
4. **Not completed (`kept`).** Covers cancel / `Login interrupted`, the user typing a real prompt, a watch timeout, a stop that is not confirmed, the bundle, and a dead watcher thread.
   - The modal **stays open**, stops polling and shows a one-line reason.
   - The user closes it with ✕ / backdrop (or Esc when focus is outside the terminal).
5. **Any manual close of the modal**, in any state:
   - stop the poll and `destroy()` the mount;
   - **POST `/api/term/close {tty, session:""}`**, unless the server already reported `removed`;
   - refresh the login status with `load(true)`.
   - Closing during `watching` with a not-yet-successful login → the watcher's final step sees `pending` → kept, and nothing is deleted.
   - Closing after `Login successful` was written → the final step deletes it. That is the session the user asked to remove (same as the Plan §3 "closes manually" row).
6. **Fallback when `window.ExtVT.mountInto` is missing.** The block calls `openAt` exactly as today (no `tab:false`): the old new-tab path. The server-side cleanup still runs.

### 2. The completion signal (server owns it, rule 5)
**Why a new route.** The existing per-tty routes cannot carry the final answer. `GET /api/term/attached` 404s once `pt.done` (`term_vt.py:4804-4805`). `GET /api/term/list` drops the row, because `_reap()` pops a done overflow pty at once (L2386-2387). Yet `removed` is only known *after* the process has exited and the file is unlinked. So the outcome must outlive the pty, and it lives in a small module-level map read by a tiny GET route.

**Data shape**
```text
GET /api/term/login?tty=<id>
 200 {"tty": "<id>", "login": "watching" | "stopping" | "removed" | "kept"}
 404 {"error": "no such login terminal"}       # not a login pty, or its outcome expired
 403 / 401                                      # term_gate.guard, as every /api/term/* route
```
| State | Meaning |
|---|---|
| `watching` | the watcher is polling the transcript |
| `stopping` | `Login successful` was seen, settled and re-checked; `stop_for_upgrade` is running |
| `removed` | the process exited and `remove_login_transcript()` returned True |
| `kept` | the watcher ended any other way |

`removed` and `kept` are terminal states. The watcher's `finally` always writes one of them, so the client can never poll a `watching` that will never change. The route does no filesystem I/O and only one dict read under `_LOCK`. It does no `_req_session` ownership check: the pty is usually gone by the time it matters, the answer is one word, and the id is a random `uuid4().hex[:12]` (`term_vt.py:1385`) behind the same `term_gate.guard`.

### 3. Exact changes — server (Clean plan §2, as reconciled, plus the signal)
**`aitracker/providers/claude.py`** — as in the Clean plan §2, with one F6 change:
- `_mtime0(f)`, used at L995, L1207 and L1245 (F2).
- `LOGIN_MAX_BYTES = 262144`.
- `_LOGIN_OK_TYPES` (F3).
- `login_transcript_state(sid) -> "ok"|"pending"|"other"`, exactly as in the Clean plan.
- `remove_login_transcript(sid) -> bool`. It requires `find_session(sid)`, realpath under `realpath(config.PROJECTS)`, `basename == sid + ".jsonl"` and `login_transcript_state(sid) == "ok"`. It then does `os.unlink` and `_META_CACHE.pop(path, None)` and returns True. **There is no `running_sessions()` check (F6 overstated).** Never raises.

**`aitracker/term_vt.py`**
- Constants next to `PARKED_DETACH_WAIT` (L3586):
  - `LOGIN_PROMPT = "/login"`, `LOGIN_POLL = 2.0`, `LOGIN_SETTLE = 3.0`, `LOGIN_WATCH_MAX = 1800.0`, `LOGIN_OUTCOME_TTL = 600.0`;
  - `LOGIN_DONE_NOTE = "Login complete — closing this terminal and removing its /login session."` (no "close this tab": the modal closes itself);
  - `LOGIN_OUTCOMES = {}` (tty → `{"state": str, "at": float}`, guarded by `_LOCK`).
- `def _login_set(tid, state)`:
  - takes `_LOCK`;
  - prunes entries whose state is `removed`/`kept` and whose `at` is older than `LOGIN_OUTCOME_TTL` (a `watching`/`stopping` entry is never pruned);
  - writes `{"state": state, "at": time.time()}`.
  - It is never called with `_LOCK` already held.
- `open_pty`:
  - set `login_sid = ""` before the mode branches;
  - in the `elif mode == "new":` arm (L3304-3310), compute `gw_eff = gw if gw in (ANTHROPIC, OPENROUTER) else config.GATEWAY` once (the expression L3307 already uses);
  - if `gw_eff == gateway.ANTHROPIC` and `isinstance(body.get("prompt"), str)` and `body["prompt"].strip() == LOGIN_PROMPT`: `login_sid = str(uuid.uuid4())` and `argv = [argv[0], "--session-id", login_sid, LOGIN_PROMPT]`, in place of `_with_prompt`;
  - cold test L3343 becomes `if mode != "cwd" and (login_sid or fp is None or not fp.startup_done):`;
  - pass `login_sid=login_sid` to that branch's `_spawn_dedicated(...)` call (L3366).
- `_spawn_dedicated(spawn_cwd, argv, mode, sid, forked, cols, rows, held=False, login_sid="")` (L3507):
  - if `login_sid`, set `pt.spawned = login_sid` before the `with _LOCK:` block;
  - inside that block, next to `PTYS[pt.id] = pt`, set `LOGIN_OUTCOMES[pt.id] = {"state": "watching", "at": time.time()}` (a direct write: the lock is already held);
  - after the `finally`, when `login_sid` is set, start `threading.Thread(target=_login_watch, args=(pt, login_sid), name="login-watch-%s" % pt.id, daemon=True)`. On `RuntimeError`, call `_login_set(pt.id, "kept")`: login still works and nothing is removed.
  - The response dict is unchanged.
- New `_login_watch(pt, sid)`:
```python
def _login_watch(pt, sid):
    result = "kept"
    try:
        prov = _provider()
        if prov is None:
            return                                   # flattened bundle: never deletes
        deadline = time.time() + LOGIN_WATCH_MAX
        while not (pt.done or pt.closing):
            if time.time() >= deadline:
                return
            st = prov.login_transcript_state(sid)
            if st == "other":
                return
            if st == "ok":
                _feed_note(pt, LOGIN_DONE_NOTE)
                time.sleep(LOGIN_SETTLE)                                   # F4
                if pt.done or pt.closing:
                    break
                if prov.login_transcript_state(sid) != "ok":
                    return
                _login_set(pt.id, "stopping")
                r = stop_for_upgrade(pt.id, sid, pt.pid) or {}
                if not (r.get("confirmed") or r.get("closed")):
                    return                                                 # never delete under a live process
                break
            time.sleep(LOGIN_POLL)
        end = time.time() + CLOSE_CONFIRM_WAIT
        while not pt.done and time.time() < end:
            time.sleep(CLOSE_CONFIRM_POLL)
        if pt.done and prov.remove_login_transcript(sid):                  # re-reads; refuses unless "ok"
            result = "removed"
            with _LOCK:                                                    # F5: plain stores, no I/O
                for q in PTYS.values():
                    if q is not pt and q.spawned == sid:
                        q.spawned = ""
                    if q is not pt and q.folder and q.fg and q.fg.get("session") == sid:
                        q.fg["session"] = ""
    except Exception:
        pass
    finally:
        _login_set(pt.id, result)
```
  `r.get("closed")` covers the user closing the modal during the settle, when `stop_for_upgrade` (L3737-3739) answers `closed: True`. The final step then decides, after `pt.done`.
- New route:
```python
def login_state(handler, parsed):
    """GET /api/term/login?tty=<id> -> {"tty", "login"}; 404 when unknown or expired."""
    if not term_gate.guard(handler):
        return
    from urllib.parse import parse_qs
    tid = parse_qs(parsed.query).get("tty", [""])[0]
    with _LOCK:
        o = LOGIN_OUTCOMES.get(tid)
        state = o["state"] if o else None
    if state is None:
        return handler._json({"error": "no such login terminal"}, 404)
    handler._json({"tty": tid, "login": state})
```
  Register it with `server.EXTRA_GET["/api/term/login"] = login_state` next to L5622.

### 4. Exact changes — client
**`aitracker/web/ext_launch.js`** — `pickDirectory` (L327). After the success branch's `closePicker();` (L363) add:
```js
if (opts && opts.tab === false) return { ok: true, tty: res.j.tty, renderer: res.j.renderer || "grid", notice: res.j.notice || null };
```
- With `tab:false` there is no toast and no `window.open`.
- The POST body is unchanged: `tab` is client-only and never sent.
- The default return stays `{ok:true}` byte-for-byte (pinned by `test_pending_ext_launch`).
- Update the `openAt` comment (L387-388) to name the `tab:false` form.

**`aitracker/web/ext_cr_dialogs.js`**
- **Seam: `onClose`.**
  - In `open()`, the entry literal (L465-466) gets `onClose: built.onClose`.
  - In `close()` (L476), right after `entry.wrap.remove();`: `if (typeof entry.onClose === 'function') { try { entry.onClose(); } catch (e) {} }`.
  - `closeSession()` (L490) needs nothing: it skips session-less entries, and `claude-login` is one.
  - No other dialog sets `onClose`, so every existing dialog is unaffected.
- **New builder `renderClaudeLogin(payload)`**, payload `{tty, renderer, onDone}`. Register it as `'claude-login': renderClaudeLogin` in `REGISTRY` (L3435). It does:
  - `chrome = buildChrome('claude-login', 'Claude Code login', <an existing sprite icon name — grep the symbol list>, '~', true)` and `chrome.panel.classList.add('cr-dialog-login')`;
  - body: one `div.cr-claude-login-status` (text "Complete the login in the terminal below." at first) and one `div.cr-login-term`, the mount container;
  - `handle = window.ExtVT.mountInto(termEl, {tty: payload.tty}, {renderer: payload.renderer})`;
  - `handle.onStatus(t => statusEl.textContent = t)` (connection errors), `handle.onNotice(n => statusEl.textContent = n.text)` (this shows `LOGIN_DONE_NOTE`) and `handle.onForked(() => handle && handle.focus())`;
  - state `done = false, removed = false, timer = null`.
  - `poll()`:
    - `crCall('/api/term/login?tty=' + encodeURIComponent(tty))`, then, if `done`, return;
    - on `body.login === 'removed'`: `removed = true; finish();` then, if `topName() === 'claude-login'`, `close()`. Otherwise do NOT remove the panel by hand (that would desync `_stack`): replace the body text with "Login complete — its /login session was removed." and let the user close it. Then `toast({title: 'Logged in', meta: 'the /login session was removed'})`;
    - on `'kept'`: `finish()`, status "Login not completed here — this session was kept. Close this window when you are done.";
    - on a 404 or `status === 0`: `finish()`, status "Lost track of this login terminal (server restarted?). Close this window.";
    - otherwise (`watching` / `stopping`), status "Closing…" for `stopping`, and `timer = setTimeout(poll, 2000)`.
  - `finish()`: `done = true; clearTimeout(timer); if (handle) { handle.destroy(); handle = null; }`. It is idempotent.
  - `onClose()`:
    - if `!removed`, POST `/api/term/close` with body `window.ExtVT.ttyBody(tty, {}, "")` (= `{tty, session: ""}`), fire-and-forget through `crCall`;
    - `finish()`;
    - `payload.onDone && payload.onDone()`.
    - Ordering: `onClose` runs inside `close()`, so the auto-close path also calls `onDone`, and `removed` suppresses the close POST.
  - `onEscape()`: `return !!(termEl.contains(document.activeElement));` (swallow Esc typed into the terminal).
  - Return `{backdrop, panel, onClose, onEscape}`. No `update` (a same-name re-open is a no-op) and no `wantsPoll`.
- **`claudeLoginBlock().login()`** (L1641):
  - keep the `ExtLaunch` check;
  - compute `inline = !!(window.ExtVT && typeof window.ExtVT.mountInto === 'function')` (read lazily at click time: ext_cr_dialogs sorts before ext_vt);
  - call `L.openAt('~','new','/login', inline ? {gateway:'anthropic', tab:false} : {gateway:'anthropic'})`;
  - on `x.ok === false`, behave as today (`busy=false`, show the message);
  - on success with `inline && x.tty`: keep `busy = true` and call `open('claude-login', {tty: x.tty, renderer: x.renderer, onDone: function () { busy = false; load(true); }})`;
  - otherwise (fallback tab): `busy = false; paint();` as today.
- The warning sub-line (L1626) changes "in a new terminal tab" to "in a terminal window over this page".
- The `onFocus` refresh stays (harmless; still useful on the fallback path).

**`aitracker/web/ext_cr_dialogs.css`** — two rules modelled on `.cr .cr-term-pane` (`ext_cr_term.css:282-290`):
- `.cr .cr-dialog-login .cr-login-term { position: relative; height: min(60vh, 520px); overflow: hidden; background: #12100E; }`
- `.cr .cr-dialog-login .cr-login-term .vttermwrap { height: 100%; }`

(Memory: a stray `*/` in an ext_* CSS file silently kills every later file and the gate misses it, so check the page in the browser.)

No `index.html` / `page.py` change: both files are already concatenated.

### 5. Tests (stdlib unittest, one module per process, `unset TRACKER_AUTH;`; each red when its fix is reverted)
**New `tests/test_login_session_cleanup.py`.** It has every Clean plan §4 class except the F6 case, plus the signal.
- `LoginTranscriptState`:
  - success → ok; `Login interrupted` → pending; missing → pending; truncated last line → pending;
  - success + a user `"hi"` → other; + `assistant` → other;
  - F3: + `continued-in` / `system` / attachment `queued_command` → other; attachment `hook_success` + `cost-state` → ok;
  - the base fixture follows the real 2028e7c5 record order.
- `RemoveLoginTranscript`: ok → unlinked and True; pending/other → kept and False; the sibling `<sid>/` dir and another `.jsonl` are untouched; a path outside `config.PROJECTS` → False.
- `OpenPtyLoginArgv`:
  - `spawn` mocked, `_login_watch` and `_warm_root` patched;
  - argv == `[L, "--session-id", U, "/login"]` with `uuid.UUID(U).version == 4`;
  - the pty is overflow and `spawned == U`;
  - **`LOGIN_OUTCOMES[tty]["state"] == "watching"`**;
  - `_login_watch` called once with `(pt, U)`;
  - an idle settled folder pty for that cwd is not typed into;
  - controls: `prompt:"hi"`, and OpenRouter + `/login` → old argv, no watcher, no `LOGIN_OUTCOMES` entry.
- `LoginWatch` (`LOGIN_POLL`/`LOGIN_SETTLE`/`CLOSE_CONFIRM_POLL` patched to 0.01, `stop_for_upgrade` mocked to set `pt.done=True` and return `{"confirmed": True}`, `_feed_note` mocked):

  | Case | Expected |
  |---|---|
  | ok | stop called with `(pt.id, U, pt.pid)`; file gone; outcome `removed`; the outcome passed through `stopping` (record `_login_set` calls) |
  | pending + `pt.closing` | no stop; file kept; `kept` |
  | other | no stop; `kept` |
  | `confirmed: False` | file kept; `kept` |
  | `{"closed": True}` with `pt.done` and an ok file | removed (the modal-closed-during-settle case) |
  | ok, then `other` after the settle | no stop; `kept` (F4) |
  | sibling folder pty with `spawned == U` | cleared to `""` after removal (F5) |
  | `_provider` → None | `kept` |
  | `login_transcript_state` raises | `kept` (the `finally`) |
- `LoginRoute`: `_FakeHandler`/`_Q` from `tests/test_term_vt.py`, as in `tests/test_attached_login_ok.py`.
  - A seeded outcome → `({"tty":"t1","login":"removed"}, 200)`; unknown → 404.
  - `server.EXTRA_GET["/api/term/login"] is term_vt.login_state`.
  - `_login_set` prunes an old `kept` entry and never a `watching` one.
- `VanishedTranscript` (F2): `list_sessions` / `search_sessions` with a glob that returns a missing path → no raise; the real row is kept.

**Rewrite (F1) `tests/test_pending_pty_prompt.py` `OpenPtyRoutePrompt`.**
- `_open` (L46-60) always patches `term_vt.spawn` with a `side_effect` that records argv and returns `Pty(tid="dd1", pid=42425, fd=98, cwd=tmp)`. It also patches `term_vt._login_watch` and `term_vt._warm_root`, so no real `claude` is ever forked.
- `test_login_prompt_pin_anthropic_launcher` (both `gw` iterations) and `test_login_prompt_anthropic_override_beats_openrouter_default` assert:
  - `inj` not called;
  - recorded argv == `["claude","--session-id",U,"/login"]` with a v4 `U`;
  - response `folder is False`;
  - `PTYS["dd1"].overflow` and `.spawned == U`.
- `test_login_prompt_pin_openrouter_launcher` and the non-login cases stay as they are.
- Update the "Declared pin of current behaviour" comment.

**`tests/test_pending_ext_launch.py`** (node). The harness counts `win.open` calls. Add `out.inline = await openAt('~','new','/login',{gateway:'anthropic',tab:false})` and assert:
- `{"ok":True,"tty":"t1","renderer":"grid","notice":None}`;
- zero `window.open` calls for it;
- its POST body has no `tab` key.

Every existing assertion is unchanged; `out.ok == {"ok": True}` proves the default path is untouched.

**`tests/test_claude_login_settings_ui.py`** (node + the existing fake DOM; `window === global` there). Extend `_BODY`:
- With `SCEN.vt`, set `global.ExtVT = {mountInto(c,t,o){ mounts.push({t,o}); return {destroy(){ destroyed++; }, onStatus(){}, onNotice(){}, onForked(){}, focus(){}}; }, ttyBody: (tty, x, s) => ({tty, session: s})}`.
- `fetch` answers `/api/term/login?tty=` from `SCEN.loginSeq` (last value repeats) and records POSTs to `/api/term/close`.
- The harness **always ends with `CR.dialogs.close()` until the stack is empty**, so a 0 ms-patched poll cannot keep node alive. The poll also stops on `done`.

New cases:
1. `test_click_opens_login_modal_over_config`:
   - opens == `[["~","new","/login",{"gateway":"anthropic","tab":false}]]`;
   - a `[data-cr-dialog="claude-login"]` panel exists **and** the `config` panel is still in the DOM;
   - mounts == `[{t:{tty:"L1"}, o:{renderer:"grid"}}]`.
2. `test_removed_autocloses_and_refreshes`: `loginSeq ["watching","removed"]` →
   - the `claude-login` panel is gone and `config` remains;
   - no `/api/term/close` POST;
   - `destroyed == 1`;
   - gets include `/api/claude/auth?fresh=1`;
   - the button is enabled again.
3. `test_manual_close_closes_its_pty`: `["watching"]`, then `CR.dialogs.close()` →
   - exactly one POST `/api/term/close` with body `{tty:"L1", session:""}`;
   - `destroyed == 1`;
   - a fresh auth GET;
   - no `/api/term/login` request after the close.
4. `test_kept_stays_open`: `["kept"]` → the dialog is still open; the status mentions "kept"; polling stopped (request count stable over extra ticks).

`test_click_opens_login_terminal_once` stays **unchanged**: with no `ExtVT` it now pins the fallback new-tab path.

**Gate.**
1. The new module.
2. Then `test_pending_pty_prompt`, `test_pending_ext_launch`, `test_claude_login_settings_ui`, `test_term_vt`, `test_open_pty_at_root`, `test_term_vt_upgrade`, `test_attached_login_ok`, `test_folder_terminal`, `test_cr_term_login_pill`, each in its own process.
3. Then the full `make check` before the push.

**Restart required**: server and `web/` both change.

**Manual check (both renderers, `TRACKER_TERM_RENDERER=grid` and `xterm`).**
1. Config → Server → Log in. The modal opens over Config and no tab opens.
2. Finish the login. The note shows; about 3 s later the process exits; the modal closes; Config shows the new account; the uuid `.jsonl` is gone; the terminal row is gone.
3. Repeat and press Esc at the method picker. Esc goes to Claude and the modal stays. Then ✕ → the pty closes and the file (`Login interrupted`) stays.
4. Switch account: same as Log in.
5. Check the network tab: the xterm assets load only when the modal opens.

### 6. Rule-6 exception (F8; replaces the Clean plan §5 text — the F6 clause is removed)
> *"Exception (login-session cleanup, user-requested 2026-11-17: \"when the login has happened can you remove that very session once the login/switch account has been completed\"): when a `POST /api/term/pty` asks for `mode=new` on the Anthropic gateway with prompt exactly `/login` (what Config → Server's Log in / Switch account sends), `aitracker/term_vt.py` runs it in a dedicated terminal as `claude --session-id <uuid4 the server generated> /login`, and its `_login_watch()` thread — and only it, never a request handler — may, once that transcript records `Login successful`, stop that terminal's own process group through `stop_for_upgrade` and, only after that terminal's process has exited, delete exactly one file, `<config.PROJECTS>/<dir>/<that uuid>.jsonl`, through `providers/claude.remove_login_transcript()`. That function first re-reads the file and refuses unless every record is of a known login-only type (last-prompt, mode, permission-mode, session-owner, tools-used, file-history-snapshot, custom-title, agent-name, cost-state, or a `hook_*` attachment) or one of the `/login` command's own user records (its `<local-command-caveat>`, its `<command-name>/login`, its `<local-command-stdout>` reporting `Login successful`), with no assistant, sidechain or other record. It never deletes any other transcript, the session's sibling directory, `~/.claude/session-env`, `history.jsonl` or anything else under `~/.claude`; a cancelled, abandoned, parked or continued login session, and any session reached through the in-terminal /login control, is left untouched. The outcome is reported read-only through `GET /api/term/login`."*

### 7. Sequencing (each step leaves `make check` green)
1. `providers/claude.py`: `_mtime0` and the state/remove helpers, with `LoginTranscriptState`, `RemoveLoginTranscript` and `VanishedTranscript`.
2. `term_vt.py`: the constants, `LOGIN_OUTCOMES`/`_login_set`, `_login_watch`, the `_spawn_dedicated` kwarg, the `open_pty` hook and the `login_state` route, with `OpenPtyLoginArgv`, `LoginWatch` and `LoginRoute`, plus **the F1 rewrite in the same commit** (otherwise the gate forks a real `claude`). Add the conventions.md exception in this same commit. The server works with the old client here: the tab path still runs and the session is still removed.
3. `ext_launch.js` `tab:false`, with the `test_pending_ext_launch` addition.
4. `ext_cr_dialogs.js`: the `onClose` seam, `renderClaudeLogin`, the `claudeLoginBlock` change and the CSS, with the `test_claude_login_settings_ui` cases.
5. Gate, restart, manual check (both renderers), `/branch-sync`, re-gate, push the branch to `personal`.

### 8. Riskiest spot + fallback
- **Riskiest: the terminal inside a stacked CR dialog.** `mountInto` has so far run only in the CR terminal overlay. In a dialog it has to:
  - get a real, non-zero box at attach time (`computeColsRows`), or the pty is resized to the minimum;
  - keep keyboard focus (the dialog's `trapFocus` Tab cycling versus the terminal's hidden textarea / xterm textarea);
  - keep Escape for Claude.
- **Mitigations in the plan:**
  - an explicit CSS height on `.cr-login-term`;
  - `onEscape` swallowing Esc that comes from inside the terminal;
  - `handle.focus()` called once `onForked` fires.
- **Fallback if any of these misbehaves in the manual check:** ship steps 1-3 and change only `claudeLoginBlock` to use the existing CR terminal overlay surface instead. Failing that, use the old tab path (drop `tab:false`). The server cleanup and the auto-refresh (via the existing `onFocus` → `load(true)`) still deliver the contract; only D2's "no other screen" would be deferred, and the user would be told.
- **Second risk:** the modal's 2 s poll and the server's 2 s watch interval add up to roughly 3 s settle + 2 s + 2 s ≈ 7 s from `Login successful` to the modal closing. That is acceptable, and the note shows within about 2 s.
- **Third risk (unchanged):** a future Claude wording or record type change. The watcher only ever sees `pending`/`other`, so nothing is deleted, the modal reports `kept`, and the user closes it.

### Decisions for the user (new in v2)
- **D4 — a cancelled login, when you close the modal.** The terminal is killed, but its transcript (`Login interrupted`) is **kept**, because the contract says to remove the session *once login has completed*. Recommended: keep it as designed. The alternative is to also delete `Login interrupted` sessions on close: same guards, one more allowed stdout string, and wider deletion.
- **D5 (FYI) — Esc inside the login terminal goes to Claude (it cancels the method picker), not to the modal.** Close the modal with ✕ or a click outside it.

## Adversarial review (v2)
_(opus reviewer, 2026-11-17. Read-only: grep + sed ranges on base 0c93bfc. Server parts re-checked only where v2 changed them.)_

**Checked and found correct (no finding):**
- `ExtVT.mountInto(container, target, opts)` exists with that signature (`web/ext_vt.js:3743`, exported `:3995`). The `{tty}` path (`:3926-3932`) only binds and attaches. It never spawns and never closes the pty (`spawned=false`). `destroy()` (`:3846-3852`) closes the SSE/raw stream for both renderers (`Terminal.destroy` `:1294`, `XtermTerminal.destroy` `:2013`).
- **Mount order is safe.** With `opts.renderer` set, `resolveRenderer()` is `Promise.resolve`, so `finish()` → `new Terminal(wrap)` runs as a microtask after `open()` has appended the panel to `_layer` (`ext_cr_dialogs.js:458-460`). `Terminal.attach` measures in a rAF (`ext_vt.js:933-941`), so the pane has a real box. No sizing defect, given an explicit height.
- **The `openAt(...,{tab:false})` change is invisible to other callers.** `app.js:2406` calls `L.openAt(r.cwd,"new",r.prompt)` with no `opts`, and the picker's own calls (`ext_launch.js:261-268`) pass none either. `opts && opts.tab === false` is therefore false and the old path runs byte-for-byte.
- **The `onClose` seam is safe.** No builder returns `onClose`. `closeSession()` (`:490-500`) skips `sid ''` entries, and `claude-login` is one. `update()` (`:520-526`) reaches only the top entry, and `claude-login` has no `update`.
- **Esc and Tab.** `onDocKeydown` is a bubble-phase `document` listener (`:371`). The grid renderer's `keyToBytes` maps Escape and Tab (`ext_vt.js:280-281`) and `stopPropagation()`s them (`:1138-1144`). xterm.js cancels the keys it handles. Neither the Esc-close nor `trapFocus` (a panel-level bubble listener, `:338-349`) sees keys typed into a focused terminal. App-level shortcuts skip typing targets (`ext_cr_board.js:3081`, `ext_cr_detail.js:2140`).
- **`POST /api/term/close {tty, session:""}` is accepted for the login pty.** `_pty_owned(p, "")` returns `p.session == ""` (`term_vt.py:3925-3926`), and the pty was opened session-less. `spawned = login_sid` does not matter.
- **Read-only.** `/api/term/login` is not in `server._RO_GET_ALLOW` (`server.py:316`, enforced `:444`), so a tunnel read-only caller is refused, as for every term GET. `term_gate.guard` provides the rest of the gating, as on the sibling routes. `LOGIN_OUTCOMES` growth is bounded: one entry per login click, pruned on each write after 600 s.

| # | Sev | Finding |
|---|---|---|
| R1 | **high** | xterm (the **default** renderer) never gets focus. Enter at Claude's picker clicks ✕ and kills the login |
| R2 | medium | `topName()` is not in scope inside `ext_cr_dialogs.js`, so the `removed` branch throws and D3's auto-close never happens |
| R3 | medium | `kept` → `finish()` destroys the terminal while its pty is still alive |
| R4 | medium | Poll error handling: 401/403/5xx loop forever, and a transient `status 0` stops polling for good |
| R5 | medium | New UI test 1 uses `[data-cr-dialog=…]` selectors, which the fake DOM cannot match, so it can never go green |
| R6 | low | The gate list omits `test_page_bundle` / `test_page_css`, the two tests that catch a load-time throw or a stray `*/` |
| R7 | low (overbuilt) | The new route + `LOGIN_OUTCOMES` + `_login_set` can be replaced by the existing `GET /api/term/attached` 404-on-done |
| R8 | low | The hard-coded `#12100E` login box clashes with the grid pane's classic-palette `var(--app)` |
| R9 | low | `onStatus` overwrites the guidance line with "connected" / "disconnected — reopen this terminal" |
| R10 | low | Known gap: a reload or tab close while the modal is open runs no `onClose` |
| R11 | low (only if the route is kept) | The `login_state` route skips the `session` param, which every sibling tty route requires |

### R1 — xterm: focus stays on ✕, so Enter or Esc aborts the login (high)
- **Defect.** `open()` focuses the first `FOCUSABLE` element in the panel (`ext_cr_dialogs.js:468-469`). That element is the header ✕ `<button>` (`:420`), because the terminal is not built yet. v2 then relies on `onForked → handle.focus()`. For xterm, `XtermTerminal.prototype.focus` is `if (this.term) …` (`ext_vt.js:2009-2011`). `this.term` exists only after `_build()`, which runs after the lazy ~480KB `_loadXtermAssets()` (`:1817`). `fireForked` fires synchronously in `finish()` (`:3922`), long before that. So the focus call is a no-op and focus stays on ✕. xterm is the default renderer (`config.py` `resolve_term_renderer`: `"xterm" (default)`).
- **Repro.** Default config → Config → Server → Log in. Claude shows the login-method picker. The user presses Enter.
  - Actual: the focused ✕ is clicked → `close()` → `onClose` POSTs `/api/term/close`, and the login is killed. Esc does the same: `onEscape` sees `activeElement` = ✕, outside `termEl`, so it does not swallow the key.
  - Expected: the keys reach Claude.
- **Fix direction.**
  - Change: the login dialog moves focus into the terminal once the renderer is actually built.
  - Must NOT change: ext_vt.js's `focus()` semantics, `open()`'s initial-focus rule (shared by every dialog), or any other dialog.
- **Way.** In `renderClaudeLogin`:
  - add `inTerm()`: `var a = document.activeElement; return !!(a && typeof termEl.contains === 'function' && termEl.contains(a));` (the `typeof` guard keeps the fake DOM, which has no `El.contains`, from throwing);
  - add `focusTerm(n)`: `if (!handle || inTerm()) return; handle.focus(); if (n > 0) setTimeout(function () { focusTerm(n - 1); }, 100);`, a bounded ~3 s retry;
  - call `focusTerm(30)` from `onForked`;
  - `onEscape` returns `inTerm()`.
  - This covers both renderers: grid focuses on the first try.
- **Test.** In `test_claude_login_settings_ui`, the `ExtVT` mock's handle counts `focus()` calls and simulates xterm: `focus` takes effect only from the 3rd call onward (set `document.activeElement` to a child the mock appended into `termEl`; give the fake `El` a `contains` in that test only).
  - Assert ≥3 `focus()` calls and that the retry stops once focused.
  - It is red with v2's single `onForked → focus()` (exactly one call).

### R2 — `topName()` is not in scope (medium)
- **Defect.** v2 §4 `poll()` calls `topName()`. The module has only the internal `topEntry()` (`ext_cr_dialogs.js:352`). `topName` exists only as a property of the exported object (`:3476`). Calling it throws `ReferenceError` inside the `crCall(...).then`, so the rejection is swallowed.
- **Repro.** `loginSeq ["watching","removed"]`.
  - Actual: the modal stays open and no toast appears.
  - Expected: the modal closes, as D3 requires.
- **Fix direction.**
  - Change: use the in-scope helper and compare by panel identity.
  - Must NOT change: the exported `topName`.
- **Way.** `var t = topEntry(); if (t && t.panel === chrome.panel) close(); else statusEl.textContent = '…ended. Close this window.';`
- **Test.** v2's own `test_removed_autocloses_and_refreshes` catches this (the panel is still present). Keep that test and make sure it runs red against the v2 text.

### R3 — `kept` tears down a live terminal (medium)
- **Defect.** v2 §4: on `'kept'`, `finish()` calls `handle.destroy()`. But `kept` covers cases where the pty is still running:
  - `other`: the user typed a real prompt after logging in;
  - `LOGIN_WATCH_MAX`: still at the browser step after 30 min;
  - `confirmed: False`.
- **Repro.** The user finishes `/login` and then types `hi`. The state becomes `other`, the watcher returns `kept`, and the modal destroys the mount.
  - Actual: the user is left staring at a status line while their Claude keeps running unseen. Closing the modal then kills it.
  - Expected: the terminal stays usable until the user closes the window.
- **Fix direction.**
  - Change: split *stop polling* from *tear down the mount*. Only pty-gone or a user close tears down.
  - Must NOT change: a user close still closes the pty (no orphan ptys). The transcript of an `other` session is never deleted; the server already guarantees that.
- **Way.** `stopPoll()` (clear the timer, `polling = false`) and `teardown()` (`stopPoll()` plus `handle.destroy()`). `kept` / error → `stopPoll()` only. The status line says "Closing this window ends this terminal."
- **Test.** New UI case `test_kept_keeps_terminal`: the terminal reports kept or stays alive → `destroyed == 0`, the poll has stopped, then `close()` → `destroyed == 1` plus one close POST. It is red with v2 (`destroyed == 1` before close).

### R4 — Poll error handling (medium)
- **Defect.** v2 §4 handles only 404 and `status === 0`. Everything else falls into "otherwise" and re-polls.
  - 401 (TRACKER_AUTH cookie expired), 403 (terminal disabled mid-run) and 500 have no `body.login`, so they re-poll every 2 s forever.
  - `status 0` (a server restart blip) stops polling permanently, even though the server comes back and would answer 404.
- **Repro.** The fetch stub answers 401.
  - Actual: an unbounded GET loop for as long as the modal is open.
  - Expected: one error line, and polling stops.
- **Fix direction.**
  - Change: reschedule only on a 2xx "still running" answer or on `status 0`. Any other non-2xx → `stopPoll()` plus show `body.error`.
  - Must NOT change: 404 still means "the pty is gone".
- **Way.** See the code shape in the Clean plan (v2) §C.
- **Test.** UI case `test_poll_error_stops`: an `attachedSeq` of `[401]` → the request count is stable over extra ticks and the status shows the error. It is red with v2 (the count keeps growing).

### R5 — UI test 1 can never pass (medium)
- **Defect.** The fake DOM's matcher `_m` (`tests/test_cr_dialogs_pending_rows.py:37-39`) supports only `.class`, a tag and `*`. `querySelector('[data-cr-dialog="claude-login"]')` always returns null, so v2 test 1 (and test 2's "panel is gone" check) is vacuous or permanently red.
- **Fix direction.** Change the test, not the DOM shim.
- **Way.** Select `.cr-dialog-login` (v2 already adds that class) and `.cr-dialog-config` (`ext_cr_dialogs.js:1671`).
- **Test.** The tests themselves. Prove test 1 red by not registering `'claude-login'` in `REGISTRY`.

### R6 — The gate omits the tests that catch the memory-note failure (low)
- **Defect.** The memory note: a load-time throw or a stray `*/` in any ext_* file silently kills every later file. `tests/test_page_bundle.py::test_bundle_executes` (it runs the whole assembled bundle in node) and `tests/test_page_css.py` (`test_comments_are_balanced`, `test_no_premature_comment_terminators`) now catch exactly that. v2's per-module gate (§5) names neither. Only the final full `make check` would run them, and that run is OOM-prone here.
- **Fix direction.** Add both to the per-module gate, right after the ext_*.js/.css edits.
- **Way.** The gate list in the Clean plan (v2) §E.
- **Test.** Prove it once: temporarily add a stray `*/` to `ext_cr_dialogs.css` → `test_page_css` is red. Revert with a scoped Edit (never `git stash`).

### R7 — The new route is replaceable by an existing one (low, overbuilt)
- **Defect.** v2 §2 claims the new route is needed because `/api/term/attached` 404s once `pt.done`. That 404 *is* the signal the client needs.
  - On success the server stops the pty, so it is done, and the unlink follows within one `CLOSE_CONFIRM_POLL`.
  - In every `kept` case where the pty is alive, `attached` answers 200, so the modal correctly stays open.
  - If the pty dies for any other reason, there is nothing left to show, so closing is right too.
  - The only things lost are the `stopping` text and the word "removed" in a toast. The `LOGIN_DONE_NOTE` notice already tells the user "Login complete — closing…" (via `onNotice`), and `load(true)` shows the new account.
  - `attached` is already polled every ~2 s per open terminal, with a pgid→comm cache (`term_vt.py:4730-4745`). It needs `session`, and `ExtVT.ttyQuery(tty)` (exported `ext_vt.js:4000`) supplies it.
- **Fix direction.**
  - Drop: `LOGIN_OUTCOMES`, `_login_set`, `LOGIN_OUTCOME_TTL`, the `login_state` route and its registration, the `LoginRoute` test class, the outcome assertions in `OpenPtyLoginArgv` / `LoginWatch`, and the rule-6 sentence "The outcome is reported read-only through GET /api/term/login".
  - Must NOT change: `_login_watch`'s logic and every deletion guard.
- **Way.** `_login_watch` keeps `result`/`finally` only if something still consumes them. Otherwise drop the `finally` write. Keep `try/except Exception: pass`.
- **Test.** `LoginWatch` keeps its file-gone / file-kept / stop-called assertions. The UI tests drive `/api/term/attached` (200 → still open; 404 → auto-close).
- **This is a decision (D6).** Recommended: drop the route. If it is kept, apply R11 and use v2 §2-3 unchanged.

### R8 — Login-box colours clash (low)
- **Defect.** v2 CSS hard-codes `background: #12100E` on `.cr-login-term`. The grid `.vtpane` paints `var(--app)` (`ext_vt.css:94`), which follows the *classic* dashboard's light/dark class. `ext_cr_term.js:360-374` documents exactly this bug for the CR pane and fixes it with `setTheme`.
- **Repro.** Classic set to light → a light pane inside a dark box, with a dark 0-px seam where the pane is shorter.
- **Fix direction.** Change: no hard-coded colour, so the terminal looks like the standalone tab the user already uses. Must NOT change: ext_cr_term's dark pane.
- **Way.** The CSS becomes `.cr .cr-dialog-login .cr-login-term { position: relative; height: min(60vh, 520px); overflow: hidden; }` plus the `.vttermwrap { height: 100%; }` rule.
- **Test.** None (visual; covered by the manual check in both themes). `test_page_css` guards the syntax.

### R9 — Status line clobbered (low)
- **Defect.** `handle.onStatus(t => statusEl.textContent = t)`. `Terminal._openStream` fires "connecting…" and then "connected" (`ext_vt.js:944-946`), which replaces the guidance text at once. On the successful exit the stream errors with "disconnected — reopen this terminal" (`:698`) for up to 2 s before the auto-close.
- **Fix direction.** Use a separate connection line that shows only abnormal states.
- **Way.** `connEl`, with `onStatus(function (s) { connEl.textContent = (s === 'connected' || s === 'connecting…') ? '' : s; })`.
- **Test.** UI case 1 asserts the guidance text is still shown after mount (the mock calls the status callback with "connected").

### R10 — Reload or tab close while the modal is open (low, known gap)
- **What happens.** No `onClose` runs, so the pty lives on.
  - If the login already succeeded, the server watcher still removes the session.
  - Otherwise the pty is reaped by idle TTL (`TERM_IDLE_TTL_MIN`) or the watcher's 30-min cap ends its watch. This is the same as today's tab path when that tab is closed.
- **Direction.** No change. Document it in the PR. Do not add a `pagehide` beacon (`close_pty` needs JSON; overbuilt).

### R11 — If the route is kept: session-less query (low)
- **Defect.** `_req_session`'s docstring (`term_vt.py:3904-3907`) says every tty-addressed caller answers a missing `session` with 400. `login_state` skips it. The plan gives a reason (the pty may be gone; the answer is one word), and that reason holds.
- **Direction.** No behaviour change. Say so in the route docstring. Add `self.assertNotIn("/api/term/login", server._RO_GET_ALLOW)` to `LoginRoute`.

## Clean plan (v2)
_(Supersedes "Revised plan (v2)" §1.3-§1.5, §2, §3's route parts, §4 and §5's UI cases where they differ. Written for D6 = recommended: drop the new route. Server §3 otherwise as v2.)_

### A. Server (`aitracker/providers/claude.py`, `aitracker/term_vt.py`)
- Use v2 §3 exactly, minus:
  - `LOGIN_OUTCOMES`, `LOGIN_OUTCOME_TTL`, `_login_set`;
  - the `LOGIN_OUTCOMES[pt.id] = …` write in `_spawn_dedicated`;
  - the `_login_set(pt.id, "kept")` call on a `RuntimeError` thread start (just leave it: login still works and nothing is removed);
  - `_login_set(pt.id, "stopping")`;
  - the `result` / `finally` in `_login_watch`;
  - `login_state` and its `EXTRA_GET` registration.
- `_login_watch` keeps its whole loop, the settle re-check, `stop_for_upgrade` with the `confirmed`/`closed` test, the bounded wait for `pt.done`, `remove_login_transcript`, the F5 clearing and the outer `try/except Exception: pass`.
- The rule-6 exception text is v2 §6 with its last sentence removed.

### B. `aitracker/web/ext_launch.js`
- v2 §4 unchanged: `if (opts && opts.tab === false) return {ok:true, tty, renderer, notice};` right after `closePicker();`.

### C. `aitracker/web/ext_cr_dialogs.js`
1. **`onClose` seam (v2):**
   - `onClose: built.onClose` in the `open()` entry literal (`:465-466`);
   - in `close()` (`:476`), after `entry.wrap.remove();`: `if (typeof entry.onClose === 'function') { try { entry.onClose(); } catch (e) {} }`.
2. **`renderClaudeLogin(payload)`**, registered as `'claude-login'` in `REGISTRY`. Payload `{tty, renderer, onDone}`.
   ```js
   function renderClaudeLogin(payload) {
     var tty = payload.tty;
     var chrome = buildChrome('claude-login', 'Claude Code login', 'gear', '~', true);
     chrome.panel.classList.add('cr-dialog-login');
     var statusEl = h('div', { class: 'cr-claude-login-status' }, ['Complete the login in the terminal below. Closing this window ends this terminal.']);
     var connEl = h('div', { class: 'cr-claude-login-conn' });
     var termEl = h('div', { class: 'cr-login-term' });
     chrome.body.appendChild(statusEl); chrome.body.appendChild(connEl); chrome.body.appendChild(termEl);
     var handle = null, polling = true, gone = false, timer = null;
     function inTerm() { var a = document.activeElement; return !!(a && typeof termEl.contains === 'function' && termEl.contains(a)); }
     function stopPoll() { polling = false; clearTimeout(timer); timer = null; }
     function teardown() { stopPoll(); if (handle) { handle.destroy(); handle = null; } }
     function focusTerm(n) { if (!handle || inTerm()) return; handle.focus(); if (n > 0) setTimeout(function () { focusTerm(n - 1); }, 100); }   // R1
     handle = window.ExtVT.mountInto(termEl, { tty: tty }, { renderer: payload.renderer });
     handle.onStatus(function (s) { connEl.textContent = (s === 'connected' || s === 'connecting…') ? '' : s; });   // R9
     handle.onNotice(function (n) { if (n && n.text) statusEl.textContent = n.text; });   // shows LOGIN_DONE_NOTE
     handle.onForked(function () { focusTerm(30); });
     function poll() {
       if (!polling) return;
       crCall('/api/term/attached?' + window.ExtVT.ttyQuery(tty)).then(function (r) {
         if (!polling) return;
         if (r.status === 404) {                       // pty gone: login finished (server removed it) or it exited
           gone = true; teardown();
           var t = topEntry();                         // R2: topEntry, not topName
           if (t && t.panel === chrome.panel) close();
           else statusEl.textContent = 'This login terminal has ended. Close this window.';
           return;
         }
         if (r.ok || r.status === 0) { timer = setTimeout(poll, 2000); return; }   // R4: alive, or a transient blip
         stopPoll(); connEl.textContent = (r.body && r.body.error) || ('login status unavailable (' + r.status + ')');
       });
     }
     timer = setTimeout(poll, 2000);
     function onClose() {
       var wasGone = gone; teardown();
       if (!wasGone) crCall('/api/term/close', 'POST', window.ExtVT.ttyBody(tty, {}, ''));
       if (payload.onDone) payload.onDone();
     }
     return { backdrop: chrome.backdrop, panel: chrome.panel, onClose: onClose, onEscape: function () { return inTerm(); } };
   }
   ```
   - There is no `kept` teardown (R3): a live pty keeps its terminal until the user closes the window.
   - The 404 auto-close runs `close()` → `onClose` → no close POST (`gone`) → `onDone`.
3. **`claudeLoginBlock().login()`** is as v2:
   - `inline = !!(window.ExtVT && typeof window.ExtVT.mountInto === 'function')`, read at click time;
   - `openAt(..., inline ? {gateway:'anthropic', tab:false} : {gateway:'anthropic'})`;
   - on `x.ok && inline && x.tty`: keep `busy` and call `open('claude-login', {tty: x.tty, renderer: x.renderer, onDone: function () { busy = false; load(true); }})`;
   - otherwise use today's code.
   - Change the warning sub-line to "in a terminal window over this page". Do not show a "session removed" toast (R7).

### D. `aitracker/web/ext_cr_dialogs.css` (R8)
```css
.cr .cr-dialog-login .cr-login-term { position: relative; height: min(60vh, 520px); overflow: hidden; }
.cr .cr-dialog-login .cr-login-term .vttermwrap { height: 100%; }
```

### E. Tests (each proved red by reverting its fix with a scoped Edit; never `git stash`)
- **Server.** v2 §5 `LoginTranscriptState`, `RemoveLoginTranscript`, `VanishedTranscript`, plus:
  - `OpenPtyLoginArgv` without the `LOGIN_OUTCOMES` assertion;
  - `LoginWatch` without the outcome-state assertions (assert the file is gone / kept, the stop call args, and the F5 clearing);
  - no `LoginRoute`;
  - the F1 rewrite of `test_pending_pty_prompt`.
- **`test_pending_ext_launch`.** As v2.
- **`test_claude_login_settings_ui`.** Extend `_BODY`:
  - **`ExtVT` mock:**
    - `mountInto` records `{t, o}` and returns a handle whose `onStatus` / `onNotice` / `onForked` store their callbacks;
    - `onForked` fires on a 0 ms timer;
    - `focus()` counts calls;
    - `destroy()` counts calls;
    - `ttyBody: (tty, x, s) => ({tty, session: s})` and `ttyQuery: t => 'tty=' + t + '&session='`.
  - **`fetch`:**
    - answers `/api/term/attached?` from `SCEN.attachedSeq` (a status per call; the last one repeats; 200 → `{claude_attached: true, login_ok: false}`);
    - records `/api/term/close` POSTs.
  - **Teardown:** the harness always ends by calling `CR.dialogs.close()` until no `.cr-dialog-wrap` is left.
  - **Cases:**
    1. **open:** opens == `[["~","new","/login",{"gateway":"anthropic","tab":false}]]`. `.cr-dialog-login` and `.cr-dialog-config` are both present (R5). mounts == `[{t:{tty:"L1"}, o:{renderer:"grid"}}]`. After the mock fires `onStatus("connected")`, the status still shows the guidance (R9).
    2. **pty gone auto-closes:** `attachedSeq [200, 404]` → `.cr-dialog-login` is gone and `.cr-dialog-config` remains. Also: zero close POSTs, `destroyed == 1`, an `/api/claude/auth?fresh=1` GET, and the button is enabled.
    3. **manual close:** `[200]`, then `close()` → exactly one close POST `{tty:"L1", session:""}`, `destroyed == 1`, a fresh auth GET, and no `/api/term/attached` request after the close.
    4. **live pty keeps its terminal (R3):** `[200]` for many ticks → `destroyed == 0` and the dialog is open.
    5. **error stops the poll (R4):** `[401]` → the attached-request count is stable across extra ticks, and `.cr-claude-login-conn` shows the error.
    6. **focus retry (R1):** the mock's `focus()` sets `document.activeElement` to a child inside `termEl` only from its 3rd call. That test patches `El.prototype.contains`. Assert ≥3 calls and no further calls once focused.
  - `test_click_opens_login_terminal_once` stays unchanged: with no `ExtVT` it pins the fallback.
- **Gate (one module per process, `unset TRACKER_AUTH;`):**
  1. `test_login_session_cleanup`
  2. `test_pending_pty_prompt`
  3. `test_pending_ext_launch`
  4. `test_claude_login_settings_ui`
  5. **`test_page_bundle`** (R6)
  6. **`test_page_css`** (R6)
  7. `test_term_vt`
  8. `test_open_pty_at_root`
  9. `test_term_vt_upgrade`
  10. `test_attached_login_ok`
  11. `test_folder_terminal`
  12. `test_cr_term_login_pill`
  13. `test_tunnel_readonly`
  14. Then the full `make check`.

### F. Sequencing and manual check
- **Sequencing.** As v2 §7, minus the route. Restart required: both the server and `web/` change.
- **Manual check.** v2 §5, with these changes:
  - Run it in **xterm (the default) first**. Press Enter at the method picker *without clicking the terminal*: it must reach Claude (R1).
  - Run it in light and dark classic themes (R8).
  - Step 2's "modal closes" now follows the pty exiting.

### Decisions
- **D6 — drop the new `GET /api/term/login` route (R7).** Recommended: drop it and auto-close on the existing `/api/term/attached` 404. Alternative: keep v2 §2-3's route, add R11, and in the client poll use `{login}`, with `removed` → teardown + close; `watching`/`stopping` → reschedule; `kept` → `stopPoll()` only (R3); 404 → teardown; other non-2xx → stop (R4).
- D4 and D5 are unchanged.

## Reconciliation (v2, main thread, 2026-11-17)
| # | Finding | Verdict | Note |
|---|---|---|---|
| R1 | Dialog focuses ✕ (`ext_cr_dialogs.js:468`); xterm built after lazy load → Enter at the method picker hits ✕ | **confirmed** (read the lines) | Bounded focus retry + `onEscape` returns `inTerm()` |
| R2 | `topName()` only on the exported object (`:3481`), module has `topEntry()` (`:352`) → ReferenceError on auto-close | **confirmed** (read the lines) | Use `topEntry()` and compare panel |
| R3 | `kept` tears down a still-running terminal | confirmed | Split `stopPoll()` / `teardown()` |
| R4 | Poll loops forever on 401/403/5xx, stops on transient 0 | confirmed | Bounded backoff; stop on 4xx except 404 |
| R5 | UI test selector the fake DOM can't match | confirmed | Use class selectors |
| R6 | Gate omits `test_page_bundle`/`test_page_css` (load-time throw / stray `*/`) | confirmed | Add to per-module gate |
| R7 | New `/api/term/login` + `LOGIN_OUTCOMES` overbuilt; `/api/term/attached` 404 on exit suffices | **confirmed — overengineered** (route exists `term_vt.py:4776`) | Pending user D6; default drop |
| R8–R10 | Light-theme box, status overwrite, reload leaves pty (known gap → PR note) | confirmed, low | |
| R11 | `session` param on the new route | moot if R7 accepted | |

## User decisions round 2 (2026-11-17, verbatim) + amendment to Clean plan (v2)
- D6: "Reuse /attached (Recommended)" → R7 accepted: NO `/api/term/login`, NO `LOGIN_OUTCOMES`/`_login_set`. The modal polls existing `GET /api/term/attached?tty=`; 404 (pty gone) → close modal, `load(true)`, toast "Logged in". R11 moot.
- D4: "Delete it too" → the watcher also deletes a /login-only transcript whose `/login` stdout is `Login interrupted` (or any mix of /login runs), once that dedicated pty is done (user closed the modal). Deletable = allowlisted record types only, every user record is caveat / `/login` command / its `<local-command-stdout>`, ≥1 such stdout. Success still triggers stop + delete as before; an interrupted-only transcript is deleted only after `pt.done` (never stops a live claude for it). Rule-6 exception text: "a /login-only transcript (successful or interrupted)".
- D5: "Esc closes modal" → `onEscape` does NOT swallow Esc from the terminal; Esc closes the modal → POST `/api/term/close` → (D4) cleanup. R1's focus retry stays (Enter must reach the terminal, not ✕); drop the `inTerm()` Esc logic.
- Sign-off: "1 with /tracker-gap" → implement via the tracker-gap skill. D4/D5 folded as this amendment without another plan/review round (user said proceed); the opus implementation review must cover them.

## Implementation review — client
_(opus adversarial reviewer, 2026-11-17. Read-only: `git diff` of ext_launch.js / ext_cr_dialogs.css / the two UI tests, grep + sed ranges of ext_cr_dialogs.js, ext_vt.js, term_vt.py and vendor/xterm.js. Ran `unset TRACKER_AUTH; python3 -m unittest tests.test_page_bundle tests.test_page_css tests.test_claude_login_settings_ui tests.test_pending_ext_launch`: 35 tests, OK. Nothing edited, no stash.)_

**Checked and found correct (no finding):**
- **Every close path tears down.** ✕ (`buildChrome` `:429`), click-outside (`:430`, backdrop mousedown), Esc with focus outside the terminal (`onDocKeydown` `:354-361`), the `dialog:close` bus (`:377`) and the 404 auto-close all go through `close()` (`:476`). `close()` pops the entry, so `onClose` runs once per entry. `onClose` → `teardown()` clears the poll timer and calls `handle.destroy()`, which closes the SSE/raw stream (`ext_vt.js:3846-3852`). `focusTerm` stops on `!handle`. A poll already in flight returns on `!polling`. `closeSession` (`:491`) skips `sid ''`, and the login entry is `''`. No leaked timer, poll or stream.
- **No close POST after a 404.** `gone = true` is set before `close()`, and `onClose` reads it as `wasGone`. `test_pty_gone_auto_closes` pins `closes == []`.
- **Other dialogs are unchanged.** No other builder returns `onClose`, and the call is wrapped in `try/catch`. `ext_cr_term.js:714`'s `CR.dialogs.close()` only runs when manage-terminals is on top.
- **The resume path is unchanged.** `app.js:2406` `L.openAt(r.cwd,"new",r.prompt)` passes no `opts`, so `opts && opts.tab === false` is false and the old toast / `window.open` path runs. `test_pending_ext_launch` asserts `tabOpens == 1` without `tab:false`.
- **The server returns `tty`.** `open_pty` → `{"tty": pt.id, ..., "renderer": config.TERM_RENDERER, "notice": None}` (`term_vt.py:3558`). `pickDirectory` binds it `""` (`ext_launch.js:351`), so `ttyQuery` sends `&session=`. `attached()` (`term_vt.py:4842-4874`) accepts it via `_pty_owned(p, "")` and answers 404 only on `pt is None or pt.done`.
- **xterm is still lazy.** The modal only calls `mountInto`. `_loadXtermAssets()` runs inside `XtermTerminal.attach` (`ext_vt.js:1817`), only when the modal opens with renderer `xterm`.
- **Focus works for both renderers.** Grid focuses its input in the constructor (`ext_vt.js:901`), and xterm focuses at the end of `_build` (`:1893`). Both run after `open()`'s ✕ focus, because `finish()` runs as a microtask. The `focusTerm(30)` retry is a harmless belt-and-braces.
- **No load-time error.** `test_page_bundle` and `test_page_css` are green. The CSS diff is two plain rules: no `*/` and no hard-coded colour (R8).
- **The tests run the real code.** `ext_cr_dialogs.js` is `eval`'d, and only `ExtVT` and `fetch` are mocked. The mock handle's API matches the real one (`onStatus/onNotice/onForked/focus/destroy`, `ext_vt.js:3839-3862`), and so does `ttyQuery`'s `tty=L1&session=` shape. `test_pending_ext_launch` runs the real `ext_launch.js` in a `vm`.

| # | Sev | Finding |
|---|---|---|
| C1 | **medium** | D5 is not delivered. Esc typed in the terminal never reaches the dialog layer: it goes to Claude, and the modal stays open |
| C2 | medium | The "Logged in" toast fires on any pty exit (exit, crash, server restart), not just on a completed login |
| C3 | low | The status-0 blip cap (`++blips < 5`) has no test |
| C4 | low | If `open('claude-login', …)` throws, `busy` sticks and the spawned pty is orphaned |

### C1 — D5 not delivered: Esc goes to Claude, not to the modal (medium)
- **Defect.**
  - `ext_cr_dialogs.js:1666-1709` dropped `onEscape` and relies on `onDocKeydown`, a bubble-phase `document` listener (`:371`).
  - Both renderers stop Escape from bubbling while they have focus:
    - grid: `keyToBytes` maps Escape (`ext_vt.js:281`), then calls `ev.stopPropagation()` (`:1144`);
    - xterm: `_keyDown` → `this.cancel(e, true)` → `e.preventDefault(), e.stopPropagation()` (vendor/xterm.js).
  - The terminal holds focus from the moment it is built (`:901` / `:1893`, plus `focusTerm`), so Esc effectively never closes the modal.
  - The new comment at `ext_cr_dialogs.js:1668` ("Esc is not swallowed: it closes the modal") is false.
- **Repro.** Config → Server → Log in. Claude shows the method picker. Press Esc.
  - Actual: Claude gets `\x1b` and cancels the picker (`Login interrupted`). The modal stays open.
  - Expected (D5 verbatim, "Esc closes modal"): the modal closes → `onClose` POSTs `/api/term/close {tty, session:""}` → D4 cleanup.
- **Fix direction.**
  - Change: the login dialog intercepts a bare Escape before the terminal sees it.
  - Must NOT change: ext_vt.js key handling (every other terminal keeps Esc → the program), `onDocKeydown`, `open()` or `close()`.
  - If the main thread would rather keep Esc → Claude, that reverses D5 and needs the user's say-so. In that case fix only the comment, and record D5 as not discharged.
- **Way.** In `renderClaudeLogin`, after `buildChrome`:
  ```js
  chrome.panel.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault(); e.stopPropagation();
    var t = topEntry(); if (t && t.panel === chrome.panel) close();
  }, true);   // capture: runs before the grid input's / xterm textarea's own keydown
  ```
  - Fix the `:1668` comment.
  - The listener dies with the panel, so it needs no cleanup.
- **Test.** `test_claude_login_settings_ui` → `test_escape_in_terminal_closes_modal`:
  - SCEN `escape: true`, `attachedSeq [200]`;
  - after `await tick(3)`, run `(q('cr-dialog-login').handlers.keydown || []).slice().forEach(f => f({key: 'Escape', preventDefault() {}, stopPropagation() {}}))`, then `tick(8)`;
  - assert that login is gone and config remains, `closes == [{tty: "L1", session: ""}]` and `destroyed == 1`.
  - It is red today: the only panel keydown handler is `trapFocus`'s Tab handler, so the modal stays open with zero closes.

### C2 — "Logged in" toast on any pty exit (medium)
- **Defect.**
  - `ext_cr_dialogs.js:1694` calls `toast('Logged in')` on every 404.
  - `attached()` answers 404 whenever `pt is None or pt.done` (`term_vt.py:4865`). That includes:
    - the user cancelling the login and then running `/exit` or pressing Ctrl+C twice;
    - claude crashing;
    - a server restart (PTYS is empty, so the first poll after the restart gets a 404);
    - the pty being closed from Manage Terminals.
  - So the client claims a success the server never reported, which breaks conventions rule 5 (the server owns the truth).
  - The amendment's "404 → toast 'Logged in'" is the spec bug the implementer copied.
  - A modal the user closes correctly shows no toast: `close()` → `onClose` never toasts.
- **Repro.** Open the login, press Esc in the picker (`Login interrupted`), then type `/exit`.
  - Actual: the next poll gets a 404 → a "Logged in" toast, and the modal closes, while `/api/claude/auth` still says logged out.
  - Expected: no success toast. The Config status line repaints from the server.
- **Fix direction.**
  - Change: the toast is driven by the fresh `/api/claude/auth` answer, not by the 404.
  - Must NOT change: the 404 auto-close, the suppressed close POST, the `load(true)` refresh, or the user-close path (still no toast).
- **Way.**
  - Delete `toast('Logged in');` at `:1694`.
  - `onClose` → `payload.onDone(wasGone)`.
  - `claudeLoginBlock`: `onDone: function (ended) { busy = false; load(true, ended); }`.
  - `load(fresh, announce)`'s `.then` adds, after `paint()`: `if (announce && r.ok && r.body && r.body.logged_in) toast({ title: 'Logged in', meta: r.body.label || '' });`.
  - `toast` is in module scope (`:273`).
- **Test.** Two UI cases, both `attachedSeq [200, 404]`. Add `out.toasts = root.querySelectorAll('.cr-toast-title').map(x => x.textContent)` to the `vt` branch output.
  - `authSeq [_auth(False), _auth(False)]`: assert there is no "Logged in". It is red today.
  - `authSeq [_auth(False), _auth(True)]`: assert exactly one "Logged in".

### C3 — Blip cap untested (low)
- **Defect.** `:1700` (`if (r.status === 0 && ++blips < 5)`) is the R4 "transient status 0" branch. No test sends a status 0, so removing or inverting the cap would stay green.
- **Fix direction.**
  - Change: add tests only.
  - Must NOT change: any code.
- **Way.**
  - In the test `fetch` mock, an `attachedSeq` value of `0` → `attached.push(url); return Promise.reject(new Error('net'))`. `crCall` maps that to `{status:0, body:{error:'net'}}`.
  - `test_blips_capped`: `[0]` with enough ticks for more than 5 polls, on the same timer setup `test_poll_error_stops_poll` uses. Assert `attached == 5` and that `'net'` is in `conn`.
  - `test_blip_recovers`: `[0, 0, 200, 404]` → the modal auto-closes and `closes == []`.
- **Test.** These cases are the test. They go red if the cap is removed (the count grows) or if status 0 stops at once (`attached == 1`).

### C4 — `open()` throwing leaves `busy` stuck and the pty orphaned (low)
- **Defect.**
  - `ext_cr_dialogs.js:1648-1651` calls `open('claude-login', …)` inside the first `.then` handler. The second `.then` argument only catches a rejection of `pr`.
  - So a builder throw (for example `mountInto` throwing) becomes an unhandled rejection:
    - `busy` stays true, and the button stays disabled until Config is rebuilt;
    - the `tab:false` pty is left with no tab, no modal and no viewer until the idle TTL.
- **Repro.** The `ExtVT.mountInto` mock throws.
  - Actual: the button stays disabled, no message appears and there is no close POST.
  - Expected: the error is shown, the button is re-enabled and the pty is closed.
- **Fix direction.**
  - Change: guard only that call.
  - Must NOT change: the success path or the fallback tab path.
- **Way.** `try { open('claude-login', {...}); } catch (e) { crCall('/api/term/close', 'POST', window.ExtVT.ttyBody(x.tty, {}, '')); busy = false; msg = 'Log in failed: ' + e; paint(); } return;`
- **Test.** UI case with SCEN `mountThrows: true`: assert `closes == [{tty:"L1", session:""}]`, `btnDisabled == false`, and that the block text contains "Log in failed". It is red today (zero closes, button disabled).

**Not examined:**
- The server half: the claude.py / term_vt.py watcher and the D4 deletion guards.
- Real-browser rendering:
  - light and dark themes;
  - xterm inside the modal;
  - whether the 520px pane fits inside `.cr-dialog-wide`.

  This needs the manual check in Clean plan (v2) §F.
- R10 is still a known gap for the PR body: a reload while the modal is open leaves the pty running until the idle TTL.

## Implementation review — server
_(opus adversarial reviewer, 2026-11-17. Scope: `aitracker/providers/claude.py`, `aitracker/term_vt.py`, the conventions.md rule-6 text, `tests/test_login_session_cleanup.py`, `tests/test_pending_pty_prompt.py`. I assumed the implementer's report was false and checked it against the code and against real transcripts under `~/.claude/projects`. I ran `unset TRACKER_AUTH; python3 -m unittest tests.test_login_session_cleanup` (29 OK) and `tests.test_pending_pty_prompt` (10 OK), one module per process.)_

**Result.** 0 high, 0 medium, 5 low. Nothing found can delete a transcript that is not this server's own `/login` session, or one that holds real work. Every finding either fails safe (the transcript is kept) or is a text, test or documentation gap.

### What held up (re-derived)
- **Only the minted session id can be deleted.**
  - `login_sid` is a server `uuid4`. It is set only when `mode=="new"`, `gw_eff == ANTHROPIC` and the prompt `.strip() == "/login"` (`term_vt.py` `open_pty`, the `elif mode == "new":` arm).
  - The only `/login` sender in `web/` that posts a new open is Config's `claudeLoginBlock` (`ext_cr_dialogs.js:1646`). The in-terminal `/login` control (`ext_vt.js:2489`, `ext_cr_term.js:313`) uses the inject route, so it never reaches this branch.
  - `remove_login_transcript` guards it in three ways:
    - `find_session` runs `safe_path_component`, which rejects glob characters and traversal;
    - the basename must be `sid + ".jsonl"`;
    - the realpath must lie under `realpath(config.PROJECTS)`, which also refuses a symlink that points outside it.
  - Its only caller is `_login_watch`, which runs on its own daemon thread, never in a request handler.
- **OpenRouter `/login` behaves as before.** `gw_eff == OPENROUTER` falls through to `_with_prompt`, `login_sid` stays `""`, and the cold test is unchanged for it. This is pinned by `test_login_prompt_pin_openrouter_launcher`, which asserts the inject argv, `spawned == []` and that no watcher starts.
- **The forced dedicated pty is tested on the live path.** `_open` seeds a warm folder pty (`startup_done=True`). Reverting `login_sid or` in the cold test sends `/login` to `_inject_argv`, and `inj.assert_not_called()` goes red.
- **Real work is never classified as login-only.**
  - Two real transcripts were checked: `-Users-pritammondal/2028e7c5…` (success) and `e25c63ac…` (interrupted).
  - Both hold only allowlisted header types, `hook_success` attachments and the caveat, `/login` and stdout user records, with `last-prompt` and `cost-state` written at exit. Every one of those is allowlisted, so the post-exit re-read still classifies the file as `ok` or `interrupted`.
  - A typed prompt goes to the model, which writes an `assistant` record → `other`.
  - A sidechain record → `other`; non-text content → `other`; any other slash command (`/exit`, `/status`) → `other`.
  - A user record that merely contains `<command-name>/login</command-name>` (`_slash_prompt` uses `.search`) still needs a stdout record before it counts. A real prompt also gets an assistant reply, so this cannot be exploited.
- **A resumed session is protected while the login pty is alive.**
  - `pt.spawned = login_sid` is set up front, and `_session_ptys` matches `p.spawned == sid` (`term_vt.py:3963`).
  - So a sidebar resume of the login session attaches to the modal's own pty. It does not start a second `claude --resume`.
- **No deletion under a live process.**
  - **Success path:** `stop_for_upgrade` returns `confirmed` only when `os.kill(pid, 0)` raises and `pt.done` is set. Without that the watcher returns without deleting.
  - **Close path:** the watcher deletes only when `pt.done` is set within `CLOSE_CONFIRM_WAIT`. `close_pty` SIGKILLs the process group (`term_vt.py:4296`).
  - **Interrupted path:** an interrupted transcript is deleted only after `pt.done`, and the watcher never stops a live claude for it.
- **The watcher thread is bounded.**
  - Every loop pass sleeps `LOGIN_POLL`.
  - It exits on done or closing, `other`, the `LOGIN_WATCH_MAX` deadline, or the single `ok` branch.
  - The tail adds at most one `PARKED_DETACH_WAIT` + 2×`CLOSE_CONFIRM_WAIT`.
  - Every exception is swallowed, so the file is kept.
  - The flattened bundle gets `_provider()` None and returns at once.
- **The tests exercise the real code.**
  - `LoginWatch` runs the real `_login_watch` against the real provider module (the same object `_provider()` imports) in a temp `PROJECTS`. Only `stop_for_upgrade` and `_feed_note` are mocked.
  - `OpenPtyRoutePrompt` drives the real `open_pty` → `_spawn_dedicated`. Only `spawn`, `_warm_root` and `_login_watch` are mocked.

### S1 — Rule-6 text understates when a *successful* transcript is deleted (low)
- **Defect.**
  - **The code.** `term_vt.py` `_login_watch` has two branches that skip `stop_for_upgrade`:
    - `if pt.done or pt.closing: break` after the settle;
    - `r.get("closed")`.
    Either way, an `ok` transcript is deleted once the pty is done, with no stop. A plain close before the first `ok` poll does the same: the loop exits, and `remove_login_transcript` accepts `ok`.
  - **The text.** The conventions.md exception says a successful transcript is deleted "after … first stopping that terminal's own process group through `stop_for_upgrade` and waiting for it to exit". It allows the "once that terminal is done" path only "for a transcript that only recorded an interrupted `/login`".
  - **Repro.** A transcript with `Login successful`, then the user clicks ✕ during the 3 s settle. Actual: deleted after `pt.done` without a stop (`test_closed_during_settle_deletes_after_done`). Expected by the text: kept, or the text should allow it.
- **Fix direction.** Change the text only. The behaviour is the one the plan intended (Revised plan v2 §1.5: "Closing after `Login successful` was written → the final step deletes it"). Do **not** change the code.
- **The way.** In the conventions.md exception, replace "or, for a transcript that only recorded an interrupted `/login`, once that terminal is done" with "or, for a successful or interrupted `/login` transcript, once that terminal is done (the user closed it)".
- **Test.** None needed for wording. `test_closed_during_settle_deletes_after_done` already pins the behaviour.

### S2 — "continued … is left untouched" is not enforced for an external resume (low, known gap)
- **Defect.**
  - The rule text promises "a login session that … was parked or continued … is left untouched". The code (`remove_login_transcript`, `login_transcript_state`) refuses only once the continuation has written a record outside the allowlist. F6, the `running_sessions()` and `_session_ptys` refusal, was dropped by the user's reconciliation.
  - Inside the tracker the gap is closed while the pty lives: `spawned` is a resume hit.
  - Outside it, the gap is open. **Repro:** the user runs `claude --resume <login uuid>` in their own shell during the login, types nothing, then the modal closes. Actual: the file is unlinked under that live process. A resume re-appends only allowlisted header types. Expected by the text: kept.
  - It is hard to hit, because the uuid is shown nowhere except the sidebar row.
- **Fix direction.** Change the text, and add a line to the PR body. No code change: F6 was overruled. Do **not** re-add `running_sessions()`.
- **The way.** In the exception, change "a login session that took a real prompt, timed out, was parked or continued" to "a login session that took a real prompt or any record outside that list (so a parked or continued session once it writes), or that timed out". Add one line to the PR body under known gaps.
- **Test.** None (documentation).

### S3 — `atis-latch` is not on the allowlist, so cleanup could silently do nothing on some Claude builds (low, fails safe)
- **Defect.** `claude.py` `_LOGIN_OK_TYPES` has no `atis-latch`. Evidence from the last 300 transcripts:
  - On Claude 2.1.325, 23 of 25 sessions contain `{"type":"atis-latch","atis":""}`. The value is always `""` (1182 records).
  - It sits in the same header block as `mode`, `permission-mode` and `session-owner`. In 15 sessions it comes before the first user record.
  - It also appears in a message-less session's exit flush (`6c1c5dc5…`: `custom-title`, `mode`, `permission-mode`, `atis-latch`, `worktree-state`, `cost-state`).
  - The two real `/login` transcripts do not have it, so today's live path works.
  - **Repro:** `records(extra=[{"type": "atis-latch", "atis": ""}])`. Actual: `login_transcript_state` → `"other"`, the watcher returns at once, and the transcript is kept. Expected: `"ok"`.
- **Fix direction.**
  - Add `"atis-latch"` to `_LOGIN_OK_TYPES`. It is a content-free latch, and any real work also writes user or assistant records, so allowing it cannot admit real work.
  - Add `atis-latch` to the list in the rule-6 text in the same commit.
  - Do **not** add `ai-title`, `agent-setting`, `worktree-state`, `relocated`, `pr-link`, `api-request*` or `queue-operation`. Those mark real work.
- **The way.** Add the one frozenset entry (`claude.py:1286`), and the word in the conventions.md list "(last-prompt, mode, …, cost-state, atis-latch, or a `hook_*` attachment)".
- **Test.** In `LoginTranscriptState`, add `test_atis_latch_is_login_metadata`: `self.assertEqual(self.st(records(extra=[{"type": "atis-latch", "atis": ""}])), "ok")`. It is red before the fix (`"other"`).

### S4 — The open-path test does not check what the watcher is started with, and races the thread (low, test gap)
- **Defect.**
  - `tests/test_pending_pty_prompt.py` `_assert_dedicated_login` calls `self.watch.assert_called_once()` with no arguments. Its repro: change `args=(pt, login_sid)` to `args=(pt, sid)` in `_spawn_dedicated` (`term_vt.py`, the `threading.Thread(target=_login_watch…)` call). The watcher then polls the request's `""` session and never deletes anything, but the test stays green.
  - The mock is also called on the new thread, while the assertion runs right after `open_pty` returns. Under load the call may not have been recorded yet, so the test can flake.
- **Fix direction.** Make the test wait for the call deterministically and assert its arguments. Do not change production code.
- **The way.** In `_open`, use `mock.patch.object(term_vt, "_login_watch", side_effect=lambda pt, sid: self._watched.set())`, with `self._watched = threading.Event()` in `setUp`. Then in `_assert_dedicated_login`:
  - `self.assertTrue(self._watched.wait(2))`;
  - `self.assertEqual(self.watch.call_args[0], (term_vt.PTYS["dd1"], argv[2]))`.
- **Test.** This change is the test. It goes red with the wrong-`sid` mutation above.

### S5 — At the terminal cap, Log in now gets a 429 where it used to reuse the warm `~` shell (low, behaviour change)
- **Defect.** The forced dedicated branch (`term_vt.py` cold test `login_sid or fp is None or not fp.startup_done`) always reserves a slot. With `MAX_TERMS` live terminals and a warm `~` folder shell, Config → Log in now returns `429 "too many running terminals (max N)"`. Before, it typed `claude /login` into that shell. The plans never mention it.
- **Fix direction.** No code change. A dedicated pty is what makes the exit observable (D2). Write it up in the PR body. Do **not** fall back to the shell inject for login, because that would lose the known session id.
- **The way.** Add one line to the PR body: "Log in / Switch account needs a free terminal slot (always a dedicated terminal); at the cap it shows the cap error with the terminal list."
- **Test.** Optional pin in `OpenPtyRoutePrompt`: with `config.MAX_TERMS = 1` and the seeded warm `fo1`, an Anthropic `/login` open → code 429 and `spawned == []`.

### Unverified (cannot run `claude` here): closing the modal at the method picker
- Claude writes the caveat, `/login` and stdout records together, when the command completes (same-millisecond timestamps in both real files). `close_pty` SIGKILLs.
- So ✕, or D5's Esc, at the picker, before Claude has handled the Esc, leaves no `/login` records. The file is then either missing (lazy materialisation, the likely case) or header-only.
- Either way the state is `pending` → kept. That is correct per D4 (≥1 stdout required). But if a header-only file is created and listed, it would show as a leftover session.
- **Manual check to add to §F.** Open Log in, close with ✕ at the picker, then `ls ~/.claude/projects/-Users-pritammondal/` for that uuid. Expect no file.
- **If a file is present.** Handling it would need a user decision: also delete an allowlisted-only, zero-user-record file once `pt.done`. That changes D4 and the rule-6 text.
