"""Server tests for the folder-terminal feature -- one shared PTY per folder that every mode
(shell/resume/new) attaches to instead of spawning a fresh one, per reports/FOLDER-TERMINAL.md's
"Design" section (the contract this file is written against).

This file is written BEFORE the server implementation necessarily exists -- see that report's
clause ledger (C1-C9, all "not discharged" at the time this file was created). Every test name is
picked to pin one clause of the contract, so a red run here should be read as "which clause is
still missing", not as a bug in the test. Nothing here weakens an assertion to dodge that; a test
that cannot yet pass is left red and reported as such.

Fixture conventions borrowed verbatim from tests/test_resolve_spawned.py and
tests/test_resume_fork_session.py: `_FakeHandler`/`_FakeHeaders` stand in for the real HTTP
handler (only `.headers`/`._json()` are used by these routes), `term_vt.PTYS` is saved and
restored around every test that touches it, and `config.TERMINAL`/`config.AUTH` are flipped on
for the duration of any test that calls a route function directly (term_gate.guard() 403s
otherwise). Run with:

    env -u TRACKER_AUTH python3 -m unittest tests.test_folder_terminal -v

(TRACKER_AUTH must be UNSET in the real environment -- see test_term_vt.py's own tests for why a
stray value there makes `allowed()` disagree with what setUp already forces via config.AUTH; this
file works around it the same way every other terminal test file does, by writing config.AUTH
directly rather than depending on the process environment at all.)
"""
import contextlib
import os
import pty
import signal
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_gate, term_vt

_HAS_PTY_FORK = hasattr(os, "fork") and hasattr(pty, "fork")


class _FakeHeaders:
    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler: records the one _json() call a route makes."""

    def __init__(self, headers=None):
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


def _wait_until(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _stub_kill(testcase):
    """Neuter `Pty.kill` for the whole test INCLUDING tearDown (cleanups run after tearDown, so
    the patch is still up when the fixture loop calls `pt.kill()`). Every fixture below that is
    built with a made-up pid (`Pty(pid=42424, fd=99)`) needs this: the real kill does
    `os.killpg(os.getpgid(pid), SIGKILL)`, and a made-up pid is a REAL process the moment the
    kernel's pid counter happens to land on it (macOS wraps at 99999) -- the test run would
    then SIGKILL some unrelated process group. Never fix this with `pid=0` instead: that is our
    own group (see Pty.kill's comment on `killpg(0)`)."""
    patcher = mock.patch.object(term_vt.Pty, "kill", autospec=True)
    patcher.start()
    testcase.addCleanup(patcher.stop)


def _best_effort_killpg(pgid_holder):
    """addCleanup safety net: kill a leftover real `sleep 60` process group if an assertion
    failed before the test itself confirmed it dead. Never raises."""
    pgid = pgid_holder[0] if isinstance(pgid_holder, list) else pgid_holder
    if pgid is None:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------- C1/C4
# Pty gains folder/overflow/fg/fg_seen_child; _folder_pty() finds the live match.


class TestPtyGainsFolderFields(unittest.TestCase):
    def test_pty_defaults_are_not_a_folder_shell(self):
        pt = term_vt.Pty(tid="d1")
        self.assertFalse(pt.folder)
        self.assertFalse(pt.overflow)
        self.assertIsNone(pt.fg)
        self.assertFalse(pt.fg_seen_child)


class TestFolderPtyLookup(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_folder_pty_matches_only_a_live_folder_pty_with_equal_cwd(self):
        match = term_vt.Pty(tid="f1", cwd="/tmp/match")
        match.folder = True

        other_cwd = term_vt.Pty(tid="f2", cwd="/tmp/other")
        other_cwd.folder = True

        not_folder = term_vt.Pty(tid="f3", cwd="/tmp/match")
        not_folder.folder = False

        done_folder = term_vt.Pty(tid="f4", cwd="/tmp/match")
        done_folder.folder = True
        done_folder.done = True
        done_folder.ended = time.time()

        closing_folder = term_vt.Pty(tid="f5", cwd="/tmp/match")
        closing_folder.folder = True
        closing_folder.closing = True

        for pt in (match, other_cwd, not_folder, done_folder, closing_folder):
            term_vt.PTYS[pt.id] = pt

        self.assertIs(term_vt._folder_pty("/tmp/match"), match,
                       "must return the one live, non-closing, folder=True pty with the same cwd")
        self.assertIsNone(term_vt._folder_pty("/tmp/nonexistent"))


# --------------------------------------------------------------------------------------------- C1
# _refresh_fg: fg_seen_child latches busy, and only clears fg once the shell is foreground again
# AFTER having seen the child.


class TestRefreshFg(unittest.TestCase):
    def test_refresh_fg_sets_seen_child_while_busy_and_clears_once_idle_again(self):
        pt = term_vt.Pty(tid="g1", pid=555, fd=9)
        pt.fg = {"session": "s", "mode": "resume", "started": time.time()}
        pt.fg_seen_child = False

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=556):
            term_vt._refresh_fg(pt)
        self.assertTrue(pt.fg_seen_child,
                         "a foreground pgid different from the shell's own must mark the child seen")
        self.assertIsNotNone(pt.fg, "must stay busy while the child still holds the foreground")

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=555):
            term_vt._refresh_fg(pt)
        self.assertIsNone(pt.fg,
                           "once the shell is foreground again after having seen the child, fg must clear")
        self.assertFalse(pt.fg_seen_child)

    def test_refresh_fg_does_not_clear_fg_before_the_child_was_ever_seen(self):
        """A resume just opened may not have had time for the shell's own tcgetpgrp reading to
        move off pt.pid yet -- clearing fg on that transient reading would drop the busy state a
        moment after setting it."""
        pt = term_vt.Pty(tid="g3", pid=555, fd=9)
        pt.fg = {"session": "s", "mode": "resume", "started": time.time()}
        pt.fg_seen_child = False
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=555):
            term_vt._refresh_fg(pt)
        self.assertIsNotNone(pt.fg,
                              "fg must not be cleared until fg_seen_child has gone True at least once")


# ---------------------------------------------------------------------------------------------- C1
# open_pty, mode="cwd": second open of the same cwd attaches to the first instead of spawning.


