#!/usr/bin/env python3
"""Integration coverage for the Control Room server capabilities that so far only had
selfcheck (unit-level) assertions: POST /api/config, the cross-stack GET /api/search,
the new shared-shape fields on /api/list and /api/session, and the no-host-gating
invariant on the served page. Boots the REAL server on an ephemeral port and drives it
over real HTTP -- the same idiom tests/test_integration.py's TestServerEndToEnd already
uses (_snap/_restore/_empty_env, ThreadingHTTPServer on port 0, http.client, addCleanup
teardown), copied here rather than invented afresh, and not touching that file (another
agent is appending to it) or test_selfcheck.py.

Stdlib only. Every server this file boots is torn down via addCleanup, including on
failure; every path this file overrides is a tempfile/tempdir, restored in the same way.
"""
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.parse

import aitracker.config as config
from aitracker import server as _server
from aitracker.providers import auggie as _auggie
from aitracker.providers import claude as _claude


# ---------------------------------------------------------------------------
# Harness -- same shape as tests/test_integration.py's _snap/_restore/_empty_env,
# extended with CONFIG_FILE (POST /api/config's target) and the plain config globals
# that GET/POST /api/config mutate live (config.apply_overrides repoints them).
# ---------------------------------------------------------------------------

_PATHS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "VSCODE_WS_ROOT", "CURSOR_WS_ROOT",
          "FLAGS_FILE", "TITLES_FILE", "PINS_FILE", "NOTES_FILE", "TASKS_DIR", "PORT_FILE",
          "TOKEN_FILE", "CONFIG_FILE", "FORKS_FILE")

_CFG_ATTRS = ("LIVE_WINDOW", "TERM_RENDERER", "MAX_TERMS", "TERMINAL")



def _snap():
    s = {k: getattr(config, k) for k in _PATHS}
    s["AUTH"] = config.AUTH
    s["_cfg"] = {k: getattr(config, k) for k in _CFG_ATTRS}
    s["_max_terms_env"] = os.environ.get("TRACKER_MAX_TERMS")
    return s


def _restore(s):
    for k in _PATHS:
        setattr(config, k, s[k])
    config.AUTH = s["AUTH"]
    for k, v in s["_cfg"].items():
        setattr(config, k, v)
    if s["_max_terms_env"] is None:
        os.environ.pop("TRACKER_MAX_TERMS", None)
    else:
        os.environ["TRACKER_MAX_TERMS"] = s["_max_terms_env"]
    _auggie._AUGGIE_LIST_CACHE.clear()
    _claude._META_CACHE.clear()


def _empty_env():
    """Repoint every data path (and CONFIG_FILE) at fresh temp locations. CONFIG_FILE is
    a tempfile.mktemp() path -- deliberately never created here, so _load_json(CONFIG_FILE,
    {}) sees no pre-existing overrides and every test starts from the built-in defaults.
    config.AUTH is force-cleared: TRACKER_AUTH is exported in the shell this runs in (a
    real value a real developer set for their own dashboard), and config.AUTH is a plain
    module constant resolved once at import time -- so it does NOT pick up a later
    os.environ change. Every existing test class that needs unauthenticated routes
    (TestTermCountBadge, TestBasicAuth's _auth_off, etc. in test_integration.py) already
    repoints config.AUTH directly for exactly this reason; this is the same idiom, just
    folded into the shared setUp instead of repeated per class."""
    config.PROJECTS = tempfile.mkdtemp()
    config.AUGMENT_DIR = tempfile.mkdtemp()
    config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
    os.makedirs(config.AUGGIE_SESSIONS)
    # Augment VSCode/Cursor extension roots -- WITHOUT this override AugmentVscodeProvider/
    # AugmentCursorProvider read the real machine's actual workspaceStorage (hundreds of the
    # developer's own real sessions leaked straight into /api/list during first authoring of
    # this file -- confirmed by running it). Same override tests/test_integration.py's own
    # _empty_env() makes, for the identical reason.
    config.VSCODE_WS_ROOT = tempfile.mkdtemp()
    config.CURSOR_WS_ROOT = tempfile.mkdtemp()
    config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
    config.TITLES_FILE = tempfile.mktemp(suffix=".json")
    config.PINS_FILE = tempfile.mktemp(suffix=".json")
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
    config.TASKS_DIR = tempfile.mkdtemp()
    config.PORT_FILE = tempfile.mktemp()
    config.TOKEN_FILE = tempfile.mktemp()
    config.CONFIG_FILE = tempfile.mktemp(suffix=".json")
    config.FORKS_FILE = tempfile.mktemp(suffix=".json")
    config.AUTH = ""
    _auggie._AUGGIE_LIST_CACHE.clear()
    _claude._META_CACHE.clear()


