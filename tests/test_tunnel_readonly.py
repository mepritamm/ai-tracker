#!/usr/bin/env python3
"""Tunnel read-only mode (TUNNEL_READONLY / TRACKER_TUNNEL_READONLY): server.Handler's single
choke point. Remote = any non-local caller (a proxy header OR a non-loopback peer); a local
caller is never read-only. When on: every POST is denied (right after auth, before the body is
parsed) and only an exact GET allow-list is served.

Proxied calls are simulated with `Cf-Connecting-Ip` (what cloudflared adds). The non-loopback
peer case uses a stub handler, since a real socket here is always 127.0.0.1. Config / state
files are redirected to a tempdir so no test touches the real pins/flags/notes."""
import json
import os
import tempfile
import unittest
from unittest import mock

import aitracker.config as config
from aitracker import server as _server
from aitracker.store import _save_json
from tests.test_tunnel import _ServerCase, _get, _post

PROXIED = {"Cf-Connecting-Ip": "1.2.3.4"}
CRED = "u:p"
RO_ERR = "read-only: this tracker is shared view-only"

_STATE = ("TITLES_FILE", "PINS_FILE", "FLAGS_FILE", "NOTES_FILE", "TITLE_SYNC_FILE", "MODEL_KEEP_FILE")

# Every mutating route (server.py POST chain + EXTRA_POST). Bodies are inert: if the choke point
# were missing these must still not do anything dangerous (term routes get `{}` -> 400).
POST_ROUTES = [
    ("/api/title", {"session": "s1", "title": "x"}),
    ("/api/config", {"key": "LIVE_WINDOW", "value": 120}),
    ("/api/tunnel", {"key": "TUNNEL_READONLY", "value": False}),
    ("/api/tunnel/ctl", {"action": "stop"}),
    ("/api/pin", {"session": "s1", "pinned": True}),
    ("/api/model-keep", {"session": "s1", "model": "m"}),
    ("/api/flags", {"session": "s1", "text": "t"}),
    ("/api/flags/resolve", {"session": "s1", "id": "1"}),
    ("/api/flags/delete", {"session": "s1", "id": "1"}),
    ("/api/notes", {"session": "s1", "text": "n"}),
    ("/api/notes/push", {"session": "s1", "id": "1"}),
    ("/api/notes/next", {"session": "s1"}),
    ("/api/notes/delete", {"session": "s1", "id": "1"}),
    ("/api/term/open", {}), ("/api/term/run", {}), ("/api/term/kill", {}), ("/api/term/pty", {}),
    ("/api/term/keys", {}), ("/api/term/resize", {}), ("/api/term/inject", {}), ("/api/term/close", {}),
]


class _RO(_ServerCase):
    def setUp(self):
        super().setUp()
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop("TRACKER_TUNNEL_READONLY", None)
        self._saved = {k: getattr(config, k) for k in _STATE if hasattr(config, k)}
        self.state = tempfile.mkdtemp()
        for k in self._saved:
            setattr(config, k, os.path.join(self.state, k + ".json"))
        self.addCleanup(self._restore_state)
        config.AUTH = CRED                    # tunnel.cred() falls back to AUTH's halves
        self.secret_file = os.path.join(self.state, "secret.txt")
        with open(self.secret_file, "w") as f:
            f.write("TOP-SECRET-CONTENT")

    def _restore_state(self):
        for k, v in self._saved.items():
            setattr(config, k, v)

    def _cfg(self):
        with open(config.CONFIG_FILE) as f:
            return json.load(f)

    def ro(self, value=True):
        _save_json(config.CONFIG_FILE, {"TUNNEL_READONLY": value})

    def get(self, path, proxied=True):
        return _get(self.port, path, cred=CRED, headers=PROXIED if proxied else None)

    def post(self, path, body, proxied=True):
        return _post(self.port, path, body, cred=CRED, headers=PROXIED if proxied else None)


class TestPostDenied(_RO):
    def test_every_post_is_403_and_nothing_written(self):
        self.ro()
        cfg_before = self._cfg()
        for path, body in POST_ROUTES:
            with self.subTest(path=path):
                st, data, _h = self.post(path, body)
                self.assertEqual(st, 403, path)
                d = json.loads(data)
                self.assertEqual(d["error"], RO_ERR)
                self.assertIs(d["readonly"], True)
        self.assertEqual(self._cfg(), cfg_before)
        for k in self._saved:
            self.assertFalse(os.path.exists(getattr(config, k)), k + " must not be written")

    def test_malformed_body_still_403_not_400(self):
        """Deny-all happens before the body is parsed."""
        self.ro()
        import http.client
        import base64
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", "/api/pin", body="{not json", headers={
            **PROXIED, "Authorization": "Basic " + base64.b64encode(CRED.encode()).decode()})
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 403)

    def test_cannot_disable_readonly_via_tunnel(self):
        self.ro()
        st, _d, _h = self.post("/api/tunnel", {"key": "TUNNEL_READONLY", "value": False})
        self.assertEqual(st, 403)
        self.assertIs(self._cfg()["TUNNEL_READONLY"], True)

    def test_unauthenticated_is_401_not_403(self):
        self.ro()
        st, _d, _h = _post(self.port, "/api/pin", {"session": "s"}, headers=PROXIED)
        self.assertEqual(st, 401)

    def test_login_still_works(self):
        self.ro()
        st, _d, _h = _post(self.port, "/login", {"user": "u", "pass": "p"}, headers=PROXIED)
        self.assertEqual(st, 200)


