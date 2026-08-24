"""Tests for aitracker.term_launch — Tier 1 (launch Terminal/iTerm at a session's cwd).

`build_script` is pure (bytes/strings in, AppleScript string out) so the quoting/escaping rules
are tested directly with no subprocess involved. `open_terminal`'s gating (resume is Claude-only,
proxied requests refused, term_gate first) is tested with a fake handler. No test here ever runs
a real `osascript`: every path either returns an error response *before* that call, or patches
`term_launch.subprocess.run` -- so running this suite never pops a Terminal/iTerm window.
"""
import os
import re
import shlex
import unittest
from unittest import mock

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


class TestBuildScriptResumeFallback(unittest.TestCase):
    """Option C, Tier-1 shape (docs/refusal-fix-direction.md): term_launch hands off to
    `osascript` and never observes the spawned tab again, so there is no way to retry
    AFTER the fact like term_vt's PTY backstop does. The fallback is built into the shell
    command itself instead -- `claude --resume <id> || claude --resume <id> --fork-session`
    -- so a refused resume falls back with no ai-tracker process involved at all."""

    def _unescape(self, script):
        m = re.search(r'do script "((?:[^"\\]|\\.)*)"', script)
        self.assertIsNotNone(m, "no valid do-script string literal found in:\n%s" % script)
        return _applescript_unescape(m.group(1))

    def test_plain_resume_gets_the_or_fallback_with_fork_session(self):
        argv = ["claude", "--resume", "abc-123"]
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", "abc-123", "resume", "Terminal", argv))
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/proj") +
            " && (claude --resume abc-123 || claude --resume abc-123 --fork-session)")

    def test_already_forked_argv_is_not_wrapped_in_a_redundant_or(self):
        """When the fast path already appended --fork-session (a background-agent
        session), there is nothing left to fall back to -- the command must stay a
        single, unwrapped command, not `(cmd || cmd)` with itself."""
        argv = ["claude", "--resume", "bg-sid", "--fork-session"]
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", "bg-sid", "resume", "Terminal", argv))
        self.assertEqual(
            inner, "cd " + shlex.quote("/tmp/proj") +
            " && claude --resume bg-sid --fork-session")
        self.assertNotIn("||", inner)

    def test_default_argv_when_resume_argv_omitted_also_gets_the_fallback(self):
        """Existing direct callers that don't pass resume_argv (e.g. the plain
        TestBuildScriptResume tests above) fall back to ["claude", "--resume", sid] --
        which has no --fork-session, so it must ALSO gain the || fallback."""
        script = term_launch.build_script("/tmp/proj", "abc-123", "resume", "Terminal")
        self.assertIn("claude --resume abc-123 || claude --resume abc-123 --fork-session",
                       script.replace("\\\\", "\\"))

    def test_cwd_mode_never_gets_an_or_fallback(self):
        script = term_launch.build_script("/tmp/proj", "abc-123", "cwd", "Terminal")
        self.assertNotIn("||", script)


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
        self.assertIn("refused", obj.get("error", ""))

    def test_error_string_does_not_claim_local_only(self):
        """The route cannot honour a "local-only" promise (a tunnel dials it over loopback), so
        it must not print one. It says what is actually true: this request was refused."""
        h = _FakeHandler(client_ip="10.0.0.5")
        term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "cwd"})
        self.assertNotIn("local-only", h.calls[-1][0].get("error", ""))


