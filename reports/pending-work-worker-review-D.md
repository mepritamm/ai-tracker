# Adversarial review D — Plan addendum A (C8 auto-install, C9 in-app Update)

Reviewer D (opus), 2026-11-15. Scope: "## Plan addendum A (to v3.1)" in `reports/pending-work-worker.md`. I did not re-review v3.1.
Method: grep plus `sed` ranges on the worktree code. I ran one scratch probe (`~/.claude/jobs/8b05c822/tmp/revD_exec_probe.py`, Python 3.12.3, macOS). It did `pty.fork()`, listened on a socket, started a thread, and called `os.execv` from that thread. Output:
`stage1 ... pty master fd 4 inheritable: True sock inheritable: False` / `stage2 rebound ok ... fds [0, 1, 2, 3, 4, 5]`.
No tests, servers or launchctl were run, and no repo file except this one was touched.

Counts: **1 blocker, 8 should-fix, 6 nit.**

---

## F1 — BLOCKER: terminals do NOT close at exec. Their Claude processes are orphaned and keep running unseen.

**Defect.** Addendum B step 2 says: "`os.execv` closes the server's non-inheritable PTY master fds (PEP 446), so in-browser terminals ... get SIGHUP". The "Not grounded" section repeats the claim. It is false.
- `pty.fork()`, used at `term_vt.py:1656` and `term_run.py:361`, returns an **inheritable** master. The probe printed `inheritable: True`, and fd 4 was still open in the exec'd image.
- After `restart_in_place`, every terminal's master survives into the new process. Nothing there knows about it or reads it.
- Repro: open a Claude terminal, then Update and restart with `confirm_terminals: true`.
  - Actual: the `claude` child keeps running, possibly mid-agentic-task and still executing tools, with no UI. It hangs once the pty buffer fills. The new dashboard shows 0 terminals.
  - Expected (and what the confirm dialog promises): the terminals close.
- Also, `_term_count()` (`server.py:94`) counts only `term_vt` PTYs. `term_run.JOBS` (`term_run.py:161`, also pty-backed) is never counted in the confirm.

**Fix direction.** Make every fd ≥3 close-on-exec right before `execv`. The kernel then closes the masters and the children get the hangup. Do NOT close the fds before exec: if exec fails, the server must still be intact (see F4). Do NOT edit `term_vt._fork_child` or `term_run.spawn` in this change.

**The way.**
- In `update.py`, add `_cloexec_all()`:
  ```python
  for fd in os.listdir("/dev/fd") (fallback range(3, os.sysconf("SC_OPEN_MAX"))):
      int(fd) >= 3 and try: os.set_inheritable(int(fd), False) except OSError: pass
  ```
- Call it in `restart_in_place` immediately before `execv`.
- For the confirm, compute the count in `update_apply` as `term_vt._live_count() + term_run._live_count()`, each looked up via `sys.modules.get(...)` and treated as 0 when absent.
  - Pass that sum from the route.
  - Leave `_term_count()`, which feeds the badge, unchanged.
- Known gap, not fixed here (document in §10): terminal B's child inherits terminal A's master across its own `execvp`. So closing A alone never hangs it up. `term_vt` masks this by using `killpg`. It is a separate ticket.

**Test** (`tests/test_update.py`):
1. `pid, fd = pty.fork()` with the child running `sleep 30`. Call `_cloexec_all()`, then assert `os.get_inheritable(fd) is False`. This is red without the helper.
2. In a subprocess script: pty.fork, then `_cloexec_all()`, then `os.execv(python, ["-c", "import os;print(os.listdir('/dev/fd'))"])`. Assert the master fd number is absent.
3. In the apply test, set `term_run._live_count` to 1 and `term_vt` to 0. Assert `needs_confirm`.

---

## F2 — should-fix: a scan or clean can start during apply and be cut off mid-delete by the exec

