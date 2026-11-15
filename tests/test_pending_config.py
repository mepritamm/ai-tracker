import os
import unittest
from unittest import mock

from aitracker import config


class IntervalParse(unittest.TestCase):
    def test_accepted(self):
        for v in ("7d", "2w", "1m", "1mo", "3m", "90d", "12m", "365d", "52w"):
            self.assertTrue(config._v_interval(v)[0], v)
        self.assertEqual(config._v_interval("off"), (True, "off"))
        self.assertEqual(config._v_interval("0"), (True, "off"))
        self.assertEqual(config._v_interval(" 3M "), (True, "3m"))

    def test_rejected(self):
        for v in ("7", "1y", "-1d", "1.5d", "13m", "400d", "", "0d", "1000d", True, 7, None):
            self.assertEqual(config._v_interval(v), (False, None), repr(v))

    def test_seconds(self):
        self.assertEqual(config.interval_seconds("90d"), 7776000)
        self.assertEqual(config.interval_seconds("3m"), 7776000)
        self.assertEqual(config.interval_seconds("3M"), 7776000)
        self.assertEqual(config.interval_seconds("1mo"), 2592000)
        self.assertEqual(config.interval_seconds("2w"), 1209600)
        for v in ("off", "0", "junk", None, True):
            self.assertIsNone(config.interval_seconds(v))


class KeysAndResolution(unittest.TestCase):
    def test_registered_live(self):
        for k in ("PENDING_INTERVAL", "PENDING_CLEAN"):
            self.assertIn(k, config.EDITABLE)
            self.assertNotIn(k, config.RESTART_REQUIRED)
            self.assertIn(k, config.VALIDATORS)
            self.assertIn(k, config._PLAIN_ATTR_KEYS)
        self.assertEqual(config.VALIDATORS["PENDING_CLEAN"]("safe"), (True, "safe"))
        self.assertFalse(config.VALIDATORS["PENDING_CLEAN"]("yes")[0])

    def test_defaults_and_precedence(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRACKER_PENDING_")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(config.resolve_pending_interval({}), "90d")
            self.assertEqual(config.resolve_pending_clean({}), "dry-run")
            os.environ["TRACKER_PENDING_INTERVAL"] = "2w"
            os.environ["TRACKER_PENDING_CLEAN"] = "safe"
            self.assertEqual(config.resolve_pending_interval({}), "2w")
            self.assertEqual(config.resolve_pending_clean({}), "safe")
            self.assertEqual(config.resolve_pending_interval({"PENDING_INTERVAL": "1m"}), "1m")
            self.assertEqual(config.resolve_pending_clean({"PENDING_CLEAN": "off"}), "off")
            os.environ["TRACKER_PENDING_INTERVAL"] = "bogus"
            os.environ["TRACKER_PENDING_CLEAN"] = "bogus"
            self.assertEqual(config.resolve_pending_interval({"PENDING_INTERVAL": "7"}), "90d")
            self.assertEqual(config.resolve_pending_clean({}), "dry-run")
            os.environ["TRACKER_PENDING_INTERVAL"] = "off"
            self.assertEqual(config.resolve_pending_interval({}), "off")

    def test_apply_overrides_live(self):
        old = (config.PENDING_INTERVAL, config.PENDING_CLEAN)
        try:
            config.apply_overrides({"PENDING_INTERVAL": "2w", "PENDING_CLEAN": "safe"})
            self.assertEqual((config.PENDING_INTERVAL, config.PENDING_CLEAN), ("2w", "safe"))
            self.assertFalse(config.snapshot({})["PENDING_INTERVAL"]["restart"])
        finally:
            config.PENDING_INTERVAL, config.PENDING_CLEAN = old

    def test_paths(self):
        self.assertTrue(config.PENDING_FILE.endswith("pending.json"))
        self.assertTrue(config.PENDING_LOG.endswith("pending.log"))
        self.assertEqual(config.PENDING_LOCK, os.path.join(os.path.expanduser("~"), ".ai-tracker-pending.lock"))
        self.assertEqual(config.SCRATCH_ROOT, "/tmp/claude-%d" % os.getuid())


if __name__ == "__main__":
    unittest.main()
