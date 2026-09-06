"""Regression tests for the "rail row parity" change to the control-room
session rail (ext_cr_board.js / ext_cr_board.css):

1. THE BUG: `.cr-rail-row` used to be `display:flex; align-items:center` (one
   horizontal line) with `.cr-rail-meta` pinned `flex: 0 0 auto` (never
   shrinks). Once the project+source labels joined the meta line, meta ate
   the rail width and `.cr-rail-titlewrap` (flex:1) collapsed to 1-2
   characters, so session titles rendered as "A"/"f." or vanished. FIX: the
   row is now `flex-direction: column`; the title line is a new
   `.cr-rail-r1` block; `.cr-rail-titlewrap` is GONE; `.cr-rail-meta` is
   `display: block` and must not carry `flex: 0 0 auto` again.

2. Rail rows now render VISIBLE flag/note badges on the TITLE line
   (`.cr-rail-badge--flag` / `--note`), which previously only existed as
   text in the meta line and the tooltip. `railRowMeta()` must no longer
   emit the flag or note counts (it still emits age and, when `s.bg`, a
   "N running" chip) -- otherwise those counts are double-reported.

3. Those badges are BUTTONS: the flag badge emits bus event `open:flags`;
   the note badge and the `.cr-rail-badge--bg` chip call `openSession(s.id)`
   (-> `ctx.go('detail', id)`). All three call `e.stopPropagation()` so
   clicking one does not ALSO fire the row's own click handler (which would
   otherwise navigate a second time via the row's own `openSession` call).

4. `computeAgentParentIds(sessions, now)` now returns, per parent id, an
   object `{n, live}` (was a bare `true`), and a parent row renders a "kid
   chip" (`.cr-rail-badge--kids`) reading e.g. "2 live / 5 agents" (the live
   share omitted when zero). Both call sites (the rail's `renderRail` and
   the Sessions destination's `renderSessionsView`) pass `now`.

5. A done/completed row now takes a GREEN BACKGROUND:
   `.cr-rail-row--done` gets `background: var(--surface-done)` in addition
   to its existing `border-left: 3px solid var(--line-done)`.

Idiom reused verbatim in spirit from tests/test_cr_rail_polish.py:
`_read_page()`, `_extract_script_content(html)`, `_extract_style_content(html)`,
`_run_node(js_source)`, `make_session(id, mtime, **overrides)`, the fixed
`NOW` clock, the `_HAS_NODE` skip guard, and the hand-rolled DOM stub
(`makeReal`/`queryAllReal`/`allTextIn`) that drives the REAL `railRow()`
render through `window.CR.board.mount()`/`.update()` -- never a no-op stub,
since what's under test here only exists inside an actual render. The stub's
`addEventListener` is extended (beyond test_cr_rail_polish.py's no-op) to
actually RECORD the handler, so this file can additionally simulate a real
click (with bubbling) on a badge button -- needed for requirement 3, which
no existing test drives.
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
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)

NOW = 1_700_000_000  # fixed epoch seconds, matches tests/test_cr_logic.py's own fixture clock


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_style_content(html):
    m = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
    if not m:
        raise AssertionError("No <style> tag found in assembled page")
    return m.group(1)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def make_session(id, mtime, **overrides):
    """Real list-dict shape (registry.all_sessions() / providers/claude.py
    list_sessions()), matching tests/test_cr_logic.py's own fixture builder."""
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
# Hand-rolled DOM harness -- same technique as test_cr_rail_polish.py /
# test_cr_logic.py's TestCRFailingTileRender, extended with a REAL
# addEventListener (records the handler instead of discarding it) so clicks
# on rail badges can actually be simulated, with bubbling, for requirement 3.
# ---------------------------------------------------------------------------

