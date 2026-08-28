"""Tests for the Tier 3 CLIENT half — aitracker/web/ext_vt.{js,css} and the ext_launch.js rewire.

There is no JS engine in the stdlib, so — mirroring tests/test_term_launch.py's
TestButtonsFollowServerPolicy — these assert against the baked page and the raw asset source,
not against runtime behaviour. term_vt.py (the server-side emulator/routes) is a SEPARATE,
concurrently-built half and is deliberately not imported or required here.
"""
import os
import re
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
    fixed-size slice.

    `marker` is matched as a PREFIX of the target's signature, not a full-literal exact match: a
    trailing ") {" (a complete, closed parameter list) is stripped before searching, so a marker
    like "function Terminal(container, ttyId) {" actually locates the source via the shorter
    "function Terminal(container, ttyId" -- which still matches even after the real signature
    grows an added parameter (e.g. "function Terminal(container, ttyId, rendererSwitch) {"). The
    real function start is then found by scanning forward to the first "{" from there, so the
    returned body still opens at the true brace regardless of how long the parameter list got.
    This is what lets a constructor's signature grow without invalidating every test that locates
    its body by this literal (see ext_vt.js's own Terminal/XtermTerminal constructor comments).

    Substring hazard checked: a Terminal marker must never accidentally match inside
    XtermTerminal's signature. It can't -- "function " is followed directly by "XtermTerminal" in
    that constructor, never by "Terminal", so the prefix "function Terminal(" (or the fuller
    "function Terminal(container, ttyId") never occurs as a substring of
    "function XtermTerminal(container, ttyId, ...) {" at any position.
    """
    prefix = marker[:-3] if marker.endswith(") {") else marker
    start = src.index(prefix)
    brace = src.index("{", start)
    nxt = src.find("Terminal.prototype.", brace)
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
    the server's claude_attached answer (not on how the terminal was opened), and never steals
    keyboard focus from the terminal."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_model_ladder_is_hardcoded_with_reasoning(self):
        self.assertIn('var MODEL_LADDER = ["haiku", "sonnet", "opus", "fable"];', self.src)
        self.assertIn("HARDCODED", self.src)

    def test_gating_uses_server_attached_not_the_old_mode_proxy(self):
        # The user's actual regression: a plain `cwd` shell where they typed `claude` themselves
        # used to hide the switcher forever, because `mode === "resume" || mode === "new"` was
        # used as a proxy for "Claude is listening". That literal proxy must be GONE from the
        # constructor -- the only gate left is the server's own claude_attached answer.
        body = _body_until(self.src, "function ContextBar(", ["ContextBar.prototype."])
        self.assertNotIn('mode === "resume"', body)
        self.assertNotIn('mode === "new"', body)
        self.assertNotIn("showSwitcher", self.src)
        self.assertIn("this.attached = false;", body)

    # test_picking_a_model_sends_the_documented_inject_contract,
    # test_inject_failure_surfaces_a_toast_not_silence and test_button_never_takes_native_focus
    # were REMOVED here: they were grep-only checks of the inject-contract/toast/preventDefault
    # wiring, which no longer executes. Real behaviour is now proven by driving the actual click
    # path under Node -- see tests/test_term_vt_exec.py's TestContextBarModelInject (inject
    # contract + toast-on-failure) and TestContextBarFocusSafety (preventDefault actually fires).


class TestContextBarEffortSwitcher(unittest.TestCase):
    """The effort picker: mirrors the model switcher exactly -- same component, same idioms
    (hardcoded ladder, same inject contract, same toast-on-failure, same focus-safety pattern).

    Only the ladder's own literal contents/ordering/provenance stay here -- that is genuinely
    static-only (there is nothing to "execute" about an array literal). Every behavioural claim
    this class used to grep for (inject contract, toast-on-failure, focus safety, meta.effort
    labelling, current-item marking) is now proven by driving the real code under Node -- see
    tests/test_term_vt_exec.py's TestContextBarEffortInject, TestContextBarFocusSafety and
    TestContextBarEffortLabel."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_effort_ladder_is_hardcoded_low_to_high_with_provenance(self):
        ladder_line = 'var EFFORT_LADDER = ["low", "medium", "high", "xhigh", "max"];'
        self.assertIn(ladder_line, self.src)
        # Not effort levels at all -- must never be offered in the picker (the ARRAY itself, not
        # the surrounding comment, which legitimately names both to explain the exclusion).
        self.assertNotIn("ultracode", ladder_line)
        self.assertNotIn("auto", ladder_line)
        # Provenance recorded, mirroring MODEL_LADDER's own self-documenting comment.
        self.assertIn("2.1.247", self.src)
        self.assertIn("CONFIRMED", self.src)


# TestContextBarAttachGating was REMOVED here: every one of its four assertions was a grep-only
# check of behaviour that is now executed for real under Node --
# tests/test_term_vt_exec.py's TestContextBarAttachToggle (polling both endpoints off one timer,
# reacting to true->false->true across successive polls) and TestContextBarVisibility (the
# attached||hasUsage display rule). The one genuinely-static claim in the removed class -- that
# the old `this.showSwitcher` proxy is gone -- is already covered by
# TestContextBarModelSwitcher.test_gating_uses_server_attached_not_the_old_mode_proxy's own
# broader `assertNotIn("showSwitcher", self.src)` above, so nothing was lost.


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
        # ext_vt.js now picks between Terminal (grid) and XtermTerminal per the server-owned
        # `renderer` -- see the TRACKER_TERM_RENDERER switch -- so the construction call is
        # `new Cls(...)`, not a literal `new Terminal(...)`. The terminal is built into its own
        # dedicated `wrap` (see TestRendererSwitch below for why), not modalBodyEl directly; the
        # ordering guarantee this test pins (terminal built before the context bar) is unchanged.
        term_i = self.src.index("var term = new Cls(wrap, activeTty, {")
        bar_i = self.src.index("activeBar = new ContextBar(modalBodyEl, sid, activeTty, mode,")
        self.assertLess(term_i, bar_i)

    def test_standalone_builds_a_context_bar_too(self):
        body = _body_until(self.src, "function bootStandalone", ["})();\n})();"])
        self.assertIn("new ContextBar(mount, sid, tty, mode,", body)

    def test_standalone_carries_sid_and_mode_in_the_new_tab_url(self):
        body = _body_until(self.src, "function openNewTab",
                            ['// ===== "Manage terminals" panel'])
        self.assertIn('"&sid=" + encodeURIComponent(activeSid || "")', body)
        self.assertIn('"&mode=" + encodeURIComponent(activeMode || "")', body)

    def test_close_destroys_the_bar(self):
        body = _body_until(self.src, "function closeVT", ["function openNewTab"])
        self.assertIn("activeBar.destroy()", body)

    # test_destroy_stops_the_poll_and_the_document_listener was REMOVED here: it grepped for
    # `clearInterval`/`_pollStop()`/`removeEventListener` appearing in destroy()'s source text.
    # The real behaviour -- that destroy() actually stops the poll (no further fetches occur
    # afterward) and actually removes the document click listener -- is now proven by executing
    # the real destroy() under Node: tests/test_term_vt_exec.py's
    # TestContextBarTeardown.test_destroy_stops_polling_and_removes_the_doc_listener.


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
        for cls in (".vtctxbar", ".vtmodelbtn", ".vtmodeldd", ".vtctxreadout",
                    ".vteffortbtn", ".vteffortdd", ".vtswitchers", ".vtswitcher"):
            self.assertIn(cls, self.css)

    def test_reuses_existing_design_tokens_not_new_colors(self):
        body = self.css[self.css.index(".vtctxbar {"):self.css.index(".vtmodelitem.cur::after")]
        self.assertIn("var(--chipbg)", body)
        self.assertIn("var(--line3)", body)
        # the effort button/dropdown/item rules are GROUPED with the model ones (comma selectors),
        # not a forked second copy of the chrome -- both share these same literal declarations.
        self.assertIn(".vtmodelbtn, .vteffortbtn {", body)
        self.assertIn(".vtmodeldd, .vteffortdd {", body)

    def test_dropdown_is_anchored_to_its_own_switcher_not_the_bar(self):
        # each picker's dropdown is positioned relative to ITS OWN wrap (.vtswitcher), not a
        # second hardcoded pixel offset on .vtctxbar -- robust to "opus" vs "xhigh" label widths.
        self.assertIn(".vtswitcher { position: relative", self.css)
        dd = self.css[self.css.index(".vtmodeldd, .vteffortdd {"):self.css.index(".vtmodeldd.show")]
        self.assertIn("left: 0;", dd)
        self.assertNotIn("left: 10px;", dd)

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

    def test_effort_button_never_hidden_by_breakpoint(self):
        phone = self.css[self.css.index("@media(max-width:600px) {\n  .vtctxbar"):]
        phone = phone[:phone.index("}\n\n") + 1] if "}\n\n" in phone else phone
        self.assertNotIn(".vteffortbtn { display: none", phone)
        self.assertNotIn(".vteffortdd { display: none", phone)
        # explicitly present (grouped with the model button) rather than simply absent-by-luck.
        self.assertIn(".vtmodelbtn, .vteffortbtn { padding: 3px 6px; }", phone)

    def test_switchers_pinned_left_so_effort_dropdown_cannot_reach_the_right_edge(self):
        # Adversarial review flagged (unproven) that the effort dropdown -- second in the row,
        # anchored to a button further right than the old single picker ever sat -- might overflow
        # a narrow viewport's right edge, since neither dropdown has a max-width or right-edge
        # fallback. EMPIRICALLY SETTLED (live browser, getBoundingClientRect against the viewport
        # and .vtctxbar) at 375x812, 600x800, 768x1024 and a 1280-wide desktop, even forcing the
        # widest ladder label ("xhigh") onto the effort button: no overflow at any width. The
        # reason is structural, not incidental, so THAT structure is what this pins -- not a
        # max-width band-aid nothing measured requires. `.vtswitchers` is `flex: 0 0 auto` and is
        # appended to `.vtctxbar` BEFORE `.vtctxreadout` (a flex row, so DOM order is visual
        # order), which keeps both pickers pinned at the bar's LEFT edge regardless of label width;
        # `.vtctxreadout` is `flex: 1 1 auto` with `overflow: hidden` and is what absorbs a narrow
        # bar by truncating, never by pushing the switchers rightward. Break any one of these and
        # the empirical no-overflow result above no longer holds.
        bar = self.css[self.css.index(".vtctxbar {"):self.css.index(".vtswitchers {")]
        self.assertIn("display: flex;", bar)   # a flex row -> DOM order is left-to-right visual order
        self.assertIn(".vtswitchers { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }",
                       self.css)
        readout = self.css[self.css.index(".vtctxreadout {"):self.css.index(".vtctxbarwrap {")]
        self.assertIn("flex: 1 1 auto;", readout)
        self.assertIn("overflow: hidden;", readout)
        # switchers must appear BEFORE the readout in JS's DOM-assembly order (bar.appendChild
        # calls), not just in the CSS -- otherwise "first flex child" above is meaningless.
        js = _read("ext_vt.js")
        self.assertLess(js.index("switchers.className = \"vtswitchers\";\n    switchers.style.display"),
                         js.index("readout.className = \"vtctxreadout\";"))


class TestZoomControlOverlapFix(unittest.TestCase):
    """The layout bug from the user's screenshot: the A-/A+ zoom controls used to be an
    absolutely-positioned `.vtzoom` overlay pinned inside `.vtpane`'s own top-right corner
    (top:4px;right:6px), sitting directly on top of row 0's real content. The fix moves it to its
    own `.vttoolbar` flex row, appended as a sibling BEFORE the pane -- both in CSS (no more
    position:absolute over the pane) and in JS (no more `pane.appendChild` of the zoom element),
    for BOTH renderers."""

    def setUp(self):
        self.css = _read("ext_vt.css")
        self.js = _read("ext_vt.js")

    def test_old_overlapping_vtzoom_rule_is_gone(self):
        # the OLD class name/selector must not appear at all -- this is the actual regression
        # bar: if a future edit reintroduces `.vtzoom {` (the absolutely-positioned overlay), this
        # fails even if everything else below still passes.
        self.assertNotIn(".vtzoom {", self.css)
        self.assertNotIn(".vtzoom span", self.css)

    def test_new_toolbar_rule_exists_and_is_not_absolutely_positioned_over_the_pane(self):
        self.assertIn(".vttoolbar {", self.css)
        self.assertIn(".vtzoombtn {", self.css)
        block = self.css[self.css.index(".vttoolbar {"):self.css.index(".vtzoombtn {")]
        # the whole POINT of the fix: no `position: absolute` pinning it inside the pane's box.
        self.assertNotIn("position: absolute", block)

    def test_toolbar_is_built_once_and_shared_by_both_renderers(self):
        self.assertIn("function buildToolbar(", self.js)
        # both Terminal's and XtermTerminal's constructors call the SAME helper -- one fix, not
        # two reimplementations that could drift back apart.
        self.assertEqual(self.js.count("buildToolbar("), 3,   # 1 definition + 2 call sites
                          "buildToolbar should be defined once and called from both renderers")

    def test_zoom_element_is_no_longer_appended_inside_the_pane(self):
        # the old bug, structurally: the toolbar used to be a CHILD of `.vtpane`.
        self.assertNotIn("pane.appendChild(zoomEl)", self.js)
        self.assertNotIn("var zoomEl = document.createElement", self.js)

    def test_toolbar_is_appended_as_a_sibling_before_the_pane_in_both_constructors(self):
        term_body = _function_body(self.js, "function Terminal(container, ttyId) {")
        self.assertIn("container.appendChild(toolbarEl)", term_body)
        self.assertIn("container.appendChild(pane)", term_body)
        self.assertLess(term_body.index("container.appendChild(toolbarEl)"),
                         term_body.index("container.appendChild(pane)"))

        xterm_start = self.js.index("function XtermTerminal(container, ttyId")
        xterm_body = self.js[xterm_start:self.js.index("XtermTerminal.prototype.attach")]
        self.assertIn("container.appendChild(toolbarEl)", xterm_body)
        self.assertIn("container.appendChild(pane)", xterm_body)


class TestShortViewportFooterFix(unittest.TestCase):
    """Short-viewport fix (this session): `.vtctxbar` (the model-selector + token-readout footer)
    used to be laid out entirely past `.modal`'s clipped bottom edge on any window short enough
    that app.css's `.modal { max-height: 88vh; overflow: hidden }` left less room than two fixed
    min-heights in this file (`.vtmodal .mb.vtmb`'s 360px, `.vtpane`'s 300px) together demanded --
    with no scroll affordance to reach it either, the footer was simply gone. Both floors must be
    able to yield to a starved container instead of forcing it to overflow, for BOTH renderers
    (.vtpane is shared by the grid pane and .vtxpane's xterm.js pane alike)."""

    def setUp(self):
        self.css = _read("ext_vt.css")

    def test_vtmb_no_longer_carries_a_fixed_360px_floor(self):
        self.assertNotIn("min-height: 360px", self.css)
        start = self.css.index(".vtmodal .mb.vtmb {")
        rule = self.css[start:self.css.index("}", start)]
        self.assertIn("min-height: 0", rule)

    def test_vtpane_base_rule_can_shrink_below_300px(self):
        # the BASE (non-media-query, non-fullscreen) `.vtpane` rule -- the one actually in force
        # inside a modal wider than 600px, exactly the case the short-viewport repro hit (neither
        # the max-width:600px mobile override nor #ext_vt.vtfull's own min-height:0 applied there).
        start = self.css.index(".vtpane {")
        block = self.css[start:self.css.index("}", start)]
        self.assertNotIn("min-height: 300px;", block,
                          "a bare 300px floor refuses to flex-shrink inside a height-capped .modal")
        self.assertIn("min-height: min(300px,", block,
                       "expected a shrinkable min(300px, <vh-based>) floor, mirroring the "
                       "max-width:600px rule's own vh/dvh idiom below")

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn("min-height: 0", page)
        self.assertIn("min-height: min(300px,", page)
        self.assertNotIn("min-height: 360px", page)


class TestXtermRendererSwitch(unittest.TestCase):
    """The client half of TRACKER_TERM_RENDERER: openVT()/bootStandalone() must read which
    renderer to build from the SERVER (POST /api/term/pty's `renderer` field, or GET
    /api/term/renderer for a reconnecting standalone tab) and never invent the choice locally
    (conventions rule 5)."""

    def setUp(self):
        self.js = _read("ext_vt.js")

    def test_xterm_terminal_class_exists(self):
        self.assertIn("function XtermTerminal(container, ttyId", self.js)
        for method in ("attach", "measureAndResize", "destroy", "focus"):
            self.assertIn("XtermTerminal.prototype.%s = function" % method, self.js)

    def test_openvt_reads_renderer_from_the_pty_response_not_locally(self):
        body = _function_body(self.js, "function openVT(sid, mode) {")
        self.assertIn('res.j.renderer === "xterm"', body)
        self.assertIn("var Cls = activeRenderer === \"xterm\" ? XtermTerminal : Terminal;", body)

    def test_standalone_falls_back_to_the_dedicated_renderer_route(self):
        body = _body_until(self.js, "function bootStandalone", ["})();\n})();"])
        self.assertIn('fetch("/api/term/renderer")', body)
        self.assertIn('renderer === "xterm" ? XtermTerminal : Terminal', body)

    def test_new_tab_url_relays_the_server_chosen_renderer(self):
        body = _body_until(self.js, "function openNewTab",
                            ['// ===== "Manage terminals" panel'])
        self.assertIn('"&renderer=" + encodeURIComponent(activeRenderer || "grid")', body)

    def test_lazy_asset_loader_targets_the_vendored_paths_not_a_cdn(self):
        body = _function_body(self.js, "function _loadXtermAssets() {") \
            if "function _loadXtermAssets() {" in self.js else self.js
        self.assertIn('"/vendor/xterm.js"', self.js)
        self.assertIn('"/vendor/xterm.css"', self.js)
        self.assertIn('"/vendor/addon-fit.js"', self.js)
        for host in ("cdn.", "unpkg.com", "jsdelivr", "cdnjs"):
            self.assertNotIn(host, self.js)

    def test_raw_stream_uses_the_dedicated_raw_route(self):
        self.assertIn('"/api/term/raw?tty="', self.js)

    def test_context_bar_focus_works_for_either_renderer_object(self):
        # ContextBar's getInput callback hands back the TERMINAL object (not a raw DOM node) at
        # both call sites -- both Terminal and XtermTerminal expose .focus(), so _focusTerminal's
        # existing `input.focus()` call works unmodified for either.
        self.assertIn("function () { return term; }", self.js)
        self.assertNotIn("function () { return term.input; }", self.js)


class TestForkedStatusIndicator(unittest.TestCase):
    """POST /api/term/pty gains a `forked` field (true/false) indicating if the terminal is a
    copy of a background agent. The client must surface this unmistakably in both modal and
    standalone views, and read it defensively (if absent, behave as false)."""

    def setUp(self):
        self.js = _read("ext_vt.js")

    def test_forked_is_stored_as_active_module_variable(self):
        self.assertIn("var activeForked = false", self.js)

    def test_fork_chip_element_created_in_buildoverlay(self):
        self.assertIn("modalForkChip = document.createElement", self.js)
        self.assertIn('modalForkChip.className = "vtforkchip"', self.js)

    def test_fork_chip_shown_when_forked_true(self):
        self.assertIn("activeForked = !!res.j.forked", self.js)
        self.assertIn("if (modalForkChip) modalForkChip.style.display = activeForked ? \"\" : \"none\";", self.js)

    def test_fork_chip_hidden_on_close(self):
        body = _body_until(self.js, "function closeVT()", ["function openNewTab"])
        self.assertIn("if (modalForkChip) modalForkChip.style.display = \"none\";", body)

    def test_forked_parameter_passed_to_standalone_view(self):
        self.assertIn('"&forked=" + (activeForked ? "1" : "0")', self.js)

    def test_standalone_reads_forked_from_url_defensively(self):
        body = _body_until(self.js, "function bootStandalone", ["})();\n})();"])
        self.assertIn('var standaloneForked = qs.get("forked") === "1";', body)

    def test_standalone_shows_fork_indicator_in_status_line(self):
        body = _body_until(self.js, "function bootStandalone", ["})();\n})();"])
        self.assertIn("standaloneForked", body)
        self.assertIn('chip.className = "vtstatus-fork"', body)


class TestServerNoticeAdvisory(unittest.TestCase):
    """POST /api/term/pty gains a `notice` field (string or null) with a human-readable advisory
    warning. The client must display it as a muted advisory line (not red/error), escape it, and
    read it defensively (if absent, render nothing)."""

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def test_notice_stored_as_active_module_variable(self):
        self.assertIn("activeNotice = null", self.js)  # part of comma-separated variable declaration

    def test_notice_element_created_in_buildoverlay(self):
        self.assertIn("modalNoticeEl = document.createElement", self.js)

    def test_notice_extracted_from_response_defensively(self):
        # activeNotice gets the string if notice is present, or null otherwise
        self.assertIn('activeNotice = (typeof res.j.notice === "string") ? res.j.notice : null;', self.js)

    def test_notice_text_is_escaped_not_inserted_raw_html(self):
        body = _body_until(self.js, "if (activeNotice) {", ["} else if (modalNoticeEl"])
        # textContent property escapes; innerHTML with pre-created elements is safe
        self.assertIn("noticeText.textContent = activeNotice", body)
        self.assertNotIn("noticeText.innerHTML = activeNotice", body)

    def test_notice_renders_nothing_when_null(self):
        # When activeNotice is null/falsy, the else clause removes the notice element from DOM
        self.assertIn("} else if (modalNoticeEl && modalNoticeEl.parentNode) {", self.js)
        self.assertIn("modalNoticeEl.parentNode.removeChild(modalNoticeEl);", self.js)

    def test_notice_removed_on_close(self):
        body = _body_until(self.js, "function closeVT()", ["function openNewTab"])
        self.assertIn("activeNotice = null;", body)
        self.assertIn("if (modalNoticeEl && modalNoticeEl.parentNode)", body)
        self.assertIn("modalNoticeEl.parentNode.removeChild(modalNoticeEl);", body)

    def test_notice_passed_to_standalone_view_in_url(self):
        self.assertIn('(activeNotice ? "&notice=" + encodeURIComponent(activeNotice) : "")', self.js)

    def test_standalone_reads_notice_from_url(self):
        body = _body_until(self.js, "function bootStandalone", ["})();\n})();"])
        self.assertIn('var standaloneNotice = qs.get("notice") || null;', body)

    def test_standalone_displays_notice_element(self):
        body = _body_until(self.js, "function bootStandalone", ["})();\n})();"])
        self.assertIn('if (standaloneNotice) {', body)
        self.assertIn('noticeEl.className = "vtnotice"', body)
        self.assertIn("noticeText.textContent = standaloneNotice", body)

    def test_notice_css_class_exists_and_is_muted_not_error(self):
        self.assertIn(".vtnotice {", self.css)
        # Extract just the .vtnotice rule block to check its styling
        notice_start = self.css.index(".vtnotice {")
        notice_end = self.css.index("}", notice_start) + 1
        notice_block = self.css[notice_start:notice_end]
        # must be visually subtle (muted) not alarming (red/error)
        self.assertIn("color: var(--dim);", notice_block)
        self.assertNotIn("color: var(--red);", notice_block)
        # advisory line styling (bg, border, padding, font-size)
        self.assertIn("background: var(--side);", notice_block)
        self.assertIn("border-bottom: 1px solid var(--line3);", notice_block)


class TestForkedAndNoticeResponsiveness(unittest.TestCase):
    """The fork chip and notice must work at all viewport widths (phone, tablet, desktop)
    without overflowing or pushing content off-screen."""

    def setUp(self):
        self.css = _read("ext_vt.css")

    def test_fork_chip_has_responsive_styling(self):
        # The chip should be small and use white-space: nowrap to prevent wrapping
        self.assertIn(".vtforkchip {", self.css)
        self.assertIn("white-space: nowrap;", self.css)
        # Font size kept small on all breakpoints
        self.assertIn("font-size: 11px;", self.css)

    def test_notice_reflows_on_narrow_viewports(self):
        # The notice element should be responsive and not overflow
        self.assertIn(".vtnotice {", self.css)
        # Uses monospace but normal flow (not fixed width)
        self.assertIn("font-family: 'JetBrains Mono', monospace;", self.css)


class TestAsyncNoticesFromScreenFrame(unittest.TestCase):
    """POST /api/term/screen (SSE) now carries async notices in each frame. The client must:
    - Consume and dedupe by seq
    - Render multiple notices (capped at 3)
    - Escape text safely
    - Handle missing/malformed notices defensively
    - Reset state when terminal changes"""

    def setUp(self):
        self.js = _read("ext_vt.js")

    def test_terminal_constructor_initializes_notice_tracking(self):
        # Terminal must set up _noticeHighestSeq and _noticeEls on construction
        body = _function_body(self.js, "function Terminal(container, ttyId) {")
        self.assertIn("this._noticeHighestSeq = -1;", body)
        self.assertIn("this._noticeEls = [];", body)

    def test_applyPatch_processes_notices_array_defensively(self):
        # _applyPatch must read notices array only if it's an Array
        body = _function_body(self.js, "Terminal.prototype._applyPatch = function")
        self.assertIn("Array.isArray(notices)", body)

    def test_applyPatch_extracts_seq_and_text_from_each_notice(self):
        body = _function_body(self.js, "Terminal.prototype._applyPatch = function")
        # Must extract seq as number and text as string
        self.assertIn('typeof notice.seq === "number"', body)
        self.assertIn('typeof notice.text === "string"', body)

    def test_applyPatch_dedupes_by_seq(self):
        # Only display notices with seq > _noticeHighestSeq; update high water mark
        body = _function_body(self.js, "Terminal.prototype._applyPatch = function")
        self.assertIn("seq > this._noticeHighestSeq", body)
        self.assertIn("this._noticeHighestSeq = seq", body)

    def test_applyPatch_calls_displayNotice_for_new_notices(self):
        body = _function_body(self.js, "Terminal.prototype._applyPatch = function")
        self.assertIn("this._displayNotice(text)", body)

    def test_displayNotice_method_exists(self):
        self.assertIn("Terminal.prototype._displayNotice = function", self.js)

    def test_displayNotice_creates_vtnotice_div(self):
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn('el.className = "vtnotice"', body)

    def test_displayNotice_escapes_text_via_textContent(self):
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("span.textContent = text;", body)
        self.assertNotIn("span.innerHTML = text;", body)

    def test_displayNotice_inserts_as_sibling_before_pane(self):
        # Notices are now inserted as siblings BEFORE the pane (not as children of it) to avoid
        # consuming the pane's vertical space and clipping rows. The insertion uses
        # pane.parentNode.insertBefore(el, pane), placing notices in the same flex container.
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("this.pane.parentNode.insertBefore(el, this.pane)", body)

    def test_displayNotice_tracks_elements_in_noticeEls_array(self):
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("this._noticeEls.push(el);", body)

    def test_displayNotice_caps_stacked_notices_at_3(self):
        # When 4th notice arrives, oldest is removed
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("var maxNotices = 3", body)
        self.assertIn("while (this._noticeEls.length > maxNotices)", body)
        self.assertIn("this._noticeEls.shift()", body)

    def test_destroy_cleans_up_async_notices(self):
        # When terminal is destroyed, remove all async notice DOM elements and reset state
        body = _function_body(self.js, "Terminal.prototype.destroy = function")
        self.assertIn("this._noticeEls = [];", body)
        self.assertIn("this._noticeHighestSeq = -1;", body)
        # Check that it removes elements from DOM
        self.assertIn("el.parentNode.removeChild(el)", body)

    def test_sync_notice_path_still_works(self):
        # The synchronous notice from POST /api/term/pty response (activeNotice) must still render
        # This ensures backward compat with older servers not sending async notices
        self.assertIn("activeNotice = (typeof res.j.notice === \"string\") ? res.j.notice : null;", self.js)


class TestAsyncNoticesMovedOutOfPane(unittest.TestCase):
    """Layout defect fix: notices used to be inserted as children of .vtpane, consuming its
    vertical space and clipping rows. They are now siblings of .vtpane, and measureAndResize()
    is called whenever the notice list changes to renegotiate the row count."""

    def setUp(self):
        self.js = _read("ext_vt.js")

    def test_notices_inserted_as_pane_siblings_not_pane_children(self):
        # The key fix: use pane.parentNode.insertBefore(el, pane) not rowsEl.parentNode.insertBefore
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("this.pane.parentNode.insertBefore(el, this.pane)", body)
        # Old code path must be gone entirely
        self.assertNotIn("rowsEl.parentNode.insertBefore(el, rowsEl)", body)

    def test_displayNotice_calls_measureAndResize_after_adding(self):
        # After adding a notice, the pane's available height has decreased (notices consume space
        # in the flex container). measureAndResize() recalculates cols/rows for the new pane height.
        body = _function_body(self.js, "Terminal.prototype._displayNotice = function")
        self.assertIn("this.measureAndResize()", body)

    def test_destroy_calls_measureAndResize_if_notices_were_shown(self):
        # When the terminal is destroyed and notices exist, removing them frees up space in the
        # container. Though the terminal itself is going away, the resize ensures consistency.
        body = _function_body(self.js, "Terminal.prototype.destroy = function")
        self.assertIn("measureAndResize()", body)

    def test_notice_css_is_flex_container_item(self):
        # .vtnotice must be `flex: 0 0 auto` so it doesn't consume the pane's shrinking space
        css = _read("ext_vt.css")
        notice_start = css.index(".vtnotice {")
        notice_end = css.index("}", notice_start) + 1
        notice_block = css[notice_start:notice_end]
        self.assertIn("flex: 0 0 auto;", notice_block,
                      "notices must be flex items with fixed height, not flex: 1")


class TestCapReclaimBlock(unittest.TestCase):
    """Hitting the concurrent-terminal cap must be recoverable from the browser: the 429 body
    names the ttys holding the slots, and the modal offers a kill-and-retry per row. Before this,
    the only exit was waiting out the 30-minute IDLE_TIMEOUT."""

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def test_429_takes_the_reclaim_branch_not_the_dead_end_string(self):
        body = _body_until(self.js, "function openVT(", ["window.ExtVT ="])
        self.assertIn("res.status === 429", body)
        self.assertIn("renderCapBlock(sid, mode, res.j, gen)", body)

    def test_reclaim_rows_post_to_the_close_route_and_retry_the_open(self):
        block = _body_until(self.js, "function renderCapBlock(", ["function openVT("])
        self.assertIn('"/api/term/close"', block)
        self.assertIn('JSON.stringify({ tty: t.tty })', block)
        self.assertIn("openVT(sid, mode)", block)

    def test_the_retry_does_not_reopen_a_dismissed_or_superseded_modal(self):
        """The retry is on a 250ms timer, so it must re-check on the way in: the user may have
        closed the modal (don't re-open it behind their back) or switched to another session
        (don't hijack it back). Same supersede discipline as openVT's own activeSid guard."""
        block = _body_until(self.js, "function renderCapBlock(", ["function openVT("])
        self.assertIn("if (gen !== openGen) return;", block)
        self.assertIn('overlay.style.display === "none"', block)

    def test_one_click_latches_the_whole_block_not_just_its_own_button(self):
        """Each click schedules its own retry, and openVT's destroy() closes the client SSE
        WITHOUT killing the pty it replaces. So two clicks would attach two terminals and orphan
        the first one viewer-less for the full IDLE_TIMEOUT — freeing two slots and immediately
        re-filling them. The latch must cover every row, and lift again only on failure."""
        block = _body_until(self.js, "function renderCapBlock(", ["function openVT("])
        self.assertIn('wrap.querySelectorAll(".vtcapx")', block)
        self.assertNotIn("x.disabled = true;", block)     # per-button latch is the bug
        self.assertIn("b.disabled = true;", block)
        self.assertIn("var unlatch = function ()", block)
        self.assertIn(".catch(unlatch)", block)

    def test_a_superseded_open_hands_its_pty_back_instead_of_leaking_it(self):
        """openVT's supersede branch used to drop a tty the server had already spawned: live,
        viewer-less and invisible for the full IDLE_TIMEOUT. Reached most easily from the cap
        block itself — the user frees a slot, dismisses the modal mid-retry, and silently gains a
        hidden terminal instead. The abandon path must close what it abandons."""
        body = _body_until(self.js, "function openVT(", ["window.ExtVT ="])
        i = body.index("if (gen !== openGen) {")
        supersede = body[i:body.index("if (!res.ok", i)]      # just the supersede branch
        self.assertIn('"/api/term/close"', supersede)
        self.assertIn("tty: res.j.tty", supersede)

    def test_supersede_is_keyed_on_a_generation_not_on_the_session_id(self):
        """`activeSid !== sid` cannot see a SAME-session supersede — two opens for one sid, or two
        modes. Both responses passed it, both attached, and the second overwrote the first
        terminal without closing its SSE, so pt.viewers never returned to 0 and the server could
        not idle-reap that pty for the life of the tab. A counter cannot miss that case."""
        self.assertIn("var openGen = 0;", self.js)
        body = _body_until(self.js, "function openVT(", ["window.ExtVT ="])
        self.assertIn("var gen = ++openGen;", body)
        self.assertIn("if (gen !== openGen) {", body)
        self.assertNotIn("if (activeSid !== sid) return;", body)   # the guard this replaced

    def test_dismissing_the_modal_invalidates_an_in_flight_open(self):
        """The regression the generation token could have introduced. `activeSid !== sid` got this
        for free — closeVT nulls activeSid — so an open still in flight when the user hits Escape
        was dropped. A counter loses that unless closeVT bumps it, and without the bump the
        response would attach a terminal AND an SSE behind a hidden overlay, pinning a live pty
        with a viewer nobody can see or reach."""
        close_body = _body_until(self.js, "function closeVT(", ["function openNewTab("])
        self.assertIn("openGen++;", close_body)

    def test_cap_message_is_the_servers_text_not_a_client_copy_of_the_number(self):
        """Conventions rule 5: the client renders server policy, never re-derives it. The cap
        number must appear nowhere in the JS."""
        block = _body_until(self.js, "function renderCapBlock(", ["function openVT("])
        self.assertIn("j.error", block)
        for hardcoded in ("max 4", "max 12", "MAX_TERMS", "MAX_PTYS"):
            self.assertNotIn(hardcoded, self.js)

    def test_reclaim_rows_are_usable_on_phone_and_tablet(self):
        """No fixed widths, no host gating -- the cap is hit from a tunnelled phone as readily as
        from localhost desktop, and the kill button must stay tappable there."""
        self.assertIn(".vtcaprow {", self.css)
        self.assertIn("min-width: 0;", self.css)          # the label ellipsises instead of overflowing
        self.assertIn("text-overflow: ellipsis;", self.css)
        self.assertIn(".vtcapx {", self.css)
        self.assertIn("min-height: 28px;", self.css)      # a real tap target
        self.assertNotIn("location.hostname", self.js)

    def test_reclaim_block_survives_into_the_served_page(self):
        page = build_page()
        self.assertIn("renderCapBlock", page)
        self.assertIn("/api/term/close", page)
        self.assertIn(".vtcapx", page)


class TestCursorSitsOnTheSameOriginAsTheRows(unittest.TestCase):
    """The synthetic cursor drew one padding up-and-left of the character it marks.

    `.vtcursor` is `position:absolute` inside `.vtpane`, so its top:0/left:0 origin is the pane's
    PADDING box, while `.vtrows` is in normal flow and starts at the CONTENT box -- 8px down and
    10px right of that. `_layoutCursor`'s translate() was pure `col*cellW, row*cellH`, so the block
    floated between the previous line and the previous character. The same padding was also never
    subtracted in `computeColsRows` (padX/padY were declared and then unused), so cols/rows were
    measured against the unpadded box and overcounted -- the bottom row the cursor usually sits on
    was clipped by .vtpane's overflow:hidden. Both halves read ONE source of truth: the pane's own
    computed padding."""

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def _ccr(self):
        return _body_until(self.js, "function computeColsRows(", ["function debounce("])

    def test_the_premise_still_holds_absolute_cursor_in_a_padded_pane(self):
        # If either of these changes, the offset below is the thing to revisit -- so pin them.
        pane = self.css[self.css.index(".vtpane {"):]
        self.assertIn("padding: 8px 10px;", pane[:pane.index("}")])
        cursor = self.css[self.css.index(".vtcursor {"):]
        self.assertIn("position: absolute;", cursor[:cursor.index("}")])

    def test_cursor_translate_adds_the_pane_padding(self):
        body = _function_body(self.js, "Terminal.prototype._layoutCursor")
        line = body[body.index('"translate("'):]
        line = line[:line.index(";")]
        self.assertIn("this.padX + c * this.cellW", line)
        self.assertIn("this.padY + r * this.cellH", line)

    def test_padding_comes_from_the_computed_style_not_a_second_hardcoded_copy(self):
        ccr = self._ccr()
        self.assertIn("getComputedStyle(pane)", ccr)
        self.assertIn("cs.paddingLeft", ccr)
        self.assertIn("cs.paddingTop", ccr)
        self.assertNotIn("padX = 20", ccr)   # the old guessed constants are gone
        self.assertNotIn("padY = 16", ccr)

    def test_cols_and_rows_are_measured_against_the_content_box(self):
        ccr = self._ccr()
        for line in ccr.splitlines():
            s = line.strip()
            if s.startswith("var innerW ="):
                self.assertTrue(s.endswith("- padX;"), s)
            if s.startswith("var innerH ="):
                self.assertTrue(s.endswith("- padY;"), s)
        self.assertIn("var innerW =", ccr)
        self.assertIn("var innerH =", ccr)

    def test_the_measurement_hands_the_padding_to_the_cursor(self):
        # computeColsRows returns it, measureAndResize stores it -- otherwise this.padX is the
        # constructor's 0 forever and the translate() above silently reverts to the old bug.
        self.assertIn("padX: padL, padY: padT", self._ccr())
        body = _function_body(self.js, "Terminal.prototype.measureAndResize")
        self.assertIn("this.padX = m.padX; this.padY = m.padY;", body)
        self.assertIn("this.padX = 0; this.padY = 0;", self.js)   # safe default pre-measure

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        # ext_vt.js is inlined into PAGE at startup -- assert against what is actually served.
        page = build_page()
        self.assertIn("this.padX + c * this.cellW", page)
        self.assertIn("padX: padL, padY: padT", page)


class TestModifierAwareKeyEncoding(unittest.TestCase):
    """keyToBytes used to ignore modifiers on every non-letter key -- Ctrl+ArrowLeft fell through
    to the unmodified \\x1b[D, Shift+Enter/Alt+Enter fell through to a plain \\r (so Claude Code's
    newline-without-submit SUBMITS instead), and F1-F12/Ctrl+Space were swallowed entirely (fell
    through to `return null`). Fixed per xterm ctlseqs (invisible-island.net/xterm/ctlseqs/
    ctlseqs.html), Patch #411: a modifier parameter Pm = 1 + 1*Shift + 2*Alt + 4*Ctrl + 8*Meta,
    appended only when some modifier is actually held."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def _key_body(self):
        return _body_until(self.src, "function keyToBytes(ev) {", ["function b64utf8("])

    def test_modifier_formula_is_present(self):
        body = self._key_body()
        self.assertIn(
            "var pm = 1 + (ev.shiftKey ? 1 : 0) + (ev.altKey ? 2 : 0) + "
            "(ev.ctrlKey ? 4 : 0) + (ev.metaKey ? 8 : 0);",
            body,
        )

    def test_pm_equals_one_emits_the_plain_form(self):
        # Pm === 1 (nothing held) must NOT get a ";1" suffix -- the plain form stays exactly what
        # it was before this change, for every modified-key case below.
        body = self._key_body()
        self.assertIn("var plain = (pm === 1);", body)
        self.assertIn('case "ArrowLeft": return plain ? "\\x1b[D" : "\\x1b[1;" + pm + "D";', body)

    def test_ctrl_left_shaped_cursor_output_pins_the_dynamic_construction(self):
        # Pin the actual expression the code builds (not a hardcoded "\x1b[1;5D" string) -- this
        # is what makes Ctrl+Left emit \x1b[1;5D, Shift+Up emit \x1b[1;2A, Alt+Right emit
        # \x1b[1;3C, all from the SAME construction with a different `pm`.
        body = self._key_body()
        self.assertIn('case "ArrowUp": return plain ? "\\x1b[A" : "\\x1b[1;" + pm + "A";', body)
        self.assertIn('case "ArrowDown": return plain ? "\\x1b[B" : "\\x1b[1;" + pm + "B";', body)
        self.assertIn('case "ArrowRight": return plain ? "\\x1b[C" : "\\x1b[1;" + pm + "C";', body)

    def test_home_end_tilde_keys_also_take_the_modified_form(self):
        body = self._key_body()
        self.assertIn('case "Home": return plain ? "\\x1b[H" : "\\x1b[1;" + pm + "H";', body)
        self.assertIn('case "End": return plain ? "\\x1b[F" : "\\x1b[1;" + pm + "F";', body)
        self.assertIn('case "PageUp": return plain ? "\\x1b[5~" : "\\x1b[5;" + pm + "~";', body)
        self.assertIn('case "PageDown": return plain ? "\\x1b[6~" : "\\x1b[6;" + pm + "~";', body)
        self.assertIn('case "Delete": return plain ? "\\x1b[3~" : "\\x1b[3;" + pm + "~";', body)
        self.assertIn('case "Insert": return plain ? "\\x1b[2~" : "\\x1b[2;" + pm + "~";', body)

    def test_f1_to_f4_use_ss3_plain_and_csi_with_leading_one_modified(self):
        body = self._key_body()
        self.assertIn('case "F1": return plain ? "\\x1bOP" : "\\x1b[1;" + pm + "P";', body)
        self.assertIn('case "F2": return plain ? "\\x1bOQ" : "\\x1b[1;" + pm + "Q";', body)
        self.assertIn('case "F3": return plain ? "\\x1bOR" : "\\x1b[1;" + pm + "R";', body)
        self.assertIn('case "F4": return plain ? "\\x1bOS" : "\\x1b[1;" + pm + "S";', body)

    def test_f5_to_f12_tilde_numbers_are_all_present(self):
        # F1-F12 were previously swallowed entirely (fell through to `return null`) -- this is a
        # brand-new capability, not a modifier fix to an existing one.
        body = self._key_body()
        for n in (15, 17, 18, 19, 20, 21, 23, 24):
            self.assertIn('"\\x1b[%d~" : "\\x1b[%d;" + pm + "~";' % (n, n), body)

    def test_alt_enter_sends_esc_prefixed_form_plain_enter_still_sends_cr(self):
        body = self._key_body()
        self.assertIn(
            'if (ev.altKey && !ev.ctrlKey && !ev.metaKey) return "\\x1b\\r";', body
        )
        # the Enter case's fallthrough (Shift+Enter, Ctrl+Enter, and plain Enter alike) must still
        # be a bare \r -- no invented sequence for the two combos with no portable encoding.
        enter_i = body.index('case "Enter":')
        after_alt = body.index('return "\\x1b\\r";', enter_i)
        tail = body[after_alt: body.index("\n", after_alt) + 40]
        self.assertIn('return "\\r";', tail)

    def test_ctrl_c_still_maps_to_x03_unconditionally_regression_guard(self):
        # This must stay reachable and return BEFORE the new pm/plain machinery is ever computed --
        # a new branch intercepting Ctrl+C ahead of this would be exactly the regression the brief
        # calls out as the one thing this file must never get wrong.
        body = self._key_body()
        self.assertIn(
            "if (/^[a-zA-Z]$/.test(k)) return String.fromCharCode(k.toUpperCase().charCodeAt(0) & 0x1f);",
            body,
        )
        ctrl_letter_i = body.index("String.fromCharCode(k.toUpperCase()")
        pm_i = body.index("var pm =")
        self.assertLess(ctrl_letter_i, pm_i)

    def test_ctrl_space_sends_nul_and_flags_it_as_unconfirmed_convention(self):
        body = self._key_body()
        self.assertIn('if (k === " ") return "\\x00";', body)
        # must be flagged as the ASCII C0 convention, not an xterm ctlseqs-documented sequence --
        # and must NOT guess at the unconfirmed siblings (Ctrl+2..8, Ctrl+/).
        self.assertIn("FLAGGED", body)
        self.assertIn("C0 convention", body)
        self.assertNotIn('k === "/"', body)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn(
            "var pm = 1 + (ev.shiftKey ? 1 : 0) + (ev.altKey ? 2 : 0) + "
            "(ev.ctrlKey ? 4 : 0) + (ev.metaKey ? 8 : 0);",
            page,
        )
        self.assertIn('if (k === " ") return "\\x00";', page)


class TestMouseReportingIsGatedAndThrottled(unittest.TestCase):
    """No mouse event was EVER sent to the PTY before this change -- the only mouse handler on the
    pane was a bare `mousedown -> input.focus()`. Forwarding is added for mousedown/mousemove/
    mouseup/wheel, but ONLY while a program has turned tracking on (`this.mouse.mode`, read
    defensively off the SSE frame's new `mouse` field -- a parallel agent's addition to
    term_vt.Screen.snapshot(), contract: {"mouse": {"mode": 0, "sgr": false}})."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_mouse_state_defaults_to_tracking_off(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this.mouse = { mode: 0, sgr: false };", body)

    def test_mouse_field_is_read_defensively_in_applypatch(self):
        body = _function_body(self.src, "Terminal.prototype._applyPatch = function")
        self.assertIn("if (msg.mouse !== undefined && msg.mouse) {", body)
        self.assertIn('if (typeof msg.mouse.mode === "number") this.mouse.mode = msg.mouse.mode;', body)
        self.assertIn("if (msg.mouse.sgr !== undefined) this.mouse.sgr = !!msg.mouse.sgr;", body)

    def test_gate_checks_mode_then_shift_then_history_in_that_order(self):
        # Order matters for readability/maintenance, and each is an independent early-return --
        # pin all three so a future edit can't silently drop the shift bypass (the user's only
        # escape hatch) or the viewingHistory guard (frozen-snapshot coordinates).
        body = _function_body(self.src, "Terminal.prototype._mouseGate = function")
        mode_i = body.index("if (this.mouse.mode === 0) return false;")
        shift_i = body.index("if (ev.shiftKey) return false;")
        hist_i = body.index("if (this.viewingHistory) return false;")
        self.assertLess(mode_i, shift_i)
        self.assertLess(shift_i, hist_i)

    def test_every_mouse_entry_point_consults_the_shared_gate(self):
        for fn in ("_onMouseDown", "_onMouseMove", "_onMouseUp"):
            body = _function_body(self.src, "Terminal.prototype.%s = function" % fn)
            self.assertIn("if (!this._mouseGate(ev)) return;", body)
        wheel_body = _function_body(self.src, "Terminal.prototype._onWheel = function")
        self.assertIn("if (this._mouseGate(ev)) {", wheel_body)

    def test_mousedown_mousemove_mouseup_listeners_are_wired_on_the_pane(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn(
            'pane.addEventListener("mousedown", function (ev) { input.focus(); self._onMouseDown(ev); });',
            body,
        )
        self.assertIn('pane.addEventListener("mousemove", function (ev) { self._onMouseMove(ev); });', body)
        self.assertIn('pane.addEventListener("mouseup", function (ev) { self._onMouseUp(ev); });', body)

    def test_coordinates_are_derived_from_rowsel_rect_not_the_panes(self):
        # The exact off-by-one-cell bug _layoutCursor's own fix addressed: .vtpane is padded
        # (8px 10px), so its border box is offset from where rows actually start.
        body = _function_body(self.src, "Terminal.prototype._mouseCell = function")
        self.assertIn("this.rowsEl.getBoundingClientRect()", body)
        self.assertNotIn("this.pane.getBoundingClientRect()", body)

    def test_coordinates_are_one_based_and_clamped_to_the_grid(self):
        body = _function_body(self.src, "Terminal.prototype._mouseCell = function")
        self.assertIn("+ 1;", body)
        self.assertIn("col = Math.max(1, Math.min(this.cols, col));", body)
        self.assertIn("row = Math.max(1, Math.min(this.rows, row));", body)

    def test_motion_is_throttled_on_cell_change(self):
        body = _function_body(self.src, "Terminal.prototype._onMouseMove = function")
        self.assertIn(
            "if (this._lastMouseCell && this._lastMouseCell.row === cell.row "
            "&& this._lastMouseCell.col === cell.col) return;",
            body,
        )

    def test_mode_1002_only_reports_motion_while_dragging(self):
        body = _function_body(self.src, "Terminal.prototype._onMouseMove = function")
        self.assertIn("if (this.mouse.mode === 1000) return;", body)
        self.assertIn("if (this.mouse.mode === 1002 && !dragging) return;", body)
        self.assertIn('var dragging = this._mouseButtonDown !== null;', body)

    def test_sgr_release_uses_lowercase_m_final_character_with_the_real_button(self):
        body = _function_body(self.src, "Terminal.prototype._sendMouseReport = function")
        self.assertIn(
            '"\\x1b[<" + pb + ";" + cell.col + ";" + cell.row + (isRelease ? "m" : "M")', body
        )

    def test_legacy_release_always_reports_button_3(self):
        body = _function_body(self.src, "Terminal.prototype._sendMouseReport = function")
        self.assertIn("var legacyPb = isRelease ? 3 : pb;", body)

    def test_legacy_coordinates_are_clamped_to_223(self):
        body = _function_body(self.src, "Terminal.prototype._sendMouseReport = function")
        self.assertIn("Math.min(223, cell.col)", body)
        self.assertIn("Math.min(223, cell.row)", body)

    def test_wheel_sends_button_4_or_5_when_tracking_is_on(self):
        body = _function_body(self.src, "Terminal.prototype._onWheel = function")
        self.assertIn("var wcode = (ev.deltaY < 0 ? 0 : 1) + 64;", body)

    def test_wheel_keeps_scrollback_behaviour_untouched_when_gate_is_closed(self):
        # The pre-existing scrollback/alt-screen-arrow logic must still be present, reachable when
        # _mouseGate returns false (mode 0, shift held, or viewingHistory).
        body = _function_body(self.src, "Terminal.prototype._onWheel = function")
        self.assertIn("if (this.alt) {", body)
        self.assertIn("this._scrollToBottom();", body)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn("Terminal.prototype._mouseGate = function", page)
        self.assertIn("Terminal.prototype._sendMouseReport = function", page)
        self.assertIn('"\\x1b[<" + pb + ";" + cell.col + ";" + cell.row', page)


class TestOutsidePaneReleaseFallback(unittest.TestCase):
    """DEFECT 2: pane's own mousedown/mousemove/mouseup are wired on `pane` only, so a
    press-inside/drag-outside/release-outside sequence never fires `_onMouseUp` and
    `_mouseButtonDown` sticks forever -- every later hover then reads as a drag. These are
    source-text checks that the wiring exists and is torn down; the actual runtime behaviour
    (state really clears, no double-send for an in-pane release) is proven by executing the real
    code in tests/test_term_vt_exec.py."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_document_level_mouseup_listener_is_wired_in_constructor(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this._onDocMouseUp = function (ev) {", body)
        self.assertIn('document.addEventListener("mouseup", this._onDocMouseUp);', body)

    def test_fallback_skips_a_release_that_landed_inside_the_pane(self):
        # must not double-send: the pane's own "mouseup" listener already handled an in-pane
        # release by the time this document-level one fires (bubbling order).
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        i = body.index("this._onDocMouseUp = function (ev) {")
        handler = body[i: body.index("document.addEventListener", i)]
        self.assertIn("if (pane.contains(ev.target)) return;", handler)

    def test_fallback_reuses_onmouseup_for_clamped_coordinates_and_the_report(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        i = body.index("this._onDocMouseUp = function (ev) {")
        handler = body[i: body.index("document.addEventListener", i)]
        self.assertIn("self._onMouseUp(ev);", handler)

    def test_fallback_unconditionally_clears_button_state(self):
        # belt-and-suspenders: state must clear even if _onMouseUp's own gate declined to send.
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        i = body.index("this._onDocMouseUp = function (ev) {")
        handler = body[i: body.index("document.addEventListener", i)]
        self.assertIn("self._mouseButtonDown = null;", handler)
        self.assertIn("self._lastMouseCell = null;", handler)

    def test_listener_is_removed_in_destroy(self):
        body = _function_body(self.src, "Terminal.prototype.destroy = function")
        self.assertIn(
            'document.removeEventListener("mouseup", this._onDocMouseUp);', body
        )
        self.assertIn("this._onDocMouseUp = null;", body)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn("this._onDocMouseUp = function (ev) {", page)
        self.assertIn('document.removeEventListener("mouseup", this._onDocMouseUp);', page)


class TestMouseButtonCodeCommentIsHonest(unittest.TestCase):
    """DEFECT 3 (minor): `_mouseButtonCode` never adds +4 for Shift (Shift always bypasses mouse
    reporting via `_mouseGate`, so a Shift-held event never reaches this function), but the old
    comment claimed the encoder 'stays honest and general' about Shift -- a false claim about
    dead code that was never added. Fix is comment-only: no +4 branch should exist or appear."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_no_shift_bit_is_encoded(self):
        body = _function_body(self.src, "Terminal.prototype._mouseButtonCode = function")
        self.assertNotIn("+ 4", body)
        self.assertNotIn("shiftKey", body)

    def test_stale_overstatement_is_gone(self):
        self.assertNotIn("stays honest and general", self.src)

    def test_comment_states_shift_never_reaches_this_function(self):
        self.assertIn("Shift=4 is deliberately NOT encoded here", self.src)
        self.assertIn("never reaches this function", self.src)


class TestMouseReportingToggle(unittest.TestCase):
    """The user-visible fix for the regression 4bc3e08 introduced: Claude Code's own TUI turns on
    `?1003` any-motion tracking, so plain dragging inside the pane stopped making a native text
    selection. Shift+drag still worked (XTSHIFTESCAPE, `_mouseGate`) but wasn't discoverable and
    isn't the default the user wants. This toggle is a further gate in front of the EXISTING mouse
    encoder (buildToolbar/_mouseGate) -- it must not delete or rewrite any of that machinery."""

    def setUp(self):
        self.src = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def test_toggle_is_built_in_the_shared_toolbar_not_per_renderer(self):
        # both renderers inherit it from ONE place, exactly like the A-/A+ zoom controls -- pinned
        # the same way TestZoomControlOverlapFix pins buildToolbar's shared-ness.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("vtmousebtn", body)
        self.assertIn("mouseToggle.getEnabled()", body)
        self.assertIn("mouseToggle.setEnabled(", body)
        self.assertIn("mouseToggle.isMeaningful()", body)
        # not reimplemented separately inside either constructor
        term_body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertNotIn("vtmousebtn", term_body)
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertNotIn("vtmousebtn", xterm_body)

    def test_default_is_off_in_the_initializer_not_just_a_comment(self):
        # pin the actual assignment, not prose -- a comment claiming "default off" with the
        # initializer flipped to true would still pass a text-only "mentions off" check.
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this.mouseReportingEnabled = false;", body)

    def test_toggle_is_not_persisted_no_new_state_file(self):
        # matches _fontPx/_linePx's own per-instance, not-saved precedent -- no _load_json/
        # _save_json-style read/write anywhere near the field.
        self.assertNotIn("mouseReportingEnabled", self._read_flags_or_titles_refs())

    def _read_flags_or_titles_refs(self):
        # every place flags.json/titles.json are touched in this file (there should be none --
        # ext_vt.js never persists anything; this just documents/pins that assumption locally
        # rather than assuming it silently).
        return "\n".join(line for line in self.src.splitlines() if "flags.json" in line or "titles.json" in line)

    def test_mousegate_still_consults_mode_shift_and_viewinghistory_in_order(self):
        # the pre-existing three checks must survive, in their pre-existing order -- this toggle
        # is a FOURTH, additional gate, not a replacement.
        body = _function_body(self.src, "Terminal.prototype._mouseGate = function")
        mode_i = body.index("if (this.mouse.mode === 0) return false;")
        shift_i = body.index("if (ev.shiftKey) return false;")
        hist_i = body.index("if (this.viewingHistory) return false;")
        toggle_i = body.index("if (this.mouseReportingEnabled === false) return false;")
        self.assertLess(mode_i, shift_i)
        self.assertLess(shift_i, hist_i)
        self.assertLess(hist_i, toggle_i)

    def test_mousegate_consults_the_toggle(self):
        body = _function_body(self.src, "Terminal.prototype._mouseGate = function")
        self.assertIn("this.mouseReportingEnabled", body)

    def test_wheel_still_takes_the_scrollback_branch_when_gate_is_closed(self):
        # with the toggle off, `_mouseGate` returns false (same as mode===0 today) -- the
        # pre-existing scrollback/alt-screen-arrow branch must still be the fallback path.
        body = _function_body(self.src, "Terminal.prototype._onWheel = function")
        self.assertIn("if (this._mouseGate(ev)) {", body)
        self.assertIn("if (this.alt) {", body)
        self.assertIn("this._scrollToBottom();", body)

    def test_control_is_not_hidden_by_host_or_viewport(self):
        # hard project rule: no control is gated on location.hostname; and requirement 5 says this
        # toggle must work on desktop/tablet/phone alike -- no @media rule may hide .vtmousebtn.
        self.assertNotIn("location.hostname", self.src)
        css = self.css
        idx = 0
        while True:
            idx = css.find(".vtmousebtn", idx)
            if idx == -1:
                break
            # walk back to the nearest enclosing @media block (if any) and confirm it isn't one
            # that hides the control via display:none.
            media_start = css.rfind("@media", 0, idx)
            if media_start != -1:
                block_end = css.find("}", idx)
                block = css[media_start:block_end]
                self.assertNotIn("display: none", block, "a @media rule must not hide .vtmousebtn")
                self.assertNotIn("display:none", block, "a @media rule must not hide .vtmousebtn")
            idx += len(".vtmousebtn")

    def test_inert_state_is_deliberate_and_commented(self):
        # requirement 5: when the toggle would do nothing (mouse.mode === 0), the choice to
        # dim+no-op rather than hide it must be an explicit, commented decision.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("vtmouseinert", body)
        self.assertIn("inert", body.lower())

    def test_xterm_toggle_is_inert_and_commented_as_deliberate(self):
        # requirement 7: xterm.js owns its own mouse handling -- the toggle must not fight it.
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertIn("isMeaningful: function () { return false; }", xterm_body)
        self.assertIn("do not fight it", xterm_body)

    def test_button_carries_aria_pressed_and_a_title(self):
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn('mouseBtn.setAttribute("aria-pressed"', body)
        self.assertIn("mouseBtn.title", body)
        self.assertIn("Shift", body)   # the title must explain the Shift+drag escape hatch

    def test_button_is_reachable_and_activatable_by_tap_not_only_hover(self):
        # no hover-only affordance: a real click/keydown listener, a tabindex for focusability,
        # and no CSS rule making the control only appear on :hover.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn('mouseBtn.addEventListener("click"', body)
        self.assertIn('mouseBtn.setAttribute("tabindex", "0")', body)
        self.assertNotIn(".vtmousebtn:hover { display", self.css)

    def test_css_uses_a_sibling_class_in_the_same_idiom_as_vtzoombtn(self):
        self.assertIn(".vtmousebtn", self.css)
        # reuses the shared .vtzoombtn base class (same font/padding/border tokens) rather than
        # inventing a whole new control system.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn('mouseBtn.className = "vtzoombtn vtmousebtn";', body)

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn("vtmousebtn", page)
        self.assertIn("this.mouseReportingEnabled = false;", page)
        self.assertIn("if (this.mouseReportingEnabled === false) return false;", page)


class TestFocusReportingClient(unittest.TestCase):
    """`?1004` focus in/out reporting, the client half of TestFocusReportingSnapshot
    (tests/test_term_vt.py -- server side). Mirrors `mouse`'s own defensive-read pattern exactly:
    default off, read off every SSE frame, no-op when the server hasn't turned it on."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_focus_events_defaults_to_false(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this.focusEvents = false;", body)

    def test_focus_events_read_defensively_in_applypatch(self):
        body = _function_body(self.src, "Terminal.prototype._applyPatch = function")
        self.assertIn("if (msg.focus_events !== undefined) this.focusEvents = !!msg.focus_events;", body)

    def test_focus_sends_csi_i_gated_on_focus_events(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn('input.addEventListener("focus", function () {', body)
        i = body.index('input.addEventListener("focus", function () {')
        focus_handler = body[i:body.index("});", i)]
        self.assertIn("if (self.focusEvents) self._send(\"\\x1b[I\");", focus_handler)

    def test_blur_sends_csi_o_gated_on_focus_events(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        i = body.index('input.addEventListener("blur", function () {')
        blur_handler = body[i:body.index("});", i)]
        self.assertIn("if (self.focusEvents) self._send(\"\\x1b[O\");", blur_handler)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn("this.focusEvents = false;", page)
        self.assertIn("\\x1b[I", page)
        self.assertIn("\\x1b[O", page)


class TestSendOrderingAndMotionCoalescing(unittest.TestCase):
    """`?1003` any-motion tracking turns postKeys()'s pre-existing lack of send ordering from a
    rare race into a routine one. Two fixes, pinned separately:
    (a) motion reports are coalesced to at most one per animation frame, and ONLY motion --
        keystrokes/press/release must never be dropped or merged;
    (b) every send (motion included, once flushed) is serialized through one promise chain so
        bytes reach /api/term/keys in production order, and a rejected send doesn't wedge it.

    NOTE: these are all source-text substring checks -- they can confirm the SHAPE of the fix
    (which function calls which) but, being static, cannot prove the actual byte ORDER two
    real timers produce. That is a timing property, and a text search cannot fail against a
    timing bug. The behavioural proof -- executing the real functions with a fake clock and
    checking the actual POST order, including the reviewer's exact motion-then-early-discrete-send
    regression scenario -- lives in tests/test_term_vt_exec.py, which runs the real code under
    Node instead of grepping for it."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_send_chain_initialized_in_constructor(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this._sendChain = Promise.resolve();", body)

    def test_enqueue_appends_to_the_chain_in_order(self):
        # `_enqueue` is the ONE place that appends to `_sendChain` -- both `_send` (discrete
        # events) and `_flushMotion` (a flushed motion report) must go through it rather than
        # each maintaining their own chain-append logic. It goes through `_sendWithTimeout`
        # (see that test class below) rather than calling `postKeys` directly, so a send that
        # never settles still cannot block the chain -- see TestSendNeverSettlesTimeout.
        body = _function_body(self.src, "Terminal.prototype._enqueue = function")
        self.assertIn("this._sendChain = this._sendChain.then(function () {", body)
        self.assertIn("return self._sendWithTimeout(s);", body)

    def test_a_rejected_send_does_not_wedge_the_chain(self):
        body = _function_body(self.src, "Terminal.prototype._enqueue = function")
        self.assertIn("}).catch(function () { });", body)

    def test_ordering_comment_explains_typing_is_also_protected(self):
        # the explanatory comment sits directly ABOVE the `_enqueue` definition (a doc block, not
        # code inside the function), so search the raw source rather than _function_body's
        # marker-to-next-marker slice, which starts AT the marker and would miss it.
        self.assertIn("makes fast typing safe", self.src)

    def test_send_flushes_pending_motion_before_enqueueing_itself(self):
        # This is the actual DEFECT 1 fix: a discrete `_send` must flush any pending motion into
        # the chain FIRST, so a motion report produced earlier can never be overtaken by a later
        # discrete event reaching the chain first.
        body = _function_body(self.src, "Terminal.prototype._send = function")
        self.assertIn("this._flushMotion();", body)
        self.assertIn("this._enqueue(s);", body)

    def test_flushmotion_does_not_call_send_to_avoid_recursion(self):
        # `_send` -> `_flushMotion` -> `_send` would recurse (and re-trigger another flush check)
        # -- `_flushMotion` must go straight to `_enqueue` instead.
        body = _function_body(self.src, "Terminal.prototype._flushMotion = function")
        self.assertIn("this._enqueue(s);", body)
        self.assertNotIn("this._send(", body)

    def test_flushmotion_is_a_noop_once_already_flushed(self):
        # A late rAF callback firing after a discrete _send already flushed the same pending
        # motion must not send it a second time -- `_pendingMotion` is already null by then.
        body = _function_body(self.src, "Terminal.prototype._flushMotion = function")
        self.assertIn("if (this._pendingMotion === null) return;", body)
        self.assertIn("this._pendingMotion = null;", body)

    def test_sendmotion_method_exists_and_uses_raf(self):
        body = _function_body(self.src, "Terminal.prototype._sendMotion = function")
        self.assertIn("requestAnimationFrame(function () {", body)

    def test_sendmotion_keeps_only_the_newest_pending_report(self):
        body = _function_body(self.src, "Terminal.prototype._sendMotion = function")
        self.assertIn("this._pendingMotion = s;", body)
        self.assertIn("if (this._motionRAFPending) return;", body)

    def test_sendmotion_raf_callback_flushes_through_flushmotion_not_postkeys_directly(self):
        # the flush must still go through _flushMotion/_enqueue (and therefore the ordering
        # chain), not call postKeys() itself -- otherwise the flushed report could bypass the
        # ordering guarantee.
        body = _function_body(self.src, "Terminal.prototype._sendMotion = function")
        self.assertIn("self._flushMotion();", body)
        self.assertNotIn("postKeys(", body)

    def test_only_mousemove_passes_ismotion_true(self):
        body = _function_body(self.src, "Terminal.prototype._onMouseMove = function")
        self.assertIn(
            "this._sendMouseReport(this._mouseButtonCode(ev, true), cell, false, true);", body,
        )

    def test_mousedown_mouseup_wheel_do_not_coalesce(self):
        # press, release and wheel must call _sendMouseReport WITHOUT isMotion=true -- each is a
        # discrete event and must never be routed through _sendMotion's coalescing.
        down_body = _function_body(self.src, "Terminal.prototype._onMouseDown = function")
        self.assertIn("this._sendMouseReport(this._mouseButtonCode(ev, false), cell, false);", down_body)
        up_body = _function_body(self.src, "Terminal.prototype._onMouseUp = function")
        self.assertIn("this._sendMouseReport(this._mouseButtonCode(ev, false), cell, true);", up_body)
        wheel_body = _function_body(self.src, "Terminal.prototype._onWheel = function")
        self.assertIn("this._sendMouseReport(wcode, wcell, false);", wheel_body)

    def test_sendmousereport_routes_motion_through_sendmotion_others_through_send(self):
        body = _function_body(self.src, "Terminal.prototype._sendMouseReport = function")
        self.assertIn("if (isMotion) this._sendMotion(s); else this._send(s);", body)

    def test_keydown_sends_directly_never_coalesced(self):
        # a keystroke is a discrete event -- _onKeyDown must call _send directly, never _sendMotion.
        body = _function_body(self.src, "Terminal.prototype._onKeyDown = function")
        self.assertIn("this._send(bytes);", body)
        self.assertNotIn("_sendMotion", body)

    def test_oninput_sends_directly_never_coalesced(self):
        body = _function_body(self.src, "Terminal.prototype._onInput = function")
        self.assertIn("this._send(v);", body)
        self.assertNotIn("_sendMotion", body)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn("this._sendChain = this._sendChain.then(function () {", page)
        self.assertIn("Terminal.prototype._sendMotion = function", page)


