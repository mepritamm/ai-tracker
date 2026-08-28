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
import re
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
        _function_body(_SRC, "Terminal.prototype._sendWithTimeout = function"),
        _function_body(_SRC, "Terminal.prototype._flushMotion = function"),
        _function_body(_SRC, "Terminal.prototype._send = function"),
        _function_body(_SRC, "Terminal.prototype._sendMotion = function"),
    ])

    # keyToBytes is a bare top-level function (not a Terminal.prototype method), so it's extracted
    # by literal span the same way the constructor's outside-pane wiring is above: from its own
    # declaration through (but not including) the very next function declaration in the file.
    _key_start = _SRC.index("function keyToBytes(ev) {")
    _key_end = _SRC.index("function b64utf8(")
    _KEY_TO_BYTES_SRC = _SRC[_key_start:_key_end]

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

    # The mouse-reporting toggle's real wiring: the `mouseToggle` interface object literal built
    # inside the Terminal constructor and handed to buildToolbar (see that function's own header
    # comment). Extracted the same span way as the outside-pane fallback above, because it too is
    # a closure captured inline in the constructor, not a `Terminal.prototype.X`. Using the REAL
    # `setEnabled`/`getEnabled` here (instead of a test just poking `self.mouseReportingEnabled`
    # by hand) is what actually closes the gap this module's own header/the task brief describe:
    # tests/test_term_vt_client.py's TestMouseReportingToggle pins that buildToolbar CALLS
    # `mouseToggle.setEnabled(...)` by name, but never checks what field that real `setEnabled`
    # writes -- a future edit that had it write to a differently-named property would still pass
    # every one of those source-text pins. Routing through the extracted `setEnabled`/`getEnabled`
    # closures here means a regression like that breaks THESE tests instead.
    _MOUSE_TOGGLE_WIRING_SRC = _span(
        _SRC,
        "getEnabled: function () { return self.mouseReportingEnabled; },",
        "isMeaningful: function () { return self.mouse.mode !== 0; }",
    )

    # ===== 256-colour / true-colour SGR rendering (this session) =====
    # `sgrRunClass` plus its helpers (_byte255, _stdColorClass, _cubeLevel, _256Rgb) are all
    # plain top-level functions declared back-to-back, bounded by the next top-level function
    # declaration (`keyToBytes`) -- same "span between two literal markers" extraction strategy
    # _KEY_TO_BYTES_SRC above already uses for a bare (non Terminal.prototype) function.
    _sgr_start = _SRC.index("function _byte255(tok) {")
    _sgr_end = _SRC.index("function keyToBytes(ev) {")
    _SGR_HELPERS_SRC = _SRC[_sgr_start:_sgr_end]

    # `esc()` is a one-line `var` assignment at the very top of the IIFE, and `_padSpaces` is a
    # small top-level function declared immediately before `Terminal.prototype._paintRow` --
    # both needed alongside _SGR_HELPERS_SRC to run the real _paintRow standalone.
    _esc_start = _SRC.index("var esc = window.esc")
    _esc_end = _SRC.index("\n", _esc_start)
    _ESC_SRC = _SRC[_esc_start:_esc_end]
    _padspaces_start = _SRC.index("function _padSpaces(n) {")
    _PADSPACES_SRC = _SRC[_padspaces_start:_SRC.index("Terminal.prototype._paintRow = function")]
    _PAINT_ROW_SRC = _function_body(_SRC, "Terminal.prototype._paintRow = function")

    # ===== XtermTerminal: the async-load-vs-destroy race (this session) =====
    # Everything from `_b64ToBytes` (used by `_openStream`'s onmessage) through the end of
    # `XtermTerminal.prototype.destroy` -- one contiguous span covering `_xtermTheme`, the
    # `XtermTerminal` constructor, `attach`/`_build`/`_doResize`/`_zoom`/`_openStream`/
    # `measureAndResize`/`focus`/`destroy`. Bounded by the "===== the modal" comment that opens
    # the next section of the file, the same "span between two literal markers" strategy
    # `_SGR_HELPERS_SRC` above already uses.
    _xterm_leak_start = _SRC.index("function _b64ToBytes(")
    _xterm_leak_end = _SRC.index("// ===== the modal")
    _XTERM_LEAK_SRC = _SRC[_xterm_leak_start:_xterm_leak_end]

    # ===== bell flash: the ONE shared helper both renderers call (this task) =====
    # `_flashBellPane` sits in the GRID section of the file (right before `Terminal.prototype.
    # _flashBell`, which is itself outside `_XTERM_LEAK_SRC` above) but XtermTerminal._build's own
    # onBell handler calls it directly -- so any XtermTerminal-bell test needs this pulled in
    # separately, span-extracted the same "between two literal markers" way as `_XTERM_LEAK_SRC`.
    # Also grabs `Terminal.prototype._flashBell` itself (the grid delegate), used by the grid-path
    # regression test below via `_APPLY_PATCH_SRC`.
    _flashbell_start = _SRC.index("function _flashBellPane(pane) {")
    _flashbell_end = _SRC.index("// ===== font size:")
    _FLASH_BELL_SRC = _SRC[_flashbell_start:_flashbell_end]

    # `Terminal.prototype._applyPatch` -- the grid renderer's server-counter-driven bell trigger
    # (`if (typeof msg.bell === "number") { if (this._bellSeen !== null && msg.bell !==
    # this._bellSeen) this._flashBell(); this._bellSeen = msg.bell; }`), extracted whole via the
    # same `_function_body` helper the rest of this module already uses for single methods.
    _APPLY_PATCH_SRC = _function_body(_SRC, "Terminal.prototype._applyPatch = function")

    # ===== notice banner: the ONE mount-owned helper both renderers feed (this task) =====
    # `createNoticeBanner` (plus its `NOTICE_MAX` constant) replaced THREE near-copies of the same
    # build-a-.vtnotice-div logic -- Terminal.prototype._displayNotice, openVT's open-time
    # `res.j.notice` block, and bootStandalone's `?notice=` block. It is module-scope in ext_vt.js
    # between `observePane` and `buildToolbar`, so it is span-extracted the same "between two
    # literal markers" way as _XTERM_LEAK_SRC/_CONTEXT_BAR_SRC above.
    _notice_start = _SRC.index("var NOTICE_MAX = 3;")
    _notice_end = _SRC.index("// ===== shared zoom toolbar")
    _NOTICE_BANNER_SRC = _SRC[_notice_start:_notice_end]

    # ===== ContextBar: model/effort switchers, attach-gating, usage readout (this task) =====
    # tests/test_term_vt_client.py used to assert the WHOLE of this behaviour by grepping the
    # source text (e.g. "the inject POST body contains these substrings"), which stays true even
    # if the feature is completely broken at runtime -- an adversarial review's actual finding.
    # These two spans pull the real code out verbatim (never retyped) so it can be executed under
    # Node instead: MODEL_LADDER/EFFORT_LADDER/_matchLadderModel/fmtTok/readContextUsage (plain
    # top-level helpers ContextBar's own methods call), then the ContextBar constructor through
    # the end of `ContextBar.prototype.destroy` -- one contiguous span, the same "between two
    # literal markers" strategy `_XTERM_LEAK_SRC` above already uses. `renderCapBlock` (the next
    # top-level function after destroy) is the bound; it is unrelated to ContextBar and not needed
    # here.
    _ctxbar_helpers_start = _SRC.index("var MODEL_LADDER = [")
    _ctxbar_helpers_end = _SRC.index("function ContextBar(container, sid, ttyId, mode, getInput) {")
    _CONTEXT_BAR_HELPERS_SRC = _SRC[_ctxbar_helpers_start:_ctxbar_helpers_end]

    _ctxbar_start = _ctxbar_helpers_end
    _ctxbar_end = _SRC.index("function renderCapBlock(")
    _CONTEXT_BAR_SRC = _SRC[_ctxbar_start:_ctxbar_end]

    # ===== "Manage terminals" panel: the kill-all safety guard (this task) =====
    # A double-click on "Close all" SIGKILLed every running terminal without the confirmation ever
    # being displayed for a single frame -- 15 source-text-grep tests all stayed green while this
    # was true, because none of them ever ran the code. Extracted the same "span between two
    # literal markers" way as `_XTERM_LEAK_SRC`/`_CONTEXT_BAR_SRC` above: `buildTermRow` (the row
    # builder the cap block AND this panel share -- conventions rule 4, one row shape, not two)
    # through `function renderCapBlock(` (the cap block itself is unrelated and not needed here),
    # then the whole manager-panel banner comment through (but not including) `window.ExtVT =`.
    #
    # The second span's end is found via `_SRC.index("window.ExtVT =", _mgr_start)` -- i.e. a
    # search that starts AFTER the manager section itself -- rather than a bare `_SRC.index(...)`
    # from the top of the file: `"window.ExtVT ="` also appears verbatim in this file's own header
    # comment near line 7 ("Exposes window.ExtVT = {open(sid, mode), manage()} ..."), which sits
    # BEFORE `_mgr_start`. A bare `.index` would resolve to that comment instead, and slicing
    # `_SRC[_mgr_start:end]` with an end index smaller than the start silently returns an empty
    # string rather than raising -- so a test built on it would import zero code and pass on
    # nothing asserted, not fail loudly. Confirmed by hand while building this harness.
    _buildrow_start = _SRC.index("function buildTermRow(t, now, actions) {")
    _buildrow_end = _SRC.index("function renderCapBlock(")
    _BUILD_TERM_ROW_SRC = _SRC[_buildrow_start:_buildrow_end]

    _mgr_start = _SRC.index('// ===== "Manage terminals" panel')
    _mgr_end = _SRC.index("window.ExtVT =", _mgr_start)
    _MANAGER_PANEL_SRC = _SRC[_mgr_start:_mgr_end]


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
var __rejectNth = null;      // 1-based index of a postKeys() call to make reject, or null
var __neverResolveNth = null;   // 1-based index of a postKeys() call that NEITHER resolves NOR
                                 // rejects -- ever -- simulating the observed background-tab hang
                                 // (a real POST /api/term/keys stuck ~5 minutes under Chrome's
                                 // throttling). Used to prove _sendWithTimeout's bound is what
                                 // advances the chain, not the request itself ever settling.
