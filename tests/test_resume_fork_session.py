"""Tests for the fork-session usability fix -- and its correction.

Claude Code's OWN CLI refuses a plain `claude --resume <sid>` against a session it
considers "currently running as a background agent (bg)." -- that refusal happens
inside the `claude` binary itself, not in ai-tracker. docs/claude-resume-command-matrix.md
(live PTY tests against the real CLI) found this refusal fires for EVERY background-agent
status tested ("blocked" and "done" alike, not just "running"), independent of recency.

The FIRST fix appended `--fork-session` to the resume argv proactively, whenever the
SESSION'S OWN TRANSCRIPT claimed to be a background agent (sessionKind == "bg" or
entrypoint == "sdk-cli"). That turned out to be OVER-BROAD: a live proof against this
machine's real `claude` binary found a session that still carried sessionKind == "bg" in
its transcript, yet a plain `claude --resume <id>` opened it normally -- because `claude`
had already deregistered it as a background agent (confirmed via `claude agents --json`
no longer listing it). Proactively forking that session would have handed the user a COPY
under a new session id when a plain resume would have reopened their actual conversation
-- silently losing continuity, which is worse than a recoverable refusal.

The CORRECTED behaviour (this file): `term_gate.resume_argv()` no longer appends
`--fork-session` proactively AT ALL -- see that function's docstring for the measured
`claude agents --json` latency (750-960ms/call on this machine) that ruled out a live
registry cross-check as a synchronous fast path too. Correctness now rests entirely on
two independent backstops that already run unconditionally on every `mode="resume"`
open, regardless of anything term_gate.resume_argv decides:
  - term_vt.py's `_resume_backstop` (Tier 2, in-browser PTY): watches the child's own
    output for the refusal and retries once with --fork-session.
  - term_launch.py's `build_script` (Tier 3, external Terminal/iTerm): always wraps a
    resume argv lacking --fork-session in a shell-level
    `(<resume> || <resume> --fork-session)` fallback.

Both terminal tiers -- term_vt.open_pty and term_launch.open_terminal/build_script --
call term_gate.resume_argv() as the single seam, so this file proves both the seam's own
(now much simpler) logic AND that the two call sites actually use it and agree, never
re-deriving the decision themselves.

The transcript classifier that used to feed the fork decision (providers/claude.py's
`_is_bg_agent`) still exists and is still correct -- it now drives ONLY the sidebar's 🤖
badge (see tests/test_selfcheck.py), a DIFFERENT concern with a DIFFERENT correctness
requirement: a session that WAS a background agent should stay badged as one forever,
which is exactly why the badge stays transcript-based while the fork decision could not.
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
    _is_bg_agent() treats either as a background agent for BADGE purposes. Neither any
    longer has any bearing on term_gate.resume_argv()'s fork decision -- that's the
    behaviour this file pins."""
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


class TestResumeArgvNeverForksProactively(_ResumeArgvBase):
    """The core regression test for the over-broad-detection bug: resume_argv() must
    return the plain resume argv for EVERY session -- an sdk-cli agent, a real
    `sessionKind:"bg"` agent, a stale one of either, an ordinary session, and an unknown
    one -- since the transcript can no longer be trusted to mean "still forkable". This
    is intentionally the OPPOSITE of what this suite asserted before the correction."""

    def test_sdk_cli_session_does_not_fork(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("live-agent"),
                          ["claude", "--resume", "live-agent"])

    def test_sessionKind_bg_session_does_not_fork(self):
        """A REAL `claude --bg` agent (sessionKind == "bg") -- the matrix found this is
        the field that drives the refusal WHILE the CLI still has it registered, but a
        live proof against this machine found sessionKind alone outlives that
        registration, so it must not trigger a proactive fork either."""
        _write_session("real-bg-agent", entrypoint="cli", session_kind="bg", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("real-bg-agent"),
                          ["claude", "--resume", "real-bg-agent"])

    def test_stale_agent_session_does_not_fork(self):
        _write_session("stale-agent", entrypoint="sdk-cli", age_seconds=config.LIVE_WINDOW + 600)
        self.assertEqual(term_gate.resume_argv("stale-agent"),
                          ["claude", "--resume", "stale-agent"])

    def test_stale_real_bg_agent_does_not_fork(self):
        _write_session("stale-real-bg", session_kind="bg", age_seconds=config.LIVE_WINDOW + 600)
        self.assertEqual(term_gate.resume_argv("stale-real-bg"),
                          ["claude", "--resume", "stale-real-bg"])

    def test_plain_session_does_not_fork(self):
        _write_session("live-human", entrypoint="cli", age_seconds=5)
        self.assertEqual(term_gate.resume_argv("live-human"),
                          ["claude", "--resume", "live-human"])

    def test_unknown_session_does_not_fork(self):
        self.assertEqual(term_gate.resume_argv("no-such-session"),
                          ["claude", "--resume", "no-such-session"])

    def test_resume_argv_does_not_touch_the_filesystem_at_all(self):
        """The whole point of dropping the transcript classifier: resume_argv() no
        longer needs to read anything about `sid` to decide -- it's a pure function of
        the id now. Proven by pointing config.PROJECTS at an empty dir (no session file
        for `sid` exists anywhere) and getting the identical plain argv back."""
        self.assertEqual(term_gate.resume_argv("anything-at-all"),
                          ["claude", "--resume", "anything-at-all"])


