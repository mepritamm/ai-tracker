"""The terminal split button: Resume (primary) + a "▾" disclosure holding "Open terminal" and
"External ..." -- on the Control Room header, the CR terminal overlay bar and the classic pane.

One shared helper (`termSplit` / `termSplitSync` / `termSplitClose` + two document capture listeners
in app.js) and one CSS block (app.css) serve all three surfaces.  Behavioural tests brace-match the
real functions out of the shipped sources and run them under node against a tiny fake DOM (same
extract-and-stub recipe as test_cr_manage_terminals_poll.py); markup/CSS checks are source checks
with no line-number pins.  Tests labelled *guard* are green on the base too: they pin behaviour
this change must not disturb.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _extract(src, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    if not m:
        raise AssertionError("function %s() not found" % name)
    i = src.index("{", m.start())
    depth = 0
    for k in range(i, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():k + 1]
    raise AssertionError("unbalanced %s" % name)


def _run(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        proc = subprocess.run(["node", p], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node failed: " + proc.stderr[-2000:])
    return json.loads(proc.stdout.split("OUT:", 1)[1])


# A small fake DOM: elements with parent links, `hidden`/`open`, a classList, and a selector matcher
# that understands `tag`, `.class`, `[attr]` and the descendant combinator (all these tests need).
_FAKE_DOM = r"""
function El(tag, cls) {
  this.tag = tag; this.children = []; this.parent = null; this.hidden = false; this.open = false;
  this._cls = new Set((cls || "").split(/\s+/).filter(Boolean)); this.focused = false;
  var self = this;
  this.classList = {
    toggle: function (c, on) { if (on === undefined) on = !self._cls.has(c); if (on) self._cls.add(c); else self._cls.delete(c); },
    contains: function (c) { return self._cls.has(c); },
  };
}
El.prototype.add = function (c) { c.parent = this; this.children.push(c); return c; };
El.prototype.focus = function () { this.focused = true; };
Object.defineProperty(El.prototype, "parentNode", {get: function () { return this.parent; }});
Object.defineProperty(El.prototype, "firstChild", {get: function () { return this.children[0] || null; }});
El.prototype.insertBefore = function (c, ref) {
  if (c.parent) c.parent.children.splice(c.parent.children.indexOf(c), 1);
  var i = ref ? this.children.indexOf(ref) : this.children.length;
  this.children.splice(i < 0 ? this.children.length : i, 0, c); c.parent = this; return c;
};
function _part(el, p) {
  var m = p.match(/^([a-z]*)((?:\.[\w-]+)*)((?:\[[\w-]+\])*)$/);
  if (!m) throw new Error("selector " + p);
  if (m[1] && el.tag !== m[1]) return false;
  var cs = m[2].split(".").filter(Boolean);
  for (var i = 0; i < cs.length; i++) if (!el._cls.has(cs[i])) return false;
  var as = m[3].replace(/\[|\]/g, " ").trim().split(/\s+/).filter(Boolean);
  for (var j = 0; j < as.length; j++) if (!el[as[j]]) return false;
  return true;
}
El.prototype.matches = function (sel) {
  var parts = sel.split(/\s+/);
  if (!_part(this, parts[parts.length - 1])) return false;
  var cur = this.parent;
  for (var k = parts.length - 2; k >= 0; k--) {
    while (cur && !_part(cur, parts[k])) cur = cur.parent;
    if (!cur) return false;
    cur = cur.parent;
  }
  return true;
};
El.prototype.closest = function (sel) { for (var e = this; e; e = e.parent) if (e.matches(sel)) return e; return null; };
El.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (c) { if (c.matches(sel)) out.push(c); walk(c); }); })(this);
  return out;
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
function mkSplit(root, primaries, items) {
  var split = root.add(new El("span", "tsplit"));
  var prim = primaries.map(function (n) { var b = split.add(new El("button")); b.name = n; return b; });
  var menu = split.add(new El("details", "tsplit-menu"));
  var summary = menu.add(new El("summary", "tsplit-caret"));
  var list = menu.add(new El("div", "tsplit-list"));
  var its = items.map(function (n) { var b = list.add(new El("button")); b.name = n; return b; });
  return {split: split, menu: menu, summary: summary, list: list, prim: prim, items: its};
}
var document = new El("html");
function ev(target, extra) {
  var e = {target: target, key: "", stopped: false, prevented: false,
    stopPropagation: function () { this.stopped = true; }, preventDefault: function () { this.prevented = true; }};
  return Object.assign(e, extra || {});
}
"""

_HELPERS = ("termSplit", "termSplitSync", "termSplitClose", "termSplitOnClick", "termSplitOnKey")


def _helpers_js():
    app = _read("app.js")
    return "\n".join(_extract(app, n) for n in _HELPERS)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestTermSplitHelper(unittest.TestCase):
    def _go(self, body):
        return _run(_FAKE_DOM + _helpers_js() + "\nvar out = {};\n" + body +
                    "\nconsole.log('OUT:' + JSON.stringify(out));")

    def test_markup_is_a_plain_disclosure_not_a_menu(self):
        o = self._go("""
          var h = termSplit('<button>P</button>', '<button>X</button>', 'cc');
          out.h = h; out.alone = termSplit('<button>P</button>', '', 'cc');
          out.solo = termSplit('<b>P</b>', '<i>x</i>', 'cc', 'External');""")
        h = o["h"]
        self.assertIn('<span class="tsplit"><button>P</button><details class="tsplit-menu">', h)
        self.assertIn('<summary class="cc tsplit-caret" aria-label="More terminal actions"', h)
        self.assertIn('<div class="tsplit-list"><button>X</button></div>', h)
        for bad in ("role=", "aria-haspopup", "aria-expanded"):
            self.assertNotIn(bad, h)
        self.assertEqual(o["alone"], "<button>P</button>", "no items -> the primary alone, no caret")
        self.assertIn('<span class="tsplit-solo-label">External</span>', o["solo"])

    def test_sync_hides_caret_when_every_item_hidden(self):
        o = self._go("""
          var r = mkSplit(document, ['p'], ['a', 'b']);
          r.items[0].hidden = true; r.items[1].hidden = true; r.menu.open = true;
          termSplitSync(r.split); out.allHidden = [r.menu.hidden, r.menu.open];
          r.items[1].hidden = false; termSplitSync(r.split); out.oneShown = r.menu.hidden;""")
        self.assertEqual(o["allHidden"], [True, False])
        self.assertFalse(o["oneShown"])

    def test_sync_marks_solo_when_no_primary_visible(self):
        o = self._go("""
          var r = mkSplit(document, ['p1', 'p2'], ['a']);
          termSplitSync(r.split); out.withPrimary = r.split.classList.contains('tsplit-solo');
          r.prim.forEach(function (b) { b.hidden = true; });
          termSplitSync(r.split); out.noPrimary = r.split.classList.contains('tsplit-solo');""")
        self.assertFalse(o["withPrimary"])
        self.assertTrue(o["noPrimary"])

    def test_item_click_and_outside_click_close(self):
        o = self._go("""
          var a = mkSplit(document, ['p'], ['x']), b = mkSplit(document, ['q'], ['y']);
          var other = document.add(new El('div'));
          a.menu.open = true; termSplitOnClick(ev(a.items[0])); out.item = a.menu.open;
          a.menu.open = true; termSplitOnClick(ev(other)); out.outside = a.menu.open;
          a.menu.open = true; b.menu.open = true; termSplitOnClick(ev(b.summary));
          out.otherCaret = [a.menu.open, b.menu.open];
          out.summaryOwn = (function () { b.menu.open = true; termSplitOnClick(ev(b.summary)); return b.menu.open; })();""")
        self.assertFalse(o["item"])
        self.assertFalse(o["outside"])
        self.assertEqual(o["otherCaret"], [False, True], "opening one menu closes the other")
        self.assertTrue(o["summaryOwn"], "the summary's own click is left to the native toggle")

    def test_escape_closes_focuses_summary_and_stops_propagation(self):
        o = self._go("""
          var a = mkSplit(document, ['p'], ['x']);
          a.menu.open = true; var e = ev(a.summary, {key: 'Escape'}); termSplitOnKey(e);
          out.open = a.menu.open; out.focus = a.summary.focused; out.stopped = e.stopped; out.prevented = e.prevented;
          var e2 = ev(null, {key: 'Escape'}); termSplitOnKey(e2);          // none open: untouched
          out.idle = [e2.stopped, e2.prevented];
          a.menu.open = true; var e3 = ev(a.summary, {key: 'a'}); termSplitOnKey(e3);
          out.otherKey = [a.menu.open, e3.stopped];""")
        self.assertFalse(o["open"])
        self.assertTrue(o["focus"])
        self.assertTrue(o["stopped"] and o["prevented"])
        self.assertEqual(o["idle"], [False, False], "no menu open -> the overlay's own Escape still runs")
        self.assertEqual(o["otherKey"], [True, False])

    def test_escape_outside_the_menu_is_not_swallowed(self):
        # U1: a menu left open (focus Tabbed away) must not eat Escape typed in xterm / a dialog.
        o = self._go("""
          var a = mkSplit(document, ['p'], ['x']);
          var ta = document.add(new El('textarea'));
          a.menu.open = true; var e = ev(ta, {key: 'Escape'}); termSplitOnKey(e);
          out.stopped = e.stopped; out.prevented = e.prevented; out.summaryFocused = a.summary.focused;
          out.taFocused = ta.focused; out.open = a.menu.open;""")
        self.assertFalse(o["stopped"])
        self.assertFalse(o["prevented"])
        self.assertFalse(o["summaryFocused"], "focus must not jump to the caret")
        self.assertFalse(o["taFocused"])
        self.assertFalse(o["open"], "the stale menu still closes, silently")

    def test_listeners_are_document_capture(self):
        app = _read("app.js")
        self.assertIn('document.addEventListener("click",termSplitOnClick,true)', app)
        self.assertIn('document.addEventListener("keydown",termSplitOnKey,true)', app)
        for n in ("termSplit", "termSplitSync", "termSplitClose"):
            self.assertIn("window.%s=%s" % (n, n), app)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestOverlaySplit(unittest.TestCase):
    """R2 + R3 (overlay half): External stays reachable while a terminal is attached; a non-Claude id
    keeps Open terminal here as the primary."""

    def _go(self, st_js):
        term = _read("ext_cr_term.js")
        fns = "\n".join(_extract(term, n) for n in ("isClaudeId", "_placeOpenHere", "_syncSplit"))
        return _run(_FAKE_DOM + _helpers_js() + "\n" + fns + r"""
