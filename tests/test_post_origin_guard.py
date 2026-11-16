"""Every POST route refuses a cross-origin / `Origin: null` request with 403 (CSRF), with and without
TRACKER_AUTH; an absent or matching Origin is not refused; GET is untouched."""
import base64
import http.client
import json
import unittest
from unittest import mock

from aitracker import config
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase


class PostOriginTests(_ServerCase):
    def req(self, method, path, payload=None, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": "127.0.0.1:%d" % self.port}
        if origin is not None:
            h["Origin"] = origin
        if config.AUTH:
            h["Authorization"] = "Basic " + base64.b64encode(config.AUTH.encode()).decode()
        body = None
        if method == "POST":
            body = json.dumps(payload or {}).encode()
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    def test_cross_origin_post_refused(self):
        for auth in ("", "u:p"):
            with mock.patch.object(config, "AUTH", auth):
                for o in ("http://evil.example", "null"):
                    for path in ("/api/pin", "/login"):
                        st, data = self.req("POST", path, {"session": "x", "pinned": False}, origin=o)
                        self.assertEqual(st, 403, (auth, o, path))
                        self.assertIn("cross-origin", data.decode(), (auth, o, path))

    def test_same_or_absent_origin_not_refused(self):
        for auth in ("", "u:p"):
            with mock.patch.object(config, "AUTH", auth):
                for o in (None, "http://127.0.0.1:%d" % self.port):
                    for path in ("/api/pin", "/login"):
                        st, _d = self.req("POST", path, {"session": "x", "pinned": False}, origin=o)
                        self.assertNotEqual(st, 403, (auth, o, path))

    def test_get_with_bad_origin_unchanged(self):
        st, _d = self.req("GET", "/api/list", origin="http://evil.example")
        self.assertNotEqual(st, 403)

    def test_tunnel_ctl_cross_origin_with_credential(self):
        with mock.patch.object(config, "AUTH", "u:p"), mock.patch.object(_server.tunnel, "stop") as stop:
            st, _d = self.req("POST", "/api/tunnel/ctl", {"action": "stop"}, origin="http://evil.example")
        self.assertEqual(st, 403)
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
