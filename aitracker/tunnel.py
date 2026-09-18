"""Runtime tunnel switch: mint (or kill) a Cloudflare quick tunnel from THIS already-running
server process, on demand, no restart required. `make tunnel` (see the Makefile) still works
the old way -- shell out, grep a log file -- but that path never let this Python process see
the URL or control the child. This module owns both: it spawns cloudflared itself, reads the
public URL straight off its stderr banner, and stores it in config.json's TUNNEL_URL key (see
config.py's "Tunnel management" section for why that key already existed and what changes
about it here) so the existing Tunnel tab / share_url keep working unmodified.

Auth model: a tunnel makes the dashboard reachable from the open internet, so it needs its
OWN credential -- TUNNEL_USER/TUNNEL_PASS -- independent of TRACKER_AUTH, which still governs
every direct (loopback/LAN) request exactly as before. cloudflared tags every proxied request
with Cf-Connecting-Ip/Cf-Ray (see via_tunnel()); server.py's Handler._cred() uses that to pick
which credential a given request is judged against. ensure_creds()/rotate_creds() guarantee
that credential is never blank once a tunnel is live -- an unauthenticated public dashboard is
the one outcome this whole feature must never produce.

Stdlib only: subprocess, threading, re, shutil, secrets, atexit, time, os, signal.
"""
import atexit
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time

from . import config
from .store import _load_json, _save_json

# Module attr (not a local const) so tests can repoint it at a fake executable -- shutil.which()
# resolves an absolute path directly (no PATH lookup needed) so this doubles as the "is
# cloudflared installed" probe used by status()/start().
CLOUDFLARED = "cloudflared"

TUNNEL_TTL = 12 * 3600  # auto-close after 12h -- a forgotten public tunnel is a standing risk

# cloudflared's own banner line looks like "|  https://foo-bar.trycloudflare.com  |" --
# this is deliberately loose (no anchors) since the padding/box-drawing characters around it
# aren't part of any documented contract.
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_proc = None          # the cloudflared Popen, or None when off
_started = None       # epoch seconds of the current start(), or None
_timer = None         # threading.Timer that fires stop() at TUNNEL_TTL
_error = ""           # last user-facing error ("" when fine)
_autostarted = False  # True iff the CURRENT run was started by autostart(), not a click
# Reentrant: a SIGTERM can arrive while the main thread already holds _lock (autostart()/
# status() at boot) -- server._on_sigterm -> stop() must not deadlock against itself.
_lock = threading.RLock()


def _save_cfg(overrides):
    """Write config.json and lock it to owner-only. config.json can hold TUNNEL_USER/
    TUNNEL_PASS, so every write through this module gets the same chmod-0600 idiom
    server.py's POST /api/tunnel already applies -- best-effort, a chmod failure must never
    lose the write itself."""
    _save_json(config.CONFIG_FILE, overrides)
    try:
        os.chmod(config.CONFIG_FILE, 0o600)
    except OSError:
        pass


def via_tunnel(headers):
    """True when this request arrived THROUGH cloudflared, not loopback/LAN directly.
    cloudflared adds Cf-Connecting-Ip (the real client IP) and Cf-Ray to every request it
    proxies; a direct request carries neither. `headers` is a Handler's `.headers`
    (email.message.Message), whose `.get()` is already case-insensitive."""
    return bool(headers.get("Cf-Connecting-Ip") or headers.get("Cf-Ray"))


def cred():
    """"user:pass" for the tunnel's OWN Basic-auth check, resolved exactly the way the
    Config dialog's fields already are (config.resolve_tunnel_user/_pass: a config.json
    override, else a split of the CURRENT config.AUTH). "" when either half is blank --
    never a half-formed credential a request could match against an empty string."""
    overrides = _load_json(config.CONFIG_FILE, {})
    user = config.resolve_tunnel_user(overrides)
    pw = config.resolve_tunnel_pass(overrides)
    if not user or not pw:
        return ""
    return user + ":" + pw


def ensure_creds():
    """Guarantee a non-blank TUNNEL_USER/TUNNEL_PASS pair exists before a tunnel goes live.
    Returns (user, pass, generated) -- generated=True the ONE time a fresh pair was just
    minted, so the caller (server.py's ctl handler) can hand it back to the browser once;
    it can never be read back again after that (see config.py's tunnel_reveal for the sole
    deliberate exception to that rule). Never overwrites an already-staged pair."""
    with _lock:
        overrides = _load_json(config.CONFIG_FILE, {})
        user = config.resolve_tunnel_user(overrides)
        pw = config.resolve_tunnel_pass(overrides)
        if user and pw:
            return user, pw, False
        user = "ai-" + secrets.token_hex(3)
        pw = secrets.token_urlsafe(12)
        overrides["TUNNEL_USER"] = user
        overrides["TUNNEL_PASS"] = pw
        _save_cfg(overrides)
        return user, pw, True


