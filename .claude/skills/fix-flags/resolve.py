#!/usr/bin/env python3
"""Flag helper for the fix-flags skill.

Usage:
  resolve.py list              # print open (unresolved) flags
  resolve.py resolve <id>...   # mark flag id(s) resolved
  resolve.py selfcheck         # self-test

Locates flags.json from $FLAGS_FILE, then ./flags.json, then the
claude-tracker project root relative to this script.
"""
import json
import os
import sys


def flags_path():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = (
        os.environ.get("FLAGS_FILE"),
        "flags.json",
        os.path.normpath(os.path.join(here, "..", "..", "..", "flags.json")),
    )
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return "flags.json"


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save(path, flags):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(flags, fh, indent=2)
    os.replace(tmp, path)


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "selfcheck":
        return _selfcheck()
    path = flags_path()
    flags = load(path)
    if cmd == "list":
        openf = [f for f in flags if not f.get("resolved")]
        if not openf:
            print("no open flags (%s)" % path)
            return 0
        print("%d open flag(s) in %s:\n" % (len(openf), path))
        for f in openf:
            print("id:%s  session:%s" % (f.get("id"), str(f.get("session", ""))[:8]))
            print("  note:", (f.get("note") or "").strip())
            if f.get("context"):
                print("  context:", f["context"].strip())
            print()
        return 0
    if cmd == "resolve":
        try:
            ids = {int(x) for x in argv[1:]}
        except ValueError:
            print("ids must be integers"); return 1
        if not ids:
            print("usage: resolve.py resolve <id>..."); return 1
        n = 0
        for f in flags:
            if f.get("id") in ids and not f.get("resolved"):
                f["resolved"] = True
                n += 1
        save(path, flags)
        print("resolved %d flag(s) in %s" % (n, path))
        return 0
    print("unknown command:", cmd)
    return 1


def _selfcheck():
    import tempfile
    p = tempfile.mktemp(suffix=".json")
    save(p, [{"id": 1, "note": "x", "resolved": False},
             {"id": 2, "note": "y", "resolved": False}])
    assert sum(1 for f in load(p) if not f["resolved"]) == 2
    os.environ["FLAGS_FILE"] = p
    main(["resolve", "1"])
    fs = load(p)
    assert fs[0]["resolved"] is True and fs[1]["resolved"] is False, fs
    os.unlink(p)
    print("resolve.py selfcheck ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
