"""Agent CLI Doctor / Upgrade (user-requested; see .claude/rules/conventions.md rule 6, "agent CLI Doctor/Upgrade").

Runs `<agent> --version`, `<claude> doctor`, `<agent> update|upgrade` through update._run (no shell, cwd ~), and after a
successful update restarts the Claude sessions that run in the tracker's own terminals (term_vt.stop_for_upgrade, then
term_vt.open_pty mode=resume). Everything the request picks is the agent id and the action; argv comes from the provider
descriptor. Every module-level name starts with agent_/_agent_/AGENT_ (the bundle flattens all modules into one
namespace). term_vt is optional and absent from the bundle, so it is reached through sys.modules only."""
import json, os, re, shutil, sys, threading, time
from . import config
from .update import _run, _APPLY, _AGENT_JOB_LOCK
from .pending import _pending_lock
from .registry import PROVIDERS, all_sessions, resume_cmd
from .providers.claude import session_state, user_line_has, transcript_size, _live_workers

AGENT_RESUME_PROMPT = "continue, re-read CLAUDE.md"
AGENT_VERSION_TIMEOUT, AGENT_DOCTOR_TIMEOUT, AGENT_STOP_TIMEOUT = 15, 60, 30
AGENT_VERSION_TTL = 60          # s a cached --version is trusted
AGENT_VERIFY_WAIT = 90          # s, ONE shared deadline for all resumed sessions
AGENT_OUTPUT_CAP = 8000         # chars of ANSI-stripped output kept on the job
AGENT_RESTART_DAEMON = True     # V6d passed (S5)
AGENT_DAEMON_STOP_WAIT = 8      # s for both recorded worker pids to be gone after `claude stop`

AGENT_AUTO_UPDATE_NOTE = ("Note: Claude Code also updates itself in the background; the tracker leaves that alone. "
                          "A new version only takes effect when a session restarts.")
# _agent_message(names, restarts):
AGENT_MSG_STOP = ("The following sessions: {list} will be stopped, you might have to continue again with a prompt "
                  "once the upgrade lands. The tracker restarts each one on the new version as soon as the update "
                  "finishes. A session that is working, or waiting on you for a permission or an answer, when it is "
                  "stopped is resumed with the prompt “continue, re-read CLAUDE.md”; an idle one is resumed and "
                  "left waiting for you. A session already on the new version is left running. Even if nothing new "
                  "is installed, a session running an older version than the installed one is restarted onto it.")
AGENT_MSG_NO_STOP = "No session started from this dashboard will be stopped."
# version_text per stop row (D8):
AGENT_VER_OLD = "runs v{v}, older than the installed v{i} — restarted even if nothing new is installed"
AGENT_VER_CURRENT = "already on the installed v{i} — restarted only if a newer version installs"
AGENT_VER_NEWER = ("runs v{v}, newer than the tracker's v{i} — left running (another claude may be first on "
                   "your shell's PATH)")
AGENT_VER_NEWER_WARN = AGENT_VER_NEWER + ", unless the update installs a newer one"     # warning only
AGENT_VER_UNKNOWN = "version unknown — restarted only if a newer version installs"
AGENT_VER_UNKNOWN_SKIPPED = "version unknown and nothing new was installed, so it was left running"
AGENT_OUT_OF_DATE = "out of date (installed v%s)"
AGENT_RELABELLED = "now runs this session (the terminal was opened on %s)"
AGENT_MSG_NO_RESTART = ("Auggie sessions are not restarted by the tracker; restart them yourself once the upgrade "
                        "lands.")
# state_text per stop row (from session_state at warning time; the prompt decision is re-taken at stop time):
AGENT_STATE_BUSY = "working now — its current turn will be interrupted, then resumed with the prompt."
AGENT_STATE_WAITING = "waiting on you (a permission or a question) — that prompt will be cancelled, then resumed with the prompt."
AGENT_STATE_IDLE = "idle — resumed without a prompt."
AGENT_STATE_UNKNOWN = "state unknown — resumed with the prompt only if it is working when stopped."
AGENT_STATE_KIDS = " Commands it started (tool runs, background shells such as a dev server) are stopped too."  # appended to every state_text
AGENT_STATE_DAEMON_MOVE = (" It runs in Claude's background daemon now; it comes back as a session in this tracker "
                           "terminal, which ends if the tracker stops.")  # appended for daemon rows (S3)
# cannot_stop:
AGENT_REASON_DAEMON = "runs in the Claude background daemon; the tracker does not restart it — restart it yourself:"  # only if V6d fails
AGENT_DUP_WARN = ("the same session as terminal %s — this terminal is stopped; the "
                  "session comes back once, in a tracker terminal")
AGENT_DUP_PARTIAL = "its other copy (terminal %s) was not confirmed, so neither copy was stopped"
AGENT_DUP_CLOSED = "stopped; the session was resumed in terminal %s"
AGENT_DUP_BLOCKED = ("the same session also runs in terminal %s, which cannot be restarted, so this one was not "
                     "stopped — close it and press Upgrade again")
AGENT_DUP_NOT_RESUMED = ("stopped, but not resumed, because terminal %s could not be stopped — close that terminal, "
                         "then press Upgrade again")
AGENT_RESUME_REUSED = ("another tracker terminal (%s) still runs this session, so it was not resumed — close it and "
                       "press Upgrade again")
AGENT_PROMPT_NOT_SEEN = ("resumed, but the prompt was not confirmed in its transcript — check its terminal")
AGENT_REASON_NOJOB = "its background job is gone from the daemon roster"
AGENT_NO_SLOT = "no free terminal slot to resume it in, so it was not stopped — close a terminal and press Upgrade again"
AGENT_STILL_DAEMON = "it reattached to a background job that is still running"
AGENT_FAIL_SCAN = ("The update ran, but a pending-work scan is running, so no session was restarted — press Upgrade "
                   "again when it finishes.")
