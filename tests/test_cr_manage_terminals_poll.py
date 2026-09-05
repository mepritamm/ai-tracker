"""Regression test for: the "Manage terminals" dialog (aitracker/web/ext_cr_dialogs.js's
renderManageTerminals) went empty a poll round after opening, even with a terminal
actually running.

THE BUG: ext_cr_boot.js's SIDE_EXT hook broadcasts `window.CR.dialogs.update({flags, sessions,
now})` on every poll tick (~2s cadence) so the Flags dialog stays live -- but
CR.dialogs.update()/open() (ext_cr_dialogs.js's generic `update(state)`/`open(name, payload)`)
forward that blob to WHICHEVER dialog happens to be topmost, unconditionally, regardless of
whether it was meant for that dialog. renderManageTerminals's own `update` closure used to do
a blind `payload = p || {}; paint();` -- so the very next poll after opening "Manage terminals"
clobbered its real `{terminals, max, onPeek, onKill, onCloseAll}` payload with the broadcast's
unrelated `{flags, sessions, now}` shape. With no `terminals`/`max` fields, `paint()` computed
`terms = [] `, `max = 0`, and rendered "Manage terminals — 0 of 0 running" plus the empty state
-- while a terminal was still actually running.

THE FIX: the dialog's `update` closure now ignores any payload that carries neither `terminals`
nor `error` -- the two shapes every real manage-terminals payload always carries (see
ext_cr_term.js's `_openManageDialog`/`_openCapDialog`, the only real callers) -- instead of
accepting whatever the generic broadcast forwarder hands it.

IDIOM: same "brace-match the exact function out of the real bundle" technique as
test_cr_rail_toggle.py's _extract_function()/_run_node() -- never a hand-retyped paraphrase, so
a source-shape drift fails loudly instead of silently testing stale text. renderManageTerminals's
own DOM calls (buildChrome/h/icon/emptyState/errorState/sessionTitleFor/timeAgo/cwdTail) are
stubbed to the minimum needed to read back the dialog's title text and know whether the empty
state painted -- not a no-op stub (that would make every assertion here vacuously pass), but real
enough that a title/emptyState mismatch is actually observable.
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

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
    matches = list(script_pattern.finditer(html))
    if not matches:
        raise ValueError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the real
    bundle. Raises loudly (never returns a guess) if the shape has moved, so this
    test fails honestly instead of silently exercising stale text. Copied from
    test_cr_rail_toggle.py's own helper of the same name/behaviour."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found in the real bundle" % name)
    brace_start = source.index('{', m.start())
    depth = 0
    for i in range(brace_start, len(source)):
        c = source[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return source[m.start():i + 1]
    raise AssertionError("unterminated function %s() (brace mismatch)" % name)


def _run_node(js_source, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(js_source)
        proc = subprocess.run(["node", path], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _extract_json(stdout):
    marker = "===MANAGE_TERMINALS_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


def _driver_js():
    html = _read_page()
    bundle = _extract_script_content(html)
    fn_src = _extract_function(bundle, "renderManageTerminals")

    return r"""
