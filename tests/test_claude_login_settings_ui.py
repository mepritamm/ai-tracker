"""EXECUTED test (Node + the fake DOM of test_cr_dialogs_pending_rows) for the Settings dialog's
"Claude Code login (/login)" block (Server tab). fetch and ExtLaunch are stubbed; no `claude`
process is ever started. Skipped without node.
"""
import json
import os
import subprocess
import tempfile
import unittest

try:
    from tests.test_update_settings_ui import _DOM, _WEB, _HAS_NODE
except ImportError:  # run as a bare file
    from test_update_settings_ui import _DOM, _WEB, _HAS_NODE

_BODY = r"""
const SCEN = JSON.parse(process.argv[3]);
const realST = setTimeout;
const gets = [], opens = [], listeners = {};
global.setTimeout = (f, ms) => ms === 8000 ? 0 : realST(f, 0);   // toast auto-dismiss never fires
global.window.location = {host: 'x', reload() {}};
global.addEventListener = (t, f) => { (listeners[t] = listeners[t] || []).push(f); };
const removed = [];
global.removeEventListener = (t, f) => { removed.push(t); const a = listeners[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1); };
let ROOT = null;
if (!El.prototype.remove) El.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
Object.defineProperty(El.prototype, 'isConnected', {configurable: true, get() {
  for (let n = this; n; n = n.parentNode) if (n === ROOT) return true; return false; }});
global.ExtLaunch = {openAt: (...a) => { opens.push(a); return Promise.resolve(SCEN.openReply || {ok: true}); }};
const mounts = [], closes = [], attached = [];
const M = {destroyed: 0, focused: 0, cb: {}};
let termEl = null, activeChild = null;
if (SCEN.vt) {
  global.ExtVT = {
    mountInto: (el, t, o) => {
      if (SCEN.mountThrows) throw new Error('boom');
      termEl = el; mounts.push({t, o});
      activeChild = new El('div');
      if (SCEN.focusAt) el.appendChild(activeChild);
      if (SCEN.forked) realST(() => (M.cb.f || (() => {}))(), 0);
      return {onStatus: f => { M.cb.s = f; }, onNotice: f => { M.cb.n = f; }, onForked: f => { M.cb.f = f; },
              focus: () => { M.focused++; if (SCEN.focusAt && M.focused >= SCEN.focusAt) document.activeElement = activeChild; },
              destroy: () => { M.destroyed++; }};
    },
    ttyBody: (tty, x, s) => ({tty, session: s}),
    ttyQuery: t => 'tty=' + t + '&session=',
  };
  if (SCEN.focusAt) { const oc = El.prototype.contains; El.prototype.contains = function (n) { if (this === termEl && n === activeChild) return true; return oc ? oc.call(this, n) : false; }; }
}
global.fetch = (url, opt) => {
  const json = (body, ok=true, status) => Promise.resolve({ok, status: status || (ok ? 200 : 400), json: () => Promise.resolve(body)});
  if (url === '/api/tunnel') return json({on: false});
  if (url === '/api/config') return json({});
  if (url === '/api/update') return json({kind: 'package', version: '1'});
  if (url.indexOf('/api/claude/auth') === 0) {
    gets.push(url);
    const rep = SCEN.authSeq ? SCEN.authSeq[Math.min(gets.length - 1, SCEN.authSeq.length - 1)] : SCEN.auth;
    return json(rep.body, rep.status < 400, rep.status);
  }
  if (url.indexOf('/api/term/attached?') === 0) {
    const seq = SCEN.attachedSeq || [200]; const st = seq[Math.min(attached.length, seq.length - 1)]; attached.push(url);
    if (st === 0) return Promise.reject(new Error('net'));
    return json(st === 200 ? {claude_attached: true, login_ok: false} : {error: 'e' + st}, st < 400, st);
  }
  if (url === '/api/term/close') { closes.push(JSON.parse(opt.body)); return json({ok: true}); }
  return json({});
};
const tick = async (n=6) => { for (let i = 0; i < n; i++) await new Promise(r => realST(r, 5)); };
const SRC = require('fs').readFileSync(process.argv[2], 'utf8');
(async () => {
  (0, eval)(SRC);
  const root = new El('div'); ROOT = root;
  window.CR.dialogs.mount(root, {icon: () => '', readOnly: () => !!SCEN.ro});
  await tick();
  window.CR.dialogs.open('config', {section: SCEN.tab || 'Server'});
  await tick();
  const q = (c) => root.querySelector('.' + c);
  const info = () => { const b = q('cr-claude-login-block'); return b ? {
    text: b.textContent, name: (b.querySelector('.cr-cfg-row-name') || {}).textContent,
    buttons: b.querySelectorAll('button').map(x => x.textContent)} : null; };
  const out = {before: info(), getsAfterOpen: gets.slice()};
  if (SCEN.click && out.before) {
    q('cr-claude-login-block').querySelectorAll('button')[0].fire('click'); await tick(10);
    out.afterClick = info(); out.opens = opens;
  }
  if (SCEN.vt && SCEN.click) {
    const cnt = (c) => root.querySelectorAll('.' + c).length;
    const snap = () => ({login: cnt('cr-dialog-login'), config: cnt('cr-dialog-config')});
    out.mounts = mounts; out.open = snap();
    if (SCEN.statusConnected && M.cb.s) { M.cb.s('connected'); out.statusAfter = (q('cr-dialog-login').querySelector('.cr-claude-login-status') || {}).textContent; }
    if (SCEN.manualClose) { await tick(3); window.CR.dialogs.close(); await tick(8); const n = attached.length; await tick(8); out.attachedAfterClose = attached.length - n; }
    else if (SCEN.escape) {
      await tick(3);
      (q('cr-dialog-login').handlers.keydown || []).slice().forEach(f => f({key: 'Escape', preventDefault() {}, stopPropagation() {}}));
      await tick(8);
    }
    else if (SCEN.ticks) { await tick(SCEN.ticks); const n = attached.length; await tick(10); out.attachedExtra = attached.length - n; }
    else await tick(15);
    out.end = snap(); out.destroyed = M.destroyed; out.closes = closes; out.focused = M.focused;
    out.conn = (q('cr-claude-login-conn') || {}).textContent; out.gets = gets;
    const btn = q('cr-claude-login-block'); out.btnDisabled = btn ? !!btn.querySelectorAll('button')[0].attrs.disabled : null;
    out.attached = attached.length;
    out.toasts = root.querySelectorAll('.cr-toast-title').map(x => x.textContent);
    out.block = btn ? btn.textContent : null;
    while (root.querySelectorAll('.cr-dialog-wrap').length) { const b = root.querySelectorAll('.cr-dialog-wrap').length; window.CR.dialogs.close(); if (root.querySelectorAll('.cr-dialog-wrap').length >= b) break; }
  }
  if (SCEN.focus) { (listeners.focus || []).slice().forEach(f => f()); await tick(10); out.afterFocus = info(); out.gets = gets; }
  if (SCEN.reopen) {
    window.CR.dialogs.close(); await tick();
    const g0 = gets.length;
    (listeners.focus || []).slice().forEach(f => f()); await tick(10);
    out.closedGets = gets.length - g0; out.removed = removed.slice(); out.leftAfterClose = (listeners.focus || []).length;
    window.CR.dialogs.open('config', {section: 'Server'}); await tick();
    const g1 = gets.length;
    (listeners.focus || []).slice().forEach(f => f()); await tick(10);
    out.reopenGets = gets.length - g1;
  }
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run(scen):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_DOM + _BODY)
        proc = subprocess.run(["node", p, os.environ.get("CR_DIALOGS_SRC") or os.path.join(_WEB, "ext_cr_dialogs.js"), json.dumps(scen)],
                              capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _auth(logged_in, **kw):
    d = {"available": True, "logged_in": logged_in, "auth_method": "claude.ai" if logged_in else "none",
         "subscription": "max" if logged_in else None,
         "label": "Claude subscription" if logged_in else "not logged in", "error": None}
    d.update(kw)
    return {"status": 200, "body": d}


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class ClaudeLoginBlock(unittest.TestCase):
    def go(self, auth, **kw):
        kw.setdefault("tab", "Server")
        return _run(dict(auth=auth, **kw))

    def test_name_warning_and_logged_out_button(self):
        r = self.go(_auth(False))
        self.assertEqual(r["before"]["name"], "Claude Code login (/login)")
        self.assertIn("every Claude Code session on this machine", r["before"]["text"])
        self.assertIn("not logged in", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Log in"])
        self.assertTrue(r["getsAfterOpen"] and set(r["getsAfterOpen"]) == {"/api/claude/auth"})

    def test_logged_in_shows_switch_account(self):
        r = self.go(_auth(True))
        self.assertIn("Claude subscription", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Switch account"])

    def test_click_opens_login_terminal_once(self):
        r = self.go(_auth(True), click=True)
        self.assertEqual(r["opens"], [["~", "new", "/login", {"gateway": "anthropic"}]])

    def vt(self, **kw):
        return self.go(_auth(False), click=True, vt=True, **kw)

    def test_inline_open_mounts_over_config(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, statusConnected=True, attachedSeq=[200])
        self.assertEqual(r["opens"], [["~", "new", "/login", {"gateway": "anthropic", "tab": False}]])
        self.assertEqual(r["open"], {"login": 1, "config": 1})
        self.assertEqual(r["mounts"], [{"t": {"tty": "L1"}, "o": {"renderer": "grid"}}])
        self.assertIn("Complete the login", r["statusAfter"])   # connection status never overwrites guidance

    def test_pty_gone_auto_closes(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200, 404])
        self.assertEqual(r["end"], {"login": 0, "config": 1})
        self.assertEqual(r["closes"], [])
        self.assertEqual(r["destroyed"], 1)
        self.assertIn("/api/claude/auth?fresh=1", r["gets"])
        self.assertFalse(r["btnDisabled"])

    def test_manual_close_posts_close_once(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200], manualClose=True)
        self.assertEqual(r["closes"], [{"tty": "L1", "session": ""}])
        self.assertEqual(r["destroyed"], 1)
        self.assertIn("/api/claude/auth?fresh=1", r["gets"])
        self.assertEqual(r["attachedAfterClose"], 0)

    def test_live_pty_keeps_terminal(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200], ticks=12)
        self.assertEqual(r["destroyed"], 0)
        self.assertEqual(r["open"]["login"], 1)
        self.assertEqual(r["end"]["login"], 1)

    def test_poll_error_stops_poll(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[401], ticks=6)
        self.assertEqual(r["attachedExtra"], 0)
        self.assertIn("e401", r["conn"])
        self.assertEqual(r["destroyed"], 0)

    def test_escape_in_terminal_closes_modal(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200], escape=True)
        self.assertEqual(r["end"], {"login": 0, "config": 1})
        self.assertEqual(r["closes"], [{"tty": "L1", "session": ""}])
        self.assertEqual(r["destroyed"], 1)

    def test_pty_exit_without_login_no_toast(self):
        r = self.go(_auth(False), click=True, vt=True, openReply={"ok": True, "tty": "L1", "renderer": "grid"},
                    attachedSeq=[200, 404], authSeq=[_auth(False), _auth(False)])
        self.assertNotIn("Logged in", r["toasts"])

    def test_pty_exit_after_login_toasts_once(self):
        r = self.go(_auth(False), click=True, vt=True, openReply={"ok": True, "tty": "L1", "renderer": "grid"},
                    attachedSeq=[200, 404], authSeq=[_auth(False), _auth(True)])
        self.assertEqual(r["toasts"].count("Logged in"), 1)

    def test_blips_capped(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[0], ticks=14)
        self.assertEqual(r["attached"], 5)
        self.assertIn("net", r["conn"])

    def test_blip_recovers(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[0, 0, 200, 404])
        self.assertEqual(r["end"], {"login": 0, "config": 1})
        self.assertEqual(r["closes"], [])

    def test_open_throw_closes_pty_and_reenables(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, mountThrows=True)
        self.assertEqual(r["closes"], [{"tty": "L1", "session": ""}])
        self.assertFalse(r["btnDisabled"])
        self.assertIn("Log in failed", r["block"])

    def test_focus_retry_until_focused(self):
        r = self.vt(openReply={"ok": True, "tty": "L1", "renderer": "grid"}, attachedSeq=[200], forked=True, focusAt=3, ticks=12)
        self.assertEqual(r["focused"], 3)   # retried until focus landed, then stopped

    def test_open_failure_shown(self):
        r = self.go(_auth(False), click=True, openReply={"ok": False, "error": "X"})
        self.assertIn("Log in failed: X", r["afterClick"]["text"])

    def test_403_message(self):
        r = self.go({"status": 403, "body": {"error": "forbidden"}})
        self.assertIn("Login status is shown on this machine only", r["before"]["text"])

    def test_unknown_status_offers_log_in(self):
        r = self.go(_auth(False, available=False, label="", error="claude not found"))
        self.assertEqual(r["before"]["buttons"], ["Log in"])
        self.assertIn("claude not found", r["before"]["text"])

    def test_closed_dialog_listener_removes_itself_and_reopen_registers_once(self):
        r = self.go(_auth(False), reopen=True)
        self.assertEqual(r["closedGets"], 0)             # detached block: no status GET on focus
        self.assertTrue(r["removed"] and set(r["removed"]) == {"focus"})
        self.assertEqual(r["leftAfterClose"], 0)         # every listener removed itself
        self.assertEqual(r["reopenGets"], 1)             # one live block -> one GET, no double-register

    def test_read_only_has_no_block(self):
        r = self.go(_auth(False), ro=True)
        self.assertIsNone(r["before"])

    def test_not_fetched_off_server_tab(self):
        r = self.go(_auth(False), tab="Board")
        self.assertIsNone(r["before"])
        self.assertEqual(r["getsAfterOpen"], [])

    def test_focus_refetches_fresh(self):
        r = self.go(None, authSeq=[_auth(False), _auth(True)], focus=True)
        self.assertEqual(r["gets"][0], "/api/claude/auth")
        self.assertIn("/api/claude/auth?fresh=1", r["gets"])
        self.assertEqual(r["afterFocus"]["buttons"], ["Switch account"])


if __name__ == "__main__":
    unittest.main()
