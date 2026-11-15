"""Model marker: board tiles, rail rows and the session-detail header show the server's
`model_label` as one small `.cr-model-chip` (OpenRouter sessions included -- the server label
already reads "gpt-5 (OpenRouter)", never the raw `vendor/model` id). Server owns the label:
the board no longer re-derives it with modelShort(). Source-shape checks + the server label."""
import os
import re
import unittest

from aitracker.util import model_label

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker", "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


class TestModelMarker(unittest.TestCase):
    def setUp(self):
        self.board = _read("ext_cr_board.js")
        self.detail = _read("ext_cr_detail.js")
        self.css = _read("ext_cr.css")

    def test_board_chip_reads_server_label_only(self):
        m = re.search(r"function modelChip\(s\) \{(.*?)\n    \}", self.board, re.S)
        self.assertIsNotNone(m, "modelChip helper missing")
        body = m.group(1)
        self.assertIn("s.model_label", body)
        self.assertIn("'cr-model-chip'", body)
        self.assertNotIn("modelShort", body, "server owns the label -- no JS re-derivation")

    def test_tile_and_rail_both_render_the_chip(self):
        self.assertIn("if (chip) head.appendChild(chip);", self.board)           # tile, null-safe
        self.assertNotRegex(self.board, r"appendChild\(modelChip\(",
                            "modelChip returns null for an unknown model; appendChild(null) throws")
        self.assertIn("[dirLine, modelChip(s)]", self.board)                      # rail row
        self.assertNotIn("trailing += ' · ' + mdl", self.board, "model no longer text-joined")
        self.assertNotIn("var mdl = ", self.board)

    def test_detail_header_has_chip_hidden_when_unknown(self):
        self.assertIn('<span class="cr-model-chip" hidden></span>', self.detail)
        self.assertIn("chipEl.hidden = !modelBit;", self.detail)
        self.assertIn("meta.model_label", self.detail)
        line = re.search(r"var metaBits = \[(.*?)\]", self.detail).group(1)
        self.assertNotIn("modelBit", line, "model moved out of the metaline into the chip")

    def test_classic_sidebar_and_header_render_the_chip(self):
        app = _read("app.js")
        self.assertIn("if(s.model_label)bits.push(modelChipHtml(s.model_label,s.model));", app)
        self.assertIn("if(m.model_label)meta.push(modelChipHtml(m.model_label,m.model));", app)
        self.assertIn('replace(/"/g,"&quot;")', app, "tooltip attr must escape quotes")

    def test_chip_style_is_shared_and_scoped(self):
        self.assertIn(".cr-model-chip {", self.css)
        self.assertIn(".cr-model-chip[hidden] { display: none; }", self.css)
        # the detail chip's `hidden` (unknown model) relies on this !important blanket rule
        # beating the chip's own display:inline-block
        self.assertIn(".tracker-next [hidden] { display: none !important; }", self.css)

    def test_server_labels_the_chip_reads(self):
        self.assertEqual(model_label("claude-fable-5-2"), "Fable 5.2")   # modelShort missed fable
        self.assertEqual(model_label("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(model_label("openai/gpt-5:free"), "gpt-5 (OpenRouter)")
        self.assertEqual(model_label("claude-opus-4-7-500k"), "Opus 4.7 (500k)")   # Auggie id
        self.assertEqual(model_label("claude-sonnet-4-5-20250929"), "Sonnet 4.5")  # date not a ctx tag
        self.assertEqual(model_label(""), "")                           # unknown -> no chip
        self.assertEqual(model_label("<synthetic>"), "")


if __name__ == "__main__":
    unittest.main()
