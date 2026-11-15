import os
import plistlib
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from aitracker import schedule

# captured at import, before HOME is patched: the REAL LaunchAgents dir
LA = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")


def _listing():
    try:
        return sorted(os.listdir(LA))
    except OSError:
        return None


class Rec:
    """Stub for subprocess.run: records argv, never spawns anything."""

    def __init__(self, rcs=None, stdout=""):
        self.calls, self.rcs, self.stdout = [], rcs or {}, stdout

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return SimpleNamespace(returncode=self.rcs.get(argv[1], 0), stdout=self.stdout, stderr="")


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.before = _listing()
        self.home = tempfile.TemporaryDirectory()
        self.root = tempfile.TemporaryDirectory()
        for p in (mock.patch.dict(os.environ, {"HOME": self.home.name}),
                  mock.patch.object(schedule, "_root", lambda: self.root.name)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.home.cleanup)
        self.addCleanup(self.root.cleanup)

    def tearDown(self):
        self.assertEqual(_listing(), self.before)  # real LaunchAgents untouched

    def plat(self, p):
        q = mock.patch.object(schedule.sys, "platform", p)
        q.start()
        self.addCleanup(q.stop)

    def test_plist_keys_and_paths(self):
        d = plistlib.loads(schedule.launchd_plist())
        self.assertEqual(d["Label"], schedule.LABEL)
        self.assertEqual(d["ProgramArguments"][1:], ["-m", "aitracker", "--pending", "--if-due"])
        self.assertEqual(d["WorkingDirectory"], self.root.name)
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 10, "Minute": 0})
        self.assertFalse(d["RunAtLoad"])
        self.assertTrue(d["StandardOutPath"].startswith(os.path.join(self.home.name, "Library", "Logs")))
        self.assertTrue(schedule.plist_path().startswith(self.home.name))

    def test_schtasks_argv_and_cap(self):
        a = schedule.schtasks_create_argv()
        self.assertEqual(a[:3], ["schtasks", "/Create", "/TN"])
        self.assertIn("--if-due", a[-1])
        self.assertIn("ai-tracker-pending.log", a[-1])
        with mock.patch.object(schedule, "_root", lambda: "C:\\" + "x" * 300):
            self.plat("win32")
            rec = Rec()
            self.assertEqual(schedule.sched_install(rec), 2)
            self.assertEqual(rec.calls, [])

    def test_worktree_refused(self):
        self.plat("darwin")
        open(os.path.join(self.root.name, ".git"), "w").close()
        rec = Rec()
        self.assertEqual(schedule.sched_install(rec), 2)
        self.assertEqual(rec.calls, [])
        self.assertFalse(os.path.exists(schedule.plist_path()))

    def test_install_uninstall_sequence(self):
        self.plat("darwin")
        rec = Rec()
        self.assertEqual(schedule.sched_install(rec), 0)
        self.assertEqual([c[1] for c in rec.calls], ["bootout", "bootstrap"])
        self.assertTrue(os.path.exists(schedule.plist_path()))
        rec2 = Rec()
        self.assertEqual(schedule.sched_uninstall(rec2), 0)
        self.assertEqual([c[1] for c in rec2.calls], ["bootout"])
        self.assertFalse(os.path.exists(schedule.plist_path()))
        self.assertEqual(schedule.sched_uninstall(Rec()), 0)  # idempotent

    def test_bootstrap_failure_leaves_no_plist(self):
        self.plat("darwin")
        self.assertEqual(schedule.sched_install(Rec({"bootstrap": 5})), 1)
        self.assertFalse(os.path.exists(schedule.plist_path()))

    def test_reinstall_reports_old_root(self):
        self.plat("darwin")
        schedule.sched_install(Rec())
        with mock.patch.object(schedule, "_root", lambda: "/elsewhere"), \
                mock.patch("builtins.print") as pr:
            schedule.sched_install(Rec())
        self.assertIn(self.root.name, str(pr.call_args_list))

    def test_status_parses_last_exit(self):
        self.plat("darwin")
        schedule.sched_install(Rec())
        st = schedule.sched_status(Rec(stdout="x = 1\n\tlast exit code = 7\n"))
        self.assertEqual((st["kind"], st["installed"], st["last_exit"]), ("launchd", True, 7))
        self.assertEqual(st["root"], self.root.name)
        self.assertTrue(st["root_exists"])
        self.assertFalse(schedule.sched_status(Rec({"print": 113}))["installed"])

    def test_windows_status_uninstall(self):
        self.plat("win32")
        self.assertTrue(schedule.sched_status(Rec())["installed"])
        rec = Rec()
        schedule.sched_uninstall(rec)
        self.assertEqual(rec.calls[0][:2], ["schtasks", "/Delete"])

    def test_other_platform_prints_crontab(self):
        self.plat("linux")
        with mock.patch("builtins.print") as pr:
            self.assertEqual(schedule.sched_install(Rec()), 2)
        self.assertIn("0 10 * * *", str(pr.call_args_list))


