"""item_detail runs its four read-only git calls concurrently (M8) without changing the output."""
import json
import os
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
    def _detail(self, capped, base=None):
        with tempfile.TemporaryDirectory() as d:
            report = {"generated_at": 1, "items": [{"id": "x1", "path": d, "branch": "b", "verdict": "keep", "kind": "worktree",
                                                    "base": base}],
                      "tmp": []}
            with mock.patch.object(pending, "_read_report", return_value=report), \
                    mock.patch.object(pending, "session_evidence", return_value=[]), \
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

    def test_base_adds_fifth_section_after_the_four(self):
        slow, dt, _ = self._detail(_stub_capped(0.3), base="origin/main")
        self.assertLess(dt, 0.6)
        md = slow["md"]
        heads = ("**git status --short**", "**git diff HEAD --stat**", "**git diff HEAD**", "**git log --oneline HEAD --not --remotes**",
                 "**git log --oneline HEAD --not origin/main**")
        pos = [md.index(h) for h in heads]
        self.assertEqual(pos, sorted(pos))
        self.assertNotIn("--not origin/main", self._detail(_stub_capped(0), base="-x")[0]["md"])

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


def _save(fx, mutate=None):
    from aitracker import config
    from aitracker.store import _save_json
    report = pending.scan()
    if mutate:
        mutate(report)
    _save_json(config.PENDING_FILE, report)
    pending._REPORT_MEMO.clear()
    return {i["path"]: i for i in report["items"]}


def _write_tx(fx, sid, cwd, text="hi", last=None, name="proj"):
    d = os.path.join(fx.paths["PROJECTS"], name)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, sid + ".jsonl")
    recs = [{"type": "user", "cwd": cwd, "message": {"role": "user", "content": text}}]
    if last:
        recs.append({"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "model": "claude-sonnet-4-5",
                                                                  "content": [{"type": "text", "text": last}]}})
    with open(fp, "w") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in recs))
        fh.write(json.dumps({"type": "worktree-state", "worktreeSession": {"worktreePath": cwd}}) + "\n")
    return fp


