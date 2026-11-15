import unittest

from aitracker import config, term_gate
from aitracker.util import is_loopback_host


class _H:
    def __init__(self, h):
        self._h = h

    def get(self, k, d=""):
        return self._h.get(k, d)


class _Handler:
    def __init__(self, headers):
        self.headers = _H(headers)
        self.calls = []

    def _json(self, obj, code=200):
        self.calls.append((obj, code))


class TestIsLoopbackHost(unittest.TestCase):
    def test_table(self):
        yes = ["localhost", "LocalHost:8790", "127.0.0.1", "127.0.0.1:8790", "127.5.6.7:1",
               "[::1]", "[::1]:8790", "tabc123.localhost:8790"]
        no = ["", None, "evil.example", "evil.example:8790", "localhost.evil.example",
              "127.0.0.1.evil.example", "10.0.0.1:8790", "0.0.0.0", "::1", "[::1", "localhost:abc",
              "[::1]x"]
        for h in yes:
            self.assertTrue(is_loopback_host(h), h)
        for h in no:
            self.assertFalse(is_loopback_host(h), h)


class TestOriginMatchesHost(unittest.TestCase):
    def test_table(self):
        from aitracker.util import origin_matches_host
        ok = [{}, {"Host": "h:1"}, {"Origin": "http://h:1", "Host": "h:1"}, {"Origin": "https://h:1", "Host": "h:1"}]
        bad = [{"Origin": "http://evil.example", "Host": "h:1"}, {"Origin": "null", "Host": "h:1"},
               {"Origin": "http://h:2", "Host": "h:1"}, {"Origin": "http://h:1"}]
        for h in ok:
            self.assertTrue(origin_matches_host(_H(h)), h)
        for h in bad:
            self.assertFalse(origin_matches_host(_H(h)), h)
            self.assertFalse(term_gate._origin_ok(_Handler(h)), h)


class TestGuardHost(unittest.TestCase):
    def setUp(self):
        self._s = (config.TERMINAL, config.AUTH, config.BIND_HOST)
        config.TERMINAL, config.AUTH, config.BIND_HOST = True, "", "127.0.0.1"

    def tearDown(self):
        config.TERMINAL, config.AUTH, config.BIND_HOST = self._s

    def test_rebinding_refused(self):
        h = _Handler({"Host": "evil.example"})
        self.assertFalse(term_gate.guard(h))
        self.assertEqual(h.calls[0][1], 403)

    def test_loopback_hosts_allowed(self):
        for host in ("localhost:8790", "127.0.0.1:8790"):
            h = _Handler({"Host": host})
            self.assertTrue(term_gate.guard(h), host)
            self.assertEqual(h.calls, [])

    def test_with_login_other_host_allowed(self):
        config.AUTH = "u:p"
        h = _Handler({"Host": "abc.trycloudflare.com"})
        self.assertTrue(term_gate.guard(h))


if __name__ == "__main__":
    unittest.main()
