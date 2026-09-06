"""Regression tests for the control-room "session rail polish" pass:

FIX 1 -- raw HTML leaking into rail/tile labels. `toolLabel()` (ext_cr_board.js)
used to derive its plain-text word by regex-stripping app.js's HTML-bearing
`SRC` map (`ico(name)+" "+text`) with `/^\\S+\\s*/` -- that only strips the icon
tag's FIRST whitespace-free token (`<svg`/`<span`), so the tag's OWN attributes
rendered as literal visible text whenever the icon markup carried more than one
token (e.g. `class="ico ico-glyph" aria-hidden="true">CLI`). Fixed at the
shared seam, not with a local regex patch: app.js now exports `SRC_TEXT`/
`srcText`, a plain-TEXT-only map with no markup at all, and `SRC` (the
HTML-bearing map every OTHER consumer -- app.js's own renderSide(), etc. --
still uses unchanged) is built FROM it. `toolLabel()` reads `srcText()`
directly, so there is nothing left to strip.

FIX 2 -- rail row parity markers (pinned/waiting/done/flagged/agent) the
classic sidebar (`app.js` sessionRow()) has always carried on the row itself
(background/border modifier classes, an agent-icon name prefix), missing from
the control-room rail row before this pass.

Idiom: same "assemble the real page, run the bundle under a real (tracked) DOM
stub" technique tests/test_cr_logic.py's TestCRFailingTileRender uses -- a
hand-rolled DOM with real classList/appendChild/textContent bookkeeping (never
the no-op stub some OTHER tests in that file use for pure functions), because
what's under test here only exists inside an actual render.
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
# FIX 1a -- Python-only checks on the served page's JS SOURCE TEXT (no node
# needed): the shared plain-text seam exists, and the old fragile regex is
# actually gone (not just superseded by dead code sitting alongside it).
# ---------------------------------------------------------------------------

class TestSourceLabelSharedSeam(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def test_plain_text_source_map_exists(self):
        self.assertIn("const SRC_TEXT=", self.bundle)
        self.assertIn("const srcText=", self.bundle)

    def test_html_source_map_is_built_from_the_text_map_not_a_second_literal(self):
        """SRC must be DERIVED from SRC_TEXT (ico(name)+" "+SRC_TEXT[k]) --
        never a second hand-written table that could drift from it."""
        self.assertIn("SRC[k]=ico(SRC_ICON[k])+\" \"+SRC_TEXT[k]", self.bundle)

    def test_old_fragile_strip_regex_is_gone(self):
        """THE BUG: stripping SRC's icon markup with `^\\S+\\s*` only removes
        the tag's first whitespace-free token, leaving its OWN attributes as
        literal text. This exact pattern must never reappear anywhere in the
        bundle -- not just inside toolLabel()."""
        self.assertNotIn(r"replace(/^\S+\s*/", self.bundle)

    def test_tool_label_reads_srctext_not_srclabel(self):
        m = re.search(r'function\s+toolLabel\s*\([^)]*\)\s*\{', self.bundle)
        self.assertIsNotNone(m, "toolLabel() not found in the real bundle")
        brace_start = self.bundle.index('{', m.start())
        depth, end = 0, None
        for i in range(brace_start, len(self.bundle)):
            c = self.bundle[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        self.assertIsNotNone(end, "unterminated toolLabel() (brace mismatch)")
        fn_src = self.bundle[m.start():end]
        self.assertIn("srcText(", fn_src)
        self.assertNotIn("srcLabel(", fn_src)

    def test_no_source_label_value_contains_markup(self):
        """Regression guard: whatever SRC_TEXT actually contains today, none
        of its VALUES may contain a `<` -- if one ever did, it would prove
        HTML crept back into the plain-text map this whole fix exists to keep
        clean."""
        m = re.search(r'const SRC_TEXT=\{(.*?)\};', self.bundle)
        self.assertIsNotNone(m, "SRC_TEXT literal not found in the real bundle")
        values = re.findall(r':"([^"]*)"', m.group(1))
        self.assertGreaterEqual(len(values), 7, "expected at least the 7 known source ids")
        for v in values:
            self.assertNotIn("<", v, "SRC_TEXT value contains markup: %r" % v)


# ---------------------------------------------------------------------------
# FIX 1b -- end-to-end: drive the REAL mount()/update() render path (not just
# the source text above) and prove neither the rail row's meta line nor the
# board tile's trailing/sub lines ever render icon markup as literal text --
# the user's actual observed symptom ("ai-tracker · claude class="ico"
# viewbox="0 0 24 24" aria-hidden=...") in BOTH the rail and the board tiles.
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
  // renderRail()/renderBoard()/renderTriage() all clear their container with
  // `list.innerHTML = ''` before re-appending fresh rows on every poll --
  // WITHOUT this, `mount()`'s own applyRailMode() (which renders the rail
  // once against whatever `lastState` a PRIOR mount() call in the same test
  // left behind) leaves a stale row sitting in `_children` ahead of the row
  // this test's own update() call just appended, and `_children[0]` silently
  // picks up the wrong (previous scenario's) row.
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
  el.addEventListener = function () {}; el.removeEventListener = function () {};
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

_LEAK_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
window.CR.board.update({ sessions: [%(session)s], now: %(now)d });

var railText = allTextIn(root);
var out = { railText: railText };

console.log("===CR_LEAK_JSON_START===");
console.log(JSON.stringify(out));
"""


