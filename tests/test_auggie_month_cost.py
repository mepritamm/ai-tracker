"""providers.auggie.month_cost + accounts.auggie_usage over legacy ~/.augment/sessions/*.json fixtures
(shape: chatHistory[i].finishedAt, .exchange.response_nodes[].billing_metadata.cost_usd as a string,
top-level `modified` and subAgentCostUsd)."""
import builtins
import calendar
import datetime
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from aitracker import accounts, config
from aitracker.providers import auggie

UTC = datetime.timezone.utc


def ts(y, m, d):
    return datetime.datetime(y, m, d, 12, tzinfo=UTC).timestamp()


NOV1, OCT1 = ts(2026, 11, 1) - 12 * 3600, ts(2026, 10, 1) - 12 * 3600


def item(finished, cost):
    return {"finishedAt": finished, "exchange": {"response_nodes": [{"billing_metadata": {"cost_usd": cost}}, {"other": 1}]}}


class MonthCostTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(config, "AUGGIE_SESSIONS", self.d)
        p.start()
        self.addCleanup(p.stop)
        auggie._AUGGIE_BILL_CACHE.clear()

    def put(self, name, chat, modified, mtime, **extra):
        f = os.path.join(self.d, name)
        with open(f, "w") as fh:
            json.dump(dict({"sessionId": name, "modified": modified, "chatHistory": chat}, **extra), fh)
        os.utime(f, (mtime, mtime))
        return f

    def test_this_month_summed_and_last_month_excluded_in_one_file(self):
        self.put("a.json", [item("2026-11-03T10:00:00.123Z", "1.50"), item("2026-10-30T10:00:00.000Z", "9.00"),
                            item("2026-11-04T10:00:00.000Z", "0.25")], "2026-11-04T10:00:00.000Z", ts(2026, 11, 4))
        r = auggie.month_cost(NOV1)
        self.assertAlmostEqual(r["usd"], 1.75)
        self.assertEqual((r["sessions"], r["unpriced"], r["sources"]), (1, 0, ["~/.augment/sessions"]))

    def test_old_mtime_file_is_never_opened(self):
        old = self.put("old.json", [item("2026-09-01T10:00:00.000Z", "5")], "2026-09-01T10:00:00.000Z", ts(2026, 9, 1))
        opened = []
        real = builtins.open

        def spy(path, *a, **kw):
            opened.append(path)
            return real(path, *a, **kw)
        with mock.patch.object(auggie, "open", spy, create=True):
            r = auggie.month_cost(NOV1)
        self.assertEqual((r["usd"], r["sessions"]), (0, 0))
        self.assertNotIn(old, opened)

    def test_non_numeric_cost_is_unpriced_not_zero_session(self):
        self.put("b.json", [item("2026-11-03T10:00:00.000Z", "abc"), item("2026-11-03T11:00:00.000Z", "nan"),
                            item("2026-11-03T12:00:00.000Z", "2")], "2026-11-03T12:00:00.000Z", ts(2026, 11, 3))
        r = auggie.month_cost(NOV1)
        self.assertEqual((r["usd"], r["unpriced"]), (2.0, 2))

    def test_sub_agent_cost_counts_by_modified(self):
        self.put("c.json", [], "2026-11-05T10:00:00.000Z", ts(2026, 11, 5), subAgentCostUsd=0.5)
        self.put("d.json", [], "2026-10-05T10:00:00.000Z", ts(2026, 11, 5), subAgentCostUsd=7)   # touched, but last active in Oct
        self.put("e.json", [], "2026-11-05T10:00:00.000Z", ts(2026, 11, 5), subAgentCostUsd="x")
        r = auggie.month_cost(NOV1)
        self.assertAlmostEqual(r["usd"], 0.5)
        self.assertEqual(r["sessions"], 1)

    def test_item_without_finished_at_follows_the_file_modified(self):
        self.put("f.json", [item(None, "3")], "2026-11-06T10:00:00.000Z", ts(2026, 11, 6))
        self.put("g.json", [item(None, "4")], "2026-10-06T10:00:00.000Z", ts(2026, 11, 6))
        self.assertAlmostEqual(auggie.month_cost(NOV1)["usd"], 3.0)

    def test_since_change_recomputes(self):
        self.put("h.json", [item("2026-10-20T10:00:00.000Z", "2"), item("2026-11-02T10:00:00.000Z", "3")],
                 "2026-11-02T10:00:00.000Z", ts(2026, 11, 2))
        self.assertAlmostEqual(auggie.month_cost(NOV1)["usd"], 3.0)
        self.assertAlmostEqual(auggie.month_cost(OCT1)["usd"], 5.0)
        self.assertAlmostEqual(auggie.month_cost(NOV1)["usd"], 3.0)

    def test_corrupt_and_non_dict_files_are_skipped(self):
        f = os.path.join(self.d, "bad.json")
        with open(f, "w") as fh:
            fh.write("{not json")
        os.utime(f, (ts(2026, 11, 5), ts(2026, 11, 5)))
        f = os.path.join(self.d, "list.json")
        with open(f, "w") as fh:
            fh.write("[1]")
        os.utime(f, (ts(2026, 11, 5), ts(2026, 11, 5)))
        self.assertEqual(auggie.month_cost(NOV1)["usd"], 0)


class AuggieUsageBodyTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        p = mock.patch.object(config, "AUGGIE_SESSIONS", self.d)
        p.start()
        self.addCleanup(p.stop)
        auggie._AUGGIE_BILL_CACHE.clear()

    def test_note_names_the_source_and_the_v2_gap(self):
        b = accounts.auggie_usage()
        self.assertEqual(b["label"], "Local session cost, not account balance")
        self.assertEqual((b["available"], b["cost_text"], b["sessions"]), (True, "$0.00", 0))
        self.assertIn("~/.augment/sessions;", b["note"])
        self.assertIn("sessions-v2", b["note"])
        self.assertIn("sub-agent cost counts in the month the session was last active", b["note"])
        self.assertRegex(b["window"], r"^This month \(UTC, from [A-Z][a-z]{2} 1\)$")

    def test_unavailable_folder(self):
        with mock.patch.object(config, "AUGGIE_SESSIONS", os.path.join(self.d, "missing")):
            b = accounts.auggie_usage()
        self.assertEqual((b["available"], b["cost_text"]), (False, ""))
        self.assertIn("No ~/.augment/sessions folder", b["note"])

    def test_cost_text_and_unpriced_note(self):
        now = datetime.datetime.now(UTC)
        stamp = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        f = os.path.join(self.d, "x.json")
        with open(f, "w") as fh:
            json.dump({"modified": stamp, "chatHistory": [item(stamp, "1.234"), item(stamp, "bad")]}, fh)
        b = accounts.auggie_usage()
        self.assertEqual((b["cost_text"], b["sessions"]), ("$1.23", 1))
        self.assertIn("1 billed entry had no readable price", b["note"])

    def test_month_start_is_utc_midnight_even_when_local_time_is_ahead(self):
        class Frozen(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 12, 1, 2, 0, tzinfo=tz)       # IST is already Dec 1 07:30; a local midnight is 5.5 h early
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Kolkata"
        time.tzset()
        self.addCleanup(lambda: (os.environ.__setitem__("TZ", old) if old is not None else os.environ.pop("TZ", None), time.tzset()))
        spy = mock.Mock(return_value={"usd": 0, "sessions": 0, "unpriced": 0, "sources": []})
        with mock.patch.object(accounts.datetime, "datetime", Frozen), mock.patch.object(accounts, "month_cost", spy):
            b = accounts.auggie_usage()
        self.assertEqual(spy.call_args[0][0], calendar.timegm((2026, 12, 1, 0, 0, 0)))
        self.assertIn("from Dec 1", b["window"])


if __name__ == "__main__":
    unittest.main()
