#!/usr/bin/env python3
"""opencode provider tests — against the PUBLIC seam contract only (Provider's
available/list/parse/search/exists/output/diff/shell/agent + the exact dict keys
documented for OpencodeProvider), never against the module's internals. The
provider module (aitracker/providers/opencode.py) is being written concurrently
by another agent; until it lands, importing this file raises ImportError — that
is expected. Verify structurally with `python3 -m py_compile tests/test_opencode.py`
until then.

The fixture below mirrors the CONFIRMED opencode SQLite schema (read from the real
~/.local/share/opencode/opencode.db): sessions/messages/parts/todos/projects, with
`time_*` columns in epoch MILLISECONDS and `session.model` a JSON *string*. Two
sessions: ses_main (a normal top-level session) and ses_sub (parent_id=ses_main, a
sub-agent session, opencode's Task/sub-agent analog). ses_main's parts cover every
tool kind called out in the brief — bash (one completed, one error), read, write,
edit, task, question — plus a real assistant text part and a `"synthetic": true`
text part that must never leak into narrative/requests.
"""
import json
import os
import re
import sqlite3
import tempfile
import time
import unittest

import aitracker.config as config
from aitracker.providers import opencode as _oc
from aitracker.providers.opencode import OpencodeProvider


NOW_MS = int(time.time() * 1000)


def _ms(offset_s):
    return NOW_MS + offset_s * 1000


DDL = """
CREATE TABLE session (
    id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT, slug TEXT,
    directory TEXT NOT NULL, path TEXT, title TEXT NOT NULL, version TEXT, share_url TEXT,
    summary_additions INT, summary_deletions INT, summary_files INT, summary_diffs INT,
    metadata TEXT, cost REAL, tokens_input INT, tokens_output INT, tokens_reasoning INT,
    tokens_cache_read INT, tokens_cache_write INT, revert TEXT, permission TEXT, agent TEXT,
    model TEXT, time_created INT, time_updated INT, time_compacting INT, time_archived INT
);
CREATE TABLE message (
    id TEXT PRIMARY KEY, session_id TEXT, time_created INT, time_updated INT, data TEXT
);
CREATE TABLE part (
    id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INT, time_updated INT,
    data TEXT
);
CREATE TABLE todo (
    session_id TEXT, content TEXT, status TEXT, priority TEXT, position INT,
    time_created INT, time_updated INT, PRIMARY KEY (session_id, position)
);
CREATE TABLE project (
    id TEXT PRIMARY KEY, worktree TEXT NOT NULL, vcs TEXT, name TEXT, icon_url TEXT,
    time_created INT, time_updated INT, sandboxes TEXT, commands TEXT
);
"""