class TestTranscriptClassifierNoLongerReachableFromTheFastPath(_ResumeArgvBase):
    """The seam this bug lived in is GONE, not just bypassed: `registry.is_bg_agent`,
    `Provider.is_bg_agent` and `ClaudeProvider.is_bg_agent` were removed outright (they
    existed solely to serve term_gate's fork decision), so nothing can wire the
    transcript classifier back into resume_argv by simply calling an existing seam --
    reintroducing it now requires writing new code, not un-commenting a call."""

    def test_term_gate_has_no_is_bg_agent(self):
        self.assertFalse(hasattr(term_gate, "is_bg_agent"))

    def test_registry_has_no_is_bg_agent(self):
        from aitracker import registry
        self.assertFalse(hasattr(registry, "is_bg_agent"))

    def test_provider_base_has_no_is_bg_agent(self):
        from aitracker.providers.base import Provider
        self.assertFalse(hasattr(Provider, "is_bg_agent"))

    def test_claude_provider_has_no_is_bg_agent(self):
        from aitracker.registry import ClaudeProvider
        self.assertFalse(hasattr(ClaudeProvider, "is_bg_agent"))

    def test_badge_classifier_is_unaffected(self):
        """providers/claude.py's `_is_bg_agent` -- the 🤖 badge classifier -- must still
        exist and still work exactly as before; only the FORK decision changed."""
        _write_session("badge-agent", entrypoint="sdk-cli", age_seconds=5)
        sm = _claude._session_meta(_claude.find_session("badge-agent"))
        self.assertTrue(_claude._is_bg_agent(sm))


