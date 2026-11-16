"""agent_cli jobs: stub claude/auggie on a temp PATH, a fake aitracker.term_vt in sys.modules, patched running()/
session_state. Nothing real is updated, stopped or started."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import agent_cli as ac
from aitracker import config, pending, update
from aitracker.providers import claude as _claude

STUB = r"""#!/bin/sh
echo "$(pwd -P)|$*" >> "$STUB_LOG"
case "$1" in
--version) echo "$(cat "$STUB_STATE") (stub)";;
doctor) printf '\033[31mdoctor out\033[0m\n'; exit 0;;
update) [ -n "$STUB_RC" ] && exit "$STUB_RC"; [ -n "$STUB_NEW" ] && echo "$STUB_NEW" > "$STUB_STATE"; exit 0;;
stop) [ -n "$STUB_STOP_RC" ] && exit "$STUB_STOP_RC"; exit 0;;
upgrade) [ "$2" = "--skip-confirmation" ] || exit 1; [ -n "$STUB_RC" ] && exit "$STUB_RC"
         [ -n "$STUB_NEW" ] && echo "$STUB_NEW" > "$STUB_STATE"; exit 0;;
esac
"""


def cand(tty, session, version="2.1.323", **kw):
    d = {"tty": tty, "session": session, "relabelled": "", "target": session, "pid": 1000 + len(tty) + ord(tty[-1]),
         "version": version, "status": "busy", "cwd": "/w", "title": "T" + session, "cols": 80, "rows": 24,
         "folder": True, "thin": False, "daemon": False, "job_short": "", "needs_slot": False, "stoppable": True,
         "reason": "", "command": ["claude --resume " + session], "dup_group": [], "primary": True}
    d.update(kw)
    return d


class FakeTV:
    def __init__(self, cands):
        self.cands, self.calls, self.stop_res, self.open_code, self.live = cands, [], {}, 200, 0
        self.reused = False

    def upgrade_candidates(self):
        return [dict(c) for c in self.cands]

    def stop_for_upgrade(self, tty, sid, pid, thin=False):
        self.calls.append(("stop", tty))
        self.log_at_stop = open(self.logpath).read() if getattr(self, "logpath", None) and os.path.exists(self.logpath) else ""
        return dict({"stopped": True, "graceful": True, "confirmed": True, "work_children": 0, "orphans_killed": 0,
                     "error": None}, **self.stop_res.get(tty, {}))

    def open_pty(self, *a):
        pass

    def call_route(self, fn, body):
        assert fn == self.open_pty
        self.calls.append(("open", body))
        if self.open_code != 200:
            return self.open_code, {"error": "bad resume"}
        tty = next(c["tty"] for c in self.cands if c["target"] == body["session"])
        # the real folder landing replies reused=True; "attached" is only set when nothing was typed
        return 200, dict({"tty": tty, "forked": False, "reused": True}, **({"attached": True} if self.reused else {}))

    PTYS = {}
    kids_swept = None

    def _agent_kids(self, pid):
        return [(pid + 1, "lstart")]

    def _agent_sweep(self, kids, shell_pid):
        self.calls.append(("sweep", kids))
        return len(kids)

    def _live_count(self):
        return self.live

    def stops(self):
        return [c[1] for c in self.calls if c[0] == "stop"]

    def opens(self):
        return [c[1] for c in self.calls if c[0] == "open"]


class JobBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        bindir, self.home = os.path.join(self.tmp, "bin"), os.path.join(self.tmp, "home")
        os.makedirs(bindir)
        os.makedirs(self.home)
        for n in ("claude", "auggie"):
            p = os.path.join(bindir, n)
            with open(p, "w") as fh:
                fh.write(STUB)
            os.chmod(p, 0o755)
        self.log, self.state = os.path.join(self.tmp, "log"), os.path.join(self.tmp, "state")
        with open(self.state, "w") as fh:
            fh.write("2.1.323\n")
        env = {"PATH": bindir + ":/usr/bin:/bin", "HOME": self.home, "STUB_LOG": self.log, "STUB_STATE": self.state,
               "STUB_NEW": "2.1.325", "STUB_RC": "", "STUB_STOP_RC": ""}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.envp = os.environ
        self.tv = FakeTV([])
        for p in (mock.patch.dict(sys.modules, {"aitracker.term_vt": self.tv}),
                  mock.patch.object(config, "PENDING_LOCK", os.path.join(self.tmp, "pending.lock")),
                  mock.patch.object(ac, "AGENT_VERIFY_WAIT", 0),
                  mock.patch.object(ac, "session_state", lambda sid, status=None: self.states.get(sid, "idle")),
                  mock.patch.object(ac, "user_line_has", lambda *a, **k: True),
                  mock.patch.object(ac, "transcript_size", lambda sid: 7),
                  mock.patch.object(ac, "all_sessions", lambda: []),
                  mock.patch.object(_claude.ClaudeProvider, "running", lambda s: self.running())):
            p.start()
            self.addCleanup(p.stop)
        self.states, self.run_version, self.extra_running = {}, "2.1.325", []
        ac._AGENT_JOB = None
        ac._AGENT_VERSIONS.clear()
        self.addCleanup(self.wait)

    def running(self):
        rows = [{"id": c["target"], "pid": 90000 + i, "version": self.run_version, "kind": "interactive",
                 "entrypoint": "cli", "job": "", "host": "tui", "state": "idle", "status_raw": "idle", "cwd": "/w",
                 "title": "", "model": ""} for i, c in enumerate(self.tv.cands)]
        return rows + self.extra_running

    def wait(self):
        end = time.time() + 20
        while (ac._AGENT_JOB_LOCK.locked() or ac._AGENT_VLOCK.locked()) and time.time() < end:
            time.sleep(0.02)

    def go(self, agent="claude", action="upgrade", confirm="all"):
        if confirm == "all":      # exactly what the UI sends: the stop[] rows of the warning, never cannot_stop[]
            confirm = [{"tty": r["tty"], "session": r["session"]} for r in ac.agent_plan_upgrade("claude")["stop"]]
        code, body = ac.agent_start(agent, action, confirm)
        self.assertEqual(code, 202, body)
        self.wait()
        return ac._agent_snapshot()

    def logged(self):
        with open(self.log) as fh:
            return fh.read().splitlines()

    @staticmethod
    def items(job):
        return {i["session"]: i for i in job["items"]}


class DaemonPaneTests(JobBase):
    def setUp(self):
        super().setUp()
        self.tv.logpath = self.log
        self.dead = self._dead_pid()
        self.tv.cands = [cand("t1", "DMN", daemon=True, job_short="ab12", pid=4242,
                              command=["claude stop ab12", "claude --resume DMN"])]
        self.extra_running = [{"id": "DMN", "pid": 777, "version": "2.1.323", "kind": "bg", "entrypoint": "cli",
                               "job": "ab12", "host": "daemon", "state": "busy", "status_raw": "busy", "cwd": "/w",
                               "title": "", "model": ""}]
        self.workers = {"ab12": {"pid": self.dead, "replPid": self.dead, "sessionId": "DMN"}}
        for p in (mock.patch.object(ac, "_live_workers", lambda: self.workers),
                  mock.patch.object(ac, "AGENT_DAEMON_STOP_WAIT", 0.5)):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def _dead_pid():
        import subprocess
        p = subprocess.Popen(["true"])
        p.wait()
        return p.pid

    def running(self):      # the daemon row replaces the interactive one for this session
        return list(self.extra_running)

    def test_n_stop_by_short_before_stop_for_upgrade_then_resume(self):
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t1"])
        self.assertIn("|stop ab12", self.tv.log_at_stop)             # the SHORT id, logged before the pane stop
        self.assertNotIn("DMN", "".join(l for l in self.logged() if "|stop" in l))   # never the full session id
        self.assertEqual([self.tv.opens()[0]["session"], self.tv.opens()[0]["mode"]], ["DMN", "resume"])
        self.assertEqual(self.tv.opens()[0]["prompt"], ac.AGENT_RESUME_PROMPT)      # busy daemon job
        self.assertEqual([c[0] for c in self.tv.calls], ["stop", "sweep", "open"])
        self.assertIn(job["items"][0]["outcome"], ("prompted", "unprompted"))
        self.assertTrue(job["items"][0]["daemon"])

    def test_a2_overflow_client_already_gone_is_resumed(self):
        self.tv.cands = [cand("t1", "DMN", daemon=True, job_short="ab12", pid=4242, folder=False,
                              command=["claude stop ab12", "claude --resume DMN"])]
        self.tv.stop_res = {"t1": {"error": "its terminal closed", "closed": True, "confirmed": False}}
        job = self.go()
        self.assertEqual([o["session"] for o in self.tv.opens()], ["DMN"])
        self.assertIn(job["items"][0]["outcome"], ("prompted", "unprompted"))

    def test_nf2_daemon_copies_stop_the_worker_once_and_resume_once(self):
        import subprocess
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (sleeper.poll() is None and sleeper.kill(), sleeper.wait()))
        real_run = ac._run

        def run(argv, timeout, cwd=None):
            r = real_run(argv, timeout, cwd=cwd)
            if argv[1:2] == ["stop"]:
                sleeper.kill()
                sleeper.wait()
            return r
        common = dict(daemon=True, job_short="ab12", target="DMN", dup_group=["t1", "t2"], thin=True,
                      command=["claude stop ab12", "claude --resume DMN"])
        self.tv.cands = [cand("t1", "DMN", primary=True, pid=4242, **common),
                         cand("t2", "DMN", primary=False, pid=4343, **common)]
        roster = lambda: {"ab12": {"pid": sleeper.pid, "replPid": sleeper.pid}} if sleeper.poll() is None else {}
        with mock.patch.object(ac, "_live_workers", roster), mock.patch.object(ac, "_run", run), \
             mock.patch.object(ac, "AGENT_DAEMON_STOP_WAIT", 1):
            job = self.go()
        self.assertEqual(len([l for l in self.logged() if "|stop" in l]), 1)
        self.assertEqual(self.tv.stops(), ["t1", "t2"])
        self.assertEqual([o["session"] for o in self.tv.opens()], ["DMN"])
        its = {i["tty"]: i for i in job["items"]}
        self.assertEqual(its["t2"]["outcome"], "closed")

    def test_n_stop_rc1_touches_nothing_else(self):
        self.envp["STUB_STOP_RC"] = "1"
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual((job["items"][0]["outcome"], job["items"][0]["detail"]), ("failed", ac.AGENT_DAEMON_STOP_FAILED))

    def test_n_restart_flag_off_is_cannot_stop(self):
        with mock.patch.object(ac, "AGENT_RESTART_DAEMON", False):
            job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual(job["items"][0]["detail"], ac.AGENT_REASON_DAEMON)
        self.assertEqual(job["items"][0]["command"], ["claude stop ab12", "claude --resume DMN"])

    def test_n_no_worker_in_roster_fails_untouched(self):
        self.workers = {}
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual(job["items"][0]["detail"], ac.AGENT_REASON_NOJOB)
        self.assertFalse([l for l in self.logged() if "|stop" in l])   # `claude stop` never ran

    def test_n2_roster_reads_empty_but_worker_alive_is_unconfirmed(self):
        import subprocess
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        calls = []

        def roster():            # recorded before the stop, then an unreadable/empty roster
            calls.append(1)
            return {"ab12": {"pid": sleeper.pid, "replPid": sleeper.pid}} if len(calls) == 1 else {}
        with mock.patch.object(ac, "_live_workers", roster):
            job = self.go()
        self.assertTrue([l for l in self.logged() if l.endswith("|stop ab12")])
        self.assertEqual(self.tv.calls, [])                            # no pane stop, no open
        self.assertEqual(job["items"][0]["outcome"], "unconfirmed")


class UpgradeFlowTests(JobBase):
    def test_a_update_failure_stops_nothing(self):
        self.tv.cands = [cand("t1", "S1")]
        self.envp["STUB_RC"] = "1"
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual(job["state"], "failed")
        self.assertIn("no session was stopped", job["summary"])
        self.assertIn("Still on 2.1.323", job["summary"])

    def test_b_success_stop_then_open_in_sequence_resume_only(self):
        self.tv.cands = [cand("t1", "S1"), cand("t2", "S2")]
        job = self.go()
        self.assertEqual(job["state"], "done", job)
        self.assertEqual([c[0] for c in self.tv.calls], ["stop", "open", "stop", "open"])
        self.assertEqual(self.tv.stops(), ["t1", "t2"])
        for body in self.tv.opens():
            self.assertEqual(body["mode"], "resume")
        self.assertFalse(any(b.get("mode") == "new" for b in self.tv.opens()))
        self.assertIn("Claude Code 2.1.323 → 2.1.325.", job["summary"])
        self.assertTrue(all(i["on_version"] is True for i in job["items"]))

    def test_c_prompt_only_for_busy(self):
        self.tv.cands = [cand("t1", "SB"), cand("t2", "SW"), cand("t3", "SI"), cand("t4", "SK")]
        self.states = {"SB": "busy", "SW": "waiting", "SI": "idle", "SK": "idle"}
        self.tv.stop_res = {"t4": {"work_children": 2}}
        job = self.go()
        bodies = {b["session"]: b for b in self.tv.opens()}
        self.assertEqual(bodies["SB"]["prompt"], ac.AGENT_RESUME_PROMPT)
        self.assertEqual(bodies["SW"]["prompt"], ac.AGENT_RESUME_PROMPT)
        self.assertNotIn("prompt", bodies["SI"])
        self.assertEqual(bodies["SK"]["prompt"], ac.AGENT_RESUME_PROMPT)
        self.assertIn("Resumed with “continue, re-read CLAUDE.md” (were working or waiting)", job["summary"])
        self.assertIn("Resumed without a prompt (were idle): TSI.", job["summary"])
        self.assertTrue(self.items(job)["SB"]["prompt_seen"])
        self.assertEqual(self.items(job)["SB"]["size_before"], 7)

    def test_d_already_current_is_not_stopped(self):
        self.tv.cands = [cand("t1", "S1", version="2.1.325"), cand("t2", "S2")]
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t2"])
        self.assertEqual(self.items(job)["S1"]["outcome"], "current")
        self.assertIn("Already on 2.1.325, left running: TS1.", job["summary"])

    def test_e_unconfirmed_pair_not_stopped(self):
        self.tv.cands = [cand("t1", "S1"), cand("t2", "S2")]
        job = self.go(confirm=[{"tty": "t1", "session": "S1"}, {"tty": "t2", "session": "WRONG"}])
        self.assertEqual(self.tv.stops(), ["t1"])
        it = self.items(job)["S2"]
        self.assertEqual((it["outcome"], it["detail"]), ("not_shown", ac.AGENT_NOT_SHOWN))
        self.assertIn(ac.AGENT_NOT_SHOWN, job["summary"])

    def test_f_not_stoppable_never_stopped(self):
        self.tv.cands = [cand("t1", "S1", stoppable=False, reason="folder gone")]
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual((job["items"][0]["outcome"], job["items"][0]["detail"]), ("not_restarted", "folder gone"))
        self.assertIn("run `claude --resume S1`", job["summary"])

    def test_g_unconfirmed_stop_is_not_resumed(self):
        self.tv.cands = [cand("t1", "S1")]
        self.tv.stop_res = {"t1": {"confirmed": False}}
        job = self.go()
        self.assertEqual(self.tv.opens(), [])
        self.assertEqual(job["items"][0]["outcome"], "unconfirmed")
        self.assertIn(ac.AGENT_UNCONFIRMED, job["summary"])

    def test_g2_stop_error_is_failed_and_not_resumed(self):
        self.tv.cands = [cand("t1", "S1")]
        self.tv.stop_res = {"t1": {"error": "its terminal closed", "confirmed": False}}
        job = self.go()
        self.assertEqual(self.tv.opens(), [])
        self.assertEqual((job["items"][0]["outcome"], job["items"][0]["detail"]), ("failed", "its terminal closed"))

    def test_h_open_400_is_failed_with_command(self):
        self.tv.cands = [cand("t1", "S1")]
        self.tv.open_code = 400
        job = self.go()
        self.assertEqual(job["items"][0]["outcome"], "failed")
        self.assertIn("bad resume", job["summary"])
        self.assertIn("run `claude --resume S1`", job["summary"])

    def test_o_summary_is_logged(self):
        self.tv.cands = [cand("t1", "S1")]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            job = self.go()
        self.assertIn("ai-tracker: agent upgrade: " + job["summary"], buf.getvalue())
        self.assertIn("if this dashboard dies, resume it with: claude --resume S1", buf.getvalue())

    def test_p_d8_nothing_installed_restarts_only_older(self):
        self.envp["STUB_NEW"] = ""
        with open(self.state, "w") as fh:
            fh.write("2.1.325\n")
        self.tv.cands = [cand("t1", "OLD", version="2.1.323"), cand("t2", "CUR", version="2.1.325"),
                         cand("t3", "UNK", version="")]
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t1"])
        self.assertEqual(self.items(job)["UNK"]["outcome"], "current")
        self.assertEqual(self.items(job)["UNK"]["detail"], ac.AGENT_VER_UNKNOWN_SKIPPED)
        self.assertIn("is already on 2.1.325; nothing new was installed.", job["summary"])
        # with a newer version installed the unknown one IS restarted
        self.tv.calls.clear()
        self.envp["STUB_NEW"] = "2.1.326"
        self.go()
        self.assertEqual(self.tv.stops(), ["t1", "t2", "t3"])

    def test_s_no_free_slot_stops_nothing(self):
        self.tv.cands = [cand("t1", "S1", needs_slot=True)]
        self.tv.live = config.MAX_TERMS
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual((job["items"][0]["outcome"], job["items"][0]["detail"]), ("failed", ac.AGENT_NO_SLOT))

    def test_t_pending_scan_lock_stops_nothing(self):
        self.tv.cands = [cand("t1", "S1")]
        with pending._pending_lock() as got:
            self.assertTrue(got)
            job = self.go()
        self.assertEqual(self.tv.calls, [])
        self.assertEqual((job["state"], job["summary"]), ("failed", ac.AGENT_FAIL_SCAN))

    def test_k_verify_shared_deadline_and_mismatch(self):
        class Clock:
            now = 1000.0

            def time(self):
                return self.now

            def sleep(self, s):
                self.now += s
                if self.now - 1000.0 > 1000:
                    raise AssertionError("verify did not stop at its deadline")
        clk = Clock()
        job = {"agent": "claude", "items": [ac._agent_item(cand("t%d" % i, "S%d" % i), "prompted") for i in range(3)]}
        with mock.patch.object(ac, "AGENT_VERIFY_WAIT", 90), mock.patch.object(ac, "time", clk):
            ac._agent_verify(job, "2.1.325", clk.time() + ac.AGENT_VERIFY_WAIT)
        # ONE shared deadline for all 3 unsettled items: a per-item deadline would take 270 s
        self.assertTrue(90 <= clk.now - 1000.0 <= 92, clk.now - 1000.0)
        for it in job["items"]:
            self.assertIn(ac.AGENT_NOT_CONFIRMED % "2.1.325", it["detail"])
        # an older version on the resumed process is reported
        self.tv.cands = [cand("t1", "S1")]
        self.run_version = "2.1.300"
        job = {"agent": "claude", "items": [ac._agent_item(cand("t1", "S1"), "unprompted")]}
        ac._agent_verify(job, "2.1.325", time.time())
        self.assertIs(job["items"][0]["on_version"], False)
        self.assertIn(ac.AGENT_VERSION_MISMATCH % ("2.1.300", "2.1.325"), job["items"][0]["detail"])

    def test_verify_flags_reattached_daemon(self):
        self.tv.cands = []
        self.extra_running = [{"id": "S1", "pid": 5, "version": "2.1.325", "kind": "bg", "host": "daemon", "job": "ab12"}]
        job = {"agent": "claude", "items": [ac._agent_item(cand("t1", "S1"), "unprompted")]}
        ac._agent_verify(job, "2.1.325", time.time())
        self.assertIs(job["items"][0]["on_version"], True)
        self.assertIn(ac.AGENT_STILL_DAEMON, job["items"][0]["detail"])


class OutcomeTests(JobBase):
    """A1/B-SF3, A3 (D16), A5/B-SF4, B-SF2 resume reuse, N6, N8."""

    def test_a1_cannot_stop_row_reported_by_its_reason_with_ui_confirm(self):
        self.tv.cands = [cand("t1", "S1"), cand("t3", "S3", stoppable=False, reason="its folder no longer exists")]
        confirm = [{"tty": r["tty"], "session": r["session"]} for r in ac.agent_plan_upgrade("claude")["stop"]]
        self.assertEqual(confirm, [{"tty": "t1", "session": "S1"}])        # the UI never confirms cannot_stop rows
        job = self.go(confirm=confirm)
        it = self.items(job)["S3"]
        self.assertEqual((it["outcome"], it["detail"]), ("not_restarted", "its folder no longer exists"))
        self.assertNotIn(ac.AGENT_NOT_SHOWN, job["summary"])
        self.assertIn("Not restarted: TS3 — its folder no longer exists", job["summary"])
        self.assertNotIn("Failed: TS3", job["summary"])
        self.assertEqual(self.tv.stops(), ["t1"])

    def test_a3_newer_than_installed_is_left_running(self):
        self.tv.cands = [cand("t1", "NEW", version="2.1.326"), cand("t2", "OLD", version="2.1.323")]
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t2"])
        it = self.items(job)["NEW"]
        self.assertEqual((it["outcome"], it["detail"]), ("current", ac.AGENT_VER_NEWER.format(v="2.1.326", i="2.1.325")))

    def test_a5_prompt_not_in_transcript_is_reported(self):
        self.tv.cands = [cand("t1", "S1")]
        self.states = {"S1": "busy"}
        with mock.patch.object(ac, "user_line_has", lambda *a, **k: False):
            job = self.go()
        it = self.items(job)["S1"]
        self.assertIs(it["prompt_seen"], False)
        self.assertIn(ac.AGENT_PROMPT_NOT_SEEN, it["detail"])
        self.assertIn(ac.AGENT_PROMPT_NOT_SEEN, job["summary"])
        self.assertIn("Prompt not seen yet: TS1", job["summary"])
        self.assertNotIn("Not confirmed on", job["summary"])

    def test_reused_pane_is_a_failure_never_resumed(self):
        self.tv.cands = [cand("t1", "S1")]
        self.tv.reused = True
        job = self.go()
        it = self.items(job)["S1"]
        self.assertEqual((it["outcome"], it["detail"]), ("failed", ac.AGENT_RESUME_REUSED % "t1"))
        self.assertNotIn("Resumed", job["summary"])

    def test_n6_dedicated_pane_at_the_cap_frees_its_own_slot(self):
        self.tv.cands = [cand("t1", "S1", needs_slot=True, folder=False)]
        self.tv.live = config.MAX_TERMS
        self.go()
        self.assertEqual(self.tv.stops(), ["t1"])

    def test_n8_unknown_running_version_is_not_a_mismatch(self):
        self.tv.cands = [cand("t1", "S1")]
        self.run_version = ""
        job = self.go()
        d = self.items(job)["S1"]["detail"]
        self.assertNotIn("resumed on v", d)
        self.assertIn(ac.AGENT_NOT_CONFIRMED % "2.1.325", d)


class DuplicateGroupTests(JobBase):
    """D15: the same session in two tracker terminals: stop every copy, resume once in the primary's terminal."""

    def setUp(self):
        super().setUp()
        self.tv.cands = [cand("t1", "S1", dup_group=["t1", "t2"], primary=True),
                         cand("t2", "S1", dup_group=["t1", "t2"], primary=False)]
        self.tv.cands[1]["pid"] += 7

    def test_stops_every_copy_resumes_once(self):
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t1", "t2"])
        self.assertEqual([o["session"] for o in self.tv.opens()], ["S1"])      # ONE resume
        self.assertEqual([c[0] for c in self.tv.calls], ["stop", "stop", "open"])
        its = {i["tty"]: i for i in job["items"]}
        self.assertIn(its["t1"]["outcome"], ("prompted", "unprompted"))
        self.assertEqual((its["t2"]["outcome"], its["t2"]["detail"]), ("closed", ac.AGENT_DUP_CLOSED % "t1"))
        self.assertIn(ac.AGENT_DUP_CLOSED % "t1", job["summary"])

    def test_confirm_naming_only_some_copies_stops_none(self):
        job = self.go(confirm=[{"tty": "t1", "session": "S1"}])
        self.assertEqual(self.tv.calls, [])
        self.assertEqual({i["outcome"] for i in job["items"]}, {"not_shown"})
        self.assertEqual(len(job["items"]), 2)
        its = {i["tty"]: i for i in job["items"]}
        self.assertEqual(its["t1"]["detail"], ac.AGENT_DUP_PARTIAL % "t2")
        self.assertEqual(its["t2"]["detail"], ac.AGENT_NOT_SHOWN)

    def test_exception_in_a_group_reports_every_copy(self):
        def boom(fn, body):
            raise RuntimeError("kaboom")
        self.tv.call_route = boom
        job = self.go()
        self.assertEqual(sorted((i["tty"], i["outcome"], i["detail"]) for i in job["items"]),
                         [("t1", "failed", "kaboom"), ("t2", "failed", "kaboom")])

    def test_unconfirmed_copy_resumes_none_and_reports_each_copy_truthfully(self):
        self.tv.stop_res = {"t2": {"confirmed": False}}
        job = self.go()
        self.assertEqual(self.tv.opens(), [])
        self.assertEqual(self.tv.stops(), ["t1", "t2"])
        its = {i["tty"]: i for i in job["items"]}
        self.assertEqual(its["t1"]["detail"], ac.AGENT_DUP_NOT_RESUMED % "t2")     # t1 WAS confirmed stopped
        self.assertEqual(its["t2"]["detail"], ac.AGENT_UNCONFIRMED)

    def test_failed_primary_stop_leaves_the_other_copies_running(self):
        self.tv.stop_res = {"t1": {"confirmed": False}}
        job = self.go()
        self.assertEqual(self.tv.stops(), ["t1"])                                  # t2 is never stopped
        self.assertEqual(self.tv.opens(), [])
        its = {i["tty"]: i for i in job["items"]}
        self.assertEqual(its["t1"]["detail"], ac.AGENT_UNCONFIRMED)
        self.assertEqual(its["t2"]["detail"], ac.AGENT_DUP_BLOCKED % "t1")

    def test_failed_resume_fails_the_closed_copy_too(self):
        self.tv.open_code = 400
        job = self.go()
        self.assertEqual({i["outcome"] for i in job["items"]}, {"failed"})
        self.assertNotIn("closed", {i["outcome"] for i in job["items"]})

    def test_copy_that_cannot_be_stopped_blocks_the_group(self):
        self.tv.cands[1].update(stoppable=False, reason="its folder no longer exists")
        plan = ac.agent_plan_upgrade("claude")
        self.assertEqual(plan["stop"], [])                                         # the warning promises no stop
        self.assertEqual({r["tty"]: r["reason"] for r in plan["cannot_stop"]},
                         {"t1": ac.AGENT_DUP_BLOCKED % "t2", "t2": "its folder no longer exists"})
        job = self.go()
        self.assertEqual(self.tv.calls, [])
        its = {i["tty"]: i for i in job["items"]}
        self.assertEqual(its["t1"]["detail"], ac.AGENT_DUP_BLOCKED % "t2")
        self.assertEqual(its["t2"]["detail"], "its folder no longer exists")

    def test_warning_row_for_the_non_primary_copy(self):
        rows = {r["tty"]: r for r in ac.agent_plan_upgrade("claude")["stop"]}
        self.assertEqual(sorted(rows), ["t1", "t2"])                          # both are in stop[], not cannot_stop[]
        self.assertEqual(rows["t2"]["dup_text"], ac.AGENT_DUP_WARN % "t1")
        self.assertTrue(rows["t2"]["dup_text"].endswith("comes back once, in a tracker terminal"))   # never names the landing
        self.assertNotIn("t1,", ac.AGENT_DUP_WARN % "t1")
        self.assertNotIn("dup_text", rows["t1"])


