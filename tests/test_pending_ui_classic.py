"""Pending-work shared SPA client + classic card (plan v3.1 step 12 + addendum A1).

Runs the REAL aitracker/web/app.js under Node with a persistent-element DOM stub and a scripted fetch;
no server is started. Also covers A1: Copy prompt is always present, and two /api/list polls with
different X-Server-Started reload the page exactly once.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "aitracker", "web", "app.js")
sys.path.insert(0, _ROOT)

_PRE = r"""
globalThis.window = globalThis;
var REG = {};
function makeEl(tag) {
  var el = { tagName: (tag || "div").toUpperCase(), id: "", className: "", style: {}, dataset: {}, children: [],
    classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {}, addEventListener() {},
    removeEventListener() {}, remove() {}, append() {}, select() {}, setSelectionRange() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, closest() { return null; }, focus() {}, click() {},
    textContent: "", hidden: false, value: "", onclick: null, _h: "" };
  el.appendChild = function (c) { this.children.push(c); return c; };
  el.insertBefore = function (c, ref) { this.children.unshift(c); return c; };
  Object.defineProperty(el, "innerHTML", { get() { return el._h; }, set(v) { el._h = v; if (v === "") el.children = []; } });
  return el;
}
window.document = {
  createElement: (t) => makeEl(t), createTextNode: () => makeEl(),
  getElementById: (id) => { if (!REG[id]) { REG[id] = makeEl(); REG[id].id = id; } return REG[id]; },
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {},
  dispatchEvent() {}, documentElement: makeEl("html"), body: makeEl("body"), head: makeEl("head"), readyState: "complete"
};
var _ls = {};
window.localStorage = { getItem: (k) => (k in _ls) ? _ls[k] : null, setItem: (k, v) => { _ls[k] = v; }, removeItem: (k) => { delete _ls[k]; } };
window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
var RELOADS = 0;
window.location = { href: "", search: "", pathname: "/", reload() { RELOADS++; } };
var CLIP = [];
Object.defineProperty(globalThis, "navigator", { configurable: true, writable: true,
  value: { userAgent: "node", clipboard: { writeText: (t) => { CLIP.push(t); return Promise.resolve(); } } } });
window.CustomEvent = function (type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});
var CALLS = [];
var ROUTES = {};   // url -> () => response
window.fetch = function (url, opts) {
  CALLS.push({ url: url, method: (opts && opts.method) || "GET" });
  var f = ROUTES[String(url).split("?")[0]];
  if (!f) return Promise.resolve({ ok: false, headers: { get: () => null }, json: () => Promise.resolve({}) });
  return Promise.resolve().then(f);
};
function okJson(o, hdr) { return { ok: true, headers: { get: (k) => (hdr && hdr[k]) || null }, json: () => Promise.resolve(o) }; }
function flush() { return new Promise((r) => setImmediate(r)); }
function find(el, pred) {
  if (pred(el)) return el;
  for (var c of el.children || []) { var f = find(c, pred); if (f) return f; }
  return null;
}
var REPORT = { items: [{ id: "abc123abc123", label: "2 uncommitted · worktree", path: "/w/x", branch: "feat", verdict: "pending" }],
  tmp: [], running: false, card: { show: true, title: "Pending work", summary: "1 worktree with unfinished work (oldest idle 3d)", count: 1 } };
