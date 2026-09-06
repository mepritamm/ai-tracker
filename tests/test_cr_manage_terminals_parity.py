"""Regression test for: the Control Room's "Manage terminals" dialog had buttons that were wired
to nothing, or wired without the guards the dashboard's equivalent has.

THE BUGS (all in aitracker/web/ext_cr_dialogs.js's renderManageTerminals):

  1. "Close all" was a SILENT NO-OP. The confirm button called `payload.onCloseAll()` with NO
     ARGUMENTS, while its only implementation -- ext_cr_term.js's `_closeAllTerminals(terminals)`
     -- iterates `(terminals || [])`. The list was therefore always `undefined`, the iteration ran
     over an empty array, the promise resolved immediately and NOTHING WAS KILLED. The dialog's
     own documented payload contract said `onCloseAll()` too, so both sides agreed on a contract
     that could not work. The dashboard's twin (ext_vt.js's renderManagerBody) passes the list:
     `closeAll(terminals)`.

  2. No ARM GUARD on the confirm. ext_vt.js swallows any activation within `_ARM_GUARD_MS` of
     arming (`_armGuardActive()`), because the confirm button is revealed synchronously inside the
     first click's own handler, in the box the "Close all" button just vacated -- so the second
     click of a double-click lands on it and kills every terminal with the warning never displayed
     for a single frame. The Control Room had no guard at all.

  3. A FABRICATED SERVER VALUE (conventions rule 5). `var max = payload.max || terms.length`
     invented a cap whenever the server sent none, rendering "1 of 1 running -- free a slot" and
     applying the red at-cap treatment for a cap that was never reached. ext_vt.js deliberately
     omits the "of N" instead of substituting a guess.

THE FIX: the confirm passes `terms`; the dialog installs `window.ExtVT.term.armGuard()` when it
arms and consults it on both the confirm and the Cancel; `max` is read straight off the payload.

IDIOM: same "brace-match the exact function out of the real bundle" technique as
test_cr_manage_terminals_poll.py / test_cr_rail_toggle.py -- never a hand-retyped paraphrase, so a
source-shape drift fails loudly instead of silently testing stale text.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_HAS_NODE = shutil.which("node") is not None

sys.path.insert(0, _ROOT)


def _read_page():
    from aitracker import page
    return page.build_page()


def _extract_script_content(html):
    matches = list(re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL).finditer(html))
    if not matches:
        raise ValueError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the real bundle.
    Raises loudly (never returns a guess) if the shape has moved."""
    start = source.find("function " + name + "(")
    if start < 0:
        raise AssertionError("function %s() not found in the assembled bundle" % name)
    brace = source.find("{", start)
    if brace < 0:
        raise AssertionError("no opening brace for %s()" % name)
    depth, i, n = 0, brace, len(source)
    while i < n:
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    raise AssertionError("unbalanced braces while extracting %s()" % name)


