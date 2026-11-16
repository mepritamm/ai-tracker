"""GET /api/claude/auth: local callers only, never in _RO_GET_ALLOW, status call stubbed (never the real CLI),
no identifying key ever reaches the body."""
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

OK = {"available": True, "logged_in": True, "auth_method": "claude.ai", "subscription": "max",
      "label": "Logged in", "error": ""}
PATH = "/api/claude/auth"


class AuthRouteTests(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("AUTH", ""), ("CONFIG_FILE", os.path.join(d, "config.json"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        m = mock.patch.object(_server, "claude_auth_status", return_value=dict(OK))
        self.stub = m.start()
        self.addCleanup(m.stop)
        self.remote = _server.Server(("127.0.0.1", 0), _RemotePeer)
        self.addCleanup(self.remote.server_close)
        threading.Thread(target=self.remote.serve_forever, daemon=True).start()
        self.addCleanup(self.remote.shutdown)

    def req(self, path=PATH, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=5)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        out = r.read()
        c.close()
        try:
            return r.status, json.loads(out)
        except ValueError:
            return r.status, {}

    def test_local_200(self):
        st, j = self.req()
        self.assertEqual((st, j), (200, OK))
        self.stub.assert_called_once_with(fresh=False)

    def test_fresh_passes_through(self):
        self.assertEqual(self.req(PATH + "?fresh=1")[0], 200)
        self.stub.assert_called_once_with(fresh=True)
        self.stub.reset_mock()
        self.req(PATH + "?fresh=0")
        self.stub.assert_called_once_with(fresh=False)

    def test_refused_callers_never_call_status(self):
        cases = (("foreign host", {"Host": "evil.example"}, None),
                 ("cross origin", {"Origin": "http://evil.example"}, None),
                 ("proxy header", FWD, None),
                 ("tunnel", dict(CF, Authorization="Basic dHU6dHA="), None),
                 ("non-local peer", {}, self.remote.server_address[1]))
        for name, h, port in cases:
            with self.subTest(name), mock.patch.object(_server.tunnel, "cred", return_value="tu:tp"):
                self.assertEqual(self.req(headers=h, port=port)[0], 403)
        self.stub.assert_not_called()

    def test_readonly_visitor_refused(self):
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"TUNNEL_READONLY": True}, fh)
        st, j = self.req(headers=FWD)
        self.assertEqual(st, 403)
        self.assertTrue(j.get("readonly"))
        self.stub.assert_not_called()

    def test_not_in_ro_allow(self):
        self.assertNotIn(PATH, _server._RO_GET_ALLOW)

    def test_no_identifying_key_in_body(self):
        self.stub.return_value = dict(OK, email="a@b.c", org="Acme", orgId="o1", accountUuid="u1", userId="x")
        st, j = self.req()
        self.assertEqual(st, 200)
        self.assertEqual(set(j), set(OK))
        for bad in ("a@b.c", "Acme", "o1", "u1"):
            self.assertNotIn(bad, json.dumps(j))


if __name__ == "__main__":
    unittest.main()
