"""S3 of the agent-upgrade feature: the terminal-tier pieces in aitracker/term_vt.py
(`_with_prompt` in the resume arm, `upgrade_candidates`, `stop_for_upgrade`, `_agent_sweep`,
`call_route`). Fake panes use made-up pids with `Pty.kill` stubbed; the real-pty tests only signal
processes they spawned themselves. Run: unset TRACKER_AUTH; python3 -m unittest -q tests.test_term_vt_upgrade
"""
import contextlib
import os
import signal
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, gateway, term_gate, term_vt
from tests import test_folder_terminal as tft

_SID = "11111111-2222-3333-4444-555555555555"


class _Base(unittest.TestCase):
    def setUp(self):
        self._t0, self._a0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._restore)

    def _restore(self):
        config.TERMINAL, config.AUTH = self._t0, self._a0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)


class ResumePromptArgv(_Base):
    def setUp(self):
        super().setUp()
        tft._stub_kill(self)

    def _open(self, body):
        pt = term_vt.Pty(tid="fo1", pid=42424, fd=99, cwd=self._tmpdir)
        pt.folder, pt.session, pt.mode, pt.shell_cmd, pt.startup_done = True, "", "cwd", "sh", True
        term_vt.PTYS["fo1"] = pt
        h = tft._FakeHandler()
        with mock.patch.object(term_gate, "session_cwd", return_value=self._tmpdir), \
             mock.patch.object(term_gate, "resume_argv", return_value=["claude", "--resume", "S"]), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=lambda p: p.pid), \
             mock.patch.object(term_vt, "_inject_argv", return_value=(True, "")) as inj, \
             mock.patch.object(term_vt, "_start_backstop", return_value=False), \
             mock.patch.object(term_vt, "resolve_spawned"):
            term_vt.open_pty(h, None, dict(body, cols=80, rows=24))
        return h.calls[-1], inj

    def test_resume_prompt_reaches_injected_argv(self):
        (obj, code), inj = self._open({"session": "S", "mode": "resume", "prompt": "continue, re-read CLAUDE.md"})
        self.assertEqual(code, 200, obj)
        self.assertEqual(inj.call_args[0][1], ["claude", "--resume", "S", "continue, re-read CLAUDE.md"])

    def test_resume_without_prompt_is_unchanged(self):
        (obj, code), inj = self._open({"session": "S", "mode": "resume"})
        self.assertEqual(code, 200, obj)
        self.assertEqual(inj.call_args[0][1], ["claude", "--resume", "S"])


    def test_nf1_typed_resume_into_idle_folder_shell_is_not_attached(self):
        (obj, code), inj = self._open({"session": "S", "mode": "resume"})
        self.assertTrue(obj.get("reused"))
        self.assertNotIn("attached", obj)
        self.assertTrue(inj.called)

    def test_nf1_agent_resume_counts_typed_landing_as_resumed(self):
        from aitracker import agent_cli as ac
        pt = term_vt.Pty(tid="fo1", pid=42424, fd=99, cwd=self._tmpdir)
        pt.folder, pt.session, pt.mode, pt.shell_cmd, pt.startup_done = True, "", "cwd", "sh", True
        term_vt.PTYS["fo1"] = pt
        cand = {"tty": "fo1", "session": "S", "target": "S", "title": "T", "cols": 80, "rows": 24, "command": []}
        with mock.patch.object(term_gate, "session_cwd", return_value=self._tmpdir), \
             mock.patch.object(term_gate, "resume_argv", return_value=["claude", "--resume", "S"]), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=lambda p: p.pid), \
             mock.patch.object(term_vt, "_inject_argv", return_value=(True, "")), \
             mock.patch.object(term_vt, "_start_backstop", return_value=False), \
             mock.patch.object(term_vt, "resolve_spawned"), \
             mock.patch.object(ac, "transcript_size", lambda s: 0):
            item = ac._agent_resume({"items": []}, term_vt, cand, False)
        self.assertEqual(item["outcome"], "unprompted", item)

    def test_nf1_pane_already_running_the_session_is_attached(self):
        pt = term_vt.Pty(tid="fo1", pid=42424, fd=99, cwd=self._tmpdir)
        pt.folder, pt.shell_cmd, pt.startup_done = True, "sh", True
        pt.fg = {"session": "S", "mode": "resume", "started": time.time(), "grants": {"S"}}
        term_vt.PTYS["fo1"] = pt
        h = tft._FakeHandler()
        with mock.patch.object(term_vt, "_refresh_fg"), \
             mock.patch.object(term_gate, "session_cwd", return_value=self._tmpdir):
            term_vt.open_pty(h, None, {"session": "S", "mode": "resume", "cols": 80, "rows": 24})
        obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        self.assertIs(obj.get("attached"), True)


