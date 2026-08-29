from .providers.claude import ClaudeProvider
from .providers.auggie import AuggieProvider
from .providers.augment_ext import AugmentVscodeProvider, AugmentCursorProvider
# NOTE: one line, no parenthesised continuation — scripts/bundle.py strips imports
# line-by-line (`^(import |from )`), so a wrapped import leaves its tail behind and
# `make bundle` emits a file that won't parse.
from .store import load_pins, load_notes, load_flags, load_forks, resolve_fork_child, fork_parent_of


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
    # Fork lineage (shared seam — every provider inherits this from one implementation).
    # resolve_fork_child() fast-paths to "" for any sid that isn't a recorded fork parent
    # (a single dict lookup, cheap even across ~200 sessions on every poll); it only does
    # real work — and only ONCE, memoized after — for a genuine parent. Non-Claude
    # providers (Auggie, Augment ext) have no fork concept and no ids ever recorded here,
    # so they get "" for both through this exact same loop, no per-provider branch.
    #
    # The record map is loaded ONCE for the whole listing and handed to both loops.
    # It used to be re-read from disk inside each of them — 2 x N file reads of the
    # same small file per poll (measured: 1900 of one real /api/list's 3963 total
    # open() calls, ~40% of its warm cost, on an endpoint the SPA polls every few
    # seconds). Nothing about the ANSWERS changes; only the number of reads does.
    forks = load_forks()
    continued_as = {}                              # parent sid -> child sid, for sids in `out`
    for s in out:
        child = resolve_fork_child(s.get("id", ""), forks)
        if child:
            continued_as[s["id"]] = child
    # child sid -> parent sid. Deliberately NOT a `{c: p for p, c in continued_as.items()}`
    # reversal: that dict is built above in `out`'s (provider-list) order, which need not
    # agree with fork_parent_of's own insertion-order first-match scan over forks.json
    # (store.py:356-358) if a child were ever claimed by two parents at once -- store.py's
    # creation-time-ordering fix makes that unreachable in practice, but this must not be
    # silently order-dependent if it ever happens again. Calling fork_parent_of() directly
    # keeps the two in agreement BY CONSTRUCTION (same function, same answer) instead of
    # risking a second, independently-ordered derivation.
    #
    # Re-read before the reverse pass: resolve_fork_child WRITES when it first resolves
    # a parent, so a fork that resolved in the loop above is not in the map loaded before
    # it. Without this, the child would render with a dangling "forked from" until the
    # next poll. Thanks to load_forks' mtime/inode memo this is a single stat() — free —
    # in the overwhelmingly common case where nothing above wrote anything.
    forks = load_forks()
    continued_from = {}
    for s in out:
        sid = s.get("id", "")
        parent = fork_parent_of(sid, forks)
        if parent:
            continued_from[sid] = parent
    for s in out:
        sid = s.get("id", "")
        s["pinned"] = sid in pins
        s["note_count"] = len(notes.get(sid, []))
        s["open_flags"] = open_flags.get(sid, 0)  # 🚩 badge + the cross-session flag list
        s["continued_as"] = continued_as.get(sid, "")      # "" unless this session was forked
        s["continued_from"] = continued_from.get(sid, "")  # "" unless this session IS a fork
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
    d = p.parse(sid) if p else None
    if d is None:
        return None
    # Same two keys as all_sessions() above (shared seam, one implementation — Auggie/
    # Augment ext ids never appear in forks.json, so they get "" here too, same as there).
    # Deliberately NOT shipping a title for the other end: that would mean parsing the
    # OTHER session on every ~2s poll of THIS session's detail view — exactly the cost
    # store.resolve_fork_child's memoization exists to avoid, and it doesn't generalize
    # across providers anyway. The client already holds every session's title from its
    # own periodic session-list poll (all_sessions() above carries continued_as/
    # continued_from too), so shipping the id here is enough for it to render the link
    # with no extra round trip.
    d["continued_as"] = resolve_fork_child(sid)
    d["continued_from"] = fork_parent_of(sid)
    # pinned/open_flags/note_count: same shared seam as all_sessions() above, same store.py
    # helpers, one implementation for every provider. Without this the detail header (pinned
    # pill, 🚩 count) has nothing to read and hides — these three small JSON files are already
    # read live on every /api/list poll at this same ~2s cadence, so reading them again here for
    # ONE session's detail view is not a measurable added cost.
    d["pinned"] = sid in set(load_pins())
    d["note_count"] = len(load_notes().get(sid, []))
    d["open_flags"] = sum(1 for f in load_flags() if f.get("session") == sid and not f.get("resolved"))
    return d


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
