"""A background session may take over an UNWATCHED folder pane that shows another background
session's daemon thin client (docs/folder-terminal-reuse-plan.md, "REVISED SPEC").

Most tests drive `open_pty` with a made-up shell pid and mocked process probes (`tcgetpgrp`,
`killpg`, `_thin_client_short`, the roster); `os.killpg` is asserted NOT called wherever a guard
must hold. `TestSwapRealProcesses` runs a real shell, real `ps` and real signals with a fake
`claude` first on PATH. Run one module per process:

    TRACKER_AUTH= python3 -m unittest tests.test_folder_swap -v
"""
import os
import signal
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_gate, term_vt
from aitracker.providers import claude as claude_provider
from tests.test_folder_terminal import _FakeHandler, _stub_kill, _wait_until

CWD = "/tmp/swap-cwd"
SHELL, CLIENT = 42424, 42500
A, B = "aaaaaaaa-1111-2222-3333-444444444444", "bbbbbbbb-1111-2222-3333-444444444444"


class _SwapBase(unittest.TestCase):
    """One folder shell (made-up pid) whose foreground group is session A's `claude attach` client."""

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        _stub_kill(self)
        self.state = {"pg": CLIENT}          # what tcgetpgrp reports; killpg moves it to the shell
        self.killed, self.typed, self.events = [], [], []
        self.live = {A: 1111, B: 2222}       # daemon REPL pids by session
        self.short = "aaaaaaaa"              # what `ps` says the foreground group is `attach`ing
        self.shell_cwd = CWD
        self.exits = True                    # does SIGTERM make the client leave?
        self.write_ok = True
        self.overflow = term_vt.Pty(tid="overflow-1", pid=0)
        fp = self.fp = term_vt.Pty(tid="folder-1", pid=SHELL, fd=99, cwd=CWD)
        fp.folder, fp.mode, fp.startup_done = True, "cwd", True
        fp.screen = term_vt.Screen(cols=80, rows=24)
        fp.fg = {"session": A, "mode": "resume", "started": time.time() - 60, "grants": {A}}
        fp.fg_seen_child = True
        term_vt.PTYS[fp.id] = fp
        self._session_cwd0 = term_gate.session_cwd
        term_gate.session_cwd = lambda sid, resume=False: CWD

        def killpg(pg, sig):
            self.killed.append((pg, sig))
            self.events.append("killpg")
            if self.exits:
                self.state["pg"] = SHELL

        def write(pt, data):
            self.events.append("write")
            self.typed.append(data)
            return self.write_ok

        def tee(pt, data):
            self.events.append("tee")

        for p in (
            mock.patch.object(term_vt.os, "tcgetpgrp", lambda fd: self.state["pg"]),
            mock.patch.object(term_vt.os, "killpg", killpg),
            mock.patch.object(term_vt, "_thin_client_short", lambda pg: self.short),
            mock.patch.object(term_vt, "_shell_cwd", lambda pid: self.shell_cwd),
            mock.patch.object(term_vt, "_background_target", lambda sid: sid),
            mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True),
            mock.patch.object(term_vt, "_inject_write", write),
            mock.patch.object(term_vt, "_tee_raw", tee),
            mock.patch.object(term_vt, "_resume_backstop"),
            mock.patch.object(term_vt, "VIEWER_GRACE", 0.0),
            mock.patch.object(term_vt, "THIN_DETACH_WAIT", 0.4),
            mock.patch.object(claude_provider, "daemon_repl_pid", lambda sid: self.live.get(sid, 0)),
            mock.patch.object(claude_provider, "session_label", lambda sid: {A: "Alpha"}.get(sid, "")),
            mock.patch.object(term_vt, "spawn", return_value=self.overflow),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.spawn = term_vt.spawn

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_gate.session_cwd = self._session_cwd0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def open(self, sid=B, mode="resume"):
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": sid, "mode": mode, "cols": 80, "rows": 24})
        obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        return obj


