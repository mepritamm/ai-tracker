"""Granular unit tests for four capabilities that just landed on the shared registry
seam (aitracker/registry.py) and its providers:

  * fail_cmd    -- session-LIST dict only. Claude derives it in providers/claude.py's
                   _tail_scan(); Auggie in providers/auggie.py's _auggie_fail_cmd();
                   providers/augment_ext.py always emits None (no command stream to
                   read). registry.py:89 setdefault()s it so the key is ALWAYS present.
  * flag_text   -- session-LIST dict (registry.py:82) AND detail dict (registry.py:132),
                   sourced from the app-owned flags.json, shared by every provider.
  * term_attached -- detail dict only (registry.py:145 / _term_attached at :149):
                   whether a live Claude CLI is the foreground process of any open
                   terminal against this session, off term_vt.PTYS.
  * pinned      -- detail dict (registry.py:128), from pins.json.

tests/test_selfcheck.py carries the fixture-style behavioral eval for these same four
capabilities (one assertion each, in the same giant `_run()` the whole suite already
exercises via test_tracker.py). This file is the unit-test companion: one TestCase
method per distinct path / branch / edge case, run and reported individually.

Stdlib unittest only. Each test manages its own tempdir + config overrides and
restores them in tearDown, so tests here never depend on ordering or leak into
test_selfcheck.py's own (much bigger) fixture tree.
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from aitracker.registry import all_sessions, parse_any
import aitracker.registry as registry
from aitracker.providers.claude import _tail_scan, list_sessions, _is_real_bash_error
from aitracker.providers.auggie import (_auggie_fail_cmd, list_auggie, _AUGGIE_LIST_CACHE,
                                         _auggie_is_real_launch_error)
from aitracker.providers.augment_ext import AugmentVscodeProvider
from aitracker.store import save_flags, _save_json


def _write_jsonl(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return path


def _claude_session(dirpath, name, rows, cwd="/tmp/proj"):
    """A minimal Claude transcript: an opening user turn (so cwd/entrypoint resolve)
    plus whatever extra rows the caller supplies."""
    head = {"type": "user", "cwd": cwd, "entrypoint": "cli",
            "message": {"role": "user", "content": "go"}}
    p = os.path.join(dirpath, name + ".jsonl")
    _write_jsonl(p, [head] + rows)
    return name


BASH_USE = {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "make test"}}]}}


def _bash_result(is_error, content="out"):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "b1", "is_error": is_error, "content": content}]}}


class ClaudeFailCmdTests(unittest.TestCase):
    """providers/claude.py's _tail_scan() -- the pure derivation -- and its wiring
    onto list_sessions()."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)

    def tearDown(self):
        config.PROJECTS = self._pdir_snap

    def test_no_bash_at_all_is_honestly_none(self):
        p = _claude_session(self.sdir, "s_nobash", [])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_errored_result_surfaces_the_command(self):
        p = _claude_session(self.sdir, "s_fail", [BASH_USE, _bash_result(True)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertEqual(_tail_scan(path)["fail_cmd"], "make test")

    def test_clean_result_is_none(self):
        p = _claude_session(self.sdir, "s_ok", [BASH_USE, _bash_result(False)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    # -- noise filter: a framework refusal is not a real command failure --------
    # (reports/drift/: 116/957 real sessions carried a fail_cmd before this filter,
    # every one of them one of Claude Code's own never-ran-at-all refusals — see
    # _is_real_bash_error's docstring, providers/claude.py.)

    def test_permission_denied_refusal_yields_no_fail_cmd(self):
        content = ("Permission to use Bash has been denied because Claude Code is "
                   "running in don't ask mode")
        p = _claude_session(self.sdir, "s_perm", [BASH_USE, _bash_result(True, content=content)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_blocked_tool_use_error_refusal_yields_no_fail_cmd(self):
        content = "<tool_use_error>Blocked: this command is not allowed</tool_use_error>"
        p = _claude_session(self.sdir, "s_blocked", [BASH_USE, _bash_result(True, content=content)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_worktree_isolation_refusal_yields_no_fail_cmd(self):
        content = "This session is isolated in the worktree and cannot run this command"
        p = _claude_session(self.sdir, "s_iso", [BASH_USE, _bash_result(True, content=content)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_genuine_failure_with_real_command_output_still_sets_fail_cmd(self):
        """The filter must not go the OTHER way -- a real, non-refusal failure
        (actual command output, not one of the fixed refusal strings) still
        surfaces the command."""
        content = "AssertionError: 1 != 2\nFAILED tests/test_x.py::test_thing"
        p = _claude_session(self.sdir, "s_real_fail", [BASH_USE, _bash_result(True, content=content)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertEqual(_tail_scan(path)["fail_cmd"], "make test")

    def test_later_pass_clears_an_earlier_fail(self):
        """'Latest wins' -- a second, different Bash command that PASSES after an
        earlier one FAILED must clear fail_cmd, matching model/last_text's own
        'what's true right now' rule."""
        second_use = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "b2", "name": "Bash", "input": {"command": "make retest"}}]}}
        second_ok = {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "b2", "is_error": False, "content": "out"}]}}
        p = _claude_session(self.sdir, "s_recover",
                             [BASH_USE, _bash_result(True), second_use, second_ok])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_no_tool_use_id_is_never_matched(self):
        """A Bash tool_use with no `id` can never be joined to a result -- must not
        crash, must stay honestly None."""
        bad_use = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "make test"}}]}}
        p = _claude_session(self.sdir, "s_noid", [bad_use, _bash_result(True)])
        path = os.path.join(self.sdir, p + ".jsonl")
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_missing_cwd_field_does_not_crash(self):
        """EDGE CASE: no 'cwd' key on any line at all -- _tail_scan doesn't even look
        at cwd, but the wiring through list_sessions() must still not crash and must
        fall back to an honest empty cwd."""
        path = os.path.join(self.sdir, "s_nocwd.jsonl")
        _write_jsonl(path, [{"type": "user", "message": {"role": "user", "content": "hi"}},
                             BASH_USE, _bash_result(True)])
        rows = {s["id"]: s for s in list_sessions()}
        self.assertEqual(rows["s_nocwd"]["cwd"], "")
        self.assertEqual(rows["s_nocwd"]["fail_cmd"], "make test")

    def test_malformed_trailing_line_does_not_crash(self):
        """EDGE CASE: a truncated JSON line at the very end of the tail must be
        skipped, not raise -- and a real failure seen before it must still count."""
        path = os.path.join(self.sdir, "s_trunc.jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": "/tmp/proj",
                                  "message": {"role": "user", "content": "go"}}) + "\n")
            fh.write(json.dumps(BASH_USE) + "\n")
            fh.write(json.dumps(_bash_result(True)) + "\n")
            fh.write('{"type": "user", "message": {"content": [{"trunc')  # no closing, no newline
        self.assertEqual(_tail_scan(path)["fail_cmd"], "make test")

    def test_empty_file_does_not_crash(self):
        """EDGE CASE: a zero-byte transcript (e.g. created but never written to)."""
        path = os.path.join(self.sdir, "s_empty.jsonl")
        open(path, "w").close()
        self.assertIsNone(_tail_scan(path)["fail_cmd"])

    def test_key_always_present_on_list_sessions_regardless_of_outcome(self):
        _claude_session(self.sdir, "s_a", [BASH_USE, _bash_result(True)])
        _claude_session(self.sdir, "s_b", [BASH_USE, _bash_result(False)])
        _claude_session(self.sdir, "s_c", [])
        rows = {s["id"]: s for s in list_sessions()}
        for sid in ("s_a", "s_b", "s_c"):
            self.assertIn("fail_cmd", rows[sid], sid)


