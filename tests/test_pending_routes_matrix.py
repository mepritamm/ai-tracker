"""T8 / T10 / safe-delete-remote: the pending / update / scheduler route matrix over real HTTP.

Every route x every caller class -> the exact status, and for every refused cell no side effect ran
(no scan, no fetch/apply/restart, no scheduler install). All side-effecting entry points are stubbed:
nothing here scans, fetches, restarts or touches launchd."""
import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, pending
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase

FWD = {"X-Forwarded-For": "203.0.113.9"}
CF = {"Cf-Connecting-Ip": "203.0.113.9", "Cf-Ray": "abc"}
ROUTES = (
    ("GET", "/api/pending", None),
    ("GET", "/api/pending/item?id=nope", None),
    ("POST", "/api/pending/run", {}),
    ("GET", "/api/update", None),
    ("POST", "/api/update/fetch", {}),
    ("POST", "/api/update/apply", {}),
    ("GET", "/api/scheduler", None),
    ("POST", "/api/scheduler", {"action": "install"}),
    ("GET", "/api/service", None),
    ("POST", "/api/service", {"action": "install"}),
)
LOCAL_OK = {"/api/pending": 200, "/api/pending/item?id=nope": 404, "/api/pending/run": 202, "/api/update": 200,
            "/api/update/fetch": 200, "/api/update/apply": 409, "/api/scheduler": 200,
            "/api/service": 200}


def basic(cred):
    return {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()}


def _expected_local(method, path):
    if method == "POST" and path in ("/api/scheduler", "/api/service"):
        return 200
    return LOCAL_OK[path]


class _RemotePeer(_server.Handler):
    """The same handler, but the socket peer is NOT loopback (a LAN caller / a forwarder on another host)."""
    @property
    def client_address(self):
        return ("10.1.2.3", 5555)

    @client_address.setter
    def client_address(self, _v):
        pass


