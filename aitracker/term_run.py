"""Tier 2 — embedded command runner: allowlisted, shell-free, bounded, streamed over SSE.

What this is: a panel that runs *line-oriented* commands (`git status`, `make check`, `npm test`)
in a session's own `cwd` and streams their output into the page with colour. It is not a terminal:
append-only, no cursor addressing, no TUIs. That is Tier 3's problem, by definition.

The five properties that make it defensible — none of them are negotiable:

1. **No shell. Ever.** `pty.fork()` then `os.execvp(argv[0], argv)`, argv straight out of
   `shlex.split(cmd)`. There is no `sh -c` in this module, so there is no shell injection: `;`,
   `&&` and `|` are just argv tokens, never operators. A PTY is used only so tools emit colour.
2. **Allowlist by argv prefix** (`parse_cmd`), not by string matching — plus a refusal of any argv
   token carrying a shell metacharacter, so `git status && curl x | sh` cannot ride in behind an
   allowlisted prefix even though nothing would interpret those tokens.
3. **Bounded everywhere.** MAX_BYTES per job (truncated with a visible marker), MAX_JOBS
   concurrent (a 4th gets 429), TIMEOUT seconds then SIGKILL. Each SSE stream pins a
   ThreadingHTTPServer thread; these caps are what stop a tab-refresh loop exhausting the pool.
4. **Reap on disconnect.** Every write+flush sits inside the repo's BrokenPipeError/
   ConnectionResetError guard (conventions rule 8), and a disconnect kills the job instead of
   leaking a process. The reader thread always `waitpid`s, so no zombies.
5. **term_gate.guard() first in every route** — opt-in flag AND a configured login AND an origin
   check, because `make tunnel` can put this server on the public internet.
"""
import json
import os
import pty
import re
import select
import shlex
import signal
import socket
import struct
import threading
import time
import uuid

from . import term_gate
# Circular by design: server.py's bottom-of-file loader imports this module, and this module
# registers its routes back into server.EXTRA_GET/EXTRA_POST. Safe because those two dicts are
# created near the top of server.py, long before the loader runs.
from . import server

MAX_BYTES = 256 * 1024      # per job
MAX_JOBS = 3                # concurrent
TIMEOUT = 300               # seconds, then SIGKILL

TRUNC_MARK = b"\r\n\x1b[33m\xe2\x80\xa6 output truncated\x1b[0m\r\n"

# Argv prefixes that may run. Entries are matched against the joined first ONE or TWO argv
# elements after shlex.split -- "git" alone is not enough, "git status --short" is.
DEFAULT_ALLOW = (
    "git status", "git diff", "git log", "git branch",
    "make check", "make test", "npm test", "pytest", "ls", "cat",
)

# A shell metacharacter can never be meaningful here (there is no shell), so its presence means
# the caller is trying to smuggle something past the prefix check. Refuse rather than pass it to
# execvp as a literal argument.
_META = re.compile(r"[;&|<>`$(){}\n\r\\]")

JOBS = {}                   # id -> Job
_LOCK = threading.Lock()


def allowlist():
    """The permitted argv prefixes. TRACKER_TERM_ALLOW (comma- or newline-separated) replaces the
    default set outright; read from os.environ on every call so a test can flip it."""
    raw = os.environ.get("TRACKER_TERM_ALLOW", "").strip()
    if not raw:
        return list(DEFAULT_ALLOW)
    return [e.strip() for e in re.split(r"[,\n]", raw) if e.strip()]


def parse_cmd(cmd):
    """shlex.split + allowlist check. Returns argv. Raises ValueError if not permitted.

    THE injection test lives on this function: `git status; rm -rf /` splits to
    ['git', 'status;', 'rm', ...] -- the joined two-element prefix is 'git status;', which is not
    allowlisted -- and `git status ; rm -rf /` splits to ['git', 'status', ';', ...], whose prefix
    IS allowlisted, so the metacharacter refusal below is what stops it. Neither would actually
    execute anything (no shell), but both are refused before they get near execvp.
    """
    argv = shlex.split(cmd or "")           # unbalanced quotes raise ValueError here already
    if not argv:
        raise ValueError("empty command")
    for tok in argv:
        if _META.search(tok):
            raise ValueError("refused: shell metacharacter in %r (there is no shell here)" % tok)
    allow = set(allowlist())
    prefixes = [argv[0]]
    if len(argv) > 1:
        prefixes.append(argv[0] + " " + argv[1])
    for pre in prefixes:
        if pre in allow:
            return argv
    raise ValueError("command not allowed: %s (allowed: %s)" % (" ".join(prefixes[-1:]), ", ".join(sorted(allow))))


