"""Behavioural (EXECUTED) tests for aitracker/web/ext_vt.js's mouse/send-ordering fixes.

tests/test_term_vt_client.py asserts against the SOURCE TEXT of ext_vt.js -- it can confirm the
shape of the fix (which function calls which) but cannot fail against a pure TIMING bug, because
it never runs the code. That was exactly how the send/motion reordering defect shipped once
already: a text-only test asserted the flush called `_send`, which stayed true even with the
reordering bug fully intact, because the bug is about WHEN a promise-chain append happens, not
what literal appears in the source.

This module closes that gap by actually EXECUTING the real functions -- extracted verbatim (by
source-text slicing, not retyped) out of aitracker/web/ext_vt.js -- under Node, with a fake
Terminal-like `self` object and mocked `postKeys`/`requestAnimationFrame`, and asserting on the
real order bytes were handed to the (mocked) network call.

Node is NOT a dependency of this project (see CLAUDE.md: "Stdlib only, no new dependencies" /
conventions.md rule 2) -- this whole module is skipped outright when `node` isn't on PATH, so
`make check` stays green on a machine without it. Nothing here is added to any Makefile, config,
or packaging metadata; `node` is invoked directly via subprocess, exactly like an optional,
best-effort extra check.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None


def _read_src():
    with open(os.path.join(_WEB, "ext_vt.js"), encoding="utf-8") as fh:
        return fh.read()


def _function_body(src, marker):
    """Identical extraction strategy to test_term_vt_client.py's own helper: the full source of
    one `Terminal.prototype.X = function ...` (or any `marker`), up to the next
    `Terminal.prototype.` after it. Trailing comment text before the next marker rides along,
    which is harmless once pasted into a JS file (comments are just ignored)."""
    start = src.index(marker)
    nxt = src.find("Terminal.prototype.", start + len(marker))
    return src[start: nxt if nxt != -1 else len(src)]


def _span(src, start_marker, end_marker):
    """From `start_marker` through the END of the line containing `end_marker` (inclusive) --
    used for the constructor's outside-pane-release wiring, which sits BEFORE the first
    `Terminal.prototype.` marker and so can't use `_function_body`'s next-marker strategy."""
    start = src.index(start_marker)
    end = src.index(end_marker, start) + len(end_marker)
    return src[start:end]


def _run_node(js_source):
    """Writes `js_source` to a temp file and runs it with `node`, returning parsed JSON printed
    to stdout by the script's own final `console.log(JSON.stringify(...))`. Raises with the
    script's stderr/stdout on any non-zero exit or unparsable output, so a failure here shows up
    as a normal test failure with full context, not a silent None."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(
            "node harness exited %d\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (proc.returncode, proc.stdout, proc.stderr)
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise AssertionError(
            "could not parse JSON from node harness output: %r\nfull stdout:\n%s\nstderr:\n%s"
            % (e, proc.stdout, proc.stderr)
        )


# ===== extraction: pulled once at import time, straight out of the shipped source ===============
_SRC = _read_src() if _HAS_NODE else ""

if _HAS_NODE:
    _SEND_ORDERING_SRC = "\n".join([
        _function_body(_SRC, "Terminal.prototype._enqueue = function"),
        _function_body(_SRC, "Terminal.prototype._flushMotion = function"),
        _function_body(_SRC, "Terminal.prototype._send = function"),
        _function_body(_SRC, "Terminal.prototype._sendMotion = function"),
    ])

    _DESTROY_SRC = _function_body(_SRC, "Terminal.prototype.destroy = function")

    _MOUSE_METHODS_SRC = "\n".join([
        _function_body(_SRC, "Terminal.prototype._mouseGate = function"),
        _function_body(_SRC, "Terminal.prototype._mouseCell = function"),
        _function_body(_SRC, "Terminal.prototype._mouseButtonCode = function"),
        _function_body(_SRC, "Terminal.prototype._sendMouseReport = function"),
        _function_body(_SRC, "Terminal.prototype._onMouseDown = function"),
        _function_body(_SRC, "Terminal.prototype._onMouseMove = function"),
        _function_body(_SRC, "Terminal.prototype._onMouseUp = function"),
    ])

    # The outside-pane release fallback is a CLOSURE wired inside the constructor (it captures
    # `self`, `pane`, and refers to the ambient `document`), not a `Terminal.prototype.X` -- so it
    # is extracted by literal span instead, and re-wrapped below as a standalone function that
    # takes `pane`/`document` as parameters and re-declares `var self = this;` the same way the
    # real constructor does right above it.
    _DOC_MOUSEUP_WIRING_SRC = _span(
        _SRC,
        "this._onDocMouseUp = function (ev) {",
        'document.addEventListener("mouseup", this._onDocMouseUp);',
    )


