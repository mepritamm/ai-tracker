"""Control Room terminal /login pill: rendered only from the server's `login_ok`.

Extract-and-stub (same recipe as test_cr_manage_terminals_parity): the real function text is
pulled out of ext_cr_term.js and run under node with stubbed st/el/fetch. No server, no claude.
Set LOGIN_PILL_SRC to point at another copy of ext_cr_term.js (used to prove the test red).
"""
import json
import os
import re
import subprocess
import unittest

SRC = os.environ.get("LOGIN_PILL_SRC") or os.path.join(
    os.path.dirname(__file__), "..", "aitracker", "web", "ext_cr_term.js")
TIP = ("Types /login into Claude Code. Use when Claude is idle at its prompt. Signs in for every "
       "Claude Code session on this machine — choosing a different login method signs out the "
       "existing claude.ai login.")


def _extract(src, name):
    start = src.find("function " + name + "(")
    if start < 0:
        raise AssertionError("function %s() not found" % name)
    i = src.find("{", start)
    depth = 0
    while i < len(src):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            return src[start:i + 1]
        i += 1
    raise AssertionError("unbalanced %s" % name)


_HARNESS = r"""
%s
var out = {};
var toasts = [], posts = [];
function mkEl() { return {hidden: undefined, textContent: "", title: "", classList: {toggle: function(){}}}; }
var el, st;
function reset(s) {
  el = {modelPill: mkEl(), effortPill: mkEl(), loginPill: mkEl(), status: mkEl(), ctxreadout: mkEl()};
  st = Object.assign({attached: true, loginOk: false, tty: "t1", ctx: null, cumulative: 0}, s || {});
}
function esc(x){return x;} function fmtTok(x){return x;}
function showToast(m) { toasts.push(m); }
var window = {ExtVT: {ttyBody: function (t, o) { return Object.assign({tty: t}, o); }}};
var respond = {ok: true, status: 200, j: {ok: true}};
function post(u, b) { posts.push([u, b]); return Promise.resolve(respond); }
function j(r) { return Promise.resolve(r); }
function close(){}
function _syncSplit(){}   // the split button's own sync is covered by test_term_split_menu.py
var ctx = {dialog: function(){}};
reset({attached: true, loginOk: false}); _syncStatusBar(); out.hidden_off = el.loginPill.hidden;
st.loginOk = true; _syncStatusBar(); out.shown_on = el.loginPill.hidden;
st.loginOk = false; _syncStatusBar(); out.hidden_again = el.loginPill.hidden;
reset({attached: false, loginOk: true}); _syncStatusBar(); out.shown_unattached = el.loginPill.hidden;
(async function () {
  reset({attached: true, loginOk: true});
  _onAction("login");
  await new Promise(function (r) { setTimeout(r, 5); });
  out.posts = posts.slice();
  respond = {ok: true, status: 200, j: {ok: false, error: "not at prompt"}};
  _onAction("login");
  await new Promise(function (r) { setTimeout(r, 5); });
  respond = {ok: true, status: 500, j: {}};
  _onAction("login");
  await new Promise(function (r) { setTimeout(r, 5); });
  post = function () { return Promise.reject(new Error("x")); };
  _onAction("login");
  await new Promise(function (r) { setTimeout(r, 5); });
  out.toasts = toasts;
  console.log("===J===" + JSON.stringify(out));
})();
"""

_POLL = r"""
%s
var st = {open: true, sessionId: "s", tty: "t1", attached: true, loginOk: true};
var el = {}; var pollGen = 0, pollTimer = null;
function _syncStatusBar() {}
function _stopPoll() { pollGen++; }
function _applySessionData() {} function _refreshRunningList() {}
var window = {ExtVT: {ttyQuery: function () { return "q"; }}};
var mode = "ok";
function fetch(u) {
  if (u.indexOf("/api/term/attached") < 0) return Promise.resolve({json: function () { return Promise.resolve({}); }});
  if (mode === "throw") return Promise.reject(new Error("x"));
  return Promise.resolve({ok: true, json: function () { return Promise.resolve({claude_attached: true, login_ok: true}); }});
}
var setInterval = function () { return 1; }; var clearInterval = function () {};
var out = {};
(async function () {
  st.loginOk = false;
  _startPoll(); await new Promise(function (r) { setTimeout(r, 5); });
  out.after_ok = st.loginOk;
  mode = "throw"; _startPoll(); await new Promise(function (r) { setTimeout(r, 5); });
  out.after_catch = st.loginOk; out.attached_after_catch = st.attached;
  console.log("===J===" + JSON.stringify(out));
})();
"""


def _run(script):
    p = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise AssertionError("node failed: " + p.stderr[-1500:])
    return json.loads(p.stdout.split("===J===")[1].strip().splitlines()[0])


class LoginPillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(SRC, encoding="utf-8").read()
        fns = "\n".join(_extract(cls.src, n) for n in ("_syncStatusBar", "_onAction", "_injectSlash"))
        cls.out = _run(_HARNESS % fns)
        cls.poll = _run(_POLL % _extract(cls.src, "_startPoll"))

    def test_pill_follows_login_ok_only(self):
        self.assertIs(self.out["hidden_off"], True)
        self.assertIs(self.out["shown_on"], False)          # attached unchanged, flag flips
        self.assertIs(self.out["hidden_again"], True)
        self.assertIs(self.out["shown_unattached"], False)  # render-only: no client gating

    def test_click_posts_exact_inject_body(self):
        self.assertEqual(self.out["posts"], [["/api/term/inject", {
            "tty": "t1", "text": "/login", "submit": True, "clear_first": True,
            "require_claude": True}]])

    def test_failure_toasts(self):
        self.assertEqual(self.out["toasts"], [
            "Couldn't start login — not at prompt",
            "Couldn't start login — the terminal didn't confirm it",
            "Couldn't reach the server — the command wasn't sent"])
        self.assertFalse([t for t in self.out["toasts"] if "switch" in t])

    def test_poll_success_sets_and_catch_clears(self):
        self.assertIs(self.poll["after_ok"], True)
        self.assertIs(self.poll["after_catch"], False)
        self.assertIs(self.poll["attached_after_catch"], False)

    def test_reset_clears_login_ok(self):
        self.assertRegex(self.src, r"st\.attached = false;\s*st\.loginOk = false;\s*st\.model = null;")

    def test_markup_title_equals_tip_and_action_wired(self):
        m = re.search(r'<button[^>]*data-action="login"[^>]*>', self.src)
        self.assertTrue(m)
        self.assertIn('title="%s"' % TIP, m.group(0))
        self.assertIn("hidden", m.group(0))
        self.assertIn("loginPill: status.querySelector('[data-el=\"loginpill\"]')", self.src)


if __name__ == "__main__":
    unittest.main()
