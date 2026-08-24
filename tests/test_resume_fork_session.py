"""Tests for the fork-session usability fix.

Claude Code's OWN CLI refuses a plain `claude --resume <sid>` against a session it
considers "currently running as a background agent (bg)." -- that refusal happens
inside the `claude` binary itself, not in ai-tracker. docs/claude-resume-command-matrix.md
(live PTY tests against the real CLI) found this refusal fires for EVERY background-agent
status tested ("blocked" and "done" alike, not just "running"), independent of recency --
so the fix is: append `--fork-session` to the resume argv whenever `sid` names a
background-agent session, full stop, no liveness condition.

The single seam is `term_gate.resume_argv()` (and the `is_bg_agent()` it calls, which in
turn calls `registry.is_bg_agent()` -- the seam that resolves ONE session id DIRECTLY
through its owning provider, rather than scanning `all_sessions()`'s top-N-by-mtime list,
which would miss a background agent outside that recency window). Both terminal tiers --
term_vt.open_pty (the in-browser PTY) and term_launch.open_terminal/build_script (the
external Terminal/iTerm launch) -- must go through it, so this file proves both the
seam's own logic AND that the two call sites actually use it and agree.

`is_bg_agent` was previously named `is_live_agent` and additionally required the session
to be inside `config.LIVE_WINDOW` -- see TestIsBgAgent for the tests proving that gate is
gone (a stale background-agent session still forks) and TestIsBgAgentResolvesDirectly for
the top-N-list bug this rename also fixes.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, term_gate, term_launch, term_vt
from aitracker.providers import claude as _claude


def _write_session(sid, entrypoint=None, session_kind=None, age_seconds=5, cwd="/tmp"):
    """A minimal Claude session file under config.PROJECTS, with a controlled filesystem
    mtime. `entrypoint` models an SDK-spawned agent (source == "sdk-cli"); `session_kind`
    models a REAL `claude --bg` agent (sessionKind == "bg") -- providers/claude.py's
    _is_bg_agent() treats either as a background agent."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".jsonl")
    line = {"cwd": cwd, "timestamp": "2026-06-01T00:00:00Z",
            "message": {"role": "user", "content": "go"}}
    if entrypoint is not None:
        line["entrypoint"] = entrypoint
    if session_kind is not None:
        line["sessionKind"] = session_kind
    with open(path, "w") as fh:
        fh.write(json.dumps(line) + "\n")
    t = time.time() - age_seconds
    os.utime(path, (t, t))
    return path


class _ResumeArgvBase(unittest.TestCase):
    """Shared fixture: an isolated config.PROJECTS with the meta cache cleared, so one
    test's session files can never leak into another's."""

    def setUp(self):
        self._projects0 = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        _claude._META_CACHE.clear()

    def tearDown(self):
        config.PROJECTS = self._projects0
        _claude._META_CACHE.clear()


