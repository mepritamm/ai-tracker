"""Augment VSCode / Cursor extension provider — reads workspaceStorage/<hash>/
Augment.vscode-augment/{task-storage,agent-edits}. The chat transcript lives in
LevelDB (binary) so this provider surfaces todos + files-touched + a synthetic
note in the narrative panel."""
import json
import os
import tempfile
import unittest

from aitracker import config
from aitracker.providers.augment_ext import (
    AugmentVscodeProvider, AugmentCursorProvider,
    _decode_folder, _files_touched, _resolve_subtasks, _title_for)


def _mk_workspace(root, ws_hash, folder_uri, tasks=(), shards=()):
    """Build a `<root>/<ws_hash>/Augment.vscode-augment/…` tree matching the real layout."""
    ws_dir = os.path.join(root, ws_hash)
    aug = os.path.join(ws_dir, "Augment.vscode-augment")
    tasks_dir = os.path.join(aug, "augment-user-assets", "task-storage", "tasks")
    shards_dir = os.path.join(aug, "augment-user-assets", "agent-edits", "shards")
    os.makedirs(tasks_dir)
    os.makedirs(shards_dir)
    with open(os.path.join(ws_dir, "workspace.json"), "w") as f:
        json.dump({"folder": folder_uri}, f)
    for t in tasks:
        with open(os.path.join(tasks_dir, t["uuid"] + ".json"), "w") as f:
            json.dump(t, f)
    for s in shards:
        with open(os.path.join(shards_dir, s["id"] + ".json"), "w") as f:
            json.dump(s, f)
    return aug


class TestPurePieces(unittest.TestCase):
    """The pure helpers — no filesystem, no config."""

    def test_decode_folder_strips_scheme_and_url_decodes(self):
        self.assertEqual(_decode_folder("file:///Users/x/my%20repo"), "/Users/x/my repo")
        self.assertEqual(_decode_folder(""), "")
        self.assertEqual(_decode_folder("/plain/path"), "/plain/path")   # no scheme -> passthrough

    def test_title_prefers_task_name_over_boilerplate(self):
        # the extension seeds every workspace with a "Current Task List" root — skip it
        self.assertEqual(_title_for({"name": "Current Task List"}, "/repo/x"), "x")
        self.assertEqual(_title_for({"name": "Fix the parser"}, "/repo/x"), "Fix the parser")
        self.assertEqual(_title_for({"name": ""}, "/repo/foo"), "foo")
        self.assertEqual(_title_for({}, ""), "Augment session")

    def test_subtask_resolution_maps_state_to_todo_status(self):
        root = {"uuid": "r", "subTasks": ["a", "b", "c"]}
        allmap = {
            "r": root,
            "a": {"uuid": "a", "name": "one", "state": "COMPLETE"},
            "b": {"uuid": "b", "name": "two", "state": "IN_PROGRESS"},
            "c": {"uuid": "c", "name": "three", "state": "NOT_STARTED"},
        }
        todos = _resolve_subtasks(root, allmap)
        self.assertEqual([t["content"] for t in todos], ["one", "two", "three"])
        self.assertEqual([t["status"] for t in todos],
                         ["completed", "in_progress", "pending"])

    def test_subtask_resolution_tolerates_cycles(self):
        # a malformed store with a cycle must not infinite-loop
        allmap = {
            "r": {"uuid": "r", "subTasks": ["a"]},
            "a": {"uuid": "a", "name": "loops", "state": "NOT_STARTED", "subTasks": ["r"]},
        }
        todos = _resolve_subtasks(allmap["r"], allmap)
        self.assertEqual([t["content"] for t in todos], ["loops"])   # `r` already seen -> skipped


class TestFilesTouched(unittest.TestCase):
    def test_dedupes_across_shards_keeps_latest_mtime(self):
        tmp = tempfile.mkdtemp()
        aug = _mk_workspace(tmp, "abc123", "file:///repo/x", shards=[
            {"id": "shard-1", "checkpoints": {
                "u1:/repo/x/a.py": {},
                "u1:/repo/x/b.py": {},
            }, "metadata": {"lastModified": 1000000}},
            {"id": "shard-2", "checkpoints": {
                "u2:/repo/x/a.py": {},   # SAME file, newer shard
                "u2:/repo/x/c.py": {},
            }, "metadata": {"lastModified": 2000000}},
        ])
        files = _files_touched(aug)
        paths = [f["path"] for f in files]
        self.assertEqual(sorted(paths), ["/repo/x/a.py", "/repo/x/b.py", "/repo/x/c.py"])
        # /repo/x/a.py should carry the newer shard's mtime (2000 vs 1000)
        a = next(f for f in files if f["path"] == "/repo/x/a.py")
        self.assertEqual(a["t"], 2000.0)

    def test_missing_shards_dir_returns_empty(self):
        self.assertEqual(_files_touched("/no/such/aug/dir"), [])


