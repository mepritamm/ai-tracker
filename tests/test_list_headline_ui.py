"""The list-row headline renderers, driven through the REAL bundle under node (never source greps):
Control Room rail rows + board tiles (ext_cr_board.js) and the classic sidebar row (app.js sessionRow).
The server owns the text/label/band/covers_needs; these only render it."""
import json
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from tests.test_cr_rail_polish import (  # noqa: E402
    _REAL_DOM_PREAMBLE, _REAL_DOM_MID, _run_node, _read_page, _extract_script_content, make_session, NOW, _HAS_NODE,
)
from tests import test_view_parity as VP  # noqa: E402

URL = "https://github.com/o/r/pull/7"


def _hl(text, **kw):
    h = {"mode": "summary", "source": "job", "text": text, "band": None, "label": None, "state": None,
         "updated": None, "covers_needs": False}
    h.update(kw)
    return h


SCEN = {
    "job_await": make_session("job_await", NOW - 5, waiting=True, needs="provide a username",
                              headline=_hl("Reviewing the patch", band="blocked", label="Needs input")),
    "nar": make_session("nar", NOW - 5, headline=_hl("**bold** <img src=x> opened " + URL, source="narration", mode="summary")),
    "work_bg": make_session("work_bg", NOW - 5, bg=2, now_line="⚙ 2 background agents",
                            headline=_hl("Running the gate", band="working", label="Working")),
    "covers": make_session("covers", NOW - 5, waiting=True, needs="pick A or B",
                           headline=_hl("pick A or B", band="blocked", label="Needs input", covers_needs=True)),
    "null_work": make_session("null_work", NOW - 5, bg=1, now_line="⚙ 1 background agent", headline=None),
    "null_await": make_session("null_await", NOW - 5, waiting=True, needs="login required", headline=None),
}

_CR_TAIL = r"""
var SCEN = %(scen)s;
function renderOne(s) {
  var root = makeReal('div'); docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: [s], now: %(now)d });
  var rows = queryAllReal(root, '.cr-rail-row');
  var rail = rows[0];
  var hl = queryAllReal(root, '.cr-rail-hl');
  var thl = queryAllReal(root, '.cr-tile-line--hl');
  var now = queryAllReal(root, '.cr-tile-line--now');
  var plain = queryAllReal(root, '.cr-tile-line').filter(function (e) { return !e._classes.has('cr-tile-line--hl') && !e._classes.has('cr-tile-line--now'); });
  return {
    railKids: rail ? rail._children.map(function (c) { return Array.from(c._classes)[0]; }) : null,
    railHl: hl.map(function (e) { return e.innerHTML; }),
    tileHl: thl.map(function (e) { return e.innerHTML; }),
    tileNow: now.map(function (e) { return allTextIn(e); }),
    tilePlain: plain.map(function (e) { return allTextIn(e); })
  };
}
var out = {};
Object.keys(SCEN).forEach(function (k) { out[k] = renderOne(SCEN[k]); });
console.log("===CRHL===");
console.log(JSON.stringify(out));
"""


