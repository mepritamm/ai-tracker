"""Regression test: the assembled page's JS bundle executes without load-time errors.

When aitracker/page.py's build_page() inlines app.js plus every ext_*.js into ONE <script>
tag, a load-time throw in any file halts execution of all files after it, blanking the whole
dashboard. This test catches two classes of errors:

1. BUNDLE-EXEC: a JS syntax error or load-time throw (e.g., ReferenceError: CR is not defined).
2. STATIC-CR-ASSIGNMENT: a bare CR.* assignment at line start (e.g., `CR.detail = {...}` instead
   of `window.CR.detail = {...}`), which would throw if executed in the bundle's global scope.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")
_HAS_NODE = shutil.which("node") is not None


def _read_page():
    """Import and run build_page() to get the assembled HTML."""
    import sys
    sys.path.insert(0, os.path.dirname(_AITRACKER))
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    """Extract the text inside the LAST <script>...</script> HTML tag.

    Use regex to avoid false matches with <script> inside comments/strings.
    """
    # Find all actual HTML <script> tags (not ones in comments).
    # Match <script> or <script [attributes]>, but only when it's an HTML tag.
    script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    matches = list(script_pattern.finditer(html))

    if not matches:
        raise ValueError("No <script> tag found in assembled page")

    # Return the content of the LAST script tag.
    return matches[-1].group(1)


def _run_node(js_source):
    """Write js_source to a temp file and run it with node. Return True if exit code is 0."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


_JS_PREAMBLE = r"""
// Minimal browser environment for bundle execution.
globalThis.window = globalThis;

// Factory for DOM elements.
function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {},
    dataset: {},
    setAttribute() {},
    getAttribute() { return null; },
    appendChild() {},
    append() {},
    remove() {},
    insertBefore() {},
    addEventListener() {},
    removeEventListener() {},
    querySelector: function() { return self; },
    querySelectorAll: () => [self],
    closest: function() { return self; },
    firstElementChild: self,
    children: [self],
    innerHTML: "",
    textContent: "",
    hidden: false,
    focus() {},
    click() {}
  };
  return self;
}

// Stub document.
var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(),
  createTextNode: () => makeEl(),
  getElementById: () => stubEl,
  querySelector: () => stubEl,
  querySelectorAll: () => [stubEl],
  addEventListener() {},
  dispatchEvent() {},
  documentElement: stubEl,
  body: stubEl,
  head: stubEl,
  readyState: "complete"
};

// localStorage backed by an object.
const _localStorage = {};
window.localStorage = {
  getItem: (k) => _localStorage[k] || null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};

// matchMedia stub.
window.matchMedia = () => ({
  matches: false,
  addEventListener() {},
  addListener() {},
  removeEventListener() {}
});

// fetch stub.
window.fetch = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve({}),
  text: () => Promise.resolve(""),
  headers: { get: () => null }
});

// Timers as no-ops (prevents polling).
window.setInterval = () => 0;
window.setTimeout = () => 0;
window.clearInterval = () => {};
window.clearTimeout = () => {};

// location stub.
window.location = { href: "", search: "", pathname: "/" };

// navigator stub.
window.navigator = {
  userAgent: "node",
  clipboard: { writeText: () => Promise.resolve() }
};

// Events.
window.CustomEvent = class {
  constructor(type, opts) { this.type = type; this.detail = opts?.detail; }
};
window.Event = window.CustomEvent;

// Animation frame stub.
window.requestAnimationFrame = () => 0;

// Style computation stub.
window.getComputedStyle = () => ({ getPropertyValue: () => "" });

// Selection stub.
window.getSelection = () => ({ toString: () => "" });

// Global event listeners (not on objects).
window.addEventListener = () => {};
window.removeEventListener = () => {};
window.dispatchEvent = () => {};

// URLSearchParams is built-in to node.
// console is built-in to node.

// Catch any unhandled promise rejections from async startup (e.g., fetch promises).
process.on("unhandledRejection", () => {});

try {
"""

_JS_EPILOGUE = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}

