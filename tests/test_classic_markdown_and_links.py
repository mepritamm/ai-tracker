"""Regression tests for two classic-dashboard (app.js) gaps closed in this pass:

TASK 1 -- markdown rendering parity with the control room. Three classic-side
consumers of session-authored free text were still on plain esc() while their
control-room counterparts (ext_cr_detail.js's mdHtml()) already rendered
markdown -- the exact "same data, two renderings" asymmetry that file's own
comments call out for the Session summary panel:
  - the background-agent card's last message   (a.last)
  - the background-shell card's last output    (s.last)
  - the per-session notes list                 (n.text)
All three now go through app.js's existing md() (inline: `code`, **bold**,
*italic*, [text](url) -- http(s) only), never a new renderer. Two things that
must NOT be swept in, because they are not free text:
  - the shell command FALLBACK (s.cmd, shown when no output has been captured
    yet) -- `*`/`_`/backticks are shell metacharacters there
  - file paths, PR ids, session ids, commands list, version/model strings --
    unaffected by this pass, spot-checked below to prove they stayed on esc().

TASK 2 -- a Links section for the classic dashboard, mirroring the control
room's Links panel (ext_cr_detail.js's deriveLinks()/renderLinks()) so links
are usable from both views. Per the SHARED-SEAM rule (this repo's hard rule:
land a capability once, never fork it), deriveLinks() itself was PROMOTED to
app.js (as a global `deriveLinks`/`window.deriveLinks`) rather than copy-pasted
-- app.js loads before every ext_cr_*.js file (aitracker/page.py's
read_ext(), sorted glob), so it is the one file both renderers can reach.
ext_cr_detail.js no longer defines its own copy; its `deriveLinks` identifier
now resolves to the same global function via normal JS scope lookup. The
classic dashboard gets its own renderLinksPanel() (app.js), built the same way
renderForkLinks() builds its DOM (created once, into `.actcol`, then
repainted every render() pass) -- because index.html is not in this task's
file ownership, so the classic Links section has no home there.

Security (Task 2 item 5): a Links row is only ever a live, clickable <a href>
when the URL matches `/^https?:\\/\\//i` -- anything else (a local file path, or
a hostile scheme smuggled in as a fake path) renders as inert escaped text,
never an anchor, never a `javascript:` href.

Idiom: same "assemble the real page, run the real bundle/source under Node
with honest stubs" technique as tests/test_links_liveness.py /
tests/test_cr_detail_agents_pill_and_markdown.py -- never a hand-retyped
paraphrase of md()/deriveLinks()/renderLinksPanel() themselves.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_HAS_NODE = shutil.which("node") is not None
_APP_JS_PATH = os.path.join(_ROOT, "aitracker", "web", "app.js")

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _read_app_js():
    with open(_APP_JS_PATH, encoding="utf-8") as fh:
        return fh.read()


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_after_marker(stdout, marker):
    idx = stdout.find(marker)
    if idx < 0:
        raise AssertionError("marker %r not found in node output:\n%s" % (marker, stdout))
    return json.loads(stdout[idx + len(marker):].strip())


# ---------------------------------------------------------------------------
# TASK 1a -- static routing: the three consumers call md(), and the things
# that must stay literal (s.cmd fallback, paths, ids, the commands list) are
# untouched.
# ---------------------------------------------------------------------------

class TestClassicConsumersRouteThroughMarkdown(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def test_background_agent_last_message_uses_md(self):
        # DEFECT FIX (adversarial review): a.last is MACHINE output (an agent's
        # own free-text last message can legitimately read "ran ruff over *.py
        # and *.js files" or "*** 3 failed, 2 passed ***") -- plain md()'s
        # single-asterisk italics rule was corrupting exactly that, so this now
        # routes through mdSafe() (same escape/code/bold/links, no single-
        # asterisk italics), never plain md() and never plain esc().
        self.assertIn('<div class=last>${mdSafe(a.last||"")}</div>', self.bundle)
        self.assertNotIn('<div class=last>${esc(a.last||"")}</div>', self.bundle)
        self.assertNotIn('<div class=last>${md(a.last||"")}</div>', self.bundle)

    def test_shell_last_output_uses_mdsafe_but_cmd_fallback_stays_escaped(self):
        # DEFECT FIX: s.last is raw shell STDOUT -- the most exposed machine-
        # output surface (shown verbatim in a mono font) -- so it must go
        # through mdSafe(), not plain md() (which corrupted globs/separator
        # lines the exact same way as a.last above).
        self.assertIn(
            '<div class="last mono" style=font-size:11px>${s.last?mdSafe(s.last):esc(s.cmd||"")}</div>',
            self.bundle,
        )
        self.assertNotIn('${esc(s.last||s.cmd)}', self.bundle)
        self.assertNotIn('${s.last?md(s.last):esc(s.cmd||"")}', self.bundle)

    def test_note_text_uses_md(self):
        self.assertIn('<div class=ntxt>${md(n.text||"")}</div>', self.bundle)
        self.assertNotIn('<div class=ntxt>${esc(n.text||"")}</div>', self.bundle)

    def test_shell_command_and_path_and_id_surfaces_are_unchanged(self):
        """THE THINGS THAT MUST NOT CHANGE: a shell command string, a file
        path, and a shell/session id are not free text -- `*`/`_`/backticks/
        `[`/`]` are shell metacharacters and path syntax there."""
        for needle in (
            'esc(a.task||a.id)',            # agent card title (id/label, not a message)
            'esc(s.desc||s.cmd)',           # shell card title
            'esc(s.id)',                    # shell id in the footer
            'esc(base(lastFile.path))',     # last-touched file path
        ):
            self.assertIn(needle, self.bundle, "%s must stay on esc()" % needle)

    def test_commands_list_still_escapes_the_command_string(self):
        self.assertIn('<span class="cmd mono">${esc(x.cmd)}</span>', self.bundle)


# ---------------------------------------------------------------------------
# TASK 1b -- THE MOST VALUABLE TEST: md() actually escapes before it
# transforms, executed for real against hostile input, exactly as it will run
# for a.last/s.last/n.text in production.
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAS_NODE, "node not available")
class TestClassicMarkdownEscapesBeforeTransforming(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        driver = _APP_JS_STUB_PREAMBLE + _read_app_js() + r"""
var OUT = {};
OUT["script_tag"] = md("<script>alert(1)</script>");
OUT["img_onerror"] = md("<img src=x onerror=alert(1)>");
OUT["js_link"] = md("[click me](javascript:alert(1))");
OUT["bold_wrapping_script"] = md("**<script>alert(1)</script>**");
OUT["benign_bold"] = md("**hello**");
console.log("===MD_XSS_JSON_START===");
console.log(JSON.stringify(OUT));
"""
        returncode, stdout, stderr = _run_node(driver)
        if returncode != 0:
            raise AssertionError("md() XSS harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                                  % (returncode, stdout, stderr))
        cls.OUT = _extract_after_marker(stdout, "===MD_XSS_JSON_START===")

    def test_script_tag_is_neutralised(self):
        out = self.OUT["script_tag"]
        self.assertNotIn("<script", out)
        self.assertIn("&lt;script&gt;", out)

    def test_img_onerror_is_neutralised(self):
        out = self.OUT["img_onerror"]
        self.assertNotIn("<img", out)
        self.assertIn("&lt;img", out)

    def test_javascript_href_link_is_never_created(self):
        out = self.OUT["js_link"]
        self.assertNotIn("<a ", out, "an anchor was created for a non-http(s) link: %r" % out)
        self.assertNotRegex(out, r'href\s*=', "a live href leaked through: %r" % out)

    def test_escape_runs_before_markdown_transform(self):
        out = self.OUT["bold_wrapping_script"]
        self.assertNotIn("<script", out)
        self.assertIn("<strong>", out, "markdown bold was not applied at all: %r" % out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)

    def test_benign_markdown_still_renders(self):
        """A fix that degraded md() into esc()-only everywhere would pass
        every test above while quietly regressing narration/requests/the
        Session summary panel back to plain text."""
        self.assertEqual(self.OUT["benign_bold"], "<strong>hello</strong>")


# ---------------------------------------------------------------------------
# DEFECT FIX (adversarial review): md()'s single-asterisk italics rule
# corrupts literal asterisks in MACHINE OUTPUT -- a glob (`*.py`) or a
# separator line (`*** 3 failed, 2 passed ***`), both real shell/tool output
# shapes -- because it can't tell "emphasis" from "literal star". mdSafe()
# (app.js, next to md()) is the fix: same escape-first pipeline, same `code`/
# **bold**/links, single-asterisk italics DROPPED. Proven for real against
# the exact corrupting inputs named in the review, not a paraphrase.
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAS_NODE, "node not available")
class TestMdSafeDropsAsteriskItalicsButKeepsEverythingElse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        driver = _APP_JS_STUB_PREAMBLE + _read_app_js() + r"""
var OUT = {};
OUT["glob_line"] = mdSafe("ran ruff over *.py and *.js files");
OUT["separator_line"] = mdSafe("*** 3 failed, 2 passed ***");
OUT["plain_md_glob_line"] = md("ran ruff over *.py and *.js files");
OUT["bold_preserved"] = mdSafe("**3 failed**, 2 passed");
OUT["code_preserved"] = mdSafe("run `pytest -q`");
OUT["link_preserved"] = mdSafe("see [the log](https://example.com/log)");
OUT["underscore_path_unaffected"] = mdSafe("wrote my_file_name.py");
OUT["xss_still_neutralised"] = mdSafe("<script>alert(1)</script> *.py");
console.log("===MDSAFE_JSON_START===");
console.log(JSON.stringify(OUT));
"""
        returncode, stdout, stderr = _run_node(driver)
        if returncode != 0:
            raise AssertionError("mdSafe() harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                                  % (returncode, stdout, stderr))
        cls.OUT = _extract_after_marker(stdout, "===MDSAFE_JSON_START===")

    def test_glob_asterisks_are_not_turned_into_italics(self):
        out = self.OUT["glob_line"]
        self.assertNotIn("<em>", out, "mdSafe() must never emit <em> at all: %r" % out)
        self.assertIn("*.py", out)
        self.assertIn("*.js", out)

    def test_plain_md_still_corrupts_the_same_glob_line(self):
        """Sanity control proving this is a REAL bug in md(), not a
        mischaracterisation: plain md() on the exact same input still
        produces the broken output the review reported."""
        out = self.OUT["plain_md_glob_line"]
        self.assertIn("<em>", out, "md() is expected to (still) mis-italicise this input: %r" % out)

    def test_separator_line_of_asterisks_is_not_mangled(self):
        out = self.OUT["separator_line"]
        self.assertNotIn("<em>", out)
        self.assertNotIn("<strong><em>", out)
        self.assertIn("3 failed, 2 passed", out)

    def test_bold_code_and_links_still_work_in_safe_mode(self):
        self.assertIn("<strong>3 failed</strong>", self.OUT["bold_preserved"])
        self.assertIn("<code>pytest -q</code>", self.OUT["code_preserved"])
        self.assertIn('<a href="https://example.com/log"', self.OUT["link_preserved"])

    def test_underscores_in_filenames_still_pass_through_untouched(self):
        # NOTE what is NOT a problem (do not "fix" this): md()/mdSafe() have no
        # underscore-italics rule at all -- this is an existing-behaviour pin,
        # not a new claim.
        self.assertIn("my_file_name.py", self.OUT["underscore_path_unaffected"])
        self.assertNotIn("<em>", self.OUT["underscore_path_unaffected"])

    def test_xss_is_still_neutralised_in_safe_mode(self):
        """Escape-first must hold in mdSafe() too -- dropping the italics
        rule must not accidentally also drop or reorder the esc() step."""
        out = self.OUT["xss_still_neutralised"]
        self.assertNotIn("<script", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("*.py", out)


# ---------------------------------------------------------------------------
# TASK 2a -- deriveLinks() is ONE function, reachable identically from
# app.js (classic) and ext_cr_detail.js (control room).
# ---------------------------------------------------------------------------

# Same stub idiom as tests/test_links_liveness.py's TestDeriveLinksSkipsDeadEntries
# (a minimal, tracked DOM environment good enough to load the WHOLE assembled
# page bundle without executing a real browser) -- reused verbatim here so this
# file stays self-contained rather than importing another test module.
_BUNDLE_STUB_PREAMBLE = r"""
globalThis.window = globalThis;
function makeEl() {
  var self = {
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    style: {}, dataset: {}, setAttribute() {}, getAttribute() { return null; },
    appendChild() {}, append() {}, remove() {}, insertBefore() {},
    addEventListener() {}, removeEventListener() {},
    querySelector: function() { return self; }, querySelectorAll: () => [self],
    closest: function() { return self; }, firstElementChild: self, children: [self],
    innerHTML: "", textContent: "", hidden: false, focus() {}, click() {}
  };
  return self;
}
var stubEl = makeEl();
window.document = {
  createElement: () => makeEl(), createTextNode: () => makeEl(),
  getElementById: () => stubEl, querySelector: () => stubEl, querySelectorAll: () => [stubEl],
  addEventListener() {}, dispatchEvent() {},
  documentElement: stubEl, body: stubEl, head: stubEl, readyState: "complete"
};
const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};
window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve(""), headers: { get: () => null } });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts && opts.detail; } };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});
"""

_PARITY_FIXTURE_JS = r"""
var session = {
  now: 1780000000,
  files: [
    { path: "aitracker/web/app.js", created: true, alive: true, last: "2026-01-01T00:00:00.000Z" },
    { path: "aitracker/web/dead.js", created: true, alive: false, last: "2026-01-01T00:00:00.000Z" },
    { path: "aitracker/web/legacy.js", created: true, last: "2026-01-01T00:00:00.000Z" }
  ],
  prs: [
    { url: "https://github.com/acme/widget/pull/9", repo: "acme/widget", num: 9, created: true, state: "merged", t: "2026-01-01T00:00:00.000Z", agent: true },
    { url: "https://github.com/acme/widget/pull/3", repo: "acme/widget", num: 3, created: false, t: "2026-01-01T00:00:00.000Z" }
  ],
  narrative: [
    { text: "see https://example.com/readme and http://localhost:8790/api/session", t: "2026-01-01T00:00:00.000Z" }
  ],
  requests: [ { text: "check https://example.com/readme again", t: "2026-01-01T00:00:00.000Z" } ],
  commands: [ { cmd: "curl https://example.com/readme", t: "2026-01-01T00:00:00.000Z" } ]
};
var a = window.deriveLinks(session);
var b = window.CR.detail._internal.deriveLinks(session);
console.log("===PARITY_JSON_START===");
console.log(JSON.stringify({ a: a, b: b }));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestDeriveLinksIsOneSharedFunction(unittest.TestCase):
    """Proves the promotion to app.js didn't fork behaviour: the classic
    dashboard's window.deriveLinks and the control room's
    window.CR.detail._internal.deriveLinks must be, and produce, the exact
    same thing for the exact same input."""

    @classmethod
    def setUpClass(cls):
        bundle = _extract_script_content(_read_page())
        js = _BUNDLE_STUB_PREAMBLE + bundle + _PARITY_FIXTURE_JS
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError("parity harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                                  % (returncode, stdout, stderr))
        cls.OUT = _extract_after_marker(stdout, "===PARITY_JSON_START===")

    def test_classic_and_control_room_get_identical_rows(self):
        self.assertEqual(self.OUT["a"], self.OUT["b"])

    def test_dead_file_is_skipped_and_legacy_no_flag_file_defaults_shown(self):
        urls = [e["url"] for e in self.OUT["a"]["generated"]]
        self.assertIn("aitracker/web/app.js", urls)
        self.assertIn("aitracker/web/legacy.js", urls, "no `alive` key (older/synthetic data) must default to shown")
        self.assertNotIn("aitracker/web/dead.js", urls, "alive:false must be skipped")

    def test_grouping_verbs_and_aggregation_are_correct(self):
        a = self.OUT["a"]
        self.assertEqual(a["total"], 6)
        gen_by_url = {e["url"]: e for e in a["generated"]}
        self.assertEqual(gen_by_url["https://github.com/acme/widget/pull/9"]["verb"], "merged")
        self.assertTrue(gen_by_url["https://github.com/acme/widget/pull/9"]["agent"])
        self.assertEqual(gen_by_url["http://localhost:8790/api/session"]["verb"], "endpoint",
                          "a localhost URL cited in narration must be classified as generated/endpoint")
        work_by_url = {e["url"]: e for e in a["worked"]}
        self.assertEqual(work_by_url["https://github.com/acme/widget/pull/3"]["verb"], "cited")
        self.assertEqual(work_by_url["https://example.com/readme"]["verb"], "read ×3",
                          "the same URL cited in narrative+requests+commands collapses to one row, count 3")


# ---------------------------------------------------------------------------
# TASK 2b -- the classic Links panel itself: renders, skips dead entries,
# and only ever makes an http(s) URL clickable.
# ---------------------------------------------------------------------------

# A tracked-by-id DOM stub, standalone for app.js only (not the full bundle):
# ids are resolved through a registry so renderLinksPanel()'s dynamically-
# created panel (and the "linkc"/"links" ids inside its innerHTML) can
# actually be found again by $() -- the same generic stub any OTHER id
# resolves to a fresh, harmless element so unrelated top-level app.js init
# code (icon boot, theme, misc addEventListener calls) never dereferences
# null.
_APP_JS_STUB_PREAMBLE = r"""
globalThis.window = globalThis;
var REG = {};
function makeEl(tag) {
  var el = {
    tagName: (tag || "div").toUpperCase(), id: "", className: "",
    style: { setProperty() {}, getPropertyValue() { return ""; } },
    dataset: {}, children: [],
    classList: { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    appendChild(c) { this.children.push(c); if (c && c.id) REG[c.id] = c; return c; },
    insertAdjacentElement(pos, e2) { this.children.push(e2); if (e2 && e2.id) REG[e2.id] = e2; },
    addEventListener() {}, removeEventListener() {}, remove() {}, append() {}, insertBefore() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, focus() {}, click() {},
    textContent: "", hidden: false, _innerHTML: ""
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._innerHTML; },
    set(v) {
      el._innerHTML = v;
      // Lightweight id="..."/id=bare scan -- enough for $() to find the
      // "linkc"/"links" sub-elements renderLinksPanel() writes as a string,
      // without pulling in a real HTML parser (stdlib-only rule).
      var re = /\bid=(?:"([^"]+)"|'([^']+)'|([^\s>]+))/g, m;
      while ((m = re.exec(v))) {
        var id = m[1] || m[2] || m[3];
        if (id && !REG[id]) { var sub = makeEl(); sub.id = id; REG[id] = sub; }
      }
    }
  });
  return el;
}
var ACTCOL = makeEl("div"); ACTCOL.className = "actcol";
window.document = {
  createElement: (tag) => makeEl(tag), createTextNode: () => makeEl(),
  getElementById: (id) => {
    if (id === "linkspanel") return REG[id] || null; // force the create-once path under test
    if (REG[id]) return REG[id];
    var stub = makeEl(); stub.id = id; return stub;
  },
  querySelector: (sel) => sel === ".actcol" ? ACTCOL : null,
  querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  documentElement: makeEl("html"), body: makeEl("body"), head: makeEl("head"),
  readyState: "complete"
};
const _localStorage = {};
window.localStorage = {
  getItem: (k) => (k in _localStorage) ? _localStorage[k] : null,
  setItem: (k, v) => { _localStorage[k] = v; },
  removeItem: (k) => { delete _localStorage[k]; }
};
window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {}, removeEventListener() {} });
window.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}), text: () => Promise.resolve("") });
window.setInterval = () => 0; window.setTimeout = () => 0; window.clearInterval = () => {}; window.clearTimeout = () => {};
window.location = { href: "", search: "", pathname: "/" };
window.navigator = { userAgent: "node", clipboard: { writeText: () => Promise.resolve() } };
window.CustomEvent = function (type, opts) { this.type = type; this.detail = opts && opts.detail; };
window.Event = window.CustomEvent;
window.requestAnimationFrame = () => 0;
window.getComputedStyle = () => ({ getPropertyValue: () => "" });
window.getSelection = () => ({ toString: () => "" });
window.addEventListener = () => {}; window.removeEventListener = () => {}; window.dispatchEvent = () => {};
process.on("unhandledRejection", () => {});
"""

_LINKS_PANEL_FIXTURE_JS = r"""
var session = {
  now: 1780000000,
  files: [
    { path: "aitracker/web/app.js", created: true, alive: true, last: "2026-01-01T00:00:00.000Z" },
    { path: "aitracker/web/dead.js", created: true, alive: false, last: "2026-01-01T00:00:00.000Z" },
    { path: "javascript:alert(1)", created: true, alive: true, last: "2026-01-01T00:00:00.000Z" },
    { path: "<img src=x onerror=alert(1)>", created: true, alive: true, last: "2026-01-01T00:00:00.000Z" }
  ],
  prs: [ { url: "https://github.com/acme/widget/pull/9", repo: "acme/widget", num: 9, created: true, state: "open", t: "2026-01-01T00:00:00.000Z" } ],
  narrative: [ { text: "see https://example.com/readme", t: "2026-01-01T00:00:00.000Z" } ],
  requests: [], commands: []
};
renderLinksPanel(session);
var linksEl = document.getElementById("links");
var linkcEl = document.getElementById("linkc");
console.log("===LINKSPANEL_JSON_START===");
console.log(JSON.stringify({ html: linksEl.innerHTML, count: linkcEl.textContent }));
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestClassicLinksPanelRenders(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        js = _APP_JS_STUB_PREAMBLE + _read_app_js() + _LINKS_PANEL_FIXTURE_JS
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError("renderLinksPanel harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                                  % (returncode, stdout, stderr))
        cls.OUT = _extract_after_marker(stdout, "===LINKSPANEL_JSON_START===")
        cls.html = cls.OUT["html"]

    def test_panel_renders_and_counts_only_live_entries(self):
        # 4 alive entries (app.js, javascript:.., <img..>, the PR) + 1 worked (readme) = 5.
        # aitracker/web/dead.js (alive:false) must NOT be counted.
        self.assertEqual(self.OUT["count"], 5)

    def test_dead_file_entry_is_skipped_entirely(self):
        self.assertNotIn("dead.js", self.html)

    def test_legit_https_pr_is_a_real_clickable_link(self):
        self.assertIn('<a class=prlink href="https://github.com/acme/widget/pull/9"', self.html)
        self.assertIn("target=_blank rel=noopener", self.html)

    def test_local_file_path_is_not_clickable(self):
        """A local path is real history (it was created here) but the
        browser can't usefully open it -- it must render as inert text
        inside a plain <div>, not an <a>."""
        self.assertIn(
            '<div class=prlink><span class="kind new">wrote</span>'
            '<span class=prurl title="aitracker/web/app.js">aitracker/web/app.js</span>',
            self.html,
        )
        self.assertNotIn('href="aitracker/web/app.js"', self.html)

    def test_javascript_scheme_never_becomes_an_href(self):
        """A hostile/fake local 'path' using the javascript: scheme must
        never be turned into a clickable link -- only http(s) may ever
        reach an href."""
        self.assertNotRegex(self.html.lower(), r'href="javascript:',
                             "a javascript: URL was made clickable: %r" % self.html)
        self.assertNotRegex(self.html.lower(), r"href='javascript:")

    def test_script_and_img_tags_are_neutralised_not_live(self):
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<img", self.html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", self.html)

    def test_only_http_entries_are_wrapped_in_an_anchor(self):
        """Structural check: exactly the http(s) entries (the PR + the
        narration-cited readme link) get <a>; everything else (the clean
        local path, the javascript: fake path, the <img> fake path) gets the
        same visual row via a plain, non-clickable <div class=prlink>."""
        self.assertEqual(self.html.count("<a class=prlink"), 2)
        self.assertEqual(self.html.count("<div class=prlink>"), 3)


# ---------------------------------------------------------------------------
# CSS: the tags md() actually produces (code/strong/em/a) and the classic
# panel classes the Links section reuses must still be styled -- guards
# against a concurrent edit to app.css dropping them out from under this pass.
# ---------------------------------------------------------------------------

class TestSupportingCssStillPresent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(_ROOT, "aitracker", "web", "app.css"), encoding="utf-8") as fh:
            cls.css = fh.read()

    def test_markdown_produced_tags_are_styled(self):
        for selector in ("code{", "strong{", "em{"):
            self.assertIn(selector, self.css)
        self.assertRegex(self.css, r'(?<![.\w])a\{color')

    def test_links_panel_reuses_existing_classic_classes_not_new_ones(self):
        for selector in (".prlink{", ".prurl{", ".prtime{", ".kind{", ".agenttag{"):
            self.assertIn(selector, self.css, "%s must already exist (reused, not invented)" % selector)
        self.assertIn(".linkgrp{", self.css, "the one small new group-label rule this pass adds")


if __name__ == "__main__":
    unittest.main()