def rotate_creds():
    """The Config dialog's explicit "Rotate credentials" action -- unlike ensure_creds,
    always mints a fresh pair even when one is already staged (any previously-shared link
    stops working immediately)."""
    with _lock:
        overrides = _load_json(config.CONFIG_FILE, {})
        user = "ai-" + secrets.token_hex(3)
        pw = secrets.token_urlsafe(12)
        overrides["TUNNEL_USER"] = user
        overrides["TUNNEL_PASS"] = pw
        _save_cfg(overrides)
        return user, pw


def _reader(proc):
    """Daemon thread: drain cloudflared's stderr for the rest of its life. Stops matching at the
    FIRST URL (an already-open tunnel doesn't get a second one) but keeps reading to EOF
    regardless -- a Popen whose PIPE fills up and is never drained will deadlock the child. If
    the process dies before any URL ever appeared, the last non-empty line is almost always
    cloudflared's own error message (missing network, DNS, etc.) -- surface that verbatim
    (truncated) rather than a generic failure."""
    global _error, _timer
    saw_url = False
    last_line = ""
    try:
        for raw in iter(proc.stderr.readline, b""):
            try:
                line = raw.decode("utf-8", "replace").strip()
            except Exception:
                continue
            if not line:
                continue
            last_line = line
            if not saw_url:
                m = URL_RE.search(line)
                if m:
                    saw_url = True
                    # Only write config.json under the lock, and only when this reader still
                    # belongs to the CURRENT tunnel (`proc is _proc`) -- a reader whose tunnel
                    # was already stop()ped (or replaced by a rotate) must not resurrect state
                    # a later/earlier writer already settled.
                    with _lock:
                        if proc is _proc:
                            overrides = _load_json(config.CONFIG_FILE, {})
                            overrides["TUNNEL_URL"] = m.group(0)
                            _save_cfg(overrides)
    finally:
        try:
            proc.stderr.close()
        except Exception:
            pass
        proc.wait()
        with _lock:
            # `proc is _proc`: a later start() may already have replaced the global by the
            # time this EOF fires (e.g. a rotate mid-flight, or this same tunnel already
            # stop()ped) -- don't let a stale reader clobber a newer attempt's state.
            if proc is _proc:
                if not saw_url:
                    _error = last_line[:200] if last_line else "cloudflared exited before a URL appeared"
                else:
                    # The child exited ON ITS OWN after printing a URL (network blip, the
                    # cloudflare edge dropping it, ...) -- surface that instead of leaving a
                    # dead URL looking live. TUNNEL_ON is left alone: it is the user's INTENT
                    # ("I want a tunnel"), not "is one running right now", so autostart() on
                    # the next boot still retries rather than treating this as opt-out.
                    _error = ("cloudflared exited: %s" % last_line[:200]) if last_line else "cloudflared exited"
                    if _timer is not None:
                        _timer.cancel()
                        _timer = None
                    overrides = _load_json(config.CONFIG_FILE, {})
                    overrides["TUNNEL_URL"] = ""
                    _save_cfg(overrides)


