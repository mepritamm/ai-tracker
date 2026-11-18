"""Account-level usage for Config -> Usage: Claude plan limits (`claude -p /usage`), Auggie auth status and
local month cost, and OpenRouter key usage (`GET /api/v1/key`). Every external run lives in a background
thread behind the `_Bg` cache, so no request handler ever blocks on one. The exceptions this module relies on
are written out in .claude/rules/conventions.md rule 6 (Claude plan usage, OpenRouter key usage, Auggie login).

Bundle note: scripts/bundle.py flattens every module into one namespace, so top-level names here are
unique (`_acct_*`, `usage_*`) and server.py imports them by name (never `accounts.X`)."""
import datetime, json, os, re, ssl, threading, time, urllib.error, urllib.request
from . import config
from .update import _run
from .gateway import claude_auth_cached, or_launcher, openrouter_configured
from .agent_cli import _agent_spec
from .providers.auggie import month_cost
from .store import _load_json

_ACCT_OR_URL = "https://openrouter.ai/api/v1/key"
_ACCT_OR_MAX = 65536
_ACCT_CLAUDE_ARGV = ["-p", "/usage", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                     "--settings", '{"disableAllHooks":true}', "--strict-mcp-config"]
_ACCT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ACCT_STATE = {"or_n": 0}


def _acct_now():
    return time.monotonic()


class _Bg:
    """Background single-flight cache. get() never blocks: it returns the last body (or a loading placeholder)
    with refreshing/stale/at, and starts at most one thread. Every finished run (ok or not) stamps _t; a failure
    with no earlier good body stores the error body. A run's result is dropped if invalidate() ran meanwhile.
    producer() -> (body: dict, ok: bool, hold: float seconds before a retry after a failure)."""

    def __init__(self, ttl, floor, producer, placeholder):
        self.ttl, self.floor, self.producer, self.placeholder = ttl, floor, producer, placeholder
        self._lock = threading.Lock()
        self._gen = 0
        self._th = None
        self._reset()

    def _reset(self):
        self.body, self.good, self.ran, self.ok_last = None, False, False, True
        self.hold, self.t, self.running = 0.0, 0.0, False

    def invalidate(self):
        with self._lock:
            self._gen += 1
            self._reset()
            self.running = self._th is not None and self._th.is_alive()

    def get(self, fresh=False):
        with self._lock:
            age = _acct_now() - self.t
            if self.running:
                due = False
            elif not self.ran:
                due = True
            elif self.ok_last:
                due = age >= self.ttl or (fresh and age >= self.floor)
            else:
                due = age >= self.hold      # `fresh` never overrides a failure hold
            if due:
                self.running = True
                self._th = threading.Thread(target=self._work, args=(self._gen,), daemon=True)
                self._th.start()
            out = dict(self.body if self.body is not None else self.placeholder)
            out["refreshing"] = self.running
            out.setdefault("stale", False)
            out.setdefault("at", 0)
            return out

    def _work(self, gen):
        try:
            body, ok, hold = self.producer()
        except Exception:
            body, ok, hold = {"state": "error", "error": "internal error"}, False, 60.0
        with self._lock:
            self.running = False
            if gen != self._gen:
                return                      # invalidated mid-run: drop the result
            self.t, self.ran, self.ok_last, self.hold = _acct_now(), True, ok, hold
            at = int(time.time())
            if ok:
                self.body, self.good = dict(body, at=at, stale=False), True
            elif self.good and self.body is not None:
                self.body = dict(self.body, stale=True, error=body.get("error", ""))
            else:
                self.body = dict(body, at=at, stale=False)


# --------------------------------------------------------------------------------------------- Claude /usage
_ACCT_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T[0-9:.]{5,16}(Z|[+-]\d{2}:?\d{2})?")
_ACCT_SEVERITIES = ("normal", "warning", "critical")


def _acct_name(v):
    if not isinstance(v, str):
        return ""
    return "".join(c for c in v if c.isprintable()).strip()[:40]