var out = {};
var s = mkSplit(document, ['resume-here'], ['ext-terminal', 'ext-resume']);
var openHere = s.split.add(new El('button', 'cr-term-btn cr-term-btn-solid')); openHere.name = 'open-here';
s.split.children.splice(s.split.children.indexOf(openHere), 1); s.split.children.unshift(openHere);
var el = {split: s.split, splitList: s.list, openHere: openHere, resumeHere: s.prim[0]};
s.items.forEach(function (b) { b.hidden = false; });          // local host, external allowed
var st = """ + st_js + r""";
_syncSplit();
out.openHereHidden = openHere.hidden; out.resumeHidden = el.resumeHere.hidden;
out.openHereInList = openHere.parent === s.list; out.menuHidden = s.menu.hidden;
out.extTerminalHidden = s.items[0].hidden; out.splitHidden = s.split.hidden; out.solo = s.split.classList.contains('tsplit-solo');
out.openCls = Array.from(openHere._cls);
console.log('OUT:' + JSON.stringify(out));""")

    def test_attached_claude_hides_only_the_here_buttons_external_stays(self):
        o = self._go('{attached: true, sessionId: "abc-123"}')
        self.assertTrue(o["openHereHidden"])
        self.assertTrue(o["resumeHidden"])
        self.assertFalse(o["extTerminalHidden"])
        self.assertFalse(o["splitHidden"], "External must not sit under a hidden group")
        self.assertFalse(o["menuHidden"], "the caret (External) must stay reachable while attached")
        self.assertTrue(o["solo"], "no primary visible -> the caret carries the External label")

    def test_unattached_claude_resume_primary_open_in_list(self):
        o = self._go('{attached: false, sessionId: "abc-123"}')
        self.assertFalse(o["resumeHidden"])
        self.assertFalse(o["openHereHidden"])
        self.assertTrue(o["openHereInList"])
        self.assertFalse(o["solo"])

    def test_non_claude_id_keeps_open_here_as_primary(self):   # R3, overlay
        o = self._go('{attached: false, sessionId: "auggie:xyz"}')
        self.assertTrue(o["resumeHidden"])
        self.assertFalse(o["openHereHidden"])
        self.assertFalse(o["openHereInList"], "Open terminal here is the primary for a non-Claude id")
        self.assertIn("cr-term-btn-solid", o["openCls"])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestHeaderPrimarySwap(unittest.TestCase):
    """R3: the CR header's Resume would 400 for an Auggie id, so its primary is Open terminal."""

    def _slice(self):
        src = _read("ext_cr_detail.js")
        a = src.index("var resumable = !/^(auggie")
        b = src.index('termSplitSync(qs(node, ".tsplit"));', a) + len('termSplitSync(qs(node, ".tsplit"));')
        return src[a:b]

    def _go(self, sid):
        return _run(_FAKE_DOM + _helpers_js() + r"""
var s = mkSplit(document, ['resume', 'open-primary'], ['open-item', 'external']);
var map = {'[data-act="resume"]': s.prim[0], '[data-act="open-terminal"][data-primary]': s.prim[1],
  '.tsplit-item[data-act="open-terminal"]': s.items[0], '.tsplit': s.split};
function qs(node, sel) { if (!(sel in map)) throw new Error("unexpected selector " + sel); return map[sel]; }
s.prim[1].hidden = true; s.items[1].hidden = false;   // External shown (local host)
var session = {id: %s}, sid = %s, node = null, out = {};
%s
out.resumeHidden = s.prim[0].hidden; out.primaryOpenHidden = s.prim[1].hidden;
out.listOpenHidden = s.items[0].hidden; out.menuHidden = s.menu.hidden;
console.log('OUT:' + JSON.stringify(out));""" % (json.dumps(sid), json.dumps(sid), self._slice()))

    def test_claude_id_resume_primary(self):
        o = self._go("11111111-2222-3333-4444-555555555555")
        self.assertEqual([o["resumeHidden"], o["primaryOpenHidden"], o["listOpenHidden"]], [False, True, False])

    def test_auggie_id_open_terminal_primary(self):
        o = self._go("auggie:abc")
        self.assertEqual([o["resumeHidden"], o["primaryOpenHidden"], o["listOpenHidden"]], [True, False, True])
        self.assertFalse(o["menuHidden"], "External still lives behind the caret")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestClassicPaneKeepsMenuOpenAcrossPoll(unittest.TestCase):
    """R1: ext_launch's render() rewrites innerHTML every ~2 s; an open menu and the caret's focus
    must survive that rebuild."""

    def _render(self, was_open, caret_focused, item_focused=False):
        src = _read("ext_launch.js")
        return _run(r"""
const src = %s;
const fresh = {open: false, sum: {focused: false, focus() { this.focused = true; }}, querySelector(s) { return s === 'summary' ? this.sum : null; }};
let rebuilt = false;
const el = {style: {}, set innerHTML(v) { rebuilt = true; }, get innerHTML() { return ''; },
  querySelector(s) {
    if (s === '.tsplit-menu[open]') return rebuilt ? null : (%s ? {} : null);
    if (s === '.tsplit-menu') return fresh;
    return null;
  }};
const itemSpy = {focused: false, focus() { this.focused = true; }};
const doc = {getElementById: id => id === 'ext_launch' ? el : (id === 'extopenbtn' ? itemSpy : null),
  activeElement: %s ? {closest: s => s === '#ext_launch .tsplit-caret' ? {} : null}
    : (%s ? {id: 'extopenbtn', closest: () => null} : null)};
el.contains = n => !!n && n.id === 'extopenbtn' && !rebuilt;
const EXT = [];
const run = new Function('document', 'location', 'fetch', 'EXT', 'SIDE_EXT', 'ico', 'esc', 'toast', 'cur', 'window', 'termSplit',
  src + '; return EXT;');
const fns = run(doc, {hostname: 'example.com'}, () => Promise.resolve({}), EXT, [], () => '', s => s, () => {}, 'abc', {},
  (p, i) => p + i);
fns[0]({meta: {}});
console.log('OUT:' + JSON.stringify({open: fresh.open, focused: fresh.sum.focused, item: itemSpy.focused}));""" %
                    (json.dumps(src), "true" if was_open else "false", "true" if caret_focused else "false",
                     "true" if item_focused else "false"))

    def test_open_state_and_focus_carried(self):
        o = self._render(True, True)
        self.assertTrue(o["open"])
        self.assertTrue(o["focused"])

    def test_focus_on_a_menu_item_is_carried_by_id(self):   # U4
        o = self._render(True, False, item_focused=True)
        self.assertTrue(o["open"])
        self.assertTrue(o["item"], "focus on an item (extopenbtn) must survive the 2 s rebuild")
        self.assertFalse(o["focused"])

    def test_closed_stays_closed_and_unfocused(self):
        o = self._render(False, False)
        self.assertFalse(o["open"])
        self.assertFalse(o["focused"])


