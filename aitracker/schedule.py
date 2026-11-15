"""OS scheduler glue for the pending-work worker: a launchd agent (macOS) or a
Task Scheduler task (Windows) that daily runs `--pending --if-due`. The job only
*asks* tick(); PENDING_INTERVAL alone decides whether a run happens."""
import os
import plistlib
import re
import subprocess
import sys
import tempfile

from . import config

LABEL = "com.aitracker.pending"
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
                or "--selfcheck" in argv or "unittest" in (argv[0] or ""))


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
        r = run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            _set_optout(False)
        return 0 if r.returncode == 0 else 1
    old = _read_plist()
    if old and old.get("WorkingDirectory") not in (None, _root()):
        print("replacing job that pointed at %s" % old.get("WorkingDirectory"))
    path = plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.makedirs(os.path.dirname(sched_log_path()), exist_ok=True)
    with open(path, "wb") as f:
        f.write(launchd_plist())
    os.chmod(path, 0o644)
    run(["launchctl", "bootout", _target()], capture_output=True, text=True)
    r = run(["launchctl", "bootstrap", "gui/%d" % os.getuid(), path], capture_output=True, text=True)
    if r.returncode != 0:
        try:
            os.remove(path)
        except OSError:
            pass
        print("ai-tracker: launchctl bootstrap failed (rc %s)" % r.returncode)
        return 1
    _set_optout(False)
    return 0


def sched_uninstall(run=subprocess.run):
    if sys.platform == "win32":
        run(["schtasks", "/Delete", "/TN", TASK, "/F"], capture_output=True, text=True)
    elif sys.platform == "darwin":
        run(["launchctl", "bootout", _target()], capture_output=True, text=True)
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
        st["installed"] = run(["schtasks", "/Query", "/TN", TASK],
                              capture_output=True, text=True).returncode == 0
        return st
    if sys.platform != "darwin":
        return st
    st["kind"] = "launchd"
    r = run(["launchctl", "print", _target()], capture_output=True, text=True)
    st["installed"] = r.returncode == 0
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