var __callCount = 0;
function postKeys(tty, s) {
  __callCount++;
  __calls.push(s);
  if (__neverResolveNth !== null && __callCount === __neverResolveNth) {
    return new Promise(function () { });   // deliberately never resolves or rejects
  }
  if (__rejectNth !== null && __callCount === __rejectNth) {
    return Promise.reject(new Error('simulated network hiccup'));
  }
  return Promise.resolve({ ok: true });
}
// Manually-driven setTimeout/clearTimeout -- shadows the real Node globals by name within this
// script (same trick already used for requestAnimationFrame/cancelAnimationFrame/document below),
// so _sendWithTimeout's 5000ms timer never has to actually elapse in real wall-clock time for the
// test to control exactly when it fires.
var __timeoutQueue = [];      // [{id, cb, ms, cancelled}]
var __cancelledTimeoutIds = [];
var __nextTimeoutId = 1;
function setTimeout(cb, ms) {
  var id = __nextTimeoutId++;
  __timeoutQueue.push({ id: id, cb: cb, ms: ms, cancelled: false });
  return id;
}
function clearTimeout(id) {
  __cancelledTimeoutIds.push(id);
  for (var i = 0; i < __timeoutQueue.length; i++) {
    if (__timeoutQueue[i].id === id) __timeoutQueue[i].cancelled = true;
  }
}
// Fires every still-pending (non-cancelled) mock timer's callback, simulating however much real
// time would need to pass -- mirrors flushRAF()'s "nothing fires until told to" design.
function fireAllTimeouts() {
  var q = __timeoutQueue; __timeoutQueue = [];
  q.forEach(function (t) { if (!t.cancelled) t.cb(); });
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
    _sendTimers: [],
    _pendingMotion: null,
    _motionRAFPending: false,
    _motionRAFHandle: null,
    _mouseButtonDown: null,
    _lastMouseCell: null,
    mouse: { mode: 0, sgr: false },
    // Real boolean default, matching the production Terminal constructor's own
    // `this.mouseReportingEnabled = false;` -- NOT left undefined. A test double that predates a
    // field and leaves it undefined is exactly how a `=== false` gate check can silently mean
    // "enabled" for every scenario built on this helper; see _mouseGate's own comment and
    // TestMouseReportingToggleGateExecuted below for the tests that actually exercise this.
    mouseReportingEnabled: false,
    viewingHistory: false,
    cols: 80, rows: 24,
    rowsEl: { getBoundingClientRect: function () { return { left: 0, top: 0 }; } },
    cellW: 8, cellH: 16,
    es: null,
    _onDocMouseUp: null,
    _noticeEls: [],
    measureAndResize: function () {},
    _enqueue: Terminal.prototype._enqueue,
    _sendWithTimeout: Terminal.prototype._sendWithTimeout,
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


class TestKeyToBytesComposedCharacters(unittest.TestCase):
    """DEFECT 1, executed: keyToBytes used to ESC-prefix ANY single-character Alt/Option key,
    including a COMPOSED character. On macOS, Option is `altKey`, and Option+key produces the
    composed character directly in `ev.key` -- Option+2 arrives as {altKey: true, key: "€"}
    ("€" == the EURO SIGN), so the old `ev.key.length === 1` check let it through and sent
    ESC + "€", corrupting a character the user simply typed. Fixed by restricting the
    Alt-prefix path to the printable ASCII range -- a composed/non-ASCII character now returns
    null and falls through to the textarea's own `input` handler instead."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def _key_to_bytes(self, ev_overrides):
        script = _HARNESS_PRELUDE + _KEY_TO_BYTES_SRC + """
var ev = {
  ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, key: "",
};
""" + "\n".join(
            "ev.%s = %s;" % (k, json.dumps(v)) for k, v in ev_overrides.items()
        ) + """
var result = keyToBytes(ev);
console.log(JSON.stringify({ result: result }));
"""
        return _run_node(script)["result"]

    def test_option_2_composed_euro_sign_is_not_esc_prefixed(self):
        # The exact scenario from the defect report: Option+2 on a Mac keyboard.
        result = self._key_to_bytes({"altKey": True, "key": "€"})
        self.assertIsNone(
            result,
            "a composed character must fall through to the textarea, not get ESC-prefixed",
        )

    def test_another_composed_option_character_is_also_rejected(self):
        # Option+p on a US Mac layout composes "π" (GREEK SMALL LETTER PI) -- a second,
        # independent example of the same composed-character class, not just the one the defect
        # report happened to name.
        result = self._key_to_bytes({"altKey": True, "key": "π"})
        self.assertIsNone(result)

    def test_plain_ascii_alt_letter_still_gets_the_meta_prefix(self):
        # The line's actual intent (readline's Alt+b word-motion binding) must still work --
        # this is the regression guard against an over-broad fix that rejects everything.
        result = self._key_to_bytes({"altKey": True, "key": "b"})
        self.assertEqual(result, "\x1bb")

    def test_plain_ascii_alt_digit_still_gets_the_meta_prefix(self):
        # A plain US-layout Alt+2 (no composition happens on that layout) must be unaffected --
        # this is what proves the fix narrowed to "non-ASCII", not to "letters only".
        result = self._key_to_bytes({"altKey": True, "key": "2"})
        self.assertEqual(result, "\x1b2")

    def test_windows_linux_altgr_is_excluded_by_the_pre_existing_ctrlkey_guard(self):
        # AltGr on Windows/Linux reports BOTH ctrlKey and altKey set. Even though "@" itself is
        # plain ASCII (and so would otherwise pass the new range check), this must still be
        # excluded -- but by the line's OWN pre-existing `!ev.ctrlKey` guard, not by the ASCII
        # check added here. Confirms the two guards are independent and both hold.
        result = self._key_to_bytes({"altKey": True, "ctrlKey": True, "key": "@"})
        self.assertNotEqual(result, "\x1b@")

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        from aitracker.page import build_page
        page = build_page()
        self.assertIn(r"/^[\x20-\x7e]$/.test(ev.key)", page)


class TestSendTimeoutRegression(unittest.TestCase):
    """DEFECT 2, executed: a queued send that never SETTLES (neither resolves nor rejects -- the
    observed real failure was a `POST /api/term/keys` hung ~5 minutes under Chrome's
    background-tab throttling, vs. a control curl to the same endpoint returning in 17ms) used to
    block `_sendChain` -- and therefore every later keystroke -- forever. `_sendWithTimeout` bounds
    each queued send with a 5000ms timer raced against the real request, so the chain always
    advances. Uses the harness's mock setTimeout/clearTimeout (see `_harness_mocks()`) so the
    5000ms never has to actually elapse in wall-clock time."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_never_settling_send_does_not_block_later_sends_forever(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-hang');
  __neverResolveNth = 1;   // the FIRST postKeys() call hangs forever, like the observed bug
  self._send.call(self, 'a');
  // Drain pending microtasks WITHOUT advancing the (mock) clock -- 'b' must NOT have reached
  // postKeys yet. This is the ordering guarantee: a later send must not overtake an earlier one
  // that is still in flight, only stand behind it until it times out.
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  self._send.call(self, 'b');
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  var callsBeforeTimeout = __calls.slice();

  fireAllTimeouts();   // simulate the 5000ms elapsing for 'a's still-hung request
  await self._sendChain;

  console.log(JSON.stringify({
    callsBeforeTimeout: callsBeforeTimeout,
    callsAfterTimeout: __calls,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["callsBeforeTimeout"], ["a"],
            "while 'a' is still hung (before its timeout fires), 'b' must not have been issued "
            "-- a later send must never overtake one still in flight",
        )
        self.assertEqual(
            result["callsAfterTimeout"], ["a", "b"],
            "once 'a' times out the chain must advance and 'b' must still be sent, in order",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_send_is_bounded_by_a_five_second_timeout(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-delay');
  self._send.call(self, 'x');
  await Promise.resolve(); await Promise.resolve();
  console.log(JSON.stringify({ delays: __timeoutQueue.map(function (t) { return t.ms; }) }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["delays"], [5000],
            "each queued send must be bounded by a 5000ms timeout",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_a_send_that_settles_normally_clears_its_own_timer(self):
        # Proves the timer doesn't leak/double-fire on the ordinary (healthy) path: once postKeys
        # resolves normally, its timer must be cancelled, not left pending.
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-healthy');
  self._send.call(self, 'x');
  await self._sendChain;
  console.log(JSON.stringify({
    cancelledCount: __cancelledTimeoutIds.length,
    stillQueued: __timeoutQueue.length,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["cancelledCount"], 1, "the settled send's own timer must be cleared")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_timed_out_payload_is_dropped_like_a_rejected_send(self):
        # A timed-out send must not be retried -- exactly like an ordinarily-rejected send, it is
        # simply dropped. Proven by never seeing 'a' reach postKeys() a second time.
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-drop');
  __neverResolveNth = 1;
  self._send.call(self, 'a');
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  fireAllTimeouts();
  await self._sendChain;
  console.log(JSON.stringify({ calls: __calls, count: __callCount }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["calls"], ["a"],
            "the timed-out send must never be retried/resent",
        )
        self.assertEqual(result["count"], 1)


class TestDestroyClearsSendTimers(unittest.TestCase):
    """destroy() must clear any outstanding send-timeout timers (see _sendWithTimeout), the same
    way it already cancels a scheduled motion rAF -- otherwise a timer from a send still in flight
    at teardown time keeps running past destroy(), which the brief explicitly rules out."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_cancels_the_pending_send_timer(self):
        script = _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _DESTROY_SRC + _harness_mocks() + """
async function main() {
  var self = makeSelf('tty-destroy-timer');
  __neverResolveNth = 1;   // the send hangs -- its timer is still pending at destroy() time
  self._send.call(self, 'a');
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  var pendingBeforeDestroy = self._sendTimers.length;

  self.destroy.call(self);

  console.log(JSON.stringify({
    pendingBeforeDestroy: pendingBeforeDestroy,
    pendingAfterDestroy: self._sendTimers.length,
    cancelledCount: __cancelledTimeoutIds.length,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["pendingBeforeDestroy"], 1, "a timer must actually be pending first")
        self.assertEqual(result["pendingAfterDestroy"], 0, "destroy() must clear _sendTimers")
        self.assertEqual(result["cancelledCount"], 1, "destroy() must clearTimeout() the pending timer")


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
  self.mouseReportingEnabled = true;   // this scenario is about outside-pane release plumbing,
                                        // not the toggle -- keep the gate open exactly like every
                                        // one of these tests behaved before the toggle field
                                        // existed (see makeSelf's own comment on the field).
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
  self.mouseReportingEnabled = true;   // see tty5's comment above -- keep the gate open
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
  self.mouseReportingEnabled = true;   // see tty5's comment above -- keep the gate open
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
  self.mouseReportingEnabled = true;   // see tty5's comment above -- keep the gate open
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


class TestMouseReportingToggleGateExecuted(unittest.TestCase):
    """Closes the gap this module's own header/the task brief describe: tests/test_term_vt_client.py's
    TestMouseReportingToggle proves the SHAPE of the toggle (13 source-text pins -- the toolbar
    calls `mouseToggle.setEnabled(...)`, `_mouseGate` mentions `this.mouseReportingEnabled`, in the
    right order relative to the other three checks) but never actually RUNS any of it. Nothing
    instantiates a real gate call with the flag flipped and observes the resulting boolean or
    postKeys call -- so the toggle's actual runtime interaction with the other three gate
    conditions (mode/shift/viewingHistory) was proven by nobody, and a future change that had
    `setEnabled` write to a differently-named property would still pass every one of those pins.

    These tests route through the REAL extracted `getEnabled`/`setEnabled`/`isMeaningful` closures
    (Terminal's constructor `mouseToggle` object handed to buildToolbar -- see
    `_MOUSE_TOGGLE_WIRING_SRC`'s own comment above), not a hand-poked `self.mouseReportingEnabled`,
    specifically so a `setEnabled`-writes-the-wrong-field regression breaks THESE tests instead of
    sailing through every text pin unnoticed."""

    def _toggle_wired_self_script(self):
        return (
            _HARNESS_PRELUDE + _SEND_ORDERING_SRC + _MOUSE_METHODS_SRC + _harness_mocks()
            + "function makeMouseToggle(self) {\n  return {\n    " + _MOUSE_TOGGLE_WIRING_SRC
            + "\n  };\n}\n"
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_toggle_off_blocks_mousedown_and_gate_returns_false(self):
        script = self._toggle_wired_self_script() + """
async function main() {
  var self = makeSelf('tty-toggle-off');
  self.mouse = { mode: 1000, sgr: false };   // a program HAS asked for tracking...
  var mouseToggle = makeMouseToggle(self);
  mouseToggle.setEnabled(false);             // ...but the user's toolbar toggle is off (default)
  var ev = fakeEvent({ clientX: 10, clientY: 10, target: 'inside' });
  var gateResult = self._mouseGate.call(self, ev);
  self._onMouseDown.call(self, ev);
  await self._sendChain;
  console.log(JSON.stringify({ gateResult: gateResult, sentCount: __callCount }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertFalse(result["gateResult"], "_mouseGate must return false while the toggle is off")
        self.assertEqual(result["sentCount"], 0, "a mousedown must produce no postKeys call while the toggle is off")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_toggle_on_allows_mousedown_and_gate_returns_true(self):
        script = self._toggle_wired_self_script() + """
async function main() {
  var self = makeSelf('tty-toggle-on');
  self.mouse = { mode: 1000, sgr: false };
  var mouseToggle = makeMouseToggle(self);
  mouseToggle.setEnabled(true);              // the user has flipped the toolbar toggle on
  var ev = fakeEvent({ clientX: 10, clientY: 10, target: 'inside' });
  var gateResult = self._mouseGate.call(self, ev);
  self._onMouseDown.call(self, ev);
  await self._sendChain;
  console.log(JSON.stringify({ gateResult: gateResult, sentCount: __callCount, sent: __calls[0] || null }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertTrue(result["gateResult"], "_mouseGate must return true once the toggle is on")
        self.assertEqual(result["sentCount"], 1, "a mousedown must produce exactly one mouse report once the toggle is on")
        self.assertIsInstance(result["sent"], str)
        self.assertTrue(len(result["sent"]) > 0, "the mouse report payload must be non-empty")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_toggle_on_does_not_override_the_other_three_gate_conditions(self):
        # Pins the actual INTERACTION: the toggle is a FOURTH, additional gate (per _mouseGate's
        # own comment) -- it must never bypass the pre-existing mode/shift/viewingHistory checks,
        # even once the user has explicitly turned it on.
        script = self._toggle_wired_self_script() + """
async function main() {
  var out = {};

  // shiftKey drag must still be bypassed (the user's native-selection escape hatch) even with
  // the toggle ON.
  var s1 = makeSelf('tty-toggle-shift');
  s1.mouse = { mode: 1000, sgr: false };
  makeMouseToggle(s1).setEnabled(true);
  var ev1 = fakeEvent({ clientX: 1, clientY: 1, target: 'inside', shiftKey: true });
  var before1 = __callCount;
  var gate1 = s1._mouseGate.call(s1, ev1);
  s1._onMouseDown.call(s1, ev1);
  await s1._sendChain;
  out.shiftKey = { gate: gate1, sent: __callCount - before1 };

  // mouse.mode === 0 (no program has asked for tracking) must still block, even with the toggle ON.
  var s2 = makeSelf('tty-toggle-mode0');
  s2.mouse = { mode: 0, sgr: false };
  makeMouseToggle(s2).setEnabled(true);
  var ev2 = fakeEvent({ clientX: 1, clientY: 1, target: 'inside' });
  var before2 = __callCount;
  var gate2 = s2._mouseGate.call(s2, ev2);
  s2._onMouseDown.call(s2, ev2);
  await s2._sendChain;
  out.modeZero = { gate: gate2, sent: __callCount - before2 };

  // viewingHistory (a frozen scrollback snapshot) must still block, even with the toggle ON.
  var s3 = makeSelf('tty-toggle-history');
  s3.mouse = { mode: 1000, sgr: false };
  s3.viewingHistory = true;
  makeMouseToggle(s3).setEnabled(true);
  var ev3 = fakeEvent({ clientX: 1, clientY: 1, target: 'inside' });
  var before3 = __callCount;
  var gate3 = s3._mouseGate.call(s3, ev3);
  s3._onMouseDown.call(s3, ev3);
  await s3._sendChain;
  out.viewingHistory = { gate: gate3, sent: __callCount - before3 };

  console.log(JSON.stringify(out));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertFalse(result["shiftKey"]["gate"], "Shift+drag must still bypass reporting even with the toggle on")
        self.assertEqual(result["shiftKey"]["sent"], 0)
        self.assertFalse(result["modeZero"]["gate"], "mode===0 (tracking off) must still block even with the toggle on")
        self.assertEqual(result["modeZero"]["sent"], 0)
        self.assertFalse(result["viewingHistory"]["gate"], "viewingHistory must still block even with the toggle on")
        self.assertEqual(result["viewingHistory"]["sent"], 0)


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


class TestSgrColourRendering(unittest.TestCase):
    """256-colour (38;5;N / 48;5;N) and true-colour (38;2;R;G;B / 48;2;R;G;B) support: the Python
    emulator's SGR parser already resolves these into the run's code string (CONFIRMED against
    Screen._sgr / Screen._recompute_code in term_vt.py -- e.g. "38;5;208" or "7;48;2;10;20;30"),
    but sgrRunClass()/_paintRow used to silently drop anything outside the 16 plain ANSI codes.
    Driven EXECUTED (not just source-pinned) because the interesting failure mode -- a malformed
    or out-of-range extended sequence leaking raw text into the `style` attribute _paintRow
    builds -- is exactly the class of bug a text-only assertion cannot catch."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def _sgr(self, sgr_string):
        script = _HARNESS_PRELUDE + _SGR_HELPERS_SRC + """
var result = sgrRunClass(""" + json.dumps(sgr_string) + """);
console.log(JSON.stringify({ result: result }));
"""
        return _run_node(script)["result"]

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def _paint(self, text, runs, cols=None):
        script = _HARNESS_PRELUDE + "\nvar window = {};\n" + _ESC_SRC + "\n" + _SGR_HELPERS_SRC + "\n" + _PADSPACES_SRC + "\n" + _PAINT_ROW_SRC + """
var self = {
  viewingHistory: false,
  historyGrid: [],
  grid: [{ text: """ + json.dumps(text) + """, runs: """ + json.dumps(runs) + """ }],
  rowEls: [{ innerHTML: "" }],
  cols: """ + str(cols if cols is not None else len(text)) + """
};
Terminal.prototype._paintRow.call(self, 0);
console.log(JSON.stringify({ html: self.rowEls[0].innerHTML }));
"""
        return _run_node(script)["html"]

    # ----- sgrRunClass: 256-colour cube -----------------------------------------------------

    def test_256_colour_cube_value_produces_the_derived_rgb_style(self):
        # 38;5;208 -- a mid-cube index (not 0-15, not the greyscale ramp). i = 208-16 = 192;
        # r-level = 192//36 = 5 -> 255, g-level = (192//6)%6 = 2 -> 135, b-level = 192%6 = 0 -> 0.
        # This is xterm's documented "DarkOrange"-ish 208 swatch.
        out = self._sgr("38;5;208")
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "color:rgb(255,135,0);")

    def test_256_colour_greyscale_ramp_value(self):
        # 48;5;244 -- greyscale ramp (232-255): v = 8 + 10*(244-232) = 128, i.e. a mid grey,
        # applied as a BACKGROUND (48, not 38).
        out = self._sgr("48;5;244")
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "background-color:rgb(128,128,128);")

    def test_256_colour_low_index_reuses_the_existing_ansi_class_path(self):
        # Indices 0-15 must NOT go through the inline-style path at all -- they reuse the same
        # vtf*/vtg* classes the plain 30-37/90-97/40-47 codes already use (one set of CSS rules).
        fg_dim = self._sgr("38;5;3")          # 3 < 8 -> plain, maps to the existing 30+3 class
        self.assertEqual(fg_dim["cls"], "vtf33")
        self.assertEqual(fg_dim["style"], "")
        fg_bright = self._sgr("38;5;12")      # 12 >= 8 -> bright, maps to the existing 90+(12-8)
        self.assertEqual(fg_bright["cls"], "vtf94")
        self.assertEqual(fg_bright["style"], "")

    def test_true_colour_rgb_foreground(self):
        out = self._sgr("38;2;255;99;71")     # tomato
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "color:rgb(255,99,71);")

    def test_true_colour_background_variant(self):
        out = self._sgr("48;2;10;20;30")
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "background-color:rgb(10,20,30);")

    def test_out_of_range_index_is_dropped_not_clamped_or_guessed(self):
        # 999 is not a valid byte -- the run's colour must be dropped entirely (default colour),
        # never clamped into range and never silently reinterpreted.
        out = self._sgr("38;5;999")
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "")

    def test_truncated_truecolor_sequence_is_swallowed_not_misparsed(self):
        # "38;2;10;20" is missing the blue component. Mirrors Screen._sgr's own defence against a
        # truncated extended sequence: the malformed tail must be consumed so it can never fall
        # through and be reinterpreted as unrelated SGR codes (e.g. "20" as some other attribute).
        # Bold (1) before it must still register; nothing after must leak through as a stray class.
        out = self._sgr("1;38;2;10;20")
        self.assertEqual(out["cls"], "vtb")
        self.assertEqual(out["style"], "")

    def test_garbage_colour_token_cannot_reach_the_style_string(self):
        # A non-numeric token in the index/RGB position (this is the injection-shaped case: what
        # if the value were somehow attacker-controlled text rather than a validated integer) must
        # be rejected by the digits-only check and produce no colour at all -- never get
        # interpolated into `style` verbatim.
        out = self._sgr('38;5;1" onmouseover="alert(1)')
        self.assertEqual(out["cls"], "")
        self.assertEqual(out["style"], "")

    def test_composes_with_reverse_video(self):
        # Reverse (7) and an extended true-colour foreground both resolve independently: the "vtr"
        # class still appears (CSS's .vtr rule swaps the DEFAULT fg/bg via the `--text`/`--app`
        # tokens) and the true-colour style is emitted alongside it. Inline `style` always wins
        # CSS specificity over any class selector, so this explicit foreground colour overrides
        # .vtr's color swap while background still comes from .vtr -- the same "explicit colour
        # wins its own property, reverse still governs the other" composition the pre-existing
        # 16-colour path already has (an explicit vtf3x class already outranks .vtr's color rule
        # by CSS cascade order within the same specificity) -- this is not a special case in JS.
        out = self._sgr("7;38;2;255;0;0")
        self.assertEqual(out["cls"], "vtr")
        self.assertEqual(out["style"], "color:rgb(255,0,0);")

    # ----- _paintRow: the style actually lands safely in the markup ------------------------

    def test_paint_row_emits_class_and_style_together(self):
        html = self._paint("hi", [[0, 2, "38;5;208"]])
        self.assertEqual(html, '<span style="color:rgb(255,135,0);">hi</span>')

    def test_paint_row_malformed_sequence_never_injects_into_the_markup(self):
        # Same attack-shaped payload as test_garbage_colour_token_cannot_reach_the_style_string,
        # but proven at the _paintRow level: the glyphs are real PTY text ("x") and the SGR
        # portion is attacker-shaped junk -- the produced HTML must contain neither a stray
        # attribute nor any unescaped quote/tag, and the run's own text is still correctly
        # HTML-escaped.
        html = self._paint('x<"\'', [[0, 4, '38;5;1" onmouseover="alert(1)']])
        self.assertNotIn("onmouseover", html)
        self.assertNotIn("<script", html)
        self.assertEqual(html, "x&lt;\"'")   # no span at all: cls and style both came back empty


class TestSgrClassCssCoverage(unittest.TestCase):
    """Structural test: EVERY class string sgrRunClass()/_stdColorClass() can emit for a plain
    16-colour attribute/foreground/background code -- direct SGR params (1/3/4/7 attrs, 30-37/
    90-97 fg, 40-47/100-107 bg) and the 256-colour low-index path (38;5;N/48;5;N for N in 0-15,
    resolved through _stdColorClass onto those SAME class names) -- must have a matching
    `.vtrow .vtXXX` rule in ext_vt.css. A class sgrRunClass can produce with no CSS rule renders
    as an invisible/no-op span: exactly the `vtg100`..`vtg107` (bright 256-colour background) and
    pre-existing `vtg40`/`vtg45`/`vtg46`/`vtg47` (classic background) bug this test class was
    added to catch. Data-driven over the FULL 0-15 index range and the full direct-code ranges,
    not a handful of hand-picked cases -- a future gap anywhere in that space fails this test by
    name, not just the two spans a human happened to think to check.

    100-107 direct (not just 48;5;8..15) are included deliberately: term_vt.py's Screen._sgr
    (confirmed by reading it) stores a raw aixterm bright-background code 100-107 VERBATIM in the
    run's sgr string, so a program that emits `\\x1b[100m` directly takes a different code path
    through sgrRunClass than `\\x1b[48;5;8m` does -- both must resolve to a real class."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_every_emittable_sgr_class_has_a_css_rule(self):
        inputs = ["1", "3", "4", "7"]                              # vtb / vti / vtu / vtr
        for v in list(range(30, 38)) + list(range(90, 98)):        # direct foreground
            inputs.append(str(v))
        for v in list(range(40, 48)) + list(range(100, 108)):      # direct background
            inputs.append(str(v))
        for idx in range(16):                                      # 256-colour low-index path
            inputs.append("38;5;%d" % idx)
            inputs.append("48;5;%d" % idx)

        script = _HARNESS_PRELUDE + _SGR_HELPERS_SRC + """
var out = [];
""" + "\n".join("out.push(sgrRunClass(%s).cls);" % json.dumps(s) for s in inputs) + """
console.log(JSON.stringify({ classes: out }));
"""
        result = _run_node(script)["classes"]
        self.assertEqual(len(result), len(inputs))

        # Every one of these inputs is a real, well-formed SGR param this file must render --
        # an empty `cls` means sgrRunClass silently dropped it (a JS-side gap, not a CSS one).
        empty = [inp for inp, cls in zip(inputs, result) if not cls]
        self.assertEqual(empty, [], "sgrRunClass(...) produced NO class at all for: %s" % empty)

        emitted = set()
        for cls in result:
            emitted.update(c for c in cls.split(" ") if c)

        with open(os.path.join(_WEB, "ext_vt.css"), encoding="utf-8") as fh:
            css = fh.read()
        # SGR run classes are always written as one or more `.vtrow .vtXXX` selectors sharing a
        # rule (e.g. ".vtrow .vtf30, .vtrow .vtf90 { ... }") -- see the comment right above that
        # block in ext_vt.css. Collecting every such class name gives the exact set of classes the
        # stylesheet actually defines, independent of how the rules are grouped.
        defined = set(re.findall(r"\.vtrow \.([A-Za-z0-9]+)", css))

        missing = sorted(emitted - defined)
        self.assertEqual(missing, [],
                          "sgrRunClass()/_stdColorClass() can emit these classes but ext_vt.css "
                          "defines no `.vtrow .<class>` rule for them: %s" % missing)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_256_colour_background_low_index_reuses_the_existing_ansi_class_path(self):
        # The background twin of test_256_colour_low_index_reuses_the_existing_ansi_class_path
        # above, which only ever exercised foreground (38;5;3, 38;5;12) -- never 48;5;N for any N
        # in 0-15, which is exactly why the background gap shipped unnoticed. Covers a classic
        # low index (0), a classic high index that needed a NEW css token (5, 7), the bright
        # boundary (7 -> 8), and a bright high index (15).
        script = _HARNESS_PRELUDE + _SGR_HELPERS_SRC + """
var out = {};
[0, 5, 7, 8, 9, 15].forEach(function (n) {
  out[n] = sgrRunClass("48;5;" + n).cls;
});
console.log(JSON.stringify({ result: out }));
"""
        result = _run_node(script)["result"]
        self.assertEqual(result["0"], "vtg40")     # classic black bg
        self.assertEqual(result["5"], "vtg45")     # classic magenta bg
        self.assertEqual(result["7"], "vtg47")     # classic white bg
        self.assertEqual(result["8"], "vtg100")    # bright black bg (0-7 -> 8-15 boundary)
        self.assertEqual(result["9"], "vtg101")    # bright red bg
        self.assertEqual(result["15"], "vtg107")   # bright white bg
        for n in (0, 5, 7, 8, 9, 15):
            self.assertEqual(_run_node(_HARNESS_PRELUDE + _SGR_HELPERS_SRC + """
console.log(JSON.stringify({ style: sgrRunClass("48;5;" + """ + str(n) + """).style }));
""")["style"], "", "index %d must stay on the class path, not fall through to inline style" % n)


def _xterm_leak_harness(pane_bottom=100, initial_overflow_px=0, has_screen_el=True,
                         term_cols=80, term_rows=24, row_height_px=17, always_overflow=False):
    """Mock infrastructure for XtermTerminal, standing in for the browser globals `_build()`/
    `destroy()` touch: `window.Terminal`/`window.FitAddon.FitAddon` (fake xterm.js), a fake
    `ResizeObserver` global (matching real DOM behaviour: `window.ResizeObserver` is just a
    feature-detection READ of the same global, so this is one constructor, not two independent
    fakes that could silently drift apart), `window.addEventListener`/`removeEventListener` (net
    counting 'resize' registrations), a minimal `document`/`getComputedStyle` for `_xtermTheme()`,
    a controllable `_loadXtermAssets()` (returns a Promise this harness resolves on command,
    simulating the real ~480KB asset fetch staying pending for an arbitrary amount of time), and
    counters for how many real xterm.js Terminal instances were ever constructed/disposed. Every
    counter is a plain running total -- the tests read it directly rather than eyeballing calls.

    Every keyword arg defaults to the exact geometry `TestXtermSwitchDestroyRace` (below) was
    already written against -- a 100px pane with a 100px `.xterm-screen` (zero overflow, i.e.
    `_correctFitOverflow`'s early "fits" return) -- so calling this with no args reproduces the
    prior fixed harness byte-for-byte in behaviour. `TestCorrectFitOverflowExecuted` (further
    below) is what actually exercises the non-default geometry:

    - `initial_overflow_px`: how many px `.xterm-screen`'s measured bottom starts out past the
      pane's content-box bottom (`pane_bottom`). The real, live-measured range was ~1.4px-7.4px
      (see `_correctFitOverflow`'s own header comment in ext_vt.js) -- enough to clip the last
      row's text without `_correctFitOverflow`'s correction.
    - `row_height_px`: how many px the real DomRenderer's `.xterm-screen` shrinks by when
      `term.resize()` removes one row (rows render at a whole device pixel each -- see that same
      comment). The stub's `resize()` subtracts this from the tracked overflow on every call, so a
      correction that removes enough rows genuinely stops overflowing, exactly like the real DOM.
    - `always_overflow`: pins the pathological case where `.xterm-screen` overflows no matter how
      many rows are removed (ignores `row_height_px` entirely) -- for proving the loop's 2-
      iteration bound actually stops it rather than hanging.
    - `has_screen_el`: False reproduces a future xterm.js build changing `.xterm-screen`'s DOM
      shape -- `pane.querySelector('.xterm-screen')` returns null, which `_correctFitOverflow`
      must treat as a safe no-op, not a throw.
    - `term_cols`/`term_rows`: the stub `window.Terminal` instance's starting `cols`/`rows` --
      real fields now (not the prior harness's absent ones), read and written by
      `_correctFitOverflow`'s `term.resize(term.cols, term.rows - 1)` call.
    """
    return """
// Real addEventListener/removeEventListener are keyed on the FUNCTION REFERENCE, not a counter --
// adding the same listener twice is a no-op, and removing one that was never added is *also* a
// no-op (never goes negative). A plain incr/decr counter mock would get this wrong -- e.g.
// destroy()'s own removeEventListener() call is UNCONDITIONAL even when _build() never ran and
// nothing was ever added -- so this models it as a Set instead, exactly like the real DOM.
var __resizeListenerSet = new Set();
var __roInstances = [];          // every ResizeObserver ever constructed, in creation order
var __xtermBuilt = 0;            // how many real (fake) xterm.js Terminal instances were built
var __xtermDisposed = 0;
var __termResizeCalls = [];      // {cols, rows} for every term.resize() call _correctFitOverflow makes
var __postResizeCalls = [];      // {ttyId, cols, rows} for every postResize() call -- i.e. what the
                                  // server actually learns, via term.onResize's registered handler

function ResizeObserver(cb) {
  this._cb = cb;
  this.disconnected = false;
  __roInstances.push(this);
}
ResizeObserver.prototype.observe = function () {};
ResizeObserver.prototype.disconnect = function () { this.disconnected = true; };

var window = {
  ResizeObserver: ResizeObserver,
  addEventListener: function (name, fn) { if (name === 'resize') __resizeListenerSet.add(fn); },
  removeEventListener: function (name, fn) { if (name === 'resize') __resizeListenerSet.delete(fn); },
};
window.Terminal = function (opts) {
  __xtermBuilt++;
  this._opts = opts;
  this.cols = %(term_cols)d;
  this.rows = %(term_rows)d;
  this._onResizeHandlers = [];
};
window.Terminal.prototype.loadAddon = function () {};
window.Terminal.prototype.open = function () {};
window.Terminal.prototype.attachCustomKeyEventHandler = function () {};
window.Terminal.prototype.onData = function () {};
// Real xterm.js: onResize(fn) registers a listener that FIRES synchronously, off resize()'s own
// call, whenever rows/cols actually change -- including a resize the terminal makes to correct
// its own fit (see _build's onResize-before-fit() comment in ext_vt.js). This stub mirrors that
// exactly: resize() below both updates this.cols/this.rows AND calls every registered handler,
// so a correction genuinely reaches postResize() the same synchronous way any other resize does.
window.Terminal.prototype.onResize = function (fn) { this._onResizeHandlers.push(fn); };
window.Terminal.prototype.resize = function (cols, rows) {
  __termResizeCalls.push({ cols: cols, rows: rows });
  this.cols = cols; this.rows = rows;
  if (!__alwaysOverflow) __screenOverflowPx -= %(row_height_px)d;
  this._onResizeHandlers.forEach(function (fn) { fn({ cols: cols, rows: rows }); });
};
window.Terminal.prototype.focus = function () {};
window.Terminal.prototype.hasSelection = function () { return false; };
window.Terminal.prototype.dispose = function () { __xtermDisposed++; };
// Real xterm.js: onBell(fn) is a VS Code-style Emitter subscription -- it returns a Disposable
// (an object with its own .dispose()), NOT a plain unsubscribe function, and calling that
// Disposable's .dispose() removes the listener so a later fireBell() no longer reaches it. This
// stub mirrors both halves exactly, because XtermTerminal._build stores what onBell() returns and
// calls .dispose() on it from destroy() -- a stub that returned a bare function instead would let
// a "disposed" test pass without proving the real Disposable contract holds.
var __bellDisposeCount = 0;
window.Terminal.prototype.onBell = function (fn) {
  this._bellHandlers = this._bellHandlers || [];
  this._bellHandlers.push(fn);
  var handlers = this._bellHandlers, disposed = false;
  return {
    dispose: function () {
      if (disposed) return;
      disposed = true;
      __bellDisposeCount++;
      var i = handlers.indexOf(fn);
      if (i !== -1) handlers.splice(i, 1);
    }
  };
};
// Test-only helper (not part of real xterm.js): fires every STILL-REGISTERED onBell handler, the
// same way the real DomRenderer/InputHandler would when a BEL byte is processed.
window.Terminal.prototype.fireBell = function () {
  (this._bellHandlers || []).slice().forEach(function (fn) { fn(); });
};
function FakeFitAddon() {}
FakeFitAddon.prototype.fit = function () {};
window.FitAddon = { FitAddon: FakeFitAddon };

// Real observePane() (module-scope in ext_vt.js, shared by Terminal and XtermTerminal) lives
// BEFORE _b64ToBytes -- outside _XTERM_LEAK_SRC's slice -- so, like buildToolbar() below, it needs
// its own stand-in here. Mirrors the real implementation exactly (same ResizeObserver construct/
// observe/disconnect shape) so __roInstances/__resizeListenerSet keep counting real (fake)
// instances instead of silently going stale once _build() starts calling through this instead of
// constructing its own ResizeObserver inline.
function observePane(pane, fn) {
  if (!window.ResizeObserver) return function () {};
  var ro = new ResizeObserver(fn);
  ro.observe(pane);
  return function () { ro.disconnect(); };
}

// __alwaysOverflow/__screenOverflowPx drive the fake `.xterm-screen`'s reported geometry -- see
// this function's own docstring above for what each constructor kwarg controls.
var __alwaysOverflow = %(always_overflow_js)s;
var __screenOverflowPx = %(initial_overflow_px)r;

var document = {
  documentElement: {},
  // The real pane XtermTerminal builds is a live DOM node -- xterm.js's DomRenderer appends the
  // real `.xterm-screen` element underneath it, and _correctFitOverflow() (ext_vt.js) reads BOTH
  // the pane's own getBoundingClientRect() and pane.querySelector(".xterm-screen")'s to detect
  // bottom-row clipping (see that method's own header comment). This stub models both: a plausible
  // `.xterm-screen` stand-in with its own getBoundingClientRect(), sized per this call's kwargs
  // (the default geometry fits inside the pane's rect, matching the harness's prior fixed
  // behaviour; TestCorrectFitOverflowExecuted below drives the overflowing variants). Returning a
  // real element here -- not null, unless has_screen_el is False -- means _correctFitOverflow()
  // actually runs its geometry comparison instead of short-circuiting at the "no screen element"
  // guard the way a null stub would.
  createElement: function () {
    var screenEl = %(has_screen_el_js)s ? {
      getBoundingClientRect: function () {
        // Recomputed on every read (not cached at creation) so a term.resize() call in between
        // two _correctFitOverflow loop iterations is actually reflected -- exactly like the real
        // DomRenderer, whose handleResize() sets .xterm-screen's style.height synchronously, off
        // term.resize()'s own call, before _correctFitOverflow ever reads it back again.
        var bottom = __alwaysOverflow ? (%(pane_bottom)r + 999) : (%(pane_bottom)r + __screenOverflowPx);
        return { top: 0, left: 0, right: 200, bottom: bottom, width: 200, height: bottom };
      }
    } : null;
    // classList: a real Set-backed mock (same shape __makeEl's below already uses for the
    // ContextBar/manager-panel harnesses) -- needed because XtermTerminal's own pane is what
    // _flashBellPane (ext_vt.js) toggles "vtbell" on; `addCalls` records every literal class name
    // ever passed to .add(), which the burst-safety test reads to prove the SAME class name is
    // reused every time (never a fresh per-event class that would stack independent animations).
    var __classes = new Set();
    var __classAddCalls = [];
    return {
      className: '',
      classList: {
        add: function (c) { __classAddCalls.push(c); __classes.add(c); },
        remove: function (c) { __classes.delete(c); },
        contains: function (c) { return __classes.has(c); },
        toggle: function (c, force) {
          if (force === undefined) { __classes.has(c) ? __classes.delete(c) : __classes.add(c); }
          else if (force) __classes.add(c); else __classes.delete(c);
        },
        _addCalls: __classAddCalls,
      },
      appendChild: function () {},
      setAttribute: function () {},
      querySelector: function (sel) { return sel === '.xterm-screen' ? screenEl : null; },
      getBoundingClientRect: function () { return { top: 0, left: 0, right: 200, bottom: %(pane_bottom)r, width: 200, height: %(pane_bottom)r }; },
    };
  },
  // XtermTerminal's constructor/destroy add/remove a document-level "themechange" listener (see
  // that class's own comments) -- this harness's buildToolbar() stub below is fully mocked out
  // (no real theme-button listener of its own), so these only need to exist, not track anything.
  addEventListener: function () {},
  removeEventListener: function () {},
};
function getComputedStyle() { return { getPropertyValue: function () { return ''; } }; }

function postKeys() {}
function postResize(ttyId, cols, rows) { __postResizeCalls.push({ ttyId: ttyId, cols: cols, rows: rows }); }
// EventSource: `close()` plus the named-event listener API. XtermTerminal._openStream subscribes
// to `/api/term/raw`'s `event: notice` frames with addEventListener("notice", ...) and
// _closeStream removes that listener by reference -- a stub without both halves could not tell a
// real teardown from a no-op. `__emit`/`__listenerCount` are TEST-ONLY (not part of the real
// EventSource API): the former dispatches a named event exactly like the browser would, with the
// raw `data` string the server put on the wire; the latter is how a leak test reads the truth.
function EventSource(url) { this.url = url; this.closed = false; this._listeners = {}; }
EventSource.prototype.close = function () { this.closed = true; };
EventSource.prototype.addEventListener = function (name, fn) {
  (this._listeners[name] = this._listeners[name] || []).push(fn);
};
EventSource.prototype.removeEventListener = function (name, fn) {
  var a = this._listeners[name] || [];
  var i = a.indexOf(fn);
  if (i !== -1) a.splice(i, 1);
};
EventSource.prototype.__emit = function (name, data) {
  (this._listeners[name] || []).slice().forEach(function (fn) { fn({ data: data }); });
};
EventSource.prototype.__listenerCount = function (name) { return (this._listeners[name] || []).length; };

function debounce(fn) { return fn; }   // real debounce timing is not what this module tests

var _noopRendererSwitch = { getActive: function () { return 'grid'; }, switchTo: function () {} };
function buildToolbar() { return { refreshMouseToggle: function () {} }; }

function makeContainer() {
  return { innerHTML: '', appendChild: function () {} };
}

// Controllable stand-in for the real _loadXtermAssets(): each call returns a NEW pending Promise
// and stashes its resolver, so the test decides exactly when (and whether) that call's asset
// "finishes loading" -- this is what lets a test put attach() into the exact pending state the
// reviewer's repro needs, hold it there across a destroy(), and only then let it resolve.
var __assetLoadResolvers = [];
function _loadXtermAssets() {
  return new Promise(function (resolve) { __assetLoadResolvers.push(resolve); });
}
function resolveNextAssetLoad() {
  var r = __assetLoadResolvers.shift();
  if (r) r();
}
""" % {
        "pane_bottom": pane_bottom,
        "initial_overflow_px": initial_overflow_px,
        "has_screen_el_js": json.dumps(bool(has_screen_el)),
        "term_cols": term_cols,
        "term_rows": term_rows,
        "row_height_px": row_height_px,
        "always_overflow_js": json.dumps(bool(always_overflow)),
    }


class TestXtermSwitchDestroyRace(unittest.TestCase):
    """DEFECT 1, executed: the reviewer's exact repro. `XtermTerminal.prototype.attach` defers
    everything (the real `this.term`, the `observePane()`-backed `this._disposePaneObserver`
    ResizeObserver, and the `window` resize listener)
    behind `_loadXtermAssets()`'s promise; `destroy()` called while that promise is still pending
    used to complete as a clean no-op (nothing was built yet to tear down) and then the deferred
    `_build()` fired anyway -- ON the already-destroyed instance -- building a real xterm.js
    Terminal (never disposed), a ResizeObserver on a detached pane (never disconnected), and
    re-adding the window resize listener AFTER destroy() had already tried to remove it. Fixed by
    the `_destroyed` flag set in destroy() and checked at the top of `_build()` (mirroring
    ContextBar._destroyed). Proven RED against the pre-fix code by hand: temporarily reverted the
    `_destroyed` guard (the constructor's `this._destroyed = false;`, `_build`'s early-return
    check, and destroy()'s `this._destroyed = true;`) back to the original code, reran this exact
    test, and confirmed it fails with the same leak the reviewer measured, before restoring the
    fix."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_during_pending_asset_load_leaks_nothing(self):
        script = _HARNESS_PRELUDE + _xterm_leak_harness() + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty1');
  term.attach();      // starts the (pending, controllable) asset load
  term.destroy();     // destroy() BEFORE that load ever resolves -- the exact race
  resolveNextAssetLoad();   // now let the deferred _build() fire, if it still would
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    termSetOnDestroyed: term.term !== null,
    roSetOnDestroyed: !!term._disposePaneObserver,   // see _disposePaneObserver comment in
                                                       // test_normal_path_build_then_destroy_cleans_up_everything
    liveResizeListeners: __resizeListenerSet.size,
    liveResizeObservers: __roInstances.filter(function (r) { return !r.disconnected; }).length,
    xtermInstancesBuilt: __xtermBuilt,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertFalse(result["termSetOnDestroyed"], "term.term must stay null on a destroyed instance")
        self.assertFalse(result["roSetOnDestroyed"], "term._disposePaneObserver must stay null on a destroyed instance")
        self.assertEqual(result["liveResizeListeners"], 0, "no window resize listener may survive")
        self.assertEqual(result["liveResizeObservers"], 0, "no live ResizeObserver may survive")
        self.assertEqual(
            result["xtermInstancesBuilt"], 0,
            "_build() must bail out before ever constructing a real xterm.js Terminal",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_repeated_switches_do_not_leak_cumulatively(self):
        # The exact real-world shape: an impatient user taps the switch button repeatedly before
        # each load finishes. Ten repetitions of attach()-then-destroy()-then-resolve, asserting
        # the leak counters stay at their post-fix value of zero EVERY time, not just once --
        # catching a fix that clears state once but still accumulates across repeats.
        script = _HARNESS_PRELUDE + _xterm_leak_harness() + _XTERM_LEAK_SRC + """
async function main() {
  var snapshots = [];
  for (var i = 0; i < 10; i++) {
    var container = makeContainer();
    var term = new XtermTerminal(container, 'tty-repeat-' + i);
    term.attach();
    term.destroy();
    resolveNextAssetLoad();
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    snapshots.push({
      liveResizeListeners: __resizeListenerSet.size,
      liveResizeObservers: __roInstances.filter(function (r) { return !r.disconnected; }).length,
      xtermInstancesBuilt: __xtermBuilt,
    });
  }
  console.log(JSON.stringify({ snapshots: snapshots }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        for i, snap in enumerate(result["snapshots"]):
            self.assertEqual(snap["liveResizeListeners"], 0, "repetition %d leaked a resize listener" % i)
            self.assertEqual(snap["liveResizeObservers"], 0, "repetition %d leaked a live ResizeObserver" % i)
            self.assertEqual(snap["xtermInstancesBuilt"], 0, "repetition %d built a real xterm.js instance" % i)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_normal_path_build_then_destroy_cleans_up_everything(self):
        # The non-racing path: attach() resolves BEFORE destroy() -- _build() runs for real, and
        # destroy() must then actually dispose the xterm.js terminal, disconnect the
        # ResizeObserver, and remove the window listener (not just skip re-leaking them).
        script = _HARNESS_PRELUDE + _xterm_leak_harness() + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-normal');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  var afterBuild = {
    termIsSet: term.term !== null,
    // _ro was the pre-observePane-refactor field name (see TestObservePaneSharedResizeHelper in
    // test_term_vt_client.py: "replacing xterm's old bespoke `this._ro` wiring") -- XtermTerminal
    // now stores observePane()'s dispose closure on `_disposePaneObserver` instead.
    roIsSet: !!term._disposePaneObserver,
    liveResizeListeners: __resizeListenerSet.size,
    liveResizeObservers: __roInstances.filter(function (r) { return !r.disconnected; }).length,
    xtermInstancesBuilt: __xtermBuilt,
  };

  term.destroy();

  console.log(JSON.stringify({
    afterBuild: afterBuild,
    termAfterDestroy: term.term,
    roAfterDestroy: term._disposePaneObserver,
    liveResizeListenersAfterDestroy: __resizeListenerSet.size,
    liveResizeObserversAfterDestroy: __roInstances.filter(function (r) { return !r.disconnected; }).length,
    xtermInstancesDisposed: __xtermDisposed,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        before = result["afterBuild"]
        self.assertTrue(before["termIsSet"], "sanity: _build() must actually run on the normal path")
        self.assertTrue(before["roIsSet"])
        self.assertEqual(before["liveResizeListeners"], 1)
        self.assertEqual(before["liveResizeObservers"], 1)
        self.assertEqual(before["xtermInstancesBuilt"], 1)

        self.assertIsNone(result["termAfterDestroy"], "destroy() must dispose and clear this.term")
        self.assertIsNone(result["roAfterDestroy"], "destroy() must disconnect and clear this._disposePaneObserver")
        self.assertEqual(result["liveResizeListenersAfterDestroy"], 0, "destroy() must remove the window listener")
        self.assertEqual(result["liveResizeObserversAfterDestroy"], 0, "destroy() must disconnect the ResizeObserver")
        self.assertEqual(result["xtermInstancesDisposed"], 1, "destroy() must dispose() the xterm.js terminal")


class TestCorrectFitOverflowExecuted(unittest.TestCase):
    """`XtermTerminal.prototype._correctFitOverflow` (ext_vt.js), executed: an adversarial review
    found this method -- the headline fix of this change, which stops the terminal's bottom row
    being clipped -- shipped with ZERO coverage of its corrective branch. The pre-existing
    `_xterm_leak_harness()` always measured a `.xterm-screen` that exactly fit its pane (bottom:100
    vs. bottom:100), so `_correctFitOverflow` only ever took its "fits, nothing to do" early
    return; its stub `window.Terminal.prototype` also defined no `.resize()`/`.cols`/`.rows`, so
    the corrective branch (`term.resize(term.cols, term.rows - 1)`) would have thrown a TypeError
    had it ever been reached.

    `_xterm_leak_harness()` now takes geometry/behaviour kwargs (see that function's own
    docstring) that make the corrective branch, the postResize/server-desync path it exists to
    prevent, the 2-iteration bound, and both defensive guards all genuinely reachable and
    assertable -- while its zero-argument call (used throughout `TestXtermSwitchDestroyRace`
    above) reproduces the prior fixed "fits" geometry byte-for-byte."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_overflowing_screen_triggers_exactly_one_corrective_resize(self):
        # Realistic measured overflow (see _correctFitOverflow's own header comment in ext_vt.js:
        # "the mismatch reached +1.4px" up to the ~7.4px this test uses) with rows rendering at
        # exactly 17px each -- one row removed (7.4 - 17 = -9.6, well past the 0.5px fits
        # threshold) is enough to bring `.xterm-screen` back inside the pane, so the loop must
        # correct exactly once and then stop on its own "fits" check, not run out the 2-iteration
        # bound.
        script = _HARNESS_PRELUDE + _xterm_leak_harness(
            initial_overflow_px=7.4, row_height_px=17, term_cols=80, term_rows=24,
        ) + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-overflow');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    resizeCalls: __termResizeCalls,
    finalRows: term.term.rows,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["resizeCalls"], [{"cols": 80, "rows": 23}],
            "an overflowing .xterm-screen must be corrected by exactly one term.resize() call to "
            "cols, rows-1",
        )
        self.assertEqual(result["finalRows"], 23)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_correction_posts_the_corrected_row_count_not_the_pre_correction_one(self):
        # The desync bug class this whole fix exists to prevent: term.onResize is registered
        # BEFORE the first fit() specifically so that any _correctFitOverflow() correction it
        # triggers also reaches postResize() -> POST /api/term/resize (see _build's own comment in
        # ext_vt.js). If the server only ever learned the PRE-correction row count (24), its PTY
        # would stay sized for a row the browser is no longer actually rendering.
        script = _HARNESS_PRELUDE + _xterm_leak_harness(
            initial_overflow_px=7.4, row_height_px=17, term_cols=80, term_rows=24,
        ) + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-post-resize');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({ postResizeCalls: __postResizeCalls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["postResizeCalls"], [{"ttyId": "tty-post-resize", "cols": 80, "rows": 23}],
            "the server must learn the CORRECTED row count (23), not the pre-correction one (24) "
            "-- that mismatch is exactly the client/server desync this fix exists to prevent",
        )

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_a_screen_that_already_fits_triggers_no_correction(self):
        # Guards against an over-eager fix that shrinks a row every time regardless of whether one
        # is actually needed, which would permanently waste a row on every terminal. Uses the
        # harness's DEFAULT geometry (zero overflow) -- the same "fits" case
        # TestXtermSwitchDestroyRace already relies on above.
        script = _HARNESS_PRELUDE + _xterm_leak_harness() + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-fits');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    resizeCalls: __termResizeCalls,
    postResizeCalls: __postResizeCalls,
    finalRows: term.term.rows,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["resizeCalls"], [], "a screen that already fits must never be resized")
        self.assertEqual(result["postResizeCalls"], [], "no correction means no extra resize POST")
        self.assertEqual(result["finalRows"], 24)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_a_pathologically_always_overflowing_screen_is_bounded_to_two_corrections(self):
        # Constructs a screen that overflows NO MATTER how many rows are removed (always_overflow
        # ignores row_height_px entirely -- see the harness's own docstring) to prove the loop's
        # documented 2-iteration bound is what actually stops it, not the "fits" check -- i.e. it
        # neither hangs nor keeps shrinking indefinitely. (`_run_node`'s own 30s subprocess timeout
        # is a second, independent backstop against an actual hang.)
        script = _HARNESS_PRELUDE + _xterm_leak_harness(
            always_overflow=True, term_cols=80, term_rows=24,
        ) + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-always-overflow');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    resizeCalls: __termResizeCalls,
    finalRows: term.term.rows,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(
            result["resizeCalls"], [{"cols": 80, "rows": 23}, {"cols": 80, "rows": 22}],
            "a screen that never fits must still stop after exactly 2 corrective resizes, not "
            "hang or keep shrinking indefinitely",
        )
        self.assertEqual(result["finalRows"], 22)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_rows_at_one_is_never_shrunk_to_zero_or_negative(self):
        # `if (term.rows <= 1) return;` -- a legitimate defensive guard in the source, pinned here.
        # Paired with a large overflow (50px) so the ONLY thing stopping a resize is this guard,
        # not the geometry happening to already fit.
        script = _HARNESS_PRELUDE + _xterm_leak_harness(
            initial_overflow_px=50, term_rows=1,
        ) + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-one-row');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    resizeCalls: __termResizeCalls,
    finalRows: term.term.rows,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["resizeCalls"], [], "a 1-row terminal must never be resized smaller")
        self.assertEqual(result["finalRows"], 1)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_missing_xterm_screen_node_returns_safely_without_throwing(self):
        # `pane.querySelector(".xterm-screen")` returning null -- e.g. a future xterm.js build that
        # changed its DOM shape -- must be a safe no-op (per the source's own comment: "fail safe,
        # no-op"), not a throw. A throw here would propagate out of _build() (the node harness would
        # exit non-zero / _run_node would raise), so this test's own success is part of the proof.
        script = _HARNESS_PRELUDE + _xterm_leak_harness(
            has_screen_el=False, initial_overflow_px=50,
        ) + _XTERM_LEAK_SRC + """
async function main() {
  var container = makeContainer();
  var term = new XtermTerminal(container, 'tty-no-screen-el');
  term.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  console.log(JSON.stringify({
    resizeCalls: __termResizeCalls,
    finalRows: term.term.rows,
    built: __xtermBuilt,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["resizeCalls"], [], "no .xterm-screen node means no correction can be computed")
        self.assertEqual(result["finalRows"], 24, "rows must be left untouched")
        self.assertEqual(result["built"], 1, "sanity: _build() itself must have completed, not thrown")


# ===== ContextBar: executed behaviour, replacing the grep-only assertions this task's brief =====
# flagged in tests/test_term_vt_client.py (TestContextBarModelSwitcher/EffortSwitcher's inject/
# toast/focus-safety methods, all of TestContextBarAttachGating, and
# TestContextBarDocksToBottomOfBothMounts's destroy-teardown method -- see that file for exactly
# which methods were removed and why). Mirrors `_xterm_leak_harness()`'s own style: a stub
# `document`, a stub network layer (here `fetch` -- XtermTerminal has no fetch of its own, so that
# harness didn't need one), and recorded calls the tests assert on directly, rather than grepping
# ext_vt.js's source text for the right substrings.

_CONTEXT_BAR_MOCKS = """
// fetch() is a small router keyed on URL prefix, backed by a per-endpoint QUEUE the test pushes
// canned {status, json, badJson, reject} responses onto -- draining left-to-right, one queue
// entry per call, except a queue with exactly one entry left repeats it forever (so a test that
// only cares about the FIRST response can leave the queue at length 1 and every later poll still
// gets something sane). This is what lets a test drive a real true -> false -> true sequence
// across three separate polls of the SAME endpoint.
var __fetchCalls = [];
var __toastCalls = [];
var __sessionQueue = [{ json: {} }];
var __attachedQueue = [{ json: { claude_attached: false } }];
var __injectQueue = [{ json: { ok: true } }];

function __nextFrom(queue) {
  return queue.length > 1 ? queue.shift() : queue[0];
}

function __makeResponse(status, jsonBody, jsonFails) {
  return {
    ok: status >= 200 && status < 300,
    status: status,
    json: function () {
      return jsonFails ? Promise.reject(new Error('invalid json')) : Promise.resolve(jsonBody);
    },
  };
}

function fetch(url, opts) {
  __fetchCalls.push({ url: url, opts: opts });
  var queue = null;
  if (url.indexOf('/api/session') === 0) queue = __sessionQueue;
  else if (url.indexOf('/api/term/attached') === 0) queue = __attachedQueue;
  else if (url.indexOf('/api/term/inject') === 0) queue = __injectQueue;
  if (!queue) return Promise.resolve(__makeResponse(200, {}));
  var b = __nextFrom(queue);
  if (b.reject) return Promise.reject(new Error(b.rejectMsg || 'simulated network failure'));
  return Promise.resolve(__makeResponse(b.status === undefined ? 200 : b.status, b.json, !!b.badJson));
}

function toast(title, msg) { __toastCalls.push({ title: title, msg: msg }); }

// A controllable setInterval: ContextBar.prototype.start calls this exactly ONCE and stashes the
// tick function -- the test then invokes __tick() by hand instead of waiting on a real 2000ms
// timer, exactly like _xterm_leak_harness's own manually-driven ResizeObserver/asset-load
// stand-ins do for XtermTerminal.
var __setIntervalCallCount = 0;
var __intervalFn = null;
var __intervalCleared = false;
function setInterval(fn, ms) {
  __setIntervalCallCount++;
  __intervalFn = fn;
  return 1;
}
function clearInterval(id) { __intervalCleared = true; __intervalFn = null; }
function __tick() { if (__intervalFn) __intervalFn(); }

// Drains the microtask queue: every fetch() above resolves SYNCHRONOUSLY (Promise.resolve, no
// real I/O), so any depth of .then()/.catch() chaining off of it fully settles before Node's
// event loop ever reaches a macrotask -- one hop through a real setTimeout is enough to prove
// "the chain is done"; this loops a few times purely for safety margin.
function __flush(n) {
  var p = Promise.resolve();
  for (var i = 0; i < (n || 4); i++) {
    p = p.then(function () { return new Promise(function (r) { setTimeout(r, 0); }); });
  }
  return p;
}

// ===== minimal fake DOM: just enough for ContextBar's own document.createElement/addEventListener
// calls -- classList, innerHTML, textContent, appendChild/removeChild, a `.dispatch(type, ev)`
// helper the tests use to drive REAL listeners registered via REAL addEventListener calls (never
// calling a `_pick*`/`_open*Dropdown` method directly to simulate a click), and `.contains()` for
// the outside-click-closes-dropdown wiring. =====
function __makeEl(tag) {
  var listeners = {};
  var classes = new Set();
  var el = {
    tagName: tag, className: '', style: {}, textContent: '', title: '', innerHTML: '',
    children: [], parentNode: null, _attrs: {},
    appendChild: function (child) { child.parentNode = el; el.children.push(child); return child; },
    removeChild: function (child) {
      var i = el.children.indexOf(child);
      if (i !== -1) el.children.splice(i, 1);
      child.parentNode = null;
    },
    setAttribute: function (k, v) { el._attrs[k] = String(v); },
    getAttribute: function (k) { return el._attrs.hasOwnProperty(k) ? el._attrs[k] : null; },
    addEventListener: function (type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener: function (type, fn) {
      var arr = listeners[type] || [];
      var i = arr.indexOf(fn);
      if (i !== -1) arr.splice(i, 1);
    },
    dispatch: function (type, ev) {
      ev = ev || {};
      if (ev.target === undefined) ev.target = el;
      (listeners[type] || []).slice().forEach(function (fn) { fn(ev); });
    },
    contains: function (node) {
      while (node) { if (node === el) return true; node = node.parentNode; }
      return false;
    },
    querySelectorAll: function () { return []; },
  };
  el.classList = {
    add: function (c) { classes.add(c); },
    remove: function (c) { classes.delete(c); },
    toggle: function (c, force) {
      if (force === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); }
      else if (force) classes.add(c); else classes.delete(c);
    },
    contains: function (c) { return classes.has(c); },
  };
  return el;
}

var document = {
  createElement: function (tag) { return __makeEl(tag); },
  _listeners: {},
  addEventListener: function (type, fn) { (document._listeners[type] = document._listeners[type] || []).push(fn); },
  removeEventListener: function (type, fn) {
    var arr = document._listeners[type] || [];
    var i = arr.indexOf(fn);
    if (i !== -1) arr.splice(i, 1);
  },
};
var window = {};   // esc's own `window.esc ||` fallback (its extracted line, below) needs this global

function fakeEvent(overrides) {
  var ev = { stopPropagation: function () {}, preventDefault: function () {} };
  for (var k in (overrides || {})) ev[k] = overrides[k];
  return ev;
}
"""


class TestContextBarAttachToggle(unittest.TestCase):
    """Task 1, executed: the switchers' visibility is a REACTIVE answer driven by real polls of
    GET /api/term/attached, not just the first one. Drives the real `ContextBar.prototype.start`
    and manually advances the SAME stored tick function across three separate polls, proving the
    switchers container's real `style.display` actually flips true -> false -> true -- the
    grep-only version this replaces could only confirm the right URL strings and call shape
    appeared in the source, which stays true even if `_setAttached` were a no-op.

    PROVEN REAL (see the task report for the full RED transcript): temporarily reverting
    `ContextBar.prototype._setAttached` to a no-op in aitracker/web/ext_vt.js (via a `cp` backup,
    never git) made `test_attach_state_reacts_across_successive_polls` fail before the file was
    restored."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_attach_state_reacts_across_successive_polls(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  __attachedQueue = [
    { json: { claude_attached: true } },
    { json: { claude_attached: false } },
    { json: { claude_attached: true } },
  ];
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  bar.start();
  await __flush();
  var afterFirst = bar.switchersEl.style.display;

  __tick();
  await __flush();
  var afterSecond = bar.switchersEl.style.display;

  __tick();
  await __flush();
  var afterThird = bar.switchersEl.style.display;

  console.log(JSON.stringify({
    afterFirst: afterFirst, afterSecond: afterSecond, afterThird: afterThird,
    setIntervalCalls: __setIntervalCallCount,
    sessionCalls: __fetchCalls.filter(function (c) { return c.url.indexOf('/api/session') === 0; }).length,
    attachedCalls: __fetchCalls.filter(function (c) { return c.url.indexOf('/api/term/attached') === 0; }).length,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["afterFirst"], "", "attached:true must show the switchers")
        self.assertEqual(result["afterSecond"], "none", "attached:false must hide them again")
        self.assertEqual(result["afterThird"], "", "attached:true must show them a third time -- reactive, not latched")
        # one timer drives both fetches out of ONE tick(), not two independent timers/polls.
        self.assertEqual(result["setIntervalCalls"], 1)
        self.assertEqual(result["sessionCalls"], 3)
        self.assertEqual(result["attachedCalls"], 3)


class TestContextBarFailClosed(unittest.TestCase):
    """Task 2, executed: a 404, a non-JSON body, and a rejected fetch on GET /api/term/attached
    must each flip an already-attached bar back to not-attached. This is a safety property -- the
    task's own framing is that typing a slash command into a plain bash prompt is the harm a stale
    "attached" answer would cause -- so all three failure SHAPES are pinned separately rather than
    trusting one to stand in for the others.

    PROVEN REAL: temporarily changing the `.catch` branch in `ContextBar.prototype.start` to call
    `self._setAttached(true)` instead of `false` (a plausible-looking but wrong "fail open"
    mistake, via a `cp` backup, never git) made all three of these go RED before the file was
    restored -- see the task report."""

    def _run(self, attached_queue):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  __attachedQueue = %s;
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  bar.start();
  await __flush();
  var afterFirst = { attached: bar.attached, display: bar.switchersEl.style.display };
  __tick();
  await __flush();
  var afterSecond = { attached: bar.attached, display: bar.switchersEl.style.display };
  console.log(JSON.stringify({ afterFirst: afterFirst, afterSecond: afterSecond }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""" % json.dumps(attached_queue)
        return _run_node(script)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_404_flips_to_not_attached(self):
        result = self._run([{"json": {"claude_attached": True}}, {"status": 404, "json": {}}])
        self.assertTrue(result["afterFirst"]["attached"])
        self.assertFalse(result["afterSecond"]["attached"])
        self.assertEqual(result["afterSecond"]["display"], "none")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_non_json_body_flips_to_not_attached(self):
        result = self._run([{"json": {"claude_attached": True}}, {"json": None, "badJson": True}])
        self.assertTrue(result["afterFirst"]["attached"])
        self.assertFalse(result["afterSecond"]["attached"])
        self.assertEqual(result["afterSecond"]["display"], "none")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_rejected_fetch_flips_to_not_attached(self):
        result = self._run([{"json": {"claude_attached": True}}, {"reject": True}])
        self.assertTrue(result["afterFirst"]["attached"])
        self.assertFalse(result["afterSecond"]["attached"])
        self.assertEqual(result["afterSecond"]["display"], "none")


class TestContextBarVisibility(unittest.TestCase):
    """Task 3, executed: the bar's own `.el.style.display` must follow `attached || hasUsage`
    exactly. Driven by calling the real `_setAttached`/`_renderReadout` methods directly (no
    fetch/poll needed to prove this rule -- it's pure state -> display logic, not a network
    concern), covering all three combinations the task names: not-attached+no-usage (hidden),
    not-attached+usage (visible), attached+no-usage (visible)."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_visibility_follows_attached_or_has_usage(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  var results = {};
  results.initial = bar.el.style.display;               // not attached, no usage -> hidden

  bar._renderReadout({ current: 100, limit: null, pct: null }, 0);
  results.notAttachedWithUsage = bar.el.style.display;   // not attached, HAS usage -> visible

  bar._renderReadout(null, 0);
  results.backToNothing = bar.el.style.display;          // usage cleared again -> hidden

  bar._setAttached(true);
  results.attachedNoUsage = bar.el.style.display;        // attached, no usage -> visible

  bar._setAttached(false);
  results.neitherAgain = bar.el.style.display;           // back to neither -> hidden

  console.log(JSON.stringify(results));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["initial"], "none")
        self.assertEqual(result["notAttachedWithUsage"], "")
        self.assertEqual(result["backToNothing"], "none")
        self.assertEqual(result["attachedNoUsage"], "")
        self.assertEqual(result["neitherAgain"], "none")


class TestContextBarInjectContract(unittest.TestCase):
    """Task 4, executed: picking a model or an effort from the REAL dropdown -- a real click on
    the real button opens it, a real click on a real dropdown item picks it, both dispatched
    through listeners registered via real `addEventListener` calls, never a direct
    `_pickModel`/`_pickEffort` call standing in for the click -- must send exactly the documented
    POST /api/term/inject body. This is what actually types the slash command into the CLI; a
    wrong body silently sends nothing useful.

    PROVEN REAL: temporarily dropping `clear_first: true` from `ContextBar.prototype._pickModel`'s
    request body (via a `cp` backup, never git) made
    `test_model_pick_drives_the_dropdown_and_sends_the_inject_contract` go RED before the file was
    restored -- see the task report."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_model_pick_drives_the_dropdown_and_sends_the_inject_contract(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty42', 'cwd', function () { return null; });
  bar._setAttached(true);

  bar.modelBtn.dispatch('click', fakeEvent());
  var openedAfterClick = bar.modelDropdownOpen;

  var item = null;
  for (var i = 0; i < bar.modelDd.children.length; i++) {
    if (bar.modelDd.children[i].getAttribute('data-model') === 'opus') item = bar.modelDd.children[i];
  }
  bar.modelDd.dispatch('click', fakeEvent({ target: item }));
  await __flush();

  var closedAfterPick = bar.modelDropdownOpen;
  var call = __fetchCalls[__fetchCalls.length - 1];
  console.log(JSON.stringify({
    openedAfterClick: openedAfterClick,
    closedAfterPick: closedAfterPick,
    url: call.url,
    method: call.opts.method,
    body: JSON.parse(call.opts.body),
    toasts: __toastCalls,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertTrue(result["openedAfterClick"])
        self.assertFalse(result["closedAfterPick"], "picking must close the dropdown again")
        self.assertEqual(result["url"], "/api/term/inject")
        self.assertEqual(result["method"], "POST")
        self.assertEqual(result["body"], {
            "tty": "tty42", "text": "/model opus", "submit": True, "clear_first": True,
        })
        self.assertEqual(result["toasts"], [], "a successful inject must not surface a toast")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_effort_pick_drives_the_dropdown_and_sends_the_inject_contract(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty42', 'cwd', function () { return null; });
  bar._setAttached(true);

  bar.effortBtn.dispatch('click', fakeEvent());
  var openedAfterClick = bar.effortDropdownOpen;

  var item = null;
  for (var i = 0; i < bar.effortDd.children.length; i++) {
    if (bar.effortDd.children[i].getAttribute('data-effort') === 'xhigh') item = bar.effortDd.children[i];
  }
  bar.effortDd.dispatch('click', fakeEvent({ target: item }));
  await __flush();

  var closedAfterPick = bar.effortDropdownOpen;
  var call = __fetchCalls[__fetchCalls.length - 1];
  console.log(JSON.stringify({
    openedAfterClick: openedAfterClick,
    closedAfterPick: closedAfterPick,
    url: call.url,
    method: call.opts.method,
    body: JSON.parse(call.opts.body),
    toasts: __toastCalls,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertTrue(result["openedAfterClick"])
        self.assertFalse(result["closedAfterPick"], "picking must close the dropdown again")
        self.assertEqual(result["url"], "/api/term/inject")
        self.assertEqual(result["method"], "POST")
        self.assertEqual(result["body"], {
            "tty": "tty42", "text": "/effort xhigh", "submit": True, "clear_first": True,
        })
        self.assertEqual(result["toasts"], [], "a successful inject must not surface a toast")


class TestContextBarInjectFailureToast(unittest.TestCase):
    """Task 5, executed: an inject POST that comes back 404, or one whose fetch() itself rejects
    (server unreachable), must surface a toast rather than fail silently -- the user has no other
    signal that "/model opus" never reached the CLI."""

    def _pick_model_and_capture_toasts(self, inject_queue):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  __injectQueue = %s;
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  bar._pickModel('opus');
  await __flush();
  console.log(JSON.stringify({ toasts: __toastCalls }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""" % json.dumps(inject_queue)
        return _run_node(script)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_404_response_surfaces_a_toast(self):
        result = self._pick_model_and_capture_toasts([{"status": 404, "json": {}}])
        self.assertEqual(len(result["toasts"]), 1)
        self.assertIn("model", result["toasts"][0]["title"].lower())

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_rejected_fetch_surfaces_a_toast(self):
        result = self._pick_model_and_capture_toasts([{"reject": True}])
        self.assertEqual(len(result["toasts"]), 1)
        self.assertIn("reach", result["toasts"][0]["title"].lower())


class TestContextBarFocusSafety(unittest.TestCase):
    """Task 6, executed: mousedown on either button or either dropdown must call
    `ev.preventDefault()` -- a real DOM `<button>`/click target takes native focus on mousedown,
    and stealing focus from the terminal's own capture textarea breaks typing while a dropdown is
    open. Driven with a real fake mousedown event whose `preventDefault` is a recording function,
    dispatched through the REAL listener registered via the REAL `addEventListener` call in the
    constructor -- not a source-text check for the literal `ev.preventDefault()` call."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_all_four_mousedown_targets_prevent_default(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  var results = {};
  ['modelBtn', 'effortBtn', 'modelDd', 'effortDd'].forEach(function (name) {
    var calls = 0;
    bar[name].dispatch('mousedown', { preventDefault: function () { calls++; } });
    results[name] = calls;
  });
  console.log(JSON.stringify(results));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        for name in ("modelBtn", "effortBtn", "modelDd", "effortDd"):
            self.assertEqual(result[name], 1, "%s's mousedown handler must call preventDefault()" % name)


class TestContextBarEffortLabel(unittest.TestCase):
    """Task 7, executed: `ContextBar.prototype._applySessionData`'s real handling of
    `meta.effort` -- labelled when present, falls back to "effort ▾" when absent, and survives an
    unrecognised value (a future CLI tier) without throwing, rendering it as-is and marking no
    dropdown item current."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_effort_label_present_absent_and_unrecognized(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  var results = {};

  bar._applySessionData({ meta: { effort: 'high' }, tokens: { in: 0, out: 0 } });
  results.withEffort = bar.effortBtn.textContent;
  bar._openEffortDropdown();
  var highCur = false;
  for (var i = 0; i < bar.effortDd.children.length; i++) {
    if (bar.effortDd.children[i].getAttribute('data-effort') === 'high') {
      highCur = bar.effortDd.children[i].classList.contains('cur');
    }
  }
  results.highMarkedCurrent = highCur;
  bar._closeEffortDropdown();

  bar._applySessionData({ meta: {}, tokens: { in: 0, out: 0 } });
  results.withoutEffort = bar.effortBtn.textContent;

  var threw = false;
  try {
    bar._applySessionData({ meta: { effort: 'banana' }, tokens: { in: 0, out: 0 } });
  } catch (e) { threw = true; }
  results.threwOnUnrecognized = threw;
  results.unrecognizedLabel = bar.effortBtn.textContent;

  bar._openEffortDropdown();
  var anyCurrent = false;
  for (var j = 0; j < bar.effortDd.children.length; j++) {
    if (bar.effortDd.children[j].classList.contains('cur')) anyCurrent = true;
  }
  results.anyItemMarkedCurrentForUnrecognized = anyCurrent;

  console.log(JSON.stringify(results));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertEqual(result["withEffort"], "high ▾")
        self.assertTrue(result["highMarkedCurrent"], "a recognised effort must mark its own dropdown item current")
        self.assertEqual(result["withoutEffort"], "effort ▾")
        self.assertFalse(result["threwOnUnrecognized"])
        self.assertEqual(result["unrecognizedLabel"], "banana ▾")
        self.assertFalse(result["anyItemMarkedCurrentForUnrecognized"])


class TestContextBarTeardown(unittest.TestCase):
    """Task 8, executed: `destroy()` must actually stop the poll -- the stored tick function,
    invoked directly (bypassing this harness's own `clearInterval` bookkeeping so the REAL
    `_destroyed` guard is what's on trial, not this test's mock) -- must no-op, and `destroy()`
    must actually remove the document-level click listener. A leaked 2s poll per closed terminal
    is a real resource leak, the exact thing the task calls out by name.

    PROVEN REAL: temporarily deleting the `if (self._destroyed) return;` guard at the top of
    `tick()` inside `ContextBar.prototype.start` (via a `cp` backup, never git) made this go RED
    -- fetches kept happening after destroy() -- before the file was restored; see the task
    report."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_stops_polling_and_removes_the_doc_listener(self):
        script = _HARNESS_PRELUDE + _CONTEXT_BAR_MOCKS + _ESC_SRC + _CONTEXT_BAR_HELPERS_SRC + _CONTEXT_BAR_SRC + """
async function main() {
  var container = document.createElement('div');
  var bar = new ContextBar(container, 'sid1', 'tty1', 'cwd', function () { return null; });
  bar.start();
  await __flush();
  var callsBeforeDestroy = __fetchCalls.length;
  var savedTick = __intervalFn;              // captured BEFORE destroy -- see class docstring
  var onDocClickRef = bar._onDocClick;
  var listenerPresentBefore = (document._listeners['click'] || []).indexOf(onDocClickRef) !== -1;

  bar.destroy();

  savedTick();                               // simulate a timer firing that our own
                                              // clearInterval stub failed to cancel
  await __flush();
  var callsAfterDestroy = __fetchCalls.length;
  var listenerPresentAfter = (document._listeners['click'] || []).indexOf(onDocClickRef) !== -1;

  console.log(JSON.stringify({
    callsBeforeDestroy: callsBeforeDestroy,
    callsAfterDestroy: callsAfterDestroy,
    intervalCleared: __intervalCleared,
    listenerPresentBefore: listenerPresentBefore,
    listenerPresentAfter: listenerPresentAfter,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
"""
        result = _run_node(script)
        self.assertTrue(result["listenerPresentBefore"])
        self.assertFalse(result["listenerPresentAfter"], "destroy() must remove the document click listener")
        self.assertTrue(result["intervalCleared"])
        self.assertEqual(result["callsAfterDestroy"], result["callsBeforeDestroy"],
                          "a tick firing after destroy() must not issue any further fetches")


def _grid_attach_race_harness():
    """Mocks for the grid `Terminal`'s attach()/destroy() race: a counting `EventSource` (every
    construction is recorded, so "did a stream get opened after destroy()?" is a number, not an
    inference), plus the handful of instance fields those two methods actually touch. Deliberately
    a plain object with the REAL prototype methods bolted on -- the same `makeSelf` strategy the
    rest of this module already uses, because the grid Terminal's constructor needs a full DOM
    (toolbar, pane, textarea, ResizeObserver) that has nothing to do with this race."""
    return """
var __esBuilt = [];          // one entry per EventSource CONSTRUCTION -- the leak counter
var __esClosed = 0;
function EventSource(url) {
  this.url = url;
  this.closed = false;
  __esBuilt.push(url);
}
EventSource.prototype.close = function () { this.closed = true; __esClosed++; };
// `document` (destroy()'s removeEventListener) and the manual rAF queue both come from
// _harness_mocks() above -- this harness is always concatenated after it.
var __measureCalls = 0;
function makeGridSelf(ttyId) {
  return {
    ttyId: ttyId,
    es: null,
    // Mirrors the production constructor's own `this._destroyed = false;` -- a double that left
    // this undefined would make the guard read "falsy" for the wrong reason and could not tell a
    // present guard from an absent one. (TestGridAttachDestroyRace also pins the constructor
    // line itself by source text, so this default cannot silently drift from the real one.)
    _destroyed: false,
    _onStatusChange: null,
    _disposeThemeBtn: null,
    _disposePaneObserver: null,
    _motionRAFHandle: null,
    _motionRAFPending: false,
    _pendingMotion: null,
    _sendTimers: [],
    _onDocMouseUp: null,
    _noticeEls: [],
    _noticeHighestSeq: -1,
    measureAndResize: function () { __measureCalls++; },
    attach: Terminal.prototype.attach,
    _openStream: Terminal.prototype._openStream,
    destroy: Terminal.prototype.destroy,
  };
}
"""


class TestGridAttachDestroyRace(unittest.TestCase):
    """The grid renderer's mirror of TestXtermSwitchDestroyRace, for the same class of leak.
    `Terminal.prototype.attach` defers BOTH the first measure and `_openStream()` behind a
    `requestAnimationFrame`. `destroy()` running in that gap (closeVT, or switchActiveRenderer /
    mountRenderer swapping to xterm) used to complete as a clean no-op -- `this.es` is still null
    at that point, and nothing cancelled the pending frame -- and then the frame fired anyway,
    constructing an `EventSource` against `/api/term/screen` on an already-destroyed terminal that
    NOTHING would ever close. Server-side that pins `pt.viewers > 0`, so the pty can never be
    idle-reaped. `XtermTerminal` has guarded this exact race with `_destroyed` since the switch
    button landed; the grid renderer had neither the guard nor a test."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_between_attach_and_the_pending_frame_opens_no_stream(self):
        src = _read_src()
        script = _HARNESS_PRELUDE + _harness_mocks() + _grid_attach_race_harness() + "\n".join([
            _function_body(src, "Terminal.prototype.attach = function"),
            _function_body(src, "Terminal.prototype._openStream = function"),
            _function_body(src, "Terminal.prototype.destroy = function"),
        ]) + """
var term = makeGridSelf('tty-race');
term.attach();       // schedules the rAF; nothing has run yet (flushRAF is manual)
term.destroy();      // the race: teardown lands BEFORE the frame fires
flushRAF();          // now let the deferred callback run, if it still would

console.log(JSON.stringify({
  esBuilt: __esBuilt.length,
  esUrls: __esBuilt,
  measureCalls: __measureCalls,
  esFieldAfter: term.es,
  destroyedFlag: term._destroyed,
}));
"""
        result = _run_node(script)
        self.assertEqual(
            result["esBuilt"], 0,
            "the pending frame must open ZERO EventSources after destroy() -- each one is a "
            "stream nothing will ever close, pinning pt.viewers server-side (opened: %r)"
            % (result["esUrls"],),
        )
        self.assertEqual(result["measureCalls"], 0,
                          "the frame must bail out BEFORE measureAndResize(), like XtermTerminal._build()")
        self.assertIsNone(result["esFieldAfter"], "destroy() must leave this.es null")
        self.assertTrue(result["destroyedFlag"], "destroy() must set this._destroyed")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_the_non_racing_path_still_opens_exactly_one_stream(self):
        # The guard must not break the normal case: attach() with no destroy() in between still
        # measures once and opens exactly one stream, which a later destroy() then closes.
        src = _read_src()
        script = _HARNESS_PRELUDE + _harness_mocks() + _grid_attach_race_harness() + "\n".join([
            _function_body(src, "Terminal.prototype.attach = function"),
            _function_body(src, "Terminal.prototype._openStream = function"),
            _function_body(src, "Terminal.prototype.destroy = function"),
        ]) + """
var term = makeGridSelf('tty-normal');
term.attach();
flushRAF();
var afterAttach = { esBuilt: __esBuilt.length, measureCalls: __measureCalls, esSet: !!term.es };
term.destroy();
console.log(JSON.stringify({
  afterAttach: afterAttach,
  esClosed: __esClosed,
  esFieldAfterDestroy: term.es,
}));
"""
        result = _run_node(script)
        self.assertEqual(result["afterAttach"]["esBuilt"], 1, "sanity: the normal path must open one stream")
        self.assertEqual(result["afterAttach"]["measureCalls"], 1)
        self.assertTrue(result["afterAttach"]["esSet"])
        self.assertEqual(result["esClosed"], 1, "destroy() must close the stream attach() opened")
        self.assertIsNone(result["esFieldAfterDestroy"])

    def test_the_constructor_seeds_the_flag_that_guard_reads(self):
        # Source-text companion to the executed tests above: they drive a hand-built double, so
        # only this assertion catches a fix where the guard and destroy() exist but the real
        # constructor never seeds `_destroyed` (leaving it undefined on a live terminal).
        src = _read_src()
        start = src.index("  function Terminal(container, ttyId")
        ctor = src[start:src.index("Terminal.prototype.", start)]
        self.assertIn("this._destroyed = false;", ctor,
                       "the grid Terminal constructor must seed _destroyed, like XtermTerminal's does")


# ===== "Manage terminals" panel: the kill-all safety guard (this task) ==========================
# A real bug shipped here despite 15 GREEN tests: every one of them was a source-text grep against
# tests/test_term_vt_client.py, so none of them ever ran the code. Reproduced live: a double-click
# on "Close all" SIGKILLed three running terminals with the one-line confirmation warning never
# painted for a single frame. Mirrors this file's own `_CONTEXT_BAR_MOCKS` in spirit -- a stub
# `document`/`fetch`/`toast` layer plus a fake-DOM `.dispatch(type, ev)` that drives REAL listeners
# registered via the real addEventListener/onclick assignments, never a test calling a private
# method to simulate a click -- but adds two mocks that section didn't need: a controllable
# `Date.now()` (the arm guard is time-based) and a controllable `setTimeout` (the post-close
# refresh is scheduled, not immediate). Real Node global `setTimeout` is captured as
# `__realSetTimeout` BEFORE the local `function setTimeout` shadows the bare identifier for the
# whole script (top-level `function` declarations in a Node CommonJS module are hoisted to the
# module-wrapper's own scope, never attached to `globalThis` -- so `globalThis.setTimeout` stays
# real throughout), so `__flush()`'s real macrotask hop keeps working even though the extracted
# manager code's OWN `setTimeout` calls land in a manually-driven queue instead.
_MANAGER_MOCKS = """
var __fetchCalls = [];
var __listQueue = [{ terminals: [], max: 8 }];   // each entry: {terminals, max} or {reject:true}
var __closeQueue = [{}];                          // each entry: {} (200 ok), {status:N}, {reject:true}
var __closeCalls = [];                            // every tty POSTed to /api/term/close, in order
var __toastCalls = [];

function __nextFrom(queue) { return queue.length > 1 ? queue.shift() : queue[0]; }

function __makeResponse(status, jsonBody) {
  return {
    ok: status >= 200 && status < 300, status: status,
    json: function () { return Promise.resolve(jsonBody); },
  };
}

function fetch(url, opts) {
  __fetchCalls.push({ url: url, opts: opts });
  if (url === "/api/term/list") {
    var spec = __nextFrom(__listQueue);
    if (spec.reject) return Promise.reject(new Error(spec.rejectMsg || "simulated network failure"));
    var status = spec.status === undefined ? 200 : spec.status;
    return Promise.resolve(__makeResponse(status, { terminals: spec.terminals || [], max: spec.max }));
  }
  if (url === "/api/term/close") {
    var body = {};
    try { body = JSON.parse(opts.body); } catch (e) {}
    __closeCalls.push(body.tty);
    var cspec = __nextFrom(__closeQueue);
    if (cspec.reject) return Promise.reject(new Error("simulated network failure"));
    var cstatus = cspec.status === undefined ? 200 : cspec.status;
    return Promise.resolve(__makeResponse(cstatus, {}));
  }
  return Promise.resolve(__makeResponse(200, {}));
}

function toast(title, msg) { __toastCalls.push({ title: title, msg: msg }); }

// ----- controllable clock: the 500ms arm guard is Date.now()-based -----------------------------
var __now = 1000000;
Date.now = function () { return __now; };

// ----- controllable setTimeout: the post-close refresh (_refreshAfterReap) is scheduled, not
// immediate -- see this section's own header comment for why __realSetTimeout is captured first.
var __realSetTimeout = globalThis.setTimeout;
var __timers = [];
function setTimeout(fn, ms) { __timers.push({ fn: fn, ms: ms }); return __timers.length; }
function clearTimeout(id) {}
function __runTimers() {
  var t = __timers; __timers = [];
  t.forEach(function (x) { x.fn(); });
}

function __flush(n) {
  var p = Promise.resolve();
  for (var i = 0; i < (n || 6); i++) {
    p = p.then(function () { return new Promise(function (r) { __realSetTimeout(r, 0); }); });
  }
  return p;
}

// ----- minimal fake DOM: same shape as _CONTEXT_BAR_MOCKS's __makeEl, plus a working
// querySelectorAll(".class") (real code latches/finds buttons by class, e.g.
// `mgrBodyEl.querySelectorAll(".vtcapx")`) and an innerHTML setter that actually clears
// `children` (renderManagerBody does `mgrBodyEl.innerHTML = ""` before rebuilding) -- neither of
// which the ContextBar harness needed, since ContextBar never queries by class or clears via
// innerHTML. className and classList are kept in sync via a getter/setter, because the real code
// sets `.className = "vtcapx vtmgrall"` as a plain string, never through `.classList.add`.
function __makeEl(tag) {
  var listeners = {};
  var classes = new Set();
  var _html = "";
  var el = {
    tagName: tag, style: {}, textContent: "", title: "", disabled: false,
    children: [], parentNode: null, _attrs: {},
    appendChild: function (child) { child.parentNode = el; el.children.push(child); return child; },
    removeChild: function (child) {
      var i = el.children.indexOf(child);
      if (i !== -1) el.children.splice(i, 1);
      child.parentNode = null;
    },
    setAttribute: function (k, v) { el._attrs[k] = String(v); },
    getAttribute: function (k) { return el._attrs.hasOwnProperty(k) ? el._attrs[k] : null; },
    addEventListener: function (type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener: function (type, fn) {
      var arr = listeners[type] || [];
      var i = arr.indexOf(fn);
      if (i !== -1) arr.splice(i, 1);
    },
    dispatch: function (type, ev) {
      ev = ev || {};
      if (ev.target === undefined) ev.target = el;
      (listeners[type] || []).slice().forEach(function (fn) { fn(ev); });
    },
    contains: function (node) {
      while (node) { if (node === el) return true; node = node.parentNode; }
      return false;
    },
    querySelectorAll: function (selector) {
      var cls = selector.charAt(0) === "." ? selector.slice(1) : null;
      var out = [];
      (function walk(node) {
        (node.children || []).forEach(function (c) {
          if (cls && c.classList && c.classList.contains(cls)) out.push(c);
          walk(c);
        });
      })(el);
      return out;
    },
    focus: function () { el._focused = true; },
  };
  Object.defineProperty(el, "className", {
    get: function () { return Array.from(classes).join(" "); },
    set: function (v) { classes = new Set(String(v).split(/\\s+/).filter(Boolean)); },
  });
  Object.defineProperty(el, "innerHTML", {
    get: function () { return _html; },
    set: function (v) {
      _html = v;
      el.children.forEach(function (c) { c.parentNode = null; });
      el.children = [];
    },
  });
  el.classList = {
    add: function (c) { classes.add(c); },
    remove: function (c) { classes.delete(c); },
    toggle: function (c, force) {
      if (force === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); }
      else if (force) classes.add(c); else classes.delete(c);
    },
    contains: function (c) { return classes.has(c); },
  };
  return el;
}

var document = {
  createElement: function (tag) { return __makeEl(tag); },
  _listeners: {},
  addEventListener: function (type, fn) { (document._listeners[type] = document._listeners[type] || []).push(fn); },
  removeEventListener: function (type, fn) {
    var arr = document._listeners[type] || [];
    var i = arr.indexOf(fn);
    if (i !== -1) arr.splice(i, 1);
  },
};
document.body = document.createElement("body");
var window = {};   // esc's own `window.esc ||` fallback needs this global, same as _CONTEXT_BAR_MOCKS

// ----- test-driver helpers: find controls by the SAME classes/text the real renderManagerBody
// gives them, never by reaching into a closure's private locals. `all` (the Close-all / "Yes,
// kill all N" button) always carries "vtmgrall" in either state; `cancel` only exists once armed
// and carries "vtcapx" but never "vtmgrall", distinguished here by its own fixed label.
function makeTerm(id, cmd) {
  return { tty: id, cmd: cmd || "bash", cwd: "/tmp", started: __now / 1000 - 60,
           session: "", mode: "", forked: false };
}
function findAllBtn() { return mgrBodyEl.querySelectorAll(".vtmgrall")[0]; }
function findCancelBtn() {
  var btns = mgrBodyEl.querySelectorAll(".vtcapx");
  for (var i = 0; i < btns.length; i++) { if (btns[i].textContent === "Cancel") return btns[i]; }
  return null;
}
function findRowKillButtons() {
  return mgrBodyEl.querySelectorAll(".vtcapx").filter(function (b) { return b.textContent === "✕"; });
}
function hasWarning() { return mgrBodyEl.querySelectorAll(".vtmgrwarn").length > 0; }
"""


class TestManagerPanelKillAllGuard(unittest.TestCase):
    """Executes the REAL `openManager`/`refreshManager`/`renderManagerBody`/`closeAll`/
    `closeOneFromManager`/`_armGuardActive` straight out of aitracker/web/ext_vt.js (never
    retyped), against a fake DOM/fetch/clock, to pin the safety property a double-click on "Close
    all" violated in production: 3 running terminals, 3 SIGKILLs, the confirmation warning never
    displayed for a single frame -- while 15 source-text-only tests stayed green throughout,
    because none of them ever ran the code.

    PROVEN REAL for the two tests marked below: see this class's own docstring companion in the
    task report for the full RED transcript from temporarily neutralising the corresponding guard
    in aitracker/web/ext_vt.js via a `cp` backup (never git), and the restoration + `diff`/`shasum`
    proof that the file was returned byte-identical afterwards."""

    def _script(self, body):
        return (_HARNESS_PRELUDE + _MANAGER_MOCKS + _ESC_SRC + _BUILD_TERM_ROW_SRC
                + _MANAGER_PANEL_SRC + body)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_double_click_inside_the_guard_window_kills_nothing(self):
        """THE test that would have caught the shipped bug: arm, then dispatch a second click on
        the (synchronously re-rendered) confirm button immediately -- still inside the 500ms
        guard window. Neither click may reach closeAll()."""
        script = self._script("""
async function main() {
  __listQueue = [{ terminals: [makeTerm("t1"), makeTerm("t2"), makeTerm("t3")], max: 8 }];
  openManager();
  await __flush();

  findAllBtn().onclick();          // click 1: arms, re-renders SYNCHRONOUSLY
  var confirmBtn = findAllBtn();   // the confirm button that now exists, same tick
  confirmBtn.onclick();            // click 2: still inside the 500ms guard window
  await __flush();

  console.log(JSON.stringify({
    closeCalls: __closeCalls,
    stillArmed: mgrConfirmAll,
    stillHasWarning: hasWarning(),
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertEqual(result["closeCalls"], [], "a double-click inside the guard window must kill nothing")
        self.assertTrue(result["stillArmed"], "the panel must stay armed, not silently reset")
        self.assertTrue(result["stillHasWarning"], "the warning must still be showing, never skipped")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_click_after_the_guard_window_confirms_and_kills_all(self):
        """The mirror property: the guard must not also break the honest case. A second click that
        arrives AFTER the 500ms window is a deliberate confirmation and must kill every terminal."""
        script = self._script("""
async function main() {
  var terms = [makeTerm("t1"), makeTerm("t2"), makeTerm("t3")];
  __listQueue = [{ terminals: terms, max: 8 }];
  openManager();
  await __flush();

  findAllBtn().onclick();     // arm
  __now += 600;                // past the 500ms guard
  findAllBtn().onclick();     // deliberate second click, well outside the window
  await __flush(8);
  __runTimers();               // fire the scheduled _refreshAfterReap
  await __flush(6);

  console.log(JSON.stringify({
    closeCalls: __closeCalls.slice().sort(),
    toasts: __toastCalls,
    armedAfter: mgrConfirmAll,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertEqual(result["closeCalls"], ["t1", "t2", "t3"], "a genuine confirm must still kill every terminal")
        self.assertTrue(any(t["title"] == "Closed all terminals" for t in result["toasts"]))
        self.assertFalse(result["armedAfter"], "closeAll must leave the panel unarmed")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_single_click_only_arms_kills_nothing(self):
        script = self._script("""
async function main() {
  __listQueue = [{ terminals: [makeTerm("t1")], max: 8 }];
  openManager();
  await __flush();
  findAllBtn().onclick();
  await __flush();
  console.log(JSON.stringify({
    closeCalls: __closeCalls,
    armed: mgrConfirmAll,
    hasWarning: hasWarning(),
    label: findAllBtn().textContent,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertEqual(result["closeCalls"], [])
        self.assertTrue(result["armed"])
        self.assertTrue(result["hasWarning"])
        self.assertTrue(result["label"].startswith("Yes, kill all"))

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_cancel_aborts_and_is_guarded_against_the_same_double_click_swallow(self):
        script = self._script("""
async function main() {
  var terms = [makeTerm("t1"), makeTerm("t2")];
  __listQueue = [{ terminals: terms, max: 8 }];
  openManager();
  await __flush();

  findAllBtn().onclick();          // arm
  var cancel1 = findCancelBtn();
  cancel1.onclick();               // inside the SAME arm guard window -> swallowed
  var armedAfterFirstCancel = mgrConfirmAll;
  var cancel1b = findCancelBtn();  // no re-render happened -- same element
  cancel1b.onclick();               // a second, still inside the window -> swallowed too
  var armedAfterSecondCancel = mgrConfirmAll;

  __now += 600;                     // past the guard -- a real cancel now
  findCancelBtn().onclick();
  await __flush();

  console.log(JSON.stringify({
    armedAfterFirstCancel: armedAfterFirstCancel,
    armedAfterSecondCancel: armedAfterSecondCancel,
    armedAfterRealCancel: mgrConfirmAll,
    closeCalls: __closeCalls,
    closeAllLabelRestored: findAllBtn().textContent === "Close all",
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertTrue(result["armedAfterFirstCancel"], "cancel inside the arm guard window must be swallowed")
        self.assertTrue(result["armedAfterSecondCancel"])
        self.assertFalse(result["armedAfterRealCancel"], "a cancel after the guard window must actually abort")
        self.assertEqual(result["closeCalls"], [], "cancelling, at any point, must kill nothing")
        self.assertTrue(result["closeAllLabelRestored"])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_held_enter_repeat_does_not_confirm(self):
        """The keyboard twin of the double-click hazard: a HELD Enter auto-repeats keydown at
        ~30ms once past the OS's repeat delay -- long after the 500ms time guard has expired -- so
        only the dedicated `ev.repeat` check stops it. Time is advanced past the guard window
        FIRST so this test cannot pass merely because the time-based guard is still active; it
        isolates the repeat-blocker specifically.

        This fake DOM has no browser-level "unprevented Enter keydown becomes a click" behaviour
        to fall back on, so the driver performs that translation explicitly here, exactly like a
        real browser's default action would -- see the `if (!prevented)` line below."""
        script = self._script("""
async function main() {
  var terms = [makeTerm("t1"), makeTerm("t2")];
  __listQueue = [{ terminals: terms, max: 8 }];
  openManager();
  await __flush();

  findAllBtn().onclick();     // arm
  __now += 600;                // past the 500ms guard -- isolates the repeat-blocker
  var confirmBtn = findAllBtn();

  var prevented = false;
  confirmBtn.dispatch("keydown", { repeat: true, preventDefault: function () { prevented = true; } });
  if (!prevented) confirmBtn.onclick();   // the browser's default action, performed by hand
  await __flush();

  console.log(JSON.stringify({ prevented: prevented, closeCalls: __closeCalls, armed: mgrConfirmAll }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertTrue(result["prevented"], "ev.repeat must call preventDefault()")
        self.assertEqual(result["closeCalls"], [], "a held-Enter repeat must never confirm the kill")
        self.assertTrue(result["armed"], "the panel must stay armed, waiting for a real decision")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_arming_then_closing_one_row_redraws_the_panel_unarmed(self):
        """`refreshManager` disarms on EVERY redraw (`mgrConfirmAll = false` at its own top), not
        just on open/close -- this drives the REAL closeOneFromManager -> _refreshAfterReap ->
        refreshManager -> renderManagerBody chain end to end and asserts the armed flag is cleared
        by THAT path, not merely by re-checking after a manual openManager()/closeManager()."""
        script = self._script("""
async function main() {
  var terms = [makeTerm("t1"), makeTerm("t2"), makeTerm("t3")];
  __listQueue = [{ terminals: terms, max: 8 }];
  openManager();
  await __flush();

  findAllBtn().onclick();               // arm
  var armedBeforeClose = mgrConfirmAll;
  findRowKillButtons()[0].onclick();    // closeOneFromManager(t1) -- an UNRELATED row kill
  await __flush(6);
  __runTimers();                         // fire the scheduled _refreshAfterReap -> refreshManager
  await __flush(6);

  console.log(JSON.stringify({
    armedBeforeClose: armedBeforeClose,
    armedAfterRefresh: mgrConfirmAll,
    hasWarningAfterRefresh: hasWarning(),
    closeAllLabelRestored: findAllBtn().textContent === "Close all",
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertTrue(result["armedBeforeClose"])
        self.assertFalse(result["armedAfterRefresh"], "a row kill's refresh must clear the armed flag too")
        self.assertFalse(result["hasWarningAfterRefresh"])
        self.assertTrue(result["closeAllLabelRestored"])


# ===== Bell flash: one shared helper, two triggers (this task) ==================================
# The bell reached the user on the grid renderer (a `.vtbell` pulse driven off the SSE frame's
# `msg.bell` counter, in `_applyPatch`) but produced NOTHING on XtermTerminal, now the DEFAULT
# renderer: xterm.js's own `onBell` event fires on a real BEL byte (confirmed against the vendored
# build -- see the comment above XtermTerminal._build's onBell wiring in ext_vt.js) but nothing
# ever subscribed to it. Fixed by hoisting the pulse itself -- `pane.classList.add("vtbell")` plus
# the 180ms removal -- into ONE shared `_flashBellPane(pane)` helper that both `Terminal.prototype.
# _flashBell` (grid) and XtermTerminal's new onBell handler call. Only the TRIGGER differs per
# renderer (server counter vs. xterm's own event) -- see `_flashBellPane`'s own header comment in
# ext_vt.js for why that is one implementation fed by two sources, not a forked capability under
# conventions rule 4.
class TestXtermBellFlash(unittest.TestCase):
    """XtermTerminal side: onBell -> the shared _flashBellPane -> the pane gets 'vtbell'; disposed
    cleanly on destroy(); a burst of bells never stacks more than the one class."""

    def _script(self, body):
        # _FLASH_BELL_SRC (the shared helper + the grid's own _flashBell delegate) must precede
        # _XTERM_LEAK_SRC so XtermTerminal._build's onBell handler has _flashBellPane to call --
        # see _FLASH_BELL_SRC's own comment above for why it lives outside that span in the real
        # file and has to be pulled in separately here.
        return _HARNESS_PRELUDE + _xterm_leak_harness() + _FLASH_BELL_SRC + _XTERM_LEAK_SRC + body

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_xterm_onbell_flashes_the_pane(self):
        """The exact gap: ring xterm.js's own bell event and confirm the pane actually pulses --
        not a source-text grep, the real handler chain end to end."""
        script = self._script("""
async function main() {
  var container = makeContainer();
  var t = new XtermTerminal(container, 'tty-bell');
  t.attach();               // starts the (controllable) asset load
  resolveNextAssetLoad();   // let the deferred _build() run
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  var beforeFlash = t.pane.classList.contains('vtbell');
  t.term.fireBell();        // the real xterm.js Emitter firing, via the mock's fireBell() helper
  var afterFlash = t.pane.classList.contains('vtbell');

  console.log(JSON.stringify({
    beforeFlash: beforeFlash,
    afterFlash: afterFlash,
    disposeBellIsDisposable: !!(t._disposeBell && typeof t._disposeBell.dispose === 'function'),
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertFalse(result["beforeFlash"], "sanity: the pane must start with no 'vtbell' class")
        self.assertTrue(result["afterFlash"],
                         "firing xterm's onBell must reach _flashBellPane and add 'vtbell' to the pane")
        self.assertTrue(result["disposeBellIsDisposable"],
                         "_build() must store the Disposable onBell() returns, for destroy() to dispose")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_bell_listener_disposed_on_destroy_no_leak(self):
        """Mirrors this file's own TestXtermSwitchDestroyRace idiom: destroy() must leave nothing
        behind. Keeps a reference to the RAW fake xterm.js instance from before destroy() nulls
        `t.term`, then fires its bell directly -- proving the listener list is actually empty
        afterward (a real leak, not just an untested assumption that dispose() was called)."""
        script = self._script("""
async function main() {
  var container = makeContainer();
  var t = new XtermTerminal(container, 'tty-dispose');
  t.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  var innerTerm = t.term;   // the raw stub xterm.js Terminal -- destroy() will null t.term itself
  var disposeCountBefore = __bellDisposeCount;
  t.destroy();
  var disposeCountAfter = __bellDisposeCount;

  innerTerm.fireBell();     // ring the bell on the UNDERLYING stub directly, post-destroy
  var handlersLeftAfterDestroy = (innerTerm._bellHandlers || []).length;

  console.log(JSON.stringify({
    disposeCountBefore: disposeCountBefore,
    disposeCountAfter: disposeCountAfter,
    disposeBellFieldAfter: t._disposeBell,
    handlersLeftAfterDestroy: handlersLeftAfterDestroy,
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertEqual(result["disposeCountBefore"], 0)
        self.assertEqual(result["disposeCountAfter"], 1,
                          "destroy() must call the onBell Disposable's .dispose() exactly once")
        self.assertIsNone(result["disposeBellFieldAfter"], "destroy() must null out _disposeBell")
        self.assertEqual(result["handlersLeftAfterDestroy"], 0,
                          "a bell fired on the raw xterm.js instance AFTER destroy() must reach "
                          "zero handlers -- anything else is exactly the leak this test guards")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_bell_burst_does_not_stack_animations(self):
        """A program spamming BEL (e.g. a build script on every error) must not queue N overlapping
        pulses. `_flashBellPane` always (re-)adds the SAME literal class name -- re-adding an
        already-present class is a DOM no-op and can't restart/stack a CSS animation -- so this
        proves the class name never varies per event (which would be the actual way to stack
        independent animations) and that the pane is still (simply) flashing afterward."""
        script = self._script("""
async function main() {
  var container = makeContainer();
  var t = new XtermTerminal(container, 'tty-burst');
  t.attach();
  resolveNextAssetLoad();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();

  for (var i = 0; i < 50; i++) t.term.fireBell();   // a burst, well within any 180ms pulse window

  console.log(JSON.stringify({
    stillFlashing: t.pane.classList.contains('vtbell'),
    addCallCount: t.pane.classList._addCalls.length,
    distinctClassesAdded: Array.from(new Set(t.pane.classList._addCalls)),
  }));
}
main().catch(function (e) { console.error(e.stack || String(e)); process.exit(1); });
""")
        result = _run_node(script)
        self.assertTrue(result["stillFlashing"])
        self.assertEqual(result["addCallCount"], 50, "sanity: every fireBell() reached the helper")
        self.assertEqual(result["distinctClassesAdded"], ["vtbell"],
                          "every bell in the burst must (re-)add the SAME class -- a fresh "
                          "per-event class name is what would actually stack overlapping animations")


class TestGridBellFlashRegression(unittest.TestCase):
    """The grid renderer's OWN trigger (`_applyPatch`'s `msg.bell` counter) must keep working after
    the pulse itself was hoisted into `_flashBellPane` -- a regression guard for the refactor: a
    bad extraction could easily break the flash for BOTH renderers by leaving `Terminal.prototype.
    _flashBell` calling something that no longer exists, or the wrong `this`."""

    @staticmethod
    def _self_helper():
        return """
function makePaneEl() {
  var classes = new Set();
  return {
    classList: {
      add: function (c) { classes.add(c); },
      remove: function (c) { classes.delete(c); },
      contains: function (c) { return classes.has(c); },
      toggle: function (c, force) {
        if (force === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); }
        else if (force) classes.add(c); else classes.delete(c);
      },
    },
  };
}
function makeGridBellSelf() {
  return {
    pane: makePaneEl(),
    grid: [],
    cursor: [0, 0],
    version: 0,
    alt: false,
    starting: false,
    cursorVisible: true,
    bracketedPaste: false,
    focusEvents: false,
    mouse: { mode: 0, sgr: false },
    _refreshMouseToggle: null,
    _bellSeen: null,
    viewingHistory: false,
    _onStatusChange: null,
    _onNotice: null,
    _paintRow: function () {},
    _layoutCursor: function () {},
    _updateNewOutputBadge: function () {},
    _flashBell: Terminal.prototype._flashBell,
    _applyPatch: Terminal.prototype._applyPatch,
  };
}
"""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_server_bell_counter_still_flashes_the_grid_pane(self):
        script = _HARNESS_PRELUDE + _FLASH_BELL_SRC + _APPLY_PATCH_SRC + self._self_helper() + """
var self1 = makeGridBellSelf();
self1._applyPatch({ v: 1, bell: 1 });   // baseline frame: seeds _bellSeen, must NOT flash
var flashedOnBaseline = self1.pane.classList.contains('vtbell');
self1._applyPatch({ v: 2, bell: 2 });   // counter advanced -- must flash
var flashedOnIncrement = self1.pane.classList.contains('vtbell');

var self2 = makeGridBellSelf();
self2._applyPatch({ v: 1, bell: 5 });
self2._applyPatch({ v: 2, bell: 5 });   // counter UNCHANGED between frames -- must not (re-)flash
console.log(JSON.stringify({
  flashedOnBaseline: flashedOnBaseline,
  flashedOnIncrement: flashedOnIncrement,
}));
"""
        result = _run_node(script)
        self.assertFalse(result["flashedOnBaseline"],
                          "the FIRST frame only establishes the _bellSeen baseline -- it must not flash")
        self.assertTrue(result["flashedOnIncrement"],
                         "a server bell counter that actually advanced must still flash the grid pane")


# ===== notice banners: ONE mount-owned helper, fed by BOTH renderers ===========================
# tests/test_term_vt_client.py used to pin this behaviour with ~15 source-text greps against
# `Terminal.prototype._displayNotice`'s exact body and `_applyPatch`'s notice block -- every one of
# which stayed green while the DEFAULT renderer (xterm) raised no banner at all, because none of
# them ever ran anything. These execute the real extracted code instead.
#
# A proper little DOM is needed here, not the append-only stubs elsewhere in this module:
# createNoticeBanner's whole insertion rule is positional (`insertBefore(el, last ? last.nextSibling
# : container.firstChild)`), so `firstChild`/`nextSibling`/`removeChild` have to behave like the
# real thing or the test would prove nothing about where a banner actually lands.
_NOTICE_DOM_MOCKS = """
function __makeNode(tag) {
  var node = {
    tagName: tag || 'div',
    className: '',
    textContent: '',
    parentNode: null,
    childNodes: [],
    // Real DOM semantics for the three operations createNoticeBanner uses. insertBefore(el, null)
    // appends (that IS the spec, and it is the empty-container case the mounts rely on).
    insertBefore: function (el, ref) {
      if (el.parentNode) el.parentNode.removeChild(el);
      var i = ref ? this.childNodes.indexOf(ref) : -1;
      if (ref && i === -1) throw new Error('insertBefore: reference node is not a child');
      if (i === -1) this.childNodes.push(el); else this.childNodes.splice(i, 0, el);
      el.parentNode = this;
      return el;
    },
    appendChild: function (el) { return this.insertBefore(el, null); },
    removeChild: function (el) {
      var i = this.childNodes.indexOf(el);
      if (i === -1) throw new Error('removeChild: not a child');
      this.childNodes.splice(i, 1);
      el.parentNode = null;
      return el;
    },
    setAttribute: function () {},
    // Present so XtermTerminal's own pane can be one of these too: `.xterm-screen` never exists
    // here, which _correctFitOverflow treats as a safe no-op (its `if (!screenEl) return` guard).
    querySelector: function () { return null; },
    getBoundingClientRect: function () { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
  };
  var __classes = new Set();
  node.classList = {
    add: function (c) { __classes.add(c); },
    remove: function (c) { __classes.delete(c); },
    contains: function (c) { return __classes.has(c); },
    toggle: function (c, force) {
      if (force === undefined) { __classes.has(c) ? __classes.delete(c) : __classes.add(c); }
      else if (force) __classes.add(c); else __classes.delete(c);
    },
  };
  Object.defineProperty(node, 'firstChild', {
    get: function () { return this.childNodes.length ? this.childNodes[0] : null; },
  });
  Object.defineProperty(node, 'nextSibling', {
    get: function () {
      if (!this.parentNode) return null;
      var i = this.parentNode.childNodes.indexOf(this);
      return (i !== -1 && i + 1 < this.parentNode.childNodes.length)
        ? this.parentNode.childNodes[i + 1] : null;
    },
  });
  Object.defineProperty(node, 'innerHTML', {
    get: function () { return this.__html || ''; },
    set: function (v) { this.__html = v; this.childNodes.length = 0; },
  });
  return node;
}

// Reads back what a viewer would actually SEE: the text of every .vtnotice banner in `container`,
// top to bottom. Goes through textContent only -- if the implementation ever switched to innerHTML
// this returns '' and every text assertion below fails, which is the point.
function __bannerTexts(container) {
  return container.childNodes
    .filter(function (n) { return n.className === 'vtnotice'; })
    .map(function (n) { return n.childNodes.map(function (s) { return s.textContent; }).join(''); });
}
"""

# The MOUNT's own wiring, verbatim in spirit with `_wireModalTerm` / bootStandalone's
# `mountRenderer`: forward the renderer's notice into the shared banner, and hand the terminal one
# measureAndResize() only when the DOM actually changed.
_NOTICE_MOUNT_WIRING = """
function __wireMount(term, banner) {
  term.__resizes = 0;
  term.measureAndResize = function () { term.__resizes++; };
  term._onNotice = function (n) { if (banner.show(n)) term.measureAndResize(); };
}
"""


class TestNoticeBannerXtermPath(unittest.TestCase):
    """The GAP this task closed, executed: the xterm renderer -- the DEFAULT -- drew no notice
    banner at all. `/api/term/raw` emits `event: notice\\ndata: {"seq":<int>,"text":"<str>"}`
    (verified on the wire against term_vt._raw_stream_body), and `_openStream`'s
    addEventListener("notice", ...) must turn that into a real banner through the shared,
    mount-owned helper."""

    def _script(self, body):
        return (_HARNESS_PRELUDE + _xterm_leak_harness() + _NOTICE_DOM_MOCKS
                + _NOTICE_BANNER_SRC + _XTERM_LEAK_SRC + _NOTICE_MOUNT_WIRING
                # Every element XtermTerminal builds is a real tree node here too, so the pane and
                # the banners live in one consistent DOM.
                + "\ndocument.createElement = __makeNode;\n" + body)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_named_notice_event_on_the_raw_stream_raises_a_banner(self):
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = new XtermTerminal(makeContainer(), 'tty-1', _noopRendererSwitch);
__wireMount(term, banner);
term.attach();
resolveNextAssetLoad();
setTimeout(function () {
  var listeners = term.es.__listenerCount('notice');
  term.es.__emit('notice', JSON.stringify({ seq: 1, text: 'the resume was refused' }));
  console.log(JSON.stringify({
    listeners: listeners,
    texts: __bannerTexts(mount),
    resizes: term.__resizes,
  }));
}, 0);
"""))
        self.assertEqual(result["listeners"], 1,
                          "_openStream must subscribe to the stream's named `notice` event")
        self.assertEqual(result["texts"], ["the resume was refused"],
                          "a `notice` frame on /api/term/raw must raise a real .vtnotice banner")
        self.assertEqual(result["resizes"], 1,
                          "a new banner shrinks the pane -- the mount must renegotiate the rows")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_unnamed_data_frames_never_become_banners(self):
        """The raw stream's UNNAMED frames are base64 PTY bytes. A regression that listened on
        onmessage instead of the named event would both corrupt the terminal and raise garbage
        banners; this pins that the two channels stay separate."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = new XtermTerminal(makeContainer(), 'tty-1', _noopRendererSwitch);
__wireMount(term, banner);
term.attach();
resolveNextAssetLoad();
setTimeout(function () {
  term.es.onmessage({ data: Buffer.from('plain pty bytes').toString('base64') });
  console.log(JSON.stringify({ texts: __bannerTexts(mount) }));
}, 0);
"""))
        self.assertEqual(result["texts"], [])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_malformed_notice_frame_is_ignored_not_thrown(self):
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = new XtermTerminal(makeContainer(), 'tty-1', _noopRendererSwitch);
__wireMount(term, banner);
term.attach();
resolveNextAssetLoad();
setTimeout(function () {
  var threw = false;
  try { term.es.__emit('notice', 'not json at all'); } catch (e) { threw = true; }
  term.es.__emit('notice', JSON.stringify({ seq: 4, text: 'still working' }));
  console.log(JSON.stringify({ threw: threw, texts: __bannerTexts(mount) }));
}, 0);
"""))
        self.assertFalse(result["threw"], "a malformed frame must not throw out of the listener")
        self.assertEqual(result["texts"], ["still working"],
                          "the stream must keep working after a malformed frame")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_destroy_removes_the_notice_listener_and_closes_the_stream(self):
        """Teardown discipline, executed: destroy() goes through _closeStream, which removes the
        named-event listener BY REFERENCE and then closes the stream. A leaked listener would keep
        firing `_onNotice` into a mount whose terminal is gone."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = new XtermTerminal(makeContainer(), 'tty-1', _noopRendererSwitch);
__wireMount(term, banner);
term.attach();
resolveNextAssetLoad();
setTimeout(function () {
  var es = term.es;                       // destroy() nulls term.es -- keep our own handle
  var before = es.__listenerCount('notice');
  term.destroy();
  var after = es.__listenerCount('notice');
  es.__emit('notice', JSON.stringify({ seq: 9, text: 'after teardown' }));
  console.log(JSON.stringify({
    before: before, after: after, closed: es.closed,
    texts: __bannerTexts(mount), esNulled: term.es === null,
  }));
}, 0);
"""))
        self.assertEqual(result["before"], 1)
        self.assertEqual(result["after"], 0, "destroy() must remove the `notice` listener")
        self.assertTrue(result["closed"])
        self.assertTrue(result["esNulled"])
        self.assertEqual(result["texts"], [],
                          "a torn-down terminal must not still be able to raise banners")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_reopening_the_stream_does_not_stack_notice_listeners(self):
        """_openStream replaces the stream (it is called again on a reconnect path); it must tear
        the old subscription down rather than leave the previous EventSource holding one."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = new XtermTerminal(makeContainer(), 'tty-1', _noopRendererSwitch);
__wireMount(term, banner);
term.attach();
resolveNextAssetLoad();
setTimeout(function () {
  var first = term.es;
  term._openStream();
  console.log(JSON.stringify({
    firstClosed: first.closed,
    firstListeners: first.__listenerCount('notice'),
    secondListeners: term.es.__listenerCount('notice'),
    isNewStream: term.es !== first,
  }));
}, 0);
"""))
        self.assertTrue(result["isNewStream"])
        self.assertTrue(result["firstClosed"])
        self.assertEqual(result["firstListeners"], 0,
                          "the replaced stream must not keep its `notice` listener")
        self.assertEqual(result["secondListeners"], 1)


class TestNoticeBannerGridPath(unittest.TestCase):
    """REGRESSION guard for collapsing the three copies: the grid renderer's own trigger -- the
    `notices` array inside /api/term/screen's JSON frame -- must still reach the same shared
    banner, now via `_onNotice` instead of the deleted `Terminal.prototype._displayNotice`."""

    @staticmethod
    def _grid_self():
        return """
function makeGridSelf() {
  return {
    pane: __makeNode('div'),
    grid: [], cursor: [0, 0], version: 0, alt: false, starting: false,
    cursorVisible: true, bracketedPaste: false, focusEvents: false,
    mouse: { mode: 0, sgr: false },
    _refreshMouseToggle: null, _bellSeen: null, viewingHistory: false,
    _onStatusChange: null, _onNotice: null,
    _paintRow: function () {}, _layoutCursor: function () {},
    _updateNewOutputBadge: function () {}, _flashBell: function () {},
    _applyPatch: Terminal.prototype._applyPatch,
  };
}
"""

    def _script(self, body):
        return (_HARNESS_PRELUDE + _NOTICE_DOM_MOCKS + _NOTICE_BANNER_SRC + _APPLY_PATCH_SRC
                + _NOTICE_MOUNT_WIRING + self._grid_self()
                + "\nvar document = { createElement: __makeNode };\n" + body)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_notices_in_the_json_frame_still_raise_banners(self):
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = makeGridSelf();
__wireMount(term, banner);
term._applyPatch({ v: 1, notices: [{ seq: 1, text: 'first' }, { seq: 2, text: 'second' }] });
console.log(JSON.stringify({ texts: __bannerTexts(mount), resizes: term.__resizes }));
"""))
        self.assertEqual(result["texts"], ["first", "second"],
                          "the grid renderer's JSON-frame notices must still become banners")
        self.assertEqual(result["resizes"], 2)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_absent_or_malformed_notices_key_is_a_no_op(self):
        """Older server, or a frame with no notices at all -- the defensive read `_applyPatch`
        always had must survive the refactor."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var banner = createNoticeBanner(mount);
var term = makeGridSelf();
__wireMount(term, banner);
var threw = false;
try {
  term._applyPatch({ v: 1 });                       // key absent entirely
  term._applyPatch({ v: 2, notices: null });        // present but null
  term._applyPatch({ v: 3, notices: 'nope' });      // present but not an array
  term._applyPatch({ v: 4, notices: [{ seq: 1 }] }); // an entry with no text at all
} catch (e) { threw = true; }
console.log(JSON.stringify({ threw: threw, texts: __bannerTexts(mount) }));
"""))
        self.assertFalse(result["threw"])
        self.assertEqual(result["texts"], [])


class TestNoticeBannerSharedPolicy(unittest.TestCase):
    """The policy that used to be duplicated per renderer -- seq dedupe, the 3-banner cap, escaping,
    insertion position -- now lives once in createNoticeBanner. These execute it directly, which is
    also what makes it true for BOTH renderers at once."""

    def _script(self, body):
        return (_HARNESS_PRELUDE + _NOTICE_DOM_MOCKS + _NOTICE_BANNER_SRC
                + "\nvar document = { createElement: __makeNode };\n" + body)

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_replayed_seq_is_suppressed_but_a_higher_seq_still_shows(self):
        """EventSource auto-retries the transport on its own, and the server replays from seq 0 for
        the reconnected viewer -- so the SAME notices arrive again. Already-displayed ones must not
        re-flash; anything genuinely new must."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
var shown = [];
shown.push(b.show({ seq: 1, text: 'one' }));
shown.push(b.show({ seq: 2, text: 'two' }));
// ---- transport reconnect: the server replays from seq 0 ----
shown.push(b.show({ seq: 1, text: 'one' }));
shown.push(b.show({ seq: 2, text: 'two' }));
shown.push(b.show({ seq: 3, text: 'three' }));   // genuinely new
console.log(JSON.stringify({ shown: shown, texts: __bannerTexts(mount) }));
"""))
        self.assertEqual(result["shown"], [True, True, False, False, True])
        self.assertEqual(result["texts"], ["one", "two", "three"],
                          "a replayed notice must not be raised twice, a new one must be")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_a_new_viewer_gets_the_whole_replay_as_banners(self):
        """The other half of the same server behaviour: a viewer attaching LATE receives every
        queued notice from seq 1. A fresh mount has seen nothing, so all of them must show."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
[{ seq: 1, text: 'a' }, { seq: 2, text: 'b' }].forEach(function (n) { b.show(n); });
console.log(JSON.stringify({ texts: __bannerTexts(mount) }));
"""))
        self.assertEqual(result["texts"], ["a", "b"])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_stack_caps_at_three_and_evicts_the_oldest(self):
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
for (var i = 1; i <= 5; i++) b.show({ seq: i, text: 'n' + i });
console.log(JSON.stringify({ texts: __bannerTexts(mount), children: mount.childNodes.length }));
"""))
        self.assertEqual(result["texts"], ["n3", "n4", "n5"],
                          "the cap is 3 displayed banners, oldest evicted first")
        self.assertEqual(result["children"], 3,
                          "an evicted banner must leave the DOM, not just the tracking array")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_text_is_escaped_via_textContent_never_parsed_as_html(self):
        """Notice text is SERVER-supplied. `__bannerTexts` reads textContent only, so a switch to
        innerHTML would make this return the empty string rather than the markup."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
b.show({ seq: 1, text: '<img src=x onerror=alert(1)>' });
var banner = mount.childNodes[0];
console.log(JSON.stringify({
  texts: __bannerTexts(mount),
  bannerInnerHtml: banner.__html || '',
  spanInnerHtml: banner.childNodes[0].__html || '',
  className: banner.className,
}));
"""))
        self.assertEqual(result["texts"], ["<img src=x onerror=alert(1)>"],
                          "the raw text must land in textContent, verbatim and inert")
        self.assertEqual(result["bannerInnerHtml"], "")
        self.assertEqual(result["spanInnerHtml"], "",
                          "nothing may be assigned through innerHTML on the notice path")
        self.assertEqual(result["className"], "vtnotice")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_empty_and_seqless_notices(self):
        """An empty/absent text is dropped (there is nothing to say); a notice with NO seq -- the
        open-time advisory from POST /api/term/pty's response, or the ?notice= link -- is always
        shown, because it has no position in the stream to be deduped against."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
var shown = [
  b.show({ seq: 1, text: '' }),
  b.show({ seq: 2 }),
  b.show(null),
  b.show({ text: 'open-time advisory' }),
  b.show({ text: 'another seqless one' }),
  b.show({ seq: 1, text: 'streamed one' }),
];
console.log(JSON.stringify({ shown: shown, texts: __bannerTexts(mount) }));
"""))
        self.assertEqual(result["shown"], [False, False, False, True, True, True])
        self.assertEqual(result["texts"],
                          ["open-time advisory", "another seqless one", "streamed one"],
                          "a seqless notice must never consume or be blocked by the seq tracker")

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_banners_stay_above_the_terminal_in_arrival_order(self):
        """The mount's container also holds .vttermwrap / .vtctxbar / .vtfullstatus. A banner
        raised long after those exist must still land ABOVE the terminal, and after the banners
        already on screen -- never reversed, never below the pane."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
b.show({ text: 'open-time' });          // raised BEFORE the terminal exists
var wrap = __makeNode('div'); wrap.className = 'vttermwrap'; mount.appendChild(wrap);
var status = __makeNode('div'); status.className = 'vtfullstatus'; mount.appendChild(status);
b.show({ seq: 1, text: 'mid-session' }); // raised long AFTER
b.show({ seq: 2, text: 'later still' });
console.log(JSON.stringify({
  order: mount.childNodes.map(function (n) { return n.className; }),
  texts: __bannerTexts(mount),
}));
"""))
        self.assertEqual(result["order"],
                          ["vtnotice", "vtnotice", "vtnotice", "vttermwrap", "vtfullstatus"])
        self.assertEqual(result["texts"], ["open-time", "mid-session", "later still"])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_clear_removes_the_banners_and_resets_the_seq_tracker(self):
        """clear() is what openVT/closeVT call for a NEW pty, whose seqs restart at 1 -- so it must
        reset the high-water mark, not only the DOM, or the next pty's notices would be swallowed."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
b.show({ seq: 1, text: 'old pty' });
b.show({ seq: 2, text: 'old pty 2' });
b.clear();
var afterClear = mount.childNodes.length;
var reshown = b.show({ seq: 1, text: 'new pty seq 1' });
console.log(JSON.stringify({ afterClear: afterClear, reshown: reshown, texts: __bannerTexts(mount) }));
"""))
        self.assertEqual(result["afterClear"], 0)
        self.assertTrue(result["reshown"],
                         "after clear(), a fresh pty's seq 1 must not be suppressed as a replay")
        self.assertEqual(result["texts"], ["new pty seq 1"])

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_banners_survive_a_renderer_switch_without_reflashing(self):
        """BEHAVIOUR CHANGE, pinned deliberately. Terminal.prototype.destroy used to drop both the
        banner elements AND the seq tracker, so switching renderers re-showed every notice as the
        rebuilt renderer replayed them. The tracker now belongs to the MOUNT, which a switch does
        not touch (only closeVT/openVT clear it) -- so the banners simply stay put, exactly like
        the ContextBar both switch paths deliberately re-wire rather than destroy."""
        result = _run_node(self._script("""
var mount = __makeNode('div');
var b = createNoticeBanner(mount);
b.show({ seq: 1, text: 'refused resume' });
var before = __bannerTexts(mount);
// ---- switchActiveRenderer / mountRenderer: old term destroyed, new one attached to the SAME
// pty, whose stream replays from seq 0 for this fresh viewer. The mount is untouched. ----
b.show({ seq: 1, text: 'refused resume' });
console.log(JSON.stringify({ before: before, after: __bannerTexts(mount) }));
"""))
        self.assertEqual(result["before"], ["refused resume"])
        self.assertEqual(result["after"], ["refused resume"],
                          "a renderer switch must neither drop nor duplicate a standing banner")


if __name__ == "__main__":
    unittest.main()
