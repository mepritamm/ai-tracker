"""Regression tests for three control-room polish fixes in this pass:

1. THE NARRATION DIALOG RENDERED WHITE IN DARK THEME.
   Ground truth (read from the real call path, not assumed): a narration
   entry opened from the control view (ext_cr_detail.js's openTimelineEntry())
   never opens one of ext_cr_dialogs.js's own `.cr`-scoped dialogs -- it calls
   app.js's shared openText()/#msgmodal, the SAME static overlay classic's own
   "Narration" row (openMsg(), app.js) has always used. #msgmodal is a real
   node in index.html, a SIBLING of #nextRoot -- never its descendant -- so it
   never inherited Control Room's `--surface-*`/`--text-*` tokens, and instead
   rendered classic's OWN (differently-hued, but separately theme-synced)
   palette -- a dialog opened FROM the control view that didn't "clearly
   maintain the color theme for the dark-themed control view."
   THE FIX (aitracker/web/ext_cr_boot.css): a block of rules repointing
   #msgmodal's own children at Control Room's real dark tokens, every one
   gated with the general sibling combinator on
   `#nextRoot.is-dark:not([hidden]) ~ #msgmodal` -- `.is-dark` is Control
   Room's own resolved-dark flag, `:not([hidden])` is "the 'next' UI is the
   one currently shown" -- so classic's own default appearance (#nextRoot
   hidden, whichever theme its own button last picked) can never match this
   selector and is left completely untouched.
   What's asserted below: every rule this fix added that mentions #msgmodal
   carries that exact gate (nothing can leak into classic's default), and
   that #nextRoot genuinely precedes #msgmodal in the served page's DOM order
   (the general sibling combinator `~` only matches a LATER sibling -- if a
   future edit reordered index.html, this fix would silently stop firing).
   A real "does this actually paint dark in a browser" check is NOT something
   this stdlib-only, browser-less test suite can perform -- said plainly per
   this task's own instructions, rather than faked with a hollow assertion.

2. THREE HARDCODED SCRIM/BACKDROP COLOURS, NO LIGHT/DARK HANDLING.
   ext_cr_dialogs.css's .cr-backdrop and ext_cr_boot.css's .cr-scrim were both
   a bare rgba() with no theme awareness. THE FIX: one new `--scrim` token
   (ext_cr.css), defined under both `.tracker-next` (light) and
   `.tracker-next.is-dark` (dark), with both sites repointed at it (a literal
   fallback kept for safety, matching this file's own existing var()-with-
   fallback convention). ext_cr_board.css's third site (.cr-rail-scrim) is
   OUT OF SCOPE here -- owned by another agent this pass.

3. THE TERMINAL "CLOSE" BUTTON HAD NO VISIBLE LABEL.
   Every sibling in the same terminal header/control-bar chrome (Config,
   Help, External terminal, New tab, Manage terminals, Theme, Copy, Kill, ...)
   pairs an icon with a plain-text word; Close shipped icon-only, readable
   only via its title/aria-label. THE FIX (ext_cr_term.js): the same
   icon-span + text-node markup Config/Help already use, added inside the
   existing `cr-term-close` button (title/aria-label and the button's own
   class -- kept separate from `cr-term-kill` -- both left untouched, so the
   Close-vs-Kill distinction and the "detaches, does not kill" explanation
   both survive).

IDIOM: page.build_page() assembles the real served page from the real source
files (aitracker/page.py) -- these tests read that assembled output (and, for
the scoping proof, the real source CSS file itself) rather than a hand-copied
paraphrase, so a future edit that moves the markup/selectors fails these
tests loudly instead of leaving them silently testing stale text.
"""
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

_WEB = os.path.join(_ROOT, "aitracker", "web")


def _read_page():
    from aitracker import page
    return page.build_page()


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


class TestTerminalCloseButtonHasVisibleLabel(unittest.TestCase):
    """Task 3: aitracker/web/ext_cr_term.js's cr-term-close button."""

    def _close_button_markup(self, html):
        m = re.search(r'<button[^>]*class="cr-term-close"[^>]*>.*?</button>', html, re.DOTALL)
        self.assertIsNotNone(m, "cr-term-close button not found in the served page")
        return m.group(0)

    def _close_button_inner_content(self, html):
        # ONLY what sits between the opening tag's `>` and `</button>` -- the
        # title/aria-label attributes both legitimately contain the word
        # "Close" too (the explanatory tooltip), so a check for a VISIBLE
        # label text node must never look inside the opening tag itself.
        m = re.search(r'<button[^>]*class="cr-term-close"[^>]*>(.*?)</button>', html, re.DOTALL)
        self.assertIsNotNone(m, "cr-term-close button not found in the served page")
        return m.group(1)

    def test_close_button_has_a_visible_close_text_node(self):
        inner = self._close_button_inner_content(_read_page())
        # Strip the aria-hidden icon span (Config/Help's own pattern) before
        # checking for a visible text node -- the icon glyph itself must not
        # be mistaken for the label.
        without_icon_span = re.sub(
            r'<span[^>]*class="cr-emo tn-emo"[^>]*>.*?</span>', "", inner, flags=re.DOTALL
        )
        self.assertIn("Close", without_icon_span)

    def test_close_button_still_uses_the_same_icon_plus_label_markup_as_config_help(self):
        html = _read_page()
        btn = self._close_button_markup(html)
        # Same wrapper class Config/Help already use for their icon span --
        # "no new pattern", per this task's own brief.
        self.assertIn('<span class="cr-emo tn-emo" aria-hidden="true">', btn)

    def test_close_button_keeps_its_explanatory_title_and_own_class(self):
        html = _read_page()
        opening_tag = re.search(r'<button[^>]*class="cr-term-close"[^>]*>', html).group(0)
        self.assertIn("Close — detaches, does not kill", opening_tag)
        self.assertIn('data-action="close"', opening_tag)
        # Must stay its OWN class, never merged into Kill's -- that is what
        # keeps Close from picking up Kill's destructive styling.
        self.assertNotIn("cr-term-kill", opening_tag)
        self.assertNotIn("btn-danger", opening_tag)


