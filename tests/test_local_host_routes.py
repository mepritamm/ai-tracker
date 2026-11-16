"""_local_caller refuses a non-loopback Host (DNS rebinding) on every local-only route family;
loopback Hosts still work. Same policy as term_gate.guard: not applied when TRACKER_AUTH is set."""
import http.client
import json
import os
import tempfile
import unittest
from unittest import mock

from aitracker import config
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase

ROUTES = (("GET", "/api/pending"), ("GET", "/api/pending/item?id=x"), ("POST", "/api/pending/run"),
          ("GET", "/api/scheduler"), ("POST", "/api/scheduler"), ("GET", "/api/update"),
          ("POST", "/api/update/fetch"), ("POST", "/api/update/apply"),
          ("GET", "/api/service"), ("POST", "/api/service"))


class HostTests(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("PENDING_FILE", os.path.join(d, "pending.json")), ("PENDING_LOCK", os.path.join(d, "p.lock")),
                     ("PENDING_LOG", os.path.join(d, "p.log")), ("AUTH", ""),
                     ("CONFIG_FILE", os.path.join(d, "config.json"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        for n, rv in (("run_async", False), ("update_fetch", {}), ("update_apply", (200, {})),
                      ("sched_install", 0), ("sched_uninstall", 0), ("start_restart", None),
                      ("svc_install", 0), ("svc_uninstall", 0), ("svc_spawn_deferred", None)):
            p = mock.patch.object(_server, n, return_value=rv)
            p.start()
            self.addCleanup(p.stop)
        for n in ("update_status", "_sched_body", "_svc_body"):
            p = mock.patch.object(_server, n, return_value={})
            p.start()
            self.addCleanup(p.stop)

    def req(self, method, path, host, payload=None, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload or {}).encode() if method == "POST" else None
        h = {"Host": host}
        if origin is not None:
            h["Origin"] = origin
        if config.AUTH:
            import base64
            h["Authorization"] = "Basic " + base64.b64encode(config.AUTH.encode()).decode()
        if body is not None:
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_foreign_host_refused_everywhere(self):
        for m, p in ROUTES:
            self.assertEqual(self.req(m, p, "evil.example", {"action": "install"}), 403, p)
            self.assertEqual(self.req(m, p, "evil.example:%d" % self.port, {"action": "install"}), 403, p)

    def test_config_safe_refused_for_foreign_host(self):
        self.assertEqual(self.req("POST", "/api/config", "evil.example", {"key": "PENDING_CLEAN", "value": "safe"}), 403)

    def test_loopback_hosts_still_work(self):
        for host in ("localhost:%d" % self.port, "127.0.0.1:%d" % self.port):
            for m, p in ROUTES:
                self.assertNotEqual(self.req(m, p, host, {"action": "install"}), 403, (host, p))

    def _origins(self):
        hp = "127.0.0.1:%d" % self.port
        return hp, ("http://evil.example", "null", "http://localhost:9999", "http://127.0.0.1:%d" % (self.port + 1),
                    "http://evil.example:%d" % self.port)

    def test_cross_origin_refused_everywhere(self):
        hp, bad = self._origins()
        for auth in ("", "u:p"):
            with mock.patch.object(config, "AUTH", auth):
                for o in bad:
                    for m, p in ROUTES:
                        self.assertEqual(self.req(m, p, hp, {"action": "install"}, origin=o), 403, (auth, o, p))
                    self.assertEqual(self.req("POST", "/api/config", hp,
                                              {"key": "PENDING_CLEAN", "value": "safe"}, origin=o), 403, (auth, o))
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

    def test_same_origin_and_absent_origin_allowed(self):
        hp, _bad = self._origins()
        for o in (None, "http://" + hp):
            for m, p in ROUTES:
                self.assertNotEqual(self.req(m, p, hp, {"action": "install"}, origin=o), 403, (o, p))
            self.assertEqual(self.req("POST", "/api/config", hp, {"key": "PENDING_CLEAN", "value": "safe"},
                                      origin=o), 200, o)

    def test_tunnel_routes_cross_origin_and_foreign_host(self):
        hp, bad = self._origins()
        routes = (("GET", "/api/tunnel/reveal"), ("POST", "/api/tunnel/ctl"))
        with mock.patch.object(_server.tunnel, "stop"):
            for m, p in routes:
                for o in bad:
                    self.assertEqual(self.req(m, p, hp, {"action": "stop"}, origin=o), 403, (p, o))
                self.assertEqual(self.req(m, p, "evil.example", {"action": "stop"}), 403, p)
                for o in (None, "http://" + hp):
                    self.assertNotEqual(self.req(m, p, hp, {"action": "stop"}, origin=o), 403, (p, o))

    def test_tunnel_routes_unchanged_with_login(self):
        with mock.patch.object(config, "AUTH", "u:p"), mock.patch.object(_server.tunnel, "stop"):
            h = {"Host": "x.trycloudflare.com", "Authorization": "Basic dTpw"}
            for m, p in (("GET", "/api/tunnel/reveal"), ("POST", "/api/tunnel/ctl")):
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                body = b'{"action":"stop"}' if m == "POST" else None
                c.request(m, p, body=body, headers=h)
                r = c.getresponse()
                r.read()
                c.close()
                self.assertNotEqual(r.status, 403, p)

    def test_with_login_foreign_host_not_refused_by_the_host_check(self):
        with mock.patch.object(config, "AUTH", "u:p"):
            ok, _e = _server._local_caller(type("H", (), {"headers": {"Host": "x.trycloudflare.com"},
                                                         "client_address": ("127.0.0.1", 1)})())
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
