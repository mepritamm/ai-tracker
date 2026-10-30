"""EXECUTED test (Node + a tiny fake DOM) for the Config dialog's Terminal section:
the "OpenRouter: launcher not configured" note must follow the SERVER's
OPENROUTER_CONFIGURED flag live -- after a successful POST of OPENROUTER_LAUNCHER the
dialog re-reads GET /api/config and toggles the note in place (no re-render, so focus and
the row's Saved badge survive), instead of keeping it painted from the first open. Skipped when `node` is absent."""
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
global.fetch = (url, opt) => {
  calls.push((opt && opt.method || 'GET') + ' ' + url);
  const json = (body, ok=true) => Promise.resolve({ok, json: () => Promise.resolve(body)});
  if (url === '/api/tunnel') return json({on:false});
  if (url === '/api/config' && opt && opt.method === 'POST') {
    const b = JSON.parse(opt.body);
    if (b.key === 'OPENROUTER_LAUNCHER') launcher = b.value;
    return json({value: b.value});
  }
  if (url === '/api/config') return json({OPENROUTER_CONFIGURED: launcher !== '',
    OPENROUTER_LAUNCHER: {value: launcher}, OPENROUTER_SLOTS_FILE: {value: ''}});
  return json({});
};
const tick = () => new Promise(r => setTimeout(r, 20));
const SRC = require('fs').readFileSync(process.argv[2], 'utf8');
(async () => {
  (0, eval)(SRC);
  const root = new El('div');
  window.CR.dialogs.mount(root, {icon: () => ''});
  await tick();
  window.CR.dialogs.open('config', {section: 'Terminal'});
  await tick();
  const NOTE = 'launcher not configured';
  const has = () => root.querySelectorAll('p').some(n => !n.hidden && n.textContent.includes(NOTE));
  const rowInput = (label) => root.querySelectorAll('.cr-cfg-row')
    .filter(r => r.querySelector('.cr-cfg-row-name').textContent.startsWith(label))[0].querySelector('input');
  const out = {before: has()};
  const slot = rowInput('OpenRouter slot file');
  const inp = rowInput('OpenRouter launcher');
  inp.value = '/bin/launch'; inp.fire('change');
  await tick(); await tick();
  out.afterSet = has();
  out.badge = root.querySelectorAll('.cr-cfg-row').filter(r => r.querySelector('.cr-cfg-row-name').textContent.startsWith('OpenRouter launcher'))[0]
    .querySelector('.cr-cfg-status').textContent;
  out.sameSlot = rowInput('OpenRouter slot file') === slot;
  const n0 = calls.filter(c => c === 'GET /api/config').length;
  slot.value = '/tmp/slots.env'; slot.fire('change');
  await tick(); await tick();
  out.slotRefetch = calls.filter(c => c === 'GET /api/config').length - n0;
  const inp2 = rowInput('OpenRouter launcher');
  inp2.value = ''; inp2.fire('change');
  await tick(); await tick();
  out.afterClear = has();
  out.calls = calls;
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
class ConfigOpenRouterNoteLive(unittest.TestCase):
    def test_note_follows_server_flag_after_launcher_commit(self):
        r = _run()
        self.assertTrue(r["before"], "note shown while server says not configured")
        self.assertFalse(r["afterSet"], "note must vanish after launcher saved")
        self.assertEqual(r["badge"], "Saved", "no re-render: Saved badge survives")
        self.assertTrue(r["sameSlot"], "no re-render: other inputs keep identity/focus")
        self.assertEqual(r["slotRefetch"], 0, "slot file commit must not refetch config")
        self.assertTrue(r["afterClear"], "note must reappear after launcher cleared")


if __name__ == "__main__":
    unittest.main()
