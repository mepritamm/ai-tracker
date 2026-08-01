#!/usr/bin/env python3
"""In-session search — `search_detail` filters ONE session's parsed detail dict
(the shape BOTH providers emit) across narration/prompts/files/commands/todos.
Testing it on the shared shape covers Claude and Auggie in one place."""
import unittest

from aitracker.registry import search_detail

# a minimal detail dict in the shared shape (keys both parsers fill)
_D = {
    "narrative": [{"t": "2026-06-27T05:00:00Z", "text": "Refactoring the parser module"},
                  {"t": "2026-06-27T05:01:00Z", "text": "All tests green now"}],
    "requests":  [{"t": "2026-06-27T04:59:00Z", "text": "please refactor the parser"}],
    "files":     [{"path": "/repo/aitracker/parser.py", "last": "2026-06-27T05:00:30Z"}],
    "commands":  [{"cmd": "python -m pytest tests/", "ok": True, "kind": "test"}],
    "todos":     [{"content": "Refactor parser", "status": "completed"}],
}


class TestSearchDetail(unittest.TestCase):
    def test_empty_query_returns_nothing(self):
        for q in ("", "   ", None):
            r = search_detail(_D, q)
            self.assertEqual(r["hits"], [])
            self.assertEqual(r["total"], 0)

    def test_spans_every_kind(self):
        # "parser" appears in narration, prompt, file, and a todo — one query, all kinds
        kinds = {h["kind"] for h in search_detail(_D, "parser")["hits"]}
        self.assertEqual(kinds, {"narration", "prompt", "file", "todo"})

    def test_matches_command(self):
        hits = search_detail(_D, "pytest")["hits"]
        self.assertEqual([h["kind"] for h in hits], ["command"])
        self.assertEqual(hits[0]["text"], "python -m pytest tests/")

    def test_keyword_and_is_case_insensitive(self):
        # both words must be present in the SAME item; "tests green" only hits one narration line
        hits = search_detail(_D, "TESTS GREEN")["hits"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "narration")

    def test_no_match_is_empty(self):
        self.assertEqual(search_detail(_D, "zzznotfound")["hits"], [])

    def test_hit_carries_full_text_and_snippet(self):
        h = search_detail(_D, "refactoring")["hits"][0]
        self.assertIn("text", h)          # full text → client opens the modal with it
        self.assertIn("refactor", h["snippet"].lower())

    def test_missing_keys_dont_crash(self):
        self.assertEqual(search_detail({}, "anything")["hits"], [])


if __name__ == "__main__":
    unittest.main()
