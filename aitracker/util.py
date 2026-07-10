import datetime, os, re, subprocess


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
            line = open(gitpath, encoding="utf-8").read().strip()
            head = os.path.join(line[7:].strip(), "HEAD") if line.startswith("gitdir:") else ""
        else:
            head = os.path.join(gitpath, "HEAD")
        ref = open(head, encoding="utf-8").read().strip()
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
