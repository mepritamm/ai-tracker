"""L5 of terminal-at-root (S3): a cold or warming root shell never makes a resume/new opener wait. It
gets a dedicated claude at its worktree at once, and the root shell warms beside it only when two
slots are free. Slots are reserved atomically under `_LOCK` (D6); a warm shell that never settles is
closed atomically (E4). Fake spawns throughout. Run: unset TRACKER_AUTH first."""
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from tests.test_open_pty_at_root import SHELL, _Base, _H, contextlib_stack


class _S3(_Base):
    FAKE_SETTLE = True

    def setUp(self):
        super().setUp()
        self.top3 = self.worktree("w3")
        self.runs.update({"S": self.top, "T": self.top2, "U": self.top3})
        self.spawns = []
        self.delay = 0.0
        self._max0, self._slots0 = config.MAX_TERMS, term_vt._SLOTS_RESERVED
        self.addCleanup(self._restore)
        term_vt._FOLDER_SPAWNING.clear()
        self.settle_mock = None
        if self.FAKE_SETTLE:
            p = mock.patch.object(term_vt, "_folder_settled", return_value=True)
            self.settle_mock = p.start()
            self.addCleanup(p.stop)
        sp = mock.patch.object(term_vt, "spawn", side_effect=self.fake_spawn)
        sp.start()
        self.addCleanup(sp.stop)

    def _restore(self):
        config.MAX_TERMS = self._max0
        term_vt._SLOTS_RESERVED = self._slots0
        term_vt._FOLDER_SPAWNING.clear()

    def fake_spawn(self, cwd, argv, cols, rows):
        time.sleep(self.delay)
        with term_vt._LOCK:
            n = len(self.spawns) + 1
            self.spawns.append((cwd, list(argv)))
        pt = term_vt.Pty(tid="sp%d" % n, pid=1000 + n, fd=100 + n, cwd=cwd)
        pt.cmd = " ".join(argv)
        return pt

    def go(self, sid, mode, typed=None, fg=SHELL, **extra):
        typed = [] if typed is None else typed
        with contextlib_stack(self.patches(typed, fg=fg)):
            return self.open(sid, mode, **extra)

    def fill(self, n):
        for i in range(n):
            term_vt.PTYS["fill%d" % i] = term_vt.Pty(tid="fill%d" % i, pid=0)


class TestColdOpen(_S3):
    def test_cold_resume_execs_claude_now_and_warms_root(self):
        obj, code = self.go("S", "resume")
        self.assertEqual(code, 200, obj)
        self.assertEqual(len(self.spawns), 2, self.spawns)
        (c0, a0), (c1, a1) = self.spawns
        self.assertEqual((c0, a0), (self.top, ["claude", "--resume", "S"]))
        self.assertEqual(c1, self.root)
        self.assertEqual(a1[-1], "-l")
        ded, shell = term_vt.PTYS["sp1"], term_vt.PTYS["sp2"]
        self.assertTrue(ded.overflow)
        self.assertFalse(ded.folder)
        self.assertTrue(shell.folder)
        self.assertIsNone(shell.fg)
        self.assertEqual(obj["tty"], "sp1")
        self.assertFalse(obj["folder"])
        for _ in range(100):                                # the watcher thread: settle only, no claim
            if self.settle_mock.call_count:
                break
            time.sleep(0.02)
        self.assertEqual(self.settle_mock.call_count, 1)
        self.assertIs(self.settle_mock.call_args[0][0], shell)
        self.assertTrue(self.settle_mock.call_args[0][2])
        self.assertEqual([t.name for t in threading.enumerate() if t.name.startswith("folder-start-")], [])

    def test_resume_during_warm_goes_dedicated_without_wait(self):
        fp = self.folder_pty()
        fp.startup_done = False
        typed = []
        with mock.patch.object(threading.Event, "wait", side_effect=AssertionError("waited")):
            obj, code = self.go("S", "resume", typed)
        self.assertEqual(code, 200, obj)
        self.assertEqual(self.spawns, [(self.top, ["claude", "--resume", "S"])])
        self.assertEqual(typed, [])
        self.assertIsNone(fp.fg)

    def test_resume_while_reserved_does_not_wait(self):
        ev = mock.Mock()
        ev.wait.side_effect = AssertionError("waited")
        term_vt._FOLDER_SPAWNING[self.root] = ev
        obj, code = self.go("S", "new")
        self.assertEqual(code, 200, obj)
        self.assertFalse(ev.wait.called)
        self.assertEqual([a for _, a in self.spawns], [["claude"]])     # reserved: no second warm shell

    def test_warm_skipped_at_cap(self):
        config.MAX_TERMS = 12
        self.fill(11)
        obj, code = self.go("S", "resume")
        self.assertEqual(code, 200, obj)
        self.assertEqual(self.spawns, [(self.top, ["claude", "--resume", "S"])])
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)

    def test_cold_burst_never_overshoots_cap(self):
        config.MAX_TERMS = 12
        self.fill(11)
        self.delay = 0.5
        out = []

        def one(sid):
            h = _H()
            term_vt.open_pty(h, None, {"session": sid, "mode": "resume", "cols": 80, "rows": 24})
            out.append(h.calls[-1][1])

        with contextlib_stack(self.patches([])):
            ts = [threading.Thread(target=one, args=(s,)) for s in "STU"]
            for t in ts:
                t.start()
            for t in ts:
                t.join(10)
        with term_vt._LOCK:
            live = term_vt._live_count()
        self.assertLessEqual(live, 12)
        self.assertEqual(sorted(out), [200, 429, 429])
        self.assertEqual(term_vt._SLOTS_RESERVED, self._slots0)

    def test_resume_of_session_in_dedicated_returns_same_tty(self):
        typed = []
        o1, _ = self.go("S", "resume", typed)
        self.assertFalse(o1["folder"])
        self.assertEqual(len(self.spawns), 2)
        term_vt.PTYS["sp2"].startup_done = True        # the warm shell has settled
        o2, code = self.go("S", "resume", typed)
        self.assertEqual(code, 200, o2)
        self.assertEqual(o2["tty"], o1["tty"])
        self.assertEqual(len(self.spawns), 2)
        self.assertEqual(typed, [])                    # nothing typed into the root shell

    def test_settled_warm_shell_is_reused(self):
        typed = []
        self.go("S", "resume", typed)
        term_vt.PTYS["sp2"].startup_done = True
        obj, code = self.go("T", "resume", typed, fg=1002)
        self.assertEqual(code, 200, obj)
        self.assertEqual((obj["tty"], obj["reused"], obj["folder"]), ("sp2", True, True))
        self.assertIn(b"sh -c 'cd \"$0\" && exec \"$@\"'", b"".join(typed))
        self.assertEqual(len(self.spawns), 2)

    def test_cwd_mode_cold_still_opens_shell(self):                      # guard: unchanged behaviour
        obj, code = self.go("", "cwd", cwd=self.root)
        self.assertEqual(code, 200, obj)
        self.assertEqual(len(self.spawns), 1)
        self.assertTrue(obj["folder"])


