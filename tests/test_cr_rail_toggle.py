"""Regression tests for: the "Expand session rail" toggle was a no-op in the
detail view / 1025-1279px board tier (aitracker/web/ext_cr_board.js).

THE BUG: applyRailMode() computed

    var collapsed = isDetail || (railMode === 'collapsed') ||
                     (innerWidth < 1280 && innerWidth >= 1025);

so the FORCED conditions (detail view; the 1025-1279px board tier) OR-ed over
the user's stored `railMode`. Clicking "Expand session rail" wrote
localStorage['tracker.rail'] and called applyRailMode(), which immediately
re-forced collapsed=true — a visible button, correctly labelled, that did
nothing.

THE FIX pinned here (read from the real shipped source, not retyped by hand —
see _extract_function() below):
  - `railMode` is tri-state 'auto' | 'open' | 'collapsed', DEFAULT 'auto'
    (was 'open').
  - applyRailMode() only applies the forced conditions when railMode==='auto';
    an explicit 'open'/'collapsed' choice always wins over them.
  - toggleRail() derives the next mode from what's actually RENDERED
    (the `cr-rail--collapsed` class), not from the previous stored value —
    under 'auto' those two could disagree, and flipping the stored value
    produced a dead first click.
  - `cr-rail--detail` (the 56px orb styling) is now gated on `collapsed` too,
    so an explicitly expanded detail rail gets the full 232px row rail
    instead of staying stuck in orb mode.

IDIOM: same "assemble the real page, pull the bundle out of its <script> tag"
idiom as test_cr_logic.py (aitracker.page.build_page()). That file then runs
the WHOLE bundle under a full stub DOM to reach window.CR.board's EXPORTED
pure functions — but applyRailMode()/toggleRail() are internal closures over
`els`/`railMode`/`currentView` inside createBoard(), never exported, and that
file's own DOM stub gives every element a no-op classList (add/remove/toggle
do nothing, contains() always returns false) — fine for pure functions, but
it would make every assertion here vacuously pass regardless of the fix.

So instead: brace-match the exact `function applyRailMode() {...}` /
`function toggleRail() {...}` text out of the REAL bundle (never a hand-copied
paraphrase — if the source drifts, extraction fails loudly rather than
silently testing stale text), and execute each inside a tiny harness that
supplies just its free variables (`els`, `railMode`, `currentView`,
`window.innerWidth`, `localStorage`, …), with a real Set-backed classList so
class add/remove/toggle/contains are actually observable.

TWO THINGS CHANGED SINCE THIS FILE WAS FIRST WRITTEN (both pinned below):

  1. The localStorage key was RENAMED from 'tracker.rail' to 'tracker.rail.mode'.
     The old key's vocabulary was 'open'|'collapsed' with 'open' as the literal
     default, so a stored 'open' was indistinguishable from "never chose" —
     and the old dead toggle wrote one on every frustrated click. Reading a
     legacy 'tracker.rail' value as an explicit 'open' would hand existing
     users an expanded rail in the detail view they never asked for, so the
     new key starts everyone at 'auto' (byte-for-byte the old default
     behaviour) and the legacy key is deliberately never read. See
     TestRailToggleNotADeadControl.test_default_railmode_ignores_legacy_key_and_stays_auto
     and TestRailPrefTriState.test_read_rail_pref_ignores_legacy_key_and_stays_auto
     for the guarantee itself.
  2. ext_cr_board.js's mount() now subscribes to the shared 'cr:pref' bus
     event, so Config's "Session rail" row actually moves the live rail
     instead of writing localStorage into a void. See
     TestBoardSubscribesToConfigPrefChanges below.
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


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    matches = list(script_pattern.finditer(html))
    if not matches:
        raise ValueError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the
    real bundle. Raises loudly (never returns a guess) if the shape has moved,
    so this test fails honestly instead of silently exercising stale text."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in the real bundle" % name)
    brace_start = source.index('{', m.start())
    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[m.start():i + 1]
    raise AssertionError("unterminated function %s() (brace mismatch)" % name)


def _extract_statement(source, var_name):
    """Grabs a single `var NAME = ...;` statement verbatim (no nested braces
    expected), e.g. railMode's own default-value line."""
    m = re.search(r'var\s+' + re.escape(var_name) + r'\s*=\s*[^\n;]+;', source)
    if not m:
        raise AssertionError("`var %s = ...;` not found in the real bundle" % var_name)
    return m.group(0)


def _extract_call(source, marker):
    """Grabs a full `marker(...)` call expression verbatim, paren-matched from
    the marker's own opening `(` through its balanced close. Unlike
    _extract_function() this isn't a function *definition* -- it's used to
    pull the "Session rail" `cfgRow('Session rail', ..., segmented(...))` call
    site out of renderConfig(), matched the same honest way: if the call moves
    or its shape changes so the marker text no longer appears verbatim, this
    raises loudly instead of silently checking stale text."""
    idx = source.find(marker)
    if idx < 0:
        raise AssertionError("%r not found in the real bundle" % (marker,))
    paren_start = source.index('(', idx)
    depth = 0
    for i in range(paren_start, len(source)):
        c = source[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return source[idx:i + 1]
    raise AssertionError("unterminated call for marker %r (paren mismatch)" % (marker,))


# ---------------------------------------------------------------------------
# rail-mode VOCABULARY extraction -- used by the drift guard between
# ext_cr_dialogs.js (readRailPref/writeRailPref) and ext_cr_board.js
# (applyRailMode/toggleRail/the module-level default). See
# TestRailPrefConfigRowAndVocabulary.test_rail_mode_vocabulary_agrees_across_both_files
# below for what this is protecting against.
# ---------------------------------------------------------------------------

_MODE_LITERAL_RE = re.compile(r"'([a-z]+)'")

# Exactly one documented exclusion: writeRailPref's `_ctx.emit(...)` line
# happens to share its source line with `typeof _ctx.emit === 'function'`
# (a capability check, not a rail-mode value) -- the ONLY lowercase
# single-quoted word on any line that mentions the mode variable/parameter
# that isn't actually a rail mode. If a real 'function'-named mode is ever
# introduced this will need revisiting, but that's not a real mode name.
_NON_MODE_WORDS = frozenset({'function'})


def _mode_literals_on_lines_mentioning(source, var_name):
    """Collects lowercase single-quoted string literals ('auto', 'open',
    'collapsed', ...) that appear on the same source line as `var_name` -- the
    actual local variable/parameter each function threads the rail-mode value
    through ('v' in readRailPref, 'mode' in writeRailPref, 'railMode' in
    applyRailMode/toggleRail/the module-level default statement). Line-scoped
    and anchored to that name rather than a blanket scan of the whole function
    text, so CSS/view-name literals elsewhere in the same function body
    ('cr-rail--collapsed', 'detail', 'sessions') are never mistaken for a rail
    mode just because they happen to live in the same function."""
    anchor = re.compile(r'\b' + re.escape(var_name) + r'\b')
    out = set()
    for line in source.splitlines():
        if anchor.search(line):
            out |= set(_MODE_LITERAL_RE.findall(line))
    return out - _NON_MODE_WORDS


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout):
    marker = "===RAIL_TOGGLE_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