class TestSurfacesUseTheSharedSplit(unittest.TestCase):
    def test_every_surface_calls_termsplit(self):
        for name in ("ext_cr_detail.js", "ext_cr_term.js", "ext_launch.js"):
            self.assertIn("termSplit(", _read(name), name)

    def test_header_secondary_actions_only_inside_the_list(self):
        src = _read("ext_cr_detail.js")
        a = src.index("termSplit(\n")
        for m in re.finditer(r'<button[^>]*data-act="(external|open-terminal)"[^>]*>', src):
            tag = m.group(0)
            if m.start() < a:
                self.fail("header action before the split: " + tag)
            self.assertTrue("tsplit-item" in tag or "data-primary" in tag, tag)
        self.assertIn('data-act="resume"', src)

    def test_overlay_external_moved_into_the_list_and_group_removed(self):
        src = _read("ext_cr_term.js")
        self.assertNotIn('data-group="external"', src)
        self.assertGreater(src.index('data-action="ext-terminal"'), src.index("termSplit("))
        self.assertGreater(src.index('data-action="ext-resume"'), src.index("termSplit("))
        self.assertIn("termSplitClose();", _extract(src, "close"))

    def test_classic_native_buttons_only_via_the_split(self):
        src = _read("ext_launch.js")
        body = src[src.index("function render(d) {"):src.index("EXT.push(render)")]
        self.assertIn("(resumable ? openHtml : \"\") + nativeHtml", body)
        self.assertNotIn("vtHtml + nativeHtml", body)

    def test_header_reset_closes_the_menu(self):
        src = _read("ext_cr_detail.js")
        a = src.index('ctx.on("session:reset"')
        self.assertIn("termSplitClose();", src[a:a + 900])


