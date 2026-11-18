"""The shared split button (termSplit family in app.js + one CSS block in app.css).

Behaviour tests brace-match the real functions out of the shipped app.js and run them under node
against the fake DOM in tests/_tsplit_dom.py.  Case 14 instead loads the same functions into the
bundle harness's `_REAL_DOM_PREAMBLE` (the DOM ~20 other modules use) to prove they never touch
what that DOM cannot do (parsing innerHTML, closest(), selector queries, activeElement).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import _tsplit_dom as D  # noqa: E402


def _css():
    return D.read("app.css")


def _split_block():
    css = _css()
    a = css.index("/* Split button (termSplit in app.js)")
    b = css.index("/* Read-only view: cosmetic")
    return css[a:b]


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestMarkupAndSet(unittest.TestCase):
    def test_1_markup_and_aria(self):
        out = D.go("""
var sp = mkSplit({key: "hdr:1"}); termSplitSet(sp, {resumable: true, ext: true});
var t = sp._ts;
out.root = sp.className; out.reg = TSPLITS["hdr:1"] === sp;
out.prim = [t.res.tagName, t.res.getAttribute("type"), t.open.tagName, t.open.getAttribute("type")];
out.caret = {tag: t.caret.tagName, type: t.caret.getAttribute("type"), pop: t.caret.getAttribute("aria-haspopup"),
  exp: t.caret.getAttribute("aria-expanded"), ctl: t.caret.getAttribute("aria-controls"), label: t.caret.getAttribute("aria-label")};
out.list = {role: t.list.getAttribute("role"), id: t.list.getAttribute("id"), hidden: t.list.hidden};
out.items = [t.iOpen, t.iExt].map(function (b) { return [b.getAttribute("role"), b.getAttribute("tabindex"), b.getAttribute("type")]; });
out.hint = [t.hint.getAttribute("aria-hidden"), t.hint.textContent];
out.arrow = [t.iExt.children[1].getAttribute("aria-hidden"), t.iExt.children[1].textContent];
out.caretGlyph = [t.caret.children[1].getAttribute("aria-hidden"), t.caret.children[1].textContent];
out.noDup = TSPLITS["hdr:1"] === sp && Object.keys(TSPLITS).length;
""")
        self.assertIn("tsplit", out["root"].split())
        self.assertTrue(out["reg"])
        self.assertEqual(out["prim"], ["BUTTON", "button", "BUTTON", "button"])
        c = out["caret"]
        self.assertEqual((c["tag"], c["type"], c["pop"], c["exp"]), ("BUTTON", "button", "menu", "false"))
        self.assertEqual(c["ctl"], out["list"]["id"])
        self.assertIn("Resume", c["label"])
        self.assertEqual((out["list"]["role"], out["list"]["hidden"]), ("menu", True))
        self.assertEqual(out["items"], [["menuitem", "-1", "button"]] * 2)
        self.assertEqual(out["hint"], ["true", "⌥-click"])
        self.assertEqual(out["arrow"], ["true", " ↗"])
        self.assertEqual(out["caretGlyph"], ["true", "▾"])

    def test_2_set_truth_table(self):
        rows = D.go("""
out.rows = [];
[true, false].forEach(function (r) { [true, false].forEach(function (here) { [true, false].forEach(function (ext) {
  var sp = mkSplit({}); termSplitSet(sp, {resumable: r, here: here, ext: ext}); var t = sp._ts;
  out.rows.push({r: r, here: here, ext: ext, res: t.res.hidden, open: t.open.hidden, iOpen: t.iOpen.hidden,
    iExt: t.iExt.hidden, label: t.label.textContent, caret: t.caret.hidden, solo: sp.classList.contains("tsplit-solo"),
    nomenu: sp.classList.contains("tsplit-nomenu"), hidden: sp.hidden,
    hint: t.res.title.indexOf("⌥-click") >= 0 && t.open.title.indexOf("⌥-click") >= 0,
    nohint: t.res.title.indexOf("⌥-click") < 0 && t.open.title.indexOf("⌥-click") < 0,
    cname: t.caret.getAttribute("aria-label")});
}); }); });
""")["rows"]
        self.assertEqual(len(rows), 8)
        for x in rows:
            any_item = (x["here"] and x["r"]) or x["ext"]
            tag = repr((x["r"], x["here"], x["ext"]))
            self.assertEqual(x["res"], not (x["here"] and x["r"]), tag)
            self.assertEqual(x["open"], not (x["here"] and not x["r"]), tag)
            self.assertEqual(x["iOpen"], not (x["here"] and x["r"]), tag)
            self.assertEqual(x["iExt"], not x["ext"], tag)
            self.assertEqual(x["label"], "Resume externally" if x["r"] else "Open externally", tag)
            self.assertEqual(x["caret"], not any_item, tag)
            self.assertEqual(x["solo"], (not x["here"]) and any_item, tag)
            self.assertEqual(x["nomenu"], not any_item, tag)
            self.assertEqual(x["hidden"], (not x["here"]) and not x["ext"], tag)
            self.assertTrue(x["hint"] if x["ext"] else x["nohint"], tag)
            if not x["here"]:
                self.assertEqual(x["cname"], "External terminal options", tag)
            else:
                self.assertEqual(x["cname"], "More %s options" % ("Resume" if x["r"] else "Open terminal"), tag)


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestInteraction(unittest.TestCase):
    def test_3_caret_click_toggles_and_exclusive(self):
        out = D.go("""