class TestWarmSettle(_S3):
    FAKE_SETTLE = False                          # exercise the real _folder_settled

    def setUp(self):
        super().setUp()
        self.killed = []
        p = mock.patch.object(term_vt.Pty, "kill",
                              new=lambda pt: (self.killed.append(pt.id), setattr(pt, "done", True)))
        p.start()
        self.addCleanup(p.stop)

    def wedged(self, cls=term_vt.Pty):
        fp = cls(tid="warm", pid=SHELL, fd=99, cwd=self.root)
        fp.folder, fp.mode, fp.startup_done = True, "cwd", False
        term_vt.PTYS["warm"] = fp
        return fp

    def run_settle(self, fp, fg, wedge=True):
        with mock.patch.object(term_vt.os, "tcgetpgrp", side_effect=lambda fd: fg):
            return term_vt._folder_settled(fp, time.time() - 1, wedge)

    def test_wedged_warm_shell_is_closed_after_settle_timeout(self):
        fp = self.wedged()
        with term_vt._LOCK:
            before = term_vt._live_count()
        self.assertFalse(self.run_settle(fp, SHELL + 1))
        self.assertTrue(fp.startup_done)
        self.assertTrue(fp.closing)
        self.assertEqual(self.killed, ["warm"])
        with term_vt._LOCK:
            self.assertEqual(term_vt._live_count(), before - 1)

    def test_warm_shell_with_viewer_or_at_prompt_is_kept(self):
        fp = self.wedged()
        fp.viewers = 1
        self.run_settle(fp, SHELL + 1)
        self.assertEqual((fp.closing, self.killed), (False, []))
        fp2 = self.wedged()
        self.run_settle(fp2, SHELL)
        self.assertEqual((fp2.closing, self.killed), (False, []))

    def test_opener_racing_timeout_never_sees_unclosed_wedged_shell(self):        # E4
        seen = []

        class Watched(term_vt.Pty):
            armed = False

            @property
            def startup_done(self):
                return self.__dict__.get("_sd", True)

            @startup_done.setter
            def startup_done(self, v):
                self.__dict__["_sd"] = v
                if v and Watched.armed:
                    Watched.armed = False

                    def peek():                  # an opener's view the moment startup_done flips
                        with term_vt._LOCK:
                            seen.append((self.startup_done, self.closing))
                    self.peek = threading.Thread(target=peek)
                    self.peek.start()

        fp = self.wedged(Watched)
        Watched.armed = True
        first = []

        def slow(pt):                            # the decision's syscall: slow enough for the opener to run
            if not first:
                first.append(1)
                time.sleep(0.3)
            return SHELL + 1

        with mock.patch.object(term_vt, "_fg_pgid", side_effect=slow):
            term_vt._folder_settled(fp, time.time() - 1, True)
        fp.peek.join(5)
        self.assertEqual(seen, [(True, True)])


if __name__ == "__main__":
    unittest.main()
