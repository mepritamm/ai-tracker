"""Coverage for the rename-sync feature:

  * server._sanitize_rename_text -- collapses control bytes to single spaces.
  * server._sync_title_to_claude / POST /api/title -- a tracker rename best-effort syncs
    into the REAL Claude session by injecting `/rename <title>` into an attached
    terminal, via registry._attached_pty (tty lookup + foreground-Claude check) and
    term_vt.inject (the pty write itself) -- reused, not reimplemented. Response gains
    a `synced` bool; a successful sync is remembered in store.save_title_sync so
    registry.parse_any() can report meta.title_local_only honestly.
  * registry.parse_any()'s meta.title_claude / meta.title_local_only.

Stdlib unittest only.
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from aitracker import config, server as _server
from aitracker import registry
from aitracker import store


# =============================================================================
# 1. server._sanitize_rename_text
# =============================================================================

class SanitizeRenameTextTests(unittest.TestCase):
    def test_collapses_control_chars_to_single_space_and_strips(self):
        cases = [
            ("hello world", "hello world"),
            ("hello\nworld", "hello world"),
            ("hello\r\tworld", "hello world"),          # a RUN of control chars -> ONE space
            ("  hello world  ", "hello world"),
            ("a\x00b\x1fc\x7fd", "a b c d"),
            ("a\x85b\u2028c\u2029d", "a b c d"),        # unicode line/paragraph separators too
            ("\n\nleading and trailing\r\n", "leading and trailing"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_server._sanitize_rename_text(raw), expected)


# =============================================================================
# 2. POST /api/title -- rename sync
# =============================================================================

class _ServerCase(unittest.TestCase):
    _PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE",
              "TITLE_SYNC_FILE", "PINS_FILE", "NOTES_FILE", "FORKS_FILE", "MODEL_KEEP_FILE",
              "TASKS_DIR", "CONFIG_FILE")

    def setUp(self):
        self._snap = {k: getattr(config, k) for k in self._PATHS}
        self._auth_snap = config.AUTH
        config.PROJECTS = tempfile.mkdtemp()
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.TITLE_SYNC_FILE = tempfile.mktemp(suffix=".json")
        config.PINS_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        config.MODEL_KEEP_FILE = tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        config.CONFIG_FILE = tempfile.mktemp(suffix=".json")
        config.AUTH = ""
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.addCleanup(self.srv.server_close)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._snap.items():
            setattr(config, k, v)
        config.AUTH = self._auth_snap

    def _post(self, path, payload):
        body = json.dumps(payload).encode()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=body,
                   headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        r = c.getresponse()
        resp = r.read()
        c.close()
        return r.status, json.loads(resp)


class ApiTitleSyncTests(_ServerCase):
    def _fake_inject_ok(self):
        def fn(handler, parsed, body):
            self._inject_calls.append(body)
            handler._json({"ok": True, "quiescent": True, "cr_attempts": 1, "submitted": True})
        return fn

    def setUp(self):
        super().setUp()
        self._inject_calls = []
        self._term_vt = sys.modules["aitracker.term_vt"]

    def test_attached_injects_rename_and_records_sync(self):
        pty = SimpleNamespace(id="tty-1")
        with mock.patch.object(_server, "_attached_pty", return_value=pty), \
             mock.patch.object(self._term_vt, "inject", side_effect=self._fake_inject_ok()):
            st, j = self._post("/api/title", {"session": "s1", "title": "argocd-alerts"})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "synced": True})
        self.assertEqual(len(self._inject_calls), 1)
        call = self._inject_calls[0]
        self.assertEqual(call["tty"], "tty-1")
        self.assertEqual(call["text"], "/rename argocd-alerts")
        self.assertTrue(call["submit"])
        self.assertTrue(call["clear_first"])
        self.assertEqual(store.load_titles(), {"s1": "argocd-alerts"})
        self.assertEqual(store.load_title_sync(), {"s1": "argocd-alerts"})

    def test_not_attached_reports_unsynced_and_never_injects(self):
        with mock.patch.object(_server, "_attached_pty", return_value=None), \
             mock.patch.object(self._term_vt, "inject", side_effect=self._fake_inject_ok()):
            st, j = self._post("/api/title", {"session": "s2", "title": "renamed"})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "synced": False})
        self.assertEqual(self._inject_calls, [])
        self.assertEqual(store.load_titles(), {"s2": "renamed"})
        self.assertEqual(store.load_title_sync(), {})

    def test_inject_raising_never_500s_and_reports_unsynced(self):
        pty = SimpleNamespace(id="tty-1")
        with mock.patch.object(_server, "_attached_pty", return_value=pty), \
             mock.patch.object(self._term_vt, "inject", side_effect=RuntimeError("boom")):
            st, j = self._post("/api/title", {"session": "s3", "title": "renamed"})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "synced": False})
        self.assertEqual(store.load_title_sync(), {})

    def test_title_with_newline_is_sanitized_before_injection(self):
        pty = SimpleNamespace(id="tty-1")
        with mock.patch.object(_server, "_attached_pty", return_value=pty), \
             mock.patch.object(self._term_vt, "inject", side_effect=self._fake_inject_ok()):
            st, j = self._post("/api/title", {"session": "s4", "title": "hello\nworld\r\tfoo"})
        self.assertEqual(st, 200)
        self.assertEqual(j["synced"], True)
        self.assertEqual(self._inject_calls[0]["text"], "/rename hello world foo")

    def test_empty_title_clears_override_and_drops_sync_never_injects(self):
        store._save_json(config.TITLES_FILE, {"s5": "old title"})
        store._save_json(config.TITLE_SYNC_FILE, {"s5": "old title"})
        with mock.patch.object(_server, "_attached_pty", return_value=SimpleNamespace(id="tty-1")), \
             mock.patch.object(self._term_vt, "inject", side_effect=self._fake_inject_ok()):
            st, j = self._post("/api/title", {"session": "s5", "title": ""})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "synced": False})
        self.assertEqual(self._inject_calls, [])
        self.assertEqual(store.load_titles(), {})
        self.assertEqual(store.load_title_sync(), {})


# =============================================================================
# 3. registry.parse_any(): meta.title_claude / meta.title_local_only
# =============================================================================

class _RegistryCase(unittest.TestCase):
    _PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE",
              "TITLE_SYNC_FILE", "PINS_FILE", "NOTES_FILE", "FORKS_FILE", "MODEL_KEEP_FILE",
              "TASKS_DIR")

    def setUp(self):
        self._snap = {k: getattr(config, k) for k in self._PATHS}
        config.PROJECTS = tempfile.mkdtemp()
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.TITLE_SYNC_FILE = tempfile.mktemp(suffix=".json")
        config.PINS_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        config.MODEL_KEEP_FILE = tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()

    def tearDown(self):
        for k, v in self._snap.items():
            setattr(config, k, v)

    def _write_claude(self, sid, custom_title=None):
        d = os.path.join(config.PROJECTS, "proj")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + ".jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": "/x",
                                  "message": {"role": "user", "content": "go"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5",
                                  "content": [{"type": "text", "text": "ok"}]}}) + "\n")
            if custom_title is not None:
                fh.write(json.dumps({"type": "custom-title", "customTitle": custom_title}) + "\n")
        return sid

    def _write_auggie(self, sid):
        d = {"sessionId": sid, "modified": "2026-06-27T05:48:03Z", "customTitle": "auggie's own name",
             "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                               "exchange": {"request_message": "hi", "response_text": "hello"}}]}
        json.dump(d, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        return "auggie:" + sid


class TitleClaudeAndLocalOnlyTests(_RegistryCase):
    def test_no_override_reports_false_and_claudes_own_name(self):
        sid = self._write_claude("s_no_override", custom_title="claude's name")
        d = registry.parse_any(sid)
        self.assertEqual(d["meta"]["title_claude"], "claude's name")
        self.assertFalse(d["meta"]["title_local_only"])

    def test_override_equal_to_claudes_name_reports_false(self):
        sid = self._write_claude("s_equal", custom_title="same-name")
        store._save_json(config.TITLES_FILE, {sid: "same-name"})
        d = registry.parse_any(sid)
        self.assertFalse(d["meta"]["title_local_only"])

    def test_override_differs_and_unsynced_reports_true(self):
        sid = self._write_claude("s_differs", custom_title="claude's name")
        store._save_json(config.TITLES_FILE, {sid: "my override"})
        d = registry.parse_any(sid)
        self.assertTrue(d["meta"]["title_local_only"])

    def test_override_differs_but_synced_reports_false(self):
        sid = self._write_claude("s_synced", custom_title="claude's name")
        store._save_json(config.TITLES_FILE, {sid: "my override"})
        store._save_json(config.TITLE_SYNC_FILE, {sid: "my override"})
        d = registry.parse_any(sid)
        self.assertFalse(d["meta"]["title_local_only"])

    def test_auggie_session_with_override_reports_true_and_empty_title_claude(self):
        sid = self._write_auggie("s_auggie")
        store._save_json(config.TITLES_FILE, {sid: "my override"})
        d = registry.parse_any(sid)
        self.assertTrue(d["meta"]["title_local_only"])
        self.assertEqual(d["meta"]["title_claude"], "")

    def test_auggie_session_with_no_override_reports_false(self):
        sid = self._write_auggie("s_auggie_no_override")
        d = registry.parse_any(sid)
        self.assertFalse(d["meta"]["title_local_only"])


if __name__ == "__main__":
    unittest.main()
