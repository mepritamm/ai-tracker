"""Pins the three Control Room TIMELINE-panel defects fixed in ext_cr_detail.js:

  1) newest-first ordering (mergeTimeline used to sort ascending/oldest-first;
     the rest of the app — the server's own narrative[::-1], classic's curNarr/
     narrState prepend-on-arrival, navFirst's own "index 0 = newest" comment —
     is newest-first).
  2) the four legend words (prompts/narration/tools/results) are now real,
     individually-selectable, additive filter chips on top of the existing
     all/talk-only preset, instead of static text.
  3) clicking a timeline entry (or the panel's pop-out button) opens it in the
     SAME classic openText()/_setNav() modal the narration pop-out already uses
     — not a second, Control-Room-native dialog.

Idiom copied from tests/test_cr_logic.py / tests/test_page_bundle.py: build the
REAL assembled page (aitracker.page.build_page()), extract the inlined <script>
bundle, execute it in Node under a minimal stub DOM, then reach into
window.CR.detail._internal for the exported pure derivations. Self-contained
(does not import tests/test_cr_logic.py, which another session may be editing
concurrently) — the small amount of harness code is duplicated here on purpose.
Skips cleanly (not a failure) when node is unavailable, same as its siblings.
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
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
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


# ---------------------------------------------------------------------------
# Stub DOM. Unlike test_cr_logic.py's single shared stub element (fine for pure
# derivations), this one hands out a DISTINCT element per id, keyed by id, so a
# test can tell "was #msgtitle written?" apart from "was #msgnav written?" — the
# only way to prove, by execution, that the pop-out reuses the classic modal's
# real element ids rather than some parallel dialog.
# ---------------------------------------------------------------------------
_JS_PREAMBLE = r"""
globalThis.window = globalThis;
var _elMap = {};
function makeEl(id) {
  var self = {
    id: id || null,
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
var stubEl = makeEl(null);
window.document = {
  createElement: () => makeEl(null), createTextNode: () => makeEl(null),
  getElementById: function (id) { if (!_elMap[id]) _elMap[id] = makeEl(id); return _elMap[id]; },
  querySelector: () => stubEl, querySelectorAll: () => [stubEl],
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


def iso_ms(ms):
    dt = datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def make_detail(**overrides):
    d = {
        "meta": {"cwd": "/tmp/proj", "gitBranch": "main", "sessionId": "sid",
                  "model": "", "effort": "", "title": "t"},
        "todos": [], "files": [], "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": [], "agents": [], "agents_bg": [], "shells": [],
        "decisions": [], "waiting": False, "prs": [], "narrative": [],
        "tokens": {"in": 0, "out": 0}, "context": {"current": 0, "limit": 0, "pct": 0},
        "counts": {}, "mtime": 0, "now": 0, "notes": [], "push_when": "turn",
        "overview": {"where": "", "goal": "", "now": "", "now_kind": "", "sofar": "", "commits": []},
        "continued_as": "", "continued_from": "",
    }
    d.update(overrides)
    return d


# A mixed fixture exercising every kind mergeTimeline emits: prompt, narration,
# ask, command (ok), command-fail, tool (a touched file). Timestamps are spaced
# 10s apart and deliberately NOT inserted in time order, so a passing "descending
# by t" assertion actually proves the sort, not fixture-order luck.
BASE = 1_700_000_000_000  # fixed epoch ms


def _mixed_detail():
    return make_detail(
        requests=[{"t": iso_ms(BASE + 10_000), "text": "do the thing"}],
        narrative=[{"t": iso_ms(BASE + 30_000), "text": "working on it"}],
        decisions=[{"t": iso_ms(BASE + 50_000), "open": True,
                    "questions": [{"q": "which way?", "options": ["a", "b"]}]}],
        commands=[
            {"id": "c1", "t": iso_ms(BASE + 20_000), "cmd": "ls", "ok": True, "kind": "shell"},
            {"id": "c2", "t": iso_ms(BASE + 60_000), "cmd": "pytest", "ok": False, "kind": "shell"},
        ],
        files=[{"path": "a.py", "ops": 2, "last": iso_ms(BASE + 40_000), "created": False}],
    )


# A provider-parity fixture: Auggie/augment-* carry no commands/tools data at
# all — mergeTimeline must never fabricate a "tool"/"command" entry for one.
def _talk_only_provider_detail():
    return make_detail(
        requests=[{"t": iso_ms(BASE + 10_000), "text": "hi"}],
        narrative=[{"t": iso_ms(BASE + 20_000), "text": "hello back"}],
    )


def _driver_js():
    detail = _mixed_detail()
    provider_detail = _talk_only_provider_detail()
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)

    js_body = r"""
var detail = %s;
var providerDetail = %s;
var OUT = {};

// -- defect 1: newest-first -------------------------------------------------
OUT.merged = window.CR.detail._internal.mergeTimeline(detail).map(function(e){ return {kind:e.kind, t:e.t}; });

// -- defect 2: kind mapping + talk-only unchanged ---------------------------
function visibleKinds(ui) {
  return window.CR.detail._internal.mergeTimeline(detail)
    .filter(function (e) { return window.CR.detail._internal.timelineEntryVisible(e, ui); })
    .map(function (e) { return e.kind; });
}
OUT.allDefault = visibleKinds({ timelineFilter: "all", timelineKindsOn: {} });
OUT.talkOnly = visibleKinds({ timelineFilter: "talk", timelineKindsOn: {} });
OUT.chipPrompts = visibleKinds({ timelineFilter: "all", timelineKindsOn: { prompts: true } });
OUT.chipNarration = visibleKinds({ timelineFilter: "all", timelineKindsOn: { narration: true } });
OUT.chipTools = visibleKinds({ timelineFilter: "all", timelineKindsOn: { tools: true } });
OUT.chipResults = visibleKinds({ timelineFilter: "all", timelineKindsOn: { results: true } });
OUT.chipUnion = visibleKinds({ timelineFilter: "all", timelineKindsOn: { prompts: true, tools: true } });
OUT.kindMap = window.CR.detail._internal.TIMELINE_KIND_MAP;

// Provider parity: Auggie/augment-* never emit a command/tool entry, so the
// "results"/"tools" chips must yield an EMPTY list, never throw.
OUT.providerResults = visibleKinds.call(null, { timelineFilter: "all", timelineKindsOn: { results: true } });
OUT.providerAll = (function () {
  return window.CR.detail._internal.mergeTimeline(providerDetail)
    .filter(function (e) { return window.CR.detail._internal.timelineEntryVisible(e, { timelineFilter: "all", timelineKindsOn: { results: true } }); })
    .map(function (e) { return e.kind; });
})();

// -- defect 3: pop-out reuses openText()/_setNav(), not a parallel modal ----
// Every element id involved (#msgtitle/#msgwhen/#msgbody/#msgmodal/#msgnav) is
// the SAME id the classic narration pop-out (openMsg -> openText) already
// uses (app.js:1610-1618) — if a second, CR-native modal existed instead, none
// of these ids would ever be touched.
var filteredAll = window.CR.detail._internal.mergeTimeline(detail)
  .filter(function (e) { return window.CR.detail._internal.timelineEntryVisible(e, { timelineFilter: "all", timelineKindsOn: {} }); });
var ui = { timelineEntries: filteredAll };
OUT.popoutListLen = filteredAll.length;
OUT.popoutNewestKind = filteredAll[0].kind;
window.CR.detail._internal.openTimelineEntry(ui, 0);
OUT.msgTitleText = _elMap["msgtitle"] && _elMap["msgtitle"].textContent;
OUT.msgModalDisplay = _elMap["msgmodal"] && _elMap["msgmodal"].style.display;
OUT.msgBodyHtml = _elMap["msgbody"] && _elMap["msgbody"].innerHTML;
OUT.msgNavText = _elMap["msgnav"] && _elMap["msgnav"].textContent; // "<i+1> / <n>" from _setNav

// timelineEntryModalPayload: pure — the right entry's data reaches the modal.
OUT.payloadCommandFail = window.CR.detail._internal.timelineEntryModalPayload(
  filteredAll.filter(function (e) { return e.kind === "command-fail"; })[0]
);
OUT.payloadPrompt = window.CR.detail._internal.timelineEntryModalPayload(
  filteredAll.filter(function (e) { return e.kind === "prompt"; })[0]
);

console.log("===CR_TIMELINE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (json.dumps(detail), json.dumps(provider_detail))

    return "\n".join([_JS_PREAMBLE, bundle_js, _JS_MID, js_body])


def _extract_json(stdout):
    marker = "===CR_TIMELINE_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


# ---------------------------------------------------------------------------
# Regression: ext_cr_boot.js's CLASSIC_SIBLINGS must NOT include the two
# shared overlays (#msgmodal, #diffmodal) — they're made visible only by their
# own openers setting an inline `style.display`, and the stylesheet's
# `[hidden] { display: none !important }` rule beats that inline display if
# `setUiMode()` ever sets `hidden` on them. This needs its OWN small stub DOM
# (self-contained on purpose, like the rest of this file): unlike _JS_PREAMBLE
# above (a single shared stubEl from querySelector, setTimeout a no-op so
# init() never fires), this one hands back REAL, DISTINCT elements for the
# five CLASSIC_SIBLINGS selectors and runs setTimeout's callback immediately
# so ext_cr_boot.js's deferred `setTimeout(init, 0)` actually executes
# setUiMode('next') for real, the same way test_cr_logic.py's theme-scope
# driver does for its own scenario.
# ---------------------------------------------------------------------------
_UI_MODE_JS_PREAMBLE = r"""
globalThis.window = globalThis;
var _elMap = {};
function makeEl(id, tag, cls) {
  var self = {
    id: id || null, tag: tag || null, cls: cls || null,
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; },
    removeAttribute() {},
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus() {}, click() {}
  };
  return self;
}
var stubEl = makeEl(null);

// Real stand-ins for the classic chrome + the two shared overlays.
var appEl = makeEl(null, 'div', 'app');
var footerEl = makeEl(null, 'footer', 'foot');
var toastsEl = makeEl('toasts');
var diffmodalEl = makeEl('diffmodal');
var msgmodalEl = makeEl('msgmodal');
_elMap['toasts'] = toastsEl;
_elMap['diffmodal'] = diffmodalEl;
_elMap['msgmodal'] = msgmodalEl;

function matchesSelector(el, sel) {
  if (!el) return false;
  if (sel.charAt(0) === '#') return el.id === sel.slice(1);
  if (sel.indexOf('.') >= 0) {
    var parts = sel.split('.');
    var tag = parts[0]; // may be ''
    var cls = parts[1];
    if (tag && el.tag !== tag) return false;
    if (el.cls !== cls) return false;
    return true;
  }
  return false;
}

window.document = {
  createElement: () => makeEl(null), createTextNode: () => makeEl(null),
  getElementById: function (id) { if (!_elMap[id]) _elMap[id] = makeEl(id); return _elMap[id]; },
  querySelector: function (sel) {
    var candidates = [appEl, footerEl, toastsEl, diffmodalEl, msgmodalEl];
    for (var i = 0; i < candidates.length; i++) {
      if (matchesSelector(candidates[i], sel)) return candidates[i];
    }
    return stubEl;
  },
  querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};

const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};
// Seeded BEFORE the bundle runs: a returning user already in 'next' mode, so
// init()'s deferred call to setUiMode('next') actually fires for real.
window.localStorage.setItem('tracker.ui', 'next');

