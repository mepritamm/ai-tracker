#!/usr/bin/env python3
"""Auggie parity + the drill-down seam.

Three capabilities Auggie sessions used to drop on the floor, and the route seam
that makes them clickable:

  (A) command exit status — every `tool_result_node` carries `is_error`; the parser
      already stored each command's `tool_use_id` but never joined them, so every
      Auggie command rendered green (`ok: True`, "Auggie stores no exit status").
  (B) sub-agents — `sub-agent-*` tool calls (~ Claude's `Task`) were hardcoded to [].
  (C) files touched — derived only from `changedFiles`, which is EMPTY in all 85
      real sessions on this machine; the real edits are `save-file` /
      `str-replace-editor` / `remove-files` calls.
  (D) /api/diff|output|shell|agent used to call providers.claude.find_session()
      directly, so every namespaced (auggie:/augment-vscode:) id 404'd on click.

Every fixture below mirrors the REAL on-disk shape confirmed against
~/.augment/sessions/*.json: `input_json` is a JSON **string**, and a tool's result
lands in the **next** exchange's `request_nodes` as a `tool_result_node`.
"""
import http.client
import json
import os
import tempfile
import threading
import unittest

import aitracker.config as config
from aitracker import registry, server as _server
from aitracker.providers import auggie as A
from aitracker.providers import claude as C


def _tu(tid, name, inp):
    """A response_nodes tool_use — input_json as the JSON *string* Auggie writes."""
    return {"tool_use": {"tool_use_id": tid, "tool_name": name, "input_json": json.dumps(inp)}}


def _tr(tid, content, is_error=False):
    return {"tool_result_node": {"tool_use_id": tid, "content": content, "is_error": is_error}}


IDE = {"ide_state_node": {"current_terminal": {"current_working_directory": "/work/repo"}}}


def _session(sid="s1"):
    """One realistic session: 2 commands (one failing), a created file, an edited
    file, a deleted file and a sub-agent — results arriving the exchange after."""
    return {
        "sessionId": sid, "modified": "2026-06-27T05:48:03Z", "customTitle": "Drill",
        "chatHistory": [
            {"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
                "request_message": "do the work", "response_text": "on it",
                "request_nodes": [IDE],
                "response_nodes": [
                    _tu("c_ok", "launch-process", {"command": "pytest -q"}),
                    _tu("c_bad", "launch-process", {"command": "npm test"}),
                    _tu("f_new", "save-file", {"path": "/abs/new.py", "file_content": "a\nb\n"}),
                    _tu("f_ed", "str-replace-editor", {"command": "str_replace", "path": "rel/app.py",
                                                       "old_str_1": "x", "new_str_1": "y"}),
                    _tu("f_rm", "remove-files", {"file_paths": ["rel/gone.py"]}),
                    _tu("a1", "sub-agent-explore", {"action": "run", "name": "read-seam",
                                                    "instruction": "read the provider seam"}),
                ]}},
            {"finishedAt": "2026-06-27T05:48:00Z", "exchange": {
                "request_nodes": [
                    _tr("c_ok", "3 passed"),
                    _tr("c_bad", "Here are the results from executing the command.\n"
                                 "<return-code>\n1\n</return-code>\n<output>\nzsh:1: parse error", True),
                ],
                "response_text": "done"}},
        ]}


class _AuggieEnv(unittest.TestCase):
    """Repoint the Auggie data paths at a temp dir holding one written session."""

    def setUp(self):
        self._snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE,
                      config.NOTES_FILE, config.TASKS_DIR)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        A._AUGGIE_LIST_CACHE.clear()
        self.write(_session("s1"))

    def tearDown(self):
        (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE,
         config.NOTES_FILE, config.TASKS_DIR) = self._snap
        A._AUGGIE_LIST_CACHE.clear()

    def write(self, d):
        with open(os.path.join(config.AUGGIE_SESSIONS, d["sessionId"] + ".json"), "w") as fh:
            json.dump(d, fh)
        A._AUGGIE_LIST_CACHE.clear()


# --------------------------------------------------------------------------- helpers

class TestToolInput(unittest.TestCase):
    """input_json is a JSON string in real logs, a dict in older fixtures."""

    def test_json_string(self):
        self.assertEqual(A._tool_input({"input_json": '{"path": "a.py"}'}), {"path": "a.py"})

    def test_dict_passthrough(self):
        self.assertEqual(A._tool_input({"input_json": {"path": "a.py"}}), {"path": "a.py"})

    def test_malformed_and_missing(self):
        self.assertEqual(A._tool_input({"input_json": "not json"}), {})
        self.assertEqual(A._tool_input({}), {})
        self.assertEqual(A._tool_input({"input_json": ["a"]}), {})   # non-dict JSON


