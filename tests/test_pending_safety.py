"""G1 fixes (safety/correctness of pending.py): every test builds temp repos/dirs only and was seen RED
before its fix. Covers the deleting code first (assume-unchanged, live scratch, scratch-root trust,
unreadable subtrees, in-progress ops, protected branch names)."""
import json
import os
import subprocess
import threading
import time
import unittest
from unittest import mock

from aitracker import config, pending
from tests.pending_fixture import make_fixture, requires_git


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class _Base(unittest.TestCase):
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

    def merged_worktree(self, name="a", days=8):
        wt = self.fx.worktree(name)
        self.fx.commit(wt, name + ".txt", name)
        self.fx.git(wt, "push", "origin", "%s:main" % name)
        self.fx.git(self.fx.repo, "fetch", "origin")
        self.fx.git(self.fx.repo, "merge", "--ff-only", "origin/main")
        self.fx.age(wt, days)
        return wt

    def scan_clean(self, mode="safe"):
        self.now = time.time()
        self.rep = pending.scan(self.now)
        pending.clean(self.rep, mode, self.now)
        return self.rep

    def item(self, path):
        return next(i for i in self.rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(path))

    def tree(self, path, days=8, files=("f.txt",)):
        for f in files:
            _write(os.path.join(path, f))
        self.fx.age_tree(path, days)
        return path


@requires_git
class DeleteGuardTests(_Base):
    def test_F4_assume_unchanged_edit_survives(self):
        wt = self.merged_worktree()
        self.fx.git(wt, "update-index", "--assume-unchanged", "a.txt")
        _write(os.path.join(wt, "a.txt"), "PRECIOUS LOCAL EDIT")
        self.fx.age(wt, 8)
        rep = self.scan_clean()
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(open(os.path.join(wt, "a.txt")).read(), "PRECIOUS LOCAL EDIT")
        self.assertEqual(rep["deleted"], [])

    def test_F4_skip_worktree_edit_survives(self):
        wt = self.merged_worktree()
        self.fx.git(wt, "update-index", "--skip-worktree", "a.txt")
        _write(os.path.join(wt, "a.txt"), "PRECIOUS LOCAL EDIT")
        self.fx.age(wt, 8)
        rep = self.scan_clean()
        self.assertTrue(os.path.isdir(wt))
        self.assertEqual(rep["deleted"], [])

    def test_F12_operation_in_progress_not_deletable(self):
        wt = self.merged_worktree()
        adm = self.fx.git(wt, "rev-parse", "--absolute-git-dir")
        _write(os.path.join(adm, "BISECT_LOG"), "git bisect start\n")
        self.fx.age(wt, 8)
        rep = self.scan_clean()
        self.assertTrue(os.path.isdir(wt))
        self.assertFalse(self.item(wt)["deletable"])
        self.assertEqual(rep["deleted"], [])

    def test_F16_protected_branch_name_never_deleted(self):
        self.fx.git(self.fx.repo, "checkout", "-b", "other")            # free `main` for a linked worktree
        self.fx.git(self.fx.repo, "push", "origin", "main:develop")
        self.fx.git(self.fx.repo, "fetch", "origin")
        wt = os.path.join(self.fx.root, "mainwt")
        self.fx.git(self.fx.repo, "worktree", "add", wt, "main")
        self.fx.age(wt, 8)
        self.scan_clean()
        self.assertFalse(os.path.exists(wt))                              # the worktree itself is reclaimed
        self.assertNotIn(("branch", "-d", "main"), self.calls)
        self.assertIn("main", self.fx.git(self.fx.repo, "branch", "--format=%(refname:short)").split())


