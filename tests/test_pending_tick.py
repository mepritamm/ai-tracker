"""Step 10: tick / due / run_once / worker / cli_main. Everything runs against a temp fixture: config paths and
the lock file are patched, sched_* are stubbed, no real scheduler or real repo is touched."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, pending
from tests.pending_fixture import make_fixture, requires_git

DAY = 86400


def write_report(path, **kw):
    with open(path, "w") as fh:
        json.dump(kw, fh)


@requires_git
class TickTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)
        for k, v in (("PENDING_INTERVAL", "90d"), ("PENDING_CLEAN", "dry-run")):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.rf = config.PENDING_FILE

    def report(self):
        with open(self.rf) as fh:
            return json.load(fh)

    def test_due_is_pure(self):
        self.assertFalse(pending.due({}, 1000, None))
        self.assertTrue(pending.due({}, 1000, 90 * DAY))                       # no scheduled_at -> due
        self.assertFalse(pending.due({"scheduled_at": 1000}, 1000 + 5, DAY))
        self.assertTrue(pending.due({"scheduled_at": 0}, DAY - pending.SLACK, DAY))   # SLACK tolerance
        self.assertFalse(pending.due({"scheduled_at": 0}, DAY - pending.SLACK - 1, DAY))

    def test_tick_off_never_runs(self):
        write_report(self.rf, scheduled_at=1)
        with mock.patch.object(config, "PENDING_INTERVAL", "off"), \
                mock.patch.object(pending, "run_once") as ro:
            self.assertEqual(pending.tick(time.time()), "off")
        ro.assert_not_called()

    def test_tick_idle_when_scheduled_recently_even_if_list_is_old(self):
        now = time.time()
        write_report(self.rf, generated_at=now - 2 * DAY, scheduled_at=now - 10 * DAY)
        with mock.patch.object(pending, "run_once") as ro:
            self.assertEqual(pending.tick(now), "idle")                         # 90d interval: no list-refresh branch
        ro.assert_not_called()

    def test_tick_runs_when_due_scheduled_and_slack(self):
        now = time.time()
        write_report(self.rf, scheduled_at=now - 86370)
        with mock.patch.object(config, "PENDING_INTERVAL", "1d"):
            self.assertEqual(pending.tick(now), "run")
        self.assertAlmostEqual(self.report()["scheduled_at"], now, delta=1)
        self.assertEqual(self.report()["mode"], "dry-run")

    def test_tick_runs_with_no_report_then_idle_reading_disk_fresh(self):
        now = time.time()
        self.assertEqual(pending.tick(now), "run")
        self.assertEqual(pending.tick(now + 5), "idle")                         # no double run thread vs OS job

    def test_dry_run_leaves_scheduled_at_unchanged(self):
        write_report(self.rf, scheduled_at=1234.0)
        pending.run_once("dry-run", scheduled=False)
        self.assertEqual(self.report()["scheduled_at"], 1234.0)
        pending.run_once("safe", scheduled=True)                               # mode != configured mode -> carried forward
        self.assertEqual(self.report()["scheduled_at"], 1234.0)

    def test_lock_busy_returns_running_across_pending_files(self):
        with pending._pending_lock() as held:
            self.assertTrue(held)
            with mock.patch.object(config, "PENDING_FILE", os.path.join(self.fx.root, "other.json")):
                self.assertEqual(pending.run_once("dry-run"), {"running": True})
            with mock.patch.object(pending, "run_once", return_value={"running": True}):
                self.assertEqual(pending.tick(time.time()), "busy")
        self.assertFalse(os.path.exists(os.path.join(self.fx.root, "other.json")))

    def test_run_once_clears_running_flag_even_on_error(self):
        with mock.patch.object(pending, "scan", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                pending.run_once("dry-run")
        self.assertFalse(pending._RUNNING.is_set())
        with pending._pending_lock() as got:
            self.assertTrue(got)                                                # lock released too

    def test_run_async_refuses_while_running(self):
        gate = threading.Event()
        started = threading.Event()

        def slow(mode=None, **kw):
            started.set()
            gate.wait(5)
            return {}
        with mock.patch.object(pending, "run_once", slow):
            self.assertTrue(pending.run_async("dry-run"))
            started.wait(5)
            pending._RUNNING.set()
            try:
                self.assertFalse(pending.run_async("dry-run"))
            finally:
                pending._RUNNING.clear()
                gate.set()

    def test_start_worker_starts_even_when_scheduler_installed_and_is_idempotent(self):
        pending._WORKER[:] = []
        started = []
        with mock.patch.object(pending, "sched_status", return_value={"installed": True}), \
                mock.patch.object(pending, "_worker_loop", lambda: started.append(1)):
            pending.start_worker()
            t = pending._WORKER[0]
            t.join(2)
        self.assertEqual(started, [1])
        # alive thread -> second call is a no-op
        ev = threading.Event()
        alive = threading.Thread(target=ev.wait, daemon=True)
        alive.start()
        pending._WORKER[:] = [alive]
        pending.start_worker()
        self.assertIs(pending._WORKER[0], alive)
        ev.set()
        pending._WORKER[:] = []

    def test_worker_loop_survives_exceptions_and_sleeps_at_least_60(self):
        sleeps = []

        class Stop(BaseException):
            pass

        def fake_sleep(s):
            sleeps.append(s)
            if len(sleeps) >= 4:
                raise Stop()
        with mock.patch.object(pending, "tick", side_effect=RuntimeError("boom")):
            with self.assertRaises(Stop):
                pending._worker_loop(sleep=fake_sleep, clock=lambda: 1000.0)
        self.assertEqual(len(sleeps), 4)
        self.assertEqual(sleeps[0], 60)                                          # boot delay
        self.assertTrue(all(60 <= s <= 3600 for s in sleeps))
        self.assertIn("worker error", open(config.PENDING_LOG).read())

    def test_worker_loop_sleeps_until_next_due(self):
        now = 10_000_000.0
        write_report(self.rf, scheduled_at=now)
        sleeps = []

        def fake_sleep(s):
            sleeps.append(s)
            if len(sleeps) >= 2:
                raise KeyboardInterrupt
        with mock.patch.object(pending, "tick", return_value="idle"):
            with self.assertRaises(KeyboardInterrupt):
                pending._worker_loop(sleep=fake_sleep, clock=lambda: now + 90 * DAY - 7200)
        self.assertEqual(sleeps[1], 3600)                                        # capped at an hour

    def test_grace_decoupled_from_interval(self):
        for iv in ("1d", "90d"):
            with mock.patch.object(config, "PENDING_INTERVAL", iv):
                self.assertEqual(pending.PENDING_GRACE, 7 * DAY)

    # -- cli
    def test_cli_main_honours_config_json_safe(self):
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"PENDING_CLEAN": "safe", "PENDING_INTERVAL": "30d"}, fh)
        self.assertEqual(pending.cli_main([]), 0)
        rep = self.report()
        self.assertEqual((rep["mode"], rep["interval"]), ("safe", "30d"))
        self.assertIsNotNone(rep["scheduled_at"])

    def test_cli_dry_run_overrides_safe_and_prints_counts(self):
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"PENDING_CLEAN": "safe"}, fh)
        with mock.patch("builtins.print") as pr:
            self.assertEqual(pending.cli_main(["--dry-run"]), 0)
        self.assertEqual(self.report()["mode"], "dry-run")
        self.assertIn("pending-work [dry-run]", pr.call_args[0][0])

    def test_cli_json_flag(self):
        with mock.patch("builtins.print") as pr:
            pending.cli_main(["--dry-run", "--json"])
        self.assertIn("items", json.loads(pr.call_args[0][0]))

    def test_cli_if_due_and_scheduler_flags_use_stubs(self):
        with mock.patch("builtins.print") as pr:
            self.assertEqual(pending.cli_main(["--if-due"]), 0)                 # first ever: due -> run
        self.assertEqual(pr.call_args[0][0], "run")
        with mock.patch.object(pending, "sched_install", return_value=7) as si, \
                mock.patch.object(pending, "sched_uninstall", return_value=8) as su, \
                mock.patch.object(pending, "sched_status", return_value={"installed": False}) as ss, \
                mock.patch("builtins.print") as pr:
            self.assertEqual(pending.cli_main(["--install-scheduler"]), 7)
            self.assertEqual(pending.cli_main(["--uninstall-scheduler"]), 8)
            self.assertEqual(pending.cli_main(["--scheduler-status"]), 0)
        for m in (si, su, ss):
            m.assert_called_once_with()
        self.assertEqual(json.loads(pr.call_args[0][0]), {"installed": False})

    def test_cli_reports_lock_busy(self):
        with pending._pending_lock():
            with mock.patch("builtins.print") as pr:
                self.assertEqual(pending.cli_main(["--dry-run"]), 0)
        self.assertIn("lock", pr.call_args[0][0])


class LockPathTests(unittest.TestCase):
    def test_lock_path_ignores_tmpdir(self):
        code = "from aitracker import config; print(config.PENDING_LOCK)"
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        outs = []
        for tmpdir in ("/tmp/a-tmpdir", None):
            env = dict(os.environ, PYTHONPATH=root)
            env.pop("TMPDIR", None)
            if tmpdir:
                env["TMPDIR"] = tmpdir
            outs.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=root).stdout.strip())
        self.assertEqual(outs[0], outs[1])
        self.assertTrue(outs[0].startswith(os.path.expanduser("~")))


if __name__ == "__main__":
    unittest.main()
