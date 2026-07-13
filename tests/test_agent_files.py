#!/usr/bin/env python3
"""Files written by a session's BACKGROUND AGENTS (Task sub-agents, whose
transcripts live under <session>/**/agent-*.jsonl — e.g. an agent editing inside
a git worktree) must surface in the shared `files` shape, not just main-transcript
edits. They're tagged `agent` and remain diffable via file_diffs."""
import json
import os
import shutil
import tempfile
import unittest

from aitracker.providers.claude import parse_session, file_diffs


def _write(path, lines):
    with open(path, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


class TestAgentFiles(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sid = "sess"
        self.main = os.path.join(self.dir, self.sid + ".jsonl")
        _write(self.main, [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "timestamp": "2026-07-13T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "m1", "name": "Write",
                 "input": {"file_path": "/x/main.py", "content": "print(1)\n"}}]}},
        ])
        adir = os.path.join(self.dir, self.sid, "subagents")
        os.makedirs(adir)
        _write(os.path.join(adir, "agent-aaa111.jsonl"), [
            {"type": "user", "message": {"role": "user", "content": "fix auth in the worktree"}},
            {"type": "assistant", "timestamp": "2026-07-13T10:05:00Z", "message": {"content": [
                {"type": "tool_use", "id": "a1", "name": "Edit",
                 "input": {"file_path": "/x/.worktrees/wt/auth.py",
                           "old_string": "allow_all", "new_string": "deny_by_default"}}]}},
            {"type": "assistant", "timestamp": "2026-07-13T10:06:00Z", "message": {"content": [
                {"type": "tool_use", "id": "a2", "name": "Write",
                 "input": {"file_path": "/x/.worktrees/wt/new.py", "content": "x=1\n"}}]}},
        ])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_agent_edits_appear_in_files(self):
        d = parse_session(self.main)
        by = {f["path"]: f for f in d["files"]}
        self.assertIn("/x/main.py", by)                          # main-session file still there
        self.assertIn("/x/.worktrees/wt/auth.py", by)            # agent edit now surfaces
        self.assertIn("/x/.worktrees/wt/new.py", by)
        self.assertTrue(by["/x/.worktrees/wt/auth.py"]["agent"])  # tagged agent
        self.assertFalse(by["/x/main.py"].get("agent"))          # main file untagged
        self.assertTrue(by["/x/.worktrees/wt/new.py"]["created"])  # Write => created
        self.assertFalse(by["/x/.worktrees/wt/auth.py"]["created"])  # Edit => edited

    def test_counts_include_agent_files(self):
        c = parse_session(self.main)["counts"]
        self.assertEqual(c["created"], 2)   # main.py + agent new.py
        self.assertEqual(c["edited"], 1)    # agent auth.py

    def test_agent_file_is_diffable(self):
        ops = file_diffs(self.main, "/x/.worktrees/wt/auth.py")
        self.assertTrue(ops, "agent edit must be reconstructable from the agent transcript")
        self.assertIn("deny_by_default", ops[0]["diff"])


if __name__ == "__main__":
    unittest.main()
