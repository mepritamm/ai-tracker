"""Regression tests for FOUR later changes layered on top of the control-room
session rail (aitracker/web/ext_cr_board.js, ext_cr_detail.js):

1. RAIL CAP. `renderSessionRows(container, sessions, now, opts)` gained an
   `opts.limit` branch: it keeps ALL of `order.pinned` and slices
   `order.unpinned` to `opts.limit`. `renderRail` now calls it as
   `renderSessionRows(els.railList, baseSessions, now, { limit: railLimit })`
   with `railLimit` starting at `RAIL_LIMIT_STEP` (25). Pinned sessions are
   never dropped by the cap -- only the unpinned tail is sliced. The Sessions
   destination (`renderSessionsView`, which always passes `{ page, pageSize }`,
   never `limit`) is untouched by this change.

2. SEARCH FILTER SURVIVES THE CAP. `renderSessionRows` used to decide whether
   to apply the rail's own live `searchQuery` with `opts ? '' : undefined` --
   "any caller that passes opts wants no local filter". That was only ever
   true of the Sessions pager (which always sets `pageSize`). Once `renderRail`
   started passing `opts` too (the new `{ limit: railLimit }`), the OLD line
   would have silently forced the override to `''` on every single rail
   render, permanently disabling the rail's own search box. The fix keys off
   `pageSize` specifically: `(opts && opts.pageSize) ? '' : undefined`.

3. SHARED SELECTION. New `selectedId()` (ext_cr_board.js) returns the classic
   global `cur` if truthy, else `localStorage.getItem('sid')`, else the
   module-local `selectedSessionId` fallback. Rail rows get
   `cr-rail-row--selected` for whichever id it resolves to. THE BUG this
   fixes: selecting a session in the classic dashboard (which only ever
   writes `cur` + localStorage 'sid', never this module's own
   `selectedSessionId`) used to highlight nothing at all in the rail.

4. DETAIL SOURCE LABEL DELEGATION. `ext_cr_detail.js`'s `renderHeader` used to
   derive the header's source word inline with `/auggie/i.test(...)` /
   `/augment/i.test(...)` / else the literal "Claude CLI" -- collapsing
   'cli', 'claude-desktop', 'sdk-cli' and 'claude-vscode' ALL into "Claude
   CLI". It now calls a new `sourceLabel(meta)`, which delegates to
   `window.CR.board.toolLabel` (newly exported from ext_cr_board.js, the same
   map the rail/board tiles already use) and falls back to the old regex
   trio only when that function isn't reachable at all.

Idiom reused verbatim from tests/test_cr_rail_row_parity.py and
tests/test_cr_rail_polish.py: `_read_page()`, `_extract_script_content()`,
`_extract_style_content()`, `_run_node()`, `make_session()`, the fixed `NOW`
clock, the `_HAS_NODE` skip guard, and the hand-rolled DOM stub
(`makeReal`/`queryAllReal`/`allTextIn`/`findRowById`) that drives the REAL
`mount()`/`update()` render path -- never a no-op stub, since everything
under test here only exists inside an actual render. `_extract_function()` is
reused verbatim from tests/test_cr_detail_agents_pill_and_markdown.py /
tests/test_cr_rail_toggle.py (brace-match a named function's exact text out
of the real bundle) for requirement 4's `sourceLabel`, which -- unlike
`toolLabel` -- is never exported on `window.CR.detail`, so it can only be
pinned by extracting its real source and running it under Node, wired to the
REAL (not hand-mocked) `window.CR.board.toolLabel` produced by actually
running the full bundle first.

One deliberate extension of the idiom: requirement 3 needs to control the
classic global `cur` (`let cur = localStorage.getItem("sid") || "";`, from
app.js, concatenated as the very first statement inside the bundle). That
`let` is block-scoped to the `try { ... }` wrapper every one of these harness
files runs the bundle inside, so it is NOT reachable from driver code written
after the wrapper's closing `catch` (unlike `window.CR.board`, which is a
property on the global `window` object and so escapes the block just fine).
The only way to control `cur`'s value is to seed `window.localStorage`'s
'sid' BEFORE the bundle runs -- exactly how a real page boot would already
have `cur` come from a previously-selected session -- via a parameterised
`_dom_preamble(pre_sid=...)` that pre-populates the storage backing map
before the `try {` line. Once the bundle has already captured that value into
`cur`, `window.localStorage` can still be repointed to a DIFFERENT id
afterwards (it's just a plain global object) without touching `cur` again --
which is exactly the lever used below to prove `cur` really does win over
`localStorage` when both are set to different sessions.
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


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the
    real bundle. Raises loudly (never returns a guess) if the shape has
    moved. Verbatim helper from tests/test_cr_detail_agents_pill_and_markdown.py
    / tests/test_cr_rail_toggle.py."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in the real bundle" % name)
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
# Hand-rolled DOM harness -- same technique as test_cr_rail_row_parity.py /
# test_cr_rail_polish.py, parameterised so requirement 3's tests can seed
# localStorage's 'sid' BEFORE the bundle's own `let cur = localStorage.
# getItem("sid") || "";` (app.js, line 1) captures it -- see the module
# docstring's "one deliberate extension" note for why this can't be done any
# other way.
# ---------------------------------------------------------------------------

def _dom_preamble(pre_sid=None):
    storage_literal = json.dumps({"sid": pre_sid} if pre_sid else {})
    return r"""
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

