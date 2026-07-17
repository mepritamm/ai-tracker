from .providers.claude import ClaudeProvider
from .providers.auggie import AuggieProvider
from .store import load_pins


PROVIDERS = [ClaudeProvider(), AuggieProvider()]


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
    for s in out:
        s["pinned"] = s.get("id") in pins
    out.sort(key=lambda s: (not s.get("pinned"), -s.get("mtime", 0)))   # pinned first, then newest
    return out


def parse_any(sid):
    """Route a namespaced session id to the provider that owns it."""
    for p in sorted(PROVIDERS, key=lambda x: len(x.prefix), reverse=True):
        if p.prefix and sid.startswith(p.prefix):
            return p.parse(sid)
    for p in PROVIDERS:  # default: the unprefixed provider (Claude)
        if p.prefix == "":
            return p.parse(sid)
    return None


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
