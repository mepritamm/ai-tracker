import datetime, difflib, os, re, subprocess

from .config import LIVE_WINDOW


def safe_path_component(s):
    """Reject a URL-sourced id that could escape its intended directory once joined
    into a filesystem path (`../../etc/passwd`-style traversal, an absolute path or
    separator smuggled in, a NUL byte) — the id portion of a namespaced sid
    (`auggie:<id>`, `augment-vscode:<ws>:<uuid>`, a bare Claude session id, …) is
    untrusted, sourced straight from the URL. Also rejects glob metacharacters
    (`*?[]`): a provider that reaches its lookup via glob.glob() would otherwise
    honour them and disclose an arbitrary sibling session instead of 404ing. Every
    real id across every provider is a bare filename/uuid with no separators, dots-
    run, or glob syntax, so this rejects nothing legitimate. Returns the id
    unchanged if safe, else None — callers treat None as "not found", never raise.

    This is the shared seam: every provider must call this instead of writing its
    own copy — see aitracker/providers/auggie.py and augment_ext.py.
    """
    if not s or "\x00" in s:
        return None
    if "/" in s or "\\" in s or os.sep in s:
        return None
    if os.altsep and os.altsep in s:
        return None
    if ".." in s:
        return None
    if any(c in s for c in "*?[]"):
        return None
    return s


