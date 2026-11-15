import importlib, os, sys, unittest
from unittest import mock


class WindowsShims(unittest.TestCase):
    def test_store_imports_without_fcntl_and_locks_via_msvcrt(self):
        calls = []
        fake = mock.Mock(LK_LOCK=1, LK_UNLCK=0, locking=lambda fd, mode, n: calls.append(mode))
        saved = sys.modules.get("aitracker.store")
        try:
            with mock.patch.dict(sys.modules, {"fcntl": None, "msvcrt": fake}):
                sys.modules.pop("aitracker.store", None)
                store = importlib.import_module("aitracker.store")
                self.assertIsNone(store.fcntl)
                import tempfile
                with tempfile.TemporaryFile() as fh:
                    store._lock_fh(fh, True)
                    store._lock_fh(fh, False)
                self.assertEqual(calls, [1, 0])
        finally:
            if saved is not None:
                sys.modules["aitracker.store"] = saved
            else:
                sys.modules.pop("aitracker.store", None)

    def test_loader_skips_term_modules_on_nt(self):
        from aitracker import server
        with mock.patch.object(server.os, "name", "nt"):
            self.assertEqual(server._term_modules(), ())
        with mock.patch.object(server.os, "name", "posix"):
            self.assertEqual(server._term_modules(), ("term_launch", "term_run", "term_vt"))


if __name__ == "__main__":
    unittest.main()
