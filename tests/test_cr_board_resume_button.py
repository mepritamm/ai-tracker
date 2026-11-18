"""Unit C: "Waiting on you" tiles resume natively.

Board: awaiting + resumable tiles get a Resume button (hero: play icon + label; others: icon-only
`.cr-tile-resume`), read-only hides every write control, Auggie keeps its old behaviour.
Parity with the session header's Resume: the tile emits the SAME `session:resume` {id}, which boot turns
into the in-app terminal `CR.term.open(id, {mode:'resume'})` — never POST /api/term/open (external window).

Runs the real assembled page in the node DOM harness from test_working_glow_board. The boot file's
event bus is private, so the driver lets the real boot init() run (setTimeout captured, ui mode
'next'), swaps CR.dialogs for a stub whose mount() captures the real boot ctx, and listens to
`session:resume` through that ctx.
"""
import json
import os
import re
import unittest

from tests.test_working_glow_board import (
    _HAS_NODE, _REAL_DOM_PREAMBLE, _bundle_js, _extract_marker_json, _run_node, make_session,
)

NOW = 1_800_000_000
MARK = "===CR_RESUME_JSON_START==="
_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")

def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


# Runs BEFORE the bundle: capture deferred callbacks and pick the Control Room UI mode.
_PRE = r"""
var __timers = [];
window.setTimeout = function (fn) { __timers.push(fn); return 0; };
window.localStorage.setItem('tracker.ui', 'next');
"""

