"""Regression tests for two control-room polish fixes in this pass
(ext_cr_dialogs.js / ext_cr_dialogs.css / ext_cr_board.css):

TASK 1 -- ext_cr_dialogs.js used to carry its own second, weaker markdown
renderer, `mdLite(s)`: escape, then only backtick-code and **bold**, with
`\n\n+` turned into a paragraph break and a bare `\n` turned into `<br>`. Its
own code comment already said it shouldn't exist ("every consumer ... should
call the SAME implementation rather than fork a second one"). Two call sites
in `renderDiffPopout()` used it: the diff pop-out's "Rendered" view of a .md
file's diff content, and the narration/prompt full-text pop-out ('text'
mode) -- both document-shaped, potentially multi-paragraph content, so both
are now routed through app.js's own block-level renderer `mdBlock()`
(concatenated ahead of every ext_cr_*.js file into ONE <script> tag by
page.py's build_page(), the same reachable-global pattern
ext_cr_detail.js's mdHtml() already relies on for the exact same reason --
see that file's own comment at ~line 203). `mdLite()` and its stale comment
are deleted outright.

TASK 2 -- the shared `--scrim` token (ext_cr.css, defined under
`.tracker-next` / `.tracker-next.is-dark`) already had two of its three
consumers repointed at it (ext_cr_dialogs.css's .cr-backdrop, ext_cr_boot.
css's .cr-scrim). The third, ext_cr_board.css's `.cr-rail-scrim`, was still a
bare `rgba(0, 0, 0, .35)` with no light/dark handling -- now repointed at
`var(--scrim, rgba(0, 0, 0, .35))`, same "own prior literal value as
fallback" pattern the other two sites already use. The token's own values
are untouched.

Idiom: same "brace-match the real function text out of the assembled page
bundle, run it under Node against hostile input" technique
tests/test_cr_detail_agents_pill_and_markdown.py uses for mdHtml() -- proving
the escape-first-then-transform order for real rather than trusting a
comment, applied here to mdBlock() at the exact two call sites that used to
go through mdLite().
"""
import json
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
_WEB = os.path.join(_ROOT, "aitracker", "web")

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the
    real bundle. Raises loudly (never returns a guess) if the shape has
    moved. Same helper as tests/test_cr_detail_agents_pill_and_markdown.py."""
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


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


# ---------------------------------------------------------------------------
# TASK 1a -- mdLite is gone, everywhere, and the two call sites now route
# through the shared block renderer.
# ---------------------------------------------------------------------------

class TestMdLiteForkIsDeleted(unittest.TestCase):

    def test_mdlite_does_not_appear_anywhere_in_the_served_page(self):
        """Regression guard against the fork coming back under any name --
        checks the WHOLE assembled page (script + style + markup), not just
        the extracted bundle, so a stray reference anywhere would be caught."""
        html = _read_page()
        self.assertNotIn("mdLite", html)

    def test_mdlite_does_not_appear_in_the_source_file_either(self):
        src = _read_web_file("ext_cr_dialogs.js")
        self.assertNotIn("mdLite", src)

    def test_render_diff_popout_routes_both_call_sites_through_mdblock(self):
        bundle = _extract_script_content(_read_page())
        src = _extract_function(bundle, "renderDiffPopout")
        self.assertNotIn("mdLite(", src)
        # Site 1: the diff pop-out's "Rendered" view of a .md file's diff text.
        self.assertIn(
            "mdBlock((payload.lines || []).map(function (l) { return l.text; }).join('\\n'))",
            src,
        )
        # Site 2: the narration/prompt full-text pop-out ('text' mode).
        self.assertIn("mdBlock(payload.text || '')", src)
        # Sanity: at least the two real calls above are present (a doc comment
        # elsewhere in the function also mentions mdBlock() by name, so this
        # checks a floor, not an exact count).
        self.assertGreaterEqual(src.count("mdBlock("), 2)


# ---------------------------------------------------------------------------
# TASK 1b -- THE MOST VALUABLE TEST: mdBlock(), at the exact two call sites
# that used to go through mdLite(), actually escapes before it transforms --
# proven by executing it against hostile input, not by reading the source.
# ---------------------------------------------------------------------------

def _mdblock_xss_driver_js(bundle):
    esc_src = re.search(r'const esc\s*=.*', bundle).group(0)
    md_src = _extract_function(bundle, "md")
    md_block_src = _extract_function(bundle, "mdBlock")
    # None of the hostile strings below contain a ``` fence, so mdBlock()'s
    # fenced-code branch (which calls mermaidSvg/ico/copyCode) is never
    # reached -- esc/md/mdBlock alone are a faithful, self-contained slice.
    return r"""