**Defect.**
- `can_update` checks `pending._RUNNING.is_set()` once, in rule 7. That event is in-process only (`pending.py:31`, set at :822).
- After the check, apply runs fetch (≤60s) and pre-flight (≤90s), then sleeps 0.5s and calls exec.
- `_worker_loop` → `tick()` → `run_once()` can start in that window. In Safe-delete mode, the exec then interrupts `git worktree remove` (`pending.py:707`) or `shutil.rmtree` (`:765`) halfway. That leaves a half-deleted worktree with its admin entry still present, or a partly-removed tmp dir.
- Two concurrent applies (double-click, two tabs, or a re-post after `needs_confirm` while the first is in flight) both pass the checks and both get 202.

**Fix direction.**
- Use the existing cross-process per-user flock as the guard, and keep holding it until exec.
- Add a single-flight lock for apply.
- Do NOT add a new lock file. Do NOT edit `pending.py`.

**The way.**
- In `update_apply`, first take `_APPLY = threading.Lock()` with `acquire(blocking=False)`. If it is busy, return `409 {"error": "update already in progress"}`.
- Then enter `cm = pending._pending_lock(); got = cm.__enter__()` (`pending.py:98`). If `got` is false, return `409 "scan in progress"`.
- On every failure path, call `cm.__exit__(None, None, None)` and release `_APPLY`.
- On success, keep both held. The flock fd is opened with O_CLOEXEC, so the exec releases it.
- Status keeps `_RUNNING` for display only.

**Test:**
- With the test holding `pending._pending_lock()`, `update_apply` returns 409 and HEAD is unchanged.
- While apply holds it (patch `restart_in_place` to block), `pending.run_once()` returns `{"running": True}`.
- A second concurrent `update_apply` returns 409.
- Red-proof: remove the acquire and the merge happens.

---

## F3 — should-fix: the pre-flighted commit is not necessarily the merged commit

**Defect.**
- Step 3 archives `@{u}` and step 4 merges `@{u}`. Each resolves the ref separately.
- In between there is up to 90s of pre-flight. A Check for updates from another tab, or the user's own `git fetch` in a terminal, can move `personal/main`.
- Actual: an un-pre-flighted commit is merged. Expected: exactly the tested sha is merged.

**Fix direction.** Resolve the target once and use that sha everywhere.

**The way.** After `update_fetch()`:
1. `target = _g("rev-parse", "@{u}")`.
2. Run `git archive --format=tar <target>`.
3. Then `merge --ff-only <target>`.

The 202 body's `to` is `target`, and D6's text names "the fetched, pre-flighted sha".

**Test.** The fixture pushes commit X and fetches. A patched pre-flight hook then pushes Y and fetches again. Assert HEAD == X after apply.

---

## F4 — should-fix: the exec-failure path leaves a half-state with the tunnel stopped and a misleading page

**Defect.**
- `restart_in_place` runs `tunnel.stop(keep_on=True)` and then `os.execv`. The plan does not handle exec raising. Three ways it can:
  - `sys.executable` is gone after `brew upgrade python`;
  - ENOEXEC;
  - `sys.orig_argv` is **3.10+** while `pyproject.toml:9` says `requires-python = ">=3.8"`, so it raises AttributeError.
- If it raises, the thread dies quietly, and the process keeps serving **old Python with new web files**. `build_page()` re-reads `web/*` from disk on every `/` request (`page.py:11–24`, `server.py:371`), so the "baked at startup" premise in §B is wrong.
- The tunnel stays off. After 60s the page says "did not come back", but the server is up.
- Buffered stdout is lost at exec: the probe's stage-1 print vanished until it was re-run with `-u`.

**Fix direction.** Keep the server whole on exec failure and report the error. Do NOT `os._exit` on failure.

**The way.**
- Build argv as `getattr(sys, "orig_argv", None)`, falling back to `[sys.executable, "-m", "aitracker", *sys.argv[1:]]`.
- Before exec:
  1. `sys.stdout.flush(); sys.stderr.flush()`;
  2. `print(recovery_line, flush=True)` (see F12);
  3. `_cloexec_all()` (F1);
  4. `execv`.
