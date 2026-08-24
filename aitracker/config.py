import os


PROJECTS = os.path.expanduser("~/.claude/projects")


_HERE = os.path.dirname(os.path.abspath(__file__))


FLAGS_FILE = os.path.join(_HERE, "flags.json")


TITLES_FILE = os.path.join(_HERE, "titles.json")


PINS_FILE = os.path.join(_HERE, "pins.json")


NOTES_FILE = os.path.join(_HERE, "notes.json")


# Where the server is actually listening, written at startup. `run()` falls back to the next
# free port when 8787 is taken, so anything outside the browser (the notes drain hook) has to
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


# TWO renderer implementations exist for the in-browser terminal (Tier 3): "grid" (default) is
# term_vt.Screen, a server-side VT100 emulator streaming parsed rows over SSE to a hand-written JS
# painter; "xterm" hands the PTY's raw bytes straight to a vendored xterm.js in the browser. This
# is a DELIBERATE exception to conventions rule 4 ("land a capability at the shared seam, never
# two forked implementations") -- see the big comment above term_vt.raw_stream() (search
# "TRACKER_TERM_RENDERER switch" in term_vt.py) for why the user chose "both, switchable" instead
# of a straight replacement, and for exactly what each path does and does not support.
# Server-owned (conventions rule 5): the client learns this from POST /api/term/pty's response or
# GET /api/term/renderer, never decides it locally. Default "grid" so nothing changes for existing
# users until they opt in; any value other than "grid"/"xterm" falls back to "grid" rather than
# breaking the terminal outright.
TERM_RENDERER = os.environ.get("TRACKER_TERM_RENDERER", "grid")
if TERM_RENDERER not in ("grid", "xterm"):
    TERM_RENDERER = "grid"