class TestIsBgAgent(_ResumeArgvBase):
    def test_sdk_cli_session_is_bg_agent(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        self.assertTrue(term_gate.is_bg_agent("live-agent"))

    def test_sessionKind_bg_session_is_bg_agent(self):
        """A REAL `claude --bg` agent (sessionKind == "bg"), not just an SDK-spawned one --
        the matrix found this is the field that actually drives the refusal on this
        machine's real background-agent sessions, distinct from entrypoint=sdk-cli."""
        _write_session("real-bg-agent", entrypoint="cli", session_kind="bg", age_seconds=5)
        self.assertTrue(term_gate.is_bg_agent("real-bg-agent"))

    def test_stale_agent_session_is_still_bg_agent(self):
        """The liveness gate is GONE: the matrix found the refusal fires for a "blocked" or
        "done" background agent exactly as much as a "running" one, so an agent session
        older than LIVE_WINDOW must still fork -- this is the opposite assertion of the
        old (now-wrong) is_live_agent behaviour."""
        _write_session("stale-agent", entrypoint="sdk-cli", age_seconds=config.LIVE_WINDOW + 600)
        self.assertTrue(term_gate.is_bg_agent("stale-agent"))

    def test_stale_real_bg_agent_is_still_bg_agent(self):
        _write_session("stale-real-bg", session_kind="bg", age_seconds=config.LIVE_WINDOW + 600)
        self.assertTrue(term_gate.is_bg_agent("stale-real-bg"))

    def test_plain_session_is_not_bg_agent(self):
        _write_session("live-human", entrypoint="cli", age_seconds=5)
        self.assertFalse(term_gate.is_bg_agent("live-human"))

    def test_unknown_session_is_not_bg_agent(self):
        self.assertFalse(term_gate.is_bg_agent("no-such-session"))


class TestIsBgAgentResolvesDirectlyNotViaTopN(_ResumeArgvBase):
    """The other half of the bug this rename fixes: the old implementation scanned
    registry.all_sessions() (top-N by mtime) looking for a matching id, so a background
    agent outside that window was invisible and silently answered False. is_bg_agent must
    resolve the ONE session id directly through its owning provider instead."""

    def test_ignores_all_sessions_entirely(self):
        _write_session("outside-any-list", entrypoint="sdk-cli", age_seconds=5)
        from aitracker import registry
        original = registry.all_sessions
        # Simulate "invisible to the top-N list" -- if is_bg_agent depended on this, it
        # would now answer False no matter what the on-disk session actually is.
        registry.all_sessions = lambda: []
        try:
            self.assertTrue(term_gate.is_bg_agent("outside-any-list"))
        finally:
            registry.all_sessions = original

    def test_provider_is_bg_agent_called_with_the_exact_sid(self):
        from aitracker import registry
        calls = []
        with mock.patch.object(registry.ClaudeProvider, "is_bg_agent",
                                lambda self, sid: calls.append(sid) or True):
            self.assertTrue(registry.is_bg_agent("some-sid"))
        self.assertEqual(calls, ["some-sid"])

    def test_non_claude_provider_defaults_to_false(self):
        from aitracker.registry import PROVIDERS
        prefixed = [p for p in PROVIDERS if p.prefix]
        if not prefixed:
            self.skipTest("no prefixed provider registered")
        from aitracker import registry
        self.assertFalse(registry.is_bg_agent(prefixed[0].prefix + "whatever"))


class TestResumeArgv(_ResumeArgvBase):
    def test_bg_agent_session_yields_fork_session(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("live-agent"),
                          ["claude", "--resume", "live-agent", "--fork-session"])

    def test_stale_agent_session_still_forks(self):
        _write_session("stale-agent", entrypoint="sdk-cli", age_seconds=config.LIVE_WINDOW + 600)
        self.assertEqual(term_gate.resume_argv("stale-agent"),
                          ["claude", "--resume", "stale-agent", "--fork-session"])

    def test_plain_session_does_not_fork(self):
        _write_session("live-human", entrypoint="cli", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("live-human"),
                          ["claude", "--resume", "live-human"])

    def test_unknown_session_does_not_fork(self):
        self.assertEqual(term_gate.resume_argv("no-such-session"),
                          ["claude", "--resume", "no-such-session"])


class TestBothCallSitesAgree(_ResumeArgvBase):
    """The whole point: term_vt (PTY) and term_launch (external Terminal/iTerm) must
    produce the SAME resume command for the SAME session -- not two forks of this
    decision that can drift out of step."""

    def setUp(self):
        super().setUp()
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        term_gate.session_cwd = lambda sid: "/tmp"  # bypass the on-disk cwd check; not what's under test

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0
        super().tearDown()

    def test_term_vt_pty_argv_matches_term_gate_resume_argv(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        spawned = []
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: spawned.append(argv) or term_vt.Pty(tid="t1")
        try:
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "live-agent", "mode": "resume"})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200, obj)
        finally:
            term_vt.spawn = original_spawn
        self.assertEqual(spawned, [term_gate.resume_argv("live-agent")])
        self.assertIn("--fork-session", spawned[0])
        self.assertTrue(obj["forked"])

    def test_term_launch_build_script_argv_matches_term_gate_resume_argv(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        expected = term_gate.resume_argv("live-agent")
        script = term_launch.build_script("/tmp", "live-agent", "resume", "Terminal", expected)
        self.assertIn(" ".join(expected), script.replace("\\\\", "\\"))  # unescape the doubled backslash-noop
        self.assertIn("--fork-session", script)

    def test_term_launch_open_terminal_computes_the_same_resume_argv(self):
        """open_terminal itself must call term_gate.resume_argv -- not re-derive the
        fork decision -- so this is patched at the point of use and asserted called
        with the exact sid, then the produced script is checked for the flag."""
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        calls = []
        real = term_gate.resume_argv

        def spy(sid):
            calls.append(sid)
            return real(sid)
        term_gate.resume_argv = spy
        captured = {}

        def fake_run(argv, **kw):
            captured["script"] = argv[2]  # ["osascript", "-e", script]
            class R:
                returncode = 0
            return R()
        original_run = term_launch.subprocess.run
        term_launch.subprocess.run = fake_run
        try:
            h = _FakeHandler()
            term_launch.open_terminal(h, None, {"session": "live-agent", "mode": "resume"})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200, obj)
        finally:
            term_gate.resume_argv = real
            term_launch.subprocess.run = original_run
        self.assertEqual(calls, ["live-agent"])
        self.assertIn("--fork-session", captured["script"])

    def test_plain_session_neither_call_site_forks(self):
        _write_session("plain-session", entrypoint="cli", age_seconds=5)
        spawned = []
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: spawned.append(argv) or term_vt.Pty(tid="t2")
        try:
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "plain-session", "mode": "resume"})
            obj, _ = h.calls[-1]
        finally:
            term_vt.spawn = original_spawn
        self.assertNotIn("--fork-session", spawned[0])
        self.assertFalse(obj["forked"])

        captured = {}
        def fake_run(argv, **kw):
            captured["script"] = argv[2]
            class R:
                returncode = 0
            return R()
        original_run = term_launch.subprocess.run
        term_launch.subprocess.run = fake_run
        try:
            h2 = _FakeHandler()
            term_launch.open_terminal(h2, None, {"session": "plain-session", "mode": "resume"})
        finally:
            term_launch.subprocess.run = original_run
        # No proactive fork -- but the OPTION-C fallback must still be BUILT INTO the
        # command (see TestBuildScriptFallback in test_term_launch.py for the shape).
        self.assertIn("--fork-session", captured["script"])


