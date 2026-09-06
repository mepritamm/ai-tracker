"""Cross-view "is this session working" parity for Claude sessions.

THE BUG: the control room's session DETAIL view decides whether to show the live glow
via the shared predicate `isSessionWorking(s, live)` in aitracker/web/app.js, which needs
a real `ended` boolean. The board/rail get it from list_sessions()'s `ended` (derived by
providers/claude.py's `_tail_scan` off the tail of the main transcript: `waiting =
bool(open_asks)`; `ended = (not waiting) and last == "assistant_text"`). But
`parse_session()` (the detail dict's producer) never carried that field at all, so the
client (ext_cr_detail.js's `detailIsWorking`) had to GUESS from whether any todo is
in_progress -- which provably disagrees with the board in both directions: a live
session with NO todos (rail says "working", detail said "Landed", no glow), and a
genuinely ended session with a stale in_progress todo (board says "landed", detail said
"Working" and glows).

THE FIX: `parse_session()`'s meta now carries `ended` by calling the SAME
`_session_meta(path)` (-> `_tail_scan`) the list path already calls -- not a second,
independently-written copy of the rule. This module proves, off REAL on-disk
transcripts (not hand-built dicts), that:

  1. parse_session()'s meta.ended is always a real bool.
  2. For the SAME session, parse_session()["meta"]["ended"] == the `ended` list_sessions()
     reports for it -- across an ended-on-text session, a mid-turn session, and a
     waiting-on-the-user session. This is the anti-drift assertion.
  3. A session with NO todos at all still gets a correct `ended` -- the exact case the
     client-side guess got wrong.
  4. A malformed/truncated transcript doesn't throw and still yields a bool.
"""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config
from aitracker.providers.claude import list_sessions, parse_session


def _write_jsonl(path, rows, trailing_garbage=None):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        if trailing_garbage is not None:
            fh.write(trailing_garbage)
    return path


class _ProjectsDirCase(unittest.TestCase):
    """Common fixture: a temp config.PROJECTS with one project subdir, restored after."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        shutil.rmtree(self.pdir, ignore_errors=True)

    def _path(self, sid):
        return os.path.join(self.sdir, sid + ".jsonl")

    def _list_entry(self, sid):
        rows = list_sessions()
        by_id = {r["id"]: r for r in rows}
        self.assertIn(sid, by_id, "list_sessions() must see the session written to config.PROJECTS")
        return by_id[sid]


# ---------------------------------------------------------------------------
# Basic shape: meta.ended is always a real bool, no todos required to get it right.
# ---------------------------------------------------------------------------

class EndedBasicShapeTests(_ProjectsDirCase):
    def test_ended_true_no_todos_last_event_assistant_text(self):
        """The exact case the client-side todo-based guess got wrong: a live session
        with NO todos at all. The parser must still report ended=True here (last real
        turn was the assistant finishing, no open question)."""
        sid = "s_ended_true"
        _write_jsonl(self._path(sid), [
            {"type": "user", "cwd": "/tmp/proj",
             "message": {"role": "user", "content": "summarize the repo"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done — here is the summary."}]}},
        ])
        d = parse_session(self._path(sid))
        self.assertIsInstance(d["meta"]["ended"], bool)
        self.assertTrue(d["meta"]["ended"])
        self.assertEqual(d["todos"], [])  # confirms this really is the no-todos case

    def test_ended_false_mid_turn(self):
        """Last event is an assistant tool_use with no reply yet -- the session is
        still actively working, so ended must be False."""
        sid = "s_midturn"
        _write_jsonl(self._path(sid), [
            {"type": "user", "cwd": "/tmp/proj",
             "message": {"role": "user", "content": "run the tests"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "b1", "name": "Bash",
                 "input": {"command": "pytest -q"}}]}},
        ])
        d = parse_session(self._path(sid))
        self.assertIsInstance(d["meta"]["ended"], bool)
        self.assertFalse(d["meta"]["ended"])

    def test_ended_false_waiting_on_user(self):
        """An unanswered AskUserQuestion sits at the tail -- ended must be False even
        though the assistant's own last block is otherwise text-shaped."""
        sid = "s_waiting"
        _write_jsonl(self._path(sid), [
            {"type": "user", "cwd": "/tmp/proj",
             "message": {"role": "user", "content": "pick an approach"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "ask1", "name": "AskUserQuestion",
                 "input": {"questions": [{"question": "Which approach?", "header": "Approach",
                                           "options": [{"label": "A"}, {"label": "B"}]}]}}]}},
        ])
        d = parse_session(self._path(sid))
        self.assertIsInstance(d["meta"]["ended"], bool)
        self.assertFalse(d["meta"]["ended"])


