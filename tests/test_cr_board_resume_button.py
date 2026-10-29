"""Unit C: "Waiting on you" tiles resume natively.

Board: awaiting + resumable tiles get a Resume button (hero: play icon + label; others: icon-only
`.cr-tile-resume`), read-only hides every write control, Auggie keeps its old behaviour.
Boot: `session:answer` -> `CR.answerSession(payload)` -> POST /api/term/open {mode:'resume'}, with the
in-browser fallback only on 403 {remote:true} (and not readonly); everything else notifies once.

Runs the real assembled page in the node DOM harness from test_working_glow_board. The boot file's
event bus is private, so the driver lets the real boot init() run (setTimeout captured, ui mode
'next'), swaps CR.dialogs for a stub whose mount() captures the real boot ctx, and listens to
`notify` / `session:resume` through that ctx.
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
    __o.heroAction = __btns(tileHero, 'cr-tile-action').map(__desc);
    __o.heroSmall = __btns(tileHero, 'cr-tile-resume').length;
    __o.plainResume = __btns(tilePlain, 'cr-tile-resume').map(__desc);
    __o.plainAction = __btns(tilePlain, 'cr-tile-action').length;
    __o.idleBtns = __btns(tileIdle, 'cr-tile-resume').length + __btns(tileIdle, 'cr-tile-action').length;
    var hb = __btns(tileHero, 'cr-tile-action')[0];
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

    // ---- Auggie alone (hero + non-hero)
    var mA = __mount(false, [__byId('auggie:hero_a'), __byId('auggie:plain_a')]);
    var ah = findByAttr(mA.root, 'data-tile-id', 'auggie:hero_a');
    var ap = findByAttr(mA.root, 'data-tile-id', 'auggie:plain_a');
    __o.augHeroIsHero = ah._classes.has('cr-tile--hero');
    __o.augHero = __btns(ah, 'cr-tile-action').map(__desc);
    __o.augHeroResume = __btns(ah, 'cr-tile-resume').length;
    __o.augPlain = __btns(ap, 'cr-tile-resume').length + __btns(ap, 'cr-tile-action').length;
    simulateClick(__btns(ah, 'cr-tile-action')[0]);
    __o.augHeroEmit = mA.emitted;

    // ---- read-only board
    var mR = __mount(true, __fx);
    __o.roCounts = { resume: __btns(mR.root, 'cr-tile-resume').length, action: __btns(mR.root, 'cr-tile-action').length };

    // ---- boot: capture the real ctx via a stub dialogs module, then let init() run
    var ctxCap = null;
    window.CR.dialogs = { mount: function (root, c) { ctxCap = c; } };
    __timers.slice().forEach(function (fn) { try { fn(); } catch (e) {} });
    __o.ctxCaptured = !!ctxCap;
    var __nt = [], resumes = [], opened = [], fetched = [];
    ctxCap.on('notify', function (p) { __nt.push(p.text); });
    ctxCap.on('session:resume', function (p) { resumes.push(p.id); });
    window.CR.term = { open: function (id, o) { opened.push([id, o]); } };
    __o.readOnlyDefault = ctxCap.readOnly();
    async function run(label, payload, ro, resp, viaBus) {
      __nt.length = 0; resumes.length = 0; opened.length = 0; fetched.length = 0;
      trackerReadOnly = ro;
      window.fetch = function (url, init) {
        fetched.push([url, JSON.parse(init.body)]);
        return Promise.resolve({ ok: resp.ok, status: resp.status, json: function () { return Promise.resolve(resp.body); } });
      };
      if (viaBus) ctxCap.emit('session:answer', payload); else window.CR.answerSession(payload);
      await __flush(); await __flush();
      __o[label] = { fetched: fetched.slice(), opened: opened.slice(), notes: __nt.slice(), resumes: resumes.slice() };
    }
    await run('ok', { id: 'cc1', resumable: true }, false, { ok: true, status: 200, body: { ok: true } });
    await run('okBus', { id: 'cc1', resumable: true }, false, { ok: true, status: 200, body: { ok: true } }, true);
    await run('remote', { id: 'cc1', resumable: true }, false, { ok: false, status: 403, body: { error: 'x', remote: true } });
    await run('termDisabled', { id: 'cc1', resumable: true }, false, { ok: false, status: 403, body: { error: 'terminal disabled' } });
    await run('readonly403', { id: 'cc1', resumable: true }, false, { ok: false, status: 403, body: { error: 'ro', readonly: true, remote: true } });
    await run('serverError', { id: 'cc1', resumable: true }, false, { ok: false, status: 500, body: { error: 'boom' } });
    await run('auggie', { id: 'auggie:x', resumable: false }, false, { ok: true, status: 200, body: {} });
    await run('claudeIdNotResumable', { id: 'cc1', resumable: false }, false, { ok: true, status: 200, body: {} });
    await run('auggieIdResumableTrue', { id: 'auggie:x', resumable: true }, false, { ok: true, status: 200, body: {} });
    await run('roBoot', { id: 'cc1', resumable: true }, true, { ok: true, status: 200, body: {} });
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


_OPEN_POST = [["/api/term/open", {"session": "cc1", "mode": "resume"}]]


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestResumeButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_fixture_hero_is_first_awaiting(self):
        self.assertTrue(self.O["heroIsHero"])
        self.assertTrue(self.O["augHeroIsHero"])

    def test_hero_has_icon_and_resume_label(self):
        (b,) = self.O["heroAction"]
        self.assertEqual(b["text"], "Resume")
        self.assertTrue(b["hasIcon"])
        self.assertEqual(b["act"], "resume")
        self.assertEqual(b["title"], "Resume this session to answer")
        self.assertEqual(b["aria"], "Resume this session to answer")
        self.assertEqual(self.O["heroSmall"], 0)

    def test_hero_click_emits_answer_with_resumable_and_stops_propagation(self):
        self.assertTrue(self.O["heroStopped"])
        self.assertIn(["session:answer", {"id": "cc_hero", "resumable": True}], self.O["emitted"])

    def test_non_hero_is_icon_only(self):
        (b,) = self.O["plainResume"]
        self.assertEqual(b["text"], "")
        self.assertTrue(b["hasIcon"])
        self.assertEqual(b["act"], "resume")
        self.assertEqual(b["aria"], "Resume this session to answer")
        self.assertEqual(self.O["plainAction"], 0)
        self.assertTrue(self.O["plainStopped"])
        self.assertIn(["session:answer", {"id": "cc_plain", "resumable": True}], self.O["emitted"])

    def test_enter_on_inner_button_does_not_activate_tile(self):
        self.assertEqual(self.O["goAfterClicks"], 0)
        self.assertEqual(self.O["enterOnButton"], 0)

    def test_enter_on_tile_itself_opens_the_session_once(self):
        self.assertEqual(self.O["enterOnTile"], [["go", "detail", "cc_hero"]])

    def test_read_only_hides_every_write_control(self):
        self.assertEqual(self.O["roCounts"], {"resume": 0, "action": 0})

    def test_non_awaiting_tile_has_no_buttons(self):
        self.assertEqual(self.O["idleBtns"], 0)

    def test_auggie_hero_keeps_open_terminal(self):
        (b,) = self.O["augHero"]
        self.assertEqual(b["text"], "Open terminal to answer")
        self.assertEqual(self.O["augHeroResume"], 0)
        self.assertEqual(self.O["augHeroEmit"], [["terminal:open", {"id": "auggie:hero_a"}]])

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
                src = src[src.index("function answerSession"):src.index("window.CR.answerSession")]
            else:
                src = src[src.index("var canResume"):src.index("var canResume") + 2500]
            self.assertNotIn("hostname", src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAnswerSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.O = _run()

    def test_harness_captured_boot_ctx(self):
        self.assertTrue(self.O["ctxCaptured"])
        self.assertFalse(self.O["readOnlyDefault"])

    def test_ok_posts_resume_notifies_no_fallback(self):
        for k in ("ok", "okBus"):
            o = self.O[k]
            self.assertEqual(o["fetched"], _OPEN_POST, k)
            self.assertEqual(o["opened"], [], k)
            self.assertEqual(o["resumes"], [], k)
            self.assertEqual(len(o["notes"]), 1, k)

    def test_remote_403_falls_back_to_in_browser_resume(self):
        o = self.O["remote"]
        self.assertEqual(o["fetched"], _OPEN_POST)
        self.assertEqual(o["resumes"], ["cc1"])
        self.assertEqual(o["opened"], [["cc1", {"mode": "resume"}]])

    def test_terminal_disabled_403_no_fallback_one_notify(self):
        o = self.O["termDisabled"]
        self.assertEqual((o["resumes"], o["opened"]), ([], []))
        self.assertEqual(o["notes"], ["terminal disabled"])

    def test_readonly_403_no_fallback(self):
        o = self.O["readonly403"]
        self.assertEqual((o["resumes"], o["opened"]), ([], []))
        self.assertEqual(o["notes"], ["ro"])

    def test_other_error_notifies_error_text(self):
        self.assertEqual(self.O["serverError"]["notes"], ["boom"])
        self.assertEqual(self.O["serverError"]["resumes"], [])

    def test_non_resumable_opens_cwd_terminal_without_post(self):
        # branches on payload.resumable, never on the id shape
        for k, sid in (("auggie", "auggie:x"), ("claudeIdNotResumable", "cc1")):
            o = self.O[k]
            self.assertEqual(o["fetched"], [], k)
            self.assertEqual(o["opened"], [[sid, {"mode": "cwd"}]], k)

    def test_resumable_flag_wins_over_id_regex(self):
        o = self.O["auggieIdResumableTrue"]
        self.assertEqual(o["fetched"], [["/api/term/open", {"session": "auggie:x", "mode": "resume"}]])

    def test_read_only_does_nothing_but_notify(self):
        o = self.O["roBoot"]
        self.assertEqual((o["fetched"], o["opened"], o["resumes"]), ([], [], []))
        self.assertEqual(len(o["notes"]), 1)


if __name__ == "__main__":
    unittest.main()