class TestSendNeverSettlesTimeout(unittest.TestCase):
    """A send that neither resolves nor rejects (observed: a POST /api/term/keys hung ~5 minutes
    under Chrome's background-tab throttling) used to wedge `_sendChain` -- and every later
    keystroke behind it -- forever, since `.catch()` only protects against a REJECTED send. The
    actual timing/ordering proof (a never-settling postKeys() call followed by a later send that
    must still arrive once the timeout fires, and must not arrive before) is executed under Node
    in tests/test_term_vt_exec.py's TestSendTimeoutRegression -- these are source-text pins for
    the parts a text search CAN usefully confirm: the constant itself, that destroy() sweeps up
    any timer still pending, and that the fix is actually in the served page."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_send_with_timeout_races_postkeys_against_a_bounded_timer(self):
        body = _function_body(self.src, "Terminal.prototype._sendWithTimeout = function")
        self.assertIn("setTimeout(function () {", body)
        self.assertIn("}, 5000);", body)
        self.assertIn("postKeys(self.ttyId, s).then(", body)

    def test_timeout_rejects_so_enqueues_catch_drops_it_like_any_rejected_send(self):
        # No retry: the timeout path must REJECT (not resolve, not silently swallow itself) so
        # it flows through the exact same `.catch(function () { })` in `_enqueue` that an
        # ordinarily-rejected send already goes through -- one drop path, not two.
        body = _function_body(self.src, "Terminal.prototype._sendWithTimeout = function")
        self.assertIn('reject(new Error("term send timed out"));', body)

    def test_destroy_clears_any_pending_send_timers(self):
        body = _function_body(self.src, "Terminal.prototype.destroy = function")
        self.assertIn("clearTimeout(this._sendTimers[ti]);", body)
        self.assertIn("this._sendTimers = [];", body)

    def test_send_timers_array_initialized_in_constructor(self):
        body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this._sendTimers = [];", body)

    def test_the_fix_reaches_the_browser_not_just_the_source_file(self):
        page = build_page()
        self.assertIn("Terminal.prototype._sendWithTimeout = function", page)
        self.assertIn("}, 5000);", page)


class TestRendererSwitchControl(unittest.TestCase):
    """xterm.js is now the DEFAULT renderer (config.TERM_RENDERER, flipped by a concurrent agent
    this session); this is the client half that keeps the built-in grid painter reachable ON
    DEMAND, per terminal, from the toolbar -- so a user can switch away from xterm the moment they
    hit one of its documented gaps. Mirrors TestMouseReportingToggle's own structure closely: same
    "shared toolbar, not reimplemented per renderer" shape, same "never hidden by host/viewport"
    rule, same "reaches the browser" check."""

    def setUp(self):
        self.src = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    def _switch_body(self):
        return _body_until(self.src, "function switchActiveRenderer(renderer) {", ["function openVT(sid, mode) {"])

    def _mount_body(self):
        return _body_until(self.src, "function mountRenderer(renderer) {", ["function boot(renderer) {"])

    def test_switch_is_built_in_the_shared_toolbar_not_per_renderer(self):
        # Same pattern TestZoomControlOverlapFix/TestMouseReportingToggle already pin for the
        # zoom controls and the mouse toggle: ONE buildToolbar definition, consulted by both
        # constructors, never reimplemented separately inside either one.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("vtrendererbtn", body)
        self.assertIn("rendererSwitch.getActive()", body)
        self.assertIn("rendererSwitch.switchTo(", body)
        term_body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertNotIn("vtrendererbtn", term_body)
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertNotIn("vtrendererbtn", xterm_body)

    def test_both_constructors_pass_a_rendererswitch_into_the_shared_toolbar(self):
        # The interface itself is supplied by the CALL SITE (openVT / bootStandalone), not
        # invented inside Terminal/XtermTerminal -- each constructor just forwards what it was
        # given, now as an ordinary third NAMED parameter (`rendererSwitch`). This used to be read
        # via `arguments[2]` specifically to avoid touching the `function Terminal(container,
        # ttyId) {` / `function XtermTerminal(container, ttyId) {` literals that dozens of OTHER
        # tests in this file located bodies by; `_function_body` (see its own docstring) now
        # matches those by prefix instead, so the signature is free to carry the parameter for
        # real -- default-filled with `_noopRendererSwitch` when the caller omits it.
        term_body = _function_body(self.src, "function Terminal(container, ttyId, rendererSwitch) {")
        self.assertIn("rendererSwitch = rendererSwitch || _noopRendererSwitch;", term_body)
        self.assertIn("rendererSwitch\n    );", term_body)
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertIn("function XtermTerminal(container, ttyId, rendererSwitch)", xterm_body)
        self.assertIn("rendererSwitch = rendererSwitch || _noopRendererSwitch;", xterm_body)
        self.assertIn("rendererSwitch\n    );", xterm_body)

    def test_switching_destroys_the_old_terminal(self):
        # Requirement 3: the old Terminal/XtermTerminal must actually be torn down (closing its
        # SSE, timers and document-level listeners -- see Terminal.prototype.destroy /
        # XtermTerminal.prototype.destroy) before the replacement is built, for BOTH mount points.
        self.assertIn("activeTerm.destroy();", self._switch_body())
        self.assertIn("curTerm.destroy(); curTerm = null;", self._mount_body())

    def test_switching_rebuilds_against_the_same_tty(self):
        # Both renderers share the server's PTYS table -- the switch must pass the EXISTING tty id
        # to the new constructor, never request a fresh one.
        self.assertIn("new Cls(activeTermWrap, activeTty,", self._switch_body())
        self.assertIn("new Cls(termWrap, tty,", self._mount_body())

    def test_contextbar_is_rewired_not_destroyed_on_switch(self):
        # Requirement 4: "re-wire it to the new terminal object rather than leaving it pointing at
        # a destroyed one" -- the SAME ContextBar instance must survive, only its getInput()
        # callback should move to the new terminal. Destroying/recreating the bar would also be
        # wrong here (it would reset the bar's own DOM/poll timer for no reason).
        modal = self._switch_body()
        self.assertIn("activeBar.getInput = function () { return term; };", modal)
        self.assertNotIn("activeBar.destroy()", modal)
        standalone = self._mount_body()
        self.assertIn("curBar.getInput = function () { return term; };", standalone)
        self.assertNotIn("curBar.destroy()", standalone)

    def test_switch_updates_the_active_renderer_variable_new_tab_url_reads(self):
        # openNewTab() (TestXtermRendererSwitch.test_new_tab_url_relays_the_server_chosen_renderer)
        # builds its URL from the module-level `activeRenderer` -- the switch must write to that
        # SAME variable so a "New tab" opened after a switch carries the renderer actually on
        # screen, not the server's original pick from openVT's own res.j.renderer line.
        self.assertIn("activeRenderer = renderer;", self._switch_body())

    def test_initial_choice_lines_are_unchanged_by_the_switch_feature(self):
        # The switch is a later, explicit override -- it must not touch how the INITIAL renderer
        # is picked. Both of the server-owned decision lines from before this feature existed are
        # pinned verbatim.
        self.assertIn('activeRenderer = (res.j.renderer === "xterm") ? "xterm" : "grid";', self.src)
        body = _body_until(self.src, "function bootStandalone", ["})();\n})();"])
        self.assertIn('fetch("/api/term/renderer")', body)
        self.assertIn('renderer === "xterm" ? XtermTerminal : Terminal', body)

    def test_control_documents_the_blank_pane_asymmetry_honestly(self):
        # Requirement 6: switching TO xterm must warn, in the control's own title/aria-label, that
        # the pane goes blank until the next write -- not hidden in a code comment only.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("BLANK", body)
        self.assertIn("no repaint", body)
        # and the reverse direction (xterm -> grid) is explained as the safe/instant one, so the
        # asymmetry itself -- not just one direction -- is documented on the control.
        self.assertIn("repaints instantly", body)

    def test_control_carries_aria_pressed_and_is_keyboard_activatable(self):
        # Requirement 7: real accessibility state, not just a visual style change, and reachable
        # by keyboard (Enter/Space) as well as tap/click -- same pattern as the mouse toggle.
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn('rendererBtn.setAttribute("aria-pressed"', body)
        self.assertIn('rendererBtn.setAttribute("tabindex", "0")', body)
        self.assertIn('rendererBtn.addEventListener("click"', body)
        self.assertIn('rendererBtn.addEventListener("keydown"', body)

    def test_control_is_not_hidden_by_host_or_viewport(self):
        # Hard project rule (same as TestMouseReportingToggle.test_control_is_not_hidden_by_
        # host_or_viewport): no location.hostname gate anywhere, and no @media rule may hide
        # .vtrendererbtn behind display:none at any breakpoint.
        self.assertNotIn("location.hostname", self.src)
        css = self.css
        idx = 0
        while True:
            idx = css.find(".vtrendererbtn", idx)
            if idx == -1:
                break
            media_start = css.rfind("@media", 0, idx)
            if media_start != -1:
                block_end = css.find("}", idx)
                block = css[media_start:block_end]
                self.assertNotIn("display: none", block, "a @media rule must not hide .vtrendererbtn")
                self.assertNotIn("display:none", block, "a @media rule must not hide .vtrendererbtn")
            idx += len(".vtrendererbtn")

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn("vtrendererbtn", page)
        self.assertIn("function switchActiveRenderer(renderer) {", page)
        self.assertIn("function mountRenderer(renderer) {", page)


class TestTerminalModalTitleIsUppercase(unittest.TestCase):
    """The modal title now reads "TERMINAL" (uppercase) at both sites that set it:
    buildOverlay()'s static default (painted before any terminal has opened) and openVT()'s
    per-open title (which appends the resume/session suffix). Both must use the new uppercase
    form, and the old mixed-case "Terminal" strings must be fully gone, not merely superseded --
    precise enough that reverting either site alone fails this."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_static_default_title_is_uppercase(self):
        self.assertIn('modalTitleEl.textContent = "TERMINAL";', self.src)

    def test_per_open_title_is_uppercase_with_suffix(self):
        self.assertIn(
            'modalTitleEl.textContent = "TERMINAL — " + (mode === "resume" ? "resume · " : "") + sid;',
            self.src)

    def test_old_mixed_case_title_strings_are_gone(self):
        self.assertNotIn('modalTitleEl.textContent = "Terminal";', self.src)
        self.assertNotIn('modalTitleEl.textContent = "Terminal — "', self.src)

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn('modalTitleEl.textContent = "TERMINAL";', page)
        self.assertIn('modalTitleEl.textContent = "TERMINAL — "', page)

    # The standalone tab's title used to be the constant "TERMINAL — AI Tracker", which made
    # several ⤢-opened tabs indistinguishable in the tab strip -- and several tabs is the whole
    # point of that button. It now carries the SAME session identifier the modal's own header
    # does (mode prefix + sid, falling back to the tty for a bare ?tty= link). These two tests
    # keep their original job -- the word is TERMINAL, never "Terminal" -- against the new string.
    def test_standalone_document_title_is_uppercase_and_identifies_the_session(self):
        self.assertIn(
            'standaloneTitle = "TERMINAL — " + (mode === "resume" ? "resume · " : "") '
            '+ (sid || "tty " + tty);',
            self.src)
        self.assertIn("document.title = standaloneTitle;", self.src)
        self.assertNotIn('document.title = "Terminal — ', self.src)
        self.assertNotIn('document.title = "TERMINAL — AI Tracker";', self.src)

    def test_standalone_title_survives_app_js_own_two_second_retitle(self):
        # app.js's render() does `document.title = title + " · tracker"` on EVERY poll, and it
        # keeps polling in the standalone tab -- so a title written only at boot is clobbered
        # seconds later (observed live before this assertion existed). ext_vt.js's own render
        # hook, which app.js calls at the END of that same render, must re-assert it.
        self.assertIn(
            'if (standaloneTitle && document.title !== standaloneTitle) document.title = standaloneTitle;',
            self.src)

    def test_standalone_document_title_reaches_the_browser(self):
        page = build_page()
        self.assertIn(
            'standaloneTitle = "TERMINAL — " + (mode === "resume" ? "resume · " : "") '
            '+ (sid || "tty " + tty);',
            page)
        self.assertIn("document.title = standaloneTitle;", page)
        self.assertNotIn('document.title = "Terminal — ', page)


