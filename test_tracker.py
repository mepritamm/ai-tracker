#!/usr/bin/env python3
"""Regression tests + evals for tracker.py — the mandatory gate (run via `make check`).

Stdlib `unittest` only — no dependencies, matching the app's zero-dep rule. This is a
safety net so a change can't silently break an existing feature:

  * granular unit tests for the pure helpers (fast, they pinpoint the break);
  * end-to-end "evals" that parse a realistic fixture session and assert the WHOLE
    derived view (summary, counts, commands, tokens, git branch, provider routing);
  * the embedded `--selfcheck` run as one guarded smoke test, so its rich fixtures
    (background agents/shells, diffs, command output, search boilerplate) count too.

Run: `python3 -m unittest -q test_tracker`  (or `make check`).
"""
import json
import os
import tempfile
import unittest

import tracker


# --- helpers: tracker keeps a few module-level globals (data paths + caches).
# Snapshot/restore them so tests that repoint them can't leak into each other. ---
_GLOBALS = ("PROJECTS", "AUGMENT_DIR", "AUGGIE_SESSIONS", "FLAGS_FILE", "TITLES_FILE", "TASKS_DIR")


def _snapshot():
    return {k: getattr(tracker, k) for k in _GLOBALS if hasattr(tracker, k)}


def _restore(snap):
    for k, v in snap.items():
        setattr(tracker, k, v)
    for cache in ("_AUGGIE_LIST_CACHE", "_META_CACHE"):
        if hasattr(tracker, cache):
            getattr(tracker, cache).clear()


class TestSelfcheckSmoke(unittest.TestCase):
    """The embedded --selfcheck must pass — it's the fixture-based eval the skills
    gate on. Running it here keeps its coverage (agents, shells, diffs, output,
    search) inside the suite. Guarded, since it repoints module globals."""

    def test_selfcheck_passes(self):
        snap = _snapshot()
        try:
            tracker._selfcheck()   # raises AssertionError on any regression
        finally:
            _restore(snap)


class TestCmdKind(unittest.TestCase):
    def test_classification(self):
        cases = {
            "git commit -m 'x'": "commit",
            "pytest -q tests/": "test",
            "npm test": "test",
            "pip install requests": "install",
            "make build": "build",
            "git status": "git",
            "ls -la /tmp": "cmd",
        }
        for cmd, kind in cases.items():
            self.assertEqual(tracker.cmd_kind(cmd), kind, cmd)


class TestShortTitle(unittest.TestCase):
    def test_strips_filler(self):
        self.assertEqual(tracker._short_title("Can you add a footer to the page"),
                         "Add a footer to the page")
        self.assertEqual(tracker._short_title("please fix the bug"), "Fix the bug")

    def test_truncates_long(self):
        self.assertTrue(tracker._short_title("word " * 40).endswith("…"))

    def test_empty(self):
        self.assertEqual(tracker._short_title(""), "")


class TestSearchHelpers(unittest.TestCase):
    def test_window_centers_and_ellipsizes(self):
        w = tracker._window("the quick brown fox jumps", "brown", pad=4)
        self.assertIn("brown", w)
        self.assertTrue(w.startswith("…") and w.endswith("…"))

    def test_boilerplate_is_excluded(self):
        data = "\n".join([
            json.dumps({"type": "user", "message": {"role": "user", "content": "fix the auth bug"}}),
            json.dumps({"type": "user", "message": {"role": "user",
                        "content": "<system-reminder>skills: xyztool-automation</system-reminder>"}}),
        ])
        cnt, snip, inq = tracker._match_content(data, "auth bug")
        self.assertGreaterEqual(cnt, 1)
        self.assertTrue(inq and "auth bug" in snip.lower())
        # a term living only inside the injected skill list must NOT match
        self.assertEqual(tracker._match_content(data, "xyztool-automation")[0], 0)


