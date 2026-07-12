#!/usr/bin/env python3
"""PR/MR links a session touched surface on the shared `prs` shape — filled by
BOTH providers, created-first, deduped. The capability spans Claude and Auggie."""
import json
import os
import tempfile
import unittest

import aitracker.config as config
from aitracker.util import collect_prs, prs_sorted
from aitracker.providers.claude import parse_session
from aitracker.providers import auggie as _auggie


class TestCollectPrs(unittest.TestCase):
    def test_extracts_and_labels(self):
        acc = {}
        collect_prs(acc, "opened https://github.com/acme/widget/pull/42 today", "t1")
        self.assertIn("https://github.com/acme/widget/pull/42", acc)
        e = acc["https://github.com/acme/widget/pull/42"]
        self.assertEqual(e["repo"], "acme/widget")
        self.assertEqual(e["num"], "42")
        self.assertFalse(e["created"])

    def test_dedup_and_created_sticks(self):
        acc = {}
        collect_prs(acc, "see https://github.com/a/b/pull/1", "t1", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/1 (from gh)", "t2", created=True)
        collect_prs(acc, "https://github.com/a/b/pull/1 again", "t3", created=False)
        self.assertEqual(len(acc), 1)                      # deduped by URL
        self.assertTrue(acc["https://github.com/a/b/pull/1"]["created"])   # created wins
        self.assertEqual(acc["https://github.com/a/b/pull/1"]["t"], "t3")  # latest ts kept

    def test_trailing_punctuation_and_slash(self):
        acc = {}
        collect_prs(acc, "does https://github.com/a/b/pull/45/ affect x?", "t")
        collect_prs(acc, "[https://github.com/a/b/pull/9].", "t")
        self.assertIn("https://github.com/a/b/pull/45", acc)   # trailing / stripped -> same PR
        self.assertIn("https://github.com/a/b/pull/9", acc)    # trailing ]. stripped

    def test_bitbucket_and_gitlab_shapes(self):
        acc = {}
        collect_prs(acc, "https://bitbucket.org/team/repo/pull-requests/7", "t")
        collect_prs(acc, "https://gitlab.com/grp/proj/-/merge_requests/13", "t")
        self.assertEqual(len(acc), 2)                      # both hosting styles recognised
        nums = sorted(e["num"] for e in acc.values())
        self.assertEqual(nums, ["13", "7"])

    def test_non_pr_urls_ignored(self):
        acc = {}
        collect_prs(acc, "https://github.com/a/b/issues/5 and https://github.com/a/b/tree/main", "t")
        self.assertEqual(acc, {})

    def test_sorted_created_first_then_recent(self):
        acc = {}
        collect_prs(acc, "https://github.com/a/b/pull/1", "2026-01-01T00:00:00Z", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/2", "2026-01-03T00:00:00Z", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/3", "2026-01-02T00:00:00Z", created=True)
        order = [p["num"] for p in prs_sorted(acc)]
        self.assertEqual(order, ["3", "2", "1"])           # created(#3) first, then #2 (newer ref) > #1


def _write_jsonl(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")
    return path


class TestClaudePrs(unittest.TestCase):
    def test_created_from_gh_output_vs_referenced(self):
        # a Bash `gh pr create` whose tool_result carries the new URL (=created),
        # plus an unrelated PR the assistant merely mentions (=referenced).
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "ship it"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu1", "name": "Bash",
                 "input": {"command": "gh pr create --fill"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu1",
                 "content": "https://github.com/acme/app/pull/7"}]}},
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                {"type": "text", "text": "Related: https://github.com/acme/app/pull/3"}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        by = {p["num"]: p for p in d["prs"]}
        self.assertEqual(set(by), {"7", "3"})
        self.assertTrue(by["7"]["created"])                # came from gh pr create result
        self.assertFalse(by["3"]["created"])               # merely referenced
        self.assertEqual(d["prs"][0]["num"], "7")          # created sorts first
        self.assertEqual(by["7"]["repo"], "acme/app")


class TestAuggiePrs(unittest.TestCase):
    def setUp(self):
        self._sess = config.AUGGIE_SESSIONS
        config.AUGGIE_SESSIONS = tempfile.mkdtemp()
        _auggie._AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        config.AUGGIE_SESSIONS = self._sess
        _auggie._AUGGIE_LIST_CACHE.clear()

    def test_pr_from_response_text(self):
        sid = "s1"
        json.dump({"sessionId": sid, "modified": "2026-06-27T05:48:03Z",
                   "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
                       "request_message": "open a PR",
                       "response_text": "Opened https://github.com/acme/lib/pull/12"}}]},
                  open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        d = _auggie.parse_auggie(sid)
        self.assertIsNotNone(d)
        nums = [p["num"] for p in d["prs"]]
        self.assertEqual(nums, ["12"])
        self.assertEqual(d["prs"][0]["repo"], "acme/lib")


if __name__ == "__main__":
    unittest.main()
