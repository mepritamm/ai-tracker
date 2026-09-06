"""Regression tests for the nine control-room SESSION RAIL defects found by
driving the REAL `page.build_page()` bundle through the node DOM harness.

Every one of these was reproduced against the assembled page before being
fixed — none is hypothetical:

  1. the rail dropped `agent:true, group:""` sessions entirely (rows, collapsed
     orbs AND the Sessions-destination count) because its `!s.agent` filter was
     not the complement of the agent-bucket pass's `s.agent && s.group`;
  2. `failing` — sessionState()'s sixth state — had no rail dot colour and the
     rail's own status badge called such a session "done" while the board, from
     the SAME derivation, painted it red with "fail: <cmd>";
  3. the SHARED uiState 'query' field was stored lowercased by the rail and
     case-preserved by classic, so typing "Normal" in classic's box emptied the
     rail;
  4. paneScroll()'s `if (liveEl.scrollTop)` treated a genuine scrollTop of 0 as
     "no live value", so a pane could never be scrolled back to the top;
  5. the agent-group row HTML-escaped a label that goes into a TEXT node, so a
     repo named `R&D` rendered as `R&amp;D`;
  6. the collapsed rail hides the search box and the live-only pill with
     `display: none` while still applying both filters;
  7. the "N more" footer counted sessions the current search had already thrown
     away ("scroll · 954 more" under an empty list);
  8. rail rows carry tabindex="0" but only the SEARCH INPUT's focus survived the
     full rebuild renderRail() does every 2s;
  9. the rail search had no empty state at all.

Harness: the same one the defects were found with — tests/test_cr_rail_polish's
`_REAL_DOM_PREAMBLE` / `_run_node` / `_read_page` / `make_session`, imported
rather than copied, driving the real assembled bundle under a tracked DOM stub.
"""
import json
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, _ROOT)

from tests.test_cr_rail_polish import (            # noqa: E402
    NOW, _HAS_NODE, _REAL_DOM_PREAMBLE, _REAL_DOM_MID,
    _extract_script_content, _read_page, _run_node, make_session,
)

_MARKER = "===CR_DEFECT_JSON_START==="

# Shared tail prologue: a real ctx (so 'view:changed' can be fired the way
# ext_cr_boot.js fires it), focus tracking (the harness's own focus() is a
# no-op), and small readers over the rendered tree.
_TAIL_PROLOGUE = r"""
var HANDLERS = {};
var CTX = {
  on: function (name, fn) { (HANDLERS[name] = HANDLERS[name] || []).push(fn); },
  emit: function (name, payload) { (HANDLERS[name] || []).forEach(function (fn) { fn(payload); }); },
  go: function () {}
};
function fire(name, payload) { (HANDLERS[name] || []).forEach(function (fn) { fn(payload); }); }

// The stub's makeReal() gives every element a no-op focus(); wrap the ones the
// BUNDLE creates so a focus() call is observable (defect 8) and so
// document.activeElement tracks it the way a browser's does.
var FOCUSED = null;
var _origCreate = document.createElement;
document.createElement = function (tag) {
  var el = _origCreate(tag);
  el.focus = function () { FOCUSED = el; document.activeElement = el; };
  return el;
};

var NOW = %(now)d;
var root = makeReal('div');
docBody.appendChild(root);
window.CR.board.mount(root, CTX);
var railEl = queryAllReal(root, '.cr-rail')[0];
var railList = queryAllReal(root, '.cr-rail-list')[0];
var railFooter = queryAllReal(root, '.cr-rail-footer')[0];

function attrs(sel, name) {
  return queryAllReal(root, sel).map(function (e) { return e.getAttribute(name); });
}
function classesOf(sel) {
  return queryAllReal(root, sel).map(function (e) { return Array.from(e._classes); });
}
function textsOf(sel) {
  return queryAllReal(root, sel).map(function (e) { return allTextIn(e); });
}
function railRowIds() { return attrs('.cr-rail-row', 'data-id'); }
function rowById(id) {
  return queryAllReal(root, '.cr-rail-row').filter(function (r) {
    return r.getAttribute('data-id') === id;
  })[0] || null;
}
function poll(sessions) { window.CR.board.update({ sessions: sessions, now: NOW }); }
function emit(out) {
  console.log("%(marker)s");
  console.log(JSON.stringify(out));
}
"""


