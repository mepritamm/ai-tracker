#!/usr/bin/env python3
"""Runtime tunnel switch (aitracker/tunnel.py): start/stop/rotate a cloudflared quick tunnel
from an already-running server process (no `make tunnel` restart needed), TUNNEL_TTL
auto-close, live per-request credential routing (TUNNEL_USER/TUNNEL_PASS for a request that
arrived via cloudflared, TRACKER_AUTH otherwise), and the new POST /api/tunnel/ctl route.

NEVER spawns a real cloudflared: every test that exercises start()/rotate()/autostart()
points tunnel.CLOUDFLARED at a small standalone Python script (written fresh per test to a
tempdir) that mimics cloudflared's own stderr banner -- or, for the failure case, exits 1
with an error line and no URL. Every test tears down through tunnel.stop() (idempotent, safe
even when nothing is running) so no fake child or its TTL timer survives past the test.

TRACKER_AUTH is read-and-restored as a plain config.AUTH module attribute (it is read live
by the Handler on every request), same fix tests/test_cr_tunnel.py and
tests/test_integration.py's TestBasicAuth already use, so this suite is unaffected by
whatever the dev shell happens to export."""
import base64
import http.client
import json
import os
import random
import shutil
import signal
import tempfile
import threading
import time
import unittest

import aitracker.config as config
import aitracker.tunnel as tunnel
from aitracker import server as _server
from aitracker.store import _load_json, _save_json


def _fake_cloudflared(dirpath, ok=True, error_line=None, delay=0, exit_after=None, exit_code=1):
    """Write a standalone script that behaves like cloudflared's stderr output and return its
    path. ok=True -> optionally sleeps `delay` seconds first (simulating a slow-to-connect
    tunnel), then prints the banner + a fresh random *.trycloudflare.com URL -- the randomness
    is what lets a rotate test tell two starts apart. After printing, it either sleeps 60s (a
    real tunnel stays up until killed) or, when `exit_after` is given, sleeps that many seconds
    then exits `exit_code` -- mimicking cloudflared dying on its own AFTER a successful start
    (network blip, the edge dropping it, ...). ok=False -> exits 1 with `error_line` and never
    prints a URL, mimicking a real startup failure (bad network, DNS, ...)."""
    path = os.path.join(dirpath, "fake_cloudflared_%d.py" % random.randint(0, 10 ** 9))
    if ok:
        tail = ("time.sleep(60)\n" if exit_after is None
                else "time.sleep(%r)\nsys.exit(%d)\n" % (exit_after, exit_code))
        src = (
            "#!/usr/bin/env python3\n"
            "import random, sys, time\n"
            + ("time.sleep(%r)\n" % delay if delay else "")
            + "print('Your quick Tunnel has been created! Visit it at:', file=sys.stderr)\n"
            "print('https://%08x-fake.trycloudflare.com' % random.randint(0, 0xffffffff), file=sys.stderr)\n"
            "sys.stderr.flush()\n"
            + tail
        )
    else:
        src = (
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print(%r, file=sys.stderr)\n"
            "sys.stderr.flush()\n"
            "sys.exit(1)\n"
        ) % (error_line or "failed to connect: dial tcp: no such host")
    with open(path, "w") as fh:
        fh.write(src)
    os.chmod(path, 0o755)
    return path