# outside `how`:
AGENT_HOW_TUI = "not started from this dashboard — exit it, then run:"
AGENT_HOW_DAEMON = "a background session — stop it, then resume it in a terminal:"
AGENT_HOW_DESKTOP = "runs inside the Claude desktop app; it updates with the app"
AGENT_HOW_AUGGIE = "version unknown — restart Auggie in that terminal once the upgrade lands"
# steps:
AGENT_STEP_OLD, AGENT_STEP_UPDATE, AGENT_STEP_NEW = ("Reading the installed version…", "Running {bin} {args}…",
                                                     "Checking the new version…")
AGENT_STEP_RESTART = "Restarting {title} ({n} of {m})…"
AGENT_STEP_VERIFY = "Checking the restarted sessions…"
# failures / per-item:
AGENT_FAIL_VERSION = "Could not run `{bin} --version`; nothing was changed and no session was stopped."
AGENT_FAIL_UPDATE = "{label} update failed; no session was stopped. Run Doctor to see why."
AGENT_FAIL_UPDATE_NODOC = "{label} update failed; no session was stopped. Its output is below."   # agents without Doctor (Auggie)
AGENT_STILL_ON = " Still on {old}."
AGENT_FAIL_INTERNAL = "The upgrade stopped on an internal error (%s); see the list below for what was already done."
AGENT_NOT_SHOWN = "not shown in the warning, not stopped"
AGENT_UNCONFIRMED = "could not confirm it stopped, so it was not resumed — open its terminal"
AGENT_DAEMON_STOP_FAILED = "`claude stop` failed; it is still running in the background"
AGENT_VERSION_MISMATCH = ("resumed on v%s, expected v%s — another claude may be first on your shell's PATH; "
                          "run Doctor")
AGENT_NOT_CONFIRMED = "resumed, but not yet seen running on v%s — open its terminal"
AGENT_DOCTOR_DONE, AGENT_DOCTOR_FAILED = "Doctor finished.", "Doctor exited with an error; see its output."
# resume all prior terminals (every user-facing string is server-written):
AGENT_RA_MESSAGE = ("These Claude sessions ran in a tracker terminal from this checkout (newest first, closed ones "
                    "included) and are not open now. Resume opens the ticked ones in the background with claude "
                    "--resume, each in its folder's terminal. No terminal window opens and no prompt is sent; they "
                    "appear in Manage terminals.")
AGENT_RA_NONE = ("Nothing to resume: no Claude session that is not open now has run in a tracker terminal from "
                 "this checkout. The tracker keeps this record from this version on.")
AGENT_RA_NONE_OPENABLE = " None of them can be reopened here; the reasons are below."
AGENT_RA_PICK = ("Only %d terminal slot%s free (%d of %d in use), so the newest that fit are ticked; tick others "
                 "instead, or close a terminal first. Each new folder, and each further session in a folder whose "
                 "terminal is busy, takes a slot.")
AGENT_RA_ALREADY = "Already open in a terminal here, so not listed: %s."
AGENT_RA_NOTE = ("Nobody is watching these terminals, so one that sits idle closes after %d minutes "
                 "(Config → Terminal → Idle terminal TTL). Peek or open one to keep it.")
AGENT_RA_TOO_MANY = ("The %d you ticked need %d terminal slot%s, but only %d %s free now. Untick some or close a "
                     "terminal, then press Resume again. The list below is current.")
AGENT_RA_NONE_PICKED = "None of the sessions you ticked can be opened now. The list below is current."
AGENT_RA_GONE = "no longer in the list (it is open now, or its transcript is gone)"
AGENT_RA_REUSED = "already open in tracker terminal %s, so it was not opened again"
AGENT_RA_STEP = "Opening %d of %d: %s"
AGENT_RA_NO_TERMS = "This build has no in-browser terminals, so there is nothing to resume."
AGENT_RA_DISABLED = "Terminals are disabled here (TRACKER_TERMINAL=0, or a network bind without TRACKER_AUTH)."
AGENT_RA_FAIL_SCAN = "A pending-work scan is running; nothing was opened. Try again in a minute."

_AGENT_JOB = None               # last job, memory only
_AGENT_JLOCK = threading.Lock() # guards every write to _AGENT_JOB and its items
_AGENT_VERSIONS = {}            # id -> {version, checked_at, error}
_AGENT_VLOCK = threading.Lock() # single flight for the version refresh thread
_AGENT_SEQ = 0
_AGENT_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_AGENT_VER_RE = re.compile(r"\d+\.\d+\.\d+")
_AGENT_ITEM_KEYS = ("tty", "session", "target", "title", "daemon", "outcome", "detail", "command", "tty_after",
                    "forked", "on_version", "prompt_seen", "size_before")


# --------------------------------------------------------------------------- pure helpers
def agent_parse_version(text):
    """First d.d.d on the first non-blank line, else None."""
    for line in (text or "").splitlines():
        if line.strip():
            m = _AGENT_VER_RE.search(line)
            return m.group(0) if m else None
    return None


def _agent_vtuple(v):
    try:
        return tuple(int(x) for x in v.split(".")) if isinstance(v, str) and v else None
    except ValueError:
        return None


def _agent_message(names, restarts):
    if not restarts:
        return AGENT_MSG_NO_RESTART
    if not names:
        return AGENT_MSG_NO_STOP
    return AGENT_MSG_STOP.format(list=", ".join(names))


def _agent_was_busy(state, work_children):
    return bool(work_children) and work_children > 0 or state in ("busy", "waiting")


def _agent_version_text(version, installed):
    v, i = _agent_vtuple(version), _agent_vtuple(installed)
    if v is None or i is None:
        return AGENT_VER_UNKNOWN
    if v < i:
        return AGENT_VER_OLD.format(v=version, i=installed)
    if v > i:
        return AGENT_VER_NEWER_WARN.format(v=version, i=installed)
    return AGENT_VER_CURRENT.format(i=installed)


