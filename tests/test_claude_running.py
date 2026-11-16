"""S1 seams: claude.running_sessions / session_state / transcript_size / user_line_has,
Provider.agent_cli / running descriptors, registry.resume_cmd."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker import config, registry
from aitracker.providers import claude
from aitracker.providers.base import Provider
from aitracker.providers.auggie import AuggieProvider
from aitracker.providers.augment_ext import AugmentVscodeProvider, AugmentCursorProvider


def _dead_pid():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


def _line(**o):
    return json.dumps(o, separators=(",", ":")) + "\n"


def _asst(blocks):
    return _line(type="assistant", message={"role": "assistant", "content": blocks})


def _user(text):
    return _line(type="user", message={"role": "user", "content": text})


class _Env(unittest.TestCase):
    def setUp(self):
        self._saved = (config.PROJECTS, config.LIVE_SESSIONS_DIR)
        self.tmp = tempfile.mkdtemp(prefix="running-")
        config.PROJECTS = os.path.join(self.tmp, "projects")
        config.LIVE_SESSIONS_DIR = os.path.join(self.tmp, "sessions")
        os.makedirs(os.path.join(config.PROJECTS, "proj"))
        os.makedirs(config.LIVE_SESSIONS_DIR)

    def tearDown(self):
        config.PROJECTS, config.LIVE_SESSIONS_DIR = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def transcript(self, sid, *lines):
        p = os.path.join(config.PROJECTS, "proj", sid + ".jsonl")
        with open(p, "w") as fh:
            fh.write("".join(lines))
        return p

    def pidfile(self, pid, **kw):
        d = {"pid": pid, "procStart": claude._ps_lstart(os.getpid()), "sessionId": "s-%s" % pid,
             "kind": "interactive", "entrypoint": "cli", "version": "2.1.323", "status": "idle", "cwd": "/x"}
        d.update(kw)
        d = {k: v for k, v in d.items() if v is not None}
        with open(os.path.join(config.LIVE_SESSIONS_DIR, "%s.json" % pid), "w") as fh:
            json.dump(d, fh)
        return d


class RunningSessions(_Env):
    def test_live_pid_kept_dead_wrong_start_nonint_excluded(self):
        me = os.getpid()
        self.pidfile(me)
        dead = _dead_pid()
        self.pidfile(dead, sessionId="dead")
        # wrong procStart on a live pid: write under a distinct filename
        d = self.pidfile(me, sessionId="wrongstart", procStart="Mon Jan  1 00:00:00 2001")
        os.rename(os.path.join(config.LIVE_SESSIONS_DIR, "%d.json" % me),
                  os.path.join(config.LIVE_SESSIONS_DIR, "wrong.json"))
        self.pidfile(me)
        with open(os.path.join(config.LIVE_SESSIONS_DIR, "str.json"), "w") as fh:
            json.dump(dict(d, pid=str(me), sessionId="strpid", procStart=claude._ps_lstart(me)), fh)
        got = {r["id"]: r for r in claude.running_sessions()}
        self.assertEqual(set(got), {"s-%d" % me})
        self.assertEqual(got["s-%d" % me]["version"], "2.1.323")

    def test_host_mapping_and_job_validation(self):
        me = os.getpid()
        cases = [("bg", "cli", "ab12cd", None, "daemon", "ab12cd"),
                 ("interactive", "cli", None, "beef01", "daemon", "beef01"),
                 ("interactive", "claude-desktop", None, None, "desktop", ""),
                 ("interactive", "cli", None, None, "tui", ""),
                 ("bg", "cli", "../ZZ", None, "daemon", "")]
        for i, (kind, ent, job, parked, host, want_job) in enumerate(cases):
            self.pidfile(me, sessionId="c%d" % i, kind=kind, entrypoint=ent, jobId=job, parkedJobId=parked)
            os.rename(os.path.join(config.LIVE_SESSIONS_DIR, "%d.json" % me),
                      os.path.join(config.LIVE_SESSIONS_DIR, "c%d.json" % i))
        got = {r["id"]: r for r in claude.running_sessions()}
        for i, (kind, ent, job, parked, host, want_job) in enumerate(cases):
            self.assertEqual((got["c%d" % i]["host"], got["c%d" % i]["job"]), (host, want_job), i)

    def test_key_whitelist_and_status_raw(self):
        me = os.getpid()
        self.pidfile(me, messagingSocketPath="SECRET-X", name="SECRET-X", status="shell")
        rows = claude.running_sessions()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("SECRET-X", json.dumps(rows))
        self.assertEqual(rows[0]["status_raw"], "shell")
        self.assertEqual(rows[0]["state"], "busy")


class SessionState(_Env):
    def test_status_mapping(self):
        self.assertEqual(claude.session_state("x", "idle"), "idle")
        self.assertEqual(claude.session_state("x", "waiting"), "waiting")
        for s in ("busy", "shell", "compacting"):
            self.assertEqual(claude.session_state("x", s), "busy")

    def test_transcript_fallback(self):
        ask = _asst([{"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": {}}])
        self.transcript("ask", _user("hi"), ask)
        self.assertEqual(claude.session_state("ask"), "waiting")
        self.transcript("tool", _user("hi"), _asst([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]))
        self.assertEqual(claude.session_state("tool"), "busy")
        self.transcript("done", _user("hi"), _asst([{"type": "text", "text": "all done"}]))
        self.assertEqual(claude.session_state("done"), "idle")
        self.assertEqual(claude.session_state("nope"), "")

    def test_tail_scan_last(self):
        p = self.transcript("l", _user("hi"), _asst([{"type": "text", "text": "ok"}]))
        self.assertEqual(claude._tail_scan(p)["last"], "assistant_text")


class Transcript(_Env):
    def test_user_line_has_since(self):
        p = self.transcript("t", _user("continue, re-read CLAUDE.md"))
        size = claude.transcript_size("t")
        self.assertEqual(size, os.path.getsize(p))
        self.assertFalse(claude.user_line_has("t", "continue, re-read CLAUDE.md", since=size))
        self.assertTrue(claude.user_line_has("t", "continue, re-read CLAUDE.md"))
        with open(p, "a") as fh:
            fh.write(_user("continue, re-read CLAUDE.md"))
        self.assertTrue(claude.user_line_has("t", "continue, re-read CLAUDE.md", since=size))
        self.assertEqual(claude.transcript_size("nope"), 0)


class Descriptors(unittest.TestCase):
    def test_descriptors(self):
        self.assertEqual(Provider().running(), [])
        self.assertEqual(AuggieProvider().running(), [])
        self.assertIsNone(Provider.agent_cli)
        self.assertIsNone(AugmentVscodeProvider.agent_cli)
        self.assertIsNone(AugmentCursorProvider.agent_cli)
        self.assertEqual(claude.ClaudeProvider.agent_cli, {
            "id": "claude", "label": "Claude Code", "bin": "claude", "version": ["--version"],
            "doctor": ["doctor"], "update": ["update"], "update_timeout": 600, "restarts_sessions": True})
        self.assertEqual(AuggieProvider.agent_cli, {
            "id": "auggie", "label": "Auggie", "bin": "auggie", "version": ["--version"], "doctor": None,
            "update": ["upgrade", "--skip-confirmation"], "update_timeout": 300, "restarts_sessions": False})

    def test_resume_cmd(self):
        self.assertEqual(registry.resume_cmd("abc-1", "claude-opus-4-1"), "claude --resume abc-1")
        with mock.patch.object(registry, "gateway_of", return_value="openrouter"):
            with mock.patch.object(registry, "or_launcher", return_value=("/opt/my launcher", None)):
                self.assertEqual(registry.resume_cmd("X", "m"), "'/opt/my launcher' --resume X")
            with mock.patch.object(registry, "or_launcher", return_value=(None, "unset")):
                self.assertIsNone(registry.resume_cmd("X", "m"))


if __name__ == "__main__":
    unittest.main()
