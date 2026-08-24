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


def _body_until(src, start_marker, end_markers):
    """Like _function_body, but for the ContextBar/modal section, which comes AFTER every
    `Terminal.prototype.` definition in the file -- `_function_body`'s hardcoded next-marker scan
    would return "start of ContextBar through end of file" there instead of one function's body.
    Bounds to whichever of `end_markers` occurs first after `start_marker`."""
    start = src.index(start_marker)
    search_from = start + len(start_marker)
    ends = [i for i in (src.find(m, search_from) for m in end_markers) if i != -1]
    return src[start: min(ends) if ends else len(src)]


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


class TestContextBarModelSwitcher(unittest.TestCase):
    """The model switcher: hardcoded ladder, sends /model <name> via the inject route, gated on
    Claude-vs-shell mode, and never steals keyboard focus from the terminal."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_model_ladder_is_hardcoded_with_reasoning(self):
        self.assertIn('var MODEL_LADDER = ["haiku", "sonnet", "opus", "fable"];', self.src)
        self.assertIn("HARDCODED", self.src)

    def test_gated_on_resume_or_new_never_cwd(self):
        body = _body_until(self.src, "function ContextBar(", ["ContextBar.prototype."])
        self.assertIn('mode === "resume"', body)
        self.assertIn('mode === "new"', body)

    def test_picking_a_model_sends_the_documented_inject_contract(self):
        body = _body_until(self.src, "ContextBar.prototype._pickModel = function", ["ContextBar.prototype."])
        self.assertIn('"/api/term/inject"', body)
        self.assertIn('tty: this.ttyId', body)
        self.assertIn('text: "/model " + name', body)
        self.assertIn("submit: true", body)
        self.assertIn("clear_first: true", body)

    def test_inject_failure_surfaces_a_toast_not_silence(self):
        body = _body_until(self.src, "ContextBar.prototype._pickModel = function", ["ContextBar.prototype."])
        self.assertIn("404", body)
        self.assertIn("toast(", body)

    def test_button_never_takes_native_focus(self):
        body = _body_until(self.src, "function ContextBar(", ["ContextBar.prototype."])
        # preventDefault on mousedown is what stops a <button> from stealing DOM focus at all.
        self.assertIn('btn.addEventListener("mousedown", function (ev) { ev.preventDefault(); });', self.src)
        self.assertIn("_focusTerminal", body)


class TestContextUsageIsIsolatedAndDocumented(unittest.TestCase):
    """The context-window field's wire shape (d.context = {current, limit, pct}) was landed by a
    parallel agent partway through this session -- CONFIRMED against the coordinator's real
    shape, not this file's own first guess (which used {used, limit} with a client-computed
    percentage; see the reconciliation note in the header comment and this file's own git log).
    The read must live in exactly one small function with the real contract spelled out."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_single_read_function(self):
        self.assertEqual(self.src.count("function readContextUsage"), 1)

    def test_contract_is_documented_for_reconciliation(self):
        self.assertIn("d.context", self.src)
        self.assertIn("CONFIRMED CONTRACT", self.src)
        self.assertIn("current", self.src)
        self.assertIn("limit", self.src)
        self.assertIn("pct", self.src)

    def test_reads_current_not_the_first_guess_used_field(self):
        body = _body_until(self.src, "function readContextUsage", ["function ContextBar("])
        self.assertIn("c.current", body)
        self.assertNotIn("c.used", body)

    def test_absent_or_malformed_context_means_nothing_to_show(self):
        body = _body_until(self.src, "function readContextUsage", ["function ContextBar("])
        self.assertIn("return null;", body)

    def test_no_denominator_is_invented_when_limit_is_absent(self):
        body = _body_until(self.src, "function readContextUsage", ["function ContextBar("])
        # limit must stay null (not e.g. defaulted to some guessed window size) when the server
        # doesn't supply a positive number for it.
        self.assertIn('var limit = (typeof c.limit === "number" && c.limit > 0) ? c.limit : null;', body)

    def test_pct_is_read_verbatim_never_computed_here(self):
        # the coordinator was explicit: pct is SERVER-computed only, and this file must never
        # re-derive its own percentage from current/limit (the earlier draft did exactly that).
        body = _body_until(self.src, "function readContextUsage", ["function ContextBar("])
        self.assertIn('var pct = (typeof c.pct === "number") ? c.pct : null;', body)
        self.assertNotIn("current / limit", body.replace("c.current", "current").replace("c.limit", "limit"))
        self.assertNotIn("current / c.limit", body)

    def test_cumulative_total_reads_the_existing_shared_tokens_field(self):
        # d.tokens.{in,out} already ships today for every provider (claude.py/auggie.py/
        # augment_ext.py) -- unlike d.context, this one is NOT a guess, so it's read directly
        # rather than through the isolated function above.
        body = _body_until(self.src, "ContextBar.prototype._applySessionData = function", ["ContextBar.prototype."])
        self.assertIn("d.tokens", body)


