"""Coverage for the model-update nudge feature:

  * util.real_model / model_version / model_label -- the pure id-parsing vocabulary
    shared by providers/claude.py and registry.py.
  * providers/claude.py's DETAIL parser (parse_session) skipping the "<synthetic>"
    sentinel a client-side API error stamps on an assistant message, same as the
    list-level tail scan already did.
  * registry.parse_any()'s meta.model_update -- present only when a strictly newer
    same-family model exists and the user hasn't already chosen to keep the current one
    (store.save_model_keep), honest None/no-crash for a provider with no model at all.
  * POST /api/model-keep -- the "keep current" persistence route.

Stdlib unittest only.
"""
import http.client
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import config, server as _server
from aitracker.providers import auggie as _auggie
from aitracker.providers import claude as _claude
from aitracker.providers.claude import parse_session
from aitracker.util import real_model, model_version, model_label
from aitracker import registry
from aitracker import store


# =============================================================================
# 1. util.py: real_model / model_version / model_label
# =============================================================================

class ModelHelpersTests(unittest.TestCase):
    def test_real_model(self):
        cases = [
            ("claude-opus-5", "claude-opus-5"),
            ("<synthetic>", ""),
            ("", ""),
            (None, ""),
            (123, ""),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(real_model(raw), expected)

    def test_model_version(self):
        cases = [
            ("claude-opus-5-5", ("opus", (5, 5))),
            ("claude-opus-5", ("opus", (5,))),
            ("claude-haiku-4-5-20251001", ("haiku", (4, 5))),   # date suffix stripped
            ("claude-haiku-4-5", ("haiku", (4, 5))),
            ("claude-opus-4-8", ("opus", (4, 8))),
            ("claude-sonnet-4-6", ("sonnet", (4, 6))),
            ("claude-opus-4-6", ("opus", (4, 6))),
            ("claude-opus-5[1m]", ("opus", (5,))),              # [1m] tag stripped
            ("claude-3-5-sonnet-20241022", ("sonnet", (3, 5))), # legacy form
            ("claude-fable-5-1", ("fable", (5, 1))),
            ("sonnet", None),     # bare alias, no version
            ("opus", None),
            ("haiku", None),
            ("<synthetic>", None),
            ("", None),
            (None, None),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(model_version(raw), expected)

    def test_model_version_ordering(self):
        self.assertLess(model_version("claude-opus-5"), model_version("claude-opus-5-5"))

    def test_model_label(self):
        cases = [
            ("claude-opus-5-5", "Opus 5.5"),
            ("claude-opus-5", "Opus 5"),
            ("claude-haiku-4-5-20251001", "Haiku 4.5"),
            ("claude-opus-5[1m]", "Opus 5 (1M)"),
            ("opus", "Opus"),
            ("sonnet", "Sonnet"),
            ("haiku", "Haiku"),
            ("", ""),
            ("<synthetic>", ""),
            ("some-unknown-id", "some-unknown-id"),   # unchanged
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(model_label(raw), expected)


# =============================================================================
# 2. providers/claude.py detail parser: synthetic never overwrites a real model
# =============================================================================

class _ProjectsDirCase(unittest.TestCase):
    def setUp(self):
        self._pdir_snap = config.PROJECTS
        self.pdir = tempfile.mkdtemp()
        config.PROJECTS = self.pdir
        self.sdir = os.path.join(self.pdir, "proj")
        os.makedirs(self.sdir)

    def tearDown(self):
        config.PROJECTS = self._pdir_snap

    def _write(self, sid, rows):
        path = os.path.join(self.sdir, sid + ".jsonl")
        with open(path, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path


class ClaudeDetailSyntheticSkipTests(_ProjectsDirCase):
    def test_synthetic_tail_does_not_overwrite_the_last_real_model(self):
        sid = "s_synth_tail"
        path = self._write(sid, [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "message": {"model": "claude-opus-5",
             "content": [{"type": "text", "text": "working on it"}]}},
            # a client-side API error (rate limit, etc.) stamps this sentinel model --
            # must not clobber the real "claude-opus-5" recorded just above.
            {"type": "assistant", "message": {"model": "<synthetic>",
             "content": [{"type": "text", "text": "Error: rate limited"}]}},
        ])
        d = parse_session(path)
        self.assertEqual(d["meta"]["model"], "claude-opus-5")
        # model_label/model_update are added by registry.parse_any(), NOT parse_session
        # itself -- confirm parse_session's own meta has no such key yet (the seam
        # boundary between the provider and the shared registry seam).
        self.assertNotIn("model_label", d["meta"])


# =============================================================================
# 3. registry.parse_any(): meta.model_update
# =============================================================================

class _RegistryCase(unittest.TestCase):
    """Overrides every app-owned path parse_any() might touch with a fresh temp
    location, so this never reads the real machine's own sessions/flags/pins/etc."""

    _PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE",
              "PINS_FILE", "NOTES_FILE", "FORKS_FILE", "MODEL_KEEP_FILE", "TASKS_DIR")

    def setUp(self):
        self._snap = {k: getattr(config, k) for k in self._PATHS}
        config.PROJECTS = tempfile.mkdtemp()
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.PINS_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.FORKS_FILE = tempfile.mktemp(suffix=".json")
        config.MODEL_KEEP_FILE = tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        _claude._META_CACHE.clear()
        _auggie._AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        for k, v in self._snap.items():
            setattr(config, k, v)
        _claude._META_CACHE.clear()
        _auggie._AUGGIE_LIST_CACHE.clear()

    def _write_claude(self, sid, model):
        d = os.path.join(config.PROJECTS, "proj")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, sid + ".jsonl")
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": "/x",
                                  "message": {"role": "user", "content": "go"}}) + "\n")
            fh.write(json.dumps({"type": "assistant", "message": {"model": model,
                                  "content": [{"type": "text", "text": "ok"}]}}) + "\n")
        return sid

    def _write_auggie_no_model(self, sid):
        d = {"sessionId": sid, "modified": "2026-06-27T05:48:03Z", "customTitle": "no model",
             "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                               "exchange": {"request_message": "hi", "response_text": "hello"}}]}
        json.dump(d, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        return "auggie:" + sid


class ParseAnyModelUpdateTests(_RegistryCase):
    def test_update_present_when_a_strictly_newer_same_family_model_exists(self):
        sid = self._write_claude("s_update", "claude-opus-5")
        with mock.patch.object(registry, "newest_models", return_value={"opus": "claude-opus-5-5"}):
            d = registry.parse_any(sid)
        self.assertEqual(d["meta"]["model_label"], "Opus 5")
        self.assertEqual(d["meta"]["model_update"],
                          {"id": "claude-opus-5-5", "label": "Opus 5.5", "current_label": "Opus 5"})

    def test_update_hidden_once_kept_against_that_exact_newest_id(self):
        sid = self._write_claude("s_kept", "claude-opus-5")
        store.save_model_keep(sid, "claude-opus-5-5")
        with mock.patch.object(registry, "newest_models", return_value={"opus": "claude-opus-5-5"}):
            d = registry.parse_any(sid)
        self.assertIsNone(d["meta"]["model_update"])

    def test_update_resurfaces_once_an_even_newer_model_lands(self):
        """The keep is recorded against a SPECIFIC newest id -- an even newer one must
        still nudge, not stay silently hidden forever."""
        sid = self._write_claude("s_kept_again", "claude-opus-5")
        store.save_model_keep(sid, "claude-opus-5-5")
        with mock.patch.object(registry, "newest_models", return_value={"opus": "claude-opus-6"}):
            d = registry.parse_any(sid)
        self.assertEqual(d["meta"]["model_update"]["id"], "claude-opus-6")

    def test_no_update_when_current_is_already_newest(self):
        sid = self._write_claude("s_already_newest", "claude-opus-5-5")
        with mock.patch.object(registry, "newest_models", return_value={"opus": "claude-opus-5-5"}):
            d = registry.parse_any(sid)
        self.assertIsNone(d["meta"]["model_update"])

    def test_auggie_session_with_no_model_never_crashes_and_reports_none(self):
        sid = self._write_auggie_no_model("s_no_model")
        with mock.patch.object(registry, "newest_models", return_value={"opus": "claude-opus-5-5"}):
            d = registry.parse_any(sid)
        self.assertIsNotNone(d, "parse_any must not fail on an Auggie session with no model")
        self.assertEqual(d["meta"].get("model_label"), "")
        self.assertIsNone(d["meta"]["model_update"])


# =============================================================================
# 4. POST /api/model-keep
# =============================================================================

class _ServerCase(unittest.TestCase):
    _PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE",
              "PINS_FILE", "NOTES_FILE", "FORKS_FILE", "MODEL_KEEP_FILE", "TASKS_DIR",
              "CONFIG_FILE")

    def setUp(self):
        self._snap = {k: getattr(config, k) for k in self._PATHS}
        self._auth_snap = config.AUTH
        config.PROJECTS = tempfile.mkdtemp()
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
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


class ApiModelKeepRouteTests(_ServerCase):
    def test_happy_path_records_the_keep_and_reports_ok(self):
        st, j = self._post("/api/model-keep", {"id": "sess-1", "model": "claude-opus-5-5"})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True})
        self.assertEqual(store.load_model_keep(), {"sess-1": "claude-opus-5-5"})

    def test_missing_id_is_rejected_with_400(self):
        st, j = self._post("/api/model-keep", {"model": "claude-opus-5-5"})
        self.assertEqual(st, 400)
        self.assertIn("error", j)
        self.assertEqual(store.load_model_keep(), {})

    def test_missing_model_is_rejected_with_400(self):
        st, j = self._post("/api/model-keep", {"id": "sess-1"})
        self.assertEqual(st, 400)
        self.assertIn("error", j)

    def test_empty_string_values_are_rejected_with_400(self):
        st, j = self._post("/api/model-keep", {"id": "", "model": "claude-opus-5-5"})
        self.assertEqual(st, 400)
        st, j = self._post("/api/model-keep", {"id": "sess-1", "model": ""})
        self.assertEqual(st, 400)

    def test_non_string_values_are_rejected_with_400(self):
        st, j = self._post("/api/model-keep", {"id": 123, "model": "claude-opus-5-5"})
        self.assertEqual(st, 400)


if __name__ == "__main__":
    unittest.main()
