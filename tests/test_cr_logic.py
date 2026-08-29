"""Pins the client-side DERIVED VALUES the Control Room UI computes in JavaScript.

Every one of these encodes actual product design (board ranking + the 8-tile cap,
session-state derivation, the progress spine's time-proportional widths, the merged
timeline, triage counts) and, unlike the server-side derived values (todo counts, PR
fields, todo timings, config precedence — all covered in tests/test_selfcheck.py),
had NO assertion anywhere before this file.

Idiom copied from tests/test_page_bundle.py: build the REAL assembled page
(aitracker.page.build_page()), extract the inlined <script> bundle, execute it under
a minimal stub DOM in Node, then reach into window.CR for the exported pure
derivations. Skips cleanly (not a failure) when node is unavailable — same as
test_page_bundle.py.

Exported surface exercised here (verified by reading the source, not guessed):
  window.CR.board  (aitracker/web/ext_cr_board.js, createBoard()'s return object):
    boardTiles, sessionState, railOrder, agentGroups, triageCounts, activityHistogram
  window.CR.detail._internal  (aitracker/web/ext_cr_detail.js, end of file):
    spineSegments, mergeTimeline, deriveLinks, stateOf, firstEventTime,
    extractDiagram, groupAgentReruns

Only boardTiles/sessionState/railOrder/agentGroups/triageCounts (board) and
spineSegments/mergeTimeline (detail) are pinned below, per the assignment. See the
bottom of this file for what was deliberately left unpinned and why.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_AITRACKER = os.path.join(_ROOT, "aitracker")
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)
from aitracker import config  # noqa: E402  (LIVE_WINDOW pinned against this, never a second literal)

LIVE_WINDOW = config.LIVE_WINDOW  # 300s as of writing; read live so a config change is caught, not silently outdated


# ---------------------------------------------------------------------------
# Idiom copied from test_page_bundle.py: read the real page, pull out the bundle,
# run it in node under a stub DOM.
# ---------------------------------------------------------------------------

def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    matches = list(script_pattern.finditer(html))
    if not matches:
        raise ValueError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


_JS_PREAMBLE = r"""
// Minimal browser environment for bundle execution (same stub as test_page_bundle.py).
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus() {}, click() {}
  };
  return self;
}

var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};

const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});