def _write_claude(sid, prompt="go", cwd="/x", mtime=None):
    """Minimal valid Claude session: one user line the parsers can read cwd/prompt off."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + ".jsonl")
    with open(path, "w") as fh:
        fh.write(json.dumps({"type": "user", "cwd": cwd,
                              "message": {"role": "user", "content": prompt}}) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _write_claude_with_todo(sid):
    """A Claude session whose one TodoWrite call gives parse_session's `todos` a real
    entry -- proves started_at/ended_at are present as KEYS on every todo (they're set
    unconditionally in the started_at/ended_at join loop, null here since there's no
    TaskCreate/TaskUpdate/task-store backing this fixture -- see providers/claude.py's
    comment above that loop)."""
    d = os.path.join(config.PROJECTS, "proj")
    os.makedirs(d, exist_ok=True)
    lines = [
        {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
        {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z",
         "message": {"content": [
             {"type": "tool_use", "name": "TodoWrite", "input": {"todos": [
                 {"content": "Ship the thing", "activeForm": "Shipping the thing",
                  "status": "in_progress"}]}}]}},
    ]
    with open(os.path.join(d, sid + ".jsonl"), "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


def _write_auggie(sid, title, req="the request", resp="the reply", root_uuid=None):
    d = {"sessionId": sid, "modified": "2026-06-27T05:48:03Z", "customTitle": title,
         "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                           "exchange": {"request_message": req, "response_text": resp}}]}
    if root_uuid:
        d["rootTaskUuid"] = root_uuid
    json.dump(d, open(os.path.join(config.AUGGIE_SESSIONS, sid + ".json"), "w"))


def _mk_auggie_task_file(uuid, name, state, subtasks=None):
    """One Auggie CLI task-storage file -- AUGMENT_DIR/task-storage/tasks/<uuid>, filename
    IS the uuid with no extension (providers/auggie.py's _load_task_file/_auggie_all read
    it that way; this is a DIFFERENT layout from the per-workspace VSCode/Cursor extension
    task store tests/test_integration.py's _mk_augment_task builds)."""
    d = os.path.join(config.AUGMENT_DIR, "task-storage", "tasks")
    os.makedirs(d, exist_ok=True)
    json.dump({"uuid": uuid, "name": name, "state": state, "subTasks": subtasks or []},
               open(os.path.join(d, uuid), "w"))


def _write_auggie_with_todo(sid, title="Has a todo"):
    """An Auggie session whose rootTaskUuid resolves (via the task-storage files above) to
    one child todo -- proves todo_times_approximate is True and started_at/ended_at are
    present as keys (always null for Auggie -- see _auggie_resolve's own comment on why
    there's no reliable id join, unlike Claude's exact task-store join)."""
    root, child = "root-" + sid, "child-" + sid
    _mk_auggie_task_file(root, "root", "PENDING", subtasks=[child])
    _mk_auggie_task_file(child, "Ship the thing", "IN_PROGRESS")
    _write_auggie(sid, title, root_uuid=root)


class _ServerCase(unittest.TestCase):
    """Boots the real server on an ephemeral port against an emptied env; every request
    goes over real HTTP. Teardown is registered via addCleanup (LIFO: shutdown ->
    server_close -> restore config), so a failing test still leaves no server running and
    no leftover config.json."""

    def setUp(self):
        self.snap = _snap()
        self.addCleanup(_restore, self.snap)
        _empty_env()
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.addCleanup(self.srv.server_close)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()
        self.addCleanup(self.srv.shutdown)

    def _get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def _get_json(self, path):
        st, body = self._get(path)
        return st, json.loads(body)

    def _post(self, path, payload):
        body = json.dumps(payload).encode()
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=body,
                   headers={"Content-Type": "application/json", "Content-Length": str(len(body))})
        r = c.getresponse()
        resp = r.read()
        c.close()
        return r.status, json.loads(resp)


