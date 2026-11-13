"""The detail header's one line: a background job's own summary (~/.claude/jobs/<sid8>/state.json)
by default, the latest narration otherwise -- config HEADER_LINE, both providers, via the seam."""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config, overview, registry
from aitracker.providers import auggie as A
from aitracker.providers import claude as C
from tests.test_jobs_waiting import _write_roster
from tests.test_cr_routes import _ServerCase, _empty_env

SID = "abcd1234-0000-4000-8000-000000000001"
SHORT = SID[:8]


def _write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


class _Base(unittest.TestCase):
    def setUp(self):
        self._snap = (config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER, config.HEADER_LINE)
        self.pdir, self.jdir, self.rdir = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        self.roster = os.path.join(self.rdir, "roster.json")
        config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER = self.pdir, self.jdir, self.roster
        config.HEADER_LINE = "summary"
        _write_roster(self.roster, [SHORT])
        os.makedirs(os.path.join(self.pdir, "-p"))
        self.addCleanup(self._restore)

    def _restore(self):
        config.PROJECTS, config.JOBS_DIR, config.DAEMON_ROSTER, config.HEADER_LINE = self._snap
        for d in (self.pdir, self.jdir, self.rdir):
            shutil.rmtree(d, True)

    def transcript(self, sid=SID, narration="narrated words"):
        rows = [{"type": "user", "cwd": "/p", "message": {"role": "user", "content": "go"}}]
        if narration:
            rows.append({"type": "assistant", "timestamp": "2026-11-13T10:00:00Z",
                         "message": {"content": [{"type": "text", "text": narration}]}})
        _write(os.path.join(self.pdir, "-p", sid + ".jsonl"), rows)

    def job(self, short=SHORT, **st):
        os.makedirs(os.path.join(self.jdir, short), exist_ok=True)
        st.setdefault("sessionId", SID)
        with open(os.path.join(self.jdir, short, "state.json"), "w") as fh:
            json.dump(st, fh)

    def head(self, sid=SID):
        return registry.parse_any(sid)["headline"]


class ConfigTests(unittest.TestCase):
    def test_default_mode_is_summary(self):
        self.assertEqual(config.resolve_header_line({}), "summary")
        self.assertEqual(config.resolve_header_line({"HEADER_LINE": "prompt"}), "summary")
        self.assertEqual(config.resolve_header_line({"HEADER_LINE": "narration"}), "narration")
        self.assertEqual(config.HEADER_LINE, "summary")
        self.assertIn("HEADER_LINE", config.EDITABLE)
        self.assertNotIn("HEADER_LINE", config.RESTART_REQUIRED)
        ok, _ = config.VALIDATORS["HEADER_LINE"]("prompt")
        self.assertFalse(ok)
        self.assertTrue(config.VALIDATORS["HEADER_LINE"]("narration")[0])


class HeadlineTests(_Base):
    def test_summary_from_job_detail_direct_dir(self):
        self.transcript()
        self.job(state="blocked", tempo="blocked", detail="Waiting on a pick", needs="A or B")
        h = self.head()
        self.assertEqual((h["source"], h["text"], h["mode"]), ("job", "Waiting on a pick", "summary"))
        self.assertEqual((h["band"], h["label"]), ("blocked", "Needs input"))

    def test_job_found_via_resume_session_id(self):
        self.transcript(sid="resumed-id-9999")
        self.job(short="zzzz9999", sessionId=SID, resumeSessionId="resumed-id-9999", state="done",
                 tempo="idle", detail="Shipped it")
        h = self.head("resumed-id-9999")
        self.assertEqual((h["source"], h["text"], h["label"]), ("job", "Shipped it", "Completed"))

    def test_prefix_collision_not_borrowed(self):
        self.transcript()
        self.job(state="done", sessionId="abcd1234-ffff-4000-8000-999999999999", detail="a stranger")
        self.assertIsNone(registry.parse_any(SID)["job"])
        self.assertEqual(self.head()["source"], "narration")

    def test_band_mapping_each_state(self):
        self.transcript()
        cases = (("done", "idle", "done", "Completed"), ("failed", "idle", "done", "Completed · failed"),
                 ("stopped", "idle", "done", "Completed · stopped"), ("done", "active", "working", "Working"),
                 ("blocked", "blocked", "blocked", "Needs input"), ("working", "blocked", "blocked", "Needs input"),
                 ("blocked", "idle", "working", "Working"), ("working", "active", "working", "Working"))
        for state, tempo, band, label in cases:
            self.job(state=state, tempo=tempo, detail="x")
            h = self.head()
            self.assertEqual((h["band"], h["label"]), (band, label), (state, tempo))
            self.assertNotEqual(h["band"], "review")

    def test_dead_blocked_job_keeps_text_drops_pill(self):
        self.transcript()
        self.job(state="blocked", tempo="blocked", detail="stale ask")
        _write_roster(self.roster, [])
        h = self.head()
        self.assertEqual((h["text"], h["label"], h["band"]), ("stale ask", None, None))
        self.assertEqual(registry.parse_any(SID)["job"]["state"], "blocked")
        _write_roster(self.roster, [SHORT])
        self.assertEqual(self.head()["label"], "Needs input")
        self.job(state="done", tempo="idle", detail="old")
        _write_roster(self.roster, [])
        self.assertEqual(self.head()["label"], "Completed")

    def test_missing_job_file_falls_back_to_narration(self):
        self.transcript()
        self.assertEqual(self.head()["source"], "narration")
        os.makedirs(os.path.join(self.jdir, SHORT, "tmp"))
        h = self.head()
        self.assertEqual((h["source"], h["text"]), ("narration", "narrated words"))

    def test_malformed_state_json_falls_back(self):
        self.transcript()
        os.makedirs(os.path.join(self.jdir, SHORT))
        p = os.path.join(self.jdir, SHORT, "state.json")
        for body in ("{not json", "[1, 2]", json.dumps({"sessionId": SID, "detail": 42, "state": "done"})):
            with open(p, "w") as fh:
                fh.write(body)
            self.assertEqual(self.head()["source"], "narration", body)

    def test_empty_detail_uses_needs_then_result(self):
        self.transcript()
        self.job(state="blocked", tempo="blocked", detail="", needs="pick one", output={"result": "r"})
        self.assertEqual(self.head()["text"], "pick one")
        self.job(state="done", tempo="idle", detail="", output={"result": "final result"})
        self.assertEqual(self.head()["text"], "final result")
        self.job(state="done", tempo="idle", detail="")
        self.assertEqual(self.head()["source"], "narration")

    def test_narration_mode_ignores_job(self):
        self.transcript()
        self.job(state="done", tempo="idle", detail="job words")
        config.HEADER_LINE = "narration"
        h = self.head()
        self.assertEqual((h["mode"], h["source"], h["text"], h["label"]), ("narration", "narration", "narrated words", None))

    def test_no_narration_source_none(self):
        self.transcript(narration="")
        h = self.head()
        self.assertEqual((h["source"], h["text"]), ("none", ""))

    def test_headline_pure_function(self):
        d = {"job": None, "narrative": [{"text": "newest", "t": "T"}, {"text": "older"}], "message": "m"}
        self.assertEqual(overview.headline(d, "summary")["text"], "newest")