_REAL_DOM_PREAMBLE = r"""
globalThis.window = globalThis;

function makeDummy() {
  var self = {
    classList: { add: function () {}, remove: function () {}, toggle: function () { return false; }, contains: function () { return false; } },
    style: {}, dataset: {},
    setAttribute: function () {}, getAttribute: function () { return null; }, removeAttribute: function () {},
    appendChild: function (c) { return c; }, append: function () {}, remove: function () {}, insertBefore: function (c) { return c; },
    addEventListener: function () {}, removeEventListener: function () {},
    querySelector: function () { return self; }, querySelectorAll: function () { return [self]; },
    closest: function () { return self; }, firstElementChild: null, children: [],
    innerHTML: "", textContent: "", value: "", hidden: false,
    focus: function () {}, click: function () {}, scrollIntoView: function () {}
  };
  return self;
}
var dummy = makeDummy();

function queryAllReal(root, sel) {
  var out = [];
  if (!sel || sel.charAt(0) !== '.') return out;
  var cls = sel.slice(1);
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (c && c._classes && c._classes.has(cls)) out.push(c);
      walk(c);
    });
  })(root);
  return out;
}

// data-id lookup (used by the kid-chip / cross-view-parity tests below) --
// queryAllReal only matches class selectors, so a separate walk is needed.
function findRowById(root, id) {
  var found = null;
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (!found && c && c._attrs && c._attrs['data-id'] === id) { found = c; }
      if (!found) walk(c);
    });
  })(root);
  return found;
}

function allTextIn(node) {
  var out = [];
  (function walk(n) {
    // makeReal() uppercases every tag (`String(tag).toUpperCase()`), so a
    // text node created via `document.createTextNode('#text')` carries
    // tagName '#TEXT', never the lowercase DOM convention.
    if (n.tagName === '#TEXT') { out.push(n.textContent || ''); return; }
    (n._children || []).forEach(walk);
  })(node);
  return out.join('');
}

// Simulates a real click, WITH bubbling: fires the target's own listener
// first, then each ancestor's in turn, stopping the instant a handler calls
// stopPropagation() -- exactly the semantics requirement 3 depends on (a
// badge's own handler stops the row's own click/openSession from also
// firing). Returns whether propagation was stopped.
function simulateClick(el) {
  var stopped = false;
  var evt = { stopPropagation: function () { stopped = true; } };
  var node = el;
  while (node) {
    if (node._listeners && node._listeners.click) node._listeners.click(evt);
    if (stopped) break;
    node = node.parentNode;
  }
  return stopped;
}

function makeReal(tag) {
  var el = {
    tagName: String(tag || 'div').toUpperCase(),
    _classes: new Set(),
    _children: [],
    _attrs: {},
    _id: '',
    style: {}, dataset: {},
    hidden: false, innerHTML: '', textContent: '', value: '',
    parentNode: null
  };
  el.classList = {
    add: function () { for (var i = 0; i < arguments.length; i++) if (arguments[i]) el._classes.add(arguments[i]); },
    remove: function () { for (var i = 0; i < arguments.length; i++) el._classes.delete(arguments[i]); },
    toggle: function (c, force) {
      var has = el._classes.has(c);
      var want = (force === undefined) ? !has : !!force;
      if (want) el._classes.add(c); else el._classes.delete(c);
      return want;
    },
    contains: function (c) { return el._classes.has(c); }
  };
  Object.defineProperty(el, 'className', {
    get: function () { return Array.from(el._classes).join(' '); },
    set: function (v) { el._classes = new Set(String(v == null ? '' : v).split(/\s+/).filter(Boolean)); }
  });
  Object.defineProperty(el, 'id', {
    get: function () { return el._id; },
    set: function (v) { el._id = v; if (v) _idRegistry[v] = el; }
  });
  var _innerHTML = '';
  Object.defineProperty(el, 'innerHTML', {
    get: function () { return _innerHTML; },
    set: function (v) {
      _innerHTML = v;
      if (v === '') { el._children.forEach(function (c) { c.parentNode = null; }); el._children = []; }
    }
  });
  el.setAttribute = function (k, v) { el._attrs[k] = v; if (k === 'class') el.className = v; if (k === 'id') el.id = v; };
  el.getAttribute = function (k) { return (k in el._attrs) ? el._attrs[k] : null; };
  el.removeAttribute = function (k) { delete el._attrs[k]; };
  el.appendChild = function (c) { if (c) { el._children.push(c); c.parentNode = el; } return c; };
  el.append = function () { for (var i = 0; i < arguments.length; i++) el.appendChild(arguments[i]); };
  el.insertBefore = function (c) { if (c) { el._children.push(c); c.parentNode = el; } return c; };
  el.removeChild = function (c) { var idx = el._children.indexOf(c); if (idx >= 0) el._children.splice(idx, 1); return c; };
  el.remove = function () { if (el.parentNode) el.parentNode.removeChild(el); };
  // EXTENDED beyond test_cr_rail_polish.py's no-op: actually records the
  // handler (single slot per event type is enough for this file's needs) so
  // simulateClick() above can invoke it -- required to exercise requirement
  // 3 (bus event + stopPropagation) through a REAL click, not a string check.
  el._listeners = {};
  el.addEventListener = function (type, fn) { el._listeners[type] = fn; };
  el.removeEventListener = function (type) { if (el._listeners) delete el._listeners[type]; };
  el.focus = function () {}; el.click = function () {}; el.scrollIntoView = function () {};
  el.querySelectorAll = function (sel) { return queryAllReal(el, sel); };
  el.querySelector = function (sel) { return queryAllReal(el, sel)[0] || null; };
  el.closest = function () { return null; };
  Object.defineProperty(el, 'firstElementChild', { get: function () { return el._children[0] || null; } });
  Object.defineProperty(el, 'lastChild', { get: function () { return el._children[el._children.length - 1] || null; } });
  Object.defineProperty(el, 'children', { get: function () { return el._children.slice(); } });
  return el;
}

var _idRegistry = {};
var docBody = makeReal('body');

window.document = {
  createElement: function (tag) { return makeReal(tag); },
  createElementNS: function (ns, tag) { return makeReal(tag); },
  createTextNode: function (text) { var t = makeReal('#text'); t.textContent = text; return t; },
  getElementById: function (id) { return _idRegistry[id] || dummy; },
  querySelector: function (sel) { return queryAllReal(docBody, sel)[0] || null; },
  querySelectorAll: function (sel) { return queryAllReal(docBody, sel); },
  addEventListener: function () {}, removeEventListener: function () {}, dispatchEvent: function () {},
  documentElement: dummy, body: docBody, head: dummy, readyState: "complete"
};

var _STORAGE = {};
window.localStorage = {
  getItem: function (k) { return (k in _STORAGE) ? _STORAGE[k] : null; },
  setItem: function (k, v) { _STORAGE[k] = String(v); },
  removeItem: function (k) { delete _STORAGE[k]; }
};
window.matchMedia = function () { return { matches: false, addEventListener: function () {}, addListener: function () {}, removeEventListener: function () {} }; };
window.fetch = function () { return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); }, text: function () { return Promise.resolve(""); }, headers: { get: function () { return null; } } }); };
window.setTimeout = function () { return 0; };
window.setInterval = function () { return 0; };
window.clearInterval = function () {}; window.clearTimeout = function () {};
window.location = { href: "", search: "", pathname: "/", host: "localhost" };
window.navigator = { userAgent: "node", clipboard: { writeText: function () { return Promise.resolve(); } } };
window.CustomEvent = function (type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = function () { return 0; };
window.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
window.getSelection = function () { return { toString: function () { return ""; } }; };
window.addEventListener = function () {}; window.removeEventListener = function () {}; window.dispatchEvent = function () {};
window.URLSearchParams = function () { return { get: function () { return null; } }; };
process.on("unhandledRejection", function () {});

try {
"""

