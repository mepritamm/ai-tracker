"""Regression tests for two control-room top-bar fixes (ext_cr_board.js /
ext_cr_board.css):

1. TOP-BAR SIZING (owner: a real ~1900px screenshot of the top bar showing
   inconsistent control widths and the right-most "New session" button
   CLIPPED at the viewport edge):
     - `.cr-pill` (the Board / Sessions / Terminals destination pills) is the
       ONE shared rule all three already used -- it now also carries a
       `min-width`, so "Board" (4 chars) and "Terminals 0 of 10" (with its
       appended live count) read as consistently-sized controls in the same
       row instead of wildly different widths.
     - The appended live count ("Terminals 0 of 10", "Flags 0") used to be
       bare text riding on the control's own font (Terminals: a `.cr-pill-
       count` span; Flags: a literal trailing text node with a hand-written
       leading space). Both now render through the SAME `.cr-pill-count`
       "count slot": a small pill-shaped chip with `min-width` + tabular-nums,
       so the count reads as a distinct, roughly fixed-width badge rather
       than inflating the whole control. Flags reuses the identical class
       Terminals already had -- not a second count-slot system.
     - `.cr-topbar` itself gained `overflow-x: auto` as a last-resort safety
       net: every child is `flex: 0 0 auto` (never shrinks) and the >=1280px
       tiers (ext_cr_board.css, pre-existing) deliberately keep the bar to
       ONE row via icon-only compaction rather than wrapping (doc 02 line 93).
       If content ever exceeds the bar's own width for a reason that
       compaction doesn't cover (e.g. a large `--ico-scale` icon-size
       preference), this turns silent, unreachable clipping into a
       horizontally scrollable row instead -- "New session" stays reachable.
       This does not change how the bar looks when content fits (the common
       case the pre-existing tiers are tuned for): no scrollbar, no visual
       change.

2. ALERTS MUTE PARITY (owner: classic's own bell -- app.css `.bell`,
   index.html's `#i-bell`/`#i-bell-off` symbols, app.js's `setBell()` --
   swaps to a struck-through glyph and retitles itself when the shared sound
   setting (`soundOn`, backed by the ONE `soundOff` localStorage key) is
   muted; the control room's "Alerts" button read identically muted or not).
   `ext_cr_board.js`'s new `paintBell()` reads the SAME `soundOn` global
   (accessible as a bare identifier because page.py concatenates app.js and
   every ext_*.js into a single `<script>` tag -- confirmed by grepping
   ext_cr_dialogs.js, which already reads `soundOn`/`toggleSound` the same
   way for Config's own sound toggle) rather than inventing a second on/off
   store, and toggles `.cr-bell.is-muted` (a CSS strike-through overlay,
   icon-style-independent) plus the button's title/aria-label ("Alerts" vs
   "Alerts (muted)") -- colour/icon are never the only signal.

Scope: aitracker/web/ext_cr_board.css and ext_cr_board.js only (plus this
test file).

Idiom reused verbatim from tests/test_cr_rail_row_parity.py: `_read_page()`,
`_extract_script_content(html)`, `_extract_style_content(html)`,
`_run_node(js_source)`, `make_session(id, mtime, **overrides)`, the fixed
`NOW` clock, the `_HAS_NODE` skip guard, `_REAL_DOM_PREAMBLE` / `_REAL_DOM_MID`
/ `_bundle_js()` / `_extract_marker_json()`, and the hand-rolled real-DOM stub
baked into `_REAL_DOM_PREAMBLE` (`makeReal` / `queryAllReal` / `allTextIn`)
that drives the REAL `buildTopBar()`/`paintBell()` render through
`window.CR.board.mount()`/`.update()` -- never a no-op stub, since a class or
a title string only exists once something actually renders it.
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
# Hand-rolled DOM harness -- copied verbatim from tests/test_cr_rail_row_parity.py.
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

// data-id lookup -- queryAllReal only matches class selectors, so a separate
// walk is needed.
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

// Generic attribute lookup (used for board tiles, which carry
// `data-tile-id`, not `data-id`).
function findByAttr(root, attr, value) {
  var found = null;
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (!found && c && c._attrs && c._attrs[attr] === value) { found = c; }
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


# ---------------------------------------------------------------------------
# PART 1 -- CSS source-level checks.
# ---------------------------------------------------------------------------

def _rule_block(css, selector):
    """Same technique as tests/test_working_glow_board.py's own helper, plus
    a comment strip: `.cr-topbar`'s rule carries a long explanatory `/* ... */`
    comment INSIDE its braces (right above the real `overflow-x` declaration),
    and that comment's own prose literally contains the word "overflow-x" --
    without stripping comments first, `assertIn("overflow-x", block)` would
    pass on the COMMENT alone even with the real declaration deleted, which
    is exactly the false-negative-proof-of-fix step below is designed to
    catch."""
    selector = selector.rstrip().rstrip('{').rstrip()
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    if m is None:
        raise AssertionError("rule %r not found in assembled CSS" % selector)
    body = m.group(1)
    return re.sub(r'/\*.*?\*/', '', body, flags=re.DOTALL)


def _px_value(block, prop):
    """Extract the numeric px value of one declaration (e.g. `min-width:
    88px;` -> 88.0) from an already comment-stripped rule body. Raises if the
    property is missing or its value isn't a bare px length -- a test that
    calls this can't be satisfied by mere textual presence."""
    m = re.search(re.escape(prop) + r'\s*:\s*(-?[\d.]+)px', block)
    if m is None:
        raise AssertionError("no %r: <N>px declaration found in block:\n%s" % (prop, block))
    return float(m.group(1))


