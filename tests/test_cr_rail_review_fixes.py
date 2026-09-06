"""Regression tests for FOUR bugs an adversarial review found (and this
session fixed) in the control-room session rail (ext_cr_board.js /
ext_cr_board.css), each pinned via a REAL render of the bundle:

1. FOOTER COUNT MIXED TWO POPULATIONS. `renderRail()` used to compute
   `var more = baseSessions.length - shown` -- `shown` counts only the
   non-agent, search-surviving, cap-admitted rows renderSessionRows() actually
   drew, while `baseSessions` counts EVERY session handed to the rail,
   including agent sessions (already on screen inside their own "Agents"
   buckets) and sessions a live search query deliberately excluded. Fixed to
   `hiddenN = res.total - res.shown`, where `res.total` is
   `renderSessionRows()`'s own `flat.length` -- the exact non-agent,
   search-filtered population `shown` is drawn from. Three consequences pinned
   here: (a) agent sessions must not inflate the hidden count; (b) clicking
   "Show more" enough times must reach a genuine terminal state (plain text
   containing "all shown", `cr-rail-footer--more` class gone, `role="button"`
   gone) -- unreachable under the old formula whenever any agent session
   existed, because the leftover agent count could never be clicked away;
   (c) a search matching nothing must render zero rows AND claim zero hidden.

2. "SESSIONS" GROUP HEADER VANISHED WHEN EVERY SESSION IS PINNED.
   `renderSessionRows()`'s guard was `if (unpinnedShown.length || !opts)`. The
   rail always passes `{limit: railLimit}` now, making `opts` truthy, so with
   zero unpinned sessions (everything pinned) the guard's OR chain went
   false||false = false and the "Sessions -- N -- newest first" header
   disappeared entirely, even though the Pinned header above it still
   rendered fine. Fixed to `unpinnedShown.length || !opts || opts.limit`,
   which restores the header for the rail's own `{limit}` call without giving
   the Sessions destination's `{pageSize}` pager a header it never had.

3. FAILING SESSIONS DROPPED ENTIRELY UNDER GROUP-BY "ACTIVENESS".
   `sessionState()` can return `'failing'` (a live session with `fail_cmd`
   set), but `ACTIVENESS_GROUP_ORDER` only ever named
   awaiting/flagged/working/landed/idle, and `groupUnpinnedSessions()` filters
   its buckets THROUGH that list (`ACTIVENESS_GROUP_ORDER.filter(...)`) -- so
   a failing session's bucket was computed, populated, and then filtered out
   of existence: it rendered nowhere in the rail at all. Fixed by adding
   `'failing'` to the list, between `'flagged'` and `'working'` (matching
   `RANK`'s own ordering), with the label `'Failing'`.

4. A PINNED ROW THAT IS ALSO DONE LOST ITS PINNED FILL.
   `.cr-rail-row--pinned` and `.cr-rail-row--done` are independent booleans
   (a session's `pinned` flag and its live/ended-derived `statusKind` never
   interact), so a session can carry both classes at once. Both selectors
   have identical specificity (0,2,0), and `--done`'s new green
   `background: var(--surface-done)` was declared AFTER `--pinned`'s amber
   `background: var(--surface-agent-quiet)` -- so on equal specificity the
   later rule always won, and a pinned session silently lost its pinned look
   the instant it finished. Classic's `.sitem.done` (app.css) sets no
   background at all, so pinned+done stays amber there; ported here with an
   explicit combined-selector rule,
   `.tracker-next .cr-rail-row--pinned.cr-rail-row--done { background: var(--surface-agent-quiet); }`,
   placed AFTER the plain `--done` rule so it wins on source order too (CSS
   cascade: among equal-specificity rules, later wins -- a combined selector
   is MORE specific than either single-class rule (0,2,0) vs (0,1,0), so it
   would win regardless of order, but the fix additionally places it last,
   matching the file's own stated convention of "later rule wins" documented
   next to `--pinned`/`--waiting`/`--done`/`--flagged` above it).

Idiom reused verbatim (by direct copy -- this codebase's own convention,
see test_cr_rail_polish.py / test_cr_rail_row_parity.py, each of which
carries its own copy rather than importing a shared module) from
tests/test_cr_rail_row_parity.py: `_read_page()`, `_extract_script_content()`,
`_extract_style_content()`, `_run_node()`, `make_session()`, the fixed `NOW`
clock, the `_HAS_NODE` skip guard, and the hand-rolled DOM stub
(`makeReal`/`queryAllReal`/`findRowById`/`allTextIn`) that drives the REAL
`CR.board.mount()`/`.update()` render. Adds one small helper of its own,
`findFirstByTag()`, to locate the rail's search `<input>` (it carries no
class attribute, so `queryAllReal()`'s class-only selector can't find it).

NOTE: tests/test_cr_rail_cap_and_selection.py may be added concurrently by
another session -- this file does not import from it, depend on it, or
assume anything about its contents.
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
# Hand-rolled DOM harness -- copied verbatim (this codebase's own convention)
# from tests/test_cr_rail_row_parity.py, plus one addition of this file's own
# (findFirstByTag, for the rail search <input>, which carries no class).
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

// data-id lookup (used for group-by / kid-chip style tests below) --
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

// ADDED FOR THIS FILE: the rail's own search <input> carries no class
// attribute (only its wrapping <div class="cr-rail-search"> does), so it is
// unreachable through queryAllReal()'s class-only selector. Finds the first
// descendant with the given (uppercased, per makeReal()) tagName instead.
function findFirstByTag(root, tag) {
  var want = String(tag).toUpperCase();
  var found = null;
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (!found && c && c.tagName === want) { found = c; }
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


def _extract_marker_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


def _run_driver(tail):
    js = "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])
    returncode, stdout, stderr = _run_node(js)
    if returncode != 0:
        raise AssertionError(
            "Driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (returncode, stdout, stderr))
    return stdout


# ---------------------------------------------------------------------------
# FIX 1 -- the rail footer's hidden count mixed two different populations
# (baseSessions vs. shown), so agent sessions inflated it and it could go
# permanently unreachable at zero. Now `hiddenN = res.total - res.shown`.
# ---------------------------------------------------------------------------

_FOOTER_PARITY_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});

function footerEl() { return queryAllReal(root, '.cr-rail-footer')[0]; }
function searchInputEl() { return findFirstByTag(root, 'input'); }

var out = {};

// -- (a) agent sessions must not inflate the hidden count -----------------
// 30 non-agent + 5 agent sessions, default cap 25 (RAIL_LIMIT_STEP): the
// footer must report exactly 5 hidden (the capped non-agent overflow), never
// 10 (which is what `baseSessions.length(35) - shown(25)` produced under the
// bug, since baseSessions also counted the 5 agent sessions the cap never
// touches -- they render in their own "Agents" bucket regardless of railLimit).
var mixedSessions = [];
for (var i = 0; i < 30; i++) {
  mixedSessions.push({
    id: 'mix_s' + i, project: 'proj', cwd: '/tmp/proj', title: 'Mixed ' + i, prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - i,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: ''
  });
}
for (var j = 0; j < 5; j++) {
  mixedSessions.push({
    id: 'mix_agent' + j, project: 'proj', cwd: '/tmp/proj', title: 'Agent ' + j, prompt: 'p',
    source: 'cli', agent: true, group: 'mixgrp', groupLabel: 'Mix repo', parentId: 'mix_s0',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - j,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: ''
  });
}
window.CR.board.update({ sessions: mixedSessions, now: %(now)d });
out.footerAtCap = footerEl().textContent;

// -- (b) "Show more" must eventually reach a genuine terminal state --------
// 60 non-agent + 5 agent sessions: under the OLD `baseSessions.length - shown`
// formula this population NEVER reaches 0 hidden -- the 5 agent sessions
// permanently pad the count no matter how many times "Show more" is clicked,
// so the footer can never flip back to plain "... all shown" text. Clicks
// enough times to exceed the full 65-session population several times over.
var manySessions = [];
for (var k = 0; k < 60; k++) {
  manySessions.push({
    id: 'many_s' + k, project: 'proj', cwd: '/tmp/proj', title: 'Many ' + k, prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - k,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: ''
  });
}
for (var m = 0; m < 5; m++) {
  manySessions.push({
    id: 'many_agent' + m, project: 'proj', cwd: '/tmp/proj', title: 'Agent ' + m, prompt: 'p',
    source: 'cli', agent: true, group: 'manygrp', groupLabel: 'Many repo', parentId: 'many_s0',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - m,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: ''
  });
}
window.CR.board.update({ sessions: manySessions, now: %(now)d });
var footer = footerEl();
var clicked = 0;
for (var c = 0; c < 8 && footer.onclick; c++) { footer.onclick(); clicked++; }
out.clicksUntilTerminal = clicked;
out.footerTextAfterClicks = footer.textContent;
out.footerHasMoreClassAfterClicks = footer.classList.contains('cr-rail-footer--more');
out.footerHasRoleAfterClicks = footer.getAttribute('role');
out.footerOnclickAfterClicks = !!footer.onclick;

// -- (c) a search matching nothing must render zero rows and claim zero
// hidden, never the population it filtered out. --------------------------
var searchable = [];
for (var n = 0; n < 10; n++) {
  searchable.push({
    id: 'srch_s' + n, project: 'findableproj', cwd: '/tmp/proj', title: 'Findable Title ' + n, prompt: 'findable prompt',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - n,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: ''
  });
}
window.CR.board.update({ sessions: searchable, now: %(now)d });
var input = searchInputEl();
// h() wires 'on*' attrs through addEventListener (never a direct .oninput
// property -- only the rail footer's own onclick is a raw property, set
// later by renderRail() directly), so the recorded handler lives under
// el._listeners.input, per this harness's addEventListener stub above.
input._listeners.input({ target: { value: 'zzz-nothing-matches-this-query-zzz' } });
out.searchNoMatchRowCount = queryAllReal(root, '.cr-rail-row').length;
out.searchNoMatchFooterText = footerEl().textContent;
out.searchNoMatchFooterHasMoreClass = footerEl().classList.contains('cr-rail-footer--more');

console.log("===CR_FOOTERPARITY_JSON_START===");
console.log(JSON.stringify(out));
"""