# A real, honest classList backed by a Set -- deliberately NOT the no-op stub
# test_cr_logic.py uses for its full-bundle-under-stub-DOM runs (fine there,
# since that file never inspects class state; it would be a silent false-pass
# here, since every assertion below is exactly about class state).
_CLASSLIST_STUB = r"""
function makeClassList() {
  var set = new Set();
  return {
    add: function (c) { set.add(c); },
    remove: function (c) { set.delete(c); },
    toggle: function (c, force) {
      if (force === undefined) force = !set.has(c);
      if (force) set.add(c); else set.delete(c);
      return force;
    },
    contains: function (c) { return set.has(c); },
  };
}
"""


def _apply_rail_mode_case_js(case_id, apply_rail_mode_src, rail_mode, current_view, inner_width):
    return r"""
OUT["%s"] = (function () {
  var railMode = %s;
  var currentView = %s;
  var window = { innerWidth: %d };
  var lastState = { sessions: [], now: 0 };
  function renderRail() {}
  var els = {
    rail: { classList: makeClassList() },
    railChevron: { setAttribute: function () {} },
    railToggleTop: null,
  };
  %s
  applyRailMode();
  return {
    collapsed: els.rail.classList.contains('cr-rail--collapsed'),
    detail: els.rail.classList.contains('cr-rail--detail'),
    hidden: els.rail.classList.contains('cr-rail--hidden'),
  };
})();
""" % (case_id, json.dumps(rail_mode), json.dumps(current_view), inner_width, apply_rail_mode_src)


def _toggle_rail_case_js(case_id, toggle_rail_src, apply_rail_mode_src,
                          rail_mode, current_view, inner_width, rendered_collapsed):
    return r"""
OUT["%s"] = (function () {
  var railMode = %s;
  var currentView = %s;
  var window = { innerWidth: %d };
  var railOverlayOpen = false;
  var lastState = { sessions: [], now: 0 };
  var localStorageStore = {};
  var localStorage = {
    getItem: function (k) { return (k in localStorageStore) ? localStorageStore[k] : null; },
    setItem: function (k, v) { localStorageStore[k] = v; },
  };
  function renderRail() {}
  function closeRailOverlay() {}
  function openRailOverlay() {}
  var els = {
    rail: { classList: makeClassList() },
    railChevron: { setAttribute: function () {} },
    railToggleTop: null,
  };
  if (%s) els.rail.classList.add('cr-rail--collapsed');
  %s
  %s
  toggleRail();
  return {
    railModeAfter: railMode,
    storedAfter: localStorageStore['tracker.rail.mode'] || null,
    collapsedAfter: els.rail.classList.contains('cr-rail--collapsed'),
  };
})();
""" % (case_id, json.dumps(rail_mode), json.dumps(current_view), inner_width,
       json.dumps(bool(rendered_collapsed)), toggle_rail_src, apply_rail_mode_src)


def _default_rail_mode_case_js():
    # Confirms the DEFAULT-VALUE expression itself, executed for real (not
    # regexed for the string 'auto') against a localStorage that has never
    # seen 'tracker.rail.mode' -- the exact state of a first-ever page load.
    return r"""
OUT["default_railmode_is_auto"] = (function () {
  var localStorage = { getItem: function () { return null; } };
  %s
  return railMode;
})();
"""


def _default_rail_mode_ignores_legacy_key_case_js():
    # THE MIGRATION GUARANTEE, executed for real: models a browser that has
    # ONLY ever written the OLD 'tracker.rail' key (to 'open', the two-state
    # world's own literal default) and has NEVER written the new
    # 'tracker.rail.mode' key. The default-value statement must still resolve
    # to 'auto' -- reading the legacy value as an explicit 'open' would hand
    # an existing user an expanded 232px rail in the detail view they never
    # asked for. This is the whole point of the rename; if a future change
    # "helpfully" reads the old key again, this must fail loudly.
    return r"""
OUT["default_railmode_ignores_legacy_key"] = (function () {
  var localStorage = { getItem: function (k) { return (k === 'tracker.rail') ? 'open' : null; } };
  %s
  return railMode;
})();
"""