class Job:
    """One running (or finished) child. `buf` is the captured PTY output, capped at MAX_BYTES."""

    def __init__(self, jid=None, pid=0, fd=-1, cmd=""):
        self.id = jid or uuid.uuid4().hex[:12]
        self.pid = pid
        self.fd = fd
        self.cmd = cmd
        self.buf = bytearray()
        self.done = False
        self.rc = None
        self.truncated = False
        self.started = time.time()
        self.lock = threading.Lock()

    def feed(self, data):
        """Append PTY output. Returns False once the byte cap is hit (and kills the child then),
        so the reader loop stops. The marker is appended exactly once and is visible in the pane."""
        with self.lock:
            if self.truncated:
                return False
            room = MAX_BYTES - len(self.buf)
            if len(data) < room:
                self.buf.extend(data)
                return True
            self.buf.extend(data[:max(room, 0)])
            self.buf.extend(TRUNC_MARK)
            self.truncated = True
        self.kill()
        return False

    def kill(self):
        """SIGKILL the child if it is still ours to kill. Reaping happens in the reader thread."""
        if self.pid > 0 and not self.done:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def finish(self):
        """Close the master fd and reap the child -- always called from the reader thread, so
        waitpid happens exactly once and nothing is left as a zombie."""
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1
        if self.pid > 0:
            try:
                _, status = os.waitpid(self.pid, 0)
                self.rc = -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)
            except (ChildProcessError, OSError):
                pass
        self.done = True


def _set_winsize(fd, rows=30, cols=120):
    """Give the PTY a sane size -- without it tools wrap at 80 columns forever. Best effort."""
    try:
        import fcntl
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def spawn(cwd, argv):
    """pty.fork() + execvp in `cwd`. No shell anywhere on this path."""
    pid, fd = pty.fork()
    if pid == 0:                                    # child
        try:
            os.chdir(cwd or "/")
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = "120"
            os.environ["LINES"] = "30"
            # A PTY makes git/less think they are interactive; without these, `git log` would sit
            # in the pager forever and the job would only end at TIMEOUT.
            os.environ["PAGER"] = "cat"
            os.environ["GIT_PAGER"] = "cat"
            os.environ["GIT_TERMINAL_PROMPT"] = "0"
            os.execvp(argv[0], argv)                # <-- the only exec in this module
        except Exception:
            pass
        os._exit(127)                               # execvp only returns on failure
    _set_winsize(fd)
    job = Job(pid=pid, fd=fd, cmd=" ".join(argv))
    t = threading.Thread(target=_reader, args=(job,), daemon=True)
    t.start()
    return job


def _reader(job):
    """Drain the PTY into job.buf until EOF, cap, or TIMEOUT. Owns the reap."""
    deadline = job.started + TIMEOUT
    try:
        while True:
            if time.time() > deadline:
                job.kill()
                job.feed(b"\r\n\x1b[31m... killed after %ds (TIMEOUT)\x1b[0m\r\n" % TIMEOUT)
                break
            try:
                r, _, _ = select.select([job.fd], [], [], 0.2)
            except (OSError, ValueError):
                break
            if not r:
                continue
            try:
                data = os.read(job.fd, 65536)
            except OSError:                          # EIO on macOS/Linux == child closed the PTY
                break
            if not data:
                break
            if not job.feed(data):                   # byte cap hit; feed() already killed it
                break
    finally:
        job.finish()


def _live_count():
    return sum(1 for j in JOBS.values() if not j.done)


def _reap_old():
    """Drop finished jobs older than 10 minutes so JOBS cannot grow without bound."""
    cut = time.time() - 600
    for jid in [j.id for j in JOBS.values() if j.done and j.started < cut]:
        JOBS.pop(jid, None)


# --------------------------------------------------------------------------- routes

