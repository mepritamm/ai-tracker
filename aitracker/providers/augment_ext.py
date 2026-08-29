"""Augment VSCode/Cursor extension sessions.

Same product family as Auggie (~/.augment) but a different disk layout: the
extension lives inside the IDE's per-workspace storage and writes JSON for
tasks + agent-edit checkpoints while the chat transcript (user/assistant
turns) is kept in a LevelDB kv-store — binary, unreadable stdlib-only. So
this provider surfaces what's honestly available (todos + files-touched +
metadata) and pins a note into `narrative` explaining what isn't.

One "session" per task file (matches Auggie CLI's per-transcript rows);
grouped visually in the sidebar by workspace via `cwd`. Two providers so
the source badge distinguishes the IDE — mirrors Claude's per-surface
`claude-desktop` / `cli` / `claude-vscode` split under one product.
"""
import glob, json, os, time, urllib.parse
from .. import config
from ..store import load_titles, load_notes, _load_json
from ..util import _first_line, push_when, _window, _git_branch, safe_path_component, context_window, todo_summary
from .base import Provider


_STATE_TO_TODO = {"COMPLETE": "completed", "COMPLETED": "completed", "DONE": "completed",
                  "IN_PROGRESS": "in_progress", "STARTED": "in_progress",
                  "NOT_STARTED": "pending", "CANCELLED": "pending"}


def _ide_root(kind):
    """Late-bound so tests can repoint. `kind` ∈ {'vscode','cursor'}."""
    return config.VSCODE_WS_ROOT if kind == "vscode" else config.CURSOR_WS_ROOT


def _decode_folder(folder_uri):
    """workspace.json's `folder` is `file:///Users/foo/bar%20baz` — return `/Users/foo/bar baz`."""
    if not folder_uri:
        return ""
    if folder_uri.startswith("file://"):
        folder_uri = folder_uri[len("file://"):]
    return urllib.parse.unquote(folder_uri)


def _scan_workspaces(kind):
    """Yield (ws_hash, aug_dir, folder) for every workspace with Augment extension state."""
    root = _ide_root(kind)
    if not root or not os.path.isdir(root):
        return
    for ws in os.listdir(root):
        aug_dir = os.path.join(root, ws, "Augment.vscode-augment")
        if not os.path.isdir(aug_dir):
            continue
        ws_json = os.path.join(root, ws, "workspace.json")
        folder = ""
        if os.path.isfile(ws_json):
            try:
                folder = _decode_folder(json.load(open(ws_json, encoding="utf-8")).get("folder", ""))
            except (OSError, ValueError):
                folder = ""
        yield ws, aug_dir, folder


def _tasks_dir(aug_dir):
    return os.path.join(aug_dir, "augment-user-assets", "task-storage", "tasks")


def _shards_dir(aug_dir):
    return os.path.join(aug_dir, "augment-user-assets", "agent-edits", "shards")


def _iter_tasks(aug_dir):
    """Yield (task_uuid, task_dict, mtime) for every task file. Malformed tasks skipped."""
    d = _tasks_dir(aug_dir)
    if not os.path.isdir(d):
        return
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        try:
            mt = os.path.getmtime(p)
            t = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        yield t.get("uuid") or fn, t, mt


def _files_touched(aug_dir):
    """Distinct absolute file paths touched, latest first, from agent-edit shards.
    Shard shape: {id, checkpoints:{<shard-uuid>:<abs-path>: <chkpt>}, metadata:{lastModified,…}}."""
    sd = _shards_dir(aug_dir)
    if not os.path.isdir(sd):
        return []
    latest = {}   # path -> mtime
    for fn in os.listdir(sd):
        p = os.path.join(sd, fn)
        try:
            shard = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mt = ((shard.get("metadata") or {}).get("lastModified") or 0) / 1000.0
        for key in (shard.get("checkpoints") or {}).keys():
            # key is "<shard-uuid>:<abs-path>" — split off the first colon
            _, _, path = key.partition(":")
            if not path:
                continue
            if path not in latest or mt > latest[path]:
                latest[path] = mt
    return [{"path": p, "t": t or ""} for p, t in
            sorted(latest.items(), key=lambda kv: kv[1] or 0, reverse=True)]