def _leak_driver_js(session):
    bundle_js = _extract_script_content(_read_page())
    tail = _LEAK_JS_TAIL % {"session": json.dumps(session), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_leak_json(stdout):
    marker = "===CR_LEAK_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestNoIconMarkupLeaksAsRailOrTileText(unittest.TestCase):
    """THE BUG (user's own screenshot, both the rail row and the board tile):
    'ai-tracker · claude class="ico" viewbox="0 0 24 24" aria-hidden=...'.
    Drives the REAL render path end to end (mount -> update -> the actual DOM
    text) for every known `source` id, rather than just asserting on
    toolLabel()'s isolated return value -- this is what the user actually saw
    on screen."""

    SOURCE_IDS = ["cli", "claude-desktop", "sdk-cli", "claude-vscode",
                  "auggie", "augment-vscode", "augment-cursor"]

    @classmethod
    def setUpClass(cls):
        cls.rendered = {}
        for source in cls.SOURCE_IDS:
            session = make_session("leak_" + source, NOW - 5, source=source, ended=False)
            js = _leak_driver_js(session)
            returncode, stdout, stderr = _run_node(js)
            if returncode != 0:
                raise AssertionError(
                    "Leak driver failed for source=%r (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                    % (source, returncode, stdout, stderr)
                )
            cls.rendered[source] = _extract_leak_json(stdout)["railText"]

    def test_no_source_id_leaks_svg_markup(self):
        for source, text in self.rendered.items():
            self.assertNotIn("<svg", text, "source=%r rendered raw SVG markup as text: %r" % (source, text))
            self.assertNotIn('viewBox', text, "source=%r leaked a viewBox attribute as text: %r" % (source, text))
            self.assertNotIn('viewbox', text, "source=%r leaked a viewBox attribute as text: %r" % (source, text))

    def test_no_source_id_leaks_glyph_span_markup(self):
        for source, text in self.rendered.items():
            self.assertNotIn('ico-glyph', text, "source=%r leaked glyph-span markup as text: %r" % (source, text))
            self.assertNotIn('class="ico', text, "source=%r leaked an icon class attribute as text: %r" % (source, text))
            self.assertNotIn('aria-hidden', text, "source=%r leaked an aria-hidden attribute as text: %r" % (source, text))

    def test_every_source_id_still_shows_its_real_word(self):
        """Sanity control: the fix must not have gone too far the OTHER way --
        the tool word is still actually present, not blanked."""
        expectations = {
            "cli": "claude cli", "claude-desktop": "claude desktop", "sdk-cli": "claude sdk",
            "claude-vscode": "claude vs code", "auggie": "auggie cli",
            # toolLabel() strips parens after lowercasing -- "Augment (VS Code)"
            # -> "augment (vs code)" -> "augment vs code".
            "augment-vscode": "augment vs code", "augment-cursor": "augment cursor",
        }
        for source, word in expectations.items():
            self.assertIn(word, self.rendered[source], "source=%r: expected %r in %r" % (source, word, self.rendered[source]))


# ---------------------------------------------------------------------------
# FIX 2 -- rail row parity markers (pinned/waiting/done/flagged/agent),
# driven through the same REAL mount()/update() render path.
# ---------------------------------------------------------------------------

_PARITY_JS_TAIL = r"""
function classesFor(session) {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: [session], now: %(now)d });
  var rows = queryAllReal(root, '.cr-rail-row');
  if (!rows.length) return null;
  return Array.from(rows[0]._classes);
}

var NOW = %(now)d;
var out = {};
out.pinned  = classesFor(%(pinned)s);
out.waiting = classesFor(%(waiting)s);
out.done    = classesFor(%(done)s);
out.flagged = classesFor(%(flagged)s);
out.plain   = classesFor(%(plain)s);

console.log("===CR_PARITY_JSON_START===");
console.log(JSON.stringify(out));
"""


def _parity_driver_js():
    bundle_js = _extract_script_content(_read_page())
    pinned = make_session("p_pin", NOW - 5000, ended=True, pinned=True)
    waiting = make_session("p_wait", NOW - 5, waiting=True)
    done = make_session("p_done", NOW - 5, ended=True)
    flagged = make_session("p_flag", NOW - 5000, ended=True, open_flags=2)
    plain = make_session("p_plain", NOW - 5000, ended=True)
    tail = _PARITY_JS_TAIL % {
        "now": NOW,
        "pinned": json.dumps(pinned), "waiting": json.dumps(waiting),
        "done": json.dumps(done), "flagged": json.dumps(flagged), "plain": json.dumps(plain),
    }
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_parity_json(stdout):
    marker = "===CR_PARITY_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowParityMarkerClasses(unittest.TestCase):
    """The classic sidebar (app.js sessionRow()) has always painted the ROW
    ITSELF with pinned/waiting/done/flagged modifier classes -- the control
    room rail row carried none of them (only a small 7px dot's colour). Pins
    the new `.cr-rail-row--*` classes so a session's state reads at a glance
    in the rail too, the same information the classic sidebar has always
    shown."""

    @classmethod
    def setUpClass(cls):
        js = _parity_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Rail-parity driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_parity_json(stdout)

    def test_pinned_session_gets_the_pinned_row_class(self):
        self.assertIn("cr-rail-row--pinned", self.OUT["pinned"])

    def test_waiting_session_gets_the_waiting_row_class(self):
        self.assertIn("cr-rail-row--waiting", self.OUT["waiting"])

    def test_done_session_gets_the_done_row_class(self):
        self.assertIn("cr-rail-row--done", self.OUT["done"])

    def test_flagged_session_gets_the_flagged_row_class(self):
        self.assertIn("cr-rail-row--flagged", self.OUT["flagged"])

    def test_plain_session_gets_none_of_the_four(self):
        for cls_name in ("cr-rail-row--pinned", "cr-rail-row--waiting",
                          "cr-rail-row--done", "cr-rail-row--flagged"):
            self.assertNotIn(cls_name, self.OUT["plain"])


# ---------------------------------------------------------------------------
# DEFECT 1 (adversarial review, second pass) -- classic's `.sitem.hasagents`
# (app.css: a full amber border on a PARENT row whose own transcript spawned
# agent children) had no rail equivalent at all. The rail groups agent
# sessions under collapsible "Agents · <label>" buckets (renderSessionRows'
# agentBuckets, keyed by `s.group` -- the repo/sandbox) rather than nesting
# them inline under one specific parent row, so there is no per-row kids list
# to port directly. But the underlying FACT -- did THIS session specifically
# originate one or more agent sessions -- is still just `s.agent && s.parentId`
# on the full session list (the same field classic's own kids[s.parentId]
# nesting reads, from providers/claude.py's _pick_parent()), independent of
# where the children are displayed. `railAgentParentIds` (ext_cr_board.js)
# computes that set once per render; `railRow()` reads it to add
# `cr-rail-row--hasagents`. Fed the parent + child in the SAME update() call
# (both must be in state.sessions for the linkage to be seen), then looks the
# PARENT row up by `data-id` (queryAllReal only matches class selectors).
# ---------------------------------------------------------------------------

_HASAGENTS_JS_TAIL = r"""
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

function classesForId(sessions, id) {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: sessions, now: %(now)d });
  var row = findRowById(root, id);
  return row ? Array.from(row._classes) : null;
}

var out = {};
out.withKids = classesForId([%(parentWithKids)s, %(agentChild)s], "parent_has_kids");
out.withoutKids = classesForId([%(parentPlain)s], "parent_plain");

console.log("===CR_HASAGENTS_JSON_START===");
console.log(JSON.stringify(out));
"""


def _hasagents_driver_js():
    bundle_js = _extract_script_content(_read_page())
    parent_with_kids = make_session("parent_has_kids", NOW - 5000, ended=True)
    agent_child = make_session("agent_child", NOW - 10, agent=True,
                                parentId="parent_has_kids", group="g1", groupLabel="repo")
    parent_plain = make_session("parent_plain", NOW - 5000, ended=True)
    tail = _HASAGENTS_JS_TAIL % {
        "now": NOW,
        "parentWithKids": json.dumps(parent_with_kids),
        "agentChild": json.dumps(agent_child),
        "parentPlain": json.dumps(parent_plain),
    }
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_hasagents_json(stdout):
    marker = "===CR_HASAGENTS_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowHasAgentsMarkerParity(unittest.TestCase):
    """The user's own requirement, verbatim: 'the session markers/pinned and
    other pieces of information must be same in both the UIs.' Pins the rail's
    `cr-rail-row--hasagents` modifier: present on a session that specifically
    originated an agent child (`agent_child.parentId == "parent_has_kids"`),
    absent on one that did not."""

    @classmethod
    def setUpClass(cls):
        js = _hasagents_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "hasagents driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_hasagents_json(stdout)

    def test_parent_with_agent_children_gets_the_hasagents_row_class(self):
        self.assertIsNotNone(self.OUT["withKids"], "parent row did not render")
        self.assertIn("cr-rail-row--hasagents", self.OUT["withKids"])

    def test_parent_without_agent_children_does_not_get_it(self):
        self.assertIsNotNone(self.OUT["withoutKids"], "parent row did not render")
        self.assertNotIn("cr-rail-row--hasagents", self.OUT["withoutKids"])


# ---------------------------------------------------------------------------
# DEFECT FIX (adversarial review) -- TestRailRowParityMarkerClasses above never
# exercises bg>0: make_session() defaults `bg: 0`, and a repo-wide grep found NO
# test anywhere that renders a rail row with bg>0. So railRow()'s
# `!isWorking(s, isLiveRow)` guard on `statusKind` was a no-op the whole suite
# never caught -- reverting it back to the pre-fix `(s.ended && isLiveRow)` left
# every test here GREEN. These fixtures set bg>0 specifically to close that gap,
# and also pin the cross-view PARITY requirement verbatim from the user
# ("the session markers/pinned and other pieces of information must be same in
# both the UIs"): the exact same session dict fed to classic's sessionRow()
# (app.js) and to the rail's isWorking()/sessionState() (ext_cr_board.js) must
# agree -- both now call the ONE shared global, app.js's isSessionWorking().
# ---------------------------------------------------------------------------

_BG_WORKING_JS_TAIL = r"""
function rowInfo(session) {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: [session], now: %(now)d });
  var rows = queryAllReal(root, '.cr-rail-row');
  if (!rows.length) return null;
  var row = rows[0];
  var dots = queryAllReal(row, '.cr-rail-dot');
  return {
    rowClasses: Array.from(row._classes),
    dotClasses: dots.length ? Array.from(dots[0]._classes) : []
  };
}

var bgWorking = %(bgWorking)s;
var bgDone = %(bgDone)s;
var out = {};
out.bgWorking = rowInfo(bgWorking);
out.bgDone = rowInfo(bgDone);
// CROSS-VIEW PARITY (DEFECT 1): classic's OWN row render (app.js's sessionRow,
// a global function -- the bundle is one <script> tag) for the EXACT SAME
// session objects, so a single fixture proves both views agree.
out.classicBgWorkingHtml = sessionRow(bgWorking, %(now)d);
out.classicBgDoneHtml = sessionRow(bgDone, %(now)d);

console.log("===CR_BGWORK_JSON_START===");
console.log(JSON.stringify(out));
"""


def _bg_working_driver_js():
    bundle_js = _extract_script_content(_read_page())
    bg_working = make_session("bg_working", NOW - 5, ended=True, bg=3)
    bg_done = make_session("bg_done", NOW - 5, ended=True, bg=0)
    tail = _BG_WORKING_JS_TAIL % {
        "now": NOW,
        "bgWorking": json.dumps(bg_working),
        "bgDone": json.dumps(bg_done),
    }
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_bg_working_json(stdout):
    marker = "===CR_BGWORK_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowBackgroundAgentsStillWorking(unittest.TestCase):
    """Renders a REAL rail row (mount -> update -> DOM) for a session shaped
    exactly like production's reported bug (`ended: true, bg: 3`, fresh mtime)
    and asserts it gets the working treatment, not the done one -- and that
    classic's sidebar renders the SAME verdict for the SAME session object."""

    @classmethod
    def setUpClass(cls):
        js = _bg_working_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "bg-working driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_bg_working_json(stdout)

    def test_ended_with_live_background_agents_is_not_marked_done_on_the_rail(self):
        info = self.OUT["bgWorking"]
        self.assertIsNotNone(info, "rail row did not render for the bg-working session")
        self.assertNotIn("cr-rail-row--done", info["rowClasses"],
                          "ended:true, bg:3, fresh mtime must NOT get the done row class")

    def test_ended_with_live_background_agents_gets_the_working_dot(self):
        info = self.OUT["bgWorking"]
        self.assertIn("is-live", info["dotClasses"],
                      "a session with live background agents must show the SAME dot as "
                      "any other working session (sessionState() -> 'working' -> is-live)")

    def test_genuinely_ended_session_with_no_bg_agents_still_gets_done_on_the_rail(self):
        # Sanity control: the fix must not have gone too far the other way --
        # an ended session with NO background agents is still marked done.
        info = self.OUT["bgDone"]
        self.assertIn("cr-rail-row--done", info["rowClasses"])
        self.assertNotIn("is-live", info["dotClasses"])

    def test_classic_sidebar_agrees_the_bg_working_session_is_not_done(self):
        """CROSS-VIEW PARITY -- the user's requirement, verbatim: "the session
        markers/pinned and other pieces of information must be same in both
        the UIs". Classic's sessionRow() for the EXACT SAME session dict the
        rail just rendered as "working" must not carry the done row class or
        the done badge either."""
        html = self.OUT["classicBgWorkingHtml"]
        row_class = re.search(r'class="(sitem[^"]*)"', html).group(1)
        self.assertNotIn("done", row_class.split(),
                          "classic must not add the done row class while background agents run")
        self.assertNotIn("statusbadge done", html,
                          "classic must not show the done checkmark badge while background agents run")
        self.assertIn("3 running", html, "classic's own bgchip must still report the running agents")

    def test_classic_sidebar_agrees_the_genuinely_done_session_is_done(self):
        # Sanity control, mirroring the rail's own control above. sessionRow()
        # concatenates several optional class ternaries ahead of `status`
        # (active/pinned/agentrow/hasagents, all empty here), so the row's
        # class attribute reads `class="sitem  done"` (extra space) -- match
        # via regex on the actual class attribute rather than assume spacing.
        html = self.OUT["classicBgDoneHtml"]
        row_class = re.search(r'class="(sitem[^"]*)"', html).group(1)
        self.assertIn("done", row_class.split())
        self.assertIn("statusbadge done", html)


# ---------------------------------------------------------------------------
# FIX 3 -- collapsed rail alignment (48px orb column).
#   (a) a vertical scrollbar inside the 48px column eats width, shifting the
#       centred orbs left whenever it's present -- fixed with
#       `scrollbar-width: none` (Firefox) + `::-webkit-scrollbar{width:0}`
#       (Chrome/Safari) on the COLLAPSED list only (the expanded list keeps
#       its normal, visible scrollbar).
#   (b) the footer's "scroll · N more" wraps/clips at 48px wide -- collapsed
#       gets a compact "+N" instead (ext_cr_board.js renderRail()).
#   (c) the collapsed header's brand mark + now-empty title-group used to
#       fight `justify-content: center` for space -- both hidden so the
#       collapse/expand toggle alone centres cleanly.
# ---------------------------------------------------------------------------

def _extract_style_content(html):
    m = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
    if not m:
        raise AssertionError("No <style> tag found in assembled page")
    return m.group(1)


class TestCollapsedRailAlignmentCss(unittest.TestCase):
    """Text-level checks (no node needed) that the actual fix rules exist in
    the assembled CSS -- test_page_css.py already guards against a syntax
    error blanking rules like these silently; this pins their PRESENCE."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())

    def test_collapsed_list_hides_its_scrollbar_both_ways(self):
        self.assertIn(".tracker-next .cr-rail--collapsed .cr-rail-list", self.css)
        self.assertIn("scrollbar-width: none", self.css)
        self.assertIn(".tracker-next .cr-rail--collapsed .cr-rail-list::-webkit-scrollbar", self.css)

    def test_collapsed_header_hides_the_now_empty_title_group_and_brand(self):
        self.assertIn(".tracker-next .cr-rail--collapsed .cr-rail-title-group { display: none; }", self.css)
        self.assertIn(".tracker-next .cr-rail--collapsed .cr-rail-brand { display: none; }", self.css)

    def test_collapsed_header_still_centres_its_remaining_content(self):
        m = re.search(
            r'\.tracker-next \.cr-rail--collapsed \.cr-rail-header\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".cr-rail--collapsed .cr-rail-header rule not found")
        self.assertIn("justify-content: center", m.group(1))

    def test_orb_size_and_rail_width_are_unchanged(self):
        """This fix is explicitly scoped to alignment, not sizing -- pins that
        the 48px collapsed width and 28px orb size were not touched."""
        self.assertIn(".tracker-next .cr-rail--collapsed { width: 48px; }", self.css)
        self.assertIn("width: 28px;", self.css)

    def test_collapsed_footer_has_its_own_compact_rule(self):
        """DEFECT 2 (adversarial review): `.cr-rail-footer`'s base rule
        (padding: 8px 14px) leaves only ~20px of content width once the
        collapsed rail's 48px `overflow: hidden` (this class's own rule
        above) is accounted for -- fine for the expanded phrase, but the
        collapsed "+N" token has no spaces to wrap on, so it silently clips
        at 3-4 digits with no override. Pins that a collapsed-specific rule
        exists with tighter padding and `white-space: nowrap` (so the
        rendered token can never wrap/clip mid-digit)."""
        m = re.search(
            r'\.tracker-next \.cr-rail--collapsed \.cr-rail-footer\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".cr-rail--collapsed .cr-rail-footer rule not found")
        rule = m.group(1)
        self.assertIn("white-space: nowrap", rule)
        # tighter than the base rule's "8px 14px" -- must actually shrink, not just repeat it
        self.assertNotIn("14px", rule)


_FOOTER_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
var railEl = queryAllReal(root, '.cr-rail')[0];
var footer = queryAllReal(root, '.cr-rail-footer')[0];

var sessions = %(sessions)s;
window.CR.board.update({ sessions: sessions, now: %(now)d });
var out = { expanded: footer.textContent };

railEl.classList.add('cr-rail--collapsed');
window.CR.board.update({ sessions: sessions, now: %(now)d });
out.collapsed = footer.textContent;
out.collapsedTitle = footer.title;

railEl.classList.remove('cr-rail--collapsed');
window.CR.board.update({ sessions: sessions, now: %(now)d });
out.expandedAgain = footer.textContent;

console.log("===CR_FOOTER_JSON_START===");
console.log(JSON.stringify(out));
"""


