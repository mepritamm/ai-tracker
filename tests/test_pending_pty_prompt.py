import unittest

from aitracker import term_vt


class PtyPromptArgv(unittest.TestCase):
    def test_prompt_appended(self):
        self.assertEqual(term_vt._with_prompt(["claude"], "do the thing"), ["claude", "do the thing"])

    def test_rejected_prompts_leave_argv(self):
        for p in (None, "", "   ", 5, "-x", "  --print hi", "a" * 4001):
            self.assertEqual(term_vt._with_prompt(["claude"], p), ["claude"], repr(p)[:20])

    def test_cap_boundary_and_shell_quoting(self):
        import shlex
        self.assertEqual(len(term_vt._with_prompt(["claude"], "a" * 4000)), 2)
        self.assertEqual(shlex.split(shlex.join(term_vt._with_prompt(["claude"], "it's $x; rm"))),
                         ["claude", "it's $x; rm"])


if __name__ == "__main__":
    unittest.main()
