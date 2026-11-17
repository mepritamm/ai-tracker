"""C11: a drafted reply in narration ("**Draft reply for X** (not posted):" + a `>` quote) always
gets the same Copy button a code fence has, copying clean paste-ready text. Runs the real app.js
(mdBlock / copyCode / looksLikeBlockMd) under node."""
import json
import unittest

from tests.test_classic_markdown_and_links import (
    _APP_JS_STUB_PREAMBLE, _HAS_NODE, _extract_after_marker, _read_app_js, _run_node)
from tests.test_cr_detail_agents_pill_and_markdown import _extract_function

PASTE = ("**Prompt to paste into a fresh session:**\n\n> Continue the X work.\n> - step one\n> - step two")
LOOK_CASES = [PASTE, "## h", "- a\n- b", "1. a\n2. b", "a | b\n|---|---|", "x\n```\ny\n```", "> one line",
              "plain prose", "done - that's it", "- just one", "#1 priority", "a | b no sep", "", None]
LOOK_EXPECT = [True, True, True, True, True, True, True, False, False, False, False, False, False, False]

BHARADWAJ = ("**Draft reply for Bharadwaj** (not posted):\n\n> No direct ViDA impact. The change touches "
             "`dw-vida-ai` only.\n> Happy to pair on it.")

