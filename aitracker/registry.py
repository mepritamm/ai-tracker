from .providers.claude import ClaudeProvider
from .providers.auggie import AuggieProvider
from .providers.augment_ext import AugmentVscodeProvider, AugmentCursorProvider
from .store import load_pins, load_notes, load_flags


PROVIDERS = [ClaudeProvider(), AuggieProvider(),
             AugmentVscodeProvider(), AugmentCursorProvider()]


def all_sessions():
    """Every available provider's sessions, pinned first then newest-first."""
    out = []
    for p in PROVIDERS:
        try:
            if p.available():
                out += p.list()
        except Exception:
            pass  # one broken provider must not sink the whole list
    pins = set(load_pins())                       # user-pinned ids, read live
    notes = load_notes()                          # per-session note stacks, read live
    open_flags = {}                               # session id -> unresolved 🚩 count, read live
    for f in load_flags():
        if not f.get("resolved"):
            open_flags[f.get("session", "")] = open_flags.get(f.get("session", ""), 0) + 1
    for s in out:
        sid = s.get("id", "")
        s["pinned"] = sid in pins
        s["note_count"] = len(notes.get(sid, []))
        s["open_flags"] = open_flags.get(sid, 0)  # 🚩 badge + the cross-session flag list
    out.sort(key=lambda s: (not s.get("pinned"), -s.get("mtime", 0)))   # pinned first, then newest
    return out


def provider_for(sid):
    """The provider that owns a namespaced session id (longest prefix wins;
    the unprefixed provider is the fallback)."""
    for p in sorted(PROVIDERS, key=lambda x: len(x.prefix), reverse=True):
        if p.prefix and sid.startswith(p.prefix):
            return p
    for p in PROVIDERS:  # default: the unprefixed provider (Claude)
        if p.prefix == "":
            return p
    return None


def parse_any(sid):
    """Route a namespaced session id to the provider that owns it."""
    p = provider_for(sid)
    return p.parse(sid) if p else None


DRILLS = ("output", "diff", "shell", "agent")


def drill(sid, kind, arg):
    """One drill-down view (output/diff/shell/agent) on ONE session, routed to the
    owning provider. This is the seam the /api/output|diff|shell|agent routes call —
    they must never reach into a single provider's session lookup, or every
    namespaced id 404s. None => the session doesn't exist (checked via exists()
    BEFORE calling the drill method, so a bogus id can't reach a provider's empty
    default and read back as 200)."""
    if kind not in DRILLS:
        return None
    p = provider_for(sid)
    if not p:
        return None
    try:
        if not p.exists(sid):
            return None
        return getattr(p, kind)(sid, arg)
    except Exception:
        return None   # one broken session must not close the socket mid-poll


def search_all(q):
    """Merge every provider's search hits and rank them together: title matches
    first, then hits in the user's own prompt, then by recency — across sources."""
    out = []
    for p in PROVIDERS:
        try:
            if p.available():
                out += p.search(q)
        except Exception:
            pass
    out.sort(key=lambda r: (not r.get("titleMatch"), not r.get("inQuery"), -r.get("mtime", 0)))
    return out


# in-session search: scan ONE opened session's own content. Operates on the shared
# detail shape (the dict both parsers emit), so Claude and Auggie are covered by one
# implementation — no per-provider fork. Every item already carries full text, so the
# client opens a hit with the existing modals (openText/openDiff/openCmd) — no indices.
_SEARCH_KINDS = (   # (result kind, detail-dict key, field holding the searchable text)
    ("narration", "narrative", "text"),
    ("prompt",    "requests",  "text"),
    ("file",      "files",     "path"),
    ("command",   "commands",  "cmd"),
    ("todo",      "todos",     "content"),
)


def _snip(s, terms, width=160):
    """A ~one-line window around the first matched term, newlines flattened."""
    low = s.lower()
    hits = [low.find(t) for t in terms if low.find(t) >= 0]
    pos = min(hits) if hits else 0
    start = max(0, pos - 30)
    out = " ".join(s[start:start + width].split())
    return ("…" if start else "") + out + ("…" if start + width < len(s) else "")


def search_detail(d, q):
    """Filter a parsed detail dict `d` for q (keyword AND, case-insensitive) across
    its narration, prompts, files, commands and todos. Pure — the testable seam."""
    ql = (q or "").strip().lower()
    if not ql:
        return {"q": q or "", "total": 0, "hits": []}
    terms = ql.split()
    hits = []
    for kind, key, field in _SEARCH_KINDS:
        for x in (d.get(key) or []):
            s = x.get(field) or ""
            if s and all(t in s.lower() for t in terms):
                hits.append({"kind": kind, "t": x.get("t"), "text": s, "snippet": _snip(s, terms)})
    return {"q": q or "", "total": len(hits), "hits": hits}


def search_session(sid, q):
    """In-session search over the owning provider's parsed detail (shared shape)."""
    if not (q or "").strip():
        return {"q": q or "", "total": 0, "hits": []}
    return search_detail(parse_any(sid) or {}, q)
