"""Agent map dialog (ext_cr_dialogs.js): pure model functions, the opt-in update seam,
Escape handling, and a syntax check of the assembled page script.

Same technique as test_cr_dialogs_poll_broadcast_seam.py: brace-match the REAL shipped
functions out of aitracker/web/ext_cr_dialogs.js and run them under node, so drift fails
loudly. Skips cleanly when node is missing.
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


def _read_source():
    with open(os.path.join(_WEB, "ext_cr_dialogs.js"), encoding="utf-8") as fh:
        return fh.read()


def _extract_function(source, name):
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in ext_cr_dialogs.js" % name)
    depth = 0
    for i in range(source.index('{', m.start()), len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[m.start():i + 1]
    raise AssertionError("unterminated function %s()" % name)


def _run_node(js, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


MARK = "===AMAP_JSON==="


def _fns(*names):
    src = _read_source()
    return "\n".join(_extract_function(src, n) for n in names)


_PURE_JS = r"""
var window = {};
%s
var OUT = {};
function row(aid, o) {
  var r = { id: aid, aid: aid, parent: '', depth: 1, desc: 'd-' + aid, model_label: 'Haiku 4.5',
            state: 'done', ts: 't0', tools: 1, ctx_tok: 1000, dur_s: 5 };
  for (var k in (o || {})) r[k] = o[k];
  return r;
}
function ids(list) { return list.map(function (n) { return n.aid; }); }
function sess(rows) { return { meta: { title: 'T', model_label: 'Opus 5.5' }, context: { current: 5000 }, agents_bg: rows, agent_sessions: [] }; }

// (a) tree shape
var m = agentMapModel(sess([
  row('a'), row('b', { parent: 'a', depth: 2 }), row('o', { parent: 'ghost' }),
  row('c', { model_label: 'Sonnet 4.6' }), row('d', { model_label: 'Opus 5.5' }),
]), {});
OUT.roots = ids(m.nodes);
OUT.a_children = ids(m.nodes.filter(function (n) { return n.aid === 'a'; })[0].children);
OUT.b_level = m.nodes.filter(function (n) { return n.aid === 'a'; })[0].children[0].level;
OUT.byFamily = m.counts.byFamily;
OUT.total = m.counts.total;
OUT.no_running_all_visible = m.hiddenCount === 0 && m.flags.hideFinished === false;
// one node per run: two rows with the same aid-less desc stay two nodes
var m2 = agentMapModel(sess([row('r1', { aid: 'x1' }), row('r2', { aid: 'x2', desc: 'same' }), row('r3', { aid: 'x3', desc: 'same' })]), {});
OUT.per_run = m2.nodes.length;

// hide-finished
var hs = sess([
  row('p', { state: 'done' }), row('k', { parent: 'p', depth: 2, state: 'running' }),
  row('z', { state: 'done' }), row('y', { state: 'done' }),
]);
hs.agent_sessions = [{ id: 's1', title: 'sess', running: false, runs: 1 }, { id: 's2', title: 'live', running: true, runs: 2 }];
var mh = agentMapModel(hs, {});
OUT.h_roots = ids(mh.nodes);
OUT.h_parent_dimmed = mh.nodes[0].dimmed;
OUT.h_child_dimmed = mh.nodes[0].children[0].dimmed;
OUT.h_hidden = mh.hiddenCount;
OUT.h_sessions = mh.sessions.map(function (s) { return s.id; });
var mf = agentMapModel(hs, { focus: 'z' });
OUT.f_roots = ids(mf.nodes);
OUT.f_hidden = mf.hiddenCount;
OUT.f_z_dimmed = mf.nodes.filter(function (n) { return n.aid === 'z'; })[0].dimmed;
var ms = agentMapModel(hs, { hideFinished: false });
OUT.show_all = ids(ms.nodes).length === 3 && ms.hiddenCount === 0;
var none = agentMapModel(sess([row('q'), row('w')]), { hideFinished: true });
OUT.empty_visible = none.flags.emptyVisible; OUT.empty_hidden = none.hiddenCount;
OUT.subtitle_ok = agentMapSubtitle(m).indexOf('5 agents') === 0 && agentMapSubtitle(m).indexOf('3 haiku') > 0;