class TestThemeFlipperInTerminal(unittest.TestCase):
    """Dark/light flipper reachable from inside a terminal (the full-screen overlay otherwise
    covers app.js's own top-bar #themebtn, leaving no way to flip theme mid-session). app.js's
    setTheme() dispatches a "themechange" CustomEvent on `document` -- from INSIDE setTheme
    itself, so it fires for every caller (the pre-existing top-bar button included), not just this
    new one. ext_vt.js's shared buildToolbar() -- the same single place TestZoomControlOverlapFix/
    TestMouseReportingToggle/TestRendererSwitchControl already pin -- builds the button so BOTH
    renderers inherit it for free; it must call the global toggleTheme() rather than reimplement
    theme logic, and XtermTerminal's live re-theme listener must be both added (constructor) and
    removed (destroy) -- an add without a matching remove is a leak that outlives the DOM."""

    def setUp(self):
        self.app_js = _read("app.js")
        self.src = _read("ext_vt.js")

    def test_setTheme_dispatches_themechange(self):
        self.assertIn(
            'document.dispatchEvent(new CustomEvent("themechange",{detail:{theme:t}}));',
            self.app_js)

    def test_dispatch_lives_inside_setTheme_so_every_caller_gets_it(self):
        # setTheme/toggleTheme are each one statement per line in this file; slicing from
        # setTheme's own start up to toggleTheme's definition isolates setTheme's body, and
        # confirms there is exactly one dispatch site for the whole file -- not a second one
        # bolted onto just the new button's click handler.
        start = self.app_js.index("function setTheme(t){")
        end = self.app_js.index("function toggleTheme(")
        body = self.app_js[start:end]
        self.assertIn('CustomEvent("themechange"', body)
        self.assertEqual(self.app_js.count('CustomEvent("themechange"'), 1)

    def test_theme_button_built_in_shared_toolbar_not_per_renderer(self):
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("vtthemebtn", body)
        term_body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertNotIn("vtthemebtn", term_body)
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_ctor_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertNotIn("vtthemebtn", xterm_ctor_body)

    def test_button_calls_the_global_toggleTheme_not_reimplemented_logic(self):
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn("toggleTheme();", body)
        # must not reach into the class toggle / persistence itself -- setTheme() alone owns that.
        self.assertNotIn('classList.toggle("light"', body)
        self.assertNotIn("localStorage.theme", body)

    def test_button_label_rerenders_on_themechange_and_is_disposed(self):
        body = _function_body(self.src, "function buildToolbar(")
        self.assertIn('document.addEventListener("themechange", renderThemeBtn);', body)
        self.assertIn("bar.disposeThemeBtn = function ()", body)
        self.assertIn('document.removeEventListener("themechange", renderThemeBtn);', body)

    def test_theme_button_dispose_is_wired_in_both_destroys(self):
        term_destroy = _function_body(self.src, "Terminal.prototype.destroy = function")
        self.assertIn("this._disposeThemeBtn()", term_destroy)
        xterm_destroy = _body_until(self.src, "XtermTerminal.prototype.destroy = function",
                                     ["// ===== the modal (reuses app.css"])
        self.assertIn("this._disposeThemeBtn()", xterm_destroy)

    def test_xterm_adds_and_removes_the_themechange_listener(self):
        # add: in the constructor, alongside building this._onThemeChange.
        xterm_start = self.src.index("function XtermTerminal(container, ttyId")
        xterm_ctor_body = self.src[xterm_start:self.src.index("XtermTerminal.prototype.attach")]
        self.assertIn(
            "this._onThemeChange = function () { if (self.term) self.term.options.theme = _xtermTheme(); };",
            xterm_ctor_body)
        self.assertIn('document.addEventListener("themechange", this._onThemeChange);', xterm_ctor_body)
        # remove: in destroy, or the listener leaks for the life of the tab.
        xterm_destroy = _body_until(self.src, "XtermTerminal.prototype.destroy = function",
                                     ["// ===== the modal (reuses app.css"])
        self.assertIn(
            'document.removeEventListener("themechange", this._onThemeChange); this._onThemeChange = null;',
            xterm_destroy)

    def test_control_is_not_hidden_by_host_or_viewport(self):
        # hard project rule, same as TestMouseReportingToggle/TestRendererSwitchControl's own
        # checks: no control here may be gated on location.hostname.
        self.assertNotIn("location.hostname", self.src)

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn("vtthemebtn", page)
        self.assertIn('document.dispatchEvent(new CustomEvent("themechange"', page)