def _overflow_x_value(block):
    m = re.search(r'overflow-x\s*:\s*([a-zA-Z-]+)', block)
    if m is None:
        raise AssertionError("no overflow-x declaration found in block:\n%s" % block)
    return m.group(1).strip()


def _rotate_degrees(block):
    m = re.search(r'rotate\(\s*(-?[\d.]+)deg\s*\)', block)
    if m is None:
        raise AssertionError("no rotate(<N>deg) transform found in block:\n%s" % block)
    return float(m.group(1))


class TestTopbarSizingCssDeclarations(unittest.TestCase):
    """Pins the exact CSS this pass added/changed for the top-bar sizing fix:
    a shared min-width on the destination pills, a fixed-width tabular-nums
    count slot reused by both Terminals and Flags, and an overflow-x safety
    net on the bar itself -- so an unrelated future edit can't silently strip
    any one of the three back out.

    ADVERSARIAL REVIEW FIX: every assertion below used to check for the bare
    SUBSTRING of a property name (`assertIn("min-width", block)`), which a
    value of `0`/`hidden`/`clip`/`rotate(0deg)` satisfies just as well as the
    real fix -- each of those mutations keeps the CSS shaped like the fix
    while silently undoing what it does. Each check below now parses the
    actual VALUE and asserts it is in the range that keeps the fix's real
    effect (a non-trivial min-width, a scroll-capable overflow keyword, a
    genuinely diagonal, non-zero rotation)."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())
        if not cls.css.strip():
            raise AssertionError("no <style> content found in the assembled page")

    def test_destination_pills_have_a_shared_min_width(self):
        """`min-width: 0` (or any near-zero value) satisfies a bare substring
        check but is functionally IDENTICAL to no min-width at all -- pinning
        a real floor (>= 80px, comfortably below the actual 88px this pass
        uses but well above "effectively disabled") is what the "Board"/
        "Sessions" width-consistency fix this rule exists for actually needs."""
        block = _rule_block(self.css, ".tracker-next .cr-pill {")
        self.assertGreaterEqual(_px_value(block, "min-width"), 80)

    def test_count_slot_is_fixed_width_and_tabular(self):
        block = _rule_block(self.css, ".tracker-next .cr-pill-count {")
        self.assertIn("tabular-nums", block)
        # min-width is expressed in `ch` here (`3.4ch`) -- parse the numeric
        # value rather than accepting the bare substring (a `min-width: 0ch`
        # would keep the substring check happy while collapsing the chip).
        m = re.search(r'min-width\s*:\s*(-?[\d.]+)ch', block)
        self.assertIsNotNone(m, "expected a ch-based min-width on the count slot")
        self.assertGreaterEqual(float(m.group(1)), 2.0)

    def test_topbar_has_an_overflow_safety_net(self):
        """The row must never hard-clip its last control: if content ever
        exceeds the bar's own width, it should become scrollable rather than
        silently losing the tail (the exact reported bug). `overflow-x: clip`
        (or `visible`) would pass a bare substring/exclusion check while
        restoring the exact original bug -- `clip` is not a scroll container,
        so the tail becomes permanently unreachable, same as `hidden`. Only
        `auto`/`scroll` actually let the row become scrollable."""
        block = _rule_block(self.css, ".tracker-next .cr-topbar {")
        self.assertIn(_overflow_x_value(block), ("auto", "scroll"))

    def test_alerts_muted_state_has_a_visible_strike_rule(self):
        block = _rule_block(self.css, ".tracker-next .cr-bell.is-muted {")
        self.assertIn("opacity", block)
        strike = _rule_block(self.css, ".tracker-next .cr-bell.is-muted .tn-emo::after {")
        # `rotate(0deg)` (or 180/-180) satisfies a bare "rotate" substring
        # check while leaving the border-top line exactly horizontal -- the
        # "invisible hairline" regression this test exists to catch. A real
        # diagonal strike needs an angle meaningfully off both 0 and 90/-90;
        # the shipped value is -45deg, so a wide-but-excluding band (20-70
        # degrees off either axis) still leaves room for minor future tuning
        # without being satisfiable by 0/90/180/270.
        angle = abs(_rotate_degrees(strike)) % 180
        self.assertTrue(
            20 <= angle <= 70,
            "rotate(%sdeg) is not a genuinely diagonal strike (want 20-70 degrees off axis)" % _rotate_degrees(strike))


class TestTopbarOverflowFixTierBoundary(unittest.TestCase):
    """Pins the overflow fix itself: the icon-only compaction tier
    (originally `min-width: 1280px` / `max-width: 1439px`) must now extend
    far enough past 1439px to cover the measured worst-case content
    requirement (1319px content, needing `viewport >= 1619px` with the rail
    open at 300px -- see the file-level "ADVERSARIAL REVIEW FIX" /
    "ARITHMETIC" comment block in ext_cr_board.css above this same rule).
    Moving the upper bound back down to (or near) 1439px -- silently
    reintroducing the 1440-1618px overflow this whole pass exists to fix --
    must fail this test."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())
        if not cls.css.strip():
            raise AssertionError("no <style> content found in the assembled page")

    def test_icon_only_tier_upper_bound_clears_the_measured_worst_case(self):
        m = re.search(r'@media\s*\(min-width:\s*1280px\)\s*and\s*\(max-width:\s*(\d+)px\)', self.css)
        self.assertIsNotNone(m, "the 1280px-floor icon-only compaction tier's media query was not found at all")
        upper_bound = int(m.group(1))
        # Worst-case measured requirement (Playwright, real assembled page,
        # 3-digit flag count + 2-digit-vs-2-digit terminals count): content
        # 1319px, rail 300px open -> viewport must reach 1619px before the
        # labelled (full-text) tier is safe. 1439px (the pre-fix boundary)
        # fails this by nearly 200px; require the fixed boundary to clear the
        # measured worst case with at least a little headroom.
        self.assertGreaterEqual(
            upper_bound, 1619,
            "icon-only tier ends at %dpx, below the measured 1619px worst-case "
            "requirement -- the labelled tier would overflow again in that gap" % upper_bound)

    def test_labelled_tier_pill_count_slot_still_uses_the_shared_class(self):
        """Sanity anchor: the boundary test above is meaningless if the
        selector list inside the tier no longer matches real markup -- confirm
        the destination pills' count slot class referenced throughout this
        file is still the one ext_cr_board.js actually renders."""
        self.assertIn(".cr-pill-count", self.css)


