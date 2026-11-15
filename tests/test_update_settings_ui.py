"""EXECUTED test (Node + the tiny fake DOM of test_cr_dialogs_pending_rows) for the Settings
dialog's "Scheduled scan" (Board tab) and "Update" (Server tab) blocks, driven by a stubbed
fetch that serves the /api/scheduler and /api/update JSON schemas. Skipped without node.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

try:
    from tests.test_cr_dialogs_pending_rows import _HARNESS as _ROWS_HARNESS
except ImportError:  # run as a bare file
    from test_cr_dialogs_pending_rows import _HARNESS as _ROWS_HARNESS

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None
_DOM = _ROWS_HARNESS[:_ROWS_HARNESS.index("// server state the stubbed fetch")]

_BODY = r"""
const SCEN = JSON.parse(process.argv[3]);
const realST = setTimeout;
const posts = [];            // [url, parsedBody]
let reloads = 0;
let updateGets = 0;
let sched = SCEN.sched || {supported: true, installed: false, opted_out: false, kind: 'launchd', root: null, root_exists: false, last_exit: null};
let upd = SCEN.update || {};
let clock = 1000000;
Date.now = () => { clock += (SCEN.clockStep || 0); return clock; };
global.setTimeout = (f, ms) => realST(f, 0);
global.window.location = {host: 'x', reload() { reloads++; }};
global.fetch = (url, opt) => {
  const json = (body, ok=true, status) => Promise.resolve({ok, status: status || (ok ? 200 : 400), json: () => Promise.resolve(body)});
  const method = (opt && opt.method) || 'GET';
  const body = opt && opt.body ? JSON.parse(opt.body) : undefined;
  if (url === '/api/tunnel') return json({on: false});
  if (url === '/api/config') return json({});
  if (url === '/api/scheduler' && method === 'GET') return json(sched);
  if (url === '/api/scheduler') {
    posts.push([url, body]);
    sched = Object.assign({}, sched, SCEN.afterPost[body.action]);
    return json(sched);
  }
  if (url === '/api/pending/run') { posts.push([url, body]); return json({started: true}); }
  if (url === '/api/update' && method === 'GET') {
    updateGets++;
    const seq = SCEN.updateSeq;
    return json(seq && updateGets > 1 ? seq[Math.min(updateGets - 2, seq.length - 1)] : upd);
  }
  if (url === '/api/update/fetch') { posts.push([url, body]); upd = Object.assign({}, upd, SCEN.afterFetch || {}); return json(upd); }
  if (url === '/api/update/apply') {
    posts.push([url, body]);
    const r = SCEN.applyReplies.shift();
    return json(r.body, r.status < 400, r.status);
  }
  return json({});
};
const tick = async (n=6) => { for (let i = 0; i < n; i++) await new Promise(r => realST(r, 5)); };
const SRC = require('fs').readFileSync(process.argv[2], 'utf8');
(async () => {
  (0, eval)(SRC);
  const root = new El('div');
  window.CR.dialogs.mount(root, {icon: () => '', readOnly: () => !!SCEN.ro});
  await tick();
  window.CR.dialogs.open('config', {section: SCEN.tab});
  await tick();
  const q = (c) => root.querySelector('.' + c);
  const btns = (c) => { const b = q(c); return b ? b.querySelectorAll('button') : []; };
  const click = async (c, label) => {
    const b = btns(c).filter(x => x.textContent === label)[0];
    if (!b) throw new Error('no button ' + label + ' in ' + c);
    b.fire('click'); await tick(10);
  };
  const out = {};
  const sb = q('cr-sched-block'), ub = q('cr-update-block');
  out.hasSched = !!sb; out.hasUpdate = !!ub;
  const info = (c) => ({
    text: q(c) ? q(c).textContent : null,
    buttons: btns(c).map(b => b.textContent),
    disabled: btns(c).filter(b => b.attrs.disabled).map(b => b.textContent),
    hidden: q(c) ? q(c).style.display === 'none' : null,
  });
  if (SCEN.tab === 'Board') {
    out.before = info('cr-sched-block');
    for (const step of (SCEN.clicks || [])) { await click('cr-sched-block', step); out['after_' + step] = info('cr-sched-block'); }
  } else {
    out.before = info('cr-update-block');
    for (const step of (SCEN.clicks || [])) {
      await click('cr-update-block', step);
      out['after_' + step] = info('cr-update-block');
    }
  }
  out.posts = posts; out.reloads = reloads;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run(scen):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_DOM + _BODY)
        proc = subprocess.run(["node", p, os.path.join(_WEB, "ext_cr_dialogs.js"), json.dumps(scen)],
                              capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _git(**kw):
    d = {"kind": "git", "version": "1.1.0", "root": "/r", "branch": "main", "detached": False,
         "upstream": "personal/main", "head": "abcdef1234567", "head_subject": "Fix thing",
         "behind": 3, "ahead": 0, "dirty": [], "fetched_at": 1, "started_at": 100,
         "can_update": True, "reason": None, "terminals": 0, "pending_running": False,
         "restart_error": None}
    d.update(kw)
    return d


def _sched(**kw):
    d = {"supported": True, "installed": False, "opted_out": False, "kind": "launchd",
         "root": None, "root_exists": False, "last_exit": None}
    d.update(kw)
    return d


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class ScheduledScanBlock(unittest.TestCase):
    def go(self, sched, clicks=(), after=None, **kw):
        return _run(dict(tab="Board", sched=sched, clicks=list(clicks), afterPost=after or {}, **kw))

    def test_four_status_texts_and_buttons(self):
        r = self.go(_sched(installed=True, last_exit=0, root="/here", root_exists=True))
        self.assertIn("Installed (launchd) · last exit 0 · runs from /here", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])
        r = self.go(_sched())
        self.assertIn("Not installed", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Install", "Scan now"])
        r = self.go(_sched(opted_out=True))
        self.assertIn("Turned off (you uninstalled it)", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Install", "Scan now"])
        r = self.go(_sched(installed=True, root="/gone", root_exists=False))
        self.assertIn("Points at a missing checkout", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])

    def test_buttons_post_enum_action_and_rerender_from_response(self):
        r = self.go(_sched(), ["Install"], {"install": {"installed": True, "last_exit": 0, "root": "/x", "root_exists": True}})
        self.assertEqual(r["posts"], [["/api/scheduler", {"action": "install"}]])
        self.assertEqual(r["after_Install"]["buttons"], ["Reinstall", "Uninstall", "Scan now"])
        r = self.go(_sched(installed=True, root="/x", root_exists=True), ["Uninstall"],
                    {"uninstall": {"installed": False, "opted_out": True}})
        self.assertEqual(r["posts"], [["/api/scheduler", {"action": "uninstall"}]])
        self.assertIn("Turned off", r["after_Uninstall"]["text"])
        self.assertEqual(r["after_Uninstall"]["buttons"], ["Install", "Scan now"])

    def test_scan_now_posts_pending_run(self):
        r = self.go(_sched(), ["Scan now"])
        self.assertEqual(r["posts"], [["/api/pending/run", {}]])

    def test_hidden_when_unsupported_or_read_only(self):
        r = self.go(_sched(supported=False), ["Scan now"])
        self.assertFalse(r["before"]["hidden"])
        self.assertEqual(r["before"]["buttons"], ["Scan now"])
        self.assertIn("not available on this platform", r["before"]["text"])
        self.assertEqual(r["posts"], [["/api/pending/run", {}]])
        r = self.go(_sched(), ro=True)
        self.assertFalse(r["hasSched"])


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class UpdateBlock(unittest.TestCase):
    def go(self, update, clicks=(), **kw):
        return _run(dict(tab="Server", update=update, clicks=list(clicks), **kw))

    def test_status_reason_verbatim_and_button_disabled(self):
        r = self.go(_git(behind=0, can_update=False, reason="up to date (nothing to pull)", dirty=["M a.py"]))
        t = r["before"]["text"]
        self.assertIn("main @ abcdef1 — Fix thing", t)
        self.assertIn("0 behind personal/main", t)
        self.assertIn("Local changes: M a.py", t)
        self.assertIn("up to date (nothing to pull)", t)
        self.assertEqual(r["before"]["buttons"], ["Check for updates", "Update and restart"])
        self.assertEqual(r["before"]["disabled"], ["Update and restart"])

    def test_not_a_git_checkout_has_no_buttons(self):
        r = self.go(_git(kind="package", can_update=False, reason="Installed package (version 1.1.0) — reinstall it with uv to update"))
        self.assertIn("not a git checkout", r["before"]["text"])
        self.assertIn("reinstall it with uv", r["before"]["text"])
        self.assertEqual(r["before"]["buttons"], [])

    def test_check_for_updates_posts_fetch_and_rerenders(self):
        r = self.go(_git(behind=0, can_update=False, reason="up to date"), ["Check for updates"],
                    afterFetch={"behind": 2, "can_update": True, "reason": None})
        self.assertEqual(r["posts"], [["/api/update/fetch", {}]])
        self.assertIn("2 behind", r["after_Check for updates"]["text"])
        self.assertEqual(r["after_Check for updates"]["disabled"], [])

    def test_409_needs_confirm_then_reposts_confirmed_then_reload(self):
        r = self.go(_git(), ["Update and restart", "Update anyway"],
                    applyReplies=[{"status": 409, "body": {"error": "2 open terminals will close", "needs_confirm": True}},
                                  {"status": 202, "body": {"restarting": True, "recover": "RECOVER"}}],
                    updateSeq=[_git(started_at=100), _git(started_at=200)])
        self.assertIn("2 open terminals will close", r["after_Update and restart"]["text"])
        self.assertEqual(r["after_Update and restart"]["buttons"], ["Update anyway", "Cancel"])
        self.assertEqual(r["posts"], [["/api/update/apply", {"confirm_terminals": False}],
                                      ["/api/update/apply", {"confirm_terminals": True}]])
        self.assertEqual(r["reloads"], 1)

    def test_known_open_terminals_ask_before_posting(self):
        r = self.go(_git(terminals=1), ["Update and restart"],
                    applyReplies=[{"status": 409, "body": {"error": "3 open terminals will close", "needs_confirm": True}}])
        self.assertEqual(r["posts"], [["/api/update/apply", {"confirm_terminals": False}]])
        self.assertIn("3 open terminals will close", r["after_Update and restart"]["text"])

    def test_refusal_shown_verbatim(self):
        r = self.go(_git(), ["Update and restart"],
                    applyReplies=[{"status": 409, "body": {"error": "scan in progress"}}])
        self.assertIn("scan in progress", r["after_Update and restart"]["text"])

    def test_restart_error_shown_at_once_without_reload(self):
        r = self.go(_git(), ["Update and restart"],
                    applyReplies=[{"status": 202, "body": {"restarting": True, "recover": "R"}}],
                    updateSeq=[_git(started_at=100, restart_error="exec failed: ENOEXEC")])
        self.assertIn("exec failed: ENOEXEC", r["after_Update and restart"]["text"])
        self.assertEqual(r["reloads"], 0)

    def test_sixty_second_timeout_shows_recover_line(self):
        r = self.go(_git(), ["Update and restart"],
                    applyReplies=[{"status": 202, "body": {"restarting": True, "recover": "git -C /r checkout --detach abc"}}],
                    updateSeq=[_git(started_at=100)], clockStep=20000)
        self.assertIn("git -C /r checkout --detach abc", r["after_Update and restart"]["text"])
        self.assertEqual(r["reloads"], 0)

    def test_hidden_when_read_only(self):
        r = self.go(_git(), ro=True)
        self.assertFalse(r["hasUpdate"])


if __name__ == "__main__":
    unittest.main()
