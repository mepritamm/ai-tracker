"""Config -> Usage tab, Auggie login block and OpenRouter key block (ext_cr_dialogs.js). Executed under Node with the
fake DOM of test_update_settings_ui; fetch / ExtLaunch / ExtVT are stubbed, so no CLI and no network is touched.
Skipped without node. Static checks (no html:/innerHTML in the new code, every field read is emitted by
accounts.py) run without it."""
import json
import os
import re
import subprocess
import tempfile
import unittest

try:
    from tests.test_update_settings_ui import _DOM, _WEB, _HAS_NODE
except ImportError:  # run as a bare file
    from test_update_settings_ui import _DOM, _WEB, _HAS_NODE

_SRC = os.path.join(_WEB, "ext_cr_dialogs.js")

_BODY = r"""
const SCEN = JSON.parse(process.argv[3]);
const realST = setTimeout;
const gets = [], posts = [], toasts = [], opens = [], listeners = {}, removed = [];
global.setTimeout = (f, ms) => ms === 8000 ? 0 : realST(f, 0);   // toast auto-dismiss never fires
global.window.location = {host: 'x', reload() {}};
global.addEventListener = (t, f) => { (listeners[t] = listeners[t] || []).push(f); };
global.removeEventListener = (t, f) => { removed.push(t); const a = listeners[t] || []; const i = a.indexOf(f); if (i >= 0) a.splice(i, 1); };
global.confirm = () => true; window.confirm = () => true;
let ROOT = null;
if (!El.prototype.remove) El.prototype.remove = function () { if (this.parentNode) this.parentNode.removeChild(this); };
Object.defineProperty(El.prototype, 'isConnected', {configurable: true, get() {
  for (let n = this; n; n = n.parentNode) if (n === ROOT) return true; return false; }});
global.ExtLaunch = {openAt: (...a) => { opens.push(a); return Promise.resolve(SCEN.openReply || {ok: true}); }};
if (SCEN.vt) global.ExtVT = {
  mountInto: () => ({onStatus() {}, onNotice() {}, onForked() {}, focus() {}, destroy() {}}),
  ttyBody: (tty) => ({tty}), ttyQuery: (t) => 'tty=' + t,
};
const seqs = {};
global.fetch = (url, opt) => {
  const json = (body, ok=true, status) => Promise.resolve({ok, status: status || (ok ? 200 : 400), json: () => Promise.resolve(body)});
  const method = (opt && opt.method) || 'GET';
  if (url === '/api/tunnel') return json({on: false});
  if (url === '/api/update') return json({kind: 'package', version: '1'});
  if (url === '/api/config' && method === 'POST') {
    posts.push([url, JSON.parse(opt.body)]);
    const r = SCEN.postReply || {status: 200, body: {ok: true}};
    return json(r.body, r.status < 400, r.status);
  }
  if (url === '/api/config') return json({});
  if (url.indexOf('/api/term/attached') === 0) return SCEN.alive ? json({claude_attached: true}) : json({error: 'gone'}, false, 404);
  if (url === '/api/term/close') return json({ok: true});
  const base = url.split('?')[0];
  const rep = (SCEN.routes || {})[url] || (SCEN.routes || {})[base];
  if (!rep) return json({});
  gets.push(url);
  const list = Array.isArray(rep) ? rep : [rep];
  const n = seqs[url] = (seqs[url] || 0) + 1;
  const r = list[Math.min(n - 1, list.length - 1)];
  return json(r.body, r.status < 400, r.status);
};
const tick = async (n=6) => { for (let i = 0; i < n; i++) await new Promise(r => realST(r, 5)); };
const SRC = require('fs').readFileSync(process.argv[2], 'utf8');
(async () => {
  (0, eval)(SRC);
  const root = new El('div'); ROOT = root;
  window.CR.dialogs.mount(root, {icon: () => '', readOnly: () => !!SCEN.ro});
  await tick();
  window.CR.dialogs.open('config', {section: SCEN.tab});
  await tick(SCEN.settle || 12);
  const q = (c) => root.querySelector('.' + c);
  const qa = (c) => root.querySelectorAll('.' + c);
  const out = {};
  out.nav = qa('cr-cfg-nav')[0] ? qa('cr-cfg-nav')[0].children.map(b => b.textContent) : [];
  out.text = root.textContent;
  out.rows = qa('cr-usage-row').length;
  out.credits = qa('cr-usage-credits').length;
  out.fills = qa('cr-usage-fill').map(e => e.attrs.style);
  out.barClasses = qa('cr-usage-bar').map(e => e.className);
  out.imgs = root.querySelectorAll('img').length;
  out.cards = qa('cr-usage-card').length;
  if (SCEN.act === 'key') {
    const input = () => q('cr-or-key-input');
    const btn = (label) => qa('cr-or-key-block')[0].querySelectorAll('button').filter(b => b.textContent === label)[0];
    out.before = q('cr-or-key-block').textContent;
    btn(SCEN.firstBtn).fire('click'); await tick(4);
    out.inputAttrs = input() ? {type: input().attrs.type, ac: input().attrs.autocomplete, name: input().attrs.name, id: input().attrs.id, value: input().value || '', vattr: input().attrs.value, inForm: false} : null;
    input().value = SCEN.typed;
    btn('Save').fire('click'); await tick(10);
    out.posts = posts;
    out.afterSave = q('cr-or-key-block').textContent;
    out.inputAfter = input() ? (input().value || '') : null;
    out.leaked = root.textContent.indexOf(SCEN.typed) >= 0;
    out.toastTexts = [];
  }
  if (SCEN.act === 'clear') { qa('cr-or-key-block')[0].querySelectorAll('button').filter(b => b.textContent === 'Clear')[0].fire('click'); await tick(10); out.posts = posts; }
  if (SCEN.act === 'auggie') {
    qa('cr-auggie-login-block')[0].querySelectorAll('button')[0].fire('click'); await tick(10);
    out.opens = opens;
    if (SCEN.vt) {
      if (SCEN.manualClose) { window.CR.dialogs.close(); await tick(15); }
      else await tick(20);   // the stubbed attached poll answers 404: the pty ended by itself
    }
    out.toasts = qa('cr-toast-title').map(x => x.textContent);
    out.title = (q('cr-dialog-login') || {}).textContent;
    out.focusBefore = (listeners.focus || []).length;
    out.gets = gets;
  }
  if (SCEN.act === 'focus') {
    out.focusBefore = (listeners.focus || []).length;
    window.CR.dialogs.close(); await tick();
    (listeners.focus || []).slice().forEach(f => f()); await tick(8);
    out.removed = removed.slice(); out.left = (listeners.focus || []).length;
  }
  out.gets = gets;
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run(scen):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "h.js")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_DOM + _BODY)
        proc = subprocess.run(["node", p, os.environ.get("CR_DIALOGS_SRC") or _SRC, json.dumps(scen)],
                              capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node exited %d\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return json.loads(proc.stdout.strip().splitlines()[-1])


def ok(body):
    return {"status": 200, "body": body}


A_LIMITS = [
    {"kind": "session", "label": "Current session", "percent": 87, "resets_at": "2026-11-18T10:19:00+00:00", "severity": "warning", "active": True},
    {"kind": "weekly_all", "label": "Current week (all models)", "percent": 84, "resets_at": "2026-11-22T21:59:00+00:00", "severity": "warning", "active": False},
    {"kind": "weekly_scoped", "label": "Current week (Fable)", "percent": 4, "resets_at": None, "severity": "normal", "active": False},
]
CLAUDE_A = {"state": "ok", "refreshing": False, "stale": False, "at": 1790000000, "account": "Logged in · Claude Max subscription",
            "limits": A_LIMITS, "credits": None, "message": "", "error": ""}
ORK = {"key_set": True, "state": "ok", "refreshing": False, "stale": False, "at": 1790000000,
       "rows": [{"label": "Today (UTC)", "text": "$0.50"}], "limit_text": "Limit $50.00", "remaining_text": "Remaining $37.50",
       "limit_reset": "monthly", "free_tier": False, "retry_in": 0, "error": ""}
AUG = {"available": True, "label": "Local session cost, not account balance", "window": "This month (UTC, from Nov 1)",
       "cost_text": "$1.23", "sessions": 2, "note": "Auggie CLI sessions read from ~/.augment/sessions"}


def usage_routes(**over):
    r = {"/api/usage/claude": ok(CLAUDE_A), "/api/usage/openrouter": ok(ORK), "/api/usage/auggie": ok(AUG)}
    r.update(over)
    return r


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class UsageTab(unittest.TestCase):
    def test_usage_listed_and_dispatched(self):
        r = _run({"tab": "Usage", "routes": usage_routes()})
        self.assertIn("Usage", r["nav"])
        self.assertEqual(r["nav"].index("Usage"), r["nav"].index("Agents") + 1)
        self.assertEqual(r["cards"], 3)

    def test_probed_max_shape_three_rows_no_credits(self):
        r = _run({"tab": "Usage", "routes": usage_routes()})
        self.assertEqual(r["rows"], 3)
        self.assertEqual(r["credits"], 0)
        for s in ("Current session", "Current week (all models)", "Current week (Fable)", "87% used", "Logged in · Claude Max subscription", "as of"):
            self.assertIn(s, r["text"])
        self.assertEqual(r["fills"][:3], ["width:87%", "width:84%", "width:4%"])
        self.assertTrue(r["barClasses"][0].endswith("is-warning"))

    def test_credits_block_renders_server_text_only_when_present(self):
        cred = dict(CLAUDE_A, limits=[], credits={"text": "$758.44 spent of $2000.00 this month", "utilization": 37.9, "note": ""})
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(cred)})})
        self.assertEqual((r["rows"], r["credits"]), (0, 1))
        self.assertIn("$758.44 spent of $2000.00 this month", r["text"])
        self.assertNotIn("nlimited", r["text"])
        nolimit = dict(cred, credits={"text": "$12.34 spent this month · no monthly limit of its own", "utilization": None,
                                       "note": "your organisation's limits apply"})
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(nolimit)})})
        self.assertIn("no monthly limit of its own", r["text"])
        self.assertIn("your organisation's limits apply", r["text"])
        self.assertNotIn("nlimited", r["text"])
        self.assertEqual(r["fills"], [])              # no limit, nothing to measure: text only, no 0% bar

    def test_empty_limits_message_only_without_credits(self):
        none = dict(CLAUDE_A, limits=[], credits=None, message="No plan limits reported for this login.")
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(none)})})
        self.assertIn("No plan limits reported for this login.", r["text"])
        self.assertEqual(r["credits"], 0)
        cred = dict(CLAUDE_A, limits=[], message="", credits={"text": "$758.44 spent of $2000.00 this month", "utilization": 37.9, "note": ""})
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(cred)})})
        self.assertNotIn("No plan limits reported", r["text"])
        self.assertEqual((r["rows"], r["credits"]), (0, 1))
        both = dict(CLAUDE_A, credits=cred["credits"])
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(both)})})
        self.assertEqual((r["rows"], r["credits"]), (3, 1))

    def test_no_report_message_and_error(self):
        nr = dict(CLAUDE_A, state="no_report", limits=[], message="Claude Code returned no plan usage for this login")
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(nr)})})
        self.assertIn("returned no plan usage", r["text"])
        self.assertEqual(r["rows"], 0)

    def test_refreshing_polls_then_stops(self):
        load = dict(CLAUDE_A, refreshing=True, limits=[])
        r = _run({"tab": "Usage", "settle": 40, "routes": usage_routes(**{"/api/usage/claude": [ok(load), ok(load), ok(CLAUDE_A)]})})
        self.assertEqual(r["gets"].count("/api/usage/claude"), 3)
        self.assertEqual(r["rows"], 3)

    def test_403_text_and_readonly(self):
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": {"status": 403, "body": {"error": "x"}}})})
        self.assertIn("Usage is shown on this machine only", r["text"])
        r = _run({"tab": "Usage", "ro": True, "routes": usage_routes()})
        self.assertEqual(r["cards"], 0)
        self.assertEqual([g for g in r["gets"] if "usage" in g], [])

    def test_label_is_literal_text_not_markup(self):
        evil = dict(CLAUDE_A, limits=[dict(A_LIMITS[0], label="<img src=x onerror=1>")])
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/claude": ok(evil)})})
        self.assertIn("<img src=x onerror=1>", r["text"])
        self.assertEqual(r["imgs"], 0)

    def test_openrouter_and_auggie_cards(self):
        r = _run({"tab": "Usage", "routes": usage_routes()})
        for s in ("Today (UTC): $0.50", "Limit $50.00", "Remaining $37.50", "Local session cost, not account balance",
                  "This month (UTC, from Nov 1)", "$1.23 · 2 sessions"):
            self.assertIn(s, r["text"])
        nk = {"key_set": False, "state": "not_set", "refreshing": False, "rows": [], "limit_text": "", "remaining_text": ""}
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/openrouter": ok(nk)})})
        self.assertIn("No OpenRouter key saved — add it in Config → Server", r["text"])
        rj = dict(nk, state="rejected", key_set=True)
        r = _run({"tab": "Usage", "routes": usage_routes(**{"/api/usage/openrouter": ok(rj)})})
        self.assertIn("OpenRouter rejected the saved key — replace it in Config → Server", r["text"])


@unittest.skipUnless(_HAS_NODE, "node not on PATH")
class ServerTabBlocks(unittest.TestCase):
    PEEK = {"key_set": True, "launcher_configured": False, "file": "/x/aitracker/config.json"}

    def routes(self, **over):
        r = {"/api/usage/openrouter?peek=1": ok(self.PEEK), "/api/auggie/auth": ok({"available": True, "logged_in": True, "label": "Logged in · Augment", "error": "", "refreshing": False}),
             "/api/claude/auth": ok({"available": True, "logged_in": False, "label": "n"})}
        r.update(over)
        return r

    def test_server_tab_reads_peek_never_the_bare_route(self):
        r = _run({"tab": "Server", "routes": self.routes()})
        self.assertIn("/api/usage/openrouter?peek=1", r["gets"])
        self.assertNotIn("/api/usage/openrouter", r["gets"])
        self.assertNotIn("/api/usage/claude", r["gets"])
        self.assertIn("API key: set", r["text"])
        self.assertIn("Saved to /x/aitracker/config.json (owner-only)", r["text"])
        self.assertIn("Logged in · Augment", r["text"])

    def test_key_input_attributes_empty_and_cleared_after_success(self):
        key = "sk-or-v1-TYPEDSENTINEL012345"
        r = _run({"tab": "Server", "routes": self.routes(), "act": "key", "firstBtn": "Replace", "typed": key,
                  "postReply": {"status": 200, "body": {"ok": True, "set": True}}})
        self.assertEqual(r["inputAttrs"], {"type": "password", "ac": "new-password", "value": "", "inForm": False})
        self.assertEqual(r["posts"], [["/api/config", {"key": "OPENROUTER_API_KEY", "value": key}]])
        self.assertIsNone(r["inputAfter"])            # editing closed, input gone
        self.assertFalse(r["leaked"])

    def test_save_with_an_empty_box_posts_nothing(self):
        for typed in ("", "   "):
            r = _run({"tab": "Server", "routes": self.routes(), "act": "key", "firstBtn": "Replace", "typed": typed})
            self.assertEqual(r["posts"], [])
            self.assertIn("Paste a key first", r["afterSave"])

    def test_400_keeps_the_editor_empty_and_shows_the_fixed_error(self):
        key = "bad key value with spaces"
        r = _run({"tab": "Server", "routes": self.routes(), "act": "key", "firstBtn": "Replace", "typed": key,
                  "postReply": {"status": 400, "body": {"error": "invalid value for OPENROUTER_API_KEY"}}})
        self.assertEqual(r["inputAfter"], "")
        self.assertIn("invalid value for OPENROUTER_API_KEY", r["afterSave"])
        self.assertFalse(r["leaked"])

    def test_not_set_shows_set_and_clear_posts_empty(self):
        r = _run({"tab": "Server", "routes": self.routes(**{"/api/usage/openrouter?peek=1": ok(dict(self.PEEK, key_set=False))}),
                  "act": "key", "firstBtn": "Set", "typed": "sk-or-v1-ZZZZZZZZZZZZZZZZZZ",
                  "postReply": {"status": 200, "body": {"ok": True}}})
        self.assertIn("API key: not set", r["before"])
        r = _run({"tab": "Server", "routes": self.routes(), "act": "clear", "postReply": {"status": 200, "body": {"ok": True}}})
        self.assertEqual(r["posts"], [["/api/config", {"key": "OPENROUTER_API_KEY", "value": ""}]])

    def test_auggie_opens_the_selector_prompt(self):
        r = _run({"tab": "Server", "routes": self.routes(), "act": "auggie"})
        self.assertEqual(r["opens"], [["~", "new", "auggie auth login", {"gateway": "anthropic"}]])

    def test_auggie_toast_only_when_the_pty_ended_by_itself(self):
        base = {"tab": "Server", "routes": self.routes(), "act": "auggie", "vt": True,
                "openReply": {"ok": True, "tty": "A1", "renderer": "grid"}}
        r = _run(dict(base))
        self.assertEqual(r["opens"][0][3], {"gateway": "anthropic", "tab": False})
        self.assertIn("Auggie: Logged in · Augment", r["toasts"])
        self.assertIn("/api/auggie/auth?fresh=1", r["gets"])
        r = _run(dict(base, manualClose=True, alive=True))
        self.assertEqual(r["toasts"], [])
        self.assertIn("/api/auggie/auth?fresh=1", r["gets"])

    def test_focus_listener_removes_itself_after_close(self):
        r = _run({"tab": "Server", "routes": self.routes(), "act": "focus"})
        self.assertGreaterEqual(r["focusBefore"], 2)         # the Claude and the Auggie block each listen
        self.assertEqual(r["removed"].count("focus"), r["focusBefore"])
        self.assertEqual(r["left"], 0)


class StaticChecks(unittest.TestCase):
    def _fn(self, name):
        with open(_SRC, encoding="utf-8") as fh:
            src = fh.read()
        i = src.index("  function %s(" % name)
        m = re.search(r"\n  (?:// |function )", src[i + 10:])
        return src[i:i + 10 + (m.start() if m else 4000)]

    def test_new_blocks_build_dom_with_text_children_only(self):
        for fn in ("usageWhen", "usageBar", "usageCard", "usageLine", "usageBlock", "auggieLoginBlock", "openrouterKeyBlock"):
            body = self._fn(fn)
            self.assertNotRegex(body, r"html\s*:", fn)
            self.assertNotRegex(body, r"innerHTML\s*=(?!\s*'';)", fn)

    def test_every_field_the_ui_reads_is_emitted_by_accounts(self):
        with open(os.path.join(os.path.dirname(_WEB), "accounts.py"), encoding="utf-8") as fh:
            acc = fh.read()
        js = self._fn("usageBlock") + self._fn("usageCard") + self._fn("auggieLoginBlock") + self._fn("openrouterKeyBlock")
        for field in ("limits", "credits", "label", "percent", "resets_at", "severity", "active", "utilization", "note", "text",
                      "message", "error", "account", "refreshing", "stale", "rows", "limit_text", "remaining_text", "free_tier",
                      "window", "cost_text", "sessions", "logged_in", "key_set", "file", "state", "at"):
            self.assertRegex(acc, r'["\']%s["\']' % field, field)
        self.assertIn("crCall", js)   # sanity: the slice is real code


if __name__ == "__main__":
    unittest.main()