@requires_git
class ItemDetailSessionResume(unittest.TestCase):
    def _wt(self, fx):
        wt = fx.worktree("feat")
        fx.commit(wt, "b.txt", "local")
        with open(wt + "/a.txt", "a") as fh:
            fh.write("more")
        return wt

    def test_created_session_becomes_resume_target_with_git_state_only(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt, text="SENTINEL-GOAL-PUSH do it", last="LAST-SAID-XYZ")
        items = _save(fx)
        out = pending.item_detail(items[wt]["id"])
        self.assertEqual(out["resume"]["session"], "S1")
        pr = out["resume"]["prompt"]
        self.assertNotRegex(pr, r"[\x00-\x1f]")
        self.assertLessEqual(len(pr), pending.PROMPT_MAX)
        self.assertIn("1 uncommitted", pr)
        self.assertIn("not merged into", pr)
        self.assertNotIn("SENTINEL-GOAL-PUSH", pr)
        self.assertNotIn("LAST-SAID-XYZ", pr)
        self.assertIn("LAST-SAID-XYZ", out["md"])
        self.assertIn("Resume target", out["md"])
        self.assertEqual([x["id"] for x in out["sessions"]], ["S1"])

    def test_newer_session_after_scan_is_the_target(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        f1 = _write_tx(fx, "S1", wt)
        items = _save(fx)
        f2 = _write_tx(fx, "S2", wt, name="proj2")
        t = time.time() + 1000
        os.utime(f2, (t, t))
        out = pending.item_detail(items[wt]["id"])
        self.assertEqual(out["resume"]["session"], "S2")
        self.assertEqual({x["id"] for x in out["sessions"]}, {"S1", "S2"})

    def test_live_counts_beat_scan_time_counts(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt)
        items = _save(fx)
        fx.git(wt, "push", "origin", "feat")
        pr = pending.item_detail(items[wt]["id"])["resume"]["prompt"]
        self.assertIn("0 commits on no remote", pr)
        self.assertIn("1 commits not merged", pr)

    def test_backtick_in_branch_is_stripped(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt)
        items = _save(fx, lambda r: [i.update(branch="a`b") for i in r["items"] if i["kind"] == "worktree"])
        pr = pending.item_detail(items[wt]["id"])["resume"]["prompt"]
        self.assertIn("`a'b`", pr)
        self.assertNotIn("a`b", pr)

    def test_no_session_keeps_the_old_prompt(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        items = _save(fx)
        out = pending.item_detail(items[wt]["id"])
        self.assertEqual(out["resume"]["session"], "")
        self.assertEqual(out["resume"]["prompt"], pending.resume_prompt(items[wt]))
        self.assertEqual(out["sessions"], [])
        self.assertIn("No Claude session", out["md"])

    def test_repo_item_never_gets_a_session(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", fx.repo)
        items = _save(fx)
        out = pending.item_detail(items[fx.repo]["id"])
        self.assertEqual(out["resume"]["session"], "")
        self.assertEqual(out["resume"]["prompt"], pending.resume_prompt(items[fx.repo]))
        self.assertNotIn("--not origin/main**", out["md"])

    def test_deleted_transcript_falls_back_to_old_flow(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        fp = _write_tx(fx, "S1", wt)
        items = _save(fx)
        os.remove(fp)
        out = pending.item_detail(items[wt]["id"])
        self.assertEqual(out["sessions"], [])
        self.assertEqual(out["resume"]["session"], "")
        self.assertEqual(out["resume"]["prompt"], pending.resume_prompt(items[wt]))

    def test_squash_merged_prompt_names_pr(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt)
        items = _save(fx, lambda r: [i.update(gh={"state": "merged", "pr": "https://x/pull/42", "number": 42, "base": "main"})
                                     for i in r["items"] if i["kind"] == "worktree"])
        pr = pending.item_detail(items[wt]["id"])["resume"]["prompt"]
        self.assertIn("PR #42 into `main`", pr)

    def test_stamp_is_now_when_counts_are_live(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt)
        items = _save(fx, lambda r: r.update(generated_at=86400 * 400))
        pr = pending.item_detail(items[wt]["id"])["resume"]["prompt"]
        self.assertNotIn("1971", pr)
        self.assertIn(time.strftime("%Y-%m-%d"), pr)

    def test_truncated_log_output_falls_back_to_scan_count(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        for i in range(30):
            fx.commit(wt, "f%d.txt" % i, "x")
        _write_tx(fx, "S1", wt)
        items = _save(fx)
        with mock.patch.object(pending, "ITEM_GIT_BYTES", 200):
            pr = pending.item_detail(items[wt]["id"])["resume"]["prompt"]
        self.assertIn("%d commits on no remote" % items[wt]["unpushed"], pr)

    def test_base_that_is_also_a_path_does_not_fail_the_log(self):
        fx = make_fixture(self)
        wt = self._wt(fx)
        _write_tx(fx, "S1", wt)
        items = _save(fx)
        base = items[wt]["base"]
        os.makedirs(os.path.join(wt, base), exist_ok=True)
        open(os.path.join(wt, base, "f"), "w").close()
        self.assertNotIn("(git failed)", pending.item_detail(items[wt]["id"])["md"])

    def test_path_hint_is_shell_quoted_and_backtick_free(self):
        it = {"kind": "worktree", "path": "/tmp/a b`c", "top": "/tmp", "branch": "x", "base": "origin/main"}
        pr = pending.resume_work_prompt(it, {"role": "last worked here"}, {}, "now")
        self.assertIn("git -C '/tmp/a b'\"'\"'c' status", pr)
        self.assertNotIn("b`c", pr)

    def test_missing_worktree_wording_allows_recreate(self):
        it = {"kind": "worktree", "path": "/tmp/gone", "top": "/tmp", "branch": "x", "base": "origin/main", "missing": True}
        pr = pending.resume_work_prompt(it, {"role": "last worked here"}, {}, "T0")
        self.assertIn("was missing at T0", pr)
        self.assertIn("may have recreated it", pr)

    def test_safe_ref(self):
        for bad in ("-x", "a..b", "", None, "a b"):
            self.assertFalse(pending._safe_ref(bad), bad)
        self.assertTrue(pending._safe_ref("origin/main"))


if __name__ == "__main__":
    unittest.main()
