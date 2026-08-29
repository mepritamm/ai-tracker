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
import re
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


REFUSAL_MARKER = "is currently running as a background agent (bg)"
"""Substring of the CLI's OLD verbatim refusal (docs/claude-resume-command-matrix.md), kept
for backward compat -- existing tests reference this name directly, and an older `claude`
binary on another machine may still emit exactly this wording:

    Session <id> is currently running as a background agent (bg). Use `claude agents`
    to find and attach to it, or add --fork-session to branch off a copy.

Deliberately just this phrase, not the whole message: it never contains the resumed
`<id>` (which the caller doesn't have handy to interpolate) and isn't a plausible line-
wrap boundary, so it's safe to match on its own -- see looks_like_bg_refusal(). This was
the ONE seam that owned the exact wording -- see BG_REFUSAL_MARKERS below for why it's
no longer the only one."""

BG_REFUSAL_MARKERS = (
    REFUSAL_MARKER,
    "is running as a background session",
)
"""Every wording of the CLI's "still running elsewhere" refusal that `looks_like_bg_refusal()`
matches. REFUSAL_MARKER (above) is the LEGACY wording; the CURRENT `claude` CLI instead prints
(verbatim, from a real capture):

    Session <id> is running as a background session (<short-id>). Run `claude attach
    <short-id>` to open it, or `claude stop <short-id>` first to resume it here. Add
    --fork-session to branch off a copy instead.

This is not a cosmetic rewrite -- the two messages describe DIFFERENT recoveries. The legacy
CLI only offered `claude agents` (an interactive picker, no scriptable argv) or
`--fork-session`; the current CLI instead names a `claude attach <id>` command we CAN drive
non-interactively -- see attach_target()/attach_argv() below. Both strings are kept in this
tuple, not just swapped, because a wording change silently disables whichever backstop keyed
off the old string -- looks_like_bg_refusal()'s docstring predicted exactly this ("degrades to
no retry at all"), and that prediction came true (the backstop went silently dead) before it
was caught here. Matching a tuple of known wordings, instead of one pinned string, is the
mitigation: a NEXT wording change still degrades gracefully (no match, no retry, no crash),
but this file no longer bets its only recovery path on one exact sentence."""

MISSING_TRANSCRIPT_MARKER = "No conversation found with session ID:"
"""Verbatim prefix of the CLI's message when `--resume <sid>` can't find ANY transcript
for `sid` (docs/claude-resume-command-matrix.md). Unlike the bg-agent refusal, the CLI
does not exit here -- it prints this and then silently falls through into a BRAND-NEW
session in the current directory. So this is a warn-but-still-open signal, not a retry
trigger -- see looks_like_missing_transcript()."""


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?<>=]*[ -/]*[@-~]"     # CSI -- incl. the \x1b[<n>G cursor jumps below. The ':'
                                          # is required: ITU sub-parameter SGR (\x1b[38:2:255:0:0m,
                                          # \x1b[4:3m curly underline) is real output, and without
                                          # it the whole sequence spilled through as "38:2:255:0:0m".
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC  -- title sets etc.
    r"|\x1b[P^_X][^\x1b]*(?:\x1b\\|\x07)"   # DCS / PM / APC / SOS -- terminated strings
    r"|\x1b[ -/]*[0-~]"                   # Fp/Fs/Fe + charset escapes: ESC 7, ESC 8, ESC ( B, ...
                                          # (0x30-0x7E finals -- NOT just @-Z: ESC 7 / ESC 8 are
                                          # the first bytes a real `claude --resume` emits, and a
                                          # narrower class left a stray "7"/"8" behind that read as
                                          # printable text)
)

