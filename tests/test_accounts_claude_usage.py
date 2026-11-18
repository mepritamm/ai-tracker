"""accounts: `claude -p /usage` producer + usage_report parser. The real CLI is never spawned (accounts._run is a fake)."""
import json
import os
import unittest
from unittest import mock

from aitracker import accounts, gateway

SENT = "SENT-email@x.test"
A_LIMITS = [  # the probed Max account's shape, verbatim types
    {"kind": "session", "group": "g", "percent": 87, "resets_at": "2026-11-18T10:19:00.000000+00:00", "scope": None,
     "severity": "warning", "is_active": True},
    {"kind": "weekly_all", "group": "g", "percent": 84, "resets_at": "2026-11-22T21:59:00+00:00", "scope": None,
     "severity": "warning", "is_active": False},
    {"kind": "weekly_scoped", "group": "g", "percent": 4, "resets_at": "2026-11-22T21:59:00+00:00",
     "scope": {"model": {"display_name": "Fable"}, "surface": None}, "severity": "normal", "is_active": False},
]


def stream(report, extra=None, is_error=False):
    lines = [{"type": "system", "subtype": "init", "mcp_servers": []}]
    if report is not None:
        lines.append({"type": "assistant", "message": {}, "usage_report": report})
    lines += list(extra or [])
    lines.append({"type": "result", "subtype": "success", "is_error": is_error})
    return ("\n".join(json.dumps(x) for x in lines) + "\n").encode()


def report(limits=A_LIMITS, extra_usage=None, **kw):
    rl = {"limits": limits}
    if extra_usage is not None:
        rl["extra_usage"] = extra_usage
    return dict({"session": {"total_cost_usd": 0}, "rate_limits": rl}, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.out = (0, stream(report()), b"")
        self.spec = {"id": "claude", "path": "/usr/bin/claude"}
        for p in (mock.patch.object(accounts, "_run", self.fake_run),
                  mock.patch.object(accounts, "_agent_spec", lambda i: self.spec),
                  mock.patch.object(accounts, "or_launcher", return_value=("/opt/or-launch", "")),
                  mock.patch.object(accounts, "claude_auth_cached", return_value={"label": "Logged in · Claude Max subscription", "subscription": "max"})):
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, argv, timeout, env=None, cwd=None):
        self.calls.append((argv, timeout, cwd))
        return self.out

    def run_it(self):
        return accounts._acct_claude_producer()


