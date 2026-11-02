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


if __name__ == "__main__":
    unittest.main()
