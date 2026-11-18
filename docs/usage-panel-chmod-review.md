# Adversarial review: config.json chmod 600 on every server start (`470cc4b..d038030`)

Scope: 5d34ac5 (`store.secure_config_file()` + call at the top of `server.run()`) and d038030 (tests pinning
the Update-and-restart re-exec → `cli.main()` → `run()` → chmod). Spec: "Addendum (2026-11-19)" in
`docs/usage-panel-plan.md`. Reviewer stance: assume the report is false.

**Verdict: the claim holds.** Every path that ends with a serving process passes through `run()` →
`secure_config_file()`. No High or Medium findings. 0 High, 0 Medium, 1 Low, 2 Info, 3 Nit.

## Findings

### F1 (Low): a `make serve` whose service never reaches `run()` leaves config.json at its old mode
- **Defect.** On the macOS primary checkout, `make serve` runs `cli.main()` with `--serve` (`aitracker/cli.py:54-70`).
  That process only installs the LaunchAgent and exits. The chmod happens later, in the launchd child
  (`--service` → `cli.py:90` → `server.py:1210`). If `launchctl bootstrap` fails (`svc_install` returns 1,
  `cli.py:71-73`), or the child dies before `run()` (for example an import error in new code, with KeepAlive looping), then
  nothing ever runs `secure_config_file()`. The command the user actually typed never tightens the file.
- **Repro.** Leave `aitracker/config.json` at 0644. Patch `cli.svc_install` to return 1, then run `python3 -m aitracker --serve`.
  It exits 1, and the mode is still 0644 (expected 0600 under the literal ask "should happen when someone does make serve").
- **Why only Low.** When this happens nothing is serving, so nothing reads or writes the secrets. The exposure is exactly what it was
  before 5d34ac5, and the next successful start fixes it.
- **Fix direction.** Optional. Also tighten in the CLI install branches. Do NOT remove or move the `run()` call
  (`server.py:1210`), because it is the call that covers launchd respawn, Update-and-restart and foreground starts.
- **Way.** In `aitracker/cli.py`, import `secure_config_file` from `.store`. Call it once at the top of
  `if "--serve" in sys.argv:` (`cli.py:54`) and at the top of the `--install-service`/`--reinstall-service` branch
  (`cli.py:75`). It is idempotent and never raises on a missing file. Nothing else changes.
- **Red-first test.** `tests/test_save_json_mode.py::SecureConfigFileTests`: add `test_serve_install_failure_still_secures_config`.
  Use the `_reexec_secures` setup (0644 `self.p`, env patch, pop `AITRACKER_SERVICE_PID`) with argv `["aitracker","--serve"]`, and patch
  `cli.svc_baked` to return None, `cli._port_busy` to return False and `cli.svc_install` to return 1. Call `cli.main()` under
  `assertRaises(SystemExit)` and assert `_mode(self.p) == 0o600`. Today it fails with 420 != 384.

### F2 (Info): `os.chmod` follows a symlinked config.json
- **Observation.** I set `config.CONFIG_FILE` to a symlink pointing at a 0644 file and called `secure_config_file()`. The target became 0600.
  A dangling symlink is silently ignored (FileNotFoundError).
- **Why it is not a defect.** It only ever *tightens* a file the user owns. On a file the user does not own it fails with EPERM, which
  is caught. Planting a symlink in `aitracker/` requires write access to the code itself. The existing chmods already
  follow symlinks: `server.py:829`, `server.py:890` and `tunnel.py:61`.
- **Fix direction.** No change. Do **not** switch to `os.chmod(..., follow_symlinks=False)`. On Linux it raises
  `NotImplementedError`, which is not an `OSError`, so startup would crash.
- **Test.** None.

### F3 (Info, pre-existing, outside this range): the bundle's config file is `dist/json`
- **Observation.** `scripts/bundle.py:45` rewrites every `config.` that has no word or `.` character in front of it, including the one inside the
  string literal `"config.json"`. As a result `dist/tracker.py:249` is `CONFIG_FILE = os.path.join(_HERE, "json")`. The helper and every
  reader use the same name, so the bundle is self-consistent: it chmods the same file it reads. The comment and the warning text read
  "json" in the bundle. The bundled helper is present (`dist/tracker.py:2005` def, `:16475` call) and `sys` is in the bundle header.
- **Fix direction.** No change in this PR (the bug predates it, as `git show 470cc4b:aitracker/config.py:233` shows). If it is fixed separately:
  either make the regex skip string literals, or spell the literal in `config.py:233` as `"config" + ".json"`. Then add a bundle test that
  asserts `CONFIG_FILE.endswith("config.json")`.

