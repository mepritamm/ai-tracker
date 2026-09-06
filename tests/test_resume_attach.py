"""Pins the `claude` CLI's CURRENT background-session refusal wording -- the regression
this file exists to prevent forever.

BACKGROUND: term_gate.py used to key its whole auto-recovery backstop off ONE pinned
string, the LEGACY refusal ("is currently running as a background agent (bg)"). The
`claude` CLI silently changed its wording to "is running as a background session
(<short-id>) ... Run `claude attach <short-id>` ...", so looks_like_bg_refusal() stopped
matching, term_vt.py's _resume_backstop never fired, and a resumed terminal hung forever
showing the bare refusal to the user. Nothing caught this because no test anywhere
exercised the CLI's CURRENT real output -- every pinned string in the existing suite
(tests/test_resume_fork_session.py's TestRefusalAndMissingTranscriptMarkers) was the
legacy wording. These tests exist so that specific failure mode -- a CLI wording drift
with no test using the live wording -- cannot happen silently again.
"""
import unittest

from aitracker import term_gate


CURRENT_MESSAGE = (
    "Session e30d3b6a-046e-483b-b0f5-e0a1d692abfa is running as a background session "
    "(e30d3b6a). Run `claude attach e30d3b6a` to open it, or `claude stop e30d3b6a` "
    "first to resume it here. Add --fork-session to branch off a copy instead."
)
"""Verbatim CLI output, captured from a real screenshot on 2026-08-30 -- see
term_gate.py's BG_REFUSAL_MARKERS docstring, which quotes this same capture."""

LEGACY_MESSAGE = (
    "Session <id> is currently running as a background agent (bg). Use `claude agents` "
    "to find and attach to it, or add --fork-session to branch off a copy."
)
"""The OLD wording -- must keep matching, since an older `claude` binary on another
machine may still emit exactly this (see term_gate.REFUSAL_MARKER's docstring)."""


def _fuse_words_with_column_jumps(text):
    """Rejoins `text.split(" ")` with `\\x1b[<n>G` cursor-jump escapes instead of literal
    spaces -- approximates how Ink actually renders this message on a real pty (see
    term_gate.py's _ANSI_RE docstring, which documents the identical rendering for the
    legacy message), where the marker arrives split across escape sequences rather than
    surrounded by whitespace. Verified (see the RED/GREEN proof in the task report) that
    `term_gate._normalize_output(_fuse_words_with_column_jumps(CURRENT_MESSAGE)) ==
    CURRENT_MESSAGE` -- the fuse-then-normalize round trip is lossless, so any assertion
    that holds for CURRENT_MESSAGE must also hold for its fused form, or the ANSI handling
    is what broke."""
    words = text.split(" ")
    col = 9
    pieces = [words[0]]
    for w in words[1:]:
        col += len(w) + 3
        pieces.append("\x1b[%dG%s" % (col, w))
    return "".join(pieces)


FUSED_CURRENT_MESSAGE = _fuse_words_with_column_jumps(CURRENT_MESSAGE)


class TestRegressionEval(unittest.TestCase):
    """The core pin the user asked for: both known CLI wordings must be recognised as the
    bg-refusal signal, and every marker term_gate actually matches on must be traceable to
    real captured CLI output -- not a marker that quietly stopped meaning anything."""

    def test_current_message_is_recognised(self):
        """THE regression test: the CURRENT CLI wording must match, or term_vt.py's
        auto-recovery backstop silently never fires again -- exactly what shipped broken."""
        self.assertTrue(term_gate.looks_like_bg_refusal(CURRENT_MESSAGE))

    def test_legacy_message_is_recognised(self):
        """The OLD wording must keep matching -- an older `claude` binary elsewhere may
        still emit exactly this, and REFUSAL_MARKER is kept specifically for it."""
        self.assertTrue(term_gate.looks_like_bg_refusal(LEGACY_MESSAGE))

    def test_every_marker_is_grounded_in_a_real_capture(self):
        """Anti-rot guard: each string in BG_REFUSAL_MARKERS must be a substring of at
        least one of the two verbatim captured messages above. If someone edits a marker
        into wording no real CLI output actually contains, this fails loudly instead of
        the marker silently matching nothing -- the exact way the original bug hid."""
        for marker in term_gate.BG_REFUSAL_MARKERS:
            with self.subTest(marker=marker):
                self.assertTrue(
                    marker in CURRENT_MESSAGE or marker in LEGACY_MESSAGE,
                    "marker %r is not a substring of either captured message" % (marker,))