class TestObservePaneSharedResizeHelper(unittest.TestCase):
    """Bottom-row clipping fix: a shared module-level `observePane(pane, fn)` helper wraps
    ResizeObserver so Terminal (grid) and XtermTerminal (canvas) share ONE observe/dispose
    implementation -- replacing xterm's old bespoke `this._ro` wiring -- instead of each renderer
    forking its own. This is what makes the pane re-measure (and re-POST /api/term/resize) when
    .vtctxbar's footer changes height, instead of leaving a stale row count clipped by
    `.vtpane { overflow: hidden }`."""

    def setUp(self):
        self.src = _read("ext_vt.js")

    def test_observePane_defined_exactly_once(self):
        self.assertEqual(self.src.count("function observePane(pane, fn)"), 1)

    def test_observePane_is_the_only_ResizeObserver_construction_site(self):
        # the actual forked-implementation regression bar: if either renderer goes back to wiring
        # its own bespoke `new ResizeObserver(...)`, this fails even though observePane itself
        # still exists and still works.
        self.assertEqual(self.src.count("new ResizeObserver("), 1)

    def test_no_leftover_bespoke_ro_field(self):
        # the old xterm-only wiring this replaced kept its observer on `this._ro`.
        self.assertNotIn("this._ro", self.src)

    def test_grid_terminal_calls_observePane_in_its_constructor(self):
        term_body = _function_body(self.src, "function Terminal(container, ttyId) {")
        self.assertIn("this._disposePaneObserver = observePane(pane, this._resizeDebounced);", term_body)

    def test_xterm_terminal_calls_observePane_when_it_builds(self):
        # unlike the grid Terminal, XtermTerminal defers building its real pane/xterm.js instance
        # to _build() (behind the lazy asset-load promise) -- observePane is wired there, not in
        # the constructor itself.
        body = _body_until(self.src, "XtermTerminal.prototype._build = function",
                            ["XtermTerminal.prototype._doResize = function"])
        self.assertIn("this._disposePaneObserver = observePane(this.pane, self._resizeDebounced);", body)

    def test_both_destroys_dispose_the_observer(self):
        term_destroy = _function_body(self.src, "Terminal.prototype.destroy = function")
        self.assertIn("this._disposePaneObserver()", term_destroy)
        xterm_destroy = _body_until(self.src, "XtermTerminal.prototype.destroy = function",
                                     ["// ===== the modal (reuses app.css"])
        self.assertIn("this._disposePaneObserver()", xterm_destroy)

    def test_helper_disconnects_and_degrades_when_unsupported(self):
        body = _body_until(self.src, "function observePane(pane, fn) {", ["function buildToolbar("])
        self.assertIn("if (!window.ResizeObserver) return function () { };", body)
        self.assertIn("ro.disconnect()", body)

    def test_reaches_the_browser(self):
        page = build_page()
        self.assertIn("function observePane(pane, fn)", page)
        self.assertEqual(page.count("new ResizeObserver("), 1)


