# Implementation review B: launchd-server-install (schedule.py, ext_cr_dialogs.js, README, conventions, UI/schedule tests)

Reviewer brief: assume the implementer's report is false. This review was read-only except for two scoped red-proof edits, both restored (`git diff --stat -- aitracker/schedule.py` is unchanged at 176 lines and test_service is green after the restore). server.py and cli.py are reviewer A's scope. They appear here only where a schedule.py defect reaches them.

## Verdict

0 HIGH, 2 MEDIUM, 7 LOW, 2 INFO. Steps 1, 3, 5 and 6 of the clean plan are implemented as written, and the gate is green for the in-scope modules. Both MEDIUM findings are live-path gaps that unit tests cannot see.

## Re-verified (not defects)

- **Plist:** Label, `ProgramArguments [sys.executable,-m,aitracker,--service]`, `WorkingDirectory=_root()`, `RunAtLoad`, `KeepAlive: True`, `ThrottleInterval 30`, `ExitTimeOut 10` (below `_sched_run`'s 15 s timeout, so R8 holds), no ProcessType, stdout and stderr both going to `~/Library/Logs/ai-tracker-server.log`. Checked at schedule.py:268-280.
- **Env filter:** `TRACKER_AUTH`, `GITHUB_PAT`, `TRACKER_*TOKEN*` and `TRACKER_NO_BROWSER` are dropped. `TRACKER_TUNNEL_READONLY`, `TRACKER_TERM_APP` and `LANG` are kept. None of the `TRACKER_*` names the code reads is credential-shaped apart from `TRACKER_AUTH` (grep over aitracker/).
- **XML escaping:** plistlib escapes `& < >` and tabs, and they round-trip. Control characters are the exception (L1).
- **Refusals:** non-darwin, bundle, linked worktree, a `/.claude/worktrees/` path, a temp dir, `0.0.0.0`, `::1` and a LAN IP all return 2, make no launchctl call and write no plist.
- **Deferred path:** `svc_install` writes the final plist before it returns 3, so the helper's `$3` bootstraps the NEW plist. `svc_uninstall` removes the plist before it returns 3. The helper is `start_new_session=True` (setsid, so it is outside the job's process group, which launchd kills), with `close_fds` and DEVNULL stdio, and it cannot hold the listening socket. For uninstall the empty `$3` correctly skips bootstrap. A helper that fails leaves the plist present but not loaded, and launchd loads it again at the next login. The UI's 60 s message names `make service-install`.
- **svc_status:** never raises, makes no launchctl call off darwin, and returns `port` as an int.
- **sched_\*:** unchanged. The schedule.py diff only adds code, plus the docstring and `import time`.
- **Rename:** complete for every button, for the "Turned off (you unscheduled it)" text, in README l.291, and in tests (test_update_settings_ui, test_pending_web_gaps, test_pending_web_contract).
- **serviceBlock buttons per state:** not installed and installable gives Install. Installed and installable gives Reinstall and Uninstall. Installed but not installable gives Uninstall only. An unsupported platform, or a busy or deferred block, shows no buttons.
- **JS load safety:** `serviceBlock` is a function declaration with no top-level code, and `node --check` passes. `crCall` never rejects (`.catch` maps to `{ok:false}`), so the restart-gap poll cannot die on a failed fetch.
- **Tests:** `unset TRACKER_AUTH; python3 -m unittest tests.test_service tests.test_update_settings_ui tests.test_pending_web_gaps tests.test_pending_web_contract tests.test_pending_schedule` ran 89 tests, OK.
- **Red-proofs re-run by this reviewer:**
  1. `AUTH` dropped from the `_svc_env` regex makes `PlistTest.test_service_plist_contents` go RED ("Items in the first set but not the second").
  2. The pid regex broken (`pidX`) makes `StatusTest.test_status_parses_launchctl` go RED (`(None,…) != (4242,…)`). The implementation log had no revert run for this one.
  Both edits were restored, and test_service is back to 19 tests OK.

---

## M1 [MEDIUM] Install or Reinstall from a dashboard terminal served by the service leaves the service booted out until the next login