def _resolve_subtasks(root, allmap, seen=None):
    """Depth-first flatten of subTasks (uuid refs) into todo dicts. Same shape as Auggie CLI.
    Seeds the current root's uuid into `seen` so a subtree pointing back at its own root
    (malformed but observed in the wild) can't recurse into it."""
    seen = seen or set()
    ru = root.get("uuid")
    if ru:
        seen.add(ru)
    out = []
    for uu in (root.get("subTasks") or []):
        if uu in seen or uu not in allmap:
            continue
        seen.add(uu)
        t = allmap[uu]
        out.append({"content": t.get("name") or t.get("description") or "",
                    "status": _STATE_TO_TODO.get((t.get("state") or "").upper(), "pending"),
                    "t": "",
                    # Same shape as Claude's todos, but honestly null: see auggie.py's
                    # _auggie_resolve for why this task-storage family can't join a real
                    # start/end pair onto a todo (task-storage's own lastUpdated is one
                    # instant, not a range, and the extension has no separate event log).
                    "started_at": None, "ended_at": None})
        out += _resolve_subtasks(t, allmap, seen)
    return out


def _todos_from(task, allmap):
    """The task's own subTasks → todo list. Empty for a leaf task."""
    return _resolve_subtasks(task, allmap)


def _title_for(task, folder):
    """Skip the boilerplate 'Current Task List' root: use its first subTask's name if any,
    else the folder's basename, else 'Augment session'."""
    n = (task.get("name") or "").strip()
    if n and n != "Current Task List":
        return n
    return os.path.basename(folder) if folder else "Augment session"


def _mtime_of(task, aug_dir):
    """Prefer task.lastUpdated (ms since epoch), fall back to filesystem mtime of shards."""
    lu = task.get("lastUpdated")
    if isinstance(lu, (int, float)) and lu > 0:
        return lu / 1000.0
    sd = _shards_dir(aug_dir)
    if os.path.isdir(sd):
        try:
            return max(os.path.getmtime(os.path.join(sd, f)) for f in os.listdir(sd)) or 0
        except (OSError, ValueError):
            pass
    return 0


def _list(kind, prefix, src_label):
    """Session-summary dicts for one IDE. Same shape as list_auggie()."""
    titles = load_titles()
    out = []
    for ws, aug_dir, folder in _scan_workspaces(kind):
        # ONE pass over the task files, materialized so the todo-tree lookup below can
        # share it. There used to be a SEPARATE `allmap` built from a second _iter_tasks()
        # pass here — it just opened and json-parsed every task file a second time on
        # every /api/list. Measured on real data: 665 Augment tasks read as 1330 opens,
        # ~0.12s of a 0.40s warm /api/list (~30%). Building allmap from THIS SAME pass
        # (already fully in memory) costs nothing extra — no second read, same list.
        tasks = list(_iter_tasks(aug_dir))
        allmap = {u: t for u, t, _ in tasks}
        for uu, task, mt_file in tasks:
            gid = "%s%s:%s" % (prefix, ws, uu)
            mt = _mtime_of(task, aug_dir) or mt_file
            title = _title_for(task, folder)
            todo_total, todo_done, todo_current, todo_current_index = todo_summary(_todos_from(task, allmap))
            out.append({
                "id": gid, "project": os.path.basename(folder) if folder else "Augment", "cwd": folder,
                "title": titles.get(gid) or title,
                "prompt": (task.get("description") or "")[:200],
                "source": src_label, "mtime": mt,
                "agent": False, "group": "", "groupLabel": "", "parentId": "", "bg": 0, "first": 0,
                "waiting": False, "ended": (task.get("state") or "").upper() in ("COMPLETE", "COMPLETED", "DONE"),
                "todo_total": todo_total, "todo_done": todo_done, "todo_current": todo_current,
                "todo_current_index": todo_current_index,
            })
    return out