var ITEM = { title: "feat @ /w/x", when: "now", md: "status", resume: { cwd: "/w", prompt: "Use the worktree-cleanup skill on /w/x" } };
var OUT = {};
"""

_DRIVER = r"""
(async function () {
  ROUTES["/api/pending"] = () => okJson(REPORT);
  ROUTES["/api/pending/item"] = () => okJson(ITEM);
  ROUTES["/api/pending/run"] = () => ({ ok: true, headers: { get: () => null }, json: () => Promise.resolve({ running: true }) });

  // card hidden when show=false, shown + clickable when true
  pendingCache = { items: [], card: { show: false, title: "Pending work", summary: "" } };
  renderPendingSide();
  OUT.hidden_when_false = $("pendside").hidden === true;
  pendingCache = REPORT; renderPendingSide();
  OUT.shown_when_true = $("pendside").hidden === false && $("pendside").innerHTML.indexOf("1 worktree with unfinished work") >= 0;
  $("pendside").onclick();
  OUT.click_opens_list = $("msgmodal").style.display === "flex" && $("msgtitle").textContent === "Pending work";

  // syncModal must not overwrite the list: modal's live re-sync state is cleared
  var refreshed = 0;
  curModal = { open() {}, i: 0, n: 3, fromEnd: 2, len: () => 3, live: true, refresh() { refreshed++; } };
  openPendingList(REPORT);
  syncModal();
  OUT.sync_cleared = curModal === null && refreshed === 0;

  // list rows + Scan now
  var scan = find($("msgbody"), (e) => e.textContent === "Scan now");
  OUT.scan_btn = !!scan;
  scan.onclick(); await flush(); await flush();
  OUT.scan_text = scan.textContent;
  OUT.scan_posted = CALLS.some((c) => c.url === "/api/pending/run" && c.method === "POST");

  // item modal: Resume + Copy prompt, with ExtLaunch
  var launched = [];
  window.ExtLaunch = { openAt: (c, m, p) => { launched.push([c, m, p]); return Promise.resolve({ ok: true }); } };
  await openPendingItem("abc123abc123");
  var res = find($("msgbody"), (e) => e.textContent === "Resume"), cp = find($("msgbody"), (e) => e.textContent === "Copy prompt");
  OUT.has_resume = !!res; OUT.has_copy_with = !!cp;
  res.onclick(); await flush();
  OUT.launched = launched;
  cp.onclick(); await flush();
  OUT.clip = CLIP.slice();

  // openAt resolving {ok:false}: error shown
  window.ExtLaunch = { openAt: () => Promise.resolve({ ok: false, error: "no slots" }) };
  await openPendingItem("abc123abc123");
  find($("msgbody"), (e) => e.textContent === "Resume").onclick(); await flush(); await flush();
  OUT.err_shown = find($("msgbody"), (e) => (e.textContent || "").indexOf("no slots") >= 0) !== null;

  // without ExtLaunch (standalone dist build): message + Copy prompt STILL present
  delete window.ExtLaunch;
  await openPendingItem("abc123abc123");
  OUT.has_copy_without = !!find($("msgbody"), (e) => e.textContent === "Copy prompt");
  find($("msgbody"), (e) => e.textContent === "Resume").onclick(); await flush();
  OUT.unavailable = !!find($("msgbody"), (e) => (e.textContent || "").indexOf("Resume unavailable in this build — use Copy prompt") >= 0);

  // fetch: throttled to one per 60s, never throws
  CALLS.length = 0; pendingCache = null; pendingAt = 0; pendingDirty = false; trackerReadOnly = false;
  await loadPending(); await loadPending();
  OUT.throttled = CALLS.filter((c) => c.url === "/api/pending").length;
  pendingAt = 0; ROUTES["/api/pending"] = () => { throw new Error("boom"); };
  try { await loadPending(); OUT.no_throw = true; } catch (e) { OUT.no_throw = false; }

  // read-only: no fetch at all, card hidden
  ROUTES["/api/pending"] = () => okJson(REPORT);
  CALLS.length = 0; pendingAt = 0; trackerReadOnly = true;
  await loadPending();
  OUT.readonly_fetches = CALLS.length;
  renderPendingSide();
  OUT.readonly_hidden = $("pendside").hidden === true;
  trackerReadOnly = false;

  // A1: two polls with different X-Server-Started -> exactly one reload
  var n = 0, started = ["100", "100", "200", "200"];
  ROUTES["/api/list"] = () => okJson([], { "X-Server-Started": started[Math.min(n++, 3)] });
  for (var i = 0; i < 4; i++) { await loadSide(); await flush(); }
  OUT.reloads = RELOADS;
  // S1: real buttons + keyboard on the card and rows
  REPORT.running = false; pendingCache = REPORT; renderPendingSide(); openPendingList(REPORT);
  OUT.scan_is_button = find($("msgbody"), (e) => e.textContent === "Scan now").tagName === "BUTTON";
  var row = find($("msgbody"), (e) => e.className.indexOf("pendrow") >= 0);
  OUT.row_focusable = row.tabIndex === 0;
  CALLS.length = 0;
  if (row.onkeydown) row.onkeydown({ key: "Enter", preventDefault() {} }); await flush(); await flush();
  OUT.row_key_fetches_item = CALLS.some((c) => c.url.indexOf("/api/pending/item") === 0);
  OUT.item_btns = ["Resume", "Copy prompt"].map((t) => { var b = find($("msgbody"), (e) => e.textContent === t); return b ? b.tagName : null; });
  $("msgmodal").style.display = "none";
  if ($("pendside").onkeydown) $("pendside").onkeydown({ key: "Enter", preventDefault() {} });
  OUT.card_key_opens = $("msgmodal").style.display === "flex";

  // N5: a refused scan shows the server's error
  ROUTES["/api/pending/run"] = () => ({ ok: false, headers: { get: () => null }, json: () => Promise.resolve({ error: "scan refused: tmp checkout" }) });
  REPORT.running = false; openPendingList(REPORT);
  var sb = find($("msgbody"), (e) => e.textContent === "Scan now");
  sb.onclick(); await flush(); await flush(); await flush();
  OUT.scan_refused_text = sb.textContent;

  // as_of rendered when present, absent otherwise
  pendingCache = { items: [], card: { show: true, title: "Pending work", summary: "s", as_of: "2026-11-15" } }; renderPendingSide();
  OUT.as_of_shown = $("pendside").innerHTML.indexOf("2026-11-15") >= 0;
  pendingCache = REPORT; renderPendingSide();
  OUT.as_of_absent = $("pendside").innerHTML.indexOf("as of") < 0;

  // F10: restart reload deferred while a text field has focus, done once the user stops typing
  var before = RELOADS;
  document.activeElement = { tagName: "TEXTAREA" };
  ROUTES["/api/list"] = () => okJson([], { "X-Server-Started": "300" });
  await loadSide(); await flush();
  OUT.deferred_while_typing = RELOADS === before;
  document.activeElement = null;
  await loadSide(); await flush();
  OUT.reloaded_after_typing = RELOADS === before + 1;
  console.log("@@OUT@@" + JSON.stringify(OUT));
})().catch((e) => { console.log("@@ERR@@" + (e && e.stack || e)); });
"""


@unittest.skipUnless(shutil.which("node"), "node not available")
class TestPendingUiClassic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_APP, encoding="utf-8") as fh:
            src = fh.read()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "h.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_PRE + src + "\n" + _DRIVER)
            p = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
        out = p.stdout
        if "@@OUT@@" not in out:
            raise AssertionError("harness failed rc=%s\n%s\n%s" % (p.returncode, out[-2000:], p.stderr[-2000:]))
        cls.O = json.loads(out.split("@@OUT@@", 1)[1].strip().splitlines()[0])

    def test_card_hidden_when_show_false(self):
        self.assertTrue(self.O["hidden_when_false"])

    def test_card_shown_and_clickable_when_true(self):
        self.assertTrue(self.O["shown_when_true"])
        self.assertTrue(self.O["click_opens_list"])

    def test_sync_modal_does_not_overwrite_list(self):
        self.assertTrue(self.O["sync_cleared"])

    def test_scan_now_posts_and_shows_scanning(self):
        self.assertTrue(self.O["scan_btn"])
        self.assertTrue(self.O["scan_posted"])
        self.assertEqual(self.O["scan_text"], "scanning…")

    def test_resume_calls_openat_with_server_prompt(self):
        self.assertTrue(self.O["has_resume"])
        self.assertEqual(self.O["launched"], [["/w", "new", "Use the worktree-cleanup skill on /w/x"]])

    def test_copy_prompt_always_present_and_copies(self):
        self.assertTrue(self.O["has_copy_with"])
        self.assertTrue(self.O["has_copy_without"])
        self.assertEqual(self.O["clip"], ["Use the worktree-cleanup skill on /w/x"])

    def test_resume_error_and_unavailable_are_visible(self):
        self.assertTrue(self.O["err_shown"])
        self.assertTrue(self.O["unavailable"])

    def test_fetch_throttled_never_throws_and_readonly_skips(self):
        self.assertEqual(self.O["throttled"], 1)
        self.assertTrue(self.O["no_throw"])
        self.assertEqual(self.O["readonly_fetches"], 0)
        self.assertTrue(self.O["readonly_hidden"])

    def test_server_started_change_reloads_once(self):
        self.assertEqual(self.O["reloads"], 1)

    def test_keyboard_reachable_controls(self):
        self.assertTrue(self.O["scan_is_button"])
        self.assertEqual(self.O["item_btns"], ["BUTTON", "BUTTON"])
        self.assertTrue(self.O["row_focusable"])
        self.assertTrue(self.O["row_key_fetches_item"])
        self.assertTrue(self.O["card_key_opens"])

    def test_refused_scan_shows_server_error(self):
        self.assertEqual(self.O["scan_refused_text"], "scan refused: tmp checkout")

    def test_card_as_of_shown_only_when_present(self):
        self.assertTrue(self.O["as_of_shown"])
        self.assertTrue(self.O["as_of_absent"])

    def test_restart_reload_deferred_while_typing(self):
        self.assertTrue(self.O["deferred_while_typing"])
        self.assertTrue(self.O["reloaded_after_typing"])

    def test_pendside_survives_build_page(self):
        from aitracker import page
        html = page.build_page()
        self.assertIn("id=pendside", html)
        self.assertIn(".pendside{", html)
        self.assertIn("function openPendingList", html)


if __name__ == "__main__":
    unittest.main()