class AuggieHeadlineTests(unittest.TestCase):
    def test_auggie_headline_is_narration(self):
        snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.TITLES_FILE, config.NOTES_FILE = tempfile.mktemp(suffix=".json"), tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        A._AUGGIE_LIST_CACHE.clear()

        def restore():
            for p in (config.AUGMENT_DIR, config.TASKS_DIR):
                shutil.rmtree(p, True)
            (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR) = snap
            A._AUGGIE_LIST_CACHE.clear()
        self.addCleanup(restore)
        with open(os.path.join(config.AUGGIE_SESSIONS, "h1.json"), "w") as fh:
            json.dump({"sessionId": "h1", "modified": "2026-06-27T05:48:03Z", "chatHistory": [
                {"finishedAt": "2026-06-27T05:47:50Z", "exchange": {"request_message": "hi", "response_text": "auggie says"}}]}, fh)
        d = registry.parse_any("auggie:h1")
        self.assertIsNone(d["job"])
        self.assertEqual((d["headline"]["source"], d["headline"]["text"]), ("narration", "auggie says"))


class ConfigRoundtripTests(_ServerCase):
    def test_config_post_roundtrip(self):
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        _write(os.path.join(config.PROJECTS, "proj", "rt1.jsonl"), [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "narr"}]}}])
        st, j = self._get_json("/api/session?id=rt1")
        self.assertEqual((st, j["headline"]["mode"]), (200, "summary"))
        st, _ = self._post("/api/config", {"key": "HEADER_LINE", "value": "narration"})
        self.assertEqual(st, 200)
        self.assertEqual(self._get_json("/api/session?id=rt1")[1]["headline"]["mode"], "narration")
        st, _ = self._post("/api/config", {"key": "HEADER_LINE", "value": "prompt"})
        self.assertEqual(st, 400)

    def test_http_job_session_and_served_page(self):
        """End to end over HTTP: a job session carries headline(job) + cost; the served page has the new UI."""
        jdir, rdir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, jdir, True)
        self.addCleanup(shutil.rmtree, rdir, True)
        snap = (config.JOBS_DIR, config.DAEMON_ROSTER)
        self.addCleanup(lambda: (setattr(config, "JOBS_DIR", snap[0]), setattr(config, "DAEMON_ROSTER", snap[1])))
        config.JOBS_DIR, config.DAEMON_ROSTER = jdir, os.path.join(rdir, "roster.json")
        _write_roster(config.DAEMON_ROSTER, ["jobsess1"])
        os.makedirs(os.path.join(jdir, "jobsess1"))
        with open(os.path.join(jdir, "jobsess1", "state.json"), "w") as fh:
            json.dump({"sessionId": "jobsess1-http", "state": "working", "tempo": "active", "detail": "Running the gate"}, fh)
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        _write(os.path.join(config.PROJECTS, "proj", "jobsess1-http.jsonl"), [
            {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "message": {"model": "claude-opus-5-5", "id": "m1",
                                              "usage": {"input_tokens": 1000000, "output_tokens": 0},
                                              "content": [{"type": "text", "text": "narr"}]}}])
        st, j = self._get_json("/api/session?id=jobsess1-http")
        self.assertEqual(st, 200)
        self.assertEqual((j["headline"]["source"], j["headline"]["text"], j["headline"]["label"]),
                         ("job", "Running the gate", "Working"))
        self.assertAlmostEqual(j["cost"]["total_usd"], 4.0)
        st, body = self._get("/")
        page = body.decode()
        for needle in ("openCostModal", "hasDraftQuote", "paintGoalLine", 'data-act', "ov_hlrow"):
            self.assertIn(needle, page)
        self.assertNotRegex(page, r"location\.hostname[^;\n]*(openCostModal|paintGoalLine|hasDraftQuote)")


if __name__ == "__main__":
    unittest.main()
