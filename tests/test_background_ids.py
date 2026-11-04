"""`background_id`: a session id (or the job it was parked into) hosted by a live daemon REPL.

A parked session FORKS: the job gets its own session id and the original transcript ends with
`{"type":"continued-in", ..., "continuedInSessionId": J}` (the CLI reads it from the tail and a later
completed turn voids it). Run one module per process:

    TRACKER_AUTH= python3 -m unittest tests.test_background_ids -v
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from aitracker import config
from aitracker.providers import claude as cp

O = "11111111-1111-4111-8111-111111111111"
J = "22222222-2222-4222-8222-222222222222"
K = "33333333-3333-4333-8333-333333333333"


def _line(**kw):
    return json.dumps(kw, separators=(",", ":")) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        os.mkdir(os.path.join(self.proj, "p"))
        self.live = {}
        for p in (mock.patch.object(config, "PROJECTS", self.proj),
                  mock.patch.object(cp, "daemon_repl_pid", lambda sid: self.live.get(sid, 0))):
            p.start()
            self.addCleanup(p.stop)

    def transcript(self, sid, *lines, raw=None):
        path = os.path.join(self.proj, "p", sid + ".jsonl")
        with open(path, "w") as fh:
            fh.write(raw if raw is not None else "".join(lines))
        return path


class TestContinuedIn(_Base):
    def test_marker_as_newest_record(self):
        path = self.transcript(O, _line(type="user", message="hi"), _line(type="assistant"),
                               _line(type="continued-in", sessionId=O, continuedInSessionId=J),
                               _line(type="last-prompt"))
        self.assertEqual(cp._continued_in(path), J)

    def test_voided_by_a_later_user_or_assistant_line(self):
        for later in ("user", "assistant"):
            path = self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J),
                                   _line(type=later))
            self.assertEqual(cp._continued_in(path), "", later)

    def test_no_marker_missing_file_and_garbage(self):
        self.assertEqual(cp._continued_in(self.transcript(O, _line(type="user"))), "")
        self.assertEqual(cp._continued_in(os.path.join(self.proj, "nope.jsonl")), "")
        self.assertEqual(cp._continued_in(self.transcript(O, raw='{"type":"continued-in"  not json\n')), "")

    def test_unsafe_id_is_rejected(self):
        for bad in ("../../etc/passwd", "a/b", "", 7, None):
            path = self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=bad))
            self.assertEqual(cp._continued_in(path), "", repr(bad))

    def test_reads_only_the_tail_of_a_big_transcript(self):
        filler = _line(type="user", message="x" * 1000) * 300          # ~300 KB
        path = self.transcript(O, filler, _line(type="continued-in", sessionId=O, continuedInSessionId=J))
        self.assertEqual(cp._continued_in(path), J)
        path = self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J), filler)
        self.assertEqual(cp._continued_in(path), "", "a marker buried under 300 KB of later turns is not current")
        sys_filler = _line(type="system", subtype="x", content="y" * 1000) * 300
        path = self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J), sys_filler)
        self.assertEqual(cp._continued_in(path), "", "only the 96 KB tail is read, like the CLI")


class TestBackgroundIds(_Base):
    def test_background_id_direct(self):
        self.live[O] = 10
        self.assertEqual(cp.background_id(O), O)

    def test_background_id_follows_continued_in(self):
        self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J))
        self.live[J] = 20
        self.assertEqual(cp.background_id(O), J)

    def test_continued_in_voided_by_later_turn(self):
        self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J), _line(type="user"))
        self.live[J] = 20
        self.assertEqual(cp.background_id(O), "")

    def test_background_id_empty_when_job_dead(self):
        self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J))
        self.assertEqual(cp.background_id(O), "")

    def test_one_hop_only(self):
        self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J))
        self.transcript(J, _line(type="continued-in", sessionId=J, continuedInSessionId=K))
        self.live[K] = 30
        self.assertEqual(cp.background_id(O), "", "O -> J -> K is not followed")

    def test_unknown_session_and_errors(self):
        self.assertEqual(cp.background_id("nope"), "")
        with mock.patch.object(cp, "find_session", side_effect=RuntimeError):
            self.assertEqual(cp.background_id(O), "")

    def test_never_writes(self):
        path = self.transcript(O, _line(type="continued-in", sessionId=O, continuedInSessionId=J))
        before = (os.path.getmtime(path), os.path.getsize(path))
        self.live[J] = 20
        cp.background_id(O)
        self.assertEqual(before, (os.path.getmtime(path), os.path.getsize(path)))


if __name__ == "__main__":
    unittest.main()