var a = mkSplit({}), b = mkSplit({}); termSplitSet(a, {resumable: true, ext: true}); termSplitSet(b, {resumable: true, ext: true});
dispatch(a._ts.caret, "click");
out.aOpen = [isOpen(a), a._ts.list.hidden, document.activeElement === a._ts.iOpen];
dispatch(a._ts.caret, "click");
out.aClosed = [isOpen(a), a._ts.list.hidden];
dispatch(a._ts.caret, "click"); dispatch(b._ts.caret, "click");
out.exclusive = [isOpen(a), a._ts.list.hidden, isOpen(b)];
""")
        self.assertEqual(out["aOpen"], [True, False, True])
        self.assertEqual(out["aClosed"], [False, True])
        self.assertEqual(out["exclusive"], [False, True, True])

    def test_4_keys(self):
        out = D.go("""
var sp = mkSplit({}); termSplitSet(sp, {resumable: true, ext: true}); var t = sp._ts, ov = [];
document.addEventListener("keydown", function () { ov.push("overlay"); }, false);   // a fake overlay Escape handler
var eDown = key(t.caret, "ArrowDown");
function key(el, k, init) { return dispatch(el, "keydown", Object.assign({key: k}, init || {})); }
out.down = [isOpen(sp), document.activeElement === t.iOpen, eDown.defaultPrevented, eDown._stopped];
key(t.iOpen, "ArrowDown"); out.next = document.activeElement === t.iExt;
key(t.iExt, "ArrowDown"); out.wrapDown = document.activeElement === t.iOpen;
key(t.iOpen, "ArrowUp"); out.wrapUp = document.activeElement === t.iExt;
key(t.iExt, "Home"); out.home = document.activeElement === t.iOpen;
key(t.iOpen, "End"); out.end = document.activeElement === t.iExt;
var other = key(t.iExt, "a"); out.other = [isOpen(sp), other.defaultPrevented, other._stopped]; ov.length = 0;
var esc = key(t.iExt, "Escape");
out.escItem = [isOpen(sp), t.list.hidden, document.activeElement === t.caret, esc.defaultPrevented, esc._stopped, ov.length];
dispatch(t.caret, "click");
var escCaret = key(t.caret, "Escape");
out.escCaret = [isOpen(sp), document.activeElement === t.caret, escCaret.defaultPrevented, escCaret._stopped, ov.length];
var escClosed = key(t.caret, "Escape");
out.escCaretClosed = [escClosed.defaultPrevented, ov.length];   // not ours: falls through to the overlay
var up = key(t.caret, "ArrowUp");
out.up = [isOpen(sp), document.activeElement === t.iExt, up.defaultPrevented];
var tab = key(t.iExt, "Tab");
out.tab = [isOpen(sp), document.activeElement === t.caret, tab.defaultPrevented, tab._stopped];
dispatch(t.caret, "click");
var ta = mount(new El("textarea")), escTa = key(ta, "Escape");
out.escTa = [isOpen(sp), escTa.defaultPrevented, escTa._stopped];
// skipping hidden items
var s2 = mkSplit({}); termSplitSet(s2, {resumable: false, ext: true});
key(s2._ts.caret, "ArrowDown"); var f1 = document.activeElement === s2._ts.iExt;
key(s2._ts.iExt, "ArrowDown"); var f2 = document.activeElement === s2._ts.iExt;
key(s2._ts.iExt, "ArrowUp"); var f3 = document.activeElement === s2._ts.iExt;
out.skip = [f1, f2, f3];
""")
        self.assertEqual(out["down"], [True, True, True, True])
        self.assertTrue(out["next"] and out["wrapDown"] and out["wrapUp"] and out["home"] and out["end"])
        self.assertEqual(out["other"], [True, False, False])
        self.assertEqual(out["escItem"], [False, True, True, True, True, 0])
        self.assertEqual(out["escCaret"], [False, True, True, True, 0])
        self.assertEqual(out["escCaretClosed"], [False, 1])
        self.assertEqual(out["up"], [True, True, True])
        self.assertEqual(out["tab"], [False, True, False, False])
        self.assertEqual(out["escTa"], [False, False, False])
        self.assertEqual(out["skip"], [True, True, True])

    def test_5_item_click_closes_focuses_caret_then_handler_once(self):
        out = D.go("""
