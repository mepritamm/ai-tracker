"""Control Room pending-work tile (plan v3.1 step 13).

Drives the REAL page.build_page() bundle under node: the tile renders from the
server `card` only when card.show and no filter is active, sits outside the
boardTiles cap, opens the shared list modal on click, and the `t` shortcut
resolves the focused tile by id (not DOM index) now that the tile is prepended.
"""
import json
import os
import re
import unittest

from tests.test_working_glow_board import (
    _HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node, make_session,
)

NOW = 1_800_000_000
MARK = "===PENDING_BOARD_JSON==="
_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")

_PRE = r"""
window.localStorage.setItem('tracker.ui', 'next');
var __kd = null;
document.addEventListener = function (t, fn) { if (t === 'keydown') __kd = fn; };
dummy.contains = function () { return false; };
"""

_DRIVER = r"""
var __o = {};
var __opened = [];
openPendingList = function (r) { __opened.push(r); };   // app.js's real function, replaced to observe the call
pendingCache = { card: { show: true, title: 'Pending work', summary: '3 items', as_of: '2026-11-01' } };
var __sess = __SESSIONS__;
var __emitted = [];
var ctx = { emit: function (n, p) { __emitted.push([n, p]); }, readOnly: function () { return false; } };
var root = makeReal('div'); root.isConnected = true; docBody.appendChild(root);
window.CR.board.mount(root, ctx);
// The harness's querySelectorAll only understands '.class'; the keyboard handler asks for '[data-tile-id]'.
var __board = queryAllReal(root, '.cr-board')[0];
__board.querySelectorAll = function () { return tiles(); };
function tiles() { return queryAllReal(root, '.cr-tile'); }
function render(pending) { window.CR.board.update({ sessions: __sess, now: __NOW__, pending: pending }); }

try {
  render(pendingCache);
  var ts = tiles();
  __o.firstIsPending = ts[0] && ts[0]._classes.has('cr-tile--pending');
  __o.span2 = ts[0] && ts[0]._classes.has('cr-tile--span2');
  __o.ownGridColumn = JSON.stringify(ts[0] && ts[0].style).indexOf('grid') >= 0;
  __o.text = ts[0] ? allTextIn(ts[0]) : '';
  __o.pendingCount = ts.filter(function (t) { return t._classes.has('cr-tile--pending'); }).length;
  __o.sessionTiles = ts.length - __o.pendingCount;

  ts[0]._listeners.click({ target: { closest: function () { return null; } } });
  __o.opened = __opened.length;

  // `t` on the 2nd session tile: DOM index is 2 (pending is index 0), boardTiles index is 1.
  var second = tiles()[2];
  var sid = second._attrs['data-tile-id'];
  second._listeners.focus && second._listeners.focus();
  __kd({ key: 't', target: second, preventDefault: function () {} });
  __o.termOpen = __emitted.filter(function (e) { return e[0] === 'terminal:open'; }).map(function (e) { return e[1].id; });
  __o.expectedSid = sid;
  // `t` on the pending tile opens no terminal.
  __emitted.length = 0;
  tiles()[0]._listeners.focus && tiles()[0]._listeners.focus();
  __kd({ key: 't', target: tiles()[0], preventDefault: function () {} });
  __o.termOnPending = __emitted.filter(function (e) { return e[0] === 'terminal:open'; }).length;

  render({ card: { show: true, title: 'Pending work', summary: '3 items' } });
  __o.textNoAsOf = allTextIn(tiles()[0]);
  render({ card: { show: false, title: 'x', summary: 'y' } });
  __o.hiddenWhenNotShow = tiles().filter(function (t) { return t._classes.has('cr-tile--pending'); }).length;
  render(null);
  __o.hiddenWhenNull = tiles().filter(function (t) { return t._classes.has('cr-tile--pending'); }).length;

  window.CR.board.setFilter('working');
  render(pendingCache);
  __o.hiddenWhenFiltered = tiles().filter(function (t) { return t._classes.has('cr-tile--pending'); }).length;
  console.log(__MARK__);
  console.log(JSON.stringify(__o));
} catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
"""

_MID = r"""
} catch (e) { console.error("BUNDLE-THREW: " + (e && e.stack || e)); process.exit(1); }
"""


