"""Which gateway a Claude Code session runs through: plain `claude` (Anthropic) or the configured
OpenRouter launcher (a wrapper that exports OpenRouter env vars and execs `claude`), and how the
CLI's opus/sonnet/haiku slots map there. Both OpenRouter settings are empty until the user sets them."""
import json, os, re, shlex, shutil, signal, subprocess, threading, time

from . import config
from .util import real_model

ANTHROPIC, OPENROUTER = "anthropic", "openrouter"
LADDERS = {ANTHROPIC: ["haiku", "sonnet", "opus", "fable"], OPENROUTER: ["haiku", "sonnet", "opus"]}


class GatewayError(Exception):
    """The OpenRouter gateway is needed but its launcher isn't usable; str(e) is the user-facing reason."""


def gateway_of(model_id):
    """OPENROUTER for a `vendor/model` id, ANTHROPIC for any other real id, "" if none."""
    rm = real_model(model_id)
    return (OPENROUTER if "/" in rm else ANTHROPIC) if rm else ""


def or_launcher():
    """(argv0, "") for the configured OpenRouter launcher -- one executable, a command on PATH or a path --
    or ("", reason) when it is unset or not runnable."""
    raw = (config.OPENROUTER_LAUNCHER or "").strip()
    if not raw:
        return "", "OpenRouter launcher not configured — set it in Config → Terminal"
    p = os.path.expanduser(raw)
    p = p if os.sep in p else (shutil.which(p) or "")
    if p and os.path.isfile(p) and os.access(p, os.X_OK):
        return os.path.abspath(p), ""
    return "", "OpenRouter launcher %r not found or not executable — fix it in Config → Terminal" % raw


def openrouter_configured():
    return not or_launcher()[1]


def launcher(gw):
    """argv[0] for a session on `gw`. Raises GatewayError for OpenRouter when no usable launcher is
    configured -- never plain `claude`, which would silently run the session on Anthropic instead."""
    if gw != OPENROUTER:
        return "claude"
    p, err = or_launcher()
    if err:
        raise GatewayError(err)
    return p


def slots():
    """{"opus","sonnet","haiku"} -> OpenRouter model id from the configured slot file; {} when it is
    unset. A set env var beats the file; MID defaults to HIGH, LOW to MID. Never raises."""
    path = os.path.expanduser(config.OPENROUTER_SLOTS_FILE or "")
    if not path:
        return {}
    cfg = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    for tok in shlex.split(line, comments=True):
                        k, eq, v = tok.partition("=")
                        if eq:
                            cfg[k] = v
                except ValueError:
                    pass
    except OSError:
        pass          # unreadable or missing file == an empty file
    # a SET env var (even empty) beats the file; all whitespace is stripped
    g = lambda k: "".join((os.environ[k] if k in os.environ else cfg.get(k, "")).split())
    high = g("OR_MODEL_HIGH")
    mid = g("OR_MODEL_MID") or high
    low = g("OR_MODEL_LOW") or mid
    return {s: m for s, m in (("opus", high), ("sonnet", mid), ("haiku", low)) if m}


def model_meta(model_id):
    """gateway / model_ladder / model_hints / model_slot for a session's latest model; the OpenRouter
    branch also carries the server-owned `openrouter_configured` flag (the Anthropic branch is unchanged)."""
    gw = gateway_of(model_id)
    if gw != OPENROUTER:
        return {"gateway": gw, "model_ladder": LADDERS[ANTHROPIC], "model_hints": {}, "model_slot": None}
    hints = slots()
    base = model_id.split(":", 1)[0]
    hit = [s for s in ("opus", "sonnet", "haiku") if s in hints and hints[s].split(":", 1)[0] == base]
    slot = hit[0] if len(hit) == 1 else None      # several slots share the model -> ambiguous, don't claim
    return {"gateway": gw, "model_ladder": LADDERS[OPENROUTER], "model_hints": hints, "model_slot": slot,
            "openrouter_configured": openrouter_configured()}


