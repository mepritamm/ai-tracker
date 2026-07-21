#!/usr/bin/env python3
"""End-to-end evals across the seams that unit tests don't reach: the HTTP server,
the page assembly (web/ inlining), cross-source search ranking, the standalone
bundle, and a few pure helpers. Stdlib only."""
import ast
import base64
import http.client
import json
import sys
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

_PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE", "PINS_FILE", "TASKS_DIR", "NOTES_FILE")


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
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
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
        # installable-on-phone bits (Add to Home Screen -> fullscreen)
        self.assertIn("apple-mobile-web-app-capable", p)
        self.assertIn("rel=apple-touch-icon", p)
        self.assertIn("rel=manifest", p)
        self.assertIn("max-width:600px", p)    # the phone responsive block is baked in
        self.assertIn("min-width:601px", p)    # the tablet master-detail block is baked in
        self.assertIn(".remote .addflag", p)   # flag button hidden for remote (non-localhost) viewers
        self.assertIn("notes_list", p)          # notes stack panel baked into page
        # mobile: Sessions is a left slide-in drawer (hamburger + scrim + off-canvas rule)
        self.assertIn("toggleDrawer", p)
        self.assertIn("id=scrim", p)
        self.assertIn(".app.draweropen .side", p)
        self.assertIn("addNote", p)             # notes JS function present
        # notes must be addable from mobile/tablet (remote host): the Add-note button uses its own
        # `addnote` class, so the `.remote .addflag{display:none}` rule (local-only flagging) never
        # hides it. Regression guard for the mobile "can't add a note" bug.
        self.assertIn("class=addnote", p)                   # note button has its own class
        self.assertNotIn(".remote .addnote", p)             # …and is NOT hidden on remote
        self.assertIn(".remote .addflag", p)                # flagging stays local-only (unchanged)
        # touch devices have no :hover — pin/rename (hover-only) must stay usable on the phone/tablet drawer
        self.assertIn("@media(hover:none)", p)


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

    def _post(self, path, payload):
        body = json.dumps(payload).encode()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=body, headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        r = c.getresponse()
        resp = r.read()
        c.close()
        return r.status, json.loads(resp)

    def test_serves_page(self):
        st, body = self._get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"<!doctype", body.lower())
        self.assertIn(b"AI Session Tracker", body)

    def test_page_is_not_cached(self):
        # the page is rebuilt at each restart; without no-store a plain reload serves the
        # stale cached doc and new UI never shows. Assert the freshness header is present.
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        cc = r.getheader("Cache-Control")
        c.close()
        self.assertEqual(cc, "no-store")

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

    def test_notes_add_and_delete(self):
        # add two notes
        st, j = self._post("/api/notes", {"session": "sess-x", "text": "first plan"})
        self.assertEqual(st, 200)
        self.assertEqual(j["notes"], ["first plan"])

        st, j = self._post("/api/notes", {"session": "sess-x", "text": "second plan"})
        self.assertEqual(st, 200)
        self.assertEqual(j["notes"], ["first plan", "second plan"])

        # delete index 0 (first note)
        st, j = self._post("/api/notes/delete", {"session": "sess-x", "index": 0})
        self.assertEqual(st, 200)
        self.assertEqual(j["notes"], ["second plan"])

        # delete the last note — stack cleaned up
        st, j = self._post("/api/notes/delete", {"session": "sess-x", "index": 0})
        self.assertEqual(st, 200)
        self.assertEqual(j["notes"], [])

    def test_notes_empty_text_rejected(self):
        st, j = self._post("/api/notes", {"session": "sess-y", "text": "   "})
        self.assertEqual(st, 400)

    def test_notes_missing_session_rejected(self):
        st, j = self._post("/api/notes", {"text": "oops"})
        self.assertEqual(st, 400)

    def test_notes_invalid_index_is_noop(self):
        self._post("/api/notes", {"session": "sess-z", "text": "note"})
        # out-of-range index: no crash, note still there
        st, j = self._post("/api/notes/delete", {"session": "sess-z", "index": 99})
        self.assertEqual(st, 200)
        self.assertEqual(j["notes"], ["note"])