_REAL_DOM_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


def _bundle_js():
    return _extract_script_content(_read_page())


# ---------------------------------------------------------------------------
# FIX 1 -- the rail row's flex layout (source-text level: no node needed).
# ---------------------------------------------------------------------------

class TestRailRowColumnLayoutCss(unittest.TestCase):
    """THE BUG: `.cr-rail-row` was one horizontal flex line with
    `.cr-rail-meta` pinned `flex: 0 0 auto` -- meta ate the row's width the
    instant project+source joined it, collapsing the title to 1-2 chars.
    Pins the CSS-level fix: the row is now a column flex container, the meta
    block is a plain block that can wrap, and `.cr-rail-titlewrap` is gone."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())

    def _rule_block(self, selector):
        selector = selector.rstrip().rstrip('{').rstrip()
        m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, "rule %r not found in assembled CSS" % selector)
        return m.group(1)

    def test_row_is_column_flex_not_the_old_single_line(self):
        block = self._rule_block(".tracker-next .cr-rail-row {")
        self.assertIn("flex-direction: column", block)

    def test_meta_is_block_display_and_never_flex_shrink_locked_again(self):
        block = self._rule_block(".tracker-next .cr-rail-meta {")
        self.assertIn("display: block", block)
        self.assertNotIn("flex: 0 0 auto", block)

    def test_titlewrap_rule_no_longer_exists(self):
        """`.cr-rail-titlewrap` is gone -- the title is a direct child of the
        new `.cr-rail-r1` row instead. Matches on an actual RULE (selector
        immediately followed by `{`), not the bare substring, since the
        removal is itself documented in a CSS comment that still mentions
        the class name by name."""
        self.assertIsNone(re.search(r'\.cr-rail-titlewrap\s*\{', self.css))

    def test_r1_title_line_rule_exists(self):
        block = self._rule_block(".tracker-next .cr-rail-r1 {")
        self.assertIn("display: flex", block)

    def test_done_row_gets_green_surface_background_plus_its_border(self):
        block = self._rule_block(".tracker-next .cr-rail-row--done {")
        self.assertIn("background: var(--surface-done)", block)
        self.assertIn("border-left: 3px solid var(--line-done)", block)


# ---------------------------------------------------------------------------
# FIX 1, continued -- the same restack, proven through a REAL RENDER (DOM
# structure), not just the source CSS above.
# ---------------------------------------------------------------------------

_STRUCTURE_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: [%(session)s], now: %(now)d });

var row = queryAllReal(root, '.cr-rail-row')[0];
var out = {};
out.hasTitlewrap = queryAllReal(row, '.cr-rail-titlewrap').length > 0;
out.r1Classes = row._children.length ? Array.from(row._children[0]._classes) : [];
out.metaIsSeparateFromR1 = queryAllReal(row, '.cr-rail-r1 .cr-rail-meta').length === 0
  && queryAllReal(row, '.cr-rail-meta').length === 1;

console.log("===CR_STRUCT_JSON_START===");
console.log(JSON.stringify(out));
"""