var OUT = {};
(function () {
  // Minimal, honest-enough stubs: a real title element and a real body element
  // whose appendChild/innerHTML are actually observable, so a wrong paint()
  // shows up rather than passing vacuously.
  var titleEl = { textContent: '' };
  var bodyChildren = [];
  var body = {
    appendChild: function (c) { bodyChildren.push(c); },
  };
  Object.defineProperty(body, 'innerHTML', {
    set: function () { bodyChildren = []; },
    get: function () { return ''; },
  });
  function buildChrome() {
    return {
      backdrop: {},
      panel: { classList: { toggle: function () {} }, querySelector: function () { return titleEl; } },
      body: body,
    };
  }
  function errorState(opts) { return { kind: 'error', opts: opts }; }
  function emptyState(opts) { return { kind: 'empty', opts: opts }; }
  function h(tag, attrs, children) {
    var kids = (children || []).slice();
    return {
      tag: tag, attrs: attrs, children: kids,
      appendChild: function (c) { kids.push(c); },
    };
  }
  function icon(name) { return { icon: name }; }
  var sessions = [];
  function sessionTitleFor(sid) { return null; }
  function timeAgo(t) { return 'AGO'; }
  function cwdTail(cwd) { return cwd; }

  %s

  var terminals = [{ tty: '/dev/pts/3', cwd: '/proj', started: 1000, session: '', mode: '' }];
  var built = renderManageTerminals({
    terminals: terminals, max: 4,
    onPeek: function () {}, onKill: function () {}, onCloseAll: function () {},
  });
  OUT['title_after_open'] = titleEl.textContent;
  OUT['empty_after_open'] = bodyChildren.some(function (c) { return c && c.kind === 'empty'; });

  // THE BUG, reproduced exactly: ext_cr_boot.js's SIDE_EXT poll broadcasts this
  // shape to whichever dialog is topmost, every ~2s, regardless of which dialog
  // that is (see ext_cr_boot.js:903-904's window.CR.dialogs.update(...) call).
  built.update({ flags: [], sessions: [], now: 1234 });
  OUT['title_after_unrelated_broadcast'] = titleEl.textContent;
  OUT['empty_after_unrelated_broadcast'] = bodyChildren.some(function (c) { return c && c.kind === 'empty'; });

  // A REAL re-open (ext_cr_term.js's _openManageDialog/_openCapDialog, the only
  // legitimate callers) must still land -- the fix must ignore the broadcast,
  // not manage-terminals updates in general.
  built.update({
    terminals: terminals.concat([{ tty: '/dev/pts/4', cwd: '/proj2', started: 1000, session: '', mode: '' }]),
    max: 4, onPeek: function () {}, onKill: function () {}, onCloseAll: function () {},
  });
  OUT['title_after_real_reopen'] = titleEl.textContent;

  // An error re-open (the list-fetch-failed path) is the other real shape and
  // must also still land.
  built.update({ error: 'boom' });
  OUT['title_after_error_reopen'] = titleEl.textContent;
  OUT['error_shown_after_error_reopen'] = bodyChildren.some(function (c) { return c && c.kind === 'error'; });
})();
console.log("===MANAGE_TERMINALS_JSON_START===");
console.log(JSON.stringify(OUT));
""" % fn_src


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestManageTerminalsDialogSurvivesUnrelatedPollBroadcast(unittest.TestCase):
    """Pins renderManageTerminals()'s `update` closure against the REAL shipped
    source (brace-matched out of the assembled page's bundle), not a hand-retyped
    paraphrase of it."""

    @classmethod
    def setUpClass(cls):
        js = _driver_js()
        returncode, stdout, stderr = _run_node(js)
        if returncode != 0:
            raise AssertionError(
                "Manage-terminals harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s"
                % (returncode, stdout, stderr)
            )
        cls.OUT = _extract_json(stdout)

    def test_opens_with_the_real_running_count(self):
        self.assertEqual(self.OUT["title_after_open"], "Manage terminals — 1 of 4 running")
        self.assertFalse(self.OUT["empty_after_open"])

    def test_unrelated_poll_broadcast_does_not_clobber_the_dialog(self):
        """THE BUG, precisely: a {flags, sessions, now} broadcast meant for the
        Flags dialog -- forwarded here only because this dialog happened to be
        topmost when the poll fired -- must leave the terminals list alone, not
        reset the dialog to "0 of 0 running" / the empty state."""
        self.assertEqual(
            self.OUT["title_after_unrelated_broadcast"], "Manage terminals — 1 of 4 running",
            "an unrelated poll broadcast overwrote the real terminal count")
        self.assertFalse(
            self.OUT["empty_after_unrelated_broadcast"],
            "an unrelated poll broadcast made the dialog fall back to the empty state")

    def test_a_real_reopen_with_fresh_terminals_still_updates(self):
        """The fix must not make the dialog inert to real updates -- only to
        broadcasts that aren't meant for it."""
        self.assertEqual(self.OUT["title_after_real_reopen"], "Manage terminals — 2 of 4 running")

    def test_a_real_error_reopen_still_updates(self):
        """The list-fetch-failed path re-opens with {error}, not {terminals} --
        the other real shape this dialog must still accept."""
        self.assertTrue(self.OUT["error_shown_after_error_reopen"])


if __name__ == "__main__":
    unittest.main()