def _session_row(conn, **kw):
    cols = ("id", "project_id", "workspace_id", "parent_id", "slug", "directory", "path",
            "title", "version", "agent", "model", "cost", "tokens_input", "tokens_output",
            "tokens_reasoning", "tokens_cache_read", "tokens_cache_write",
            "time_created", "time_updated")
    vals = [kw[c] for c in cols]
    conn.execute("INSERT INTO session (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), vals)


def _message(conn, mid, sid, t, data):
    conn.execute("INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?,?,?,?,?)",
                 (mid, sid, t, t, json.dumps(data)))


def _part(conn, pid, mid, sid, t, data):
    conn.execute("INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?,?,?,?,?,?)",
                 (pid, mid, sid, t, t, json.dumps(data)))


MODEL_JSON = json.dumps({"id": "big-pickle", "providerID": "opencode", "variant": "default"})


def build_fixture_db(path):
    """The full-coverage fixture: ses_main (normal) + ses_sub (sub-agent), messages,
    every documented part.data.type, todos in all three statuses, one project."""
    conn = sqlite3.connect(path)
    conn.executescript(DDL)

    conn.execute("INSERT INTO project (id, worktree, vcs, name, time_created, time_updated) VALUES (?,?,?,?,?,?)",
                 ("proj1", "/work/repo", "git", "repo", _ms(-3600), _ms(-60)))

    _session_row(conn, id="ses_main", project_id="proj1", workspace_id="ws1", parent_id="",
                 slug="fixing-fox", directory="/work/repo", path="/work/repo",
                 title="Fix the login timeout bug", version="0.1.0", agent="build", model=MODEL_JSON,
                 cost=0.42, tokens_input=100, tokens_output=40, tokens_reasoning=5,
                 tokens_cache_read=20, tokens_cache_write=10,
                 time_created=_ms(-3600), time_updated=_ms(-60))
    _session_row(conn, id="ses_sub", project_id="proj1", workspace_id="ws1", parent_id="ses_main",
                 slug="witty-circuit", directory="/work/repo", path="/work/repo",
                 title="Investigate -low/-max 404s (@general subagent)", version="0.1.0",
                 agent="general", model=MODEL_JSON, cost=0.05, tokens_input=10, tokens_output=5,
                 tokens_reasoning=0, tokens_cache_read=0, tokens_cache_write=0,
                 time_created=_ms(-1800), time_updated=_ms(-1700))

    # ses_main: one user turn, one assistant turn carrying every tool kind
    # "time": {"created": ...} mirrors the assistant message's own shape below (which
    # genuinely needs it for time.completed) — parse_opencode()'s ts fallback for a part
    # is `part.get("time_created") or (msg.get("time") or {}).get("created")`, and no
    # part.data in this fixture (or, per the confirmed-schema comment above, the real db)
    # carries a top-level "time_created" key, so a user message missing "time" entirely
    # would leave every request's `t` field permanently "" — silently failing the
    # Z-suffix contract for the *requests* list without a mutant in sight.
    _message(conn, "msg_u1", "ses_main", _ms(-3600),
             {"role": "user", "path": {"cwd": "/work/repo", "root": "/work/repo"},
              "time": {"created": _ms(-3600)}})
    _part(conn, "part_u1", "msg_u1", "ses_main", _ms(-3600),
          {"type": "text", "text": "Fix the login timeout bug in the auth flow"})
    _part(conn, "part_u1_synth", "msg_u1", "ses_main", _ms(-3599),
          {"type": "text", "text": "<system-reminder>ignore this boilerplate</system-reminder>",
           "synthetic": True})

    _message(conn, "msg_a1", "ses_main", _ms(-3500),
             {"role": "assistant", "modelID": "big-pickle", "providerID": "opencode",
              "tokens": {"total": 165, "input": 100, "output": 40, "reasoning": 5,
                         "cache": {"read": 20, "write": 10}},
              "time": {"created": _ms(-3500), "completed": _ms(-60)}, "finish": "tool-calls"})
    _part(conn, "part_narr", "msg_a1", "ses_main", _ms(-3480),
          {"type": "text", "text": "Investigating the auth flow now"})
    _part(conn, "part_bash_ok", "msg_a1", "ses_main", _ms(-3400),
          {"type": "tool", "tool": "bash", "callID": "call_ok",
           "state": {"status": "completed", "input": {"command": "pytest -q"}, "output": "3 passed",
                     "time": {"start": _ms(-3400), "end": _ms(-3395)}}})
    _part(conn, "part_bash_bad", "msg_a1", "ses_main", _ms(-3390),
          {"type": "tool", "tool": "bash", "callID": "call_bad",
           "state": {"status": "error", "input": {"command": "npm test"}, "output": "",
                     "error": "exit code 1", "time": {"start": _ms(-3390), "end": _ms(-3385)}}})
    _part(conn, "part_read", "msg_a1", "ses_main", _ms(-3300),
          {"type": "tool", "tool": "read", "callID": "call_read",
           "state": {"status": "completed", "input": {"filePath": "/work/repo/bar.py"}}})
    _part(conn, "part_write", "msg_a1", "ses_main", _ms(-3200),
          {"type": "tool", "tool": "write", "callID": "call_write",
           "state": {"status": "completed", "input": {"filePath": "/work/repo/new.py"}}})
    _part(conn, "part_edit", "msg_a1", "ses_main", _ms(-3100),
          {"type": "tool", "tool": "edit", "callID": "call_edit",
           "state": {"status": "completed",
                     "input": {"filePath": "/work/repo/app.py",
                               "oldString": "def old():\n    pass",
                               "newString": "def new():\n    return True"}}})
    _part(conn, "part_task", "msg_a1", "ses_main", _ms(-3000),
          {"type": "tool", "tool": "task", "callID": "call_task",
           "state": {"status": "completed",
                     "input": {"description": "survey the auth config",
                               "prompt": "read the provider seam and report back"}}})
    _part(conn, "part_q", "msg_a1", "ses_main", _ms(-2900),
          {"type": "tool", "tool": "question", "callID": "call_q",
           "state": {"status": "completed",
                     "input": {"questions": [{"question": "Which fix approach?", "header": "Approach",
                                               "options": [{"label": "Patch", "description": "quick patch"},
                                                            {"label": "Rewrite", "description": "full rewrite"}]}]}}})

    conn.execute("INSERT INTO todo VALUES (?,?,?,?,?,?,?)",
                 ("ses_main", "Write regression test", "completed", "high", 0, _ms(-3600), _ms(-3000)))
    conn.execute("INSERT INTO todo VALUES (?,?,?,?,?,?,?)",
                 ("ses_main", "Patch the timeout handler", "in_progress", "high", 1, _ms(-3600), _ms(-100)))
    conn.execute("INSERT INTO todo VALUES (?,?,?,?,?,?,?)",
                 ("ses_main", "Update changelog", "pending", "low", 2, _ms(-3600), _ms(-3600)))

    # ses_sub: minimal transcript so it's a real, parseable session
    _message(conn, "msg_u2", "ses_sub", _ms(-1800),
             {"role": "user", "path": {"cwd": "/work/repo"}, "time": {"created": _ms(-1800)}})
    _part(conn, "part_u2", "msg_u2", "ses_sub", _ms(-1800),
          {"type": "text", "text": "Investigate the 404 errors on -low/-max"})

    conn.commit()
    conn.close()


class _OpencodeEnv(unittest.TestCase):
    """Repoint config.OPENCODE_DB at a temp fixture db, late-bound (never imported
    directly), and restore it in tearDown."""

    def setUp(self):
        self._snap = config.OPENCODE_DB
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)   # build_fixture_db creates it fresh via sqlite3.connect
        build_fixture_db(self.db_path)
        config.OPENCODE_DB = self.db_path
        self.provider = OpencodeProvider()
        # mirrors the Auggie idiom (see tests/test_path_traversal_shared_seam.py:60,66,
        # A._AUGGIE_LIST_CACHE.clear() in both setUp and tearDown): every subclass here
        # builds a fresh fixture db per test, but list()'s module-level _LIST_CACHE is
        # keyed by session id and survives across tests unless cleared — without this a
        # later test could read a still-warm entry left behind by an earlier one.
        _oc._LIST_CACHE.clear()

    def tearDown(self):
        config.OPENCODE_DB = self._snap
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        _oc._LIST_CACHE.clear()


