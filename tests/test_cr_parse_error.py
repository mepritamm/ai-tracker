"""Tests for `parse_error` on the detail dict -- landed at the shared registry seam
(registry.py:138's setdefault) with each provider computing its own raw fact:
Claude off parse_session's per-line JSONL loop (providers/claude.py ~1104-1119),
Auggie off _auggie_all's per-task-file JSON read (providers/auggie.py ~61-74, joined
in _auggie_todos_for ~264-277).

Contract (same shape both providers), confirmed by reading the source:
  None                                     -- transcript/tree parsed cleanly
  {"line": <int|None>, "parsed_before": N} -- a record failed; `line` is the 1-based
                                              line number of the FIRST bad line for
                                              Claude (no single-file line concept for
                                              Auggie -> None), `parsed_before` counts
                                              records recovered before/despite the
                                              failure -- the whole point being that
                                              everything before (and, unlike a naive
                                              truncation, after) the bad record still
                                              renders.

The key must be present on EVERY parse_any() detail dict for EVERY provider -- every
test below asserts with assertIn, never relies on .get() silently defaulting.
"""
import json
import os
import tempfile
import unittest

from aitracker import config
from aitracker.providers.claude import parse_session
from aitracker.providers.auggie import parse_auggie, _AUGGIE_LIST_CACHE
from aitracker.registry import parse_any