DRIVER = r"""
var OUT = {};
var BHARADWAJ = %(bharadwaj)s;
OUT["bharadwaj"] = mdBlock(BHARADWAJ);
OUT["heading"] = mdBlock("## 3. Slack message draft (for review — not posted)\n\n> *AIO-4183* :mag: looks good\n> second line");
OUT["neg_list"] = mdBlock("**Draft plan:**\n1. one\n2. two");
OUT["neg_prose"] = mdBlock("**P2 is green — the PR stays draft.**\n\nSome words.\n\n> a quoted prompt");
OUT["neg_mermaid"] = mdBlock("## 4. What the saved draft task looked like\n```mermaid\nflowchart LR\n A-->B\n```");
OUT["plain_quote"] = mdBlock("> just a quote\n> two lines");
OUT["fence_alone"] = mdBlock("```\ncode\n```");
OUT["both"] = mdBlock(BHARADWAJ + "\n\n```\ncode\n```");
OUT["fence_in_draft"] = mdBlock("**Draft reply**\n> text\n> ```\n> code\n> ```");
OUT["paste_prompt"] = mdBlock(%(paste)s);
OUT["looks"] = %(cases)s.map(function (c) { return looksLikeBlockMd(c); });
OUT["ol_restart"] = mdBlock("1. a\n   - x\n2. b");
OUT["ol_plain"] = mdBlock("1. a\n2. b");
OUT["br_plain"] = mdBlock("a\nb");
OUT["br_bold"] = mdBlock("**x\ny**");
OUT["br_file"] = mdBlock("a\nb", false, true);
OUT["li_indent"] = mdBlock("- a\n  - b\n- c");
OUT["xss_quote"] = mdBlock("> </textarea><img src=x onerror=alert(1)>");
OUT["quote_hi"] = mdBlock("> hi");
OUT["nested_plain"] = mdBlock("> outer\n> > inner");
OUT["repl_quote"] = mdBlock(">>> import foo\n>>> foo.bar()");
var ctx = { markdown: function (t) { return { innerHTML: md(t || "") }; } };
%(mdhtml)s
OUT["route_list"] = mdHtml(ctx, "Done:\n- one\n- two");
OUT["route_paste"] = mdHtml(ctx, %(paste)s);
OUT["route_single"] = mdHtml(ctx, "- that's it");
OUT["nested_md"] = mdBlock("> **Draft x**\n> > inner");
OUT["multi_para_noblank"] = mdBlock("**Draft reply:**\n\n> Hi team,\n\n> Second para.");
OUT["quote_then_prose"] = mdBlock("**Draft reply:**\n\n> Hi team,\n\nplain prose after");
OUT["plain_split_quotes"] = mdBlock("> one\n\n> two");

// copyCode under stubs: a fake button whose parent holds a .cpsrc textarea
function fakeBtn(srcValue, codeText) {
  var btn = { classList: { add() {}, remove() {} }, innerHTML: "x" };
  btn.parentNode = { querySelector(sel) {
    if (sel === ".cpsrc") return srcValue == null ? null : { value: srcValue, tagName: "TEXTAREA", select() {}, hidden: true };
    if (sel === "code") return codeText == null ? null : { innerText: codeText, textContent: codeText };
    return null;
  } };
  return btn;
}
var copied = [];
window.navigator.clipboard = { writeText: function (t) { copied.push(t); return Promise.resolve(); } };
copyCode(fakeBtn("No direct ViDA impact.\nHappy to pair.", "ignored"));
copyCode(fakeBtn(null, "plain code"));
OUT["copied_clipboard"] = copied.slice();
// non-secure context: no navigator.clipboard -> execCommand("copy") on a FRESH, non-readonly off-screen
// textarea (iOS cannot select() a readonly one); "Copied" only when execCommand returns true.
window.navigator.clipboard = undefined;
var made = [], execLog = [], execRet = true;
document.createElement = function (tag) {
  var t = { tagName: tag.toUpperCase(), value: "", readOnly: false, style: {}, setAttribute: function (k, v) { if (k === "readonly") this.readOnly = true; },
            select: function () { execLog.push("select"); }, setSelectionRange: function () {} };
  made.push(t); return t;
};
document.body.appendChild = function (c) { execLog.push("append"); return c; };
document.body.removeChild = function (c) { execLog.push("remove"); return c; };
document.execCommand = function (c) { execLog.push(c); return execRet; };
var ta = { value: "draft text", tagName: "TEXTAREA", hidden: true, readOnly: true, select() { execLog.push("SRC-select"); } };
function mkBtn() { return { classList: { add() {}, remove() {} }, innerHTML: "x", parentNode: { querySelector(sel) { return sel === ".cpsrc" ? ta : null; } } }; }
var b2 = mkBtn(); copyCode(b2);
OUT["fallback"] = execLog.slice(); OUT["fallback_value"] = made[0].value; OUT["fallback_readonly"] = made[0].readOnly;
OUT["fallback_ok_html"] = b2.innerHTML; OUT["fallback_src_hidden"] = ta.hidden;
execRet = false; var b3 = mkBtn(); copyCode(b3);
OUT["fallback_fail_html"] = b3.innerHTML;
console.log("===DRAFT_JSON_START===");
console.log(JSON.stringify(OUT));
""" % {"bharadwaj": json.dumps(BHARADWAJ), "paste": json.dumps(PASTE), "cases": json.dumps(LOOK_CASES),
       "mdhtml": _extract_function(__import__("aitracker.page", fromlist=["x"]).build_page(), "mdHtml")}


