"""Regression tests for two Control Room detail-view fixes in ext_cr_detail.js /
ext_cr_detail.css:

JOB 1 -- the "latest" convo-nav button (`CONVERSATION <title> < prev  next >
[latest]`) rendered its icon with a BARE `ico("jump-top")` call. The base
`.ico` rule (app.css) sizes an icon off `calc(1em * var(--ico-scale))` -- but
this button's own font-size is a FIXED `10.5px` (`.crd-convonav button`,
ext_cr_detail.css), not itself scaled by the Config dialog's icon-size knob.
So the icon's "1em" base never grows/shrinks the way the SURROUNDING TEXT
does, and at higher scale percentages it visibly outgrows its own "latest"
label and its prev/next neighbours (which carry no icon at all) instead of
tracking them in proportion. Every OTHER icon-bearing control in this same
header (Stop, Search, Flag, Rename, Pin -- see ext_cr_detail.js) wraps its
icon in `<span class="crd-ico">`, which gets an explicit, font-size-
independent base (`.crd-ico svg { width: calc(14px * var(--ico-scale)) }`,
ext_cr_detail.css) -- the established mechanism this button now also uses.
`ico()` itself already honours ICON_STYLE (icons/emoji/text) via app.js's
_icoStyle -- unaffected by, and unrelated to, this wrapper change; confirmed
here by pinning that "jump-top" is present in both style glyph maps (ICON_
STYLE parity is otherwise covered globally by tests/test_icons.py).

JOB 2 -- the live "Now" card (`* Now * <HH:MM>` + the latest line) used to
render at the BOTTOM of the conversation timeline (`.crd-timeline-live`,
nested inside `.crd-timeline-panel`'s `.crd-panel-body`). Moved (not
duplicated -- ONE renderer, ONE call site: `renderLiveEntry()`/
`ui_findLiveEl()`) to a new top-level `.crd-now` card directly below the
progress spine (`.crd-spine`) and above the three-column layout
(`.crd-columns`), so current state is visible without scrolling into the
timeline. Must still update on every poll and degrade cleanly (hidden, empty)
when there is no "now" line.

Idiom for the functional half: copied from tests/test_cr_timeline.py -- build
the REAL assembled page (aitracker.page.build_page()), extract the inlined
<script> bundle, execute it in Node under a minimal stub DOM, then reach into
window.CR.detail._internal for the exported pure derivations (stateOf/
detailIsWorking/renderLiveEntry all operate on plain data + a tiny node stub,
no HTML parsing needed -- unlike Detail.prototype.mount(), which relies on a
real browser's `<template>.innerHTML` parser and cannot run under this
stdlib-only harness). Self-contained (no cross-import from sibling test
files, which other sessions may be editing concurrently). Skips cleanly (not
a failure) when node is unavailable, same as its siblings.
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
_WEB = os.path.join(_ROOT, "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)

NOW = 1_700_000_000


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


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


def _block(css, selector):
    start = css.index(selector)
    brace = css.index("{", start)
    depth = 0
    for i in range(brace, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[brace:i + 1]
    raise AssertionError("unterminated block for %r" % selector)


# ===========================================================================
# JOB 1 -- source-level checks (a static markup change; no derived logic).
# ===========================================================================

class TestLatestButtonIconScale(unittest.TestCase):
    def setUp(self):
        self.js = _read_web_file("ext_cr_detail.js")
        self.css = _read_web_file("ext_cr_detail.css")

    def test_latest_button_icon_is_wrapped_in_crd_ico(self):
        """The bare `ico("jump-top")` call must now be wrapped the SAME way
        every other icon-bearing control in this header is (Stop/Search/Flag/
        Rename/Pin all use `<span class="crd-ico">`)."""
        m = re.search(
            r'data-act="convo-latest">\s*<span class="crd-ico">\s*'
            r'["\']?\s*\+?\s*ico\(\s*"jump-top"\s*\)',
            self.js,
        )
        self.assertIsNotNone(
            m,
            "convo-latest button's ico('jump-top') is no longer wrapped in "
            "<span class=\"crd-ico\"> -- it will size off this button's own "
            "fixed 10.5px font instead of the shared calc(14px * "
            "var(--ico-scale)) base every sibling icon uses",
        )

    def test_latest_button_no_longer_calls_bare_ico(self):
        """Ground truth: the OLD bug's exact shape (`>` immediately followed
        by the ico() call, no wrapper) must be gone."""
        self.assertNotRegex(
            self.js,
            r'data-act="convo-latest">["\']?\s*\+?\s*ico\(\s*"jump-top"\s*\)\s*\+\s*["\'] latest',
        )

    def test_crd_ico_svg_rule_still_scales_with_ico_scale(self):
        """Sanity anchor: the wrapper this fix relies on must still size off
        --ico-scale (not a fixed px value) -- if this regressed, wrapping the
        latest icon in it would accomplish nothing."""
        block = _block(self.css, ".cr .crd-ico svg {")
        self.assertIn("var(--ico-scale)", block)
        self.assertNotRegex(block, r'width:\s*\d+px\s*;')

    def test_jump_top_glyph_present_in_both_icon_style_maps(self):
        """ICON_STYLE parity (icons/emoji/text) for this specific glyph --
        the broader "every sprite icon is covered" invariant is pinned
        globally by tests/test_icons.py; this just anchors THIS icon name."""
        app_js = _read_web_file("app.js")
        emoji_map = re.search(r'const ICO_EMOJI\s*=\s*\{(.*?)\}\s*;', app_js, re.DOTALL)
        text_map = re.search(r'const ICO_TEXT\s*=\s*\{(.*?)\}\s*;', app_js, re.DOTALL)
        self.assertIsNotNone(emoji_map)
        self.assertIsNotNone(text_map)
        self.assertIn('"jump-top"', emoji_map.group(1))
        self.assertIn('"jump-top"', text_map.group(1))

    def test_jump_top_icon_size_matches_across_icon_styles(self):
        """ITEM 2 / ITEM 3d (adversarial-review test gap): the previous test above
        only pinned that "jump-top" is PRESENT in the emoji/text glyph maps -- the
        very branch that defeats the icon-size fix -- without ever asserting its
        SIZE. `ico("jump-top")` in "icons" style emits `<svg class="ico">`, sized by
        `.crd-ico svg { width: calc(14px * var(--ico-scale)) }`; in "emoji"/"text"
        style it emits `<span class="ico ico-glyph">` instead, which that svg-only
        rule never matches -- without a matching `.crd-ico > .ico-glyph` rule at the
        SAME 14px base, the glyph falls back to app.css's generic
        `.ico-glyph{font-size:calc(1em*var(--ico-scale))}`, inheriting this button's
        own FIXED 10.5px font instead. Reproduces the review's exact measurement
        (at --ico-scale:2: glyph 21px vs svg 28px, a mismatch) by evaluating both
        rules' calc() formulas at scale=2 directly from the real CSS -- must go RED
        if the glyph rule regresses or reverts to a different px base."""
        svg_block = _block(self.css, ".cr .crd-ico svg {")
        glyph_block = _block(self.css, ".cr .crd-ico > .ico-glyph {")

        def px_at_scale(block, prop, scale):
            m = re.search(prop + r':\s*calc\(\s*(\d+(?:\.\d+)?)px\s*\*\s*var\(--ico-scale\)\s*\)', block)
            self.assertIsNotNone(m, "%r rule missing 'calc(<n>px * var(--ico-scale))' for %s" % (block, prop))
            return float(m.group(1)) * scale

        svg_px = px_at_scale(svg_block, "width", 2)
        glyph_px = px_at_scale(glyph_block, "font-size", 2)
        self.assertEqual(svg_px, 28.0, "sanity: the icons-style svg base must still be 14px")
        self.assertEqual(
            glyph_px, svg_px,
            "at --ico-scale:2 the emoji/text glyph (%.0fpx) must match the icons-style "
            "svg (%.0fpx) -- this is the review's exact measured mismatch (glyph 21px vs "
            "svg 28px) if the .crd-ico > .ico-glyph rule is missing or uses a different base"
            % (glyph_px, svg_px))


# ===========================================================================
# JOB 2 -- source-level structural checks (placement / no duplication).
# ===========================================================================

class TestNowCardRelocatedSource(unittest.TestCase):
    def setUp(self):
        self.js = _read_web_file("ext_cr_detail.js")
        self.css = _read_web_file("ext_cr_detail.css")

    def test_now_card_sits_directly_above_the_spine(self):
        """Owner correction: the Now card goes ABOVE the progress spine (the
        very first thing in the main session view under the header), not
        below it."""
        notecard_close = self.js.index('data-act="note-queue-send">Queue</button>')
        now_card = self.js.index('<div class="crd-now" hidden></div>')
        spine_open = self.js.index('<div class="crd-spine" role="group"')
        columns_open = self.js.index('<div class="crd-columns">')
        self.assertLess(notecard_close, now_card,
                         "'.crd-now' must come after the rest of the header/card block")
        self.assertLess(now_card, spine_open,
                         "'.crd-now' must come BEFORE the progress spine, not after it")
        self.assertLess(spine_open, columns_open,
                         "the progress spine must still precede the three-column layout")

    def test_old_timeline_live_class_no_longer_used_as_a_real_selector(self):
        """The OLD class must no longer be declared as a real selector/markup
        class anywhere -- confirms a real move, not a rename that left a
        duplicate behind. (Explanatory prose elsewhere in this file's own
        comments may still name the old class for history; that's fine --
        this only bans it as an actual selector or class= attribute.)"""
        self.assertNotIn('class="crd-timeline-live"', self.js)
        self.assertNotRegex(self.css, r'\.crd-timeline-live\s*\{')

    def test_now_card_not_declared_inside_the_timeline_panel_markup(self):
        """The timeline panel (from its own opening class to its closing
        </section>) must no longer contain the live card anywhere inside it."""
        panel_start = self.js.index('crd-timeline-panel')
        panel_end = self.js.index("</section>", panel_start)
        panel_body = self.js[panel_start:panel_end]
        self.assertNotIn('class="crd-now"', panel_body)

    def test_no_duplicate_now_markup_in_skeleton(self):
        self.assertEqual(self.js.count('class="crd-now"'), 1,
                          "'.crd-now' must be declared exactly once in the SKELETON")

    def test_ui_find_live_el_targets_crd_now(self):
        self.assertRegex(
            self.js,
            r'function ui_findLiveEl\(node\)\s*\{\s*return qs\(node,\s*["\']\.crd-now["\']\)\s*;\s*\}',
        )

    def test_render_live_entry_defined_once_and_called_exactly_once(self):
        """ONE renderer, ONE call site -- renderLiveEntry must be invoked
        exactly once per render pass (renderUpdate), not from two places.
        (Matches only the function definition and a real call passing its
        three positional args -- not comment-prose mentions of the name.)"""
        self.assertEqual(
            len(re.findall(r'function renderLiveEntry\(node, session, nowSec\)', self.js)), 1,
            "expected exactly one renderLiveEntry function definition")
        self.assertEqual(
            len(re.findall(r'(?<!function )renderLiveEntry\(node, session, nowSec\);', self.js)), 1,
            "expected exactly one real call site for renderLiveEntry()")

    def test_crd_now_css_rule_exists_with_expected_chrome(self):
        block = _block(self.css, ".cr .crd-now {")
        self.assertIn("border", block)
        self.assertIn("var(--line-agent)", block)
        self.assertIn("var(--glow-agent)", block)
        # top-level card margin rhythm, matching .crd-spine's own (not the old
        # panel-internal 15px gutter margin)
        self.assertIn("24px", block)


# ===========================================================================
# JOB 2 -- functional checks via the real, bundled renderLiveEntry().
# ===========================================================================

_JS_PREAMBLE = r"""
globalThis.window = globalThis;
var _elMap = {};
function makeEl(id) {
  var self = {
    id: id || null,
    classList: { add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; } },
    style: {}, dataset: {}, setAttribute: function(){}, getAttribute: function(){ return null; },
    appendChild: function(){}, append: function(){}, remove: function(){}, insertBefore: function(){},
    addEventListener: function(){}, removeEventListener: function(){},
    querySelector: function() { return self; }, querySelectorAll: function() { return [self]; },
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus: function(){}, click: function(){}
  };
  return self;
}
var stubEl = makeEl(null);
window.document = {
  createElement: function() { return makeEl(null); }, createTextNode: function() { return makeEl(null); },
  getElementById: function (id) { if (!_elMap[id]) _elMap[id] = makeEl(id); return _elMap[id]; },
  querySelector: function() { return stubEl; }, querySelectorAll: function() { return [stubEl]; },
  addEventListener: function(){}, dispatchEvent: function(){},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};

