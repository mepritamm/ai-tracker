"""Tests for aitracker.term_gate.session_cwd()'s resume=True ancestor-walk.

Bug: resuming a Claude session whose recorded cwd was deleted (e.g. a removed git worktree)
used to 404 with "session not found or its cwd no longer exists", even though `claude --resume
<sid>` looks the session up by id and will happily continue it from any existing directory --
verified empirically on claude 2.1.280 (see term_gate.session_cwd's docstring). resume=True walks
up via os.path.dirname to the nearest EXISTING ancestor of the recorded cwd instead of returning
"" outright; resume=False (the default, used by cwd/new/run) is unchanged -- strict on-disk check.
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker import term_gate


class TestSessionCwdResumeAncestorWalk(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_resume_true_walks_up_to_the_nearest_existing_ancestor(self):
        existing = os.path.join(self.tmpdir, "a")
        os.makedirs(existing)
        gone = os.path.join(existing, "b", "gone")   # neither "b" nor "b/gone" exists
        with mock.patch("aitracker.registry.parse_any",
                         return_value={"meta": {"cwd": gone}}):
            self.assertEqual(term_gate.session_cwd("sid"), "")
            self.assertEqual(term_gate.session_cwd("sid", resume=True), existing)

    def test_unknown_session_is_empty_either_way(self):
        with mock.patch("aitracker.registry.parse_any", side_effect=Exception("boom")):
            self.assertEqual(term_gate.session_cwd("no-such-sid"), "")
            self.assertEqual(term_gate.session_cwd("no-such-sid", resume=True), "")

    def test_unknown_session_via_empty_parse_result_is_empty_either_way(self):
        with mock.patch("aitracker.registry.parse_any", return_value=None):
            self.assertEqual(term_gate.session_cwd("no-such-sid"), "")
            self.assertEqual(term_gate.session_cwd("no-such-sid", resume=True), "")

    def test_existing_cwd_is_returned_unchanged_for_both(self):
        with mock.patch("aitracker.registry.parse_any",
                         return_value={"meta": {"cwd": self.tmpdir}}):
            self.assertEqual(term_gate.session_cwd("sid"), self.tmpdir)
            self.assertEqual(term_gate.session_cwd("sid", resume=True), self.tmpdir)

    def test_resume_true_stops_at_root_and_returns_empty(self):
        gone = "/this-path-should-not-exist-xyz/deep/gone"
        with mock.patch("aitracker.registry.parse_any",
                         return_value={"meta": {"cwd": gone}}):
            self.assertEqual(term_gate.session_cwd("sid", resume=True), "")


if __name__ == "__main__":
    unittest.main()
