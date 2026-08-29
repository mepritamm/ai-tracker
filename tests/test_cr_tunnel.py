#!/usr/bin/env python3
"""Tunnel management section of the Config dialog: GET /api/tunnel (masked default read),
GET /api/tunnel/reveal (the one deliberate route that returns the raw credential), and
POST /api/tunnel (stages an edit into config.json). See aitracker/config.py's "Tunnel
management" section for the design rationale and aitracker/server.py's three routes.

Owned files for this feature: aitracker/config.py, aitracker/server.py,
aitracker/web/ext_cr_dialogs.js, aitracker/web/ext_cr_dialogs.css, and this test file.

TRACKER_AUTH is exported in the dev shell that runs this suite (it would otherwise make
every server call below 401 unless neutralised) -- same fix tests/test_integration.py's
TestBasicAuth already uses: read-and-restore config.AUTH directly as a plain module
attribute (it is read live by the Handler on every request) rather than touching the
process environment. Ephemeral port via Server(("127.0.0.1", 0), ...); every server is
torn down via addCleanup, never left running; config.json is repointed at a tempfile.mktemp()
path per test so the repo's real config.json is never touched (confirmed clean via
`git status --short` after this file's own run -- see the report)."""
import base64
import http.client
import json
import os
import tempfile
import threading
import unittest

import aitracker.config as config
from aitracker import server as _server


def _get(port, path, cred=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdr = {}
    if cred is not None:
        hdr["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    c.request("GET", path, headers=hdr)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


def _post(port, path, body, cred=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdr = {"Content-Type": "application/json"}
    if cred is not None:
        hdr["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    c.request("POST", path, body=json.dumps(body), headers=hdr)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data


class _TunnelServerCase(unittest.TestCase):
    """Shared server-lifecycle plumbing. Subclasses set self._auth to whatever
    config.AUTH should be for their scenario before the server starts accepting requests."""
    _auth = ""   # override in a subclass for the "auth is configured" scenarios

    def setUp(self):
        self._auth0 = config.AUTH
        self._cfgfile0 = config.CONFIG_FILE
        config.CONFIG_FILE = tempfile.mktemp(suffix=".json")   # never the repo's real file
        config.AUTH = self._auth
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.srv.shutdown()
        self.srv.server_close()
        try:
            os.remove(config.CONFIG_FILE)
        except OSError:
            pass
        config.AUTH = self._auth0
        config.CONFIG_FILE = self._cfgfile0


class TestTunnelConfigNoAuth(_TunnelServerCase):
    """No TRACKER_AUTH configured -- every route here is reachable with no credential,
    same baseline TestBasicAuth.test_default_off_lets_all_through already establishes for
    every OTHER route."""
    _auth = ""

    def test_reports_not_set_honestly_when_nothing_is_staged(self):
        """Requirement 6/4th test bucket: "not set" must be the real, unfabricated state --
        never guessed, never defaulted to something that looks configured."""
        st, body = _get(self.port, "/api/tunnel")
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual(d, {"url": "", "user_set": False, "pass_set": False, "auth_set": False})

    def test_post_rejects_a_malformed_username(self):
        """3rd test bucket: validation rejects a malformed user:pass. A username containing
        ':' would make the "user:pass" TRACKER_AUTH round trip ambiguous, so it's a 400,
        and -- just as important -- nothing must reach disk on a rejected write."""
        st, body = _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "bad:name"})
        self.assertEqual(st, 400)
        self.assertIn("error", json.loads(body))
        self.assertFalse(os.path.exists(config.CONFIG_FILE), "a rejected value must never touch disk")

    def test_post_rejects_an_unknown_key(self):
        """Defense in depth: TUNNEL_USER/TUNNEL_PASS live on their OWN allowlist
        (config.TUNNEL_EDITABLE), never config.EDITABLE -- confirms a bogus/foreign key
        (including a literal "TRACKER_AUTH", which must never be writable from here either,
        same invariant test_selfcheck.py already pins for the general /api/config route)
        can't slip through this route."""
        for bad_key in ("NOT_A_REAL_KEY", "TRACKER_AUTH", "PORT"):
            with self.subTest(key=bad_key):
                st, body = _post(self.port, "/api/tunnel", {"key": bad_key, "value": "x"})
                self.assertEqual(st, 400)

    def test_post_accepts_a_wellformed_username_and_never_echoes_it_in_the_public_read(self):
        st, _ = _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "alice"})
        self.assertEqual(st, 200)
        st2, body2 = _get(self.port, "/api/tunnel")
        self.assertEqual(st2, 200)
        d = json.loads(body2)
        self.assertTrue(d["user_set"])
        self.assertNotIn(b"alice", body2, "the non-reveal read must never carry the raw value")

    def test_config_json_is_0600_after_writing_a_credential(self):
        """1st test bucket: the single most important defence. A fresh temp path starts
        with the OS/umask default mode; writing a credential through this route must lock
        it down to owner-only immediately."""
        before_mode = None
        st, _ = _post(self.port, "/api/tunnel", {"key": "TUNNEL_PASS", "value": "s3cret"})
        self.assertEqual(st, 200)
        self.assertTrue(os.path.exists(config.CONFIG_FILE))
        mode = os.stat(config.CONFIG_FILE).st_mode & 0o777
        self.assertEqual(oct(mode), "0o600", "config.json must be owner-only once it can hold a credential")

    def test_url_only_write_also_gets_0600(self):
        """The mode is asserted unconditionally, not just on a USER/PASS write -- a URL-only
        edit must not leave config.json at a looser mode than a previous credential write set."""
        st, _ = _post(self.port, "/api/tunnel", {"key": "TUNNEL_URL", "value": "https://foo.trycloudflare.com"})
        self.assertEqual(st, 200)
        mode = os.stat(config.CONFIG_FILE).st_mode & 0o777
        self.assertEqual(oct(mode), "0o600")

    def test_reveal_returns_raw_values_restart_cmd_and_share_url(self):
        _post(self.port, "/api/tunnel", {"key": "TUNNEL_URL", "value": "https://foo.trycloudflare.com"})
        _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "alice"})
        _post(self.port, "/api/tunnel", {"key": "TUNNEL_PASS", "value": "s3cret"})
        st, body = _get(self.port, "/api/tunnel/reveal")
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual(d["user"], "alice")
        self.assertEqual(d["pass"], "s3cret")
        self.assertIn("alice:s3cret", d["restart_cmd"])
        self.assertIn("make tunnel", d["restart_cmd"])
        # requirement 5: standard userinfo form, never a query string
        self.assertEqual(d["share_url"], "https://alice:s3cret@foo.trycloudflare.com")
        self.assertNotIn("?", d["share_url"])
        self.assertNotIn("=", d["share_url"])

    def test_reveal_masks_nothing_but_the_public_route_still_never_leaks(self):
        _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "alice"})
        _post(self.port, "/api/tunnel", {"key": "TUNNEL_PASS", "value": "s3cret"})
        st, body = _get(self.port, "/api/tunnel")
        self.assertEqual(st, 200)
        self.assertNotIn(b"s3cret", body)

    def test_editing_user_or_pass_reports_restart_required_url_does_not(self):
        st, body = _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "alice"})
        self.assertTrue(json.loads(body)["restart"])
        st, body = _post(self.port, "/api/tunnel", {"key": "TUNNEL_URL", "value": "https://x.trycloudflare.com"})
        self.assertFalse(json.loads(body)["restart"])

    def test_tunnel_user_defaults_from_current_auth_when_nothing_staged(self):
        """No override in config.json yet -- the dialog's first paint should reflect
        whatever TRACKER_AUTH is ALREADY active, not a blank field next to an unlocked
        padlock. (config.AUTH is a plain module global here, same idiom as MAX_TERMS.)"""
        config.AUTH = "carol:hunter2"
        try:
            # config.AUTH is read live, so it now also gates this very request -- present it.
            st, body = _get(self.port, "/api/tunnel/reveal", cred="carol:hunter2")
            self.assertEqual(st, 200)
            d = json.loads(body)
            self.assertEqual(d["user"], "carol")
            self.assertEqual(d["pass"], "hunter2")
        finally:
            config.AUTH = ""


