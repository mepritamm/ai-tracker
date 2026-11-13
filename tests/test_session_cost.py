"""Session cost ($ burned, cache savings, agents $): util pricing + Claude recompute + the
Claude Code `cost-state` line + Auggie's billed cost + the registry seam defaults."""
import json
import os
import shutil
import tempfile
import unittest

from aitracker import config, registry, util
from aitracker.providers import auggie as A
from aitracker.providers import claude as C


def _write(path, rows):
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _u(i=0, o=0, rd=0, w5=0, w1=0, cc=None):
    u = {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": rd,
         "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}
    if cc is not None:
        u["cache_creation_input_tokens"] = cc
    return u


def _priced(model, u, speed=None):
    acc = {}
    util.cost_add(acc, model, u, speed)
    return acc


class PriceTests(unittest.TestCase):
    def test_price_table_matches_cli_cost_state(self):
        """Rows copied from real `cost-state.modelUsage` records: Claude Code's own costUSD."""
        for model, i, o, rd, w1, want in (
                ("claude-opus-5-5", 4465, 321099, 74318753, 1305144, 31.7447426),
                ("claude-sonnet-5-5", 462, 104141, 38375246, 608536, 7.3140026),
                ("claude-opus-5-5", 1598, 45779, 6517904, 226002, 4.0335688)):
            acc = _priced(model, _u(i=i, o=o, rd=rd, w1=w1))
            self.assertAlmostEqual(acc[model][5], want, places=6, msg=model)

    def test_cache_creation_breakdown_wins_and_top_level_fallback(self):
        self.assertEqual(util.cost_usage(_u(cc=0, w1=9780)), (0, 0, 9780, 0, 0))
        self.assertEqual(util.cost_usage({"cache_creation_input_tokens": 500,
                                          "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                                             "ephemeral_1h_input_tokens": 0}}), (0, 500, 0, 0, 0))

    def test_cache_savings_gross_premium_net(self):
        acc = _priced("claude-opus-5-5", _u(rd=1000000, w5=1000000, w1=1000000))
        c = util.cost_summary(acc, {}, [])["cache"]
        self.assertEqual(c["read_tokens"], 1000000)
        self.assertAlmostEqual(c["saved_gross_usd"], 3.8)          # 1M * (4 - 0.20)
        self.assertAlmostEqual(c["write_premium_usd"], 5.0)        # (5-4) + (8-4)
        self.assertAlmostEqual(c["saved_net_usd"], -1.2)

    def test_haiku55_long_prompt_tier_per_request(self):
        m = "claude-haiku-5-5"
        a, b = _priced(m, _u(i=99999)), _priced(m, _u(i=100001))
        self.assertAlmostEqual(a[m][5], 99999 * 0.10 / 1e6)
        self.assertAlmostEqual(b[m][5], 100001 * 0.50 / 1e6)
        self.assertEqual((a[m][6], b[m][6]), (0, 1))

    def test_unknown_and_openrouter_models_flagged_unpriced(self):
        acc = {}
        util.cost_add(acc, "claude-opus-5-5", _u(i=1000000))
        util.cost_add(acc, "claude-fable-9-9", _u(i=10, o=5))
        util.cost_add(acc, "openai/gpt-6-luna", _u(i=7))
        util.cost_add(acc, "claude-opus-5-5", _u(i=10), speed="fast")
        s = util.cost_summary(acc, {}, [])
        self.assertAlmostEqual(s["total_usd"], 4.0)               # only the priced part
        self.assertEqual({u["model"] for u in s["unpriced"]},
                         {"claude-fable-9-9", "openai/gpt-6-luna", "claude-opus-5-5 (fast)"})
        self.assertTrue(all(r["usd"] is None for r in s["models"] if r["model"] != "claude-opus-5-5"))

    def test_synthetic_model_skipped(self):
        acc = {}
        util.cost_add(acc, "<synthetic>", _u(i=5))
        util.cost_add(acc, "", _u(i=5))
        self.assertEqual(acc, {})
        self.assertIsNone(util.cost_summary(acc, {}, [])["total_usd"])


def _asst(mid, usage, model="claude-opus-5-5"):
    m = {"id": mid, "model": model, "content": [{"type": "text", "text": "x"}], "usage": usage}
    if mid is None:
        del m["id"]
    return {"type": "assistant", "message": m}


class ClaudeCostTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.main = os.path.join(self.d, "sess1.jsonl")

    def rows(self, *more):
        return [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}] + list(more)

    def test_cost_last_usage_per_message_id_wins(self):
        _write(self.main, self.rows(
            _asst("m1", {"input_tokens": 10, "output_tokens": 1}),
            _asst("m1", {"input_tokens": 10, "output_tokens": 120}),
            _asst("m1", {"input_tokens": 10, "output_tokens": 287}),
            _asst(None, {"input_tokens": 0, "output_tokens": 100})))
        d = C.parse_session(self.main)
        row = d["cost"]["models"][0]
        self.assertEqual((row["in"], row["out"]), (10, 387))       # 287 (last wins) + the id-less line
        self.assertEqual(d["tokens"]["out"], 101)                   # existing count keeps first-seen (1 + 100)

    def test_cost_state_reported_only_when_after_last_usage(self):
        cs = lambda usd, unk=False: {"type": "cost-state", "sessionId": "s", "totalCostUSD": usd,
                                     "hasUnknownModelCost": unk}
        u = {"input_tokens": 1000000, "output_tokens": 0}
        _write(self.main, self.rows(_asst("m1", u), cs(1.5), cs(12.2, True)))
        c = C.parse_session(self.main)["cost"]
        self.assertEqual((c["reported_usd"], c["reported_unknown"]), (12.2, True))   # last, never summed
        self.assertAlmostEqual(c["total_usd"], 4.0)
        _write(self.main, self.rows(_asst("m1", u), cs(12.2), _asst("m2", u)))
        self.assertIsNone(C.parse_session(self.main)["cost"]["reported_usd"])

    def test_agents_cost_split_and_rows(self):
        _write(self.main, self.rows(_asst("m1", {"input_tokens": 1000000, "output_tokens": 0})))
        adir = os.path.join(self.d, "sess1", "subagents")
        os.makedirs(adir)
        _write(os.path.join(adir, "agent-x.jsonl"), [
            {"type": "user", "message": {"role": "user", "content": "task x"}},
            _asst("a1", {"input_tokens": 500000, "output_tokens": 0}, model="claude-sonnet-5-5")])
        d1 = C.parse_session(self.main)
        c = d1["cost"]
        self.assertAlmostEqual(c["main_usd"], 4.0)
        self.assertAlmostEqual(c["agents_usd"], 1.0)
        self.assertAlmostEqual(c["total_usd"], 5.0)
        self.assertEqual(len(c["agents"]), 1)
        self.assertAlmostEqual(c["agents"][0]["usd"], 1.0)
        self.assertEqual({r["who"] for r in c["models"]}, {"main", "agents"})
        self.assertTrue(all("cost_usd" not in r for r in d1["agents_bg"]))
        self.assertEqual(C.parse_session(self.main)["cost"], c)     # second call: cached passes, same answer


class AuggieCostTests(unittest.TestCase):
    def setUp(self):
        self._snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        config.TASKS_DIR = tempfile.mkdtemp()
        A._AUGGIE_LIST_CACHE.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        for p in (config.AUGMENT_DIR, config.TASKS_DIR):
            shutil.rmtree(p, True)
        (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR) = self._snap
        A._AUGGIE_LIST_CACHE.clear()

    def session(self, cost="1.832267125", sub=1.72737669):
        d = {"sessionId": "c1", "modified": "2026-06-27T05:48:03Z", "chatHistory": [
            {"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
                "request_message": "hi", "response_text": "ok", "model_id": "claude-opus-4-7-500k",
                "response_nodes": [
                    {"token_usage": {"input_tokens": 100, "output_tokens": 50,
                                     "cache_read_input_tokens": 1000000, "cache_creation_input_tokens": 0}},
                    {"billing_metadata": {"cost_usd": cost}}]}}]}
        if sub is not None:
            d["subAgentCostUsd"] = sub
        with open(os.path.join(config.AUGGIE_SESSIONS, "c1.json"), "w") as fh:
            json.dump(d, fh)
        A._AUGGIE_LIST_CACHE.clear()

    def test_auggie_recorded_cost_and_subagents(self):
        self.session()
        c = A.parse_auggie("c1")["cost"]
        self.assertEqual(c["basis"], "Billed by Augment, USD")
        self.assertEqual((c["main_usd"], c["agents_usd"], c["total_usd"]), (1.8323, 1.7274, 3.5596))
        self.assertGreater(c["cache"]["saved_gross_usd"], 0)        # via the -500k alias
        self.assertEqual(c["models"][0]["read"], 1000000)
        self.assertIn("Billed by Augment", c["note"])

    def test_auggie_bad_cost_string_skipped(self):
        self.session(cost="n/a", sub=None)
        c = A.parse_auggie("c1")["cost"]
        self.assertEqual((c["main_usd"], c["agents_usd"], c["total_usd"]), (0.0, 0.0, 0.0))


class SeamTests(unittest.TestCase):
    def test_seam_default_cost_for_providers_without_usage(self):
        from tests.test_augment_ext import _mk_workspace
        snap = config.VSCODE_WS_ROOT
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()
        self.addCleanup(setattr, config, "VSCODE_WS_ROOT", snap)
        self.addCleanup(shutil.rmtree, config.VSCODE_WS_ROOT, True)
        _mk_workspace(config.VSCODE_WS_ROOT, "wshash1", "file:///Users/me/proj",
                      tasks=[{"uuid": "root", "name": "Current Task List", "state": "NOT_STARTED", "subTasks": []}])
        d = registry.parse_any("augment-vscode:wshash1:root")
        self.assertIsNotNone(d)
        self.assertIsNone(d["cost"]["total_usd"])
        self.assertIn("No per-turn usage", d["cost"]["note"])
        self.assertIsNone(d["job"])
        self.assertEqual(d["headline"]["mode"], config.HEADER_LINE)

    def test_continued_session_cost_note(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        snap = (config.PROJECTS, config.FORKS_FILE)
        self.addCleanup(lambda: (setattr(config, "PROJECTS", snap[0]), setattr(config, "FORKS_FILE", snap[1])))
        config.PROJECTS = d
        config.FORKS_FILE = os.path.join(d, "forks.json")
        os.makedirs(os.path.join(d, "-x"))
        for sid in ("parent1", "child1"):
            _write(os.path.join(d, "-x", sid + ".jsonl"), [
                {"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}},
                _asst("m" + sid, {"input_tokens": 1000, "output_tokens": 1})])
        with open(config.FORKS_FILE, "w") as fh:
            json.dump({"parent1": {"child": "child1"}}, fh)
        self.assertIn("copied", registry.parse_any("child1")["cost"]["note"])
        self.assertNotIn("copied", registry.parse_any("parent1")["cost"]["note"] or "")


if __name__ == "__main__":
    unittest.main()
