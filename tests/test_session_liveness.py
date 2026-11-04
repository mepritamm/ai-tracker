"""Idle-TTL keep-alive building blocks: the provider-side session liveness helpers
(`session_last_active`, `daemon_repl_pid`) and the LIVE_WINDOW call-time/served-to-SPA drift fix."""
import glob
import json
import os
import re
import shutil
import tempfile
import time
import unittest

from aitracker import config, page, util
from aitracker.providers import claude

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")


def _dead_pid():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


class _Env(unittest.TestCase):
    def setUp(self):
        self._saved = (config.PROJECTS, config.DAEMON_ROSTER, config.LIVE_WINDOW)
        self.tmp = tempfile.mkdtemp(prefix="liveness-")
        config.PROJECTS = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        config.DAEMON_ROSTER = os.path.join(self.tmp, "roster.json")

    def tearDown(self):
        config.PROJECTS, config.DAEMON_ROSTER, config.LIVE_WINDOW = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _transcript(self, sid, age=0):
        p = os.path.join(config.PROJECTS, "proj", sid + ".jsonl")
        with open(p, "w") as fh:
            fh.write("{}\n")
        t = time.time() - age
        os.utime(p, (t, t))
        return p


class TestSessionLastActive(_Env):
    def test_P1_newer_of_main_and_agent_file(self):
        main = self._transcript("sidP1", age=500)
        agent_dir = os.path.join(config.PROJECTS, "proj", "sidP1", "subagents")
        os.makedirs(agent_dir)
        af = os.path.join(agent_dir, "agent-a.jsonl")
        with open(af, "w") as fh:
            fh.write("{}\n")
        t = time.time() - 20
        os.utime(af, (t, t))
        self.assertAlmostEqual(claude.session_last_active("sidP1"), t, delta=1.0)
        t2 = time.time() - 5
        os.utime(main, (t2, t2))
        self.assertAlmostEqual(claude.session_last_active("sidP1"), t2, delta=1.0)

    def test_P2_unknown_or_unsafe_id_is_zero(self):
        self._transcript("real")
        for bad in ("nope", "*", "../x", "", None):
            self.assertEqual(claude.session_last_active(bad), 0.0, bad)


class TestDaemonReplPid(_Env):
    def _roster(self, raw):
        with open(config.DAEMON_ROSTER, "w") as fh:
            fh.write(raw if isinstance(raw, str) else json.dumps(raw))

    def _ro(self, sup=None, **w):
        me = os.getpid()
        worker = {"pid": me, "sessionId": "SID", "replPid": me}
        worker.update(w)
        return {"supervisorPid": me if sup is None else sup, "workers": {"x": worker}}

    def test_P3_matrix(self):
        me = os.getpid()
        self._roster(self._ro())
        self.assertEqual(claude.daemon_repl_pid("SID"), me)
        self.assertEqual(claude.daemon_repl_pid("OTHER"), 0)          # wrong sessionId
        self._roster(self._ro(sup=999999))
        self.assertEqual(claude.daemon_repl_pid("SID"), 0)            # dead supervisor
        self._roster(self._ro(replPid=_dead_pid()))
        self.assertEqual(claude.daemon_repl_pid("SID"), 0)            # dead replPid
        self._roster(self._ro(replPid=str(me)))
        self.assertEqual(claude.daemon_repl_pid("SID"), 0)            # str replPid
        self._roster("not json{")
        self.assertEqual(claude.daemon_repl_pid("SID"), 0)            # malformed
        os.remove(config.DAEMON_ROSTER)
        self.assertEqual(claude.daemon_repl_pid("SID"), 0)            # missing roster


class TestLiveWindowAtCallTime(_Env):
    def test_L1_mtime_bg_n_reads_config_at_call_time(self):
        main = self._transcript("sidL1", age=600)
        agent_dir = os.path.join(config.PROJECTS, "proj", "sidL1", "subagents")
        os.makedirs(agent_dir)
        af = os.path.join(agent_dir, "agent-a.jsonl")
        with open(af, "w") as fh:
            fh.write("{}\n")
        t = time.time() - 60
        os.utime(af, (t, t))
        config.LIVE_WINDOW = 300
        self.assertEqual(claude._mtime_bg_n(main)[1], 1)
        config.LIVE_WINDOW = 10
        self.assertEqual(claude._mtime_bg_n(main)[1], 0)

    def test_L2_push_when_reads_config_at_call_time(self):
        now = time.time()
        config.LIVE_WINDOW = 10
        self.assertEqual(util.push_when(True, now - 60, now), "wake")
        config.LIVE_WINDOW = 300
        self.assertEqual(util.push_when(True, now - 60, now), "turn")

    def test_L3_no_frozen_import_of_live_window(self):
        pat = re.compile(r"from \.+config import[^\n]*\bLIVE_WINDOW\b")
        for rel in sorted(os.path.relpath(p, _PKG) for p in glob.glob(os.path.join(_PKG, "**", "*.py"), recursive=True) if os.path.basename(p) != "config.py"):
            with open(os.path.join(_PKG, rel), encoding="utf-8") as fh:
                self.assertIsNone(pat.search(fh.read()), rel + " snapshots LIVE_WINDOW at import")

    def test_L4_page_serves_live_window(self):
        with open(os.path.join(_PKG, "web", "app.js"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count(page.LIVE_MARK), 1)
        config.LIVE_WINDOW = 777
        built = page.build_page()
        self.assertIn("const LIVE=777", built)
        self.assertNotIn("__LIVE_WINDOW__", built)


if __name__ == "__main__":
    unittest.main()
