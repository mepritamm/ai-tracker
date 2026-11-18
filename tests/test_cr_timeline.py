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


def _decisions_detail():
    qs = [{"q": "pick?", "options": ["a", "b"]}]
    return make_detail(
        requests=[{"t": iso_ms(BASE + 10_000), "text": "go"}],
        decisions=[
            {"t": iso_ms(BASE + 20_000), "open": False, "answer": "a", "questions": qs},
            {"t": iso_ms(BASE + 30_000), "open": True, "answer": "", "questions": qs},
        ],
    )


def _multi_q_detail():
    def q(text, header="", opts=("a",), answer=None):
        d = {"q": text, "header": header, "options": list(opts)}
        if answer is not None:
            d["answer"] = answer
        return d
    return make_detail(decisions=[
        {"t": iso_ms(BASE + 1_000), "open": True, "answer": "",
         "questions": [q("Scope q?", "Scope", ("a", "b")), q("Second q?", "", ("c",)), q("DB q?", "DB", ("pg",))]},
        {"t": iso_ms(BASE + 2_000), "open": False, "answer": '"Q1"="A", "Q2"="B"',
         "questions": [q("Q1", "", ("A", "Z"), "A"), q("Q2", "", ("B",), "B")]},
        {"t": iso_ms(BASE + 3_000), "open": False, "answer": '"Ship?"="Yes"',
         "questions": [q("Ship?", "", ("Yes", "No"), "Yes")]},
        {"t": iso_ms(BASE + 4_000), "open": False, "answer": "ok",
         "questions": [q("Proceed?", "", ("Yes",))]},
        {"t": iso_ms(BASE + 5_000), "open": True, "answer": "",
         "questions": [q("Auggie open?", "", ("x",))]},
    ])