# ===== CSS-rule helpers for TestMountPointParity's assertion 3 only. Deliberately NOT a general
# CSS parser (this file's own convention -- see _body_until's docstring for the same philosophy
# applied to JS): brace-depth matching to find one rule's `{...}` body, and a `prop: value;` ->
# name split within it. Good enough to answer "which properties does this selector set inside this
# @media block", nothing more. =====
def _matching_brace_block(text, open_brace_idx):
    """The full `{...}` block starting at `open_brace_idx` (which must point AT a '{'), matched by
    brace depth so a block containing nested rules (an @media body full of other rules) still ends
    at its OWN closing brace, not the first '}' encountered."""
    depth = 0
    i = open_brace_idx
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx:i + 1]
        i += 1
    raise AssertionError("unterminated CSS block starting at %d" % open_brace_idx)


def _all_indices(text, marker):
    out, start = [], 0
    while True:
        i = text.find(marker, start)
        if i == -1:
            return out
        out.append(i)
        start = i + 1


def _props_from_body(body):
    props = set()
    for decl in body.split(";"):
        decl = decl.strip()
        if not decl or ":" not in decl:
            continue
        prop = decl.split(":", 1)[0].strip()
        if prop:
            props.add(prop)
    return props


def _props_of_rule(text, selector_with_brace):
    """Properties set by the FIRST `selector_with_brace { ... }` rule in `text`. `selector_with_brace`
    must end in '{' so a qualified selector (`.vt-standalone #ext_vt.vtfull .vtpane {`) can never be
    mistaken for the bare one (`#ext_vt.vtfull .vtpane {`) it contains as a substring -- see the
    css.index hazard documented on the call site below."""
    idx = text.index(selector_with_brace)
    brace = idx + len(selector_with_brace) - 1
    end = text.index("}", brace)
    return _props_from_body(text[brace + 1:end])


