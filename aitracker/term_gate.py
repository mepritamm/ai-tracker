"""Shared gate for the terminal features (Tiers 1-3).

These routes start processes on the host, and are enabled by default. `HOST=0.0.0.0 make serve`
(LAN/Tailscale — see cli.py's HOST env var) and `make tunnel` are both supported, documented ways
to expose this server beyond loopback, and both require TRACKER_AUTH before the terminal is
usable off-loopback — see allowed() below. A loopback-only `make serve` (the default) needs no
TRACKER_AUTH. Cross-origin requests are still rejected as a belt-and-braces protection.

IMPORTANT: On a server that IS reachable and has a password, anyone with TRACKER_AUTH gets an
unrestricted shell as this OS user.
"""
import ipaddress
from urllib.parse import urlparse

from . import config

_LOOPBACK_NAMES = {"localhost"}


def _is_loopback(host):
    """True if `host` can only ever mean "this machine talking to itself". Evaluated against
    the server's *bind* address (config.BIND_HOST) — never a request's peer address, since a
    tunnel terminates locally and its requests also arrive from 127.0.0.1 even though the
    tunnel makes the server reachable from anywhere. Unknown/unparseable input is treated as
    NOT loopback: the safe default is to require auth, not to wave it through."""
    if not host:
        return False
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def allowed():
    """True if terminal routes may run at all. Terminal is ON by default; set
    TRACKER_TERMINAL=0 to disable. When the server is bound beyond loopback — HOST=0.0.0.0, a
    LAN/Tailscale IP, anything `make tunnel` fronts — TRACKER_AUTH is also required, since
    without it the terminal would hand an unauthenticated, unrestricted shell to anyone who can
    reach the server."""
    if not config.TERMINAL:
        return False
    return bool(config.AUTH) or _is_loopback(config.BIND_HOST)

def _origin_ok(handler):
    """Reject cross-site POSTs. The signed cookie is SameSite=Lax, which already blocks
    cross-site form POSTs, but this is the belt to that braces -- a shell is not a place to
    rely on one mechanism."""
    origin = handler.headers.get("Origin", "")
    if not origin:
        return True                     # same-origin fetch / curl: no Origin header
    host = handler.headers.get("Host", "")
    return urlparse(origin).netloc == host

def guard(handler):
    """Call first in every terminal route. Returns True if the request may proceed;
    otherwise it has already written the response."""
    if not config.TERMINAL:
        handler._json({"error": "terminal disabled — unset TRACKER_TERMINAL or set it to anything other than 0"}, 403)
        return False
    if not allowed():
        handler._json({"error": "terminal disabled: this server is reachable on the network, so it needs TRACKER_AUTH"}, 403)
        return False
    if not _origin_ok(handler):
        handler._json({"error": "cross-origin refused"}, 403)
        return False
    return True

def session_cwd(sid):
    """The working directory for a session id, or "" if unknown/gone. Late import: registry
    pulls in every provider, and this module is imported from server at startup."""
    import os
    from .registry import parse_any
    try:
        cwd = ((parse_any(sid) or {}).get("meta") or {}).get("cwd") or ""
    except Exception:
        return ""
    return cwd if cwd and os.path.isdir(cwd) else ""


def is_live_agent(sid):
    """True when `sid` names a background-agent session (the shared session-list shape's
    `"agent"` key -- providers/claude.py sets it for entrypoint=sdk-cli; every other
    provider hardcodes it False) that is STILL WITHIN the app's own liveness window
    (config.LIVE_WINDOW, matched by `LIVE` in web/app.js -- conventions rule 5, don't add
    a second threshold). This is exactly the condition under which Claude Code's own CLI
    refuses a plain `claude --resume <sid>` with "... is currently running as a background
    agent (bg)." -- see resume_argv() below, the seam that acts on this.

    Looks the sid up in registry.all_sessions() (the shared list shape every provider
    emits), never a specific provider's list -- conventions rule 3. Late import: registry
    pulls in every provider, and this module is imported from server at startup."""
    import time
    from .config import LIVE_WINDOW
    from .registry import all_sessions
    for s in all_sessions():
        if s.get("id") == sid:
            return bool(s.get("agent")) and (time.time() - (s.get("mtime") or 0)) < LIVE_WINDOW
    return False


def resume_argv(sid):
    """The argv for `claude --resume <sid>`, with `--fork-session` appended when
    `is_live_agent(sid)` -- the ONE place both terminal tiers decide this (term_vt.open_pty
    uses the list directly; term_launch.open_terminal passes it into build_script), so the
    two call sites can't drift (conventions rule 4).

    Why this is the honest fix and not a full one: `--fork-session` branches a COPY of the
    agent's conversation -- it does NOT attach to the actually-running agent. Claude Code's
    refusal message also suggests `claude agents`, which WOULD attach to the live session,
    but that's an interactive picker with no argv that could drive it non-interactively.
    Between "refuse to open a terminal at all" and "open one on a deliberate copy", this
    picks the copy -- and callers should say so where they surface the result (a fork was
    the trade-off, not a mistake). A finished (no-longer-live) agent session is resumed
    normally: forking a conversation nothing is still adding to would just hand the user a
    pointless duplicate."""
    argv = ["claude", "--resume", sid]
    if is_live_agent(sid):
        argv.append("--fork-session")
    return argv