class TestGetAllowList(_RO):
    def test_file_route_blocked_and_secret_absent(self):
        self.ro()
        st, data, _h = self.get("/api/file?path=" + self.secret_file)
        self.assertEqual(st, 403)
        self.assertNotIn(b"TOP-SECRET-CONTENT", data)

    def test_reveal_and_term_gets_blocked(self):
        self.ro()
        for path in ("/api/tunnel/reveal", "/api/term/list", "/api/term/status", "/api/term/stream",
                     "/api/term/screen", "/api/term/raw", "/api/term/cwds"):
            with self.subTest(path=path):
                st, data, _h = self.get(path)
                self.assertEqual(st, 403)
                self.assertIs(json.loads(data)["readonly"], True)

    def test_unknown_get_is_403_not_404(self):
        self.ro()
        st, _d, _h = self.get("/api/not-a-route")
        self.assertEqual(st, 403)

    def test_allow_listed_gets_served(self):
        self.ro()
        for path in ("/", "/api/list", "/api/flags", "/api/tunnel", "/api/config"):
            with self.subTest(path=path):
                st, _d, _h = self.get(path)
                self.assertEqual(st, 200, path)

    def test_session_route_reaches_its_handler(self):
        """Allow-listed -> the route's own 404 for an unknown id, not the read-only 403."""
        self.ro()
        st, _d, _h = self.get("/api/session?id=no-such-session")
        self.assertEqual(st, 404)

    def test_vendor_exact_paths_served_via_tunnel(self):
        self.ro()
        for name in ("xterm.js", "xterm.css", "addon-fit.js", "mermaid.min.js"):
            with self.subTest(name=name):
                st, _d, _h = self.get("/vendor/" + name)
                self.assertEqual(st, 200, name)

    def test_other_vendor_path_blocked(self):
        self.ro()
        st, _d, _h = self.get("/vendor/anything-else.js")
        self.assertEqual(st, 403)

    def test_login_page_for_unauthenticated(self):
        self.ro()
        st, _d, _h = _get(self.port, "/", headers=PROXIED)     # no cred -> styled login page
        self.assertEqual(st, 200)

    def test_unauthenticated_api_is_401(self):
        self.ro()
        st, _d, _h = _get(self.port, "/api/list", headers=PROXIED)
        self.assertEqual(st, 401)


class TestListHeader(_RO):
    def test_list_sets_header_and_skips_term_count(self):
        self.ro()
        with mock.patch.object(_server, "_term_count", side_effect=AssertionError("must not be called")):
            st, _d, h = self.get("/api/list")
        self.assertEqual(st, 200)
        self.assertEqual(h.get("X-Read-Only"), "1")
        self.assertNotIn("X-Term-Count", h)

    def test_header_absent_locally_even_when_on(self):
        self.ro()
        st, _d, h = self.get("/api/list", proxied=False)
        self.assertEqual(st, 200)
        self.assertNotIn("X-Read-Only", h)

    def test_header_absent_when_off(self):
        st, _d, h = self.get("/api/list")
        self.assertEqual(st, 200)
        self.assertNotIn("X-Read-Only", h)