def start(port, host=None, _autostarted_flag=False):
    """Spawn cloudflared pointed at this server's own port. Idempotent: a no-op while
    already on. Clears TUNNEL_URL immediately (the new URL arrives asynchronously via
    _reader) and marks TUNNEL_ON so a later autostart() picks it back up. `_autostarted_flag`
    is set only by autostart() itself -- never pass it from a click handler.

    `host` is the bind host the SERVER is actually listening on (server.py's config.BIND_HOST
    or the socket's own address) -- NOT necessarily "127.0.0.1". A blank/None/"0.0.0.0"/"::"
    (every "listen on all interfaces" spelling) still origins to 127.0.0.1: cloudflared runs
    on THIS machine, so the loopback address always reaches a wildcard-bound server, while
    "0.0.0.0" itself is not a connectable address.

    The _reader thread is started right after Popen, BEFORE the config.json write below --
    a write failure must never leave cloudflared's stderr undrained (a full PIPE deadlocks
    the child). The write itself is try/except'd: on failure the just-spawned child is killed
    (via stop(), idempotent) and _error is set, so status() shows on=False with the failure
    instead of a tunnel the UI thinks is up that config.json never actually recorded."""
    global _proc, _started, _timer, _error, _autostarted
    origin_host = host if host not in (None, "", "0.0.0.0", "::") else "127.0.0.1"
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return  # already on
        if not shutil.which(CLOUDFLARED):
            _error = "cloudflared not found — brew install cloudflared"
            _proc = None
            _autostarted = False
            return
        try:
            proc = subprocess.Popen(
                [CLOUDFLARED, "tunnel", "--url", "http://%s:%d" % (origin_host, port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        except OSError as e:
            _error = ("failed to start cloudflared: %s" % e)[:200]
            return
        _error = ""
        _proc = proc
        _started = time.time()
        _autostarted = _autostarted_flag
        threading.Thread(target=_reader, args=(proc,), daemon=True).start()
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(TUNNEL_TTL, stop)
        _timer.daemon = True
        _timer.start()
    try:
        overrides = _load_json(config.CONFIG_FILE, {})
        overrides["TUNNEL_URL"] = ""
        overrides["TUNNEL_ON"] = True
        _save_cfg(overrides)
    except Exception as e:
        _error = "config write failed: %s" % e
        stop()  # kill the child we just spawned -- config.json never recorded it as on


def stop(keep_on=False):
    """Kill the current tunnel, if any. SIGTERM the whole process group first (cloudflared
    forks helpers under some builds; start_new_session=True at spawn time makes `proc.pid`
    its own group leader, so killpg reaches all of them), SIGKILL as a fallback. Idempotent
    -- safe to call when already off. Touches config.json ONLY when this process owns a
    tunnel: the atexit hook runs in every process that imports this module (--selfcheck, the
    test suite, make bundle), and a no-op stop must not wipe the TUNNEL_ON/TUNNEL_URL of the
    server that is actually running one. A stale "on" flag from a killed-without-stop()
    process is exactly what autostart() is for.

    `keep_on=True` (the SERVER PROCESS itself exiting -- atexit/_on_sigterm) leaves TUNNEL_ON
    untouched so the next `make serve` re-mints the tunnel (autostart() + run()'s one-time
    notice); only TUNNEL_URL is cleared, since the old hostname is dead either way. The
    explicit switch-off (ctl "stop"), the TTL timer, and rotate()'s internal stop keep the
    default (False) -- those ARE the user/policy turning the tunnel off.

    The kill happens BEFORE the config.json write, and the write is try/except'd, so a write
    failure can never leave the cloudflared child running unkilled."""
    global _proc, _timer, _autostarted, _error
    with _lock:
        proc = _proc
        _proc = None
        _autostarted = False
        if _timer is not None:
            _timer.cancel()
            _timer = None
    if proc is not None and proc.poll() is None:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # ponytail: SIGTERM alone occasionally leaves a stuck cloudflared behind under
                # load in local testing -- one SIGKILL fallback rather than looping/retrying is
                # enough for a single-user local tool; this is not a process supervisor.
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=3)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
    if proc is not None:
        try:
            overrides = _load_json(config.CONFIG_FILE, {})
            overrides["TUNNEL_URL"] = ""
            if not keep_on:
                overrides["TUNNEL_ON"] = False
            _save_cfg(overrides)
        except Exception as e:
            _error = "config write failed: %s" % e


def rotate(port, host=None):
    """"Rotate" = stop + start, per the task's own definition -- a Cloudflare quick tunnel
    always mints a brand-new random hostname; there is no in-place URL refresh to ask for.
    ensure_creds() runs first so rotating a tunnel that was never actually started (blank
    creds) still comes up authenticated. `host` -- see start()'s docstring."""
    ensure_creds()
    stop()
    start(port, host=host)


def autostart(port, host=None):
    """Called once from server.py's run(), right after the real bound port is known. If the
    LAST run left the tunnel on (TUNNEL_ON in config.json), bring it back up with a fresh
    URL and the SAME staged credential, flagged autostarted=True so the SPA can show a
    one-time notice instead of silently reintroducing public exposure. No-op otherwise.
    `host` -- see start()'s docstring."""
    overrides = _load_json(config.CONFIG_FILE, {})
    if not overrides.get("TUNNEL_ON"):
        return
    ensure_creds()
    start(port, host=host, _autostarted_flag=True)


def status():
    """The one shape GET /api/tunnel and POST /api/tunnel/ctl both report (merged with
    config.tunnel_public() by server.py). Reads config.json fresh on every call -- this is a
    low-frequency dialog poll, not a hot path -- so a URL the reader thread just wrote is
    visible on the very next poll."""
    overrides = _load_json(config.CONFIG_FILE, {})
    with _lock:
        proc, started, autostarted, err = _proc, _started, _autostarted, _error
    alive = proc is not None and proc.poll() is None
    return {
        "on": alive,
        "url": config.resolve_tunnel_url(overrides),
        "pid": proc.pid if alive else None,
        "started": started if alive else None,
        "expires": (started + TUNNEL_TTL) if (alive and started) else None,
        "error": err,
        "cloudflared": bool(shutil.which(CLOUDFLARED)),
        "autostarted": bool(alive and autostarted),
    }


def _on_exit():
    """atexit hook: kill any child this process spawned when the process itself exits
    (Ctrl-C, crash, `make stop`'s SIGTERM via server._on_sigterm). keep_on=True -- this is
    the PROCESS going away, not the user switching the tunnel off, so TUNNEL_ON is left as-is
    and the next `make serve` re-mints it. Module-level (not a lambda/closure) so a test can
    call it directly."""
    stop(keep_on=True)


# Registered at import time so it applies regardless of how run() was reached. stop() is
# idempotent, so this is a no-op when nothing is running.
atexit.register(_on_exit)
