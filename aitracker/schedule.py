"""OS scheduler glue for the pending-work worker: a launchd agent (macOS) or a
Task Scheduler task (Windows) that daily runs `--pending --if-due`. The job only
*asks* tick(); PENDING_INTERVAL alone decides whether a run happens.

It also holds the dashboard's own LaunchAgent (macOS, `com.aitracker.server`, the svc_* functions):
runs `python -m aitracker --service` at login on the same port as `make serve`, loopback-only and
without TRACKER_AUTH, and takes the port over when a shell-started server stops."""
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import time

from . import config

LABEL = "com.aitracker.pending"
SVC_LABEL = "com.aitracker.server"
SVC_WAIT = 5.0      # strict-port poll period while the port is busy (server.bind)
SVC_GRACE = 3.0     # strict-port quiet period before binding (a starting shell server wins)
TASK = r"ai-tracker\pending"
_TR_MAX = 261


def _root():
    return os.path.dirname(config._HERE)


def _argv():
    return [sys.executable, "-m", "aitracker", "--pending", "--if-due"]


def plist_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LABEL + ".plist")


def sched_log_path():
    return os.path.join(os.path.expanduser("~"), "Library", "Logs", "ai-tracker-pending.log")


def launchd_plist():
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": _argv(),
        "WorkingDirectory": _root(),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": _root()},
        "StartCalendarInterval": {"Hour": 10, "Minute": 0},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": sched_log_path(),
        "StandardErrorPath": sched_log_path(),
    })


def _tr(with_log=True):
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    py = pyw if os.path.exists(pyw) else sys.executable
    tr = 'cmd /c cd /d "%s" && "%s" -m aitracker --pending --if-due' % (_root(), py)
    if with_log:
        tr += ' >> "%LOCALAPPDATA%\\ai-tracker-pending.log" 2>&1'
    return tr


def schtasks_create_argv():
    tr = _tr(True)
    if len(tr) > _TR_MAX:
        tr = _tr(False)
    return ["schtasks", "/Create", "/TN", TASK, "/SC", "DAILY", "/ST", "10:00", "/F", "/TR", tr]


def _is_linked_worktree():
    return os.path.isfile(os.path.join(_root(), ".git"))


def _optout_path():
    return os.path.join(os.path.expanduser("~"), ".ai-tracker-sched-optout")


def _set_optout(on):
    """Uninstall records the opt-out, install clears it. Best effort: never raises."""
    try:
        if on:
            with open(_optout_path(), "w") as f:
                f.write("uninstalled\n")
        else:
            os.remove(_optout_path())
    except OSError:
        pass


def _under_test():
    """True in a test run or a --selfcheck. Patchable (tests flip it off to reach the later guards)."""
    argv = sys.argv or [""]
    return bool(os.environ.get("AITRACKER_NO_AUTOINSTALL") or os.environ.get("PYTEST_CURRENT_TEST")
                or "--selfcheck" in argv or "unittest" in (argv[0] or "")
                or os.path.basename(argv[0] or "").startswith("test_"))


def _is_temp(path):
    p = os.path.realpath(path)
    roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath("/tmp"), os.path.realpath("/var/folders")}
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def _target():
    return "gui/%d/%s" % (os.getuid(), LABEL)


