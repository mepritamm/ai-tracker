"""Regression tests for two board-tabs fixes (both scoped to
aitracker/web/ext_cr_board.js / ext_cr_board.css):

TASK — owner ruling on board sort order: `boardTiles()`'s comparator used to
tie-break on `pinned` before recency (`RANK` first, then pinned, then mtime).
The owner ruled pinned is no longer a board sort key at all — attention rank
first, then purely most-recent-activity, full stop. Pinned stays a marker
(the pin glyph / `--state-pinned` accent) and a triage filter only. Symptom
that made this a real bug, not a style nit: four pinned sessions aged
22h/3d/7d/8d sat above a session touched 8 MINUTES ago.

TASK — a triage cell whose count is 0 ("Waiting on you" reads 0, click it,
board says "Nothing matches that filter right now." / footer says "0 of 0")
is indistinguishable from a broken control even though the filtering is
correct. Three legibility fixes, all covered here:
  (a) the board's empty state names which bucket is empty (BOARD_EMPTY_COPY,
      keyed by filter key), instead of one generic sentence for every filter;
      the no-filter copy is unchanged.
  (b) a 0-count triage cell gets a `cr-triage-cell--empty` modifier class
      (dimmed via CSS opacity, still a real focusable/clickable <button>);
      an *active* 0-count cell must still render at full strength (CSS
      specificity check).
  (c) the cap footer, when a filter is active and nothing matched, states the
      bucket is empty instead of the misleading "0 of 0" + "never shows more
      than N tiles" pairing.

Idiom: reuses tests/test_cr_rail_polish.py's real-page/real-DOM harness
(_REAL_DOM_PREAMBLE/_REAL_DOM_MID/_run_node/_read_page/_extract_script_content/
make_session) rather than a second copy of it — this drives the REAL
page.build_page() bundle end to end (mount()/update()/setFilter()), not an
isolated reimplementation.
"""
import json
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

from tests.test_cr_rail_polish import (  # noqa: E402
    _REAL_DOM_PREAMBLE, _REAL_DOM_MID, _run_node, _read_page,
    _extract_script_content, make_session, NOW, _HAS_NODE,
)


def _extract_style_content(html):
    m = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
    if not m:
        raise AssertionError("No <style> tag found in assembled page")
    return m.group(1)


# ---------------------------------------------------------------------------
# Sort ruling: RANK first, then pure recency -- no pinned tiebreak.
# ---------------------------------------------------------------------------

_SORT_JS_TAIL = r"""
var NOW = %(now)d;

// (1) THE OWNER'S ACTUAL COMPLAINT: a recent unpinned session must sort ahead
// of an older pinned one. Input order is deliberately pinned-first, so this
// only passes if boardTiles() actually reorders them.
var oldPinned = %(old_pinned)s;
var recentUnpinned = %(recent_unpinned)s;
var tiles1 = window.CR.board.boardTiles([oldPinned, recentUnpinned], NOW);
var order1 = tiles1.filter(function (t) { return t.kind === 'session'; })
                    .map(function (t) { return t.session.id; });

// (2) Attention rank still wins over recency: an older WAITING session still
// leads a newer plain IDLE one.
var waitingOlder = %(waiting_older)s;
var idleNewer = %(idle_newer)s;
var tiles2 = window.CR.board.boardTiles([idleNewer, waitingOlder], NOW);
var order2 = tiles2.filter(function (t) { return t.kind === 'session'; })
                    .map(function (t) { return t.session.id; });

var out = { order1: order1, order2: order2 };
console.log("===CR_SORT_JSON_START===");
console.log(JSON.stringify(out));
"""


