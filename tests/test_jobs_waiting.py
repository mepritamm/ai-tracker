"""Claude Code background jobs blocked on the user ("Needs input", ~/.claude/jobs/<id>/state.json
state == "blocked") must surface as waiting + a "⧖ <question>" now_line, via the real list_sessions()
and parse_session(); a done job and a job dir with no state.json must not."""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config
from aitracker.providers.claude import list_sessions, parse_session


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _job(jdir, name, state=None):
    d = os.path.join(jdir, name)
    os.makedirs(d)
    if state is not None:
        with open(os.path.join(d, "state.json"), "w") as fh:
            json.dump(state, fh)


class BlockedJobWaitingTests(unittest.TestCase):
    def setUp(self):
        self._snap = (config.PROJECTS, config.JOBS_DIR)
        self.pdir = tempfile.mkdtemp()
        self.jdir = tempfile.mkdtemp()
        config.PROJECTS, config.JOBS_DIR = self.pdir, self.jdir
        sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(sdir)
        self.paths = {}
        for sid in ("s_blocked", "s_done"):
            self.paths[sid] = os.path.join(sdir, sid + ".jsonl")
            _write_jsonl(self.paths[sid], [
                {"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
                 "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "working on it"}]}},
            ])
        _job(self.jdir, "aaa111", {"state": "blocked", "needs": "pick A or B", "sessionId": "s_blocked"})
        _job(self.jdir, "bbb222", {"state": "done", "sessionId": "s_done"})
        _job(self.jdir, "ccc333")   # no state.json

    def tearDown(self):
        config.PROJECTS, config.JOBS_DIR = self._snap
        shutil.rmtree(self.pdir, ignore_errors=True)
        shutil.rmtree(self.jdir, ignore_errors=True)

    def test_list_sessions(self):
        by_id = {r["id"]: r for r in list_sessions()}
        self.assertTrue(by_id["s_blocked"]["waiting"])
        self.assertIn("pick A or B", by_id["s_blocked"]["now_line"])
        self.assertFalse(by_id["s_done"]["waiting"])
        self.assertNotIn("⧖", by_id["s_done"]["now_line"])
        self.assertIn("pick A or B", by_id["s_blocked"]["needs"])
        self.assertEqual(by_id["s_done"]["needs"], "")

    def test_parse_session_detail(self):
        self.assertTrue(parse_session(self.paths["s_blocked"])["waiting"])
        self.assertFalse(parse_session(self.paths["s_done"])["waiting"])

    def test_detail_overview_now_shows_question(self):
        self.assertIn("pick A or B", parse_session(self.paths["s_blocked"])["overview"]["now"])

    def _extra(self, sid, state):
        p = os.path.join(self.pdir, "-tmp-proj", sid + ".jsonl")
        _write_jsonl(p, [{"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
                          "message": {"role": "user", "content": "go"}}])
        _job(self.jdir, "x_" + sid, dict(state, state="blocked", sessionId=sid))
        return {r["id"]: r for r in list_sessions()}[sid]

    def test_long_needs_truncated_single_line(self):
        row = self._extra("s_long", {"needs": ("word " * 20).strip() + "\n" + "tail " * 20})
        self.assertNotIn("\n", row["now_line"])
        self.assertLessEqual(len(row["now_line"]), 62)

    def test_detail_only_not_used(self):
        row = self._extra("s_det", {"detail": "<bash-stdout>junk</bash-stdout>"})
        self.assertNotIn("junk", row["now_line"])
        self.assertIn("needs your input", row["now_line"])


if __name__ == "__main__":
    unittest.main()
