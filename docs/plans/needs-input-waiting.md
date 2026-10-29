# Plan (rev 2): "Needs input" jobs → "Waiting on you", native resume buttons, read-only remote viewing

Branch `worktree-needs-input-waiting` (base `594ac65`). Authored by an opus Plan agent; rev 2 applies the 14 amendments from an opus adversarial review (F-ids tagged). Status column maintained by the orchestrator.

## 0. Contract (verbatim)

| # | User's words | How discharged | Status |
|---|---|---|---|
| C1 | "whats there in the needs input should also go in the waiting for you section in the ai-tracker" | `claude._blocked_jobs()` → `waiting`, `needs`, `⧖ now_line`. **(F7)** narrowed by the user's own C5/C6 answers to *live* daemon jobs whose transcript exists. Unit A adds the narrowing + `needs`/`resumable` on every provider at the registry seam | partly (base impl, uncommitted) |
| C2 | "make sure the waiting for you section should have the native resume button instead of open-terminal button in that view" | Unit C: awaiting Claude tiles → `session:answer` = native `POST /api/term/open {mode:"resume"}` | not yet |
| C3 | "Hero tile only, for others add a small icon button which resumes it. the hero tile gets the icon + label in the button and the others get only the icon" | Unit C: hero `.cr-tile-action` = `play` + "Resume"; non-hero awaiting → icon-only `.cr-tile-resume`; both `data-act="resume"` | not yet |
| C4 | in-browser resume fallback when not on localhost "and add a separate config to have a read-only tunnel option in the tracker, thats specially important when sharing the tunnel with friends and colleagues" | **(F5)** fallback only on `/api/term/open` 403 with `remote:true` and no `readonly` → `session:resume`. **(F1–F4)** `TUNNEL_READONLY` enforced at one point in `server.Handler`: deny all POST, allow-listed GET only; SPA hides buttons from `X-Read-Only` | not yet |
| C5 | Q "Filter them out?" → **"Only live daemon jobs (Recommended)"** | Unit A: short ∈ roster workers ∧ supervisor pid alive ∧ worker pid alive | not yet |
| C6 | Q transcript-less jobs → **"Only live ones (Recommended)"**; awaiting tile shows the question | no synthesized rows; `ext_cr_board.js:2807` `s.needs \|\| s.prompt` | **discharged** |

## 1. Verified facts
- Jobs `~/.claude/jobs/<short>/state.json`: dir == `daemonShort` for all 99; all `backend:"daemon"`; 56 blocked; newest blocked non-worker is 27.6 days stale.
- Roster `~/.claude/daemon/roster.json`: `{proto, supervisorPid, updatedAt, workers:{<short>:{pid, replPid, sessionId, dispatch, ptyAuth, rvAuth, ptySock, rendezvousSock, …}}}`. **(A1)** `ptyAuth/rvAuth/ptySock/rendezvousSock` are secrets — synthetic fixtures only, no test reads the real roster. Workers fluctuate (15/14/11); blocked∩workers = 2 (`7d44ec42`, `e7a94a24`); workers ⊄ blocked (working/done/no-state also present). `~/.claude/daemon.status.json` `workers:{}` — unusable. live∩blocked∩(rs≠sid) = 0 today.
- Caller identity: `term_launch._local_caller(h)` (`term_launch.py:58-67`) refuses on any `_PROXY_HEADERS` (`:39`) or non-`127.0.0.1` peer. `tunnel.via_tunnel` (`tunnel.py:66`) only picks the credential. `term_gate.allowed()` (`:37`) lets tunnel callers have a full shell today.
- POST routes (all mutating): server.py `/api/title, /api/config, /api/tunnel, /api/tunnel/ctl, /api/pin, /api/model-keep, /api/flags, /api/flags/resolve, /api/flags/delete, /api/notes, /api/notes/push, /api/notes/next, /api/notes/delete`; `EXTRA_POST` `/api/term/open|run|kill|pty|keys|resize|inject|close`; `/login` handled pre-auth (`server.py:465`).
- GET routes: `do_GET` (`server.py:287-462`) `/`, `/api/list, /api/flags, /api/config, /api/tunnel, /api/tunnel/reveal, /api/search, /api/diff, /api/file, /api/output, /api/shell, /api/agent, /api/session, /api/narration, /api/session_search`; `EXTRA_GET` `/api/term/{status,stream,attached,screen,scrollback,renderer,raw,cwds,list}` + `/vendor/{xterm.js,xterm.css,addon-fit.js,mermaid.min.js}` (`term_vt.py:4145-4192`). No favicon/static routes; login page served pre-gate. **Sensitive:** `/api/file?path=` (`server.py:371-384`, any path ≤500KB), `/api/tunnel/reveal`, `/api/term/*`.
- Config: `TUNNEL_EDITABLE`/`TUNNEL_VALIDATORS` (`config.py:556-582`), `POST /api/tunnel` (`server.py:529`), `tunnel_public()` (`:601`); `store._load_json` lenient (`store.py:5-10`); `config.py` os-only.
- SPA: `/api/list` policy headers (`server.py:307-324`) → `app.js loadSide()` (`:1260`) globals → boot ctx (`:429-447`). Board hero `tiles[0]` iff awaiting (`ext_cr_board.js:432`), button `:2862-2866`; `tileBaseAttrs` (`:2628-2637`) Enter-key bubbling bug. Boot `session:resume` (`:749`), `session:openExternal` (`:766-788`), `terminal:open` (`:481`).
- Imports: `term_launch` imports `server`; `server` loads `term_launch` from its bottom loader (`:828`).