@unittest.skipUnless(_HAS_NODE, "node not available")
class DraftCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rc, out, err = _run_node(_APP_JS_STUB_PREAMBLE + _read_app_js() + DRIVER)
        if rc != 0:
            raise AssertionError("draft harness failed (%d)\n%s\n%s" % (rc, out, err))
        cls.OUT = _extract_after_marker(out, "===DRAFT_JSON_START===")

    def n(self, key, needle):
        return self.OUT[key].count(needle)

    def test_bharadwaj_shape_gets_one_copy_button(self):
        o = self.OUT["bharadwaj"]
        self.assertEqual(self.n("bharadwaj", 'class="cblock dq"'), 1)
        self.assertEqual(self.n("bharadwaj", "codecopy"), 1)
        self.assertIn("<textarea class=cpsrc hidden readonly>No direct ViDA impact. The change touches "
                      "`dw-vida-ai` only.\nHappy to pair on it.</textarea>", o)   # `> ` stripped, markdown kept
        self.assertIn("<p class=mdp><strong>Draft reply for Bharadwaj</strong> (not posted):</p>", o)   # label above
        self.assertNotIn("&gt;", o)                                                # no more inline "> "
        self.assertIn("<blockquote class=mdq>", o)

    def test_draft_label_titles_the_button_draft(self):
        self.assertIn('title="Copy this draft"', self.OUT["bharadwaj"])           # I4
        self.assertIn('title="Copy this quote"', self.OUT["quote_hi"])

    def test_file_preview_keeps_soft_wrap_join(self):
        self.assertEqual(self.OUT["br_file"], "<p class=mdp>a b</p>")             # I1

    def test_indented_list_items_are_indented(self):                              # I2
        o = self.OUT["li_indent"]
        self.assertIn('<li style="margin-left:1.2em">b</li>', o)
        self.assertIn("<li>a</li>", o)
        self.assertEqual(o.count("<ul"), 1)

    def test_quote_source_textarea_is_escaped(self):                              # I3
        o = self.OUT["xss_quote"]
        self.assertIn("&lt;/textarea&gt;&lt;img", o)
        self.assertNotIn("<img", o)
        self.assertEqual(o.count("</textarea>"), 1)

    def test_heading_label_then_blank_then_quote(self):
        o = self.OUT["heading"]
        self.assertEqual(self.n("heading", "cblock dq"), 1)
        self.assertIn("<textarea class=cpsrc hidden readonly>*AIO-4183* :mag: looks good\nsecond line</textarea>", o)

    def test_negatives_no_button(self):
        for k in ("neg_list", "neg_mermaid"):
            self.assertEqual(self.n(k, "cblock dq"), 0, k)
        self.assertEqual(self.n("neg_list", "codecopy"), 0)
        self.assertEqual(self.n("neg_prose", "<blockquote class=mdq>"), 1)   # the quote still renders as a quote
        self.assertEqual(self.n("neg_prose", "cblock dq"), 1)                # ...and now carries Copy

    def test_plain_blockquote_gets_copy_button(self):
        o = self.OUT["plain_quote"]
        self.assertEqual((o.count("<blockquote class=mdq>"), o.count("codecopy"), o.count("&gt;")), (1, 1, 0))
        self.assertIn("<textarea class=cpsrc hidden readonly>just a quote\ntwo lines</textarea>", o)
        self.assertIn('title="Copy this quote"', o)

    def test_paste_prompt_quote_gets_copy(self):
        o = self.OUT["paste_prompt"]
        self.assertEqual(self.n("paste_prompt", 'class="cblock dq"'), 1)
        self.assertIn('title="Copy this quote"', o)
        self.assertIn("<textarea class=cpsrc hidden readonly>Continue the X work.\n- step one\n- step two</textarea>", o)
        self.assertNotIn("&gt;", o)

    def test_looks_like_block_md_detector(self):
        self.assertEqual(self.OUT["looks"], LOOK_EXPECT)

    def test_cr_gate_routes_detected_text_to_mdblock(self):
        self.assertIn("<ul class=mdul>", self.OUT["route_list"])
        self.assertIn("cblock dq", self.OUT["route_paste"])
        self.assertNotIn("<ul", self.OUT["route_single"])
        self.assertNotIn("<p class=mdp>", self.OUT["route_single"])

    def test_ordered_list_keeps_source_number_after_break(self):
        self.assertIn("<ol class=mdul start=2>", self.OUT["ol_restart"])
        self.assertNotIn("start=", self.OUT["ol_plain"])

    def test_single_newline_in_paragraph_is_br(self):
        self.assertEqual(self.OUT["br_plain"], "<p class=mdp>a<br>b</p>")
        self.assertIn("<strong>x<br>y</strong>", self.OUT["br_bold"])

    def test_nested_plain_quote_has_one_button(self):
        self.assertEqual(self.n("nested_plain", "cblock dq"), 1)
        self.assertEqual(self.n("repl_quote", "cblock dq"), 1)

    def test_code_fence_keeps_single_button_inside_draft_doc(self):
        self.assertEqual(self.n("both", "codecopy"), 2)      # 1 draft + 1 fence
        self.assertEqual(self.n("fence_alone", "codecopy"), 1)

    def test_fence_inside_draft_quote(self):
        o = self.OUT["fence_in_draft"]
        self.assertEqual(o.count("codecopy"), 2)
        # outer draft source keeps the fence lines; the inner fence's code is its own block inside .mdq
        self.assertIn("<textarea class=cpsrc hidden readonly>text\n```\ncode\n```</textarea>", o)
        self.assertGreater(o.index('<div class=cblock><button'), o.index("<blockquote class=mdq>"))
        self.assertLess(o.index('<div class=cblock><button'), o.index("</blockquote>"))

    def test_copycode_uses_cpsrc_and_textarea_fallback(self):
        self.assertEqual(self.OUT["copied_clipboard"], ["No direct ViDA impact.\nHappy to pair.", "plain code"])
        # no clipboard API: a fresh NON-readonly textarea is selected + copied, then removed (CF5)
        self.assertEqual(self.OUT["fallback"], ["append", "select", "copy", "remove"])
        self.assertEqual(self.OUT["fallback_value"], "draft text")
        self.assertFalse(self.OUT["fallback_readonly"])
        self.assertTrue(self.OUT["fallback_src_hidden"])           # the hidden readonly source is never touched
        self.assertIn("Copied", self.OUT["fallback_ok_html"])
        self.assertNotIn("Copied", self.OUT["fallback_fail_html"])  # execCommand returned false -> no false success


    def test_multi_paragraph_draft_copies_every_paragraph(self):
        o = self.OUT["multi_para_noblank"]
        self.assertEqual(self.n("multi_para_noblank", 'class="cblock dq"'), 1)
        self.assertIn("<textarea class=cpsrc hidden readonly>Hi team,\n\nSecond para.</textarea>", o)
        # a draft quote followed by prose, and an unlabelled split quote, keep their old shape
        self.assertEqual(self.n("quote_then_prose", 'class="cblock dq"'), 1)
        self.assertIn("<textarea class=cpsrc hidden readonly>Hi team,</textarea>", self.OUT["quote_then_prose"])
        self.assertEqual(self.n("plain_split_quotes", "<blockquote class=mdq>"), 2)
        self.assertEqual(self.n("plain_split_quotes", "cblock dq"), 2)   # still not merged: two quotes, two buttons

    def test_nested_draft_keeps_its_button(self):
        self.assertEqual(self.n("nested_md", "cblock dq"), 2)


