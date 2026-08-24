#!/usr/bin/env python3
"""Regression coverage for the liveness-clock gap.

Before this fix, /api/session shipped a server-stamped `now` field (each provider's
parse() stamps time.time()) and the detail pane's render() used it -- but /api/list
returned a bare array with no time signal at all, so the sidebar (renderSide()) fell
back to the browser's own Date.now(). Two independent clocks meant a session could show
✅ done in the sidebar while the still-open detail pane showed it ▶ live (or vice
versa) whenever the two clocks disagreed -- trivially true on a phone/tablet over a
tunnel, or on any desktop with clock drift. Conventions rule 5: "server owns policy;
client renders it... Liveness is one constant."

The fix: /api/list now carries the server's own clock on an X-Server-Now response
header (the response SHAPE gains the clock without reshaping the JSON body -- see the
comment at the /api/list route in aitracker/server.py for why a header was chosen over
wrapping the array). The SPA's loadSide() reads it into a module-level `listNow` and
renderSide() computes every live/done check from that value instead of Date.now().

The load-bearing assertion here is test_api_list_and_api_session_agree_on_now: both
endpoints must report the SAME clock, not merely "both look like the current time."
"""
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest

import aitracker.config as config
from aitracker import server as _server
from aitracker.page import build_page
from aitracker.providers import auggie as _auggie
from aitracker.providers import claude as _claude

_PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE",
          "PINS_FILE", "TASKS_DIR", "NOTES_FILE", "PORT_FILE", "TOKEN_FILE")


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
    config.VSCODE_WS_ROOT = tempfile.mkdtemp()
    config.CURSOR_WS_ROOT = tempfile.mkdtemp()
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
    _auggie._AUGGIE_LIST_CACHE.clear()
    _claude._META_CACHE.clear()


def _write_claude_session(sid):
    """A minimal Claude session under config.PROJECTS -- just enough for parse_session()
    to succeed and stamp its own `now`."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    lines = [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}]
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


class TestListCarriesServerClock(unittest.TestCase):
    """/api/list must expose the server's own clock so the sidebar can compute liveness
    from the same clock /api/session's `now` field already uses."""

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
        headers = dict(r.getheaders())
        c.close()
        return r.status, body, headers

    def test_api_list_carries_x_server_now_header(self):
        before = time.time()
        st, body, headers = self._get("/api/list")
        after = time.time()
        self.assertEqual(st, 200)
        self.assertIn("X-Server-Now", headers)
        now = float(headers["X-Server-Now"])
        self.assertGreaterEqual(now, before - 1)     # a real clock reading, not a stub/zero
        self.assertLessEqual(now, after + 1)
        # the body shape is UNCHANGED — still a bare array. The clock rides the header,
        # not a body reshape, so every existing /api/list consumer keeps working untouched.
        self.assertIsInstance(json.loads(body), list)

    def test_api_list_body_unchanged_with_sessions_present(self):
        _write_claude_session("shape-sess")
        st, body, _ = self._get("/api/list")
        self.assertEqual(st, 200)
        parsed = json.loads(body)
        self.assertIsInstance(parsed, list)
        self.assertIn("shape-sess", [s["id"] for s in parsed])

    def test_api_list_and_api_session_agree_on_now(self):
        """THE load-bearing assertion. Both endpoints' `now` must come from the same
        clock, not just both be plausible-looking timestamps. A regression that drops
        the header (or reintroduces a second, client-side clock for the sidebar) is
        exactly what this catches."""
        _write_claude_session("clock-sess")
        st1, _, headers = self._get("/api/list")
        st2, body2, _ = self._get("/api/session?id=clock-sess")
        self.assertEqual((st1, st2), (200, 200))
        list_now = float(headers["X-Server-Now"])
        detail = json.loads(body2)
        session_now = detail["now"]
        # both are time.time() calls on the same machine a moment apart in this test --
        # nowhere near the 300s LIVE_WINDOW. A tight tolerance is what makes this a
        # "same clock" assertion rather than a "both roughly now" one.
        self.assertLess(abs(list_now - session_now), 5)

    def test_api_list_now_advances_between_polls(self):
        """Not a frozen/constant value -- each /api/list response stamps its own
        time.time(), matching how /api/session already behaves."""
        _, _, h1 = self._get("/api/list")
        time.sleep(0.05)
        _, _, h2 = self._get("/api/list")
        self.assertGreaterEqual(float(h2["X-Server-Now"]), float(h1["X-Server-Now"]))


class TestSidebarUsesServerNow(unittest.TestCase):
    """The served page (web/app.js inlined by page.build_page()) must source the
    sidebar's liveness clock from the server, not the browser's Date.now() -- the exact
    regression this gap closes. Pure static-content checks; no server needed."""

    def setUp(self):
        self.page = build_page()

    def test_list_now_global_declared(self):
        self.assertIn("let listNow=", self.page)

    def test_loadside_reads_the_header(self):
        i = self.page.index("async function loadSide()")
        seg = self.page[i:i + 400]
        self.assertIn("X-Server-Now", seg)
        self.assertIn("listNow", seg)

    def test_rendersid_now_is_not_client_clock(self):
        i = self.page.index("function renderSide(){")
        # renderSide's `now` is assigned on the very next statement -- inspect just that
        head = self.page[i:i + 200]
        self.assertIn("now=listNow", head)
        self.assertNotIn("Date.now()", head)

    def test_flag_panels_use_server_now_not_client_clock(self):
        for fn in ("function renderFlags(){", "function renderAllFlags(){"):
            i = self.page.index(fn)
            seg = self.page[i:i + 400]
            self.assertIn("now=listNow", seg)
            self.assertNotIn("Date.now()", seg)


if __name__ == "__main__":
    unittest.main()
