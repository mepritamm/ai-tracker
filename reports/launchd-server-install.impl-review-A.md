# Implementation review A — launchd server install (server.py / cli.py / config.py / bundle / Makefile / route tests)

Reviewer stance: assume the implementation log is false. Scope: `aitracker/server.py` (`_port_busy`, strict
`bind`, `run(service=)`, `_svc_body`, GET/POST `/api/service`), `aitracker/cli.py`, `aitracker/config.py`,
`scripts/bundle.py`, Makefile `service-*`, `tests/test_service.py`, `tests/test_local_host_routes.py`.
Schedule.py and the JS are reviewer B's scope.

Counts: **HIGH 0 · MEDIUM 2 · LOW 4 · NIT 1**.

---

## F1 [MEDIUM] Strict bind treats a stalled holder as "free": exit 75 while the port is still held, then a respawn loop

- **Defect:** `server.py:990-995` `_port_busy` returns False on *any* `OSError`. A listener whose accept queue
  is full answers connect with `ConnectionResetError` (errno 54) on macOS. Then `bind` (l.1013-1015) takes
  the "freed after a wait" branch and raises `SystemExit(75)`. launchd respawns it. The new process probes
  "free", sleeps through the grace, and `Server()` fails with EADDRINUSE (l.1021-1025). That sets
  `waited = True`, the next probe says "free" again, and it exits 75 again. The result is a respawn loop at
  launchd's ThrottleInterval (30 s), with two log lines per cycle, for as long as the holder is stalled.
- **Realistic trigger:** a user presses Ctrl-Z on `make serve` (SIGTSTP). The listening socket stays open.
  The service's own probes connect and close every 5 s, and those connections sit unaccepted in the
  backlog (`request_queue_size=5`), so the queue fills within about 30 s even with no browser open. A
  wedged shell server (main thread stuck) does the same.
- **Repro (run during this review, ephemeral port, sleeps patched):** listen(1) on a socket that never
  accepts, open 8 non-blocking connects to fill the queue, then run
  `_server._port_busy("127.0.0.1", port)`. Actual: `False`. Then `bind(..., strict=True)`. Actual: it
  prints "port N is free; restarting to take it over", then `SystemExit 75` while the holder still
  LISTENs. Expected: it reports busy and keeps waiting.
- **Fix direction:** only a refused connection means free. Any other connect error (reset, timeout,
  unreachable) means busy. An EADDRINUSE from `Server()` must not lead straight to an exit-75 respawn.
  **Must NOT change:** the non-strict `make serve` path (it never calls `_port_busy`), and the R2 semantics
  ("busy then freed" exits 75; "taken during grace" exits 75 later).
- **Way:**
  ```python
  def _port_busy(host, port):
      try:
          socket.create_connection((host, port), timeout=1).close()
          return True
      except ConnectionRefusedError:
          return False
      except OSError:          # reset (full backlog: a stopped/wedged holder), timeout, ...: still held
          return True
  ```
  In `bind`'s `except OSError as e:` branch (l.1022-1025), replace `waited = True` with
  `time.sleep(wait)` and leave `waited` unchanged. A socket that is bound but not listening (refused +
  EADDRINUSE) then retries bind every wait+grace instead of exiting. A shell server that won the
  probe→bind race is seen as busy on the next probe, and the normal path follows.
- **Test (red before the fix):** add to `BindStrictTest` in `tests/test_service.py`:
  1. `test_port_busy_on_stalled_listener`: use a real socket with `listen(1)`, never accept, and fill
     the backlog with 8 non-blocking connects. Assert `_server._port_busy("127.0.0.1", port) is True`.
     It is red today (returns False).
  2. `test_bind_strict_eaddrinuse_retries_without_exit`: patch `_port_busy` to always False, and
     `Server` with `side_effect=[OSError(errno.EADDRINUSE, "x"), sentinel]`. Assert it returns
     `sentinel` and that sleeps are `[3.0, 5.0, 3.0]`. It is red today (`SystemExit(75)`).

## F2 [MEDIUM, missed by plan and review] `make service-install|reinstall` from a dashboard terminal served by the service leaves the service unloaded

- **Defect:** `cli.py:49-50` runs `svc_install` synchronously, and `config.SERVICE` is False in the CLI
  process. `svc_install` runs `launchctl bootout` first, then `bootstrap`. If the CLI runs inside a
  dashboard terminal (a `pty.fork` child of the service, term_run.py:361 / term_vt), the bootout
  terminates the service. Its pty master closes and the kernel SIGHUPs the terminal's foreground group,
  which is `make` plus the Python CLI. Both die inside `subprocess.run(bootout)`, before `bootstrap` runs.
  The end state: the plist is on disk and the job is not loaded, so the dashboard is down until next
  login or a manual install from a real terminal. The UI path handles "self" through rc 3 and
  `svc_spawn_deferred`. The CLI path has no such detection. `--uninstall-service` is fine: the plist is
  removed and the bootout request is sent before the hangup.