// (b) pane tail trimmed at a paragraph break
var long = ''; for (var i = 0; i < 80; i++) long += 'paragraph number ' + i + ' with some filler text here\n\n';
var pm = agentPaneModel(row('a'), { task: 'do it', tail: long });
OUT.tail_len = pm.lastOutput.length;
OUT.tail_starts_clean = /^…\nparagraph number \d+ with/.test(pm.lastOutput);
OUT.tail_end_kept = pm.lastOutput.slice(-30) === long.slice(-30);
OUT.short_tail = agentPaneModel(row('a'), { tail: 'abc' }).lastOutput;
OUT.prompt = pm.prompt;
OUT.loading = agentPaneModel(row('a'), null).loading;

// (c) paneNeedsFetch
var T = 100000;
function node(state, ts) { return { state: state, ts: ts }; }
OUT.f_err_3s = paneNeedsFetch('a', node('done', 't0'), { a: { ts: 't0', at: T - 3000, detail: { error: 'x' } } }, {}, T);
OUT.f_err_11s = paneNeedsFetch('a', node('done', 't0'), { a: { ts: 't0', at: T - 11000, detail: { error: 'x' } } }, {}, T);
OUT.f_done_same = paneNeedsFetch('a', node('done', 't0'), { a: { ts: 't0', at: 0 } }, {}, T);
OUT.f_run_same = paneNeedsFetch('a', node('running', 't0'), { a: { ts: 't0', at: 0 } }, {}, T);
OUT.f_run_new_old = paneNeedsFetch('a', node('running', 't1'), { a: { ts: 't0', at: T - 6000 } }, {}, T);
OUT.f_run_new_fresh = paneNeedsFetch('a', node('running', 't1'), { a: { ts: 't0', at: T - 5000 } }, {}, T);
OUT.f_done_new_fresh = paneNeedsFetch('a', node('done', 't1'), { a: { ts: 't0', at: T - 1000 } }, {}, T);
OUT.f_inflight = paneNeedsFetch('a', node('done', 't1'), {}, { a: { at: T - 9000 } }, T);
OUT.f_inflight_stale = paneNeedsFetch('a', node('done', 't1'), {}, { a: { at: T - 10000 } }, T);
OUT.f_other_inflight = paneNeedsFetch('a', node('done', 't1'), {}, { b: { at: T - 1000 } }, T);
OUT.f_nosel = paneNeedsFetch(null, node('done', 't1'), {}, {}, T);
OUT.f_nocache = paneNeedsFetch('a', node('done', 't1'), {}, {}, T);
console.log("%s" + JSON.stringify(OUT));
""" % ("%s", MARK)


_SEAM_JS = r"""
var window = {};
var document = { activeElement: null };
function h(tag, attrs, children) { return { tag: tag, attrs: attrs || {}, kids: children || [], remove: function () {} }; }
var FOCUSABLE = 'button';
function trapFocus() { return function () {}; }
var _layer = { appendChild: function () {}, setAttribute: function () {} };
var _ctx = null;
var _stack = [];
%s
var LOG = { plain: [], opt: [], escCalls: 0 };
var escResult = true;
function mk(name, opts) {
  var panel = { querySelector: function () { return null; }, focus: function () {}, setAttribute: function () {} };
  var built = { backdrop: {}, panel: panel, update: function (s) { LOG[name].push(s.kind); } };
  if (opts) for (var k in opts) built[k] = opts[k];
  return built;
}
var REGISTRY = {
  plain: function () { return mk('plain'); },
  opt: function () { return mk('opt', { wantsSession: true, onEscape: function () { LOG.escCalls++; return escResult; } }); },
};
var OUT = {};
open('plain', {});
update({ kind: 'session', sid: 's', session: {} });
update({ kind: 'agent-detail', sid: 's', aid: 'a', seq: 1, detail: {} });
update({ kind: 'poll' });
update({ foo: 1 });
OUT.plain_got = LOG.plain.slice();
OUT.plain_wants = !!topEntry().wantsSession;
var prevented = 0;
function esc() { onDocKeydown({ key: 'Escape', preventDefault: function () { prevented++; } }); }
esc();                       // plain dialog has no onEscape: closes
OUT.plain_closed = _stack.length === 0;
open('opt', {});
update({ kind: 'session', sid: 's', session: {} });
update({ kind: 'agent-detail', sid: 's', aid: 'a', seq: 1, detail: {} });
update({ kind: 'poll' });
OUT.opt_got = LOG.opt.slice();
OUT.opt_wants = !!topEntry().wantsSession;
esc();                       // onEscape returns true: stays open
OUT.opt_kept = _stack.length === 1;
OUT.esc_calls = LOG.escCalls;
escResult = false;
esc();                       // onEscape returns false: closes
OUT.opt_closed = _stack.length === 0;
console.log("%s" + JSON.stringify(OUT));
""" % ("%s", MARK)


def _parse(stdout):
    idx = stdout.find(MARK)
    if idx < 0:
        raise AssertionError("marker not found:\n" + stdout)
    return json.loads(stdout[idx + len(MARK):].strip())


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAgentMapPure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = _PURE_JS % _fns("amapFmtK", "amapFmtDur", "agentMapModel", "agentMapSubtitle",
                             "agentPaneModel", "paneNeedsFetch")
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("harness failed\n%s\n%s" % (out, err))
        cls.O = _parse(out)

    def test_tree_shape(self):
        O = self.O
        self.assertEqual(O["roots"], ["a", "o", "c", "d"])      # orphan 'o' at root level
        self.assertEqual(O["a_children"], ["b"])
        self.assertEqual(O["b_level"], 1)
        self.assertEqual(O["total"], 5)
        self.assertEqual(O["per_run"], 3)
        self.assertEqual(O["byFamily"], {"haiku": 3, "sonnet": 1, "opus": 1})
        self.assertTrue(O["subtitle_ok"])

    def test_no_running_shows_everything(self):
        self.assertTrue(self.O["no_running_all_visible"])

    def test_hide_finished_default_keeps_running_ancestors(self):
        O = self.O
        self.assertEqual(O["h_roots"], ["p"])              # z, y hidden; p stays for running child k
        self.assertTrue(O["h_parent_dimmed"])
        self.assertFalse(O["h_child_dimmed"])
        self.assertEqual(O["h_hidden"], 3)                  # z, y + finished session s1
        self.assertEqual(O["h_sessions"], ["s2"])

    def test_focus_forces_finished_node_visible(self):
        O = self.O
        self.assertEqual(sorted(O["f_roots"]), ["p", "z"])
        self.assertEqual(O["f_hidden"], 2)
        self.assertFalse(O["f_z_dimmed"])
        self.assertTrue(O["show_all"])

    def test_empty_visible_state(self):
        self.assertTrue(self.O["empty_visible"])
        self.assertEqual(self.O["empty_hidden"], 2)

    def test_pane_tail_trimmed_at_paragraph(self):
        O = self.O
        self.assertLessEqual(O["tail_len"], 2000)
        self.assertTrue(O["tail_starts_clean"])
        self.assertTrue(O["tail_end_kept"])
        self.assertEqual(O["short_tail"], "abc")
        self.assertEqual(O["prompt"], "do it")
        self.assertTrue(O["loading"])

    def test_pane_needs_fetch(self):
        O = self.O
        self.assertFalse(O["f_err_3s"])
        self.assertTrue(O["f_err_11s"])
        self.assertFalse(O["f_done_same"])
        self.assertFalse(O["f_run_same"])
        self.assertTrue(O["f_run_new_old"])
        self.assertFalse(O["f_run_new_fresh"])
        self.assertTrue(O["f_done_new_fresh"])
        self.assertFalse(O["f_inflight"])
        self.assertTrue(O["f_inflight_stale"])
        self.assertTrue(O["f_other_inflight"])
        self.assertFalse(O["f_nosel"])
        self.assertTrue(O["f_nocache"])


_DOM_JS = r"""
var window = {};
var NOW = 1000000;
Date.now = function () { return NOW; };
var SCROLLS = 0, CLOSES = 0, OPENS = [], EMITS = [];
function FText(t) { this.nodeType = 3; this.text = String(t); this.parentNode = null; }
function FEl(tag) {
  this.nodeType = 1; this.tagName = tag; this.children = []; this.attrs = {}; this.className = '';
  this.parentNode = null; this.listeners = {}; this.scrollTop = 0;
  var self = this;
  this.classList = {
    add: function (c) { if (!self.classList.contains(c)) self.className = (self.className + ' ' + c).trim(); },
    remove: function (c) { self.className = self.className.split(/\s+/).filter(function (x) { return x && x !== c; }).join(' '); },
    contains: function (c) { return self.className.split(/\s+/).indexOf(c) >= 0; },
  };
}
FEl.prototype.appendChild = function (c) { c.parentNode = this; this.children.push(c); return c; };
FEl.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
FEl.prototype.getAttribute = function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; };
FEl.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
FEl.prototype.addEventListener = function (t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); };
FEl.prototype.click = function () { (this.listeners.click || []).forEach(function (f) { f({}); }); };
FEl.prototype.contains = function (n) { for (; n; n = n.parentNode) if (n === this) return true; return false; };
FEl.prototype.focus = function () {
  if (this.tagName === 'button' || this.tagName === 'a' || this.tagName === 'input' || this.getAttribute('tabindex') != null) document.activeElement = this;
};
FEl.prototype.scrollIntoView = function () { SCROLLS++; };
FEl.prototype._match = function (sel) {
  var self = this;
  return sel.split(',').some(function (s) {
    s = s.trim();
    if (s.charAt(0) === '.') return self.classList.contains(s.slice(1));
    var m = /^\[([\w-]+)\]$/.exec(s);
    return m ? self.getAttribute(m[1]) != null : false;
  });
};
FEl.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (c) { if (c.nodeType === 1) { if (c._match(sel)) out.push(c); walk(c); } }); })(this);
  return out;
};
FEl.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
Object.defineProperty(FEl.prototype, 'textContent', {
  get: function () { return this.children.map(function (c) { return c.nodeType === 3 ? c.text : c.textContent; }).join(''); },
  set: function (v) { this.children = [new FText(v)]; this.children[0].parentNode = this; },
});
Object.defineProperty(FEl.prototype, 'innerHTML', {
  get: function () { return ''; },
  set: function (v) {
    if (v !== '') throw new Error('innerHTML only for clearing');
    if (this.contains(document.activeElement)) document.activeElement = document.body;
    this.children = [];
  },
});
var document = { body: new FEl('body'), activeElement: null,
  createElement: function (t) { return new FEl(t); }, createTextNode: function (t) { return new FText(t); } };