# --------------------------------------------------------------------------- available()

class TestAvailable(_OpencodeEnv):

    def test_available_true_with_fixture(self):
        self.assertTrue(self.provider.available())

    def test_available_false_when_db_missing(self):
        config.OPENCODE_DB = os.path.join(tempfile.mkdtemp(), "does-not-exist.db")
        self.assertFalse(OpencodeProvider().available())


# --------------------------------------------------------------------------------- list()

class TestList(_OpencodeEnv):

    def _by_id(self):
        return {it["id"]: it for it in self.provider.list()}

    def test_list_returns_the_exact_key_set(self):
        main = self._by_id()["opencode:ses_main"]
        expected = {"id", "project", "cwd", "title", "prompt", "source", "mtime", "agent",
                    "group", "groupLabel", "parentId", "bg", "first", "waiting", "ended"}
        self.assertEqual(set(main.keys()), expected)

    def test_ids_are_prefixed_and_source_is_opencode(self):
        main = self._by_id()["opencode:ses_main"]
        self.assertEqual(main["id"], "opencode:ses_main")
        self.assertEqual(main["source"], "opencode")

    def test_mtime_is_epoch_seconds_not_milliseconds(self):
        """The easiest bug to ship: opencode stores time_updated in epoch MS; a
        list() that forgets to divide by 1000 would report a mtime ~1000x too large
        (~1.8e12 instead of ~1.8e9 for a 2026 timestamp)."""
        main = self._by_id()["opencode:ses_main"]
        now_s = time.time()
        self.assertGreater(main["mtime"], 1e9, "looks too small to be a plausible unix-seconds value")
        self.assertLess(main["mtime"], 1e11, "looks like epoch MILLISECONDS leaked through unconverted")
        self.assertLess(abs(main["mtime"] - now_s), 3600, "should be close to 'now' given the fixture's offsets")


