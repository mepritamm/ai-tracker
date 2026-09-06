"""Regression tests for the shared UI-state store (window.uiState, aitracker/web/app.js).

The user's ruling: any UI state set in one view (classic dashboard vs. control room) must be
shared across the whole app. Before this store existed, the same concept lived in two separate
variables per view (`liveOnly` vs `railLiveOnly`, etc). This file checks:

1. STATIC: the store's standardised field names and its single localStorage key are actually
   present in the served page (so a future edit can't quietly rename/drop one), and the one-time
   `agrpOpen` -> `groupsOpen` migration code exists.
2. BEHAVIOURAL (skipped if node is unavailable): the store's actual runtime semantics, executed
   for real in node against the real aitracker/web/app.js source -- get/set/subscribe, the
   no-op-on-unchanged-value rule, single-key persistence shape, and the agrpOpen migration
   actually moving a pre-existing legacy value into the new store.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from aitracker import page

_AITRACKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aitracker")
_WEB = os.path.join(_AITRACKER, "web")
_HAS_NODE = shutil.which("node") is not None


def _read_app_js():
    with open(os.path.join(_WEB, "app.js"), encoding="utf-8") as fh:
        return fh.read()


def _read_page():
    return page.build_page()


# ============================================================================
# 1. Static: field names / key name / migration code present in the served page.
# ============================================================================

class TestUiStateStatic(unittest.TestCase):
    def test_store_exposed_on_window(self):
        js = _read_app_js()
        self.assertIn("window.uiState=uiState", js)
        self.assertIn("uiState={", js)
        self.assertIn("get(key,fallback)", js)
        self.assertIn("set(key,value)", js)
        self.assertIn("subscribe(fn)", js)

    def test_single_localstorage_key(self):
        js = _read_app_js()
        self.assertIn('UI_STATE_KEY="tracker.uiState"', js)
        # every persistence write goes through the one constant, never a second literal key
        self.assertEqual(js.count('"tracker.uiState"'), 1)

    def test_standard_field_names_present(self):
        # Scoped to the fields app.js ITSELF reads/writes -- 'filter' and 'showAll' are the Board's
        # fields (implemented in ext_cr_board.js, a different file/agent), so asserting them here
        # would either be vacuous (a bare quoted string is satisfied by the doc comment at the top
        # of this file, which is exactly the bug this test used to have) or couple this file's
        # pass/fail to a concurrently-edited file this test doesn't own. That coverage belongs in
        # ext_cr_board.js's own test file, not here. Each assertion below is a genuine call-site
        # pattern (an actual uiState.get/set invocation), not a bare quoted field name, so deleting
        # the real implementation -- not just the comment -- makes it fail.
        js = _read_app_js()
        call_sites = [
            "uiState.get('sid',null)", "uiState.set('sid',cur)",
            "uiState.get('liveOnly',false)", "uiState.set('liveOnly',!liveOnly)",
            "uiState.set('query',q)", "uiState.get('query','')",
            "uiState.set('groupsOpen'", "uiState.get('groupsOpen',", "uiState.get('groupsOpen',null)",
            "uiState.get('scroll',{})", "uiState.set('scroll',",
        ]
        for site in call_sites:
            self.assertIn(site, js, f"call site {site!r} missing from app.js")

    def test_filter_and_showall_are_not_apps_own_fields(self):
        # Documents the DEFECT-2 finding and guards against it recurring here: app.js's role for
        # these two Board-only fields is limited to naming them in the shared-shape doc comment
        # (line ~11-12) -- it must not itself read/write them (that would fork the Board's own
        # state handling, which ext_cr_board.js owns). If this starts failing because app.js now
        # has a genuine 'filter'/'showAll' call site, move that coverage into this file for real
        # (mirroring test_standard_field_names_present above) instead of just loosening this check.
        js = _read_app_js()
        for field in ["'filter'", "'showAll'"]:
            self.assertNotIn(f"uiState.get({field}", js)
            self.assertNotIn(f"uiState.set({field}", js)

    def test_field_names_survive_page_assembly(self):
        # page.build_page() inlines app.js verbatim into the served <script> -- confirm the
        # store's identity (not just its individual field names, which other code could coin
        # by coincidence) makes it into what actually ships.
        html = _read_page()
        self.assertIn("window.uiState=uiState", html)
        self.assertIn('"tracker.uiState"', html)

    def test_agrpopen_migration_present(self):
        js = _read_app_js()
        self.assertIn("localStorage.getItem(\"agrpOpen\")", js)
        self.assertIn("uiState.get('groupsOpen',null)===null", js)
        self.assertIn("uiState.set('groupsOpen'", js)

    def test_classic_liveonly_routed_through_store(self):
        js = _read_app_js()
        self.assertIn("uiState.get('liveOnly',false)", js)
        self.assertIn("uiState.set('liveOnly',!liveOnly)", js)

    def test_classic_query_routed_through_store(self):
        js = _read_app_js()
        self.assertIn("uiState.set('query',q)", js)
        self.assertIn("uiState.set('query','')", js)
        self.assertIn("uiState.get('query','')", js)

    def test_sid_mirrored_without_removing_legacy_key(self):
        js = _read_app_js()
        # legacy behaviour untouched: cur is still read from / written to localStorage["sid"]
        self.assertIn('localStorage.getItem("sid")', js)
        self.assertIn('localStorage.setItem("sid",cur)', js)
        # ... and mirrored into the shared store alongside it
        self.assertIn("uiState.set('sid',cur)", js)

    def test_classic_subscribes_to_store(self):
        js = _read_app_js()
        self.assertIn("uiState.subscribe(function(key,value)", js)


# ============================================================================
# 2. Behavioural: run the real app.js in node, poke window.uiState for real.
# ============================================================================

_PREAMBLE = r"""
globalThis.window = globalThis;

