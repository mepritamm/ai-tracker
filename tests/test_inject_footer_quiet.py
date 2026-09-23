"""Regression tests for the footer-redraw-defeats-quiescence bug in aitracker.term_vt.inject().

`_wait_for_quiescence` used to reset its idle clock on ANY pty byte (`Pty.last_output`), so a
Claude Code CLI whose footer/status line redraws faster than `INJECT_QUIET_WINDOW` was never
"quiet" and `inject()` (used by /model, /effort) always timed out against it. The fix
(`_body_rows_version`, `INJECT_IGNORE_BOTTOM_ROWS`) ignores the bottom rows -- the footer band --
when deciding quiescence, while still honouring real transcript output above that band.

Real ptys via `term_vt.spawn()`, mirroring `TestSpawnAndScreen` in test_term_vt.py: a tiny python
child plays the role of the redrawing TUI. No mocking of the PTY layer itself, only of the
`INJECT_*` timing constants where a test needs to stay fast.
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, term_vt


class _FakeHeaders:
    def __init__(self, d=None):
        self._d = d or {}

    def get(self, name, default=""):
        return self._d.get(name, default)


class _FakeHandler:
    """Stands in for the real Handler: records the one _json() call a route makes -- same shape
    as test_term_vt.py's own _FakeHandler."""

    def __init__(self):
        self.headers = _FakeHeaders()
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


