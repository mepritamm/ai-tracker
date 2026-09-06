"""Regression tests for JOB 3: the always-on "glowing bulb" WORKING indicator
in the Control Room's session DETAIL view (desktop layout).

BACKGROUND: the owner's "for both sessions and the board have the glowing
bulb always on for the working on the live sessions/board tile" ask was
already done for the board tile / rail dot / collapsed orb pip (see
tests/test_working_glow_board.py) and for the detail view's PHONE layout
(`.crd-phone-orb.crd-state-working`, box-shadow + `crd-pulse`, ext_cr_detail.
css). The desktop header's own state pill (`.crd-pill-state.crd-state-
working`) was flat -- no glow, no pulse -- so an open, working session was
identifiable on the board/rail and on phone, but not in its own open detail
view on desktop. This pass adds the glow there.

THE PREDICATE GAP this pass also closes: the detail view's `stateOf()`
(ext_cr_detail.js) used to re-derive its own "is this working" AND/OR
(`live && (running || inProgress)`) instead of calling app.js's global,
canonical `isSessionWorking(s, live)` -- the SAME formula the board tile and
rail dot use (ext_cr_board.js's own `isWorking()` wrapper). Two independently-
maintained copies of one predicate is exactly the kind of drift this
codebase's history warns about (classic's sidebar once disagreed with the
board for precisely this reason). `detailIsWorking(session, live)`
(ext_cr_detail.js) adapts the detail dict's own fields into a `{ended, bg}`-
shaped object and hands it to the REAL global `isSessionWorking()` -- the
formula itself is never re-derived here. `stateOf()` calls this adapter
instead of its own copy of the AND/OR.

CORRECTION (adversarial-review fix, formerly a false claim in this exact
docstring and in ext_cr_detail.js's own comment): this used to say the detail
dict carries "no `ended` boolean", so the adapter had to GUESS one from
`!inProgress` (todos). That is false -- the SAME transcript-tail fact the list
dict's `ended` is built from is threaded onto `session.meta.ended` (Auggie's
providers/auggie.py, fixed here to match Claude's), and this renderer already
reads sibling `session.meta.*` fields elsewhere. The todo-derived guess
disagreed with the real value in BOTH directions: a live session with no
todos at all (Claude prunes ~/.claude/tasks/* and most sessions never call
TodoWrite) read as landed while the board said working (glow missing); a
session that genuinely ended but left a stale `in_progress` todo read as
permanently working. `detailIsWorking()` now prefers `session.meta.ended`
when present and only falls back to the todo-derived guess otherwise (see its
own comment for the one provider -- Claude -- still missing the field as of
this pass). The `bg` half of the adapter (`agents_bg`-derived) was always
correct and is untouched.

THE FIX (ext_cr_detail.css):
  - `.crd-pill-state.crd-state-working` gains `box-shadow: var(--glow-working,
    var(--glow-agent-soft))` plus `animation: crd-pulse 2.4s infinite` -- the
    SAME keyframe every other pulsing dot in this file already uses
    (`.crd-seg-dot`, `.crd-phone-orb.crd-state-working`), no second animation
    invented. Consumes the CANONICAL `--state-working`/`--glow-working`
    tokens (ext_cr.css, both palettes) -- not a hardcoded hex, and not the
    phone orb's older `--line-agent`/`--glow-agent` pair, so all three
    surfaces (board tile, rail dot, detail pill) read as the SAME "working"
    signal.
  - The existing `@media (prefers-reduced-motion: reduce)` block (the one
    that already turns off `.crd-seg-dot`'s pulse) gains a matching override
    for the pill: `animation: none` plus `outline: 2px solid
    var(--state-working)` -- the pulse is disabled, but the STATIC glow
    (the base rule's own `box-shadow`, no longer masked by the animation)
    remains, exactly matching `.crd-phone-orb.crd-state-working`'s own
    reduced-motion treatment.

Idiom for the functional half: copied from tests/test_cr_timeline.py (a
minimal stub DOM, no HTML parsing) -- `window.CR.detail._internal.stateOf` /
`.detailIsWorking` are pure functions over plain data, so no full
`Detail.prototype.mount()` (which needs a REAL `<template>.innerHTML` parser
this stdlib-only harness cannot provide) is needed to exercise them.
Self-contained; skips cleanly (not a failure) when node is unavailable.
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
_WEB = os.path.join(_ROOT, "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)

NOW = 1_700_000_000


def _read_web_file(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as f:
        return f.read()


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _block(css, selector):
    start = css.index(selector)
    brace = css.index("{", start)
    depth = 0
    for i in range(brace, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[brace:i + 1]
    raise AssertionError("unterminated block for %r" % selector)


def _reduced_motion_blocks(css):
    """Every `@media (prefers-reduced-motion: reduce) { ... }` block's inner
    text, brace-matched (idiom copied verbatim from
    tests/test_working_glow_board.py)."""
    blocks = []
    for m in re.finditer(r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{', css):
        i = m.end()
        depth = 1
        while i < len(css) and depth > 0:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
            i += 1
        blocks.append(css[m.end():i - 1])
    return blocks


# ===========================================================================
# PART 1 -- CSS source-level checks.
# ===========================================================================

class TestDesktopWorkingGlowCss(unittest.TestCase):
    def setUp(self):
        self.css = _read_web_file("ext_cr_detail.css")

    def test_working_pill_has_glow_and_pulse(self):
        block = _block(self.css, ".cr .crd-pill-state.crd-state-working {")
        self.assertIn("box-shadow", block)
        self.assertIn("--glow-working", block)
        self.assertIn("var(--glow-agent-soft)", block, "must fall back if --glow-working hasn't landed yet")
        self.assertIn("animation", block)
        self.assertIn("crd-pulse", block, "must reuse the SAME keyframe as .crd-seg-dot/.crd-phone-orb, not invent a new one")

    def test_working_pill_uses_shared_tokens_not_a_hardcoded_hex_or_rgba(self):
        block = _block(self.css, ".cr .crd-pill-state.crd-state-working {")
        self.assertNotRegex(block, r'#[0-9a-fA-F]{3,8}\b', "must not hardcode a hex colour")
        self.assertNotRegex(block, r'rgba?\(\s*\d', "must not hardcode a literal rgb()/rgba() -- consume the token instead")

    def test_other_state_classes_get_no_glow(self):
        """Only 'working' gets a glow -- a sibling state must not have picked
        one up by an over-broad selector or a copy/paste."""
        for cls in ("awaiting", "flagged", "failed", "done", "idle"):
            block = _block(self.css, ".cr .crd-pill-state.crd-state-%s {" % cls)
            self.assertNotIn("box-shadow", block, "%s must not carry a glow" % cls)
            self.assertNotIn("animation", block, "%s must not carry a pulse" % cls)

    def test_reduced_motion_disables_the_pulse_but_adds_an_outline(self):
        blocks = _reduced_motion_blocks(self.css)
        hit = [b for b in blocks if "crd-pill-state.crd-state-working" in b]
        self.assertTrue(hit, "no reduced-motion block overrides .crd-pill-state.crd-state-working")
        block = hit[0]
        self.assertIn("animation: none", block)
        self.assertIn("outline", block)
        self.assertIn("--state-working", block)

    def test_reduced_motion_never_re_declares_the_static_glow_away(self):
        """The base rule's box-shadow must survive reduced motion untouched --
        it is only ever MASKED by the animation while that plays, so turning
        the animation off is enough for the static glow to reappear. If the
        reduced-motion override also touched box-shadow, that guarantee could
        silently break."""
        blocks = _reduced_motion_blocks(self.css)
        for b in blocks:
            if "crd-pill-state.crd-state-working" in b:
                # find just this selector's own declaration body within the block
                m = re.search(r'\.crd-pill-state\.crd-state-working\s*\{([^}]*)\}', b)
                self.assertIsNotNone(m)
                self.assertNotIn("box-shadow", m.group(1),
                                  "reduced-motion override must not re-declare box-shadow")

    def test_reduced_motion_seg_dot_regression_still_holds(self):
        """Non-regression: the pre-existing .crd-seg-dot pulse-disable must
        still be present (this pass edits the SAME media block)."""
        blocks = _reduced_motion_blocks(self.css)
        self.assertTrue(any("crd-seg-dot" in b and "animation: none" in b for b in blocks))


# ===========================================================================
# PART 2 -- functional: the predicate itself, via the real bundled JS.
# ===========================================================================

_JS_PREAMBLE = r"""
globalThis.window = globalThis;
var _elMap = {};
function makeEl(id) {
  var self = {
    id: id || null,
    classList: { add: function(){}, remove: function(){}, toggle: function(){}, contains: function(){ return false; } },
    style: {}, dataset: {}, setAttribute: function(){}, getAttribute: function(){ return null; },
    appendChild: function(){}, append: function(){}, remove: function(){}, insertBefore: function(){},
    addEventListener: function(){}, removeEventListener: function(){},
    querySelector: function() { return self; }, querySelectorAll: function() { return [self]; },
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus: function(){}, click: function(){}
  };
  return self;
}
var stubEl = makeEl(null);
window.document = {
  createElement: function() { return makeEl(null); }, createTextNode: function() { return makeEl(null); },
  getElementById: function (id) { if (!_elMap[id]) _elMap[id] = makeEl(id); return _elMap[id]; },
  querySelector: function() { return stubEl; }, querySelectorAll: function() { return [stubEl]; },
  addEventListener: function(){}, dispatchEvent: function(){},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};