_MULTI_Q_JS = r"""
(function () {
  var I = window.CR.detail._internal, MQ = __MQ__, R = {};
  OUT.mq = R;
  function T(name, fn) { try { R[name] = fn(); } catch (e) { R[name] = { err: String(e && e.stack || e) }; } }
  var entries = I.mergeTimeline(MQ);
  function ask(textStart) {
    return entries.filter(function (e) { return e.kind === "ask" && e.decision.questions[0].q.indexOf(textStart) === 0; })[0];
  }
  var ask3 = ask("Scope q"), closed2 = ask("Q1"), closed1 = ask("Ship"), augC = ask("Proceed"), augO = ask("Auggie");
  function fakeWrap() { return makeEl(); }

  T("pager", function () { return I.entryHtml(ask3, null, null, { qPage: {} }); });
  T("key", function () { return I.qKey(ask3.decision); });
  T("page2", function () {
    var k = I.qKey(ask3.decision), a = { qPage: {} }, b = { qPage: {} };
    a.qPage[k] = 2; b.qPage[k] = 9;
    return { ok: I.entryHtml(ask3, null, null, a), clamp: I.entryHtml(ask3, null, null, b) };
  });
  T("step", function () { return [I.qPageStep(0, -1, 3), I.qPageStep(2, 1, 3), I.qPageStep(0, 1, 3)]; });

  function fakePager(key, n) {
    var tabs = [], prevent = 0;
    for (var i = 0; i < n; i++) tabs.push(makeEl());
    var steps = [makeEl(), makeEl()], panes = [makeEl(), makeEl(), makeEl()], pos = makeEl();
    var pg = makeEl();
    pg.getAttribute = function (a) { return a === "data-qkey" ? key : null; };
    pg.querySelectorAll = function (sel) {
      if (sel.indexOf("tab") >= 0 && sel.indexOf("is-cur") < 0) return tabs;
      if (sel.indexOf("pane") >= 0) return panes;
      if (sel.indexOf("step") >= 0) return steps;
      return [];
    };
    pg.querySelector = function (sel) { return sel.indexOf("is-cur") >= 0 ? tabs[0] : (sel.indexOf("pos") >= 0 ? pos : null); };
    pg.focus = function () { pg._focused = true; };
    pg._tabs = tabs;
    return pg;
  }
  function fakeNode(pg) {
    var n = makeEl();
    n.contains = function (x) { return x === pg || (pg && pg._tabs.indexOf(x) >= 0); };
    n.querySelectorAll = function (sel) { return sel.indexOf("crd-qpager") >= 0 ? [pg] : []; };
    return n;
  }
  function ev(target, over) {
    var e = { key: "ArrowRight", target: target, shiftKey: false, metaKey: false, ctrlKey: false, altKey: false, prevented: 0,
              preventDefault: function () { e.prevented++; } };
    for (var k in (over || {})) e[k] = over[k];
    return e;
  }
  T("keys", function () {
    var K = "kk#3", pg = fakePager(K, 3), node = fakeNode(pg), out = {};
    document.getElementById("msgmodal").style.display = "";   // the pop-out test above left it "flex"
    var inside = makeEl(); inside.closest = function () { return pg; };
    var outside = makeEl(); outside.closest = function () { return null; };
    var ui = { qPage: {} }, e1 = ev(inside);
    out.right = I.qPagerOnKey(e1, ui, node); out.page = ui.qPage[K]; out.prevented = e1.prevented;
    var ui2 = { qPage: {} };
    out.outside = I.qPagerOnKey(ev(outside), ui2, node); out.outsidePage = ui2.qPage[K];
    out.j = I.qPagerOnKey(ev(inside, { key: "j" }), { qPage: {} }, node);
    out.mods = ["shiftKey", "metaKey", "ctrlKey", "altKey"].map(function (m) {
      var o = {}; o[m] = true; return I.qPagerOnKey(ev(inside, o), { qPage: {} }, node); });
    var mm = document.getElementById("msgmodal"); mm.style.display = "flex";
    out.modal = I.qPagerOnKey(ev(inside), { qPage: {} }, node);
    mm.style.display = "";
    return out;
  });
  T("refocus", function () {
    var K = "kk#3", pg = fakePager(K, 3), cont = fakeNode(pg), out = {};
    var tab = makeEl();
    tab.classList = { contains: function (c) { return c === "crd-qpager-tab"; }, add() {}, remove() {}, toggle() {} };
    tab.closest = function () { return pg; };
    cont.contains = function (x) { return x === tab; };
    document.activeElement = tab;
    var f = I.focusedQKey(cont); out.f = f;
    var focusArgs = null, cur = pg._tabs[0];
    cur.focus = function (a) { focusArgs = a || true; };
    var newC = fakeNode(pg);
    I.refocusQ(newC, f); out.focusArgs = focusArgs;
    var gone = makeEl(); gone.querySelectorAll = function () { return []; }; gone.querySelector = function () { return null; };
    focusArgs = null; I.refocusQ(gone, f); out.goneCalls = focusArgs;
    I.refocusQ(newC, null); out.nullNoop = focusArgs;
    document.activeElement = null;
    return out;
  });
  function repaintCase(render, rootKey, probeSel) {
    var openD = MQ.decisions.filter(function (d) { return d.open; })[0];
    var K = I.qKey(openD), out = { key: K };
    var pg = fakePager(K, 3), body = makeEl();
    var tab = makeEl(), calls = [];
    tab.classList = { contains: function (c) { return c === "crd-qpager-tab"; }, add() {}, remove() {}, toggle() {} };
    tab.closest = function () { return pg; };
    pg._tabs[0].focus = function (a) { calls.push(a || true); };
    var root = makeEl();
    root.contains = function (x) { return x === tab; };
    root.querySelector = function (sel) { return sel.indexOf("crd-qpager") >= 0 ? pg : (sel === probeSel ? root : body); };
    root.querySelectorAll = function (sel) { return sel.indexOf("crd-qpager") >= 0 ? [pg] : []; };
    var u = { qPage: {} };
    document.activeElement = null;
    render(root, MQ, u);
    document.activeElement = tab;
    u.qPage[K] = 1;
    render(root, MQ, u);
    document.activeElement = null;
    out.calls = calls;
    return out;
  }
  T("panelRefocus", function () { return repaintCase(I.renderDecisions, "wrap", ""); });
  T("phoneRefocus", function () { return repaintCase(I.renderPhoneAwaiting, "node", ".crd-phone-awaiting"); });
  T("single", function () { return I.entryHtml(augO, null, null, { qPage: {} }); });
  T("closedSingle", function () {
    return { yes: I.entryHtml(closed1, null, null, { qPage: {} }), aug: I.entryHtml(augC, null, null, { qPage: {} }) };
  });
  T("panel", function () { var w = fakeWrap(); I.renderDecisions(w, MQ, { qPage: {} }); return w.innerHTML; });
  T("phone", function () { var n = fakeWrap(); I.renderPhoneAwaiting(n, MQ, { qPage: {} }); return n.innerHTML; });
  T("markers", function () {
    var base = entries[0].t;
    return I.buildMarkers(MQ, base + 10000, base - 10000, base + 10000, false)
      .filter(function (m) { return m.kind === "ask"; }).map(function (m) { return m.title; });
  });
  T("modal", function () {
    return { o3: I.timelineEntryModalPayload(ask3).text, c2: I.timelineEntryModalPayload(closed2).text,
             o1: I.timelineEntryModalPayload(augO).text };
  });
  T("degrade", function () {
    var bare = { kind: "ask", t: 1, key: "k", decision: { t: "x", open: true, questions: [], answer: "" } };
    var w = fakeWrap(); I.renderDecisions(w, make0(), { qPage: {} });
    return { bare: I.entryHtml(bare, null, null, { qPage: {} }), empty: w.innerHTML };
    function make0() { return { decisions: [] }; }
  });
  T("answerHtml", function () { return { a: I.answerHtml(null, "**x**"), b: I.answerHtml(null, "") }; });
  T("answerPaths", function () {
    var k = I.qKey(closed2.decision), pages = [0, 1].map(function (i) {
      var u = { qPage: {} }; u.qPage[k] = i; return I.entryHtml(closed2, null, null, u); });
    return { pages: pages, panel: (function () { var w = fakeWrap(); I.renderDecisions(w, MQ, { qPage: {} }); return w.innerHTML; })() };
  });
})();
"""