def _full_driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    apply_rail_mode_src = _extract_function(bundle, "applyRailMode")
    toggle_rail_src = _extract_function(bundle, "toggleRail")
    default_railmode_stmt = _extract_statement(bundle, "railMode")

    parts = [_CLASSLIST_STUB, "var OUT = {};"]

    # (a) explicit 'open' beats the FORCED conditions (isDetail; the
    #     1025-1279px tier) that used to be OR-ed in unconditionally.
    parts.append(_apply_rail_mode_case_js(
        "explicit_open_beats_detail_force", apply_rail_mode_src,
        rail_mode="open", current_view="detail", inner_width=1600))
    parts.append(_apply_rail_mode_case_js(
        "explicit_open_beats_tier_force", apply_rail_mode_src,
        rail_mode="open", current_view="board", inner_width=1100))
    # explicit 'collapsed' still collapses outside any forced tier/view too.
    parts.append(_apply_rail_mode_case_js(
        "explicit_collapsed_applies_outside_forced_zone", apply_rail_mode_src,
        rail_mode="collapsed", current_view="board", inner_width=1600))

    # (b) tri-state default: 'auto' defers to the forced conditions (unlike
    #     the old default 'open', which -- per (a) above -- no longer does).
    parts.append(_default_rail_mode_case_js() % default_railmode_stmt)
    parts.append(_default_rail_mode_ignores_legacy_key_case_js() % default_railmode_stmt)
    parts.append(_apply_rail_mode_case_js(
        "auto_mode_still_follows_detail_force", apply_rail_mode_src,
        rail_mode="auto", current_view="detail", inner_width=1600))
    parts.append(_apply_rail_mode_case_js(
        "auto_mode_still_follows_tier_force", apply_rail_mode_src,
        rail_mode="auto", current_view="board", inner_width=1100))

    # (c) toggleRail derives the next mode from the RENDERED class, not the
    #     previous stored value -- seed `railMode` with a value unrelated to
    #     either outcome so a same-as-before pass can't hide a wrong wiring.
    parts.append(_toggle_rail_case_js(
        "toggle_from_rendered_collapsed_to_open", toggle_rail_src, apply_rail_mode_src,
        rail_mode="not-a-real-mode-1", current_view="board", inner_width=1600,
        rendered_collapsed=True))
    parts.append(_toggle_rail_case_js(
        "toggle_from_rendered_open_to_collapsed", toggle_rail_src, apply_rail_mode_src,
        rail_mode="not-a-real-mode-2", current_view="board", inner_width=1600,
        rendered_collapsed=False))

    # (d) cr-rail--detail is gated on `collapsed`: forced-collapsed detail
    #     gets the 56px orb; an explicitly EXPANDED detail rail must not.
    parts.append(_apply_rail_mode_case_js(
        "detail_class_present_when_detail_collapsed", apply_rail_mode_src,
        rail_mode="collapsed", current_view="detail", inner_width=1600))
    parts.append(_apply_rail_mode_case_js(
        "detail_class_absent_when_detail_explicitly_expanded", apply_rail_mode_src,
        rail_mode="open", current_view="detail", inner_width=1600))

    parts.append(r"""
console.log("===RAIL_TOGGLE_JSON_START===");
console.log(JSON.stringify(OUT));
""")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# readRailPref() / writeRailPref() (ext_cr_dialogs.js) -- the Config dialog's
# "Session rail" row reads/writes through these, and they must agree with
# ext_cr_board.js's own railMode vocabulary (tri-state 'auto' | 'open' |
# 'collapsed', default/fallback 'auto'). Same brace-matched-real-source idiom
# as _full_driver_js() above; no classList stub needed since neither function
# touches the DOM.
# ---------------------------------------------------------------------------

def _read_rail_pref_case_js(case_id, read_rail_pref_src, stored_value):
    """stored_value=None simulates a 'tracker.rail.mode' key that was never
    written (localStorage.getItem returns null) -- a first-ever page load.
    Any other value simulates that exact string already being stored under
    'tracker.rail.mode' (the getItem stub ignores which key is requested, so
    this also happens to model "no key at all was ever written" for
    stored_value=None -- see _read_rail_pref_legacy_key_only_case_js below
    for the case that distinguishes the two keys)."""
    getitem_body = "return null;" if stored_value is None else ("return %s;" % json.dumps(stored_value))
    return r"""
OUT["%s"] = (function () {
  var localStorage = { getItem: function (k) { %s } };
  %s
  return readRailPref();
})();
""" % (case_id, getitem_body, read_rail_pref_src)


def _read_rail_pref_legacy_key_only_case_js(case_id, read_rail_pref_src):
    """THE MIGRATION GUARANTEE, executed for real: models a browser that has
    ONLY ever written the OLD 'tracker.rail' key (to 'open') and has NEVER
    written the new 'tracker.rail.mode' key readRailPref() actually reads.
    Must resolve to 'auto' -- reading the legacy key as an explicit 'open'
    would hand an existing user a rail state they never asked for. This is
    the whole point of the rename; make it fail loudly if 'tracker.rail' is
    ever read again."""
    return r"""
OUT["%s"] = (function () {
  var localStorage = { getItem: function (k) { return (k === 'tracker.rail') ? 'open' : null; } };
  %s
  return readRailPref();
})();
""" % (case_id, read_rail_pref_src)


def _write_rail_pref_case_js(case_id, write_rail_pref_src, mode_to_write):
    return r"""
OUT["%s"] = (function () {
  var _ctx = null; // writeRailPref optionally emits via _ctx.emit(...); harmless no-op here
  var store = {};
  var localStorage = {
    setItem: function (k, v) { store[k] = v; },
    getItem: function (k) { return (k in store) ? store[k] : null; },
  };
  %s
  writeRailPref(%s);
  return (store['tracker.rail.mode'] !== undefined) ? store['tracker.rail.mode'] : null;
})();
""" % (case_id, write_rail_pref_src, json.dumps(mode_to_write))