class TestThinSwap(_SwapBase):
    def test_unwatched_thin_client_is_swapped_in_the_same_tty(self):
        obj = self.open()
        self.assertEqual(obj["tty"], "folder-1")
        self.assertEqual(self.killed, [(CLIENT, signal.SIGTERM)], "SIGTERM to the client's group, once")
        self.assertFalse(self.spawn.called, "no dedicated pty")
        self.assertIn(b"claude --resume " + B.encode(), b"".join(self.typed))
        self.assertEqual(self.fp.fg["session"], B)
        self.assertFalse(self.fp.fg_pending)
        self.assertIn("Alpha", obj["notice"])
        self.assertIn("aaaaaaaa", obj["notice"])
        self.assertIn("keeps running in the background", obj["notice"])
        self.assertTrue(obj["reused"] and obj["folder"])

    def test_notice_falls_back_to_the_short_without_a_title(self):
        self.short = "aaaaaaaa"
        with mock.patch.object(claude_provider, "session_label", lambda sid: ""):
            obj = self.open()
        self.assertTrue(obj["notice"].startswith("session (aaaaaaaa)"), obj["notice"])

    def test_mode_reset_is_fed_after_the_client_leaves_and_before_typing(self):
        self.open()
        self.assertEqual(self.events[:3], ["killpg", "tee", "write"], self.events)

    def test_claim_names_target_during_detach_and_touches_the_idle_clock(self):
        seen = {}
        before = self.fp.last_active = time.time() - 3600

        def killpg(pg, sig):
            seen.update(session=self.fp.fg["session"], pending=self.fp.fg_pending,
                        starting=self.fp.starting, active=self.fp.last_active)
            self.state["pg"] = SHELL

        with mock.patch.object(term_vt.os, "killpg", killpg):
            self.open()
        self.assertEqual(seen["session"], B, "a concurrent open of B must peek, not race")
        self.assertTrue(seen["pending"] and seen["starting"])
        self.assertGreater(seen["active"], before + 3000, "idle reap must not take the shell mid-swap")

    def test_viewer_grace_waits_for_a_closing_stream(self):
        self.fp.viewers = 1
        threading.Timer(0.2, lambda: setattr(self.fp, "viewers", 0)).start()
        with mock.patch.object(term_vt, "VIEWER_GRACE", 1.5):
            self.open()
        self.assertEqual(len(self.killed), 1)

    def test_swap_never_signals_when_foreground_changed(self):
        cand = {"fg": self.fp.fg, "pg": CLIENT, "kind": "thin", "shown": A}
        self.state["pg"] = 55555           # something else took the foreground since the probe
        self.assertIsNone(term_vt._swap_in(self.fp, cand, B, ["claude", "--resume", B], False, 80, 24))
        self.assertEqual(self.killed, [])
        self.assertIs(self.fp.fg, cand["fg"], "claim untouched")

    def test_swap_never_signals_the_shell_or_our_own_group(self):
        for pg in (SHELL, os.getpgrp()):
            self.state["pg"] = pg
            cand = {"fg": self.fp.fg, "pg": pg, "kind": "thin", "shown": A}
            with mock.patch.object(term_vt, "THIN_DETACH_WAIT", 0.05):
                term_vt._swap_in(self.fp, cand, B, ["claude", "--resume", B], False, 80, 24)
            self.assertEqual(self.killed, [], pg)
            self.fp.fg = cand["fg"]

    def test_swap_restores_same_label_when_client_will_not_exit(self):
        self.exits = False
        old = self.fp.fg
        obj = self.open()
        self.assertEqual(self.killed, [(CLIENT, signal.SIGTERM)])
        self.assertIs(self.fp.fg, old, "the displaced client's label is back")
        self.assertTrue(self.fp.fg_seen_child)
        self.assertFalse(self.fp.fg_pending)
        self.assertFalse(self.fp.starting)
        self.assertEqual(self.typed, [], "nothing typed over a client that never left")
        self.assertTrue(self.spawn.called, "falls through to a dedicated pty")
        self.assertEqual(obj["tty"], "overflow-1")

    def test_closing_pane_is_not_given_its_label_back(self):
        self.exits = False
        old = self.fp.fg

        def killpg(pg, sig):
            self.fp.closing = True

        with mock.patch.object(term_vt.os, "killpg", killpg):
            self.open()
        self.assertIsNot(self.fp.fg, old, "a pane being closed is not given the dead client's label back")
        self.assertFalse(self.fp.fg_pending)
        self.assertFalse(self.fp.starting)

    def test_type_failure_releases_claim_and_falls_through(self):
        self.write_ok = False
        obj = self.open()
        self.assertIsNone(self.fp.fg)
        self.assertFalse(self.fp.fg_pending)
        self.assertFalse(self.fp.fg_seen_child)
        self.assertFalse(self.fp.starting)
        self.assertTrue(self.spawn.called)
        self.assertEqual(obj["tty"], "overflow-1")


