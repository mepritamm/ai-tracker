"""Tests for aitracker.term_launch — Tier 1 (launch Terminal/iTerm at a session's cwd).

`build_script` is pure (bytes/strings in, AppleScript string out) so the quoting/escaping rules
are tested directly with no subprocess involved. `open_terminal`'s gating (resume is Claude-only,
proxied requests refused, term_gate first) is tested with a fake handler. No test here ever runs
a real `osascript`: every path either returns an error response *before* that call, or patches
`term_launch.subprocess.run` -- so running this suite never pops a Terminal/iTerm window.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from aitracker import config, term_gate, term_launch


def _iter_named_functions(src):
    """Yields (name, full source including braces) for every `function name(...) { ... }` /
    `async function name(...) { ... }` declaration in `src`, body extracted by brace-matching (not
    a fixed-indent guess like the "\\n  }" trick this file's other source-text tests use) -- so it
    stays correct regardless of how deeply the function's own body happens to be indented."""
    for m in re.finditer(r"(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{", src):
        name = m.group(1)
        i = m.end() - 1  # index of the opening '{'
        depth = 0
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield name, src[m.end() - 1:i + 1]


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
    command itself instead -- now a THREE-leg chain,
    `claude --resume <id> || claude attach <id[:8]> || claude --resume <id> --fork-session`
    -- so a refused resume tries to reattach to the REAL session before ever falling back
    to a forked copy, with no ai-tracker process involved at all.

    `claude attach` was inserted in the middle of the existing two-leg chain because a
    bare `--fork-session` fallback only ever gave the user a COPY of the conversation --
    it never really "resumed" anything, which was the whole complaint this fix answers."""

    def _unescape(self, script):
        m = re.search(r'do script "((?:[^"\\]|\\.)*)"', script)
        self.assertIsNotNone(m, "no valid do-script string literal found in:\n%s" % script)
        return _applescript_unescape(m.group(1))

    def test_plain_resume_gets_the_attach_then_fork_fallback_chain(self):
        argv = ["claude", "--resume", "abc-123"]
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", "abc-123", "resume", "Terminal", argv))
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/proj") +
            " && (claude --resume abc-123 || claude attach abc-123"
            " || claude --resume abc-123 --fork-session)")

    def test_already_forked_argv_is_not_wrapped_in_a_redundant_or(self):
        """When the fast path already appended --fork-session (a background-agent
        session), there is nothing left to fall back to -- the command must stay a
        single, unwrapped command, not `(cmd || cmd)` with itself, and no attach leg
        is added either."""
        argv = ["claude", "--resume", "bg-sid", "--fork-session"]
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", "bg-sid", "resume", "Terminal", argv))
        self.assertEqual(
            inner, "cd " + shlex.quote("/tmp/proj") +
            " && claude --resume bg-sid --fork-session")
        self.assertNotIn("||", inner)
        self.assertNotIn("attach", inner)

    def test_default_argv_when_resume_argv_omitted_also_gets_the_fallback_chain(self):
        """Existing direct callers that don't pass resume_argv (e.g. the plain
        TestBuildScriptResume tests above) fall back to ["claude", "--resume", sid] --
        which has no --fork-session, so it must ALSO gain the attach-then-fork chain."""
        script = term_launch.build_script("/tmp/proj", "abc-123", "resume", "Terminal")
        self.assertIn(
            "claude --resume abc-123 || claude attach abc-123"
            " || claude --resume abc-123 --fork-session",
            script.replace("\\\\", "\\"))

    def test_cwd_mode_never_gets_an_or_fallback(self):
        script = term_launch.build_script("/tmp/proj", "abc-123", "cwd", "Terminal")
        self.assertNotIn("||", script)
        self.assertNotIn("attach", script)

    def test_attach_leg_uses_the_short_eight_char_sid_not_the_full_uuid(self):
        """Regression: `claude attach` takes the short id (first 8 chars), not the full
        uuid the way `--resume` does -- a long, realistic uuid-shaped sid must be
        truncated in the attach leg while the --resume legs keep the id in full."""
        sid = "abcd1234-5678-90ab-cdef-1234567890ab"
        argv = ["claude", "--resume", sid]
        inner = self._unescape(
            term_launch.build_script("/tmp/x", sid, "resume", "Terminal", argv))
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/x") +
            " && (claude --resume %s || claude attach abcd1234"
            " || claude --resume %s --fork-session)" % (sid, sid))
        # sanity: the attach leg itself never carries more than 8 characters of the id
        self.assertIn("claude attach abcd1234", inner)
        self.assertNotIn("claude attach " + sid, inner)

    def test_attach_leg_ordered_between_resume_and_fork_not_just_present(self):
        """ORDER MATTERS: the whole point of the fix is that attach is tried before the
        chain gives up and forks a copy. Assert relative position, not just membership --
        a chain with the legs shuffled would pass a plain assertIn check but still be the
        old, broken behaviour (fork tried before/without ever trying attach in place)."""
        sid = "abcd1234-5678-90ab-cdef-1234567890ab"
        inner = self._unescape(
            term_launch.build_script("/tmp/x", sid, "resume", "Terminal",
                                      ["claude", "--resume", sid]))
        i_resume = inner.index("claude --resume %s ||" % sid)
        i_attach = inner.index("claude attach abcd1234")
        i_fork = inner.index("--fork-session")
        self.assertLess(i_resume, i_attach,
                         "plain resume must be tried before attach")
        self.assertLess(i_attach, i_fork,
                         "attach must be tried before the fork-session fallback")

    def test_custom_resume_argv_still_gets_the_attach_leg_inserted(self):
        """A non-default resume_argv (e.g. one carrying extra flags a caller supplied)
        must still gain the attach leg in the middle, keyed off the extra flags surviving
        into the first and last legs unchanged."""
        sid = "abcd1234-5678-90ab-cdef-1234567890ab"
        argv = ["claude", "--resume", sid, "--extra-flag"]
        inner = self._unescape(
            term_launch.build_script("/tmp/x", sid, "resume", "Terminal", argv))
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/x") +
            " && (claude --resume %s --extra-flag || claude attach abcd1234"
            " || claude --resume %s --extra-flag --fork-session)" % (sid, sid))

    def test_every_leg_is_shlex_quoted_and_cannot_break_out_of_the_do_script_string(self):
        """cwd is untrusted input (comes from a session log) -- a cwd containing both a
        space and a shell metacharacter must not let anything escape the quoted `cd`
        argument, and the whole inner command must still round-trip cleanly through the
        AppleScript do-script string (i.e. build_script's own escaping still holds with
        the new, longer fallback chain in play)."""
        cwd = "/tmp/a b;c"
        sid = "abcd1234-5678-90ab-cdef-1234567890ab"
        argv = ["claude", "--resume", sid]
        script = term_launch.build_script(cwd, sid, "resume", "Terminal", argv)
        inner = self._unescape(script)
        self.assertEqual(
            inner,
            "cd " + shlex.quote(cwd) +
            " && (claude --resume %s || claude attach abcd1234"
            " || claude --resume %s --fork-session)" % (sid, sid))
        # the metacharacter never appears un-quoted / bare in the inner command
        self.assertNotIn("cd /tmp/a b;c ", inner)
        self.assertIn(shlex.quote(cwd), inner)
        # and the do-script string literal itself still parses as exactly one string --
        # i.e. there is exactly one properly-terminated do-script argument in the script.
        self.assertEqual(len(re.findall(r'do script "(?:[^"\\]|\\.)*"', script)), 1)

    def test_empty_sid_in_resume_mode_emits_no_broken_attach_leg(self):
        """Edge case: an empty sid in resume mode (shouldn't normally reach build_script,
        but this function takes sid as a bare argument with no validation of its own) must
        not emit a broken `claude attach ` leg with an empty/missing argument -- pinning
        the real behaviour of the `if sid:` guard in build_script, which skips the attach
        leg entirely when sid is falsy rather than emitting `claude attach` with a blank
        or missing argv."""
        argv = ["claude", "--resume", ""]
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", "", "resume", "Terminal", argv))
        self.assertNotIn("attach", inner)
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/proj") +
            " && (claude --resume '' || claude --resume '' --fork-session)")

    def test_none_sid_in_resume_mode_also_emits_no_broken_attach_leg(self):
        """Same edge case as above but with sid=None rather than "" -- `if sid:` treats
        both as falsy, so this must behave identically (no attach leg). Uses an explicit
        resume_argv, since the *default* argv (resume_argv omitted) interpolates sid
        directly into ["claude", "--resume", sid] and shlex.quote(None) would raise --
        that is a separate, pre-existing contract of the function unrelated to this fix,
        not something this test is pinning."""
        inner = self._unescape(
            term_launch.build_script("/tmp/proj", None, "resume", "Terminal",
                                      ["claude", "--resume", ""]))
        self.assertNotIn("attach", inner)
        self.assertEqual(
            inner,
            "cd " + shlex.quote("/tmp/proj") +
            " && (claude --resume '' || claude --resume '' --fork-session)")


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
_INDEX_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "aitracker", "web", "index.html")


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
    """The four Tier 1/3 detail-pane buttons are named by WHERE the terminal opens ('…here' =
    in-browser, 'External …' = the Mac's own Terminal/iTerm, this-machine-only). Asserted
    against the asset's source, same as TestButtonsFollowServerPolicy above: there is no JS
    engine here."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_here_pair_labels(self):
        # Symbols became inline <svg><use href="#i-NAME"/></svg> icons emitted by ico(name) --
        # the icon builds its href at runtime by concatenation, so the literal call site
        # (ico("play")/ico("redo")) is what the static source actually shows. The words remain
        # the durable part of the label.
        self.assertIn("Open terminal here", self.src)
        self.assertIn('ico("play")', self.src)
        self.assertIn("Resume terminal here", self.src)
        self.assertIn('ico("redo")', self.src)

    def test_external_pair_is_renamed(self):
        self.assertIn("External terminal", self.src)
        self.assertIn("External resume", self.src)
        self.assertIn('ico("external")', self.src)
        # the old, unqualified labels must not survive the rename
        self.assertNotIn(">Terminal</button>", self.src)
        self.assertNotIn(">Resume</button>", self.src)

    def test_external_pair_is_still_host_gated(self):
        # Unchanged: the native "External …" buttons are still built inside the localOnly()
        # branch, so they stay off the DOM entirely off-localhost.
        gate_idx = self.src.index("if (localOnly())")
        ext_idx = self.src.index("External terminal")
        self.assertGreater(ext_idx, gate_idx)

    def test_detail_pane_render_is_back_to_four_buttons(self):
        # render()'s own innerHTML assembly must be exactly vtHtml + nativeHtml -- the "+ New …"
        # pair (a THIRD group that used to be spliced in here) is gone from this function.
        start = self.src.index("function render(d) {")
        end = self.src.index("EXT.push(render)")
        body = self.src[start:end]
        self.assertIn("el.innerHTML = vtHtml + nativeHtml;", body)
        self.assertNotIn("newHtml", body)
        self.assertNotIn("+ New terminal", body)
        self.assertNotIn("+ New Claude session", body)
        self.assertNotIn("extnewgroup", body)


class TestSidebarNewControls(unittest.TestCase):
    """The "+ New terminal" / "+ New Claude session" pair moved to the sidebar (mounted into
    #ext_launch_side) and now opens a directory picker instead of acting on `cur` directly --
    they are global (no session need be selected). Asserted against the asset's source, same as
    the classes above: there is no JS engine here."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_sidebar_mount_is_used(self):
        self.assertIn('getElementById("ext_launch_side")', self.src)

    def test_labels_present(self):
        self.assertIn("+ New terminal", self.src)
        self.assertIn("+ New Claude session", self.src)

    def test_buttons_open_the_picker_with_the_right_mode(self):
        # "+ New terminal" -> mode "cwd" (a plain shell); "+ New Claude session" -> mode "new"
        # (a fresh `claude`) -- checked by pairing each button id with the very next openPicker()
        # call after it, not just presence anywhere in the file.
        m = re.search(r'sidenewcwdbtn"\).*?openPicker\("(\w+)"\)', self.src, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "cwd")
        m = re.search(r'sidenewclaudebtn"\).*?openPicker\("(\w+)"\)', self.src, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "new")

    def test_sidebar_controls_are_never_host_gated(self):
        # Unlike the native "External …" pair, these must never disappear off a tunnel -- they
        # are built (and their listeners wired) by a function that is called unconditionally,
        # entirely separate from localOnly()/allowed.
        self.assertIn("buildSideControls();", self.src)
        build_start = self.src.index("function buildSideControls()")
        build_end = self.src.index("function buildPicker()")
        body = self.src[build_start:build_end]
        self.assertNotIn("localOnly", body)
        self.assertNotIn("allowed", body)


class TestDirectoryPicker(unittest.TestCase):
    """The picker: lists server-supplied recent directories (GET /api/term/cwds), accepts free
    text, and opens the terminal via the session-less form of POST /api/term/pty ({cwd, cols,
    rows, mode}). Asserted against the asset's source -- there is no JS engine here."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_reuses_the_existing_modal_classes_not_a_second_modal_system(self):
        self.assertIn('pkOverlay.className = "overlay";', self.src)
        self.assertIn('modal.className = "modal cwdmodal";', self.src)
        self.assertIn('mh.className = "mh";', self.src)
        self.assertIn('pkBodyEl.className = "mb cwdmb";', self.src)

    def test_built_on_body_not_inside_the_sidebar_mount(self):
        # .side gets a CSS transform for its phone drawer -- appending the overlay inside it
        # would break position:fixed. Must be a body-level child, like #diffmodal/#msgmodal.
        self.assertIn("document.body.appendChild(pkOverlay);", self.src)
        self.assertNotIn('getElementById("ext_launch_side").appendChild', self.src)

    def test_escape_closes_only_while_this_overlay_is_open(self):
        m = re.search(r'document\.addEventListener\("keydown", function \(ev\) \{\s*'
                       r'if \(ev\.key !== "Escape"\) return;\s*'
                       r'if \(!pkOverlay \|\| pkOverlay\.style\.display !== "flex"\) return;\s*'
                       r'closePicker\(\);', self.src)
        self.assertIsNotNone(m)

    def test_backdrop_click_closes(self):
        self.assertIn("if (ev.target === pkOverlay) closePicker();", self.src)

    def test_opening_closes_the_phone_drawer_first(self):
        # On a phone, these buttons only exist inside the open sidebar drawer (.side, z-index
        # 60); the picker overlay reuses app.css's shared .overlay class (z-index 50), so a
        # still-open drawer would sit on top of it and hide it entirely. openPicker() must close
        # the drawer before showing the overlay -- checked by requiring the closeDrawer() call to
        # appear before pkOverlay.style.display is set to "flex" inside the function body.
        start = self.src.index("function openPicker(mode)")
        end = self.src.index("function showPickerBusy()")
        body = self.src[start:end]
        self.assertIn("closeDrawer()", body)
        self.assertLess(body.index("closeDrawer()"), body.index('pkOverlay.style.display = "flex"'))

    def test_lists_recent_dirs_from_the_server_owned_route(self):
        self.assertIn('fetch("/api/term/cwds")', self.src)

    def test_label_and_path_are_escaped_before_reaching_the_dom(self):
        self.assertIn("esc(p)", self.src)
        self.assertIn("esc(label)", self.src)

    def test_missing_cwds_route_degrades_to_free_text_not_a_hang(self):
        self.assertIn("cwds: [], note: note", self.src)
        self.assertIn("aren't available on this server yet", self.src)

    def test_free_text_is_trimmed(self):
        self.assertIn("function pickDirectory(raw, mode)", self.src)
        fn_start = self.src.index("function pickDirectory(raw, mode)")
        fn_body = self.src[fn_start:fn_start + 400]
        self.assertIn(".trim()", fn_body)

    def test_free_text_never_invents_a_home_directory_for_a_leading_tilde(self):
        # The client must not fabricate its own idea of "home" (conventions rule 5: never invent
        # data the server should supply) -- no regex/string substitution of a leading "~"
        # anywhere in this file; the raw text (trimmed only) is what's sent, and the server
        # expands it (a comment here may mention *why*, but the code itself must not rewrite it).
        self.assertNotIn("replace(/^~", self.src)
        self.assertNotIn('path.replace("~"', self.src)

    def test_posts_the_session_less_pty_route_with_cwd_and_mode(self):
        self.assertIn('fetch("/api/term/pty"', self.src)
        self.assertIn("cwd: path", self.src)
        self.assertIn("mode: mode", self.src)
        self.assertIn("cols: 100, rows: 30", self.src)

    def test_bad_path_error_surfaces_inline_not_silently(self):
        self.assertIn("function showPickerError(msg)", self.src)
        self.assertIn("res.j && res.j.error", self.src)
        self.assertIn("err.textContent = msg;", self.src)   # never innerHTML for server text

    def test_404_and_403_on_pty_get_readable_messages(self):
        self.assertIn("isn't available on this server yet", self.src)
        self.assertIn("in-browser terminal is disabled", self.src)

    def test_success_reuses_the_existing_standalone_tab_path(self):
        # Reuses ext_vt.js's own ?tty= standalone route (see ext_vt.js's openNewTab/
        # bootStandalone) instead of duplicating its terminal renderer in this file.
        self.assertIn('"?tty=" + encodeURIComponent(res.j.tty)', self.src)
        self.assertIn("window.open(url", self.src)


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


class TestSidebarMount(unittest.TestCase):
    """index.html's own mount point, added the same way Step 0 added #ext_launch/#ext_run/
    #ext_vt: a single empty div, filled by ext_launch.js. Placed immediately above the "search
    sessions…" box, inside .sidehead."""

    def setUp(self):
        self.html = open(_INDEX_HTML, encoding="utf-8").read()

    def test_mount_exists(self):
        self.assertIn("<div id=ext_launch_side></div>", self.html)

    def test_mount_sits_in_the_sidehead_immediately_above_the_search_box(self):
        sidehead_idx = self.html.index("class=sidehead")
        mount_idx = self.html.index("id=ext_launch_side")
        searchbox_idx = self.html.index("class=searchbox")
        search_idx = self.html.index("id=q ")
        self.assertLess(sidehead_idx, mount_idx)
        self.assertLess(mount_idx, searchbox_idx)
        self.assertLess(mount_idx, search_idx)

    def test_detail_pane_mount_is_unchanged(self):
        # the four-button detail-pane mount from Step 0 is untouched -- only the sidebar gained
        # a new mount, nothing was renamed or removed.
        self.assertIn("<div id=ext_launch></div>", self.html)
        self.assertIn("<div id=ext_run></div>", self.html)
        self.assertIn("<div id=ext_vt></div>", self.html)


class TestRouteRegistered(unittest.TestCase):
    def test_open_terminal_registered_into_extra_post(self):
        from aitracker import server
        self.assertIs(server.EXTRA_POST.get("/api/term/open"), term_launch.open_terminal)


_APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "aitracker", "web", "app.js")