def _driver(tail, now=NOW):
    bundle_js = _extract_script_content(_read_page())
    prologue = _TAIL_PROLOGUE % {"now": now, "marker": _MARKER}
    return "\n".join([_REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, prologue, tail])


def _run(tail, now=NOW):
    returncode, stdout, stderr = _run_node(_driver(tail, now))
    if returncode != 0:
        raise AssertionError(
            "rail-defect driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (returncode, stdout, stderr)
        )
    idx = stdout.find(_MARKER)
    if idx < 0:
        raise AssertionError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(_MARKER):].strip())


def _css():
    html = _read_page()
    m = max(re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL), key=len)
    return m


# ---------------------------------------------------------------------------
# DEFECT 1 — `agent:true, group:""` sessions vanished from the rail.
# ---------------------------------------------------------------------------

_D1_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);
out.railRowIds = railRowIds();

railEl.classList.add('cr-rail--collapsed');
poll(sessions);
out.orbLabels = attrs('.cr-orb', 'aria-label');
railEl.classList.remove('cr-rail--collapsed');

fire('view:changed', { view: 'sessions' });
poll(sessions);
out.sessionsPagerLabel = queryAllReal(root, '.cr-sessions-pager-label')[0].textContent;
out.sessionsRowIds = queryAllReal(root, '.cr-sessions-list')[0]
  .querySelectorAll('.cr-rail-row').map(function (r) { return r.getAttribute('data-id'); });
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestUngroupedAgentSessionStaysInTheRail(unittest.TestCase):
    """providers/claude.py's _is_bg_agent() (:370) marks a session `agent: true`
    for sessionKind == "bg" OR source == "sdk-cli", but _agent_group() (:382)
    only buckets sdk-cli ones — a plain `claude --bg` agent is
    `agent: true, group: ""`. The rail's `!s.agent` filter and its agent-bucket
    pass's `s.agent && s.group` are not complements, so such a session matched
    NEITHER and disappeared from the rail, the collapsed orbs and the Sessions
    count. boardTiles() had already fixed exactly this ("950 sessions, 1
    working, 0 tiles"); the rail was the only view still losing it."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("normal1", NOW - 5, title="Normal One"),
            make_session("bgagent1", NOW - 5, title="Bg Agent", agent=True, group=""),
            make_session("grpagent1", NOW - 5, title="Grp Agent", agent=True,
                         group="repoX", groupLabel="repoX"),
        ]
        cls.OUT = _run(_D1_TAIL % {"sessions": json.dumps(sessions)})

    def test_expanded_rail_renders_the_ungrouped_agent_as_an_ordinary_row(self):
        self.assertIn("bgagent1", self.OUT["railRowIds"])
        self.assertIn("normal1", self.OUT["railRowIds"])

    def test_grouped_agent_is_still_represented_by_its_bucket_not_a_flat_row(self):
        """The fix must not go the other way: an agent WITH a group still
        belongs to its "Agents · repoX" bucket, never a flat row."""
        self.assertNotIn("grpagent1", self.OUT["railRowIds"])

    def test_collapsed_orbs_include_the_ungrouped_agent(self):
        labels = " | ".join(self.OUT["orbLabels"])
        self.assertIn("Bg Agent", labels)
        self.assertIn("Normal One", labels)
        self.assertNotIn("Grp Agent", labels)

    def test_sessions_destination_count_and_rows_agree_and_include_it(self):
        self.assertIn("bgagent1", self.OUT["sessionsRowIds"])
        # 2 individually-rendered sessions (normal1 + bgagent1); grpagent1 is
        # the bucket's. The pager total must MATCH what is rendered.
        self.assertEqual(self.OUT["sessionsPagerLabel"], "1–2 of 2")


# ---------------------------------------------------------------------------
# DEFECT 2 — `failing` had no rail colour and read as "done".
# ---------------------------------------------------------------------------

_D2_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);
var fail = rowById('fail1'), idle = rowById('idle1');
out.failRowClasses = Array.from(fail._classes);
out.failDotClasses = Array.from(queryAllReal(fail, '.cr-rail-dot')[0]._classes);
out.failAria = fail.getAttribute('aria-label');
out.failStatusText = textsOf('.cr-rail-status').join('');
out.failStatusClasses = classesOf('.cr-rail-status')[0] || [];
out.failStatusTitle = queryAllReal(root, '.cr-rail-status')[0].getAttribute('title');
out.idleDotClasses = Array.from(queryAllReal(idle, '.cr-rail-dot')[0]._classes);

railEl.classList.add('cr-rail--collapsed');
poll(sessions);
out.pipClasses = classesOf('.cr-orb-pip');
railEl.classList.remove('cr-rail--collapsed');

out.boardTileClasses = classesOf('.cr-tile');
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestFailingStateIsVisibleInTheRail(unittest.TestCase):
    """STATE_DOT_CLASS had no `failing` key, so stateDotClass('failing')
    returned '' and .cr-rail-dot fell back to --state-idle grey — a failing
    session's dot was byte-identical to an idle one's. Separately the row's
    statusKind was computed from the raw fields (`s.ended && live &&
    !isWorking`), so the SAME session the board painted red with
    "fail: pytest -q" got a green ✓ "done" badge in the rail."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("fail1", NOW - 5, title="Failing One", ended=True, fail_cmd="pytest -q"),
            make_session("idle1", NOW - 99999, title="Idle One", ended=True),
        ]
        cls.OUT = _run(_D2_TAIL % {"sessions": json.dumps(sessions)})

    def test_failing_row_has_its_own_dot_class_not_the_idle_default(self):
        self.assertIn("is-failing", self.OUT["failDotClasses"])
        self.assertNotEqual(self.OUT["failDotClasses"], self.OUT["idleDotClasses"])

    def test_idle_dot_is_still_the_bare_default(self):
        self.assertEqual(self.OUT["idleDotClasses"], ["cr-rail-dot"])

    def test_failing_row_never_reads_as_done(self):
        self.assertNotIn("cr-rail-row--done", self.OUT["failRowClasses"])
        self.assertIn("cr-rail-row--failing", self.OUT["failRowClasses"])
        self.assertNotIn("done", self.OUT["failStatusText"])
        self.assertIn("fail", self.OUT["failStatusText"])
        self.assertIn("cr-rail-status--failing", self.OUT["failStatusClasses"])

    def test_rail_status_tooltip_says_the_same_thing_the_board_tile_says(self):
        self.assertEqual(self.OUT["failStatusTitle"], "fail: pytest -q")

    def test_row_aria_label_agrees_with_the_board(self):
        self.assertIn("failing", self.OUT["failAria"])
        self.assertIn("cr-tile--failing", sum(self.OUT["boardTileClasses"], []))

    def test_collapsed_orb_pip_is_no_longer_idle_grey(self):
        self.assertIn("is-failing", sum(self.OUT["pipClasses"], []))

    def test_css_paints_the_failing_dot_pip_and_row_with_the_existing_token(self):
        css = _css()
        self.assertIn(".tracker-next .cr-rail-dot.is-failing { background: var(--state-failed); }", css)
        self.assertIn(".tracker-next .cr-orb-pip.is-failing { background: var(--state-failed); }", css)
        self.assertIn(".tracker-next .cr-rail-status--failing { color: var(--state-failed); }", css)
        m = re.search(r'\.tracker-next \.cr-rail-row--failing\s*\{([^}]*)\}', css)
        self.assertIsNotNone(m, ".cr-rail-row--failing rule not found")
        self.assertIn("var(--line-failed)", m.group(1))