# =============================================================================
# 1. POST /api/config
# =============================================================================

class TestApiConfigWrite(_ServerCase):
    """POST/GET /api/config over real HTTP -- see config.py's big module comment for the
    precedence contract (config.json > env > default) this is proving end-to-end."""

    def setUp(self):
        super().setUp()
        os.environ.pop("TRACKER_MAX_TERMS", None)   # clean baseline for the precedence test

    def test_valid_key_accepted_and_takes_effect_on_a_later_read(self):
        st, j = self._post("/api/config", {"key": "MAX_TERMS", "value": 5})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "key": "MAX_TERMS", "value": 5, "restart": False})

        # a SEPARATE GET (not just the POST's own echo) sees the same value -- proves it
        # actually reached config.json, not just this one response.
        st, j = self._get_json("/api/config")
        self.assertEqual(st, 200)
        self.assertEqual(j["MAX_TERMS"], {"value": 5, "overridden": True, "restart": False})
        self.assertTrue(os.path.exists(config.CONFIG_FILE))
        self.assertEqual(json.load(open(config.CONFIG_FILE))["MAX_TERMS"], 5)

    def test_unknown_key_is_rejected_with_400(self):
        """RED demonstration #1: a key that isn't on config.EDITABLE at all."""
        st, j = self._post("/api/config", {"key": "NOT_A_REAL_SETTING", "value": 1})
        self.assertEqual(st, 400)
        self.assertEqual(j, {"error": "unknown config key", "key": "NOT_A_REAL_SETTING"})
        # never wrote a config.json at all for a rejected key
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

    def test_tracker_auth_is_rejected_even_though_its_not_a_typo(self):
        """THE most important assertion in this file. TRACKER_AUTH gates every route with
        HTTP Basic Auth (server.py's config.AUTH) -- but it is DELIBERATELY EXCLUDED from
        config.EDITABLE (see config.py's comment beside `AUTH = os.environ.get(...)`)
        because writing a password typed into a Config-dialog form into a plaintext
        config.json, on a server that may be reachable over a tunnel, is a real security
        regression, not a convenience. This must 400 exactly like any other unknown key --
        proving the dialog can never persist a credential to disk."""
        st, j = self._post("/api/config", {"key": "TRACKER_AUTH", "value": "someone:newpass"})
        self.assertEqual(st, 400)
        self.assertEqual(j["error"], "unknown config key")
        self.assertEqual(j["key"], "TRACKER_AUTH")
        # ...and no config.json was written with the attempted credential in it
        self.assertFalse(os.path.exists(config.CONFIG_FILE))
        # config.AUTH itself (the live gate) is completely unaffected by the rejected write
        self.assertEqual(config.AUTH, "")

    def test_out_of_range_value_is_rejected_and_never_reaches_disk(self):
        """RED demonstration #2: MAX_TERMS is clamped to [1, 64] -- 9999 is a valid int,
        just out of range, so this exercises VALIDATORS, not the key-membership check."""
        st, j = self._post("/api/config", {"key": "MAX_TERMS", "value": 9999})
        self.assertEqual(st, 400)
        self.assertEqual(j, {"error": "invalid value for MAX_TERMS"})
        self.assertFalse(os.path.exists(config.CONFIG_FILE))
        # a wrong-TYPE value for a different key is rejected the same way (bool where a
        # string enum is required)
        st, j = self._post("/api/config", {"key": "TERM_RENDERER", "value": True})
        self.assertEqual(st, 400)
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

    def test_precedence_config_over_env_over_builtin_default(self):
        # 1) nothing set anywhere -> the built-in default (12), not overridden
        st, j = self._get_json("/api/config")
        self.assertEqual(j["MAX_TERMS"], {"value": 12, "overridden": False, "restart": False})

        # 2) TRACKER_MAX_TERMS set, still no config.json override -> env wins over default
        os.environ["TRACKER_MAX_TERMS"] = "7"
        st, j = self._get_json("/api/config")
        self.assertEqual(j["MAX_TERMS"], {"value": 7, "overridden": False, "restart": False})

        # 3) a config.json override on top of that same env var -> config.json wins over env
        st, j = self._post("/api/config", {"key": "MAX_TERMS", "value": 5})
        self.assertEqual(st, 200)
        st, j = self._get_json("/api/config")
        self.assertEqual(j["MAX_TERMS"], {"value": 5, "overridden": True, "restart": False})


