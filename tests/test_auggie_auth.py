"""accounts: `auggie auth status` producer. The real CLI is never spawned (accounts._run is a fake)."""
import os
import unittest
from unittest import mock

from aitracker import accounts


class AuggieAuthTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.out = (0, b"Logged in.\n", b"")
        self.spec = {"id": "auggie", "path": "/opt/bin/auggie"}
        for p in (mock.patch.object(accounts, "_run", self.fake_run),
                  mock.patch.object(accounts, "_agent_spec", lambda i: self.spec)):
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, argv, timeout, env=None, cwd=None):
        self.calls.append((argv, timeout, cwd))
        return self.out

    def run_it(self):
        return accounts._acct_auggie_producer()

    def test_argv_uses_the_spec_path(self):
        body, ok, _ = self.run_it()
        self.assertEqual(self.calls, [(["/opt/bin/auggie", "auth", "status"], 20, os.path.expanduser("~"))])
        self.assertEqual((body["logged_in"], ok), (True, True))
        self.assertIn("account name isn't reported", body["label"])

    def test_banner_line_before_the_status_still_parses(self):
        self.out = (0, b"Update available\nLogged in.\n", b"")
        self.assertTrue(self.run_it()[0]["logged_in"])

    def test_exact_equality_not_prefix(self):
        self.out = (0, b"Logged in as someone@x.test\n", b"")
        body, ok, _ = self.run_it()
        self.assertEqual((body["logged_in"], body["error"], ok), (False, "couldn't read auggie auth status", False))

    def test_not_logged_in(self):
        self.out = (1, b"Not logged in.\n", b"")
        body, ok, _ = self.run_it()
        self.assertEqual((body["logged_in"], body["label"], body["error"], ok), (False, "Not logged in", "", True))

    def test_rc_must_match_the_text(self):
        for out in ((1, b"Logged in.\n", b""), (0, b"Not logged in.\n", b""), (2, b"", b"Authentication status could not be read.")):
            with self.subTest(out=out[0]):
                self.out = out
                self.assertEqual(self.run_it()[0]["error"], "couldn't read auggie auth status")

    def test_timeout_spawn_failure_and_missing_spec(self):
        self.out = (None, b"", b"timeout")
        self.assertIn("timed out", self.run_it()[0]["error"])
        self.out = (None, b"", b"/secret/path")
        body = self.run_it()[0]
        self.assertEqual(body["error"], "auggie couldn't be started")
        self.assertNotIn("secret", str(body))
        self.spec = None
        body, ok, _ = self.run_it()
        self.assertEqual((body["available"], ok), (False, False))

    def test_public_body_is_whitelisted(self):
        accounts.usage_invalidate("auggie_auth")
        accounts.auggie_auth_status()
        accounts._AUG._th.join(5)
        d = accounts.auggie_auth_status()
        self.assertEqual(set(d), {"available", "logged_in", "label", "error", "refreshing"})
        self.assertTrue(d["logged_in"])
        accounts.usage_invalidate("auggie_auth")


if __name__ == "__main__":
    unittest.main()