class TestEditPairs(unittest.TestCase):
    """str-replace-editor numbers its edits; some calls use the unnumbered form."""

    def test_numbered_multi_edit(self):
        inp = {"old_str_1": "a", "new_str_1": "b", "old_str_2": "c", "new_str_2": "d"}
        self.assertEqual(A._edit_pairs(inp), [("a", "b"), ("c", "d")])

    def test_unnumbered(self):
        self.assertEqual(A._edit_pairs({"old_str": "a", "new_str": "b"}), [("a", "b")])

    def test_insert_has_no_old_text(self):
        self.assertEqual(A._edit_pairs({"new_str_1": "added", "insert_line_1": 4}),
                         [("", "added")])

    def test_gap_stops_the_walk(self):
        # _2 missing => _3 is unreachable; never spin forever on a sparse numbering
        self.assertEqual(A._edit_pairs({"old_str_1": "a", "new_str_1": "b",
                                        "old_str_3": "c", "new_str_3": "d"}), [("a", "b")])

    def test_empty(self):
        self.assertEqual(A._edit_pairs({}), [])


class TestAbs(unittest.TestCase):
    """Auggie logs most edit paths relative to the session cwd."""

    def test_relative_is_anchored(self):
        self.assertEqual(A._abs("rel/app.py", "/work/repo"), "/work/repo/rel/app.py")

    def test_absolute_untouched(self):
        self.assertEqual(A._abs("/abs/app.py", "/work/repo"), "/abs/app.py")

    def test_no_cwd_leaves_it_alone(self):
        self.assertEqual(A._abs("rel/app.py", ""), "rel/app.py")

    def test_empty_path(self):
        self.assertEqual(A._abs("", "/work/repo"), "")


# --------------------------------------------------------- (A) command exit status

class TestCommandExitStatus(_AuggieEnv):

    def test_failed_command_is_not_ok(self):
        d = A.parse_auggie("s1")
        by = {c["id"]: c for c in d["commands"]}
        self.assertTrue(by["c_ok"]["ok"])
        self.assertFalse(by["c_bad"]["ok"], "is_error on the tool_result_node must reach the command")

    def test_counts_unpinned(self):
        c = A.parse_auggie("s1")["counts"]
        self.assertEqual(c["errors"], 1)         # was hardcoded 0
        self.assertEqual(c["tests"], 2)
        self.assertEqual(c["tests_failed"], 1)   # was hardcoded 0

    def test_no_result_yet_stays_ok(self):
        """A command still running has no tool_result_node — don't paint it red."""
        d = _session("s2")
        d["chatHistory"] = d["chatHistory"][:1]          # drop the results exchange
        self.write(d)
        by = {c["id"]: c for c in A.parse_auggie("s2")["commands"]}
        self.assertTrue(by["c_bad"]["ok"])
        self.assertEqual(A.parse_auggie("s2")["counts"]["errors"], 0)


# ------------------------------------------------------------------ (B) sub-agents

class TestSubAgents(_AuggieEnv):

    def test_sub_agent_call_becomes_an_agent(self):
        d = A.parse_auggie("s1")
        self.assertEqual(len(d["agents"]), 1)
        a = d["agents"][0]
        self.assertEqual(a["type"], "explore")      # from the tool name, ~ subagent_type
        self.assertEqual(a["desc"], "read-seam")    # from input.name, ~ description
        self.assertEqual(d["counts"]["agents"], 1)  # was hardcoded 0

    def test_agents_reach_the_overview_line(self):
        self.assertIn("dispatched 1 sub-agent(s)", A.parse_auggie("s1")["overview"]["sofar"])

    def test_instruction_is_the_desc_fallback(self):
        d = _session("s3")
        d["chatHistory"][0]["exchange"]["response_nodes"] = [
            _tu("a1", "sub-agent-general-purpose", {"action": "run", "instruction": "survey the config"})]
        self.write(d)
        a = A.parse_auggie("s3")["agents"][0]
        self.assertEqual((a["type"], a["desc"]), ("general-purpose", "survey the config"))


# ---------------------------------------------------------------------- (C) files

