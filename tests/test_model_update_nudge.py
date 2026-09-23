"""Regression test for the model-update nudge (client half): a shared banner —
"<label> is available -- this session is on <current_label>." with Switch/Keep
buttons — built once in ext_cr_dialogs.js (`modelUpdateNotice`) and reused by
both the model ladder picker (`renderLadderPicker`'s own `payload.update`) and
ext_vt.js's inline model dropdown (`ContextBar._syncModelUpdateNotice`), instead
of two forked copies. Keep POSTs `/api/model-keep {id, model}`; Switch defers to
each caller's own onPick/`_pickModel` so the actual `/model <id>` injection stays
where it already lived.

Owned files for this feature (client half): aitracker/web/ext_cr_dialogs.js,
aitracker/web/ext_cr_dialogs.css, aitracker/web/ext_cr_detail.js,
aitracker/web/ext_cr_term.js, aitracker/web/ext_cr_term.css, aitracker/web/ext_vt.js,
and this test file. (The server half -- meta.model/model_label/model_update and
POST /api/model-keep -- is a parallel change to aitracker/providers/*.py and
aitracker/server.py, not asserted here.)

Same "brace-match the exact function out of the real file" technique
test_cr_dialogs_poll_broadcast_seam.py already uses: read straight off the real
shipped source (never a hand-retyped paraphrase), and also confirm the same
strings survive into the fully assembled page (aitracker/page.py's build_page()),
so an upstream concatenation break would fail this test too.
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


class TestModelUpdateNoticeSource(unittest.TestCase):
    """Ground-truth checks against ext_cr_dialogs.js's own source text."""

    def setUp(self):
        self.dialogs_js = _read("ext_cr_dialogs.js")

    def test_notice_builder_exists_and_posts_model_keep(self):
        notice_fn = _extract_function(self.dialogs_js, "modelUpdateNotice")
        self.assertIn("update.id", notice_fn)
        self.assertIn("Switch to ", notice_fn)
        self.assertIn("Keep ", notice_fn)

        keep_fn = _extract_function(self.dialogs_js, "postModelKeep")
        self.assertIn("/api/model-keep", keep_fn)
        # Same fetch/JSON/`cb(ok, body)` shape as postConfigValue/postTunnelValue
        # above it in the same file, not a third pattern.
        self.assertIn("method: 'POST'", keep_fn)
        self.assertIn("sessionId", keep_fn)
        self.assertIn("modelId", keep_fn)

    def test_notice_builder_is_exported_for_ext_vt(self):
        # ext_vt.js's ContextBar is a second dropdown surface that predates the
        # dialog system and isn't reachable via REGISTRY/open() -- it has to reach
        # the shared builder off window.CR.dialogs instead.
        self.assertRegex(
            self.dialogs_js,
            r"modelUpdateNotice\s*:\s*modelUpdateNotice",
            "modelUpdateNotice is not exposed on window.CR.dialogs",
        )

    def test_ladder_picker_wires_the_update_payload(self):
        picker_fn = _extract_function(self.dialogs_js, "renderLadderPicker")
        self.assertIn("payload.update", picker_fn)
        self.assertIn("payload.currentLabel", picker_fn)
        self.assertIn("modelUpdateNotice(", picker_fn)


class TestModelUpdateNoticeCallers(unittest.TestCase):
    """The two picker-opening callers pass the new server-owned fields through
    unchanged (server owns the label/update policy; these files only read it)."""

    def test_detail_terminal_picker_passes_label_and_update(self):
        src = _read("ext_cr_detail.js")
        self.assertIn("meta2.model_label", src)
        self.assertIn("meta2.model_update", src)

    def test_term_toolbar_picker_passes_label_and_update(self):
        src = _read("ext_cr_term.js")
        self.assertIn("st.modelLabel", src)
        self.assertIn("st.modelUpdate", src)
        self.assertIn("meta.model_label", src)
        self.assertIn("meta.model_update", src)

    def test_vt_dropdown_reuses_the_shared_builder(self):
        src = _read("ext_vt.js")
        self.assertIn("CR.dialogs.modelUpdateNotice", src)
        self.assertIn("meta.model_update", src)


class TestAssembledPageCarriesTheFeature(unittest.TestCase):
    """Confirms none of the above got swallowed by page.py's build_page()
    concatenation (ext_*.js load order / a stray syntax error upstream)."""

    def test_build_page_contains_the_notice_and_the_keep_route(self):
        from aitracker import page
        html = page.build_page()
        self.assertIn("modelUpdateNotice", html)
        self.assertIn("/api/model-keep", html)
        self.assertIn("payload.update", html)


if __name__ == "__main__":
    unittest.main()