class TestSidebarPollCarriesTermCount(unittest.TestCase):
    """app.js's global `termCount` and the `SIDE_EXT` hook array (parallel to the existing `EXT`
    array, but fired after every SIDEBAR poll -- loadSide() -- not just while a session is
    selected). Asserted against the asset's source: there is no JS engine here."""

    def setUp(self):
        self.src = open(_APP_JS, encoding="utf-8").read()

    def test_term_count_global_declared(self):
        self.assertIn("let termCount=null;", self.src)

    def test_side_ext_array_declared(self):
        self.assertIn("const SIDE_EXT=[];", self.src)

    def test_loadside_reads_the_header_into_term_count(self):
        i = self.src.index("async function loadSide()")
        seg = self.src[i:i + 700]
        self.assertIn('res.headers.get("X-Term-Count")', seg)
        self.assertIn("termCount=", seg)

    def test_loadside_falls_back_to_null_when_header_absent(self):
        # fetch's Headers.get() returns null, not undefined, for a missing header -- the ternary
        # must check against that, not just falsiness (0 is a valid, falsy count that must NOT
        # collapse to null).
        i = self.src.index("async function loadSide()")
        seg = self.src[i:i + 700]
        self.assertIn("tc!==null", seg)

    def test_loadside_fires_side_ext_after_rendering(self):
        i = self.src.index("async function loadSide()")
        end = self.src.index("\n}", i)
        body = self.src[i:end]
        self.assertIn("SIDE_EXT.forEach", body)
        # renderSide() must run first -- SIDE_EXT hooks (the badge) rebuild off DOM renderSide
        # just produced, not the other way around.
        self.assertLess(body.index("renderSide();"), body.index("SIDE_EXT.forEach"))

    def test_no_second_polling_timer_was_introduced(self):
        # the gap this closes is explicitly about NOT adding a new timer -- the only two
        # setInterval calls in the whole SPA must still be the pre-existing sidebar (5s) and
        # per-session (2s) polls.
        self.assertEqual(self.src.count("setInterval("), 2)

    def test_no_recursive_settimeout_poll_disguised_as_a_one_shot_timer(self):
        """Adversarial review finding: `count("setInterval(") == 2` alone stays green if a SECOND
        poll is added shaped as a self-rescheduling `setTimeout` instead of `setInterval` -- a
        function like `function f(){ fetch(...); ...; setTimeout(f, N); }` never adds a literal
        "setInterval(" anywhere, so the count-based assertion above cannot see it. This walks every
        named function in app.js (brace-matched, not regex-guessed) and flags any whose body BOTH
        calls `fetch(` and reschedules ITSELF via `setTimeout(<its own name>` -- the exact
        fingerprint of a recursive polling loop. Legitimate one-shot timers in this file (the
        180ms search debounce, toast auto-dismiss, "✓ Copied" reverts, flash-class cleanup) all
        pass: none of them references its own enclosing function name inside a setTimeout call, so
        none of them is caught here.

        This is still a structural/source-text check, not an executing one -- app.js is the SPA's
        state/poll layer (not a pure DOM function), so it doesn't fit this repo's node/DOM-exec
        harness pattern the way aitracker/web/ext_launch.js's renderTermBadge does (see
        TestTermCountBadgeClientExecuted below). It is, however, a materially stronger structural
        check than a bare setInterval() count: it inspects what each function's body actually DOES
        (fetch + self-reschedule), not just which timer API name appears in the file.
        """
        offenders = []
        for name, body in _iter_named_functions(self.src):
            if "fetch(" in body and re.search(r"setTimeout\(\s*" + re.escape(name) + r"\b", body):
                offenders.append(name)
        self.assertEqual(offenders, [],
                          "recursive setTimeout-driven fetch poll found in: %r" % offenders)

    def test_known_pollers_still_use_setinterval_not_a_recursive_settimeout(self):
        # Belt and braces on the same defect from the other direction: the two functions the
        # legitimate pollers actually call (poll/loadSide, scheduled via setInterval at start()/
        # track()) must not themselves contain ANY setTimeout call -- if a future edit converted
        # either to self-rescheduling via setTimeout, this catches it even before it grows a
        # fetch() call of its own (which is what the offender-scan above keys on).
        seen = set()
        for name, body in _iter_named_functions(self.src):
            if name in ("poll", "loadSide"):
                seen.add(name)
                self.assertNotIn("setTimeout(", body, "%s must not self-reschedule" % name)
        self.assertEqual(seen, {"poll", "loadSide"})


