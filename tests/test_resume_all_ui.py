"""T15: the "Resume all prior terminals" widget (ext_cr_dialogs.js resumeAllWidget), both hosts, and the
agentWatchJob onDone hook. Static source checks plus a node harness over the real shipped functions."""
import os
import unittest

from tests.test_cr_manage_terminals_poll import (
    _HAS_NODE, _extract_function, _extract_json, _extract_script_content, _read_page, _run_node)

_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "aitracker", "web", "ext_cr_dialogs.js")


def _src():
    with open(_JS, encoding="utf-8") as f:
        return f.read()


class ResumeAllStatic(unittest.TestCase):
    def test_label_and_route(self):
        s = _src()
        self.assertIn("'Resume all prior terminals'", s)
        self.assertIn("'/api/terminals/resume-all'", s)

    def test_no_server_sentence_in_js(self):
        from aitracker import agent_cli, term_vt
        s = _src()
        for mod, pre in ((agent_cli, "AGENT_RA_"), (term_vt, "RA_")):
            for name in dir(mod):
                v = getattr(mod, name)
                if name.startswith(pre) and isinstance(v, str) and len(v) > 8:
                    self.assertNotIn(v, s, name)


class ResumeAllWiring(unittest.TestCase):
    def test_manage_dialog_passes_onrefresh_and_cap_dialog_does_not(self):
        with open(_JS.replace("ext_cr_dialogs.js", "ext_cr_term.js"), encoding="utf-8") as f:
            s = f.read()

        def body(name):
            i = s.index("function " + name)
            j = s.find("\n  function ", i + 10)
            return s[i:] if j < 0 else s[i:j]
        self.assertIn("onRefresh: _repaintManage", body("_openManageDialog"))   # without it no button in Manage
        self.assertNotIn("onRefresh", body("_openCapDialog"))                    # the cap dialog gets none


