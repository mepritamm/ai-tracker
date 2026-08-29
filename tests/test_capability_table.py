"""Fix 5 (design_handoff_control_room/04-coverage-and-help.md): "Generate the
capability table from the same data structure the tests assert against ... That is
what keeps Help from drifting from what shipped."

Before this test, `CR.dialogs.CAPABILITIES` (aitracker/web/ext_cr_dialogs.js) was a
JS-only literal no test referenced, and the Help dialog's Coverage tab rendered a
SEPARATE, hand-typed "58" next to it, even though the array itself lists 60 entries
(#1-#60 of doc 04's capability map, including the two rows the doc marks New: the
Config dialog and the progress spine — both genuinely shipped). That is the drift the
doc's own instruction exists to prevent, and the audit caught it live (Help said "58"
while the map has 60).

Reconciled by deriving the Coverage tab's stat number from `CAPABILITIES.length`
instead of repeating the doc's stale literal (see ext_cr_dialogs.js's helpCoverageTab).
This test pins the truth on both sides of that reconciliation:

  1. CR.dialogs.CAPABILITIES exists, is non-empty, and every entry has the three
     required fields (a numeric id, a non-empty label, a non-empty owner module tag).
  2. Its length is exactly 60 -- the real, reconciled count.
  3. The rendered Coverage-tab stat (built by helpCoverageTab(), invoked the same way
     a real "?" press would via CR.dialogs.open('help', {})) shows that SAME number,
     not a stale hardcoded one -- so deleting an entry from CAPABILITIES, or
     reintroducing a hardcoded literal in the render path, makes this go red.

This runs the REAL assembled bundle (aitracker/page.py's build_page()) under Node,
the same "confirm the actual shipped code, don't guess" approach test_page_bundle.py
already uses -- with its own small DOM stub (below) that, unlike test_page_bundle's,
keeps a REAL parent/child tree so the rendered stat text can be read back out.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    import re
    matches = list(re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL))
    if not matches:
        raise ValueError("No <script> tag found in assembled page")
    return matches[-1].group(1)


# A minimal but REAL DOM: unlike test_page_bundle.py's stub (one shared element,
# appendChild a no-op), createElement here returns a fresh object each call and
# appendChild really appends -- enough for CR.dialogs.open('help', {}) to build a
# genuine, walkable tree so this test can read the rendered stat text back out.
_JS_HARNESS = r"""
globalThis.window = globalThis;

function makeEl(tag) {
  var self = {
    tag: tag, className: "", attrs: {}, children: [],
    style: {}, dataset: {}, textContent: "", innerHTML: "", hidden: false,
    classList: {
      add: function (c) { if ((" " + self.className + " ").indexOf(" " + c + " ") < 0) self.className = (self.className + " " + c).trim(); },
      remove: function () {}, toggle: function () {},
      contains: function (c) { return (" " + self.className + " ").indexOf(" " + c + " ") >= 0; }
    },
    setAttribute: function (k, v) { self.attrs[k] = v; },
    getAttribute: function (k) { return (k in self.attrs) ? self.attrs[k] : null; },
    appendChild: function (c) { self.children.push(c); return c; },
    append: function () { for (var i = 0; i < arguments.length; i++) self.appendChild(arguments[i]); },
    remove: function () {},
    insertBefore: function (n) { self.children.push(n); },
    addEventListener: function () {},
    removeEventListener: function () {},
    querySelector: function (sel) { return findFirstByClass(self, lastClass(sel)); },
    querySelectorAll: function (sel) { var r = []; collectByClass(self, lastClass(sel), r); return r; },
    closest: function () { return null; },
    focus: function () {},
    click: function () {}
  };
  Object.defineProperty(self, "firstElementChild", { get: function () { return self.children[0] || null; } });
  return self;
}
function makeText(text) { return { tag: "#text", className: "", children: [], textContent: String(text == null ? "" : text) }; }
function lastClass(sel) {
  if (typeof sel !== "string") return null;
  var m = sel.trim().split(/\s+/).pop();
  return (m && m.charAt(0) === ".") ? m.slice(1) : null;
}
function findFirstByClass(node, cls) {
  if (!cls) return null;
  if (node.className && (" " + node.className + " ").indexOf(" " + cls + " ") >= 0) return node;
  for (var i = 0; i < (node.children || []).length; i++) {
    var r = findFirstByClass(node.children[i], cls);
    if (r) return r;
  }
  return null;
}
function collectByClass(node, cls, out) {
  if (!cls) return;
  if (node.className && (" " + node.className + " ").indexOf(" " + cls + " ") >= 0) out.push(node);
  (node.children || []).forEach(function (c) { collectByClass(c, cls, out); });
}
function textOf(node) {
  if (!node) return "";
  var s = node.textContent || "";
  (node.children || []).forEach(function (c) { s += textOf(c); });
  return s;
}

