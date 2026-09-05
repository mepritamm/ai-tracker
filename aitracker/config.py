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
#
# DELIBERATELY env-only, forever: this is a plain module constant, not one of the
# config.json-overridable settings below, and it is NOT in EDITABLE/VALIDATORS — POST
# /api/config rejects "TRACKER_AUTH" outright (server.py checks against config.EDITABLE).
# Writing a password typed into a web form into a plaintext JSON file on disk, on a server
# that may be reachable over a tunnel, is a real security regression, not a convenience —
# the Config dialog only ever shows "set" / "not set" for this row, same as before.
AUTH = os.environ.get("TRACKER_AUTH", "")


# The address the server is actually bound to, written by server.run() once the real bind host
# is known (default here is the loopback fallback for anything that reads this before run() has
# executed, e.g. tests, or a caller that imports the package without ever serving). term_gate
# reads this — not a request's peer address — to decide whether TRACKER_AUTH is required: a
# tunnel terminates locally, so a request that arrived through `make tunnel` still shows up with
# a loopback peer address even though the tunnel makes the server reachable from anywhere.
BIND_HOST = "127.0.0.1"


# =============================================================================
# Runtime settings editable from the browser — config.json overrides
# =============================================================================
#
# The product owner asked for a Config dialog that can actually WRITE settings, not just
# display them. Precedence for every key below: config.json (if the key is present there)
# > environment variable (if set) > built-in default.
#
# Ownership split (per CLAUDE.md/conventions.md — store.py belongs to another agent): this
# module holds the PATH constant, the allowlist, the validators and the pure resolve
# functions, but NEVER touches store.py or the filesystem itself — config.json is read/
# written by server.py, which already imports store's `_load_json`/`_save_json` at its own
# top level (same as every other app-owned file: flags.json/titles.json/pins.json/
# notes.json). server.py loads the current config.json dict once per request and hands it
# to the functions below as an explicit `overrides` argument — config.py stays a plain,
# dependency-free module (only `os`), which matters for two concrete reasons:
#   1. `make bundle` flattens the whole package into one standalone file and asserts the
#      result contains no leftover relative-import lines (tests/test_integration.py). A
#      relative import anywhere in this file — even indented, inside a function body,
#      where bundle.py's strip-top-level-imports regex can't reach it — would survive
#      into dist/tracker.py and break it.
#   2. tests/test_term_vt.py's `test_max_terms_env_parsing_and_clamp` execs this file's
#      SOURCE into a bare namespace with no package context ("config.py imports nothing but
#      os" is a load-bearing assumption stated right there) to unit-test MAX_TERMS's
#      env-parsing in isolation. A relative import at this module's top level would break
#      under that legitimate technique too.
#   3. (bonus, not the reason above but confirmed while investigating both) a top-level
#      importing store here is also a genuine, order-dependent circular import:
#      store.py's own top level imports config right back, so whichever of the two
#      modules some caller happens to import FIRST decides whether the cycle resolves —
#      reproduced directly: importing `aitracker.store` before `aitracker.config` raises
#      "cannot import name ... from partially initialized module" the instant config.py
#      tries to pull a name from store at ITS top level.
#
# LIVE_WINDOW, TERM_RENDERER, MAX_TERMS and TERMINAL stay ordinary, freely-reassignable
# module globals — NOT a PEP 562 dynamic attribute. That design was tried and reverted:
# this codebase's existing test suite has ~15 files that repoint these directly
# (`config.TERMINAL = True`, `config.MAX_TERMS = 3`, `config.TERM_RENDERER = "grid"`) and
# restore them in tearDown — the same idiom this file's own BIND_HOST already uses — and
# the instant any of them does a plain assignment, normal attribute lookup would win over a
# module `__getattr__` for the rest of the process, permanently shadowing the dynamic
# resolver. Repointing the plain global directly (via `apply_overrides` below, called by
# server.py) is exactly what those tests already do by hand, so every EXISTING call site
# that reads `config.TERMINAL` / `config.TERM_RENDERER` / `config.MAX_TERMS`
# (term_gate.py, term_vt.py — both read the attribute fresh on every call, confirmed by
# reading them) sees a browser-made change on its very next read, with zero changes to
# those two files.
#
# LIVE_WINDOW's OTHER consumers (overview.py, util.py, providers/claude.py,
# providers/auggie.py) all import LIVE_WINDOW directly out of config — a name binding evaluated
# once, at THEIR OWN import time, which is a fixed snapshot regardless of how live this
# module's own global is. That is unchanged by this feature (those files are out of scope
# here) — LIVE_WINDOW is live for any caller that reads `config.LIVE_WINDOW` fresh (which is
# exactly what GET /api/config does), but not retroactively for those four already-frozen
# imports.
#
# TERM_APP / TERM_ALLOW are a different shape again: term_launch.py / term_run.py read
# `os.environ.get("TRACKER_TERM_APP"/"TRACKER_TERM_ALLOW", ...)` directly on every call —
# never through config.py at all. The only way to make a config.json override reach them
# without editing those two files is to mirror the resolved value straight into os.environ
# (see `resolve_term_app`/`resolve_term_allow` below) the moment it's resolved — os.environ
# .get() then sees it on the very next call, because those two functions already re-read
# os.environ every time.
#
# PORT / HOST are recorded here (and validated/writable via POST /api/config) for a single
# source of truth and for display, but rebinding a LIVE listening socket is out of scope (the
# task explicitly says so) — they only take effect on the next process start, and even then
# only if that start also has the env var set: cli.py's own startup path reads `PORT`/`HOST`
# from os.environ directly and is not touched by this change (out of this feature's file
# scope).
#
# TRACKER_AUTH (config.AUTH, above) is DELIBERATELY EXCLUDED from all of this — see the
# comment beside it.