_HARNESS = r"""
var OUT = {};
(function () {
  // ---- minimum stubs: real enough that a wiring mistake is observable, never no-ops ----
  var ALL = [];
  var titleEl = { textContent: '' };
  var bodyChildren = [];
  function buildChrome(name, title) {
    return {
      backdrop: {}, panel: {
        querySelector: function () { return titleEl; },
        classList: { toggle: function (cls, on) { OUT['cap_class_' + cls] = !!on; } },
      },
      body: {
        innerHTML: '',
        appendChild: function (c) { bodyChildren.push(c); },
      },
    };
  }
  function errorState(o) { return { kind: 'error', opts: o }; }
  function emptyState(o) { return { kind: 'empty', opts: o }; }
  function h(tag, attrs, children) {
    attrs = attrs || {};
    var node = {
      tag: tag, attrs: attrs, children: (children || []).slice(),
      appendChild: function (c) { node.children.push(c); },
    };
    if ('text' in attrs) node.textContent = attrs.text;
    if ('hidden' in attrs) node.hidden = attrs.hidden;
    ALL.push(node);
    return node;
  }
  function icon(n) { return { icon: n }; }
  var sessions = [];
  function sessionTitleFor() { return null; }
  function timeAgo() { return 'AGO'; }
  function cwdTail(c) { return c; }

  // ---- the real function, lifted verbatim from the assembled bundle ----
  %s

  // ---- helpers over the stub tree ----
  function reset() { ALL = []; bodyChildren = []; titleEl.textContent = ''; }
  function findByText(t) {
    for (var i = ALL.length - 1; i >= 0; i--) {
      if (ALL[i].tag === 'button' && String(ALL[i].textContent || '') === t) return ALL[i];
    }
    return null;
  }
  function findByTextPrefix(p) {
    for (var i = ALL.length - 1; i >= 0; i--) {
      if (ALL[i].tag === 'button' && String(ALL[i].textContent || '').indexOf(p) === 0) return ALL[i];
    }
    return null;
  }
  function allText() {
    return ALL.map(function (n) {
      var s = String(n.textContent || '');
      (n.children || []).forEach(function (c) { if (typeof c === 'string') s += c; });
      return s;
    }).join(' | ');
  }
  function click(n) { n.attrs.onclick(); }

  var TERMS = [
    { tty: '/dev/pts/3', cwd: '/proj', started: 1000, session: '', mode: '' },
    { tty: '/dev/pts/4', cwd: '/proj2', started: 1000, session: '', mode: '' },
  ];

  // ===== SCENARIO A: "Close all" must hand the terminal LIST to onCloseAll =====
  // window.ExtVT.term.armGuard() is stubbed to a predicate that is always FALSE (guard elapsed),
  // so this scenario isolates the argument-passing bug from the timing guard.
  var window = { ExtVT: { term: { armGuard: function () { return function () { return false; }; } } } };
  reset();
  var closeAllArg = 'NEVER_CALLED';
  renderManageTerminals({
    terminals: TERMS, max: 4,
    onPeek: function () {}, onKill: function () {},
    onCloseAll: function (list) { closeAllArg = list; },
  });
  click(findByText('Close all'));            // arm
  var confirmA = findByTextPrefix('Yes, kill all');
  OUT['confirm_button_exists'] = !!confirmA;
  OUT['confirm_label'] = confirmA ? confirmA.textContent : null;
  if (confirmA) click(confirmA);
  OUT['close_all_called'] = closeAllArg !== 'NEVER_CALLED';
  OUT['close_all_arg_is_array'] = Array.isArray(closeAllArg);
  OUT['close_all_arg_len'] = Array.isArray(closeAllArg) ? closeAllArg.length : -1;

  // ===== SCENARIO B: the arm guard must be INSTALLED and CONSULTED =====
  // armGuard() now returns a predicate that is always TRUE (still inside the arm window), which
  // is exactly the double-click case. onCloseAll must NOT fire.
  var guardAsked = 0;
  window = { ExtVT: { term: { armGuard: function () {
    OUT['arm_guard_installed'] = true;
    return function () { guardAsked++; return true; };
  } } } };
  reset();
  var firedB = false;
  renderManageTerminals({
    terminals: TERMS, max: 4,
    onPeek: function () {}, onKill: function () {},
    onCloseAll: function () { firedB = true; },
  });
  click(findByText('Close all'));            // arm -> installs the guard
  click(findByTextPrefix('Yes, kill all'));  // the double-click's second click
  OUT['guard_consulted'] = guardAsked > 0;
  OUT['close_all_fired_while_armed'] = firedB;

  // ===== SCENARIO C: the cap is the SERVER's number -- never fabricated =====
  window = { ExtVT: { term: { armGuard: function () { return function () { return false; }; } } } };
  reset();
  renderManageTerminals({
    terminals: TERMS,                        // NOTE: no `max` -- the server sent none
    onPeek: function () {}, onKill: function () {}, onCloseAll: function () {},
  });
  OUT['title_without_max'] = titleEl.textContent;

  reset();
  renderManageTerminals({
    terminals: TERMS, max: 4,
    onPeek: function () {}, onKill: function () {}, onCloseAll: function () {},
  });
  OUT['title_with_max'] = titleEl.textContent;

  // ===== SCENARIO D: the warning must name the blast radius =====
  reset();
  renderManageTerminals({
    terminals: TERMS, max: 4,
    onPeek: function () {}, onKill: function () {}, onCloseAll: function () {},
  });
  click(findByText('Close all'));
  OUT['warning_text'] = allText();

  // ===== SCENARIO E: the close-all sweep must LATCH the panel for its whole duration =====
  // The arm guard only covers the first ~500ms after arming. killSeries is SEQUENTIAL -- one HTTP
  // round trip per terminal -- so a real sweep routinely outlasts that window, after which the
  // still-visible confirm button would fire a SECOND sweep across a half-drained list. The guard
  // and the latch cover different spans; both are required.
  window = { ExtVT: { term: { armGuard: function () { return function () { return false; }; } } } };
  reset();
  var resolveSweep = null;
  renderManageTerminals({
    terminals: TERMS, max: 4,
    onPeek: function () {}, onKill: function () {},
    onCloseAll: function () { return new Promise(function (res) { resolveSweep = res; }); },
  });
  click(findByText('Close all'));
  var confirmE = findByTextPrefix('Yes, kill all');
  click(confirmE);                                  // sweep starts, promise still pending
  OUT['confirm_disabled_during_sweep'] = !!confirmE.disabled;
  var rowKill = null;
  for (var k = 0; k < ALL.length; k++) {
    var cls = String((ALL[k].attrs && ALL[k].attrs.class) || '');
    if (ALL[k].tag === 'button' && cls.indexOf('cr-btn-danger') >= 0 && ALL[k] !== confirmE) { rowKill = ALL[k]; break; }
  }
  OUT['row_kill_found'] = !!rowKill;
  OUT['row_kill_disabled_during_sweep'] = !!(rowKill && rowKill.disabled);
})();
console.log("===PARITY_JSON_START===");
console.log(JSON.stringify(OUT));
"""


