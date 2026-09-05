"""THE BOARD-TAB BUG (user report: "the board tab 'working' and others arent
working at all") -- root cause and fix.

Two fields that the Board (aitracker/web/ext_cr_board.js) and the classic
sidebar (aitracker/web/app.js) both rely on agreeing with each other were
computed from DIFFERENT inputs in providers/claude.py's list_sessions():

  * `mtime` (providers/claude.py:538, from `_mtime_and_bg()`) folds in
    background-agent transcript activity -- max(main transcript mtime,
    every live background-agent transcript's mtime). So a session with
    running background agents stays LIVE even after its own foreground
    turn has finished.
  * `ended` (providers/claude.py:537, from `_tail_scan()`) reads ONLY the
    main transcript -- it has no idea background agents exist at all.

So a session whose foreground turn closed with assistant text, but which
still has N background agents running, is simultaneously `live == True`
(fresh mtime) AND `ended == True` (foreground already "finished"). This
module proves providers/claude.py really emits that exact combination off
a real on-disk transcript (not just a hand-built test dict -- see
tests/test_cr_logic.py for the JS-side pure-function/DOM coverage that
consumes fixtures shaped like this), and that the two fixes hold:

  1. `now_line`'s background-agent branch (previously gated behind
     `not sm["ended"]`, making it unreachable for exactly this shape) is
     now reachable and reports the running agents instead of "".
  2. providers/auggie.py has no background-agent concept at all (`bg` is
     always 0), so it can never hit this asymmetry -- confirmed directly
     below rather than assumed.

The JS-side fix (ext_cr_board.js's shared `isWorking()` predicate, used by
both `sessionState()` and `triageCounts()`) is exercised in
tests/test_cr_logic.py against dicts shaped exactly like the ones this
module proves list_sessions() really produces.
"""
import glob
import json
import os
import shutil
import tempfile
import time
import unittest

from aitracker import config
from aitracker.providers.claude import list_sessions
from aitracker.providers.auggie import list_auggie


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


class ClaudeEndedTrueWithLiveBackgroundAgentsTests(unittest.TestCase):
    """Builds a real Claude transcript on disk (main session file + a
    background-agent transcript under <sid>/subagents/, the same layout
    tests/test_agent_files.py confirms against the real log shape) and runs
    the REAL list_sessions() over it -- not a hand-built dict."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        self.sid = "s_bgended"
        self.main = os.path.join(self.sdir, self.sid + ".jsonl")
        # Main transcript: an opening user turn (cwd resolution) then an
        # assistant turn that ends in plain text with NO tool_use and NO
        # open AskUserQuestion -- providers/claude.py's _tail_scan sets
        # last="assistant_text" for exactly this shape, so `ended` resolves
        # True (the foreground turn "finished").
        _write_jsonl(self.main, [
            {"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
             "message": {"role": "user", "content": "kick off the refactor"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Kicked off three background agents; here's the summary."}]}},
        ])
        # Background-agent transcript: providers/claude.py's _agent_files()
        # globs <sid>/**/agent-*.jsonl next to the main file. Its mtime (a
        # freshly-written file, so "now" by construction) is what keeps the
        # session LIVE (_mtime_and_bg) even though the main transcript above
        # already "ended".
        adir = os.path.join(self.sdir, self.sid, "subagents")
        os.makedirs(adir)
        _write_jsonl(os.path.join(adir, "agent-bg1.jsonl"), [
            {"type": "user", "message": {"role": "user", "content": "fix the flaky test"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "a1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        ])

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        shutil.rmtree(self.pdir, ignore_errors=True)

    def _entry(self):
        rows = list_sessions()
        by_id = {r["id"]: r for r in rows}
        self.assertIn(self.sid, by_id, "list_sessions() must surface the session")
        return by_id[self.sid]

    def test_provider_really_emits_ended_true_with_bg_greater_than_zero_and_fresh_mtime(self):
        """THE CONNECTING ASSERTION: proves the combination the JS-side fix and its
        tests (tests/test_cr_logic.py) assume is real, not assumed -- ended=True,
        bg>0, and mtime inside LIVE_WINDOW, all off a real on-disk transcript."""
        e = self._entry()
        self.assertTrue(e["ended"], "main transcript's last turn was plain assistant text")
        self.assertGreater(e["bg"], 0, "a live background-agent transcript exists")
        self.assertLess(time.time() - e["mtime"], config.LIVE_WINDOW,
                         "the background agent's fresh mtime must keep the session live")

    def test_now_line_reports_the_running_background_agents(self):
        """THE FIX (providers/claude.py's now_line gate): this branch used to sit
        behind `not sm["ended"]` in the outer gate, making it unreachable for a
        session that is `ended` in the foreground but still has agents running --
        measured in production as `now_line: ''` on a session with `bg: 3`. It
        must now report what the background agents are doing instead of ''."""
        e = self._entry()
        self.assertIn("background agent", e["now_line"])
        self.assertIn(str(e["bg"]), e["now_line"])

    def test_now_line_stays_empty_for_a_genuinely_ended_session_with_no_bg_agents(self):
        """Sanity control: the fix must not make every ended session report a
        (fabricated) now_line -- only ones that actually have bg>0."""
        # Remove the background-agent transcript entirely: bg must drop to 0
        # and now_line must go back to "" for this now-genuinely-idle-foreground
        # session (still fresh mtime, from the main transcript's own write time).
        shutil.rmtree(os.path.join(self.sdir, self.sid))
        e = self._entry()
        self.assertTrue(e["ended"])
        self.assertEqual(e["bg"], 0)
        self.assertEqual(e["now_line"], "")


class AuggieHasNoBackgroundAgentAsymmetryTests(unittest.TestCase):
    """PROVIDER PARITY (mandatory per the repo's shared-seam rule): does Auggie
    carry the same `ended`-blind-to-background-activity asymmetry? Answer: no --
    Auggie has no background-agent concept at all, and always emits `bg: 0`
    (providers/auggie.py's list_auggie(), the "bg": 0 literal with the comment
    "Auggie has no background-agent/SDK model"). The shared JS predicate
    (ext_cr_board.js's `isWorking(s, live) = live && (!s.ended || !!s.bg)`)
    reduces to the original `live && !s.ended` whenever bg is falsy, so Auggie
    sessions are provably unaffected by the fix -- this pins that `bg` really
    is always 0/falsy for Auggie, the premise the reduction depends on."""

    def setUp(self):
        self._adir_snap = config.AUGGIE_SESSIONS
        self.adir = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = self.adir

    def tearDown(self):
        config.AUGGIE_SESSIONS = self._adir_snap
        shutil.rmtree(self.adir, ignore_errors=True)

    def test_auggie_session_always_carries_bg_zero(self):
        sess = {
            "sessionId": "augsess1",
            "customTitle": "",
            "chatHistory": [
                {"exchange": {"request_nodes": [], "response_nodes": [],
                              "response_text": "done"}},
            ],
            "modified": "2026-09-05T10:00:00Z",
        }
        with open(os.path.join(self.adir, "augsess1.json"), "w") as fh:
            json.dump(sess, fh)
        rows = list_auggie()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bg"], 0)
        self.assertTrue(rows[0]["ended"])
        # And no code path anywhere in providers/auggie.py's list_auggie() ever
        # writes a different value -- confirmed by reading the source (the "bg":
        # 0 key is a literal in the appended dict, not derived from any per-session
        # computation), so this single instance is representative of every Auggie
        # session, not just this fixture's.


if __name__ == "__main__":
    unittest.main()