CONFIG_FILE = os.path.join(_HERE, "config.json")

# The one true list of writable keys -- POST /api/config (server.py) validates against
# VALIDATORS (below) using exactly this key set, and GET /api/config reports exactly these.
# TRACKER_AUTH is deliberately not a member.
EDITABLE = ("LIVE_WINDOW", "TERM_RENDERER", "MAX_TERMS", "TERMINAL",
            "TERM_APP", "TERM_ALLOW", "PORT", "HOST", "ICON_STYLE", "ICON_SCALE")

# Keys that only bind at process startup -- the dialog labels these "takes effect on
# restart" and never claims a live apply for them.
# TERMINAL joins PORT/HOST here per doc 04's Config table ("Terminal enabled | toggle |
# TRACKER_TERMINAL | yes") -- the one row in that table marked Restart=yes besides
# Auth/Port/Host. Note this is a UI/doc contract, not a claim that the attribute
# resolution above is non-live (it is: term_gate.py rereads config.TERMINAL on every
# request, per the comment above) -- the restart note is what the product spec calls for
# on this row regardless.
RESTART_REQUIRED = frozenset({"PORT", "HOST", "TERMINAL"})


def _v_bool(v):
    return (True, bool(v)) if isinstance(v, bool) else (False, None)


def _v_int(lo, hi):
    def fn(v):
        # bool is a subclass of int in Python -- exclude it explicitly, or True/False would
        # silently pass as 1/0.
        if isinstance(v, bool) or not isinstance(v, int):
            return False, None
        return (True, v) if lo <= v <= hi else (False, None)
    return fn


def _v_enum(choices):
    def fn(v):
        return (True, v) if v in choices else (False, None)
    return fn


def _v_str(max_len):
    def fn(v):
        return (True, v) if isinstance(v, str) and len(v) <= max_len else (False, None)
    return fn