class TestSplitCss(unittest.TestCase):
    def test_group_never_wraps(self):
        css = _read("app.css")
        m = re.search(r"\.tsplit\{([^}]*)\}", css)
        self.assertTrue(m)
        self.assertIn("flex-wrap:nowrap", m.group(1))

    def test_no_band_hides_the_split_or_its_items(self):
        for name in ("app.css", "ext_cr_detail.css", "ext_cr_term.css", "ext_launch.css", "ext_cr.css"):
            css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if "display:none" in body.replace(" ", "") and "tsplit" in sel and "readonly" not in sel:
                    for part in sel.split(","):
                        if "tsplit" in part:
                            self.assertRegex(part.strip(), r"\[hidden\]$|tsplit-solo-label$|-webkit-details-marker$|:not\(\.tsplit-item\)$",
                                             "%s hides a split part: %r" % (name, part.strip()))

    def test_phone_band_bare_hide_excludes_split_items(self):
        css = _read("ext_cr_detail.css")
        self.assertIn(".cr .crd-btn-bare:not(.tsplit-item)", css)
        self.assertNotRegex(css, r"\.cr \.crd-btn-bare,\s*\.cr \.crd-btn-ai \{ display: none; \}")

    def test_readonly_hides_the_whole_split_in_the_header(self):
        css = _read("ext_cr.css")
        self.assertRegex(css, r"html\.tracker-readonly \.tracker-next \.crd-row1-actions \.tsplit[,\s]")

    def test_one_css_block_in_app_css(self):
        css = _read("app.css")
        self.assertEqual(css.count("*/"), css.count("/*"))
        for n in ("ext_cr_detail.css", "ext_cr_term.css", "ext_launch.css", "ext_cr.css"):
            self.assertNotIn(".tsplit-menu", _read(n), "the split's base rules live once, in app.css")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestStatusBarAttachedKeepsExternalReachable(unittest.TestCase):
    """U2: _syncStatusBar's attached branch must go through _syncSplit only; hiding the split's whole
    group (the old primaryGroup.hidden = st.attached) would strand External."""

    def test_no_dead_primary_group_handle(self):
        term = _read("ext_cr_term.js")
        self.assertNotIn("primaryGroup", term)
        self.assertIn("_syncSplit();", _extract(term, "_syncStatusBar"))

    def test_attached_status_bar_leaves_external_reachable(self):
        term = _read("ext_cr_term.js")
        fns = "\n".join(_extract(term, n) for n in ("isClaudeId", "_placeOpenHere", "_syncSplit", "_syncStatusBar"))
        o = _run(_FAKE_DOM + _helpers_js() + "\n" + fns + r"""
var s = mkSplit(document, ['resume-here'], ['ext-terminal']);
var openHere = s.split.add(new El('button')); openHere.name = 'open-here';
var group = new El('div'); var mk = function () { return {hidden: true, textContent: "", classList: {toggle() {}}}; };
var el = {split: s.split, splitList: s.list, openHere: openHere, resumeHere: s.prim[0], primaryGroup: group,
  modelPill: mk(), effortPill: mk(), loginPill: mk(), ctxreadout: mk(), status: mk()};
var st = {attached: true, sessionId: "abc-123", tty: "t", loginOk: false, ctx: null, cumulative: 0};
function esc(x) { return x; } function fmtTok(x) { return x; }
_syncStatusBar();
console.log('OUT:' + JSON.stringify({openHereHidden: openHere.hidden, groupHidden: group.hidden,
  menuHidden: s.menu.hidden, splitHidden: s.split.hidden, extHidden: s.items[0].hidden}));""")
        self.assertTrue(o["openHereHidden"])
        self.assertFalse(o["groupHidden"])
        self.assertFalse(o["splitHidden"])
        self.assertFalse(o["menuHidden"], "External must stay reachable while attached")
        self.assertFalse(o["extHidden"])


