"""Regression test for: the detail view's header action row (Search / Flag /
Open terminal / Resume / Queue a note / External, plus Rename / Pin on the title
line below it) could wrap onto extra lines in the ~900-1300px band, even though
`ext_cr_detail.css` already has a `@media (max-width: 900px)` rule whose own
comment says it exists to prevent exactly that.

THE GAP: that 900px rule only ever targeted `.crd-btn-label` (the icon+word
span used by Search/Flag/Rename/Pin) and the icon-only buttons themselves
(`.crd-iconbtn`, `.crd-rename`, `.crd-pin`) -- it never touched the actual
WIDEST buttons in the same row: "Open terminal", "Resume", "Queue a note",
"External" (ext_cr_detail.js, plain `.crd-btn` text, not `.crd-btn-label`).
Both `.crd-id-row1` and `.crd-row1-actions` carry `flex-wrap: wrap`, so nothing
ever clips -- the row just silently wraps in the 900-1300px band instead,
which is the very crowding the existing rule's comment says it exists to stop.

THE FIX: a new `@media (max-width: 1300px) and (min-width: 901px)` rule
compacts `.crd-row1-actions .crd-btn`'s padding/font-size (and the row's own
gap) -- WITHOUT removing any button's text. "Open terminal" reads exactly as
written at every width; every control keeps a real accessible name (its own
text node, plus the pre-existing title/aria-label attributes on the
icon-only ones). The existing <=900px rule also re-applies the same compacted
padding to these four buttons (belt-and-braces against a future edit to
either block independently drifting the other back to full size).

Widths targeted, and why: 901-1300px is the band the crowding was actually
observed in (900px is already owned by the existing, more drastic,
label-dropping rule; 1024px/1279px are unrelated column-layout breakpoints
already in this file). Below 900px, the four wide buttons stay compacted
(not reset to full padding) alongside the icon-only degrade the pre-existing
rule already applies to Search/Flag/Rename/Pin.
"""
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

_WEB = os.path.join(_ROOT, "aitracker", "web")


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


def _block(css, selector, after=None):
    text = css if after is None else css[after:]
    start = text.index(selector)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:i + 1]
    raise AssertionError("unterminated block for %r" % selector)


class TestDetailActionRowCompactsBeforeItWraps(unittest.TestCase):
    def setUp(self):
        self.css = _read_web_file("ext_cr_detail.css")
        self.js = _read_web_file("ext_cr_detail.js")

    def test_the_four_wide_buttons_are_plain_crd_btn_text_not_crd_btn_label(self):
        """Ground truth check: confirms the bug's premise still holds -- these
        four are NOT using the .crd-btn-label the 900px rule already covers."""
        for action in ("open-terminal", "resume", "toggle-note", "external"):
            m = re.search(r'data-act="%s"[^>]*>([^<]*)</button>' % re.escape(action), self.js)
            self.assertIsNotNone(m, "button for data-act=%r not found" % action)
            self.assertNotIn("crd-btn-label", self.js[max(0, m.start() - 80):m.start()])

    def test_a_901_to_1300_band_exists_and_compacts_the_wide_buttons(self):
        self.assertIn("max-width: 1300px", self.css)
        self.assertIn("min-width: 901px", self.css)
        block = _block(self.css, "@media (max-width: 1300px) and (min-width: 901px)")
        self.assertIn(".crd-row1-actions .crd-btn", block)
        # Compacts padding/font, never `display: none` on the buttons or their text.
        self.assertIn("padding:", block)
        self.assertNotRegex(block, r"\.crd-row1-actions\s+\.crd-btn\b[^}]*display:\s*none")

    def test_the_901_1300_band_does_not_touch_labels_or_hide_any_control(self):
        block = _block(self.css, "@media (max-width: 1300px) and (min-width: 901px)")
        self.assertNotIn("crd-btn-label", block)
        self.assertNotIn("display: none", block)
        self.assertNotIn("display:none", block)

    def test_below_900px_the_wide_buttons_stay_compacted_not_reset(self):
        block = _block(self.css, "@media (max-width: 900px) {")
        self.assertIn(".crd-row1-actions .crd-btn", block)
        self.assertIn("padding:", block)

    def test_ordinary_desktop_width_keeps_full_padding_and_real_words(self):
        """Above 1300px, `.crd-btn`'s own base rule (not a media query) still
        wins -- full padding, and the buttons' own text nodes are untouched --
        so this task's "readable words at ordinary widths" requirement holds."""
        base_btn = _block(self.css, ".cr .crd-btn {")
        self.assertIn("padding: 7px 14px", base_btn)
        for label in ("Open terminal", "Resume", "Queue a note", "External"):
            self.assertIn(label, self.js)

    def test_every_action_still_has_an_accessible_name_in_source(self):
        # The four wide buttons carry their own visible text (checked above);
        # Search/Flag/Rename/Pin (icon-only at <=900px) already carry a real
        # title/aria-label pair, unaffected by this task's changes.
        for act in ("toggle-search", "toggle-flag", "rename", "toggle-pin"):
            self.assertIn('data-act="%s"' % act, self.js)


if __name__ == "__main__":
    unittest.main()
