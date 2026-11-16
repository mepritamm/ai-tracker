#!/usr/bin/env python3
"""Resume-all: the R0 refactors (store._update_json, agent_cli._agent_launch)."""
import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

import aitracker
from aitracker import agent_cli as ac
import time

from aitracker import config, store, term_gate, term_vt
from tests import test_folder_terminal as tft
from tests import test_term_vt_upgrade as tvu


class UpdateJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "x.json")

    def test_t0a_concurrent_updates_survive_and_false_skips_save(self):
        def worker(name):
            for i in range(10):
                store._update_json(self.path, lambda d, k="%s%d" % (name, i): d.__setitem__(k, 1))
        ts = [threading.Thread(target=worker, args=(n,)) for n in "ab"]
        [t.start() for t in ts]
        [t.join() for t in ts]
        with open(self.path) as fh:
            self.assertEqual(len(json.load(fh)), 20)
        before = os.stat(self.path).st_mtime_ns
        store._update_json(self.path, lambda d: False)
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)


class LaunchTests(unittest.TestCase):
    def test_t0b_launch_refusals_release_the_slot(self):
        fn = lambda job: None
        self.assertTrue(ac._AGENT_JOB_LOCK.acquire(blocking=False))
        try:
            code, body = ac._agent_launch("claude", "doctor", fn, ())
            self.assertEqual(code, 409)
            self.assertIn("already running", body["error"])
        finally:
            ac._AGENT_JOB_LOCK.release()
        self.assertTrue(ac._APPLY.acquire(blocking=False))
        try:
            code, body = ac._agent_launch("claude", "doctor", fn, ())
            self.assertEqual(code, 409)
            self.assertIn("updating itself", body["error"])
            self.assertFalse(ac._AGENT_JOB_LOCK.locked())
        finally:
            ac._APPLY.release()
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no threads")):
            code, body = ac._agent_launch("claude", "doctor", fn, ())
        self.assertEqual(code, 500)
        self.assertFalse(ac._AGENT_JOB_LOCK.locked())


def _row(target, **kw):
    r = {"session": target, "target": target, "cwd": "/w", "title": "T", "cols": 120, "rows": 32}
    r.update(kw)
    return r


class _RecBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "last_terms.json")
        saved = (config.LAST_TERMS_FILE, term_vt._REMEMBER_ON, term_vt._LAST_FP, term_vt._LAST_FULL)
        config.LAST_TERMS_FILE = self.path
        term_vt._LAST_FP, term_vt._LAST_FULL = None, 0.0
        self.addCleanup(lambda: (setattr(config, "LAST_TERMS_FILE", saved[0]),
                                 setattr(term_vt, "_REMEMBER_ON", saved[1]),
                                 setattr(term_vt, "_LAST_FP", saved[2]),
                                 setattr(term_vt, "_LAST_FULL", saved[3])))

    def _file(self):
        with open(self.path) as fh:
            return json.load(fh)

    def _stub(self, rows, fp=(("t1", 1),)):
        self.calls = 0

        def cands(light=False):
            self.calls += 1
            self.light = light
            return rows
        for name, val in (("upgrade_candidates", cands), ("_pane_fingerprint", lambda: fp)):
            p = mock.patch.object(term_vt, name, val)
            p.start()
            self.addCleanup(p.stop)


class EntriesAndMerge(unittest.TestCase):
    def test_t1_entries_key_on_target_skip_empty_dedupe(self):
        out = term_vt._entries([_row("Y", session="X"), _row(""), _row("Y", title="second"), _row("Z")], 5.0)
        self.assertEqual(sorted(out), ["Y", "Z"])
        self.assertEqual(out["Y"]["title"], "T")
        self.assertEqual(set(out["Y"]), {"cwd", "title", "seen", "cols", "rows"})

    def test_t2_merge_semantics(self):
        e = lambda seen, title="t": {"cwd": "/w", "title": title, "seen": seen, "cols": 1, "rows": 1}
        d = {"A": e(10)}
        self.assertFalse(term_vt._merge_terms(d, {}))
        self.assertEqual(d, {"A": e(10)})
        self.assertTrue(term_vt._merge_terms(d, {"B": e(11)}))
        self.assertEqual(sorted(d), ["A", "B"])
        term_vt._merge_terms(d, {"A": e(5, "new")})
        self.assertEqual((d["A"]["seen"], d["A"]["title"]), (10, "new"))
        d["x"] = 5
        term_vt._merge_terms(d, {"B": e(12)})
        self.assertNotIn("x", d)
        big = {"k%d" % i: e(100 + i) for i in range(40)}
        term_vt._merge_terms(big, {"live": e(1)})
        self.assertEqual(len(big), term_vt.LAST_TERMS_MAX)
        self.assertNotIn("live", big)
        self.assertIn("k39", big)