document.activeElement = document.body;
function glyph() { return null; } function icon() { return null; }
function providerNoteFor() { return null; } function degraded() { return new FEl('div'); }
function close() { CLOSES++; } function open(n, p) { OPENS.push([n, p]); }
var _idSeq = 0;
var _ctx = { emit: function (n, p) { EMITS.push([n, p]); } };
%s
function row(aid, o) {
  var r = { id: aid, aid: aid, parent: '', depth: 1, desc: 'd-' + aid, model_label: 'Haiku 4.5',
            state: 'done', ts: 't0', tools: 1, ctx_tok: 1000, dur_s: 5 };
  for (var k in (o || {})) r[k] = o[k];
  return r;
}
function sess(rows) { return { meta: { title: 'T', model_label: 'Opus 5.5' }, context: { current: 5000 }, agents_bg: rows, agent_sessions: [] }; }
function tick(d, rows) { d.update({ kind: 'session', sid: 'S', session: sess(rows) }); }
function nodeBtn(d, aid) { return d.panel.querySelectorAll('[data-aid]').filter(function (e) { return e.getAttribute('data-aid') === aid; })[0]; }
function mk() {
  EMITS.length = 0; SCROLLS = 0; CLOSES = 0; NOW = 1000000;
  return renderAgentMap({ sessionId: 'S', session: sess([row('a', { state: 'running', ts: 't1' }), row('b')]) });
}
function paneEl(d) { return d.panel.querySelector('.cr-amap-pane'); }
var OUT = {};

