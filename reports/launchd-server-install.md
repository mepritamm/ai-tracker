# launchd server install: Schedule rename + Install / Uninstall / Reinstall a dashboard LaunchAgent

Status: **PLAN, not yet reviewed or implemented.** Worktree `.claude/worktrees/launchd-server-install`,
branch `worktree-launchd-server-install`, base `personal/main` @ `f5cf56c`.

## Contract (verbatim)

1. "would need an install button which would create a launchd session, and rename the executing install button which only schedules every day now at 10:00 to 'schedule' instead of install"
2. "Need an install and uninstall and reinstall button"

| # | Clause | Verdict |
|---|---|---|
| 1a | New Install button creates a launchd session (job) that runs the dashboard | not discharged (plan: §B, §D) |
| 1b | The existing scheduler "Install" button is renamed to "Schedule" | not discharged (plan: §A) |
| 2 | Install, Uninstall and Reinstall buttons for the new job | not discharged (plan: §D) |

User goal stated in the brief (not verbatim contract, but it shapes the design): the installed job serves the
dashboard on the **same port** as the shell server, with no shell, and **takes over when the shell-started
server stops**.

## What exists today (read from the repo at f5cf56c)

- `aitracker/schedule.py` (225 lines): `LABEL = "com.aitracker.pending"` (l.13), `_root()` (l.18),
  `_argv()` (l.22, `[sys.executable, "-m", "aitracker", "--pending", "--if-due"]`), `plist_path()` (l.26),
  `sched_log_path()` (l.30), `launchd_plist()` (l.34-46: PATH + PYTHONPATH env, StartCalendarInterval 10:00,
  RunAtLoad False, no KeepAlive), `_is_linked_worktree()` (l.65), `_is_temp()` (l.93), `_target()` (l.99),
  `_read_plist()` (l.103), `_sched_run()` (l.111, 15 s timeout, returns None on hang), `sched_install()`
  (l.119-157: write plist, `bootout` then `bootstrap gui/<uid>`; removes the plist on bootstrap failure),
  `sched_uninstall()` (l.160-170, writes opt-out `~/.ai-tracker-sched-optout`), `sched_status()` (l.173-197,
  parses `launchctl print` for `last exit code`), `autoinstall_once()` (l.200-225; skips non-darwin/win32,
  test runs, the bundle via `os.path.isfile(os.path.join(config._HERE, "__init__.py"))`, linked worktrees and
  `/.claude/worktrees/` paths, temp dirs, opt-out).
- `aitracker/server.py`: imports `sched_install, sched_uninstall, sched_status, autoinstall_once, _optout_path`
  (l.12); `_local_caller()` (l.223-240); `_STARTED` (l.243); `_sched_body()` (l.262-269); `_RO_GET_ALLOW`
  (l.297, `/api/scheduler` deliberately absent); GET `/api/update`/`/api/scheduler` local-only branch
  (l.476-481); `do_POST` read-only deny-all (l.632); POST local-only branch for
  `/api/update/fetch|apply` and `/api/scheduler` (l.659-680, `start_restart` in `finally` after the 202 is
  flushed); `bind()` (l.956-965, walks to the next free port on `EADDRINUSE`, 20 tries); `publish_endpoint()`
  (l.973); `_on_sigterm()` (l.1002-1016, SIGTERM -> `tunnel.stop(keep_on=True)` -> `SystemExit(0)`);
  `run()` (l.1019-1048: `config.BIND_HOST = host`, `signal.signal(SIGTERM)` **before** `bind()`, then
  `publish_endpoint`, `start_worker`, scheduler autoinstall thread, `tunnel.autostart`, browser open).
- `aitracker/cli.py` l.44-46: `PORT` env default 8790, `HOST` env default `127.0.0.1`,
  `open_browser=not os.environ.get("TRACKER_NO_BROWSER")`. `--pending` is routed to `pending.cli_main`, which
  owns `--install-scheduler/--uninstall-scheduler/--scheduler-status` (pending.py l.1188-1193).
- `aitracker/update.py` `restart_in_place()` (l.343-369) re-execs `sys.orig_argv` in the same PID and sets
  `os.environ["PORT"]` to the actual port; `start_restart()` (l.372) defers it on a 0.5 s Timer.
- `aitracker/web/ext_cr_dialogs.js`: `crCall` (l.1144), `crBtn` (l.1156), `schedulerText` (l.1162),
  `schedulerBlock()` (l.1173-1216; buttons at l.1182 `Reinstall`, l.1183 `Uninstall`, l.1185 `Install`;
  `act()` POSTs `{action}` to `/api/scheduler`, l.1202-1209); mounted on the **Board** tab (l.1525).
  `updateBlock()` (l.1218-1305) has the restart-poll pattern (`waitForRestart`, compares `started_at`),
  mounted on the **Server** tab (l.1593).
- Tests that assert the current scheduler labels (they go red on the rename, which is the point):
  `tests/test_update_settings_ui.py` l.138-157, `tests/test_pending_web_gaps.py` l.138-150,
  `tests/test_pending_web_contract.py` l.267. Scheduler unit tests: `tests/test_pending_schedule.py`
  (`Rec` stub for `subprocess.run`, HOME + `_root` patched, tearDown asserts the real LaunchAgents dir is
  untouched). Route guard test: `tests/test_local_host_routes.py` (`ROUTES` tuple l.14-16). Port fallback test:
  `tests/test_integration.py` `TestPortFallback` l.1136-1150.
- `scripts/bundle.py` ORDER (l.11-15) already contains `schedule.py`, `server.py`, `cli.py` — adding functions
  to those files needs **no** bundle change; a new module would.
