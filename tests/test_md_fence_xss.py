"""Markdown fence + mermaid style XSS (E3-B2a/B2b): runs the REAL mdBlock / mermaidSvg from app.js under Node."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "aitracker", "web", "app.js")
sys.path.insert(0, _ROOT)
from aitracker import pending  # noqa: E402
from tests.test_pending_ui_classic import _PRE  # noqa: E402

_HOSTILE_DIFF = "\n".join([
    " ```",
    " ```mermaid",
    " flowchart TD",
    '   classDef x fill:red" onmouseover="alert(document.domain)',
    "   A[hover me]:::x --> B",
    " ```",
    " ```x | 1 +",
    " [click](https://evil.example)",
    " <img src=x onerror=alert(1)>",
])

_DRIVER = r"""
var IN = JSON.parse(process.env.MDX_IN);
var OUT = {};
OUT.hostile = mdBlock("**git diff**\n" + IN.fenced);
OUT.mmd = mermaidSvg(IN.mmd);
OUT.plain = mdBlock("```js\nvar a = 1 < 2;\n```\nafter");
OUT.nested = mdBlock("````\n```\nstill code\n```\n````\nafter");
OUT.draft_open = hasDraftQuote("````\n```\n**Draft plan**\n> hi\n````");
OUT.draft_real = hasDraftQuote("**Draft plan**\n> hi");
OUT.draft_after_fence = hasDraftQuote("```\ncode\n```\n**Draft plan**\n> hi");
console.log("@@OUT@@" + JSON.stringify(OUT));
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestMdFenceXss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_APP, encoding="utf-8") as fh:
            src = fh.read()
        env = dict(os.environ, MDX_IN=json.dumps({
            "fenced": pending._fence(_HOSTILE_DIFF),
            "mmd": 'flowchart TD\n classDef x fill:red" onmouseover="x\n A:::x-->B\n B:::x'}))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_PRE + src + "\n" + _DRIVER)
            p = subprocess.run(["node", path], capture_output=True, text=True, timeout=60, env=env)
        if "@@OUT@@" not in p.stdout:
            raise AssertionError("harness failed rc=%s\n%s\n%s" % (p.returncode, p.stdout[-2000:], p.stderr[-2000:]))
        cls.O = json.loads(p.stdout.split("@@OUT@@", 1)[1].strip().splitlines()[0])

    def test_hostile_diff_stays_in_one_pre(self):
        h = self.O["hostile"]
        self.assertEqual(h.count("<pre class=mdpre>"), 1)
        # the hostile text is inert inside <pre><code> (angle brackets escaped); nothing may live outside it
        outside = h.split("<pre class=mdpre><code>", 1)[0] + h.split("</code></pre>", 1)[1]
        for bad in ("<a ", "mmd-slot", "onmouseover=", "<img", "onerror="):
            self.assertNotIn(bad, outside)
        self.assertNotIn("<img", h)
        self.assertNotIn("<a href", h)

    def test_mermaid_classdef_cannot_leave_style_attribute(self):
        m = self.O["mmd"] or ""
        self.assertNotIn("onmouseover=", m)

    def test_ordinary_fence_unchanged(self):
        p = self.O["plain"]
        self.assertEqual(p.count("<pre class=mdpre>"), 1)
        self.assertIn("var a = 1 &lt; 2;", p)
        self.assertIn("after", p.split("</pre>", 1)[1])

    def test_longer_fence_holds_shorter_fence_lines(self):
        n = self.O["nested"]
        self.assertEqual(n.count("<pre class=mdpre>"), 1)
        self.assertIn("still code", n.split("</pre>", 1)[0])

    def test_draft_quote_scan_agrees_on_fence_length(self):
        # a 4-backtick fence holds a 3-backtick line: the draft quote inside it is code, not a draft
        self.assertFalse(self.O["draft_open"])
        # positive controls: the same quote outside a fence IS a draft (so False above is the fence's doing)
        self.assertTrue(self.O["draft_real"])
        self.assertTrue(self.O["draft_after_fence"])


if __name__ == "__main__":
    unittest.main()
