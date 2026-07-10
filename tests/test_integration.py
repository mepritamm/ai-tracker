#!/usr/bin/env python3
"""End-to-end evals across the seams that unit tests don't reach: the HTTP server,
the page assembly (web/ inlining), cross-source search ranking, the standalone
bundle, and a few pure helpers. Stdlib only."""
import ast
import http.client
import json
import os
import runpy
import tempfile
import threading
import unittest

import aitracker.config as config
from aitracker import server as _server
from aitracker.page import build_page
from aitracker.registry import search_all
from aitracker.overview import build_overview
from aitracker.util import _first_line, _iso_epoch
from aitracker.providers import auggie as _auggie
from aitracker.providers import claude as _claude

_PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE", "TASKS_DIR")


def _snap():
    return {k: getattr(config, k) for k in _PATHS}


def _restore(s):
    for k, v in s.items():
        setattr(config, k, v)
    _auggie._AUGGIE_LIST_CACHE.clear()
    _claude._META_CACHE.clear()


def _empty_env():
    """Repoint every data path at empty temp dirs so listings are deterministic."""
    config.PROJECTS = tempfile.mkdtemp()
    config.AUGMENT_DIR = tempfile.mkdtemp()
    config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
    os.makedirs(config.AUGGIE_SESSIONS)
    _auggie._AUGGIE_LIST_CACHE.clear()
    _claude._META_CACHE.clear()


def _write_auggie(sid, title, req="the request", resp="the reply"):
    json.dump({"sessionId": sid, "modified": "2026-06-27T05:48:03Z", "customTitle": title,
               "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                                "exchange": {"request_message": req, "response_text": resp}}]},
              open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))


class TestBuildPage(unittest.TestCase):
    """page.py assembles web/index.html + app.css + app.js into one document."""

    def test_inlines_web_assets(self):
        p = build_page()
        self.assertTrue(p.lstrip().lower().startswith("<!doctype"))
        self.assertNotIn("__CSS__", p)          # placeholders fully substituted
        self.assertNotIn("__JS__", p)
        self.assertIn(".side{", p)              # a CSS rule made it in
        self.assertIn("function render", p)     # the JS made it in
        self.assertIn("AI Session Tracker", p)
        self.assertIn("rel=icon", p)            # the favicon


class TestSearchAllRanking(unittest.TestCase):
    """registry.search_all merges providers and ranks title matches first — across sources."""

    def setUp(self):
        self.snap = _snap()
        _empty_env()
        os.makedirs(os.path.join(config.AUGMENT_DIR, "task-storage", "tasks"))
        open(os.path.join(config.AUGMENT_DIR, "settings.json"), "w").write('{"indexingAllowDirs":["/x"]}')
        _write_auggie("s", "Deploy the widget", req="deploy the widget please", resp="on it")

    def tearDown(self):
        _restore(self.snap)

    def test_title_match_ranks_first(self):
        r = search_all("deploy the widget")
        self.assertTrue(r, "auggie session must be found")
        self.assertEqual(r[0]["id"], "auggie:s")
        self.assertTrue(r[0]["titleMatch"])

    def test_no_match_is_empty(self):
        self.assertEqual(search_all("zzznotfoundzzz"), [])


class TestServerEndToEnd(unittest.TestCase):
    """Boot the real server on an ephemeral port and exercise the routes."""

    def setUp(self):
        self.snap = _snap()
        _empty_env()
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        _restore(self.snap)

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def test_serves_page(self):
        st, body = self._get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"<!doctype", body.lower())
        self.assertIn(b"AI Session Tracker", body)

    def test_api_list_is_json(self):
        st, body = self._get("/api/list")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body), [])          # empty env -> no sessions

    def test_api_list_includes_auggie(self):
        os.makedirs(os.path.join(config.AUGMENT_DIR, "task-storage", "tasks"))
        open(os.path.join(config.AUGMENT_DIR, "settings.json"), "w").write('{"indexingAllowDirs":["/x"]}')
        _write_auggie("s", "Hello world")
        st, body = self._get("/api/list")
        self.assertEqual(st, 200)
        ids = [s["id"] for s in json.loads(body)]
        self.assertIn("auggie:s", ids)

    def test_api_session_missing_is_404(self):
        st, _ = self._get("/api/session?id=no-such-session-xyz")
        self.assertEqual(st, 404)

    def test_api_search_is_json(self):
        st, body = self._get("/api/search?q=zzznotfound")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body), [])

    def test_unknown_route_404(self):
        st, _ = self._get("/api/nope")
        self.assertEqual(st, 404)


class TestOverviewSynthesis(unittest.TestCase):
    """build_overview turns the derived counts into the Goal / Now / So-far line."""

    def test_goal_now_sofar(self):
        d = {"meta": {"cwd": "/x/proj", "gitBranch": "main"},
             "counts": {"done": 1, "todos": 2, "created": 1, "edited": 0, "read": 0,
                        "commits": 1, "tests": 0, "tests_failed": 0, "errors": 0,
                        "agents": 0, "searches": 0}}
        todos = [{"content": "a", "status": "completed"}, {"content": "b", "status": "in_progress"}]
        files = [{"path": "/x/proj/a.py", "created": True}]
        cmds = [{"kind": "commit", "ok": True}]
        ov = build_overview(d, todos, files, cmds, [{"msg": "init"}], [], [],
                            [{"text": "build the thing"}], [{"text": "starting"}], [],
                            5, "2026-06-22T10:00:00Z", "2026-06-22T10:05:00Z")
        self.assertEqual(ov["goal"], "build the thing")
        self.assertEqual(ov["now"], "▶ b")   # the in-progress todo
        self.assertIn("proj", ov["where"])
        self.assertTrue(ov["now"].startswith("▶"))


class TestHelpers(unittest.TestCase):
    def test_first_line(self):
        self.assertEqual(_first_line("first line\nsecond"), "first line")
        self.assertEqual(_first_line("\n\n  hello  \nx")[:5], "hello")
        self.assertEqual(_first_line(""), "")

    def test_iso_epoch(self):
        self.assertGreater(_iso_epoch("2026-06-27T05:48:03Z"), 0)
        self.assertEqual(_iso_epoch(""), 0.0)
        self.assertEqual(_iso_epoch(None), 0.0)
        # later timestamp -> larger epoch
        self.assertGreater(_iso_epoch("2026-06-27T06:00:00Z"), _iso_epoch("2026-06-27T05:00:00Z"))


class TestBundle(unittest.TestCase):
    """`make bundle` produces a valid, standalone single-file build."""

    def test_bundle_builds_and_is_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundler = os.path.join(root, "scripts", "bundle.py")
        if not os.path.exists(bundler):
            self.skipTest("no bundler")
        runpy.run_path(bundler, run_name="__main__")
        src = open(os.path.join(root, "dist", "tracker.py")).read()
        ast.parse(src)                          # syntactically valid
        self.assertIn("PAGE = ", src)           # page inlined
        self.assertIn("def main(", src)
        self.assertNotIn("from .", src)         # no leftover intra-package imports


if __name__ == "__main__":
    unittest.main()
