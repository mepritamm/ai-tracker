"""Cross-view uniformity pins, from an adversarial review of both UIs.

The project rule (.claude/rules/conventions.md) is that a capability lands on the
shared seam so every path inherits it — "two parallel implementations of one
capability is the next bug". These tests pin three defects that rule was meant to
prevent and did not, because nothing was checking:

1. `sessionState()` grew a 'failing' state, but STATE_DOT_CLASS never did. The
   lookup falls back to '' — the SAME class as idle — so a live failing session
   drew an idle-grey dot while the very same tile's text read "fail: <cmd>". In
   the collapsed orb rail the dot is the ONLY state signal, so there it was the
   entire signal, silently wrong.

2. `fail_cmd` is on the shared list dict for every provider (registry.py sets it
   on every session). The Control Room read it nine times; the classic sidebar
   read it zero. A failing session was invisible in one of the two UIs.

A third finding from that review — that the rail footer's "N more" wrongly counts
agent sessions — was investigated and REJECTED. tests/test_cr_rail_polish.py pins
that behaviour deliberately: a session folded into an agent GROUP row is not shown
as its own row, so counting it as "more" is the intent, not a bug. Recorded here
because the reasoning is easy to re-derive and get wrong a second time.

The first test is the important one: it is structural, so a state added tomorrow
without a colour fails here instead of shipping as an invisible grey dot.
"""
import os
import re
import unittest

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


class TestEveryStateIsRenderable(unittest.TestCase):
    """Structural: whatever sessionState() can return must be renderable everywhere."""

    def setUp(self):
        self.js = _read("ext_cr_board.js")
        self.css = _read("ext_cr_board.css")

    def _states_from_rank(self):
        """RANK is the canonical list of states this app knows about."""
        m = re.search(r"var RANK = \{([^}]*)\}", self.js)
        self.assertIsNotNone(m, "RANK map not found")
        return set(re.findall(r"(\w+):", m.group(1)))

    def _keys_of(self, var_name):
        m = re.search(r"var " + var_name + r" = \{(.*?)\};", self.js, re.DOTALL)
        self.assertIsNotNone(m, var_name + " not found")
        return set(re.findall(r"(\w+):", m.group(1)))

    def test_every_state_has_a_dot_colour(self):
        """The defect: 'failing' was absent, so stateDotClass() returned '' and the
        dot was indistinguishable from idle."""
        states = self._states_from_rank()
        dot = self._keys_of("STATE_DOT_CLASS")
        missing = states - dot
        self.assertEqual(missing, set(),
                         "states with no dot class (they render as idle): %s" % sorted(missing))

    def test_every_state_has_an_orb_word(self):
        states = self._states_from_rank()
        missing = states - self._keys_of("ORB_STATE_WORD")
        self.assertEqual(missing, set(), "states with no spoken orb word: %s" % sorted(missing))

    def test_every_dot_class_has_a_colour_defined(self):
        """A class name in the map with no CSS rule behind it is the same bug one
        layer down."""
        for cls in self._keys_of("STATE_DOT_CLASS"):
            m = re.search(r"STATE_DOT_CLASS = \{(.*?)\};", self.js, re.DOTALL)
            body = m.group(1)
            got = re.search(cls + r":\s*'([^']*)'", body)
            self.assertIsNotNone(got, cls)
            name = got.group(1)
            if not name:
                continue  # idle is deliberately the bare default
            self.assertIn(".cr-rail-dot." + name, self.css,
                          name + " has no rail-dot colour")

    def test_failing_is_specifically_covered(self):
        self.assertIn("failing: 'is-failing'", self.js)
        self.assertIn(".cr-rail-dot.is-failing", self.css)
        self.assertIn(".cr-orb-pip.is-failing", self.css)


class TestFailCmdReachesBothUIs(unittest.TestCase):
    def test_the_classic_sidebar_shows_a_failure_at_all(self):
        """It read fail_cmd zero times before this; the server sends it for every
        provider, so one whole UI was blind to a failing session."""
        app = _read("app.js")
        self.assertIn("s.fail_cmd", app, "classic UI still ignores fail_cmd")
        self.assertIn("failbadge", app)
        self.assertIn(".failbadge{", _read("app.css"), "badge has no styling")

    def test_the_control_room_still_shows_it(self):
        self.assertIn("fail_cmd", _read("ext_cr_board.js"))


if __name__ == "__main__":
    unittest.main()