class TestGitBranch(unittest.TestCase):
    def test_normal_repo(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".git"))
        with open(os.path.join(d, ".git", "HEAD"), "w") as f:
            f.write("ref: refs/heads/feature/x\n")
        self.assertEqual(tracker._git_branch(d), "feature/x")

    def test_worktree(self):
        base = tempfile.mkdtemp()
        gitdir = os.path.join(base, "wt-gitdir")
        os.makedirs(gitdir)
        with open(os.path.join(gitdir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/wt-branch\n")
        wt = tempfile.mkdtemp()
        with open(os.path.join(wt, ".git"), "w") as f:
            f.write("gitdir: " + gitdir + "\n")
        self.assertEqual(tracker._git_branch(wt), "wt-branch")

    def test_missing_is_empty(self):
        self.assertEqual(tracker._git_branch("/no/such/dir"), "")
        self.assertEqual(tracker._git_branch(""), "")


class TestFlagsAndTitles(unittest.TestCase):
    def setUp(self):
        self.snap = _snapshot()
        tracker.FLAGS_FILE = tempfile.mktemp(suffix=".json")
        tracker.TITLES_FILE = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        _restore(self.snap)

    def test_flags_roundtrip(self):
        self.assertEqual(tracker.load_flags(), [])          # missing file -> empty
        tracker.save_flags([{"id": 1, "note": "x", "resolved": False}])
        got = tracker.load_flags()
        self.assertEqual(got[0]["note"], "x")
        got[0]["resolved"] = True
        tracker.save_flags(got)
        self.assertTrue(tracker.load_flags()[0]["resolved"])

    def test_titles_roundtrip(self):
        self.assertEqual(tracker.load_titles(), {})
        tracker._save_json(tracker.TITLES_FILE, {"sess": "My Title"})
        self.assertEqual(tracker.load_titles()["sess"], "My Title")


class TestClaudeEval(unittest.TestCase):
    """End-to-end: a realistic Claude session -> the full derived view."""

    def test_parse_session_view(self):
        rows = [
            {"type": "user", "cwd": "/x/proj", "gitBranch": "main",
             "message": {"role": "user", "content": "build the thing"}},
            {"type": "assistant", "timestamp": "2026-06-22T10:00:00Z",
             "message": {"usage": {"input_tokens": 100, "output_tokens": 20},
                         "content": [
                             {"type": "text", "text": "working on it"},
                             {"type": "tool_use", "name": "Write",
                              "input": {"file_path": "/x/proj/a.py", "content": "x\n"}},
                             {"type": "tool_use", "id": "b1", "name": "Bash",
                              "input": {"command": "git commit -m \"init\""}}]}},
        ]
        p = tempfile.mktemp(suffix=".jsonl")
        with open(p, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        d = tracker.parse_session(p)
        os.unlink(p)
        self.assertEqual(d["meta"]["cwd"], "/x/proj")
        self.assertEqual(d["meta"]["gitBranch"], "main")
        self.assertEqual(d["tokens"]["in"], 100)
        self.assertEqual(d["counts"]["created"], 1)
        self.assertEqual(d["commits"][0]["msg"], "init")
        self.assertEqual([r["text"] for r in d["requests"]], ["build the thing"])
        self.assertIn("working on it", [n["text"] for n in d["narrative"]])


class TestAuggieEval(unittest.TestCase):
    """End-to-end: a realistic Auggie session -> parity with Claude's shape."""

    def setUp(self):
        self.snap = _snapshot()
        tracker.AUGMENT_DIR = tempfile.mkdtemp()
        tracker.AUGGIE_SESSIONS = os.path.join(tracker.AUGMENT_DIR, "sessions")
        os.makedirs(tracker.AUGGIE_SESSIONS)
        os.makedirs(os.path.join(tracker.AUGMENT_DIR, "task-storage", "tasks"))
        with open(os.path.join(tracker.AUGMENT_DIR, "settings.json"), "w") as f:
            json.dump({"indexingAllowDirs": ["/idx"]}, f)
        tracker._AUGGIE_LIST_CACHE.clear()
        with open(os.path.join(tracker.AUGGIE_SESSIONS, "s.json"), "w") as f:
            json.dump({"sessionId": "s", "modified": "2026-06-27T05:48:03Z",
                       "customTitle": "Do a thing",
                       "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
                           "request_message": "please do a thing",
                           "response_text": "doing it now",
                           "request_nodes": [{"ide_state_node": {"current_terminal": {
                               "current_working_directory": "/work/repo"}}}],
                           "response_nodes": [
                               {"token_usage": {"input_tokens": 5, "output_tokens": 7,
                                                "cache_read_input_tokens": 50}},
                               {"tool_use": {"tool_name": "launch-process",
                                             "input_json": {"command": "pytest -q"}}},
                               {"tool_use": {"tool_name": "view",
                                             "input_json": {"path": "x.py", "type": "file"}}}]}}]}, f)

    def tearDown(self):
        _restore(self.snap)

    def test_detail_parity(self):
        d = tracker.parse_auggie("s")
        self.assertEqual(d["meta"]["source"], "auggie")
        self.assertEqual(d["meta"]["cwd"], "/work/repo")            # real IDE cwd, not the fallback
        self.assertEqual(d["tokens"], {"in": 55, "out": 7})         # input + cache, like Claude
        self.assertEqual(len(d["commands"]), 1)                     # launch-process -> command
        self.assertEqual(d["counts"]["read"], 1)                    # view -> read
        self.assertEqual(d["counts"]["tests"], 1)                   # pytest classified
        self.assertEqual([r["text"] for r in d["requests"]], ["please do a thing"])
        self.assertIn("doing it now", [n["text"] for n in d["narrative"]])

    def test_list_uses_ide_cwd(self):
        al = tracker.list_auggie()
        self.assertEqual(len(al), 1)
        self.assertEqual(al[0]["title"], "Do a thing")             # customTitle wins
        self.assertEqual(al[0]["project"], "repo")                 # basename of the real IDE cwd

    def test_search_hits_and_ranks_title(self):
        hits = tracker.search_auggie("do a thing")
        self.assertTrue(any(h["id"] == "auggie:s" and h["titleMatch"] for h in hits))
        self.assertEqual(tracker.search_auggie("zzznotfoundzzz"), [])


class TestProviders(unittest.TestCase):
    def test_parse_any_routes_by_prefix(self):
        # unknown ids route to the owning provider and return None, not raise
        self.assertIsNone(tracker.parse_any("auggie:does-not-exist"))
        self.assertIsNone(tracker.parse_any("no-such-claude-session-id"))

    def test_registry_present(self):
        self.assertTrue(tracker.PROVIDERS, "at least one provider must be registered")
        prefixes = {p.prefix for p in tracker.PROVIDERS}
        self.assertIn("auggie:", prefixes)
        self.assertIn("", prefixes)   # the default (Claude) provider


if __name__ == "__main__":
    unittest.main()
