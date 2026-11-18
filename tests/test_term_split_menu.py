"""The Resume split button's surfaces: source-level checks that every surface mounts the ONE shared
`termSplit` (app.js), that the CSS lives once, and two guards that pin the in-terminal Resume path.

Expected change: the old `<details>/<summary>` implementation (termSplitSync, the string-returning
termSplit and this file's private fake DOM) was replaced by the WAI-ARIA split in app.js. The behavioural
tests of that markup were superseded by tests/test_tsplit_shared.py, test_tsplit_header.py,
test_tsplit_toolbar.py and test_tsplit_classic.py, which share ONE fake DOM (tests/_tsplit_dom.py); what
stays here is the cross-surface source checks, updated to the new contract, and the *guard* tests that
were green on the base and must stay so.
"""
import os
import re
import sys
import json
import subprocess
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import _tsplit_dom as D  # noqa: E402

_HAS_NODE = D.HAS_NODE
_read = D.read
_extract = D.extract
_run = D.run


class TestSurfacesUseTheSharedSplit(unittest.TestCase):
    def test_every_surface_calls_termsplit(self):
        for name in ("ext_cr_detail.js", "ext_cr_term.js", "ext_launch.js", "ext_cr_board.js"):
            self.assertIn("termSplit(", _read(name), name)

    def test_header_secondary_actions_only_inside_the_list(self):
        # The header's Open terminal / External items are built by termSplit (app.js); the caller keeps
        # no hand-written button for them and routes them through termSplitOn handlers.
        src = _read("ext_cr_detail.js")
        self.assertNotRegex(src, r'<button[^>]*data-act="(external|open-terminal|resume)"')
        a = src.index("function mountHeaderSplit")
        body = src[a:src.index("function syncHeaderSplit")]
        for ev in ("session:resume", "terminal:open", "session:openExternal"):
            self.assertIn(ev, body)

    def test_overlay_external_moved_into_the_list_and_group_removed(self):
        src = _read("ext_cr_term.js")
        self.assertNotIn('data-group="external"', src)
        self.assertNotIn('data-action="ext-terminal"', src)
        self.assertNotIn('data-action="ext-resume"', src)
        self.assertIn("termSplit(", src)
        self.assertIn("termSplitClose();", _extract(src, "close"))

    def test_classic_native_buttons_only_via_the_split(self):
        src = _read("ext_launch.js")
        body = src[src.index("function render(d) {"):src.index("EXT.push(render)")]
        self.assertIn("termSplit(", body)
        self.assertNotIn("nativeHtml", body)
        self.assertNotIn("vtHtml", body)

    def test_board_hero_tile_uses_the_split_and_emits_session_resume(self):
        src = _read("ext_cr_board.js")
        a = src.index("function heroSplit")
        body = src[a:a + 1800]
        self.assertIn("termSplit(", body)
        self.assertIn("resume: emit('session:resume')", body)

    def test_header_reset_closes_the_menu(self):
        src = _read("ext_cr_detail.js")
        a = src.index('ctx.on("session:reset"')
        self.assertIn("termSplitClose();", src[a:a + 900])


class TestSplitCss(unittest.TestCase):
    def test_group_never_wraps(self):
        css = _read("app.css")
        m = re.search(r"\.tsplit\{([^}]*)\}", css)
        self.assertTrue(m)
        self.assertIn("flex-wrap:nowrap", m.group(1))

    def test_no_band_hides_the_split_or_its_items(self):
        for name in ("app.css", "ext_cr_detail.css", "ext_cr_term.css", "ext_launch.css", "ext_cr.css"):
            css = re.sub(r"/\*.*?\*/", "", _read(name), flags=re.S)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                if "display:none" in body.replace(" ", "") and "tsplit" in sel and "readonly" not in sel:
                    for part in sel.split(","):
                        if "tsplit" in part:
                            self.assertRegex(part.strip(), r"\[hidden\]$|tsplit-solo-label$|-webkit-details-marker$|:not\(\.tsplit-item\)$",
                                             "%s hides a split part: %r" % (name, part.strip()))

    def test_phone_band_bare_hide_excludes_split_items(self):
        css = _read("ext_cr_detail.css")
        self.assertIn(".cr .crd-btn-bare:not(.tsplit-item)", css)
        self.assertNotRegex(css, r"\.cr \.crd-btn-bare,\s*\.cr \.crd-btn-ai \{ display: none; \}")

    def test_readonly_hides_the_whole_split_in_one_universal_rule(self):
        # expected change: one `html.tracker-readonly .tsplit` rule in app.js's stylesheet covers every
        # surface; the header-only selector in ext_cr.css is gone.
        self.assertRegex(_read("app.css"), r"html\.tracker-readonly \.tsplit\{display:none!important\}")
        self.assertNotIn(".tsplit", _read("ext_cr.css"))

    def test_one_css_block_in_app_css(self):
        css = _read("app.css")
        self.assertEqual(css.count("*/"), css.count("/*"))
        for n in ("ext_cr_detail.css", "ext_cr_term.css", "ext_launch.css", "ext_cr.css"):
            self.assertNotIn(".tsplit-menu", _read(n), "the split's base rules live once, in app.css")


class TestStatusBarAttachedKeepsExternalReachable(unittest.TestCase):
    """U2: _syncStatusBar's attached branch must go through _syncSplit only; hiding a whole group (the
    old primaryGroup.hidden = st.attached) would strand External. The behaviour itself is covered by
    tests/test_tsplit_toolbar.py (test_a_attached_claude_is_external_only)."""

    def test_no_dead_primary_group_handle(self):
        term = _read("ext_cr_term.js")
        self.assertNotIn("primaryGroup", term)
        self.assertIn("_syncSplit();", _extract(term, "_syncStatusBar"))



