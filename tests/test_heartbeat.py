"""Heartbeat (tokens + tool time over a session): build_heartbeat unit tests, plus the
provider-parity check that every provider's detail dict carries the same heartbeat keys."""
import inspect
import json
import os
import tempfile
import unittest

from aitracker import overview as ov, registry
from aitracker.overview import build_heartbeat, empty_heartbeat
from aitracker.providers import claude, auggie, augment_ext

T0 = 1_800_000_000.0
KEYS = {"span", "bucket_s", "beats", "by_tool", "waiting_ms", "by_agent", "by_model", "total",
        "agents_n", "note"}


def _tool(h, name):
    return next(r for r in h["by_tool"]["rows"] if r["name"] == name)


class TestBuildHeartbeat(unittest.TestCase):
    def test_overlapping_intervals_merge(self):
        h = build_heartbeat([], [(T0, "Read", "")], {"Read": [(T0, T0 + 10), (T0 + 5, T0 + 15)]})
        self.assertEqual(_tool(h, "Read")["busy_ms"], 15000)       # union, not 10+10

    def test_wait_tool_is_all_waiting(self):
        h = build_heartbeat([], [(T0, "AskUserQuestion", "")], {"AskUserQuestion": [(T0, T0 + 90)]})
        self.assertEqual(_tool(h, "AskUserQuestion")["busy_ms"], 0)
        self.assertEqual(h["waiting_ms"], 90000)

    def test_long_bash_interval_capped_excess_is_waiting(self):
        h = build_heartbeat([], [(T0, "Bash", "")], {"Bash": [(T0, T0 + 1000)]})
        self.assertEqual(_tool(h, "Bash")["busy_ms"], 600000)
        self.assertEqual(h["waiting_ms"], 400000)

    def test_cap_is_per_raw_interval_not_per_merged_block(self):
        h = build_heartbeat([], [(T0, "Bash", ""), (T0 + 300, "Bash", "")],
                            {"Bash": [(T0, T0 + 400), (T0 + 300, T0 + 700)]})
        self.assertEqual(_tool(h, "Bash")["busy_ms"], 700000)
        self.assertEqual(h["waiting_ms"], 0)

    def test_nested_long_interval_still_capped(self):
        h = build_heartbeat([], [(T0, "Bash", "")], {"Bash": [(T0, T0 + 1000), (T0 + 100, T0 + 200)]})
        self.assertEqual(_tool(h, "Bash")["busy_ms"], 600000)
        self.assertEqual(h["waiting_ms"], 400000)

    def test_empty_model_zero_token_row_dropped_but_tokened_kept(self):
        h = build_heartbeat([(T0, "", 0, 0, 0, ""), (T0, "m", 1, 0, 0, "")], [])
        self.assertEqual([r["model"] for r in h["by_model"]["rows"]], ["m"])
        h = build_heartbeat([(T0, "", 5, 0, 0, ""), (T0, "m", 1, 0, 0, "")], [])
        self.assertEqual([r["model"] for r in h["by_model"]["rows"]], ["", "m"])

    def test_agent_tool_is_uncapped(self):
        h = build_heartbeat([], [(T0, "Agent", "")], {"Agent": [(T0, T0 + 1000)]})
        self.assertEqual(_tool(h, "Agent")["busy_ms"], 1000000)
        self.assertEqual(h["waiting_ms"], 0)

    def test_no_intervals_means_nulls_and_rank_by_calls(self):
        h = build_heartbeat([], [(T0, "a", ""), (T0, "b", ""), (T0 + 1, "b", "")], None)
        self.assertIsNone(h["waiting_ms"])
        self.assertEqual([(r["name"], r["calls"], r["busy_ms"]) for r in h["by_tool"]["rows"]],
                         [("b", 2, None), ("a", 1, None)])

    def test_empty(self):
        h = empty_heartbeat("nothing here")
        self.assertEqual(set(h), KEYS)
        self.assertIsNone(h["span"])
        self.assertEqual((h["beats"], h["note"]), ([], "nothing here"))
        self.assertEqual(h["total"], {"out": 0, "fresh": 0, "cache": 0, "calls": 0})
        self.assertEqual((h["by_tool"]["rows"], h["by_agent"]["rows"], h["agents_n"]), ([], [], 0))

    def test_untimed_turn_lands_in_last_bucket(self):
        h = build_heartbeat([(T0, "m", 1, 0, 0, ""), (T0 + 600, "m", 2, 0, 0, ""), (0, "m", 4, 0, 0, "")], [])
        self.assertEqual(h["beats"][-1]["out"], 6)                 # the T0+600 turn + the untimed one
        self.assertEqual(sum(b["out"] for b in h["beats"]), h["total"]["out"])

    def test_beat_count_bounded_and_sums_hold(self):
        turns = [(T0 + i * 7, "m", 1, 2, 3, "") for i in range(1000)]
        h = build_heartbeat(turns, [(T0 + i, "x", "") for i in range(5000)])
        self.assertLessEqual(len(h["beats"]), ov.HB_BUCKETS)
        for k in ("out", "fresh", "cache", "calls"):
            self.assertEqual(sum(b[k] for b in h["beats"]), h["total"][k], k)

    def test_132_entities_roll_into_rest_and_invariant_holds(self):
        turns = [(T0 + i, "m%d" % (i % 12), 1 + i, 10, 100, "" if i == 0 else "ag%03d" % i) for i in range(132)]
        labels = {"ag%03d" % i: ("agent %d" % i, "m1") for i in range(1, 132)}
        h = build_heartbeat(turns, [], None, labels)
        ba = h["by_agent"]
        self.assertEqual(len(ba["rows"]), ov.HB_TOP)
        self.assertEqual(ba["rest"]["n"], 124)                      # 132 entities (main + 131) - 8 shown
        self.assertEqual(ba["rows"][0]["aid"], "")                  # main first
        for k in ("out", "fresh", "cache"):
            self.assertEqual(sum(r[k] for r in ba["rows"]) + ba["rest"][k], h["total"][k], k)
        bm = h["by_model"]
        for k in ("out", "fresh", "cache"):
            self.assertEqual(sum(r[k] for r in bm["rows"]) + (bm["rest"] or {}).get(k, 0), h["total"][k], k)
        self.assertEqual(h["agents_n"], 131)

    def test_tool_rest_rollup(self):
        h = build_heartbeat([], [(T0, "t%02d" % i, "") for i in range(11)], {})
        self.assertEqual(len(h["by_tool"]["rows"]), ov.HB_TOP)
        self.assertEqual(h["by_tool"]["rest"], {"n": 3, "calls": 3})


class TestProviderParity(unittest.TestCase):
    def test_every_provider_shares_the_heartbeat_key_set(self):
        p = tempfile.mktemp(suffix=".jsonl")
        with open(p, "w") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}) + "\n")
        try:
            self.assertEqual(set(claude.parse_session(p)["heartbeat"]), KEYS)
        finally:
            os.unlink(p)
        self.assertEqual(set(auggie._degraded_auggie_detail("x", p)["heartbeat"]), KEYS)   # unreadable file
        self.assertIn("empty_heartbeat(", inspect.getsource(augment_ext))                    # augment_ext explicit
        self.assertEqual(set(empty_heartbeat()), KEYS)

    def test_registry_parse_any_installs_a_heartbeat_when_a_provider_omits_it(self):
        class Stub:
            prefix = "stub:"

            def available(self):
                return True

            def parse(self, sid):
                return {"meta": {}, "files": []}      # no heartbeat key

        orig = registry.PROVIDERS
        registry.PROVIDERS = [Stub()]
        try:
            d = registry.parse_any("stub:abc")
        finally:
            registry.PROVIDERS = orig
        self.assertIsNotNone(d)
        self.assertEqual(set(d["heartbeat"]), KEYS)


if __name__ == "__main__":
    unittest.main()
