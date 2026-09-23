"""Regression test for the title-local-only nudge (client half): a small
dismissible note in the session detail header, shown when `meta.title_local_only`
is true (a tracker-side rename never reached the tool's own session name --
either no Claude CLI was attached at rename time, or the tool has no rename
channel at all, e.g. Auggie). Built once per bundle:

- Control Room: aitracker/web/ext_cr_detail.js (`paintTitleNote`, called from
  `renderHeader`), styled in aitracker/web/ext_cr_detail.css.
- Classic: aitracker/web/app.js (`paintTitleNote`, called from `render(d)`),
  styled in aitracker/web/app.css, with the note's container declared in
  aitracker/web/index.html (`#titlenote`).

Both share the same localStorage key prefix ("cr.titleNote.") keyed by session id
+ current title, so dismissing the note in one view dismisses it in the other,
and a NEW rename (a new title) shows it again.

Server owns the policy (meta.title_local_only / meta.title_claude); this test
only asserts the client reads and renders those fields, never re-derives them.

Same "brace-match the exact function out of the real file" technique
test_model_update_nudge.py uses: read straight off the real shipped source
(never a hand-retyped paraphrase), and also confirm the strings survive into
the fully assembled page (aitracker/page.py's build_page()), so an upstream
concatenation break would fail this test too.
"""
import os
import re
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
_WEB = os.path.join(_ROOT, "aitracker", "web")

sys.path.insert(0, _ROOT)


def _read(name):
    with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
        return fh.read()


def _extract_function(source, name):
    """Brace-matches the exact `function NAME(...) { ... }` text out of the real
    source. Raises loudly (never returns a guess) if the shape has moved, so this
    test fails honestly instead of silently exercising stale text."""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{', source)
    if not m:
        raise AssertionError("function %s() not found" % name)
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


class TestTitleNoteControlRoom(unittest.TestCase):
    """Ground-truth checks against ext_cr_detail.js's own source text."""

    def setUp(self):
        self.detail_js = _read("ext_cr_detail.js")

    def test_paint_function_reads_the_server_owned_fields(self):
        fn = _extract_function(self.detail_js, "paintTitleNote")
        self.assertIn("title_local_only", fn)
        self.assertIn("title_claude", fn)
        # dismiss control
        self.assertIn("aria-label", fn)
        self.assertIn("Dismiss", fn)
        # localStorage read/write both guarded -- can throw in private mode etc.
        self.assertIn("try {", fn)
        self.assertIn("localStorage", fn)

    def test_dismiss_key_uses_shared_prefix(self):
        fn = _extract_function(self.detail_js, "titleNoteKey")
        self.assertIn("cr.titleNote.", fn)

    def test_render_header_calls_paint_title_note(self):
        render_header_fn = _extract_function(self.detail_js, "renderHeader")
        self.assertIn("paintTitleNote(", render_header_fn)

    def test_skeleton_declares_the_note_container(self):
        self.assertIn("crd-titlenote", self.detail_js)


class TestTitleNoteClassic(unittest.TestCase):
    """Ground-truth checks against app.js's own source text."""

    def setUp(self):
        self.app_js = _read("app.js")

    def test_paint_function_reads_the_server_owned_fields(self):
        fn = _extract_function(self.app_js, "paintTitleNote")
        self.assertIn("title_local_only", fn)
        self.assertIn("title_claude", fn)
        self.assertIn("aria-label", fn)
        self.assertIn("Dismiss", fn)
        self.assertIn("try{", fn)
        self.assertIn("localStorage", fn)

    def test_dismiss_key_uses_shared_prefix(self):
        self.assertIn("cr.titleNote.", self.app_js)

    def test_render_calls_paint_title_note(self):
        render_fn = _extract_function(self.app_js, "render")
        self.assertIn("paintTitleNote(", render_fn)

    def test_rename_reads_synced_flag(self):
        fn = _extract_function(self.app_js, "renameSession")
        self.assertIn("synced", fn)

    def test_index_html_declares_the_note_container(self):
        html = _read("index.html")
        self.assertIn('id=titlenote', html)


class TestControlRoomRenameSurfacesSyncedToo(unittest.TestCase):
    """ext_cr_boot.js bridges 'cr:rename' to POST /api/title -- confirms it reads
    the response body's `synced` flag rather than discarding it like before."""

    def test_cr_rename_handler_reads_synced(self):
        boot_js = _read("ext_cr_boot.js")
        m = re.search(r"on\('cr:rename'.*?\}\);\n  \}\);", boot_js, re.S)
        self.assertIsNotNone(m, "on('cr:rename', ...) handler not found")
        handler = m.group(0)
        self.assertIn("synced", handler)
        self.assertIn("r.json()", handler)


class TestAssembledPageCarriesTheFeature(unittest.TestCase):
    """Confirms none of the above got swallowed by page.py's build_page()
    concatenation (ext_*.js load order / a stray syntax error upstream)."""

    def test_build_page_contains_the_note(self):
        from aitracker import page
        html = page.build_page()
        self.assertIn("title_local_only", html)
        self.assertIn("title_claude", html)
        self.assertIn("cr.titleNote.", html)
        self.assertIn("paintTitleNote", html)
        self.assertIn('id=titlenote', html)


if __name__ == "__main__":
    unittest.main()
