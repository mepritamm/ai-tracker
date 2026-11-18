"""accounts._Bg: non-blocking single-flight cache with a TTL, a refresh floor and a failure hold."""
import threading
import time
import unittest
from unittest import mock

from aitracker import accounts


class BgTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        p = mock.patch.object(accounts, "_acct_now", lambda: self.now[0])
        p.start()
        self.addCleanup(p.stop)
        self.calls = 0

    def mk(self, producer, ttl=300, floor=60):
        return accounts._Bg(ttl, floor, producer, {"state": "loading"})

    def settle(self, bg):
        if bg._th:
            bg._th.join(5)

    def ok(self):
        self.calls += 1
        return {"state": "ok", "n": self.calls}, True, 0.0

    def test_get_returns_at_once_with_refreshing(self):
        gate = threading.Event()

        def slow():
            gate.wait(5)
            return {"state": "ok"}, True, 0.0
        bg = self.mk(slow)
        t0 = time.time()
        first = bg.get()
        self.assertLess(time.time() - t0, 1)
        self.assertEqual((first["state"], first["refreshing"]), ("loading", True))
        gate.set()
        self.settle(bg)
        self.assertEqual(bg.get()["state"], "ok")

    def test_single_flight(self):
        gate = threading.Event()

        def slow():
            self.calls += 1
            gate.wait(5)
            return {"state": "ok"}, True, 0.0
        bg = self.mk(slow)
        for _ in range(5):
            bg.get()
        gate.set()
        self.settle(bg)
        self.assertEqual(self.calls, 1)

    def test_ttl_and_floor(self):
        bg = self.mk(self.ok)
        bg.get()
        self.settle(bg)
        self.now[0] += 30
        bg.get(fresh=True)                      # inside the floor: no run
        self.settle(bg)
        self.assertEqual(self.calls, 1)
        self.now[0] += 31                       # 61 s: fresh passes the floor
        bg.get(fresh=True)
        self.settle(bg)
        self.assertEqual(self.calls, 2)
        self.now[0] += 100                      # inside the ttl without fresh: no run
        bg.get()
        self.settle(bg)
        self.assertEqual(self.calls, 2)
        self.now[0] += 250
        bg.get()
        self.settle(bg)
        self.assertEqual(self.calls, 3)

    def test_failure_stamps_time_and_holds(self):
        def bad():
            self.calls += 1
            return {"state": "error", "error": "x"}, False, 60.0
        bg = self.mk(bad)
        bg.get()
        self.settle(bg)
        self.now[0] += 4
        bg.get()
        self.settle(bg)
        self.assertEqual(self.calls, 1)
        self.now[0] += 57                       # t=61
        bg.get()
        self.settle(bg)
        self.assertEqual(self.calls, 2)

    def test_fresh_never_overrides_the_hold(self):
        def bad():
            self.calls += 1
            return {"state": "error", "error": "x"}, False, 900.0
        bg = self.mk(bad)
        bg.get()
        self.settle(bg)
        self.now[0] += 100
        bg.get(fresh=True)
        self.settle(bg)
        self.assertEqual(self.calls, 1)

    def test_failure_keeps_the_good_body_as_stale(self):
        results = [({"state": "ok", "v": 1}, True, 0.0), ({"state": "error", "error": "boom"}, False, 60.0)]
        bg = self.mk(lambda: results.pop(0))
        bg.get()
        self.settle(bg)
        self.now[0] += 301
        bg.get()
        self.settle(bg)
        b = bg.get()
        self.assertEqual((b["state"], b["v"], b["stale"], b["error"]), ("ok", 1, True, "boom"))

    def test_invalidate_mid_run_drops_the_result(self):
        gate = threading.Event()

        def slow():
            self.calls += 1
            gate.wait(5)
            return {"state": "ok", "n": self.calls}, True, 0.0
        bg = self.mk(slow)
        bg.get()
        bg.invalidate()
        gate.set()
        self.settle(bg)
        self.assertEqual(bg.get()["state"], "loading")      # the stale result was dropped; a fresh run starts
        self.settle(bg)
        self.assertEqual(bg.get()["state"], "ok")

    def test_at_is_wall_clock(self):
        bg = self.mk(self.ok)
        bg.get()
        self.settle(bg)
        self.assertLess(abs(bg.get()["at"] - time.time()), 5)

    def test_producer_exception_is_a_fixed_error(self):
        def boom():
            raise RuntimeError("SECRET-detail")
        bg = self.mk(boom)
        bg.get()
        self.settle(bg)
        b = bg.get()
        self.assertEqual(b["error"], "internal error")
        self.assertNotIn("SECRET", repr(b))


if __name__ == "__main__":
    unittest.main()