# ------------------------------------------------------------------ sub-agent vs normal

class TestSubAgentAttribution(_OpencodeEnv):

    def _by_id(self):
        return {it["id"]: it for it in self.provider.list()}

    def test_sub_agent_session_reports_agent_and_parent(self):
        sub = self._by_id()["opencode:ses_sub"]
        self.assertTrue(sub["agent"])
        self.assertEqual(sub["parentId"], "opencode:ses_main")

    def test_normal_session_reports_no_agent_and_empty_parent(self):
        main = self._by_id()["opencode:ses_main"]
        self.assertFalse(main["agent"])
        self.assertEqual(main["parentId"], "")


# -------------------------------------------------------------------------------- parse()

class TestParseDetailContract(_OpencodeEnv):

    def setUp(self):
        super().setUp()
        self.d = self.provider.parse("opencode:ses_main")

    def test_every_contract_key_present(self):
        expected = {"meta", "todos", "files", "reads", "commands", "commits", "tests", "requests",
                    "agents", "agents_bg", "agent_sessions", "shells", "decisions", "waiting", "prs",
                    "narrative", "message", "tokens", "context", "counts", "overview", "mtime",
                    "now", "notes", "push_when"}
        self.assertEqual(set(self.d.keys()), expected)

    def test_meta_carries_source_entrypoint_and_parsed_model(self):
        m = self.d["meta"]
        self.assertEqual(m["source"], "opencode")
        self.assertEqual(m["entrypoint"], "opencode")
        self.assertEqual(m["model"], "big-pickle")     # model column is JSON string -> .id

    def test_todo_statuses_and_shape(self):
        by_content = {t["content"]: t for t in self.d["todos"]}
        self.assertEqual(by_content["Write regression test"]["status"], "completed")
        self.assertEqual(by_content["Patch the timeout handler"]["status"], "in_progress")
        self.assertEqual(by_content["Update changelog"]["status"], "pending")
        for t in self.d["todos"]:
            self.assertIn("activeForm", t)

    def test_bash_error_part_is_not_ok_and_counted_as_an_error(self):
        by_cmd = {c["cmd"]: c for c in self.d["commands"]}
        self.assertTrue(by_cmd["pytest -q"]["ok"])
        self.assertFalse(by_cmd["npm test"]["ok"])
        self.assertEqual(self.d["counts"]["errors"], 1)

    def test_write_counts_as_created_and_edit_counts_as_edited(self):
        c = self.d["counts"]
        self.assertEqual(c["created"], 1)
        self.assertEqual(c["edited"], 1)
        by_path = {f["path"]: f for f in self.d["files"]}
        self.assertTrue(by_path["/work/repo/new.py"]["created"])
        self.assertFalse(by_path["/work/repo/app.py"]["created"])

    def test_read_part_reaches_reads_and_counts(self):
        self.assertTrue(any(r["path"] == "/work/repo/bar.py" for r in self.d["reads"]))
        self.assertEqual(self.d["counts"]["read"], 1)

    def test_task_part_becomes_an_agent_entry(self):
        self.assertEqual(len(self.d["agents"]), 1)
        self.assertEqual(self.d["agents"][0]["desc"], "survey the auth config")
        self.assertEqual(self.d["counts"]["agents"], 1)

    def test_question_part_becomes_a_decision_entry(self):
        self.assertEqual(len(self.d["decisions"]), 1)
        dec = self.d["decisions"][0]
        self.assertEqual(len(dec["questions"]), 1)
        self.assertEqual(dec["questions"][0]["q"], "Which fix approach?")
        self.assertTrue(dec["open"] is False or dec.get("answer"), "status completed -> answered, not open")

    def test_tokens_are_the_session_row_aggregates(self):
        # brief: tokens.in = tokens_input + tokens_cache_read + tokens_cache_write; tokens.out = tokens_output
        self.assertEqual(self.d["tokens"], {"in": 100 + 20 + 10, "out": 40})

    def test_agents_bg_and_shells_are_empty_lists(self):
        self.assertEqual(self.d["agents_bg"], [])
        self.assertEqual(self.d["shells"], [])


