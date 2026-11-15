"""Step 9: `clean` (the only code that deletes) on real temp repos. Every path lives in a mkdtemp; no test
touches real worktrees, ~/.claude or the real gh."""
import os
import time
import unittest
from unittest import mock

from aitracker import config, pending
from tests.pending_fixture import make_fixture, requires_git


def pr(sha, n=12, base="main"):
    return {"number": n, "url": "https://github.com/o/r/pull/%d" % n, "headRefOid": sha,
            "baseRefName": base, "mergedAt": "2026-11-01T00:00:00Z"}


@requires_git
class CleanTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)
        self.calls = []
        real = pending._git

        def spy(cwd, *a):
            self.calls.append(a)
            return real(cwd, *a)
        p = mock.patch.object(pending, "_git", spy)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        # no run of any test may ever force-remove or -D a branch
        for a in self.calls:
            self.assertNotIn("--force", a)
            self.assertNotIn("-f", a)
            self.assertNotIn("-D", a)

    # -- helpers
    def merged_worktree(self, name="a", days=8, ff_primary=True):
        wt = self.fx.worktree(name)
        self.fx.commit(wt, name + ".txt", name)
        self.fx.git(wt, "push", "origin", "%s:main" % name)
        self.fx.git(self.fx.repo, "fetch", "origin")
        if ff_primary:
            self.fx.git(self.fx.repo, "merge", "--ff-only", "origin/main")
        self.fx.age(wt, days)
        return wt

    def scan_clean(self, mode, now=None):
        now = now or time.time()
        rep = pending.scan(now)
        pending.clean(rep, mode, now)
        self.rep = rep
        return rep

    def scan(self):
        self.now = time.time()
        self.rep = pending.scan(self.now)
        return self.rep

    def item(self, path):
        return next(i for i in self.rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(path))

    def branches(self):
        return self.fx.git(self.fx.repo, "branch", "--format=%(refname:short)").split()

    def log(self):
        try:
            return open(config.PENDING_LOG).read()
        except OSError:
            return ""

    # -- worktrees
    def test_A_safe_removes_worktree_and_branch(self):
        wt = self.merged_worktree()
        rep = self.scan_clean("safe")
        self.assertFalse(os.path.exists(wt))
        self.assertNotIn("a", self.branches())
        self.assertEqual([d["path"] for d in rep["deleted"] if d["kind"] == "worktree"], [wt])
        self.assertTrue(rep["deleted"][0]["branch_deleted"])
        self.assertEqual(rep["refused"], [])
        self.assertNotIn(os.path.realpath(wt), [os.path.realpath(i["path"]) for i in rep["items"]])
        self.assertIn("DELETED worktree", self.log())

    def test_branch_d_refusal_keeps_ref_not_dash_D(self):
        wt = self.merged_worktree()
        real = pending._git
        refuse_d = lambda cwd, *a: (1, "") if a[:2] == ("branch", "-d") else real(cwd, *a)
        with mock.patch.object(pending, "_git", refuse_d):
            rep = self.scan_clean("safe")
        self.assertFalse(os.path.exists(wt))                  # worktree removed ...
        self.assertIn("a", self.branches())                   # ... branch ref kept
        self.assertFalse(rep["deleted"][0]["branch_deleted"])
        self.assertIn("branch kept", rep["deleted"][0]["note"])

    def test_dry_run_removes_nothing(self):
        wt = self.merged_worktree()
        before = self.fx.git(self.fx.repo, "worktree", "list", "--porcelain")
        rep = self.scan_clean("dry-run")
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(self.fx.git(self.fx.repo, "worktree", "list", "--porcelain"), before)
        self.assertEqual(rep["deleted"], [])
        self.assertEqual([w["path"] for w in rep["would_delete"] if w["kind"] == "worktree"], [wt])
        self.assertFalse([a for a in self.calls if a[:2] == ("worktree", "remove")])

    def test_off_mode_and_unknown_mode_do_nothing(self):
        wt = self.merged_worktree()
        for mode in ("off", "bogus", None):
            rep = self.scan_clean(mode)
            self.assertTrue(os.path.isdir(wt))
            self.assertEqual((rep["deleted"], rep["would_delete"]), ([], []))

    def test_N1_squash_merged_worktree_removed_branch_kept(self):
        wt = self.fx.worktree("n1")
        sha = self.fx.commit(wt, "n1.txt", "n1")
        self.fx.age(wt, 8)
        self.fx.fake_gh({"n1": [pr(sha)]})
        rep = self.scan_clean("safe")
        self.assertFalse(os.path.exists(wt))
        self.assertIn("n1", self.branches())                                  # ref kept ...
        self.assertEqual(self.fx.git(self.fx.repo, "cat-file", "-t", sha), "commit")   # ... commits reachable
        self.assertFalse(rep["deleted"][0]["branch_deleted"])
        self.assertIn("squash-merged", rep["deleted"][0]["note"])

    # -- TOCTOU: the item changes between the scan and the clean
    def toctou(self, mutate):
        wt = self.merged_worktree()
        rep = self.scan()
        self.assertTrue(pending.reclaimable(self.item(wt), self.now))        # the scan said "reclaimable"
        mutate(wt)
        pending.clean(rep, "safe", self.now)
        return wt, rep

    def test_toctou_dirty_survives(self):
        def dirty(wt):
            with open(os.path.join(wt, "a.txt"), "w") as fh:
                fh.write("edited after the scan")
        wt, rep = self.toctou(dirty)
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(open(os.path.join(wt, "a.txt")).read(), "edited after the scan")
        self.assertEqual(rep["deleted"], [])
        self.assertIn("re-inspection", rep["refused"][0]["reason"])
        self.assertIn("REFUSED worktree", self.log())

    def test_toctou_untracked_survives(self):
        def new(wt):
            with open(os.path.join(wt, "notes.txt"), "w") as fh:
                fh.write("n")
        wt, rep = self.toctou(new)
        self.assertTrue(os.path.isfile(os.path.join(wt, "notes.txt")))
        self.assertEqual(rep["deleted"], [])

    def test_toctou_head_moved_survives(self):
        wt, rep = self.toctou(lambda w: self.fx.commit(w, "late.txt", "late"))
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(rep["deleted"], [])

    def test_toctou_live_session_survives(self):
        wt, rep = self.toctou(lambda w: self.fx.live(os.getpid(), w))
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(rep["deleted"], [])

    def test_toctou_new_unfinished_job_survives(self):
        wt, rep = self.toctou(lambda w: self.fx.job("jb", "working", cwd=w))
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(rep["deleted"], [])

    def test_toctou_worktree_vanished(self):
        def gone(wt):
            self.fx.git(self.fx.repo, "worktree", "remove", wt)
        wt, rep = self.toctou(gone)
        self.assertEqual(rep["deleted"], [])
        self.assertIn("vanished", rep["refused"][0]["reason"])

    # -- guards that keep
    def test_G_ignored_file_survives(self):
        wt = self.merged_worktree()
        with open(os.path.join(wt, ".gitignore"), "w") as fh:
            fh.write(".env\n")
        self.fx.git(wt, "add", ".gitignore")
        self.fx.git(wt, "commit", "-m", "ignore")
        self.fx.git(wt, "push", "origin", "a:main")
        self.fx.git(self.fx.repo, "fetch", "origin")
        with open(os.path.join(wt, ".env"), "w") as fh:
            fh.write("SECRET=1")
        self.fx.age(wt, 8)
        self.scan_clean("safe")
        self.assertEqual(open(os.path.join(wt, ".env")).read(), "SECRET=1")
        self.assertEqual(self.rep["deleted"], [])

    def test_I_primary_checkout_never_removed(self):
        self.merged_worktree()
        self.fx.age(self.fx.repo, 30)
        self.scan_clean("safe")
        self.assertTrue(os.path.isdir(self.fx.repo))
        self.assertNotIn(self.fx.repo, [d["path"] for d in self.rep["deleted"]])

    def test_unpushed_survives_and_fresh_survives(self):
        c = self.fx.worktree("c")
        self.fx.commit(c, "c.txt", "c")
        self.fx.age(c, 8)
        f = self.merged_worktree("f", days=0)
        self.scan_clean("safe")
        self.assertTrue(os.path.isdir(c))
        self.assertTrue(os.path.isdir(f))
        self.assertEqual(self.rep["deleted"], [])

    def test_error_in_reinspect_keeps(self):
        wt = self.merged_worktree()
        rep = self.scan()
        with mock.patch.object(pending, "list_worktrees", side_effect=RuntimeError("boom")):
            pending.clean(rep, "safe", self.now)
        self.assertTrue(os.path.isdir(wt))
        self.assertIn("boom", rep["refused"][0]["reason"])

    def test_git_remove_failure_keeps(self):
        wt = self.merged_worktree()
        rep = self.scan()
        real = pending._git

        def failing(cwd, *a):
            if a[:2] == ("worktree", "remove"):
                return 1, ""
            return real(cwd, *a)
        with mock.patch.object(pending, "_git", failing):
            pending.clean(rep, "safe", self.now)
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(rep["deleted"], [])
        self.assertIn("refused", rep["refused"][0]["reason"])

    def test_git_timeout_keeps(self):
        wt = self.merged_worktree()
        rep = self.scan()
        real = pending._git

        def timing_out(cwd, *a):
            if a[:2] == ("worktree", "remove"):
                return None, ""
            return real(cwd, *a)
        with mock.patch.object(pending, "_git", timing_out):
            pending.clean(rep, "safe", self.now)
        self.assertTrue(os.path.isdir(wt))
        self.assertIn("timeout", rep["refused"][0]["reason"])

    # -- prune of missing worktrees
    def test_D_prune_contained_missing(self):
        d = self.merged_worktree("d", days=0)
        os.system("rm -rf '%s'" % d)
        rep = self.scan_clean("safe")
        self.assertEqual([x["kind"] for x in rep["deleted"]], ["prune"])
        self.assertNotIn(d, self.fx.git(self.fx.repo, "worktree", "list"))
        self.assertIn("d", self.branches())                                    # prune never touches the branch

    def test_H_prune_skipped_for_orphan_commits(self):
        h = self.fx.worktree("h", detach=True)
        sha = self.fx.commit(h, "h.txt", "h")
        os.system("rm -rf '%s'" % h)
        rep = self.scan_clean("safe")
        self.assertEqual(rep["deleted"], [])
        self.assertIn("orphan", rep["refused"][0]["reason"])
        self.assertEqual(self.fx.git(self.fx.repo, "cat-file", "-t", sha), "commit")
        self.assertIn(os.path.basename(h), self.fx.git(self.fx.repo, "worktree", "list", "--porcelain"))

    def test_prune_dry_run_only_lists(self):
        d = self.merged_worktree("d", days=0)
        os.system("rm -rf '%s'" % d)
        rep = self.scan_clean("dry-run")
        self.assertEqual(rep["deleted"], [])
        self.assertEqual([w["kind"] for w in rep["would_delete"]], ["prune"])
        self.assertTrue([w for w in self.fx.git(self.fx.repo, "worktree", "list").splitlines() if "/d " in w])

    # -- tmp
    def tmp_tree(self, jid="done1", state="done", days=8, files=("f.txt",)):
        d = self.fx.job(jid, state)
        t = os.path.join(d, "tmp")
        for f in files:
            with open(os.path.join(t, f), "w") as fh:
                fh.write("x")
        self.fx.age_tree(t, days)
        return d, t

    def test_tmp_stale_removed_state_and_transcripts_untouched(self):
        d, t = self.tmp_tree()
        tx = os.path.join(config.PROJECTS, "p")
        os.makedirs(tx)
        jl = os.path.join(tx, "abc.jsonl")
        open(jl, "w").write("{}\n")
        old = time.time() - 30 * 86400
        os.utime(jl, (old, old))
        rep = self.scan_clean("safe")
        self.assertFalse(os.path.exists(t))
        self.assertTrue(os.path.isfile(os.path.join(d, "state.json")))
        self.assertTrue(os.path.isfile(jl))
        self.assertEqual([x["kind"] for x in rep["deleted"]], ["scratch"])
        self.assertEqual(rep["tmp"], [])

    def test_tmp_dry_run_lists_only(self):
        d, t = self.tmp_tree()
        rep = self.scan_clean("dry-run")
        self.assertTrue(os.path.isdir(t))
        self.assertEqual([w["kind"] for w in rep["would_delete"]], ["scratch"])

    def test_K_tmp_with_git_repo_survives(self):
        d, t = self.tmp_tree()
        proj = os.path.join(t, "proj")
        os.makedirs(proj)
        self.fx.git(proj, "init", "-b", "main")
        self.fx.commit(proj, "p.txt", "p")
        self.fx.age_tree(t, 8)
        self.scan_clean("safe")
        self.assertTrue(os.path.isdir(os.path.join(proj, ".git")))
        self.assertTrue(os.path.isfile(os.path.join(proj, "p.txt")))

    def test_tmp_git_appearing_after_scan_survives(self):
        d, t = self.tmp_tree()
        rep = self.scan()
        self.assertTrue([x for x in rep["tmp"] if x["deletable"]])
        os.makedirs(os.path.join(t, "late", ".git"))                          # a repo shows up between scan and clean
        self.fx.age_tree(t, 8)
        pending.clean(rep, "safe", self.now)
        self.assertTrue(os.path.isdir(os.path.join(t, "late", ".git")))
        self.assertEqual(rep["deleted"], [])

    def test_tmp_becoming_active_after_scan_survives(self):
        d, t = self.tmp_tree()
        rep = self.scan()
        with open(os.path.join(t, "fresh.txt"), "w") as fh:                   # mtime = now
            fh.write("x")
        pending.clean(rep, "safe", self.now)
        self.assertTrue(os.path.isfile(os.path.join(t, "fresh.txt")))
        self.assertEqual(rep["deleted"], [])

    def test_L_scratch_symlink_root_sibling_kept(self):
        real = os.path.join(self.fx.root, "real-scratch")
        sid = os.path.join(real, "slug", "sid1")
        os.makedirs(sid)
        open(os.path.join(sid, "f"), "w").write("x")
        self.fx.age_tree(sid, 8)
        link = os.path.join(self.fx.root, "scr-link")
        os.symlink(real, link)
        sib = os.path.join(self.fx.root, "scr-link0", "slug", "sid2")
        os.makedirs(sib)
        open(os.path.join(sib, "f"), "w").write("x")
        self.fx.age_tree(sib, 8)
        with mock.patch.object(config, "SCRATCH_ROOT", link):
            self.scan_clean("safe")
        self.assertFalse(os.path.exists(sid))
        self.assertTrue(os.path.isfile(os.path.join(sib, "f")))

    def test_tmp_leaf_symlink_not_followed(self):
        d, t = self.tmp_tree()
        victim = os.path.join(self.fx.root, "victim")
        os.makedirs(victim)
        open(os.path.join(victim, "keep"), "w").write("x")
        os.symlink(victim, os.path.join(t, "lnk"))
        self.fx.age_tree(t, 8)
        self.scan_clean("safe")
        self.assertTrue(os.path.isfile(os.path.join(victim, "keep")))

    # -- own tracker
    def test_M_own_tracker_checkout_survives(self):
        wt = self.merged_worktree()
        with mock.patch.object(config, "_HERE", os.path.join(wt, "aitracker")):
            self.scan_clean("safe")
        self.assertTrue(os.path.isdir(wt))


if __name__ == "__main__":
    unittest.main()
