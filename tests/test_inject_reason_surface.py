"""Test that POST /api/term/inject error reason fallback is present at all call sites."""

import os
import re
import unittest


class TestInjectReasonSurface(unittest.TestCase):
    """Verify .reason fallback is present wherever we read inject error text."""

    def _read_file(self, name):
        """Read a web/*.js file relative to the tests/ directory."""
        base = os.path.dirname(__file__)
        path = os.path.join(base, "..", "aitracker", "web", name)
        with open(path, 'r') as f:
            return f.read()

    def test_ext_cr_term_has_reason_fallback(self):
        """ext_cr_term.js _injectSlash must use (error || reason)."""
        content = self._read_file("ext_cr_term.js")
        # Find the _injectSlash function and verify reason fallback is there
        match = re.search(r'function _injectSlash\(.*?\n.*?var reason = \(res\.j && \((.*?)\)\)', content, re.DOTALL)
        self.assertIsNotNone(match, "_injectSlash not found or reason fallback missing")
        reason_expr = match.group(1)
        self.assertIn("res.j.error", reason_expr, "res.j.error not found in reason expression")
        self.assertIn("res.j.reason", reason_expr, "res.j.reason not found in reason expression")

    def test_ext_vt_pickmodel_has_reason_fallback(self):
        """ext_vt.js _pickModel must use (error || reason)."""
        content = self._read_file("ext_vt.js")
        # Find the _pickModel function context (look for model-switch)
        match = re.search(r'text: "/model " \+ name.*?var reason = \(res\.j && \((.*?)\)\)', content, re.DOTALL)
        self.assertIsNotNone(match, "_pickModel or reason fallback not found")
        reason_expr = match.group(1)
        self.assertIn("res.j.error", reason_expr, "res.j.error not found in _pickModel reason")
        self.assertIn("res.j.reason", reason_expr, "res.j.reason not found in _pickModel reason")

    def test_ext_vt_pickeffort_has_reason_fallback(self):
        """ext_vt.js _pickEffort must use (error || reason)."""
        content = self._read_file("ext_vt.js")
        # Find the _pickEffort function context (look for effort-switch)
        match = re.search(r'text: "/effort " \+ level.*?var reason = \(res\.j && \((.*?)\)\)', content, re.DOTALL)
        self.assertIsNotNone(match, "_pickEffort or reason fallback not found")
        reason_expr = match.group(1)
        self.assertIn("res.j.error", reason_expr, "res.j.error not found in _pickEffort reason")
        self.assertIn("res.j.reason", reason_expr, "res.j.reason not found in _pickEffort reason")

    def test_ext_cr_detail_has_reason_fallback(self):
        """ext_cr_detail.js _injectToTerminal must use (error || reason)."""
        content = self._read_file("ext_cr_detail.js")
        # Find the _injectToTerminal function and verify reason fallback is there
        match = re.search(r'function _injectToTerminal\(.*?\n.*?var reason = \(res\.j && \((.*?)\)\)', content, re.DOTALL)
        self.assertIsNotNone(match, "_injectToTerminal not found or reason fallback missing")
        reason_expr = match.group(1)
        self.assertIn("res.j.error", reason_expr, "res.j.error not found in reason expression")
        self.assertIn("res.j.reason", reason_expr, "res.j.reason not found in reason expression")


if __name__ == '__main__':
    unittest.main()
