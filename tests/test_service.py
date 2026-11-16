"""The dashboard LaunchAgent (com.aitracker.server): plist, install/uninstall/status, the --service
strict bind, the CLI flags and the /api/service route. launchctl and subprocess are always stubbed."""
import errno
import os
import plistlib
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock

from aitracker import cli, config, schedule
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase
from tests.test_pending_schedule import Rec, _listing


class SvcBase(unittest.TestCase):
    def setUp(self):
        self.before = _listing()
        self.home = tempfile.TemporaryDirectory()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.addCleanup(self.root.cleanup)
        for p in (mock.patch.dict(os.environ, {"HOME": self.home.name}),
                  mock.patch.object(schedule, "_root", lambda: self.root.name),
                  mock.patch.object(schedule, "_is_temp", lambda p: False),
                  mock.patch.object(schedule, "_is_linked_worktree", lambda: False),
                  mock.patch.object(schedule.sys, "platform", "darwin"),
                  mock.patch.object(schedule.time, "sleep", lambda s: None),
                  mock.patch.object(config, "SERVICE", False)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.assertEqual(_listing(), self.before)  # real LaunchAgents untouched


class PlistTest(SvcBase):
    def test_service_plist_contents(self):
        env = {"HOME": self.home.name, "PATH": "/bin", "LANG": "en_US.UTF-8", "SHELL": "/bin/zsh", "TRACKER_AUTH": "u:p",
               "GITHUB_PAT": "x", "TRACKER_TUNNEL_READONLY": "1", "TRACKER_TERM_APP": "iTerm",
               "TRACKER_X_TOKEN": "t", "TRACKER_NO_BROWSER": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            d = plistlib.loads(schedule.service_plist(8790, "127.0.0.1"))
        self.assertEqual(d["Label"], schedule.SVC_LABEL)
        self.assertEqual(d["ProgramArguments"][1:], ["-m", "aitracker", "--service"])
        self.assertIs(d["RunAtLoad"], True)
        self.assertIs(d["KeepAlive"], True)
        self.assertEqual(d["ThrottleInterval"], 30)
        self.assertEqual(d["ExitTimeOut"], 10)
        self.assertNotIn("ProcessType", d)
        self.assertEqual(d["WorkingDirectory"], self.root.name)
        self.assertTrue(d["StandardOutPath"].startswith(os.path.join(self.home.name, "Library", "Logs")))
        self.assertEqual(set(d["EnvironmentVariables"]),
                         {"PATH", "PYTHONPATH", "PORT", "HOST", "PYTHONUNBUFFERED",
                          "TRACKER_TUNNEL_READONLY", "TRACKER_TERM_APP", "LANG", "SHELL"})
        self.assertEqual(d["EnvironmentVariables"]["PORT"], "8790")


class InstallTest(SvcBase):
    def test_install_refusals(self):
        def why(host="127.0.0.1"):
            r = Rec()
            self.assertEqual(schedule.svc_install(8790, host, run=r), 2)
            self.assertEqual(r.calls, [])
            self.assertFalse(os.path.exists(schedule.svc_plist_path()))

        with mock.patch.object(schedule.sys, "platform", "linux"):
            why()
        with mock.patch.object(config, "_HERE", self.root.name):   # no __init__.py: the bundle
            why()
        with mock.patch.object(schedule, "_is_linked_worktree", lambda: True):
            why()
        with mock.patch.object(schedule, "_root", lambda: "/x/.claude/worktrees/y"):
            why()
        with mock.patch.object(schedule, "_is_temp", lambda p: True):
            why()
        with mock.patch.object(schedule.sys, "executable", "/x/.cache/uv/archive/bin/python3"):
            why()
        for h in ("0.0.0.0", "::1", "192.168.1.5"):
            why(h)

    def test_install_never_truncates_live_plist(self):
        schedule.svc_install(8790, "127.0.0.1", run=Rec())
        path = schedule.svc_plist_path()
        def read():
            with open(path, "rb") as f:
                return f.read()
        before = read()
        with mock.patch.object(schedule, "service_plist", side_effect=ValueError("bad")):
            with self.assertRaises(ValueError):
                schedule.svc_install(8790, "127.0.0.1", run=Rec())
        self.assertEqual(read(), before)

    def test_install_sequence(self):
        r = Rec()
        self.assertEqual(schedule.svc_install(8790, "127.0.0.1", run=r), 0)
        path = schedule.svc_plist_path()
        self.assertEqual(r.calls, [["launchctl", "bootout", schedule._svc_target()],
                                   ["launchctl", "bootstrap", "gui/%d" % os.getuid(), path]])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)
        r = Rec(rcs={"bootstrap": 5})
        self.assertEqual(schedule.svc_install(8790, "127.0.0.1", run=r), 1)
        self.assertEqual(len(r.calls), 3)            # bootout + bootstrap + one retry
        self.assertFalse(os.path.exists(path))

    def test_uninstall_removes_plist_and_boots_out(self):
        schedule.svc_install(8790, "127.0.0.1", run=Rec())
        r = Rec()
        self.assertEqual(schedule.svc_uninstall(run=r), 0)
        self.assertFalse(os.path.exists(schedule.svc_plist_path()))
        self.assertEqual(r.calls, [["launchctl", "bootout", schedule._svc_target()]])
        self.assertFalse(os.path.exists(schedule._optout_path()))

    def test_self_defers(self):
        with mock.patch.object(config, "SERVICE", True):
            r = Rec()
            self.assertEqual(schedule.svc_install(8790, "127.0.0.1", run=r), 3)
            self.assertTrue(os.path.exists(schedule.svc_plist_path()))
            self.assertEqual(r.calls, [])
            self.assertEqual(schedule.svc_uninstall(run=r), 3)
            self.assertFalse(os.path.exists(schedule.svc_plist_path()))
            self.assertEqual(r.calls, [])
        popen = mock.Mock()
        schedule.svc_spawn_deferred(True, popen=popen)
        argv, kw = popen.call_args
        self.assertIs(kw["start_new_session"], True)
        self.assertEqual(argv[0][-3:], [schedule._svc_target(), "gui/%d" % os.getuid(), schedule.svc_plist_path()])
        schedule.svc_spawn_deferred(False, popen=popen)
        self.assertEqual(popen.call_args[0][0][-1], "")


class StatusTest(SvcBase):
    OUT = "state = running\n\tpid = 4242\n\tlast exit code = 0\n"

    def test_status_parses_launchctl(self):
        schedule.svc_install(8790, "127.0.0.1", run=Rec())
        st = schedule.svc_status(run=Rec(stdout=self.OUT))
        self.assertTrue(st["installed"] and st["loaded"] and st["python_exists"])
        self.assertEqual((st["pid"], st["state"], st["last_exit"], st["port"], st["host"]),
                         (4242, "running", 0, 8790, "127.0.0.1"))
        self.assertIsInstance(st["port"], int)
        self.assertTrue(st["can_install"])
        self.assertEqual(schedule.svc_baked(), (8790, "127.0.0.1"))

    def test_status_ignores_nested_pid_lines(self):
        schedule.svc_install(8790, "127.0.0.1", run=Rec())
        out = "\tparent pid = 1\n\tstate = running\n\tpid = 4242\n\tlast exit code = 0\n"
        self.assertEqual(schedule.svc_status(run=Rec(stdout=out))["pid"], 4242)

    def test_status_missing_python_and_not_loaded(self):
        path = schedule.svc_plist_path()
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            plistlib.dump({"ProgramArguments": ["/nope/python", "-m", "aitracker"],
                           "WorkingDirectory": self.root.name,
                           "EnvironmentVariables": {"PORT": "8790", "HOST": "127.0.0.1"}}, f)
        st = schedule.svc_status(run=Rec(rcs={"print": 113}))
        self.assertIs(st["python_exists"], False)
        self.assertTrue(st["installed"])
        self.assertFalse(st["loaded"])

    def test_status_non_darwin_makes_no_call(self):
        r = Rec()
        with mock.patch.object(schedule.sys, "platform", "linux"):
            st = schedule.svc_status(run=r)
        self.assertFalse(st["supported"])
        self.assertEqual(r.calls, [])

    def test_baked_none_without_plist(self):
        self.assertIsNone(schedule.svc_baked())


class BindStrictTest(unittest.TestCase):
    def _free_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        return p

    def _run(self, seq, **kw):
        sleeps = []
        it = iter(seq)
        with mock.patch.object(_server, "_port_busy", lambda h, p: next(it)), \
                mock.patch.object(_server.time, "sleep", sleeps.append):
            try:
                return _server.bind("127.0.0.1", self._free_port(), strict=True, wait=5.0, grace=3.0, **kw), sleeps
            except SystemExit as e:
                return e, sleeps

    def test_bind_strict_free_binds_on_exact_port(self):
        p = self._free_port()
        with mock.patch.object(_server, "_port_busy", lambda h, q: False), \
                mock.patch.object(_server.time, "sleep", lambda s: None):
            srv = _server.bind("127.0.0.1", p, strict=True)
        try:
            self.assertEqual(srv.server_address[1], p)
        finally:
            srv.server_close()

    def test_bind_strict_exits_75_after_a_wait(self):
        r, sleeps = self._run([True, True, False])
        self.assertIsInstance(r, SystemExit)
        self.assertEqual(r.code, 75)
        self.assertEqual(sleeps, [5.0, 5.0])

    def test_bind_strict_taken_during_grace_exits_75(self):
        r, sleeps = self._run([False, True, False])
        self.assertIsInstance(r, SystemExit)
        self.assertEqual(r.code, 75)
        self.assertEqual(sleeps, [3.0])

    def test_port_busy_only_refused_means_free(self):
        for exc, busy in ((ConnectionRefusedError(), False), (ConnectionResetError(), True), (socket.timeout(), True)):
            with mock.patch.object(_server.socket, "create_connection", side_effect=exc):
                self.assertIs(_server._port_busy("127.0.0.1", 1), busy, exc)

    def test_bind_strict_eaddrinuse_retries_without_exit(self):
        sentinel = object()
        sleeps = []
        with mock.patch.object(_server, "_port_busy", lambda h, p: False), \
                mock.patch.object(_server.time, "sleep", sleeps.append), \
                mock.patch.object(_server, "Server", side_effect=[OSError(errno.EADDRINUSE, "x"), sentinel]):
            self.assertIs(_server.bind("127.0.0.1", 1, strict=True, wait=5.0, grace=3.0), sentinel)
        self.assertEqual(sleeps, [3.0, 5.0, 3.0])

    def test_bind_strict_reraises_other_errors(self):
        with mock.patch.object(_server, "_port_busy", lambda h, p: False), \
                mock.patch.object(_server.time, "sleep", lambda s: None), \
                mock.patch.object(_server, "Server", side_effect=OSError(errno.EADDRNOTAVAIL, "x")):
            with self.assertRaises(OSError):
                _server.bind("127.0.0.1", 1, strict=True)


class CliTest(unittest.TestCase):
    def _main(self, argv):
        with mock.patch.object(sys, "argv", ["aitracker"] + argv), \
                mock.patch.object(cli, "run") as run, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRACKER_NO_BROWSER", None)
            cli.main()
        return run.call_args[1]

    def test_cli_service_flags(self):
        kw = self._main(["--service"])
        self.assertIs(kw["service"], True)
        self.assertIs(kw["open_browser"], False)
        kw = self._main([])
        self.assertIs(kw["service"], False)
        self.assertIs(kw["open_browser"], True)

    def test_cli_install_inside_service_defers(self):
        def inst(port, host):
            return 3 if config.SERVICE else 0
        with mock.patch.object(sys, "argv", ["aitracker", "--reinstall-service"]), \
                mock.patch.object(config, "SERVICE", False), \
                mock.patch.dict(os.environ, {"AITRACKER_SERVICE_PID": "1", "PORT": "8790"}), \
                mock.patch.object(cli, "svc_install", side_effect=inst), \
                mock.patch.object(cli, "svc_spawn_deferred") as spawn:
            with self.assertRaises(SystemExit) as e:
                cli.main()
        self.assertEqual(e.exception.code, 0)
        spawn.assert_called_once_with(True)

    def test_cli_reinstall_keeps_baked_port_without_env(self):
        with mock.patch.object(sys, "argv", ["aitracker", "--reinstall-service"]), \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(cli, "svc_baked", return_value=(8799, "127.0.0.1")), \
                mock.patch.object(cli, "svc_install", return_value=0) as inst:
            os.environ.pop("PORT", None)
            os.environ.pop("AITRACKER_SERVICE_PID", None)
            with self.assertRaises(SystemExit):
                cli.main()
        inst.assert_called_once_with(8799, "127.0.0.1")

    def test_run_service_sets_marker(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(config, "SERVICE", False), mock.patch.object(config, "BIND_PORT", 8790), \
                mock.patch.object(config, "BIND_HOST", "127.0.0.1"), \
                mock.patch.object(_server, "bind", side_effect=RuntimeError("stop")):
            os.environ.pop("AITRACKER_SERVICE_PID", None)
            with self.assertRaises(RuntimeError):
                _server.run(service=True)
            self.assertEqual(os.environ.get("AITRACKER_SERVICE_PID"), str(os.getpid()))

    def test_cli_service_status_prints_json(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["aitracker", "--service-status"]), \
                mock.patch.object(cli, "svc_status", return_value={"supported": True}), \
                mock.patch("sys.stdout", buf):
            cli.main()
        self.assertEqual(buf.getvalue().strip(), '{"supported": true}')


class RouteTest(_ServerCase):
    def setUp(self):
        super().setUp()
        self.m = {}
        for n, rv in (("svc_install", 0), ("svc_uninstall", 0), ("svc_spawn_deferred", None),
                      ("svc_baked", None), ("_svc_body", {"ok": 1})):
            p = mock.patch.object(_server, n, return_value=rv)
            self.m[n] = p.start()
            self.addCleanup(p.stop)
        for k, v in (("AUTH", ""), ("BIND_PORT", 8790), ("BIND_HOST", "127.0.0.1")):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)

    def test_route_dispatch(self):
        for act in ("install", "reinstall"):
            self.assertEqual(self._post("/api/service", {"action": act})[0], 200)
        self.assertEqual(self.m["svc_install"].call_count, 2)
        self.m["svc_install"].assert_called_with(8790, "127.0.0.1")
        self.assertEqual(self._post("/api/service", {"action": "uninstall"})[0], 200)
        self.m["svc_uninstall"].assert_called_once()
        n = self.m["svc_install"].call_count
        self.assertEqual(self._post("/api/service", {"action": "bogus"})[0], 400)
        self.assertEqual(self.m["svc_install"].call_count, n)
        self.assertEqual(self._get_json("/api/service"), (200, {"ok": 1}))
        self.m["svc_spawn_deferred"].assert_not_called()   # only an rc-3 (self) call defers

    def test_route_deferred_returns_202_then_spawns(self):
        self.m["svc_install"].return_value = 3
        order = []
        orig = _server.Handler._json

        def spy(h, *a, **k):
            order.append("json")
            return orig(h, *a, **k)
        self.m["svc_spawn_deferred"].side_effect = lambda r: order.append("spawn")
        with mock.patch.object(_server.Handler, "_json", spy):
            st, body = self._post("/api/service", {"action": "reinstall"})
        self.assertEqual((st, body["deferred"]), (202, "reinstall"))
        self.assertEqual(order, ["json", "spawn"])
        self.m["svc_spawn_deferred"].assert_called_once_with(True)
        self.m["svc_uninstall"].return_value = 3
        st, body = self._post("/api/service", {"action": "uninstall"})
        self.assertEqual(st, 202)
        self.m["svc_spawn_deferred"].assert_called_with(False)

    def test_reinstall_keeps_installed_port(self):
        self.m["svc_baked"].return_value = (8790, "127.0.0.1")
        with mock.patch.object(config, "BIND_PORT", 8791):
            self._post("/api/service", {"action": "reinstall"})
            self.m["svc_install"].assert_called_with(8790, "127.0.0.1")
            self._post("/api/service", {"action": "install"})
            self.m["svc_install"].assert_called_with(8791, "127.0.0.1")


class SvcBodyTest(unittest.TestCase):
    def test_body_fields(self):
        st = {"installed": True, "port": 8790, "loaded": True, "pid": 7, "reason": "why"}
        with mock.patch.object(_server, "svc_status", return_value=dict(st)), \
                mock.patch.object(config, "SERVICE", False), mock.patch.object(config, "BIND_PORT", 8791):
            b = _server._svc_body(8790)
            self.assertTrue(b["waiting"])
            self.assertEqual(b["install_port"], 8790)
            self.assertIn("started_at", b)
            self.assertEqual(_server._svc_body(8790, rc=2)["error"], "why")
            self.assertIn("launchctl", _server._svc_body(8790, rc=1)["error"])
            self.assertFalse(_server._svc_body(8791)["waiting"])


if __name__ == "__main__":
    unittest.main()