class TestMsgModalDarkThemeBridgeScopedToControlRoom(unittest.TestCase):
    """Task 1: aitracker/web/ext_cr_boot.css's #msgmodal dark-theme bridge."""

    GATE = "#nextRoot.is-dark:not([hidden]) ~ #msgmodal"

    def setUp(self):
        self.css = _read_web_file("ext_cr_boot.css")

    def test_the_gated_bridge_rules_exist(self):
        self.assertGreaterEqual(
            self.css.count(self.GATE), 10,
            "expected a full set of #msgmodal dark-theme bridge rules, all under the same gate",
        )

    def test_every_msgmodal_selector_is_the_pre_existing_hidden_rule_or_gated(self):
        # Every selector line that opens a rule mentioning #msgmodal must
        # either be the pre-existing [hidden] display:none rule (predates
        # this task) or start with the exact control-room-dark gate above --
        # proof that nothing this fix added can ever apply outside a
        # genuinely-active, genuinely-dark control room, i.e. never bleeds
        # into classic's own default #msgmodal appearance.
        selector_lines = re.findall(r"^([^\n{]*#msgmodal[^\n{]*)\{", self.css, re.MULTILINE)
        self.assertGreater(len(selector_lines), 0, "no #msgmodal selectors found at all")
        for raw in selector_lines:
            sel = raw.strip()
            if "[hidden]" in sel:
                continue
            self.assertTrue(
                sel.startswith(self.GATE),
                "found a #msgmodal selector not gated to control-room dark mode: %r" % sel,
            )

    def test_bridge_rules_only_use_real_control_room_dark_tokens(self):
        # Every var() this fix introduces must be one of the doc-defined
        # tokens ext_cr.css's `.tracker-next.is-dark` block already carries --
        # never an invented name. Spot-check a representative sample rather
        # than the entire token set.
        cr_css = _read_web_file("ext_cr.css")
        for token in (
            "--surface-raised", "--surface-sunken", "--surface-top",
            "--text-primary", "--text-secondary", "--text-muted", "--text-link", "--text-dusk",
            "--line-default", "--line-subtle", "--line-focus",
        ):
            self.assertIn(token + ":", cr_css, "%s is not a real token in ext_cr.css" % token)
            self.assertIn(token, self.css, "%s introduced in the bridge is never used" % token)

    def test_nextroot_precedes_msgmodal_in_served_dom_order(self):
        # The fix relies on the CSS general sibling combinator (`~`), which
        # only matches when #nextRoot appears BEFORE #msgmodal among their
        # shared parent's children -- if a future edit reordered index.html,
        # this fix would silently stop firing with no visible error.
        html = _read_page()
        next_root_at = html.index("id=nextRoot")
        msgmodal_at = html.index("id=msgmodal")
        self.assertLess(next_root_at, msgmodal_at)


class TestSharedScrimToken(unittest.TestCase):
    """Task 2: the shared `--scrim` token and its two owned call sites."""

    def setUp(self):
        self.cr_css = _read_web_file("ext_cr.css")

    def _block(self, selector, after=None):
        text = self.cr_css if after is None else self.cr_css[after:]
        start = text.index(selector + " {")
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i]
        raise AssertionError("unterminated block for %r" % selector)

    def test_scrim_token_defined_for_both_light_and_dark(self):
        light_block = self._block(".tracker-next")
        dark_start = self.cr_css.index(".tracker-next.is-dark {")
        dark_block = self._block(".tracker-next.is-dark")
        self.assertIn("--scrim:", light_block)
        self.assertIn("--scrim:", dark_block)
        # Different values per theme (the whole point of a token here) --
        # never the same literal copy-pasted into both blocks.
        light_val = re.search(r"--scrim:\s*([^;]+);", light_block).group(1).strip()
        dark_val = re.search(r"--scrim:\s*([^;]+);", dark_block).group(1).strip()
        self.assertNotEqual(light_val, dark_val)
        # Stays in the warm-stone family (never pure black) -- rgb, not rgba(0,0,0,...).
        self.assertNotIn("rgba(0,0,0", light_val)
        self.assertNotIn("rgba(0,0,0", dark_val)

    def test_owned_backdrop_sites_use_the_token(self):
        dialogs_css = _read_web_file("ext_cr_dialogs.css")
        boot_css = _read_web_file("ext_cr_boot.css")
        self.assertIn("var(--scrim,", dialogs_css)
        self.assertIn("var(--scrim,", boot_css)
        # The two rules these replaced (.cr-backdrop / .cr-scrim) no longer
        # hardcode a bare, un-themed rgba() as their *only* value.
        backdrop = re.search(r"\.cr \.cr-backdrop \{([^}]*)\}", dialogs_css).group(1)
        scrim = re.search(r"\.cr-scrim \{([^}]*)\}", boot_css).group(1)
        self.assertIn("var(--scrim", backdrop)
        self.assertIn("var(--scrim", scrim)


if __name__ == "__main__":
    unittest.main()
