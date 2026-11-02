"""The detail header's goal line (raw last prompt) is clamped, click-to-expand.

After a compaction the last prompt is the whole multi-KB summary; unclamped it
pushed the rest of the detail page below the fold.
"""
import os
import re
import unittest

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker", "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


class GoalLineClamp(unittest.TestCase):
    def test_css_clamps_and_open_unclamps(self):
        css = _read("ext_cr_detail.css")
        base = re.search(r"\.cr \.crd-goalline \{([^}]*)\}", css).group(1)
        self.assertIn("-webkit-line-clamp: 3", base)
        self.assertIn("overflow: hidden", base)
        opened = re.search(r"\.cr \.crd-goalline\.crd-goal-open \{([^}]*)\}", css).group(1)
        self.assertIn("-webkit-line-clamp: unset", opened)

    def test_js_wires_toggle_and_resets_on_session_switch(self):
        js = _read("ext_cr_detail.js")
        self.assertIn('goalEl.setAttribute("data-act", "toggle-goal")', js)
        self.assertRegex(js, r'case "toggle-goal":[^;]*classList\.toggle\("crd-goal-open"\)')
        self.assertIn('gl.classList.remove("crd-goal-open")', js)

    def test_empty_goal_stays_hidden(self):
        # no goal (fresh session / Auggie without a prompt) -> line hidden, no empty clamp box
        self.assertIn("goalEl.hidden = !goalText;", _read("ext_cr_detail.js"))

    def test_served_page_carries_clamp_ungated(self):
        # eval: the page the server actually serves (built from web/*) has the clamp + toggle,
        # and nothing gates the goal line by host or viewport.
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(_WEB)))
        from aitracker.page import build_page
        page = build_page()
        self.assertIn("-webkit-line-clamp: 3", page)
        self.assertIn('case "toggle-goal":', page)
        self.assertNotRegex(page, r"\.remote[^{]*\.crd-goalline|\.crd-goalline\s*\{\s*display:\s*none")


if __name__ == "__main__":
    unittest.main()
