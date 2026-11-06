"""Tests for scripts/run_tests_parallel.py's _is_benign_empty_module.

This tooling script is otherwise exempt from tests/ coverage (same exemption as
scripts/bundle.py -- see run_tests_parallel.py's own module docstring), but
_is_benign_empty_module carries real judgment worth pinning directly: the benign-empty-module
exemption must be scoped to the ONE module known to define no TestCase of its own
(tests.test_selfcheck -- its logic is exercised via tests/test_tracker.py's own import), not to
ANY module that happens to exit 5 with "NO TESTS RAN". Without that name check, a test method
accidentally renamed without its `test_` prefix in some OTHER module would also collect zero
tests and get silently waved through as benign instead of failing the gate.
"""
import importlib.util
import os
import unittest

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "run_tests_parallel.py")
_spec = importlib.util.spec_from_file_location("run_tests_parallel", _SCRIPT)
_rtp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rtp)

_NO_TESTS_RAN = (
    "\n----------------------------------------------------------------------\n"
    "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n"
)


class TestIsBenignEmptyModule(unittest.TestCase):
    def test_the_one_known_empty_module_is_benign(self):
        self.assertTrue(
            _rtp._is_benign_empty_module("tests.test_selfcheck", 5, _NO_TESTS_RAN))

    def test_a_different_module_with_the_same_exit_shape_is_not_benign(self):
        """The regression this guards: a test method renamed without its test_ prefix in any
        OTHER module collects zero tests too (same exit 5, same "NO TESTS RAN") but is a real
        bug, not a documented test-free helper module -- it must still fail the gate."""
        self.assertFalse(
            _rtp._is_benign_empty_module("tests.test_icons", 5, _NO_TESTS_RAN))

    def test_the_known_module_with_a_traceback_is_not_benign(self):
        self.assertFalse(_rtp._is_benign_empty_module(
            "tests.test_selfcheck", 1,
            "Traceback (most recent call last):\n  ...\nImportError: boom\n",
        ))

    def test_the_known_module_with_a_different_exit_code_is_not_benign(self):
        self.assertFalse(
            _rtp._is_benign_empty_module("tests.test_selfcheck", 1, _NO_TESTS_RAN))


if __name__ == "__main__":
    unittest.main()