class ClaudeUsageTests(Base):
    def test_exact_argv_cwd_timeout(self):
        self.run_it()
        argv, timeout, cwd = self.calls[0]
        self.assertEqual(argv, ["/usr/bin/claude", "-p", "/usage", "--output-format", "stream-json",
                                "--verbose", "--no-session-persistence", "--settings", '{"disableAllHooks":true}',
                                "--strict-mcp-config"])
        self.assertEqual((timeout, cwd), (150, os.path.expanduser("~")))

    def test_probed_max_shape_three_rows_no_credits(self):
        body, ok, _ = self.run_it()
        self.assertTrue(ok)
        self.assertEqual(body["state"], "ok")
        self.assertEqual([(r["label"], r["percent"], r["severity"], r["active"]) for r in body["limits"]],
                         [("Current session", 87, "warning", True), ("Current week (all models)", 84, "warning", False),
                          ("Current week (Fable)", 4, "normal", False)])
        self.assertIsNone(body["credits"])

    def test_extra_usage_disabled_variants_give_no_credits(self):
        for eu in ({"is_enabled": False, "monthly_limit": 10000, "used_credits": 0},
                   {"is_enabled": "true", "monthly_limit": 10000, "used_credits": 5},
                   {"is_enabled": 1, "monthly_limit": 10000, "used_credits": 5}, None):
            with self.subTest(eu=eu):
                self.out = (0, stream(report(extra_usage=eu)), b"")
                self.assertIsNone(self.run_it()[0]["credits"])

    def test_fixture_b_usage_credits_account(self):
        # B: the probed usage-credits account's shape (empty limits, extra_usage inside rate_limits), neutral numbers.
        eu = {"is_enabled": True, "monthly_limit": 200000, "used_credits": 75844, "utilization": 37.922, "currency": "USD"}
        self.out = (0, stream(report(limits=[], extra_usage=eu)), b"")
        body, ok, _ = self.run_it()
        self.assertEqual((body["state"], ok, body["limits"], body["message"]), ("ok", True, [], ""))
        c = body["credits"]
        self.assertEqual(c["text"], "$758.44 spent of $2000.00 this month")
        self.assertEqual((c["used_minor"], c["limit_minor"], c["utilization"], c["currency"], c["note"]),
                         (75844, 200000, 37.9, "USD", ""))

    def test_fixture_c_team_enterprise_null_limit_never_unlimited(self):
        eu = {"is_enabled": True, "monthly_limit": None, "used_credits": 1234, "utilization": None, "currency": "USD"}
        self.out = (0, stream(report(limits=[], extra_usage=eu)), b"")
        for sub in ("team", "enterprise"):
            with self.subTest(sub=sub), mock.patch.object(accounts, "claude_auth_cached", return_value={"label": "x", "subscription": sub}):
                body = self.run_it()[0]
                c = body["credits"]
                self.assertEqual(c["text"], "$12.34 spent this month · no monthly limit of its own")
                self.assertEqual((c["note"], c["limit_minor"], c["utilization"]), ("your organisation's limits apply", None, None))
                self.assertNotIn("nlimited", json.dumps(body))
        self.assertEqual(self.run_it()[0]["credits"]["note"], "")        # a max login: no organisation note

    def test_credits_alongside_limits_and_other_currency(self):
        eu = {"is_enabled": True, "monthly_limit": 5000, "used_credits": 250, "utilization": 5, "currency": "EUR"}
        self.out = (0, stream(report(extra_usage=eu)), b"")
        body = self.run_it()[0]
        self.assertEqual(len(body["limits"]), 3)
        self.assertEqual(body["credits"]["text"], "2.50 EUR spent of 50.00 EUR this month")

    def test_credits_bad_values_are_none_or_sanitized(self):
        for eu in ({"is_enabled": True, "used_credits": "9"}, {"is_enabled": True, "used_credits": True},
                   {"is_enabled": True, "used_credits": -5}, {"is_enabled": True}):
            with self.subTest(eu=eu):
                self.out = (0, stream(report(limits=[], extra_usage=eu)), b"")
                body = self.run_it()[0]
                self.assertIsNone(body["credits"])
                self.assertEqual(body["message"], "No plan limits reported for this login.")
        eu = {"is_enabled": True, "monthly_limit": 100, "used_credits": 50, "utilization": 900, "currency": "<b>x</b>"}
        self.out = (0, stream(report(limits=[], extra_usage=eu)), b"")
        c = self.run_it()[0]["credits"]
        self.assertEqual((c["utilization"], c["currency"], c["text"]), (None, "USD", "$0.50 spent of $1.00 this month"))

    def test_no_usage_report_is_no_report(self):
        self.out = (0, stream(None), b"")
        body, ok, _ = self.run_it()
        self.assertEqual(body["state"], "no_report")
        self.assertTrue(ok)
        self.assertIn("usage-based billing", body["message"])

    def test_garbage_lines_skipped(self):
        self.out = (0, b"not json\n[1,2]\n" + stream(report()), b"")
        self.assertEqual(len(self.run_it()[0]["limits"]), 3)

    def test_usage_report_not_a_dict_is_error(self):
        self.out = (0, stream([1, 2]), b"")
        body, ok, hold = self.run_it()
        self.assertEqual((body["state"], ok, hold), ("error", False, 60.0))

    def test_is_error_and_rc_are_fixed_errors_without_stderr(self):
        for out in ((0, stream(report(), is_error=True), b"STDERR-LEAK"), (1, stream(report()), b"STDERR-LEAK")):
            with self.subTest(out=out[0]):
                self.out = out
                body, ok, _ = self.run_it()
                self.assertEqual((body["state"], body["error"], ok), ("error", "claude /usage failed", False))
                self.assertNotIn("STDERR-LEAK", json.dumps(body))

    def test_timeout_and_spawn_failure(self):
        self.out = (None, b"", b"timeout")
        self.assertIn("timed out", self.run_it()[0]["error"])
        self.out = (None, b"", b"/secret/path: No such file")
        body = self.run_it()[0]
        self.assertEqual(body["error"], "claude couldn't be started")
        self.assertNotIn("secret", json.dumps(body))

    def test_unknown_kind_scope_surface_and_sanitizing(self):
        rows = [{"kind": "daily_burst", "percent": 12.6, "resets_at": "2026-11-18T10:19:00Z", "severity": "weird",
                 "scope": {"model": None, "surface": {"display_name": "Cowork"}}},
                {"kind": "session", "percent": 250, "resets_at": "not a date <img>", "severity": "critical"},
                {"kind": "session", "percent": True, "resets_at": 5},
                {"kind": "weekly_scoped", "scope": {"model": {"display_name": "A\x07B" + "x" * 80}}}, "junk"]
        self.out = (0, stream(report(limits=rows)), b"")
        lim = self.run_it()[0]["limits"]
        self.assertEqual((lim[0]["label"], lim[0]["percent"], lim[0]["severity"]), ("Daily burst (Cowork)", 13, "normal"))
        self.assertEqual((lim[1]["percent"], lim[1]["resets_at"], lim[1]["severity"]), (None, None, "critical"))
        self.assertEqual((lim[2]["percent"], lim[2]["resets_at"]), (None, None))
        self.assertTrue(lim[3]["label"].startswith("Current week (AB") and len(lim[3]["label"]) <= 60)
        self.assertEqual(len(lim), 4)

    def test_nothing_else_of_the_report_is_forwarded(self):
        rep = report(email=SENT, rate_limits_extra=SENT)
        rep["rate_limits"]["limits"] = [dict(A_LIMITS[0], email=SENT, group=SENT)]
        self.out = (0, stream(rep), b"")
        self.assertNotIn(SENT, json.dumps(self.run_it()[0]))

    def test_launcher_or_missing_spec_is_unavailable(self):
        with mock.patch.object(accounts, "or_launcher", return_value=("/usr/bin/claude", "")):
            body, ok, _ = self.run_it()
        self.assertEqual((body["state"], ok), ("unavailable", False))
        self.spec = None
        self.assertEqual(self.run_it()[0]["state"], "unavailable")
        self.assertEqual(len(self.calls), 0)

    def test_never_runs_claude_auth_status(self):
        with mock.patch.object(gateway, "_auth_run", side_effect=AssertionError("auth status must not run")):
            accounts.usage_invalidate("claude")
            accounts.claude_usage()
            accounts._CLAUDE._th.join(5)
            body = accounts.claude_usage()
        self.assertEqual(body["account"], "Logged in · Claude Max subscription")
        self.assertEqual(body["state"], "ok")
        accounts.usage_invalidate("claude")


if __name__ == "__main__":
    unittest.main()
