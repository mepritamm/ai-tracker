"""Regression test for: CR.dialogs.update() — the generic seam ext_cr_boot.js's
SIDE_EXT poll hook uses to broadcast {flags, sessions, now} to whichever dialog
happens to be open — forwarded that broadcast to WHICHEVER dialog was topmost,
unconditionally, even when the dialog never asked for it.

THE BUG (confirmed by adversarial review, on top of the one already fixed for
manage-terminals): the directory picker (ext_cr_dialogs.js's renderDirectoryPicker,
opened by ext_cr_term.js's "+ New terminal"/"+ New Claude session" flow — first
with {loading:true}, then re-opened with {cwds, note} once GET /api/term/cwds
resolves) has an `update` closure that does a blind `payload = p || {}; paint();`.
If the poll broadcast lands while the picker is topmost, `payload` is replaced by
{flags, sessions, now} -- paint() then sees no `loading`, no `note`, and `cwds=[]`,
so it renders "No recent directories" over what was a real list, and (because
paint() rebuilds `chrome.body.innerHTML`) destroys any partially-typed path in the
free-text input too.

Guarding renderDirectoryPicker's own `update` (the way manage-terminals's `update`
was hardened, per test_cr_manage_terminals_poll.py) would only protect THIS one
dialog -- the next dialog anyone adds inherits the exact same bug by default. THE
FIX instead lives at the seam: ext_cr_boot.js now tags the broadcast itself
(`{kind: 'poll', ...}`), and ext_cr_dialogs.js's own `open()`/`update()`:
  1. `open()` records `wantsPoll: !!built.wantsPoll` on the dialog's stack entry --
     an opt-in a builder declares by returning `wantsPoll: true` alongside its own
     backdrop/panel/update (today: only renderFlagsList, the one real consumer).
  2. `update(state)` refuses to forward a `kind:'poll'` payload to a dialog whose
     entry doesn't carry `wantsPoll` -- REGARDLESS of which dialog that is, now or
     in the future. A non-poll update (a dialog's own richer re-open, via open()'s
     same-name dedupe path) is untouched -- it never carries `kind:'poll'`.

This test proves BOTH halves at once, against the REAL shipped `open`/`close`/
`update`/`topEntry`/`renderDirectoryPicker`/`renderFlagsList` (brace-matched
straight out of aitracker/web/ext_cr_dialogs.js, never a hand-retyped paraphrase,
so a future shape drift fails this test loudly instead of silently going stale):
  (a) the directory picker, opened with a real {cwds} list and made topmost,
      SURVIVES a poll-shaped broadcast delivered through the real `update()` seam
      -- its rendered list of directory buttons is byte-for-byte unchanged -- and
      a real re-open (a fresh, larger {cwds}) still lands correctly afterward;
  (b) the flags dialog, made topmost, STILL legitimately receives {flags} off
      the very same poll-shaped broadcast -- its rendered row count tracks each
      new {flags} array the broadcast carries.

IDIOM: same "brace-match the exact function out of the real file" technique as
test_cr_rail_toggle.py/test_cr_manage_terminals_poll.py's own _extract_function()
helper -- extracted from the single-file source (aitracker/web/ext_cr_dialogs.js)
rather than the fully assembled multi-file bundle, because `open`/`close`/`update`
are NOT unique names across the whole concatenated app (ext_cr_term.js/
ext_cr_board.js each define their own same-named functions) -- page.py's own
build_page() only concatenates raw file text verbatim (confirmed by reading it),
so this file's own text IS the real shipped source for its own contribution.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_WEB = os.path.join(_ROOT, "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)


def _read_source():
    with open(os.path.join(_WEB, "ext_cr_dialogs.js"), encoding="utf-8") as fh:
        return fh.read()


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the real
    source. Raises loudly (never returns a guess) if the shape has moved, so this
    test fails honestly instead of silently exercising stale text."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in ext_cr_dialogs.js" % name)
    brace_start = source.index('{', m.start())
    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[m.start():i + 1]
    raise AssertionError("unterminated function %s() (brace mismatch)" % name)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout):
    marker = "===POLL_SEAM_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _driver_js():
    src = _read_source()
    fn_open = _extract_function(src, "open")
    fn_close = _extract_function(src, "close")
    fn_update = _extract_function(src, "update")
    fn_top = _extract_function(src, "topEntry")
    fn_dirpicker = _extract_function(src, "renderDirectoryPicker")
    fn_flags = _extract_function(src, "renderFlagsList")

    return r"""