def _footer_driver_js():
    bundle_js = _extract_script_content(_read_page())
    # One plain session (renders as an individual row) plus three folded into
    # an agent bucket -- excluded from the individual rows, so the rail's own
    # "more" count (baseSessions.length - shown) is exactly 3.
    sessions = [make_session("f_plain", NOW - 5, ended=True)]
    for i in range(3):
        sessions.append(make_session("f_agent_%d" % i, NOW - 5, agent=True, group="g1", groupLabel="repo"))
    tail = _FOOTER_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_footer_json(stdout):
    marker = "===CR_FOOTER_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCollapsedRailFooterIsCompact(unittest.TestCase):
    """THE BUG: the expanded footer's "scroll · N more" wraps and clips to
    "scrol . N more" at the 48px collapsed width. Collapsed now renders a
    compact "+N" with no wrapping; the collapsed form must stay byte-for-byte
    what it always was.

    ADVERSARIAL REVIEW FIX (since this class was first written): the expanded
    sentence used to be `hidden = baseSessions.length - shown`, subtracting
    two DIFFERENT populations -- `shown` counts only non-agent,
    search-surviving, cap-admitted rows, while `baseSessions` counts EVERY
    session including agent ones already visible inside their "Agents"
    buckets. So it claimed sessions were hidden when they were already on
    screen. It's now `hidden = res.total - res.shown` (the SAME population),
    which for this fixture (1 individual session, 3 folded into an agent
    bucket that's fully visible) is exactly 0 -- so the expanded footer reads
    the plain "N session(s) · all shown" sentence, not "scroll · N more". The
    ORIGINAL INTENT of this class -- collapsed gets a compact "+N" because the
    full sentence clips at 48px, expanded keeps the full sentence -- is
    unchanged; only the full sentence's WORDING is. The "Show N more · M
    hidden" branch (reachable once the unpinned rows exceed the 25-row cap)
    is covered separately below, in
    TestExpandedRailFooterShowsMoreWhenTheCapIsExceeded."""

    @classmethod
    def setUpClass(cls):
        js = _footer_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Footer driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_footer_json(stdout)

    def test_expanded_footer_is_unchanged(self):
        """"Unchanged" now means: with nothing actually hidden (the 3 agent
        sessions are folded into a visible bucket, not off-screen), the
        expanded footer reads the plain "all shown" sentence -- the
        hidden=0 branch -- not the old, buggy "scroll · 3 more"."""
        self.assertEqual(self.OUT["expanded"], "1 session · all shown")

    def test_collapsed_footer_is_compact_and_never_wraps_the_old_phrase(self):
        self.assertEqual(self.OUT["collapsed"], "+3")
        self.assertNotIn("scroll", self.OUT["collapsed"])

    def test_re_expanding_restores_the_full_sentence(self):
        self.assertEqual(self.OUT["expandedAgain"], "1 session · all shown")