# server.py's POST /api/config handler validates the incoming {key, value} against this
# BEFORE writing config.json -- a bad or out-of-range value is rejected with 400 and never
# reaches disk. Each validator takes the raw JSON value and returns (ok, coerced).
VALIDATORS = {
    "LIVE_WINDOW":   _v_int(5, 24 * 3600),      # 5s .. 24h -- a threshold of 0 or negative is nonsensical
    "TERM_RENDERER": _v_enum(("grid", "xterm")),
    "MAX_TERMS":     _v_int(1, 64),             # same clamp term_vt.py has always enforced
    "TERMINAL":      _v_bool,
    "TERM_APP":      _v_enum(("Terminal", "iTerm")),
    "TERM_ALLOW":    _v_str(4000),              # one argv prefix per line; a generous cap, not a real limit
    "PORT":          _v_int(1, 65535),
    "HOST":          _v_str(255),
    "ICON_STYLE":    _v_enum(("icons", "emoji", "text")),
    # Percent int, not a float: it fits the existing _v_int validator and the existing
    # integer slider control in the Config dialog with zero new machinery. 75..200% covers
    # "a bit smaller" to "twice as big" without letting a typo shrink icons to nothing or
    # blow up the layout.
    "ICON_SCALE":    _v_int(75, 200),
}

# The real env var name backing each key, where one exists (LIVE_WINDOW never had one).
_ENV_NAME = {
    "TERM_RENDERER": "TRACKER_TERM_RENDERER",
    "MAX_TERMS": "TRACKER_MAX_TERMS",
    "TERMINAL": "TRACKER_TERMINAL",
    "TERM_APP": "TRACKER_TERM_APP",
    "TERM_ALLOW": "TRACKER_TERM_ALLOW",
    "PORT": "PORT",
    "HOST": "HOST",
}

# TERM_APP/TERM_ALLOW's *real* env var, captured ONCE at this module's own first import --
# i.e. the value the process actually started with, before this feature ever mutates
# os.environ to mirror an override into it (see resolve_term_app/resolve_term_allow below).
# Restoring THIS when an override is cleared (rather than just deleting the key) means a
# user who genuinely launched with `TRACKER_TERM_APP=iTerm make serve` doesn't lose that
# when a browser override is cleared -- only this feature's own mutation is undone.
_ORIG_ENVIRON = {name: os.environ.get(name) for name in ("TRACKER_TERM_APP", "TRACKER_TERM_ALLOW")}


def _env_backed(key, valid, default, overrides):
    """Effective value for a setting whose ONLY real consumer(s) read os.environ directly
    (TERM_APP -> term_launch.py, TERM_ALLOW -> term_run.py -- neither goes through config.py).
    Resolves config.json > env > default same as everything else, AND mirrors the winning
    value into os.environ so the next call those two files make already sees it -- see the
    big module comment above for why this is the only lever available without editing them.
    `valid`: a tuple of acceptable values, or None for "any string is fine" (TERM_ALLOW).
    `overrides`: the CALLER's already-loaded config.json dict (see the module comment for
    why this function never loads it itself)."""
    env_name = _ENV_NAME[key]
    d = overrides
    if key in d and (valid is None or d[key] in valid):
        val = d[key]
        os.environ[env_name] = str(val)
        return val
    # no override (or an invalid one) -- fall back to the env var this PROCESS actually
    # started with, not to whatever a previous call here may have mutated os.environ to.
    orig = _ORIG_ENVIRON.get(env_name)
    val = orig if orig is not None else default
    if valid is not None and val not in valid:
        val = default
    if orig is None:
        os.environ.pop(env_name, None)
    else:
        os.environ[env_name] = orig
    return val


def resolve_terminal(overrides):
    """Terminal features (Tiers 1-3) are ON by default. Set TRACKER_TERMINAL=0 to disable
    them. They turn the tracker from a read-only viewer into something that can start
    processes. `HOST=0.0.0.0 make serve` (see cli.py's HOST env var) is a supported,
    documented way to reach this server from a LAN or over Tailscale — it is not just a
    `make tunnel` thing. Exposing the terminal that way with no TRACKER_AUTH would hand an
    unauthenticated, unrestricted shell to anyone who can reach the box, so
    term_gate.allowed() additionally requires TRACKER_AUTH whenever config.BIND_HOST is not
    loopback. A loopback-only `make serve` (the default) needs no TRACKER_AUTH, and `make
    tunnel` already requires TRACKER_AUTH on its own regardless. See term_gate.allowed() for
    the exact gate logic. Now config.json-overridable: config.json > TRACKER_TERMINAL > on."""
    if "TERMINAL" in overrides and isinstance(overrides["TERMINAL"], bool):
        return overrides["TERMINAL"]
    return os.environ.get("TRACKER_TERMINAL", "") != "0"


