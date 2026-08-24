"""Tests for aitracker.term_gate — the shared gate for the terminal tiers.

The terminal is enabled by default (config.TERMINAL defaults to True). allowed() additionally
requires TRACKER_AUTH whenever the server is bound beyond loopback (config.BIND_HOST) — a
loopback-only `make serve` needs no TRACKER_AUTH, but `HOST=0.0.0.0 make serve` (LAN/Tailscale)
or `make tunnel` do, since either makes the terminal reachable from off the box. This module also
enforces same-origin requests as a belt-and-braces protection against cross-origin POSTs.

These tests exercise the gate directly (no route, no PTY) with a minimal fake handler
standing in for http.server.BaseHTTPRequestHandler.
"""
import unittest

from aitracker import config, term_gate


class _FakeHeaders:
    """Just enough of http.client.HTTPMessage's interface for term_gate: .get(key, default)."""

    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler: records the one call term_gate.guard() may make."""

    def __init__(self, headers=None):
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class TestAllowed(unittest.TestCase):
    """Test the allowed() function: config.TERMINAL gates everything, and — when TERMINAL is
    on — config.BIND_HOST not being loopback additionally requires config.AUTH."""

    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        self._bind0 = config.BIND_HOST

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0
        config.BIND_HOST = self._bind0

    # -- row: make serve (127.0.0.1, no auth) -> ON --
    def test_on_for_loopback_bind_without_auth(self):
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "127.0.0.1"
        self.assertTrue(term_gate.allowed(),
                        "loopback bind needs no TRACKER_AUTH")

    # -- row: make tunnel (auth mandatory per the Makefile) -> ON --
    # A tunnel terminates locally, so the bind address the server sees is still loopback; the
    # Makefile is what forces TRACKER_AUTH for that path. Either way allowed() is True here.
    def test_on_for_loopback_bind_with_auth(self):
        config.TERMINAL = True
        config.AUTH = "user:pass"
        config.BIND_HOST = "127.0.0.1"
        self.assertTrue(term_gate.allowed())

    # -- row: HOST=0.0.0.0 with TRACKER_AUTH -> ON --
    def test_on_for_nonloopback_bind_with_auth(self):
        config.TERMINAL = True
        config.AUTH = "user:pass"
        config.BIND_HOST = "0.0.0.0"
        self.assertTrue(term_gate.allowed(),
                        "non-loopback bind is fine once TRACKER_AUTH is set")

    # -- row: HOST=0.0.0.0 without TRACKER_AUTH -> OFF (the hole this commit closes) --
    def test_off_for_nonloopback_bind_without_auth(self):
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "0.0.0.0"
        self.assertFalse(term_gate.allowed(),
                         "a server reachable beyond loopback must not run an unauthenticated shell")

    def test_off_for_lan_ip_bind_without_auth(self):
        """Same as above but with a concrete LAN address rather than the wildcard bind."""
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "192.168.1.42"
        self.assertFalse(term_gate.allowed())

    def test_on_for_ipv6_loopback_without_auth(self):
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "::1"
        self.assertTrue(term_gate.allowed())

    def test_on_for_localhost_name_without_auth(self):
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "localhost"
        self.assertTrue(term_gate.allowed())

    # -- row: TRACKER_TERMINAL=0 anywhere -> OFF --
    def test_false_when_terminal_disabled(self):
        """Terminal is OFF when config.TERMINAL is False, loopback or not."""
        config.TERMINAL = False
        config.AUTH = ""
        config.BIND_HOST = "127.0.0.1"
        self.assertFalse(term_gate.allowed())

    def test_false_when_terminal_disabled_even_with_auth(self):
        """Terminal is OFF when disabled, even with AUTH set and a non-loopback bind."""
        config.TERMINAL = False
        config.AUTH = "u:p"
        config.BIND_HOST = "0.0.0.0"
        self.assertFalse(term_gate.allowed())


class TestGuard(unittest.TestCase):
    """Test the guard() function, which checks allowed() and origin."""

    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        self._bind0 = config.BIND_HOST
        # Enabled, loopback, no auth needed -- the default-serve case -- unless a test overrides.
        config.TERMINAL = True
        config.AUTH = ""
        config.BIND_HOST = "127.0.0.1"

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0
        config.BIND_HOST = self._bind0

    def test_disabled_terminal_403s(self):
        """guard() returns False when terminal is disabled."""
        config.TERMINAL = False
        h = _FakeHandler()
        self.assertFalse(term_gate.guard(h))
        self.assertEqual(h.calls[-1][1], 403)

    def test_nonloopback_without_auth_403s_with_actionable_message(self):
        """guard() refuses a non-loopback, unauthenticated request and says how to fix it."""
        config.BIND_HOST = "0.0.0.0"
        config.AUTH = ""
        h = _FakeHandler()
        self.assertFalse(term_gate.guard(h))
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)
        self.assertIn("TRACKER_AUTH", obj.get("error", ""))
        self.assertIn("network", obj.get("error", ""))

    def test_nonloopback_with_auth_passes(self):
        config.BIND_HOST = "0.0.0.0"
        config.AUTH = "user:pass"
        h = _FakeHandler()
        self.assertTrue(term_gate.guard(h))
        self.assertEqual(h.calls, [])

    def test_cross_origin_post_403s(self):
        """guard() returns False when Origin header doesn't match Host."""
        # Same-origin curl/fetch sends no Origin header at all -- only a mismatched Origin
        # (a cross-site POST) should be refused.
        h = _FakeHandler({"Origin": "https://evil.example", "Host": "localhost:8787"})
        self.assertFalse(term_gate.guard(h))
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)
        self.assertIn("cross-origin", obj.get("error", ""))

    def test_same_origin_post_passes(self):
        """guard() returns True when Origin header matches Host."""
        h = _FakeHandler({"Origin": "http://localhost:8787", "Host": "localhost:8787"})
        self.assertTrue(term_gate.guard(h))
        self.assertEqual(h.calls, [])   # guard writes nothing when it allows the request through

    def test_no_origin_header_passes(self):
        """guard() returns True when there is no Origin header (same-origin fetch or curl)."""
        h = _FakeHandler()   # curl / same-origin fetch: no Origin header at all
        self.assertTrue(term_gate.guard(h))
        self.assertEqual(h.calls, [])


class TestIsLoopback(unittest.TestCase):
    """Direct tests for the host-classification helper the gate relies on."""

    def test_loopback_v4(self):
        self.assertTrue(term_gate._is_loopback("127.0.0.1"))
        self.assertTrue(term_gate._is_loopback("127.0.0.53"))

    def test_loopback_v6(self):
        self.assertTrue(term_gate._is_loopback("::1"))

    def test_localhost_name(self):
        self.assertTrue(term_gate._is_loopback("localhost"))
        self.assertTrue(term_gate._is_loopback("Localhost"))

    def test_wildcard_bind_is_not_loopback(self):
        self.assertFalse(term_gate._is_loopback("0.0.0.0"))

    def test_lan_ip_is_not_loopback(self):
        self.assertFalse(term_gate._is_loopback("10.0.0.5"))
        self.assertFalse(term_gate._is_loopback("192.168.1.1"))

    def test_empty_or_unparseable_is_not_loopback(self):
        """Unknown input is treated as NOT loopback -- fail closed, not open."""
        self.assertFalse(term_gate._is_loopback(""))
        self.assertFalse(term_gate._is_loopback("not-an-ip"))


if __name__ == "__main__":
    unittest.main()
