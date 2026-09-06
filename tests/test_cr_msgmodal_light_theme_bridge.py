"""Regression test for: the #msgmodal dark-theme bridge (ext_cr_boot.css) covered
DARK only -- with the control view active in LIGHT theme, a narration entry opened
from the control view (ext_cr_detail.js's openTimelineEntry() -> app.js's shared
openText()/#msgmodal, the SAME static overlay classic's own "Narration" row has
always used) kept classic's OWN light tokens (app.css :root/html.light) instead of
ext_cr.css's `.tracker-next` ("Cream") palette -- a visible mismatch against the
rest of the control view in light theme, even though the equivalent dark case was
already fixed.

WHY NOT JUST WIDEN THE EXISTING DARK GATE (`#nextRoot.is-dark:not([hidden]) ~
#msgmodal`) TO `#nextRoot:not([hidden]) ~ #msgmodal` AND LET var() PICK THE RIGHT
VALUE PER THEME -- the obvious-looking simplification that would HALVE the rule
count instead of doubling it: #msgmodal is a SIBLING of #nextRoot in the DOM, never
its descendant, so it is never inside `.tracker-next`/`.tracker-next.is-dark` --
the only two places ext_cr.css defines --surface-raised/--text-primary/etc. No
ancestor of #msgmodal defines those custom properties (app.css's :root defines a
completely different token set for classic's own palette), so every
var(--token, ...) in the EXISTING dark block never actually resolves the custom
property -- it always falls straight through to its own literal fallback. That
means widening the dark block's own gate would make #msgmodal render the DARK
literal fallbacks unconditionally, including in light theme. THE FIX instead adds
a SEPARATE light-theme block, gated on `#nextRoot:not(.is-dark):not([hidden]) ~
#msgmodal`, using the light token names' LIGHT literal values as the var()
fallback (matching the existing dark block's own convention).

HARD CONSTRAINT (the user was explicit): classic's own default #msgmodal
appearance (#nextRoot [hidden], i.e. the classic dashboard on screen) must stay
byte-for-byte unchanged. This is verified below by grep: every selector line in
ext_cr_boot.css that mentions #msgmodal or #diffmodal is either the pre-existing
`[hidden]` display rule (predates this task, a different concern) or starts with
one of the two exact control-view gates -- nothing can ever apply outside a
genuinely-active control view.
"""
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

_WEB = os.path.join(_ROOT, "aitracker", "web")

DARK_GATE = "#nextRoot.is-dark:not([hidden]) ~ #msgmodal"
LIGHT_GATE = "#nextRoot:not(.is-dark):not([hidden]) ~ #msgmodal"


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


class TestMsgModalLightThemeBridgeAdded(unittest.TestCase):
    def setUp(self):
        self.css = _read_web_file("ext_cr_boot.css")
        self.cr_css = _read_web_file("ext_cr.css")

    def test_light_theme_gate_exists_with_a_full_rule_set(self):
        self.assertGreaterEqual(
            self.css.count(LIGHT_GATE), 10,
            "expected a full set of #msgmodal LIGHT-theme bridge rules, all under the light gate",
        )

    def test_dark_theme_gate_is_unchanged_and_still_present(self):
        # The pre-existing dark bridge (a different task) must still be there,
        # untouched by this addition.
        self.assertGreaterEqual(self.css.count(DARK_GATE), 10)

    def test_every_msgmodal_or_diffmodal_selector_is_hidden_rule_or_one_of_the_two_gates(self):
        """The hard constraint, proven by grep: nothing added or touched by this
        task can ever leak into classic's own default #msgmodal/#diffmodal
        appearance (#nextRoot [hidden])."""
        selector_lines = re.findall(r"^([^\n{]*#(?:msgmodal|diffmodal)[^\n{]*)\{", self.css, re.MULTILINE)
        self.assertGreater(len(selector_lines), 0, "no #msgmodal/#diffmodal selectors found at all")
        bad = []
        for raw in selector_lines:
            sel = raw.strip()
            if "[hidden]" in sel:
                continue
            if sel.startswith(DARK_GATE) or sel.startswith(LIGHT_GATE):
                continue
            bad.append(sel)
        self.assertEqual(
            bad, [],
            "found #msgmodal/#diffmodal selector(s) not gated to a control-room theme: %r" % bad,
        )

    def test_light_gate_and_dark_gate_are_mutually_exclusive_by_construction(self):
        # :not(.is-dark) vs .is-dark on the same #nextRoot -- can never both match
        # the same element at once, so light and dark rules can never both apply.
        self.assertIn(".is-dark", DARK_GATE)
        self.assertIn(":not(.is-dark)", LIGHT_GATE)

    def test_light_bridge_rules_only_use_real_control_room_light_tokens_with_matching_literals(self):
        # Every var() the light block introduces must be a real ext_cr.css token,
        # AND its literal fallback must be that token's actual LIGHT (.tracker-next)
        # value -- not the dark block's value copy-pasted by mistake. Confirms
        # the light block wasn't produced by a find-and-replace of the gate alone.
        light_block_start = self.css.index(LIGHT_GATE)
        light_block = self.css[light_block_start:]
        checks = {
            "--surface-raised": "#FFFFFF",
            "--surface-sunken": "#F4F1E8",
            "--surface-top": "#FBFAF7",
            "--text-primary": "#1E1B17",
            "--text-secondary": "#4A4237",
            "--text-muted": "#877866",
            "--text-link": "#3B5747",
            "--line-default": "#CFC7B7",
            "--line-subtle": "#E7E2D5",
            "--line-focus": "#3B5747",
        }
        for token, light_hex in checks.items():
            self.assertIn(token + ":", self.cr_css, "%s is not a real token in ext_cr.css" % token)
            pattern = re.compile(re.escape(token) + r",\s*" + re.escape(light_hex))
            self.assertRegex(
                light_block, pattern,
                "%s's fallback in the light bridge should be its light value %s" % (token, light_hex),
            )

    def test_nextroot_precedes_msgmodal_in_served_dom_order(self):
        # The `~` general sibling combinator only matches a LATER sibling.
        from aitracker import page
        html = page.build_page()
        next_root_at = html.index("id=nextRoot")
        msgmodal_at = html.index("id=msgmodal")
        self.assertLess(next_root_at, msgmodal_at)


if __name__ == "__main__":
    unittest.main()
