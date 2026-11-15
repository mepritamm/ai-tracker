"""Step 11: pending.py load_report/item_detail/resume_prompt/start_worker + the server routes
(/api/pending, /api/pending/item, /api/pending/run, /api/config PENDING_CLEAN=safe gate, run()).
No test scans this machine: paths are temp (pending_fixture) and run_once/run_async are stubbed."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import config, pending
from aitracker import server as _server
from tests.pending_fixture import make_fixture, requires_git
from tests.test_cr_routes import _ServerCase

FWD = {"X-Forwarded-For": "203.0.113.9"}      # a tunnel fingerprint: _local_caller refuses it


class _Base(_ServerCase):
    def setUp(self):
        super().setUp()
        d = tempfile.mkdtemp()
        for k, v in (("PENDING_FILE", os.path.join(d, "pending.json")), ("PENDING_LOCK", os.path.join(d, "p.lock")),
                     ("PENDING_LOG", os.path.join(d, "p.log"))):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)

    def req(self, method, path, payload=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        body = None
        if method == "POST":
            body = json.dumps(payload or {}).encode()
            h.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, json.loads(out)


class RouteTests(_Base):
    def test_get_pending_local_ok_and_never_ro_allowed(self):
        st, j = self.req("GET", "/api/pending")
        self.assertEqual(st, 200)
        self.assertEqual((j["items"], j["running"]), ([], False))
        self.assertFalse(j["card"]["show"])
        self.assertNotIn("/api/pending", _server._RO_GET_ALLOW)
        self.assertNotIn("/api/pending/item", _server._RO_GET_ALLOW)

    def test_get_routes_refuse_non_local(self):
        self.assertEqual(self.req("GET", "/api/pending", headers=FWD)[0], 403)
        self.assertEqual(self.req("GET", "/api/pending/item?id=x", headers=FWD)[0], 403)

    def test_item_unknown_is_404(self):
        st, _j = self.req("GET", "/api/pending/item?id=nope")
        self.assertEqual(st, 404)

    def test_run_refuses_non_local_and_never_scans(self):
        with mock.patch.object(_server, "run_async") as ra, mock.patch.object(pending, "run_once") as ro:
            self.assertEqual(self.req("POST", "/api/pending/run", {}, FWD)[0], 403)
            ra.assert_not_called()
            ro.assert_not_called()

    def test_run_local_is_202_listonly_and_does_not_block(self):
        calls = []

        def stub(mode="dry-run"):
            calls.append(mode)
            return True
        with mock.patch.object(_server, "run_async", stub), mock.patch.object(pending, "run_once") as ro:
            t0 = time.monotonic()
            st, j = self.req("POST", "/api/pending/run", {"dry_run": False})   # body cannot widen the mode
            self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual((st, j), (202, {"running": True}))
        self.assertEqual(calls, ["dry-run"])
        ro.assert_not_called()

    def test_config_safe_refused_for_non_local_unchanged_file(self):
        st, _j = self.req("POST", "/api/config", {"key": "PENDING_CLEAN", "value": "safe"}, FWD)
        self.assertEqual(st, 403)
        self.assertFalse(os.path.exists(config.CONFIG_FILE))
        st, _j = self.req("POST", "/api/config", {"key": "PENDING_CLEAN", "value": "dry-run"}, FWD)
        self.assertEqual(st, 200)                      # only "safe" is gated
        st, j = self.req("POST", "/api/config", {"key": "PENDING_CLEAN", "value": "safe"})
        self.assertEqual((st, j["value"]), (200, "safe"))

    def test_run_calls_start_worker(self):
        srv = mock.MagicMock()
        srv.server_address = ("127.0.0.1", 4321)
        srv.serve_forever.side_effect = SystemExit
        with mock.patch.object(_server, "bind", return_value=srv), mock.patch.object(_server, "publish_endpoint"), \
                mock.patch.object(_server.tunnel, "autostart"), \
                mock.patch.object(_server.tunnel, "status", return_value={"on": False}), \
                mock.patch.object(_server.signal, "signal"), mock.patch.object(_server, "start_worker") as sw:
            with self.assertRaises(SystemExit):
                _server.run(open_browser=False)
        sw.assert_called_once_with()


class WorkerTests(unittest.TestCase):
    def test_start_worker_starts_even_when_off_and_loop_picks_up_on(self):
        pending._WORKER[:] = []
        self.addCleanup(pending._WORKER.__setitem__, slice(None), [])
        with mock.patch.object(config, "PENDING_INTERVAL", "off"), \
                mock.patch.object(pending, "_worker_loop", lambda: None):
            pending.start_worker()
            self.assertEqual(len(pending._WORKER), 1)      # off must NOT skip the thread
            pending._WORKER[0].join(2)
        # the real loop re-reads the interval each tick: off, then on
        d = tempfile.mkdtemp()
        ticks, sleeps = [], []

        def fake_sleep(s):
            sleeps.append(s)
            if len(sleeps) == 2:
                config.PENDING_INTERVAL = "1d"        # flipped while the thread lives
            if len(sleeps) == 4:
                raise KeyboardInterrupt

        def fake_tick(now=None):
            ticks.append(config.PENDING_INTERVAL)
            return "x"
        with mock.patch.object(config, "PENDING_INTERVAL", "off"), \
                mock.patch.object(config, "PENDING_FILE", os.path.join(d, "p.json")), \
                mock.patch.object(pending, "tick", fake_tick):
            with self.assertRaises(KeyboardInterrupt):
                pending._worker_loop(sleep=fake_sleep, clock=lambda: 1000.0)
        self.assertEqual(ticks[0], "off")
        self.assertEqual(ticks[-1], "1d")
        self.assertTrue(all(60 <= s <= 3600 for s in sleeps[1:]))


@requires_git
class DetailTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_fixture(self)

    def test_load_report_running_and_item_detail_resume(self):
        wt = self.fx.worktree("feat")
        with open(os.path.join(wt, "a.txt"), "w") as fh:
            fh.write("edited ``` fence breaker\n")
        pending.run_once("dry-run")
        r = pending.load_report()
        self.assertNotIn("gh_cache", r)
        self.assertFalse(r["running"])
        pending._RUNNING.set()
        try:
            self.assertTrue(pending.load_report()["running"])
            self.assertEqual(pending.load_report()["card"]["summary"], "scanning…")
        finally:
            pending._RUNNING.clear()
        it = next(i for i in r["items"] if i["branch"] == "feat")
        d = pending.item_detail(it["id"])
        self.assertEqual(os.path.realpath(d["resume"]["cwd"]), os.path.realpath(self.fx.repo))
        self.assertIn(it["path"], d["resume"]["prompt"])
        self.assertIn("worktree-cleanup", d["resume"]["prompt"])
        self.assertIn("git -C", d["resume"]["prompt"])
        self.assertIn(" M a.txt", d["md"])                     # live git status, fenced
        self.assertIn("````", d["md"])                         # longer fence than the ``` in the diff
        self.assertIsNone(pending.item_detail("nope"))

    def test_scratch_resume_cwd_is_home(self):
        sd = os.path.join(self.fx.paths["SCRATCH_ROOT"], "slug", "sid1")
        os.makedirs(sd)
        with open(os.path.join(sd, "f"), "w") as fh:
            fh.write("x")
        self.fx.age_tree(sd, 30)
        pending.run_once("dry-run")
        t = pending.load_report()["tmp"][0]
        d = pending.item_detail(t["id"])
        self.assertEqual(d["resume"]["cwd"], os.path.expanduser("~"))
        self.assertIn("cleanup skill", d["resume"]["prompt"])


if __name__ == "__main__":
    unittest.main()
