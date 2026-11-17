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


FLOAT_PRE = 'var H = {}; document.addEventListener = function (t, f, c) { H[t + (c ? "!" : "")] = f; };\n'
FLOAT_DRIVER = r"""
var OUT = {};
var TIMERS = [];
globalThis.setTimeout = function (f, ms) { TIMERS.push({ f: f, ms: ms }); return TIMERS.length; };
globalThis.clearTimeout = function () {};
function fk(tag, o, parent) {
  o = o || {};
  var n = { tagName: tag.toUpperCase(), className: o.cls || "", textContent: o.text || "", parent: parent || null,
            _href: o.href, _rects: o.rects || [{ top: 50, right: 100, bottom: 60 }], isConnected: o.connected !== false };
  n.getAttribute = function (k) { return k === "href" ? n._href : null; };
  n.getClientRects = function () { return n._rects; };
  n.contains = function (x) { for (; x; x = x.parent) if (x === n) return true; return false; };
  n.nextElementSibling = o.next || null;
  n.closest = function (sel) {
    for (var x = n; x; x = x.parent) {
      if (sel === ".lnkcopy" && /\blnkcopy\b/.test(x.className)) return x;
      if (sel === "code" && x.tagName === "CODE") return x;
      if (sel === 'a[href^="http"]' && x.tagName === "A" && /^http/.test(x._href || "")) return x;
      if (sel.indexOf(".shline") === 0 && (x.tagName === "PRE" || /\b(shline|cr-rail-hl|cr-tile-line--hl)\b/.test(x.className))) return x;
    }
    return null;
  };
  return n;
}
var row = fk("div");
var code = fk("code", { text: "rm *.pyc" }, row);
var link = fk("a", { href: "https://x.test/a?b=1&c=2", text: "label" }, row);
var cmd = fk("code", { text: "curl https://x.test/u" }, row), cmdA = fk("a", { href: "https://x.test/u", text: "https://x.test/u" }, cmd);
var lcode = fk("a", { href: "https://x.test/l", text: "x" }, row), lcodeK = fk("code", { text: "x" }, lcode);
var hl = fk("div", { cls: "shline" });
function strip(r) { return r && { text: r.text, kind: r.kind, same: r.el }; }
OUT["code"] = strip(copyTargetOf(code)); OUT["code_same"] = copyTargetOf(code).el === code;
OUT["link"] = strip(copyTargetOf(link)); OUT["link_text"] = copyTargetOf(link).text;
OUT["cmd"] = strip(copyTargetOf(cmdA)).text; OUT["cmd_kind"] = copyTargetOf(cmdA).kind;
OUT["linkcode"] = strip(copyTargetOf(lcodeK)).kind;
OUT["classed"] = copyTargetOf(fk("code", { text: "z", cls: "mono" }, row));
OUT["headline"] = copyTargetOf(fk("code", { text: "z" }, hl));
OUT["pre"] = copyTargetOf(fk("code", { text: "z" }, fk("pre")));
OUT["nonhttp"] = copyTargetOf(fk("a", { href: "javascript:alert(1)" }, row));
OUT["none"] = copyTargetOf(null) === null && copyTargetOf(row) === null;
OUT["empty"] = copyTargetOf(fk("code", { text: "" }, row));
OUT["chip_anchor"] = copyTargetOf(fk("a", { href: "https://claude.ai/artifact/q", next: { className: "codecopy lnkcopy" } }, row));
OUT["on_chip"] = copyTargetOf(fk("button", { cls: "codecopy lnkcopy" }, fk("code", { text: "u" }, row)));

var copied = [];
window.navigator.clipboard = { writeText: function (t) { copied.push(t); return Promise.resolve(); } };
// _flShow: positions the single body button beside the (last) rect, once
document.body.appendChild = function (c) { return c; };
var shown = fk("code", { text: "rm *.pyc", rects: [{ top: 10, right: 30, bottom: 20 }, { top: 40, right: 90, bottom: 50 }] }, row);
globalThis.innerWidth = 1000;
_flShow({ el: shown, text: "rm *.pyc", kind: "code" });
OUT["btn_made"] = !!_flBtn; OUT["btn_style"] = [_flBtn.style.left, _flBtn.style.top, _flBtn.hidden, _flText];
_flBtn = null; _flEl = null;
_flShow({ el: fk("code", { text: "d", connected: false }, row), text: "d", kind: "code" });
OUT["detached_no_btn"] = _flBtn === null;
_flShow({ el: fk("code", { text: "e", rects: [] }, row), text: "e", kind: "code" });
OUT["norect_no_btn"] = _flBtn === null;
// I4: the button's onclick copies the CURRENT target; a scroll hides it
_flBtn = null; _flEl = null;
_flShow({ el: fk("code", { text: "A" }, row), text: "A", kind: "code" });
_flShow({ el: fk("code", { text: "B" }, row), text: "B", kind: "code" });
_flBtn.onclick(); OUT["click_copies_latest"] = copied[copied.length - 1];
_flBtn.hidden = false; H["scroll!"](); OUT["scroll_hidden"] = _flBtn.hidden;
_flBtn = null; _flEl = null;
_flShow({ el: shown, text: "A", kind: "code" });
_flBtn.classList = { contains: function (c) { return c === "ok"; }, add() {}, remove() {} };
_flShow({ el: fk("code", { text: "B" }, row), text: "B", kind: "code" });
OUT["ok_held_text"] = _flText;
_flBtn.contains = function (x) { return x === "inside"; };
// _flOver: touch -> nothing; buttons -> no show timer; mouse -> one 300 ms timer
TIMERS.length = 0; H["pointerover"]({ pointerType: "touch", target: code, buttons: 0 }); OUT["touch_timers"] = TIMERS.length;
TIMERS.length = 0; H["pointerover"]({ pointerType: "mouse", target: code, buttons: 1 }); OUT["drag_timers"] = TIMERS.map(function (t) { return t.ms; });
TIMERS.length = 0; H["pointerover"]({ pointerType: "mouse", target: code, buttons: 0 }); OUT["mouse_timers"] = TIMERS.map(function (t) { return t.ms; });
// _flAway: a press outside the button hides it
_flBtn.hidden = false; _flBtn.contains = function (x) { return x === "inside"; };
H["pointerdown!"]({ target: "outside" }); OUT["away_hidden"] = _flBtn.hidden;
_flBtn.hidden = false; H["pointerdown!"]({ target: "inside" }); OUT["inside_kept"] = _flBtn.hidden;
// copyText: clipboard path, then fallback only reports success when execCommand does
var done = []; copyText("hello", function () { done.push(1); });
copyText("", function () { done.push(2); });
var made = [], execRet = false;
document.createElement = function (tag) { var t = { tagName: tag.toUpperCase(), value: "", style: {}, setAttribute() {}, select() {}, setSelectionRange() {} }; made.push(t); return t; };
document.body.removeChild = function (c) { return c; };
document.execCommand = function () { return execRet; };
window.navigator.clipboard = undefined;
copyText("fb1", function () { done.push("fb1"); });
execRet = true;
copyText("fb2", function () { done.push("fb2"); });
OUT["fallback_value"] = made.map(function (t) { return t.value; });
// artifact chip click: copies the preceding anchor's href at click time, stops the row's handler
window.navigator.clipboard = { writeText: function (t) { copied.push(t); return Promise.resolve(); } };
var anchor = fk("a", { href: "https://claude.ai/artifact/abc?x=1&y=2" }, row);
var chipAdds = [];
var chip = { previousElementSibling: anchor, textContent: "Copy", classList: { add(c) { chipAdds.push(c); }, remove() {} } };
chip.closest = function (sel) { return sel === ".lnkcopy" ? chip : null; };
var ev = { target: chip, stopped: 0, prevented: 0, stopPropagation: function () { this.stopped++; }, preventDefault: function () { this.prevented++; } };
H["click!"](ev);
OUT["chip_evt"] = [ev.stopped, ev.prevented];
var ev2 = { target: { closest: function () { return null; } }, stopped: 0, stopPropagation: function () { this.stopped++; }, preventDefault() {} };
H["click!"](ev2); OUT["other_click_stopped"] = ev2.stopped;
OUT["copied"] = copied.slice();
OUT["chip_text"] = chip.textContent;
OUT["done"] = done;
Promise.resolve().then(function () { return null; }).then(function () {
  OUT["done_after"] = done; OUT["chip_adds"] = chipAdds;
  console.log("===FLOAT_JSON_START===");
  console.log(JSON.stringify(OUT));
});
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class FloatingCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rc, out, err = _run_node(_APP_JS_STUB_PREAMBLE + FLOAT_PRE + _read_app_js() + FLOAT_DRIVER)
        if rc != 0:
            raise AssertionError("float harness failed (%d)\n%s\n%s" % (rc, out, err))
        cls.OUT = _extract_after_marker(out, "===FLOAT_JSON_START===")

    def test_copy_target_code_and_link(self):
        o = self.OUT
        self.assertEqual((o["code"]["text"], o["code"]["kind"], o["code_same"]), ("rm *.pyc", "code", True))
        self.assertEqual((o["link"]["text"], o["link"]["kind"]), ("https://x.test/a?b=1&c=2", "link"))

    def test_link_inside_code_copies_the_whole_command(self):                      # F4
        self.assertEqual((self.OUT["cmd"], self.OUT["cmd_kind"]), ("curl https://x.test/u", "code"))
        self.assertEqual(self.OUT["linkcode"], "link")                              # [`x`](url) -> the url

    def test_skips_classed_headline_pre_nonhttp_and_empty(self):                   # F6 + exclusions
        for k in ("classed", "headline", "pre", "nonhttp", "empty", "chip_anchor", "on_chip"):
            self.assertIsNone(self.OUT[k], k)
        self.assertTrue(self.OUT["none"])

    def test_button_positioned_once_beside_last_rect(self):
        self.assertEqual(self.OUT["btn_style"], ["94px", "37px", False, "rm *.pyc"])

    def test_detached_or_rectless_target_makes_no_button(self):                    # F5
        self.assertTrue(self.OUT["detached_no_btn"])
        self.assertTrue(self.OUT["norect_no_btn"])

    def test_copied_flash_holds_the_button(self):
        self.assertEqual(self.OUT["ok_held_text"], "A")

    def test_hover_is_mouse_only_delayed_and_not_mid_drag(self):                   # F2 + F3
        self.assertEqual(self.OUT["touch_timers"], 0)
        self.assertEqual(self.OUT["drag_timers"], [250])                            # hide timer only, never a show timer
        self.assertEqual(self.OUT["mouse_timers"], [300])

    def test_press_outside_hides_press_on_button_keeps(self):                      # F3
        self.assertTrue(self.OUT["away_hidden"])
        self.assertFalse(self.OUT["inside_kept"])

    def test_copy_text_clipboard_and_honest_fallback(self):
        self.assertIn("hello", self.OUT["copied"])
        self.assertEqual(sorted(set(self.OUT["fallback_value"])), ["fb1", "fb2"])
        self.assertEqual(sorted(map(str, self.OUT["done_after"])), ["1", "fb2"])                       # fb1: execCommand false -> no "Copied"

    def test_artifact_chip_copies_href_and_swallows_the_click(self):
        self.assertEqual(self.OUT["chip_evt"], [1, 1])
        self.assertIn("https://claude.ai/artifact/abc?x=1&y=2", self.OUT["copied"])
        self.assertEqual(self.OUT["other_click_stopped"], 0)
        self.assertIn("ok", self.OUT["chip_adds"])                                   # I1: success toggles .ok (label is ::after)
        self.assertEqual(self.OUT["chip_text"], "Copy")                              # ...and never writes textContent

    def test_float_click_uses_current_target_and_scroll_hides(self):                # I4
        self.assertEqual(self.OUT["click_copies_latest"], "B")
        self.assertTrue(self.OUT["scroll_hidden"])

    def test_listeners_are_wired_in_the_page(self):
        from aitracker.page import build_page
        page = build_page()
        self.assertIn('addEventListener("pointerover",_flOver)', page)
        self.assertIn('addEventListener("pointerdown",_flAway,true)', page)
        self.assertIn('addEventListener("click",_lnkCopyClick,true)', page)
        self.assertIn(".flcopy{position:fixed", page)
        self.assertIn('.lnkcopy::after{content:"Copy"}', page)                       # I1
        self.assertIn(".pw .lnkcopy{display:none}", page)                            # I3


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
