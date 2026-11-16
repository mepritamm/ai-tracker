"""In-app Update restart path (A3b). The exec itself is ALWAYS stubbed in-process; the one real exec
happens in a throw-away child interpreter that is not the test runner."""
import inspect
import io
import os
import pty
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import config, pending, update


class FlushLog(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1


def _pty_sleeper():
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("sleep", ["sleep", "30"])
    return pid, fd


class CloexecTests(unittest.TestCase):
    def _reap(self, pid, fd):
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        os.close(fd)

    def test_pty_master_becomes_non_inheritable(self):
        pid, fd = _pty_sleeper()
        self.addCleanup(self._reap, pid, fd)
        # pty.fork left it inheritable (the bug) before Python 3.15; recreate that state on every
        # runtime so this stays a red proof of _cloexec_all, not of the interpreter.
        os.set_inheritable(fd, True)
        update._cloexec_all()
        self.assertFalse(os.get_inheritable(fd))

    def test_master_is_closed_in_the_exec_image(self):
        # run the REAL function body in a child interpreter: pty.fork, cloexec, then exec a probe
        script = ("import os, pty, sys, signal\n" + inspect.getsource(update._cloexec_all) + "\n"
                  "pid, fd = pty.fork()\n"
                  "if pid == 0:\n    os.execvp('sleep', ['sleep', '30'])\n"
                  "os.set_inheritable(fd, True)\n"        # the pre-3.15 pty.fork state (see above)
                  "if os.environ.get('DO_CLOEXEC') == '1':\n    _cloexec_all()\n"
                  "probe = 'import os,sys\\ntry:\\n os.fstat(int(sys.argv[1])); print(\"open\")\\n"
                  "except OSError:\\n print(\"closed\")'\n"
                  "try:\n    os.execv(sys.executable, [sys.executable, '-c', probe, str(fd)])\n"
                  "finally:\n    os.kill(pid, signal.SIGKILL)\n")
        for flag, want in (("1", "closed"), ("0", "open")):       # the "0" run is the red proof
            env = dict(os.environ, DO_CLOEXEC=flag)
            p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(p.stdout.strip(), want, p.stderr)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="restart-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        p = mock.patch.object(config, "PENDING_LOCK", os.path.join(self.tmp, "pending.lock"))
        p.start()
        self.addCleanup(p.stop)
        self.stop = mock.patch.object(update.tunnel, "stop")
        self.auto = mock.patch.object(update.tunnel, "autostart")
        self.m_stop, self.m_auto = self.stop.start(), self.auto.start()
        self.addCleanup(self.stop.stop)
        self.addCleanup(self.auto.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        update._RESTART_ERROR = None
        self.addCleanup(setattr, update, "_RESTART_ERROR", None)
        self.addCleanup(update._release_held)

    def _hold(self, recover="RECOVER ME"):
        self.assertTrue(update._APPLY.acquire(blocking=False))
        cm = pending._pending_lock()
        self.assertTrue(cm.__enter__())
        update._HELD = {"cm": cm, "recover": recover}
        return update._HELD

    def test_exec_failure_restarts_tunnel_reports_and_releases(self):
        held = self._hold()
        order = []
        with mock.patch.object(update, "_cloexec_all", lambda: order.append("cloexec")), \
                mock.patch.object(update.os, "execv", side_effect=OSError("moved python")):
            update.restart_in_place(8790, held)
        self.assertEqual(order, ["cloexec"])
        self.m_stop.assert_called_once_with(keep_on=True)
        self.m_auto.assert_called_once_with(8790, config.BIND_HOST)
        self.assertEqual(update.update_status()["restart_error"], "moved python")
        self.assertIsNone(update._HELD)
        self.assertTrue(update._APPLY.acquire(blocking=False))          # apply lock released
        update._APPLY.release()
        with pending._pending_lock() as got:                            # pending lock released
            self.assertTrue(got)

    def test_t7b_remember_terminals_final_runs_before_exec_and_cannot_block_it(self):
        held = self._hold()
        order = []

        class Rec:
            @staticmethod
            def remember_terminals(final=False):
                order.append(("remember", final))
                raise RuntimeError("boom")        # a failing recorder must not stop the exec
        with mock.patch.dict(sys.modules, {"aitracker.term_vt": Rec}), \
                mock.patch.object(update, "_cloexec_all", lambda: order.append("cloexec")), \
                mock.patch.object(update.os, "execv", side_effect=lambda *a: order.append("exec") or (_ for _ in ()).throw(OSError("x"))):
            update.restart_in_place(8790, held)
        self.assertEqual(order, [("remember", True), "cloexec", "exec"])

    def test_exec_args_env_and_recovery_line_before_exec(self):
        held = self._hold("RECOVER ME")
        out = FlushLog()
        seen = {}

        def fake_exec(path, argv):
            seen.update(path=path, argv=argv, text=out.getvalue(), flushes=out.flushes, locked=update._HELD is not None)
        with mock.patch.object(sys, "stdout", out), mock.patch.object(update.os, "execv", fake_exec), \
                mock.patch.object(update, "_cloexec_all"), \
                mock.patch.object(sys, "orig_argv", ["python3", "-m", "aitracker", "--x"], create=True):
            update.restart_in_place(8791, held)
        self.assertEqual(seen["path"], sys.executable)
        self.assertEqual(seen["argv"], ["python3", "-m", "aitracker", "--x"])
        self.assertIn("RECOVER ME", seen["text"])                       # printed before exec
        self.assertGreaterEqual(seen["flushes"], 2)                     # and flushed
        self.assertTrue(seen["locked"])                                 # locks held right up to exec
        self.assertEqual(os.environ["PORT"], "8791")
        self.assertEqual(os.environ["TRACKER_NO_BROWSER"], "1")
        self.m_stop.assert_called_once_with(keep_on=True)

    def test_fallback_argv_without_orig_argv(self):
        held = self._hold("")
        seen = {}
        saved = getattr(sys, "orig_argv", None)
        had = hasattr(sys, "orig_argv")
        if had:
            del sys.orig_argv
        try:
            with mock.patch.object(update.os, "execv", lambda p, a: seen.update(argv=a)), \
                    mock.patch.object(update, "_cloexec_all"), mock.patch.object(sys, "argv", ["x", "--serve"]):
                update.restart_in_place(8790, held)
        finally:
            if had:
                sys.orig_argv = saved
        self.assertEqual(seen["argv"], [sys.executable, "-m", "aitracker", "--serve"])

    def _assert_recovered(self, execv):                                         # E2-F4
        execv.assert_not_called()
        self.assertTrue(update.update_status()["restart_error"])
        self.m_auto.assert_called_once_with(8790, config.BIND_HOST)
        self.assertIsNone(update._HELD)
        with pending._pending_lock() as got:                            # a later scan is accepted
            self.assertTrue(got)
        with mock.patch.object(update, "_apply_locked", return_value=(409, {"error": "x"})):
            self.assertEqual(update.update_apply()[1]["error"], "x")    # a later apply is accepted too
        self.assertIsNone(update._HELD)

    def test_tunnel_stop_failure_releases_both_locks(self):
        held = self._hold()
        execv = mock.Mock()
        self.m_stop.side_effect = PermissionError("nope")
        with mock.patch.object(update.os, "execv", execv), mock.patch.object(update, "_cloexec_all"):
            update.restart_in_place(8790, held)
        self._assert_recovered(execv)

    def test_cloexec_failure_releases_both_locks(self):
        held = self._hold()
        execv = mock.Mock()
        with mock.patch.object(update.os, "execv", execv), \
                mock.patch.object(update, "_cloexec_all", side_effect=RuntimeError("boom")):
            update.restart_in_place(8790, held)
        self._assert_recovered(execv)

    def test_dead_stdout_does_not_block_exec(self):                             # E2-F4
        held = self._hold("RECOVER ME")

        class Dead(io.StringIO):
            def write(self, s):
                raise OSError(5, "EIO")
        execv = mock.Mock()
        with mock.patch.object(sys, "stdout", Dead()), mock.patch.object(update.os, "execv", execv), \
                mock.patch.object(update, "_cloexec_all"):
            update.restart_in_place(8790, held)
        execv.assert_called_once()

    def test_start_restart_runs_on_a_thread(self):
        done = threading.Event()
        calls = []
        with mock.patch.object(update, "restart_in_place", lambda port, held=None: (calls.append(port), done.set())):
            t = update.start_restart(8792, delay=0)
        self.assertTrue(done.wait(10))
        self.assertEqual(calls, [8792])
        self.assertTrue(t.daemon)


if __name__ == "__main__":
    unittest.main()