def _media_block_containing(css, media_marker, needle):
    """The brace-matched body of the @media block opened by `media_marker` (which must end in '{')
    that contains `needle` -- there are TWO same-named @media blocks in this file (one for
    .vtctxbar, one for .vtpane), and `media_marker` alone is also not reliably unique: it appears a
    second time as plain PROSE inside a comment a few lines above the real .vtpane block (see the
    comment right before that block), so a naive css.index(media_marker) can find the comment
    instead of the rule and then brace-match into the wrong following block entirely. Iterating
    every occurrence and keeping the one whose block actually contains `needle` sidesteps both
    hazards at once."""
    for idx in _all_indices(css, media_marker):
        block = _matching_brace_block(css, idx + len(media_marker) - 1)
        if needle in block:
            return block
    raise AssertionError("no %r block containing %r found in ext_vt.css" % (media_marker, needle))


def _iter_top_level_rules(block):
    """Yield (selector, body) for every `selector { body }` rule directly inside `block` (which must
    itself be a full `{...}` block, e.g. an @media body). None of this file's @media blocks nest a
    rule inside another rule, so a single non-nesting regex over the block's inner text is enough --
    no recursive brace matching needed here."""
    inner = block[block.index("{") + 1: block.rindex("}")]
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", inner):
        yield m.group(1).strip(), m.group(2)