class TestBothCallSitesAgree(_ResumeArgvBase):
    """The whole point: term_vt (PTY) and term_launch (external Terminal/iTerm) must
    produce the SAME resume command for the SAME session -- not two forks of this
    decision that can drift out of step. Post-correction, that command is identical
    (the plain resume) for every session; what still differs, correctly, is that each
    tier's OWN backstop is what can fork it later."""

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

    def test_term_vt_pty_argv_matches_term_gate_resume_argv_and_does_not_fork(self):
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        spawned = []
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: spawned.append(argv) or term_vt.Pty(tid="t1")
        try:
            with mock.patch.object(term_vt, "_resume_backstop"):
                h = _FakeHandler()
                term_vt.open_pty(h, None, {"session": "live-agent", "mode": "resume"})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200, obj)
        finally:
            term_vt.spawn = original_spawn
        self.assertEqual(spawned, [term_gate.resume_argv("live-agent")])
        self.assertNotIn("--fork-session", spawned[0])
        self.assertFalse(obj["forked"])

    def test_term_launch_build_script_still_carries_the_fork_fallback(self):
        """resume_argv() no longer forks, so build_script's OWN `(<resume> || <resume>
        --fork-session)` fallback (Tier 3's independent backstop, unaffected by this
        correction) must still be present -- this is what actually protects a real
        background-agent resume through the external-Terminal tier now."""
        _write_session("live-agent", entrypoint="sdk-cli", age_seconds=5)
        expected = term_gate.resume_argv("live-agent")
        self.assertNotIn("--fork-session", expected)
        script = term_launch.build_script("/tmp", "live-agent", "resume", "Terminal", expected)
        self.assertIn(" ".join(expected), script.replace("\\\\", "\\"))  # unescape the doubled backslash-noop
        self.assertIn("--fork-session", script)  # the || fallback, not a proactive fork

    def test_term_launch_open_terminal_computes_the_same_resume_argv(self):
        """open_terminal itself must call term_gate.resume_argv -- not re-derive the
        fork decision -- so this is patched at the point of use and asserted called
        with the exact sid, then the produced script is checked for the fallback."""
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
        self.assertIn("--fork-session", captured["script"])  # the || fallback

    def test_plain_session_neither_call_site_forks(self):
        _write_session("plain-session", entrypoint="cli", age_seconds=5)
        spawned = []
        original_spawn = term_vt.spawn
        term_vt.spawn = lambda cwd, argv, cols, rows: spawned.append(argv) or term_vt.Pty(tid="t2")
        try:
            with mock.patch.object(term_vt, "_resume_backstop"):
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
    term_vt.py's Option-C backstop (see that module's _resume_backstop) -- which, post-
    correction, is the ONLY thing that decides a fork for the in-browser PTY tier."""

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

    # The SAME refusal as VERBATIM_REFUSAL, captured from a REAL pty (python -m pty forking
    # `claude --resume <a-live-bg-agent-id>`) rather than from a pipe. Ink renders it by jumping
    # the cursor to each word's column instead of emitting spaces, so the plain-text capture
    # above is NOT what the backstop actually receives -- and REFUSAL_MARKER is not a substring
    # of these bytes until term_gate._ANSI_RE has stripped the escapes. This is the regression:
    # every pinned-wording test passed while the live terminal never fired the backstop once.
    PTY_REFUSAL = (
        b"\x1b[?25l\x1b[?2004h\x1b[>0q\x1b[c\x1b[>4m\x1b[<u\x1b[?1004l\x1b[?2004l"
        b"Session\x1b[9Ge4e6bdd6-937b-4b4a-ac2f-9a8c7789e5b7\x1b[46Gis\x1b[49Gcurrently"
        b"\x1b[59Grunning\x1b[67Gas\x1b[70Ga\r\r\n"
        b"background\x1b[12Gagent\x1b[18G(bg).\x1b[24GUse\x1b[28G`claude\x1b[36Gagents`"
        b"\x1b[44Gto\x1b[47Gfind\x1b[52Gand\x1b[56Gattach\x1b[63Gto\x1b[66Git,\x1b[70Gor"
        b"\x1b[73Gadd\r\r\n"
        b"--fork-session\x1b[16Gto\x1b[19Gbranch\x1b[26Goff\x1b[30Ga\x1b[32Gcopy.\r\r\n"
        b"\x1b[?25h\x1b[?1000l\x1b(B\x0f\x1b[?25h"
    )

    # Seconds from spawn to exit(1), measured on a real pty against a genuine background-agent
    # id (refusal bytes printed at 2.05s, waitpid reaped code=1 at 2.61s). The backstop can only
    # retry once it has observed BOTH the marker and a non-zero rc, so the window has to clear
    # this -- at the old 2.5 it expired ~0.1s early and _retry_with_fork never ran.
    MEASURED_REFUSAL_EXIT_SECONDS = 2.61

    def test_backstop_window_clears_the_measured_refusal_exit(self):
        """The OTHER half of the bug: a correct matcher still can't fire if the watcher has
        already given up. Every other backstop test mocks BACKSTOP_WINDOW down to keep the
        suite fast, so this is the only thing pinning the shipped value."""
        from aitracker import term_vt
        self.assertGreater(term_vt.BACKSTOP_WINDOW, self.MEASURED_REFUSAL_EXIT_SECONDS * 2,
                           "BACKSTOP_WINDOW must leave real headroom over a cold-start refusal")

    # The init frame a real `claude --resume` writes before it prints anything readable.
    PTY_INIT_BURST = (b"\x1b7\x1b[r\x1b8\x1b[?25h\x1b[?25l\x1b[?2004h\x1b[?1049h"
                      b"\x1b[2J\x1b[H\x1b[?1004h\x1b[?2031h\x1b[>0q\x1b[c")

    def test_no_prefix_of_the_init_burst_normalises_to_text(self):
        """A pty master read is capped at 1024 bytes, so this burst NEVER arrives as one chunk,
        and `_resume_backstop` re-scans its buffer after every chunk. If a boundary falls inside an
        escape sequence -- which is the common case, not the corner one -- the partial tail must
        not survive stripping as printable junk: b'...\x1b[38' must not normalise to '38', and a
        buffer ending on a bare b'\x1b' must not normalise to '\x1b' (str.split() does not treat
        ESC as whitespace).

        Asserting over EVERY prefix is the point. The earlier version of this test fed the burst as
        a single chunk and therefore could not fail, which is how the settle clock ended up
        latching at t~=0.06s and letting the refusal paint after all."""
        for i in range(len(self.PTY_INIT_BURST) + 1):
            prefix = self.PTY_INIT_BURST[:i]
            self.assertEqual(term_gate._normalize_output(prefix), "",
                             "prefix of length %d normalised to text: %r"
                             % (i, term_gate._normalize_output(prefix)))

    def test_escape_forms_the_cli_actually_emits_leave_no_residue(self):
        """Forms that used to spill through as text because no branch matched them. Each would
        latch the settle clock on its own, with no chunk split involved at all."""
        for raw, expected in [
            (b"\x1b[38:2:255:0:0mhi\x1b[0m", "hi"),   # ITU sub-parameter (colon) SGR
            (b"\x1b[4:3m", ""),                       # curly underline
            (b"\x1b]0;claude", ""),                   # OSC whose terminator is in the next chunk
            (b"\x1bP>|Claude Code\x1b\\", ""),        # DCS
            (b"\x1b_G f=100\x1b\\", ""),             # APC
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(term_gate._normalize_output(raw), expected)

    def test_pty_rendered_refusal_is_recognised(self):
        """The one that was failing in production: ANSI-laden bytes off a real pty."""
        self.assertTrue(term_gate.looks_like_bg_refusal(self.PTY_REFUSAL))

    def test_ansi_strip_separates_words_it_removes(self):
        """A column jump BETWEEN two words must become a space, not vanish -- deleting it
        would fuse "currently"/"running" and fail the match just as quietly."""
        self.assertIn("is currently running as a background agent (bg)",
                      term_gate._normalize_output(self.PTY_REFUSAL))

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