def _driver():
    bundle = _extract_script_content(_read_page())
    fns = "\n".join(_extract_function(bundle, n) for n in (
        "_agentFireDone", "agentWatchJob", "resumeAllWidget", "agentsBlock", "renderManageTerminals", "crBtn"))
    return r"""
var OUT = {};
function mk(tag, attrs) {
  var n = { tag: tag, attrs: attrs || {}, children: [], l: {}, attr: {}, hidden: false, checked: false, textContent: '' };
  n.cls = (attrs && attrs.class) || '';
  n.appendChild = function (c) { n.children.push(c); };
  n.addEventListener = function (t, f) { (n.l[t] = n.l[t] || []).push(f); };
  n.fire = function (t) { (n.l[t] || []).forEach(function (f) { f({}); }); };
  n.setAttribute = function (k, v) { n.attr[k] = v; };
  n.removeAttribute = function (k) { delete n.attr[k]; };
  Object.defineProperty(n, 'innerHTML', { set: function () { n.children = []; }, get: function () { return ''; } });
  if (attrs && attrs.text) n.textContent = attrs.text;
  return n;
}
function h(tag, attrs, kids) {
  var n = mk(tag, attrs);
  (kids || []).forEach(function (k) { n.children.push(typeof k === 'string' ? { text: k } : k); });
  return n;
}
function walk(n, f) { if (!n) return; f(n); (n.children || []).forEach(function (c) { walk(c, f); }); }
function all(n, pred) { var o = []; walk(n, function (x) { if (pred(x)) o.push(x); }); return o; }
function hasCls(c) { return function (x) { return (x.className || x.cls || '').split(' ').indexOf(c) >= 0; }; }
function text(n) { var t = []; walk(n, function (x) { if (x.text) t.push(x.text); if (x.textContent) t.push(x.textContent); }); return t.join('|'); }
var roCalls = 0, ro = false;
function crReadOnly() { roCalls++; return ro; }
var queue = [], calls = [];
function crCall(url, method, body) {
  calls.push({ url: url, method: method, body: body });
  return Promise.resolve(queue.shift() || { ok: false, status: 0, body: {} });
}
var toasts = [];
function toast(t) { toasts.push(t); }
var timers = [];
function setInterval(f) { timers.push(f); return timers.length; }
function clearInterval() {}
function setTimeout() { return 1; }
function timeAgo() { return 'AGO'; }
function cwdTail(c) { return c; }
function sessionTitleFor() { return null; }
function icon() { return {}; }
function emptyState(o) { var n = mk('div', {}); n.kind = 'empty'; return n; }
function errorState(o) { return mk('div', {}); }
var titleEl = { textContent: '' };
var made = [];
function buildChrome() {
  var body = mk('div', {});
  var c = { backdrop: {}, panel: { classList: { toggle: function () {} }, querySelector: function () { return titleEl; } }, body: body };
  made.push(c);
  return c;
}
var _agentJobTimer = null, _agentToasted = null, _agentWatchId = null, _agentJobDone = null;
%s
var tick = function () { return timers[timers.length - 1](); };
var settle = function () { return new Promise(function (r) { setImmediate(r); }); };
var PLAN = { needs_confirm: true, message: 'MSG-X', pick: 'PICK-X', error: 'ERR-X', note: 'NOTE-X', already: 'ALREADY-X',
  open: [{ session: 's1', title: 'T1', cwd: '/a', seen: 1, checked: true }, { session: 's2', title: 'T2', cwd: '/b', seen: 2, checked: false }],
  cannot: [{ title: 'T3', reason: 'REASON-X', command: ['CMD-X'] }] };
var T = [{ tty: '/dev/ttys1', cwd: '/p', started: 1, session: '', mode: '' }];
(async function () {
  var refreshed = 0;
  var base = { max: 4, onPeek: function () {}, onKill: function () {}, onCloseAll: function () {}, onRefresh: function () { refreshed++; } };
  var d0 = renderManageTerminals(Object.assign({ terminals: [] }, base));
  OUT.empty_has = all(made[0].body, hasCls('cr-resume-all')).length;
  var d1 = renderManageTerminals(Object.assign({ terminals: T }, base));
  OUT.list_has = all(made[1].body, hasCls('cr-resume-all')).length;
  roCalls = 0;
  var d2 = renderManageTerminals({ terminals: T, max: 1 });
  OUT.cap_has = all(made[2].body, hasCls('cr-resume-all')).length; OUT.cap_ro_calls = roCalls;
  ro = true;
  var d3 = renderManageTerminals(Object.assign({ terminals: T }, base));
  OUT.ro_has = all(made[3].body, hasCls('cr-resume-all')).length;
  ro = false;
  var btn = all(made[1].body, hasCls('cr-resume-all'))[0];
  var panel = all(made[1].body, hasCls('cr-resume-all-confirm'))[0];
  queue.push({ ok: false, status: 409, body: PLAN });
  btn.fire('click'); await settle();
  OUT.ask_call = calls[0];
  OUT.panel_text = text(panel);
  OUT.list_n = all(panel, hasCls('cr-resume-all-list')).length;
  OUT.row_n = all(panel, hasCls('cr-resume-all-row')).length;
  OUT.actions_btns = all(all(panel, hasCls('cr-confirm-actions'))[0] || {children:[]}, function (x) { return x.tag === 'button'; }).map(function (b) { return b.textContent; });
  var cbs = all(panel, function (x) { return x.tag === 'input'; });
  OUT.cb_n = cbs.length; OUT.cb_checked = cbs.map(function (c) { return c.checked; });
  OUT.cmd = text(panel).indexOf('CMD-X') >= 0;
  d1.update(Object.assign({ terminals: T.concat([{ tty: '/dev/ttys2', cwd: '/q', started: 2, session: '', mode: '' }]) }, base));
  OUT.kept_panel = all(made[1].body, hasCls('cr-resume-all-confirm'))[0] === panel;
  OUT.kept_boxes = all(panel, function (x) { return x.tag === 'input'; }).length;
  cbs = all(panel, function (x) { return x.tag === 'input'; });
  cbs[1].checked = true; cbs[1].fire('change');
  var conf = all(panel, function (x) { return x.tag === 'button' && /^Resume \d+ ticked$/.test(x.textContent); })[0];
  OUT.conf_label = conf.textContent;
  calls.length = 0;
  queue.push({ ok: true, status: 202, body: { job: { id: 7, state: 'running' } } });
  conf.fire('click'); conf.fire('click'); await settle();
  OUT.confirm_calls = calls.filter(function (c) { return c.body && c.body.confirm; }).map(function (c) { return c.body; });
  queue.push({ ok: true, status: 200, body: { job: { id: 7, state: 'done', summary: 'SUM' } } });
  await tick(); await settle();
  OUT.refreshed = refreshed; OUT.toast = toasts.length && toasts[0].title;
  queue.push({ ok: false, status: 409, body: PLAN });
  btn.fire('click'); await settle();
  conf = all(panel, function (x) { return x.tag === 'button' && /^Resume/.test(x.textContent); })[0];
  var pre = all(panel, function (x) { return x.tag === 'input'; });
  pre[1].checked = true; pre[1].fire('change');
  queue.push({ ok: false, status: 409, body: Object.assign({}, PLAN, { error: 'STALE-X' }) });
  conf.fire('click'); await settle();
  OUT.stale_text = text(panel);
  OUT.stale_ticks = all(panel, function (x) { return x.tag === 'input'; }).map(function (c) { return c.checked; });
  var a = [], b = [], c = [];
  agentWatchJob(1, function (j) { a.push(j); });
  agentWatchJob(2, function (j) { b.push(j); });
  OUT.a_after_switch = a.length === 1 && a[0] === null; OUT.b_after_switch = b.length;
  queue.push({ ok: true, status: 200, body: { job: { id: 2, state: 'done', summary: 'S2' } } });
  await tick(); await settle();
  OUT.b_after_done = b.length === 1 && !!b[0] && b[0].id === 2; OUT.a_total = a.length;
  agentWatchJob(3, function (j) { c.push(j); });
  queue.push({ ok: false, status: 500, body: {} });
  await tick(); await settle();
  OUT.c_after_failed_poll = c.length;
  queue.push({ ok: true, status: 200, body: { agents: [{ id: 'claude', label: 'Claude', installed: '1', can_doctor: true, can_upgrade: true, can_resume_all: true },
    { id: 'auggie', label: 'Auggie', installed: '1', can_doctor: true, can_upgrade: true }] } });
  var wrap = agentsBlock(); await settle();
  var rows = all(wrap, hasCls('cr-agent-row'));
  OUT.cfg_rows = rows.length;
  OUT.cfg_btn_in_claude = all(rows[0], hasCls('cr-resume-all')).length;
  OUT.cfg_btn_in_auggie = all(rows[1], hasCls('cr-resume-all')).length;
  OUT.cfg_panel = all(wrap, hasCls('cr-resume-all-confirm')).length;
})().then(function () {
  console.log("===MANAGE_TERMINALS_JSON_START==="); console.log(JSON.stringify(OUT));
}, function (e) { console.log(String(e && e.stack || e)); process.exit(1); });
""" % fns


