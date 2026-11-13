"""The summary headline on the session LIST rows (/api/list -> board tiles, both rails): the same
overview.headline() policy as the detail header, built from cheap per-row facts (one job index per
list call + the cached tail narration) at the registry seam, for both providers."""
import datetime
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker import config, overview, registry
from aitracker.providers import auggie as A
from aitracker.providers import claude as C
from tests.test_job_headline import _Base, _write, SID, SHORT
from tests.test_jobs_waiting import _write_roster
from tests.test_cr_routes import _ServerCase

NEEDS = "provide a username for the account"


def row(sid=SID):
    return {r["id"]: r for r in registry.all_sessions()}[sid]


class ListHeadlineTests(_Base):
    def test_job_row_summary_live(self):
        self.transcript()
        self.job(state="working", tempo="active", detail="Running the gate")
        h = row()["headline"]
        self.assertEqual((h["source"], h["text"], h["label"], h["band"]), ("job", "Running the gate", "Working", "working"))

    def test_dead_blocked_job_row_keeps_text_drops_pill(self):
        _write_roster(self.roster, [])
        self.transcript()
        self.job(state="blocked", tempo="blocked", detail="Waiting on review")
        h = row()["headline"]
        self.assertEqual((h["source"], h["text"], h["label"], h["band"]), ("job", "Waiting on review", None, None))

    def test_dead_done_job_keeps_completed(self):
        _write_roster(self.roster, [])
        self.transcript()
        self.job(state="done", detail="All shipped")
        self.assertEqual(row()["headline"]["label"], "Completed")
        self.job(state="failed", detail="All shipped")
        self.assertEqual(row()["headline"]["label"], "Completed · failed")

    def test_resume_session_id_row(self):
        self.transcript()
        self.job(short="zzzz9999", sessionId="other-sid", resumeSessionId=SID, state="working", tempo="active", detail="resumed job")
        self.assertEqual(row()["headline"]["text"], "resumed job")

    def test_prefix_collision_not_borrowed(self):
        self.transcript()
        self.job(sessionId="abcd1234-stranger", state="working", tempo="active", detail="not mine")
        h = row()["headline"]
        self.assertEqual((h["source"], h["text"]), ("narration", "narrated words"))

    def test_index_agrees_with_job_for(self):
        live = {SHORT, "aaaa0001", "zzzz9999"}
        self.job(state="working", tempo="active", detail="direct")
        self.job(short="aaaa0001", sessionId="sid-resume-x", resumeSessionId="sid-r2", state="blocked", tempo="blocked", detail="d2")
        self.job(short="bbbb0002", sessionId="abcd1234-collide", state="done", detail="collider")
        self.job(short="cccc0003", sessionId="sid-dup", state="working", tempo="active", detail="first")
        self.job(short="dddd0004", sessionId="sid-dup", state="done", detail="second")
        idx = C.job_index(live)
        for sid in (SID, "sid-resume-x", "sid-r2", "abcd1234-collide", "sid-dup", "nope"):
            self.assertEqual(idx.get(sid), C.job_for(sid, live), sid)
        self.assertIsNone(idx.get("nope"))

    def test_one_listdir_per_list_call(self):
        for i in range(3):
            self.transcript(sid="plain%d-0000-4000-8000-00000000000%d" % (i, i))
        real = os.listdir
        with mock.patch.object(C.os, "listdir", wraps=real) as m:
            C.list_sessions()
        n = sum(1 for c in m.call_args_list if c.args and c.args[0] == config.JOBS_DIR)
        self.assertEqual(n, 1)

    def test_job_detail_clipped(self):
        self.transcript()
        self.job(state="working", tempo="active", detail="word " * 100)
        t = row()["headline"]["text"]
        self.assertEqual(len(t), 200)
        self.assertTrue(t.endswith("…"))

    def test_narration_flattened(self):
        self.transcript(narration="line one\nline two")
        h = row()["headline"]
        self.assertEqual(h["source"], "narration")
        self.assertNotIn("\n", h["text"])
        self.assertLessEqual(len(h["text"]), 200)
        self.assertIsNone(h["label"])

    def test_no_narration_row_is_null(self):
        self.transcript(narration="")
        self.assertIsNone(row()["headline"])

    def test_narration_mode_ignores_job(self):
        self.transcript()
        self.job(state="working", tempo="active", detail="job words")
        config.HEADER_LINE = "narration"
        h = row()["headline"]
        self.assertEqual((h["source"], h["text"], h["label"]), ("narration", "narrated words", None))

    def test_list_headline_pure_none(self):
        self.assertIsNone(overview.list_headline({}, "summary"))

    def test_raw_inputs_not_on_wire(self):
        self.transcript()
        self.job(state="working", tempo="active", detail="x")
        for r in registry.all_sessions():
            self.assertNotIn("job", r)
            self.assertNotIn("last_text", r)

    def test_list_and_detail_agree_on_job_row(self):
        self.transcript()
        self.job(state="working", tempo="active", detail="Running the gate")
        a, b = row()["headline"], registry.parse_any(SID)["headline"]
        for k in ("label", "band", "state", "text", "source"):
            self.assertEqual(a[k], b[k], k)

    def test_covers_needs(self):
        self.transcript()
        self.job(state="blocked", tempo="blocked", detail=NEEDS, needs=NEEDS)
        self.assertIs(row()["headline"]["covers_needs"], True)
        self.job(state="blocked", tempo="blocked", detail="Reviewing the patch", needs=NEEDS)
        self.assertIs(row()["headline"]["covers_needs"], False)
        self.job(state="blocked", tempo="blocked", needs=NEEDS)      # needs-only: the headline IS the question
        r = row()
        self.assertIs(r["headline"]["covers_needs"], True)
        self.assertIn(NEEDS[:20], r["needs"])


