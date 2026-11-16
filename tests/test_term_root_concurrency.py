"""L2c of terminal-at-root: K sessions of one repo opening/resuming at once never hold each other up.
Counts are asserted (one shared root shell + K-1 dedicated terminals, each in its own worktree, none bare
at the root), never which handler wins. Fake spawns sleep 0.5 s; `term_vt._LOCK` is instrumented so a
spawn moved under it fails the hold-time bound. Run: unset TRACKER_AUTH first."""
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from tests.test_open_pty_at_root import _Base, _H, contextlib_stack

K = 4
SIDS = ["S%d" % i for i in range(K)]


class _TimedLock:
    """Drop-in for term_vt._LOCK recording the longest hold."""

    def __init__(self):
        self._l = threading.Lock()
        self._t = threading.local()
        self.max_hold = 0.0

    def acquire(self, *a, **k):
        ok = self._l.acquire(*a, **k)
        if ok:
            self._t.t0 = time.monotonic()
        return ok

    def release(self):
        held = time.monotonic() - self._t.t0
        self.max_hold = max(self.max_hold, held)
        self._l.release()

    __enter__ = acquire

    def __exit__(self, *a):
        self.release()


class _Conc(_Base):
    SPAWN_DELAY = 0.5

    def setUp(self):
        super().setUp()
        self.tops = [self.top, self.top2] + [self.worktree("w%d" % i) for i in range(3, K + 1)]
        self.runs.update(dict(zip(SIDS, self.tops)))
        self._max0, self._slots0, self._lock0 = config.MAX_TERMS, term_vt._SLOTS_RESERVED, term_vt._LOCK
        self.addCleanup(self._restore)
        term_vt._FOLDER_SPAWNING.clear()
        self.lock = term_vt._LOCK = _TimedLock()
        self.spawns, self._sl = [], threading.Lock()
        self.waits = []
        p = mock.patch.object(term_vt, "_folder_settled", return_value=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(term_vt, "spawn", side_effect=self.fake_spawn)
        p.start()
        self.addCleanup(p.stop)
        real_wait = threading.Event.wait
        me = self

        def wait(ev, timeout=None):
            if any(ev is r for r in list(term_vt._FOLDER_SPAWNING.values())):
                me.waits.append(threading.current_thread().name)
            return real_wait(ev, timeout)
        p = mock.patch.object(threading.Event, "wait", wait)
        p.start()
        self.addCleanup(p.stop)

    def _restore(self):
        term_vt._LOCK = self._lock0
        config.MAX_TERMS = self._max0
        term_vt._SLOTS_RESERVED = self._slots0
        term_vt._FOLDER_SPAWNING.clear()

    def fake_spawn(self, cwd, argv, cols, rows):
        time.sleep(self.SPAWN_DELAY)
        with self._sl:
            n = len(self.spawns) + 1
            self.spawns.append((cwd, list(argv)))
        pt = term_vt.Pty(tid="sp%d" % n, pid=1000 + n, fd=100 + n, cwd=cwd)
        pt.cmd = " ".join(argv)
        return pt

    def burst(self, sids, mode, typed):
        """Open every sid at once on a barrier; returns [(body, code, seconds)]."""
        bar, out = threading.Barrier(len(sids)), []

        def one(sid):
            h = _H()
            bar.wait(10)
            t0 = time.monotonic()
            term_vt.open_pty(h, None, {"session": sid, "mode": mode, "cols": 80, "rows": 24})
            out.append((h.calls[-1][0], h.calls[-1][1], time.monotonic() - t0))

        with contextlib_stack(self.patches(typed)):
            ts = [threading.Thread(target=one, args=(s,), name="opener-" + s) for s in sids]
            for t in ts:
                t.start()
            for t in ts:
                t.join(20)
        self.assertEqual(len(out), len(sids), "an opener never returned")
        return out

    def check_common(self, out):
        for obj, code, secs in out:
            self.assertEqual(code, 200, obj)
            self.assertLess(secs, 2.0, "an opener was held up")
        self.assertLess(self.lock.max_hold, 0.2, "_LOCK held across a spawn")
        with term_vt._LOCK:
            self.assertLessEqual(term_vt._live_count(), config.MAX_TERMS)

    def no_bare_root(self, typed):
        """Every claude spawn runs at its own top; every typed claude line cd's to a top."""
        for cwd, argv in self.spawns:
            if argv and argv[0] == "claude":
                self.assertIn(cwd, self.tops, (cwd, argv))
                self.assertNotEqual(cwd, self.root)
        for line in typed:
            if b"claude" in line:
                self.assertIn(b'cd "$0"', line)


class TestWarmBurst(_Conc):
    def test_k_simultaneous_resumes_warm(self):
        fp = self.folder_pty()                              # settled, idle root shell
        typed = []
        out = self.burst(SIDS, "resume", typed)
        self.check_common(out)
        lines = [t for t in typed if b"claude" in t]
        self.assertEqual(len(lines), 1, typed)              # exactly one shared root shell line
        self.assertEqual(len(self.spawns), K - 1, self.spawns)   # K-1 dedicated, no extra root shell
        self.assertTrue(all(a[0] == "claude" for _, a in self.spawns))
        self.assertEqual(len({c for c, _ in self.spawns}), K - 1)
        self.assertTrue(all(c in self.tops for c, _ in self.spawns))
        ttys = [o["tty"] for o, _, _ in out]
        self.assertEqual(ttys.count(fp.id), 1, ttys)
        self.assertEqual(len(set(ttys)), K)
        self.no_bare_root(typed)

    def test_k_simultaneous_open_terminal_share_root(self):
        fp = self.folder_pty()
        typed = []
        out = self.burst(SIDS, "cwd", typed)
        self.check_common(out)
        self.assertEqual({o["tty"] for o, _, _ in out}, {fp.id})
        self.assertEqual(self.spawns, [])


class TestColdBurst(_Conc):
    def test_k_simultaneous_resumes_cold(self):
        typed = []
        out = self.burst(SIDS, "resume", typed)
        self.check_common(out)
        ded = [s for s in self.spawns if s[1][0] == "claude"]
        shells = [s for s in self.spawns if s[1][0] != "claude"]
        self.assertEqual(len(ded), K, self.spawns)
        self.assertEqual(sorted(c for c, _ in ded), sorted(self.tops))
        self.assertLessEqual(len(shells), 1, shells)
        self.assertTrue(all(c == self.root for c, _ in shells))
        self.assertEqual(typed, [])
        self.assertEqual(self.waits, [], "an opener waited on the reservation")
        self.assertEqual(len({o["tty"] for o, _, _ in out}), K)
        self.no_bare_root(typed)

    def test_cold_burst_never_exceeds_cap(self):
        config.MAX_TERMS = 4
        for i in range(2):
            term_vt.PTYS["fill%d" % i] = term_vt.Pty(tid="fill%d" % i, pid=0)
        bar, out = threading.Barrier(K), []

        def one(sid):
            h = _H()
            bar.wait(10)
            term_vt.open_pty(h, None, {"session": sid, "mode": "resume", "cols": 80, "rows": 24})
            out.append(h.calls[-1][1])

        with contextlib_stack(self.patches([])):
            ts = [threading.Thread(target=one, args=(s,)) for s in SIDS]
            for t in ts:
                t.start()
            for t in ts:
                t.join(20)
        with term_vt._LOCK:
            self.assertLessEqual(term_vt._live_count(), 4)
        self.assertEqual(len(out), K)
        self.assertTrue(1 <= out.count(200) <= 2, out)       # only the 2 free slots can be used
        self.assertEqual(out.count(200) + out.count(429), K, out)
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)
        self.assertLess(self.lock.max_hold, 0.2)


class TestGuards(_Conc):
    def test_waiter_bounded_by_spawn(self):
        """cwd-mode openers of a cold root shell DO wait, but only for the one spawn."""
        t0 = time.monotonic()
        out = self.burst(SIDS, "cwd", [])
        self.assertLess(time.monotonic() - t0, 2.5)
        self.check_common(out)
        self.assertEqual(len(self.spawns), 1, self.spawns)
        self.assertEqual(len({o["tty"] for o, _, _ in out}), 1)

    def test_same_session_twice_one_tty(self):
        typed = []
        o1 = self.burst(["S0"], "resume", typed)[0][0]
        o2 = self.burst(["S0"], "resume", typed)[0][0]
        self.assertEqual(o1["tty"], o2["tty"])
        self.assertEqual(len([s for s in self.spawns if s[1][0] == "claude"]), 1)

    def test_hold_time_instrument_catches_spawn_under_lock(self):
        """The bound can fail: a spawn made while holding _LOCK exceeds the 0.2 s limit."""
        with term_vt._LOCK:
            self.fake_spawn(self.root, ["claude"], 80, 24)
        self.assertGreaterEqual(self.lock.max_hold, 0.2)


if __name__ == "__main__":
    unittest.main()
