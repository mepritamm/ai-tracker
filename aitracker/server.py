import json, os, sys, errno, webbrowser, base64, hmac, hashlib, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import config                       # referenced live (config.AUTH) so tests/env see one source
from .config import LIVE_WINDOW, NARR_PAGE
from .page import build_page
from .registry import all_sessions, parse_any, search_all, search_session, drill
from .store import load_flags, save_flags, load_titles, load_pins, load_notes, save_notes, _load_json, _save_json
# TITLES_FILE/PINS_FILE (below) are referenced live as config.TITLES_FILE/config.PINS_FILE at
# their write sites, never imported by name -- a copied name freezes the value at import
# time, so a caller that repoints config.TITLES_FILE (e.g. a test's temp-dir override) would
# be silently ignored. store.py and the providers already follow this "config.NAME, not a
# copied import" rule (see CLAUDE.md); this file used to be the one exception for exactly
# these two paths -- FLAGS_FILE/NOTES_FILE were never actually at risk here since their real
# write path (store.save_flags()/save_notes()) already reads config.FLAGS_FILE/config.NOTES_FILE
# live on its own, but TITLES_FILE/PINS_FILE had no such protection.

# ponytail: route seam for optional feature modules (the terminal tiers). A module registers its
# own routes here on import instead of server.py forking a per-feature elif chain. See the loader
# at the bottom of this file.
EXTRA_GET = {}    # path -> fn(handler, parsed_url)
EXTRA_POST = {}   # path -> fn(handler, parsed_url, body)

# --- login gate: a styled login page + a signed-cookie session (routes accept the cookie OR HTTP Basic,
# so curl -u still works). One credential — config.AUTH (TRACKER_AUTH) — compared in constant time. ---
_COOKIE_TTL = 43200  # 12h

def _sign(msg):
    return hmac.new(config.AUTH.encode(), msg.encode(), hashlib.sha256).hexdigest()

def _make_token(ttl=_COOKIE_TTL):
    exp = str(int(time.time()) + ttl)
    return exp + "." + _sign(exp)

def _token_ok(tok):
    try:
        exp, sig = tok.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(exp)):   # constant-time — a forged/edited cookie fails
        return False
    try:
        return int(exp) > int(time.time())          # not expired
    except ValueError:
        return False

# theme tokens duplicated here (the login page is server-rendered, outside the SPA's app.css) so it's
# fully legible in Light too. Keep in sync with web/app.css :root / html.light.
_LOGIN_CSS = """:root{--app:#0c0f15;--card:#0e121a;--line:#1c2330;--line3:#2c333f;--text:#e6edf3;--muted:#8b98a8;--dim:#6b7585;--blue:#4c8dff;--red:#f85149;--ring1:#4c8dff;--ring2:#29d398}
html.light{--app:#f4efe3;--card:#fbf8f0;--line:#e3d9c4;--line3:#d8ccae;--text:#2b2820;--muted:#6f6754;--dim:#958c76;--blue:#2f6bd8;--red:#c53d2c;--ring1:#2f6bd8;--ring2:#1f9d6b}
*{box-sizing:border-box}html,body{height:100%;margin:0;background:var(--app);color:var(--text);font-family:'Source Sans 3',system-ui,sans-serif;display:flex;align-items:center;justify-content:center}
.lw{width:min(92vw,400px);padding:20px}
.lc{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:30px 26px 24px;box-shadow:0 14px 44px rgba(0,0,0,.35);text-align:center}
.lt{font-size:19px;font-weight:700;margin:12px 0 3px}.ls{font-size:12.5px;color:var(--muted);margin-bottom:22px}
.lf{text-align:left;margin-bottom:13px}.lf label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);margin-bottom:5px}
.lf input{width:100%;background:var(--app);border:1px solid var(--line3);color:var(--text);border-radius:9px;padding:11px 12px;font-size:14px;outline:none}
.lf input:focus{border-color:var(--blue)}
.lb{width:100%;margin-top:6px;min-height:46px;padding:12px;border:0;border-radius:10px;background:linear-gradient(90deg,var(--ring1),var(--ring2));color:#fff;font-weight:700;font-size:14px;cursor:pointer}
.lb:active{opacity:.9}.le{color:var(--red);font-size:12.5px;min-height:17px;margin-top:9px}
.lfoot{margin-top:16px;font-size:11px;color:var(--dim);line-height:1.5}"""