def _marker(stdout, marker):
    i = stdout.find(marker)
    if i < 0:
        raise ValueError("marker missing:\n" + stdout)
    return json.loads(stdout[i + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class CrHeadlineRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = "\n".join([_REAL_DOM_PREAMBLE, _extract_script_content(_read_page()), _REAL_DOM_MID,
                        _CR_TAIL % {"scen": json.dumps(SCEN), "now": NOW}])
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("cr driver failed\n%s\n%s" % (out, err))
        cls.O = _marker(out, "===CRHL===")

    def test_rail_row_order_r1_hl_meta(self):
        kids = self.O["job_await"]["railKids"]
        self.assertEqual([k for k in kids if k in ("cr-rail-r1", "cr-rail-hl", "cr-rail-meta")],
                         ["cr-rail-r1", "cr-rail-hl", "cr-rail-meta"], kids)

    def test_rail_pill_and_text(self):
        self.assertTrue(self.O["job_await"]["railHl"][0].startswith(
            '<span class="crd-hl-band crd-hl-blocked">Needs input</span> '), self.O["job_await"]["railHl"])

    def test_narration_safe_no_anchor_url_text_kept(self):
        h = self.O["nar"]["railHl"][0]
        self.assertIn("<strong>bold</strong>", h)
        self.assertIn("&lt;img", h)
        self.assertNotIn("<img", h)
        self.assertNotIn("<a ", h)
        self.assertIn(URL, h)
        self.assertNotIn("crd-hl-band", h)

    def test_null_headline_has_no_rail_hl_and_todays_tile_lines(self):
        self.assertEqual(self.O["null_work"]["railHl"], [])
        self.assertEqual(self.O["null_work"]["tileHl"], [])
        self.assertEqual(self.O["null_work"]["tileNow"], ["⚙ 1 background agent"])
        self.assertEqual(self.O["null_await"]["tilePlain"], ["login required"])

    def test_awaiting_tile_headline_plus_question(self):
        o = self.O["job_await"]
        self.assertEqual(len(o["tileHl"]), 1)
        self.assertEqual(o["tileNow"], ["⧖ provide a username"])

    def test_covers_needs_tile_drops_question_line(self):
        o = self.O["covers"]
        self.assertEqual(len(o["tileHl"]), 1)
        self.assertEqual(o["tileNow"], [])

    def test_working_tile_headline_plus_structural_now_line(self):
        o = self.O["work_bg"]
        self.assertEqual(len(o["tileHl"]), 1)
        self.assertEqual(o["tileNow"], ["⚙ 2 background agents"])


_CLASSIC_TAIL = r"""
var out = {};
out.job = sessionRow(%(job)s, %(now)d);
out.nar = sessionRow(%(nar)s, %(now)d);
out.aug = sessionRow(%(aug)s, %(now)d);
out.none = sessionRow(%(none)s, %(now)d);
paintHeadline({ headline: %(nar_hl)s });
out.header = document.getElementById("ov_hl").innerHTML;
console.log("===CLHL===");
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class ClassicHeadlineRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nar_hl = _hl("see " + URL, source="narration")
        tail = _CLASSIC_TAIL % {
            "now": NOW, "nar_hl": json.dumps(nar_hl),
            "job": json.dumps(VP.make_session("cj", NOW - 5, headline=_hl("Needs a pick", band="blocked", label="Needs input"))),
            "nar": json.dumps(VP.make_session("cn", NOW - 5, headline=nar_hl)),
            "aug": json.dumps(VP.make_session("auggie:ca", NOW - 5, source="auggie", headline=_hl("auggie says", source="narration"))),
            "none": json.dumps(VP.make_session("cz", NOW - 5, headline=None)),
        }
        rc, out, err = _run_node("\n".join([VP._PREAMBLE, _extract_script_content(_read_page()), VP._MID, tail]))
        if rc != 0:
            raise AssertionError("classic driver failed\n%s\n%s" % (out, err))
        cls.O = _marker(out, "===CLHL===")

    def test_markup_order_srow1_shline_smeta(self):
        h = self.O["job"]
        a, b, c = h.find("class=srow1"), h.find("<div class=shline>"), h.find("<div class=smeta>")
        self.assertTrue(0 <= a < b < c, (a, b, c))
        self.assertIn('<div class=shline><span class="hlband hl-blocked">Needs input</span> Needs a pick', h)

    def test_row_url_not_linked_header_url_linked(self):
        shline = re.search(r"<div class=shline>(.*?)</div>", self.O["nar"], re.S).group(1)
        self.assertNotIn("<a ", shline)
        self.assertIn(URL, shline)
        self.assertIn("<a ", self.O["header"])          # the header keeps its real links

    def test_auggie_row_has_line_no_pill_null_has_none(self):
        shline = re.search(r"<div class=shline>(.*?)</div>", self.O["aug"], re.S).group(1)
        self.assertEqual(shline, "auggie says")
        self.assertNotIn("shline", self.O["none"])


def _css():
    m = re.search(r"<style>(.*?)</style>", _read_page(), re.S)
    return m.group(1)


class HeadlineCssTests(unittest.TestCase):
    def test_one_line_ellipsis_rules(self):
        css = _css()
        for sel in (".cr-rail-hl", ".shline"):
            m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css)
            self.assertIsNotNone(m, sel)
            self.assertRegex(m.group(1), r"white-space:\s*nowrap")
            self.assertRegex(m.group(1), r"text-overflow:\s*ellipsis")

    def test_no_media_rule_hides_the_lines(self):
        css = _css()
        for m in re.finditer(r"@media[^{]*\{", css):
            depth, i = 1, m.end()
            while depth and i < len(css):
                depth += (css[i] == "{") - (css[i] == "}")
                i += 1
            self.assertNotRegex(css[m.end():i], r"(cr-rail-hl|shline|cr-tile-line--hl)[^{]*\{[^}]*display:\s*none")

    def test_pill_classes_reused_under_cr_root(self):
        page = _read_page()
        self.assertRegex(_css(), r"\.cr \.crd-hl-band\b")
        self.assertRegex(page, r'id="?nextRoot"?[^>]*class="[^"]*\bcr\b|class="[^"]*\bcr\b[^"]*"[^>]*id="?nextRoot')

    def test_no_host_gating(self):
        self.assertNotRegex(_read_page(), r"location\.hostname[^;\n]*(headlineEl|hlHtml)")


if __name__ == "__main__":
    unittest.main()
