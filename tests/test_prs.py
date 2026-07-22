#!/usr/bin/env python3
"""PR/MR links a session touched surface on the shared `prs` shape — filled by
BOTH providers, created-first, deduped. The capability spans Claude and Auggie."""
import json
import os
import tempfile
import unittest

import aitracker.config as config
from aitracker.util import collect_prs, prs_sorted, note_pr_states
from aitracker.providers.claude import parse_session
from aitracker.providers import auggie as _auggie


class TestCollectPrs(unittest.TestCase):
    def test_extracts_and_labels(self):
        acc = {}
        collect_prs(acc, "opened https://github.com/acme/widget/pull/42 today", "t1")
        self.assertIn("https://github.com/acme/widget/pull/42", acc)
        e = acc["https://github.com/acme/widget/pull/42"]
        self.assertEqual(e["repo"], "acme/widget")
        self.assertEqual(e["num"], "42")
        self.assertFalse(e["created"])

    def test_dedup_and_created_sticks(self):
        acc = {}
        collect_prs(acc, "see https://github.com/a/b/pull/1", "t1", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/1 (from gh)", "t2", created=True)
        collect_prs(acc, "https://github.com/a/b/pull/1 again", "t3", created=False)
        self.assertEqual(len(acc), 1)                      # deduped by URL
        self.assertTrue(acc["https://github.com/a/b/pull/1"]["created"])   # created wins
        self.assertEqual(acc["https://github.com/a/b/pull/1"]["t"], "t3")  # latest ts kept

    def test_trailing_punctuation_and_slash(self):
        acc = {}
        collect_prs(acc, "does https://github.com/a/b/pull/45/ affect x?", "t")
        collect_prs(acc, "[https://github.com/a/b/pull/9].", "t")
        self.assertIn("https://github.com/a/b/pull/45", acc)   # trailing / stripped -> same PR
        self.assertIn("https://github.com/a/b/pull/9", acc)    # trailing ]. stripped

    def test_bitbucket_and_gitlab_shapes(self):
        acc = {}
        collect_prs(acc, "https://bitbucket.org/team/repo/pull-requests/7", "t")
        collect_prs(acc, "https://gitlab.com/grp/proj/-/merge_requests/13", "t")
        self.assertEqual(len(acc), 2)                      # both hosting styles recognised
        nums = sorted(e["num"] for e in acc.values())
        self.assertEqual(nums, ["13", "7"])

    def test_non_pr_urls_ignored(self):
        acc = {}
        collect_prs(acc, "https://github.com/a/b/issues/5 and https://github.com/a/b/tree/main", "t")
        self.assertEqual(acc, {})

    def test_sorted_created_first_then_recent(self):
        acc = {}
        collect_prs(acc, "https://github.com/a/b/pull/1", "2026-01-01T00:00:00Z", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/2", "2026-01-03T00:00:00Z", created=False)
        collect_prs(acc, "https://github.com/a/b/pull/3", "2026-01-02T00:00:00Z", created=True)
        order = [p["num"] for p in prs_sorted(acc)]
        self.assertEqual(order, ["3", "2", "1"])           # created(#3) first, then #2 (newer ref) > #1


class TestPrStates(unittest.TestCase):
    def test_note_states_number_bearing_only(self):
        st = {}
        note_pr_states(st, "commit abc Merge pull request #42 from acme/feat")   # git-log subject
        note_pr_states(st, "gh pr merge 7 --squash")                              # explicit merge
        note_pr_states(st, "cd /repo && gh pr close 8")                           # explicit close (after &&)
        note_pr_states(st, "these all merged: #99 #100")                          # bare mention → ignored
        self.assertEqual(st, {"42": "merged", "7": "merged", "8": "closed"})

    def test_merged_wins_over_closed(self):
        st = {"5": "closed"}
        note_pr_states(st, "Merge pull request #5 from x")
        self.assertEqual(st["5"], "merged")                # merged is the meaningful state

    def test_prs_sorted_overlays_state_by_num(self):
        acc = {}
        collect_prs(acc, "https://github.com/a/b/pull/42", "t", created=True)
        out = prs_sorted(acc, {"42": "merged"})
        self.assertEqual(out[0]["state"], "merged")
        # a PR with no signal stays "" (renders as open)
        self.assertEqual(prs_sorted({"u": {"url": "u", "num": "9", "created": False,
                                           "narr": False, "state": "", "t": "t"}}, {})[0]["state"], "")


def _write_jsonl(lines):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")
    return path


class TestClaudePrs(unittest.TestCase):
    def test_only_generated_prs_not_referenced(self):
        # a Bash `gh pr create` whose tool_result carries the new URL (=generated here),
        # plus an unrelated PR the assistant merely mentions. Only the generated one shows.
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "ship it"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu1", "name": "Bash",
                 "input": {"command": "gh pr create --fill"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu1",
                 "content": "https://github.com/acme/app/pull/7"}]}},
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                {"type": "text", "text": "Related: https://github.com/acme/app/pull/3"}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        nums = [p["num"] for p in d["prs"]]
        self.assertEqual(nums, ["7"])                      # #3 (referenced) filtered out
        self.assertTrue(d["prs"][0]["created"])
        self.assertEqual(d["prs"][0]["repo"], "acme/app")

    def test_generated_via_github_mcp_tool(self):
        # PR created through the GitHub MCP tool (not gh): its result URL still counts.
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "open a PR"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "mcp1", "name": "mcp__github__create_pull_request",
                 "input": {"title": "x"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "mcp1",
                 "content": '{"html_url": "https://github.com/acme/app/pull/9"}'}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        self.assertEqual([p["num"] for p in d["prs"]], ["9"])
        self.assertTrue(d["prs"][0]["created"])

    def test_merge_commit_line_marks_pr_merged(self):
        # a created PR (#7); later a `git log` result carries its merge-commit subject → state=merged.
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "ship it"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "tu1", "name": "Bash",
                 "input": {"command": "gh pr create --fill"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu1",
                 "content": "https://github.com/acme/app/pull/7"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "g1", "name": "Bash", "input": {"command": "git log --oneline"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "g1",
                 "content": "a575fc2 Merge pull request #7 from acme/feat"}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        self.assertEqual(d["prs"][0]["num"], "7")
        self.assertEqual(d["prs"][0]["state"], "merged")

    def test_referenced_only_session_shows_none(self):
        # a session that only views/pastes PRs generates none -> empty panel.
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "does https://github.com/acme/app/pull/3 affect us?"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "b1", "name": "Bash",
                 "input": {"command": "gh pr view https://github.com/acme/app/pull/3"}}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        self.assertEqual(d["prs"], [])

    def test_command_mentioning_pr_create_does_not_mark_output_created(self):
        # a command that only MENTIONS "gh pr create" (a grep) must NOT flag the PRs in its
        # output as created — only a real invocation does. (Was: diagnostic greps polluted the panel.)
        path = _write_jsonl([
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "audit the logs"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "g1", "name": "Bash",
                 "input": {"command": "grep -rn 'gh pr create' ~/.augment"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "g1",
                 "content": "found https://github.com/other/repo/pull/55"}]}},
        ])
        d = parse_session(path)
        os.unlink(path)
        self.assertEqual(d["prs"], [])                     # #55 not created (grep) and cross-repo → hidden