# inferred (unproven): a slow CLI (keychain contention measured at 20-26 s under 16 concurrent runs) overran the old 15 s
AUTH_TTL, AUTH_FRESH_FLOOR, AUTH_STATUS_TIMEOUT, AUTH_LOCK_EXTRA = 60, 5, 40, 10     # seconds
_AUTH_CACHE = {"at": 0.0, "val": None, "ttl": AUTH_TTL}
_AUTH_LOCK = threading.Lock()
_AUTH_LABELS = {"claude.ai": "Claude subscription", "oauth_token": "CLAUDE_CODE_OAUTH_TOKEN",
                "api_key": "API key", "api_key_helper": "apiKeyHelper script",
                "third_party": "cloud provider", "none": "not logged in"}


def _auth_result(available=True, logged_in=False, method="", sub="", label="", error=""):
    return {"available": available, "logged_in": logged_in, "auth_method": method, "subscription": sub,
            "label": label, "error": error}


def _auth_run(exe):
    """Run `claude auth status --json` -> parsed dict or None. Own session (no tty); on timeout the whole
    process group is killed. -> dict | None (bad output) | "timeout" | False (spawn failed); never an exception."""
    kw = {} if os.name == "nt" else {"start_new_session": True}
    try:
        p = subprocess.Popen([exe, "auth", "status", "--json"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=os.path.expanduser("~"), **kw)
    except OSError:
        return False
    try:
        out, _err = p.communicate(timeout=AUTH_STATUS_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            try:
                p.kill()
            except OSError:
                pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return "timeout"
    except Exception:
        return None
    try:
        d = json.loads(out)
    except (TypeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def claude_auth_status(fresh=False):
    """-> {"available","logged_in","auth_method","subscription","label","error"}, built FRESH from three
    keys of `claude auth status --json` (loggedIn/authMethod/subscriptionType) -- never spreads the CLI's
    dict, so email/org/ids and any key it adds later can't leak. Cached AUTH_TTL s; `fresh` re-runs only
    when the cache is >= AUTH_FRESH_FLOOR s old. One run at a time; a stuck run can't block a later
    caller past the lock timeout. Logs nothing."""
    if not _AUTH_LOCK.acquire(timeout=AUTH_STATUS_TIMEOUT + AUTH_LOCK_EXTRA):
        return _auth_result(error="claude auth status is busy — try again")
    try:
        age = time.monotonic() - _AUTH_CACHE["at"]
        if _AUTH_CACHE["val"] is not None and (age < AUTH_FRESH_FLOOR or (not fresh and age < _AUTH_CACHE["ttl"])):
            return _AUTH_CACHE["val"]
        exe, failed = shutil.which("claude"), False
        if not exe:
            res = _auth_result(available=False, error="claude not found on the server's PATH")
        elif exe == or_launcher()[0]:
            res = _auth_result(available=False, error="claude on PATH is the OpenRouter launcher")
        else:
            d = _auth_run(exe)
            failed = not isinstance(d, dict)
            if d is False:
                res = _auth_result(available=False, error="claude couldn't be started")
            elif d == "timeout":
                res = _auth_result(error="claude auth status timed out after %d s" % AUTH_STATUS_TIMEOUT)
            elif d is None:
                res = _auth_result(error="couldn't read claude auth status")
            else:
                m, st = d.get("authMethod"), d.get("subscriptionType")
                m = m if isinstance(m, str) and re.fullmatch(r"[A-Za-z0-9_.]{1,24}", m) else ""
                st = st if isinstance(st, str) and re.fullmatch(r"[a-z0-9_]{1,24}", st) else ""
                if d.get("loggedIn") is True:
                    if m == "claude.ai":
                        label = "Logged in · Claude " + (st.replace("_", " ").title() + " " if st else "") + "subscription"
                    else:
                        label = "Logged in · " + _AUTH_LABELS.get(m, "another credential")
                    res = _auth_result(logged_in=True, method=m if m in _AUTH_LABELS else "", sub=st, label=label)
                else:
                    res = _auth_result(method=m if m in _AUTH_LABELS else "", label="Not logged in")
        prev = _AUTH_CACHE["val"]
        if failed and prev is not None and prev.get("logged_in"):
            res = prev           # a slow/unreadable read must not flip a known-good login to an error
        # a transient failure (timeout / unreadable) is only held AUTH_FRESH_FLOOR s, not the full AUTH_TTL
        _AUTH_CACHE.update(at=time.monotonic(), val=res, ttl=AUTH_FRESH_FLOOR if failed else AUTH_TTL)
        return res
    finally:
        _AUTH_LOCK.release()