class TestFilesTouched(_AuggieEnv):

    def test_edit_tools_fill_the_files_panel(self):
        d = A.parse_auggie("s1")
        by = {f["path"]: f for f in d["files"]}
        self.assertIn("/abs/new.py", by)
        self.assertTrue(by["/abs/new.py"]["created"], "save-file == Claude's Write")
        self.assertIn("/work/repo/rel/app.py", by)        # relative path anchored to the cwd
        self.assertFalse(by["/work/repo/rel/app.py"]["created"])
        self.assertIn("/work/repo/rel/gone.py", by)       # remove-files still counts as touched

    def test_counts(self):
        c = A.parse_auggie("s1")["counts"]
        self.assertEqual(c["created"], 1)   # was hardcoded 0
        self.assertEqual(c["edited"], 2)

    def test_repeated_edits_accumulate_ops(self):
        d = _session("s4")
        d["chatHistory"][0]["exchange"]["response_nodes"] = [
            _tu("e1", "str-replace-editor", {"path": "a.py", "old_str_1": "1", "new_str_1": "2"}),
            _tu("e2", "str-replace-editor", {"path": "a.py", "old_str_1": "2", "new_str_1": "3"})]
        self.write(d)
        f = A.parse_auggie("s4")["files"][0]
        self.assertEqual((f["path"], f["ops"]), ("/work/repo/a.py", 2))

    def test_save_after_edit_still_reads_created(self):
        d = _session("s5")
        d["chatHistory"][0]["exchange"]["response_nodes"] = [
            _tu("e1", "str-replace-editor", {"path": "a.py", "old_str_1": "1", "new_str_1": "2"}),
            _tu("e2", "save-file", {"path": "a.py", "file_content": "z"})]
        self.write(d)
        self.assertTrue(A.parse_auggie("s5")["files"][0]["created"])

    def test_no_edits_means_empty_panel(self):
        d = _session("s6")
        d["chatHistory"][0]["exchange"]["response_nodes"] = [
            _tu("c1", "launch-process", {"command": "ls"})]
        self.write(d)
        p = A.parse_auggie("s6")
        self.assertEqual(p["files"], [])
        self.assertEqual((p["counts"]["created"], p["counts"]["edited"]), (0, 0))


# ------------------------------------------------- drill-downs: output + file diffs

class TestAuggieDrillDowns(_AuggieEnv):

    def test_command_output_is_verbatim(self):
        o = A.command_output("s1", "c_bad")
        self.assertEqual(o["cmd"], "npm test")
        self.assertIn("<return-code>\n1\n</return-code>", o["out"])
        self.assertFalse(o["ok"])

    def test_command_output_ok_path(self):
        o = A.command_output("s1", "c_ok")
        self.assertEqual((o["cmd"], o["out"], o["ok"]), ("pytest -q", "3 passed", True))

    def test_unknown_command_id_is_empty_not_an_error(self):
        self.assertEqual(A.command_output("s1", "nope"), {"cmd": "", "out": "", "ok": True})

    def test_missing_session_is_none(self):
        self.assertIsNone(A.command_output("gone", "c_ok"))
        self.assertIsNone(A.file_diffs("gone", "/abs/new.py"))

    def test_diff_of_a_created_file(self):
        ops = A.file_diffs("s1", "/abs/new.py")
        self.assertEqual([o["kind"] for o in ops], ["created"])
        self.assertIn("+a", ops[0]["diff"])
        self.assertIn("+b", ops[0]["diff"])

    def test_diff_of_an_edit_uses_the_anchored_path(self):
        ops = A.file_diffs("s1", "/work/repo/rel/app.py")
        self.assertEqual([o["kind"] for o in ops], ["edited"])
        self.assertIn("-x", ops[0]["diff"])
        self.assertIn("+y", ops[0]["diff"])
        self.assertEqual(A.file_diffs("s1", "rel/app.py"), [],
                         "the un-anchored path is not what the Files panel emits")

    def test_diff_of_an_untouched_file_is_empty(self):
        self.assertEqual(A.file_diffs("s1", "/abs/never.py"), [])

    def test_every_files_row_is_diffable(self):
        """The panel must not offer a row whose click yields nothing (except a
        delete, which has no content to diff)."""
        d = A.parse_auggie("s1")
        for f in d["files"]:
            if f["path"].endswith("gone.py"):
                continue
            self.assertTrue(A.file_diffs("s1", f["path"]), f["path"])


# --------------------------------------------------- session-id path-traversal guard

