"""Config login terminal: `claude auth login` runs in a dedicated pty the tracker never lists as a managed
terminal, records only {at, outcome, ok_at} when it ends, and deletes nothing under ~/.claude."""
import os
import tempfile
import unittest
from unittest import mock

from aitracker import config, store, term_vt
from aitracker.providers import claude
from tests import test_folder_terminal as tft


def _pty(tid="L1", login="claudeai", rc=0, **kw):
    # pid=0 / fd=-1: finish() touches no real process or descriptor
    pt = term_vt.Pty(tid=tid, pid=0, fd=-1, cwd="/tmp")
    pt.overflow, pt.login, pt.rc = True, login, rc
    for k, v in kw.items():
        setattr(pt, k, v)
    return pt


class _Recorder(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "last_login.json")
        p = mock.patch.object(config, "LAST_LOGIN_FILE", self.path, create=True)
        p.start()
        self.addCleanup(p.stop)
        self._ptys0 = dict(term_vt.PTYS)
        self.addCleanup(self._restore)

    def _restore(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)


class LoginOutcome(_Recorder):
    def test_outcome_mapping(self):
        cases = (
            (dict(rc=0), "ok"),
            (dict(rc=0, closing=True), "ok"),
            (dict(rc=1), "failed"),
            (dict(rc=130), "closed"),
            (dict(rc=-9), "closed"),
            (dict(rc=None), "closed"),
            (dict(rc=1, closing=True), "closed"),
            (dict(rc=-9, login_timed_out=True), "timeout"),
            (dict(rc=None, login_timed_out=True), "timeout"),
        )
        for kw, want in cases:
            with self.subTest(kw=kw):
                self.assertEqual(term_vt._login_outcome(_pty(**kw)), want)

    def test_finish_records_before_done(self):
        pt = _pty(rc=0)
        seen = []
        real = store.record_login

        def spy(outcome, now=None):
            seen.append((outcome, pt.done))
            return real(outcome, now)
        with mock.patch.object(store, "record_login", side_effect=spy):
            pt.finish()
        self.assertEqual(seen, [("ok", False)])         # recorded while done is still False
        self.assertTrue(pt.done)
        self.assertEqual(store.load_last_login()["outcome"], "ok")

    def test_non_login_pty_records_nothing(self):
        pt = _pty(login="", rc=0)
        pt.finish()
        self.assertFalse(os.path.exists(self.path))

    def test_raise_is_swallowed(self):
        pt = _pty(rc=0)
        with mock.patch.object(store, "record_login", side_effect=RuntimeError("disk")):
            pt.finish()
        self.assertTrue(pt.done)

    def test_never_deletes_a_login_transcript(self):
        self.assertFalse(hasattr(claude, "remove_login_transcript"))
        self.assertFalse(hasattr(claude, "login_transcript_state"))
        with mock.patch("os.remove") as rm, mock.patch("os.unlink") as ul:
            _pty(rc=0).finish()
        rm.assert_not_called()
        ul.assert_not_called()


class LoginWatch(_Recorder):
    def setUp(self):
        super().setUp()
        for name, val in (("LOGIN_POLL", 0.01), ("LOGIN_WATCH_MAX", 0.1)):
            p = mock.patch.object(term_vt, name, val)
            p.start()
            self.addCleanup(p.stop)

    def test_timeout_kills_own_group(self):
        pt = _pty(rc=None)
        with mock.patch.object(term_vt.Pty, "kill", autospec=True) as k:
            term_vt._login_watch(pt)
        k.assert_called_once_with(pt)
        self.assertTrue(pt.login_timed_out)

    def test_done_pty_is_left_alone(self):
        pt = _pty(rc=0)
        pt.done = True
        with mock.patch.object(term_vt.Pty, "kill", autospec=True) as k:
            term_vt._login_watch(pt)
        k.assert_not_called()
        self.assertFalse(pt.login_timed_out)
        self.assertFalse(os.path.exists(self.path))     # the watcher records nothing

    def test_kill_raise_is_swallowed(self):
        with mock.patch.object(term_vt.Pty, "kill", autospec=True, side_effect=OSError("x")):
            term_vt._login_watch(_pty(rc=None))


class LoginPtyHidden(unittest.TestCase):
    def setUp(self):
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self.addCleanup(self._restore)
        tft._stub_kill(self)
        self.lp = _pty("L1", "claudeai", rc=None)
        self.other = term_vt.Pty(tid="T1", pid=0, fd=-1, cwd="/tmp")
        term_vt.PTYS["L1"], term_vt.PTYS["T1"] = self.lp, self.other

    def _restore(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def test_term_list_hides_login_pty(self):
        with mock.patch.object(term_vt, "_live_list", wraps=term_vt._live_list) as ll:
            h = tft._FakeHandler()
            with mock.patch.object(term_vt.term_gate, "guard", return_value=True), \
                 mock.patch.object(term_vt, "resolve_spawned"):
                term_vt.term_list(h, None)
        self.assertEqual(ll.call_args.kwargs.get("hide_login"), True)
        self.assertEqual([t["tty"] for t in h.calls[-1][0]["terminals"]], ["T1"])

    def test_429_lists_login_pty(self):
        with term_vt._LOCK:
            self.assertEqual({t["tty"] for t in term_vt._live_list("")}, {"L1", "T1"})
            self.assertEqual({t["tty"] for t in term_vt._live_list("", hide_login=True)}, {"T1"})

    def test_live_count_still_counts_login_pty(self):
        with term_vt._LOCK:
            self.assertEqual(term_vt._live_count(), 2)

    def test_resolve_spawned_never_latches_login_pty(self):
        self.lp.mode = "new"
        with mock.patch.object(claude, "newest_session_in_cwd", return_value="sid-1"):
            term_vt.resolve_spawned(throttle=0)
        self.assertEqual(self.lp.spawned, "")

    def test_upgrade_candidates_skip_login_pty(self):
        seen = []
        with mock.patch.object(term_vt, "_refresh_fg", side_effect=seen.append), \
             mock.patch.object(term_vt, "_provider", return_value=None):
            self.lp.folder = self.other.folder = True
            term_vt.upgrade_candidates(light=True)
        self.assertEqual([p.id for p in seen], ["T1"])


class LoginMarkedBeforeReader(unittest.TestCase):
    def test_login_marked_before_reader_starts(self):
        import time
        seen = []
        with mock.patch.object(term_vt, "_reader", side_effect=lambda pt: seen.append(pt.login)):
            pt = term_vt.spawn("/tmp", ["/usr/bin/true"], 80, 24, login="claudeai")
            for _ in range(100):
                if seen:
                    break
                time.sleep(0.02)
        for fn, a in ((os.waitpid, (pt.pid, 0)), (os.close, (pt.fd,))):
            try:
                fn(*a)
            except OSError:
                pass
        self.assertEqual(seen, ["claudeai"])


if __name__ == "__main__":
    unittest.main()
