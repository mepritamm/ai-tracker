"""Test that app.css honours prefers-reduced-motion: reduce for pulse animations.

The classic dashboard's .dot.live and .dot.amber elements pulse indefinitely by
default. Under prefers-reduced-motion: reduce, the animation must stop and the
dots must remain clearly identifiable via a static outline fallback (matching how
ext_cr_board.css handles .cr-tile-dot.is-working).

An adversarial review found THREE more still-animating-under-reduce offenders the
original version of this file didn't cover:
  - `.nowbanner .dot` -- index.html renders it as a bare `<span class=dot>` (no .live/
    .amber class), so the plain `.dot.live,.dot.amber` selector can never match it.
  - `.cursor` -- an indefinitely blinking text-entry caret, the canonical
    reduced-motion offender, injected on every live non-waiting session.
  - `.flash` -- a one-shot card-attention pulse.
This file now covers all five animating elements, not just the original two.

This file asserts:
1. The @media (prefers-reduced-motion: reduce) block exists in the assembled page;
2. Within it, .dot.live, .dot.amber, .nowbanner .dot, .cursor and .flash all disable
   their animation;
3. .dot.live/.dot.amber/.nowbanner .dot also have a visible static fallback (an outline);
   .cursor has an explicit static-visible fallback (opacity:1); .flash keeps a static
   version of its attention cue (a fixed box-shadow) rather than losing it outright;
4. The pulse/blink/flash animations still exist OUTSIDE the reduced-motion block (no
   blanket deletion);
5. The reduced-motion block comes AFTER every rule it overrides in source order --
   including `.cursor{animation:blink...}`, which (in the pre-fix file) sat AFTER the
   original reduced-motion block, meaning the plain rule silently won the cascade.

Idiom: static CSS-source checks against the assembled page (aitracker.page.build_page()),
same as tests/test_state_color_parity_app.py -- no node needed, this is pure CSS text.

Load-bearing proof: rsync this repo to /tmp without .git, delete the @media block
from the throwaway copy, and verify this test goes RED against that copy. Then
restore the real worktree (no changes made).
"""
import re
import unittest

from aitracker.page import build_page