try {
"""

_JS_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


# ---------------------------------------------------------------------------
# Fixture builders — real list-dict / detail-dict shapes, read from the source
# (aitracker/providers/claude.py:list_sessions / :parse_session, aitracker/registry.py),
# not guessed.
# ---------------------------------------------------------------------------

def make_session(id, mtime, **overrides):
    s = {
        "id": id, "project": "proj", "cwd": "/tmp/proj", "title": "t", "prompt": "p",
        "source": "claude",
        "agent": False, "group": "", "groupLabel": "", "parentId": "",
        "bg": 0, "waiting": False, "ended": False, "mtime": mtime,
        "todo_total": 0, "todo_done": 0, "todo_current": None, "todo_current_index": None,
        "pr_num": None, "pr_url": None, "pr_repo": None, "pr_state": "",
        "now_line": "",
        # registry.all_sessions() additions
        "pinned": False, "note_count": 0, "open_flags": 0,
        "continued_as": "", "continued_from": "",
    }
    s.update(overrides)
    return s


def make_detail(**overrides):
    d = {
        "meta": {"cwd": "/tmp/proj", "gitBranch": "main", "version": "1.0", "sessionId": "sid",
                  "entrypoint": "cli", "aiTitle": "", "customTitle": "", "model": "", "effort": "", "title": "t"},
        "todos": [], "files": [], "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": [], "agents": [], "agents_bg": [], "shells": [],
        "decisions": [], "waiting": False, "prs": [], "narrative": [],
        "tokens": {"in": 0, "out": 0}, "context": {"current": 0, "limit": 0, "pct": 0},
        "counts": {"done": 0, "todos": 0, "created": 0, "edited": 0, "read": 0, "commits": 0,
                   "tests": 0, "tests_failed": 0, "errors": 0, "agents": 0, "searches": 0},
        "mtime": 0, "now": 0, "notes": [], "push_when": "turn",
        "overview": {"where": "", "goal": "", "now": "", "now_kind": "", "sofar": "", "commits": []},
        "continued_as": "", "continued_from": "",
    }
    d.update(overrides)
    return d


def iso_ms(ms):
    """Epoch milliseconds -> ISO string parseable by JS Date.parse, matching the
    'requests[].t' / 'narrative[].t' / etc. ISO-string shape claude.py actually emits."""
    dt = datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Board fixtures (epoch SECONDS — the list-dict's mtime unit).
# ---------------------------------------------------------------------------

NOW = 1_700_000_000  # fixed epoch seconds


def _board_driver_js():
    # 1) Rank ordering must dominate recency: mtime is DELIBERATELY reversed vs. rank
    #    (the landed session is the most recent, the awaiting one the oldest) so a
    #    recency-only sort would get this backwards.
    rank_sessions = [
        make_session("land", NOW - 10, ended=True),
        make_session("work", NOW - 20, ended=False),
        make_session("flag", NOW - 9999, open_flags=1),
        make_session("wait", NOW - 40, waiting=True),
    ]

    # 2) Pinned beats recency within the same rank ('working').
    pin_sessions = [
        make_session("new_unpinned", NOW - 10, ended=False, pinned=False),
        make_session("old_pinned", NOW - 200, ended=False, pinned=True),
    ]

    # 3) An idle session (older than LIVE_WINDOW, not waiting/flagged) never gets a tile.
    idle_sessions = [
        make_session("stale", NOW - (LIVE_WINDOW + 1), ended=False, waiting=False, open_flags=0),
        make_session("fresh", NOW - 5, ended=False),
    ]

    # 4) The cap: default 8, configurable 3..8 via localStorage cr.boardTileCount, always clamped.
    cap_sessions = [make_session("s%d" % i, NOW - i, waiting=True) for i in range(12)]

    # 5) Regression: agent:true, group:"" must still get an individual tile (the "950
    #    sessions, 0 tiles" bug — excluded from BOTH the individual and the group path).
    #    A properly-grouped agent session (group:"repoA") must NOT get an individual tile.
    agent_sessions = [
        make_session("orphan_agent", NOW - 5, agent=True, group="", groupLabel="", ended=False),
        make_session("grouped_agent", NOW - 3, agent=True, group="repoA", groupLabel="repoA", ended=False),
    ]

    # 6) sessionState: every state, plus the LIVE_WINDOW boundary (pinned against
    #    aitracker.config.LIVE_WINDOW, not a second hardcoded "300").
    state_probe = {
        "awaiting": make_session("a", NOW - 1, waiting=True),
        "flagged": make_session("b", NOW - 99999, open_flags=2),
        "working": make_session("c", NOW - 5, ended=False),
        "landed": make_session("d", NOW - 5, ended=True),
        "idle": make_session("e", NOW - 99999, ended=False),
        "boundary_live": make_session("f", NOW - (LIVE_WINDOW - 1), ended=False),
        "boundary_idle": make_session("g", NOW - LIVE_WINDOW, ended=False),
    }

    # 7) railOrder: pinned/unpinned partition, each newest-first.
    rail_sessions = [
        make_session("p_old", NOW - 500, pinned=True),
        make_session("p_new", NOW - 10, pinned=True),
        make_session("u_old", NOW - 400, pinned=False),
        make_session("u_new", NOW - 20, pinned=False),
    ]

    # 8) agentGroups: bucketed by group, idle sessions excluded from their bucket,
    #    buckets ordered newest-first by max mtime.
    group_sessions = [
        make_session("ga1", NOW - 5, agent=True, group="A", groupLabel="Repo A", ended=False),
        make_session("ga2_idle", NOW - 99999, agent=True, group="A", groupLabel="Repo A", ended=False),
        make_session("gb1", NOW - 3, agent=True, group="B", groupLabel="Repo B", ended=False),
    ]

    # 13) triageCounts: not mutually exclusive.
    triage_sessions = [
        make_session("await1", NOW - 1, waiting=True),
        make_session("both", NOW - 5, ended=False, waiting=False, open_flags=3),
    ]

    # 14) BUG 2: pr_num/pr_url/pr_repo/pr_state reached the SPA (registry.py's shared
    #     list dict, Claude-only) but had zero render call sites — prInfo() is the pure
    #     decision behind the fix. A Landed session with pr_num renders it (linked when
    #     pr_url is present); one without renders nothing.
    pr_sessions = {
        "with_pr": make_session("has_pr", NOW - 5, ended=True,
                                 pr_num=42, pr_url="https://example.com/pr/42",
                                 pr_repo="acme/widgets", pr_state="merged"),
        "without_pr": make_session("no_pr", NOW - 5, ended=True),
        "not_landed": make_session("working_with_pr", NOW - 5, ended=False,
                                    pr_num=7, pr_url="https://example.com/pr/7"),
    }

    def tiles_summary(var_name):
        return (
            "(function(){ var tiles = window.CR.board.boardTiles(%s, NOW);"
            " return tiles.map(function(t){"
            "   return t.kind === 'session' ? {kind:'session', id:t.session.id, state:t.state}"
            "                                : {kind:'agent-group', group:t.group};"
            " }); })()" % var_name
        )

    js = []
    js.append("var NOW = %d;" % NOW)
    js.append("var OUT = {};")

    js.append("var rankSessions = %s;" % json.dumps(rank_sessions))
    js.append("OUT.rank_order = %s;" % tiles_summary("rankSessions"))

    js.append("var pinSessions = %s;" % json.dumps(pin_sessions))
    js.append("OUT.pin_order = %s;" % tiles_summary("pinSessions"))

    js.append("var idleSessions = %s;" % json.dumps(idle_sessions))
    js.append("OUT.idle_tiles = %s;" % tiles_summary("idleSessions"))
    js.append("OUT.idle_state_direct = window.CR.board.sessionState(idleSessions[0], NOW);")

    js.append("var capSessions = %s;" % json.dumps(cap_sessions))
    js.append("OUT.cap_default = window.CR.board.boardTiles(capSessions, NOW).length;")
    js.append("window.localStorage.setItem('cr.boardTileCount', JSON.stringify(5));")
    js.append("OUT.cap_five = window.CR.board.boardTiles(capSessions, NOW).length;")
    js.append("window.localStorage.setItem('cr.boardTileCount', JSON.stringify(20));")
    js.append("OUT.cap_clamp_high = window.CR.board.boardTiles(capSessions, NOW).length;")
    js.append("window.localStorage.setItem('cr.boardTileCount', JSON.stringify(1));")
    js.append("OUT.cap_clamp_low = window.CR.board.boardTiles(capSessions, NOW).length;")
    js.append("window.localStorage.removeItem('cr.boardTileCount');")

    js.append("var agentSessions = %s;" % json.dumps(agent_sessions))
    js.append("OUT.agent_tiles = %s;" % tiles_summary("agentSessions"))
    js.append("OUT.agent_groups_of_agent_sessions = window.CR.board.agentGroups(agentSessions, NOW)"
               ".map(function(g){ return g.group; });")

    js.append("var stateProbe = %s;" % json.dumps(state_probe))
    js.append("OUT.states = {};")
    js.append("Object.keys(stateProbe).forEach(function(k){"
              " OUT.states[k] = window.CR.board.sessionState(stateProbe[k], NOW); });")

    js.append("var railSessions = %s;" % json.dumps(rail_sessions))
    js.append("(function(){ var r = window.CR.board.railOrder(railSessions);"
              " OUT.rail_pinned = r.pinned.map(function(s){ return s.id; });"
              " OUT.rail_unpinned = r.unpinned.map(function(s){ return s.id; }); })();")

    js.append("var groupSessions = %s;" % json.dumps(group_sessions))
    js.append("OUT.agent_groups = window.CR.board.agentGroups(groupSessions, NOW).map(function(g){"
              " return { group: g.group, label: g.label, mtime: g.mtime,"
              "          ids: g.sessions.map(function(s){ return s.id; }) }; });")

    js.append("var triageSessions = %s;" % json.dumps(triage_sessions))
    js.append("OUT.triage = window.CR.board.triageCounts(triageSessions, NOW);")

    js.append("var prSessions = %s;" % json.dumps(pr_sessions))
    js.append("OUT.pr_with = window.CR.board.prInfo(prSessions.with_pr, 'landed');")
    js.append("OUT.pr_without = window.CR.board.prInfo(prSessions.without_pr, 'landed');")
    js.append("OUT.pr_not_landed = window.CR.board.prInfo(prSessions.not_landed, 'working');")

    return "\n".join(js)


# ---------------------------------------------------------------------------
# Detail fixtures (epoch MILLISECONDS + ISO strings — the detail-dict's time unit
# via parseT()/Date.parse() — EXCEPT todos[].started_at/ended_at, which are epoch
# SECONDS (a number), the same convention as session.mtime/now, per
# aitracker/util.py:_ts_epoch and providers/claude.py:1209-1210. Confirmed against a
# live /api/session payload (curl'd during Bug 1 verification): a real todo looks like
# {"started_at": None, "ended_at": 1787654030.205} — started_at only gets a value when
# the transcript recorded an explicit TaskUpdate to "in_progress", which many real
# sessions never do.
# ---------------------------------------------------------------------------

BASE_MS = 1_700_000_000_000


def epoch_sec(ms):
    """Epoch milliseconds -> epoch SECONDS float, matching util._ts_epoch's own output
    shape for todos[].started_at/ended_at (never an ISO string, unlike the `.t` fields)."""
    return ms / 1000.0


def _detail_driver_js():
    # 9) spineSegments fallback: no todos[].started_at anywhere -> equal-width split,
    #    never a nonsensical (NaN/negative) width.
    fallback_detail = make_detail(
        todos=[
            {"content": "a", "status": "completed", "activeForm": ""},
            {"content": "b", "status": "in_progress", "activeForm": ""},
            {"content": "c", "status": "pending", "activeForm": ""},
            {"content": "d", "status": "pending", "activeForm": ""},
        ],
        requests=[{"t": iso_ms(BASE_MS - 100_000), "text": "go"}],
    )

    # 9b) BUG 1 REGRESSION: the exact real-world shape confirmed live — every todo
    #     carries started_at/ended_at keys (claude.py always sets both), but started_at
    #     is None throughout (no in_progress TaskUpdate ever recorded) even though
    #     ended_at IS populated for the completed todo. Must still fall back honestly,
    #     never mistake a lone ended_at for real timing.
    only_ended_detail = make_detail(
        todos=[
            {"content": "a", "status": "completed", "activeForm": "",
             "started_at": None, "ended_at": epoch_sec(BASE_MS - 190_000)},
            {"content": "b", "status": "in_progress", "activeForm": "",
             "started_at": None, "ended_at": None},
            {"content": "c", "status": "pending", "activeForm": "",
             "started_at": None, "ended_at": None},
        ],
        requests=[{"t": iso_ms(BASE_MS - 200_000), "text": "go"}],
    )

    # 10) spineSegments time-proportional: THE FIELD NAMES /api/session REALLY EMITS —
    #     snake_case, epoch-seconds numbers (see epoch_sec() above), not the camelCase
    #     ISO-string shape a prior version of this fixture wrongly assumed (that
    #     fixture passed while Bug 1 shipped: production read camelCase, so this test's
    #     own made-up camelCase fixture "worked" without ever exercising the real
    #     payload shape). Widths must still track actual elapsed time, not todo count:
    #     done=10s spent, running=190s spent (so far), 1 pending. Numbers chosen so the
    #     expected percentages are exact (see the test for the by-hand derivation):
    #     done 4.4%, running 83.6%, pending 12%.
    t0_start = BASE_MS - 200_000
    t0_end = BASE_MS - 190_000
    t1_start = BASE_MS - 190_000
    now_ms_for_timed = BASE_MS
    timed_detail = make_detail(
        todos=[
            {"content": "done-task", "status": "completed", "activeForm": "",
             "started_at": epoch_sec(t0_start), "ended_at": epoch_sec(t0_end)},
            {"content": "running-task", "status": "in_progress", "activeForm": "",
             "started_at": epoch_sec(t1_start), "ended_at": None},
            {"content": "pending-task", "status": "pending", "activeForm": "",
             "started_at": None, "ended_at": None},
        ],
        requests=[{"t": iso_ms(t0_start), "text": "go"}],
    )

    # 11) spineSegments with zero todos: honest "no tasks recorded", no fabricated segments.
    empty_detail = make_detail(todos=[])

    # 12) mergeTimeline: prompts + narration + decisions + commands merge into ONE
    #     chronologically-ordered list.
    merge_detail = make_detail(
        requests=[{"t": iso_ms(BASE_MS + 10_000), "text": "prompt"}],
        narrative=[{"t": iso_ms(BASE_MS + 5_000), "text": "narration"}],
        decisions=[{"t": iso_ms(BASE_MS + 15_000), "questions": [{"q": "Q?"}]}],
        commands=[{"t": iso_ms(BASE_MS + 0), "cmd": "ls", "ok": True, "kind": "shell"}],
    )

    js = []
    js.append("var OUT2 = {};")

    js.append("var fallbackDetail = %s;" % json.dumps(fallback_detail))
    js.append("OUT2.fallback = (function(){"
              " var r = window.CR.detail._internal.spineSegments(fallbackDetail, %d);"
              " return { timeAccurate: r.timeAccurate, total: r.total,"
              "          widths: r.segments.map(function(s){ return s.widthPct; }),"
              "          sum: r.segments.reduce(function(a,s){ return a+s.widthPct; }, 0) };"
              " })();" % now_ms_for_timed)

    js.append("var timedDetail = %s;" % json.dumps(timed_detail))
    js.append("OUT2.timed = (function(){"
              " var r = window.CR.detail._internal.spineSegments(timedDetail, %d);"
              " return { timeAccurate: r.timeAccurate,"
              "          widths: r.segments.map(function(s){ return { kind: s.kind, widthPct: s.widthPct }; }),"
              "          sum: r.segments.reduce(function(a,s){ return a+s.widthPct; }, 0) };"
              " })();" % now_ms_for_timed)

    js.append("var onlyEndedDetail = %s;" % json.dumps(only_ended_detail))
    js.append("OUT2.only_ended = (function(){"
              " var r = window.CR.detail._internal.spineSegments(onlyEndedDetail, %d);"
              " return { timeAccurate: r.timeAccurate, total: r.total,"
              "          widths: r.segments.map(function(s){ return s.widthPct; }) };"
              " })();" % now_ms_for_timed)

    js.append("var emptyDetail = %s;" % json.dumps(empty_detail))
    js.append("OUT2.empty = (function(){"
              " var r = window.CR.detail._internal.spineSegments(emptyDetail, %d);"
              " return { total: r.total, segCount: r.segments.length, ariaLabel: r.ariaLabel };"
              " })();" % now_ms_for_timed)

    js.append("var mergeDetail = %s;" % json.dumps(merge_detail))
    js.append("OUT2.merged = window.CR.detail._internal.mergeTimeline(mergeDetail)"
              ".map(function(e){ return { kind: e.kind, t: e.t }; });")

    return "\n".join(js)


def _full_driver_js():
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)
    parts = [
        _JS_PREAMBLE,
        bundle_js,
        _JS_MID,
        _board_driver_js(),
        _detail_driver_js(),
        r"""
console.log("===CR_LOGIC_JSON_START===");
console.log(JSON.stringify(Object.assign({}, OUT, OUT2)));
""",
    ]
    return "\n".join(parts)


def _extract_json(stdout):
    marker = "===CR_LOGIC_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    payload = stdout[idx + len(marker):].strip()
    return json.loads(payload)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRLogic(unittest.TestCase):
    """Pins the client-side derived values that ARE the Control Room design."""

    @classmethod
    def setUpClass(cls):
        js = _full_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Driver script failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    # -- boardTiles: ranking + cap -----------------------------------------

    def test_board_tiles_rank_order(self):
        """awaiting < flagged < working < landed, REGARDLESS of recency (mtime is
        deliberately reversed vs. rank in the fixture)."""
        got = [t["state"] for t in self.OUT["rank_order"]]
        self.assertEqual(got, ["awaiting", "flagged", "working", "landed"])

    def test_board_tiles_pinned_beats_recency(self):
        """Within the same rank, a pinned session outranks a strictly newer unpinned one."""
        got = [t["id"] for t in self.OUT["pin_order"]]
        self.assertEqual(got, ["old_pinned", "new_unpinned"])

    def test_board_tiles_idle_never_gets_a_tile(self):
        ids = [t["id"] for t in self.OUT["idle_tiles"]]
        self.assertNotIn("stale", ids)
        self.assertIn("fresh", ids)
        self.assertEqual(self.OUT["idle_state_direct"], "idle")

    def test_board_tile_cap(self):
        """Default cap is 8; cr.boardTileCount (localStorage) can lower it but the
        result is always clamped to [3, 8]."""
        self.assertEqual(self.OUT["cap_default"], 8)
        self.assertEqual(self.OUT["cap_five"], 5)
        self.assertEqual(self.OUT["cap_clamp_high"], 8)  # 20 clamps down to 8
        self.assertEqual(self.OUT["cap_clamp_low"], 3)   # 1 clamps up to 3

    def test_board_tiles_agent_no_group_regression(self):
        """Regression for the '950 sessions, 0 tiles' bug: agent:true, group:"" must
        still surface as an individual tile (it falls through both the individual
        exclusion and the group bucketing otherwise). A properly-grouped agent
        session must NOT also get an individual tile."""
        tiles = self.OUT["agent_tiles"]
        session_ids = [t["id"] for t in tiles if t["kind"] == "session"]
        self.assertIn("orphan_agent", session_ids)
        self.assertNotIn("grouped_agent", session_ids)
        group_kinds = [t for t in tiles if t["kind"] == "agent-group"]
        self.assertEqual([g["group"] for g in group_kinds], ["repoA"])
        # and agentGroups() itself never buckets the group-less agent session
        self.assertEqual(self.OUT["agent_groups_of_agent_sessions"], ["repoA"])

    # -- sessionState: every state, boundary pinned to config.LIVE_WINDOW --

    def test_session_state_every_value(self):
        self.assertEqual(self.OUT["states"]["awaiting"], "awaiting")
        self.assertEqual(self.OUT["states"]["flagged"], "flagged")
        self.assertEqual(self.OUT["states"]["working"], "working")
        self.assertEqual(self.OUT["states"]["landed"], "landed")
        self.assertEqual(self.OUT["states"]["idle"], "idle")

    def test_session_state_live_window_boundary_matches_server_constant(self):
        """The 'live' cutoff is exactly aitracker.config.LIVE_WINDOW seconds — read from
        config, never a second hardcoded '300' in this test — so a change to the
        server constant that the JS literal doesn't follow would be caught here."""
        self.assertEqual(self.OUT["states"]["boundary_live"], "working")
        self.assertEqual(self.OUT["states"]["boundary_idle"], "idle")

    # -- railOrder / agentGroups --------------------------------------------

    def test_rail_order_pinned_partition_and_recency(self):
        self.assertEqual(self.OUT["rail_pinned"], ["p_new", "p_old"])
        self.assertEqual(self.OUT["rail_unpinned"], ["u_new", "u_old"])

    def test_agent_groups_bucketing_and_idle_exclusion(self):
        groups = {g["group"]: g for g in self.OUT["agent_groups"]}
        self.assertEqual(set(groups.keys()), {"A", "B"})
        # idle session excluded from its own bucket
        self.assertEqual(groups["A"]["ids"], ["ga1"])
        self.assertEqual(groups["B"]["ids"], ["gb1"])
        self.assertEqual(groups["A"]["label"], "Repo A")
        # newest bucket (B, mtime NOW-3) sorts before A (mtime NOW-5)
        order = [g["group"] for g in self.OUT["agent_groups"]]
        self.assertEqual(order, ["B", "A"])

    # -- triageCounts: not mutually exclusive --------------------------------

    def test_triage_counts_not_mutually_exclusive(self):
        counts = self.OUT["triage"]
        self.assertEqual(counts["awaiting"], 1)
        self.assertEqual(counts["working"], 1)
        self.assertEqual(counts["flagged"], 1)
        # 2 sessions, 3 total count-contributions -> at least one session counted twice
        self.assertGreater(counts["awaiting"] + counts["working"] + counts["flagged"], 2)

    # -- spineSegments: time-proportional widths + the honest fallback ------

    def test_spine_segments_fallback_equal_width_when_no_timings(self):
        r = self.OUT["fallback"]
        self.assertFalse(r["timeAccurate"])
        self.assertEqual(r["total"], 4)
        self.assertAlmostEqual(r["sum"], 100.0, places=2)
        for w in r["widths"]:
            self.assertGreaterEqual(w, 3.0)   # FLOOR — never a vanishing sliver
            self.assertLessEqual(w, 100.0)    # never a nonsensical width
        # 2 active (1 done + 1 running) + 2 pending, evenly split -> all four ~25%
        for w in r["widths"]:
            self.assertAlmostEqual(w, 25.0, delta=0.5)

    def test_spine_segments_time_proportional_when_timings_exist(self):
        """BUG 1 pin: fixture uses the REAL keys /api/session emits — snake_case
        started_at/ended_at, epoch-seconds numbers (epoch_sec() above) — not the
        camelCase ISO-string shape a prior version of this fixture assumed. That
        wrong fixture is exactly what let Bug 1 ship: production read camelCase, so
        the old fixture's own made-up camelCase fields "worked" without ever
        exercising the real payload shape, and the spine never went time-proportional
        for any real session."""
        r = self.OUT["timed"]
        self.assertTrue(r["timeAccurate"])
        self.assertAlmostEqual(r["sum"], 100.0, places=2)
        by_kind = {w["kind"]: w["widthPct"] for w in r["widths"]}
        # done spent 10s, running has spent 190s (so far) of a 200s elapsed window:
        # done ~4.4%, running ~83.6%, pending gets the 12% remainder.
        self.assertAlmostEqual(by_kind["done"], 4.4, delta=0.5)
        self.assertAlmostEqual(by_kind["running"], 83.6, delta=0.5)
        self.assertAlmostEqual(by_kind["pending"], 12.0, delta=0.5)
        # the running (more time spent) segment must be visibly wider than the done one
        self.assertGreater(by_kind["running"], by_kind["done"])
        for w in r["widths"]:
            self.assertGreaterEqual(w["widthPct"], 0.0)
            self.assertLessEqual(w["widthPct"], 100.0)

    def test_spine_segments_no_todos_is_honest_not_fabricated(self):
        r = self.OUT["empty"]
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["segCount"], 0)
        self.assertEqual(r["ariaLabel"], "Progress: no tasks recorded.")

    def test_spine_segments_ended_at_alone_is_not_mistaken_for_real_timing(self):
        """Regression for the exact real-world shape confirmed live: a completed
        todo can carry a populated ended_at with started_at still None (no in_progress
        TaskUpdate was ever recorded). Must still take the honest equal-width
        fallback, never treat the lone ended_at as real timing."""
        r = self.OUT["only_ended"]
        self.assertFalse(r["timeAccurate"])
        self.assertEqual(r["total"], 3)
        for w in r["widths"]:
            self.assertGreaterEqual(w, 3.0)
            self.assertLessEqual(w, 100.0)

    # -- prInfo: Landed tile PR metadata (Bug 2) ------------------------------

    def test_pr_info_renders_pr_number_on_landed_tile(self):
        info = self.OUT["pr_with"]
        self.assertIsNotNone(info)
        self.assertEqual(info["label"], "#42")
        self.assertEqual(info["url"], "https://example.com/pr/42")

    def test_pr_info_renders_nothing_without_pr_num(self):
        self.assertIsNone(self.OUT["pr_without"])

    def test_pr_info_renders_nothing_off_landed_state(self):
        """A session that happens to carry pr_num but isn't in the 'landed' state
        (still working) shows no PR metadata — it's a Landed-tile-only affordance."""
        self.assertIsNone(self.OUT["pr_not_landed"])

    # -- mergeTimeline: one chronological list, NEWEST FIRST ------------------

    def test_merge_timeline_is_one_chronological_list(self):
        # Newest-first, so index 0 is the newest entry. That is the whole app's
        # convention -- the server already emits narration newest-first, and
        # app.js's navFirst() documents "index 0 = newest". The timeline used to
        # sort ascending, which silently inverted the panel against every other
        # surface; the owner reported it.
        merged = self.OUT["merged"]
        kinds = [e["kind"] for e in merged]
        self.assertEqual(kinds, ["ask", "prompt", "narration", "command"])
        times = [e["t"] for e in merged]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertGreater(times[0], times[-1])