def status(handler, parsed):
    """GET /api/term/status -> {ok, allow:[...]}.

    Not in the original three-route table: the SPA needs *some* way to learn whether the feature
    is on, because guard() 403s are the only signal and a dead panel is worse than no panel. It
    leaks nothing a caller past guard() couldn't get by trying commands one at a time."""
    if not term_gate.guard(handler):
        return
    handler._json({"ok": True, "allow": allowlist(), "max_bytes": MAX_BYTES,
                   "max_jobs": MAX_JOBS, "timeout": TIMEOUT})


def run(handler, parsed, body):
    """POST /api/term/run {session, cmd} -> {job}. Rejection order is cheapest-first: a refused
    command never costs a registry parse, and a full job table never costs one either."""
    if not term_gate.guard(handler):
        return
    try:
        argv = parse_cmd(body.get("cmd") or "")
    except ValueError as e:
        return handler._json({"error": str(e)}, 400)
    with _LOCK:
        _reap_old()
        if _live_count() >= MAX_JOBS:
            return handler._json({"error": "too many running jobs (max %d)" % MAX_JOBS}, 429)
    sid = body.get("session") or ""
    cwd = term_gate.session_cwd(sid)
    if not cwd:
        return handler._json({"error": "no working directory for session %r" % sid}, 400)
    try:
        job = spawn(cwd, argv)
    except OSError as e:
        return handler._json({"error": "spawn failed: %s" % e}, 500)
    with _LOCK:
        JOBS[job.id] = job
    handler._json({"job": job.id, "cmd": job.cmd, "cwd": cwd})


def _peer_gone(handler):
    """True once the SSE client has closed its end.

    A write is not a reliable detector on its own: the first send after the peer disappears lands
    in the kernel buffer and only the *second* raises EPIPE, so a silent job (say `cat` with no
    input) would outlive its reader by two heartbeats. We answer `Connection: close`, so anything
    readable on this socket can only be EOF -- peek for it."""
    try:
        r, _, _ = select.select([handler.connection], [], [], 0)
        return bool(r) and handler.connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


def _write(handler, job, text):
    """One SSE write+flush inside the repo's disconnect guard (conventions rule 8). A dead client
    means the job has no audience: kill it rather than leak a process for the full TIMEOUT."""
    try:
        handler.wfile.write(text.encode())
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError):
        job.kill()
        return False


def stream(handler, parsed):
    """GET /api/term/stream?job=<id> -> text/event-stream of the job's output, then `end`."""
    if not term_gate.guard(handler):
        return
    from urllib.parse import parse_qs
    jid = parse_qs(parsed.query).get("job", [""])[0]
    job = JOBS.get(jid)
    if not job:
        return handler._json({"error": "no such job", "job": jid}, 404)
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")      # no Content-Length: the body is open-ended
        handler.end_headers()
    except (BrokenPipeError, ConnectionResetError):
        job.kill()
        return
    off, quiet = 0, time.time()
    while True:
        with job.lock:
            chunk, done = bytes(job.buf[off:]), job.done
        if chunk:
            off += len(chunk)
            quiet = time.time()
            payload = json.dumps({"b": chunk.decode("utf-8", "replace")})
            if not _write(handler, job, "data: %s\n\n" % payload):
                return
        elif done:
            _write(handler, job, "event: end\ndata: %s\n\n"
                   % json.dumps({"rc": job.rc, "truncated": job.truncated}))
            return
        else:
            if _peer_gone(handler):                      # instant: the tab closed
                job.kill()
                return
            if time.time() - quiet > 10:                 # heartbeat: keeps proxies from idling us
                quiet = time.time()                      # out, and is the backstop detector
                if not _write(handler, job, ": ping\n\n"):
                    return
            time.sleep(0.15)


def kill(handler, parsed, body):
    """POST /api/term/kill {job} -> {ok}."""
    if not term_gate.guard(handler):
        return
    job = JOBS.get(body.get("job") or "")
    if not job:
        return handler._json({"error": "no such job"}, 404)
    job.kill()
    handler._json({"ok": True})


server.EXTRA_GET["/api/term/status"] = status
server.EXTRA_GET["/api/term/stream"] = stream
server.EXTRA_POST["/api/term/run"] = run
server.EXTRA_POST["/api/term/kill"] = kill
