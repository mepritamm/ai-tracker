"""agent_cli pure helpers: version parser, spec resolution, warning text, busy rule, version_text."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker import agent_cli as ac


class ParseTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(ac.agent_parse_version("2.1.211 (Claude Code)"), "2.1.211")
        self.assertEqual(ac.agent_parse_version("\n  0.36.0 (commit 7c61e5bb)\n9.9.9"), "0.36.0")
        self.assertIsNone(ac.agent_parse_version("command not found"))
        self.assertIsNone(ac.agent_parse_version(""))
        self.assertIsNone(ac.agent_parse_version(None))

    def test_specs_resolve_path_from_stub_path(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        for n in ("claude", "auggie"):
            p = os.path.join(d, n)
            with open(p, "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(p, 0o755)
        with mock.patch.dict(os.environ, {"PATH": d}):
            specs = {s["id"]: s for s in ac.agent_specs()}
        self.assertEqual(specs["claude"]["path"], os.path.join(d, "claude"))
        self.assertEqual(specs["auggie"]["path"], os.path.join(d, "auggie"))
        self.assertEqual(specs["auggie"]["update"], ["upgrade", "--skip-confirmation"])
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        with mock.patch.dict(os.environ, {"PATH": empty}):
            self.assertTrue(all(s["path"] is None for s in ac.agent_specs()))

    def test_message_three_texts(self):
        m = ac._agent_message(["Alpha", "Beta"], True)
        self.assertIn("The following sessions: Alpha, Beta will be stopped", m)
        self.assertIn("continue, re-read CLAUDE.md", m)
        self.assertEqual(ac._agent_message([], True), ac.AGENT_MSG_NO_STOP)
        self.assertEqual(ac._agent_message(["x"], False), ac.AGENT_MSG_NO_RESTART)

    def test_busy_rule(self):
        self.assertTrue(ac._agent_was_busy("waiting", 0))
        self.assertTrue(ac._agent_was_busy("busy", 0))
        self.assertFalse(ac._agent_was_busy("idle", 0))
        self.assertTrue(ac._agent_was_busy("idle", 2))
        self.assertFalse(ac._agent_was_busy("", 0))

    def test_version_text_uses_tuple_compare(self):
        self.assertEqual(ac._agent_version_text("2.1.323", "2.1.325"), ac.AGENT_VER_OLD.format(v="2.1.323", i="2.1.325"))
        self.assertEqual(ac._agent_version_text("2.1.325", "2.1.325"), ac.AGENT_VER_CURRENT.format(i="2.1.325"))
        self.assertEqual(ac._agent_version_text("2.1.326", "2.1.325"), ac.AGENT_VER_NEWER_WARN.format(v="2.1.326", i="2.1.325"))
        self.assertIn("unless the update installs a newer one", ac._agent_version_text("2.1.326", "2.1.325"))
        self.assertEqual(ac._agent_version_text("", "2.1.325"), ac.AGENT_VER_UNKNOWN)
        self.assertEqual(ac._agent_version_text("2.1.9", "2.1.10"), ac.AGENT_VER_OLD.format(v="2.1.9", i="2.1.10"))

    def test_strip_ansi_and_cap(self):
        s = ac._agent_strip(b"\x1b[31mred\x1b[0m \x1b]0;title\x07ok\r\n")
        self.assertEqual(s, "red ok\n")
        s = ac._agent_strip(b"x" * 20000 + b"\x1b[31mERROR at the end\x1b[0m")     # the updater's error is at the tail
        self.assertLessEqual(len(s), ac.AGENT_OUTPUT_CAP)
        self.assertTrue(s.endswith("ERROR at the end"))
        self.assertNotIn("\x1b", s)

    def test_item_has_every_schema_key(self):
        it = ac._agent_item({"tty": "t", "session": "s"}, "failed", "why")
        self.assertEqual(set(it), set(ac._AGENT_ITEM_KEYS))
        self.assertEqual((it["outcome"], it["detail"], it["prompt_seen"], it["size_before"]), ("failed", "why", None, 0))
        self.assertEqual(len(it), 13)

    def test_dup_wording_has_no_stale_prompt_or_command_text(self):
        self.assertNotIn("shell prompt", ac.AGENT_DUP_WARN)
        self.assertEqual(ac.AGENT_DUP_WARN.count("%s"), 1)
        self.assertNotIn("command below", ac.AGENT_DUP_NOT_RESUMED)


if __name__ == "__main__":
    unittest.main()