class TestRefusalAndMissingTranscriptMarkers(unittest.TestCase):
    """Pins the exact wording docs/claude-resume-command-matrix.md captured from the real
    CLI, so a future wording change fails this suite loudly instead of silently disabling
    term_vt.py's Option-C backstop (see that module's _resume_backstop)."""

    # Verbatim from the matrix's "Verbatim captured output" section, including its
    # original line-wrapping -- proves the whitespace-normalising match survives that wrap.
    VERBATIM_REFUSAL = (
        "Session e4e6bdd6-937b-4b4a-ac2f-9a8c7789e5b7 is currently running as a\n"
        "background agent (bg). Use `claude agents` to find and attach to it, or add\n"
        "--fork-session to branch off a copy.\n"
    )
    VERBATIM_MISSING_TRANSCRIPT = (
        "No conversation found with session ID: 00000000-0000-0000-0000-000000000000\n"
    )

    def test_pinned_refusal_wording_is_recognised(self):
        self.assertTrue(term_gate.looks_like_bg_refusal(self.VERBATIM_REFUSAL))
        self.assertTrue(term_gate.looks_like_bg_refusal(self.VERBATIM_REFUSAL.encode()))

    def test_pinned_missing_transcript_wording_is_recognised(self):
        self.assertTrue(term_gate.looks_like_missing_transcript(self.VERBATIM_MISSING_TRANSCRIPT))
        self.assertTrue(
            term_gate.looks_like_missing_transcript(self.VERBATIM_MISSING_TRANSCRIPT.encode()))

    def test_unrelated_output_matches_neither(self):
        text = "bash-3.2$ ls\nfile1  file2\nbash-3.2$ "
        self.assertFalse(term_gate.looks_like_bg_refusal(text))
        self.assertFalse(term_gate.looks_like_missing_transcript(text))

    def test_partial_output_does_not_false_positive(self):
        """A resume that's merely printing something ABOUT agents (e.g. shell history,
        a banner) must not be mistaken for the refusal."""
        text = "Tip: use `claude agents` to manage your background agents.\n"
        self.assertFalse(term_gate.looks_like_bg_refusal(text))

    def test_markers_are_substrings_of_the_verbatim_capture(self):
        """Cheap consistency check tying the matching constants back to the doc quote."""
        normalized = " ".join(self.VERBATIM_REFUSAL.split())
        self.assertIn(term_gate.REFUSAL_MARKER, normalized)
        normalized_missing = " ".join(self.VERBATIM_MISSING_TRANSCRIPT.split())
        self.assertIn(term_gate.MISSING_TRANSCRIPT_MARKER, normalized_missing)


class _FakeHeaders:
    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler across both routes: client_address for
    term_launch's loopback check, headers for term_gate's origin check, _json()
    recorded for assertions."""

    def __init__(self, client_ip="127.0.0.1", headers=None):
        self.client_address = (client_ip, 54321)
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


if __name__ == "__main__":
    unittest.main()
