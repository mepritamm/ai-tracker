"""Regression tests for two control-room detail-view fixes (ext_cr_detail.js /
ext_cr_detail.css):

TASK 1 -- the "N AGENTS RUNNING" header pill was a display-only `<span>`, dead
to click and keyboard alike, no matter how many background agents were
running. Fixed by making it a real `<button type="button" data-act=
"focus-agents">` (renderHeader sets textContent/title/aria-label/hidden on
every render pass, same convention as paintPinButton()/the flag badge next to
it), wired through the SAME delegated click handler every other header
control here already uses. Clicking it expands + scrolls to the EXISTING
"Agents & shells" evidence panel (EVIDENCE_PANELS, renderAgentsPanel()) rather
than opening a second surface -- that panel is already repainted on every
render() pass off ui.lastSession, so it stays live across polls for free,
unlike the dialog bug just fixed elsewhere in this app (a payload captured
once at open time, clobbered by the next poll -- ext_cr_dialogs.js:1774).
Deliberately NOT gated on location.hostname/isLocalhost -- the one control in
this file that IS host-gated ("external") stays that way, but the agents pill
must work from a phone/tablet over a tunnel.

TASK 2 -- markdown rendering. mdHtml(ctx, text) (this file, ~line 192) was
already the shared, escape-first-then-transform renderer used by narration/
prompts/notes -- but three session-authored-text consumers were still on
plain esc(), the exact same-data-two-renderings asymmetry the classic
sidebar's own ov.goal/ov.now/ov.sofar `md()` calls (app.js:1439-1441) already
exposed for the Summary panel:
  - renderSummary()'s Goal/Now/So-far fields
  - renderAgentsPanel()'s agent task title (a.task)
  - entryHtml()'s "ask" (decision) timeline entry -- the question and its
    options
Shell commands (c.cmd) and file paths (e.target) are LEFT ALONE -- `*`, `_`,
backticks, `[`/`]` are shell metacharacters and path syntax there, and running
them through markdown would corrupt what they actually say.

Idiom: same "brace-match the real function text out of the assembled page
bundle, run it under Node with honest stubs" technique as
tests/test_cr_rail_toggle.py / tests/test_cr_manage_terminals_poll.py -- never
a hand-retyped paraphrase of the shipped source. Static routing assertions
(which fields call mdHtml() vs esc()) are plain substring checks against the
real extracted function bodies, same as tests/test_cr_rail_toggle.py's
TestRailPrefConfigRowAndVocabulary. The XSS invariant is proven by actually
EXECUTING mdHtml() under Node against hostile input -- not just checking the
source calls esc().
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the
    real bundle. Raises loudly (never returns a guess) if the shape has
    moved, so this test fails honestly instead of silently exercising stale
    text. Same helper as tests/test_cr_rail_toggle.py."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in the real bundle" % name)
    brace_start = source.index('{', m.start())
    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[m.start():i + 1]
    raise AssertionError("unterminated function %s() (brace mismatch)" % name)


def _extract_braced_block(source, marker):
    """Brace-matches a `MARKER { ... }` block that starts at MARKER's own
    literal text (e.g. a `case "x": {` label) rather than a function
    declaration. Same fail-loudly contract as _extract_function()."""
    idx = source.find(marker)
    if idx < 0:
        raise AssertionError("%r not found in the real bundle" % (marker,))
    brace_start = source.index('{', idx)
    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[idx:i + 1]
    raise AssertionError("unterminated block for marker %r (brace mismatch)" % (marker,))


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout):
    marker = "===MD_XSS_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    import json
    return json.loads(stdout[idx + len(marker):].strip())


# ---------------------------------------------------------------------------
# TASK 1 -- the agents pill: real button, live target, no host gate.
# ---------------------------------------------------------------------------

class TestAgentsPillIsARealButton(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = _read_page()
        cls.bundle = _extract_script_content(cls.html)

    def test_pill_markup_is_a_real_button_not_a_span(self):
        """THE BUG, precisely: this used to be `<span class="crd-pill
        crd-pill-agents" hidden></span>` -- a span has no keyboard activation
        and nothing to click. Must now be a real <button type="button"> with
        a data-act the delegated click handler can route on."""
        self.assertIn(
            '<button type="button" class="crd-pill crd-pill-agents" data-act="focus-agents" hidden></button>',
            self.bundle,
        )
        self.assertNotIn(
            '<span class="crd-pill crd-pill-agents" hidden></span>', self.bundle,
            "the old display-only span is still present alongside (or instead of) the button",
        )

    def test_render_header_gives_it_a_title_and_aria_label(self):
        render_header_src = _extract_function(self.bundle, "renderHeader")
        self.assertIn("crd-pill-agents", render_header_src)
        self.assertIn('agentsPill.setAttribute("aria-label"', render_header_src)
        self.assertIn("agentsPill.title =", render_header_src)
        # And it degrades to hidden -- inert, not just invisible -- at zero.
        self.assertIn("agentsPill.hidden = true;", render_header_src)

    def test_agents_pill_is_not_gated_on_localhost(self):
        """Constraint 6: this control must work from a phone/tablet over a
        tunnel. The ONE control in this header that IS host-gated is
        `[data-act="external"]` (`isLocalhost`, `location.hostname`) -- the
        block that sets up the agents pill (`var agentsRunning` ... its
        `else { agentsPill.hidden = true; }`) must not mention either."""
        render_header_src = _extract_function(self.bundle, "renderHeader")
        m = re.search(
            r'var agentsRunning[\s\S]*?agentsPill\.hidden = true;\s*\n\s*\}',
            render_header_src,
        )
        self.assertIsNotNone(m, "could not isolate the agents-pill block inside renderHeader()")
        block = m.group(0)
        self.assertNotIn("isLocalhost", block)
        self.assertNotIn("location.hostname", block)
        # Sanity: the isolated block really is the agents-pill logic, not an
        # accidentally-matched unrelated span (guards against the regex above
        # silently matching nothing meaningful after a future refactor).
        self.assertIn("crd-pill-agents", block)
        self.assertIn("agentsRunning", block)

    def test_click_handler_expands_and_scrolls_to_the_live_agents_panel(self):
        """Clicking must reach the SAME `ui.panels.agents` wrap
        renderAgentsPanel() repaints on every render() pass (see
        test_agents_panel_is_repainted_on_every_render_pass below) -- not a
        second, poll-blind copy of the agent list."""
        block = _extract_braced_block(self.bundle, 'case "focus-agents": {')
        self.assertIn("ui.panels.agents", block)
        self.assertIn("setPanelCollapsed(ctx, agentsWrap, sid, false)", block)
        self.assertIn("scrollIntoView", block)

    def test_agents_panel_is_repainted_on_every_render_pass(self):
        """THE LIVE-ACROSS-POLLS GUARANTEE: renderAgentsPanel(ui.panels.agents,
        ...) must be called from the main per-poll render path (not only once
        at mount, and not only from a dialog-open handler) -- otherwise
        expanding the panel from the pill would show a snapshot frozen at
        click time, the exact class of bug just fixed for a dialog elsewhere
        in this app (a payload captured once at open time and clobbered by
        the next poll)."""
        self.assertRegex(
            self.bundle,
            r'renderAgentsPanel\(ui\.panels\.agents,\s*ctx,\s*ui,\s*session\)',
            "renderAgentsPanel() is not called with the live per-render `session` "
            "argument from the main render pass",
        )


# ---------------------------------------------------------------------------
# TASK 2a -- static routing: summary / agents-task / ask-question go through
# mdHtml(); commands and file paths stay on esc().
# ---------------------------------------------------------------------------

class TestMarkdownRoutingBySource(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())
        cls.render_summary_src = _extract_function(cls.bundle, "renderSummary")
        cls.render_agents_panel_src = _extract_function(cls.bundle, "renderAgentsPanel")
        cls.entry_html_src = _extract_function(cls.bundle, "entryHtml")

    def test_summary_goal_now_sofar_use_mdhtml(self):
        src = self.render_summary_src
        for field in ("ov.goal", "ov.now", "ov.sofar"):
            self.assertIn(
                "mdHtml(ctx, %s" % field, src,
                "renderSummary() no longer runs %s through mdHtml()" % field,
            )
            self.assertNotIn(
                "esc(%s" % field, src,
                "renderSummary() still escapes %s directly instead of via mdHtml()" % field,
            )

    def test_summary_now_still_carries_the_live_status_class(self):
        """Non-regression: the `.crd-summary-now` modifier class on the "Now"
        field must survive the esc()->mdHtml() swap."""
        self.assertIn('crd-summary-body crd-summary-now', self.render_summary_src)

    def test_agents_panel_task_title_uses_mdhtmlsafe_but_fallbacks_stay_escaped(self):
        # DEFECT FIX (adversarial review): a.task is machine/agent-authored
        # free text (e.g. "delete the stray *.pyc") -- mdHtml() always goes
        # through app.js's full md(), whose single-asterisk italics rule
        # corrupts that glob. This must route through mdHtmlSafe() (drops
        # single-asterisk italics only), never plain mdHtml() and never
        # plain esc().
        src = self.render_agents_panel_src
        self.assertIn("mdHtmlSafe(a.task)", src)
        self.assertNotIn("mdHtml(ctx, a.task)", src)
        # The id/literal-label fallback is NOT session-authored free text --
        # must stay on plain esc(), not be swept into the mdHtmlSafe() call too.
        self.assertIn('esc(a.aid || "background agent")', src)
        self.assertNotIn('esc(a.task', src)

    def test_ask_question_and_options_use_mdhtml(self):
        src = self.entry_html_src
        self.assertIn("mdHtml(ctx, q0.q)", src)
        self.assertIn("mdHtml(ctx, o)", src)
        self.assertNotIn("esc(q0.q)", src)

    def test_shell_commands_and_file_paths_are_not_converted(self):
        """THE THINGS THAT MUST NOT CHANGE: `*`, `_`, backticks are shell
        metacharacters and path syntax -- running c.cmd/e.target through
        markdown would corrupt what they actually say. Same entryHtml()
        function that now calls mdHtml() for the ask entry must still esc()
        these two."""
        src = self.entry_html_src
        self.assertIn("esc(c.cmd)", src)
        self.assertIn("esc(e.target)", src)
        self.assertNotIn("mdHtml(ctx, c.cmd)", src)
        self.assertNotIn("mdHtml(ctx, e.target)", src)


# ---------------------------------------------------------------------------
# TASK 2b -- THE MOST VALUABLE TEST: mdHtml() actually escapes before it
# transforms, executed for real against hostile input. No test anywhere in
# this suite asserted this invariant before; a recent icon refactor nearly
# removed the escape-first ordering entirely (see this file's own security
# comment, ext_cr_detail.js ~line 182).
# ---------------------------------------------------------------------------

def _md_xss_driver_js(bundle):
    md_html_src = _extract_function(bundle, "mdHtml")
    # app.js's own esc()/md() -- concatenated ahead of ext_cr_detail.js into
    # the SAME <script> tag by page.py's build_page(), so mdHtml()'s bare
    # references to `esc`/`mdBlock` are real reachable globals in production.
    # Pulled from the SAME assembled bundle, not retyped, so a change to
    # either stays honestly pinned.
    esc_src = re.search(r'const esc\s*=.*', bundle).group(0)
    md_src = _extract_function(bundle, "md")
    return r"""