class TestFolderShellReuse(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_second_cwd_open_reuses_folder_shell(self):
        h1 = _FakeHandler()
        term_vt.open_pty(h1, None, {"cwd": self._tmpdir, "mode": "cwd", "cols": 80, "rows": 24})
        obj1, code1 = h1.calls[-1]
        self.assertEqual(code1, 200, obj1)
        tid1 = obj1["tty"]

        h2 = _FakeHandler()
        term_vt.open_pty(h2, None, {"cwd": self._tmpdir, "mode": "cwd", "cols": 80, "rows": 24})
        obj2, code2 = h2.calls[-1]
        self.assertEqual(code2, 200, obj2)

        self.assertEqual(obj2["tty"], tid1,
                          "a second cwd-open of the SAME folder must attach to the first shell")
        self.assertTrue(obj2.get("reused"), "the second open must report reused:true")
        self.assertTrue(obj2.get("folder"), "the shared shell must be reported as a folder pty")
        self.assertEqual(term_vt._live_count(), 1,
                          "only ONE pty should exist for the shared folder, not two")


# ---------------------------------------------------------------------------------------------- C2
# open_pty, mode="resume" against an idle folder shell: injects, does not spawn.


class TestFolderResumeInjection(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        _stub_kill(self)      # every fixture here has a made-up pid -- see _stub_kill

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0

    def test_teardown_kill_on_a_fake_pid_fixture_signals_nothing(self):
        """The fixture hazard itself: tearDown's `pt.kill()` on a made-up pid must reach no
        signal syscall. The real syscalls are mocked here so that WITHOUT the setUp stub the
        attempt is recorded (red) rather than delivered to whatever process owns pid 42424."""
        pt = term_vt.Pty(tid="fake-pid", pid=42424, fd=99)
        pt.folder = True
        term_vt.PTYS["fake-pid"] = pt
        with mock.patch.object(term_vt.os, "killpg") as killpg, \
             mock.patch.object(term_vt.os, "kill") as kill, \
             mock.patch.object(term_vt.os, "getpgid", return_value=42424), \
             mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42424):
            pt.kill()               # exactly what tearDown does to every fixture left in PTYS
        killpg.assert_not_called()
        kill.assert_not_called()

    def test_resume_reuses_idle_folder_shell_and_injects_the_resume_command(self):
        cwd = "/tmp/folder-resume-idle"
        folder_pty = term_vt.Pty(tid="folder1", pid=42424, fd=99, cwd=cwd)
        folder_pty.folder = True
        folder_pty.mode = "cwd"
        folder_pty.fg = None
        term_vt.PTYS["folder1"] = folder_pty
        term_gate.session_cwd = lambda sid, resume=False: cwd

        injected = []

        def _capture(pt, data):
            injected.append(data)
            return True

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42424), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write", side_effect=_capture), \
             mock.patch.object(term_vt, "_resume_backstop"):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "sid-1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]

        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["tty"], "folder1",
                          "resume against an idle folder shell must attach to it, not spawn a new tty")
        self.assertTrue(obj.get("folder"), "response must report folder:true")

        self.assertIsNotNone(folder_pty.fg, "the folder pty must record who is now running in it")
        self.assertEqual(folder_pty.fg.get("session"), "sid-1")
        self.assertEqual(folder_pty.fg.get("mode"), "resume")
        self.assertIn("started", folder_pty.fg)

        joined = b"".join(injected)
        self.assertIn(b"claude --resume sid-1", joined,
                       "the injected text must be the resume argv, not just typed blind")

    def test_resume_while_folder_shell_busy_with_a_different_session_gets_overflow(self):
        cwd = "/tmp/folder-resume-busy"
        folder_pty = term_vt.Pty(tid="folder2", pid=42425, fd=99, cwd=cwd)
        folder_pty.folder = True
        folder_pty.mode = "resume"
        folder_pty.fg = {"session": "other-sid", "mode": "resume", "started": time.time()}
        term_vt.PTYS["folder2"] = folder_pty
        term_gate.session_cwd = lambda sid, resume=False: cwd

        overflow_pty = term_vt.Pty(tid="overflow1", pid=0)

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42426), \
             mock.patch.object(term_vt, "spawn", return_value=overflow_pty) as spawn_mock, \
             mock.patch.object(term_vt, "_resume_backstop"):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "sid-2", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]

        self.assertEqual(code, 200, obj)
        self.assertTrue(spawn_mock.called,
                         "a folder shell busy with a DIFFERENT session must fall back to a dedicated spawn")
        self.assertNotEqual(obj["tty"], "folder2")
        self.assertTrue(overflow_pty.overflow, "the dedicated fallback pty must be flagged overflow")
        self.assertIsNone(obj.get("notice"), "the overflow label is no longer user-facing")


# ---------------------------------------------------------------------------------------------- C2
# The claim's PENDING window: between open_pty's claim (under _LOCK) and _inject_argv's Enter the
# shell's own startup job may hold the foreground while the list poll runs _refresh_fg(). That
# poll must neither latch the job nor clear the claim -- otherwise `fg` is None while Claude runs,
# a same-session re-open cannot peek and opens a duplicate `claude --resume` instead.


