"""Step 11: pending.py load_report/item_detail/resume_prompt/start_worker + the server routes
(/api/pending, /api/pending/item, /api/pending/run, /api/config PENDING_CLEAN=safe gate, run()).
No test scans this machine: paths are temp (pending_fixture) and run_once/run_async are stubbed."""
import http.client
import inspect
import json
import re
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
                mock.patch.object(_server.signal, "signal"), mock.patch.object(_server, "start_worker") as sw, \
                mock.patch.object(_server, "autoinstall_once", return_value={"action": "skipped"}):
            with self.assertRaises(SystemExit):
                _server.run(open_browser=False)
        sw.assert_called_once_with()

    # -- T16: the 5 s list path and the page's polls never reach the scan / clean / update / scheduler code
    def _boom(self, *names):
        for owner, name in names:
            p = mock.patch.object(owner, name, side_effect=AssertionError("%s must not run on this path" % name))
            p.start()
            self.addCleanup(p.stop)

    def test_list_and_session_never_touch_pending_update_scheduler(self):
        self._boom((pending, "scan"), (pending, "run_once"), (pending, "run_async"), (pending, "clean"),
                   (pending, "load_report"), (pending, "item_detail"), (pending, "_git"),
                   (_server, "run_async"), (_server, "update_status"), (_server, "update_fetch"),
                   (_server, "sched_status"), (_server, "sched_install"), (_server, "autoinstall_once"),
                   (_server, "load_report"), (_server, "item_detail"))
        proj = os.path.join(config.PROJECTS, "p")
        os.makedirs(proj)
        sid = "11111111-2222-3333-4444-555555555555"
        with open(os.path.join(proj, sid + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": "/tmp", "sessionId": sid, "timestamp": "2026-11-01T00:00:00Z",
                                 "message": {"role": "user", "content": "hi"}}) + "\n")
        st, j = self.req("GET", "/api/list")
        self.assertEqual(st, 200)
        self.assertIn(sid, [r.get("id") for r in j])
        self.assertEqual(self.req("GET", "/api/session?id=" + sid)[0], 200)
        self.assertEqual(self.req("GET", "/api/session?id=" + sid, headers=FWD)[0], 200)   # a tunnel visitor too

    def test_get_pending_never_scans(self):
        self._boom((pending, "scan"), (pending, "run_once"), (pending, "run_async"), (pending, "clean"),
                   (pending, "_git"), (_server, "run_async"))
        st, j = self.req("GET", "/api/pending")
        self.assertEqual((st, j["running"]), (200, False))
        self.assertEqual(self.req("GET", "/api/pending/item?id=nope")[0], 404)

    def test_list_handler_source_has_no_pending_code(self):
        src = inspect.getsource(_server.Handler.do_GET)
        a = src.index('p.path == "/api/list"')
        branch = src[a:src.index("elif p.path ==", a + 10)]
        for word in ("pending", "load_report", "update_", "sched", "run_async", "autoinstall"):
            self.assertNotIn(word, branch)
        from aitracker import registry
        self.assertIsNone(re.search(r"(?m)^\s*(from|import)\s.*\b(pending|schedule|update)\b",
                                    inspect.getsource(registry)))


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
                mock.patch.object(pending, "_scan_here_ok", lambda: True), \
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


class ReportStateTests(unittest.TestCase):
    """G2: stable report, memoised parse, foreign-lock card, as_of, containment fast path."""

    def setUp(self):
        d = tempfile.mkdtemp()
        for k, v in (("PENDING_FILE", os.path.join(d, "pending.json")), ("PENDING_LOCK", os.path.join(d, "p.lock")),
                     ("PENDING_LOG", os.path.join(d, "p.log")), ("PENDING_INTERVAL", "90d")):
            p = mock.patch.object(config, k, v)
            p.start()
            self.addCleanup(p.stop)
        pending._REPORT_MEMO.clear()

    def _write(self, **kw):
        with open(config.PENDING_FILE, "w") as fh:
            json.dump(kw, fh)

    def test_unchanged_file_gives_identical_json(self):
        for kw in ({}, {"items": [], "generated_at": 5}, {"scheduled_at": 100.0}):
            self._write(**kw)
            a = json.dumps(pending.load_report(), sort_keys=True)
            time.sleep(0.01)
            b = json.dumps(pending.load_report(), sort_keys=True)
            self.assertEqual(a, b)
        self._write()
        self.assertIsNone(pending.load_report()["next_due"])
        self._write(scheduled_at=100.0)
        self.assertEqual(pending.load_report()["next_due"], 100.0 + 90 * 86400)
        with mock.patch.object(config, "PENDING_INTERVAL", "off"):
            self.assertIsNone(pending.load_report()["next_due"])

    def test_card_as_of_derived_on_read(self):
        # a report written before build_card added as_of: the age comes from generated_at at READ time
        self._write(items=[], generated_at=1700000000, card={"show": True, "title": "Pending work", "summary": "x", "count": 1})
        want = time.strftime("%Y-%m-%d", time.localtime(1700000000))
        self.assertEqual(pending.load_report()["card"]["as_of"], want)
        self.assertEqual(pending.build_card({"generated_at": 1700000000})["as_of"], want)
        self._write(items=[], card={"show": False, "title": "Pending work", "summary": "", "count": 0})
        self.assertNotIn("as_of", pending.load_report()["card"])
        self._write(items=[])                                  # no card, no generated_at: no crash, no as_of
        self.assertNotIn("as_of", pending.load_report()["card"])

    def test_parse_is_memoised_and_rewrite_invalidates(self):
        self._write(items=[], generated_at=1)
        with mock.patch.object(pending, "_load_json", wraps=pending._load_json) as lj:
            pending.load_report()
            pending.load_report()
            pending.item_detail("nope")
            self.assertEqual(lj.call_count, 1)
            self._write(items=[], generated_at=123456789, pad="x" * 40)   # size changes
            self.assertEqual(pending.load_report()["generated_at"], 123456789)
            self.assertEqual(lj.call_count, 2)

    def test_foreign_lock_does_not_pop_hidden_card_in(self):
        self._write(items=[])
        with pending._pending_lock() as got:
            self.assertTrue(got)
            r = pending.load_report()
        self.assertTrue(r["running"])
        self.assertFalse(r["card"]["show"])
        pending._RUNNING.set()
        self.addCleanup(pending._RUNNING.clear)
        r = pending.load_report()
        self.assertTrue(r["card"]["show"])
        self.assertEqual(r["card"]["summary"], "scanning\u2026")

    def test_card_as_of_is_fixed_at_scan_time(self):
        t = 1_700_000_000
        c = pending.build_card({"items": [], "tmp": [], "generated_at": t}, now=t + 999 * 86400)
        self.assertEqual(c["as_of"], time.strftime("%Y-%m-%d", time.localtime(t)))

    def test_under_rp_matches_commonpath_semantics(self):
        self.assertTrue(pending._under_rp("/a/b", "/a/b"))
        self.assertTrue(pending._under_rp("/a/b/c", "/a/b"))
        self.assertFalse(pending._under_rp("/a/b0", "/a/b"))
        self.assertFalse(pending._under_rp("/a", "/a/b"))
        self.assertTrue(pending._under_rp("/a", "/"))


if __name__ == "__main__":
    unittest.main()