- `except OSError as e:`
  - call `tunnel.autostart(port, config.BIND_HOST)`;
  - set `_RESTART_ERROR = str(e)`;
  - release the F2 locks.
- `update_status()` gains `restart_error`. The page shows it as soon as it is non-null, instead of waiting out the 60s.

**Test:**
- Patch `os.execv` to raise OSError. Assert `tunnel.autostart` was called and `update_status()["restart_error"]` is set.
- Patch `sys` so it has no `orig_argv`. Assert the argv fallback is used.

---

## F5 — should-fix: an SSH fetch can prompt in the `make serve` terminal and leave an orphan `ssh`

**Defect.**
- `GIT_TERMINAL_PROMPT=0` only stops git's own credential prompt.
- `ssh` reads passphrase and host-key answers from **`/dev/tty`**, not stdin, so `stdin=DEVNULL` does not help.
- The server runs in the foreground of the user's terminal (`Makefile serve:`), so ssh can grab that terminal.
- Repro: the `github-personal` key has a passphrase that is not in the agent, or a new host key appears.
  - Actual: "Enter passphrase…" appears in the server terminal, the request stalls 60s, and `subprocess.run(timeout)` kills only `git`. The `ssh` grandchild lives on, still reading the tty.
  - Expected: a clean "fetch failed: …" within the timeout and no leftover process.

**Fix direction.** Run update git calls with no controlling terminal and kill the whole process group on timeout.

**The way.**
- In `update._g`, use `subprocess.Popen([...], start_new_session=True, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=...)` and `communicate(timeout=...)`.
- On `TimeoutExpired`, `os.killpg(p.pid, SIGKILL)`, using the same pattern as `tunnel.py:211/264`.
- Optional, flagged as possibly wider than needed: add `GIT_SSH_COMMAND="ssh -o BatchMode=yes"` only when neither the env var nor `core.sshCommand` is set. `start_new_session` alone already makes `/dev/tty` unavailable.

**Test.**
- Point `GIT_SSH_COMMAND` at a fake ssh script that tries `open("/dev/tty")`, records the result, and then sleeps 30s. Use an `ssh://` fixture remote and patch `FETCH_TIMEOUT=2`.
- Assert the open failed (ENXIO) and the fake's pid is dead after `update_fetch()` returns.
- Red-proof: without `start_new_session` the pid survives.

---

## F6 — should-fix: DNS rebinding passes both gates, and the bundle fails open on origin

**Defect.**
- `_local_caller` (`server.py:219–229`) checks only the peer address and proxy headers.
- `_origin_ok` (`term_gate.py:47–55`) accepts any request where `Origin` netloc == `Host`.
- No route checks that Host is a loopback name; grep finds no Host allowlist.
- Repro: a page on `evil.example:8790` rebinds to 127.0.0.1 and POSTs `/api/update/apply {"confirm_terminals":true}`.
  - Actual: peer is 127.0.0.1, there are no proxy headers, Origin == Host, and auth is off by default. The result is 202: terminals are killed and the dashboard restarts. The attacker cannot choose the commit.
  - Expected: 403.
- Separately, the addendum's `if tg and not tg._origin_ok(self)` **skips** the origin check when `term_gate` is absent, as in the bundle. That leaves `/api/update/scheduler` with no origin check at all.

**Fix direction.**
- For the update POSTs only, require Host's hostname ∈ {`localhost`, `127.0.0.1`, `[::1]`} and fail closed when `term_gate` is absent.
- Do NOT change the `/api/term/*` routes in this PR. They have the same, larger gap; record it as a known gap and a follow-up ticket.

**The way.** In server.py, add a small `_update_gate(handler)` used by the update POSTs:
```python
ok, err = _local_caller(h)
host = urlparse("//" + h.headers.get("Host", "")).hostname
tg = sys.modules.get("aitracker.term_gate")
pass only if ok and host in {"localhost", "127.0.0.1", "::1"} and tg and tg._origin_ok(h)
```