_MORE_FOOTER_JS_TAIL = r"""
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});
var footer = queryAllReal(root, '.cr-rail-footer')[0];

var sessions = %(sessions)s;
window.CR.board.update({ sessions: sessions, now: %(now)d });

var out = {
  text: footer.textContent,
  hasMoreClass: footer._classes.has('cr-rail-footer--more'),
  role: footer.getAttribute('role'),
};

console.log("===CR_MORE_FOOTER_JSON_START===");
console.log(JSON.stringify(out));
"""


def _footer_over_cap_driver_js():
    bundle_js = _extract_script_content(_read_page())
    # 30 plain, unpinned, non-agent sessions -- exceeds RAIL_LIMIT_STEP (25),
    # so renderSessionRows() actually caps them and res.total (30) > res.shown
    # (25), landing on the "Show N more · M hidden" branch this class's own
    # name is really about (hidden = res.total - res.shown = 5).
    sessions = [make_session("cap_%d" % i, NOW - 5 - i, ended=True) for i in range(30)]
    tail = _MORE_FOOTER_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


def _extract_more_footer_json(stdout):
    marker = "===CR_MORE_FOOTER_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestExpandedRailFooterShowsMoreWhenTheCapIsExceeded(unittest.TestCase):
    """The THIRD footer state TestCollapsedRailFooterIsCompact's class name is
    really about: with more unpinned sessions than the 25-row cap
    (RAIL_LIMIT_STEP), hidden = res.total - res.shown is > 0, and the
    expanded footer becomes a real "Show N more · M hidden" affordance --
    class cr-rail-footer--more, role="button" -- rather than either the
    collapsed "+N" orb-rail token or the "all shown" plain sentence."""

    @classmethod
    def setUpClass(cls):
        js = _footer_over_cap_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Over-cap footer driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_more_footer_json(stdout)

    def test_expanded_footer_shows_the_show_more_hidden_sentence(self):
        # 30 unpinned sessions, cap 25 -> step = min(25, 5) = 5, hidden = 5.
        self.assertEqual(self.OUT["text"], "Show 5 more · 5 hidden")

    def test_footer_gets_the_more_button_affordances(self):
        self.assertTrue(self.OUT["hasMoreClass"], "footer missing cr-rail-footer--more")
        self.assertEqual(self.OUT["role"], "button")