var _docActiveElement = null;
window.document = {
  createElement: function (tag) { return makeEl(tag); },
  createElementNS: function (_ns, tag) { return makeEl(tag); },
  createTextNode: function (t) { return makeText(t); },
  getElementById: function () { return makeEl("div"); },
  querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  addEventListener: function () {},
  dispatchEvent: function () {},
  get activeElement() { return _docActiveElement; },
  documentElement: makeEl("html"),
  body: makeEl("body"),
  head: makeEl("head"),
  readyState: "complete",
  hidden: false
};

var _localStorage = {};
window.localStorage = {
  getItem: function (k) { return Object.prototype.hasOwnProperty.call(_localStorage, k) ? _localStorage[k] : null; },
  setItem: function (k, v) { _localStorage[k] = String(v); },
  removeItem: function (k) { delete _localStorage[k]; }
};
window.matchMedia = function () { return { matches: false, addEventListener: function () {}, addListener: function () {}, removeEventListener: function () {} }; };
window.fetch = function () { return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); }, text: function () { return Promise.resolve(""); }, headers: { get: function () { return null; } } }); };
window.setInterval = function () { return 0; };
window.setTimeout = function () { return 0; };
window.clearInterval = function () {};
window.clearTimeout = function () {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: function () { return Promise.resolve(); } } };
window.CustomEvent = function (type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = function () { return 0; };
window.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
window.getSelection = function () { return { toString: function () { return ""; } }; };
window.addEventListener = function () {};
window.removeEventListener = function () {};
window.dispatchEvent = function () {};

process.on("unhandledRejection", function () {});

try {
"""

_JS_TAIL = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}

if (!window.CR || !window.CR.dialogs) {
  console.error("CR.dialogs not present after bundle execution");
  process.exit(1);
}

// Render the Help dialog's Coverage tab for real, in a root this script can walk.
var testRoot = makeEl("div");
var bus = {};
var testCtx = {
  on: function (name, fn) { (bus[name] = bus[name] || []).push(fn); },
  emit: function (name, payload) { (bus[name] || []).forEach(function (fn) { fn(payload); }); },
  theme: { get: function () { return "auto"; } }
};
window.CR.dialogs.mount(testRoot, testCtx);
window.CR.dialogs.open("help", {});

var statEl = findFirstByClass(testRoot, "cr-stat-num");
var statText = statEl ? textOf(statEl).trim() : null;

console.log("CAPS_JSON:" + JSON.stringify(window.CR.dialogs.CAPABILITIES));
console.log("STAT_TEXT:" + statText);
console.log("CAPTABLE-OK");
"""


def _run_node(js_source):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "captable_harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


def _capture(full_js):
    returncode, stdout, stderr = _run_node(full_js)
    caps = None
    stat_text = None
    for line in stdout.splitlines():
        if line.startswith("CAPS_JSON:"):
            caps = json.loads(line[len("CAPS_JSON:"):])
        elif line.startswith("STAT_TEXT:"):
            stat_text = line[len("STAT_TEXT:"):]
    return returncode, stdout, stderr, caps, stat_text


class TestCapabilityTable(unittest.TestCase):
    """Pins CR.dialogs.CAPABILITIES against what Help's Coverage tab actually shows."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_capability_table_matches_help_display(self):
        html = _read_page()
        js = _extract_script_content(html)
        full_js = _JS_HARNESS + js + _JS_TAIL

        returncode, stdout, stderr, caps, stat_text = _capture(full_js)

        self.assertEqual(
            returncode, 0,
            f"Harness failed (exit {returncode})\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )
        self.assertIsNotNone(caps, f"CAPS_JSON line not found.\n--- stdout ---\n{stdout}")
        self.assertTrue(caps, "CR.dialogs.CAPABILITIES is empty")

        for entry in caps:
            self.assertEqual(len(entry), 3, f"capability entry missing a field: {entry!r}")
            cap_id, label, owner = entry
            self.assertIsInstance(cap_id, int)
            self.assertIsInstance(label, str)
            self.assertTrue(label.strip(), f"capability {cap_id} has a blank label")
            self.assertIsInstance(owner, str)
            self.assertTrue(owner.strip(), f"capability {cap_id} has a blank owner")

        # The reconciled truth (Fix 5): the doc's capability map lists 60 items,
        # including the two rows it marks New (Config dialog, progress spine) which
        # both genuinely shipped -- so 60, not the doc's stale "58", is correct.
        self.assertEqual(len(caps), 60, "CR.dialogs.CAPABILITIES should list all 60 documented capabilities")

        # The number Help's own Coverage tab renders must be the SAME number --
        # this is the drift the doc's instruction exists to prevent.
        self.assertEqual(
            stat_text, str(len(caps)),
            f"Help's Coverage tab shows {stat_text!r} but CR.dialogs.CAPABILITIES has {len(caps)} entries"
        )


if __name__ == "__main__":
    unittest.main()