**Test** (`test_update_routes.py`):
- `Host: evil.example:P` with a matching Origin → 403.
- `term_gate` popped from `sys.modules` (via patch) → 403.
- `Host: localhost:P` with no Origin → passes the gate.

---

## F7 — should-fix: AD3 (no rollback) is acceptable only if the pre-flight covers what `run()` does before `serve_forever`

**Defect.**
- The pre-flight imports only `aitracker.server` and `aitracker.cli`.
- `run()` also calls `config.apply_overrides(_load_json(config.CONFIG_FILE))` (`server.py:918`). New validators applied to the user's existing `config.json` can raise at startup.
- `/` calls `build_page()`, which opens `index.html`, `app.js`, `app.css` and every `ext_*`. A renamed or missing web file returns 500 on the reloaded page.
- A load-time JS throw in any `ext_*` (memory: "gate misses load-time JS errors") gives a blank page after reload. Because the Update UI lives in `ext_cr_dialogs.js`, there is then no UI and no recovery text.

**Fix direction.** Keep AD3: no automatic rollback, because a rollback would need `reset` or `checkout`, which D6 forbids. Strengthen the pre-flight, and put the recovery line somewhere that survives a broken page. Do NOT build a supervisor.

**The way.**
- Extend the pre-flight `-c` with:
  - `from aitracker import config, page; config.apply_overrides(json.load(open(sys.argv[2])) if sys.argv[2] else {}); page.build_page()`.
  - Pass the real `config.CONFIG_FILE` path, or `""` when it is absent, as argv[2].
- Print the recovery line to stdout before exec (F4).
- Add a README line with the same recovery command.
- Optional, flagged as possibly wider than needed: `node --check` each `web/*.js` when `shutil.which("node")` finds node.

**Test.**
- The fixture target commit has a `config.py` whose `apply_overrides` raises on the key `"X"`, and the real `config.json` contains `{"X":1}`. Expect 409 and HEAD unchanged.
- A second target commit deletes `web/app.css`. Expect 409.

---

## F8 — should-fix: guard 2 makes Part A's tests unreachable or vacuous

**Defect.**
- Inside `tests/test_scheduler_autoinstall.py`, `"unittest" in sys.modules` is always true.
- So every assertion for guards 3–8 (bundle, worktree, temp, marker, adopt, install rc 0/1, exception) returns `skipped:test`, unless the test deletes `unittest` from `sys.modules`, which is fragile.
- A5's "`run()` with interval off never calls install" passes because of the unittest guard, not the interval guard.

**Fix direction.** Keep the belt, but make it patchable.

**The way.**
- Add `def _under_test(): return "unittest" in sys.modules` in `schedule.py`.
- Guard 2 calls it.
- Tests patch it to False for every non-test guard case.

**Test.**
- A5: patch `_under_test`→False and `TRACKER_PENDING_INTERVAL=off`. Expect `skipped:test` and `sched_install` not called. Red-proof: remove the interval clause and install is called.
- A2: for each guard case, patch `_under_test`→False.

---

## F9 — should-fix (user decision): AD1/AD2 keep more state than the user's words need, and the Reinstall route exists only to cover AD2

**Defect.**
- R6 says first serve "should always generate the launchd job".
- The marker-as-"done once" design (guards 6–7, adopt-and-write, retry-once-on-failure) leaves two cases where it does not regenerate:
  - a hand-deleted plist is never regenerated;
  - a moved checkout leaves the job pointing at a dead path. That then needs a new Settings line, a **new POST route** `/api/update/scheduler` (more attack surface) and a Reinstall button.

**Fix direction.** Store only the opt-out, and install whenever the job is missing or broken.
- The marker holds only `{"opted_out": true}`. `--uninstall-scheduler` writes it and `--install-scheduler` removes it.
- On serve, after guards 1–5:
  - if opted out, skip;
  - else if `sched_status()["installed"] and root_exists`, skip;
  - else call `sched_install()`. `sched_install` already replaces a job pointing elsewhere (`schedule.py:98`). This auto-repoints a moved checkout to the checkout actually being served.
