"""store.record_login / load_last_login: the only thing a Config login leaves behind (when, outcome)."""
import json
import os
import tempfile
import unittest
from unittest import mock

from aitracker import config, store


class LastLogin(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "last_login.json")
        p = mock.patch.object(config, "LAST_LOGIN_FILE", self.path, create=True)
        p.start()
        self.addCleanup(p.stop)

    def test_record_and_load_roundtrip(self):
        self.assertIsNone(store.load_last_login())
        self.assertTrue(store.record_login("ok", now=100))
        self.assertEqual(store.load_last_login(), {"at": 100, "ok_at": 100, "outcome": "ok", "label": "logged in"})
        self.assertTrue(store.record_login("closed", now=200))
        self.assertEqual(store.load_last_login(),
                         {"at": 200, "ok_at": 100, "outcome": "closed", "label": "login cancelled"})
        with open(self.path) as fh:
            self.assertEqual(set(json.load(fh)), {"at", "ok_at", "outcome"})    # no method, nothing else

    def test_unknown_outcome_not_written(self):
        self.assertFalse(store.record_login("weird"))
        self.assertFalse(store.record_login(True))
        self.assertFalse(os.path.exists(self.path))

    def test_bad_shape_loads_none(self):
        for bad in ("[]", '{"at": "x", "outcome": "ok"}', '{"at": 1, "outcome": "nope"}', "not json",
                    '{"at": 1, "outcome": "ok", "ok_at": "z"}'):
            with open(self.path, "w") as fh:
                fh.write(bad)
            self.assertIsNone(store.load_last_login(), bad)


if __name__ == "__main__":
    unittest.main()