def resolve_term_renderer(overrides):
    """TWO renderer implementations exist for the in-browser terminal (Tier 3): "grid" is
    term_vt.Screen, a server-side VT100 emulator streaming parsed rows over SSE to a
    hand-written JS painter; "xterm" (default) hands the PTY's raw bytes straight to a
    vendored xterm.js in the browser. This is a DELIBERATE exception to conventions rule 4
    ("land a capability at the shared seam, never two forked implementations") -- see the
    big comment above term_vt.raw_stream() (search "TRACKER_TERM_RENDERER switch" in
    term_vt.py) for why the user chose "both, switchable" instead of a straight replacement,
    and for exactly what each path does and does not support. Server-owned (conventions rule
    5): the client learns this from POST /api/term/pty's response or GET
    /api/term/renderer, never decides it locally. Default "xterm" -- it beats grid on wide
    characters (CJK/emoji -- the grid emulator treats every codepoint as one column), true
    colour and native VT fidelity, and the user has accepted its gaps (no repaint on
    attach/reconnect, no server-backed scrollback/badge/scrollbar, no mid-session server
    notices on the raw path). An unrecognised env value is a DIFFERENT question from
    "unset": it's user/env error, not a preference, so it deliberately falls back to "grid"
    -- the safer renderer -- rather than to the now-riskier default; this is a decision, not
    an accident. Now config.json-overridable: a browser-set override is validated against
    the same ("grid","xterm") set and takes top priority; the env-invalid-falls-back-to-
    "grid" behaviour is preserved exactly for the no-override case, unchanged from the
    original."""
    if "TERM_RENDERER" in overrides and overrides["TERM_RENDERER"] in ("grid", "xterm"):
        return overrides["TERM_RENDERER"]
    v = os.environ.get("TRACKER_TERM_RENDERER", "xterm")
    return v if v in ("grid", "xterm") else "grid"


def resolve_max_terms(overrides):
    """How many in-browser terminals (Tier 3 PTYs) may run at once. Each pins a forked child
    process, a reader thread and a Screen grid, so the cap is real -- but the whole point of
    this app is watching SEVERAL concurrent AI sessions, so 12 was well under what the
    machine can hold and well under what the user actually runs. Clamped to [1, 64] so a
    typo can't uncap the box. The other half of this is reclaim: POST /api/term/close lets
    the user free a slot instead of waiting out term_vt.IDLE_TIMEOUT, and the 429 body lists
    what is holding the slots -- see term_vt.open_pty. Now config.json-overridable -- same
    [1, 64] clamp applies to a browser-set override too (server.py's validator also enforces
    this range before it's ever written, so a bad value never reaches this function)."""
    if "MAX_TERMS" in overrides:
        try:
            return max(1, min(64, int(overrides["MAX_TERMS"])))
        except (TypeError, ValueError):
            pass
    try:
        return max(1, min(64, int(os.environ.get("TRACKER_MAX_TERMS", 12))))
    except (TypeError, ValueError):
        return 12


def resolve_live_window(overrides):
    """LIVE_WINDOW never had an env var backing it -- config.json > built-in default (300s).
    See the module comment above for which consumers actually see this live vs. which
    snapshotted the old plain constant at their own import time."""
    if "LIVE_WINDOW" in overrides:
        try:
            return max(5, int(overrides["LIVE_WINDOW"]))
        except (TypeError, ValueError):
            pass
    return 300


def resolve_term_app(overrides):
    return _env_backed("TERM_APP", ("Terminal", "iTerm"), "Terminal", overrides)


def resolve_term_allow(overrides):
    return _env_backed("TERM_ALLOW", None, "", overrides)


def resolve_port(overrides):
    if "PORT" in overrides:
        try:
            return int(overrides["PORT"])
        except (TypeError, ValueError):
            pass
    try:
        return int(os.environ.get("PORT", 8790))
    except (TypeError, ValueError):
        return 8790


def resolve_host(overrides):
    if "HOST" in overrides and isinstance(overrides["HOST"], str) and overrides["HOST"]:
        return overrides["HOST"]
    return os.environ.get("HOST", "127.0.0.1") or "127.0.0.1"