// data-id lookup -- queryAllReal only matches class selectors.
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

// attribute lookup by exact value (used to find the rail's search <input>,
// which carries no distinguishing class of its own -- its wrapper's
// '.cr-rail-search' class is shared with the Sessions destination's own
// search box).
function findByAttr(root, attr, val) {
  var found = null;
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (!found && c && c._attrs && c._attrs[attr] === val) { found = c; }
      if (!found) walk(c);
    });
  })(root);
  return found;
}

function allTextIn(node) {
  var out = [];
  (function walk(n) {
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
  // Records the handler (single slot per event type) so a driver can invoke
  // it directly -- same extension test_cr_rail_row_parity.py made for its
  // badge-click tests.
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

// Seeded (per _dom_preamble's `pre_sid` argument) BEFORE the bundle runs, so
// app.js's own `let cur = localStorage.getItem("sid") || "";` (its very
// first statement) captures this value -- the only way to control that
// block-scoped `cur` binding from outside the bundle's own try{} wrapper.
var _STORAGE = %(storage)s;
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
""" % {"storage": storage_literal}


_DOM_MID = r"""
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


# ===========================================================================
# 1. RAIL CAP -- `renderSessionRows`'s `opts.limit` branch: unpinned sliced to
#    the cap, pinned never dropped; the Sessions destination (pageSize) is
#    untouched.
# ===========================================================================

_CAP_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: %(sessions)s, now: %(now)d });

var out = {};
out.railRowCount = queryAllReal(root, '.cr-rail-row').length;
out.pinnedRowCount = queryAllReal(root, '.cr-rail-row--pinned').length;

console.log("===CR_CAP_JSON_START===");
console.log(JSON.stringify(out));
"""


def _cap_driver_js(sessions):
    tail = _CAP_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_dom_preamble(), _bundle_js(), _DOM_MID, tail])


def _sixty_unpinned():
    # Non-default: 60 (well over RAIL_LIMIT_STEP == 25), distinct mtimes so
    # railOrder()'s recency sort is deterministic.
    return [make_session("u_%02d" % i, NOW - i * 10, ended=(i % 2 == 0))
            for i in range(60)]


def _run_cap_scenario(sessions):
    js = _cap_driver_js(sessions)
    returncode, stdout, stderr = _run_node(js)
    if returncode != 0:
        raise AssertionError(
            "Rail-cap driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (returncode, stdout, stderr))
    return _extract_marker_json(stdout, "===CR_CAP_JSON_START===")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailCapSlicesUnpinnedKeepsAllPinned(unittest.TestCase):
    """Drives the REAL renderRail()->renderSessionRows() path (mount->update->
    DOM), never a re-derivation of the slicing logic, for two non-default
    fixtures: 60 plain unpinned sessions, and 30 pinned + 60 unpinned."""

    @classmethod
    def setUpClass(cls):
        cls.only_unpinned = _run_cap_scenario(_sixty_unpinned())
        pinned = [make_session("p_%02d" % i, NOW - i * 5, pinned=True, ended=True)
                  for i in range(30)]
        cls.mixed = _run_cap_scenario(pinned + _sixty_unpinned())

    def test_sixty_unpinned_sessions_render_only_the_25_row_cap(self):
        self.assertEqual(self.only_unpinned["railRowCount"], 25,
                          "rail must cap unpinned rows at RAIL_LIMIT_STEP (25), not render all 60")

    def test_thirty_pinned_sessions_are_never_dropped_by_the_cap(self):
        # 30 pinned (all must render) + 25 of the 60 unpinned (capped) == 55.
        self.assertEqual(self.mixed["pinnedRowCount"], 30,
                          "every pinned session must render regardless of the unpinned cap")
        self.assertEqual(self.mixed["railRowCount"], 55,
                          "expected 30 pinned + 25 capped-unpinned == 55 total rail rows")


_SESSIONS_VIEW_JS_TAIL = r"""
var handlers = {};
var ctxStub = { on: function (evt, fn) { handlers[evt] = fn; }, go: function () {}, emit: function () {} };

var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, ctxStub);