class DedupeTests(_Base):
    def test_live_narration_now_line_blanked_on_wire(self):
        sid = "plainnar-0000-4000-8000-000000000009"
        self.transcript(sid=sid)
        with open(os.path.join(self.pdir, "-p", sid + ".jsonl"), "a") as fh:     # mid-turn: not "ended"
            fh.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "x"}}]}}) + "\n")
        self.assertNotEqual({r["id"]: r for r in C.list_sessions()}[sid]["now_line"], "")
        self.assertEqual(row(sid)["now_line"], "")
        self.assertEqual(row(sid)["headline"]["text"], "narrated words")

    def test_live_bg_now_line_kept(self):
        sid = "bgrow000-0000-4000-8000-000000000008"
        self.transcript(sid=sid)
        adir = os.path.join(self.pdir, "-p", sid, "subagents")
        os.makedirs(adir)
        _write(os.path.join(adir, "agent-bg1.jsonl"), [
            {"type": "user", "message": {"role": "user", "content": "fix"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a1", "name": "Bash", "input": {"command": "x"}}]}}])
        r = row(sid)
        self.assertTrue(r["now_line"].startswith("⚙"), r["now_line"])
        self.assertIsNotNone(r["headline"])


class AuggieListHeadlineTests(unittest.TestCase):
    def setUp(self):
        keys = ("AUGMENT_DIR", "AUGGIE_SESSIONS", "TITLES_FILE", "NOTES_FILE", "TASKS_DIR", "PROJECTS")
        snap = [getattr(config, k) for k in keys]
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.PROJECTS = tempfile.mkdtemp()
        config.TITLES_FILE, config.NOTES_FILE = tempfile.mktemp(suffix=".json"), tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        A._AUGGIE_LIST_CACHE.clear()

        def restore():
            for p in (config.AUGMENT_DIR, config.TASKS_DIR, config.PROJECTS):
                shutil.rmtree(p, True)
            for k, v in zip(keys, snap):
                setattr(config, k, v)
            A._AUGGIE_LIST_CACHE.clear()
        self.addCleanup(restore)

    def _write(self, gid="h1"):
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(os.path.join(config.AUGGIE_SESSIONS, gid + ".json"), "w") as fh:
            json.dump({"sessionId": gid, "modified": now, "chatHistory": [
                {"finishedAt": now, "exchange": {"request_message": "hi", "response_text": "auggie says"}},
                {"finishedAt": now, "exchange": {"request_message": "and more", "response_text": ""}}]}, fh)

    def test_auggie_row_narration(self):
        self._write()
        r = {x["id"]: x for x in registry.all_sessions()}["auggie:h1"]
        self.assertEqual((r["headline"]["source"], r["headline"]["text"], r["headline"]["band"]), ("narration", "auggie says", None))
        self.assertNotIn("last_text", r)

    def test_auggie_now_line_dedupe(self):
        self._write()
        r = {x["id"]: x for x in registry.all_sessions()}["auggie:h1"]
        self.assertEqual(r["now_line"], "")
        self.assertEqual({x["id"]: x for x in A.list_auggie()}["auggie:h1"]["now_line"], "auggie says")


class ListHeadlineHttpTests(_ServerCase):
    def test_http_list_headline_and_live_flip(self):
        jdir, rdir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, jdir, True)
        self.addCleanup(shutil.rmtree, rdir, True)
        keys = ("JOBS_DIR", "DAEMON_ROSTER", "HEADER_LINE")
        snap = [getattr(config, k) for k in keys]
        self.addCleanup(lambda: [setattr(config, k, v) for k, v in zip(keys, snap)])
        config.JOBS_DIR, config.DAEMON_ROSTER = jdir, os.path.join(rdir, "roster.json")
        _write_roster(config.DAEMON_ROSTER, ["jobsess1"])
        os.makedirs(os.path.join(jdir, "jobsess1"))
        with open(os.path.join(jdir, "jobsess1", "state.json"), "w") as fh:
            json.dump({"sessionId": "jobsess1-http", "state": "working", "tempo": "active", "detail": "Running the gate"}, fh)
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        _write(os.path.join(config.PROJECTS, "proj", "jobsess1-http.jsonl"), [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "narr words"}]}}])

        def hl():
            st, rows = self._get_json("/api/list")
            self.assertEqual(st, 200)
            return {r["id"]: r for r in rows}["jobsess1-http"]
        r = hl()
        self.assertEqual((r["headline"]["source"], r["headline"]["text"], r["headline"]["label"]), ("job", "Running the gate", "Working"))
        self.assertNotIn("job", r)
        st, _ = self._post("/api/config", {"key": "HEADER_LINE", "value": "narration"})
        self.assertEqual(st, 200)
        h = hl()["headline"]
        self.assertEqual((h["source"], h["text"]), ("narration", "narr words"))


if __name__ == "__main__":
    unittest.main()