def _acct_num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def _acct_parse_usage_report(ur, sub):
    """-> (limits, credits). Built from named fields only: nothing else of `usage_report` is forwarded.
    credits comes from rate_limits.extra_usage (see _acct_credits)."""
    limits = []
    rl = ur.get("rate_limits")
    for row in ((rl.get("limits") if isinstance(rl, dict) else None) or []):
        if not isinstance(row, dict):
            continue
        kind = row.get("kind") if isinstance(row.get("kind"), str) and re.fullmatch(r"[A-Za-z0-9_]{1,40}", row.get("kind")) else "limit"
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        name = ""
        for k in ("model", "surface"):
            part = scope.get(k)
            if isinstance(part, dict) and _acct_name(part.get("display_name")):
                name = _acct_name(part.get("display_name"))
                break
        if kind == "session":
            label = "Current session"
        elif kind == "weekly_all":
            label = "Current week (all models)"
        elif kind == "weekly_scoped":
            label = "Current week (%s)" % name if name else "Current week"
        else:
            label = kind.replace("_", " ").capitalize() + (" (%s)" % name if name else "")
        pct = _acct_num(row.get("percent"))
        pct = round(pct) if pct is not None and 0 <= pct <= 100 else None
        ra = row.get("resets_at")
        ra = ra if isinstance(ra, str) and _acct_iso(ra) else None
        sev = row.get("severity") if row.get("severity") in _ACCT_SEVERITIES else "normal"
        limits.append({"kind": kind, "label": label, "percent": pct, "resets_at": ra, "severity": sev,
                       "active": row.get("is_active") is True})
    return limits, _acct_credits(rl.get("extra_usage") if isinstance(rl, dict) else None, sub)


def _acct_money(minor, cur):
    """Minor units (cents for USD) -> text. USD is "$12.34"; any other currency "12.34 EUR"."""
    return "$%.2f" % (minor / 100) if cur == "USD" else "%.2f %s" % (minor / 100, cur)


def _acct_credits(eu, sub):
    """The usage-credits block, only when extra_usage.is_enabled is exactly True (probed shape:
    usage_report.rate_limits.extra_usage = {is_enabled, monthly_limit, used_credits, utilization, currency}).
    A null monthly_limit (team/enterprise) is never rendered as "Unlimited"."""
    if not isinstance(eu, dict) or eu.get("is_enabled") is not True:
        return None
    used = _acct_num(eu.get("used_credits"))
    if used is None or used < 0:
        return None
    cur = eu.get("currency") if isinstance(eu.get("currency"), str) and re.fullmatch(r"[A-Z]{3}", eu.get("currency")) else "USD"
    lim = _acct_num(eu.get("monthly_limit"))
    util = _acct_num(eu.get("utilization"))
    util = round(util, 1) if util is not None and 0 <= util <= 100 else None
    text = ("%s spent of %s this month" % (_acct_money(used, cur), _acct_money(lim, cur)) if lim is not None and lim >= 0
            else "%s spent this month · no monthly limit of its own" % _acct_money(used, cur))
    return {"used_minor": used, "limit_minor": lim, "utilization": util, "currency": cur, "text": text,
            "note": "your organisation's limits apply" if sub in ("team", "enterprise") else ""}


def _acct_iso(s):
    return len(s) <= 40 and bool(_ACCT_ISO_RE.fullmatch(s))


def _acct_claude_body(state, error="", message="", limits=None, credits=None):
    return {"state": state, "error": error, "message": message, "limits": limits or [], "credits": credits}


def _acct_claude_producer():
    spec = _agent_spec("claude")
    exe = spec.get("path") if spec else None
    if not exe:
        return _acct_claude_body("unavailable", "claude not found on the server's PATH (Config → Agents shows the same); "
                                 "reinstall the service from a shell where it is on PATH"), False, 60.0
    if exe == or_launcher()[0]:
        return _acct_claude_body("unavailable", "claude on PATH is the OpenRouter launcher"), False, 60.0
    rc, out, err = _run([exe] + _ACCT_CLAUDE_ARGV, 150, cwd=os.path.expanduser("~"))
    if rc is None:
        return _acct_claude_body("error", "claude /usage timed out after 150 s" if err == b"timeout"
                                 else "claude couldn't be started"), False, 60.0
    report, is_err = None, False
    for line in (out or b"").decode("utf-8", "replace").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        if o.get("type") == "result" and o.get("is_error") is True:
            is_err = True
        if report is None and o.get("type") == "assistant" and "usage_report" in o:
            report = o.get("usage_report")
    if rc != 0 or is_err:
        return _acct_claude_body("error", "claude /usage failed"), False, 60.0
    if report is None:
        return _acct_claude_body("no_report", message="Claude Code returned no plan usage for this login (API key, "
                                 "OpenRouter, setup-token or usage-based billing logins don't report it)."), True, 0.0
    if not isinstance(report, dict):
        return _acct_claude_body("error", "unrecognised usage report"), False, 60.0
    sub = (claude_auth_cached() or {}).get("subscription", "")
    limits, credits = _acct_parse_usage_report(report, sub)
    msg = "" if limits or credits else "No plan limits reported for this login."
    return _acct_claude_body("ok", limits=limits, credits=credits, message=msg), True, 0.0


