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


# Terminal features (Tiers 1-3) are ON by default. Set TRACKER_TERMINAL=0 to disable them.
# They turn the tracker from a read-only viewer into something that can start processes.
# The only way to expose this server over the network is `make tunnel`, which requires TRACKER_AUTH,
# so a loopback-only `make serve` with the terminal enabled poses no additional risk.
# See term_gate.allowed() for the gate logic.
TERMINAL = os.environ.get("TRACKER_TERMINAL", "") != "0"