_HARNESS_PRELUDE = """
'use strict';
var Terminal = function () {};
"""


def _harness_mocks():
    """Shared mock infrastructure: a `postKeys` that records every call (and can be told to
    reject the Nth call), a manually-driven `requestAnimationFrame` queue (nothing fires until
    `flushRAF()` is called -- this is what lets the test control "before/after the 16ms frame"
    without needing a real clock), and a minimal `document` stub recording addEventListener/
    removeEventListener calls so `destroy()`-style cleanup can be asserted too."""
    return """
var __calls = [];
var __rejectNth = null;   // 1-based index of a postKeys() call to make reject, or null
var __callCount = 0;
function postKeys(tty, s) {
  __callCount++;
  __calls.push(s);
  if (__rejectNth !== null && __callCount === __rejectNth) {
    return Promise.reject(new Error('simulated network hiccup'));
  }
  return Promise.resolve({ ok: true });
}
// requestAnimationFrame returns an id (its queue index) and cancelAnimationFrame records which
// ids were cancelled AND nulls that queue slot -- so flushRAF()/fireAllRAF() below can tell a
// genuinely-cancelled callback apart from one that's still live, the same distinction the real
// browser API makes and that destroy()'s cancelAnimationFrame() call depends on.
var __rafQueue = [];
var __cancelledRAFIds = [];
function requestAnimationFrame(cb) {
  var id = __rafQueue.length;
  __rafQueue.push(cb);
  return id;
}
function cancelAnimationFrame(id) {
  __cancelledRAFIds.push(id);
  if (id >= 0 && id < __rafQueue.length) __rafQueue[id] = null;
}
function flushRAF() {
  var q = __rafQueue; __rafQueue = [];
  q.forEach(function (cb) { if (cb) cb(); });
}
// fireAllRAF: like flushRAF, but fires a callback even if cancelAnimationFrame already nulled its
// slot -- used to prove destroy()'s own state-clearing (not just the cancellation call) is what
// stops a stray postKeys, i.e. it still holds even if cancellation itself somehow didn't prevent
// the callback from running (a real race the mock is deliberately pessimistic about).
function fireAllRAF(callbacks) {
  callbacks.forEach(function (cb) { if (cb) cb(); });
}
// Minimal ambient `document` -- only Terminal.prototype.destroy() reads this directly (as
// `document.removeEventListener`, an unparameterized global, unlike the outside-pane-release
// wiring above which takes `document` as an explicit constructor parameter instead).
var document = { removeEventListener: function () {} };
function makeSelf(ttyId) {
  return {
    ttyId: ttyId,
    _sendChain: Promise.resolve(),
    _pendingMotion: null,
    _motionRAFPending: false,
    _motionRAFHandle: null,
    _mouseButtonDown: null,
    _lastMouseCell: null,
    mouse: { mode: 0, sgr: false },
    viewingHistory: false,
    cols: 80, rows: 24,
    rowsEl: { getBoundingClientRect: function () { return { left: 0, top: 0 }; } },
    cellW: 8, cellH: 16,
    es: null,
    _onDocMouseUp: null,
    _noticeEls: [],
    measureAndResize: function () {},
    _enqueue: Terminal.prototype._enqueue,
    _flushMotion: Terminal.prototype._flushMotion,
    _send: Terminal.prototype._send,
    _sendMotion: Terminal.prototype._sendMotion,
    _mouseGate: Terminal.prototype._mouseGate,
    _mouseCell: Terminal.prototype._mouseCell,
    _mouseButtonCode: Terminal.prototype._mouseButtonCode,
    _sendMouseReport: Terminal.prototype._sendMouseReport,
    _onMouseDown: Terminal.prototype._onMouseDown,
    _onMouseMove: Terminal.prototype._onMouseMove,
    _onMouseUp: Terminal.prototype._onMouseUp,
    destroy: Terminal.prototype.destroy,
  };
}
function fakeEvent(overrides) {
  var base = {
    clientX: 0, clientY: 0, button: 0,
    metaKey: false, ctrlKey: false, shiftKey: false,
    target: 'inside',
    preventDefault: function () {},
  };
  for (var k in overrides) base[k] = overrides[k];
  return base;
}
"""


