"""agent_cli._agent_outside: show-only rows for sessions not running in a tracker terminal."""
import time
import unittest
from unittest import mock

from aitracker import agent_cli as ac
from aitracker import registry
from aitracker.providers import claude as _claude


def run(i, host="tui", version="2.1.300", job="", kind="interactive", model="claude-opus-4-1", pid=None, state="idle"):
    return {"id": i, "pid": pid or 5000 + len(i), "version": version, "kind": kind, "entrypoint": "cli", "job": job,
            "host": host, "state": state, "status_raw": state, "cwd": "/w/" + i, "title": "T" + i, "model": model}


class OutsideTests(unittest.TestCase):
    def _out(self, rows, installed="2.1.325", owned_pids=(), owned_ids=()):
        spec = next(s for s in ac.agent_specs() if s["id"] == "claude")
        with mock.patch.object(_claude.ClaudeProvider, "running", lambda self: rows):
            return ac._agent_outside(spec, installed, set(owned_pids), set(owned_ids))

    def test_tui_row_command_and_out_of_date(self):
        r = self._out([run("abc")])[0]
        self.assertEqual((r["how"], r["command"], r["out_of_date"]), (ac.AGENT_HOW_TUI, ["claude --resume abc"], True))
        self.assertEqual(r["host"], "tui")

    def test_out_of_date_text_is_server_written(self):
        self.assertEqual(self._out([run("a", version="2.1.99")])[0]["out_of_date_text"], "out of date (installed v2.1.325)")
        self.assertEqual(self._out([run("a", version="2.1.1000")])[0]["out_of_date_text"], "")
        self.assertEqual(self._out([run("a", version="")])[0]["out_of_date_text"], "")

    def test_tui_openrouter_goes_through_launcher(self):
        with mock.patch.object(registry, "gateway_of", return_value="openrouter"):
            with mock.patch.object(registry, "or_launcher", return_value=("/opt/my launcher", None)):
                r = self._out([run("abc", model="x/y")])[0]
            self.assertEqual(r["command"], ["'/opt/my launcher' --resume abc"])
            with mock.patch.object(registry, "or_launcher", return_value=(None, "unset")):
                self.assertEqual(self._out([run("abc", model="x/y")])[0]["command"], [])

    def test_daemon_row_two_commands(self):
        r = self._out([run("abc", host="daemon", kind="bg", job="ab12")])[0]
        self.assertEqual(r["how"], ac.AGENT_HOW_DAEMON)
        self.assertEqual(r["command"], ["claude stop ab12", "claude --resume abc"])

    def test_desktop_row(self):
        r = self._out([run("abc", host="desktop", version="2.0.1")])[0]
        self.assertEqual((r["how"], r["command"], r["out_of_date"]), (ac.AGENT_HOW_DESKTOP, [], None))

    def test_parked_tui_and_worker_are_one_row(self):
        rows = [run("abc", host="daemon", job="ab12"), run("abc2", host="daemon", kind="bg", job="ab12")]
        self.assertEqual([o["id"] for o in self._out(rows)], ["abc2"])

    def test_owned_pid_or_id_excluded(self):
        rows = [run("a", pid=11), run("b", pid=12), run("c", pid=13)]
        self.assertEqual([o["id"] for o in self._out(rows, owned_pids=[11], owned_ids=["b"])], ["c"])

    def test_tuple_compare_not_string_compare(self):
        self.assertFalse(self._out([run("a", version="2.1.1000")])[0]["out_of_date"])
        self.assertTrue(self._out([run("a", version="2.1.99")])[0]["out_of_date"])
        self.assertIsNone(self._out([run("a", version="")])[0]["out_of_date"])
        self.assertIsNone(self._out([run("a", version="2.1.1")], installed=None)[0]["out_of_date"])

    def test_auggie_live_row_only(self):
        spec = next(s for s in ac.agent_specs() if s["id"] == "auggie")
        now = time.time()
        rows = [{"id": "auggie:new", "title": "N", "cwd": "/n", "mtime": now},
                {"id": "auggie:old", "title": "O", "cwd": "/o", "mtime": now - 100000},
                {"id": "claude-sid", "title": "C", "cwd": "/c", "mtime": now}]
        with mock.patch.object(ac, "all_sessions", return_value=rows):
            out = ac._agent_outside(spec, "0.36.0", set(), set())
        self.assertEqual([(o["id"], o["how"], o["out_of_date"], o["command"]) for o in out],
                         [("auggie:new", ac.AGENT_HOW_AUGGIE, None, [])])


if __name__ == "__main__":
    unittest.main()