@requires_git
class ScratchGuardTests(_Base):
    def test_F5_live_session_id_keeps_scratch(self):
        t = self.tree(os.path.join(config.SCRATCH_ROOT, "slug", "live-sid"))
        with open(os.path.join(config.LIVE_SESSIONS_DIR, "1.json"), "w") as fh:
            json.dump({"pid": os.getpid(), "sessionId": "live-sid", "cwd": self.fx.repo}, fh)
        ents, _ = pending.scan_tmp(pending.build_ctx(), time.time())
        e = next(e for e in ents if e["path"] == t)
        self.assertEqual((e["verdict"], e["reason"], e["deletable"]), ("keep", "live session", False))
        self.scan_clean()
        self.assertTrue(os.path.isdir(t))

    def test_F6_symlinked_scratch_root_is_not_followed(self):
        real = os.path.join(self.fx.root, "real-scratch")
        t = self.tree(os.path.join(real, "slug", "sid1"))
        link = os.path.join(self.fx.root, "scr-link")
        os.symlink(real, link)
        with mock.patch.object(config, "SCRATCH_ROOT", link):
            ents, _ = pending.scan_tmp(pending.build_ctx(), time.time())
            self.assertEqual([e for e in ents if e["kind"] == "scratch"], [])
            self.scan_clean()
        self.assertTrue(os.path.isfile(os.path.join(t, "f.txt")))

    def test_F6_group_writable_scratch_root_is_skipped_and_private_one_works(self):
        t = self.tree(os.path.join(config.SCRATCH_ROOT, "slug", "sid1"))
        os.chmod(config.SCRATCH_ROOT, 0o775)
        ents, _ = pending.scan_tmp(pending.build_ctx(), time.time())
        self.assertEqual([e for e in ents if e["path"] == t], [])
        os.chmod(config.SCRATCH_ROOT, 0o700)
        ents, _ = pending.scan_tmp(pending.build_ctx(), time.time())
        self.assertEqual([e["verdict"] for e in ents if e["path"] == t], ["stale"])

    def test_F11_unreadable_subdir_keeps_whole_tree(self):
        d = self.fx.job("done1", "done")
        t = self.tree(os.path.join(d, "tmp"), files=("a.txt", os.path.join("sub", "b.txt")))
        sub = os.path.join(t, "sub")
        os.chmod(sub, 0)
        self.addCleanup(os.chmod, sub, 0o700)
        ents, _ = pending.scan_tmp(pending.build_ctx(), time.time())
        e = next(e for e in ents if e["job"] == "done1")
        self.assertEqual((e["verdict"], e["deletable"]), ("keep", False))
        self.assertIn("unreadable", e["reason"])
        self.scan_clean()
        self.assertTrue(os.path.isfile(os.path.join(t, "a.txt")))

    def test_F9_safe_clean_walks_each_tree_a_bounded_number_of_times(self):
        ts = [self.tree(os.path.join(self.fx.job("done%d" % i, "done"), "tmp")) for i in range(3)]
        rep = pending.scan(time.time())
        real = pending._walk_tree
        n = []
        with mock.patch.object(pending, "_walk_tree", lambda r: (n.append(r), real(r))[1]):
            pending.clean(rep, "safe", time.time())
        self.assertEqual(len(rep["deleted"]), 3)
        self.assertLessEqual(len(n), 2 * len(ts), n)


@requires_git
class InspectFixTests(_Base):
    def inspect(self, path, env=None):
        repos = pending.discover_repos(0)
        repo = next(r for r in repos.values() if os.path.realpath(r["top"]) == os.path.realpath(self.fx.repo))
        w = next(w for w in pending.list_worktrees(repo) if os.path.realpath(w["path"]) == os.path.realpath(path))
        with mock.patch.dict(os.environ, env or {}):
            return pending.inspect_worktree(w, repo, pending.build_ctx())

    def test_F2_unborn_head_is_pending_and_unknown_counts_in_card(self):
        r = os.path.join(self.fx.root, "fresh")
        self.fx.git(self.fx.root, "init", "-b", "main", r)
        _write(os.path.join(r, "n.txt"), "new")
        self.fx.cwds.add(r)
        rep = pending.scan(time.time())
        it = next(i for i in rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(r))
        self.assertEqual((it["verdict"], it["deletable"]), ("pending", False))
        self.assertIn("no commits yet", it["reason"])
        card = pending.build_card({"items": [{"verdict": "unknown", "last_activity": time.time()}], "tmp": []})
        self.assertEqual((card["show"], card["count"]), (True, 1))
        self.assertIn("could not be checked", card["summary"])

    def test_F3_children_of_a_parent_folder_cwd_are_discovered(self):
        self.fx.cwds.clear()
        self.fx.cwds.add(self.fx.root)                 # not a repo; `repo` is one level below
        repos = pending.discover_repos(0)
        self.assertEqual([os.path.realpath(r["top"]) for r in repos.values()], [os.path.realpath(self.fx.repo)])
        self.assertEqual(next(iter(repos.values()))["cwds"], [])          # cwds stays honest

    def test_F3_symlinked_child_is_not_followed(self):
        self.fx.cwds.clear()
        parent = os.path.join(self.fx.root, "parent")
        os.makedirs(parent)
        os.symlink(self.fx.repo, os.path.join(parent, "lnk"))
        self.fx.cwds.add(parent)
        self.assertEqual(pending.discover_repos(0), {})

    def test_F7_relative_gitdir_keeps_idle_grace(self):
        wt = os.path.join(self.fx.root, "relwt")
        p = subprocess.run(["git", "-C", self.fx.repo, "worktree", "add", "--relative-paths", "-b", "rel", wt, "origin/main"],
                           capture_output=True)
        if p.returncode:
            self.skipTest("git without worktree --relative-paths")
        adm = self.fx.git(wt, "rev-parse", "--absolute-git-dir")
        old = time.time() - 30 * 86400
        for f in ("index", os.path.join("logs", "HEAD")):
            if os.path.exists(os.path.join(adm, f)):
                os.utime(os.path.join(adm, f), (old, old))
        os.utime(wt, (old, old))
        os.utime(os.path.join(adm, "HEAD"), None)                           # committed to just now
        cwd = os.getcwd()
        os.chdir(self.fx.root)
        self.addCleanup(os.chdir, cwd)
        it = self.inspect(wt)
        self.assertLess(time.time() - it["last_activity"], 60)

    def test_F15_git_env_does_not_redirect_scan_git_calls(self):
        wt = self.fx.worktree("envwt")
        it = self.inspect(wt, {"GIT_DIR": self.fx.remote, "GIT_INDEX_FILE": os.path.join(self.fx.root, "nope")})
        self.assertEqual((it["error"], it["dirty"]), (None, 0))


