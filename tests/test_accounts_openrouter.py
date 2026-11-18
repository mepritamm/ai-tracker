"""accounts: OpenRouter /key fetch. The network is a fake opener (accounts._acct_open); no socket is ever opened."""
import io
import json
import os
import ssl
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from aitracker import accounts, config

KEY = "sk-or-v1-SENTINELKEY0123456789"
DOCS = {"data": {"label": "SENT-label", "usage": 12.5, "usage_daily": 0.5, "usage_weekly": 3, "usage_monthly": 7.25,
                 "limit": 50, "limit_remaining": 37.5, "limit_reset": "monthly", "is_free_tier": False}}


class Resp:
    def __init__(self, data):
        self.data, self.closed = data, False

    def read(self, n=-1):
        return self.data if n < 0 else self.data[:n]

    def close(self):
        self.closed = True


class FakeOpener:
    def __init__(self, script):
        self.script, self.reqs = script, []

    def open(self, req, timeout=None):
        self.reqs.append((req, timeout))
        x = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(x, BaseException):
            raise x
        return Resp(json.dumps(x).encode() if not isinstance(x, bytes) else x)


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.cfg = os.path.join(d, "config.json")
        with open(self.cfg, "w") as fh:
            json.dump({"OPENROUTER_API_KEY": KEY}, fh)
        self.now = [1000.0]
        for p in (mock.patch.object(config, "CONFIG_FILE", self.cfg),
                  mock.patch.object(accounts, "_acct_now", lambda: self.now[0]),
                  mock.patch.object(accounts, "openrouter_configured", return_value=False)):
            p.start()
            self.addCleanup(p.stop)
        accounts.usage_invalidate("openrouter")
        self.addCleanup(accounts.usage_invalidate, "openrouter")

    def opener(self, *script):
        o = FakeOpener(list(script))
        p = mock.patch.object(accounts, "_acct_open", return_value=o)
        p.start()
        self.addCleanup(p.stop)
        return o

    def get(self, fresh=False):
        accounts.openrouter_usage(fresh)
        if accounts._OR._th:
            accounts._OR._th.join(5)
        return accounts.openrouter_usage(False)

    def produce(self):
        return accounts._acct_or_producer()


