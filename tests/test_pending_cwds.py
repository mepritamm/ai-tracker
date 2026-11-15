import json, os, tempfile, unittest
from unittest import mock
from aitracker import config, registry


class _NoCwds:
    prefix = "x:"
    def available(self): return True
    def list(self): return [{"cwd": "/fallback/a"}, {"cwd": ""}, {"id": "n"}]


class CwdsSeam(unittest.TestCase):
    def test_all_first_cwds_beyond_200(self):
        with tempfile.TemporaryDirectory() as d:
            pd = os.path.join(d, "-proj")
            os.makedirs(pd)
            for i in range(250):
                with open(os.path.join(pd, "s%03d.jsonl" % i), "w") as f:
                    f.write(json.dumps({"type": "mode", "sessionId": "s"}) + "\n")
                    f.write(json.dumps({"type": "user", "cwd": "/w/%d" % i, "sessionId": "s%d" % i,
                                        "message": {"content": "hi"}}) + "\n")
            with mock.patch.object(config, "PROJECTS", d):
                got = registry.ClaudeProvider().cwds()
        self.assertEqual(got, {"/w/%d" % i for i in range(250)})

    def test_fallback_to_list(self):
        with mock.patch.object(registry, "PROVIDERS", [_NoCwds()]):
            self.assertEqual(registry.all_cwds(), {"/fallback/a"})


if __name__ == "__main__":
    unittest.main()