def _style_block(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "served page has no <style> block"
    return m.group(1)


def _strip_comments(css):
    """Remove /* ... */ CSS comments before parsing."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _extract_reduced_motion_block(css, must_contain=None):
    """Extract the @media (prefers-reduced-motion: reduce) block from CSS.

    Uses a brace counter to properly handle nested braces. This avoids the fatal bug
    of [^}]* which matches opening braces {}, causing the pattern to close on the
    first nested rule's } instead of the outer media block's }, truncating the block
    and losing any rules that come after the first one.

    Args:
        css: The CSS text to search
        must_contain: Optional substring that the block must contain (e.g., ".dot.")
                      If provided, returns the first matching block containing it.

    Returns:
        The content inside the @media block's braces, or None if not found.
    """
    pattern = r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{"

    for match in re.finditer(pattern, css):
        start = match.end()  # Position after the opening {
        depth = 1
        pos = start

        # Walk forward, counting braces until we return to depth 0
        while pos < len(css) and depth > 0:
            if css[pos] == '{':
                depth += 1
            elif css[pos] == '}':
                depth -= 1
            pos += 1

        if depth == 0:
            # Extract the block content (between the outer braces)
            block = css[start:pos-1]

            # If must_contain is specified, check if this block contains it
            if must_contain is None or must_contain in block:
                return block

    return None


class ClassicReducedMotionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        html = build_page()
        cls.css = _style_block(html)
        cls.css_stripped = _strip_comments(cls.css)

    def test_prefers_reduced_motion_block_exists(self):
        """Assert the @media (prefers-reduced-motion: reduce) block is present in app.css specifically.

        Note: must_contain=".dot." ensures we match the app.css block, not ext_cr_board.css's
        reduced-motion block, which also exists in the assembled page. Without this filter,
        deleting app.css's block entirely would still pass this test.
        """
        block = _extract_reduced_motion_block(self.css_stripped, must_contain=".dot.")
        self.assertIsNotNone(block, "no @media (prefers-reduced-motion: reduce) block found in app.css containing .dot.")

    def test_reduced_motion_block_source_order(self):
        """Assert the reduced-motion block appears AFTER the dot rules in CSS source order.

        THIS IS CRITICAL: Both the plain `.dot.live{animation:pulseDot...}` rule and the
        `@media (prefers-reduced-motion) .dot.live{animation:none}` override have the same
        specificity (0-2-0 = element selector + class vs. media query adds NO specificity).
        CSS cascade resolution for equal specificity is SOURCE ORDER: the LATER rule wins.

        If the reduced-motion block moves BEFORE the dot rules, the plain rule's `animation:`
        declaration comes last and re-applies the pulse animation, silently breaking the
        feature. This test catches that by verifying the block index is GREATER than the
        index of the `.dot.live{...animation:pulseDot...}` rule (and likewise for .dot.amber).

        Load-bearing proof: try moving the @media block to BEFORE the `.dot.live` rule
        in a throwaway copy of app.css and run this test — it will FAIL with a clear
        message explaining the order dependency.
        """
        # Find the index of the `.dot.live{` rule that sets the pulseDot animation
        dot_live_match = re.search(
            r"\.dot\.live\{[^}]*background:var\(--st-working\)[^}]*animation:pulseDot",
            self.css_stripped
        )
        self.assertIsNotNone(
            dot_live_match,
            ".dot.live rule with animation:pulseDot not found (or order of properties changed)"
        )
        dot_live_index = dot_live_match.start()

        # Find the index of the .dot.amber rule
        dot_amber_match = re.search(
            r"\.dot\.amber\{[^}]*background:var\(--amber\)[^}]*animation:pulseAmber",
            self.css_stripped
        )
        self.assertIsNotNone(
            dot_amber_match,
            ".dot.amber rule with animation:pulseAmber not found (or order of properties changed)"
        )
        dot_amber_index = dot_amber_match.start()

        # Find the index of the @media (prefers-reduced-motion: reduce) block (app.css's version)
        media_pattern = r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{"
        media_blocks = list(re.finditer(media_pattern, self.css_stripped))
        self.assertGreaterEqual(
            len(media_blocks), 1,
            "@media (prefers-reduced-motion: reduce) block not found"
        )

        # Find the block that contains ".dot." (app.css's block, not ext_cr_board's)
        media_index = None
        for match in media_blocks:
            start = match.end()
            depth = 1
            pos = start
            while pos < len(self.css_stripped) and depth > 0:
                if self.css_stripped[pos] == '{':
                    depth += 1
                elif self.css_stripped[pos] == '}':
                    depth -= 1
                pos += 1
            block_content = self.css_stripped[start:pos-1]
            if ".dot." in block_content:
                media_index = match.start()
                break

        self.assertIsNotNone(
            media_index,
            "@media (prefers-reduced-motion: reduce) block containing .dot. not found"
        )

        # The CRITICAL assertion: the reduced-motion block must come AFTER both dot rules
        # so that the media query's animation:none override takes precedence in the cascade.
        self.assertGreater(
            media_index, dot_live_index,
            f"CRITICAL: @media (prefers-reduced-motion) block at position {media_index} "
            f"comes BEFORE .dot.live rule at position {dot_live_index}. "
            f"Equal specificity → source order wins → later .dot.live animation rule "
            f"will override the media query's animation:none. Move the @media block to "
            f"AFTER the .dot.live/.dot.amber rules."
        )
        self.assertGreater(
            media_index, dot_amber_index,
            f"CRITICAL: @media (prefers-reduced-motion) block at position {media_index} "
            f"comes BEFORE .dot.amber rule at position {dot_amber_index}. "
            f"Equal specificity → source order wins → later .dot.amber animation rule "
            f"will override the media query's animation:none. Move the @media block to "
            f"AFTER the .dot.live/.dot.amber rules."
        )

        # Same check for the three offenders the adversarial review added: .nowbanner .dot,
        # .cursor and .flash. .cursor in particular sat AFTER the original media block in the
        # pre-fix file, so this is the assertion that would have caught that exact bug.
        nowbanner_dot_match = re.search(
            r"\.nowbanner \.dot\{[^}]*animation:pulseDot", self.css_stripped
        )
        self.assertIsNotNone(nowbanner_dot_match,
                              ".nowbanner .dot rule with animation:pulseDot not found")
        cursor_match = re.search(
            r"\.cursor\{animation:blink", self.css_stripped
        )
        self.assertIsNotNone(cursor_match, ".cursor rule with animation:blink not found")
        flash_match = re.search(
            r"\.flash\{animation:flashcard", self.css_stripped
        )
        self.assertIsNotNone(flash_match, ".flash rule with animation:flashcard not found")

        for name, plain_match in (
            (".nowbanner .dot", nowbanner_dot_match),
            (".cursor", cursor_match),
            (".flash", flash_match),
        ):
            with self.subTest(selector=name):
                self.assertGreater(
                    media_index, plain_match.start(),
                    f"CRITICAL: @media (prefers-reduced-motion) block at position "
                    f"{media_index} comes BEFORE {name}'s plain animation rule at position "
                    f"{plain_match.start()}. Equal specificity → source order wins → the "
                    f"plain rule would silently re-enable the animation. Move the @media "
                    f"block to AFTER {name}'s rule."
                )

    # NOTE: these four used to match with a single regex of the shape
    # `@media(...)\{[^}]*\.dot\.live[^}]*outline`. That can never match a real
    # minified media block: `[^}]*` stops at the FIRST `}`, which is the close of
    # the nested `.dot.live,.dot.amber{animation:none}` rule, so the outline
    # declarations -- which live in a LATER nested rule -- were unreachable and
    # the assertion failed against correct CSS. They now assert against the
    # brace-balanced block `_extract_reduced_motion_block()` already returns for
    # the test above, which is what makes them robust to how the block is
    # ordered or minified.
    def _rm_rule(self, selector):
        """The declarations of one nested rule inside the reduced-motion block.

        Returns a space-joined concatenation of all declarations from every nested
        rule whose selector list contains the given selector.
        """
        block = _extract_reduced_motion_block(self.css_stripped, must_contain=".dot.")
        self.assertIsNotNone(block, "no @media (prefers-reduced-motion: reduce) block in app.css")
        out = []
        for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
            sels = [x.strip() for x in rule.group(1).split(",")]
            if selector in sels:
                out.append(rule.group(2))
        self.assertTrue(out, "%s has no rule inside the reduced-motion block" % selector)
        return " ".join(out)

    def test_dot_live_animation_disabled_in_reduced_motion(self):
        """Assert .dot.live has animation: none within the reduced-motion block."""
        self.assertRegex(self._rm_rule(".dot.live"), r"animation\s*:\s*none",
                         ".dot.live missing animation: none in reduced-motion block")

    def test_dot_amber_animation_disabled_in_reduced_motion(self):
        """Assert .dot.amber has animation: none within the reduced-motion block."""
        self.assertRegex(self._rm_rule(".dot.amber"), r"animation\s*:\s*none",
                         ".dot.amber missing animation: none in reduced-motion block")

    def test_dot_live_has_outline_fallback_in_reduced_motion(self):
        """A live dot must stay identifiable without motion, not just stop moving."""
        decls = self._rm_rule(".dot.live")
        self.assertRegex(decls, r"outline\s*:\s*2px\s+solid\s+var\(\s*--st-working\s*\)",
                         ".dot.live missing outline fallback in reduced-motion block")
        self.assertRegex(decls, r"outline-offset\s*:\s*2px",
                         ".dot.live missing outline-offset in reduced-motion block")

    def test_dot_amber_has_outline_fallback_in_reduced_motion(self):
        """Same for the amber (waiting) dot."""
        decls = self._rm_rule(".dot.amber")
        self.assertRegex(decls, r"outline\s*:\s*2px\s+solid\s+var\(\s*--amber\s*\)",
                         ".dot.amber missing outline fallback in reduced-motion block")
        self.assertRegex(decls, r"outline-offset\s*:\s*2px",
                         ".dot.amber missing outline-offset in reduced-motion block")

    def test_nowbanner_dot_animation_disabled_in_reduced_motion(self):
        """.nowbanner .dot -- index.html renders it as a bare `<span class=dot>` with no
        .live/.amber class, so the original `.dot.live,.dot.amber` selector could never
        match it; it needs its own entry in the reduced-motion block."""
        self.assertRegex(self._rm_rule(".nowbanner .dot"), r"animation\s*:\s*none",
                         ".nowbanner .dot missing animation: none in reduced-motion block")

    def test_nowbanner_dot_has_outline_fallback_in_reduced_motion(self):
        decls = self._rm_rule(".nowbanner .dot")
        self.assertRegex(decls, r"outline\s*:\s*2px\s+solid\s+var\(\s*--blue\s*\)",
                         ".nowbanner .dot missing outline fallback in reduced-motion block")
        self.assertRegex(decls, r"outline-offset\s*:\s*2px",
                         ".nowbanner .dot missing outline-offset in reduced-motion block")

    def test_cursor_animation_disabled_in_reduced_motion(self):
        """.cursor -- the blinking text-entry caret, injected on every live non-waiting
        session. An indefinitely blinking element is the canonical reduced-motion offender."""
        self.assertRegex(self._rm_rule(".cursor"), r"animation\s*:\s*none",
                         ".cursor missing animation: none in reduced-motion block")

    def test_cursor_stays_visible_in_reduced_motion(self):
        """Stopping the blink must not leave the caret stuck invisible/dim -- the element
        must stay identifiable, matching the outline-fallback principle used for the dots."""
        decls = self._rm_rule(".cursor")
        self.assertRegex(decls, r"opacity\s*:\s*1\b",
                         ".cursor missing an explicit visible (opacity:1) fallback")

    def test_flash_animation_disabled_in_reduced_motion(self):
        """.flash -- the one-shot card-attention pulse (1.3s box-shadow flare)."""
        self.assertRegex(self._rm_rule(".flash"), r"animation\s*:\s*none",
                         ".flash missing animation: none in reduced-motion block")

    def test_flash_keeps_a_static_attention_cue_in_reduced_motion(self):
        """The animation stops, but the element must stay identifiable -- a static
        box-shadow standing in for the flashcard keyframe's peak, not silence."""
        decls = self._rm_rule(".flash")
        self.assertRegex(decls, r"box-shadow\s*:\s*0\s+0\s+0\s+3px\s+rgba\(",
                         ".flash missing a static box-shadow fallback in reduced-motion block")

    def test_pulse_animations_still_exist_outside_reduced_motion(self):
        """Assert the pulseDot and pulseAmber animations are NOT deleted (exist outside the block)."""
        # The animation definitions should still be present in the CSS globally.
        self.assertIn("@keyframes pulseDot", self.css_stripped,
                     "pulseDot animation deleted (should only be disabled in reduced-motion, not removed)")
        self.assertIn("@keyframes pulseAmber", self.css_stripped,
                     "pulseAmber animation deleted (should only be disabled in reduced-motion, not removed)")

        # .dot.live and .dot.amber should still reference the animations.
        # The rules might have been updated but must still exist with animation references.
        self.assertRegex(self.css_stripped,
                        r"\.dot\.live\{[^}]*background:var\(--st-working\)[^}]*animation:pulseDot",
                        ".dot.live animation rule was deleted or the animation reference changed")
        self.assertRegex(self.css_stripped,
                        r"\.dot\.amber\{[^}]*background:var\(--amber\)[^}]*animation:pulseAmber",
                        ".dot.amber animation rule was deleted or the animation reference changed")

    def test_override_relationship_in_both_directions(self):
        """Assert the override works: plain dot HAS pulse, reduced-motion dot does NOT.

        This proves the media query override is active:
        1. The plain .dot.live (outside the media block) must set animation:pulseDot
        2. The .dot.live inside @media (prefers-reduced-motion) must set animation:none
        This catches cases where one or the other is missing or misconfigured.
        """
        # Plain rule (outside media block) must have the pulse animation
        self.assertRegex(
            self.css_stripped,
            r"\.dot\.live\{[^}]*animation:pulseDot",
            ".dot.live outside the reduced-motion block does not set animation:pulseDot"
        )

        # Reduced-motion override must disable the animation
        rm_decls = self._rm_rule(".dot.live")
        self.assertRegex(
            rm_decls, r"animation\s*:\s*none",
            ".dot.live inside the reduced-motion block does not set animation:none"
        )

        # Same for amber
        self.assertRegex(
            self.css_stripped,
            r"\.dot\.amber\{[^}]*animation:pulseAmber",
            ".dot.amber outside the reduced-motion block does not set animation:pulseAmber"
        )

        rm_amber_decls = self._rm_rule(".dot.amber")
        self.assertRegex(
            rm_amber_decls, r"animation\s*:\s*none",
            ".dot.amber inside the reduced-motion block does not set animation:none"
        )


if __name__ == "__main__":
    unittest.main()