def _write_lines(path, lines):
    with open(path, "w", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(ln + "\n")
    return path


def _rec(o):
    return json.dumps(o)


class ClaudeParseErrorDirectTests(unittest.TestCase):
    """Direct unit tests of parse_session()'s own per-line scan -- no PROJECTS/
    registry plumbing needed, since parse_session takes a bare file path."""

    def setUp(self):
        self.tdir = tempfile.mkdtemp()

    def test_clean_transcript_is_none(self):
        """Guard against a false positive: a transcript with nothing wrong at all
        must report parse_error as None, not accidentally flag something."""
        path = _write_lines(os.path.join(self.tdir, "clean.jsonl"), [
            _rec({"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}),
            _rec({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}),
        ])
        d = parse_session(path)
        self.assertIn("parse_error", d)
        self.assertIsNone(d["parse_error"])

    def test_truncated_line_reports_first_bad_line_and_parsed_before(self):
        """THE important case: a malformed line in the middle of the transcript.
        parse_error must name its 1-based line number and how many records parsed
        cleanly before it -- AND the good records both BEFORE and AFTER the bad line
        must still render (parsing behaviour is otherwise unchanged; that is the
        whole point of 'everything before it is shown')."""
        path = os.path.join(self.tdir, "trunc.jsonl")
        _write_lines(path, [
            _rec({"type": "user", "cwd": "/x",
                  "message": {"role": "user", "content": "go"}}),                          # line 1, good
            _rec({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "before the break"}]}}),                          # line 2, good
        ])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"type": "user", "message": {"content": [{"trunc\n')                 # line 3, malformed
            fh.write(_rec({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "after the break"}]}}) + "\n")                     # line 4, good
        d = parse_session(path)
        self.assertEqual(d["parse_error"], {"line": 3, "parsed_before": 2})
        texts = [n["text"] for n in d["narrative"]]
        self.assertIn("before the break", texts)
        self.assertIn("after the break", texts)

    def test_multiple_bad_lines_only_the_first_is_reported(self):
        """Later bad lines are the same story, not new information -- only the
        FIRST failure is recorded, matching parse_session's own `if parse_error is
        None` guard."""
        path = os.path.join(self.tdir, "multi.jsonl")
        _write_lines(path, [
            _rec({"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}),
        ])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"bad one\n')
            fh.write('{"bad two\n')
        d = parse_session(path)
        self.assertEqual(d["parse_error"], {"line": 2, "parsed_before": 1})


class ClaudeParseErrorRegistryTests(unittest.TestCase):
    """Same contract, reached through registry.parse_any() -- proves the field
    survives the routing layer (Claude sets it itself; registry.py:138's setdefault
    is only the defensive backstop for a provider that forgets to)."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)

    def tearDown(self):
        config.PROJECTS = self._pdir_snap

    def test_clean_session_via_parse_any(self):
        _write_lines(os.path.join(self.sdir, "s_clean.jsonl"), [
            _rec({"type": "user", "cwd": "/tmp/proj", "message": {"role": "user", "content": "go"}}),
        ])
        d = parse_any("s_clean")
        self.assertIn("parse_error", d)
        self.assertIsNone(d["parse_error"])

    def test_malformed_session_via_parse_any(self):
        path = os.path.join(self.sdir, "s_bad.jsonl")
        _write_lines(path, [
            _rec({"type": "user", "cwd": "/tmp/proj", "message": {"role": "user", "content": "go"}}),
            _rec({"type": "assistant", "message": {"content": [{"type": "text", "text": "kept"}]}}),
        ])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("not json at all\n")
        d = parse_any("s_bad")
        self.assertEqual(d["parse_error"], {"line": 3, "parsed_before": 2})
        self.assertIn("kept", [n["text"] for n in d["narrative"]])


class AuggieParseErrorTests(unittest.TestCase):
    """providers/auggie.py's _auggie_all()/_auggie_todos_for() -- Auggie's equivalent
    of a truncated JSONL line is a task-storage JSON file that fails to parse. No
    single-file line concept exists across a tree of separate files, so `line` is
    always None; `parsed_before` counts todos still recovered despite the failure."""

    def setUp(self):
        self._augment_dir_snap = config.AUGMENT_DIR
        self._auggie_sessions_snap = config.AUGGIE_SESSIONS
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        self.tasks_dir = os.path.join(config.AUGMENT_DIR, "task-storage", "tasks")
        os.makedirs(self.tasks_dir)
        _AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        config.AUGMENT_DIR = self._augment_dir_snap
        config.AUGGIE_SESSIONS = self._auggie_sessions_snap
        _AUGGIE_LIST_CACHE.clear()

    def _wtask(self, uuid, **kw):
        with open(os.path.join(self.tasks_dir, uuid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"uuid": uuid, **kw}, fh)

    def _wsession(self, sid, root_uuid, title="Sess"):
        with open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w", encoding="utf-8") as fh:
            json.dump({"sessionId": sid, "modified": "2026-06-27T05:48:03Z",
                       "customTitle": title, "rootTaskUuid": root_uuid, "chatHistory": []}, fh)

    def test_clean_tree_is_none(self):
        """Guard against a false positive on the Auggie side too."""
        self._wtask("root1", name="Current Task List", subTasks=["s1", "s2"])
        self._wtask("s1", name="one", state="COMPLETE", subTasks=[])
        self._wtask("s2", name="two", state="IN_PROGRESS", subTasks=[])
        self._wsession("sess1", "root1")
        d = parse_auggie("sess1")
        self.assertIn("parse_error", d)
        self.assertIsNone(d["parse_error"])

    def test_corrupt_task_file_among_good_ones_reports_failure_and_keeps_good_todos(self):
        """One corrupt task-storage file (not even one this session's own tree
        references -- _auggie_all() reads the WHOLE task-storage dir) alongside
        otherwise-good files: parse_error must report the failure honestly (line
        None, since Auggie has no single-file line concept) while the good todos
        this session's tree actually resolves to still come through untouched."""
        self._wtask("root1", name="Current Task List", subTasks=["s1", "s2"])
        self._wtask("s1", name="one", state="COMPLETE", subTasks=[])
        self._wtask("s2", name="two", state="IN_PROGRESS", subTasks=[])
        with open(os.path.join(self.tasks_dir, "corrupt.json"), "w", encoding="utf-8") as fh:
            fh.write("{not valid json at all")
        self._wsession("sess1", "root1")
        d = parse_auggie("sess1")
        self.assertEqual(d["parse_error"], {"line": None, "parsed_before": 2})
        self.assertEqual([t["content"] for t in d["todos"]], ["one", "two"])
        self.assertEqual(d["counts"]["todos"], 2)

    def test_no_root_task_uuid_at_all_is_none(self):
        """A session with no rootTaskUuid never even calls _auggie_all() -- must
        still report the key, honestly None, never omitted or a crash."""
        self._wsession("sess_noroot", None)
        d = parse_auggie("sess_noroot")
        self.assertIn("parse_error", d)
        self.assertIsNone(d["parse_error"])

    def test_via_registry_parse_any(self):
        self._wtask("root1", name="Current Task List", subTasks=["s1"])
        self._wtask("s1", name="one", state="COMPLETE", subTasks=[])
        with open(os.path.join(self.tasks_dir, "corrupt.json"), "w", encoding="utf-8") as fh:
            fh.write("{oops")
        self._wsession("sess1", "root1")
        d = parse_any("auggie:sess1")
        self.assertEqual(d["parse_error"], {"line": None, "parsed_before": 1})


if __name__ == "__main__":
    unittest.main()
