"""Page-grep pins for the read-only UX (Config toggle row + html.tracker-readonly CSS)."""
import json
import os
import re
import unittest

from aitracker import page as _page
from tests.test_working_glow_board import (
    _HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node,
)

_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css):
    """[(selector-part, body)] for every flat rule, one entry per comma-separated selector."""
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
        for part in sel.split(","):
            out.append((" ".join(part.split()), body))
    return out


_MARK = "===CR_RO_JSON==="
_PRE = r"""
var __timers = [];
window.setTimeout = function (fn) { __timers.push(fn); return 0; };
window.localStorage.setItem('tracker.ui', 'next');
"""
_END = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""
_COMMON = r"""
function __flush() { return new Promise(function (r) { setImmediate(r); }); }
var __o = {};
function __done() { console.log(__MARK__); console.log(JSON.stringify(__o)); }
"""

# F3: real dialogs module, Tunnel section, failed read-only toggle.
_DRV_TOGGLE = r"""
(async function () {
  try {
    var posts = [];
    globalThis.confirm = function () { return true; };
    window.fetch = function (url, init) {
      var post = init && init.method === 'POST';
      if (post) posts.push([url, init.body]);
      var body = post ? { error: 'read-only: x', readonly: true }
                      : { readonly: false, readonly_env: false, on: false };
      return Promise.resolve({ ok: !post, status: post ? 403 : 200, json: function () { return Promise.resolve(body); } });
    };
    var root = makeReal('div'); docBody.appendChild(root);
    window.CR.dialogs.mount(root, { emit: function () {}, on: function () {}, readOnly: function () { return false; } });
    window.CR.dialogs.open('config', { section: 'Tunnel' });
    await __flush(); await __flush();
    function find() {
      var t = queryAllReal(root, '.cr-toggle').filter(function (b) { return b._attrs['aria-label'] === 'Read-only for remote visitors'; })[0];
      return { toggle: t, status: queryAllReal(root, '.cr-readonly-status')[0] };
    }
    var a = find();
    __o.found = !!(a.toggle && a.status);
    a.toggle._listeners.click({});
    __o.onAfterClick = a.toggle._classes.has('is-on');
    await __flush(); await __flush(); await __flush();
    var b = find();
    __o.posts = posts;
    __o.statusText = b.status ? allTextIn(b.status) + (b.status.textContent || '') : null;
    __o.isOn = b.toggle._classes.has('is-on');
    __done();
  } catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
})();
"""

# F4b: real loadSide() against stubbed /api/list headers.
_DRV_HEADER = r"""
(async function () {
  try {
    document.documentElement = makeReal('html');
    var ctxCap = null;
    window.CR.dialogs = { mount: function (r, c) { ctxCap = c; } };
    var hdr = null;
    window.fetch = function (url) {
      var list = String(url).indexOf('/api/list') === 0;
      return Promise.resolve({ ok: true, status: 200,
        headers: { get: function (k) { return list && k === 'X-Read-Only' ? hdr : null; } },
        json: function () { return Promise.resolve(list ? [] : {}); } });
    };
    __timers.slice().forEach(function (fn) { try { fn(); } catch (e) {} });
    await __flush(); await __flush();   // let init()'s own first loadSide() finish (sideBusy guard)
    async function pass(label, h) {
      hdr = h;
      await loadSide(); await __flush();
      __o[label] = { flag: trackerReadOnly, cls: document.documentElement._classes.has('tracker-readonly'),
                     ctx: ctxCap ? ctxCap.readOnly() : null };
    }
    __o.ctxCaptured = !!ctxCap;
    await pass('on', '1');
    await pass('off', null);
    __done();
  } catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
})();
"""


def _node(driver):
    drv = _COMMON.replace("__MARK__", json.dumps(_MARK)) + driver
    rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _PRE, _bundle_js(), drv, _END]))
    if rc != 0:
        raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
    return _extract_marker_json(out, _MARK)


class TestReadonlyUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _page.build_page()

    def test_readonly_toggle_row_present(self):
        h = self.html
        self.assertIn("Read-only for remote visitors", h)
        self.assertIn("'TUNNEL_READONLY'", h)
        self.assertIn("can look but not change anything or open terminals", h)
        self.assertIn("Applies live.", h)

    def test_readonly_env_lock_rendered(self):
        h = self.html
        self.assertIn("tunnel.readonly_env", h)
        self.assertIn("Locked on by TRACKER_TUNNEL_READONLY", h)
        self.assertIn("roToggle.disabled = true", h)

    def test_enable_readonly_confirms(self):
        h = self.html
        i = h.find("var roToggle = toggleCtl(")
        self.assertGreaterEqual(i, 0)
        handler = h[i:i + 1500]
        self.assertIn("window.confirm(", handler)
        self.assertIn("will be view-only. Turn it off from the Mac itself.", handler)
        self.assertLess(handler.find("confirm("), handler.find("postTunnelValue("),
                        "confirm must precede the POST")
        self.assertIn("classList.remove('is-on')", handler, "cancel must revert the toggle")

    def test_readonly_css_only_under_class(self):
        for name in ("ext_cr.css", "app.css"):
            css = _strip_comments(_read(name))
            i = css.find("html.tracker-readonly")
            self.assertGreaterEqual(i, 0, name)
            tail = css[i:]
            for sel, _ in re.findall(r"([^{}]+)\{([^{}]*)\}", tail):
                for part in sel.split(","):
                    self.assertTrue(part.strip().startswith("html.tracker-readonly"),
                                    "%s: unscoped selector %r" % (name, part.strip()))
        ext = _read("ext_cr.css")
        self.assertIn("html.tracker-readonly .cr-topbar::after", ext)
        self.assertIn('content: "View only"', ext)
        seg = ext[ext.find("html.tracker-readonly"):]
        self.assertNotIn("hostname", seg)
        self.assertNotIn(".remote", seg)
        js = _read("ext_cr_dialogs.js")
        j = js.find("var roLocked")
        self.assertNotIn("location.hostname", js[j:j + 2500])

    def test_new_selectors_hidden_only_under_readonly(self):
        ext = [sel for sel, body in _rules(_read("ext_cr.css")) if "display: none" in body]
        for s in (".tracker-next .cr-rail-pin", ".tracker-next .cr-rail-rename", ".tracker-next .crd-phone-input"):
            self.assertIn("html.tracker-readonly " + s, ext)
        app = [(sel, body) for sel, body in _rules(_read("app.css")) if sel.startswith("html.tracker-readonly")]
        hidden = [sel for sel, body in app if "display:none" in body.replace(" ", "")]
        self.assertIn("html.tracker-readonly .addflag", hidden)
        self.assertIn("html.tracker-readonly .pin:not(.on)", hidden)
        self.assertNotIn("html.tracker-readonly .pin", hidden, "a pinned marker must stay visible")
        self.assertIn("html.tracker-readonly .pin", [s for s, b in app if "pointer-events:none" in b.replace(" ", "")])
        self.assertNotIn("html.tracker-readonly .flagbtn", hidden, "flagbtn is the only way to view resolved flags")

    def test_t_shortcut_guards_readonly(self):
        js = _read("ext_cr_board.js")
        i = js.index("e.key === 't'")
        seg = js[i:i + 1200]
        self.assertIn("ctx.readOnly()", seg)
        self.assertLess(seg.index("ctx.readOnly()"), seg.index("'terminal:open'"))

    def test_topbar_badge_does_not_push_with_auto_margin(self):
        (body,) = [b for s, b in _rules(_read("ext_cr.css")) if s == "html.tracker-readonly .cr-topbar::after"]
        self.assertNotIn("margin-left: auto", body)
        self.assertNotIn("margin-left:auto", body.replace(" ", ""))


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestReadonlyToggleFailure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _node(_DRV_TOGGLE)

    def test_failed_toggle_keeps_error_visible_and_toggle_off(self):
        o = self.O
        self.assertTrue(o["found"])
        self.assertEqual(len(o["posts"]), 1)
        self.assertIn("read-only: x", o["statusText"])
        self.assertFalse(o["isOn"])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestReadOnlyHeaderWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _node(_DRV_HEADER)

    def test_header_sets_flag_class_and_ctx(self):
        self.assertTrue(self.O["ctxCaptured"])
        self.assertEqual(self.O["on"], {"flag": True, "cls": True, "ctx": True})

    def test_missing_header_clears_all_three(self):
        self.assertEqual(self.O["off"], {"flag": False, "cls": False, "ctx": False})


if __name__ == "__main__":
    unittest.main()
