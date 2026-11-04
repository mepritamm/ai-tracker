#!/usr/bin/env python3
"""util.file_pass (the server pass cache) and its use in claude.parse_session / parse_shells.

Fixture idiom from test_agent_cache.py. Each red-proof in the docstrings names the mutation that
turns the test red (docs/session-switch-cache-plan.md, P7)."""
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from aitracker import config, util
from aitracker.providers import claude
from aitracker.providers.claude import parse_session, parse_shells
from aitracker.registry import parse_any
from tests.test_agent_cache import _asst, _res, _tu, _write, make_fixture

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1783944000.0   # a fixed "now" so cold and warm compare equal


def _clear():
    with util._PASS_CACHE_LOCK:
        util._PASS_CACHE.clear()
        util._PASS_CACHE_BYTES = 0


def _append(path, text="more"):
    with open(path, "a") as fh:
        fh.write(json.dumps(_asst("2026-07-13T12:00:00Z", [{"type": "text", "text": text}])) + "\n")


def _bump_mtime(path, secs=5):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + secs * 10**9))


class _Env(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        _clear()
        self._env = mock.patch.dict(os.environ)
        self._env.start()
        os.environ.pop("AITRACKER_NO_PASS_CACHE", None)

    def tearDown(self):
        self._env.stop()
        _clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _file(self, name="a.jsonl", text="x\n"):
        p = os.path.join(self.dir, name)
        with open(p, "w") as fh:
            fh.write(text)
        return p


class TestFilePass(_Env):
    def _counting(self):
        calls = []

        def fn(path):
            calls.append(path)
            with open(path) as fh:
                return {"data": fh.read(), "n": len(calls)}
        return fn, calls

    def test_hit_does_not_reread(self):
        p = self._file()
        fn, calls = self._counting()
        a = util.file_pass("k", p, fn)
        b = util.file_pass("k", p, fn)
        self.assertEqual(len(calls), 1)
        self.assertEqual(a, b)

    def test_same_size_rewrite_with_restored_mtime_misses(self):
        p = self._file()
        with open(p, "w") as fh:
            fh.write("aa")
        st = os.stat(p)
        fn, calls = self._counting()
        util.file_pass("k", p, fn)
        with open(p, "w") as fh:
            fh.write("bb")
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(util.file_pass("k", p, fn)["data"], "bb")
        self.assertEqual(len(calls), 2)

    def test_hit_returns_a_fresh_object(self):
        p = self._file()
        fn, _ = self._counting()
        a = util.file_pass("k", p, fn)
        a["data"] = "mutated"
        self.assertEqual(util.file_pass("k", p, fn)["data"], "x\n")

    def test_kill_switch_runs_every_time(self):
        p = self._file()
        fn, calls = self._counting()
        os.environ["AITRACKER_NO_PASS_CACHE"] = "1"
        util.file_pass("k", p, fn)
        util.file_pass("k", p, fn)
        self.assertEqual(len(calls), 2)
        self.assertEqual(util._PASS_CACHE, {})

    def test_append_invalidates(self):
        p = self._file()
        fn, calls = self._counting()
        util.file_pass("k", p, fn)
        orig = os.stat(p)
        with open(p, "a") as fh:
            fh.write("y\n")
        os.utime(p, ns=(orig.st_atime_ns, orig.st_mtime_ns))   # same mtime: only size differs
        # (red when the key lacks size)
        self.assertEqual(util.file_pass("k", p, fn)["data"], "x\ny\n")
        self.assertEqual(len(calls), 2)

    def test_same_size_new_mtime_invalidates(self):
        p = self._file()
        fn, calls = self._counting()
        util.file_pass("k", p, fn)
        _bump_mtime(p)                                # same size, newer mtime (red when key lacks mtime)
        util.file_pass("k", p, fn)
        self.assertEqual(len(calls), 2)

    def test_replace_same_mtime_new_inode_invalidates(self):
        p = self._file(text="aaaa\n")
        fn, calls = self._counting()
        util.file_pass("k", p, fn)
        st = os.stat(p)
        tmp = p + ".new"
        with open(tmp, "w") as fh:
            fh.write("bbbb\n")                        # same size, new inode
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))   # same mtime
        os.replace(tmp, p)
        self.assertEqual(util.file_pass("k", p, fn)["data"], "bbbb\n")   # red when key lacks inode
        self.assertEqual(len(calls), 2)

    def test_write_during_pass_is_not_pinned(self):
        p = self._file()
        seen = []

        def fn(path):
            with open(path) as fh:
                body = fh.read()
            with open(path, "a") as fh:               # the append lands AFTER the read
                fh.write("late\n")
            seen.append(body)
            return body
        util.file_pass("k", p, fn)
        # red when os.stat moves after fn: the key would then describe the appended file
        out = util.file_pass("k", p, fn)
        self.assertEqual(len(seen), 2)
        self.assertEqual(out, "x\nlate\n")

    def test_identical_bytes_two_paths_stay_separate(self):
        a = self._file("a.jsonl")
        b = os.path.join(self.dir, "b.jsonl")
        os.link(a, b)   # a hard link: same inode, size and mtime, so ONLY the path tells them apart
        fn = lambda path: {"path": path}
        self.assertEqual(util.file_pass("k", a, fn)["path"], a)
        self.assertEqual(util.file_pass("k", b, fn)["path"], b)   # red when the key drops path
        self.assertEqual(util.file_pass("k", a, fn)["path"], a)

    def test_kinds_do_not_collide(self):
        p = self._file()
        self.assertEqual(util.file_pass("one", p, lambda _: 1), 1)
        self.assertEqual(util.file_pass("two", p, lambda _: 2), 2)

    def test_byte_bound_evicts_oldest_and_hit_refreshes_lru(self):
        files = [self._file("f%d.jsonl" % i) for i in range(3)]
        fn = lambda path: "z" * 1000
        size = len(__import__("pickle").dumps("z" * 1000, -1))
        with mock.patch.object(util, "PASS_CACHE_MAX_BYTES", size * 2 + 10):
            util.file_pass("k", files[0], fn)
            util.file_pass("k", files[1], fn)
            util.file_pass("k", files[0], fn)         # hit: f0 becomes newest (red with no touch)
            util.file_pass("k", files[2], fn)         # evicts the oldest = f1 (red with no eviction)
        self.assertEqual(sorted(k[1] for k in util._PASS_CACHE), sorted([files[0], files[2]]))
        self.assertLessEqual(util._PASS_CACHE_BYTES, size * 2 + 10)

    def test_replace_keeps_byte_count_exact(self):
        p = self._file()
        util.file_pass("k", p, lambda path: "a" * 100)
        with open(p, "a") as fh:
            fh.write("more\n")
        util.file_pass("k", p, lambda path: "b" * 300)
        # red when the replaced entry is not subtracted
        self.assertEqual(util._PASS_CACHE_BYTES, sum(len(v[1]) for v in util._PASS_CACHE.values()))
        self.assertEqual(util._PASS_CACHE_BYTES, len(util._PASS_CACHE[("k", p)][1]))

    def test_concurrent_misses_keep_byte_count_exact(self):
        """A smoke test, not a red-before-fix test: under the GIL it cannot reliably catch a counter
        update outside the lock. test_replace_keeps_byte_count_exact is the one that proves it."""
        files = [self._file("c%d.jsonl" % i) for i in range(4)]
        fn = lambda path: {"p": path, "blob": "q" * 500}
        errs = []

        def work(i):
            try:
                for n in range(50):
                    util.file_pass("k", files[(i + n) % 4], fn)
                    if n % 7 == 0:
                        with open(files[(i + n) % 4], "a") as fh:
                            fh.write("x\n")
            except Exception as e:   # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(util._PASS_CACHE_BYTES, sum(len(v[1]) for v in util._PASS_CACHE.values()))
        self.assertLessEqual(util._PASS_CACHE_BYTES, util.PASS_CACHE_MAX_BYTES)

    def test_unpicklable_fails_open(self):
        p = self._file()
        out = util.file_pass("k", p, lambda path: {"f": lambda: 1})   # red with no except around dumps
        self.assertTrue(callable(out["f"]))
        self.assertEqual(util._PASS_CACHE, {})

    def test_other_errors_in_dumps_propagate(self):
        p = self._file()
        with mock.patch.object(util.pickle, "dumps", side_effect=NameError("pickle")):
            with self.assertRaises(NameError):        # red when the except is widened
                util.file_pass("k", p, lambda path: 1)

    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            util.file_pass("k", os.path.join(self.dir, "nope.jsonl"), lambda p: 1)