# ----------------------------------------------------- (5) the synthetic-text trap

class TestSyntheticTextExcluded(_OpencodeEnv):

    def test_synthetic_part_text_absent_from_narrative_and_requests(self):
        d = self.provider.parse("opencode:ses_main")
        narrative_text = " ".join(n["text"] for n in d["narrative"])
        request_text = " ".join(r["text"] for r in d["requests"])
        self.assertNotIn("ignore this boilerplate", narrative_text)
        self.assertNotIn("ignore this boilerplate", request_text)

    def test_real_text_parts_still_present(self):
        d = self.provider.parse("opencode:ses_main")
        narrative_text = " ".join(n["text"] for n in d["narrative"])
        request_text = " ".join(r["text"] for r in d["requests"])
        self.assertIn("Investigating the auth flow now", narrative_text)
        self.assertIn("Fix the login timeout bug", request_text)


# ---------------------------------------------------------------- (6) honest context

class TestContextWindow(_OpencodeEnv):

    def test_no_fabricated_limit_or_percentage(self):
        d = self.provider.parse("opencode:ses_main")
        self.assertIsNone(d["context"]["limit"])
        self.assertIsNone(d["context"]["pct"])


# --------------------------------------------------------------------------- exists()

class TestExists(_OpencodeEnv):

    def test_exists_true_for_a_real_id(self):
        self.assertTrue(self.provider.exists("opencode:ses_main"))

    def test_exists_false_for_a_bogus_id(self):
        self.assertFalse(self.provider.exists("opencode:ses_nope"))

    def test_parse_returns_none_for_a_bogus_id(self):
        self.assertIsNone(self.provider.parse("opencode:ses_nope"))


# --------------------------------------------------------------- (8) corrupt db safety

class TestCorruptDbNeverSinksRegistry(unittest.TestCase):

    def setUp(self):
        self._snap = config.OPENCODE_DB
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"this is not a sqlite database, just garbage bytes\x00\x01\x02")
        config.OPENCODE_DB = self.db_path

    def tearDown(self):
        config.OPENCODE_DB = self._snap
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_list_returns_empty_list_not_an_exception(self):
        try:
            items = OpencodeProvider().list()
        except Exception as exc:   # noqa: BLE001 — this is exactly the failure mode under test
            self.fail("list() on a corrupt db must not raise (would sink registry.all_sessions()): %r" % exc)
        self.assertEqual(items, [])


# -------------------------------------------------------------------------------- search()

class TestSearch(_OpencodeEnv):

    def test_finds_session_by_title(self):
        hits = self.provider.search("login timeout")
        self.assertIn("opencode:ses_main", [h["id"] for h in hits])

    def test_no_match_returns_empty(self):
        self.assertEqual(self.provider.search("zzz-definitely-not-present-zzz"), [])


# ----------------------------------------------------------------------- drill-downs

class TestDrillDowns(_OpencodeEnv):

    def test_output_returns_bash_output_by_callid_ok(self):
        o = self.provider.output("opencode:ses_main", "call_ok")
        self.assertEqual(o["cmd"], "pytest -q")
        self.assertEqual(o["out"], "3 passed")
        self.assertTrue(o["ok"])

    def test_output_reflects_error_status(self):
        o = self.provider.output("opencode:ses_main", "call_bad")
        self.assertEqual(o["cmd"], "npm test")
        self.assertFalse(o["ok"])

    def test_diff_returns_edit_history_for_a_file_path(self):
        ops = self.provider.diff("opencode:ses_main", "/work/repo/app.py")
        self.assertEqual([op["kind"] for op in ops], ["edited"])
        self.assertIn("-def old", ops[0]["diff"])
        self.assertIn("+def new", ops[0]["diff"])

    def test_diff_of_an_untouched_file_is_empty(self):
        self.assertEqual(self.provider.diff("opencode:ses_main", "/no/such/file.py"), [])


