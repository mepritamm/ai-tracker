"""Tier 1 — launch a real Terminal/iTerm tab at a session's cwd, optionally resuming Claude.

Registers POST /api/term/open into server.EXTRA_POST at import time (see the loader at the
bottom of server.py). This module is file-disjoint from Step 0 and the other terminal tiers —
it never edits server.py, page.py, index.html or app.js.
"""
import os
import shlex
import subprocess

from . import server, term_gate

TERM_APPS = ("Terminal", "iTerm")   # TRACKER_TERM_APP; anything else falls back to Terminal


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
    step could still break out of the AppleScript string in the second.
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
    # Same-machine only: this launches an OS process on whatever Mac is running the server.
    # Over `make tunnel` that is never the caller's machine, so refuse anything not loopback --
    # ext_launch.js additionally hides both buttons unless the page itself was loaded from
    # localhost/127.0.0.1 (see the comment there for why that host check is allowed to exist).
    if handler.client_address[0] != "127.0.0.1":
        handler._json({"error": "terminal launch is local-only"}, 403)
        return
    body = body or {}
    sid = body.get("session", "")
    mode = body.get("mode", "cwd")
    if not sid:
        handler._json({"error": "session required"}, 400)
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