class TestApiConfigIconKeys(_ServerCase):
    """ICON_STYLE/ICON_SCALE -- the two Config-dialog knobs added for the icon-sprite
    conversion (config.py: config.EDITABLE/config.VALIDATORS, resolve_icon_style/
    resolve_icon_scale). Same POST/GET round-trip idiom as TestApiConfigWrite above;
    kept as its own class since it's a distinct feature, not a MAX_TERMS variant."""

    def test_icon_style_each_valid_value_round_trips(self):
        for val in ("icons", "emoji", "text"):
            st, j = self._post("/api/config", {"key": "ICON_STYLE", "value": val})
            self.assertEqual(st, 200)
            self.assertEqual(j, {"ok": True, "key": "ICON_STYLE", "value": val, "restart": False})

            # a separate GET confirms it actually reached config.json, not just the echo
            st, j = self._get_json("/api/config")
            self.assertEqual(st, 200)
            self.assertEqual(j["ICON_STYLE"], {"value": val, "overridden": True, "restart": False})
            self.assertEqual(json.load(open(config.CONFIG_FILE))["ICON_STYLE"], val)

    def test_icon_style_invalid_value_is_rejected_and_never_reaches_disk(self):
        st, j = self._post("/api/config", {"key": "ICON_STYLE", "value": "sparkles"})
        self.assertEqual(st, 400)
        self.assertEqual(j, {"error": "invalid value for ICON_STYLE"})
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

    def test_icon_scale_in_range_value_round_trips(self):
        st, j = self._post("/api/config", {"key": "ICON_SCALE", "value": 150})
        self.assertEqual(st, 200)
        self.assertEqual(j, {"ok": True, "key": "ICON_SCALE", "value": 150, "restart": False})

        st, j = self._get_json("/api/config")
        self.assertEqual(st, 200)
        self.assertEqual(j["ICON_SCALE"], {"value": 150, "overridden": True, "restart": False})
        self.assertEqual(json.load(open(config.CONFIG_FILE))["ICON_SCALE"], 150)

    def test_icon_scale_out_of_range_is_rejected_and_never_reaches_disk(self):
        # below range
        st, j = self._post("/api/config", {"key": "ICON_SCALE", "value": 74})
        self.assertEqual(st, 400)
        self.assertEqual(j, {"error": "invalid value for ICON_SCALE"})
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

        # above range
        st, j = self._post("/api/config", {"key": "ICON_SCALE", "value": 201})
        self.assertEqual(st, 400)
        self.assertEqual(j, {"error": "invalid value for ICON_SCALE"})
        self.assertFalse(os.path.exists(config.CONFIG_FILE))

    def test_icon_scale_boundary_values_are_accepted(self):
        """Off-by-one guard on the [75, 200] clamp -- both edges must be INSIDE the range."""
        for val in (75, 200):
            st, j = self._post("/api/config", {"key": "ICON_SCALE", "value": val})
            self.assertEqual(st, 200)
            self.assertEqual(j, {"ok": True, "key": "ICON_SCALE", "value": val, "restart": False})
            st, j = self._get_json("/api/config")
            self.assertEqual(j["ICON_SCALE"], {"value": val, "overridden": True, "restart": False})

    def test_icon_keys_default_in_snapshot_when_unoverridden(self):
        """Nothing overridden anywhere -> the defaults that reproduce today's appearance
        exactly: ICON_STYLE "icons", ICON_SCALE 100 (see resolve_icon_style/
        resolve_icon_scale in config.py)."""
        st, j = self._get_json("/api/config")
        self.assertEqual(st, 200)
        self.assertEqual(j["ICON_STYLE"], {"value": "icons", "overridden": False, "restart": False})
        self.assertEqual(j["ICON_SCALE"], {"value": 100, "overridden": False, "restart": False})


# =============================================================================
# 2. GET /api/search -- whole-stack cross-session search (not /api/list's 200 window)
# =============================================================================