def _agent_state_text(state):
    return {"busy": AGENT_STATE_BUSY, "waiting": AGENT_STATE_WAITING,
            "idle": AGENT_STATE_IDLE}.get(state, AGENT_STATE_UNKNOWN)


def _agent_item(cand, outcome, detail=""):
    """A COMPLETE item: every schema key present from creation (verify only updates existing keys)."""
    return {"tty": cand.get("tty") or "", "session": cand.get("session") or "", "target": cand.get("target") or "",
            "title": cand.get("title") or "", "daemon": bool(cand.get("daemon")), "outcome": outcome,
            "detail": detail, "command": list(cand.get("command") or []), "tty_after": None, "forked": False,
            "on_version": None, "prompt_seen": None, "size_before": 0}


def _agent_set(obj, **kw):
    with _AGENT_JLOCK:
        obj.update(kw)


def _agent_push(job, item):
    with _AGENT_JLOCK:
        job["items"].append(item)


def _agent_snapshot():
    with _AGENT_JLOCK:
        return None if _AGENT_JOB is None else json.loads(json.dumps(_AGENT_JOB))


def _agent_strip(b):
    s = b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else str(b or "")
    return _AGENT_ANSI.sub("", s).replace("\r", "")[-AGENT_OUTPUT_CAP:]


def _agent_name(item):
    return item["title"] or item["session"][:8]


def _agent_tv():
    return sys.modules.get("aitracker.term_vt")


def agent_job_running():
    return _AGENT_JOB is not None and _AGENT_JOB["state"] == "running"


# --------------------------------------------------------------------------- specs, versions, status
def agent_specs():
    """PROVIDERS that declare an agent_cli descriptor, plus provider and the resolved binary path."""
    out = []
    for p in PROVIDERS:
        d = getattr(p, "agent_cli", None)
        if d:
            out.append(dict(d, provider=p, path=shutil.which(d["bin"])))
    return out


def _agent_spec(agent_id):
    for s in agent_specs():
        if s["id"] == agent_id:
            return s
    return None


def _agent_version(spec):
    """Run `<bin> --version` -> (version | None, error text). Job / refresh threads only."""
    rc, out, err = _run([spec["path"], *spec["version"]], AGENT_VERSION_TIMEOUT, cwd=os.path.expanduser("~"))
    if rc != 0:
        return None, (err or out or b"").decode("utf-8", "replace").strip()[:200] or "exit %s" % rc
    v = agent_parse_version(out.decode("utf-8", "replace"))
    return (v, "") if v else (None, "unreadable version")


def _agent_cache(spec, version, error=""):
    _AGENT_VERSIONS[spec["id"]] = {"version": version, "checked_at": time.time(), "error": error}


def _agent_refresh_versions():
    if not _AGENT_VLOCK.acquire(blocking=False):
        return
    try:
        for spec in agent_specs():
            if spec["path"]:
                v, e = _agent_version(spec)
                _agent_cache(spec, v, e)
    except Exception:
        pass
    finally:
        _AGENT_VLOCK.release()


def agent_status():
    """GET /api/agents body. Never runs a subprocess itself (a refresh runs in its own thread)."""
    now, stale, rows, tv = time.time(), False, [], _agent_tv()
    for spec in agent_specs():
        c = _AGENT_VERSIONS.get(spec["id"]) or {}
        if spec["path"] and now - c.get("checked_at", 0) > AGENT_VERSION_TTL:
            stale = True
        rows.append({"id": spec["id"], "label": spec["label"], "path": spec["path"] or "",
                     "installed": c.get("version"), "checked_at": c.get("checked_at"),
                     "error": "" if spec["path"] else "%s not found on the tracker's PATH" % spec["bin"],
                     "can_doctor": bool(spec["doctor"] and spec["path"]), "can_upgrade": bool(spec["path"]),
                     "restarts_sessions": bool(spec["restarts_sessions"]),
                     "note": AGENT_AUTO_UPDATE_NOTE if spec["id"] == "claude" else "",
                     "can_resume_all": bool(spec["id"] == "claude" and tv is not None
                                            and hasattr(tv, "term_gate") and tv.term_gate.allowed())})
        if spec["path"] and c.get("error"):
            rows[-1]["error"] = c["error"]
    if stale and not _AGENT_VLOCK.locked():
        try:
            threading.Thread(target=_agent_refresh_versions, name="agent-versions", daemon=True).start()
        except RuntimeError:
            stale = False
    checking = stale or _AGENT_VLOCK.locked()
    for r in rows:
        r["checking"] = bool(checking and r["path"])
    return {"agents": rows, "job": _agent_snapshot()}


# --------------------------------------------------------------------------- the warning
def _agent_split(cands):
    """(stop, cannot_stop). A daemon candidate is restartable only when AGENT_RESTART_DAEMON."""
    stop, cannot = [], []
    for c in cands or []:
        if c.get("stoppable") and (AGENT_RESTART_DAEMON or not c.get("daemon")):
            stop.append(c)
        elif c.get("stoppable"):
            cannot.append(dict(c, stoppable=False, reason=AGENT_REASON_DAEMON))
        else:
            cannot.append(c)
    for blocker in [x for x in cannot if x.get("dup_group")]:      # D15: a copy that cannot be stopped blocks its group
        for c in [x for x in stop if blocker["tty"] in (x.get("dup_group") or ())]:
            stop.remove(c)
            cannot.append(dict(c, stoppable=False, reason=AGENT_DUP_BLOCKED % blocker["tty"]))
    return stop, cannot


