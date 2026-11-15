"""In-app Update core (A3a): status, fetch, apply. Every git operation runs against temp repos with a
local bare remote; nothing execs, restarts or touches the network."""
import errno
import json
import os
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from aitracker import config, pending, update
from tests.update_fixture import make_update_fixture, requires_git


@requires_git
class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.fx = make_update_fixture(self)
        self.addCleanup(update._release_held)
        self.argv = []
        orig = update._run

        def rec(argv, *a, **k):
            self.argv.append(list(argv))
            return orig(argv, *a, **k)
        p = mock.patch.object(update, "_run", rec)
        p.start()
        self.addCleanup(p.stop)

    # -- status / fetch
    def test_behind_after_fetch(self):
        self.assertEqual(update.update_status()["behind"], 0)
        self.fx.push_change()
        self.assertEqual(update.update_status()["behind"], 0)     # no network without a fetch
        st = update.update_fetch()
        self.assertEqual((st["behind"], st["ahead"], st["can_update"], st["upstream"], st["branch"]),
                         (1, 0, True, "origin/main", "main"))
        self.assertIsNotNone(st["fetched_at"])
        self.assertEqual(st["kind"], "git")

    def test_refusals(self):
        fx = self.fx
        st = update.update_status()
        self.assertFalse(st["can_update"])
        self.assertEqual(st["reason"], "Up to date")
        fx.push_change()
        update.update_fetch()
        fx.write(fx.repo, "aitracker/server.py", "VALUE = 99\n")     # dirty tracked file
        st = update.update_status()
        self.assertFalse(st["can_update"])
        self.assertIn("commit or discard local edits", st["reason"])
        self.assertTrue(st["dirty"])
        fx.git(fx.repo, "checkout", "--", "aitracker/server.py")
        fx.write(fx.repo, "scratch.txt", "untracked")                 # untracked does not block
        self.assertTrue(update.update_status()["can_update"])
        fx.git(fx.repo, "commit", "--allow-empty", "-m", "local")     # diverged
        st = update.update_status()
        self.assertFalse(st["can_update"])
        self.assertIn("not fast-forwardable", st["reason"])
        self.assertEqual(update.update_apply()[0], 409)
        fx.git(fx.repo, "branch", "--unset-upstream")
        self.assertIn("No upstream", update.update_status()["reason"])
        fx.git(fx.repo, "checkout", "-q", "--detach")
        st = update.update_status()
        self.assertTrue(st["detached"])
        self.assertIn("detached", st["reason"])
        self.assertEqual(update.update_apply()[0], 409)

    def test_bundle_and_package_reasons(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config, "_HERE", d):
                st = update.update_status()
                self.assertEqual((st["kind"], st["can_update"]), ("bundle", False))
                self.assertIn("make bundle", st["reason"])
                self.assertEqual(update.update_apply()[0], 409)
            pkg = os.path.join(d, "aitracker")
            os.makedirs(pkg)
            open(os.path.join(pkg, "__init__.py"), "w").close()
            with mock.patch.object(config, "_HERE", pkg):
                st = update.update_status()
                self.assertEqual((st["kind"], st["can_update"]), ("package", False))
                self.assertIn("reinstall it with uv", st["reason"])

    # -- apply
    def test_apply_fast_forwards_to_resolved_target_only(self):
        x = self.fx.push_change(text="VALUE = 2\n")
        orig = update._preflight

        def mid_flight(target):
            self.fx.push_change(text="VALUE = 3\n", msg="Y")           # Y lands while the pre-flight runs
            self.fx.git(self.fx.repo, "fetch", "-q", "origin")
            return orig(target)
        with mock.patch.object(update, "_preflight", mid_flight):
            code, body = update.update_apply()
        self.assertEqual(code, 202, body)
        self.assertEqual(self.fx.head(), x)
        self.assertEqual(body["to"], x)
        self.assertIn("checkout --detach", body["recover"])
        self.assertEqual(update.update_status()["behind"], 1)         # Y still pending, not merged

    def test_preflight_failures_leave_head_alone(self):
        fx = self.fx
        old = fx.head()
        cases = [("server raises", dict(rel="aitracker/server.py", text="raise RuntimeError('broken')\n")),
                 ("overrides raise", dict(rel="aitracker/config.py",
                                          text="def apply_overrides(o):\n    raise ValueError('bad key')\n")),
                 ("page build", dict(rel="aitracker/web/app.css", delete=True))]
        with open(fx.cfg, "w") as fh:
            json.dump({"WHATEVER": 1}, fh)
        for name, kw in cases:
            with self.subTest(name):
                fx.push_change(**kw)
                code, body = update.update_apply()
                self.assertEqual(code, 409, (name, body))
                self.assertIn("pre-flight", body["error"])
                self.assertEqual(fx.head(), old)
                fx.git(fx.second, "reset", "-q", "--hard", "HEAD~1")    # drop the bad commit upstream
                fx.git(fx.second, "push", "-q", "-f", "origin", "main")
                fx.git(fx.repo, "fetch", "-q", "origin")

    def test_scan_lock_held_blocks_apply(self):
        self.fx.push_change()
        old = self.fx.head()
        with pending._pending_lock() as got:
            self.assertTrue(got)
            code, body = update.update_apply()
        self.assertEqual((code, body["error"]), (409, "scan in progress"))
        self.assertEqual(self.fx.head(), old)
        code, _ = update.update_apply()                   # everything was released by the failed attempt
        self.assertEqual(code, 202)

    def test_apply_holds_pending_lock_and_is_single_flight(self):
        self.fx.push_change()
        seen = {}
        orig = update._preflight

        def pf(target):
            seen["run_once"] = pending.run_once()
            seen["second"] = update.update_apply()
            return orig(target)
        with mock.patch.object(update, "_preflight", pf):
            code, body = update.update_apply()
        self.assertEqual(code, 202, body)
        self.assertEqual(seen["run_once"], {"running": True})
        self.assertEqual(seen["second"][0], 409)
        self.assertIn("already in progress", seen["second"][1]["error"])
        with pending._pending_lock() as got:              # still held after the 202, until exec
            self.assertFalse(got)
        update._release_held()
        with pending._pending_lock() as got:
            self.assertTrue(got)

    def test_open_terminals_need_confirm(self):
        self.fx.push_change()
        old = self.fx.head()
        fake = types.SimpleNamespace(_live_count=lambda: 1)
        with mock.patch.dict(sys.modules, {"aitracker.term_run": fake}):
            self.assertEqual(update.update_status()["terminals"], 1)
            code, body = update.update_apply()
            self.assertEqual((code, body.get("needs_confirm")), (409, True))
            self.assertEqual(self.fx.head(), old)
            code, body = update.update_apply(confirm_terminals=True)
            self.assertEqual(code, 202, body)

    def test_no_destructive_git_commands(self):
        self.fx.push_change()
        update.update_fetch()
        self.assertEqual(update.update_apply()[0], 202)
        flat = [a for argv in self.argv for a in argv]
        for bad in ("stash", "reset", "checkout", "rebase", "--force", "-f", "pull", "clean"):
            self.assertNotIn(bad, flat)
        merges = [a for a in self.argv if "merge" in a]
        self.assertEqual(len(merges), 1)
        self.assertIn("--ff-only", merges[0])
        self.assertRegex(merges[0][-1], r"^[0-9a-f]{40}$")     # only a resolved sha is ever merged

    # -- fetch isolation
    def test_fetch_has_no_controlling_terminal_and_dies_on_timeout(self):
        fx = self.fx
        out = os.path.join(fx.root, "ssh.json")
        script = os.path.join(fx.root, "fake-ssh")
        with open(script, "w") as fh:
            fh.write("#!%s\nimport json, os, time\n"
                     "try:\n    os.open('/dev/tty', os.O_RDWR); tty = 'opened'\n"
                     "except OSError as e:\n    tty = e.errno\n"
                     "json.dump({'pid': os.getpid(), 'sid': os.getsid(0), 'tty': tty,"
                     " 'stdin': os.read(0, 1).decode()}, open(%r, 'w'))\n"
                     "time.sleep(60)\n" % (sys.executable, out))
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        fx.git(fx.repo, "remote", "set-url", "origin", "ssh://fake.invalid/x.git")
        os.environ["GIT_SSH_COMMAND"] = script
        t0 = time.time()
        with mock.patch.object(update, "FETCH_TIMEOUT", 3):
            st = update.update_fetch()
        self.assertLess(time.time() - t0, 20)
        self.assertIn("fetch_error", st)
        info = json.load(open(out))
        self.assertEqual(info["tty"], errno.ENXIO)
        self.assertNotEqual(info["sid"], os.getsid(0))        # its own session
        self.assertEqual(info["stdin"], "")                   # stdin is closed / empty
        for _ in range(40):
            try:
                os.kill(info["pid"], 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("fake ssh survived the timeout (process group not killed)")

    # -- review fixes (E2-N1, E2-N2, E2-F6, F-F11)
    def test_state_change_during_preflight_refuses_before_merge(self):          # E2-N1
        self.fx.push_change()
        old = self.fx.head()
        orig = update._preflight

        def pf(target):
            self.fx.git(self.fx.repo, "commit", "--allow-empty", "-m", "local during preflight")
            return orig(target)
        with mock.patch.object(update, "_preflight", pf):
            code, body = update.update_apply()
        self.assertEqual(code, 409, body)
        self.assertIn("changed", body["error"])
        self.assertNotEqual(self.fx.head(), old)                       # only the test's own commit
        self.assertFalse([a for a in self.argv if "merge" in a])      # merge never ran
        self.assertIsNone(update._HELD)

    def test_terminal_opened_during_preflight_needs_confirm(self):               # E2-N1
        self.fx.push_change()
        old = self.fx.head()
        count = [0]
        fake = types.SimpleNamespace(_live_count=lambda: count[0])
        orig = update._preflight

        def pf(target):
            count[0] = 1
            return orig(target)
        with mock.patch.dict(sys.modules, {"aitracker.term_run": fake}), mock.patch.object(update, "_preflight", pf):
            code, body = update.update_apply()
        self.assertEqual((code, body.get("needs_confirm")), (409, True), body)
        self.assertEqual(self.fx.head(), old)
        self.assertFalse([a for a in self.argv if "merge" in a])

    def test_merge_timeout_after_completed_merge_still_restarts(self):          # E2-N2
        x = self.fx.push_change()
        real = update._g

        def g(*args, **kw):
            if args and args[0] == "merge":
                real(*args, **kw)                                      # the merge really lands...
                return None, "timeout"                                 # ...but git reports a timeout
            return real(*args, **kw)
        with mock.patch.object(update, "_g", g):
            code, body = update.update_apply()
        self.assertEqual(code, 202, body)
        self.assertEqual(self.fx.head(), x)

    def test_merge_refused_without_head_move_stays_409(self):                   # E2-N2 (guard)
        self.fx.push_change()
        real = update._g
        with mock.patch.object(update, "_g", lambda *a, **k: (1, "nope") if a and a[0] == "merge" else real(*a, **k)):
            code, body = update.update_apply()
        self.assertEqual(code, 409, body)
        self.assertIn("refused", body["error"])

    def test_windows_cannot_update(self):                                       # E2-F6
        self.fx.push_change()
        update.update_fetch()
        self.assertTrue(update.update_status()["can_update"])
        with mock.patch("os.name", "nt"):
            st = update.update_status()
        self.assertFalse(st["can_update"])
        self.assertIn("Windows", st["reason"])

    def test_fetch_is_single_flight(self):                                      # F-F11
        self.fx.push_change()
        real = update._run
        started, release, fetches = threading.Event(), threading.Event(), []

        def slow(argv, *a, **k):
            if "fetch" in argv:
                fetches.append(list(argv))
                started.set()
                release.wait(20)
            return real(argv, *a, **k)
        res = {}
        with mock.patch.object(update, "_run", slow):
            t = threading.Thread(target=lambda: res.update(first=update.update_fetch()))
            t.start()
            self.assertTrue(started.wait(20))
            second = update.update_fetch()
            release.set()
            t.join(30)
        self.assertEqual(len(fetches), 1)
        self.assertIn("already running", second["fetch_error"])
        self.assertNotIn("fetch_error", res["first"])
        self.assertEqual(update.update_fetch()["behind"], 1)           # lock released afterwards


if __name__ == "__main__":
    unittest.main()