class TestParseSessionCache(_Env):
    CFG = ("PROJECTS", "TASKS_DIR", "TITLES_FILE", "NOTES_FILE", "FLAGS_FILE", "PINS_FILE")

    def setUp(self):
        super().setUp()
        self._cfg = {k: getattr(config, k) for k in self.CFG}
        config.PROJECTS = os.path.join(self.dir, "projects")
        config.TASKS_DIR = os.path.join(self.dir, "tasks")
        for k in ("TITLES_FILE", "NOTES_FILE", "FLAGS_FILE", "PINS_FILE"):
            setattr(config, k, os.path.join(self.dir, k.lower() + ".json"))
        pdir = os.path.join(config.PROJECTS, "-repo-x")
        os.makedirs(pdir)
        self.sid = "sess"
        self.main = make_fixture(self.dir)             # <dir>/sess.jsonl + <dir>/sess/subagents
        shutil.move(self.main, os.path.join(pdir, "sess.jsonl"))
        shutil.move(os.path.join(self.dir, "sess"), os.path.join(pdir, "sess"))
        self.main = os.path.join(pdir, "sess.jsonl")
        self._write_main()
        if hasattr(claude, "_AGENT_CACHE"):
            claude._AGENT_CACHE.clear()
        self._time = mock.patch("time.time", return_value=T0)
        self._time.start()

    def tearDown(self):
        self._time.stop()
        for k, v in self._cfg.items():
            setattr(config, k, v)
        super().tearDown()

    def _write_main(self):
        U = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3}
        url = "https://github.com/o/r/pull/9"
        _write(self.main, [
            {"type": "user", "timestamp": "2026-07-13T08:00:00Z", "cwd": "/x", "sessionId": "sess", "gitBranch": "b",
             "message": {"role": "user", "content": "start the work"}},
            _asst("2026-07-13T08:01:00Z", [
                {"type": "text", "text": "on it"},
                _tu("t1", "Bash", {"command": "pytest -q"}),
                _tu("t2", "Edit", {"file_path": "/x/shared.py", "old_string": "a", "new_string": "b"}),
                _tu("t3", "Bash", {"command": "sleep 99", "run_in_background": True, "description": "wait"}),
                _tu("t4", "Bash", {"command": "gh pr create --title t"}),
                _tu("t5", "TodoWrite", {"todos": [{"content": "c", "status": "pending", "activeForm": "d"}]}),
            ], "m1", U),
            _res("2026-07-13T08:01:05Z", "t1", "3 passed"),
            _res("2026-07-13T08:01:06Z", "t3", "Command running in background with ID: bg1. Output is being written to: "
                 + os.path.join(self.dir, "bg1.output")),
            _res("2026-07-13T08:01:07Z", "t4", url),
            _asst("2026-07-13T08:02:00Z", [{"type": "text", "text": "done"}], "m2", U),
        ])
        with open(os.path.join(self.dir, "bg1.output"), "w") as fh:
            fh.write("first\n")

    def _detail(self):
        return parse_any("sess")

    def test_hit_does_not_reread_transcript(self):
        self._detail()
        real_open, opened = open, []

        def counting(path, *a, **k):
            opened.append(str(path))
            return real_open(path, *a, **k)
        with mock.patch("aitracker.providers.claude.open", counting, create=True):
            self._detail()
        self.assertNotIn(self.main, opened)

    def test_cold_equals_warm_with_agent_merges(self):
        """red when file_pass returns the stored object: the assembly's `e["ops"] += ae["ops"]` would
        then compound on every call."""
        os.environ["AITRACKER_NO_PASS_CACHE"] = "1"
        cold = self._detail()
        del os.environ["AITRACKER_NO_PASS_CACHE"]
        warm1 = self._detail()
        warm2 = self._detail()
        warm3 = self._detail()
        self.assertTrue(cold["files"] and any(f.get("agent") for f in cold["files"]), "fixture lost its agent merges")
        self.assertEqual(cold, warm1)
        self.assertEqual(cold, warm2)
        self.assertEqual(cold, warm3)
        self.assertGreater(len(util._PASS_CACHE), 0)

    def test_cold_equals_warm_across_pass_names(self):
        os.environ["AITRACKER_NO_PASS_CACHE"] = "1"
        a = claude._transcript_pass(self.main)
        self.assertEqual(sorted(a), sorted(claude._PASS_NAMES))
        self.assertEqual(a, util.file_pass("claude.transcript", self.main, claude._transcript_pass))

    def test_live_inputs_seen_with_transcript_untouched(self):
        """red under the mutation 'cache all of parse_session': each live input would be ignored."""
        base = self._detail()
        self._detail()      # warm

        with open(config.TITLES_FILE, "w") as fh:
            json.dump({"sess": "A fresh title"}, fh)
        d = self._detail()
        self.assertNotEqual(d, base)
        self.assertIn("A fresh title", json.dumps(d["meta"]))
        base = d
        with open(config.NOTES_FILE, "w") as fh:
            json.dump({"sess": [{"text": "a note", "pushed": False}]}, fh)
        d = self._detail()
        self.assertNotEqual(d, base)
        self.assertIn("a note", json.dumps(d))
        base = d
        tdir = os.path.join(config.TASKS_DIR, "sess")
        os.makedirs(tdir)
        with open(os.path.join(tdir, "1.json"), "w") as fh:
            json.dump({"id": "1", "subject": "Live task", "status": "in_progress", "activeForm": "Doing"}, fh)
        d = self._detail()
        self.assertNotEqual(d, base)
        self.assertIn("Live task", json.dumps(d["todos"]))
        base = d
        adir = os.path.join(os.path.dirname(self.main), "sess", "subagents")
        with open(os.path.join(adir, "agent-aaa111.meta.json"), "w") as fh:
            json.dump({"description": "new agent desc"}, fh)
        d = self._detail()
        self.assertNotEqual(d, base)
        self.assertIn("new agent desc", json.dumps(d))
        base = d
        with open(os.path.join(self.dir, "bg1.output"), "a") as fh:
            fh.write("second line\n")
        d = self._detail()
        self.assertNotEqual(d, base)
        self.assertIn("second line", json.dumps(d["shells"]))

    def test_time_fields_move(self):
        """red under the same mutation: `now`/`push_when`/agent `running` would stay frozen."""
        a = self._detail()
        with mock.patch("time.time", return_value=T0 + 3600):
            b = self._detail()
        self.assertNotEqual(a["now"], b["now"])
        self.assertNotEqual(a, b)

    def test_append_to_transcript_changes_detail(self):
        a = self._detail()
        _append(self.main, "appended narration")
        b = self._detail()
        self.assertIn("appended narration", json.dumps(b["narrative"]))
        self.assertNotIn("appended narration", json.dumps(a["narrative"]))

    def test_identical_bytes_two_paths_have_own_id_and_meta(self):
        pdir = os.path.dirname(self.main)
        other = os.path.join(pdir, "sess2.jsonl")
        shutil.copy(self.main, other)
        st = os.stat(self.main)
        os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns))
        a, b = parse_any("sess"), parse_any("sess2")
        self.assertEqual(a["id"], "sess")
        self.assertEqual(b["id"], "sess2")
        self.assertTrue({("claude.transcript", self.main), ("claude.transcript", other)} <= set(util._PASS_CACHE))

    def test_shells_pass_cached_and_output_stays_live(self):
        s1 = parse_shells(self.main)
        with open(os.path.join(self.dir, "bg1.output"), "a") as fh:
            fh.write("tail now\n")
        s2 = parse_shells(self.main)
        self.assertEqual(s1[0]["last"], "first")
        self.assertEqual(s2[0]["last"], "tail now")
        self.assertIn(("claude.shells", self.main), util._PASS_CACHE)

    def test_missing_transcript_shells_empty(self):
        self.assertEqual(parse_shells(os.path.join(self.dir, "nope.jsonl")), [])

    def test_mutating_returned_detail_does_not_poison_cache(self):
        a = self._detail()
        a["files"].clear()
        a["requests"].clear()
        b = self._detail()
        self.assertTrue(b["files"] and b["requests"])


class TestBundle(unittest.TestCase):
    def test_bundle_pass_cache_hits(self):
        """red when `pickle` is missing from bundle.py's HEADER: the narrowed except lets the
        NameError through (a fail-open would show up as two runs)."""
        bundler = os.path.join(ROOT, "scripts", "bundle.py")
        if not os.path.exists(bundler):
            self.skipTest("no bundler")
        r = subprocess.run([sys.executable, bundler], capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        dist = os.path.join(ROOT, "dist", "tracker.py")
        ns = runpy.run_path(dist, run_name="tracker_bundle_pass_cache")
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "a.jsonl")
            with open(p, "w") as fh:
                fh.write("x\n")
            calls = []

            def fn(path):
                calls.append(path)
                return {"n": len(calls)}
            ns["file_pass"]("k", p, fn)
            ns["file_pass"]("k", p, fn)
            self.assertEqual(len(calls), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
