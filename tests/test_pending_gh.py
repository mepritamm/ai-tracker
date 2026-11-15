"""Step 8: the gh squash-merge check (fixtures N1-N8) against a FAKE gh on a temp PATH. Never the real gh."""
import json
import os
import time
import unittest
from unittest import mock

from aitracker import pending
from tests.pending_fixture import make_fixture, requires_git


def pr(sha, n=12, base="main"):
    return {"number": n, "url": "https://github.com/o/r/pull/%d" % n, "headRefOid": sha,
            "baseRefName": base, "mergedAt": "2026-11-01T00:00:00Z"}


@requires_git
class GhTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)

    def branch(self, name, days=8, commit=True):
        """C-shaped: commits only local (squash-merged upstream, remote branch gone)."""
        wt = self.fx.worktree(name)
        sha = self.fx.commit(wt, name + ".txt", name) if commit else self.fx.git(wt, "rev-parse", "HEAD")
        self.fx.age(wt, days)
        return wt, sha

    def scan(self):
        rep = pending.scan(time.time())
        self.rep = rep
        return rep

    def item(self, wt):
        return next(i for i in self.rep["items"] if os.path.realpath(i["path"]) == os.path.realpath(wt))

    def test_N1_squash_merged_is_clean_and_reclaimable(self):
        wt, sha = self.branch("n1")
        self.fx.fake_gh({"n1": [pr(sha, 12, "develop")]})
        it = self.item(wt) if self.scan() else None
        self.assertEqual((it["gh"]["state"], it["verdict"], it["deletable"]), ("merged", "clean", True))
        self.assertEqual(it["reason"], "squash-merged into develop (PR #12)")
        self.assertTrue(pending.reclaimable(it, time.time()))
        argv = self.fx.gh_calls()[0]["argv"]
        self.assertEqual(argv[:5], ["pr", "list", "--head", "n1", "--state"])
        self.assertIn("merged", argv)
        self.assertIn("number,url,headRefOid,baseRefName,mergedAt", argv)
        json.dumps(self.rep)                                          # report stays JSON-safe

    def test_N2_commit_after_merge_is_pending(self):
        wt, sha = self.branch("n2")
        self.fx.fake_gh({"n2": [pr(sha)]})
        self.fx.commit(wt, "late.txt", "late")                        # HEAD moves past the merged tip
        self.fx.age(wt, 8)
        it = self.item(wt) if self.scan() else None
        self.assertEqual((it["gh"]["state"], it["verdict"], it["deletable"]), ("none", "pending", False))

    def test_N3_merged_alone_never_deletes(self):
        wt, sha = self.branch("n3")
        self.fx.fake_gh({"n3": [pr(sha)]})
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("dirty")
        it = self.item(wt) if self.scan() else None
        self.assertEqual((it["gh"]["state"], it["verdict"], it["deletable"]), ("skipped", "pending", False))
        self.assertEqual(self.fx.gh_calls(), [])                       # dirty -> not even a candidate
        self.assertFalse(pending.reclaimable(it, time.time()))
        # also with a finished-looking tree but a live session: merged still not reclaimable
        os.system("cd '%s' && git checkout -q -- a.txt" % wt)
        self.fx.live(os.getpid(), wt)
        it = self.item(wt) if self.scan() else None
        self.assertEqual(it["gh"]["state"], "skipped")
        self.assertFalse(pending.reclaimable(it, time.time()))

    def test_N3_merged_plus_each_guard_not_reclaimable(self):
        """A real gh-merged item is reclaimable; flipping any ONE guard on it makes it not (each guard
        proven on its own, with gh.state == "merged" actually set)."""
        wt, sha = self.branch("n3b")
        self.fx.fake_gh({"n3b": [pr(sha)]})
        it = self.item(wt) if self.scan() else None
        self.assertEqual(it["gh"]["state"], "merged")
        now = time.time()
        self.assertTrue(pending.reclaimable(it, now))
        for key, val in (("deletable", False), ("verdict", "pending"), ("busy_job", True), ("live", True),
                         ("last_activity", now)):
            with self.subTest(guard=key):
                self.assertFalse(pending.reclaimable(dict(it, **{key: val}), now))
        # and the merged answer must be for the exact head: a different state is not enough
        self.assertFalse(pending.reclaimable(dict(it, gh={"state": "none"}, ancestor=False), now))

    def test_N4_gh_missing_is_unavailable_zero_calls(self):
        wt, sha = self.branch("n4")
        real = pending.shutil.which
        with mock.patch.object(pending.shutil, "which", lambda n, *a, **k: None if n == "gh" else real(n, *a, **k)):
            it = self.item(wt) if self.scan() else None
        self.assertEqual((it["gh"]["state"], it["verdict"], it["deletable"]), ("unavailable", "pending", False))
        self.assertEqual(self.fx.gh_calls(), [])

    def _breaker(self, code):
        a, _ = self.branch("n5a")
        b, _ = self.branch("n5b")
        self.fx.fake_gh({"__exit__": code})
        self.scan()
        states = sorted((self.item(a)["gh"]["state"], self.item(b)["gh"]["state"]))
        self.assertEqual(states, ["error", "skipped"])
        self.assertEqual(len(self.fx.gh_calls()), 1)                   # breaker on ANY error
        for w in (a, b):
            self.assertEqual((self.item(w)["verdict"], self.item(w)["deletable"]), ("pending", False))
        self.assertEqual(self.rep["gh_cache"], {})                     # errors are never cached

    def test_N5_breaker_auth_exit_4(self):
        self._breaker(4)

    def test_N5_breaker_offline_exit_1(self):
        self._breaker(1)

    def test_N5_unparseable_json_trips_breaker(self):
        wt, _ = self.branch("n5j")
        with open(os.path.join(self.fx.root, "bin", "gh"), "a") as fh:
            fh.write("print('not json')\n")
        it = self.item(wt) if self.scan() else None
        self.assertEqual(it["gh"]["state"], "error")

    def test_N6_timeout_is_error(self):
        wt, _ = self.branch("n6")
        self.fx.fake_gh({"__sleep__": 5})
        with mock.patch.object(pending, "GH_TIMEOUT", 1):
            it = self.item(wt) if self.scan() else None
        self.assertEqual((it["gh"]["state"], it["deletable"]), ("error", False))
        self.assertEqual(len(self.fx.gh_calls()), 1)

    def test_N7_cap_and_cache(self):
        wts = [self.branch("n7_%02d" % i, days=8 + i) for i in range(25)]
        self.fx.fake_gh({n: [pr(s)] for n, s in (("n7_%02d" % i, w[1]) for i, w in enumerate(wts))})
        with mock.patch.object(pending, "GH_MAX_CALLS", 20):
            self.scan()
        self.assertEqual(len(self.fx.gh_calls()), 20)
        st = [self.item(w)["gh"]["state"] for w, _ in wts]
        self.assertEqual((st.count("merged"), st.count("skipped")), (20, 5))
        self.assertEqual(self.item(wts[-1][0])["gh"]["state"], "merged")        # oldest (aged most) asked first
        self.assertEqual(self.item(wts[0][0])["gh"]["state"], "skipped")
        json.loads(json.dumps(self.rep))                                          # string cache key round-trips
        self.assertTrue(all(isinstance(k, str) for k in self.rep["gh_cache"]))
        from aitracker import config
        with open(config.PENDING_FILE, "w") as fh:
            json.dump(self.rep, fh)
        with mock.patch.object(pending, "GH_MAX_CALLS", 20):
            self.scan()
        self.assertEqual(len(self.fx.gh_calls()), 25)                             # only the 5 uncached asked again
        with open(config.PENDING_FILE, "w") as fh:
            json.dump(self.rep, fh)
        self.scan()
        self.assertEqual(len(self.fx.gh_calls()), 25)                             # nothing left to ask (merged cached)

    def test_none_cached_for_ttl_then_reasked(self):
        wt, _ = self.branch("n7n")
        self.fx.fake_gh({})
        rep = self.scan()
        self.assertEqual(len(self.fx.gh_calls()), 1)
        cache = rep["gh_cache"]
        items = rep["items"]
        pending.gh_merged(items, cache, time.time() + 3600)
        self.assertEqual(len(self.fx.gh_calls()), 1)                               # within 24h: cached none
        pending.gh_merged(items, cache, time.time() + 2 * 86400 + 1)
        self.assertEqual(len(self.fx.gh_calls()), 2)                               # after TTL: asked again

    def test_cache_pruned_for_dropped_repos(self):
        wt, sha = self.branch("n7p")
        cache = {"\x00".join(("/gone/.git", "b", "sha")): {"state": "merged", "checked_at": 1}}
        rep = self.scan()
        pending.gh_merged(rep["items"], cache, time.time())
        self.assertNotIn("\x00".join(("/gone/.git", "b", "sha")), cache)

    def test_N8_gh_repo_and_host_stripped(self):
        wt, _ = self.branch("n8")
        with mock.patch.dict(os.environ, {"GH_REPO": "x/y", "GH_HOST": "h"}):
            self.scan()
        env = self.fx.gh_calls()[0]["env"]
        self.assertNotIn("GH_REPO", env)
        self.assertNotIn("GH_HOST", env)
        self.assertIn("GH_PROMPT_DISABLED", env)
        self.assertIn("NO_COLOR", env)

    def test_non_candidates_are_skipped_not_asked(self):
        a = self.fx.worktree("fresh")                                  # idle < grace
        self.fx.commit(a, "f.txt", "f")
        self.fx.fake_gh({})
        it = self.item(a) if self.scan() else None
        self.assertEqual(it["gh"]["state"], "skipped")
        self.assertEqual(self.fx.gh_calls(), [])
        prim = self.item(self.fx.repo)
        self.assertEqual(prim["gh"]["state"], "skipped")


if __name__ == "__main__":
    unittest.main()