_CLAUDE = _Bg(300, 60, _acct_claude_producer, dict(_acct_claude_body("loading"), account=""))


def claude_usage(fresh=False):
    out = _CLAUDE.get(fresh)
    out["account"] = (claude_auth_cached() or {}).get("label", "")   # never runs `claude auth status`
    return out


# ------------------------------------------------------------------------------------------------ OpenRouter
class _AcctNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None                         # a 3xx raises HTTPError: the Authorization header never follows


def _acct_open():
    return urllib.request.build_opener(_AcctNoRedirect)


def _acct_or_key():
    """The saved key, re-read and re-validated from config.json at call time, or ""."""
    v = _load_json(config.CONFIG_FILE, {}).get("OPENROUTER_API_KEY")
    ok, v = config._v_or_key(v)
    return v if ok and v else ""


def _acct_usd(v):
    v = _acct_num(v)
    return "—" if v is None else "$%.2f" % v


def _acct_parse_or_key(d):
    data = d.get("data") if isinstance(d, dict) else None
    if not isinstance(data, dict):
        return None
    rows = [{"label": lab, "text": _acct_usd(data.get(k))} for k, lab in
            (("usage_daily", "Today (UTC)"), ("usage_weekly", "This week (UTC, from Monday)"),
             ("usage_monthly", "This month (UTC)"), ("usage", "All time")) if k in data]
    lim = data.get("limit", "absent")
    limit_text = "" if lim == "absent" else ("No limit on this key" if lim is None else "Limit " + _acct_usd(lim))
    rem = _acct_num(data.get("limit_remaining"))
    lr = data.get("limit_reset")
    ft = data.get("is_free_tier")
    return {"rows": rows, "limit_text": limit_text, "remaining_text": "" if rem is None else "Remaining " + _acct_usd(rem),
            "limit_reset": lr if isinstance(lr, str) and re.fullmatch(r"[a-z_]{1,16}", lr) else None,
            "free_tier": ft if isinstance(ft, bool) else None}


def _acct_or_body(state, error="", parsed=None, retry_in=0):
    p = parsed or {"rows": [], "limit_text": "", "remaining_text": "", "limit_reset": None, "free_tier": None}
    return dict(p, key_set=True, state=state, error=error, retry_in=retry_in)


def _acct_or_fail(error, state="error"):
    _ACCT_STATE["or_n"] += 1
    hold = min(30.0 * 2 ** (_ACCT_STATE["or_n"] - 1), 900.0)
    return _acct_or_body(state, error, retry_in=int(hold)), False, hold


def _acct_or_producer():
    key = _acct_or_key()
    if not key:
        return dict(_acct_or_body("not_set"), key_set=False), True, 0.0
    req = urllib.request.Request(_ACCT_OR_URL, headers={"Authorization": "Bearer " + key, "Accept": "application/json",
                                                        "User-Agent": "ai-tracker"})
    try:
        resp = _acct_open().open(req, timeout=10)
        try:
            raw = resp.read(_ACCT_OR_MAX + 1)
        finally:
            resp.close()
    except urllib.error.HTTPError as e:
        try:
            e.close()
        except Exception:
            pass
        if e.code in (401, 403):
            return _acct_or_body("rejected", "OpenRouter rejected the saved key"), False, float("inf")
        return _acct_or_fail("OpenRouter returned an error (HTTP %d)" % e.code)
    except Exception as e:
        reason = getattr(e, "reason", None)
        if isinstance(e, ssl.SSLCertVerificationError) or isinstance(reason, ssl.SSLCertVerificationError):
            return _acct_or_fail("TLS certificate check failed — this Python has no CA bundle")
        return _acct_or_fail("couldn't reach openrouter.ai")
    if len(raw) > _ACCT_OR_MAX:
        return _acct_or_fail("OpenRouter response too large")
    try:
        parsed = _acct_parse_or_key(json.loads(raw.decode("utf-8", "replace")))
    except ValueError:
        parsed = None
    if parsed is None:
        return _acct_or_fail("unrecognised OpenRouter response")
    _ACCT_STATE["or_n"] = 0
    return _acct_or_body("ok", parsed=parsed), True, 0.0