def _driver_js():
    detail = _mixed_detail()
    decisions_detail = _decisions_detail()
    provider_detail = _talk_only_provider_detail()
    bundle_html = _read_page()
    bundle_js = _extract_script_content(bundle_html)

    js_body = r"""
var detail = %s;
var providerDetail = %s;
var decisionsDetail = %s;
var OUT = {};

// -- defect 1: newest-first -------------------------------------------------
OUT.merged = window.CR.detail._internal.mergeTimeline(detail).map(function(e){ return {kind:e.kind, t:e.t}; });

// -- defect 2: kind mapping + talk-only = prompts + narration + questions ---------------------------
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
OUT.talkDecisions = window.CR.detail._internal.mergeTimeline(decisionsDetail)
  .filter(function (e) { return window.CR.detail._internal.timelineEntryVisible(e, { timelineFilter: "talk", timelineKindsOn: {} }); })
  .filter(function (e) { return e.kind === "ask"; })
  .map(function (e) { return e.decision.open; });
OUT.talkEmpty = window.CR.detail._internal.timelineEmptyMessage({ timelineFilter: "talk", timelineKindsOn: {} });

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

__MQ_BLOCK__
console.log("===CR_TIMELINE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (json.dumps(detail), json.dumps(provider_detail), json.dumps(decisions_detail))
    js_body = js_body.replace("__MQ_BLOCK__", _MULTI_Q_JS.replace("__MQ__", json.dumps(_multi_q_detail())))

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

    # -- defect 2: the four chips + talk-only = prompts + narration + questions ----------------------

    def test_default_all_shows_every_kind_including_ask(self):
        self.assertEqual(
            sorted(self.OUT["allDefault"]),
            sorted(["prompt", "narration", "ask", "command", "command-fail", "tool"]),
        )

    def test_talk_only_shows_prompts_narration_and_questions(self):
        self.assertEqual(sorted(self.OUT["talkOnly"]), ["ask", "narration", "prompt"])
        for k in ("command", "command-fail", "tool"):
            self.assertNotIn(k, self.OUT["talkOnly"])

    def test_talk_only_shows_open_and_answered_decisions(self):
        self.assertEqual(sorted(self.OUT["talkDecisions"]), [False, True])

    def test_talk_only_empty_message_names_questions(self):
        self.assertIn("questions", self.OUT["talkEmpty"])

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

    # -- multi-question pager + answers (every path renders through the shared helpers) ------------

    def _mq(self, name):
        v = self.OUT["mq"][name]
        if isinstance(v, dict) and "err" in v:
            self.fail("driver step %r threw: %s" % (name, v["err"]))
        return v

    @staticmethod
    def _panes(html):
        return re.findall(r'<div class="crd-qpager-pane"[^>]*>', html)

    def test_card_pager_renders_every_question(self):
        h = self._mq("pager")
        self.assertIn("crd-qpager", h)
        for t in ("Scope q?", "Second q?", "DB q?"):
            self.assertIn(t, h)
        for lab in ("Scope", "Q2", "DB"):
            self.assertIn(lab, h)
        panes = self._panes(h)
        self.assertEqual(len(panes), 3)
        self.assertEqual(len([x for x in panes if " hidden" not in x]), 1)
        prev = re.search(r'<button[^>]*data-dir="-1"[^>]*>', h).group(0)
        self.assertIn('aria-disabled="true"', prev)
        self.assertNotIn(" disabled", prev)
        self.assertRegex(h, r'<div class="crd-qpager"[^>]*tabindex="-1"')

    def test_card_pager_respects_ui_page(self):
        r = self._mq("page2")
        for h in (r["ok"], r["clamp"]):
            vis = [x for x in self._panes(h) if " hidden" not in x]
            self.assertEqual(len(vis), 1)
            self.assertIn('data-i="2"', vis[0])
            self.assertIn("3/3", h)

    def test_qpage_step_clamps(self):
        self.assertEqual(self._mq("step"), [0, 2, 1])

    def test_arrow_keys_page_only_when_focus_in_pager(self):
        k = self._mq("keys")
        self.assertIs(k["right"], True)
        self.assertEqual(k["page"], 1)
        self.assertEqual(k["prevented"], 1)
        self.assertIs(k["outside"], False)
        self.assertIsNone(k.get("outsidePage"))
        self.assertIs(k["j"], False)
        self.assertEqual(k["mods"], [False] * 4)
        self.assertIs(k["modal"], False)

    def test_refocus_restores_pager_focus(self):
        r = self._mq("refocus")
        self.assertEqual(r["f"], {"key": "kk#3", "onTab": True})
        self.assertEqual(r["focusArgs"], {"preventScroll": True})
        self.assertIsNone(r["goneCalls"])
        self.assertIsNone(r["nullNoop"])

    def test_panel_repaint_restores_pager_focus(self):
        r = self._mq("panelRefocus")
        self.assertEqual(r["calls"], [{"preventScroll": True}])

    def test_phone_repaint_restores_pager_focus(self):
        r = self._mq("phoneRefocus")
        self.assertEqual(r["calls"], [{"preventScroll": True}])

    @staticmethod
    def _fn_slice(js, start, end_marker="\n  function "):
        i = js.index(start)
        j = js.find(end_marker, i + len(start))
        return js[i:j if j >= 0 else len(js)]

    def test_repaint_sites_wired_source_pins(self):
        js = open(os.path.join(_ROOT, "aitracker", "web", "ext_cr_detail.js"), encoding="utf-8").read()
        tl = self._fn_slice(js, "function renderTimelineEntries")
        for needle in ("focusedQKey(scrollEl)", "refocusQ(scrollEl, fq)", "openAsks !== ui.timelineOpenAsks"):
            self.assertIn(needle, tl)
        for fn in ("function renderDecisions", "function renderPhoneAwaiting"):
            body = self._fn_slice(js, fn)
            self.assertIn("focusedQKey(", body, fn)
            self.assertIn("refocusQ(", body, fn)
        i = js.index('node.addEventListener("click", function (ev) {')
        h = js[i:i + 1500]
        self.assertIn("pg.focus({ preventScroll: true })", h)
        self.assertLess(h.index("pg.focus({ preventScroll: true })"), h.index('closest("[data-act]")'))

    def test_single_question_ask_renders_unchanged(self):
        h = self._mq("single")
        self.assertNotIn("crd-qpager", h)
        for t in ("crd-ask-q", "crd-ask-pill", "View-only"):
            self.assertIn(t, h)

    def test_closed_single_question_card_shows_answer(self):
        r = self._mq("closedSingle")
        h = r["yes"]
        self.assertIn('class="crd-answer cr-cfg-row-sub"', h)
        self.assertIn("</span> Yes</div>", h)
        self.assertNotIn('"Ship?"=', h)
        self.assertNotIn("answer in the session", h)
        self.assertIn("</span> ok</div>", r["aug"])

    def test_decisions_panel_pages_open_and_closed_multi_q(self):
        h = self._mq("panel")
        self.assertEqual(h.count('class="crd-qpager"') , 2)
        for t in ("Scope q?", "Second q?", "DB q?", "Q1", "Q2"):
            self.assertIn(t, h)
        self.assertIn("crd-decision-opt", h)
        self.assertNotIn('"Q1"="A"', h)
        self.assertNotIn("Decided:", h)

    def test_phone_awaiting_pages_multi_q(self):
        h = self._mq("phone")
        self.assertIn("crd-qpager", h)
        for t in ("Scope q?", "Second q?", "DB q?"):
            self.assertIn(t, h)

    def test_spine_marker_title_counts_more(self):
        titles = self._mq("markers")
        self.assertTrue(any("Scope q? (+2 more)" in t for t in titles), titles)
        self.assertTrue(any("Ship?" in t and "→ Yes" in t for t in titles), titles)

    def test_modal_payload_lists_every_question(self):
        m = self._mq("modal")
        for t in ("1/3", "2/3", "3/3", "Scope q?", "Second q?", "DB q?"):
            self.assertIn(t, m["o3"])
        self.assertIn("→ A", m["c2"])
        self.assertIn("→ B", m["c2"])
        self.assertNotIn("Decided:", m["c2"])
        self.assertEqual(
            m["o1"],
            "**Auggie open?**\n- x\n\n_View-only — answer in the session itself; the tracker never writes to it._")

    def test_auggie_and_empty_degrade(self):
        h = self._mq("single")
        self.assertIn("crd-ask-q", h)
        self.assertNotIn("crd-qpager", h)
        d = self._mq("degrade")
        self.assertNotIn("crd-qpager", d["bare"])
        self.assertIn("No decisions recorded yet", d["empty"])

    def test_answer_html_uses_config_note_class(self):
        a = self._mq("answerHtml")
        self.assertTrue(a["a"].startswith('<div class="crd-answer cr-cfg-row-sub">'))
        self.assertIn("→", a["a"])
        self.assertIn("<strong>x</strong>", a["a"])
        self.assertEqual(a["b"], "")
        web = os.path.join(_ROOT, "aitracker", "web")
        dlg = open(os.path.join(web, "ext_cr_dialogs.css"), encoding="utf-8").read()
        self.assertRegex(dlg, r"\.cr \.cr-cfg-row-sub \{[^}]*11\.5px")
        css = open(os.path.join(web, "ext_cr_detail.css"), encoding="utf-8").read()
        m = re.search(r"\.cr \.cr-cfg-row-sub\.crd-answer \{([^}]*)\}", css)
        self.assertTrue(m, "missing .cr .cr-cfg-row-sub.crd-answer rule")
        self.assertNotIn("font", m.group(1))
        self.assertIn(".cr .crd-answer code", css)
        js = open(os.path.join(web, "ext_cr_detail.js"), encoding="utf-8").read()
        for gone in ("crd-decision-answer", "crd-ask-answer", "crd-qpager-answer"):
            self.assertNotIn(gone, js)

    def test_every_answer_path_uses_answer_html(self):
        r = self._mq("answerPaths")
        for i, want in enumerate(("</span> A</div>", "</span> B</div>")):
            vis = re.split(r'<div class="crd-qpager-pane"', r["pages"][i])[1:]
            vis = [x for x in vis if not x.split(">", 1)[0].count(" hidden")]
            self.assertEqual(len(vis), 1)
            self.assertIn(want, vis[0])
        self.assertEqual(r["panel"].count('class="crd-answer cr-cfg-row-sub"'), 4)

    def test_pager_wired_on_click_key_and_state(self):
        js = open(os.path.join(_ROOT, "aitracker", "web", "ext_cr_detail.js"), encoding="utf-8").read()
        for needle in ('case "qpage-go"', 'case "qpage-step"', "if (qPagerOnKey(ev, ui, node)) return;",
                       "qPage: {}", "ui.qPage = {}", "refocusQ(", "focusedQKey("):
            self.assertIn(needle, js)
        i = js.index('node.addEventListener("click", function (ev) {')
        h = js[i:i + 1500]
        self.assertIn('closest(".crd-qpager-head")', h)
        self.assertLess(h.index('closest(".crd-qpager-head")'), h.index('closest("[data-act]")'))

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
