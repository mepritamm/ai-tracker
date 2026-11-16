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


if __name__ == "__main__":
    unittest.main()