def _run_node(script):
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError("node failed: %s\n%s" % (proc.stderr[-2000:], proc.stdout[-1000:]))
    marker = "===PARITY_JSON_START==="
    idx = proc.stdout.find(marker)
    if idx < 0:
        raise AssertionError("no JSON marker in node output:\n%s" % proc.stdout[-2000:])
    return json.loads(proc.stdout[idx + len(marker):].strip().splitlines()[0])


@unittest.skipUnless(_HAS_NODE, "node not available")
class ManageTerminalsParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = _extract_script_content(_read_page())
        fn = _extract_function(src, "renderManageTerminals")
        cls.out = _run_node(_HARNESS % fn)

    def test_close_all_receives_the_terminal_list(self):
        """THE dead button: onCloseAll() was called with no arguments, so the only implementation
        (_closeAllTerminals(terminals)) iterated `undefined || []` and killed nothing."""
        self.assertTrue(self.out.get("confirm_button_exists"),
                        "arming 'Close all' must reveal a confirm button")
        self.assertTrue(self.out.get("close_all_called"),
                        "confirming must actually invoke onCloseAll")
        self.assertTrue(self.out.get("close_all_arg_is_array"),
                        "onCloseAll must receive the terminal LIST, not undefined "
                        "(got: %r) -- this is the no-op bug" % (self.out.get("close_all_arg_len"),))
        self.assertEqual(self.out.get("close_all_arg_len"), 2,
                         "onCloseAll must receive every terminal the rows were drawn from")

    def test_confirm_is_arm_guarded_against_a_double_click(self):
        """The confirm is revealed inside the first click's own handler, in the box the armed
        button just vacated -- without the guard, click two of a double-click kills everything."""
        self.assertTrue(self.out.get("arm_guard_installed"),
                        "arming must install window.ExtVT.term.armGuard() -- the shared seam owns "
                        "the delay, so no second timing constant is retyped in the dialog")
        self.assertTrue(self.out.get("guard_consulted"),
                        "the confirm handler must consult the arm guard")
        self.assertFalse(self.out.get("close_all_fired_while_armed"),
                         "a confirm activated while still inside the arm window must be swallowed")

    def test_cap_is_never_fabricated_when_the_server_sends_none(self):
        """conventions rule 5: the server owns the cap. `payload.max || terms.length` invented one,
        producing '2 of 2 running -- free a slot' for a cap that was never reached."""
        without = self.out.get("title_without_max") or ""
        self.assertIn("2 running", without)
        self.assertNotIn(" of ", without,
                         "with no server cap the title must omit 'of N' entirely, not guess it "
                         "(got %r)" % without)
        self.assertNotIn("free a slot", without,
                         "a fabricated cap must not trigger the at-cap treatment (got %r)" % without)
        self.assertIn("2 of 4 running", self.out.get("title_with_max") or "",
                      "a real server cap must still be rendered")

    def test_warning_names_the_blast_radius(self):
        """The dashboard's warning says how many die and that Claude sessions are inside them."""
        text = self.out.get("warning_text") or ""
        self.assertIn("2 running terminal", text)
        self.assertIn("cannot be undone", text)
        self.assertIn("Yes, kill all 2", text,
                      "the confirm must name the count, so it can never be mistaken for the "
                      "harmless button it replaced")


    def test_close_all_latches_the_panel_for_the_whole_sweep(self):
        """The arm guard is a ~500ms double-click guard. A sequential kill of several terminals
        outlasts it, so without a latch the still-visible confirm fires a second overlapping
        sweep across a list the first one is halfway through draining."""
        self.assertTrue(self.out.get("row_kill_found"), "harness must locate a row kill button")
        self.assertTrue(self.out.get("confirm_disabled_during_sweep"),
                        "the confirm button must disable itself while the kill sweep is in flight")
        self.assertTrue(self.out.get("row_kill_disabled_during_sweep"),
                        "every row's kill button must latch during the sweep too -- they target "
                        "terminals the sweep is already killing")