class TestFailClosed(_RO):
    def test_corrupt_config_is_readonly(self):
        with open(config.CONFIG_FILE, "w") as f:
            f.write("{not json")
        st, data, _h = self.post("/api/pin", {"session": "s"})
        self.assertEqual(st, 403)
        self.assertIs(json.loads(data)["readonly"], True)

    def test_corrupt_config_tunnel_status_reports_readonly(self):
        with open(config.CONFIG_FILE, "w") as f:
            f.write("{not json")
        st, data, _h = self.get("/api/tunnel", proxied=False)
        self.assertEqual(st, 200)
        self.assertIs(json.loads(data)["readonly"], True)

    def test_non_dict_config_is_readonly_but_list_served(self):
        with open(config.CONFIG_FILE, "w") as f:
            f.write("[]")
        st, _d, h = self.get("/api/list")
        self.assertEqual(st, 200)
        self.assertEqual(h.get("X-Read-Only"), "1")
        self.assertEqual(self.post("/api/pin", {"session": "s"})[0], 403)

    def test_string_true_is_readonly(self):
        self.ro("true")
        self.assertEqual(self.post("/api/pin", {"session": "s"})[0], 403)

    def test_env_floor_beats_config_false(self):
        self.ro(False)
        os.environ["TRACKER_TUNNEL_READONLY"] = "1"
        self.assertEqual(self.post("/api/pin", {"session": "s"})[0], 403)

    def test_missing_config_file_is_not_readonly(self):
        self.assertFalse(os.path.exists(config.CONFIG_FILE))
        self.assertEqual(_server._load_config_strict(), {})
        self.assertEqual(self.post("/api/pin", {"session": "s"})[0], 200)

    def test_strict_loader_raises_on_bad_files(self):
        for text in ("{not json", "[]", '"x"'):
            with open(config.CONFIG_FILE, "w") as f:
                f.write(text)
            with self.subTest(text=text), self.assertRaises((ValueError, OSError)):
                _server._load_config_strict()

    def test_readonly_exception_fails_closed(self):
        class H:
            client_address = ("1.2.3.4", 1)
            headers = {}
        with mock.patch.object(_server, "_load_config_strict", side_effect=RuntimeError("boom")):
            self.assertTrue(_server.Handler._readonly(H()))


class TestCallerIdentity(_RO):
    """Remote = proxy header OR non-loopback peer. Local is never read-only."""

    class _Stub:
        def __init__(self, ip, headers=None):
            self.client_address = (ip, 5555)
            self.headers = headers or {}

    def test_non_loopback_peer_without_headers_is_readonly(self):
        self.ro()
        self.assertTrue(_server.Handler._readonly(self._Stub("192.168.1.5")))

    def test_non_loopback_peer_when_off_is_not(self):
        self.assertFalse(_server.Handler._readonly(self._Stub("192.168.1.5")))

    def test_loopback_without_headers_never_readonly(self):
        self.ro()
        os.environ["TRACKER_TUNNEL_READONLY"] = "1"
        self.assertFalse(_server.Handler._readonly(self._Stub("127.0.0.1")))

    def test_loopback_with_proxy_header_is_readonly(self):
        self.ro()
        self.assertTrue(_server.Handler._readonly(self._Stub("127.0.0.1", {"X-Forwarded-For": "9.9.9.9"})))

    def test_local_caller_lives_in_server_and_is_aliased_in_term_launch(self):
        from aitracker import term_launch
        self.assertIs(term_launch._local_caller, _server._local_caller)
        self.assertIs(term_launch._PROXY_HEADERS, _server._PROXY_HEADERS)


class TestGuards(_RO):
    def test_default_off_allows_proxied_post(self):
        self.assertEqual(self.post("/api/pin", {"session": "s1", "pinned": True})[0], 200)

    def test_localhost_post_ok_when_on(self):
        self.ro()
        self.assertEqual(self.post("/api/pin", {"session": "s1", "pinned": True}, proxied=False)[0], 200)

    def test_localhost_file_ok_when_on(self):
        self.ro()
        st, data, _h = self.get("/api/file?path=" + self.secret_file, proxied=False)
        self.assertEqual(st, 200)
        self.assertIn(b"TOP-SECRET-CONTENT", data)

    def test_validator_rejects_non_bool(self):
        st, _d, _h = self.post("/api/tunnel", {"key": "TUNNEL_READONLY", "value": "yes"}, proxied=False)
        self.assertEqual(st, 400)

    def test_config_route_rejects_the_key(self):
        st, _d, _h = self.post("/api/config", {"key": "TUNNEL_READONLY", "value": True}, proxied=False)
        self.assertEqual(st, 400)

    def test_tunnel_post_echoes_value_and_locked(self):
        st, d, _h = self.post("/api/tunnel", {"key": "TUNNEL_READONLY", "value": True}, proxied=False)
        self.assertEqual(st, 200)
        j = json.loads(d)
        self.assertIs(j["value"], True)
        self.assertIs(j["locked"], False)
        self.assertIs(j["restart"], False)

    def test_env_lock_reported_and_value_cannot_be_lowered(self):
        os.environ["TRACKER_TUNNEL_READONLY"] = "1"
        st, d, _h = self.post("/api/tunnel", {"key": "TUNNEL_READONLY", "value": False}, proxied=False)
        self.assertEqual(st, 200)
        j = json.loads(d)
        self.assertIs(j["value"], True)
        self.assertIs(j["locked"], True)

    def test_tunnel_public_reports_readonly_and_env_lock(self):
        d = json.loads(self.get("/api/tunnel", proxied=False)[1])
        self.assertIs(d["readonly"], False)
        self.assertIs(d["readonly_env"], False)
        os.environ["TRACKER_TUNNEL_READONLY"] = "1"
        d = json.loads(self.get("/api/tunnel", proxied=False)[1])
        self.assertIs(d["readonly"], True)
        self.assertIs(d["readonly_env"], True)


if __name__ == "__main__":
    unittest.main()