def _structure_driver_js():
    session = make_session("struct_1", NOW - 5, ended=False, title="A somewhat long session title")
    tail = _STRUCTURE_JS_TAIL % {"session": json.dumps(session), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])


def _extract_marker_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowStructuralRestack(unittest.TestCase):
    """Drives the REAL railRow() render (mount -> update -> DOM) and checks
    the actual element structure it produced, rather than only the source
    CSS: no `.cr-rail-titlewrap` element anywhere in the row, and the new
    `.cr-rail-r1` title line is a SIBLING of `.cr-rail-meta`, not its
    ancestor -- the structural half of the fix a CSS-only check can't see
    (there is no layout engine in this harness to prove the visual
    consequence, but the element tree the fix actually rewired is real)."""

    @classmethod
    def setUpClass(cls):
        js = _structure_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Structure driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_STRUCT_JSON_START===")

    def test_no_titlewrap_element_in_the_rendered_row(self):
        self.assertFalse(self.OUT["hasTitlewrap"], "a .cr-rail-titlewrap element still rendered")

    def test_r1_title_line_is_the_rows_first_child(self):
        self.assertIn("cr-rail-r1", self.OUT["r1Classes"])

    def test_meta_is_a_sibling_of_r1_not_nested_inside_it(self):
        self.assertTrue(self.OUT["metaIsSeparateFromR1"])


