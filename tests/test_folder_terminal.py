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
        term_gate.session_cwd = lambda sid: cwd

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
        term_gate.session_cwd = lambda sid: cwd

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
        self.assertIsNotNone(obj.get("notice"), "an overflow open must carry a notice for the client")


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
        term_gate.session_cwd = lambda sid: cwd

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
