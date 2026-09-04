"""Self-check suite for ai-tracker — the former in-file _selfcheck, as stdlib unittest.

Run: python -m unittest discover -s tests   (or: make check)
"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from aitracker import config, term_vt
from aitracker.config import LIVE_WINDOW
from aitracker.util import _short_title, _window, _git_branch, push_when
from aitracker.store import load_flags, save_flags, load_titles, load_tasks, load_notes, save_notes, _save_json
from aitracker.registry import parse_any, all_sessions
from aitracker.providers.claude import (
    parse_session, parse_agents, parse_shells, _match_content, _active_mtime,
    file_diffs, command_output, shell_output, agent_detail, _redirect_log,
    list_sessions, child_agent_sessions, _agent_group, _pick_parent, _mtime_and_bg, _tail_fields,
    _is_bg_agent, _tail_scan)
from aitracker.providers.auggie import (
    list_auggie, parse_auggie, search_auggie, _AUGGIE_LIST_CACHE, _auggie_state, _auggie_fail_cmd)
from aitracker.providers.augment_ext import AugmentVscodeProvider


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
    # the todo summary rides the session-LIST shape too (todo_total/todo_done/todo_current) — a
    # compact progress tick for the sidebar, off root1/s1(completed)/s2(in_progress) above, without
    # a full detail parse. (Claude's half of this is asserted below, once the task store is set up.)
    assert (al[0]["todo_total"], al[0]["todo_done"], al[0]["todo_current"], al[0]["todo_current_index"]) == \
        (2, 1, "step two", 1), al[0]  # s2 is in_progress at index 1, not 0 -- pins the index, not just the label
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

    # pinned/open_flags/note_count must ALSO reach the DETAIL dict (registry.parse_any), not just
    # the list (all_sessions above) -- same store.py helpers, same shared seam, one implementation
    # covering every provider (the detail header's pinned pill / 🚩 count silently hid without this).
    _pins_snap, _notes_snap, _flags_snap2 = config.PINS_FILE, config.NOTES_FILE, config.FLAGS_FILE
    config.PINS_FILE = tempfile.mktemp(suffix=".json")
    config.NOTES_FILE = tempfile.mktemp(suffix=".json")
    config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
    _save_json(config.PINS_FILE, ["s_wait", "auggie:sess1"])
    save_notes({"s_wait": [{"text": "a note", "pushed": False}]})
    save_flags([{"id": 1, "session": "s_wait", "note": "open one", "resolved": False},
                {"id": 2, "session": "auggie:sess1", "note": "auggie gap", "resolved": False},
                {"id": 3, "session": "auggie:sess1", "note": "old", "resolved": True}])
    dw = parse_any("s_wait")
    assert (dw["pinned"], dw["open_flags"], dw["note_count"]) == (True, 1, 1), dw
    da = parse_any("auggie:sess1")
    assert (da["pinned"], da["open_flags"], da["note_count"]) == (True, 1, 0), da
    os.unlink(config.PINS_FILE); os.unlink(config.NOTES_FILE); os.unlink(config.FLAGS_FILE)
    config.PINS_FILE, config.NOTES_FILE, config.FLAGS_FILE = _pins_snap, _notes_snap, _flags_snap2
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
    # ...and it rides the session-LIST shape too (todo_total/todo_done/todo_current), read via the
    # SAME cheap load_tasks() call above — not a full transcript re-parse — for a sidebar progress
    # tick. (Auggie's half of this capability is asserted above, off root1/s1/s2.)
    d5 = os.path.join(pdir, "-x-sess-x"); os.makedirs(d5)
    _mk(d5, "sess-x.jsonl", "/x", "cli", "2026-06-01T09:00:00Z", "do the thing")
    lst = {s["id"]: s for s in list_sessions()}
    assert (lst["sess-x"]["todo_total"], lst["sess-x"]["todo_done"], lst["sess-x"]["todo_current"], lst["sess-x"]["todo_current_index"]) == \
        (2, 1, "Second", 1), lst["sess-x"]  # Second is in_progress at index 1, not 0

    # time-proportional progress-spine segments: started_at/ended_at per todo (epoch seconds),
    # reconstructed from TaskUpdate tool calls already being walked in parse_session's one
    # transcript pass — no extra file I/O. Joined onto load_tasks()'s todos above (sess-x's
    # "1.json"/"2.json") by taskId <-> the task-store file's own stem, confirmed against a real
    # ~/.claude/tasks/<sid>/<n>.json + its owning transcript on this machine.
    with open(os.path.join(d5, "sess-x.jsonl"), "a") as fh:
        for r in [
            {"type": "assistant", "timestamp": "2026-06-01T09:10:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "1", "status": "in_progress"}}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:20:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "1", "status": "completed"}}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:25:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "2", "status": "in_progress"}}]}},
        ]:
            fh.write(json.dumps(r) + "\n")
    dtb = parse_session(os.path.join(d5, "sess-x.jsonl"))
    by_id = {t["id"]: t for t in dtb["todos"]}
    assert by_id["1"]["status"] == "completed", by_id["1"]
    assert by_id["1"]["started_at"] == _ts_epoch("2026-06-01T09:10:00.000Z"), by_id["1"]
    assert by_id["1"]["ended_at"] == _ts_epoch("2026-06-01T09:20:00.000Z"), by_id["1"]
    assert by_id["2"]["status"] == "in_progress", by_id["2"]
    assert by_id["2"]["started_at"] == _ts_epoch("2026-06-01T09:25:00.000Z"), by_id["2"]
    assert by_id["2"]["ended_at"] is None, "still in_progress -> no fabricated ended_at"
    # Auggie/Augment-ext have no reliable join key for this (their in-session task ids don't
    # match the task-storage file's uuid — see auggie.py's _auggie_resolve) -- they emit the
    # SAME two keys, honestly null, never a guess. (`pa` == parse_auggie("sess1") from above.)
    assert all(t["started_at"] is None and t["ended_at"] is None for t in pa["todos"]), pa["todos"]

    # task store PRUNED (Claude Code deletes ~/.claude/tasks/<sid>/*.json after ~2 days): the
    # transcript's own TaskCreate/TaskUpdate history must be replayed instead of coming back
    # empty. sess-recon gets no directory at all under config.TASKS_DIR (load_tasks -> []),
    # so parse_session has nothing but the transcript to work with.
    d6 = os.path.join(pdir, "-x-sess-recon"); os.makedirs(d6)
    _mk(d6, "sess-recon.jsonl", "/x", "cli", "2026-06-01T09:00:00Z", "do three things")
    with open(os.path.join(d6, "sess-recon.jsonl"), "a") as fh:
        for r in [
            {"type": "assistant", "timestamp": "2026-06-01T09:01:00.000Z", "message": {"content": [
                {"type": "tool_use", "id": "tc1", "name": "TaskCreate",
                 "input": {"subject": "First reconstructed", "description": "do it"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tc1",
                 "content": "Task #1 created successfully: First reconstructed"}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:02:00.000Z", "message": {"content": [
                {"type": "tool_use", "id": "tc2", "name": "TaskCreate",
                 "input": {"subject": "Second reconstructed"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tc2",
                 "content": "Task #2 created successfully: Second reconstructed"}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:03:00.000Z", "message": {"content": [
                {"type": "tool_use", "id": "tc3", "name": "TaskCreate",
                 "input": {"subject": "Third reconstructed"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tc3",
                 "content": "Task #3 created successfully: Third reconstructed"}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:10:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "1", "status": "in_progress"}}]}},
            {"type": "assistant", "timestamp": "2026-06-01T09:20:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "1", "status": "completed"}}]}},
            # task 2 goes in_progress and stays there (never completed) -- lands at index 1, not 0
            {"type": "assistant", "timestamp": "2026-06-01T09:25:00.000Z", "message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate", "input": {"taskId": "2", "status": "in_progress"}}]}},
            # task 3 never updated at all -- stays "pending"
        ]:
            fh.write(json.dumps(r) + "\n")
    assert load_tasks("sess-recon") == [], "no task-store dir at all -- the pruned-history case"
    drec = parse_session(os.path.join(d6, "sess-recon.jsonl"))
    assert [t["content"] for t in drec["todos"]] == \
        ["First reconstructed", "Second reconstructed", "Third reconstructed"], drec["todos"]
    assert [t["status"] for t in drec["todos"]] == ["completed", "in_progress", "pending"], drec["todos"]
    assert drec["counts"]["todos"] == 3 and drec["counts"]["done"] == 1, drec["counts"]
    by_rid = {t["id"]: t for t in drec["todos"]}
    assert by_rid["1"]["desc"] == "do it", by_rid["1"]
    assert by_rid["1"]["started_at"] == _ts_epoch("2026-06-01T09:10:00.000Z"), by_rid["1"]
    assert by_rid["1"]["ended_at"] == _ts_epoch("2026-06-01T09:20:00.000Z"), by_rid["1"]
    assert by_rid["2"]["started_at"] == _ts_epoch("2026-06-01T09:25:00.000Z"), by_rid["2"]
    assert by_rid["2"]["ended_at"] is None, "still in_progress -> no fabricated ended_at"
    assert by_rid["3"]["started_at"] is None and by_rid["3"]["ended_at"] is None, "never touched"
    # ...but the session-LIST surface (/api/list) does NOT recover this: it reads load_tasks()
    # only, never a transcript, on purpose (950 sessions polled every ~5s -- a per-session
    # transcript read there would be the slow-dashboard regression, not a fix).
    lst6 = {s["id"]: s for s in list_sessions()}
    assert (lst6["sess-recon"]["todo_total"], lst6["sess-recon"]["todo_done"]) == (0, 0), \
        lst6["sess-recon"]  # deliberately NOT reconstructed -- see the comment above

    # Augment-ext (VSCode/Cursor extension) rides the SAME todo_total/todo_done/todo_current
    # session-list capability as Claude/Auggie above, off its own task-storage subTasks tree --
    # and, like Auggie, has no reliable join key for started_at/ended_at, so both come back
    # honestly None rather than a guess (see augment_ext.py's _resolve_subtasks).
    from aitracker.providers.augment_ext import AugmentVscodeProvider
    config.VSCODE_WS_ROOT = tempfile.mkdtemp()
    ext_ws = os.path.join(config.VSCODE_WS_ROOT, "wshash-ext")
    ext_tasks = os.path.join(ext_ws, "Augment.vscode-augment", "augment-user-assets", "task-storage", "tasks")
    os.makedirs(ext_tasks)
    with open(os.path.join(ext_ws, "workspace.json"), "w") as fh:
        json.dump({"folder": "file:///x/ext-proj"}, fh)
    def _etask(u, **kw):
        with open(os.path.join(ext_tasks, u + ".json"), "w") as fh:
            json.dump({"uuid": u, **kw}, fh)
    _etask("root", name="Current Task List", subTasks=["a", "b"])
    _etask("a", name="add helper", state="COMPLETE")
    _etask("b", name="wire tests", state="IN_PROGRESS")
    ep = AugmentVscodeProvider()
    erows = {r["id"]: r for r in ep.list()}
    eroot = erows["augment-vscode:wshash-ext:root"]
    assert (eroot["todo_total"], eroot["todo_done"], eroot["todo_current"], eroot["todo_current_index"]) == \
        (2, 1, "wire tests", 1), eroot  # "wire tests" (b) is in_progress at index 1, not 0
    ed = ep.parse("augment-vscode:wshash-ext:root")
    assert ed["todos"] and all(t["started_at"] is None and t["ended_at"] is None for t in ed["todos"]), ed["todos"]

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

    # Auggie: approximate per-todo timings recovered by NAME, not id -- add_tasks/update_tasks
    # key a task by a short per-call id that does NOT match the task-storage file's uuid (see
    # _auggie_resolve's docstring), so a todo's timing is recovered by matching its NAME back to
    # that chat-side id space via every add_tasks/update_tasks tool_result_node's echoed
    # "UUID:<id> NAME:<name> DESCRIPTION:…" text. A name pinning down exactly one chat-side id
    # gets real timings from that id's update_tasks transitions; a name that collides across TWO
    # different chat-side ids ("Dup Task" below, from two unrelated tasks that happen to share a
    # title) is ambiguous and MUST come back null rather than guessing either one's timing.
    _wtask("root2", name="Current Task List", description="Root task for conversation Y",
           subTasks=["tu1", "tdup"])
    _wtask("tu1", name="Unique Task", state="COMPLETE", subTasks=[])
    _wtask("tdup", name="Dup Task", state="COMPLETE", subTasks=[])

    def _utcall(cid, task_id, state):
        return {"tool_use": {"tool_name": "update_tasks", "tool_use_id": cid,
                             "input_json": json.dumps({"tasks": [{"task_id": task_id, "state": state}]})}}

    def _utresult(cid, task_id, name, marker):
        return {"tool_result_node": {"tool_use_id": cid,
                "content": ("Task list updated successfully. Created: 0, Updated: 1, Deleted: 0.\n\n"
                            "# Task Changes\n\n## Updated Tasks\n\n%s UUID:%s NAME:%s DESCRIPTION:desc"
                            % (marker, task_id, name))}}
    T1, T2, T3, T4 = ("2026-07-01T10:00:00.000Z", "2026-07-01T10:05:00.000Z",
                      "2026-07-01T10:10:00.000Z", "2026-07-01T10:15:00.000Z")
    chat2 = [
        {"finishedAt": T1, "exchange": {"response_nodes": [_utcall("ut1", "u1chat", "IN_PROGRESS")]}},
        {"finishedAt": T1, "exchange": {"request_nodes": [_utresult("ut1", "u1chat", "Unique Task", "[/]")]}},
        {"finishedAt": T2, "exchange": {"response_nodes": [_utcall("ut2", "u1chat", "COMPLETE")]}},
        {"finishedAt": T2, "exchange": {"request_nodes": [_utresult("ut2", "u1chat", "Unique Task", "[x]")]}},
        {"finishedAt": T3, "exchange": {"response_nodes": [_utcall("ut3", "dupA", "COMPLETE")]}},
        {"finishedAt": T3, "exchange": {"request_nodes": [_utresult("ut3", "dupA", "Dup Task", "[x]")]}},
        {"finishedAt": T4, "exchange": {"response_nodes": [_utcall("ut4", "dupB", "COMPLETE")]}},
        {"finishedAt": T4, "exchange": {"request_nodes": [_utresult("ut4", "dupB", "Dup Task", "[x]")]}},
    ]
    with open(os.path.join(config.AUGGIE_SESSIONS, "sess2.json"), "w") as fh:
        json.dump({"sessionId": "sess2", "modified": "2026-07-01T10:20:00Z",
                   "customTitle": "Timings test", "rootTaskUuid": "root2",
                   "chatHistory": chat2}, fh)
    pa2 = parse_auggie("sess2")
    assert pa2["todo_times_approximate"] is True, "Auggie's name-matched timings must be flagged approximate"
    by_content = {t["content"]: t for t in pa2["todos"]}
    assert by_content["Unique Task"]["started_at"] == _ts_epoch(T1), by_content["Unique Task"]
    assert by_content["Unique Task"]["ended_at"] == _ts_epoch(T2), by_content["Unique Task"]
    assert by_content["Dup Task"]["started_at"] is None and by_content["Dup Task"]["ended_at"] is None, \
        "a name colliding across two different chat-side ids must stay null, never a guess: %r" % by_content["Dup Task"]

    # PR data on the session-LIST dict (control-room board tile "PR number if any"): only a
    # `gh pr create` the session itself ran counts -- a PR merely mentioned in narration must
    # not light up a tile. Cached in _META_CACHE alongside the rest of the session's meta and
    # resolved via claude.py's _fill_pr (both fixtures below are ended AND freshly-written, so
    # their mtime is "now" -- inside LIVE_WINDOW, the only sessions a Landed tile could ever be).
    dpr = os.path.join(pdir, "-repo-x-pr"); os.makedirs(dpr)
    def _mkpr(fn, rows):
        p = os.path.join(dpr, fn + ".jsonl")
        with open(p, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return p
    def _prhead(cwd):
        return {"cwd": cwd, "entrypoint": "cli", "timestamp": "2026-08-01T09:00:00Z",
                "type": "user", "message": {"role": "user", "content": "ship it"}}
    PR_CREATE_CALL = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "c1", "name": "Bash", "input": {"command": "gh pr create --fill"}}]}}
    PR_CREATE_RESULT = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1",
         "content": "https://github.com/acme/widget/pull/101 created"}]}}
    PR_DONE = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Opened the PR, all done."}]}}
    _mkpr("sess_pr_created", [_prhead("/repo/x/pr"), PR_CREATE_CALL, PR_CREATE_RESULT, PR_DONE])
    # a PR only NARRATED about (never created) must not surface -- the list-path scan never
    # calls collect_prs on plain assistant text at all, matching parse_session's own
    # created=False default for narration (see collect_prs's narr-only calls at claude.py:900).
    PR_MENTION = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "see https://github.com/acme/other/pull/55 for context"}]}}
    _mkpr("sess_pr_mentioned", [_prhead("/repo/x/pr2"), PR_MENTION, PR_DONE])
    ls3 = {s["id"]: s for s in list_sessions()}
    assert ls3["sess_pr_created"]["pr_num"] == "101", ls3["sess_pr_created"]
    assert ls3["sess_pr_created"]["pr_url"] == "https://github.com/acme/widget/pull/101", ls3["sess_pr_created"]
    assert not ls3["sess_pr_mentioned"]["pr_num"] and not ls3["sess_pr_mentioned"]["pr_url"], \
        "a PR only narrated about, never created, must not surface on the list dict: %r" % ls3["sess_pr_mentioned"]

    # config.json override precedence for the browser-editable runtime settings (Config
    # dialog -> POST /api/config -> server.py, which writes config.json; config.py itself
    # never touches the file, see its module comment -- these resolve functions are pure,
    # taking the already-loaded overrides dict as an argument). MAX_TERMS has all three
    # layers (an env var AND a built-in default), so one key pins down the whole chain:
    # config.json > env var > built-in default.
    os.environ["TRACKER_MAX_TERMS"] = "20"
    try:
        assert config.resolve_max_terms({}) == 20, "env var must beat the built-in default"
        assert config.resolve_max_terms({"MAX_TERMS": 30}) == 30, "config.json override must beat the env var"
    finally:
        del os.environ["TRACKER_MAX_TERMS"]
    assert config.resolve_max_terms({}) == 12, "built-in default once neither override nor env is set"
    # The allowlist: POST /api/config's real gate is `key not in config.EDITABLE`
    # (server.py) -- a bogus key must never validate, and TRACKER_AUTH must never be a
    # member on purpose (writing a password from a browser into a plaintext file is a
    # security regression, not a convenience -- see config.py's AUTH comment).
    assert "MAX_TERMS" in config.EDITABLE
    assert "TRACKER_AUTH" not in config.EDITABLE, "TRACKER_AUTH must never be browser-writable"
    assert "NOT_A_REAL_KEY" not in config.EDITABLE, "a non-allowlisted key must never validate"

    # session-LIST `now_line` (a short "what's it doing right now" board-tile phrase) and
    # `model` (its current model id) -- both ride the SAME bounded tail read _tail_scan
    # already does for waiting/ended (providers/claude.py), cached in the same mtime-keyed
    # _META_CACHE entry as pr_num/pr_url/etc, no second read or cache. `now_line` is
    # LIVE-gated (idle/ended sessions get "" for free); `model` is NOT -- a session still
    # reports its last known model whether live or idle.
    NOW_TXT = {"type": "assistant", "message": {"model": "claude-opus-9-test", "content": [
        {"type": "text", "text": "Working through the retry-backoff edge cases in the client now"}]}}
    NOW_TOOL = {"type": "assistant", "message": {"model": "claude-opus-9-test", "content": [
        {"type": "tool_use", "id": "nt1", "name": "Bash", "input": {"command": "pytest -q"}}]}}
    p_now_live = _mklines("s_now_live", [UMSG, NOW_TXT, NOW_TOOL])
    p_now_idle = _mklines("s_now_idle", [UMSG, NOW_TXT, NOW_TOOL])
    os.utime(p_now_live, (time.time(), time.time()))
    os.utime(p_now_idle, (time.time() - LIVE_WINDOW - 100, time.time() - LIVE_WINDOW - 100))
    ls_now = {s["id"]: s for s in list_sessions()}
    assert ls_now["s_now_live"]["now_line"].startswith("Working through the retry-backoff"), \
        "live session, last block a tool_use (not ended) -> narration fallback surfaces: %r" % ls_now["s_now_live"]
    assert ls_now["s_now_live"]["model"] == "claude-opus-9-test", ls_now["s_now_live"]
    assert ls_now["s_now_idle"]["now_line"] == "", \
        "idle session must get \"\" even with the exact same narration sitting in its tail"
    assert ls_now["s_now_idle"]["model"] == "claude-opus-9-test", \
        "model is NOT liveness-gated -- an idle session still reports its last known model: %r" % ls_now["s_now_idle"]

    # same two fields on Auggie's session-LIST dict -- one shared shape, not a second mechanism.
    with open(os.path.join(config.AUGGIE_SESSIONS, "sess_now.json"), "w") as fh:
        json.dump({"sessionId": "sess_now", "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "chatHistory": [
                       {"finishedAt": "2026-06-27T05:47:50Z",
                        "exchange": {"request_message": "start", "response_text": "Refactoring the retry queue now",
                                     "model_id": "claude-sonnet-9-test"}},
                       # a later, still-pending exchange with no model_id yet -- must not blank out
                       # the last KNOWN model (see _auggie_current_model's backward scan)
                       {"finishedAt": "2026-06-27T05:48:00Z", "exchange": {"request_message": "continue"}},
                   ]}, fh)
    _AUGGIE_LIST_CACHE.clear()
    al_now = {s["id"]: s for s in list_auggie()}
    assert al_now["auggie:sess_now"]["now_line"] == "Refactoring the retry queue now", al_now["auggie:sess_now"]
    assert al_now["auggie:sess_now"]["model"] == "claude-sonnet-9-test", al_now["auggie:sess_now"]

    # Augment-ext (VSCode/Cursor extension): no chat transcript at all -> `model` is honestly
    # "" always; `now_line` still works off the todo tree alone (see augment_ext.py's _list).
    ext_ws2 = os.path.join(config.VSCODE_WS_ROOT, "wshash-now")
    ext_tasks2 = os.path.join(ext_ws2, "Augment.vscode-augment", "augment-user-assets", "task-storage", "tasks")
    os.makedirs(ext_tasks2)
    with open(os.path.join(ext_ws2, "workspace.json"), "w") as fh:
        json.dump({"folder": "file:///x/now-proj"}, fh)
    with open(os.path.join(ext_tasks2, "root.json"), "w") as fh:
        json.dump({"uuid": "root", "name": "Current Task List", "subTasks": ["t1"]}, fh)
    with open(os.path.join(ext_tasks2, "t1.json"), "w") as fh:
        json.dump({"uuid": "t1", "name": "wire up retries", "state": "IN_PROGRESS"}, fh)
    now_ep = AugmentVscodeProvider()
    now_erow = next(r for r in now_ep.list() if r["id"] == "augment-vscode:wshash-now:root")
    assert now_erow["now_line"] == "▶ wire up retries", now_erow
    assert now_erow["model"] == "", "augment-ext has no chat transcript -- model must be \"\", never a guess"

    # ---- fail_cmd: board "failing" tile signal -- session-LIST dict only, every provider ----
    # Claude: providers/claude.py's _tail_scan tracks a Bash tool_use's id -> command text, then
    # a later tool_result's is_error flag decides pass/fail; "latest wins", like model/last_text.
    FAIL_BASH = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "fb1", "name": "Bash", "input": {"command": "pytest -q --maxfail=1"}}]}}
    def _fail_result(is_error):
        return {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "fb1", "is_error": is_error, "content": "x"}]}}
    fc_dir = tempfile.mkdtemp()
    def _fc_write(fn, rows):
        p = os.path.join(fc_dir, fn)
        with open(p, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return p
    p_failed = _fc_write("failed.jsonl", [FAIL_BASH, _fail_result(True)])
    p_passed = _fc_write("passed.jsonl", [FAIL_BASH, _fail_result(False)])
    p_norun = _fc_write("norun.jsonl", [{"type": "user", "message": {"role": "user", "content": "hi"}}])
    assert _tail_scan(p_failed)["fail_cmd"] == "pytest -q --maxfail=1", _tail_scan(p_failed)
    assert _tail_scan(p_passed)["fail_cmd"] is None, "a later PASS clears an earlier FAIL"
    assert _tail_scan(p_norun)["fail_cmd"] is None, "no Bash tool_use at all -> honestly None, not a crash"
    # EDGE CASE: a truncated/malformed trailing line must not blow up the tail scan, and a
    # valid Bash failure seen before the garbage still counts.
    p_trunc = _fc_write("trunc.jsonl", [])
    with open(p_trunc, "w") as fh:
        fh.write(json.dumps(FAIL_BASH) + "\n")
        fh.write(json.dumps(_fail_result(True)) + "\n")
        fh.write('{"type": "user", "message": {"content": [{"type": "tool_resu\n')   # cut mid-line
    assert _tail_scan(p_trunc)["fail_cmd"] == "pytest -q --maxfail=1", _tail_scan(p_trunc)

    # wired onto the real session-LIST dict (list_sessions()), not just _tail_scan in isolation
    dfc = os.path.join(pdir, "-x-failcmd"); os.makedirs(dfc)
    _mk(dfc, "s_fail.jsonl", "/x", "cli", "2026-06-02T09:00:00Z", "run the suite")
    with open(os.path.join(dfc, "s_fail.jsonl"), "a") as fh:
        fh.write(json.dumps(FAIL_BASH) + "\n")
        fh.write(json.dumps(_fail_result(True)) + "\n")
    _mk(dfc, "s_pass.jsonl", "/x", "cli", "2026-06-02T09:00:00Z", "run the suite")
    with open(os.path.join(dfc, "s_pass.jsonl"), "a") as fh:
        fh.write(json.dumps(FAIL_BASH) + "\n")
        fh.write(json.dumps(_fail_result(False)) + "\n")
    # EDGE CASE: no "cwd" field on any line -- must not crash, must fall back to "".
    with open(os.path.join(dfc, "s_nocwd.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "go, no cwd anywhere"}}) + "\n")
    ls_fc = {s["id"]: s for s in list_sessions()}
    assert ls_fc["s_fail"]["fail_cmd"] == "pytest -q --maxfail=1", ls_fc["s_fail"]
    assert ls_fc["s_fail"]["todo_total"] == 0, "the new field coexists fine with a session that has no todos"
    assert "fail_cmd" in ls_fc["s_pass"] and ls_fc["s_pass"]["fail_cmd"] is None, ls_fc["s_pass"]
    assert ls_fc["s_nocwd"]["cwd"] == "", "missing cwd field -> empty string, not a crash"
    assert "fail_cmd" in ls_fc["s_nocwd"] and ls_fc["s_nocwd"]["fail_cmd"] is None, ls_fc["s_nocwd"]

    # Auggie: same signal off launch-process tool_use / tool_result_node pairs (zero extra I/O --
    # the chatHistory is already loaded), same "latest wins" rule.
    assert _auggie_fail_cmd(None) is None, "no chatHistory at all -> honestly None"
    assert _auggie_fail_cmd([]) is None
    err_chat = [
        {"exchange": {"response_nodes": [{"tool_use": {"tool_name": "launch-process", "tool_use_id": "lp1",
                                                         "input_json": json.dumps({"command": "npm test"})}}]}},
        {"exchange": {"request_nodes": [{"tool_result_node": {"tool_use_id": "lp1", "is_error": True}}]}},
    ]
    assert _auggie_fail_cmd(err_chat) == "npm test", _auggie_fail_cmd(err_chat)
    ok_chat = [
        {"exchange": {"response_nodes": [{"tool_use": {"tool_name": "launch-process", "tool_use_id": "lp2",
                                                         "input_json": json.dumps({"command": "npm test"})}}]}},
        {"exchange": {"request_nodes": [{"tool_result_node": {"tool_use_id": "lp2", "is_error": False}}]}},
    ]
    assert _auggie_fail_cmd(ok_chat) is None
    # EDGE CASE: a launch-process call with no matching result at all (still running) -> None.
    pending_chat = [
        {"exchange": {"response_nodes": [{"tool_use": {"tool_name": "launch-process", "tool_use_id": "lp3",
                                                         "input_json": json.dumps({"command": "npm test"})}}]}},
    ]
    assert _auggie_fail_cmd(pending_chat) is None
    # already wired onto sess1's real fixture above (c1 "git commit" ok, c2 "pytest -q" errored,
    # request_nodes processed in that order) -- the LATEST result (c2, failed) wins.
    assert al[0]["fail_cmd"] == "pytest -q", al[0]
    # EDGE CASE: an Auggie session lacking the field entirely (no "chatHistory" key at all in
    # the on-disk JSON, not merely an empty list) -- must not crash, must come back None.
    with open(os.path.join(config.AUGGIE_SESSIONS, "sess_nofield.json"), "w") as fh:
        json.dump({"sessionId": "sess_nofield", "modified": "2026-06-27T05:48:03Z"}, fh)
    _AUGGIE_LIST_CACHE.clear()
    al_nf = {s["id"]: s for s in list_auggie()}
    assert al_nf["auggie:sess_nofield"]["fail_cmd"] is None, al_nf["auggie:sess_nofield"]
    _AUGGIE_LIST_CACHE.clear()

    # Augment-ext (VSCode/Cursor extension): no command/tool-result stream at all -> honestly
    # None, always -- never a guess, never omitted (augment_ext.py's _list()).
    assert now_erow["fail_cmd"] is None and "fail_cmd" in now_erow, now_erow

    # registry.all_sessions() guarantees the key on EVERY session regardless of provider
    # (registry.py:89's setdefault) -- spot-check across every source populated above.
    by_all = {s["id"]: s for s in all_sessions()}
    for _sid in ("s_fail", "s_pass", "auggie:sess1", "augment-vscode:wshash-now:root"):
        assert "fail_cmd" in by_all[_sid], "%s missing fail_cmd on the list dict" % _sid
    assert by_all["s_fail"]["fail_cmd"] == "pytest -q --maxfail=1", by_all["s_fail"]

    # a provider that FORGETS to set fail_cmd at all must still get it defaulted to None by the
    # shared seam's setdefault -- never a KeyError reaching the client.
    class _NoFailCmdProvider:
        prefix = "nofc:"
        def available(self):
            return True
        def list(self):
            return [{"id": "nofc:x", "mtime": time.time()}]   # no "fail_cmd" key at all
    import aitracker.registry as _registry_mod
    _orig_providers = _registry_mod.PROVIDERS
    _registry_mod.PROVIDERS = _orig_providers + [_NoFailCmdProvider()]
    try:
        row = next(s for s in all_sessions() if s["id"] == "nofc:x")
        assert row["fail_cmd"] is None, "setdefault must backfill a missing fail_cmd as None: %r" % row
    finally:
        _registry_mod.PROVIDERS = _orig_providers

    # ---- flag_text: the flag badge's text -- list dict AND detail dict, both providers ----
    config.FLAGS_FILE = tempfile.mktemp(suffix=".json")
    save_flags([
        {"id": 1, "session": "s_wait", "note": "first note", "resolved": False},
        {"id": 2, "session": "s_wait", "note": "latest note wins", "resolved": False},
        {"id": 3, "session": "auggie:sess1", "note": "auggie flag text", "resolved": False},
        {"id": 4, "session": "s_done", "note": "resolved, must not count", "resolved": True},
    ])
    by_ft = {s["id"]: s for s in all_sessions()}
    assert by_ft["s_wait"]["flag_text"] == "latest note wins", by_ft["s_wait"]   # append-only -> last unresolved wins
    assert by_ft["auggie:sess1"]["flag_text"] == "auggie flag text", by_ft["auggie:sess1"]
    assert by_ft["s_done"]["flag_text"] is None, "no OPEN flag -> None, never omitted or stale"
    assert "flag_text" in by_ft["augment-vscode:wshash-now:root"], "key always present, even unflagged"
    assert by_ft["augment-vscode:wshash-now:root"]["flag_text"] is None

    dft_wait = parse_any("s_wait")
    assert dft_wait["flag_text"] == "latest note wins", dft_wait["flag_text"]
    dft_auggie = parse_any("auggie:sess1")
    assert dft_auggie["flag_text"] == "auggie flag text", dft_auggie["flag_text"]
    dft_done = parse_any("s_done")
    assert dft_done["flag_text"] is None, "detail dict: no open flag -> honestly None"
    os.unlink(config.FLAGS_FILE)

    # ---- term_attached (detail dict only) + pinned (detail dict, true AND false) ----
    _pins_snap3 = config.PINS_FILE
    config.PINS_FILE = tempfile.mktemp(suffix=".json")
    _save_json(config.PINS_FILE, [])   # nothing pinned yet
    assert parse_any("s_done")["term_attached"] is False, "no open terminal at all -> not attached"
    assert parse_any("auggie:sess1")["term_attached"] is False
    assert parse_any("s_done")["pinned"] is False, "not in pins.json -> False, never merely absent"

    _ptys_snapshot = dict(term_vt.PTYS)
    term_vt.PTYS.clear()
    try:
        pt = term_vt.Pty(tid="fake-term-1")
        pt.session = "s_done"
        pt.done = False
        term_vt.PTYS[pt.id] = pt
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            assert parse_any("s_done")["term_attached"] is True, \
                "an open pty for this session with claude in the foreground -> attached"
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=False):
            assert parse_any("s_done")["term_attached"] is False, \
                "an open pty exists but claude isn't the foreground process -> not attached"
        # a FINISHED pty (done=True) for this session must not count as attached
        pt.done = True
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            assert parse_any("s_done")["term_attached"] is False, "a done pty must not count as attached"
        # a live pty against a DIFFERENT session must not leak onto this one (both providers)
        pt2 = term_vt.Pty(tid="fake-term-2")
        pt2.session = "auggie:sess1"
        pt2.done = False
        term_vt.PTYS[pt2.id] = pt2
        with mock.patch("aitracker.term_vt._foreground_is_claude", return_value=True):
            assert parse_any("s_done")["term_attached"] is False, "another session's pty must not attach here"
            assert parse_any("auggie:sess1")["term_attached"] is True, "...but it does attach to ITS OWN session"
    finally:
        term_vt.PTYS.clear()
        term_vt.PTYS.update(_ptys_snapshot)

    _save_json(config.PINS_FILE, ["s_done", "auggie:sess1"])
    assert parse_any("s_done")["pinned"] is True, "pinned session -> detail dict must say so"
    assert parse_any("auggie:sess1")["pinned"] is True
    assert parse_any("s_wait")["pinned"] is False, "un-pinned session -> False, not merely absent"
    os.unlink(config.PINS_FILE)
    config.PINS_FILE = _pins_snap3

    # ---- brand mark ---------------------------------------------------------------
    # The logo is ONE shared #brandMark symbol (index.html) that both dashboards
    # <use>; its colours come from --brand-plate/--brand-dot + currentColor, set per
    # theme by each shell. Before this, the control-room rail drew a generic outlined
    # sparkle and the classic mark hardcoded the dark-theme palette (broken in light).
    import aitracker as _ait
    _WEB = os.path.join(os.path.dirname(_ait.__file__), "web")
    def _read(n):
        with open(os.path.join(_WEB, n), encoding="utf-8") as _fh:
            return _fh.read()
    _idx, _appcss = _read("index.html"), _read("app.css")
    _brdjs, _brdcss = _read("ext_cr_board.js"), _read("ext_cr_board.css")

    assert _idx.count("id=brandMark") == 1, "brand symbol must be defined exactly once -- shared seam, not forked"
    # fallbacks matter: a consumer that forgets the tokens must degrade to the
    # outline form, not an opaque black plate.
    for _tok in ("var(--brand-plate, transparent)", "var(--brand-dot, currentColor)", "currentColor"):
        assert _tok in _idx, "the brand symbol must take %s from the theme, not a literal" % _tok

    # ...scoped to the MARK itself: unrelated chrome (the agent/shell count badges) is
    # free to use a literal hex, but the logo must take every colour from a token.
    import re as _re
    _sprite = _idx.split("<svg class=brandsprite", 1)[1].split("</svg>", 1)[0]
    _logospan = _re.search(r"<span class=logo\b.*?</span>", _idx, _re.S).group(0)
    for _where, _frag in (("brand symbol", _sprite), ("classic logo span", _logospan)):
        for _hex in ("#f5b443", "#29d398", "#11161f"):
            assert _hex not in _frag, "%s must not hardcode the dark-theme hex %s" % (_where, _hex)

    # both shells render the same symbol ...
    assert 'use href="#brandMark"' in _idx, "classic sidebar logo must <use> the shared symbol"
    assert 'use href="#brandMark"' in _brdjs, "control-room rail must <use> the shared symbol"
    _railline = next(l for l in _brdjs.splitlines() if "class: 'cr-rail-brand'" in l)
    assert "icon('spark'" not in _railline, "the rail brand must be the product mark, not the generic spark glyph"

    # ... and each defines the tint tokens for its own theme scope
    for _name, _css in (("app.css", _appcss), ("ext_cr_board.css", _brdcss)):
        for _v in ("--brand-plate", "--brand-dot"):
            assert _v in _css, "%s must define %s so the mark tints in both themes" % (_name, _v)

    print("selfcheck ok")