### F4 (Nit): `test_server_run_calls_it_before_binding` mutates config globals without restoring them
- **Defect.** `tests/test_save_json_mode.py:80-88` calls `server.run(open_browser=False)`, which sets `config.BIND_HOST/BIND_PORT/SERVICE`
  (`server.py:1200-1202`). The two re-exec tests restore those with `patch.object` (`:94-97`); this test does not. It is harmless today
  because the values written equal the defaults (`config.py:157-161`). Under `--selfcheck` (a single process) a future default change would leak.
- **Fix direction / way.** Move the `for attr in ("BIND_HOST","BIND_PORT","SERVICE"): patch.object(...)` loop from `_reexec_secures` into
  `setUp`, so it covers all three tests. Do not change the assertions.
- **Test.** None needed (hygiene only).

### F5 (Nit): the warning can print `None` as the reason
- **Defect.** `aitracker/store.py:25` formats `e.strerror`, which is `None` for an `OSError` raised without an errno.
- **Fix direction / way.** Optional: use `{e.strerror or type(e).__name__}`. That keeps the message to the path plus a reason, and still never prints `str(e)` contents.
- **Test.** Optional: patch `os.chmod` with `side_effect=OSError("x")`, capture stderr, and assert `"None"` does not appear in it.

### F6 (Nit, docs): one stale line reference in the addendum
- `docs/usage-panel-plan.md` addendum cites `schedule.py:271` for the plist `ProgramArguments`. The actual line is `aitracker/schedule.py:269`.
  Fix: edit the reference. No test.

## Verified OK
- **Call site.** `secure_config_file()` is the first config action in `run()` (`server.py:1210`). It runs before `apply_overrides`, `bind`,
  `publish_endpoint`, `start_worker` and `tunnel.autostart`. Nothing in `cli.main()` or at import time writes config.json before it.
- **Every start path reaches `run()`:**
  - `make serve` on the primary checkout (`Makefile:10`) → `svc_install` writes the plist, runs bootout and then bootstrap every time (`schedule.py:320-333`) → plist argv
    `[python, -m, aitracker, --service]` (`schedule.py:269`) → `__main__.py` → `cli.main()` → `run()`.
  - The deferred rc-3 path (`svc_spawn_deferred`), the UI service reinstall, and `--install-service`/`--reinstall-service`: each launches the same `--service` child.
  - KeepAlive respawn uses the same argv.
  - `make serve` in a worktree or off macOS: `svc_install` returns 2, then falls through to `run()` (`cli.py:74,90`).
  - `make tunnel`: `python3 -m aitracker` → `run()`.
  - Update and restart: `restart_in_place` re-execs with `sys.orig_argv`, or falls back to `[python, -m, aitracker, *argv[1:]]` (`update.py:357,372`).
    The new code's `cli.main()` therefore runs, which covers the first upgrade that brings the helper in.
- **`--selfcheck`** is not a server start. Its tests patch `config.CONFIG_FILE` (`setUp`) or the helper itself, so a selfcheck never chmods the real file.
- **Late binding.** `store` imports the `config` module (`store.py:7`) and reads `config.CONFIG_FILE` at call time. There is no copied name, and the tests repoint it correctly.
- **No startup crash on odd errors (probed).** Missing file: silent. ENOTDIR: warning, no raise. EPERM on a root-owned file: warning, no raise.
  Pointing it at a directory chmods that directory, which is a nonsensical input and not reachable through the fixed `config.py:233` path.
- **The warning is path-only.** It prints `config.CONFIG_FILE` and `e.strerror`, never the file's contents.
- **The merge never touches config.json.** It is gitignored (`.gitignore:16`, confirmed with `git check-ignore -v aitracker/config.json`), so `merge --ff-only` neither writes it nor changes its mode.
- **Tests.** `unset TRACKER_AUTH; python3 -m unittest tests.test_save_json_mode`: 9/9 OK. The tests assert the real file mode, not a mock call, and they contain `os.environ` with `patch.dict`
  and pop `AITRACKER_SERVICE_PID` (so they are safe inside a dashboard terminal). The `--serve` test would also go red if the rc-2 fallthrough exited, because
  `SystemExit` is not the expected `RuntimeError`.
- **Red proof (re-run by the reviewer).** I replaced `server.py:1210` with `pass` and re-ran the module: 3 FAIL
  (`test_server_run_calls_it_before_binding` [] != ['chmod'], and both re-exec tests 420 != 384, that is 0644 vs 0600). I then restored the line exactly; `git diff` was empty.