class IsRealBashErrorTests(unittest.TestCase):
    """Direct unit tests of the pure predicate itself (providers/claude.py's
    _is_real_bash_error), no transcript/file plumbing needed."""

    def test_every_fixed_refusal_prefix_is_not_real(self):
        for prefix in (
            "Permission to use Bash has been denied because Claude Code is running in don't ask mode",
            "This session is isolated in the worktree and cannot run this command",
            "Permission for this action was denied by the Claude Code auto mode classifier",
            "The user doesn't want to proceed with this tool use.",
            "<tool_use_error>Blocked: rm -rf /</tool_use_error>",
            "<tool_use_error>Cancelled: sibling call errored</tool_use_error>",
        ):
            self.assertFalse(_is_real_bash_error(prefix), prefix)

    def test_auto_mode_unavailable_substring_is_not_real(self):
        text = "claude-sonnet-5 is temporarily unavailable, so auto mode cannot determine the safety of Bash right now"
        self.assertFalse(_is_real_bash_error(text))

    def test_genuine_output_is_real(self):
        self.assertTrue(_is_real_bash_error("AssertionError: 1 != 2"))

    def test_non_string_content_is_treated_as_real(self):
        """Content that can't be classified either way (None, a dict, ...) must
        never silently hide a real is_error result."""
        self.assertTrue(_is_real_bash_error(None))
        self.assertTrue(_is_real_bash_error({}))

    def test_empty_string_is_treated_as_real(self):
        self.assertTrue(_is_real_bash_error(""))


