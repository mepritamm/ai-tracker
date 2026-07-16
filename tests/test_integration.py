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


class TestPortFallback(unittest.TestCase):
    """bind() skips a busy port and takes the next free one."""

    def test_bind_skips_busy_port(self):
        busy = _server.Server(("127.0.0.1", 0), _server.Handler)   # occupy an ephemeral port
        p = busy.server_address[1]
        try:
            srv = _server.bind("127.0.0.1", p, tries=10)
            try:
                self.assertNotEqual(srv.server_address[1], p)       # didn't reuse the busy port
                self.assertGreater(srv.server_address[1], p)        # took a later one
            finally:
                srv.server_close()
        finally:
            busy.server_close()


class TestDecisions(unittest.TestCase):
    """AskUserQuestion (Claude) + ask-user (Auggie) surface as `decisions`, open ones pinned first."""

    def setUp(self):
        self.snap = _snap(); _empty_env()

    def tearDown(self):
        _restore(self.snap)

    def test_claude_decisions(self):
        d = os.path.join(config.PROJECTS, "proj"); os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "s1.jsonl")
        lines = [
            {"type": "assistant", "timestamp": "2026-07-16T10:00:00Z", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "a1", "name": "AskUserQuestion", "input": {"questions": [
                    {"question": "Ship it now?", "header": "Scope",
                     "options": [{"label": "Yes"}, {"label": "No"}]}]}}]}},
            {"type": "user", "timestamp": "2026-07-16T10:01:00Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "a1",
                 "content": 'Your questions have been answered: "Ship it now?"="Yes"'}]}},
            {"type": "assistant", "timestamp": "2026-07-16T10:02:00Z", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "a2", "name": "AskUserQuestion", "input": {"questions": [
                    {"question": "Which DB?", "header": "DB",
                     "options": [{"label": "pg"}, {"label": "sqlite"}]}]}}]}},
        ]
        open(path, "w").write("\n".join(json.dumps(x) for x in lines))
        dec = _claude.parse_session(path)["decisions"]
        self.assertEqual(len(dec), 2)
        self.assertTrue(dec[0]["open"])                                  # open pinned first
        self.assertEqual(dec[0]["questions"][0]["header"], "DB")
        self.assertEqual(dec[0]["questions"][0]["options"], ["pg", "sqlite"])
        decided = next(x for x in dec if not x["open"])
        self.assertIn("Yes", decided["answer"])
        self.assertFalse(decided["answer"].startswith("Your questions"))  # prefix stripped

    def test_auggie_decisions(self):
        sid = "au1"
        doc = {"sessionId": sid, "modified": "2026-07-16T10:00:00Z", "chatHistory": [
            {"finishedAt": "2026-07-16T10:00:00Z", "exchange": {"request_message": "go", "response_nodes": [
                {"tool_use": {"tool_use_id": "q1", "tool_name": "ask-user",
                              "input_json": json.dumps({"question": "Proceed?",
                                                        "suggested_responses": ["Yes", "No"]})}}]}},
            {"finishedAt": "2026-07-16T10:01:00Z", "exchange": {"request_message": "", "response_nodes": [],
                "request_nodes": [{"tool_result_node": {"tool_use_id": "q1",
                                                        "content": "User responded: Yes, go ahead"}}]}},
        ]}
        json.dump(doc, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        dec = _auggie.parse_auggie(sid)["decisions"]
        self.assertEqual(len(dec), 1)
        self.assertFalse(dec[0]["open"])
        self.assertEqual(dec[0]["questions"][0]["options"], ["Yes", "No"])
        self.assertIn("Yes", dec[0]["answer"])
        self.assertNotIn("User responded", dec[0]["answer"])             # prefix stripped


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


def _write_claude(sid, n_replies):
    """A Claude session under config.PROJECTS with n_replies narration entries."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    lines = [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}]
    for k in range(n_replies):
        lines.append({"type": "assistant", "timestamp": "2026-06-22T10:00:%02dZ" % (k % 60),
                      "message": {"content": [{"type": "text", "text": "reply number %d" % k}]}})
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


class TestNarrationPagination(unittest.TestCase):
    """The route pages narration: /api/session ships one page + a total; the full
    tail is served on demand by /api/narration. History is unbounded end-to-end."""

    def setUp(self):
        self.snap = _snap()
        _empty_env()
        _write_claude("spage", 200)
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        _restore(self.snap)

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse(); body = r.read(); c.close()
        return r.status, json.loads(body)

    def test_session_ships_one_page_and_total(self):
        st, d = self._get("/api/session?id=spage")
        self.assertEqual(st, 200)
        self.assertEqual(len(d["narrative"]), 60)              # NARR_PAGE, not 200
        self.assertEqual(d["narrative_total"], 200)
        self.assertEqual(d["narrative"][0]["text"], "reply number 199")   # newest first

    def test_narration_serves_the_tail(self):
        st, j = self._get("/api/narration?id=spage&offset=60&limit=60")
        self.assertEqual(st, 200)
        self.assertEqual(j["total"], 200)
        self.assertEqual(j["offset"], 60)
        self.assertEqual(len(j["items"]), 60)
        self.assertEqual(j["items"][0]["text"], "reply number 139")       # 200-1-60

    def test_pages_tile_to_cover_everything(self):
        seen = []
        for off in range(0, 200, 60):
            _, j = self._get("/api/narration?id=spage&offset=%d&limit=60" % off)
            seen += [it["text"] for it in j["items"]]
        self.assertEqual(len(seen), 200)                       # nothing dropped
        self.assertEqual(len(set(seen)), 200)                  # nothing duplicated

    def test_offset_past_end_is_empty(self):
        _, j = self._get("/api/narration?id=spage&offset=999&limit=60")
        self.assertEqual(j["items"], [])
        self.assertEqual(j["total"], 200)

    def test_narration_missing_session_404(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/narration?id=nope-xyz")
        r = c.getresponse(); r.read(); c.close()
        self.assertEqual(r.status, 404)


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