class StartAndLockTests(JobBase):
    def test_i_locks_and_thread_failure(self):
        self.assertTrue(ac._AGENT_JOB_LOCK.acquire(blocking=False))
        try:
            code, body = ac.agent_start("claude", "doctor", None)
            self.assertEqual(code, 409)
            self.assertIn("already running", body["error"])
            code, body = update.update_apply()      # the other side of the lock
            self.assertEqual(code, 409)
            self.assertIn("agent upgrade", body["error"])
        finally:
            ac._AGENT_JOB_LOCK.release()
        self.assertTrue(update._APPLY.acquire(blocking=False))
        try:
            code, body = ac.agent_start("claude", "doctor", None)
            self.assertEqual(code, 409)
            self.assertIn("updating itself", body["error"])
            self.assertFalse(ac._AGENT_JOB_LOCK.locked())
        finally:
            update._APPLY.release()
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no threads")):
            code, body = ac.agent_start("claude", "doctor", None)
        self.assertEqual(code, 500)
        self.assertFalse(ac._AGENT_JOB_LOCK.locked())

    def test_j_bad_input_is_400_and_requests_never_reach_argv(self):
        self.assertEqual(ac.agent_start("nope", "doctor", None)[0], 400)
        self.assertEqual(ac.agent_start("claude", "rm", None)[0], 400)
        self.assertEqual(ac.agent_start("auggie", "doctor", None)[0], 400)      # no doctor
        for bad in ("x", [1], [{"tty": 1, "session": "s"}], [{"tty": "t"}], [{"tty": "t", "session": "s"}] * 65):
            self.assertEqual(ac.agent_start("claude", "upgrade", bad)[0], 400, bad)
        self.assertFalse(ac._AGENT_JOB_LOCK.locked())
        self.tv.cands = [cand("t1", "S1")]
        job = self.go(confirm=[{"tty": "; touch /tmp/pwn", "session": "$(evil)"}])
        self.assertEqual(job["state"], "done")
        text = "\n".join(self.logged())
        self.assertNotIn("pwn", text)
        self.assertNotIn("evil", text)

    def test_l_doctor_cwd_home_and_output_stripped(self):
        job = self.go(action="doctor", confirm=None)
        self.assertEqual((job["state"], job["summary"], job["output"]), ("done", ac.AGENT_DOCTOR_DONE, "doctor out\n"))
        self.assertEqual(self.logged(), [os.path.realpath(self.home) + "|doctor"])

    def test_l2_upgrade_commands_run_in_home(self):
        self.go()
        for line in self.logged():
            self.assertTrue(line.startswith(os.path.realpath(self.home) + "|"), line)
        self.assertEqual([l.split("|")[1] for l in self.logged()], ["--version", "update", "--version"])

    def test_m_auggie_flag_no_restart_and_failure_text(self):
        self.tv.cands = [cand("t1", "S1")]
        self.envp["STUB_NEW"] = "2.1.325"
        job = self.go("auggie", confirm=None)
        self.assertEqual(self.tv.calls, [])
        self.assertIn("upgrade --skip-confirmation", self.logged()[1])
        self.assertEqual(job["state"], "done")
        self.assertIn(ac.AGENT_MSG_NO_RESTART, job["summary"])
        self.envp["STUB_RC"] = "1"
        job = self.go("auggie", confirm=None)
        self.assertEqual(job["state"], "failed")
        self.assertEqual(job["summary"], ac.AGENT_FAIL_UPDATE_NODOC.format(label="Auggie") + ac.AGENT_STILL_ON.format(old="2.1.325"))
        self.assertNotIn("Doctor", job["summary"])

    def test_version_unreadable_fails_without_changes(self):
        with open(self.state, "w") as fh:
            fh.write("garbage\n")
        job = self.go()
        self.assertEqual(job["state"], "failed")
        self.assertEqual(job["summary"], ac.AGENT_FAIL_VERSION.format(bin="claude"))
        self.assertEqual([l.split("|")[1] for l in self.logged()], ["--version"])    # update never ran