# ---------------------------------------------------------------------------
# FIX 2 -- flag/note counts moved OFF the meta line and onto visible title-
# line badges; railRowMeta() must not double-report them.
# ---------------------------------------------------------------------------

_META_BADGES_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: [%(session)s], now: %(now)d });

var row = queryAllReal(root, '.cr-rail-row')[0];
var meta = queryAllReal(row, '.cr-rail-meta')[0];
var flagBadges = queryAllReal(row, '.cr-rail-badge--flag');
var noteBadges = queryAllReal(row, '.cr-rail-badge--note');
var bgBadges = queryAllReal(row, '.cr-rail-badge--bg');

var out = {};
out.metaText = meta ? allTextIn(meta) : null;
out.flagBadgeText = flagBadges.length ? allTextIn(flagBadges[0]) : null;
out.noteBadgeText = noteBadges.length ? allTextIn(noteBadges[0]) : null;
out.bgBadgeText = bgBadges.length ? allTextIn(bgBadges[0]) : null;

console.log("===CR_METABADGE_JSON_START===");
console.log(JSON.stringify(out));
"""


def _meta_badges_driver_js():
    # Non-default values throughout, per the load-bearing requirement:
    # open_flags=2, note_count=3, bg=4 -- a fixture where every one of those
    # fields defaulting to 0 (as make_session() does) would make this
    # vacuous.
    session = make_session(
        "meta_badges_1", NOW - 5,
        ended=False, open_flags=2, note_count=3, bg=4, flag_text="needs review",
    )
    tail = _META_BADGES_JS_TAIL % {"session": json.dumps(session), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowMetaAndBadgesNoDoubleReport(unittest.TestCase):
    """A session with open_flags=2, note_count=3 and bg=4 (all non-default):
    the flag/note counts must show up ONCE, as real clickable badges on the
    title line -- and must NOT also appear as text in the meta line, which
    would double-report the same information. The meta line still owes the
    age and the background-agent "N running" chip."""

    @classmethod
    def setUpClass(cls):
        js = _meta_badges_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Meta/badges driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_METABADGE_JSON_START===")

    def test_meta_line_no_longer_mentions_flags_or_notes(self):
        meta = self.OUT["metaText"]
        self.assertIsNotNone(meta, "meta line did not render")
        self.assertNotIn("flag", meta.lower(), "meta line still mentions flags: %r" % meta)
        self.assertNotIn("note", meta.lower(), "meta line still mentions notes: %r" % meta)

    def test_meta_line_still_reports_age_and_the_bg_running_chip(self):
        meta = self.OUT["metaText"]
        self.assertIn("just now", meta)   # mtime is NOW-5, well inside "just now"
        self.assertIn("4 running", meta)  # s.bg == 4, classic's own bgchip wording

    def test_flag_badge_renders_on_the_title_line_with_its_count(self):
        self.assertIsNotNone(self.OUT["flagBadgeText"], ".cr-rail-badge--flag did not render")
        self.assertIn("2", self.OUT["flagBadgeText"])

    def test_note_badge_renders_on_the_title_line_with_its_count(self):
        self.assertIsNotNone(self.OUT["noteBadgeText"], ".cr-rail-badge--note did not render")
        self.assertIn("3", self.OUT["noteBadgeText"])


# ---------------------------------------------------------------------------
# FIX 3 -- the flag/note/bg badges are real, clickable buttons: the flag
# badge emits 'open:flags'; note/bg badges call openSession() (-> ctx.go);
# all three stop propagation so the row behind them doesn't ALSO navigate.
# ---------------------------------------------------------------------------

_BADGE_CLICK_JS_TAIL = r"""
var calls = { emit: [], go: [] };
var ctxStub = {
  emit: function (name, payload) { calls.emit.push([name, payload === undefined ? null : payload]); },
  go: function (view, id) { calls.go.push([view, id]); }
};