function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {},
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; },
    querySelectorAll: () => [self],
    closest: function() { return self; },
    firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", value: "", hidden: false,
    focus() {}, click() {}, scrollIntoView() {}
  };
  return self;
}

var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(),
  createTextNode: () => makeEl(),
  getElementById: () => stubEl,
  querySelector: () => stubEl,
  querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl,
  readyState: "complete"
};

// Real, JSON-backed localStorage -- seeded from PRESEED below -- so the migration/persistence
// behaviour under test is the actual mechanism, not a mock of it.
var _ls = Object.assign({}, PRESEED);
window.localStorage = {
  getItem: (k) => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; }
};

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0;
window.setTimeout = () => 0;
window.clearInterval = () => {};
window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {};
window.removeEventListener = () => {};
window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});

try {
"""

_EPILOGUE = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}

var results = {};
results.hasApi = typeof window.uiState.get === "function"
  && typeof window.uiState.set === "function"
  && typeof window.uiState.subscribe === "function";

results.fallback = window.uiState.get("nope", "fallback-value") === "fallback-value";

// Use a synthetic key nothing else in app.js reads or writes, so real subscribers' own side
// effects (e.g. the classic renderer persisting scroll position as a reaction to OTHER keys
// changing) can't add noise to this count.
var calls = 0;
var unsub = window.uiState.subscribe(function(k, v) { if (k === "__test_key__") calls++; });
window.uiState.set("__test_key__", 1);
results.notifiesOnChange = calls === 1;
results.getReturnsSetValue = window.uiState.get("__test_key__", 0) === 1;

window.uiState.set("__test_key__", 1);   // same value again -- must NOT notify (no render storm)
results.noopOnUnchanged = calls === 1;

unsub();
window.uiState.set("__test_key__", 2);
results.unsubscribeWorks = calls === 1;

var persisted = JSON.parse(window.localStorage.getItem("tracker.uiState"));
results.persistsUnderSingleKey = persisted && persisted.__test_key__ === 2;

results.groupsOpenMigrated = Array.isArray(persisted.groupsOpen)
  && persisted.groupsOpen.indexOf("sess:legacy1") !== -1
  && persisted.groupsOpen.indexOf("g:legacy2") !== -1;

// DEFECT 6a: a caller that mutates an already-stored object IN PLACE and re-calls set() with that
// SAME reference must not have the write silently dropped -- comparing the new value against
// _uiState[key] directly can never see a difference when both sides are literally one object.
var obj = { a: 1 };
window.uiState.set("__obj_key__", obj);
obj.a = 2;
window.uiState.set("__obj_key__", obj);
results.sameRefMutationInMemory = window.uiState.get("__obj_key__", null).a === 2;
var persistedObj = JSON.parse(window.localStorage.getItem("tracker.uiState")).__obj_key__;
results.sameRefMutationPersisted = !!persistedObj && persistedObj.a === 2;

// DEFECT 6b: JSON can't represent `undefined`/NaN -- set() must normalise both to `null` up front
// so the in-memory value and a reload agree from the start, instead of memory holding `undefined`/
// NaN until reload silently turns it into `null`.
window.uiState.set("__undef_key__", undefined);
results.undefinedNormalizedInMemory = window.uiState.get("__undef_key__", "FB") === null;
var persistedAfterUndef = JSON.parse(window.localStorage.getItem("tracker.uiState"));
results.undefinedNormalizedPersisted = ("__undef_key__" in persistedAfterUndef) && persistedAfterUndef.__undef_key__ === null;

window.uiState.set("__nan_key__", NaN);
results.nanNormalizedInMemory = window.uiState.get("__nan_key__", "FB") === null;

console.log("RESULTS:" + JSON.stringify(results));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestUiStateBehaviour(unittest.TestCase):
    def _run(self, preseed):
        js = _read_app_js()
        full = _PREAMBLE.replace("PRESEED", json.dumps(preseed)) + js + _EPILOGUE
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "harness.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(full)
            proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        m = re.search(r"RESULTS:(\{.*\})", proc.stdout)
        self.assertIsNotNone(
            m,
            f"harness did not report results\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return json.loads(m.group(1))

    def test_store_api_and_persistence(self):
        results = self._run(preseed={})
        self.assertTrue(results["hasApi"], results)
        self.assertTrue(results["fallback"], results)
        self.assertTrue(results["notifiesOnChange"], results)
        self.assertTrue(results["getReturnsSetValue"], results)
        self.assertTrue(results["noopOnUnchanged"], "set() must no-op when the value is unchanged")
        self.assertTrue(results["unsubscribeWorks"], "subscribe()'s returned fn must unsubscribe")
        self.assertTrue(results["persistsUnderSingleKey"], results)

    def test_agrpopen_migrates_into_groupsopen_once(self):
        # Simulate a real returning user: the OLD per-view key already has expanded groups from
        # before this store existed, and the new key has never been written.
        legacy = json.dumps(["sess:legacy1", "g:legacy2"])
        results = self._run(preseed={"agrpOpen": legacy})
        self.assertTrue(
            results["groupsOpenMigrated"],
            f"legacy agrpOpen value was not migrated into uiState's groupsOpen: {results}",
        )

    def test_set_persists_same_reference_mutation(self):
        # DEFECT 6a. Revert the fix (compare `value` against `_uiState[key]` again) and this goes
        # RED: obj.a stays 1 both in memory and in the persisted blob, because the pre-mutation
        # write and the post-mutation write compare a reference against itself.
        results = self._run(preseed={})
        self.assertTrue(results["sameRefMutationInMemory"], results)
        self.assertTrue(results["sameRefMutationPersisted"], results)

    def test_set_normalizes_undefined_and_nan(self):
        # DEFECT 6b. Revert the fix and `undefinedNormalizedInMemory` goes RED first: the in-memory
        # get() returns the fallback ('FB') because the stored value is the literal `undefined`,
        # not `null`, so a reload (which can only ever produce `null`) would disagree with the
        # live tab until then.
        results = self._run(preseed={})
        self.assertTrue(results["undefinedNormalizedInMemory"], results)
        self.assertTrue(results["undefinedNormalizedPersisted"], results)
        self.assertTrue(results["nanNormalizedInMemory"], results)


# ============================================================================
# 3. Behavioural: classic-dashboard DOM interactions (scroll, search, selection,
#    group toggling) driven for real against a per-id element registry -- the shared
#    single-stub-element harness above can't tell $("slist") apart from $("q")/$("sid"),
#    which several of these regressions specifically hinge on.
# ============================================================================

_CLASSIC_PREAMBLE = r"""
globalThis.window = globalThis;

var _elsById = {};
function makeEl(id) {
  var self = {
    id: id,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {},
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; },
    querySelectorAll: () => [self],
    closest: function() { return self; },
    firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", value: "", hidden: false, scrollTop: 0,
    focus() {}, click() {}, scrollIntoView() {}
  };
  return self;
}