class TestApiSearchWholeStack(_ServerCase):
    def test_search_hit_shape_matches_what_the_client_reads(self):
        """ext_cr_board.js's search-hit handling (aitracker/web/ext_cr_board.js, the comment
        above scheduleSessionsSearch's fetch) states the exact shape a raw /api/search hit
        carries: {id, project, title, agent, matches, snippet, inQuery, titleMatch, mtime}.
        Assert the real HTTP response carries exactly those fields, nothing more/less."""
        _write_claude("term-hit", prompt="please deploy the shiny widget now")
        st, j = self._get_json("/api/search?q=shiny%20widget")
        self.assertEqual(st, 200)
        self.assertTrue(j, "expected at least one hit")
        hit = next(h for h in j if h["id"] == "term-hit")
        expected_keys = {"id", "project", "title", "agent", "matches", "snippet",
                          "inQuery", "titleMatch", "mtime"}
        self.assertEqual(set(hit.keys()), expected_keys)
        self.assertIsInstance(hit["matches"], int)
        self.assertIsInstance(hit["inQuery"], bool)
        self.assertIsInstance(hit["titleMatch"], bool)

    def test_empty_and_whitespace_query_degrade_to_empty_list(self):
        _write_claude("anything", prompt="hello world")
        for q in ("", "   ", "\t\n "):
            st, j = self._get_json("/api/search?q=" + urllib.parse.quote(q))
            self.assertEqual(st, 200, repr(q))
            self.assertEqual(j, [], repr(q))

    def test_search_covers_sessions_api_list_has_already_dropped(self):
        """/api/list caps each provider at its newest 200 (providers/claude.py's
        list_sessions(limit=200)) -- the Sessions destination's search must still reach an
        OLDER session than that. Build 221 Claude sessions (well past the 200 cutoff) with
        one deliberately the GLOBAL oldest and carrying a unique term; prove /api/list has
        dropped it while /api/search still finds it."""
        base = time.time() - 100000
        _write_claude("historic-session", prompt="zzzhistoricmarker is buried here", mtime=base)
        for i in range(1, 221):
            _write_claude("filler-%03d" % i, prompt="just filler content", mtime=base + i)
        _claude._META_CACHE.clear()

        st, j = self._get_json("/api/list")
        self.assertEqual(st, 200)
        ids = [s["id"] for s in j]
        self.assertEqual(len(ids), 200, "list_sessions(limit=200) must still cap at 200")
        self.assertNotIn("historic-session", ids, "the 200-per-provider window must have dropped it")

        st, j = self._get_json("/api/search?q=zzzhistoricmarker")
        self.assertEqual(st, 200)
        self.assertIn("historic-session", [h["id"] for h in j],
                       "search must cover the whole stack, not just /api/list's window")


# =============================================================================
# 3. /api/list -- shared-shape fields, present + consistently typed for EVERY provider
# =============================================================================

class TestApiListSharedFields(_ServerCase):
    def test_todo_pr_and_now_line_fields_present_and_typed_alike_on_every_provider(self):
        _write_claude("c1")
        _write_auggie("a1", "Auggie one")
        st, j = self._get_json("/api/list")
        self.assertEqual(st, 200)
        ids = {s["id"] for s in j}
        self.assertEqual(ids, {"c1", "auggie:a1"}, "fixture must be found via both providers")

        for s in j:
            for k in ("todo_total", "todo_done"):
                self.assertIsInstance(s[k], int, (s["id"], k))
            self.assertTrue(s["todo_current"] is None or isinstance(s["todo_current"], str), s["id"])
            idx = s["todo_current_index"]
            self.assertTrue(idx is None or (isinstance(idx, int) and not isinstance(idx, bool)), s["id"])
            self.assertTrue(s["pr_num"] is None or isinstance(s["pr_num"], int), s["id"])
            self.assertTrue(s["pr_url"] is None or isinstance(s["pr_url"], str), s["id"])
            self.assertTrue(s["pr_repo"] is None or isinstance(s["pr_repo"], str), s["id"])
            self.assertIsInstance(s["pr_state"], str, s["id"])   # always a string, never None
            self.assertIsInstance(s["now_line"], str, s["id"])   # always a string, "" when not live

        # `model`: present on the session-LIST dict for BOTH providers (providers/claude.py's
        # list_sessions -- "model": sm.get("model") or ""; providers/auggie.py's list_auggie
        # -- "model": e.get("model") or "") -- always a string, "" when unknown.
        for s in j:
            self.assertIn("model", s, s["id"])
            self.assertIsInstance(s["model"], str, s["id"])


