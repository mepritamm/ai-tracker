"""Shared gate for the terminal features (Tiers 1-3).

These routes start processes on the host. `make tunnel` deliberately puts this server on the
public internet, so "it's only localhost" is never true here -- a tunnel terminates locally and
its requests also arrive from 127.0.0.1. Hence: opt-in flag AND a configured login, always.
"""
from . import config
from urllib.parse import urlparse

def allowed():
    """True if terminal routes may run at all. Both conditions are required."""
    return bool(config.TERMINAL) and bool(config.AUTH)

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
    if not allowed():
        handler._json({"error": "terminal disabled — set TRACKER_TERMINAL=1 and TRACKER_AUTH"}, 403)
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