def resolve_icon_style(overrides):
    """How the SPA renders UI icons: "icons" (the sprite -- see the icon-conversion work),
    "emoji" (the old glyphs), or "text" (a plain-text fallback). No env var backs this --
    config.json > built-in default, same as LIVE_WINDOW. Default "icons" is deliberately
    what the app already renders today, so an unconfigured install's appearance doesn't
    change under this feature."""
    if "ICON_STYLE" in overrides and overrides["ICON_STYLE"] in ("icons", "emoji", "text"):
        return overrides["ICON_STYLE"]
    return "icons"


def resolve_icon_scale(overrides):
    """Icon size as an integer percent of the sprite's native size (75..200). No env var --
    config.json > built-in default. Default 100 is exactly today's size, so an unconfigured
    install's appearance doesn't change under this feature."""
    if "ICON_SCALE" in overrides:
        try:
            v = int(overrides["ICON_SCALE"])
            if 75 <= v <= 200:
                return v
        except (TypeError, ValueError):
            pass
    return 100


_RESOLVERS = {
    "LIVE_WINDOW": resolve_live_window,
    "TERM_RENDERER": resolve_term_renderer,
    "MAX_TERMS": resolve_max_terms,
    "TERMINAL": resolve_terminal,
    "TERM_APP": resolve_term_app,
    "TERM_ALLOW": resolve_term_allow,
    "PORT": resolve_port,
    "HOST": resolve_host,
    "ICON_STYLE": resolve_icon_style,
    "ICON_SCALE": resolve_icon_scale,
}

# The four keys that ALSO exist as a plain, freely-reassignable module attribute (see the
# big module comment above for why these four specifically, and why a PEP 562 dynamic
# attribute was reverted in favour of this).
_PLAIN_ATTR_KEYS = ("LIVE_WINDOW", "TERM_RENDERER", "MAX_TERMS", "TERMINAL")

# Seeded here from env/default ONLY (an explicit `{}`, never a file read) -- this module has
# no filesystem access of its own (see the big comment above), so at its own import time
# there is no config.json to consult yet regardless. A pre-existing config.json override is
# folded in by `apply_overrides()` below, called by server.py once at real startup and again
# on every GET/POST /api/config.
LIVE_WINDOW = resolve_live_window({})
TERM_RENDERER = resolve_term_renderer({})
MAX_TERMS = resolve_max_terms({})
TERMINAL = resolve_terminal({})


def apply_overrides(overrides):
    """Given the CURRENT config.json content (`overrides` -- the caller, server.py, reads it
    via store._load_json(CONFIG_FILE, {}); config.py never touches store, see the module
    comment above), repoint the plain LIVE_WINDOW/TERM_RENDERER/MAX_TERMS/TERMINAL globals
    and refresh the TERM_APP/TERM_ALLOW os.environ mirror. Called by server.py at real
    startup (run()) and at the top of every GET/POST /api/config, so both a browser-made
    change and a hand-edited config.json apply immediately, no restart, without this module
    ever reading the file itself."""
    for key in _PLAIN_ATTR_KEYS:
        globals()[key] = _RESOLVERS[key](overrides)
    resolve_term_app(overrides)     # side effect only here: mirrors into os.environ
    resolve_term_allow(overrides)   # ditto


def get(key, overrides):
    """Effective value of an EDITABLE key, given the config.json content the CALLER already
    loaded (`overrides`). LIVE_WINDOW/TERM_RENDERER/MAX_TERMS/TERMINAL read the plain module
    attribute directly (globals()[key]) -- exactly what term_gate.py/term_vt.py already do
    -- so this reports precisely what those call sites would see, including a value a test
    repointed directly for its own purposes. TERM_APP/TERM_ALLOW/PORT/HOST have no such
    attribute and are resolved fresh from `overrides` instead."""
    if key in _PLAIN_ATTR_KEYS:
        return globals()[key]
    return _RESOLVERS[key](overrides)