class TestContextReadoutLeadsWithCurrentNotTheBar(unittest.TestCase):
    """Coordinator's design correction, mid-build: Claude sessions (the terminal's main use case)
    have `limit: null` and `pct: null` -- there is no honest denominator. `current` must always
    be the lead element when present, the bar/percentage only an ENHANCEMENT gated on `pct`
    specifically (never on `limit` alone, and never fabricated), and the whole readout must
    render nothing -- not "0", not empty chrome -- when `current` is null."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def _readout_body(self):
        return _body_until(self.src, "ContextBar.prototype._renderReadout", ["ContextBar.prototype."])

    def test_current_rendered_unconditionally_when_usage_present(self):
        body = self._readout_body()
        # the "current" span is built before the pct-gated branch, i.e. unconditionally once
        # `usage` itself is truthy -- not nested inside the `usage.pct !== null` check.
        cur_i = body.index('vtctxused')
        pct_gate_i = body.index("usage.pct !== null")
        self.assertLess(cur_i, pct_gate_i)

    def test_bar_gated_on_pct_not_on_limit(self):
        body = self._readout_body()
        self.assertIn("if (usage.pct !== null) {", body)

    def test_nothing_rendered_when_usage_is_null(self):
        body = self._readout_body()
        self.assertIn('if (!usage) {\n        el.innerHTML = "";', body)


class TestContextBarDocksToBottomOfBothMounts(unittest.TestCase):
    """The bar must appear in both the modal (openVT) and the standalone ?tty= view
    (bootStandalone), built AFTER the Terminal so its own container.innerHTML="" doesn't wipe it,
    and it must be torn down (poll interval + doc listener) whenever its terminal is."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_modal_builds_a_context_bar_after_the_terminal(self):
        term_i = self.src.index("var term = new Terminal(modalBodyEl, activeTty);")
        bar_i = self.src.index("activeBar = new ContextBar(modalBodyEl, sid, activeTty, mode,")
        self.assertLess(term_i, bar_i)

    def test_standalone_builds_a_context_bar_too(self):
        body = _body_until(self.src, "function bootStandalone", ["})();\n})();"])
        self.assertIn("new ContextBar(mount, sid, tty, mode,", body)

    def test_standalone_carries_sid_and_mode_in_the_new_tab_url(self):
        body = _body_until(self.src, "function openNewTab", ["window.ExtVT ="])
        self.assertIn('"&sid=" + encodeURIComponent(activeSid || "")', body)
        self.assertIn('"&mode=" + encodeURIComponent(activeMode || "")', body)

    def test_close_destroys_the_bar(self):
        body = _body_until(self.src, "function closeVT", ["function openNewTab"])
        self.assertIn("activeBar.destroy()", body)

    def test_destroy_stops_the_poll_and_the_document_listener(self):
        body = _body_until(self.src, "ContextBar.prototype.destroy", ["function openVT"])
        self.assertIn("clearInterval", self.src)   # inside _pollStop, referenced from destroy
        self.assertIn("_pollStop()", body)
        self.assertIn('document.removeEventListener("click", this._onDocClick)', body)


class TestContextBarUsesSharedTokensNotRawHtml(unittest.TestCase):
    """The readout must escape everything dynamic before it reaches innerHTML -- same untrusted-
    output discipline as _paintRow (requirement 6)."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_readout_escapes_the_tooltip_title(self):
        body = _body_until(self.src, "ContextBar.prototype._renderReadout", ["ContextBar.prototype."])
        self.assertIn("esc(title)", body)
        self.assertIn("esc(fmtTok(", body)


class TestContextBarCss(unittest.TestCase):
    """No second styling system -- the bar reuses the app's existing color/spacing tokens, and
    responsive rules exist for both breakpoints without hiding the interactive control."""

    def setUp(self):
        self.css = _read("ext_vt.css")

    def test_bar_classes_present(self):
        for cls in (".vtctxbar", ".vtmodelbtn", ".vtmodeldd", ".vtctxreadout"):
            self.assertIn(cls, self.css)

    def test_reuses_existing_design_tokens_not_new_colors(self):
        body = self.css[self.css.index(".vtctxbar {"):self.css.index(".vtmodelitem.cur::after")]
        self.assertIn("var(--chipbg)", body)
        self.assertIn("var(--line3)", body)

    def test_both_breakpoints_present(self):
        self.assertIn("min-width:601px) and (max-width:900px)", self.css)
        self.assertIn("max-width:600px", self.css)

    def test_model_button_never_hidden_by_breakpoint(self):
        # the model button itself must stay reachable at every width -- only the least essential
        # figure (cumulative total) may be dropped at the narrowest breakpoint.
        phone = self.css[self.css.index("@media(max-width:600px) {\n  .vtctxbar"):]
        phone = phone[:phone.index("}\n\n") + 1] if "}\n\n" in phone else phone
        self.assertNotIn(".vtmodelbtn { display: none", phone)
        self.assertNotIn(".vtmodeldd { display: none", phone)


if __name__ == "__main__":
    unittest.main()