window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0;
// Runs its callback IMMEDIATELY (same trick as test_cr_logic.py's theme-scope
// driver) so the one `setTimeout(init, 0)` at the end of ext_cr_boot.js's IIFE
// actually executes here, instead of being silently swallowed like _JS_PREAMBLE above.
window.setTimeout = function (fn) { if (typeof fn === 'function') fn(); return 0; };
window.clearInterval = () => {}; window.clearTimeout = () => {};
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

_UI_MODE_JS_TAIL = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
var OUT = {
  msgmodalHidden: msgmodalEl.hidden,
  diffmodalHidden: diffmodalEl.hidden,
  appHidden: appEl.hidden,
  footerHidden: footerEl.hidden,
  toastsHidden: toastsEl.hidden
};
console.log("===CR_UI_MODE_JSON_START===");
console.log(JSON.stringify(OUT));
"""


def _ui_mode_driver_js():
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)
    return "\n".join([_UI_MODE_JS_PREAMBLE, bundle_js, _UI_MODE_JS_TAIL])


def _extract_ui_mode_json(stdout):
    marker = "===CR_UI_MODE_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestCRTimeline(unittest.TestCase):
    """Pins the timeline-panel fixes: newest-first order, the four filter chips,
    and the pop-out reusing the classic openText()/_setNav() modal."""

    @classmethod
    def setUpClass(cls):
        js = _driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Driver script failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    # -- defect 1: newest-first --------------------------------------------

    def test_merge_timeline_is_newest_first(self):
        merged = self.OUT["merged"]
        times = [e["t"] for e in merged]
        self.assertEqual(times, sorted(times, reverse=True), "mergeTimeline must sort descending (newest-first)")
        self.assertGreater(times[0], times[-1])
        # The newest fixture entry (t = BASE+60_000, a failing command) must be first.
        self.assertEqual(merged[0]["kind"], "command-fail")
        self.assertEqual(merged[-1]["kind"], "prompt")

    # -- defect 2: the four chips + talk-only unchanged ----------------------

    def test_default_all_shows_every_kind_including_ask(self):
        self.assertEqual(
            sorted(self.OUT["allDefault"]),
            sorted(["prompt", "narration", "ask", "command", "command-fail", "tool"]),
        )

    def test_talk_only_is_unchanged_prompt_and_narration_only(self):
        self.assertEqual(sorted(self.OUT["talkOnly"]), ["narration", "prompt"])
        self.assertNotIn("ask", self.OUT["talkOnly"])

    def test_chip_prompts_yields_only_prompt(self):
        self.assertEqual(self.OUT["chipPrompts"], ["prompt"])

    def test_chip_narration_yields_only_narration(self):
        self.assertEqual(self.OUT["chipNarration"], ["narration"])

    def test_chip_tools_yields_only_tool(self):
        self.assertEqual(self.OUT["chipTools"], ["tool"])

    def test_chip_results_yields_command_and_command_fail_only(self):
        self.assertEqual(sorted(self.OUT["chipResults"]), ["command", "command-fail"])

    def test_chip_selection_is_additive_union(self):
        self.assertEqual(sorted(self.OUT["chipUnion"]), ["prompt", "tool"])

    def test_ask_is_excluded_from_every_kind_chip(self):
        for kinds in self.OUT["kindMap"].values():
            self.assertNotIn("ask", kinds)

    def test_results_chip_never_throws_for_a_commandless_provider(self):
        # Auggie/augment-* sessions carry no commands/tools — the "results" chip
        # must degrade to an empty list, not raise or fabricate an entry.
        self.assertEqual(self.OUT["providerAll"], [])

    # -- defect 3: pop-out reuses the classic modal --------------------------

    def test_popout_opens_the_newest_entry_of_the_filtered_list(self):
        self.assertEqual(self.OUT["popoutNewestKind"], "command-fail")
        self.assertEqual(self.OUT["popoutListLen"], 6)

    def test_popout_calls_the_real_openText_modal_elements(self):
        # These are the CLASSIC modal's own element ids (app.js openText, used by
        # openMsg/openReq/openCmd/...). If a second, CR-native dialog existed
        # instead, none of these would be written.
        self.assertEqual(self.OUT["msgModalDisplay"], "flex")
        self.assertEqual(self.OUT["msgTitleText"], "Command")
        self.assertIn("pytest", self.OUT["msgBodyHtml"])
        self.assertIn("failed", self.OUT["msgBodyHtml"])

    def test_popout_registers_nav_over_the_filtered_list_via_setNav(self):
        # _setNav(open, i, n, opts) writes "<i+1> / <n>" into #msgnav/#diffnav —
        # i=0, n=6 (the full filtered list here) proves _setNav (not a homemade
        # nav mechanism) was called with THIS entry's index and THIS list's length.
        self.assertEqual(self.OUT["msgNavText"], "1 / 6")

    def test_payload_for_command_entry_is_a_markdown_code_fence(self):
        p = self.OUT["payloadCommandFail"]
        self.assertEqual(p["title"], "Command")
        self.assertIn("```", p["text"])
        self.assertIn("pytest", p["text"])
        self.assertIn("failed", p["text"])

    def test_payload_for_prompt_entry_is_the_prompt_text(self):
        p = self.OUT["payloadPrompt"]
        self.assertEqual(p["title"], "Prompt")
        self.assertEqual(p["text"], "do the thing")

    # -- shared-overlay regression: #msgmodal/#diffmodal must survive Control
    # Room mode un-hidden, while the actual classic chrome still gets hidden --

    @unittest.skipUnless(_HAS_NODE, "node not available")
    def test_control_room_leaves_shared_overlays_unhidden_but_hides_classic_chrome(self):
        # #msgmodal/#diffmodal are shared overlays (invisible by default via
        # `.overlay { display: none }`, made visible only by their own openers'
        # inline `style.display`) — not classic-only chrome. ext_cr_boot.js's
        # CLASSIC_SIBLINGS must not force `hidden` onto them: combined with the
        # stylesheet's `[hidden] { display: none !important }` rule, that beats
        # any opener's inline `display:flex` and permanently hides the modal
        # (the bug this test pins). `.app`/`footer.foot`/`#toasts` ARE classic
        # chrome and must still be hidden in Control Room mode.
        returncode, stdout, stderr = _run_node(_ui_mode_driver_js())
        self.assertEqual(
            returncode, 0,
            "Driver script failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (returncode, stdout, stderr),
        )
        out = _extract_ui_mode_json(stdout)
        self.assertFalse(out["msgmodalHidden"], "#msgmodal must NOT be hidden in Control Room mode")
        self.assertFalse(out["diffmodalHidden"], "#diffmodal must NOT be hidden in Control Room mode")
        self.assertTrue(out["appHidden"], ".app must still be hidden in Control Room mode")
        self.assertTrue(out["footerHidden"], "footer.foot must still be hidden in Control Room mode")
        self.assertTrue(out["toastsHidden"], "#toasts must still be hidden in Control Room mode")


if __name__ == "__main__":
    unittest.main()
