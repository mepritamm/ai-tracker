"""Regression tests for the control-room detail-view "relative age beside the
timeline clock" pass (ext_cr_detail.js / ext_cr_detail.css / app.js /
ext_cr_board.js).

TASK 1 -- every CONVERSATION > TIMELINE entry's left gutter used to show only
the absolute clock (`fmtClock(e.t)`, "15:15"). It now also shows the SAME
relative wording the Narration header already uses -- `ago()`, app.js's own
global -- as "(18m ago)" underneath it: `entryTsHtml(t, nowMs, extraClass)`
is the one new helper every one of entryHtml()'s six render branches now
calls, replacing six copies of `fmtClock(e.t)` inline. `e.t` is epoch
MILLISECONDS (parseT()/Date.parse); ago() wants SECONDS, so the divide-by-
1000-once-not-twice unit conversion is exactly what
test_entry_ts_html_pins_exact_strings_across_magnitudes below pins.

TASK 2 -- timelineEntryModalPayload() (the pop-out dialog's "when" field)
used to re-derive its own age from `Date.now()` -- the CLIENT clock, which
this repo's conventions forbid (liveness/ages are server-stamped). It now
takes a `nowMs` argument (openTimelineEntry passes `ui.nowMs`, the same
server-stamped `state.now` renderTimeline() stashes on `ui` every poll) and
never calls Date.now() at all.

TASK 3 -- ext_cr_board.js used to carry a SECOND, forked `ago()` (same
60s/3600s/86400s thresholds, a shorter "just now"/"Xm"/"Xh"/"Xd" spelling for
tile/rail rows). app.js's global ago() now takes that as a `short` argument
instead, and the board calls `ago(seconds, true)` -- one function, one set of
thresholds, unchanged rendered output on the rail.

Idiom: same "brace-match the real function text out of the assembled page
bundle, run it under Node with honest stubs" technique as
tests/test_cr_detail_agents_pill_and_markdown.py / tests/test_cr_rail_toggle.py
-- never a hand-retyped paraphrase of the shipped source.
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
    matches = list(re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL))
    if not matches:
        raise AssertionError("No <script> tag found in assembled page")
    return matches[-1].group(1)


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the
    real bundle. Raises loudly (never returns a guess) if the shape has
    moved, so this test fails honestly instead of silently exercising stale
    text."""
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
    marker = "===TIMELINE_AGE_JSON_START==="
    idx = stdout.find(marker)
    if idx < 0:
        raise ValueError("marker not found in node output:\n" + stdout)
    return json.loads(stdout[idx + len(marker):].strip())


# A fixed epoch, deliberately nowhere near the real wall clock at test-run
# time -- any code path that fell back to Date.now() would produce an age
# wildly different from what's pinned below, so a passing test IS the proof
# the server-stamped `nowMs` argument was actually used.
T0_MS = 1_700_000_000_000