_LOGO = ("<svg viewBox='0 0 32 32' xmlns='http://www.w3.org/2000/svg' width=42 height=42>"
  "<rect x='2.5' y='2.5' width='27' height='27' rx='8' fill='#11161f' stroke='#f5b443' stroke-width='2'/>"
  "<path d='M6.5 18h3.6l2-5.6 3 10 2.2-6.3 1.5 1.9H25' fill='none' stroke='#f5b443' stroke-width='2.3' stroke-linecap='round' stroke-linejoin='round'/>"
  "<circle cx='23.4' cy='9' r='3' fill='#29d398'/></svg>")

def login_page():
    return ("<!doctype html><html><head><meta charset=utf-8>"
      "<meta name=viewport content='width=device-width,initial-scale=1'>"
      "<title>AI Session Tracker — Sign in</title><meta name=theme-color content='#0c0f15'>"
      "<script>try{if(localStorage.theme==='light')document.documentElement.classList.add('light')}catch(e){}</script>"
      "<style>" + _LOGIN_CSS + "</style></head><body>"
      "<div class=lw><form class=lc onsubmit='return doLogin(event)'>" + _LOGO +
      "<div class=lt>AI Session Tracker</div><div class=ls>Private dashboard · protected access</div>"
      "<div class=lf><label>Username</label><input id=lu autocomplete=username autofocus></div>"
      "<div class=lf><label>Password</label><input id=lp type=password autocomplete=current-password></div>"
      "<button class=lb type=submit><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' focusable='false' style='width:1em;height:1em;vertical-align:-0.15em'><path d='M5 11h14v9H5z'/><path d='M8 11V7a4 4 0 0 1 7.5-2'/></svg> Unlock dashboard</button>"
      "<div class=le id=lerr></div>"
      "<div class=lfoot>HTTP Basic via <code>TRACKER_AUTH</code> · constant-time · read-only</div>"
      "</form></div>"
      "<script>async function doLogin(e){e.preventDefault();"
      "var r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},"
      "body:JSON.stringify({user:document.getElementById('lu').value,pass:document.getElementById('lp').value})});"
      "if(r.ok){location.reload()}else{document.getElementById('lerr').textContent='Incorrect username or password'}"
      "return false}</script></body></html>")


