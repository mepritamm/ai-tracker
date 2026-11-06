"""Taking over a PARKED pane (Left arrow at an empty prompt: the conversation lives in a daemon job,
the TUI left in the pane is only a client). Separate from tests/test_folder_swap.py so the parked
branch can be reverted alone. Run one module per process:

    TRACKER_AUTH= python3 -m unittest tests.test_folder_swap_parked -v
"""
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from aitracker.providers import claude as claude_provider
from tests.test_folder_swap import _SwapBase, A, B, CLIENT, SHELL

JOB = "cccccccc-1111-2222-3333-444444444444"     # the parked pane's job (its OWN session id)


class _Parked(_SwapBase):
    def setUp(self):
        super().setUp()
        self.short = ""                            # a parked pane's args are plain `claude ...`
        self.parked = {(CLIENT, A): JOB}
        self.children = []
        for p in (mock.patch.object(claude_provider, "parked_job_id",
                                    lambda pid, label: self.parked.get((pid, label), "")),
                  mock.patch.object(term_vt, "_claude_work_children",
                                    lambda pid, strict=False: self.children),
                  mock.patch.object(term_vt, "PARKED_DETACH_WAIT", 1.5),
                  mock.patch.object(term_vt, "PARKED_WORK_SETTLE", 0.5)):
            p.start()
            self.addCleanup(p.stop)
        self.live[JOB] = 3333


class TestParkedSwap(_Parked):
    def test_parked_pane_swaps_and_banner_names_the_job(self):
        obj = self.open(B)
        self.assertEqual(obj["tty"], "folder-1")
        self.assertEqual(self.killed, [(CLIENT, signal.SIGTERM)])
        self.assertFalse(self.spawn.called)
        self.assertIn(b"claude --resume " + B.encode(), b"".join(self.typed))
        self.assertIn(JOB[:8], obj["notice"])
        self.assertEqual(self.fp.fg["session"], B)

    def test_parked_pane_resets_itself_so_no_mode_reset_is_fed(self):
        self.open(B)
        self.assertNotIn("tee", self.events, "a parked TUI exits gracefully; only a thin client needs the reset")

    def test_opening_the_job_itself_has_no_banner(self):
        obj = self.open(JOB)
        self.assertEqual(obj["tty"], "folder-1")
        self.assertEqual(len(self.killed), 1)
        self.assertIsNone(obj["notice"], "the displaced job IS the target: nothing to announce")

    def test_parked_exit_takes_longer_than_the_thin_wait(self):
        """A graceful exit (SessionEnd hooks) that outlasts THIN_DETACH_WAIT must still be waited for."""
        def killpg(pg, sig):
            self.killed.append((pg, sig))
            threading.Timer(0.8, lambda: self.state.update(pg=SHELL)).start()
        with mock.patch.object(term_vt.os, "killpg", killpg):
            obj = self.open(B)
        self.assertEqual(obj["tty"], "folder-1")
        self.assertFalse(self.spawn.called)

    def test_parked_pane_with_unseen_work_children_is_left_alone(self):
        self.children = [4242]
        obj = self.open(B)
        self.assertEqual(self.killed, [])
        self.assertTrue(self.spawn.called)
        self.assertEqual(obj["tty"], "overflow-1")

    def test_transient_hook_children_are_waited_out(self):
        """iTerm `it2` hooks show as children for a second or two after a park: sample until clean."""
        calls = []

        def work(pid, strict=False):
            calls.append(1)
            return [4242] if len(calls) < 3 else []
        with mock.patch.object(term_vt, "_claude_work_children", work):
            obj = self.open(B)
        self.assertEqual(obj["tty"], "folder-1")
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(len(self.killed), 1)

    def test_persistent_work_children_wait_out_the_settle_window_then_refuse(self):
        t0 = time.time()
        self.children = [4242]
        obj = self.open(B)
        self.assertGreaterEqual(time.time() - t0, 0.45, "sampled for the whole settle window")
        self.assertEqual(self.killed, [])
        self.assertEqual(obj["tty"], "overflow-1")

    def test_unreadable_process_table_is_not_no_work(self):
        self.children = None                       # strict: None = could not tell
        self.open(B)
        self.assertEqual(self.killed, [])
        self.assertTrue(self.spawn.called)

    def test_not_a_parked_pane_is_left_alone(self):
        self.parked = {}
        self.open(B)
        self.assertEqual(self.killed, [])
        self.assertTrue(self.spawn.called)

    def test_parked_pane_watched_is_left_alone(self):
        self.fp.viewers = 1
        self.open(B)
        self.assertEqual(self.killed, [])

    def test_hand_typed_parked_pane_stays_out(self):
        """A parked pane the app did not type (no fg label) is not a candidate (Decision 3)."""
        self.fp.fg = None
        self.fp.spawned = ""
        self.parked = {(CLIENT, A): JOB}
        self.open(B)
        self.assertEqual(self.killed, [])

    def test_parked_pane_restores_label_when_it_will_not_exit(self):
        self.exits = False
        old = self.fp.fg
        with mock.patch.object(term_vt, "PARKED_DETACH_WAIT", 0.3):
            self.open(B)
        self.assertIs(self.fp.fg, old)
        self.assertEqual(self.typed, [])


class TestWorkChildrenStrict(unittest.TestCase):
    def test_strict_fails_closed_lenient_does_not(self):
        with mock.patch.object(term_vt.subprocess, "run", side_effect=OSError):
            self.assertEqual(term_vt._claude_work_children(1), [])
            self.assertIsNone(term_vt._claude_work_children(1, strict=True))
        with mock.patch.object(term_vt.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="")):
            self.assertEqual(term_vt._claude_work_children(1), [])
            self.assertIsNone(term_vt._claude_work_children(1, strict=True))
        ok = mock.Mock(returncode=0, stdout=" 100 1 100\n 200 100 200\n 201 100 100\n")
        with mock.patch.object(term_vt.subprocess, "run", return_value=ok):
            self.assertEqual(term_vt._claude_work_children(100, strict=True), [200])


