"""Classic dashboard pane (ext_launch.js render) on the shared split button.

Runs the REAL ext_launch.js under node via `new Function`, with the real termSplit family from app.js
(tests/_tsplit_dom.py) and its fake DOM.  The pane is an El whose innerHTML setter clears children, the
way a real element does (the shared fake stores innerHTML without parsing).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import _tsplit_dom as D  # noqa: E402

_NAMES = ("trackerIsLocal", "termExtProbe", "termExtAllowed", "termExtDeny", "termResumable",
          "termSplit", "termSplitSet", "termSplitOn", "termSplitSnapshot", "termSplitRestore")

_PRE = r"""
var pane = new El("div"); pane.id = "ext_launch";
Object.defineProperty(pane, "innerHTML", {
  get: function () { return ""; },
  set: function (v) { pane.children.forEach(function (c) { c.parentNode = null; }); pane.children = []; pane._home = String(v); },
});
Object.defineProperty(pane, "firstChild", {get: function () { return pane.children[0] || null; }});
pane.insertBefore = function (n, ref) {
  if (n.parentNode) n.parentNode.removeChild(n);
  pane.children.splice(pane.children.indexOf(ref), 0, n); n.parentNode = pane; return n;
};
mount(pane);
document.getElementById = function (id) { return id === "ext_launch" ? pane : null; };
var alerts = [], extvt = [], EXT = [];
var win = {ExtVT: {open: function (s, m) { extvt.push([s, m]); }}};
var src = SRC;
var factory = new Function("document", "location", "fetch", "EXT", "SIDE_EXT", "ico", "esc", "toast", "cur", "window", "alert",
  %(names)s, src + "; return {EXT: EXT, setCur: function (v) { cur = v; }};");
var api = factory(document, location, fetch, EXT, [], function (n) { return "<i>" + n + "</i>"; },
  function (s) { return String(s); }, function () {}, "abc", win, function (m) { alerts.push(m); },
  %(args)s);
var render = EXT[0];
function tick() { return new Promise(function (r) { setTimeout(r, 5); }); }
function cur() { return pane.children[0]; }
fetchImpl = function (url, opts) {
  var b = JSON.parse(opts.body);
  if (b.session === "") return Promise.resolve({status: 400, ok: false, json: function () { return Promise.resolve({}); }});
  return Promise.resolve({status: 200, ok: true, json: function () { return Promise.resolve({}); }});
};
"""


def _go(body):
    pre = _PRE % {"names": ", ".join('"%s"' % n for n in _NAMES), "args": ", ".join(_NAMES)}
    pre = pre.replace("SRC", __import__("json").dumps(D.read("ext_launch.js")), 1)
    return D.go(pre + "\n" + body)


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestClassicPane(unittest.TestCase):
    def test_a_open_menu_and_item_focus_survive_rerender(self):
        out = _go("""
render({}); await tick();
var old = cur(); dispatch(old._ts.caret, "click", {});
old._ts.iExt.focus();
render({}); await tick();
var n = cur();
out.rebuilt = n !== old; out.exp = n._ts.caret.getAttribute("aria-expanded");
out.listHidden = n._ts.list.hidden; out.focusOnNewItem = document.activeElement === n._ts.iExt;
out.key = n.getAttribute("data-tsplit-key");
""")
        self.assertTrue(out["rebuilt"])
        self.assertEqual(out["exp"], "true")
        self.assertFalse(out["listHidden"])
        self.assertTrue(out["focusOnNewItem"])
        self.assertEqual(out["key"], "ext_launch:abc")

    def test_b_caret_focus_with_menu_closed(self):
        out = _go("""
render({}); await tick();
cur()._ts.caret.focus();
render({}); await tick();
var n = cur();
out.focus = document.activeElement === n._ts.caret; out.exp = n._ts.caret.getAttribute("aria-expanded");
out.hidden = n._ts.list.hidden;
""")
        self.assertTrue(out["focus"])
        self.assertEqual(out["exp"], "false")
        self.assertTrue(out["hidden"])

    def test_c_changed_cur_is_not_restored(self):
        out = _go("""