# ---------------------------------------------------------------------------
# DEFECT 3 — shared `query` case semantics.
# ---------------------------------------------------------------------------

_D3_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);

// Exactly what classic does: app.js:1204 writes the TRIMMED, case-PRESERVED
// value of its own search box into the shared uiState field.
uiState.set('query', 'Normal');
poll(sessions);
out.upperIds = railRowIds();
out.upperStored = uiState.get('query', '');
out.upperInputValue = queryAllReal(root, '.cr-rail-search')[0]._children
  .filter(function (c) { return c.tagName === 'INPUT'; })[0].value;

uiState.set('query', 'normal');
poll(sessions);
out.lowerIds = railRowIds();

uiState.set('query', 'NORMAL ONE');
poll(sessions);
out.shoutIds = railRowIds();
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSharedQueryIsCaseInsensitiveAcrossViews(unittest.TestCase):
    """railRowsFor() lowercased only the HAYSTACK and compared it with the raw
    needle from the shared uiState 'query' field — which classic (app.js:1204)
    writes case-preserved. Typing "Normal" in the classic search box therefore
    emptied the control-room rail. The rail's own input compensated by
    lowercasing on the way IN, which rewrote the user's typed text."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("s1", NOW - 5, title="Normal One"),
            make_session("s2", NOW - 6, title="other thing"),
        ]
        cls.OUT = _run(_D3_TAIL % {"sessions": json.dumps(sessions)})

    def test_capitalised_query_from_classic_still_matches(self):
        self.assertEqual(self.OUT["upperIds"], ["s1"])

    def test_lowercase_query_matches_the_same_session(self):
        self.assertEqual(self.OUT["lowerIds"], ["s1"])

    def test_all_caps_query_matches_too(self):
        self.assertEqual(self.OUT["shoutIds"], ["s1"])

    def test_the_query_is_stored_verbatim_not_lowercased(self):
        """The other view must show the user what they typed."""
        self.assertEqual(self.OUT["upperStored"], "Normal")

    def test_rail_input_mirrors_the_verbatim_text(self):
        self.assertEqual(self.OUT["upperInputValue"], "Normal")


# ---------------------------------------------------------------------------
# DEFECT 4 — paneScroll()'s falsy-zero scroll lock.
# ---------------------------------------------------------------------------

_D4_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
railList.clientHeight = 400;          // a laid-out, visible scroll container
poll(sessions);

railList.scrollTop = 500;             // the user scrolls down
poll(sessions);
out.afterScrollDown = railList.scrollTop;
out.storedAfterScrollDown = (uiState.get('scroll', {}) || {}).rail;

// The pane is hidden (the Sessions destination hides the rail): a display:none
// element reports clientHeight 0 and scrollTop 0 for reasons that have nothing
// to do with where the user left it -- the stored value must SURVIVE that.
railList.clientHeight = 0;
railList.scrollTop = 0;
poll(sessions);
out.storedWhileHidden = (uiState.get('scroll', {}) || {}).rail;

railList.clientHeight = 400;          // shown again -> restored from the store
poll(sessions);
out.afterReshow = railList.scrollTop;

railList.scrollTop = 0;               // the user scrolls back to the very top
poll(sessions);
out.afterScrollToTop = railList.scrollTop;
out.storedAfterScrollToTop = (uiState.get('scroll', {}) || {}).rail;
poll(sessions);
out.afterAnotherPoll = railList.scrollTop;
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestPaneScrollCanPersistZero(unittest.TestCase):
    """`if (liveEl && liveEl.scrollTop) return liveEl.scrollTop;` — a genuine
    scrollTop of 0 is falsy, so it fell through to the stored value and 0 could
    never be written back: scroll to 500, then back to the top, and every 2s
    poll yanked the pane down to 500 again, forever. One helper, three panes
    ('rail'/'sessions'/'board')."""

    @classmethod
    def setUpClass(cls):
        sessions = [make_session("sc%d" % i, NOW - 5 - i) for i in range(6)]
        cls.OUT = _run(_D4_TAIL % {"sessions": json.dumps(sessions)})

    def test_a_real_scroll_offset_is_still_preserved(self):
        self.assertEqual(self.OUT["afterScrollDown"], 500)
        self.assertEqual(self.OUT["storedAfterScrollDown"], 500)

    def test_scrolling_back_to_the_top_is_not_undone_by_the_next_poll(self):
        self.assertEqual(self.OUT["afterScrollToTop"], 0)
        self.assertEqual(self.OUT["afterAnotherPoll"], 0)

    def test_zero_is_actually_persisted(self):
        self.assertEqual(self.OUT["storedAfterScrollToTop"], 0)

    def test_a_hidden_pane_does_not_clobber_the_stored_offset(self):
        """The regression the old truthiness check was accidentally covering:
        a display:none pane reports 0, and that 0 must not overwrite the store
        or the offset would be lost on every view switch."""
        self.assertEqual(self.OUT["storedWhileHidden"], 500)
        self.assertEqual(self.OUT["afterReshow"], 500)


# ---------------------------------------------------------------------------
# DEFECT 5 — the agent-group row double-escaped its label.
# ---------------------------------------------------------------------------

_D5_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);
out.agentRowText = textsOf('.cr-rail-agentrow').join('');
out.agentRowTitle = attrs('.cr-rail-agentrow', 'title')[0] || '';
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAgentGroupLabelIsNotDoubleEscaped(unittest.TestCase):
    """`'Agents · ' + esc(b.label)` is handed to h() as a STRING child, and h()
    puts string children through document.createTextNode() — which needs no
    HTML escaping. _agent_group() returns os.path.basename(repo), so a real
    directory named `R&D` rendered as `R&amp;D`, while the title/aria-label on
    the SAME element used the raw label."""

    @classmethod
    def setUpClass(cls):
        sessions = [make_session("a1", NOW - 5, agent=True, group="g1", groupLabel="a&b<x>")]
        cls.OUT = _run(_D5_TAIL % {"sessions": json.dumps(sessions)})

    def test_visible_label_shows_the_real_characters(self):
        self.assertIn("Agents · a&b<x>", self.OUT["agentRowText"])

    def test_no_html_entity_leaks_into_the_visible_text(self):
        self.assertNotIn("&amp;", self.OUT["agentRowText"])
        self.assertNotIn("&lt;", self.OUT["agentRowText"])

    def test_tooltip_and_visible_text_agree(self):
        self.assertIn(self.OUT["agentRowTitle"], self.OUT["agentRowText"])


# ---------------------------------------------------------------------------
# DEFECT 6 — the collapsed rail filters invisibly.
# ---------------------------------------------------------------------------

_D6_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
railEl.classList.add('cr-rail--collapsed');
poll(sessions);
out.noFilterChipOn = classesOf('.cr-rail-filterchip').map(function (c) {
  return c.indexOf('cr-rail-filterchip--on') >= 0;
});
out.orbsUnfiltered = attrs('.cr-orb', 'aria-label').length;

uiState.set('liveOnly', true);
poll(sessions);
out.orbsLiveOnly = attrs('.cr-orb', 'aria-label').length;
out.chipOnLiveOnly = classesOf('.cr-rail-filterchip')[0] || [];
out.chipLabelLiveOnly = attrs('.cr-rail-filterchip', 'aria-label')[0] || '';

uiState.set('query', 'Alpha');
poll(sessions);
out.chipLabelBoth = attrs('.cr-rail-filterchip', 'aria-label')[0] || '';
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCollapsedRailSurfacesItsActiveFilters(unittest.TestCase):
    """ext_cr_board.css hides `.cr-rail-search`, `.cr-rail-count` (the ONLY
    control bound to toggleRailLiveOnly), `.cr-rail-groupby` and
    `.cr-rail-group-header` under `.cr-rail--collapsed`, but renderRail() keeps
    applying both filters to the orb list — so collapsing the rail with
    live-only on showed 1 orb out of 957 with no visible cause and no way to
    clear it. The chosen fix (lower blast radius than silently widening the
    collapsed rail to every session, which would also contradict the "+N"
    footer beside it) is one always-visible, click-to-clear indicator that
    exists ONLY while a filter is actually on."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("al", NOW - 5, title="Alpha"),
            make_session("be", NOW - 6, title="Beta"),
            make_session("ga", NOW - 99999, title="StaleGamma", ended=True),
        ]
        cls.OUT = _run(_D6_TAIL % {"sessions": json.dumps(sessions)})

    def test_no_indicator_when_nothing_is_filtered(self):
        self.assertTrue(all(v is False for v in self.OUT["noFilterChipOn"]),
                        self.OUT["noFilterChipOn"])
        self.assertEqual(self.OUT["orbsUnfiltered"], 3)

    def test_live_only_still_filters_but_now_says_so(self):
        self.assertEqual(self.OUT["orbsLiveOnly"], 2)
        self.assertIn("cr-rail-filterchip--on", self.OUT["chipOnLiveOnly"])
        self.assertIn("live only", self.OUT["chipLabelLiveOnly"])
        self.assertIn("click to clear", self.OUT["chipLabelLiveOnly"])

    def test_indicator_names_every_active_filter(self):
        self.assertIn("live only", self.OUT["chipLabelBoth"])
        self.assertIn("search", self.OUT["chipLabelBoth"])
        self.assertIn("Alpha", self.OUT["chipLabelBoth"])

    def test_css_actually_shows_the_indicator_in_the_collapsed_rail(self):
        css = _css()
        self.assertIn(".tracker-next .cr-rail-filterchip { display: none; }", css)
        m = re.search(
            r'\.tracker-next \.cr-rail--collapsed \.cr-rail-filterchip--on\s*\{([^}]*)\}', css)
        self.assertIsNotNone(m, "collapsed filter-chip rule not found")
        self.assertIn("display: flex", m.group(1))
        self.assertIn("cursor: pointer", m.group(1))