class TestFgClaimPendingUntilTyped(unittest.TestCase):
    SHELL, STARTUP_JOB, CLAUDE = 51515, 51516, 51517

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        _stub_kill(self)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0

    def test_claim_survives_a_startup_job_polled_during_the_inject_window(self):
        cwd = "/tmp/folder-pending"
        fp = term_vt.Pty(tid="folderP", pid=self.SHELL, fd=99, cwd=cwd)
        fp.folder = True
        fp.mode = "cwd"
        term_vt.PTYS["folderP"] = fp
        term_gate.session_cwd = lambda sid, resume=False: cwd

        fg_now = [self.SHELL]           # what the kernel would answer for tcgetpgrp right now
        injected = []
        in_window = threading.Event()   # _inject_argv has been entered (claim made, nothing typed)
        polled = threading.Event()      # the poller has run its job -> prompt timeline
        real_inject_argv = term_vt._inject_argv

        def _inject_argv_after_the_poll(pt, argv):
            in_window.set()
            polled.wait(3)
            return real_inject_argv(pt, argv)

        def _list_poll():
            # The 2s term_list/attached poll, twice, inside the window: `pyenv rehash` takes the
            # foreground, then the prompt is back -- both BEFORE the resume line is typed.
            in_window.wait(3)
            fg_now[0] = self.STARTUP_JOB
            with term_vt._LOCK:
                term_vt._refresh_fg(fp)
            fg_now[0] = self.SHELL
            with term_vt._LOCK:
                term_vt._refresh_fg(fp)
            polled.set()

        poller = threading.Thread(target=_list_poll, daemon=True)
        poller.start()
        overflow = term_vt.Pty(tid="overflow-p", pid=0)
        with mock.patch.object(term_vt.os, "tcgetpgrp", side_effect=lambda fd: fg_now[0]), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda pt, d: injected.append(d) or True), \
             mock.patch.object(term_vt, "_inject_argv", side_effect=_inject_argv_after_the_poll), \
             mock.patch.object(term_vt, "spawn", return_value=overflow) as spawn_mock, \
             mock.patch.object(term_vt, "_resume_backstop"):
            h1 = _FakeHandler()
            term_vt.open_pty(h1, None, {"session": "sid-p", "mode": "resume", "cols": 80, "rows": 24})
            poller.join(3)
            obj1, code1 = h1.calls[-1]
            self.assertEqual(code1, 200, obj1)
            self.assertEqual(obj1["tty"], "folderP")
            self.assertTrue(polled.is_set(), "the poll never ran inside the inject window")
            self.assertIn(b"claude --resume sid-p", b"".join(injected))

            self.assertIsNotNone(fp.fg, "the claim must survive a startup job polled before Enter")
            self.assertEqual(fp.fg.get("session"), "sid-p")
            self.assertFalse(fp.fg_pending, "pending ends with the typed line")
            self.assertFalse(fp.fg_seen_child, "only a child seen AFTER the typed line may latch")

            # Claude is now the foreground job; a second open of the SAME session is a peek.
            fg_now[0] = self.CLAUDE
            typed_before = len(injected)
            h2 = _FakeHandler()
            term_vt.open_pty(h2, None, {"session": "sid-p", "mode": "resume", "cols": 80, "rows": 24})
            obj2, code2 = h2.calls[-1]

        self.assertEqual(code2, 200, obj2)
        self.assertEqual(obj2["tty"], "folderP", "a same-session re-open must peek, not overflow")
        self.assertIsNone(obj2.get("notice"), obj2)
        self.assertTrue(obj2.get("reused"))
        self.assertFalse(spawn_mock.called, "no duplicate `claude --resume` in a dedicated pty")
        self.assertEqual(len(injected), typed_before, "a peek types nothing")

    def test_refresh_fg_leaves_a_pending_claim_alone(self):
        pt = term_vt.Pty(tid="g4", pid=555, fd=9)
        pt.fg = {"session": "s", "mode": "resume", "started": time.time() - 3600}   # past grace
        pt.fg_pending = True
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=556):
            term_vt._refresh_fg(pt)
        self.assertFalse(pt.fg_seen_child, "a foreground group before Enter is not the claimed job")
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=555):
            term_vt._refresh_fg(pt)
        self.assertIsNotNone(pt.fg, "a pending claim is never cleared, grace or no grace")


# ---------------------------------------------------------------------------------------------- C1
# Two simultaneous FIRST opens of one cwd: the spawn runs outside _LOCK, so without a per-cwd
# reservation both pass the lookup and both spawn a folder=True shell -- two folder rows.


@unittest.skipUnless(_HAS_PTY_FORK, "pty/fork not available on this platform")
class TestConcurrentFirstOpenSpawnsOneFolderShell(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()          # real shells, real pids -- the real kill is the right one here
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_two_simultaneous_first_opens_share_one_folder_shell(self):
        real_spawn = term_vt.spawn

        def _slow_spawn(cwd, argv, cols, rows):
            time.sleep(0.4)    # hold the lookup-to-register window open so BOTH threads are in it
            return real_spawn(cwd, argv, cols, rows)

        results = {}

        def _open(name):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"cwd": self._tmpdir, "mode": "cwd", "cols": 80, "rows": 24})
            results[name] = h.calls[-1]

        with mock.patch.object(term_vt, "spawn", side_effect=_slow_spawn):
            threads = [threading.Thread(target=_open, args=(n,)) for n in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)

        self.assertEqual(sorted(results), ["a", "b"], "both opens must answer")
        for name, (obj, code) in results.items():
            self.assertEqual(code, 200, (name, obj))
        folders = [p for p in term_vt.PTYS.values() if p.folder and p.cwd == self._tmpdir]
        self.assertEqual(len(folders), 1,
                          "exactly ONE folder shell may exist for a cwd, however many opens raced")
        self.assertEqual(results["a"][0]["tty"], results["b"][0]["tty"],
                          "both racing opens must be handed the same tty")
        self.assertEqual(sorted(r[0]["reused"] for r in results.values()), [False, True],
                          "one open spawned it, the other reused it -- `reused` stays honest")
        self.assertNotIn(self._tmpdir, term_vt._FOLDER_SPAWNING, "the reservation must be released")


# ---------------------------------------------------------------------------------------------- C2
# _folder_retype must not type over another session's claim: the prompt can be showing because
# the refused claude exited and a NEW open (different session) has claimed the shell and is still
# in its pending window.


class TestFolderRetypeRespectsAnotherClaim(unittest.TestCase):
    def setUp(self):
        _stub_kill(self)

    def test_retype_refuses_when_fg_is_claimed_by_a_different_session(self):
        pt = term_vt.Pty(tid="rt1", pid=61616, fd=99, cwd="/tmp/retype")
        pt.folder = True
        claim_b = {"session": "sid-B", "mode": "resume", "started": time.time()}
        pt.fg = claim_b
        pt.fg_pending = True
        injected = []
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=61616), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda p, d: injected.append(d) or True):
            ok = term_vt._folder_retype(pt, "sid-A", ["claude", "--resume", "sid-A"])
        self.assertFalse(ok, "a retry for A must not proceed while the shell is claimed for B")
        self.assertEqual(injected, [], "nothing may be typed over another session's claim")
        self.assertIs(pt.fg, claim_b, "B's claim must be left exactly as it was")
        self.assertTrue(pt.fg_pending, "B's pending window must be left exactly as it was")
        self.assertTrue(pt.notices and "sid-A" in pt.notices[-1]["text"],
                         "the abandoned retry must be reported as a notice, not silently dropped")

    def test_retype_still_retypes_over_its_own_claim(self):
        pt = term_vt.Pty(tid="rt2", pid=61617, fd=99, cwd="/tmp/retype")
        pt.folder = True
        pt.fg = {"session": "sid-A", "mode": "resume", "started": time.time()}
        injected = []
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=61617), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda p, d: injected.append(d) or True):
            ok = term_vt._folder_retype(pt, "sid-A", ["claude", "--resume", "sid-A"])
        self.assertTrue(ok)
        self.assertIn(b"claude --resume sid-A", b"".join(injected))
        self.assertEqual(pt.fg.get("session"), "sid-A")
        self.assertFalse(pt.fg_pending, "the retype's own pending window ends with its Enter")