render({}); await tick();
dispatch(cur()._ts.caret, "click", {});
api.setCur("def");
render({}); await tick();
var n = cur();
out.exp = n._ts.caret.getAttribute("aria-expanded"); out.hidden = n._ts.list.hidden;
out.key = n.getAttribute("data-tsplit-key");
out.focusInNew = n.contains(document.activeElement);
""")
        self.assertEqual(out["key"], "ext_launch:def")
        self.assertEqual(out["exp"], "false")
        self.assertTrue(out["hidden"])
        self.assertFalse(out["focusInNew"])

    def test_d_remote_host_no_external_no_posts(self):
        out = _go("""
location.hostname = "example.com"; resetExt();
render({}); await tick();
out.extHidden = cur()._ts.iExt.hidden; out.posts = fetchCalls.length;
""")
        self.assertTrue(out["extHidden"])
        self.assertEqual(out["posts"], 0)

    def test_d_local_400_shows_external(self):
        out = _go("""
location.hostname = "localhost"; resetExt();
render({}); await tick();
out.extHidden = cur()._ts.iExt.hidden; out.label = cur()._ts.label.textContent;
out.probes = fetchCalls.length;
""")
        self.assertFalse(out["extHidden"])
        self.assertEqual(out["label"], "Resume externally")
        self.assertEqual(out["probes"], 1)

    def test_d_openterm_403_hides_external_on_next_render(self):
        out = _go("""
render({}); await tick();
out.before = cur()._ts.iExt.hidden;
fetchImpl = function () { return Promise.resolve({status: 403, ok: false, json: function () { return Promise.resolve({error: "nope"}); }}); };
dispatch(cur()._ts.iExt, "click", {});
await tick(); await tick();
out.after = cur()._ts.iExt.hidden; out.alerts = alerts.slice();
""")
        self.assertFalse(out["before"])
        self.assertTrue(out["after"])
        self.assertEqual(out["alerts"], ["nope"])

    def test_e_non_claude_cur(self):
        out = _go("""
api.setCur("auggie:x");
render({}); await tick();
var t = cur()._ts;
out.res = t.res.hidden; out.open = t.open.hidden; out.openItem = t.iOpen.hidden;
out.label = t.label.textContent;
fetchCalls.length = 0;
dispatch(t.iExt, "click", {}); await tick();
out.body = fetchCalls.map(function (c) { return JSON.parse(c.opts.body); });
dispatch(t.open, "click", {});
out.vt = extvt.slice();
""")
        self.assertTrue(out["res"])
        self.assertFalse(out["open"])
        self.assertTrue(out["openItem"])
        self.assertEqual(out["label"], "Open externally")
        self.assertEqual(out["body"], [{"session": "auggie:x", "mode": "cwd"}])
        self.assertEqual(out["vt"], [["auggie:x", "cwd"]])

    def test_e_claude_external_resumes_and_primary_opens_inline(self):
        out = _go("""
render({}); await tick();
var t = cur()._ts;
fetchCalls.length = 0;
dispatch(t.iExt, "click", {}); await tick();
out.body = fetchCalls.map(function (c) { return JSON.parse(c.opts.body); });
dispatch(t.res, "click", {});
out.vt = extvt.slice();
""")
        self.assertEqual(out["body"], [{"session": "abc", "mode": "resume"}])
        self.assertEqual(out["vt"], [["abc", "resume"]])

    def test_f_root_is_tsplit_and_note_kept(self):
        out = _go("""
render({meta: {term_home_note: "gone"}}); await tick();
out.cls = cur().className; out.home = pane._home;
""")
        self.assertIn("tsplit", out["cls"].split())
        self.assertIn("extlaunchnote", out["home"])

    def test_g_source_has_no_old_markup(self):
        src = D.read("ext_launch.js")
        for gone in ("extnative", "extvtopenbtn", "extvtresumebtn", "extopenbtn", "extresumebtn",
                     "function probe", "var probing", "var allowed"):
            self.assertNotIn(gone, src, gone)
        self.assertIn("termSplitRestore(snap);", src)
        self.assertIn("termExtDeny();", src)


if __name__ == "__main__":
    unittest.main()