class TestTermCountBadgeClient(unittest.TestCase):
    """The badge itself (aitracker/web/ext_launch.js): rendered from the SERVER's number,
    absent (not "0") when the server omits it, rides the existing sidebar poll, and is never
    host-gated. Asserted against the asset's source, same as the classes above."""

    def setUp(self):
        self.src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()

    def test_registers_into_side_ext_not_a_new_timer(self):
        self.assertIn("SIDE_EXT.push(renderTermBadge);", self.src)
        self.assertNotIn("setInterval", self.src)
        # Also forbid setTimeout outright: this file has zero timer usage today (the badge rides
        # app.js's existing sidebar poll via SIDE_EXT), so a recursive `setTimeout`-driven poll
        # smuggled in here -- which a bare setInterval-count check elsewhere can't see, since it
        # never touches that literal -- is caught immediately by this file containing the string
        # at all, with no need to reason about self-reference the way app.js's check must.
        self.assertNotIn("setTimeout", self.src)

    def test_never_fetches_term_list_outside_the_panel(self):
        # the panel itself (window.ExtVT.manage()) owns GET /api/term/list -- this file must
        # never call it directly, on a tick or otherwise; the count comes from app.js's
        # X-Term-Count-derived `termCount` global instead. A comment may name the route (to
        # explain why it's avoided); actually fetching it is what must never appear.
        self.assertNotIn('fetch("/api/term/list', self.src)
        self.assertNotIn("fetch('/api/term/list", self.src)

    def test_badge_reads_the_server_global_not_a_recomputed_value(self):
        start = self.src.index("function renderTermBadge()")
        end = self.src.index("\n  }", start)
        body = self.src[start:end]
        self.assertIn("termCount", body)
        # it must not derive its own count from anything DOM/session-shaped -- only the one
        # server-supplied number, formatted.
        self.assertNotIn("sessions.", body)
        self.assertNotIn(".length", body)

    def test_absent_not_zero_when_server_omits_the_count(self):
        start = self.src.index("function renderTermBadge()")
        end = self.src.index("\n  }", start)
        body = self.src[start:end]
        # null (not a number) removes/never creates the badge element entirely
        self.assertIn('typeof termCount !== "number"', body)
        self.assertIn("badge.remove()", body)
        # the zero case is handled separately, further down the same function, and must still
        # render (not be folded into the same early-return as the absent case)
        self.assertNotIn("termCount === 0", body[:body.index("badge.remove()")])

    def test_badge_never_gated_by_host(self):
        start = self.src.index("function renderTermBadge()")
        end = self.src.index("\n  }", start)
        body = self.src[start:end]
        self.assertNotIn("location.hostname", body)
        self.assertNotIn("localOnly", body)

    def test_badge_distinguishes_zero_from_positive_counts(self):
        start = self.src.index("function renderTermBadge()")
        end = self.src.index("\n  }", start)
        body = self.src[start:end]
        self.assertIn('classList.toggle("live", termCount > 0)', body)

    def test_build_side_controls_repaints_the_badge_after_rebuilding_the_button(self):
        # the button's innerHTML is fully replaced on every buildSideControls() call (e.g. a
        # rename-free re-render never happens today, but nothing prevents a future one) -- the
        # badge element would be silently destroyed along with it unless repainted right after.
        start = self.src.index("function buildSideControls()")
        end = self.src.index("function renderTermBadge()")
        body = self.src[start:end]
        self.assertIn("renderTermBadge();", body)


