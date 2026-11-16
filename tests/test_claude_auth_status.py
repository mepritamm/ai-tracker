"""gateway.claude_auth_status: three-key allowlist, cache + single-flight, lock timeout, group kill.
Every `claude` subprocess is a fake -- the real CLI is never spawned."""
import json
import os
import signal
import subprocess
import threading
import types
import unittest
from unittest import mock

from aitracker import gateway

SENTINELS = {"email": "SENT-email@x.test", "orgId": "SENT-org", "orgName": "SENT-orgname",
             "planTier": "SENT-tier", "newIdField": "SENT-new"}


class FakePopen:
    """Records construction; communicate returns canned output, raises, or blocks on an Event."""
    instances = []
    out = "{}"
    gate = None          # threading.Event: the first communicate waits on it
    timeouts = 0         # how many leading communicate calls raise TimeoutExpired
    raise_os = False

    def __init__(self, argv, **kw):
        if FakePopen.raise_os:
            raise OSError("boom /secret/path")
        self.argv, self.kw, self.pid, self.calls = argv, kw, 4242, []
        self.returncode = 0
        FakePopen.instances.append(self)

    def communicate(self, timeout=None):
        self.calls.append(timeout)
        if FakePopen.gate is not None and len(self.calls) == 1:
            FakePopen.gate.wait(10)
        if len(self.calls) <= FakePopen.timeouts:
            raise subprocess.TimeoutExpired("claude", timeout)
        return FakePopen.out, "STDERR-LEAK"

    def kill(self):
        pass


class Base(unittest.TestCase):
    def setUp(self):
        FakePopen.instances, FakePopen.out = [], "{}"
        FakePopen.gate, FakePopen.timeouts, FakePopen.raise_os = None, 0, False
        gateway._AUTH_CACHE.update(at=0.0, val=None)
        self.now = [1000.0]
        self.killpg = mock.Mock()
        for p in (mock.patch.object(gateway.shutil, "which", return_value="/usr/bin/claude"),
                  mock.patch.object(gateway.subprocess, "Popen", FakePopen),
                  mock.patch.object(gateway.os, "killpg", self.killpg),
                  mock.patch.object(gateway, "or_launcher", return_value=("/opt/or-launch", "")),
                  mock.patch.object(gateway, "time", types.SimpleNamespace(monotonic=lambda: self.now[0]))):
            p.start()
            self.addCleanup(p.stop)

    def run_status(self, d, **kw):
        FakePopen.out = json.dumps(d)
        return gateway.claude_auth_status(**kw)


class ParseTests(Base):
    def test_only_allowed_keys_survive(self):
        r = self.run_status(dict(loggedIn=True, authMethod="claude.ai", subscriptionType="max", **SENTINELS))
        blob = json.dumps(r)
        for v in SENTINELS.values():
            self.assertNotIn(v, blob)
        self.assertEqual(set(r), {"available", "logged_in", "auth_method", "subscription", "label", "error"})
        self.assertTrue(r["logged_in"])
        self.assertEqual(r["label"], "Logged in · Claude Max subscription")

    def test_logged_out(self):
        r = self.run_status({"loggedIn": False, "authMethod": "none"})
        self.assertFalse(r["logged_in"])
        self.assertEqual(r["label"], "Not logged in")

    def test_labels(self):
        self.assertEqual(self.run_status({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "<b>"},
                                         fresh=True)["label"], "Logged in · Claude subscription")
        self.now[0] += 100
        self.assertEqual(self.run_status({"loggedIn": True, "authMethod": "weird<x>"})["label"],
                         "Logged in · another credential")
        self.now[0] += 100
        self.assertEqual(self.run_status({"loggedIn": True, "authMethod": "weird"})["auth_method"], "")

    def test_non_json_and_list(self):
        FakePopen.out = "not json /home/leak"
        r = gateway.claude_auth_status()
        self.assertEqual(r["error"], "couldn't read claude auth status")
        self.assertNotIn("leak", json.dumps(r))
        self.assertNotIn("STDERR-LEAK", json.dumps(r))
        self.now[0] += 100
        FakePopen.out = "[1]"
        self.assertEqual(gateway.claude_auth_status()["error"], "couldn't read claude auth status")

    def test_argv_and_kwargs(self):
        self.run_status({"loggedIn": False})
        p = FakePopen.instances[0]
        self.assertEqual(p.argv, ["/usr/bin/claude", "auth", "status", "--json"])
        self.assertIs(p.kw["stdin"], subprocess.DEVNULL)
        self.assertTrue(p.kw["start_new_session"])
        self.assertEqual(p.kw["cwd"], os.path.expanduser("~"))


