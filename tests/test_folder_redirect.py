"""A moved session's OLD row opens the live conversation (docs/folder-terminal-reuse-plan.md,
Decision 1): when original session O was parked into daemon job J, `open_pty(O, resume)` runs J.
Separate module so the redirect can be reverted alone. Run one module per process:

    TRACKER_AUTH= python3 -m unittest tests.test_folder_redirect -v
"""
import time
import unittest
from unittest import mock

from aitracker import config, term_gate, term_vt
from aitracker.providers import claude as claude_provider
from tests.test_folder_terminal import _FakeHandler, _stub_kill

CWD = "/tmp/redirect-cwd"
SHELL = 42424
O = "11111111-1111-4111-8111-111111111111"
J = "22222222-2222-4222-8222-222222222222"
OTHER = "99999999-9999-4999-8999-999999999999"


class _Base(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        _stub_kill(self)
        self.typed = []
        self.cwds = {O: CWD, J: CWD, OTHER: CWD}
        self.targets = {O: J, J: J}               # what the roster says: O's live home is J
        self.fp = term_vt.Pty(tid="folder-1", pid=SHELL, fd=99, cwd=CWD)
        self.fp.folder, self.fp.mode, self.fp.startup_done = True, "cwd", True
        self.fp.screen = term_vt.Screen(cols=80, rows=24)
        term_vt.PTYS[self.fp.id] = self.fp
        self.overflow = term_vt.Pty(tid="overflow-1", pid=0)
        self._session_cwd0 = term_gate.session_cwd
        term_gate.session_cwd = lambda sid, resume=False: self.cwds.get(sid, "")
        self.state = {"pg": SHELL}

        def write(pt, data):
            self.typed.append(data)
            return True

        for p in (mock.patch.object(term_vt.os, "tcgetpgrp", lambda fd: self.state["pg"]),
                  mock.patch.object(term_vt, "_background_target", lambda sid: self.targets.get(sid, "")),
                  mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True),
                  mock.patch.object(term_vt, "_inject_write", write),
                  mock.patch.object(term_vt, "_resume_backstop"),
                  mock.patch.object(term_vt, "spawn", return_value=self.overflow)):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_gate.session_cwd = self._session_cwd0
        for pt in list(term_vt.PTYS.values()):
            pt.kill()
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def open(self, sid, mode="resume"):
        h = _FakeHandler()
        term_vt.open_pty(h, None, {"session": sid, "mode": mode, "cols": 80, "rows": 24})
        obj, code = h.calls[-1]
        return obj, code


