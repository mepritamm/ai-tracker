"""A5: /api/update, /api/update/fetch, /api/update/apply, /api/scheduler, X-Server-Started, run() wiring.
Everything that acts (schedule/update/start_restart) is stubbed; nothing installs, fetches, merges or restarts."""
import http.client
import json
import unittest
from unittest import mock

from aitracker import server as _server
from tests.test_cr_routes import _ServerCase

FWD = {"X-Forwarded-For": "203.0.113.9"}
ST = {"kind": "git", "terminals": 2, "can_update": True}


class _Base(_ServerCase):
    def req(self, method, path, payload=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        body = None
        if method == "POST":
            body = json.dumps(payload or {}).encode()
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = r.read()
        hd = dict(r.getheaders())
        c.close()
        return r.status, json.loads(out), hd


class RouteTests(_Base):
    def test_every_new_route_refuses_non_local(self):
        with mock.patch.object(_server, "update_status") as us, mock.patch.object(_server, "update_fetch") as uf, \
                mock.patch.object(_server, "update_apply") as ua, mock.patch.object(_server, "sched_install") as si, \
                mock.patch.object(_server, "sched_uninstall") as su, mock.patch.object(_server, "start_restart") as sr:
            for m, p in (("GET", "/api/update"), ("GET", "/api/scheduler"), ("POST", "/api/update/fetch"),
                         ("POST", "/api/update/apply"), ("POST", "/api/scheduler")):
                self.assertEqual(self.req(m, p, {"action": "install"}, FWD)[0], 403, p)
            for f in (us, uf, ua, si, su, sr):
                f.assert_not_called()
        for p in ("/api/update", "/api/scheduler"):
            self.assertNotIn(p, _server._RO_GET_ALLOW)

    def test_get_update_adds_run_jobs(self):
        with mock.patch.object(_server, "update_status", return_value=dict(ST)), \
                mock.patch.object(_server, "_run_jobs", return_value=1):
            st, j, _ = self.req("GET", "/api/update")
        self.assertEqual((st, j["terminals"], j["run_jobs"]), (200, 2, 1))

    def test_fetch_returns_status_body(self):
        with mock.patch.object(_server, "update_fetch", return_value=dict(ST, fetch_error="x")) as uf:
            st, j, _ = self.req("POST", "/api/update/fetch", {"remote": "evil"})
        self.assertEqual((st, j["fetch_error"]), (200, "x"))
        uf.assert_called_once_with()

    def test_apply_409_needs_confirm_then_confirmed_202_restarts(self):
        calls = []

        def apply(confirm=False):
            calls.append(confirm)
            if not confirm:
                return 409, {"error": "2 open terminals will close", "needs_confirm": True, "terminals": 2}
            return 202, {"restarting": True, "recover": "r"}
        with mock.patch.object(_server, "update_apply", apply), mock.patch.object(_server, "start_restart") as sr, \
                mock.patch.object(_server, "_run_jobs", return_value=1):
            st, j, _ = self.req("POST", "/api/update/apply", {})
            self.assertEqual((st, j["needs_confirm"], j["terminals"], j["run_jobs"]), (409, True, 2, 1))
            sr.assert_not_called()
            st, j, _ = self.req("POST", "/api/update/apply", {"confirm_terminals": "yes"})   # only literal true counts
            self.assertEqual(st, 409)
            st, j, _ = self.req("POST", "/api/update/apply", {"confirm_terminals": True, "remote": "x"})
            self.assertEqual((st, j["recover"]), (202, "r"))
            sr.assert_called_once()
        self.assertEqual(calls, [False, False, True])

    def test_202_whose_write_raises_still_schedules_the_restart(self):
        real_json = _server.Handler._json

        def boom(self, obj, code=200, headers=None):
            if code == 202:
                raise ConnectionAbortedError("peer gone")
            return real_json(self, obj, code, headers)
        with mock.patch.object(_server, "update_apply", return_value=(202, {"restarting": True})), \
                mock.patch.object(_server, "start_restart") as sr, mock.patch.object(_server.Handler, "_json", boom):
            try:
                self.req("POST", "/api/update/apply", {"confirm_terminals": True})
            except Exception:
                pass            # the server drops the connection; only the restart matters
        sr.assert_called_once()

    def test_scheduler_enum_and_actions(self):
        stat = {"kind": "launchd", "installed": True, "root": "/r", "root_exists": True, "last_exit": 0}
        with mock.patch.object(_server, "sched_status", return_value=dict(stat)), \
                mock.patch.object(_server, "sched_install", return_value=0) as si, \
                mock.patch.object(_server, "sched_uninstall", return_value=0) as su:
            self.assertEqual(self.req("POST", "/api/scheduler", {"action": "rm -rf"})[0], 400)
            self.assertEqual(self.req("POST", "/api/scheduler", {})[0], 400)
            si.assert_not_called()
            st, j, _ = self.req("POST", "/api/scheduler", {"action": "install"})
            self.assertEqual((st, si.call_count, su.call_count, j["installed"]), (200, 1, 0, True))
            self.assertIn("supported", j)
            self.assertIn("opted_out", j)
            self.req("POST", "/api/scheduler", {"action": "uninstall"})
            self.assertEqual(su.call_count, 1)
        with mock.patch.object(_server, "sched_status", return_value=dict(stat)), \
                mock.patch.object(_server, "sched_install", return_value=2):
            self.assertIn("error", self.req("POST", "/api/scheduler", {"action": "install"})[1])

    def test_list_carries_server_started(self):
        st, _j, h = self.req("GET", "/api/list")
        self.assertEqual(st, 200)
        self.assertEqual(h.get("X-Server-Started"), _server._STARTED)


class RunWiring(unittest.TestCase):
    def _run(self, autoinstall, env=None):
        class Stop(Exception):
            pass
        srv = mock.Mock()
        srv.server_address = ("127.0.0.1", 1)
        srv.serve_forever.side_effect = Stop
        threads = []
        real = _server.threading.Thread

        def mk(*a, **k):
            t = real(*a, **k)
            threads.append(t)
            return t
        with mock.patch.dict("os.environ", env or {}), mock.patch.object(_server, "bind", return_value=srv), \
                mock.patch.object(_server, "publish_endpoint"), mock.patch.object(_server, "start_worker"), \
                mock.patch.object(_server.tunnel, "autostart"), mock.patch.object(_server.signal, "signal"), \
                mock.patch.object(_server, "autoinstall_once", autoinstall), \
                mock.patch.object(_server.threading, "Thread", mk):
            with self.assertRaises(Stop):
                _server.run(open_browser=False)
        for t in threads:
            t.join(5)

    def test_failing_autoinstall_does_not_stop_run(self):
        boom = mock.Mock(side_effect=RuntimeError("boom"))
        self._run(boom)
        boom.assert_called_once()

    def test_run_starts_the_terminal_recorder(self):
        from aitracker import term_vt
        with mock.patch.object(term_vt, "start_remember") as sr:
            self._run(mock.Mock(return_value={"action": "skipped", "reason": "x"}))
        sr.assert_called_once()

    def test_autoinstall_called_once_and_opt_out_env(self):
        ok = mock.Mock(return_value={"action": "skipped", "reason": "x"})
        self._run(ok)
        ok.assert_called_once()
        off = mock.Mock()
        self._run(off, {"TRACKER_SCHEDULER_AUTOINSTALL": "0"})
        off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
