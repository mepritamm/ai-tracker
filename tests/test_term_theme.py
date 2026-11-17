"""TERM_THEME (Config -> Terminal -> Terminal colours): black (default) | app.

Source-text pins for the CSS / JS wiring (no JS engine in the stdlib) plus one EXECUTED node case
(skipped when node is absent, like tests/test_term_vt_exec.py) for the full-tab flip button.
The server half (config key, validator, <html data-term-theme>) is in tests/test_cr_routes.py
(TestApiConfigTermTheme) and tests/test_selfcheck.py.
"""
import os
import unittest

from aitracker.page import build_page
from tests.test_term_vt_exec import _run_node, _HAS_NODE

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "aitracker", "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


_BLACK = ('html[data-term-theme="black"] .vttermwrap,html[data-term-theme="black"] .vtmodal,'
          'html[data-term-theme="black"] #ext_vt.vtfull')

_COLOR_BLACK = ('html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] .vtmodal, '
                'html[data-term-theme="black"] #ext_vt.vtfull { color-scheme: dark; color: var(--text); }')
_COLOR_LIGHT = 'html[data-term-theme="light"] #ext_vt.vtfull { color: var(--text); }'


class TestTermThemeClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_css = _read("app.css")
        cls.vt_css = _read("ext_vt.css")
        cls.js = _read("ext_vt.js")
        cls.app_js = _read("app.js")
        cls.dlg = _read("ext_cr_dialogs.js")

    def test_app_css_dark_palette_prefix(self):
        self.assertTrue(self.app_css.split("\n")[0].startswith(":root," + _BLACK + "{--app:#0c0f15"))

    def test_app_css_light_palette_prefix(self):
        self.assertTrue(self.app_css.split("\n")[1].startswith(
            'html.light,html[data-term-theme="light"] #ext_vt.vtfull{--app:#f4efe3'))

    def test_ext_vt_css_pins(self):
        self.assertIn(':root, html[data-term-theme="black"] .vttermwrap, html[data-term-theme="black"] '
                      '.vtmodal, html[data-term-theme="black"] #ext_vt.vtfull {', self.vt_css)
        self.assertIn('html.light, html[data-term-theme="light"] #ext_vt.vtfull {', self.vt_css)
        self.assertIn('html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }',
                      self.vt_css)

    def test_inherited_text_colour_follows_the_surface_palette(self):
        # H1: `color` inherits from <html> (app tokens); the surface must re-resolve it itself.
        self.assertIn(_COLOR_BLACK, self.vt_css)
        self.assertIn(_COLOR_LIGHT, self.vt_css)

    def test_guard_no_negative_attr_selector_and_no_output_boxes(self):
        # guard, green before the change: positive selectors only, and command-output boxes
        # (.runout) are never themed by TERM_THEME.
        self.assertNotIn(":not([data-term-theme", self.app_css + self.vt_css)
        for line in (self.app_css + "\n" + self.vt_css).split("\n"):
            if "data-term-theme" in line:
                self.assertNotIn(".runout", line)

    def test_built_page_carries_prefixes_and_hide_rule(self):
        page = build_page()
        self.assertIn(":root," + _BLACK + "{--app:#0c0f15", page)
        self.assertIn('html.light,html[data-term-theme="light"] #ext_vt.vtfull{--app:#f4efe3', page)
        self.assertIn('html[data-term-theme="black"]:not(.vt-standalone) .vtthemebtn { display: none; }', page)
        self.assertIn('<html data-term-theme="black">', page)
        self.assertIn(_COLOR_BLACK, page)
        self.assertIn(_COLOR_LIGHT, page)

    def test_xterm_ctor_reads_own_wrap_and_listens(self):
        ctor = self.js[self.js.index("function XtermTerminal(container, ttyId"):
                       self.js.index("XtermTerminal.prototype.attach")]
        self.assertIn("_xtermTheme(self.container); };", ctor)
        self.assertIn('document.addEventListener("termthemechange", this._onThemeChange);', ctor)

    def test_xterm_destroy_removes_termthemechange(self):
        a = self.js.index("XtermTerminal.prototype.destroy = function")
        destroy = self.js[a:self.js.index("// ===== the modal (reuses app.css", a)]
        self.assertIn('document.removeEventListener("termthemechange", this._onThemeChange);', destroy)

    def test_mountinto_set_theme_reads_wrap(self):
        a = self.js.index("function mountInto(container, target, opts) {")
        body = self.js[a:self.js.index("function copyBuffer()", a)]
        self.assertIn("curTerm.term.options.theme = _xtermTheme(wrap);", body)

    def test_flip_helpers_precede_toolbar_and_stay_dom_only(self):
        t = self.js.index("function buildToolbar(")
        self.assertLess(self.js.index("function _termThemeAttr("), t)
        self.assertLess(self.js.index("function _flipTabTermTheme("), t)
        sl = self.js[self.js.index("function _flipTabTermTheme("):t]
        self.assertIn('setAttribute("data-term-theme", next)', sl)
        self.assertIn('CustomEvent("termthemechange"', sl)
        self.assertNotIn("localStorage", sl)
        self.assertNotIn("fetch(", sl)

    def test_toolbar_button_wiring(self):
        a = self.js.index("function buildToolbar(")
        bar = self.js[a:self.js.index("var zoomOut = document.createElement", a)]
        self.assertIn('if (_termThemeAttr() === "app") toggleTheme(); else _flipTabTermTheme();', bar)
        self.assertIn('document.addEventListener("termthemechange", renderThemeBtn);', bar)
        self.assertIn('document.removeEventListener("termthemechange", renderThemeBtn);', bar)

    def test_app_js_apply_term_theme(self):
        self.assertIn("function applyTermTheme(", self.app_js)
        self.assertIn('CustomEvent("termthemechange"', self.app_js)

    def test_config_row_and_envchip(self):
        a = self.dlg.index("active === 'Terminal'")
        sec = self.dlg[a:self.dlg.index("} else if (active ===", a + 10)]
        self.assertIn("serverRow('Terminal colours', 'TERM_THEME'", sec)
        self.assertIn("TERM_THEME: null", self.dlg)


