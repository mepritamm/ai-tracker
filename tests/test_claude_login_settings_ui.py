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
global.setTimeout = (f, ms) => realST(f, 0);
global.window.location = {host: 'x', reload() {}};
global.addEventListener = (t, f) => { (listeners[t] = listeners[t] || []).push(f); };
const removed = [];
global.removeEventListener = (t, f) => { removed.push(t); const a = listeners[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1); };
let ROOT = null;
if (!El.prototype.remove) El.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
Object.defineProperty(El.prototype, 'isConnected', {configurable: true, get() {
  for (let n = this; n; n = n.parentNode) if (n === ROOT) return true; return false; }});
global.ExtLaunch = {openAt: (...a) => { opens.push(a); return Promise.resolve(SCEN.openReply || {ok: true}); }};
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