class TestAttachTarget(unittest.TestCase):
    """Tests for term_gate.attach_target() -- the short id fed to `claude attach`."""

    def test_parses_short_id_from_current_message(self):
        """The happy path this whole feature exists for: pull the short id straight out
        of the CLI's own `claude attach <id>` hint in its refusal -- verified against the
        real captured sid for THIS session (term_vt.py always has this sid on hand; a
        hint is only ever trusted once it cross-checks against it, see
        test_hint_for_a_different_session_is_rejected_not_trusted below)."""
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertEqual(term_gate.attach_target(CURRENT_MESSAGE, sid), "e30d3b6a")

    def test_hint_for_a_different_session_is_rejected_not_trusted(self):
        """SECURITY REGRESSION TEST. attach_target() used to prefer a scraped
        `claude attach <token>` hint over `sid` with NO cross-check at all. The pane it
        scrapes from is a live terminal showing a Claude session, and that session can
        itself print or replay text that merely QUOTES a refusal for a totally
        different session (old scrollback, a pasted transcript, ...). Trusting the
        hint unconditionally meant a replayed/quoted refusal for session X could hijack
        an attach the user clicked for session Y -- dropping them into someone else's
        live agent, silently, since the attach path shows no `⑂` chip. The hint
        must now be REJECTED whenever it is not a prefix of the sid actually clicked,
        falling back to sid[:8] instead."""
        sid = "00000000-aaaa-bbbb-cccc-dddddddddddd"
        self.assertNotEqual(sid[:8], "e30d3b6a")
        self.assertEqual(term_gate.attach_target(CURRENT_MESSAGE, sid), "00000000")

    def test_quoted_refusal_for_another_live_session_never_hijacks_the_click(self):
        """THE reviewer's exact demonstrated attack. `output` is not a genuine refusal
        for the clicked session at all -- it is a REPLAYED TRANSCRIPT that merely QUOTES
        a refusal for session e30d3b6a (e.g. old scrollback the user is scrolled past,
        or the assistant discussing a prior attach). The user actually clicked a
        DIFFERENT session, aaaaaaaa-1111-2222-3333-444444444444. attach_target() must
        return the sid's own fallback ('aaaaaaaa'), and must NEVER return 'e30d3b6a' --
        doing so would silently attach the user into someone else's still-live agent,
        with no `⑂` chip or any other signal that the pane is not what they clicked."""
        buffer = (
            "some earlier scrollback in this pane...\n"
            "Session e30d3b6a-046e-483b-b0f5-e0a1d692abfa is running as a background "
            "session (e30d3b6a). Run `claude attach e30d3b6a` to open it.\n"
            "...more scrollback follows"
        )
        sid = "aaaaaaaa-1111-2222-3333-444444444444"
        result = term_gate.attach_target(buffer, sid)
        self.assertEqual(result, "aaaaaaaa")
        self.assertNotEqual(result, "e30d3b6a")

    def test_correct_hint_appearing_second_still_wins(self):
        """Two `claude attach <token>` hints appear in the buffer -- an unrelated/stale
        one FIRST, and the one that actually matches the clicked sid SECOND. A
        first-match-wins scan would return the wrong (first) token; attach_target() must
        scan every candidate and accept the first one that cross-checks against sid,
        regardless of position."""
        buffer = (
            "Session deadbeef-0000-0000-0000-000000000000 is running as a background "
            "session (deadbeef). Run `claude attach deadbeef` to open it.\n"
            "Session e30d3b6a-046e-483b-b0f5-e0a1d692abfa is running as a background "
            "session (e30d3b6a). Run `claude attach e30d3b6a` to open it."
        )
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertEqual(term_gate.attach_target(buffer, sid), "e30d3b6a")

    def test_arbitrary_word_after_claude_attach_is_not_absorbed(self):
        """The old token regex (`[0-9a-zA-Z_-]*`) absorbed ANY word following "claude
        attach", not just a real hex short-id -- e.g. a stray sentence containing the
        words "claude attach my-session-name-here" parsed out
        'my-session-name-here' as if it were a genuine target. With no sid to verify
        against either, nothing should be attached at all."""
        self.assertEqual(
            term_gate.attach_target("Run claude attach my-session-name-here now", sid=""),
            "")

    def test_hint_case_insensitive_against_sid(self):
        """Session ids/hints are hex and case shouldn't matter for the cross-check --
        an UPPERCASE hint must still be accepted against a lowercase sid (and vice
        versa), since the CLI's own casing shouldn't gate a genuine match."""
        buffer = (
            "Session E30D3B6A-046E-483B-B0F5-E0A1D692ABFA is running as a background "
            "session (E30D3B6A). Run `claude attach E30D3B6A` to open it."
        )
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertEqual(term_gate.attach_target(buffer, sid), "E30D3B6A")

    def test_falls_back_to_sid_prefix_when_output_has_no_hint(self):
        """LEGACY_MESSAGE carries no `claude attach` hint at all, so the fallback -- the
        first 8 characters of the caller-supplied sid -- must be used instead."""
        self.assertEqual(
            term_gate.attach_target(LEGACY_MESSAGE, "abcdef1234567890"), "abcdef12")

    def test_returns_empty_string_when_neither_hint_nor_sid(self):
        self.assertEqual(term_gate.attach_target(LEGACY_MESSAGE, ""), "")
        self.assertEqual(term_gate.attach_target(LEGACY_MESSAGE, None), "")

    def test_never_raises_on_hostile_input(self):
        """attach_target() runs on live, possibly-garbage pty output on every chunk -- it
        must degrade to "" rather than ever raising, or a malformed chunk would crash the
        terminal route instead of just missing a match."""
        for output in (b"", "", None, b"\xff\xfe garbage", "\x1b[38:2:255:0:0m\x1b[0m"):
            with self.subTest(output=output):
                try:
                    result = term_gate.attach_target(output)
                except Exception as exc:
                    self.fail("attach_target(%r) raised %r instead of returning \"\""
                              % (output, exc))
                else:
                    self.assertEqual(result, "")