def _rail_pref_driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    read_rail_pref_src = _extract_function(bundle, "readRailPref")
    write_rail_pref_src = _extract_function(bundle, "writeRailPref")

    parts = ["var OUT = {};"]

    # (1) a first-ever page load: 'tracker.rail.mode' was never written.
    parts.append(_read_rail_pref_case_js("read_default_is_auto", read_rail_pref_src, None))

    # (2) round-trips each of the three real modes.
    for mode in ("auto", "open", "collapsed"):
        parts.append(_read_rail_pref_case_js("read_roundtrip_%s" % mode, read_rail_pref_src, mode))

    # (3) an unrecognised/garbage stored value falls back to 'auto'.
    parts.append(_read_rail_pref_case_js(
        "read_garbage_falls_back_to_auto", read_rail_pref_src, "not-a-real-mode"))

    # (3b) THE MIGRATION GUARANTEE: only the legacy 'tracker.rail' key was
    # ever written (to 'open') -- must still read back as 'auto'.
    parts.append(_read_rail_pref_legacy_key_only_case_js(
        "read_ignores_legacy_key_and_stays_auto", read_rail_pref_src))

    # (4) writeRailPref persists all three real modes, and coerces garbage to 'auto'.
    for mode in ("auto", "open", "collapsed"):
        parts.append(_write_rail_pref_case_js("write_persists_%s" % mode, write_rail_pref_src, mode))
    parts.append(_write_rail_pref_case_js(
        "write_garbage_coerces_to_auto", write_rail_pref_src, "not-a-real-mode"))

    parts.append(r"""
console.log("===RAIL_TOGGLE_JSON_START===");
console.log(JSON.stringify(OUT));
""")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ext_cr_board.js's mount() `ctx.on('cr:pref', ...)` subscription -- Config's
# "Session rail" row emits this (writeRailPref(), ext_cr_dialogs.js) so the
# LIVE rail actually moves when a user picks a mode in Config, instead of
# only changing what the next chevron click happens to read.
#
# UNLIKE applyRailMode()/toggleRail(), this handler is registered INLINE
# inside mount() rather than being its own top-level named function, so it
# cannot be pulled out with _extract_function() (which brace-matches a
# `function NAME(...) {...}` declaration). _extract_call() works here instead:
# the entire `ctx.on('cr:pref', function (payload) {...});` expression is
# itself one balanced-paren call -- every paren inside the callback body is a
# balanced pair (`(!payload || payload.key !== 'tracker.rail.mode')`,
# `(v === 'open' || v === 'collapsed')`, `applyRailMode()`) -- so paren-depth
# matching from the marker's own `(` captures exactly the call, verbatim from
# the real bundle. Executed against a fake `ctx.on` that just records the
# handler by event name, then invoked directly with synthetic payloads.
# ---------------------------------------------------------------------------

