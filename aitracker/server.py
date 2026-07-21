import json, os, sys, errno, webbrowser, base64, hmac, hashlib, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import config                       # referenced live (config.AUTH) so tests/env see one source
from .config import LIVE_WINDOW, NARR_PAGE
from .page import build_page
from .registry import all_sessions, parse_any, search_all
from .store import load_flags, save_flags, load_titles, load_pins, load_notes, save_notes, _load_json, _save_json
from .config import TITLES_FILE, FLAGS_FILE, PINS_FILE, NOTES_FILE
from .providers.claude import find_session, file_diffs, command_output, shell_output, agent_detail

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
      "<button class=lb type=submit>🔓 Unlock dashboard</button>"
      "<div class=le id=lerr></div>"
      "<div class=lfoot>HTTP Basic via <code>TRACKER_AUTH</code> · constant-time · read-only</div>"
      "</form></div>"
      "<script>async function doLogin(e){e.preventDefault();"
      "var r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},"
      "body:JSON.stringify({user:document.getElementById('lu').value,pass:document.getElementById('lp').value})});"
      "if(r.ok){location.reload()}else{document.getElementById('lerr').textContent='Incorrect username or password'}"
      "return false}</script></body></html>")


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
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
            self._json(all_sessions())
        elif p.path == "/api/flags":
            self._json(load_flags())
        elif p.path == "/api/search":
            self._json(search_all(parse_qs(p.query).get("q", [""])[0]))
        elif p.path == "/api/diff":
            qs = parse_qs(p.query)
            sid, fp = qs.get("id", [""])[0], qs.get("file", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json({"file": fp, "ops": file_diffs(path, fp)})
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
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(command_output(path, cid))
        elif p.path == "/api/shell":
            qs = parse_qs(p.query)
            sid, shid = qs.get("id", [""])[0], qs.get("shell", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(shell_output(path, shid))
        elif p.path == "/api/agent":
            qs = parse_qs(p.query)
            sid, aid = qs.get("id", [""])[0], qs.get("agent", [""])[0]
            path = find_session(sid)
            if not path:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            self._json(agent_detail(path, aid))
        elif p.path == "/api/session":
            sid = parse_qs(p.query).get("id", [""])[0]
            try:
                data = parse_any(sid)          # routes to the owning provider
            except OSError as e:
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
            except OSError as e:
                self._json({"error": str(e)}, 500)
                return
            if not data:
                self._json({"error": "session not found", "id": sid}, 404)
                return
            full = data.get("narrative") or []
            self._json({"items": full[off:off + lim], "total": len(full), "offset": off})
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
            _save_json(TITLES_FILE, titles)
            self._json({"ok": True})
            return
        if p.path == "/api/pin":
            sid = body.get("session", "")
            pins = load_pins()
            if body.get("pinned") and sid and sid not in pins:
                pins.append(sid)
            elif not body.get("pinned") and sid in pins:
                pins.remove(sid)
            _save_json(PINS_FILE, pins)
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
            notes.setdefault(sid, []).append(text[:2000])
            save_notes(notes)
            self._json({"ok": True, "notes": notes[sid]})
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


def bind(host="127.0.0.1", port=8787, tries=20):
    """Bind to `port`, or the next free port after it (up to `tries`).
    Returns the listening Server — read its real port off server_address."""
    for p in range(port, port + tries):
        try:
            return Server((host, p), Handler)
        except OSError as e:
            if e.errno == errno.EADDRINUSE and p < port + tries - 1:
                continue
            raise


def run(host="127.0.0.1", port=8787, open_browser=True):
    srv = bind(host, port)
    actual = srv.server_address[1]
    if actual != port:
        print(f"port {port} is in use → using {actual}")
    url = f"http://localhost:{actual}"
    print(f"AI session tracker → {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    srv.serve_forever()