def _hang(argv, **kw):
    assert kw.get("timeout"), "every OS-scheduler call needs a timeout"
    raise subprocess.TimeoutExpired(argv, kw["timeout"])


class TimeoutTest(ScheduleTest):
    def test_timeouts_never_raise(self):
        for p in ("darwin", "win32"):
            with mock.patch.object(schedule.sys, "platform", p):
                st = schedule.sched_status(_hang)
                self.assertFalse(st["installed"])
                self.assertEqual(st.get("error"), "timeout")
                self.assertEqual(schedule.sched_install(_hang), 1)
                self.assertEqual(schedule.sched_uninstall(_hang), 0)
        self.assertFalse(os.path.exists(schedule.plist_path()))


class AutoInstallTest(ScheduleTest):
    _real = staticmethod(schedule._under_test)

    def setUp(self):
        super().setUp()
        self.plat("darwin")
        for target, val in (("_under_test", lambda: False), ("_is_temp", lambda p: False)):
            q = mock.patch.object(schedule, target, val)
            q.start()
            self.addCleanup(q.stop)

    def test_missing_installs(self):
        rec = Rec({"print": 113})
        r = schedule.autoinstall_once(rec)
        self.assertEqual(r["action"], "installed")
        self.assertTrue(os.path.exists(schedule.plist_path()))

    def test_present_only_status_call(self):
        schedule.sched_install(Rec())
        rec = Rec()
        self.assertEqual(schedule.autoinstall_once(rec)["action"], "present")
        self.assertEqual([c[1] for c in rec.calls], ["print"])

    def test_root_gone_repoints(self):
        schedule.sched_install(Rec())
        with mock.patch.object(schedule, "_read_plist", lambda: {"WorkingDirectory": "/gone/x"}):
            r = schedule.autoinstall_once(Rec())
        self.assertEqual(r, {"action": "installed", "reason": "repointed"})

    def test_optout_roundtrip(self):
        schedule.sched_uninstall(Rec())
        self.assertTrue(os.path.exists(schedule._optout_path()))
        rec = Rec({"print": 113})
        self.assertEqual(schedule.autoinstall_once(rec)["reason"], "opted out")
        self.assertEqual(rec.calls, [])
        schedule.sched_install(Rec())
        self.assertFalse(os.path.exists(schedule._optout_path()))

    def test_guards_skip_without_calls(self):
        rec = Rec({"print": 113})
        with mock.patch.object(schedule, "_under_test", lambda: True):
            self.assertEqual(schedule.autoinstall_once(rec)["action"], "skipped")
        with mock.patch.object(schedule, "_is_temp", lambda p: True):
            self.assertEqual(schedule.autoinstall_once(rec)["reason"], "temp directory")
        with mock.patch.object(schedule, "_root", lambda: "/Users/x/ai-tracker/.claude/worktrees/w"):
            self.assertEqual(schedule.autoinstall_once(rec)["reason"], "linked worktree checkout")
        open(os.path.join(self.root.name, ".git"), "w").close()
        self.assertEqual(schedule.autoinstall_once(rec)["reason"], "linked worktree checkout")
        self.plat("linux")
        self.assertEqual(schedule.autoinstall_once(rec)["action"], "skipped")
        self.assertEqual(rec.calls, [])

    def test_under_test_helper_real(self):
        q = mock.patch.object(schedule, "_under_test", self._real)
        q.start(); self.addCleanup(q.stop)
        self.assertTrue(schedule._under_test())  # we are running under unittest
        with mock.patch.object(schedule.sys, "argv", ["x", "--selfcheck"]):
            self.assertTrue(schedule._under_test())

    def test_under_test_direct_test_file_run(self):
        q = mock.patch.object(schedule, "_under_test", self._real)
        q.start(); self.addCleanup(q.stop)
        with mock.patch.dict(os.environ, {}, clear=False) as env:
            env.pop("AITRACKER_NO_AUTOINSTALL", None)
            env.pop("PYTEST_CURRENT_TEST", None)
            with mock.patch.object(schedule.sys, "argv", ["tests/test_x.py"]):
                self.assertTrue(schedule._under_test())
            with mock.patch.object(schedule.sys, "argv", ["/usr/bin/ai-tracker"]):
                self.assertFalse(schedule._under_test())

    def test_failure_returns_reason(self):
        r = schedule.autoinstall_once(Rec({"print": 113, "bootstrap": 5}))
        self.assertEqual(r["action"], "failed")
        self.assertFalse(os.path.exists(schedule._optout_path()))
        def boom(*a, **k):
            raise OSError("nope")
        self.assertEqual(schedule.autoinstall_once(boom)["action"], "failed")


if __name__ == "__main__":
    unittest.main()
