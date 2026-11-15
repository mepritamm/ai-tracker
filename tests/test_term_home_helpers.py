"""L2a of terminal-at-root: util.git_worktree_root / deleted_worktree_root and term_gate.place."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from aitracker import term_gate, util


def _w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "repo")

    def admin(self, name, top):
        """Fabricate <root>/.git/worktrees/<name> registered for `top`; returns its admin dir."""
        g = os.path.join(self.root, ".git", "worktrees", name)
        _w(os.path.join(g, "commondir"), "../..\n")
        _w(os.path.join(g, "gitdir"), os.path.join(top, ".git") + "\n")
        return g

    def linked(self, name, rel=False):
        top = os.path.join(self.root, ".claude", "worktrees", name)
        g = self.admin(name, top)
        os.makedirs(os.path.join(top, "sub"), exist_ok=True)
        ref = os.path.relpath(g, top) if rel else g
        _w(os.path.join(top, ".git"), "gitdir: " + ref + "\n")
        return top


class TestGitWorktreeRoot(_Base):
    def test_linked_and_subdir(self):
        top = self.linked("a")
        self.assertEqual(util.git_worktree_root(top), (self.root, top))
        self.assertEqual(util.git_worktree_root(os.path.join(top, "sub")), (self.root, top))

    def test_relative_gitdir(self):
        top = self.linked("a", rel=True)
        self.assertEqual(util.git_worktree_root(top), (self.root, top))

    def test_symlinked_tmp_root(self):
        top = self.linked("a")
        link = os.path.join(self.tmp, "link")
        os.symlink(self.root, link)
        self.assertEqual(util.git_worktree_root(os.path.join(link, ".claude", "worktrees", "a")),
                         (self.root, top))

    def test_guards(self):
        os.makedirs(os.path.join(self.root, ".git", "sub"))
        os.makedirs(os.path.join(self.root, "pkg"))
        self.assertEqual(util.git_worktree_root(self.root), ("", ""))
        self.assertEqual(util.git_worktree_root(os.path.join(self.root, "pkg")), ("", ""))
        mod = os.path.join(self.tmp, "super", "mod")       # submodule: .git file, modules/ gitdir, no commondir
        modgit = os.path.join(self.tmp, "super", ".git", "modules", "mod")
        os.makedirs(modgit)
        _w(os.path.join(mod, ".git"), "gitdir: " + modgit + "\n")
        self.assertEqual(util.git_worktree_root(mod), ("", ""))
        bare = os.path.join(self.tmp, "bare.git")
        os.makedirs(os.path.join(bare, "refs"))
        self.assertEqual(util.git_worktree_root(bare), ("", ""))

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_real_git_cross_check(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(k, None)

        def git(*a):
            subprocess.run(("git", "-C", self.root) + a, check=True, capture_output=True, env=env)
        os.makedirs(self.root)
        git("init", "-q")
        git("commit", "-q", "--allow-empty", "-m", "x")
        wt = os.path.join(self.root, ".claude", "worktrees", "w")
        git("worktree", "add", "-q", "-b", "wb", wt)
        self.assertEqual(util.git_worktree_root(wt), (self.root, wt))
        self.assertEqual(util.git_worktree_root(self.root), ("", ""))
        shutil.rmtree(wt)                                   # hand rm -rf: the admin entry survives
        self.assertEqual(util.deleted_worktree_root(wt), self.root)


class TestDeletedWorktreeRoot(_Base):
    def test_admin_entry_names_raw_or_ancestor(self):
        gone = os.path.join(self.root, "wts", "gone")
        os.makedirs(os.path.join(self.root, "wts"))
        self.admin("gone", gone)
        self.assertEqual(util.deleted_worktree_root(gone), self.root)
        self.assertEqual(util.deleted_worktree_root(os.path.join(gone, "deep", "er")), self.root)

    def test_admin_entry_found_by_content_not_basename(self):
        gone = os.path.join(self.root, "wts", "api")
        os.makedirs(os.path.join(self.root, "wts"))
        self.admin("api1", gone)                            # git-suffixed admin name
        self.assertEqual(util.deleted_worktree_root(gone), self.root)
        self.assertEqual(util._admin_dir_for(self.root, gone),
                         os.path.join(self.root, ".git", "worktrees", "api1"))
        self.assertEqual(util._admin_dir_for(self.root, os.path.join(self.root, "wts", "other")), "")

    def test_marker_claude_worktrees(self):
        os.makedirs(os.path.join(self.root, ".git"))
        os.makedirs(os.path.join(self.root, ".claude", "worktrees"))
        self.assertEqual(util.deleted_worktree_root(os.path.join(self.root, ".claude", "worktrees", "x")), self.root)

    def test_symlinked_root(self):
        os.makedirs(os.path.join(self.root, ".git"))
        os.makedirs(os.path.join(self.root, ".claude", "worktrees"))
        link = os.path.join(self.tmp, "link")
        os.symlink(self.root, link)
        self.assertEqual(util.deleted_worktree_root(os.path.join(link, ".claude", "worktrees", "x")), self.root)

    def test_guards(self):
        os.makedirs(os.path.join(self.root, ".git"))
        os.makedirs(os.path.join(self.root, "pkg"))
        self.assertEqual(util.deleted_worktree_root(os.path.join(self.root, "pkg", "gone")), "")
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertEqual(util.deleted_worktree_root(os.path.join(plain, "gone")), "")
        self.assertEqual(util.deleted_worktree_root(plain), "")       # exists -> not deleted
        self.assertEqual(util.deleted_worktree_root(""), "")


class TestPlace(_Base):
    def _raw(self, raw):
        return mock.patch("aitracker.registry.term_home", return_value=(raw, ""))

    def test_live_worktree(self):
        top = self.linked("a")
        with self._raw(os.path.join(top, "sub")):
            pl = term_gate.place("s", top, "resume")
            self.assertEqual((pl["shell"], pl["run"]), (self.root, top))
            self.assertEqual(term_gate.place("s", top, "new")["run"], top)
            self.assertIsNone(term_gate.place("s", top, "cwd")["run"])

    def test_order_deleted_wt_ancestor_inside_repo(self):
        os.makedirs(os.path.join(self.root, ".git"))
        anc = os.path.join(self.root, ".claude", "worktrees")
        os.makedirs(anc)
        gone = os.path.join(anc, "gone")
        for mode in ("resume", "new", "cwd"):
            with self._raw(gone):
                pl = term_gate.place("s", anc, mode)       # cwd = what session_cwd(resume=True) returned
            self.assertEqual(pl["shell"], "")              # never row 4 (shell = the ancestor)
            self.assertEqual(pl["recreate"], {"path": gone, "root": self.root})
            self.assertIn("was removed", pl["error"])
            self.assertEqual(pl["note"], pl["error"])

    def test_repo_gone_has_no_recreate(self):
        gone = os.path.join(self.root, ".claude", "worktrees", "g")
        with self._raw(gone), mock.patch.object(term_gate, "terminal_dir", return_value=("deleted", self.root, "")):
            pl = term_gate.place("s", "", "resume")
        self.assertNotIn("recreate", pl)
        self.assertIn("no longer exists", pl["error"])

    def test_plain_and_main_checkout_unchanged(self):
        os.makedirs(os.path.join(self.root, ".git"))
        with self._raw(self.root):
            pl = term_gate.place("s", self.root, "resume")
        self.assertEqual((pl["shell"], pl["run"], pl["error"]), (self.root, self.root, ""))
        with self._raw(os.path.join(self.tmp, "gone")):
            pl = term_gate.place("s", "/x", "resume")
        self.assertEqual((pl["shell"], pl["run"]), ("/x", "/x"))

    def test_auggie_and_fake_sid_use_cwd(self):
        top = self.linked("a")
        pl = term_gate.place("auggie:zzz", top, "new")      # provider has no term_home -> raw = cwd
        self.assertEqual((pl["shell"], pl["run"]), (self.root, top))
        pl = term_gate.place("no-such-sid", self.tmp, "resume")
        self.assertEqual((pl["shell"], pl["run"]), (self.tmp, self.tmp))
        self.assertEqual(term_gate.place("no-such-sid", "", "resume")["shell"], "")

    def test_home_note(self):
        os.makedirs(os.path.join(self.root, ".git"))
        gone = os.path.join(self.root, ".claude", "worktrees", "g")
        os.makedirs(os.path.dirname(gone))
        with self._raw(gone):
            self.assertIn(gone, term_gate.home_note("s", ""))
        with self._raw(self.root):
            self.assertEqual(term_gate.home_note("s", self.root), "")

    def test_meta_never_reenters_parse_any(self):
        with mock.patch("aitracker.registry.parse_any", side_effect=AssertionError):
            pl = term_gate.place("s", self.tmp, "resume", meta={"cwd": self.tmp})
        self.assertEqual(pl["shell"], self.tmp)


if __name__ == "__main__":
    unittest.main()