%s
%s
%s
var OUT = {};
OUT["script_tag"] = mdBlock("<script>alert(1)</script>");
OUT["img_onerror"] = mdBlock("<img src=x onerror=alert(1)>");
OUT["js_link"] = mdBlock("[x](javascript:alert(1))");
// THE ORDER PROOF (same shape as mdHtml()'s own test): if escaping ever ran
// AFTER the markdown transform, this would either leave the <script> tag
// live inside the <strong>, or corrupt the ** into literal asterisks.
OUT["bold_wrapping_script"] = mdBlock("**<script>alert(1)</script>**");
// Sanity: mdBlock() must still actually be a markdown renderer, not esc()
// wearing a new name -- a "fix" that degraded it that way would pass every
// assertion above while quietly regressing every other mdBlock() consumer
// (narration, prompts, the classic full-text modal) back to plain text.
OUT["benign_bold"] = mdBlock("**hello**");
console.log("===MDBLOCK_XSS_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (esc_src, md_src, md_block_src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMdBlockEscapesBeforeTransformingAtTheConvertedCallSites(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        bundle = _extract_script_content(_read_page())
        js = _mdblock_xss_driver_js(bundle)
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "mdBlock XSS harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout, "===MDBLOCK_XSS_JSON_START===")

    def test_script_tag_is_neutralised(self):
        out = self.OUT["script_tag"]
        self.assertNotIn("<script", out, "a live <script> tag survived mdBlock(): %r" % out)
        self.assertIn("&lt;script&gt;", out)

    def test_img_onerror_is_neutralised(self):
        out = self.OUT["img_onerror"]
        # No LIVE <img element can exist -- `<`/`>` are always escaped by
        # esc() first, so a real unescaped "<img ... onerror=...>" tag can
        # never appear. The literal text "onerror=" surviving INSIDE the
        # escaped &lt;...&gt; wrapper is inert plain text, not an attribute.
        self.assertNotIn("<img", out, "a live <img> tag survived mdBlock(): %r" % out)
        self.assertNotRegex(out, r'<img[^&]*onerror=',
                             "a live onerror= attribute survived on a real tag: %r" % out)
        self.assertIn("&lt;img", out)

    def test_javascript_href_link_is_never_created(self):
        """md()'s own link rule only matches `https?://`, so a `javascript:`
        target can never become a real <a href> -- must surface as inert
        text, with no `<a` tag and no live href attribute at all (the literal
        word "javascript:" surviving as plain, non-attribute text is fine --
        it is never wired to anything clickable)."""
        out = self.OUT["js_link"]
        self.assertNotIn("<a ", out, "an anchor tag was created for a non-http(s) link: %r" % out)
        self.assertNotRegex(out, r'href\s*=', "a live href attribute leaked through: %r" % out)

    def test_escape_runs_before_markdown_transform_not_after(self):
        out = self.OUT["bold_wrapping_script"]
        self.assertNotIn("<script", out)
        self.assertIn("<strong>", out, "markdown bold was not applied at all: %r" % out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        self.assertNotIn("&lt;strong&gt;", out)

    def test_benign_bold_still_becomes_strong(self):
        """Guards against a future 'fix' that quietly degrades the shared
        renderer into esc()-only -- **bold** must still produce a real
        <strong>, wrapped in mdBlock()'s own paragraph markup."""
        self.assertIn("<strong>hello</strong>", self.OUT["benign_bold"])
        self.assertIn("mdp", self.OUT["benign_bold"], "mdBlock()'s own paragraph wrapper is missing")


# ---------------------------------------------------------------------------
# TASK 1c -- the CSS addition for mdBlock()'s .mdh headings inside the
# pop-out's .cr-rendered-md wrapper (the other classes -- .mdp/.mdul/.mdt/
# .cblock/.mdpre/.codecopy/.mmd -- are already styled generically under the
# `.cr` scope in ext_cr_detail.css, so no addition was needed for those).
# ---------------------------------------------------------------------------

class TestRenderedMarkdownPopoutHeadingIsStyled(unittest.TestCase):

    def test_cr_rendered_md_headings_get_the_shared_heading_treatment(self):
        css = _read_web_file("ext_cr_dialogs.css")
        self.assertIn(".cr .cr-rendered-md .mdh", css)
        self.assertIn(".cr .cr-rendered-md .mdh:first-child", css)


# ---------------------------------------------------------------------------
# TASK 2 -- the third hardcoded scrim (ext_cr_board.css's .cr-rail-scrim) is
# repointed at the shared --scrim token, matching the other two sites.
# ---------------------------------------------------------------------------

class TestRailScrimUsesSharedToken(unittest.TestCase):

    def test_no_bare_hardcoded_scrim_rgba_remains(self):
        """THE BUG, precisely: `background: rgba(0, 0, 0, .35);` with no
        var(--scrim, ...) wrapper at all."""
        css = _read_web_file("ext_cr_board.css")
        self.assertNotIn("background: rgba(0, 0, 0, .35);", css)

    def test_rail_scrim_references_the_shared_scrim_token(self):
        css = _read_web_file("ext_cr_board.css")
        m = re.search(r'\.cr-rail-scrim\s*\{[^}]*\}', css)
        self.assertIsNotNone(m, "could not find the .cr-rail-scrim rule block")
        # (the real rule spans the @media block below the bare display:none
        # selector -- fall back to a wider window if the tight match above
        # only caught the empty display:none shell)
        idx = css.index(".cr-rail-scrim")
        window = css[idx:idx + 1200]
        self.assertIn("var(--scrim, rgba(0, 0, 0, .35))", window,
                      "cr-rail-scrim's background does not reference the shared --scrim token "
                      "with its own prior literal value as fallback")

    def test_all_three_scrim_sites_reference_the_shared_token(self):
        sites = {
            "ext_cr_dialogs.css (.cr-backdrop)": ("ext_cr_dialogs.css", ".cr-backdrop"),
            "ext_cr_boot.css (.cr-scrim)": ("ext_cr_boot.css", ".cr-scrim"),
            "ext_cr_board.css (.cr-rail-scrim)": ("ext_cr_board.css", ".cr-rail-scrim"),
        }
        for label, (fname, selector) in sites.items():
            css = _read_web_file(fname)
            idx = css.find(selector)
            self.assertGreaterEqual(idx, 0, "%s not found in %s" % (selector, fname))
            window = css[idx:idx + 1200]
            self.assertIn("var(--scrim,", window, "%s does not reference var(--scrim, ...)" % label)

    def test_scrim_token_values_are_unchanged(self):
        """This pass repoints consumers at the token -- it must never touch
        the token's own values."""
        css = _read_web_file("ext_cr.css")
        self.assertIn("--scrim: rgba(30, 27, 23, .38);", css)
        self.assertIn("--scrim: rgba(16, 14, 12, .58);", css)


if __name__ == "__main__":
    unittest.main()