class FetchTests(Base):
    def test_request_shape_and_docs_parse(self):
        o = self.opener(DOCS)
        body, ok, _ = self.produce()
        req, timeout = o.reqs[0]
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/key")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(req.get_header("User-agent"), "ai-tracker")
        self.assertEqual(timeout, 10)
        self.assertTrue(ok)
        self.assertEqual([(r["label"], r["text"]) for r in body["rows"]],
                         [("Today (UTC)", "$0.50"), ("This week (UTC, from Monday)", "$3.00"),
                          ("This month (UTC)", "$7.25"), ("All time", "$12.50")])
        self.assertEqual((body["limit_text"], body["remaining_text"], body["limit_reset"], body["free_tier"]),
                         ("Limit $50.00", "Remaining $37.50", "monthly", False))

    def test_label_and_key_never_in_body(self):
        self.opener(DOCS)
        self.assertNotIn("SENT-label", json.dumps(self.produce()[0]))
        self.assertNotIn(KEY, json.dumps(self.get()))

    def test_bad_numbers_null_limit_and_non_dict(self):
        self.opener({"data": {"usage": "oops", "usage_daily": True, "limit": None, "limit_remaining": "x",
                              "limit_reset": "Bad Value!", "is_free_tier": "yes"}})
        b = self.produce()[0]
        self.assertEqual([r["text"] for r in b["rows"]], ["—", "—"])
        self.assertEqual((b["limit_text"], b["remaining_text"], b["limit_reset"], b["free_tier"]),
                         ("No limit on this key", "", None, None))
        for junk in ({"data": [1]}, {"data": "x"}, [1], {}):
            with self.subTest(junk=junk):
                self.opener(junk)
                body, ok, _ = self.produce()
                self.assertEqual((body["state"], body["error"], ok), ("error", "unrecognised OpenRouter response", False))

    def test_rejected_401_is_held_until_invalidate(self):
        err = urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"x"))
        o = self.opener(err)
        self.assertEqual(self.get()["state"], "rejected")
        self.now[0] += 1000
        self.assertEqual(self.get(fresh=True)["state"], "rejected")
        self.assertEqual(len(o.reqs), 1)
        accounts.usage_invalidate("openrouter")
        self.get()
        self.assertEqual(len(o.reqs), 2)

    def test_http_error_closed_and_backoff_then_reset(self):
        closed = []
        err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b"x"))
        err.close = lambda: closed.append(1)
        o = self.opener(err, err, err, DOCS)
        self.get()
        self.assertEqual(accounts._ACCT_STATE["or_n"], 1)
        self.assertTrue(closed)
        self.now[0] += 31                           # hold is 30: due
        self.get()
        self.now[0] += 61                           # n=2 -> hold 60: due
        self.get()
        self.assertEqual((len(o.reqs), accounts._ACCT_STATE["or_n"]), (3, 3))
        self.now[0] += 31                           # inside n=3's 120 s hold, even with fresh
        self.get(fresh=True)
        self.assertEqual(len(o.reqs), 3)
        self.now[0] += 100
        b = self.get()
        self.assertEqual((b["state"], accounts._ACCT_STATE["or_n"]), ("ok", 0))

    def test_backoff_caps_at_900(self):
        accounts._ACCT_STATE["or_n"] = 20
        self.opener(urllib.error.URLError("x"))
        body, ok, hold = self.produce()
        self.assertEqual((hold, body["retry_in"], ok), (900.0, 900, False))

    def test_real_opener_has_no_redirects(self):
        op = accounts._acct_open()
        self.assertTrue(any(isinstance(h, accounts._AcctNoRedirect) for h in op.handlers))
        self.assertFalse(any(type(h) is urllib.request.HTTPRedirectHandler for h in op.handlers))
        h = accounts._AcctNoRedirect()
        req = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer x"})
        self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/"))
        # and over real loopback sockets: a 302 raises, and the target never sees the Authorization header
        import http.server
        import threading
        seen = []

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        tgt = http.server.HTTPServer(("127.0.0.1", 0), Target)

        class Redir(Target):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/" % tgt.server_address[1])
                self.end_headers()
        src = http.server.HTTPServer(("127.0.0.1", 0), Redir)
        for s in (tgt, src):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)
        op = urllib.request.build_opener(accounts._AcctNoRedirect, urllib.request.ProxyHandler({}))
        r2 = urllib.request.Request("http://127.0.0.1:%d/" % src.server_address[1], headers={"Authorization": "Bearer x"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            op.open(r2, timeout=5)
        cm.exception.close()
        self.assertEqual((cm.exception.code, seen), (302, []))

    def test_oversize_and_tls_and_fixed_errors(self):
        self.opener(b"x" * 70000)
        self.assertEqual(self.produce()[0]["error"], "OpenRouter response too large")
        self.opener(urllib.error.URLError(ssl.SSLCertVerificationError("SECRET-detail")))
        self.assertEqual(self.produce()[0]["error"], "TLS certificate check failed — this Python has no CA bundle")
        self.opener(ssl.SSLCertVerificationError("SECRET-detail"))
        self.assertEqual(self.produce()[0]["error"], "TLS certificate check failed — this Python has no CA bundle")
        self.opener(TimeoutError("SECRET-detail " + KEY))
        body = self.produce()[0]
        self.assertEqual(body["error"], "couldn't reach openrouter.ai")
        self.assertNotIn(KEY, json.dumps(body))
        self.assertNotIn("SECRET", json.dumps(body))

    def test_not_set_and_peek_make_no_opener_call(self):
        o = self.opener(DOCS)
        peek = accounts.openrouter_peek()
        self.assertEqual((peek["key_set"], peek["file"]), (True, self.cfg))
        self.assertNotIn(KEY, json.dumps(peek))
        self.assertEqual(o.reqs, [])
        with open(self.cfg, "w") as fh:
            json.dump({}, fh)
        body = accounts.openrouter_usage()
        self.assertEqual((body["state"], body["key_set"]), ("not_set", False))
        self.assertEqual(o.reqs, [])
        self.assertFalse(accounts.openrouter_peek()["key_set"])

    def test_invalid_stored_key_counts_as_not_set(self):
        with open(self.cfg, "w") as fh:
            json.dump({"OPENROUTER_API_KEY": "short key\r\nX: y"}, fh)
        self.assertEqual(accounts._acct_or_key(), "")


if __name__ == "__main__":
    unittest.main()