def _extract_sort_json(stdout):
    marker = "===CR_SORT_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _sort_driver_js():
    bundle_js = _extract_script_content(_read_page())
    old_pinned = make_session("old_pinned", NOW - 7 * 86400, pinned=True, ended=True)
    recent_unpinned = make_session("recent_unpinned", NOW - 8 * 60, pinned=False, ended=True)
    waiting_older = make_session("waiting_older", NOW - 7 * 86400, waiting=True)
    idle_newer = make_session("idle_newer", NOW - 301, ended=True)  # just outside the 300s live window -> idle
    tail = _SORT_JS_TAIL % {
        "now": NOW,
        "old_pinned": json.dumps(old_pinned),
        "recent_unpinned": json.dumps(recent_unpinned),
        "waiting_older": json.dumps(waiting_older),
        "idle_newer": json.dumps(idle_newer),
    }
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardSortsByAttentionThenRecencyNotPinned(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _sort_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Sort driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_sort_json(stdout)

    def test_recent_unpinned_sorts_ahead_of_older_pinned(self):
        self.assertEqual(self.OUT["order1"], ["recent_unpinned", "old_pinned"],
                          "pinned must no longer hoist an older session above a more recent one")

    def test_attention_rank_still_beats_recency(self):
        self.assertEqual(self.OUT["order2"], ["waiting_older", "idle_newer"],
                          "a waiting session must still lead a newer idle one")


# ---------------------------------------------------------------------------
# Empty-state legibility: (a) named copy per filter, (b) empty-cell modifier
# class, (c) cap-footer empty-filter sentence. All three driven through one
# real mount()/update()/setFilter() session.
# ---------------------------------------------------------------------------

_EMPTY_JS_TAIL = r"""
var NOW = %(now)d;
// ONE root/mount for this whole scenario -- window.CR.board is a SINGLETON
// (createBoard() is only ever called once, at the bottom of the bundle), so
// a second mount() call on a different root element redirects the shared
// `els`/`lastState` closure state to that new root, silently freezing the
// first root's DOM at whatever it last rendered. Sequencing every render
// through one root via update() (never a second mount()) is what keeps
// every query below live.
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, {});

function boardEmptyText() {
  var els = queryAllReal(root, '.cr-board-empty');
  return els.length ? allTextIn(els[0]) : null;
}
function capfooterText() {
  var els = queryAllReal(root, '.cr-capfooter');
  return els.length ? allTextIn(els[0]) : '';
}
function cellClasses(key) {
  var els = queryAllReal(root, '.cr-triage-cell--' + key);
  return els.length ? Array.from(els[0]._classes) : null;
}

var out = {};

// Default (no filter) copy with genuinely ZERO sessions -- must be
// byte-for-byte unchanged from before this fix.
window.CR.board.update({ sessions: [], now: NOW });
out.noFilterEmptyText = boardEmptyText();

// One AWAITING session so that bucket's count is non-zero (1) while
// working/flagged/pinned all stay at 0 -- lets a single fixture cover both
// "own copy per empty filter" (working/flagged/pinned all empty; awaiting
// isn't a candidate for the *board-empty* text since it always has a tile)
// and "a non-zero cell carries no empty modifier". Same root, same mount --
// just a fresh update() with a different session list.
var sessions = [%(awaiting)s];
window.CR.board.update({ sessions: sessions, now: NOW });

// awaiting has a real tile (count 1), so its own filter is non-empty --
// confirms the non-zero cell gets no --empty class and the filtered board
// is NOT the generic/empty branch.
window.CR.board.setFilter('awaiting');
out.awaitingCellClasses = cellClasses('awaiting');
out.awaitingBoardEmptyWhileNonEmpty = boardEmptyText();   // expect null: tiles exist
window.CR.board.setFilter('awaiting');   // toggle back off

var emptyKeys = ['working', 'flagged', 'pinned'];
out.perKeyEmptyText = {};
out.perKeyCapfooterText = {};
out.perKeyCellClasses = {};
emptyKeys.forEach(function (key) {
  window.CR.board.setFilter(key);
  out.perKeyEmptyText[key] = boardEmptyText();
  out.perKeyCapfooterText[key] = capfooterText();
  out.perKeyCellClasses[key] = cellClasses(key);
  window.CR.board.setFilter(key);   // toggle back off before the next key
});

// Active zero-count cell: filter to 'pinned' (count 0) and check it carries
// BOTH the empty and the active modifier at once -- the CSS specificity
// check (asserted separately, at the stylesheet level) is what makes the
// active look win visually; this proves the DOM precondition for it.
window.CR.board.setFilter('pinned');
out.activeZeroCountCellClasses = cellClasses('pinned');

console.log("===CR_EMPTY_JSON_START===");
console.log(JSON.stringify(out));
"""


def _extract_empty_json(stdout):
    marker = "===CR_EMPTY_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _empty_driver_js():
    bundle_js = _extract_script_content(_read_page())
    awaiting = make_session("only_awaiting", NOW - 5, waiting=True)
    tail = _EMPTY_JS_TAIL % {"now": NOW, "awaiting": json.dumps(awaiting)}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestTriageEmptyStateLegibility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _empty_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Empty-state driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_empty_json(stdout)

    def test_no_filter_empty_copy_is_unchanged(self):
        self.assertEqual(self.OUT["noFilterEmptyText"], "Nothing needs you right now.")

    def test_nonzero_cell_gets_no_empty_modifier(self):
        self.assertIsNotNone(self.OUT["awaitingCellClasses"])
        self.assertNotIn("cr-triage-cell--empty", self.OUT["awaitingCellClasses"])

    def test_filtering_to_a_nonempty_bucket_does_not_show_generic_empty_copy(self):
        self.assertIsNone(self.OUT["awaitingBoardEmptyWhileNonEmpty"])

    def test_each_empty_filter_gets_its_own_board_copy(self):
        expected = {
            "working": "Nothing is working right now.",
            "flagged": "No sessions have open flags.",
            "pinned": "No sessions are pinned.",
        }
        for key, text in expected.items():
            self.assertEqual(self.OUT["perKeyEmptyText"][key], text,
                              "filter=%r got board-empty text %r" % (key, self.OUT["perKeyEmptyText"][key]))
        # Sanity: the three empty-bucket sentences are genuinely distinct from
        # each other and from the generic/no-filter copy.
        texts = set(expected.values())
        texts.add("Nothing needs you right now.")
        self.assertEqual(len(texts), 4)

    def test_each_empty_filter_gets_a_true_capfooter_sentence_not_bare_zero_count(self):
        for key in ("working", "flagged", "pinned"):
            footer = self.OUT["perKeyCapfooterText"][key]
            self.assertNotIn("0 of 0", footer, "filter=%r footer still shows the bare '0 of 0' count" % key)
            self.assertNotIn("never shows more than", footer,
                              "filter=%r footer still claims tiles are being capped when nothing matched" % key)
        self.assertIn("No sessions are pinned.", self.OUT["perKeyCapfooterText"]["pinned"])
        self.assertIn("Nothing is working right now.", self.OUT["perKeyCapfooterText"]["working"])
        self.assertIn("No sessions have open flags.", self.OUT["perKeyCapfooterText"]["flagged"])
        # "Scroll for the rest" affordance is kept even when the filter is empty.
        for key in ("working", "flagged", "pinned"):
            self.assertIn("Scroll for the rest", self.OUT["perKeyCapfooterText"][key])

    def test_zero_count_cells_carry_the_empty_modifier_class(self):
        for key in ("working", "flagged", "pinned"):
            classes = self.OUT["perKeyCellClasses"][key]
            self.assertIsNotNone(classes, "cell for %r not found" % key)
            self.assertIn("cr-triage-cell--empty", classes)

    def test_active_zero_count_cell_still_carries_the_active_class_alongside_empty(self):
        """DOM-level precondition for the CSS specificity override (checked at the
        stylesheet level in TestTriageEmptyCellCss below): an active filter on a
        0-count bucket keeps BOTH modifier classes -- the JS never suppresses
        --empty just because the cell is also --active, so the CSS override is
        what has to win."""
        classes = self.OUT["activeZeroCountCellClasses"]
        self.assertIsNotNone(classes)
        self.assertIn("cr-triage-cell--empty", classes)
        self.assertIn("cr-triage-cell--active", classes)


class TestTriageEmptyCellCss(unittest.TestCase):
    """Text-level checks (no node needed) that the empty-cell dimming rule and
    its active-beats-empty override actually exist in the assembled CSS, and
    that the override selector is strictly MORE specific -- not merely later
    in source order, which would be fragile against future edits."""

    @classmethod
    def setUpClass(cls):
        cls.css = _extract_style_content(_read_page())

    def test_empty_cell_dim_rule_exists(self):
        self.assertIn(".tracker-next .cr-triage-cell--empty { opacity: .5; }", self.css)

    def test_active_beats_empty_override_exists(self):
        self.assertIn(
            ".tracker-next .cr-triage-cell--empty.cr-triage-cell--active { opacity: 1; }", self.css)

    def test_override_selector_is_strictly_more_specific(self):
        """A same-element compound selector with N classes always beats one with
        fewer classes, regardless of source order. Counts the class-selector
        tokens (`.foo`) in each rule's selector to verify the override actually
        has MORE of them than the plain empty rule -- not just relying on it
        appearing later in the file."""
        plain_selector = ".tracker-next .cr-triage-cell--empty"
        active_selector = ".tracker-next .cr-triage-cell--empty.cr-triage-cell--active"
        plain_specificity = plain_selector.count(".")
        active_specificity = active_selector.count(".")
        self.assertGreater(active_specificity, plain_specificity)


if __name__ == "__main__":
    unittest.main()
