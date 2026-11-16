"""L2b of terminal-at-root: the wiring. A worktree session's terminal is ONE shell at the repo root;
claude runs in the worktree through `sh -c 'cd "$0" && exec "$@"'`. Run: unset TRACKER_AUTH first."""
import json
import os
import re
import shlex
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import config, gateway, registry, term_gate, term_launch, term_vt
from aitracker.providers import claude

SHELL = 4242


class _H:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = os.path.join(self.tmp, "repo")
        self.top = self.worktree("w1")
        self.top2 = self.worktree("w2")
        self._t0, self._a0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, ""
        self._ptys0 = dict(term_vt.PTYS)
        term_vt.PTYS.clear()
        patcher = mock.patch.object(term_vt.Pty, "kill", autospec=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runs = {}                       # sid -> raw run dir the "transcript" recorded
        for target, fn in (("recorded_run_dir", lambda sid, meta=None: (self.runs.get(sid, ""), "")),
                           ("session_cwd", lambda sid, resume=False: self.runs.get(sid, ""))):
            p = mock.patch.object(term_gate, target, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._t0, self._a0
        term_vt.PTYS.clear()
        term_vt.PTYS.update(self._ptys0)

    def worktree(self, name):
        g = os.path.join(self.root, ".git", "worktrees", name)
        os.makedirs(g, exist_ok=True)
        with open(os.path.join(g, "commondir"), "w") as fh:
            fh.write("../..\n")
        top = os.path.join(self.root, ".claude", "worktrees", name)
        os.makedirs(top, exist_ok=True)
        with open(os.path.join(top, ".git"), "w") as fh:
            fh.write("gitdir: " + g + "\n")
        return top

    def folder_pty(self, cwd=None, tid="root1"):
        fp = term_vt.Pty(tid=tid, pid=SHELL, fd=99, cwd=cwd or self.root)
        fp.folder, fp.mode = True, "cwd"
        term_vt.PTYS[tid] = fp
        return fp

    def open(self, sid, mode, **extra):
        h = _H()
        body = {"session": sid, "mode": mode, "cols": 80, "rows": 24}
        body.update(extra)
        term_vt.open_pty(h, None, body)
        return h.calls[-1]

    def patches(self, typed, fg=SHELL):
        return [
            mock.patch.object(term_vt.os, "tcgetpgrp", side_effect=lambda fd: fg),
            mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True),
            mock.patch.object(term_vt, "_inject_write", side_effect=lambda pt, d: typed.append(d) or True),
            mock.patch.object(term_vt, "_start_backstop", return_value=False),
            mock.patch.object(term_vt, "_background_target", return_value=""),
            mock.patch.object(term_vt.term_gate, "resume_argv", side_effect=lambda s: ["claude", "--resume", s]),
            mock.patch.object(term_vt.gateway, "launcher", return_value="claude"),
        ]

    def run_open(self, sid, mode, typed, **kw):
        with contextlib_stack(self.patches(typed, **kw)):
            return self.open(sid, mode)


class contextlib_stack:
    def __init__(self, ps):
        self.ps = ps

    def __enter__(self):
        for p in self.ps:
            p.start()

    def __exit__(self, *a):
        for p in reversed(self.ps):
            p.stop()


class TestOpenPtyAtRoot(_Base):
    def test_all_modes_land_in_the_root_shell(self):
        fp = self.folder_pty()
        self.runs["S"] = self.top
        for mode in ("cwd", "resume", "new"):
            fp.fg = None
            fp.fg_pending = False
            obj, code = self.run_open("S", mode, [])
            self.assertEqual(code, 200, obj)
            self.assertEqual(obj["tty"], "root1", mode)
        self.assertEqual(fp.cwd, self.root)

    def test_golden_typed_line(self):
        fp = self.folder_pty()
        self.runs["S"] = self.top
        typed = []
        obj, code = self.run_open("S", "resume", typed)
        self.assertEqual(code, 200, obj)
        self.assertEqual(typed[0].decode(),
                         "sh -c 'cd \"$0\" && exec \"$@\"' %s claude --resume S" % shlex.quote(self.top))
        self.assertEqual(fp.run_dirs["S"], self.top)

    def test_launcher_not_resolved_by_server_path(self):
        self.folder_pty()
        self.runs["S"] = self.top
        typed = []
        with mock.patch("shutil.which", return_value="/wrong/claude"):
            self.run_open("S", "resume", typed)
        self.assertTrue(typed)
        self.assertNotIn(b"/wrong/claude", b"".join(typed))
        self.assertIn(b" claude --resume S", b"".join(typed))

    def test_overflow_resume_runs_in_the_top(self):
        fp = self.folder_pty()
        fp.fg = {"session": "OTHER", "mode": "resume", "started": 1e12, "grants": {"OTHER"}}
        fp.fg_seen_child = True
        self.runs["S"] = self.top
        extra = term_vt.Pty(tid="ov", pid=0)
        with mock.patch.object(term_vt, "spawn", return_value=extra) as sp:
            self.run_open("S", "resume", [], fg=SHELL + 1)
        self.assertEqual(sp.call_args[0][0], self.top)

    def test_second_worktree_session_reuses_the_tty(self):
        fp = self.folder_pty()
        self.runs.update({"A": self.top, "B": self.top2})
        t1, t2 = [], []
        o1, _ = self.run_open("A", "resume", t1)
        fp.fg = None
        o2, _ = self.run_open("B", "resume", t2)
        self.assertEqual((o1["tty"], o2["tty"]), ("root1", "root1"))
        self.assertIn(shlex.quote(self.top2).encode(), t2[0])

    def test_deleted_worktree_all_modes_409_with_recreate(self):
        gone = os.path.join(self.root, ".claude", "worktrees", "gone")
        self.runs["S"] = gone
        self.folder_pty()
        fake = ({"path": gone, "root": self.root, "token": "t"}, "")     # planning: test_term_recreate
        with mock.patch.object(term_vt, "spawn") as sp, mock.patch.object(term_gate, "_plan", return_value=fake):
            for mode in ("cwd", "new", "resume"):
                obj, code = self.run_open("S", mode, [])
                self.assertEqual(code, 409, (mode, obj))
                self.assertIn("recreate", obj)
                self.assertIn("was removed", obj["error"])
            self.assertFalse(sp.called)


class TestInjectArgv(_Base):
    def inject(self, argv, run_dir=None, cwd=None, sid="S"):
        pt = term_vt.Pty(tid="i1", pid=SHELL, fd=99, cwd=cwd or self.root)
        if run_dir:
            pt.run_dirs[sid] = run_dir
        typed = []
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=SHELL), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda p, d: typed.append(d) or True):
            res = term_vt._inject_argv(pt, argv, sid=sid)
        return res, typed

    def test_never_brackets_long_shell_line(self):
        long_top = os.path.join(self.tmp, "x" * 260)
        (ok, _), typed = self.inject(["claude", "--resume", "S"], run_dir=long_top)
        self.assertTrue(ok)
        self.assertGreater(len(typed[0]), 250)
        self.assertNotIn(b"\x1b[200~", b"".join(typed))

    def test_199_201_golden_pair(self):
        for n in (199, 201):
            argv = ["claude", "x" * (n - 7)]
            (ok, _), typed = self.inject(argv)
            self.assertEqual(typed[0].decode(), shlex.join(argv))
            self.assertEqual(len(typed[0]), n)
            self.assertNotIn(b"\x1b[200~", typed[0])

    def test_refuses_newline_path(self):
        (ok, why), typed = self.inject(["claude", "--resume", "S"], run_dir=self.top + "\nrm -rf x")
        self.assertFalse(ok)
        self.assertEqual(why, "unsafe path")
        self.assertEqual(typed, [])


