"""Session-header split button (Unit 2): mountHeaderSplit / syncHeaderSplit in ext_cr_detail.js and the
`session:openExternal` handler in ext_cr_boot.js.

Extract-based: the two header functions are brace-matched out of the shipped source and run under node
against the shared fake DOM + the real termSplit family (tests/_tsplit_dom.py).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import _tsplit_dom as D  # noqa: E402

PRE = r"""
function qs(n, sel) { return sel === ".crd-split-slot" ? n._slot : null; }
function mkNode() { var n = new El("div"); n._slot = new El("span"); mount(n); n.appendChild(n._slot); return n; }
var emitted = [];
var ctx = {emit: function (ev, p) { emitted.push([ev, p && p.id]); }};
var ui = {sid: "S1"};
function vis(sp) {
  var t = sp._ts, o = {};
  [["res", t.res], ["open", t.open], ["iOpen", t.iOpen], ["iExt", t.iExt]].forEach(function (p) {
    o[p[0]] = p[1].hidden ? null : p[1].textContent;
  });
  o.label = t.label.textContent;
  return o;
}
function setup(sid) {
  var node = mkNode(); mountHeaderSplit(node, ctx, ui); syncHeaderSplit(node, sid); return node;
}
"""


def _run(body):
    src = D.read("ext_cr_detail.js")
    fns = D.extract(src, "mountHeaderSplit") + "\n" + D.extract(src, "syncHeaderSplit")
    js = (D.FAKE_DOM + D.helpers_js() + "\n" + fns + "\n" + PRE +
          "\n(async function () {\nvar out = {};\n" + body +
          "\nconsole.log('OUT:' + JSON.stringify(out));\n})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });")
    return D.run(js)


def _strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$|(?<=\s)//.*$", "", s)


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestHeaderSplit(unittest.TestCase):
    def test_a_claude_id(self):
        out = _run("""
var node = setup("S1"); await fetchCalls.length; await termExtProbe();
syncHeaderSplit(node, "S1");
out.v = vis(node._crSplit);
""")
        v = out["v"]
        self.assertEqual(v["res"], "Resume")
        self.assertIsNone(v["open"])
        self.assertEqual(v["iOpen"], "Open terminal")
        self.assertEqual(v["label"], "Resume externally")
        self.assertIsNotNone(v["iExt"])

    def test_b_auggie_id(self):
        out = _run("""
var node = setup("auggie:x"); await termExtProbe(); syncHeaderSplit(node, "auggie:x");
out.v = vis(node._crSplit);
""")
        v = out["v"]
        self.assertIsNone(v["res"])
        self.assertEqual(v["open"], "Open terminal")
        self.assertIsNone(v["iOpen"])
        self.assertEqual(v["label"], "Open externally")

    def test_c_server_flag_wins(self):
        out = _run("""
sessions = [{id: "bare", resumable: false}];
var node = setup("bare");
out.v = vis(node._crSplit);
""")
        self.assertIsNone(out["v"]["res"])
        self.assertEqual(out["v"]["open"], "Open terminal")

    def test_d1_evil_host_hidden_and_no_fetch(self):
        out = _run("""
location.hostname = "localhost.evil.com";
var node = setup("S1");
out.v = vis(node._crSplit); out.fetches = fetchCalls.length;
""")
        self.assertIsNone(out["v"]["iExt"])
        self.assertEqual(out["fetches"], 0)

    def test_d2_403_hides_external(self):
        out = _run("""
fetchImpl = function () { return Promise.resolve({status: 403}); };
var node = setup("S1"); await termExtProbe();
out.v = vis(node._crSplit);
""")
        self.assertIsNone(out["v"]["iExt"])

    def test_d3_400_shows_after_probe_without_rerender(self):
        out = _run("""
var node = setup("S1");
out.before = vis(node._crSplit).iExt;
await termExtProbe(); await Promise.resolve();
out.after = vis(node._crSplit).iExt;
""")
        self.assertIsNone(out["before"])
        self.assertIn("Resume externally", out["after"])

    def test_e_events(self):
        out = _run("""
var node = setup("S1"); await termExtProbe(); await Promise.resolve();
var t = node._crSplit._ts;
dispatch(t.res, "click");
out.plain = emitted.slice(); emitted.length = 0;
dispatch(t.res, "click", {altKey: true});
out.alt = emitted.slice(); emitted.length = 0;
dispatch(t.iExt, "click");
out.ext = emitted.slice(); emitted.length = 0;
dispatch(t.iOpen, "click");
out.open = emitted.slice();
""")
        self.assertEqual(out["plain"], [["session:resume", "S1"]])
        self.assertEqual(out["alt"], [["session:openExternal", "S1"]])
        self.assertEqual(out["ext"], [["session:openExternal", "S1"]])
        self.assertEqual(out["open"], [["terminal:open", "S1"]])

    def test_f_render_header_has_no_local_host_regex(self):
        src = D.read("ext_cr_detail.js")
        body = _strip_comments(D.extract(src, "renderHeader"))
        self.assertNotIn("isLocalhost", body)
        self.assertNotIn("location.hostname", body)
        self.assertIn("syncHeaderSplit(", body)

    def test_g_boot_openexternal(self):
        boot = D.read("ext_cr_boot.js")
        a = boot.index("on('session:openExternal'")
        sl = boot[a:a + 2500]
        self.assertIn("termResumable(", sl)
        self.assertEqual(sl.count("termExtDeny("), 2)
        self.assertNotIn("auggie|augment", sl)

    def test_h_skeleton_and_css(self):
        src = D.read("ext_cr_detail.js")
        self.assertIn('<span class="crd-split-slot"></span>', src)
        self.assertNotIn("termSplit(\n", src)
        for act in ("open-terminal", "data-act=\"external\"", "data-act=\"resume\""):
            self.assertNotIn(act, src)
        css = D.read("ext_cr_detail.css")
        self.assertIn(".cr .crd-split-slot{display:contents}", css)
        self.assertNotIn(".crd-row1-actions .tsplit", css)


if __name__ == "__main__":
    unittest.main()
