# Terminal-in-the-tracker — spec + technical plan for Tiers 1–3

**Status:** plan approved for build, not yet implemented.
**Owner:** Pritam Mondal · **Written:** 2026-08-22

## Contract (verbatim)

> "I want to make this tracker into a full blown app… I am thinking of a way where I could launch
> the terminal directly from the tracker itself and work with the terminal directly from their.
> Is that something can be done? Lets first understand if thats possible"
>
> "Spec for all the Tiers and add the technical plan for each one of them, handover script with
> prompt such that I can build them parallely in 3 different sessions."

| Clause | Discharged? |
|---|---|
| Feasibility answered | ✅ yes — `pty.fork()` + `select` round-trip spiked and confirmed on this machine |
| Spec for all 3 tiers | ✅ below |
| Technical plan per tier | ✅ below (files, signatures, routes, tests, risks) |
| Handover prompts for 3 parallel sessions | ✅ §7 |
| Implementation | ❌ not started — this document is the input to that work |

## 1. Feasibility verdict

Confirmed by spike, not assumption:

```
pid, fd = pty.fork()  → exec bash → write "echo hi-from-pty" → select/read
b'...hi-from-pty\r\n...'
```

Stdlib only (`pty`, `os`, `select`, `fcntl`, `struct`, `termios`). **The server half is free.**
The cost is entirely on the browser half, and that is what separates the three tiers.

All three providers already emit `cwd` on the shared session shape
(`aitracker/providers/claude.py`, `auggie.py`, `augment_ext.py`), so the seam the tiers need
already exists. Claude's session id **is** its `--resume` id (`claude -r, --resume [value]`,
confirmed from `claude --help`).

## 2. The parallelism problem — read this before splitting the work

Naively, all three tiers touch the same four files: `server.py` (route dispatch), `page.py`
(asset inlining), `web/index.html` (panel markup), `web/app.js` (render hook). Three concurrent
sessions editing those = three-way conflicts on every landing.

**Step 0 removes every shared edit.** It is ~45 lines, landed once, before any tier starts.
After Step 0 the three tiers are **file-disjoint**: each creates only new files.

### Step 0 — shared pre-flight (land first, alone)

**0a. `aitracker/config.py`** — add the opt-in flag:

```python
# Terminal features (Tiers 1-3) are OFF unless explicitly enabled. They turn the tracker from a
# read-only viewer into something that can start processes, so they require BOTH this flag and a
# configured TRACKER_AUTH — see term_gate.allowed().
TERMINAL = os.environ.get("TRACKER_TERMINAL", "") == "1"
```

**0b. `aitracker/server.py`** — a route seam plus an optional-module loader.
Near the top, after the imports:

```python
EXTRA_GET = {}    # path -> fn(handler, parsed_url)
EXTRA_POST = {}   # path -> fn(handler, parsed_url, body)
```

In `do_GET`, immediately before the final `else: self.send_error(404)`:

```python
        elif p.path in EXTRA_GET:
            EXTRA_GET[p.path](self, p)
```

In `do_POST`, immediately before its final `else: self.send_error(404)`:

```python
        elif p.path in EXTRA_POST:
            EXTRA_POST[p.path](self, p, body)
```

At the **bottom** of `server.py` (after `class Server`), the loader:

```python
# ponytail: optional feature modules register their own routes into EXTRA_GET/EXTRA_POST on
# import. Listed by name (not globbed) so a stray file can't mount a route. A module that isn't
# present yet is skipped -- that's what lets the three terminal tiers be built in parallel.
# Ceiling: only a genuinely-absent module is swallowed; a real ImportError inside one still raises.
for _m in ("term_launch", "term_run", "term_vt"):
    try:
        __import__("%s.%s" % (__package__, _m))
    except ModuleNotFoundError as e:
        if e.name != "%s.%s" % (__package__, _m):
            raise
```

**0c. `aitracker/page.py`** — inline any per-tier asset files:

```python
def build_page():
    def read(name):
        with open(os.path.join(_WEB, name), encoding="utf-8") as fh:
            return fh.read()
    def read_ext(suffix):
        # ponytail: sorted glob so the baked page is byte-stable across restarts
        names = sorted(n for n in os.listdir(_WEB) if n.startswith("ext_") and n.endswith(suffix))
        return "\n".join(read(n) for n in names)
    html = read("index.html")
    return (html.replace("__CSS__", read("app.css") + read_ext(".css"))
                .replace("__JS__", read("app.js") + read_ext(".js")))
```