def _driver_js(bundle, calls):
    esc_src = _extract_function(bundle, "esc")
    fmt_clock_src = _extract_function(bundle, "fmtClock")
    ago_src = _extract_function(bundle, "ago")
    entry_ts_html_src = _extract_function(bundle, "entryTsHtml")
    modal_payload_src = _extract_function(bundle, "timelineEntryModalPayload")
    return r"""
%s
%s
%s
%s
%s
var OUT = {};
%s
console.log("===TIMELINE_AGE_JSON_START===");
console.log(JSON.stringify(OUT));
""" % (esc_src, fmt_clock_src, ago_src, entry_ts_html_src, modal_payload_src, calls)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestEntryTsHtmlRelativeAge(unittest.TestCase):
    """Task 1: entryTsHtml(t, nowMs, extraClass) -- the one helper every
    entryHtml() branch now calls for its timestamp span."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def _render(self, t, now_ms, extra=None):
        calls = 'OUT["r"] = entryTsHtml(%s, %s, %s);' % (
            "null" if t is None else t,
            "null" if now_ms is None else now_ms,
            "null" if extra is None else json.dumps(extra),
        )
        js = _driver_js(self.bundle, calls)
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("node harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (rc, out, err))
        return _extract_json(out)["r"]

    def test_pins_exact_strings_across_magnitudes(self):
        """"the days seconds minutes" -- the user explicitly asked for
        coverage past a single magnitude. Each case pins the EXACT expected
        string, including the parenthesised wording ago() already produces
        for the Narration header ("Xs ago"/"Xm ago"/"Xh ago"/"Xd ago"), so a
        units error (e.g. dividing e.t by 1000 twice) fails loudly rather
        than merely "looking plausible"."""
        cases = [
            (45 * 1000, "(45s ago)"),           # seconds
            (18 * 60 * 1000, "(18m ago)"),      # minutes
            (3 * 3600 * 1000, "(3h ago)"),       # hours
            (2 * 86400 * 1000, "(2d ago)"),      # days
        ]
        for delta_ms, expected_age in cases:
            t = T0_MS
            now_ms = T0_MS + delta_ms
            html = self._render(t, now_ms)
            self.assertIn(expected_age, html, "delta_ms=%d -> %r" % (delta_ms, html))
            # The clock stays the primary read -- both must be present, not
            # one instead of the other.
            self.assertIn('class="crd-entry-age"', html)

    def test_missing_or_zero_t_renders_no_age(self):
        """A missing/zero e.t must render just the clock, never a nonsense
        age like "(56y ago)" (what a naive `t || 0` age calc would produce
        against a real nowMs)."""
        for t in (None, 0):
            html = self._render(t, T0_MS + 1000)
            self.assertNotIn("ago", html, "t=%r produced an age: %r" % (t, html))
            self.assertNotIn("crd-entry-age", html)

    def test_missing_now_ms_renders_no_age(self):
        """Before nowMs is threaded down (e.g. a render that races the first
        poll), entryTsHtml must degrade to just the clock, not throw or
        fabricate an age from nothing."""
        html = self._render(T0_MS, None)
        self.assertNotIn("ago", html)

    def test_age_follows_the_passed_now_ms_not_the_real_wall_clock(self):
        """THE LOAD-BEARING ASSERTION for Task 2's server-clock-discipline
        rule, exercised here on the render helper too: T0_MS/now_ms are both
        fixed points nowhere near the actual current time this test runs at.
        If entryTsHtml ever fell back to Date.now() this would render some
        multi-decade-old age instead of the pinned "(18m ago)"."""
        html = self._render(T0_MS, T0_MS + 18 * 60 * 1000)
        self.assertIn("(18m ago)", html)
        self.assertNotIn("y ago", html)  # no multi-year drift from a real-clock fallback

    def test_source_never_calls_date_now(self):
        src = _extract_function(self.bundle, "entryTsHtml")
        self.assertNotIn("Date.now()", src)


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestTimelineEntryModalPayloadUsesServerClock(unittest.TestCase):
    """Task 2: the pop-out dialog's "when" field must derive from the
    server-stamped nowMs argument, never Date.now()."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def test_source_never_calls_date_now(self):
        src = _extract_function(self.bundle, "timelineEntryModalPayload")
        self.assertNotIn("Date.now()", src,
                          "timelineEntryModalPayload() still re-derives its age from the "
                          "CLIENT clock instead of the threaded server nowMs")

    def test_when_follows_passed_now_ms(self):
        calls = (
            'OUT["r"] = timelineEntryModalPayload('
            '{kind:"prompt", t:%d, text:"hi"}, %d).when;'
        ) % (T0_MS, T0_MS + 3 * 3600 * 1000)
        js = _driver_js(self.bundle, calls)
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("node harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (rc, out, err))
        self.assertEqual(_extract_json(out)["r"], "3h ago")


@unittest.skipUnless(_HAS_NODE, "node not available")
class TestBoardAgoReusesTheSharedHelper(unittest.TestCase):
    """Task 3: ext_cr_board.js must not carry its own second `ago()` -- and
    the shared app.js one must serve both spellings without the thresholds
    drifting apart."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = _extract_script_content(_read_page())

    def test_board_file_defines_no_local_ago(self):
        board_src = None
        with open(os.path.join(_ROOT, "aitracker", "web", "ext_cr_board.js"), encoding="utf-8") as fh:
            board_src = fh.read()
        self.assertNotRegex(board_src, r'function\s+ago\s*\(',
                             "ext_cr_board.js still defines its own ago() -- a forked "
                             "implementation of the app.js global")
        self.assertIn("ago(now - (s.mtime || 0), true)", board_src)

    def test_short_form_matches_long_form_thresholds(self):
        """The board's compact spelling must land on the SAME boundary as the
        long form -- proving one function serves both rather than two
        thresholds that could silently drift."""
        cases = [
            (45, "45s ago", "just now"),
            (18 * 60, "18m ago", "18m"),
            (3 * 3600, "3h ago", "3h"),
            (2 * 86400, "2d ago", "2d"),
        ]
        calls = []
        for i, (sec, _, _) in enumerate(cases):
            calls.append('OUT["long_%d"] = ago(%d);' % (i, sec))
            calls.append('OUT["short_%d"] = ago(%d, true);' % (i, sec))
        js = _driver_js(self.bundle, "\n".join(calls))
        rc, out, err = _run_node(js)
        if rc != 0:
            raise AssertionError("node harness failed (exit %d)\n--- stdout ---\n%s\n--- stderr ---\n%s" % (rc, out, err))
        result = _extract_json(out)
        for i, (_, expected_long, expected_short) in enumerate(cases):
            self.assertEqual(result["long_%d" % i], expected_long)
            self.assertEqual(result["short_%d" % i], expected_short)


if __name__ == "__main__":
    unittest.main()
