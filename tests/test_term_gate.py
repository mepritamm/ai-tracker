"""Tests for aitracker.term_gate — the shared origin gate for the terminal tiers.

The terminal is enabled by default (config.TERMINAL defaults to True) and checks only
whether it's enabled. This module also enforces same-origin requests as a belt-and-braces
protection against cross-origin POSTs.

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
    """Test the allowed() function, which only checks config.TERMINAL.

    Terminal is ON by default; only setting config.TERMINAL=False disables it (via TRACKER_TERMINAL=0).
    Note: The old tests checked both TERMINAL and AUTH. The new implementation only checks
    TERMINAL, since AUTH is checked separately at tunnel entry. This reflects that
    the default make serve binds to localhost only, so no AUTH is needed there; tunnel always
    requires AUTH at a higher level."""

    def setUp(self):
        # Save original config values
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH

    def tearDown(self):
        # Restore original config values
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_true_when_terminal_enabled(self):
        """Terminal is ON when config.TERMINAL is True."""
        config.TERMINAL = True
        self.assertTrue(term_gate.allowed())

    def test_true_when_terminal_enabled_without_auth(self):
        """Terminal is ON when enabled, even without AUTH (NEW BEHAVIOR)."""
        config.TERMINAL = True
        config.AUTH = ""
        self.assertTrue(term_gate.allowed(),
                        "Terminal is ON by default; AUTH not required")

    def test_false_when_terminal_disabled(self):
        """Terminal is OFF when config.TERMINAL is False."""
        config.TERMINAL = False
        self.assertFalse(term_gate.allowed())

    def test_false_when_terminal_disabled_even_with_auth(self):
        """Terminal is OFF when disabled, even with AUTH set."""
        config.TERMINAL = False
        config.AUTH = "u:p"
        self.assertFalse(term_gate.allowed())


class TestGuard(unittest.TestCase):
    """Test the guard() function, which checks both allowed() and origin."""

    def setUp(self):
        # Save original config values
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        # Enabled by default for these tests
        config.TERMINAL = True
        config.AUTH = ""

    def tearDown(self):
        # Restore original config values
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_disabled_terminal_403s(self):
        """guard() returns False when terminal is disabled."""
        config.TERMINAL = False
        h = _FakeHandler()
        self.assertFalse(term_gate.guard(h))
        self.assertEqual(h.calls[-1][1], 403)

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


if __name__ == "__main__":
    unittest.main()