// Verify all CR modules registered correctly.
var missing = [];
["board", "detail", "dialogs", "term"].forEach(function(k) {
  var m = window.CR && window.CR[k];
  if (!m) {
    missing.push(k + " (absent)");
    return;
  }
  if (typeof m.mount !== "function") missing.push(k + ".mount (not a function)");
  if (typeof m.update !== "function") missing.push(k + ".update (not a function)");
});
if (missing.length) {
  console.error("MISSING: " + missing.join(", "));
  process.exit(1);
}
console.log("BUNDLE-OK");
"""


class TestPageBundle(unittest.TestCase):
    """Test that the assembled page's JS bundle executes without load-time errors."""

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_bundle_executes(self):
        """Call build_page(), extract its JS, and verify it runs without errors."""
        html = _read_page()
        js = _extract_script_content(html)

        # Wrap the bundle with preamble and epilogue.
        full_js = _JS_PREAMBLE + js + _JS_EPILOGUE

        returncode, stdout, stderr = _run_node(full_js)

        # Check for success marker in output.
        has_ok = "BUNDLE-OK" in stdout
        self.assertEqual(
            returncode, 0,
            f"Bundle execution failed (exit {returncode})\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )
        self.assertTrue(
            has_ok,
            f"Success marker 'BUNDLE-OK' not found in output.\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
        )

    def test_no_bare_cr_assignments(self):
        """Scan ext_cr_*.js files for bare CR. assignments (missing window. prefix)."""
        # Regex to find `CR.` at the start of a line (after whitespace).
        bare_cr_pattern = re.compile(r"^\s*CR\.\w+\s*=", re.MULTILINE)

        failed_files = []
        for name in sorted(os.listdir(_WEB)):
            if not (name.startswith("ext_cr_") and name.endswith(".js")):
                continue
            path = os.path.join(_WEB, name)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()

            # Find all bare CR assignments.
            for match in bare_cr_pattern.finditer(content):
                line_num = content[:match.start()].count("\n") + 1
                failed_files.append(f"{name}:{line_num}: {match.group()}")

        self.assertEqual(
            failed_files, [],
            f"Found bare CR. assignments (missing window. prefix):\n" +
            "\n".join(f"  {f}" for f in failed_files)
        )

    def test_script_block_count(self):
        """Assert the assembled page has exactly 2 <script> blocks.

        The page consists of:
          1. index.html's theme init script (line 6)
          2. The main app bundle (placeholder __JS__ on line 186 gets filled)

        A higher count signals that the closing script tag bug broke the inlined
        <script> tag, causing the browser to prematurely close it and spawn new ones.
        """
        html = _read_page()
        script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
        script_blocks = list(script_pattern.finditer(html))

        self.assertEqual(
            len(script_blocks), 2,
            f"Expected 2 <script> blocks, found {len(script_blocks)}. "
            f"A count > 2 indicates the closing script tag bug: a literal </script> "
            f"inside a comment or string in a .js file terminated the inlined <script> "
            f"early, causing multiple <script> blocks instead of one bundle. "
            f"Check aitracker/web/*.js for </script> in comments/strings."
        )

    def test_no_closing_script_in_js_files(self):
        """Scan all aitracker/web/*.js files for the literal </script> tag.

        If any .js file contains </script> (even in a comment or string), it will
        terminate the inlined <script> tag in the assembled HTML, causing a
        SyntaxError and breaking the dashboard silently. This test catches the bug
        at its source by checking the source files.
        """
        failed_files = []
        for name in sorted(os.listdir(_WEB)):
            if not name.endswith(".js"):
                continue
            path = os.path.join(_WEB, name)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()

            # Find all occurrences of the literal closing script tag.
            for i, line in enumerate(content.split("\n"), start=1):
                if "</script>" in line:
                    # Extract the offending text for clarity.
                    snippet = line.strip()[:60]
                    failed_files.append(f"{name}:{i}: {snippet}")

        self.assertEqual(
            failed_files, [],
            f"Found closing </script> tag in .js file(s) — this terminates the inlined "
            f"<script> and breaks every module after it:\n" +
            "\n".join(f"  {f}" for f in failed_files)
        )


if __name__ == "__main__":
    unittest.main()
