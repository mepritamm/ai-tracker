"""Session isolation: the client seam in aitracker/web/app.js, executed under Node.

Pieces are sliced verbatim out of app.js (never retyped) and run against mocked fetch/DOM, the
idiom of tests/test_integration.py. Skipped when `node` is not on PATH.
Other test classes (static sweep, control-room harness) are appended below by later stages.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _block(src, start_marker, func_marker):
    """From start_marker through the closing brace of the function introduced by func_marker."""
    start = src.index(start_marker)
    i = src.index("{", src.index(func_marker, start))
    depth = 0
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return src[start:i + 1]


_MOCKS = """
'use strict';
var cur = "", timer = null, lastData = null;
var __renders = [], __fetches = [], __intervals = 0;
var __els = {};
var __main = { dataset: {} };
var document = { querySelector: function (s) { return s === "main" ? __main : null; }, title: "" };
var localStorage = { setItem: function () {} };
var uiState = { set: function () {} };
function $(id) { return __els[id] || (__els[id] = { value: "", innerHTML: "", textContent: "", style: {} }); }
function setInterval() { __intervals++; return 1; }
function clearInterval() {}
function render(d) { __renders.push({ id: d.id, sess: __main.dataset.sess }); }
function loadFlags() {}
function checkCompletions() {}
function esc(s) { return String(s); }
function fetch(url, opts) {
  return new Promise(function (resolve, reject) {
    __fetches.push({ url: url, opts: opts || {}, resolve: resolve, reject: reject });
  });
}
function __ok(i, body) {
  __fetches[i].resolve({ ok: true, json: function () { return Promise.resolve(body); } });
}
function __pick(sid) { $("sid").value = sid; track(); }
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestSessionSeamExecuted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "aitracker", "web", "app.js"), encoding="utf-8") as fh:
            src = fh.read()
        cls.js = (
            _MOCKS
            + _block(src, "function track(){", "function track(){") + "\n"
            + _block(src, "let sessEpoch=0;", "function resetSession(") + "\n"
            + _block(src, "let pollBusy=false", "async function poll(){") + "\n"
        )

    def _run(self, body):
        script = self.js + "\n(async function(){\n" + body + "\n})().catch(function(e){console.error(e.stack||String(e));process.exit(1);});\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(script)
            proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError("node exit %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
        return json.loads(proc.stdout.strip().splitlines()[-1])

    # (1) sessJSON drops a response whose (sid, epoch) moved -- including A -> B -> A
    def test_sessJSON_stale_when_selection_moves(self):
        r = self._run("""
cur = "A";
var p = sessJSON("/x");
cur = "B";
__ok(0, {v: 1});
var moved = await p;
cur = "A";
var p2 = sessJSON("/y");
resetSession("B", "A"); cur = "B"; resetSession("A", "B"); cur = "A";   // A -> B -> A: sid equal, epoch not
__ok(1, {v: 2});
var back = await p2;
cur = "A";
var p3 = sessJSON("/z"); __ok(2, {v: 3});
var live = await p3;
console.log(JSON.stringify({moved: moved === STALE, back: back === STALE, live: live && live.v}));
""")
        self.assertTrue(r["moved"])
        self.assertTrue(r["back"], "A->B->A must still be stale: the epoch moved though cur is back")
        self.assertEqual(r["live"], 3)

    # (2) GET rides the abort signal, POST does not
    def test_sessJSON_get_has_signal_post_does_not(self):
        r = self._run("""
cur = "A";
var g = sessJSON("/g"); var p = sessJSON("/p", {method: "POST", body: "{}"});
__ok(0, {}); __ok(1, {});
await g; await p;
var gs = __fetches[0].opts.signal, aborted0 = gs.aborted;
resetSession("B", "A");
console.log(JSON.stringify({getSignal: !!gs, postSignal: !!__fetches[1].opts.signal, abortedBefore: aborted0, abortedAfter: gs.aborted}));
""")
        self.assertTrue(r["getSignal"])
        self.assertFalse(r["postSignal"])
        self.assertFalse(r["abortedBefore"])
        self.assertTrue(r["abortedAfter"], "a switch must abort in-flight GETs")

    # (3) track() with A's poll in flight issues B's fetch synchronously (no 2s wait)
    def test_track_fires_new_poll_synchronously_while_old_in_flight(self):
        r = self._run("""
__pick("A");
var afterA = __fetches.length;     // A's poll pending, pollBusy true
__pick("B");
var syncAfterB = __fetches.length; // must already include B's fetch
console.log(JSON.stringify({afterA: afterA, syncAfterB: syncAfterB, urlB: __fetches[1] && __fetches[1].url}));
""")
        self.assertEqual(r["afterA"], 1)
        self.assertEqual(r["syncAfterB"], 2, "B's first fetch must not wait for the next 2s tick")
        self.assertTrue(r["urlB"].endswith("id=B"))

    # (4) hooks fire only on a real change, with (next, prev)
    def test_reset_hooks_only_on_change(self):
        r = self._run("""
var calls = [];
onSessionReset(function (n, p) { calls.push([n, p]); });
__pick("A"); var afterFirst = calls.length;
__pick("A"); var afterSame = calls.length;
__pick("B");
console.log(JSON.stringify({afterFirst: afterFirst, afterSame: afterSame, calls: calls}));
""")
        self.assertEqual(r["afterFirst"], 1)
        self.assertEqual(r["afterSame"], 1, "re-picking the same sid must not reset")
        self.assertEqual(r["calls"], [["A", ""], ["B", "A"]])

    # (5) renderFor / cache refuse mismatched ids; LRU caps at 8
    def test_renderFor_and_cache_refuse_mismatch(self):
        r = self._run("""
cur = "A";
var okMatch = renderFor("A", {id: "A"});
var badId = renderFor("A", {id: "B"});
var badCur = renderFor("B", {id: "B"});
var noId = renderFor("A", {});
sessCachePut("X", {id: "Y"});
var mismatchStored = sessCacheGet("X");
for (var i = 0; i < 10; i++) sessCachePut("s" + i, {id: "s" + i});
console.log(JSON.stringify({okMatch: okMatch, badId: badId, badCur: badCur, noId: noId, mismatchStored: mismatchStored,
  size: SESS_CACHE.size, oldest: sessCacheGet("s0"), newest: !!sessCacheGet("s9"), renders: __renders.length}));
""")
        self.assertTrue(r["okMatch"])
        self.assertFalse(r["badId"])
        self.assertFalse(r["badCur"])
        self.assertFalse(r["noId"])
        self.assertIsNone(r["mismatchStored"])
        self.assertEqual(r["size"], 8)
        self.assertIsNone(r["oldest"])
        self.assertTrue(r["newest"])
        self.assertEqual(r["renders"], 1)

    # (6) cache hit paints before the fetch resolves, marked refreshing; miss is "loading"
    def test_cache_hit_paints_refreshing_miss_is_loading(self):
        r = self._run("""
cur = "";
sessCachePut("B", {id: "B"});
__pick("A");
var missMark = __main.dataset.sess, rendersAfterA = __renders.length;
__pick("B");
var hitMark = __main.dataset.sess, hit = __renders.slice();   // painted synchronously, fetch unresolved
__ok(1, {id: "B", now: 1});
await new Promise(function (r) { setTimeout(r, 20); });
console.log(JSON.stringify({missMark: missMark, rendersAfterA: rendersAfterA, hitMark: hitMark, hit: hit,
  finalMark: __main.dataset.sess === undefined ? null : __main.dataset.sess, nFetch: __fetches.length}));
""")
        self.assertEqual(r["missMark"], "loading")
        self.assertEqual(r["rendersAfterA"], 0)
        self.assertEqual(r["hitMark"], "refreshing")
        self.assertEqual(r["hit"], [{"id": "B", "sess": "refreshing"}])
        self.assertIsNone(r["finalMark"], "the fresh poll must clear the refreshing mark")


if __name__ == "__main__":
    unittest.main()
