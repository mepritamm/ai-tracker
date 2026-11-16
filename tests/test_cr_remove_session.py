"""Remove-session front end (ext_cr_board.js): buttons, sticky removal overlay, Cmd/Ctrl+Z undo.

Drives the REAL page.build_page() bundle in the node DOM harness from test_working_glow_board, with ONE
mount (the removed-id stack is module state, so a second mount would double-pop). Every keydown listener
the page registers is collected and each synthetic event is dispatched to all of them (try/catch each).
The stub DOM does not bubble, so stopPropagation is proven with a spy on the event object. Sub-cases a-l
map to reports/remove-session-plan.md (T5 + v2 amendments F1-F6).
"""
import json
import os
import re
import unittest

from tests.test_working_glow_board import (
    _HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node, make_session,
)

NOW = 1_800_000_000
MARK = "===CR_REMOVE_SESSION_JSON==="
_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")

_PRE = r"""
window.localStorage.setItem('tracker.ui', 'next');
var __KD = [];
document.addEventListener = function (t, fn) { if (t === 'keydown') __KD.push(fn); };
dummy.contains = function () { return false; };
"""

_DRIVER = r"""
function __flush() { return new Promise(function (r) { setImmediate(r); }); }
var __fx = __SESSIONS__;
var __o = {};
var fetched = [], emitted = [], gone = [], handlers = {}, searchHits = [], failHide = false, ro = false, sideCalls = 0;
window.fetch = function (url, opts) {
  fetched.push([url, opts && opts.body ? JSON.parse(opts.body) : null]);
  if (url.indexOf('/api/hide') === 0 && failHide) return Promise.resolve({ ok: false, json: function () { return Promise.resolve({}); } });
  if (url.indexOf('/api/search') === 0) return Promise.resolve({ ok: true, json: function () { return Promise.resolve(searchHits); } });
  return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } });
};
loadSide = function () { sideCalls++; };
var ctx = { emit: function (n, p) { emitted.push([n, p]); }, readOnly: function () { return ro; },
            go: function (v, id) { gone.push([v, id]); },
            on: function (n, fn) { (handlers[n] = handlers[n] || []).push(fn); } };
var root = makeReal('div'); root.isConnected = true; docBody.appendChild(root);
window.CR.board.mount(root, ctx);
var rail = queryAllReal(root, '.cr-rail')[0];
var sList = queryAllReal(root, '.cr-sessions-list')[0];
function full() { window.CR.board.update({ sessions: __fx.slice(), now: __NOW__ }); }
function hides() { return fetched.filter(function (f) { return f[0] === '/api/hide'; }).map(function (f) { return f[1]; }); }
function toasts() { return emitted.filter(function (e) { return e[0] === 'notify'; }).map(function (e) { return e[1]; }); }
function key(ev) {
  var pd = 0; ev.preventDefault = function () { pd++; };
  __KD.forEach(function (f) { try { f(ev); } catch (_) {} });
  return pd;
}
function cmdZ(target, extra) { return key(Object.assign({ key: 'z', metaKey: true, target: target || docBody }, extra || {})); }
function spyEvt() { var e = { n: 0, stopPropagation: function () { e.n++; } }; return e; }
function tileOf(id) { return findByAttr(root, 'data-tile-id', id); }
function clickRemoveTile(id) { var b = findByAttr(tileOf(id), 'data-act', 'remove'); var e = spyEvt(); b._listeners.click(e); return e; }
async function reset() {
  ro = false; failHide = false; searchHits = [];
  for (var i = 0; i < 10; i++) { var n = fetched.length; cmdZ(); await __flush(); await __flush(); if (fetched.length === n) break; }
  uiState.set('query', ''); await __flush();
  fetched.length = 0; emitted.length = 0; gone.length = 0; full();
}

(async function () {
  try {
    window.setTimeout = function (fn) { fn(); return 0; };   // collapse the search debounce (after mount)
    (handlers['view:changed'] || []).forEach(function (f) { f({ view: 'sessions' }); });
    full();

    // a: rich Sessions rows and the board tile carry the button; the compact rail does not
    __o.a = {
      richBtns: queryAllReal(sList, '.cr-rail-remove').length,
      richRows: queryAllReal(sList, '.cr-rail-row').length,
      tileBtn: !!findByAttr(tileOf('s1'), 'data-act', 'remove'),
      railBtns: queryAllReal(rail, '.cr-rail-remove').length,
      railRows: queryAllReal(rail, '.cr-rail-row').length,
    };

    // c: read-only viewers get no remove control anywhere
    ro = true; full();
    __o.c = { rail: queryAllReal(root, '.cr-rail-remove').length, tile: !!findByAttr(tileOf('s1'), 'data-act', 'remove'),
              anyAct: !!findByAttr(root, 'data-act', 'remove') };
    ro = false; full();

    // b: tile click -> POST hidden:true, stopPropagation, toast
    var ev = clickRemoveTile('s1'); await __flush(); await __flush();
    __o.b = { hides: hides(), stopped: ev.n, toasts: toasts().map(function (t) { return [t.title, t.actionLabel, typeof t.onAction]; }),
              sideCalls: sideCalls };

    // d: Cmd+Z pops the NEWEST first, preventDefault only when it acted
    clickRemoveTile('s2'); await __flush(); await __flush();
    var pd1 = cmdZ(); await __flush(); await __flush();
    var h1 = hides().slice(-1)[0];
    var pd2 = cmdZ(null, { metaKey: false, ctrlKey: true, key: 'Z' }); await __flush(); await __flush();
    __o.d = { pd1: pd1, h1: h1, pd2: pd2, h2: hides().slice(-1)[0] };
    await reset();

    // e: blocked targets leave the stack and the network alone
    clickRemoveTile('s1'); await __flush(); await __flush();
    var n0 = fetched.length;
    var pdIn = cmdZ({ tagName: 'INPUT' }, { metaKey: false, ctrlKey: true });
    var pdTerm = cmdZ({ tagName: 'DIV', closest: function (sel) { return /xterm|cr-term-root/.test(sel) ? {} : null; } }, { metaKey: false, ctrlKey: true });
    var oq = document.querySelector;
    document.querySelector = function (s) { return /cr-dialog-layer/.test(s) ? {} : null; };
    var pdDlg = cmdZ();
    document.querySelector = oq;
    await __flush();
    var blockedFetches = fetched.length - n0;
    var pdOk = cmdZ(); await __flush(); await __flush();
    __o.e = { pdIn: pdIn, pdTerm: pdTerm, pdDlg: pdDlg, blockedFetches: blockedFetches, pdOk: pdOk, then: hides().slice(-1)[0] };
    await reset();

    // m: every key/target/visibility guard is individually load-bearing
    clickRemoveTile('s1'); await __flush(); await __flush();
    var nm = fetched.length; var mpd = [];
    mpd.push(cmdZ(null, { shiftKey: true }));
    mpd.push(cmdZ(null, { repeat: true }));
    mpd.push(cmdZ(null, { altKey: true }));
    mpd.push(key({ key: 'y', ctrlKey: true, target: docBody }));
    mpd.push(cmdZ({ tagName: 'TEXTAREA', className: 'xterm-helper-textarea' }));
    mpd.push(cmdZ({ tagName: 'SELECT' }));
    mpd.push(cmdZ({ tagName: 'DIV', isContentEditable: true }));
    ['#cr-term-root', '#vtmodal', '#vtmgrmodal', '.vtpane', '.xterm'].forEach(function (X) {
      // matches only when X is itself one of the selectors passed to closest()
      mpd.push(cmdZ({ tagName: 'DIV', closest: function (sel) { return String(sel).split(',').map(function (q) { return q.trim(); }).indexOf(X) >= 0 ? {} : null; } }));
    });
    var ogid = document.getElementById;
    document.getElementById = function (i) { return i === 'nextRoot' ? { hidden: true } : ogid.call(document, i); };
    mpd.push(cmdZ());
    document.getElementById = ogid;
    await __flush(); await __flush();
    var mfetch = fetched.length - nm;
    var mok = cmdZ(); await __flush(); await __flush();
    __o.m = { pds: mpd, fetches: mfetch, ok: mok, then: hides().slice(-1)[0] };
    await reset();

    // f: empty stack -> browser default passes through
    var nf = fetched.length; var pdf = cmdZ(); await __flush();
    __o.f = { pd: pdf, fetches: fetched.length - nf };

    // g: toast Undo drops its id from the stack
    clickRemoveTile('s1'); await __flush(); await __flush();
    var t1 = toasts()[0];
    clickRemoveTile('s2'); await __flush(); await __flush();
    t1.onAction(); await __flush(); await __flush();
    var gh = hides().slice(-1)[0];
    cmdZ(); await __flush(); await __flush();
    var gh2 = hides().slice(-1)[0];
    var ng = fetched.length; cmdZ(); await __flush(); await __flush();
    __o.g = { toastUndo: gh, nextZ: gh2, third: fetched.length - ng };
    await reset();

    // k: a stale poll (in flight before the POST landed) must not resurrect the row
    clickRemoveTile('s1'); await __flush(); await __flush();
    window.CR.board.update({ sessions: __fx.slice(), now: __NOW__ });
    __o.k = { tile: !!tileOf('s1'), railRow: !!findRowById(rail, 's1'), otherTile: !!tileOf('s2') };
    await reset();

    // l: failed undo keeps its id and tells the user
    clickRemoveTile('s1'); await __flush(); await __flush();
    failHide = true; cmdZ(); await __flush(); await __flush();
    failHide = false; var pdl = cmdZ(); await __flush(); await __flush();
    var lerr = toasts().filter(function (t) { return /update the session/.test(t.title || ''); });
    __o.l = { hides: hides(), err: lerr.length, icon: lerr[0] && lerr[0].icon, pd: pdl };
    await reset();

    // j: Enter on the button does not open the session; Enter on the row does
    var row = queryAllReal(sList, '.cr-rail-row')[0];
    var rb = findByAttr(row, 'data-act', 'remove');
    row._listeners.keydown({ key: 'Enter', target: rb, currentTarget: row });
    var goBtn = gone.length;
    row._listeners.keydown({ key: 'Enter', target: row, currentTarget: row });
    __o.j = { afterBtn: goBtn, afterRow: gone.slice(), rowId: row._attrs['data-id'] };
    await reset();

    // h: Restore from a search hit flips to Remove after the POST
    searchHits = [{ id: 'hx', title: 't', project: 'p', agent: false, mtime: __NOW__ - 5, hidden: true }];
    uiState.set('query', 't'); await __flush(); await __flush();
    var hrow = findRowById(sList, 'hx');
    var hb = findByAttr(hrow, 'data-act', 'restore');
    __o.h = { before: !!hb };
    hb._listeners.click(spyEvt()); await __flush(); await __flush();
    var hb2 = findByAttr(findRowById(sList, 'hx'), 'data-act', 'remove');
    __o.h.after = !!hb2; __o.h.aria = hb2 && hb2._attrs['aria-label']; __o.h.hides = hides();
    await reset();

    // i: a hidden search hit that is ALREADY in the live list renders Remove, not Restore
    searchHits = [{ id: 's1', title: 't', project: 'p', agent: false, mtime: __NOW__ - 5, hidden: true }];
    uiState.set('query', 'u'); await __flush(); await __flush();
    var irow = findRowById(sList, 's1');
    __o.i = { remove: !!findByAttr(irow, 'data-act', 'remove'), restore: !!findByAttr(irow, 'data-act', 'restore') };
    await reset();

    console.log(__MARK__);
    console.log(JSON.stringify(__o));
  } catch (e) {
    console.error('DRIVER-THREW: ' + (e && e.stack || e));
    process.exit(1);
  }
})();
"""