class TestAttachArgv(unittest.TestCase):
    """Tests for term_gate.attach_argv() -- the argv for `claude attach <target>`."""

    def test_builds_claude_attach_argv(self):
        self.assertEqual(term_gate.attach_argv("e30d3b6a"),
                          ["claude", "attach", "e30d3b6a"])

    def test_empty_target_returns_empty_list(self):
        self.assertEqual(term_gate.attach_argv(""), [])

    def test_none_target_returns_empty_list(self):
        self.assertEqual(term_gate.attach_argv(None), [])


class TestAnsiInkRobustness(unittest.TestCase):
    """This is HOW the original bug hid: the CLI renders via Ink, which jumps the cursor
    to each word's column instead of emitting spaces, so a naive substring match against
    raw pty bytes never sees the marker as a contiguous string -- see term_gate.py's
    _ANSI_RE / _normalize_output docstrings for the measured real-pty byte shapes this
    mirrors."""

    def test_column_jump_fused_message_is_recognised(self):
        """CURRENT_MESSAGE with every space replaced by an Ink-style \\x1b[NG column jump
        -- must still match after ANSI normalization collapses the jumps back to spaces."""
        self.assertTrue(term_gate.looks_like_bg_refusal(FUSED_CURRENT_MESSAGE))

    def test_column_jump_fused_message_attach_target_still_works(self):
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertEqual(term_gate.attach_target(FUSED_CURRENT_MESSAGE, sid), "e30d3b6a")

    def test_sgr_color_codes_sprinkled_inside_still_matches(self):
        """SGR (colour) escapes -- including the ITU sub-parameter colon form a real
        terminal emits -- landing INSIDE the marker text must not break the match."""
        colored = CURRENT_MESSAGE.replace(
            "background session",
            "\x1b[38:2:255:0:0mbackground session\x1b[0m")
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertTrue(term_gate.looks_like_bg_refusal(colored))
        self.assertEqual(term_gate.attach_target(colored, sid), "e30d3b6a")

    def test_line_wrap_mid_sentence_still_matches(self):
        """A `\\r\\n` inserted mid-sentence (an ordinary terminal line-wrap) must not
        split the marker out of matching -- _normalize_output()'s whitespace collapse is
        what's under test here."""
        wrapped = CURRENT_MESSAGE.replace("background session", "background\r\nsession")
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertTrue(term_gate.looks_like_bg_refusal(wrapped))
        self.assertEqual(term_gate.attach_target(wrapped, sid), "e30d3b6a")

    def test_bytes_message_matches(self):
        """The real pty hands term_gate bytes, not str -- both looks_like_bg_refusal and
        attach_target must accept bytes directly."""
        sid = "e30d3b6a-046e-483b-b0f5-e0a1d692abfa"
        self.assertTrue(term_gate.looks_like_bg_refusal(CURRENT_MESSAGE.encode()))
        self.assertEqual(term_gate.attach_target(CURRENT_MESSAGE.encode(), sid), "e30d3b6a")


class TestNegativeCases(unittest.TestCase):
    """A wrong retry is worse than none: ordinary output that merely brushes up against
    the vocabulary of the refusal, or the OTHER "can't resume" signal, must not
    false-positive as the bg-refusal."""

    def test_mentions_background_and_session_separately_does_not_match(self):
        """The words "background" and "session" appearing separately, in an unrelated
        sentence, must not be mistaken for the specific refusal phrase."""
        text = "Running in the background. Starting a new session now."
        self.assertFalse(term_gate.looks_like_bg_refusal(text))

    def test_missing_transcript_message_is_not_a_bg_refusal(self):
        """The "no conversation found" message is a DIFFERENT signal with a DIFFERENT
        handler (looks_like_missing_transcript) -- it must not also trip the bg-refusal
        retry, which would fork a session that was never running in the background."""
        text = "No conversation found with session ID: 00000000-0000-0000-0000-000000000000"
        self.assertFalse(term_gate.looks_like_bg_refusal(text))
        self.assertTrue(term_gate.looks_like_missing_transcript(text))

    def test_empty_output_does_not_match(self):
        self.assertFalse(term_gate.looks_like_bg_refusal(""))
        self.assertFalse(term_gate.looks_like_bg_refusal(b""))

    def test_whitespace_only_output_does_not_match(self):
        self.assertFalse(term_gate.looks_like_bg_refusal("   \n\t  "))


if __name__ == "__main__":
    unittest.main()