def snapshot(overrides):
    """Every editable key's current effective value, whether config.json currently overrides
    it, and whether it needs a restart to apply -- the whole body of GET /api/config
    (server.py, which loads `overrides` once via store._load_json and should call
    apply_overrides(overrides) first -- see that function's docstring)."""
    return {
        key: {
            "value": get(key, overrides),
            "overridden": key in overrides,
            "restart": key in RESTART_REQUIRED,
        }
        for key in EDITABLE
    }


# =============================================================================
# Tunnel management (Config dialog "Tunnel" section)
# =============================================================================
#
# Investigation first (per the task this section came from): grepping the whole tree for
# tunnel/cloudflare/tailscale/ngrok turns up plenty of talk about the tunnel (term_gate.py,
# term_vt.py, term_launch.py, docs/remote-access.md, this file's own AUTH/BIND_HOST
# comments) but no STORED tunnel URL anywhere -- because there is nowhere for one to live.
# `make tunnel` (see the Makefile) shells out to `cloudflared tunnel --url
# http://localhost:$(TUNNEL_PORT)`, which mints a brand-new random
# `https://<word>-<word>.trycloudflare.com` address on every single run and prints it to a
# log file the Makefile then greps -- this Python process never sees that URL, has no way
# to ask cloudflared for it, and it changes on every restart regardless. So TUNNEL_URL below
# is plain user-entered data, no different in kind from a note or a title: the user tells
# the app what its own address currently is, purely so the Config dialog can display it and
# build the share URL. There is no resolver chain (env > default) for it the way PORT/HOST
# have one -- config.json is the only source, default "".
#
# TUNNEL_USER/TUNNEL_PASS are deliberately NOT a second credential concept. `make tunnel`
# refuses to start without TRACKER_AUTH ("the tunnel URL is public" -- see the Makefile), so
# the tunnel's login already IS TRACKER_AUTH, "user:pass" split on the first colon (see AUTH
# above). These two keys let the browser stage an edit to that credential's constituent
# parts and have it persist across dialog close/reopen, WITHOUT touching the live
# config.AUTH global -- AUTH stays env-only, forever, exactly as its own comment says.
# Editing here only stages a value; it takes effect the next time the process starts, when
# the user runs the restart command this feature hands them (which passes the edited value
# as TRACKER_AUTH on the command line -- see tunnel_restart_command below). Precedence when
# no override is staged: fall back to splitting the CURRENT config.AUTH, so the dialog's
# first paint shows "what's actually active" rather than blank fields next to a padlock
# that's already unlocked.
#
# Kept OUT of EDITABLE/VALIDATORS/_RESOLVERS above and given their own dedicated routes in
# server.py (GET /api/tunnel, GET /api/tunnel/reveal, POST /api/tunnel) rather than folding
# into the general POST /api/config -- so a credential can never be read back through the
# general config snapshot route (GET /api/config), only through the one deliberate reveal
# endpoint. tests/test_selfcheck.py already asserts `"TRACKER_AUTH" not in config.EDITABLE`;
# this feature does not touch that tuple at all, so that invariant is untouched.

TUNNEL_EDITABLE = ("TUNNEL_URL", "TUNNEL_USER", "TUNNEL_PASS")


def _v_tunnel_url(v):
    if not isinstance(v, str) or len(v) > 2000:
        return False, None
    if v == "" or v.startswith("http://") or v.startswith("https://"):
        return True, v
    return False, None


def _v_tunnel_user(v):
    # No ':' -- that's the user/pass separator in the "user:pass" HTTP Basic credential
    # (see AUTH above); a username containing one would make the round trip through
    # TRACKER_AUTH="user:pass" ambiguous on the way back out. This is the "malformed
    # user:pass" rejection the feature's own tests pin down.
    if not isinstance(v, str) or len(v) > 200 or ":" in v:
        return False, None
    return True, v


TUNNEL_VALIDATORS = {
    "TUNNEL_URL": _v_tunnel_url,
    "TUNNEL_USER": _v_tunnel_user,
    "TUNNEL_PASS": _v_str(500),
}


def resolve_tunnel_url(overrides):
    v = overrides.get("TUNNEL_URL")
    return v if isinstance(v, str) else ""


def resolve_tunnel_user(overrides):
    if "TUNNEL_USER" in overrides and isinstance(overrides["TUNNEL_USER"], str):
        return overrides["TUNNEL_USER"]
    return AUTH.split(":", 1)[0] if AUTH else ""


