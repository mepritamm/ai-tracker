"""Regression tests for the "glowing bulb" WORKING indicator (owner's own
words: "for both sessions and the board have the glowing bulb always on for
the working on the live sessions/board tile for those sessions such that
that's easily identifiable").

Scope: aitracker/web/ext_cr_board.css only (plus this test file) -- no JS
change was needed. The WORKING predicate itself
(`isWorking(s, live) = live && (!s.ended || !!s.bg)`, ext_cr_board.js) and the
class ext_cr_board.js already attaches for it were already correct and are
NOT re-derived here:

  * `.cr-rail-dot` / `.cr-orb-pip` already carry class `is-live` for, and
    ONLY for, sessionState()'s 'working' state (STATE_DOT_CLASS's
    `working: 'is-live'`) -- the same shared isWorking()/sessionState()
    predicate the board tile and the triage strip use. `is-live` had no glow
    at all before this change: a flat 7px/8px dot.
  * `.cr-tile--working` already got an unconditional `box-shadow:
    var(--glow-agent-soft), var(--shadow-raised)` -- already "always on" in
    the sense of never being hover/selection-gated, but sharing the same
    generic glow token as plain selection/agent accents elsewhere on this
    board (`.cr-orb--selected`, `.cr-rail-row--selected`), so a working tile
    did not read as visually DISTINCT. Judgement: strengthen it to the new
    canonical `--glow-working` token (wider spread + higher alpha than
    --glow-agent-soft in both palettes, ext_cr.css) rather than leave it
    as-is.

THE FIX (ext_cr_board.css, this pass):
  - `.cr-rail-dot.is-live`  gains `box-shadow: var(--glow-working, var(--glow-agent-soft))`
  - `.cr-orb-pip.is-live`   gains the identical box-shadow (the collapsed-rail
    counterpart -- the pip is the ONLY state signal left once the rail
    collapses to bare orbs, so it needs the same always-on cue or the
    indicator vanishes exactly when the rail is collapsed)
  - `.cr-tile--working`     strengthened from `var(--glow-agent-soft)` alone
    to `var(--glow-working, var(--glow-agent-soft))`

All three fallbacks (`var(--glow-working, var(--glow-agent-soft))`) keep this
file correct even a moment before/without the sibling-owned tokens
(`--glow-working`/`--state-working`, ext_cr.css) landing.

None of the three declarations is an animation, so none needs a
prefers-reduced-motion guard -- a plain box-shadow is unaffected by that media
feature and remains visible with motion disabled, which is exactly what
"the static glow REMAINS" requires. The pre-existing PULSE
(`.cr-tile-dot.is-working`'s `cr-board-pulse` keyframe animation, a *different*
element -- the small dot inside a working tile's head, not the tile's own
border-glow) is untouched and its own prefers-reduced-motion block (which
turns the animation off and substitutes a static outline) is unaffected by
this change; that is pinned here too, as a non-regression check.

Colour never carries meaning alone: a working session's row/orb already
carries the word "working" in its accessible name (`orbStateWord()` ->
aria-label "<title> — working"), and a working tile already shows the visible
text "Working" (`stateWord()`) plus a distinct glyph (`stateIcon('working')`)
-- both pre-existing, confirmed here rather than re-implemented.

Idiom reused verbatim from tests/test_cr_rail_row_parity.py: `_read_page()`,
`_extract_script_content(html)`, `_extract_style_content(html)`,
`_run_node(js_source)`, `make_session(id, mtime, **overrides)`, the fixed
`NOW` clock, the `_HAS_NODE` skip guard, `_REAL_DOM_PREAMBLE` /
`_REAL_DOM_MID` / `_bundle_js()` / `_extract_marker_json()`, and the
hand-rolled real-DOM stub baked into `_REAL_DOM_PREAMBLE` (`makeReal` /
`queryAllReal` / `findRowById` / `allTextIn`) that drives the REAL
`railRow()`/`railOrb()`/`sessionTile()` render through
`window.CR.board.mount()`/`.update()` -- never a no-op stub, since a class
only exists once something actually renders it.
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
# PART 1 -- CSS source-level checks: the exact glow declarations exist, and
# the reduced-motion blocks disable the PULSE animation but never touch (or
# re-declare away) the static glow.
# ---------------------------------------------------------------------------

def _rule_block(css, selector):
    selector = selector.rstrip().rstrip('{').rstrip()
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    if m is None:
        raise AssertionError("rule %r not found in assembled CSS" % selector)
    return m.group(1)


def _reduced_motion_blocks(css):
    """Every `@media (prefers-reduced-motion: reduce) { ... }` block's inner
    text, brace-matched (these blocks nest one level of rule braces, so a
    naive non-greedy regex up to the first `}` would truncate mid-block)."""
    blocks = []
    for m in re.finditer(r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{', css):
        i = m.end()
        depth = 1
        while i < len(css) and depth > 0:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
            i += 1
        blocks.append(css[m.end():i - 1])
    return blocks


class TestWorkingGlowCssDeclarations(unittest.TestCase):
    """Pins the exact CSS this pass added: an always-on box-shadow, keyed off
    --glow-working with a safe fallback, on the rail dot, the collapsed orb
    pip, and the board's working tile -- and nowhere else (a non-working dot/
    tile must not pick up a stray glow from an unrelated rule)."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())
        if not cls.css.strip():
            raise AssertionError("no <style> content found in the assembled page")

    def test_rail_dot_working_class_has_the_glow(self):
        block = _rule_block(self.css, ".tracker-next .cr-rail-dot.is-live {")
        self.assertIn("box-shadow", block)
        self.assertIn("--glow-working", block)
        self.assertIn("var(--glow-agent-soft)", block, "must fall back if --glow-working hasn't landed yet")

    def test_orb_pip_working_class_has_the_glow(self):
        block = _rule_block(self.css, ".tracker-next .cr-orb-pip.is-live {")
        self.assertIn("box-shadow", block)
        self.assertIn("--glow-working", block)
        self.assertIn("var(--glow-agent-soft)", block)

    def test_tile_working_class_has_the_strengthened_glow(self):
        block = _rule_block(self.css, ".tracker-next .cr-tile--working {")
        self.assertIn("--glow-working", block)
        self.assertIn("var(--glow-agent-soft)", block, "must still fall back if the token hasn't landed")
        # --shadow-raised must survive the strengthening -- it wasn't part of
        # this task and dropping it would be an unrelated regression.
        self.assertIn("--shadow-raised", block)

    def test_other_dot_state_classes_get_no_glow(self):
        """Only the WORKING ('is-live') dot classes get a glow -- a sibling
        state (e.g. waiting) must not have picked one up by an over-broad
        selector or a copy/paste."""
        for cls in ("is-waiting", "is-flagged", "is-landed", "is-failing"):
            block = _rule_block(self.css, ".tracker-next .cr-rail-dot.%s {" % cls)
            self.assertNotIn("box-shadow", block, "%s must not carry a glow" % cls)

    def test_glow_working_token_resolves_to_a_visible_glow_in_both_palettes(self):
        """ADVERSARIAL REVIEW FIX: every assertion above only checks that the
        board's own rules REFERENCE `--glow-working` by name
        (`var(--glow-working, ...)`) -- none of them look at what that token
        actually RESOLVES to. `--glow-working` is defined once per palette in
        ext_cr.css (a sibling file this test suite doesn't own and never
        reads directly), not in this file's own board-CSS blocks, so a
        mutation there -- e.g. `--glow-working: 0 0 0 rgba(0,0,0,0);` --
        leaves every assertion above passing while the glow on the rail dot,
        the orb pip AND the tile is completely invisible. This test resolves
        the token from the FULLY ASSEMBLED page (app.css + every ext_*.css
        concatenated into one <style>, exactly what a real browser parses --
        see aitracker/page.py) and requires each definition to carry a
        non-zero blur/spread radius AND a non-zero alpha channel, i.e. an
        actual box-shadow value, not a value that resolves to nothing."""
        # Strip comments first -- ext_cr.css's own --glow-working definitions
        # are preceded by long explanatory block comments whose PROSE also
        # contains the literal string "--glow-working:" (e.g. "the light
        # block's own --glow-working:" style cross-references), which a
        # comment-unaware regex would happily match instead of (or as well
        # as) the real declaration, exactly the false-positive trap
        # `_rule_block()` above already guards against for the same reason.
        css_no_comments = re.sub(r'/\*.*?\*/', '', self.css, flags=re.DOTALL)
        declarations = re.findall(r'--glow-working\s*:\s*([^;]+);', css_no_comments)
        # Two palettes define this token (light default block, `.is-dark`
        # override) -- both must exist and both must be genuinely visible;
        # relying on only one would miss a regression confined to the other.
        self.assertGreaterEqual(
            len(declarations), 2,
            "expected at least 2 --glow-working token definitions (light + dark "
            "palette) in the assembled CSS, found %d: %r" % (len(declarations), declarations))
        for value in declarations:
            # Blur radius may legally appear as a bare `0` in CSS (no unit
            # required on a zero length) as well as `<N>px` -- match both so
            # a mutation like `--glow-working: 0 0 0 rgba(0,0,0,0);` still
            # parses far enough to hit the blur/alpha assertions below,
            # rather than failing on a parse error that would mask them.
            m = re.search(r'(-?[\d.]+)(?:px)?\s+rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)', value)
            self.assertIsNotNone(
                m, "could not parse a `<blur>[px] rgba(r,g,b,<alpha>)` box-shadow out of "
                   "--glow-working: %r" % value)
            blur = float(m.group(1))
            alpha = float(m.group(2))
            self.assertGreater(blur, 0, "--glow-working %r has a zero blur radius -- no visible glow" % value)
            self.assertGreater(alpha, 0, "--glow-working %r has a zero alpha -- fully transparent, invisible" % value)

    def test_reduced_motion_disables_the_pulse_animation_only(self):
        """The pre-existing tile-dot PULSE (a different element from the
        static glow this pass added) must still be disabled under reduced
        motion -- non-regression check."""
        blocks = _reduced_motion_blocks(self.css)
        self.assertTrue(
            any("cr-tile-dot.is-working" in b and "animation: none" in b for b in blocks),
            "no reduced-motion block disables .cr-tile-dot.is-working's pulse")

    def test_reduced_motion_never_touches_the_static_glow(self):
        """None of the three glow declarations this pass added are
        re-declared (and so potentially zeroed out) inside ANY
        prefers-reduced-motion block -- the static glow is unconditional and
        therefore survives reduced motion by construction, exactly what
        "the static glow REMAINS" requires."""
        blocks = _reduced_motion_blocks(self.css)
        combined = "\n".join(blocks)
        self.assertNotIn("cr-rail-dot.is-live", combined)
        self.assertNotIn("cr-orb-pip.is-live", combined)
        self.assertNotIn("cr-tile--working", combined)


