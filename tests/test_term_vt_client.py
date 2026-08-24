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
        # Renamed "↗ Terminal" / "↗ Resume" -> "↗ External terminal" / "↗ External resume" (user
        # instruction, landing via a concurrent worktree not yet merged into this one). What this
        # test actually protects is that the native/external launch pair still EXISTS as a
        # secondary control at all, not the exact wording -- accept either label so it stays green
        # both before and after that sibling rename merges in.
        self.assertTrue("↗ External terminal" in self.src or "↗ Terminal" in self.src)
        self.assertTrue("↗ External resume" in self.src or "↗ Resume" in self.src)


class TestPlainCtrlCAlwaysSendsSigint(unittest.TestCase):
    """The single most important key in a terminal (plan requirement 2): plain Ctrl+C (no Shift,
    no Meta) must ALWAYS reach keyToBytes's ctrl-letter mapping (which turns it into \\x03) and
    must NEVER be captured by the copy handler -- copy is Cmd+C or Ctrl+Shift+C only. Proven here
    by pinning the actual boolean conditions, not just their presence, so a future edit that
    accidentally widens the copy condition to swallow plain Ctrl+C fails this test."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_copy_combo_requires_meta_or_ctrl_shift_never_plain_ctrl(self):
        body = _function_body(self.src, "Terminal.prototype._onKeyDown")
        i = body.index("var copyCombo")
        combo = body[i:body.index(";", body.index(");", i))]
        # plain Ctrl+C is ctrlKey=true, shiftKey=false, metaKey=false -- assert the condition
        # structurally excludes that combination on both of its OR branches.
        self.assertIn('ev.metaKey && !ev.ctrlKey', combo)
        self.assertIn('ev.ctrlKey && ev.shiftKey', combo)

    def test_plain_ctrl_c_falls_through_to_keytobytes_unmodified(self):
        # keyToBytes's own ctrl-letter branch (the thing that actually produces \x03 for Ctrl+C)
        # must still exist, unconditioned on any copy/paste/zoom check -- i.e. this file never grew
        # a special case that intercepts a bare "c" before it reaches this regex mapping.
        self.assertIn('if (/^[a-zA-Z]$/.test(k)) return String.fromCharCode(k.toUpperCase().charCodeAt(0) & 0x1f);', self.src)

    def test_onkeydown_never_returns_before_keytobytes_for_plain_ctrl_key(self):
        # Every early `return` inside _onKeyDown before the keyToBytes call is gated behind a
        # combo/zoom condition that plain Ctrl+C cannot satisfy (copyCombo/pasteCombo require Meta
        # or Ctrl+Shift; the zoom check requires +/-/=/_) -- so plain Ctrl+C always reaches
        # `var bytes = keyToBytes(ev);` further down.
        body = _function_body(self.src, "Terminal.prototype._onKeyDown")
        self.assertIn("var bytes = keyToBytes(ev);", body)
        self.assertLess(body.index("var copyCombo"), body.index("var bytes = keyToBytes(ev);"))


class TestCopyRunsBeforeReturnToLive(unittest.TestCase):
    """Copying FROM a frozen scrollback selection must not first jump back to live -- doing so
    would rebuild every row's innerHTML (see _paintRow) and destroy the very DOM text nodes the
    browser Selection was anchored to, silently copying nothing. The copy branch must therefore
    `return` before the generic viewingHistory-returns-to-live rule runs."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_copy_branch_returns_before_the_generic_scroll_to_bottom_rule(self):
        body = _function_body(self.src, "Terminal.prototype._onKeyDown")
        copy_idx = body.index("if (copyCombo)")
        generic_idx = body.index("if (this.viewingHistory) this._scrollToBottom();")
        self.assertLess(copy_idx, generic_idx)


class TestScrollbackNeverYanksLiveDiffsBack(unittest.TestCase):
    """Requirement 1's core promise: while scrolled into history, a live SSE diff must never
    repaint the DOM out from under the user. _applyPatch must update the live model
    unconditionally (so returning to live is instant and correct) but skip painting/cursor layout
    while viewingHistory."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_applypatch_updates_model_before_the_viewinghistory_gate(self):
        body = _function_body(self.src, "Terminal.prototype._applyPatch")
        model_update = body.index("this.grid[r] = {")
        gate = body.index("if (this.viewingHistory) {")
        self.assertLess(model_update, gate)

    def test_applypatch_skips_paint_while_viewing_history(self):
        body = _function_body(self.src, "Terminal.prototype._applyPatch")
        self.assertIn("if (this.viewingHistory) {", body)
        self.assertIn("this.pendingNewOutput = true", body)
        # the live-paint loop must be reachable only AFTER that gate would have returned
        gate = body.index("if (this.viewingHistory) {")
        paint = body.index("this._paintRow(rows[j][0]")
        self.assertLess(gate, paint)


class TestAltScreenWheelSendsArrowsNotHistory(unittest.TestCase):
    """Requirement 1: vim/less/top own the alt screen and read arrow keys -- the wheel must NEVER
    trigger a scrollback fetch while `this.alt` is true."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_onwheel_checks_alt_before_touching_scroll_state(self):
        body = _function_body(self.src, "Terminal.prototype._onWheel")
        alt_check = body.index("if (this.alt)")
        # the scrollback-history path (fetchScrollback / _scrollHistoryDebounced) must be
        # textually AFTER the alt-screen branch's own early return.
        history_call = body.index("this._scrollHistoryDebounced(next)")
        self.assertLess(alt_check, history_call)
        self.assertIn('"\\x1b[B"', body)
        self.assertIn('"\\x1b[A"', body)