class PlanAndStatusTests(JobBase):
    def test_q_warning_rows_carry_version_text_and_daemon_rows_split(self):
        ac._AGENT_VERSIONS["claude"] = {"version": "2.1.325", "checked_at": time.time(), "error": ""}
        self.tv.cands = [cand("t1", "OLD", version="2.1.323", relabelled="abcdef123456"),
                         cand("t2", "CUR", version="2.1.325"), cand("t3", "UNK", version=""),
                         cand("t4", "DMN", daemon=True, job_short="ab12",
                              command=["claude stop ab12", "claude --resume DMN"])]
        self.states = {"OLD": "busy", "CUR": "idle", "UNK": ""}
        with mock.patch.object(ac, "AGENT_RESTART_DAEMON", False):
            plan = ac.agent_plan_upgrade("claude")
        rows = {r["session"]: r for r in plan["stop"]}
        self.assertEqual(rows["OLD"]["version_text"], ac.AGENT_VER_OLD.format(v="2.1.323", i="2.1.325"))
        self.assertEqual(rows["CUR"]["version_text"], ac.AGENT_VER_CURRENT.format(i="2.1.325"))
        self.assertEqual(rows["UNK"]["version_text"], ac.AGENT_VER_UNKNOWN)
        self.assertTrue(rows["OLD"]["state_text"].startswith(ac.AGENT_STATE_BUSY))
        self.assertTrue(rows["OLD"]["state_text"].endswith(ac.AGENT_STATE_KIDS))
        self.assertEqual(rows["OLD"]["relabelled_text"], ac.AGENT_RELABELLED % "abcdef12")
        self.assertIn(ac.AGENT_STATE_UNKNOWN, rows["UNK"]["state_text"])
        self.assertIn("will be stopped", plan["message"])
        self.assertIn("updates itself in the background", plan["note"])
        self.assertEqual([r["session"] for r in plan["cannot_stop"]], ["DMN"])      # flag off
        self.assertEqual(plan["cannot_stop"][0]["reason"], ac.AGENT_REASON_DAEMON)
        self.assertEqual(plan["cannot_stop"][0]["command"], ["claude stop ab12", "claude --resume DMN"])
        plan = ac.agent_plan_upgrade("claude")                   # default True (S5)
        self.assertTrue(ac.AGENT_RESTART_DAEMON)
        dm = next(r for r in plan["stop"] if r["session"] == "DMN")
        self.assertIn("comes back as a session in this tracker terminal", dm["state_text"])

    def test_plan_auggie_and_unknown(self):
        self.tv.cands = [cand("t1", "S1")]
        plan = ac.agent_plan_upgrade("auggie")
        self.assertEqual((plan["message"], plan["stop"], plan["cannot_stop"]), (ac.AGENT_MSG_NO_RESTART, [], []))
        self.assertEqual(plan["note"], "")
        self.assertIsNone(ac.agent_plan_upgrade("nope"))
        self.tv.cands = []
        self.assertEqual(ac.agent_plan_upgrade("claude")["message"], ac.AGENT_MSG_NO_STOP)

    def test_status_reads_versions_in_a_thread(self):
        st = ac.agent_status()
        self.assertTrue(all(a["checking"] for a in st["agents"]))
        end = time.time() + 10
        while "auggie" not in ac._AGENT_VERSIONS and time.time() < end:
            time.sleep(0.02)
        self.wait()
        st = ac.agent_status()
        rows = {a["id"]: a for a in st["agents"]}
        self.assertEqual(rows["claude"]["installed"], "2.1.323")
        self.assertTrue(rows["claude"]["can_doctor"] and rows["claude"]["can_upgrade"])
        self.assertFalse(rows["auggie"]["can_doctor"])
        self.assertIn("updates itself", rows["claude"]["note"])
        self.assertEqual(rows["auggie"]["note"], "")
        self.assertIsNone(st["job"])

    def test_status_missing_binary(self):
        with mock.patch.dict(os.environ, {"PATH": self.tmp}):
            st = ac.agent_status()
        for a in st["agents"]:
            self.assertFalse(a["can_upgrade"])
            self.assertIn("not found on the tracker's PATH", a["error"])

    def test_r2_snapshot_and_set_take_the_job_lock(self):
        # json.dumps runs under the GIL, so the mutation race cannot be provoked reliably; pin the lock itself.
        ac._AGENT_JOB = {"items": [], "state": "running"}
        for fn in (ac._agent_snapshot, lambda: ac._agent_set(ac._AGENT_JOB, step="x")):
            done = threading.Event()
            t = threading.Thread(target=lambda: (fn(), done.set()))
            with ac._AGENT_JLOCK:
                t.start()
                self.assertFalse(done.wait(0.3))
            self.assertTrue(done.wait(5))
            t.join()

    def test_r_snapshot_is_safe_while_a_job_mutates(self):
        item = ac._agent_item(cand("t1", "S1"), "prompted")
        job = {"id": 1, "agent": "claude", "action": "upgrade", "state": "running", "step": "", "started": 0,
               "finished": None, "old": None, "new": None, "output": "", "items": [item], "outside": [], "summary": ""}
        ac._AGENT_JOB = job
        stop = threading.Event()

        def churn():
            i = 0
            while not stop.is_set():
                i += 1
                ac._agent_set(job, **{"extra%d" % (i % 3000): i})
                ac._agent_set(item, detail=str(i), on_version=bool(i % 2))
        t = threading.Thread(target=churn)
        t.start()
        try:
            for _ in range(500):
                for it in ac.agent_status()["job"]["items"]:
                    self.assertEqual(set(it), set(ac._AGENT_ITEM_KEYS))
        finally:
            stop.set()
            t.join()


if __name__ == "__main__":
    unittest.main()
