"""Regression tests for the control-room SEARCH PARITY seam (ext_cr_board.js).

THE DEFECT (confirmed by an adversarial parity audit): three different search
implementations shared one label ("search") and one shared uiState key
('query'), but disagreed about what "matches" means:

  - classic (app.js doSearch()) hits GET /api/search -> registry.search_all()
    -> providers/claude.py search_sessions(), which scans the FULL raw
    transcript (prompts, replies, tool inputs) across up to 500 sessions.
  - the control-room RAIL (railRowsFor()) used to be a client-side substring
    filter over only title+project+prompt of the loaded, 200-cap `sessions`
    array -- it never called /api/search at all, so a phrase that only
    appears deep in a transcript matched classic's sidebar but NOT the rail,
    even though both read/wrote the identical uiState 'query' key.
  - the Sessions destination had a THIRD, fully separate query variable that
    DID call /api/search (with a debounce + stale-response seq guard) but was
    never wired to uiState at all, so typing there updated neither classic's
    box nor the rail.

THE FIX: one seam. The Sessions destination's debounced /api/search call
(scheduleSessionsSearch()/commitSessionsSearch()) is now driven by every
write to the shared uiState 'query' field (from ANY of the three boxes), and
railRowsFor() defers to that call's resolved hit-id set the instant it has
answered for the query currently in the box -- never a second matcher. A
local substring pass survives only as INSTANT FEEDBACK before the server has
answered; it is provably powerless to make the rail disagree with a settled
server answer, which is what these tests pin.

Idiom: reuses tests/test_cr_rail_polish.py's real-DOM node harness (mount()
+ update() against the actual page.build_page() bundle) -- imported, not
copied. window.fetch and window.setTimeout are overridden AFTER mount() (so
buildShell()'s own timers are unaffected) to make the debounced /api/search
round-trip deterministic: setTimeout fires its callback synchronously (the
debounce still exists in the source -- see TestScheduleStillDebounces below
-- it's only the TEST clock that's collapsed), and fetch resolves against a
small canned {query -> hits} table standing in for registry.search_all().
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
    _HAS_NODE, _REAL_DOM_PREAMBLE, _REAL_DOM_MID, _run_node, _read_page,
    _extract_script_content, make_session, NOW,
)


def _extract_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


_SEARCH_TAIL = r"""
function idsOf(rows) { return rows.map(function (r) { return r.getAttribute('data-id'); }).sort(); }

