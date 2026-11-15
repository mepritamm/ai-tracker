"""Step 7b: classify / reclaimable / scan_tmp / card on real temp repos (fixtures A, D, F, F2, G, H, I, K, L, M)."""
import os
import time
import unittest
from unittest import mock

from aitracker import config, pending
from tests.pending_fixture import make_fixture, requires_git


@requires_git
class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)

    def run_scan(self, now=None):
        rep = pending.scan(now or time.time())
        self.rep = rep
        return rep

    def item(self, path, rep=None):
        rep = rep or self.rep
        return next(i for i in rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(path))

    def merged_worktree(self, name="a", days=8):
        """Branch with a commit pushed straight to origin/main: merged, clean."""
        wt = self.fx.worktree(name)
        self.fx.commit(wt, name + ".txt", name)
        self.fx.git(wt, "push", "origin", "%s:main" % name)
        self.fx.git(self.fx.repo, "fetch", "origin")
        if days:
            self.fx.age(wt, days)
        return wt

    def test_A_merged_clean_aged_is_reclaimable(self):
        wt = self.merged_worktree()
        it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"], it["ancestor"], it["unpushed"]), ("clean", True, True, 0))
        self.assertTrue(pending.reclaimable(it, time.time()))
        self.assertIn("worktree reclaimable", it["label"])

    def test_B_dirty_is_pending(self):
        wt = self.merged_worktree()
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("x")
        it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"]), ("pending", False))
        self.assertFalse(pending.reclaimable(it, time.time()))

    def test_C_unpushed_is_pending_and_gh_none_keeps(self):
        wt = self.fx.worktree("c")
        self.fx.commit(wt, "c.txt", "c")
        self.fx.age(wt, 8)
        it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["unpushed"], it["deletable"]), ("pending", 1, False))
        self.assertIn("1 unpushed", it["reason"])

    def test_E_pushed_not_merged_clean_but_not_reclaimable(self):
        wt = self.fx.worktree("e")
        self.fx.commit(wt, "e.txt", "e")
        self.fx.git(wt, "push", "-u", "origin", "e")
        self.fx.age(wt, 8)
        it = self.item(wt, self.run_scan())
        self.assertEqual(it["verdict"], "clean")
        self.assertEqual(it["reason"], "pushed; not merged into origin/main")
        self.assertTrue(it["deletable"])
        self.assertFalse(pending.reclaimable(it, time.time()))           # ancestor term

    def test_D_missing_worktree_contained(self):
        d = self.fx.worktree("d")
        self.fx.commit(d, "d.txt", "d")
        os.system("rm -rf '%s'" % d)
        it = self.item(d, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"], it["contained"]), ("missing", False, True))
        self.assertEqual(it["reason"], "branch has 1 unpushed")
        self.assertEqual(self.rep["card"]["count"], 1)

    def test_H_detached_orphan_commit(self):
        h = self.fx.worktree("h", detach=True)
        sha = self.fx.commit(h, "h.txt", "h")
        os.system("rm -rf '%s'" % h)
        it = self.item(h, self.run_scan())
        self.assertEqual((it["verdict"], it["contained"], it["reason"]), ("missing", False, "1 orphan commits"))
        self.assertEqual(self.fx.git(self.fx.repo, "cat-file", "-t", sha), "commit")

    def test_F_fresh_worktree_not_reclaimable(self):
        wt = self.merged_worktree(days=0)
        it = self.item(wt, self.run_scan())
        self.assertTrue(it["deletable"])
        self.assertFalse(pending.reclaimable(it, time.time()))            # idle < grace

    def test_F2_unfinished_job_blocks(self):
        wt = self.merged_worktree()
        self.fx.job("jb", "blocked", cwd=wt)
        it = self.item(wt, self.run_scan())
        self.assertTrue(it["busy_job"])
        self.assertFalse(pending.reclaimable(it, time.time()))
        self.fx.job("jb", "done", cwd=wt)
        it = self.item(wt, self.run_scan())
        self.assertTrue(pending.reclaimable(it, time.time()))             # finished job no longer blocks

    def test_live_session_blocks(self):
        wt = self.merged_worktree()
        self.fx.live(os.getpid(), wt)
        it = self.item(wt, self.run_scan())
        self.assertTrue(it["live"])
        self.assertFalse(pending.reclaimable(it, time.time()))

    def test_G_ignored_file_not_deletable(self):
        wt = self.merged_worktree()
        self.fx.commit(wt, ".gitignore", ".env\n")
        self.fx.git(wt, "push", "origin", "a:main")
        self.fx.git(self.fx.repo, "fetch", "origin")
        self.fx.age(wt, 8)
        with open(os.path.join(wt, ".env"), "w") as fh:
            fh.write("SECRET")
        it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["ignored"], it["deletable"]), ("clean", 1, False))
        self.assertIn("1 ignored", it["label"])
        self.assertFalse(pending.reclaimable(it, time.time()))
        with open(os.path.join(wt, ".env")) as fh:
            self.assertEqual(fh.read(), "SECRET")

    def test_I_primary_never_deletable(self):
        with open(os.path.join(self.fx.repo, "a.txt"), "w") as fh:
            fh.write("dirty")
        it = self.item(self.fx.repo, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"], it["primary"]), ("pending", False, True))
        self.fx.git(self.fx.repo, "checkout", "--", "a.txt")
        it = self.item(self.fx.repo, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"]), ("clean", False))   # clean primary: still never deletable

    def test_M_own_tracker_worktree(self):
        wt = self.merged_worktree()
        os.makedirs(os.path.join(wt, "aitracker"))
        with mock.patch.object(config, "_HERE", os.path.join(wt, "aitracker")):
            it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"]), ("clean", False))

    def test_unknown_on_git_error_not_deletable(self):
        wt = self.merged_worktree()
        real = pending._git

        def flaky(cwd, *a):
            if a and a[0] == "status":
                return None, ""
            return real(cwd, *a)
        with mock.patch.object(pending, "_git", flaky):
            it = self.item(wt, self.run_scan())
        self.assertEqual((it["verdict"], it["deletable"]), ("unknown", False))
        self.assertFalse(pending.reclaimable(it, time.time()))
        self.assertEqual(self.rep["card"]["count"], 2)         # both items (primary + worktree) unverifiable work is never invisible (E1-F2)

    def test_card_show_hide(self):
        self.merged_worktree()
        self.assertFalse(self.run_scan()["card"]["show"])
        wt = self.fx.worktree("c")
        self.fx.commit(wt, "c.txt", "c")
        self.fx.age(wt, 3)
        card = self.run_scan()["card"]
        self.assertEqual((card["show"], card["count"]), (True, 1))
        self.assertIn("1 worktree with unfinished work (oldest idle 3d)", card["summary"])


@requires_git
class TmpTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)
        self.now = time.time()

    def tmp(self):
        return pending.scan_tmp(pending.build_ctx(), self.now)

    def make_tree(self, path, days=8, files=("f.txt",)):
        os.makedirs(path, exist_ok=True)
        for f in files:
            with open(os.path.join(path, f), "w") as fh:
                fh.write("x")
        self.fx.age_tree(path, days)
        return path

    def test_done_job_tmp_stale_and_unfinished_kept(self):
        d = self.fx.job("done1", "done")
        self.make_tree(os.path.join(d, "tmp"))
        d2 = self.fx.job("work1", "working")
        self.make_tree(os.path.join(d2, "tmp"))
        ents, _ = self.tmp()
        by = {e["job"]: e for e in ents}
        self.assertEqual((by["done1"]["verdict"], by["done1"]["deletable"]), ("stale", True))
        self.assertEqual((by["work1"]["verdict"], by["work1"]["deletable"]), ("keep", False))

    def test_recent_mtime_keeps(self):
        d = self.fx.job("done2", "done")
        self.make_tree(os.path.join(d, "tmp"), days=1)
        self.assertEqual(self.tmp()[0][0]["verdict"], "keep")

    def test_K_tmp_holding_standalone_repo_kept_and_discovered(self):
        d = self.fx.job("done3", "done")
        t = self.make_tree(os.path.join(d, "tmp", "proj"), files=())
        self.fx.git(t, "init", "-b", "main")
        self.fx.commit(t, "p.txt", "p")
        self.fx.age_tree(os.path.join(d, "tmp"), 8)
        ents, roots = self.tmp()
        e = next(e for e in ents if e["job"] == "done3")
        self.assertEqual((e["verdict"], e["deletable"]), ("keep", False))
        self.assertEqual([os.path.realpath(r) for r in roots], [os.path.realpath(t)])
        rep = pending.scan(self.now)
        it = next(i for i in rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(t))
        self.assertEqual((it["kind"], it["verdict"], it["unpushed"], it["deletable"]), ("repo", "pending", 1, False))

    def test_L_scratch_root_symlink_and_sibling(self):
        # a symlinked SCRATCH_ROOT is never trusted (E1-F6): nothing under it, or its siblings, is listed
        real = os.path.join(self.fx.root, "real-scratch")
        os.makedirs(os.path.join(real, "slug"))
        os.chmod(real, 0o700)
        link = os.path.join(self.fx.root, "scr-link")
        os.symlink(real, link)
        self.make_tree(os.path.join(real, "slug", "sid1"))
        sib = self.make_tree(os.path.join(self.fx.root, "scr-link0", "slug", "sid2"))
        with mock.patch.object(config, "SCRATCH_ROOT", link):
            ents, _ = self.tmp()
        self.assertEqual([e for e in ents if e["kind"] == "scratch"], [])
        # a real private root works; a slug that is a symlink escaping the root is never listed
        outside = self.make_tree(os.path.join(self.fx.root, "outside", "sid3"))
        os.symlink(os.path.join(self.fx.root, "outside"), os.path.join(real, "esc"))
        with mock.patch.object(config, "SCRATCH_ROOT", real):
            ents, _ = self.tmp()
        paths = [os.path.realpath(e["path"]) for e in ents]
        self.assertEqual(paths, [os.path.realpath(os.path.join(real, "slug", "sid1"))])
        self.assertEqual(ents[0]["verdict"], "stale")
        self.assertNotIn(os.path.realpath(sib), paths)
        self.assertNotIn(os.path.realpath(outside), paths)

    def _scratch_root(self):
        root = os.path.join(self.fx.root, "scratch")
        os.makedirs(os.path.join(root, "slug"), exist_ok=True)
        os.chmod(root, 0o700)
        return root

    def test_scratch_recent_transcript_keeps(self):
        # no job owns the sid; the transcript was written just now, so an 8-day-old tree is still kept
        sid = "sidT"
        d = os.path.join(self.fx.paths["PROJECTS"], "p")
        os.makedirs(d)
        with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
            fh.write("{}\n")
        root = self._scratch_root()
        self.make_tree(os.path.join(root, "slug", sid), days=8)
        e = next(e for e in self.tmp()[0] if e["kind"] == "scratch")
        self.assertEqual((e["verdict"], e["deletable"], e["reason"]), ("keep", False, "recent transcript"))
        # control: same tree with an aged transcript is stale, so the transcript is what kept it
        t = time.time() - 9 * 86400
        os.utime(os.path.join(d, sid + ".jsonl"), (t, t))
        e = next(e for e in self.tmp()[0] if e["kind"] == "scratch")
        self.assertEqual((e["verdict"], e["deletable"]), ("stale", True))

    def test_scratch_sid_symlink_keeps(self):
        root = self._scratch_root()
        self.make_tree(os.path.join(root, "slug", "real"), days=8)
        os.symlink(os.path.join(root, "slug", "real"), os.path.join(root, "slug", "sidL"))
        by = {os.path.basename(e["path"]): e for e in self.tmp()[0] if e["kind"] == "scratch"}
        self.assertEqual((by["sidL"]["verdict"], by["sidL"]["deletable"], by["sidL"]["reason"]),
                         ("keep", False, "symlink"))
        self.assertEqual(by["real"]["verdict"], "stale")

    def test_entry_cap_keeps(self):
        d = self.fx.job("done4", "done")
        self.make_tree(os.path.join(d, "tmp"), files=("a", "b", "c"))
        with mock.patch.object(pending, "SCAN_ENTRY_CAP", 2):
            e = self.tmp()[0][0]
        self.assertEqual((e["verdict"], e["reason"]), ("keep", "too many entries to verify"))

    def test_stale_tmp_counts_in_card(self):
        d = self.fx.job("done5", "done")
        self.make_tree(os.path.join(d, "tmp"))
        card = pending.scan(self.now)["card"]
        self.assertEqual((card["show"], card["count"]), (True, 1))
        self.assertIn("1 stale tmp tree", card["summary"])


if __name__ == "__main__":
    unittest.main()