# =============================================================================
# 4. /api/session -- pinned/note_count/open_flags/todo_times_approximate/per-todo timestamps
# =============================================================================

class TestApiSessionSharedFields(_ServerCase):
    def test_pinned_note_count_open_flags_present_for_both_providers(self):
        _write_claude("c2")
        _write_auggie("a2", "Auggie two")

        for sid in ("c2", "auggie:a2"):
            st, j = self._get_json("/api/session?id=" + sid)
            self.assertEqual(st, 200, sid)
            self.assertIs(j["pinned"], False, sid)
            self.assertEqual(j["note_count"], 0, sid)
            self.assertEqual(j["open_flags"], 0, sid)

        # flip pinned/note_count/open_flags for one of them and confirm the detail dict
        # actually reflects it (not just always-zero placeholders)
        self._post("/api/pin", {"session": "c2", "pinned": True})
        self._post("/api/notes", {"session": "c2", "text": "a note"})
        self._post("/api/flags", {"session": "c2", "project": "x", "note": "a gap"})
        st, j = self._get_json("/api/session?id=c2")
        self.assertIs(j["pinned"], True)
        self.assertEqual(j["note_count"], 1)
        self.assertEqual(j["open_flags"], 1)

    def test_todo_times_approximate_and_per_todo_timestamp_keys(self):
        _write_claude_with_todo("c3")
        _write_auggie_with_todo("a3")

        st, j = self._get_json("/api/session?id=c3")
        self.assertEqual(st, 200)
        self.assertIs(j["todo_times_approximate"], False, "Claude's join is exact")
        self.assertTrue(j["todos"], "fixture must produce at least one todo")
        for t in j["todos"]:
            self.assertIn("started_at", t)
            self.assertIn("ended_at", t)

        st, j = self._get_json("/api/session?id=auggie:a3")
        self.assertEqual(st, 200)
        self.assertIs(j["todo_times_approximate"], True, "Auggie's join is name-matched, not exact")
        self.assertTrue(j["todos"], "fixture must produce at least one todo")
        for t in j["todos"]:
            self.assertIn("started_at", t)
            self.assertIn("ended_at", t)


# =============================================================================
# 5. Served page -- recorded-user-data controls are never host-gated
# =============================================================================

class TestServedPageNotHostGated(_ServerCase):
    def test_no_host_gating_on_flag_rename_pin_note_controls(self):
        st, body = self._get("/")
        self.assertEqual(st, 200)
        page = body.decode("utf-8", "replace")

        # the exact bug class conventions.md calls out: a `.remote` CSS class hiding a
        # recorded-user-data control from a remote/tunnel viewer. Must be fully gone.
        self.assertNotIn(".remote", page)

        controls = ('class=addflag', 'class=addnote', 'data-act="toggle-flag"',
                    'data-act="rename"', 'togglePin(')
        for marker in controls:
            self.assertIn(marker, page, "control must be baked into the page: %s" % marker)

        # `location.hostname`/`localOnly()` gating DOES legitimately exist in this app --
        # but ONLY for the one approved OS-process-launch exception ext_launch.js documents
        # ("Do not 'fix' it to match the usual rule") -- opening a real terminal on the
        # machine running the server. It must never sit next to a recorded-user-data
        # control. Confirm none of the controls above falls within a plausible
        # if(isLocalhost)/if(localOnly()) block's reach of a location.hostname check.
        gate_positions = [m.start() for m in re.finditer(r"location\.hostname", page)]
        self.assertTrue(gate_positions, "sanity: the approved terminal-launch exception must still exist")
        for marker in controls:
            for pos in (m.start() for m in re.finditer(re.escape(marker), page)):
                nearest = min(abs(pos - g) for g in gate_positions)
                self.assertGreater(nearest, 300,
                    "%r sits only %d chars from a location.hostname gate" % (marker, nearest))


if __name__ == "__main__":
    unittest.main()