var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, ctxStub);
window.CR.board.update({ sessions: [%(session)s], now: %(now)d });

var row = queryAllReal(root, '.cr-rail-row')[0];
var flagBtn = queryAllReal(row, '.cr-rail-badge--flag')[0];
var noteBtn = queryAllReal(row, '.cr-rail-badge--note')[0];
var bgBtn = queryAllReal(row, '.cr-rail-badge--bg')[0];

var out = {};

calls.emit = []; calls.go = [];
var flagStopped = simulateClick(flagBtn);
out.flag = { stopped: flagStopped, emit: calls.emit.slice(), go: calls.go.slice() };

calls.emit = []; calls.go = [];
var noteStopped = simulateClick(noteBtn);
out.note = { stopped: noteStopped, emit: calls.emit.slice(), go: calls.go.slice() };

calls.emit = []; calls.go = [];
var bgStopped = simulateClick(bgBtn);
out.bg = { stopped: bgStopped, emit: calls.emit.slice(), go: calls.go.slice() };

console.log("===CR_BADGECLICK_JSON_START===");
console.log(JSON.stringify(out));
"""


def _badge_click_driver_js():
    session = make_session(
        "badge_click_1", NOW - 5,
        ended=False, open_flags=2, note_count=3, bg=4, flag_text="needs review",
    )
    tail = _BADGE_CLICK_JS_TAIL % {"session": json.dumps(session), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowBadgeClicksAreWired(unittest.TestCase):
    """Simulates a REAL click (with bubbling) on each of the flag/note/bg
    badges of a session with open_flags=2, note_count=3, bg=4, and checks
    what actually fired: the flag badge must emit 'open:flags' and must NOT
    let the row's own click (openSession -> ctx.go) also fire; the note and
    bg badges must call openSession themselves (ctx.go('detail', id)) and,
    same as the flag badge, stop the row's own click from ALSO firing (which
    would otherwise call ctx.go a second time)."""

    @classmethod
    def setUpClass(cls):
        js = _badge_click_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Badge-click driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_BADGECLICK_JSON_START===")

    def test_flag_badge_click_emits_open_flags(self):
        emitted = [c[0] for c in self.OUT["flag"]["emit"]]
        self.assertIn("open:flags", emitted)

    def test_flag_badge_click_does_not_also_navigate_the_row(self):
        # stopPropagation must have kept the row's own onclick (openSession)
        # from ALSO firing -- ctx.go must never be called for a flag click.
        self.assertEqual(self.OUT["flag"]["go"], [])

    def test_note_badge_click_opens_the_session_exactly_once(self):
        self.assertEqual(self.OUT["note"]["go"], [["detail", "badge_click_1"]])

    def test_bg_badge_click_opens_the_session_exactly_once(self):
        self.assertEqual(self.OUT["bg"]["go"], [["detail", "badge_click_1"]])


# ---------------------------------------------------------------------------
# FIX 4 -- computeAgentParentIds(sessions, now) returns {n, live} per parent
# (was a bare `true`); a parent row renders a "kid chip" reading e.g.
# "2 live / 5 agents" (live share omitted when zero). Both call sites (the
# rail's renderRail and the Sessions destination's renderSessionsView) pass
# `now` and must agree.
# ---------------------------------------------------------------------------

_KID_CHIP_JS_TAIL = r"""
function kidChipTextFor(root, id) {
  var row = findRowById(root, id);
  if (!row) return undefined;   // row not found at all
  var chips = queryAllReal(row, '.cr-rail-badge--kids');
  return chips.length ? allTextIn(chips[0]) : null;   // null = row found, no chip
}

