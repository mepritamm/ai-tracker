"""Tier 2 — embedded command runner: allowlisted, shell-free, bounded, streamed over SSE.

What this is: a panel that runs *line-oriented* commands (`git status`, `make check`, `npm test`)
in a session's own `cwd` and streams their output into the page with colour. It is not a terminal:
append-only, no cursor addressing, no TUIs. That is Tier 3's problem, by definition.

The five properties that make it defensible — none of them are negotiable:

1. **No shell. Ever.** `pty.fork()` then `os.execvp(argv[0], argv)`, argv straight out of
   `shlex.split(cmd)`. There is no `sh -c` in this module, so there is no shell injection: `;`,
   `&&` and `|` are just argv tokens, never operators. A PTY is used only so tools emit colour.
2. **Allowlist by argv prefix** (`parse_cmd`), not by string matching — plus a refusal of any
   UNQUOTED shell metacharacter, so `git status && curl x | sh` cannot ride in behind an
   allowlisted prefix even though nothing would interpret those tokens.
2b. **An allowlisted prefix is not the end of the argument.** `git` will run a program that a
   working tree names for it — an external diff driver, a textconv filter, a pager, an editor —
   so a fully allowlisted `git diff` was demonstrated executing arbitrary code with no
   metacharacters and no shell. `_harden_git` injects the kill-switch flags and refuses the flags
   that would undo them; `spawn` neutralises the env-selected programs. And `cat`/`ls` would
   otherwise be an arbitrary file read as the server uid, so `check_paths` confines their path
   arguments to the session's own cwd.
3. **Bounded everywhere.** MAX_BYTES per job (a hard ceiling -- the truncation marker is counted
   inside it), MAX_JOBS concurrent children (a 4th gets 429), MAX_STREAMS concurrent SSE
   connections (the 25th gets 429), TIMEOUT seconds then SIGKILL of the whole process group. Each
   SSE stream pins a ThreadingHTTPServer thread, and bounding the CHILDREN never bounded the
   CONNECTIONS: unbounded, 900 held streams drove the process into its thread ceiling, where no
   request of any kind can get a thread -- the whole dashboard, not just this panel.
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
MAX_STREAMS = 24            # concurrent SSE connections, across all jobs
TIMEOUT = 300               # seconds, then SIGKILL

TRUNC_MARK = b"\r\n\x1b[33m\xe2\x80\xa6 output truncated\x1b[0m\r\n"

# Argv prefixes that may run. Entries are matched against the joined first ONE or TWO argv
# elements after shlex.split -- "git" alone is not enough, "git status --short" is.
DEFAULT_ALLOW = (
    "git status", "git diff", "git log", "git branch",
    "make check", "make test", "npm test", "pytest", "ls", "cat",
)

# A shell metacharacter can never be meaningful here (there is no shell), so an UNQUOTED one means
# the caller is trying to smuggle something past the prefix check. Refuse rather than pass it to
# execvp as a literal argument. A QUOTED one is ordinary text: `git log --grep="a;b"` is a real
# command, and shlex hands it over as the single inert token `--grep=a;b`.
_META_CHARS = ";&|<>`$(){}\n\r\\"


def _unquoted_meta(cmd):
    """The first shell metacharacter appearing OUTSIDE quotes in the raw command, or "".

    shlex.split() strips the quotes, so once we hold argv we can no longer tell `--grep="a;b"`
    (text a caller legitimately wants) from `; rm -rf /` (an attempt at an operator). Scan the raw
    string instead: inside a quoted run a metacharacter is just a character. This is narrower than
    the old per-token scan but not weaker -- the refusal was never the load-bearing control (the
    prefix allowlist and the absence of a shell are), it is the belt to their braces.
    """
    quote = ""
    for ch in cmd:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in _META_CHARS:
            return ch
    return ""


# The git subcommands that accept the diff-driver kill switches. `git status` and `git branch` do
# NOT ("error: unknown option `no-ext-diff'"), so this is a set, never a blanket append.
_GIT_DIFFY = ("diff", "log", "show")

# git options that make git RUN A PROGRAM of the caller's choosing, point at another repo, or
# write a file. Refused ANYWHERE in argv, not just at argv[1]: git lets the LAST occurrence win
# (measured -- `git diff --no-ext-diff --ext-diff` runs the driver again), so without this refusal
# a caller could simply re-enable what _harden_git injects.
_GIT_BANNED = ("--ext-diff", "--textconv", "--exec-path", "--upload-pack", "--receive-pack",
               "-c", "--config-env", "--git-dir", "--work-tree", "--output")

# Repo-local `.git/config` keys that name a PROGRAM for git to run, injected as `-c key=value`
# global options -- AFTER the allowlist has passed, so a caller writing `git -c ...` themselves
# still fails the prefix test -- so that the working tree's own values lose.
#
# READ THIS BEFORE TRUSTING IT. Running git inside a repository whose `.git/config` you do not
# control is CODE EXECUTION BY GIT'S OWN DESIGN, and an allowlist cannot make it otherwise. git
# has no "ignore the local config" switch (GIT_CONFIG_NOSYSTEM covers /etc/gitconfig only). What
# follows is an ENUMERATION of the exec points reachable from the allowlisted subcommands, and an
# enumeration is never proven complete.
#
# Closed here, each one demonstrated firing before the override was added:
#   core.fsmonitor   runs a program on `git status`
#   core.hooksPath   redirects hooks; `git status` fires post-index-change
#   diff.external    the repo-wide external diff driver (--no-ext-diff also kills it; belt)
#   core.pager       belt to the PAGER/GIT_PAGER env vars set in spawn()
#   core.editor      runs on `git branch --edit-description`; belt to GIT_EDITOR
#   gpg.program      runs on `git log --show-signature`, an allowlisted prefix
# Closed by argv instead: the external diff driver and textconv filter, via _harden_git's
# --no-ext-diff/--no-textconv, plus the _GIT_BANNED refusal of the flags that would undo them.
#
# NOT closed, and named rather than implied away: `filter.<name>.clean/smudge` is keyed by a
# driver NAME the tree's own .gitattributes chooses, so there is no fixed key to override;
# `core.sshCommand`, `credential.helper`, `core.gitProxy` and `uploadpack.packObjectsHook` need a
# network subcommand that is not allowlisted today, but they are one allowlist entry away.
#
# THE THREAT MODEL, plainly. The cwd comes from the user's own session logs, so this is not a
# path an anonymous caller picks. The realistic exposure is a maliciously-crafted repository the
# user has cloned, plus someone holding the tracker password -- and Tier 1 established that
# `make tunnel` can put that password on the public internet. Narrow, but real.
_GIT_SAFE_CONFIG = ("core.fsmonitor=false", "core.hooksPath=/dev/null", "diff.external=",
                    "core.pager=cat", "core.editor=true", "gpg.program=false")

JOBS = {}                   # id -> Job
_STREAMS = 0                # open SSE connections; guarded by _LOCK
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

    THE injection test lives on this function. `git status; rm -rf /` splits to
    ['git', 'status;', 'rm', ...] -- the joined two-element prefix is 'git status;', which is not
    allowlisted -- and `git status ; rm -rf /` splits to ['git', 'status', ';', ...], whose prefix
    IS allowlisted, so the unquoted-metacharacter refusal is what stops it. Neither would actually
    execute anything (no shell), but both are refused before they get near execvp.

    Three checks, in this order: the raw string must carry no unquoted metacharacter; the joined
    one- or two-element prefix must be allowlisted; and _harden_git then vets and rewrites git's
    argv, because an allowlisted `git diff` can otherwise be talked into running a program.
    Path confinement for `cat`/`ls` is check_paths -- it needs the cwd, which this does not have.
    """
    cmd = cmd or ""
    bad = _unquoted_meta(cmd)
    if bad:
        raise ValueError("refused: unquoted shell metacharacter %r (there is no shell here; "
                         "quote it if you meant it literally)" % bad)
    argv = shlex.split(cmd)                 # unbalanced quotes raise ValueError here already
    if not argv:
        raise ValueError("empty command")
    allow = set(allowlist())
    prefixes = [argv[0]]
    if len(argv) > 1:
        prefixes.append(argv[0] + " " + argv[1])
    for pre in prefixes:
        if pre in allow:
            return _harden_git(argv)
    raise ValueError("command not allowed: %s (allowed: %s)" % (" ".join(prefixes[-1:]), ", ".join(sorted(allow))))


