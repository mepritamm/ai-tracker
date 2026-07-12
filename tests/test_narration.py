#!/usr/bin/env python3
"""Regression: injected skill/command/tool text lives in a USER-role message whose
content is a list of blocks (e.g. 'Base directory for this skill: …'). It must NOT
leak into the Narration panel (assistant-only) or into search."""
import json
import os
import tempfile
import unittest

from aitracker.providers.claude import parse_session, _match_content, _searchable_texts

SKILL_TEXT = ("Base directory for this skill: /Users/x/.claude/skills/tracker-push\n\n"
              "# Ship ai-tracker to both remotes — a long injected skill definition.")


def _write(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")
    return path


class TestNarrationExcludesInjectedContent(unittest.TestCase):
    def setUp(self):
        # a real user prompt (string), an injected skill block (user + list),
        # and one genuine assistant reply.
        self.path = _write([
            {"type": "user", "cwd": "/x", "gitBranch": "main",
             "message": {"role": "user", "content": "do the tracker-push"}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": SKILL_TEXT}]}},
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z",
             "message": {"content": [
                 {"type": "text", "text": "On it — pushing to both remotes now."}]}},
        ])

    def tearDown(self):
        os.unlink(self.path)

    def test_skill_text_not_in_narration(self):
        d = parse_session(self.path)
        joined = " ".join(n["text"] for n in d["narrative"])
        self.assertNotIn("Base directory for this skill", joined)
        self.assertIn("pushing to both remotes", joined)          # the real reply is kept

    def test_skill_text_not_searchable(self):
        # the injected block must not be a searchable segment
        for line in open(self.path):
            o = json.loads(line)
            segs = list(_searchable_texts(o))
            self.assertFalse(any("Base directory for this skill" in t for t, _ in segs),
                             "skill injection leaked into search segments")

    def test_real_prompt_still_a_request(self):
        d = parse_session(self.path)
        self.assertIn("do the tracker-push", [r["text"] for r in d["requests"]])


if __name__ == "__main__":
    unittest.main()


class TestNarrationCap(unittest.TestCase):
    """The narration list is no longer capped at 16 (real sessions have 100s)."""

    def _session(self, n_replies):
        lines = [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}]
        for k in range(n_replies):
            lines.append({"type": "assistant", "timestamp": "2026-06-22T10:00:%02dZ" % (k % 60),
                          "message": {"content": [{"type": "text", "text": "reply number %d" % k}]}})
        return _write(lines)

    def test_more_than_16_kept(self):
        p = self._session(30)
        d = parse_session(p); os.unlink(p)
        self.assertEqual(len(d["narrative"]), 30)      # was 16

    def test_caps_at_60(self):
        p = self._session(80)
        d = parse_session(p); os.unlink(p)
        self.assertEqual(len(d["narrative"]), 60)      # bounded for payload
        self.assertEqual(d["narrative"][0]["text"], "reply number 79")   # newest first
