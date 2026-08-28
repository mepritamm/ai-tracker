"""Self-check suite for ai-tracker — the former in-file _selfcheck, as stdlib unittest.

Run: python -m unittest discover -s tests   (or: make check)
"""
import json
import os
import tempfile
import time
import unittest

from aitracker import config
from aitracker.config import LIVE_WINDOW
from aitracker.util import _short_title, _window, _git_branch, push_when
from aitracker.store import load_flags, save_flags, load_titles, load_tasks, load_notes, save_notes, _save_json
from aitracker.registry import parse_any, all_sessions
from aitracker.providers.claude import (
    parse_session, parse_agents, parse_shells, _match_content, _active_mtime,
    file_diffs, command_output, shell_output, agent_detail, _redirect_log,
    list_sessions, child_agent_sessions, _agent_group, _pick_parent, _mtime_and_bg, _tail_fields,
    _is_bg_agent)
from aitracker.providers.auggie import (
    list_auggie, parse_auggie, search_auggie, _AUGGIE_LIST_CACHE, _auggie_state)


def _run():
    import tempfile
    rows = [
        {"type": "user", "cwd": "/x/proj", "gitBranch": "main", "version": "1.0",
         "message": {"role": "user", "content": "build the thing"}},
        # a slash-command invocation is a <command-...> wrapper STRING → shows as the "/foo args" typed
        {"type": "user", "message": {"role": "user", "content":
            "<command-message>smasher-gap</command-message>\n<command-name>/smasher-gap</command-name>\n<command-args>fix the parser bug</command-args>"}},
        # non-command <...> noise (task-notification, system-reminder) has no <command-name> → excluded
        {"type": "user", "message": {"role": "user", "content":
            "<task-notification>\n<task-id>abc</task-id>\n</task-notification>"}},
        # a real typed prompt with a pasted image → content is a LIST of blocks; must be captured
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "image", "source": {}},
            {"type": "text", "text": "fix the parser"}]}},
        # a slash-command/skill expansion is a separate user message tagged isMeta → NOT a prompt
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": "Base directory for this skill: /x/skills/foo"}]}},
        # isMeta system notices arrive as a plain STRING too (skill reload, /context) → NOT a prompt
        {"type": "user", "isMeta": True,
         "message": {"role": "user", "content": "Skill /foo is already loaded above; instructions unchanged."}},
        # "effort" is a TOP-LEVEL field of the record, a sibling of "message" -- never nested
        # inside it (confirmed against a real ~/.claude/projects/*/*.jsonl transcript).
        {"type": "assistant", "timestamp": "2026-06-22T10:00:00.000Z", "effort": "high",
         "message": {"usage": {"input_tokens": 100, "output_tokens": 20},
                     "content": [
                         {"type": "text", "text": "starting"},
                         {"type": "tool_use", "name": "TodoWrite",
                          "input": {"todos": [
                              {"content": "a", "status": "completed", "activeForm": "doing a"},
                              {"content": "b", "status": "in_progress", "activeForm": "doing b"}]}},
                         {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/proj/foo.py", "content": "line1\nline2\n"}},
                         {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/proj/foo.py", "old_string": "line1", "new_string": "LINE1"}},
                         {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/proj/bar.py"}},
                         {"type": "tool_use", "id": "t1", "name": "Bash",
                          "input": {"command": "pytest -q"}},
                         {"type": "tool_use", "id": "t2", "name": "Bash",
                          "input": {"command": "git commit -m \"add foo\""}}]}},
        # a second assistant turn with a DIFFERENT top-level effort -- proves last-value-wins,
        # same as "model". Empty usage/content so it doesn't disturb any other assertion below.
        {"type": "assistant", "timestamp": "2026-06-22T10:00:05.000Z", "effort": "low",
         "message": {}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "boom"}]}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.write("garbage not json\n")  # must be skipped, not crash
        path = f.name
    d = parse_session(path)
    df = file_diffs(path, "/x/proj/foo.py")  # before unlink — reads the file again
    co = command_output(path, "t1")
    os.unlink(path)
    c = d["counts"]
    assert len(d["todos"]) == 2 and c["done"] == 1, d["todos"]
    assert d["files"][0]["path"] == "/x/proj/foo.py" and d["files"][0]["ops"] == 2, d["files"]
    assert d["files"][0]["created"] is True, "Write should mark created"
    # per-file diffs reconstructed from the transcript (Write content, Edit old/new)
    assert len(df) == 2 and df[0]["kind"] == "created" and df[1]["kind"] == "edited", df
    assert "+line1" in df[0]["diff"], df[0]["diff"]
    assert "-line1" in df[1]["diff"] and "+LINE1" in df[1]["diff"], df[1]["diff"]
    # command output fetched on click: command text + its (failed) result output
    assert co["cmd"] == "pytest -q" and co["ok"] is False and "boom" in co["out"], co
    assert c["created"] == 1 and c["read"] == 1, c
    assert d["commits"][0]["msg"] == "add foo", d["commits"]
    assert c["tests"] == 1 and c["tests_failed"] == 1, "failed pytest via is_error link"
    # string prompt + slash-command + list-form prompt captured; task-notification, isMeta expansion, tool_result excluded
    assert [r["text"] for r in d["requests"]] == \
        ["build the thing", "/smasher-gap fix the parser bug", "fix the parser"], d["requests"]
    assert d["tokens"]["in"] == 100
    # context occupancy: the ONE usage block's input_tokens (no cache fields in this fixture) —
    # Claude's JSONL never states a context-window size, so limit/pct stay honestly None.
    assert d["context"] == {"current": 100, "limit": None, "pct": None}, d["context"]
    assert [n["text"] for n in d["narrative"]] == ["starting"], d["narrative"]
    ov = d["overview"]
    assert ov["goal"] == "fix the parser", ov  # goal = latest prompt (now incl. list-form)
    assert ov["now"] == "▶ doing b", ov
    assert "ouched 1 file(s) (foo.py)" in ov["sofar"], ov
    assert "ran 2 command(s)" in ov["sofar"] and "1 commit" in ov["sofar"], ov
    assert ov["commits"] == ["add foo"], ov
    assert d["meta"]["title"] == "Build the thing", d["meta"].get("title")
    # reasoning effort: last non-empty top-level "effort" wins, exactly like "model" —
    # the fixture's two assistant turns carry "high" then "low".
    assert d["meta"]["effort"] == "low", d["meta"].get("effort")

    # short-title derivation: strips filler, shortens, keeps it readable
    assert _short_title("Can you create a HTML tracker where I paste the session id and track it") \
        == "Create a HTML tracker where I paste the…", _short_title("Can you create a HTML tracker where I paste the session id and track it")
    assert _short_title("I want you to implement the create_contact tool") \
        == "Implement the create_contact tool", _short_title("I want you to implement the create_contact tool")

    # background-agent detection: agent files under <session-id>/ keep it "live"
    import tempfile as _tf
    sdir = _tf.mkdtemp()
    spath = os.path.join(sdir, "sess.jsonl")
    with open(spath, "w") as f:
        f.write(json.dumps({"type": "user", "cwd": "/x",
                            "message": {"role": "user", "content": "go"}}) + "\n")
    adir = os.path.join(sdir, "sess", "subagents", "workflows", "wf_abc123")
    os.makedirs(adir)
    with open(os.path.join(adir, "agent-deadbeef00.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "timestamp": "2026-06-22T10:00:00Z",
                            "message": {"role": "user", "content": "Audit the auth module"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:01:00Z",
                            "message": {"content": [
            {"type": "text", "text": "Scanning auth.py for issues"},
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "/x/.worktrees/wt/auth.py",
                       "old_string": "a", "new_string": "b"}}]}}) + "\n")
    ags, newest, afiles, aprs, apst = parse_agents(spath)
    assert len(ags) == 1 and ags[0]["task"] == "Audit the auth module", ags
    assert ags[0]["last"] == "Scanning auth.py for issues" and ags[0]["tools"] == 2, ags
    assert ags[0]["wf"] == "wf_abc123", ags
    assert "/x/.worktrees/wt/auth.py" in afiles, afiles         # agent file edit captured
    assert _active_mtime(spath) >= os.path.getmtime(spath)
    # a live in-transcript agent -> bg count so the sidebar can badge it (no separate agent session)
    mt_bg, bg_n = _mtime_and_bg(spath)
    assert bg_n == 1 and mt_bg == _active_mtime(spath), (bg_n, mt_bg)
    ds = parse_session(spath)
    # no assistant record in THIS session's own transcript carries "effort" at all (only its
    # subagent file does, and that's a separate transcript) -- absent, not a crash or a fake "".
    assert "effort" not in ds["meta"], ds["meta"]
    assert len(ds["agents_bg"]) == 1 and "background agent" in ds["overview"]["now"], ds["overview"]["now"]
    afile = next((x for x in ds["files"] if x["path"] == "/x/.worktrees/wt/auth.py"), None)
    assert afile and afile.get("agent"), "agent-edited file must surface in files, tagged"  # the gap
    # a file BOTH the main session and an agent touch must STILL carry the 🤖 marker
    # ("created OR updated by the agent") — not only files the main session never touched.
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"file_path": "/x/shared.py"}}]}}) + "\n")
    with open(os.path.join(adir, "agent-deadbeef00.jsonl"), "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:02:00Z", "message": {"content": [
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": "/x/shared.py", "old_string": "a", "new_string": "b"}}]}}) + "\n")
    shared = next((x for x in parse_session(spath)["files"] if x["path"] == "/x/shared.py"), None)
    assert shared and shared.get("agent"), "a file touched by BOTH main and an agent stays tagged 🤖"  # the fix

    # a PR a BACKGROUND AGENT opens (gh pr create in the subagent) is attributed to the session,
    # tagged 🤖, and its merge state surfaces — else agent-generated PRs vanish (the flagged gap).
    with open(os.path.join(adir, "agent-deadbeef00.jsonl"), "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:03:00Z", "message": {"content": [
            {"type": "tool_use", "id": "aprc", "name": "Bash", "input": {"command": "gh pr create --fill"}}]}}) + "\n")
        f.write(json.dumps({"type": "user", "timestamp": "2026-06-22T10:03:30Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "aprc",
             "content": "https://github.com/acme/app/pull/77"}]}}) + "\n")
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:04:00Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "x",
             "content": "abc Merge pull request #77 from acme/feat"}]}}) + "\n")
    apr = next((x for x in parse_session(spath)["prs"] if x["num"] == "77"), None)
    assert apr and apr["created"] and apr.get("agent"), "agent-opened PR must surface, tagged 🤖"  # the gap
    assert apr["state"] == "merged", "the agent PR's merge state must surface too"

    # live window: activity within 5 min counts as live; older does not
    af = os.path.join(adir, "agent-deadbeef00.jsonl")
    os.utime(af, (time.time() - 200, time.time() - 200))
    assert parse_agents(spath)[0][0]["running"] is True, "200s ago should still be live"
    os.utime(af, (time.time() - 400, time.time() - 400))
    assert parse_agents(spath)[0][0]["running"] is False, "400s ago should be stale"
    assert parse_agents(spath)[0][0]["aid"] == "deadbeef00", "agent detail id"

    # agent_detail returns the FULL prompt (multi-paragraph, un-truncated) — the card blurb
    # collapses to 160 chars, but the click-through detail must not lose the message.
    longtask = "Map the pipeline.\n\n" + "x" * 400 + "\n\nStop before any push."
    adir2 = os.path.join(sdir, "sess", "subagents", "workflows", "wf_full")
    os.makedirs(adir2)
    with open(os.path.join(adir2, "agent-cafebabe00.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "timestamp": "2026-06-22T10:00:00Z",
                            "message": {"role": "user", "content": longtask}}) + "\n")
    det = agent_detail(spath, "cafebabe00")
    assert det["task"] == longtask, "detail task must be full & keep paragraph breaks"

    # background shells: launch + result naming id/output file; live .output -> running
    outp = os.path.join(sdir, "srv.output")
    with open(outp, "w") as f:
        f.write("booting\nlistening on :8765\n")
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:01:00Z", "message": {"content": [
            {"type": "tool_use", "id": "bgL", "name": "Bash",
             "input": {"command": "python srv.py", "description": "Serve fixtures", "run_in_background": True}}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "bgL",
             "content": "Command running in background with ID: abcd1234. Output is being written to: %s. You will be notified." % outp}]}}) + "\n")
    shls = parse_shells(spath)
    assert len(shls) == 1 and shls[0]["id"] == "abcd1234" and shls[0]["desc"] == "Serve fixtures", shls
    assert shls[0]["last"] == "listening on :8765" and shls[0]["running"] is True, shls
    so = shell_output(spath, "abcd1234")
    assert so["cmd"] == "python srv.py" and "listening on :8765" in so["out"] and so["running"] is True, so
    # running until a <task-notification> for that id arrives — NOT output-file mtime
    os.utime(outp, (time.time() - 400, time.time() - 400))
    assert parse_shells(spath)[0]["running"] is True, "stale output file alone must NOT mark it done"
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user",
                "content": "<task-notification>\n<task-id>abcd1234</task-id>\n</task-notification>"}}) + "\n")
    assert parse_shells(spath)[0]["running"] is False, "task-notification -> done"

    # output fallback: command redirects to its own LOG, harness .output stays empty
    logf = os.path.join(sdir, "heal.log")
    with open(logf, "w") as f:
        f.write("driver started\nPASS 12/12\n")
    empty_out = os.path.join(sdir, "job2.output")
    open(empty_out, "w").close()  # harness file empty — output went to LOG
    assert _redirect_log('LOG=%s\npython x.py > "$LOG" 2>&1' % logf) == logf
    with open(spath, "a") as f:
        f.write(json.dumps({"type": "assistant", "timestamp": "2026-06-22T10:02:00Z", "message": {"content": [
            {"type": "tool_use", "id": "bgL2", "name": "Bash",
             "input": {"command": 'LOG=%s\npython x.py > "$LOG" 2>&1' % logf, "run_in_background": True}}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "bgL2",
             "content": "Command running in background with ID: ef567890. Output is being written to: %s." % empty_out}]}}) + "\n")
    so2 = shell_output(spath, "ef567890")
    assert "PASS 12/12" in so2["out"], so2  # fell back to the LOG file

    # search: matches real content, prefers user prompts, and ignores boilerplate
    w = _window("the quick brown fox jumps over", "brown", pad=5)
    assert "brown" in w and w.startswith("…") and w.endswith("…"), w
    data = "\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": "fix the auth bug please"}}),
        json.dumps({"type": "user", "message": {"role": "user", "content": "<system-reminder>skills: bitbucket-automation, auth bug helper</system-reminder>"}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "the auth bug is in login"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "grep auth bug"}}]}}),
    ])
    cnt, snip, inq = _match_content(data, "auth bug")
    assert cnt >= 2 and inq is True and "auth bug" in snip.lower(), (cnt, snip, inq)
    # a term that lives ONLY in the injected skill list must NOT match
    assert _match_content(data, "bitbucket-automation")[0] == 0, "boilerplate leaked into search"

    # background-agent detection: both real claude --bg (sessionKind:"bg") and SDK-spawned (sdk-cli)
    # should be flagged as agents and show the 🤖 badge
    assert _is_bg_agent({"sessionKind": "bg", "source": "cli"}), "real claude --bg sessions have sessionKind:bg"
    assert _is_bg_agent({"sessionKind": None, "source": "sdk-cli"}), "SDK-spawned sessions have source:sdk-cli"
    assert _is_bg_agent({"sessionKind": "bg", "source": "sdk-cli"}), "overlapping markers both true"
    assert not _is_bg_agent({"sessionKind": None, "source": "cli"}), "regular interactive sessions have neither"
    assert not _is_bg_agent({"sessionKind": None, "source": "claude-desktop"}), "desktop sessions are not agents"

    # background-agent (SDK) sessions nest under their ORIGINATING session — attributed by shared PROJECT
    # DIR (the SDK writes each agent transcript beside its orchestrator, even when their cwd fields differ)
    # and by who was live when the agent spawned (latest start <= agent start — handles resume chains).
    assert _agent_group("/repo/x/.claude/worktrees/wt-a", "sdk-cli") == ("/repo/x", "x")
    assert _agent_group("/repo/x", "cli") == ("", ""), "human sessions are never agents"
    assert _pick_parent(500, [("A", 100), ("B", 400), ("C", 900)]) == "B", "latest start <= agent"
    assert _pick_parent(50, [("A", 100), ("B", 400)]) == "A", "predates all -> earliest human"
    # order-independent on ties, so the sidebar (mtime order) and the detail panel (glob order) agree;
    # and a start-less session (first==0, its first line not yet written) is 'unknown', never 'earliest'
    assert _pick_parent(500, [("a", 100), ("b", 100)]) == _pick_parent(500, [("b", 100), ("a", 100)]), "tie must not depend on feed order"
    assert _pick_parent(100, [("hnew", 0.0), ("hreal", 500)]) == "hreal", "a first=0 session is not the earliest fallback"
    from aitracker.util import _ts_epoch, _iso_epoch as _ie
    assert _ts_epoch("2026-06-01T00:00:00.750Z") > _ts_epoch("2026-06-01T00:00:00.100Z"), "_ts_epoch keeps sub-second order"
    assert _ie("2026-06-01T00:00:00.750Z") == _ie("2026-06-01T00:00:00.100Z"), "_iso_epoch floors to the whole second"
    assert _ts_epoch("") == 0.0 and _ts_epoch("nonsense") == 0.0, "_ts_epoch tolerates junk"
    pdir = tempfile.mkdtemp(); config.PROJECTS = pdir
    WT = "/repo/x/.claude/worktrees/wt-a"
    d1 = os.path.join(pdir, "-repo-x--claude-worktrees-wt-a"); os.makedirs(d1)
    def _mk(dd, fn, cwd, ep, ts, content="go"):
        with open(os.path.join(dd, fn), "w") as f:
            f.write(json.dumps({"cwd": cwd, "entrypoint": ep, "timestamp": ts,
                                "message": {"role": "user", "content": content}}) + "\n")
    _mk(d1, "orchA.jsonl", WT, "cli", "2026-06-01T10:00:00Z", "start the run")   # first orchestrator
    _mk(d1, "orchB.jsonl", WT, "cli", "2026-06-01T12:00:00Z", "resume the run")  # resumed later, same dir
    _mk(d1, "ag_late.jsonl", WT, "sdk-cli", "2026-06-01T12:30:00Z", "finding 1")  # after orchB -> orchB
    _mk(d1, "ag_mid.jsonl",  WT, "sdk-cli", "2026-06-01T11:00:00Z", "finding 2")  # between A and B -> orchA
    # repo-root-orchestrator topology: the orchestrator's file is in the worktree dir but its cwd is the
    # REPO ROOT (not the worktree). Attribution must still find it — via the shared dir, not the cwd field.
    d3 = os.path.join(pdir, "-repo-x--claude-worktrees-wt-c"); os.makedirs(d3)
    _mk(d3, "orchR.jsonl", "/repo/x", "cli", "2026-06-01T08:00:00Z", "drive from the repo root")
    _mk(d3, "ag_root.jsonl", "/repo/x/.claude/worktrees/wt-c", "sdk-cli", "2026-06-01T08:30:00Z", "finding 3")
    d2 = os.path.join(pdir, "-repo-x--claude-worktrees-wt-b"); os.makedirs(d2)   # dir with agents but no human
    _mk(d2, "ag_orphan.jsonl", "/repo/x/.claude/worktrees/wt-b", "sdk-cli", "2026-06-01T09:00:00Z", "orphan")
    # real claude --bg background agents with sessionKind:"bg" should also be flagged as agent=True
    _mk(d1, "bg_real.jsonl", WT, "cli", "2026-06-01T14:00:00Z", "analyzing the code")
    with open(os.path.join(d1, "bg_real.jsonl"), "r") as f:
        bg_line = json.loads(f.readline())
    bg_line["sessionKind"] = "bg"
    with open(os.path.join(d1, "bg_real.jsonl"), "w") as f:
        f.write(json.dumps(bg_line) + "\n")

    ls = {s["id"]: s for s in list_sessions()}
    assert ls["ag_late"]["agent"] and ls["ag_late"]["parentId"] == "orchB", ls["ag_late"]
    assert ls["ag_mid"]["parentId"] == "orchA", ls["ag_mid"]
    assert ls["ag_root"]["parentId"] == "orchR", "repo-root orchestrator attributed via shared dir despite cwd mismatch"
    assert ls["ag_orphan"]["parentId"] == "" and ls["ag_orphan"]["group"] == "/repo/x", "no same-dir human -> bucket"
    assert not ls["orchR"]["agent"] and ls["orchR"]["parentId"] == "", ls["orchR"]
    assert ls["bg_real"]["agent"] and not ls["bg_real"]["parentId"], "real claude --bg sessions get agent=True and no parent"
    kb = child_agent_sessions("orchB", d1)           # detail uses the SAME dir-scoped set as the sidebar
    assert [k["id"] for k in kb] == ["ag_late"] and kb[0]["wt"] == "wt-a", kb
    assert kb[0]["runs"] == 1, kb                    # a single-run agent reports runs=1
    assert [k["id"] for k in child_agent_sessions("orchA", d1)] == ["ag_mid"], "each orchestrator gets its own agents"
    assert [k["id"] for k in child_agent_sessions("orchR", d3)] == ["ag_root"], "repo-root orchestrator surfaces its agent"

    # sidebar end-state (Claude): waiting = unanswered AskUserQuestion; ended = last real turn is assistant text
    d4 = os.path.join(pdir, "-repo-x-state"); os.makedirs(d4)   # PROJECTS/*/*.jsonl -> needs a subdir to be listed
    def _mklines(fn, rows):
        p = os.path.join(d4, fn + ".jsonl")
        with open(p, "w") as fh:
            for r in rows: fh.write(json.dumps(r) + "\n")
        return p
    UMSG = {"cwd": "/repo/x", "entrypoint": "cli", "timestamp": "2026-06-01T10:00:00Z",
            "type": "user", "message": {"role": "user", "content": "go"}}
    ASK = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": {"questions": []}}]}}
    ANS = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "q1", "content": "picked A"}]}}
    TXT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "all done ✅"}]}}
    assert _tail_fields(_mklines("s_wait", [UMSG, ASK]))[3:] == (True, False), "open question -> waiting, not ended"
    assert _tail_fields(_mklines("s_done", [UMSG, TXT]))[3:] == (False, True), "assistant finished -> ended"
    assert _tail_fields(_mklines("s_answered", [UMSG, ASK, ANS, TXT]))[3:] == (False, True), "answered then replied -> ended, not waiting"
    assert _tail_fields(_mklines("s_mid", [UMSG, ASK, ANS]))[3:] == (False, False), "stopped on a tool_result -> neither"
    # ignore a trailing task-notification (isMeta / <...> system text) — a completed session stays 'ended'
    NOTE = {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<task-notification>x</task-notification>"}}
    assert _tail_fields(_mklines("s_note", [UMSG, TXT, NOTE]))[3:] == (False, True), "trailing notification doesn't unset ended"
    ls2 = {s["id"]: s for s in list_sessions()}
    assert ls2["s_wait"]["waiting"] and not ls2["s_wait"]["ended"], ls2["s_wait"]   # wired onto the list dict
    assert ls2["s_done"]["ended"] and not ls2["s_done"]["waiting"], ls2["s_done"]
    # …and onto the DETAIL dict too, so the header can say "waiting on you" instead of "idle 26m ago"
    assert parse_session(_mklines("s_wait", [UMSG, ASK]))["waiting"] is True, "unanswered question -> detail waiting"
    assert parse_session(_mklines("s_answered", [UMSG, ASK, ANS, TXT]))["waiting"] is False, "answered -> not waiting"
    assert parse_session(_mklines("s_none", [UMSG, TXT]))["waiting"] is False, "no question at all -> not waiting"

    # sidebar end-state (Auggie): same capability off ask-user / response_text — parity with Claude
    def _ex(**kw): return {"exchange": kw}
    waiting_chat = [_ex(request_message="go", response_text="thinking",
                        response_nodes=[{"tool_use": {"tool_name": "ask-user", "tool_use_id": "a1"}}])]
    assert _auggie_state(waiting_chat) == (True, False), "open ask-user -> waiting"
    answered_chat = waiting_chat + [_ex(request_nodes=[{"tool_result_node": {"tool_use_id": "a1"}}],
                                        response_text="here you go")]
    assert _auggie_state(answered_chat) == (False, True), "answered ask-user then replied -> ended"
    assert _auggie_state([_ex(request_message="go", response_text="done")]) == (False, True), "plain reply -> ended"
    assert child_agent_sessions("ag_late", d1) == [], "an agent is not the orchestrator of its siblings"
    # re-runs of the SAME agent (identical task/first-prompt) collapse to ONE entry so the count isn't
    # inflated; the most-recently-active run represents the group (the open target) and runs=N counts them.
    _mk(d1, "ag_late2.jsonl", WT, "sdk-cli", "2026-06-01T13:00:00Z", "finding 1")  # re-run of ag_late's task
    _mk(d1, "ag_late3.jsonl", WT, "sdk-cli", "2026-06-01T12:45:00Z", "finding 1")  # a third run
    for fn, age in [("ag_late.jsonl", 300), ("ag_late3.jsonl", 200), ("ag_late2.jsonl", 100)]:
        os.utime(os.path.join(d1, fn), (time.time() - age, time.time() - age))     # ag_late2 = newest active
    dup = child_agent_sessions("orchB", d1)
    assert [k["id"] for k in dup] == ["ag_late2"], "same task collapses; the freshest run represents it"
    assert dup[0]["runs"] == 3, dup                     # three executions counted, one row

    # auggie (Augment CLI) sessions from ~/.augment/sessions + todos from task-storage
    config.AUGMENT_DIR = tempfile.mkdtemp()
    config.AUGGIE_SESSIONS = os.path.join(config.AUGMENT_DIR, "sessions")
    os.makedirs(config.AUGGIE_SESSIONS)
    atd = os.path.join(config.AUGMENT_DIR, "task-storage", "tasks")
    os.makedirs(atd)
    _AUGGIE_LIST_CACHE.clear()
    with open(os.path.join(config.AUGMENT_DIR, "settings.json"), "w") as fh:
        json.dump({"indexingAllowDirs": ["/x/myrepo", "/x"]}, fh)  # two roots; specific one wins

    def _wtask(u, **kw):
        with open(os.path.join(atd, u), "w") as fh:
            json.dump({"uuid": u, **kw}, fh)
    _wtask("root1", name="Current Task List", description="Root task for conversation Z", subTasks=["s1", "s2"])
    _wtask("s1", name="step one", state="COMPLETE", subTasks=[])
    _wtask("s2", name="step two", state="IN_PROGRESS", subTasks=[])
    with open(os.path.join(config.AUGGIE_SESSIONS, "sess1.json"), "w") as fh:
        json.dump({"sessionId": "sess1", "modified": "2026-06-27T05:48:03Z",
                   "customTitle": "List Home Dir", "rootTaskUuid": "root1",
                   "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                                    "exchange": {"request_message": "list the dir",
                                                 "response_text": "I'll list it. " + "Z" * 2000,
                                                 "request_nodes": [{"ide_state_node": {"current_terminal": {
                                                     "current_working_directory": "/work/dw-stack"}}}],
                                                 "response_nodes": [
                                                     {"token_usage": {"input_tokens": 10, "output_tokens": 20,
                                                                      "cache_read_input_tokens": 100,
                                                                      "max_context_tokens": 550}},
                                                     # input_json is a JSON *string* in every real log (0/3882
                                                     # nodes on this machine carry it as a dict) — these three
                                                     # match that real shape like the edit-tool nodes below do.
                                                     {"tool_use": {"tool_name": "launch-process", "tool_use_id": "c1",
                                                                   "input_json": json.dumps({"command": "git commit -m \"fix it\""})}},
                                                     {"tool_use": {"tool_name": "launch-process", "tool_use_id": "c2",
                                                                   "input_json": json.dumps({"command": "pytest -q"})}},
                                                     {"tool_use": {"tool_name": "view", "tool_use_id": "v1",
                                                                   "input_json": json.dumps({"path": "app.py", "type": "file"})}},
                                                     # the REAL edit shape: input_json is a JSON *string*,
                                                     # str-replace-editor paths are usually cwd-relative
                                                     {"tool_use": {"tool_name": "save-file", "tool_use_id": "w1",
                                                                   "input_json": json.dumps({"path": "/work/dw-stack/new.py",
                                                                                             "file_content": "hello\n"})}},
                                                     {"tool_use": {"tool_name": "str-replace-editor", "tool_use_id": "w2",
                                                                   "input_json": json.dumps({"command": "str_replace", "path": "app.py",
                                                                                             "old_str_1": "old", "new_str_1": "new"})}},
                                                     {"tool_use": {"tool_name": "sub-agent-explore", "tool_use_id": "sa1",
                                                                   "input_json": json.dumps({"action": "run", "name": "find the seam",
                                                                                             "instruction": "read it"})}}]}},
                                   # results arrive the NEXT exchange, keyed by tool_use_id, each with is_error
                                   {"finishedAt": "2026-06-27T05:48:10Z",
                                    "exchange": {"response_text": "done",
                                                 "request_nodes": [
                                                     {"tool_result_node": {"tool_use_id": "c1", "content": "ok", "is_error": False}},
                                                     {"tool_result_node": {"tool_use_id": "c2", "is_error": True,
                                                                           "content": "<return-code>\n1\n</return-code>\n1 failed"}}]}}]}, fh)
    al = list_auggie()
    assert len(al) == 1 and al[0]["id"] == "auggie:sess1", al
    # real IDE cwd wins over the indexed-root/changed-file fallback (matches Claude's per-session cwd)
    assert al[0]["source"] == "auggie" and al[0]["project"] == "dw-stack" and al[0]["cwd"] == "/work/dw-stack", al
    assert al[0]["title"] == "List Home Dir", al                       # customTitle wins
    pa = parse_auggie("sess1")
    assert pa and pa["counts"]["done"] == 1 and pa["counts"]["todos"] == 2, pa   # todos via rootTaskUuid
    assert [r["text"] for r in pa["requests"]] == ["list the dir"], pa["requests"]
    _narr = next((n for n in pa["narrative"] if "list it" in n["text"].lower()), None)
    assert _narr, pa["narrative"]
    assert len(_narr["text"]) > 2000, "narration must keep the full message, not cap at 900"
    assert pa["tokens"] == {"in": 110, "out": 20}, pa["tokens"]          # input + cache, like Claude
    # context occupancy + limit: Auggie's token_usage carries max_context_tokens (Claude's
    # doesn't), so a real percentage is honestly derivable here — 110/550 = 20.0%.
    assert pa["context"] == {"current": 110, "limit": 550, "pct": 20.0}, pa["context"]
    assert pa["meta"]["cwd"] == "/work/dw-stack", pa["meta"]["cwd"]      # real IDE cwd, like Claude
    # parity: commands (launch-process), reads (view), commits + tests — like Claude
    assert len(pa["commands"]) == 2 and pa["counts"]["read"] == 1, (pa["commands"], pa["counts"])
    assert pa["counts"]["commits"] == 1 and pa["counts"]["tests"] == 1, pa["counts"]
    assert pa["commits"] and pa["commits"][0]["msg"] == "fix it", pa["commits"]
    # `view`'s path is anchored to the cwd, like `files` — 13/85 real sessions carry both
    # relative and absolute read paths for the same tree, so an un-anchored `reads` entry
    # can double-count against `files` and the two panels visibly disagree on one file.
    assert pa["reads"][0]["path"] == "/work/dw-stack/app.py", pa["reads"]
    # parity: files, sub-agents and command exit status — the three Auggie used to drop.
    byf = {x["path"]: x for x in pa["files"]}
    assert byf["/work/dw-stack/new.py"]["created"], "save-file == Write -> created"      # (C)
    assert "/work/dw-stack/app.py" in byf, byf     # str-replace-editor path anchored to the cwd
    assert not byf["/work/dw-stack/app.py"]["created"], byf
    assert (pa["counts"]["created"], pa["counts"]["edited"]) == (1, 1), pa["counts"]
    assert [(a["type"], a["desc"]) for a in pa["agents"]] == [("explore", "find the seam")], pa["agents"]   # (B)
    assert pa["counts"]["agents"] == 1, pa["counts"]
    ok_by = {c["id"]: c["ok"] for c in pa["commands"]}                                    # (A)
    assert ok_by == {"c1": True, "c2": False}, "tool_result_node.is_error must reach the command"
    assert (pa["counts"]["errors"], pa["counts"]["tests_failed"]) == (1, 1), pa["counts"]
    # the drill-downs behind those panels, routed through the provider seam (not find_session)
    from aitracker.registry import drill
    assert drill("auggie:sess1", "output", "c2")["out"].endswith("1 failed"), "auggie command output"
    assert drill("auggie:sess1", "diff", "/work/dw-stack/app.py")[0]["kind"] == "edited"
    assert drill("auggie:sess1", "output", "nope") == {"cmd": "", "out": "", "ok": True}
    assert drill("auggie:missing", "output", "c1") is None, "unknown session -> the route 404s"
    assert drill("auggie:sess1", "shell", "x") == {"cmd": "", "out": "", "running": False}  # safe default
    assert "gitBranch" in pa["meta"], "auggie meta must carry gitBranch like Claude"
    # reasoning effort is a Claude-only concept -- Auggie degrades by OMITTING the key
    # entirely (unlike "model", which Auggie has but may report as ""), never faking a value.
    assert "effort" not in pa["meta"], "auggie meta must not fake a reasoning-effort field"
    assert pa["waiting"] is False, "no open ask-user -> not waiting"
    assert parse_auggie("missing") is None

    # detail-dict `waiting` spans BOTH providers — an unanswered ask-user must reach parse_auggie
    # the same way an unanswered AskUserQuestion reaches parse_session (one capability, one shape).
    with open(os.path.join(config.AUGGIE_SESSIONS, "sess_wait.json"), "w") as fh:
        json.dump({"sessionId": "sess_wait", "modified": "2026-06-27T05:48:03Z", "customTitle": "Blocked",
                   "chatHistory": [{"finishedAt": "2026-06-27T05:47:50Z",
                                    "exchange": {"request_message": "which one?", "response_text": "asking",
                                                 "response_nodes": [{"tool_use": {"tool_name": "ask-user",
                                                                     "tool_use_id": "w1"}}]}}]}, fh)
    assert parse_auggie("sess_wait")["waiting"] is True, "auggie: open ask-user -> detail waiting"
    _AUGGIE_LIST_CACHE.clear()

    # 🚩 open-flag counts land on the shared list dict in registry.all_sessions(), so BOTH
    # providers inherit the badge — a flag on a session you aren't viewing must still be findable.
    _flag_snap = config.FLAGS_FILE
    config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
    save_flags([{"id": 1, "session": "s_wait", "note": "open one", "resolved": False},
                {"id": 2, "session": "s_wait", "note": "another", "resolved": False},
                {"id": 3, "session": "s_wait", "note": "already handled", "resolved": True},
                {"id": 4, "session": "auggie:sess1", "note": "auggie gap", "resolved": False}])
    byid = {s["id"]: s for s in all_sessions()}
    assert byid["s_wait"]["open_flags"] == 2, byid["s_wait"]            # resolved ones don't count
    assert byid["auggie:sess1"]["open_flags"] == 1, byid["auggie:sess1"]  # namespaced id matches too
    assert byid["s_done"]["open_flags"] == 0, byid["s_done"]            # unflagged -> 0, never missing
    os.unlink(config.FLAGS_FILE)
    config.FLAGS_FILE = _flag_snap
    assert all_sessions()[0].get("open_flags") == 0, "no flags file -> every session still reports 0"
    _AUGGIE_LIST_CACHE.clear()

    # _git_branch reads a normal repo and a worktree (Auggie's git branch source)
    gdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(gdir, ".git"))
    with open(os.path.join(gdir, ".git", "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/feat/x\n")
    assert _git_branch(gdir) == "feat/x", _git_branch(gdir)
    wt = tempfile.mkdtemp()
    real = os.path.join(gdir, ".git", "worktrees", "wt")
    os.makedirs(real)
    with open(os.path.join(real, "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/wt-branch\n")
    with open(os.path.join(wt, ".git"), "w") as fh:
        fh.write("gitdir: " + real + "\n")
    assert _git_branch(wt) == "wt-branch", _git_branch(wt)

    # provider registry routes ids to the owning adapter
    assert parse_any("auggie:sess1")["meta"]["source"] == "auggie", "auggie prefix must route to Auggie"
    assert parse_any("auggie:missing") is None
    assert parse_any("no-such-claude-session-id") is None, "bare id must route to the Claude provider"

    # search reaches Auggie too (it was Claude-only): match the transcript + title
    byq = search_auggie("list the dir")            # in the user's request_message
    hit = [r for r in byq if r["id"] == "auggie:sess1"]
    assert hit and hit[0]["inQuery"] is True, ("auggie search must hit the transcript", byq)
    assert hit[0]["project"] == "dw-stack", hit[0]["project"]   # search project = real IDE cwd too
    byt = search_auggie("home dir")                # both words in customTitle "List Home Dir"
    assert any(r["id"] == "auggie:sess1" and r["titleMatch"] for r in byt), byt
    assert search_auggie("zzznotfoundzzz") == []

    # task store (TaskCreate/TaskUpdate) — replaced in-transcript TodoWrite
    config.TASKS_DIR = tempfile.mkdtemp()
    tdir = os.path.join(config.TASKS_DIR, "sess-x")
    os.makedirs(tdir)
    open(os.path.join(tdir, ".lock"), "w").close()  # must be skipped
    json.dump({"id": "2", "subject": "Second", "status": "in_progress", "description": "do it"},
              open(os.path.join(tdir, "2.json"), "w"))
    json.dump({"id": "1", "subject": "First", "status": "completed"},
              open(os.path.join(tdir, "1.json"), "w"))
    tl = load_tasks("sess-x")
    assert [t["content"] for t in tl] == ["First", "Second"], tl  # numeric-id order
    assert tl[0]["status"] == "completed" and tl[1]["status"] == "in_progress", tl
    assert tl[1]["desc"] == "do it", tl
    assert load_tasks("missing") == []

    # flags persistence round-trip
    config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
    assert load_flags() == []  # missing file -> empty
    save_flags([{"id": 1, "session": "s", "note": "gap here", "resolved": False}])
    fl = load_flags()
    assert fl[0]["note"] == "gap here" and fl[0]["resolved"] is False
    fl[0]["resolved"] = True
    save_flags(fl)
    assert load_flags()[0]["resolved"] is True
    os.unlink(config.FLAGS_FILE)

    # user title override round-trip
    config.TITLES_FILE = tempfile.mktemp(suffix=".json")
    assert load_titles() == {}
    _save_json(config.TITLES_FILE, {"sess-1": "My Custom Name"})
    assert load_titles()["sess-1"] == "My Custom Name"
    os.unlink(config.TITLES_FILE)

    # notes stack round-trip
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
    assert load_notes() == {}                                         # missing file -> empty dict
    save_notes({"sess-a": [{"text": "plan step 1", "pushed": False},
                           {"text": "plan step 2", "pushed": False}]})
    ns = load_notes()
    assert [n["text"] for n in ns["sess-a"]] == ["plan step 1", "plan step 2"], ns
    ns["sess-a"].pop(0)                                               # remove first note
    save_notes(ns)
    assert [n["text"] for n in load_notes()["sess-a"]] == ["plan step 2"]
    # bare strings are the pre-push on-disk format — they must upgrade, not crash
    _save_json(config.NOTES_FILE, {"sess-b": ["written by an older build"]})
    assert load_notes()["sess-b"] == [{"text": "written by an older build", "pushed": False}]
    os.unlink(config.NOTES_FILE)

    # parse_session includes notes key
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"type": "user", "cwd": "/x", "message": {"role": "user", "content": "go"}}) + "\n")
        note_sid = os.path.basename(f.name)[:-6]
        note_path = f.name
    save_notes({note_sid: [{"text": "remember this", "pushed": True}]})
    dn = parse_session(note_path)
    os.unlink(note_path)
    os.unlink(config.NOTES_FILE)
    assert [n["text"] for n in dn["notes"]] == ["remember this"], dn.get("notes")
    assert dn["notes"][0]["pushed"] is True, "queued state must reach the client"
    # `push_when` spans BOTH providers — the client renders the server's answer, never guesses it.
    # The fixture jsonl was written just now, so Claude's session is live -> delivered this turn.
    assert dn["push_when"] == "turn", dn.get("push_when")
    assert pa["push_when"] == "none", "auggie: no hook at all -> push queues but can't deliver"
    # …and the same helper says "wake" once that session goes quiet, which is what stops the UI
    # promising "this turn" to a session with no turn in flight.
    assert push_when(True, 0, LIVE_WINDOW) == "wake", "idle claude session -> lands on wake"
    assert push_when(True, 1, LIVE_WINDOW) == "turn", "just inside the live window -> this turn"
    assert push_when(False, LIVE_WINDOW, LIVE_WINDOW) == "none", "no drain beats liveness"
    print("selfcheck ok")
