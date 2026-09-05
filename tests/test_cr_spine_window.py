"""Pins the progress spine's shipped SURFACE — the parts that live in markup and
CSS rather than in a pure function, and that `tests/test_cr_logic.py` (which only
evaluates the exported derivations) therefore cannot see.

Three capabilities are pinned here:

1. The dead collapse caret is GONE. `.crd-spine-chevron` was a `<span>` with no
   `data-act` and no handler anywhere — a control that looked collapsible and
   toggled nothing. Its removal is only real if no reference survives.

2. The time-window control (span chips + drag-pan) is PRESENT and reachable on
   every viewport. Per the tracker-gap localhost-vs-remote rule, a control the
   user drives must never be gated by host, and must survive the phone tier —
   a long session is exactly what you triage from a phone.

3. The full-motion treatment has a reduced-motion off-switch for EVERY animation
   it adds. Motion without that switch is an accessibility regression, and the
   assembled-page gate would not otherwise notice.
"""
import os
import re
import unittest

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")


def _read_page():
    import sys
    sys.path.insert(0, os.path.dirname(_AITRACKER))
    from aitracker import page
    return page.build_page()


def _detail_css():
    with open(os.path.join(_WEB, "ext_cr_detail.css"), encoding="utf-8") as fh:
        return fh.read()


class TestSpineChevronRemoved(unittest.TestCase):
    def setUp(self):
        self.page = _read_page()

    def test_no_chevron_reference_survives_anywhere(self):
        """The caret is removed from markup AND from CSS — a leftover rule for a
        class nobody emits is the kind of thing that gets re-added by mistake."""
        self.assertNotIn("crd-spine-chevron", self.page)
        for name in ("ext_cr_detail.js", "ext_cr_detail.css"):
            with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
                self.assertNotIn("crd-spine-chevron", fh.read(), name)

    def test_spine_is_a_group_not_an_image(self):
        """role="img" makes assistive tech ignore every descendant — which would
        hide the segment buttons the design doc calls focusable, and the new span
        chips. The summary moves to a visually-hidden live region instead."""
        self.assertIn('class="crd-spine" role="group"', self.page)
        self.assertNotIn('class="crd-spine" role="img"', self.page)
        self.assertIn("crd-spine-sr", self.page)


