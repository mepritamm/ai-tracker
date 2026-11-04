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
var __events = [];
var document = { querySelector: function (s) { return s === "main" ? __main : null; }, title: "",
  dispatchEvent: function (e) { __events.push(e.detail); } };
var localStorage = { setItem: function () {} };
var uiState = { set: function () {} };
function $(id) { return __els[id] || (__els[id] = { value: "", innerHTML: "", textContent: "", style: {}, dataset: {} }); }
var __row = null, __added = [], __renderSideCalls = 0;
var __sels = [], __oldRemoved = 0;
var __oldRow = { classList: { remove: function (c) { if (c === "active") __oldRemoved++; } } };
__els.slist = { querySelector: function (q) { __sels.push(q); return __row; },
  querySelectorAll: function (q) { __sels.push(q); return [__oldRow]; } };
var sessions = [], selEntry = null, autoExpandedFor = null, searchResults = null;
var CSS = { escape: function (s) { return String(s); } };
function renderSide() { __renderSideCalls++; }
function closeDrawer() {}
function toast() {}
function renderNotes() {}
function pushSays() { return {toast: "", tip: "", chip: ""}; }
var __t0 = 1700000000000;
Date.now = function () { return __t0; };
function __at(sec) { __t0 = 1700000000000 + sec * 1000; }
function setInterval() { __intervals++; return 1; }
function clearInterval() {}
function render(d) { __renders.push({ id: d.id, sess: __main.dataset.sess, refreshing: sessRefreshing, snapLabel: sessSnapLabel, d: d }); }
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
function __status(i, status, body) {
  __fetches[i].resolve({ ok: false, status: status, json: function () { return Promise.resolve(body); } });
}
function __reject(i, err) { __fetches[i].reject(err); }
function __tick() { return new Promise(function (r) { setTimeout(r, 15); }); }
function __grace() { return new Promise(function (r) { setTimeout(r, SNAP_GRACE_MS + 30); }); }   // past the snapshot grace timer
function __st() { return { mark: __main.dataset.sess === undefined ? null : __main.dataset.sess, label: sessSnapLabel,
  refreshing: sessRefreshing, renders: __renders.length, nev: __events.length, ev: __events[__events.length - 1] || null }; }
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
            + _block(src, "function sideMarkActive(", "function sideMarkActive(") + "\n"
            + _block(src, "function pick(id)", "function pick(id)") + "\n"
            + _block(src, "async function removeNote(", "async function removeNote(") + "\n"
            + _block(src, "async function pushNote(", "async function pushNote(") + "\n"
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
snapTtlMin = 30;
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
cur = ""; snapTtlMin = 30;
sessCachePut("B", {id: "B"});
__pick("A");
var missMark = __main.dataset.sess, rendersAfterA = __renders.length;
__pick("B");
var inGraceMark = __main.dataset.sess, inGraceRenders = __renders.length;   // nothing old inside the grace
await __grace();
var hitMark = __main.dataset.sess, hit = __renders.slice();   // painted after the grace, fetch unresolved
__ok(1, {id: "B", now: 1});
await new Promise(function (r) { setTimeout(r, 20); });
console.log(JSON.stringify({missMark: missMark, rendersAfterA: rendersAfterA, hitMark: hitMark, hit: hit, inGraceMark: inGraceMark, inGraceRenders: inGraceRenders,
  finalMark: __main.dataset.sess === undefined ? null : __main.dataset.sess, nFetch: __fetches.length}));
""")
        self.assertEqual(r["missMark"], "loading")
        self.assertEqual(r["rendersAfterA"], 0)
        self.assertEqual((r["inGraceMark"], r["inGraceRenders"]), ("loading", 0), "the snapshot must not paint synchronously")
        self.assertEqual(r["hitMark"], "refreshing")
        self.assertEqual([(h["id"], h["sess"], h["refreshing"]) for h in r["hit"]], [("B", "refreshing", True)])
        self.assertTrue(r["hit"][0]["snapLabel"], "the snapshot must be painted with a label already set (board reads it inside render)")
        self.assertIsNone(r["finalMark"], "the fresh poll must clear the refreshing mark")

    # (7) C1: an uncached pick that errors must NOT un-hide the previous session's DOM
    def test_uncached_error_lands_as_error_state(self):
        r = self._run("""
__pick("A"); __ok(0, {id: "A", now: 1});
await new Promise(function (r) { setTimeout(r, 20); });
var afterA = __main.dataset.sess === undefined ? null : __main.dataset.sess;
__pick("C");                                   // uncached
__ok(1, {error: "not found"});
await new Promise(function (r) { setTimeout(r, 20); });
console.log(JSON.stringify({afterA: afterA, mark: __main.dataset.sess, err: __main.dataset.err, events: __events}));
""")
        self.assertIsNone(r["afterA"])
        self.assertEqual(r["mark"], "error", "A's DOM must stay hidden under C's failed load")
        self.assertEqual(r["err"], "not found")
        self.assertEqual(r["events"][0]["id"], "C")

    def test_cached_error_keeps_snapshot_and_next_land_clears_error(self):
        r = self._run("""
