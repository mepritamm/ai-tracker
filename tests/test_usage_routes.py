"""The four usage GET routes: local AND same-site callers only, never in _RO_GET_ALLOW, backends stubbed."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import config
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase
from tests.test_pending_routes_matrix import _RemotePeer, FWD, CF

ROUTES = {"/api/usage/claude": "claude_usage", "/api/usage/openrouter": "openrouter_usage",
          "/api/usage/auggie": "auggie_usage", "/api/auggie/auth": "auggie_auth_status"}


class UsageRouteTests(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("AUTH", ""), ("CONFIG_FILE", os.path.join(d, "config.json"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.stubs = {}
        for name in list(ROUTES.values()) + ["openrouter_peek"]:
            m = mock.patch.object(_server, name, return_value={"stub": name})
            self.stubs[name] = m.start()
            self.addCleanup(m.stop)
        self.remote = _server.Server(("127.0.0.1", 0), _RemotePeer)
        self.addCleanup(self.remote.server_close)
        threading.Thread(target=self.remote.serve_forever, daemon=True).start()
        self.addCleanup(self.remote.shutdown)

    def req(self, path, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=5)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        out = r.read()
        c.close()
        try:
            return r.status, json.loads(out)
        except ValueError:
            return r.status, {}

    def calls(self):
        return sum(m.call_count for m in self.stubs.values())

    def test_local_200(self):
        for path, name in ROUTES.items():
            with self.subTest(path):
                self.assertEqual(self.req(path), (200, {"stub": name}))

    def test_refused_callers_never_reach_a_backend(self):
        cases = (("foreign host", {"Host": "evil.example"}, None), ("cross origin", {"Origin": "http://evil.example"}, None),
                 ("proxy header", FWD, None), ("non-local peer", {}, self.remote.server_address[1]),
                 ("cross-site fetch", {"Sec-Fetch-Site": "cross-site"}, None),
                 ("same-site fetch", {"Sec-Fetch-Site": "same-site"}, None))
        for path in ROUTES:
            for name, h, port in cases:
                with self.subTest(path=path, case=name), mock.patch.object(_server.tunnel, "cred", return_value="tu:tp"):
                    self.assertEqual(self.req(path, headers=h, port=port)[0], 403)
        self.assertEqual(self.calls(), 0)

    def test_same_origin_and_none_are_allowed(self):
        for hv in ("same-origin", "none"):
            for path in ROUTES:
                with self.subTest(hv=hv, path=path):
                    self.assertEqual(self.req(path, headers={"Sec-Fetch-Site": hv})[0], 200)

    def test_readonly_visitor_refused(self):
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"TUNNEL_READONLY": True}, fh)
        for path in ROUTES:
            with self.subTest(path):
                st, j = self.req(path, headers=FWD)
                self.assertEqual(st, 403)
                self.assertTrue(j.get("readonly"))
        self.assertEqual(self.calls(), 0)

    def test_none_is_in_ro_allow(self):
        for path in ROUTES:
            self.assertNotIn(path, _server._RO_GET_ALLOW)

    def test_fresh_and_peek_pass_through(self):
        self.req("/api/usage/claude?fresh=1")
        self.stubs["claude_usage"].assert_called_once_with(True)
        self.req("/api/usage/claude")
        self.stubs["claude_usage"].assert_called_with(False)
        self.req("/api/usage/openrouter?fresh=1")
        self.stubs["openrouter_usage"].assert_called_once_with(True)
        self.req("/api/auggie/auth?fresh=1")
        self.stubs["auggie_auth_status"].assert_called_once_with(True)
        self.assertEqual(self.req("/api/usage/openrouter?peek=1"), (200, {"stub": "openrouter_peek"}))
        self.assertEqual(self.stubs["openrouter_usage"].call_count, 1)


if __name__ == "__main__":
    unittest.main()