# ---------------------------------------------------------------------------
# The anti-drift assertion: parse_session() and list_sessions() must never disagree
# about `ended` for the same session, since both must now derive it via the same call.
# ---------------------------------------------------------------------------

class AntiDriftMatchesListSessionsTests(_ProjectsDirCase):
    def test_ended_matches_list_sessions_across_three_states(self):
        cases = {
            "s_drift_ended": [
                {"type": "user", "cwd": "/tmp/proj",
                 "message": {"role": "user", "content": "wrap it up"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "All done."}]}},
            ],
            "s_drift_midturn": [
                {"type": "user", "cwd": "/tmp/proj",
                 "message": {"role": "user", "content": "keep going"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "c1", "name": "Bash",
                     "input": {"command": "make check"}}]}},
            ],
            "s_drift_waiting": [
                {"type": "user", "cwd": "/tmp/proj",
                 "message": {"role": "user", "content": "need a decision"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "ask2", "name": "AskUserQuestion",
                     "input": {"questions": [{"question": "A or B?", "header": "Decision",
                                               "options": [{"label": "A"}, {"label": "B"}]}]}}]}},
            ],
        }
        for sid, rows in cases.items():
            _write_jsonl(self._path(sid), rows)

        for sid in cases:
            detail_ended = parse_session(self._path(sid))["meta"]["ended"]
            list_ended = self._list_entry(sid)["ended"]
            self.assertIsInstance(detail_ended, bool)
            self.assertIsInstance(list_ended, bool)
            self.assertEqual(
                detail_ended, list_ended,
                "parse_session()/list_sessions() disagree on `ended` for %s "
                "(detail=%r, list=%r) -- the exact cross-view drift this fix closes"
                % (sid, detail_ended, list_ended))

        # sanity: the three cases really do cover three different `ended`/`waiting` states,
        # not three copies of the same one.
        self.assertTrue(self._list_entry("s_drift_ended")["ended"])
        self.assertFalse(self._list_entry("s_drift_midturn")["ended"])
        self.assertFalse(self._list_entry("s_drift_waiting")["ended"])
        self.assertTrue(self._list_entry("s_drift_waiting")["waiting"])


# ---------------------------------------------------------------------------
# Malformed / truncated transcripts must not throw, and still yield a real bool.
# ---------------------------------------------------------------------------

class EndedMalformedTranscriptTests(_ProjectsDirCase):
    def test_truncated_last_line_does_not_throw(self):
        sid = "s_truncated"
        path = self._path(sid)
        _write_jsonl(path, [
            {"type": "user", "cwd": "/tmp/proj",
             "message": {"role": "user", "content": "start something long"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "working on it"}]}},
        ], trailing_garbage='{"type": "assistant", "message": {"content": [{"type": "text", "text": "cut off mid-wri')
        try:
            d = parse_session(path)
        except Exception as e:  # pragma: no cover - failure path
            self.fail("parse_session() raised on a truncated transcript: %r" % (e,))
        self.assertIsInstance(d["meta"]["ended"], bool)
        # list_sessions() must survive the same file too (it's globbed off the same dir).
        try:
            entry = self._list_entry(sid)
        except Exception as e:  # pragma: no cover - failure path
            self.fail("list_sessions() raised on a truncated transcript: %r" % (e,))
        self.assertIsInstance(entry["ended"], bool)

    def test_only_garbage_lines_does_not_throw(self):
        sid = "s_allgarbage"
        path = self._path(sid)
        with open(path, "w") as fh:
            fh.write("not json at all\n")
            fh.write("{also not valid json\n")
        try:
            d = parse_session(path)
        except Exception as e:  # pragma: no cover - failure path
            self.fail("parse_session() raised on an all-garbage transcript: %r" % (e,))
        self.assertIsInstance(d["meta"]["ended"], bool)
        # A transcript with no real content never "finished on assistant text" -- honest False.
        self.assertFalse(d["meta"]["ended"])


if __name__ == "__main__":
    unittest.main()
