"""A9: scan children run niced on posix; no prefix elsewhere; server process untouched."""
import os
import unittest
from unittest import mock

from aitracker import pending


class _R:
    returncode = 0
    stdout = b""


class NiceTest(unittest.TestCase):
    def _argv(self, fn, osname, which):
        with mock.patch.object(pending.os, "name", osname), \
             mock.patch.object(pending.shutil, "which", lambda n: which(n)), \
             mock.patch.object(pending.subprocess, "run", return_value=_R()) as run:
            fn()
        return run.call_args[0][0]

    def test_posix_prefix(self):
        w = lambda n: "/usr/bin/" + n
        self.assertEqual(self._argv(lambda: pending._git("/", "status"), "posix", w)[:3], ["nice", "-n", "10"])
        a = self._argv(lambda: pending._gh("/", "pr"), "posix", w)
        self.assertEqual(a[:3], ["nice", "-n", "10"])
        self.assertEqual(a[3], "/usr/bin/gh")

    def test_no_prefix_on_nt_or_missing_nice(self):
        w = lambda n: "/x/" + n
        self.assertEqual(self._argv(lambda: pending._git("/", "status"), "nt", w)[0], "git")
        a = self._argv(lambda: pending._gh("/", "pr"), "posix", lambda n: None if n == "nice" else "/x/gh")
        self.assertEqual(a[0], "/x/gh")

    def test_server_not_reniced(self):
        before = os.nice(0) if hasattr(os, "nice") else 0
        self._argv(lambda: pending._git("/", "status"), "posix", lambda n: "/usr/bin/" + n)
        self.assertEqual(os.nice(0) if hasattr(os, "nice") else 0, before)


if __name__ == "__main__":
    unittest.main()