(async function () {
try {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: SESSIONS, now: NOW });

  // The Sessions destination (els.viewSessions) is a SEPARATE, merely-`hidden`
  // subtree of the same persistent shell (STRUCTURAL FIX era: board/sessions/
  // detail are siblings, never removed from the DOM) and renders its OWN
  // `.cr-rail-row` elements once a search settles -- scope every query to the
  // rail's own `.cr-rail` subtree specifically, or a settled search would be
  // double-counted (one copy from the rail, one from the hidden Sessions list).
  var railEl = queryAllReal(root, '.cr-rail')[0];

  var fetchLog = [];
  window.fetch = function (url) {
    fetchLog.push(url);
    var m = /\/api\/search\?q=([^&]*)/.exec(url);
    var q = m ? decodeURIComponent(m[1]).toLowerCase() : '';
    var hits = HITS_BY_QUERY[q] || [];
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve(hits); } });
  };
  // Collapse the debounce clock only -- the debounce ITSELF (clearTimeout + a
  // fresh setTimeout per call) still runs; see TestScheduleStillDebounces,
  // which asserts on the SOURCE for that, not on this stubbed timer.
  window.setTimeout = function (fn) { fn(); return 0; };

  uiState.set('query', QUERY1);
  var instantIds = idsOf(queryAllReal(railEl, '.cr-rail-row'));
  var instantText = allTextIn(railEl);

  // Flush the fetch(...).then(r.json()).then(hits=>...) microtask chain: a
  // REAL macrotask (captured before the preamble's own setTimeout stub
  // overwrote the global) runs only after Node drains every pending
  // microtask, so two ticks is ample headroom for a 2-hop .then() chain.
  await new Promise(function (resolve) { _origSetTimeout(resolve, 0); });
  await new Promise(function (resolve) { _origSetTimeout(resolve, 0); });
  var settledIds = idsOf(queryAllReal(railEl, '.cr-rail-row'));
  var settledText = allTextIn(railEl);

  uiState.set('query', QUERY2);
  await new Promise(function (resolve) { _origSetTimeout(resolve, 0); });
  await new Promise(function (resolve) { _origSetTimeout(resolve, 0); });
  var emptyIds = idsOf(queryAllReal(railEl, '.cr-rail-row'));
  var emptyText = allTextIn(railEl);

  console.log("===CR_SEARCH_JSON_START===");
  console.log(JSON.stringify({
    instantIds: instantIds, instantText: instantText,
    settledIds: settledIds, settledText: settledText,
    emptyIds: emptyIds, emptyText: emptyText,
    fetchLog: fetchLog
  }));
} catch (e) {
  console.error("SEARCH-DRIVER-THREW: " + (e && e.stack || e));
  process.exit(1);
}
})();
"""


def _search_driver_js(sessions, hits_by_query, query1, query2):
    bundle_js = _extract_script_content(_read_page())
    tail = (
        "var NOW = " + str(NOW) + ";\n"
        + "var SESSIONS = " + json.dumps(sessions) + ";\n"
        + "var HITS_BY_QUERY = " + json.dumps(hits_by_query) + ";\n"
        + "var QUERY1 = " + json.dumps(query1) + ";\n"
        + "var QUERY2 = " + json.dumps(query2) + ";\n"
        + _SEARCH_TAIL
    )
    # `_origSetTimeout` must be captured from Node's REAL global setTimeout
    # BEFORE `_REAL_DOM_PREAMBLE` overwrites it with the no-op test stub.
    return "\n".join(["var _origSetTimeout = setTimeout;", _REAL_DOM_PREAMBLE, bundle_js, _REAL_DOM_MID, tail])


# `deep` only matches in the (simulated) full transcript the server scans --
# neither its title, project nor first-prompt summary contain the phrase, so
# the OLD client-side substring filter could never have found it. `titlehit`
# matches both the server AND a naive local substring pass (its title
# contains the phrase). `nomatch` matches neither.
def _three_sessions():
    return [
        make_session("deep", NOW - 10, title="unrelated title", project="proj", prompt="unrelated prompt"),
        make_session("titlehit", NOW - 20, title="a SecretPhrase sighting", project="proj", prompt="p"),
        make_session("nomatch", NOW - 30, title="nothing here", project="proj", prompt="p"),
    ]


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailDefersToServerSearchResult(unittest.TestCase):
    """(a) + (d): once the server has answered for the query in the box, the
    rail's session set is EXACTLY the server's hit-id set -- a deep transcript
    hit the old substring filter could never have found now shows up, and a
    query the server confirms matches nothing renders the empty state rather
    than a silently short (or stale) list."""

    @classmethod
    def setUpClass(cls):
        sessions = _three_sessions()
        hits_by_query = {
            "secretphrase": [{"id": "deep", "title": "x", "project": "proj", "mtime": NOW}, {"id": "titlehit", "title": "y", "project": "proj", "mtime": NOW}],
            "zzz-nothing-zzz": [],
        }
        js = _search_driver_js(sessions, hits_by_query, "SecretPhrase", "zzz-nothing-zzz")
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError("search driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (returncode, stdout, stderr))
        cls.OUT = _extract_json(stdout, "===CR_SEARCH_JSON_START===")

    def test_settled_rail_matches_server_hit_ids_exactly(self):
        """THE FIX: 'deep' (transcript-only, server-side match) is now present,
        and it agrees byte-for-byte with what the server actually returned --
        never a superset/subset invented locally."""
        self.assertEqual(self.OUT["settledIds"], ["deep", "titlehit"])

    def test_nomatch_session_never_appears_once_server_has_answered(self):
        self.assertNotIn("nomatch", self.OUT["settledIds"])

    def test_a_query_the_server_confirms_empty_renders_empty_state_not_a_short_list(self):
        self.assertEqual(self.OUT["emptyIds"], [])
        self.assertIn("No sessions match", self.OUT["emptyText"])

    def test_real_search_endpoint_was_actually_called_not_a_fourth_matcher(self):
        """Requirement 1: reuse the server round-trip -- assert the rail's
        settled state was actually produced by hitting /api/search, not by a
        client-side heuristic that happens to agree by coincidence."""
        self.assertTrue(any("/api/search?q=" in u for u in self.OUT["fetchLog"]))


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestInstantFeedbackNeverContradictsSettledServerAnswer(unittest.TestCase):
    """(c) mixed-case regression guard, and requirement 3's "local filter may
    only ever show EXTRA candidates before the server answers, never fewer
    than -- and never fewer once settled: it must be strictly REPLACED by --
    the real answer." Uses a query in mixed case (DEFECT 3's regression
    surface: classic stores the query verbatim, not lowercased)."""

    @classmethod
    def setUpClass(cls):
        sessions = _three_sessions()
        hits_by_query = {
            # server keys are matched case-insensitively here (mirroring the
            # real server's `q.lower()`), same as production commitSessionsSearch()
            # sends the box's raw (verbatim, un-lowercased) text over the wire.
            "secretphrase": [{"id": "deep", "title": "x", "project": "proj", "mtime": NOW}, {"id": "titlehit", "title": "y", "project": "proj", "mtime": NOW}],
            "nomatch-anywhere": [],
        }
        js = _search_driver_js(sessions, hits_by_query, "SecretPhrase", "nomatch-anywhere")
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError("search driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (returncode, stdout, stderr))
        cls.OUT = _extract_json(stdout, "===CR_SEARCH_JSON_START===")

    def test_instant_feedback_is_case_insensitive_local_substring(self):
        """Before the server has answered, 'titlehit' (title contains the
        phrase) is visible from the LOCAL pass alone, case-insensitively --
        the exact DEFECT 3 surface (needle case must not break the match)."""
        self.assertIn("titlehit", self.OUT["instantIds"])

    def test_instant_feedback_never_shows_fewer_than_the_eventual_server_answer(self):
        """The transient local pass may show fewer candidates than the server
        will eventually confirm (it cannot see 'deep' yet) -- but it may never
        show something the settled answer then RETRACTS. Every id shown
        instantly must still be present once settled."""
        for sid in self.OUT["instantIds"]:
            self.assertIn(sid, self.OUT["settledIds"],
                           "instant feedback showed %r, which the settled server answer then dropped" % sid)

    def test_settled_answer_is_the_final_word_deep_included(self):
        self.assertEqual(self.OUT["settledIds"], ["deep", "titlehit"])

    def test_a_second_query_that_settles_empty_clears_everything(self):
        self.assertEqual(self.OUT["emptyIds"], [])
        self.assertIn("No sessions match", self.OUT["emptyText"])


# ---------------------------------------------------------------------------
# (b) The Sessions destination writes 'query' into uiState -- source check.
# The real-DOM harness's addEventListener is a no-op stub (test_cr_rail_polish.py's
# own makeReal(): "el.addEventListener = function () {};"), so a simulated
# `input` event can never reach an oninput handler in this harness -- there is
# no way to drive this behaviourally without a real browser. The FUNCTIONAL
# half of requirement 2 ("vice versa": the rail/classic must react to a query
# that arrived through uiState regardless of which box wrote it) is exactly
# what TestRailDefersToServerSearchResult above already exercises end-to-end
# (uiState.set('query', ...) standing in for whichever box the user actually
# typed into -- the rail's own render code has no way to tell which box a
# uiState write came from, by construction). This is the narrow remaining
# claim: the Sessions destination's OWN input is wired to make that write,
# not to a private call that bypasses uiState the way the pre-fix code did.
# ---------------------------------------------------------------------------

class TestSessionsDestinationWritesThroughSharedQuery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def _sessions_search_input_block(self):
        m = re.search(r"els\.sessionsSearchInput\s*=\s*h\('input',\s*\{", self.bundle)
        self.assertIsNotNone(m, "sessionsSearchInput construction not found in the real bundle")
        # Slice out just this h(...) call's attrs object by brace balance.
        brace_start = self.bundle.index('{', m.start())
        depth, end = 0, None
        for i in range(brace_start, len(self.bundle)):
            c = self.bundle[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        self.assertIsNotNone(end, "unterminated sessionsSearchInput attrs object (brace mismatch)")
        return self.bundle[brace_start:end]

    def test_sessions_input_oninput_writes_through_uistate_query(self):
        block = self._sessions_search_input_block()
        self.assertIn("uiState.set('query'", block)

    def test_sessions_input_no_longer_bypasses_uistate_with_a_direct_call(self):
        """THE DEFECT: this used to be `scheduleSessionsSearch(e.target.value)`
        directly, wired to nothing classic or the rail could see."""
        block = self._sessions_search_input_block()
        self.assertNotIn("scheduleSessionsSearch(e.target.value)", block)

    def test_query_subscriber_is_the_one_place_that_now_calls_schedulesessionssearch(self):
        """The write side (the box) only ever reaches uiState; the READ side
        (issuing the actual debounced request) lives in exactly one place --
        the shared 'query' subscriber -- so a write from ANY of the three
        boxes drives the SAME single call, never a fourth path."""
        m = re.search(r"key === 'query'\)\s*\{(.*?)\}\s*else if \(key === 'liveOnly'\)", self.bundle, re.DOTALL)
        self.assertIsNotNone(m, "uiState 'query' subscriber branch not found")
        self.assertIn("scheduleSessionsSearch(", m.group(1))


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestScheduleStillDebounces(unittest.TestCase):
    """Requirement 1's "keep the debounce it already has": scheduleSessionsSearch()
    must still clearTimeout() any pending call and issue exactly ONE fresh
    setTimeout() per invocation -- i.e. three rapid uiState writes for the same
    box must still resolve to a SINGLE eventual /api/search call, not three."""

    @classmethod
    def setUpClass(cls):
        sessions = _three_sessions()
        js = r"""
