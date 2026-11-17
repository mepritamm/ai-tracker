"""Terminal-resume regression: a Resume (or a double click / two tabs) of session S yields at most ONE
terminal running S and no shell beyond the one root shell hosting it. A cold Resume spawns the shared
root shell, claims it and types claude into it once it settles (the pre-S3 deferred path); /login stays
dedicated; slots are reserved atomically under `_LOCK` so a burst never overshoots MAX_TERMS; and
`_RESUME_SPAWNING` collapses two simultaneous openers of one session. Fake spawns throughout.
Run: unset TRACKER_AUTH first."""
import os
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from tests.test_open_pty_at_root import SHELL, _Base, _H, contextlib_stack


class _Budget(_Base):
    def setUp(self):
        super().setUp()
        self.top3 = self.worktree("w3")
        self.runs.update({"S": self.top, "T": self.top2, "U": self.top3})
        self.spawns = []
        self.delay = 0.0
        self.fail_spawn = False
        self._max0, self._slots0 = config.MAX_TERMS, term_vt._SLOTS_RESERVED
        self.addCleanup(self._restore)
        term_vt._FOLDER_SPAWNING.clear()
        term_vt._RESUME_SPAWNING.clear()
        p = mock.patch.object(term_vt, "_folder_settled", return_value=True)
        self.settle_mock = p.start()
        self.addCleanup(p.stop)
        sp = mock.patch.object(term_vt, "spawn", side_effect=self.fake_spawn)
        sp.start()
        self.addCleanup(sp.stop)
        self.shell_argv = [os.environ.get("SHELL", "/bin/bash"), "-l"]

    def _restore(self):
        config.MAX_TERMS = self._max0
        term_vt._SLOTS_RESERVED = self._slots0
        term_vt._FOLDER_SPAWNING.clear()
        term_vt._RESUME_SPAWNING.clear()

    def fake_spawn(self, cwd, argv, cols, rows, login=""):
        time.sleep(self.delay)
        if self.fail_spawn:
            raise OSError("boom")
        with term_vt._LOCK:
            n = len(self.spawns) + 1
            self.spawns.append((cwd, list(argv)))
        # a shell (`... -l`) is what the patched tcgetpgrp reports as the foreground group
        pt = term_vt.Pty(tid="sp%d" % n, pid=SHELL if argv[-1] == "-l" else 1000 + n, fd=100 + n, cwd=cwd)
        pt.login = login
        pt.cmd = " ".join(argv)
        return pt

    def go(self, sid, mode, typed=None, fg=SHELL, **extra):
        typed = [] if typed is None else typed
        with contextlib_stack(self.patches(typed, fg=fg)):
            obj, code = self.open(sid, mode, **extra)
            self.join_deferred()
            return obj, code

    def join_deferred(self):
        for pt in list(term_vt.PTYS.values()):
            if pt.deferred is not None:
                pt.deferred.join(5)

    def fill(self, n):
        for i in range(n):
            term_vt.PTYS["fill%d" % i] = term_vt.Pty(tid="fill%d" % i, pid=0)

    def live(self):
        with term_vt._LOCK:
            return term_vt._live_count()


class TestColdResume(_Budget):
    def test_cold_resume_one_root_shell_claimed(self):
        typed = []
        obj, code = self.go("S", "resume", typed)
        self.assertEqual(code, 200, obj)
        self.assertEqual(self.spawns, [(self.root, self.shell_argv)])
        fp = term_vt.PTYS[obj["tty"]]
        self.assertTrue(obj["folder"])
        self.assertTrue(fp.folder)
        self.assertEqual(fp.fg["session"], "S")
        self.assertIsNotNone(fp.deferred)
        self.assertFalse(fp.overflow)

    def test_cold_resume_types_claude_after_settle(self):
        typed = []
        self.go("S", "resume", typed)
        line = b"".join(typed)
        self.assertIn(b"--resume S", line)
        self.assertIn(b"sh -c 'cd \"$0\" && exec \"$@\"'", line)
        self.assertEqual(self.settle_mock.call_count, 1)

    def test_cold_new_types_launcher_into_root_shell(self):
        typed = []
        obj, code = self.go("S", "new", typed)
        self.assertEqual(code, 200, obj)
        self.assertEqual(self.spawns, [(self.root, self.shell_argv)])
        self.assertTrue(obj["folder"])
        self.assertIn(b" claude", b"".join(typed))

    def test_repeated_resume_same_session_adds_none(self):
        ttys = set()
        for _ in range(5):
            obj, code = self.go("S", "resume")
            self.assertEqual(code, 200, obj)
            ttys.add(obj["tty"])
        self.assertEqual(len(ttys), 1)
        self.assertEqual(self.live(), 1)
        self.assertEqual(len(self.spawns), 1)

    def test_three_sessions_twice_three_ptys(self):
        first = {s: self.go(s, "resume")[0]["tty"] for s in "STU"}
        second = {s: self.go(s, "resume")[0]["tty"] for s in "STU"}
        self.assertEqual(first, second)
        self.assertEqual(self.live(), 3)                  # 1 root + 2 overflow, never K+1
        self.assertEqual(len(self.spawns), 3)

    def test_resume_of_session_in_root_returns_same_tty(self):     # rewritten from the S3 dedicated test
        typed = []
        o1, _ = self.go("S", "resume", typed)
        o2, code = self.go("S", "resume", typed)
        self.assertEqual(code, 200, o2)
        self.assertEqual(o2["tty"], o1["tty"])
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(b"".join(typed).count(b"--resume S"), 1)    # claude typed once

    def test_settled_shell_with_foreground_job_goes_dedicated_nothing_typed(self):    # F7
        fp = self.folder_pty()
        fp.startup_done = True
        typed = []
        with mock.patch.object(term_vt, "_fg_pgid", return_value=SHELL + 1), \
                mock.patch.object(term_vt, "_inject_argv", side_effect=AssertionError("claimed the shell")):
            obj, code = self.go("S", "resume", typed)
        self.assertEqual(code, 200, obj)
        self.assertEqual(typed, [])
        self.assertEqual(self.spawns, [(self.top, ["claude", "--resume", "S"])])
        self.assertNotEqual(obj["tty"], fp.id)
        self.assertIsNone(fp.fg)

    def test_cwd_mode_cold_still_opens_shell(self):                      # guard: unchanged behaviour
        obj, code = self.go("", "cwd", cwd=self.root)
        self.assertEqual(code, 200, obj)
        self.assertEqual(len(self.spawns), 1)
        self.assertTrue(obj["folder"])

    def test_login_open_stays_dedicated(self):                           # RED on e6acfe7: /login no longer warms a root shell
        obj, code = self.go("S", "new", prompt=term_vt.LOGIN_PROMPT)
        self.assertEqual(code, 200, obj)
        self.assertEqual(len(self.spawns), 1)
        self.assertFalse(obj["folder"])
        self.assertTrue(term_vt.PTYS[obj["tty"]].overflow)