def _get(port, path, cred=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdr = dict(headers or {})
    if cred is not None:
        hdr["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    c.request("GET", path, headers=hdr)
    r = c.getresponse()
    data = r.read()
    out_headers = dict(r.getheaders())
    c.close()
    return r.status, data, out_headers


def _post(port, path, body, cred=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    hdr = {"Content-Type": "application/json"}
    hdr.update(headers or {})
    if cred is not None:
        hdr["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()
    c.request("POST", path, body=json.dumps(body), headers=hdr)
    r = c.getresponse()
    data = r.read()
    out_headers = dict(r.getheaders())
    c.close()
    return r.status, data, out_headers


def _poll(fn, timeout=3.0, interval=0.1):
    """Poll `fn()` until it returns a truthy value or `timeout` elapses; return the last
    value either way. The reader thread that captures a tunnel's URL (or its startup error)
    runs asynchronously, so every assertion about it has to poll rather than read once."""
    deadline = time.time() + timeout
    val = fn()
    while not val and time.time() < deadline:
        time.sleep(interval)
        val = fn()
    return val


class _TunnelCase(unittest.TestCase):
    """Shared plumbing: a temp config.json, a saved/restored tunnel.CLOUDFLARED/TUNNEL_TTL,
    and a guaranteed tunnel.stop() so no fake child (or its TTL timer) survives past the
    test -- module-level state in tunnel.py is shared across every test in this process."""

    def setUp(self):
        self._cfgfile0 = config.CONFIG_FILE
        self._cloudflared0 = tunnel.CLOUDFLARED
        self._auth0 = config.AUTH
        self._ttl0 = tunnel.TUNNEL_TTL
        config.CONFIG_FILE = tempfile.mktemp(suffix=".json")
        config.AUTH = ""
        self._tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._teardown)

    def _teardown(self):
        tunnel.stop()
        tunnel.TUNNEL_TTL = self._ttl0
        tunnel.CLOUDFLARED = self._cloudflared0
        config.AUTH = self._auth0
        try:
            os.remove(config.CONFIG_FILE)
        except OSError:
            pass
        config.CONFIG_FILE = self._cfgfile0
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _fake(self, ok=True, error_line=None, delay=0, exit_after=None, exit_code=1):
        return _fake_cloudflared(self._tmpdir, ok=ok, error_line=error_line,
                                  delay=delay, exit_after=exit_after, exit_code=exit_code)


class TestStartStop(_TunnelCase):
    def test_start_then_stop(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999)
        self.assertTrue(tunnel.status()["on"])
        proc = tunnel._proc               # captured before stop() clears the module global
        self.assertIsNotNone(proc)
        self.assertIsNone(proc.poll(), "must still be alive right after start()")

        url = _poll(lambda: tunnel.status()["url"])
        self.assertTrue(url.startswith("https://") and url.endswith(".trycloudflare.com"), url)
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertEqual(overrides.get("TUNNEL_URL"), url)
        self.assertTrue(overrides.get("TUNNEL_ON"))

        tunnel.stop()
        self.assertIsNotNone(proc.poll(), "the cloudflared child must actually be dead")
        st2 = tunnel.status()
        self.assertFalse(st2["on"])
        self.assertEqual(st2["url"], "")
        overrides2 = _load_json(config.CONFIG_FILE, {})
        self.assertFalse(overrides2.get("TUNNEL_ON"))
        self.assertEqual(overrides2.get("TUNNEL_URL"), "")

    def test_stop_keep_on_clears_url_but_leaves_intent_on(self):
        # fix A: process-exit path (atexit/_on_sigterm) must not flip TUNNEL_ON off, so a
        # `make stop; make serve` re-mints the tunnel instead of silently dropping it.
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999)
        _poll(lambda: tunnel.status()["url"])
        proc = tunnel._proc
        tunnel.stop(keep_on=True)
        self.assertIsNotNone(proc.poll(), "the cloudflared child must actually be dead")
        self.assertFalse(tunnel.status()["on"])
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertTrue(overrides.get("TUNNEL_ON"), "keep_on=True must leave TUNNEL_ON alone")
        self.assertEqual(overrides.get("TUNNEL_URL"), "")

    def test_stop_when_already_off_is_a_noop(self):
        tunnel.stop()
        st = tunnel.status()
        self.assertFalse(st["on"])

    def test_noop_stop_leaves_another_processes_state_alone(self):
        # The atexit(stop) hook fires in EVERY process that imports tunnel.py (--selfcheck, a
        # test run, make bundle). If this process never started a tunnel, its stop() must not
        # wipe the TUNNEL_ON/TUNNEL_URL that a running server persisted -- that was a live
        # defect: the gate's test processes blanked the URL of a tunnel that was still up.
        _save_json(config.CONFIG_FILE, {"TUNNEL_ON": True, "TUNNEL_URL": "https://x.trycloudflare.com"})
        tunnel.stop()
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertTrue(overrides.get("TUNNEL_ON"))
        self.assertEqual(overrides.get("TUNNEL_URL"), "https://x.trycloudflare.com")


class TestTTL(_TunnelCase):
    def test_ttl_autocloses(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.TUNNEL_TTL = 0.5
        tunnel.start(9999)
        self.assertTrue(tunnel.status()["on"])
        time.sleep(1.5)
        self.assertFalse(tunnel.status()["on"], "TTL timer must auto-stop the tunnel")
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertFalse(overrides.get("TUNNEL_ON"), "TTL expiry is a real switch-off, not a process exit")


class TestRotate(_TunnelCase):
    def test_rotate_yields_new_url(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999)
        url1 = _poll(lambda: tunnel.status()["url"])
        self.assertTrue(url1)

        tunnel.rotate(9999)
        url2 = _poll(lambda: (tunnel.status()["url"] or "") if tunnel.status()["url"] != url1 else "")
        self.assertTrue(url2, "rotate must produce a fresh URL")
        self.assertNotEqual(url1, url2)


class TestMissingBinary(_TunnelCase):
    def test_missing_cloudflared_does_not_crash(self):
        tunnel.CLOUDFLARED = "/nonexistent/cloudflared"
        tunnel.start(9999)
        st = tunnel.status()
        self.assertFalse(st["on"])
        self.assertIn("cloudflared", st["error"].lower())
        self.assertFalse(st["cloudflared"])


class TestStartupFailure(_TunnelCase):
    def test_process_exits_immediately_sets_error(self):
        tunnel.CLOUDFLARED = self._fake(ok=False, error_line="boom: dns lookup failed")
        tunnel.start(9999)
        err = _poll(lambda: tunnel.status()["error"])
        self.assertIn("boom", err)
        self.assertFalse(tunnel.status()["on"])


class TestLateReaderAfterStop(_TunnelCase):
    def test_stop_before_url_arrives_leaves_state_off(self):
        # defect 3: the reader thread's config.json write (URL arrival) must be guarded by
        # _lock and by `proc is _proc`, so a reader whose tunnel was already stop()ped before
        # its (delayed) URL line ever showed up cannot resurrect TUNNEL_ON/TUNNEL_URL.
        tunnel.CLOUDFLARED = self._fake(ok=True, delay=1.0)
        tunnel.start(9999)
        tunnel.stop()   # before the fake's 1s delay has elapsed -- no URL has been read yet
        time.sleep(2.0)
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertFalse(overrides.get("TUNNEL_ON"))
        self.assertEqual(overrides.get("TUNNEL_URL", ""), "")


class TestChildExitsAfterUrl(_TunnelCase):
    def test_child_exits_on_its_own_sets_stale_state(self):
        # defect 4: cloudflared can die on its own AFTER a successful connect (network blip,
        # the edge dropping it, ...) -- the reader must notice and clear the now-stale URL
        # (and TTL timer) while leaving TUNNEL_ON alone (user intent -> autostart retries).
        tunnel.CLOUDFLARED = self._fake(ok=True, exit_after=0.5, exit_code=1)
        tunnel.start(9999)
        self.assertTrue(_poll(lambda: not tunnel.status()["on"], timeout=5.0))
        st = tunnel.status()
        self.assertTrue(st["error"].startswith("cloudflared exited"), st["error"])
        self.assertEqual(st["url"], "")
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertEqual(overrides.get("TUNNEL_URL", ""), "")
        self.assertTrue(overrides.get("TUNNEL_ON"))
        self.assertTrue(tunnel._timer is None or not tunnel._timer.is_alive())


class TestOriginHost(_TunnelCase):
    def test_start_uses_given_host(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999, host="10.1.2.3")
        self.assertEqual(tunnel._proc.args[-1], "http://10.1.2.3:9999")

    def test_start_wildcard_host_origins_to_loopback(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999, host="0.0.0.0")
        self.assertEqual(tunnel._proc.args[-1], "http://127.0.0.1:9999")


class TestCreds(_TunnelCase):
    def test_ensure_creds_generates_when_blank(self):
        user, pw, generated = tunnel.ensure_creds()
        self.assertTrue(generated)
        self.assertTrue(user.startswith("ai-"), user)
        self.assertGreaterEqual(len(pw), 12)
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertEqual(overrides["TUNNEL_USER"], user)
        self.assertEqual(overrides["TUNNEL_PASS"], pw)
        mode = os.stat(config.CONFIG_FILE).st_mode & 0o777
        self.assertEqual(oct(mode), "0o600", "config.json must be owner-only once it holds a credential")

    def test_ensure_creds_does_not_overwrite_existing(self):
        user1, pw1, gen1 = tunnel.ensure_creds()
        self.assertTrue(gen1)
        user2, pw2, gen2 = tunnel.ensure_creds()
        self.assertFalse(gen2)
        self.assertEqual((user1, pw1), (user2, pw2))

    def test_rotate_creds_changes_both(self):
        user1, pw1, _g = tunnel.ensure_creds()
        user2, pw2 = tunnel.rotate_creds()
        self.assertNotEqual((user1, pw1), (user2, pw2))
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertEqual(overrides["TUNNEL_USER"], user2)
        self.assertEqual(overrides["TUNNEL_PASS"], pw2)


class _ServerCase(_TunnelCase):
    """Adds a real, ephemeral-port Handler server on top of _TunnelCase's tunnel plumbing --
    same idiom as tests/test_cr_tunnel.py's _TunnelServerCase."""

    def setUp(self):
        super().setUp()
        self.srv = _server.Server(("127.0.0.1", 0), _server.Handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self):
        self.srv.shutdown()
        self.srv.server_close()


class TestCtlRoute(_ServerCase):
    def test_start_generates_creds_and_get_never_leaks_them(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {"action": "start"})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertTrue(d.get("generated"))
        self.assertTrue(d["user"].startswith("ai-"))
        self.assertGreaterEqual(len(d["pass"]), 12)
        self.assertIn("share_url", d)

        st2, body2, _h2 = _get(self.port, "/api/tunnel")
        self.assertEqual(st2, 200)
        d2 = json.loads(body2)
        self.assertTrue(d2["on"])
        self.assertNotIn("user", d2)
        self.assertNotIn("pass", d2)
        self.assertNotIn("generated", d2)

    def test_unknown_action_400(self):
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {"action": "nonsense"})
        self.assertEqual(st, 400)
        self.assertIn("error", json.loads(body))

    def test_missing_action_400(self):
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {})
        self.assertEqual(st, 400)

    def test_stop_action(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        _post(self.port, "/api/tunnel/ctl", {"action": "start"})
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {"action": "stop"})
        self.assertEqual(st, 200)
        self.assertFalse(json.loads(body)["on"])

    def test_stop_when_already_off_is_a_noop(self):
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {"action": "stop"})
        self.assertEqual(st, 200)
        self.assertFalse(json.loads(body)["on"])

    def test_start_when_already_on_is_a_noop(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        st1, body1, _h = _post(self.port, "/api/tunnel/ctl", {"action": "start"})
        pid1 = json.loads(body1)["pid"]
        st2, body2, _h2 = _post(self.port, "/api/tunnel/ctl", {"action": "start"})
        self.assertEqual(st2, 200)
        self.assertEqual(json.loads(body2)["pid"], pid1, "a second start on an already-on tunnel must not respawn")

    def test_rotate_generates_creds_when_blank(self):
        # defect 6: rotate() mints creds internally (ensure_creds()), but the ctl route must
        # ALSO call it and surface the one-time user/pass/share_url, exactly like "start" does
        # -- otherwise a rotate that happens to be the first thing to ever mint creds hides
        # them from the browser forever.
        tunnel.CLOUDFLARED = self._fake(ok=True)
        st, body, _h = _post(self.port, "/api/tunnel/ctl", {"action": "rotate"})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertTrue(d.get("generated"))
        self.assertTrue(d["user"].startswith("ai-"))
        self.assertIn("share_url", d)


class TestAuthByPath(_ServerCase):
    """Handler._cred() must pick TUNNEL_USER/TUNNEL_PASS for a request that carries
    Cf-Connecting-Ip (cloudflared's own marker) and config.AUTH for everything else --
    regardless of whether a real tunnel process is running (the header is what matters, not
    tunnel.status()["on"])."""

    def test_localhost_open_when_auth_off(self):
        st, _b, _h = _get(self.port, "/api/list")
        self.assertEqual(st, 200)

    def test_tunnel_header_without_staged_creds_401s(self):
        st, _b, _h = _get(self.port, "/api/list", headers={"Cf-Connecting-Ip": "1.2.3.4"})
        self.assertEqual(st, 401, "a tunnel request must never fall back to config.AUTH's blank == open")

    def test_tunnel_header_with_correct_creds_200s(self):
        _save_json(config.CONFIG_FILE, {"TUNNEL_USER": "u", "TUNNEL_PASS": "p"})
        st, _b, _h = _get(self.port, "/api/list", cred="u:p", headers={"Cf-Connecting-Ip": "1.2.3.4"})
        self.assertEqual(st, 200)

    def test_tunnel_header_with_wrong_password_401s(self):
        _save_json(config.CONFIG_FILE, {"TUNNEL_USER": "u", "TUNNEL_PASS": "p"})
        st, _b, _h = _get(self.port, "/api/list", cred="u:wrong", headers={"Cf-Connecting-Ip": "1.2.3.4"})
        self.assertEqual(st, 401)

    def test_login_via_tunnel_sets_cookie_that_then_works(self):
        _save_json(config.CONFIG_FILE, {"TUNNEL_USER": "u", "TUNNEL_PASS": "p"})
        st, _b, headers = _post(self.port, "/login", {"user": "u", "pass": "p"},
                                 headers={"Cf-Connecting-Ip": "1.2.3.4"})
        self.assertEqual(st, 200)
        setc = headers.get("Set-Cookie")
        self.assertIsNotNone(setc)
        st2, _b2, _h2 = _get(self.port, "/api/list",
                              headers={"Cf-Connecting-Ip": "1.2.3.4", "Cookie": setc.split(";")[0]})
        self.assertEqual(st2, 200)


class TestAutostart(_TunnelCase):
    def test_autostart_true_starts_and_flags_autostarted(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        _save_json(config.CONFIG_FILE, {"TUNNEL_ON": True})
        tunnel.autostart(9999)
        self.assertTrue(tunnel.status()["on"])
        self.assertTrue(tunnel.status()["autostarted"])

    def test_autostart_false_does_nothing(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        _save_json(config.CONFIG_FILE, {"TUNNEL_ON": False})
        tunnel.autostart(9999)
        self.assertFalse(tunnel.status()["on"])

    def test_autostart_absent_key_does_nothing(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.autostart(9999)
        self.assertFalse(tunnel.status()["on"])


class TestSigterm(_TunnelCase):
    def test_sigterm_stops_tunnel_then_exits(self):
        # defect 1: `make stop` sends a plain SIGTERM, and Python runs no atexit handlers on
        # an unhandled signal -- server._on_sigterm must itself stop() the tunnel (killing the
        # cloudflared child) before turning the signal into a normal SystemExit.
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999)
        self.assertTrue(_poll(lambda: tunnel.status()["on"]))
        proc = tunnel._proc
        with self.assertRaises(SystemExit):
            _server._on_sigterm(signal.SIGTERM, None)
        self.assertIsNotNone(proc.poll(), "the cloudflared child must actually be dead")
        self.assertFalse(tunnel.status()["on"])
        # fix A: _on_sigterm is the process itself exiting, not the user switching the
        # tunnel off -- TUNNEL_ON must survive so the next `make serve` re-mints it.
        overrides = _load_json(config.CONFIG_FILE, {})
        self.assertTrue(overrides.get("TUNNEL_ON"), "_on_sigterm must not clear TUNNEL_ON")


class TestConfigWriteFailure(_TunnelCase):
    """fix B: a config.json write failure (disk full, permissions, ...) must never leave the
    cloudflared child running unkilled, and must surface as status()["error"] rather than a
    silently-half-started tunnel."""

    def _break_save_cfg(self):
        real = tunnel._save_cfg

        def _boom(overrides):
            raise OSError("disk full")
        tunnel._save_cfg = _boom
        self.addCleanup(lambda: setattr(tunnel, "_save_cfg", real))

    def test_start_write_failure_kills_child_and_sets_error(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        self._break_save_cfg()
        tunnel.start(9999)
        st = tunnel.status()
        self.assertFalse(st["on"])
        self.assertIn("config write failed", st["error"])
        self.assertIsNone(tunnel._proc, "no child must be left registered after a write failure")

    def test_stop_write_failure_still_kills_child(self):
        tunnel.CLOUDFLARED = self._fake(ok=True)
        tunnel.start(9999)          # succeeds normally -- _save_cfg not yet broken
        _poll(lambda: tunnel.status()["url"])
        proc = tunnel._proc
        self._break_save_cfg()
        tunnel.stop()
        self.assertIsNotNone(proc.poll(), "the cloudflared child must actually be dead")
        self.assertIsNone(tunnel._proc)
        self.assertIn("config write failed", tunnel.status()["error"])


if __name__ == "__main__":
    unittest.main()
