"""Step 7a: pending.py discovery + read-only inspection (fixtures B, C, E, I, J), _under/_alive/_pending_lock/_git."""
import os
import subprocess
import unittest
from unittest import mock

from aitracker import pending
from tests.pending_fixture import make_fixture, requires_git


def by_path(items, path):
    return next(i for i in items if os.path.realpath(i["path"]) == os.path.realpath(path))


@requires_git
class InspectTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)

    def inspect(self, path):
        repos = pending.discover_repos(0)
        self.assertEqual(len(repos), 1)
        repo = next(iter(repos.values()))
        ctx = pending.build_ctx()
        wts = pending.list_worktrees(repo)
        return pending.inspect_worktree(next(w for w in wts if os.path.realpath(w["path"]) == os.path.realpath(path)), repo, ctx)

    def test_B_uncommitted_edit(self):
        wt = self.fx.worktree("b")
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("edited")
        it = self.inspect(wt)
        self.assertEqual((it["dirty"], it["untracked"], it["unpushed"], it["error"]), (1, 0, 0, None))
        self.assertEqual(it["files"], ["a.txt"])
        self.assertTrue(it["ancestor"])

    def test_untracked_and_ignored_counted(self):
        wt = self.fx.worktree("u")
        self.fx.commit(wt, ".gitignore", ".env\n")
        with open(os.path.join(wt, "new.txt"), "w") as fh:
            fh.write("x")
        with open(os.path.join(wt, ".env"), "w") as fh:
            fh.write("SECRET")
        it = self.inspect(wt)
        self.assertEqual((it["untracked"], it["ignored"]), (1, 1))
        self.assertEqual(it["ignored_files"], [".env"])

    def test_C_local_commit_never_pushed(self):
        wt = self.fx.worktree("c")
        self.fx.commit(wt, "c.txt", "c")
        it = self.inspect(wt)
        self.assertEqual((it["unpushed"], it["ancestor"], it["dirty"]), (1, False, 0))
        self.assertEqual(it["base"], "origin/main")

    def test_E_pushed_not_merged(self):
        wt = self.fx.worktree("e")
        self.fx.commit(wt, "e.txt", "e")
        self.fx.git(wt, "push", "-u", "origin", "e")
        it = self.inspect(wt)
        self.assertEqual((it["unpushed"], it["ancestor"], it["upstream"], it["ahead"], it["behind"]),
                         (0, False, "origin/e", 0, 0))

    def test_I_dirty_primary(self):
        with open(os.path.join(self.fx.repo, "a.txt"), "w") as fh:
            fh.write("dirty")
        it = self.inspect(self.fx.repo)
        self.assertEqual((it["primary"], it["kind"], it["dirty"]), (True, "repo", 1))
        with open(os.path.join(self.fx.repo, "a.txt")) as fh:
            self.assertEqual(fh.read(), "dirty")           # inspection never touches the tree

    def test_J_branch_tracking_local_main_two_ahead(self):
        self.fx.commit(self.fx.repo, "m1.txt", "1")
        self.fx.commit(self.fx.repo, "m2.txt", "2")
        wt = self.fx.worktree("j", base="main")
        self.fx.git(wt, "branch", "--set-upstream-to=main")
        it = self.inspect(wt)
        self.assertEqual(it["unpushed"], 2)               # --not --remotes: tracking a LOCAL branch is not "pushed"
        self.assertEqual(it["upstream"], "main")

    def test_missing_worktree_contained_vs_orphan(self):
        d = self.fx.worktree("d")
        self.fx.commit(d, "d.txt", "d")
        h = self.fx.worktree("h", detach=True)
        self.fx.commit(h, "h.txt", "h")
        for p in (d, h):
            subprocess.run(["rm", "-rf", p], check=True)
        repo = next(iter(pending.discover_repos(0).values()))
        ctx = pending.build_ctx()
        wts = {os.path.basename(w["path"]): w for w in pending.list_worktrees(repo)}
        di, hi = (pending.inspect_worktree(wts[n], repo, ctx) for n in ("d", "h"))
        self.assertEqual((di["missing"], di["contained"], di["unpushed"]), (True, True, 1))
        self.assertEqual((hi["missing"], hi["contained"], hi["unpushed"]), (True, False, 1))

    def test_git_timeout_sets_error_never_raises(self):
        wt = self.fx.worktree("t")
        repo = next(iter(pending.discover_repos(0).values()))
        w = next(w for w in pending.list_worktrees(repo) if w["branch"] == "t")
        with mock.patch.object(pending.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 1)):
            it = pending.inspect_worktree(w, repo, pending.build_ctx())
        self.assertIn("timeout", it["error"])

    def test_last_activity_tracks_admin_files(self):
        wt = self.fx.worktree("la")
        self.fx.age(wt, 10)
        it = self.inspect(wt)
        self.assertGreater(it["last_activity"], 0)
        import time
        self.assertGreaterEqual(time.time() - it["last_activity"], 10 * 86400)