- **Defect:** schedule.py:312-322. The CLI path (`config.SERVICE` is False in the CLI process) runs `bootout` and then `bootstrap` synchronously. cli.py:49-50 calls it for `--install-service`/`--reinstall-service`, and so do `make service-install`/`make service-reinstall`.
- **Repro:** the service serves :8790, and the user opens a dashboard terminal (a pty child of the service) and runs `make service-reinstall`.
  - **What happens:** `launchctl bootout` SIGTERMs the service. Its shutdown closes the pty masters, and term_vt.py:1583-1600 sends SIGHUP and then SIGKILL to the terminal's group. The CLI python dies inside `subprocess.run(bootout)` and never reaches `bootstrap`. The plist is on disk but the job is unloaded, so there is no dashboard until the next login, and the terminal simply vanishes.
  - **Expected:** the service comes back with the new plist.
  - This is a realistic path, because the dashboard is where this user runs their terminals. Uninstall is unaffected: the plist is removed first and the bootout is the desired end state.
- **Direction:** a process that runs inside the service's tree must hand bootout and bootstrap to the detached helper, exactly as the service itself does. Do NOT change the synchronous path for a process outside the tree (Terminal.app, a shell server's route), and keep the return-code contract `0/1/2/3`.
- **Way:**
  - `server.run()`: in service mode, add `os.environ["AITRACKER_SERVICE_PID"] = str(os.getpid())`. Dashboard terminals inherit it. The `AITRACKER_` prefix is not `TRACKER_`, so it is never baked into the plist.
  - `schedule.py`: add `def _in_service(): return config.SERVICE or bool(os.environ.get("AITRACKER_SERVICE_PID"))`, and use it in place of `config.SERVICE` at schedule.py:312 and :337.
  - `cli.py:49-52`: on `rc == 3`, call `svc_spawn_deferred(reinstall=<not uninstall>)`, print "handed to a detached helper; the service restarts in a few seconds", then exit 0.
  - Do not use `signal(SIGHUP, SIG_IGN)` instead: term_vt SIGKILLs the group.
- **Test:** in `tests/test_service.py::InstallTest`, add `test_defers_inside_service_tree`. With `os.environ["AITRACKER_SERVICE_PID"]="1"` and `config.SERVICE=False`, assert that `svc_install(8790,"127.0.0.1",run=r)` returns 3, that `r.calls == []`, and that the plist exists. Add a CliTest asserting `--reinstall-service` with rc 3 calls `svc_spawn_deferred(True)`. Both are RED today: svc_install returns 0 and makes two launchctl calls.

## M2 [MEDIUM] The live proof cannot catch TCC: the real checkout is under `~/Documents`, the proof clone is not

- **Defect:** schedule.py:271 bakes `WorkingDirectory=_root()` and `PYTHONPATH=_root()`. On this machine that is `/Users/…/Documents/Projects/AIengg/ai-tracker`. A launchd agent's responsible process is the python binary itself, and on Catalina and later, reading `~/Documents` (or Desktop or Downloads) from a launchd job is TCC-gated. It either shows a "python3 would like to access files in your Documents folder" prompt, which is easy to miss at login, or fails with `Operation not permitted`. Clean plan step 7 runs the proof in `~/aitracker-svc-proof`, which is not protected, so the proof passes while the real install could crash-loop every `ThrottleInterval`. R10 only covered terminals cd'ing into `~/Documents`, not the checkout itself living there.
- **Repro:** cannot be shown by a unit test, which is the point. Install from the primary checkout and deny or miss the prompt. The log fills with `PermissionError: [Errno 1] Operation not permitted` / `can't open file`, and the status reads "Installed, not running · last exit 1".
- **Direction:** prove it on the real shape, and document it. Do NOT add a refusal for `~/Documents`: granting access is a legitimate fix, and refusing would block this user's only checkout.
- **Way:**
  1. Clean plan step 7: put the proof clone at `~/Documents/aitracker-svc-proof`, and add a check that the first launch either serves or prompts, recording which.
  2. README "Background service": add one line. If the checkout is under Documents, Desktop or Downloads, macOS asks once to let python3 access that folder. If you missed the prompt, grant it in System Settings › Privacy & Security › Files and Folders (or Full Disk Access) for `<python path from service-status>`, then Reinstall.
  3. Optional, but cheap: in `svc_status`, when `loaded and last_exit not in (None, 0)` and `root` is under `~/Documents|Desktop|Downloads`, set `st["hint"]`. The UI pushes `st.hint` as one extra line in `lines()`.
- **Test:** if (3) lands, add a `StatusTest` where `_root` sits under `HOME/Documents/x`, the print output has `last exit code = 1`, and the assertion is `"Files and Folders" in st["hint"]`. It is RED before (3). Items (1) and (2) are proof and documentation.

## L1 [LOW] `svc_install` truncates the live plist before serializing; an unencodable env value leaves a 0-byte plist and raises