var sp = mkSplit({}); termSplitSet(sp, {resumable: true, ext: true}); var t = sp._ts, seen = [];
termSplitOn(sp, {resume: function () {}, open: function () { seen.push("open:" + (document.activeElement === t.caret) + ":" + isOpen(sp)); },
  external: function () { seen.push("ext:" + (document.activeElement === t.caret) + ":" + isOpen(sp)); }});
dispatch(t.caret, "click"); dispatch(t.iExt, "click");
out.ext = [seen.slice(), isOpen(sp)];
var again = [];
termSplitOn(sp, {resume: function () {}, open: function () { again.push("open2"); }, external: function () { again.push("ext2"); }});
dispatch(t.caret, "click"); dispatch(t.iOpen, "click");
out.rebind = [again, seen.length];
""")
        self.assertEqual(out["ext"], [["ext:true:false"], False])
        self.assertEqual(out["rebind"], [["open2"], 1])

    def test_6_option_click_runs_external(self):
        out = D.go("""
var a = mkSplit({}); termSplitSet(a, {resumable: true, ext: true}); var la = bindLog(a);
dispatch(a._ts.res, "click", {altKey: true}); out.altRes = la.slice();
var b = mkSplit({}); termSplitSet(b, {resumable: true, ext: false}); var lb = bindLog(b);
dispatch(b._ts.res, "click", {altKey: true}); out.altNoExt = lb.slice();
dispatch(a._ts.caret, "click"); dispatch(a._ts.iOpen, "click", {altKey: true}); out.altItem = la.slice(1);
var c = mkSplit({resumable: false}); termSplitSet(c, {resumable: false, ext: true}); var lc = bindLog(c);
dispatch(c._ts.open, "click", {altKey: true}); out.altOpen = lc.slice();
dispatch(c._ts.open, "click"); out.plain = lc.slice(1);
var d = mkSplit({}); termSplitSet(d, {resumable: true, ext: true}); var ld = bindLog(d), thrown = "";
var fn = d._ts.res._listeners.filter(function (l) { return l.type === "click"; })[0].fn;
try { fn(undefined); fn({}); fn({target: d._ts.res}); } catch (e) { thrown = String(e); }
out.bare = [thrown, ld.slice()];
""")
        self.assertEqual(out["altRes"], ["external"])
        self.assertEqual(out["altNoExt"], ["resume"])
        self.assertEqual(out["altItem"], ["open"])
        self.assertEqual(out["altOpen"], ["external"])
        self.assertEqual(out["plain"], ["open"])
        self.assertEqual(out["bare"], ["", ["resume", "resume", "resume"]])

    def test_7_outside_close(self):
        out = D.go("""
var sp = mkSplit({}); termSplitSet(sp, {resumable: true, ext: true}); var t = sp._ts, away = mount(new El("div"));
function reopen() { dispatch(t.caret, "click"); return isOpen(sp); }
reopen(); dispatch(away, "pointerdown"); out.pd = isOpen(sp);
reopen(); dispatch(away, "click"); out.click = isOpen(sp);
reopen(); dispatch(t.list, "pointerdown"); dispatch(t.list, "click"); out.inside = isOpen(sp);
dispatch(t.caret, "pointerdown"); out.caretPd = isOpen(sp);
var other = mkSplit({}); termSplitSet(other, {resumable: true, ext: true});
dispatch(other._ts.caret, "pointerdown"); out.otherPd = isOpen(sp);
""")
        self.assertEqual((out["pd"], out["click"]), (False, False))
        self.assertEqual((out["inside"], out["caretPd"]), (True, True))
        self.assertFalse(out["otherPd"])

    def test_8_focusout(self):
        out = D.go("""