class AuggieFailCmdTests(unittest.TestCase):
    """providers/auggie.py's _auggie_fail_cmd() -- the pure derivation -- and its
    wiring onto list_auggie()."""

    def setUp(self):
        self._augment_dir_snap = config.AUGMENT_DIR
        self._auggie_sessions_snap = config.AUGGIE_SESSIONS
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        _AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        config.AUGMENT_DIR = self._augment_dir_snap
        config.AUGGIE_SESSIONS = self._auggie_sessions_snap
        _AUGGIE_LIST_CACHE.clear()

    def _launch_use(self, cid, cmd):
        return {"tool_use": {"tool_name": "launch-process", "tool_use_id": cid,
                              "input_json": json.dumps({"command": cmd})}}

    def _launch_result(self, cid, is_error, content=None):
        trn = {"tool_use_id": cid, "is_error": is_error}
        if content is not None:
            trn["content"] = content
        return {"tool_result_node": trn}

    def test_missing_chathistory_key_entirely_is_none(self):
        """EDGE CASE: an Auggie session lacking the field entirely (no 'chatHistory'
        key at all in the on-disk JSON, not merely an empty list)."""
        self.assertIsNone(_auggie_fail_cmd(None))

    def test_empty_chathistory_is_none(self):
        self.assertIsNone(_auggie_fail_cmd([]))

    def test_errored_result_surfaces_the_command(self):
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                {"exchange": {"request_nodes": [self._launch_result("c1", True)]}}]
        self.assertEqual(_auggie_fail_cmd(chat), "npm test")

    def test_clean_result_is_none(self):
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                {"exchange": {"request_nodes": [self._launch_result("c1", False)]}}]
        self.assertIsNone(_auggie_fail_cmd(chat))

    # -- noise filter: an Auggie pre-exec guard refusal is not a real command
    # failure either -- same reasoning, same corpus, as Claude's _is_real_bash_error.

    def test_backticks_refusal_yields_no_fail_cmd(self):
        content = "Error: Backticks are not allowed in shell commands"
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                {"exchange": {"request_nodes": [self._launch_result("c1", True, content=content)]}}]
        self.assertIsNone(_auggie_fail_cmd(chat))

    def test_rejected_with_user_message_refusal_yields_no_fail_cmd(self):
        content = "Tool use rejected with user message: not now"
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                {"exchange": {"request_nodes": [self._launch_result("c1", True, content=content)]}}]
        self.assertIsNone(_auggie_fail_cmd(chat))

    def test_genuine_failure_with_real_command_output_still_sets_fail_cmd(self):
        content = "exit code 1: npm test failed with 3 failing specs"
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                {"exchange": {"request_nodes": [self._launch_result("c1", True, content=content)]}}]
        self.assertEqual(_auggie_fail_cmd(chat), "npm test")

    def test_pending_command_with_no_result_yet_is_none(self):
        chat = [{"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}}]
        self.assertIsNone(_auggie_fail_cmd(chat))

    def test_later_pass_clears_an_earlier_fail(self):
        chat = [
            {"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
            {"exchange": {"request_nodes": [self._launch_result("c1", True)]}},
            {"exchange": {"response_nodes": [self._launch_use("c2", "npm retest")]}},
            {"exchange": {"request_nodes": [self._launch_result("c2", False)]}},
        ]
        self.assertIsNone(_auggie_fail_cmd(chat))

    def test_non_launch_process_tool_use_is_ignored(self):
        """A view/save-file/etc. tool_use must never be mistaken for a command."""
        chat = [{"exchange": {"response_nodes": [
            {"tool_use": {"tool_name": "view", "tool_use_id": "v1",
                          "input_json": json.dumps({"path": "app.py"})}}]}},
                {"exchange": {"request_nodes": [self._launch_result("v1", True)]}}]
        self.assertIsNone(_auggie_fail_cmd(chat))

    def test_wired_onto_list_auggie_key_always_present(self):
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_fail.json"), "w") as fh:
            json.dump({"sessionId": "sess_fail", "modified": "2026-06-27T05:48:03Z",
                       "chatHistory": [
                           {"exchange": {"response_nodes": [self._launch_use("c1", "npm test")]}},
                           {"exchange": {"request_nodes": [self._launch_result("c1", True)]}},
                       ]}, fh)
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_clean.json"), "w") as fh:
            json.dump({"sessionId": "sess_clean", "modified": "2026-06-27T05:48:03Z",
                       "chatHistory": []}, fh)
        # EDGE CASE: a session file with no chatHistory key at all
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_nofield.json"), "w") as fh:
            json.dump({"sessionId": "sess_nofield", "modified": "2026-06-27T05:48:03Z"}, fh)
        rows = {s["id"]: s for s in list_auggie()}
        self.assertEqual(rows["auggie:sess_fail"]["fail_cmd"], "npm test")
        self.assertIsNone(rows["auggie:sess_clean"]["fail_cmd"])
        self.assertIn("fail_cmd", rows["auggie:sess_clean"])
        self.assertIsNone(rows["auggie:sess_nofield"]["fail_cmd"])
        self.assertIn("fail_cmd", rows["auggie:sess_nofield"])


class IsRealLaunchErrorTests(unittest.TestCase):
    """Direct unit tests of the pure predicate itself (providers/auggie.py's
    _auggie_is_real_launch_error), no chatHistory plumbing needed."""

    def test_every_fixed_refusal_prefix_is_not_real(self):
        for prefix in (
            "Error: Backticks are not allowed in shell commands",
            "Tool use rejected with user message: not now",
        ):
            self.assertFalse(_auggie_is_real_launch_error(prefix), prefix)

    def test_genuine_output_is_real(self):
        self.assertTrue(_auggie_is_real_launch_error("exit code 1: 3 failing specs"))

    def test_non_string_content_is_treated_as_real(self):
        self.assertTrue(_auggie_is_real_launch_error(None))
        self.assertTrue(_auggie_is_real_launch_error({}))

    def test_empty_string_is_treated_as_real(self):
        self.assertTrue(_auggie_is_real_launch_error(""))


class AugmentExtFailCmdTests(unittest.TestCase):
    """providers/augment_ext.py has no command/tool-result stream at all -- fail_cmd
    must always be honestly None, never omitted."""

    def setUp(self):
        self._vscode_snap = config.VSCODE_WS_ROOT
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()

    def tearDown(self):
        config.VSCODE_WS_ROOT = self._vscode_snap

    def test_always_none_key_always_present(self):
        ws = os.path.join(config.VSCODE_WS_ROOT, "wshash")
        tasks = os.path.join(ws, "Augment.vscode-augment", "augment-user-assets", "task-storage", "tasks")
        os.makedirs(tasks)
        with open(os.path.join(ws, "workspace.json"), "w") as fh:
            json.dump({"folder": "file:///x/proj"}, fh)
        with open(os.path.join(tasks, "root.json"), "w") as fh:
            json.dump({"uuid": "root", "name": "Current Task List", "subTasks": []}, fh)
        rows = AugmentVscodeProvider().list()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["fail_cmd"])
        self.assertIn("fail_cmd", rows[0])


class RegistrySetdefaultTests(unittest.TestCase):
    """registry.py:89's setdefault() -- the seam guarantee that EVERY session on the
    list dict carries a fail_cmd key, even a provider that forgot to set one."""

    def setUp(self):
        self._providers_snap = registry.PROVIDERS

    def tearDown(self):
        registry.PROVIDERS = self._providers_snap

    def test_missing_key_is_backfilled_as_none(self):
        class _Bare:
            prefix = "bare:"
            def available(self):
                return True
            def list(self):
                return [{"id": "bare:x", "mtime": time.time()}]  # no fail_cmd key
        registry.PROVIDERS = [_Bare()]
        rows = {s["id"]: s for s in all_sessions()}
        self.assertIn("fail_cmd", rows["bare:x"])
        self.assertIsNone(rows["bare:x"]["fail_cmd"])

    def test_a_provider_that_DOES_set_it_is_left_alone(self):
        class _Setter:
            prefix = "setter:"
            def available(self):
                return True
            def list(self):
                return [{"id": "setter:x", "mtime": time.time(), "fail_cmd": "already set"}]
        registry.PROVIDERS = [_Setter()]
        rows = {s["id"]: s for s in all_sessions()}
        self.assertEqual(rows["setter:x"]["fail_cmd"], "already set")

    def test_a_broken_provider_does_not_sink_the_whole_list(self):
        """A provider whose list() raises must not take fail_cmd (or anything else)
        down with it for the OTHER providers -- registry.all_sessions()'s existing
        try/except around each provider."""
        class _Bad:
            prefix = "bad:"
            def available(self):
                return True
            def list(self):
                raise RuntimeError("boom")
        class _Good:
            prefix = "good:"
            def available(self):
                return True
            def list(self):
                return [{"id": "good:x", "mtime": time.time()}]
        registry.PROVIDERS = [_Bad(), _Good()]
        rows = {s["id"]: s for s in all_sessions()}
        self.assertIn("good:x", rows)
        self.assertIsNone(rows["good:x"]["fail_cmd"])


class FlagTextTests(unittest.TestCase):
    """flag_text on the session-LIST dict (registry.all_sessions) and the detail
    dict (registry.parse_any), both providers."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self._flags_snap = config.FLAGS_FILE
        self._augment_dir_snap = config.AUGMENT_DIR
        self._auggie_sessions_snap = config.AUGGIE_SESSIONS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        _AUGGIE_LIST_CACHE.clear()
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        _claude_session(self.sdir, "s_flagged", [])
        _claude_session(self.sdir, "s_clean", [])
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_a.json"), "w") as fh:
            json.dump({"sessionId": "sess_a", "modified": "2026-06-27T05:48:03Z", "chatHistory": []}, fh)

    def tearDown(self):
        if os.path.exists(config.FLAGS_FILE):
            os.unlink(config.FLAGS_FILE)
        config.PROJECTS = self._pdir_snap
        config.FLAGS_FILE = self._flags_snap
        config.AUGMENT_DIR = self._augment_dir_snap
        config.AUGGIE_SESSIONS = self._auggie_sessions_snap
        _AUGGIE_LIST_CACHE.clear()

    def test_list_dict_latest_unresolved_note_wins(self):
        save_flags([
            {"id": 1, "session": "s_flagged", "note": "first", "resolved": False},
            {"id": 2, "session": "s_flagged", "note": "second and latest", "resolved": False},
        ])
        rows = {s["id"]: s for s in all_sessions()}
        self.assertEqual(rows["s_flagged"]["flag_text"], "second and latest")

    def test_list_dict_none_when_no_open_flag(self):
        save_flags([{"id": 1, "session": "s_flagged", "note": "resolved already", "resolved": True}])
        rows = {s["id"]: s for s in all_sessions()}
        self.assertIsNone(rows["s_flagged"]["flag_text"])
        self.assertIsNone(rows["s_clean"]["flag_text"])

    def test_key_always_present_when_no_flags_file(self):
        if os.path.exists(config.FLAGS_FILE):
            os.unlink(config.FLAGS_FILE)
        rows = {s["id"]: s for s in all_sessions()}
        self.assertIn("flag_text", rows["s_clean"])
        self.assertIsNone(rows["s_clean"]["flag_text"])

    def test_detail_dict_matches_list_dict_claude(self):
        save_flags([{"id": 1, "session": "s_flagged", "note": "detail note", "resolved": False}])
        d = parse_any("s_flagged")
        self.assertEqual(d["flag_text"], "detail note")
        d2 = parse_any("s_clean")
        self.assertIsNone(d2["flag_text"])

    def test_detail_and_list_dict_auggie(self):
        save_flags([{"id": 1, "session": "auggie:sess_a", "note": "auggie note", "resolved": False}])
        rows = {s["id"]: s for s in all_sessions()}
        self.assertEqual(rows["auggie:sess_a"]["flag_text"], "auggie note")
        d = parse_any("auggie:sess_a")
        self.assertEqual(d["flag_text"], "auggie note")


class DetailFailCmdTests(unittest.TestCase):
    """fail_cmd on the DETAIL dict (registry.parse_any) -- just landed at the shared
    seam: registry.py:130's setdefault() guarantees the key always exists, and
    Claude's parse_session()/Auggie's parse_auggie() each set it themselves off their
    own whole-transcript scan (providers/claude.py:1380, providers/auggie.py:667),
    the SAME field name and filter (_is_real_bash_error / _auggie_is_real_launch_error)
    the list dict already uses -- so the board and the detail header derive "failing"
    off one field regardless of which view is open."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self._augment_dir_snap = config.AUGMENT_DIR
        self._auggie_sessions_snap = config.AUGGIE_SESSIONS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        _AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        config.PROJECTS = self._pdir_snap
        config.AUGMENT_DIR = self._augment_dir_snap
        config.AUGGIE_SESSIONS = self._auggie_sessions_snap
        _AUGGIE_LIST_CACHE.clear()

    def test_claude_detail_dict_honest_none_when_nothing_failed(self):
        _claude_session(self.sdir, "s_clean", [])
        d = parse_any("s_clean")
        self.assertIn("fail_cmd", d)
        self.assertIsNone(d["fail_cmd"])

    def test_claude_detail_dict_surfaces_the_command_when_something_failed(self):
        _claude_session(self.sdir, "s_fail", [BASH_USE, _bash_result(True)])
        d = parse_any("s_fail")
        self.assertEqual(d["fail_cmd"], "make test")

    def test_claude_detail_dict_matches_list_dict(self):
        """Both the list row and the detail dict derive fail_cmd off the SAME
        whole-transcript scan -- they must never disagree for the same session."""
        _claude_session(self.sdir, "s_fail", [BASH_USE, _bash_result(True)])
        rows = {s["id"]: s for s in all_sessions()}
        d = parse_any("s_fail")
        self.assertEqual(rows["s_fail"]["fail_cmd"], d["fail_cmd"])

    def test_claude_detail_dict_filters_a_framework_refusal_too(self):
        """The noise filter applies on the detail dict's whole-transcript scan just
        as it does on the list dict's tail scan -- a refusal must not surface here
        either."""
        content = "Permission to use Bash has been denied because Claude Code is running in don't ask mode"
        _claude_session(self.sdir, "s_refused", [BASH_USE, _bash_result(True, content=content)])
        d = parse_any("s_refused")
        self.assertIsNone(d["fail_cmd"])

    def test_auggie_detail_dict_honest_none_when_nothing_failed(self):
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_clean.json"), "w") as fh:
            json.dump({"sessionId": "sess_clean", "modified": "2026-06-27T05:48:03Z",
                       "chatHistory": []}, fh)
        d = parse_any("auggie:sess_clean")
        self.assertIn("fail_cmd", d)
        self.assertIsNone(d["fail_cmd"])

    def test_auggie_detail_dict_surfaces_the_command_when_something_failed(self):
        chat = [{"exchange": {"response_nodes": [
                    {"tool_use": {"tool_name": "launch-process", "tool_use_id": "c1",
                                  "input_json": json.dumps({"command": "npm test"})}}]}},
                {"exchange": {"request_nodes": [
                    {"tool_result_node": {"tool_use_id": "c1", "is_error": True}}]}}]
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_fail.json"), "w") as fh:
            json.dump({"sessionId": "sess_fail", "modified": "2026-06-27T05:48:03Z",
                       "chatHistory": chat}, fh)
        d = parse_any("auggie:sess_fail")
        self.assertEqual(d["fail_cmd"], "npm test")

    def test_auggie_detail_dict_matches_list_dict(self):
        chat = [{"exchange": {"response_nodes": [
                    {"tool_use": {"tool_name": "launch-process", "tool_use_id": "c1",
                                  "input_json": json.dumps({"command": "npm test"})}}]}},
                {"exchange": {"request_nodes": [
                    {"tool_result_node": {"tool_use_id": "c1", "is_error": True}}]}}]
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_fail.json"), "w") as fh:
            json.dump({"sessionId": "sess_fail", "modified": "2026-06-27T05:48:03Z",
                       "chatHistory": chat}, fh)
        rows = {s["id"]: s for s in all_sessions()}
        d = parse_any("auggie:sess_fail")
        self.assertEqual(rows["auggie:sess_fail"]["fail_cmd"], d["fail_cmd"])


class TermAttachedTests(unittest.TestCase):
    """detail dict only -- registry._term_attached() over term_vt.PTYS. Never spawns
    a real PTY: PTYS is fully stubbed with plain term_vt.Pty() objects and
    _foreground_is_claude is monkeypatched."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        _claude_session(self.sdir, "s_a", [])
        _claude_session(self.sdir, "s_b", [])
        self._ptys_snap = dict(term_vt.PTYS)
        term_vt.PTYS.clear()

    def tearDown(self):
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys_snap)
        config.PROJECTS = self._pdir_snap

    def test_false_with_no_open_ptys_at_all(self):
        self.assertFalse(parse_any("s_a")["term_attached"])

    def test_true_when_live_pty_and_claude_foreground(self):
        pt = term_vt.Pty(tid="t1")
        pt.session, pt.done = "s_a", False
        term_vt.PTYS[pt.id] = pt
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            self.assertTrue(parse_any("s_a")["term_attached"])

    def test_false_when_pty_open_but_not_claude_foreground(self):
        pt = term_vt.Pty(tid="t1")
        pt.session, pt.done = "s_a", False
        term_vt.PTYS[pt.id] = pt
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=False):
            self.assertFalse(parse_any("s_a")["term_attached"])

    def test_false_when_pty_is_done(self):
        pt = term_vt.Pty(tid="t1")
        pt.session, pt.done = "s_a", True
        term_vt.PTYS[pt.id] = pt
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            self.assertFalse(parse_any("s_a")["term_attached"])

    def test_a_different_sessions_pty_does_not_leak_over(self):
        pt = term_vt.Pty(tid="t1")
        pt.session, pt.done = "s_b", False
        term_vt.PTYS[pt.id] = pt
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            self.assertFalse(parse_any("s_a")["term_attached"])
            self.assertTrue(parse_any("s_b")["term_attached"])

    def test_multiple_ptys_one_attached_one_not(self):
        pt_dead = term_vt.Pty(tid="t1")
        pt_dead.session, pt_dead.done = "s_a", False
        pt_live = term_vt.Pty(tid="t2")
        pt_live.session, pt_live.done = "s_a", False
        term_vt.PTYS[pt_dead.id] = pt_dead
        term_vt.PTYS[pt_live.id] = pt_live

        # only pt_live's fd reports claude in the foreground
        pt_dead.fd, pt_live.fd = -1, -2
        with mock.patch("aitracker.term_vt._foreground_is_claude", side_effect=lambda fd: fd == -2):
            self.assertTrue(parse_any("s_a")["term_attached"], "ANY matching pty being attached is enough")

    def test_never_raises_if_term_vt_import_fails(self):
        """registry._term_attached() must degrade to False, never propagate, if
        term_vt can't even be imported (see its own docstring)."""
        with mock.patch.dict("sys.modules", {"aitracker.term_vt": None}):
            self.assertFalse(parse_any("s_a")["term_attached"])


class PinnedTests(unittest.TestCase):
    """detail dict only -- registry.py:128, both providers, true and false."""

    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self._pins_snap = config.PINS_FILE
        self._augment_dir_snap = config.AUGMENT_DIR
        self._auggie_sessions_snap = config.AUGGIE_SESSIONS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "-tmp-proj")
        os.makedirs(self.sdir)
        _claude_session(self.sdir, "s_a", [])
        _claude_session(self.sdir, "s_b", [])
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        with open(os.path.join(config.AUGGIE_SESSIONS, "sess_a.json"), "w") as fh:
            json.dump({"sessionId": "sess_a", "modified": "2026-06-27T05:48:03Z", "chatHistory": []}, fh)
        _AUGGIE_LIST_CACHE.clear()
        config.PINS_FILE = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(config.PINS_FILE):
            os.unlink(config.PINS_FILE)
        config.PROJECTS = self._pdir_snap
        config.PINS_FILE = self._pins_snap
        config.AUGMENT_DIR = self._augment_dir_snap
        config.AUGGIE_SESSIONS = self._auggie_sessions_snap
        _AUGGIE_LIST_CACHE.clear()

    def test_true_when_pinned_claude(self):
        _save_json(config.PINS_FILE, ["s_a"])
        self.assertTrue(parse_any("s_a")["pinned"])

    def test_false_when_not_pinned_claude(self):
        _save_json(config.PINS_FILE, ["s_a"])
        self.assertFalse(parse_any("s_b")["pinned"])

    def test_true_when_pinned_auggie(self):
        _save_json(config.PINS_FILE, ["auggie:sess_a"])
        self.assertTrue(parse_any("auggie:sess_a")["pinned"])

    def test_false_when_no_pins_file_at_all(self):
        if os.path.exists(config.PINS_FILE):
            os.unlink(config.PINS_FILE)
        self.assertFalse(parse_any("s_a")["pinned"])


class RestartRequiredTests(unittest.TestCase):
    """config.py's RESTART_REQUIRED (~line 196) -- what makes the Config dialog show
    its 'takes effect on restart' note. TERMINAL joined PORT/HOST here per doc 04's
    Config table ("Terminal enabled | toggle | TRACKER_TERMINAL | yes"), the one row
    besides PORT/HOST marked Restart=yes -- because term_gate.py rereads
    config.TERMINAL live on every request, so flipping it without a restart would
    silently half-apply."""

    def test_terminal_key_joins_port_and_host(self):
        self.assertIn("PORT", config.RESTART_REQUIRED)
        self.assertIn("HOST", config.RESTART_REQUIRED)
        self.assertIn("TERMINAL", config.RESTART_REQUIRED)


if __name__ == "__main__":
    unittest.main()
