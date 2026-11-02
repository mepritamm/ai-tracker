"""Agent-map ENTRY POINTS + WIRING (ext_cr_boot.js / ext_cr_detail.js / ext_cr_board.js).

Real shipped text is brace-extracted from the source files and run under node
(same idiom as test_cr_dialogs_poll_broadcast_seam.py); skipped if node is missing.
  1. skeleton: the Open agent map button sits between .crd-id-row2 and .crd-goalline.
  2. renderAgentsPanel: degraded Auggie card keeps NO map link; agents_bg adds it;
     agent_sessions render a Sessions group.
  3. boot drill handler: reply:'agent-map' routes success, {error} and a rejected
     fetch to CR.dialogs.update(kind:'agent-detail', seq) and NEVER to dialog().
  4. rail/tile map buttons are gated on agent_map_n (rail also on !bg). railRow and
     sessionTile close over all of createBoard(), so the gates are asserted on the
     shipped source text; openMap() itself is extracted and run.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEB = os.path.join(_ROOT, "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None


def _src(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _balanced(source, start):
    i = source.index("{", start)
    depth = 0
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces")


def _fn(source, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", source)
    if not m:
        raise AssertionError("function %s not found" % name)
    return _balanced(source, m.start())


def _node(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError("node failed:\n" + r.stderr + r.stdout)
    return json.loads(r.stdout.split("@@JSON@@", 1)[1])


@unittest.skipUnless(_HAS_NODE, "node not installed")
class AgentMapEntry(unittest.TestCase):
    def test_skeleton_button_between_row2_and_goalline(self):
        s = _src("ext_cr_detail.js")
        a = s.index('<div class="crd-id-row2">')
        g = s.index('<div class="crd-goalline" hidden>')
        r3 = s.index('<div class="crd-id-row3">', a)
        b = s.index('data-act="agent-map"', a)
        self.assertTrue(a < r3 < b < g)
        self.assertIn("Open agent map", s[r3:g])
        self.assertIn("crd-mapbtn-count", s[r3:g])

    def _panel(self, session, ui=None):
        s = _src("ext_cr_detail.js")
        js = r"""
var OUT = [];
function esc(x){return String(x==null?'':x);}
function parseT(t){return t||0;}
function shortModel(m){return m;}
function mdHtmlSafe(t){return esc(t);}
function setPanelCount(){}
function setPanelBody(w,h){ OUT.push(h); }
function emptyHtml(t){return 'EMPTY';}
function sharedStateHtml(n){return 'DEGRADED-MARKER';}
function providerNote(sess){ return sess.note || null; }
""" + _fn(s, "groupAgentReruns") + "\n" + _fn(s, "renderAgentsPanel") + "\n" + r"""
var sess = %s;
renderAgentsPanel({}, {}, %s, sess);
console.log('@@JSON@@' + JSON.stringify(OUT[0]));
""" % (json.dumps(session), json.dumps(ui or {}))
        return _node(js)

    def test_panel_degraded_has_no_map_link(self):
        html = self._panel({"agents_bg": [], "shells": [], "agent_sessions": [],
                            "note": {"name": "Auggie", "degraded": "no bg model"}})
        self.assertIn("DEGRADED-MARKER", html)
        self.assertNotIn("agent-map", html)

    def test_panel_with_agent_has_map_links(self):
        html = self._panel({"agents_bg": [{"aid": "a1", "task": "t", "running": True, "ts": 1}],
                            "shells": []})
        self.assertIn('data-act="agent-map"', html)
        self.assertIn("View in agent map", html)
        self.assertIn('data-focus="a1"', html)

    def test_panel_sessions_group(self):
        html = self._panel({"agents_bg": [], "shells": [], "agent_sessions": [
            {"id": "s9", "title": "Child work", "wt": "wt/x", "running": True, "runs": 3,
             "model_label": "Haiku 4.5"}]})
        self.assertIn("Sessions", html)
        self.assertIn("Child work", html)
        self.assertIn("×3", html)
        self.assertIn("Haiku 4.5", html)
        self.assertIn('data-act="agent-session-open" data-id="s9"', html)
        self.assertNotIn("DEGRADED-MARKER", html)

    def test_panel_with_only_agent_sessions_has_map_link(self):
        html = self._panel({"agents_bg": [], "shells": [], "agent_sessions": [
            {"id": "s9", "title": "Child", "running": False, "runs": 1}]})
        self.assertIn('data-act="agent-map"', html)

    def test_boot_tick_uses_current_session_id_for_both_seams(self):
        s = _src("ext_cr_boot.js")
        k = s.index("triage: computeTriage(d)")
        start = s.rindex("EXT.push(", 0, k)
        hook = _balanced(s, s.index("function (d)", start))
        js = r"""
var cur = 'auggie:x';
var mounted = true;
function getUiMode(){ return 'next'; }
function computeTriage(){ return null; }
var got = {};
var window = {CR: {
  detail: {update: function(p){ got.detail = p.sid; }},
  dialogs: {update: function(p){ got.dialogs = p.sid; }}
}};
var fn = %s;
fn({meta: {}});
console.log('@@JSON@@' + JSON.stringify(got));
""" % hook
        self.assertEqual(_node(js), {"detail": "auggie:x", "dialogs": "auggie:x"})

    def _jk(self, layer_open):
        s = _src("ext_cr_detail.js")
        k = s.index("stepSession(ctx, ui, 1)")
        start = s.rindex('document.addEventListener("keydown"', 0, k)
        handler = _balanced(s, s.index("function (e)", start))
        js = r"""
