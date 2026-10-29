"""Claude Code background jobs blocked on the user ("Needs input", ~/.claude/jobs/<id>/state.json
state == "blocked") must surface as waiting + a "⧖ <question>" now_line, via the real list_sessions()
and parse_session(); a done job and a job dir with no state.json must not."""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config
from aitracker.providers import claude
from aitracker.providers.claude import list_sessions, parse_session


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _job(jdir, name, state=None):
    d = os.path.join(jdir, name)
    os.makedirs(d)
    if state is not None:
        with open(os.path.join(d, "state.json"), "w") as fh:
            json.dump(state, fh)


def _dead_pid():
    """A pid that is certainly not running: a reaped child."""
    import subprocess
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _write_roster(path, shorts, supervisor=None, pid=None, raw=None):
    """SYNTHETIC roster only -- the real ~/.claude/daemon/roster.json holds secrets and is never read."""
    me = os.getpid()
    if raw is None:
        raw = {"proto": 1, "supervisorPid": me if supervisor is None else supervisor,
               "workers": {sh: {"pid": me if pid is None else pid, "ptyAuth": "x"} for sh in shorts}}
    with open(path, "w") as fh:
        json.dump(raw, fh)


class BlockedJobWaitingTests(unittest.TestCase):
    def setUp(self):
        self._snap = (config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER)
        self.pdir = tempfile.mkdtemp()
        self.jdir = tempfile.mkdtemp()
        self.rdir = tempfile.mkdtemp()
        self.roster = os.path.join(self.rdir, "roster.json")
        config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER = self.pdir, self.jdir, self.roster
        self.live = ["aaa111", "bbb222"]
        _write_roster(self.roster, self.live)
        sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(sdir)
        self.paths = {}
        for sid in ("s_blocked", "s_done"):
            self.paths[sid] = os.path.join(sdir, sid + ".jsonl")
            _write_jsonl(self.paths[sid], [
                {"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
                 "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "working on it"}]}},
            ])
        _job(self.jdir, "aaa111", {"state": "blocked", "needs": "pick A or B", "sessionId": "s_blocked"})
        _job(self.jdir, "bbb222", {"state": "done", "sessionId": "s_done"})
        _job(self.jdir, "ccc333")   # no state.json

    def tearDown(self):
        config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER = self._snap
        shutil.rmtree(self.pdir, ignore_errors=True)
        shutil.rmtree(self.jdir, ignore_errors=True)
        shutil.rmtree(self.rdir, ignore_errors=True)

    def test_list_sessions(self):
        by_id = {r["id"]: r for r in list_sessions()}
        self.assertTrue(by_id["s_blocked"]["waiting"])
        self.assertIn("pick A or B", by_id["s_blocked"]["now_line"])
        self.assertFalse(by_id["s_done"]["waiting"])
        self.assertNotIn("⧖", by_id["s_done"]["now_line"])
        self.assertIn("pick A or B", by_id["s_blocked"]["needs"])
        self.assertEqual(by_id["s_done"]["needs"], "")

    def test_parse_session_detail(self):
        self.assertTrue(parse_session(self.paths["s_blocked"])["waiting"])
        self.assertFalse(parse_session(self.paths["s_done"])["waiting"])

    def test_detail_overview_now_shows_question(self):
        self.assertIn("pick A or B", parse_session(self.paths["s_blocked"])["overview"]["now"])

    def _extra(self, sid, state):
        p = os.path.join(self.pdir, "-tmp-proj", sid + ".jsonl")
        _write_jsonl(p, [{"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
                          "message": {"role": "user", "content": "go"}}])
        _job(self.jdir, "x_" + sid, dict(state, state="blocked", sessionId=sid))
        _write_roster(self.roster, self.live + ["x_" + sid])
        return {r["id"]: r for r in list_sessions()}[sid]

    def test_long_needs_truncated_single_line(self):
        row = self._extra("s_long", {"needs": ("word " * 20).strip() + "\n" + "tail " * 20})
        self.assertNotIn("\n", row["now_line"])
        self.assertLessEqual(len(row["now_line"]), 62)

    def test_detail_only_not_used(self):
        row = self._extra("s_det", {"detail": "<bash-stdout>junk</bash-stdout>"})
        self.assertNotIn("junk", row["now_line"])
        self.assertIn("needs your input", row["now_line"])

    # --- liveness narrowing (RED proofs) ---
    def _waiting(self, sid="s_blocked"):
        return {r["id"]: r for r in list_sessions()}[sid]["waiting"]

    def test_dead_job_not_waiting(self):
        _write_roster(self.roster, ["bbb222"])          # aaa111 (blocked) is not a live worker
        self.assertFalse(self._waiting())
        self.assertEqual(claude._blocked_jobs(), {})

    def test_missing_roster_nothing_waiting(self):
        os.remove(self.roster)
        self.assertEqual(claude._live_daemon_shorts(), set())
        self.assertFalse(self._waiting())

    def test_dead_supervisor_roster_is_stale(self):
        _write_roster(self.roster, self.live, supervisor=_dead_pid())
        self.assertEqual(claude._live_daemon_shorts(), set())
        self.assertFalse(self._waiting())

    def test_dead_worker_pid_not_waiting(self):
        _write_roster(self.roster, self.live, pid=_dead_pid())
        self.assertFalse(self._waiting())

    def test_supervisor_pid_zero_or_negative_is_dead(self):
        for bad in (0, -1, -os.getpid()):
            _write_roster(self.roster, self.live, supervisor=bad)
            self.assertEqual(claude._live_daemon_shorts(), set(), bad)
            self.assertFalse(claude._pid_alive(bad))

    # --- guards ---
    def test_malformed_roster_no_crash(self):
        for raw in ("not json{", "[]", '{"workers": []}', '{"supervisorPid": %d, "workers": "x"}' % os.getpid(), ""):
            with open(self.roster, "w") as fh:
                fh.write(raw)
            self.assertEqual(claude._live_daemon_shorts(), set(), raw)
            self.assertEqual(claude._blocked_jobs(), {})

    def test_non_int_pid_no_crash(self):
        for bad in ("123", 1.5, True, None, [1], 10 ** 40):
            _write_roster(self.roster, None, raw={"supervisorPid": os.getpid(),
                          "workers": {"aaa111": {"pid": bad}, "bbb222": "junk"}})
            self.assertEqual(claude._live_daemon_shorts(), set(), bad)
            self.assertFalse(claude._pid_alive(bad))
        self.assertTrue(claude._pid_alive(os.getpid()))

    def test_live_worker_dir_without_state_json_ignored(self):
        _write_roster(self.roster, self.live + ["ccc333", "nodir999"])   # ccc333: dir w/o state; nodir999: no dir
        self.assertEqual(set(claude._blocked_jobs()), {"s_blocked"})

    def test_resume_session_id_maps_when_live(self):
        _job(self.jdir, "ddd444", {"state": "blocked", "needs": "q", "sessionId": "sid1", "resumeSessionId": "rs1"})
        _write_roster(self.roster, self.live + ["ddd444"])
        got = claude._blocked_jobs()
        self.assertEqual((got["sid1"], got["rs1"]), ("q", "q"))

    def test_daemonshort_mismatch_skipped(self):
        _job(self.jdir, "eee555", {"state": "blocked", "needs": "q", "sessionId": "sid2", "daemonShort": "other"})
        _write_roster(self.roster, self.live + ["eee555"])
        self.assertNotIn("sid2", claude._blocked_jobs())

    def test_non_string_needs_does_not_sink_the_list(self):
        for needs in ({"question": "q"}, 123, ["a"]):
            with self.subTest(needs=needs):
                with open(os.path.join(self.jdir, "aaa111", "state.json"), "w") as fh:
                    json.dump({"state": "blocked", "needs": needs, "sessionId": "s_blocked"}, fh)
                by_id = {r["id"]: r for r in list_sessions()}
                self.assertEqual({"s_blocked", "s_done"}, set(by_id))
                self.assertTrue(by_id["s_blocked"]["waiting"])
                if isinstance(needs, dict):
                    self.assertIn("q", by_id["s_blocked"]["now_line"])
                parse_session(self.paths["s_blocked"])   # must not raise

    def test_roster_key_with_path_traversal_is_ignored(self):
        _write_roster(self.roster, ["../x"])
        os.makedirs(os.path.join(self.jdir, "..", "x"), exist_ok=True)
        xdir = os.path.normpath(os.path.join(self.jdir, "..", "x"))
        self.addCleanup(shutil.rmtree, xdir, True)
        with open(os.path.join(xdir, "state.json"), "w") as fh:
            json.dump({"state": "blocked", "needs": "evil", "sessionId": "s_done"}, fh)
        self.assertEqual(claude._blocked_jobs(), {})


if __name__ == "__main__":
    unittest.main()