window.document = {
  createElement: () => makeEl(""),
  createTextNode: () => makeEl(""),
  getElementById: (id) => { if (!_elsById[id]) _elsById[id] = makeEl(id); return _elsById[id]; },
  querySelector: () => makeEl("__qs__"),
  querySelectorAll: () => [makeEl("__qsa__")],
  addEventListener() {}, dispatchEvent() {},
  documentElement: makeEl("__doc__"), body: makeEl("__body__"), head: makeEl("__head__"),
  readyState: "complete"
};

var _ls = Object.assign({}, PRESEED);
window.localStorage = {
  getItem: (k) => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: (k) => { delete _ls[k]; }
};

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
// start() (called unconditionally at the bottom of app.js) fires loadSide()/poll() in the
// background via setInterval-less fire-and-forget calls; their completion order relative to our
// own await points below is otherwise a real race (both are separate promise chains resolving
// concurrently), and loadSide() reassigning `sessions` or re-rendering mid-test would make this
// harness flaky. Only '/api/search' (what our test actually drives, via doSearch()) resolves;
// everything else returns a promise that never settles, so start()'s background chain begins but
// can never reach `sessions=await res.json()` or its own renderSide() call during our test window.
// A never-settling promise doesn't keep the process alive (no timer/IO backs it), so this doesn't
// hang node -- it just leaves that chain permanently parked once our own test IIFE finishes.
window.fetch = function (url) {
  url = String(url);
  if (url.indexOf("/api/search") !== -1) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve([
      { id: "s1", title: "Hit One", project: "proj", matches: 1, mtime: Date.now() / 1000, snippet: "hit" }
    ]) });
  }
  return new Promise(() => {});
};
window.setInterval = () => 0;
window.setTimeout = () => 0;
window.clearInterval = () => {};
window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {};
window.removeEventListener = () => {};
window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});