class TestMountPointParity(unittest.TestCase):
    """Structural guard against the ext_vt.{js,css} bug this file's header brief opens with: FOUR
    past bugs where a control/behaviour landed in the MODAL (openVT/switchActiveRenderer, plus the
    buildOverlay/_wireModalStatus helpers they share) but not the STANDALONE full-tab mount
    (bootStandalone/mountRenderer), or vice versa -- caught only by adversarial review, never by a
    test, because every existing "both mounts" test asserts a PAIR of independently-worded
    one-sided literals (`activeTerm` vs `curTerm`, `modalStatusEl` vs `statusEl`, ...) against each
    side SEPARATELY, so a change to one side that leaves its own literal alone still passes. The one
    test that structurally can't be fooled that way is
    TestZoomControlOverlapFix.test_toolbar_is_built_once_and_shared_by_both_renderers -- it asserts
    a SINGLE shared count (`buildToolbar(` appears exactly 3 times: 1 definition + 2 call sites), so
    a control missing from one call site changes that number. This class generalises that shape to
    the rest of the per-mount surface, plus the two other kinds of parity bug (title, CSS
    specificity) the header brief calls out.
    """

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")

    # ----- shared slices, verified against the CURRENT file (see class docstring) -----

    def _slices(self):
        js = self.js
        # BUILD_OVERLAY/WIRE_STATUS are sliced TIGHTLY (ending at the very next function, not at
        # switchActiveRenderer several functions later) specifically so they do NOT swallow
        # ContextBar/ContextBar.prototype/renderCapBlock, which sit in between in the file and are
        # a genuinely SHARED class (one definition, `new ContextBar(...)` from both mounts) -- if
        # included here, its own toast(...) calls would make "toast(" look like modal-only code
        # (an artifact of file layout, not a real duplication) and silently invalidate the
        # not-duplicated assertion in test_shared_once_helpers_are_not_reimplemented_per_mount.
        build_overlay = _body_until(js, "function buildOverlay", ["function _matchLadderModel"])
        wire_status = _body_until(js, "function _wireModalStatus", ["function switchActiveRenderer"])
        switch = _body_until(js, "function switchActiveRenderer", ["function openVT"])
        modal = _body_until(js, "function openVT(sid, mode)", ["function closeVT"])
        standalone = _body_until(js, "function bootStandalone", ["})();\n})();"])
        return build_overlay, wire_status, switch, modal, standalone

    def test_slices_are_nonempty_and_plausibly_sized(self):
        # Guard against the markers silently drifting out of date: if a future refactor renames or
        # moves one of these functions, _body_until's src.index(start_marker) raises outright (a
        # loud failure) -- but if a marker still matches while the REAL boundary moved, the slice
        # could come back tiny/empty instead, which would make every assertion below vacuously pass.
        # Minimums are well under each slice's actual current size (see the probe this class was
        # built from), just large enough that a near-empty slice trips them.
        build_overlay, wire_status, switch, modal, standalone = self._slices()
        self.assertGreater(len(build_overlay), 500, "buildOverlay slice looks truncated")
        self.assertGreater(len(wire_status), 200, "_wireModalStatus slice looks truncated")
        self.assertGreater(len(switch), 200, "switchActiveRenderer slice looks truncated")
        self.assertGreater(len(modal), 2000, "openVT slice looks truncated")
        self.assertGreater(len(standalone), 2000, "bootStandalone slice looks truncated")
        # and the two function-identity spot checks _body_until can't give us for free -- the slice
        # actually opens where it should, not somewhere `start_marker` merely appears as a comment.
        self.assertTrue(modal.startswith("function openVT(sid, mode)"))
        self.assertTrue(standalone.startswith("function bootStandalone"))

    # ----- assertion 1: shared-capability parity -----

    def test_shared_capability_markers_present_in_both_mount_points(self):
        """For each marker below, assert it appears BOTH in the modal-side code (buildOverlay +
        _wireModalStatus + switchActiveRenderer + openVT) AND in the standalone tab's code
        (bootStandalone/mountRenderer/renderStandaloneStatus/boot). A control shipped to one mount
        only fails this immediately, unlike the existing PAIR-style tests described in the class
        docstring. Every marker was verified present at a specific line on both sides against the
        CURRENT file before being added here (not guessed from the task brief) -- see the per-marker
        comment for where.
        """
        build_overlay, wire_status, switch, modal, standalone = self._slices()
        modal_side = build_overlay + wire_status + switch + modal

        table = [
            # ContextBar (the model/effort switcher + token readout footer) built by both mounts.
            ("new ContextBar(", "openVT L2582 / mountRenderer L2769"),
            # the advisory-notice element's class -- bug: "the notice placement" (header brief #4).
            ("vtnotice", "openVT L2529 / boot() L2796"),
            # the terminal's dedicated wrap class, kept separate from the notice/status/bar chrome.
            ("vttermwrap", "openVT L2553 / boot() L2809"),
            # the status callback hook each mount wires onto its Terminal/XtermTerminal instance.
            ("_onStatusChange", "_wireModalStatus L2411 / mountRenderer L2772"),
            # the call that actually opens the SSE stream, on both the initial build and a switch.
            ("term.attach()", "switchActiveRenderer L2449 / openVT L2584 / mountRenderer L2782"),
            # the resume-refusal status guard -- bug: header brief #4's "status guard" existed on
            # one side only. Both sides must suppress connecting/reconnecting churn identically
            # while a mode="resume" pane is still coming up.
            ("if (term.starting)", "_wireModalStatus L2418 / mountRenderer L2779"),
            # the fork chip's accessible name -- bug: header brief #4's "fork-chip aria-label"
            # existed on one side only. Anchored to the `aria-label` attribute NAME, not just the
            # tooltip text: both sides also set an identical `title` attribute (the hover tooltip),
            # so a marker on the bare sentence alone would still find a match via `title` even with
            # the `aria-label` attribute itself missing -- exactly the shape of the original bug,
            # and exactly what a plain-text marker here would have missed.
            ('setAttribute("aria-label", "This terminal is a copy of a background agent — the '
             'original is still running separately")',
             "buildOverlay L1887 / renderStandaloneStatus L2733"),
        ]
        for marker, where in table:
            self.assertIn(marker, modal_side,
                           "modal-side code (buildOverlay/_wireModalStatus/switchActiveRenderer/"
                           "openVT) is missing %r -- expected at %s" % (marker, where))
            self.assertIn(marker, standalone,
                           "standalone code (bootStandalone/mountRenderer/renderStandaloneStatus) "
                           "is missing %r -- expected at %s" % (marker, where))

    def test_shared_once_helpers_are_not_reimplemented_per_mount(self):
        """`buildToolbar(` and `toast(` are deliberately NOT in the table above: both are called
        through a genuinely SHARED code path (Terminal/XtermTerminal's constructor for
        buildToolbar; ContextBar.prototype's methods for toast), reached identically by
        `new Cls(...)`/`new ContextBar(...)` from both mounts, so textually neither call ever
        appears inside either mount's OWN slice -- a substring check for them in the table above
        would either be vacuous or (as buildToolbar's own existing
        test_toolbar_is_built_once_and_shared_by_both_renderers already checks with a raw count)
        redundant. What this DOES need to confirm is the premise: that neither mount has quietly
        grown its OWN local reimplementation instead of calling the shared one -- which is exactly
        what "not present in either per-mount slice" proves.
        """
        build_overlay, wire_status, switch, modal, standalone = self._slices()
        modal_side = build_overlay + wire_status + switch + modal
        for marker in ("buildToolbar(", "toast("):
            self.assertNotIn(marker, modal_side,
                              "%r found inside the modal's own slice -- expected it to only be "
                              "reached through the shared Terminal/XtermTerminal/ContextBar code" % marker)
            self.assertNotIn(marker, standalone,
                              "%r found inside the standalone tab's own slice -- expected it to "
                              "only be reached through the shared Terminal/XtermTerminal/ContextBar "
                              "code" % marker)

    # ----- assertion 2: title symmetry -----

    def test_title_symmetry_shares_prefix_and_interpolates_session_identifier(self):
        """Bug: header brief #1 -- "the modal title was uppercased but the standalone document.title
        was not". Assert both title assignments share the SAME literal `TERMINAL — ` prefix (not
        just "both happen to say TERMINAL somewhere") AND both continue past that literal with a `+`
        that interpolates a session identifier, rather than one side being a bare hardcoded string a
        future edit could leave un-synced with the other.
        """
        modal_line = _body_until(self.js, 'modalTitleEl.textContent = "TERMINAL — "', [";"])
        standalone_line = _body_until(self.js, 'standaloneTitle = "TERMINAL — "', [";"])

        # Same literal prefix, verbatim (including the em dash) -- a future edit that reworded one
        # side ("TERMINAL:" or a plain hyphen) without touching the other fails right here.
        self.assertTrue(modal_line.startswith('modalTitleEl.textContent = "TERMINAL — "'),
                         "modal title assignment does not start with the TERMINAL prefix: %r" % modal_line)
        self.assertTrue(standalone_line.startswith('standaloneTitle = "TERMINAL — "'),
                         "standalone title assignment does not start with the TERMINAL prefix: %r"
                         % standalone_line)

        # Both INTERPOLATE a session identifier -- i.e. the statement doesn't end right after the
        # literal prefix (which would make it a hardcoded constant, the exact shape of bug #1: the
        # modal recomputed its title per-open while the standalone tab's document.title was set
        # once from a fixed string and never revisited).
        self.assertIn("+ sid", modal_line,
                       "modal title no longer interpolates `sid` -- looks hardcoded: %r" % modal_line)
        self.assertTrue("+ (sid ||" in standalone_line or "+ sid" in standalone_line,
                         "standalone title no longer interpolates a session identifier -- looks "
                         "hardcoded: %r" % standalone_line)

    # ----- assertion 3: CSS specificity guard -----

    def test_media_query_overrides_for_vtpane_are_mirrored_for_the_fullscreen_pane(self):
        """Bug: header brief #4's "phone padding" -- no other source-text test can see this one,
        because both the mobile `.vtpane` rule and the fullscreen `#ext_vt.vtfull .vtpane` rule
        individually look correct in isolation; the bug only exists in how CSS resolves the
        conflict BETWEEN them. `#ext_vt.vtfull .vtpane` (specificity (1,2,0): one ID + two classes)
        sits OUTSIDE any @media block and beats the bare `.vtpane` (0,1,0) inside one on specificity
        alone, regardless of source order -- so any property both rules set, the fullscreen rule
        silently wins on every viewport, including narrow ones where the @media rule was supposed to
        take over. The only way out is a same-or-higher-specificity selector INSIDE that @media
        block restating the property -- which is exactly what
        `.vt-standalone #ext_vt.vtfull .vtpane` (1,3,0) does for `padding` there.

        Restricted to `padding` on purpose (not a fully general "assert every collision is
        restated" loop) -- see KNOWN_IMPORTANT_OVERRIDE_PROPS below for why a fully general version
        would be WRONG here, not just fiddlier.
        """
        # The one property whose silent loss was an actual historical bug. `min-height` ALSO
        # collides (the base rule sets `min-height: 0`; the max-width:600px `.vtpane` rule sets
        # `min-height: 46vh`/`46dvh`) but is DELIBERATELY left un-restated -- ext_vt.css's own
        # comment beside the override rule says so explicitly ("Only `padding` is restated:
        # `flex`/`min-height: 0` from that rule are deliberate and still apply"): the fullscreen
        # base rule's min-height:0 is meant to WIN there, so a generic "every collision must be
        # restated" assertion would be a false positive on min-height, not a real regression bar.
        KNOWN_IMPORTANT_OVERRIDE_PROPS = {"padding"}

        base_props = _props_of_rule(self.css, "\n#ext_vt.vtfull .vtpane {")
        self.assertTrue(base_props, "could not find the base #ext_vt.vtfull .vtpane rule at all")

        for media_marker in ("@media(min-width:601px) and (max-width:900px) {",
                              "@media(max-width:600px) {"):
            block = _media_block_containing(self.css, media_marker, ".vtpane {")
            self.assertGreater(len(block), 20, "media block for %r looks truncated" % media_marker)
            vtpane_props = _props_of_rule(block, ".vtpane {")

            override_props = set()
            found_override = False
            for selector, body in _iter_top_level_rules(block):
                if "#ext_vt.vtfull" in selector and ".vtpane" in selector and selector != ".vtpane":
                    found_override = True
                    override_props |= _props_from_body(body)

            for prop in KNOWN_IMPORTANT_OVERRIDE_PROPS:
                if prop not in vtpane_props:
                    continue    # this media block doesn't touch this property -- nothing to guard
                # sanity: this scenario is only a real bug if the base rule ALSO sets it (otherwise
                # there is no specificity fight to lose in the first place).
                self.assertIn(prop, base_props,
                               "%r is asserted as a known-important collision but the base "
                               "#ext_vt.vtfull .vtpane rule doesn't set it -- update "
                               "KNOWN_IMPORTANT_OVERRIDE_PROPS" % prop)
                self.assertTrue(found_override,
                                 "%s sets %r on .vtpane, which collides with the higher-specificity "
                                 "#ext_vt.vtfull .vtpane rule, but this @media block has no "
                                 "`#ext_vt.vtfull ... .vtpane` override selector to restate it -- "
                                 "the fullscreen rule will silently win at every viewport width "
                                 "instead of just widths above this @media's range"
                                 % (media_marker, prop))
                self.assertIn(prop, override_props,
                               "%s's fullscreen-pane override exists but doesn't restate %r -- "
                               "the higher-specificity base rule wins on this property at every "
                               "viewport width, defeating the mobile value from this @media block "
                               "entirely (this is the shape of the historical phone-padding bug)"
                               % (media_marker, prop))