**0d. `aitracker/web/index.html`** — three empty mounts inside `<div class=body>`, right after
the `#flagcard` div:

```html
  <div id=ext_launch></div>
  <div id=ext_run></div>
  <div id=ext_vt></div>
```

**0e. `aitracker/web/app.js`** — a render hook. Near the other top-level consts:

```javascript
const EXT=[];   // feature modules (web/ext_*.js) push a fn(d); called at the end of every render
```

and as the **last statement inside `function render(d)`**:

```javascript
  EXT.forEach(f=>{try{f(d)}catch(e){console.error("ext render",e)}});
```

**0f. `aitracker/term_gate.py`** — the shared security gate, complete:

```python
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
```

**0g. `tests/test_term_gate.py`** — assert `allowed()` is False with either input missing, True
with both, and that `guard()` 403s a cross-origin POST.

**Step 0 acceptance:** `make check` prints `selfcheck ok`; `make serve` starts; the page renders
unchanged; `curl -s localhost:8787/api/term/anything` → 404 (no tier installed yet).

---

## 3. Tier 1 — Launch the real terminal

**What it is.** Two buttons on the session detail: *Open terminal here* (a Terminal/iTerm tab
already `cd`'d to the session's `cwd`) and *Resume in terminal* (same, plus `claude --resume <sid>`).

**Why it's first.** It is the literal request, it needs no emulator and no streaming, and it is
the only tier that gets you back into a live Claude session in one click.

### Files (all new except where noted)

| File | Role |
|---|---|
| `aitracker/term_launch.py` | route + AppleScript command construction |
| `aitracker/web/ext_launch.js` | the two buttons, mounted into `#ext_launch` |
| `aitracker/web/ext_launch.css` | button styling (reuse `.chip`/`.mini` tokens from `app.css`) |
| `tests/test_term_launch.py` | quoting + provider-gating assertions |

### Route

`POST /api/term/open` → body `{"session": "<sid>", "mode": "cwd"|"resume"}` → `{"ok": true}`
or `{"error": "..."}` with 400/403.

### Signatures

```python
def build_script(cwd: str, sid: str, mode: str, app: str) -> str
    """Return the AppleScript source that opens a tab and runs the command.
    Pure function -- no side effects -- so the test can assert the exact string."""

def open_terminal(handler, parsed, body) -> None   # registered into server.EXTRA_POST
```

### The rules that must not be relaxed