class TestAgentPrs(unittest.TestCase):
    """A PR opened by a background subagent (`<sid>/**/agent-*.jsonl`) is attributed to the
    session's `prs`, tagged agent, with its merge state — the flagged gap (only 2 of N showed)."""

    def _session_with_agent(self, agent_lines, main_lines=None):
        d = tempfile.mkdtemp()
        spath = os.path.join(d, "sess.jsonl")
        with open(spath, "w") as f:
            for o in (main_lines or [{"type": "user", "cwd": "/x",
                                      "message": {"role": "user", "content": "go"}}]):
                f.write(json.dumps(o) + "\n")
        adir = os.path.join(d, "sess", "subagents", "workflows", "wf_x")
        os.makedirs(adir)
        with open(os.path.join(adir, "agent-a0.jsonl"), "w") as f:
            for o in agent_lines:
                f.write(json.dumps(o) + "\n")
        return spath

    def test_agent_created_pr_surfaces_tagged(self):
        spath = self._session_with_agent([
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "a1", "name": "Bash", "input": {"command": "gh pr create --fill"}}]}},
            {"type": "user", "timestamp": "2026-06-22T10:00:30Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "a1",
                 "content": "https://github.com/acme/app/pull/9"}]}},
        ])
        d = parse_session(spath)
        pr = next((p for p in d["prs"] if p["num"] == "9"), None)
        self.assertIsNotNone(pr)
        self.assertTrue(pr["created"] and pr.get("agent"))     # attributed + agent-tagged

    def test_agent_created_via_mcp_and_merge_state(self):
        # created through the GitHub MCP tool, then merged via a git-log merge-commit line.
        spath = self._session_with_agent([
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "m1", "name": "mcp__github__create_pull_request", "input": {}}]}},
            {"type": "user", "timestamp": "2026-06-22T10:00:30Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "m1",
                 "content": '{"html_url": "https://github.com/acme/app/pull/12"}'}]}},
            {"type": "assistant", "timestamp": "2026-06-22T10:01:00Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "x",
                 "content": "abc Merge pull request #12 from acme/feat"}]}},
        ])
        d = parse_session(spath)
        pr = next((p for p in d["prs"] if p["num"] == "12"), None)
        self.assertEqual((pr["created"], pr.get("agent"), pr["state"]), (True, True, "merged"))

    def test_main_referenced_agent_created_dedup_and_promoted(self):
        # main session only VIEWS #5 (referenced, would be filtered); the agent CREATED it.
        # One row, promoted to created + agent-tagged (no duplicate).
        spath = self._session_with_agent(
            agent_lines=[
                {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                    {"type": "tool_use", "id": "a1", "name": "Bash", "input": {"command": "gh pr create --fill"}}]}},
                {"type": "user", "timestamp": "2026-06-22T10:00:30Z", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "a1",
                     "content": "https://github.com/acme/app/pull/5"}]}}],
            main_lines=[
                {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": "v1", "name": "Bash",
                     "input": {"command": "gh pr view https://github.com/acme/app/pull/5"}}]}}])
        d = parse_session(spath)
        rows = [p for p in d["prs"] if p["num"] == "5"]
        self.assertEqual(len(rows), 1)                          # deduped by URL
        self.assertTrue(rows[0]["created"] and rows[0].get("agent"))


