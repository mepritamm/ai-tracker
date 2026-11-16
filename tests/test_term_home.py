"""L1 of terminal-at-root: tail-derived cwd (S1) and the recorded run dir."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker import config, term_gate
from aitracker.providers import claude


def _write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.proj = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(self.proj, "p"))
        patcher = mock.patch.object(config, "PROJECTS", self.proj)
        patcher.start()
        self.addCleanup(patcher.stop)

    def transcript(self, sid, rows):
        p = os.path.join(self.proj, "p", sid + ".jsonl")
        _write(p, rows)
        return p

    def fake_worktree(self, name):
        """root/ (main checkout) + root/.claude/worktrees/<name> (linked, .git file)."""
        root = os.path.join(self.tmp, "repo")
        g = os.path.join(root, ".git", "worktrees", name)
        os.makedirs(g, exist_ok=True)
        with open(os.path.join(g, "commondir"), "w") as fh:
            fh.write("../..\n")
        top = os.path.join(root, ".claude", "worktrees", name)
        os.makedirs(os.path.join(top, "sub"), exist_ok=True)
        with open(os.path.join(top, ".git"), "w") as fh:
            fh.write("gitdir: " + g + "\n")
        return root, top


class TestTailScanCwd(_Base):
    def test_latest_and_history(self):
        a, b = os.path.join(self.tmp, "a"), os.path.join(self.tmp, "b")
        p = self.transcript("s1", [
            {"cwd": a, "gitBranch": "feat"}, {"cwd": b, "gitBranch": "feat"}, {"cwd": a, "gitBranch": "feat"},
            {"type": "worktree-state", "worktreeSession": {"worktreePath": a}},
            {"type": "worktree-state", "worktreeSession": None}])
        t = claude._tail_scan(p)
        self.assertEqual(t["cwd"], a)
        self.assertEqual(t["cwds"], [a, b])          # newest first, distinct
        self.assertTrue(t["wt_seen"])
        self.assertIsNone(t["wt"])                   # null clears
        self.assertEqual(t["gitBranch"], "feat")

    def test_detached_head_is_no_branch(self):
        p = self.transcript("s2", [{"cwd": "/x", "gitBranch": "real"}, {"cwd": "/x", "gitBranch": "HEAD"}])
        self.assertEqual(claude._tail_scan(p)["gitBranch"], "")


class TestTailMemoCopyAndKey(_Base):
    def test_result_is_an_independent_copy(self):                       # F3
        p = self.transcript("m1", [{"cwd": "/a"}, {"cwd": "/b"}])
        t = claude._tail_scan(p)
        t["cwds"].append("/zzz")
        if isinstance(t.get("wt"), dict):
            t["wt"]["poison"] = 1
        t2 = claude._tail_scan(p)
        self.assertNotIn("/zzz", t2["cwds"])
        self.assertNotIn("poison", t2.get("wt") or {})

    def test_one_memo_entry_per_file(self):                             # F4
        p = self.transcript("m2", [{"cwd": "/a"}])
        claude._TAIL_MEMO.clear()
        for i in range(300):
            with open(p, "a") as fh:
                fh.write(json.dumps({"cwd": "/c%d" % i}) + "\n")
            os.utime(p, ns=(10**9 + i, 10**9 + i))     # distinct mtime each append
            claude._tail_scan(p)
        self.assertEqual(len(claude._TAIL_MEMO), 1)
        self.assertEqual(claude._tail_scan(p)["cwd"], "/c299")


class TestSessionCwdFastPath(_Base):
    def test_tail_cwd_without_parse_any(self):
        self.transcript("s3", [{"cwd": self.tmp}])
        with mock.patch("aitracker.registry.parse_any", side_effect=AssertionError):
            self.assertEqual(term_gate.session_cwd("s3"), self.tmp)

    def test_tail_empty_falls_back(self):
        self.transcript("s4", [{"cwd": self.tmp, "pad": "x" * 120000}])   # one 120 KB line
        with mock.patch("aitracker.registry.parse_any", return_value={"meta": {"cwd": self.tmp}}) as pa:
            self.assertEqual(term_gate.session_cwd("s4"), self.tmp)
        self.assertEqual(pa.call_count, 1)

    def test_no_transcript_falls_back(self):
        with mock.patch("aitracker.registry.parse_any", return_value={"meta": {"cwd": self.tmp}}) as pa:
            self.assertEqual(term_gate.session_cwd("nope"), self.tmp)
        self.assertEqual(pa.call_count, 1)

    def test_meta_arg_never_reenters_parse_any(self):
        self.transcript("s5", [{"cwd": "x", "pad": "y" * 120000}])
        with mock.patch("aitracker.registry.parse_any", side_effect=AssertionError):
            raw, br = term_gate.recorded_run_dir("s5", meta={"cwd": self.tmp, "gitBranch": "HEAD"})
        self.assertEqual((raw, br), (self.tmp, ""))


class TestTailMemo(_Base):
    def test_unchanged_not_reopened_changed_reread(self):
        root, top = self.fake_worktree("w")
        rows = [{"type": "user", "cwd": top, "message": {"role": "user", "content": "a"}}]
        path = self.transcript("sidm", rows)
        term_gate.recorded_run_dir("sidm")
        real_open = open
        opened = []

        def spy(f, *a, **k):
            if str(f) == path:
                opened.append(f)
            return real_open(f, *a, **k)
        with mock.patch("builtins.open", spy):
            self.assertEqual(term_gate.recorded_run_dir("sidm")[0], top)
            self.assertEqual(opened, [], "unchanged transcript was reopened")
            with real_open(path, "a") as fh:
                fh.write(json.dumps({"type": "user", "cwd": root, "message": {"role": "user", "content": "bb"}}) + "\n")
            term_gate.recorded_run_dir("sidm")
            self.assertTrue(opened, "appended transcript must be re-read")


class TestRunDirPreference(_Base):
    def test_wt_preferred_over_later_root_cwd(self):
        root, top = self.fake_worktree("w")
        self.transcript("s6", [{"cwd": top}, {"cwd": os.path.join(top, "sub")}, {"cwd": root, "gitBranch": "b"}])
        self.assertEqual(term_gate.recorded_run_dir("s6"), (top, "b"))

    def test_worktree_state_wins(self):
        root, top = self.fake_worktree("w")
        other = os.path.join(self.tmp, "other")
        self.transcript("s7", [{"cwd": other}, {"type": "worktree-state", "worktreeSession": {"worktreePath": top}}])
        self.assertEqual(term_gate.recorded_run_dir("s7")[0], top)

    def test_worktree_state_null_keeps_latest(self):
        root, top = self.fake_worktree("w")
        self.transcript("s8", [{"cwd": top}, {"type": "worktree-state", "worktreeSession": None}, {"cwd": root}])
        self.assertEqual(term_gate.recorded_run_dir("s8")[0], root)

    def test_non_claude_sid(self):
        self.assertEqual(term_gate.recorded_run_dir("auggie:abc"), ("", ""))


if __name__ == "__main__":
    unittest.main()