var sessions = %(sessions)s;
window.CR.board.update({ sessions: sessions, now: %(now)d });

// Non-default page size (50, not the 25 default AND not the rail's 25 cap) --
// driven through the real <select onchange>, same as a user would.
var pageSizeSel = queryAllReal(root, '.cr-sessions-pagesize')[0];
pageSizeSel.value = '50';
pageSizeSel._listeners.change({ target: pageSizeSel });

if (handlers['view:changed']) handlers['view:changed']({ view: 'sessions' });

var sessionsListEl = queryAllReal(root, '.cr-sessions-list')[0];
var out = { sessionsRowCount: queryAllReal(sessionsListEl, '.cr-rail-row').length };

console.log("===CR_SESSVIEW_JSON_START===");
console.log(JSON.stringify(out));
"""


def _sessions_view_driver_js():
    sessions = _sixty_unpinned()
    tail = _SESSIONS_VIEW_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_dom_preamble(), _bundle_js(), _DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSessionsDestinationPagingUnaffectedByRailCap(unittest.TestCase):
    """The Sessions destination (renderSessionsView) always calls
    renderSessionRows with { page, pageSize }, never { limit }. Set its page
    size to 50 (neither the stock default of 25 NOR the rail's own 25 cap) on
    60 unpinned sessions and confirm it renders exactly 50 -- proof its own
    pagination, not the rail's limit, governs how many rows it shows."""

    @classmethod
    def setUpClass(cls):
        js = _sessions_view_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Sessions-view driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SESSVIEW_JSON_START===")

    def test_sessions_destination_shows_its_own_page_size_not_the_rail_cap(self):
        self.assertEqual(self.OUT["sessionsRowCount"], 50,
                          "Sessions destination must page by its own pageSize (50), "
                          "not be truncated to the rail's 25-row cap")


# ===========================================================================
# 2. SEARCH FILTER MUST SURVIVE THE CAP -- driving the rail's OWN search
#    <input> (oninput), the way a real user would, then checking the cap-
#    capable render still honours it.
# ===========================================================================

_SEARCH_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
var sessions = %(sessions)s;
window.CR.board.update({ sessions: sessions, now: %(now)d });

// The rail's own search <input> carries no distinguishing class (its wrapper
// class '.cr-rail-search' is shared with the Sessions destination's search
// box) -- found here by its own unique placeholder text instead.
var searchInput = findByAttr(root, 'placeholder', 'Search');
searchInput.value = 'gizmo';
searchInput._listeners.input({ target: searchInput });   // real oninput -> renderRail(lastState)

var out = {};
out.rowCount = queryAllReal(root, '.cr-rail-row').length;
out.matchOutsideCapPresent = !!findRowById(root, 's_25');   // oldest match; would be cap-excluded without search
out.nonMatchAbsent = !findRowById(root, 's_00');            // newest non-match; would show without search

console.log("===CR_SEARCH_JSON_START===");
console.log(JSON.stringify(out));
"""


def _search_driver_js():
    # 30 unpinned (over the 25-row cap) with 3 matches ("gizmo widget") spread
    # across the recency order, INCLUDING one (s_25) that recency-only capping
    # (no search) would exclude entirely -- the newest 25 by mtime are
    # s_00..s_24. If search were silently disabled by the old `opts ? '' :
    # undefined` line (opts is now always truthy: renderRail always passes
    # { limit }), s_25 could never appear and s_00 (a non-match) would.
    sessions = []
    for i in range(30):
        title = "gizmo widget correlate" if i in (5, 15, 25) else "plain session"
        sessions.append(make_session("s_%02d" % i, NOW - i * 10, title=title, ended=True))
    tail = _SEARCH_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_dom_preamble(), _bundle_js(), _DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailSearchSurvivesTheCap(unittest.TestCase):
    """30 unpinned sessions (over the 25-row cap), 3 titled "gizmo widget
    correlate" at recency positions 5, 15 and 25 -- s_25 is OLD ENOUGH that a
    plain top-25-by-recency cap (no search) would exclude it, and s_00 is
    NEW enough that it would always appear under that same plain cap. Typing
    "gizmo" into the rail's real search <input> must still filter down to
    just the 3 matches -- including s_25 -- proving the search query was
    never silently defeated by the (always-truthy, post-cap-change) opts
    object now passed to renderSessionRows."""

    @classmethod
    def setUpClass(cls):
        js = _search_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Rail-search driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SEARCH_JSON_START===")

    def test_search_narrows_to_only_the_three_matches(self):
        self.assertEqual(self.OUT["rowCount"], 3,
                          "rail search must filter down to the 3 'gizmo' matches, not the 25-row cap")

    def test_a_match_the_plain_recency_cap_would_have_excluded_still_shows(self):
        self.assertTrue(self.OUT["matchOutsideCapPresent"],
                         "s_25 matches the query but sits outside the top-25-by-recency window -- "
                         "it must still render, proving the filter ran, not just the cap")

    def test_a_non_match_inside_the_cap_window_is_excluded(self):
        self.assertTrue(self.OUT["nonMatchAbsent"],
                         "s_00 does not match 'gizmo' -- it must not render just because it's newest")


# ===========================================================================
# 3. SHARED SELECTION -- selectedId() precedence: classic global `cur` first,
#    then localStorage 'sid', then the module-local fallback; never throws.
# ===========================================================================

_SELECTION_JS_TAIL = r"""
%(pre)s
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: %(sessions)s, now: %(now)d });