# ---------------------------------------------------------------------------
# Theme-scope regression: "selecting Dark leaves the whole app light".
#
# Root cause (measured live): ext_cr.css's dark tokens are declared as
# `.tracker-next.is-dark`, and the light tokens as a BARE `.tracker-next`.
# `#cr-shell` used to carry its own bare `tracker-next` class in addition to
# `#nextRoot` (its ancestor) — so it re-declared the light token block
# directly on itself, shadowing every dark value it should have inherited.
# The invariant that must hold from now on: once the theme has resolved to
# dark, EVERY element carrying `.tracker-next` also carries `.is-dark`.
#
# This exercises the REAL init -> ensureMounted -> CR.board.mount ->
# applyTheme flow (not just the pure derivations TestCRLogic reaches into
# above), under a purpose-built DOM stub with an actual element tree + real
# classList tracking — the generic stub used above returns ONE shared dummy
# node for every query, which can't express "this specific element carries
# this specific class", so it can't see this bug at all.
# ---------------------------------------------------------------------------

_THEME_JS_PREAMBLE = r"""
globalThis.window = globalThis;

function makeDummy() {
  var self = {
    classList: { add: function () {}, remove: function () {}, toggle: function () { return false; }, contains: function () { return false; } },
    style: {}, dataset: {},
    setAttribute: function () {}, getAttribute: function () { return null; }, removeAttribute: function () {},
    appendChild: function (c) { return c; }, append: function () {}, remove: function () {}, insertBefore: function (c) { return c; },
    addEventListener: function () {}, removeEventListener: function () {},
    querySelector: function () { return self; }, querySelectorAll: function () { return [self]; },
    closest: function () { return self; }, firstElementChild: null, children: [],
    innerHTML: "", textContent: "", value: "", hidden: false,
    focus: function () {}, click: function () {}, scrollIntoView: function () {}
  };
  return self;
}
var dummy = makeDummy();

var _idRegistry = {};

// Walks REAL descendants only (never the root itself) collecting elements
// whose real classList (a Set, see makeReal below) contains `sel`'s class.
// Used for BOTH document.querySelectorAll(...) (root = the fake <body>) and
// a real element's own .querySelectorAll(...) (root = that element) — real
// DOM semantics never include the calling node itself either way.
function queryAllReal(root, sel) {
  var out = [];
  if (!sel || sel.charAt(0) !== '.') return out;
  var cls = sel.slice(1);
  (function walk(node) {
    (node._children || []).forEach(function (c) {
      if (c && c._classes && c._classes.has(cls)) out.push(c);
      walk(c);
    });
  })(root);
  return out;
}

function makeReal(tag) {
  var el = {
    tagName: String(tag || 'div').toUpperCase(),
    _classes: new Set(),
    _children: [],
    _attrs: {},
    _id: '',
    style: {}, dataset: {},
    hidden: false, innerHTML: '', textContent: '', value: '',
    parentNode: null
  };
  el.classList = {
    add: function () { for (var i = 0; i < arguments.length; i++) if (arguments[i]) el._classes.add(arguments[i]); },
    remove: function () { for (var i = 0; i < arguments.length; i++) el._classes.delete(arguments[i]); },
    toggle: function (c, force) {
      var has = el._classes.has(c);
      var want = (force === undefined) ? !has : !!force;
      if (want) el._classes.add(c); else el._classes.delete(c);
      return want;
    },
    contains: function (c) { return el._classes.has(c); }
  };
  Object.defineProperty(el, 'className', {
    get: function () { return Array.from(el._classes).join(' '); },
    set: function (v) { el._classes = new Set(String(v == null ? '' : v).split(/\s+/).filter(Boolean)); }
  });
  Object.defineProperty(el, 'id', {
    get: function () { return el._id; },
    set: function (v) { el._id = v; if (v) _idRegistry[v] = el; }
  });
  el.setAttribute = function (k, v) { el._attrs[k] = v; if (k === 'class') el.className = v; if (k === 'id') el.id = v; };
  el.getAttribute = function (k) { return (k in el._attrs) ? el._attrs[k] : null; };
  el.removeAttribute = function (k) { delete el._attrs[k]; };
  el.appendChild = function (c) { if (c) { el._children.push(c); c.parentNode = el; } return c; };
  el.append = function () { for (var i = 0; i < arguments.length; i++) el.appendChild(arguments[i]); };
  el.insertBefore = function (c) { if (c) { el._children.push(c); c.parentNode = el; } return c; };
  el.removeChild = function (c) { var idx = el._children.indexOf(c); if (idx >= 0) el._children.splice(idx, 1); return c; };
  el.remove = function () { if (el.parentNode) el.parentNode.removeChild(el); };
  el.addEventListener = function () {}; el.removeEventListener = function () {};
  el.focus = function () {}; el.click = function () {}; el.scrollIntoView = function () {};
  el.querySelectorAll = function (sel) { return queryAllReal(el, sel); };
  el.querySelector = function (sel) { return queryAllReal(el, sel)[0] || null; };
  el.closest = function () { return null; };
  Object.defineProperty(el, 'firstElementChild', { get: function () { return el._children[0] || null; } });
  Object.defineProperty(el, 'children', { get: function () { return el._children.slice(); } });
  return el;
}

var docBody = makeReal('body');
var nextRoot = makeReal('div');
nextRoot.id = 'nextRoot';
nextRoot.className = 'tracker-next cr';
nextRoot.hidden = true;
docBody.appendChild(nextRoot);

window.document = {
  createElement: function (tag) { return makeReal(tag); },
  createElementNS: function (ns, tag) { return makeReal(tag); },
  createTextNode: function (text) { var t = makeReal('#text'); t.textContent = text; return t; },
  getElementById: function (id) { return _idRegistry[id] || dummy; },
  querySelector: function (sel) { return queryAllReal(docBody, sel)[0] || null; },
  querySelectorAll: function (sel) { return queryAllReal(docBody, sel); },
  addEventListener: function () {}, removeEventListener: function () {}, dispatchEvent: function () {},
  documentElement: dummy, body: docBody, head: dummy, readyState: "complete"
};

var _THEME_STORAGE = {};
window.localStorage = {
  getItem: function (k) { return (k in _THEME_STORAGE) ? _THEME_STORAGE[k] : null; },
  setItem: function (k, v) { _THEME_STORAGE[k] = String(v); },
  removeItem: function (k) { delete _THEME_STORAGE[k]; }
};
// Seeded BEFORE the bundle runs -- the exact live scenario: preference already
// 'dark', UI already 'next' (a returning user with Dark selected), so init()
// actually mounts Control Room and calls applyTheme() for real.
window.localStorage.setItem('tracker.theme', 'dark');
window.localStorage.setItem('tracker.ui', 'next');

window.matchMedia = function () { return { matches: false, addEventListener: function () {}, addListener: function () {}, removeEventListener: function () {} }; };
window.fetch = function () { return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); }, text: function () { return Promise.resolve(""); }, headers: { get: function () { return null; } } }); };
// setTimeout runs its callback IMMEDIATELY (still inside the current
// synchronous script). ext_cr_boot.js's whole init() flow (buildRoots ->
// wireEntryButton -> setUiMode('next') -> ensureMounted -> CR.board.mount ->
// applyTheme) is queued via exactly one `setTimeout(init, 0)` at the end of
// its own IIFE (deferred there only so every OTHER concatenated ext_*.js
// file has finished defining window.CR.* first) -- running it synchronously
// here is safe for what this test exercises: CR.board is already defined
// (board.js sorts before boot.js), so its mount() runs for real; CR.detail/
// dialogs/term are not yet defined at that point, so their mounts fall back
// to safeMount()'s own try/catch placeholder path -- exactly what already
// happens if any of them ever throws for real.
window.setTimeout = function (fn) { if (typeof fn === 'function') fn(); return 0; };
window.setInterval = function () { return 0; };
window.clearInterval = function () {}; window.clearTimeout = function () {};
window.location = { href: "", search: "", pathname: "/", host: "localhost" };
window.navigator = { userAgent: "node", clipboard: { writeText: function () { return Promise.resolve(); } } };
window.CustomEvent = function (type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = function () { return 0; };
window.getComputedStyle = function () { return { getPropertyValue: function () { return ""; } }; };
window.getSelection = function () { return { toString: function () { return ""; } }; };
window.addEventListener = function () {}; window.removeEventListener = function () {}; window.dispatchEvent = function () {};
window.URLSearchParams = function () { return { get: function () { return null; } }; };
process.on("unhandledRejection", function () {});

try {
"""