def resolve_tunnel_pass(overrides):
    if "TUNNEL_PASS" in overrides and isinstance(overrides["TUNNEL_PASS"], str):
        return overrides["TUNNEL_PASS"]
    return AUTH.split(":", 1)[1] if ":" in AUTH else ""


def tunnel_public(overrides):
    """The Config dialog's default, no-secrets-in-the-response read (GET /api/tunnel): the
    URL (not sensitive) plus only WHETHER a user/password are set -- never the values
    themselves, and never fabricated when unset. See tunnel_reveal for the one deliberate
    route that returns the raw credential."""
    return {
        "url": resolve_tunnel_url(overrides),
        "user_set": bool(resolve_tunnel_user(overrides)),
        "pass_set": bool(resolve_tunnel_pass(overrides)),
        "auth_set": bool(AUTH),
    }


# Safe-without-encoding characters for a URL userinfo component (RFC 3986 unreserved set).
_USERINFO_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _pct_encode(s):
    """Percent-encode `s` for safe use inside a URL userinfo component. config.py imports
    nothing but os (see the big module comment up top -- an earlier attempt to add a second
    import here broke both `make bundle`'s self-containment check and a test that execs this
    file's source into a bare namespace), so this hand-rolls the dozen lines
    urllib.parse.quote would otherwise cover rather than adding an import just for it."""
    out = []
    for ch in s:
        if ch in _USERINFO_SAFE:
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append("%%%02X" % b)
    return "".join(out)


def share_url(url, user, password):
    """The standard `https://user:pass@host/...` userinfo form -- never a query string,
    which is where credentials leak into server logs and browser history most readily.
    Strips any userinfo already present in `url` (a user who pasted one in by hand) before
    adding the real one -- only within the authority part of the URL, so a literal '@'
    further into the path is left alone. Returns "" when there is no URL to build on."""
    if not url:
        return ""
    sep = "://"
    i = url.find(sep)
    if i == -1:
        scheme, rest = "https://", url
    else:
        scheme, rest = url[:i + len(sep)], url[i + len(sep):]
    slash = rest.find("/")
    if slash == -1:
        authority, tail = rest, ""
    else:
        authority, tail = rest[:slash], rest[slash:]
    at = authority.find("@")
    if at != -1:
        authority = authority[at + 1:]
    userinfo = _pct_encode(user or "")
    if password:
        userinfo += ":" + _pct_encode(password)
    if not userinfo:
        return scheme + authority + tail
    return scheme + userinfo + "@" + authority + tail


def _shq(s):
    """POSIX single-quote shell-escaping -- safe for any byte a credential might contain
    (unlike double quotes, which still let $ and backticks expand inside them)."""
    return "'" + s.replace("'", "'\\''") + "'"


def tunnel_restart_command(user, password):
    """The exact command the Makefile's `tunnel` target expects (see Makefile: it refuses to
    start without TRACKER_AUTH set in the environment -- "the tunnel URL is public" -- then
    runs `PORT=$(TUNNEL_PORT) HOST=127.0.0.1 nohup python3 -m aitracker` plus cloudflared).
    This is the common case -- a user working with `make`/`make tunnel` -- not a hand-rolled
    invocation; the Config dialog's own footnote next to this states that plainly rather
    than silently assuming it."""
    return "TRACKER_AUTH=%s make tunnel" % _shq(user + ":" + password)


def tunnel_reveal(overrides):
    """The ONE deliberate route allowed to return the raw credential (server.py's GET
    /api/tunnel/reveal) -- reached only by an explicit user action (the dialog's Show
    button), never the default read. Bundles the restart command and share URL alongside it
    since both already embed the same raw values and there is no secrecy tier below "the
    user asked to see it"."""
    user = resolve_tunnel_user(overrides)
    pw = resolve_tunnel_pass(overrides)
    url = resolve_tunnel_url(overrides)
    return {
        "user": user,
        "pass": pw,
        "restart_cmd": tunnel_restart_command(user, pw),
        "share_url": share_url(url, user, pw),
    }
