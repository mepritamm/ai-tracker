"""The header line (job summary / narration + band pill) and the cost chip + modal, in BOTH views
(Control Room and classic). Real functions are brace-matched out of the served page bundle and
run under node with honest stubs -- never a retyped paraphrase."""
import json
import re
import unittest

from tests.test_classic_markdown_and_links import _HAS_NODE, _extract_after_marker, _run_node
from tests.test_cr_detail_agents_pill_and_markdown import _extract_function, _extract_script_content, _read_page


def _read_cr_detail():
    with open(__file__.rsplit("/", 2)[0] + "/aitracker/web/ext_cr_detail.js", encoding="utf-8") as fh:
        return fh.read()


def _bundle():
    return _extract_script_content(_read_page())


CR_DRIVER = r"""
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
function fmtNum(n) { return String(n); }
function md(s) { return esc(s); }
function qs(root, sel) { return root.querySelector(sel); }
%(fns)s
var OUT = {};
function line() { return { hidden: null, innerHTML: "", title: "", attrs: {}, setAttribute: function (k, v) { this.attrs[k] = v; } }; }
function nodeWith(el) { return { querySelector: function () { return el; } }; }
var el;
el = line(); paintGoalLine(nodeWith(el), { headline: { text: "Waiting on a pick", label: "Needs input", band: "blocked" } });
OUT.pill = [el.hidden, el.innerHTML, el.title, el.attrs["data-act"]];
el = line(); paintGoalLine(nodeWith(el), { headline: { text: "narrated", label: null, band: null } });
OUT.nopill = [el.hidden, el.innerHTML];
el = line(); paintGoalLine(nodeWith(el), { headline: { text: "", label: null } });
OUT.hidden = [el.hidden];
el = line(); paintGoalLine(nodeWith(el), { headline: { text: "boom", label: "Completed · failed", band: "done", state: "failed" } });
OUT.failed = el.innerHTML;
// the real chip row
var calls = [];
globalThis.openText = function (t, w, m) { calls.push([t, w, m]); };
%(costfns)s
var base = { counts: {}, files: [], commands: [], tokens: { in: 1, out: 2 }, meta: {} };
OUT.chipOn = statChipsHtml(Object.assign({ cost: { total_usd: 12.34, unpriced: [{ model: "x", tokens: 1 }] } }, base));
OUT.chipOff = statChipsHtml(Object.assign({ cost: { total_usd: null, unpriced: [] } }, base));
OUT.chipNone = statChipsHtml(base);
OUT.chipUnpricedOnly = statChipsHtml(Object.assign({ cost: { total_usd: null, unpriced: [{ model: "x", tokens: 1 }] } }, base));
openCostModal({ basis: "API list price", total_usd: 12.2, main_usd: 9, agents_usd: 3.2, reported_usd: 12.2, reported_unknown: true,
  cache: { read_tokens: 41000000, saved_gross_usd: 160.2, write_premium_usd: 21.7, saved_net_usd: 138.5 },
  agents: [{ aid: "a1", label: "explore | seam", usd: 3.2 }],
  models: [{ model: "claude-opus-5-5", label: "Opus 5.5", who: "main", usd: 9, in: 1200, w5m: 0, w1h: 900000, read: 38000000, out: 210000 }],
  unpriced: [{ model: "openai/gpt-6-luna", tokens: 1234567 }], note: "a note" });
openCostModal({ basis: "b", total_usd: 1, cache: {} });
OUT.modal = calls[0]; OUT.modal2 = calls[1];
console.log("===UI_JSON_START===");
console.log(JSON.stringify(OUT));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class HeaderAndCostUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = _bundle()
        cls.bundle = b
        fns = "\n".join(_extract_function(b, n) for n in ("statChip", "statChipsHtml", "paintGoalLine"))
        costfns = "\n".join(_extract_function(b, n) for n in ("_usd", "_ntok", "costChipText", "costModalMd", "openCostModal"))
        cls.STAT_CONST = 'var STAT_CHIP_MISSING = "--";\n'
        rc, out, err = _run_node(cls.STAT_CONST + CR_DRIVER % {"fns": fns, "costfns": costfns})
        if rc != 0:
            raise AssertionError("ui harness failed (%d)\n%s\n%s" % (rc, out, err))
        cls.OUT = _extract_after_marker(out, "===UI_JSON_START===")

    def test_cr_header_line_renders_headline_text_and_band_pill(self):
        hidden, html, title, act = self.OUT["pill"]
        self.assertFalse(hidden)
        self.assertTrue(html.startswith('<span class="crd-hl-band crd-hl-blocked">Needs input</span> Waiting on a pick'), html)
        self.assertIn("Needs input", title)
        self.assertEqual(act, "toggle-goal")
        self.assertEqual(self.OUT["nopill"], [False, "narrated"])          # label null -> no pill
        self.assertEqual(self.OUT["hidden"], [True])                        # empty text -> the line is hidden
        self.assertIn("crd-hl-done crd-hl-failed", self.OUT["failed"])

    def test_cr_cost_chip_is_button_and_opens_modal(self):
        on = self.OUT["chipOn"]
        self.assertIn('data-act="cost"', on)
        self.assertIn("<button", on)
        self.assertIn("$12.34+?", on)                                       # an unpriced model flags the total as partial
        self.assertNotIn('data-act="cost"', self.OUT["chipOff"])            # nothing priced, nothing unpriced -> no chip
        self.assertNotIn('data-act="cost"', self.OUT["chipNone"])           # no cost at all
        self.assertIn(">unpriced<", self.OUT["chipUnpricedOnly"].replace('<span class="crd-statchip-val">', ">").replace("</span>", "<"))
        title, when, md = self.OUT["modal"]
        self.assertEqual((title, when), ("Cost", "API list price"))
        self.assertIn("| **Burned (this session)** | **$12.20** |", md)
        self.assertIn("Saved by prompt caching (net)", md)
        self.assertIn("$138.50", md)
        self.assertIn("explore / seam", md)                                 # a | in a label can't break the table
        self.assertIn("openai/gpt-6-luna", md)

    def test_cost_modal_reported_line(self):
        self.assertIn("Claude Code reported $12.20 at last exit (includes sub-agents) — some models unpriced by Claude Code.",
                      self.OUT["modal"][2])
        self.assertNotIn("Claude Code reported", self.OUT["modal2"][2])

    def _click_driver(self, snippet, setup):
        costfns = "\n".join(_extract_function(self.bundle, n) for n in ("_usd", "_ntok", "costChipText", "costModalMd", "openCostModal"))
        drv = ('function esc(s){return String(s==null?"":s);} function fmtNum(n){return String(n);} function md(s){return esc(s);}\n'
               'var calls=[]; globalThis.openText=function(t,w,m){calls.push([t,w,m]);};\n' + costfns + "\n" + setup + "\n" + snippet +
               '\nconsole.log("===CLK_START==="); console.log(JSON.stringify(calls));')
        rc, out, err = _run_node(drv)
        self.assertEqual(rc, 0, err)
        return _extract_after_marker(out, "===CLK_START===")

    def test_delegated_handler_opens_the_modal(self):
        m = re.search(r'case "cost":(.*?)break;', _read_cr_detail(), re.S)
        self.assertIsNotNone(m)
        setup = 'function click(act, ui){ switch (act) { case "cost":' + m.group(1) + 'break; } }'
        calls = self._click_driver('click("cost", {lastSession: {cost: {basis: "API list price", total_usd: 3, cache: {}}}});', setup)
        self.assertEqual(calls[0][:2], ["Cost", "API list price"])
        calls = self._click_driver('click("cost", {lastSession: null});', setup)
        self.assertEqual(calls[0][0], "Cost")                       # no session yet -> empty cost, still no throw

    def test_classic_cost_chip_present(self):
        m = re.search(r'onclick="(openCostModal\(lastData\.cost\))"', self.bundle)
        self.assertIsNotNone(m)
        self.assertIn("costChipText(d.cost)", self.bundle)
        calls = self._click_driver(m.group(1) + ";", 'var lastData={cost:{basis:"b",total_usd:1,cache:{}}};')
        self.assertEqual(calls[0][:2], ["Cost", "b"])

    def test_auggie_session_with_no_usage_has_no_cost_chip(self):
        """CF1 end to end: the REAL server payload for a zero-usage Auggie session -> no chip."""
        import json as _json, os, shutil, tempfile
        from aitracker import config
        from aitracker.providers import auggie as A
        snap = (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR)
        config.AUGMENT_DIR = tempfile.mkdtemp()
        config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
        os.makedirs(config.AUGGIE_SESSIONS)
        config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR = tempfile.mktemp(suffix=".json"), tempfile.mktemp(suffix=".json"), tempfile.mkdtemp()
        A._AUGGIE_LIST_CACHE.clear()

        def restore():
            shutil.rmtree(config.AUGMENT_DIR, True)
            shutil.rmtree(config.TASKS_DIR, True)
            (config.AUGMENT_DIR, config.AUGGIE_SESSIONS, config.TITLES_FILE, config.NOTES_FILE, config.TASKS_DIR) = snap
            A._AUGGIE_LIST_CACHE.clear()
        self.addCleanup(restore)
        with open(os.path.join(config.AUGGIE_SESSIONS, "c1.json"), "w") as fh:
            _json.dump({"sessionId": "c1", "modified": "2026-06-27T05:48:03Z", "chatHistory": []}, fh)
        cost = A.parse_auggie("c1")["cost"]
        self.assertIsNone(cost["total_usd"])
        drv = ('var STAT_CHIP_MISSING="--"; function esc(s){return String(s==null?"":s);} function fmtNum(n){return String(n);} function qs(){return null;}\n'
               + "\n".join(_extract_function(self.bundle, n) for n in ("_usd", "_ntok", "costChipText", "statChip", "statChipsHtml")) +
               '\nconsole.log("===Z==="); console.log(JSON.stringify(statChipsHtml({cost:%s,counts:{},files:[],commands:[],tokens:{in:1,out:2},meta:{}})));' % _json.dumps(cost))
        rc, out, err = _run_node(drv)
        self.assertEqual(rc, 0, err)
        self.assertNotIn('data-act="cost"', _extract_after_marker(out, "===Z==="))

    def test_phone_css_keeps_only_cost_chip(self):
        with open(__file__.rsplit("/", 2)[0] + "/aitracker/web/ext_cr_detail.css", encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn(".cr .crd-statchips > .crd-statchip:not(.crd-statchip-cost) { display: none; }", css)
        self.assertIsNone(re.search(r"\.cr \.crd-statchips \{ display: none; \}", css))
        self.assertRegex(css, r"\.cr \.crd-statchip-cost \{[^}]*min-height: 44px")

    def test_config_dialog_has_header_line_row(self):
        self.assertIn("serverRow('Header line', 'HEADER_LINE'", self.bundle)
        self.assertIn("['summary', 'Job summary'], ['narration', 'Narration']", self.bundle)

    def test_no_host_gating(self):
        for fn in ("paintGoalLine", "costModalMd", "paintHeadline"):
            self.assertNotIn("location.hostname", _extract_function(self.bundle, fn))


CLASSIC_DRIVER = r"""
const esc=s=>(s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function md(s){ return esc(s); }
var els = {};
function $(id){ return els[id] || (els[id] = { style: {}, innerHTML: "" }); }
%(fn)s
var OUT = {};
paintHeadline({ headline: { text: "Waiting on a pick", label: "Needs input", band: "blocked" } });
OUT.on = [$("ov_hlrow").style.display, $("ov_hl").innerHTML];
paintHeadline({ headline: { text: "", label: null } });
OUT.off = [$("ov_hlrow").style.display, $("ov_hl").innerHTML];
paintHeadline({});
OUT.none = $("ov_hlrow").style.display;
console.log("===CL_JSON_START===");
console.log(JSON.stringify(OUT));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class ClassicHeadlineTests(unittest.TestCase):
    def test_classic_overview_renders_headline(self):
        b = _bundle()
        rc, out, err = _run_node(CLASSIC_DRIVER % {"fn": _extract_function(b, "paintHeadline")})
        self.assertEqual(rc, 0, err)
        o = _extract_after_marker(out, "===CL_JSON_START===")
        self.assertEqual(o["on"][0], "")
        self.assertEqual(o["on"][1], '<span class="hlband hl-blocked">Needs input</span> Waiting on a pick')
        self.assertEqual(o["off"][0], "none")
        self.assertEqual(o["none"], "none")
        self.assertIn('id=ov_hlrow style=display:none', _read_page())                 # the markup the painter targets exists
        self.assertIn("paintHeadline(d);", b)


if __name__ == "__main__":
    unittest.main()