class TestRetryAndSwap(_Base):
    def test_fork_retry_after_fg_cleared_still_cds(self):
        fp = self.folder_pty()
        self.runs["S"] = self.top
        typed = []
        with contextlib_stack(self.patches(typed)):
            self.open("S", "resume")
            typed.clear()
            fp.fg = None                      # _refresh_fg cleared the claim when the refused claude exited
            with mock.patch.object(term_vt, "_folder_wait_prompt", return_value=True), \
                 mock.patch.object(term_vt.store, "capture_fork_snapshot", return_value={}), \
                 mock.patch.object(term_vt.store, "record_fork") as rf, \
                 mock.patch.object(term_vt, "_feed_note"):
                term_vt._retry_with_fork(fp, "S", 80, 24)
        line = b"".join(typed).decode()
        self.assertIn('cd "$0"', line)
        self.assertIn(self.top, line)
        self.assertIn("--fork-session", line)
        self.assertEqual(rf.call_args[0][1], self.top)       # fork lineage keyed on the run dir

    def test_swap_in_types_cd_line(self):
        fp = self.folder_pty()
        old = {"session": "OLD", "mode": "resume", "started": 1, "grants": {"OLD"}}
        fp.fg = old
        cand = {"fg": old, "pg": 777, "kind": "parked", "shown": "S"}
        typed = []
        with mock.patch.object(term_vt.os, "tcgetpgrp", return_value=777), \
             mock.patch.object(term_vt.os, "killpg"), \
             mock.patch.object(term_vt, "_folder_wait_prompt", return_value=True), \
             mock.patch.object(term_vt, "_wait_for_quiescence", return_value=True), \
             mock.patch.object(term_vt, "_fg_pgid", side_effect=[777, SHELL, SHELL, SHELL]), \
             mock.patch.object(term_vt, "_inject_write", side_effect=lambda p, d: typed.append(d) or True), \
             mock.patch.object(term_vt, "_start_backstop", return_value=False):
            term_vt._swap_in(fp, cand, "S", ["claude", "--resume", "S"], False, 80, 24, run_dir=self.top)
        line = b"".join(typed).decode()
        self.assertIn('cd "$0"', line)
        self.assertIn(self.top, line)