var sp = mkSplit({}); termSplitSet(sp, {resumable: true, ext: true}); var t = sp._ts, away = mount(new El("div"));
var o = mkSplit({}); termSplitSet(o, {resumable: true, ext: true});
function reopen() { dispatch(t.caret, "click"); }
reopen(); dispatch(t.iOpen, "focusout", {relatedTarget: away}); out.outside = isOpen(sp);
reopen(); dispatch(t.iOpen, "focusout", {relatedTarget: null}); out.nullRel = isOpen(sp);
dispatch(t.iOpen, "focusout", {relatedTarget: t.iExt}); out.same = isOpen(sp);
dispatch(t.iOpen, "focusout", {relatedTarget: o._ts.caret}); out.other = isOpen(sp);
""")
        self.assertEqual((out["outside"], out["nullRel"], out["same"], out["other"]), (False, True, True, False))

    def test_9_snapshot_restore(self):
        out = D.go("""
function rebuild(old, key, ext) {
  document.removeChild(old);
  var n = termSplit({key: key, primaryCls: "b", caretCls: "c", resumable: true}); termSplitSet(n, {resumable: true, ext: ext}); mount(n); return n;
}
var sp = termSplit({key: "board:1", primaryCls: "b", caretCls: "c", resumable: true}); mount(sp); termSplitSet(sp, {resumable: true, ext: true});
dispatch(sp._ts.caret, "click"); sp._ts.iExt.focus();
var snap = termSplitSnapshot("board:");
out.snap = [snap && snap.key, snap && snap.open, snap && snap.focus];
var n = rebuild(sp, "board:1", true);
out.fresh = [isOpen(n), document.activeElement === n._ts.iExt];
termSplitRestore(snap);
out.restored = [isOpen(n), n._ts.list.hidden, document.activeElement === n._ts.iExt, TSPLITS["board:1"] === n];
termSplitClose(); var n2 = n; n2._ts.caret.focus();
var snap2 = termSplitSnapshot("board:"); out.snap2 = [snap2.open, snap2.focus];
var n3 = rebuild(n2, "board:1", true); termSplitRestore(snap2);
out.caretFocus = [isOpen(n3), document.activeElement === n3._ts.caret];
dispatch(n3._ts.caret, "click");
var snap3 = termSplitSnapshot("board:");
var n4 = rebuild(n3, "board:2", true); termSplitRestore(snap3);
out.otherKey = [isOpen(n4), TSPLITS["board:1"] === undefined ? "gone" : "present"];
out.noPrefix = termSplitSnapshot("zzz:");
termSplitRestore(null);
""")
        self.assertEqual(out["snap"], ["board:1", True, "item:external"])
        self.assertEqual(out["fresh"], [False, False])
        self.assertEqual(out["restored"], [True, False, True, True])
        self.assertEqual(out["snap2"], [False, "caret"])
        self.assertEqual(out["caretFocus"], [False, True])
        self.assertFalse(out["otherKey"][0])
        self.assertIsNone(out["noPrefix"])

    def test_10_fit_flips_only_across_a_clipping_frame(self):
        out = D.go("""
function frame(cs) {
  var p = mount(new El("div")); p._cs = cs; p._rect = {left: 100};
  var sp = termSplit({key: "fit" + (++__n), primaryCls: "b", caretCls: "c", resumable: true}); termSplitSet(sp, {resumable: true, ext: true});
  p.appendChild(sp); sp._ts.list._rect = {left: 50}; return sp;
}
var h = frame({overflowX: "hidden"}); termSplitOpen(h, null);
out.hidden = h.classList.contains("tsplit-start");
var a = frame({overflowX: "auto"}); termSplitOpen(a, null);
out.auto = a.classList.contains("tsplit-start");
var y = frame({overflowX: "visible", overflowY: "auto"}); termSplitOpen(y, null);
out.yOnly = y.classList.contains("tsplit-start");
h._ts.list._rect = {left: 150}; termSplitOpen(h, null);
out.reopenFits = h.classList.contains("tsplit-start");
var v = mkSplit({}); termSplitSet(v, {resumable: true, ext: true}); v._ts.list._rect = {left: -20}; termSplitOpen(v, null);
out.viewport = v.classList.contains("tsplit-start");
""")
        self.assertTrue(out["hidden"], "list measured before it was unhidden, or the clipping frame was ignored")
        self.assertTrue(out["auto"])
        self.assertFalse(out["yOnly"])
        self.assertFalse(out["reopenFits"])
        self.assertTrue(out["viewport"])


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestPolicyHelpers(unittest.TestCase):
    def test_11_tracker_is_local(self):
        out = D.go("""