# ===== executing harness for renderTermBadge (aitracker/web/ext_launch.js) =====================
# TestTermCountBadgeClient above (and the classes before it) only ever `assertIn`/`assertNotIn`
# against ext_launch.js's SOURCE TEXT -- it can confirm the shape of the fix (which literal guard
# appears, which classList call is present) but it never actually RUNS renderTermBadge, so it
# cannot fail against a real behavioural bug. That is exactly how a real data-loss bug shipped
# once already in this repo's terminal work: a double-click that SIGKILLed every running terminal
# without ever showing the confirmation sailed past 15 source-text-grep tests, because none of
# them executed the code (see tests/test_term_vt_exec.py's own module docstring for the full
# account, and its _MANAGER_MOCKS-based tests for the fix). This section closes the same class of
# gap for renderTermBadge specifically: it slices the real function verbatim out of the shipped
# ext_launch.js (never retyped) and executes it under Node against a minimal stub DOM, following
# the extraction/`_run_node` pattern tests/test_term_vt_exec.py already established for ext_vt.js.
#
# Concretely, this closes two named weaknesses from that source-text suite:
#   - test_absent_not_zero_when_server_omits_the_count only checks that the literal string
#     "termCount === 0" does not appear in the source before "badge.remove()". A guard WIDENED to
#     `!termCount` (which also treats a legitimate 0 as absent) contains that literal exactly as
#     little as the correct `typeof termCount !== "number" || !isFinite(termCount)` guard does --
#     the test cannot tell them apart. Running the real function against termCount===0 can.
#   - test_no_second_polling_timer_was_introduced (TestSidebarPollCarriesTermCount, above) counted
#     literal setInterval() calls, which a recursive setTimeout poll would not touch at all; see
#     the strengthened structural checks added next to it for that half of the gap.
#
# Node is NOT a dependency of this project (CLAUDE.md: "stdlib only"; conventions.md rule 2) --
# this whole section is skipped when `node` isn't on PATH, so `make check` stays green on a
# machine without it, exactly like tests/test_term_vt_exec.py's own `_HAS_NODE` gate.
_HAS_NODE = shutil.which("node") is not None