snapTtlMin = 30;
sessCachePut("B", {id: "B"});
__pick("B"); __ok(0, {error: "boom"});
await new Promise(function (r) { setTimeout(r, 20); });
var cachedMark = __main.dataset.sess === undefined ? null : __main.dataset.sess;
console.log(JSON.stringify({cachedMark: cachedMark}));
""")
        self.assertEqual(r["cachedMark"], "refreshing", "a failed refresh keeps the snapshot AND stays marked not-current")
        r2 = self._run("""
__pick("C"); __ok(0, {error: "boom"});
await new Promise(function (r) { setTimeout(r, 20); });
var e1 = __main.dataset.sess;
sessLanded("C", {id: "C", now: 1});
console.log(JSON.stringify({e1: e1, after: __main.dataset.sess === undefined ? null : __main.dataset.sess, err: __main.dataset.err === undefined ? null : __main.dataset.err}));
""")
        self.assertEqual(r2["e1"], "error")
        self.assertIsNone(r2["after"])
        self.assertIsNone(r2["err"])

    # (8) C2: the fresh render must not see refreshing:true; a mismatch must not clear it
    def test_fresh_render_sees_refreshing_false(self):
        r = self._run("""
snapTtlMin = 30;
sessCachePut("B", {id: "B"});
__pick("B"); await __grace();
var painted = __renders.slice();
__ok(0, {id: "B", now: 1});
await new Promise(function (r) { setTimeout(r, 20); });
console.log(JSON.stringify({painted: painted, last: __renders[__renders.length - 1]}));
""")
        self.assertTrue(r["painted"][0]["refreshing"])
        self.assertFalse(r["last"]["refreshing"], "fresh data rendered while sessRefreshing still true")

    def test_mismatched_land_does_not_clear_refreshing(self):
        r = self._run("""
snapTtlMin = 30;
sessCachePut("B", {id: "B"});
__pick("B"); await __grace();
var ok = sessLanded("B", {id: "X"});
console.log(JSON.stringify({ok: ok, mark: __main.dataset.sess, refreshing: sessRefreshing}));
""")
        self.assertFalse(r["ok"])
        self.assertEqual(r["mark"], "refreshing")
        self.assertTrue(r["refreshing"])

    # (9) C6: the classic reset hook empties the windowing counters
    def test_classic_reset_hook_clears_win(self):
        with open(os.path.join(ROOT, "aitracker", "web", "app.js"), encoding="utf-8") as fh:
            src = fh.read()
        hook = _block(src, "// Classic view's per-session state", "onSessionReset(function(){")
        r = self._run("""
