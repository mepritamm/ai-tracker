"""Log in / Switch account cleanup: the /login-only transcript is recognised and deleted, nothing else."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from aitracker.providers import claude

SID = "2028e7c5-d85d-4a86-8227-0edc7c62ff42"
CAVEAT = ("<local-command-caveat>The command below was run directly in Claude Code, not sent to you "
          "as a request.</local-command-caveat>")
CMD = "<command-name>/login</command-name>\n  <command-message>login</command-message>\n  <command-args></command-args>"


def _u(text, meta=False):
    d = {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}}
    if meta:
        d["isMeta"] = True
    return d


def records(stdout="Login successful", extra=()):
    r = [{"type": "last-prompt"}, {"type": "mode"}, {"type": "permission-mode"}, {"type": "session-owner"},
         {"type": "tools-used"}, {"type": "file-history-snapshot"},
         {"type": "attachment", "isSidechain": False, "attachment": {"type": "hook_success"}},
         _u(CAVEAT, meta=True), _u(CMD)]
    if stdout:
        r.append(_u("<local-command-stdout>%s</local-command-stdout>" % stdout))
    r += list(extra) + [{"type": "last-prompt"}, {"type": "cost-state"}]
    return r


class _Proj(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.d = os.path.join(self.root, "-Users-x")
        os.makedirs(self.d)
        p = mock.patch.object(config, "PROJECTS", self.root)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, recs, sid=SID, raw_tail=""):
        path = os.path.join(self.d, sid + ".jsonl")
        with open(path, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in recs) + "\n" + raw_tail)
        return path


class LoginTranscriptState(_Proj):
    def st(self, recs, **kw):
        self.write(recs, **kw)
        return claude.login_transcript_state(SID)

    def test_success_is_ok(self):
        self.assertEqual(self.st(records()), "ok")

    def test_atis_latch_is_login_metadata(self):
        self.assertEqual(self.st(records(extra=[{"type": "atis-latch", "atis": ""}])), "ok")

    def test_interrupted_state(self):
        self.assertEqual(self.st(records("Login interrupted")), "interrupted")

    def test_no_stdout_yet_is_pending(self):
        self.assertEqual(self.st(records(None)), "pending")

    def test_missing_file_is_pending(self):
        self.assertEqual(claude.login_transcript_state(SID), "pending")

    def test_truncated_last_line_is_pending_but_bad_middle_is_other(self):
        self.write(records(), raw_tail='{"type": "us')
        self.assertEqual(claude.login_transcript_state(SID), "pending")
        path = os.path.join(self.d, SID + ".jsonl")
        with open(path, "w") as fh:
            fh.write('{"type": "mo\n' + json.dumps(records()[0]) + "\n")
        self.assertEqual(claude.login_transcript_state(SID), "other")

    def test_mix_of_logins_successful_wins(self):
        extra = [_u(CAVEAT, meta=True), _u(CMD), _u("<local-command-stdout>Login interrupted</local-command-stdout>")]
        self.assertEqual(self.st(records("Login successful", extra)), "ok")

    def test_real_prompt_or_assistant_is_other(self):
        self.assertEqual(self.st(records(extra=[_u("hi")])), "other")
        self.assertEqual(self.st(records(extra=[{"type": "assistant", "message": {"content": CMD}}])), "other")

    def test_allowlist_rejects_unknown_record_types(self):
        m = {"content": CMD}      # a looks-like-login body must not rescue an unknown record type
        for extra in ({"type": "system", "message": m}, {"type": "continued-in", "message": m},
                      {"type": "queue-operation", "message": m},
                      {"type": "attachment", "attachment": {"type": "queued_command"}},
                      {"type": "user", "isSidechain": True, "message": {"content": CMD}}):
            self.assertEqual(self.st(records(extra=[extra])), "other", extra)

    def test_non_text_user_part_is_other(self):
        part = _u([{"type": "tool_result", "content": "x"}])
        self.assertEqual(self.st(records(extra=[part])), "other")

    def test_oversize_is_other(self):
        with mock.patch.object(claude, "LOGIN_MAX_BYTES", 10):
            self.assertEqual(self.st(records()), "other")


class RemoveLoginTranscript(_Proj):
    def test_ok_and_interrupted_are_deleted_only_that_file(self):
        for out in ("Login successful", "Login interrupted"):
            path = self.write(records(out))
            other = self.write(records(), sid="aaaaaaaa-0000-4000-8000-000000000000")
            sib = os.path.join(self.d, SID)
            os.makedirs(sib, exist_ok=True)
            self.assertTrue(claude.remove_login_transcript(SID))
            self.assertFalse(os.path.exists(path))
            self.assertTrue(os.path.exists(other))
            self.assertTrue(os.path.isdir(sib))

    def test_pending_and_other_are_kept(self):
        for recs in (records(None), records(extra=[_u("hi")])):
            path = self.write(recs)
            self.assertFalse(claude.remove_login_transcript(SID))
            self.assertTrue(os.path.exists(path))

    def test_missing_file_false(self):
        self.assertFalse(claude.remove_login_transcript(SID))

    def test_path_outside_projects_refused(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        real = os.path.join(outside, SID + ".jsonl")
        with open(real, "w") as fh:
            fh.write("\n".join(json.dumps(r) for r in records()) + "\n")
        os.symlink(real, os.path.join(self.d, SID + ".jsonl"))
        self.assertFalse(claude.remove_login_transcript(SID))
        self.assertTrue(os.path.exists(real))

    def test_basename_guard(self):
        path = self.write(records(), sid="other")
        with mock.patch.object(claude, "find_session", return_value=path):
            self.assertFalse(claude.remove_login_transcript(SID))
        self.assertTrue(os.path.exists(path))   # basename is "other.jsonl", not "<SID>.jsonl"

    def test_never_raises(self):
        with mock.patch.object(claude, "find_session", side_effect=RuntimeError):
            self.assertFalse(claude.remove_login_transcript(SID))


class VanishedTranscript(_Proj):
    def test_list_and_search_survive_a_file_deleted_after_the_glob(self):
        other = "bbbbbbbb-0000-4000-8000-000000000000"
        real = self.write([_u("hello needle")], sid=other)
        ghost = os.path.join(self.d, "gone.jsonl")
        with mock.patch.object(claude.glob, "glob", return_value=[ghost, real]):
            rows = claude.list_sessions()
            hits = claude.search_sessions("needle")
        self.assertIn(other, [r["id"] for r in rows])
        self.assertEqual([r["id"] for r in hits], [other])


class LoginWatch(_Proj):
    def setUp(self):
        super().setUp()
        for name, val in (("LOGIN_POLL", 0.01), ("LOGIN_SETTLE", 0.01), ("CLOSE_CONFIRM_POLL", 0.01),
                          ("CLOSE_CONFIRM_WAIT", 0.3), ("LOGIN_WATCH_MAX", 0.5)):
            p = mock.patch.object(term_vt, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.pt = term_vt.Pty(tid="L1", pid=4242, fd=97, cwd=self.root)
        self.pt.overflow, self.pt.spawned = True, SID
        self._ptys0 = dict(term_vt.PTYS)
        self.addCleanup(self._restore)
        self.stop_calls = []
        self.stop_result = {"confirmed": True}

        def fake_stop(tty, sid, pid, thin=False):
            self.stop_calls.append((tty, sid, pid))
            self.pt.done = True
            return self.stop_result
        p = mock.patch.object(term_vt, "stop_for_upgrade", side_effect=fake_stop)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(term_vt, "_feed_note")
        self.note = p.start()
        self.addCleanup(p.stop)
        self.path = os.path.join(self.d, SID + ".jsonl")

    def _restore(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def run_watch(self):
        term_vt._login_watch(self.pt, SID)

    def test_success_stops_then_deletes(self):
        self.write(records())
        self.run_watch()
        self.assertEqual(self.stop_calls, [("L1", SID, 4242)])
        self.note.assert_called_once()
        self.assertFalse(os.path.exists(self.path))

    def test_stop_not_confirmed_keeps(self):
        self.write(records())
        self.stop_result = {"confirmed": False}
        self.run_watch()
        self.assertEqual(len(self.stop_calls), 1)
        self.assertTrue(os.path.exists(self.path))

    def test_closed_during_settle_deletes_after_done(self):
        self.write(records())
        self.stop_result = {"closed": True}
        self.run_watch()
        self.assertFalse(os.path.exists(self.path))

    def test_interrupted_deleted_only_after_done(self):
        self.write(records("Login interrupted"))
        seen = []

        def finish():
            time.sleep(0.1)
            seen.append(os.path.exists(self.path))      # still there while the pty lives
            self.pt.closing = True
            self.pt.done = True
        t = threading.Thread(target=finish)
        t.start()
        self.run_watch()
        t.join()
        self.assertEqual(seen, [True])
        self.assertEqual(self.stop_calls, [])
        self.assertFalse(os.path.exists(self.path))

    def test_interrupted_never_deleted_while_pty_lives(self):
        self.write(records("Login interrupted"))
        self.run_watch()                                # times out: pt never done
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(os.path.exists(self.path))

    def test_interrupted_closing_but_not_done_keeps(self):
        self.write(records("Login interrupted"))
        self.pt.closing = True                          # reaper has not caught up: no delete
        self.run_watch()
        self.assertTrue(os.path.exists(self.path))

    def test_pending_then_closed_keeps(self):
        self.write(records(None))
        self.pt.closing = self.pt.done = True
        self.run_watch()
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(os.path.exists(self.path))

    def test_real_prompt_keeps(self):
        self.write(records(extra=[_u("hi")]))
        t0 = time.time()
        with mock.patch.object(term_vt, "LOGIN_WATCH_MAX", 5.0):
            self.run_watch()
        self.assertLess(time.time() - t0, 1.0)          # gave up at once, did not poll to the timeout
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(os.path.exists(self.path))

    def test_settle_flip_to_other_does_not_stop(self):
        self.write(records())
        real = claude.login_transcript_state
        calls = []

        def flip(sid):
            calls.append(1)
            return real(sid) if len(calls) == 1 else "other"
        with mock.patch.object(claude, "login_transcript_state", side_effect=flip):
            self.run_watch()
        self.assertEqual(self.stop_calls, [])
        self.assertTrue(os.path.exists(self.path))

    def test_timeout_keeps(self):
        self.write(records(None))
        self.run_watch()
        self.assertTrue(os.path.exists(self.path))

    def test_provider_none_and_raise_keep(self):
        self.write(records())
        with mock.patch.object(term_vt, "_provider", return_value=None):
            self.run_watch()
        self.assertTrue(os.path.exists(self.path))
        with mock.patch.object(claude, "login_transcript_state", side_effect=RuntimeError):
            self.run_watch()                            # swallowed
        self.assertTrue(os.path.exists(self.path))

    def test_sibling_latch_cleared_after_removal(self):
        self.write(records())
        sib = term_vt.Pty(tid="F1", pid=1, fd=96, cwd=self.root)
        sib.spawned, sib.folder, sib.fg = SID, True, {"session": SID}
        term_vt.PTYS["F1"] = sib
        self.run_watch()
        self.assertEqual((sib.spawned, sib.fg["session"]), ("", ""))


if __name__ == "__main__":
    unittest.main()