def _run_node(js_source):
    """Writes `js_source` to a temp file, runs it with `node`, and returns the JSON the script's
    own final `console.log(JSON.stringify(...))` printed. Identical contract to
    tests/test_term_vt_exec.py's own `_run_node` (kept as a self-contained duplicate here rather
    than imported, so this file's node harness has no import-time dependency on that module)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(
            "node harness exited %d\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (proc.returncode, proc.stdout, proc.stderr)
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise AssertionError(
            "could not parse JSON from node harness output: %r\nfull stdout:\n%s\nstderr:\n%s"
            % (e, proc.stdout, proc.stderr)
        )


def _extract_render_term_badge():
    """Slices the real `renderTermBadge` function verbatim out of the shipped ext_launch.js, by
    literal span from its declaration through the first dedent back to its own 2-space indent
    level -- the same "\\n  }" fixed-indent technique TestTermCountBadgeClient above already
    relies on (13 existing source-text tests depend on that same boundary being correct), so this
    reuses a boundary already validated rather than inventing a second extraction strategy."""
    src = open(_EXT_LAUNCH_JS, encoding="utf-8").read()
    start = src.index("function renderTermBadge() {")
    end = src.index("\n  }", start) + len("\n  }")
    return src[start:end]


# Minimal fake DOM: exactly the surface renderTermBadge touches (document.getElementById/
# createElement, element id/className/textContent/title, classList.add/remove/toggle/contains,
# appendChild, and Element.remove()'s real semantics -- detach from whatever parent recorded it).
# Mirrors tests/test_term_vt_exec.py's own `__makeEl` helper in spirit (same shape: a plain object
# with a hand-rolled classList), scoped down to only what this one function needs.
_BADGE_DOM_HARNESS = """
'use strict';