def _parse(kind, prefix, src_label, sid):
    """Detail dict for one task. Same shape as parse_auggie()."""
    if not sid.startswith(prefix):
        return None
    rest = sid[len(prefix):]
    ws, _, uu = rest.partition(":")
    if not ws or not uu:
        return None
    # both components are untrusted, straight from the URL, and get joined into a
    # filesystem path below (aug_dir, ws_json) — reject a traversal/separator/glob
    # payload here rather than letting it reach os.path.join. Same seam Auggie uses.
    ws = safe_path_component(ws)
    uu = safe_path_component(uu)
    if ws is None or uu is None:
        return None
    root = _ide_root(kind)
    aug_dir = os.path.join(root, ws, "Augment.vscode-augment")
    if not os.path.isdir(aug_dir):
        return None
    # locate this task
    allmap = {u: t for u, t, _ in _iter_tasks(aug_dir)}
    task = allmap.get(uu)
    if not task:
        return None
    # workspace folder
    ws_json = os.path.join(root, ws, "workspace.json")
    folder = ""
    if os.path.isfile(ws_json):
        try:
            folder = _decode_folder(json.load(open(ws_json, encoding="utf-8")).get("folder", ""))
        except (OSError, ValueError):
            folder = ""

    todos = _todos_from(task, allmap)
    done = sum(1 for x in todos if x["status"] == "completed")
    files = _files_touched(aug_dir)
    title = load_titles().get(sid) or _title_for(task, folder)
    mt = _mtime_of(task, aug_dir)
    now = time.time()

    # Narrative-lite: one system note explaining the LevelDB gap, then a synthetic
    # entry per file-touched shard so the timeline shows *something* rather than being
    # empty. The SPA renders narrative as-is (newest-first), so no client change needed.
    NOTE = ("Augment %s extension session. Chat transcript lives in the extension's "
            "augment-kv-store (LevelDB) which the tracker cannot read stdlib-only. "
            "What follows is what IS available on disk: todos from task-storage, and "
            "files touched from agent-edit checkpoints." % kind.upper())
    narrative = [{"t": now, "text": NOTE}]

    return {
        "meta": {"cwd": folder, "title": title, "source": src_label, "entrypoint": src_label,
                 "gitBranch": _git_branch(folder), "model": ""},
        "todos": todos,
        "files": files, "reads": [], "commands": [], "commits": [], "tests": [],
        "requests": [], "agents": [], "agents_bg": [], "agent_sessions": [], "shells": [],
        "decisions": [], "waiting": False,
        "prs": [],
        "narrative": narrative,
        "message": NOTE[:2000],
        "tokens": {"in": 0, "out": 0},
        # no per-turn usage data survives stdlib-only (chat transcript is in the extension's
        # LevelDB kv-store) — honestly empty, never a fabricated occupancy/limit.
        "context": context_window(None, None),
        "counts": {"done": done, "todos": len(todos), "created": 0, "edited": len(files),
                   "read": 0, "commits": 0, "tests": 0,
                   "tests_failed": 0, "errors": 0, "agents": 0, "searches": 0},
        "overview": {
            "where": os.path.basename(folder) if folder else "Augment",
            "goal": task.get("description") or task.get("name") or "",
            "now": (_first_line(NOTE) if not files else "▶ edited %d file(s)" % len(files)),
            "now_kind": "file" if files else "narration",
            "sofar": (("%d/%d tasks done" % (done, len(todos))) if todos
                      else ("%d file(s) touched" % len(files) if files else "No activity recorded yet.")),
            "commits": [],
        },
        "mtime": mt,
        "now": now,
        "notes": load_notes().get(sid, []),
        "push_when": push_when(False, 0, 0),
    }


def _search(kind, prefix, src_label, q, limit=500):
    """Match task name/description; emits the FULL shared search-result shape —
    {id, project, title, agent, matches, snippet, inQuery, titleMatch, mtime} —
    same as ClaudeProvider.search()/search_auggie(), so renderSide() (web/app.js)
    can draw an augment-ext hit exactly like any other source."""
    ql = (q or "").strip().lower()
    if not ql:
        return []
    terms = ql.split()
    hits = []
    for ws, aug_dir, folder in _scan_workspaces(kind):
        for uu, task, mt_file in _iter_tasks(aug_dir):
            title = _title_for(task, folder)
            body = task.get("description") or ""
            tl, bl = title.lower(), body.lower()
            hay = tl + " " + bl
            if not all(t in hay for t in terms):
                continue
            title_match = all(t in tl for t in terms)
            in_query = bool(body) and all(t in bl for t in terms)
            count = sum(hay.count(t) for t in terms)
            if ql in bl:
                snippet = _window(body, ql)
            else:
                hit = next((t for t in terms if t in bl), None)
                snippet = _window(body, hit) if hit else ""
            gid = "%s%s:%s" % (prefix, ws, uu)
            hits.append({
                "id": gid, "project": os.path.basename(folder) if folder else "Augment",
                "title": title, "agent": False,
                "matches": count, "snippet": snippet, "inQuery": in_query,
                "titleMatch": title_match,
                "mtime": _mtime_of(task, aug_dir) or mt_file,
            })
            if len(hits) >= limit:
                return hits
    return hits


class _AugmentExtBase(Provider):
    """Shared logic; the two concrete providers just carry (kind, prefix, src_label)."""
    kind = "vscode"        # overridden
    prefix = "augment-vscode:"
    src_label = "augment-vscode"

    def available(self):
        root = _ide_root(self.kind)
        return bool(root) and os.path.isdir(root)

    def list(self):
        return _list(self.kind, self.prefix, self.src_label)

    def parse(self, sid):
        return _parse(self.kind, self.prefix, self.src_label, sid)

    def search(self, q):
        return _search(self.kind, self.prefix, self.src_label, q)


class AugmentVscodeProvider(_AugmentExtBase):
    kind = "vscode"
    prefix = "augment-vscode:"
    src_label = "augment-vscode"


class AugmentCursorProvider(_AugmentExtBase):
    kind = "cursor"
    prefix = "augment-cursor:"
    src_label = "augment-cursor"