def _cr_pref_subscription_driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    call_src = _extract_call(bundle, "ctx.on('cr:pref'")

    return r"""
var OUT = {};
(function () {
  var REGISTRY = {};
  var ctx = { on: function (name, fn) { REGISTRY[name] = fn; } };
  var railMode = 'unrelated-seed-value';
  var applyRailModeCalls = 0;
  function applyRailMode() { applyRailModeCalls++; }
  // The same subscription now also owns the board-tile-cap repaint (Config's
  // "Board tiles" row -> cr.boardTileCount), so the harness has to supply the
  // two names that branch closes over in mount(): the poll's last state and
  // the board renderer. Both are counted, never asserted by identity.
  var lastState = null;
  var renderBoardCalls = 0;
  function renderBoard(s) { renderBoardCalls++; }

  %s

  function fire(payload, state) {
    railMode = 'unrelated-seed-value';
    applyRailModeCalls = 0;
    renderBoardCalls = 0;
    lastState = (state === undefined) ? null : state;
    REGISTRY['cr:pref'](payload);
    return {
      railModeAfter: railMode,
      applyRailModeCalls: applyRailModeCalls,
      renderBoardCalls: renderBoardCalls,
    };
  }

  OUT['wrong_key_is_ignored'] = fire({ key: 'cr.pollIntervalMs', value: 1000 });
  OUT['missing_payload_is_ignored'] = fire(null);
  // THE BOARD-TILES FIX: Config writes cr.boardTileCount, boardTileCap() reads
  // it fresh -- but before this branch existed nothing repainted, so the slider
  // was a dead control. With a live state the board must re-render exactly once
  // (which also redraws the cap footer, renderBoard -> renderCapFooter), and the
  // rail must be left completely alone.
  OUT['board_tiles_repaints'] = fire({ key: 'cr.boardTileCount', value: 5 }, { sessions: [], now: 0 });
  // ...and before the first poll has landed there is no state to paint from:
  // the branch must no-op rather than throw on a null lastState.
  OUT['board_tiles_without_state_is_safe'] = fire({ key: 'cr.boardTileCount', value: 5 });
  OUT['explicit_open'] = fire({ key: 'tracker.rail.mode', value: 'open' });
  OUT['explicit_collapsed'] = fire({ key: 'tracker.rail.mode', value: 'collapsed' });
  OUT['garbage_coerces_to_auto'] = fire({ key: 'tracker.rail.mode', value: 'not-a-real-mode' });
})();
console.log("===RAIL_TOGGLE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % call_src


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailPrefTriState(unittest.TestCase):
    """Pins readRailPref()/writeRailPref() (ext_cr_dialogs.js, the Config
    dialog's "Session rail" row) against the REAL shipped source.

    THE BUG these pin: ext_cr_dialogs.js used to be two-state
    ('open' | 'collapsed', default 'open'), which (a) made the Config dialog
    MISREPORT the state for a user who had never touched the rail -- it read
    back 'open' when the board's own real default is 'auto' -- and (b) meant
    that once anyone touched the Config row, writeRailPref() coerced anything
    unrecognised to 'open', SILENTLY AND PERMANENTLY destroying the board's
    'auto' default: after one write through the row, 'auto' could never be
    reached again, because the row's own vocabulary had no way to write it.
    """

    @classmethod
    def setUpClass(cls):
        js = _rail_pref_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Rail-pref harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_read_rail_pref_default_is_auto_not_open(self):
        """A first-ever page load (localStorage has never seen
        'tracker.rail.mode') must report 'auto' -- the board's real default
        -- not 'open', the pre-fix two-state default that misreported this
        exact case in Config."""
        self.assertEqual(self.OUT["read_default_is_auto"], "auto")

    def test_read_rail_pref_ignores_legacy_key_and_stays_auto(self):
        """THE MIGRATION GUARANTEE, on the Config-dialog side: a browser
        where only the OLD 'tracker.rail' key was ever written (to 'open')
        must still report 'auto' from readRailPref(), because the new
        'tracker.rail.mode' key it actually reads was never written. If a
        future change "helpfully" reads the legacy key again, this fails
        loudly instead of quietly handing existing users an 'open' rail."""
        self.assertEqual(self.OUT["read_ignores_legacy_key_and_stays_auto"], "auto")

    def test_read_rail_pref_round_trips_all_three_modes(self):
        for mode in ("auto", "open", "collapsed"):
            with self.subTest(mode=mode):
                self.assertEqual(self.OUT["read_roundtrip_%s" % mode], mode)

    def test_read_rail_pref_falls_back_to_auto_for_garbage(self):
        """An unrecognised stored value must fall back to 'auto', matching the
        board's own default -- never silently to 'open'."""
        self.assertEqual(self.OUT["read_garbage_falls_back_to_auto"], "auto")

    def test_write_rail_pref_persists_all_three_modes(self):
        for mode in ("auto", "open", "collapsed"):
            with self.subTest(mode=mode):
                self.assertEqual(self.OUT["write_persists_%s" % mode], mode)

    def test_write_rail_pref_coerces_garbage_to_auto_not_open(self):
        """THE BUG, precisely: writeRailPref() must coerce an unrecognised mode
        to 'auto', not 'open'. The pre-fix two-state coercion
        (`mode = (mode === 'collapsed') ? 'collapsed' : 'open'`) meant ANY
        write through the Config row destroyed 'auto' permanently -- there was
        no longer any value the row could write that got the user back to it."""
        self.assertEqual(self.OUT["write_garbage_coerces_to_auto"], "auto")


class TestRailPrefConfigRowAndVocabulary(unittest.TestCase):
    """Static structural pins on the Config dialog's "Session rail" row and on
    the rail-mode vocabulary shared between ext_cr_dialogs.js and
    ext_cr_board.js. No JS execution needed -- same brace/paren-matched
    real-source extraction as the rest of this file, asserted on directly.
    """

    @classmethod
    def setUpClass(cls):
        html = _read_page()
        bundle = _extract_script_content(html)
        cls.session_rail_row_src = _extract_call(bundle, "cfgRow('Session rail'")
        cls.read_rail_pref_src = _extract_function(bundle, "readRailPref")
        cls.write_rail_pref_src = _extract_function(bundle, "writeRailPref")
        cls.apply_rail_mode_src = _extract_function(bundle, "applyRailMode")
        cls.toggle_rail_src = _extract_function(bundle, "toggleRail")
        cls.default_railmode_stmt = _extract_statement(bundle, "railMode")

    def test_config_session_rail_row_offers_all_three_options(self):
        """THE BUG's other half: the Config dialog's "Session rail" row used to
        be wired to a two-state toggleCtl (Open/Collapsed only, via a boolean),
        with no way to pick 'auto' at all -- so a user could never get back to
        the board's real default once they'd looked at Config. Pins that the
        shipped row is wired to the tri-state `segmented` control carrying
        auto/open/collapsed, not toggleCtl."""
        row = self.session_rail_row_src
        self.assertIn(
            "segmented(", row,
            "the 'Session rail' Config row is no longer wired to segmented() -- "
            "if it's back on toggleCtl(), 'auto' has no UI path again")
        self.assertNotIn(
            "toggleCtl(", row,
            "the 'Session rail' row reverted to the two-state toggleCtl() control")
        for label in ("'auto'", "'open'", "'collapsed'"):
            self.assertIn(
                label, row,
                "the 'Session rail' row's segmented control is missing the %s option" % label)

    def test_rail_mode_vocabulary_agrees_across_both_files(self):
        """DRIFT GUARD: ext_cr_dialogs.js (readRailPref/writeRailPref) and
        ext_cr_board.js (applyRailMode/toggleRail/the module-level default)
        must recognise EXACTLY the same set of rail-mode strings.

        THE BUG was precisely this disagreement: ext_cr_dialogs.js's
        vocabulary used to be {'open', 'collapsed'} while ext_cr_board.js's was
        {'auto', 'open', 'collapsed'} -- 'auto' had no representation on the
        Config side at all. If a future change adds a fourth mode to only one
        file, or reverts either side back to two-state, the two extracted sets
        stop matching and this fails with both sets printed, naming exactly
        which file is missing what.
        """
        dialogs_modes = (
            _mode_literals_on_lines_mentioning(self.read_rail_pref_src, "v")
            | _mode_literals_on_lines_mentioning(self.write_rail_pref_src, "mode")
        )
        board_modes = _mode_literals_on_lines_mentioning(
            self.apply_rail_mode_src + "\n" + self.toggle_rail_src + "\n" + self.default_railmode_stmt,
            "railMode",
        )
        self.assertTrue(
            dialogs_modes,
            "extraction found no rail-mode literals in readRailPref()/writeRailPref() "
            "at all -- the extraction technique likely needs updating for a source shape change")
        self.assertTrue(
            board_modes,
            "extraction found no rail-mode literals in applyRailMode()/toggleRail()/the "
            "default statement at all -- the extraction technique likely needs updating "
            "for a source shape change")
        self.assertEqual(
            dialogs_modes, board_modes,
            "ext_cr_dialogs.js (readRailPref/writeRailPref) and ext_cr_board.js "
            "(applyRailMode/toggleRail/the default) disagree on the rail-mode "
            "vocabulary:\n"
            "  ext_cr_dialogs.js accepts:    %r\n"
            "  ext_cr_board.js understands:  %r\n"
            "This is the exact shape of the original bug (dialogs.js two-state, "
            "board.js tri-state) -- both files must always recognise the "
            "identical set of modes."
            % (sorted(dialogs_modes), sorted(board_modes))
        )


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailToggleNotADeadControl(unittest.TestCase):
    """Pins applyRailMode()/toggleRail() behaviour against the REAL, currently
    shipped source (brace-matched out of the assembled page's bundle), not a
    hand-retyped paraphrase of it."""

    @classmethod
    def setUpClass(cls):
        js = _full_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Rail-toggle harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    # -- (a) explicit railMode beats the old unconditional OR of isDetail / tier --

    def test_explicit_open_beats_detail_view_force(self):
        """The bug, precisely: in the detail view, an explicit 'open' choice
        must render EXPANDED. Under the old `collapsed = isDetail || ...`
        formula this was unconditionally True regardless of railMode -- the
        exact reason the toggle did nothing in the detail view."""
        r = self.OUT["explicit_open_beats_detail_force"]
        self.assertFalse(r["collapsed"])

    def test_explicit_open_beats_1025_1279_tier_force(self):
        """Same bug, the other forced zone: an explicit 'open' choice must
        win at 1100px (inside the 1025-1279 auto-collapse tier) too."""
        r = self.OUT["explicit_open_beats_tier_force"]
        self.assertFalse(r["collapsed"])

    def test_explicit_collapsed_still_collapses_outside_forced_zone(self):
        """Sanity check on the other side: an explicit 'collapsed' choice
        must still collapse the rail even at a width/view neither force ever
        applied to (1600px, board view) -- the fix must not have simply
        disabled collapsing altogether."""
        r = self.OUT["explicit_collapsed_applies_outside_forced_zone"]
        self.assertTrue(r["collapsed"])

    # -- (b) tri-state default is 'auto', not 'open' -----------------------

    def test_default_railmode_is_auto_not_open(self):
        """Executes railMode's own default-value initializer for real, against
        a localStorage that has never seen 'tracker.rail.mode' (a first-ever
        page load). Must resolve to 'auto', not the pre-fix default 'open'."""
        self.assertEqual(self.OUT["default_railmode_is_auto"], "auto")

    def test_default_railmode_ignores_legacy_key_and_stays_auto(self):
        """THE MIGRATION GUARANTEE, precisely: a browser where only the OLD
        'tracker.rail' key was ever written (to 'open') must still resolve
        railMode to 'auto', because the new 'tracker.rail.mode' key was
        never written. Reading the legacy key as an explicit 'open' would
        hand an existing user an expanded rail in the detail view they never
        asked for -- this is the entire reason for the key rename, so this
        must fail loudly if the legacy key is ever read again."""
        self.assertEqual(self.OUT["default_railmode_ignores_legacy_key"], "auto")

    def test_auto_mode_still_defers_to_detail_force(self):
        """Unlike explicit 'open' (which now wins, per test above), the
        'auto' mode must still collapse in the detail view -- otherwise the
        fix would have just turned the forced conditions off entirely instead
        of making them overridable."""
        r = self.OUT["auto_mode_still_follows_detail_force"]
        self.assertTrue(r["collapsed"])

    def test_auto_mode_still_defers_to_1025_1279_tier_force(self):
        r = self.OUT["auto_mode_still_follows_tier_force"]
        self.assertTrue(r["collapsed"])

    # -- (c) toggleRail derives from the RENDERED class, not the stored value --

    def test_toggle_rail_reads_rendered_class_not_stored_value(self):
        """`railMode` is deliberately seeded with a value that is neither
        'open' nor 'collapsed' (garbage left over from -- in spirit -- the
        old two-state world) so that a same-as-before result can't disguise a
        wrong wiring: the outcome must be determined ENTIRELY by what's
        rendered right now (`cr-rail--collapsed`), which is exactly the fix
        for 'auto' mode's stored/rendered mismatch producing a dead click."""
        collapsed_to_open = self.OUT["toggle_from_rendered_collapsed_to_open"]
        self.assertEqual(collapsed_to_open["railModeAfter"], "open")
        self.assertEqual(collapsed_to_open["storedAfter"], "open")
        self.assertFalse(collapsed_to_open["collapsedAfter"])

        open_to_collapsed = self.OUT["toggle_from_rendered_open_to_collapsed"]
        self.assertEqual(open_to_collapsed["railModeAfter"], "collapsed")
        self.assertEqual(open_to_collapsed["storedAfter"], "collapsed")
        self.assertTrue(open_to_collapsed["collapsedAfter"])

    # -- (d) cr-rail--detail (56px orb) gated on `collapsed` -----------------

    def test_detail_orb_class_present_only_when_actually_collapsed(self):
        collapsed_case = self.OUT["detail_class_present_when_detail_collapsed"]
        self.assertTrue(collapsed_case["collapsed"])
        self.assertTrue(collapsed_case["detail"])

    def test_detail_orb_class_absent_when_detail_explicitly_expanded(self):
        """The other half of the same gate: an explicitly EXPANDED detail
        rail must NOT carry the 56px orb styling -- it should get the full
        232px row rail instead. Before this fix, `cr-rail--detail` was
        applied whenever isDetail alone, with no dependency on `collapsed`."""
        expanded_case = self.OUT["detail_class_absent_when_detail_explicitly_expanded"]
        self.assertFalse(expanded_case["collapsed"])
        self.assertFalse(expanded_case["detail"])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardSubscribesToConfigPrefChanges(unittest.TestCase):
    """Pins that ext_cr_board.js's mount() actually subscribes to the shared
    'cr:pref' bus event, wired to 'tracker.rail.mode' and applyRailMode() --
    against the REAL shipped source (paren-matched out of the bundle via
    _extract_call(), same honest-extraction idiom as the rest of this file),
    not a hand-retyped paraphrase of it.

    THE BUG this closes: before this subscription existed, `railMode` was a
    closure variable read ONCE at mount time. Picking a mode in Config's
    "Session rail" row called writeRailPref() (ext_cr_dialogs.js), which
    wrote localStorage and emitted 'cr:pref' -- but nothing on the board was
    listening, so nothing on screen moved. The NEXT chevron click
    (toggleRail(), which reads the RENDERED class and writes) then silently
    overwrote the user's Config choice. Same dead-control bug the whole
    tri-state change exists to remove, on a different door.
    """

    @classmethod
    def setUpClass(cls):
        js = _cr_pref_subscription_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "cr:pref subscription harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_ignores_a_payload_for_a_different_config_key(self):
        """The handler must filter on `payload.key` -- a 'cr:pref' emission
        for an unrelated Config row (e.g. the poll-interval control) must
        not touch railMode, and must not repaint the board either."""
        r = self.OUT["wrong_key_is_ignored"]
        self.assertEqual(r["railModeAfter"], "unrelated-seed-value")
        self.assertEqual(r["applyRailModeCalls"], 0)
        self.assertEqual(r["renderBoardCalls"], 0)

    def test_board_tile_count_repaints_the_board(self):
        """THE BOARD-TILES FIX, precisely: Config's "Board tiles" slider
        writes cr.boardTileCount and boardTileCap() already read it fresh --
        but nothing repainted on the write, so moving the slider changed a
        number in localStorage and left the board on screen untouched. The
        subscription must re-render the board (which redraws the cap footer
        with it) and must not disturb the rail."""
        r = self.OUT["board_tiles_repaints"]
        self.assertEqual(r["renderBoardCalls"], 1)
        self.assertEqual(r["railModeAfter"], "unrelated-seed-value")
        self.assertEqual(r["applyRailModeCalls"], 0)

    def test_board_tile_count_without_a_state_does_not_throw(self):
        """Edge case: the pref can be changed before the first poll has
        landed, so lastState is still null. The branch must no-op rather
        than throw (a throw here would kill the whole cr:pref handler, taking
        the rail-mode row down with it)."""
        r = self.OUT["board_tiles_without_state_is_safe"]
        self.assertEqual(r["renderBoardCalls"], 0)
        self.assertEqual(r["railModeAfter"], "unrelated-seed-value")

    def test_ignores_a_missing_payload(self):
        r = self.OUT["missing_payload_is_ignored"]
        self.assertEqual(r["railModeAfter"], "unrelated-seed-value")
        self.assertEqual(r["applyRailModeCalls"], 0)

    def test_applies_explicit_open_and_calls_applyRailMode(self):
        """THE FIX, precisely: an 'open' picked in Config must update the
        board's own `railMode` AND call applyRailMode() so it actually
        renders -- not just sit in localStorage until the next click."""
        r = self.OUT["explicit_open"]
        self.assertEqual(r["railModeAfter"], "open")
        self.assertEqual(r["applyRailModeCalls"], 1)

    def test_applies_explicit_collapsed_and_calls_applyRailMode(self):
        r = self.OUT["explicit_collapsed"]
        self.assertEqual(r["railModeAfter"], "collapsed")
        self.assertEqual(r["applyRailModeCalls"], 1)

    def test_coerces_unrecognised_value_to_auto_not_open(self):
        """The handler's own coercion must match applyRailMode()'s tri-state
        vocabulary: an unrecognised value lands on 'auto', never on 'open' --
        a stray/garbage payload value must not be able to silently expand
        the rail."""
        r = self.OUT["garbage_coerces_to_auto"]
        self.assertEqual(r["railModeAfter"], "auto")
        self.assertEqual(r["applyRailModeCalls"], 1)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# RAIL PARITY WITH THE CLASSIC SIDEBAR (owner ask: the rail must be "the same
# size width" as the old default view and "in absolute feature parity ...
# including the information present in there").
#
# Two halves are pinned here:
#   1. railRowMeta() no longer swallows metadata. It used to `return` on the
#      FIRST truthy of open_flags / bg / age, so a FLAGGED row silently lost
#      its age and a row with background agents lost it too -- while the
#      classic sidebar (app.js sessionRow) shows the flag badge, the note
#      badge, the agent chip AND the age all at once.
#   2. The rail width is one variable (--cr-rail-w) set to the classic
#      sidebar's own 300px, read by every rule that sets a rail width, so the
#      three rules can never drift apart again.
# ---------------------------------------------------------------------------

def _rail_row_meta_driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    fn_src = _extract_function(bundle, "railRowMeta")

    return r"""
var OUT = {};
(function () {
  // railRowMeta()'s only dependency is app.js's own `ago()` string builder --
  // stubbed to a fixed sentinel so an assertion about "the age is present"
  // can never be satisfied by some other number that happens to appear.
  function ago(sec) { return 'AGE'; }

  %s

  var NOW = 1000;
  OUT['plain']        = railRowMeta({ mtime: NOW }, NOW);
  OUT['flagged']      = railRowMeta({ mtime: NOW, open_flags: 2 }, NOW);
  OUT['noted']        = railRowMeta({ mtime: NOW, note_count: 3 }, NOW);
  OUT['bg']           = railRowMeta({ mtime: NOW, bg: 4 }, NOW);
  OUT['all_at_once']  = railRowMeta({ mtime: NOW, open_flags: 2, note_count: 3, bg: 4 }, NOW);
})();
console.log("===RAIL_TOGGLE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % fn_src


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRailRowMetaParity(unittest.TestCase):
    """THE BUG: railRowMeta() returned early on the first truthy field, so a
    flagged rail row showed ONLY its flag count -- no age, no note count, no
    background-agent count. The classic sidebar shows all of them together."""

    @classmethod
    def setUpClass(cls):
        js = _rail_row_meta_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "railRowMeta harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_plain_row_still_shows_only_the_age(self):
        """The unchanged base case: nothing to report but recency."""
        self.assertEqual(self.OUT["plain"], "AGE")

    def test_a_flagged_row_keeps_its_age(self):
        """THE REGRESSION, precisely: before the fix this returned the flag
        count ALONE and the age vanished from the row."""
        r = self.OUT["flagged"]
        self.assertIn("2", r)
        self.assertIn("AGE", r)

    def test_a_noted_row_shows_the_note_count_and_the_age(self):
        """Note counts were tooltip-only in the rail; classic shows a visible
        badge, so parity means the count reaches the row itself."""
        r = self.OUT["noted"]
        self.assertIn("3", r)
        self.assertIn("AGE", r)

    def test_a_background_agent_row_keeps_its_age(self):
        r = self.OUT["bg"]
        self.assertIn("4", r)
        self.assertIn("AGE", r)

    def test_everything_at_once_is_all_present(self):
        """The whole point of parity: flags, notes, agents and age coexist on
        one row rather than the first one winning and hiding the rest."""
        r = self.OUT["all_at_once"]
        for expected in ("2", "3", "4", "AGE"):
            self.assertIn(expected, r)


class TestRailWidthMatchesClassicSidebar(unittest.TestCase):
    """The owner asked for the rail to be "the same size width" as the old
    default view. The classic sidebar is `.side{width:300px}` (app.css)."""

    def test_rail_width_variable_is_the_classic_sidebar_width(self):
        page = _read_page()
        self.assertIn("--cr-rail-w: 300px", page)

    def test_no_rule_still_hardcodes_the_old_rail_width(self):
        """Three separate rules set a rail width (open, mobile overlay, and
        the overlay's "collapsed is still the full row rail" case). They must
        all read the variable -- a leftover literal is exactly how they drift."""
        page = _read_page()
        self.assertNotIn("width: 232px", page)

    def test_status_badge_is_styled_for_both_states(self):
        """Colour never carries meaning alone here, but an unstyled badge would
        still inherit muted body text and read as noise -- pin both classes."""
        page = _read_page()
        self.assertIn("cr-rail-status--waiting", page)
        self.assertIn("cr-rail-status--done", page)


# ---------------------------------------------------------------------------
# BOARD FILTER vs AGENT-GROUP TILES.
#
# THE BUGS (one line carried both): the group branch of passesFilter() read
# `t.session.open_flags`, but an agent-group tile has no `.session` at all --
# it aggregates several under `.sessions` (plural). So:
#   1. the 'flagged' filter threw a TypeError as soon as any group tile was on
#      the board, and
#   2. every other filter returned a flat false, hiding the grouped sessions
#      from 'awaiting'/'working' -- even though triageCounts() counts exactly
#      those sessions in the strip above. A cell could read "1 WORKING" and
#      still render "Nothing matches that filter right now."
# ---------------------------------------------------------------------------

def _passes_filter_driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    fn_src = _extract_function(bundle, "passesFilter")

    return r"""
var OUT = {};
(function () {
  var activeFilter = null;
  var lastState = { now: 1000 };
  // The real sessionState() vocabulary, reduced to what these cases need.
  function sessionState(s, now) {
    if (s.waiting) return 'awaiting';
    if (s.open_flags) return 'flagged';
    if (!s.ended) return 'working';
    return 'idle';
  }

  %s

  function run(filter, tile) {
    activeFilter = filter;
    try { return { ok: passesFilter(tile, 1000) }; }
    catch (e) { return { threw: String(e && e.message || e) }; }
  }

  var groupWorking = { kind: 'agent-group', group: 'g1',
                       sessions: [{ ended: false }], mtime: 1000, pinned: false };
  var groupFlagged = { kind: 'agent-group', group: 'g2',
                       sessions: [{ open_flags: 2, ended: true }], mtime: 1000, pinned: false };
  var groupIdle    = { kind: 'agent-group', group: 'g3',
                       sessions: [{ ended: true }], mtime: 1000, pinned: false };
  var soloWorking  = { kind: 'session', state: 'working', session: { ended: false } };

  OUT['group_flagged_under_flagged'] = run('flagged', groupFlagged);
  OUT['group_working_under_working'] = run('working', groupWorking);
  OUT['group_idle_under_working']    = run('working', groupIdle);
  OUT['solo_working_under_working']  = run('working', soloWorking);
  OUT['no_filter_passes_group']      = run(null, groupWorking);
})();
console.log("===RAIL_TOGGLE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % fn_src


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardFilterHandlesAgentGroupTiles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _passes_filter_driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "passesFilter harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_flagged_filter_does_not_throw_on_a_group_tile(self):
        """BUG 1: `t.session.open_flags` on a tile whose sessions live under
        `.sessions` is a TypeError, not a false -- it took the whole render
        down rather than merely filtering the tile out."""
        r = self.OUT["group_flagged_under_flagged"]
        self.assertNotIn("threw", r, "flagged filter threw on a group tile: %r" % (r,))
        self.assertTrue(r["ok"])

    def test_working_filter_surfaces_a_group_with_a_working_member(self):
        """BUG 2: the strip counts the grouped sessions, so the filter has to
        be able to show them -- otherwise the count and the board disagree."""
        r = self.OUT["group_working_under_working"]
        self.assertNotIn("threw", r)
        self.assertTrue(r["ok"])

    def test_working_filter_still_excludes_a_group_with_no_working_member(self):
        """The fix must not turn into "every group always passes"."""
        r = self.OUT["group_idle_under_working"]
        self.assertNotIn("threw", r)
        self.assertFalse(r["ok"])

    def test_individual_session_tiles_are_unaffected(self):
        r = self.OUT["solo_working_under_working"]
        self.assertTrue(r["ok"])

    def test_no_active_filter_still_passes_everything(self):
        r = self.OUT["no_filter_passes_group"]
        self.assertTrue(r["ok"])