# ---------------------------------------------------------------------------
# DEFECT 7 — "N more" counted filtered-out sessions.
# ---------------------------------------------------------------------------

_D7_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);
out.footerNoQuery = railFooter.textContent;
out.rowsNoQuery = railRowIds().length;

uiState.set('query', 'zzzzz');
poll(sessions);
out.footerNoMatch = railFooter.textContent;
out.rowsNoMatch = railRowIds().length;

uiState.set('query', '');
railEl.classList.add('cr-rail--collapsed');
poll(sessions);
uiState.set('query', 'zzzzz');
poll(sessions);
out.collapsedFooterNoMatch = railFooter.textContent;
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailFooterCountsOnlyWhatIsActuallyHidden(unittest.TestCase):
    """`var more = baseSessions.length - shown;` where `shown` was the POST-search
    count: a search matching nothing rendered zero rows under
    "scroll · 954 more", pointing at content that does not exist."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("f1", NOW - 5, title="One"),
            make_session("f2", NOW - 6, title="Two"),
        ]
        cls.OUT = _run(_D7_TAIL % {"sessions": json.dumps(sessions)})

    def test_nothing_hidden_when_everything_is_rendered(self):
        self.assertEqual(self.OUT["rowsNoQuery"], 2)
        self.assertEqual(self.OUT["footerNoQuery"], "scroll · 0 more")

    def test_a_search_that_matches_nothing_reports_nothing_more_to_scroll_to(self):
        self.assertEqual(self.OUT["rowsNoMatch"], 0)
        self.assertEqual(self.OUT["footerNoMatch"], "scroll · 0 more")

    def test_the_collapsed_footer_counts_the_same_way(self):
        self.assertEqual(self.OUT["collapsedFooterNoMatch"], "+0")


# ---------------------------------------------------------------------------
# DEFECT 8 — a focused rail row lost focus on every 2s poll.
# ---------------------------------------------------------------------------

_D8_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
poll(sessions);
out.rowsAreFocusable = attrs('.cr-rail-row', 'tabindex');

// The user tabs onto the middle row.
document.activeElement = rowById('k2');
out.focusedBefore = document.activeElement.getAttribute('data-id');

FOCUSED = null;
poll(sessions);                       // one 2s poll -> full rebuild
out.focusedAfterPoll = FOCUSED ? FOCUSED.getAttribute('data-id') : null;
out.rowStillInTree = !!rowById('k2');

FOCUSED = null;
poll(sessions);                       // and it must survive the NEXT poll too
out.focusedAfterSecondPoll = FOCUSED ? FOCUSED.getAttribute('data-id') : null;
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestFocusedRailRowSurvivesThePollRebuild(unittest.TestCase):
    """renderRail() does `els.railList.innerHTML = ''` and re-appends every row
    on each 2s poll, restoring focus only for the SEARCH INPUT. Rail rows carry
    tabindex="0", so keyboard focus on a row was handed back to document.body
    twice a minute — the rail could not be driven from the keyboard at all. The
    board already solves this with `focusedTileId` (renderBoard); the same
    pattern is used here rather than a second one."""

    @classmethod
    def setUpClass(cls):
        sessions = [make_session("k%d" % i, NOW - 5 - i, title="Row %d" % i) for i in range(1, 4)]
        cls.OUT = _run(_D8_TAIL % {"sessions": json.dumps(sessions)})

    def test_rail_rows_really_are_keyboard_focusable(self):
        self.assertTrue(self.OUT["rowsAreFocusable"])
        self.assertTrue(all(t == "0" for t in self.OUT["rowsAreFocusable"]))

    def test_focus_returns_to_the_same_session_row_after_a_poll(self):
        self.assertTrue(self.OUT["rowStillInTree"])
        self.assertEqual(self.OUT["focusedAfterPoll"], "k2")

    def test_focus_keeps_surviving_subsequent_polls(self):
        self.assertEqual(self.OUT["focusedAfterSecondPoll"], "k2")


# ---------------------------------------------------------------------------
# DEFECT 9 — the rail search had no empty state.
# ---------------------------------------------------------------------------

_D9_TAIL = r"""
var sessions = %(sessions)s;
var out = {};
uiState.set('query', 'zzzzz');
poll(sessions);
out.emptyText = textsOf('.cr-rail-empty').join('');
out.emptyCount = queryAllReal(railList, '.cr-rail-empty').length;
out.headers = textsOf('.cr-rail-group-header');

