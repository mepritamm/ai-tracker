"""`title` on every `_live_list()` row: "<folder> - <Anthropic models|OpenRouter models> - <Claude Code|Auggie>",
built server-side from the pty's cwd + running argv[0] (the client only renders it)."""
import os
import tempfile
import unittest

from aitracker import config, term_vt


class TermTitleTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        self._orl = config.OPENROUTER_LAUNCHER
        self.addCleanup(self._restore)

    def _restore(self):
        config.OPENROUTER_LAUNCHER = self._orl
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._saved)

    def _title(self, cmd, cwd="/w/ai-tracker"):
        term_vt.PTYS["t1"] = term_vt.Pty(tid="t1", cwd=cwd, cmd=cmd)
        return {r["tty"]: r for r in term_vt._live_list()}["t1"]["title"]

    def test_anthropic_claude(self):
        self.assertEqual(self._title("claude"), "ai-tracker - Anthropic models - Claude Code")

    def test_openrouter_launcher(self):
        d = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, d)
        path = os.path.join(d, "or-claude")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        self.addCleanup(os.remove, path)
        config.OPENROUTER_LAUNCHER = path
        launcher = os.path.abspath(path)
        self.assertEqual(self._title(launcher), "ai-tracker - OpenRouter models - Claude Code")
        self.assertEqual(self._title(launcher + " --resume abc --fork-session"),
                         "ai-tracker - OpenRouter models - Claude Code")

    def test_openrouter_launcher_path_with_spaces(self):
        d = tempfile.mkdtemp(prefix="Application Support ")
        self.addCleanup(os.rmdir, d)
        path = os.path.join(d, "or-claude")
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        self.addCleanup(os.remove, path)
        config.OPENROUTER_LAUNCHER = path
        launcher = os.path.abspath(path)
        want = "ai-tracker - OpenRouter models - Claude Code"
        self.assertEqual(self._title(launcher), want)
        self.assertEqual(self._title(launcher + " --resume abc"), want)

    def test_term_list_resolves_launcher_outside_the_lock(self):
        seen = []
        real = term_vt.gateway.or_launcher

        def spy():
            seen.append(term_vt._LOCK.locked())
            return real()

        term_vt.gateway.or_launcher = spy
        self.addCleanup(setattr, term_vt.gateway, "or_launcher", real)
        term_vt.PTYS["t1"] = term_vt.Pty(tid="t1", cwd="/w/ai-tracker", cmd="claude")
        calls = []

        class H:
            headers = type("Hd", (), {"get": lambda self, k, d="": d})()
            def _json(self, obj, code=200):
                calls.append((obj, code))

        term_vt.term_list(H(), type("Q", (), {"query": ""})())
        self.assertEqual(calls[-1][1], 200)
        self.assertEqual(calls[-1][0]["terminals"][0]["title"], "ai-tracker - Anthropic models - Claude Code")
        self.assertTrue(seen)
        self.assertFalse(any(seen), "or_launcher() ran while _LOCK was held")

    def test_resume_argv_with_flags(self):
        self.assertEqual(self._title("claude --resume abc-123 --fork-session"),
                         "ai-tracker - Anthropic models - Claude Code")

    def test_auggie(self):
        self.assertEqual(self._title("/usr/local/bin/auggie --resume x"), "ai-tracker - Auggie")

    def test_idle_shell_is_terminal(self):
        self.assertEqual(self._title("/bin/zsh -l"), "ai-tracker - Terminal")

    def test_trailing_slash_cwd(self):
        self.assertEqual(self._title("claude", cwd="/w/ai-tracker/"),
                         "ai-tracker - Anthropic models - Claude Code")

    def test_unbalanced_quote_falls_back(self):
        self.assertEqual(self._title("claude 'oops"), "ai-tracker - Anthropic models - Claude Code")

    def test_title_on_every_row(self):
        for i, c in enumerate(("claude", "/bin/zsh -l", "")):
            term_vt.PTYS["r%d" % i] = term_vt.Pty(tid="r%d" % i, cwd="/w/x", cmd=c)
        rows = term_vt._live_list()
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIsInstance(r["title"], str)
            self.assertTrue(r["title"])


if __name__ == "__main__":
    unittest.main()