var _win = {narr: 90, files: 60};
var curModal, curFiles, curDiffFile, curDiffOps, diffExpand, curDiffText, diffAllExpanded;
var curNarr, curCmds, curReqs, curOv, curShells, curAgents, curTodos, narrState, dSid, notifSession, notifRunning;
function closeDiff() {} function closeMsg() {} function clearDetailSearch() {}
""" + hook + ");" + """
resetSession("B", "A");
console.log(JSON.stringify({win: _win}));
""")
        self.assertEqual(r["win"], {})

    # ---- honest snapshot (plan P4.2-P4.5, P7) -------------------------------------------------
    def test_fresh_inside_grace_paints_no_snapshot(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B", now: 1});
__pick("B"); __ok(0, {id: "B", now: 2}); await __tick(); await __grace();
console.log(JSON.stringify({renders: __renders.map(function (x) { return [x.id, x.refreshing, x.d.snapshot_age == null]; }), timer: sessSnapTimer}));
""")
        self.assertEqual(r["renders"], [["B", False, True]], "only the fresh paint, no snapshot")
        self.assertIsNone(r["timer"])

    def test_switch_during_grace_never_paints_old(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"}); sessCachePut("A", {id: "A", now: 1});
__pick("B"); __pick("A"); __ok(1, {id: "A", now: 2}); await __tick(); await __grace();
console.log(JSON.stringify({renders: __renders.map(function (x) { return [x.id, x.d.snapshot_age == null]; }), mark: __main.dataset.sess, timer: sessSnapTimer}));
""")
        self.assertEqual(r["renders"], [["A", True]], "B's timer must not paint a snapshot over A's fresh data")
        self.assertIsNone(r.get("mark"))
        self.assertIsNone(r["timer"])

    def test_500_inside_grace_paints_then_keeps(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"});
__pick("B"); __status(0, 500, {error: "boom"}); await __tick();
console.log(JSON.stringify(Object.assign(__st(), {timer: sessSnapTimer})));
await __grace();
""")
        self.assertEqual((r["renders"], r["mark"], r["refreshing"], r["ev"]["cached"]), (1, "refreshing", True, True))
        self.assertIn("can't refresh", r["label"])
        self.assertIsNone(r["timer"])

    def test_snapshot_strips_live_fields(self):
        r = self._run("""
snapTtlMin = 30; __at(0);
sessCachePut("B", {id: "B", now: 100, term_tty: "t1", term_attached: true, waiting: true,
  overview: {now: "working", now_kind: "k", goal: "g"}});
__at(120); __pick("B"); await __grace();
var d = __renders[0].d, e = SESS_CACHE.get("B").d;
console.log(JSON.stringify({tty: d.term_tty, att: d.term_attached, w: d.waiting, on: d.overview.now, ok: d.overview.now_kind,
  goal: d.overview.goal, now: d.now, age: d.snapshot_age, eTty: e.term_tty, eW: e.waiting, eNow: e.overview.now}));
""")
        self.assertEqual((r["tty"], r["att"], r["w"], r["on"], r["ok"]), (None, False, False, "", ""))
        self.assertEqual((r["goal"], r["now"], r["age"]), ("g", 220, 120))
        self.assertEqual((r["eTty"], r["eW"], r["eNow"]), ("t1", True, "working"), "the cached entry itself must not be edited")

    def test_over_age_snapshot_not_painted(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"});
SESS_CACHE.get("B").at -= (30 * 60 + 1) * 1000;
__pick("B");
console.log(JSON.stringify(Object.assign(__st(), {has: SESS_CACHE.has("B")})));
""")
        self.assertEqual(r["renders"], 0)
        self.assertEqual(r["mark"], "loading")
        self.assertFalse(r["has"], "an expired entry is deleted by the one reader")

    def test_no_ttl_heard_paints_no_snapshot(self):
        r = self._run("""
snapTtlMin = 0; sessCachePut("B", {id: "B"});
__pick("B");
console.log(JSON.stringify(__st()));
""")
        self.assertEqual(r["renders"], 0)
        self.assertEqual(r["mark"], "loading")

    def test_404_purges_and_errors(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"}); sessCachePut("C", {id: "C"});
__pick("B"); __status(0, 404, {error: "not found"}); await __tick();
console.log(JSON.stringify(Object.assign(__st(), {hasB: SESS_CACHE.has("B"), hasC: SESS_CACHE.has("C")})));
""")
        self.assertEqual(r["mark"], "error")
        self.assertFalse(r["hasB"], "a deleted session's snapshot must be purged")
        self.assertTrue(r["hasC"])
        self.assertFalse(r["ev"]["cached"])

    def test_401_clears_everything(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"}); sessCachePut("C", {id: "C"});
__pick("B"); __status(0, 401, {}); await __tick();
console.log(JSON.stringify(Object.assign(__st(), {size: SESS_CACHE.size})));
""")
        self.assertEqual(r["mark"], "error")
        self.assertEqual(r["size"], 0)
        self.assertFalse(r["ev"]["cached"])

    def test_500_keeps_labelled_snapshot_then_clears(self):
        r = self._run("""
snapTtlMin = 30; sessCachePut("B", {id: "B"});
__pick("B"); __status(0, 500, {error: "boom"}); await __tick();
var failed = __st();
poll(); __ok(1, {id: "B", now: 1}); await __tick();
console.log(JSON.stringify({failed: failed, after: __st()}));
""")
        f = r["failed"]
        self.assertEqual((f["mark"], f["refreshing"], f["ev"]["cached"]), ("refreshing", True, True))
        self.assertIn("can't refresh", f["label"])
        self.assertEqual(f["ev"]["snapLabel"], f["label"])
        self.assertEqual((r["after"]["mark"], r["after"]["label"], r["after"]["refreshing"]), (None, "", False))

    def test_steady_state_500_and_network_error_keep_view(self):
        r = self._run("""
snapTtlMin = 30;
__pick("A"); __ok(0, {id: "A", now: 1}); await __tick();
var base = __st();
poll(); __status(1, 500, {error: "boom"}); await __tick(); var s500 = __st();
poll(); __reject(2, new TypeError("net")); await __tick(); var sNet = __st();
poll(); __ok(3, {id: "A", now: 2}); await __tick(); var good = __st();
console.log(JSON.stringify({base: base, s500: s500, sNet: sNet, good: good}));
""")
        for k in ("s500", "sNet"):
            s = r[k]
            self.assertEqual(s["renders"], r["base"]["renders"], k + ": a failure must not re-render")
            self.assertEqual((s["mark"], s["refreshing"], s["ev"]["cached"]), ("refreshing", True, True), k)
            self.assertIn("can't refresh", s["label"])
        self.assertEqual((r["good"]["mark"], r["good"]["label"], r["good"]["refreshing"]), (None, "", False))
        self.assertEqual(r["good"]["renders"], r["base"]["renders"] + 1)

    def test_backdated_entry_and_500_stays_error(self):
        r = self._run("""
snapTtlMin = 30;
__pick("A"); __ok(0, {id: "A", now: 1}); await __tick();
sessCachePut("B", {id: "B"}); SESS_CACHE.get("B").at -= (snapTtlMin * 60 + 1) * 1000;
var before = __renders.length;
__pick("B"); __status(1, 500, {error: "boom"}); await __tick();
console.log(JSON.stringify(Object.assign(__st(), {before: before})));
""")
        self.assertEqual(r["mark"], "error", "the previous session's DOM must stay hidden")
        self.assertEqual(r["renders"], r["before"])
        self.assertFalse(r["ev"]["cached"])

    def test_outage_reages_then_expires(self):
        for ttl in (30, 2):
            r = self._run("""
snapTtlMin = %d; __at(0);
__pick("A"); __ok(0, {id: "A", now: 1}); await __tick();
var out = [];
__at(60); poll(); __status(1, 500, {error: "x"}); await __tick(); out.push(__st());
__at(120); poll(); __status(2, 500, {error: "x"}); await __tick(); out.push(__st());
__at(snapTtlMin * 60 + 1); poll(); __status(3, 500, {error: "x"}); await __tick(); out.push(__st());
console.log(JSON.stringify(out));
""" % ttl)
            self.assertIn("1m ago", r[0]["label"])
            self.assertIn("2m ago", r[1]["label"])
            self.assertEqual((r[1]["mark"], r[1]["ev"]["cached"]), ("refreshing", True), "ttl=%d" % ttl)
            self.assertEqual((r[2]["mark"], r[2]["ev"]["cached"]), ("error", False), "ttl=%d" % ttl)

    def test_hung_fetch_still_expires(self):
        r = self._run("""
snapTtlMin = 2; __at(0); sessCachePut("B", {id: "B"});
__pick("B"); await __grace();                 // snapshot painted; its fetch (0) never resolves
var f0 = __fetches.length;
__at(60); poll(); var s1 = __st();
__at(121); poll(); var s2 = __st();
console.log(JSON.stringify({f0: f0, n: __fetches.length, s1: s1, s2: s2}));
""")
        self.assertEqual(r["n"], r["f0"], "no new fetch while one is in flight")
        self.assertIn("1m ago", r["s1"]["label"])
        self.assertEqual(r["s1"]["mark"], "refreshing")
        self.assertEqual((r["s2"]["mark"], r["s2"]["ev"]["cached"]), ("error", False))

    def test_hung_fetch_on_fresh_data_changes_nothing(self):
        r = self._run("""
snapTtlMin = 2; __at(0);
__pick("A"); __ok(0, {id: "A", now: 1}); await __tick();
poll();                                       // hangs
var a = __st(); __at(119); poll(); var b = __st(); __at(121); poll(); var c = __st();
console.log(JSON.stringify({a: a, b: b, c: c}));
""")
        self.assertEqual(r["a"], r["b"], "a slow healthy poll must not change anything before the TTL")
        self.assertIsNone(r["b"]["mark"])
        self.assertEqual((r["c"]["mark"], r["c"]["ev"]["cached"]), ("error", False))

    def test_hung_fetch_on_fresh_data_unknown_ttl_changes_nothing(self):
        # TTL not heard yet (first /api/list failed, or a NaN header): "unknown" counts as expired
        # for painting snapshots, but must not turn a slow healthy poll on fresh data into an error.
        r = self._run("""
snapTtlMin = 0; __at(0);
__pick("A"); __ok(0, {id: "A", now: 1}); await __tick();
poll();                                       // hangs
var a = __st(); __at(3); poll(); var b = __st();
console.log(JSON.stringify({a: a, b: b}));
""")
        self.assertEqual(r["a"], r["b"], "unknown TTL must leave fresh data alone")
        self.assertIsNone(r["b"]["mark"])

    def test_aborted_old_poll_does_not_unblock_hung_check(self):
        r = self._run("""
snapTtlMin = 2; __at(0); sessCachePut("B", {id: "B"});
__pick("A"); poll();
__pick("B"); await __grace();                 // B's snapshot is up; B's fetch hangs
var e = new Error("aborted"); e.name = "AbortError";
__reject(0, e); await __tick();               // A's aborted poll settles late
var f0 = __fetches.length;
__at(121); poll();
console.log(JSON.stringify({f0: f0, n: __fetches.length, s: __st(), sig: __fetches[0].opts.signal.aborted}));
""")
        self.assertTrue(r["sig"])
        self.assertEqual(r["n"], r["f0"], "an aborted old poll must not free pollBusy and start a new fetch")
        self.assertEqual((r["s"]["mark"], r["s"]["ev"]["cached"]), ("error", False))

    def test_refused_paint_resets_label_and_mark(self):
        r = self._run("""
snapTtlMin = 30; cur = "B"; sessCachePut("B", {id: "B"});
var t = sessToken();
renderFor = function () { return false; };
var ok = sessPaintSnapshot(t);
console.log(JSON.stringify({ok: ok, refreshing: sessRefreshing, label: sessSnapLabel, mark: __main.dataset.sess}));
""")
        self.assertFalse(r["ok"])
        self.assertFalse(r["refreshing"])
        self.assertEqual(r["label"], "")
        self.assertEqual(r["mark"], "loading")

    def test_abort_mid_flight_does_not_touch_new_session(self):
        r = self._run("""
snapTtlMin = 30;
__pick("A"); __pick("B");
var e = new Error("aborted"); e.name = "AbortError";
__reject(0, e); await __tick();
console.log(JSON.stringify(__st()));
""")
        self.assertEqual(r["mark"], "loading")
        self.assertEqual(r["label"], "")
        self.assertEqual(r["nev"], 0)

    def test_prefixed_and_bare_ids_do_not_collide(self):
        r = self._run("""
snapTtlMin = 30;
sessCachePut("auggie:abc", {id: "auggie:abc", v: 1}); sessCachePut("abc", {id: "abc", v: 2});
console.log(JSON.stringify({a: sessCacheGet("auggie:abc").v, b: sessCacheGet("abc").v, size: SESS_CACHE.size}));
""")
        self.assertEqual((r["a"], r["b"], r["size"]), (1, 2, 2))

    def test_position_note_senders_send_text(self):
        r = self._run("""
cur = "A"; lastData = {notes: [{text: "n0"}, {text: "n1", pushed: true}]};
removeNote(1); pushNote(1);
console.log(JSON.stringify(__fetches.map(function (f) { return [f.url, JSON.parse(f.opts.body)]; })));
""")
        self.assertEqual(r[0], ["/api/notes/delete", {"session": "A", "index": 1, "text": "n1", "pushed": True}])
        self.assertEqual(r[1], ["/api/notes/push", {"session": "A", "index": 1, "text": "n1", "pushed": True}])

    # ---- sidebar fast path (P4.1) -------------------------------------------------------------
    def test_pick_skips_full_sidebar_when_row_present(self):
        r = self._run("""
__row = {classList: {add: function (c) { __added.push(c); }}}; sessions = [{id: "B"}];
pick("B");
console.log(JSON.stringify({calls: __renderSideCalls, added: __added, old: __oldRemoved}));
""")
        self.assertEqual(r["calls"], 0)
        self.assertEqual(r["added"], ["active"])
        self.assertEqual(r["old"], 1, "the previously active row must lose its class")

    def test_fast_pick_selector_escapes_id(self):
        r = self._run("""
CSS.escape = function (s) { return String(s).replace(/"/g, String.fromCharCode(92) + '"'); };
__row = {classList: {add: function () {}}}; sessions = [{id: 'a"b'}];
pick('a"b');
console.log(JSON.stringify({sels: __sels}));
""")
        self.assertIn('.sitem[data-sid="a\\"b"]', r["sels"])

    def test_pick_falls_back_when_row_absent(self):
        r = self._run("""
__row = null; pick("B");
console.log(JSON.stringify({calls: __renderSideCalls}));
""")
        self.assertEqual(r["calls"], 1)

    def test_fast_pick_keeps_sidebar_bookkeeping(self):
        r = self._run("""
__row = {classList: {add: function () {}}}; sessions = [{id: "B"}]; autoExpandedFor = "Z";
pick("B");
console.log(JSON.stringify({auto: autoExpandedFor, sel: selEntry && selEntry.id, calls: __renderSideCalls}));
""")
        self.assertEqual((r["auto"], r["sel"], r["calls"]), ("B", "B", 0))

    def test_fast_pick_in_search_leaves_auto_expand_pending(self):
        r = self._run("""
__row = {classList: {add: function () {}}}; sessions = [{id: "B"}]; autoExpandedFor = "Z"; searchResults = [{id: "B"}];
pick("B");
console.log(JSON.stringify({auto: autoExpandedFor, sel: selEntry && selEntry.id}));
""")
        self.assertEqual((r["auto"], r["sel"]), ("Z", "B"))


# ---------------------------------------------------------------------------------------------
# Static sweep: the "future panels can't forget" guard. Reads the shipped web sources and fails
# when a tty-addressed call leaves the page without its session, or a session-scoped read skips
# the guarded helper.
# ---------------------------------------------------------------------------------------------
import re

WEB = os.path.join(ROOT, "aitracker", "web")


def _web_src(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _code_only(src):
    """Drop whole-line // comments so prose that mentions a route is not mistaken for a call."""
    return "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("//"))


def _web_js_files():
    return sorted(f for f in os.listdir(WEB) if f.endswith(".js"))


class TestSessionIsolationStaticSweep(unittest.TestCase):
    POST_RE = re.compile(r'''["']/api/term/(keys|resize|inject|close)["']''')
    GET_RE = re.compile(r'''["']/api/term/(screen|raw|scrollback|attached)\?''')

    def test_every_tty_post_body_carries_its_session(self):
        seen = 0
        for f in _web_js_files():
            code = _code_only(_web_src(f))
            for m in self.POST_RE.finditer(code):
                seen += 1
                window = code[m.end():m.end() + 420]
                ok = ("ttyBody(" in window or "_ttyBodyFor(" in window
                      or re.search(r"\bsession\b", window))
                self.assertTrue(ok, "%s: POST /api/term/%s body has no ttyBody()/session near: %r"
                                % (f, m.group(1), window[:160]))
        self.assertGreater(seen, 6, "sweep found suspiciously few tty POST sites")

    def test_every_tty_get_url_is_built_with_ttyQuery(self):
        seen = 0
        for f in _web_js_files():
            for line in _code_only(_web_src(f)).split("\n"):
                m = self.GET_RE.search(line)
                if not m:
                    continue
                seen += 1
                self.assertIn("ttyQuery(", line, "%s: GET /api/term/%s URL not built with ttyQuery: %s"
                              % (f, m.group(1), line.strip()[:160]))
        self.assertGreater(seen, 3, "sweep found suspiciously few tty GET sites")

    def test_app_js_session_reads_go_through_sessJSON(self):
        seen = 0
        for line in _code_only(_web_src("app.js")).split("\n"):
            if "encodeURIComponent(cur)" in line and "fetch(" in line:
                self.fail("app.js reads a session-scoped URL with bare fetch(): " + line.strip()[:160])
            if "encodeURIComponent(cur)" in line and "sessJSON(" in line:
                seen += 1
        self.assertGreater(seen, 4)

    def test_every_cr_detail_dialog_is_session_bound(self):
        code = _code_only(_web_src("ext_cr_detail.js"))
        seen = 0
        for m in re.finditer(r"ctx\.dialog\(", code):
            seen += 1
            window = code[m.end():m.end() + 1400]
            end = window.find("});")
            self.assertIn("sessionId", window[:end if end > 0 else 1400],
                          "ctx.dialog without sessionId near: %r" % window[:80])
        self.assertGreater(seen, 5)

    def test_cr_session_reads_are_guarded(self):
        pat = re.compile(r"/api/(narration|session_search|diff|output|shell|agent)\?id=")
        seen = 0
        for f in _web_js_files():
            if not f.startswith("ext_cr_"):
                continue
            lines = _code_only(_web_src(f)).split("\n")
            for i, line in enumerate(lines):
                if not pat.search(line):
                    continue
                if "return '/api/" in line:                 # URL builder, fetched via sessJSON(urlFn(
                    continue
                seen += 1
                ctx = "\n".join(lines[max(0, i - 3):i + 12])
                self.assertTrue("sessJSON(" in line or "ui.sid !== sid" in ctx,
                                "%s:%d unguarded session read: %s" % (f, i + 1, line.strip()[:140]))
        self.assertGreater(seen, 0)
        poll = _code_only(_web_src("app.js"))
        i = poll.index("async function poll(){")
        body = poll[i:i + 1600]
        self.assertIn("sessAbort.signal", body)
        self.assertIn("sessLanded(id", body)

    def test_cr_detail_reset_listener_clears_all_six_inputs(self):
        src = _web_src("ext_cr_detail.js")
        i = src.index('ctx.on("session:reset"')
        body = src[i:i + 1800]
        for sel in (".crd-flag-input", ".crd-note-queue-input", ".crd-phone-input",
                    ".crd-plan-input", ".crd-run-input", ".crd-search-input"):
            self.assertIn(sel, body, "session:reset listener does not clear " + sel)
        for fld in ("ui.flagOpen", "ui.noteOpen", "ui.lastSession", "ui.lastState", "ui.spineSession"):
            self.assertIn(fld, body, "session:reset listener does not reset " + fld)

    def test_every_session_module_hooks_the_reset_registry(self):
        boot = _web_src("ext_cr_boot.js")
        self.assertIn("onSessionReset(", boot)
        self.assertIn("onSessionReset", _web_src("ext_run.js"))
        self.assertIn("closeSession", _web_src("ext_cr_dialogs.js"))
        i = boot.index("on('cr:drill-request'")
        self.assertRegex(boot[i:i + 900], r"sid !== cur", "drill request is not gated on the selection")
        self.assertIn("sessJSON(urlFn(", boot)

    def test_model_effort_senders_require_claude_and_note_senders_send_text(self):
        for f, needle, n in (("ext_cr_detail.js", "clear_first: true, require_claude: true", 1),
                             ("ext_cr_term.js", "clear_first: true, require_claude: true", 1),
                             ("ext_vt.js", "clear_first: true, require_claude: true", 2)):
            self.assertEqual(_web_src(f).count(needle), n, f + ": model/effort sender without require_claude")
        self.assertIn("snapLabel: (typeof sessSnapLabel", _web_src("ext_cr_boot.js"))
        self.assertIn("text: payload.text", _web_src("ext_cr_boot.js"))
        self.assertIn("text: rmNote && rmNote.text", _web_src("ext_cr_detail.js"))
        self.assertIn("pushed: !!(rmNote && rmNote.pushed)", _web_src("ext_cr_detail.js"))
        self.assertIn("pushed: !!payload.pushed", _web_src("ext_cr_boot.js"))
        self.assertEqual(_web_src("app.js").count("pushed:!!("), 2, "app.js note senders must send pushed")
        app = _web_src("app.js")
        for fn in ("function sessLanded(", "function sessFailed("):
            i = app.index(fn)
            body = app[i:app.index("\nfunction ", i + 10)]
            self.assertNotIn("sessCacheGet(", body, fn + " must not read the age-gated cache to decide error-or-keep")
        code = _code_only(app)
        self.assertNotRegex(code, r"(localStorage|sessionStorage|indexedDB)[^;]*SESS_CACHE")

    def test_run_command_sid_is_read_at_click_time(self):
        src = _web_src("ext_run.js")
        self.assertIn("var runSid = curSid()", src)
        self.assertNotIn("session: sid,", src)


# ---------------------------------------------------------------------------------------------
# Full-bundle harness: the REAL assembled page under a stub DOM. A session switch must clear the
# control room's typed-but-unsent input and close session-bound dialogs, but leave session-less
# ones (the Flags list) open.
# ---------------------------------------------------------------------------------------------
_CR_STUB = r"""
function fakeNode(path) {
  var memo = {}, n = {
    _path: path, hidden: false, value: "", innerHTML: "", textContent: "", style: {}, dataset: {},
    children: [], childNodes: [], scrollLeft: 0, scrollTop: 0, clientHeight: 0, scrollHeight: 0, scrollWidth: 0,
    _cls: {},
    classList: { add: function (c) { n._cls[c] = true; }, remove: function (c) { delete n._cls[c]; },
                 toggle: function (c, f) { var w = f === undefined ? !n._cls[c] : !!f; if (w) n._cls[c] = true; else delete n._cls[c]; return w; },
                 contains: function (c) { return !!n._cls[c]; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {}, hasAttribute() { return false; },
    appendChild(c) { return c; }, append() {}, remove() {}, insertBefore(c) { return c; }, removeChild(c) { return c; },
    addEventListener() {}, removeEventListener() {}, focus() {}, click() {}, scrollIntoView() {},
    closest() { return null; }, getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; },
    querySelector(sel) { return memo[sel] || (memo[sel] = fakeNode(path + ">" + sel)); },
    querySelectorAll() { return []; }
  };
  return n;
}
window.__docL = {};
document.addEventListener = function (t, f) { (window.__docL[t] = window.__docL[t] || []).push(f); };
var __origCE = document.createElement;
var __fetch0 = window.fetch;     // the board's first /api/list reply tells the page its snapshot TTL (30 min)
window.fetch = function () {
  return __fetch0.apply(this, arguments).then(function (r) {
    var g = r.headers && r.headers.get ? r.headers.get.bind(r.headers) : function () { return null; };
    r.headers = { get: function (k) { return k === "X-Snapshot-TTL" ? "30" : g(k); } };
    return r;
  });
};
document.createElement = function (tag) {
  if (tag === "template") {
    var t = { content: { firstChild: null } };
    Object.defineProperty(t, "innerHTML", { set: function () { t.content.firstChild = fakeNode("root"); } });
    return t;
  }
  return __origCE(tag);
};
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestControlRoomSessionReset(unittest.TestCase):
    def _run(self, body_js):
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, ROOT)
        import test_cr_crossview as cv
        bundle = cv._extract_script_content(cv._read_page())
        pre = cv._JS_PREAMBLE % {"seed": "'tracker.ui': 'next'"}
        defer = "window.__q = []; window.setTimeout = function (fn) { window.__q.push(fn); return 0; };"
        # boot.js's init() is a setTimeout(init, 0) queued before the later ext_cr_* files define
        # window.CR.*; run it only after the whole bundle has evaluated.
        run_init = "window.__q.splice(0).forEach(function (f) { f(); });"
        tail = ("(window.__wait || Promise.resolve()).then(function () {"
                "console.log('===SI_JSON===');console.log(JSON.stringify(OUT));});")
        js = "\n".join([pre, defer, _CR_STUB, bundle, cv._JS_MID, "var OUT = {};", run_init, body_js, tail])
        rc, out, err = cv._run_node(js)
        self.assertEqual(rc, 0, "node failed\n%s\n%s" % (out, err))
        self.assertNotIn("mount detail threw", err, err)
        return json.loads(out[out.index("===SI_JSON===") + len("===SI_JSON==="):].strip())

    def test_switch_clears_inputs_and_closes_only_session_bound_dialogs(self):
        r = self._run(r"""
var D = window.CR.dialogs, node = window.CR.detail._root._crDetail.node;
window.CR.detail.update({session: {id: "A", meta: {sessionId: "A"}}, sid: "A", now: 1700000000});
var sels = [".crd-flag-input", ".crd-note-queue-input", ".crd-phone-input", ".crd-plan-input", ".crd-run-input", ".crd-search-input"];
sels.forEach(function (s) { node.querySelector(s).value = "typed-for-A"; });
D.open("flags", {});                                       // session-less: stays
D.open("rename", {sessionId: "A", currentTitle: "x"});     // bound to A: closes
OUT.before = D.topName();
OUT.loadingBefore = !!node._cls["crd-is-loading"];
resetSession("B", "A");
OUT.after = D.topName();
OUT.values = sels.map(function (s) { return node.querySelector(s).value; });
OUT.loadingAfter = !!node._cls["crd-is-loading"];
window.CR.detail.update({session: {id: "B", meta: {sessionId: "B"}}, sid: "B", now: 1700000001});
OUT.loadingPainted = !!node._cls["crd-is-loading"];
""")
        self.assertEqual(r["before"], "rename")
        self.assertFalse(r["loadingBefore"])
        self.assertEqual(r["after"], "flags", "rename (session A) must close, session-less flags must stay")
        self.assertEqual(r["values"], [""] * 6, "typed input leaked across the session switch")
        self.assertTrue(r["loadingAfter"])
        self.assertFalse(r["loadingPainted"], "the next detail paint must clear the loading mark")

    def test_same_session_keeps_its_own_dialogs(self):
        r = self._run(r"""
var D = window.CR.dialogs;
D.open("rename", {sessionId: "A", currentTitle: "x"});
D.closeSession("A");                                      // keep A's own dialogs
OUT.top = D.topName();
""")
        self.assertEqual(r["top"], "rename")

    # C3: a run-command POST that resolves after a switch must not open A's run pane under B
    def test_run_command_resolving_after_switch_opens_nothing(self):
        r = self._run(r"""
window.EventSource = globalThis.EventSource = function () { this.close = function () {}; this.addEventListener = function () {}; };
var D = window.CR.dialogs, ctx = window.CR.detail._ctx, pending = [];
globalThis.fetch = window.fetch = function (url) {
  return new Promise(function (res) { if (String(url).indexOf("/api/term/run") >= 0) pending.push(res); });
};
function pick(s) { document.getElementById("x").value = s; track(); }
var notes = [];
ctx.on("notify", function (p) { notes.push(p && p.text); });
var opened = [];
ctx.on("dialog:open", function (p) { opened.push(p && p.name); });
pick("A");
ctx.emit("cr:run-command", {sessionId: "A", argv: "ls"});
pick("B");
pending[0]({ok: true, status: 200, json: function () { return Promise.resolve({job: "j1"}); }});
window.__wait = (async function () {
  for (var i = 0; i < 10; i++) await Promise.resolve();
  OUT.pending = pending.length;
  OUT.notes = notes;
  OUT.opened = opened;
})();
""")
        self.assertEqual(r["pending"], 1)
        # ponytail: no topName() check -- the harness has no MutationObserver, so run-output never
        # reaches the stack and that assert could not fail; the dialog:open capture is the real proof.
        self.assertNotIn("run-output", r["opened"], "A's run pane opened under B")
        self.assertIn("Started in previous session", r["notes"])
        self.assertNotIn("Running: ls", r["notes"])

    # C1 (control room half): an error for the selection swaps loading for the error state
    def test_session_error_event_clears_loading(self):
        r = self._run(r"""
var node = window.CR.detail._root._crDetail.node;
function pick(s) { document.getElementById("x").value = s; track(); }
pick("A"); pick("B");
OUT.loadingBefore = !!node._cls["crd-is-loading"];
(window.__docL["tracker:session-error"] || []).forEach(function (f) { f({detail: {id: "B", error: "boom", cached: false}}); });
OUT.loading = !!node._cls["crd-is-loading"]; OUT.errored = !!node._cls["crd-is-error"];
window.CR.detail.update({session: {id: "B", meta: {sessionId: "B"}}, sid: "B", now: 1700000001});
OUT.errorAfterLand = !!node._cls["crd-is-error"];
pick("C");
(window.__docL["tracker:session-error"] || []).forEach(function (f) { f({detail: {id: "C", error: "not found", cached: false}}); });
OUT.cErrored = !!node._cls["crd-is-error"];
pick("B");
OUT.errorAfterSwitch = !!node._cls["crd-is-error"];
""")
        self.assertTrue(r["loadingBefore"])
        self.assertFalse(r["loading"])
        self.assertTrue(r["errored"])
        self.assertFalse(r["errorAfterLand"])
        self.assertTrue(r["cErrored"])
        self.assertFalse(r["errorAfterSwitch"], "C's error state leaked onto B's loading")

    # A failed poll on a view that is already shown: the board keeps it, labelled, instead of ignoring it
    def test_cached_error_event_labels_header(self):
        r = self._run(r"""
window.__wait = new Promise(function (res) { setImmediate(res); }).then(function () {
var node = window.CR.detail._root._crDetail.node;
var hd = node.querySelector(".crd-header"); OUT.attrs = [];
hd.setAttribute = function (k, v) { OUT.attrs.push([k, v]); };
function pick(s) { document.getElementById("x").value = s; track(); }
var __ivs = []; window.setInterval = function (fn) { __ivs.push(fn); return 1; };
window.fetch = function () { return new Promise(function () {}); };          // every poll hangs
var __now = Date.now(); Date.now = function () { return __now; };
render = function () {};                      // the classic renderer is not under test here
sessCachePut("B", {id: "B", now: 1, meta: {sessionId: "B"}, tokens: {in: 0, out: 0}, counts: {}, overview: {}});
pick("B");
window.__q.splice(0).forEach(function (f) { f(); });                          // snapshot grace -> snapshot painted
OUT.attrs.length = 0; __now += 61000;
__ivs[__ivs.length - 1]();                    // the hung-fetch pre-check re-ages the label and forwards it to the board
OUT.hungSnap = OUT.attrs.slice();
var fire = function (d) { (window.__docL["tracker:session-error"] || []).forEach(function (f) { f({detail: d}); }); };
fire({id: "B", error: "boom", cached: true, snapLabel: "data from 2m ago · can't refresh"});
OUT.refreshing = !!node._cls["crd-is-refreshing"]; OUT.errored = !!node._cls["crd-is-error"];
fire({id: "B", error: "boom", cached: false});
OUT.errored2 = !!node._cls["crd-is-error"];
}).catch(function (e) { OUT.err = String(e && e.stack || e); });
""")
        self.assertNotIn("err", r, r.get("err"))
        self.assertTrue(any(a[0] == "data-snap" and "snapshot from 1m ago" in a[1] for a in r["hungSnap"]),
                        "the pre-check must forward its label to the board header" + repr(r["hungSnap"]))
        self.assertTrue(r["refreshing"])
        self.assertFalse(r["errored"], "a kept view must not show the error state")
        self.assertIn(["data-snap", "data from 2m ago · can't refresh"], r["attrs"])
        self.assertTrue(r["errored2"])

    # C5: building a tty body must not rebind the page-wide tty->session map
    def test_tty_body_for_does_not_mutate_binding(self):
        r = self._run(r"""
var X = window.ExtVT;
X.bindTty("t", "");
var body = window.CR.detail._internal.ttyBodyFor("t", "A", {text: "x"});
OUT.bound = X.ttyBody("t").session; OUT.body = body;
""")
        self.assertEqual(r["bound"], "")
        self.assertEqual(r["body"]["session"], "A")
        self.assertEqual(r["body"]["text"], "x")


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestDialogsUnmounted(unittest.TestCase):
    def test_close_session_before_mount_does_not_throw(self):
        with open(os.path.join(WEB, "ext_cr_dialogs.js"), encoding="utf-8") as fh:
            src = fh.read()
        js = ("var window = {}; var document = {createElement: function () { return {style: {}, setAttribute: function () {}}; }, "
              "addEventListener: function () {}};\n" + src +
              "\ntry { window.CR.dialogs.closeSession('B'); console.log('ok'); } catch (e) { console.log('threw ' + e.message); }\n")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
            tf.write(js)
            path = tf.name
        try:
            proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