var _localStorage = {};
window.localStorage = {
  getItem: function(k) { return (k in _localStorage) ? _localStorage[k] : null; },
  setItem: function(k, v) { _localStorage[k] = v; },
  removeItem: function(k) { delete _localStorage[k]; }
};

window.matchMedia = function() { return { matches: false, addEventListener: function(){}, addListener: function(){}, removeEventListener: function(){} }; };
window.fetch = function() { return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({}); }, text: function(){ return Promise.resolve(""); }, headers: { get: function(){ return null; } } }); };
window.setInterval = function() { return 0; }; window.setTimeout = function() { return 0; }; window.clearInterval = function(){}; window.clearTimeout = function(){};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: function(){ return Promise.resolve(); } } };
window.CustomEvent = function(type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = function() { return 0; };
window.getComputedStyle = function() { return { getPropertyValue: function(){ return ""; } }; };
window.getSelection = function() { return { toString: function(){ return ""; } }; };
window.addEventListener = function(){}; window.removeEventListener = function(){}; window.dispatchEvent = function(){};
process.on("unhandledRejection", function(){});

try {
"""

_JS_MID = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


def make_detail(**overrides):
    # ITEM 3b (adversarial-review test gap): this fixture's `meta` used to carry NO
    # `ended` key at all, so every assertion below exercised only the broken
    # todo-derived adapter, never the real transcript-tail fact detailIsWorking() now
    # prefers. Default here is `ended: True` (a bare "nothing in flight" baseline) --
    # every fixture below overrides it explicitly so tests drive the REAL value, not
    # an accidental default.
    d = {
        "meta": {"cwd": "/tmp/proj", "gitBranch": "main", "sessionId": "sid",
                  "model": "", "effort": "", "title": "t", "ended": True},
        "todos": [], "files": [], "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": [], "agents": [], "agents_bg": [], "shells": [],
        "decisions": [], "waiting": False, "prs": [], "narrative": [],
        "tokens": {"in": 0, "out": 0}, "context": {"current": 0, "limit": 0, "pct": 0},
        "counts": {}, "mtime": 0, "now": 0, "notes": [], "push_when": "turn",
        "overview": {"where": "", "goal": "", "now": "", "now_kind": "", "sofar": "", "commits": []},
        "continued_as": "", "continued_from": "", "open_flags": 0, "fail_cmd": None,
    }
    d.update(overrides)
    return d


def _bundle_js():
    return _extract_script_content(_read_page())


def _extract_marker_json(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


def _meta(ended, **kw):
    """A full meta dict driving `ended` EXPLICITLY (item 3b) -- every fixture below
    states the real transcript-tail fact it wants detailIsWorking() to prefer,
    instead of leaning on make_detail()'s bare default."""
    m = {"cwd": "/tmp/proj", "gitBranch": "main", "sessionId": "sid",
         "model": "", "effort": "", "title": "t", "ended": ended}
    m.update(kw)
    return m


# Six fixtures, each isolating one cell of the WORKING predicate this file's
# detailIsWorking() adapts onto isSessionWorking(s, live) = live && (!s.ended
# || !!s.bg):
#   working_live       live, real meta.ended=False (foreground turn not finished) -> WORKING
#   landed_live        live, real meta.ended=True, no running bg agent            -> NOT working (landed)
#   working_ended_bg   live, real meta.ended=True, a RUNNING bg agent             -> WORKING (the bg-aware fix)
#   idle_stale_bg      NOT live, real meta.ended=True, a running bg agent         -> NOT working (idle) --
#                      bg alone, without liveness, must not force "working"
#   live_no_todos      ITEM 1 / defect A: live, real meta.ended=False, NO todos at
#                      all (the common case -- Claude prunes ~/.claude/tasks/* and many
#                      sessions never call TodoWrite). The OLD todo-derived adapter
#                      guessed `ended = !inProgress = true` here (no in-progress todo
#                      found) and read this as LANDED while the board/rail's real
#                      `ended:false` said WORKING -- glow silently missing. Must be
#                      WORKING now that the real value is preferred.
#   ended_stale_todo   ITEM 1 / defect B: live, real meta.ended=True (the session
#                      genuinely finished), but a STALE `in_progress` todo survives.
#                      The OLD adapter guessed `ended = !inProgress = false` and kept
#                      showing WORKING (a permanent false glow) long after the board
#                      already read LANDED. Must be NOT working (landed) now.
_DRIVER_TAIL = r"""
var NOW = %(now)d;
var I = window.CR.detail._internal;
var OUT = {};

var sessions = {
  working_live:     %(working_live)s,
  landed_live:      %(landed_live)s,
  working_ended_bg: %(working_ended_bg)s,
  idle_stale_bg:    %(idle_stale_bg)s,
  live_no_todos:    %(live_no_todos)s,
  ended_stale_todo: %(ended_stale_todo)s
};

Object.keys(sessions).forEach(function (key) {
  var s = sessions[key];
  var idle = NOW - (s.mtime || 0);
  var live = idle < 300;
  OUT["detailIsWorking_" + key] = I.detailIsWorking(s, live);
  OUT["stateOf_" + key] = I.stateOf(s, NOW).cls;
});

console.log("===CR_DETAIL_GLOW_JSON_START===");
console.log(JSON.stringify(OUT));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestDetailWorkingPredicate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        working_live = make_detail(mtime=NOW - 5, agents_bg=[], todos=[{"status": "in_progress"}],
                                    meta=_meta(False))
        landed_live = make_detail(mtime=NOW - 5, agents_bg=[], todos=[{"status": "done"}],
                                   meta=_meta(True))
        working_ended_bg = make_detail(mtime=NOW - 5, agents_bg=[{"running": True}], todos=[{"status": "done"}],
                                        meta=_meta(True))
        idle_stale_bg = make_detail(mtime=NOW - 10_000, agents_bg=[{"running": True}], todos=[{"status": "done"}],
                                     meta=_meta(True))
        # defect A: no todos at all, real ended is False (live, foreground still open)
        live_no_todos = make_detail(mtime=NOW - 5, agents_bg=[], todos=[], meta=_meta(False))
        # defect B: real ended is True, but a stale in_progress todo survives
        ended_stale_todo = make_detail(mtime=NOW - 5, agents_bg=[], todos=[{"status": "in_progress"}],
                                        meta=_meta(True))
        tail = _DRIVER_TAIL % {
            "now": NOW,
            "working_live": json.dumps(working_live),
            "landed_live": json.dumps(landed_live),
            "working_ended_bg": json.dumps(working_ended_bg),
            "idle_stale_bg": json.dumps(idle_stale_bg),
            "live_no_todos": json.dumps(live_no_todos),
            "ended_stale_todo": json.dumps(ended_stale_todo),
        }
        js = "\n".join([_JS_PREAMBLE, _bundle_js(), _JS_MID, tail])
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Detail working-glow predicate driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_DETAIL_GLOW_JSON_START===")

    def test_working_live_is_working(self):
        self.assertTrue(self.OUT["detailIsWorking_working_live"])
        self.assertEqual(self.OUT["stateOf_working_live"], "working")

    def test_landed_live_is_not_working(self):
        """live + real ended=True + no running bg agent must NOT read as working."""
        self.assertFalse(self.OUT["detailIsWorking_landed_live"])
        self.assertEqual(self.OUT["stateOf_landed_live"], "done")

    def test_ended_with_background_agents_is_working(self):
        """The bg-aware case: no foreground work in flight, but a background
        agent is still running -- must still read as working, matching the
        board tile's own bg-aware fix."""
        self.assertTrue(self.OUT["detailIsWorking_working_ended_bg"])
        self.assertEqual(self.OUT["stateOf_working_ended_bg"], "working")

    def test_stale_with_background_agents_is_not_working(self):
        """bg alone, without liveness, must not force 'working'."""
        self.assertFalse(self.OUT["detailIsWorking_idle_stale_bg"])
        self.assertEqual(self.OUT["stateOf_idle_stale_bg"], "idle")

    def test_live_session_with_no_todos_and_real_ended_false_is_working(self):
        """Regression for defect A: a live session with NO todos at all (the common
        case) and a REAL meta.ended=False must read WORKING -- the old todo-derived
        adapter guessed ended=True here (no in-progress todo found) and silently lost
        the glow. This must go RED if the adapter regresses to the todo-only guess."""
        self.assertTrue(self.OUT["detailIsWorking_live_no_todos"])
        self.assertEqual(self.OUT["stateOf_live_no_todos"], "working")

    def test_ended_session_with_stale_in_progress_todo_is_not_working(self):
        """Regression for defect B: a session that REALLY ended (meta.ended=True) but
        left a stale in_progress todo must read LANDED, not a permanent false glow."""
        self.assertFalse(self.OUT["detailIsWorking_ended_stale_todo"])
        self.assertEqual(self.OUT["stateOf_ended_stale_todo"], "done")


# ===========================================================================
# ITEM 3a (adversarial-review test gap): there was NO board-vs-detail parity
# assertion anywhere in this codebase -- the exact class of bug this whole pass
# fixes (detail disagreeing with the board/rail about the SAME session) had no test
# that could ever have caught it. This drives the board's OWN `sessionState()`
# (ext_cr_board.js, exposed as window.CR.board.sessionState) and the detail's OWN
# `detailIsWorking()`/`stateOf()` (ext_cr_detail.js) off a SHARED scenario -- a
# board-shaped session dict and a detail-shaped session dict built from the same
# {ended, bg_running, todo_status} inputs -- and requires their working-ness to
# AGREE. Must fail if detailIsWorking() regresses to a second, independently
# re-derived rule that drifts from the board's.
# ===========================================================================

def _paired_sessions(mtime, ended, bg_running, todo_status=None):
    """(board_dict, detail_dict) describing the SAME session, built from the same
    inputs but in each dict's own real shape -- board's flat {ended, bg}, detail's
    {meta.ended, agents_bg, todos}."""
    board = {
        "mtime": mtime, "waiting": False, "open_flags": 0, "fail_cmd": None,
        "ended": ended, "bg": 1 if bg_running else 0,
    }
    todos = [{"status": todo_status}] if todo_status else []
    detail = make_detail(mtime=mtime, waiting=False, open_flags=0, fail_cmd=None,
                          agents_bg=[{"running": True}] if bg_running else [],
                          todos=todos, meta=_meta(ended))
    return board, detail


_PARITY_DRIVER_TAIL = r"""
var NOW = %(now)d;
var board = window.CR.board;
var detailI = window.CR.detail._internal;
var OUT = {};

var cases = %(cases)s;

Object.keys(cases).forEach(function (key) {
  var c = cases[key];
  var idle = NOW - (c.board.mtime || 0);
  var live = idle < 300;
  OUT["board_" + key] = board.sessionState(c.board, NOW) === "working";
  OUT["detail_" + key] = detailI.detailIsWorking(c.detail, live);
});

console.log("===CR_PARITY_JSON_START===");
console.log(JSON.stringify(OUT));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardDetailWorkingParity(unittest.TestCase):
    """The parity test the adversarial review said must exist: board's
    sessionState() and detail's detailIsWorking() must agree on the SAME session,
    for every scenario that used to divergence."""

    @classmethod
    def setUpClass(cls):
        no_todos_live_board, no_todos_live_detail = _paired_sessions(
            NOW - 5, ended=False, bg_running=False, todo_status=None)
        ended_stale_todo_board, ended_stale_todo_detail = _paired_sessions(
            NOW - 5, ended=True, bg_running=False, todo_status="in_progress")
        ended_running_bg_board, ended_running_bg_detail = _paired_sessions(
            NOW - 5, ended=True, bg_running=True, todo_status="done")
        landed_board, landed_detail = _paired_sessions(
            NOW - 5, ended=True, bg_running=False, todo_status="done")
        working_board, working_detail = _paired_sessions(
            NOW - 5, ended=False, bg_running=False, todo_status="in_progress")
        cases = {
            "no_todos_live": {"board": no_todos_live_board, "detail": no_todos_live_detail},
            "ended_stale_todo": {"board": ended_stale_todo_board, "detail": ended_stale_todo_detail},
            "ended_running_bg": {"board": ended_running_bg_board, "detail": ended_running_bg_detail},
            "landed": {"board": landed_board, "detail": landed_detail},
            "working": {"board": working_board, "detail": working_detail},
        }
        tail = _PARITY_DRIVER_TAIL % {"now": NOW, "cases": json.dumps(cases)}
        js = "\n".join([_JS_PREAMBLE, _bundle_js(), _JS_MID, tail])
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Board/detail parity driver failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr))
        cls.OUT = _extract_marker_json(stdout, "===CR_PARITY_JSON_START===")
        cls.cases = list(cases.keys())

    def test_board_and_detail_agree_on_every_scenario(self):
        for key in self.cases:
            self.assertEqual(
                self.OUT["board_" + key], self.OUT["detail_" + key],
                "board sessionState() and detail detailIsWorking() DISAGREE for "
                "scenario %r (board=%r, detail=%r) -- same session, two different "
                "answers to 'is this working'" % (key, self.OUT["board_" + key], self.OUT["detail_" + key]))

    def test_no_todos_live_session_is_working_on_both(self):
        """Defect A pinned at the parity layer: live, no todos, real ended=False."""
        self.assertTrue(self.OUT["board_no_todos_live"])
        self.assertTrue(self.OUT["detail_no_todos_live"])

    def test_ended_with_stale_todo_is_not_working_on_both(self):
        """Defect B pinned at the parity layer: really ended, stale in_progress todo."""
        self.assertFalse(self.OUT["board_ended_stale_todo"])
        self.assertFalse(self.OUT["detail_ended_stale_todo"])

    def test_ended_with_running_bg_is_working_on_both(self):
        self.assertTrue(self.OUT["board_ended_running_bg"])
        self.assertTrue(self.OUT["detail_ended_running_bg"])


# ===========================================================================
# ITEM 3c (adversarial-review test gap): the glow assertions above only grep
# substrings ("--glow-working", "box-shadow") inside ext_cr_detail.css -- a file
# that never DEFINES the token, only consumes it via var(--glow-working, ...).
# Someone could set `--glow-working: 0 0 0 rgba(0,0,0,0)` in ext_cr.css (the file
# that DOES define it, and a file these tests never read) and every assertion above
# would stay green while the glow is completely invisible. This resolves the
# token's ACTUAL declared value(s) from the real ASSEMBLED page (app.css + every
# ext_*.css concatenated, exactly what page.build_page() sends the browser) and
# requires a non-zero blur radius and non-zero alpha in EVERY declaration found.
# ===========================================================================

def _extract_style_content(html):
    m = re.search(r'<style>(.*?)</style>', html, re.DOTALL)
    if not m:
        raise AssertionError("No <style> tag found in assembled page")
    return m.group(1)


class TestGlowWorkingTokenIsActuallyVisible(unittest.TestCase):
    def setUp(self):
        from aitracker import page
        css = _extract_style_content(page.build_page())
        # strip /* ... */ comments first -- the token name and prose about it appear
        # in plenty of explanatory CSS comments too, which are not declarations.
        self.css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)

    def test_glow_working_has_nonzero_blur_and_alpha_in_every_declaration(self):
        decls = re.findall(r'--glow-working:\s*([^;]+);', self.css)
        self.assertTrue(decls, "no --glow-working custom property is declared anywhere "
                                "in the assembled page")
        for value in decls:
            m = re.search(r'(\d+(?:\.\d+)?)\s*px\s*rgba?\(([^)]+)\)', value)
            self.assertIsNotNone(
                m, "--glow-working: %r has no <blur>px rgba(...) shadow layer to measure" % value)
            blur = float(m.group(1))
            channels = [c.strip() for c in m.group(2).split(",")]
            alpha = float(channels[-1]) if len(channels) == 4 else 1.0
            self.assertGreater(blur, 0,
                                "--glow-working: %r has a ZERO blur radius -- an invisible glow "
                                "would still pass the substring-only checks above" % value)
            self.assertGreater(alpha, 0,
                                "--glow-working: %r has a ZERO alpha -- an invisible glow "
                                "would still pass the substring-only checks above" % value)


# ===========================================================================
# ITEM 1 (Python half, Auggie): providers/auggie.py's DETAIL meta used to omit
# `ended` entirely, even though its LIST dict has always carried it (both via
# `_auggie_state(chatHistory)`). That left the JS predicate above no real value
# to prefer for Auggie sessions, same as the false "no ended boolean" claim this
# pass corrects. This is a plain Python-level check (no node needed) that
# parse_auggie()'s meta now carries a real `ended` bool, derived the SAME way
# (one call to `_auggie_state`) as list_auggie()'s own `ended` for the identical
# session -- board list and detail agreeing at the SERVER layer, not just in a
# synthetic JS fixture.
# ===========================================================================

import aitracker.config as _config
from aitracker.providers import auggie as _auggie

_AUGGIE_ENDED_SESSION = {
    "sessionId": "s_glow_ended", "modified": "2026-06-27T05:48:03Z", "customTitle": "Ended",
    "chatHistory": [
        {"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
            "request_message": "do the thing", "response_text": "done doing the thing",
            "request_nodes": [], "response_nodes": []}},
    ],
}

_AUGGIE_WAITING_SESSION = {
    "sessionId": "s_glow_waiting", "modified": "2026-06-27T05:48:03Z", "customTitle": "Waiting",
    "chatHistory": [
        {"finishedAt": "2026-06-27T05:47:50Z", "exchange": {
            "request_message": "do the thing", "response_text": "",
            "request_nodes": [],
            "response_nodes": [
                {"tool_use": {"tool_use_id": "ask1", "tool_name": "ask-user", "input_json": "{}"}},
            ]}},
    ],
}


class TestAuggieDetailEndedMatchesListDict(unittest.TestCase):
    def setUp(self):
        self._snap = (_config.AUGMENT_DIR, _config.AUGGIE_SESSIONS, _config.TITLES_FILE,
                      _config.NOTES_FILE, _config.TASKS_DIR)
        _config.AUGMENT_DIR = tempfile.mkdtemp()
        _config.AUGGIE_SESSIONS = os.path.join(_config.AUGMENT_DIR, "sessions")
        os.makedirs(_config.AUGGIE_SESSIONS)
        _config.TITLES_FILE = tempfile.mktemp(suffix=".json")
        _config.NOTES_FILE = tempfile.mktemp(suffix=".json")
        _config.TASKS_DIR = tempfile.mkdtemp()
        _auggie._AUGGIE_LIST_CACHE.clear()

    def tearDown(self):
        (_config.AUGMENT_DIR, _config.AUGGIE_SESSIONS, _config.TITLES_FILE,
         _config.NOTES_FILE, _config.TASKS_DIR) = self._snap
        _auggie._AUGGIE_LIST_CACHE.clear()

    def _write(self, d):
        with open(os.path.join(_config.AUGGIE_SESSIONS, d["sessionId"] + ".json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        _auggie._AUGGIE_LIST_CACHE.clear()

    def test_ended_session_meta_ended_is_true_and_matches_list_dict(self):
        self._write(_AUGGIE_ENDED_SESSION)
        detail = _auggie.parse_auggie("s_glow_ended")
        self.assertIn("ended", detail["meta"], "parse_auggie()'s meta must carry `ended`")
        self.assertIs(detail["meta"]["ended"], True)
        listed = {e["id"]: e for e in _auggie.list_auggie()}
        self.assertEqual(listed["auggie:s_glow_ended"]["ended"], detail["meta"]["ended"],
                          "list dict and detail dict `ended` must agree for the SAME session")

    def test_waiting_session_meta_ended_is_false_and_matches_list_dict(self):
        self._write(_AUGGIE_WAITING_SESSION)
        detail = _auggie.parse_auggie("s_glow_waiting")
        self.assertIn("ended", detail["meta"])
        self.assertIs(detail["meta"]["ended"], False)
        listed = {e["id"]: e for e in _auggie.list_auggie()}
        self.assertEqual(listed["auggie:s_glow_waiting"]["ended"], detail["meta"]["ended"],
                          "list dict and detail dict `ended` must agree for the SAME session")


if __name__ == "__main__":
    unittest.main()