class TestSessionIdSanitisation(_AuggieEnv):
    """`auggie:<id>` is unsanitised user input straight from the URL — the id
    portion must not be able to escape AUGGIE_SESSIONS via `..`/separators to read
    an arbitrary `.json` file on the filesystem (pre-existing hole on
    /api/session at 85a21bf; this branch put it on 4 routes, so it's fixed here)."""

    def test_traversal_id_cannot_read_an_arbitrary_json_file(self):
        secret = os.path.join(config.AUGMENT_DIR, "secret.json")
        with open(secret, "w") as fh:
            json.dump({"sessionId": "secret", "chatHistory": [
                {"finishedAt": "t", "exchange": {
                    "response_nodes": [_tu("x", "launch-process",
                                            {"command": "SECRET-COMMAND-LEAKED"})]}},
                {"finishedAt": "t2", "exchange": {"request_nodes": [
                    _tr("x", "SECRET-OUTPUT-LEAKED")]}},
            ]}, fh)
        traversal_id = "../secret"    # AUGGIE_SESSIONS/../secret.json == AUGMENT_DIR/secret.json
        self.assertIsNone(A.command_output(traversal_id, "x"),
                          "must not read outside AUGGIE_SESSIONS")
        self.assertIsNone(A.file_diffs(traversal_id, "/a.py"))
        self.assertIsNone(registry.drill("auggie:" + traversal_id, "output", "x"))
        self.assertFalse(A.AuggieProvider().exists("auggie:" + traversal_id))

    def test_separators_and_traversal_and_nul_bytes_are_rejected(self):
        for bad in ("../x", "a/b", "a\\b", "a\x00b", ".."):
            self.assertIsNone(A._safe_session_id(bad), bad)
        self.assertEqual(A._safe_session_id("s1"), "s1")   # a normal id passes through


# -------------------------------------------------------------- (D) the route seam

class TestRegistryDrillSeam(_AuggieEnv):

    def test_routes_to_the_owning_provider(self):
        self.assertIsInstance(registry.provider_for("auggie:s1"), A.AuggieProvider)
        self.assertIsInstance(registry.provider_for("abc123"), C.ClaudeProvider)

    def test_auggie_output_through_the_seam(self):
        d = registry.drill("auggie:s1", "output", "c_bad")
        self.assertFalse(d["ok"])
        self.assertIn("return-code", d["out"])

    def test_auggie_diff_through_the_seam(self):
        self.assertEqual(len(registry.drill("auggie:s1", "diff", "/abs/new.py")), 1)

    def test_missing_session_returns_none_so_the_route_404s(self):
        self.assertIsNone(registry.drill("auggie:nope", "output", "c1"))

    def test_unknown_kind_is_refused(self):
        self.assertIsNone(registry.drill("auggie:s1", "parse", "x"))

    def test_unsupported_view_degrades_to_empty_not_404(self):
        """Auggie has no background shells/agents of its own — for a session that
        DOES exist (s1, written in setUp), the base default answers with an empty
        view so the modal says 'nothing', not 'error'."""
        self.assertEqual(registry.drill("auggie:s1", "shell", "sh1"),
                         {"cmd": "", "out": "", "running": False})
        self.assertEqual(registry.drill("auggie:s1", "agent", "a1"), {})

    def test_missing_auggie_session_404s_on_every_drill_kind(self):
        """A bogus auggie id must 404 on ALL FOUR drill kinds — including shell/agent,
        which AuggieProvider never overrides. Before registry.drill() checked
        exists() first, a bogus id fell through to the base class's empty default
        (200) on shell/agent instead of 404 — output/diff already 404'd because
        _load_auggie() itself returns None, but shell/agent silently did not."""
        for kind, arg in (("output", "c1"), ("diff", "/a.py"), ("shell", "sh1"), ("agent", "a1")):
            self.assertIsNone(registry.drill("auggie:nope", kind, arg), kind)

    def test_augment_ext_ids_do_not_fall_off_the_seam(self):
        """The VSCode/Cursor providers emit a files panel but record no diffs, and
        never override output/diff/shell/agent — for a REAL session (a task file
        that actually exists on disk) they must return the base default, never None
        (which the route 404s). For a session that does NOT exist on disk, they must
        404 like every other provider — registry.drill() calls exists() (the base
        default: a full parse()) before ever reaching the empty default, so a bogus
        augment-vscode/-cursor id can no longer read back as 200+empty."""
        orig_vs, orig_cur = config.VSCODE_WS_ROOT, config.CURSOR_WS_ROOT
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()
        config.CURSOR_WS_ROOT = tempfile.mkdtemp()
        try:
            for root in (config.VSCODE_WS_ROOT, config.CURSOR_WS_ROOT):
                aug = os.path.join(root, "ws", "Augment.vscode-augment")
                tasks_dir = os.path.join(aug, "augment-user-assets", "task-storage", "tasks")
                os.makedirs(tasks_dir)
                with open(os.path.join(root, "ws", "workspace.json"), "w") as fh:
                    json.dump({"folder": "file:///repo/x"}, fh)
                with open(os.path.join(tasks_dir, "uu.json"), "w") as fh:
                    json.dump({"uuid": "uu", "name": "a real task"}, fh)

            # a REAL session (task "uu" exists in workspace "ws") -> the base default
            # answers, not None
            self.assertEqual(registry.drill("augment-vscode:ws:uu", "diff", "/a.py"), [])
            self.assertEqual(registry.drill("augment-cursor:ws:uu", "output", "c1"),
                             {"cmd": "", "out": "", "ok": True})
            # no such workspace/task on disk -> the route 404s, same as every provider
            self.assertIsNone(registry.drill("augment-vscode:ws:nope", "diff", "/a.py"))
            self.assertIsNone(registry.drill("augment-cursor:x:y", "output", "c1"))
        finally:
            config.VSCODE_WS_ROOT, config.CURSOR_WS_ROOT = orig_vs, orig_cur