function __makeEl(tag) {
  var classes = new Set();
  var el = {
    tagName: tag, id: '', className: '', textContent: '', title: '',
    parentNode: null, children: [],
    appendChild: function (child) { child.parentNode = el; el.children.push(child); return child; },
    remove: function () {
      if (el.parentNode) {
        var i = el.parentNode.children.indexOf(el);
        if (i !== -1) el.parentNode.children.splice(i, 1);
        el.parentNode = null;
      }
    },
  };
  el.classList = {
    add: function (c) { classes.add(c); },
    remove: function (c) { classes.delete(c); },
    toggle: function (c, force) {
      if (force === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); }
      else if (force) classes.add(c); else classes.delete(c);
    },
    contains: function (c) { return classes.has(c); },
  };
  return el;
}

var __root = { children: [] };
function __findById(nodes, id) {
  for (var i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) return nodes[i];
    var found = __findById(nodes[i].children, id);
    if (found) return found;
  }
  return null;
}
var document = {
  createElement: function (tag) { return __makeEl(tag); },
  getElementById: function (id) { return __findById(__root.children, id); },
};

// The one pre-existing element renderTermBadge requires ("if (!mt) return;" is the early-out for
// its ABSENCE, not exercised here -- every test below wants the badge logic to actually run).
var mt = __makeEl('button');
mt.id = 'sidemanagetermbtn';
__root.children.push(mt);