var OUT = {};
(function () {
  'use strict';

  // ---- minimal, honest-enough stubs (same spirit as the manage-terminals
  // harness: real enough that a wrong paint()/wrong forward is observable, not
  // a no-op that would make every assertion here pass vacuously) ----
  var document = { activeElement: null };
  var BODIES = {}; // dialog name -> its chrome.body stub, for reading back what actually painted

  function makeBody() {
    var kids = [];
    var body = {
      appendChild: function (c) { kids.push(c); },
    };
    Object.defineProperty(body, 'children', { get: function () { return kids; } });
    Object.defineProperty(body, 'innerHTML', {
      get: function () { return ''; },
      set: function () { kids.length = 0; },
    });
    return body;
  }

  function h(tag, attrs, children) {
    var kids = (children || []).slice();
    var el = {
      tag: tag, attrs: attrs || {},
      appendChild: function (c) { kids.push(c); },
      querySelector: function () { return null; },
      setAttribute: function () {},
      addEventListener: function () {},
      focus: function () {},
      remove: function () {},
      classList: { add: function () {}, toggle: function () {} },
    };
    Object.defineProperty(el, 'children', { get: function () { return kids; } });
    Object.defineProperty(el, 'innerHTML', {
      get: function () { return ''; },
      set: function () { kids.length = 0; },
    });
    return el;
  }

  function emptyState(opts) { return { kind: 'empty', opts: opts }; }
  function errorState(opts) { return { kind: 'error', opts: opts }; }

  function buildChrome(name, title) {
    var titleEl = { textContent: title || '' };
    var body = makeBody();
    BODIES[name] = body;
    var panel = {
      querySelector: function (sel) { return sel === '.cr-dialog-title' ? titleEl : null; },
      focus: function () {},
      setAttribute: function () {},
      classList: { add: function () {} },
    };
    return { backdrop: {}, panel: panel, body: body, titleEl: titleEl };
  }

  var FOCUSABLE = 'a[href],button:not([disabled])';
  function trapFocus() { return function () {}; }

  var _layer = { appendChild: function () {}, setAttribute: function () {} };
  var _ctx = null;
  var _stack = [];

  %s
  %s
  %s
  %s
  %s
  %s

  var REGISTRY = {
    'directory-picker': renderDirectoryPicker,
    flags: renderFlagsList,
  };

  function dirPickerButtons() {
    // body._kids: [list-of-cwd-buttons, textfield-row] when cwds.length > 0
    var kids = BODIES['directory-picker'].children;
    var list = kids.length ? kids[0] : null;
    return list && list.children ? list.children : [];
  }
  function flagsRows() {
    var kids = BODIES.flags.children; // [the cr-flag-list div]
    var list = kids.length ? kids[0] : null;
    return list && list.children ? list.children : [];
  }

  // ---- scenario (a): the directory picker survives an unrelated poll broadcast ----
  var cwds = [{ path: '/proj/a', label: 'alpha' }, { path: '/proj/b', label: 'beta' }];
  open('directory-picker', { title: 'Choose a directory', cwds: cwds });
  var dpEntry = topEntry();
  OUT.dp_wants_poll = !!dpEntry.wantsPoll;
  OUT.dp_button_count_after_open = dirPickerButtons().length;
  OUT.dp_labels_after_open = dirPickerButtons().map(function (b) { return b.attrs.text; });

  // THE BUG, reproduced exactly through the REAL public seam (not the dialog's
  // own update() called directly) -- ext_cr_boot.js's SIDE_EXT hook broadcasts
  // this exact shape, kind:'poll' included, to whichever dialog is topmost.
  update({ kind: 'poll', flags: [{ id: 1, text: 'unrelated' }], sessions: [], now: 1234 });
  OUT.dp_button_count_after_poll = dirPickerButtons().length;
  OUT.dp_labels_after_poll = dirPickerButtons().map(function (b) { return b.attrs.text; });

  // A real re-open (fresh, larger cwds) must still land -- the fix must not make
  // the dialog inert to legitimate updates, only to broadcasts not meant for it.
  open('directory-picker', { title: 'Choose a directory', cwds: cwds.concat([{ path: '/proj/c', label: 'gamma' }]) });
  OUT.dp_button_count_after_real_reopen = dirPickerButtons().length;
  close();

  // ---- scenario (b): the flags dialog still legitimately receives {flags} ----
  open('flags', { flags: [] });
  var flagsEntry = topEntry();
  OUT.flags_wants_poll = !!flagsEntry.wantsPoll;
  OUT.flags_row_count_when_empty = flagsRows().length;
  OUT.flags_row_kind_when_empty = flagsRows()[0] && flagsRows()[0].kind;

  update({ kind: 'poll', flags: [{ id: 7, text: 'a' }, { id: 8, text: 'b' }], sessions: [], now: 999 });
  OUT.flags_row_count_after_first_poll = flagsRows().length;
  OUT.flags_row_class_after_first_poll = flagsRows()[0] && flagsRows()[0].attrs.class;

  update({ kind: 'poll', flags: [{ id: 9, text: 'c' }], sessions: [], now: 1000 });
  OUT.flags_row_count_after_second_poll = flagsRows().length;
  close();
})();
console.log("===POLL_SEAM_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (fn_top, fn_open, fn_close, fn_update, fn_dirpicker, fn_flags)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestPollBroadcastSeamProtectsUnoptedInDialogs(unittest.TestCase):
    """Pins the REAL open()/close()/update()/topEntry() seam plus
    renderDirectoryPicker()/renderFlagsList() against the exact shipped
    source in aitracker/web/ext_cr_dialogs.js."""

    @classmethod
    def setUpClass(cls):
        js = _driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Poll-broadcast-seam harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_directory_picker_did_not_opt_in_to_poll_data(self):
        self.assertFalse(self.OUT["dp_wants_poll"])

    def test_directory_picker_opens_with_the_real_directory_list(self):
        self.assertEqual(self.OUT["dp_button_count_after_open"], 2)
        self.assertEqual(self.OUT["dp_labels_after_open"], ["alpha", "beta"])

    def test_directory_picker_survives_the_seam_forwarded_poll_broadcast(self):
        """THE BUG, precisely: a {kind:'poll', flags, sessions, now} broadcast --
        delivered through the REAL public update() seam, not the dialog's own
        update() called directly -- must not blank the picker's list just
        because it happened to be topmost when the poll landed."""
        self.assertEqual(
            self.OUT["dp_button_count_after_poll"], 2,
            "an unrelated poll broadcast changed the directory picker's button count",
        )
        self.assertEqual(
            self.OUT["dp_labels_after_poll"], ["alpha", "beta"],
            "an unrelated poll broadcast clobbered the real directory list",
        )

    def test_directory_picker_still_accepts_a_real_reopen_after_surviving_a_poll(self):
        self.assertEqual(self.OUT["dp_button_count_after_real_reopen"], 3)

    def test_flags_dialog_opts_in_to_poll_data(self):
        """The one legitimate consumer -- must keep working after the fix."""
        self.assertTrue(self.OUT["flags_wants_poll"])
        self.assertEqual(self.OUT["flags_row_count_when_empty"], 1)
        self.assertEqual(self.OUT["flags_row_kind_when_empty"], "empty")

    def test_flags_dialog_keeps_receiving_poll_broadcasts_through_the_seam(self):
        self.assertEqual(
            self.OUT["flags_row_count_after_first_poll"], 2,
            "the flags dialog did not pick up {flags} from the poll-shaped broadcast",
        )
        self.assertEqual(self.OUT["flags_row_class_after_first_poll"], "cr-flag-row")
        self.assertEqual(
            self.OUT["flags_row_count_after_second_poll"], 1,
            "the flags dialog did not update again on a second poll-shaped broadcast",
        )


if __name__ == "__main__":
    unittest.main()