@unittest.skipUnless(_HAS_NODE, "node not available")
class ResumeAllNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rc, out, err = _run_node(_driver())
        if rc != 0:
            raise AssertionError("harness failed\n%s\n%s" % (out, err))
        cls.O = _extract_json(out)

    def test_button_placement(self):
        self.assertEqual(self.O["empty_has"], 1)
        self.assertEqual(self.O["list_has"], 1)

    def test_cap_dialog_and_readonly_have_none(self):
        self.assertEqual(self.O["cap_has"], 0)
        self.assertEqual(self.O["cap_ro_calls"], 0)      # onRefresh is checked BEFORE crReadOnly
        self.assertEqual(self.O["ro_has"], 0)

    def test_plan_rendered_verbatim(self):
        self.assertEqual(self.O["ask_call"], {"url": "/api/terminals/resume-all", "method": "POST", "body": {}})
        for w in ("MSG-X", "PICK-X", "ERR-X", "NOTE-X", "ALREADY-X", "REASON-X", "T1", "T3"):
            self.assertIn(w, self.O["panel_text"])
        self.assertTrue(self.O["cmd"])
        self.assertEqual(self.O["cb_n"], 2)
        self.assertEqual(self.O["cb_checked"], [True, False])

    def test_panel_structure(self):
        self.assertEqual(self.O["list_n"], 1)
        self.assertEqual(self.O["row_n"], 2)
        self.assertEqual(self.O["actions_btns"], ["Resume 1 ticked", "Cancel"])

    def test_picker_survives_update(self):
        self.assertTrue(self.O["kept_panel"])
        self.assertEqual(self.O["kept_boxes"], 2)

    def test_confirm_posts_ticked_ids_once(self):
        self.assertEqual(self.O["conf_label"], "Resume 2 ticked")
        self.assertEqual(self.O["confirm_calls"], [{"confirm": ["s1", "s2"]}])
        self.assertEqual(self.O["refreshed"], 1)
        self.assertEqual(self.O["toast"], "SUM")

    def test_stale_confirm_shows_fresh_list_and_error(self):
        self.assertIn("STALE-X", self.O["stale_text"])
        self.assertIn("MSG-X", self.O["stale_text"])
        self.assertEqual(self.O["stale_ticks"], [True, True])      # the user's tick on s2 survives the fresh list

    def test_watch_job_handoff(self):
        self.assertTrue(self.O["a_after_switch"])
        self.assertEqual(self.O["b_after_switch"], 0)
        self.assertTrue(self.O["b_after_done"])
        self.assertEqual(self.O["a_total"], 1)
        self.assertEqual(self.O["c_after_failed_poll"], 0)

    def test_config_host(self):
        self.assertEqual(self.O["cfg_rows"], 2)
        self.assertEqual(self.O["cfg_btn_in_claude"], 1)
        self.assertEqual(self.O["cfg_btn_in_auggie"], 0)
        self.assertEqual(self.O["cfg_panel"], 1)


if __name__ == "__main__":
    unittest.main()