_PICKER_HARNESS = r"""
var OUT = {};
(function () {
  var ALL = [];
  var titleEl = { textContent: '' };
  var closed = 0;
  function close() { closed++; }
  function buildChrome() {
    return {
      backdrop: {}, panel: { querySelector: function () { return titleEl; } },
      body: { innerHTML: '', appendChild: function () {} },
    };
  }
  function emptyState(o) { return { kind: 'empty', opts: o }; }
  function h(tag, attrs, children) {
    attrs = attrs || {};
    var node = { tag: tag, attrs: attrs, children: (children || []).slice(),
                 appendChild: function (c) { node.children.push(c); } };
    if ('text' in attrs) node.textContent = attrs.text;
    ALL.push(node);
    return node;
  }

  %s

  function findStart() {
    for (var i = ALL.length - 1; i >= 0; i--) {
      if (ALL[i].tag === 'button' && /^(Start|Opening…)$/.test(String(ALL[i].textContent || ''))) return ALL[i];
    }
    return null;
  }
  function findInput() {
    for (var i = ALL.length - 1; i >= 0; i--) if (ALL[i].tag === 'input') return ALL[i];
    return null;
  }

  // The dialog's OWN open sequence: shown first with {loading:true}, then re-opened with the cwds
  // list once GET /api/term/cwds resolves. That second open runs update() -> paint().
  var onPick = function () { return new Promise(function () {}); };   // never settles: still in flight
  var built = renderDirectoryPicker({ loading: true, title: 'New terminal', onPick: onPick });

  // The user types a path and hits Start BEFORE the directory list arrives -- reachable because
  // the text field and Start button render even while loading.
  findInput().value = '/tmp/proj';
  var startBefore = findStart();
  startBefore.attrs.onclick();
  OUT['start_disabled_during_flight'] = !!startBefore.disabled;
  OUT['label_during_flight'] = startBefore.textContent;
  OUT['closed_before_settle'] = closed;

  // Now the cwds response lands and repaints the dialog while that POST is STILL in flight.
  built.update({ title: 'New terminal', cwds: [{ path: '/a', label: 'a' }], onPick: onPick });
  var startAfter = findStart();
  OUT['repaint_made_new_button'] = startAfter !== startBefore;
  OUT['start_disabled_after_repaint'] = !!startAfter.disabled;

  // ...and a click on that repainted button must not fire a SECOND spawn.
  var second = 0;
  built.update({ title: 'New terminal', cwds: [{ path: '/a', label: 'a' }],
                 onPick: function () { second++; return new Promise(function () {}); } });
  var startAgain = findStart();
  findInput().value = '/tmp/proj';
  startAgain.attrs.onclick();
  OUT['second_spawn_fired'] = second;

  // ===== a spawn that FAILS after a repaint must re-enable the LIVE controls =====
  // release() used to close over the button the CLICK started on. When a repaint landed between
  // submit and settle, that node was already detached: release cleared `busy` but re-enabled a
  // button nobody could see, leaving the on-screen Start stuck disabled and reading "Opening…"
  // with no further repaint to reconcile it -- a dead dialog until closed and reopened.
  var rejectSpawn = null;
  var built2 = renderDirectoryPicker({
    loading: true, title: 'New terminal',
    onPick: function () { return new Promise(function (_res, rej) { rejectSpawn = rej; }); },
  });
  findInput().value = '/tmp/x';
  findStart().attrs.onclick();                       // spawn starts on THIS render's button
  built2.update({ title: 'New terminal', cwds: [{ path: '/a', label: 'a' }],
                  onPick: function () { return new Promise(function () {}); } });
  OUT['live_disabled_before_reject'] = !!findStart().disabled;
  rejectSpawn(new Error('spawn failed'));            // ... and now it fails

  setTimeout(function () {
    var after = findStart();
    OUT['live_enabled_after_reject'] = !after.disabled;
    OUT['live_label_after_reject'] = after.textContent;
    console.log("===PICKER_JSON_START===");
    console.log(JSON.stringify(OUT));
  }, 0);
})();
"""


