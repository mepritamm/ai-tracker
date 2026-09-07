"""Tests for aitracker.term_vt.resolve_spawned() -- the function that latches a session-less
`cwd`/`new` terminal onto the Claude session it later creates.

An adversarial review found this function had ZERO coverage: every existing test in
tests/test_term_vt.py still passes with resolve_spawned()'s entire body deleted. Two real
defects were found and fixed there (a phase-3 re-derivation to close a double-latch race, and a
narrow fork-guard) -- nothing previously locked either fix in. This file exists to do that.

Every test stubs `aitracker.providers.claude.newest_session_in_cwd` (monkeypatched module
attribute, restored in tearDown) so no real filesystem/session data is needed, and uses `pid=0`
placeholder Ptys (see tests/test_term_vt.py's own convention) so nothing real is spawned.
"""
import threading
import unittest

from aitracker import term_vt
from aitracker.providers import claude as claude_provider


class TestResolveSpawned(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._orig_probe = claude_provider.newest_session_in_cwd

    def tearDown(self):
        claude_provider.newest_session_in_cwd = self._orig_probe
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    # ---------------------------------------------------------------- 1. the point of the file

    def test_no_double_latch_under_concurrency(self):
        """THE POINT OF THIS FILE -- the race the adversarial review reproduced.

        Two live 'cwd' terminals share a cwd. Both threads' probes are made to block until
        BOTH are genuinely inside phase 2 (lock released) at once, and both are told the SAME
        newly-created session id. If the phase-3 claim were a plain check-then-act against a
        stale snapshot (the bug that was fixed), both threads could see 'not yet claimed' and
        both would store it -- two rows wearing the same session name forever. The fix
        re-derives ownership from live PTYS inside a fresh, per-hit `with _LOCK:` immediately
        before the store, so exactly one must win.
        """
        pt1 = term_vt.Pty(tid="p1", pid=0, cwd="/tmp/race")
        pt1.mode = "cwd"
        pt2 = term_vt.Pty(tid="p2", pid=0, cwd="/tmp/race")
        pt2.mode = "cwd"
        term_vt.PTYS["p1"] = pt1
        term_vt.PTYS["p2"] = pt2

        enter_count = [0]
        enter_lock = threading.Lock()
        both_in = threading.Event()

        def stub(cwd, after_ts, exclude=()):
            with enter_lock:
                enter_count[0] += 1
                if enter_count[0] >= 2:
                    both_in.set()
            # Block here until a second call has also entered -- proves both threads were
            # inside the probe (lock released) at the same time, not serialized one-at-a-time.
            if not both_in.wait(timeout=5):
                raise AssertionError("second probe call never arrived -- not concurrent")
            return "SID-RACE"

        claude_provider.newest_session_in_cwd = stub

        errors = []

        def run():
            try:
                # throttle=0 so BOTH threads' phase-1 scans select BOTH candidates regardless
                # of which one stamped spawn_probe first -- what forces genuine overlap in
                # phase 2 rather than one call's throttle silently starving the other.
                term_vt.resolve_spawned(throttle=0)
            except Exception as exc:      # pragma: no cover - surfaced via `errors`
                errors.append(exc)

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertFalse(t1.is_alive() or t2.is_alive(), "a thread deadlocked")
        self.assertFalse(errors, "resolve_spawned must never raise: %r" % (errors,))
        self.assertEqual(
            sorted([pt1.spawned, pt2.spawned]), ["", "SID-RACE"],
            "exactly one pty must latch the session; the other must stay unclaimed")

    # ---------------------------------------------------------------- 2. lock ordering

    def test_lock_is_released_during_the_probe(self):
        """Guards the lock-ordering discipline the docstring exists to protect: the probe
        (filesystem I/O) must run with `_LOCK` released, or every other terminal route
        (open/close/resize) would stall behind someone else's directory glob."""
        pt = term_vt.Pty(tid="p1", pid=0, cwd="/tmp/lockcheck")
        pt.mode = "cwd"
        term_vt.PTYS["p1"] = pt

        observed = []

        def stub(cwd, after_ts, exclude=()):
            observed.append(term_vt._LOCK.locked())
            return ""

        claude_provider.newest_session_in_cwd = stub
        term_vt.resolve_spawned()

        self.assertEqual(observed, [False])

    # ---------------------------------------------------------------- 3. throttle

    def test_throttle_prevents_a_second_probe_of_the_same_pty(self):
        pt = term_vt.Pty(tid="p1", pid=0, cwd="/tmp/throttle")
        pt.mode = "cwd"
        term_vt.PTYS["p1"] = pt

        calls = []

        def stub(cwd, after_ts, exclude=()):
            calls.append(cwd)
            return ""

        claude_provider.newest_session_in_cwd = stub
        term_vt.resolve_spawned()
        term_vt.resolve_spawned()

        self.assertEqual(len(calls), 1, "the second call must not re-probe within the throttle")

    # ---------------------------------------------------------------- 4. fork guard

    def test_fork_guard_is_narrow_to_the_forked_cwd_only(self):
        """A cwd holding a live forked pty must be skipped entirely (not even probe-stamped),
        but the guard must not blanket-disable resolution for an unrelated cwd."""
        forked = term_vt.Pty(tid="forked", pid=0, cwd="/tmp/X")
        forked.mode = "resume"
        forked.forked = True
        guarded = term_vt.Pty(tid="guarded", pid=0, cwd="/tmp/X")
        guarded.mode = "cwd"
        elsewhere = term_vt.Pty(tid="elsewhere", pid=0, cwd="/tmp/Y")
        elsewhere.mode = "cwd"
        term_vt.PTYS["forked"] = forked
        term_vt.PTYS["guarded"] = guarded
        term_vt.PTYS["elsewhere"] = elsewhere

        probed_cwds = []

        def stub(cwd, after_ts, exclude=()):
            probed_cwds.append(cwd)
            return "SID-Y" if cwd == "/tmp/Y" else "SID-X"

        claude_provider.newest_session_in_cwd = stub
        term_vt.resolve_spawned()

        self.assertNotIn("/tmp/X", probed_cwds, "the forked cwd must never be probed")
        self.assertEqual(guarded.spawned, "", "the forked cwd's sibling must not be latched")
        self.assertEqual(guarded.spawn_probe, 0.0, "the guard must skip BEFORE stamping")

        self.assertIn("/tmp/Y", probed_cwds, "an unrelated cwd must still be probed")
        self.assertEqual(elsewhere.spawned, "SID-Y", "the guard must not be a blanket disable")

    # ---------------------------------------------------------------- 5. never raises

    def test_probe_exception_never_propagates(self):
        pt = term_vt.Pty(tid="p1", pid=0, cwd="/tmp/boom")
        pt.mode = "cwd"
        term_vt.PTYS["p1"] = pt

        def stub(cwd, after_ts, exclude=()):
            raise RuntimeError("boom")

        claude_provider.newest_session_in_cwd = stub
        term_vt.resolve_spawned()  # must not raise

        self.assertEqual(pt.spawned, "")

    # ---------------------------------------------------------------- 6. ordinary case

    def test_ordinary_case_latches_and_live_list_reports_it(self):
        pt = term_vt.Pty(tid="p1", pid=0, cwd="/tmp/ordinary")
        pt.mode = "cwd"
        term_vt.PTYS["p1"] = pt

        def stub(cwd, after_ts, exclude=()):
            return "S-ORDINARY"

        claude_provider.newest_session_in_cwd = stub
        term_vt.resolve_spawned()

        self.assertEqual(pt.spawned, "S-ORDINARY")

        rows = {row["tty"]: row for row in term_vt._live_list()}
        self.assertEqual(rows["p1"]["session"], "S-ORDINARY")
        self.assertEqual(rows["p1"]["suffix"], "-terminal",
                          "the launch-mode suffix must not change when a session is resolved")


if __name__ == "__main__":
    unittest.main()