# ---------------------------------------------------------------------------------------------- C4
# _reap: an overflow pty is dropped immediately, ignoring _REAP_LINGER; a normal one still lingers.


class TestReapOverflow(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_overflow_pty_is_reaped_immediately_ignoring_the_linger(self):
        overflow_pt = term_vt.Pty(tid="ov1")
        overflow_pt.overflow = True
        overflow_pt.done = True
        overflow_pt.ended = time.time()          # just finished -- well within _REAP_LINGER

        normal_pt = term_vt.Pty(tid="norm1")
        normal_pt.overflow = False
        normal_pt.done = True
        normal_pt.ended = time.time()

        term_vt.PTYS["ov1"] = overflow_pt
        term_vt.PTYS["norm1"] = normal_pt

        term_vt._reap()

        self.assertNotIn("ov1", term_vt.PTYS, "a finished overflow pty must not linger at all")
        self.assertIn("norm1", term_vt.PTYS,
                       "a non-overflow finished pty must still honour _REAP_LINGER")


# ---------------------------------------------------------------------------------------------- C5
# close_pty: busy folder pty -> 409 without force, kills with force; overflow pty is dropped from
# PTYS in the same call.


class TestCloseFolderBusyAndOverflow(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_close_busy_folder_pty_without_force_returns_409_and_does_not_kill(self):
        pt = term_vt.Pty(tid="busy1", pid=7001, fd=9)
        pt.folder = True
        pt.fg = {"session": "s", "mode": "resume", "started": time.time()}
        term_vt.PTYS["busy1"] = pt

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=7002), \
             mock.patch.object(pt, "kill") as kill_mock:
            h = _FakeHandler()
            term_vt.close_pty(h, None, {"tty": "busy1"})
            obj, code = h.calls[-1]

        self.assertEqual(code, 409)
        self.assertTrue(obj.get("busy"))
        kill_mock.assert_not_called()
        self.assertIn("busy1", term_vt.PTYS, "a refused close must not drop the pty")
        self.assertFalse(pt.done)

    def test_close_force_on_busy_folder_pty_kills_it(self):
        pt = term_vt.Pty(tid="busy2", pid=7003, fd=9)
        pt.folder = True
        pt.fg = {"session": "s", "mode": "resume", "started": time.time()}
        term_vt.PTYS["busy2"] = pt

        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=7004), \
             mock.patch.object(pt, "kill") as kill_mock:
            h = _FakeHandler()
            term_vt.close_pty(h, None, {"tty": "busy2", "force": True})
            obj, code = h.calls[-1]

        self.assertEqual(code, 200, obj)
        self.assertTrue(obj.get("ok"))
        self.assertIsInstance(obj.get("killed"), list)
        kill_mock.assert_called()

    def test_close_overflow_pty_deletes_it_from_ptys_in_the_same_call(self):
        pt = term_vt.Pty(tid="ov2", pid=0)
        pt.overflow = True
        term_vt.PTYS["ov2"] = pt

        h = _FakeHandler()
        term_vt.close_pty(h, None, {"tty": "ov2"})
        obj, code = h.calls[-1]

        self.assertEqual(code, 200, obj)
        self.assertNotIn("ov2", term_vt.PTYS,
                          "an overflow pty must be removed from PTYS synchronously on close")


# ---------------------------------------------------------------------------------------------- C7/C1
# _live_list rows expose folder/overflow/fg.