class TestCallSites(_Base):
    def test_resolve_spawned_forked_cwds_uses_run_dir(self):
        fp = self.folder_pty()
        fp.forked = True
        fp.run_dirs["S"] = self.top
        fp.fg = {"session": "", "mode": "new", "started": 1.0, "grants": set()}
        fp.fg["session"] = ""
        fp.run_dirs[""] = self.top
        with mock.patch.object(claude, "newest_session_in_cwd", return_value="") as ns:
            term_vt.resolve_spawned(throttle=0)
        for c in ns.call_args_list:
            self.assertNotEqual(c[0][0], self.top)
        self.assertFalse(ns.called)

    def test_resolve_spawned_skips_a_pty_in_a_forked_run_dir(self):
        fp = self.folder_pty()
        fp.forked = True
        fp.run_dirs["S"] = self.top             # a fork transcript may live in the worktree
        other = term_vt.Pty(tid="n1", pid=1, fd=98, cwd=self.top)
        other.mode = "new"
        term_vt.PTYS["n1"] = other
        with mock.patch.object(claude, "newest_session_in_cwd", return_value="") as ns:
            term_vt.resolve_spawned(throttle=0)
        self.assertFalse(ns.called)

    def test_live_list_labels_worktree_not_root(self):
        fp = self.folder_pty()
        fp.run_dirs[""] = self.top
        fp.fg = {"session": "", "mode": "new", "started": 1.0, "grants": set()}
        fp.cmd = "claude"
        row = term_vt._live_list("")[0]
        self.assertEqual((row["cwd"], row["shell_cwd"]), (self.top, self.root))
        self.assertTrue(row["title"].startswith("w1 - "), row["title"])

    def test_idle_root_shell_not_labelled_worktree(self):
        fp = self.folder_pty()
        fp.run_dirs[""] = self.top             # a `new` claim that has since ended
        fp.fg = None
        row = term_vt._live_list("")[0]
        self.assertEqual(row["cwd"], self.root)

    def test_fg_public_has_no_run_dirs(self):
        fp = self.folder_pty()
        fp.run_dirs["S"] = self.top
        fp.fg = {"session": "S", "mode": "resume", "started": 1.0, "grants": {"S"}}
        row = term_vt._live_list("")[0]
        self.assertNotIn("run_dir", json.dumps(row["fg"]))
        self.assertNotIn(self.top, json.dumps(row["fg"]))