def _footer_parity_driver_js():
    return _FOOTER_PARITY_JS_TAIL % {"now": NOW}


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailFooterHiddenCountFix(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX 1: `renderRail()`'s hidden-count footer used to
    subtract two different populations (`baseSessions.length - shown`),
    letting agent sessions inflate the count and making the terminal "all
    shown" state permanently unreachable whenever any agent session existed.
    Now `hiddenN = res.total - res.shown`, both drawn from the same
    non-agent, search-filtered population `renderSessionRows()` actually
    rendered from."""

    @classmethod
    def setUpClass(cls):
        cls.OUT = _extract_marker_json(_run_driver(_footer_parity_driver_js()), "===CR_FOOTERPARITY_JSON_START===")

    def test_agent_sessions_do_not_inflate_the_hidden_count(self):
        # 30 non-agent + 5 agent, cap 25 -> exactly 5 hidden, never 10 (which
        # is what baseSessions.length(35) - shown(25) produced under the bug).
        text = self.OUT["footerAtCap"]
        self.assertIn("5 hidden", text)
        self.assertNotIn("10 hidden", text)

    def test_show_more_reaches_a_genuine_terminal_state(self):
        # Regression: under the old formula this population (60 non-agent + 5
        # agent) never reaches 0 hidden -- the 5 agent sessions permanently
        # pad the subtraction no matter how many times "Show more" is clicked.
        self.assertIn("all shown", self.OUT["footerTextAfterClicks"])
        self.assertNotIn("hidden", self.OUT["footerTextAfterClicks"])
        self.assertFalse(self.OUT["footerHasMoreClassAfterClicks"])
        self.assertIsNone(self.OUT["footerHasRoleAfterClicks"])
        self.assertFalse(self.OUT["footerOnclickAfterClicks"])

    def test_search_matching_nothing_renders_zero_rows_and_claims_none_hidden(self):
        self.assertEqual(self.OUT["searchNoMatchRowCount"], 0)
        self.assertIn("all shown", self.OUT["searchNoMatchFooterText"])
        self.assertNotIn("hidden", self.OUT["searchNoMatchFooterText"])
        self.assertFalse(self.OUT["searchNoMatchFooterHasMoreClass"])


# ---------------------------------------------------------------------------
# FIX 2 -- the "Sessions -- N -- newest first" group header vanished whenever
# every rendered session was pinned, because the rail's own `{limit}` opts
# made the old `unpinnedShown.length || !opts` guard go false||false.
# ---------------------------------------------------------------------------

_ALL_PINNED_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});

// Non-default: 3 sessions, ALL pinned, none of them the make_session()
// default title/id shape (bespoke ids/titles below).
var allPinned = [
  { id: 'ap_one', project: 'projx', cwd: '/tmp/x', title: 'Alpha pinned', prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - 1,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: true, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: '' },
  { id: 'ap_two', project: 'projx', cwd: '/tmp/x', title: 'Bravo pinned', prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - 2,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: true, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: '' },
  { id: 'ap_three', project: 'projx', cwd: '/tmp/x', title: 'Charlie pinned', prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - 3,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: true, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: '' }
];
window.CR.board.update({ sessions: allPinned, now: %(now)d });

var headers = queryAllReal(root, '.cr-rail-group-header').map(function (h) { return allTextIn(h); });
console.log("===CR_ALLPINNED_JSON_START===");
console.log(JSON.stringify({ headers: headers }));
"""


def _all_pinned_driver_js():
    return _ALL_PINNED_JS_TAIL % {"now": NOW}


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailSessionsHeaderSurvivesAllPinned(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX 2: with 3 sessions and ALL of them pinned, the
    rail must render BOTH the "Pinned" group header AND the "Sessions" group
    header. Under the bug, the rail's own `{limit}` opts made `opts` truthy,
    so `if (unpinnedShown.length || !opts)` (0 || false) suppressed the
    "Sessions" header entirely -- it is now `|| opts.limit`."""

    @classmethod
    def setUpClass(cls):
        cls.OUT = _extract_marker_json(_run_driver(_all_pinned_driver_js()), "===CR_ALLPINNED_JSON_START===")

    def test_both_pinned_and_sessions_headers_render(self):
        headers = self.OUT["headers"]
        self.assertTrue(any("Pinned" in h for h in headers), "no Pinned header: %r" % headers)
        self.assertTrue(any("Sessions" in h for h in headers), "no Sessions header: %r" % headers)


# ---------------------------------------------------------------------------
# FIX 3 -- a live session with fail_cmd set (sessionState() -> 'failing') was
# rendered NOWHERE at all once group-by was set to "activeness", because
# ACTIVENESS_GROUP_ORDER never named 'failing' and groupUnpinnedSessions()
# filters its buckets through that list.
# ---------------------------------------------------------------------------

_FAILING_GROUP_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});

// Non-default fail_cmd text, live mtime (well inside LIVE_WINDOW=300s).
var sessions = [
  { id: 'fail_one', project: 'projy', cwd: '/tmp/y', title: 'Broken build session', prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - 5,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: 'make check -- suite red', model: '' },
  // A second, ordinary idle session, to prove grouping itself still works
  // and this isn't just an empty-rail false pass.
  { id: 'idle_two', project: 'projy', cwd: '/tmp/y', title: 'Idle sibling session', prompt: 'p',
    source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
    bg: 0, waiting: false, ended: false, mtime: %(now)d - 999999,
    todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
    pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
    pinned: false, note_count: 0, open_flags: 0,
    continued_as: '', continued_from: '', fail_cmd: null, model: '' }
];

// Drive group-by the way the real UI does: through the rendered <select>'s
// own onchange handler (persistRailGroupMode() + re-render), not a direct
// localStorage write.
window.CR.board.update({ sessions: sessions, now: %(now)d });
var groupSelect = queryAllReal(root, '.cr-rail-groupby-select')[0];
// h() wires 'on*' attrs through addEventListener, so the handler lives under
// el._listeners.change (see the note above the search-input driver above).
groupSelect._listeners.change({ target: { value: 'activeness' } });

var headers = queryAllReal(root, '.cr-rail-group-header').map(function (h) { return allTextIn(h); });
var failingRow = findRowById(root, 'fail_one');
var idleRow = findRowById(root, 'idle_two');

console.log("===CR_FAILINGGROUP_JSON_START===");
console.log(JSON.stringify({
  headers: headers,
  failingRowRendered: !!failingRow,
  idleRowRendered: !!idleRow,
  persistedMode: window.localStorage.getItem('cr.railGroupBy')
}));
"""


def _failing_group_driver_js():
    return _FAILING_GROUP_JS_TAIL % {"now": NOW}


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestFailingSessionRendersUnderActivenessGrouping(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX 3: a live session with `fail_cmd` set
    (sessionState() -> 'failing') must render under a "Failing" group header
    once group-by is switched to 'activeness' -- driven through the real
    <select>'s onchange, exactly as a user would. This test MUST fail if
    'failing' is ever removed from ACTIVENESS_GROUP_ORDER again: that removal
    makes groupUnpinnedSessions() filter the failing bucket out of existence,
    so the row renders nowhere."""

    @classmethod
    def setUpClass(cls):
        cls.OUT = _extract_marker_json(_run_driver(_failing_group_driver_js()), "===CR_FAILINGGROUP_JSON_START===")

    def test_groupby_select_persisted_activeness_mode(self):
        self.assertEqual(self.OUT["persistedMode"], json.dumps("activeness"))

    def test_failing_header_renders(self):
        headers = self.OUT["headers"]
        self.assertTrue(any(h.startswith("Failing") for h in headers), "no Failing header: %r" % headers)

    def test_failing_session_row_renders(self):
        self.assertTrue(self.OUT["failingRowRendered"], "the failing session's row did not render at all")

    def test_sibling_idle_session_still_renders_too(self):
        # Guards against a vacuous pass (e.g. an empty rail from a driver bug).
        self.assertTrue(self.OUT["idleRowRendered"], "the idle sibling session did not render")


# ---------------------------------------------------------------------------
# FIX 4 -- a pinned row that is also done must keep its amber pinned fill,
# not lose it to the later, equal-specificity `--done` green background rule.
# ---------------------------------------------------------------------------

_PINNED_DONE_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});

// Built carefully per the fix's own precondition: ended=true, mtime inside
// LIVE_WINDOW (300s) of `now`, bg=0 (no background agents -- isWorking()
// would otherwise keep statusKind from ever becoming 'done'), not waiting,
// no open_flags (keeps rowMods clean of an unrelated class).
var session = {
  id: 'pd_one', project: 'projz', cwd: '/tmp/z', title: 'Pinned and done', prompt: 'p',
  source: 'cli', agent: false, group: '', groupLabel: '', parentId: '',
  bg: 0, waiting: false, ended: true, mtime: %(now)d - 5,
  todo_total: 0, todo_done: 0, todo_current: null, todo_current_index: null,
  pr_num: null, pr_url: null, pr_repo: null, pr_state: '', now_line: '',
  pinned: true, note_count: 0, open_flags: 0,
  continued_as: '', continued_from: '', fail_cmd: null, model: ''
};
window.CR.board.update({ sessions: [session], now: %(now)d });

var row = findRowById(root, 'pd_one');
console.log("===CR_PINNEDDONE_JSON_START===");
console.log(JSON.stringify({ classes: row ? Array.from(row._classes) : null }));
"""


def _pinned_done_driver_js():
    return _PINNED_DONE_JS_TAIL % {"now": NOW}


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestPinnedDoneRowKeepsBothModifierClasses(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX 4 (a): a session that is BOTH pinned and done
    (ended=true, mtime inside LIVE_WINDOW, no background agents) must carry
    BOTH `.cr-rail-row--pinned` and `.cr-rail-row--done` on its rendered row.
    This alone does not prove the pinned fill wins visually -- see the CSS
    test below for the cascade half of the fix."""

    @classmethod
    def setUpClass(cls):
        cls.OUT = _extract_marker_json(_run_driver(_pinned_done_driver_js()), "===CR_PINNEDDONE_JSON_START===")

    def test_row_carries_pinned_class(self):
        classes = self.OUT["classes"]
        self.assertIsNotNone(classes, "row did not render at all")
        self.assertIn("cr-rail-row--pinned", classes)

    def test_row_carries_done_class(self):
        classes = self.OUT["classes"] or []
        self.assertIn("cr-rail-row--done", classes)


class TestPinnedDoneCssRestoresAmberFill(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX 4 (b): the CSS half. `.cr-rail-row--pinned` and
    `.cr-rail-row--done` have identical specificity and `--done`'s green
    background was declared later, so it silently overrode the amber pinned
    fill. The fix adds an explicit combined-selector rule restoring
    `var(--surface-agent-quiet)`, placed AFTER the plain `--done` rule in
    source order (belt-and-suspenders with the combined selector's own higher
    specificity) so it wins either way."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())

    def test_combined_pinned_done_rule_exists_and_restores_amber(self):
        m = re.search(
            r'\.tracker-next \.cr-rail-row--pinned\.cr-rail-row--done\s*\{([^}]*)\}',
            self.css)
        self.assertIsNotNone(m, "combined .cr-rail-row--pinned.cr-rail-row--done rule not found")
        self.assertIn("background: var(--surface-agent-quiet)", m.group(1))

    def test_combined_rule_appears_after_the_plain_done_rule_in_source_order(self):
        done_m = re.search(r'\.tracker-next \.cr-rail-row--done\s*\{', self.css)
        combined_m = re.search(r'\.tracker-next \.cr-rail-row--pinned\.cr-rail-row--done\s*\{', self.css)
        self.assertIsNotNone(done_m, "plain .cr-rail-row--done rule not found")
        self.assertIsNotNone(combined_m, "combined rule not found")
        self.assertLess(done_m.start(), combined_m.start(),
                         "combined pinned+done rule must come AFTER the plain --done rule")


if __name__ == "__main__":
    unittest.main()