def _wait_for(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


# A redraw confined to the LAST row (1-indexed row 24 of a 24-row screen) -- squarely inside the
# default INJECT_IGNORE_BOTTOM_ROWS=5 band -- alongside a stdin reader that echoes what it
# receives as a new line ABOVE the footer, so a real submit is independently observable on
# screen, not just inferred from inject()'s own "ok" flag.
FOOTER_REDRAW_CHILD = r'''
import sys, threading, time
sys.stdout.write("ready\r\n> \r\n")
sys.stdout.flush()

def _footer():
    n = 0
    while True:
        n += 1
        sys.stdout.write("\x1b7\x1b[24;1H\x1b[2Kstatus %d auto\x1b8" % n)
        sys.stdout.flush()
        time.sleep(0.4)

threading.Thread(target=_footer, daemon=True).start()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write("GOT:" + line.strip() + "\r\n")
    sys.stdout.flush()
'''

# A redraw confined to a row ABOVE the footer band (row 3 of a 24-row screen, well inside the
# body rows _body_rows_version watches) -- this must still keep the terminal "not quiet".
BODY_REDRAW_CHILD = r'''
import sys, threading, time
sys.stdout.write("ready\r\n> \r\n")
sys.stdout.flush()

def _body():
    n = 0
    while True:
        n += 1
        sys.stdout.write("\x1b7\x1b[3;1H\x1b[2Kbody %d\x1b8" % n)
        sys.stdout.flush()
        time.sleep(0.4)

threading.Thread(target=_body, daemon=True).start()
while True:
    time.sleep(10)
'''

# Claude's real bottom layout (rule / prompt / rule / footer) grown TALLER than the fixed
# INJECT_IGNORE_BOTTOM_ROWS=5 floor -- a wrapped status line, a queued-message line, a compact
# warning. The whole block from the rule ABOVE the prompt line down redraws together every 0.4s
# (input-box border included, not just the footer text below it) -- that repaint touches the
# rule directly under the prompt, which sits OUTSIDE a fixed-5-row band (rows 16-24 of a 24-row
# screen: rule=16, prompt=17, rule=18, footer=19-24 -- only 19-24 fall in a bottom-5 band, so the
# row-18 rule redrawing every cycle keeps the old fixed-band code from ever seeing quiet). The
# anchor in `_footer_anchor_band` finds the row-16 rule (the one directly above the prompt) and
# widens the ignored band to cover the whole block instead.
FOOTER_TALL_CHILD = r'''
import sys, threading, time
sys.stdout.write("ready\r\n")
sys.stdout.write("\x1b[16;1H" + ("─" * 40))
sys.stdout.write("\x1b[17;1H❯ ")
sys.stdout.write("\x1b[18;1H" + ("─" * 40))
sys.stdout.write("\x1b[19;1Hqueued: 0")
sys.stdout.write("\x1b[1;1H")
sys.stdout.flush()

def _footer():
    n = 0
    while True:
        n += 1
        sys.stdout.write("\x1b7")
        sys.stdout.write("\x1b[18;1H\x1b[2K" + ("─" * 40))
        for row in (20, 21, 22, 23, 24):
            sys.stdout.write("\x1b[%d;1H\x1b[2Kstatus %d" % (row, n))
        sys.stdout.write("\x1b8")
        sys.stdout.flush()
        time.sleep(0.4)

threading.Thread(target=_footer, daemon=True).start()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write("GOT:" + line.strip() + "\r\n")
    sys.stdout.flush()
'''

# No '>'/'❯' anywhere on screen at all -- `_footer_anchor_band` must find no anchor and
# `_body_rows_version` must fall back to the fixed `INJECT_IGNORE_BOTTOM_ROWS` floor, unchanged
# from before the anchor detection existed. Redraw confined to the last row, same shape as
# FOOTER_REDRAW_CHILD, just with no prompt-marker text drawn anywhere.
NO_MARKER_FOOTER_CHILD = r'''
import sys, threading, time
sys.stdout.write("ready\r\n")
sys.stdout.write("\x1b[1;1H")
sys.stdout.flush()

def _footer():
    n = 0
    while True:
        n += 1
        sys.stdout.write("\x1b7\x1b[24;1H\x1b[2Kstatus %d auto\x1b8" % n)
        sys.stdout.flush()
        time.sleep(0.4)

threading.Thread(target=_footer, daemon=True).start()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write("GOT:" + line.strip() + "\r\n")
    sys.stdout.flush()
'''

# A quiet child (no redraw at all) for the small-screen crash test -- only proves
# _body_rows_version's max(1, rows - INJECT_IGNORE_BOTTOM_ROWS) path doesn't blow up when
# rows <= INJECT_IGNORE_BOTTOM_ROWS, not anything about redraw filtering.
QUIET_ECHO_CHILD = r'''
import sys
sys.stdout.write("ready\r\n> \r\n")
sys.stdout.flush()
while True:
    line = sys.stdin.readline()
    if not line:
        break
    sys.stdout.write("GOT:" + line.strip() + "\r\n")
    sys.stdout.flush()
'''


class TestInjectFooterQuiet(unittest.TestCase):
    """Real pty.fork() + a real Screen -- same feasibility-spike style as
    TestSpawnAndScreen in test_term_vt.py."""

    def setUp(self):
        self._ptys = []
        self._tmpdir = tempfile.TemporaryDirectory()
        self._terminal0, self._auth0 = config.TERMINAL, config.AUTH
        config.TERMINAL, config.AUTH = True, "u:p"

    def tearDown(self):
        config.TERMINAL, config.AUTH = self._terminal0, self._auth0
        for pt in self._ptys:
            try:
                pt.kill()
            except Exception:
                pass
            with term_vt._LOCK:
                term_vt.PTYS.pop(pt.id, None)
            end = time.time() + 5.0
            while not pt.done and time.time() < end:
                time.sleep(0.02)
        self._tmpdir.cleanup()

    def _spawn_script(self, code, rows=24, cols=80):
        path = os.path.join(self._tmpdir.name, "child_%d.py" % len(self._ptys))
        with open(path, "w") as f:
            f.write(code)
        pt = term_vt.spawn(self._tmpdir.name, [sys.executable, path], cols, rows)
        self._ptys.append(pt)
        with term_vt._LOCK:
            term_vt.PTYS[pt.id] = pt
        return pt

    def _snapshot_text(self, pt):
        with pt.lock:
            snap = pt.screen.snapshot(-1)
        return [r[1] for r in snap["rows"]]

    def test_footer_only_redraw_does_not_block_inject(self):
        """A footer redrawing every 0.4s (inside INJECT_IGNORE_BOTTOM_ROWS) must not starve
        quiescence: inject() should succeed and the child must actually receive the text."""
        pt = self._spawn_script(FOOTER_REDRAW_CHILD, rows=24, cols=80)
        self.assertTrue(_wait_for(lambda: any("ready" in t for t in self._snapshot_text(pt)), 5),
                         "child never printed its initial prompt")
        time.sleep(0.5)   # let the footer loop get going before we inject

        h = _FakeHandler()
        term_vt.inject(h, None, {"tty": pt.id, "text": "hello", "submit": True})

        self.assertEqual(len(h.calls), 1)
        result, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertTrue(result.get("ok"), "inject() reported not-ok against a footer-only redraw: %r" % (result,))
        self.assertTrue(result.get("submitted"), "inject() did not observe the submit: %r" % (result,))

        self.assertTrue(_wait_for(lambda: any("GOT:hello" in t for t in self._snapshot_text(pt)), 5),
                         "child never echoed the injected text back")

    def test_tall_wrapped_footer_does_not_block_inject(self):
        """A footer block taller than the fixed INJECT_IGNORE_BOTTOM_ROWS floor -- rule, prompt,
        rule, footer -- that redraws as one unit (the rule below the prompt included, not just
        the footer text under it) must still be recognised as footer via the anchor in
        `_footer_anchor_band`: inject() should succeed and the child must actually receive the
        text, exactly like the plain 5-row-footer case."""
        pt = self._spawn_script(FOOTER_TALL_CHILD, rows=24, cols=80)
        self.assertTrue(_wait_for(lambda: any("ready" in t for t in self._snapshot_text(pt)), 5),
                         "child never printed its initial prompt")
        self.assertTrue(
            _wait_for(lambda: any(t.lstrip().startswith("❯") for t in self._snapshot_text(pt)), 5),
            "child never drew its input line")
        time.sleep(0.5)   # let the footer loop get going before we inject

        h = _FakeHandler()
        term_vt.inject(h, None, {"tty": pt.id, "text": "hello", "submit": True})

        self.assertEqual(len(h.calls), 1)
        result, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertTrue(result.get("ok"), "inject() reported not-ok against a tall footer: %r" % (result,))
        self.assertTrue(result.get("submitted"), "inject() did not observe the submit: %r" % (result,))

        self.assertTrue(_wait_for(lambda: any("GOT:hello" in t for t in self._snapshot_text(pt)), 5),
                         "child never echoed the injected text back")

    def test_no_prompt_marker_falls_back_to_fixed_band(self):
        """No '>'/'❯' anywhere on screen -> `_footer_anchor_band` must find nothing and
        `_body_rows_version` must fall back to the fixed INJECT_IGNORE_BOTTOM_ROWS floor, i.e.
        behave exactly as it did before the anchor detection existed."""
        pt = self._spawn_script(NO_MARKER_FOOTER_CHILD, rows=24, cols=80)
        self.assertTrue(_wait_for(lambda: any("ready" in t for t in self._snapshot_text(pt)), 5),
                         "child never printed its initial prompt")
        time.sleep(0.5)

        with pt.lock:
            self.assertIsNone(term_vt._footer_anchor_band(pt.screen),
                               "anchor detection found a prompt line that was never drawn")

        h = _FakeHandler()
        term_vt.inject(h, None, {"tty": pt.id, "text": "hello", "submit": True})

        self.assertEqual(len(h.calls), 1)
        result, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertTrue(result.get("ok"), "inject() reported not-ok against a marker-less footer: %r" % (result,))
        self.assertTrue(result.get("submitted"), "inject() did not observe the submit: %r" % (result,))

        self.assertTrue(_wait_for(lambda: any("GOT:hello" in t for t in self._snapshot_text(pt)), 5),
                         "child never echoed the injected text back")

    def test_body_redraw_still_blocks_inject(self):
        """A redraw ABOVE the footer band must still count as activity: inject() should time
        out exactly like it did before the fix."""
        pt = self._spawn_script(BODY_REDRAW_CHILD, rows=24, cols=80)
        self.assertTrue(_wait_for(lambda: any("ready" in t for t in self._snapshot_text(pt)), 5),
                         "child never printed its initial prompt")
        time.sleep(0.5)

        h = _FakeHandler()
        with mock.patch.object(term_vt, "INJECT_MAX_WAIT", 2.0):
            term_vt.inject(h, None, {"tty": pt.id, "text": "hello", "submit": True})

        self.assertEqual(len(h.calls), 1)
        result, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertFalse(result.get("ok"), "inject() unexpectedly succeeded against a body redraw: %r" % (result,))
        self.assertEqual(result.get("reason"), "terminal never went quiet")

    def test_small_screen_does_not_crash(self):
        """rows <= INJECT_IGNORE_BOTTOM_ROWS must fall back to using every row instead of
        ignoring the whole screen, and must not raise."""
        self.assertLessEqual(4, term_vt.INJECT_IGNORE_BOTTOM_ROWS)
        pt = self._spawn_script(QUIET_ECHO_CHILD, rows=4, cols=40)
        self.assertTrue(_wait_for(lambda: any("ready" in t for t in self._snapshot_text(pt)), 5),
                         "child never printed its initial prompt")

        h = _FakeHandler()
        term_vt.inject(h, None, {"tty": pt.id, "text": "hi", "submit": True})

        self.assertEqual(len(h.calls), 1)
        result, code = h.calls[-1]
        self.assertEqual(code, 200)
        self.assertIn("ok", result)
        self.assertTrue(result.get("ok"), "inject() failed on a tiny (rows<=IGNORE) screen: %r" % (result,))


if __name__ == "__main__":
    unittest.main()