// (a) F1: reply must record the ts it was REQUESTED at
var d = mk();
nodeBtn(d, 'a').click();
OUT.a_emit1 = EMITS.length;
tick(d, [row('a', { state: 'done', ts: 't2' }), row('b')]);
OUT.a_emit_after_tick = EMITS.length;
d.update({ kind: 'agent-detail', sid: 'S', aid: 'a', seq: EMITS[0][1].seq, detail: { task: 'x', tail: 'out' } });
tick(d, [row('a', { state: 'done', ts: 't2' }), row('b')]);
OUT.a_emit_final = EMITS.length;

// (b) F2: focus survives a repaint (new element, same data-act)
d = mk();
var tg = d.panel.querySelector('[data-act]');
tg.focus();
tick(d, [row('a', { state: 'running', ts: 't1' }), row('b')]);
var ae = document.activeElement;
OUT.b_new_el = ae !== tg;
OUT.b_act = ae.getAttribute('data-act');
OUT.b_in_panel = d.panel.contains(ae);

// (c) F3: a plain tick must not scroll the focused node
d = mk();
nodeBtn(d, 'a').click();
OUT.c_after_select = SCROLLS;
SCROLLS = 0;
tick(d, [row('a', { state: 'running', ts: 't1' }), row('b')]);
OUT.c_after_tick = SCROLLS;
OUT.c_focus_kept = document.activeElement.getAttribute('data-aid');