class TestEmptyPillCountSlotHasNoFootprint(unittest.TestCase):
    """ADVERSARIAL REVIEW FIX (item 2): ext_cr_board.js builds the Terminals
    pill's count slot as an EMPTY span
    (`h('span', {class:'cr-pill-count'}, [''])`) until `ctx.terminals` exists,
    and `update()` only overwrites it once terminal data actually arrives --
    with terminals disabled/absent the span stays empty, but the base
    `.cr-pill-count` rule's `min-width`/padding/background applied regardless
    of content, rendering as a ~20px grey blob glued to "Terminals" with
    nothing in it. Verified directly in a real browser (Chromium, via
    Playwright, against the real assembled page): `.cr-pill-count:empty {
    display: none; }` collapses BOTH the never-filled initial span (a single
    zero-length Text node) and a later `update()` reset via
    `.textContent = ''` (which the DOM spec defines as removing all children
    outright) -- this class only pins the CSS-side declaration that a
    same-shaped mutation (e.g. re-adding padding/background inside the
    `:empty` block, or dropping the rule) would otherwise silently undo."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())
        if not cls.css.strip():
            raise AssertionError("no <style> content found in the assembled page")

    def test_empty_count_slot_collapses_to_display_none(self):
        block = _rule_block(self.css, ".tracker-next .cr-pill-count:empty {")
        m = re.search(r'display\s*:\s*([a-zA-Z-]+)', block)
        self.assertIsNotNone(m, "no display declaration in the :empty rule")
        self.assertEqual(m.group(1).strip(), "none")


# ---------------------------------------------------------------------------
# PART 2 -- real render: the destination pills, the two count slots, and the
# Alerts button's muted vs. unmuted DOM state.
# ---------------------------------------------------------------------------

_TOPBAR_RENDER_JS_TAIL = r"""
function classesOf(el) { return el ? Array.from(el._classes) : null; }
function lastChildOf(el) { return el ? el._children[el._children.length - 1] : null; }