@unittest.skipUnless(_HAS_NODE, "node not available")
class DirectoryPickerDoubleSubmit(unittest.TestCase):
    """The picker re-opens ITSELF (loading -> cwds), and that re-open repaints. A busy flag scoped
    to paint() is wiped by the dialog's own load sequence, handing back a live Start button while
    the first POST /api/term/pty is still in flight -- reintroducing the exact double-submit the
    guard was written to prevent."""

    @classmethod
    def setUpClass(cls):
        src = _extract_script_content(_read_page())
        fn = _extract_function(src, "renderDirectoryPicker")
        proc = subprocess.run(["node", "-e", _PICKER_HARNESS % fn],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError("node failed: %s" % proc.stderr[-2000:])
        marker = "===PICKER_JSON_START==="
        idx = proc.stdout.find(marker)
        if idx < 0:
            raise AssertionError("no JSON marker:\n%s" % proc.stdout[-2000:])
        cls.out = json.loads(proc.stdout[idx + len(marker):].strip().splitlines()[0])

    def test_start_disables_while_the_spawn_is_in_flight(self):
        self.assertTrue(self.out.get("start_disabled_during_flight"))
        self.assertEqual(self.out.get("label_during_flight"), "Opening…")
        self.assertEqual(self.out.get("closed_before_settle"), 0,
                         "the picker must NOT close before the spawn settles")

    def test_busy_state_survives_the_dialogs_own_repaint(self):
        self.assertTrue(self.out.get("repaint_made_new_button"),
                        "sanity: the cwds re-open really does rebuild the controls")
        self.assertTrue(self.out.get("start_disabled_after_repaint"),
                        "the repaint handed back an ENABLED Start button while a spawn was still "
                        "in flight -- the double-submit guard did not survive paint()")

    def test_repainted_button_cannot_fire_a_second_spawn(self):
        self.assertEqual(self.out.get("second_spawn_fired"), 0,
                         "clicking the repainted Start button fired a second POST /api/term/pty "
                         "while the first was still outstanding")

    def test_a_failed_spawn_re_enables_the_controls_that_are_actually_on_screen(self):
        """release() must reconcile the CURRENT render. Closing over the clicked button meant a
        repaint mid-flight left the visible Start button permanently disabled."""
        self.assertTrue(self.out.get("live_disabled_before_reject"),
                        "sanity: the live button is disabled while the spawn is in flight")
        self.assertTrue(self.out.get("live_enabled_after_reject"),
                        "a failed spawn left the ON-SCREEN Start button disabled forever -- "
                        "release() reconciled a detached node from a discarded render")
        self.assertEqual(self.out.get("live_label_after_reject"), "Start",
                         "the live button must return to its 'Start' label, not stay 'Opening…'")


class ManageDialogSingleKillIsWired(unittest.TestCase):
    """The everyday single 'kill' inside Manage terminals was wired to the bare _killTerminal,
    which only refreshes st.running and the badge: the killed row stayed visibly in the OPEN
    dialog until it was closed and reopened, and a failed kill reported nothing at all."""

    def setUp(self):
        path = os.path.join(_ROOT, "aitracker", "web", "ext_cr_term.js")
        with open(path, encoding="utf-8") as fh:
            self.src = fh.read()

    def _open_manage_body(self):
        i = self.src.index("function _openManageDialog(")
        j = self.src.index("function _peekTerminal(", i)
        return self.src[i:j]

    def test_single_kill_repaints_and_reports(self):
        body = self._open_manage_body()
        self.assertNotIn("onKill: _killTerminal,", body,
                         "the bare _killTerminal never repaints the open dialog and swallows no "
                         "failure -- it must be wrapped")
        self.assertIn("_repaintManage()", body,
                      "a successful kill must repaint the dialog so the row disappears")
        self.assertIn(".catch(", body,
                      "a failed kill must be reported, not left as an unhandled rejection")
        self.assertIn("showToast(", body)

    def test_the_deferred_repaint_does_not_reopen_a_dismissed_dialog(self):
        """_repaintManage fires after REAP_SETTLE_MS. open()'s same-name dedupe only folds into
        update() while the dialog is STILL topmost -- otherwise it pushes a new one. So a user who
        kills a terminal and immediately closes the dialog would have it spring back open."""
        i = self.src.index("function _repaintManage(")
        # Cut at the next TOP-LEVEL declaration (two-space indent), not the next "function "
        # anywhere -- the body contains an anonymous setTimeout callback.
        j = self.src.index("\n  function ", i + 1)
        body = self.src[i:j]
        self.assertIn("topName()", body,
                      "the deferred repaint must confirm the manage dialog is still on screen "
                      "before re-opening it")
        self.assertIn('"manage-terminals"', body)

    def test_dialogs_exposes_the_top_dialog_name(self):
        """The accessor _repaintManage relies on must actually be exported."""
        path = os.path.join(_ROOT, "aitracker", "web", "ext_cr_dialogs.js")
        with open(path, encoding="utf-8") as fh:
            dialogs = fh.read()
        self.assertIn("topName:", dialogs)
        self.assertIn("window.CR.dialogs = {", dialogs)


if __name__ == "__main__":
    unittest.main()