var termCount = null;   // app.js's real global; each test overwrites this before calling render
"""


def _badge_observation_snippet():
    """Appended after each renderTermBadge() call in a test script: reports everything the
    assertions below need in one JSON blob, including `mtChildCount` (how many children the
    button actually has right now) -- the guard against a badge getting appended TWICE across
    repeated calls instead of being reused."""
    return """
var __badge = document.getElementById('sidetermbadge');
console.log(JSON.stringify({
  badgeExists: !!__badge,
  text: __badge ? __badge.textContent : null,
  live: __badge ? __badge.classList.contains('live') : null,
  title: __badge ? __badge.title : null,
  className: __badge ? __badge.className : null,
  mtChildCount: mt.children.length,
}));
"""


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class TestTermCountBadgeExecuted(unittest.TestCase):
    """Executes the real renderTermBadge -- see the module-level comment block above this class
    for why TestTermCountBadgeClient's source-text tests can't catch what these do."""

    @classmethod
    def setUpClass(cls):
        cls._fn_src = _extract_render_term_badge()

    def _run(self, term_count_js_literal, extra=""):
        script = (
            _BADGE_DOM_HARNESS
            + self._fn_src
            + "\ntermCount = %s;\n" % term_count_js_literal
            + extra
            + "renderTermBadge();\n"
            + _badge_observation_snippet()
        )
        return _run_node(script)

    def test_zero_count_renders_a_badge_showing_0_and_is_not_removed(self):
        # The exact case the source-text guard-literal check cannot see (see module comment):
        # termCount === 0 is a NUMBER, so the real guard (`typeof !== "number" || !isFinite`) must
        # NOT treat it as absent. A regression widened to `!termCount` would fail this.
        r = self._run("0")
        self.assertTrue(r["badgeExists"], "a 0 count must still render a badge, not remove it")
        self.assertEqual(r["text"], "0")
        self.assertFalse(r["live"], "0 running terminals must not get the 'live' highlight")
        self.assertEqual(r["mtChildCount"], 1)
        self.assertIn("0 terminals running now", r["title"])

    def test_null_count_renders_no_badge_at_all(self):
        # Server omitted X-Term-Count (feature off, or gated without TRACKER_AUTH) -> app.js's
        # loadSide() leaves termCount === null. No badge must exist -- not a "0" badge.
        r = self._run("null")
        self.assertFalse(r["badgeExists"])
        self.assertEqual(r["mtChildCount"], 0)

    def test_positive_count_renders_the_number_and_the_live_class(self):
        r = self._run("3")
        self.assertTrue(r["badgeExists"])
        self.assertEqual(r["text"], "3")
        self.assertTrue(r["live"])
        self.assertIn("3 terminals running now", r["title"])

    def test_singular_terminal_wording_for_count_one(self):
        r = self._run("1")
        self.assertEqual(r["text"], "1")
        self.assertTrue(r["live"])
        self.assertIn("1 terminal running now", r["title"])
        self.assertNotIn("1 terminals", r["title"])

    def test_two_digit_count_renders_correctly(self):
        # Reviewer-flagged legibility case: nothing in renderTermBadge truncates/formats the
        # number specially, but this proves it end to end rather than assuming String(12) is fine.
        r = self._run("12")
        self.assertTrue(r["badgeExists"])
        self.assertEqual(r["text"], "12")
        self.assertTrue(r["live"])
        self.assertIn("12 terminals running now", r["title"])
        self.assertEqual(r["mtChildCount"], 1)

    def test_transition_sequence_null_then_3_then_0_then_null(self):
        # This runs on every sidebar poll (SIDE_EXT.forEach), so the real question is whether
        # repeated calls across a changing count leave the DOM correct at EVERY step -- and never
        # accumulate a second badge element inside the button.
        script = _BADGE_DOM_HARNESS + self._fn_src + """