def agent_plan_upgrade(agent_id):
    """The warning (the 409 needs_confirm body); None for an unknown agent."""
    spec = _agent_spec(agent_id)
    if spec is None:
        return None
    installed = (_AGENT_VERSIONS.get(agent_id) or {}).get("version")
    tv = _agent_tv() if spec["restarts_sessions"] else None
    cands = tv.upgrade_candidates() if tv else []
    stop, cannot = _agent_split(cands)
    rows = []
    for c in stop:
        st = session_state(c["target"], c.get("status"))
        r = {"tty": c["tty"], "session": c["session"], "title": c.get("title") or "", "cwd": c.get("cwd") or "",
             "version": c.get("version") or "", "daemon": bool(c.get("daemon")), "command": list(c.get("command") or []),
             "state_text": _agent_state_text(st) + AGENT_STATE_KIDS + (AGENT_STATE_DAEMON_MOVE if c.get("daemon") else ""),
             "version_text": _agent_version_text(c.get("version"), installed)}
        if c.get("relabelled"):
            r["relabelled_text"] = AGENT_RELABELLED % c["relabelled"][:8]
        if c.get("dup_group") and not c.get("primary"):
            r["dup_text"] = AGENT_DUP_WARN % ", ".join(t for t in c["dup_group"] if t != c["tty"])
        rows.append(r)
    nostop = [{"tty": c.get("tty") or "", "session": c.get("session") or "", "title": c.get("title") or "",
               "reason": c.get("reason") or "", "command": list(c.get("command") or [])} for c in cannot]
    owned_pids = {c.get("pid") for c in cands}
    owned_ids = {c.get("target") for c in cands} | {c.get("session") for c in cands}
    return {"needs_confirm": True, "agent": agent_id, "installed": installed,
            "message": _agent_message([c["title"] or c["session"][:8] for c in rows], spec["restarts_sessions"]),
            "note": AGENT_AUTO_UPDATE_NOTE if agent_id == "claude" else "",
            "stop": rows, "cannot_stop": nostop,
            "outside": _agent_outside(spec, installed, owned_pids, owned_ids)}


def _agent_outside(spec, installed, owned_pids, owned_ids):
    """Sessions not running in a tracker terminal: show-only rows with the command to run."""
    out = []
    if spec["id"] == "claude":
        seen = {}
        rows = [e for e in spec["provider"].running() if e["pid"] not in owned_pids and e["id"] not in owned_ids]
        for e in rows:                       # a parked TUI and its worker are one conversation: keep the bg entry
            if e.get("job"):
                if e["job"] not in seen or e.get("kind") == "bg":
                    seen[e["job"]] = e
        keep = [e for e in rows if not e.get("job") or seen.get(e["job"]) is e]
        for e in keep:
            host, vt, it = e["host"], _agent_vtuple(e.get("version")), _agent_vtuple(installed)
            ood = None if host == "desktop" or vt is None or it is None else vt < it
            if host == "tui":
                how, cmd = AGENT_HOW_TUI, resume_cmd(e["id"], e.get("model"))
                command = [cmd] if cmd else []
            elif host == "daemon":
                how = AGENT_HOW_DAEMON
                command = (["claude stop " + e["job"]] if e.get("job") else []) + ["claude --resume " + e["id"]]
            else:
                how, command = AGENT_HOW_DESKTOP, []
            out.append({"id": e["id"], "title": e.get("title") or "", "cwd": e.get("cwd") or "",
                        "version": e.get("version") or "", "host": host, "state": e.get("state") or "",
                        "out_of_date": ood, "out_of_date_text": (AGENT_OUT_OF_DATE % installed) if ood else "", "how": how, "command": command})
    else:
        pre = spec["provider"].prefix
        for r in all_sessions():
            if str(r.get("id", "")).startswith(pre) and time.time() - (r.get("mtime") or 0) < config.LIVE_WINDOW:
                out.append({"id": r["id"], "title": r.get("title") or "", "cwd": r.get("cwd") or "", "version": "",
                            "host": "tui", "out_of_date": None, "out_of_date_text": "", "how": AGENT_HOW_AUGGIE, "command": []})
    return out


# --------------------------------------------------------------------------- start
def agent_start(agent_id, action, confirm):
    """-> (202 | 400 | 409 | 500, body). confirm: None or a list of {tty, session} the user saw in the warning."""
    spec = _agent_spec(agent_id) if isinstance(agent_id, str) else None
    if spec is None:
        return 400, {"error": "unknown agent"}
    if action not in ("doctor", "upgrade"):
        return 400, {"error": "action must be doctor or upgrade"}
    if action == "doctor" and not spec["doctor"]:
        return 400, {"error": "%s has no doctor" % spec["label"]}
    if confirm is not None and not (isinstance(confirm, list) and len(confirm) <= 64 and all(
            isinstance(c, dict) and isinstance(c.get("tty"), str) and isinstance(c.get("session"), str)
            for c in confirm)):
        return 400, {"error": "confirm must be a list of {tty, session}"}
    if not spec["path"]:
        return 409, {"error": "%s not found on the tracker's PATH" % spec["bin"]}
    fn, args = (_agent_job_doctor, (spec,)) if action == "doctor" else (_agent_job_upgrade, (spec, confirm))
    return _agent_launch(agent_id, action, fn, args)


def _agent_launch(agent, action, fn, args):
    """The job-slot tail shared by every agent job. -> (202 | 409 | 500, body)."""
    global _AGENT_JOB, _AGENT_SEQ
    if not _AGENT_JOB_LOCK.acquire(blocking=False):
        return 409, {"error": "an agent job is already running", "job": _agent_snapshot()}
    if _APPLY.locked():
        _AGENT_JOB_LOCK.release()
        return 409, {"error": "the tracker is updating itself — try again after it restarts"}
    _AGENT_SEQ += 1
    job = {"id": _AGENT_SEQ, "agent": agent, "action": action, "state": "running", "step": "",
           "started": time.time(), "finished": None, "old": None, "new": None, "output": "", "items": [],
           "outside": [], "summary": ""}
    with _AGENT_JLOCK:
        _AGENT_JOB = job
    try:
        threading.Thread(target=_agent_thread, args=(job, fn, args), name="agent-" + action, daemon=True).start()
    except RuntimeError as e:
        _agent_set(job, state="failed", finished=time.time(), summary=AGENT_FAIL_INTERNAL % e)
        _AGENT_JOB_LOCK.release()
        return 500, {"error": "could not start the job", "job": _agent_snapshot()}
    return 202, {"job": _agent_snapshot()}