- Cut `POST /api/update/scheduler`, the Reinstall button and the scheduler line. If the user wants visibility, keep a read-only status line.
- Flag: this overrules the planner's AD1 and AD2 recommendations, so it is the user's call.

**The way.**
- Rewrite `autoinstall_once` in `schedule.py` along these lines.
- In A5, drop the scheduler route. In A6, drop the button.

**Test** (A2):
- no marker + not installed → install;
- opted out → skip;
- installed + `root_exists` False → install;
- installed + root present → skip, and `run` is called only for status.

---

## F10 — nit: the temp-root guard misses `/tmp`

**Defect.** Guard 5 compares against `tempfile.gettempdir()` and `/private/var/folders`. On macOS, a clone in `/tmp/x` has realpath `/private/tmp/x`, which neither covers.

**Fix.** Compare `realpath(_root())` against the realpaths of `gettempdir()`, `/tmp` and `/var/folders`.

**Test.** Patch `_root` to `/tmp/fake` and expect `skipped:temp`.

---

## F11 — nit (optional, touches app.js and server.py): only the tab that pressed Update reloads

**Defect.**
- Other open tabs keep stale JS talking to the new server.
- This is already true of any restart, but it cuts against R6's "doesn't have to refresh".

**Fix.**
- Add `headers["X-Server-Started"]` next to `X-Server-Now` at `server.py:398`. That goes in A5.
- At `app.js:1323`, reload when the value differs from the first one seen. That folds into A1's slot, after v3.1 step 12.

**Test.** A node test: two polls with different `X-Server-Started` values call `location.reload`.

---

## F12 — nit (overbuild): `update.json`, `TRACKER_RESTARTED` and the .gitignore entry

**Defect.**
- They exist only to hold recovery text, and the page already has that text from the 202 body.
- Their one other use is the "ok:true after bind" mark, which nothing reads.

**Fix.**
- Drop `UPDATE_FILE`, `TRACKER_RESTARTED`, the `run()` hook and the .gitignore line.
- Print one recovery line to stdout before exec (F4/F7).

**Test.** None needed. Remove the plan's `TRACKER_RESTARTED` assertion.

---

## F13 — nit: the Makefile claim (brief item 3)

**The planner is right.**
- `Makefile:9–10` is `serve: @PORT=$(PORT) python3 -m aitracker`. Commit `4165837` "serve: scan for a free port instead of killing whatever holds it" removed `serve: stop`.
- `CLAUDE.md:22` ("frees the port first") is stale.
- Consequence for this addendum: a second `make serve` starts a second server on 8791 rather than replacing the first. Both run `autoinstall_once`, which is harmless; F9 makes it idempotent. The restart relies on exec closing the socket, and the probe confirms that does happen (`sock inheritable: False`, rebind ok).

**Fix.**
- A4 corrects `CLAUDE.md:22` to "starts on PORT or the next free port; `make stop` first to replace a running one".
- Do not change the Makefile.

**Test.** Review only.

---

## F14 — nit: step sizing and file-disjointness (brief item 4)

**Disjointness holds as written:**
- A1 goes into v3.1 step 12 (`app.js`).
- A4 runs after step 6 (README, .gitignore, conventions).
- A5 runs after step 11 (`server.py`).
- A6 runs after step 14 (`ext_cr_dialogs.js`).
- A2 (`schedule.py`) and A3 (`update.py`) touch none of the files in steps 11–15 (`server.py`, `app.js`, `index.html`, `app.css`, `ext_cr_*`, `store.py`).
- F2 only *calls* `pending._pending_lock`, so `pending.py` is not edited.

**Sizing.** With F1–F7 in, A3 is too much for one sonnet leg. Split it, sequentially because both parts are the same file:
- **A3a** — `update_kind/_g/update_status/update_fetch/update_apply` with the F2/F3/F5/F7 guards.
- **A3b** — `restart_in_place`, `_cloexec_all` and the exec-failure path (F1/F4).

