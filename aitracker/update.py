"""In-app Update (plan addendum A.1, part B): fast-forward the running git checkout to its
branch's upstream, then restart the dashboard process in place.

The only write to the checkout is `git merge --ff-only <sha>`; there is never a stash, reset,
checkout, force or rebase. Every git call has no controlling terminal, stdin closed, prompts off,
its own process group and a timeout that kills the group. The fetched tree is smoke-tested in a
child process BEFORE the merge. Nothing here takes a value from a request: remote, branch and sha
all come from git config / rev-parse."""
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from . import config, __version__
from . import tunnel
from .pending import _pending_lock, _RUNNING

FETCH_TIMEOUT = 60            # s, git fetch
PREFLIGHT_TIMEOUT = 90        # s, import + startup smoke test of the fetched tree
_APPLY = threading.Lock()     # single-flight apply
_RESTART_ERROR = None         # str set when exec fails; surfaced in update_status()
_STARTED_AT = time.time()     # module import = process start
_HELD = None                  # {"cm": <pending lock cm>, "recover": str} while an apply owns both locks


# --------------------------------------------------------------------------- git plumbing
def _root():
    return os.path.dirname(config._HERE)


def _git_env(extra=None):
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GCM_INTERACTIVE": "never"})
    for k in [k for k in env if k in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")]:
        del env[k]                   # a hook-provided GIT_DIR must never redirect us
    if extra:
        env.update(extra)
    return env


def _kill_proc_group(p):
    try:
        if os.name == "nt":
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            p.kill()
        except OSError:
            pass


def _run(argv, timeout, env=None):
    """argv -> (rc, stdout_bytes, stderr_bytes). stdin closed, no controlling tty (own session, so
    ssh cannot read a passphrase from /dev/tty), and on timeout the whole group is killed: (None, b"", b"timeout")."""
    kw = {} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env or _git_env(), **kw)
    except OSError as e:
        return None, b"", str(e).encode()
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc_group(p)
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return None, b"", b"timeout"
    return p.returncode, out, err


def _g(*args, timeout=10):
    """git -C <root> ... -> (rc, text). rc None on timeout / spawn failure."""
    rc, out, err = _run(["git", "-C", _root(), *args], timeout)
    text = (out if rc == 0 else (err or out)).decode("utf-8", "replace").strip()
    return rc, text


def update_kind():
    """"git" | "bundle" | "package"."""
    if not os.path.isfile(os.path.join(config._HERE, "__init__.py")):
        return "bundle"
    rc, top = _g("rev-parse", "--show-toplevel")
    if rc == 0 and os.path.realpath(top) == os.path.realpath(_root()):
        return "git"
    return "package"


def _term_live():
    """Open terminals of either tier (term_* are optional modules, absent from the bundle)."""
    n = 0
    for name in ("aitracker.term_vt", "aitracker.term_run"):
        m = sys.modules.get(name)
        try:
            n += int(m._live_count()) if m is not None else 0
        except Exception:
            pass
    return n


def _recover_line(old, branch):
    return ("If the dashboard does not come back: `git -C %s checkout --detach %s` then `make serve` "
            "(you were on `%s` at `%s`)." % (_root(), old, branch or "(detached)", old))