# ---------------------------------------------------------------------------------------
# Everything below closes a verification gap found by mutation testing: an adversarial
# pass proved two mutations to opencode.py survive the entire 840-test suite —
#   M1: _list_state() replaced with `return "", False, False`
#   M3: _iso() drops the trailing "Z" from its ISO timestamps
# — meaning list()'s prompt/waiting/ended values and every emitted timestamp's Z-suffix
# had ZERO coverage. TestList above only ever asserted the list dict's KEY SET, never
# the values behind those keys. The classes below pin the values, and pin two already-
# diagnosed defects in how list() computes and caches them (D1: cache staleness against
# session.time_updated; D2: cache not keyed by db path; D5: "last question wins" instead
# of "any question still open").
# ---------------------------------------------------------------------------------------


# ----------------------------------------------------------- (M1) list() VALUES, not keys

class TestListValuesNotJustKeys(_OpencodeEnv):
    """The M1 mutant (`_list_state` -> `return "", False, False`) sails through every
    existing list() test because none of them look past the key set. These do."""

    def _by_id(self):
        return {it["id"]: it for it in self.provider.list()}

    def test_prompt_is_the_first_non_synthetic_user_text(self):
        # the fixture's user text as-typed, whitespace-normalized by " ".join(t.split())
        # — must not be "" (the M1 mutant's constant).
        main = self._by_id()["opencode:ses_main"]
        self.assertEqual(main["prompt"], "Fix the login timeout bug in the auth flow")

    def test_waiting_is_false_when_the_only_question_is_resolved(self):
        # ses_main's one question part (call_q) has state.status "completed" -> resolved.
        main = self._by_id()["opencode:ses_main"]
        self.assertFalse(main["waiting"])

    def test_ended_is_true_for_a_completed_final_assistant_message(self):
        # ses_main's last message overall is msg_a1 (assistant), whose time.completed is
        # set and whose only question is resolved -> ended must be True, not the M1
        # mutant's constant False.
        main = self._by_id()["opencode:ses_main"]
        self.assertTrue(main["ended"])

    def test_ended_is_false_when_no_assistant_reply_exists_yet(self):
        # ses_sub's only message is the dispatch prompt (role=user) -- no assistant turn
        # has answered it yet, so ended must be False.
        sub = self._by_id()["opencode:ses_sub"]
        self.assertFalse(sub["ended"])


class TestListWaitingTrueWhenQuestionUnresolved(_OpencodeEnv):
    """Flips the base fixture's only question part to unresolved directly in the db
    (no new fixture builder needed) and proves list()'s waiting tracks it. Combined with
    test_waiting_is_false_when_the_only_question_is_resolved above, this pins waiting as
    a real function of question state, not a constant in either direction."""

    def test_waiting_true_when_the_question_is_unresolved(self):
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT data FROM part WHERE id = 'part_q'").fetchone()
            data = json.loads(row[0])
            data["state"]["status"] = "pending"   # was "completed" -> resolved
            conn.execute("UPDATE part SET data = ? WHERE id = 'part_q'", (json.dumps(data),))
            conn.commit()
        finally:
            conn.close()

        main = {it["id"]: it for it in self.provider.list()}["opencode:ses_main"]
        self.assertTrue(main["waiting"])


# ------------------------------------------------------- (D5) ANY-unresolved semantics