class UpgradeCandidates(_Base):
    def setUp(self):
        super().setUp()
        tft._stub_kill(self)
        self.runs = []
        self.bg = {}
        self.cwd = {}
        self.argv_err = None
        self.allowed = True
        self.pg = {}

    def pane(self, tid, pid, label=None, cwd=None):
        pt = term_vt.Pty(tid=tid, pid=pid, fd=90 + pid % 7, cwd=cwd or self._tmpdir)
        pt.folder, pt.shell_cmd, pt.startup_done = True, "sh", True
        if label:
            pt.fg = {"session": label, "mode": "resume", "started": time.time(), "grants": {label}}
        term_vt.PTYS[tid] = pt
        self.pg[tid] = pid + 1000        # the foreground pgid of this pane's Claude
        return pt

    def cands(self):
        return self.cands_keep(thin="")

    def cands_keep(self, thin=None):
        cwd_of = lambda sid, resume=False: self.cwd.get(sid, self._tmpdir)

        def resume_argv(sid):
            if self.argv_err:
                raise gateway.GatewayError(self.argv_err)
            return ["claude", "--resume", sid]

        prov = term_vt._provider()
        with mock.patch.object(term_vt, "_reap"), mock.patch.object(term_vt, "_refresh_fg"), \
             mock.patch.object(term_vt, "_foreground_is_claude", return_value=True), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=lambda p: self.pg[p.id]), \
             mock.patch.object(term_vt, "_thin_client_short", return_value="") if thin is not None else contextlib.nullcontext(), \
             mock.patch.object(term_vt, "_background_target", side_effect=lambda s: self.bg.get(s, "")) if thin is not None else contextlib.nullcontext(), \
             mock.patch.object(prov, "running_sessions", return_value=self.runs), \
             mock.patch.object(term_gate, "session_cwd", side_effect=cwd_of), \
             mock.patch.object(term_gate, "allowed", side_effect=lambda: self.allowed), \
             mock.patch.object(term_gate, "resume_argv", side_effect=resume_argv):
            return term_vt.upgrade_candidates()

    def test_labelled_pane_is_stoppable(self):
        self.pane("a", 100, label="X")
        (r,) = self.cands()
        self.assertEqual((r["session"], r["relabelled"], r["target"], r["stoppable"]), ("X", "", "X", True))
        self.assertEqual(r["command"], ["claude --resume X"])
        self.assertEqual(r["pid"], 1100)

    def test_unlabelled_forked_pane_uses_the_pid_file_f7(self):
        self.pane("a", 100)
        self.runs = [{"pid": 1100, "id": "S", "host": "tui", "version": "2.1.1", "status_raw": "idle"}]
        (r,) = self.cands()
        self.assertEqual((r["session"], r["stoppable"], r["version"], r["status"]), ("S", True, "2.1.1", "idle"))

    def test_pid_file_beats_a_stale_label_b2(self):
        self.pane("a", 100, label="X")
        self.runs = [{"pid": 1100, "id": "Y", "host": "tui", "version": "2.1.1", "status_raw": "busy"}]
        (r,) = self.cands()
        self.assertEqual((r["session"], r["relabelled"]), ("Y", "X"))
        self.assertIn("Y", r["command"][0])
        self.assertNotIn("X", r["command"][0])

    def test_pane_without_pid_file_keeps_its_label(self):
        self.pane("a", 100, label="X")
        self.runs = [{"pid": 9999, "id": "Y", "host": "tui"}]      # another pid
        (r,) = self.cands()
        self.assertEqual((r["session"], r["relabelled"]), ("X", ""))

    def test_non_tui_pid_file_does_not_beat_the_label(self):
        self.pane("a", 100, label="X")
        self.runs = [{"pid": 1100, "id": "Y", "host": "daemon", "job": "ab12"}]
        (r,) = self.cands()
        self.assertEqual(r["session"], "X")

    def test_daemon_row_has_job_short_and_two_commands(self):
        self.pane("a", 100, label="X")
        self.bg = {"X": "B"}
        self.runs = [{"pid": 7, "id": "B", "kind": "bg", "host": "daemon", "job": "ab12cd", "version": "2.1.0"}]
        (r,) = self.cands()
        self.assertTrue(r["daemon"])
        self.assertEqual((r["target"], r["job_short"], r["version"], r["stoppable"]), ("B", "ab12cd", "2.1.0", True))
        self.assertEqual(r["command"], ["claude stop ab12cd", "claude --resume B"])

    def test_daemon_without_a_job_short_is_not_stoppable(self):
        self.pane("a", 100, label="X")
        self.bg = {"X": "B"}
        (r,) = self.cands()
        self.assertFalse(r["stoppable"])
        self.assertIn("background job", r["reason"])

    def test_preflight_failures(self):
        self.pane("a", 100, label="X")
        self.argv_err = "no launcher configured"
        (r,) = self.cands()
        self.assertEqual((r["stoppable"], r["reason"], r["command"]), (False, "no launcher configured", []))
        self.argv_err = None
        self.cwd = {"X": ""}
        (r,) = self.cands()
        self.assertEqual((r["stoppable"], r["reason"]), (False, "its folder no longer exists"))
        self.cwd = {}
        self.allowed = False
        (r,) = self.cands()
        self.assertFalse(r["stoppable"])
        self.assertIn("terminals are disabled", r["reason"])

    def test_unknown_session_is_not_stoppable(self):
        self.pane("a", 100)
        (r,) = self.cands()
        self.assertEqual((r["session"], r["stoppable"]), ("", False))

    def test_dedupe_same_target_forms_a_group_d15(self):
        d1, d2 = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.pane("a", 100, label="X", cwd=d1)
        self.pane("b", 101, label="X", cwd=d2)
        r1, r2 = self.cands()
        self.assertTrue(r1["stoppable"] and r2["stoppable"])          # every copy is stopped (D15)
        self.assertEqual((r1["dup_group"], r2["dup_group"]), (["a", "b"], ["a", "b"]))
        self.assertEqual((r1["primary"], r2["primary"]), (True, False))
        self.assertFalse(hasattr(term_vt, "AGENT_REASON_DUP"))

    def test_primary_is_the_first_row_in_ptys_order(self):
        self.pane("a", 100, label="X")
        self.pane("b", 101, label="X")
        self.pane("c", 102, label="Y")
        r = {x["tty"]: x for x in self.cands()}
        self.assertEqual((r["c"]["dup_group"], r["c"]["primary"]), ([], True))
        self.assertEqual((r["a"]["primary"], r["b"]["primary"]), (True, False))

    def test_unknown_panes_are_not_deduped(self):
        self.pane("a", 100)
        self.pane("b", 101)
        r1, r2 = self.cands()
        for r in (r1, r2):
            self.assertTrue(r["reason"].startswith("the tracker cannot tell"), r["reason"])
            self.assertEqual((r["dup_group"], r["primary"]), ([], True))

    def test_row_keys_are_the_contract(self):
        self.pane("a", 100, label="X")
        (r,) = self.cands()
        self.assertEqual(set(r), {
            "tty", "session", "relabelled", "target", "pid", "version", "status", "cwd", "title", "cols", "rows",
            "folder", "thin", "daemon", "job_short", "needs_slot", "stoppable", "reason", "command",
            "dup_group", "primary"})

    def test_thin_client_without_its_daemon_is_not_stoppable(self):
        self.pane("a", 100, label="X")
        with mock.patch.object(term_vt, "_thin_client_short", return_value="ab12"):
            with mock.patch.object(term_vt, "_background_target", return_value=""):
                (r,) = self.cands_keep()
        self.assertFalse(r["stoppable"])
        self.assertIn("background job", r["reason"])

    def test_busy_folder_shell_is_not_a_landing_spot_a6(self):
        self.pane("a", 100, label="X")
        self.pane("b", 101)
        self.cwd = {"X": "/w"}
        pa, pb = term_vt.PTYS["a"], term_vt.PTYS["b"]
        pa.cwd, pb.cwd = "/w/wt", "/w"
        (r,) = [x for x in self.cands() if x["tty"] == "a"]
        self.assertTrue(r["needs_slot"])       # b's foreground (pgid != its shell pid) is busy

    def test_needs_slot_when_no_folder_pane_for_the_sessions_cwd_s7(self):
        self.pane("a", 100, label="X")
        self.cwd = {"X": "/nowhere/else"}
        (r,) = self.cands()
        self.assertTrue(r["needs_slot"])
        self.cwd = {}
        (r,) = self.cands()
        self.assertFalse(r["needs_slot"])


