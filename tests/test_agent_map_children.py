#!/usr/bin/env python3
"""agent_sessions_n / agent_map_n: SDK child sessions counted in a pre-pass over ALL sessions
(not just the `limit` window), re-runs collapsed like the panel, and the registry seam's sum/backfill."""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, registry
from aitracker.providers.auggie import AuggieProvider, _AUGGIE_LIST_CACHE
from aitracker.providers.claude import child_agent_sessions, list_sessions


def _mk(d, fn, ep, ts, content, age):
    p = os.path.join(d, fn)
    with open(p, "w") as fh:
        fh.write(json.dumps({"cwd": "/repo/x", "entrypoint": ep, "timestamp": ts,
                             "message": {"role": "user", "content": content}}) + "\n")
    t = time.time() - age
    os.utime(p, (t, t))


class ChildCount(unittest.TestCase):
    def setUp(self):
        self._snap = config.PROJECTS
        config.PROJECTS = tempfile.mkdtemp()
        self.d = os.path.join(config.PROJECTS, "-repo-x")
        os.makedirs(self.d)

    def tearDown(self):
        shutil.rmtree(config.PROJECTS, ignore_errors=True)
        config.PROJECTS = self._snap

    def test_child_counted_outside_list_window(self):
        _mk(self.d, "parent.jsonl", "cli", "2026-06-01T10:00:00Z", "orchestrate", 10)        # newest
        _mk(self.d, "kid.jsonl", "sdk-cli", "2026-06-01T11:00:00Z", "finding", 5000)         # outside limit=1
        rows = {r["id"]: r for r in list_sessions(limit=1)}
        self.assertEqual(set(rows), {"parent"})
        self.assertEqual(rows["parent"]["agent_sessions_n"], 1)
        self.assertEqual(len(child_agent_sessions("parent", self.d)), 1)

    def test_reruns_collapse_like_panel(self):
        _mk(self.d, "parent.jsonl", "cli", "2026-06-01T10:00:00Z", "orchestrate", 10)
        _mk(self.d, "r1.jsonl", "sdk-cli", "2026-06-01T11:00:00Z", "same task", 300)
        _mk(self.d, "r2.jsonl", "sdk-cli", "2026-06-01T11:30:00Z", "same task", 200)
        rows = {r["id"]: r for r in list_sessions()}
        self.assertEqual(rows["parent"]["agent_sessions_n"], 1)
        self.assertEqual(len(child_agent_sessions("parent", self.d)), 1)
        self.assertEqual(rows["r1"]["agent_sessions_n"], 0)

    def test_same_id_in_two_dirs_counts_per_dir(self):
        dir_b = os.path.join(config.PROJECTS, "-repo-y")
        os.makedirs(dir_b)
        _mk(self.d, "X.jsonl", "cli", "2026-06-01T10:00:00Z", "orchestrate", 10)
        _mk(self.d, "kidA.jsonl", "sdk-cli", "2026-06-01T11:00:00Z", "task one", 300)
        _mk(dir_b, "X.jsonl", "cli", "2026-06-01T10:00:00Z", "orchestrate", 10)
        _mk(dir_b, "kidB.jsonl", "sdk-cli", "2026-06-01T11:00:00Z", "task two", 300)
        rows = [r for r in list_sessions() if r["id"] == "X"]
        self.assertEqual(len(rows), 2)
        for r in rows:
            self.assertEqual(r["agent_sessions_n"], 1)
        for dir_path in (self.d, dir_b):
            self.assertEqual(len(child_agent_sessions("X", dir_path)), 1)


class RegistrySeam(unittest.TestCase):
    def test_registry_agent_map_n_sums_and_backfills(self):
        class Fake:
            prefix = "fake:"

            def available(self):
                return True

            def list(self):
                return [{"id": "fake:a", "mtime": 2},
                        {"id": "fake:b", "mtime": 1, "agent_files_n": 2, "agent_sessions_n": 3}]
        with mock.patch.object(registry, "PROVIDERS", [Fake()]):
            rows = {r["id"]: r for r in registry.all_sessions()}
        a, b = rows["fake:a"], rows["fake:b"]
        self.assertEqual((a["agent_files_n"], a["agent_sessions_n"], a["agent_map_n"]), (0, 0, 0))
        self.assertEqual(b["agent_map_n"], 5)

    def test_auggie_row_agent_map_n_zero(self):
        snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        _AUGGIE_LIST_CACHE.clear()
        try:
            with open(os.path.join(config.AUGGIE_SESSIONS, "s1.json"), "w") as fh:
                json.dump({"sessionId": "s1", "modified": "2026-06-27T05:48:03Z", "customTitle": "T",
                           "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                                            "exchange": {"request_message": "hi", "response_text": "yo"}}]}, fh)
            with mock.patch.object(registry, "PROVIDERS", [AuggieProvider()]):
                rows = registry.all_sessions()
            self.assertEqual([r["agent_map_n"] for r in rows], [0])
        finally:
            shutil.rmtree(config.AUGMENT_DIR, ignore_errors=True)
            config.AUGMENT_DIR, config.AUGGIE_SESSIONS = snap
            _AUGGIE_LIST_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