def _term_count():
    """Live terminal count for the sidebar's "Manage terminals" badge, or None when the count
    would be meaningless to show.

    Folded into /api/list's response the SAME way the server clock is (see the X-Server-Now
    comment at the /api/list route below): a response header, not a body reshape, so the sidebar
    gets this on its EXISTING poll instead of a second timer hitting GET /api/term/list every
    tick (a 403 on every one of those wherever the feature is off, purely for cosmetics — the
    gap this closes).

    Degrades to None -- the caller omits the header entirely -- in exactly the states where the
    Manage terminals panel itself would 403 on open: TRACKER_TERMINAL=0, or reachable beyond
    loopback without TRACKER_AUTH configured (term_gate.allowed() is the SAME check GET
    /api/term/list's own term_gate.guard() makes; conventions rule 5 -- server decides, client
    only renders what it's given, never re-derives the gate itself).

    term_vt/term_gate are optional modules while the terminal tiers are built in parallel (see
    the loader at the bottom of this file) -- this file doesn't own them, so it only calls the
    accessor they already export (term_vt._live_count()) rather than reaching into their
    internals. Deliberately does NOT import them here: the loader below already imports both,
    unconditionally, at server startup, so by request time they're either sitting in sys.modules
    (real bug inside one of them would already have crashed the loader, not this function) or
    they were never there to begin with -- a parallel-dev worktree missing the module, or the
    flattened `make bundle` standalone script, which regex-strips that loader entirely and ships
    without the terminal feature (see scripts/bundle.py's comment on it). A plain sys.modules
    lookup handles every one of those states as the same "not available -> None" outcome, with
    no import attempt of its own -- which also means this function carries none of the
    package-relative-import text the bundler has to special-case for the loader below (that
    string-replace already asserts nothing ELSE in this file needs the same treatment)."""
    term_gate = sys.modules.get("aitracker.term_gate")
    term_vt = sys.modules.get("aitracker.term_vt")
    if term_gate is None or term_vt is None:
        return None
    if not term_gate.allowed():
        return None
    # _live_count() iterates the module-global PTYS dict; open_pty()/_reap() mutate it from other
    # request threads (ThreadingHTTPServer), so the iteration must run under term_vt._LOCK -- the
    # same discipline _live_list()'s docstring states and the one pre-existing caller (the 429
    # path above open_pty(), term_vt.py ~2079-2081) already follows. Skipped: the _reap() sibling
    # call that path also makes under the lock. This is a read-only display count on a 5s poll,
    # not a slot-allocation decision, so a pty that finished moments ago and hasn't been reaped
    # yet is an acceptable staleness -- and it's already excluded from the number regardless,
    # since _live_count()'s own `if not p.done` filter drops it whether or not it's still resident
    # in PTYS. Reaping here would just do another route's cleanup work on every poll tick for no
    # change in the reported value.
    with term_vt._LOCK:
        return term_vt._live_count()


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200, headers=None):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # client closed the connection (normal: a newer 2s poll superseded
            # this one, or the tab closed). Nothing to send; don't crash.
            pass

    def _cookie_token(self):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "ai_auth":
                return v
        return ""

    def _authok(self):
        """True if the request may proceed: no auth configured, a valid signed cookie, or valid HTTP
        Basic (so curl -u keeps working). No side effects — the caller renders the response."""
        cred = config.AUTH
        if not cred:
            return True
        tok = self._cookie_token()
        if tok and _token_ok(tok):
            return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Basic "):
            try:
                dec = base64.b64decode(got[6:]).decode("utf-8", "replace")
            except Exception:
                dec = ""
            if hmac.compare_digest(dec, cred):   # constant-time — don't leak length/prefix via ==
                return True
        return False

    def _serve_login(self):
        body = login_page().encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_login(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except (ValueError, TypeError):
            body = {}
        creds = (body.get("user") or "") + ":" + (body.get("pass") or "")
        if not config.AUTH or not hmac.compare_digest(creds, config.AUTH):
            return self._json({"ok": False}, 401)
        out = b'{"ok":true}'
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie",
                             "ai_auth=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (_make_token(), _COOKIE_TTL))
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        p = urlparse(self.path)
        if not self._authok():
            # HTML routes -> styled login page; API -> 401 (the SPA's polls carry the cookie once in)
            return self._json({"error": "auth required"}, 401) if p.path.startswith("/api") else self._serve_login()
        if p.path == "/":
            body = build_page().encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                # The whole SPA is inlined here and rebuilt at each server start, so a
                # restart bakes a new page. Without this, browsers heuristically cache the
                # doc and a plain reload serves the OLD page (new panels/JS never show until
                # a hard refresh). no-store => every reload fetches the current page.
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif p.path == "/api/list":
            # Liveness is one clock: /api/session already ships a `now` field (each
            # provider's parse() stamps time.time()) and the detail pane renders live/done
            # off it. /api/list has no per-item slot for that (it's a bare array, one entry
            # per session, no "endpoint-level" field) so the server's clock rides an HTTP
            # header instead of reshaping the body into {"sessions": [...], "now": ...} --
            # that would force every consumer (the SPA's fetch, every existing /api/list
            # test) to unwrap an object for a value that's about the RESPONSE, not any one
            # session. The sidebar reads this header and uses it for every now-s.mtime<LIVE
            # check, so it can never compute liveness from a different clock than the detail
            # pane does (see .claude/rules/conventions.md rule 5 -- server owns policy, client renders it).
            # X-Term-Count rides the same header-not-body trick, for the same reason -- see
            # _term_count()'s docstring above for why a header, and why it degrades to None/omitted.
            headers = {"X-Server-Now": str(time.time())}
            tc = _term_count()
            if tc is not None:
                headers["X-Term-Count"] = str(tc)
            self._json(all_sessions(), headers=headers)
        elif p.path == "/api/flags":
            self._json(load_flags())
        elif p.path == "/api/config":
            # The Config dialog's live read: every config.json-overridable setting's current
            # effective value (config.json > env > default -- see config.py's big module
            # comment), whether config.json currently overrides it, and whether it needs a
            # restart to apply. Read live, no caching -- this is a small dict, not a hot
            # path. config.py holds no filesystem access of its own (see its module
            # comment); this route loads config.json via the SAME store._load_json already
            # imported for flags/titles/pins/notes, then applies it (so the plain
            # LIVE_WINDOW/TERM_RENDERER/MAX_TERMS/TERMINAL globals reflect a hand-edited
            # config.json too, not just a browser-made change) before reporting it.
            overrides = _load_json(config.CONFIG_FILE, {})
            config.apply_overrides(overrides)
            snap = config.snapshot(overrides)
            # AUTH_SET: the Server tab's "Auth" row (readonlyField in ext_cr_dialogs.js)
            # reads this to show honestly whether TRACKER_AUTH is currently configured --
            # never the value itself, same "set"/"not set" contract that row has always had.
            snap["AUTH_SET"] = bool(config.AUTH)
            self._json(snap)
        elif p.path == "/api/tunnel":
            # Config dialog's Tunnel section, default read: URL (not sensitive) plus only
            # WHETHER a user/password are staged -- never the raw values. See config.py's
            # "Tunnel management" section for the full design rationale.
            overrides = _load_json(config.CONFIG_FILE, {})
            self._json(config.tunnel_public(overrides))
        elif p.path == "/api/tunnel/reveal":
            # The ONE route allowed to return the raw tunnel credential -- reached only by
            # the dialog's explicit "Show" action, already gated by the same _authok() check
            # every other route in do_GET goes through (see the top of this method) -- an
            # unauthenticated caller never reaches this line at all.
            overrides = _load_json(config.CONFIG_FILE, {})
            self._json(config.tunnel_reveal(overrides))
        elif p.path == "/api/search":
            self._json(search_all(parse_qs(p.query).get("q", [""])[0]))
        elif p.path == "/api/diff":
            qs = parse_qs(p.query)
            sid, fp = qs.get("id", [""])[0], qs.get("file", [""])[0]
            ops = drill(sid, "diff", fp)          # provider seam, not one source's lookup
            if ops is None:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json({"file": fp, "ops": ops})
        elif p.path == "/api/file":
            # ponytail: local single-user tool — reads the file at the given path
            # (paths come from the session's own edits) with a size cap.
            fp = parse_qs(p.query).get("path", [""])[0]
            try:
                if not fp or not os.path.isfile(fp):
                    self._json({"error": "not found", "content": ""}, 404)
                elif os.path.getsize(fp) > 500_000:
                    self._json({"error": "file too large to render", "content": ""})
                else:
                    with open(fp, encoding="utf-8", errors="replace") as fh:
                        self._json({"path": fp, "content": fh.read()})
            except OSError as e:
                self._json({"error": str(e), "content": ""}, 500)
        elif p.path == "/api/output":
            qs = parse_qs(p.query)
            sid, cid = qs.get("id", [""])[0], qs.get("cmd", [""])[0]
            d = drill(sid, "output", cid)
            if d is None:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(d)
        elif p.path == "/api/shell":
            qs = parse_qs(p.query)
            sid, shid = qs.get("id", [""])[0], qs.get("shell", [""])[0]
            d = drill(sid, "shell", shid)
            if d is None:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(d)
        elif p.path == "/api/agent":
            qs = parse_qs(p.query)
            sid, aid = qs.get("id", [""])[0], qs.get("agent", [""])[0]
            d = drill(sid, "agent", aid)
            if d is None:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(d)
        elif p.path == "/api/session":
            sid = parse_qs(p.query).get("id", [""])[0]
            try:
                data = parse_any(sid)          # routes to the owning provider
            except Exception as e:
                # A malformed session must not crash the handler: an unhandled
                # exception closes the socket with no response, which a tunnel
                # (cloudflared) reports to the browser as 502 on every 2s poll.
                # Degrade to a clean JSON 500; keep the trace in the server log.
                traceback.print_exc()
                self._json({"error": str(e)}, 500)
                return
            if data:
                # narration is unbounded; ship only the newest page here (the 2s
                # poll's payload) — older entries come from /api/narration on scroll.
                full = data.get("narrative") or []
                data["narrative_total"] = len(full)
                data["narrative"] = full[:NARR_PAGE]
            self._json(data if data else {"error": "session not found", "id": sid},
                       200 if data else 404)
        elif p.path == "/api/narration":
            # paginated tail of a session's narration (newest-first). Lets the
            # client load older entries on demand without capping history.
            qs = parse_qs(p.query)
            sid = qs.get("id", [""])[0]
            try:
                off = max(0, int(qs.get("offset", ["0"])[0]))
                lim = min(200, max(1, int(qs.get("limit", [str(NARR_PAGE)])[0])))
            except ValueError:
                off, lim = 0, NARR_PAGE
            try:
                data = parse_any(sid)
            except Exception as e:
                traceback.print_exc()
                self._json({"error": str(e)}, 500)
                return
            if not data:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            full = data.get("narrative") or []
            self._json({"items": full[off:off + lim], "total": len(full), "offset": off})
        elif p.path == "/api/session_search":
            # search WITHIN one opened session (narration/prompts/files/commands/todos).
            qs = parse_qs(p.query)
            try:
                self._json(search_session(qs.get("id", [""])[0], qs.get("q", [""])[0]))
            except Exception as e:
                traceback.print_exc()
                self._json({"error": str(e)}, 500)
        elif p.path in EXTRA_GET:
            EXTRA_GET[p.path](self, p)
        else:
            self.send_error(404)

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/login":          # the only route reachable while unauthenticated
            return self._do_login()
        if not self._authok():
            return self._json({"error": "auth required"}, 401)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or "{}")
        except (ValueError, TypeError):
            self._json({"error": "bad body"}, 400)
            return
        if p.path == "/api/title":
            sid, t = body.get("session", ""), (body.get("title") or "").strip()
            titles = load_titles()
            if t:
                titles[sid] = t[:120]
            else:
                titles.pop(sid, None)  # empty = clear override, fall back to auto
            _save_json(config.TITLES_FILE, titles)
            self._json({"ok": True})
            return
        if p.path == "/api/config":
            # Writes a runtime setting into config.json (see config.py's big module comment
            # for the precedence/liveness contract). ALLOWLIST-ONLY: `key` must be a member of
            # config.EDITABLE (TRACKER_AUTH is deliberately never in it -- writing a password
            # typed into a web form into a plaintext file on a server that may be tunneled is a
            # real security regression, not a convenience; that row stays "set"/"not set" only,
            # same as before this feature). Every accepted key is additionally type/range
            # checked by config.VALIDATORS before anything touches disk -- a bad value is
            # rejected with 400 and never reaches config.json.
            key = body.get("key")
            if not isinstance(key, str) or key not in config.EDITABLE:
                self._json({"error": "unknown config key", "key": key}, 400)
                return
            if "value" not in body:
                self._json({"error": "value required"}, 400)
                return
            validator = config.VALIDATORS[key]
            ok, coerced = validator(body.get("value"))
            if not ok:
                self._json({"error": "invalid value for %s" % key}, 400)
                return
            # config.py holds no filesystem access of its own (see its module comment) --
            # read-modify-write config.json right here, the SAME shape as every other
            # app-owned write in this handler (load, mutate, _save_json), then apply the
            # new value immediately so it's live in this process before the response goes
            # out (config.apply_overrides repoints the plain LIVE_WINDOW/TERM_RENDERER/
            # MAX_TERMS/TERMINAL globals and refreshes the TERM_APP/TERM_ALLOW os.environ
            # mirror -- see that function's docstring).
            overrides = _load_json(config.CONFIG_FILE, {})
            overrides[key] = coerced
            _save_json(config.CONFIG_FILE, overrides)
            config.apply_overrides(overrides)
            self._json({"ok": True, "key": key, "value": config.get(key, overrides),
                        "restart": key in config.RESTART_REQUIRED})
            return
        if p.path == "/api/tunnel":
            # Writes one Tunnel-section field into config.json. ALLOWLIST-ONLY, same shape
            # as POST /api/config above but a SEPARATE allowlist (config.TUNNEL_EDITABLE,
            # never config.EDITABLE) -- TUNNEL_USER/TUNNEL_PASS can hold a live credential,
            # so they get their own gate rather than folding into the general config route.
            key = body.get("key")
            if not isinstance(key, str) or key not in config.TUNNEL_EDITABLE:
                self._json({"error": "unknown tunnel key", "key": key}, 400)
                return
            if "value" not in body:
                self._json({"error": "value required"}, 400)
                return
            validator = config.TUNNEL_VALIDATORS[key]
            ok, coerced = validator(body.get("value"))
            if not ok:
                self._json({"error": "invalid value for %s" % key}, 400)
                return
            overrides = _load_json(config.CONFIG_FILE, {})
            overrides[key] = coerced
            _save_json(config.CONFIG_FILE, overrides)
            # config.json can now hold a credential (TUNNEL_USER/TUNNEL_PASS) -- lock it to
            # owner-only read/write the moment that becomes true. Applied unconditionally on
            # every write through this route, not just USER/PASS ones, so a URL-only edit
            # re-asserts the same tight mode instead of silently leaving it at whatever a
            # PREVIOUS credential write set (a mode can only be tightened here, never loosened
            # by this route). Best-effort: a chmod failure must not lose the write itself.
            try:
                os.chmod(config.CONFIG_FILE, 0o600)
            except OSError:
                pass
            # Never echo the credential back in the response -- only TUNNEL_URL (not
            # sensitive) is safe to confirm this way; USER/PASS get "ok": true and nothing
            # else (the client already knows what it just sent).
            resp = {"ok": True, "key": key, "restart": key in ("TUNNEL_USER", "TUNNEL_PASS")}
            if key == "TUNNEL_URL":
                resp["value"] = coerced
            self._json(resp)
            return
        if p.path == "/api/pin":
            sid = body.get("session", "")
            pins = load_pins()
            if body.get("pinned") and sid and sid not in pins:
                pins.append(sid)
            elif not body.get("pinned") and sid in pins:
                pins.remove(sid)
            _save_json(config.PINS_FILE, pins)
            self._json({"ok": True})
            return
        flags = load_flags()
        if p.path == "/api/flags":
            note = (body.get("note") or "").strip()
            if not note:
                self._json({"error": "empty note"}, 400)
                return
            flag = {
                "id": int(time.time() * 1000),
                "session": body.get("session", ""),
                "project": body.get("project", ""),
                "note": note[:1000],
                "context": (body.get("context") or "")[:500],
                "ts": time.time(),
                "resolved": False,
            }
            flags.append(flag)
            save_flags(flags)
            self._json(flag, 201)
        elif p.path == "/api/flags/resolve":
            for f in flags:
                if f["id"] == body.get("id"):
                    f["resolved"] = not f.get("resolved", False)
            save_flags(flags)
            self._json({"ok": True})
        elif p.path == "/api/flags/delete":
            save_flags([f for f in flags if f["id"] != body.get("id")])
            self._json({"ok": True})
        elif p.path == "/api/notes":
            sid = body.get("session", "")
            text = (body.get("text") or "").strip()
            if not sid or not text:
                self._json({"error": "session and text required"}, 400)
                return
            notes = load_notes()
            notes.setdefault(sid, []).append({"text": text[:2000], "pushed": False})
            save_notes(notes)
            self._json({"ok": True, "notes": notes[sid]})
        elif p.path == "/api/notes/push":
            # Queue a note for delivery into the live session. Delivery itself is the tool's
            # job: a turn-end hook drains /api/notes/next. Queuing is provider-agnostic.
            sid, idx = body.get("session", ""), body.get("index")
            notes = load_notes()
            stack = notes.get(sid, [])
            if not (isinstance(idx, int) and 0 <= idx < len(stack)):
                self._json({"error": "session and index required"}, 400)
                return
            stack[idx]["pushed"] = not stack[idx].get("pushed")   # click again to un-queue
            save_notes(notes)
            self._json({"ok": True, "notes": stack})
        elif p.path == "/api/notes/next":
            # The drain: hand the oldest queued note to the session that asks for it, once.
            # Delivered notes leave the stack — from here on they live in the session's own log.
            sid = body.get("session", "")
            notes = load_notes()
            stack = notes.get(sid, [])
            hit = next((i for i, n in enumerate(stack) if n.get("pushed")), None)
            if hit is None:
                self._json({"note": None})
                return
            note = stack.pop(hit)
            if stack:
                notes[sid] = stack
            else:
                notes.pop(sid, None)
            save_notes(notes)
            self._json({"note": note["text"]})
        elif p.path == "/api/notes/delete":
            sid = body.get("session", "")
            idx = body.get("index")
            if not sid or idx is None:
                self._json({"error": "session and index required"}, 400)
                return
            notes = load_notes()
            stack = notes.get(sid, [])
            if isinstance(idx, int) and 0 <= idx < len(stack):
                stack.pop(idx)
                if stack:
                    notes[sid] = stack
                else:
                    notes.pop(sid, None)
                save_notes(notes)
            self._json({"ok": True, "notes": notes.get(sid, [])})
        elif p.path in EXTRA_POST:
            EXTRA_POST[p.path](self, p, body)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True  # don't let in-flight polls block Ctrl-C

    def handle_error(self, request, client_address):
        # a client hanging up mid-response is expected with 2s polling — stay quiet
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def bind(host="127.0.0.1", port=8790, tries=20):
    """Bind to `port`, or the next free port after it (up to `tries`).
    Returns the listening Server — read its real port off server_address."""
    for p in range(port, port + tries):
        try:
            return Server((host, p), Handler)
        except OSError as e:
            if e.errno == errno.EADDRINUSE and p < port + tries - 1:
                continue
            raise