def _dur(a, b):
    if not (a and b):
        return ""
    try:
        import datetime as _dt
        fmt = "%Y-%m-%dT%H:%M:%S"
        s = (_dt.datetime.strptime(b[:19], fmt) - _dt.datetime.strptime(a[:19], fmt)).total_seconds()
    except ValueError:
        return ""
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    return "%dh %dm" % (s // 3600, (s % 3600) // 60)


def _names(items, n=4):
    short = [os.path.basename(p) for p in items[:n]]
    extra = len(items) - n
    return ", ".join(short) + (" +%d more" % extra if extra > 0 else "")


_FILLER = re.compile(
    r"^(can|could|would|will)\s+(you|i|we)\b|"
    r"^(please|kindly|hey|hi|hello|so|ok|okay|now|also|just|lets|let's|"
    r"i\s+want\s+(you\s+)?to|i\s+would\s+like\s+(you\s+)?to|i'?d\s+like\s+(you\s+)?to|"
    r"help\s+me|we\s+need\s+to|i\s+need\s+(you\s+)?to)\b", re.I)


def _short_title(s, maxw=8, maxc=56):
    """Boil a long first prompt down to a short, title-like phrase."""
    s = " ".join((s or "").split())
    s = re.split(r"(?<=[.?!])\s", s)[0]          # first sentence only
    prev = None
    while prev != s:                              # peel leading filler ("Can you", "I want you to"…)
        prev = s
        s = _FILLER.sub("", s).strip(" ,:-")
    words = s.split()
    out = " ".join(words[:maxw])
    if len(out) > maxc:
        out = out[:maxc].rsplit(" ", 1)[0]
    if len(words) > maxw or len(out) < len(s):
        out = out.rstrip(" ,.;:") + "…"
    return (out[:1].upper() + out[1:]) if out else s[:maxc]


def _first_line(s, n=200):
    for ln in s.strip().splitlines():
        ln = ln.strip().lstrip("#").strip()
        if ln:
            return ln[:n]
    return ""


def _git_branch(cwd):
    """Current branch of the checkout at cwd — handles git worktrees, where `.git`
    is a file pointing at the real gitdir. Auggie doesn't record the branch (Claude
    does, in its JSONL), so we read it from the repo to reach parity."""
    if not cwd:
        return ""
    try:
        gitpath = os.path.join(cwd, ".git")
        if os.path.isfile(gitpath):                       # worktree: "gitdir: <path>"
            with open(gitpath, encoding="utf-8") as fh:
                line = fh.read().strip()
            head = os.path.join(line[7:].strip(), "HEAD") if line.startswith("gitdir:") else ""
        else:
            head = os.path.join(gitpath, "HEAD")
        with open(head, encoding="utf-8") as fh:
            ref = fh.read().strip()
        if ref.startswith("ref: refs/heads/"):
            return ref[len("ref: refs/heads/"):]
        return ref[:12]                                   # detached HEAD -> short sha
    except OSError:
        return ""


def _iso_epoch(s):
    try:
        import datetime as _dt
        return _dt.datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=_dt.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _ts_epoch(s):
    """ISO timestamp -> epoch keeping sub-second precision (unlike _iso_epoch, which floors to
    the second). Used to order sessions started in the same second when attributing agents."""
    try:
        import datetime as _dt
        return _dt.datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _window(text, ql, pad=70):
    t = " ".join(text.split())
    i = t.lower().find(ql)
    if i < 0:
        return t[:160]
    s, e = max(0, i - pad), min(len(t), i + len(ql) + pad)
    return ("…" if s > 0 else "") + t[s:e] + ("…" if e < len(t) else "")


TEST_RE = re.compile(r"\b(pytest|jest|vitest|mocha|go test|cargo test|rspec|"
                     r"npm (run )?test|yarn test|pnpm test|mvn test|gradle test|"
                     r"phpunit|tox|nox|ctest|unittest)\b")

COMMIT_MSG_RE = re.compile(r"-m\s+(['\"])(.+?)\1", re.S)

# PR/MR links a session touched: GitHub /pull/N, Bitbucket /pull-requests/N,
# GitLab /merge_requests/N. Scanned out of assistant text + command output so the
# app can list them as clickable links (see collect_prs).
PR_URL_RE = re.compile(r"""https?://[^\s<>"'()\[\]]+?/(?:pull|pull-requests|merge_requests)/\d+""")
# Where a real command can START: line start, a separator (`;` `&` `|`), or an opener that begins a
# NESTED command — `$( … )` / a subshell / backtick, or a loop-or-conditional body (`do`/`then`/`else`).
# Anchoring here keeps a script that merely MENTIONS "gh pr create" from having its output mislabelled
# as a created PR, while still catching the real invocation the bare-line anchor missed:
# `url=$(gh pr create …)` inside a `for r in …; do … done` fan-out over sibling repos.
_CMD_START = r"(?:^|[\n;&|(`]|\b(?:do|then|else)\s)\s*"
# an ACTUAL `gh pr create` invocation (its result URL is a PR this session created).
PR_CREATE_RE = re.compile(_CMD_START + r"gh\s+pr\s+create\b")
# NUMBER-BEARING state signals only — so we never guess a PR's fate from a bare "merged" that might
# describe someone else's PR. A GitHub merge-commit subject (`Merge pull request #N from …`, seen in
# git-log output) or an explicit `gh pr merge/close N`. Number is captured; matched to a PR by num.
PR_MERGED_RE = re.compile(r"Merge pull request #(\d+)\b|" + _CMD_START + r"gh\s+pr\s+merge\s+#?(\d+)\b")
PR_CLOSED_RE = re.compile(_CMD_START + r"gh\s+pr\s+close\s+#?(\d+)\b")


def collect_prs(acc, text, ts, created=False, narr=False):
    """Merge PR/MR URLs found in `text` into acc (url -> entry). `created` = URL from a
    `gh pr create`/MCP result. `narr` = the assistant narrated about it (shown only if it's the
    session's own repo — see pr_worked; a cross-repo status-report mention doesn't count). A
    prompt-only reference passes neither flag → stays hidden. Dedupes by URL; flags are sticky;
    keeps the latest timestamp."""
    if not text:
        return
    for raw in PR_URL_RE.findall(text):
        url = raw.rstrip("/.,);]'\"")
        e = acc.get(url)
        if not e:
            m = re.search(r"([^/]+/[^/]+)/(?:pull|pull-requests|merge_requests)/(\d+)", url)
            e = acc[url] = {"url": url, "repo": m.group(1) if m else "",
                            "num": m.group(2) if m else "", "created": False, "narr": False,
                            "state": "", "t": ts}
        if created:
            e["created"] = True
        if narr:
            e["narr"] = True
        if ts and (not e["t"] or ts > e["t"]):
            e["t"] = ts


def note_pr_states(states, text):
    """Scan `text` for number-bearing merge/close signals and record num -> state in `states`.
    Merged wins over closed (a merged PR is also closed, but 'merged' is the meaningful state)."""
    if not text:
        return
    for a, b in PR_MERGED_RE.findall(text):
        n = a or b
        if n:
            states[n] = "merged"
    for n in PR_CLOSED_RE.findall(text):
        if n and states.get(n) != "merged":
            states[n] = "closed"


def pr_worked(e, cwd):
    """True if the session generated the PR, or narrated about it AND it lives in the session's
    own repo. Excludes cross-repo status-report mentions and prompt-only references."""
    if e["created"]:
        return True
    if not e.get("narr") or not cwd:
        return False
    name = (e["repo"] or "").rsplit("/", 1)[-1]
    return bool(name) and any(s == name or s.startswith(name + "-") for s in cwd.split("/"))


def prs_sorted(acc, states=None):
    """Created PRs first, then most-recently-seen — the shared shape's `prs` list. Overlays merged/
    closed state from `states` (num -> state) captured this session. ponytail: matched by num alone;
    two repos sharing a PR number in one session would collide — add repo to the key if that bites."""
    if states:
        for e in acc.values():
            st = states.get(e.get("num"))
            if st:
                e["state"] = st
    return sorted(acc.values(), key=lambda p: (p["created"], p["t"] or ""), reverse=True)


def pr_summary(prs, states=None):
    """(num, url, repo, state) for the session-LIST dict's one representative CREATED pull
    request — reuses prs_sorted's created-first/most-recent ordering and state overlay (the
    same primitives the detail path's `prs` panel is built from) rather than re-deriving
    either. Only entries with created=True count: a PR the session merely referenced or
    narrated about (pr_worked's broader detail-only semantics) must not light up a board
    tile. Returns (None, None, None, "") when the session created no PR, so the list dict's
    fields come back falsy rather than a stale or spurious entry. The one place this gets
    computed — same precedent as todo_summary below (total/done/current derived once, shared
    by every provider's list function)."""
    top = next((p for p in prs_sorted(prs, states) if p["created"]), None)
    if not top:
        return None, None, None, ""
    return top.get("num") or None, top.get("url") or None, top.get("repo") or None, top.get("state") or ""


def context_window(current, limit):
    """The shared `context` shape every provider emits: `current` is the context the
    model is CARRYING RIGHT NOW — input + cache-read + cache-creation tokens off the
    LATEST turn's usage block, the "am I about to run out" number. This is deliberately
    NOT the same as the session-cumulative `tokens` dict (which sums every turn's usage
    across the whole session and only grows). `limit` is the model/session's context-
    window size IF the provider's own logs state one — never guessed. `pct` is derived
    only when both are known; a provider whose transcript carries no limit (Claude's
    JSONL usage blocks don't) reports `limit`/`pct` as None rather than a fabricated
    denominator. Callers must treat None as "unknown", not zero.
    """
    pct = None
    if isinstance(current, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        pct = round(current * 100.0 / limit, 1)
    return {"current": current, "limit": limit, "pct": pct}


def push_when(has_drain, mtime, now):
    """When a ▶ pushed note will actually reach this session — the server owns this policy,
    the client only renders it. One helper, both providers.

    "turn" — the session is live, so its next turn-end hook delivers within seconds.
    "wake" — it's idle: no turn is in flight to end, so the note waits for the next prompt
             or resume. Real, but not imminent — the UI must not promise "this turn".
    "none" — the tool has no drain hook at all; the note queues but you deliver it by hand.
    """
    if not has_drain:
        return "none"
    return "turn" if (now - mtime) < LIVE_WINDOW else "wake"


def cmd_kind(c):
    if re.search(r"git\s+commit", c):
        return "commit"
    if TEST_RE.search(c):
        return "test"
    if re.search(r"\b(pip install|npm i\b|npm install|yarn add|pnpm add|poetry add|"
                 r"uv add|uv pip|brew install|apt-get|cargo add)\b", c):
        return "install"
    if re.search(r"\b(make|docker|build|compile|tsc|webpack|vite build)\b", c):
        return "build"
    if re.match(r"\s*git\b", c):
        return "git"
    return "cmd"


def todo_summary(todos):
    """(total, done, current-label-or-None, current-index-or-None) from a list of
    normalized todo dicts ({"content"/"activeForm"/"status"} — the shape both
    providers already emit: Claude's store.load_tasks() and Auggie's task-tree
    resolver). The one place this gets computed, so the session-list dict's
    todo_total/todo_done/todo_current/todo_current_index (registry.py's shared
    seam) aren't derived twice, once per provider. current_index is the same
    todo's 0-based position in `todos` that current was picked from (the FIRST
    in_progress one) — kept in lockstep so a tick-highlighter can point at the
    exact row the label came from."""
    total = len(todos)
    done = sum(1 for t in todos if t.get("status") == "completed")
    current_index = next((i for i, t in enumerate(todos) if t.get("status") == "in_progress"), None)
    cur = todos[current_index] if current_index is not None else None
    current = (cur.get("activeForm") or cur.get("content") or None) if cur else None
    return total, done, current, current_index


def now_phrase(s, maxc=60):
    """A short board-tile "now" phrase: one line, truncated with an ellipsis rather than
    wrapped. Shared by every provider's session-list `now_line` field (providers/claude.py,
    auggie.py, augment_ext.py) so the truncation rule lives in exactly one place, not
    forked per provider. `s` is already a short, pre-selected signal (an in-progress todo's
    label, or a tail-read narration snippet) -- this only bounds its on-screen length."""
    s = _first_line(s or "", 400)
    if len(s) > maxc:
        cut = s[:maxc].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        s = (cut or s[:maxc]) + "…"
    return s


def todo_times_approximate(provider_type):
    """Whether this provider's todo start/end times are approximate (name-matched or unavailable)
    rather than exact. Always a bool on the detail dict, even with no todos at all, so the UI
    never has to special-case a provider.
    - "claude": False (exact ID join from task-store file stem == TaskUpdate's taskId)
    - "auggie": True (name-matched against chatHistory task ids from add_tasks/update_tasks echoes)
    - "augment": True (no timing source available; chat transcript in LevelDB unreadable stdlib-only)
    This is the ONE definition point shared by all providers; it lives here so the semantics
    stay consistent if the rule ever changes."""
    return provider_type != "claude"


def unified(old, new, cap=20000):
    """Unified diff between two strings, each capped to keep payloads sane.
    Shared by every provider that reconstructs an edit from the tool input it
    logged (Claude: Write/Edit/MultiEdit; Auggie: save-file/str-replace-editor)."""
    old, new = (old or "")[:cap], (new or "")[:cap]
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(), "before", "after", lineterm=""))
