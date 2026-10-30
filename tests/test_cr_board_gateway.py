"""Board tiles and rail rows show the server's `model_label` for an OpenRouter session (never the raw
`vendor/model` id); Anthropic rows keep `modelShort(s.model)`. Source-shape check on ext_cr_board.js."""
import os
import re
import unittest

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker", "web")


class TestBoardGatewayModelLabel(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_WEB, "ext_cr_board.js"), encoding="utf-8") as fh:
            self.src = fh.read()

    def test_both_sites_read_model_label_under_openrouter_guard(self):
        guarded = re.findall(
            r"var mdl = \(s\.gateway === 'openrouter' && s\.model_label\) \? s\.model_label : modelShort\(s\.model\);",
            self.src)
        self.assertEqual(len(guarded), 2, "rail row and tile must both use the guarded label")

    def test_no_unguarded_modelshort_assignment_left(self):
        self.assertNotIn("var mdl = modelShort(s.model);", self.src)


if __name__ == "__main__":
    unittest.main()