class TestOpenTerminalAtRoot(_Base):
    def unescape(self, script):
        m = re.search(r'(?:do script|write text) "((?:[^"\\]|\\.)*)"', script)
        return m.group(1).replace('\\"', '"').replace("\\\\", "\\")

    def test_script_holds_root_cd_and_run_dir(self):
        script = term_launch.build_script(self.root, "S", "resume", "Terminal",
                                          ["claude", "--resume", "S"], run_dir=self.top)
        inner = self.unescape(script)
        self.assertTrue(inner.startswith("cd %s && sh -c " % shlex.quote(self.root)), inner)
        parts = shlex.split(inner)
        self.assertEqual(parts[-1], self.top)

    def test_nasty_run_dir_round_trips(self):
        nasty = self.tmp + "/we'ird \"dir\" $x"
        script = term_launch.build_script(self.root, "S", "resume", "Terminal",
                                          ["claude", "--resume", "S", "--fork-session"], run_dir=nasty)
        parts = shlex.split(self.unescape(script).split(" && ", 1)[1])
        self.assertEqual(parts[-1], nasty)

    def test_route_places_before_404_and_409(self):
        h = _H()
        self.runs["S"] = self.top
        with mock.patch.object(term_launch, "_local_caller", return_value=(True, "")), \
             mock.patch.object(term_launch.subprocess, "run") as run, \
             mock.patch.dict(os.environ, {"TRACKER_TERM_APP": "Terminal"}), \
             mock.patch.object(term_launch, "_background_target", return_value=""), \
             mock.patch.object(term_gate, "resume_argv", return_value=["claude", "--resume", "S"]):
            term_launch.open_terminal(h, None, {"session": "S", "mode": "resume"})
            self.assertEqual(h.calls[-1][1], 200)
            self.assertIn("cd %s && sh -c" % shlex.quote(self.root), self.unescape(run.call_args[0][0][2]))
            self.runs["S"] = os.path.join(self.root, ".claude", "worktrees", "gone")
            fake = ({"path": self.runs["S"], "root": self.root, "token": "t"}, "")
            for mode in ("cwd", "resume"):
                with mock.patch.object(term_gate, "_plan", return_value=fake):
                    term_launch.open_terminal(h, None, {"session": "S", "mode": mode})
                self.assertEqual(h.calls[-1][1], 409, mode)
                self.assertIn("recreate", h.calls[-1][0])
            self.assertEqual(run.call_count, 1)


class TestRegistryTermHome(_Base):
    def setUp(self):
        super().setUp()
        self.proj = os.path.join(self.tmp, "projects")
        os.makedirs(os.path.join(self.proj, "p"))
        p = mock.patch.object(config, "PROJECTS", self.proj)
        p.start()
        self.addCleanup(p.stop)

    def test_claude_fixture_sets_keys_and_note(self):
        gone = os.path.join(self.root, ".claude", "worktrees", "gone")
        sid = "11111111-2222-3333-4444-555555555555"
        with open(os.path.join(self.proj, "p", sid + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": self.top, "message": {"role": "user", "content": "hi"}}) + "\n")
        term_gate.recorded_run_dir.side_effect = lambda s, meta=None: (self.top, "")
        meta = registry.parse_any(sid)["meta"]
        self.assertEqual(meta["term_home"], self.root)
        self.assertEqual(meta["term_home_note"], "")
        term_gate.recorded_run_dir.side_effect = lambda s, meta=None: (gone, "")
        meta = registry.parse_any(sid)["meta"]
        self.assertIn("was removed", meta["term_home_note"])

    def test_other_provider_fixture(self):
        class P:
            prefix = "fake:"

            def parse(self, sid):
                return {"meta": {"cwd": self_.top}, "counts": {}}

            def term_home(self, sid, meta=None):
                return "", ""
        self_ = self
        with mock.patch.object(registry, "PROVIDERS", list(registry.PROVIDERS) + [P()]):
            meta = registry.parse_any("fake:1")["meta"]
        self.assertEqual(meta["term_home"], self.root)


class TestParseAnyHugeLastLine(unittest.TestCase):
    def test_parse_any_no_recursion_on_huge_last_line(self):
        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        root = os.path.join(tmp, "repo")
        g = os.path.join(root, ".git", "worktrees", "w")
        os.makedirs(g)
        with open(os.path.join(g, "commondir"), "w") as fh:
            fh.write("../..\n")
        top = os.path.join(root, ".claude", "worktrees", "w")
        os.makedirs(top)
        with open(os.path.join(top, ".git"), "w") as fh:
            fh.write("gitdir: " + g + "\n")
        proj = os.path.join(tmp, "projects", "p")
        os.makedirs(proj)
        sid = "99999999-2222-3333-4444-555555555555"
        with open(os.path.join(proj, sid + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "user", "cwd": top, "message": {"role": "user", "content": "hi"}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "x" * 120000}}) + "\n")
        real = registry.parse_any
        calls = []

        def counting(s):
            calls.append(s)
            return real(s)
        with mock.patch.object(config, "PROJECTS", os.path.join(tmp, "projects")), \
             mock.patch.object(registry, "parse_any", side_effect=counting):
            d = registry.parse_any(sid)
        self.assertEqual(len(calls), 1)
        self.assertEqual(d["meta"]["term_home"], root)


if __name__ == "__main__":
    unittest.main()
