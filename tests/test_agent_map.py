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


def _iso(off):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + off))


def _bash(tuid, off, bg=True, cmd="sleep 99"):
    inp = {"command": cmd, "description": "d"}
    if bg:
        inp["run_in_background"] = True
    return _msg(_iso(off), "run", tool_use={"type": "tool_use", "id": tuid, "name": "Bash", "input": inp})


def _result(tuid, off, text, tur=None, err=False):
    o = {"type": "user", "timestamp": _iso(off),
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid,
                                                   "content": text, "is_error": err}]}}
    if tur is not None:
        o["toolUseResult"] = tur
    return o


def _bgres(tid):
    return "Command running in background with ID: %s. Output is being written to: /tmp/t/%s.output" % (tid, tid)


class TestBackgroundHold(Base):
    """Sidecar background shells hold their agent running while the host process lives."""
    def setUp(self):
        super().setUp()
        self.live = tempfile.mkdtemp()
        p = mock.patch.object(config, "LIVE_SESSIONS_DIR", self.live)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.live, True)
        self.host()

    def host(self, off=-3600, sid="sess"):
        for n in os.listdir(self.live):
            os.remove(os.path.join(self.live, n))
        if off is None:
            return
        ps = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(time.time() + off))
        with open(os.path.join(self.live, "%d.json" % os.getpid()), "w") as fh:
            json.dump({"pid": os.getpid(), "sessionId": sid, "kind": "bg", "procStart": ps}, fh)

    def side(self, aid="a1", extra=(), stop=True):
        rows = [_msg(_iso(-1900), "start")] + list(extra) + ([_stop(_iso(-1000))] if stop else [])
        return self.agent(aid, rows, age=1000)

    def sess(self):
        claude._AGENT_CACHE.clear()
        return parse_session(self.main)

    def ag(self, d, aid="a1"):
        return next(a for a in d["agents_bg"] if a["aid"] == aid)

    def s1(self, tid="bsh1"):
        return [_bash("u1", -1800), _result("u1", -1790, _bgres(tid), {"backgroundTaskId": tid})]

    def main_add(self, rows):
        with open(self.main, "a") as fh:
            for o in rows:
                fh.write(json.dumps(o) + "\n")

    def notify(self, off, *ids, op=None):
        """A <task-notification> row (timestamped `off` s from now) for each id, in the main transcript."""
        o = {"type": "queue-operation", "timestamp": _iso(off),
             "content": "".join("<task-notification><task-id>%s</task-id></task-notification>" % i for i in ids)}
        if op:
            o["operation"] = op
        self.main_add([o])

    def test_notified_owner_of_open_shell_is_waiting(self):
        self.side(extra=self.s1())
        a = self.ag(self.sess())
        self.assertEqual(a["state"], "running")        # not notified yet: still working
        self.notify(-1000, "a1")
        d = self.sess()
        a = self.ag(d)
        self.assertEqual((a["state"], a["running"], a["ended"], a["waiting_on"]), ("waiting", False, None, ["bsh1"]))
        self.assertIs(d["shells"][0]["running"], True)

    def test_unanswered_foreground_bash_agent_is_running(self):
        self.side(extra=[_bash("u5", -1800, bg=False)])
        a = self.ag(self.sess())
        self.assertEqual((a["state"], a["running"]), ("running", True))
        self.host(None)
        self.assertEqual(self.ag(self.sess())["state"], "done")

    def test_interrupted_sync_spawn_that_later_completes_is_done(self):
        self.agent("a1", [_msg(_iso(-1900), "start"), _msg(_iso(-1500), "still working after the interrupt"),
                          _stop(_iso(-1499))], meta={"toolUseId": "tu1"}, age=1000)
        self.main_add([_msg(_iso(-2000), "spawn", tool_use=_spawn("tu1")),
                       _result("tu1", -1800, "[Request interrupted by user for tool use]",
                               "[Request interrupted by user for tool use]", err=True),
                       _result("tu1", -1490, "done", {"status": "completed", "agentId": "a1"})])
        self.assertEqual(self.ag(self.sess())["state"], "done")

    def test_sync_spawn_result_ends_agent_async_does_not(self):
        self.agent("a1", [_msg(_iso(-1900), "start"), _stop(_iso(-1000))], meta={"toolUseId": "tu1"}, age=1000)
        self.main_add([_msg(_iso(-2000), "spawn", tool_use=_spawn("tu1")),
                       _result("tu1", -1000, "done", {"status": "completed", "agentId": "a1"})])
        self.assertEqual(self.ag(self.sess())["state"], "done")
        self.main_add([_msg(_iso(-3000), "spawn", tool_use=_spawn("tu2")),
                       _result("tu2", -2900, "launched", {"status": "async_launched", "agentId": "a2"})])
        self.agent("a2", [_msg(_iso(-2950), "start")], meta={"toolUseId": "tu2"}, age=1000)
        self.assertEqual(self.ag(self.sess(), "a2")["state"], "running")

    def test_notification_in_another_sidecar_counts(self):
        self.side("a1")
        self.side("a0", extra=[{"type": "queue-operation", "timestamp": _iso(-1000),
                                "content": "<task-notification><task-id>a1</task-id></task-notification>"}])
        self.assertEqual(self.ag(self.sess())["state"], "done")

    def test_woken_agent_is_running_until_renotified(self):
        sp = self.side(extra=self.s1())
        self.notify(-1000, "a1")
        self.assertEqual(self.ag(self.sess())["state"], "waiting")
        with open(sp, "a") as fh:                       # woken by SendMessage: new work after the notification
            fh.write(json.dumps(_msg(_iso(-500), "woken")) + "\n")
        self.assertEqual(self.ag(self.sess())["state"], "running")
        self.notify(-50, "a1", op="remove")             # a dequeue row is not a notification
        self.assertEqual(self.ag(self.sess())["state"], "running")
        self.notify(-100, "a1")
        self.assertEqual(self.ag(self.sess())["state"], "waiting")

    def test_resumed_host_agent_woken_after_restart_is_running(self):
        sp = self.side()
        self.notify(-1000, "a1")
        self.host(-600)                                 # host restarted after the agent's first run
        self.assertEqual(self.ag(self.sess())["state"], "done")
        with open(sp, "a") as fh:
            fh.write(json.dumps(_msg(_iso(-300), "woken")) + "\n")
        self.assertEqual(self.ag(self.sess())["state"], "running")

    def test_shell_output_follows_host_gate(self):
        self.side(extra=self.s1())
        for off, want in ((None, False), (-3600, True), (-600, False)):
            self.host(off)
            self.assertIs(claude.shell_output(self.main, "bsh1")["running"], want, off)

    def test_error_exit_quoting_harness_sentence_is_not_a_shell(self):
        txt = "Exit code 1\nCommand running in background with ID: zzz9. Output is being written to: /tmp/t/zzz9.output"
        self.side(extra=[_bash("u6", -1800, bg=False), _result("u6", -1790, txt, txt, err=True)])
        self.notify(-1000, "a1")
        self.assertEqual(self.sess()["shells"], [])

    def test_sidecar_shell_listed_with_owner(self):
        self.side(extra=self.s1())
        sh = self.sess()["shells"]
        self.assertEqual([(s["id"], s["agent"], s["running"]) for s in sh], [("bsh1", "a1", True)])

    def test_moved_to_background_shell_listed(self):
        # (a) main, structured id + timeout wording
        self.main_add([_bash("m1", -1800, bg=False),
                       _result("m1", -1790, "Command did not complete within its 120s timeout and was moved to the background (ID: bmv1).",
                               {"backgroundTaskId": "bmv1"})])
        # (b) sidecar with no toolUseResult: harness text only, output path after the sentence
        txt = ("...test output...\nCommand was moved to the background (ID: bmv2) so that a message that arrived "
               "while it was running can reach you; it was not interrupted. Output is being written to: /tmp/t/bmv2.output")
        self.side(extra=[_bash("u2", -1800, bg=False), _result("u2", -1790, txt)])
        d = self.sess()
        sh = {s["id"]: s for s in d["shells"]}
        self.assertTrue(sh["bmv1"]["running"] and sh["bmv2"]["running"], sh)
        self.assertTrue(sh["bmv2"]["out"].endswith("/bmv2.output"))
        self.notify(-1000, "a1")
        a = self.ag(self.sess())
        self.assertEqual((a["state"], a["waiting_on"]), ("waiting", ["bmv2"]))

    def test_quoted_harness_text_is_not_a_shell(self):
        line = "Command did not complete within its 120s timeout and was moved to the background (ID: bq1)."
        # (a) dict toolUseResult without backgroundTaskId: the sentence starts a line (a cat of a log)
        # (b) no toolUseResult: the sentence is quoted mid-line (a grep over a transcript)
        for tur, q in (({"stdout": line, "interrupted": False}, line), (None, 'grep out: "content": "' + line + ' x"')):
            self.side(extra=[_bash("u3", -1800, bg=False), _result("u3", -1790, q, tur)])
            self.notify(-1000, "a1")
            d = self.sess()
            self.assertEqual(d["shells"], [], tur)
            self.assertEqual(self.ag(d)["state"], "done", tur)

    def test_refused_background_launch_is_not_a_shell(self):
        self.side(extra=[_bash("u4", -1800), _result("u4", -1790, "auto mode cannot determine the safety of Bash", err=True)])
        self.notify(-1000, "a1")
        d = self.sess()
        self.assertEqual(d["shells"], [])
        self.assertEqual(self.ag(d)["state"], "done")

    def test_completion_in_main_closes_sidecar_shell(self):
        self.side(extra=self.s1())
        self.notify(-1000, "a1")
        self.assertEqual(self.ag(self.sess())["state"], "waiting")
        self.notify(-900, "bsh1")
        d = self.sess()
        self.assertFalse(d["shells"][0]["running"])
        self.assertEqual(self.ag(d)["state"], "done")

    def test_failed_taskstop_keeps_shell_open_successful_closes(self):
        self.side(extra=self.s1())
        self.notify(-1000, "a1")
        self.main_add([_msg(_iso(-900), "stop", tool_use={"type": "tool_use", "id": "ts1", "name": "TaskStop", "input": {"task_id": "bsh1"}}),
                       _result("ts1", -890, "No task found", err=True)])
        self.assertEqual(self.ag(self.sess())["state"], "waiting")
        self.main_add([_msg(_iso(-800), "stop", tool_use={"type": "tool_use", "id": "ts2", "name": "TaskStop", "input": {"task_id": "bsh1"}}),
                       _result("ts2", -790, "Successfully stopped task")])
        d = self.sess()
        self.assertEqual(self.ag(d)["state"], "done")
        self.assertFalse(d["shells"][0]["running"])

    def test_agent_taskstopped_from_main_releases_its_shells(self):
        self.side(extra=self.s1())
        self.main_add([_msg(_iso(-900), "stop", tool_use={"type": "tool_use", "id": "ts3", "name": "TaskStop", "input": {"task_id": "a1"}}),
                       _result("ts3", -890, "Successfully stopped task")])
        d = self.sess()
        self.assertEqual(self.ag(d)["state"], "done")
        self.assertFalse(d["shells"][0]["running"])

    def test_monitor_is_not_a_shell(self):
        self.side(extra=[_msg(_iso(-1800), "m", tool_use={"type": "tool_use", "id": "mn1", "name": "Monitor", "input": {"command": "tail -f x"}}),
                         _result("mn1", -1790, "Monitor started", {"taskId": "bm1", "timeoutMs": 1800000})])
        self.notify(-1000, "a1")
        d = self.sess()
        self.assertEqual(d["shells"], [])
        self.assertEqual(self.ag(d)["state"], "done")

    def test_host_gate_orphans(self):
        self.side(extra=self.s1())
        boot = time.time() - time.clock_gettime(getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC))
        for label, off in (("no live file", None), ("procStart after launch", -600),
                           ("procStart before boot", boot - 7200 - time.time())):
            self.host(off)
            d = self.sess()
            self.assertEqual(self.ag(d)["state"], "done", label)
            self.assertFalse(d["shells"][0]["running"], label)

    def test_unknown_host_keeps_todays_rules(self):
        self.side(extra=self.s1())
        with mock.patch.object(config, "LIVE_SESSIONS_DIR", os.path.join(self.live, "missing")):
            d = self.sess()
        self.assertEqual(self.ag(d)["state"], "done")
        self.assertTrue(d["shells"][0]["running"])

    def test_gate_keys_on_file_name(self):
        self.side(extra=self.s1())
        self.main_add([{"type": "user", "sessionId": "other", "message": {"role": "user", "content": "later"}}])
        self.assertEqual(self.ag(self.sess())["state"], "running")

    def test_union_never_mutates_cached_agent_sets(self):
        sp = self.side(extra=self.s1() + [_msg(_iso(-1850), "sp", tool_use=_spawn("tu8")),
                                          _result("tu8", -1840, "x", {"status": "completed"}),
                                          {"type": "queue-operation", "timestamp": _iso(-1830),
                                           "content": "<task-notification><task-id>qq</task-id></task-notification>"}])
        self.sess()
        bg = claude._AGENT_CACHE[sp][1]["bg"]
        snap = {k: (set(bg[k]) if isinstance(bg[k], set) else dict(bg[k])) for k in ("done", "stopped", "nts", "ret")}
        self.main_add([_msg(_iso(-1900), "spawn", tool_use=_spawn("tu9")), _result("tu9", -900, "x", {"status": "completed"})])
        self.notify(-1000, "zzz")
        parse_session(self.main)
        self.assertEqual({k: bg[k] for k in snap}, snap)


if __name__ == "__main__":
    unittest.main()
