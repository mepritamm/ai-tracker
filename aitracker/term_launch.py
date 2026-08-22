"""Tier 1 — launch a real Terminal/iTerm tab at a session's cwd, optionally resuming Claude.

Registers POST /api/term/open into server.EXTRA_POST at import time (see the loader at the
bottom of server.py). This module is file-disjoint from Step 0 and the other terminal tiers —
it never edits server.py, page.py, index.html or app.js.

What this route can and cannot promise
--------------------------------------
It starts a process on the Mac running the tracker, so it must never act for a remote caller.
**The real gate is `term_gate.guard()`: TRACKER_TERMINAL=1 *and* a configured TRACKER_AUTH.**
Everything below that is a mitigation, not a guarantee:

* A loopback peer address is not evidence of a local user. `make tunnel` runs
  `cloudflared tunnel --url http://localhost:<port>`, so the tunnel terminates on this machine
  and dials the server over loopback — every request that arrives from the public internet has
  `client_address[0] == "127.0.0.1"`. Checking the peer address alone is worthless here.
* So we also refuse anything carrying a proxy's fingerprint (`_PROXY_HEADERS`), which is what
  cloudflared and the usual reverse proxies add. That closes the `make tunnel` path.
* **Residual limitation, stated plainly:** an authenticated caller on the LAN who reaches the
  port directly (`HOST=0.0.0.0`), or a proxy configured to strip its own headers, still
  presents as an unproxied loopback client and would be allowed through. "Local-only" here is
  BEST EFFORT, not a guarantee. What actually stands between a stranger and a terminal on this
  Mac is TRACKER_AUTH.
"""
import os
import re
import shlex
import subprocess

from . import server, term_gate

TERM_APPS = ("Terminal", "iTerm")   # TRACKER_TERM_APP; anything else falls back to Terminal

# Headers that only ever appear when something forwarded the request on the caller's behalf.
# cloudflared (`make tunnel`) sets CF-Connecting-IP / CF-Ray / X-Forwarded-For; nginx, Caddy and
# ngrok set the X-Forwarded-* / Forwarded family. WHY sniff headers at all: the peer address
# does not distinguish a local user from the public internet, because a tunnel terminates on
# this machine and connects to the server over loopback. Any of these present => refuse.
_PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Host", "Forwarded",
                  "CF-Connecting-IP", "CF-Ray", "X-Real-IP")

# Glob metacharacters and path separators. providers.claude.find_session interpolates the sid
# straight into glob.glob("<PROJECTS>/*/<sid>.jsonl"), so a sid of "*" quietly resolves to
# whichever session sorts first — one the caller never named. "*" is not a typo of a session id.
_SID_BAD = re.compile(r"[*?\[\]/\\]")

_NOT_LOCAL = "; this opens a terminal on the tracker's own Mac"


def _proxy_header(handler):
    """Name of the first proxy fingerprint header present, or "" — see _PROXY_HEADERS."""
    for h in _PROXY_HEADERS:
        if handler.headers.get(h, ""):
            return h
    return ""


def _local_caller(handler):
    """(ok, error). Belt: no proxy fingerprint. Braces: the peer address is still loopback.
    Neither is sufficient alone — see the module docstring for what this does NOT promise."""
    hdr = _proxy_header(handler)
    if hdr:
        return False, "refused: request appears to be proxied (%s)%s" % (hdr, _NOT_LOCAL)
    peer = handler.client_address[0]
    if peer != "127.0.0.1":
        return False, "refused: caller is not on this machine (%s)%s" % (peer, _NOT_LOCAL)
    return True, ""


def normalize_sid(sid):
    """The sid as it will actually be resolved, or "" when its shape is unusable.

    `providers.claude.find_session` strips whitespace and drops ".jsonl" before it globs, so the
    raw body value and the session that really gets opened can differ — and the value handed to
    `claude --resume` must be the one that was resolved, not the one that was typed. Normalise
    the same way find_session does, and reject outright anything with a glob metacharacter, a
    path separator, or surrounding whitespace.
    """
    if not isinstance(sid, str) or not sid or sid != sid.strip():
        return ""
    if _SID_BAD.search(sid):
        return ""
    if sid.endswith(".jsonl"):
        sid = sid[:-len(".jsonl")]
    if ".jsonl" in sid:                 # find_session's .replace() would strip it; we don't guess
        return ""
    return sid


def _is_claude(sid):
    """True when `sid` belongs to the unprefixed (Claude) provider. Late import: registry
    pulls in every provider, and this module is imported from server at startup."""
    from .registry import PROVIDERS
    for p in PROVIDERS:
        if p.prefix and sid.startswith(p.prefix):
            return False
    return True


def build_script(cwd: str, sid: str, mode: str, app: str) -> str:
    """Return the AppleScript source that opens a tab and runs the command.

    Pure function -- no side effects -- so the test can assert the exact string. `cwd` comes
    out of a session log file, so it is untrusted input to a shell: it is shlex-quoted for the
    inner shell command FIRST, then the whole inner command is escaped for the AppleScript
    string literal (backslash, then double-quote) -- in that order, or a `"` surviving the first
    step could still break out of the AppleScript string in the second. `sid` reaches here only
    via normalize_sid().
    """
    inner = "cd %s" % shlex.quote(cwd)
    if mode == "resume":
        inner += " && claude --resume %s" % shlex.quote(sid)
    escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
    if app == "iTerm":
        return (
            'tell application "iTerm"\n'
            "  activate\n"
            "  create window with default profile\n"
            "  tell current session of current window\n"
            '    write text "%s"\n'
            "  end tell\n"
            "end tell"
        ) % escaped
    return (
        'tell application "Terminal"\n'
        "  activate\n"
        '  do script "%s"\n'
        "end tell"
    ) % escaped


def open_terminal(handler, parsed, body) -> None:
    """POST /api/term/open -- {"session": "<sid>", "mode": "cwd"|"resume"} -> {"ok": true}."""
    if not term_gate.guard(handler):
        return
    ok, err = _local_caller(handler)
    if not ok:
        handler._json({"error": err}, 403)
        return
    if not isinstance(body, dict):      # server.do_POST accepts ANY JSON value, "a string" included
        handler._json({"error": "bad body: expected a JSON object"}, 400)
        return
    raw = body.get("session", "")
    mode = body.get("mode", "cwd")
    if not raw:
        handler._json({"error": "session required"}, 400)
        return
    sid = normalize_sid(raw)
    if not sid:
        handler._json({"error": "bad session id"}, 400)
        return
    if mode not in ("cwd", "resume"):
        handler._json({"error": "bad mode"}, 400)
        return
    if mode == "resume" and not _is_claude(sid):
        handler._json({"error": "resume is Claude-only"}, 400)
        return
    cwd = term_gate.session_cwd(sid)
    if not cwd:
        handler._json({"error": "session not found or its cwd no longer exists"}, 404)
        return
    app = os.environ.get("TRACKER_TERM_APP", "Terminal")
    if app not in TERM_APPS:
        app = "Terminal"
    script = build_script(cwd, sid, mode, app)
    try:
        subprocess.run(["osascript", "-e", script], check=True, timeout=10,
                        capture_output=True)
    except Exception as e:
        handler._json({"error": "failed to launch terminal: %s" % e}, 500)
        return
    handler._json({"ok": True})


server.EXTRA_POST["/api/term/open"] = open_terminal