def _agent_thread(job, fn, args):
    try:
        fn(job, *args)
    except Exception as e:
        _agent_set(job, state="failed", summary=AGENT_FAIL_INTERNAL % e)
    finally:
        _agent_set(job, finished=time.time())
        _AGENT_JOB_LOCK.release()


def _agent_fail(job, summary, label="agent upgrade"):
    _agent_set(job, state="failed", summary=summary)
    print("ai-tracker: %s: %s" % (label, summary), flush=True)


# --------------------------------------------------------------------------- resume all prior terminals
def _agent_ra_body(plan, error=""):
    """The 409 picker body for a plan from term_vt.resume_all_plan (idle is server-only and stripped)."""
    opn, cannot = plan["open"], plan["cannot"]
    msg = AGENT_RA_NONE if not opn and not cannot else AGENT_RA_MESSAGE + ("" if opn else AGENT_RA_NONE_OPENABLE)
    free = plan["free"]
    pick = AGENT_RA_PICK % (free, "" if free == 1 else "s", plan["in_use"], plan["max"]) \
        if any(not r["checked"] for r in opn) else ""
    return {"needs_confirm": True, "error": error, "message": msg, "pick": pick,
            "already": AGENT_RA_ALREADY % ", ".join(plan["already"]) if plan["already"] else "",
            "note": AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN if opn else "",
            "open": opn, "cannot": cannot, "free": free, "max": plan["max"]}


def _agent_ra_gate():
    """-> (tv, None) or (None, (409, body)): the refusals shared by the preview and the start."""
    tv = _agent_tv()
    if tv is None:
        return None, (409, {"error": AGENT_RA_NO_TERMS})
    if not tv.term_gate.allowed():
        return None, (409, {"error": AGENT_RA_DISABLED})
    if agent_job_running():
        return None, (409, {"error": "an agent job is already running", "job": _agent_snapshot()})
    if _APPLY.locked():
        return None, (409, {"error": "the tracker is updating itself — try again after it restarts"})
    return tv, None


def agent_plan_resume_all():
    """POST /api/terminals/resume-all with no confirm -> (409, picker body). No side effects."""
    tv, refusal = _agent_ra_gate()
    return refusal if refusal else (409, _agent_ra_body(tv.resume_all_plan()))


def agent_start_resume_all(confirm):
    """POST /api/terminals/resume-all {confirm: [session ids]} -> (202 | 400 | 409 | 500, body)."""
    if not (isinstance(confirm, list) and 1 <= len(confirm) <= 64 and all(
            isinstance(c, str) and 0 < len(c) <= 200 for c in confirm)):
        return 400, {"error": "confirm must be a list of 1 to 64 session ids"}
    confirm = list(dict.fromkeys(confirm))
    tv, refusal = _agent_ra_gate()
    if refusal:
        return refusal
    plan = tv.resume_all_plan()
    want = set(confirm)
    picked = [r for r in plan["open"] if r["session"] in want]
    if not picked:
        return 409, _agent_ra_body(plan, AGENT_RA_NONE_PICKED)
    need = tv._ra_need([r["cwd"] for r in picked], set(plan["idle"]))
    if need > plan["free"]:
        return 409, _agent_ra_body(plan, AGENT_RA_TOO_MANY % (
            len(picked), need, "" if need == 1 else "s", plan["free"], "is" if plan["free"] == 1 else "are"))
    return _agent_launch("claude", "resume_all", _agent_job_resume_all, (confirm,))


def _agent_job_resume_all(job, confirm):
    tv = _agent_tv()
    cm = _pending_lock()
    got = cm.__enter__()
    try:
        if not got:
            return _agent_fail(job, AGENT_RA_FAIL_SCAN, "resume all")
        plan = tv.resume_all_plan()
        want = set(confirm)
        opn = {r["session"]: r for r in plan["open"]}
        bad = {r["session"]: r for r in plan["cannot"]}
        todo = [r for r in plan["open"] if r["session"] in want]
        for sid in confirm:
            if sid not in opn:
                r = bad.get(sid) or {"session": sid, "title": sid[:8], "reason": AGENT_RA_GONE, "command": []}
                _agent_push(job, _agent_item(dict(r, target=sid), "failed", r["reason"]))
        for i, r in enumerate(todo, 1):
            _agent_set(job, step=AGENT_RA_STEP % (i, len(todo), r["title"]))
            cand = {"tty": "", "session": r["session"], "target": r["session"], "title": r["title"],
                    "command": r["command"], "cols": r["cols"], "rows": r["rows"]}
            try:
                _agent_resume(job, tv, cand, False, AGENT_RA_REUSED)    # mode "resume", no prompt key
            except Exception as e:
                _agent_push(job, _agent_item(cand, "failed", str(e)))
    finally:
        cm.__exit__(None, None, None)
    summary = _agent_ra_summary(job["items"])
    _agent_set(job, summary=summary, state="done")
    print("ai-tracker: resume all: " + summary, flush=True)


def _agent_ra_summary(items):
    ok = [i for i in items if i["outcome"] == "unprompted"]
    bad = [i for i in items if i["outcome"] == "failed"]
    s = ("Started resuming %d of %d prior terminal%s in the background: %s." % (
        len(ok), len(items), "" if len(items) == 1 else "s",
        ", ".join(_agent_name(i) + (" (opened as a copy, --fork-session)" if i.get("forked") else "") for i in ok))
        if ok else "No prior terminal started resuming.")
    if bad:
        s += " Not opened: %s." % "; ".join("%s (%s)" % (_agent_name(i), i["detail"]) for i in bad)
    if ok:
        s += " " + AGENT_RA_NOTE % config.TERM_IDLE_TTL_MIN
    return s


