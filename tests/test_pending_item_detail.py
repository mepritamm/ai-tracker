"""item_detail runs its four read-only git calls concurrently (M8) without changing the output."""
import tempfile
import time
import unittest
from unittest import mock

from aitracker import pending
from tests.pending_fixture import make_fixture, requires_git


def _stub_capped(delay, fail=None):
    def f(cwd, max_bytes, *args):
        time.sleep(delay)
        if fail and args[0] == fail:
            raise RuntimeError("boom")
        return 0, "out-%s-%s\n" % (args[0], len(args))
    return f


class ItemDetailConcurrency(unittest.TestCase):
    def _detail(self, capped):
        with tempfile.TemporaryDirectory() as d:
            report = {"generated_at": 1, "items": [{"id": "x1", "path": d, "branch": "b", "verdict": "keep", "kind": "worktree"}],
                      "tmp": []}
            with mock.patch.object(pending, "_read_report", return_value=report), \
                    mock.patch.object(pending, "_git", return_value=(0, "abc\n")), \
                    mock.patch.object(pending, "_git_capped", side_effect=capped):
                t = time.time()
                out = pending.item_detail("x1")
                return out, time.time() - t, d

    def test_parallel_and_same_output(self):
        slow, dt, d = self._detail(_stub_capped(0.3))
        self.assertLess(dt, 0.6)
        fast, _, d2 = self._detail(_stub_capped(0))
        self.assertEqual(slow["md"].replace(d, "P"), fast["md"].replace(d2, "P"))
        md = slow["md"]
        pos = [md.index(h) for h in ("**git status --short**", "**git diff HEAD --stat**", "**git diff HEAD**", "**git log --oneline")]
        self.assertEqual(pos, sorted(pos))

    def test_failed_call_keeps_other_sections(self):
        out, _, _ = self._detail(_stub_capped(0, fail="diff"))
        self.assertIn("out-status", out["md"])
        self.assertIn("out-log", out["md"])
        self.assertIn("(git failed)", out["md"])


@requires_git
class ItemDetailRealKinds(unittest.TestCase):
    """repo-kind (primary checkout) and worktree-kind items both carry status, diff summary and log."""

    def test_repo_and_worktree_kinds_have_all_sections(self):
        fx = make_fixture(self)
        fx.commit(fx.repo, "b.txt", "unpushed")                 # one unpushed commit on the primary
        wt = fx.worktree("feat")
        for d in (fx.repo, wt):
            with open(fx.repo + "/a.txt" if d == fx.repo else wt + "/a.txt", "a") as fh:
                fh.write("more")
            for n in ("u1.txt", "u2.txt"):
                with open(d + "/" + n, "w") as fh:
                    fh.write("x")
        report = pending.scan()
        from aitracker.store import _save_json
        from aitracker import config
        _save_json(config.PENDING_FILE, report)
        pending._REPORT_MEMO.clear()
        kinds = {i["kind"]: i for i in report["items"]}
        self.assertEqual(set(kinds), {"repo", "worktree"})
        for kind, it in kinds.items():
            md = pending.item_detail(it["id"])["md"]
            self.assertIn("**git status --short**", md, kind)
            self.assertIn(" M a.txt", md, kind)
            self.assertIn("?? u1.txt", md, kind)
            self.assertIn("?? u2.txt", md, kind)
            self.assertIn("**git diff HEAD --stat**", md, kind)
            self.assertIn("a.txt", md.split("**git diff HEAD --stat**")[1], kind)
        self.assertIn("c b.txt", pending.item_detail(kinds["repo"]["id"])["md"].split("**git log")[1])


if __name__ == "__main__":
    unittest.main()
