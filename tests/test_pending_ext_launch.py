"""ExtLaunch.openAt (ext_launch.js) -- the single Resume path. Runs the real file under node."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "aitracker", "web", "ext_launch.js")

HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const calls = [];
let reply = {status: 200, j: {tty: 't1'}};
const win = {open: () => ({})};
const ctx = {
  window: win, EXT: [], SIDE_EXT: [], cur: null, toast() {}, esc: s => s, alert() {},
  document: {getElementById: () => null, addEventListener() {}, body: {appendChild() {}},
             createElement: () => ({style: {}, addEventListener() {}, setAttribute() {}})},
  location: {hostname: 'x', origin: 'http://x', pathname: '/'},
  fetch: (u, o) => {
    calls.push({u, body: JSON.parse(o.body)});
    if (reply.fail) return Promise.reject(new Error('down'));
    return Promise.resolve({ok: reply.status < 400, status: reply.status, json: () => Promise.resolve(reply.j)});
  },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
(async () => {
  const out = {};
  out.ok = await win.ExtLaunch.openAt('/tmp/p', 'new', 'do it');
  out.body = calls[0].body;
  calls.length = 0;
  await win.ExtLaunch.openAt('/tmp/p', 'new');
  out.noprompt = calls[0].body;
  reply = {status: 400, j: {error: 'bad cwd'}};
  out.err = await win.ExtLaunch.openAt('/tmp/p', 'new', 'x');
  reply = {fail: true};
  out.net = await win.ExtLaunch.openAt('/tmp/p', 'new', 'x');
  reply = {status: 200, j: {tty: 't1'}};
  calls.length = 0;
  await win.ExtLaunch.openAt('~', 'new', '/login', {gateway: 'anthropic'});
  out.gw = calls[0].body;
  calls.length = 0;
  await win.ExtLaunch.openAt('~', 'new', '/login', {gateway: 'bedrock'});
  out.gwbad = calls[0].body;
  reply = {status: 200, j: {tty: 'L1', renderer: 'xterm', notice: 'n'}};
  const wo = []; win.open = (...a) => { wo.push(a); return {}; };
  out.notab = await win.ExtLaunch.openAt('~', 'new', '/login', {gateway: 'anthropic', tab: false});
  out.notabOpens = wo.length;
  out.tabOpens = (await win.ExtLaunch.openAt('~', 'new', '/login', {gateway: 'anthropic'}), wo.length);
  reply = {status: 200, j: {tty: 'R1', session: 'S9'}};
  calls.length = 0; wo.length = 0;
  await win.ExtLaunch.openAt('/w', 'resume', 'go', {session: 'S9'});
  out.sess = calls[0].body;
  out.sessUrl = wo[0][0];
  const binds = []; win.ExtVT = {bindTty: (t, s) => binds.push([t, s]), confirmRecreate: (j, retry) => { out.confirmArg = j; out.retry = retry; }};
  reply = {status: 409, j: {error: 'gone', recreate: {token: 'T'}}};
  calls.length = 0;
  const onRes = [];
  out.r409 = await win.ExtLaunch.openAt('/w', 'resume', 'go', {session: 'S9', onResult: x => onRes.push(x)});
  reply = {status: 429, j: {error: 'too many'}};
  out.retry({recreate: 'T'});
  await new Promise(r => setTimeout(r, 20));
  out.onRes = onRes;
  reply = {status: 200, j: {tty: 'R2', session: 'S9'}};
  out.retry({recreate: 'T'});
  await new Promise(r => setTimeout(r, 20));
  out.calls409 = calls.map(c => c.body);
  reply = {status: 200, j: {tty: 'R3', session: 'S9', attached: true}};
  const toasts = []; ctx.toast = (...a) => toasts.push(a);
  out.attached = await win.ExtLaunch.openAt('/w', 'resume', 'go', {session: 'S9'});
  out.toasts = toasts; out.binds = binds;
  reply = {fail: true};
  out.empty = await win.ExtLaunch.openAt('  ', 'new', 'x');
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class OpenAt(unittest.TestCase):
    def test_openat(self):
        with tempfile.TemporaryDirectory() as d:
            h = os.path.join(d, "h.js")
            with open(h, "w") as f:
                f.write(HARNESS)
            r = subprocess.run(["node", h, JS], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout)
        self.assertEqual(o["ok"], {"ok": True})
        self.assertEqual(o["body"]["prompt"], "do it")
        self.assertEqual(o["body"]["cwd"], "/tmp/p")
        self.assertEqual(o["body"]["mode"], "new")
        self.assertNotIn("prompt", o["noprompt"])
        self.assertEqual(o["err"], {"ok": False, "error": "bad cwd"})
        self.assertFalse(o["net"]["ok"])
        self.assertIn("down", o["net"]["error"])
        self.assertFalse(o["empty"]["ok"])
        self.assertEqual(o["gw"]["gateway"], "anthropic")
        self.assertEqual(o["gw"]["prompt"], "/login")
        self.assertNotIn("gateway", o["body"])
        self.assertNotIn("gateway", o["noprompt"])
        self.assertNotIn("gateway", o["gwbad"])
        # tab:false -> hand the pty back, open no tab; without it a tab opens as before
        self.assertEqual(o["notab"], {"ok": True, "tty": "L1", "renderer": "xterm", "notice": "n"})
        self.assertEqual(o["notabOpens"], 0)
        self.assertEqual(o["tabOpens"], 1)
        # resume a specific session: body carries it, the tab URL gets &sid=
        self.assertEqual(o["sess"]["session"], "S9")
        self.assertEqual(o["sess"]["mode"], "resume")
        self.assertIn("&sid=S9", o["sessUrl"])
        # 409 {recreate} -> confirm hook, then a retry carrying the token and the session
        self.assertEqual(o["r409"], {"ok": False, "error": "gone", "recreate": True})
        self.assertEqual(o["confirmArg"]["recreate"], {"token": "T"})
        self.assertEqual(o["onRes"][0], {"ok": False, "error": "too many"})   # C1: retry result reaches the caller
        self.assertEqual(o["onRes"][1], {"ok": True})
        self.assertNotIn("onResult", o["calls409"][1])
        self.assertEqual(len(o["calls409"]), 3)
        self.assertNotIn("recreate", o["calls409"][0])                         # C3
        for c in o["calls409"][1:]:
            self.assertEqual(c["prompt"], "go")
            self.assertEqual(c["mode"], "resume")
        self.assertEqual(o["calls409"][1]["recreate"], "T")
        self.assertEqual(o["calls409"][1]["session"], "S9")
        # attached -> the "nothing was typed" toast
        self.assertEqual(o["attached"], {"ok": True, "attached": True})        # C2
        self.assertEqual(o["toasts"][-1][0], "Session already open in a terminal")
        self.assertIn(["R3", "S9"], o["binds"])


if __name__ == "__main__":
    unittest.main()