_THEME_JS_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""

_THEME_JS_TAIL = r"""
var out = { scopes: [], mountedIds: Object.keys(_idRegistry) };
queryAllReal(docBody, '.tracker-next').forEach(function (el) {
  out.scopes.push({ id: el.id || null, classes: Array.from(el._classes).sort() });
});
out.nextRootIsDark = nextRoot.classList.contains('is-dark');
console.log("===CR_THEME_JSON_START===");
console.log(JSON.stringify(out));
"""


def _theme_scope_driver_js():
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)
    return "\n".join([_THEME_JS_PREAMBLE, bundle_js, _THEME_JS_MID, _THEME_JS_TAIL])


def _extract_theme_json(stdout):
    marker = "===CR_THEME_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRThemeScope(unittest.TestCase):
    """Regression for the '#cr-shell renders light under a dark #nextRoot' bug.

    Runs the REAL init -> ensureMounted -> CR.board.mount -> applyTheme flow
    (not just the pure derivations TestCRLogic reaches into above) with
    tracker.theme=dark and tracker.ui=next already seeded in localStorage --
    the exact state a returning user with Dark selected loads into.
    """

    @classmethod
    def setUpClass(cls):
        js = _theme_scope_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Theme-scope driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_theme_json(stdout)

    def test_nextroot_resolves_dark(self):
        self.assertTrue(self.OUT["nextRootIsDark"], "resolved theme should be dark per seeded localStorage")

    def test_shell_actually_mounted(self):
        """Sanity check so the invariant below can't pass VACUOUSLY on an empty
        tree: if CR.board.mount() silently failed to run under this stub,
        #cr-shell would never have been built (and registered) at all. (It is
        correctly ABSENT from the tracker-next scope list itself -- that is
        the fix: the shell no longer carries the class.)"""
        self.assertIn("cr-shell", self.OUT["mountedIds"],
                      "CR.board.mount() should have built #cr-shell; ids seen: %r" % self.OUT["mountedIds"])

    def test_every_tracker_next_element_also_carries_is_dark(self):
        """The actual regression guard: no element carrying `.tracker-next` may
        lack `is-dark` once the theme has resolved to dark -- otherwise that
        element's own bare `.tracker-next {...}` rule (ext_cr.css) re-declares
        the LIGHT token block directly on itself, shadowing the dark values it
        should inherit from its #nextRoot ancestor (the live bug this pins:
        `#cr-shell` used to carry a redundant bare `tracker-next` class)."""
        offenders = [s for s in self.OUT["scopes"] if "is-dark" not in s["classes"]]
        self.assertEqual(offenders, [], "these elements carry tracker-next without is-dark: %r" % offenders)