**Fixture.** A3's fixture remote must commit a **stub** `aitracker/` package: `__init__.py` with `__version__`, plus `server.py`, `cli.py`, `config.py` with `apply_overrides`, `page.py` with `build_page`, and `web/`. The pre-flight imports these from the archived tree; the real package would be slow and import the world.

**Test.** n/a.

---

## F15 — nit: behaviour that is fine as planned (no change; document it)

- **Worktree checkout / non-main branch.** Kind is `git`, and Update fast-forwards that branch to its own upstream. That is exactly `git pull` semantics.
- **Detached HEAD, dirty tree, no upstream, diverged.** All are refused with a server-owned reason.
- **uv/bundle install.** Shows the version and the reason, with no buttons.
- **Zombies.** SIGHUP'd children become zombies under the new image until it exits. This is harmless; document it.
- **Primary-checkout dirtiness.** I could not inspect the primary checkout; the sandbox refused `git -C`. If other sessions leave it dirty, Update will usually refuse. That is correct behaviour; README should say "commit or discard local edits first".

---

## D6 (third rule-6 exception)

It is **needed**: `git fetch` is outbound network. Narrow the wording to:

> *"Exception (in-app Update, user-requested R6): `aitracker/update.py` may run `git fetch --quiet --no-tags <remote> <branch>` for the running checkout's own upstream, only when a local caller (loopback peer, loopback Host name, same Origin, not tunnelled, not read-only) presses Check for updates or Update and restart. Remote and branch come from git config, never from the request. The fetch runs with no controlling terminal and a timeout that kills its process group. There is no scheduled or automatic fetch. The only write is `git merge --ff-only <sha>`, where `<sha>` is the commit fetched and import/startup pre-flighted in that same request. It never stashes, resets, checks out, forces or rebases. No other outbound network call is allowed."*

---

## Clean-plan deltas

1. **§B step 2 and "Not grounded" (F1).**
   - Replace the PEP-446 claim with: "`pty.fork` masters are inheritable (measured), so `_cloexec_all()` runs before `execv`."
   - The confirm count is `term_vt._live_count() + term_run._live_count()`.
   - Add a §10 gap: cross-terminal master inheritance.
2. **`update_apply` (F2).**
   - Step 0 takes `_APPLY` non-blocking, then `pending._pending_lock()`, and holds both until exec. Either busy → 409.
   - Remove `pending_running` from the apply-time checks; keep it in status for display.
3. **Steps 3–4 (F3).** Use `target = rev-parse @{u}` once, then `archive <target>`, then `merge --ff-only <target>`.
4. **`restart_in_place` (F4).**
   - argv via `getattr(sys, "orig_argv", None)` with a fallback.
   - Before exec: flush, print the recovery line, `_cloexec_all`.
   - On OSError: `tunnel.autostart`, set `restart_error`, release the locks.
   - `update_status` gains `restart_error`.
5. **`_g` (F5).** `Popen(start_new_session=True)`, with `killpg` on timeout.
6. **Routes (F6).** Add `_update_gate` (local + loopback Host + origin, failing closed when `term_gate` is absent). Record the term routes' DNS-rebinding gap as known.
7. **Pre-flight (F7).** Add `config.apply_overrides(<real config.json>)` and `page.build_page()`. Keep AD3 with that justification.
8. **Guard 2 (F8).** Use `_under_test()`, patchable.
9. **Part A (F9, user decision).** The marker holds only the opt-out. Install when the job is not installed or `root_exists` is false. Delete guards 6–7 adopt/retry, `POST /api/update/scheduler`, the Reinstall button and AD2.
10. **Guard 5 (F10).** Also cover `/tmp` via realpath.
11. **Optional (F11).** `X-Server-Started` header plus an app.js reload.
12. **Drop (F12).** `update.json`, `TRACKER_RESTARTED`, the `.gitignore` entry and the `run()` ok-marking.
13. **A4 (F13).** Fix the `CLAUDE.md:22` wording.
14. **Steps (F14).** Split A3 into A3a then A3b (sequential). The A3 fixture uses a stub `aitracker` package.
15. **D6.** Use the narrowed text above.