_ANSI_PARTIAL_TAIL_RE = re.compile(
    r"\x1b(?:\[[0-9;:?<>=]*[ -/]*"       # a CSI whose final byte hasn't arrived yet
    r"|\][^\x07\x1b]*"                  # an OSC still waiting for its BEL / ST
    r"|[P^_X][^\x1b]*"                   # a DCS/PM/APC/SOS still waiting for its ST
    r"|[ -/]*"                            # ESC + intermediates, final byte not here yet
    r")?$"
)
"""A TRAILING, still-incomplete escape sequence -- dropped before matching rather than left to be
half-eaten by _ANSI_RE.

This is the same defect as the one _ANSI_RE's ESC 7/ESC 8 comment describes, one level down, and
it is the reason it matters: **a pty master read is capped at 1024 bytes**, so Ink's init frame
never arrives as one chunk, and `_resume_backstop` re-scans its buffer after EVERY chunk. Whenever
a chunk boundary falls inside an escape sequence -- probability ~(N-1)/N for N-byte sequences, so
usually -- the partial tail survives stripping as printable junk: b'...\x1b[38' normalises to
'38', a buffer ending on a bare b'\x1b' normalises to '\x1b' (str.split() does NOT treat ESC as
whitespace). Measured: 26 of the 42 prefixes of the captured init burst normalised to non-empty.

That junk latched `_resume_backstop`'s settle clock at t~=0.06s instead of at first real text, so
`starting` cleared at ~0.57s and the refusal painted at 2.05s after all -- the exact bug the flag
exists to prevent, reproduced end to end. Stripping the partial tail makes normalisation a
function of the CONTENT rather than of where the reader happened to slice the stream."""
"""Every escape sequence stripped (to a SPACE, never to nothing) before marker matching.

MEASURED, not assumed: `claude --resume <bg-id>` on a real pty renders the refusal through
Ink, which does not emit spaces between words -- it jumps the cursor to each word's column.
The raw bytes are literally:

    Session\x1b[9G<id>\x1b[46Gis\x1b[49Gcurrently\x1b[59Grunning\x1b[67Gas\x1b[70Ga\r\r\n
    background\x1b[12Gagent\x1b[18G(bg).\x1b[24GUse ...

so REFUSAL_MARKER ("is currently running as a background agent (bg)") is NOT a substring of
those bytes at all, whitespace-collapsed or not -- the old normalisation only handled the
`\r\n` wraps, which is why the pinned plain-text capture in the tests passed while the live
terminal never once fired the backstop. Substituting a space keeps the words apart; deleting
the escapes would fuse "currently" and "running" into one token and fail just as silently."""


def _normalize_output(output) -> str:
    """`bytes` (or `str`) captured from a child's pty -> one whitespace-collapsed line with
    escape sequences replaced by spaces, so neither the terminal's own line-wrapping nor
    Ink's column-jump rendering (see _ANSI_RE) can hide a REFUSAL_MARKER/
    MISSING_TRANSCRIPT_MARKER match."""
    # None/absent output normalizes to "" rather than raising. Every caller here is a
    # `looks_like_*`/`attach_target` predicate on a best-effort read of a child's pty, and a
    # predicate that throws on "nothing arrived yet" would take down the backstop thread that
    # is the ONLY thing rescuing a refused resume -- the exact failure this seam exists to fix.
    if output is None:
        return ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    # Drop a trailing half-arrived escape FIRST -- see _ANSI_PARTIAL_TAIL_RE. Doing it after
    # _ANSI_RE would be too late: _ANSI_RE's last branch would already have eaten the ESC and
    # spilled the rest as text.
    output = _ANSI_PARTIAL_TAIL_RE.sub("", output)
    return " ".join(_ANSI_RE.sub(" ", output).split())


def looks_like_bg_refusal(output) -> bool:
    """True if `output` (raw bytes/str captured from a `claude --resume` child) contains
    ANY of BG_REFUSAL_MARKERS -- the ONE signal Option C's backstop (term_vt.py) uses to
    retry once with --fork-session. resume_argv() no longer guesses proactively at all
    (see its docstring), so this is now the ONLY thing that decides a fork for the
    in-browser PTY tier, not a safety net for a fast path that missed. This USED to match
    a single pinned string, and a CLI wording change silently degraded that to no retry at
    all -- that prediction came true (see BG_REFUSAL_MARKERS): the CLI switched from
    "is currently running as a background agent (bg)" to "is running as a background
    session", and the single-string match went silently dead. Matching the tuple is the
    mitigation, not a fix that rules out recurrence -- a THIRD wording still degrades the
    same way (a bare refusal shown to the user, no retry) rather than raising."""
    normalized = _normalize_output(output)
    return any(marker in normalized for marker in BG_REFUSAL_MARKERS)