var handlers = {};
var ctxStub = {
  on: function (evt, fn) { handlers[evt] = fn; },
  go: function () {}, emit: function () {}
};

var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, ctxStub);

var sessions = %(sessions)s;
window.CR.board.update({ sessions: sessions, now: %(now)d });

var out = {};
out.railLiveParent = kidChipTextFor(root, "parent_live_and_stale");
out.railZeroLiveParent = kidChipTextFor(root, "parent_zero_live");

// Cross-view parity (requirement 4's second call site): switch to the
// Sessions destination and check the SAME parent renders the SAME chip
// there, driven by renderSessionsView's own computeAgentParentIds(sessions, now)
// call -- not a second, hand-derived value.
if (handlers['view:changed']) handlers['view:changed']({ view: 'sessions' });
var sessionsListEl = queryAllReal(root, '.cr-sessions-list')[0];
out.sessionsViewLiveParent = sessionsListEl ? kidChipTextFor(sessionsListEl, "parent_live_and_stale") : undefined;

console.log("===CR_KIDCHIP_JSON_START===");
console.log(JSON.stringify(out));
"""


def _kid_chip_driver_js():
    sessions = [
        make_session("parent_live_and_stale", NOW - 100, ended=False),
        make_session("parent_zero_live", NOW - 100, ended=False),
    ]
    # 2 live (fresh mtime) + 3 stale (long past LIVE_WINDOW=300s) agent
    # children of parent_live_and_stale -> kid chip must read
    # "2 live / 5 agents".
    for i in range(2):
        sessions.append(make_session(
            "live_child_%d" % i, NOW - 5, agent=True,
            parentId="parent_live_and_stale", group="g1", groupLabel="repo"))
    for i in range(3):
        sessions.append(make_session(
            "stale_child_%d" % i, NOW - 10_000, agent=True,
            parentId="parent_live_and_stale", group="g1", groupLabel="repo"))
    # 3 entirely stale agent children of parent_zero_live -> "3 agents", no
    # "live" wording at all (live share omitted when zero).
    for i in range(3):
        sessions.append(make_session(
            "zerolive_child_%d" % i, NOW - 10_000, agent=True,
            parentId="parent_zero_live", group="g2", groupLabel="repo2"))
    tail = _KID_CHIP_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestComputeAgentParentIdsKidChipParity(unittest.TestCase):
    """`parent_live_and_stale` spawned 5 agent children total, 2 of them
    still live (fresh mtime) and 3 long stale -- its kid chip must read
    "2 live / 5 agents" in BOTH the rail and the Sessions destination (the
    two call sites of computeAgentParentIds). `parent_zero_live` spawned 3
    entirely-stale children -- 0 live -- so its chip must read "3 agents"
    with no "live" wording at all."""

    @classmethod
    def setUpClass(cls):
        js = _kid_chip_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Kid-chip driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_KIDCHIP_JSON_START===")

    def test_rail_kid_chip_shows_live_share_and_total(self):
        text = self.OUT["railLiveParent"]
        self.assertIsNotNone(text, "kid chip did not render on the rail row")
        self.assertIn("2 live / 5 agents", text)

    def test_rail_kid_chip_omits_live_share_when_zero(self):
        text = self.OUT["railZeroLiveParent"]
        self.assertIsNotNone(text, "kid chip did not render on the rail row")
        self.assertIn("3 agents", text)
        self.assertNotIn("live", text)

    def test_sessions_destination_call_site_agrees_with_the_rail(self):
        """The Sessions destination's own renderSessionsView() call site must
        compute the identical {n, live} for the SAME sessions+now -- not a
        stale or re-derived value."""
        text = self.OUT["sessionsViewLiveParent"]
        self.assertIsNotNone(text, "parent row did not render in the Sessions destination")
        self.assertIn("2 live / 5 agents", text)


if __name__ == "__main__":
    unittest.main()