var _localStorage = {};
window.localStorage = {
  getItem: function(k) { return (k in _localStorage) ? _localStorage[k] : null; },
  setItem: function(k, v) { _localStorage[k] = v; },
  removeItem: function(k) { delete _localStorage[k]; }
};

window.matchMedia = function() { return { matches: false, addEventListener: function(){}, addListener: function(){}, removeEventListener: function(){} }; };
window.fetch = function() { return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({}); }, text: function(){ return Promise.resolve(""); }, headers: { get: function(){ return null; } } }); };
window.setInterval = function() { return 0; }; window.setTimeout = function() { return 0; }; window.clearInterval = function(){}; window.clearTimeout = function(){};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: function(){ return Promise.resolve(); } } };
window.CustomEvent = function(type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = function() { return 0; };
window.getComputedStyle = function() { return { getPropertyValue: function(){ return ""; } }; };
window.getSelection = function() { return { toString: function(){ return ""; } }; };
window.addEventListener = function(){}; window.removeEventListener = function(){}; window.dispatchEvent = function(){};
process.on("unhandledRejection", function(){});

try {
"""

_JS_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


def make_detail(**overrides):
    d = {
        "meta": {"cwd": "/tmp/proj", "gitBranch": "main", "sessionId": "sid",
                  "model": "", "effort": "", "title": "t"},
        "todos": [], "files": [], "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": [], "agents": [], "agents_bg": [], "shells": [],
        "decisions": [], "waiting": False, "prs": [], "narrative": [],
        "tokens": {"in": 0, "out": 0}, "context": {"current": 0, "limit": 0, "pct": 0},
        "counts": {}, "mtime": 0, "now": 0, "notes": [], "push_when": "turn",
        "overview": {"where": "", "goal": "", "now": "", "now_kind": "", "sofar": "", "commits": []},
        "continued_as": "", "continued_from": "",
    }
    d.update(overrides)
    return d


def _bundle_js():
    return _extract_script_content(_read_page())


def _extract_marker_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


_DRIVER_TAIL = r"""
var NOW = %(now)d;
function fakeNode() {
  var wrap = { hidden: false, innerHTML: "" };
  var node = { querySelector: function (sel) { return sel === ".crd-now" ? wrap : null; } };
  return { node: node, wrap: wrap };
}
var I = window.CR.detail._internal;
var OUT = {};

var withNow = %(with_now)s;
var f1 = fakeNode();
I.renderLiveEntry(f1.node, withNow, NOW);
OUT.hiddenWhenPresent = f1.wrap.hidden;
OUT.htmlWhenPresent = f1.wrap.innerHTML;

var noNow = %(no_now)s;
var f2 = fakeNode();
I.renderLiveEntry(f2.node, noNow, NOW);
OUT.hiddenWhenAbsent = f2.wrap.hidden;
OUT.htmlWhenAbsent = f2.wrap.innerHTML;

// stale (outside LIVE_WINDOW) with a now line must ALSO degrade to hidden
var stale = %(stale)s;
var f3 = fakeNode();
I.renderLiveEntry(f3.node, stale, NOW);
OUT.hiddenWhenStale = f3.wrap.hidden;

console.log("===CR_NOW_JSON_START===");
console.log(JSON.stringify(OUT));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestNowCardFunctional(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with_now = make_detail(mtime=NOW - 5, overview={"now": "doing a thing", "now_kind": "narration",
                                                          "where": "", "goal": "", "sofar": "", "commits": []})
        no_now = make_detail(mtime=NOW - 5, overview={"now": "", "now_kind": "",
                                                        "where": "", "goal": "", "sofar": "", "commits": []})
        stale = make_detail(mtime=NOW - 10_000, overview={"now": "doing a thing", "now_kind": "narration",
                                                            "where": "", "goal": "", "sofar": "", "commits": []})
        tail = _DRIVER_TAIL % {
            "now": NOW,
            "with_now": json.dumps(with_now),
            "no_now": json.dumps(no_now),
            "stale": json.dumps(stale),
        }
        js = "\n".join([_JS_PREAMBLE, _bundle_js(), _JS_MID, tail])
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Now-card render driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_NOW_JSON_START===")

    def test_renders_visible_with_now_and_time_when_live_and_present(self):
        self.assertFalse(self.OUT["hiddenWhenPresent"])
        self.assertIn("Now ·", self.OUT["htmlWhenPresent"])
        self.assertIn("doing a thing", self.OUT["htmlWhenPresent"])

    def test_degrades_hidden_and_empty_when_no_now_line(self):
        self.assertTrue(self.OUT["hiddenWhenAbsent"])
        self.assertEqual(self.OUT["htmlWhenAbsent"], "")

    def test_degrades_hidden_when_stale_even_with_a_now_line(self):
        """Liveness gates the card too -- a now line surviving past
        LIVE_WINDOW must not keep showing as 'live'."""
        self.assertTrue(self.OUT["hiddenWhenStale"])


if __name__ == "__main__":
    unittest.main()
