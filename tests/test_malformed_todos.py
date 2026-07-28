#!/usr/bin/env python3
"""A malformed TodoWrite must not crash the session parse. Seen in the wild: a
`TodoWrite` whose `todos` input was the string "[]" (not a list) — the parser
iterated the string's characters, called `.get` on a str, and raised. The
unhandled exception closed the socket with no response, which a Cloudflare
tunnel reported to the browser as 502 Bad Gateway on every 2s poll.

Two guarantees, both pinned here:
 1. parse_session normalizes `todos` to a list of dicts (parser seam).
 2. /api/session degrades to a clean JSON 500 instead of a dropped connection
    even if a provider still raises (route-resilience seam).
"""
import http.client
import json
import os
import shutil
import tempfile
import threading
import unittest

import aitracker.config as config
from aitracker import server as _server
from aitracker.providers import claude as _claude
from aitracker.providers.claude import parse_session


def _write(path, lines):
    with open(path, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


class TestMalformedTodosParse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _parse_with_todos(self, todos):
        sid = "sess"
        p = os.path.join(self.dir, sid + ".jsonl")
        _write(p, [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "timestamp": "2026-07-13T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "TodoWrite",
                 "input": {"todos": todos}}]}},
        ])
        return parse_session(p)

    def test_todos_as_string_does_not_crash(self):
        # the exact wild input: todos == "[]" (a string). Must not raise.
        d = self._parse_with_todos("[]")
        self.assertEqual(d["todos"], [])
        self.assertEqual(d["counts"]["todos"], 0)
        self.assertEqual(d["counts"]["done"], 0)

    def test_stray_non_dict_entries_are_dropped(self):
        d = self._parse_with_todos([
            "just a string",
            {"content": "real", "status": "completed"},
            None,
        ])
        self.assertEqual([t["content"] for t in d["todos"]], ["real"])
        self.assertEqual(d["counts"]["done"], 1)


class TestMalformedTodosEndToEnd(unittest.TestCase):
    """The 502 scenario end-to-end: fetch /api/session for a session whose last
    TodoWrite is malformed. It must return a normal 200 payload, not drop the
    connection (which becomes a tunnel 502)."""

    def setUp(self):
        self._proj0 = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        _claude._META_CACHE.clear()
        sid = "ab36a071"
        d = os.path.join(config.PROJECTS, "proj")
        os.makedirs(d)
        _write(os.path.join(d, sid + ".jsonl"), [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "timestamp": "2026-07-13T10:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "TodoWrite",
                 "input": {"todos": "[]"}}]}},
        ])
        self.sid = sid
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(config.PROJECTS, ignore_errors=True)
        config.PROJECTS = self._proj0
        _claude._META_CACHE.clear()

    def test_session_route_returns_200_not_dropped(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", "/api/session?id=" + self.sid)
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        self.assertEqual(r.status, 200)          # not a dropped connection (=> tunnel 502)
        self.assertEqual(body["todos"], [])


if __name__ == "__main__":
    unittest.main()
