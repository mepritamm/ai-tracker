#!/usr/bin/env python3
"""parse_agents per-file cache: the golden test pins today's merge semantics (written and
green on the pre-cache code), the rest pin the cache's own contract."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from aitracker.providers import claude
from aitracker.providers.claude import parse_agents, parse_session

LEGACY = ("id", "aid", "wf", "task", "last", "ts", "tools", "running", "model")


def _write(path, lines):
    with open(path, "w") as fh:
        for o in lines:
            fh.write(json.dumps(o) + "\n")


def _asst(ts, blocks, mid=None, usage=None, model="claude-opus-4-5"):
    m = {"content": blocks}
    if mid:
        m["id"] = mid
        m["model"] = model
    if usage:
        m["usage"] = usage
    o = {"type": "assistant", "message": m}
    if ts:
        o["timestamp"] = ts
    return o


def _res(ts, tid, text):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}


def _tu(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def make_fixture(root):
    """3 agent files exercising every cross-file merge rule parse_agents has."""
    main = os.path.join(root, "sess.jsonl")
    _write(main, [{"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}])
    adir = os.path.join(root, "sess", "subagents")
    os.makedirs(adir)
    U = {"input_tokens": 10, "output_tokens": 5, "cache_creation_input_tokens": 2, "cache_read_input_tokens": 3}
    url = "https://github.com/o/r/pull/7"
    _write(os.path.join(adir, "agent-aaa111.jsonl"), [
        {"type": "user", "message": {"role": "user", "content": "task aaa"}},
        _asst("2026-07-13T11:00:00Z", [
            _tu("b1", "Bash", {"command": "gh pr create --title t"}),
            _tu("e1", "Edit", {"file_path": "/x/shared.py", "old_string": "a", "new_string": "b"})],
            "ma1", U),
        _res("2026-07-13T11:00:05Z", "b1", url),
        _asst("2026-07-13T11:01:00Z", [
            _tu("b2", "Bash", {"command": "gh pr close 7 && gh pr merge 8"}),
            {"type": "text", "text": "done aaa"}], "ma2", U),
        _res("2026-07-13T11:01:09Z", "b2", "ok"),
    ])
    _write(os.path.join(adir, "agent-bbb222.jsonl"), [
        {"type": "user", "message": {"role": "user", "content": "task bbb"}},
        _asst("2026-07-13T10:05:00Z", [
            _tu("b3", "Bash", {"command": "echo hi"}),
            _tu("w1", "Write", {"file_path": "/x/shared.py", "content": "x"})], "mb1", U),
        _res("2026-07-13T10:06:00Z", "b3", "see " + url + "\nMerge pull request #7 from o/br"),
        _asst("2026-07-13T10:07:00Z", [{"type": "text", "text": "last bbb"}], "mb2", U),
    ])
    _write(os.path.join(adir, "agent-ccc333.jsonl"), [
        {"type": "user", "message": {"role": "user", "content": "task ccc"}},
        _asst(None, [_tu("e2", "Edit", {"file_path": "/x/c.py", "old_string": "a", "new_string": "b"})], "mc1", U),
        _asst("2026-07-13T09:00:00Z", [
            _tu("b4", "Bash", {"command": "gh pr close 8"}),
            _tu("e3", "Edit", {"file_path": "/x/c.py", "old_string": "b", "new_string": "c"})], "mc2", U),
        _res("2026-07-13T09:00:30Z", "b4", "closed"),
    ])
    return main


def legacy(rows):
    return [{k: r[k] for k in LEGACY} for r in rows]


def hbd():
    return {"turns": [], "calls": [], "iv": {}, "labels": {}}


# Frozen from the PRE-cache parse_agents. `last` on /x/shared.py is the LATER-sorted file's
# value (bbb's 10:05), not the max (aaa's 11:00); PR 7 closed-then-merged and PR 8 merged-then-
# closed both end "merged"; the PR's `t` is the max across files and `created` is sticky.
GOLDEN = {
    "files": {
        "/x/c.py": {"agent": True, "created": False, "last": "2026-07-13T09:00:00Z", "ops": 2, "path": "/x/c.py"},
        "/x/shared.py": {"agent": True, "created": True, "last": "2026-07-13T10:05:00Z", "ops": 2,
                         "path": "/x/shared.py"},
    },
    "hb": {
        "calls": [(1783940400.0, "Bash", "aaa111"), (1783940400.0, "Edit", "aaa111"),
                  (1783940460.0, "Bash", "aaa111"), (1783937100.0, "Bash", "bbb222"),
                  (1783937100.0, "Write", "bbb222"), (0.0, "Edit", "ccc333"),
                  (1783933200.0, "Bash", "ccc333"), (1783933200.0, "Edit", "ccc333")],
        "iv": {"Bash": [(1783940400.0, 1783940405.0), (1783940460.0, 1783940469.0),
                        (1783937100.0, 1783937160.0), (1783933200.0, 1783933230.0)]},
        "labels": {"aaa111": ("task aaa", "claude-opus-4-5"), "bbb222": ("task bbb", "claude-opus-4-5"),
                   "ccc333": ("task ccc", "claude-opus-4-5")},
        "turns": [(1783940400.0, "claude-opus-4-5", 5, 12, 3, "aaa111"),
                  (1783940460.0, "claude-opus-4-5", 5, 12, 3, "aaa111"),
                  (1783937100.0, "claude-opus-4-5", 5, 12, 3, "bbb222"),
                  (1783937220.0, "claude-opus-4-5", 5, 12, 3, "bbb222"),
                  (0.0, "claude-opus-4-5", 5, 12, 3, "ccc333"),
                  (1783933200.0, "claude-opus-4-5", 5, 12, 3, "ccc333")],
    },
    "prs": {"https://github.com/o/r/pull/7": {
        "agent": True, "created": True, "narr": False, "num": "7", "repo": "o/r", "state": "",
        "t": "2026-07-13T11:00:05Z", "url": "https://github.com/o/r/pull/7"}},
    "pst": {"7": "merged", "8": "merged"},
    "rows": [
        {"aid": "ccc333", "id": "ccc333", "last": "", "model": "claude-opus-4-5", "running": True,
         "task": "task ccc", "tools": 3, "ts": "2026-07-13T09:00:30Z", "wf": ""},
        {"aid": "bbb222", "id": "bbb222", "last": "last bbb", "model": "claude-opus-4-5", "running": True,
         "task": "task bbb", "tools": 2, "ts": "2026-07-13T10:07:00Z", "wf": ""},
        {"aid": "aaa111", "id": "aaa111", "last": "done aaa", "model": "claude-opus-4-5", "running": True,
         "task": "task aaa", "tools": 3, "ts": "2026-07-13T11:01:09Z", "wf": ""},
    ],
}


class TestAgentCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.main = make_fixture(self.dir)
        if hasattr(claude, "_AGENT_CACHE"):
            claude._AGENT_CACHE.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_golden_vs_base(self):
        hb = hbd()
        rows, newest, files, prs, pst = parse_agents(self.main, hb)
        self.assertEqual(GOLDEN, dict(rows=legacy(rows), files=files, prs=prs, pst=pst, hb=hb))

    # -- helpers -------------------------------------------------------------------------
    def _adir(self):
        return os.path.join(self.dir, "sess", "subagents")

    def _touch(self, aid):
        """Append a message to agent `aid` (changes size + mtime => new cache key)."""
        with open(os.path.join(self._adir(), "agent-%s.jsonl" % aid), "a") as fh:
            fh.write(json.dumps(_asst("2026-07-13T12:00:00Z", [{"type": "text", "text": "more"}])) + "\n")

    def _count_opens(self, fn):
        real_open, opened = open, []

        def counting(path, *a, **k):
            opened.append(str(path))
            return real_open(path, *a, **k)
        with mock.patch("aitracker.providers.claude.open", counting, create=True):
            fn()
        return [p for p in opened if p.endswith(".jsonl")]

    def _everything(self):
        hb = hbd()
        rows, newest, files, prs, pst = parse_agents(self.main, hb)
        return dict(rows=rows, newest=newest, files=files, prs=prs, pst=pst, hb=hb)

    # -- cache contract ------------------------------------------------------------------
    def test_warm_call_opens_zero_files(self):
        self.assertEqual(len(self._count_opens(lambda: parse_agents(self.main, hbd()))), 3)   # cold
        self.assertEqual(self._count_opens(lambda: parse_agents(self.main, hbd())), [])      # warm

    def test_touched_file_is_reread_alone(self):
        parse_agents(self.main, hbd())
        self._touch("bbb222")
        opened = self._count_opens(lambda: parse_agents(self.main, hbd()))
        self.assertEqual([os.path.basename(p) for p in opened], ["agent-bbb222.jsonl"])

    def test_sidecar_change_invalidates(self):
        parse_agents(self.main, hbd())
        with open(os.path.join(self._adir(), "agent-aaa111.meta.json"), "w") as fh:
            json.dump({"description": "now described"}, fh)
        rows = parse_agents(self.main)[0]
        self.assertEqual(next(r for r in rows if r["aid"] == "aaa111")["desc"], "now described")

    def test_sidecar_growth_within_same_mtime_invalidates(self):
        # Claude Code grows a sidecar in place (e.g. adds "finished": true). On a coarse-mtime
        # filesystem the rewrite can land in the same mtime tick, so the key must carry size too.
        # ponytail: a same-length rewrite in the same tick is still a hit — stat can't see it.
        side = os.path.join(self._adir(), "agent-aaa111.meta.json")
        with open(side, "w") as fh:
            json.dump({"description": "AAAA"}, fh)
        parse_agents(self.main, hbd())                       # warm the cache
        orig = os.stat(side)
        with open(side, "w") as fh:
            json.dump({"description": "BBBB", "finished": True}, fh)   # longer file
        os.utime(side, ns=(orig.st_atime_ns, orig.st_mtime_ns))       # same mtime tick
        rows = parse_agents(self.main, hbd())[0]
        self.assertEqual(next(r for r in rows if r["aid"] == "aaa111")["desc"], "BBBB")

    def test_cold_equals_warm_including_hb(self):
        with mock.patch.dict(os.environ, {"AITRACKER_NO_AGENT_CACHE": "1"}):
            nocache = self._everything()
            self.assertEqual(len(claude._AGENT_CACHE), 0)          # kill-switch really bypasses it
        cold = self._everything()
        warm = self._everything()
        self.assertEqual(cold, warm)
        self.assertEqual(nocache, warm)

    def test_no_aliasing_across_parse_session_calls(self):
        d1 = parse_session(self.main)
        d2 = parse_session(self.main)
        self.assertEqual(d1["prs"], d2["prs"])
        self.assertEqual(d1["files"], d2["files"])
        d1["prs"][0]["state"] = "POISON"
        d1["files"][0]["ops"] = 999
        d1["agents_bg"][0]["task"] = "POISON"
        d3 = parse_session(self.main)
        self.assertEqual(d3["prs"], d2["prs"])
        self.assertEqual(d3["files"], d2["files"])
        self.assertNotEqual(d3["agents_bg"][0]["task"], "POISON")
        # the CACHED PR/file entries were never written through
        for _key, ent in claude._AGENT_CACHE.values():
            for pe in ent["prs"].values():
                self.assertEqual(pe["state"], "")
                self.assertNotIn("agent", pe)
            for fe in ent["files"].values():
                self.assertLessEqual(fe["ops"], 2)

    def test_hb_survives_a_prior_call_without_hb(self):
        parse_agents(self.main)                      # no hb: must still cache the hb parts
        d = parse_session(self.main)
        rows = d["heartbeat"]["by_agent"]["rows"]
        self.assertEqual({r["aid"] for r in rows if r["aid"]}, {"aaa111", "bbb222", "ccc333"})

    def test_eviction_drops_oldest_and_retouch_moves_to_newest(self):
        for a in ("ddd", "eee", "fff", "ggg"):
            self._touch_new(a)
        path = lambda a: os.path.join(self._adir(), "agent-%s.jsonl" % a)
        keys = lambda: [os.path.basename(k)[6:-6] for k in claude._AGENT_CACHE]
        with mock.patch.object(claude, "_AGENT_CACHE_MAX", 4):
            for a in ("aaa111", "bbb222", "ccc333", "ddd", "eee"):
                claude._agent_entry(path(a))       # 5th insert overflows: oldest half (2) goes
            self.assertEqual(keys(), ["ccc333", "ddd", "eee"])
            self._touch("ccc333")
            claude._agent_entry(path("ccc333"))    # re-read: pop-then-set => NEWEST slot
            self.assertEqual(keys(), ["ddd", "eee", "ccc333"])
            claude._agent_entry(path("fff"))
            claude._agent_entry(path("ggg"))       # overflow again: ddd+eee go, ccc333 survives
            self.assertEqual(keys(), ["ccc333", "fff", "ggg"])

    def _touch_new(self, aid):
        _write(os.path.join(self._adir(), "agent-%s.jsonl" % aid),
               [_asst("2026-07-13T08:00:00Z", [{"type": "text", "text": aid}], "m" + aid)])