// (d) F5: error reply shows the message and stops per-tick refetch for 6s
d = mk();
nodeBtn(d, 'a').click();
d.update({ kind: 'agent-detail', sid: 'S', aid: 'a', seq: EMITS[0][1].seq, error: 'boom' });
OUT.d_text = paneEl(d).textContent;
OUT.d_loading = paneEl(d).textContent.indexOf('Loading') >= 0;
NOW += 3000;
tick(d, [row('a', { state: 'running', ts: 't9' }), row('b')]);
OUT.d_emit_3s = EMITS.length;
NOW += 4000;
tick(d, [row('a', { state: 'running', ts: 't10' }), row('b')]);
OUT.d_emit_7s = EMITS.length;
NOW += 4000;
tick(d, [row('a', { state: 'running', ts: 't11' }), row('b')]);
OUT.d_emit_11s = EMITS.length;

// (e) a tick for another session closes the dialog
d = mk();
d.update({ kind: 'session', sid: 'OTHER', session: sess([row('a')]) });
OUT.e_closes = CLOSES;

// (f) Escape + root card
d = mk();
OUT.f_no_pane = d.onEscape();
nodeBtn(d, 'a').click();
OUT.f_pane_open = paneEl(d).getAttribute('hidden');
OUT.f_esc = d.onEscape();
OUT.f_pane_after = paneEl(d).getAttribute('hidden');
nodeBtn(d, 'a').click();
d.panel.querySelector('.cr-amap-rootcard').click();
OUT.f_root_closes = paneEl(d).getAttribute('hidden');
OUT.f_wide = d.panel.classList.contains('cr-dialog-wide');
// (g) V-F1: focused control vanishes on repaint -> focus falls back to the (tabindex) panel
d = renderAgentMap({ sessionId: 'S', session: sess([row('a'), row('b')]) });
d.panel.querySelector('[data-act]').click();           // Hide finished -> empty-visible state
var sf = d.panel.querySelectorAll('[data-act]').filter(function (e) { return e.getAttribute('data-act') === 'show-finished'; })[0];
OUT.g_has_inline = !!sf;
sf.focus();
sf.click();                                            // Show finished: inline button disappears
tick(d, [row('a'), row('b')]);
OUT.g_in_panel = d.panel.contains(document.activeElement);