_OR = _Bg(300, 30, _acct_or_producer, dict(_acct_or_body("loading")))


def openrouter_usage(fresh=False):
    if not _acct_or_key():
        out = dict(_acct_or_body("not_set"), key_set=False, refreshing=False, stale=False, at=0)   # no network
    else:
        out = _OR.get(fresh)
    out["launcher_configured"] = openrouter_configured()
    return out


def openrouter_peek():
    """Config read only: never touches _OR and never opens a socket."""
    return {"key_set": bool(_acct_or_key()), "launcher_configured": openrouter_configured(), "file": config.CONFIG_FILE}


# -------------------------------------------------------------------------------------------------- Auggie
_AUGGIE_AUTH_KEYS = ("available", "logged_in", "label", "error", "refreshing")


def _acct_aug_body(available=True, logged_in=False, label="", error=""):
    return {"available": available, "logged_in": logged_in, "label": label, "error": error}


def _acct_auggie_producer():
    spec = _agent_spec("auggie")
    exe = spec.get("path") if spec else None
    if not exe:
        return _acct_aug_body(False, error="auggie not found on the server's PATH (Config → Agents shows the same)"), False, 5.0
    rc, out, err = _run([exe, "auth", "status"], 20, cwd=os.path.expanduser("~"))
    if rc is None:
        return _acct_aug_body(error="auggie auth status timed out after 20 s" if err == b"timeout"
                              else "auggie couldn't be started"), False, 5.0
    lines = [l.strip() for l in (out or b"").decode("utf-8", "replace").splitlines()]
    if rc == 0 and "Logged in." in lines:
        return _acct_aug_body(logged_in=True, label="Logged in · Augment (account name isn't reported by auggie)"), True, 0.0
    if rc == 1 and "Not logged in." in lines:
        return _acct_aug_body(label="Not logged in"), True, 0.0
    return _acct_aug_body(error="couldn't read auggie auth status"), False, 5.0


_AUG = _Bg(60, 5, _acct_auggie_producer, _acct_aug_body(label="Checking…"))


def auggie_auth_status(fresh=False):
    d = _AUG.get(fresh)
    return {k: d.get(k) for k in _AUGGIE_AUTH_KEYS}


def auggie_usage():
    """Calendar month to date (UTC), local session cost only: synchronous, local reads."""
    now = datetime.datetime.now(datetime.timezone.utc)
    since = datetime.datetime(now.year, now.month, 1, tzinfo=datetime.timezone.utc).timestamp()
    out = {"available": os.path.isdir(config.AUGGIE_SESSIONS), "label": "Local session cost, not account balance",
           "window": "This month (UTC, from %s 1)" % _ACCT_MONTHS[now.month - 1], "cost_text": "", "sessions": 0, "note": ""}
    if not out["available"]:
        out["note"] = "No ~/.augment/sessions folder found."
        return out
    mc = month_cost(since)
    out["cost_text"] = "$%.2f" % mc["usd"]
    out["sessions"] = mc["sessions"]
    note = "Auggie CLI sessions read from %s; sub-agent cost counts in the month the session was last active" % ", ".join(mc["sources"])
    if mc["unpriced"]:
        note += "; %d billed entr%s had no readable price" % (mc["unpriced"], "y" if mc["unpriced"] == 1 else "ies")
    out["note"] = note + ". Sessions from Auggie 1.3+ (~/.augment/sessions-v2) aren't read yet."
    return out


def usage_invalidate(name):
    """Drop a cached result (login or key change): 'claude', 'openrouter' or 'auggie_auth'."""
    if name == "openrouter":
        _ACCT_STATE["or_n"] = 0
    {"claude": _CLAUDE, "openrouter": _OR, "auggie_auth": _AUG}[name].invalidate()