# Runs inside the same try-block scope as the bundle, so app.js's `let trackerReadOnly` is reachable.
_DRIVER = r"""
function __flush() { return new Promise(function (r) { setImmediate(r); }); }
function __btns(root, cls) { return queryAllReal(root, '.' + cls); }
function __desc(b) {
  return { cls: Array.from(b._classes), text: allTextIn(b), title: b._attrs.title,
           aria: b._attrs['aria-label'], act: b._attrs['data-act'],
           hasIcon: b._children.some(function (c) { return c.tagName !== '#TEXT'; }) };
}

function __txt(n) {   // helper-built nodes carry text in the plain textContent property, not #text children
  return (n.tagName === '#TEXT' ? (n.textContent || '') : '') + (n._children || []).map(__txt).join('') +
         (n.tagName !== '#TEXT' && !(n._children || []).length ? (n.textContent || '') : '');
}
function __walk(n, f) { (n._children || []).forEach(function (c) { if (c && c._attrs) { f(c); __walk(c, f); } }); }
function __find(root, pred) { var out = []; __walk(root, function (c) { if (pred(c)) out.push(c); }); return out; }
function __act(sp, kind, act) {   // visible primary/item by data-tsplit-act (R2: no selector engine)
  return __find(sp, function (c) {
    return c._classes.has(kind === 'item' ? 'tsplit-item' : 'tsplit-primary') && c._attrs['data-tsplit-act'] === act && !c.hidden;
  })[0];
}
function __caret(sp) { return __find(sp, function (c) { return c._classes.has('tsplit-caret'); })[0]; }
function __list(sp) { return __find(sp, function (c) { return c._classes.has('tsplit-list'); })[0]; }
function __sdesc(sp) {
  var car = __caret(sp);
  return {
    primaries: __find(sp, function (c) { return c._classes.has('tsplit-primary') && !c.hidden; }).map(function (b) {
      return { act: b._attrs['data-tsplit-act'], text: __txt(b), title: b.title || b._attrs.title,
               hasIcon: b._children.some(function (c) { return c.tagName !== '#TEXT' && !c._classes.has('tsplit-txt'); }) };
    }),
    items: __find(sp, function (c) { return c._classes.has('tsplit-item') && !c.hidden; }).map(function (b) {
      return { act: b._attrs['data-tsplit-act'], text: __txt(b) };
    }),
    popup: car._attrs['aria-haspopup'], expanded: car._attrs['aria-expanded'], listHidden: !!__list(sp).hidden
  };
}
function __openCaret(sp) { var c = __caret(sp); c._listeners.click({ target: c }); }   // R2: shared listener, not simulateClick
function __closest(node) {   // the fake DOM's closest() is null; emulate the ignore selector's tag / [role=x] parts
  node.closest = function (sel) {
    var parts = sel.split(',');
    for (var n = node; n; n = n.parentNode) {
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i];
        if (p.charAt(0) === '[') { if (n._attrs && ('[role=' + n._attrs.role + ']') === p) return n; }
        else if (n.tagName && n.tagName.toLowerCase() === p) return n;
      }
    }
    return null;
  };
}
var __probeFetches = [], __resolveProbe = null;
window.location.hostname = 'localhost';
window.fetch = function (url) { __probeFetches.push(url); return new Promise(function (r) { __resolveProbe = r; }); };

var __fx = __SESSIONS__;
var __o = {};

function __mount(ro, sess) {
  var emitted = [];
  var ctx = { emit: function (n, p) { emitted.push([n, p]); }, readOnly: function () { return ro; },
              go: function (v, id) { emitted.push(['go', v, id]); } };
  var root = makeReal('div'); docBody.appendChild(root);
  window.CR.board.mount(root, ctx);
  window.CR.board.update({ sessions: sess, now: __NOW__ });
  return { root: root, emitted: emitted };
}
function __byId(id) { return __fx.filter(function (s) { return s.id === id; })[0]; }

(async function () {
  try {
    // ---- board, not read-only
    var m = __mount(false, __fx);
    var tileHero = findByAttr(m.root, 'data-tile-id', 'cc_hero');
    var tilePlain = findByAttr(m.root, 'data-tile-id', 'cc_plain');
    var tileIdle = findByAttr(m.root, 'data-tile-id', 'cc_idle');
    __o.heroIsHero = tileHero._classes.has('cr-tile--hero');
    var sp0 = __find(tileHero, function (c) { return c._classes.has('tsplit'); });
    __o.heroSplitCount = sp0.length;
    var sp = sp0[0];
    __o.heroPre = __sdesc(sp);                  // probe unresolved: no external item yet
    __o.probeFetches = __probeFetches.slice();
    __o.heroSmall = __btns(tileHero, 'cr-tile-resume').length;
    __o.plainResume = __btns(tilePlain, 'cr-tile-resume').map(__desc);
    __o.plainAction = __btns(tilePlain, 'cr-tile-action').length;
    __o.idleBtns = __btns(tileIdle, 'cr-tile-resume').length + __btns(tileIdle, 'cr-tile-action').length;
    var hb = __act(sp, 'primary', 'resume');
    __o.heroStopped = simulateClick(hb);
    __o.plainStopped = simulateClick(__btns(tilePlain, 'cr-tile-resume')[0]);
    __o.emitted = m.emitted.slice();
    m.emitted.length = 0;
    var goOf = function () { return m.emitted.filter(function (e) { return e[0] === 'go'; }); };
    __o.goAfterClicks = goOf().length;   // clicking the buttons must never navigate
    m.emitted.length = 0;
    tileHero._listeners.keydown({ key: 'Enter', target: hb, currentTarget: tileHero });
    __o.enterOnButton = goOf().length;
    tileHero._listeners.keydown({ key: 'Enter', target: tileHero, currentTarget: tileHero });
    __o.enterOnTile = goOf();

    // ---- hero split: menu, probe re-set on the same node, items, option-click, [role=menu] guard
    m.emitted.length = 0;
    __openCaret(sp);
    __o.openState = __sdesc(sp);
    var lst = __list(sp); __closest(lst);
    lst._listeners.click && lst._listeners.click({ target: lst });
    tileHero._listeners.click({ target: lst, stopPropagation: function () {} });
    __o.menuClickGo = m.emitted.filter(function (e) { return e[0] === 'go'; }).length;
    __resolveProbe({ status: 400 });
    await __flush(); await __flush();
    __o.heroPost = __sdesc(sp);
    __o.sameNode = __find(tileHero, function (c) { return c._classes.has('tsplit'); })[0] === sp;
    __o.stillOpen = !__list(sp).hidden;
    m.emitted.length = 0;
    __o.itemOpenStopped = simulateClick(__act(sp, 'item', 'open'));
    __o.itemExtStopped = simulateClick(__act(sp, 'item', 'external'));
    var rb = __act(sp, 'primary', 'resume');
    __o.altEvt = rb._listeners.click({ altKey: true, stopPropagation: function () {}, preventDefault: function () {} });
    __o.splitEmitted = m.emitted.slice();
    __o.heroPostTitle = rb.title || rb._attrs.title;
    // snapshot/restore across a board re-render (R3: open state only)
    __openCaret(sp);
    window.CR.board.update({ sessions: __fx, now: __NOW__ });
    var tileHero2 = findByAttr(m.root, 'data-tile-id', 'cc_hero');
    var sp2 = __find(tileHero2, function (c) { return c._classes.has('tsplit'); })[0];
    __o.rerender = { newNode: sp2 !== sp, expanded: __caret(sp2)._attrs['aria-expanded'], listHidden: !!__list(sp2).hidden };

    // ---- Auggie alone (hero + non-hero)
    var mA = __mount(false, [__byId('auggie:hero_a'), __byId('auggie:plain_a')]);
    var ah = findByAttr(mA.root, 'data-tile-id', 'auggie:hero_a');
    var ap = findByAttr(mA.root, 'data-tile-id', 'auggie:plain_a');
    __o.augHeroIsHero = ah._classes.has('cr-tile--hero');
    var asp = __find(ah, function (c) { return c._classes.has('tsplit'); })[0];
    __o.augHero = __sdesc(asp);
    __o.augHeroResume = __btns(ah, 'cr-tile-resume').length;
    __o.augPlain = __btns(ap, 'cr-tile-resume').length + __btns(ap, 'cr-tile-action').length;
    simulateClick(__act(asp, 'primary', 'open'));
    __o.augHeroEmit = mA.emitted.slice();
    mA.emitted.length = 0;
    simulateClick(__act(asp, 'item', 'external'));
    __o.augHeroItems = mA.emitted.slice();

    // ---- read-only board
    var mR = __mount(true, __fx);
    __o.roSplits = __find(mR.root, function (c) { return c._classes.has('tsplit'); }).length;
    __o.roCounts = { resume: __btns(mR.root, 'cr-tile-resume').length, action: __btns(mR.root, 'cr-tile-action').length };

    // ---- boot: capture the real ctx via a stub dialogs module, then let init() run
    var ctxCap = null;
    window.CR.dialogs = { mount: function (root, c) { ctxCap = c; } };
    __timers.slice().forEach(function (fn) { try { fn(); } catch (e) {} });
    __o.ctxCaptured = !!ctxCap;
    var opened = [], fetched = [];
    window.CR.term = { open: function (id, o) { opened.push([id, o]); } };
    window.fetch = function (url, init) { fetched.push(url); return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve({}); } }); };
    __o.readOnlyDefault = ctxCap.readOnly();
    // replay exactly what the board tile emitted through the real boot bus
    __o.emitted.filter(function (e) { return e[0] === 'session:resume'; }).forEach(function (e) { ctxCap.emit(e[0], e[1]); });
    await __flush(); await __flush();
    __o.boot = { opened: opened, fetched: fetched };
    console.log(__MARK__);
    console.log(JSON.stringify(__o));
  } catch (e) {
    console.error('DRIVER-THREW: ' + (e && e.stack || e));
    process.exit(1);
  }
})();
"""