out.r = ["localhost", "127.0.0.1", "localhost.evil.com", "127.0.0.1.nip.io", "t1.localhost", "example.com", "evil-localhost"].map(
  function (h) { location.hostname = h; return trackerIsLocal(); });
""")
        self.assertEqual(out["r"], [True, True, False, False, False, False, False])

    def test_12_ext_allowed_probe(self):
        out = D.go("""
location.hostname = "example.com"; resetExt();
out.remote = [termExtAllowed(), termExtAllowed(), fetchCalls.length];
location.hostname = "localhost"; resetExt();
var first = termExtAllowed(); for (var i = 0; i < 6; i++) termExtAllowed();
out.cache = [first, fetchCalls.length, fetchCalls[0].url, fetchCalls[0].opts.method, fetchCalls[0].opts.body];
out.settled = await termExtProbe(); out.after = [termExtAllowed(), fetchCalls.length];
resetExt(); fetchImpl = function () { return Promise.resolve({status: 403}); };
out.p403 = [await termExtProbe(), TERM_EXT.allowed];
resetExt(); fetchImpl = function () { return Promise.resolve({status: 400}); };
out.p400 = [await termExtProbe(), TERM_EXT.allowed];
resetExt(); fetchImpl = function () { return Promise.reject(new Error("net")); };
out.pRej = [await termExtProbe(), TERM_EXT.allowed];
resetExt(); fetchImpl = function () { return Promise.resolve({status: 400}); };
termExtDeny(); out.deny = [termExtAllowed(), fetchCalls.length, await termExtProbe()];
""")
        self.assertEqual(out["remote"], [False, False, 0])
        self.assertEqual(out["cache"], [None, 1, "/api/term/open", "POST", '{"session":""}'])
        self.assertTrue(out["settled"])
        self.assertEqual(out["after"], [True, 1])
        self.assertEqual(out["p403"], [False, False])
        self.assertEqual(out["p400"], [True, True])
        self.assertEqual(out["pRej"], [False, False])
        self.assertEqual(out["deny"], [False, 0, False])

    def test_13_resumable(self):
        out = D.go("""
sessions = [{id: "a", resumable: false}, {id: "auggie:x", resumable: true}, {id: "b"}];
out.r = ["a", "auggie:x", "b", "auggie:y", "augment-vscode:z", "augment-cursor:q", "plain", "", null, undefined].map(termResumable);
""")
        self.assertEqual(out["r"], [False, True, True, False, False, False, True, False, False, False])


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestBundleHarness(unittest.TestCase):
    def test_14_runs_under_the_bundle_fake_dom(self):
        from tests.test_working_glow_board import _REAL_DOM_PREAMBLE, _REAL_DOM_MID, _run_node
        body = r"""
