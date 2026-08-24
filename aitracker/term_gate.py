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


def is_bg_agent(sid):
    """True when `sid` names a background-agent session, in ANY status.

    Previously named `is_live_agent` and additionally required the session to be inside
    `config.LIVE_WINDOW` -- that liveness condition was wrong and is now GONE.
    docs/claude-resume-command-matrix.md (live PTY tests against the real `claude` CLI)
    found the "currently running as a background agent" refusal fires for a background
    agent whose `claude agents --json` status is `"blocked"` OR `"done"` -- i.e.
    unconditionally on `sessionKind == "bg"`, never on recency. Gating this on
    LIVE_WINDOW meant a bg-agent session older than 5 minutes silently got NO
    `--fork-session` and hit the refusal anyway -- see resume_argv() below, the seam that
    acts on this.

    Resolved via registry.is_bg_agent(sid), which asks the OWNING PROVIDER directly for
    THIS ONE sid (for Claude: one glob + a bounded read of that single file) rather than
    scanning registry.all_sessions()'s top-N-by-mtime list -- a background agent outside
    that recency window used to be invisible to a lookup keyed off that list and silently
    answered False, which was the other half of this bug. This is the shared seam
    (conventions rule 3): term_gate does not reimplement providers/claude.py's own
    classifier (`sessionKind == "bg"` OR `entrypoint == "sdk-cli"`, fixed independently in
    that module) -- it calls it. Late import: registry pulls in every provider, and this
    module is imported from server at startup."""
    from .registry import is_bg_agent as _registry_is_bg_agent
    return _registry_is_bg_agent(sid)


REFUSAL_MARKER = "is currently running as a background agent (bg)"
"""Substring of the CLI's verbatim refusal (docs/claude-resume-command-matrix.md):

    Session <id> is currently running as a background agent (bg). Use `claude agents`
    to find and attach to it, or add --fork-session to branch off a copy.

Deliberately just this phrase, not the whole message: it never contains the resumed
`<id>` (which the caller doesn't have handy to interpolate) and isn't a plausible line-
wrap boundary, so it's safe to match on its own -- see looks_like_bg_refusal(). This is
the ONE seam that owns the exact wording; a test pins it against the matrix's verbatim
capture so a future CLI wording change fails the suite loudly instead of silently
disabling the Option-C backstop term_vt.py builds on top of it."""

MISSING_TRANSCRIPT_MARKER = "No conversation found with session ID:"
"""Verbatim prefix of the CLI's message when `--resume <sid>` can't find ANY transcript
for `sid` (docs/claude-resume-command-matrix.md). Unlike the bg-agent refusal, the CLI
does not exit here -- it prints this and then silently falls through into a BRAND-NEW
session in the current directory. So this is a warn-but-still-open signal, not a retry
trigger -- see looks_like_missing_transcript()."""


def _normalize_output(output) -> str:
    """`bytes` (or `str`) captured from a child's pty -> one whitespace-collapsed line, so
    a real terminal's own line-wrapping (which can split REFUSAL_MARKER/
    MISSING_TRANSCRIPT_MARKER across two visual lines at whatever column the pty happens
    to be) can never hide a match."""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    return " ".join(output.split())


def looks_like_bg_refusal(output) -> bool:
    """True if `output` (raw bytes/str captured from a `claude --resume` child) contains
    the "currently running as a background agent" refusal -- the ONE signal Option C's
    backstop (term_vt.py) uses to retry once with --fork-session when the fast-path
    classification (is_bg_agent, above) missed. This is what makes the fast path the
    normal case and the string match only a safety net: a future wording change makes
    this stop matching, which degrades to today's behaviour (no retry) rather than
    breaking anything."""
    return REFUSAL_MARKER in _normalize_output(output)


def looks_like_missing_transcript(output) -> bool:
    """True if `output` contains the CLI's "no conversation found" message -- see
    MISSING_TRANSCRIPT_MARKER. Used to warn the user that what just opened is a brand-new
    conversation, not the transcript they clicked Resume on."""
    return MISSING_TRANSCRIPT_MARKER in _normalize_output(output)


def resume_argv(sid):
    """The argv for `claude --resume <sid>`, with `--fork-session` appended when
    `is_bg_agent(sid)` -- the ONE place both terminal tiers decide this (term_vt.open_pty
    uses the list directly; term_launch.open_terminal passes it into build_script), so the
    two call sites can't drift (conventions rule 4).

    Why this is the honest fix and not a full one: `--fork-session` branches a COPY of the
    agent's conversation -- it does NOT attach to the actually-running agent. Claude Code's
    refusal message also suggests `claude agents`, which WOULD attach to the live session,
    but that's an interactive picker with no argv that could drive it non-interactively.
    Between "refuse to open a terminal at all" and "open one on a deliberate copy", this
    picks the copy -- and callers should say so where they surface the result (a fork was
    the trade-off, not a mistake). This is the FAST path (Option A); when it misses (a
    background agent this classification failed to recognise), term_vt.py's Option-C
    backstop -- retry once with --fork-session on seeing REFUSAL_MARKER -- is the safety
    net, not a second decision point here."""
    argv = ["claude", "--resume", sid]
    if is_bg_agent(sid):
        argv.append("--fork-session")
    return argv