- **Repro:** with the service installed and serving :8790, open a dashboard terminal on that page and
  run `make service-reinstall`. Expected: the service returns on :8790. Actual (by construction; confirm
  in live proof step 7): the shell dies, and `launchctl print gui/$UID/com.aitracker.server` fails.
- **Fix direction:** when the CLI is a descendant of the service job, install and reinstall go through
  the same deferred, setsid helper the route uses. The plist is written first, and the CLI exits 0 with a
  "deferred" line. **Must NOT change:** the synchronous rc 0/1/2 path from an ordinary terminal, and
  uninstall's ordering.
- **Way:** in `run()`, when `service` is set, add `os.environ["AITRACKER_SERVICE_PID"] = str(os.getpid())`.
  Use a name outside `TRACKER_*` so `_svc_env` never bakes it into a plist. Every dashboard terminal
  inherits it. In `cli.main` before l.49:
  `in_svc = bool(os.environ.get("AITRACKER_SERVICE_PID"))`. For install and reinstall when `in_svc`, set
  `config.SERVICE = True`, call `rc = svc_install(port, host)`, and if `rc == 3`, call
  `svc_spawn_deferred(True)`, print "deferred: the service restarts in about 2 s", and `sys.exit(0)`.
  Otherwise `sys.exit(rc)`. Import `svc_spawn_deferred` in cli.py. `launchd`'s own `XPC_SERVICE_NAME ==
  SVC_LABEL` is an alternative detector, but it is unverified that it survives into pty children.
- **Test (red before the fix):** in `CliTest`, `test_cli_install_inside_service_defers`. Set the env
  marker, patch `cli.svc_install` with a side effect that returns 3 when `config.SERVICE` else 0, and
  patch `cli.svc_spawn_deferred`. Run `--reinstall-service`. Assert spawn is called once with `True` and
  the exit code is 0. It is red today: cli has no spawn call, and exits with svc_install's 0 without
  deferring. Add the scenario to live-proof step 7.

## F3 [LOW] `make service-reinstall` silently resets a custom installed port to 8790

- **Defect:** `Makefile:62-63` runs `PORT=$(PORT) … --reinstall-service` with `PORT ?= 8790` (l.1). The
  CLI (cli.py:49) bakes the env PORT. R5's "must NOT change" kept the CLI on "the env PORT *the user
  typed*". Through `make`, though, the user typed nothing, and gets 8790.
- **Repro:** run `make service-install PORT=8799`, later `make service-reinstall` (for example after a
  Python upgrade). Expected: the plist PORT stays 8799. Actual: 8790, and the service moves.
- **Fix direction:** an explicit PORT still wins. A default reinstall keeps the baked port and host, the
  same as the route. **Must NOT change:** `--install-service` semantics.
- **Way:** in the Makefile, give `service-reinstall` the env only when it was set:
  `@$(if $(filter command line environment,$(origin PORT)),PORT=$(PORT) ,)python3 -m aitracker --reinstall-service`.
  In cli.py, for `--reinstall-service` when `"PORT" not in os.environ`, use
  `port, host = svc_baked() or (port, host)`.
- **Test:** add `CliTest.test_cli_reinstall_keeps_baked_port_without_env`. Pop PORT from the env, patch
  `cli.svc_baked` to return `(8799, "127.0.0.1")` and `cli.svc_install`, then run `--reinstall-service`.
  Assert it is called with `(8799, "127.0.0.1")`. It is red today (`8790`).

## F4 [LOW] "202 is flushed before the spawn" is not tested

- **Defect:** `server.py:695-699` is correct today. `Handler` keeps the default `wbufsize=0`, so the
  `_SocketWriter.sendall` writes happen before `finally` runs, on HTTP/1.0. The helper also sleeps 1 s.
  But `test_route_deferred_returns_202_then_spawns` does not pin the order. **Re-proved:** with the code
  swapped to `svc_spawn_deferred(...)` and then `self._json(..., 202)`, `tests.test_service` stays green
  on the route tests. The only failures in that run were the unrelated transients noted below.
- **Fix direction:** test only, no code change.
- **Way / test:** in `RouteTest.test_route_deferred_returns_202_then_spawns`, wrap `_server.Handler._json`
  (use `mock.patch.object(..., autospec=True, side_effect=orig)` that appends `"json"` to a list) and give
  `svc_spawn_deferred` `side_effect=lambda r: order.append("spawn")`. Assert
  `order == ["json", "spawn"]`. It is red with the swapped order.

## F5 [LOW] `/api/service` is missing from the proxy / read-only / tunnel / non-local-peer matrix

- **Defect:** the code is safe by construction. GET: it is not in `_RO_GET_ALLOW` (server.py:313) → 403,
  then `_local_caller`. POST: read-only is deny-all before the body is parsed, then `_local_caller`.
  **Re-proved:** moving the GET `/api/service` dispatch above `_local_caller` turns
  `test_foreign_host_refused_everywhere` and `test_cross_origin_refused_everywhere` RED (200 != 403).
  But `tests/test_pending_routes_matrix.py:22-31` ROUTES, which sweeps `X-Forwarded-For`, a read-only
  tunnel visitor, tunnel credentials and a non-loopback peer, has no `/api/service` rows. A future
  reorder that bypasses only the proxy check would go unseen.
- **Fix direction:** test only.
- **Way:** add `("GET", "/api/service", None)` and `("POST", "/api/service", {"action": "install"})` to
  ROUTES, add `"/api/service": 200` to LOCAL_OK, and in that file's setUp mock `svc_install`,
  `svc_uninstall`, `svc_spawn_deferred` and `_svc_body`, as test_local_host_routes.py does.
- **Test:** it is red if `/api/service` is dropped from the GET tuple at server.py:492 or the POST tuple
  at l.677.

## F6 [LOW] The README's "takes over within about 8 s" is false for a service younger than ThrottleInterval, and update-restart in service mode adds 3 s

- **Defect:** README.md:76. The exit-75 respawn is subject to launchd's `ThrottleInterval: 30`, counted
  from the previous launch. If the service launched less than 30 s before the shell server stops (for
  example right after `make service-install`, which is when a user tests takeover), takeover takes
  about 20-35 s. Separately, `restart_in_place` exec's `--service` (orig_argv keeps the flag, so this was
  verified OK), and the new process then runs the 3 s grace before binding.
- **Fix direction:** documentation only, no code change.
- **Way:** add one clause to README l.76: "(up to ~30 s if the service itself started less than 30 s
  earlier — launchd throttles restarts)". The in-place update note can say that the service is
  unreachable for about 3 s longer.
- **Test:** none; this is documentation.

## F7 [NIT] cli.py:56 carries the HOST comment on the wrong line

- `service = "--service" in sys.argv   # internal: … # 0.0.0.0 to reach it from a phone/tablet on LAN/Tailscale`.
  The `0.0.0.0` comment belonged to the `host =` line (l.48). Move it back. No test.