class TestProviderEndToEnd(unittest.TestCase):
    """Full round-trip with fresh temp roots — list/parse/search on both IDEs."""

    def setUp(self):
        self._orig_vs = config.VSCODE_WS_ROOT
        self._orig_cur = config.CURSOR_WS_ROOT
        config.VSCODE_WS_ROOT = tempfile.mkdtemp()
        config.CURSOR_WS_ROOT = tempfile.mkdtemp()

    def tearDown(self):
        config.VSCODE_WS_ROOT = self._orig_vs
        config.CURSOR_WS_ROOT = self._orig_cur

    def test_vscode_provider_lists_parses_searches(self):
        _mk_workspace(config.VSCODE_WS_ROOT, "wshash1", "file:///Users/me/proj%20one",
                      tasks=[
                          # the boilerplate root — must be present, must NOT dominate the title
                          {"uuid": "root", "name": "Current Task List", "state": "NOT_STARTED",
                           "subTasks": ["s1", "s2"], "lastUpdated": 1700000000000},
                          {"uuid": "s1", "name": "add helper", "state": "COMPLETE",
                           "description": "add get_x helper", "lastUpdated": 1700000100000},
                          {"uuid": "s2", "name": "wire tests", "state": "IN_PROGRESS",
                           "lastUpdated": 1700000200000},
                      ],
                      shards=[
                          {"id": "shard-a", "checkpoints": {
                              "u:/Users/me/proj one/foo.py": {},
                              "u:/Users/me/proj one/bar.py": {},
                          }, "metadata": {"lastModified": 1700000300000}},
                      ])

        p = AugmentVscodeProvider()
        self.assertTrue(p.available(), "should be available with a workspace on disk")
        rows = p.list()
        self.assertEqual(len(rows), 3, "one row per task file (root + 2 subs)")

        # id shape: "augment-vscode:<ws-hash>:<task-uuid>"
        s1 = next(r for r in rows if r["id"].endswith(":s1"))
        self.assertEqual(s1["id"], "augment-vscode:wshash1:s1")
        self.assertEqual(s1["source"], "augment-vscode")
        self.assertEqual(s1["project"], "proj one")          # URL-decoded from workspace.json
        self.assertEqual(s1["cwd"], "/Users/me/proj one")
        self.assertEqual(s1["title"], "add helper")
        self.assertTrue(s1["ended"], "COMPLETE task -> ended")

        s2 = next(r for r in rows if r["id"].endswith(":s2"))
        self.assertFalse(s2["ended"], "IN_PROGRESS -> not ended")

        # the boilerplate root shows folder basename, not "Current Task List"
        root = next(r for r in rows if r["id"].endswith(":root"))
        self.assertEqual(root["title"], "proj one")

        # parse — detail dict matches the shared shape
        d = p.parse("augment-vscode:wshash1:root")
        self.assertIsNotNone(d)
        self.assertEqual(d["meta"]["source"], "augment-vscode")
        self.assertEqual(d["meta"]["entrypoint"], "augment-vscode")
        self.assertEqual(d["meta"]["cwd"], "/Users/me/proj one")
        # todos flattened from the root's subTasks
        self.assertEqual([t["content"] for t in d["todos"]], ["add helper", "wire tests"])
        self.assertEqual(d["counts"]["done"], 1)
        self.assertEqual(d["counts"]["todos"], 2)
        # files touched — deduped, from agent-edit shards
        paths = sorted(f["path"] for f in d["files"])
        self.assertEqual(paths, ["/Users/me/proj one/bar.py", "/Users/me/proj one/foo.py"])
        self.assertEqual(d["counts"]["edited"], 2)
        # honesty note: the narrative panel explains what's missing
        self.assertTrue(d["narrative"], "narrative must not be empty")
        self.assertIn("LevelDB", d["narrative"][0]["text"])
        # shape parity with other providers (SPA renders these keys uniformly)
        for k in ("reads", "commands", "commits", "tests", "requests",
                  "agents", "agents_bg", "shells", "decisions", "prs"):
            self.assertIn(k, d)
        # no chat transcript survives stdlib-only (LevelDB) -> honestly empty, not a fabricated 0
        self.assertEqual(d["context"], {"current": None, "limit": None, "pct": None})

        # parse of a bogus id returns None (doesn't crash)
        self.assertIsNone(p.parse("augment-vscode:nope:nope"))
        self.assertIsNone(p.parse("augment-vscode:wshash1:missing-uuid"))
        self.assertIsNone(p.parse("not-my-prefix:x"))

        # search — matches task name AND description; empty query -> no hits
        self.assertEqual(p.search(""), [])
        hits = p.search("helper")
        self.assertTrue(any(h["id"].endswith(":s1") for h in hits))
        self.assertEqual(p.search("zzznotfoundzzz"), [])

    def test_cursor_prefix_and_availability(self):
        _mk_workspace(config.CURSOR_WS_ROOT, "curhash1", "file:///repo/y",
                      tasks=[{"uuid": "t1", "name": "cursor task", "state": "NOT_STARTED",
                              "lastUpdated": 1700000000000}])
        p = AugmentCursorProvider()
        self.assertTrue(p.available())
        rows = p.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "augment-cursor:curhash1:t1")
        self.assertEqual(rows[0]["source"], "augment-cursor")

    def test_missing_root_disables_provider(self):
        # empty temp dir removed -> provider disabled, not crashing
        empty = tempfile.mkdtemp()
        os.rmdir(empty)
        config.VSCODE_WS_ROOT = empty
        p = AugmentVscodeProvider()
        self.assertFalse(p.available())
        self.assertEqual(p.list(), [])

    def test_search_result_shape_matches_shared_contract(self):
        """search() must emit the FULL shared search-result shape — {id, project,
        title, agent, matches, snippet, inQuery, titleMatch, mtime} — the same keys
        ClaudeProvider.search()/search_auggie() emit. It used to emit {id, titleMatch,
        inQuery, mtime, text, source} instead, so renderSide() (web/app.js), which
        reads s.title/s.project/s.matches/s.snippet, drew "undefined×" search rows
        for every augment-vscode/augment-cursor hit."""
        _mk_workspace(config.VSCODE_WS_ROOT, "wshash2", "file:///Users/me/proj%20two",
                      tasks=[
                          {"uuid": "t1", "name": "fix the parser bug", "state": "NOT_STARTED",
                           "description": "root cause was a stray token in the lexer",
                           "lastUpdated": 1700000000000},
                      ])
        p = AugmentVscodeProvider()
        expected_keys = {"id", "project", "title", "agent", "matches", "snippet",
                          "inQuery", "titleMatch", "mtime"}

        # term only in the title, not the description -> no snippet, inQuery False
        hits = p.search("parser")
        self.assertEqual(len(hits), 1)
        h = hits[0]
        self.assertEqual(set(h.keys()), expected_keys)
        self.assertEqual(h["id"], "augment-vscode:wshash2:t1")
        self.assertEqual(h["project"], "proj two")           # URL-decoded workspace folder basename
        self.assertEqual(h["title"], "fix the parser bug")
        self.assertIs(h["agent"], False)
        self.assertTrue(h["titleMatch"])
        self.assertFalse(h["inQuery"], "term only in the title, not the description")
        self.assertEqual(h["snippet"], "")

        # term only in the description -> inQuery True, a real snippet around the hit
        hits2 = p.search("lexer")
        self.assertEqual(len(hits2), 1)
        h2 = hits2[0]
        self.assertEqual(set(h2.keys()), expected_keys)
        self.assertFalse(h2["titleMatch"])
        self.assertTrue(h2["inQuery"])
        self.assertEqual(h2["matches"], 1)
        self.assertIn("lexer", h2["snippet"])

    def test_gitbranch_filled_from_folder_like_auggie(self):
        """meta.gitBranch used to be hardcoded "" even though the workspace folder
        is known — now reads the real branch via util._git_branch(folder), the same
        helper AuggieProvider already uses (providers/auggie.py) to reach parity."""
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(repo, ".git"))
        with open(os.path.join(repo, ".git", "HEAD"), "w") as f:
            f.write("ref: refs/heads/feature-x\n")
        _mk_workspace(config.VSCODE_WS_ROOT, "wshash3", "file://" + repo,
                      tasks=[{"uuid": "root", "name": "Current Task List", "state": "NOT_STARTED",
                              "lastUpdated": 1700000000000}])
        p = AugmentVscodeProvider()
        d = p.parse("augment-vscode:wshash3:root")
        self.assertEqual(d["meta"]["gitBranch"], "feature-x")

        # a workspace folder with no .git at all -> empty string, no crash
        _mk_workspace(config.VSCODE_WS_ROOT, "wshash4", "file:///no/such/repo",
                      tasks=[{"uuid": "root", "name": "Current Task List", "state": "NOT_STARTED",
                              "lastUpdated": 1700000000000}])
        d2 = p.parse("augment-vscode:wshash4:root")
        self.assertEqual(d2["meta"]["gitBranch"], "")


if __name__ == "__main__":
    unittest.main()