class GuardTests(Base):
    def test_missing_claude(self):
        with mock.patch.object(gateway.shutil, "which", return_value=None):
            r = gateway.claude_auth_status()
        self.assertFalse(r["available"])
        self.assertEqual(FakePopen.instances, [])

    def test_or_launcher_is_claude(self):
        with mock.patch.object(gateway, "or_launcher", return_value=("/usr/bin/claude", "")):
            r = gateway.claude_auth_status()
        self.assertFalse(r["available"])
        self.assertIn("OpenRouter launcher", r["error"])
        self.assertEqual(FakePopen.instances, [])

    def test_popen_oserror_is_generic_unavailable(self):      # C2
        FakePopen.raise_os = True
        r = gateway.claude_auth_status()
        self.assertFalse(r["available"])
        self.assertNotIn("secret", json.dumps(r))


class TimeoutTests(Base):
    def test_timeout_kills_group_and_bounded_wait(self):
        FakePopen.timeouts = 1
        r = self.run_status({"loggedIn": True})
        p = FakePopen.instances[0]
        self.killpg.assert_called_once_with(p.pid, signal.SIGKILL)
        self.assertEqual(p.calls, [gateway.AUTH_STATUS_TIMEOUT, 5])
        self.assertTrue(r["error"])
        self.assertFalse(r["logged_in"])

    def test_busy_lock_returns_within_bound(self):
        FakePopen.gate = threading.Event()
        with mock.patch.object(gateway, "AUTH_STATUS_TIMEOUT", 0.05), \
                mock.patch.object(gateway, "AUTH_LOCK_EXTRA", 0.05):
            a = threading.Thread(target=gateway.claude_auth_status)
            a.start()
            while not FakePopen.instances:
                pass
            res = []
            b = threading.Thread(target=lambda: res.append(gateway.claude_auth_status(fresh=True)))
            b.start()
            b.join(3)
            self.assertFalse(b.is_alive())
            self.assertIn("busy", res[0]["error"])
            FakePopen.gate.set()
            a.join(3)


class CacheTests(Base):
    def calls(self):
        return len(FakePopen.instances)

    def test_ttl_and_fresh_floor(self):
        self.run_status({"loggedIn": False})
        self.now[0] += 3
        self.run_status({"loggedIn": False})
        self.run_status({"loggedIn": False}, fresh=True)
        self.assertEqual(self.calls(), 1)
        self.now[0] += 3          # 6 s
        self.run_status({"loggedIn": False}, fresh=True)
        self.assertEqual(self.calls(), 2)
        self.now[0] += 30         # 36 s, not fresh
        self.run_status({"loggedIn": False})
        self.assertEqual(self.calls(), 2)
        self.now[0] += 30         # 66 s since last run
        self.run_status({"loggedIn": False})
        self.assertEqual(self.calls(), 3)

    def test_concurrent_callers_one_run(self):
        FakePopen.out = json.dumps({"loggedIn": False})
        FakePopen.gate = threading.Event()
        out = []
        ts = [threading.Thread(target=lambda: out.append(gateway.claude_auth_status(fresh=True)))
              for _ in range(6)]
        for t in ts:
            t.start()
        while not FakePopen.instances:
            pass
        FakePopen.gate.set()
        for t in ts:
            t.join(5)
        self.assertEqual(self.calls(), 1)
        self.assertEqual(len(out), 6)


if __name__ == "__main__":
    unittest.main()
