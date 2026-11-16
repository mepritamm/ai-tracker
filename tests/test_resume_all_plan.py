#!/usr/bin/env python3
"""Resume-all R2: term_vt._ra_need and resume_all_plan (T8, T9).
Run: unset TRACKER_AUTH; python3 -m unittest -q tests.test_resume_all_plan"""
import types
import unittest
from unittest import mock

from aitracker import config, gateway, term_gate, term_vt
from tests.test_resume_all_jobs import FakeTV, row


class NeedTests(unittest.TestCase):
    def test_t8_ra_need(self):
        self.assertEqual(term_vt._ra_need(["/a"], {"/a"}), 0)
        self.assertEqual(term_vt._ra_need(["/a", "/a"], {"/a"}), 1)
        self.assertEqual(term_vt._ra_need(["/b", "/b"], set()), 2)


def _sid(n):
    return "0000000%d-1111-2222-3333-444444444444" % n


AUG, OPEN, DAE, DESK, TUI, BADARGV, NOCWD, O1, O2, O3 = (
    "auggie:x", _sid(1), _sid(2), _sid(3), _sid(4), _sid(5), _sid(6), _sid(7), _sid(8), _sid(9))


class _Prov:
    @staticmethod
    def running_sessions():
        return [{"id": DAE, "host": "daemon", "pid": 1}, {"id": DESK, "host": "desktop", "pid": 2},
                {"id": TUI, "host": "tui", "pid": 77}]

    @staticmethod
    def session_label(sid):
        return ""


def _argv(sid):
    if sid == BADARGV:
        raise gateway.GatewayError("x")
    return ["claude", "--resume", sid]


class PlanTests(unittest.TestCase):
    def _plan(self, idle_cwd, argv=_argv):
        ents = [{"session": s, "cwd": "/w/" + s[:9], "title": "t" + s[:9], "seen": 100 - i, "cols": 80, "rows": 24}
                for i, s in enumerate([AUG, OPEN, DAE, DESK, TUI, BADARGV, NOCWD, O1, O2, O3])]
        cwds = {O1: "/c1", O2: "/c2", O3: "/c3"}
        ptys = {}
        live = types.SimpleNamespace(done=False, closing=False, folder=False, cwd="/live", fg=None, pid=9)
        ptys["a"] = live
        if idle_cwd:
            ptys["b"] = types.SimpleNamespace(done=False, closing=False, folder=True, cwd=idle_cwd, fg=None, pid=5)
        else:
            ptys["b"] = types.SimpleNamespace(done=False, closing=False, folder=False, cwd="/x", fg=None, pid=6)
        self.fasts = []
        old = config.MAX_TERMS
        config.MAX_TERMS = 4            # 2 live -> free == 2
        self.addCleanup(setattr, config, "MAX_TERMS", old)
        with mock.patch.object(term_vt, "remembered_terminals", return_value=ents), \
             mock.patch.object(term_vt, "_provider", return_value=_Prov), \
             mock.patch.object(term_vt, "PTYS", ptys), \
             mock.patch.object(term_vt, "_reap"), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=lambda p: p.pid), \
             mock.patch.object(term_vt, "_session_pty", side_effect=lambda s: object() if s == OPEN else None), \
             mock.patch.object(term_vt, "_background_target", return_value=""), \
             mock.patch.object(term_gate, "resume_argv", side_effect=argv), \
             mock.patch.object(term_gate, "session_cwd",
                               side_effect=lambda s, resume=False, fast=False: self.fasts.append(fast) or ("" if s == NOCWD else cwds.get(s, "/z"))):
            return term_vt.resume_all_plan()

    def test_t9_classification_and_pretick_with_idle_shell(self):
        p = self._plan("/c3")
        why = {r["session"]: r["reason"] for r in p["cannot"]}
        self.assertEqual(why[AUG], term_vt.RA_ONLY_CLAUDE)
        self.assertEqual(why[DAE], term_vt.RA_DAEMON)
        self.assertEqual(why[DESK], term_vt.RA_DESKTOP)
        self.assertEqual(why[TUI], term_vt.RA_TUI % 77)
        self.assertIn("pid 77", why[TUI])
        self.assertEqual(why[BADARGV], "x")
        self.assertEqual(why[NOCWD], term_vt.RA_NO_CWD)
        self.assertEqual(len(p["cannot"]), 6)
        self.assertEqual(p["already"], ["t" + OPEN[:9]])
        self.assertEqual([r["session"] for r in p["open"]], [O1, O2, O3])
        self.assertTrue(all(r["checked"] for r in p["open"]))
        self.assertEqual((p["free"], p["max"], p["in_use"], p["idle"]), (2, 4, 2, ["/c3"]))
        r = p["open"][0]
        self.assertEqual((r["cwd"], r["command"], r["reason"], r["cols"], r["rows"]),
                         ("/c1", ["claude --resume " + O1], "", 80, 24))

    def test_t9_no_idle_shell_leaves_oldest_unticked(self):
        p = self._plan("")
        self.assertEqual([r["checked"] for r in p["open"]], [True, True, False])
        self.assertEqual(p["idle"], [])

    def test_s2_plan_resolves_cwd_on_the_fast_path(self):
        self._plan("/c3")
        self.assertTrue(self.fasts and all(self.fasts), self.fasts)

    def test_n3_one_bad_entry_is_a_cannot_row_not_an_empty_plan(self):
        def argv(sid):
            if sid == O2:
                raise ValueError("boom")
            return _argv(sid)
        p = self._plan("/c3", argv)
        self.assertEqual([r["session"] for r in p["open"]], [O1, O3])
        bad = next(r for r in p["cannot"] if r["session"] == O2)
        self.assertEqual(bad["reason"], term_vt.RA_ERROR % "boom")

    def test_real_plan_shape_fits_the_fake_plan(self):
        p, fake = self._plan("/c3"), FakeTV.mkplan([row("A")], [row("B", reason="r")])
        self.assertEqual(set(p), set(fake))
        self.assertTrue(p["open"] and p["cannot"])
        for r in p["open"] + p["cannot"]:
            self.assertEqual(set(r), set(row("A")))
            self.assertIsInstance(r["command"], list)
            self.assertTrue(all(isinstance(c, str) for c in r["command"]))


class FastCwd(unittest.TestCase):
    """The preview resolves cwd from the transcript's head/tail, never a full parse (S2)."""

    def test_s2_fast_cwd_reads_tail_then_head_and_never_parses(self):
        import json
        import os
        import shutil
        import tempfile
        from aitracker import registry
        from aitracker.providers import claude
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        new = os.path.join(d, "new")
        os.mkdir(new)
        f = os.path.join(d, "s.jsonl")
        with open(f, "w") as fh:
            fh.write(json.dumps({"cwd": os.path.join(d, "gone", "old")}) + "\n")
            fh.write(json.dumps({"cwd": new, "message": {"role": "user", "content": "hi"}}) + "\n")
        boom = mock.Mock(side_effect=AssertionError("full parse in the preview"))
        with mock.patch.object(claude, "find_session", return_value=f), \
             mock.patch.object(claude, "parse_session", boom), mock.patch.object(registry, "parse_any", boom):
            self.assertEqual(term_gate.session_cwd(_sid(1), resume=True, fast=True), new)     # last cwd wins
            with open(f, "w") as fh:                       # tail has none: the head's, walked up to d
                fh.write(json.dumps({"cwd": os.path.join(d, "gone", "old")}) + "\n")
            claude._META_CACHE.clear()
            self.assertEqual(term_gate.session_cwd(_sid(1), resume=True, fast=True), d)
        boom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
