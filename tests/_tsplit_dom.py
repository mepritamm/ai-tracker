"""Shared node harness for the split-button tests (not a test module: the leading underscore keeps
unittest discovery away).

It is the `_FAKE_DOM` + `_extract` + `_run` recipe of tests/test_term_split_menu.py grown just enough
for the WAI-ARIA split button in app.js: createElement, attributes, textContent, appendChild,
contains/isConnected, focus() -> document.activeElement, per-element listeners (several per type),
and `dispatch(el, type, init)` which runs the document CAPTURE listeners first, then the target, then
bubbles (stopPropagation honoured), plus stubs for getBoundingClientRect/getComputedStyle/location/fetch.

`helpers_js()` extracts every shared function out of the shipped app.js, so a test exercises the real
code.  Brace matching is why those functions keep `{`/`}` out of string and regex literals.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aitracker", "web")
HAS_NODE = shutil.which("node") is not None


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as fh:
        return fh.read()


def extract(src, name):
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", src)
    if not m:
        raise AssertionError("function %s() not found" % name)
    i = src.index("{", m.start())
    depth = 0
    for k in range(i, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():k + 1]
    raise AssertionError("unbalanced %s" % name)


def run(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(js)
        proc = subprocess.run(["node", p], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node failed: " + proc.stderr[-2000:])
    return json.loads(proc.stdout.split("OUT:", 1)[1])


FAKE_DOM = r"""
var window = globalThis;
function El(tag) {
  this.tagName = String(tag).toUpperCase(); this.nodeType = 1; this.children = []; this.parentNode = null;
  this.hidden = false; this.title = ""; this.style = {}; this.id = "";
  this._attrs = {}; this._cls = new Set(); this._text = ""; this._html = ""; this._listeners = [];
  this._rect = null; this._cs = null;
  var self = this;
  this.classList = {
    add: function () { for (var i = 0; i < arguments.length; i++) self._cls.add(arguments[i]); },
    remove: function () { for (var i = 0; i < arguments.length; i++) self._cls.delete(arguments[i]); },
    toggle: function (c, on) { if (on === undefined) on = !self._cls.has(c); if (on) self._cls.add(c); else self._cls.delete(c); return !!on; },
    contains: function (c) { return self._cls.has(c); },
  };
}
Object.defineProperty(El.prototype, "className", {
  get: function () { return Array.from(this._cls).join(" "); },
  set: function (v) { this._cls = new Set(String(v == null ? "" : v).split(/\s+/).filter(Boolean)); },
});
Object.defineProperty(El.prototype, "textContent", {
  get: function () { return this.children.length ? this.children.map(function (c) { return c.textContent; }).join("") : this._text; },
  set: function (v) { this.children.forEach(function (c) { c.parentNode = null; }); this.children = []; this._text = String(v); },
});
Object.defineProperty(El.prototype, "innerHTML", {   // like the bundle harness: stored, never parsed
  get: function () { return this._html; }, set: function (v) { this._html = String(v); },
});
Object.defineProperty(El.prototype, "isConnected", {
  get: function () { for (var n = this; n; n = n.parentNode) if (n === document) return true; return false; },
});
El.prototype.setAttribute = function (k, v) { this._attrs[k] = String(v); if (k === "class") this.className = v; if (k === "id") this.id = String(v); };
El.prototype.getAttribute = function (k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; };
El.prototype.hasAttribute = function (k) { return Object.prototype.hasOwnProperty.call(this._attrs, k); };
El.prototype.removeAttribute = function (k) { delete this._attrs[k]; };
El.prototype.appendChild = function (c) {
  if (c.parentNode) c.parentNode.removeChild(c);
  this.children.push(c); c.parentNode = this; return c;
};
El.prototype.removeChild = function (c) {
  var i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); c.parentNode = null; return c;
};
El.prototype.contains = function (n) { for (; n; n = n.parentNode) if (n === this) return true; return false; };
El.prototype.focus = function () { document.activeElement = this; };
El.prototype.addEventListener = function (type, fn, cap) { this._listeners.push({type: type, fn: fn, cap: cap === true}); };
El.prototype.getBoundingClientRect = function () {
  if (this.hidden) return {left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0};   // a hidden box measures 0x0
  return this._rect || {left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0};
};
var document = new El("html");
document.activeElement = null;
document.createElement = function (tag) { return new El(tag); };
function getComputedStyle(n) { return n._cs || {overflowX: "visible", overflowY: "visible"}; }
var location = {hostname: "localhost"};
var navigator = {userAgent: "node"};
var fetchCalls = [];
var fetchImpl = function () { return Promise.resolve({status: 400}); };
function fetch(url, opts) { fetchCalls.push({url: url, opts: opts}); return fetchImpl(url, opts); }