var _origSetTimeout = setTimeout;
""" + _REAL_DOM_PREAMBLE + _extract_script_content(_read_page()) + _REAL_DOM_MID + r"""
(async function () {
  var root = makeReal('div');
  docBody.appendChild(root);
  window.CR.board.mount(root, {});
  window.CR.board.update({ sessions: """ + json.dumps(sessions) + r""", now: """ + str(NOW) + r""" });

  var fetchLog = [];
  var pendingTimers = [];
  window.fetch = function (url) {
    fetchLog.push(url);
    return Promise.resolve({ ok: true, json: function () { return Promise.resolve([]); } });
  };
  // A REAL (uncollapsed) debounce clock this time: capture scheduled callbacks
  // instead of firing them, so this test can prove there is only ever ONE
  // still-pending timer after several rapid writes for the same box.
  window.setTimeout = function (fn, ms) { pendingTimers.push(fn); return pendingTimers.length; };
  window.clearTimeout = function () { pendingTimers.length = 0; };

  uiState.set('query', 'a');
  uiState.set('query', 'ab');
  uiState.set('query', 'abc');

  console.log("===CR_DEBOUNCE_JSON_START===");
  console.log(JSON.stringify({ timersLeftPending: pendingTimers.length, fetchLogBeforeFiring: fetchLog.length }));
})();
"""
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError("debounce driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (returncode, stdout, stderr))
        cls.OUT = _extract_json(stdout, "===CR_DEBOUNCE_JSON_START===")

    def test_no_request_fires_before_the_debounce_timer_does(self):
        self.assertEqual(self.OUT["fetchLogBeforeFiring"], 0)

    def test_three_rapid_writes_leave_exactly_one_pending_timer(self):
        """THE ACTUAL DEBOUNCE: clearTimeout() on every call means the first two
        scheduled callbacks are cancelled outright, not merely superseded --
        `clearTimeout` here empties the whole pending list, so if scheduleSessionsSearch()
        ever stopped calling it, this would fail with 3, not 1."""
        self.assertEqual(self.OUT["timersLeftPending"], 1)


if __name__ == "__main__":
    unittest.main()
