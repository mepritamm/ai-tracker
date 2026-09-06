"""Board-tabs colour tokens — verifies the per-state triage/tile colours are
defined in BOTH theme blocks of the served page (light `.tracker-next` and
dark `.tracker-next.is-dark`), never only one — the exact defect class this
one-<style>-tag page can't catch any other way (a raw hex slipping in, or a
token defined in only one theme, silently renders wrong instead of failing
to render at all).

Run: python -m unittest discover -s tests   (or: make check)
"""
import re
import unittest

from aitracker.page import build_page


def _style_block(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    assert m, "served page has no <style> block"
    return m.group(1)


def _theme_block(css, dark):
    # Same light-block-then-dark-block split every other pass over this file
    # uses: light tokens live in the bare `.tracker-next { ... }` rule, dark
    # overrides in the `.tracker-next.is-dark { ... }` rule right after it.
    marker = ".tracker-next.is-dark {"
    idx = css.index(marker)
    if dark:
        # from the dark marker to the NEXT top-level rule close — good enough
        # since nothing else redeclares --state-pinned/--text-dusk after it.
        return css[idx: idx + 4000]
    return css[:idx]


class StateColorTokensTest(unittest.TestCase):
    def setUp(self):
        self.css = _style_block(build_page())
        self.light = _theme_block(self.css, dark=False)
        self.dark = _theme_block(self.css, dark=True)

    def test_pinned_state_token_defined_both_themes(self):
        # --state-pinned must exist in BOTH theme blocks (never given its
        # only definition in one) and must alias the app's existing blue-
        # leaning --text-dusk accent, not a freshly invented hex.
        self.assertIn("--state-pinned:", self.light)
        self.assertIn("--state-pinned:", self.dark)
        self.assertIn("var(--text-dusk)", self.light)
        self.assertIn("var(--text-dusk)", self.dark)

    def test_existing_state_tokens_still_dual_themed(self):
        # awaiting/working(thinking)/flagged/failing(failed)/landed(done)/idle
        # already had dual-themed tokens before this change; guard against a
        # future edit accidentally collapsing one to a single theme block.
        for tok in ("--state-awaiting", "--state-thinking", "--state-flagged",
                    "--state-failed", "--state-done", "--state-idle"):
            self.assertIn(tok + ":", self.light, tok + " missing from light theme")
            self.assertIn(tok + ":", self.dark, tok + " missing from dark theme")

    def test_pinned_triage_cell_uses_pinned_token(self):
        self.assertIn(
            ".cr-triage-cell--pinned .cr-triage-count { color: var(--state-pinned); }",
            self.css)
        self.assertIn(
            ".cr-triage-cell--pinned.cr-triage-cell--active { border-bottom-color: var(--state-pinned); }",
            self.css)

    def test_board_tile_awaiting_rule_present_and_token_backed(self):
        # DEFECT 1: a non-hero awaiting tile previously had no colour at all
        # (only .cr-tile--hero, capped at one tile, ever carried the awaiting
        # tint). The rule must exist and must be built from the awaiting
        # family tokens, all dual-themed.
        self.assertIn(
            ".tracker-next .cr-tile--awaiting {\n"
            "  background: var(--surface-awaiting);\n"
            "  border-color: var(--line-awaiting);\n"
            "  border-left: 3px solid var(--state-awaiting);\n"
            "}",
            self.css)
        for tok in ("--surface-awaiting", "--line-awaiting", "--state-awaiting"):
            self.assertIn(tok + ":", self.light, tok + " missing from light theme")
            self.assertIn(tok + ":", self.dark, tok + " missing from dark theme")

    def test_board_tile_idle_rule_present_and_token_backed(self):
        # DEFECT 2: idle tiles are new on the board (boardTiles() now
        # backfills with idle sessions instead of excluding them) and had no
        # styling, so they were indistinguishable from an awaiting tile.
        self.assertIn(
            ".tracker-next .cr-tile--idle { background: var(--surface-sunken); "
            "border-color: var(--line-strong); }",
            self.css)
        for tok in ("--surface-sunken", "--line-strong"):
            self.assertIn(tok + ":", self.light, tok + " missing from light theme")
            self.assertIn(tok + ":", self.dark, tok + " missing from dark theme")


if __name__ == "__main__":
    unittest.main()