# ---------------------------------------------------------------------------
# PART 2 -- real render: which sessions actually pick up the glow-bearing
# classes, in the rail row, the collapsed orb, and the board tile. This is
# the part that catches a lazy `live`-only (or `ended`-only) implementation:
# the four fixtures below deliberately separate every combination of
# live/ended/bg the WORKING predicate cares about.
# ---------------------------------------------------------------------------

_RENDER_JS_TAIL = r"""
function classesOf(el) { return el ? Array.from(el._classes) : null; }
function orbByTitlePrefix(root, prefix) {
  var orbs = queryAllReal(root, '.cr-orb');
  for (var i = 0; i < orbs.length; i++) {
    var t = orbs[i]._attrs && orbs[i]._attrs.title;
    if (t && t.indexOf(prefix) === 0) return orbs[i];
  }
  return null;
}

var sessions = %(sessions)s;
var now = %(now)d;

var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: sessions, now: now });

var out = { rail: {}, tile: {}, pureState: {}, orb: {} };
sessions.forEach(function (s) {
  out.pureState[s.id] = window.CR.board.sessionState(s, now);
  var row = findRowById(root, s.id);
  var dot = row ? queryAllReal(row, '.cr-rail-dot')[0] : null;
  out.rail[s.id] = classesOf(dot);
  var tile = findByAttr(root, 'data-tile-id', s.id);
  out.tile[s.id] = classesOf(tile);
});

// Second render, rail forced to the COLLAPSED orb strip -- same technique
// applyRailMode() itself uses (toggling the class on the real, already-
// mounted `.cr-rail` node), then re-running update() so renderRail()'s own
// `collapsed = els.rail.classList.contains('cr-rail--collapsed')` check
// (read fresh every render) takes the branch that builds orbs instead of rows.
var railEl = queryAllReal(root, '.cr-rail')[0];
railEl.classList.add('cr-rail--collapsed');
window.CR.board.update({ sessions: sessions, now: now });
sessions.forEach(function (s) {
  var orb = orbByTitlePrefix(root, s.title);
  var pip = orb ? queryAllReal(orb, '.cr-orb-pip')[0] : null;
  out.orb[s.id] = classesOf(pip);
});

console.log("===CR_WORKINGGLOW_JSON_START===");
console.log(JSON.stringify(out));
"""


