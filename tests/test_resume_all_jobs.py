"""Resume all prior terminals: the agent_cli side (T0b, T10-T13). A fake aitracker.term_vt in sys.modules supplies
resume_all_plan / _ra_need / call_route / term_gate; nothing real is opened and no record file is touched."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from aitracker import agent_cli as ac
from aitracker import config, update


def row(sid, cwd="/w", checked=True, **kw):
    d = {"session": sid, "title": "T" + sid, "cwd": cwd, "seen": 1.0, "cols": 100, "rows": 30, "reason": "",
         "command": ["claude --resume " + sid], "checked": checked}
    d.update(kw)
    return d


class FakeGate:
    ok = True

    def allowed(self):
        return self.ok


class FakeTV:
    def __init__(self):
        self.term_gate, self.bodies, self.plan = FakeGate(), [], self.mkplan([])
        self.replies, self.need = {}, None

    @staticmethod
    def mkplan(opn, cannot=(), free=5, already=(), idle=()):
        return {"open": list(opn), "cannot": list(cannot), "already": list(already), "free": free, "max": 8,
                "in_use": 8 - free, "idle": list(idle)}

    def resume_all_plan(self):
        return self.plan

    def _ra_need(self, cwds, idle):
        return len(cwds) if self.need is None else self.need

    def open_pty(self, *a):
        pass

    def call_route(self, fn, body):
        assert fn == self.open_pty
        self.bodies.append(dict(body))
        return self.replies.get(body["session"], (200, {"tty": "t-" + body["session"]}))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tv = FakeTV()
        for p in (mock.patch.dict(sys.modules, {"aitracker.term_vt": self.tv}),
                  mock.patch.object(config, "PENDING_LOCK", os.path.join(self.tmp, "pending.lock")),
                  mock.patch.object(ac, "transcript_size", lambda sid: 7)):
            p.start()
            self.addCleanup(p.stop)
        ac._AGENT_JOB = None
        self.addCleanup(self.wait)

    def wait(self):
        end = time.time() + 20
        while ac._AGENT_JOB_LOCK.locked() and time.time() < end:
            time.sleep(0.02)

    def start(self, confirm):
        code, body = ac.agent_start_resume_all(confirm)
        self.assertEqual(code, 202, body)
        self.wait()
        return ac._agent_snapshot()


class LaunchTests(Base):
    def test_t0b_launch_releases_lock(self):
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no threads")):
            code, body = ac._agent_launch("claude", "x", lambda job: None, ())
        self.assertEqual(code, 500)
        self.assertFalse(ac._AGENT_JOB_LOCK.locked())
        self.assertTrue(update._APPLY.acquire(blocking=False))
        try:
            code, body = ac._agent_launch("claude", "x", lambda job: None, ())
        finally:
            update._APPLY.release()
        self.assertEqual(code, 409)
        self.assertFalse(ac._AGENT_JOB_LOCK.locked())
        self.assertTrue(ac._AGENT_JOB_LOCK.acquire(blocking=False))
        self.addCleanup(lambda: ac._AGENT_JOB_LOCK.locked() and ac._AGENT_JOB_LOCK.release())
        code, body = ac._agent_launch("claude", "x", lambda job: None, ())
        self.assertEqual((code, body["error"]), (409, "an agent job is already running"))


class PreviewTests(Base):
    def test_t10_guards_and_body(self):
        with mock.patch.dict(sys.modules, {"aitracker.term_vt": None}):
            self.assertEqual(ac.agent_plan_resume_all(), (409, {"error": ac.AGENT_RA_NO_TERMS}))
        self.tv.term_gate.ok = False
        self.assertEqual(ac.agent_plan_resume_all(), (409, {"error": ac.AGENT_RA_DISABLED}))
        self.tv.term_gate.ok = True
        self.assertTrue(ac._AGENT_JOB_LOCK.acquire(blocking=False))
        ac._AGENT_JOB = {"state": "running", "items": []}
        try:
            code, body = ac.agent_plan_resume_all()
            self.assertEqual((code, body["error"]), (409, "an agent job is already running"))
        finally:
            ac._AGENT_JOB = None
            ac._AGENT_JOB_LOCK.release()
        code, body = ac.agent_plan_resume_all()               # empty plan
        self.assertEqual((code, body["message"], body["pick"], body["note"], body["already"]),
                         (409, ac.AGENT_RA_NONE, "", "", ""))
        self.tv.plan = FakeTV.mkplan([row("A"), row("B", checked=False)], [row("C", reason="why")], free=1,
                                     already=["X", "Y"], idle=["/w"])
        code, body = ac.agent_plan_resume_all()
        self.assertTrue(body["needs_confirm"])
        self.assertEqual(body["message"], ac.AGENT_RA_MESSAGE)
        self.assertEqual(body["pick"], ac.AGENT_RA_PICK % (1, "", 7, 8))
        self.assertEqual(body["already"], ac.AGENT_RA_ALREADY % "X, Y")
        self.assertEqual(body["note"], ac.AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN)
        self.assertEqual((body["free"], body["max"], len(body["open"]), len(body["cannot"])), (1, 8, 2, 1))
        for k in ("idle", "port", "saved_at"):
            self.assertNotIn(k, body)
        self.tv.plan = FakeTV.mkplan([], [row("C", reason="why")])
        self.assertEqual(ac.agent_plan_resume_all()[1]["message"], ac.AGENT_RA_MESSAGE + ac.AGENT_RA_NONE_OPENABLE)


class ConfirmTests(Base):
    def test_t11_validation_and_recheck(self):
        for bad in ("x", [], ["a"] * 65, [1], [""], ["a" * 201]):
            code, body = ac.agent_start_resume_all(bad)
            self.assertEqual((code, body["error"]), (400, "confirm must be a list of 1 to 64 session ids"), bad)
        self.tv.plan = FakeTV.mkplan([row("A"), row("B", "/x")], free=1)
        self.tv.need = 2
        code, body = ac.agent_start_resume_all(["A", "B"])
        self.assertEqual(code, 409)
        self.assertTrue(body["needs_confirm"])
        self.assertTrue(body["error"].startswith("The 2 you ticked need 2 terminal slots"), body["error"])
        self.assertEqual(body["error"], ac.AGENT_RA_TOO_MANY % (2, 2, "s", 1, "is"))
        self.assertIsNone(ac._AGENT_JOB)
        self.tv.plan = FakeTV.mkplan([row("A")], [row("C", reason="r")])
        for ids in (["C"], ["FORGED"]):
            code, body = ac.agent_start_resume_all(ids)
            self.assertEqual((code, body["error"]), (409, ac.AGENT_RA_NONE_PICKED))
        self.assertIsNone(ac._AGENT_JOB)
        self.tv.need = 1
        with mock.patch.object(ac, "_agent_launch", return_value=(202, {})) as la:
            self.assertEqual(ac.agent_start_resume_all(["A", "A"])[0], 202)
        self.assertEqual(la.call_args[0][3], (["A"],))
        code, body = ac.agent_start_resume_all(["A", "A"])
        self.assertEqual(code, 202)
        self.wait()
        self.assertEqual([b["session"] for b in self.tv.bodies], ["A"])


class JobTests(Base):
    def test_t12_job(self):
        self.tv.plan = FakeTV.mkplan([row("A"), row("B", "/b"), row("D", "/d")], [row("C", reason="cant, tui")])
        self.tv.replies = {"B": (429, {"error": "too many running terminals (max 2)"}),
                           "D": (200, {"tty": "t4", "attached": True})}
        job = self.start(["A", "B", "C", "D"])
        self.assertEqual(job["state"], "done")
        self.assertEqual([b["session"] for b in self.tv.bodies], ["A", "B", "D"])
        for b in self.tv.bodies:
            self.assertEqual(b["mode"], "resume")
            self.assertNotIn("prompt", b)
        it = {i["session"]: i for i in job["items"]}
        self.assertEqual((it["A"]["outcome"], it["A"]["tty_after"]), ("unprompted", "t-A"))
        self.assertEqual((it["B"]["outcome"], it["B"]["detail"]), ("failed", "too many running terminals (max 2)"))
        self.assertEqual((it["C"]["outcome"], it["C"]["detail"]), ("failed", "cant, tui"))
        self.assertEqual((it["D"]["outcome"], it["D"]["detail"]), ("failed", ac.AGENT_RA_REUSED % "t4"))
        for i in job["items"]:
            self.assertEqual(set(i), set(ac._AGENT_ITEM_KEYS))
        self.assertEqual(job["summary"], ac._agent_ra_summary(job["items"]))
        self.assertEqual(job["summary"], (
            "Started resuming 1 of 4 prior terminals in the background: TA. Not opened: TC (cant, tui); TB (too many "
            "running terminals (max 2)); TD (already open in tracker terminal t4, so it was not opened again). "
            + ac.AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN))

    def test_s4_summary_says_started_and_names_a_fork(self):
        self.tv.plan = FakeTV.mkplan([row("A"), row("B", cwd="/x")])
        self.tv.replies["B"] = (200, {"tty": "t-B", "forked": True})
        job = self.start(["A", "B"])
        self.assertEqual(job["summary"].split(":")[0], "Started resuming 2 of 2 prior terminals in the background")
        self.assertNotIn("Resumed", job["summary"])
        self.assertIn("TB (opened as a copy, --fork-session)", job["summary"])
        self.assertNotIn("TA (opened", job["summary"])
        self.tv.plan = FakeTV.mkplan([])
        self.assertEqual(ac._agent_ra_summary([]), "No prior terminal started resuming.")

    def test_t12_gone_and_scan_busy(self):
        self.tv.plan = FakeTV.mkplan([row("A")])
        job = self.start(["A"])                       # plan still has A
        self.assertEqual(job["items"][0]["outcome"], "unprompted")
        self.tv.plan = FakeTV.mkplan([row("A")])
        with mock.patch.object(ac, "_pending_lock") as pl:
            pl.return_value.__enter__.return_value = False
            job = self.start(["A"])
        self.assertEqual((job["state"], job["summary"]), ("failed", ac.AGENT_RA_FAIL_SCAN))
        self.assertEqual(len(self.tv.bodies), 1)      # only the first run called call_route


class StatusTests(Base):
    def test_t13_can_resume_all(self):
        rows = {r["id"]: r for r in ac.agent_status()["agents"]}
        self.assertIs(rows["claude"]["can_resume_all"], True)
        self.assertIs(rows["auggie"]["can_resume_all"], False)
        self.tv.term_gate.ok = False
        self.assertIs({r["id"]: r for r in ac.agent_status()["agents"]}["claude"]["can_resume_all"], False)
        with mock.patch.dict(sys.modules, {"aitracker.term_vt": None}):
            self.assertIs({r["id"]: r for r in ac.agent_status()["agents"]}["claude"]["can_resume_all"], False)


if __name__ == "__main__":
    unittest.main()
