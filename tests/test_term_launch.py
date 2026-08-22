"""Tests for aitracker.term_launch — Tier 1 (launch Terminal/iTerm at a session's cwd).

`build_script` is pure (bytes/strings in, AppleScript string out) so the quoting/escaping rules
are tested directly with no subprocess involved. `open_terminal`'s gating (resume is Claude-only,
same-machine only, term_gate first) is tested with a fake handler; none of these tests reach
`subprocess.run(["osascript", ...])` -- every path exercised here returns an error response
*before* that call, so running this suite never pops an actual Terminal/iTerm window.
"""
import re
import shlex
import unittest

from aitracker import config, term_gate, term_launch


def _applescript_unescape(s):
    """Reverse of build_script's escaping (backslash-then-char -> char). Used to prove the
    do-script argument round-trips back to the exact inner shell command."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


class _FakeHeaders:
    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler: records every _json() call; client_address mimics
    BaseHTTPRequestHandler's (ip, port) tuple."""

    def __init__(self, client_ip="127.0.0.1", headers=None):
        self.client_address = (client_ip, 54321)
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class TestBuildScriptQuoting(unittest.TestCase):
    """Rule 1: cwd is untrusted (comes from a session log). shlex.quote first, THEN
    AppleScript-escape the whole inner command -- in that order."""

    def test_nasty_cwd_is_shell_quoted(self):
        cwd = '/tmp/a b"c'
        script = term_launch.build_script(cwd, "", "cwd", "Terminal")
        quoted = shlex.quote(cwd)
        self.assertIn('"', quoted)  # sanity: this path really does contain a bare double-quote
        escaped = quoted.replace("\\", "\\\\").replace('"', '\\"')
        self.assertIn(escaped, script)          # the shell-quoted, AppleScript-escaped cwd is present verbatim
        self.assertNotIn('b"c', script)         # the raw (unescaped) quote never survives adjacent to its neighbours

    def test_nasty_cwd_round_trips_through_applescript_escaping(self):
        # Extract the do-script argument with a regex that respects backslash-escapes, so this
        # proves the closing quote lands where build_script intended, not at the first bare `"`.
        cwd = '/tmp/a b"c'
        script = term_launch.build_script(cwd, "", "cwd", "Terminal")
        m = re.search(r'do script "((?:[^"\\]|\\.)*)"', script)
        self.assertIsNotNone(m, "no valid do-script string literal found in:\n%s" % script)
        self.assertEqual(_applescript_unescape(m.group(1)), "cd " + shlex.quote(cwd))

    def test_backslash_in_cwd_is_doubled_before_quote_escaping(self):
        cwd = r"/tmp/weird\path"
        script = term_launch.build_script(cwd, "", "cwd", "Terminal")
        m = re.search(r'do script "((?:[^"\\]|\\.)*)"', script)
        self.assertIsNotNone(m)
        self.assertEqual(_applescript_unescape(m.group(1)), "cd " + shlex.quote(cwd))

    def test_iterm_uses_a_different_wrapper(self):
        script_term = term_launch.build_script("/tmp/x", "", "cwd", "Terminal")
        script_iterm = term_launch.build_script("/tmp/x", "", "cwd", "iTerm")
        self.assertIn('tell application "Terminal"', script_term)
        self.assertIn('tell application "iTerm"', script_iterm)
        self.assertNotEqual(script_term, script_iterm)


class TestBuildScriptResume(unittest.TestCase):
    def test_resume_mode_runs_claude_resume(self):
        script = term_launch.build_script("/tmp/proj", "abc-123", "resume", "Terminal")
        self.assertIn("claude --resume abc-123", script)

    def test_cwd_mode_does_not_mention_claude(self):
        script = term_launch.build_script("/tmp/proj", "abc-123", "cwd", "Terminal")
        self.assertNotIn("claude --resume", script)


class TestIsClaude(unittest.TestCase):
    def test_bare_id_is_claude(self):
        self.assertTrue(term_launch._is_claude("abc-123"))

    def test_auggie_prefix_is_not_claude(self):
        self.assertFalse(term_launch._is_claude("auggie:xyz"))

    def test_augment_ext_prefixes_are_not_claude(self):
        self.assertFalse(term_launch._is_claude("augment-vscode:ws:uu"))
        self.assertFalse(term_launch._is_claude("augment-cursor:ws:uu"))


class _TerminalEnabled(unittest.TestCase):
    """Shared setUp/tearDown: flips config so term_gate.guard() lets requests through."""

    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        config.TERMINAL = True
        config.AUTH = "u:p"

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0


class TestOpenTerminalGating(_TerminalEnabled):
    """None of these reach subprocess.run -- every case here is rejected before that call."""

    def test_resume_rejected_for_auggie_prefixed_id(self):
        h = _FakeHandler()
        term_launch.open_terminal(h, None, {"session": "auggie:xyz", "mode": "resume"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("Claude-only", obj.get("error", ""))

    def test_missing_session_is_rejected(self):
        h = _FakeHandler()
        term_launch.open_terminal(h, None, {"mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)

    def test_bad_mode_is_rejected(self):
        h = _FakeHandler()
        term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "nope"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)

    def test_non_loopback_client_is_refused(self):
        h = _FakeHandler(client_ip="10.0.0.5")
        term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)
        self.assertIn("local-only", obj.get("error", ""))


class TestOpenTerminalGuardFirst(unittest.TestCase):
    """Rule 5: term_gate.guard() runs first. With TRACKER_TERMINAL unset, the route 403s before
    any of open_terminal's own checks (mode, session, client_address) even run."""

    def setUp(self):
        self._terminal0 = config.TERMINAL
        self._auth0 = config.AUTH
        config.TERMINAL = False
        config.AUTH = ""

    def tearDown(self):
        config.TERMINAL = self._terminal0
        config.AUTH = self._auth0

    def test_guard_refuses_when_terminal_flag_unset(self):
        self.assertFalse(term_gate.guard(_FakeHandler()))

    def test_route_403s_when_terminal_flag_unset_even_from_loopback(self):
        h = _FakeHandler(client_ip="127.0.0.1")
        term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)


class TestRouteRegistered(unittest.TestCase):
    def test_open_terminal_registered_into_extra_post(self):
        from aitracker import server
        self.assertIs(server.EXTRA_POST.get("/api/term/open"), term_launch.open_terminal)


if __name__ == "__main__":
    unittest.main()
