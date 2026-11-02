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
function $(id) { return __els[id] || (__els[id] = { value: "", innerHTML: "", textContent: "", style: {} }); }
function setInterval() { __intervals++; return 1; }
function clearInterval() {}
function render(d) { __renders.push({ id: d.id, sess: __main.dataset.sess, refreshing: sessRefreshing }); }
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
        self.assertEqual(r["hit"], [{"id": "B", "sess": "refreshing", "refreshing": True}])
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
sessCachePut("B", {id: "B"});
__pick("B"); __ok(0, {error: "boom"});
await new Promise(function (r) { setTimeout(r, 20); });
var cachedMark = __main.dataset.sess === undefined ? null : __main.dataset.sess;
console.log(JSON.stringify({cachedMark: cachedMark}));
""")
        self.assertIsNone(r["cachedMark"], "a cached snapshot stays shown")
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
sessCachePut("B", {id: "B"});
__pick("B");
var painted = __renders.slice();
__ok(0, {id: "B", now: 1});
await new Promise(function (r) { setTimeout(r, 20); });
console.log(JSON.stringify({painted: painted, last: __renders[__renders.length - 1]}));
""")
        self.assertTrue(r["painted"][0]["refreshing"])
        self.assertFalse(r["last"]["refreshing"], "fresh data rendered while sessRefreshing still true")

    def test_mismatched_land_does_not_clear_refreshing(self):
        r = self._run("""
sessCachePut("B", {id: "B"});
__pick("B");
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


if __name__ == "__main__":
    unittest.main()
