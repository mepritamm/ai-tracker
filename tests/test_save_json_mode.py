"""store._save_json keeps an existing file's exact mode (so a 0600 config.json survives every writer) and can create
the temp file at a requested mode before it holds data. A new file keeps today's umask-derived mode."""
import os
import stat
import tempfile
import unittest
from unittest import mock

from aitracker import store


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


class SaveJsonModeTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "c.json")
        old = os.umask(0o002)
        self.addCleanup(os.umask, old)

    def test_new_file_keeps_umask_mode(self):
        store._save_json(self.p, {"a": 1})
        self.assertEqual(_mode(self.p), 0o664)

    def test_existing_mode_survives_rewrite(self):
        store._save_json(self.p, {"a": 1})
        os.chmod(self.p, 0o600)
        store._save_json(self.p, {"a": 2})
        self.assertEqual(_mode(self.p), 0o600)
        self.assertEqual(store._load_json(self.p, {}), {"a": 2})

    def test_mode_arg_applies_to_temp_before_swap(self):
        store._save_json(self.p, {"a": 1})
        os.chmod(self.p, 0o644)
        seen = []
        real = os.replace

        def spy(src, dst):
            seen.append(_mode(src))
            return real(src, dst)
        with mock.patch.object(store.os, "replace", spy):
            store._save_json(self.p, {"k": "v"}, mode=0o600)
        self.assertEqual(seen, [0o600])
        self.assertEqual(_mode(self.p), 0o600)

    def test_existing_file_write_without_fchmod(self):
        store._save_json(self.p, {"a": 1})
        saved = os.fchmod
        del os.fchmod                   # Windows before 3.13 has none
        try:
            store._save_json(self.p, {"a": 2})
        finally:
            os.fchmod = saved
        self.assertEqual(store._load_json(self.p, {}), {"a": 2})
        self.assertEqual([f for f in os.listdir(self.d) if f.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