- **Defect:** schedule.py:309-310 runs `with open(path,"wb") as f: f.write(service_plist(...))`. The open truncates first. plistlib raises `ValueError` ("strings can't contain control characters") for `\x01-\x1f` other than tab and newline, and `UnicodeEncodeError` for surrogate-escaped non-UTF-8 env bytes. Both were verified in python3.
- **Repro:** `export TRACKER_X=$'\e[0m'; make service-reinstall`.
  - **Actual:** a traceback, and `~/Library/LaunchAgents/com.aitracker.server.plist` is 0 bytes. The loaded job keeps running, but the next login loads nothing. `svc_status` reports `installed:false`, because `_read_svc_plist` swallows the parse error. From the route, the error is an unhandled exception.
  - **Expected:** a carried value that cannot be encoded is skipped, and the old plist is never truncated.
- **Direction:** serialize before opening, and drop values plistlib cannot encode. Do NOT change which keys are carried.
- **Way:**
  - In `svc_install`: `data = service_plist(port, host)`, then `open(...,"wb").write(data)`.
  - In `_svc_env`, add `and _plist_safe(v)` to the comprehension, where `_plist_safe(v)` is `not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", v)` and `v.encode("utf-8")` succeeds (try/except UnicodeEncodeError).
- **Test:** add `PlistTest.test_unencodable_env_value_skipped`. With env `{"TRACKER_X": "a\x1b[0m", "TRACKER_TERM_APP": "iTerm", "PATH": "/bin"}`, `service_plist` loads and `TRACKER_X` is not in it. Also call `svc_install` over an existing plist and assert the file is still parseable. RED today (ValueError).

## L2 [LOW] An ephemeral interpreter is baked without a refusal

- **Defect:** `_svc_refusal` (schedule.py:283-296) checks `_root()` but not `sys.executable`. An install from `uvx`, `uv run --isolated` or a worktree venv bakes a python under `~/.cache/uv/…`, `/var/folders/…` or `…/.claude/worktrees/…`. When that is garbage-collected, the job crash-loops. `svc_status` only reports `python_exists:false` after the fact.
- **Repro:** set `sys.executable="/var/folders/x/T/uv/bin/python3"` and call `svc_install`. Actual: 0. Expected: 2 with a reason.
- **Direction:** refuse a temp or worktree interpreter, using the same predicates as the root check. Do NOT refuse a venv in general (`~/.local/share/uv/tools/...` is stable).
- **Way:** in `_svc_refusal`, after the root checks, add `exe = os.path.realpath(sys.executable)` and `if _is_temp(exe) or "/.claude/worktrees/" in exe or "/.cache/uv/" in exe: return "python %s is temporary; install with a stable interpreter (python3 -m aitracker --install-service)" % sys.executable`.
- **Test:** add a case to `InstallTest.test_install_refusals`: `mock.patch.object(schedule.sys, "executable", "/x/.cache/uv/archive/bin/python3")` makes `why()`. RED today.

## L3 [LOW] `launchctl print` parsing is tested only against a synthetic 3-line fixture

- **Defect:** schedule.py:390-394 uses unanchored `\bpid = `, `\bstate = ([\w ]+)` and `last exit code =`. Real `launchctl print` output has `inherited environment`, `environment` and `endpoints` sub-blocks and many other `x = y` lines. `\bpid` would also match a `<word> pid = N` line. `StatusTest.OUT` has never been compared with a real capture.
- **Repro:** none on synthetic data. The risk is on real output, which this reviewer may not capture (no launchctl).
- **Direction:** anchor every key to its own top-level line. Do NOT change the returned shape.
- **Way:** call `re.search(rx, out, re.M)` with `r"^\s*pid = (\d+)\s*$"`, `r"^\s*state = (.+?)\s*$"` and `r"^\s*last exit code = (-?\d+)"`. During live-proof step 1, save one `launchctl print gui/$UID/com.aitracker.server` (environment lines redacted) as the `StatusTest.OUT` fixture.
- **Test:** add a `StatusTest` fixture line `\tparent pid = 1\n` *before* `\tpid = 4242`, and assert `pid == 4242`. RED today, because the unanchored `\bpid` takes the first match, which is 1.

## L4 [LOW] The UI cannot uninstall a job that is loaded but has no plist

