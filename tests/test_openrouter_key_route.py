"""POST /api/config for OPENROUTER_API_KEY: local-only, 0600 from the first byte, never echoed, never published
(GET /api/config, /api/file under a rebinding Host, every usage/auth/agent route), never in os.environ or the plist."""
import http.client
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import accounts, config, schedule
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase
from tests.test_pending_routes_matrix import _RemotePeer, FWD

KEY = "sk-or-v1-LEAKSENTINEL0123456789"


class _Resp:
    def read(self, n=-1):
        return json.dumps({"data": {"label": KEY, "usage": 1}}).encode()

    def close(self):
        pass


class _Opener:
    def open(self, req, timeout=None):
        return _Resp()


class KeyRouteTests(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("AUTH", ""), ("CONFIG_FILE", os.path.join(d, "config.json"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        for name, val in (("claude_usage", {"state": "ok", "limits": []}), ("claude_auth_status", {"label": "x"}),
                          ("auggie_auth_status", {"available": True}), ("agent_status", {"agents": []})):
            p = mock.patch.object(_server, name, return_value=val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(accounts, "_acct_open", return_value=_Opener())
        p.start()
        self.addCleanup(p.stop)
        accounts.usage_invalidate("openrouter")
        self.addCleanup(accounts.usage_invalidate, "openrouter")
        self.remote = _server.Server(("127.0.0.1", 0), _RemotePeer)
        self.addCleanup(self.remote.server_close)
        threading.Thread(target=self.remote.serve_forever, daemon=True).start()
        self.addCleanup(self.remote.shutdown)

    def call(self, method, path, body=None, headers=None, port=None):
        c = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=5)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body)
            h.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, raw

    def post_key(self, value=KEY, **kw):
        return self.call("POST", "/api/config", {"key": "OPENROUTER_API_KEY", "value": value}, **kw)

    def cfg_text(self):
        with open(config.CONFIG_FILE) as fh:
            return fh.read()

    def cfg(self):
        return json.loads(self.cfg_text())

    def mode(self):
        return stat.S_IMODE(os.stat(config.CONFIG_FILE).st_mode)

    def test_local_post_stores_key_0600_and_never_echoes(self):
        st, raw = self.post_key()
        self.assertEqual(st, 200)
        j = json.loads(raw)
        self.assertEqual((j["ok"], j["key"], j["set"], j["file"]), (True, "OPENROUTER_API_KEY", True, config.CONFIG_FILE))
        self.assertNotIn(KEY.encode(), raw)
        self.assertEqual(self.cfg()["OPENROUTER_API_KEY"], KEY)
        self.assertEqual(self.mode(), 0o600)

    def test_0600_survives_a_later_ordinary_write_under_umask_022(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        self.post_key()
        st, _ = self.call("POST", "/api/config", {"key": "LIVE_WINDOW", "value": 120})
        self.assertEqual(st, 200)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.cfg()["OPENROUTER_API_KEY"], KEY)

    def test_clear_and_bad_values(self):
        self.post_key()
        st, raw = self.post_key("")
        self.assertEqual((st, json.loads(raw)["set"]), (200, False))
        self.assertNotIn("OPENROUTER_API_KEY", self.cfg())
        for bad in ("short", "has space in it 0123456789", "line\r\nbreak0123456789ab", 5, None, "x" * 300):
            with self.subTest(bad=repr(bad)[:20]):
                st, raw = self.post_key(bad)
                self.assertEqual(st, 400)
                self.assertNotIn(b"has space", raw)
        self.assertNotIn("OPENROUTER_API_KEY", self.cfg())

    def test_refused_callers_leave_the_file_untouched(self):
        before = None
        cases = (("remote peer", {}, self.remote.server_address[1]), ("forwarded", FWD, None),
                 ("cross origin", {"Origin": "http://evil.example"}, None))
        for name, h, port in cases:
            with self.subTest(name):
                st, raw = self.post_key(headers=h, port=port)
                self.assertEqual(st, 403)
                self.assertNotIn(KEY.encode(), raw)
                self.assertFalse(os.path.exists(config.CONFIG_FILE))
        with open(config.CONFIG_FILE, "w") as fh:
            json.dump({"TUNNEL_READONLY": True}, fh)
        before = self.cfg_text()
        st, _ = self.post_key(headers=FWD)
        self.assertEqual(st, 403)
        self.assertEqual(self.cfg_text(), before)

    def test_key_is_not_an_editable_setting(self):
        self.assertNotIn("OPENROUTER_API_KEY", config.EDITABLE)
        self.post_key()
        st, raw = self.call("GET", "/api/config")
        self.assertEqual(st, 200)
        self.assertNotIn(KEY.encode(), raw)
        self.assertNotIn(b"OPENROUTER_API_KEY", raw)

    def test_key_never_leaks_through_any_route(self):
        self.post_key()
        paths = ("/api/config", "/api/tunnel", "/api/usage/claude", "/api/usage/openrouter",
                 "/api/usage/openrouter?peek=1", "/api/usage/openrouter?fresh=1", "/api/usage/auggie", "/api/auggie/auth",
                 "/api/claude/auth", "/api/agents")
        for p in paths:
            with self.subTest(p):
                st, raw = self.call("GET", p)
                self.assertNotIn(KEY.encode(), raw)
                self.assertNotIn(b"LEAKSENTINEL", raw)
        accounts._OR._th and accounts._OR._th.join(5)

    def test_api_file_refuses_a_rebinding_host(self):
        self.post_key()
        q = "/api/file?path=" + config.CONFIG_FILE
        st, raw = self.call("GET", q, headers={"Host": "rebind.example:%d" % self.port})
        self.assertEqual(st, 403)
        self.assertNotIn(KEY.encode(), raw)
        st, raw = self.call("GET", q, headers={"Host": "localhost:%d" % self.port})
        self.assertEqual(st, 200)

    def test_key_never_reaches_environ_or_plist(self):
        self.post_key()
        self.assertFalse(any(KEY in v for v in os.environ.values()))
        self.assertNotIn(KEY.encode(), schedule.service_plist(8790, "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
