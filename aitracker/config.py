import os


PROJECTS = os.path.expanduser("~/.claude/projects")


_HERE = os.path.dirname(os.path.abspath(__file__))


FLAGS_FILE = os.path.join(_HERE, "flags.json")


TITLES_FILE = os.path.join(_HERE, "titles.json")


PINS_FILE = os.path.join(_HERE, "pins.json")


NOTES_FILE = os.path.join(_HERE, "notes.json")


# Fork lineage (a `claude --resume` retried with `--fork-session` because the CLI refused
# to resume a session it considers a background agent). Keyed by the PARENT session id ->
# {"at": unix-time-of-fork, "cwd": …, "child": resolved child id or "", "abandoned": bool,
#  "parent_uuids": [...], "parent_dir": …, "pre_existing": [...], "parent_ct": float|None}.
# There is no on-disk fork lineage from Claude Code itself (parentSessionId/forkedFrom don't
# exist — verified against a real transcript), so this file IS the only record linking the
# two: parent_uuids is the parent's own early-message uuid fingerprint, pre_existing is the
# exact SET of session ids already present in parent_dir at fork time (a candidate in that
# set can never be the child — the fact that replaced three rounds of a broken timestamp-
# ordering heuristic), and parent_ct is the parent transcript's own creation time (a belt-
# and-braces "child can't predate its parent" floor). All captured once, at fork time, by
# store.record_fork, and matched against candidates by store.resolve_fork_child. See
# store.py's "fork lineage" section for the full rationale. A sibling lock file (FORKS_FILE +
# ".lock") serializes concurrent read-modify-write access — see store._update_forks.
FORKS_FILE = os.path.join(_HERE, "forks.json")


# Where the server is actually listening, written at startup. `run()` falls back to the next
# free port when 8790 is taken, so anything outside the browser (the notes drain hook) has to
# be told the real one rather than assume the default.
PORT_FILE = os.path.join(_HERE, "port")


# A credential for local, non-browser callers (the notes drain hook), written at startup only
# when TRACKER_AUTH is set. Hooks are spawned by the AI tool, not by your shell, so they never
# inherit TRACKER_AUTH — without this the drain just gets a 401 and silently delivers nothing.
TOKEN_FILE = os.path.join(_HERE, "token")


AUGMENT_DIR = os.path.expanduser("~/.augment")


TASKS_DIR = os.path.expanduser("~/.claude/tasks")


EDIT_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}


LIVE_WINDOW = 300


NARRATION_CAP = 40000


NARR_PAGE = 60          # narration entries per /api/session page + per /api/narration fetch


AUGGIE_SESSIONS = os.path.join(AUGMENT_DIR, "sessions")


# Augment VSCode / Cursor extension state — one dir per workspace, containing
# `Augment.vscode-augment/augment-user-assets/{task-storage,agent-edits}/…`.
# macOS paths; overridable via env for tests / non-mac hosts. Empty = provider disabled.
VSCODE_WS_ROOT = os.environ.get(
    "TRACKER_VSCODE_WS_ROOT",
    os.path.expanduser("~/Library/Application Support/Code/User/workspaceStorage"),
)


CURSOR_WS_ROOT = os.environ.get(
    "TRACKER_CURSOR_WS_ROOT",
    os.path.expanduser("~/Library/Application Support/Cursor/User/workspaceStorage"),
)


# HTTP Basic Auth for the whole server. Empty = off (default; localhost dev unaffected).
# Set TRACKER_AUTH="user:pass" to require a login on every route — the one gate that covers
# every access path (localhost, LAN, Tailscale, ngrok), so remote viewers must authenticate.
AUTH = os.environ.get("TRACKER_AUTH", "")


# The address the server is actually bound to, written by server.run() once the real bind host
# is known (default here is the loopback fallback for anything that reads this before run() has
# executed, e.g. tests, or a caller that imports the package without ever serving). term_gate
# reads this — not a request's peer address — to decide whether TRACKER_AUTH is required: a
# tunnel terminates locally, so a request that arrived through `make tunnel` still shows up with
# a loopback peer address even though the tunnel makes the server reachable from anywhere.
BIND_HOST = "127.0.0.1"


# Terminal features (Tiers 1-3) are ON by default. Set TRACKER_TERMINAL=0 to disable them.
# They turn the tracker from a read-only viewer into something that can start processes.
# `HOST=0.0.0.0 make serve` (see cli.py's HOST env var) is a supported, documented way to reach
# this server from a LAN or over Tailscale — it is not just a `make tunnel` thing. Exposing the
# terminal that way with no TRACKER_AUTH would hand an unauthenticated, unrestricted shell to
# anyone who can reach the box, so term_gate.allowed() additionally requires TRACKER_AUTH
# whenever config.BIND_HOST is not loopback. A loopback-only `make serve` (the default) needs no
# TRACKER_AUTH, and `make tunnel` already requires TRACKER_AUTH on its own regardless.
# See term_gate.allowed() for the exact gate logic.
TERMINAL = os.environ.get("TRACKER_TERMINAL", "") != "0"


# TWO renderer implementations exist for the in-browser terminal (Tier 3): "grid" is term_vt.Screen,
# a server-side VT100 emulator streaming parsed rows over SSE to a hand-written JS painter; "xterm"
# (default) hands the PTY's raw bytes straight to a vendored xterm.js in the browser. This is a
# DELIBERATE exception to conventions rule 4 ("land a capability at the shared seam, never two
# forked implementations") -- see the big comment above term_vt.raw_stream() (search
# "TRACKER_TERM_RENDERER switch" in term_vt.py) for why the user chose "both, switchable" instead
# of a straight replacement, and for exactly what each path does and does not support.
# Server-owned (conventions rule 5): the client learns this from POST /api/term/pty's response or
# GET /api/term/renderer, never decides it locally. Default "xterm" -- it beats grid on wide
# characters (CJK/emoji -- the grid emulator treats every codepoint as one column), true colour and
# native VT fidelity, and the user has accepted its gaps (no repaint on attach/reconnect, no
# server-backed scrollback/badge/scrollbar, no mid-session server notices on the raw path).
# An unrecognised value is a DIFFERENT question from "unset": it's user/env error, not a preference,
# so it deliberately falls back to "grid" -- the safer renderer (repaint on reconnect, server-backed
# scrollback, mid-session notices) -- rather than to the now-riskier default. This is a decision,
# not an accident: don't "fix" it to match the unset default without re-reading this comment.
TERM_RENDERER = os.environ.get("TRACKER_TERM_RENDERER", "xterm")
if TERM_RENDERER not in ("grid", "xterm"):
    TERM_RENDERER = "grid"


# How many in-browser terminals (Tier 3 PTYs) may run at once. Each pins a forked child process,
# a reader thread and a Screen grid, so the cap is real -- but the whole point of this app is
# watching SEVERAL concurrent AI sessions, so 4 was well under what the machine can hold and well
# under what the user actually runs. Env-overridable (like TRACKER_TERMINAL/TRACKER_TERM_RENDERER
# above) rather than hardcoded, and clamped to [1, 64] so a typo can't uncap the box. The other
# half of this is reclaim: POST /api/term/close lets the user free a slot instead of waiting out
# term_vt.IDLE_TIMEOUT, and the 429 body lists what is holding the slots -- see term_vt.open_pty.
MAX_TERMS = 12
try:
    MAX_TERMS = max(1, min(64, int(os.environ.get("TRACKER_MAX_TERMS", MAX_TERMS))))
except (TypeError, ValueError):
    MAX_TERMS = 12