_F4_JS = r"""
function U() { const f = function () {}; return new Proxy(f, { get(t, k) { if (k === Symbol.toPrimitive) return () => 0; if (k === 'length') return 0; if (k === Symbol.iterator) return function* () {}; if (k === 'then') return undefined; return U(); }, apply() { return U(); }, construct() { return U(); }, has() { return true; }, set() { return true; } }); }
const fs = require('fs'), vm = require('vm');
const calls = [];
function resp(j) { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(j) }); }
const ctx = {
  console, Promise, JSON, Math, Date, RegExp, Array, Object, String, Number, Boolean, Map, Set, WeakMap, Symbol, Error,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, URLSearchParams, TextEncoder, TextDecoder,
  setTimeout: (f) => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: (f) => { Promise.resolve().then(f); return 1; },
  getComputedStyle: () => ({ paddingLeft: '0', paddingTop: '0', paddingRight: '0', paddingBottom: '0' }),
  document: U(), location: { hostname: 'localhost', origin: 'http://localhost', pathname: '/', search: '', protocol: 'http:', host: 'localhost' },
  navigator: { userAgent: 'node', platform: 'mac', clipboard: U() }, localStorage: { getItem: () => null, setItem() {} },
  addEventListener() {}, removeEventListener() {}, EventSource: function () { return U(); }, WebSocket: function () { return U(); },
  ResizeObserver: function () { return U(); }, MutationObserver: function () { return U(); }, alert() {}, confirm: () => false,
  ico: () => '', icoChar: () => null, esc: s => s, toast() {}, EXT: [], SIDE_EXT: [], termSplitSync() {},
  fetch: (u, o) => {
    calls.push({ u: String(u), m: (o && o.method) || 'GET' });
    if (String(u).startsWith('/api/term/list')) return resp({ terminals: [] });
    if (String(u).startsWith('/api/term/pty')) return resp({ tty: 't1', session: 'S1' });
    if (String(u).startsWith('/api/term/renderer')) return resp({ renderer: 'grid' });
    return resp({});
  },
};
ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, { filename: 'ext_vt.js' });
let manage = 0; ctx.ExtVT.manage = function () { manage++; };
(async () => {
  ctx.ExtVT.mountInto(U(), { session: 'S1', mode: 'resume' }, {});
  for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r));
  const posts = calls.filter(c => c.u.startsWith('/api/term/pty') && c.m === 'POST').length;
  console.log('OUT:' + JSON.stringify({ posts, manage, calls: calls.map(c => c.m + ' ' + c.u) }));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run_f4(vt_src):
    with tempfile.TemporaryDirectory() as d:
        vt = os.path.join(d, "ext_vt.js")
        h = os.path.join(d, "h.js")
        with open(vt, "w", encoding="utf-8") as fh:
            fh.write(vt_src)
        with open(h, "w", encoding="utf-8") as fh:
            fh.write(_F4_JS)
        proc = subprocess.run(["node", h, vt], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node failed: " + proc.stderr[-2000:])
    return json.loads(proc.stdout.split("OUT:", 1)[1])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMountIntoEmptyListOnePost(unittest.TestCase):
    """U3 *guard* (green on the base): mountInto(resume) with an empty /api/term/list spawns exactly
    one pty and never opens the manage dialog."""

    def test_mountinto_empty_list_one_pty_post(self):
        o = _run_f4(_read("ext_vt.js"))
        self.assertEqual(o["posts"], 1, o["calls"])
        self.assertEqual(o["manage"], 0)
        self.assertEqual(o["calls"][0].split(" ", 1)[0] + " " + o["calls"][0].split(" ", 1)[1].split("?")[0],
                         "GET /api/term/list")

    def test_double_spawn_mutant_is_caught(self):
        src = _read("ext_vt.js")
        m = re.search(r"\bspawn\(\);", src)
        self.assertTrue(m, "spawn(); call site not found for the mutant")
        o = _run_f4(src[:m.end()] + " spawn();" + src[m.end():])
        self.assertNotEqual(o["posts"], 1, "the guard must detect a double spawn")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestResumeOpensOneEngineGuard(unittest.TestCase):
    """*guard* (green on the base): CR.term's inline Resume attaches exactly one engine via
    mountInto and never routes through the "Manage terminals" dialog -- the double-spawn lives on the
    server, not in this path."""

    def test_open_inline_resume_mounts_once_no_manage_dialog(self):
        term = _read("ext_cr_term.js")
        fns = "\n".join(_extract(term, n) for n in ("_attachEngine", "_openInline"))
        o = _run(r"""
var mounts = [], dialogs = [], engineGen = 0;
function mkEl() { return {hidden: false, textContent: "", disabled: false}; }
var el = {pane: {}, placeholder: mkEl(), status: mkEl(), newTab: mkEl()};
var st = {};
var ctx = {dialog: function (n) { dialogs.push(n); }};
var handle = {onStatus() {}, onNotice() {}, onForked() {}, destroy() {}};
var window = {ExtVT: {mountInto: function (c, t, o) { mounts.push(t); return handle; }}};
function _openCapDialog() { dialogs.push("cap"); }
function _syncNotice() {} function _syncRendererSeg() {} function _applyDarkTheme() {} function showToast() {}
""" + fns + r"""
_openInline("sid-1", "resume");
console.log('OUT:' + JSON.stringify({mounts: mounts, dialogs: dialogs}));""")
        self.assertEqual(o["mounts"], [{"session": "sid-1", "mode": "resume"}])
        self.assertEqual(o["dialogs"], [])


if __name__ == "__main__":
    unittest.main()
