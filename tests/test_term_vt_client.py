"""Tests for the Tier 3 CLIENT half — aitracker/web/ext_vt.{js,css} and the ext_launch.js rewire.

There is no JS engine in the stdlib, so — mirroring tests/test_term_launch.py's
TestButtonsFollowServerPolicy — these assert against the baked page and the raw asset source,
not against runtime behaviour. term_vt.py (the server-side emulator/routes) is a SEPARATE,
concurrently-built half and is deliberately not imported or required here.
"""
import os
import unittest

from aitracker.page import build_page

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "aitracker", "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _function_body(src, marker):
    """The full source of one `Terminal.prototype.X = function ...` (or any `marker`), up to the
    next `Terminal.prototype.` after it -- robust against the body growing/shrinking, unlike a
    fixed-size slice."""
    start = src.index(marker)
    nxt = src.find("Terminal.prototype.", start + len(marker))
    return src[start: nxt if nxt != -1 else len(src)]


class TestAssetsAreInlined(unittest.TestCase):
    """Step 0's page.build_page() must pick up ext_vt.js/css the same way it already picks up
    ext_launch.*/ext_run.* -- confirmed against the actually-served page, not just the source
    files in isolation."""

    def setUp(self):
        self.page = build_page()

    def test_ext_vt_js_is_inlined(self):
        self.assertIn("window.ExtVT", self.page)
        self.assertIn("sgrRunClass", self.page)

    def test_ext_vt_css_is_inlined(self):
        self.assertIn(".vtpane", self.page)
        self.assertIn(".vtcursor", self.page)

    def test_mount_div_is_used_not_decorative(self):
        # the mount exists (Step 0) ...
        self.assertIn("id=ext_vt", self.page)
        # ... and ext_vt.js actually targets it, twice: once for the modal (EXT render hook),
        # once for the standalone tab.
        self.assertIn('document.getElementById("ext_vt")', self.page)
        self.assertIn('mount.classList.add("vtfull")', self.page)

    def test_registers_into_the_shared_ext_array(self):
        self.assertIn("EXT.push(render)", self.page)

    def test_placement_relative_to_the_other_two_tiers(self):
        # page.py's read_ext() glob-sorts ext_*.js by filename -- launch, then run, then vt --
        # so ext_vt.js's definitions land after ext_launch.js's in the one concatenated script.
        # window.ExtVT must exist by the time a click can happen (after full load), which is true
        # regardless of order, but this pins the actual concatenation order this file assumed.
        self.assertLess(self.page.index("function localOnly"),   # ext_launch.js
                         self.page.index("window.ExtVT"))         # ext_vt.js


class TestSgrEncodingIsIsolated(unittest.TestCase):
    """The SGR decoding must live in exactly one small, clearly-labelled function -- that's the
    piece that has to be reconciled against term_vt.Screen.snapshot() once it exists."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_single_sgr_decode_function(self):
        self.assertEqual(self.src.count("function sgrRunClass"), 1)

    def test_classes_come_from_parsed_integers_only(self):
        self.assertIn("parseInt(p, 10)", self.src)

    def test_contract_is_documented_for_reconciliation(self):
        self.assertIn("term_vt.Screen.snapshot()", self.src)
        self.assertIn("ASSUMED", self.src.upper())


class TestEscapeKeyConflictIsResolved(unittest.TestCase):
    """Requirement 4: Escape must reach the shell while the terminal is focused, and must not
    also close the modal at the same time. Resolution asserted here: the terminal's own keydown
    handler stops propagation for every key it handles (Escape included), and the modal's own
    Escape-to-close listener is registered separately and only ever sees the key when the
    terminal did NOT consume it."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_terminal_keydown_stops_propagation(self):
        i = self.src.index("Terminal.prototype._onKeyDown")
        body = self.src[i:i + 800]
        self.assertIn("ev.stopPropagation()", body)
        self.assertIn('case "Escape": return "\\x1b";', self.src)

    def test_modal_escape_listener_is_separate_and_guarded(self):
        self.assertIn('if (ev.key !== "Escape") return;', self.src)
        self.assertIn('overlay.style.display !== "flex"', self.src)


class TestNoRawHtmlInsertion(unittest.TestCase):
    """Requirement 6: terminal content is untrusted, so text must be escaped before insertion,
    and span classes must come from parsed integers only (covered above)."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_row_text_is_escaped_before_going_into_innerhtml(self):
        body = _function_body(self.src, "Terminal.prototype._paintRow")
        self.assertIn("esc(glyphs)", body)
        self.assertIn("esc(_padSpaces(", body)


class TestStandaloneMountEscapesTheHiddenApp(unittest.TestCase):
    """Caught by driving the real browser against the real server, not by any assertion here.

    The `#ext_vt` mount lives inside `.app`, and `.vt-standalone` hides `.app` with
    `display:none !important`. A `display:none` ancestor removes its whole subtree from
    rendering -- `position:fixed; inset:0` on the descendant does NOT rescue it. So the
    standalone tab built a completely correct DOM (25 rows, right text, right colours) and
    laid it out at 0x0: the user saw a black screen and nothing in the console.

    The bootstrap must therefore reparent the mount to <body> BEFORE it takes over the window."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_standalone_reparents_the_mount_out_of_app(self):
        self.assertIn("document.body.appendChild(mount)", self.src)

    def test_reparent_happens_before_the_fullscreen_class(self):
        reparent = self.src.index("document.body.appendChild(mount)")
        vtfull = self.src.index('mount.classList.add("vtfull")')
        self.assertLess(reparent, vtfull,
                        "reparent must precede the fullscreen layout, or the first paint is 0x0")


