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
        kind = "agents"                 # which panel the "now" click should jump to
    elif ip:
        now = "▶ " + (ip.get("activeForm") or ip["content"])
        kind = "todo"
    elif narrative and idle < LIVE_WINDOW:
        now = _first_line(narrative[-1]["text"])
        kind = "narration"
    elif narrative:
        now = "Idle — last said: " + _first_line(narrative[-1]["text"], 140)
        kind = "narration"
    else:
        now = ""
        kind = ""

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

    return {"where": where, "goal": goal, "now": now, "now_kind": kind, "sofar": sofar,
            "commits": [cm["msg"] for cm in commits[:6]]}


# ---- heartbeat: where tokens and tool time went (shared shape, both providers fill it) ----
# NB: scripts/bundle.py flattens every module into one namespace -> every module-level
# name here is HB_/_hb_ prefixed, and this section takes no new imports.
HB_BUCKETS = 60            # max beats drawn
HB_TOP = 8                 # rows kept per list; the remainder rolls into `rest`
HB_TOOL_CAP_S = 600        # one tool interval longer than this is mostly a human/prompt wait
HB_WAIT_TOOLS = {"AskUserQuestion", "ExitPlanMode", "TaskOutput"}   # time here is waiting, never busy
HB_UNCAPPED = {"Agent", "Task"}                                     # a sub-agent legitimately runs long


def _hb_merge(ivs):
    """Union of overlapping (a, b) intervals, ascending."""
    out = []
    for a, b in sorted(iv for iv in ivs if iv[1] > iv[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _hb_group(turns, keyf):
    acc = {}
    for x in turns:
        r = acc.setdefault(keyf(x), {"out": 0, "fresh": 0, "cache": 0})
        r["out"] += x[2]; r["fresh"] += x[3]; r["cache"] += x[4]
    return acc


def _hb_rest(rest):
    return {"n": len(rest), "out": sum(r["out"] for r in rest), "fresh": sum(r["fresh"] for r in rest),
            "cache": sum(r["cache"] for r in rest)} if rest else None


def build_heartbeat(turns, calls, intervals=None, labels=None, note=None):
    """Heartbeat dict (see reports/heartbeat-panel.md "Shape"). Pure.
    turns     [(t, model, out, fresh, cache, who)]  who ""=main else agent id; t<=0/None = untimed
    calls     [(t, tool_name, who)]
    intervals {tool_name: [(start, end)]} | None  (None -> busy_ms / waiting_ms are null)
    labels    {agent_id: (label, model)}"""
    labels = labels or {}
    turns = [(t or 0, m or "", o or 0, f or 0, c or 0, w or "") for t, m, o, f, c, w in turns]
    calls = [(t or 0, n or "?", w or "") for t, n, w in calls]
    stamps = [x[0] for x in turns if x[0] > 0] + [x[0] for x in calls if x[0] > 0]
    t0, t1 = (min(stamps), max(stamps)) if stamps else (None, None)
    bs, beats = 1, []
    if t0 is not None:
        bs = max(1, int(-(-(t1 - t0) // HB_BUCKETS)))
        nb = min(HB_BUCKETS, int((t1 - t0) // bs) + 1)
        beats = [{"t": t0 + i * bs, "out": 0, "fresh": 0, "cache": 0, "calls": 0} for i in range(nb)]

        def _bin(t):   # untimed -> last bucket
            return beats[min(nb - 1, int((t - t0) // bs))] if t > 0 else beats[-1]
        for t, _m, o, f, c, _w in turns:
            b = _bin(t); b["out"] += o; b["fresh"] += f; b["cache"] += c
        for t, _n, _w in calls:
            _bin(t)["calls"] += 1
    total = {"out": sum(x[2] for x in turns), "fresh": sum(x[3] for x in turns),
             "cache": sum(x[4] for x in turns), "calls": len(calls)}
    n_calls = {}
    for _t, n, _w in calls:
        n_calls[n] = n_calls.get(n, 0) + 1
    busy, wait = {}, 0
    if intervals is not None:
        for n, ivs in intervals.items():
            full = sum(b - a for a, b in _hb_merge(ivs))
            if n in HB_WAIT_TOOLS:
                tot = 0; wait += full
            elif n in HB_UNCAPPED:
                tot = full
            else:   # cap each RAW interval, then union; the excess is waiting
                tot = sum(b - a for a, b in _hb_merge([(a, min(b, a + HB_TOOL_CAP_S)) for a, b in ivs]))
                wait += full - tot
            busy[n] = int(round(tot * 1000))
    trows = [{"name": n, "calls": c, "busy_ms": (busy.get(n, 0) if intervals is not None else None)}
             for n, c in n_calls.items()]
    trows += [{"name": n, "calls": 0, "busy_ms": b} for n, b in busy.items() if n not in n_calls]
    trows.sort(key=lambda r: (r["busy_ms"] is None, -(r["busy_ms"] or 0), -r["calls"], r["name"]))
    rest = trows[HB_TOP:]
    by_tool = {"rows": trows[:HB_TOP],
               "rest": {"n": len(rest), "calls": sum(r["calls"] for r in rest)} if rest else None}
    # agents: main first, then by size
    per = _hb_group(turns, lambda x: x[5])
    for aid in labels:
        per.setdefault(aid, {"out": 0, "fresh": 0, "cache": 0})
    mm = {}
    for x in turns:
        if x[5] == "" and x[1]:
            mm[x[1]] = mm.get(x[1], 0) + x[2] + x[3] + x[4]
    arows = []
    for aid, r in per.items():
        if aid == "":
            lab, mod = "main", (max(mm, key=mm.get) if mm else "")
        else:
            lab, mod = labels.get(aid, ("agent " + aid[:7], ""))
        arows.append(dict(label=lab, aid=aid, model=mod, **r))
    arows.sort(key=lambda r: (r["aid"] != "", -(r["out"] + r["fresh"] + r["cache"]), r["label"]))
    mrows = [dict(model=m, **r) for m, r in _hb_group(turns, lambda x: x[1]).items()
             if m or r["out"] + r["fresh"] + r["cache"]]   # drop <synthetic> "" zero-token rows
    mrows.sort(key=lambda r: (-(r["out"] + r["fresh"] + r["cache"]), r["model"]))
    return {"span": [t0, t1] if t0 is not None else None, "bucket_s": bs, "beats": beats,
            "by_tool": by_tool, "waiting_ms": int(round(wait * 1000)) if intervals is not None else None,
            "by_agent": {"rows": arows[:HB_TOP], "rest": _hb_rest(arows[HB_TOP:])},
            "by_model": {"rows": mrows[:HB_TOP], "rest": _hb_rest(mrows[HB_TOP:])},
            "total": total, "agents_n": len([a for a in per if a]), "note": note}


def empty_heartbeat(note=None):
    return build_heartbeat([], [], note=note)