def _footer_four_digit_driver_js():
    bundle_js = _extract_script_content(_read_page())
    # DEFECT 2 (adversarial review): the user has 957 sessions today -- a
    # 4-digit overflow count is realistic, not a contrived edge case. One
    # plain session (renders individually) plus 1234 folded into one agent
    # bucket (excluded from the individual rows entirely), so `more` is
    # exactly 1234 -- a real 4-digit "+1234" token, not "+3".
    sessions = [make_session("fd_plain", NOW - 5, ended=True)]
    for i in range(1234):
        sessions.append(make_session("fd_agent_%d" % i, NOW - 5, agent=True, group="g1", groupLabel="repo"))
    tail = _FOOTER_JS_TAIL % {"sessions": json.dumps(sessions), "now": NOW}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCollapsedRailFooterFourDigitCount(unittest.TestCase):
    """DEFECT 2 (adversarial review): `+1234` is a single unbreakable token --
    reachable today (957 sessions) -- silently clipped by the collapsed
    rail's `overflow: hidden` with no collapsed-specific footer rule. The
    fix keeps the SAME "+N" format (no abbreviation: see
    TestCollapsedRailAlignmentCss.test_collapsed_footer_has_its_own_compact_rule
    for why the CSS-only route was chosen), so the rendered string is
    asserted to still be exactly "+1234" -- short by construction, not
    truncated -- with the full count preserved in `title` either way."""

    @classmethod
    def setUpClass(cls):
        js = _footer_four_digit_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Four-digit footer driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_footer_json(stdout)

    def test_collapsed_footer_renders_the_full_four_digit_count_uncut(self):
        self.assertEqual(self.OUT["collapsed"], "+1234")

    def test_collapsed_footer_string_stays_short(self):
        # "+1234" -- 5 characters, well within what the collapsed-rule fits;
        # never the old wrapped/clipped "scroll · N more" phrase.
        self.assertLessEqual(len(self.OUT["collapsed"]), 6)
        self.assertNotIn(" ", self.OUT["collapsed"])

    def test_full_count_is_preserved_in_the_title_when_collapsed(self):
        self.assertIn("1234", self.OUT["collapsedTitle"])


if __name__ == "__main__":
    unittest.main()
