"""EXECUTED test (Node + a tiny fake DOM) for the Config dialog's Board tab pending-work rows (scan interval, cleanup mode). Skipped when node is absent.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

_WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "aitracker", "web")
_HAS_NODE = shutil.which("node") is not None

_HARNESS = r"""
class Cls { constructor(el){this.el=el;}
  _l(){return (this.el.className||'').split(/\s+/).filter(Boolean);}
  add(...c){const l=this._l();c.forEach(x=>{if(!l.includes(x))l.push(x)});this.el.className=l.join(' ');}
  remove(...c){this.el.className=this._l().filter(x=>!c.includes(x)).join(' ');}
  toggle(c,f){const on=f===undefined?!this._l().includes(c):f;on?this.add(c):this.remove(c);return on;}
  contains(c){return this._l().includes(c);} }
class El { constructor(tag){this.tagName=tag;this.children=[];this.parentNode=null;this.className='';
  this.attrs={};this.handlers={};this.classList=new Cls(this);this._text='';this.value='';this.style={};}
  get firstChild(){return this.children[0]||null;}
  get firstElementChild(){return this.children.find(c=>c.tagName)||null;}
  get offsetParent(){return {};}
  appendChild(c){if(c.parentNode)c.parentNode.removeChild(c);c.parentNode=this;this.children.push(c);return c;}
  removeChild(c){this.children=this.children.filter(x=>x!==c);c.parentNode=null;return c;}
  set innerHTML(v){this.children.forEach(c=>c.parentNode=null);this.children=[];this._text='';}
  get innerHTML(){return '';}
  set textContent(v){this.children=[];this._text=String(v);}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return this.attrs[k];}
  addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);}
  removeEventListener(){} focus(){}
  fire(t){(this.handlers[t]||[]).forEach(f=>f({target:this,preventDefault(){}}));}
  _all(out){this.children.forEach(c=>{if(c.tagName){out.push(c);c._all(out);}});return out;}
  _m(sel){return sel.split(',').some(s=>{s=s.trim();
    if(s[0]==='.')return this.classList.contains(s.slice(1));
    return s===this.tagName||s==='*';});}
  querySelectorAll(sel){return this._all([]).filter(e=>e._m(sel));}
  querySelector(sel){return this.querySelectorAll(sel)[0]||null;} }
class Txt { constructor(t){this.textContent=t;this.parentNode=null;} }
global.window = global; global.CR = undefined;
global.document = { createElement:t=>new El(t), createElementNS:(n,t)=>new El(t),
  createTextNode:t=>new Txt(t), addEventListener(){}, activeElement:null };
global.sessionStorage = {getItem(){return null;},setItem(){}};
global.location = {host:'x'};
// server state the stubbed fetch serves: configured flips with the launcher value
let launcher = '';
const calls = [];
const posts = [];
global.fetch = (url, opt) => {
  const json = (body, ok=true) => Promise.resolve({ok, json: () => Promise.resolve(body)});
  if (url === '/api/tunnel') return json({on:false});
  if (url === '/api/config' && opt && opt.method === 'POST') {
    const b = JSON.parse(opt.body); posts.push(b); return json({value: b.value});
  }
  if (url === '/api/config') return json({PENDING_INTERVAL: {value: ''}, PENDING_CLEAN: {value: 'dry-run'}});
  return json({});
};
const tick = () => new Promise(r => setTimeout(r, 20));
const SRC = require('fs').readFileSync(process.argv[2], 'utf8');
(async () => {
  (0, eval)(SRC);
  const root = new El('div');
  window.CR.dialogs.mount(root, {icon: () => ''});
  await tick();
  window.CR.dialogs.open('config', {section: 'Board'});
  await tick(); await tick();
  const row = (l) => root.querySelectorAll('.cr-cfg-row').filter(r => r.querySelector('.cr-cfg-row-name').textContent.startsWith(l))[0];
  const out = {};
  const scan = row('Pending-work scan'), clean = row('Pending-work cleanup');
  out.haveRows = !!(scan && clean);
  if (out.haveRows) {
    out.scanText = scan.textContent; out.cleanText = clean.textContent;
    const inp = scan.querySelector('input');
    out.defaultShown = inp.value;
    inp.value = '  2w '; inp.fire('change');
    const btns = clean.querySelectorAll('button');
    out.segLabels = btns.map(b => b.textContent);
    out.activeSeg = btns.filter(b => b.classList.contains('is-active')).map(b => b.textContent);
    btns.filter(b => b.textContent === 'Safe delete')[0].fire('click');
    await tick(); await tick();
  }
  out.posts = posts;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""

def _run():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_HARNESS)
        proc = subprocess.run(["node", p, os.path.join(_WEB, "ext_cr_dialogs.js")],
                              capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return json.loads(proc.stdout.strip().splitlines()[-1])


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class ConfigPendingWorkRows(unittest.TestCase):
    def test_pending_rows_in_board_tab(self):
        r = _run()
        self.assertTrue(r["haveRows"], "both pending-work rows render in the Board tab")
        self.assertEqual(r["defaultShown"], "90d")
        self.assertIn("TRACKER_PENDING_INTERVAL", r["scanText"])
        self.assertIn("TRACKER_PENDING_CLEAN", r["cleanText"])
        self.assertIn("2w", r["scanText"])
        self.assertEqual(r["segLabels"], ["Off", "List only", "Safe delete"])
        self.assertEqual(r["activeSeg"], ["List only"])
        self.assertIn("deletes nothing", r["cleanText"])
        self.assertIn("merged, clean, idle worktrees", r["cleanText"])
        self.assertIn("scratch folders", r["cleanText"])
        self.assertEqual(r["posts"], [{"key": "PENDING_INTERVAL", "value": "2w"},
                                      {"key": "PENDING_CLEAN", "value": "safe"}])


if __name__ == "__main__":
    unittest.main()