class TestAuggiePrs(unittest.TestCase):
    def setUp(self):
        self._sess = config.AUGGIE_SESSIONS
        config.AUGGIE_SESSIONS = tempfile.mkdtemp()
        _auggie._AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        config.AUGGIE_SESSIONS = self._sess
        _auggie._AUGGIE_LIST_CACHE.clear()

    def _write(self, sid, exchange):
        json.dump({"sessionId": sid, "modified": "2026-06-27T05:48:03Z",
                   "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z", "exchange": exchange}]},
                  open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))

    def test_generated_pr_from_create_command(self):
        # exchange runs `gh pr create`, response prints the URL -> generated here.
        self._write("s1", {
            "request_message": "open a PR",
            "response_nodes": [{"tool_use": {"tool_name": "launch-process",
                                             "input_json": '{"command": "gh pr create --fill"}'}}],
            "response_text": "Opened https://github.com/acme/lib/pull/12"})
        d = _auggie.parse_auggie("s1")
        self.assertEqual([p["num"] for p in d["prs"]], ["12"])
        self.assertEqual(d["prs"][0]["repo"], "acme/lib")

    def test_referenced_pr_is_not_shown(self):
        # a PR merely mentioned (no create in the exchange) generates nothing.
        self._write("s2", {"request_message": "see https://github.com/acme/lib/pull/5",
                           "response_text": "yes that one at https://github.com/acme/lib/pull/5"})
        d = _auggie.parse_auggie("s2")
        self.assertEqual(d["prs"], [])

    def test_pr_state_merged_from_merge_command(self):
        # parity with Claude: a created PR (#12) later merged via `gh pr merge 12` → state=merged.
        self._write("s3", {
            "request_message": "ship and merge it",
            "response_nodes": [
                {"tool_use": {"tool_name": "launch-process",
                              "input_json": '{"command": "gh pr create --fill"}'}},
                {"tool_use": {"tool_name": "launch-process",
                              "input_json": '{"command": "gh pr merge 12 --squash"}'}}],
            "response_text": "Opened https://github.com/acme/lib/pull/12"})
        d = _auggie.parse_auggie("s3")
        self.assertEqual([(p["num"], p["state"]) for p in d["prs"]], [("12", "merged")])


if __name__ == "__main__":
    unittest.main()