class TestConcurrent(_Budget):
    def _burst(self, sids, mode="resume", fg=SHELL):
        out = []

        def one(sid):
            h = _H()
            term_vt.open_pty(h, None, {"session": sid, "mode": mode, "cols": 80, "rows": 24})
            out.append(h.calls[-1])

        with contextlib_stack(self.patches([], fg=fg)):
            ts = [threading.Thread(target=one, args=(s,)) for s in sids]
            for t in ts:
                t.start()
            for t in ts:
                t.join(15)
            self.join_deferred()
        return out

    def test_concurrent_same_session_resume_one_spawn(self):
        self.delay = 0.3
        out = self._burst(["S", "S"])
        self.assertEqual([c for _, c in out], [200, 200], out)
        self.assertEqual(len(self.spawns), 1, self.spawns)
        self.assertEqual(len({o["tty"] for o, _ in out}), 1)

    def test_concurrent_same_session_busy_root_one_overflow(self):    # proves _RESUME_SPAWNING
        fp = self.folder_pty()
        fp.startup_done = True
        fp.fg = {"session": "OTHER", "mode": "resume", "started": 1e12, "grants": {"OTHER"}}
        fp.fg_seen_child = True
        self.delay = 0.3
        out = self._burst(["S", "S"], fg=SHELL + 1)
        self.assertEqual([c for _, c in out], [200, 200], out)
        self.assertEqual(len(self.spawns), 1, self.spawns)
        self.assertEqual(len({o["tty"] for o, _ in out}), 1)
        self.assertEqual(term_vt._RESUME_SPAWNING, {})

    def test_resume_reservation_released_on_error(self):
        self.fail_spawn = True
        obj, code = self.go("S", "resume")
        self.assertEqual(code, 500, obj)
        self.assertEqual(term_vt._RESUME_SPAWNING, {})
        self.assertEqual(term_vt._FOLDER_SPAWNING, {})

    def test_cold_burst_never_overshoots_cap(self):
        config.MAX_TERMS = 12
        self.fill(11)
        self.delay = 0.5
        out = self._burst(list("STU"))
        self.assertLessEqual(self.live(), 12)
        self.assertEqual(sorted(c for _, c in out), [200, 429, 429])
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)


class TestSlots(_Budget):
    def test_slots_back_to_baseline(self):                                # guard
        self.fail_spawn = True
        self.go("S", "resume")                                           # OSError on the root shell
        self.go("S", "new", prompt=term_vt.LOGIN_PROMPT)                 # OSError on a dedicated login
        self.fail_spawn = False
        config.MAX_TERMS = 1
        self.fill(1)
        _, code = self.go("S", "resume")                                 # 429
        self.assertEqual(code, 429)
        _, code = self.go("S", "new", prompt=term_vt.LOGIN_PROMPT)
        self.assertEqual(code, 429)
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)

    def test_429_only_at_real_cap(self):                                  # guard
        config.MAX_TERMS = 2
        o1, c1 = self.go("S", "resume")
        o2, c2 = self.go("T", "resume")                                  # busy root -> overflow, last slot
        o3, c3 = self.go("U", "resume")
        self.assertEqual((c1, c2, c3), (200, 200, 429), (o1, o2, o3))
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)

    def test_two_cwds_cold_one_slot_left(self):                          # RED without the folder-shell _slots_add
        other = os.path.realpath(os.path.join(self.tmp, "other"))
        os.makedirs(other)
        config.MAX_TERMS = 3
        self.fill(2)
        self.delay = 0.5
        codes = []

        def one(cwd):
            h = _H()
            term_vt.open_pty(h, None, {"session": "", "mode": "cwd", "cwd": cwd, "cols": 80, "rows": 24})
            codes.append(h.calls[-1][1])

        with contextlib_stack(self.patches([], fg=SHELL)):
            ts = [threading.Thread(target=one, args=(c,)) for c in (self.root, other)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(15)
            self.join_deferred()
        self.assertLessEqual(self.live(), 3)
        self.assertEqual(sorted(codes), [200, 429])
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)


if __name__ == "__main__":
    unittest.main()
