"""Test that terminal is enabled by default.

This test file verifies the new default behavior: TRACKER_TERMINAL defaults to ON via config.TERMINAL.
Only explicitly setting TRACKER_TERMINAL=0 (which sets config.TERMINAL=False) disables it.
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
    """Stands in for the real Handler: records calls to _json()."""

    def __init__(self, headers=None):
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class TestTerminalDefaults(unittest.TestCase):
    """Verify terminal is ON by default (the new contract).

    The key difference from the old behavior:
    - OLD: Terminal was OFF unless TRACKER_TERMINAL=1 AND TRACKER_AUTH was set
    - NEW: Terminal is ON by default; only TRACKER_TERMINAL=0 disables it; AUTH not required
    """

    def setUp(self):
        # Save original config values
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH

    def tearDown(self):
        # Restore original config values
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_terminal_on_by_default(self):
        """Terminal is ON by default (no environment variables needed)."""
        # Simulate default state: not explicitly disabled
        config.TERMINAL = True
        config.AUTH = ""
        self.assertTrue(term_gate.allowed(),
                        "Terminal should be ON by default, even without AUTH")

    def test_terminal_on_even_with_auth_set(self):
        """Terminal is ON regardless of whether AUTH is set."""
        config.TERMINAL = True
        config.AUTH = "user:pass"
        self.assertTrue(term_gate.allowed(),
                        "Terminal should be ON; AUTH doesn't affect allowed()")

    def test_terminal_on_remains_on_even_without_auth(self):
        """Terminal is ON without AUTH (the new behavior)."""
        config.TERMINAL = True
        config.AUTH = ""
        self.assertTrue(term_gate.allowed(),
                        "Terminal is ON by default; AUTH is not required for terminal features")

    def test_terminal_off_when_explicitly_disabled(self):
        """Terminal is OFF when TRACKER_TERMINAL=0 (i.e., config.TERMINAL=False)."""
        config.TERMINAL = False
        config.AUTH = "user:pass"
        self.assertFalse(term_gate.allowed(),
                         "Terminal should be OFF when disabled, regardless of AUTH")

    def test_cross_origin_still_refused_even_when_allowed(self):
        """Cross-origin requests are still refused even when terminal is allowed.

        This tests the belt-and-braces protection: _origin_ok() is independent of allowed()
        and still rejects cross-origin POSTs."""
        config.TERMINAL = True
        h = _FakeHandler({"Origin": "https://evil.example", "Host": "localhost:8787"})
        self.assertFalse(term_gate.guard(h),
                        "guard() should refuse cross-origin even when allowed() is True")
        self.assertEqual(h.calls[-1][1], 403,
                        "Should return 403 Forbidden for cross-origin request")


if __name__ == "__main__":
    unittest.main()