class TestLiveListFolderFields(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_live_list_rows_include_folder_overflow_and_fg(self):
        folder_pt = term_vt.Pty(tid="lf1", cwd="/tmp/x")
        folder_pt.folder = True
        folder_pt.overflow = False
        folder_pt.fg = {"session": "s1", "mode": "resume", "started": 123.0}

        overflow_pt = term_vt.Pty(tid="lf2", cwd="/tmp/x")
        overflow_pt.folder = False
        overflow_pt.overflow = True
        overflow_pt.fg = None

        term_vt.PTYS["lf1"] = folder_pt
        term_vt.PTYS["lf2"] = overflow_pt

        rows = {r["tty"]: r for r in term_vt._live_list()}

        self.assertEqual(rows["lf1"]["folder"], True)
        self.assertEqual(rows["lf1"]["overflow"], False)
        self.assertEqual(rows["lf1"]["fg"], {"session": "s1", "mode": "resume", "started": 123.0})
        self.assertEqual(rows["lf2"]["folder"], False)
        self.assertEqual(rows["lf2"]["overflow"], True)
        self.assertIsNone(rows["lf2"]["fg"])


# ---------------------------------------------------------------------------------------------- C5
# REAL PROCESS: close(force=True) on a folder pty must kill BOTH the shell's own process group
# AND a foreground job's SEPARATE process group (job control puts each foreground job in its own
# pgrp -- see the module docstring's C5 rationale and Pty.kill's own comment). A close that only
# does today's plain kill() (killpg on the SHELL's pgid) proves nothing about the foreground job
# BY ITSELF -- the kernel's own session-hangup behaviour (SIGHUP+SIGCONT to the controlling
# terminal's foreground process group when the session leader dies) can take an ordinary `sleep`
# down anyway, exactly as Pty.kill's own docstring describes for the bare-pid-vs-killpg bug this
# mirrors. So the foreground job here explicitly IGNORES SIGHUP (mirroring
# TestProcessGroupKill's escaper in tests/test_term_vt.py) -- it can only die from an explicit
# SIGKILL to its own process group, which is exactly the C5 behaviour under test, not a
# kernel side effect this test would pass without.
#
# This does NOT type into a real interactive login shell to get there. Typing `sleep 60\r` at a
# real `$SHELL -l` prompt and waiting for job control to promote it to a new foreground pgrp
# (the first version of this test) turned out to be unusable in the environment this file was
# authored in: a real login shell spawned via pty.fork() there never became responsive to typed
# input within a 10s window (reproduced 5/5, independent of `\r` vs `\n`, of going through
# `keys()` vs a raw `os.write`, and of PTYS registration -- i.e. not a flake), most likely because
# something in that machine's own shell rc chain blocks waiting on a resource the pty sandbox
# doesn't provide. So instead this drives the exact SAME kernel mechanism (job control's
# `setpgid` + `tcsetpgrp`, which is what a real shell does to hand a foreground job the
# controlling terminal) directly from a small script executed as the pty's OWN argv --
# `_fork_child`-style, no shell in the loop at all -- which is deterministic and matches
# `TestProcessGroupKill`'s already-reliable style in tests/test_term_vt.py.


_FOLDER_SHELL_SCRIPT = """
import os
import signal
import sys
import time

pidfile = sys.argv[1]
child_pid = os.fork()
if child_pid == 0:
    # What a real shell's job control does to hand a foreground job the controlling terminal:
    # its own process group, promoted to foreground on the tty. SIGTTOU is ignored around the
    # tcsetpgrp call because this process is, for one instant, still a BACKGROUND pgrp relative
    # to the terminal's current foreground (the parent's) -- exactly the case a real shell's own
    # job-control code guards against the same way.
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    os.setpgid(0, 0)
    try:
        os.tcsetpgrp(0, os.getpgrp())
    except OSError:
        pass
    # Ignores SIGHUP so the kernel's automatic "session leader died -> SIGHUP the controlling
    # terminal's foreground pgrp" cleanup cannot be what kills this -- only an explicit SIGKILL
    # to its own (separate) process group can, which is exactly the C5 behaviour under test.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    time.sleep(60)
    os._exit(0)
time.sleep(60)
"""


@unittest.skipUnless(_HAS_PTY_FORK, "pty/fork not available on this platform")
class TestCloseKillsForegroundChildForReal(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_close_kills_shell_and_foreground_child(self):
        worktree = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as td:
            script = os.path.join(td, "folder_shell.py")
            pidfile = os.path.join(td, "child.pid")
            with open(script, "w") as f:
                f.write(_FOLDER_SHELL_SCRIPT)

            pt = term_vt.spawn(worktree, ["python3", script, pidfile], 80, 24)
            pt.folder = True
            shell_pid = pt.pid
            self.addCleanup(pt.kill)

            self.assertTrue(_wait_until(lambda: os.path.exists(pidfile), 5),
                             "the foreground child never started")
            with open(pidfile) as f:
                child_pid = int(f.read())

            fg_pgid = [None]

            def child_took_foreground():
                try:
                    pgid = os.tcgetpgrp(pt.fd)
                except OSError:
                    return False
                if pgid != shell_pid:
                    fg_pgid[0] = pgid
                    return True
                return False

            self.assertTrue(_wait_until(child_took_foreground, 3),
                             "the foreground child never became the terminal's foreground "
                             "process group -- cannot prove the two-pgrp kill without it")
            self.assertEqual(fg_pgid[0], child_pid,
                              "job control assigns the foreground job's OWN pid as its pgid")
            self.addCleanup(_best_effort_killpg, fg_pgid)

            term_vt.PTYS[pt.id] = pt
            h = _FakeHandler()
            term_vt.close_pty(h, None, {"tty": pt.id, "force": True})
            obj, code = h.calls[-1]
            self.assertEqual(code, 200, obj)

            def shell_gone():
                try:
                    os.kill(shell_pid, 0)
                    return False
                except ProcessLookupError:
                    return True

            def child_gone():
                try:
                    os.kill(child_pid, 0)
                    return False
                except ProcessLookupError:
                    return True

            self.assertTrue(_wait_until(shell_gone, 2),
                             "the shell process survived close(force=True)")
            self.assertTrue(_wait_until(child_gone, 2),
                             "the SIGHUP-ignoring foreground child survived close(force=True) -- "
                             "closing a folder terminal must SIGKILL both process groups, not "
                             "just the shell's (and must not rely on the kernel's own session "
                             "hangup, which a SIGHUP-ignoring child defeats)")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------------------------- RC
# One resume must yield ONE terminal: a folder shell this request just spawned is queued behind
# its own slow rc files (deferred start), never abandoned for an overflow pty; and a resume of a
# session already running in a non-folder pty attaches instead of typing a second one.


def _timeline_pgid(t0, phases, shell):
    """`_fg_pgid` fake driven by wall time since t0[0]: phases=[(until_s, pgid), ...]; past the end -> shell."""
    def _pgid(pt):
        t = time.time() - t0[0]
        for until, pgid in phases:
            if t < until:
                return pgid
        return shell
    return _pgid


class TestFreshFolderShellQueuesInsteadOfOverflow(unittest.TestCase):
    SHELL, STARTUP_JOB = 61616, 61617

    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        _stub_kill(self)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0

    def _open(self, cwd, phases, startup_wait=None, quiesce=0.05):
        term_gate.session_cwd = lambda sid, resume=False: cwd
        fixture = term_vt.Pty(tid="fresh1", pid=self.SHELL, fd=99, cwd=cwd)
        t0 = [time.time()]
        typed = []
        pending_seen = []

        def _quiet(pt):
            pending_seen.append(pt.fg_pending)
            time.sleep(quiesce)
            return True

        patches = {
            "spawn": mock.patch.object(term_vt, "spawn", return_value=fixture),
            "pgid": mock.patch.object(term_vt, "_fg_pgid",
                                      side_effect=_timeline_pgid(t0, phases, self.SHELL)),
            "quiet_window": mock.patch.object(term_vt, "INJECT_QUIET_WINDOW", 0.2),
            "max_wait": mock.patch.object(term_vt, "INJECT_MAX_WAIT", 0.3),
            "poll": mock.patch.object(term_vt, "FOLDER_STARTUP_POLL", 0.01),
            "key_gap": mock.patch.object(term_vt, "INJECT_KEY_GAP", 0),
            "quiesce": mock.patch.object(term_vt, "_wait_for_quiescence", side_effect=_quiet),
            "write": mock.patch.object(
                term_vt, "_inject_write",
                side_effect=lambda pt, data: typed.append((time.time() - t0[0], data)) or True),
            "backstop": mock.patch.object(term_vt, "_start_backstop", return_value=True),
            "note": mock.patch.object(term_vt, "_feed_note"),
            "resolve": mock.patch.object(term_vt, "resolve_spawned"),
        }
        if startup_wait is not None:
            patches["wait"] = mock.patch.object(term_vt, "FOLDER_STARTUP_WAIT", startup_wait)
        with contextlib.ExitStack() as st:
            m = {k: st.enter_context(p) for k, p in patches.items()}
            h = _FakeHandler()
            t0[0] = time.time()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
            self.assertIsNotNone(fixture.deferred, "a fresh shell must start deferred")
            fixture.deferred.join(15)
            self.assertFalse(fixture.deferred.is_alive())
        return fixture, obj, code, typed, pending_seen, m

    def test_slow_shell_startup_queues_the_resume_instead_of_spawning_overflow(self):
        S, J = self.SHELL, self.STARTUP_JOB
        fixture, obj, code, typed, _p, m = self._open(
            "/tmp/fresh-slow", [(0.05, S), (0.25, J), (0.30, S), (1.0, J)])
        self.assertEqual(code, 200, obj)
        self.assertEqual(m["spawn"].call_count, 1, "exactly one pty may be spawned")
        self.assertEqual(obj["tty"], "fresh1")
        self.assertTrue(obj["folder"])
        self.assertIsNone(obj["notice"])
        self.assertIn(b"claude --resume S1", b"".join(d for _t, d in typed))
        self.assertGreaterEqual(typed[0][0], 1.0, "typed while the rc files still held the tty")
        m["note"].assert_not_called()
        self.assertEqual([p for p in term_vt.PTYS.values() if p.overflow], [])
        self.assertEqual(len(term_vt.PTYS), 1)
        self.assertEqual(fixture.fg.get("session"), "S1")
        self.assertFalse(fixture.fg_pending)

    def test_rc_job_longer_than_inject_max_wait_still_starts_claude(self):
        S, J = self.SHELL, self.STARTUP_JOB
        fixture, obj, code, typed, _p, m = self._open("/tmp/fresh-longrc", [(0.05, S), (1.0, J)])
        self.assertEqual(code, 200, obj)
        self.assertEqual(len([1 for _t, d in typed if d == b"\r"]), 1)
        self.assertGreaterEqual(typed[0][0], 1.0)
        m["note"].assert_not_called()
        self.assertEqual(len(term_vt.PTYS), 1)

    def test_job_after_settle_retries_with_claim_still_pending(self):
        S, J = self.SHELL, self.STARTUP_JOB
        # Timeline (INJECT_QUIET_WINDOW 0.2): SHELL until 0.55, JOB 0.55-1.35, SHELL after. The settle
        # completes at ~0.2-0.3 (>=0.24s inside SHELL); the quiescence stub (0.6s) ends ~0.8-0.9, so the
        # first typing check lands inside JOB (>=0.25s past 0.55, >=0.44s before 1.35) -> deferred attempt
        # fails with the claim pending; the shell re-settles after 1.35 and types once.
        fixture, obj, code, typed, pending_seen, m = self._open(
            "/tmp/fresh-retry", [(0.55, S), (1.35, J)], quiesce=0.6)
        self.assertEqual(code, 200, obj)
        self.assertEqual(len([1 for _t, d in typed if d == b"\r"]), 1)
        self.assertGreaterEqual(typed[0][0], 1.35)
        self.assertEqual(pending_seen, [True, True])
        m["note"].assert_not_called()
        self.assertFalse(fixture.fg_pending)

    def test_startup_wait_expiry_feeds_a_note_and_still_leaves_one_pty(self):
        S, J = self.SHELL, self.STARTUP_JOB
        phases = [(0.05 * (k + 1), J if k % 2 else S) for k in range(200)]
        fixture, obj, code, typed, _p, m = self._open("/tmp/fresh-stuck", phases, startup_wait=0.5)
        self.assertEqual(code, 200, obj)
        self.assertEqual(m["spawn"].call_count, 1)
        self.assertEqual(typed, [], "nothing may be typed into a shell that never reached a prompt")
        self.assertTrue(m["note"].called, "the failure must be surfaced in the terminal")
        self.assertIsNone(fixture.fg, "the claim must be released")
        self.assertFalse(fixture.fg_pending)
        self.assertFalse(fixture.starting)
        self.assertEqual(len(term_vt.PTYS), 1)


class TestInjectArgvGraceAndDeferredMode(unittest.TestCase):
    def setUp(self):
        self.pt = term_vt.Pty(tid="graceP", pid=555, fd=9)
        self.pt.fg_pending = True
        self.pt.fg = {"session": "s", "mode": "resume", "started": time.time() - 3600}
        self.typed = []
        for p in (mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True),
                  mock.patch.object(term_vt, "_inject_write",
                                    side_effect=lambda pt, d: self.typed.append(d) or True),
                  mock.patch.object(term_vt, "INJECT_KEY_GAP", 0)):
            p.start()
            self.addCleanup(p.stop)

    def test_grace_restarts_when_the_line_is_typed(self):
        before = time.time()
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=555):
            ok, why = term_vt._inject_argv(self.pt, ["claude", "--resume", "s"])
            self.assertTrue(ok, why)
            with term_vt._LOCK:
                term_vt._refresh_fg(self.pt)
        self.assertIsNotNone(self.pt.fg, "FG_PENDING_GRACE must count from Enter, not the claim")
        self.assertGreaterEqual(self.pt.fg["started"], before)

    def test_deferred_failure_keeps_claim_pending_and_does_not_wait_for_prompt(self):
        t = time.time()
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=556):
            ok, _why = term_vt._inject_argv(self.pt, ["claude", "--resume", "s"], deferred=True)
        self.assertFalse(ok)
        self.assertLess(time.time() - t, 0.5)
        self.assertTrue(self.pt.fg_pending)
        self.assertEqual(self.typed, [])