- **Defect:** ext_cr_dialogs.js:1335-1341 shows Uninstall only when `st.installed`, which means the plist exists. After a deferred uninstall whose helper died, or a hand-deleted plist, the job is still loaded and running. The status reads "Not installed. Install runs…" with an Install button, the running service is never mentioned, and Uninstall is unreachable from the UI.
- **Repro:** `_svc(installed=False, loaded=True, pid=5)`. Actual: buttons `["Install"]` and the "Not installed" text. Expected: the text says it is running with no plist, and Uninstall is offered.
- **Direction:** `loaded` alone is enough to offer Uninstall (`svc_uninstall` boots out whether or not the plist exists). Do NOT change the not-loaded, not-installed path.
- **Way:** in `lines()`, before the `!st.installed` branch, add `if (!st.installed && st.loaded) out.push('Running (pid ' + st.pid + ') but its plist is gone');`. In `paint()`, use `if (st.installed || st.loaded) {…Uninstall…}` and keep Reinstall gated on `st.installed && st.can_install` (or offer Install). The server already returns `loaded`.
- **Test:** in `BackgroundServiceBlock.test_states`, add `r = self.go(_svc(loaded=True, pid=5))` and assert that `"Uninstall"` is in the buttons and `"plist is gone"` is in the text. RED today. Also add the currently missing assertion for `installed=True, can_install=False`: the buttons are exactly `["Uninstall"]`.

## L5 [LOW] `SHELL` is not carried, while dashboard terminals use `os.environ.get("SHELL", "/bin/bash")`

- **Defect:** schedule.py:262 carries only `LANG/LC_ALL/LC_CTYPE`. term_vt.py:3230 falls back to `/bin/bash -l` when `SHELL` is absent. launchd's per-user default environment normally includes SHELL, but that is unverified here and lives outside the plist's control. If it is absent, a zsh user gets bash without their zsh rc, which means a different PATH, pyenv and aliases, and Resume can break.
- **Direction:** carry `SHELL`, which is non-secret and harmless. Nothing else changes.
- **Way:** `k in ("LANG", "LC_ALL", "LC_CTYPE", "SHELL")`.
- **Test:** add `"SHELL": "/bin/zsh"` to the env in `test_service_plist_contents`, and add `"SHELL"` to the expected key set. RED today.

## L6 [LOW, docs] The README's "within about 8 s" ignores ThrottleInterval, and frozen `TRACKER_*` values are undocumented

- **Defect:** README l.76. A service process that ran for less than 30 s is respawned only after `30 - runtime` s. An example is a service that lost the port during its 3 s grace and exited 75 (the "a starting shell server wins" path). If the shell server stops in that window, takeover takes about 30 s, not 8. Separately, the `TRACKER_*` values are frozen at install time. Reinstall pressed in the *service's own* UI re-bakes the service's own env, so a newly exported value is picked up only by `make service-reinstall` from a non-dashboard shell.
- **Direction:** wording only.
- **Way:** in README l.76, change "within about 8 s" to "within about 8 s (up to about 30 s right after the service itself restarted: launchd throttles respawns)". Add a bullet: "`TRACKER_*`/LANG are copied when you install. To change one, export it in a Terminal and run `make service-reinstall` (Reinstall in the service's own page re-uses the service's settings)."
- **Test:** none (docs).

## L7 [LOW, optional] The scheduler status text still says "Installed"/"Not installed" next to Schedule and Unschedule

- **Defect:** ext_cr_dialogs.js:1165 and :1170. D1 renamed the buttons, and the plan renamed only l.1169. The block now reads "Not installed [Schedule]", while the Server tab's block uses Install for a different job.
- **Direction:** this is optional and outside D1's literal scope, so the user decides. If accepted, the status nouns follow the verbs. API actions and the opt-out file stay as they are.
- **Way:** `'Scheduled (' + kind + ')'…` and `'Not scheduled'`. Update the test_update_settings_ui `ScheduledScanBlock` assertions ("Installed (launchd) ·", "Not installed") and test_pending_web_contract l.~264.
- **Test:** the updated assertions are RED before the JS edit.

## I1 [INFO, cross-scope for reviewer A] CLI reinstall ignores the baked port (R5 was fixed only in the route)

cli.py:47-50 passes `int(os.environ.get("PORT", 8790))` to `svc_install` for `--reinstall-service`. `make service-reinstall` therefore silently moves a service installed on :8799 back to the Makefile's PORT. Direction: for `--reinstall-service` only, use `svc_baked() or (port, host)`, mirroring server.py:690. Test: a CliTest with a baked 8799 and no PORT asserts `svc_install(8799, …)`.

## I2 [INFO, no change] The detached helper's survival is still unproven

The code is correct by construction (setsid, so the helper is outside the killed process group). The real proof is live-proof step 5, with `AbandonProcessGroup: true` as the documented fallback. Keep it in the PR as the named riskiest spot.