class AgentSweep(unittest.TestCase):
    def test_start_time_guard_s5(self):
        # our own pid: the real start time differs from the stale one -> never signalled
        me = os.getpid()
        real = term_vt._provider()._ps_lstart(me)
        self.assertTrue(real)
        with mock.patch.object(term_vt.os, "getpgid", return_value=987654), \
             mock.patch.object(term_vt.os, "killpg") as kp, mock.patch.object(term_vt.time, "sleep"):
            n = term_vt._agent_sweep([(me, "Mon Jan  1 00:00:00 2001")], 1)
        self.assertEqual((n, kp.call_count), (0, 0))
        # matching start time but our own group -> still refused (never signal ourselves)
        with mock.patch.object(term_vt.os, "killpg") as kp, mock.patch.object(term_vt.time, "sleep"):
            self.assertEqual(term_vt._agent_sweep([(me, real)], 1), 0)
        self.assertEqual(kp.call_count, 0)
        # matching start time, a group that is not ours/shell's -> signalled (patched, never real)
        with mock.patch.object(term_vt.os, "getpgid", return_value=987654), \
             mock.patch.object(term_vt.os, "killpg") as kp, mock.patch.object(term_vt.time, "sleep"):
            self.assertEqual(term_vt._agent_sweep([(me, real)], 1), 1)
        self.assertEqual(kp.call_args_list[0], mock.call(987654, signal.SIGTERM))

    def test_empty_start_time_is_skipped(self):
        with mock.patch.object(term_vt.os, "killpg") as kp, mock.patch.object(term_vt.time, "sleep"):
            self.assertEqual(term_vt._agent_sweep([(os.getpid(), "")], 1), 0)
        self.assertEqual(kp.call_count, 0)