class TestSwapRefusals(_SwapBase):
    """Every row: nothing is signalled and the open gets a dedicated pty, exactly as before."""

    def _refused(self, why, sid=B, mode="resume"):
        obj = self.open(sid, mode)
        self.assertEqual(self.killed, [], why)
        self.assertTrue(self.spawn.called, why)
        self.assertEqual(obj["tty"], "overflow-1", why)
        self.assertEqual(self.typed, [], why)
        self.assertIs(self.fp.fg["session"], A, why) if self.fp.fg else None

    def test_watched_pane(self):
        self.fp.viewers = 1
        self._refused("viewer")

    def test_standalone_claude_args(self):
        self.short = ""
        self._refused("standalone `claude --resume A`")

    def test_short_mismatch(self):
        self.short = "cccccccc"
        self._refused("client is attached to a different job than the label says")

    def test_displaced_repl_dead(self):
        self.live.pop(A)
        self._refused("A has no live daemon REPL")

    def test_forked_label(self):
        self.fp.fg["forked"] = True
        self._refused("forked")

    def test_starting(self):
        self.fp.starting = True
        self._refused("starting")

    def test_pending_claim(self):
        self.fp.fg_pending = True
        self._refused("pending")

    def test_no_label(self):
        self.fp.fg = None
        self.state["pg"] = SHELL
        obj = self.open()           # idle shell: typed into, never swapped (today's path)
        self.assertEqual(self.killed, [])
        self.assertEqual(obj["tty"], "folder-1")

    def test_label_names_the_target_is_a_peek(self):
        obj = self.open(A)
        self.assertEqual(self.killed, [])
        self.assertEqual(obj["tty"], "folder-1")
        self.assertIsNone(obj["notice"])

    def test_shell_moved_to_another_folder_checked_before_signal(self):
        self.shell_cwd = "/somewhere/else"
        self._refused("shell cd'd away")

    def test_non_background_target_never_swaps(self):
        with mock.patch.object(term_vt, "_background_target", lambda sid: ""):
            self._refused("target B is not hosted by the daemon")

    def test_new_and_cwd_modes_never_swap(self):
        for mode in ("new", "cwd"):
            self.spawn.reset_mock()
            obj = self.open(B, mode)
            self.assertEqual(self.killed, [], mode)
            self.assertEqual(self.typed, [], mode)
            self.assertNotEqual(obj["tty"], "folder-1", mode)

    def test_dead_or_closing_pane(self):
        self.fp.closing = True
        self._refused("closing")

    def test_probe_errors_fail_closed(self):
        with mock.patch.object(term_vt, "_thin_client_short", side_effect=RuntimeError("boom")):
            self._refused("probe raised")


class TestProbeHelpers(unittest.TestCase):
    def test_thin_client_short_table(self):
        def short(args):
            out = mock.Mock(stdout=args + "\n")
            with mock.patch.object(term_vt.subprocess, "run", return_value=out):
                return term_vt._thin_client_short(123)
        self.assertEqual(short("/Users/x/.local/bin/claude attach ab12cd34"), "ab12cd34")
        self.assertEqual(short("claude attach ab12cd34"), "ab12cd34")
        self.assertEqual(short("claude --resume ab12cd34"), "")
        self.assertEqual(short("claude attach ab12cd34 --extra"), "")
        self.assertEqual(short("/opt/my claude/claude attach ab12cd34"), "")
        self.assertEqual(short("claude attach xyz"), "")
        self.assertEqual(short("node attach ab12cd34"), "")
        self.assertEqual(short(""), "")
        with mock.patch.object(term_vt.subprocess, "run", side_effect=OSError):
            self.assertEqual(term_vt._thin_client_short(1), "")

    def test_thin_client_short_real_ps(self):
        p = subprocess.Popen(["bash", "-c", 'exec -a "claude attach ab12cd34" cat'], stdin=subprocess.PIPE)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdin.close()))
        self.assertTrue(_wait_until(lambda: term_vt._thin_client_short(p.pid) == "ab12cd34", 5),
                        "real ps shows three tokens for an exec -a name")
        q = subprocess.Popen(["bash", "-c", 'exec -a "claude --resume x" cat'], stdin=subprocess.PIPE)
        self.addCleanup(lambda: (q.kill(), q.wait(), q.stdin.close()))
        time.sleep(0.3)
        self.assertEqual(term_vt._thin_client_short(q.pid), "")
        p.kill(); p.wait()
        self.assertEqual(term_vt._thin_client_short(p.pid), "", "a dead pid")

    def test_shell_cwd_real_and_never_raises(self):
        d = os.path.realpath(tempfile.mkdtemp())
        p = subprocess.Popen(["sleep", "20"], cwd=d)
        self.addCleanup(lambda: (p.kill(), p.wait()))
        self.assertTrue(_wait_until(lambda: term_vt._shell_cwd(p.pid) != "", 5))
        self.assertEqual(os.path.realpath(term_vt._shell_cwd(p.pid)), d)
        with mock.patch.object(term_vt.subprocess, "run", side_effect=OSError):
            self.assertEqual(term_vt._shell_cwd(p.pid), "")

    def test_background_target_reads_the_roster(self):
        real = term_vt._real_background_target
        with mock.patch.object(claude_provider, "daemon_repl_pid", lambda s: 7 if s == "x" else 0):
            self.assertEqual(real("x"), "x")
            self.assertEqual(real("y"), "")
        with mock.patch.object(claude_provider, "daemon_repl_pid", side_effect=RuntimeError):
            self.assertEqual(real("x"), "")


