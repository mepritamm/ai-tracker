"""Which gateway a Claude Code session runs through: plain `claude` (Anthropic) or the configured
OpenRouter launcher (a wrapper that exports OpenRouter env vars and execs `claude`), and how the
CLI's opus/sonnet/haiku slots map there. Both OpenRouter settings are empty until the user sets them."""
import os, shlex, shutil

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