---

## Verified, with no finding

- **Strict bind never drifts:** the `while True` loop (server.py:1004-1025) only returns
  `Server((host, port))` or raises. The `range(port, port+tries)` loop is unreachable when `strict`.
- **SystemExit(75) inside run():** it is raised before `publish_endpoint`, `start_worker` and the
  autoinstall thread. `PORT_FILE` and `TOKEN_FILE` are untouched, and no worker thread is left. The
  SIGTERM handler is installed but harmless: a SIGTERM during the wait → `tunnel.stop` no-op → exit 0.
  The atexit tunnel hook is a no-op.
- **`make serve` is unchanged:** `bind` defaults to `strict=False`, so it takes the identical old loop.
  `open_browser` evaluates to the same value without `--service`. `tunnel.autostart` is still called, and
  the print lines are identical. The only new effects are `config.BIND_PORT` and `config.SERVICE`
  assignments.
- **The 202 is flushed before the spawn:** `wbufsize=0`, HTTP/1.0, the spawn runs in `finally`, and the
  helper starts with `sleep 1`.
- **Non-local, read-only and tunnelled callers cannot reach `/api/service`:** checked for GET and POST,
  as described under F5.
- **`--service` survives `update.restart_in_place`:** `argv = sys.orig_argv or [exe, -m, aitracker,
  *sys.argv[1:]]` (update.py:353). `PORT` is set to the actual port, which in strict mode is the asked
  port.
- **The bundle runs:** the HEADER has `socket`. `dist/tracker.py` (17:13) parses, and `--version` runs.
  `config.X = …` inside `run()` becomes a local, which is the known R12 issue and harmless because
  `_svc_refusal` refuses the bundle.
- **Red re-proofs:** (1) GET guard bypass → RED, as expected. (2) Spawn-before-202 swap → stayed green,
  which is F4. Both edits were restored. `git diff --stat -- aitracker/server.py` matches the
  implementer's +90/-10.
- **Gate:** `python3 -m unittest tests.test_service tests.test_local_host_routes` ran 27 tests, OK, after
  the restore.

## Note for the main thread

One run of `tests.test_service`, made while I had only edited server.py (the 202 order), also failed
`test_service_plist_contents` and `test_status_parses_launchctl`. A re-run moments later was green. This
looks like reviewer B's concurrent red-proof edits to `schedule.py`. Re-run the full gate once both
reviewers are done.