var sp = termSplit({key: "k1", primaryCls: "b", caretCls: "c", resumable: true, icons: {resume: "<i></i>"}});
docBody.appendChild(sp);
termSplitSet(sp, {resumable: true, ext: true});
var log = [];
termSplitOn(sp, {resume: function () { log.push("resume"); }, open: function () { log.push("open"); }, external: function () { log.push("external"); }});
termSplitOn(sp, {resume: function () { log.push("resume"); }, open: function () { log.push("open"); }, external: function () { log.push("external"); }});
sp._ts.caret._listeners.click({target: sp._ts.caret});
var open = sp._ts.caret.getAttribute("aria-expanded");
var snap = termSplitSnapshot("k");
termSplitRestore(snap);
termSplitClose();
termSplitSet(sp, {resumable: false, here: false, ext: true});
termSplitOnKey({key: "Escape", target: sp._ts.caret});
termSplitOnClick({}); termSplitOnPointerDown({}); termSplitOnFocusOut({});
termSplitSet(sp, {resumable: true, ext: true});
simulateClick(sp._ts.res);
console.log("OUT:" + JSON.stringify({log: log, open: open, snap: snap && snap.open}));
"""
        js = "\n".join([_REAL_DOM_PREAMBLE, D.helpers_js(), body, _REAL_DOM_MID])
        rc, out, err = _run_node(js)
        self.assertEqual(rc, 0, err[-1500:])
        got = D.json.loads(out.split("OUT:", 1)[1])
        self.assertEqual(got["log"], ["resume"])
        self.assertEqual(got["open"], "true")
        self.assertTrue(got["snap"])

    def test_14b_helpers_do_not_use_selector_queries_or_innerhtml_parsing(self):
        src = "\n".join(D.extract(D.read("app.js"), n) for n in D.FUNCTIONS)
        for bad in ("querySelector", "closest(", "matches(", "getElementById", "insertAdjacentHTML"):
            self.assertNotIn(bad, src, bad)
        self.assertEqual(len(re.findall(r"innerHTML", src)), 1, "only the optional icon string may use innerHTML")


class TestSources(unittest.TestCase):
    def test_15_css_block(self):
        css, block = _css(), _split_block()
        m = re.search(r"\.tsplit-list\{([^}]*)\}", css)
        self.assertIsNotNone(m)
        self.assertIn("z-index:80", m.group(1))
        self.assertIn("right:0", m.group(1))
        self.assertRegex(block, r"\.tsplit-list\[hidden\][^{]*\{display:none!important\}")
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
        self.assertIn("currentColor", block)
        tail = block.rstrip().splitlines()
        self.assertEqual(tail[-1], "html.tracker-readonly .tsplit{display:none!important}")
        after = css[css.index("html.tracker-readonly .tsplit{display:none!important}"):]
        nxt = after.split("\n", 1)[1]
        self.assertTrue(nxt.lstrip().startswith("/* Read-only view"), "read-only rule must sit directly before html.tracker-readonly .ren")
        self.assertIn("html.tracker-readonly .ren,", nxt)
        for gone in ("tsplit-menu", "::-webkit-details-marker", "#extnative"):
            self.assertNotIn(gone, css, gone)

    def test_15f_caret_min_width_is_28px(self):
        m = re.search(r"\.tsplit:not\(\.tsplit-solo\):not\(\.tsplit-nomenu\)>\.tsplit-caret\{([^}]*)\}", _css())
        self.assertIsNotNone(m)
        w = re.search(r"min-width:(\d+)px", m.group(1))
        self.assertIsNotNone(w)
        self.assertGreaterEqual(int(w.group(1)), 28)
        self.assertIn("box-sizing:border-box", m.group(1))

    def test_15b_no_state_class_in_any_css(self):
        allowed = {"solo", "nomenu", "start", "primary", "caret", "list", "item", "hint", "solo-label", "ico", "txt", "label", "arrow"}
        seen = set()
        for fn in os.listdir(D.WEB):
            if fn.endswith(".css"):
                seen |= set(re.findall(r"\.tsplit-([\w-]+)", D.read(fn)))
        self.assertEqual(seen - allowed, set())

    def test_15c_shared_helpers_have_no_details_markup(self):
        for fn in ("app.js", "app.css"):
            src = D.read(fn)
            for bad in ("tsplit-menu", "<details", "<summary"):
                self.assertFalse(bad in src, "%s: %s" % (fn, bad))

    def test_16_listeners_and_exports(self):
        app = D.read("app.js")
        for typ, fn in (("click", "termSplitOnClick"), ("pointerdown", "termSplitOnPointerDown"),
                        ("keydown", "termSplitOnKey"), ("focusout", "termSplitOnFocusOut")):
            self.assertIn('document.addEventListener("%s",%s,true);' % (typ, fn), app)
        m = re.search(r"Object\.assign\(window,\{([^}]*)\}\)", app)
        self.assertIsNotNone(m)
        names = {n.strip() for n in m.group(1).split(",")}
        for n in ("trackerIsLocal", "termExtProbe", "termExtAllowed", "termExtDeny", "termResumable", "termSplit",
                  "termSplitSet", "termSplitOn", "termSplitOpen", "termSplitClose", "termSplitSnapshot", "termSplitRestore"):
            self.assertIn(n, names)

    @unittest.skipUnless(D.HAS_NODE, "node not available")
    def test_16b_listeners_register_with_capture(self):
        out = D.go("""
