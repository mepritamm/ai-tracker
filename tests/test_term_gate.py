"""Tests for aitracker.term_gate — the shared opt-in/auth/origin gate for the terminal tiers.

Step 0 lands this gate alone, before any tier exists, so these tests exercise it directly
(no route, no PTY) with a minimal fake handler standing in for http.server.BaseHTTPRequestHandler.
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
    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_false_when_terminal_flag_missing(self):
        config.TERMINAL = False
        config.AUTH = "u:p"
        self.assertFalse(term_gate.allowed())

    def test_false_when_auth_missing(self):
        config.TERMINAL = True
        config.AUTH = ""
        self.assertFalse(term_gate.allowed())

    def test_false_when_both_missing(self):
        config.TERMINAL = False
        config.AUTH = ""
        self.assertFalse(term_gate.allowed())

    def test_true_when_both_present(self):
        config.TERMINAL = True
        config.AUTH = "u:p"
        self.assertTrue(term_gate.allowed())


class TestGuard(unittest.TestCase):
    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        config.TERMINAL = True
        config.AUTH = "u:p"

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_disabled_terminal_403s(self):
        config.TERMINAL = False
        h = _FakeHandler()
        self.assertFalse(term_gate.guard(h))
        self.assertEqual(h.calls[-1][1], 403)

    def test_cross_origin_post_403s(self):
        # Same-origin curl/fetch sends no Origin header at all -- only a mismatched Origin
        # (a cross-site POST) should be refused.
        h = _FakeHandler({"Origin": "https://evil.example", "Host": "localhost:8787"})
        self.assertFalse(term_gate.guard(h))
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)
        self.assertIn("cross-origin", obj.get("error", ""))

    def test_same_origin_post_passes(self):
        h = _FakeHandler({"Origin": "http://localhost:8787", "Host": "localhost:8787"})
        self.assertTrue(term_gate.guard(h))
        self.assertEqual(h.calls, [])   # guard writes nothing when it allows the request through

    def test_no_origin_header_passes(self):
        h = _FakeHandler()   # curl / same-origin fetch: no Origin header at all
        self.assertTrue(term_gate.guard(h))
        self.assertEqual(h.calls, [])


if __name__ == "__main__":
    unittest.main()