class TestBasicAuth(unittest.TestCase):
    """config.AUTH gates every route with HTTP Basic Auth; empty (default) lets all through."""

    def setUp(self):
        self.snap = _snap()
        _empty_env()
        self._auth0 = config.AUTH
        config.AUTH = "alice:s3cret"          # read live by the Handler
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        config.AUTH = self._auth0
        self.srv.shutdown()
        self.srv.server_close()
        _restore(self.snap)

    def _get(self, path, cred=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = {}
        if cred is not None:
            hdr["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
        c.request("GET", path, headers=hdr)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status, r.getheader("WWW-Authenticate")

    def test_no_credentials_401(self):
        st, wa = self._get("/")
        self.assertEqual(st, 401)
        self.assertIn("Basic", wa or "")        # prompts the browser for credentials

    def test_wrong_credentials_401(self):
        self.assertEqual(self._get("/api/list", "alice:wrong")[0], 401)

    def test_correct_credentials_200(self):
        self.assertEqual(self._get("/api/list", "alice:s3cret")[0], 200)

    def test_default_off_lets_all_through(self):
        config.AUTH = ""                        # simulate no TRACKER_AUTH set (the default)
        self.assertEqual(self._get("/api/list")[0], 200)   # no creds, still served

    def _raw(self, method, path, auth):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = {"Authorization": auth} if auth is not None else {}
        if method == "POST":
            hdr["Content-Type"] = "application/json"
            c.request("POST", path, body="{}", headers=hdr)
        else:
            c.request(method, path, headers=hdr)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_post_route_also_requires_auth(self):
        # the guard is on do_POST too, not just do_GET — a mutation must not slip through
        self.assertEqual(self._raw("POST", "/api/flags", None), 401)

    def test_malformed_or_non_basic_header_401(self):
        # a bad Authorization header must 401 cleanly (no 500), exercising the decode try/except
        self.assertEqual(self._raw("GET", "/api/list", "Basic not_valid_base64!!"), 401)
        self.assertEqual(self._raw("GET", "/api/list", "Bearer sometoken"), 401)


class TestHostEnv(unittest.TestCase):
    """cli honors HOST (default 127.0.0.1) and passes it to run() — default-localhost guards
    against accidentally exposing the server; the env is what LAN/Tailscale setup relies on."""

    def _run_main_capturing_host(self, host_env):
        import aitracker.cli as cli
        cap, orig, old_argv = {}, cli.run, sys.argv
        old_host = os.environ.pop("HOST", None)
        if host_env is not None:
            os.environ["HOST"] = host_env
        cli.run = lambda **kw: cap.update(kw)      # don't actually serve_forever
        try:
            sys.argv = ["ai-tracker"]              # no flags -> the serve path
            cli.main()
        finally:
            cli.run, sys.argv = orig, old_argv
            os.environ.pop("HOST", None)
            if old_host is not None:
                os.environ["HOST"] = old_host
        return cap.get("host")

    def test_defaults_to_localhost(self):
        self.assertEqual(self._run_main_capturing_host(None), "127.0.0.1")

    def test_host_env_is_honored(self):
        self.assertEqual(self._run_main_capturing_host("0.0.0.0"), "0.0.0.0")


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


class TestAuggiePRs(unittest.TestCase):
    """The PR panel shows PRs the session created OR actively worked on (URL in the assistant's
    narration/commands), not ones only referenced in a user prompt. Auggie logs no command
    output, so each `gh pr create` is tied to the first PR URL at/after it for the created flag."""

    def setUp(self):
        self.snap = _snap(); _empty_env()

    def tearDown(self):
        _restore(self.snap)

    def test_created_pr_attributed_and_prompt_ref_hidden(self):
        sid = "aupr"
        doc = {"sessionId": sid, "modified": "2026-07-16T10:03:00Z", "chatHistory": [
            {"finishedAt": "2026-07-16T10:00:00Z", "exchange": {                # #99 pasted in a PROMPT → reference only
                "request_message": "see https://github.com/o/r/pull/99 for context", "response_text": "ok",
                "response_nodes": []}},
            {"finishedAt": "2026-07-16T10:01:00Z", "exchange": {                # runs gh pr create (no URL here)
                "request_message": "", "response_text": "creating it now", "response_nodes": [
                    {"tool_use": {"tool_use_id": "c1", "tool_name": "launch-process",
                                  "input_json": json.dumps({"command": "gh pr create --base main"})}}]}},
            {"finishedAt": "2026-07-16T10:02:00Z", "exchange": {                # the created URL, two turns later
                "request_message": "", "response_text": "Done — PR #7 https://github.com/o/r/pull/7",
                "response_nodes": []}},
        ]}
        json.dump(doc, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        prs = _auggie.parse_auggie(sid)["prs"]
        nums = [p["num"] for p in prs]
        self.assertIn("7", nums)                                               # the generated PR shows
        self.assertTrue(next(p for p in prs if p["num"] == "7")["created"])    # ...flagged created
        self.assertNotIn("99", nums)                                           # prompt-only reference stays hidden

    def test_worked_on_same_repo_shows_crossrepo_hidden(self):
        # no create — the session works an EXISTING PR in its own repo (widgets), while its
        # narration also lists a PR in another repo (a status report). Only the own-repo one shows.
        sid = "aupr2"
        ide = {"ide_state_node": {"current_terminal": {"current_working_directory": "/home/me/proj/widgets"}}}
        doc = {"sessionId": sid, "modified": "2026-07-16T10:01:00Z", "chatHistory": [
            {"finishedAt": "2026-07-16T10:00:00Z", "exchange": {
                "request_message": "use the same PR", "request_nodes": [ide],
                "response_text": "", "response_nodes": []}},
            {"finishedAt": "2026-07-16T10:01:00Z", "exchange": {
                "request_message": "", "response_nodes": [],
                "response_text": ("PR #48 is now 1 clean commit https://github.com/acme/widgets/pull/48 "
                                  "(related: https://github.com/acme/other/pull/9)")}},
        ]}
        json.dump(doc, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        prs = _auggie.parse_auggie(sid)["prs"]
        self.assertEqual([p["num"] for p in prs], ["48"])                      # own-repo worked-on shows
        self.assertFalse(prs[0]["created"])                                    # not created — worked on
        self.assertNotIn("9", [p["num"] for p in prs])                        # cross-repo status mention hidden


class TestPinnedSessions(unittest.TestCase):
    """A pinned session sorts to the top of all_sessions(), over recency — read live from pins.json."""

    def setUp(self):
        self.snap = _snap(); _empty_env()
        config.PINS_FILE = os.path.join(tempfile.mkdtemp(), "pins.json")

    def tearDown(self):
        _restore(self.snap)

    def _wr(self, sid, modified):
        json.dump({"sessionId": sid, "modified": modified, "customTitle": sid,
                   "chatHistory": [{"finishedAt": modified,
                                    "exchange": {"request_message": "hi", "response_text": "ok"}}]},
                  open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        _auggie._AUGGIE_LIST_CACHE.clear()

    def test_pinned_sorts_first(self):
        from aitracker.registry import all_sessions
        self._wr("old", "2026-07-16T10:00:00Z")
        self._wr("new", "2026-07-16T11:00:00Z")
        ids = [s["id"] for s in all_sessions()]
        self.assertLess(ids.index("auggie:new"), ids.index("auggie:old"))   # newest-first by default
        json.dump(["auggie:old"], open(config.PINS_FILE, "w"))              # pin the older one
        _auggie._AUGGIE_LIST_CACHE.clear()
        ses = all_sessions()
        self.assertEqual(ses[0]["id"], "auggie:old")                        # pinned jumps to the top
        self.assertTrue(ses[0]["pinned"])
        self.assertFalse(next(s for s in ses if s["id"] == "auggie:new")["pinned"])


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
        self.assertEqual(ov["now_kind"], "todo")   # the "now" click jumps to the Progress panel
        self.assertIn("proj", ov["where"])
        self.assertTrue(ov["now"].startswith("▶"))

    def test_now_kind_agents(self):
        d = {"meta": {"cwd": "/x/proj"}, "counts": {"done": 0, "todos": 0, "created": 0, "edited": 0,
             "read": 0, "commits": 0, "tests": 0, "tests_failed": 0, "errors": 0, "agents": 0, "searches": 0}}
        ov = build_overview(d, [], [], [], [], [], [], [], [{"text": "hi"}],
                            [{"running": True, "task": "exploring the repo"}],
                            5, "2026-06-22T10:00:00Z", "2026-06-22T10:05:00Z")
        self.assertEqual(ov["now_kind"], "agents")   # running agent → Background agents panel
        self.assertTrue(ov["now"].startswith("⚙"))


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


class TestCoverageGaps(unittest.TestCase):
    """High-value gaps across modules: liveness-constant parity, provider isolation,
    multi-pin ordering, atomic store writes, and Claude search AND-semantics."""

    def setUp(self):
        self.snap = _snap(); _empty_env()

    def tearDown(self):
        _restore(self.snap)

    def test_live_constant_matches_server(self):
        # the one-liveness-constant invariant: the page's LIVE must equal server LIVE_WINDOW
        import re
        m = re.search(r"const\s+LIVE\s*=\s*(\d+)", build_page())
        self.assertIsNotNone(m, "LIVE const must be present in the served page")
        self.assertEqual(int(m.group(1)), int(config.LIVE_WINDOW))

    def test_broken_provider_isolated(self):
        # one provider raising in list() must not sink the whole session list
        from aitracker.registry import all_sessions, PROVIDERS
        _write_auggie("ok1", "Good one")

        class _Boom:
            def available(self): return True
            def list(self): raise RuntimeError("boom")
        saved = list(PROVIDERS)
        try:
            PROVIDERS.append(_Boom())
            ids = [s["id"] for s in all_sessions()]
            self.assertIn("auggie:ok1", ids)          # the survivor is still listed
        finally:
            PROVIDERS[:] = saved

    def test_multiple_pins_keep_recency(self):
        from aitracker.registry import all_sessions
        config.PINS_FILE = os.path.join(tempfile.mkdtemp(), "pins.json")
        for sid, mod in [("a", "2026-07-16T10:00:00Z"), ("b", "2026-07-16T11:00:00Z"), ("c", "2026-07-16T12:00:00Z")]:
            json.dump({"sessionId": sid, "modified": mod, "customTitle": sid,
                       "chatHistory": [{"finishedAt": mod, "exchange": {"request_message": "hi", "response_text": "ok"}}]},
                      open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))
        _auggie._AUGGIE_LIST_CACHE.clear()
        json.dump(["auggie:a", "auggie:c"], open(config.PINS_FILE, "w"))
        ids = [s["id"] for s in all_sessions()]
        self.assertLess(ids.index("auggie:c"), ids.index("auggie:a"))   # among pinned, newest first
        self.assertLess(ids.index("auggie:a"), ids.index("auggie:b"))   # both pinned above the unpinned one

    def test_store_roundtrip_and_corrupt_tolerance(self):
        from aitracker.store import _save_json, _load_json
        p = os.path.join(tempfile.mkdtemp(), "d.json")
        _save_json(p, {"x": [1, 2]})
        self.assertEqual(_load_json(p, None), {"x": [1, 2]})
        self.assertFalse(os.path.exists(p + ".tmp"))            # atomic: the temp file is swapped away
        open(p, "w").write("{ not valid json")
        self.assertEqual(_load_json(p, "DEFAULT"), "DEFAULT")   # corrupt file -> default, never throws

    def test_claude_search_and_semantics(self):
        from aitracker.registry import search_all
        d = os.path.join(config.PROJECTS, "p"); os.makedirs(d)
        def _wr(name, text):
            open(os.path.join(d, name + ".jsonl"), "w").write(json.dumps(
                {"cwd": "/p", "entrypoint": "cli", "timestamp": "2026-06-01T00:00:00Z",
                 "message": {"role": "user", "content": text}}) + "\n")
        _wr("aaa", "please fix the auth bug now")
        _wr("bbb", "unrelated deploy notes")
        _claude._META_CACHE.clear()
        ids = [r["id"] for r in search_all("auth bug")]
        self.assertIn("aaa", ids)                # both terms present -> match
        self.assertNotIn("bbb", ids)             # a term missing -> excluded (AND semantics)


if __name__ == "__main__":
    unittest.main()