def looks_like_missing_transcript(output) -> bool:
    """True if `output` contains the CLI's "no conversation found" message -- see
    MISSING_TRANSCRIPT_MARKER. Used to warn the user that what just opened is a brand-new
    conversation, not the transcript they clicked Resume on."""
    return MISSING_TRANSCRIPT_MARKER in _normalize_output(output)


def resume_argv(sid):
    """The argv for `claude --resume <sid>`. Deliberately does NOT append
    `--fork-session` proactively any more -- both terminal tiers (term_vt.open_pty uses
    the list directly; term_launch.open_terminal passes it into build_script) call this
    ONE function, so whatever it decides can't drift between them (conventions rule 4);
    what changed is what it decides.

    CORRECTED: this used to append --fork-session whenever the session's own TRANSCRIPT
    claimed to be a background agent (sessionKind == "bg" or entrypoint == "sdk-cli" --
    providers/claude.py's `_is_bg_agent`, which still drives the unrelated sidebar 🤖
    badge, just not this any more). That was measured live and found OVER-BROAD: a
    session keeps sessionKind == "bg" in its transcript forever, even long after `claude`
    itself has deregistered it as a background agent -- and once deregistered, a plain
    `claude --resume <sid>` opens it normally, no refusal at all. Forking pre-emptively in
    that case handed the user a COPY under a brand-new session id when a plain resume
    would have reopened their actual conversation -- silently losing continuity, which is
    worse than the refusal this file's backstops already recover from automatically.

    The signal that actually tracks the refusal is the LIVE `claude agents --json`
    registry (an id is forkable only while that command still lists it), not the
    transcript -- but timed on this machine, `claude agents --json` took 750-960ms per
    call across 5 consecutive runs, with no warm-start speedup between them. That is too
    slow to shell out for synchronously on EVERY `mode="resume"` open -- not just
    background-agent ones, since this function can't know which a session is without
    asking. So the proactive guess is dropped entirely; correctness now rests solely on
    the two backstops that already run unconditionally, independently of anything decided
    here:
      - term_vt.py's `_resume_backstop` (Tier 2, in-browser PTY): watches the just-
        spawned child's own output for REFUSAL_MARKER and retries once with
        --fork-session -- see looks_like_bg_refusal() below.
      - term_launch.py's `build_script` (Tier 3, external Terminal.app/iTerm): always
        wraps a resume argv lacking --fork-session in a shell-level
        `(<resume> || <resume> --fork-session)` fallback, so a refusal falls back with no
        ai-tracker process even watching.
    The cost of dropping the fast path is a visible refusal flash plus one respawn on a
    genuine background-agent resume, and NOTHING on every other session -- trading a
    recoverable, visible delay for never silently mis-forking a live conversation.

    `--fork-session` (whichever path appends it) branches a COPY of the agent's
    conversation -- it does not attach to the actually-running agent. Claude Code's
    refusal message also suggests `claude agents`, which WOULD attach to the live
    session, but that's an interactive picker with no argv that could drive it
    non-interactively. Between "refuse to open a terminal at all" and "open one on a
    deliberate copy", this picks the copy -- and callers should say so where they surface
    the result (a fork was the trade-off, not a mistake)."""
    return ["claude", "--resume", sid]