class TestProxiedRequestRefused(_TerminalEnabled):
    """Defect 1. `make tunnel` runs `cloudflared tunnel --url http://localhost:<port>`, so the
    tunnel terminates on this machine and EVERY public request arrives with client_address[0]
    == "127.0.0.1". The peer address therefore proves nothing; the proxy's own headers do."""

    def test_each_proxy_header_is_refused_from_loopback(self):
        for h_name in term_launch._PROXY_HEADERS:
            with self.subTest(header=h_name):
                h = _FakeHandler(client_ip="127.0.0.1", headers={h_name: "203.0.113.9"})
                term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "cwd"})
                obj, code = h.calls[-1]
                self.assertEqual(code, 403)
                self.assertIn("proxied", obj.get("error", ""))

    def test_cloudflared_shaped_request_is_refused(self):
        """The literal header set cloudflared puts in front of the origin server."""
        h = _FakeHandler(client_ip="127.0.0.1", headers={
            "Host": "some-name.trycloudflare.com",
            "X-Forwarded-For": "192.168.1.5",
            "X-Forwarded-Proto": "https",
            "CF-Connecting-IP": "192.168.1.5",
            "CF-Ray": "8f0c1e2d3a4b5c6d-SJC",
        })
        term_launch.open_terminal(h, None, {"session": "abc-123", "mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 403)
        self.assertIn("proxied", obj.get("error", ""))

    def test_plain_loopback_request_is_not_refused_as_proxied(self):
        """Belt and braces must not become a brick: a genuine local fetch still gets past the
        remote check (it fails later, on the session lookup, not with a 403)."""
        h = _FakeHandler(client_ip="127.0.0.1")
        term_launch.open_terminal(h, None, {"session": "no-such-session-xyz", "mode": "cwd"})
        obj, code = h.calls[-1]
        self.assertNotEqual(code, 403)

    def test_proxy_header_list_covers_cloudflare_and_the_x_forwarded_family(self):
        for h_name in ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded",
                       "CF-Connecting-IP", "CF-Ray", "X-Real-IP"):
            self.assertIn(h_name, term_launch._PROXY_HEADERS)


class TestSidShape(unittest.TestCase):
    """Defect 2. providers.claude.find_session globs "<PROJECTS>/*/<sid>.jsonl", so an
    unvalidated sid of "*" opens whichever session sorts first, and it normalises the sid
    (strip + drop ".jsonl") while build_script used the raw one."""

    def test_glob_metacharacters_are_rejected(self):
        for bad in ("*", "?", "abc*", "[a-z]", "ab[c]d", "*.jsonl"):
            with self.subTest(sid=bad):
                self.assertEqual(term_launch.normalize_sid(bad), "")

    def test_path_separators_are_rejected(self):
        for bad in ("../../etc/passwd", "a/b", "a\\b", "/abs"):
            with self.subTest(sid=bad):
                self.assertEqual(term_launch.normalize_sid(bad), "")

    def test_surrounding_whitespace_is_rejected(self):
        for bad in ("abc-123  ", "  abc-123", "\tabc-123", "abc-123\n"):
            with self.subTest(sid=repr(bad)):
                self.assertEqual(term_launch.normalize_sid(bad), "")

    def test_jsonl_suffix_is_normalised_away(self):
        self.assertEqual(term_launch.normalize_sid("abc-123.jsonl"), "abc-123")

    def test_plain_and_prefixed_ids_survive(self):
        self.assertEqual(term_launch.normalize_sid("abc-123"), "abc-123")
        self.assertEqual(term_launch.normalize_sid("auggie:xyz"), "auggie:xyz")
        self.assertEqual(term_launch.normalize_sid("augment-vscode:ws:uu"), "augment-vscode:ws:uu")

    def test_non_string_is_rejected(self):
        for bad in (None, 5, ["a"], {"a": 1}):
            with self.subTest(sid=bad):
                self.assertEqual(term_launch.normalize_sid(bad), "")


class TestSidShapeAtTheRoute(_TerminalEnabled):
    def test_glob_session_is_400_and_never_launches(self):
        with mock.patch.object(term_launch.subprocess, "run") as run:
            h = _FakeHandler()
            term_launch.open_terminal(h, None, {"session": "*", "mode": "resume"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("bad session id", obj.get("error", ""))
        run.assert_not_called()

    def test_trailing_space_session_is_400_and_never_launches(self):
        with mock.patch.object(term_launch.subprocess, "run") as run:
            h = _FakeHandler()
            term_launch.open_terminal(h, None, {"session": "abc-123  ", "mode": "resume"})
        self.assertEqual(h.calls[-1][1], 400)
        run.assert_not_called()

    def test_resume_argv_uses_the_normalised_sid_not_the_raw_one(self):
        """"<uuid>.jsonl" resolves to <uuid>; `claude --resume` must get <uuid>, not the
        filename the caller happened to type."""
        with mock.patch.object(term_gate, "session_cwd", return_value="/tmp"), \
             mock.patch.object(term_launch.subprocess, "run") as run:
            h = _FakeHandler()
            term_launch.open_terminal(h, None, {"session": "abc-123.jsonl", "mode": "resume"})
        self.assertEqual(h.calls[-1], ({"ok": True}, 200))
        script = run.call_args[0][0][-1]
        self.assertIn("claude --resume abc-123", script)
        self.assertNotIn("abc-123.jsonl", script)


class TestBodyShape(_TerminalEnabled):
    """Defect 3. server.do_POST json.loads()es ANY JSON value, so the body can be a string, a
    list or null -- .get() on those is an AttributeError and a RemoteDisconnected for the client."""

    def test_string_body_is_400_not_an_exception(self):
        h = _FakeHandler()
        term_launch.open_terminal(h, None, "just-a-string")
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("JSON object", obj.get("error", ""))

    def test_list_and_scalar_bodies_are_400(self):
        for bad in (["session"], 42, True, "x"):
            with self.subTest(body=bad):
                h = _FakeHandler()
                term_launch.open_terminal(h, None, bad)
                self.assertEqual(h.calls[-1][1], 400)

    def test_none_body_is_still_a_clean_400(self):
        h = _FakeHandler()
        term_launch.open_terminal(h, None, None)
        self.assertEqual(h.calls[-1][1], 400)


_EXT_LAUNCH_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "aitracker", "web", "ext_launch.js")


class TestButtonsFollowServerPolicy(unittest.TestCase):
    """Defect 4. config.TERMINAL is server-side only, so on a default install the buttons used to
    render and 403 on click (conventions rule 5 inverted). Tier 2 owns GET /api/term/status and
    server.py/app.js are off-limits here, so the SPA asks the route it already has and latches
    off on a 403. Asserted against the asset's source: there is no JS engine in the stdlib."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_it_probes_the_existing_route_and_not_a_new_one(self):
        self.assertIn('post({ session: "" })', self.src)
        # Tier 2 owns that path; the comment may name it, but nothing here may CALL it.
        self.assertNotIn('"/api/term/status"', self.src)

    def test_a_403_latches_the_buttons_off(self):
        self.assertIn("r.status === 403", self.src)
        self.assertIn("allowed = false", self.src)

    def test_buttons_are_not_drawn_before_the_server_has_answered(self):
        self.assertIn("allowed === null", self.src)
        self.assertIn("allowed === false", self.src)
        # the probe must resolve before any button markup is produced
        self.assertLess(self.src.index("allowed === null"), self.src.index("extopenbtn"))

    def test_prefix_mirror_points_at_the_source_of_truth(self):
        self.assertIn("registry.PROVIDERS", self.src)    # defect 5: one-line pointer, by choice


class TestRenamedLaunchButtonsAndNewControls(unittest.TestCase):
    """The four Tier 1/3 buttons are named by WHERE the terminal opens ('…here' = in-browser,
    'External …' = the Mac's own Terminal/iTerm, this-machine-only), plus two new controls that
    spawn a terminal NOT attached to any existing session's Claude process. Asserted against the
    asset's source, same as TestButtonsFollowServerPolicy above: there is no JS engine here."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_here_pair_labels(self):
        self.assertIn("▶ Open terminal here", self.src)
        self.assertIn("⟲ Resume terminal here", self.src)

    def test_external_pair_is_renamed(self):
        self.assertIn("↗ External terminal", self.src)
        self.assertIn("↗ External resume", self.src)
        # the old, unqualified labels must not survive the rename
        self.assertNotIn(">↗ Terminal</button>", self.src)
        self.assertNotIn(">↗ Resume</button>", self.src)

    def test_new_terminal_controls_exist_and_send_the_right_modes(self):
        self.assertIn("+ New terminal", self.src)
        self.assertIn("+ New Claude session", self.src)
        # "+ New terminal" reuses the existing mode:"cwd" contract (no new server work);
        # "+ New Claude session" sends mode:"new", which is not yet supported server-side.
        self.assertIn('window.ExtVT.open(cur, "new")', self.src)

    def test_new_controls_are_assembled_before_the_localonly_gate(self):
        # Both "+ New …" buttons must never be host-gated (conventions rule: no control hidden
        # by host/viewport) -- i.e. built into newHtml, which is assembled before localOnly()
        # is even consulted, exactly like the "…here" pair's vtHtml.
        new_idx = self.src.index("const newHtml =")
        gate_idx = self.src.index("if (localOnly())")
        self.assertLess(new_idx, gate_idx)

    def test_external_pair_is_still_host_gated(self):
        # Unchanged: the native "External …" buttons are still built inside the localOnly()
        # branch, so they stay off the DOM entirely off-localhost.
        gate_idx = self.src.index("if (localOnly())")
        ext_idx = self.src.index("↗ External terminal")
        self.assertGreater(ext_idx, gate_idx)


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