## 2. Data / schema / config
- `config.DAEMON_ROSTER` (late-bound).
- `config.resolve_tunnel_readonly(overrides) -> bool` **(F2/F3)**: env `TRACKER_TUNNEL_READONLY` ∈ {1,true,yes,on} forces True (floor) OR config key: bool as-is, **non-bool → True**; absent everywhere → False. `config.tunnel_readonly_env() -> bool`.
- `TUNNEL_READONLY` in `TUNNEL_EDITABLE` + `TUNNEL_VALIDATORS` (`_v_bool`); **never** in `EDITABLE`/`RESTART_REQUIRED`. `tunnel_public()` + `readonly`, `readonly_env`.
- List dict at `registry.all_sessions()`: `resumable = not p.prefix`; `needs` default `""`.
- `/api/list`: `X-Read-Only: 1` for read-only callers (omit `X-Term-Count`).
- RO 403 body `{"error":"read-only: this tracker is shared view-only","readonly":true}`. **(F5)** `/api/term/open` remote refusal `{"error":…,"remote":true}`.
- Default off (owner's phone flag/note/pin workflow).

## 3. Units (A/B/C own disjoint files)
**Unit 0 — `config.py` only (first).** `DAEMON_ROSTER`, `resolve_tunnel_readonly`, `tunnel_readonly_env`, editable/validator/public additions; os-only.

**Unit A — live filter + shared defaults** (after 0; ∥ B, C). `providers/claude.py`, `registry.py`, `tests/test_jobs_waiting.py`, `tests/test_cr_registry_fields.py`.
1. **(F6)** `_pid_alive(pid)`: `type(pid) is int and pid>0`; `os.kill(pid,0)`: ProcessLookupError→False, PermissionError→True, (TypeError, ValueError, OverflowError)→False.
2. `_live_daemon_shorts()`: strict-load roster; `set()` on missing/unparseable/non-dict/`workers` non-dict/supervisor not alive; else shorts whose worker dict has a live `pid`. Residual: pid reuse.
3. `_blocked_jobs()` iterates only live shorts; skip missing state.json and `daemonShort` ≠ dir; keep sid + rs mapping; remove ponytail perf comment.
4. `registry.all_sessions()`: `r["resumable"] = not p.prefix; r.setdefault("needs","")`.
5. **(F9)** setUp redirects `config.DAEMON_ROSTER` to a synthetic roster (supervisor + worker pid = `os.getpid()`); existing asserts unchanged. RED proofs: `test_dead_job_not_waiting`, `test_missing_roster_nothing_waiting`, `test_dead_supervisor_roster_is_stale`, `test_dead_worker_pid_not_waiting`, `test_supervisor_pid_zero_or_negative_is_dead`, `test_resumable_and_needs_on_every_provider`. Guards: `test_malformed_roster_no_crash`, `test_non_int_pid_no_crash`, `test_live_worker_dir_without_state_json_ignored`, `test_resume_session_id_maps_when_live`, `test_daemonshort_mismatch_skipped`, existing 5.

**Unit B — read-only choke point** (after 0; ∥ A, C). `server.py`, `term_launch.py`, `cli.py`, `tests/test_tunnel_readonly.py`, `tests/test_term_launch.py`. (`tunnel.py` untouched.)
1. **(F4)** remote = `not term_launch._local_caller(h)[0]` via late import `def _is_local(h): from . import term_launch; …` (no cycle at request time).
2. **(F2)** `_load_config_strict()`: FileNotFoundError→`{}`; other OSError/ValueError/non-dict → raise. `store._load_json` unchanged.
3. `Handler._readonly()`: local → False (exception → treat as remote); else `resolve_tunnel_readonly(_load_config_strict())`, any exception → **True**.
4. POST: right after `_authok()` (`server.py:467-468`), **before body parse** → 403 RO body. Deny-all; 401 still first.
5. **(F1)** GET allow-list after `_authok()`: `{"/", "/api/list", "/api/session", "/api/narration", "/api/search", "/api/session_search", "/api/diff", "/api/output", "/api/shell", "/api/agent", "/api/flags", "/api/tunnel", "/api/config"}` + prefix `/vendor/`. Everything else (incl. `/api/file`, `/api/tunnel/reveal`, `/api/term/*`, future routes) → 403.
6. `/api/list`: `X-Read-Only: 1`, skip term count.
7. `POST /api/tunnel` echoes effective value + `locked: tunnel_readonly_env()`, `restart: False`.
8. **(F5)** `term_launch.py:188` → `{"error":err,"remote":True}`.
9. `cli.py` HELP env line.
10. Tests (reuse `tests.test_tunnel` `_ServerCase/_get/_post`; proxied = `Cf-Connecting-Ip`; corrupt/`[]` configs patch `config.AUTH="u:p"`). RED: every POST 403 + files unchanged; non-loopback peer w/o headers readonly; `/api/file` 403 + secret absent; reveal + term GET 403; unknown GET 403; list header + no term count; corrupt config → 403; `[]` → 200 + header; string `"true"` → 403; env floor beats config false; cannot disable via tunnel; `tunnel_public` readonly + env lock. Guards: default off allowed; localhost POST ok; localhost `/api/file` 200; `/vendor/xterm.js` 200 via tunnel; login ok; unauth 401; header absent locally; validator 400; `/api/config {TUNNEL_READONLY}` → 400. `test_term_launch.py`: `test_proxied_refusal_body_has_remote_true` (`TestProxiedRequestRefused`, `:349`).

**Unit C — board buttons, boot, SPA flag** (after 0; ∥ A, B). `web/app.js`, `ext_cr_boot.js`, `ext_cr_board.js`, `ext_cr_board.css`, `tests/test_cr_board_resume_button.py`.
1. `app.js`: `let trackerReadOnly=false;` (`:1003`); `loadSide()` sets from `X-Read-Only`, toggles `html.tracker-readonly`.
2. Boot: `ctx.readOnly()`; extract `postTermOpen(id,mode)` (openExternal unchanged); `answerSession(id)`: RO → notify; non-Claude (regex `:767`) → `CR.term.open(id,{mode:'cwd'})`; Claude → `postTermOpen(id,'resume')`: ok → notify; **`403 && j.remote && !j.readonly` → `emit('session:resume')`**; else notify `j.error`. `on('session:answer')`; `window.CR.answerSession`. No `location.hostname`.
3. Board (`:2815-2875`): `canResume = awaiting && s.resumable && !readOnly`. Hero: `[icon('play'),'Resume']`, title/aria "Resume this session to answer", stopPropagation + emit. Non-resumable non-RO hero keeps old button; RO → none. Non-hero: icon-only `.cr-tile-resume` in head. Fix `tileBaseAttrs` onkeydown guard.
4. CSS: `.cr-tile-action` inline-flex; `.tracker-next .cr-tile-resume` 24px round (32px ≤600px), focus ring; check `:1958`.
5. Node-harness tests (reuse `tests/test_working_glow_board.py`). RED: hero icon+label emits answer; non-hero icon-only; stopPropagation; RO hides all; answer local ok; 403 remote → fallback; 403 terminal-disabled → no fallback + one notify; 403 readonly → no fallback; Auggie cwd; RO does nothing. Guards: non-awaiting none; Auggie hero keeps open-terminal; Auggie non-hero none; no hostname.

**Unit D — RO UX** (after B, C). `ext_cr_dialogs.js`, `app.css`, `ext_cr.css`. Toggle row "Read-only for remote visitors" (`~:1354`), disabled + "Locked on by TRACKER_TUNNEL_READONLY" when `readonly_env`; `html.tracker-readonly` hides write controls + "View only" chip. Tests: toggle row, env lock, CSS only under class.

**Unit E — attach to real short** (after A, B). **(F8) Required once live∩blocked∩(rs≠sid) > 0; 0 today.** `claude.job_short_for(sid)`; `build_script(..., attach_short=None)`; term_vt attach sites; `tests/test_resume_attach.py`.

**Unit F — evals + verification** (last). **(F10)** `tests/test_selfcheck.py` `_run()` assertion (~`:840`): rows have bool `resumable` + str `needs` (Claude True / Auggie False); RO + proxied POST → 403. `node --check` touched JS; `make check` + `--selfcheck`; restart on spare port; curl C1/C5 (needs ⊆ live∩blocked), F8 probe, C2/C3 (`session:answer` in page, hostname count unchanged), C4 (enable → tunnel POST/`/api/file` 403, `/vendor/mermaid.min.js` 200, `X-Read-Only`; local POST ok; reset); browser desktop/900/600px.

## 4. Sequencing
`0` → (`A` ∥ `B` ∥ `C`) → `D` → `E` (conditional) → `F`.

## 5. Risks
- Hero ~107px content → label "Resume"; fallback nowrap 11px.
- Roster format Claude-owned → fails safe to "nothing waiting"; pid-reuse residual.
- Header-less forwarders (`ssh -R`, VS Code port-forward) look local — RO cannot protect them; document in HELP + `docs/remote-access.md`.
- Fork-copy failure if attach short is wrong (Unit E); terminal briefly shows `--resume` refusal before `attach` — expected.
- Enter-key bubbling fixed by guard. Header lag ≤1 poll — server still 403s. SPA term probes 403 under RO — degrade like terminal-disabled.
- RO ≠ host gating: opt-in, server-decided, localhost intact.

## 6. Decisions the user may overrule
1. Global toggle (owner's phone also RO while on) vs separate guest credential.
2. Scope: any non-local caller (incl. Tailscale/LAN) vs proxied-only.
3. RO blocks terminal *viewing* too.

## 7. Rev 3 amendments (opus re-review: SIGN-OFF-WITH-AMENDMENTS) — these OVERRIDE §3 where they differ
1. **(R1, blocking) Unit B.1:** no late import. Move `_PROXY_HEADERS`, `_proxy_header`, `_local_caller(handler)` from `term_launch.py:39-67` into `server.py` (module level; names checked collision-free in the flattened bundle); `term_launch.py` aliases `_PROXY_HEADERS = server._PROXY_HEADERS`, `_local_caller = server._local_caller` (tests at `test_term_launch.py:355/388` iterate the name). `Handler._readonly()` calls `_local_caller(self)` directly. Reason: `scripts/bundle.py:38-43` strips only top-level imports and `term_launch` is not bundled → the indented relative import would raise in `dist/tracker.py` and fail closed for localhost too.
2. **B.10 + F:** bundle test in `tests/test_integration.py` bundle class: `make bundle`, run `dist/tracker.py` with `TRACKER_TUNNEL_READONLY=1 PORT=<free>`, local `POST /api/pin` → 200, `/api/list` has no `X-Read-Only` (RED with late import). Non-loopback-peer case uses a stub handler (`_FakeHandler(client_ip="192.168.1.5")`), not `_ServerCase`.
3. **(R4) B.5:** replace the `/vendor/` prefix with the four exact paths (`/vendor/xterm.js`, `/vendor/xterm.css`, `/vendor/addon-fit.js`, `/vendor/mermaid.min.js`).
4. **(R3) C.2–3:** tiles emit `{id, resumable: s.resumable}`; `answerSession` branches on `payload.resumable`, not the id regex (openExternal's regex untouched). Test: `{id:'auggie:x', resumable:false}` → `CR.term.open(…,{mode:'cwd'})`.
5. **(R2) D:** `confirm(…)` before enabling RO from the dialog ("Visitors from outside this Mac — including this device if it is remote — will be view-only. Turn it off from the Mac itself."); page-grep test.
6. **(R5b) F10:** the selfcheck RO assertion is predicate-level (`config.resolve_tunnel_readonly` + `server._local_caller(stub)`), since `_run()` has no server.
7. **(R6)** Unit B owns the `docs/remote-access.md` update. §6.2 add: with `HOST=0.0.0.0`, the owner browsing their own LAN IP from the Mac is non-loopback → RO applies. §5 add: under RO the one-shot `/api/term/list` probe 403s → `termEnabled` 'unknown' (acceptable).
8. Residual, no change: Auggie `drill`/`exists` joins `sid[len(prefix):]` (`auggie.py:920-927`) — `auggie:../..` can reach other `*.json`, only Auggie-parsed fields return; document in PR.

## Log
- Gate baseline: `test_selfcheck` (0 tests per-module) and `test_term_vt` (OOM `Killed: 9`) identical on base `594ac65` — pre-existing.
- Rev 1 review (opus): REFUTED as written; F1–F3 blocking → rev 2.
- Rev 2 re-review (opus): SIGN-OFF-WITH-AMENDMENTS; R1 blocking → rev 3 (§7). Plan signed off pending user approval of §6.
