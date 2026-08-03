#!/usr/bin/env python3
"""Claude Code Stop hook — deliver one ai-tracker note into the live session.

Wire it up in ~/.claude/settings.json:

    "Stop": [{"hooks": [{"type": "command", "timeout": 5,
              "command": "python3 /path/to/ai-tracker/hooks/drain-notes.py"}]}]

At the end of every turn it asks the tracker for the oldest note you pushed for this
session and, if there is one, hands it back as the next instruction. No tracker running,
no notes queued, or any error at all -> exit 0 and the turn ends normally.

Env: PORT (default 8787), TRACKER_AUTH ("user:pass", only if the tracker requires it).
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
if not isinstance(hook, dict):       # anything unexpected on stdin -> end the turn normally
    sys.exit(0)

if hook.get("stop_hook_active"):     # we're already inside an injected turn — don't chain
    sys.exit(0)

sid = hook.get("session_id")
if not sid:
    sys.exit(0)

url = "http://127.0.0.1:%s/api/notes/next" % os.environ.get("PORT", "8787")
req = urllib.request.Request(url, data=json.dumps({"session": sid}).encode(),
                             headers={"Content-Type": "application/json"})
cred = os.environ.get("TRACKER_AUTH", "")
if cred:
    req.add_header("Authorization", "Basic " + base64.b64encode(cred.encode()).decode())

try:
    # ponytail: short timeout — a wedged tracker must never stall the end of a turn.
    note = json.load(urllib.request.urlopen(req, timeout=2)).get("note")
except Exception:
    sys.exit(0)

if note:
    print(json.dumps({"decision": "block", "reason": note}))
