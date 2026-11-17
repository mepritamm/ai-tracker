"""Pending work links a worktree to its Claude sessions: worktree_states (whole-file), attach_sessions (pure
ranking) and session_evidence (transcripts on disk)."""
import json
import os
import tempfile
import unittest
from unittest import mock

from aitracker import pending
from aitracker.providers import claude
from tests.pending_fixture import make_fixture, requires_git


def _rec(path, entered=None, null=False):
    ws = None if null else {"worktreePath": path}
    if ws is not None and entered is not None:
        ws["enteredExisting"] = entered
    return json.dumps({"type": "worktree-state", "worktreeSession": ws}) + "\n"


class WorktreeStates(unittest.TestCase):
    def test_shapes_order_and_memo(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.jsonl")
            with open(f, "w") as fh:
                fh.write(_rec("/w/a"))                          # created (no enteredExisting)
                fh.write(_rec("/w/b", entered=True))            # entered
                fh.write(_rec("/w/x", null=True))               # worktreeSession null: skipped
                fh.write(json.dumps({"type": "worktree-state", "worktreeSession": "str"}) + "\n")
                fh.write("not json {\"worktree-state\"\n")
                fh.write(_rec("/w/c", entered=True))
                fh.write(_rec("/w/c", entered=False))           # ANY create wins -> not entered
                fh.write(_rec("/w/a", entered=True))            # a is still a create
            self.assertEqual(claude.worktree_states(f), [("/w/a", False), ("/w/b", True), ("/w/c", False)])
            mt = os.stat(f).st_mtime_ns
            with open(f, "a") as fh:
                fh.write(_rec("/w/d", entered=True))
            os.utime(f, ns=(mt, mt))                               # same mtime, new size: the memo must miss
            self.assertIn(("/w/d", True), claude.worktree_states(f))
            self.assertEqual(claude.worktree_states(os.path.join(d, "missing.jsonl")), [])

    def test_mtime_only_change_misses_the_memo(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.jsonl")
            with open(f, "w") as fh:
                fh.write(_rec("/w/a"))
            mt = os.stat(f).st_mtime_ns
            self.assertEqual(claude.worktree_states(f), [("/w/a", False)])
            with open(f, "w") as fh:
                fh.write(_rec("/w/b"))                          # same size, different content
            os.utime(f, ns=(mt + 10 ** 9, mt + 10 ** 9))        # only the mtime moved
            self.assertEqual(claude.worktree_states(f), [("/w/b", False)])

    def test_memo_is_not_capped_at_512_files(self):
        import builtins
        with tempfile.TemporaryDirectory() as d:
            fs = []
            for i in range(513):
                f = os.path.join(d, "%d.jsonl" % i)
                with open(f, "w") as fh:
                    fh.write('{"type":"user"}\n')
                fs.append(f)
            for f in fs:
                claude.worktree_states(f)
            n, real = [0], builtins.open

            def cnt(*a, **k):
                if str(a[0]).startswith((d, os.path.realpath(d))):
                    n[0] += 1
                return real(*a, **k)
            with mock.patch.object(builtins, "open", cnt):
                for f in fs:
                    claude.worktree_states(f)
            self.assertEqual(n[0], 0)


RP = pending._rp


def _wt(p):
    return {"kind": "worktree", "path": p}


def _ev(p, sid, how, last, first=0, res=True, title=None):
    return (RP(p), sid, how, last, first, title or sid, res)


class Attach(unittest.TestCase):
    def test_creator_then_newer_entered_target(self):
        it = _wt("/w/a")
        pending.attach_sessions([it], [_ev("/w/a", "S2", "entered", 400, 300), _ev("/w/a", "S1", "created", 200, 100)])
        self.assertEqual([(r["id"], r["role"], r["target"]) for r in it["sessions"]],
                         [("S1", "created this worktree", False), ("S2", "last worked here", True)])
        self.assertIn("created this worktree: S1", it["session_note"])

    def test_creator_is_target_when_newest(self):
        it = _wt("/w/a")
        pending.attach_sessions([it], [_ev("/w/a", "S1", "created", 200, 100)])
        self.assertEqual([(r["id"], r["role"], r["target"]) for r in it["sessions"]],
                         [("S1", "created this worktree · last worked here", True)])

    def test_repo_item_gets_no_rows(self):
        repo, wt = {"kind": "repo", "path": "/w"}, _wt("/w/a")
        pending.attach_sessions([repo, wt], [_ev("/w", "S1", "cwd", 500), _ev("/w", "S1", "created", 500)])
        self.assertNotIn("sessions", repo)
        self.assertEqual(wt["sessions"], [])

    def test_cwd_goes_to_deepest_worktree(self):
        a, b = _wt("/w/a"), _wt("/w/a/sub")
        pending.attach_sessions([a, b], [_ev("/w/a/sub/x", "S1", "cwd", 5, 1), _ev("/w/a/y", "S2", "cwd", 6, 2)])
        self.assertEqual([r["id"] for r in b["sessions"]], ["S1"])
        self.assertEqual([r["id"] for r in a["sessions"]], ["S2"])

    def test_same_sid_twice_is_one_row(self):
        it = _wt("/w/a")
        pending.attach_sessions([it], [_ev("/w/a", "S1", "cwd", 5, 1), _ev("/w/a", "S1", "cwd", 9, 1), _ev("/w/a", "S1", "entered", 7, 1)])
        self.assertEqual([r["id"] for r in it["sessions"]], ["S1"])
        self.assertEqual(it["sessions"][0]["last"], 9)

    def test_fork_tie_older_mtime_wins_both_orders(self):
        evs = [_ev("/w/a", "FORK", "created", 900, 100), _ev("/w/a", "ORIG", "created", 300, 100)]
        for order in (evs, evs[::-1]):
            it = _wt("/w/a")
            pending.attach_sessions([it], list(order))
            self.assertEqual(it["sessions"][0]["id"], "ORIG")
            self.assertTrue(it["sessions"][0]["role"].startswith("created this worktree"))

    def test_newer_auggie_row_is_link_only(self):
        it = _wt("/w/a")
        pending.attach_sessions([it], [_ev("/w/a", "S1", "created", 200, 100), _ev("/w/a", "auggie:x", "cwd", 900, 0, res=False)])
        byid = {r["id"]: r for r in it["sessions"]}
        self.assertFalse(byid["auggie:x"]["resumable"])
        self.assertFalse(byid["auggie:x"]["target"])
        self.assertTrue(byid["S1"]["target"])
        self.assertIn("Auggie", byid["auggie:x"]["role"])


def _transcript(fx, sid, records, name="proj"):
    d = os.path.join(fx.paths["PROJECTS"], name)
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, sid + ".jsonl")
    with open(fp, "w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return fp


@requires_git
class Evidence(unittest.TestCase):
    def test_later_record_cwd_links_worktree(self):
        fx = make_fixture(self)
        wt = fx.worktree("feat")
        _transcript(fx, "S1", [{"type": "user", "cwd": fx.repo, "message": {"content": "hi"}},
                               {"type": "user", "cwd": wt, "message": {"content": "later"}}])
        ev = pending.session_evidence(full=False)
        self.assertIn((pending._rp(wt), "S1", "cwd"), [(e[0], e[1], e[2]) for e in ev])

    def test_full_false_never_walks_worktree_states(self):
        fx = make_fixture(self)
        wt = fx.worktree("feat")
        _transcript(fx, "S1", [{"type": "user", "cwd": fx.repo, "message": {"content": "hi"}},
                               {"type": "worktree-state", "worktreeSession": {"worktreePath": wt}}])
        with mock.patch.object(pending, "worktree_states", wraps=claude.worktree_states) as m:
            pending.session_evidence(full=False)
            self.assertEqual(m.call_count, 0)
            ev = pending.session_evidence(full=True)
            self.assertEqual(m.call_count, 1)
        self.assertIn((pending._rp(wt), "S1", "created"), [(e[0], e[1], e[2]) for e in ev])

    def test_unchanged_transcripts_cost_no_tail_read(self):
        fx = make_fixture(self)
        wt = fx.worktree("feat")
        for i in range(3):
            _transcript(fx, "S%d" % i, [{"type": "user", "cwd": wt, "message": {"content": "hi"}}])
        claude._TAIL_MEMO.clear()                    # earlier tests leave it larger than the patched cap
        n, orig = [0], claude._tail_scan_raw

        def cnt(*a, **k):
            n[0] += 1
            return orig(*a, **k)
        with mock.patch.object(claude, "_TAIL_MEMO_MAX", 2), mock.patch.object(claude, "_tail_scan_raw", cnt):
            pending.session_evidence(full=False)
            n[0] = 0
            pending.session_evidence(full=False)
        self.assertEqual(n[0], 0)

    def test_nul_in_cwd_or_worktree_path_does_not_raise(self):
        fx = make_fixture(self)
        wt = fx.worktree("feat")
        _transcript(fx, "S1", [{"type": "user", "cwd": wt, "message": {"content": "hi"}},
                               {"type": "user", "cwd": "/a\u0000b", "message": {"content": "x"}},
                               {"type": "worktree-state", "worktreeSession": {"worktreePath": "/w\u0000x"}}])
        ev = pending.session_evidence(full=True)
        self.assertIn((pending._rp(wt), "S1", "cwd"), [(e[0], e[1], e[2]) for e in ev])

    def test_clean_does_not_walk_transcripts(self):
        fx = make_fixture(self)
        wt = fx.worktree("old")
        fx.age(wt, 100)
        _transcript(fx, "S1", [{"type": "worktree-state", "worktreeSession": {"worktreePath": wt}}])
        with mock.patch.object(pending, "worktree_states", wraps=claude.worktree_states) as m:
            report = pending.scan()
            n = m.call_count
            self.assertGreater(n, 0)
            pending.clean(report, "safe")
            self.assertEqual(m.call_count, n)


if __name__ == "__main__":
    unittest.main()
