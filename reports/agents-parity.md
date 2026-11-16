# Agents parity — tracker counts vs Claude Code

Branch `worktree-tracker-agents-parity` (base personal/main f07f1e4). Opened 2026-11-16.

## Contract (verbatim)
> the actual agents in the session and the agents in the agents map or agents section never matches

| Clause | Status |
|---|---|
| Agent map / Agents section agree with the session's actual agents | not discharged |

## Diagnosis (sonnet, read-only; session 82ce95d1-1717-4154-9d1a-53798586893b, dw-vida-stack)
Observed: Claude Code footer "51 agents · 3 shells" with 3 agents running; tracker Agent map "133 agents · 0 running"; Evidence "Agents & shells 142".

- **A (bug)**: "0 running". `parse_agents` (aitracker/providers/claude.py ~1484-1495) and `_agent_file_pass` (~1269-1276) treat a trailing SubagentStop row as done. That row is the user's own hook, written at every turn end. Agent a544bd31 has 15 stop rows; its last text is "Waiting for the final c3 gate runs." and its shell bc3tkgaj3 is still alive. meta.finished=true on all 133, so it is useless as a signal. No sidecar mtime is within LIVE_WINDOW.
- **B (bug)**: background shells launched by subagents are invisible. `parse_shells`/`_shells_pass` (claude.py ~1605-1635) scan only the main transcript. All 3 live shells (bn4u12cbj, bsh4mgoq0, bc3tkgaj3) were launched in sidecars.
- **C (label)**: 142 = 133 agents_bg + 9 shells (ext_cr_detail.js ~2994). The Agent map counts agents only (ext_cr_dialogs.js ~2702-2770). "View in agent map" implies the same set.
- **D (definition)**: 133 = every Agent tool_use in the session (verified 1:1 with sidecars; no nested, duplicate or workflow agents). Claude Code's 51 is not derivable from disk. Best fit: its in-memory list since the compaction at 2026-11-15T08:55:07Z (48 spawned since then plus the 3 live ones). Not a tracker bug.
- Claude Code "running" source of truth: ~/.claude/jobs/<id8>/state.json `fan` (3 agent + 3 shell + 86 todo entries).

## Plan / review / reconciliation
(below, appended by each stage)

## Plan v1 (opus)

Base: worktree at f07f1e4. Line numbers are from that commit (`aitracker/providers/claude.py` unless stated).

### 0. Shapes I checked on disk (session 82ce95d1, read-only)

Every rule below depends on one of these. I opened each one; none is assumed.

