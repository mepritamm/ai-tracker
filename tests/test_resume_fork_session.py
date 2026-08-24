"""Tests for the fork-session usability fix.

Claude Code's OWN CLI refuses a plain `claude --resume <sid>` against a session it
considers "currently running as a background agent (bg)." -- that refusal happens
inside the `claude` binary itself, not in ai-tracker. The fix: append `--fork-session`
to the resume argv when (and only when) `sid` names a background-agent session
(the shared session-list shape's `"agent"` key, i.e. entrypoint=sdk-cli) that is
STILL WITHIN the app's own liveness window (`config.LIVE_WINDOW`). A finished agent
session resumes normally -- forking it would hand the user a pointless copy.

The single seam is `term_gate.resume_argv()` (and the `is_live_agent()` it calls).
Both terminal tiers -- term_vt.open_pty (the in-browser PTY) and
term_launch.open_terminal/build_script (the external Terminal/iTerm launch) -- must
go through it, so this file proves both the seam's own logic AND that the two call
sites actually use it and agree.
"""
import json
import os
import tempfile
import time
import unittest

from aitracker import config, term_gate, term_launch, term_vt
from aitracker.providers import claude as _claude


def _write_session(sid, entrypoint, age_seconds, cwd="/tmp"):
    """A minimal Claude session file under config.PROJECTS, with a controlled
    filesystem mtime (list_sessions()/_mtime_and_bg() key liveness off the FILE's
    mtime, not the JSON `timestamp` field -- see providers/claude.py:_mtime_and_bg)."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".jsonl")
    line = {"cwd": cwd, "entrypoint": entrypoint, "timestamp": "2026-06-01T00:00:00Z",
            "message": {"role": "user", "content": "go"}}
    with open(path, "w") as fh:
        fh.write(json.dumps(line) + "\n")
    t = time.time() - age_seconds
    os.utime(path, (t, t))
    return path


class _ResumeArgvBase(unittest.TestCase):
    """Shared fixture: an isolated config.PROJECTS with the meta cache cleared, so one
    test's session files can never leak into another's liveness check."""

    def setUp(self):
        self._projects0 = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        _claude._META_CACHE.clear()

    def tearDown(self):
        config.PROJECTS = self._projects0
        _claude._META_CACHE.clear()


class TestIsLiveAgent(_ResumeArgvBase):
    def test_live_agent_session_is_live_agent(self):
        _write_session("live-agent", "sdk-cli", age_seconds=5)
        self.assertTrue(term_gate.is_live_agent("live-agent"))

    def test_stale_agent_session_is_not_live_agent(self):
        _write_session("stale-agent", "sdk-cli", age_seconds=config.LIVE_WINDOW + 60)
        self.assertFalse(term_gate.is_live_agent("stale-agent"))

    def test_live_non_agent_session_is_not_live_agent(self):
        _write_session("live-human", "cli", age_seconds=5)
        self.assertFalse(term_gate.is_live_agent("live-human"))

    def test_unknown_session_is_not_live_agent(self):
        self.assertFalse(term_gate.is_live_agent("no-such-session"))

    def test_liveness_boundary_matches_config_live_window_not_a_second_threshold(self):
        """Conventions rule 5: one constant, config.LIVE_WINDOW -- not a second,
        hand-rolled threshold reintroduced in term_gate."""
        _write_session("just-inside", "sdk-cli", age_seconds=config.LIVE_WINDOW - 5)
        _write_session("just-outside", "sdk-cli", age_seconds=config.LIVE_WINDOW + 5)
        self.assertTrue(term_gate.is_live_agent("just-inside"))
        self.assertFalse(term_gate.is_live_agent("just-outside"))


class TestResumeArgv(_ResumeArgvBase):
    def test_live_agent_session_yields_fork_session(self):
        _write_session("live-agent", "sdk-cli", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("live-agent"),
                          ["claude", "--resume", "live-agent", "--fork-session"])

    def test_stale_agent_session_does_not_fork(self):
        _write_session("stale-agent", "sdk-cli", age_seconds=config.LIVE_WINDOW + 60)
        self.assertEqual(term_gate.resume_argv("stale-agent"),
                          ["claude", "--resume", "stale-agent"])

    def test_live_non_agent_session_does_not_fork(self):
        _write_session("live-human", "cli", age_seconds=5)
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
        _write_session("live-agent", "sdk-cli", age_seconds=5)
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

    def test_term_launch_build_script_argv_matches_term_gate_resume_argv(self):
        _write_session("live-agent", "sdk-cli", age_seconds=5)
        expected = term_gate.resume_argv("live-agent")
        script = term_launch.build_script("/tmp", "live-agent", "resume", "Terminal", expected)
        self.assertIn(" ".join(expected), script.replace("\\\\", "\\"))  # unescape the doubled backslash-noop
        self.assertIn("--fork-session", script)

    def test_term_launch_open_terminal_computes_the_same_resume_argv(self):
        """open_terminal itself must call term_gate.resume_argv -- not re-derive the
        fork decision -- so this is patched at the point of use and asserted called
        with the exact sid, then the produced script is checked for the flag."""
        _write_session("live-agent", "sdk-cli", age_seconds=5)
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

    def test_stale_agent_neither_call_site_forks(self):
        _write_session("stale-agent", "sdk-cli", age_seconds=config.LIVE_WINDOW + 60)
        spawned = []
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: spawned.append(argv) or term_vt.Pty(tid="t2")
        try:
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "stale-agent", "mode": "resume"})
        finally:
            term_vt.spawn = original_spawn
        self.assertNotIn("--fork-session", spawned[0])

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
            term_launch.open_terminal(h2, None, {"session": "stale-agent", "mode": "resume"})
        finally:
            term_launch.subprocess.run = original_run
        self.assertNotIn("--fork-session", captured["script"])


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