@requires_git
class PruneAndPromptTests(_Base):
    def test_F20_prune_skipped_when_volume_missing(self):
        sha = self.fx.git(self.fx.repo, "rev-parse", "HEAD")
        ghost = {"path": "/Volumes/NoSuchVolume-pending-test/wt", "head": sha, "branch": "x", "detached": False,
                 "bare": False, "locked": False, "prunable": True, "primary": False}
        rep = {"deleted": [], "would_delete": [], "refused": []}
        with mock.patch.object(pending, "list_worktrees", lambda repo: [ghost]):
            pending._prune_repo(os.path.join(self.fx.repo, ".git"), self.fx.repo, rep, True)
        self.assertNotIn(("worktree", "prune"), self.calls)
        self.assertEqual(rep["deleted"], [])
        self.assertIn("prune skipped", rep["refused"][0]["reason"])

    def test_resume_prompt_is_one_line_without_control_chars(self):
        it = {"path": "/tmp/a\nb\tc\x1b[0m d", "top": "/tmp/r\r\nx", "branch": "br\x00", "dirty": 1,
              "unpushed": 2, "gh": {"state": "merged", "pr": "https://x/\n1"}, "kind": "worktree"}
        scratch = {"kind": "scratch", "path": "/tmp/s\nq", "session": "s\x07id"}
        for item in (it, scratch):
            p = pending.resume_prompt(item)
            self.assertEqual(p.splitlines(), [p])
            self.assertFalse([c for c in p if ord(c) < 32 or 0x7f <= ord(c) <= 0x9f or c in "  "], repr(p))
        self.assertNotIn("any session that used it", pending.resume_prompt(it))


@requires_git
class DetailAndReportTests(_Base):
    def reported(self, wt):
        pending.run_once("dry-run")
        return next(i for i in pending.load_report()["items"] if os.path.realpath(i["path"]) == os.path.realpath(wt))

    def test_E2F5_staged_change_shows_in_detail(self):
        wt = self.fx.worktree("stg")
        _write(os.path.join(wt, "a.txt"), "STAGED_MARK\n")
        self.fx.git(wt, "add", "a.txt")
        d = pending.item_detail(self.reported(wt)["id"])
        self.assertIn("STAGED_MARK", d["md"])

    def test_FF5_huge_single_line_diff_is_byte_bounded(self):
        wt = self.fx.worktree("big")
        _write(os.path.join(wt, "a.txt"), "y" * (5 * 1024 * 1024))
        it = self.reported(wt)
        t0 = time.monotonic()
        d = pending.item_detail(it["id"])
        self.assertLess(time.monotonic() - t0, 3)
        self.assertLess(len(d["md"]), 300_000)

    def test_FF5_external_diff_tool_is_not_run(self):
        wt = self.fx.worktree("ext")
        script = os.path.join(self.fx.root, "slow-diff.sh")
        _write(script, "#!/bin/sh\nsleep 12\n")
        os.chmod(script, 0o755)
        self.fx.git(self.fx.repo, "config", "diff.external", script)
        _write(os.path.join(wt, "a.txt"), "EXT_MARK\n")
        it = self.reported(wt)
        t0 = time.monotonic()
        d = pending.item_detail(it["id"])
        self.assertLess(time.monotonic() - t0, 3)
        self.assertIn("EXT_MARK", d["md"])

    def test_S3_report_lists_hot_items_first(self):
        mk = lambda n, v, la: {"id": n, "path": "/x/" + n, "verdict": v, "last_activity": la}
        pending._save_json(config.PENDING_FILE, {"items": [mk("c1", "clean", 5), mk("p1", "pending", 1), mk("c2", "clean", 9),
                                                           mk("m1", "missing", 3), mk("p2", "pending", 8)],
                                                 "tmp": [{"id": "k", "verdict": "keep"}, {"id": "s", "verdict": "stale"}]})
        r = pending.load_report()
        self.assertEqual([i["id"] for i in r["items"]], ["p2", "p1", "m1", "c2", "c1"])
        self.assertEqual([t["id"] for t in r["tmp"]], ["s", "k"])

    def test_S4_accepted_run_async_is_running_before_the_thread_takes_the_lock(self):
        gate = threading.Event()
        with mock.patch.object(pending, "run_once", lambda mode: gate.wait(5)):
            self.assertTrue(pending.run_async("dry-run"))
            try:
                self.assertTrue(pending._RUNNING.is_set())
                with mock.patch.object(pending, "_pending_lock", side_effect=AssertionError("probed the lock")):
                    self.assertTrue(pending.load_report()["running"])
                self.assertFalse(pending.run_async("dry-run"))
            finally:
                gate.set()
                for t in threading.enumerate():
                    if t.name == "pending-scan":
                        t.join(5)
        self.assertFalse(pending._RUNNING.is_set())


if __name__ == "__main__":
    unittest.main()