var ctx = {
  icon: function (name) { return '<svg data-icon="' + name + '"></svg>'; }
};

var sessions = %(sessions)s;
var now = %(now)d;

var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, ctx);
window.CR.board.update({ sessions: sessions, now: now });

var topbar = queryAllReal(root, '.cr-topbar')[0];
var pills = queryAllReal(topbar, '.cr-pill');
var countSlots = queryAllReal(topbar, '.cr-pill-count');
var flagBtn = queryAllReal(topbar, '.cr-flagcount')[0];
var bell = queryAllReal(topbar, '.cr-bell')[0];
var bellIconWrap = bell ? (bell._children[0] && bell._children[0]._children[0]) : null;

var out = {
  topbarFound: !!topbar,
  pillCount: pills.length,
  countSlotCount: countSlots.length,
  flagLastChildClasses: classesOf(lastChildOf(flagBtn)),
  // update() mutates this span with a direct `.textContent =` assignment
  // (never rebuilds it via h()), so this reads the SAME plain property the
  // real code writes -- allTextIn() would instead walk into the STALE
  // build-time text node ('0', from h()'s children array) and never see the
  // mutation, since this stub's `.textContent` setter does not resync
  // `_children` the way a real DOM element's would.
  flagLastChildText: lastChildOf(flagBtn) ? lastChildOf(flagBtn).textContent : null,
  bellClasses: classesOf(bell),
  bellTitle: bell ? bell.getAttribute('title') : null,
  bellAriaLabel: bell ? bell.getAttribute('aria-label') : null,
  bellIconHtml: bellIconWrap ? bellIconWrap.innerHTML : null
};

