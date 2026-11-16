#!/usr/bin/env python3
"""GET /api/agents and POST /api/agents/run over real HTTP (the _ServerCase pattern of
tests/test_cr_routes.py). agent_cli's job runner is stubbed everywhere it could start a
process: no real `claude`/`auggie` command runs and no real session is touched."""
import http.client
import json
import unittest
from unittest import mock

import aitracker.config as config
from aitracker import agent_cli as ac
from aitracker import server as _server
from tests.test_cr_routes import _ServerCase

_CAND = {"stoppable": True, "daemon": False, "target": "S1", "tty": "t1", "session": "S1", "title": "My work",
         "cwd": "/tmp/x", "version": "2.1.300", "command": ["claude --resume S1"], "status": "idle"}
_DAEMON = dict(_CAND, daemon=True, tty="t2", session="S2", target="S2", title="Bg")


class _TV:
    def __init__(self, cands):
        self.cands = cands

    def upgrade_candidates(self):
        return list(self.cands)


class _Routes(_ServerCase):
    def setUp(self):
        super().setUp()
        self.patch(config, "AUTH", "")
        self.patch(ac, "_AGENT_JOB", None)

    def patch(self, obj, name, val):
        p = mock.patch.object(obj, name, val)
        p.start()
        self.addCleanup(p.stop)

    def req(self, method, path, payload=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        body = None
        if method == "POST":
            body = json.dumps(payload).encode()
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw)

    def plan_env(self, cands):
        """Real agent_plan_upgrade over a fake term_vt: nothing is spawned."""
        self.patch(ac, "_agent_tv", lambda: _TV(cands))
        self.patch(ac, "_agent_outside", lambda *a, **k: [])
        self.patch(ac, "session_state", lambda *a, **k: "idle")
        specs = [dict(s, path="/bin/true") for s in ac.agent_specs()]
        self.patch(ac, "agent_specs", lambda: specs)
        self.patch(_server, "agent_job_running", lambda: False)


class TestAgentsRoutes(_Routes):
    def test_get_ok_from_loopback(self):
        self.patch(_server, "agent_status", lambda: {"agents": [], "job": None})
        st, j = self.req("GET", "/api/agents")
        self.assertEqual((st, j), (200, {"agents": [], "job": None}))

    def test_get_refused_proxied_and_foreign_host(self):
        self.patch(_server, "agent_status", lambda: {"agents": []})
        st, _ = self.req("GET", "/api/agents", headers={"X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(st, 403)
        st, _ = self.req("GET", "/api/agents", headers={"Host": "evil.example"})
        self.assertEqual(st, 403)

    def test_post_cross_origin_refused_and_starts_nothing(self):
        start = mock.Mock(return_value=(202, {}))
        self.patch(_server, "agent_start", start)
        st, _ = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "doctor"},
                         headers={"Origin": "http://evil.example"})
        self.assertEqual(st, 403)
        start.assert_not_called()

    def test_read_only_tunnel_refused_both_routes(self):
        start = mock.Mock(return_value=(202, {}))
        self.patch(_server, "agent_start", start)
        self.patch(_server, "agent_status", lambda: {"agents": []})
        self.patch(config, "resolve_tunnel_readonly", lambda o: True)
        h = {"X-Forwarded-For": "1.2.3.4"}
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "doctor"}, headers=h)
        self.assertEqual((st, j.get("readonly")), (403, True))
        st, j = self.req("GET", "/api/agents", headers=h)
        self.assertEqual((st, j.get("readonly")), (403, True))
        start.assert_not_called()

    def test_doctor_202_and_passthrough(self):
        start = mock.Mock(return_value=(202, {"job": {"id": 1}}))
        self.patch(_server, "agent_start", start)
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "doctor"})
        self.assertEqual((st, j), (202, {"job": {"id": 1}}))
        start.assert_called_once_with("claude", "doctor", None)

    def test_bad_confirm_is_400(self):
        # the real agent_start validates before it can start anything
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade", "confirm": "yes"})
        self.assertEqual(st, 400)
        self.assertIn("confirm", j["error"])

    def test_json_list_body_is_400(self):
        st, j = self.req("POST", "/api/agents/run", [1, 2])
        self.assertEqual(st, 400)
        self.assertIn("JSON object", j["error"])

    def test_unknown_agent_is_400(self):
        st, j = self.req("POST", "/api/agents/run", {"agent": "nope", "action": "upgrade"})
        self.assertEqual((st, j["error"]), (400, "unknown agent"))

    def test_upgrade_without_confirm_returns_needs_confirm(self):
        self.plan_env([_CAND])
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade"})
        self.assertEqual(st, 409)
        self.assertTrue(j["needs_confirm"])
        self.assertIn("will be stopped", j["message"])
        self.assertIn("updates itself in the background", j["note"])
        self.assertEqual([r["session"] for r in j["stop"]], ["S1"])

    def test_no_stop_message_when_nothing_to_stop(self):
        self.plan_env([])
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade"})
        self.assertEqual((st, j["message"]), (409, ac.AGENT_MSG_NO_STOP))

    def test_auggie_message_is_no_restart(self):
        self.plan_env([_CAND])
        st, j = self.req("POST", "/api/agents/run", {"agent": "auggie", "action": "upgrade"})
        self.assertEqual((st, j["message"]), (409, ac.AGENT_MSG_NO_RESTART))
        self.assertEqual(j["stop"], [])

    def test_daemon_row_state_text(self):
        self.plan_env([_DAEMON])
        self.patch(ac, "AGENT_RESTART_DAEMON", True)
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade"})
        self.assertEqual(st, 409)
        self.assertIn("comes back as a session in this tracker terminal", j["stop"][0]["state_text"])

    def test_job_running_gives_already_running_not_needs_confirm(self):
        self.plan_env([_CAND])
        self.patch(_server, "agent_job_running", lambda: True)
        plan = mock.Mock()
        self.patch(_server, "agent_plan_upgrade", plan)
        self.patch(_server, "agent_start", lambda a, b, c: (409, {"error": "an agent job is already running"}))
        st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade"})
        self.assertEqual(st, 409)
        self.assertIn("already running", j["error"])
        self.assertNotIn("needs_confirm", j)
        plan.assert_not_called()

    def test_apply_held_gives_updating_not_needs_confirm(self):
        self.plan_env([_CAND])
        plan = mock.Mock()
        self.patch(_server, "agent_plan_upgrade", plan)
        self.patch(_server, "agent_start", lambda a, b, c: (409, {"error": "the tracker is updating itself"}))
        self.assertTrue(_server._APPLY.acquire(blocking=False))
        try:
            st, j = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade"})
        finally:
            _server._APPLY.release()
        self.assertEqual(st, 409)
        self.assertIn("updating itself", j["error"])
        self.assertNotIn("needs_confirm", j)
        plan.assert_not_called()

    def test_confirmed_upgrade_goes_to_agent_start(self):
        start = mock.Mock(return_value=(202, {"job": {}}))
        self.patch(_server, "agent_start", start)
        conf = [{"tty": "t1", "session": "S1"}]
        st, _ = self.req("POST", "/api/agents/run", {"agent": "claude", "action": "upgrade", "confirm": conf})
        self.assertEqual(st, 202)
        start.assert_called_once_with("claude", "upgrade", conf)


if __name__ == "__main__":
    unittest.main()