class TestClaudeDrillStillWorks(unittest.TestCase):
    """The seam must not regress the provider it was hardwired to."""

    def setUp(self):
        self._snap = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        d = os.path.join(config.PROJECTS, "proj")
        os.makedirs(d)
        rows = [
            {"type": "user", "cwd": "/x/proj", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "npm test"}},
                {"type": "tool_use", "id": "w1", "name": "Write",
                 "input": {"file_path": "/x/proj/a.py", "content": "hello\n"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "b1", "content": "boom", "is_error": True}]}},
        ]
        with open(os.path.join(d, "csess.jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        C._META_CACHE.clear()

    def tearDown(self):
        config.PROJECTS = self._snap
        C._META_CACHE.clear()

    def test_output(self):
        d = registry.drill("csess", "output", "b1")
        self.assertEqual(d["cmd"], "npm test")
        self.assertFalse(d["ok"])

    def test_diff(self):
        ops = registry.drill("csess", "diff", "/x/proj/a.py")
        self.assertEqual([o["kind"] for o in ops], ["created"])

    def test_missing_claude_session_still_404s(self):
        self.assertIsNone(registry.drill("nosuch", "output", "b1"))


# --------------------------------------------------------------- end-to-end (HTTP)

class TestDrillDownRoutes(_AuggieEnv):
    """Boot the real server: the four drill-down routes must serve a namespaced id."""

    def setUp(self):
        super().setUp()
        self._proj = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        config.PROJECTS = self._proj
        super().tearDown()

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, json.loads(body)

    def test_session_route_carries_the_three_capabilities(self):
        st, d = self._get("/api/session?id=auggie:s1")
        self.assertEqual(st, 200)
        self.assertTrue(d["files"], "files must not be empty for an Auggie session")
        self.assertTrue(d["agents"])
        self.assertIn(False, [c["ok"] for c in d["commands"]])

    def test_output_route(self):
        st, d = self._get("/api/output?id=auggie:s1&cmd=c_bad")
        self.assertEqual(st, 200)
        self.assertFalse(d["ok"])
        self.assertIn("return-code", d["out"])

    def test_diff_route(self):
        st, d = self._get("/api/diff?id=auggie:s1&file=%2Fabs%2Fnew.py")
        self.assertEqual(st, 200)
        self.assertEqual([o["kind"] for o in d["ops"]], ["created"])

    def test_shell_and_agent_routes_do_not_404(self):
        for path in ("/api/shell?id=auggie:s1&shell=x", "/api/agent?id=auggie:s1&agent=x"):
            st, _ = self._get(path)
            self.assertEqual(st, 200, path)

    def test_missing_session_still_404s(self):
        for path in ("/api/output?id=auggie:nope&cmd=c1", "/api/diff?id=auggie:nope&file=/a.py"):
            st, d = self._get(path)
            self.assertEqual(st, 404, path)
            self.assertEqual(d["error"], "session not found")


if __name__ == "__main__":
    unittest.main()
