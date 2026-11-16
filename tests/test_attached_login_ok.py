"""Step 4: GET /api/term/attached carries a server-computed per-terminal `login_ok`."""
import unittest
from unittest import mock

from aitracker import term_vt
from tests.test_term_vt import _FakeHandler, _Q, _bare_pty

LAUNCHER = "/opt/my tools/claude-or"


class AttachedLoginOk(unittest.TestCase):
    def setUp(self):
        term_vt.PTYS.clear()

    def tearDown(self):
        term_vt.PTYS.clear()

    def _ask(self, cmd, fg=True):
        pt = _bare_pty("lo")
        pt.cmd = cmd
        term_vt.PTYS["lo"] = pt
        h = _FakeHandler()
        with mock.patch.object(term_vt, "_foreground_is_claude", lambda fd: fg), \
             mock.patch.object(term_vt.gateway, "or_launcher", lambda: (LAUNCHER, "")):
            term_vt.attached(h, _Q("session=&tty=lo"))
        return h.calls[-1]

    def test_table(self):
        for cmd, want in (("claude /login", True), ("claude", True), ("/usr/bin/claude --resume x", True),
                          ("claude attach abcd", False), (LAUNCHER, False), (LAUNCHER + " --resume x", False),
                          ("/bin/zsh -l", False), ("", False)):
            body, code = self._ask(cmd)
            self.assertEqual(code, 200)
            self.assertIs(body["login_ok"], want, cmd)
            self.assertTrue(body["claude_attached"])
            self.assertNotIn("gateway", body)

    def test_false_when_claude_not_in_foreground(self):
        body, _ = self._ask("claude /login", fg=False)
        self.assertEqual(body, {"claude_attached": False, "login_ok": False})

    def test_term_title_unchanged(self):
        for cmd, want in (("claude --x", "tmp - Anthropic models - Claude Code"),
                          (LAUNCHER + " --x", "tmp - OpenRouter models - Claude Code"),
                          ("/bin/zsh -l", "tmp - Terminal"), ("auggie", "tmp - Auggie")):
            pt = _bare_pty("t", cwd="/tmp")
            pt.cmd = cmd
            self.assertEqual(term_vt._term_title(pt, LAUNCHER), want)


if __name__ == "__main__":
    unittest.main()