class TestSpineWindowControlShipped(unittest.TestCase):
    def setUp(self):
        self.page = _read_page()
        self.css = _detail_css()

    def test_span_chips_and_pan_track_are_in_the_page(self):
        self.assertIn("crd-spine-spans", self.page)
        self.assertIn('data-act="spine-span"', self.page)
        self.assertIn('data-act="spine-now"', self.page)
        self.assertIn("crd-spine-track", self.page)

    def test_drag_pan_is_wired_on_the_wrapper_not_the_repainted_children(self):
        """renderSpine replaces the bar's and gutter's innerHTML on every 2s poll,
        so a listener or pointer capture held on either would die mid-drag."""
        self.assertIn("wireSpinePan", self.page)
        self.assertIn("setPointerCapture", self.page)
        self.assertIn("pointercancel", self.page)

    def test_pointer_is_captured_lazily_so_a_plain_click_still_jumps(self):
        """Adversarial review, reproduced in a real browser: calling
        setPointerCapture in POINTERDOWN retargets the following `click` to the
        capturing element. `.crd-spine-track` has no data-act, so the delegated
        handler's closest("[data-act]") returned null and "click to jump the chat
        there" silently died for EVERY click while a span chip was active — not
        just after a drag, so the spineJustPanned guard never even ran.

        The capture must therefore happen only once the gesture is a real drag."""
        i = self.page.find("wireSpinePan")
        self.assertGreater(i, -1)
        block = self.page[i:i + 4000]

        def code_only(text):
            """Drop // comments — the pointerdown handler deliberately NAMES
            setPointerCapture in a comment explaining why it must not call it."""
            return "\n".join(ln.split("//")[0] for ln in text.splitlines())

        down = code_only(block[block.find('addEventListener("pointerdown"'):
                               block.find('addEventListener("pointermove"')])
        self.assertNotIn("setPointerCapture", down,
                         "capturing on pointerdown breaks click-to-jump")
        move = code_only(block[block.find('addEventListener("pointermove"'):])
        self.assertIn("setPointerCapture", move,
                      "the drag still needs capture once it really is a drag")

    def test_window_state_resets_when_the_bound_session_changes(self):
        """Adversarial review, reproduced live: the detail view mounts once per
        PAGE LOAD, so `ui` is shared by every session opened in the tab. spineEndMs
        is an absolute timestamp, so leaking it into the next session panned that
        spine to a meaningless time and rendered the empty-window message over a
        32-hour session. The reset belongs on the session-rebind path."""
        i = self.page.find("ui._boundSid = sid;")
        self.assertGreater(i, -1)
        rebind = self.page[i:i + 900]
        for field in ("ui.spineSpanMs = null;", "ui.spineEndMs = null;",
                      "ui.spineJustPanned = false;"):
            self.assertIn(field, rebind, field + " not reset on session change")

    def test_pan_clamps_at_write_time_so_drag_slack_cannot_accumulate(self):
        """ui.spineEndMs is written straight from pointer deltas. If it were only
        clamped when READ, dragging past the start of the session would bank the
        excess and the spine would sit frozen until you dragged all of it back.
        The pan therefore re-clamps through spineWindow -- the same single bound
        the chips use, not a second copy of the arithmetic."""
        self.assertIn("var clamped = spineWindow(ui, firstEventTime(", self.page)

    def test_pan_is_touch_usable_without_eating_vertical_scroll(self):
        """`pan-y` hands us the horizontal axis and leaves the page's own vertical
        scrolling to the browser — the difference between a usable phone control
        and a spine that traps the scroll."""
        self.assertRegex(self.css, r"\.crd-spine-track\.is-pannable\s*\{[^}]*touch-action:\s*pan-y")

    def test_window_control_is_not_gated_by_host(self):
        """tracker-gap's localhost-vs-remote rule: no control the user RECORDS with
        may be hidden off-localhost — two shipped bugs came from exactly that.

        The page does host-gate one thing, legitimately: "open in external editor"
        reaches out from the browser's own machine, which is the single carve-out
        the rule names. So this asserts the narrow, real invariant — no spine
        control sits anywhere near a hostname test — rather than banning the
        string outright and failing on an unrelated, correct usage."""
        for m in re.finditer(r"location\.hostname", self.page):
            near = self.page[max(0, m.start() - 400):m.start() + 400]
            self.assertNotIn("crd-spine", near, "a spine control is host-gated")
        # ...and nothing hides the chips by CSS either, on any host or viewport
        for rule in re.findall(r"[^{}]*crd-spine-spans[^{}]*\{[^{}]*\}", self.css):
            self.assertNotRegex(rule, r"display:\s*none", "chips hidden by: " + rule[:120])

    def _media_block(self, needle):
        """Return the body of the first @media block whose condition contains
        `needle`, brace-matched so it survives edits to the file."""
        i = self.css.find("@media")
        while i >= 0:
            brace = self.css.find("{", i)
            cond = self.css[i:brace]
            if needle in cond:
                depth, j = 0, brace
                while j < len(self.css):
                    if self.css[j] == "{":
                        depth += 1
                    elif self.css[j] == "}":
                        depth -= 1
                        if depth == 0:
                            return self.css[brace + 1:j]
                    j += 1
            i = self.css.find("@media", i + 1)
        self.fail("no @media block matching %r" % needle)

    def test_chips_are_in_the_real_phone_tier_not_a_narrower_sub_range(self):
        """The phone tier in this file is <=600px; <=480px is a NARROWER sub-range
        inside it. Chip sizing landed in the sub-range once, which left phones
        between 481 and 600px with desktop-sized 9px chips. Pin the tier."""
        phone = self._media_block("max-width: 600px")
        self.assertIn("crd-spine-span", phone,
                      "chip sizing is not in the <=600px phone tier")

    def test_phone_chips_meet_the_44px_hit_target_this_file_mandates(self):
        """ext_cr_detail.css states the rule explicitly ("All hit targets >= 44px")
        and every other phone control complies via a real box size. A 9px chip
        does not, and accessibility is not the place to be lazy."""
        phone = self._media_block("max-width: 600px")
        i = phone.find(".crd-spine-span {")
        self.assertGreater(i, -1, "no .crd-spine-span rule in the phone tier")
        rule = phone[i:phone.find("}", i)]
        self.assertRegex(rule, r"min-height:\s*44px")
        self.assertRegex(rule, r"min-width:\s*44px")

    def test_chips_wrap_rather_than_overflow(self):
        self.assertRegex(self.css, r"\.crd-spine-spans\s*\{[^}]*flex-wrap:\s*wrap")


class TestSpineMotionHasAnOffSwitch(unittest.TestCase):
    def setUp(self):
        self.css = _detail_css()

    def test_every_added_animation_exists(self):
        for kf in ("crd-seg-in", "crd-shimmer", "crd-edge-breathe", "crd-now-pulse"):
            self.assertIn("@keyframes " + kf, self.css, kf)

    def test_every_animation_is_disabled_under_reduced_motion(self):
        """Collect the reduced-motion blocks and require each animated selector to
        be named in one of them. A new animation with no off-switch fails here."""
        blocks = []
        for m in re.finditer(r"@media[^{]*prefers-reduced-motion[^{]*\{", self.css):
            depth, i = 0, m.end() - 1
            while i < len(self.css):
                if self.css[i] == "{":
                    depth += 1
                elif self.css[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            blocks.append(self.css[m.end():i])
        joined = "\n".join(blocks)
        self.assertTrue(blocks, "no prefers-reduced-motion block found at all")
        # the entry animation is switched off by SELECTOR (.is-fresh .crd-seg),
        # which is what the rule actually has to name to win the cascade
        for sel in ("crd-seg-dot", "is-fresh", "crd-seg-running::after",
                    "crd-seg-edge", "crd-mark-now"):
            self.assertIn(sel, joined, sel + " animates with no reduced-motion off-switch")

    def test_entry_animation_is_gated_on_the_segment_set_changing(self):
        """The page repaints every 2 seconds. Without the data-sig gate in
        renderSpine the entry animation restarts forever and the spine strobes."""
        page = _read_page()
        self.assertIn("is-fresh", page)
        self.assertIn('bar.getAttribute("data-sig")', page)


if __name__ == "__main__":
    unittest.main()