// (h) V-F2: errored DONE agent retries after 10s, not per tick
d = renderAgentMap({ sessionId: 'S', session: sess([row('a', { ts: 't1' }), row('b', { ts: 't1' })]) });
EMITS.length = 0; NOW = 1000000;
nodeBtn(d, 'a').click();
d.update({ kind: 'agent-detail', sid: 'S', aid: 'a', seq: EMITS[0][1].seq, error: 'boom' });
NOW += 3000; tick(d, [row('a', { ts: 't1' }), row('b', { ts: 't1' })]);
OUT.h_3s = EMITS.length;
NOW += 8000; tick(d, [row('a', { ts: 't1' }), row('b', { ts: 't1' })]);
OUT.h_11s = EMITS.length;
console.log("%s" + JSON.stringify(OUT));
""" % ("%s", MARK)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAgentMapDialogBehaviour(unittest.TestCase):
    """Runs the REAL renderAgentMap against a minimal fake DOM."""

    @classmethod
    def setUpClass(cls):
        js = _DOM_JS % _fns("h", "buildChrome", "emptyState", "amapFmtK", "amapFmtDur", "agentMapModel",
                            "agentMapSubtitle", "amapFocusKey", "agentPaneModel", "paneNeedsFetch",
                            "renderAgentMap")
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("harness failed:\n" + err + out)
        cls.o = _parse(out)

    def test_a_reply_records_requested_ts_so_stale_detail_refetches(self):
        self.assertEqual(self.o["a_emit1"], 1)
        self.assertEqual(self.o["a_emit_after_tick"], 1)   # in flight: no duplicate
        self.assertEqual(self.o["a_emit_final"], 2)        # reply was for t1, row is t2 -> refetch

    def test_b_focus_survives_repaint(self):
        self.assertTrue(self.o["b_new_el"])
        self.assertEqual(self.o["b_act"], "toggle-finished")
        self.assertTrue(self.o["b_in_panel"])

    def test_c_tick_does_not_scroll(self):
        self.assertEqual(self.o["c_after_select"], 1)
        self.assertEqual(self.o["c_after_tick"], 0)
        self.assertEqual(self.o["c_focus_kept"], "a")

    def test_d_error_reply_shown_and_throttled(self):
        self.assertIn("Couldn't load: boom", self.o["d_text"])
        self.assertFalse(self.o["d_loading"])
        self.assertEqual(self.o["d_emit_3s"], 1)
        self.assertEqual(self.o["d_emit_7s"], 1)   # error cache holds for 10s
        self.assertEqual(self.o["d_emit_11s"], 2)

    def test_g_fallback_focus_lands_on_panel(self):
        self.assertTrue(self.o["g_has_inline"])
        self.assertTrue(self.o["g_in_panel"])

    def test_h_errored_done_agent_retries_after_10s(self):
        self.assertEqual(self.o["h_3s"], 1)
        self.assertEqual(self.o["h_11s"], 2)

    def test_e_other_session_closes(self):
        self.assertEqual(self.o["e_closes"], 1)

    def test_f_escape_and_root_card(self):
        self.assertFalse(self.o["f_no_pane"])
        self.assertIsNone(self.o["f_pane_open"])
        self.assertTrue(self.o["f_esc"])
        self.assertEqual(self.o["f_pane_after"], "hidden")
        self.assertEqual(self.o["f_root_closes"], "hidden")
        self.assertTrue(self.o["f_wide"])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAgentMapSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        js = _SEAM_JS % _fns("topEntry", "onDocKeydown", "open", "close", "update")
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("harness failed\n%s\n%s" % (out, err))
        cls.O = _parse(out)

    def test_non_opt_in_dialog_refuses_session_and_agent_detail(self):
        self.assertFalse(self.O["plain_wants"])
        self.assertEqual(self.O["plain_got"], [None])       # only the kind-less update got through

    def test_opt_in_dialog_accepts_session_and_agent_detail_but_not_poll(self):
        self.assertTrue(self.O["opt_wants"])
        self.assertEqual(self.O["opt_got"], ["session", "agent-detail"])

    def test_escape_handled_by_dialog_keeps_it_open(self):
        O = self.O
        self.assertTrue(O["plain_closed"])
        self.assertTrue(O["opt_kept"])
        self.assertEqual(O["esc_calls"], 1)
        self.assertTrue(O["opt_closed"])

    def test_agent_map_registered_and_opts_in(self):
        src = _read_source()
        self.assertIn("'agent-map': renderAgentMap", src)
        body = _extract_function(src, "renderAgentMap")
        self.assertIn("wantsSession: true", body)
        self.assertIn("onEscape", body)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestAssembledPageParses(unittest.TestCase):
    def test_node_check_on_page_script(self):
        from aitracker import page
        html = page.build_page()
        with open(os.path.join(_WEB, "app.js"), encoding="utf-8") as fh:
            head = fh.read()[:200]
        start = html.find(head)          # app.js opens the baked script body
        end = html.rfind("</script></body></html>")
        self.assertGreater(start, 0)
        self.assertGreater(end, start)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "page.js")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(html[start:end])
            proc = subprocess.run(["node", "--check", p], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