@unittest.skipUnless(_HAS_NODE, "node not installed")
class TestTabTermThemeFlipExec(unittest.TestCase):
    def test_flip_black_light_black_and_default_app(self):
        js = _read("ext_vt.js")
        sl = js[js.index("function _termThemeAttr("):js.index("function buildToolbar(")]
        harness = """
var attrs = {}, events = [];
var document = {
  documentElement: {
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
    setAttribute: function (k, v) { attrs[k] = v; }
  },
  dispatchEvent: function (e) { events.push({ type: e.type, detail: e.detail }); }
};
function CustomEvent(n, o) { this.type = n; this.detail = o.detail; }
""" + sl + """
var none = _termThemeAttr();
attrs["data-term-theme"] = "black";
_flipTabTermTheme(); var a1 = _termThemeAttr();
_flipTabTermTheme(); var a2 = _termThemeAttr();
console.log(JSON.stringify({none: none, a1: a1, a2: a2, events: events}));
"""
        out = _run_node(harness)
        self.assertEqual(out["none"], "app")
        self.assertEqual((out["a1"], out["a2"]), ("light", "black"))
        self.assertEqual(out["events"], [
            {"type": "termthemechange", "detail": {"termTheme": "light"}},
            {"type": "termthemechange", "detail": {"termTheme": "black"}},
        ])


@unittest.skipUnless(_HAS_NODE, "node not installed")
class TestApplyTermThemeExec(unittest.TestCase):
    def test_sets_attr_and_dispatches_event(self):
        js = _read("app.js")
        sl = js[js.index("function applyTermTheme("):js.index("window.applyTermTheme=")]
        harness = """
var attrs = {}, events = [];
var document = {
  documentElement: { setAttribute: function (k, v) { attrs[k] = v; } },
  dispatchEvent: function (e) { events.push({ type: e.type, detail: e.detail }); }
};
function CustomEvent(n, o) { this.type = n; this.detail = o.detail; }
""" + sl + """
applyTermTheme("app"); var a1 = attrs["data-term-theme"];
applyTermTheme("bogus"); var a2 = attrs["data-term-theme"];
console.log(JSON.stringify({a1: a1, a2: a2, events: events}));
"""
        out = _run_node(harness)
        self.assertEqual((out["a1"], out["a2"]), ("app", "black"))
        self.assertEqual(out["events"], [
            {"type": "termthemechange", "detail": {"termTheme": "app"}},
            {"type": "termthemechange", "detail": {"termTheme": "black"}},
        ])


if __name__ == "__main__":
    unittest.main()