function selectedRowId() {
  var rows = queryAllReal(root, '.cr-rail-row--selected');
  return rows.length ? rows[0]._attrs['data-id'] : null;
}

var out = { selected: selectedRowId() };
console.log("===CR_SELECT_JSON_START===");
console.log(JSON.stringify(out));
"""


def _selection_driver_js(pre_sid, pre_js, sessions):
    tail = _SELECTION_JS_TAIL % {"pre": pre_js, "sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_dom_preamble(pre_sid=pre_sid), _bundle_js(), _DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSelectedIdPrefersClassicGlobalCurOverLocalStorage(unittest.TestCase):
    """Seeds localStorage 'sid' = 'cur_target' BEFORE the bundle runs, so
    app.js's own `let cur = localStorage.getItem("sid") || "";` captures it
    into `cur` at boot -- exactly how a real page load would already have
    `cur` set from a previously-selected session. AFTER the bundle has
    already captured that value, localStorage 'sid' is then repointed to a
    DIFFERENT session ('decoy_target') -- `cur` itself is untouched (it's a
    block-scoped `let`, not re-read live). The control room here never calls
    its own openSession()/session:selected path, so `selectedSessionId`
    stays null throughout -- this is precisely "the classic global `cur` set
    to a session id, and the control room never having called openSession".
    Only `cur`'s row ('cur_target') may end up selected; if selectedId()
    fell through to localStorage instead it would wrongly select
    'decoy_target'."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("cur_target", NOW - 5, ended=True),
            make_session("decoy_target", NOW - 2, ended=True),
        ]
        pre_js = "window.localStorage.setItem('sid', 'decoy_target');"
        js = _selection_driver_js("cur_target", pre_js, sessions)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Selection (cur-priority) driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SELECT_JSON_START===")

    def test_the_classic_cur_sessions_row_is_selected_not_localstorages(self):
        self.assertEqual(self.OUT["selected"], "cur_target",
                          "selectedId() must prefer the classic global `cur` over localStorage 'sid' "
                          "when they disagree -- THE BUG: a session picked in the classic dashboard "
                          "used to highlight nothing in the rail at all")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSelectedIdFallsBackToLocalStorageWhenCurIsEmpty(unittest.TestCase):
    """Boots with no 'sid' in storage at all, so `cur` initialises to ''
    (falsy) -- then localStorage 'sid' is set (after boot, so `cur` stays
    untouched at '') to a target session id. selectedId() must fall through
    to that localStorage value."""

    @classmethod
    def setUpClass(cls):
        sessions = [make_session("ls_target", NOW - 5, ended=True)]
        pre_js = "window.localStorage.setItem('sid', 'ls_target');"
        js = _selection_driver_js(None, pre_js, sessions)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Selection (localStorage-fallback) driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SELECT_JSON_START===")

    def test_localstorage_sid_selects_the_row_when_cur_is_empty(self):
        self.assertEqual(self.OUT["selected"], "ls_target",
                          "selectedId() must fall back to localStorage 'sid' when the classic "
                          "global `cur` is empty/undefined")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSelectedIdNeitherCurNorLocalStorageDoesNotThrow(unittest.TestCase):
    """Boots with no 'sid' in storage (cur == '') and never sets localStorage
    'sid' either. selectedId() must not throw (an uncaught exception would
    make the node driver exit non-zero, which setUpClass treats as a hard
    failure) and no row should end up selected."""

    @classmethod
    def setUpClass(cls):
        sessions = [make_session("neither_target", NOW - 5, ended=True)]
        js = _selection_driver_js(None, "", sessions)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Selection (neither) driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SELECT_JSON_START===")

    def test_no_row_is_selected_and_nothing_threw(self):
        self.assertIsNone(self.OUT["selected"],
                           "with neither `cur` nor localStorage 'sid' set, no row should be selected")