class TestParkedJobId(unittest.TestCase):
    """`parked_job_id` against real files, a real `ps` and a roster in a temp dir."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.sess = os.path.join(self.dir, "sessions")
        os.mkdir(self.sess)
        self.proc = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (self.proc.kill(), self.proc.wait()))
        self.pid = self.proc.pid
        self.roster = os.path.join(self.dir, "roster.json")
        self.workers = {"cccccccc": {"pid": self.pid, "sessionId": JOB, "replPid": self.pid}}
        self.write_roster()
        for p in (mock.patch.object(config, "LIVE_SESSIONS_DIR", self.sess),
                  mock.patch.object(config, "DAEMON_ROSTER", self.roster)):
            p.start()
            self.addCleanup(p.stop)
        self.start = self.utc_lstart(self.pid)

    def write_roster(self):
        with open(self.roster, "w") as fh:
            json.dump({"supervisorPid": os.getpid(), "workers": self.workers}, fh)

    @staticmethod
    def utc_lstart(pid):
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                             env=dict(os.environ, LC_ALL="C", TZ="UTC")).stdout
        return " ".join(out.split())

    def write(self, **over):
        d = {"pid": self.pid, "sessionId": A, "kind": "interactive", "parkedJobId": "cccccccc",
             "procStart": self.start, "cwd": "/secret", "status": "idle"}
        d.update(over)
        d = {k: v for k, v in d.items() if v is not None}
        with open(os.path.join(self.sess, "%d.json" % self.pid), "w") as fh:
            fh.write(d if isinstance(d, str) else json.dumps(d))

    def test_accepts_a_live_parked_pane_and_returns_the_job(self):
        self.write()
        self.assertEqual(claude_provider.parked_job_id(self.pid, A), JOB)

    def test_real_ps_in_another_timezone(self):
        """procStart is UTC; the machine's `ps` prints local time. Without TZ=UTC every pane misses."""
        self.write()
        with mock.patch.dict(os.environ, {"TZ": "Asia/Kolkata"}):
            time.tzset()
            try:
                self.assertEqual(claude_provider.parked_job_id(self.pid, A), JOB)
            finally:
                os.environ.pop("TZ", None)
                time.tzset()

    def test_rejects(self):
        cases = {
            "kind bg": dict(kind="bg"),
            "no parkedJobId": dict(parkedJobId=None),
            "label mismatch": dict(sessionId=B),
            "pid mismatch": dict(pid=self.pid + 1),
            "wrong procStart": dict(procStart="Mon Jan  1 00:00:00 2001"),
            "missing procStart": dict(procStart=None),
            "job not in roster": dict(parkedJobId="dddddddd"),
            "unsafe id": dict(parkedJobId="../../etc"),
            "non-string id": dict(parkedJobId=12345),
        }
        for name, over in cases.items():
            with self.subTest(name):
                self.write(**over)
                self.assertEqual(claude_provider.parked_job_id(self.pid, A), "", name)

    def test_rejects_dead_job_repl_and_bad_json(self):
        self.write()
        self.workers["cccccccc"]["replPid"] = None
        self.write_roster()
        self.assertEqual(claude_provider.parked_job_id(self.pid, A), "", "job's REPL is dead")
        self.workers["cccccccc"]["replPid"] = self.pid
        self.write_roster()
        with open(os.path.join(self.sess, "%d.json" % self.pid), "w") as fh:
            fh.write("{not json")
        self.assertEqual(claude_provider.parked_job_id(self.pid, A), "")
        os.remove(os.path.join(self.sess, "%d.json" % self.pid))
        self.assertEqual(claude_provider.parked_job_id(self.pid, A), "", "no file")
        self.assertEqual(claude_provider.parked_job_id(0, A), "")
        self.assertEqual(claude_provider.parked_job_id("x", A), "")
        self.assertEqual(claude_provider.parked_job_id(self.pid, ""), "")

    def test_reads_only_the_named_fields(self):
        """The sessions file also holds cwd etc.; none of it may leak into the answer."""
        self.write()
        self.assertIsInstance(claude_provider.parked_job_id(self.pid, A), str)


class TestReplIsLocal(unittest.TestCase):
    """`repl_is_local` reads LIVE_SESSIONS_DIR/<pid>.json: only an interactive, unparked Claude hosts its own conversation."""

    def setUp(self):
        self.sess = tempfile.mkdtemp()
        p = mock.patch.object(config, "LIVE_SESSIONS_DIR", self.sess)
        p.start()
        self.addCleanup(p.stop)

    def write(self, raw):
        with open(os.path.join(self.sess, "4242.json"), "w") as fh:
            fh.write(raw if isinstance(raw, str) else json.dumps(raw))

    def test_cases(self):
        f = claude_provider.repl_is_local
        self.assertFalse(f(4242), "no file: a thin client / attach / agents board")
        self.write({"pid": 4242, "kind": "interactive"})
        self.assertTrue(f(4242))
        self.write({"pid": 4242, "kind": "interactive", "parkedJobId": "cccccccc"})
        self.assertFalse(f(4242), "parked: the work lives in a daemon job")
        self.write({"pid": 4242, "kind": "bg"})
        self.assertFalse(f(4242))
        self.write("{not json")
        self.assertTrue(f(4242), "unreadable mid-write: err toward keeping a working Claude")
        self.write("[1, 2]")
        self.assertFalse(f(4242), "non-dict")


if __name__ == "__main__":
    unittest.main()