class MatrixTests(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("PENDING_FILE", os.path.join(d, "pending.json")), ("PENDING_LOCK", os.path.join(d, "p.lock")),
                     ("PENDING_LOG", os.path.join(d, "p.log"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.stubs = {}
        for name, rv in (("run_async", True), ("update_fetch", {"ok": True}),
                         ("update_apply", (409, {"needs_confirm": True, "terminals": 1})),
                         ("sched_install", 0), ("sched_uninstall", 0), ("start_restart", None),
                         ("svc_install", 0), ("svc_uninstall", 0), ("svc_spawn_deferred", None)):
            m = mock.patch.object(_server, name, return_value=rv)
            self.stubs[name] = m.start()
            self.addCleanup(m.stop)
        for name, rv in (("update_status", {"ok": True}), ("sched_status", {"installed": False}),
                       ("_svc_body", {"ok": 1})):
            m = mock.patch.object(_server, name, return_value=rv)
            m.start()
            self.addCleanup(m.stop)
        m = mock.patch.object(pending, "run_once", side_effect=AssertionError("a route must never scan inline"))
        m.start()
        self.addCleanup(m.stop)
        self.remote = _server.Server(("127.0.0.1", 0), _RemotePeer)
        self.addCleanup(self.remote.server_close)
        threading.Thread(target=self.remote.serve_forever, daemon=True).start()
        self.addCleanup(self.remote.shutdown)

    def req(self, method, path, payload=None, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=5)
        h = dict(headers or {})
        body = None
        if method == "POST":
            body = json.dumps(payload or {}).encode()
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = r.read()
        c.close()
        try:
            return r.status, json.loads(out)
        except ValueError:
            return r.status, {}

    def assert_no_side_effect(self):
        for name in ("run_async", "update_fetch", "update_apply", "sched_install", "sched_uninstall", "start_restart",
                     "svc_install", "svc_uninstall", "svc_spawn_deferred"):
            self.stubs[name].assert_not_called()

    def sweep(self, expect, headers=None, port=None):
        """expect: int (every route) or callable(method, path) -> int."""
        for method, path, payload in ROUTES:
            want = expect(method, path) if callable(expect) else expect
            with self.subTest(route="%s %s" % (method, path)):
                st, _j = self.req(method, path, payload, headers, port)
                self.assertEqual(st, want)

    # -- local callers
    def test_local_no_auth(self):
        self.sweep(_expected_local)
        # the side-effecting routes really ran (stubs), once each
        self.stubs["run_async"].assert_called_once_with("dry-run")
        self.stubs["update_fetch"].assert_called_once()
        self.stubs["update_apply"].assert_called_once()
        self.stubs["sched_install"].assert_called_once()

    def test_local_with_auth_cookie_or_basic_and_without(self):
        config.AUTH = "u:p"
        self.sweep(_expected_local, basic("u:p"))
        self.stubs["run_async"].reset_mock()
        self.stubs["update_fetch"].reset_mock()
        self.stubs["update_apply"].reset_mock()
        self.stubs["sched_install"].reset_mock()
        self.stubs["svc_install"].reset_mock()
        self.sweep(401)                                       # no credential: login wall, nothing ran
        self.assert_no_side_effect()
        self.sweep(401, basic("u:wrong"))
        self.assert_no_side_effect()

    # -- every non-local caller class is refused on every route, with no side effect
    def test_proxy_header_caller_refused(self):
        self.sweep(403, FWD)
        self.assert_no_side_effect()

    def test_tunnel_caller_with_tunnel_creds_still_refused(self):
        with mock.patch.object(_server.tunnel, "cred", return_value="tu:tp"):
            self.sweep(403, dict(CF, **basic("tu:tp")))
            self.assert_no_side_effect()
            self.sweep(401, CF)                              # no creds at all: the tunnel's own login wall
            self.assert_no_side_effect()

    def test_readonly_tunnel_visitor_refused_with_readonly_body(self):
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"TUNNEL_READONLY": True}, fh)
        for method, path, payload in ROUTES:
            with self.subTest(route="%s %s" % (method, path)):
                st, j = self.req(method, path, payload, FWD)
                self.assertEqual(st, 403)
                self.assertTrue(j.get("readonly"))
        self.assert_no_side_effect()

    def test_non_local_peer_refused(self):
        self.sweep(403, port=self.remote.server_address[1])
        self.assert_no_side_effect()

    def test_foreign_host_refused(self):
        self.sweep(403, {"Host": "evil.example.com"})
        self.assert_no_side_effect()

    def test_cross_origin_refused(self):
        self.sweep(403, {"Origin": "http://evil.example.com"})
        self.assert_no_side_effect()
        self.sweep(403, {"Origin": "null"})
        self.assert_no_side_effect()

    # -- safe-delete can never be switched on remotely
    def test_safe_delete_cannot_be_enabled_remotely(self):
        body = {"key": "PENDING_CLEAN", "value": "safe"}
        cases = (("proxy", FWD, None), ("foreign host", {"Host": "evil.example.com"}, None),
                 ("cross origin", {"Origin": "http://evil.example.com"}, None),
                 ("non-local peer", {}, self.remote.server_address[1]))
        for label, hdr, port in cases:
            with self.subTest(caller=label):
                st, _j = self.req("POST", "/api/config", body, hdr, port)
                self.assertEqual(st, 403)
                self.assertFalse(os.path.exists(config.CONFIG_FILE))
        # a tunnel caller holding VALID tunnel credentials is still not this machine
        with mock.patch.object(_server.tunnel, "cred", return_value="tu:tp"):
            st, _j = self.req("POST", "/api/config", body, dict(CF, **basic("tu:tp")))
        self.assertEqual(st, 403)
        self.assertFalse(os.path.exists(config.CONFIG_FILE))
        # a read-only visitor is refused before the body is parsed
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"TUNNEL_READONLY": True}, fh)
        before = open(config.CONFIG_FILE).read()
        self.assertEqual(self.req("POST", "/api/config", body, FWD)[0], 403)
        self.assertEqual(open(config.CONFIG_FILE).read(), before)
        os.remove(config.CONFIG_FILE)
        # the local caller can; and only "safe" is gated
        st, j = self.req("POST", "/api/config", body)
        self.assertEqual((st, j["value"]), (200, "safe"))


class ScanNowTests(_ServerCase):
    """T10: Scan now returns 202 immediately, a second click runs nothing extra, and the HTTP route
    can never request deletion even when the configured mode is safe."""

    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("PENDING_FILE", os.path.join(d, "pending.json")), ("PENDING_LOCK", os.path.join(d, "p.lock")),
                     ("PENDING_LOG", os.path.join(d, "p.log"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        pending._RUNNING.clear()
        self.addCleanup(pending._RUNNING.clear)

    def post_run(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/pending/run", body=b"{}", headers={"Content-Type": "application/json",
                                                                    "Content-Length": "2"})
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, json.loads(out)

    def test_scan_now_is_202_fast_single_flight_and_listonly(self):
        gate, started, modes = threading.Event(), threading.Event(), []

        def slow(mode=None, *a, **k):
            modes.append(mode)
            started.set()
            gate.wait(10)
            return {}
        self.addCleanup(gate.set)
        with mock.patch.object(config, "PENDING_CLEAN", "safe"), mock.patch.object(pending, "run_once", slow):
            t0 = time.monotonic()
            st, j = self.post_run()
            self.assertLess(time.monotonic() - t0, 0.2)         # never waits for the scan
            self.assertEqual((st, j), (202, {"running": True}))
            self.assertTrue(started.wait(5))
            st2, j2 = self.post_run()                           # second click while the scan runs
            self.assertEqual((st2, j2), (202, {"running": True}))
            gate.set()
            for _ in range(100):
                if not pending._RUNNING.is_set():
                    break
                time.sleep(0.05)
        self.assertEqual(modes, ["dry-run"])                    # one scan only, and never the configured "safe"


if __name__ == "__main__":
    unittest.main()
