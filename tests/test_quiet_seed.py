"""L3 of terminal-at-root (S2): the quiet timer is seeded from the shell's last output."""
import time
import unittest
from unittest import mock

from aitracker import term_vt


def _pty():
    return term_vt.Pty(tid="t1", screen=term_vt.Screen(80, 24))


class TestQuietSeed(unittest.TestCase):
    def setUp(self):
        for name, val in (("INJECT_QUIET_WINDOW", 0.4), ("INJECT_MIN_WAIT", 0.05),
                          ("INJECT_POLL_INTERVAL", 0.01)):
            p = mock.patch.object(term_vt, name, val)
            p.start()
            self.addCleanup(p.stop)

    def _elapsed(self, quiet_since):
        pt = _pty()
        t = time.time()
        self.assertTrue(term_vt._wait_for_quiescence(pt, quiet_since=quiet_since))
        return time.time() - t

    def test_seeded_long_idle_returns_fast(self):
        self.assertLess(self._elapsed(time.time() - 10), 0.2)

    def test_unseeded_waits_full_window(self):
        self.assertGreaterEqual(self._elapsed(None), 0.4)

    def test_seeded_now_waits_full_window(self):
        self.assertGreaterEqual(self._elapsed(time.time()), 0.39)

    def test_inject_argv_seeds_from_last_output(self):
        pt = _pty()
        pt.last_output = 123.0
        with mock.patch.object(term_vt, "_wait_for_quiescence", return_value=False) as w:
            ok, _ = term_vt._inject_argv(pt, ["echo", "x"])
        self.assertFalse(ok)
        self.assertEqual(w.call_args.kwargs.get("quiet_since"), 123.0)


if __name__ == "__main__":
    unittest.main()