- launchd semantics (local `man launchd.plist`): `KeepAlive.SuccessfulExit=false` restarts the job only when it
  exits non-zero (and implies RunAtLoad); `ThrottleInterval` default 10 s ("jobs will not be spawned more than
  once every 10 seconds"); on job death launchd kills the remaining processes **with the job's process group
  ID** unless `AbandonProcessGroup` is true.

## Design decisions (with the reasoning)

- **Module: functions in `schedule.py`, not a new module.** It already owns every helper needed
  (`_root`, `_sched_run`, `_is_linked_worktree`, `_is_temp`, `_read_plist`, LaunchAgents paths) and is
  already in the bundle ORDER. A new module would duplicate imports and need a `scripts/bundle.py` edit.
  Update the module docstring to say it now also holds the dashboard LaunchAgent.
- **Strict-port mode is an internal CLI flag `--service`, not an env var.** Env vars set in the plist are
  inherited by every terminal the dashboard spawns; a `make serve` typed into a dashboard terminal would then
  inherit `TRACKER_STRICT_PORT=1` and hang waiting instead of moving to 8791. argv is not inherited by
  children, and `update.restart_in_place()` re-execs `sys.orig_argv`, so `--service` survives an in-app
  "Update and restart" in the same PID. `--service` implies: strict port, no browser, `config.SERVICE = True`,
  no tunnel autostart (below).
- **Strict port waits in-process instead of exiting non-zero.** On `EADDRINUSE` the `--service` process prints
  one line and re-tries `bind` every 5 s, forever. Why not "exit 75 and let launchd respawn every
  ThrottleInterval": that writes a log line and a launchd "exited with abnormal code" system-log entry every
  10-30 s for as long as the shell server runs (thousands a day), and every respawn re-imports the package.
  The wait happens inside `bind()`, which `run()` calls **before** `publish_endpoint`, `start_worker`, the
  scheduler autoinstall thread and the tunnel. A waiting copy does nothing (no port file, no pending worker, no
  double scan) until it owns the port. Takeover latency is 5 s at most. SIGTERM while waiting already exits
  cleanly (`signal.signal` is installed before `bind()`).
- **KeepAlive = `{"SuccessfulExit": False}`, `ThrottleInterval` = 30.** A crash (non-zero exit or signal death)
  restarts it, at most once every 30 s. A clean stop (SIGTERM -> `_on_sigterm` -> exit 0, which is what
  `make stop` sends) stays stopped until the next login or Reinstall. Plain `KeepAlive: true` would respawn
  10 s after `make stop`, so `make stop && make serve` would race the respawn and the shell server would
  drift to 8791. That is the opposite of what the user asked for. **(User decision 2.)**
- **Port and host baked at install = what the running server ASKED for, not what it got.** `run()` records
  the requested port as `config.BIND_PORT = port`, next to the existing `config.BIND_HOST = host` (l.1020).
  The route bakes `config.BIND_PORT`/`config.BIND_HOST`; the CLI path bakes
  `int(os.environ.get("PORT", 8790))` and `os.environ.get("HOST", "127.0.0.1")`, the same expressions as
  `cli.main`. Reason: a shell server that drifted to 8791 because the service already held 8790 must not bake
  8791 on Reinstall. Not `config.resolve_port()`: that honours a config.json `PORT` override that `cli.main`
  ignores at startup, so it would bake a port the shell server never uses.
- **Loopback only; TRACKER_AUTH intentionally not carried.** Writing `TRACKER_AUTH` into a plist would put a
  plaintext secret in `~/Library/LaunchAgents` (0644). So the service runs with no `TRACKER_AUTH`, which is
  exactly a default `make serve` (loopback, `_local_caller` DNS-rebinding guard active, no login). Install is
  **refused** when the baked host is not loopback (`0.0.0.0`/LAN), since that would serve transcripts to the
  LAN without a login. The plist env is an explicit allow-list
  (`PATH, PYTHONPATH, PORT, HOST, PYTHONUNBUFFERED`), never `dict(os.environ)`. The caller's launchd env
  contains a GITHUB_PAT; a test asserts the exact key set.
- **No tunnel autostart in `--service` mode.** `run()` calls `tunnel.autostart()` when config.json has
  `TUNNEL_ON` from an earlier run (l.1034). Under launchd that would republish the dashboard on a public URL
  at every login, and nobody reads the stdout warning. In service mode the server skips it and logs one line.
  The Config dialog's Tunnel switch still works at runtime.
- **API: a new `/api/service` route (GET + POST), not more actions on `/api/scheduler`.** The two jobs have
  different bodies and different status shapes. Mixing them would mean every `schedulerBlock` paint has to
  ignore service fields. The new path joins the **same** `in (...)` tuples as `/api/scheduler`
  (GET l.476, POST l.659), so `_local_caller` + the read-only deny-all + "not in `_RO_GET_ALLOW`" are
  literally the same code. The scheduler's API action names stay `install`/`uninstall`; only the labels change.
- **Buttons per state (same as the scheduler block):** not installed -> `Install`; installed ->
  `Reinstall` + `Uninstall`. If the server says install is refused (e.g. linked worktree), the reason is shown
  and no buttons. The contract's three buttons all exist; you never see a button that cannot work.
- **Reinstall = `svc_install`.** Install already does rewrite plist -> `bootout` -> `bootstrap`, so a separate
  function would be a copy. The API keeps a distinct `reinstall` action name so the UI and logs say what the
  user pressed.
- **No auto-install** of the server job, ever. No change to `autoinstall_once` (it stays scheduler-only).
- Uninstalling the service does **not** touch the scheduler opt-out file (`_set_optout` is scheduler-only).

### §A Rename the scheduler block's buttons

`aitracker/web/ext_cr_dialogs.js` `schedulerBlock()`:
- l.1182 `crBtn('Reinstall', …act('install'))` -> `crBtn('Reschedule', …act('install'))`
- l.1183 `crBtn('Uninstall', …act('uninstall'), 'cr-btn-danger')` -> `crBtn('Unschedule', …)`
- l.1185 `crBtn('Install', …act('install'))` -> `crBtn('Schedule', …act('install'))`

Status texts (`schedulerText`, "Installed (launchd)…", "Turned off (you uninstalled it)") stay unchanged.
The contract renames the button only, and the status says what the OS job is. API actions stay
`install`/`uninstall`; `server.py` and `schedule.py` do not change for §A. **(User decision 1: the wording
"Reschedule"/"Unschedule" for the other two buttons. "Schedule" is fixed by the contract.)**

### §B `com.aitracker.server` LaunchAgent (schedule.py additions)

```python
SVC_LABEL = "com.aitracker.server"
SVC_WAIT = 5.0          # strict-port retry period, seconds (used by server.bind)

def svc_plist_path():   # ~/Library/LaunchAgents/com.aitracker.server.plist
def svc_log_path():     # ~/Library/Logs/ai-tracker-server.log
def _svc_target():      # "gui/%d/%s" % (os.getuid(), SVC_LABEL)

def service_plist(port, host):
    return plistlib.dumps({
        "Label": SVC_LABEL,
        "ProgramArguments": [sys.executable, "-m", "aitracker", "--service"],
        "WorkingDirectory": _root(),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": _root(),
                                 "PORT": str(int(port)), "HOST": host, "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Interactive",     # it serves a UI; Background would throttle CPU/IO
        "StandardOutPath": svc_log_path(),
        "StandardErrorPath": svc_log_path(),
    })
```
`sys.executable` is the real interpreter, not the pyenv shim (checked on this machine: the shim is
`~/.pyenv/shims/python3` but `sys.executable` is `~/.pyenv/versions/3.12.3/bin/python3`), so it is stable
across `pyenv shell` switches. It breaks only when that version or venv is deleted (see E3).

### §C Strict-port bind (server.py)

```python
def bind(host="127.0.0.1", port=8790, tries=20, strict=False, wait=5.0):
    if strict:          # --service: never move to another port; wait for this one
        said = False
        while True:
            try:
                return Server((host, port), Handler)
            except OSError as e:
                if e.errno != errno.EADDRINUSE:
                    raise                   # real bind error -> non-zero exit -> launchd restarts (throttled)
                if not said:
                    print("ai-tracker: port %d is busy; service mode waits for it (checks every %gs)"
                          % (port, wait), flush=True)
                    said = True
                time.sleep(wait)
    ...existing loop unchanged...
```
`run(host, port, open_browser=True, service=False)`: `config.BIND_PORT = port`, `config.SERVICE = service`,
`srv = bind(host, port, strict=service, wait=SVC_WAIT)`, `if not service: tunnel.autostart(actual, host)`
(else print "tunnel autostart skipped in service mode"). Add `BIND_PORT = 8790` and `SERVICE = False` to
`config.py` next to `BIND_HOST` (l.139) so late-bound `config.NAME` reads work as the conventions require.
`make serve` passes no `--service`, so the default path is byte-identical. Existing `TestPortFallback` keeps
proving that.

`cli.py main()`: before the serve lines, add
```python
if "--install-service" in sys.argv or "--reinstall-service" in sys.argv:
    sys.exit(svc_install(int(os.environ.get("PORT", 8790)), os.environ.get("HOST", "127.0.0.1")))
if "--uninstall-service" in sys.argv: sys.exit(svc_uninstall())
if "--service-status" in sys.argv: print(json.dumps(svc_status())); return
service = "--service" in sys.argv
run(host=host, port=port, open_browser=not service and not os.environ.get("TRACKER_NO_BROWSER"), service=service)
```
and one HELP line for the three public flags. `--service` is internal, so leave it out of HELP or mark it
"(used by the LaunchAgent)".

### §D Install / Uninstall / Reinstall + status

`schedule.py`:
```python
def _svc_refusal(host):
    """"" when this checkout may install the dashboard service, else the reason (shown in the UI)."""
    # order: platform, bundle, linked worktree / .claude/worktrees path, temp dir, non-loopback host
    if sys.platform != "darwin": return "the background service is macOS-only (launchd)"
    if not os.path.isfile(os.path.join(config._HERE, "__init__.py")): return "not a package checkout (bundle)"
    root = _root()
    if _is_linked_worktree() or (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in root + os.sep:
        return "%s is a linked git worktree; install from the primary checkout" % root
    if _is_temp(root): return "%s is a temp directory" % root
    if host not in ("127.0.0.1", "localhost", "::1"):
        return "HOST %s is not loopback; the service runs without TRACKER_AUTH, so it is loopback-only" % host
    return ""

def svc_install(port, host, run=subprocess.run):
    """Write the plist, bootout any loaded copy, bootstrap. 0 ok, 1 launchctl failed, 2 refused,
    3 deferred (this process IS the service: plist written; caller must svc_spawn_deferred after replying)."""
    why = _svc_refusal(host)
    if why: print("ai-tracker: " + why); return 2
    # makedirs LaunchAgents + Logs, write plist 0644 (same as sched_install l.141-146)
    if config.SERVICE: return 3
    _sched_run(run, ["launchctl", "bootout", _svc_target()])
    r = _sched_run(run, ["launchctl", "bootstrap", "gui/%d" % os.getuid(), svc_plist_path()])
    if r is not None and r.returncode != 0:            # bootout can return before the job is fully gone
        time.sleep(1); r = _sched_run(run, [...same bootstrap...])
    if r is None or r.returncode != 0: remove plist; print rc; return 1
    return 0

def svc_uninstall(run=subprocess.run):
    """0 done, 3 deferred (self). Removes the plist first in both cases."""
    remove svc_plist_path() (ignore OSError)
    if config.SERVICE: return 3
    _sched_run(run, ["launchctl", "bootout", _svc_target()]); return 0

def svc_spawn_deferred(reinstall, popen=subprocess.Popen):
    """Run bootout (+ bootstrap) from a detached helper that outlives this process (E1)."""
    popen(["/bin/sh", "-c",
           'sleep 1; launchctl bootout "$1"; [ -z "$3" ] || launchctl bootstrap "$2" "$3" '
           '|| { sleep 2; launchctl bootstrap "$2" "$3"; }',
           "sh", _svc_target(), "gui/%d" % os.getuid(), svc_plist_path() if reinstall else ""],
          stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, close_fds=True, start_new_session=True)

def svc_status(run=subprocess.run):
    """{supported, installed (plist exists), loaded, pid, state, last_exit, port, host,
        python, python_exists, root, root_exists, can_install, reason}"""
    # loaded/pid/state/last_exit: regex over `launchctl print <target>` ("pid = N", "state = X",
    # "last exit code = N"), same approach as sched_status l.185-192; never raises; timeout -> error.
    # port/host/python/root read back from the plist (_read_plist pattern, on svc_plist_path()).
```
All argv elements are code-derived (label, uid, path); nothing from the request reaches a shell.

`server.py`:
- import `svc_install, svc_uninstall, svc_status, svc_spawn_deferred` from `.schedule` (l.12).
- `_svc_body(this_port, rc=None)`: `st = svc_status()`; add `st["self"] = config.SERVICE`,
  `st["this_port"] = this_port`, `st["started_at"] = _STARTED`, and
  `st["waiting"] = bool(st["loaded"] and st["pid"] and not config.SERVICE and st["port"] == this_port)`
  (the service is alive, and this shell server holds its port). Errors: rc 2 -> `st["error"] = st["reason"]`;
  rc 1 -> `"launchctl bootstrap failed; see ~/Library/Logs/ai-tracker-server.log"`. The server owns these
  strings and the client only renders them (convention 5).
- GET: extend l.476 to `("/api/update", "/api/scheduler", "/api/service")` and dispatch to
  `_svc_body(self.server.server_address[1])`.
- POST: extend l.659 the same way. Branch:
  ```python
  if p.path == "/api/service":
      act = body.get("action")
      if act not in ("install", "reinstall", "uninstall"):
          return self._json({"error": "action must be install, reinstall or uninstall"}, 400)
      rc = (svc_uninstall() if act == "uninstall"
            else svc_install(config.BIND_PORT, config.BIND_HOST))
      if rc != 3:
          return self._json(_svc_body(self.server.server_address[1], rc))
      try:
          self._json({"deferred": act, "self": True}, 202)
      finally:                      # response is flushed before launchd SIGTERMs us
          svc_spawn_deferred(act != "uninstall")
      return
  ```

`ext_cr_dialogs.js` — a new `serviceBlock()` beside `updateBlock()`, mounted on the **Server** tab after
`updEl` (l.1593), class `cr-svc-block`, name **"Background service"**:
- `crReadOnly()` -> null (same as the others; the server 403 is the real gate).
- `st.supported === false` -> "The background service is macOS-only." with no buttons.
- `!st.can_install && !st.installed` -> show `st.reason`, no buttons.
- not installed -> "Not installed. Install runs this dashboard from launchd at login on port <this_port>,
  with no shell; it takes over when you stop make serve." + `Install`.
- installed -> one status line built from server fields: `self` -> "Running as the service (pid N) on :P";
  `waiting` -> "Installed, waiting for :P (this shell server holds it; stop it and the service takes over)";
  `loaded && pid` otherwise -> "Running (pid N) on :P"; `!loaded || !pid` -> "Installed, not running"
  + `last exit`; `python_exists === false` -> "Python at <python> is gone. Reinstall."; `root_exists === false`
  -> "Points at a missing checkout". Buttons `Reinstall` + `Uninstall` (`cr-btn-danger`).
- `act(action)` POSTs `{action}` to `/api/service`. On `202` + `deferred`: for `uninstall` show
  "Uninstalled. This dashboard was the service and is stopping. Start one with make serve."; for
  install/reinstall show "Restarting the service…" and poll `/api/service` every 1 s. When `started_at`
  changes, `window.location.reload()`. After 60 s show "The service did not come back. Run
  make service-install in a terminal." This copies the `waitForRestart` shape (l.1292-1302); it is not
  shared code, because `updateBlock`'s closure state differs and the copy is about 10 lines.

`Makefile`: add to `.PHONY` and `help`:
```make
service-install:   ; @python3 -m aitracker --install-service
service-reinstall: ; @python3 -m aitracker --reinstall-service
service-uninstall: ; @python3 -m aitracker --uninstall-service
service-status:    ; @python3 -m aitracker --service-status
```
(Written as normal two-line recipes like the `pending-install` targets.) Leave `make stop` unchanged. It
kills whatever listens on PORT, which also stops a serving launchd copy, and that copy stays stopped (decision 2).

`README.md`: rename the buttons in the "Opt-out" bullet (l.279): "Schedule (or Reschedule) and Unschedule".
Add a "Background service (macOS)" subsection after "Quick start" covering: what Install does; same port, and
waits for the shell server to stop; `make stop` stops it until next login or Reinstall; loopback-only with no
TRACKER_AUTH; not from worktrees/bundle; no tunnel autostart; log path; terminals opened from the service get
launchd's env plus your login-shell rc files, not your interactive shell's exports; the `make service-*`
aliases.

## §E Hard spots, each with a fallback

1. **Uninstall/Reinstall pressed in the dashboard that IS the launchd job.** `launchctl bootout` SIGTERMs the
   caller mid-request. Design: `config.SERVICE` (set only by `--service`) makes `svc_install`/`svc_uninstall`
   do only the file work and return 3. The route writes the 202 **first**, then in `finally` spawns a
   `start_new_session=True` `/bin/sh` helper that sleeps 1 s and runs `bootout` (+ `bootstrap` for reinstall,
   with one 2 s retry). The new session gives the helper its own process group, so launchd's "kill the
   remaining processes with the job's process group ID" does not reach it. The bootout SIGTERM goes through
   `_on_sigterm` -> exit 0. **Fallback A** (if the live proof shows the helper dies with the job, e.g. if
   launchd reaps by job rather than by pgid): set `"AbandonProcessGroup": True` in the plist. Safe because pty
   children already run in their own sessions. **Fallback B:** run the helper as its own transient launchd job
   (`launchctl submit -l com.aitracker.server.reinstall -- /bin/sh -c …`, deprecated but present), which is
   owned by launchd, not by us. **Degraded-but-safe end state either way:** the plist is already
   written/removed, so the next login converges, and the UI's 60 s message names `make service-install`.
2. **TRACKER_AUTH and shell env missing under launchd.** Intentionally omitted (see decisions). Effect: the
   service behaves like a default loopback `make serve`. The terminal gate is unchanged (loopback needs no
   auth), and `publish_endpoint` deletes a stale `token` file. config.json overrides (LIVE_WINDOW, TERM_*,
   PENDING_*) still apply because `run()` calls `config.apply_overrides` (l.1026). Env-only knobs
   (`TRACKER_TERM_TAB_HOSTS`, `TRACKER_MAX_TERMS` env, `VSCODE_WS_ROOT`…) fall back to defaults. README says
   so. Non-loopback HOST is refused at install, not silently downgraded.
3. **`sys.executable` disappears** (pyenv version or venv deleted). launchd then fails to exec and retries no
   more than every 30 s (ThrottleInterval). `svc_status` reports `python` + `python_exists`; the UI says
   "Python at … is gone. Reinstall", and Reinstall from any live dashboard or `make service-reinstall` re-bakes
   the current interpreter. A status test covers this.
4. **Installing while the shell server holds the port.** The job starts (RunAtLoad), prints one "port busy,
   waiting" line, and polls every 5 s in-process. No launchd respawns and no repeated log lines. `_svc_body`
   reports `waiting`. Ctrl-C or `make stop` on the shell server -> takeover within 5 s. **Edge:** if the shell
   server runs with `HOST=0.0.0.0`, BSD `SO_REUSEADDR` can let `127.0.0.1:P` bind next to the wildcard
   listener, so both serve and loopback goes to the service. That cannot happen to a service install (it is
   loopback-only), but a `0.0.0.0` shell server alongside it is unsupported. README names it.
   **Fallback** if the in-process wait misbehaves: switch the strict branch to `raise SystemExit(75)`. launchd
   then retries every ThrottleInterval (30 s), at the cost of the log noise described above.
5. **Bundled `dist/tracker.py`.** `-m aitracker` does not exist there. `_svc_refusal` refuses with
   "not a package checkout (bundle)", the same test `autoinstall_once` uses (l.209), so the UI shows the
   reason and no Install button. **Known gap, no change:** `sched_install` from a bundle would write the same
   broken `-m aitracker` argv today. Pre-existing; document it in the commit/PR body.
6. **Non-macOS.** `svc_status` returns `supported: False` (no launchctl call); the block renders
   "macOS-only" with no buttons; `svc_install` returns 2. On Windows this needs no `pty` guard because
   schedule.py imports nothing platform-specific.
7. (found while planning) **Env inheritance into dashboard terminals.** The plist env is inherited by every
   terminal the service spawns. Hence `--service` is an argv flag, and the env carries only PATH/PYTHONPATH/
   PORT/HOST/PYTHONUNBUFFERED, all harmless or equal to the defaults in a child shell.
8. (found while planning) **In-app "Update and restart" under the service.** `restart_in_place` re-execs
   `sys.orig_argv`, so `--service` is kept, the PID is unchanged (launchd sees no exit), and the rebind on the
   same port succeeds (the old socket is non-inheritable and closes at exec). No change needed. The live proof
   checks it.

## §F Tests (stdlib unittest; each provable red by reverting its fix)

New `tests/test_service.py` (same scaffolding as `test_pending_schedule.py`: HOME -> tempdir, `_root` ->
tempdir, the `Rec` stub, and tearDown asserting the real LaunchAgents listing did not change; patch
`schedule._is_temp` -> False and `schedule._is_linked_worktree` -> False for success paths, since the test
root is itself a temp dir):
1. `test_service_plist_contents`: `plistlib.loads(service_plist(8790, "127.0.0.1"))`: Label, ProgramArguments
   `[1:] == ["-m","aitracker","--service"]`, RunAtLoad True, KeepAlive `{"SuccessfulExit": False}`,
   ThrottleInterval 30, WorkingDirectory root, log under `$HOME/Library/Logs`, and
   `set(EnvironmentVariables) == {"PATH","PYTHONPATH","PORT","HOST","PYTHONUNBUFFERED"}` with
   `os.environ` patched to contain `TRACKER_AUTH` and `GITHUB_PAT` (both absent). Red: copy `os.environ` or
   drop KeepAlive.
2. `test_install_refusals`: `sys.platform` "linux" / bundle (`config._HERE` -> dir without `__init__.py`) /
   linked worktree / `.claude/worktrees` root / temp / host `0.0.0.0` -> rc 2, `Rec.calls == []`, no plist
   written. Red: remove any guard.
3. `test_install_sequence`: rc 0; calls == `[["launchctl","bootout",target], ["launchctl","bootstrap",
   "gui/<uid>", path]]`; plist 0644. With bootstrap rc 5 on both tries -> rc 1, plist removed, 3 calls.
4. `test_uninstall_removes_plist_and_boots_out`: rc 0, plist gone, bootout called, scheduler opt-out file
   **not** created.
5. `test_status_parses_launchctl`: `Rec(stdout="state = running\n\tpid = 4242\n\tlast exit code = 0\n")` +
   plist present -> `loaded, pid 4242, state "running", port 8790, python_exists`; plist pointing at a missing
   python -> `python_exists False`; non-darwin -> `supported False` and no calls.
6. `test_self_defers`: `config.SERVICE` patched True -> `svc_install` returns 3 and writes the plist with
   **no** launchctl call; `svc_uninstall` returns 3, removes the plist, no call; `svc_spawn_deferred(True,
   popen=stub)` gets `start_new_session=True` and argv ending `[target, "gui/<uid>", path]`;
   `svc_spawn_deferred(False, …)` ends with `""`. Red: drop the `config.SERVICE` early-return.
7. `test_bind_strict_waits_for_same_port`: occupy an ephemeral port; a `threading.Timer(0.3)` closes it;
   `bind("127.0.0.1", p, strict=True, wait=0.05)` runs in a thread joined with a 5 s timeout and must return a
   server on exactly `p`. Red: revert the strict branch (it returns a later port).
8. `test_bind_strict_reraises_other_errors`: `Server` patched to raise `OSError(errno.EADDRNOTAVAIL)` ->
   raises (no wait loop).
9. `test_cli_service_flag` (light): patch `aitracker.cli.run` and assert `--service` -> `service=True`,
   `open_browser=False`; plain argv -> `service=False`. Red: drop the flag wiring.

Route tests: in `tests/test_service.py` (a `_ServerCase` subclass from `tests.test_cr_routes`, with
`svc_install`/`svc_uninstall`/`_svc_body`/`svc_spawn_deferred` patched on `aitracker.server`):
10. `test_route_dispatch`: POST `install` and `reinstall` -> `svc_install(config.BIND_PORT, config.BIND_HOST)`
    once each; `uninstall` -> `svc_uninstall`; `"bogus"` -> 400 and nothing called. rc 3 -> status 202 and
    `svc_spawn_deferred` called once **after** the response (assert the client read the 202 body).
11. `tests/test_local_host_routes.py`: add `("GET", "/api/service"), ("POST", "/api/service")` to `ROUTES` and
    `svc_install`/`svc_uninstall`/`_svc_body` to its mock lists. The existing foreign-Host, cross-origin and
    loopback tests then cover the new route. Red: leave `/api/service` out of the l.476/l.659 tuples (a bypass,
    or a 404 instead of 403).

JS (node harness in `tests/test_update_settings_ui.py`; it loads the real `ext_cr_dialogs.js`, so a load-time
syntax error in that file shows up here, which the plain gate does not otherwise catch):
12. Rename: update the expected labels in `test_update_settings_ui.py` l.138-157,
    `test_pending_web_gaps.py` l.138-150 (`clicks=["Schedule","Reschedule","Unschedule"]`, `after_*` keys) and
    `test_pending_web_contract.py` l.267 to `["Reschedule","Unschedule","Scan now"]` / `["Schedule","Scan now"]`.
    Red: revert the three JS strings.
13. Service block: extend the harness fetch stub with `/api/service` GET/POST from `SCEN.svc`/`SCEN.afterPost`.
    Parameterise the block class it inspects (today it is hard-coded to `cr-sched-block`, l.77-87). Assert:
    not installed -> `["Install"]`; installed -> `["Reinstall","Uninstall"]`; `supported:false` -> `[]` +
    "macOS-only"; `waiting:true` -> text contains "waiting for :8790"; a POST answered 202 `deferred:
    "uninstall"` -> the "This dashboard was the service" text. Red: remove the block or the mount.

Gate notes (from memory): run `unset TRACKER_AUTH; make check` (otherwise about 33 blanket 401s). The commit
hook runs the full gate (180-380 s), so give Bash a timeout above 2 min. If the full run is OOM-killed
(`Killed: 9`), run one module per process and do not pipe it into `| tail`. One known flaky `term_vt`
backstop passes in isolation. Load-time JS errors in `ext_*` files are not caught by the gate, so also run
`node --check aitracker/web/ext_cr_dialogs.js` and load the page once on a **scratch** server (e.g.
`PORT=8797 TRACKER_SCHEDULER_AUTOINSTALL=0 python3 -m aitracker` from the worktree, stopped by PID, never
`pkill -f aitracker`; the user's dashboard on :8790 stays alone).

## §G Sequencing, files, risk

Order (each step leaves the gate green and is independently useful):
1. **§A rename** (`ext_cr_dialogs.js` 3 strings + 3 test files). This is contract clause 1b. It is
   independent, has the lowest risk, and makes the following block unambiguous.
2. **§C strict bind + `--service` + `config.BIND_PORT/SERVICE` + tunnel-skip** (`server.py` `bind`/`run`,
   `config.py`, `cli.py`) + tests 7-9. This lands first among the service pieces because the plist would be
   useless without it, and nothing installs yet.
3. **§B/§D schedule.py functions + CLI flags + Makefile targets** + tests 1-6. Usable from a terminal before
   any UI exists.
4. **§D route** (`server.py` import, `_svc_body`, GET/POST branches) + tests 10-11.
5. **§D `serviceBlock()`** + test 13.
6. **README** + `make bundle` sanity (`python3 dist/tracker.py --service-status` must print `supported`,
   and `can_install` false with the bundle reason).
7. **Live proof, with the user's go-ahead only, on a scratch identity:** bootstrap a plist from
   `service_plist(8799, "127.0.0.1")` with Label `com.aitracker.server.proof`. Check: waits while a scratch
   shell server holds 8799, takes over within 5 s after its SIGTERM, Reinstall and Uninstall from **inside**
   the proof service return 202 and converge (helper survives), Update-and-restart keeps `--service`. Then
   bootout and remove that plist and log (tear-down rule). Never touch `com.aitracker.server` or :8790 during
   the proof.

Files touched: `aitracker/schedule.py`, `aitracker/server.py`, `aitracker/config.py` (2 globals),
`aitracker/cli.py`, `aitracker/web/ext_cr_dialogs.js`, `Makefile`, `README.md`, `tests/test_service.py` (new),
`tests/test_local_host_routes.py`, `tests/test_update_settings_ui.py`, `tests/test_pending_web_gaps.py`,
`tests/test_pending_web_contract.py`. Not touched: `scripts/bundle.py`, `dist/tracker.py` (regenerate with
`make bundle` only), `autoinstall_once`.

**Riskiest spot: E1, the self-bootout from inside the launchd-run server.** It is the only part whose
correctness depends on launchd behaviour that unit tests cannot observe (does a `setsid` child survive
`bootout` of its parent's job?). Fallbacks in order: `AbandonProcessGroup: true` -> a `launchctl submit`
transient helper job. Either way the plist on disk is already in its final state, so the worst outcome is
"converges at next login" plus a UI message naming `make service-install`.

## Decisions the user may want to overrule

1. **Scheduler wording:** `Schedule` / `Reschedule` / `Unschedule` (contract fixes only "Schedule").
   Alternative: `Schedule` / `Reschedule` / `Remove schedule`, or keep `Reinstall`/`Uninstall` for the
   installed state.
2. **Stop semantics:** `KeepAlive {SuccessfulExit: false}` means `make stop` (or any clean SIGTERM) leaves the
   service stopped until the next login or Reinstall. Alternative: `KeepAlive: true` respawns within 30 s, but
   then `make stop && make serve` races the respawn and the shell server can drift to 8791.

Smaller calls also made here: buttons shown per state (not all three always); the service skips tunnel
autostart; HOST must be loopback; the port baked is the requested port, not the bound one.

## Adversarial review

Reviewer: opus, read-only, against `f5cf56c` in this worktree. Every claim below was checked with grep/sed
ranges. Verified as stated in the plan: schedule.py helper names and line ranges; `sched_install` removes the
plist when bootstrap fails (l.141-155); `_RO_GET_ALLOW` omits `/api/scheduler` (server.py l.297); the GET/POST
local-only tuples (l.476, l.659); `bind()` (l.956); `run()` installs SIGTERM before `bind()` (l.1027-1028);
`tunnel.autostart` (l.1034); `restart_in_place` re-execs `sys.orig_argv`, so `--service` survives
(update.py l.353); `cli.main` checks `in sys.argv` (it does not use argparse, so `--service` needs no parser
change); the 3 label tests and their line numbers; bundle ORDER (bundle.py l.11-15); no name collisions for
`svc_*`/`SVC_*`/`SERVICE`; no import-time threads in any module (a waiting copy really does nothing). The
user's live `com.aitracker.server` is **absent** (`launchctl print` fails and there is no plist; checked
2026-11-16). Package import takes 1.05-1.30 s (measured 3x), which sets the size of every race below.

**Counts: 2 HIGH, 3 MEDIUM, 7 LOW.**

### R1 [HIGH] `KeepAlive {SuccessfulExit:false}` breaks the user's stated goal after the everyday `make stop && make serve`
- **Defect:** §B l.152 and the decision at l.85-89. `make stop` (Makefile l.13-17) kills whatever LISTENs on
  PORT. When the service holds the port (true after every login, because RunAtLoad wins before any shell
  server exists), the user's normal restart habit kills the service. `_on_sigterm` then exits 0
  (server.py l.1016), and `SuccessfulExit:false` means launchd never restarts it.
  **Repro:** log in, so the service is on :8790. Run `make stop && make serve`, so the shell server is on
  :8790. Press Ctrl-C on the shell server. **Expected** (the goal: "takes over when the shell-started server
  stops"): the service serves :8790 within seconds. **Actual:** nothing serves :8790 until the next login;
  `launchctl print gui/$UID/com.aitracker.server` shows `state = not running` and `last exit code = 0`.
  This repo makes restarts frequent, because every edit needs `make serve` (CLAUDE.md "The rule that bites
  everyone").
- **Overstated in the plan:** the only reason given against `KeepAlive: true` is the respawn race
  (l.87-89). R2's startup grace removes that race, so the trade-off is no longer forced.
- **Fix direction:** `KeepAlive: true` plus R2's free-for-grace bind, so a shell server that is starting
  always wins and the service always comes back. **Must NOT change:** `bootout` (Uninstall) still stops it
  for good, because it removes the job and KeepAlive no longer applies. **This is a user decision (D2
  revised).**
- **Way:** in `service_plist()` set `"KeepAlive": True` and keep `"ThrottleInterval": 30`. README: "`make
  stop` stops the service only for about 4 s (it comes back); use Uninstall to stop it for good."
- **Test:** `test_service_plist_contents` asserts `d["KeepAlive"] is True`. Red with the dict form.

### R2 [HIGH] The strict-wait loop grabs the port the instant it frees: the shell server drifts, and the service serves stale Python
- **Defect:** §C l.166-179 binds on the first free poll. Three concrete failures:
  (a) **Restart race.** The service is waiting and the user runs `make stop && make serve`. The port is free
  for about 1.1 s (import time) and the poll period is 5 s, so the service takes :8790 roughly 1 time in 4-5
  and the new shell server lands on :8791 (it also opens a browser tab on :8791).
  (b) **The same race through the shell server's own "Update and restart":** the port is free during the
  exec gap (update.py l.360, then re-import).
  (c) **Stale code.** The waiting copy imported its Python at login. It can wait for days across `git pull`
  or an in-app Update of the same checkout. `build_page()` reads `web/*` on **every** `/` request
  (server.py l.427-428, page.py l.11-20), so after takeover the browser runs NEW JS against OLD routes.
  **Repro (c):** the service waits; apply an Update on the shell server, then stop it; the service takes
  over and any route the new JS added returns 404.
- **Fix direction:** bind only after the port has stayed free for a grace longer than one import. After any
  wait, do not serve from the long-lived process: exit 75, and KeepAlive respawns a fresh process that runs
  the current checkout code. **Must NOT change:** the non-strict path (`make serve` still walks to the next
  free port, and `TestPortFallback` stays green).
- **Way:** `server.py` imports `socket`. **`scripts/bundle.py` HEADER l.21 also needs `socket` added**: the
  bundle strips imports and re-adds only that list, so the plan's "no bundle change" claim becomes false with
  this fix. Code shape:
  ```python
  def _port_busy(host, port):
      try:
          socket.create_connection((host, port), timeout=1).close(); return True
      except OSError:
          return False

  def bind(host="127.0.0.1", port=8790, tries=20, strict=False, wait=5.0, grace=3.0):
      if strict:
          waited = False
          while True:
              if _port_busy(host, port):
                  if not waited: print("ai-tracker: port %d is busy; service mode waits for it" % port, flush=True)
                  waited = True; time.sleep(wait); continue
              if waited:      # freed after a wait: respawn fresh so we serve the CURRENT checkout code
                  print("ai-tracker: port %d is free; restarting to take it over" % port, flush=True)
                  raise SystemExit(75)
              time.sleep(grace)                       # a shell server starting right now wins the port
              if _port_busy(host, port): waited = True; continue
              try: return Server((host, port), Handler)
              except OSError as e:
                  if e.errno != errno.EADDRINUSE: raise
                  waited = True
      ...existing loop unchanged...
  ```
  `SVC_WAIT = 5.0` and `SVC_GRACE = 3.0` live in `schedule.py`. Exit 75 respawns under either KeepAlive form.
  Launchd respawns at once, because a process that waited has been alive for more than ThrottleInterval.
  This replaces E4's "fallback" with the main path, and costs one launchd log line per takeover, not one per
  poll.
- **Test:** `test_bind_strict_*` with `server._port_busy` and `server.time.sleep` patched to scripted
  sequences on a real free ephemeral port: `[F,F]` returns a Server on exactly `p`; `[T,T,F]` raises
  `SystemExit(75)` with `sleep(wait)` called twice; `[F,T,F]` (taken during the grace) raises
  `SystemExit(75)`; `Server` patched to raise `OSError(EADDRNOTAVAIL)` re-raises. Red: revert to "bind on
  the first free poll", and `[T,T,F]` then returns a Server.

### R3 [MEDIUM] The §G step-7 live proof cannot run as written, and it would touch the real label
- **Defect:** `_svc_target()` and `svc_plist_path()` hardcode `SVC_LABEL` (§B l.140-142). Reinstall or
  Uninstall pressed inside a `com.aitracker.server.proof` job therefore boots out and rewrites the **real**
  `com.aitracker.server`, which is exactly what l.447-448 forbids. Separately, `_svc_refusal` refuses this
  linked worktree (§D l.211), so the in-service self-defer path (E1, the riskiest spot) is unreachable from
  the worktree.
  **Repro:** bootstrap the proof plist from the worktree, then POST `{"action":"reinstall"}` to :8799.
  Expected: the proof job reinstalls. Actual: rc 2 "linked git worktree"; with the refusal bypassed, it would
  write `~/Library/LaunchAgents/com.aitracker.server.plist`.
- **Fix direction:** prove with the real label, but only behind a precondition, from a throwaway clone that
  is not a temp dir. **Must NOT change:** no proof-only env knob or label parameter in production code.
- **Way:** precondition: `launchctl print gui/$UID/com.aitracker.server` fails and no plist exists (true
  today); abort otherwise. `git clone <worktree> ~/aitracker-svc-proof` (not under /tmp or /var/folders, which
  `_is_temp` refuses), checkout the branch, then
  `PORT=8799 TRACKER_SCHEDULER_AUTOINSTALL=0 python3 -m aitracker --install-service` from the clone. Drive
  the routes with `curl -H 'Host: 127.0.0.1:8799'`. Teardown: `--uninstall-service`, confirm `launchctl print`
  fails, remove the plist, the log and the clone.
- **Test:** this is a manual proof, recorded in this file with command and output per check (see the clean
  plan §7).

### R4 [MEDIUM] Env-only `TRACKER_*` settings are silently dropped under launchd, including the `TRACKER_TUNNEL_READONLY` security floor
- **Defect:** §B l.149-150 bakes only 5 keys. `config.tunnel_readonly_floor` reads
  `os.environ["TRACKER_TUNNEL_READONLY"]` (config.py l.756-757), and cli.py l.16 documents it as "cannot be
  switched off from config". `TRACKER_TERM_APP` is set in this user's environment (key present; value not
  read), and `TRACKER_TERM_ALLOW`, `TRACKER_MAX_TERMS` and `TRACKER_PENDING_CLEAN` are also env-read.
  **Repro:** export `TRACKER_TUNNEL_READONLY=1`, Install, the service takes over, switch the Tunnel on from
  Config. Expected: remote callers are view-only, as on the shell server. Actual: the floor is gone, so
  remote callers can write.
- **Fix direction:** bake every `TRACKER_*` key present at install time except credential-shaped names, plus
  `LANG`/`LC_ALL`/`LC_CTYPE` when set. Without them, launchd starts with no LANG, so dashboard terminals
  start without a locale unless the rc files set one. **Must NOT change:** `TRACKER_AUTH` is never baked, and
  neither is any name matching `AUTH|PASS|TOKEN|SECRET|KEY`.
  This adds no new exposure to terminals: a shell-started server already passes these same keys to every
  terminal it opens.
- **Way:** `schedule._svc_env(port, host)` returns
  `{k: v for k, v in os.environ.items() if (k.startswith("TRACKER_") and not re.search("AUTH|PASS|TOKEN|SECRET|KEY", k) and k != "TRACKER_NO_BROWSER") or k in ("LANG","LC_ALL","LC_CTYPE")}`,
  then `.update(PATH=…, PYTHONPATH=_root(), PORT=str(int(port)), HOST=host, PYTHONUNBUFFERED="1")`.
  `service_plist` uses it.
- **Test:** `test_service_plist_contents` with `os.environ` patched to
  `{TRACKER_AUTH, GITHUB_PAT, TRACKER_TUNNEL_READONLY, TRACKER_TERM_APP, TRACKER_X_TOKEN, LANG, PATH}` asserts
  the exact key set `{PATH, PYTHONPATH, PORT, HOST, PYTHONUNBUFFERED, TRACKER_TUNNEL_READONLY, TRACKER_TERM_APP, LANG}`.
  Red: the 5-key dict.

### R5 [MEDIUM] Reinstall can bake the drifted port; the UI states a port the server will not bake
- **Defect:** `restart_in_place` sets `os.environ["PORT"] = str(actual)` (update.py l.351), so after an
  in-app Update-and-restart of a shell server that drifted to 8791, `cli.main` passes `port=8791` and
  `config.BIND_PORT` becomes 8791. Reinstall from that tab bakes 8791, and the service moves off 8790. The
  "requested, not got" rationale (l.90-96) does not survive one restart. Separately, the not-installed text
  says "on port <this_port>" (§D l.287), which is the *actual* port, while the server bakes `BIND_PORT`.
  The client is stating a value the server did not decide (convention 5).
  **Repro:** service on :8790, shell server drifted to :8791, Update and restart it, Reinstall. Expected:
  the plist keeps PORT 8790. Actual: PORT 8791.
- **Fix direction:** route `reinstall` keeps the installed plist's PORT/HOST; `install` uses
  `config.BIND_PORT/BIND_HOST`. The server exposes the port it will bake. **Must NOT change:** the CLI
  `--reinstall-service` still uses the env PORT the user typed.
- **Way:** `schedule.svc_baked()` returns `(int(env["PORT"]), env["HOST"])` from the plist, or None. In the
  route, `port, host = (svc_baked() if act == "reinstall" else None) or (config.BIND_PORT, config.BIND_HOST)`.
  `_svc_body` adds `install_port` (the baked port when installed, else `config.BIND_PORT`), and the UI
  renders `st.install_port`. `svc_status["port"]` is an `int`, so `waiting` compares ints.
- **Test:** route test: plist with PORT "8790", `config.BIND_PORT = 8791`, POST reinstall, then
  `svc_install` is called with `(8790, "127.0.0.1")`. Status test: `port` is the int `8790`. Red: the
  plan's `svc_install(config.BIND_PORT, …)`.

### R6 [LOW] `::1` is in the loopback allow-list, but the server cannot bind it
- **Defect:** §D l.214. `Server` is an AF_INET `ThreadingHTTPServer`, so `bind(("::1", p))` raises a
  non-EADDRINUSE error. The strict path re-raises, and under KeepAlive that becomes a crash loop every 30 s.
  `_local_caller` also requires peer `127.0.0.1` (server.py l.233).
- **Fix:** allow-list `("127.0.0.1", "localhost")` only. **Test:** add host `"::1"` to the refusal cases.
  Red: the 3-tuple.

### R7 [LOW] `cli.py` has no `import json`, so `--service-status` raises NameError
- **Defect:** cli.py l.1-7 imports only os/sys; §C l.194 calls `json.dumps`. **Fix:** `import json` in
  cli.py, and import `svc_*` from `.schedule`. **Test:** `test_cli_service_flags` patches
  `aitracker.cli.svc_status` and checks that `main()` with `--service-status` prints JSON. Red: no import.

### R8 [LOW] The bootout timeout is shorter than launchd's default ExitTimeOut
- **Defect:** `_sched_run` times out at 15 s (schedule.py l.114), but launchd waits up to its default
  ExitTimeOut (about 20 s) before it SIGKILLs. If shutdown is slow, `bootout` returns None, both bootstraps
  fail with "already loaded", and `svc_install` removes the plist. Reinstall from a shell server then ends
  uninstalled once the old job exits.
- **Fix:** add `"ExitTimeOut": 10` to the plist. **Must NOT change:** the remove-plist-on-failure behaviour
  for a genuine bootstrap error. **Test:** a plist key assertion in test 1.

### R9 [LOW] The plan claims more env isolation than launchd gives
- **Defect:** §E7 and the decision at l.101-103 imply the service and its terminals see only the baked keys.
  `launchctl print` of the existing `com.aitracker.pending` shows an **inherited environment** (key names
  `GITHUB_PAT` and `SSH_AUTH_SOCK`, values not printed). Launchd also adds HOME/USER/LOGNAME/SHELL/TMPDIR,
  which is why `os.environ.get("SHELL")` in term_vt.py l.3230 works.
- **Fix:** no code change. Correct the README/§E7 wording to "the plist adds only these keys; launchd's own
  per-user environment also applies". The key-set test stays scoped to the plist file.

### R10 [LOW] Missed: macOS privacy permissions differ under launchd
- **Defect:** term_launch.py l.212 runs `osascript` to drive Terminal/iTerm. Under launchd the responsible
  process is python3, not Terminal, so the first "open in Terminal" either raises an Automation prompt or
  fails with -1743. The checkout also lives under `~/Documents`, which macOS privacy controls protect. The
  scheduler job's `last exit code = 0` suggests reads already work, but that is not proven for terminals.
  None of this is unit-testable.
- **Fix:** add both to the live proof (clean plan §7). README: "the first external-terminal open from the
  service may ask to let python3 control Terminal".

### R11 [LOW] Wording left behind by the rename, and a conventions exception
- **Defect:** the status text "Turned off (you uninstalled it)" (ext_cr_dialogs.js l.1169; asserted in
  test_update_settings_ui.py l.143) and README l.279 still say "uninstall" next to an "Unschedule" button.
  The test_pending_web_gaps.py l.3 docstring says "Reinstall round-trip". conventions.md rule 6 lists its
  user-requested exceptions, but it has none for schedule.py writing `~/Library/LaunchAgents` and running
  launchctl. The scheduler does it unlisted, and this change doubles it.
- **Fix:** "Turned off (you unscheduled it)" plus that test; the README wording; the docstring. Add a
  one-line rule-6 exception quoting this contract: schedule.py may write/remove
  `~/Library/LaunchAgents/com.aitracker.{pending,server}.plist` and run `launchctl
  bootstrap/bootout/print`. It may run them only from a local caller or the CLI, and only with code-derived
  argv.

### R12 [LOW, no change] Bundle flattening makes `config.X = …` inside `run()` a local
- **Defect:** bundle.py l.45 rewrites `config.` to nothing, so `config.SERVICE = service` in `run()` becomes
  a function local in `dist/tracker.py`. This is the same pre-existing gap as `config.BIND_HOST` (l.1020).
  It is harmless here, because `_svc_refusal` refuses the bundle before anything reads `SERVICE`.
- **Fix:** no change. Note it in the PR body as a known gap, the same as base.

### Overengineering and over-claim verdicts
- **Tunnel skip: KEEP.** The plan understates the reason. `tunnel.cred()` falls back to a split of
  `config.AUTH` (tunnel.py l.77-80), which is empty under the service, so autostart at login would mint a
  *new* public credential the user never saw. It is one `if`.
- **Self-defer helper (E1): KEEP, but it is not the riskiest thing.** It is about 6 lines, and a
  `--reinstall-service` typed into a dashboard terminal already proves the pattern: the CLI runs in the pty's
  own session and survives `bootout` of its parent's job. The remaining unknown is coalition reaping, covered
  by the live proof.
- **`ProcessType: Interactive`: CUT.** It is unneeded. The default (Standard) does not throttle, and
  Interactive is documented "only if responsiveness depends on it".
- **Exit-75 fallback:** now the main takeover path (R2), so it is no longer a separate fallback.
- **Scratch-label proof:** replaced by R3.
- **13 tests:** proportionate. Fold test 8 into the R2 bind test; nothing else is cut.

## Overall clean plan

Contract unchanged (clauses 1a, 1b, 2). Same worktree and base. Every accepted fix above is folded in.

### 1. Rename the scheduler buttons (clause 1b) — `aitracker/web/ext_cr_dialogs.js`
- l.1182 `'Reinstall'` -> `'Reschedule'`; l.1183 `'Uninstall'` -> `'Unschedule'`; l.1185 `'Install'` ->
  `'Schedule'`; l.1169 -> `'Turned off (you unscheduled it)'`. API actions stay `install`/`uninstall`.
- Tests: test_update_settings_ui.py l.138-157 and l.143; test_pending_web_gaps.py l.3 and l.138-150
  (`clicks`, `after_*` keys); test_pending_web_contract.py l.267. README l.279 wording.
- **D1 (user):** `Schedule`/`Reschedule`/`Unschedule`. Renaming all three (not just Install) avoids two
  "Uninstall" buttons in one dialog.

### 2. Service mode: `--service`, strict grace bind, config globals — `server.py`, `config.py`, `cli.py`, `scripts/bundle.py`
- `config.py` next to `BIND_HOST` (l.139): `BIND_PORT = 8790`, `SERVICE = False`.
- `server.py`: `import socket`; `_port_busy(host, port)`; `bind(host, port, tries=20, strict=False,
  wait=5.0, grace=3.0)` with the R2 algorithm (wait while busy; exit 75 if it was busy then freed; otherwise
  `grace`, re-probe, bind; re-raise any non-EADDRINUSE error).
- `run(host, port, open_browser=True, service=False)`: `config.BIND_PORT = port`, `config.SERVICE =
  service`, `bind(host, port, strict=service, wait=SVC_WAIT, grace=SVC_GRACE)`. When not in service mode,
  call `tunnel.autostart`; otherwise print one "tunnel autostart skipped in service mode" line.
- `cli.py`: `import json`; import `svc_install, svc_uninstall, svc_status` from `.schedule`; handle
  `--install-service`/`--reinstall-service` (env PORT/HOST), `--uninstall-service` and `--service-status`
  before serving; `service = "--service" in sys.argv`, with `open_browser=False` when set. Add one HELP line
  for the three public flags.
- `scripts/bundle.py` HEADER l.21: add `socket`.
- Tests: `test_bind_strict_*` (the 4 R2 scripted cases); `test_cli_service_flags` (`--service` gives
  `service=True, open_browser=False`; plain argv gives `False`; `--service-status` prints JSON). Existing
  `TestPortFallback` stays green.

### 3. LaunchAgent functions — `aitracker/schedule.py` (docstring updated)
- `SVC_LABEL = "com.aitracker.server"`, `SVC_WAIT = 5.0`, `SVC_GRACE = 3.0`; `svc_plist_path()`,
  `svc_log_path()` (`~/Library/Logs/ai-tracker-server.log`), `_svc_target()`, `_read_svc_plist()`.
- `_svc_env(port, host)` (R4). `service_plist(port, host)`: Label, ProgramArguments `[sys.executable, "-m",
  "aitracker", "--service"]`, WorkingDirectory `_root()`, EnvironmentVariables `_svc_env`, `RunAtLoad:
  True`, `KeepAlive: True` (R1/D2), `ThrottleInterval: 30`, `ExitTimeOut: 10` (R8), stdout/stderr to the
  log. No ProcessType.
- `_svc_refusal(host)`: platform, bundle, linked worktree or `/.claude/worktrees/` path, temp dir, host not
  in `("127.0.0.1","localhost")` (R6).
- `svc_install(port, host, run=subprocess.run)` returns 0 ok, 1 launchctl failed (plist removed), 2
  refused, 3 deferred (self). It writes the plist 0644 first; returns 3 if `config.SERVICE`; otherwise
  bootout, then bootstrap, retrying once after 1 s.
- `svc_uninstall(run)` returns 0, or 3 when self. It removes the plist first and never touches the
  scheduler opt-out.
- `svc_spawn_deferred(reinstall, popen=subprocess.Popen)` is the `/bin/sh` helper from §D, unchanged
  (`start_new_session=True`, DEVNULL stdio).
- `svc_baked()` returns `(port:int, host)` from the plist, or None (R5).
- `svc_status(run)` returns `{supported, installed, loaded, pid, state, last_exit, port:int, host, python,
  python_exists, root, root_exists, can_install, reason}`. It never raises, and it makes no launchctl call
  off darwin.
- `Makefile`: `service-install|reinstall|uninstall|status` (two-line recipes), added to `.PHONY` and help.
  `make stop` is unchanged.
- Tests (`tests/test_service.py`, `test_pending_schedule.py` scaffolding): plist contents including
  KeepAlive True, ExitTimeOut and the R4 exact key set; refusals including `::1`; install sequence and
  failure; uninstall (no opt-out file); status parse with int port, missing python, non-darwin; self-defer
  rc 3 plus helper argv; `svc_baked`.

### 4. Route — `server.py`
- Import the `svc_*` names at l.12. `_svc_body(this_port, rc=None)` returns `svc_status()` plus `self`,
  `this_port`, `install_port` (R5), `started_at`, `waiting` (int compare), and server-owned error strings
  for rc 1 and 2.
- GET: add `/api/service` to the l.476 tuple, with a 3-way dispatch. POST: add it to the l.659 tuple. The
  `/api/service` branch validates `action` in `install|reinstall|uninstall`. For reinstall it takes the port
  and host from `svc_baked()`, falling back to `config.BIND_PORT/BIND_HOST`. rc 3 returns 202, then
  `svc_spawn_deferred` runs in `finally`.
- Tests: route dispatch (including the R5 reinstall-keeps-port case and 202-then-spawn);
  `test_local_host_routes.py` ROUTES gains GET/POST `/api/service`, with `svc_install`/`svc_uninstall`/
  `_svc_body` mocked.

### 5. UI — `serviceBlock()` on the Server tab after `updEl` (ext_cr_dialogs.js l.1593)
- States as in §D, with `install_port` from the server in the not-installed text. On a 202 deferred
  reinstall, poll `/api/service` every 1 s and tolerate failed fetches during the gap (about 4-5 s with the
  grace). Reload when `started_at` changes; time out after 60 s with the `make service-install` hint.
- Test: harness `/api/service` stub plus a parameterised block class, covering not installed, installed,
  unsupported, waiting, and 202-uninstall. Also run `node --check aitracker/web/ext_cr_dialogs.js`.

### 6. README and conventions
- A "Background service (macOS)" subsection covering: same port; waits and takes over within about 8 s
  (5 s poll plus 3 s grace); a shell server that is starting always wins; `make stop` stops it only briefly
  (R1), and Uninstall stops it for good; loopback-only, with no TRACKER_AUTH; non-secret `TRACKER_*`/LANG
  are carried; launchd's own env also applies (R9); no tunnel autostart, and a runtime tunnel gets its own
  credential; not from worktrees or the bundle; possible Automation prompt (R10); the log path; the `make
  service-*` aliases.
- conventions.md rule-6 exception line (R11).
- `make bundle`, then check that `python3 dist/tracker.py --service-status` prints `supported` with
  `can_install:false` and the bundle reason.

### 7. Live proof (user go-ahead only; R3, R10)
Precondition: the real label is absent, which is true today. Work in a clone at `~/aitracker-svc-proof`.
1. Run `PORT=8799 … --install-service`. Expect a log line and :8799 served by the launchd pid.
2. Start a scratch shell server on :8799 first, then install. The service logs "busy" once. SIGTERM the
   shell server by PID. Expect: exit 75 in the log, then a fresh pid serving within about 8 s.
3. Run `make stop PORT=8799` against the service. It must come back within about 5 s (R1).
4. Kill the service and immediately start a shell server on 8799. The shell server must win the port.
5. POST reinstall and uninstall to `/api/service` *inside* the service. Expect 202, and the job converges
   (the setsid helper survives; otherwise switch to `AbandonProcessGroup: true`).
6. Update-and-restart keeps `--service` (`ps -o args`).
7. Open a dashboard terminal in a `~/Documents` project and run `ls`. Also try "open in Terminal" once
   (R10).

Teardown: uninstall; `launchctl print` fails; remove the plist, the log and the clone; stop every scratch
server by PID.

### Sequencing
1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7. Each step leaves `unset TRACKER_AUTH; make check` green. §2 lands before
any plist exists, so nothing can install a half-built service.

**Riskiest spot:** E1, the in-service self-bootout plus helper survival, together with the R10 privacy
behaviour. Neither can be unit-tested. **Fallbacks:** `AbandonProcessGroup: true`, then a `launchctl
submit` helper job. The end state is safe either way: the plist is already final, and the UI's 60 s message
names `make service-install`.

### Decisions for the user
- **D2 (revised, recommended):** `KeepAlive: true` plus grace bind. The service always returns, and `make
  stop` no longer stops it (Uninstall does). The alternative, the plan's `SuccessfulExit:false`, silently
  disables takeover after the first `make stop` that hits the service.
- **D1:** scheduler wording (above).

## Reconciliation (main thread, 2026-11-16)

Spot-checked against f5cf56c: update.py:351 overwrites `PORT` with the drifted port (R5 real); cli.py imports only os/sys (R7 real); `TRACKER_TERM_APP` / `TRACKER_TUNNEL_READONLY` are env-read settings (config.py:323-337, cli.py:16 — R4 real).

| # | Sev | Verdict | Note |
|---|---|---|---|
| R1 | HIGH | confirmed | `make stop` exits the service 0 → SuccessfulExit:false never restarts it. Adopt `KeepAlive: true`. |
| R2 | HIGH | confirmed | Instant-takeover race + stale imported code are real. Grace bind + exit 75 after a wait, as written (~15 lines); a pure exit-and-respawn variant was considered and rejected (one launchd log line per ThrottleInterval while the shell server runs). |
| R3 | MED | confirmed | Proof must not touch the real label from a worktree; run from a scratch clone, user go-ahead only. |
| R4 | MED | confirmed | Bake non-secret `TRACKER_*` + `LANG`; `TRACKER_AUTH` and anything token-shaped stays excluded (test asserts). |
| R5 | MED | confirmed | Reinstall reuses the installed plist's port. |
| R6–R11 | LOW | confirmed | Apply as written. Cut `ProcessType: Interactive` (agreed). |
| R12 | LOW | no change | Pre-existing bundle quirk; document only. |
| — | — | missed by both | None found beyond the review; live behaviour of the self-uninstall helper remains provable only by the live proof (riskiest spot). |

Implement from **## Overall clean plan** with KeepAlive:true (D2) unless the user overrules.

## User sign-off (2026-11-16)

- D2: KeepAlive: true + grace bind ("Always come back").
- D1: scheduler block buttons Schedule / Reschedule / Unschedule (API actions unchanged).
- Live proof: approved (separate leg; not part of the implementation of steps 1-6).

## Implementation log

Steps 1-6 of the clean plan implemented in this worktree (uncommitted). Red-proof = the fix reverted by a scoped replace, the test run, the fix restored, the test run green.

- `test_service_plist_contents` -> KeepAlive reverted to the SuccessfulExit dict, and separately the `AUTH|PASS|TOKEN|SECRET|KEY` filter dropped -> RED both -> green
- `test_install_refusals` -> `"::1"` added back to the loopback allow-list -> RED -> green
- `test_self_defers` -> `config.SERVICE` early return dropped (svc_install, then svc_uninstall) -> RED both -> green
- `test_bind_strict_exits_75_after_a_wait` -> bind on the first free poll after a wait -> RED -> green
- `test_bind_strict_taken_during_grace_exits_75` -> grace re-probe removed -> RED -> green
- `test_bind_strict_reraises_other_errors` -> EADDRINUSE guard removed -> RED -> green
- `test_bind_strict_free_binds_on_exact_port` -> positive path (no revert; covered by the three above)
- `test_reinstall_keeps_installed_port` -> route uses `config.BIND_PORT` instead of `svc_baked()` -> RED -> green
- `test_route_dispatch` -> action validation removed, and separately the `rc != 3` guard removed (spawn called after rc 0) -> RED both -> green
- `test_route_deferred_returns_202_then_spawns` -> positive path (the `rc != 3` revert alone is not red here, because the 202 path is the fall-through; the guard is proved by `test_route_dispatch`)
- `test_body_fields` -> `waiting` forced False -> RED -> green
- `test_cli_service_flags` -> `not service and` removed from open_browser -> RED -> green
- `test_cli_service_status_prints_json` -> `import json` removed from cli.py -> RED -> green
- `test_foreign_host_refused_everywhere` (ROUTES now has GET/POST `/api/service`) -> `/api/service` dropped from the POST tuple -> RED -> green
- `BackgroundServiceBlock.test_states` -> `svcEl` mount removed -> RED -> green
- `BackgroundServiceBlock.test_deferred_reinstall_polls_through_gap_then_reloads` -> started_at-change reload disabled -> RED -> green
- `BackgroundServiceBlock.test_actions_post_and_deferred_uninstall` -> positive path
- `ScheduledScanBlock.test_four_status_texts_and_buttons` -> each of the 3 button strings and the "Turned off" text reverted to the old wording -> RED each -> green
- status tests (`test_status_parses_launchctl`, `..._missing_python_and_not_loaded`, `..._non_darwin_makes_no_call`, `test_baked_none_without_plist`) -> positive/edge paths, no revert run

Deviations: none from steps 1-6. Notes: `server.py` imports `svc_*` on a second single-line `from .schedule import` because bundle.py strips only one-line relative imports (a multi-line import left an IndentationError in dist/tracker.py, caught by TestBundle). `python3 dist/tracker.py --service-status` prints `supported: true, can_install: false, reason: "not a package checkout (bundle)"`. `reports/launchd-server-install.md` step 7 (live proof) NOT done. Nothing was committed or pushed.

### Review fixes
- A-F1 `tests.test_service.BindStrictTest.test_port_busy_only_refused_means_free`: RED with `_port_busy` catching any OSError as free, GREEN after.
- A-F1 `BindStrictTest.test_bind_strict_eaddrinuse_retries_without_exit`: RED with `waited = True` on EADDRINUSE, GREEN after.
- A-F2/B-M1 `CliTest.test_cli_install_inside_service_defers`: RED without the `svc_spawn_deferred(True)` call, GREEN after.
- A-F2/B-M1 `CliTest.test_run_service_sets_marker`: RED without the `AITRACKER_SERVICE_PID` set in `run()`, GREEN after.
- A-F3+B-I1 `CliTest.test_cli_reinstall_keeps_baked_port_without_env`: RED without the `svc_baked()` lookup, GREEN after.
- A-F4 `RouteTest.test_route_deferred_returns_202_then_spawns` (order json then spawn): RED with spawn-before-202 swap, GREEN after.
- A-F5 `tests.test_pending_routes_matrix` (`/api/service` GET+POST rows): RED with `/api/service` dropped from the GET dispatch tuple, GREEN after.
- B-L1 `InstallTest.test_install_never_truncates_live_plist`: RED with the in-place truncating write, GREEN after.
- B-L2 `InstallTest.test_install_refusals` (temp interpreter case): RED with the exe check disabled, GREEN after.
- B-L3 `StatusTest.test_status_ignores_nested_pid_lines`: RED with unanchored `\bpid`, GREEN after.
- B-L4 `BackgroundServiceBlock.test_states` (loaded-without-plist, can_install=False): RED with `st.installed` only gating Uninstall, GREEN after.
- B-L5 `PlistTest.test_service_plist_contents` (SHELL carried): RED without SHELL, GREEN after.
- B-L7 `ScheduledScanBlock.test_four_status_texts_and_buttons` + `test_pending_web_contract` ("Scheduled"/"Not scheduled"): RED with "Not installed" text, GREEN after.
- A-F6/B-L6/B-M2/A-F7: README wording (takeover timing, env baked at install, TCC note) and the cli.py comment move; no test.

## Implementation review reconciliation (main thread, 2026-11-16)

Reviews: `reports/launchd-server-install.impl-review-A.md` (server/cli) and `…-B.md` (schedule.py/UI). Fixer applies every row marked **fix**, using the designed fix in the review file.

| Finding | Verdict | Action |
|---|---|---|
| A-F1 `_port_busy` treats ConnectionReset as free (reproduced) | confirmed MED | **fix** as designed (only ConnectionRefused = free; EADDRINUSE from Server() sleeps, doesn't set waited) |
| A-F2 = B-M1 CLI install/reinstall from a dashboard terminal kills itself before bootstrap | confirmed MED (duplicate) | **fix once**: `AITRACKER_SERVICE_PID` marker set in `run(service=True)`; CLI paths write plist then `svc_spawn_deferred` |
| A-F3 Makefile `PORT ?= 8790` resets a custom port on reinstall + B-I1 CLI reinstall ignores installed port | confirmed LOW | **fix together**: CLI `--reinstall-service` uses `svc_baked()` port unless PORT explicitly given; Makefile passes PORT only if set |
| A-F4 no test that 202 precedes spawn | confirmed LOW | **fix** (test only) |
| A-F5 `/api/service` missing from routes matrix test | confirmed LOW | **fix** (test only) |
| A-F6 = B-L6 README takeover timing / env baked at install | confirmed LOW | **fix** README wording |
| A-F7 misplaced comment | nit | **fix** |
| B-M2 TCC under ~/Documents | confirmed MED (risk) | **fix**: README note; live proof clone goes under `~/Documents`. Status-hint UI: overengineered — cut |
| B-L1 plist emptied before build | confirmed LOW | **fix**: build bytes first, write atomically |
| B-L2 temp/venv interpreter not refused | confirmed LOW | **fix**: refuse when `sys.executable` is under a temp dir or `.claude/worktrees` |
| B-L3 unanchored `launchctl print` regexes | confirmed LOW | **fix**: anchor to line start, test with a `parent pid` line |
| B-L4 running job without plist shows no Uninstall | confirmed LOW | **fix** |
| B-L5 `SHELL` not carried | confirmed LOW | **fix**: add SHELL to the carried env |
| B-L7 scheduler status still says "Installed" next to Schedule | confirmed LOW | **fix** (assumption, consistent with D1): "Scheduled" / "Not scheduled" |
| B-I2 helper survives bootout | unproven | live proof step |
| missed by both | — | none found |

## Live proof (2026-11-16, bf34517, clone under ~/Documents, port 8799) — ALL PASS

| Step | Result | Evidence |
|---|---|---|
| Install (CLI) | PASS | pid ppid=1, HTTP 200 first poll; plist KeepAlive/RunAtLoad true, Throttle 30, `--service`; env keys HOST LANG PATH PORT PYTHONPATH PYTHONUNBUFFERED SHELL TRACKER_TERM_APP (no AUTH/tokens) |
| KeepAlive | PASS | SIGTERM → new pid serving 200 in ~4 s |
| Takeover | PASS | shell server owned :8799 (no drift); service logged "port 8799 is busy; service mode waits"; after shell server killed, service owned :8799 in ~24 s (30 s throttle) |
| Reinstall from inside | PASS | POST → 202 `{"deferred":"reinstall","self":true}`; new pid ppid=1 serving in ~7 s |
| Uninstall from inside | PASS | POST → 202; label gone in 2 s, plist deleted, port free, no respawn after 40 s |
| CLI reinstall/uninstall | PASS | reinstall without PORT kept baked 8799; uninstall cleared label/plist/port. Note: an exported `PORT` in the shell is treated as explicit (cli.py) — by design |
| TCC (~/Documents) | PASS | no prompt, no "Operation not permitted" |
| Teardown | PASS | label + plist absent, :8799 free, clone + log removed; :8790 still pid 86000 (verified by main thread) |
