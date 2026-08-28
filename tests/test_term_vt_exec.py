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
    return {
      className: '',
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
function EventSource(url) { this.url = url; this.closed = false; }
EventSource.prototype.close = function () { this.closed = true; };

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


if __name__ == "__main__":
    unittest.main()
