"""Client half of the heartbeat panel (aitracker/web/ext_cr_detail.js).

Runs the REAL assembled page bundle in node under test_cr_logic's stub DOM -- which also
proves no ext_*.js file throws at load time (all of them share one <script> tag, so a
load-time throw silently kills every later file) -- then calls the pure helpers exported
on window.CR.detail._internal with hand-made fixtures shaped like the server's
`session.heartbeat`.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_cr_logic as L  # noqa: E402

_DRIVER = r"""
var I = window.CR.detail._internal;
var OUT = {};
function setPref(v) { if (v === undefined) localStorage.removeItem("cr.progressView"); else localStorage.setItem("cr.progressView", v); }
OUT.pv = {};
setPref(undefined);              OUT.pv.unset = I.progressView();
setPref('"spine"');              OUT.pv.spine = I.progressView();
setPref('"heartbeat"');          OUT.pv.heartbeat = I.progressView();
setPref('spine');                OUT.pv.raw = I.progressView();   // raw, not JSON -> parse fails -> default
setPref('{{garbage');            OUT.pv.garbage = I.progressView();
setPref('42');                   OUT.pv.num = I.progressView();
setPref(undefined);

function fakeNode() {
  var hb = { hidden: false }, sp = { hidden: false };
  return { hb: hb, sp: sp, querySelector: function (sel) {
    return sel.indexOf("heartbeat") >= 0 ? hb : (sel.indexOf("spine") >= 0 ? sp : null); } };
}
var n1 = fakeNode(); I.applyProgressView(n1, "heartbeat");
OUT.apply_hb = [n1.hb.hidden, n1.sp.hidden];
var n2 = fakeNode(); I.applyProgressView(n2, "spine");
OUT.apply_sp = [n2.hb.hidden, n2.sp.hidden];
I.applyProgressView(null, "spine"); I.applyProgressView({}, "spine");

OUT.pdc = {};
localStorage.removeItem("cr.cardsFolded");
OUT.pdc.unset = ["heartbeat", "spine", "timeline", "files"].map(I.panelDefaultCollapsed);
localStorage.setItem("cr.cardsFolded", "false");
OUT.pdc.unfolded = ["heartbeat", "spine", "timeline", "files"].map(I.panelDefaultCollapsed);
localStorage.removeItem("cr.cardsFolded");

OUT.tok = [950, 0, 1234, 18234, 1234567, 18.2e6, 999999, 9999].map(I.fmtTokS);
OUT.tokB = [1.367e9, 999.6e6, 999e6, 1e9, 25e9].map(I.fmtTokS);

var HB = %(hb)s;
OUT.full = I.heartbeatHtml(HB, true);
OUT.full_idle = I.heartbeatHtml(HB, false);
OUT.summary = I.heartbeatSummaryHtml(HB);
OUT.empty_note = I.heartbeatHtml({ beats: [], note: "Auggie <b>x</b>" }, false);
OUT.empty_none = I.heartbeatHtml(null, false);
OUT.empty_sum = I.heartbeatSummaryHtml(null);
var HB2 = JSON.parse(JSON.stringify(HB)); HB2.waiting_ms = 0; HB2.by_tool.rows[0].busy_ms = null; HB2.by_tool.rest = null;
HB2.by_tool.rows.forEach(function (r) { r.busy_ms = null; });
OUT.nobusy = I.heartbeatHtml(HB2, false);
OUT.nowait = I.heartbeatHtml(HB2, false);
// y-clamp: tiny `in` next to a max `out` bin (1-unit minimum height would push y below 0)
var HBY = { span: [0, 480], bucket_s: 240, total: {},
  beats: [{ t: 0, out: 1000000, fresh: 1, cache: 0, calls: 1 }, { t: 240, out: 1, fresh: 1000000, cache: 0, calls: 1 }] };