uiState.set('query', '');
poll(sessions);
out.emptyCountAfterClear = queryAllReal(railList, '.cr-rail-empty').length;
out.headersAfterClear = textsOf('.cr-rail-group-header');
emit(out);
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailSearchHasAnEmptyState(unittest.TestCase):
    """A rail search matching nothing rendered "Sessions — 0 · newest first"
    and nothing else. The Sessions destination already answers this exact
    question ("No sessions match “…”."), so its copy and markup idiom are
    reused rather than a second one invented."""

    @classmethod
    def setUpClass(cls):
        sessions = [
            make_session("e1", NOW - 5, title="One"),
            make_session("e2", NOW - 6, title="Two"),
        ]
        cls.OUT = _run(_D9_TAIL % {"sessions": json.dumps(sessions)})

    def test_an_empty_search_result_explains_itself(self):
        self.assertEqual(self.OUT["emptyCount"], 1)
        self.assertIn("No sessions match", self.OUT["emptyText"])
        self.assertIn("zzzzz", self.OUT["emptyText"])

    def test_the_bare_zero_header_is_replaced_not_supplemented(self):
        self.assertEqual(
            [h for h in self.OUT["headers"] if "Sessions — 0" in h], [],
            "the empty state must replace the bare 'Sessions — 0' header, not sit under it")

    def test_clearing_the_search_restores_the_normal_list(self):
        self.assertEqual(self.OUT["emptyCountAfterClear"], 0)
        self.assertTrue(any("Sessions — 2" in h for h in self.OUT["headersAfterClear"]),
                        self.OUT["headersAfterClear"])


if __name__ == "__main__":
    unittest.main()
