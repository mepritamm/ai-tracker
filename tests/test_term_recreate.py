"""L2d of terminal-at-root: recreate a removed worktree on a one-click confirm (plan v4.2 A2).

Every git test runs against a REAL throwaway repo under the test's own tmp dir (never the user's
repos); skipped without `git`. Run: unset TRACKER_AUTH first."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, registry, term_gate, term_launch, term_vt, util

SID = "aaaaaaaa-0000-0000-0000-000000000001"
SID2 = "bbbbbbbb-0000-0000-0000-000000000002"
_HAS_GIT = shutil.which("git") is not None


def git(cwd, *a):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    r = subprocess.run(["git", "-C", cwd, "-c", "commit.gpgsign=false", *a], capture_output=True, text=True, env=env)
    if r.returncode:
        raise AssertionError("git %s: %s" % (a, r.stderr))
    return r.stdout.strip()


def commit(cwd, name):
    with open(os.path.join(cwd, name), "w") as fh:
        fh.write(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-m", name)
    return git(cwd, "rev-parse", "HEAD")


@unittest.skipUnless(_HAS_GIT, "git not available")
class _Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "repo")
        os.makedirs(self.root)
        git(self.root, "init", "-b", "main")
        self.main_sha = commit(self.root, "base")
        self.proj = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(self.proj, "p"))
        p = mock.patch.object(config, "PROJECTS", self.proj)
        p.start()
        self.addCleanup(p.stop)
        self.wt = os.path.join(self.root, ".claude", "worktrees", "w")
        git(self.root, "worktree", "add", "-b", "feat", self.wt)
        self.feat_sha = commit(self.wt, "f1")
        self.transcript(SID, self.wt, "feat")
        self.calls = []
        real = term_gate._git

        def spy(root, *a):
            self.calls.append(a)
            return real(root, *a)
        self.real_git = real
        p = mock.patch.object(term_gate, "_git", side_effect=spy)
        p.start()
        self.addCleanup(p.stop)

    def transcript(self, sid, cwd, branch):
        with open(os.path.join(self.proj, "p", sid + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"cwd": cwd, "gitBranch": branch}) + "\n")

    def hand_delete(self, path=None):
        shutil.rmtree(path or self.wt)

    def normal_remove(self, path=None):
        git(self.root, "worktree", "remove", "--force", path or self.wt)

    def plan(self, sid=SID, raw=None):
        return term_gate.recreate_plan(sid, raw or self.wt, self.root)

    def place(self, token=None, sid=SID, mode="resume"):
        cwd = term_gate.session_cwd(sid, resume=True)
        return term_gate.place(sid, cwd, mode, token=token) if token else term_gate.place(sid, cwd, mode)

    def branches(self):
        return git(self.root, "for-each-ref", "--format=%(refname)", "refs/heads").split()

    def wlist(self):
        return git(self.root, "worktree", "list", "--porcelain")

    def writes(self):
        return [c for c in self.calls if c[:2] in (("worktree", "add"), ("worktree", "prune"))]


class TestPlan(_Repo):
    def test_plan_existing_branch_same_path(self):
        self.normal_remove()
        pl = self.plan()
        self.assertEqual((pl["base_kind"], pl["branch"], pl["new_branch"]), ("branch", "feat", ""))
        ok, path = term_gate.recreate_worktree(pl)
        self.assertEqual((ok, path), (True, self.wt))
        self.assertEqual(util._git_branch(self.wt), "feat")

    def test_rmrf_worktree_recreates_on_b_not_cont(self):
        # E1: git still lists the dead entry as using `feat`; it must not force a -cont- branch.
        self.hand_delete()
        self.assertIn("feat", self.wlist())
        pl = self.plan()
        self.assertEqual((pl["base_kind"], pl["new_branch"]), ("branch", ""))
        self.assertTrue(pl["prune"])
        self.assertTrue(term_gate.recreate_worktree(pl)[0])
        self.assertEqual(util._git_branch(self.wt), "feat")
        self.assertEqual([b for b in self.branches() if "cont" in b], [])

    def test_plan_branch_deleted_uses_reflog_tip(self):
        self.hand_delete()
        git(self.root, "update-ref", "-d", "refs/heads/feat")
        pl = self.plan()
        self.assertEqual(pl["base_kind"], "last-commit")
        self.assertEqual(pl["base"], self.feat_sha)
        self.assertEqual(pl["new_branch"], "feat-cont-aaaaaaaa")

    def test_plan_normal_removal_uses_default_branch_not_checkout_head(self):
        self.normal_remove()
        git(self.root, "update-ref", "-d", "refs/heads/feat")
        git(self.root, "checkout", "-b", "unrelated")
        other = commit(self.root, "u1")
        pl = self.plan()
        self.assertEqual(pl["base_kind"], "default-branch")
        self.assertEqual(pl["base"], self.main_sha)
        self.assertNotEqual(pl["base"], other)
        self.assertIn("only present if they were merged", pl["summary"])

    def test_plan_no_default_branch_no_recreate(self):
        self.normal_remove()
        git(self.root, "update-ref", "-d", "refs/heads/feat")
        git(self.root, "branch", "-m", "main", "trunk")
        self.assertIsNone(self.plan())
        pl = self.place()
        self.assertNotIn("recreate", pl)
        self.assertIn("no base branch", pl["error"])

    def test_admin_dir_found_by_gitdir_not_basename(self):
        p1, p2 = os.path.join(self.tmp, "p1", "api"), os.path.join(self.tmp, "p2", "api")
        os.makedirs(os.path.dirname(p1))
        os.makedirs(os.path.dirname(p2))
        git(self.root, "worktree", "add", "-b", "b1", p1)
        git(self.root, "worktree", "add", "-b", "b2", p2)
        s1 = commit(p1, "x1")
        s2 = commit(p2, "x2")
        self.assertNotEqual(s1, s2)
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, ".git", "worktrees"))), ["api", "api1", "w"])
        self.transcript(SID2, p2, "b2")
        self.hand_delete(p2)
        git(self.root, "update-ref", "-d", "refs/heads/b2")
        pl = self.plan(SID2, p2)
        self.assertEqual((pl["base_kind"], pl["base"]), ("last-commit", s2))

    def test_plan_transcript_branch_is_primary(self):
        git(self.root, "branch", "other")
        self.hand_delete()                          # admin HEAD still says feat
        self.transcript(SID, self.wt, "other")
        self.assertEqual(self.plan()["branch"], "other")

    def test_detached_head_branch_is_no_branch(self):
        self.normal_remove()
        self.transcript(SID, self.wt, "HEAD")
        pl = self.plan()                            # E5: falls back to the default-branch rule
        self.assertEqual((pl["branch"], pl["base_kind"]), ("", "default-branch"))
        self.assertTrue(pl["new_branch"].startswith("worktree-w-cont-"))

    def test_plan_branch_checked_out_elsewhere_new_branch(self):
        self.normal_remove()
        other = os.path.join(self.tmp, "other")
        git(self.root, "worktree", "add", other, "feat")
        pl = self.plan()
        self.assertEqual((pl["base_kind"], pl["new_branch"], pl["base"]),
                         ("branch-tip", "feat-cont-aaaaaaaa", self.feat_sha))

    def test_reclone_same_path_uses_default_base(self):
        # D7: an admin reflog whose sha does not exist in the CURRENT repo is stale.
        self.normal_remove()
        git(self.root, "update-ref", "-d", "refs/heads/feat")
        g = os.path.join(self.root, ".git", "worktrees", "w")
        os.makedirs(os.path.join(g, "logs"))
        with open(os.path.join(g, "gitdir"), "w") as fh:
            fh.write(os.path.join(self.wt, ".git") + "\n")
        with open(os.path.join(g, "logs", "HEAD"), "w") as fh:
            fh.write("%s %s t <t> 1 +0000\tx\n" % ("0" * 40, "a" * 40))
        pl = self.plan()
        self.assertEqual((pl["base_kind"], pl["base"]), ("default-branch", self.main_sha))

    def test_invalid_path_no_recreate_key(self):
        bad = os.path.join(self.root, ".claude", "worktrees", "nodir", "y")   # parent missing
        self.transcript(SID2, bad, "feat")
        self.assertIsNone(term_gate.recreate_plan(SID2, bad, self.root))
        pl = term_gate.place(SID2, "", "resume")
        self.assertNotIn("recreate", pl)
        self.assertTrue(pl["error"])
        home = os.path.expanduser("~")
        self.assertFalse(term_gate._valid_recreate_path(home, self.root, SID))
        self.assertFalse(term_gate._valid_recreate_path(self.root, self.root, SID))
        self.assertFalse(term_gate._valid_recreate_path("/", self.root, SID))

    def test_repo_gone_409_without_recreate(self):
        gone = os.path.join(self.tmp, "nope")
        with mock.patch.object(term_gate, "terminal_dir", return_value=("deleted", gone, "")):
            pl = term_gate.place(SID, "", "resume")
        self.assertNotIn("recreate", pl)
        self.assertIn("no longer exists", pl["error"])

    def test_no_git_on_poll(self):
        self.normal_remove()
        d = registry.parse_any(SID)
        self.assertIn("was removed", d["meta"]["term_home_note"])
        self.assertIn("was removed", term_gate.home_note(SID, ""))
        self.assertEqual(self.calls, [])


class TestConfirm(_Repo):
    def test_recreate_then_resume_same_sid(self):
        self.normal_remove()
        h = type("H", (), {"headers": {}, "calls": [], "_json": lambda s, o, c=200: s.calls.append((o, c))})()
        with mock.patch.object(term_launch, "_local_caller", return_value=(True, "")), \
                mock.patch.object(term_launch, "subprocess") as sp, \
                mock.patch.object(term_launch, "_background_target", return_value=""), \
                mock.patch.object(term_gate, "resume_argv", return_value=["claude", "--resume", SID]):
            term_launch.open_terminal(h, None, {"session": SID, "mode": "resume"})
            body, code = h.calls[-1]
            self.assertEqual((code, "recreate" in body), (409, True), body)
            self.assertFalse(os.path.exists(self.wt))
            term_launch.open_terminal(h, None, {"session": SID, "mode": "resume", "recreate": body["recreate"]["token"]})
            self.assertEqual(h.calls[-1], ({"ok": True}, 200), h.calls[-1])
            script = sp.run.call_args[0][0][2]
        self.assertEqual(util.git_worktree_root(self.wt)[0], self.root)
        self.assertEqual(util._git_branch(self.wt), "feat")
        self.assertIn(SID, script)
        self.assertIn(self.wt, script)

    def test_token_mismatch_replans_no_write(self):
        self.normal_remove()
        before = self.branches()
        pl = self.place(token="1999999999.deadbeef")
        self.assertIn("recreate", pl)
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.branches(), before)
        self.assertEqual(self.writes(), [])

    def test_token_expired_replans(self):
        self.normal_remove()
        p = self.plan()
        old = term_gate._make_token(SID, p["path"], p["branch"], p["new_branch"], p["base"], int(time.time()) - 5)
        pl = self.place(token=old)
        self.assertIn("recreate", pl)
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.writes(), [])

    def test_token_single_use(self):
        self.normal_remove()
        tok = self.plan()["token"]
        self.assertTrue(self.place(token=tok)["shell"])
        self.normal_remove()
        pl = self.place(token=tok)
        self.assertIn("recreate", pl)
        self.assertFalse(os.path.exists(self.wt))

    def test_token_from_other_process_rejected(self):
        self.normal_remove()
        with mock.patch.object(term_gate, "_SECRET", b"x" * 32):
            tok = self.plan()["token"]
        pl = self.place(token=tok)
        self.assertIn("recreate", pl)
        self.assertFalse(os.path.exists(self.wt))

    def test_recreate_readonly_or_tunnel_visitor_403(self):
        self.normal_remove()
        tok = self.plan()["token"]
        n = len(self.calls)
        t0, a0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, ""
        self.addCleanup(setattr, config, "TERMINAL", t0)
        self.addCleanup(setattr, config, "AUTH", a0)
        for extra in ({"headers": {"CF-Ray": "x"}}, {"headers": {}, "_readonly": lambda s: True}):
            seen = []
            h = type("H", (), dict(extra, _json=lambda s, o, c=200: seen.append((o, c))))()
            term_vt.open_pty(h, None, {"session": SID, "mode": "resume", "recreate": tok})
            self.assertEqual(seen[-1][1], 403, seen)
        self.assertEqual(len(self.calls), n)               # not one git call
        self.assertFalse(os.path.exists(self.wt))

    def test_lost_race_is_success(self):
        self.normal_remove()
        pl = self.plan()

        def other_process(p):
            git(self.root, "worktree", "add", p["path"], "feat")
            return 1, "fatal: already exists"
        with mock.patch.object(term_gate, "_git_add", side_effect=other_process):
            self.assertEqual(term_gate.recreate_worktree(pl), (True, self.wt))

    def test_lost_race_any_branch_is_success(self):
        self.normal_remove()
        pl = self.plan()

        def other_process(p):                              # E3: the winner chose another branch
            git(self.root, "worktree", "add", "-b", "zzz", p["path"])
            return 1, "fatal"
        with mock.patch.object(term_gate, "_git_add", side_effect=other_process):
            self.assertEqual(term_gate.recreate_worktree(pl), (True, self.wt))
        self.assertEqual(util._git_branch(self.wt), "zzz")

    def test_add_failure_without_live_worktree_is_error(self):
        self.normal_remove()
        pl = self.plan()
        with mock.patch.object(term_gate, "_git_add", return_value=(1, "boom")):
            ok, err = term_gate.recreate_worktree(pl)
        self.assertFalse(ok)
        self.assertIn("boom", err)

    def test_path_occupied_refused_untouched(self):
        self.normal_remove()
        pl = self.plan()
        os.makedirs(self.wt)
        f = os.path.join(self.wt, "keep.txt")
        with open(f, "w") as fh:
            fh.write("mine")
        self.calls.clear()
        ok, err = term_gate.recreate_worktree(pl)
        self.assertFalse(ok)
        self.assertIn("occupied", err)
        self.assertEqual(open(f).read(), "mine")
        self.assertEqual(os.listdir(self.wt), ["keep.txt"])
        self.assertEqual(self.writes(), [])

    def test_registered_missing_prunes_then_adds(self):
        w2 = os.path.join(self.root, ".claude", "worktrees", "w2")
        git(self.root, "worktree", "add", "-b", "feat2", w2)
        self.hand_delete()
        self.hand_delete(w2)
        pl = self.plan()
        self.assertTrue(pl["prune"])
        self.assertIn("clears 2 stale worktree registration(s)", pl["summary"])
        self.assertTrue(self.place(token=pl["token"])["shell"])
        self.assertNotIn(w2, self.wlist())
        self.assertEqual(util._git_branch(self.wt), "feat")

    def test_never_force(self):
        self.hand_delete()
        git(self.root, "update-ref", "-d", "refs/heads/feat")
        self.assertTrue(self.place(token=self.plan()["token"])["shell"])      # prune + add -b
        banned = {"-f", "--force", "-B", "-D", "reset", "checkout", "clean", "--detach"}
        self.assertTrue(self.calls)
        for c in self.calls:
            self.assertFalse(banned & set(c), c)
            self.assertTrue(term_gate._git_allowed(c), c)
        for bad in (("branch", "-D", "x"), ("worktree", "add", "-f", "p", "b"), ("reset", "--hard")):
            with self.assertRaises(AssertionError):
                self.real_git(self.root, *bad)

    def test_concurrent_confirms_one_worktree(self):
        self.normal_remove()
        self.transcript(SID2, self.wt, "feat")
        toks = {SID: self.plan()["token"], SID2: self.plan(SID2)["token"]}
        adds, real = [], term_gate._git_add

        def counted(p):
            adds.append(1)
            return real(p)
        bar, out = threading.Barrier(4), []

        def go(sid):
            bar.wait()
            out.append(self.place(token=toks[sid], sid=sid))
        with mock.patch.object(term_gate, "_git_add", side_effect=counted):
            ts = [threading.Thread(target=go, args=(s,)) for s in (SID, SID, SID2, SID2)]
            [t.start() for t in ts]
            [t.join(60) for t in ts]
        self.assertEqual(len(adds), 1)
        self.assertEqual(len(out), 4)
        for pl in out:
            self.assertEqual((pl["shell"], pl["run"], pl["error"]), (self.root, self.wt, ""), pl)


_JS = r"""
var __timers = [];
window.setTimeout = function (fn) { __timers.push(fn); return 0; };
window.localStorage.setItem('tracker.ui', 'next');
"""

_DRIVER = r"""
function __flush() { return new Promise(function (r) { setImmediate(r); }); }
var __o = {};
(async function () {
  try {
    var host = makeReal('div'); host.id = 'toasts';
    var CRV = window.ExtVT.confirmRecreate;
    var body = { error: 'Worktree X was removed', recreate: { token: 'TOK', summary: 'Recreate X on feat' } };
    var seenText = '';
    function slow(v) { return function (t) { seenText = t; var e = Date.now() + 60; while (Date.now() < e) {} return v; }; }
    // accepted: retry carries the token, text = server error + summary
    var got = [];
    window.confirm = slow(true);
    __o.handled = CRV(body, function (x) { got.push(x); }, function () { return true; });
    __o.accepted = got.slice(); __o.text = seenText;
    // declined (took > 50 ms): nothing sent, no toast
    got = []; window.confirm = slow(false);
    CRV(body, function (x) { got.push(x); }, function () { return true; });
    __o.declined = got.length; __o.toastsAfterDecline = host._children.length;
    // superseded while confirm is open: no second request
    got = []; var cur = true;
    window.confirm = function () { cur = false; return true; };
    CRV(body, function (x) { got.push(x); }, function () { return cur; });
    __o.superseded = got.length;
    // suppressed confirm (false at once): toast with a wired Recreate button
    got = []; window.confirm = function () { return false; };
    CRV(body, function (x) { got.push(x); }, function () { return true; });
    var t = host._children[host._children.length - 1];
    var btn = t && t._children.filter(function (c) { return c.tagName === 'BUTTON'; })[0];
    function tx(n) { return (n.textContent || '') + (n._children || []).map(tx).join(''); }
    __o.toastText = t ? tx(t) : ''; __o.btnText = btn ? tx(btn) : '';
    __o.beforeClick = got.length;
    if (btn) btn.onclick();
    __o.afterClick = got.slice();
    __o.noRecreate = CRV({ error: 'x' }, function () {}, function () { return true; });
    // end to end through the real assembled boot: answerSession 409 -> confirm -> same POST + token
    var ctxCap = null;
    window.CR.dialogs = { mount: function (root, c) { ctxCap = c; } };
    __timers.slice().forEach(function (fn) { try { fn(); } catch (e) {} });
    var posts = [];
    window.confirm = function () { return true; };
    window.fetch = function (url, init) {
      var b = JSON.parse(init.body); posts.push(b);
      var first = posts.length === 1;
      return Promise.resolve({ ok: !first, status: first ? 409 : 200,
        json: function () { return Promise.resolve(first ? body : { ok: true }); } });
    };
    window.CR.answerSession({ id: 'cc1', resumable: true });
    await __flush(); await __flush(); await __flush();
    __o.posts = posts;
    console.log(__MARK__);
    console.log(JSON.stringify(__o));
  } catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
})();
"""


def _js_run():
    from tests.test_working_glow_board import _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node
    mark = "===RECREATE_JSON==="
    js = "\n".join([_REAL_DOM_PREAMBLE, _JS, _bundle_js(), _DRIVER.replace("__MARK__", json.dumps(mark)),
                    "\n} catch (e) { console.error('BUNDLE-THREW: ' + (e && e.stack || e)); process.exit(1); }"])
    rc, out, err = _run_node(js)
    if rc:
        raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
    return _extract_marker_json(out, mark)


_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestConfirmWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _js_run()

    def test_confirm_shows_server_text_and_retry_carries_token(self):
        self.assertTrue(self.O["handled"])
        self.assertEqual(self.O["accepted"], [{"recreate": "TOK"}])
        self.assertEqual(self.O["text"], "Worktree X was removed\n\nRecreate X on feat")
        self.assertFalse(self.O["noRecreate"])

    def test_declined_confirm_sends_nothing(self):
        self.assertEqual(self.O["declined"], 0)
        self.assertEqual(self.O["toastsAfterDecline"], 0)

    def test_confirm_retry_dropped_when_superseded(self):
        self.assertEqual(self.O["superseded"], 0)

    def test_suppressed_confirm_falls_back_to_toast(self):
        self.assertIn("Recreate X on feat", self.O["toastText"])
        self.assertEqual(self.O["btnText"], "Recreate")
        self.assertEqual(self.O["beforeClick"], 0)
        self.assertEqual(self.O["afterClick"], [{"recreate": "TOK"}])

    def test_answer_session_409_retries_with_token(self):
        self.assertEqual(self.O["posts"], [{"session": "cc1", "mode": "resume"},
                                           {"session": "cc1", "mode": "resume", "recreate": "TOK"}])

    def test_extvt_resolved_lazily(self):
        # ext_vt.js is concatenated last: each caller must look window.ExtVT up inside the handler.
        for f, needle in (("ext_launch.js", "ExtVT"), ("ext_cr_term.js", "window.ExtVT.confirmRecreate"),
                          ("ext_cr_boot.js", "window.ExtVT.confirmRecreate")):
            src = open(os.path.join(_WEB, f)).read()
            self.assertIn("confirmRecreate", src, f)
            for m in re.finditer(r"^\S.*ExtVT.*confirmRecreate", src, re.M):     # a column-0 (module scope) use
                self.fail("%s captures ExtVT at module scope: %s" % (f, m.group(0)))
            self.assertIn(needle, src, f)


if __name__ == "__main__":
    unittest.main()