class WiringTests(unittest.TestCase):
    def test_cr_mdhtml_routes_draft_text_to_mdblock_and_page_carries_it(self):
        import os
        from aitracker.page import build_page
        page = build_page()
        self.assertIn('typeof looksLikeBlockMd === "function" && looksLikeBlockMd(text)', page)
        self.assertIn("function looksLikeBlockMd", page)
        self.assertNotIn("location.hostname", page.split("function looksLikeBlockMd")[1][:400])
        # R3: the classic Agent modal routes an agent's narration through the same detector
        self.assertIn("looksLikeBlockMd(d.narration)?mdBlock(d.narration):md(d.narration)", page)

    def test_file_previews_pass_file_flag_and_agent_modal_upgrades_mermaid(self):
        from aitracker.page import build_page
        page = build_page()
        self.assertIn("mdBlock(content,false,true)", page)                        # I1 renderMdView
        self.assertIn("join('\\n'), false, true)", page)                           # I1 CR rendered diff
        a = page.split("function openAgent", 1)[1].split("function closeMsg", 1)[0]
        self.assertIn('upgradeMermaidIn($("msgbody"))', a)                        # I5

    def test_copy_click_does_not_open_the_timeline_entry(self):
        from aitracker.page import build_page
        body = build_page().split('node.addEventListener("click", function (ev) {', 1)[1][:600]
        self.assertIn('closest(".codecopy")', body)
        self.assertLess(body.index('closest(".codecopy")'), body.index('closest("[data-act]")'))


if __name__ == "__main__":
    unittest.main()