try {
"""

# Inserted BEFORE the outer try's closing brace (see _run() below) -- i.e. still lexically INSIDE
# the same block as app.js's own declarations. doSearch() is an `async function`, and Annex B's
# sloppy-mode function-in-block hoisting (which is what lets a plain `function` declared in a block
# get called from outside it) explicitly does NOT apply to async functions -- calling doSearch()
# from a separate top-level block placed AFTER app.js's closing brace throws "doSearch is not
# defined". Staying inside the same block sidesteps that entirely: this is normal lexical closure
# access, not hoisting, so it doesn't matter whether app.js's declarations are sync or async.
_CLASSIC_INNER = r"""
(async function () {
try {
  var results = {};
  var slist = document.getElementById("slist");
  // Instrument innerHTML as an accessor so we can COUNT writes -- renderSide() writes it exactly
  // once per real render, which is what DEFECT 7's "double render" claim hinges on.
  var _slistWrites = 0, _slistHtml = "";
  Object.defineProperty(slist, "innerHTML", {
    get: function () { return _slistHtml; },
    set: function (v) { _slistHtml = v; _slistWrites++; }
  });

  // ---- DEFECT 7a: renderSide()'s own prune -> _persistGroups() re-entry must not double-render.
  // (PRESEED below seeds groupsOpen with a group that matches no live session, so the very first
  // renderSide() call prunes it and calls _persistGroups() from mid-render.)
  _slistWrites = 0;
  renderSide();
  results.renderSidePruneRendersOnce = _slistWrites === 1;

  // ---- DEFECT 7b: toggleGroup()'s own trailing renderSide() call must not double-render on top
  // of the one the 'groupsOpen' subscriber already triggers.
  _slistWrites = 0;
  toggleGroup(encodeURIComponent("some-group"));
  results.toggleGroupRendersOnce = _slistWrites === 1;

  // ---- DEFECT 1: a mounted #slist's scrollTop of 0 is a real value, not "nothing scrolled yet".
  slist.scrollTop = 400;
  renderSide();
  var afterScroll = JSON.parse(window.localStorage.getItem("tracker.uiState"));
  results.scrollPersistsNonzero = !!(afterScroll && afterScroll.scroll && afterScroll.scroll.slist === 400);

  slist.scrollTop = 0;   // user scrolls back to the top
  renderSide();
  var afterTop = JSON.parse(window.localStorage.getItem("tracker.uiState"));
  results.scrollTopStaysZero = slist.scrollTop === 0;   // must NOT get yanked back to 400
  results.scrollPersistsZero = !!(afterTop && afterTop.scroll && afterTop.scroll.slist === 0);

  // Cross-tab hijack: a remote tab's stale scroll value must not win over THIS tab's mounted,
  // actively-at-the-top list.
  window.uiState.set("scroll", { slist: 999 });
  slist.scrollTop = 0;
  renderSide();
  results.localScrollWinsOverRemote = slist.scrollTop === 0;

  // ---- DEFECT 3: a remote 'query' change must leave what's ON SCREEN consistent with the box.
  var searchFetches = 0;
  var origFetch = window.fetch;
  window.fetch = function (url) { if (String(url).indexOf("/api/search") !== -1) searchFetches++; return origFetch.apply(this, arguments); };

  document.getElementById("q").value = "first query";
  await doSearch();
  results.searchPopulatesResults = _slistHtml.indexOf("Hit One") !== -1;

  window.uiState.set("query", "");   // simulate another tab clearing the search
  results.queryClearSyncsInput = document.getElementById("q").value === "";
  results.queryClearClearsStaleResults = _slistHtml.indexOf("Hit One") === -1;

  document.getElementById("q").value = "first query";
  await doSearch();   // back into search mode with a hit on screen again
  window.uiState.set("query", "second query");   // remote change to a DIFFERENT non-empty query
  results.queryChangeSyncsInput = document.getElementById("q").value === "second query";
  results.queryChangeClearsStaleResults = _slistHtml.indexOf("Hit One") === -1;
  results.queryChangeNoAutoRefetch = searchFetches === 2;   // only the two explicit doSearch() calls above -- the
                                                             // uiState.set('query',...) calls in between must add none

  // ---- DEFECT 4: 'sid' must be handled by the subscriber, not write-only.
  var setIntervalCalls = 0;
  var origSetInterval = window.setInterval;
  window.setInterval = function () { setIntervalCalls++; return origSetInterval.apply(this, arguments); };

  document.getElementById("sid").value = "session-A";
  track();   // a normal LOCAL selection -- track()'s own uiState.set('sid',cur) call notifies
             // this exact subscriber; the re-entrancy guard must stop it from calling track() again
  results.localTrackCausesSingleSetInterval = setIntervalCalls === 1;

  window.uiState.set("sid", "session-B");   // simulate a REMOTE selection arriving from another tab
  results.remoteSidUpdatesInput = document.getElementById("sid").value === "session-B";
  results.remoteSidSyncsLegacyKey = window.localStorage.getItem("sid") === "session-B";

  console.log("RESULTS:" + JSON.stringify(results));
} catch (e) {
  console.error("CLASSIC-TEST-THREW: " + (e && e.stack || e));
  process.exit(1);
}
})();
"""

# Closes the OUTER try opened at the end of _CLASSIC_PREAMBLE -- catches a SYNCHRONOUS throw from
# app.js's own top-level code (mirrors the generic harness above). _CLASSIC_INNER's async IIFE has
# its own internal try/catch for everything that happens after its first `await`, since a rejection
# surfacing in a later microtask can't be caught by a try block that already finished executing.
_CLASSIC_TAIL = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestClassicDashboardBehaviour(unittest.TestCase):
    def _run(self, preseed):
        js = _read_app_js()
        full = _CLASSIC_PREAMBLE.replace("PRESEED", json.dumps(preseed)) + js + _CLASSIC_INNER + _CLASSIC_TAIL
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "harness.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(full)
            proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        m = re.search(r"RESULTS:(\{.*\})", proc.stdout)
        self.assertIsNotNone(
            m,
            f"harness did not report results\nstdout={proc.stdout}\nstderr={proc.stderr}",
        )
        return json.loads(m.group(1))

    def setUp(self):
        # groupsOpen seeded with a group that matches no live session (sessions=[] at boot), so
        # the very first renderSide() call exercises its own prune -> _persistGroups() re-entry.
        self.results = self._run(preseed={"tracker.uiState": json.dumps({"groupsOpen": ["g:stale-group"]})})

    def test_defect1_scroll_zero_is_a_real_value(self):
        r = self.results
        self.assertTrue(r["scrollPersistsNonzero"], r)
        self.assertTrue(r["scrollPersistsZero"], "a scroll-to-top (scrollTop===0) must persist as 0, not be dropped as falsy")
        self.assertTrue(r["scrollTopStaysZero"], "the mounted list must not get yanked back to a stale non-zero scroll position")
        self.assertTrue(r["localScrollWinsOverRemote"], "a mounted tab's own scroll position must win over a remote tab's stale value")

    def test_defect3_query_stays_consistent_with_results(self):
        r = self.results
        self.assertTrue(r["searchPopulatesResults"], r)
        self.assertTrue(r["queryClearSyncsInput"], r)
        self.assertTrue(r["queryClearClearsStaleResults"], "clearing the query remotely must clear the stale match list, not just the input box")
        self.assertTrue(r["queryChangeSyncsInput"], r)
        self.assertTrue(r["queryChangeClearsStaleResults"], "a remote query change must not leave the OLD query's hits on screen under the NEW query text")
        self.assertTrue(r["queryChangeNoAutoRefetch"], "the query subscriber must not trigger its own network search (feedback-loop risk)")

    def test_defect4_sid_subscriber_updates_view_and_legacy_key(self):
        r = self.results
        self.assertTrue(r["localTrackCausesSingleSetInterval"], "a normal local selection must not be echoed back through the 'sid' subscriber into a second track() call")
        self.assertTrue(r["remoteSidUpdatesInput"], "a remote 'sid' change must update the selection, not be write-only")
        self.assertTrue(r["remoteSidSyncsLegacyKey"], "the legacy localStorage['sid'] key (read directly by ext_cr_board.js) must stay in sync")

    def test_defect7_no_double_render(self):
        r = self.results
        self.assertTrue(r["renderSidePruneRendersOnce"], "renderSide()'s own prune-triggered _persistGroups() must not cause a nested re-render")
        self.assertTrue(r["toggleGroupRendersOnce"], "toggleGroup() must not render on top of the render its own uiState notify already triggers")


# ============================================================================
# 4. DEFECT 5: the very first localStorage read (module top, before the store exists) must be
#    guarded -- the whole served page is ONE <script> tag, so an unguarded throw there kills every
#    ext_cr_*.js that follows it.
# ============================================================================

_BLOCKED_STORAGE_PREAMBLE = r"""
globalThis.window = globalThis;
function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {},
    setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", value: "", hidden: false,
    focus() {}, click() {}, scrollIntoView() {}
  };
  return self;
}
var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {}, documentElement: stubEl, body: stubEl, head: stubEl,
  readyState: "complete"
};
// Every call throws -- private browsing / blocked site data (the reviewer's reproduction used a
// SecurityError from getItem specifically, at line 1, before the store's own try/catch exists).
window.localStorage = {
  getItem: () => { throw new Error("SecurityError: blocked"); },
  setItem: () => { throw new Error("SecurityError: blocked"); },
  removeItem: () => { throw new Error("SecurityError: blocked"); }
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
"""

# NOT wrapped in its own try/catch -- that's exactly the point. app.js's line 1 runs completely
# unguarded here; if IT throws, this marker never executes, proving the single-<script>-tag hazard
# for real instead of asserting it by reading the source.
_BLOCKED_STORAGE_EPILOGUE = r"""
var _survivedToHere = true;
var results = {};
results.survivedThrowingStorage = _survivedToHere === true
  && typeof window.uiState === "object"
  && typeof window.uiState.get === "function"
  && typeof window.uiState.set === "function";
console.log("RESULTS:" + JSON.stringify(results));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestSurvivesBlockedStorage(unittest.TestCase):
    def test_defect5_first_read_is_guarded(self):
        # DEFECT 5. Revert the guard on line 1 (back to
        # `let cur=localStorage.getItem("sid")||"", timer=null;`) and this goes RED: node's stdout
        # carries an uncaught "SecurityError: blocked" instead of a RESULTS line, because that read
        # runs before app.js's own try/catch (around the store, further down) even exists.
        js = _read_app_js()
        full = _BLOCKED_STORAGE_PREAMBLE + js + _BLOCKED_STORAGE_EPILOGUE
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "harness.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(full)
            proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        m = re.search(r"RESULTS:(\{.*\})", proc.stdout)
        self.assertIsNotNone(
            m,
            f"app.js did not survive a throwing localStorage -- likely the unguarded line-1 read\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}",
        )
        results = json.loads(m.group(1))
        self.assertTrue(results["survivedThrowingStorage"], results)


if __name__ == "__main__":
    unittest.main()