class TestOrderingRegression(unittest.TestCase):
    """DEFECT 1's exact reviewer-executed proof, reproduced here as a permanent regression test:
    a motion report produced at t=0, followed 5ms later (before the 16ms rAF fires) by a discrete
    send, must reach postKeys() motion-first. Also proves recursion-safety and no-double-send."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_reviewer_scenario_motion_before_early_discrete_send(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty1');
  // t=0: mousemove -> _sendMotion (schedules an rAF flush, does NOT touch the chain yet)
  self._sendMotion.call(self, 'MOTION-at-t0');
  // t=5ms: a discrete event (e.g. mouseup) fires BEFORE the 16ms rAF callback would -- this is
  // the exact race the reviewer's proof used setTimeout(..., 5) for.
  self._send.call(self, 'RELEASE-at-t5');
  await self._sendChain;
  // Now the animation frame finally fires (simulating ~16ms).
  flushRAF();
  await self._sendChain;
  console.log(JSON.stringify({ order: __calls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["order"], ["MOTION-at-t0", "RELEASE-at-t5"],
            "motion must reach postKeys before the discrete event that followed it in time, "
            "and must be sent exactly once",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_late_raf_after_flush_does_not_resend(self):
        # Isolates the "sent exactly once" half of the guarantee above: even with NOTHING else
        # queued after the flush, a late rAF firing on an already-flushed motion must be a no-op.
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty2');
  self._sendMotion.call(self, 'M1');
  self._send.call(self, 'DISCRETE');   // flushes M1, then enqueues DISCRETE
  await self._sendChain;
  flushRAF();                          // the original rAF for M1 finally fires
  await self._sendChain;
  console.log(JSON.stringify({ calls: __calls, count: __callCount }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["calls"], ["M1", "DISCRETE"])
        self.assertEqual(result["count"], 2, "M1 must not be sent a second time by the late rAF")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_multiple_motions_before_flush_coalesce_to_the_newest(self):
        # Sanity check that coalescing itself (pre-existing behaviour) survives the restructure:
        # several motion reports produced before any flush must collapse to just the last one.
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty3');
  self._sendMotion.call(self, 'M1');
  self._sendMotion.call(self, 'M2');
  self._sendMotion.call(self, 'M3');
  flushRAF();
  await self._sendChain;
  console.log(JSON.stringify({ calls: __calls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["calls"], ["M3"])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_rejected_send_does_not_wedge_the_chain(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty4');
  __rejectNth = 1;   // the first postKeys() call rejects, simulating a network hiccup
  self._send.call(self, 'a');
  self._send.call(self, 'b');
  await self._sendChain;
  console.log(JSON.stringify({ calls: __calls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["calls"], ["a", "b"],
            "a rejected send must not prevent the next queued send from running",
        )


class TestOutsidePaneReleaseExecuted(unittest.TestCase):
    """DEFECT 2, executed: a press-inside/drag-outside/release-outside sequence must still clear
    `_mouseButtonDown`, and a release that landed INSIDE the pane must not be double-reported by
    the document-level fallback."""

    def _wired_self(self, pane_contains_target):
        # Reconstructs the constructor's outside-pane wiring, verbatim, as a standalone function
        # -- `var self = this;` mirrors the real constructor's own `var self = this;` (line ~352,
        # above where this snippet is wired), so the extracted text's bare `self`/`this`
        # references resolve exactly as they do in the real file.
        return _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _MOUSE_METHODS_SRC + _harness_mocks() + (
            """
function wireOutsidePaneFallback(pane, document) {
  var self = this;
  """ + _DOC_MOUSEUP_WIRING_SRC + """
}
"""
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_release_outside_the_pane_clears_drag_state_and_reports_it(self):
        script = self._wired_self(False) + """