var __steps = [];
function __observe(label) {
  var b = document.getElementById('sidetermbadge');
  __steps.push({
    label: label,
    badgeExists: !!b,
    text: b ? b.textContent : null,
    live: b ? b.classList.contains('live') : null,
    mtChildCount: mt.children.length,
  });
}
termCount = null; renderTermBadge(); __observe('null');
termCount = 3;    renderTermBadge(); __observe('3');
termCount = 0;    renderTermBadge(); __observe('0');
termCount = null; renderTermBadge(); __observe('null2');
console.log(JSON.stringify(__steps));
"""
        steps = {s["label"]: s for s in _run_node(script)}

        self.assertFalse(steps["null"]["badgeExists"])
        self.assertEqual(steps["null"]["mtChildCount"], 0)

        self.assertTrue(steps["3"]["badgeExists"])
        self.assertEqual(steps["3"]["text"], "3")
        self.assertTrue(steps["3"]["live"])
        self.assertEqual(steps["3"]["mtChildCount"], 1)

        self.assertTrue(steps["0"]["badgeExists"], "0 must still render, not disappear")
        self.assertEqual(steps["0"]["text"], "0")
        self.assertFalse(steps["0"]["live"])
        self.assertEqual(steps["0"]["mtChildCount"], 1, "must reuse the existing badge, not add a second one")

        self.assertFalse(steps["null2"]["badgeExists"])
        self.assertEqual(steps["null2"]["mtChildCount"], 0)

    def test_repeated_calls_with_the_same_count_never_duplicate_the_badge(self):
        # A badge appended on every poll instead of reused would be a real, user-visible bug (a
        # growing pile of "3" chips) that no source-text grep could ever catch -- it depends on
        # calling the function more than once. renderTermBadge() runs on EVERY sidebar poll
        # (SIDE_EXT.forEach), so this is the realistic case, not an edge case.
        script = _BADGE_DOM_HARNESS + self._fn_src + """
termCount = 4;
renderTermBadge();
renderTermBadge();
renderTermBadge();
""" + _badge_observation_snippet()
        r = _run_node(script)
        self.assertTrue(r["badgeExists"])
        self.assertEqual(r["text"], "4")
        self.assertEqual(r["mtChildCount"], 1, "three calls must still leave exactly one badge")


if __name__ == "__main__":
    unittest.main()
