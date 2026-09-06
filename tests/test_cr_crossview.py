"""Pins the control room's migration onto window.uiState (aitracker/web/app.js's shared
cross-view UI-state store) for the fields the user's ruling named: the triage filter, the
rail's search query and "live only" toggle, expanded agent groups, and the board's cap +
show-all toggle.

Idiom copied from tests/test_cr_logic.py (itself copied from test_page_bundle.py): build the
REAL assembled page (aitracker.page.build_page()), extract the inlined <script> bundle, execute
it under a minimal stub DOM in Node, then reach into window.CR.board / window.uiState. Skips
cleanly (not a failure) when node is unavailable.

Why boardTiles/setFilter/etc. are asserted directly rather than via a simulated click: this
file's stub DOM's addEventListener() is a no-op (see test_cr_logic.py's own comment on its
"real tracked DOM" variant, used only where a render's actual DOM text must be inspected) — a
click can't be dispatched through it. ext_cr_board.js's createBoard() return object exposes
setFilter/isRailGroupOpen/getActiveFilter/getRailLiveOnly/getSearchQuery specifically for this
(see that file's own comment at the exposure site), the same "expose internals for tests"
pattern boardTiles/sessionState already use.
"""
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
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)

NOW = 1_700_000_000  # fixed epoch seconds, matches tests/test_cr_logic.py's convention


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


def make_session(id, mtime, **overrides):
    """Same shape as tests/test_cr_logic.py's make_session — kept minimal here since these
    tests only exercise the cap/show-all slicing and the triage/rail state mirrors, not
    ranking or state derivation (already pinned there)."""
    s = {
        "id": id, "project": "proj", "cwd": "/tmp/proj", "title": "t", "prompt": "p",
        "source": "claude",
        "agent": False, "group": "", "groupLabel": "", "parentId": "",
        "bg": 0, "waiting": False, "ended": False, "mtime": mtime,
        "todo_total": 0, "todo_done": 0, "todo_current": None, "todo_current_index": None,
        "pr_num": None, "pr_url": None, "pr_repo": None, "pr_state": "",
        "now_line": "",
        "pinned": False, "note_count": 0, "open_flags": 0,
        "continued_as": "", "continued_from": "",
        "fail_cmd": None,
    }
    s.update(overrides)
    return s


# Minimal stub DOM — identical in spirit to test_cr_logic.py's _JS_PREAMBLE (no click
# simulation, no tracked classList; enough for createBoard()/mount() to run without throwing
# and for the exposed pure/test accessors to be called directly).
_JS_PREAMBLE = r"""
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    appendChild() {}, append() {}, remove() {}, insertBefore() {}, removeChild() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", value: "", hidden: false, focus() {}, click() {}, scrollIntoView() {}
  };
  return self;
}

var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createElementNS: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};

var _localStorage = {%(seed)s};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = String(v); },
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


def _driver_js(seed_ui_state, body_js):
    """`seed_ui_state`: dict written to localStorage['tracker.uiState'] BEFORE the bundle runs
    (i.e. before app.js's `let _uiState=JSON.parse(...)` / ext_cr_board.js's createBoard()
    module-init both execute) — this is what proves "read the initial value FROM uiState",
    not merely "uiState.set() after the fact happens to work"."""
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)
    seed_json = json.dumps(json.dumps(seed_ui_state))  # JSON string literal, doubly-encoded for embedding in JS
    preamble = _JS_PREAMBLE % {"seed": "'tracker.uiState': %s" % seed_json}
    tail = r"""
console.log("===CR_CROSSVIEW_JSON_START===");
console.log(JSON.stringify(OUT));
"""
    return "\n".join([preamble, bundle_js, _JS_MID, "var OUT = {};", body_js, tail])


def _extract_json(stdout):
    marker = "===CR_CROSSVIEW_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _run(seed_ui_state, body_js):
    js = _driver_js(seed_ui_state, body_js)
    returncode, stdout, stderr = _run_node(js)
    if returncode != 0:
        raise AssertionError(
            "Driver script failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (returncode, stdout, stderr)
        )
    return _extract_json(stdout)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRCrossViewInitialRead(unittest.TestCase):
    """'Read the initial value FROM uiState at mount so a value set in the other view is
    honoured on arrival' — seeds localStorage['tracker.uiState'] as if classic (or another
    browser tab) had already set filter/liveOnly/query, BEFORE the control room's own module
    state initialises, and checks the control room picked it up rather than starting from a
    private null/false/'' default."""

    def test_filter_liveonly_query_read_from_uistate_not_a_private_initializer(self):
        out = _run(
            {"filter": "working", "liveOnly": True, "query": "zzz"},
            r"""
