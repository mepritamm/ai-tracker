#!/usr/bin/env python3
"""Claude Code hook — deliver one ai-tracker note into a session.

Wire all three up in ~/.claude/settings.json, pointing at this same file:

    "Stop":             [{"hooks": [{"type": "command", "timeout": 5, "command": "python3 …/drain-notes.py"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "timeout": 5, "command": "python3 …/drain-notes.py"}]}],
    "SessionStart":     [{"matcher": "startup|resume",
                          "hooks": [{"type": "command", "timeout": 5, "command": "python3 …/drain-notes.py"}]}]

Why three. `Stop` fires at the end of a turn, which delivers within seconds — but only to a
session that HAS a turn in flight. A session parked at the prompt never ends another turn, so
on `Stop` alone a note pushed at an idle session waits forever. `UserPromptSubmit` and
`SessionStart` are the wake paths: the note rides along the next time you talk to that session
or resume it. Stop alone still works, it just can't reach an idle session — which is the
common case, since you push a note precisely when you're not sitting in that terminal.

Each event takes a different output shape (Stop steers the turn; the other two inject context),
so this script picks the shape from `hook_event_name`.

Anything unexpected — no tracker, no notes, bad stdin, an unknown event — exits 0 silently.
A queued note must never be able to break the session it was meant to help.

Finding the tracker: PORT env if set, else the port the server wrote at startup
(`aitracker/port` — it falls back past 8787 when something else already holds it), else 8787.

Env: PORT (override), TRACKER_AUTH ("user:pass", only if the tracker requires it).
"""
import base64
import json
import os
import sys
import urllib.request

try:
    hook = json.load(sys.stdin)
except Exception:
    hook = None
if not isinstance(hook, dict):       # anything unexpected on stdin -> carry on normally
    sys.exit(0)

if hook.get("stop_hook_active"):     # Stop only: already inside an injected turn — don't chain
    sys.exit(0)

event = hook.get("hook_event_name") or "Stop"
sid = hook.get("session_id")
if not sid or event not in ("Stop", "UserPromptSubmit", "SessionStart"):
    sys.exit(0)

def _port():
    """PORT env wins; otherwise the port the server actually bound (it falls back past 8787
    when something else holds it — assuming 8787 silently queries the wrong app forever)."""
    if os.environ.get("PORT"):
        return os.environ["PORT"]
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "aitracker", "port")) as fh:
            return str(int(fh.read().strip()))
    except (OSError, ValueError):
        return "8787"


url = "http://127.0.0.1:%s/api/notes/next" % _port()
req = urllib.request.Request(url, data=json.dumps({"session": sid}).encode(),
                             headers={"Content-Type": "application/json"})
cred = os.environ.get("TRACKER_AUTH", "")
if cred:
    req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())

try:
    # ponytail: short timeout — a wedged tracker must never stall a turn or a session start.
    note = json.load(urllib.request.urlopen(req, timeout=2)).get("note")
except Exception:
    sys.exit(0)

if not note:
    sys.exit(0)

if event == "Stop":
    # `decision: block` hands the note back as the next instruction, so it's acted on now.
    print(json.dumps({"decision": "block", "reason": note}))
else:
    # UserPromptSubmit / SessionStart are context-only. Label it so the note reads as a queued
    # instruction from the dashboard rather than as something the user just typed.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": event,
        "additionalContext": "Queued note from the ai-tracker dashboard: " + note,
    }}))