class TestRedirect(_Base):
    def test_opening_original_runs_the_live_job(self):
        obj, code = self.open(O)
        self.assertEqual(code, 200, obj)
        self.assertIn(b"claude --resume " + J.encode(), b"".join(self.typed))
        self.assertNotIn(b"--resume " + O.encode(), b"".join(self.typed))
        self.assertEqual(obj["session"], J, "the client binds the tty to what actually runs")
        self.assertEqual(self.fp.fg["session"], J)
        with term_vt._LOCK:
            self.assertTrue(term_vt._pty_owned(self.fp, J))

    def test_job_without_a_transcript_is_still_resumed_in_the_originals_folder(self):
        """A freshly parked job has no transcript (so no cwd of its own) until its first turn; the
        old row must already open it, in the ORIGINAL's folder."""
        del self.cwds[J]
        obj, code = self.open(O)
        self.assertEqual(code, 200, obj)
        self.assertIn(b"--resume " + J.encode(), b"".join(self.typed))
        self.assertEqual(obj["session"], J)

    def test_job_that_moved_to_another_folder_opens_there(self):
        """Sessions move into worktrees: when the job's transcript has a different cwd than the
        original's, the shell opens in the JOB's."""
        moved = "/tmp/redirect-moved-worktree"
        self.cwds[J] = moved
        moved_fp = term_vt.Pty(tid="folder-moved", pid=SHELL, fd=99, cwd=moved)
        moved_fp.folder, moved_fp.mode, moved_fp.startup_done = True, "cwd", True
        moved_fp.screen = term_vt.Screen(cols=80, rows=24)
        term_vt.PTYS[moved_fp.id] = moved_fp
        obj, code = self.open(O)
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["tty"], "folder-moved", "the shell in the JOB's folder took it, not the original's")
        self.assertIn(b"--resume " + J.encode(), b"".join(self.typed))

    def test_original_with_a_missing_folder_404s_like_today(self):
        del self.cwds[O]
        del self.cwds[J]
        obj, code = self.open(O)
        self.assertEqual(code, 404, obj)
        self.assertEqual(self.typed, [])

    def test_non_background_session_is_not_redirected(self):
        obj, code = self.open(OTHER)
        self.assertEqual(code, 200, obj)
        self.assertIn(b"--resume " + OTHER.encode(), b"".join(self.typed))
        self.assertEqual(obj["session"], OTHER)

    def test_job_itself_is_unchanged(self):
        obj, code = self.open(J)
        self.assertEqual(obj["session"], J)
        self.assertIn(b"--resume " + J.encode(), b"".join(self.typed))

    def test_new_and_cwd_modes_never_redirect(self):
        for mode in ("new", "cwd"):
            self.typed.clear()
            self.fp.fg = None
            obj, code = self.open(O, mode)
            self.assertEqual(code, 200, obj)
            self.assertNotIn(J.encode(), b"".join(self.typed), mode)

    def test_original_with_live_parked_pane_still_peeks(self):
        """The pane that runs O (a parked TUI) is still a peek for O: nothing typed, nothing signalled."""
        self.fp.fg = {"session": O, "mode": "resume", "started": time.time() - 60, "grants": {O}}
        self.fp.fg_seen_child = True
        self.state["pg"] = 55555
        obj, code = self.open(O)
        self.assertEqual(code, 200, obj)
        self.assertEqual(obj["tty"], "folder-1")
        self.assertEqual(self.typed, [])
        self.assertEqual(obj["session"], O, "the peek binds the session the pane is labelled with")
        self.assertFalse(self.overflow.overflow)

    def test_mismatch_is_unchanged_for_a_stale_viewer(self):
        self.open(O)
        with term_vt._LOCK:
            self.assertFalse(term_vt._pty_owned(self.fp, OTHER))
            self.assertFalse(term_vt._pty_owned(self.fp, O),
                             "a view bound to O (the pre-redirect page) is not the claimant: it must reopen")


class TestRedirectWithSwap(_Base):
    def test_non_background_original_never_takes_a_pane_over(self):
        """Nothing hosts O, so a busy thin-client pane must be left alone (dedicated pty)."""
        A = "aaaaaaaa-1111-2222-3333-444444444444"
        self.cwds[A] = CWD
        self.targets.pop(O)
        self.fp.fg = {"session": A, "mode": "resume", "started": time.time() - 60, "grants": {A}}
        self.fp.fg_seen_child = True
        self.state["pg"] = 42500
        killed = []
        with mock.patch.object(term_vt.os, "killpg", lambda pg, sig: killed.append(pg)), \
             mock.patch.object(term_vt, "_thin_client_short", lambda pg: "aaaaaaaa"), \
             mock.patch.object(term_vt, "_shell_cwd", lambda pid: CWD), \
             mock.patch.object(claude_provider, "daemon_repl_pid", lambda sid: 1 if sid == A else 0):
            obj, code = self.open(O)
        self.assertEqual(killed, [])
        self.assertEqual(obj["tty"], "overflow-1")

    def test_original_row_takes_over_an_unwatched_client_pane(self):
        """O's open resolves to J and then follows the normal takeover rules for J."""
        A = "aaaaaaaa-1111-2222-3333-444444444444"
        self.cwds[A] = CWD
        self.targets[A] = A
        self.fp.fg = {"session": A, "mode": "resume", "started": time.time() - 60, "grants": {A}}
        self.fp.fg_seen_child = True
        self.state["pg"] = 42500
        killed = []

        def killpg(pg, sig):
            killed.append(pg)
            self.state["pg"] = SHELL

        with mock.patch.object(term_vt.os, "killpg", killpg), \
             mock.patch.object(term_vt, "_thin_client_short", lambda pg: "aaaaaaaa"), \
             mock.patch.object(term_vt, "_shell_cwd", lambda pid: CWD), \
             mock.patch.object(claude_provider, "daemon_repl_pid", lambda sid: 1 if sid in (A, J) else 0), \
             mock.patch.object(claude_provider, "session_label", lambda sid: "Alpha"):
            obj, code = self.open(O)
        self.assertEqual(code, 200, obj)
        self.assertEqual(killed, [42500])
        self.assertEqual(obj["session"], J)
        self.assertIn(b"--resume " + J.encode(), b"".join(self.typed))


if __name__ == "__main__":
    unittest.main()