1. **`cwd` comes out of a log file, so it is untrusted input to a shell.** Build the inner
   command with `shlex.quote(cwd)`, then escape the whole thing for AppleScript
   (`\` → `\\`, `"` → `\"`). The test asserts a directory containing a space and a `"`.
2. **Resume is Claude-only.** Session ids are namespaced by prefix (`""` = Claude,
   `auggie:` = Auggie). Offer `mode=resume` only when the id has no prefix; other providers get
   `cwd` only. Do not guess another tool's resume flag — confirm the real CLI first.
3. **Same-machine only.** The button is useless over the tunnel (it would open a terminal on the
   *server's* Mac). `ext_launch.js` hides both buttons unless
   `location.hostname` is `localhost`/`127.0.0.1`; the route additionally refuses when
   `handler.client_address[0] != "127.0.0.1"`. State plainly in the UI copy that this is local-only.
4. **Terminal app is configurable:** `TRACKER_TERM_APP` ∈ `Terminal` (default) | `iTerm`.
   iTerm is installed on this machine; both use `do script`, with different AppleScript wrappers.

### Test (`tests/test_term_launch.py`)

- `build_script('/tmp/a b"c', "", "cwd", "Terminal")` contains the shell-quoted path and no
  unescaped `"`.
- `mode="resume"` with `sid="abc-123"` produces `claude --resume abc-123`.
- `mode="resume"` with `sid="auggie:xyz"` → raises/returns error (Claude-only).
- `guard()` refuses when `TRACKER_TERMINAL` unset.

### Effort

~15 lines of Python, ~25 of JS, ~30 of tests. Half a session.

---

## 4. Tier 2 — Embedded command runner

**What it is.** A panel that runs *line-oriented* commands (`git status`, `make check`,
`npm test`) in the session's `cwd` and streams output into the page with colour. Not a terminal —
no cursor addressing, no TUIs, append-only.

**Why it's the sweet spot.** It covers most of what you'd actually do from a dashboard, and it
needs no VT emulator.

### Files

| File | Role |
|---|---|
| `aitracker/term_run.py` | job table, PTY spawn, SSE stream, allowlist |
| `aitracker/web/ext_run.js` | command input, ANSI-SGR→spans renderer |
| `aitracker/web/ext_run.css` | output pane styling |
| `tests/test_term_run.py` | allowlist, output capture, byte cap |

### Routes

| Method | Path | Body / query | Returns |
|---|---|---|---|
| POST | `/api/term/run` | `{session, cmd}` | `{job: "<id>"}` |
| GET | `/api/term/stream` | `?job=<id>` | `text/event-stream` |
| POST | `/api/term/kill` | `{job}` | `{ok: true}` |

### Signatures

```python
MAX_BYTES = 256 * 1024      # per job
MAX_JOBS  = 3               # concurrent
TIMEOUT   = 300             # seconds, hard kill

class Job:
    id: str; pid: int; fd: int; buf: bytearray; done: bool; rc: int | None

def parse_cmd(cmd: str) -> list[str]
    """shlex.split + allowlist check. Raises ValueError if not permitted."""

def spawn(cwd: str, argv: list[str]) -> Job
def stream(handler, parsed) -> None     # SSE; registered into server.EXTRA_GET
```

### The rules that must not be relaxed

1. **No shell. Ever.** `pty.fork()` then `os.execvp(argv[0], argv)` with argv from
   `shlex.split(cmd)`. There is no `sh -c`, therefore there is no shell injection — this is what
   makes the feature defensible at all. A PTY is still used so tools emit colour.
2. **Allowlist by argv prefix, not by string matching.** Default set:
   `git status`, `git diff`, `git log`, `git branch`, `make check`, `make test`, `npm test`,
   `pytest`, `ls`, `cat`. Overridable via `TRACKER_TERM_ALLOW` (newline- or comma-separated).
   Match on the joined first one-or-two argv elements, after `shlex.split`.
3. **Bounded everywhere.** `MAX_BYTES` truncates with a visible `… output truncated` marker;
   `MAX_JOBS` rejects a 4th concurrent job with 429; `TIMEOUT` `SIGKILL`s. Each SSE stream holds
   a `ThreadingHTTPServer` thread — the caps are what stop a tab-refresh loop exhausting them.
4. **Reap on disconnect.** The SSE writer wraps every `self.wfile.write` +
   `self.wfile.flush()` in the existing `BrokenPipeError`/`ConnectionResetError` guard (rule 8),
   and on disconnect kills the job rather than leaking a process.
5. **SSE headers:** `Content-Type: text/event-stream`, `Cache-Control: no-store`,
   `Connection: close`. No `Content-Length`.

### Client rendering

`ext_run.js` handles **SGR only** (`ESC [ … m` → `<span class="a31">` etc.) and strips every
other CSI/OSC sequence. ~30 lines. Anything needing cursor movement is Tier 3's problem, by
definition.

### Test (`tests/test_term_run.py`)

- `parse_cmd("git status")` → `["git","status"]`; `parse_cmd("rm -rf /")` → `ValueError`;
  `parse_cmd("git status; rm -rf /")` → `ValueError` (shlex keeps `;` as an argv token, and
  `git status ;` is not the allowlisted prefix — assert this explicitly, it is the injection test).
- `spawn` + drain of `echo hi` yields `hi` (the Tier-2 equivalent of the feasibility spike).
- Feeding > `MAX_BYTES` truncates and sets the marker.

### Effort

~90 lines Python, ~60 JS, ~60 tests. One session.

---

## 5. Tier 3 — Real interactive terminal

**What it is.** A live PTY with a genuine screen: cursor addressing, scroll regions, alt-screen.
Enough to run `vim`, `htop`, or Claude Code's own TUI inside the dashboard.

**Why it's last and largest.** The browser needs a VT100/xterm emulator. `xterm.js` is exactly
that and is a new dependency, which this repo forbids. So the emulator goes **server-side** in
Python — which happens to fit the project's own convention (*server owns policy, client renders*)
and keeps the client at ~80 lines.

### Architecture

```
browser  ──POST /api/term/keys (base64)──►  PTY master fd  ──►  child (zsh / claude)
   ▲                                              │
   └──SSE /api/term/screen (changed rows only)── term_vt.Screen (ANSI → grid)
```

### Files

| File | Role |
|---|---|
| `aitracker/term_vt.py` | `Screen` emulator + PTY session table + routes |
| `aitracker/web/ext_vt.js` | grid painter + key capture |
| `aitracker/web/ext_vt.css` | terminal pane (JetBrains Mono is already loaded) |
| `tests/test_term_vt.py` | escape-sequence → grid assertions (the load-bearing test) |

### Routes

| Method | Path | Body / query | Returns |
|---|---|---|---|
| POST | `/api/term/pty` | `{session, cols, rows}` | `{tty: "<id>"}` |
| POST | `/api/term/keys` | `{tty, data}` (base64) | `{ok: true}` |
| POST | `/api/term/resize` | `{tty, cols, rows}` | `{ok: true}` |
| GET | `/api/term/screen` | `?tty=<id>` | SSE of `{v, rows:[[r, "text", [sgr…]]…], cursor:[r,c], alt}` |

### `Screen` — the actual work

```python
class Screen:
    def __init__(self, cols=100, rows=30): ...
    def feed(self, data: bytes) -> None
        """Parse ANSI and mutate the grid. The only entry point."""
    def snapshot(self, since: int) -> dict
        """Rows changed since version `since`, plus cursor + alt-screen flag."""
```

**In scope** (the set that makes real programs usable):
`CUP CUU CUD CUF CUB` cursor moves · `EL ED` erase · `SGR` colour/bold/reverse ·
`DECSTBM` scroll region · `IND RI NEL` index/reverse-index · alt-screen `?1049h/l` ·
`DECAWM ?7` autowrap · `DECTCEM ?25` cursor visibility · tabs · `CR LF BS`.

**Explicitly out of scope** — accept and no-op, do not silently mis-render:
mouse reporting (`?1000`–`?1006`), bracketed paste (`?2004`), sixel/graphics,
wide-character (CJK) width, and every OSC beyond title-set. Write these down in the module
docstring so the next reader knows the gaps are chosen, not missed.

### The rules that must not be relaxed

1. **Resize is `TIOCSWINSZ`, not cosmetic.** `fcntl.ioctl(fd, termios.TIOCSWINSZ,
   struct.pack("HHHH", rows, cols, 0, 0))` — without it TUIs render at 80×24 forever.
2. **Ship the emulator + its tests before wiring any route.** `Screen` is pure
   (bytes in, grid out) and therefore fully testable with no PTY, no server, no browser. Build
   and green it first; the plumbing after is mechanical.
3. **Send diffs, not screens.** A 30×100 grid re-sent at 10 fps is ~3 MB/min of JSON. Version
   counter + changed rows only.
4. **This is an unrestricted shell.** No allowlist is possible here — that is the point of the
   tier. It therefore inherits `term_gate.guard()` **and** should additionally refuse to start
   when the request did not arrive from `127.0.0.1`, unless a second explicit opt-in
   (`TRACKER_TERMINAL_REMOTE=1`) is set. Combined with `make tunnel`, the default must never be
   "internet-reachable shell".
5. Same bounds as Tier 2: max concurrent PTYs, idle timeout, kill-on-disconnect.

### Test (`tests/test_term_vt.py`)

Pure-function assertions on `Screen.feed` — no PTY needed:

- `feed(b"abc")` → row 0 is `abc`, cursor at `(0,3)`.
- `feed(b"\x1b[2J\x1b[5;10Hx")` → clear, then `x` at row 4 col 9.
- `feed(b"\x1b[31mR\x1b[0mN")` → `R` carries the red SGR, `N` carries none.
- `feed(b"\x1b[?1049h")` → `alt` True and the primary grid is preserved on `?1049l`.
- Scroll region: set `\x1b[2;5r`, emit enough `\n`, assert only rows 1–4 scrolled.
- Autowrap at the right margin.

### Effort

~350–500 lines Python (most of it `Screen`), ~80 JS, ~120 tests. Two to three sessions;
budget the emulator separately from the plumbing.

---

## 6. Cross-cutting rules for all three sessions

1. **Worktree, always.** `EnterWorktree` off local **HEAD** (there is no `origin`; the remotes are
   `personal` and `advisor360`, and advisor360 is archived). No in-place edits on the primary
   checkout — concurrent sessions share it.
2. **Restart to see anything.** `page.build_page()` bakes `web/*` at server start. After any
   `aitracker/**` or `web/**` edit, `make serve`. Only `flags/titles/pins/notes.json` are live.
3. **`make check` must print `selfcheck ok`.** Each tier adds its **own** `tests/test_term_*.py`
   file — `tests/test_selfcheck.py` is *not* edited, so there is no conflict there.
4. **Stdlib only.** No new dependencies, in Python or JS. Vendoring `xterm.js` is not an option.
5. **Don't touch `dist/tracker.py`** — it is generated by `make bundle`.
6. **Three sessions → three PRs.** This is a deliberate exception to the usual
   one-PR-per-repo-per-session rule, because you asked to build them in parallel. Land Step 0
   first, on its own, and branch all three off that commit.

### Landing order

```
Step 0  ──┬──► Tier 1  (independent)
          ├──► Tier 2  (independent)
          └──► Tier 3  (independent)
```

After Step 0 there is **no shared file** between the three tiers. Merge order does not matter.

### Security summary — the one thing not to negotiate

| Control | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| `TRACKER_TERMINAL=1` opt-in | ✅ | ✅ | ✅ |
| `TRACKER_AUTH` must be set | ✅ | ✅ | ✅ |
| Origin check on POST | ✅ | ✅ | ✅ |
| Loopback-only client | ✅ enforced | recommended | ✅ unless `TRACKER_TERMINAL_REMOTE=1` |
| No shell (`execvp` on argv) | n/a | ✅ | n/a (shell is the feature) |
| Command allowlist | n/a | ✅ | ✗ by design |
| Resource caps (bytes/jobs/timeout) | n/a | ✅ | ✅ |

`make tunnel` exists and publishes this server to the internet. Every default above assumes that
will happen by accident one day.

## 7. Handover prompts

Paste one into each fresh session. Each is self-contained.

### Prompt A — Step 0 (run this alone, first)

```
Read docs/terminal-tiers-plan.md in this repo, section "Step 0 — shared pre-flight".

Implement Step 0 exactly as specified: 0a config.py TERMINAL flag, 0b server.py EXTRA_GET/
EXTRA_POST dispatch + the optional-module loader, 0c page.py ext_* inlining, 0d index.html
three mount divs, 0e app.js EXT hook, 0f the complete aitracker/term_gate.py, 0g
tests/test_term_gate.py.

Work in a git worktree off local HEAD (no origin remote). Do not implement any tier.
Acceptance: `make check` prints "selfcheck ok"; `make serve` starts; the page renders unchanged;
`curl -s localhost:8787/api/term/anything` returns 404. Then stop and report.
```

### Prompt B — Tier 1 (start after Step 0 lands)

```
Read docs/terminal-tiers-plan.md, section "3. Tier 1 — Launch the real terminal", and
"6. Cross-cutting rules". Step 0 has already landed on main.

Implement Tier 1 only: aitracker/term_launch.py, aitracker/web/ext_launch.js,
aitracker/web/ext_launch.css, tests/test_term_launch.py. Register routes via
server.EXTRA_POST at import time — do not edit server.py, page.py, index.html or app.js.

Non-negotiable: shlex.quote the cwd then AppleScript-escape it (cwd comes from a log file and is
untrusted); resume mode is Claude-only (ids with no provider prefix); route refuses non-127.0.0.1
clients and the buttons hide off-localhost; honour term_gate.guard().

Work in a git worktree off local HEAD. `make check` must print "selfcheck ok". Verify by hand
with TRACKER_TERMINAL=1 TRACKER_AUTH=u:p make serve and clicking both buttons. Report what you
verified, including the quoting test.
```

### Prompt C — Tier 2 (start after Step 0 lands; parallel with B)

```
Read docs/terminal-tiers-plan.md, section "4. Tier 2 — Embedded command runner", and
"6. Cross-cutting rules". Step 0 has already landed on main.

Implement Tier 2 only: aitracker/term_run.py, aitracker/web/ext_run.js,
aitracker/web/ext_run.css, tests/test_term_run.py. Register routes via server.EXTRA_GET/
EXTRA_POST at import time — do not edit server.py, page.py, index.html or app.js.

Non-negotiable: NO SHELL — pty.fork() then os.execvp(argv[0], argv) with argv from shlex.split;
allowlist by argv prefix (TRACKER_TERM_ALLOW overrides the default set); MAX_BYTES / MAX_JOBS /
TIMEOUT all enforced; kill the job when the SSE client disconnects; keep the existing
BrokenPipeError/ConnectionResetError guards around every write+flush; honour term_gate.guard().

The client handles SGR only and strips all other CSI/OSC — cursor addressing is Tier 3's job.

Work in a git worktree off local HEAD. `make check` must print "selfcheck ok". The injection
assertion (`parse_cmd("git status; rm -rf /")` raises) is mandatory. Report what you verified.
```

### Prompt D — Tier 3 (start after Step 0 lands; parallel with B and C)

```
Read docs/terminal-tiers-plan.md, section "5. Tier 3 — Real interactive terminal", and
"6. Cross-cutting rules". Step 0 has already landed on main.

Implement Tier 3 only: aitracker/term_vt.py, aitracker/web/ext_vt.js, aitracker/web/ext_vt.css,
tests/test_term_vt.py. Register routes via server.EXTRA_GET/EXTRA_POST at import time — do not
edit server.py, page.py, index.html or app.js.

BUILD ORDER IS PART OF THE SPEC: implement the pure `Screen` emulator and get every assertion in
tests/test_term_vt.py green BEFORE writing a single route. Screen is bytes-in/grid-out and needs
no PTY, no server and no browser to test.

In scope: CUP/CUU/CUD/CUF/CUB, EL/ED, SGR, DECSTBM, IND/RI/NEL, alt-screen ?1049, DECAWM ?7,
DECTCEM ?25, tabs, CR/LF/BS. Out of scope (accept and no-op, and say so in the module docstring):
mouse reporting, bracketed paste, sixel, CJK width, OSC beyond title.

Non-negotiable: resize via fcntl.ioctl TIOCSWINSZ with struct.pack("HHHH", rows, cols, 0, 0);
send changed rows only with a version counter, never whole screens; honour term_gate.guard() AND
refuse non-127.0.0.1 clients unless TRACKER_TERMINAL_REMOTE=1 — `make tunnel` can put this server
on the public internet and this tier is an unrestricted shell.

Work in a git worktree off local HEAD. Stdlib only — vendoring xterm.js is not an option.
`make check` must print "selfcheck ok". Report which escape sequences you proved with tests.
```

## 8. Open decisions you may want to overrule

1. **Tier 3 at all.** It is 5–10× the cost of Tiers 1+2 combined, and Tier 1 already gets you a
   real terminal — just not *inside* the browser. If the goal is "work with the terminal", Tier 1
   may already be the answer and Tier 3 pure appetite. Recommend building 1 and 2, then deciding.
2. **Tier 2's allowlist.** It is what makes the runner safe by construction. Removing it collapses
   Tier 2 into "Tier 3 without the screen" — strictly worse than either.
3. **Auth default.** These plans require `TRACKER_AUTH`. You could instead make
   `TRACKER_TERMINAL=1` auto-generate a token. Not recommended: silent credentials are how a
   tunnel becomes a breach.

---

## ERRATA — added 2026-08-22 by the unattended build, not part of the approved plan

**§3 Tier 1 rule 3 and §5 Tier 3 rule 4 are wrong about loopback, and §2's `term_gate.py`
docstring already says why.**

Both rules prescribe refusing when `handler.client_address[0] != "127.0.0.1"` and call the
result "same-machine only". It is not. `make tunnel` runs
`cloudflared tunnel --url http://localhost:$(TUNNEL_PORT)` — cloudflared connects to the server
*over loopback*, so **every** request arriving through the public tunnel presents
`client_address[0] == "127.0.0.1"` and passes the check.

Demonstrated during the Tier 1 adversarial review with an equivalent forwarder: a request
originating at `192.168.1.5` returned `200 {"ok":true}` and fired the real `osascript`. The
client-side `location.hostname` gate hides the buttons over the tunnel but is cosmetic — `curl`
ignores it.

The `term_gate.py` docstring in §2 states this hazard correctly ("a tunnel terminates locally and
its requests also arrive from 127.0.0.1"). The tier rules then contradict it.

**Correction applied to Tier 1:** also refuse when the request carries proxy evidence
(`X-Forwarded-For`, `X-Forwarded-Host`, `Forwarded`, `CF-Connecting-IP`, `CF-Ray`, `X-Real-IP`),
keep the loopback check as a second layer, and stop claiming "local-only" in the error string.

**Correction OWED to Tier 3 before it is built:** §5 rule 4 inherits the same false premise, and
Tier 3 is an *unrestricted shell*. `TRACKER_TERMINAL_REMOTE=1` does not save it — the default
path is the broken one. Do not build Tier 3 against rule 4 as written.

**Honest residual limitation either way:** a caller on the LAN who reaches the port directly, or
a proxy that strips its own headers, still presents as loopback. Header-sniffing is a mitigation,
not a guarantee. The real gate is `TRACKER_TERMINAL=1` + `TRACKER_AUTH` — the security summary
table in §6 should be read with the "Loopback-only client ✅ enforced" cell downgraded to
"best-effort".