class TestListWaitingAnyUnresolvedSemantics(_OpencodeEnv):
    """The bug this pins: an EARLIER question left unresolved, followed by a LATER
    question that got answered, must still report waiting=True -- the human never
    answered q1. A "last question wins" implementation instead reports whatever the
    most-recently-seen question part's status was (False here, since q2 is resolved).

    parse()'s `waiting = any(a["open"] for a in asks.values())` has always used
    ANY-unresolved semantics (asks is a dict keyed by callID, one entry per question,
    so an earlier open one is never overwritten by a later resolved one). list()'s
    _list_state must match it -- this test proves both agree, using the exact shape
    named in the brief: q1 unresolved, q2 (later) resolved.
    """

    def _add_earlier_still_open_question(self):
        # part_q (call_q, resolved, "Which fix approach?") already sits at NOW-2900s in
        # the base fixture -- that is q2. Insert q1: an EARLIER (NOW-2950s) question
        # that is never resolved.
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
                "VALUES (?,?,?,?,?,?)",
                ("part_q0", "msg_a1", "ses_main", _ms(-2950), _ms(-2950),
                 json.dumps({"type": "tool", "tool": "question", "callID": "call_q0",
                             "state": {"status": "pending",
                                       "input": {"questions": [{"question": "Which service first?",
                                                                 "header": "Order"}]}}})))
            conn.commit()
        finally:
            conn.close()

    def test_list_and_parse_waiting_agree_true_when_an_earlier_question_is_still_open(self):
        self._add_earlier_still_open_question()

        list_main = {it["id"]: it for it in self.provider.list()}["opencode:ses_main"]
        parse_waiting = self.provider.parse("opencode:ses_main")["waiting"]

        self.assertTrue(list_main["waiting"],
                         "list() must use ANY-unresolved semantics, not last-question-wins")
        self.assertTrue(parse_waiting)
        self.assertEqual(list_main["waiting"], parse_waiting,
                          "list() and parse() must agree on whether the session is waiting")


# ------------------------------------------- (D1) cache staleness vs. session.time_updated

class TestListCachePicksUpQuestionNewerThanSessionRow(_OpencodeEnv):
    """On the real db, 67 of 77 sessions have part rows newer than their own
    session.time_updated -- so a cache keyed on time_updated alone leaves waiting
    permanently stale for the common case, not an edge case. This inserts a NEW
    unresolved question part with time_created > ses_main's time_updated WITHOUT
    bumping the session row, exactly reproducing that shape, and proves list() still
    notices after the row is already cached.

    This test is expected to FAIL against an implementation that keys _LIST_CACHE
    purely on session.time_updated -- if it fails, the D1 cache fix has not landed yet
    in aitracker/providers/opencode.py; that is a real gap, not a flaky test.
    """

    def test_waiting_flips_true_after_a_late_question_without_a_session_row_bump(self):
        main_before = {it["id"]: it for it in self.provider.list()}["opencode:ses_main"]
        self.assertFalse(main_before["waiting"], "sanity: baseline has no open question")

        conn = sqlite3.connect(self.db_path)
        try:
            tu = conn.execute(
                "SELECT time_updated FROM session WHERE id = 'ses_main'").fetchone()[0]
            self.assertLess(tu, _ms(-10),
                             "fixture assumption: the new part must be newer than the session row")
            # a question part written after session.time_updated's last bump -- the
            # session row itself is never touched, matching the real-db shape.
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
                "VALUES (?,?,?,?,?,?)",
                ("part_q_late", "msg_a1", "ses_main", _ms(-10), _ms(-10),
                 json.dumps({"type": "tool", "tool": "question", "callID": "call_q_late",
                             "state": {"status": "pending",
                                       "input": {"questions": [{"question": "Retry now?",
                                                                 "header": "Retry"}]}}})))
            conn.commit()
        finally:
            conn.close()

        main_after = {it["id"]: it for it in self.provider.list()}["opencode:ses_main"]
        self.assertTrue(
            main_after["waiting"],
            "a question written after time_updated's last bump must not stay hidden behind "
            "a cache entry keyed only on that column")


# --------------------------------------------------------- (D2) cache keyed by db path too