_F4_JS = r"""
function U() { const f = function () {}; return new Proxy(f, { get(t, k) { if (k === Symbol.toPrimitive) return () => 0; if (k === 'length') return 0; if (k === Symbol.iterator) return function* () {}; if (k === 'then') return undefined; return U(); }, apply() { return U(); }, construct() { return U(); }, has() { return true; }, set() { return true; } }); }
const fs = require('fs'), vm = require('vm');
const calls = [];
function resp(j) { return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(j) }); }
const ctx = {
  console, Promise, JSON, Math, Date, RegExp, Array, Object, String, Number, Boolean, Map, Set, WeakMap, Symbol, Error,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, URLSearchParams, TextEncoder, TextDecoder,
  setTimeout: (f) => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: (f) => { Promise.resolve().then(f); return 1; },
  getComputedStyle: () => ({ paddingLeft: '0', paddingTop: '0', paddingRight: '0', paddingBottom: '0' }),
  document: U(), location: { hostname: 'localhost', origin: 'http://localhost', pathname: '/', search: '', protocol: 'http:', host: 'localhost' },
  navigator: { userAgent: 'node', platform: 'mac', clipboard: U() }, localStorage: { getItem: () => null, setItem() {} },
  addEventListener() {}, removeEventListener() {}, EventSource: function () { return U(); }, WebSocket: function () { return U(); },
  ResizeObserver: function () { return U(); }, MutationObserver: function () { return U(); }, alert() {}, confirm: () => false,
  ico: () => '', icoChar: () => null, esc: s => s, toast() {}, EXT: [], SIDE_EXT: [], termSplitSync() {},
  fetch: (u, o) => {
    calls.push({ u: String(u), m: (o && o.method) || 'GET' });
    if (String(u).startsWith('/api/term/list')) return resp({ terminals: [] });
    if (String(u).startsWith('/api/term/pty')) return resp({ tty: 't1', session: 'S1' });
    if (String(u).startsWith('/api/term/renderer')) return resp({ renderer: 'grid' });
    return resp({});
  },
};
ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, { filename: 'ext_vt.js' });
let manage = 0; ctx.ExtVT.manage = function () { manage++; };
(async () => {
  ctx.ExtVT.mountInto(U(), { session: 'S1', mode: 'resume' }, {});
  for (let i = 0; i < 50; i++) await new Promise(r => setImmediate(r));
  const posts = calls.filter(c => c.u.startsWith('/api/term/pty') && c.m === 'POST').length;
  console.log('OUT:' + JSON.stringify({ posts, manage, calls: calls.map(c => c.m + ' ' + c.u) }));
})().catch(e => { console.error(e); process.exit(1); });
"""


def _run_f4(vt_src):
    with tempfile.TemporaryDirectory() as d:
        vt = os.path.join(d, "ext_vt.js")
        h = os.path.join(d, "h.js")
        with open(vt, "w", encoding="utf-8") as fh:
            fh.write(vt_src)
        with open(h, "w", encoding="utf-8") as fh:
            fh.write(_F4_JS)
        proc = subprocess.run(["node", h, vt], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node failed: " + proc.stderr[-2000:])
    return json.loads(proc.stdout.split("OUT:", 1)[1])


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMountIntoEmptyListOnePost(unittest.TestCase):
    """U3 *guard* (green on the base): mountInto(resume) with an empty /api/term/list spawns exactly
    one pty and never opens the manage dialog."""

    def test_mountinto_empty_list_one_pty_post(self):
        o = _run_f4(_read("ext_vt.js"))
        self.assertEqual(o["posts"], 1, o["calls"])
        self.assertEqual(o["manage"], 0)
        self.assertEqual(o["calls"][0].split(" ", 1)[0] + " " + o["calls"][0].split(" ", 1)[1].split("?")[0],
                         "GET /api/term/list")

    def test_double_spawn_mutant_is_caught(self):
        src = _read("ext_vt.js")
        m = re.search(r"\bspawn\(\);", src)
        self.assertTrue(m, "spawn(); call site not found for the mutant")
        o = _run_f4(src[:m.end()] + " spawn();" + src[m.end():])
        self.assertNotEqual(o["posts"], 1, "the guard must detect a double spawn")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestResumeOpensOneEngineGuard(unittest.TestCase):
    """*guard* (green on the base): CR.term's inline Resume attaches exactly one engine via
    mountInto and never routes through the "Manage terminals" dialog -- the double-spawn lives on the
    server, not in this path."""

    def test_open_inline_resume_mounts_once_no_manage_dialog(self):
        term = _read("ext_cr_term.js")
        fns = "\n".join(_extract(term, n) for n in ("_attachEngine", "_openInline"))
        o = _run(r"""
var mounts = [], dialogs = [], engineGen = 0;
function mkEl() { return {hidden: false, textContent: "", disabled: false}; }
var el = {pane: {}, placeholder: mkEl(), status: mkEl(), newTab: mkEl()};
var st = {};
var ctx = {dialog: function (n) { dialogs.push(n); }};
var handle = {onStatus() {}, onNotice() {}, onForked() {}, destroy() {}};
var window = {ExtVT: {mountInto: function (c, t, o) { mounts.push(t); return handle; }}};
function _openCapDialog() { dialogs.push("cap"); }
function _syncNotice() {} function _syncRendererSeg() {} function _applyDarkTheme() {} function showToast() {}
""" + fns + r"""
_openInline("sid-1", "resume");
console.log('OUT:' + JSON.stringify({mounts: mounts, dialogs: dialogs}));""")
        self.assertEqual(o["mounts"], [{"session": "sid-1", "mode": "resume"}])
        self.assertEqual(o["dialogs"], [])


if __name__ == "__main__":
    unittest.main()
