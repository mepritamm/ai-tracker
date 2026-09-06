"""Pins the Sessions destination's progress widget, and — more importantly — pins
that it is the SAME widget the board tiles draw.

`.claude/rules/conventions.md` rule 4: a capability lands on the shared renderer,
never forked per view, because "two parallel implementations of one capability is
the next bug". "How far along is this session" had already been rendered three
different ways in this codebase:

  1. board tiles      -> todoTicks(), a segmented tick bar + "4 of 12"
  2. rail rows        -> railTodoLabel(), a compact "4/12"
  3. classic sidebar  -> the progress ring's "4 of 12 tasks"

The Sessions destination now calls todoTicks() rather than becoming a fourth. The
test that matters is therefore not "does a widget appear" but "is it the same
function", which is why the assertions below are about reuse.
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


def _board_js():
    with open(os.path.join(_WEB, "ext_cr_board.js"), encoding="utf-8") as fh:
        return fh.read()


def _board_css():
    with open(os.path.join(_WEB, "ext_cr_board.css"), encoding="utf-8") as fh:
        return fh.read()


class TestSessionsProgressReusesTheTileWidget(unittest.TestCase):
    def setUp(self):
        self.js = _board_js()
        self.css = _board_css()

    def test_it_calls_todo_ticks_rather_than_reimplementing_it(self):
        """The whole point. If this ever grows its own tick loop, the two views
        drift the moment either is touched."""
        self.assertIn("function railRichProgress(s)", self.js)
        i = self.js.find("function railRichProgress(s)")
        body = self.js[i:self.js.find("\n    }", i)]
        self.assertIn("todoTicks(s)", body, "must reuse the board tile's builder")
        # and it must NOT have grown a second tick loop of its own
        self.assertNotIn("cr-tick", body, "a second tick renderer has appeared")

    def test_there_is_still_exactly_one_tick_builder(self):
        self.assertEqual(self.js.count("function todoTicks("), 1)

    def test_the_rail_is_untouched_and_stays_compact(self):
        """Rail rows are three tight lines already; the rich block is opt-in, so a
        regression that switched it on everywhere would break the rail's layout."""
        self.assertIn("var rich = !!(opts && opts.rich);", self.js)
        # the rail's own render passes no opts at all
        self.assertIn("var rowOpts = (opts && opts.rich) ? { rich: true } : null;", self.js)
        self.assertIn("function railTodoLabel(s)", self.js, "the compact label still exists")

    def test_both_sessions_render_paths_ask_for_rich_rows(self):
        """There are TWO ways the Sessions list renders — the paged path and the
        search-results path. Missing either leaves half the tab inconsistent."""
        self.assertIn("railRow(s, now, { rich: true })", self.js, "search path")
        self.assertRegex(self.js, r"pageSize: sessionsPageSize, rich: true", "paged path")

    def test_rich_rows_do_not_show_the_count_twice(self):
        """The tick bar already captions '4 of 12'; leaving the compact '4/12' on
        the same row would print the same number twice."""
        self.assertIn("var todoLabel = rich ? '' : railTodoLabel(s);", self.js)

    def test_background_agent_count_is_worded_not_a_bare_number(self):
        self.assertIn("' background agent'", self.js)
        self.assertIn("(s.bg === 1 ? '' : 's')", self.js, "must not say '1 background agents'")


class TestSessionsProgressStyling(unittest.TestCase):
    def setUp(self):
        self.css = _board_css()

    def test_rich_rows_wrap_so_the_widget_gets_its_own_line(self):
        self.assertRegex(self.css, r"\.cr-rail-row--rich\s*\{[^}]*flex-wrap:\s*wrap")
        self.assertRegex(self.css, r"\.cr-rail-progress\s*\{[^}]*flex:\s*0 0 100%")

    def test_rich_rows_do_not_re_align_every_other_rail_row(self):
        """`.cr-rail-row` is `align-items: center` app-wide. Flipping it to
        flex-start for wrapping would shift the dot and title on every row."""
        i = self.css.find(".cr-rail-row--rich {")
        rule = self.css[i:self.css.find("}", i)]
        self.assertNotIn("align-items", rule)

    def test_the_agent_label_scales_with_the_config_icon_size(self):
        """It sits next to a glyph, so a hard px would desync from the slider."""
        i = self.css.find(".cr-rail-bg {")
        self.assertGreater(i, -1)
        rule = self.css[i:self.css.find("}", i)]
        self.assertIn("var(--ico-scale", rule)


class TestSessionsProgressReachesThePage(unittest.TestCase):
    def test_it_survives_into_the_assembled_page(self):
        page = _read_page()
        self.assertIn("railRichProgress", page)
        self.assertIn("cr-rail-progress", page)
        self.assertIn("cr-rail-row--rich", page)


if __name__ == "__main__":
    unittest.main()