class _OpenFixtureBase(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        _stub_kill(self)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0


class TestSessionPtyIgnoresStaleFolderFg(_OpenFixtureBase):
    def _run(self, cwd, fixture, tcgetpgrp):
        term_gate.session_cwd = lambda sid, resume=False: cwd
        term_vt.PTYS[fixture.id] = fixture
        typed = []
        with mock.patch.object(term_vt, "resolve_spawned"), \
             mock.patch.object(term_vt, "spawn") as spawn_mock, \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write",
                               side_effect=lambda pt, d: typed.append(d) or True), \
             mock.patch.object(term_vt, "_start_backstop", return_value=True), \
             mock.patch.object(term_vt, "INJECT_KEY_GAP", 0), \
             mock.patch.object(term_vt.os, "tcgetpgrp", return_value=tcgetpgrp):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        return obj, typed, spawn_mock

    def _fixture(self, cwd, pid):
        fp = term_vt.Pty(tid="stale1", pid=pid, fd=99, cwd=cwd)
        fp.folder, fp.mode = True, "cwd"
        return fp

    def test_resume_after_claude_exited_types_again_instead_of_attaching_to_bare_shell(self):
        fp = self._fixture("/tmp/stale-fg", 42440)
        fp.fg = {"session": "S1", "mode": "resume", "started": time.time() - 60}
        fp.fg_seen_child = True
        obj, typed, spawn_mock = self._run("/tmp/stale-fg", fp, 42440)
        self.assertEqual(obj["tty"], "stale1")
        self.assertIn(b"claude --resume S1", b"".join(typed))
        spawn_mock.assert_not_called()
        self.assertEqual(fp.fg["session"], "S1")
        self.assertFalse(fp.fg_pending)

    def test_pending_claim_still_attaches(self):
        fp = self._fixture("/tmp/stale-pending", 42440)
        claim = {"session": "S1", "mode": "resume", "started": time.time() - 3600}
        fp.fg, fp.fg_pending = claim, True
        obj, typed, spawn_mock = self._run("/tmp/stale-pending", fp, 42440)
        self.assertEqual(obj["tty"], "stale1")
        self.assertEqual(typed, [])
        spawn_mock.assert_not_called()
        self.assertIs(fp.fg, claim)

    def test_live_claude_still_attaches(self):
        fp = self._fixture("/tmp/stale-live", 42440)
        fp.fg = {"session": "S1", "mode": "resume", "started": time.time() - 60}
        fp.fg_seen_child = False
        obj, typed, spawn_mock = self._run("/tmp/stale-live", fp, 42441)
        self.assertEqual(obj["tty"], "stale1")
        self.assertEqual(typed, [])
        spawn_mock.assert_not_called()