_MID_ASYNC = r"""
} catch (e) {
  console.error("BUNDLE-THREW: " + (e && e.stack || e));
  process.exit(1);
}
"""


def _sessions():
    kw = dict(waiting=True, ended=False)
    return [
        make_session("cc_hero", NOW - 5, title="Hero", resumable=True, needs="q1", **kw),
        make_session("cc_plain", NOW - 50, title="Plain", resumable=True, needs="q2", **kw),
        make_session("auggie:hero_a", NOW - 6, title="AugHero", resumable=False, needs="", source="auggie", **kw),
        make_session("auggie:plain_a", NOW - 60, title="AugPlain", resumable=False, needs="", source="auggie", **kw),
        make_session("cc_idle", NOW - 99999, title="Idle", resumable=True, ended=True),
    ]


def _run():
    drv = (_DRIVER.replace("__SESSIONS__", json.dumps(_sessions()))
           .replace("__NOW__", str(NOW)).replace("__MARK__", json.dumps(MARK)))
    js = "\n".join([_REAL_DOM_PREAMBLE, _PRE, _bundle_js(), drv, _MID_ASYNC])
    rc, stdout, stderr = _run_node(js)
    if rc != 0:
        raise AssertionError("node failed (%d)\n%s\n%s" % (rc, stdout, stderr))
    return _extract_marker_json(stdout, MARK)