_MID = r"""
} catch (e) { console.error("BUNDLE-THREW: " + (e && e.stack || e)); process.exit(1); }
"""


def _run():
    sess = [make_session("s%d" % i, NOW - 10 - i, title="T%d" % i) for i in (1, 2, 3)]
    drv = (_DRIVER.replace("__SESSIONS__", json.dumps(sess)).replace("__NOW__", str(NOW))
           .replace("__MARK__", json.dumps(MARK)))
    rc, out, err = _run_node("\n".join([_REAL_DOM_PREAMBLE, _PRE, _bundle_js(), drv, _MID]))
    if rc != 0:
        raise AssertionError("node failed (%d)\n%s\n%s" % (rc, out, err))
    return _extract_marker_json(out, MARK)


def _hide(sid, hidden):
    return {"session": sid, "hidden": hidden}


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestRemoveSessionFrontEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_a_button_only_on_rich_rows_and_tile(self):
        a = self.O["a"]
        self.assertGreater(a["richRows"], 0)
        self.assertEqual(a["richBtns"], a["richRows"])
        self.assertTrue(a["tileBtn"])
        self.assertGreater(a["railRows"], 0)
        self.assertEqual(a["railBtns"], 0)

    def test_b_click_posts_hidden_true_stops_propagation_and_toasts(self):
        b = self.O["b"]
        self.assertEqual(b["hides"], [_hide("s1", True)])
        self.assertEqual(b["stopped"], 1)
        self.assertEqual(b["toasts"], [["Session removed · ⌘Z / Ctrl+Z to undo", "Undo", "function"]])
        self.assertGreaterEqual(b["sideCalls"], 1)

    def test_c_read_only_has_no_button(self):
        c = self.O["c"]
        self.assertEqual(c["rail"], 0)
        self.assertFalse(c["tile"])
        self.assertFalse(c["anyAct"])

    def test_d_undo_pops_newest_first(self):
        d = self.O["d"]
        self.assertEqual(d["pd1"], 1)
        self.assertEqual(d["h1"], _hide("s2", False))
        self.assertEqual(d["pd2"], 1)
        self.assertEqual(d["h2"], _hide("s1", False))

    def test_e_inputs_terminals_and_dialogs_are_not_stolen(self):
        e = self.O["e"]
        self.assertEqual((e["pdIn"], e["pdTerm"], e["pdDlg"]), (0, 0, 0))
        self.assertEqual(e["blockedFetches"], 0)
        self.assertEqual(e["pdOk"], 1)
        self.assertEqual(e["then"], _hide("s1", False))   # stack was untouched by the blocked probes

    def test_m_every_guard_is_load_bearing(self):
        m = self.O["m"]
        self.assertEqual(m["pds"], [0] * 13)
        self.assertEqual(m["fetches"], 0)
        self.assertEqual(m["ok"], 1)
        self.assertEqual(m["then"], _hide("s1", False))   # stack untouched by every blocked probe

    def test_f_empty_stack_passes_through(self):
        self.assertEqual(self.O["f"], {"pd": 0, "fetches": 0})

    def test_g_toast_undo_leaves_the_stack(self):
        g = self.O["g"]
        self.assertEqual(g["toastUndo"], _hide("s1", False))
        self.assertEqual(g["nextZ"], _hide("s2", False))
        self.assertEqual(g["third"], 0)

    def test_h_search_restore_flips_to_remove(self):
        h = self.O["h"]
        self.assertTrue(h["before"])
        self.assertTrue(h["after"])
        self.assertEqual(h["aria"], "Remove from dashboard (log is kept)")
        self.assertIn(_hide("hx", False), h["hides"])

    def test_i_known_session_hit_is_not_marked_hidden(self):
        self.assertEqual(self.O["i"], {"remove": True, "restore": False})

    def test_j_enter_on_button_does_not_open(self):
        j = self.O["j"]
        self.assertEqual(j["afterBtn"], 0)
        self.assertEqual(j["afterRow"], [["detail", j["rowId"]]])

    def test_k_stale_poll_does_not_resurrect_removed_row(self):
        k = self.O["k"]
        self.assertFalse(k["tile"])
        self.assertFalse(k["railRow"])
        self.assertTrue(k["otherTile"])

    def test_l_failed_undo_keeps_id_and_notifies(self):
        l = self.O["l"]
        self.assertEqual(l["hides"], [_hide("s1", True), _hide("s1", False), _hide("s1", False)])
        self.assertEqual(l["err"], 1)
        self.assertEqual(l["icon"], "alert")
        self.assertEqual(l["pd"], 1)

    def test_bind_undo_key_registered_before_bind_keyboard(self):
        with open(os.path.join(_WEB, "ext_cr_board.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertLess(src.index("bindUndoKey();"), src.index("bindKeyboard();"))
        self.assertTrue(re.search(r"cr-tile-remove", src))


if __name__ == "__main__":
    unittest.main()