class TestUnsettledFolderShellDefersInsteadOfOverflow(_OpenFixtureBase):
    SHELL, JOB, FOREIGN = 43430, 43431, 43439

    def _patches(self, t0, phases, spawn_ret, typed):
        return [
            mock.patch.object(term_vt, "spawn", return_value=spawn_ret),
            mock.patch.object(term_vt, "_fg_pgid",
                              side_effect=_timeline_pgid(t0, phases, self.SHELL)),
            mock.patch.object(term_vt, "INJECT_QUIET_WINDOW", 0.2),
            mock.patch.object(term_vt, "INJECT_MAX_WAIT", 0.1),
            mock.patch.object(term_vt, "FOLDER_STARTUP_POLL", 0.01),
            mock.patch.object(term_vt, "INJECT_KEY_GAP", 0),
            mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True),
            mock.patch.object(term_vt, "_inject_write",
                              side_effect=lambda pt, d: typed.append((time.time() - t0[0], d)) or True),
            mock.patch.object(term_vt, "_start_backstop", return_value=True),
            mock.patch.object(term_vt, "_feed_note"),
            mock.patch.object(term_vt, "resolve_spawned"),
        ]

    def test_resume_into_a_shell_spawned_moments_ago_defers_not_overflows(self):
        cwd = "/tmp/young-shell"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        fp = term_vt.Pty(tid="young1", pid=self.SHELL, fd=99, cwd=cwd)
        fp.folder, fp.mode, fp.startup_done = True, "cwd", False
        term_vt.PTYS["young1"] = fp
        ovf = term_vt.Pty(tid="ovf", pid=0)
        t0, typed = [time.time()], []
        with contextlib.ExitStack() as st:
            ms = [st.enter_context(p) for p in
                  self._patches(t0, [(0.05, self.SHELL), (0.6, self.JOB)], ovf, typed)]
            h = _FakeHandler()
            t0[0] = time.time()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
            if fp.deferred is not None:
                fp.deferred.join(15)
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["tty"], "young1")
        self.assertTrue(obj["reused"])
        self.assertTrue(obj["folder"])
        ms[0].assert_not_called()
        self.assertIsNotNone(fp.deferred)
        self.assertTrue(typed and typed[0][0] >= 0.6, typed)
        self.assertEqual([p for p in term_vt.PTYS.values() if p.overflow], [])

    def test_second_open_same_session_during_deferred_start_attaches(self):
        cwd = "/tmp/young-attach"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        fp = term_vt.Pty(tid="young2", pid=self.SHELL, fd=99, cwd=cwd)
        fp.folder, fp.mode, fp.startup_done = True, "cwd", False
        fp.fg = {"session": "S1", "mode": "resume", "started": time.time()}
        fp.fg_pending = True
        term_vt.PTYS["young2"] = fp
        t0, typed = [time.time()], []
        with contextlib.ExitStack() as st:
            ms = [st.enter_context(p) for p in
                  self._patches(t0, [(1e9, self.JOB)], term_vt.Pty(tid="ovf2", pid=0), typed)]
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(obj["tty"], "young2")
        ms[0].assert_not_called()
        self.assertIsNone(fp.deferred)
        self.assertEqual(typed, [])

    def test_cwd_spawn_marks_startup_done_once_settled(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = tmp.name       # a session-less open requires a real directory
        fp = term_vt.Pty(tid="cwd1", pid=self.SHELL, fd=99, cwd=cwd)
        self.addCleanup(setattr, fp, "closing", True)
        t0, typed = [time.time()], []
        with contextlib.ExitStack() as st:
            for p in self._patches(t0, [(0.3, self.JOB)], fp, typed):
                st.enter_context(p)
            st.enter_context(mock.patch.object(term_vt, "INJECT_QUIET_WINDOW", 0.1))
            h = _FakeHandler()
            t0[0] = time.time()
            term_vt.open_pty(h, None, {"mode": "cwd", "cwd": cwd, "cols": 80, "rows": 24})
            self.assertFalse(fp.startup_done)
            self.assertTrue(_wait_until(lambda: fp.startup_done, 3))

    def test_settled_shell_with_user_job_still_overflows(self):
        cwd = "/tmp/settled-busy"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        fp = term_vt.Pty(tid="busy1", pid=self.SHELL, fd=99, cwd=cwd)
        fp.folder, fp.mode = True, "cwd"
        term_vt.PTYS["busy1"] = fp
        ovf = term_vt.Pty(tid="ovf3", pid=0)
        t0, typed = [time.time()], []
        with contextlib.ExitStack() as st:
            ms = [st.enter_context(p) for p in
                  self._patches(t0, [(1e9, self.FOREIGN)], ovf, typed)]
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        self.assertEqual(ms[0].call_count, 1)
        self.assertTrue(ovf.overflow)
        self.assertEqual(typed, [])


class TestUnsettledShellWithUserInputOverflows(_OpenFixtureBase):
    """A shell the user has typed into counts as settled: with a foreground job of their own it
    must overflow a different session, not be claimed behind a 120s "starting..." state."""
    SHELL, JOB, FOREIGN = 43430, 43431, 43439
    _patches = TestUnsettledFolderShellDefersInsteadOfOverflow._patches

    def test_typed_into_unsettled_shell_with_busy_fg_overflows(self):
        import base64
        cwd = "/tmp/typed-unsettled"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        fp = term_vt.Pty(tid="typed1", pid=self.SHELL, fd=99, cwd=cwd)
        fp.folder, fp.mode, fp.startup_done = True, "cwd", False
        term_vt.PTYS["typed1"] = fp
        ovf = term_vt.Pty(tid="ovf4", pid=0)
        t0, typed = [time.time()], []
        with contextlib.ExitStack() as st:
            ms = [st.enter_context(p) for p in
                  self._patches(t0, [(1e9, self.FOREIGN)], ovf, typed)]
            st.enter_context(mock.patch.object(term_gate, "guard", return_value=True))
            st.enter_context(mock.patch.object(term_vt.os, "write", return_value=3))
            kh = _FakeHandler()
            term_vt.keys(kh, None, {"tty": "typed1",
                                    "data": base64.b64encode(b"npm run dev\r").decode()})
            self.assertEqual(kh.calls[-1][1], 200, kh.calls)
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S2", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        self.assertEqual(ms[0].call_count, 1)
        self.assertTrue(ovf.overflow)
        self.assertIsNone(fp.deferred)
        self.assertFalse(fp.starting)
        self.assertEqual(typed, [])


class TestResumeAttachesToSessionRunningInDedicatedPty(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._session_cwd0 = term_gate.session_cwd
        _stub_kill(self)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)
        term_gate.session_cwd = self._session_cwd0

    def test_resume_of_session_running_in_dedicated_pty_attaches_not_types(self):
        cwd = "/tmp/dedupe-dedicated"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        folder = term_vt.Pty(tid="idlefolder", pid=42430, fd=99, cwd=cwd)
        folder.folder, folder.mode = True, "cwd"
        ded = term_vt.Pty(tid="dedicated1", pid=42431, fd=98, cwd=cwd)
        ded.mode, ded.session = "resume", "S1"
        term_vt.PTYS["idlefolder"], term_vt.PTYS["dedicated1"] = folder, ded
        with mock.patch.object(term_vt, "_inject_write", return_value=True) as w, \
             mock.patch.object(term_vt, "spawn") as spawn_mock, \
             mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42430), \
             mock.patch.object(term_vt, "resolve_spawned"):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["tty"], "dedicated1")
        self.assertTrue(obj["reused"])
        w.assert_not_called()
        spawn_mock.assert_not_called()

    def _fixture(self, cwd, forked=False):
        folder = term_vt.Pty(tid="idlefolder", pid=42430, fd=99, cwd=cwd)
        folder.folder, folder.mode = True, "cwd"
        ded = term_vt.Pty(tid="dedicated1", pid=42431, fd=98, cwd=cwd)
        ded.mode, ded.session, ded.forked = "resume", "S1", forked
        term_vt.PTYS["idlefolder"], term_vt.PTYS["dedicated1"] = folder, ded
        return folder, ded

    def test_resume_scan_is_new_only(self):
        cwd = "/tmp/dedupe-newonly"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        self._fixture(cwd)
        with mock.patch.object(term_vt, "_inject_write", return_value=True), \
             mock.patch.object(term_vt, "spawn"), \
             mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42430), \
             mock.patch.object(term_vt, "resolve_spawned") as rs:
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
        rs.assert_called_once_with(throttle=0, new_only=True)

    def test_resume_never_attaches_to_a_forked_copy(self):
        cwd = "/tmp/dedupe-forked"
        term_gate.session_cwd = lambda sid, resume=False: cwd
        folder, ded = self._fixture(cwd, forked=True)
        typed = []
        with mock.patch.object(term_vt, "resolve_spawned"), \
             mock.patch.object(term_vt, "spawn") as spawn_mock, \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write",
                               side_effect=lambda pt, d: typed.append(d) or True), \
             mock.patch.object(term_vt, "_start_backstop", return_value=True), \
             mock.patch.object(term_vt, "INJECT_KEY_GAP", 0), \
             mock.patch.object(term_vt.os, "tcgetpgrp", return_value=42430):
            h = _FakeHandler()
            term_vt.open_pty(h, None, {"session": "S1", "mode": "resume", "cols": 80, "rows": 24})
            obj, code = h.calls[-1]
        self.assertEqual(code, 200, obj)
        self.assertNotEqual(obj["tty"], "dedicated1")
        self.assertEqual(obj["tty"], "idlefolder")
        self.assertTrue(typed)

    def test_session_pty_skips_forked(self):
        _, ded = self._fixture("/tmp/dedupe-unit", forked=True)
        with term_vt._LOCK:
            self.assertIsNone(term_vt._session_pty("S1"))
            ded.forked = False
            self.assertIs(term_vt._session_pty("S1"), ded)