# A folder "shell" with job control: runs a foreground child (own pgrp) and takes the tty back when
# it exits, like a real shell. argv: pidfile sleepfile mode ("term" = exit 0 on TERM, "ignore" = ignores TERM).
_SHELL = r"""
import os, signal, subprocess, sys, time
pidfile, sleepfile, mode = sys.argv[1:4]
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    os.setpgid(0, 0)
    try:
        os.tcsetpgrp(0, os.getpgrp())
    except OSError:
        pass
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    if mode == "term":
        signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sl = subprocess.Popen(["sleep", "300"], start_new_session=True)
    open(sleepfile, "w").write(str(sl.pid))
    open(pidfile, "w").write(str(os.getpid()))
    while True:
        time.sleep(1)
os.waitpid(child, 0)
signal.signal(signal.SIGTTOU, signal.SIG_IGN)
try:
    os.tcsetpgrp(0, os.getpgrp())
except OSError:
    pass
time.sleep(60)
"""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    try:                    # a zombie still answers kill(0)
        import subprocess
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
        return bool(st.strip()) and not st.strip().startswith("Z")
    except Exception:
        return True


@unittest.skipUnless(tft._HAS_PTY_FORK, "pty/fork not available on this platform")
class StopForUpgradeReal(_Base):
    def _start(self, mode):
        td = tempfile.mkdtemp()
        script, pidfile, sleepfile = (os.path.join(td, n) for n in ("sh.py", "child.pid", "sleep.pid"))
        with open(script, "w") as f:
            f.write(_SHELL)
        pt = term_vt.spawn(td, ["python3", script, pidfile, sleepfile, mode], 80, 24)
        pt.folder = True
        self.addCleanup(pt.kill)
        term_vt.PTYS[pt.id] = pt
        pt.fg = {"session": _SID, "mode": "resume", "started": time.time(), "grants": {_SID}}   # the claim open_pty leaves
        self.assertTrue(tft._wait_until(lambda: os.path.exists(pidfile) and os.path.exists(sleepfile), 6))
        time.sleep(0.2)
        child, sleeper = int(open(pidfile).read()), int(open(sleepfile).read())
        self.addCleanup(lambda: os.path.exists(sleepfile) and _alive(sleeper) and os.kill(sleeper, signal.SIGKILL))
        self.assertTrue(tft._wait_until(lambda: os.tcgetpgrp(pt.fd) == child, 3), "child never took the tty")
        return pt, child, sleeper

    def test_graceful_stop_confirms_and_sweeps_orphans(self):
        pt, child, sleeper = self._start("term")
        with mock.patch.object(term_vt.time, "sleep", wraps=time.sleep):
            r = term_vt.stop_for_upgrade(pt.id, _SID, child)
        self.assertEqual(r["error"], "")
        self.assertTrue(r["stopped"] and r["graceful"] and r["confirmed"], r)
        self.assertEqual(r["work_children"], 1)
        self.assertEqual(r["orphans_killed"], 1)
        self.assertTrue(tft._wait_until(lambda: not _alive(sleeper), 3), "the orphaned sleep survived")
        self.assertIs(term_vt.PTYS.get(pt.id), pt)
        self.assertFalse(pt.done)
        self.assertIsNone(pt.fg)      # M6: the claim is cleared

    def test_term_ignoring_foreground_is_killed_but_the_shell_survives(self):
        pt, child, sleeper = self._start("ignore")
        with mock.patch.object(term_vt, "PARKED_DETACH_WAIT", 0.5):
            r = term_vt.stop_for_upgrade(pt.id, _SID, child)
        self.assertFalse(r["graceful"], r)
        self.assertTrue(r["confirmed"], r)
        self.assertTrue(_alive(pt.pid))
        self.assertTrue(tft._wait_until(lambda: not _alive(sleeper), 3))

    def test_wrong_pid_signals_nothing(self):
        pt, child, sleeper = self._start("term")
        with mock.patch.object(term_vt.os, "killpg") as kp:
            r = term_vt.stop_for_upgrade(pt.id, _SID, child + 1)
        self.assertIn("different program", r["error"])
        self.assertFalse(r["stopped"])
        self.assertEqual(kp.call_count, 0)
        self.assertTrue(_alive(child))

    def test_closed_terminal_sets_closed(self):
        r = term_vt.stop_for_upgrade("nope", _SID, 12345)
        self.assertTrue(r["closed"])
        self.assertEqual(r["error"], "its terminal closed")

    def test_unknown_tty_errors(self):
        r = term_vt.stop_for_upgrade("nope", _SID, 1)
        self.assertEqual(r["error"], "its terminal closed")


class CallRoute(_Base):
    def setUp(self):
        super().setUp()
        config.AUTH = ""
        b0 = config.BIND_HOST
        config.BIND_HOST = "127.0.0.1"
        self.addCleanup(setattr, config, "BIND_HOST", b0)

    def test_open_pty_via_call_route_is_not_403(self):
        code, obj = term_vt.call_route(term_vt.open_pty, {"session": "", "mode": "cwd", "cwd": "/nonexistent-dir-x"})
        self.assertEqual(code, 400, obj)      # past the guard, rejected by its own cwd check

    def test_no_reply_default_and_guard_refusal_is_returned(self):
        self.assertEqual(term_vt.call_route(lambda h, p, b: None, {}), (500, {"error": "no reply"}))
        config.TERMINAL = False
        code, _obj = term_vt.call_route(term_vt.open_pty, {"session": "", "mode": "cwd", "cwd": self._tmpdir})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
