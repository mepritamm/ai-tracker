import os
import re
from .config import LIVE_WINDOW
from .util import _dur, _names, _first_line, _short_title, _window


def build_overview(d, todos, files, cmds, commits, tests, agents, requests,
                   narrative, agents_bg, idle, t_first, t_last):
    """Concrete Goal / Now / So-far that a cold reader can understand at a glance."""
    c = d["counts"]
    m = d["meta"]
    span = _dur(t_first, t_last)
    where = os.path.basename(m.get("cwd", "") or "?")
    if m.get("gitBranch"):
        where += " · ⎇ " + m["gitBranch"]
    if span:
        where += " · %s active" % span

    goal = requests[-1]["text"] if requests else ""

    # what it's doing right now: running background agents win (the "shows idle"
    # bug was here), then in-progress task, then latest narration line
    running = [a for a in agents_bg if a["running"]]
    ip = next((t for t in todos if t.get("status") == "in_progress"), None)
    if running:
        lead = running[0].get("last") or running[0].get("task") or ""
        now = "⚙ %d background agent(s) working" % len(running)
        if lead:
            now += " — " + _first_line(lead, 140)
    elif ip:
        now = "▶ " + (ip.get("activeForm") or ip["content"])
    elif narrative and idle < LIVE_WINDOW:
        now = _first_line(narrative[-1]["text"])
    elif narrative:
        now = "Idle — last said: " + _first_line(narrative[-1]["text"], 140)
    else:
        now = ""

    # one-line synthesis of concrete work
    so = []
    if files:
        so.append("touched %d file(s) (%s)" % (len(files), _names([f["path"] for f in files], 5)))
    if cmds:
        det = []
        if c["commits"]:
            det.append("%d commit" % c["commits"])
        if c["tests"]:
            det.append("%d test%s" % (c["tests"],
                       " incl %d failed" % c["tests_failed"] if c["tests_failed"] else ""))
        if c["errors"]:
            det.append("%d errored" % c["errors"])
        so.append("ran %d command(s)%s" % (len(cmds), " — " + ", ".join(det) if det else ""))
    if agents:
        so.append("dispatched %d sub-agent(s)" % len(agents))
    if c["todos"]:
        so.append("%d/%d tasks done" % (c["done"], c["todos"]))
    sofar = "; ".join(so).capitalize() if so else "Nothing recorded yet."

    return {"where": where, "goal": goal, "now": now, "sofar": sofar,
            "commits": [cm["msg"] for cm in commits[:6]]}
