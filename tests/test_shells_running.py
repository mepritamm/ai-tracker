"""THE SHELLS-AS-LANDED BUG (owner report, with screenshots): a session whose
foreground turn has ENDED but which still has a BACKGROUND SHELL running was
shown as "LANDED / done" on the board, in the rail, and in the classic
sidebar -- even while that same session's own footer said "2 shells still
running". Root cause: `isSessionWorking()`/`isWorking()` (app.js/ext_cr_board.js)
only ever looked at `s.bg` (background AGENTS). Shell running-state lived
ONLY in `parse_shells()` (providers/claude.py), inside the expensive per-session
detail parse -- never on the cheap session-LIST dict every board/rail/sidebar
row actually reads.

REAL TRANSCRIPT SHAPES CONFIRMED before writing this (conventions rule 7) --
grepped straight out of an on-disk ~/.claude/projects/**/*.jsonl from this
machine's own history (a real `make check` run backgrounded during a prior
session in this same repo):

  launch (assistant tool_use, Bash with run_in_background):
    {"type":"tool_use","id":"toolu_01Bv...","name":"Bash",
     "input":{"command":"...","description":"Run full gate","timeout":600000,
              "run_in_background":true}}

  its result (user tool_result) -- SHELL_RE's exact match text:
    {"tool_use_id":"toolu_01Bv...","type":"tool_result",
     "content":"Command running in background with ID: bftxp6d67. Output is
     being written to: /private/tmp/.../bftxp6d67.output. You will be
     notified when it completes. To check interim output, use Read on that
     file path.","is_error":false}

  completion, TWO forms both carrying the SAME <task-id> as the shell id --
  a "queue-operation":"enqueue" wrapper AND a plain {"type":"user"} echo:
    {"type":"queue-operation","operation":"enqueue",
     "content":"<task-notification>\n<task-id>bftxp6d67</task-id>\n
     <tool-use-id>toolu_01Bv...</tool-use-id>\n<output-file>...</output-file>\n
     <status>completed</status>\n<summary>Background command \"Run full gate\"
     completed (exit code 0)</summary>\n</task-notification>"}
    {"type":"user","message":{"role":"user","content":"<task-notification>...
     same block...</task-notification>"}}

That confirms the join `parse_shells()` already makes (a shell id from
SHELL_RE, marked done by a matching <task-id> from TASKDONE_RE) is exactly
what a real transcript produces -- this module's fixtures below reproduce
that same shape, and reuses the SAME two module-level regexes (never a
second pair) inside `_tail_scan()`'s new `shells_running` count.

Fixtures are built as real on-disk transcripts and run through the REAL
`list_sessions()` (Python side, providers/claude.py) and the REAL assembled
bundle under a node DOM harness (JS side, idiom borrowed verbatim from
tests/test_cr_rail_polish.py -- `_REAL_DOM_PREAMBLE`/`_run_node`/`_read_page`/
`make_session`, imported, never copied), never a hand-built dict pretending
to be either.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

from aitracker import config, registry  # noqa: E402
from aitracker.registry import all_sessions  # noqa: E402
from aitracker.providers.claude import list_sessions, parse_shells  # noqa: E402
from aitracker.providers.auggie import list_auggie  # noqa: E402

from tests.test_cr_rail_polish import (  # noqa: E402
    NOW, _HAS_NODE, _REAL_DOM_PREAMBLE, _REAL_DOM_MID,
    _extract_script_content, _read_page, _run_node, make_session,
)


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _shell_launch_rows(tool_id="toolu_1", shell_id="shell42", cmd="make check &"):
    """The confirmed real shape above, trimmed to the fields _tail_scan/parse_shells
    actually read."""
    return [
        {"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
         "message": {"role": "user", "content": "run the gate in the background"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tool_id, "name": "Bash",
             "input": {"command": cmd, "description": "Run the gate", "timeout": 600000,
                       "run_in_background": True}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": tool_id, "type": "tool_result", "is_error": False,
             "content": "Command running in background with ID: %s. Output is being "
                        "written to: /tmp/x/%s.output. You will be notified when it "
                        "completes. To check interim output, use Read on that file "
                        "path." % (shell_id, shell_id)}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Kicked off the gate in the background."}]}},
    ]


def _task_notification_row(task_id, tool_id="toolu_1", summary="completed (exit code 0)"):
    return {"type": "user", "message": {"role": "user", "content":
            "<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>%s</tool-use-id>\n"
            "<output-file>/tmp/x/%s.output</output-file>\n<status>completed</status>\n"
            "<summary>Background command \"make check\" %s</summary>\n"
            "</task-notification>" % (task_id, tool_id, task_id, summary)}}


# ---------------------------------------------------------------------------
# Python side: _tail_scan()/list_sessions() (providers/claude.py) really emit
# `shells_running`, off a real on-disk transcript.
# ---------------------------------------------------------------------------

class ClaudeShellsRunningTailScanTests(unittest.TestCase):

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        self.sid = "s_shell"
        self.main = os.path.join(self.sdir, self.sid + ".jsonl")
        _write_jsonl(self.main, _shell_launch_rows())

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        shutil.rmtree(self.pdir, ignore_errors=True)

    def _entry(self):
        rows = list_sessions()
        by_id = {r["id"]: r for r in rows}
        self.assertIn(self.sid, by_id, "list_sessions() must surface the session")
        return by_id[self.sid]

    def test_launched_shell_with_no_completion_counts_as_running(self):
        e = self._entry()
        self.assertEqual(e["shells_running"], 1)

    def test_matching_task_notification_clears_it_to_zero(self):
        with open(self.main, "a") as fh:
            fh.write(json.dumps(_task_notification_row("shell42")) + "\n")
        e = self._entry()
        self.assertEqual(e["shells_running"], 0)

    def test_agrees_with_parse_shells_on_the_same_transcript(self):
        """The list-path's cheap tail count and the detail-path's full parse_shells()
        must reach the SAME verdict for the SAME transcript -- a launched shell with
        no completion is 'running' in both."""
        shells = parse_shells(self.main)
        self.assertEqual(len(shells), 1)
        self.assertTrue(shells[0]["running"])
        e = self._entry()
        self.assertEqual(e["shells_running"], 1)

    def test_agrees_with_parse_shells_once_the_shell_completes(self):
        with open(self.main, "a") as fh:
            fh.write(json.dumps(_task_notification_row("shell42")) + "\n")
        shells = parse_shells(self.main)
        self.assertEqual(len(shells), 1)
        self.assertFalse(shells[0]["running"])
        e = self._entry()
        self.assertEqual(e["shells_running"], 0)

    def test_a_shell_launch_with_no_matched_result_is_not_counted(self):
        """Undercount-on-purpose: a launch whose tool_result never matched
        SHELL_RE (so no shell id was ever resolved) must not be guessed at."""
        rows = [
            {"type": "user", "cwd": "/tmp/proj", "entrypoint": "cli",
             "message": {"role": "user", "content": "start something"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_nomatch", "name": "Bash",
                 "input": {"command": "true &", "run_in_background": True}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"tool_use_id": "toolu_nomatch", "type": "tool_result", "is_error": False,
                 "content": "some unrelated output that never mentions a shell id"}]}},
        ]
        _write_jsonl(self.main, rows)
        e = self._entry()
        self.assertEqual(e["shells_running"], 0)


class NowLineSurfacesShellsLikeAgentsTests(unittest.TestCase):
    """The owner's ruling, verbatim: shells "need to behave in the similar
    fashion like the agents" -- providers/claude.py's `now_line` (the board
    tile's own "what is it doing now" line) must mention a running shell the
    same way it already mentions a running background agent, and stay
    unambiguous when both are present together."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj2")
        os.makedirs(self.sdir)
        self.sid = "s_mixed"
        self.main = os.path.join(self.sdir, self.sid + ".jsonl")

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        shutil.rmtree(self.pdir, ignore_errors=True)

    def _write_main(self, shell_done=False):
        rows = _shell_launch_rows(tool_id="toolu_9", shell_id="shell99")
        if shell_done:
            rows.append(_task_notification_row("shell99", tool_id="toolu_9"))
        _write_jsonl(self.main, rows)

    def _add_agent(self):
        adir = os.path.join(self.sdir, self.sid, "subagents")
        os.makedirs(adir, exist_ok=True)
        _write_jsonl(os.path.join(adir, "agent-bg1.jsonl"), [
            {"type": "user", "message": {"role": "user", "content": "fix the flaky test"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "a1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        ])

    def _entry(self):
        rows = list_sessions()
        by_id = {r["id"]: r for r in rows}
        self.assertIn(self.sid, by_id)
        return by_id[self.sid]

    def test_shell_only_now_line_mentions_the_shell(self):
        self._write_main(shell_done=False)
        e = self._entry()
        self.assertEqual(e["bg"], 0)
        self.assertEqual(e["shells_running"], 1)
        self.assertIn("background shell", e["now_line"])
        self.assertIn("1", e["now_line"])

    def test_agent_and_shell_together_mention_both_unambiguously(self):
        self._write_main(shell_done=False)
        self._add_agent()
        e = self._entry()
        self.assertGreater(e["bg"], 0)
        self.assertEqual(e["shells_running"], 1)
        self.assertIn("background agent", e["now_line"])
        self.assertIn("shell", e["now_line"])
        # The existing bg-only phrase (pinned verbatim by
        # tests/test_cr_board_working_bg.py) must still appear intact once a
        # shell clause is appended alongside it -- the combined branch must
        # not have altered the agent wording to make room for the shell one.
        self.assertIn("%d background agent" % e["bg"], e["now_line"])

    def test_shell_completion_clears_the_shell_mention(self):
        self._write_main(shell_done=True)
        e = self._entry()
        self.assertEqual(e["shells_running"], 0)
        self.assertNotIn("shell", e["now_line"])


# ---------------------------------------------------------------------------
# Provider parity: Auggie has no background-shell concept and must always
# emit an honest 0, never omit the key.
# ---------------------------------------------------------------------------

class AuggieShellsRunningZeroTests(unittest.TestCase):

    def setUp(self):
        self._adir_snap = config.AUGGIE_SESSIONS
        self.adir = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = self.adir

    def tearDown(self):
        config.AUGGIE_SESSIONS = self._adir_snap
        shutil.rmtree(self.adir, ignore_errors=True)

    def test_auggie_session_always_carries_shells_running_zero(self):
        sess = {
            "sessionId": "augsess_shells",
            "customTitle": "",
            "chatHistory": [
                {"exchange": {"request_nodes": [], "response_nodes": [],
                              "response_text": "done"}},
            ],
            "modified": "2026-09-05T10:00:00Z",
        }
        with open(os.path.join(self.adir, "augsess_shells.json"), "w") as fh:
            json.dump(sess, fh)
        rows = list_auggie()
        self.assertEqual(len(rows), 1)
        self.assertIn("shells_running", rows[0])
        self.assertEqual(rows[0]["shells_running"], 0)


# ---------------------------------------------------------------------------
# registry.all_sessions()'s seam guarantee: the key exists for EVERY provider,
# even one that forgot to set it -- same defensive pattern as `fail_cmd`.
# ---------------------------------------------------------------------------

class RegistryShellsRunningSetdefaultTests(unittest.TestCase):

    def setUp(self):
        self._providers_snap = registry.PROVIDERS

    def tearDown(self):
        registry.PROVIDERS = self._providers_snap

    def test_missing_key_is_backfilled_as_zero(self):
        class _Bare:
            prefix = "bareshell:"
            def available(self):
                return True
            def list(self):
                return [{"id": "bareshell:x", "mtime": time.time()}]  # no shells_running key
        registry.PROVIDERS = [_Bare()]
        rows = {s["id"]: s for s in all_sessions()}
        self.assertIn("shells_running", rows["bareshell:x"])
        self.assertEqual(rows["bareshell:x"]["shells_running"], 0)

    def test_a_provider_that_does_set_it_is_left_alone(self):
        class _Setter:
            prefix = "settershell:"
            def available(self):
                return True
            def list(self):
                return [{"id": "settershell:x", "mtime": time.time(), "shells_running": 5}]
        registry.PROVIDERS = [_Setter()]
        rows = {s["id"]: s for s in all_sessions()}
        self.assertEqual(rows["settershell:x"]["shells_running"], 5)


# ---------------------------------------------------------------------------
# JS side: the shared isSessionWorking()/isWorking() predicate and the three
# surfaces that must render the running-shell count the same way they already
# render the running-agent count -- board tile, rail row, classic sidebar row.
# Harness borrowed verbatim from tests/test_cr_rail_polish.py.
# ---------------------------------------------------------------------------

_SHELLS_JS_TAIL = r"""
function rowInfo(session) {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: [session], now: %(now)d });
  var rows = queryAllReal(root, '.cr-rail-row');
  var tiles = queryAllReal(root, '.cr-tile');
  var row = rows.length ? rows[0] : null;
  var tile = tiles.length ? tiles[0] : null;
  var dots = row ? queryAllReal(row, '.cr-rail-dot') : [];
  var badges = row ? queryAllReal(row, '.cr-rail-badge--bg') : [];
  return {
    rowClasses: row ? Array.from(row._classes) : null,
    dotClasses: dots.length ? Array.from(dots[0]._classes) : [],
    rowText: row ? allTextIn(row) : null,
    badgeTitles: badges.map(function (b) { return b.getAttribute('title'); }),
    tileClasses: tile ? Array.from(tile._classes) : null,
    state: window.CR.board.sessionState(session, %(now)d)
  };
}

var shellWorking = %(shellWorking)s;
var shellDone = %(shellDone)s;
var mixed = %(mixed)s;
var out = {};
out.shellWorking = rowInfo(shellWorking);
out.shellDone = rowInfo(shellDone);
out.mixed = rowInfo(mixed);
out.classicShellWorkingHtml = sessionRow(shellWorking, %(now)d);
out.classicShellDoneHtml = sessionRow(shellDone, %(now)d);
out.classicMixedHtml = sessionRow(mixed, %(now)d);

console.log("===CR_SHELLS_JSON_START===");
console.log(JSON.stringify(out));
"""


def _shells_driver_js():
    bundle_js = _extract_script_content(_read_page())
    shell_working = make_session("shell_working", NOW - 5, ended=True, bg=0, shells_running=2)
    shell_done = make_session("shell_done", NOW - 5, ended=True, bg=0, shells_running=0)
    mixed = make_session("shell_mixed", NOW - 5, ended=True, bg=1, shells_running=3)
    tail = _SHELLS_JS_TAIL % {
        "now": NOW,
        "shellWorking": json.dumps(shell_working),
        "shellDone": json.dumps(shell_done),
        "mixed": json.dumps(mixed),
    }
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_shells_json(stdout):
    marker = "===CR_SHELLS_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestShellsRunningSurfacedLikeAgents(unittest.TestCase):
    """Renders REAL rows (board tile, rail row, classic sidebar row) for
    sessions shaped exactly like the reported bug (`ended: true,
    shells_running: N`, fresh mtime) and confirms all three agree it's
    WORKING, all three RENDER the shell count in the same idiom the agent
    count already uses, and nothing renders at 0 -- the fix does not make
    every ended session permanently 'working'."""

    @classmethod
    def setUpClass(cls):
        js = _shells_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "shells driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_shells_json(stdout)

    # -- ended:true, bg:0, shells_running:2 reads WORKING everywhere ---------

    def test_rail_row_is_not_done_when_only_shells_are_running(self):
        info = self.OUT["shellWorking"]
        self.assertIsNotNone(info["rowClasses"], "rail row did not render")
        self.assertNotIn("cr-rail-row--done", info["rowClasses"])
        self.assertIn("is-live", info["dotClasses"])

    def test_board_tile_state_is_working_when_only_shells_are_running(self):
        self.assertEqual(self.OUT["shellWorking"]["state"], "working")
        self.assertIn("cr-tile--working", self.OUT["shellWorking"]["tileClasses"] or [])

    def test_classic_sidebar_is_not_done_when_only_shells_are_running(self):
        html = self.OUT["classicShellWorkingHtml"]
        row_class = re.search(r'class="(sitem[^"]*)"', html).group(1)
        self.assertNotIn("done", row_class.split())
        self.assertNotIn("statusbadge done", html)

    # -- shells_running:0 still reads done/landed -- the fix isn't sticky ----

    def test_rail_row_still_gets_done_with_zero_shells(self):
        info = self.OUT["shellDone"]
        self.assertIn("cr-rail-row--done", info["rowClasses"])
        self.assertNotIn("is-live", info["dotClasses"])

    def test_board_tile_state_is_landed_with_zero_shells(self):
        self.assertEqual(self.OUT["shellDone"]["state"], "landed")

    def test_classic_sidebar_still_gets_done_with_zero_shells(self):
        html = self.OUT["classicShellDoneHtml"]
        row_class = re.search(r'class="(sitem[^"]*)"', html).group(1)
        self.assertIn("done", row_class.split())
        self.assertIn("statusbadge done", html)

    # -- rendered wording: present when >0, absent when 0, unambiguous -------

    def test_rail_row_renders_the_running_shell_count(self):
        self.assertIn("2 running", self.OUT["shellWorking"]["rowText"])

    def test_rail_row_renders_nothing_for_zero_shells_and_zero_agents(self):
        self.assertNotIn("running", self.OUT["shellDone"]["rowText"])

    def test_classic_sidebar_renders_the_running_shell_count(self):
        self.assertIn("2 running", self.OUT["classicShellWorkingHtml"])

    def test_classic_sidebar_renders_nothing_for_zero_shells_and_zero_agents(self):
        html = self.OUT["classicShellDoneHtml"]
        self.assertNotIn("running", html)

    def test_agents_and_shells_render_as_two_distinct_badges_not_conflated(self):
        """bg:1, shells_running:3 together -- both counts must be visible and
        distinguishable, never summed together or overwriting one another."""
        info = self.OUT["mixed"]
        self.assertIn("1 running", info["rowText"])
        self.assertIn("3 running", info["rowText"])
        self.assertEqual(len(info["badgeTitles"]), 2, info["badgeTitles"])
        agent_titles = [t for t in info["badgeTitles"] if "agent" in (t or "")]
        shell_titles = [t for t in info["badgeTitles"] if "shell" in (t or "")]
        self.assertEqual(len(agent_titles), 1)
        self.assertEqual(len(shell_titles), 1)

    def test_classic_sidebar_shows_both_agent_and_shell_counts(self):
        html = self.OUT["classicMixedHtml"]
        self.assertIn("1 running", html)
        self.assertIn("3 running", html)


if __name__ == "__main__":
    unittest.main()
