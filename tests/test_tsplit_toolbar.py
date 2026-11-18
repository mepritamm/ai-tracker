"""In-terminal toolbar split button (ext_cr_term.js, Unit 3).

Extract-based: the real helpers come from app.js (tests/_tsplit_dom.py), and the toolbar's own
functions plus its mount block are brace-matched / sliced out of the shipped ext_cr_term.js and run
under node against the shared fake DOM.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import _tsplit_dom as D  # noqa: E402

SRC = D.read("ext_cr_term.js")


def _mount_block():
    a = SRC.index("var ts = termSplit({")
    b = SRC.index("el.split = ts;") + len("el.split = ts;")
    return SRC[a:b]


def _esc_listener():
    m = re.search(r'document\.addEventListener\("keydown", function \(ev\) \{\n.*?\n    \}\);', SRC, re.S)
    assert m, "overlay Escape listener not found"
    return m.group(0)


def _prelude():
    return "\n".join(D.extract(SRC, n) for n in
                     ("localOnly", "isClaudeId", "j", "post", "_openExternal", "_syncControlVisibility", "_syncSplit"))


def go(body, hostname="localhost"):
    head = """
location.hostname = "%s";
var calls = [];
var st = {sessionId: "abc", attached: false, open: true};
var el = {split: null};
var toasts = [];
function showToast(m) { toasts.push(m); }
function _openInline(sid, mode) { calls.push(["inline", sid, mode]); }
window.ExtVT = null;
""" % hostname
    mount = """
function mountBar() {
  var group = document.createElement("div");
  var bar = {querySelector: function () { return group; }};
  %s
  document.appendChild(group);
  return group;
}
""" % _mount_block()
    js = (D.FAKE_DOM + D.helpers_js() + head + _prelude() + mount +
          "\n(async function () {\nvar out = {};\n" + body +
          "\nconsole.log('OUT:' + JSON.stringify(out));\n})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });")
    return D.run(js)


STATE = """
function vis(sp) {
  var t = sp._ts;
  return {res: !t.res.hidden, open: !t.open.hidden, iOpen: !t.iOpen.hidden, iExt: !t.iExt.hidden,
          caret: !t.caret.hidden, solo: sp.classList.contains("tsplit-solo"), label: t.label.textContent,
          splitHidden: sp.hidden};
}
function clickOf(b) { return b._listeners.filter(function (l) { return l.type === "click"; })[0].fn; }
function tick() { return new Promise(function (r) { setTimeout(r, 10); }); }
"""


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestToolbarSplit(unittest.TestCase):
    def test_a_attached_claude_is_external_only(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true;
st.attached = true; _syncSplit();
out.v = vis(el.split);
""")
        v = out["v"]
        self.assertFalse(v["res"] or v["open"] or v["iOpen"])
        self.assertTrue(v["iExt"] and v["caret"] and v["solo"])

    def test_b_unattached_claude(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true; _syncSplit();
out.v = vis(el.split);
""")
        v = out["v"]
        self.assertTrue(v["res"] and not v["open"] and v["iOpen"] and v["iExt"] and not v["solo"])
        self.assertEqual(v["label"], "Resume externally")

    def test_c_auggie_open_terminal_and_cwd(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true; st.sessionId = "auggie:x"; _syncSplit();
out.v = vis(el.split);
var t = el.split._ts;
clickOf(t.iExt)({target: t.iExt});
await tick();
out.body = JSON.parse(fetchCalls[fetchCalls.length - 1].opts.body);
clickOf(t.open)({target: t.open});
out.calls = calls;
""")
        v = out["v"]
        self.assertTrue(v["open"] and not v["res"] and not v["iOpen"])
        self.assertEqual(v["label"], "Open externally")
        self.assertEqual(out["body"]["mode"], "cwd")
        self.assertEqual(out["calls"], [["inline", "auggie:x", "cwd"]])

    def test_d_remote_host_no_external_no_post(self):
        out = go(STATE + """
mountBar(); resetExt(); _syncControlVisibility();
await tick();
out.v = vis(el.split); out.n = fetchCalls.length;
""", hostname="tracker.example.com")
        self.assertFalse(out["v"]["iExt"])
        self.assertEqual(out["n"], 0)

    def test_d2_local_hidden_until_probe_then_shown(self):
        out = go(STATE + """
mountBar(); resetExt(); _syncControlVisibility();
out.before = vis(el.split).iExt;
await tick();
out.after = vis(el.split).iExt; out.n = fetchCalls.length;
""")
        self.assertFalse(out["before"])
        self.assertTrue(out["after"])
        self.assertEqual(out["n"], 1)

    def test_e_403_hides_external(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true; _syncSplit();
out.before = vis(el.split).iExt;
fetchImpl = function () { return Promise.resolve({status: 403, ok: false, json: function () { return Promise.resolve({error: "off"}); }}); };
_openExternal("resume");
await tick();
out.after = vis(el.split).iExt;
""")
        self.assertTrue(out["before"])
        self.assertFalse(out["after"])

    def test_primary_click_calls_inline(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true; _syncSplit();
var t = el.split._ts;
clickOf(t.res)({target: t.res});
out.calls = calls;
""")
        self.assertEqual(out["calls"], [["inline", "abc", "resume"]])

    def test_g_escape_does_not_close_overlay_when_menu_open(self):
        out = go(STATE + """
mountBar(); resetExt(); TERM_EXT.allowed = true; _syncSplit();
var closed = 0;
var overlay = {classList: {contains: function () { return true; }}};
function close() { closed++; }
""" + _esc_listener() + """
var sp = el.split, t = sp._ts;
termSplitOpen(sp, "first");
var e1 = dispatch(t.caret, "keydown", {key: "Escape"});
out.afterMenu = {closed: closed, stopped: e1._stopped, open: isOpen(sp)};
var ta = document.createElement("textarea"); mount(ta);
dispatch(ta, "keydown", {key: "Escape"});
out.afterXterm = closed;
""")
        # Escape on the caret with the menu open is handled by the split; the overlay stays open.
        self.assertEqual(out["afterMenu"], {"closed": 0, "stopped": True, "open": False})
        # Escape from a fake xterm textarea with no open menu passes through to the overlay.
        self.assertEqual(out["afterXterm"], 1)

    def test_f_source_has_no_legacy_wiring(self):
        for dead in ("_placeOpenHere", "ext-terminal", "ext-resume", "extAllowed", "_probeExternal", "termSplitSync"):
            self.assertNotIn(dead, SRC)
        m = re.search(r"function close\(\) \{.*?\n  \}", SRC, re.S)
        self.assertIn("termSplitClose();", m.group(0))
        self.assertNotIn("tsplit-list", D.read("ext_cr_term.css"))


if __name__ == "__main__":
    unittest.main()