# ---------------------------------------------------------------------------
# Sound-notification regression: "notifies with sound every time" (reported
# twice against Control Room).
#
# Round 1 (fixed by commit 8fe15ca, still correct, re-pinned by the first three
# assertions below): a parallel completion detector scanned `ended` across
# every /api/list session with a baseline that only ran once, so a machine
# with hundreds of already-finished sessions kept re-announcing them, with
# sound, on every later poll. The fix reuses app.js's own checkCompletions(d) —
# it watches only the CURRENTLY VIEWED session's `agents_bg`/`shells`, keyed
# by id, and silently re-baselines (no notify) on the first poll and on a
# session switch, notifying only a real running -> not-running transition.
#
# Round 2 (fixed here): ext_cr_dialogs.js's toast() — the function every
# routine Control Room confirmation reaches (rename/flag/note/run-command/etc.,
# ~20 call sites in ext_cr_boot.js, ALL bare visual confirmations in the
# classic dashboard) — ALSO raised its own `new Notification(...)` whenever the
# tab was hidden, soundOn-gated but otherwise unconditional. A desktop
# Notification carries the OS's own alert sound by default, so backgrounding
# the tab and doing something as routine as renaming a session played an
# audible alert though nothing had "finished" — exactly the reported "sound
# every time" behaviour, and something the classic dashboard's own toast()
# (app.js ~1139) never does at all: it is a pure visual banner. Deleted the
# block; a real completion still gets its (unchanged) desktop alert from
# app.js's own notifyDone(), which toast() was never the only path for.
#
# Exercises the REAL exported functions (app.js's checkCompletions/notifyDone/
# beep, reached bare because this driver runs INSIDE the bundle's own try{}
# block scope -- not window.CR.* -- and ext_cr_dialogs.js's real
# window.CR.dialogs.toast(), after a real mount()) rather than re-deriving the
# logic in Python.
# ---------------------------------------------------------------------------