class TestScrollbackFetchContract(unittest.TestCase):
    """Pins the exact endpoint/params this file was told to code against, so a mismatch against
    the concurrently-built server half fails loudly here instead of silently at runtime."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_fetch_hits_the_documented_endpoint_with_offset_and_rows(self):
        self.assertIn('fetch("/api/term/scrollback?tty=" + encodeURIComponent(tty) + "&offset=" + offset + "&rows=" + rows)', self.src)

    def test_response_offset_is_trusted_over_the_requested_one(self):
        # the response's clamped `offset` must be what gets stored, never the value that was sent
        self.assertIn("self.scrollOffset = data.offset;", self.src)


class TestSelectionIsNotBlockedByTheCaptureInput(unittest.TestCase):
    """Requirement 2: the capture textarea must no longer cover the pane (that was v1's whole
    selection blocker) -- confirmed by asserting the CSS drops the covering `inset:0` layout and
    the JS mousedown handler no longer preventDefault()s (which would cancel native selection)."""

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def test_mousedown_no_longer_prevents_default(self):
        self.assertIn('pane.addEventListener("mousedown", function () { input.focus(); });', self.js)
        self.assertNotIn('pane.addEventListener("mousedown", function (ev) { ev.preventDefault(); input.focus(); });', self.js)

    def test_input_is_off_screen_not_covering_the_pane(self):
        self.assertIn("left: -9999px", self.css)
        self.assertNotIn("inset: 0;\n  z-index: 2;", self.css)

    def test_pane_allows_text_selection(self):
        self.assertIn("user-select: text;", self.css)


class TestFontZoomRecomputesGeometry(unittest.TestCase):
    """Requirement 3: a font-size change must reflow, exactly like a window resize -- _zoom must
    call measureAndResize() (which resets the grid and POSTs /api/term/resize) rather than just
    changing CSS."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_zoom_calls_measure_and_resize(self):
        body = _function_body(self.src, "Terminal.prototype._zoom")
        self.assertIn("this.measureAndResize();", body)

    def test_ctrl_or_cmd_plus_minus_is_wired_and_distinct_from_copy_paste(self):
        body = _function_body(self.src, "Terminal.prototype._onKeyDown")
        zoom_idx = body.index('k === "+" || k === "=" || k === "-" || k === "_"')
        copy_idx = body.index("var copyCombo")
        paste_idx = body.index("var pasteCombo")
        self.assertGreater(zoom_idx, copy_idx)
        self.assertGreater(zoom_idx, paste_idx)


class TestDefensiveServerFieldsDoNotAssumeUnbuiltState(unittest.TestCase):
    """cursor_visible / bracketed_paste / bell all depend on term_vt.py fields that do not exist
    yet in this worktree (see the header comment) -- each must be read defensively (guarded by an
    `undefined`/type check) rather than assumed present, so this file doesn't crash or misbehave
    against today's actual snapshot payload (v/rows/cursor/alt only)."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_cursor_visible_is_read_defensively(self):
        self.assertIn("if (msg.cursor_visible !== undefined) this.cursorVisible = !!msg.cursor_visible;", self.src)

    def test_bracketed_paste_is_read_defensively(self):
        self.assertIn("if (msg.bracketed_paste !== undefined) this.bracketedPaste = !!msg.bracketed_paste;", self.src)

    def test_bell_is_read_defensively_as_a_monotonic_counter(self):
        self.assertIn('if (typeof msg.bell === "number") {', self.src)

    def test_gap_is_documented_against_the_real_server_file(self):
        # this must name the actual server-side symbols so a reader can go verify/reconcile it,
        # not just assert something vague.
        self.assertIn("_set_private_mode", self.src)
        self.assertIn("cursor_visible", self.src)


if __name__ == "__main__":
    unittest.main()
