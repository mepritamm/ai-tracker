import json, os
from . import config


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
    os.replace(tmp, path)


def load_titles():
    return _load_json(config.TITLES_FILE, {})


def load_pins():
    """Session ids the user pinned to the top of the list — read live, like titles."""
    p = _load_json(config.PINS_FILE, [])
    return p if isinstance(p, list) else []


_TSTATUS = {"completed": "completed", "complete": "completed", "done": "completed",
            "in_progress": "in_progress", "started": "in_progress", "pending": "pending"}


def load_tasks(sid):
    """Current tasks for a session from ~/.claude/tasks/<sid>/<n>.json — the
    TaskCreate/TaskUpdate store that replaced in-transcript TodoWrite. Files are
    updated in place, so this reflects live status. Sorted by numeric id."""
    d = os.path.join(config.TASKS_DIR, sid)
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
    except OSError:
        return []

    def key(f):
        try:
            return int(f[:-5])
        except ValueError:
            return 1 << 30
    out = []
    for f in sorted(files, key=key):
        try:
            t = json.load(open(os.path.join(d, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        subj = isinstance(t, dict) and (t.get("subject") or t.get("content"))
        if not subj:
            continue
        out.append({"content": subj,
                    "status": _TSTATUS.get((t.get("status") or "").lower(), "pending"),
                    "activeForm": t.get("activeForm") or subj,
                    "desc": t.get("description") or ""})
    return out


def load_flags():
    try:
        with open(config.FLAGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_flags(flags):
    # ponytail: full rewrite, no locking — fine for a single-user local tool.
    _save_json(config.FLAGS_FILE, flags)


def load_notes():
    """Per-session note stacks: {session_id: [note_text, ...]} — read live."""
    d = _load_json(config.NOTES_FILE, {})
    return d if isinstance(d, dict) else {}


def save_notes(notes):
    _save_json(config.NOTES_FILE, notes)
