#!/usr/bin/env python3
"""Server half of the agent map: per-agent parent/depth/state/dur_s/ctx/model fields off
parse_agents, the Agent-tool dispatch fix (4d), child-session model, list `agent_files_n`,
and agent_detail's `tail`."""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config
from aitracker.providers import claude
from aitracker.providers.claude import (agent_detail, child_agent_sessions, list_sessions,
                                        parse_agents, parse_session)

STOP = {"type": "attachment", "attachment": {"type": "hook_success", "hookName": "SubagentStop",
                                              "hookEvent": "SubagentStop", "content": ""}}


def _write(path, rows):
    with open(path, "w") as fh:
        for o in rows:
            fh.write(json.dumps(o) + "\n")


def _msg(ts, text="x", usage=None, tool_use=None, role="assistant", model=None):
    m = {"role": role, "content": [{"type": "text", "text": text}]}
    if tool_use:
        m["content"].append(tool_use)
    if usage is not None:
        m["usage"] = usage
    if model:
        m["model"] = model
    return {"type": role, "timestamp": ts, "message": m}


def _stop(ts):
    return dict(STOP, timestamp=ts)


def _spawn(tid):
    return {"type": "tool_use", "id": tid, "name": "Agent",
            "input": {"description": "d", "subagent_type": "x"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.main = os.path.join(self.dir, "sess.jsonl")
        _write(self.main, [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}])
        self.adir = os.path.join(self.dir, "sess", "subagents")
        os.makedirs(self.adir)
        if hasattr(claude, "_AGENT_CACHE"):
            claude._AGENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def agent(self, aid, rows, meta=None, age=None, raw_meta=None):
        p = os.path.join(self.adir, "agent-%s.jsonl" % aid)
        _write(p, rows)
        if meta is not None:
            with open(p[:-6] + ".meta.json", "w") as fh:
                json.dump(meta, fh)
        if raw_meta is not None:
            with open(p[:-6] + ".meta.json", "w") as fh:
                fh.write(raw_meta)
        if age is not None:
            t = time.time() - age
            os.utime(p, (t, t))
        return p

    def row(self, aid):
        return next(r for r in parse_agents(self.main)[0] if r["aid"] == aid)


class TestTree(Base):
    def test_depth2_parent_even_when_parent_file_sorts_after_child(self):
        # child "aaa" is spawned by "zzz" (sorts later); "zzz" was spawned by "mmm"
        self.agent("mmm", [_msg("2026-07-13T10:00:00Z", tool_use=_spawn("tu_z"))],
                   {"toolUseId": "tu_root", "spawnDepth": 1})
        self.agent("zzz", [_msg("2026-07-13T10:01:00Z", tool_use=_spawn("tu_a"))],
                   {"toolUseId": "tu_z", "spawnDepth": 2})
        self.agent("aaa", [_msg("2026-07-13T10:02:00Z")], {"toolUseId": "tu_a", "spawnDepth": 3})
        self.assertEqual(self.row("mmm")["parent"], "")
        self.assertEqual(self.row("zzz")["parent"], "mmm")
        self.assertEqual(self.row("aaa")["parent"], "zzz")
        self.assertEqual((self.row("mmm")["depth"], self.row("zzz")["depth"], self.row("aaa")["depth"]), (1, 2, 3))

    def test_depth_falls_back_to_chain_without_spawndepth(self):
        self.agent("mmm", [_msg("2026-07-13T10:00:00Z", tool_use=_spawn("tu_z"))], {"toolUseId": "tu_root"})
        self.agent("zzz", [_msg("2026-07-13T10:01:00Z")], {"toolUseId": "tu_z"})
        self.assertEqual(self.row("zzz")["depth"], 2)
        self.assertEqual(self.row("mmm")["depth"], 1)

    def test_orphan_and_missing_parent_are_root(self):
        self.agent("orph", [_msg("2026-07-13T10:00:00Z")], {"toolUseId": "tu_unknown"})
        self.agent("nometa", [_msg("2026-07-13T10:00:00Z")])
        for aid in ("orph", "nometa"):
            r = self.row(aid)
            self.assertEqual((r["parent"], r["depth"]), ("", 1), r)

    def test_self_and_cycle_do_not_hang(self):
        self.agent("a1", [_msg("2026-07-13T10:00:00Z", tool_use=_spawn("t1"))], {"toolUseId": "t2"})
        self.agent("a2", [_msg("2026-07-13T10:00:00Z", tool_use=_spawn("t2"))], {"toolUseId": "t1"})
        self.assertTrue(self.row("a1")["depth"] >= 1)


class TestState(Base):
    def test_stale_no_marker_is_done(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z")], age=1000)
        r = self.row("s")
        self.assertEqual((r["state"], r["running"]), ("done", False))

    def test_fresh_stop_after_last_message_is_done_but_running_unchanged(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z"), _stop("2026-07-13T10:00:05Z")])
        r = self.row("s")
        self.assertEqual(r["state"], "done")
        self.assertIs(r["running"], True)          # mtime-only, exactly as before
        self.assertEqual(r["ended"], "2026-07-13T10:00:05Z")

    def test_stop_then_message_fresh_is_running(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z"), _stop("2026-07-13T10:00:05Z"),
                         _msg("2026-07-13T10:01:00Z")])
        r = self.row("s")
        self.assertEqual(r["state"], "running")
        self.assertIsNone(r["ended"])

    def test_out_of_order_stop_timestamp_still_ends_by_file_order(self):
        self.agent("s", [_msg("2026-07-13T10:05:00Z"), _stop("2026-07-13T10:00:00Z")])
        self.assertEqual(self.row("s")["state"], "done")

    def test_sidecar_finished_without_stop_rows_is_done(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z")], {"finished": True})
        self.assertEqual(self.row("s")["state"], "done")
        self.assertIs(self.row("s")["running"], True)

    def test_sidecar_finished_ignored_when_stop_rows_exist_and_agent_resumed(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z"), _stop("2026-07-13T10:00:05Z"),
                         _msg("2026-07-13T10:01:00Z")], {"finished": True})
        self.assertEqual(self.row("s")["state"], "running")

    def test_dur_s_sums_active_segments_across_resume_gap(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z"), _stop("2026-07-13T10:05:00Z"),
                         _msg("2026-07-13T12:00:00Z"), _stop("2026-07-13T12:01:00Z")])
        r = self.row("s")
        self.assertEqual(r["dur_s"], 360)
        self.assertEqual(r["started"], "2026-07-13T10:00:00Z")


class TestFields(Base):
    def test_ctx_is_last_usage_block_not_trailing_no_usage_row(self):
        u1 = {"input_tokens": 1, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 300, "output_tokens": 9}
        u2 = {"input_tokens": 4000, "cache_creation_input_tokens": 50000, "cache_read_input_tokens": 600000,
              "output_tokens": 7}
        self.agent("s", [_msg("2026-07-13T10:00:00Z", usage=u1), _msg("2026-07-13T10:01:00Z", usage=u2),
                         _msg("2026-07-13T10:02:00Z", role="user")])
        self.assertEqual(self.row("s")["ctx_tok"], 4000 + 50000 + 600000)

    def test_ctx_null_fields_and_no_usage(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z", usage={"input_tokens": None, "cache_read_input_tokens": 5})])
        self.agent("n", [_msg("2026-07-13T10:00:00Z")])
        self.assertEqual(self.row("s")["ctx_tok"], 5)
        self.assertIsNone(self.row("n")["ctx_tok"])

    def test_no_sidecar_and_bad_json_sidecar_use_defaults(self):
        self.agent("none", [{"type": "user", "message": {"role": "user", "content": "the task text"}},
                            _msg("2026-07-13T10:00:00Z")])
        self.agent("bad", [{"type": "user", "message": {"role": "user", "content": "other task"}},
                           _msg("2026-07-13T10:00:00Z")], raw_meta="{not json")
        for aid, task in (("none", "the task text"), ("bad", "other task")):
            r = self.row(aid)
            self.assertEqual((r["desc"], r["type"], r["model_req"], r["parent"], r["depth"]),
                             (task, "", "", "", 1), r)

    def test_sidecar_fields_and_model_label_from_alias_without_assistant_turn(self):
        self.agent("s", [{"type": "user", "message": {"role": "user", "content": "t"}}],
                   {"description": "Review it", "agentType": "reviewer", "model": "opus"})
        r = self.row("s")
        self.assertEqual((r["desc"], r["type"], r["model_req"], r["model"], r["model_label"]),
                         ("Review it", "reviewer", "opus", "", "Opus"))

    def test_real_model_beats_alias_for_label(self):
        self.agent("s", [_msg("2026-07-13T10:00:00Z", model="claude-haiku-4-5")], {"model": "opus"})
        r = self.row("s")
        self.assertEqual((r["model"], r["model_req"], r["model_label"]), ("claude-haiku-4-5", "opus", "Haiku 4.5"))


class TestChildSessions(unittest.TestCase):
    def test_newest_run_model_wins(self):
        d = tempfile.mkdtemp()
        try:
            old, new = os.path.join(d, "old.jsonl"), os.path.join(d, "new.jsonl")
            for p in (old, new):
                _write(p, [{"type": "user", "message": {"role": "user", "content": "x"}}])
            os.utime(old, (time.time() - 1000, time.time() - 1000))
            sm = lambda model: {"prompt": "same prompt", "title": "t", "cwd": "", "first": 200.0, "model": model}
            agents = [("old", old, sm("claude-haiku-4-5")), ("new", new, sm("claude-opus-4-5"))]
            with mock.patch.object(claude, "_same_dir_sessions", lambda pd: ([("H", 100.0)], agents)):
                rows = child_agent_sessions("H", d)
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual((r["id"], r["runs"], r["model"], r["model_label"]),
                             ("new", 2, "claude-opus-4-5", "Opus 4.5"))
            # single run (create branch) carries the model too
            with mock.patch.object(claude, "_same_dir_sessions", lambda pd: ([("H", 100.0)], agents[:1])):
                r1 = child_agent_sessions("H", d)[0]
            self.assertEqual((r1["model"], r1["model_label"]), ("claude-haiku-4-5", "Haiku 4.5"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestDispatch4d(Base):
    def test_agent_tool_use_reaches_agents_list_counts_and_overview(self):
        with open(self.main, "a") as fh:
            fh.write(json.dumps(_msg("2026-07-13T10:00:00Z", tool_use={
                "type": "tool_use", "id": "tu1", "name": "Agent",
                "input": {"description": "Probe it", "subagent_type": "Explore"}})) + "\n")
        d = parse_session(self.main)
        self.assertEqual(len(d["agents"]), 1, d["agents"])
        self.assertEqual((d["agents"][0]["tool"], d["agents"][0]["type"], d["agents"][0]["model"]),
                         ("Agent", "Explore", ""))
        self.assertEqual(d["counts"]["agents"], 1)
        self.assertIn("dispatched 1 sub-agent", json.dumps(d["overview"]).lower())

    def test_task_name_still_counts(self):
        with open(self.main, "a") as fh:
            fh.write(json.dumps(_msg("2026-07-13T10:00:00Z", tool_use={
                "type": "tool_use", "id": "tu1", "name": "Task", "input": {"description": "old"}})) + "\n")
        d = parse_session(self.main)
        self.assertEqual((len(d["agents"]), d["agents"][0]["tool"]), (1, "Task"))


class TestListAndDetail(unittest.TestCase):
    def test_list_agent_files_n_claude_and_auggie(self):
        snap = config.PROJECTS
        d = tempfile.mkdtemp()
        try:
            config.PROJECTS = d
            pd = os.path.join(d, "-tmp-proj")
            os.makedirs(pd)
            main = os.path.join(pd, "s1.jsonl")
            _write(main, [{"type": "user", "cwd": "/x", "timestamp": "2026-07-13T10:00:00Z",
                           "message": {"role": "user", "content": "hello"}}])
            os.makedirs(os.path.join(pd, "s1", "subagents"))
            for a in ("a1", "a2"):
                _write(os.path.join(pd, "s1", "subagents", "agent-%s.jsonl" % a), [_msg("2026-07-13T10:00:00Z")])
            row = next(r for r in list_sessions() if r["id"] == "s1")
            self.assertEqual(row["agent_files_n"], 2)
            self.assertEqual(claude._mtime_bg_n(main)[2], 2)
            self.assertEqual(len(claude._mtime_and_bg(main)), 2)     # the 2-tuple wrapper stays
        finally:
            config.PROJECTS = snap
            shutil.rmtree(d, ignore_errors=True)

    def test_auggie_list_rows_emit_zero(self):
        import inspect
        from aitracker.providers import auggie, augment_ext
        for mod in (auggie, augment_ext):
            self.assertIn('"agent_files_n": 0', inspect.getsource(mod), mod.__name__)

    def test_agent_detail_tail_survives_the_40k_cap(self):
        d = tempfile.mkdtemp()
        try:
            main = os.path.join(d, "s.jsonl")
            _write(main, [])
            os.makedirs(os.path.join(d, "s", "subagents"))
            big = [_msg("2026-07-13T10:00:00Z", "p%d " % i + "w" * 1000) for i in range(60)]
            big.append(_msg("2026-07-13T10:01:00Z", "FINAL-REPORT-MARKER"))
            _write(os.path.join(d, "s", "subagents", "agent-big.jsonl"), big)
            det = agent_detail(main, "big")
            self.assertEqual(len(det["narration"]), 40000)
            self.assertNotIn("FINAL-REPORT-MARKER", det["narration"])
            self.assertTrue(det["tail"].endswith("FINAL-REPORT-MARKER"))
            self.assertLessEqual(len(det["tail"]), 4000)
            self.assertEqual(agent_detail(main, "nope")["tail"], "")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