@unittest.skipUnless(_HAS_NODE, "node not available")
class TestResumeButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_fixture_hero_is_first_awaiting(self):
        self.assertTrue(self.O["heroIsHero"])
        self.assertTrue(self.O["augHeroIsHero"])

    def test_hero_is_a_resume_split_button(self):
        self.assertEqual(self.O["heroSplitCount"], 1)
        pre = self.O["heroPre"]
        (b,) = pre["primaries"]
        self.assertEqual(b["act"], "resume")
        self.assertEqual(b["text"], "Resume")
        self.assertTrue(b["hasIcon"])
        self.assertTrue(b["title"].startswith("Resume this session to answer"))
        self.assertNotIn("⌥-click", b["title"])          # probe unresolved: external not offered yet
        self.assertEqual(pre["popup"], "menu")
        self.assertEqual([i["act"] for i in pre["items"]], ["open"])
        self.assertEqual(self.O["heroSmall"], 0)
        self.assertEqual(self.O["probeFetches"], ["/api/term/open"])

    def test_probe_resolving_adds_external_on_the_same_node(self):
        post = self.O["heroPost"]
        self.assertTrue(self.O["sameNode"])
        self.assertTrue(self.O["stillOpen"])
        self.assertEqual([i["act"] for i in post["items"]], ["open", "external"])
        self.assertIn("Resume externally", post["items"][1]["text"])
        self.assertIn("⌥-click", self.O["heroPostTitle"])
        self.assertTrue(self.O["heroPostTitle"].startswith("Resume this session to answer"))

    def test_menu_items_and_option_click_emit(self):
        self.assertTrue(self.O["itemOpenStopped"])
        self.assertTrue(self.O["itemExtStopped"])
        self.assertEqual(self.O["splitEmitted"], [
            ["terminal:open", {"id": "cc_hero"}],
            ["session:openExternal", {"id": "cc_hero"}],
            ["session:openExternal", {"id": "cc_hero"}],   # option-click on Resume
        ])

    def test_click_inside_the_menu_does_not_activate_the_tile(self):
        self.assertEqual(self.O["openState"]["expanded"], "true")
        self.assertFalse(self.O["openState"]["listHidden"])
        self.assertEqual(self.O["menuClickGo"], 0)

    def test_open_menu_survives_a_board_rerender(self):
        r = self.O["rerender"]
        self.assertTrue(r["newNode"])
        self.assertEqual(r["expanded"], "true")
        self.assertFalse(r["listHidden"])

    def test_hero_css_shrinks_the_split_inside_the_sidebar(self):
        css = re.sub(r"/\*.*?\*/", "", _read("ext_cr_board.css"), flags=re.S)
        rules = {" ".join(sel.split()): " ".join(body.split()) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)}
        side = ".tracker-next .cr-tile-sidebar "
        self.assertIn("max-width:100%", rules[side + ".tsplit"].replace(" ", ""))
        self.assertIn("white-space:normal", rules[side + ".tsplit"].replace(" ", ""))
        prim = rules[side + ".tsplit-primary"].replace(" ", "")
        self.assertIn("min-width:0", prim)
        self.assertIn("padding:7px10px", prim)
        self.assertIn("overflow:hidden", prim)
        self.assertIn("text-overflow:ellipsis", prim)
        self.assertIn("flex:none", rules[side + ".tsplit-caret"].replace(" ", ""))
        txt = rules[side + ".tsplit-txt"].replace(" ", "")
        self.assertIn("min-width:0", txt)
        self.assertIn("text-overflow:ellipsis", txt)
        self.assertIn("padding:7px6px", rules[side + ".tsplit-caret"].replace(" ", ""))

    def test_tile_ignore_selector_covers_menus(self):
        self.assertIn("[role=menu]", _read("ext_cr_board.js").split("function tileBaseAttrs")[1][:600])

    def test_hero_click_emits_session_resume_and_stops_propagation(self):
        self.assertTrue(self.O["heroStopped"])
        self.assertIn(["session:resume", {"id": "cc_hero"}], self.O["emitted"])

    def test_non_hero_is_icon_only(self):
        (b,) = self.O["plainResume"]
        self.assertEqual(b["text"], "")
        self.assertTrue(b["hasIcon"])
        self.assertEqual(b["act"], "resume")
        self.assertEqual(b["aria"], "Resume this session to answer")
        self.assertEqual(self.O["plainAction"], 0)
        self.assertTrue(self.O["plainStopped"])
        self.assertIn(["session:resume", {"id": "cc_plain"}], self.O["emitted"])

    def test_enter_on_inner_button_does_not_activate_tile(self):
        self.assertEqual(self.O["goAfterClicks"], 0)
        self.assertEqual(self.O["enterOnButton"], 0)

    def test_enter_on_tile_itself_opens_the_session_once(self):
        self.assertEqual(self.O["enterOnTile"], [["go", "detail", "cc_hero"]])

    def test_read_only_hides_every_write_control(self):
        self.assertEqual(self.O["roCounts"], {"resume": 0, "action": 0})
        self.assertEqual(self.O["roSplits"], 0)

    def test_non_awaiting_tile_has_no_buttons(self):
        self.assertEqual(self.O["idleBtns"], 0)

    def test_auggie_hero_keeps_open_terminal(self):
        (b,) = self.O["augHero"]["primaries"]
        self.assertEqual((b["act"], b["text"]), ("open", "Open terminal"))
        self.assertEqual([i["act"] for i in self.O["augHero"]["items"]], ["external"])
        self.assertIn("Open externally", self.O["augHero"]["items"][0]["text"])
        self.assertNotIn("Resume externally", self.O["augHero"]["items"][0]["text"])
        self.assertEqual(self.O["augHeroResume"], 0)
        self.assertEqual(self.O["augHeroEmit"], [["terminal:open", {"id": "auggie:hero_a"}]])
        self.assertEqual(self.O["augHeroItems"], [["session:openExternal", {"id": "auggie:hero_a"}]])

    def test_auggie_non_hero_has_no_button(self):
        self.assertEqual(self.O["augPlain"], 0)

    def test_shared_tile_action_rule_does_not_force_nowrap(self):
        # nowrap on the shared rule overflows the narrow sidebar for Auggie's long
        # "Open terminal to answer"; a Resume-only nowrap must be scoped to [data-act="resume"].
        css = re.sub(r"/\*.*?\*/", "", open(os.path.join(_WEB, "ext_cr_board.css"), encoding="utf-8").read(), flags=re.S)
        hits = 0
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if " ".join(sel.split()) == ".tracker-next .cr-tile-action":
                hits += 1
                self.assertNotIn("white-space: nowrap", body)
        self.assertGreaterEqual(hits, 1)

    def test_no_hostname_gating_in_new_code(self):
        for f in ("ext_cr_boot.js", "ext_cr_board.js"):
            with open(os.path.join(_WEB, f), encoding="utf-8") as fh:
                src = fh.read()
            if f == "ext_cr_boot.js":
                src = src[src.index("on('session:resume'"):src.index("on('session:openExternal'")]
            else:
                src = (src[src.index("function heroSplit"):src.index("function sessionTile")]
                       + src[src.index("var canResume"):src.index("var canResume") + 2500])
            self.assertNotIn("hostname", src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardResumeParity(unittest.TestCase):
    """The tile's Resume runs what the session header's Resume runs (ext_cr_detail.js `case "resume"`)."""
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_harness_captured_boot_ctx(self):
        self.assertTrue(self.O["ctxCaptured"])
        self.assertFalse(self.O["readOnlyDefault"])

    def test_same_event_as_session_header_resume(self):
        with open(os.path.join(_WEB, "ext_cr_detail.js"), encoding="utf-8") as fh:
            self.assertIn('ctx.emit("session:resume", { id: sid });', fh.read())
        self.assertNotIn("session:answer", [e[0] for e in self.O["emitted"]])

    def test_board_resume_opens_in_app_terminal_not_external(self):
        self.assertEqual(self.O["boot"]["opened"], [["cc_hero", {"mode": "resume"}], ["cc_plain", {"mode": "resume"}]])
        self.assertEqual(self.O["boot"]["fetched"], [])


if __name__ == "__main__":
    unittest.main()