_SOUND_JS_PREAMBLE = r"""
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus() {}, click() {}
  };
  return self;
}

var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete",
  hidden: false
};

const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
// beep() (app.js) needs a WebAudio stub; notifyDone()'s desktop-alert branch
// (app.js + ext_cr_dialogs.js's toast(), pre-fix) needs a Notification stub.
window.AudioContext = function () {
  return { state: "running", resume() {}, currentTime: 0,
    createOscillator() { return { type: "", frequency: { value: 0 }, connect() {}, start() {}, stop() {} }; },
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; },
    destination: {} };
};
window.Notification = function (title, opts) { this.title = title; this.body = opts && opts.body; this.onclick = null; };
window.Notification.permission = "granted";
window.Notification.requestPermission = () => Promise.resolve("granted");
process.on("unhandledRejection", () => {});

try {
"""

_SOUND_JS_DRIVER = r"""
// Still inside the bundle's own try{} block: `cur`/`soundOn`/`notifSession`/
// `notifRunning` are app.js's real top-level `let` bindings (block-scoped —
// NOT reachable once the enclosing try{} closes), and `beep`/`checkCompletions`/
// `notifyDone` are its real top-level functions, reached bare by design (same
// note ext_cr_boot.js's own header carries about this shared script scope).
var beepCount = 0;
var origBeep = beep;
beep = function () { beepCount++; return origBeep.apply(this, arguments); };

function mkAgent(id, running) { return { id: id, task: "task-" + id, running: running }; }
function mkShell(id, running) { return { id: id, desc: "shell-" + id, cmd: "echo", running: running }; }

var results = {};

// 1) First poll ever, session already has several FINISHED agents/shells ->
//    baseline only, ZERO sound (the exact "hundreds of already-finished
//    sessions" shape round 1's bug mishandled).
cur = "sessA";
notifSession = null; notifRunning = null;
beepCount = 0;
checkCompletions({ agents_bg: [mkAgent("a1", false), mkAgent("a2", false)], shells: [mkShell("s1", false)] });
results.firstPoll = beepCount;
checkCompletions({ agents_bg: [mkAgent("a1", false), mkAgent("a2", false)], shells: [mkShell("s1", false)] });
results.firstPollSecondTick = beepCount;   // nothing changed on a later tick either

// 2) Session switch -> silent re-baseline, ZERO sound, even though the new
//    session's items are already running=false.
cur = "sessB";
beepCount = 0;
checkCompletions({ agents_bg: [mkAgent("b1", false)], shells: [] });
results.sessionSwitch = beepCount;

// 3) A genuine running -> finished transition on the session actually being
//    viewed, sound ON -> EXACTLY one beep.
soundOn = true;
cur = "sessC";
notifSession = null; notifRunning = null;
checkCompletions({ agents_bg: [mkAgent("c1", true)], shells: [] });   // baseline: c1 running
beepCount = 0;
checkCompletions({ agents_bg: [mkAgent("c1", false)], shells: [] }); // c1 finished
results.realTransitionSoundOn = beepCount;

// 4) Same genuine transition, sound OFF -> zero.
soundOn = false;
cur = "sessD";
notifSession = null; notifRunning = null;
checkCompletions({ agents_bg: [mkAgent("d1", true)], shells: [] });
beepCount = 0;
checkCompletions({ agents_bg: [mkAgent("d1", false)], shells: [] });
results.realTransitionSoundOff = beepCount;
soundOn = true;

// 5) Round 2's actual bug: a MUNDANE confirmation (rename/flag/note/etc.) must
//    NOT raise a desktop Notification while the tab is hidden — only a real
//    notifyDone() completion may. Exercise the REAL exported toast() the same
//    way every ext_cr_boot.js confirmation reaches it (ctx.on('notify', ...)
//    -> toast(payload)), after mount()ing it for real.
var notifyCtorCalls = 0;
var RealNotification = window.Notification;
window.Notification = function (title, opts) { notifyCtorCalls++; return new RealNotification(title, opts); };
window.Notification.permission = "granted";
window.CR.dialogs.mount(makeEl(), {});
document.hidden = true;
window.CR.dialogs.toast({ text: "Renamed." });          // a mundane confirmation, NOT a completion
results.mundaneConfirmationRaisedNotification = notifyCtorCalls;

// Sanity check in the SAME harness: a real completion still gets its
// (unchanged, soundOn-gated) desktop alert straight from app.js's own
// notifyDone() -- proving the fix removed only the spurious path.
notifyCtorCalls = 0;
soundOn = true;
notifyDone("Background agent finished", "some task");
results.realCompletionStillRaisesNotification = notifyCtorCalls;
document.hidden = false;
window.Notification = RealNotification;

console.log("===CR_SOUND_JSON_START===");
console.log(JSON.stringify(results));
"""