# --------------------------------------------------------------------------- jobs
def _agent_job_doctor(job, spec):
    _agent_set(job, step="Running %s %s…" % (spec["bin"], " ".join(spec["doctor"])))
    rc, out, err = _run([spec["path"], *spec["doctor"]], AGENT_DOCTOR_TIMEOUT, cwd=os.path.expanduser("~"))
    summary = AGENT_DOCTOR_DONE if rc == 0 else AGENT_DOCTOR_FAILED
    _agent_set(job, output=_agent_strip(out + err), state="done" if rc == 0 else "failed", summary=summary)
    print("ai-tracker: agent doctor: " + summary, flush=True)


def _agent_job_upgrade(job, spec, confirm):
    home, label, binname = os.path.expanduser("~"), spec["label"], spec["bin"]
    _agent_set(job, step=AGENT_STEP_OLD)
    old, _e = _agent_version(spec)
    if old is None:
        return _agent_fail(job, AGENT_FAIL_VERSION.format(bin=binname))
    _agent_set(job, old=old, step=AGENT_STEP_UPDATE.format(bin=binname, args=" ".join(spec["update"])))
    rc, out, er = _run([spec["path"], *spec["update"]], spec["update_timeout"], cwd=home)
    _agent_set(job, output=_agent_strip(out + er))
    if rc != 0:
        cur, _e = _agent_version(spec)
        msg = (AGENT_FAIL_UPDATE if spec["doctor"] else AGENT_FAIL_UPDATE_NODOC).format(label=label)
        if cur is None or cur == old:
            msg += AGENT_STILL_ON.format(old=old)
        return _agent_fail(job, msg)
    _agent_set(job, step=AGENT_STEP_NEW)
    new, _e = _agent_version(spec)
    _agent_cache(spec, new, _e)
    if new is None:
        return _agent_fail(job, AGENT_FAIL_VERSION.format(bin=binname))
    _agent_set(job, new=new)
    tv = _agent_tv() if spec["restarts_sessions"] else None
    cands = []
    if tv is not None:
        cm = _pending_lock()
        got = cm.__enter__()
        try:
            if not got:
                return _agent_fail(job, AGENT_FAIL_SCAN)
            cands = tv.upgrade_candidates()
            _agent_restart_all(job, spec, tv, cands, old, new, {(c["tty"], c["session"]) for c in (confirm or [])})
            _agent_set(job, step=AGENT_STEP_VERIFY)
            _agent_verify(job, new, time.time() + AGENT_VERIFY_WAIT)
        finally:
            cm.__exit__(None, None, None)
    outside = _agent_outside(spec, new, {c.get("pid") for c in cands},
                             {c.get("target") for c in cands} | {c.get("session") for c in cands})
    summary = _agent_summary(spec, old, new, job["items"], outside)
    _agent_set(job, outside=outside, summary=summary, state="done")
    print("ai-tracker: agent upgrade: " + summary, flush=True)


def _agent_restart_all(job, spec, tv, cands, old, new, pairs):
    """Sort every candidate (D8: the restart runs whether or not old == new), then restart the rest one by one.
    A non-stoppable row is reported by its own reason; a stoppable one the user did not see is never stopped; a
    session running a NEWER version than the installed one is left alone (D16). Copies of one session (dup_group,
    D15) are stopped together and resumed once."""
    stop, cannot = _agent_split(cands)
    rows, nt = [(c, False) for c in stop] + [(c, True) for c in cannot], _agent_vtuple(new)
    verdict = {}                              # id(c) -> (outcome, detail); "todo" rows are absent
    for c, bad in rows:
        ver, vt = c.get("version") or "", _agent_vtuple(c.get("version"))
        if bad:
            verdict[id(c)] = ("not_restarted", c.get("reason") or "")
        elif (c["tty"], c["session"]) not in pairs:
            verdict[id(c)] = ("not_shown", AGENT_NOT_SHOWN)
        elif ver and ver == new:
            verdict[id(c)] = ("current", "")
        elif vt and nt and vt > nt:
            verdict[id(c)] = ("current", AGENT_VER_NEWER.format(v=ver, i=new))
        elif not ver and old == new:
            verdict[id(c)] = ("current", AGENT_VER_UNKNOWN_SKIPPED)
    work, grouped = [], set()
    for c, bad in rows:
        key = tuple(sorted(c.get("dup_group") or ()))
        if not key:
            if id(c) not in verdict:
                work.append([c])
            continue
        if key in grouped:
            continue
        grouped.add(key)
        mem = [x for x, _b in rows if x["tty"] in key]
        stoppable = [x for x in mem if not any(x is y for y in cannot)]
        blocked = [x for x in mem if any(x is y for y in cannot)]
        if blocked:                           # a copy that cannot be stopped would make the resume a reattach
            for x in stoppable:
                verdict[id(x)] = ("failed", AGENT_DUP_BLOCKED % blocked[0]["tty"])
        elif any((x["tty"], x["session"]) not in pairs for x in stoppable):
            unseen = [x["tty"] for x in stoppable if (x["tty"], x["session"]) not in pairs]
            for x in stoppable:               # a confirm naming only some copies: stop none of them
                verdict[id(x)] = (("not_shown", AGENT_NOT_SHOWN) if x["tty"] in unseen
                                  else ("not_shown", AGENT_DUP_PARTIAL % unseen[0]))
        elif any(id(x) not in verdict for x in stoppable):
            for x in stoppable:
                verdict.pop(id(x), None)
            work.append(stoppable)
    for c, _b in rows:
        if id(c) in verdict:
            _agent_push(job, _agent_item(c, *verdict[id(c)]))
    for n, mem in enumerate(work, 1):
        c = next((x for x in mem if x.get("primary")), mem[0])
        title = c.get("title") or c["session"][:8]
        _agent_set(job, step=AGENT_STEP_RESTART.format(title=title, n=n, m=len(work)))
        try:
            if c.get("needs_slot") and tv._live_count() - (0 if c.get("folder") else 1) >= config.MAX_TERMS:
                for x in mem:
                    _agent_push(job, _agent_item(x, "failed", AGENT_NO_SLOT))
            elif len(mem) > 1:
                _agent_restart_group(job, spec, tv, mem, c)
            else:
                _agent_restart_one(job, spec, c, new)
        except Exception as e:
            for x in mem:
                _agent_push(job, _agent_item(x, "failed", str(e)))