| # | Shape | Where seen | What it means |
|---|---|---|---|
| S1 | Explicit bg Bash: `tool_use{name:"Bash", input.run_in_background:true}`, then a `type:"user"` row with `toolUseResult.backgroundTaskId:"bc3tkgaj3"` and block text `Command running in background with ID: bc3tkgaj3. Output is being written to: …/tasks/bc3tkgaj3.output.` | sidecar a544bd31, lines 1191/1194 | Existing `SHELL_RE` (claude.py:1697) matches this. |
| S2 | **Bash moved to the background on timeout.** The `tool_use` has NO `run_in_background`. The result has `toolUseResult:{backgroundTaskId:"bn4u12cbj", timedOutAfterMs:590000}` and text `Command did not complete within its 590s timeout and was moved to the background (ID: bn4u12cbj). Output is being written to: …/bn4u12cbj.output.` | sidecar a9ad361b, line 247; afd1ab11 (bsh4mgoq0) | `SHELL_RE` does **not** match this text. 82 of the session's 160 bg shells are this kind, including 2 of the 3 shells Claude Code shows as live. **Today the tracker cannot see them even in the main transcript.** |
| S3 | Monitor: `tool_use{name:"Monitor", input:{command, description, timeout_ms}}`. The result has `toolUseResult:{taskId:"bf4tirtxs", timeoutMs:1800000, persistent:false}` and text `Monitor started (task bf4tirtxs, expires in 30m …)`. | a544bd31, lines 986/989 | Expires on its own unless `persistent`. |
| S4 | Completion: a `<task-notification>` block with `<task-id>`, `<tool-use-id>`, **`<status>completed|failed</status>`**, `<summary>`. It appears in `user` (isMeta) rows, `attachment` rows and `api-request-blob` rows. | both files | Across all 2,950 local transcripts: 23,149 notification blocks carry a status. 927 have no status, and every one of those is a **Monitor event** (`<event>` + "Monitor event:" summary), not a completion. The 83 other status-less hits are code or test text quoted inside tool output. |
| S5 | **Cross-file closure.** 203 of 233 sidecar-launched task ids are closed by a notification in the **main** transcript, not their own sidecar (it lands in main once the agent's turn has ended). bc3tkgaj3 was open at diagnosis time; its completion has since landed in the main transcript. | ap_open simulation | The done-set must be the union across main and every sidecar. |
| S6 | TaskStop: `tool_use{name:"TaskStop", input:{task_id}}`. On success: `toolUseResult:{message:"Successfully stopped task: …", task_id, task_type:"local_agent"\|…}`. On failure: a block with `is_error:true` (`No such tool available: TaskStop`). | main 3576; afd1ab11 line 135/136 | A stop counts only when its result is not `is_error`. Stopping an **agent** id (task_type local_agent) also ends that agent's own shells and monitors. Example: bwsxslyjo in agent a8b61fc7 has no notification, and the agent was TaskStop'd from main. Fan agrees: it does not list it. Across all transcripts, `TaskStop{task_id}` is the only stop shape (229 uses). No KillShell or KillBash. |
| S7 | `api-request-blob` rows repeat earlier `tool_use`/`tool_result` blocks and carry **no timestamp**. 357 in main, 20 in a544bd31. | both | A launch dict keyed by tool_use id must be **first-wins** (`setdefault`). Today `_shells_pass` (claude.py:1724) overwrites, so a duplicate written later sets `ts=None`. |
| S8 | `~/.claude/sessions/<pid>.json`: `{pid, sessionId, kind:"bg"\|"interactive", procStart:"Fri Nov 13 11:19:12 2026"` (UTC, `ps lstart` format)`, …}`. 63290.json names 82ce95d1. The bg shells' processes are children of pid 63290. | live | This is the cheap "is the host alive, and since when" signal. It covers daemon jobs (kind bg) and TUI/desktop. |

### 1. Bug A: agent running/done

**Source of truth: `jobs/<id8>/state.json` `fan` is rejected; the transcript-derived rule is used for every session.** Evidence from the 12 job dirs with a non-empty fan:
- **Incomplete.** It lists 3 of 133 agents and 3 of 160 shells. It is Claude Code's in-memory roster, not the session's history.
- **Agent semantics don't fit.** All 3 fan agents for 82ce95d1 have `doneAt` set, yet the footer shows them running. "Running" there means "has an open shell", which the transcript rule reproduces directly.
- **Stale after the process dies.** Job 9383c8c3 is `state:"done"`, 68 h old, and still lists 7 shells with no `doneAt` and `inFlight.tasks:7`. Job 37184523 is `failed`, 314 h old, and still lists 2 agents with no `doneAt`.
- **No more accurate than the transcript.** Fan lists bn4u12cbj as open, but no process for it exists (`ps`). The transcript rule gives the same answer: the same 3 shells and the same 3 owning agents at diagnosis time, now 2 and 2 after bc3tkgaj3 completed.
- **Not cheaper in any useful way.** Its read is cached (`file_pass("claude.jobstate")`), but it covers daemon jobs only. Non-job sessions would still need the transcript rule, which means two rules for one capability.

**The rule.** An agent is *held* when it has at least one **open background task** that it launched in its own sidecar. A held agent gets `state:"running"`, `running:true`, `ended:null`, no matter how many trailing SubagentStop rows it has or whether `meta.finished` is set. A task T launched in file F (owner agent A, or "" for main) is **open** when:
- T is a Bash shell (S1/S2) and its id is **not** in `done_any`. `done_any` holds every `<task-id>` in any `<task-notification>` block in main or any sidecar. This keeps today's Bash semantics; old fixtures have no `<status>`.
- T is a Monitor (S3) and its id is not in `ended`, which holds ids from blocks that carry `<status>` (S4: events don't close). It must also not be past expiry: `launch_ts + timeoutMs/1000 < now` closes it, and `persistent:true` means no expiry.
- T's id is not in `stopped` (successful TaskStop in any file), **and** A is not in `stopped` (S6).
- **Staleness bound (host gate):** `host_start is not None` **and** `launch_epoch >= host_start - 1`. Here `host_start = _host_start(sid, path)`:
  - It is the **earliest `procStart`** among the live files in `config.LIVE_SESSIONS_DIR/*.json` whose `sessionId == sid` and whose `pid` passes `_pid_alive` (claude.py:562).
  - **`None`** means no live file names the session. Then nothing it launched is running: an orphan from a dead process.
  - **`0.0`** means "unknown, trust the transcript" (today's behaviour). It is returned when the dir does not exist, when `procStart` won't parse, or when no file names the session but `_active_mtime(path)` (claude.py:1232) is within `LIVE_WINDOW`. That last case is an unregistered host such as an SDK run.
  - A shell launched **before** the current host process started belongs to a previous, dead process. This is the crash-then-resume case and it is excluded.
  - There is no `ps` subprocess: `procStart` is parsed with `datetime.strptime(" ".join(s.split()), "%a %b %d %H:%M:%S %Y")` as UTC. A recycled pid reads as alive, the same residual `_live_workers` already accepts (claude.py:598).

### 2. Bug B: sidecar shells in `parse_shells`, at the existing seam, one implementation

The per-line logic of `_shells_pass` moves into one pure accumulator. Both per-file passes feed it from **the same single read** they already do. `tests/test_agent_cache.py::test_warm_call_opens_zero_files` asserts exactly one open per sidecar on a cold call, so a second read is not allowed.

### 3. Exact changes

**claude.py, near SHELL_RE/TASKDONE_RE (1697-1701):**
- Add `MOVED_RE = re.compile(r"moved to the background \(ID:\s*(\S+?)\)\.\s*Output is being written to:\s*(\S+\.output)")`. It has the same two groups as `SHELL_RE`. `SHELL_RE` itself is untouched because `_tail_scan` (claude.py:217) shares it.
- Add `def _bg_acc(): return {"launches": {}, "results": {}, "monitors": {}, "done": set(), "ended": set(), "stopped": set(), "_pend": {}}`.
- Add `def _bg_line(acc, line, o)`. It is pure (no clock, no config) and handles one raw line plus its parsed `o`, which may be `None`:
  1. If `"<task-notification>" in line`: for each chunk of `line.split("<task-notification>")[1:]`, cut at `"</task-notification>"`. Add `TASKDONE_RE.findall(chunk)` to `done`. If `"<status>" in chunk`, also add those ids to `ended`.
  2. If `o` is a dict with a list `message.content`, then for each block:
     - Bash `tool_use` with `run_in_background`: `launches.setdefault(id, {"cmd": cmd[:4000], "desc", "ts": o.get("timestamp")})`.
     - Any other Bash `tool_use`: `_pend[id] = ("bash", info)`.
     - `Monitor` `tool_use`: `_pend[id] = ("mon", {"desc", "ts"})`.
     - `TaskStop`: `_pend[id] = ("stop", input.task_id)`.
     - `tool_result` whose `tool_use_id` is in `launches` or `_pend`:
       - Bash: match `SHELL_RE.search(txt) or MOVED_RE.search(txt)` and fall back to `o["toolUseResult"]["backgroundTaskId"]` when it is a dict. When an id is found: `launches.setdefault(tuid, info)` and `results[tuid] = (sid, out or "")`.
       - mon: take `taskId`, `timeoutMs`, `persistent` from `toolUseResult` (dict), with fallback regex `r"Monitor started \(task (\S+?),"`. Record `monitors[taskId] = {"desc", "ts", "exp": None if persistent or not timeoutMs else _ts_epoch(ts) + timeoutMs/1000}`.
       - stop: if `not b.get("is_error")`, add `task_id` to `stopped`.
       - Then pop the entry from `_pend`.
- `_shells_pass(path)` (1704): becomes `acc = _bg_acc(); for line in fh: o = json.loads or None; _bg_line(acc, line, o); acc.pop("_pend"); return acc`. It is still cached by `file_pass("claude.shells", path, _shells_pass)`. The value changes from a 3-tuple to a dict; the in-memory cache is cleared by the restart the change needs anyway.
- `_agent_file_pass(af, mt)` (1343):
  - Add `bg = _bg_acc()`.
  - Restructure the parse at 1363-1367 to `try: o = json.loads(line) except ValueError: o = None`, then `_bg_line(bg, line, o)`, then `if o is None: continue`. Everything after that is unchanged. `_bg_line` must run **before** the SubagentStop `continue` (1373), because attachment rows carry notifications (S4).
  - After the loop, `bg.pop("_pend", None)`. Add `"bg": bg` to the returned entry (1459).
  - The cache key `(mtime_ns, size, sidecar stat)` (`_agent_entry`, 1487) is unchanged.
- New `def _bg_tasks(path, host_start=0.0)`:
  - `accs = [("", file_pass("claude.shells", path, _shells_pass))]` plus `(e["aid"], e["bg"])` for each `af in sorted(_agent_files(path))` via `_agent_entry(af)`. These are cache hits after `parse_agents` and need no extra open.
  - Union `done`/`ended`/`stopped` across all accs, take `now = time.time()`, apply the rule in §1, and return rows `{"kind": "shell"|"monitor", "id", "agent", "cmd", "desc", "ts", "out", "running"}`.
  - A shell's `id = shell_id or tuid[:10]`, as today. A launch with no shell id stays "running" unless gated, same as today.
  - Raises OSError when main is missing, as `file_pass` does.
- `parse_shells(path, host_start=0.0, tasks=None)` (1734):
  - `tasks = _bg_tasks(path, host_start) if tasks is None else tasks`, with `OSError -> []`.
  - Rows for `kind == "shell"` keep the **existing shape** (`id, cmd, desc, ts, running, last, out`) plus the additive `"agent": aid or ""`. `last` is read from `out` exactly as today (1746-1752). Same sort.
  - The default `host_start=0.0` keeps every direct caller and test unchanged.
- `shell_output(path, shell_id)` (1787): call `parse_shells(path, _host_start(os.path.basename(path)[:-6], path))` so a sidecar shell opens from the UI and its `running` agrees with the panel.
- New `def _host_start(sid, path)` next to `running_sessions` (731), as specified in §1. It never raises; any exception returns 0.0.
- `parse_agents(path, hb=None, cost=None, live=frozenset())` (1518). At 1584-1590:
  - `held = aid in live`
  - `running = (now - e["mt"]) < config.LIVE_WINDOW or held`
  - `if held: done, ended = False, None` comes before the existing `stop_after` / `finished` branches, which are unchanged.
  - The return stays a 5-tuple.
- `parse_session` (2139). Before the `parse_agents` call at 2184:
  - `hs = _host_start(sid, path)`
  - `try: bg_tasks = _bg_tasks(path, hs) except OSError: bg_tasks = []`
  - `live_aids = {t["agent"] for t in bg_tasks if t["running"] and t["agent"]}`
  - Pass `live=live_aids` to `parse_agents`.
  - At 2215: `shells = parse_shells(path, hs, bg_tasks)`.
  - `build_overview`'s running-agent lead (overview.py:57) then sees held agents, with no change in that file.

**C: `aitracker/web/ext_cr_detail.js:2991` (`renderAgentsPanel`).** Replace the single summed number with a label built from the same arrays, for example `133 agents · 160 shells` with `· N session(s)` added only when `agent_sessions` is non-empty. Keep `"—"` when everything is empty. Pluralise as `agentMapSubtitle` does (ext_cr_dialogs.js:2955). There is **no new server number**: these are array lengths the client already sums today, and each row's running/done comes from server-set `running`/`state`. The agent-map subtitle ("133 agents · N running") and the map button's ` · 133` (ext_cr_detail.js:2494) stay as they are. They now visibly match the "133 agents" half of the Evidence label.

**D: no change. Show nothing.** The 51 is Claude Code's in-memory roster and cannot be read from disk (diagnosis D). A tooltip explaining it would put a guess on screen. The self-describing C label already says what the tracker counts. State the definition in the PR body.

**Auggie: no equivalent, no change.** auggie.py:502/774 and augment_ext.py:276 emit `agents_bg: []`, `shells: []`. Auggie logs do have `launch-process` and `read-process`/`kill-process` (largest session: 425 / 1 / 1), but I found no completion record on disk to close a background process, so its liveness would be faked. The list fields stay honest zeros (auggie.py:374-375).

### 4. Tests (each one red before the fix; guards are proved by reverting the one line they guard)

All fixtures are copied from S1-S8. Base class `tests/test_agent_map.py::Base` (main `sess.jsonl` with sid "sess", sidecars under `sess/subagents/`). New class `TestBackgroundHold(Base)`:
- `setUp` patches `config.LIVE_SESSIONS_DIR` to a temp dir and writes `<os.getpid()>.json` = `{"pid": os.getpid(), "sessionId": "sess", "kind": "bg", "procStart": "Mon Jul 13 09:00:00 2026"}`.
- Launch timestamps are `2026-07-13T10:…Z` and sidecars are `age=1000` (stale).

| Test | Fixture | Assert | Red before because |
|---|---|---|---|
| `test_open_sidecar_shell_holds_agent_after_stop_row` | sidecar: S1 launch + result (`bsh1`), text "Waiting", `_stop()` | `parse_session(main)["agents_bg"][0]`: `state=="running"`, `running is True`, `ended is None` | today `stop_after` → done |
| `test_sidecar_shell_listed_with_owner` (B) | same | `parse_session(main)["shells"]` contains `{"id":"bsh1","agent":"<aid>","running":True}` | sidecars not scanned |
| `test_moved_to_background_shell_listed` | **main**: Bash tool_use without `run_in_background` + S2 result `bmv1` | `parse_shells(main)` has `bmv1` running | `SHELL_RE` misses S2 |
| `test_completion_in_main_closes_sidecar_shell` (guard) | hold fixture + main `user` isMeta row with an S4 block (`<status>completed</status>`) for `bsh1` | agent `state=="done"`, shell not running | guard: red if the union is per-file |
| `test_failed_taskstop_keeps_hold_successful_closes` | sidecar TaskStop `bsh1` with `is_error:true` result, then a second success result (`toolUseResult.task_id`) | after the first: running; after appending the success: done | first half red today (not held) |
| `test_agent_taskstopped_from_main_releases_its_shells` (guard) | hold fixture + main TaskStop `{"task_id":"<aid>"}` success | agent done, shell not running | guard: revert the `A in stopped` clause |
| `test_monitor_holds_until_status_or_expiry` | sidecar Monitor, `toolUseResult{taskId:"bm1",timeoutMs:1800000,persistent:false}`, launch ts = now-60s (ISO), stop row; then a status-less "Monitor event" block; then a variant with launch ts = now-2h | fresh: running, and still running after the event; expired: done | red today; the event half is red if `ended` is replaced by `done_any` |
| `test_host_gate_orphans` (guard) | (a) remove the live file; (b) procStart `Mon Jul 13 11:00:00 2026` (after launch) | both: agent done, shell not running | guard: revert the `host_start` clause |

Further tests:
- **`tests/test_selfcheck.py`** (rule 9: one assertion, both providers). Extend the shells block at 245-267: append one sidecar `agent-feed.jsonl` under the fixture's session dir with an S1 launch, and assert `parse_shells(spath)` includes it with `agent == "feed…"` and `running`. Assert `parse_any("auggie:…")["shells"] == [] and ["agents_bg"] == []` for the fixture Auggie session already in that file.
- **`tests/test_cr_agent_map_entry.py`**: add `test_panel_count_names_agents_and_shells`, using a `_panel` variant whose stub is `function setPanelCount(w,t){ CNT=t; }`.
  - Session with 2 agents, 3 shells and 1 agent_session → `"2 agents · 3 shells · 1 session"`.
  - Empty session → `"—"`.
  - Red today: the count is `"6"`.
- **Existing tests that must stay green unchanged:** `test_agent_cache` (open counts, golden), `test_agent_map.TestState`, `test_shells_running` (list-path vs `parse_shells` agreement on S1-only fixtures), `test_pass_cache.test_shells_pass_cached_and_output_stays_live`, the selfcheck shells block.

### 5. Sequencing

1. Write the tests above; run them red.
2. Add `_bg_acc`, `_bg_line` and `MOVED_RE`, and rewrite `_shells_pass` / `parse_shells` on top of them for main only. The existing suite stays green and `test_moved_to_background_shell_listed` turns green. This lands first because it is a pure refactor plus S2, and the next steps build on it.
3. Hook `_bg_line` into `_agent_file_pass`, add `_bg_tasks`, and switch `parse_shells` to it. The B tests turn green.
4. Add `_host_start`, `parse_agents(live=)` and the `parse_session` wiring. The A tests turn green.
5. Change the JS label (C).
6. `unset TRACKER_AUTH; make check` (one module per process if it gets OOM-killed).
7. Restart a **test** server on a free port and check the real session 82ce95d1:
   - expect `agents_bg` running == {a9ad361b, afd1ab11}
   - expect shells running == {bn4u12cbj, bsh4mgoq0}
   - expect Evidence "133 agents · 160 shells", map "133 agents · 2 running"
   - cross-check against state.json `fan` at that moment

   Stop the server by PID. This is a server change and a web change, so a restart is required.

### 6. Caches

- `file_pass("claude.shells", main)`: the key is unchanged and the value shape changes (dict). The pickled blob stays small because `_pend` is dropped before returning, and only bg launches and id sets are kept.
- `_AGENT_CACHE`: entries gain `"bg"`. The key is unchanged and the entry is still a pure function of the file's bytes, with no clock (Monitor `exp` is derived from the line's own timestamp).
- No new cache. `_host_start` reads about 14-30 small JSON files per detail poll. `_bg_tasks` costs one `file_pass` stat plus one `_agent_entry` stat pair per sidecar, all cache hits after `parse_agents`.

### 7. Must NOT change

- **List path:** `_tail_scan` `shells_running` (89-236), `_mtime_bg_n` `bg` (1257), and every list-dict key. Board, rail and sidebar badges stay a main-tail undercount (see decision 2).
- `parse_agents`:
  - `running` stays mtime-only for agents that are **not** held. `TestState.test_fresh_stop_after_last_message_is_done_but_running_unchanged` locks this.
  - The `state` rules for un-held agents, the sort order, and the 5-tuple return are unchanged.
  - Exactly one read per sidecar.
- `SHELL_RE`, and the "any `<task-notification>` closes a Bash shell" semantics.
- The shell dict keys (only `agent` is added) and the `agents_bg` row keys.
- No reading of `jobs/*/state.json` `fan`, and no `ps` or any other subprocess in the detail path.
- Auggie and augment_ext outputs.
- `agent_detail`'s mtime-only `running` (1834), the click-through pane. It is a known gap and stays as is.

### 8. Riskiest spot and its fallback

The **host gate** (`_host_start` returning `None`). If Claude Code stops writing `~/.claude/sessions/<pid>.json`, changes `sessionId`/`procStart`, or a host runs without one, then held agents and running shells would show **done** while still working. That is the same bug in the other direction. Fallbacks, all built in:
- dir missing → `0.0`
- unparseable `procStart` → `0.0`, keeping the liveness check but dropping the launch-time bound
- no file but session activity within `LIVE_WINDOW` → `0.0`

So the worst case is today's behaviour. The second risk is the `_agent_file_pass` loop restructure (the `json` failure path now reaches `_bg_line`). The `test_agent_cache` golden and open-count tests guard it.

Also observed, **not** in scope and not verified against the UI: `api-request-blob` rows have a `message` too, so `_agent_file_pass` probably double-counts `tools` for blocks they repeat.

### 9. Decisions you may want to overrule

1. **Parity with Claude Code, not "truth", for shells whose process died while the host is alive.** bn4u12cbj has no process, but its host 63290 is alive and launched it, and no notification exists. Under this plan it stays "running", exactly as Claude Code's footer and fan show it. The alternative is an age cap, for example a shell open for more than 24 h counts as done. That is more truthful in this case, but it breaks parity and misreports a genuine multi-day watcher. Recommended: no cap.
2. **Sidecar shells feed only the detail view.** The detail view lists all of them: 160 here, with the finished ones behind "Show N finished". Board, rail and sidebar `shells_running`/`bg` badges stay main-transcript-tail-only. Folding sidecars into the list path would cost a per-sidecar tail read on every 2 s list poll. Overrule if you want the board chip to say "2 shells" for this session too.

## Review of Plan v1 (opus)

Reviewed 2026-11-16 against worktree f07f1e4 and live data. I assumed v1 was wrong and ran its rules on real transcripts with scratch simulators (`~/.claude/jobs/16c95193/tmp/{sim,sweep,detail,moved,anchor2,noid,stops,fanmon,iserr}.py`, read-only, `python3 -I`). Corpus: 82ce95d1 (main + 133 sidecars), the 250 most recent sessions (sweep), the 3,000–4,000 most recent transcripts plus sidecars (shape census), and every `~/.claude/jobs/*/state.json` `fan`.

**Verdict:** the architecture holds: one accumulator, a union across files, TaskStop, a host gate, and a hold flag on `parse_agents`. Two rules in it produce **false "running forever"** that I observed on live sessions today (F1, F2). Monitors are overbuilt and wrong for the older shape (F4). The "worst case = today" fallback claim is false (F5). Four smaller fixes follow.

### Findings, ranked

**F1 — HIGH. Harness text quoted in ordinary Bash output creates phantom shells, and they hold the agent.**
1. *Defect:* v1 §3 `_bg_line`, the "Any other Bash `tool_use`" branch. It runs `SHELL_RE.search(txt) or MOVED_RE.search(txt)` over the **whole result text of every foreground Bash call**. Repro on live session 16c95193 (host 55745 alive): sidecar `agent-ac3a04e8…` ran `cd ~/.claude/projects/…; grep …` over 82ce95d1's transcripts. Its output quotes `"content": "Command did not complete … moved to the background (ID: bc3tkgaj3) …"`, so v1 yields running shells bc3tkgaj3 (twice) and bn4u12cbj owned by ac3a04e8, and holds ac3a04e8 `running` while 55745 lives. Expected: no shells. Grepping transcripts is routine in this repo's own workflow. Census (4,000 files): the result row's `toolUseResult` is a dict on every current-CLI row, and **its `backgroundTaskId` is the harness's own statement** (1,296 real shells: 656 explicit, 640 moved, 0 with `is_error`). The quoted-text hits are exactly the ones where `toolUseResult` is a dict *without* `backgroundTaskId`. `api-request-blob` copies of the same result carry no `toolUseResult` at all (S7: 52 blob rows with `tool_result` in 82ce95d1 main), so they would push quoted text back through any text fallback.
2. *Direction:* the structured field is authoritative whenever the row has one. Text is a fallback **only** when `toolUseResult` is not a dict (desktop sidecars, see F3), and even then only when the harness sentence **starts a line**. Blob/shape rows never feed launches, results or stops. Explicit `run_in_background` keeps today's `SHELL_RE` path unchanged. The raw-line `<task-notification>` scan is unchanged (today's rule).
3. *Way:* in `_bg_line`, return before the block loop when `o` is not a dict or `o.get("type") in ("api-request-blob", "api-request-shape")`. Resolve the id with `tid = tur.get("backgroundTaskId") if isinstance(tur, dict) else None`. Then, only if `not tid` and (`kind == "bg"` or `not isinstance(tur, dict)`), use `(SHELL_RE.search(txt) if kind == "bg" else None) or BG_LINE_RE.search(txt)` (F3). The same code serves both callers (`_shells_pass`, `_agent_file_pass`).
4. *Test:* `test_quoted_harness_text_is_not_a_shell`, a foreground Bash in a sidecar, in two variants:
   - (a) the result row has `toolUseResult:{"stdout":"…","interrupted":false}` and content containing the quoted sentence mid-line.
   - (b) the same with no `toolUseResult`.
   - Then a stop row. Assert `parse_session(main)["shells"] == []` and the agent's `state == "done"`. Red under v1.

**F2 — HIGH. Refused background launches are "running" forever and hold their agent.**
1. *Defect:* v1 §3 `_bg_tasks`: "A launch with no shell id stays 'running' unless gated, same as today" (today: claude.py:1744-1754 lists any `run_in_background` launch, even one with no matched result). Repro on live session 5849622c (host 88285 alive, procStart Nov 15 22:31Z):
   - Sidecar `agent-a033265f…` has two `run_in_background` launches at 08:22:51Z and 08:23:07Z. Their results are `is_error:true` with "auto mode cannot determine the safety of Bash".
   - Main `toolu_01Hj4U…` has a worktree-guard refusal.
   - Under v1 all three are running shells and a033265f is held `running` until the host exits. Its job `fan` shows nothing open.
   - The list path already refuses to count these: `_tail_scan` counts only resolved ids (claude.py:233; `test_shells_running.test_a_shell_launch_with_no_matched_result_is_not_counted`). Detail and list therefore disagree today, and v1 amplifies that into the agent hold.
2. *Direction:* a launch is a shell **only if its result resolves an id**. No id means the call never started a shell: it is not listed and holds nothing. That matches the list path. Do not key on `is_error`: no real shell result ever had it (iserr.py: 0 of 1,301).
3. *Way:* the accumulator holds one dict, `shells[tuid] = {"id", "cmd", "desc", "ts", "out"}`, written (`setdefault`) **only** in the `tool_result` branch, once `tid` is resolved. Pending launches live in `_pend` and are dropped with it. `_bg_tasks` iterates `shells` only.
4. *Test:* `test_refused_background_launch_is_not_a_shell`. A sidecar `run_in_background` launch whose result is `is_error:true` with the classifier text, plus a stop row. Assert no shell row and agent `state == "done"`. Also add `self.assertEqual(parse_shells(self.main), [])` to the existing `test_a_shell_launch_with_no_matched_result_is_not_counted`. Both are red today and under v1.

**F3 — MEDIUM. `MOVED_RE` misses two of the four real phrasings, and desktop sidecars have no `toolUseResult` to fall back on.**
1. *Defect:* v1's `MOVED_RE` requires `\(ID: x\)\.`. The real shapes in the census are:
   - `Command running in background with ID: x.` (656)
   - `Command did not complete within its Ns timeout and was moved to the background (ID: x).` (≈370)
   - `Command was moved to the background (ID: x) so that a message that arrived while it was running can reach you; …` (266)
   - `Command was manually backgrounded by user with ID: x.` (2)

   In claude-desktop sessions (CLI 2.1.321/323) the sidecar result rows carry **no `toolUseResult`**. Examples: 542952d8 `agent-af4663681c…` and 2bda7c0d `agent-aa931d8534…`, 202 such results in the census. There the third and fourth shapes are invisible under v1. Repro: a desktop sidecar result `Command was moved to the background (ID: bz0viz9jl) so that …` with no `toolUseResult` gives no shell. Expected: shell bz0viz9jl.
2. *Direction:* drop `MOVED_RE` and add one line-anchored fallback covering all four. `SHELL_RE` is untouched (`_tail_scan` shares it). The `.output` path is chosen by id.
3. *Way:* `BG_LINE_RE = re.compile(r"^Command (?:running in background with ID: |did not complete within its \d+s timeout and was moved to the background \(ID: |was moved to the background \(ID: |was manually backgrounded by user with ID: )([A-Za-z0-9]+)", re.M)` and `_OUT_RE = re.compile(r"Output is being written to:\s*(\S+\.output)")`. Then `outs = _OUT_RE.findall(txt)` and `out = next((p for p in outs if p.endswith("/" + tid + ".output")), outs[-1] if outs else "")`. The `outs[-1]` fallback keeps the selfcheck fixture, whose path is `srv.output` and not `<id>.output`. Census check (anchor2.py): all 202 genuine tur-less hits match at line start, including output-then-message ones. Both quoted false positives (ac3a04e8 and the ac0170be test-source dump) are mid-line and rejected.
4. *Test:* `test_moved_to_background_shell_listed`, in two variants:
   - (a) main, with `toolUseResult.backgroundTaskId:"bmv1"` and the timeout text.
   - (b) a sidecar with no `toolUseResult` and text `"…test output…\nCommand was moved to the background (ID: bmv2) so that a message that arrived while it was running can reach you; it was not interrupted. Output is being written to: /tmp/t/bmv2.output"`.
   - Assert both are listed and running, `bmv2.out` ends in `/bmv2.output`, and the owner agent is held. (b) is red under v1.

**F4 — MEDIUM, overbuilt and wrong. Monitor handling should be cut entirely.**
1. *Defect:* v1 §1/§3 adds `monitors`, `ended`, `<status>` chunking, `timeoutMs`/`persistent` expiry and a Monitor hold. But Claude Code's roster never counts Monitors. Across every job `fan`, there are 27 `shell` entries and all 27 are Bash ids (fanmon.py), with no Monitor kind. In 82ce95d1, 0 of 73 Monitors are open, so v1's Monitor rule contributes nothing to the contract. It is also wrong for the older or desktop shape. Repro: c932fc28 sidecar a3f3f25d, Monitor bma28pyb3. Its result has no `toolUseResult` ("expires in 10m" is only in text), and its expiry arrives as a **status-less** `Monitor event … [Monitor expired after 10m`, which v1 explicitly does not count as a close. So it is held forever while the host lives.
2. *Direction:* Monitors are never tasks. Remove `monitors`/`ended`, status parsing, expiry and the Monitor test. Keep "any `<task-id>` in a notification closes a Bash shell" (today's rule, `TASKDONE_RE.findall(line)` on the raw line, no chunking).
3. *Way:* `_bg_acc()` returns `{"shells": {}, "done": set(), "stopped": set(), "_pend": {}}`. `_pend` kinds are `"bg"`, `"fg"` and `"stop"` only.
4. *Test:* replace `test_monitor_holds_until_status_or_expiry` with `test_monitor_does_not_hold_agent`: a sidecar Monitor launch, `toolUseResult{taskId:"bm1",timeoutMs:1800000}`, then a stop row. Expect agent `done` and no shell row. It guards against re-adding Monitors as launches.

**F5 — MEDIUM. The "unknown host" path (`0.0`) holds agents forever. §8's "worst case is today's behaviour" is false.**
1. *Defect:* v1 returns `0.0` ("trust the transcript") when the sessions dir is missing, `procStart` won't parse, or no file but `_active_mtime` falls within LIVE_WINDOW. `live_aids` is then computed ungated. Repro: patch `config.LIVE_SESSIONS_DIR` to a missing path, with a sidecar holding an un-notified S1 shell and a trailing stop row, sidecar age 10 days. v1 gives `state:"running"` forever. Today it is `done`.
   - The `_active_mtime` branch is speculative: all 11 sessions written in the last hour have a live file (2 desktop, 9 bg).
   - It costs a glob plus a stat per sidecar on every poll of every dead session.
   - It also leaves a 5-minute "still running" tail after a clean exit.
2. *Direction:* an agent is held **only when a live host is known** (`host_start` is a positive float). When unknown, agents follow today's rules and shells today's ungated rule. A dead host (`None`) closes everything. Cut the `_active_mtime` branch.
3. *Way:* `_host_start` returns:
   - `0.0` when `os.listdir(LIVE_SESSIONS_DIR)` raises, or when a matching live file's `procStart` won't parse;
   - `None` when no live file names the sid;
   - otherwise the min epoch.

   In `parse_session`, `live_aids = {...} if hs else set()`. In `_bg_tasks`, `running = open and (hs is None → False; hs == 0.0 → True; else launch_ep >= hs - 1)`.
4. *Test:* `test_unknown_host_keeps_todays_rules`. Point the dir at a missing path. Expect agent `done`, while its shell is still listed `running` (today's shell rule). Red under v1.

**F6 — LOW-MED. Stale `<pid>.json` with a reused pid after reboot. Also, v1's fixture date predates this machine's boot.**
1. *Defect:* `_pid_alive` (claude.py:562) is the only liveness check. If a crash or power loss leaves `<pid>.json` behind and the pid is reused after reboot, that session's open shells and held agents read as running forever. `running_sessions` guards this with `ps lstart` (claude.py:753), which v1 rightly avoids. There is a stdlib boot clock: `time.time() - time.clock_gettime(CLOCK_MONOTONIC)` = 1793675862.61 here, identical to `sysctl kern.boottime`. Linux needs `CLOCK_BOOTTIME`.
2. *Direction:* ignore a live file whose `procStart` is before boot. Within-uptime pid reuse remains the documented residual, as for `_live_workers`.
3. *Way:* in `_host_start`, `boot = time.time() - time.clock_gettime(getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC))`, then `if ps < boot - 60: continue`, wrapped in the function's `try`. Separately, every test's `procStart` **must** be `time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(now - 3600))`. v1's fixture "Mon Jul 13 2026" predates the boot and would make every hold test red for the wrong reason. Launch timestamps are ISO `now - 1800`.
4. *Test:* add case (c) to `test_host_gate_orphans`: `procStart = gmtime(boot - 7200)` with pid = `os.getpid()`. Expect done. Red without the boot clause.

**F7 — LOW. Gate on the transcript's file name, not `meta.sessionId`.**
1. *Defect:* v1 wires `_host_start(sid, …)` with parse_session's `sid = meta.get("sessionId") or basename` (claude.py:2145). `meta.sessionId` is "last value wins" (claude.py:1929-1932). 4 of 257 recent transcripts carry other sessionIds; for example 7ee80df9.jsonl holds 472 a5db5b9d rows and 424 e813546e rows. If the trailing rows name another id, the live file (which names the file's id) never matches, and every shell is shown done.
2. *Direction:* use `os.path.basename(path)[:-6]`, the same key `find_session` and `shell_output` use. `sid` stays as it is for titles and tasks.
3. *Way:* `hs = _host_start(os.path.basename(path)[:-6])`, with the signature `_host_start(sid)` (no `path`, since F5 dropped `_active_mtime`).
4. *Test:* `test_gate_keys_on_file_name`: the fixture's last main row has `"sessionId":"other"`, and the live file names `"sess"`. Expect the agent held. Red if `meta.sessionId` is used.

**F8 — MEDIUM (cost). Every poll reads each shell's whole `.output` file, and the count goes from 9 to 161.**
1. *Defect:* `parse_shells` computes `last` with `fh.read().splitlines()` per shell (claude.py:1746-1752) on every 2 s detail poll. With sidecar shells, 82ce95d1 goes from 9 reads to 161; the 250-session sweep has 1,530 shells, 84% in sidecars. `.output` size is unbounded: a chatty `make check` writes MB. (82ce95d1's tasks dir is 972 KB, so it is fine today; this is not a bound.)
2. *Direction:* `last` comes from a bounded tail. `shell_output`'s click-time `_read_tail` is unchanged. Semantics stay "last non-blank line, [:200]".
3. *Way:* add `def _last_line(p, n=4096)`: open `"rb"`, `seek(max(0, size-n))`, `read().decode("utf-8","ignore")`, last non-blank line `[:200]`, `""` on OSError or empty `p`. Use it in `parse_shells`.
4. *Test:* `test_shell_last_reads_bounded_tail`. A 200 KB `.output` whose final line is `"END"`. Assert `last == "END"`, and, with a spy on `builtins.open` that wraps the returned file's `read`, that no read returns more than 4096 bytes. Red today. Existing `test_pass_cache.test_shells_pass_cached_and_output_stays_live` and the selfcheck `last` assertions stay green.

**F9 — LOW. Cached `_AGENT_CACHE` entries are frozen.** `_bg_tasks` must build fresh sets: `set().union(*(a["done"] for …))`. It must never call `.update` on `e["bg"]["done"]`. This is no behaviour change, only a directive. *Test:* in the hold fixture, with a main notification for an id that is **not** in the sidecar, call `parse_session(main)`. Assert `claude._AGENT_CACHE[sidecar][1]["bg"]["done"]` still equals the set the sidecar alone yields. Red if the union calls `.update` on the cached set.

**F10 — LOW. Hermeticity.** `parse_session` will now read the real `~/.claude/sessions` in every existing test. I grepped `tests/`: no existing assertion reads `shells[i]["running"]` or `agents_bg` state through `parse_session`/`parse_any` (test_pass_cache.py:359 checks content only). So nothing flips. *Direction:* every new test patches `config.LIVE_SESSIONS_DIR` (to a temp dir, or a missing path for F5). No change to old tests.

### Checked and left alone (direction stated)

- **The host gate is necessary.** No change. Sweep of 250 recent sessions: without the gate, 51 open shells and 20 held agents; with it, 12 and 6. All 39 removed are in sessions with no live host (e.g. 9383c8c3 with 7, 6c1c5dc5 with 5). For 82ce95d1 the gate changes nothing right now: 3 open, all launched after procStart; 29 earlier launches were already closed.
- **Both TaskStop clauses are necessary.** No change. 62 successful shell stops have no notification. 34 shells of TaskStop'd agents have no notification, from 84 agent stops.
- **The live path reaches the fix.** No change.
  - `agentMapModel` counts `a.state === 'running'` (ext_cr_dialogs.js:2907).
  - The Evidence panel groups by `x.running` (ext_cr_detail.js:2976).
  - The map is fed the detail dict (`ui.lastSession`, ext_cr_detail.js:2036-2037).
  - `build_overview` reads `a["running"]` (overview.py:57).

  v1 sets both `state` and `running`. Residual: the click-through pane's `agent_detail` mtime-only `running` (claude.py:1834). Same known gap as v1; document it.
- **Panel count C vs conventions rule 5.** No change. Lengths of server arrays are the server's data, not a re-derived threshold, label policy or ranking. The client already sums them (ext_cr_detail.js:2991), and "N open" labels exist (2772). `setPanelCount` uses `innerHTML`, so it must only ever receive numbers and fixed words.
- **The 160-shell panel is not a UI regression.** No change. Finished rows are behind "Show N finished" in both the CR panel and the legacy drawer (app.js:2027-2030), and only running ones render. The finished count rises from about 120 to about 280. `checkCompletions` (app.js:1660) will now also notify on sidecar-shell completions, which is the intended parity.
- **D (51):** no change. Agents started after host procStart number 105, not 51. 48 started after the 2026-11-15T08:55:07Z compaction, which fits the diagnosis.
- **Fan vs transcript drift:** no change; known gap. Fan lists an **in-flight foreground** Bash as a shell from its start (82ce95d1 `blow2mdbp`: fan open, its sidecar has only the `tool_use`). It becomes a moved shell only when its timeout result is written. bd1381a0 `bww58yhtv` showed the same lag. Do not hard-code "160/82" anywhere: at review time the session had 161 shells, 97 of them backgrounded by the harness rather than launched with `run_in_background`, because 266 rows corpus-wide use the "so that a message…" phrasing. Derive expectations at verification time.
- **The second glob in `_bg_tasks`** (one glob plus two stats per sidecar, cache hits): accept. Threading the entries out of `parse_agents` would change its 5-tuple contract for a few milliseconds.
- **Raw-line `TASKDONE_RE`** can be fooled by an agent quoting its own session's notification text. That is today's rule and stays as it is; the union is per session, so it cannot leak across sessions.

## Plan v2 — clean plan (opus reviewer)

Base f07f1e4. All line numbers are `aitracker/providers/claude.py` unless stated. Stdlib only. v2 is v1 with F1-F10 folded in. Monitors, `MOVED_RE`, status chunking and the `_active_mtime` fallback are cut.

### Rule (one paragraph)
A **shell** is a Bash call whose result row resolves a background id, from any file of the session (main or any sidecar `agent-*.jsonl`):
- If the row's `toolUseResult` is a dict, the id is `toolUseResult.backgroundTaskId`.
- For an explicit `run_in_background` call, `SHELL_RE` on its result also counts, as today.
- If the row has no dict `toolUseResult`, `BG_LINE_RE` (line-anchored) counts.
- `api-request-blob` and `api-request-shape` rows are never parsed for blocks.

A shell owned by file F (agent A, or "" for main) is **open** when all of these hold:
- its id is in no `<task-notification>` line of any file of the session;
- its id is not successfully TaskStop'd in any file;
- A is not successfully TaskStop'd;
- the host clause holds: `hs = _host_start(basename)` gives `None` → closed, `0.0` → no bound, a float → `launch_ep >= hs - 1`.

An agent is **held** when `hs` is a positive float and it owns an open shell. A held agent gets `running:true`, `state:"running"`, `ended:null`. Every other agent keeps today's rules exactly.

### Changes
1. **Imports (line 1):** add `calendar`.
2. **Near `SHELL_RE`/`TASKDONE_RE` (1697-1701), add:**
   - `BG_LINE_RE` and `_OUT_RE`, exactly as in F3, and `_BLOB_TYPES = ("api-request-blob", "api-request-shape")`.
   - `_bg_acc()`, returning `{"shells": {}, "done": set(), "stopped": set(), "_pend": {}}`.
   - `_bg_line(acc, line, o)`. It is pure (no clock, no config):
     1. If `"<task-notification>" in line`, then `acc["done"].update(TASKDONE_RE.findall(line))`.
     2. Return if `o` is not a dict or `o.get("type") in _BLOB_TYPES`, or if `message.content` is not a list.
     3. For each dict block:
        - **Bash `tool_use`:** `_pend[id] = ("bg" if input.run_in_background else "fg", {"cmd": command[:4000], "desc": description or "", "ts": o.get("timestamp")})`.
        - **TaskStop `tool_use`:** `_pend[id] = ("stop", input.get("task_id"))`.
        - **`tool_result` whose `tool_use_id` is in `_pend`:** pop it, then branch on its kind:
          - `"stop"`: if `not b.get("is_error")` and the id is a non-empty str, add it to `stopped`.
          - otherwise: `txt = _result_text(b.get("content"))`, `tur = o.get("toolUseResult")`. Resolve `tid` per F1. If `tid`: `outs = _OUT_RE.findall(txt)`, `out` per F3, then `acc["shells"].setdefault(tuid, dict(info, id=tid, out=out))`.
3. **`_shells_pass(path)` (1704):** `acc = _bg_acc()`. For each line: `try: o = json.loads(line) except ValueError: o = None`, then `_bg_line(acc, line, o)`. Then `acc.pop("_pend")` and `return acc`. It is still cached as `file_pass("claude.shells", …)`; the value becomes a dict, which the restart clears.
4. **`_agent_file_pass` (1343):**
   - Add `bg = _bg_acc()`.
   - At 1363-1367: `try: o = json.loads(line) except ValueError: o = None`, then `_bg_line(bg, line, o)`, then `if o is None: continue`. This runs **before** the SubagentStop `continue` at 1373; the rest is unchanged.
   - After the loop: `bg.pop("_pend", None)`. Add `"bg": bg` to the returned dict (1459).
   - The cache key is unchanged, and there is still exactly one open per sidecar.
5. **New `_host_start(sid)`, next to `running_sessions` (731).** It never raises.
   - Set `names = os.listdir(config.LIVE_SESSIONS_DIR)`; if that raises OSError, return `0.0`.
   - Set `boot` per F6. If that raises, use `boot = 0.0`.
   - For each `*.json` name, load it. Skip it unless it is a dict whose `sessionId == sid` and whose pid passes `_pid_alive`.
   - Compute `ps = calendar.timegm(time.strptime(" ".join(d["procStart"].split()), "%a %b %d %H:%M:%S %Y"))`. If that raises, return `0.0`.
   - Skip the file if `ps < boot - 60`. Otherwise keep the min.
   - Return the min, or `None`.
6. **New `_bg_tasks(path, host_start=0.0)`:**
   - `accs = [("", file_pass("claude.shells", path, _shells_pass))]`, plus `(e["aid"], e["bg"])` for each `af in sorted(_agent_files(path))` where `_agent_entry(af)[1]` is not None.
   - `done` and `stopped` are **fresh** unions (F9).
   - Each row is `{"id", "agent", "cmd", "desc", "ts", "out", "running"}`, with running per the Rule; `_ts_epoch(None)` is 0.0, so a launch with no timestamp counts as closed under a float `hs`.
   - It raises OSError when main is missing (via `file_pass`).
7. **`_last_line(p, n=4096)`:** per F8.
8. **`parse_shells(path, host_start=0.0, tasks=None)` (1734):**
   - If `tasks` is None, `tasks = _bg_tasks(path, host_start)`; on OSError return `[]`.
   - Each row is `{"id","cmd","desc","ts","running","last": _last_line(out),"out","agent"}`.
   - Same sort: `(not running, ts or "")`. Callers get the existing keys plus the additive `agent`.
9. **`shell_output` (1787):** `parse_shells(path, _host_start(os.path.basename(path)[:-6]))`.
10. **`parse_agents(path, hb=None, cost=None, live=frozenset())` (1518).** At 1584:
    - `held = aid in live`
    - `running = (now - e["mt"]) < config.LIVE_WINDOW or held`
    - `if held: done, ended = False, None`, then `elif` into the existing `stop_after` and `finished` branches, unchanged
    - The return stays a 5-tuple.
11. **`parse_session` (2139).** Just before the `parse_agents` call (2184):
    - `hs = _host_start(os.path.basename(path)[:-6])`
    - `try: bg_tasks = _bg_tasks(path, hs) except OSError: bg_tasks = []`
    - `live_aids = {t["agent"] for t in bg_tasks if t["running"] and t["agent"]} if hs else set()`
    - Pass `live_aids` as the 4th argument.
    - At 2215: `shells = parse_shells(path, hs, bg_tasks)`.
12. **`aitracker/web/ext_cr_detail.js:2991`:** the label from array lengths, as v1 C. Format: `A agent(s) · S shell(s)`, plus `· N session(s)` only when `agent_sessions` is non-empty, or `"—"` when all are empty. Numbers and fixed words only, because `setPanelCount` uses `innerHTML`.
13. **Auggie, D, list path:** no change (v1 §3 C/D/Auggie, §7).

### Tests (each red before its fix; guards proved by reverting the guarded line)
`tests/test_agent_map.py`, new `TestBackgroundHold(Base)`:
- `setUp` patches `config.LIVE_SESSIONS_DIR` to a temp dir holding `<os.getpid()>.json = {"pid": os.getpid(), "sessionId": "sess", "kind": "bg", "procStart": time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(now-3600))}`.
- Launch timestamps are ISO `now-1800`. Sidecars are aged 1000 s.

Cases:
- **`test_open_sidecar_shell_holds_agent_after_stop_row`:** S1 shell `bsh1` plus a stop row. Expect `state=="running"`, `running is True`, `ended is None`.
- **`test_sidecar_shell_listed_with_owner`:** `shells` contains `{"id":"bsh1","agent":aid,"running":True}`.
- **`test_moved_to_background_shell_listed`:** variants (a) and (b), per F3.
- **`test_quoted_harness_text_is_not_a_shell`:** variants (a) and (b), per F1.
- **`test_refused_background_launch_is_not_a_shell`:** per F2.
- **`test_completion_in_main_closes_sidecar_shell`** (guard): a main `queue-operation` row whose content holds `<task-notification><task-id>bsh1</task-id>…`. Expect done and not running.
- **`test_failed_taskstop_keeps_hold_successful_closes`:** as v1.
- **`test_agent_taskstopped_from_main_releases_its_shells`** (guard): as v1.
- **`test_monitor_does_not_hold_agent`:** per F4.
- **`test_host_gate_orphans`** (guard), three cases, each expecting done and the shell not running:
  - (a) no live file;
  - (b) procStart after the launch;
  - (c) procStart before boot, per F6.
- **`test_unknown_host_keeps_todays_rules`:** per F5.
- **`test_gate_keys_on_file_name`:** per F7.
- **`test_shell_last_reads_bounded_tail`:** per F8 (in `tests/test_pass_cache.py` beside the shells test).

Other test files:
- **`tests/test_shells_running.py`:** add `parse_shells(self.main) == []` to `test_a_shell_launch_with_no_matched_result_is_not_counted`, per F2.
- **`tests/test_selfcheck.py`** (shells block 245-267), per v1:
  - a sidecar `agent-feed….jsonl` with an S1 launch, listed with its `agent` and `running`, through `parse_shells(spath)` (default `host_start=0.0`, which is today's rule);
  - Auggie `shells == [] and agents_bg == []`.
- **`tests/test_cr_agent_map_entry.py::test_panel_count_names_agents_and_shells`:** as v1. Expected `"2 agents · 3 shells · 1 session"`, and `"—"` when empty.

These must stay green unchanged: `test_agent_cache` (open counts, golden), `test_agent_map.TestState`, `test_shells_running` agreement tests, `test_pass_cache` shells tests, and the selfcheck shells block.

### Sequencing
1. Write the tests and run them red. Every test patches `LIVE_SESSIONS_DIR`.
2. Add `BG_LINE_RE`/`_OUT_RE`/`_bg_acc`/`_bg_line`/`_last_line`, and rewrite `_shells_pass` and `parse_shells` main-only on top of `_bg_tasks` (with no sidecars yet). These turn green: F2's main half, F3(a), and F8. This lands first because it is the shared accumulator plus the two shape fixes, and nothing else depends on the host.
3. Hook `_agent_file_pass` up and finish `_bg_tasks`. The sidecar listing and quoted-text tests turn green.
4. Add `_host_start`, `parse_agents(live=)`, the `parse_session` wiring and `shell_output`. The hold, gate, unknown-host and file-name tests turn green.
5. Change the JS label.
6. Run `unset TRACKER_AUTH; make check`. If it is OOM-killed, run one module per process. The commit hook runs the gate, so give it a timeout over 2 min.
7. Start a test server on a free port, never `pkill`, and stop it by PID. A restart is required because this is a server and web change. Open 82ce95d1 and compare at that instant against `jobs/82ce95d1/state.json` `fan`:
   - running shells == fan shells without `doneAt`, minus in-flight foreground ids with no `tool_result` row yet;
   - held agents == the owners of those shells;
   - Evidence label `"133 agents · <len(shells)> shells"` (or whatever the agent count is at that moment) equals the map subtitle's agent count.

   Spot-check 16c95193 (expect no phantom shells under ac3a04e8) and 5849622c (expect no shells or held agent under a033265f).

### Caches
- `file_pass("claude.shells")`: same key; the value is now a small dict (shell dicts plus two id sets).
- `_AGENT_CACHE` entries gain `"bg"`. Each is still a pure function of the file's bytes and is never mutated (F9).
- No new cache. Each detail poll adds one `listdir`, about 14 small JSON reads and one `kill(0)` per matching file. `_bg_tasks` adds one glob and two stats per sidecar, all cache hits. `last` now costs at most 4 KB per shell.

### Must NOT change
Everything in v1 §7, plus:
- `SHELL_RE`, and the raw-line any-notification-closes rule;
- `_tail_scan` and the list-dict keys;
- un-held agents' `running`/`state`;
- `_read_tail`/`shell_output`'s output text;
- no subprocess in the detail path; no `jobs/*/state.json` read.

### Riskiest spot and its fallback
`_host_start` returning `None` for a session that is really alive: Claude Code stops writing `sessions/<pid>.json`, renames `sessionId`, or a host names a different id. Then running shells show done and held agents fall back to today's rules. That is a strictly smaller failure than today's "0 running", never "running forever". Fallbacks:
- dir missing → `0.0`;
- matching file with an unparseable `procStart` → `0.0`;
- in both cases agents get no hold and shells follow today's ungated rule.

Second risk: Claude Code rewording the harness sentence. Shells with a dict `toolUseResult` are unaffected. Desktop tur-less moved shells would simply be unlisted, which is today's state.

### Decisions for you
1. **Parity over truth** for a shell whose process died while its host lives (bn4u12cbj): it stays running, like Claude Code's footer. Recommended: no age cap. (Same as v1.)
2. **Sidecar shells are detail-only.** The board, rail and sidebar `shells_running` stay main-tail-only and ungated. That chip can already say "1 running" on a dead session; this is pre-existing and not fixed here. (Same as v1.)
3. **New: Monitors are never shown as running work**, because Claude Code's roster does not count them. Overrule if you want watchers to hold agents.
4. **New: refused or never-started background launches drop out of the shells list.** Today the detail view shows them "running" forever. This aligns detail with the list path.

## Reconciliation (main thread, 2026-11-16)

Plan v2 is the plan of record, plus the notes in this table.

| # | Finding | Verdict | Note |
|---|---|---|---|
| F1 | Quoted harness text creates phantom shells | **confirmed** | Repro is this session's own planner grepping 82ce95d1. Id-first rule kept. |
| F2 | Refused launches run forever and hold the agent | **confirmed** | Aligns detail with the list path (`_tail_scan`, claude.py:233) and its existing test. |
| F3 | Backgrounding phrasings missed | **confirmed** | One line-anchored `BG_LINE_RE`. Fallback only when there is no dict `toolUseResult`. |
| F4 | Monitors overbuilt and wrong | **confirmed** | Cut. Claude Code's roster never counts Monitors. User decision 3. |
| F5 | "Worst case = today" claim false | **confirmed** | Hold only when a live host is known; `_active_mtime` fallback cut. |
| F6 | Reused pid after reboot | **confirmed, with an implementer note** | Measured: `time.time()-clock_gettime(CLOCK_MONOTONIC)` = kern.boottime exactly, but `time.time()-time.monotonic()` is **6.2 days late** (excludes sleep) and would mark live agents done. Implementer MUST use `clock_gettime(CLOCK_BOOTTIME if present else CLOCK_MONOTONIC)`, never `time.monotonic()`. Fixture dates relative to now. |
| F7 | Host matched on transcript file name | **confirmed** | Low. |
| F8 | 161 full `.output` reads per poll | **confirmed** | A cost regression that B would introduce; last 4 KB only. |
| F9 | Never mutate cached per-agent sets | **confirmed** | |
| F10 | Tests must patch `LIVE_SESSIONS_DIR` | **confirmed** | |
| — | False alarms | none | |
| — | Missed by both / known gaps | **documented, not fixed** | (a) The click-through `agent_detail` still uses mtime-only `running` (claude.py:1834). (b) Board, rail and sidebar badges stay main-transcript-only (v1 decision 2). (c) Claude Code's "51" is not derivable from disk; no tracker change. (d) Auggie has no on-disk background-completion signal; it stays empty. |

Contract status: not discharged until implemented and live-verified (Agent map "running" matches the job's `state.json` fan agents/shells at that moment).

## User decisions (2026-11-16)
- Orphan open shell while the host is alive: show as **running**, matching Claude Code. No age cap.
- Monitors and refused or never-started launches: **excluded** from shells and from "running".
- Sign-off: **implement Plan v2 as reconciled.** The known gaps stay documented and unfixed.

## Implementation log (sonnet)

Implemented Plan v2 as reconciled: `claude.py` (`_bg_acc`/`_bg_line`/`_shells_pass`/`_host_start`/`_bg_tasks`/`_last_line`/`parse_shells`/`shell_output`, `_agent_file_pass` `bg`, `parse_agents(live=)`, `parse_session` wiring) and `ext_cr_detail.js` label. `dist/tracker.py` untouched. Boot clock uses `clock_gettime(CLOCK_BOOTTIME or CLOCK_MONOTONIC)`. procStart is UTC on this machine's live files (checked against `startedAt`), so `calendar.timegm` is right.

Deviation: `tests/test_selfcheck.py` shell block now points `config.LIVE_SESSIONS_DIR` at a missing dir (unknown host = ungated, today's rule) because `shell_output` now gates on the host and the fixture has no live file. The "must stay green unchanged" line therefore needed this one-line fixture patch.

Red/green proofs (revert the guarded line with a scoped replace, run the one test, restore, re-run). All RED when reverted, green restored:
- `TestBackgroundHold.test_open_sidecar_shell_holds_agent_after_stop_row`: `held = aid in live` -> `held = False`
- `test_sidecar_shell_listed_with_owner`: `accs.append((e["aid"], e["bg"]))` -> `pass`
- `test_moved_to_background_shell_listed`: `or BG_LINE_RE.search(txt)` -> `or None`
- `test_quoted_harness_text_is_not_a_shell`: `if kind == "bg" or not isinstance(tur, dict):` -> `if True:` (variant a); `^` anchor removed from `BG_LINE_RE` (variant b)
- `test_refused_background_launch_is_not_a_shell` and `test_shells_running...no_matched_result`: `if tid:` -> `if True:`
- `test_completion_in_main_closes_sidecar_shell`: dropped `info["id"] not in done and`
- `test_failed_taskstop_keeps_hold_successful_closes`: dropped `not b.get("is_error") and` (first half); dropped `info["id"] not in stopped and` (second half)
- `test_agent_taskstopped_from_main_releases_its_shells`: dropped `and aid not in stopped`
- `test_monitor_does_not_hold_agent`: re-added Monitor as a Bash-like launch plus `taskId` alias
- `test_host_gate_orphans`: `return best` -> `return 0.0 if best is None else best` (a); host time clause -> `True` (b); `if ps < boot - 60:` -> `if False:` (c)
- `test_unknown_host_keeps_todays_rules`: listdir OSError `return 0.0` -> `return None`
- `test_gate_keys_on_file_name`: `_host_start(basename)` -> `_host_start(sid)`
- `test_union_never_mutates_cached_agent_sets`: fresh union -> `.update` on the cached set
- `test_pass_cache.TestParseSessionCache.test_shell_last_reads_bounded_tail`: `fh.seek(max(0, size-n))` -> `fh.seek(0)`
- `test_cr_agent_map_entry...test_panel_count_names_agents_and_shells`: label -> old summed number
- selfcheck sidecar-shell assertion (`tests.test_tracker`): sidecar accumulation -> `pass`
- Auggie `shells == [] and agents_bg == []` selfcheck assertion: a regression pin, no Auggie code changed, so no red-by-revert exists.