class TestSwapRealProcesses(unittest.TestCase):
    """Real bash, real `ps`, real SIGTERM. A fake `claude` becomes `claude attach <short>` like the
    CLI does for a background session, and (like the real client) leaves the alt screen on."""

    FAKE = """#!/bin/bash
echo "$@" >> "$LOG"
if [ "$1" = "--resume" ]; then
  printf '\\033[?1049h\\033[?1003h\\033[?1006h'
  exec -a "claude attach ${2:0:8}" cat
fi
exec cat
"""

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.cwd = os.path.join(self.home, "proj")
        os.mkdir(self.cwd)
        os.mkdir(os.path.join(self.home, "bin"))
        self.log = os.path.join(self.home, "log")
        fake = os.path.join(self.home, "bin", "claude")
        with open(fake, "w") as fh:
            fh.write(self.FAKE)
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
        env = {"HOME": self.home, "SHELL": "/bin/bash", "LOG": self.log,
               "PATH": os.path.join(self.home, "bin") + ":" + os.environ.get("PATH", "")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.live = {A: 1111, B: 2222}
        self._session_cwd0 = term_gate.session_cwd
        term_gate.session_cwd = lambda sid, resume=False: self.cwd
        for p in (mock.patch.object(term_vt, "_background_target", lambda sid: sid),
                  mock.patch.object(claude_provider, "daemon_repl_pid", lambda sid: self.live.get(sid, 0)),
                  mock.patch.object(claude_provider, "session_label", lambda sid: "Alpha"),
                  mock.patch.object(term_vt, "_resume_backstop"),
                  mock.patch.object(term_vt, "VIEWER_GRACE", 0.0)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_gate.session_cwd = self._session_cwd0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def _open(self, sid, mode="resume"):
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": sid, "mode": mode, "cols": 80, "rows": 24})
        obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        return obj

    def _client_short(self, fp):
        pg = term_vt._fg_pgid(fp)
        return pg, (term_vt._thin_client_short(pg) if pg != fp.pid else "")

    def test_thin_client_swaps_in_same_tty(self):
        first = self._open(A)
        fp = term_vt.PTYS[first["tty"]]
        self.assertTrue(_wait_until(lambda: self._client_short(fp)[1] == A[:8], 30),
                        "A's fake client is up as `claude attach aaaaaaaa`")
        old_pg = self._client_short(fp)[0]
        fp.starting = False               # the backstop (mocked) is the sole clearer of `starting`
        t0 = time.time()
        second = self._open(B)
        self.assertEqual(second["tty"], first["tty"], "same tty")
        self.assertEqual(len([p for p in term_vt.PTYS.values() if not p.done]), 1, "one terminal")
        self.assertIn("Alpha", second["notice"])
        self.assertTrue(_wait_until(lambda: self._client_short(fp)[1] == B[:8], 30),
                        "B's client replaced A's in the same pane")
        with self.assertRaises(OSError):
            os.killpg(old_pg, 0)          # A's client is gone
        self.assertLess(time.time() - t0, 20)
        self.assertEqual(open(self.log).read().split("\n")[:2], ["--resume " + A, "--resume " + B])
        self.assertEqual(fp.fg["session"], B)

    def test_watched_pane_is_left_alone(self):
        first = self._open(A)
        fp = term_vt.PTYS[first["tty"]]
        self.assertTrue(_wait_until(lambda: self._client_short(fp)[1] == A[:8], 30))
        pg = self._client_short(fp)[0]
        fp.starting = False
        with term_vt._LOCK:
            fp.viewers += 1
        self.addCleanup(lambda: setattr(fp, "viewers", 0))
        second = self._open(B)
        self.assertNotEqual(second["tty"], first["tty"], "a watched pane is never taken over")
        os.killpg(pg, 0)                  # A's client still alive (raises if gone)
        self.assertEqual(self._client_short(fp)[1], A[:8])


if __name__ == "__main__":
    unittest.main()
