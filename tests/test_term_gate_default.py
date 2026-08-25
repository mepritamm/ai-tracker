"""Test that terminal is enabled by default.

This test file verifies the on-by-default behavior: TRACKER_TERMINAL defaults to ON via
config.TERMINAL, and TRACKER_AUTH is only required once the server is reachable beyond
loopback (config.BIND_HOST not loopback) -- a plain `make serve` needs neither env var set.
Only explicitly setting TRACKER_TERMINAL=0 (which sets config.TERMINAL=False) disables the
terminal outright, regardless of bind address or auth.
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
    """Verify terminal is ON by default on a loopback bind (the common case: plain `make
    serve`), and that TRACKER_TERMINAL=0 is the only thing that disables it outright.

    Contract:
    - Loopback bind (the default): terminal is ON whether or not TRACKER_AUTH is set.
    - Non-loopback bind (HOST=0.0.0.0, a LAN/Tailscale IP, ...): terminal additionally
      requires TRACKER_AUTH -- see test_term_gate.py for that half of the matrix.
    - TRACKER_TERMINAL=0: terminal is OFF unconditionally.
    """

    def setUp(self):
        # Save original config values
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        self._bind0 = config.BIND_HOST
        config.BIND_HOST = "127.0.0.1"   # the common case this file is about

    def tearDown(self):
        # Restore original config values
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0
        config.BIND_HOST = self._bind0

    def test_terminal_on_by_default(self):
        """Terminal is ON by default (no environment variables needed) on a loopback bind."""
        # Simulate default state: not explicitly disabled
        config.TERMINAL = True
        config.AUTH = ""
        self.assertTrue(term_gate.allowed(),
                        "Terminal should be ON by default on a loopback bind, even without AUTH")

    def test_terminal_on_even_with_auth_set(self):
        """Terminal is ON regardless of whether AUTH is set, on a loopback bind."""
        config.TERMINAL = True
        config.AUTH = "user:pass"
        self.assertTrue(term_gate.allowed(),
                        "Terminal should be ON; AUTH doesn't affect allowed() on loopback")

    def test_terminal_on_remains_on_even_without_auth(self):
        """Terminal is ON without AUTH on a loopback bind (the on-by-default behavior)."""
        config.TERMINAL = True
        config.AUTH = ""
        self.assertTrue(term_gate.allowed(),
                        "Terminal is ON by default on loopback; AUTH is not required there")

    def test_terminal_off_when_explicitly_disabled(self):
        """Terminal is OFF when TRACKER_TERMINAL=0 (i.e., config.TERMINAL=False)."""
        config.TERMINAL = False
        config.AUTH = "user:pass"
        self.assertFalse(term_gate.allowed(),
                         "Terminal should be OFF when disabled, regardless of AUTH")

    def test_terminal_off_when_disabled_and_nonloopback(self):
        """TRACKER_TERMINAL=0 wins even on a non-loopback bind with AUTH set."""
        config.TERMINAL = False
        config.AUTH = "user:pass"
        config.BIND_HOST = "0.0.0.0"
        self.assertFalse(term_gate.allowed())

    def test_cross_origin_still_refused_even_when_allowed(self):
        """Cross-origin requests are still refused even when terminal is allowed.

        This tests the belt-and-braces protection: _origin_ok() is independent of allowed()
        and still rejects cross-origin POSTs."""
        config.TERMINAL = True
        h = _FakeHandler({"Origin": "https://evil.example", "Host": "localhost:8790"})
        self.assertFalse(term_gate.guard(h),
                        "guard() should refuse cross-origin even when allowed() is True")
        self.assertEqual(h.calls[-1][1], 403,
                        "Should return 403 Forbidden for cross-origin request")


if __name__ == "__main__":
    unittest.main()