def _render_driver_js(sessions):
    tail = _RENDER_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, _bundle_js(), _REAL_DOM_MID, tail])


# Four fixtures, each isolating one cell of the WORKING predicate
# (`isWorking(s, live) = live && (!s.ended || !!s.bg)`, ext_cr_board.js):
#   working_live      live, not ended                      -> WORKING
#   landed_live       live, ended, bg=0                     -> NOT working (landed)
#   working_ended_bg  live, ended, bg=2                     -> WORKING (the bg-aware fix)
#   idle_stale_bg     NOT live, ended, bg=2                 -> NOT working (idle) -- bg alone,
#                     without liveness, must not force "working"
_SESSIONS = [
    make_session("s_working_live", NOW - 5, ended=False, bg=0, title="AlphaWorkingLive"),
    make_session("s_landed_live", NOW - 5, ended=True, bg=0, title="BetaLandedLive"),
    make_session("s_working_ended_bg", NOW - 5, ended=True, bg=2, title="GammaWorkingEndedBg"),
    make_session("s_idle_stale_bg", NOW - 10_000, ended=True, bg=2, title="DeltaIdleStaleBg"),
]


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestWorkingGlowRealRender(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _render_driver_js(_SESSIONS)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Working-glow render driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_WORKINGGLOW_JSON_START===")

    # -- the pure predicate itself, as a sanity anchor for the DOM assertions below --

    def test_pure_state_matches_the_four_predicate_cells(self):
        self.assertEqual(self.OUT["pureState"]["s_working_live"], "working")
        self.assertEqual(self.OUT["pureState"]["s_landed_live"], "landed")
        self.assertEqual(self.OUT["pureState"]["s_working_ended_bg"], "working")
        self.assertEqual(self.OUT["pureState"]["s_idle_stale_bg"], "idle")

    # -- rail row dot --

    def test_rail_dot_carries_glow_class_for_working_sessions(self):
        self.assertIn("is-live", self.OUT["rail"]["s_working_live"])
        self.assertIn("is-live", self.OUT["rail"]["s_working_ended_bg"],
                       "ended-but-has-background-agents session must still read as working")

    def test_rail_dot_does_not_carry_glow_class_for_non_working_sessions(self):
        self.assertNotIn("is-live", self.OUT["rail"]["s_landed_live"],
                          "live+ended+no-bg must NOT be treated as working")
        self.assertNotIn("is-live", self.OUT["rail"]["s_idle_stale_bg"])

    # -- collapsed orb pip (the rail parity requirement: the indicator must not
    #    vanish once the rail collapses to bare orbs) --

    def test_orb_pip_carries_glow_class_for_working_sessions(self):
        self.assertIsNotNone(self.OUT["orb"]["s_working_live"], "orb pip did not render at all")
        self.assertIn("is-live", self.OUT["orb"]["s_working_live"])
        self.assertIsNotNone(self.OUT["orb"]["s_working_ended_bg"])
        self.assertIn("is-live", self.OUT["orb"]["s_working_ended_bg"])

    def test_orb_pip_does_not_carry_glow_class_for_non_working_sessions(self):
        self.assertIsNotNone(self.OUT["orb"]["s_landed_live"], "orb pip did not render at all")
        self.assertNotIn("is-live", self.OUT["orb"]["s_landed_live"])
        self.assertIsNotNone(self.OUT["orb"]["s_idle_stale_bg"])
        self.assertNotIn("is-live", self.OUT["orb"]["s_idle_stale_bg"])

    # -- board tile --

    def test_tile_carries_working_class_for_working_sessions(self):
        self.assertIsNotNone(self.OUT["tile"]["s_working_live"], "tile did not render at all")
        self.assertIn("cr-tile--working", self.OUT["tile"]["s_working_live"])
        self.assertIsNotNone(self.OUT["tile"]["s_working_ended_bg"])
        self.assertIn("cr-tile--working", self.OUT["tile"]["s_working_ended_bg"],
                       "ended-but-has-background-agents tile must still read as working")

    def test_tile_does_not_carry_working_class_for_non_working_sessions(self):
        self.assertIsNotNone(self.OUT["tile"]["s_landed_live"], "tile did not render at all")
        self.assertNotIn("cr-tile--working", self.OUT["tile"]["s_landed_live"])
        self.assertIsNotNone(self.OUT["tile"]["s_idle_stale_bg"])
        self.assertNotIn("cr-tile--working", self.OUT["tile"]["s_idle_stale_bg"])


if __name__ == "__main__":
    unittest.main()