def _harden_git(argv):
    """Refuse git's run-a-program flags and inject the diff-driver kill switches. Identity for
    everything that is not git.

    THE ATTACK THIS CLOSES. A working tree can name a program for git to run as a diff driver:
    `.git/config` `[diff "x"] command = /path/evil` selected by `.gitattributes` `*.py diff=x`, or
    `diff.external`. That is arbitrary code execution behind a fully allowlisted `git diff` -- no
    metacharacters, no shell, nothing for the prefix check or the metacharacter check to catch. It
    was demonstrated against this module before this function existed. `--no-ext-diff` kills the
    external-diff forms; `--no-textconv` kills the parallel `diff.<driver>.textconv` one, and it is
    a genuinely separate hole (measured: `--no-ext-diff` alone still runs a textconv driver).

    The flags go immediately after the subcommand, not at the end -- a trailing flag would land
    after a `--` and be read as a pathspec. Since a later occurrence beats an earlier one in git,
    the injection is only sound because _GIT_BANNED refuses the re-enabling forms outright.

    The flags are not enough on their own: `git status` accepts neither of them and yet still runs
    a program named by `core.fsmonitor` or `core.hooksPath` (both demonstrated). Those go in as
    `-c key=value` global options -- see _GIT_SAFE_CONFIG, including what it does NOT cover.
    """
    if argv[0] != "git":
        return argv
    for tok in argv[1:]:
        if tok.split("=", 1)[0] in _GIT_BANNED:
            raise ValueError("refused: git option %r can run a program, retarget the repository, "
                             "or write a file" % tok)
    safe = []
    for kv in _GIT_SAFE_CONFIG:
        safe += ["-c", kv]
    argv = argv[:1] + safe + argv[1:]       # `-c` is a GLOBAL option: before the subcommand
    sub = 1 + len(safe)
    if len(argv) > sub and argv[sub] in _GIT_DIFFY:
        return argv[:sub + 1] + ["--no-ext-diff", "--no-textconv"] + argv[sub + 1:]
    return argv