console.log("===CR_TOPBAR_JSON_START===");
console.log(JSON.stringify(out));
"""


def _render_driver_js(sessions, preamble=_REAL_DOM_PREAMBLE):
    tail = _TOPBAR_RENDER_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([preamble, _bundle_js(), _REAL_DOM_MID, tail])


# Non-zero open_flags so 'flagLastChildText' actually exercises a digit, not
# just the vacuous zero every other test fixture happens to default to.
_SESSIONS = [
    make_session("s1", NOW - 5, open_flags=7),
]


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestTopbarSizingRealRender(unittest.TestCase):
    """Renders the REAL top bar (unmuted default -- no 'soundOff' key set)
    and checks the structural facts the sizing fix is supposed to produce."""

    @classmethod
    def setUpClass(cls):
        js = _render_driver_js(_SESSIONS)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Top-bar render driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_TOPBAR_JSON_START===")

    def test_topbar_renders(self):
        self.assertTrue(self.OUT["topbarFound"], "no .cr-topbar in the rendered shell")

    def test_three_destination_pills_share_one_class(self):
        """Board / Sessions / Terminals all carry `.cr-pill` -- the ONE rule
        the min-width sizing fix landed on, so all three are sized the same
        way by construction, not by three separate rules that could drift."""
        self.assertEqual(self.OUT["pillCount"], 3)

    def test_terminals_and_flags_both_use_the_one_count_slot_class(self):
        """Two count slots exist (Terminals' live count, Flags' total) and
        both are `.cr-pill-count` -- Flags reusing the SAME class Terminals
        already had, not a second count-slot system invented for it."""
        self.assertEqual(self.OUT["countSlotCount"], 2)

    def test_flags_count_renders_through_the_slot_with_no_stray_space(self):
        """Before this fix Flags appended a literal ' ' + flagTotal text
        node (a hand-written space for visual separation against its own
        bare font). The slot's own padding is the separation now, so the
        digit text itself must be exactly the number -- no leading space."""
        self.assertIn("cr-pill-count", self.OUT["flagLastChildClasses"] or [])
        self.assertEqual(self.OUT["flagLastChildText"], "7")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAlertsMuteRealRender(unittest.TestCase):
    """Two separate node runs, one per shared-mute-setting value (seeded via
    the SAME `soundOff` localStorage key classic's own bell reads, injected
    before the bundle executes so app.js's own top-level `let soundOn = ...`
    picks it up at parse time) -- proving the control room's Alerts button
    renders a genuinely different, non-colour-only state for each."""

    @classmethod
    def setUpClass(cls):
        unmuted_js = _render_driver_js(_SESSIONS)
        rc, out, err = _run_node(unmuted_js)
        if rc != 0:
            raise AssertionError("unmuted render driver failed (exit %d)\n%s\n%s" % (rc, out, err))
        cls.UNMUTED = _extract_marker_json(out, "===CR_TOPBAR_JSON_START===")

        muted_preamble = _REAL_DOM_PREAMBLE.replace(
            "try {",
            "window.localStorage.setItem('soundOff', '1');\ntry {",
            1)
        muted_js = _render_driver_js(_SESSIONS, preamble=muted_preamble)
        rc, out, err = _run_node(muted_js)
        if rc != 0:
            raise AssertionError("muted render driver failed (exit %d)\n%s\n%s" % (rc, out, err))
        cls.MUTED = _extract_marker_json(out, "===CR_TOPBAR_JSON_START===")

    def test_preamble_substitution_actually_took(self):
        """Sanity anchor: if the localStorage seed line didn't actually land
        in the muted run's source (e.g. the literal 'try {' text moved), the
        two fixtures below would be identical and every assertion past this
        one would pass VACUOUSLY. Guards against exactly that."""
        self.assertNotEqual(self.UNMUTED, self.MUTED,
                             "muted and unmuted renders are identical -- the soundOff seed did not take effect")

    def test_unmuted_alerts_button_has_no_muted_class_or_wording(self):
        self.assertNotIn("is-muted", self.UNMUTED["bellClasses"])
        self.assertEqual(self.UNMUTED["bellTitle"], "Alerts")
        self.assertEqual(self.UNMUTED["bellAriaLabel"], "Alerts")
        self.assertIn('data-icon="bell"', self.UNMUTED["bellIconHtml"] or "")

    def test_muted_alerts_button_carries_the_muted_class_and_wording(self):
        self.assertIn("is-muted", self.MUTED["bellClasses"])
        self.assertNotEqual(self.MUTED["bellTitle"], "Alerts",
                             "title must change when muted -- colour/icon must not be the only signal")
        self.assertIn("muted", (self.MUTED["bellTitle"] or "").lower())
        self.assertIn("muted", (self.MUTED["bellAriaLabel"] or "").lower())

    def test_muted_alerts_button_swaps_to_the_bell_off_glyph(self):
        self.assertIn('data-icon="bell-off"', self.MUTED["bellIconHtml"] or "")


if __name__ == "__main__":
    unittest.main()