class TestListCacheKeyedByDbPath(unittest.TestCase):
    """Two different temp dbs, each built by the same build_fixture_db(), so ses_main's
    id and time_updated are bit-for-bit identical in both -- but db B's first user
    prompt is patched to differ. A cache keyed only on session id (no db-path
    component) would let listing db B return db A's cached prompt the instant they
    share a session id and time_updated. This proves each db's list() reflects its OWN
    data, not a memoized value grabbed while a different db was active.

    This test is expected to FAIL against a _LIST_CACHE keyed on sid alone (no db-path
    component); if it fails, the D2 cache fix has not landed yet -- a real gap, not a
    flaky test.
    """

    def setUp(self):
        self._snap = config.OPENCODE_DB

        fd_a, self.db_a = tempfile.mkstemp(suffix=".db")
        os.close(fd_a)
        os.unlink(self.db_a)
        build_fixture_db(self.db_a)

        fd_b, self.db_b = tempfile.mkstemp(suffix=".db")
        os.close(fd_b)
        os.unlink(self.db_b)
        build_fixture_db(self.db_b)
        # same session id, same time_updated (both built from the same NOW_MS), but a
        # different first-user-prompt -- patched directly, no second fixture builder.
        conn = sqlite3.connect(self.db_b)
        try:
            row = conn.execute("SELECT data FROM part WHERE id = 'part_u1'").fetchone()
            data = json.loads(row[0])
            data["text"] = "Investigate the flaky checkout webhook"
            conn.execute("UPDATE part SET data = ? WHERE id = 'part_u1'", (json.dumps(data),))
            conn.commit()
        finally:
            conn.close()
        _oc._LIST_CACHE.clear()

    def tearDown(self):
        config.OPENCODE_DB = self._snap
        for p in (self.db_a, self.db_b):
            if os.path.exists(p):
                os.unlink(p)
        _oc._LIST_CACHE.clear()

    def test_prompt_reflects_the_active_db_not_a_cache_hit_from_the_other_db(self):
        config.OPENCODE_DB = self.db_a
        prompt_a = {it["id"]: it for it in OpencodeProvider().list()}["opencode:ses_main"]["prompt"]
        self.assertEqual(prompt_a, "Fix the login timeout bug in the auth flow")

        config.OPENCODE_DB = self.db_b
        prompt_b = {it["id"]: it for it in OpencodeProvider().list()}["opencode:ses_main"]["prompt"]
        self.assertEqual(prompt_b, "Investigate the flaky checkout webhook",
                          "db B's own prompt, not db A's cached one -- the cache key must "
                          "include the db path, not just the session id")


# ----------------------------------------------- (M3) every emitted stamp keeps its "Z"

_ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class TestTimestampsCarryTrailingZ(_OpencodeEnv):
    """WHY the Z matters: the SPA feeds every `t` straight to JS Date.parse(), which
    reads a bare "...T08:52:53" (no trailing Z / offset) as LOCAL time, not UTC. Drop
    the Z and every "N minutes/hours ago" label silently skews by the machine's UTC
    offset -- wrong by hours on any machine that isn't itself UTC. Claude's and
    Auggie's logs both hand the shared shape UTC stamps ending in "Z"; opencode's
    _iso() carries a five-line docstring about exactly this trap, and the M3 mutation
    (drop the trailing "Z") passed the entire 840-test suite -- nothing enforced it.
    This asserts the full ISO-with-Z shape across every list the brief named: narrative,
    requests, commands, reads, files (its `last` field, not `t`), agents, and decisions.
    """

    def test_every_emitted_timestamp_ends_in_z(self):
        d = self.provider.parse("opencode:ses_main")
        by_list = {
            "narrative": [n["t"] for n in d["narrative"]],
            "requests": [r["t"] for r in d["requests"]],
            "commands": [c["t"] for c in d["commands"]],
            "reads": [r["t"] for r in d["reads"]],
            "files": [f["last"] for f in d["files"]],
            "agents": [a["t"] for a in d["agents"]],
            "decisions": [dec["t"] for dec in d["decisions"]],
        }
        for name, stamps in by_list.items():
            self.assertTrue(stamps, "fixture must actually exercise the %r list" % name)
            for t in stamps:
                self.assertRegex(
                    t, _ISO_Z_RE,
                    "%s timestamp %r must keep the trailing Z (drop it and Date.parse "
                    "reads the stamp as LOCAL time in the SPA)" % (name, t))


if __name__ == "__main__":
    unittest.main()