class Remember(_RecBase):
    def test_t3_two_trackers_merge(self):
        store._save_json(self.path, {"X": {"cwd": "/o", "title": "x", "seen": 1.0, "cols": 1, "rows": 1}})
        term_vt._REMEMBER_ON = True
        self._stub([_row("Y")])
        term_vt.remember_terminals(final=True)
        self.assertEqual(sorted(self._file()), ["X", "Y"])
        term_vt._LAST_FP, term_vt._LAST_FULL = None, 0.0
        self._stub([_row("X")])
        term_vt.remember_terminals(final=True)
        self.assertGreater(self._file()["X"]["seen"], 1.0)

    def test_t4_gate_and_empty_fingerprint(self):
        term_vt._REMEMBER_ON = True
        self._stub([_row("Y")])
        term_vt.remember_terminals()
        term_vt.remember_terminals()
        self.assertEqual(self.calls, 1)
        term_vt.remember_terminals(final=True)
        self.assertEqual(self.calls, 2)
        os.remove(self.path)
        self._stub([_row("Y")], fp=())
        term_vt.remember_terminals(final=True)
        self.assertEqual(self.calls, 0)
        self.assertFalse(os.path.exists(self.path))

    def test_s1_recorder_asks_for_the_light_rows(self):
        term_vt._REMEMBER_ON = True
        self._stub([_row("Y")])
        term_vt.remember_terminals(final=True)
        self.assertIs(self.light, True)

    def test_t5_not_recording_and_isolation(self):
        term_vt._REMEMBER_ON = False
        self._stub([_row("Y")])
        term_vt.remember_terminals(final=True)
        self.assertFalse(os.path.exists(self.path))
        import tests
        real = tests._config.LAST_TERMS_FILE             # the suite-wide redirect (self.path is per-test)
        self.assertFalse(real.startswith(os.path.dirname(aitracker.__file__)))
        self.assertFalse(term_vt.start_remember())
        alive = lambda: [t for t in threading.enumerate() if t.name == "term-remember"]
        self.assertEqual(alive(), [])
        self.addCleanup(lambda: setattr(term_vt, "_REMEMBER_ON", False))
        self.assertTrue(term_vt._real_start_remember())
        self.assertEqual(len(alive()), 1)
        t = alive()[0]
        term_vt._REMEMBER_STOP.set()
        t.join(5)
        self.assertEqual(alive(), [])
        term_vt._REMEMBER_STOP.clear()

    def test_t7_remembered_terminals(self):
        e = lambda s: {"cwd": "/w", "title": "t", "seen": s, "cols": 1, "rows": 1}
        store._save_json(self.path, {"A": e(3), "B": e(2), "C": e(1), "junk": 5, "bad": {"seen": "x"}})
        term_vt._REMEMBER_ON = False
        with mock.patch.object(store, "_find_transcript", lambda sid: "" if sid == "B" else "/t"):
            got = term_vt.remembered_terminals()
        self.assertEqual([r["session"] for r in got], ["A", "C"])


class LightRows(tvu._Base):
    """upgrade_candidates(light=True): the recorder's rows, with no transcript parse, no `ps`, no argv work."""

    def setUp(self):
        super().setUp()
        tft._stub_kill(self)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _pane(self):
        pt = term_vt.Pty(tid="a", pid=100, fd=97, cwd=self._tmpdir)
        pt.folder, pt.shell_cmd, pt.startup_done = True, "sh", True
        pt.fg = {"session": "X", "mode": "resume", "started": time.time(), "grants": {"X"}}
        term_vt.PTYS["a"] = pt

    def _rows(self, light):
        boom = mock.Mock(side_effect=AssertionError("heavy work on the light path"))
        prov = term_vt._provider()
        runs = [{"pid": 1100, "id": "Y", "host": "tui", "version": "2.1.1", "status_raw": "busy"}]   # stale label X
        with mock.patch.object(term_vt, "_reap"), mock.patch.object(term_vt, "_refresh_fg"), \
             mock.patch.object(term_vt, "_foreground_is_claude", return_value=True), \
             mock.patch.object(term_vt, "_fg_pgid", return_value=1100), \
             mock.patch.object(term_vt, "_background_target", return_value=""), \
             mock.patch.object(term_vt, "_thin_client_short", boom if light else mock.Mock(return_value="")), \
             mock.patch.object(prov, "running_sessions", return_value=runs), \
             mock.patch.object(term_gate, "session_cwd", boom if light else mock.Mock(return_value=self._tmpdir)), \
             mock.patch.object(term_gate, "allowed", return_value=True), \
             mock.patch.object(term_gate, "resume_argv", boom if light else mock.Mock(return_value=["claude"])):
            rows = term_vt.upgrade_candidates(light=light)
        return rows, boom

    def test_s1_light_skips_transcript_work_but_keeps_the_pid_file_over_a_stale_label(self):
        self._pane()
        (r,), boom = self._rows(True)
        boom.assert_not_called()
        self.assertEqual((r["session"], r["relabelled"], r["target"], r["cwd"]), ("Y", "X", "Y", self._tmpdir))
        self.assertEqual((r["thin"], r["needs_slot"], r["stoppable"], r["command"]), (False, False, False, []))
        self.assertEqual(set(r), set(self._rows(False)[0][0]))        # same row shape as the heavy path


if __name__ == "__main__":
    unittest.main()