@requires_git
class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)

    def test_dedupes_walks_up_and_skips_non_repos(self):
        wt = self.fx.worktree("w")
        sub = os.path.join(wt, "nope", "deeper")                   # vanished cwd inside a worktree
        notrepo = os.path.join(self.fx.root, "jobs")                # exists, not a repo
        self.fx.cwds.update({wt, sub, notrepo, "/definitely/not/here"})
        repos = pending.discover_repos(0)
        self.assertEqual(len(repos), 1)
        r = next(iter(repos.values()))
        self.assertEqual(os.path.realpath(r["top"]), os.path.realpath(self.fx.repo))
        self.assertEqual(os.path.realpath(r["common"]), os.path.realpath(os.path.join(self.fx.repo, ".git")))

    def test_seeds_from_job_state_and_extra_and_sticky(self):
        self.fx.cwds.clear()
        self.assertEqual(pending.discover_repos(0), {})
        self.fx.job("j1", "done", cwd=self.fx.repo)
        self.assertEqual(len(pending.discover_repos(0)), 1)
        os.remove(os.path.join(self.fx.paths["JOBS_DIR"], "j1", "state.json"))
        self.assertEqual(pending.discover_repos(0), {})
        self.assertEqual(len(pending.discover_repos(0, extra_seeds=[self.fx.repo])), 1)
        prev = {"repos": [{"common": os.path.join(self.fx.repo, ".git"), "top": self.fx.repo}]}
        self.assertEqual(len(pending.discover_repos(0, prev=prev)), 1)            # sticky
        gone = {"repos": [{"common": "/no/such/.git", "top": "/no/such"}]}
        self.assertEqual(pending.discover_repos(0, prev=gone), {})               # dropped: common gone


class PrimitiveTests(unittest.TestCase):
    def test_under_commonpath_not_prefix(self):
        self.assertTrue(pending._under("/a/b/c", "/a/b"))
        self.assertTrue(pending._under("/a/b", "/a/b"))
        self.assertFalse(pending._under("/a/b0/x", "/a/b"))
        self.assertFalse(pending._under("/a", "/a/b"))
        self.assertTrue(pending._under("/a/b/c/d", "/a/b", depth=2))
        self.assertFalse(pending._under("/a/b/c/d", "/a/b", depth=3))
        self.assertFalse(pending._under("/a/b", "/a/b", depth=0))

    def test_under_resolves_symlinks(self):
        import tempfile
        d = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", d])
        os.makedirs(os.path.join(d, "real", "x"))
        os.makedirs(os.path.join(d, "other"))
        os.symlink(os.path.join(d, "real"), os.path.join(d, "root"))
        os.symlink(os.path.join(d, "other"), os.path.join(d, "real", "esc"))
        self.assertTrue(pending._under(os.path.join(d, "root", "x"), os.path.join(d, "root"), depth=1))
        self.assertFalse(pending._under(os.path.join(d, "root", "esc"), os.path.join(d, "root")))

    def test_alive_fails_closed_on_nt(self):
        with mock.patch.object(pending.os, "name", "nt"):
            self.assertTrue(pending._alive(99999999))
        self.assertFalse(pending._alive(None))
        self.assertTrue(pending._alive(os.getpid()))

    def test_lock_busy_when_held(self):
        import tempfile
        from aitracker import config
        d = tempfile.mkdtemp()
        self.addCleanup(subprocess.run, ["rm", "-rf", d])
        with mock.patch.object(config, "PENDING_LOCK", os.path.join(d, "l")):
            with pending._pending_lock() as a:
                self.assertTrue(a)
                with pending._pending_lock() as b:
                    self.assertFalse(b)
            with pending._pending_lock() as c:
                self.assertTrue(c)                              # released

    def test_git_and_gh_fail_closed(self):
        with mock.patch.object(pending.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 1)):
            self.assertEqual(pending._git("/", "status"), (None, ""))
        with mock.patch.object(pending.shutil, "which", return_value=None):
            self.assertEqual(pending._gh("/", "pr"), (None, ""))
        with mock.patch.object(pending.shutil, "which", return_value="/x/gh"), \
                mock.patch.object(pending.subprocess, "run", side_effect=OSError("boom")):
            self.assertEqual(pending._gh("/", "pr"), (None, ""))


if __name__ == "__main__":
    unittest.main()
