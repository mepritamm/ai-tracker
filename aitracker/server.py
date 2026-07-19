import json, os, sys, errno, webbrowser, base64, hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import config                       # referenced live (config.AUTH) so tests/env see one source
from .config import LIVE_WINDOW, NARR_PAGE
from .page import build_page
from .registry import all_sessions, parse_any, search_all
from .store import load_flags, save_flags, load_titles, load_pins, _load_json, _save_json
from .config import TITLES_FILE, FLAGS_FILE, PINS_FILE
from .providers.claude import find_session, file_diffs, command_output, shell_output, agent_detail


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

    def _authed(self):
        """True if the request may proceed. When config.AUTH is set, require matching
        HTTP Basic credentials; otherwise send 401 and return False. Off by default."""
        cred = config.AUTH
        if not cred:
            return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Basic "):
            try:
                dec = base64.b64decode(got[6:]).decode("utf-8", "replace")
            except Exception:
                dec = ""
            if hmac.compare_digest(dec, cred):   # constant-time — don't leak length/prefix via ==
                return True
        body = b"authentication required"
        try:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="ai-tracker"')
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        return False

    def do_GET(self):
        if not self._authed():
            return
        p = urlparse(self.path)
        if p.path == "/":
            body = build_page().encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
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
        if not self._authed():
            return
        p = urlparse(self.path)
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