class TestTunnelConfigWithAuth(_TunnelServerCase):
    """TRACKER_AUTH is configured -- proves the reveal/write routes are gated by the app's
    own existing auth exactly like every other route, per requirement 7 (a bypass here would
    be a genuine hole, not a cosmetic gap)."""
    _auth = "opuser:opsecret"     # the CURRENT login credential, deliberately different from
                                  # the tunnel credential being staged below, so a test that
                                  # accidentally mixes the two up would fail loudly.

    def _stage(self):
        # Authenticated as the current operator -- staging a DIFFERENT, new credential for
        # the tunnel (the thing a restart would later promote to TRACKER_AUTH).
        st, _ = _post(self.port, "/api/tunnel", {"key": "TUNNEL_USER", "value": "bob"}, cred=self._auth)
        self.assertEqual(st, 200)
        st, _ = _post(self.port, "/api/tunnel", {"key": "TUNNEL_PASS", "value": "h4x0r"}, cred=self._auth)
        self.assertEqual(st, 200)

    def test_reveal_401s_with_no_credential_and_never_leaks_the_value(self):
        """2nd test bucket: an unauthenticated caller cannot read the credential back."""
        self._stage()
        st, body = _get(self.port, "/api/tunnel/reveal")     # no Authorization header at all
        self.assertEqual(st, 401)
        self.assertNotIn(b"h4x0r", body)
        self.assertNotIn(b"bob", body)

    def test_reveal_401s_with_wrong_credential(self):
        self._stage()
        st, body = _get(self.port, "/api/tunnel/reveal", cred="opuser:wrongpass")
        self.assertEqual(st, 401)
        self.assertNotIn(b"h4x0r", body)

    def test_reveal_200s_with_the_correct_current_credential(self):
        self._stage()
        st, body = _get(self.port, "/api/tunnel/reveal", cred=self._auth)
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual(d["user"], "bob")
        self.assertEqual(d["pass"], "h4x0r")

    def test_public_read_401s_with_no_credential(self):
        st, body = _get(self.port, "/api/tunnel")
        self.assertEqual(st, 401)

    def test_write_401s_with_no_credential(self):
        """The mutation route is gated too, not just the reads -- do_POST's _authok() check
        runs before any route dispatch, same guard every other POST route already has."""
        st, body = _post(self.port, "/api/tunnel", {"key": "TUNNEL_PASS", "value": "sneaky"})
        self.assertEqual(st, 401)
        self.assertFalse(os.path.exists(config.CONFIG_FILE), "an unauthenticated write must never reach disk")


if __name__ == "__main__":
    unittest.main()