_SOUND_JS_CLOSER = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


def _sound_driver_js():
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)
    return "\n".join([_SOUND_JS_PREAMBLE, bundle_js, _SOUND_JS_DRIVER, _SOUND_JS_CLOSER])


def _extract_sound_json(stdout):
    marker = "===CR_SOUND_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRSoundNotifications(unittest.TestCase):
    """Pins the sound/desktop-notification behaviour to the classic dashboard's own
    (same trigger, same soundOn gate, same code path) -- regression for both rounds
    of the "notifies with sound every time" complaint."""

    @classmethod
    def setUpClass(cls):
        js = _sound_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Sound driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_sound_json(stdout)

    def test_first_poll_with_already_finished_items_is_silent(self):
        """Round 1's exact bug shape: a first look at a session whose background
        agents/shells are already done must never beep -- only baseline."""
        self.assertEqual(self.OUT["firstPoll"], 0)
        self.assertEqual(self.OUT["firstPollSecondTick"], 0)

    def test_session_switch_is_silent(self):
        self.assertEqual(self.OUT["sessionSwitch"], 0)

    def test_real_completion_beeps_exactly_once_when_sound_on(self):
        self.assertEqual(self.OUT["realTransitionSoundOn"], 1)

    def test_real_completion_is_silent_when_sound_off(self):
        self.assertEqual(self.OUT["realTransitionSoundOff"], 0)

    def test_mundane_confirmation_never_raises_a_desktop_notification(self):
        """Round 2's actual bug: ext_cr_dialogs.js's toast() -- reached by every
        routine confirmation (rename/flag/note/run-command/...) -- used to also pop
        a desktop Notification (with the OS's own alert sound) whenever the tab was
        hidden. The classic dashboard's own toast() never does this for anything;
        only a real completion (notifyDone(), pinned above) is allowed to."""
        self.assertEqual(self.OUT["mundaneConfirmationRaisedNotification"], 0)

    def test_real_completion_still_raises_a_desktop_notification(self):
        """Sanity check alongside the assertion above: the fix must not have also
        silenced the legitimate desktop alert for a genuine completion."""
        self.assertEqual(self.OUT["realCompletionStillRaisesNotification"], 1)


if __name__ == "__main__":
    unittest.main()
