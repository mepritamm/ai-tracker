# Adversarial review — `followup-fixes` (personal/main f07f1e4 + uncommitted)

Scope: `aitracker/gateway.py`, `tests/test_claude_auth_status.py`, `tests/test_agent_cache.py`,
`tests/test_folder_terminal.py`, `tests/test_term_vt.py`. Read-only review; no tests, servers or make run.
Probes: one idle `claude auth status --json` (keys and exit code only), plus two pure in-process probes of
`claude_auth_status` with `_auth_run` stubbed, run against both the branch and base `gateway.py`.

Counts: **1 blocker, 2 should-fix, 4 nits** (plus 1 no-change note).

---

## Verdict on the inferred cause

**Plausible, but not proven and not the only explanation.** The run itself is fast: one idle run took
0.93 s, exited 0, and printed pure JSON (`loggedIn`/`authMethod`/`subscriptionType` present). So
"couldn't read" means `_auth_run` returned `None`. Five different failures all produce that one string:

| `_auth_run` → None path | gateway.py | Produces the observed string? |
|---|---|---|
| `communicate` TimeoutExpired (the inferred cause) | 117–129 | yes |
| any other exception from `communicate` (e.g. decode error) | 130–131 | yes. Locale is ruled out here: bare-env python3 3.9.6 is UTF-8 mode |
| stdout not JSON (banner, empty stdout, CLI error on stderr only) | 132–135 | yes |
| JSON but not a dict | 136 | yes |
| lock-acquire timeout | 146–147 | **no**: different string ("…is busy — try again"), so it was not mislabelled |
| stale cached failure (base cached a failure for 60 s for non-fresh callers; Settings' first load is `load(false)`) | 151–153, ext_cr_dialogs.js:1481 | yes. The error the user saw may come from a failure up to 60 s **earlier** |

The measured mechanism is a lab proxy that does not match production. The tracker never runs 16
`auth status` processes at once, because `_AUTH_LOCK` allows one per server (two at most if 8787 and 8790
both run). Real contention more likely comes from many `claude` processes starting together. The
tracker's own Agent Upgrade does exactly that: it restarts every Claude session onto a newly installed
binary (`agent_cli.py:3-4`), and the first launch of a new macOS binary can be slow on its own. Both
remain "slow CLI", so the 40 s timeout covers them. A parse-path cause is **not excluded**, because the
error string cannot tell the cases apart (S1). No alternate `claude` binary exists on common PATH dirs,
and a missing one would show "not found" anyway, so a wrong-binary cause is unlikely.

---

## B1 — blocker: failed reads now skip the fresh floor and single-flight

- **Defect:** `gateway.py:177`
  `_AUTH_CACHE.update(at=time.monotonic() - (AUTH_TTL - AUTH_FRESH_FLOOR if failed else 0), ...)`
  backdates a failed entry so its age starts at 55 s. The guard at `:151`,
  `age < AUTH_FRESH_FLOOR or (not fresh and age < AUTH_TTL)`, then fails at once for every `fresh=True`
  caller. A failure is held 5 s only for **non-fresh** callers. For fresh callers it is held 0 s, which
  breaks the docstring's "`fresh` re-runs only when the cache is >= AUTH_FRESH_FLOOR s old" and the
  single-flight property behind `test_concurrent_callers_one_run`.
- **Repro (probe, `_auth_run` stubbed to return None):**
  - fresh, then fresh at +0.5 s, then non-fresh at +1 s, then fresh at +1.5 s: branch **3 runs**, base 1 run.
  - 6 concurrent `fresh=True` callers: branch **6 serial runs**, base 1 run.

  Live, every window focus calls `load(true)` (`ext_cr_dialogs.js:1475-1479`, whose comment says "the
  server floors the rate"). With the keychain slow, each focus starts another CLI run of up to 45 s.
  That adds load to the contention the fix targets. Queued callers past 50 s get "busy", because
  `acquire(timeout=50)` sits behind serial 45 s runs.
- **Fix direction:** keep the short life for failures, but count it forward from now, with no backdating.
  The floor must still apply to every cached value. Do NOT change the success path, the TTL, the timeout
  or the lock.
- **Way:** store the entry's own TTL.
  ```python
  _AUTH_CACHE = {"at": 0.0, "val": None, "ttl": AUTH_TTL}
  ...
  if _AUTH_CACHE["val"] is not None and (age < AUTH_FRESH_FLOOR or (not fresh and age < _AUTH_CACHE["ttl"])):
  ...
  _AUTH_CACHE.update(at=time.monotonic(), val=res, ttl=AUTH_FRESH_FLOOR if failed else AUTH_TTL)
  ```
  In `tests/test_claude_auth_status.py` `Base.setUp`, change the reset to
  `_AUTH_CACHE.update(at=0.0, val=None, ttl=gateway.AUTH_TTL)`.
- **Test (red on the branch, green after):** in `CacheTests`
  ```python
  def test_failed_read_keeps_floor_and_single_flight(self):
      FakePopen.out = "not json"
      gateway.claude_auth_status(fresh=True)
      self.now[0] += 1
      gateway.claude_auth_status(fresh=True)
      self.assertEqual(self.calls(), 1)                  # branch: 2
      self.now[0] += gateway.AUTH_FRESH_FLOOR + 1
      FakePopen.out = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
      self.assertTrue(gateway.claude_auth_status()["logged_in"])   # failure expired after the floor
  ```
  Optionally add a failing-CLI variant of `test_concurrent_callers_one_run` (`FakePopen.out = "not json"`,
  expect `calls() == 1`). The new `test_timeout_failure_is_not_cached_for_the_full_ttl` stays green under
  the fix (age 6 > ttl 5).

## S1 — should-fix: one error string for timeout and unreadable output, so the cause cannot be checked

- **Defect:** `gateway.py:162-163`. A timeout (`:129`) and bad output (`:132-136`) both become
  "couldn't read claude auth status". The fix is built on an inferred cause that was never reproduced. If
  it happens again, the UI cannot show whether the 40 s timeout fired or the output failed to parse. The
  comment at `gateway.py:92` also states the inferred cause as fact. A smaller mismatch: the `_auth_run`
  docstring says "-> parsed dict or None", but the function also returns `False`.
- **Repro:** set `FakePopen.timeouts = 1`, then `FakePopen.out = "not json"`. Both produce the same `error`.
- **Fix direction:** give a timeout its own message. Do NOT put any CLI stdout/stderr in it (privacy
  invariant, `test_non_json_and_list`), and keep "couldn't read claude auth status" for the parse paths.
- **Way:** in `_auth_run`, return the sentinel `"timeout"` from the TimeoutExpired branch (`:129`). In
  `claude_auth_status`, add
  `elif d == "timeout": res = _auth_result(error="claude auth status timed out after %d s" % AUTH_STATUS_TIMEOUT)`
  before the `d is None` branch. `failed = not isinstance(d, dict)` already covers it. Reword `:92` to
  "inferred: …", and update the docstring.
- **Test:** in `test_timeout_kills_group_and_bounded_wait`, after the first call, add
  `self.assertIn("timed out", r["error"])`. It is red today. `test_non_json_and_list` still asserts
  "couldn't read".

## S2 — should-fix: U8a's deadline moved from t0+9 to t0+30, so it no longer checks the window is LIVE_WINDOW

- **Defect:** `tests/test_term_vt.py:6414`. In the test, LIVE_WINDOW is 5 s and the recheck is patched to
  0.2 s, so the correct reap lands around t0+5…7. The new deadline lets the window grow to about 25 s
  (5× LIVE_WINDOW) and still pass. Regressions such as `window = 2*LIVE_WINDOW` (reap about t0+11) or a
  hard-coded 10-20 s window now go green; the old t0+9 caught them. The deadline also lands exactly on the
  product default `SESSION_LIVE_RECHECK = 30.0` (`term_vt.py:1261`). If the test's recheck patch ever stops
  applying, the first hold (at t0+0.06…1, plus 30 s) misses the deadline by only 0.06-1 s, so the test
  catches it by luck, not by design. The wait is a poll, so it costs wall time only on failure.
- **Fix direction:** keep enough slack for load, stay well under 2× and 3× the window, and stay clearly
  below the 30 s default recheck. Prove the window boundary itself without a wall clock. Do NOT touch the
  `assertFalse` at t0+3.
- **Way:** set the deadline to `t0 + 15`, and add a comment that it must stay well below
  SESSION_LIVE_RECHECK's default. Also add a deterministic `_session_live` boundary test in
  `TestIdleSessionLive` (`term_vt.py:4388` computes `window = max(config.LIVE_WINDOW, TTL*60)` at `:4406`):
  ```python
  def test_U8c_session_live_boundary_is_live_window(self):
      self._fg(); config.LIVE_WINDOW = 5; config.TERM_IDLE_TTL_MIN = 0.001
      self._write(age=4.5); pt = self._pty(); config.TERM_IDLE_TTL_MIN = 0.001
      self.assertTrue(term_vt._session_live(pt, time.time()))
      self._write(age=5.5)
      self.assertFalse(term_vt._session_live(pt, time.time()))
  ```
  The `_pty()` TTL reset matters because `_pty` sets the TTL to 30 min. This is red under a `2*LIVE_WINDOW`
  mutation.
- **Test that proves it:** mutate `:4406` to `2 * config.LIVE_WINDOW`. U8c goes red, and U8a at t0+15 goes
  red. On the branch, U8a at t0+30 stays green.

## N1 — nit: one slow read replaces a known-good login with an error

- `gateway.py:177` overwrites the cached good value with a failure. After a good read, the next slow
  refresh (cache expired after 60 s) flips "Logged in" to an error. A logout is a *successful* read
  (`loggedIn:false`), so keeping the last good value on a **transient** failure cannot hide a real logout.
- Way: `if failed and prev and not prev.get("error"): res = prev` (cache it with the short ttl so it is
  re-probed soon). This does not help a cold cache: an in-app Update `execv` (`update.py:366`) clears it,
  so the 40 s timeout is still needed. Test: a good read, then a timeout after the TTL; expect `logged_in`
  True. Optional.

## N2 — nit: `test_slow_real_cli_under_load_still_reads` only pins the constant

- `tests/test_claude_auth_status.py:139-153`: the stub raises when `timeout < 25`, so the test amounts to
  `assertGreaterEqual(AUTH_STATUS_TIMEOUT, 25)`. It is red before the change (15 < 25), which is valid, but
  "REAL shape … measured" overstates what it shows: it models nothing about the keychain, and the
  16-concurrent figure is not a production pattern. Direction: keep it, and reword the comment to "guards
  the timeout floor". No code change.

## N3 — nit: U2 drain 5 s → 30 s

- `tests/test_term_vt.py:6329`: the expected reap is under about 1.2 s (TTL 0.06 s, 1 s select tick). The
  30 s bound only checks "not held forever", which matches the message, and it is a poll (no added time on
  success). Suggest 15 s, again to stay clear of the 30 s default recheck. Low value.

## N4 — nit: pinning the clock in `test_cold_equals_warm_including_hb` drops a guard nobody named

- `tests/test_agent_cache.py:206-216`: the pin itself is correct. `dur_s`, `running` and `state` are
  computed per call from `now` (`claude.py:1528-1603`, "never cached"), so a second-boundary rounding of
  `dur_s` was a genuine test flake, not a product race. But no test now checks that time-derived fields
  stay out of the cache: under a frozen clock, a cached `dur_s` equals the recomputed one. Before the pin
  that was only caught by chance, so nothing real is lost.
- Way: add a companion test. Under a frozen clock, read cold at T, set `frozen.time.return_value = T + 7`,
  read warm, and compare with a `AITRACKER_NO_AGENT_CACHE=1` read at T+7: `assertEqual(warm7, nocache7)`.
  It goes red if a time-derived field moves into `_agent_file_pass`.

## No-change note

- **In-app restart and Ctrl-C do not wait on the run.** `Server.daemon_threads = True`
  (`server.py:980`), and restart is an `execv` (`update.py:366`). A running `auth status` child has its own
  session, so it is orphaned and runs to completion; it was never bounded by the tracker. This predates the
  branch and the 40 s timeout does not change it.
- **Lock bound.** Acquire waits 40+10 = 50 s and the worst-case hold is 40 + 5 (post-kill communicate),
  so 45 s. A single waiter never gets "busy"; only queues behind serial runs do, which is B1.
- **Settings while waiting.** The block shows "Loading…" (`ext_cr_dialogs.js:1445`) for up to 45 s with no
  client timeout. That is acceptable.
- **`test_folder_terminal.py:746-754`.** The pidfile is written by the **test's own** fixture script
  (`_FOLDER_SHELL_SCRIPT`: `open("w")` then `write`), not product code, so no product race is hidden. The
  poll adds time only on failure. Fine.
- **`test_term_vt.py:2341`.** Waiting 30 s for the first draw does not weaken the check. The busy-hold
  assertions that follow (`sleep(6)`, `assertFalse(done)`, `last_hold == "busy"`) are unchanged, and a
  reaper that kills the pty early still goes red. It is a poll. Fine.

## Not examined

- Did not run `make check` or any test. The red-before and green-after statements for the new tests come
  from reading the code plus the pure probes.
- Did not reproduce keychain contention or the 8 s / 21-26 s timings (that would load the user's keychain).
  Did not check whether `auth status` refreshes OAuth over the network (a slow-VPN cause), or whether it
  ever prints a non-JSON banner such as an update notice.
- Did not review `tests/test_claude_auth_route.py`, the Windows path, the `_claude()` fixture in
  test_term_vt, or whether the agent_cache fixture has `open_start` set (relevant to N4's exact assertion).
- Did not open the live Settings UI.

---

## Fix list

1. **B1 (blocker):** `gateway.py:93,151,177`: per-entry `ttl` (FLOOR for failures, TTL for successes), `at=now`;
   reset `ttl` in the test `setUp`; add `test_failed_read_keeps_floor_and_single_flight` (red now: 2 runs).
2. **S1 (should-fix):** `_auth_run` returns `"timeout"` on TimeoutExpired; new "timed out after N s" error
   with no CLI output; reword the `:92` comment and the `_auth_run` docstring; assert "timed out" in
   `test_timeout_kills_group_and_bounded_wait`.
3. **S2 (should-fix):** `test_term_vt.py:6414` deadline to `t0 + 15` with a "below SESSION_LIVE_RECHECK" comment;
   add the deterministic `test_U8c_session_live_boundary_is_live_window`.
4. N1 (optional): keep the last good value on a transient failure.
5. N2: reword the comment on `test_slow_real_cli_under_load_still_reads`.
6. N3: U2 drain to 15 s.
7. N4: companion test where warm at T+7 equals no-cache at T+7.

## Main-thread verdicts (2026-11-16)

- B1 (blocker): CONFIRMED, fixed as designed: per-entry `ttl` (success AUTH_TTL, failure AUTH_FRESH_FLOOR), `at=now`, no back-dating; test `test_failed_read_keeps_floor_and_single_flight` and a 6-caller concurrent test (red before, green after).
- S1 (should-fix): CONFIRMED, fixed: timeout returns its own "claude auth status timed out after N s" (no CLI output); parse failures keep "couldn't read"; comment and docstring reworded.
- S2 (should-fix): CONFIRMED, fixed: U8a deadline t0+30 -> t0+15, plus `test_U8c_session_live_boundary_is_live_window` (red under a `2*LIVE_WINDOW` mutation).
- N1: CONFIRMED, applied: a transient failure keeps the last good logged-in value (re-probed after the floor).
- N2: CONFIRMED, applied: comment reworded to "guards the timeout floor".
- N3: CONFIRMED, applied: U2 drain 30 -> 15 s.
- N4: CONFIRMED, applied: `test_time_derived_fields_not_cached` (warm at T+7 equals no-cache at T+7).
- Inferred cause: plausible, unproven; the distinct timeout message (SF) makes the next occurrence diagnosable.