OUT.activeFilter = window.CR.board.getActiveFilter();
OUT.railLiveOnly = window.CR.board.getRailLiveOnly();
OUT.searchQuery = window.CR.board.getSearchQuery();
""",
        )
        self.assertEqual(out["activeFilter"], "working")
        self.assertTrue(out["railLiveOnly"])
        self.assertEqual(out["searchQuery"], "zzz")

    def test_absent_uistate_falls_back_to_the_old_defaults(self):
        """Sanity check alongside the assertion above: nothing seeded -> the same defaults
        the control room always had (null filter, liveOnly off, empty query) — the migration
        must not have changed behaviour for a first-ever visit."""
        out = _run(
            {},
            r"""
OUT.activeFilter = window.CR.board.getActiveFilter();
OUT.railLiveOnly = window.CR.board.getRailLiveOnly();
OUT.searchQuery = window.CR.board.getSearchQuery();
""",
        )
        self.assertIsNone(out["activeFilter"])
        self.assertFalse(out["railLiveOnly"])
        self.assertEqual(out["searchQuery"], "")

    def test_groupsopen_seeded_in_uistate_is_honoured_by_israilgroupopen(self):
        """'groupsOpen' — same key space as classic's own per-group `s.group` buckets (see
        isRailGroupOpen()'s comment in ext_cr_board.js). Seeded via localStorage, exactly like
        the filter/liveOnly/query test above, and asserted with NO mount() call: mounting would
        pull in app.js's own 'groupsOpen' subscriber, which prunes any entry that isn't a real,
        currently-known group/session — correct real-app behaviour, but it would make this
        specific assertion depend on classic's session list (out of scope here) rather than on
        the control room's own read of the shared field."""
        out = _run(
            {"groupsOpen": ["repoA"]},
            r"""
OUT.isOpenA = window.CR.board.isRailGroupOpen('repoA');
OUT.isOpenB = window.CR.board.isRailGroupOpen('repoB');
""",
        )
        self.assertTrue(out["isOpenA"])
        self.assertFalse(out["isOpenB"])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRCrossViewWriteThrough(unittest.TestCase):
    """'Write THROUGH uiState on every change' and 'SUBSCRIBE so that a change made in the
    other view ... re-renders the control room' (guarded against a render loop)."""

    def test_setfilter_persists_filter_into_uistate(self):
        out = _run(
            {},
            r"""
window.CR.board.mount(document.createElement('div'), {});
window.CR.board.setFilter('flagged');
OUT.uistate_filter = window.uiState.get('filter', null);
OUT.local_mirror = window.CR.board.getActiveFilter();
""",
        )
        self.assertEqual(out["uistate_filter"], "flagged")
        self.assertEqual(out["local_mirror"], "flagged")

    def test_setfilter_toggles_off_back_to_null(self):
        """setFilter(key) on an ALREADY-active key clears it — same toggle behaviour as
        before the uiState migration, just now round-tripped through the shared store."""
        out = _run(
            {},
            r"""
window.CR.board.mount(document.createElement('div'), {});
window.CR.board.setFilter('pinned');
window.CR.board.setFilter('pinned');
OUT.uistate_filter = window.uiState.get('filter', null);
""",
        )
        self.assertIsNone(out["uistate_filter"])

    def test_remote_uistate_change_updates_the_local_mirror_after_mount(self):
        """Simulates a change made in the OTHER view (or another browser tab): after mount()
        has registered the uiState.subscribe() callback, a plain uiState.set() — exactly what
        app.js's own 'storage' listener re-emits through — must reach the control room's local
        mirrors without any control-room action of its own. ('groupsOpen' is covered separately
        above, seeded rather than live-set, for the reason given on that test.)"""
        out = _run(
            {},
            r"""
window.CR.board.mount(document.createElement('div'), {});
window.uiState.set('liveOnly', true);
window.uiState.set('filter', 'awaiting');
OUT.railLiveOnly = window.CR.board.getRailLiveOnly();
OUT.activeFilter = window.CR.board.getActiveFilter();
""",
        )
        self.assertTrue(out["railLiveOnly"])
        self.assertEqual(out["activeFilter"], "awaiting")

    def test_no_render_loop_on_a_no_op_remote_write(self):
        """Guard against a render loop: uiState.set() with the SAME value it already holds
        must not re-trigger anything observable going wrong — re-affirming the current filter
        (e.g. a 2s poll on the other view re-saving unchanged state) is a no-op, and calling
        setFilter or re-setting the same uiState value repeatedly must converge, not throw or
        toggle. Ten repeats of "set the same value" must leave the state exactly as set."""
        out = _run(
            {},
            r"""
window.CR.board.mount(document.createElement('div'), {});
for (var i = 0; i < 10; i++) { window.uiState.set('filter', 'flagged'); }
OUT.activeFilter = window.CR.board.getActiveFilter();
for (var j = 0; j < 10; j++) { window.CR.board.setFilter('flagged'); window.CR.board.setFilter('flagged'); }
OUT.afterDoubleToggle = window.CR.board.getActiveFilter();
""",
        )
        self.assertEqual(out["activeFilter"], "flagged")
        # setFilter('flagged') twice each loop = net no-op toggle each time -> unchanged
        self.assertEqual(out["afterDoubleToggle"], "flagged")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRShowAllToggle(unittest.TestCase):
    """Cap + show-all toggle: boardTiles(sessions, now, filterKey, showAll) lifts the cap only
    when explicitly asked; setFilter() resets 'showAll' to false on every tab switch."""

    CAP_SESSIONS_JS = "var capSessions = %s;" % json.dumps(
        [make_session("s%d" % i, NOW - i, waiting=True) for i in range(12)]
    )

    def test_boardtiles_two_arg_call_stays_capped(self):
        """Regression: the pre-existing 2-arg callers (ext_cr_boot.js's computeTriage,
        ext_cr_detail.js's stepSession) must keep getting the capped list exactly as before —
        showAll defaults to falsy when omitted."""
        out = _run(
            {},
            self.CAP_SESSIONS_JS + r"""
OUT.two_arg_length = window.CR.board.boardTiles(capSessions, %d).length;
""" % NOW,
        )
        self.assertEqual(out["two_arg_length"], 8)  # default cap

    def test_boardtiles_showall_false_matches_two_arg_default(self):
        out = _run(
            {},
            self.CAP_SESSIONS_JS + r"""
OUT.explicit_false_length = window.CR.board.boardTiles(capSessions, %d, null, false).length;
""" % NOW,
        )
        self.assertEqual(out["explicit_false_length"], 8)

    def test_boardtiles_showall_true_lifts_the_cap(self):
        out = _run(
            {},
            self.CAP_SESSIONS_JS + r"""
var tiles = window.CR.board.boardTiles(capSessions, %d, null, true);
OUT.showall_length = tiles.length;
OUT.showall_total = tiles.total;
""" % NOW,
        )
        self.assertEqual(out["showall_length"], 12)
        self.assertEqual(out["showall_total"], 12)  # total is the same pre-cap count either way

    def test_setfilter_resets_showall_to_false_on_tab_switch(self):
        out = _run(
            {},
            r"""
window.CR.board.mount(document.createElement('div'), {});
window.uiState.set('showAll', true);
OUT.before = window.uiState.get('showAll', false);
window.CR.board.setFilter('working');   // a genuine tab switch (null -> 'working')
OUT.after = window.uiState.get('showAll', false);
""",
        )
        self.assertTrue(out["before"])
        self.assertFalse(out["after"])


if __name__ == "__main__":
    unittest.main()