def _run():
    sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i, waiting=True, ended=False) for i in range(3)]
    drv = _DRIVER.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW)).replace("__MARK__", json.dumps(MARK))
    rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _PRE, _bundle_js(), drv, _MID]))
    if rc != 0:
        raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
    return _extract_marker_json(out, MARK)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestPendingBoardTile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_pending_tile_first_span2_with_server_text(self):
        self.assertTrue(self.O["firstIsPending"])
        self.assertTrue(self.O["span2"])
        self.assertFalse(self.O["ownGridColumn"])
        self.assertIn("Pending work", self.O["text"])
        self.assertIn("3 items", self.O["text"])
        self.assertEqual(self.O["pendingCount"], 1)
        self.assertIn("as of 2026-11-01", self.O["text"])
        self.assertNotIn("as of", self.O["textNoAsOf"])
        self.assertEqual(self.O["sessionTiles"], 3)

    def test_click_opens_shared_list_modal(self):
        self.assertEqual(self.O["opened"], 1)

    def test_t_key_resolves_by_id_not_dom_index(self):
        self.assertEqual(self.O["termOpen"], [self.O["expectedSid"]])
        self.assertEqual(self.O["termOnPending"], 0)

    def test_hidden_unless_show_and_unfiltered(self):
        self.assertEqual(self.O["hiddenWhenNotShow"], 0)
        self.assertEqual(self.O["hiddenWhenNull"], 0)
        self.assertEqual(self.O["hiddenWhenFiltered"], 0)


class TestPendingTokensAndHook(unittest.TestCase):
    def _read(self, n):
        with open(os.path.join(_WEB, n), encoding="utf-8") as f:
            return f.read()

    def test_tokens_in_both_theme_blocks_no_color_mix(self):
        css = self._read("ext_cr.css")
        for tok in ("--state-pending", "--surface-pending", "--line-pending"):
            self.assertEqual(len(re.findall(re.escape(tok) + r"\s*:", css)), 2, tok)
        self.assertNotIn("color-mix", self._read("ext_cr_board.css"))
        self.assertNotIn("grid-column", re.search(r"\.cr-tile--pending\s*\{[^}]*\}", self._read("ext_cr_board.css")).group(0))



_SIDE_PRE = _PRE + r"""
var __nr = makeReal('div'); __nr.id = 'nextRoot'; docBody.appendChild(__nr);   // the page's #nextRoot the boot file mounts into
var __timers = [];
window.setTimeout = function (f) { __timers.push(f); return 0; };   // let ext_cr_boot.js's deferred init() run on demand
"""

_SIDE_DRIVER = r"""
var __o = {};
try {
  while (__timers.length) { (__timers.shift())(); }                // init() -> real mount of the Control Room
  sessions = __SESSIONS__; listNow = __NOW__;
  function pend() { return queryAllReal(docBody, '.cr-tile--pending'); }
  __o.tilesBefore = pend().length;                                // nothing fetched yet
  trackerReadOnly = false;
  pendingCache = { card: { show: true, title: 'Pending work', summary: '7 items', as_of: '2026-11-02' } };
  SIDE_EXT.forEach(function (f) { f(); });                        // the REAL loadSide() hook list, ext_cr_boot.js's closure included
  __o.tilesAfter = pend().length;
  __o.text = pend()[0] ? allTextIn(pend()[0]) : '';
  pendingCache = { card: { show: false, title: 'x', summary: 'y' } };
  SIDE_EXT.forEach(function (f) { f(); });
  __o.tilesHidden = pend().length;
  console.log(__MARK__);
  console.log(JSON.stringify(__o));
} catch (e) { console.error('DRIVER-THREW: ' + (e && e.stack || e)); process.exit(1); }
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestPendingThroughSideHook(unittest.TestCase):
    """E3-N10: replaces a source grep for "pending:" -- drives the real SIDE_EXT hook and asserts the tile."""

    def test_side_hook_renders_pending_tile(self):
        sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i, waiting=True, ended=False) for i in range(2)]
        drv = _SIDE_DRIVER.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW)).replace("__MARK__", json.dumps(MARK))
        rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _SIDE_PRE, _bundle_js(), drv, _MID]))
        if rc != 0:
            raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
        o = _extract_marker_json(out, MARK)
        self.assertEqual(o["tilesBefore"], 0)
        self.assertEqual(o["tilesAfter"], 1)
        self.assertIn("7 items", o["text"])
        self.assertIn("as of 2026-11-02", o["text"])
        self.assertEqual(o["tilesHidden"], 0)


if __name__ == "__main__":
    unittest.main()