# ponytail: `cat` and `ls` are plan-approved allowlist defaults, and the plan's intent for them is
# "look at a file in the project you are already looking at". Unconfined they are also an arbitrary
# file read as the server's uid -- `cat ~/.ssh/id_rsa` parses and runs, because cat takes an
# absolute path and nothing tied it to the session. That composes badly with Tier 1's finding that
# `make tunnel` puts this server on the public internet with its requests arriving as loopback, so
# the password is the only real gate. "Anyone with the password can read your SSH keys" is not what
# the plan meant by safe by construction, so their path arguments are confined to the session's own
# cwd. This deliberately NARROWS an approved default; the feature it was for still works.
_CONFINED = ("cat", "ls")


def check_paths(argv, cwd):
    """Raise ValueError if `cat`/`ls` names a path outside `cwd`. No-op for anything else.

    realpath on BOTH sides, so a symlink inside the session pointing at ~/.ssh is caught too.
    Tokens starting with "-" are flags, not paths, and are skipped.
    """
    if not argv or argv[0] not in _CONFINED:
        return
    root = os.path.realpath(cwd or "/")
    for tok in argv[1:]:
        if tok.startswith("-"):
            continue
        target = os.path.realpath(os.path.join(root, tok))
        if target != root and not target.startswith(root + os.sep):
            raise ValueError("refused: %s resolves outside the session directory %s "
                             "(cat/ls may only read inside the session's own working tree)"
                             % (tok, root))


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
        self.viewers = 0        # open SSE connections; guarded by _LOCK, not self.lock
        self.lock = threading.Lock()

    def feed(self, data):
        """Append PTY output. Returns False once the byte cap is hit (and kills the child then),
        so the reader loop stops. The marker is appended exactly once and is visible in the pane."""
        with self.lock:
            if self.truncated:
                return False
            # The marker is counted INSIDE the budget, so MAX_BYTES is a hard ceiling on
            # len(buf) rather than a ceiling plus 33 bytes.
            room = MAX_BYTES - len(self.buf) - len(TRUNC_MARK)
            if len(data) < room:
                self.buf.extend(data)
                return True
            self.buf.extend(data[:max(room, 0)])
            self.buf.extend(TRUNC_MARK)
            self.truncated = True
        self.kill()
        return False

    def kill(self):
        """SIGKILL the child's whole PROCESS GROUP. Reaping happens in the reader thread.

        Signalling the single pid was only ever clean by accident: pty.fork() makes the child a
        session leader, so when it dies the kernel sends SIGHUP to the foreground group -- and the
        grandchildren happened to die of that. A grandchild that ignores SIGHUP (ordinary for a
        test-runner worker pool or a watcher) survived and kept running after the job was marked
        done. killpg reaches the whole group.

        Honest limit: a grandchild that calls setsid() leaves this process group entirely, and
        nothing here can follow it. Containing a deliberate daemoniser needs a sandbox this module
        does not have; what is fixed is the common case of a multi-process tree that merely
        declines to die of SIGHUP.
        """
        if self.pid > 0 and not self.done:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            try:
                os.kill(self.pid, signal.SIGKILL)       # belt, if getpgid already failed
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
            # A repo can also name an EDITOR (`core.editor`), and `git branch --edit-description`
            # -- an allowlisted prefix -- runs it. Demonstrated: it executed the repo's chosen
            # program. `true` is a no-op binary, so the editor path leads nowhere.
            os.environ["GIT_EDITOR"] = "true"
            # Honest scope: this blocks /etc/gitconfig ONLY. It does NOT block the repo-local
            # .git/config, which is where the external-diff attack actually lives -- the argv
            # flags injected by _harden_git are what close that. Set for completeness.
            os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
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
    """Drop finished jobs older than 10 minutes so JOBS cannot grow without bound.

    Called from EVERY terminal route, not just run(). When it only ran on submit, a finished job's
    buffer stayed pinned until someone happened to start another job -- "use the panel once, never
    again" held up to MAX_BYTES for the life of the process. The ceiling is still
    MAX_JOBS-in-flight plus whatever finished within the last 10 minutes; nothing sweeps in the
    background, because a daemon thread for this would be more machinery than the bound is worth.
    """
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
    with _LOCK:
        _reap_old()
    handler._json({"ok": True, "allow": allowlist(), "max_bytes": MAX_BYTES,
                   "max_jobs": MAX_JOBS, "max_streams": MAX_STREAMS, "timeout": TIMEOUT})


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
        check_paths(argv, cwd)              # needs cwd, so it cannot live in parse_cmd
    except ValueError as e:
        return handler._json({"error": str(e)}, 400)
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
    """One SSE write+flush inside the repo's disconnect guard (conventions rule 8). Returns False
    once this client is gone.

    It does NOT kill the job: killing is stream()'s job, and only once the LAST viewer has left.
    The old version killed on any writer's disconnect, so with two viewers on one job, closing one
    tab handed the other a premature `event: end` with rc=-9."""
    try:
        handler.wfile.write(text.encode())
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False