var steps = [];
function stepSession(c, u, n){ steps.push(n); }
function isDetailActive(){ return true; }
function isTypingTarget(){ return false; }
var root = {isConnected: true}, ctx = {}, ui = {};
var document = {querySelector: function(sel){
  return (%s && sel === '.cr-dialog-layer[aria-hidden="false"]') ? {} : null; }};
var fn = %s;
fn({key: 'j', preventDefault: function(){}});
console.log('@@JSON@@' + JSON.stringify(steps));
""" % (json.dumps(layer_open), handler)
        return _node(js)

    def test_jk_ignored_while_dialog_layer_open(self):
        self.assertEqual(self._jk(True), [])
        self.assertEqual(self._jk(False), [1])

    def _drill(self, reply, mode):
        s = _src("ext_cr_boot.js")
        i = s.index("on('cr:drill-request', function (payload)")
        handler = _balanced(s, s.index("function (payload)", i))
        js = r"""
var calls = [];
var handler = null;
function on(n, fn){ handler = fn; }
function dialog(n, p){ calls.push(['dialog', n, p]); }
var DRILL_DIALOG_NAME = {agent: 'agent-transcript', shell: 'shell-tail', diff: 'file-diff', output: 'command-output'};
var DRILL_URL = {agent: function(s,a){return '/api/agent?id='+s+'&agent='+a;}};
function parseDiffOpLines(){return [];}
var window = {CR: {dialogs: {update: function(p){ calls.push(['update', p]); }}}};
var mode = %s;
var STALE = {stale: true};
var cur = 'S1';
function fetch(){}
var sessJSON = function(){
  if (mode === 'reject') return Promise.reject(new Error('x'));
  return Promise.resolve(mode === 'error' ? {error: 'nope'} : {narration: 'hi'});
};
on('cr:drill-request', %s);
handler({kind: 'agent', sessionId: 'S1', arg: 'A1', seq: 7%s});
setTimeout(function(){ console.log('@@JSON@@' + JSON.stringify(calls)); }, 20);
""" % (json.dumps(mode), handler, ", reply: 'agent-map'" if reply else "")
        return _node(js)

    def test_drill_to_map_never_opens_dialog(self):
        for mode in ("ok", "error", "reject"):
            calls = self._drill(True, mode)
            self.assertEqual([c[0] for c in calls], ["update"], mode)
            p = calls[0][1]
            self.assertEqual((p["kind"], p["sid"], p["aid"], p["seq"]), ("agent-detail", "S1", "A1", 7), mode)
            if mode == "ok":
                self.assertEqual(p["detail"]["narration"], "hi")
            else:
                self.assertIn("error", p)

    def test_drill_without_reply_unchanged(self):
        calls = self._drill(False, "ok")
        self.assertEqual([c[0] for c in calls], ["dialog"])
        self.assertEqual(calls[0][1], "agent-transcript")
        self.assertEqual(calls[0][2], {"text": "hi", "sessionId": "S1"})

    def test_rail_and_tile_gates(self):
        b = _src("ext_cr_board.js")
        self.assertIn("(s.agent_map_n > 0 && !s.bg) ? h('button', {\n        class: 'cr-rail-map'", b)
        t = b.index("if (s.agent_map_n > 0) {\n        head.appendChild(h('button', {\n          class: 'cr-tile-map'")
        self.assertLess(t, b.index("var body = [", t))
        i = b.index("cr-rail-badge--bg', type: 'button',\n        title: s.bg")
        self.assertIn("openMap(ctx, s)", b[i:i + 400])

    def test_open_map_opens_session_then_dialog(self):
        b = _src("ext_cr_board.js")
        js = r"""
var log = [];
function openSession(id){ log.push(['open', id]); }
""" + _fn(b, "openMap") + r"""
var ctx = {dialog: function(n, p){ log.push(['dialog', n, p.sessionId, p.session, typeof p.onOpenSession]); }, go: function(){}};
openMap(ctx, {id: 'S2'});
console.log('@@JSON@@' + JSON.stringify(log));
"""
        self.assertEqual(_node(js), [["open", "S2"], ["dialog", "agent-map", "S2", None, "function"]])

    def test_render_update_prefers_state_sid(self):
        # renderUpdate is entangled with the whole detail view; run the real function and
        # let it throw once it leaves the sid logic -- ui.sid is assigned before that point.
        d = _src("ext_cr_detail.js")
        js = _fn(d, "renderUpdate") + r"""
var ui = {}, root = {_crDetail: {node: {}, ui: ui}};
try { renderUpdate(root, {}, {sid: 'auggie:x', session: {meta: {sessionId: 'other'}}}); } catch (e) {}
console.log('@@JSON@@' + JSON.stringify(ui.sid));
"""
        self.assertEqual(_node(js), "auggie:x")


if __name__ == "__main__":
    unittest.main()