# ===========================================================================
# 4. DETAIL SOURCE LABEL DELEGATION -- ext_cr_detail.js's sourceLabel(meta)
#    delegates to window.CR.board.toolLabel; renderHeader no longer derives
#    the label itself.
# ===========================================================================

class TestSourceLabelDelegationSourceText(unittest.TestCase):
    """Text-level checks against the real assembled bundle (no node needed)."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())
        cls.render_header_src = _extract_function(cls.bundle, "renderHeader")
        cls.source_label_src = _extract_function(cls.bundle, "sourceLabel")

    def test_board_exports_toollabel_on_its_public_object(self):
        self.assertIn("toolLabel: toolLabel,", self.bundle,
                       "ext_cr_board.js must export toolLabel on window.CR.board")

    def test_source_label_exists_and_calls_board_toollabel(self):
        self.assertIn(
            "window.CR && window.CR.board && window.CR.board.toolLabel",
            self.source_label_src,
        )

    def test_render_header_no_longer_derives_the_label_itself(self):
        """renderHeader must delegate to sourceLabel(meta) -- and must not
        carry its own inline "Claude CLI" fallback/regex derivation any more
        (that logic now lives ONLY inside sourceLabel's own fallback
        branch)."""
        self.assertIn("sourceLabel(meta)", self.render_header_src)
        self.assertNotIn("Claude CLI", self.render_header_src,
                          "renderHeader must no longer derive the source label inline -- "
                          "that must live only in sourceLabel()'s fallback branch")

    def test_the_old_fallback_still_exists_but_only_inside_sourcelabel(self):
        # Sanity control: the old regex trio is still ALLOWED to exist as
        # sourceLabel's own last-resort fallback (board not mounted at all) --
        # this fix relocates it, it doesn't delete it.
        self.assertIn("Claude CLI", self.source_label_src)
        self.assertIn("/auggie/i.test(raw)", self.source_label_src)


_SOURCE_LABEL_JS_TAIL = r"""
%(source_label_src)s

var out = {};
out.claudeDesktop = sourceLabel({ source: 'claude-desktop' });
out.cli = sourceLabel({ source: 'cli' });
out.emptySource = sourceLabel({});

console.log("===CR_SRCLABEL_JSON_START===");
console.log(JSON.stringify(out));
"""


def _source_label_driver_js():
    bundle = _bundle_js()
    source_label_src = _extract_function(bundle, "sourceLabel")
    tail = _SOURCE_LABEL_JS_TAIL % {"source_label_src": source_label_src}
    # Runs the FULL bundle first (inside the try{} wrapper, same DOM harness
    # as every other test in this file) so window.CR.board.toolLabel is the
    # REAL function (reading app.js's real SRC_TEXT map) -- then, OUTSIDE
    # that wrapper, evaluates sourceLabel()'s own extracted source text
    # (sourceLabel is never itself exported on window.CR.detail, unlike
    # toolLabel) and calls it directly against that real toolLabel.
    return "\n".join([_dom_preamble(), bundle, _DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSourceLabelRealInvocationDelegatesToToolLabel(unittest.TestCase):
    """THE BUG, proven by actually calling the real (extracted) sourceLabel()
    against the real (bundle-produced) window.CR.board.toolLabel: a
    'claude-desktop' session used to print "Claude CLI" in its header
    (collapsed together with plain 'cli'/'sdk-cli'/'claude-vscode') even
    though the SAME session's rail row and board tile correctly read "claude
    desktop". Now it must not."""

    @classmethod
    def setUpClass(cls):
        js = _source_label_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "sourceLabel driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_SRCLABEL_JSON_START===")

    def test_claude_desktop_no_longer_collapses_to_claude_cli(self):
        self.assertNotEqual(self.OUT["claudeDesktop"], "Claude CLI")
        self.assertEqual(self.OUT["claudeDesktop"], "claude desktop")

    def test_plain_cli_still_resolves_via_the_real_toollabel(self):
        # Sanity control: 'cli' really does still resolve to SOMETHING
        # sensible through the delegation, not an accidental blank.
        self.assertEqual(self.OUT["cli"], "claude cli")


if __name__ == "__main__":
    unittest.main()