def _agent_stop_one(spec, cand):
    """Stop one pane's session -> (busy, None) once confirmed, else (None, the failure item). Pushes nothing."""
    return (_agent_stop_daemon if cand.get("daemon") else _agent_stop_tui)(spec, cand)


def _agent_restart_one(job, spec, cand, new):
    busy, bad = _agent_stop_one(spec, cand)
    if bad:
        return _agent_push(job, bad)
    _agent_resume(job, _agent_tv(), cand, busy)


def _agent_restart_group(job, spec, tv, mem, prim):
    """D15: stop every copy (primary first, each with its own tty + session), resume ONCE, only if every stop was
    confirmed. The first failure halts the group: later copies are left running, earlier ones are reported stopped.
    A daemon session is stopped once (via the primary); the other copies only have their thin client cleared."""
    prim = prim if prim in mem else mem[0]
    order = [prim] + [x for x in mem if x is not prim]
    res = []
    for n, x in enumerate(order):
        busy, bad = (_agent_stop_one(spec, x) if x is prim or not prim.get("daemon") else _agent_clear_thin(tv, x))
        if bad:
            for y, _busy, _b in res:
                _agent_push(job, _agent_item(y, "failed", AGENT_DUP_NOT_RESUMED % x["tty"]))
            _agent_push(job, bad)
            for y in order[n + 1:]:
                _agent_push(job, _agent_item(y, "failed", AGENT_DUP_BLOCKED % x["tty"]))
            return
        res.append((x, busy, bad))
    item = _agent_resume(job, tv, prim, any(busy for _x, busy, _b in res))
    ok = item["outcome"] in ("prompted", "unprompted")
    for x, _busy, _b in res[1:]:
        _agent_push(job, _agent_item(x, "closed", AGENT_DUP_CLOSED % (item["tty_after"] or prim["tty"])) if ok
                    else _agent_item(x, "failed", item["detail"]))


def _agent_stop_tui(spec, cand):
    tv = _agent_tv()
    entry = next((e for e in spec["provider"].running() if e["pid"] == cand["pid"]), None)
    st = session_state(cand["target"], (entry or {}).get("status_raw"))   # just before the stop
    cmd = (cand.get("command") or [""])[0]
    print("ai-tracker: agent upgrade: restarting %s (%s); if this dashboard dies, resume it with: %s"
          % (cand.get("title") or cand["session"][:8], cand["session"], cmd), flush=True)
    r = tv.stop_for_upgrade(cand["tty"], cand["session"], cand["pid"], cand.get("thin", False))
    if r.get("error"):
        return None, _agent_item(cand, "failed", r["error"])
    if not r.get("confirmed"):
        return None, _agent_item(cand, "unconfirmed", AGENT_UNCONFIRMED)
    return _agent_was_busy(st, r.get("work_children", 0)), None


def _agent_stop_daemon(spec, cand):
    """A tracker pane showing a daemon job: `claude stop <short>`, confirm the worker pids are gone, clear the
    pane's thin client, sweep orphaned tools (plan 5.4, S5). The caller resumes the session."""
    tv = _agent_tv()
    short = cand.get("job_short") or ""
    w = next((e for e in spec["provider"].running() if e["id"] == cand["target"] and e.get("kind") == "bg"), None)
    st = (w or {}).get("state") or ""
    wk = _live_workers().get(short) or {}
    pids = [p for p in (wk.get("pid"), wk.get("replPid")) if type(p) is int and p > 0]
    kids = tv._agent_kids(wk["replPid"]) if pids and type(wk.get("replPid")) is int else []
    if not pids or not re.fullmatch(r"[0-9a-f]{4,64}", short):
        return None, _agent_item(cand, "failed", AGENT_REASON_NOJOB)
    print("ai-tracker: agent upgrade: restarting %s (%s); if this dashboard dies, resume it with: %s"
          % (cand.get("title") or cand["session"][:8], cand["session"], " then ".join(cand.get("command") or [])),
          flush=True)
    rc, _out, _er = _run([spec["path"], "stop", short], AGENT_STOP_TIMEOUT, cwd=os.path.expanduser("~"))
    if rc != 0:
        return None, _agent_item(cand, "failed", AGENT_DAEMON_STOP_FAILED)
    end = time.time() + AGENT_DAEMON_STOP_WAIT
    while True:
        alive = []
        for p in pids:
            try:
                os.kill(p, 0)
                alive.append(p)
            except ProcessLookupError:
                pass
            except OSError:
                alive.append(p)
        if not alive or time.time() >= end:
            break
        time.sleep(0.2)
    if alive:
        return None, _agent_item(cand, "unconfirmed", AGENT_UNCONFIRMED)
    return _agent_clear_thin(tv, cand, kids, st)


