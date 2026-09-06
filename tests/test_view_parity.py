"""Regression tests for two cross-view parity defects between classic (app.js/app.css) and
the control room (ext_cr_*), per the owner's ruling: "the session markers/pinned and other
pieces of information must be same in both the UIs."

DEFECT A -- todos rendered on control-room rail/tile rows (ext_cr_board.js railTodoLabel/
todoTicks, reading s.todo_done/s.todo_total) never surfaced on classic's session row
(app.js sessionRow()) -- only in the detail-pane progress ring. Fixed by adding a compact
"N/M" todobadge to sessionRow(), reading the same shared todo_done/todo_total fields every
provider (providers/claude.py, providers/auggie.py) already emits.

DEFECT B -- classic's pinned row (`app.css` `.sitem.pinned`) painted amber
(`var(--amber-bg)`) while the control room's pinned marker (`--state-pinned` in ext_cr.css,
aliased to `--text-dusk`) is blue, per the owner's explicit "pin -- blue" instruction. Fixed
by defining classic's own `--pin-blue`/`--pin-blue-bg` tokens in app.css (both themes, same
resolved hex values as ext_cr.css's --state-pinned) and using them on `.sitem.pinned`.

Idiom: static CSS-source checks (no node needed) for DEFECT B, mirroring
TestCollapsedRailAlignmentCss in tests/test_cr_rail_polish.py. DEFECT A is proven by running
the REAL bundle in node and calling sessionRow() directly as a global function (the whole
page is one <script> tag) -- the same technique test_cr_rail_polish.py's
TestRailRowBackgroundAgentsStillWorking uses for `sessionRow(bgWorking, now)` -- rather than
asserting on source text, since a previous agent's test that matched a comment instead of
real behaviour is exactly the failure mode this file must not repeat.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from aitracker import page

_HAS_NODE = shutil.which("node") is not None


def _read_page():
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return max(matches, key=lambda m: len(m.group(1))).group(1)


def _extract_style_content(html):
    matches = list(re.finditer(r'<style[^>]*>(.*?)</style>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <style> tag found in assembled page")
    return max(matches, key=lambda m: len(m.group(1))).group(1)


NOW = 1_700_000_000


def make_session(id, mtime, **overrides):
    """Real list-dict shape (registry.all_sessions()/providers/*), matching the fixture
    builder tests/test_cr_rail_polish.py already uses for the same session-dict shape."""
    s = {
        "id": id, "project": "proj", "cwd": "/tmp/proj", "title": "t", "prompt": "p",
        "source": "cli",
        "agent": False, "group": "", "groupLabel": "", "parentId": "",
        "bg": 0, "waiting": False, "ended": False, "mtime": mtime,
        "todo_total": 0, "todo_done": 0, "todo_current": None, "todo_current_index": None,
        "pr_num": None, "pr_url": None, "pr_repo": None, "pr_state": "",
        "now_line": "",
        "pinned": False, "note_count": 0, "open_flags": 0,
        "continued_as": "", "continued_from": "",
        "fail_cmd": None, "model": "",
    }
    s.update(overrides)
    return s


# ---------------------------------------------------------------------------
# DEFECT B -- pinned marker colour token: static CSS-source checks, no node needed.
# ---------------------------------------------------------------------------

class TestPinnedMarkerTokenParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())

    def test_pin_blue_defined_in_dark_default_root(self):
        # dark is the DEFAULT (bare :root, not html.light) in this file -- confirmed by
        # reading app.css's own :root/html.light split before writing this.
        self.assertIn("--pin-blue:#A8C0C9", self.css)

    def test_pin_blue_defined_in_light_theme(self):
        self.assertIn("--pin-blue:#395D6A", self.css)

    def test_pin_blue_bg_wash_defined_in_both_themes(self):
        self.assertIn("--pin-blue-bg:rgba(168,192,201,.16)", self.css)
        self.assertIn("--pin-blue-bg:rgba(57,93,106,.14)", self.css)

    def test_pinned_row_rule_uses_the_blue_token_not_amber(self):
        self.assertIn(".sitem.pinned{background:var(--pin-blue-bg)}", self.css)
        self.assertNotIn(".sitem.pinned{background:var(--amber-bg)}", self.css)

    def test_token_not_defined_in_only_one_theme_block(self):
        # A colour with only one definition would borrow the wrong theme's token whenever the
        # OTHER theme is active. Both hex values (dark #A8C0C9, light #395D6A) must each appear
        # exactly once as a --pin-blue assignment.
        self.assertEqual(self.css.count("--pin-blue:#A8C0C9"), 1)
        self.assertEqual(self.css.count("--pin-blue:#395D6A"), 1)


# ---------------------------------------------------------------------------
# DEFECT A -- compact todo progress on classic's session row, driven through the REAL
# sessionRow() global function in the real bundle (node), never asserted from source text.
# ---------------------------------------------------------------------------

_PREAMBLE = r"""
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {},
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; },
    querySelectorAll: () => [self],
    closest: function() { return self; },
    firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", value: "", hidden: false,
    focus() {}, click() {}, scrollIntoView() {}
  };
  return self;
}

var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(),
  createTextNode: () => makeEl(),
  getElementById: () => stubEl,
  querySelector: () => stubEl,
  querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl,
  readyState: "complete"
};

var _ls = {};
window.localStorage = {
  getItem: (k) => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; }
};

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => new Promise(() => {});
window.setInterval = () => 0;
window.setTimeout = () => 0;
window.clearInterval = () => {};
window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {};
window.removeEventListener = () => {};
window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});

try {
"""

_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""

_TAIL = r"""
var out = {};
out.withTodos = sessionRow(%(withTodos)s, %(now)d);
out.zeroTodos = sessionRow(%(zeroTodos)s, %(now)d);
out.absentTodos = sessionRow(%(absentTodos)s, %(now)d);
out.auggieWithTodos = sessionRow(%(auggieWithTodos)s, %(now)d);
console.log("===VIEW_PARITY_JSON_START===");
console.log(JSON.stringify(out));
"""


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _driver_js():
    bundle_js = _extract_script_content(_read_page())
    with_todos = make_session("s_todos", NOW - 5, todo_total=4, todo_done=1)
    zero_todos = make_session("s_zero", NOW - 5, todo_total=0, todo_done=0)
    absent_todos = make_session("s_absent", NOW - 5)
    del absent_todos["todo_total"]
    del absent_todos["todo_done"]
    auggie_with_todos = make_session("s_auggie", NOW - 5, source="auggie", todo_total=3, todo_done=2)
    tail = _TAIL % {
        "now": NOW,
        "withTodos": json.dumps(with_todos),
        "zeroTodos": json.dumps(zero_todos),
        "absentTodos": json.dumps(absent_todos),
        "auggieWithTodos": json.dumps(auggie_with_todos),
    }
    return "\n".join([_PREAMBLE, bundle_js, _MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestClassicSessionRowTodoBadge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "todo-badge driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout, "===VIEW_PARITY_JSON_START===")

    def test_session_with_todos_renders_the_progress_badge(self):
        html = self.OUT["withTodos"]
        self.assertIn('class=todobadge', html)
        self.assertIn("1/4", html)

    def test_zero_todo_total_renders_nothing(self):
        html = self.OUT["zeroTodos"]
        self.assertNotIn("todobadge", html)
        self.assertNotIn("0/0", html)
        self.assertNotIn("undefined", html)

    def test_absent_todo_fields_render_nothing(self):
        html = self.OUT["absentTodos"]
        self.assertNotIn("todobadge", html)
        self.assertNotIn("undefined", html)
        self.assertNotIn("NaN", html)

    def test_auggie_session_gets_the_badge_too(self):
        html = self.OUT["auggieWithTodos"]
        self.assertIn('class=todobadge', html)
        self.assertIn("2/3", html)


if __name__ == "__main__":
    unittest.main()