_LOCAL_TTL = 30 * 86400   # ponytail: long-lived because it's rewritten at every startup and a
                          # tracker can run for weeks; the ceiling is that a leaked token file is
                          # good for a month — narrow it if this ever leaves the local disk.


def publish_endpoint(actual):
    """Tell local, non-browser callers (the notes drain hook) how to reach us: the port we
    actually got — bind() walks past a busy 8790 — and, when a login is configured, a signed
    token they can present. A hook is spawned by the AI tool, so it inherits neither the URL
    nor TRACKER_AUTH; without both it silently 401s and delivers nothing.

    Loopback is deliberately NOT treated as trusted instead: a tunnel terminates locally, so
    remote requests also arrive from 127.0.0.1.

    Best-effort throughout — a read-only install must still serve."""
    try:
        with open(config.PORT_FILE, "w") as fh:
            fh.write(str(actual))
    except OSError:
        pass
    try:
        if config.AUTH:
            fd = os.open(config.TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(_make_token(_LOCAL_TTL))
        elif os.path.exists(config.TOKEN_FILE):
            os.remove(config.TOKEN_FILE)      # login turned off — don't leave a live credential
    except OSError:
        pass


def run(host="127.0.0.1", port=8790, open_browser=True):
    config.BIND_HOST = host    # term_gate reads this to know whether we're loopback-only
    # Fold in any config.json overrides left over from a previous run (LIVE_WINDOW/
    # TERM_RENDERER/MAX_TERMS/TERMINAL are plain module globals seeded from env/default at
    # config.py's own import time -- see its module comment -- so a pre-existing config.json
    # override needs this explicit apply at real startup to take effect immediately rather
    # than waiting for someone to open the Config dialog first).
    config.apply_overrides(_load_json(config.CONFIG_FILE, {}))
    srv = bind(host, port)
    actual = srv.server_address[1]
    publish_endpoint(actual)
    url = f"http://localhost:{actual}"
    if actual != port:
        print(f"Starting AI session tracker on http://localhost:{actual} ({port}-{actual-1} were busy)")
    else:
        print(f"Starting AI session tracker on http://localhost:{actual}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    srv.serve_forever()


# ponytail: optional feature modules register their own routes into EXTRA_GET/EXTRA_POST on
# import. Listed by name (not globbed) so a stray file can't mount a route. A module that isn't
# present yet is skipped -- that's what lets the three terminal tiers be built in parallel.
# Ceiling: only a genuinely-absent module is swallowed; a real ImportError inside one still raises.
for _m in ("term_launch", "term_run", "term_vt"):
    try:
        __import__("%s.%s" % (__package__, _m))
    except ModuleNotFoundError as e:
        if e.name != "%s.%s" % (__package__, _m):
            raise