def _read_plist():
    try:
        with open(plist_path(), "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def _sched_run(run, argv):
    """One bounded OS-scheduler call. A hang returns None (callers treat it as failure), never raises."""
    try:
        return run(argv, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return None


def sched_install(run=subprocess.run):
    plat = sys.platform
    if plat not in ("darwin", "win32"):
        print("ai-tracker: no OS scheduler support on %s. Add this crontab line yourself:\n"
              "0 10 * * * cd %s && %s -m aitracker --pending --if-due" % (plat, _root(), sys.executable))
        return 2
    if _is_linked_worktree():
        print("ai-tracker: %s is a linked git worktree and may be removed later. "
              "Install from the primary checkout." % _root())
        return 2
    if plat == "win32":
        argv = schtasks_create_argv()
        if len(argv[-1]) > _TR_MAX:
            print("ai-tracker: scheduled command exceeds %d chars; checkout path too long." % _TR_MAX)
            return 2
        r = _sched_run(run, argv)
        if r is not None and r.returncode == 0:
            _set_optout(False)
        return 0 if r is not None and r.returncode == 0 else 1
    old = _read_plist()
    if old and old.get("WorkingDirectory") not in (None, _root()):
        print("replacing job that pointed at %s" % old.get("WorkingDirectory"))
    path = plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(os.path.dirname(sched_log_path()), exist_ok=True)
    with open(path, "wb") as f:
        f.write(launchd_plist())
    os.chmod(path, 0o644)
    _sched_run(run, ["launchctl", "bootout", _target()])
    r = _sched_run(run, ["launchctl", "bootstrap", "gui/%d" % os.getuid(), path])
    if r is None or r.returncode != 0:
        try:
            os.remove(path)
        except OSError:
            pass
        print("ai-tracker: launchctl bootstrap failed (rc %s)" % (r.returncode if r is not None else "timeout"))
        return 1
    _set_optout(False)
    return 0


def sched_uninstall(run=subprocess.run):
    if sys.platform == "win32":
        _sched_run(run, ["schtasks", "/Delete", "/TN", TASK, "/F"])
    elif sys.platform == "darwin":
        _sched_run(run, ["launchctl", "bootout", _target()])
        try:
            os.remove(plist_path())
        except OSError:
            pass
    _set_optout(True)
    return 0


def sched_status(run=subprocess.run):
    st = {"kind": None, "installed": False, "last_exit": None, "root": None, "root_exists": False}
    if sys.platform == "win32":
        st["kind"] = "schtasks"
        r = _sched_run(run, ["schtasks", "/Query", "/TN", TASK])
        st["installed"] = r is not None and r.returncode == 0
        if r is None:
            st["error"] = "timeout"
        return st
    if sys.platform != "darwin":
        return st
    st["kind"] = "launchd"
    r = _sched_run(run, ["launchctl", "print", _target()])
    if r is None:
        st["error"] = "timeout"
    st["installed"] = r is not None and r.returncode == 0
    if st["installed"]:
        m = re.search(r"last exit code = (-?\d+)", r.stdout or "")
        if m:
            st["last_exit"] = int(m.group(1))
    p = _read_plist()
    if p and p.get("WorkingDirectory"):
        st["root"] = p["WorkingDirectory"]
        st["root_exists"] = os.path.isdir(st["root"])
    return st


def autoinstall_once(run=subprocess.run):
    """Server-start decision. Returns {"action": "skipped"|"present"|"installed"|"failed", "reason": str}.
    Installs only when the job is missing or its root is gone, and no opt-out is recorded. Never raises."""
    try:
        root = _root()
        if sys.platform not in ("darwin", "win32"):
            return {"action": "skipped", "reason": "no OS scheduler support on %s" % sys.platform}
        if _under_test():
            return {"action": "skipped", "reason": "test run or selfcheck"}
        if not os.path.isfile(os.path.join(config._HERE, "__init__.py")):
            return {"action": "skipped", "reason": "not a package checkout (bundle)"}
        if _is_linked_worktree() or (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in root + os.sep:
            return {"action": "skipped", "reason": "linked worktree checkout"}
        if _is_temp(root):
            return {"action": "skipped", "reason": "temp directory"}
        if os.path.exists(_optout_path()):
            return {"action": "skipped", "reason": "opted out"}
        st = sched_status(run)
        if st.get("installed") and (st.get("kind") != "launchd" or st.get("root_exists")):
            return {"action": "present", "reason": "job installed"}
        rc = sched_install(run)
        if rc == 0:
            return {"action": "installed", "reason": "repointed" if st.get("installed") else "job was missing"}
        return {"action": "failed", "reason": "install returned %s" % rc}
    except Exception as e:  # a failed install must never stop the server
        return {"action": "failed", "reason": "%s: %s" % (type(e).__name__, e)}


# --- the dashboard LaunchAgent (com.aitracker.server) -------------------------------------------------
def svc_plist_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", SVC_LABEL + ".plist")


def svc_log_path():
    return os.path.join(os.path.expanduser("~"), "Library", "Logs", "ai-tracker-server.log")


def _svc_target():
    return "gui/%d/%s" % (os.getuid(), SVC_LABEL)


def _read_svc_plist():
    try:
        with open(svc_plist_path(), "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def _svc_env(port, host):
    """Non-secret TRACKER_* + locale from the installer's env, then the keys the service needs.
    TRACKER_AUTH and anything credential-shaped is never written into the 0644 plist."""
    env = {k: v for k, v in os.environ.items()
           if (k.startswith("TRACKER_") and not re.search("AUTH|PASS|TOKEN|SECRET|KEY", k)
               and k != "TRACKER_NO_BROWSER") or k in ("LANG", "LC_ALL", "LC_CTYPE", "SHELL")}
    env.update(PATH=os.environ.get("PATH", ""), PYTHONPATH=_root(), PORT=str(int(port)), HOST=host,
               PYTHONUNBUFFERED="1")
    return env


def service_plist(port, host):
    return plistlib.dumps({
        "Label": SVC_LABEL,
        "ProgramArguments": [sys.executable, "-m", "aitracker", "--service"],
        "WorkingDirectory": _root(),
        "EnvironmentVariables": _svc_env(port, host),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "ExitTimeOut": 10,
        "StandardOutPath": svc_log_path(),
        "StandardErrorPath": svc_log_path(),
    })


def _svc_refusal(host):
    """"" when this checkout may install the dashboard service, else the reason (shown in the UI)."""
    if sys.platform != "darwin":
        return "the background service is macOS-only (launchd)"
    if not os.path.isfile(os.path.join(config._HERE, "__init__.py")):
        return "not a package checkout (bundle)"
    root = _root()
    if _is_linked_worktree() or (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in root + os.sep:
        return "%s is a linked git worktree; install from the primary checkout" % root
    if _is_temp(root):
        return "%s is a temp directory" % root
    exe = os.path.realpath(sys.executable)
    if _is_temp(exe) or (os.sep + ".claude" + os.sep + "worktrees" + os.sep) in exe or "/.cache/uv/" in exe:
        return "python %s is temporary; install with a stable interpreter (python3 -m aitracker --install-service)" % sys.executable
    if host not in ("127.0.0.1", "localhost"):
        return "HOST %s is not loopback; the service runs without TRACKER_AUTH, so it is loopback-only" % host
    return ""


def svc_install(port, host, run=subprocess.run):
    """Write the plist, bootout any loaded copy, bootstrap. 0 ok, 1 launchctl failed, 2 refused,
    3 deferred (this process IS the service: plist written; the caller must svc_spawn_deferred after replying)."""
    why = _svc_refusal(host)
    if why:
        print("ai-tracker: " + why)
        return 2
    path = svc_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(os.path.dirname(svc_log_path()), exist_ok=True)
    data = service_plist(port, host)      # serialize first: a failure must not truncate the live plist
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    if config.SERVICE:
        return 3
    argv = ["launchctl", "bootstrap", "gui/%d" % os.getuid(), path]
    _sched_run(run, ["launchctl", "bootout", _svc_target()])
    r = _sched_run(run, argv)
    if r is not None and r.returncode != 0:      # bootout can return before the old job is fully gone
        time.sleep(1)
        r = _sched_run(run, argv)
    if r is None or r.returncode != 0:
        try:
            os.remove(path)
        except OSError:
            pass
        print("ai-tracker: launchctl bootstrap failed (rc %s)" % (r.returncode if r is not None else "timeout"))
        return 1
    return 0


def svc_uninstall(run=subprocess.run):
    """0 done, 3 deferred (this process IS the service). The plist is removed first either way.
    Never touches the scheduler opt-out."""
    try:
        os.remove(svc_plist_path())
    except OSError:
        pass
    if config.SERVICE:
        return 3
    if sys.platform == "darwin":
        _sched_run(run, ["launchctl", "bootout", _svc_target()])
    return 0


def svc_spawn_deferred(reinstall, popen=subprocess.Popen):
    """Run bootout (+ bootstrap) from a detached helper that outlives this process (launchd SIGTERMs us)."""
    popen(["/bin/sh", "-c",
           'sleep 1; launchctl bootout "$1"; [ -z "$3" ] || launchctl bootstrap "$2" "$3" '
           '|| { sleep 2; launchctl bootstrap "$2" "$3"; }',
           "sh", _svc_target(), "gui/%d" % os.getuid(), svc_plist_path() if reinstall else ""],
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
          close_fds=True, start_new_session=True)


def svc_baked():
    """(port:int, host) the installed plist was written with, or None."""
    env = (_read_svc_plist() or {}).get("EnvironmentVariables") or {}
    try:
        return int(env["PORT"]), env["HOST"]
    except (KeyError, TypeError, ValueError):
        return None


def svc_status(run=subprocess.run):
    """{supported, installed, loaded, pid, state, last_exit, port, host, python, python_exists, root,
    root_exists, can_install, reason}. Never raises; no launchctl call off darwin."""
    st = {"supported": sys.platform == "darwin", "installed": False, "loaded": False, "pid": None,
          "state": None, "last_exit": None, "port": None, "host": None, "python": None,
          "python_exists": None, "root": None, "root_exists": None, "can_install": False, "reason": ""}
    try:
        baked = svc_baked()
        if baked:
            st["port"], st["host"] = baked
        if not st["supported"]:
            st["reason"] = _svc_refusal("127.0.0.1")
            return st
        p = _read_svc_plist()
        st["installed"] = p is not None
        if p:
            args = p.get("ProgramArguments") or [""]
            st["python"] = args[0]
            st["python_exists"] = os.path.exists(args[0])
            st["root"] = p.get("WorkingDirectory")
            st["root_exists"] = bool(st["root"]) and os.path.isdir(st["root"])
        r = _sched_run(run, ["launchctl", "print", _svc_target()])
        if r is None:
            st["error"] = "timeout"
        elif r.returncode == 0:
            st["loaded"] = True
            out = r.stdout or ""
            for key, rx in (("pid", r"^\s*pid = (\d+)\s*$"), ("state", r"^\s*state = (.+?)\s*$"),
                            ("last_exit", r"^\s*last exit code = (-?\d+)")):
                m = re.search(rx, out, re.M)
                if m:
                    st[key] = m.group(1).strip() if key == "state" else int(m.group(1))
        st["reason"] = _svc_refusal(st["host"] or config.BIND_HOST)
        st["can_install"] = not st["reason"]
    except Exception as e:
        st["error"] = "%s: %s" % (type(e).__name__, e)
    return st