class TestTerminalManagerPanel(unittest.TestCase):
    """"Manage terminals": a third sidebar button opening a panel that lists every RUNNING
    terminal — peek into one, close one, or close them all.

    Before this, the only way to see or close a running terminal was to hit the concurrency cap
    and be handed renderCapBlock's list as the consolation prize for a refusal. The panel is that
    same list, on purpose, any time — which is exactly why the row must be rendered by ONE shared
    function: two hand-rolled copies of "a terminal, with a ✕" is the forked-implementation shape
    conventions rule 4 forbids, and the shape this file's own header brief catalogues four bugs
    from.
    """

    def setUp(self):
        self.js = _read("ext_vt.js")
        self.css = _read("ext_vt.css")
        self.launch = _read("ext_launch.js")

    # ----- 1. the sidebar button -----

    def _side_controls(self):
        return _body_until(self.launch, "function buildSideControls()", ["function buildPicker"])

    def test_manage_button_is_in_the_same_group_as_the_other_two(self):
        body = self._side_controls()
        i = body.index('<div class="sidenewgroup">')
        group = body[i:body.index('"</div>"', i)]
        for btn in ("sidenewcwdbtn", "sidenewclaudebtn", "sidemanagetermbtn"):
            self.assertIn(btn, group, "%s is not inside the .sidenewgroup markup" % btn)
        # same idiom as its two neighbours: same classes, and a real title (not an icon alone)
        self.assertIn('class="mini extlaunchbtn" id=sidemanagetermbtn', group)
        self.assertIn('title="See every terminal running right now', group)

    def test_manage_button_is_not_host_gated(self):
        """conventions: no control hidden by host or viewport. This has to work from a phone or a
        tablet over a tunnel exactly like every other panel in the app."""
        body = self._side_controls()
        self.assertNotIn("localOnly", body)
        self.assertNotIn("location.hostname", body)
        # ... and the terminal module it drives gained no host gate either
        self.assertNotIn("location.hostname", self.js)

    def test_button_calls_the_terminal_module_instead_of_reimplementing_it(self):
        """ext_launch.js adds the button; ext_vt.js owns the terminal domain — the same seam the
        detail-pane buttons already use (window.ExtVT.open(cur, ...))."""
        self.assertIn("window.ExtVT.manage()", self.launch)
        self.assertIn("window.ExtVT = { open: openVT, manage: openManager };", self.js)
        for route in ("/api/term/list", "/api/term/close"):
            self.assertNotIn(route, self.launch,
                             "%s is being called from ext_launch.js -- terminal logic belongs in "
                             "ext_vt.js" % route)

    # ----- 2. the shared row renderer (the assertion that actually prevents the fork) -----

    def test_manager_and_cap_block_share_exactly_one_row_renderer(self):
        """Mirrors test_toolbar_is_built_once_and_shared_by_both_renderers: a raw COUNT, so a
        future edit that hand-rolls a second row for either caller changes the number."""
        self.assertIn("function buildTermRow(", self.js)
        self.assertEqual(self.js.count("buildTermRow("), 3,   # 1 definition + 2 call sites
                         "buildTermRow should be defined once and called from both the cap block "
                         "and the manager panel")
        cap = _body_until(self.js, "function renderCapBlock(", ["function openVT("])
        mgr = _body_until(self.js, "function renderManagerBody(", ["function peekTerm("])
        self.assertIn("buildTermRow(", cap)
        self.assertIn("buildTermRow(", mgr)
        # ... and neither caller still hand-rolls the row DOM alongside it
        for hand_rolled in ('className = "vtcaprow"', 'className = "vtcaplabel"'):
            self.assertNotIn(hand_rolled, cap)
            self.assertNotIn(hand_rolled, mgr)
        row = _body_until(self.js, "function buildTermRow(", ["function renderCapBlock("])
        self.assertIn('row.className = "vtcaprow";', row)
        self.assertIn('label.className = "vtcaplabel";', row)
        self.assertIn('b.className = "vtcapx";', row)
        # every row still shows command · cwd · age, all from the SERVER's own fields
        self.assertIn('(t.cmd || "shell")', row)
        self.assertIn("t.cwd", row)
        self.assertIn("t.started", row)

    def test_row_action_buttons_carry_titles_and_accessible_names(self):
        row = _body_until(self.js, "function buildTermRow(", ["function renderCapBlock("])
        self.assertIn("b.title = a.title;", row)
        self.assertIn('b.setAttribute("aria-label", a.aria || a.title);', row)

    # ----- 3. the cap number is the server's -----

    def test_max_comes_from_the_server_response_not_a_client_constant(self):
        """Mirrors test_cap_message_is_the_servers_text_not_a_client_copy_of_the_number: the
        client renders server policy (conventions rule 5), so `max` is read off
        GET /api/term/list and the number itself appears nowhere in the JS."""
        refresh = _body_until(self.js, "function refreshManager(", ["function renderManagerBody("])
        self.assertIn('fetch("/api/term/list")', refresh)
        self.assertIn("res.j.max", refresh)
        mgr = _body_until(self.js, "function renderManagerBody(", ["function peekTerm("])
        self.assertIn('(max ? " of " + max : "")', mgr)
        for hardcoded in ("max 4", "max 12", "MAX_TERMS", "MAX_PTYS"):
            self.assertNotIn(hardcoded, self.js)

    # ----- 4. close-all must be confirmed -----

    def test_close_all_requires_a_confirmation_step_before_it_kills_anything(self):
        """A misclick here destroys real work: it SIGKILLs every running terminal, Claude sessions
        included. The first click may only ARM the button — it must not reach the close route."""
        mgr = _body_until(self.js, "function renderManagerBody(", ["function peekTerm("])
        i = mgr.index("if (mgrConfirmAll) {")
        j = mgr.index("} else {", i)
        armed, unarmed = mgr[i:j], mgr[j:]
        self.assertIn("closeAll(terminals)", armed)
        self.assertIn("Cancel", armed)                       # an explicit way back out
        self.assertIn("are you sure — this kills ", armed)   # and it says what it is about to do
        self.assertNotIn("closeAll(", unarmed,
                         "the un-armed Close all button reaches the kill path directly -- the "
                         "first click must only arm the confirmation")
        self.assertIn("mgrConfirmAll = true;", unarmed)
        # the armed state can never survive a dismissal or a re-open
        self.assertIn("mgrConfirmAll = false;",
                      _body_until(self.js, "function openManager(", ["function refreshManager("]))
        self.assertIn("mgrConfirmAll = false;",
                      _body_until(self.js, "function closeManager(", ["function openManager("]))
        # no bulk server route was invented -- close-all loops the existing per-tty one
        close_all = _body_until(self.js, "function closeAll(", ["window.ExtVT ="])
        self.assertIn("closeTty(t.tty)", close_all)
        self.assertIn('"/api/term/close"',
                      _body_until(self.js, "function closeTty(", ["function _latchManager("]))

    # ----- 5. peek -----

    def test_peek_url_carries_tty_and_sid_and_mode(self):
        """Peek opens the standalone ?tty= tab. Now that the list carries `session` and `mode`,
        both ride along so the peeked terminal gets its full context bar, not a degraded one."""
        peek = _body_until(self.js, "function peekTerm(", ["function closeTty("])
        self.assertIn('"?tty=" + encodeURIComponent(t.tty)', peek)
        self.assertIn('"&sid=" + encodeURIComponent(t.session || "")', peek)
        self.assertIn('"&mode=" + encodeURIComponent(t.mode || "")', peek)
        self.assertIn('window.open(url, "_blank")', peek)
        self.assertIn("Popup blocked", peek)

    # ----- 6. the overlay lives on <body> -----

    def test_overlay_is_built_on_body_not_inside_the_sidebar_mount(self):
        """Mirrors test_term_launch.py's test_built_on_body_not_inside_the_sidebar_mount: .side
        gets a CSS transform for the phone drawer, and a transformed ancestor becomes the
        containing block for any position:fixed descendant -- which .overlay is."""
        build = _body_until(self.js, "function buildManager()", ["function closeManager("])
        self.assertIn("document.body.appendChild(mgrOverlay);", build)
        self.assertNotIn('getElementById("ext_launch_side")', self.js)
        self.assertNotIn("mount.appendChild(mgrOverlay)", self.js)

    def test_panel_reuses_the_shared_modal_chrome_and_the_usual_dismissals(self):
        build = _body_until(self.js, "function buildManager()", ["function closeManager("])
        self.assertIn('mgrOverlay.className = "overlay";', build)
        self.assertIn('modal.className = "modal vtmgrmodal";', build)
        self.assertIn('mh.className = "mh";', build)
        self.assertIn('mgrBodyEl.className = "mb vtmgrmb";', build)
        self.assertIn("if (ev.target === mgrOverlay) closeManager();", build)   # backdrop click
        self.assertIsNotNone(
            re.search(r'if \(ev\.key !== "Escape"\) return;\s*'
                      r'if \(!mgrOverlay \|\| mgrOverlay\.style\.display !== "flex"\) return;\s*'
                      r'closeManager\(\);', build),
            "Escape must close this overlay, and only while it is the one showing")
        # the panel's own ✕ is a DISMISSAL, not a kill -- say so, since the row ✕ IS a kill
        self.assertIn("Close this panel — every terminal keeps running", build)

    # ----- 7. server owns the truth; failures are surfaced -----

    def test_a_close_refreshes_from_the_server_rather_than_mutating_the_local_list(self):
        one = _body_until(self.js, "function closeOneFromManager(", ["function closeAll("])
        self.assertIn("_refreshAfterReap();", one)
        self.assertNotIn("splice(", one)
        self.assertIn("toast(", one)                       # failures surface, never silently
        self.assertIn("Couldn't close that terminal", one)
        close_all = _body_until(self.js, "function closeAll(", ["window.ExtVT ="])
        self.assertIn("_refreshAfterReap();", close_all)
        self.assertIn("toast(", close_all)
        self.assertNotIn("splice(", close_all)
        # ... and the refresh really is a server round-trip, delayed by ONE shared beat: a pty
        # leaves the list when the reader thread notices EOF, not when /api/term/close returns, so
        # refreshing on the response alone redraws a row for a terminal that is already dead.
        # Same 250ms the cap block's retry already waits for the same reason.
        helper = _body_until(self.js, "function _refreshAfterReap(", ["function _latchManager("])
        self.assertIn("setTimeout(refreshManager, _REAP_SETTLE_MS)", helper)
        self.assertIn("var _REAP_SETTLE_MS = 250;", self.js)

    def test_empty_state_and_a_failed_fetch_are_both_handled(self):
        mgr = _body_until(self.js, "function renderManagerBody(", ["function peekTerm("])
        self.assertIn("if (!terminals.length) {", mgr)
        self.assertIn("no terminals running", mgr)
        refresh = _body_until(self.js, "function refreshManager(", ["function renderManagerBody("])
        self.assertIn(".catch(function (e)", refresh)
        self.assertIn("failed to reach the server", refresh)
        self.assertIn("if (!res.ok) {", refresh)
        self.assertIn("esc(", refresh)             # server text never reaches raw innerHTML

    def test_kill_wording_distinguishes_it_from_merely_detaching(self):
        """POST /api/term/close SIGKILLs the process group; the terminal modal's own ✕ only stops
        watching. The user must be able to tell those apart from the control itself."""
        mgr = _body_until(self.js, "function renderManagerBody(", ["function peekTerm("])
        self.assertIn("process group", mgr)
        self.assertIn("SIGKILL", mgr)
        self.assertIn("nothing is killed", mgr)    # ... and peek says plainly that it is harmless

    # ----- 8. responsive -----

    def test_panel_is_usable_on_phone_and_tablet(self):
        """The rows inherit the cap block's responsive behaviour by BEING the cap block's rows
        (buildTermRow) rather than by a parallel rule; only the panel's own chrome needs its own
        breakpoints, and it must have one in each narrow band."""
        self.assertIn(".vtmgrmodal { width: min(720px, 100%); }", self.css)
        self.assertIn(".vtmgrfoot {", self.css)
        foot = self.css[self.css.index(".vtmgrfoot {"):
                        self.css.index("}", self.css.index(".vtmgrfoot {"))]
        self.assertIn("flex-wrap: wrap;", foot)
        self.assertNotIn("width:", foot)               # no fixed widths anywhere in the panel
        tail = self.css[self.css.index("/* ---- manager panel: narrow breakpoints"):]
        self.assertIn("@media(min-width:601px) and (max-width:900px) {", tail)   # tablet
        self.assertIn("@media(max-width:600px) {", tail)                          # phone
        self.assertIn(".vtmgrfoot", tail)
        self.assertIn(".vtcaprow { flex-wrap: wrap; }", tail)   # the shared rows wrap on a phone
        self.assertNotIn("display: none", tail)                 # nothing hidden by viewport

    # ----- 9. it actually reaches the served page -----

    def test_manager_survives_into_the_served_page(self):
        page = build_page()
        for marker in ("sidemanagetermbtn", "window.ExtVT.manage()", "buildTermRow",
                       "/api/term/list", ".vtmgrfoot", "vtmgrmodal"):
            self.assertIn(marker, page)


if __name__ == "__main__":
    unittest.main()