out.l = document._listeners.map(function (l) { return [l.type, l.cap, l.fn.name]; });
""")
        self.assertEqual(sorted(out["l"]), sorted([
            ["click", True, "termSplitOnClick"], ["pointerdown", True, "termSplitOnPointerDown"],
            ["keydown", True, "termSplitOnKey"], ["focusout", True, "termSplitOnFocusOut"]]))


@unittest.skipUnless(D.HAS_NODE, "node not available")
class TestReviewFixes(unittest.TestCase):
    def test_a1_registry_prunes_detached_splits(self):
        out = D.go("""
for (var i = 0; i < 5; i++) { var sp = mkSplit({key: "row:" + i}); document.removeChild(sp); }
mkSplit({key: "live"});
out.afterBuild = Object.keys(TSPLITS).sort();
var gone = mkSplit({key: "gone"}); document.removeChild(gone);
dispatch(document, "click", {});
out.afterOutside = Object.keys(TSPLITS).sort();
""")
        self.assertEqual(out["afterBuild"], ["live"])
        self.assertEqual(out["afterOutside"], ["live"])

    def test_a2_menu_label_follows_primary(self):
        out = D.go("""
var sp = mkSplit({key: "l"}); var t = sp._ts;
termSplitSet(sp, {resumable: true, ext: true});
out.r = [t.list.getAttribute("aria-label"), t.caret.getAttribute("aria-label")];
termSplitSet(sp, {resumable: false, ext: true});
out.o = [t.list.getAttribute("aria-label"), t.caret.getAttribute("aria-label")];
""")
        self.assertEqual(out["r"], ["Resume options", "More Resume options"])
        self.assertEqual(out["o"], ["Open terminal options", "More Open terminal options"])

    def test_a3_deny_hides_external_in_every_live_split(self):
        out = D.go("""
var a = mkSplit({key: "hdr:1"}), b = mkSplit({key: "hero:1"}), c = mkSplit({key: "old"});
document.removeChild(c);
[a, b, c].forEach(function (s) { termSplitSet(s, {resumable: true, ext: true}); });
out.before = [a._ts.iExt.hidden, b._ts.iExt.hidden];
termExtDeny();
out.after = [a._ts.iExt.hidden, b._ts.iExt.hidden, a._ts.iOpen.hidden, a._ts.caret.hidden];
""")
        self.assertEqual(out["before"], [False, False])
        self.assertEqual(out["after"], [True, True, False, False])

    def test_s1_hint_only_with_a_primary(self):
        out = D.go("""
var sp = mkSplit({key: "h"}); var t = sp._ts;
termSplitSet(sp, {resumable: true, ext: true});
out.here = t.hint.hidden;
termSplitSet(sp, {resumable: true, here: false, ext: true});
out.solo = t.hint.hidden;
""")
        self.assertFalse(out["here"])
        self.assertTrue(out["solo"])


class TestNoStrayCallerStyling(unittest.TestCase):
    """Cross-file sweep: needs Units 2-5 to have landed (callers' own CSS/markup moved onto the shared block)."""

    def test_15d_no_details_markup_anywhere_in_web(self):
        for fn in sorted(os.listdir(D.WEB)):
            if fn.endswith((".js", ".css", ".html")):
                src = D.read(fn)
                for bad in ("tsplit-menu", "<details", "<summary"):
                    self.assertFalse(bad in src, "%s: %s" % (fn, bad))

    def test_15e_only_app_css_styles_list_item_caret(self):
        pat = re.compile(r"\.tsplit-(list|item|caret)\b")
        for fn in sorted(os.listdir(D.WEB)):
            if not fn.endswith(".css") or fn == "app.css":
                continue
            css = re.sub(r"/\*.*?\*/", "", D.read(fn), flags=re.S)
            for sel in re.findall(r"([^{}]+)\{", css):
                for one in sel.split(","):
                    one = re.sub(r":not\([^)]*\)", "", one).strip()
                    last = re.split(r"[\s>+~]+", one)[-1] if one else ""
                    if pat.search(last):
                        sanctioned = ".tracker-next .cr-tile-sidebar .tsplit-caret"
                        self.assertEqual(" ".join(one.split()), sanctioned, "%s: %s" % (fn, one))


if __name__ == "__main__":
    unittest.main()