# --------------------------------------------------------------------------- status
def update_status():
    """Body of GET /api/update. No network: behind/ahead are against the last fetch."""
    kind = update_kind()
    st = {"kind": kind, "version": __version__, "root": _root(), "branch": None, "detached": False,
          "upstream": None, "head": None, "head_subject": None, "behind": 0, "ahead": 0, "dirty": [],
          "fetched_at": None, "started_at": _STARTED_AT, "can_update": False, "reason": None,
          "terminals": _term_live(), "pending_running": _RUNNING.is_set(), "restart_error": _RESTART_ERROR}
    if kind == "bundle":
        st["reason"] = "Standalone build — regenerate with `make bundle` from a clone"
        return st
    if kind == "package":
        st["reason"] = "Installed package (version %s) — reinstall it with uv to update" % __version__
        return st
    rc, br = _g("symbolic-ref", "--short", "-q", "HEAD")
    st["branch"], st["detached"] = (br, False) if rc == 0 and br else (None, True)
    rc, head = _g("rev-parse", "HEAD")
    st["head"] = head if rc == 0 else None
    rc, subj = _g("log", "-1", "--format=%s")
    st["head_subject"] = subj if rc == 0 else None
    rc, up = _g("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    st["upstream"] = up if rc == 0 and up else None
    if st["upstream"]:
        rc, cnt = _g("rev-list", "--left-right", "--count", "@{u}...HEAD")
        if rc == 0 and len(cnt.split()) == 2:
            st["behind"], st["ahead"] = (int(x) for x in cnt.split())
    rc, gd = _g("rev-parse", "--absolute-git-dir")
    if rc == 0:
        try:
            st["fetched_at"] = int(os.path.getmtime(os.path.join(gd, "FETCH_HEAD")))
        except OSError:
            pass
    rc, porc = _g("status", "--porcelain", "--untracked-files=no")
    if rc == 0 and porc:
        st["dirty"] = [l for l in porc.splitlines() if l.strip()][:10]
    if st["detached"]:
        st["reason"] = "HEAD is detached — check out a branch first"
    elif not st["upstream"]:
        st["reason"] = "No upstream branch — set one with `git branch -u <remote>/<branch>`"
    elif st["dirty"]:
        st["reason"] = "Local edits — commit or discard local edits first"
    elif st["ahead"] > 0 and st["behind"] > 0:
        st["reason"] = "Local commits — not fast-forwardable"
    elif st["behind"] == 0:
        st["reason"] = "Up to date"
    else:
        st["can_update"] = True
    return st


# --------------------------------------------------------------------------- fetch
def update_fetch():
    """git fetch of the upstream's remote/branch only (both read from git config), then a fresh status."""
    st = update_status()
    if st["kind"] != "git" or st["detached"] or not st["upstream"]:
        return st
    b = st["branch"]
    rc, remote = _g("config", "branch.%s.remote" % b)
    rc2, merge = _g("config", "branch.%s.merge" % b)
    if rc == 0 and rc2 == 0 and remote and remote != "." and merge.startswith("refs/heads/"):
        rc, msg = _g("fetch", "--quiet", "--no-tags", remote, merge[len("refs/heads/"):], timeout=FETCH_TIMEOUT)
        out = update_status()
        if rc != 0:
            out["fetch_error"] = (msg or "fetch failed")[-400:]
        return out
    return update_status()


# --------------------------------------------------------------------------- pre-flight
_PREFLIGHT_CODE = (
    "import sys, json; sys.path.insert(0, sys.argv[1]); import aitracker.server, aitracker.cli; "
    "from aitracker import config, page; "
    "config.apply_overrides(json.load(open(sys.argv[2])) if sys.argv[2] else {}); "
    "page.build_page(); print(aitracker.__version__)")


def _safe_extract(data, dest):
    """Extract a tar (bytes) into dest, rejecting absolute / escaping members and device nodes."""
    root = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = []
        for m in tf.getmembers():
            tgt = os.path.realpath(os.path.join(root, m.name))
            if os.path.isabs(m.name) or ".." in m.name.split("/") or not (tgt == root or tgt.startswith(root + os.sep)):
                raise ValueError("unsafe path in archive: %s" % m.name)
            if m.issym() or m.islnk():
                ln = m.linkname
                base = os.path.dirname(tgt) if m.issym() else root
                lt = os.path.realpath(os.path.join(base, ln))
                if os.path.isabs(ln) or not (lt == root or lt.startswith(root + os.sep)):
                    raise ValueError("unsafe link in archive: %s" % m.name)
            elif not (m.isfile() or m.isdir()):
                raise ValueError("unsupported member in archive: %s" % m.name)
            members.append(m)
        kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(root, members=members, **kw)


def _preflight(target):
    """Smoke-test <target>'s tree in a child process: imports, the user's real config.json through
    the new validators, and the page build. Returns (ok, message). The checkout is never touched."""
    tmp = tempfile.mkdtemp(prefix="aitracker-preflight-")
    try:
        rc, out, err = _run(["git", "-C", _root(), "archive", "--format=tar", target], 60)
        if rc != 0:
            return False, "pre-flight: git archive failed: " + err.decode("utf-8", "replace")[-400:]
        try:
            _safe_extract(out, tmp)
        except (ValueError, tarfile.TarError, OSError) as e:
            return False, "pre-flight: bad archive: %s" % e
        cfg = config.CONFIG_FILE if os.path.isfile(config.CONFIG_FILE) else ""
        env = _git_env({"TRACKER_PENDING_INTERVAL": "off", "TRACKER_SCHEDULER_AUTOINSTALL": "0"})
        rc, out, err = _run([sys.executable, "-I", "-c", _PREFLIGHT_CODE, tmp, cfg], PREFLIGHT_TIMEOUT, env=env)
        if rc != 0:
            tail = "\n".join(err.decode("utf-8", "replace").strip().splitlines()[-20:])
            return False, "pre-flight of the new version failed:\n" + (tail or "timeout")
        return True, out.decode("utf-8", "replace").strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- apply
def _release_held():
    """Drop the apply lock + pending lock. Idempotent."""
    global _HELD
    h, _HELD = _HELD, None
    if h is not None:
        try:
            h["cm"].__exit__(None, None, None)
        except Exception:
            pass
        try:
            _APPLY.release()
        except RuntimeError:
            pass


def update_apply(confirm_terminals=False):
    """-> (http_code, body). Never raises. On 202 the apply lock + pending lock stay HELD until
    restart_in_place execs (or fails and releases); on any other code everything is released."""
    global _HELD
    if not _APPLY.acquire(blocking=False):
        return 409, {"error": "update already in progress"}
    cm = _pending_lock()
    try:
        got = cm.__enter__()
    except Exception as e:
        _APPLY.release()
        return 409, {"error": "could not take the scan lock: %s" % e}
    if not got:
        cm.__exit__(None, None, None)
        _APPLY.release()
        return 409, {"error": "scan in progress"}
    held = {"cm": cm, "recover": ""}
    _HELD = held
    try:
        code, body = _apply_locked(confirm_terminals, held)
    except Exception as e:                       # never raise out of apply
        code, body = 500, {"error": "update failed: %s" % e}
    if code != 202:
        _release_held()
    return code, body


def _apply_locked(confirm_terminals, held):
    st = update_fetch()
    if not st["can_update"]:
        return 409, {"error": st["reason"] or "cannot update", "reason": st["reason"]}
    rc, target = _g("rev-parse", "@{u}")       # resolved ONCE; every later step uses this sha
    rc2, old = _g("rev-parse", "HEAD")
    if rc != 0 or rc2 != 0 or not target or not old:
        return 409, {"error": "could not resolve upstream: %s" % (target if rc != 0 else old)}
    n = _term_live()
    if n > 0 and not confirm_terminals:
        return 409, {"error": "%d open terminal%s will close" % (n, "" if n == 1 else "s"),
                     "needs_confirm": True, "terminals": n}
    ok, msg = _preflight(target)
    if not ok:
        return 409, {"error": msg}
    rc, msg = _g("merge", "--ff-only", target, timeout=60)
    if rc != 0:
        return 409, {"error": "fast-forward refused: %s" % (msg or "git merge failed")}
    recover = _recover_line(old, st["branch"])
    held["recover"] = recover
    return 202, {"restarting": True, "from": old, "to": target, "recover": recover}


# --------------------------------------------------------------------------- restart
def _cloexec_all():
    """Mark every fd >= 3 close-on-exec so pty masters (inheritable after pty.fork) and the pending
    flock fd are closed by the kernel at exec."""
    try:
        fds = [int(x) for x in os.listdir("/dev/fd")]
    except (OSError, ValueError):
        try:
            fds = list(range(3, os.sysconf("SC_OPEN_MAX")))
        except (ValueError, OSError, AttributeError):
            fds = list(range(3, 256))
    for fd in fds:
        if fd >= 3:
            try:
                os.set_inheritable(fd, False)
            except OSError:
                pass


def restart_in_place(port, held=None):
    """exec the dashboard again (same PID, cwd). Called from a thread after the 202 was flushed.
    On OSError the tunnel is brought back, restart_error is recorded, the locks are released."""
    global _RESTART_ERROR
    h = held if held is not None else _HELD
    recover = (h or {}).get("recover", "")
    tunnel.stop(keep_on=True)
    os.environ["PORT"] = str(port)
    os.environ["TRACKER_NO_BROWSER"] = "1"
    os.environ.pop("TRACKER_RESTARTED", None)
    argv = getattr(sys, "orig_argv", None) or [sys.executable, "-m", "aitracker", *sys.argv[1:]]
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    if recover:
        print(recover, flush=True)
    _cloexec_all()
    try:
        os.execv(sys.executable, argv)
    except OSError as e:
        _RESTART_ERROR = str(e)
        try:
            tunnel.autostart(port, config.BIND_HOST)
        except Exception:
            pass
        _release_held()


def start_restart(port, delay=0.5):
    """Schedule restart_in_place on a daemon thread so the 202 response is flushed first."""
    t = threading.Timer(delay, restart_in_place, args=(port, _HELD))
    t.daemon = True
    t.start()
    return t