def _agent_clear_thin(tv, cand, kids=(), st=""):
    """After the daemon worker is confirmed dead: clear one pane's thin client and sweep orphaned tools.
    (busy, None) once cleared, else (None, the failure item). A pane that closed by itself counts as cleared."""
    r = tv.stop_for_upgrade(cand["tty"], cand["session"], cand["pid"], True)
    if r.get("closed"):                       # the thin client exited by itself after the worker died: stopped
        r = {"confirmed": True, "error": ""}
    if r.get("error"):
        return None, _agent_item(cand, "failed", r["error"])
    if not r.get("confirmed"):
        return None, _agent_item(cand, "unconfirmed", AGENT_UNCONFIRMED)
    tv._agent_sweep(list(kids), getattr(tv.PTYS.get(cand["tty"]), "pid", 0))
    return _agent_was_busy(st, len(kids)), None


def _agent_resume(job, tv, cand, busy, reused=AGENT_RESUME_REUSED):
    body = {"session": cand["target"], "mode": "resume", "cols": cand["cols"], "rows": cand["rows"]}
    if busy:
        body["prompt"] = AGENT_RESUME_PROMPT
    item = _agent_item(cand, "prompted" if busy else "unprompted")
    item["size_before"] = transcript_size(cand["target"])
    code, obj = tv.call_route(tv.open_pty, body)
    obj = obj if isinstance(obj, dict) else {}
    if code == 200 and obj.get("attached"):     # attached to a pane that still runs it: nothing was typed
        item.update(outcome="failed", detail=reused % obj.get("tty"))
    elif code == 200:
        item.update(tty_after=obj.get("tty"), forked=bool(obj.get("forked")))
    else:
        item.update(outcome="failed", detail=str(obj.get("error") or "resume failed (%s)" % code))
    _agent_push(job, item)
    return item


def _agent_verify(job, new, deadline):
    """Poll running() every 2 s until each resumed item is settled or the ONE shared deadline passes."""
    with _AGENT_JLOCK:
        items = [i for i in job["items"] if i["outcome"] in ("prompted", "unprompted")]
    if not items:
        return
    prov = next((s["provider"] for s in agent_specs() if s["id"] == job["agent"]), None)
    while True:
        by_id = {}
        for e in (prov.running() if prov else []):
            if e["id"] not in by_id or e.get("kind") != "bg":
                by_id[e["id"]] = e
        done = True
        for it in items:
            e = by_id.get(it["target"])
            if e is not None and e.get("version") and it["on_version"] is None:   # no version yet: keep waiting
                detail = it["detail"]
                if e.get("kind") == "bg":
                    detail = (detail + " " + AGENT_STILL_DAEMON).strip()
                if e.get("version") != new:
                    detail = (detail + " " + AGENT_VERSION_MISMATCH % (e.get("version"), new)).strip()
                _agent_set(it, on_version=e.get("version") == new, detail=detail)
            if it["outcome"] == "prompted" and not it["prompt_seen"]:
                if user_line_has(it["target"], AGENT_RESUME_PROMPT, since=it["size_before"]):
                    _agent_set(it, prompt_seen=True)
            if it["on_version"] is None or (it["outcome"] == "prompted" and not it["prompt_seen"]):
                done = False
        if done or time.time() >= deadline:
            break
        time.sleep(2)
    for it in items:
        if it["on_version"] is None:
            _agent_set(it, detail=(it["detail"] + " " + AGENT_NOT_CONFIRMED % new).strip())
        if it["outcome"] == "prompted" and not it["prompt_seen"]:
            _agent_set(it, prompt_seen=False, detail=(it["detail"] + " " + AGENT_PROMPT_NOT_SEEN).strip())


def _agent_summary(spec, old, new, items, outside):
    label = spec["label"]
    parts = ["%s is already on %s; nothing new was installed." % (label, new) if old == new
             else "%s %s → %s." % (label, old, new)]
    if not spec["restarts_sessions"]:
        parts.append(AGENT_MSG_NO_RESTART)
    by = lambda *o: [i for i in items if i["outcome"] in o]
    if by("prompted"):
        parts.append("Resumed with “%s” (were working or waiting): %s."
                     % (AGENT_RESUME_PROMPT, ", ".join(_agent_name(i) for i in by("prompted"))))
    if by("unprompted"):
        parts.append("Resumed without a prompt (were idle): %s." % ", ".join(_agent_name(i) for i in by("unprompted")))
    if by("current"):
        parts.append("Already on %s, left running: %s." % (new, ", ".join(
            _agent_name(i) + (" (%s)" % i["detail"] if i["detail"] else "") for i in by("current"))))
    for i in by("not_restarted"):
        parts.append("Not restarted: %s — %s%s." % (_agent_name(i), i["detail"],
                                                     ("; run `%s`" % " then ".join(i["command"])) if i["command"] else ""))
    for i in by("failed", "unconfirmed", "not_shown"):
        parts.append("Failed: %s — %s%s." % (_agent_name(i), i["detail"],
                                              ("; run `%s`" % " then ".join(i["command"])) if i["command"] else ""))
    unseen = [i for i in by("prompted", "unprompted") if i["detail"] and i["on_version"] is True]
    if unseen:
        parts.append("Prompt not seen yet: %s." % "; ".join("%s — %s" % (_agent_name(i), i["detail"]) for i in unseen))
    unconf = [i for i in by("prompted", "unprompted") if i["detail"] and i["on_version"] is not True]
    if unconf:
        parts.append("Not confirmed on %s yet: %s." % (new, "; ".join("%s — %s" % (_agent_name(i), i["detail"])
                                                                      for i in unconf)))
    for i in by("closed"):
        parts.append("%s: %s." % (_agent_name(i), i["detail"]))
    moved = [i for i in by("prompted", "unprompted") if i["tty_after"] and i["tty_after"] != i["tty"]]
    if moved:
        parts.append("Resumed in a new terminal: %s." % ", ".join(_agent_name(i) for i in moved))
    if outside:
        parts.append("Not started here, left alone: %d (%d out of date)."
                     % (len(outside), sum(1 for o in outside if o["out_of_date"])))
    return " ".join(parts)
