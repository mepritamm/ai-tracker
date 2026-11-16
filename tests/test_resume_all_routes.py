"""Resume all prior terminals: the route (T14) and the field-fit between agent_cli's bodies and what
resumeAllWidget / agentsBlock read. Fake term_vt throughout: nothing is opened, no record file is touched."""
import unittest
from unittest import mock

from aitracker import agent_cli as ac
from aitracker import server as _server
from tests.test_agent_routes import _Routes
from tests.test_resume_all_jobs import Base, FakeTV, row


class TestResumeAllRoute(_Routes):
    def test_t14_route(self):
        plan = mock.Mock(return_value=(409, {"needs_confirm": True}))
        start = mock.Mock(return_value=(202, {"job": {"id": 1}}))
        self.patch(_server, "agent_plan_resume_all", plan)
        self.patch(_server, "agent_start_resume_all", start)
        u = "/api/terminals/resume-all"
        st, _ = self.req("POST", u, {}, headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(st, 403)
        plan.assert_not_called()
        self.assertEqual(self.req("POST", u, {}), (409, {"needs_confirm": True}))
        self.assertEqual(self.req("POST", u, {"confirm": ["S1"]}), (202, {"job": {"id": 1}}))
        start.assert_called_once_with(["S1"])
        st, _ = self.req("POST", u, [1])
        self.assertEqual(st, 400)
        self.patch(_server.Handler, "_readonly", lambda self: True)
        st, j = self.req("POST", u, {})
        self.assertEqual((st, j.get("readonly")), (403, True))


class TestFieldFit(Base):
    """Every field the widget reads must exist, with its type, in the bodies the server really builds."""

    def test_picker_and_job_bodies(self):
        self.tv.plan = FakeTV.mkplan([row("A"), row("B", checked=False)], [row("C", reason="why")], free=1,
                                     already=["X"])
        code, b = ac.agent_plan_resume_all()
        self.assertEqual(code, 409)
        for k in ("message", "pick", "already", "note", "error"):
            self.assertIsInstance(b[k], str, k)
        self.assertIs(b["needs_confirm"], True)
        for r in b["open"]:
            for k, t in (("session", str), ("title", str), ("cwd", str), ("seen", (int, float)), ("checked", bool)):
                self.assertIsInstance(r[k], t, k)
        for r in b["cannot"]:
            for k in ("title", "reason"):
                self.assertIsInstance(r[k], str, k)
            self.assertIsInstance(r["command"], list)
            self.assertTrue(all(isinstance(c, str) for c in r["command"]))
        code, body = ac.agent_start_resume_all(["A"])
        self.assertEqual(code, 202)
        self.wait()
        self.assertIsInstance(body["job"]["id"], int)

    def test_status_row_has_can_resume_all(self):
        rows = ac.agent_status()["agents"]
        self.assertTrue(rows)
        for r in rows:
            self.assertIsInstance(r["can_resume_all"], bool)
        self.assertTrue([r for r in rows if r["id"] == "claude"][0]["can_resume_all"])


if __name__ == "__main__":
    unittest.main()
