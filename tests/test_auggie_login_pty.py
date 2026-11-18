"""Config's Auggie login: POST /api/term/pty mode=new with the selector prompt runs the fixed
`auggie auth login --headless` argv in a dedicated pty on every gateway, is never typed, and leaves no Claude
last-login record. Reuses the open_pty harness of test_pending_pty_prompt (no real CLI is ever forked)."""
import unittest
from unittest import mock

from aitracker import agent_cli, term_vt
from tests.test_pending_pty_prompt import OpenPtyRoutePrompt

SPEC = {"id": "auggie", "path": "/opt/bin/auggie", "bin": "auggie"}


class AuggieLoginPty(OpenPtyRoutePrompt):
    def _auggie(self, body, spec=SPEC, **kw):
        with mock.patch.object(agent_cli, "_agent_spec", return_value=spec):
            return self._open(dict({"session": "", "mode": "new", "cwd": self._tmpdir, "prompt": "auggie auth login"},
                                   **body), **kw)

    def test_argv_is_auggie_on_every_gateway(self):
        for body, orl in (({"gateway": "anthropic"}, None), ({"gateway": "openrouter"}, None), ({}, None),
                          ({"gateway": "openrouter"}, "/opt/or/claude-or")):
            with self.subTest(body=body, orl=orl):
                self.spawned.clear()
                (obj, code), inj = self._auggie(body, or_launcher=orl)
                self.assertEqual(code, 200, obj)
                inj.assert_not_called()                                   # never typed into a shell
                self.assertEqual(self.spawned, [["/opt/bin/auggie", "auth", "login", "--headless"]])
                self.assertNotIn("claude", " ".join(self.spawned[0]))
                self.assertEqual(term_vt.PTYS["dd1"].login, "auggie")
                self.assertFalse(obj["folder"])

    def test_whitespace_is_ignored_and_other_prompts_are_not_auggie(self):
        (obj, code), inj = self._auggie({"prompt": "  auggie auth login \n"})
        self.assertEqual((code, self.spawned[0][1:]), (200, ["auth", "login", "--headless"]))
        self.spawned.clear()
        (obj, code), inj = self._auggie({"prompt": "auggie auth login --evil"})
        self.assertEqual(self.spawned, [])                                # an ordinary prompt: injected, not spawned
        inj.assert_called_once()

    def test_missing_auggie_is_400_with_no_spawn(self):
        for spec in (None, dict(SPEC, path=None)):
            self.spawned.clear()
            (obj, code), inj = self._auggie({}, spec=spec)
            self.assertEqual(code, 400)
            self.assertIn("auggie not found", obj["error"])
            self.assertEqual(self.spawned, [])
            inj.assert_not_called()

    def test_login_finished_gates_the_claude_record_by_kind(self):
        pt = term_vt.Pty(tid="x1", pid=1, fd=9, cwd="/")
        pt.rc = 0
        with mock.patch.object(term_vt.store, "record_login") as rec, \
             mock.patch("aitracker.accounts.usage_invalidate") as inv:
            pt.login = "auggie"
            term_vt._login_finished(pt)
            rec.assert_not_called()
            inv.assert_called_once_with("auggie_auth")
            inv.reset_mock()
            for kind in ("claudeai", "console"):
                pt.login = kind
                term_vt._login_finished(pt)
            self.assertEqual(rec.call_count, 2)
            self.assertEqual([c.args for c in inv.call_args_list], [("claude",), ("claude",)])


if __name__ == "__main__":
    unittest.main()