// Run listeners on `path` nodes for one phase.  cap: capture-only listeners; "target": all; false: bubble-only.
function _fire(node, e, phase) {
  node._listeners.slice().forEach(function (l) {
    if (l.type !== e.type) return;
    if (phase === "capture" && !l.cap) return;
    if (phase === "bubble" && l.cap) return;
    l.fn(e);
  });
}
// dispatch(el, type, init) -> the event.  Document capture listeners run first (a detached target never
// reaches the document), then the target, then the bubble phase; stopPropagation ends the walk.
function dispatch(target, type, init) {
  var e = Object.assign({type: type, target: target, defaultPrevented: false, _stopped: false,
    preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () { this._stopped = true; }}, init || {});
  var path = [];
  for (var n = target; n; n = n.parentNode) path.push(n);
  for (var i = path.length - 1; i >= 1 && !e._stopped; i--) _fire(path[i], e, "capture");
  if (!e._stopped) _fire(path[0], e, "target");
  for (var j = 1; j < path.length && !e._stopped; j++) _fire(path[j], e, "bubble");
  return e;
}
function mount(el) { document.appendChild(el); return el; }
var __n = 0;
function mkSplit(o) {
  var sp = termSplit(Object.assign({key: "k" + (++__n), primaryCls: "b", caretCls: "c", resumable: true}, o || {}));
  mount(sp); return sp;
}
function bindLog(sp) {
  var log = [];
  termSplitOn(sp, {resume: function () { log.push("resume"); }, open: function () { log.push("open"); },
    external: function () { log.push("external"); }});
  return log;
}
function isOpen(sp) { return sp._ts.caret.getAttribute("aria-expanded") === "true"; }
function resetExt() { TERM_EXT.allowed = null; TERM_EXT.probe = null; fetchCalls.length = 0; }
"""

# The shared functions, in dependency-free definition order (function declarations hoist anyway).
FUNCTIONS = (
    "trackerIsLocal", "termExtProbe", "termExtAllowed", "termExtDeny", "termResumable",
    "_tsplitPrune", "_tsplitOwner", "_tsplitIsOpen", "_tsplitShut", "_tsplitVisible", "_tsplitFit",
    "termSplit", "termSplitSet", "termSplitOn", "termSplitOpen", "termSplitClose",
    "_tsplitFocusTag", "termSplitSnapshot", "termSplitRestore", "_tsplitOutside",
    "termSplitOnClick", "termSplitOnPointerDown", "termSplitOnFocusOut", "termSplitOnKey",
)

_LISTENER_RE = re.compile(r'^document\.addEventListener\("(?:click|pointerdown|keydown|focusout)",termSplit\w+,true\);$', re.M)


def helpers_js(with_listeners=True):
    app = read("app.js")
    parts = ["const TERM_EXT={allowed:null,probe:null}; const TSPLITS={}; var sessions=[];"]
    parts += [extract(app, n) for n in FUNCTIONS]
    if with_listeners:
        parts += [m.group(0) for m in _LISTENER_RE.finditer(app)]
    return "\n".join(parts)


def go(body):
    """Run `body` (async-capable JS using the fake DOM + real helpers) and return its `out` dict."""
    js = (FAKE_DOM + helpers_js() + "\n(async function () {\nvar out = {};\n" + body +
          "\nconsole.log('OUT:' + JSON.stringify(out));\n})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });")
    return run(js)