def stream(handler, parsed):
    """GET /api/term/stream?job=<id> -> text/event-stream of the job's output, then `end`.

    Two accounting jobs happen here, both under _LOCK:

    * **A slot out of MAX_STREAMS.** MAX_JOBS bounds how many CHILDREN run; nothing bounded how
      many SSE CONNECTIONS were open, and each one pins a ThreadingHTTPServer thread for its whole
      life. Measured, 900 connections held open against one job: unbounded, all 900 were accepted
      and the process plateaued at its hard thread ceiling (512 on this machine), so further
      handler threads could not start at all; with the cap, 24 are served and 876 get an immediate
      429, leaving 27 threads. A tab-refresh loop reaches those numbers on its own.
      Honest note: /api/list latency itself did NOT visibly degrade in that harness (~0.1s either
      way). The failure being prevented is thread exhaustion, not slow responses.
    * **A viewer refcount on the job.** The child is killed when the LAST viewer leaves, not the
      first: with two tabs open on one job, closing one used to hand the other `event: end` with
      rc=-9 at once. A tab refresh raced the same way.
    """
    global _STREAMS
    if not term_gate.guard(handler):
        return
    from urllib.parse import parse_qs
    jid = parse_qs(parsed.query).get("job", [""])[0]
    with _LOCK:
        _reap_old()
        job = JOBS.get(jid)
        busy = job is not None and _STREAMS >= MAX_STREAMS
        if job is not None and not busy:
            _STREAMS += 1
            job.viewers += 1
    if job is None:                                  # returns in ~5ms, holds no thread
        return handler._json({"error": "no such job", "job": jid}, 404)
    if busy:
        return handler._json({"error": "too many open output streams (max %d)" % MAX_STREAMS}, 429)
    try:
        _stream_body(handler, job)
    finally:
        with _LOCK:
            _STREAMS -= 1
            job.viewers -= 1
            last = job.viewers <= 0
        if last:                                     # no audience left: don't leak the process
            job.kill()


def _stream_body(handler, job):
    """The SSE loop itself. Returns on client disconnect or on the job's `end` event; the caller
    owns the stream slot and the viewer refcount, so this never kills anything."""
    try:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")      # no Content-Length: the body is open-ended
        handler.end_headers()
    except (BrokenPipeError, ConnectionResetError):
        return
    off, quiet = 0, time.time()
    while True:
        with job.lock:
            chunk, done = bytes(job.buf[off:]), job.done
        if chunk:
            off += len(chunk)
            quiet = time.time()
            # A multi-byte character split across two PTY reads decodes to U+FFFD here. That is
            # mojibake on one character, never an exception -- errors="replace" is the ceiling we
            # accept rather than carrying a decoder's partial state across chunks.
            payload = json.dumps({"b": chunk.decode("utf-8", "replace")})
            if not _write(handler, job, "data: %s\n\n" % payload):
                return
        elif done:
            _write(handler, job, "event: end\ndata: %s\n\n"
                   % json.dumps({"rc": job.rc, "truncated": job.truncated}))
            return
        else:
            if _peer_gone(handler):                      # instant: the tab closed
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
    with _LOCK:
        _reap_old()
        job = JOBS.get(body.get("job") or "")
    if not job:
        return handler._json({"error": "no such job"}, 404)
    job.kill()
    handler._json({"ok": True})


server.EXTRA_GET["/api/term/status"] = status
server.EXTRA_GET["/api/term/stream"] = stream
server.EXTRA_POST["/api/term/run"] = run
server.EXTRA_POST["/api/term/kill"] = kill