OUT.ys = (I.heartbeatHtml(HBY, false).match(/ y="[^"]*"/g) || []);

// renderHeartbeat / setPanelCollapsed against a fake wrap
function fakeEl(attrs) {
  var a = attrs || {}, cls = {};
  return { innerHTML: "", writes: 0, _a: a,
    classList: { toggle: function (c, v) { cls[c] = !!v; }, _c: cls },
    setAttribute: function (k, v) { a[k] = v; }, getAttribute: function (k) { return k in a ? a[k] : null; },
    hasAttribute: function (k) { return k in a; } };
}
function fakeWrap(headAttrs) {
  var els = { ".crd-panel-count": fakeEl(), ".crd-panel-body": fakeEl(), ".crd-chevron": fakeEl(),
              ".crd-panel-head": fakeEl(headAttrs) };
  var w = fakeEl({ "data-panel": "heartbeat" });
  w.els = els;
  w.querySelector = function (sel) { return els[sel] || null; };
  return w;
}
var w1 = fakeWrap({ role: "button" });
I.renderHeartbeat(w1, "heartbeat", HB, true);
OUT.rh_body = w1.els[".crd-panel-body"].innerHTML;
OUT.rh_count = w1.els[".crd-panel-count"].innerHTML;
w1.els[".crd-panel-body"].innerHTML = "SENTINEL";
I.renderHeartbeat(w1, "heartbeat", JSON.parse(JSON.stringify(HB)), true);
OUT.rh_same = w1.els[".crd-panel-body"].innerHTML;
I.renderHeartbeat(w1, "heartbeat", HB, false);   // `live` changed -> must redraw
OUT.rh_changed = w1.els[".crd-panel-body"].innerHTML;
var w2 = fakeWrap({ role: "button" });
I.renderHeartbeat(w2, "spine", HB, true);        // spine view: nothing drawn
OUT.rh_spine = w2.els[".crd-panel-body"].innerHTML;
I.renderHeartbeat(null, "heartbeat", HB, true);
var w3 = fakeWrap({ role: "button" }), w4 = fakeWrap({});
try { localStorage.removeItem("cr.cardsFolded"); } catch (e) {}
I.setPanelCollapsed({}, w3, "sidX", true);  OUT.sc_btn_closed = w3.els[".crd-panel-head"].getAttribute("aria-expanded");
I.setPanelCollapsed({}, w3, "sidX", false); OUT.sc_btn_open = w3.els[".crd-panel-head"].getAttribute("aria-expanded");
I.setPanelCollapsed({}, w4, "sidX", true);  OUT.sc_plain = w4.els[".crd-panel-head"].hasAttribute("aria-expanded");
console.log("===CR_LOGIC_JSON_START===");
console.log(JSON.stringify(OUT));
"""

HB = {
    "span": [1700000000, 1700007200], "bucket_s": 240,
    "beats": [
        {"t": 1700000000, "out": 100, "fresh": 500, "cache": 9000, "calls": 3},
        {"t": 1700000240, "out": 0, "fresh": 0, "cache": 0, "calls": 0},
        {"t": 1700000480, "out": 1200, "fresh": 8400, "cache": 210000, "calls": 7},
    ],
    "by_tool": {
        "rows": [
            {"name": "<img src=x onerror=alert(1)>", "calls": 212, "busy_ms": 840000},
            {"name": "Edit", "calls": 40, "busy_ms": 38000},
            {"name": "Read", "calls": 9, "busy_ms": None},
        ],
        "rest": {"n": 5, "calls": 9},
    },
    "waiting_ms": 11520000,
    "by_agent": {
        "rows": [
            {"label": "main", "aid": "", "model": "claude-opus-4-7", "out": 11000, "fresh": 300000, "cache": 11000000},
            {"label": "Opus plan review", "aid": "abc1234567", "model": "claude-opus-4-7", "out": 5000, "fresh": 100000, "cache": 4000000},
        ],
        "rest": {"n": 124, "out": 100000, "fresh": 1000000, "cache": 2000000},
    },
    "by_model": {
        "rows": [{"model": "claude-opus-4-7", "out": 16000, "fresh": 400000, "cache": 15000000}],
        "rest": None,
    },
    "total": {"out": 18234, "fresh": 394000, "cache": 18200000, "calls": 87},
    "agents_n": 12, "note": "Tools ranked by calls.",
}


@unittest.skipUnless(L._HAS_NODE, "node not available")
class TestHeartbeatUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = "\n".join([L._JS_PREAMBLE, L._extract_script_content(L._read_page()), L._JS_MID,
                        _DRIVER % {"hb": json.dumps(HB)}])
        rc, out, err = L._run_node(js)
        assert rc == 0, "node failed (a load-time throw in some ext_*.js?):\n" + err + out
        cls.o = L._extract_json(out)

    def test_progress_view(self):
        pv = self.o["pv"]
        self.assertEqual(pv["unset"], "heartbeat")
        self.assertEqual(pv["spine"], "spine")
        self.assertEqual(pv["heartbeat"], "heartbeat")
        self.assertEqual(pv["raw"], "heartbeat")      # un-JSON'd `spine` is not what writePref writes
        self.assertEqual(pv["garbage"], "heartbeat")
        self.assertEqual(pv["num"], "heartbeat")

    def test_apply_progress_view_toggles_hidden(self):
        self.assertEqual(self.o["apply_hb"], [False, True])
        self.assertEqual(self.o["apply_sp"], [True, False])

    def test_panel_default_collapsed(self):
        # heartbeat, spine, timeline open by default; others follow cr.cardsFolded (absent -> folded)
        self.assertEqual(self.o["pdc"]["unset"], [False, False, False, True])
        self.assertEqual(self.o["pdc"]["unfolded"], [False, False, False, False])

    def test_fmt_toks(self):
        self.assertEqual(self.o["tok"][:6], ["950", "0", "1.2k", "18k", "1.2M", "18M"])
        self.assertEqual(self.o["tok"][6], "1M")      # 999,999 must not print "1000k"
        self.assertEqual(self.o["tok"][7], "10k")

    def test_fmt_toks_billions(self):
        self.assertEqual(self.o["tokB"], ["1.4B", "1B", "999M", "1B", "25B"])

    def test_bar_y_never_negative(self):
        ys = [float(y.split('"')[1]) for y in self.o["ys"]]
        self.assertGreaterEqual(len(ys), 6)
        self.assertTrue(all(y >= 0 for y in ys), ys)

    def test_legend_keys(self):
        h = self.o["full"]
        for c in ("crd-hb-key-out", "crd-hb-key-in", "crd-hb-key-cache"):
            self.assertIn('class="crd-hb-key ' + c + '" aria-hidden="true"', h)
        self.assertIn("cached (lists only)", h)

    def test_render_heartbeat_writes_body_and_count(self):
        self.assertIn("crd-hb-svg", self.o["rh_body"])
        self.assertIn("incl. 12 agents", self.o["rh_count"])

    def test_render_heartbeat_identical_poll_skips_rewrite(self):
        self.assertEqual(self.o["rh_same"], "SENTINEL")
        self.assertIn("crd-hb-svg", self.o["rh_changed"])
        self.assertNotIn("crd-hb-live", self.o["rh_changed"])
        self.assertEqual(self.o["rh_spine"], "")

    def test_set_panel_collapsed_aria_only_on_button_header(self):
        self.assertEqual(self.o["sc_btn_closed"], "false")
        self.assertEqual(self.o["sc_btn_open"], "true")
        self.assertFalse(self.o["sc_plain"])

    def test_render_update_calls_render_heartbeat(self):
        import re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                            "aitracker", "web", "ext_cr_detail.js")
        with open(path, encoding="utf-8") as f:
            js = f.read()
        m = re.search(r"function renderUpdate\(root, ctx, state\) \{(.*?)\n  \}\n", js, re.S)
        self.assertTrue(m, "renderUpdate not found")
        self.assertIn("renderHeartbeat(", m.group(1))

    def test_empty_states(self):
        self.assertEqual(self.o["empty_note"], '<p class="crd-empty">Auggie &lt;b&gt;x&lt;/b&gt;</p>')
        self.assertEqual(self.o["empty_none"], '<p class="crd-empty">No model turns recorded yet.</p>')
        self.assertEqual(self.o["empty_sum"], "&mdash;")
        self.assertNotIn("crd-hb-lists", self.o["empty_note"])

    def test_full_render(self):
        h = self.o["full"]
        self.assertEqual(h.count("<g class=\"crd-hb-bin"), 3)
        self.assertEqual(h.count("crd-hb-live"), 1)           # only the last bin pulses
        self.assertNotIn("crd-hb-live", self.o["full_idle"])
        self.assertIn("now · live", h)
        self.assertIn("each bar ≈ 4m", h)
        self.assertIn("+124 more &middot; 3.1M", h)             # agents rest, server rollup as given
        self.assertIn("+5 more &middot; 9\u00d7", h)            # tools rest
        self.assertIn("14m · 212×", h)
        self.assertIn("Waiting on you or a prompt: 3h 12m (not counted as busy)", h)
        self.assertIn("Tools ranked by calls.", h)
        self.assertIn("1.2k out · 8.4k in · 210k cached · 7 calls", h)
        self.assertIn("crd-hb-main", h)                       # main agent row emphasised

    def test_tool_name_escaped(self):
        for k in ("full", "nobusy"):
            self.assertNotIn("<img", self.o[k])
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", self.o["full"])

    def test_null_busy_and_no_waiting(self):
        h = self.o["nobusy"]
        self.assertIn("Tools &middot; calls", h)
        self.assertIn("212×", h)
        self.assertNotIn("14m", h)
        self.assertNotIn("Waiting on you", h)
        self.assertNotIn("more &middot; 9", h)                # rest dropped in this fixture

    def test_summary(self):
        s = self.o["summary"]
        self.assertIn("18k out", s)
        self.assertIn("394k in", s)
        self.assertIn("18M cached", s)
        self.assertIn("87 calls", s)
        self.assertIn("2h 0m", s)
        self.assertIn("incl. 12 agents", s)


if __name__ == "__main__":
    unittest.main()