_ATTACH_HINT_RE = re.compile(r"claude attach ([0-9a-fA-F]{4,})")
"""Pulls candidate short session ids out of the CURRENT CLI's own refusal hint (see
BG_REFUSAL_MARKERS) -- e.g. "Run `claude attach e30d3b6a` to open it" normalizes (per
_normalize_output(), which leaves backticks untouched -- they aren't an escape sequence,
so `claude attach e30d3b6a` survives normalization character-for-character; verified by
calling _normalize_output() on a real capture rather than assumed) to a plain substring
containing "claude attach e30d3b6a", which this matches directly.

Constrained to `[0-9a-fA-F]{4,}` -- hex only -- because real session ids (confirmed
against actual filenames under `~/.claude/projects/*/*.jsonl`, e.g.
"e30d3b6a-046e-483b-b0f5-e0a1d692abfa.jsonl") are lowercase-hex UUIDs, and their short
form is just a hex prefix. A looser `[0-9a-zA-Z_-]*` class previously let this regex
absorb ANY word after "claude attach" -- e.g. "Run claude attach my-session-name-here
now" parsed out "my-session-name-here" as if it were a real id. Hex-only closes that.

This regex alone does NOT decide the attach target any more -- a MATCH here is only a
CANDIDATE. See attach_target()'s cross-check: the pane this is scraped from is a
terminal replaying a live Claude session, and that session's own transcript can itself
contain text that QUOTES a refusal for a totally different session (e.g. a prior
attach attempt shown in scrollback, or the assistant discussing this very feature).
Trusting the first hex token found after "claude attach" -- with no check against what
the user actually clicked -- let a replayed/quoted refusal for session A silently attach
the user into session B's live agent while the UI showed no signal anything was
wrong (no `⑂` chip on the attach path). The fix is entirely in attach_target(): only a
token that is a genuine prefix of the clicked `sid` is ever accepted."""


def attach_target(output, sid="") -> str:
    """The short session id to hand to `claude attach`, or "" if none can be determined
    or verified.

    SECURITY: `output` is scraped from a pane showing a live terminal, which is a Claude
    session that can itself print or replay text quoting a `claude attach <token>` hint
    for a DIFFERENT session (scrollback, a pasted transcript, the assistant discussing
    this feature, ...). A scraped token is therefore never trusted on its own -- it is
    accepted ONLY when it cross-checks against `sid`, the session id the user actually
    clicked:

      1. If `sid` is non-empty, scan ALL `_ATTACH_HINT_RE` matches in the normalized
         `output` (not just the first -- a later match can be the CORRECT one when an
         earlier one is a stale/unrelated hint) and return the first token that is a
         case-insensitive prefix of `sid` (`sid.lower().startswith(token.lower())`;
         session ids are hex-ish UUIDs whose short form is a hex prefix of the full id,
         so this is exactly the relationship a genuine hint has to its session).
      2. If no candidate passes that check, fall back to `sid[:8]` -- the same short
         form the CLI itself prints alongside the full id in a genuine refusal for THIS
         session, e.g. "(e30d3b6a)" for full id "e30d3b6a-046e-...".
      3. If `sid` is empty/None, there is nothing to cross-check a scraped token
         against, so an unverifiable hint is REFUSED rather than trusted -- return "".
         The caller falls back to plain --fork-session in that case, which is safe (it
         only ever produces a copy of the session the user asked for, never someone
         else's live agent); attaching to an unverified scraped id is not.

    Returns "" -- never raises -- when nothing can be verified (e.g. `output` is the
    LEGACY refusal, which carries no attach hint at all, and no `sid` was supplied
    either)."""
    normalized = _normalize_output(output)
    if sid:
        sid_lower = sid.lower()
        for match in _ATTACH_HINT_RE.finditer(normalized):
            token = match.group(1)
            if sid_lower.startswith(token.lower()):
                return token
        return sid[:8]
    return ""


def attach_argv(target):
    """The argv for `claude attach <target>`, mirroring resume_argv() above -- both are
    bare `"claude"` (no resolved-binary helper exists in this file for resume_argv() to
    share, so there's nothing to reuse here either). Returns [] if `target` is falsy, so
    a caller that got "" from attach_target() can check truthiness of ONE thing (the argv)
    rather than re-checking the target it already asked for."""
    if not target:
        return []
    return ["claude", "attach", target]