class TestRightTrimmedRowsArePadded(unittest.TestCase):
    """The coordinator's correction: Screen.snapshot() RIGHT-TRIMS `text` (drops trailing cells
    that are both a plain space and default-styled) -- it does not pad/truncate to `cols`. A row
    that shrinks must not leave the previous, longer render's glyphs to its right ("ghost text"),
    and the cursor must not fall off the end when it sits past `text.length`. See the runtime
    proof of the shrink case in the harness (reported separately -- there is no JS engine here)."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_no_residue_because_the_whole_row_is_rebuilt_every_paint(self):
        # _paintRow must set el.innerHTML wholesale (never append to / patch a prefix of the
        # existing row markup) -- that's what makes a shorter re-render leave nothing behind.
        body = _function_body(self.src, "Terminal.prototype._paintRow")
        self.assertIn("el.innerHTML = html;", body)
        self.assertNotIn("innerHTML +=", body)
        self.assertNotIn("innerHTML.slice", body)

    def test_row_is_padded_out_to_the_full_column_width(self):
        body = _function_body(self.src, "Terminal.prototype._paintRow")
        self.assertIn("if (pos < cols) html += esc(_padSpaces(cols - pos));", body)

    def test_a_run_extending_past_text_length_is_not_clamped_to_it(self):
        # the old (wrong) version did `Math.min(text.length, run[1]|0)` -- a run's end must NOT
        # be capped at text.length, or a styled trailing pad (e.g. a background colour on an
        # erased line) silently loses its style and falls back to plain blank.
        body = _function_body(self.src, "Terminal.prototype._paintRow")
        self.assertNotIn("Math.min(text.length, run[1]", body)
        self.assertIn("tailPad", body)

    def test_cursor_clamp_uses_pane_width_not_row_text_length(self):
        body = _function_body(self.src, "Terminal.prototype._layoutCursor")
        # the actual clamp expression must bound against `this.cols`, never against the current
        # row's (possibly short, right-trimmed) text -- pull just the assignment line so the
        # explanatory comment above it (which legitimately says "text.length") can't fool this.
        line = [l for l in body.splitlines() if l.strip().startswith("var c =")][0]
        self.assertIn("this.cols - 1", line)
        self.assertNotIn("text.length", line)


class TestNoNewModalSystem(unittest.TestCase):
    """Conventions rule 4: reuse the existing modal, don't invent a second one."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_reuses_existing_overlay_modal_classes(self):
        self.assertIn('overlay.className = "overlay"', self.src)
        self.assertIn('modal.className = "modal vtmodal"', self.src)
        self.assertIn('mh.className = "mh"', self.src)


class TestResizeIsReal(unittest.TestCase):
    """Requirement 5: report actual rendered cols/rows, and resize on open + on window resize."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_measures_actual_pane_before_creating_the_pty(self):
        self.assertIn("computeColsRows(probePane)", self.src)

    def test_posts_resize_on_measured_change(self):
        self.assertIn("postResize(this.ttyId, m.cols, m.rows)", self.src)

    def test_window_resize_is_wired(self):
        self.assertIn('window.addEventListener("resize"', self.src)


class TestExtLaunchStillPassesTier1Contract(unittest.TestCase):
    """Guard against a regression in this session's own edit: ext_launch.js's Tier 1
    probe-and-latch strings (asserted properly by tests/test_term_launch.py) must survive the
    rewire, and the two NEW in-browser buttons must never be gated by that same host/probe
    check (conventions: no control hidden by host/viewport)."""

    def setUp(self):
        self.src = _read("ext_launch.js")

    def test_in_browser_buttons_call_extvt(self):
        self.assertIn("window.ExtVT.open(cur,", self.src)

    def test_in_browser_buttons_are_built_before_the_localonly_gate(self):
        # vtHtml is assembled unconditionally; nativeHtml is the only thing gated by localOnly().
        self.assertLess(self.src.index("const vtHtml ="), self.src.index("if (localOnly())"))

    def test_native_button_kept_as_secondary_control(self):
        # What this protects is that the NATIVE launch pair still exists as a secondary
        # control -- it was not deleted when the in-browser terminal became primary. Only
        # the label text moved: the pair is now qualified "External" so that which-opens-
        # where is obvious beside the two "here" buttons.
        self.assertIn("↗ External terminal", self.src)
        self.assertIn("↗ External resume", self.src)


if __name__ == "__main__":
    unittest.main()