%s
%s
%s
// ctx.markdown (ext_cr_boot.js:420) verbatim shape: wraps md() in a real
// element via innerHTML, then mdHtml() reads .innerHTML back out. No jsdom
// here -- a plain object stub is representative for well-formed, already-
// closed-tag HTML (exactly what md() ever produces), and this test only
// cares about the STRING mdHtml() ultimately hands to the caller, which is
// what actually lands in a real innerHTML= assignment in production.
var document = { createElement: function () { return { innerHTML: "" }; } };
function markdown(text) {
  var d = document.createElement("div");
  d.innerHTML = (typeof md === "function") ? md(text || "") : esc(text || "");
  return d;
}
var ctx = { markdown: markdown };

var OUT = {};
OUT["script_tag"] = mdHtml(ctx, "<script>alert(1)</script>");
OUT["img_onerror"] = mdHtml(ctx, "<img src=x onerror=alert(1)>");
OUT["js_link"] = mdHtml(ctx, "[click me](javascript:alert(1))");
// THE ORDER PROOF: if escaping ever ran AFTER markdown transforms (the exact
// "build a string with user text and then escape it afterward" bug shape),
// this would either leave the <script> tag live inside the <strong>, or
// double-escape/neuter the ** into literal asterisks. Escape-first means the
// script tag is neutralised AND the ** still becomes a real <strong>.
OUT["bold_wrapping_script"] = mdHtml(ctx, "**<script>alert(1)</script>**");
// Sanity: mdHtml() must still actually apply markdown to benign input, so a
// bug that made it esc()-only everywhere (safe, but not "the markdown
// renderer") would also be caught.
OUT["benign_bold"] = mdHtml(ctx, "**hello**");
console.log("===MD_XSS_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (esc_src, md_src, md_html_src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMarkdownRendererEscapesBeforeTransforming(unittest.TestCase):
    """The single most valuable test in this pass: mdHtml() is the ONLY
    function in ext_cr_detail.js allowed to turn session-authored text into
    HTML (its own security comment says so) -- prove that guarantee by
    actually running it against hostile strings, not by reading the source
    and trusting the comment."""

    @classmethod
    def setUpClass(cls):
        bundle = _extract_script_content(_read_page())
        js = _md_xss_driver_js(bundle)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "mdHtml XSS harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_script_tag_is_neutralised(self):
        out = self.OUT["script_tag"]
        self.assertNotIn("<script", out, "a live <script> tag survived mdHtml(): %r" % out)
        # Prove it was actually ESCAPED, not silently stripped/dropped --
        # dropping would also "pass" a naive substring check while hiding a
        # different bug (content loss).
        self.assertIn("&lt;script&gt;", out)

    def test_img_onerror_is_neutralised(self):
        out = self.OUT["img_onerror"]
        # No LIVE <img element can exist -- `<` is always escaped by esc(),
        # so a real "<img" (unescaped) tag can never appear in the output.
        self.assertNotIn("<img", out, "a live <img> tag survived mdHtml(): %r" % out)
        self.assertIn("&lt;img", out)

    def test_javascript_href_link_is_never_created(self):
        """md()'s own link rule only matches `https?://` (app.js's `md()`),
        so a `javascript:` target can never become a real <a href> -- it must
        surface as inert escaped text, and specifically no `<a` tag (with any
        href) may appear in the output at all for this input."""
        out = self.OUT["js_link"]
        self.assertNotIn("<a ", out, "an anchor tag was created for a non-http(s) link: %r" % out)
        self.assertNotRegex(out, r'href\s*=', "a live href attribute leaked through: %r" % out)

    def test_escape_runs_before_markdown_transform_not_after(self):
        """THE ORDER INVARIANT, precisely: **<script>alert(1)</script>**
        must come out as a real <strong> wrapping ESCAPED text -- proving
        esc() ran first (so the script tag was already inert text by the
        time ** was turned into a tag) rather than markdown running first
        (which would either leave the script tag live, or get its own tags
        corrupted by a later blanket-escape pass)."""
        out = self.OUT["bold_wrapping_script"]
        self.assertNotIn("<script", out)
        self.assertIn("<strong>", out, "markdown bold was not applied at all: %r" % out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        # And the <strong> tags themselves must be real, unescaped tags --
        # not also neutered by a second escape pass running after md().
        self.assertNotIn("&lt;strong&gt;", out)

    def test_benign_markdown_still_renders(self):
        """mdHtml() must still BE a markdown renderer, not just esc() wearing
        a new name -- a fix that made it esc()-only everywhere would pass
        every test above while quietly regressing every other mdHtml() call
        site (narration, prompts, notes) back to plain text."""
        self.assertEqual(self.OUT["benign_bold"], "<strong>hello</strong>")


# ---------------------------------------------------------------------------
# DEFECT FIX (adversarial review): mdHtmlSafe(text) -- the agents panel's
# machine-output-safe counterpart to mdHtml() -- actually drops single-
# asterisk italics (an agent `task` label can read "delete the stray *.pyc")
# while keeping escape-first, bold, code and links intact. Executed for real
# against the exact bundle, not paraphrased.
# ---------------------------------------------------------------------------

def _md_html_safe_driver_js(bundle):
    md_html_safe_src = _extract_function(bundle, "mdHtmlSafe")
    esc_src = re.search(r'const esc\s*=.*', bundle).group(0)
    md_src = _extract_function(bundle, "md")
    md_safe_src = _extract_function(bundle, "mdSafe")
    return r"""
%s
%s
%s
%s
var OUT = {};
OUT["glob_task"] = mdHtmlSafe("delete the stray *.pyc");
OUT["bold_preserved"] = mdHtmlSafe("**cleanup**: delete *.pyc");
OUT["xss_still_neutralised"] = mdHtmlSafe("<script>alert(1)</script> *.pyc");
console.log("===MD_XSS_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (esc_src, md_src, md_safe_src, md_html_safe_src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMdHtmlSafeDropsAsteriskItalics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        bundle = _extract_script_content(_read_page())
        js = _md_html_safe_driver_js(bundle)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "mdHtmlSafe harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_glob_in_agent_task_is_not_italicised(self):
        out = self.OUT["glob_task"]
        self.assertNotIn("<em>", out, "mdHtmlSafe() must never emit <em>: %r" % out)
        self.assertIn("*.pyc", out)

    def test_bold_still_works_alongside_a_literal_asterisk(self):
        out = self.OUT["bold_preserved"]
        self.assertIn("<strong>cleanup</strong>", out)
        self.assertNotIn("<em>", out)
        self.assertIn("*.pyc", out)

    def test_xss_is_still_neutralised(self):
        out = self.OUT["xss_still_neutralised"]
        self.assertNotIn("<script", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("*.pyc", out)


if __name__ == "__main__":
    unittest.main()