async function main() {
  var self = makeSelf('tty5');
  self.mouse = { mode: 1002, sgr: false };   // drag-only motion mode
  self._mouseButtonDown = 0;                  // a drag is in progress (left button)
  self._lastMouseCell = { row: 3, col: 3 };

  var addedHandlers = {};
  var removedHandlers = [];
  var fakeDocument = {
    addEventListener: function (name, fn) { addedHandlers[name] = fn; },
    removeEventListener: function (name, fn) { removedHandlers.push(name); },
  };
  var fakePane = { contains: function (t) { return t === 'inside'; } };

  wireOutsidePaneFallback.call(self, fakePane, fakeDocument);
  self._onDocMouseUp = addedHandlers['mouseup'];

  // Release happens WAY outside the pane -- _mouseCell must still clamp it into [1,cols]/[1,rows].
  var ev = fakeEvent({ clientX: -500, clientY: -500, target: 'outside-element' });
  self._onDocMouseUp(ev);
  await self._sendChain;

  console.log(JSON.stringify({
    buttonDownAfter: self._mouseButtonDown,
    lastCellAfter: self._lastMouseCell,
    sentCount: __callCount,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertIsNone(result["buttonDownAfter"], "the stuck-drag bug: button state must clear")
        self.assertIsNone(result["lastCellAfter"])
        self.assertEqual(result["sentCount"], 1, "the release report itself must still be sent")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_no_subsequent_hover_reports_a_drag_after_outside_release(self):
        script = self._wired_self(False) + """
async function main() {
  var self = makeSelf('tty6');
  self.mouse = { mode: 1002, sgr: false };   // 1002: motion reported ONLY while dragging
  self._mouseButtonDown = 0;
  self._lastMouseCell = { row: 3, col: 3 };

  var addedHandlers = {};
  var fakeDocument = { addEventListener: function (name, fn) { addedHandlers[name] = fn; },
                        removeEventListener: function () {} };
  var fakePane = { contains: function () { return false; } };
  wireOutsidePaneFallback.call(self, fakePane, fakeDocument);
  self._onDocMouseUp(fakeEvent({ clientX: -1, clientY: -1, target: 'outside' }));
  await self._sendChain;
  var countAfterRelease = __callCount;

  // A plain hover over the pane afterwards, mode 1002 (drag-only) -- must NOT be reported, since
  // _mouseButtonDown is (correctly) null again. Before the fix this stayed stuck at the old
  // button and every such hover was misreported as a continuing drag with the +32 bit.
  self._onMouseMove.call(self, fakeEvent({ clientX: 40, clientY: 40, target: 'inside' }));
  await self._sendChain;

  console.log(JSON.stringify({
    countAfterRelease: countAfterRelease,
    countAfterHover: __callCount,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["countAfterHover"], result["countAfterRelease"],
            "a plain hover after the drag correctly ended must send nothing under mode 1002",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_release_inside_the_pane_is_not_double_sent_by_the_fallback(self):
        script = self._wired_self(True) + """
async function main() {
  var self = makeSelf('tty7');
  self.mouse = { mode: 1000, sgr: false };
  self._mouseButtonDown = 0;
  self._lastMouseCell = { row: 1, col: 1 };

  var addedHandlers = {};
  var fakeDocument = { addEventListener: function (name, fn) { addedHandlers[name] = fn; },
                        removeEventListener: function () {} };
  var fakePane = { contains: function (t) { return t === 'inside-pane-node'; } };
  wireOutsidePaneFallback.call(self, fakePane, fakeDocument);
  self._onDocMouseUp = addedHandlers['mouseup'];

  // Simulate the REAL sequence: the pane's own "mouseup" listener runs first (bubbling order)
  // and sends the release + clears state, exactly like pane.addEventListener("mouseup", ...) do
  // in the real constructor.
  self._onMouseUp.call(self, fakeEvent({ clientX: 5, clientY: 5, target: 'inside-pane-node' }));
  await self._sendChain;
  var countAfterPaneHandler = __callCount;

  // THEN the same event bubbles to document -- pane.contains(target) is true, so the fallback
  // must be a no-op here.
  self._onDocMouseUp(fakeEvent({ clientX: 5, clientY: 5, target: 'inside-pane-node' }));
  await self._sendChain;

  console.log(JSON.stringify({
    countAfterPaneHandler: countAfterPaneHandler,
    countAfterBubble: __callCount,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["countAfterBubble"], result["countAfterPaneHandler"],
            "an in-pane release must not be double-reported by the document-level fallback",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_pane_contains_guard_alone_prevents_a_redundant_send(self):
        # Isolates the `pane.contains(ev.target)` early-return specifically -- unlike the previous
        # test, `_mouseButtonDown` is deliberately left NON-null here (as it would be if the
        # gate had declined the pane's own release, e.g. Shift held), so the null-check alone
        # would NOT skip this call; only the containment check does.
        script = self._wired_self(True) + """
async function main() {
  var self = makeSelf('tty8');
  self.mouse = { mode: 1002, sgr: false };
  self._mouseButtonDown = 0;   // still set -- as if the pane's own handler never cleared it

  var addedHandlers = {};
  var fakeDocument = { addEventListener: function (name, fn) { addedHandlers[name] = fn; },
                        removeEventListener: function () {} };
  var fakePane = { contains: function (t) { return t === 'inside-pane-node'; } };
  wireOutsidePaneFallback.call(self, fakePane, fakeDocument);
  self._onDocMouseUp = addedHandlers['mouseup'];

  self._onDocMouseUp(fakeEvent({ clientX: 5, clientY: 5, target: 'inside-pane-node' }));
  await self._sendChain;

  console.log(JSON.stringify({ sentCount: __callCount, buttonDown: self._mouseButtonDown }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["sentCount"], 0,
            "pane.contains(ev.target) must short-circuit before any report is sent",
        )
        # Even though the containment check skipped the SEND, the fallback's own body never runs
        # past that early `return;`, so button state is untouched by this call (whatever cleared
        # it, if anything, was the pane's own listener -- out of scope for this isolated call).
        self.assertEqual(result["buttonDown"], 0)


class TestMultiFrameMotionRegression(unittest.TestCase):
    """Closes the exact gap an adversarial review found: EVERY existing test above sends motion
    within a SINGLE animation frame (coalescing several _sendMotion() calls down to one flush,
    then stopping) -- none drives motion across more than one frame. That let a regression which
    drops `self._motionRAFPending = false;` from inside the rAF callback (so _sendMotion's
    `if (this._motionRAFPending) return;` guard stays permanently tripped after the very first
    flush, and every motion produced afterwards is coalesced into `_pendingMotion` but never
    scheduled to flush again) pass all 8 tests above while motion silently died in the real app
    after the first coalesced flush.

    This test drives 5 SEPARATE flush cycles (motion(s) -> flushRAF() -> motion(s) -> flushRAF()
    -> ...) and asserts EVERY cycle delivers exactly one motion report, carrying that cycle's
    newest payload -- the thing the broken variant cannot do past cycle 1.

    Proved RED against the broken variant by hand (see the task's own instructions): temporarily
    deleted the `self._motionRAFPending = false;` line from Terminal.prototype._sendMotion in
    aitracker/web/ext_vt.js, reran this exact test, observed the failure below, then restored the
    line and reran to confirm green again.

        FAIL: test_five_separate_flush_cycles_each_deliver_the_newest_motion
        AssertionError: Lists differ: ['frame1'] != ['frame1', 'frame2', 'frame3', 'frame4', 'frame5']

        Second list contains 4 additional elements.
        First extra element 1:
        'frame2'

        - ['frame1']
        + ['frame1', 'frame2', 'frame3', 'frame4', 'frame5'] : every one of the 5 separate flush
        cycles must deliver exactly one motion report, carrying that cycle's newest payload --
        this is the exact scenario (_motionRAFPending never reset) that let motion silently die
        after cycle 1 while still passing all previously existing tests

    (captured verbatim from an actual `python3 -m unittest
    tests.test_term_vt_exec.TestMultiFrameMotionRegression -v` run against that broken variant;
    restored and reconfirmed green immediately after.)
    """

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_five_separate_flush_cycles_each_deliver_the_newest_motion(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-multi');
  var callsAfterEachFrame = [];
  for (var i = 1; i <= 5; i++) {
    // Two motions per frame, produced BEFORE that frame's flush -- within-frame coalescing (the
    // pre-existing, already-tested behaviour) must still hold: only the newer of the two is
    // delivered. The thing under test is ACROSS frames: cycle 2's flush must fire independently
    // of cycle 1's, which is exactly what a never-reset _motionRAFPending prevents.
    self._sendMotion.call(self, 'stale-frame' + i);
    self._sendMotion.call(self, 'frame' + i);
    flushRAF();
    await self._sendChain;
    callsAfterEachFrame.push(__calls.length);
  }
  console.log(JSON.stringify({ calls: __calls, callsAfterEachFrame: callsAfterEachFrame }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["calls"],
            ["frame1", "frame2", "frame3", "frame4", "frame5"],
            "every one of the 5 separate flush cycles must deliver exactly one motion report, "
            "carrying that cycle's newest payload -- this is the exact scenario "
            "(_motionRAFPending never reset) that let motion silently die after cycle 1 while "
            "still passing all previously existing tests",
        )
        self.assertEqual(
            result["callsAfterEachFrame"], [1, 2, 3, 4, 5],
            "each frame's flush must land exactly one NEW call -- a call count that stalls at 1 "
            "is precisely the never-reset-_motionRAFPending regression",
        )


class TestDestroyCancelsScheduledMotion(unittest.TestCase):
    """Item 1 from the review: Terminal.prototype.destroy() did not clear `_pendingMotion` /
    `_motionRAFPending` and never cancelled the scheduled requestAnimationFrame -- so a motion
    scheduled just before destroy() posted a stray /api/term/keys for an already-torn-down
    terminal once that rAF eventually fired. Proven here by executing the real extracted
    destroy()/_sendMotion(): schedule a motion, destroy() the terminal, then fire the callback
    that was handed to requestAnimationFrame() ANYWAY (as if cancellation itself had somehow
    raced/failed) -- postKeys must still never be called, because destroy() also clears
    `_pendingMotion` as a second, independent guard."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_cancels_the_scheduled_frame_and_a_late_fire_sends_nothing(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _DESTROY_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-destroy');
  self._sendMotion.call(self, 'MOTION-should-never-post');
  var handleBeforeDestroy = self._motionRAFHandle;
  var pendingCallback = __rafQueue[handleBeforeDestroy];   // capture it before destroy() nulls the slot

  self.destroy.call(self);

  // Belt-and-suspenders check #1: destroy() must have actually asked to cancel the exact frame
  // _sendMotion scheduled.
  var cancelledTheRightId = __cancelledRAFIds.indexOf(handleBeforeDestroy) !== -1;

  // Belt-and-suspenders check #2: even calling the raw callback directly -- bypassing
  // cancellation entirely, worst case -- must be a no-op, because destroy() independently
  // cleared _pendingMotion/_motionRAFPending on `self`.
  fireAllRAF([pendingCallback]);
  await self._sendChain;

  console.log(JSON.stringify({
    calls: __calls,
    handleBeforeDestroy: handleBeforeDestroy,
    cancelledTheRightId: cancelledTheRightId,
    handleAfterDestroy: self._motionRAFHandle,
    motionRAFPendingAfterDestroy: self._motionRAFPending,
    pendingMotionAfterDestroy: self._pendingMotion,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertIsNotNone(result["handleBeforeDestroy"], "a frame must actually have been scheduled")
        self.assertTrue(
            result["cancelledTheRightId"],
            "destroy() must cancelAnimationFrame() the exact handle _sendMotion scheduled",
        )
        self.assertIsNone(result["handleAfterDestroy"], "destroy() must clear _motionRAFHandle")
        self.assertFalse(result["motionRAFPendingAfterDestroy"], "destroy() must clear _motionRAFPending")
        self.assertIsNone(result["pendingMotionAfterDestroy"], "destroy() must clear _pendingMotion")
        self.assertEqual(
            result["calls"], [],
            "a rAF that fires after destroy() -- even if cancellation itself didn't stop it -- "
            "must never reach postKeys() for an already-torn-down terminal",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_motion_still_works_normally_on_a_live_non_destroyed_terminal(self):
        # Guards against an over-eager fix (e.g. clearing state unconditionally on every send)
        # breaking ordinary motion on a terminal that is NOT being destroyed.
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _DESTROY_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-live');
  self._sendMotion.call(self, 'M1');
  flushRAF();
  await self._sendChain;
  self._sendMotion.call(self, 'M2');
  flushRAF();
  await self._sendChain;
  console.log(JSON.stringify({ calls: __calls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["calls"], ["M1", "M2"])


if __name__ == "__main__":
    unittest.main()
