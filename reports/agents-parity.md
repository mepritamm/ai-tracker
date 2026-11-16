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

## Live parity DIFF debug (sonnet)

Method: ran `_bg_line` / `_bg_tasks` of the worktree code (9e686c8) over the real jsonl bytes (scripts in `~/.claude/jobs/16c95193/tmp/{dbg,dbg2,ids}.py`). Fan `shell` rows are volatile (state.json evicts finished ones), so ids were re-found in transcripts, not in the current fan.

| # | Session / id | Verdict | Root cause |
|---|---|---|---|
| 1 | 16c95193 `bc3tkgaj3` phantom, owner `ac3a04e8` | (c) not reproducible on current code; was the OLD (pre-9e686c8) unanchored `SHELL_RE` | In `agent-ac3a04e8*.jsonl` only rows 112 (Bash#106, toolUseResult dict without `backgroundTaskId`) and 119 (Bash#116, `toolUseResult` is a str because "Exit code 1") have a `tool_result` whose text contains "running in background with ID: bc3tkgaj3. Output is being written to". Old code (`git show 9e686c8^`, claude.py:1728 `SHELL_RE.search(_result_text(...))` on any Bash result) accepted both. Current `_bg_line` (claude.py:1750-1761): kind=="fg", dict tur has no id -> skipped; row 119 str tur falls to `BG_LINE_RE` (^-anchored, `re.M`) whose text starts "Exit code 1\n--- 1191..." -> no match. `_bg_tasks` on the real transcript now returns only bd5ae7rq9/bvpycwx49/bgf8ul8im (all closed). The haiku run most likely hit the running dashboard (old code, not restarted) rather than the worktree: restart `make serve` and re-run. |
| 2 | 16c95193 fan `bud6r2kxo` (later `bcwu9t6z2`, `bvgcoz8y8`) | (c) in-flight FOREGROUND Bash, legit timing | The id appears in NO transcript row as a launch; it appears only inside the output of the parity.py / grep Bash calls themselves (agent-aabf5893 row 70 = result of Bash#61 that ran parity.py; agent-ab6e8e46 rows 73/105). Those are the very commands reading state.json while still running; the harness gives every running Bash a shell id in `fan` before any result exists, and the transcript only learns the id if/when it is backgrounded. Same documented known gap as Reconciliation (in-flight fg Bash). Not detectable from bytes. |
| 3 | 57f66536 `bx8hmd2it` | (c) timing; tracker correct | Launched in `agent-a5356f76*.jsonl` row 41 (13:58:06Z) as a plain fg Bash, auto-backgrounded at row 44 with dict `toolUseResult.backgroundTaskId:"bx8hmd2it", backgroundedToDeliverMessage:true` (accepted by `_bg_line`; confirmed in `_bg_tasks`), `<task-notification>` for it at 14:00:17.9Z (main file row 674, sidecar row 75), so tracker = closed. `fan.doneAt` lags the notification (state.json refreshed per turn), so a run within that window shows fan open vs tracker closed. Tracker is the more accurate side. |
| 3b | 57f66536 `bxfx3fgbp` | (c) in-flight fg Bash | Appears in no transcript at all (not even a result). Same as #2. The id now present in fan, `b55d4yiux` (label `bash .../probe2.sh ... | sed`), is again a running fg Bash (startedAt 1794837650187, no transcript id). |
| 4 | 82ce95d1 `be1j71eaj` | (c) in-flight fg Bash, confirmed | Id appears in no row of the main jsonl or any subagent file; fan label is `J=.../tmp/ab; for i in ...` (a foreground poll loop), and it has since left the fan. Matches Reconciliation's documented known gap. |

No (a)/(b) defect found, so no fix is required for the four DIFFs.

### Residual hardening (optional, plan gap, low severity)
- Defect: claude.py:1759-1760 - for a fg Bash whose `toolUseResult` is NOT a dict (every `Exit code N` error result and other str/None results) the text fallback runs `BG_LINE_RE.search(txt)` with `re.M`, i.e. ANY line of the output may start with "Command running in background with ID: X". Repro: a fg Bash that prints (e.g. via python decoding a transcript, or `cat` of a note) a line beginning with that sentence and exits non-zero -> `toolUseResult` is a str -> phantom shell (input: tool_result text "Exit code 1\nCommand running in background with ID: zzz9. Output is being written to: /tmp/zzz9.output"; actual: shell zzz9 open; expected: none).
- Direction: for the non-dict-tur branch only, accept the sentence at position 0 of the result text (`BG_LINE_RE.match`), never mid-text; the explicit `run_in_background` branch and dict `backgroundTaskId` path must NOT change.
- Way: claude.py:1760 `BG_LINE_RE.search(txt)` -> `BG_LINE_RE.match(txt)` (the `^`/`re.M` can stay; `.match` anchors at 0). Real harness sentences start the text, so no live shell is lost (rows 44/48 of agent-a5356f76 begin "Command was moved to the background ...").
- Test: in the `_bg_line` unit tests add rows (fg Bash tool_use + user row with str `toolUseResult` and tool_result text "Exit code 1\nCommand running in background with ID: zzz9. ...") asserting `acc["shells"] == {}`; red before the `.match` change, green after; plus a positive row with text starting at 0 and no dict tur still yields the shell.

## Implementation review B — tests & UI (opus)

Scope: TestBackgroundHold, test_shell_last_reads_bounded_tail, test_panel_count_names_agents_and_shells, test_selfcheck/test_shells_running edits, ext_cr_detail.js label, scripts/bundle.py. Every revert below was applied to the worktree file, the test run, then the file restored and `cmp`-checked against a backup.

### Verified (independently)
- **Red on revert (8 reverts, all RED, all restored):** quoted text, `^` dropped from `BG_LINE_RE`; quoted text, `if kind == "bg" or not isinstance(tur, dict):` -> `if True:`; refused launch, `if tid:` -> `if True:`; boot guard, `if ps < boot - 60:` -> `if False:` (the "procStart before boot" case of test_host_gate_orphans); cached sets, union -> in-place `.update` on a cached set; tail read, `fh.seek(...)` -> `fh.seek(0)`; JS label -> old summed number; unknown host, `live_aids = ... if hs else set()` with the `if hs` dropped -> test_unknown_host_keeps_todays_rules RED.
- **Whole-feature revert:** with the parent commit's claude.py swapped in, 10 of the 13 TestBackgroundHold tests fail. The 3 that pass (quoted, refused, monitor) pass only because the parent never scanned sidecars. They guard only the new path. The main-transcript refused case is guarded by the test_shells_running addition, which is red on the parent.
- **Hermetic:** `config.LIVE_SESSIONS_DIR` is patched to a tempdir. procStart and every timestamp are relative to `time.time()`. The host pid is `os.getpid()`. The tests do not depend on the real ~/.claude.
- **Live path:** the tests go through `parse_session` -> `_host_start`/`_bg_tasks` -> `parse_agents(live=)` (claude.py:2289-2295, 1590) and `parse_shells(path, hs, bg_tasks)` (claude.py:2326), not a side helper.
- **Selfcheck deviation:** this is not a weakening. A missing dir gives `_host_start` = 0.0, which is the pre-change ungated rule. Every prior assert is kept and one is added. It is, however, why F1 below goes unnoticed.
- **JS:** `setPanelCount` innerHTML receives only array lengths and fixed words. The empty case "—" is asserted. "N agents" = `agents_bg.length`, the same number as `agentMapModel` `counts.total` (ext_cr_dialogs.js:2898), so the map and the Evidence label agree. Nothing else reads the count text. `node --check` passes, and the change sits inside a function body, so it cannot throw at load time.
- **bundle.py:** `calendar` is claude.py's only new stdlib import (claude.py:1), and it was added to HEADER.

### F1 (medium): the `shell_output` host gate is untested
- **Defect:** the host gate in `shell_output` at aitracker/providers/claude.py:1895 (`parse_shells(path, _host_start(os.path.basename(path)[:-6]))`) has no test. Replace it with `parse_shells(path)`, then run tests.test_selfcheck, test_agent_map, test_pass_cache, test_shells_running, test_cr_routes and test_integration: all stay **green**. The /api/shell click-through (server.py -> shell_output) could therefore drift from the panel row (parse_session, gated), showing a dead-host shell as "running" in the modal while the row says done, and no test would notice.
- **Fix direction:** add a test only, with no production change. Do NOT remove the selfcheck missing-dir patch, which keeps the selfcheck on today's ungated rule.
- **Way:** in `TestBackgroundHold`, add `test_shell_output_follows_host_gate`: `self.side(extra=self.s1())`, then `self.host(None)` -> `claude.shell_output(self.main, "bsh1")["running"] is False`; `self.host(-3600)` -> `True`; `self.host(-600)` (procStart after launch) -> `False`.
- **Proof:** red with the revert above, green restored.

### F2 (low; known gap, documented at reconciliation item 2/§438)
- **Defect:** test_shells_running's `test_agrees_with_parse_shells*` docstring says the list and detail paths reach the "SAME verdict". It compares `_tail_scan` with **ungated** `parse_shells(self.main)` (host_start=0.0), not the live detail path. Repro: take that fixture and set `LIVE_SESSIONS_DIR` to an existing empty dir. `list_sessions()` then gives `shells_running` 1, while `parse_session(main)["shells"]` gives running `[False]` (run here).
- **Fix direction:** no code change; the board chip stays ungated by decision. Correct the docstring to say "ungated parse_shells (host unknown)". Patch `config.LIVE_SESSIONS_DIR` to a missing dir in that class's setUp so the test states its precondition. Name the divergence in the PR body.
- **Proof:** none required, since only a docstring changes. If the board is ever gated, a parse_session-based agreement test becomes the red/green pin.

### No other findings
The rest of the implementer's red-on-revert claims that I spot-checked held.

## Implementation review A — provider (opus), recorded by the main thread
(The reviewer agent had no Edit tool. This is the main thread's summary of its report.)
- **Verdict:** the code follows Plan v2 line for line, but the v2 **hold rule is wrong**.
- **A-F1 HIGH:** on 82ce95d1, fan `doneAt` is set for a9ad361b and afd1ab11. Each has 4 `<task-notification><task-id>{aid}` rows in main, and their shells bn4u12cbj and bsh4mgoq0 are still open.
  - The only fan-open agent is a86a4bdd: a 600 s foreground Bash with an unanswered `tool_use` and no notification.
  - v2 (claude.py:2294 `live_aids` = shell owners; :1590 `held = aid in live`) shows a9ad/afd1 as running and a86a as done. That is wrong in both directions.
  - Proposed rule: when `hs > 0`, an agent is running if all of these hold:
    - it launched at or after `hs - 1`;
    - its aid is not in the session-wide `done` union;
    - its aid is not in `stopped`;
    - its spawning `tool_use` has no result with `toolUseResult.status != "async_launched"` (this covers sync agents).
  - The reviewer measured that this matches fan-open agents exactly on 6/6 live sessions.
  - Unchanged: shell listing and running state, the `hs` None/0.0 branches, and `_tail_scan`.
  - Tests:
    - (a) the owner of an open shell has a notification, so it is not running, and its shell is running;
    - (b) an unanswered foreground Bash with an old mtime and a live host is running, and becomes done when the host is None.
- **A-F2 LOW cost:** warm `parse_any` on 82ce95d1 goes from 33–69 ms to 61–150 ms. `parse_shells` takes 16 ms (165 tail reads). No change; document it.

## Implementation reconciliation (main thread, 2026-11-16)
| # | Finding | Verdict | Action |
|---|---|---|---|
| A-F1 | Hold rule inverts agent liveness vs Claude Code | **confirmed** (matches the original screenshot: Claude Code lists notified agents with live shells as hollow ○ "waiting on its own background work") | Re-plan → Plan v3 (design change, user decision below) |
| A-F2 | Poll cost about 2× warm | confirmed, **accepted** | Document only |
| B-F1 | `shell_output` host gate untested (claude.py:1895) | **confirmed** | Add `test_shell_output_follows_host_gate` |
| B-F2 | `test_agrees_with_parse_shells*` docstrings overstate list/detail agreement | **confirmed** | Fix docstrings, patch `LIVE_SESSIONS_DIR` in setUp, document the list/detail divergence |
| DBG | `BG_LINE_RE.search` with `re.M` on non-dict results can match mid-output (claude.py:1760) | **confirmed, low** | Change to `.match`, with a negative test and a positive test |
| live DIFFs | fan-only shells | **known gap** | In-flight foreground Bash appears in fan before any transcript row exists |

## User decision (2026-11-16, second round)
- Agent state is three-way, mirroring Claude Code's footer:
  - **running**: not yet notified, not stopped, launched since host start;
  - **waiting**: notified, but owns an open shell (shown with its shell id(s));
  - **done**.
- The Agent map header shows e.g. "1 running · 2 waiting". The server owns the state; the SPA renders it.

## Plan v3 — delta (opus)

Delta on 9e686c8 (Plan v2 as implemented). No code edited while planning. Probe scripts are in `~/.claude/jobs/16c95193/tmp/`: `v3shape.py`, `v3none.py`, `v3sync.py`, `v3live.py`, `v3bgline.py`.

### 0. Real shapes confirmed (conventions rule 7)
- **Spawn result.** 82ce95d1 has 140 Agent tool_uses, and every one maps 1:1 to a sidecar `meta.json` `toolUseId`. Each one's non-blob `tool_result` row has `toolUseResult.status == "async_launched"` (118 with `run_in_background: true`, 22 without). That row also carries the keys `agentId`, `isAsync`, `outputFile`, …
  - 16 further results carry `toolUseResult = None`. All 16 are `type: "api-request-blob"` rows, which re-echo the same "Async agent launched" text. `_bg_line` already returns early on `_BLOB_TYPES`, so they never count.
  - 18 tool_use ids are re-emitted after compaction. This is harmless because a re-seen launch only re-adds a `pend` entry.
- **Sync agents.** Across the 600 newest transcripts there are 726 `async_launched` results. There are 12 `completed` results (session 2e71f77c), with the keys `agentId`, `content`, `totalDurationMs`, `toolStats`, … There are 8 errors where `toolUseResult` is a **str** (`"Error: …"`) and `is_error` is true. So "the spawning tool_use has a non-blob result whose status != `async_launched`" means the agent returned (sync) or failed. In both cases it is not running.
- **Notification id = aid.** A real row reads `<task-notification>\n<task-id>a89fa5ca3328a98ae</task-id>\n<tool-use-id>toolu_…</tool-use-id>\n<output-file>…/tasks/a89fa5ca3328a98ae.output</output-file>\n<status>completed</status>…`. The `<task-id>` is the full sidecar aid, the same 17-character id that `state.json` `fan` uses. In 82ce95d1, 138 of the 140 aids have a notification. The 2 without one, a446c33e44a406319 and af5a77723b4bddc02, are exactly the two `fan` agents with no `doneAt`.

### 1. The rule (server, `parse_agents`)
Let `hs = _host_start(file-name sid)`, which `parse_session` already computes.
- **`hs` is None or 0.0:** use today's pre-v2 rules exactly. `running = (now - mt) < LIVE_WINDOW`, the stop_after/finished chain applies, `waiting` is never set, and `waiting_on = []`.
- **`hs > 0`:** compute three states.
  - **running** when all of these hold:
    - `aid ∉ done_u`, the session-wide `<task-id>` union from main plus every sidecar;
    - `aid ∉ stopped_u`, the union of successful TaskStop targets;
    - `e["tuid"] ∉ ret_u`, the union of spawn tool_use ids whose non-blob result has `toolUseResult.status != "async_launched"`;
    - `_ts_epoch(row["started"]) >= hs - 1`.
  - **waiting:** not running, and `aid` owns at least one shell with `running=True` in `bg_tasks`.
  - **done:** otherwise.

  In the `hs > 0` branch, SubagentStop rows and the mtime are both **ignored** for liveness. The stop_after/finished chain still supplies `ended` for done agents.

Live match: `v3live.py`, run at 2026-11-16T20:00:18. It used the worktree's `_host_start`/`_bg_tasks`/`_agent_entry` plus the rule above, against `~/.claude/jobs/<sid8>/state.json` `fan` for every session with a live pid. Expected states:
- a fan agent with no `doneAt` should be **running**;
- a fan agent with `doneAt` that owns an open shell should be **waiting**;
- any other fan agent should be **done**.

| Session | hs | Fan agents | v3 = fan | Waiting (open shells) | v3 live but not in fan | Open shells (fan / tracker) |
|---|---|---|---|---|---|---|
| 82ce95d1 | live | 4 (open: a446c33e4, af5a77723) | **4/4** | a9ad361b4 [bn4u12cbj], afd1ab11c [bsh4mgoq0] | none | 5 / 3 |
| 16c95193 | live | 1 (open: af4c805a4) | **1/1** | — | none | 0 / 0 |
| 5849622c | live | 1 (done) | **1/1** | — | none | 0 / 0 |
| bd1381a0, 57f66536, 0f4ee7b4 | live | 0 | 0/0 | — | none | 0 / 0 |
| 985e4755, 2bda7c0d, 542952d8, 2e71f77c, ae962345 | — | no job `state.json` (desktop/other sessions) | n/a | | | |

Totals: 6/6 fan agents match, and the rule adds no extra live agents. Under v2, 82ce95d1 shows a9ad/afd1 as running (wrong) and the two un-notified agents as done (wrong). In 82ce95d1, a446c33e4 owns the open shell br5ilh5yj and is correctly **running**, because running wins over waiting. The 2 fan-only shells, b0f546jpo and bfyatvqoc, appear in no transcript. They are the in-flight foreground Bash known gap and are not this plan's concern.

### 2. Server shape (shared detail dict, `agents_bg[]` row)
- `state` is one of `"running" | "waiting" | "done"`; today it is only running|done.
- `running` stays a bool and is **True only for state running**. A waiting row has `running=False`.
- New field `waiting_on`: a list of shell ids, in `bg_tasks` launch order. It is non-empty only when state is `"waiting"` and `[]` otherwise. It is always present on Claude rows. Auggie emits `agents_bg: []`, so it needs no change.
- `ended` is None for waiting. `dur_s` for a waiting agent freezes at its last message (`end_ep = last_msg_ep if done or waiting else now`). This is identical to today for pre-v2 rows.
- The sort is unchanged (`(not running, ts)`).

Consumers of `running`/`state`, and whether waiting counts as live:

| Consumer | Reads | Waiting counts as live? | Change |
|---|---|---|---|
| overview.py:57 "⚙ N background agent(s) working" | `running` | **no**: its own turn is done; its shell is listed under shells | none |
| ext_cr_detail.js:962 `detailIsWorking` (glow) | `running` | no; stays close to the board's mtime-based `bg` | none |
| ext_cr_detail.js:2466 pill "N agents running" | `running` | no ("running" means running) | none |
| ext_cr_detail.js:712 timeline "finished" marker | `!running` | marker = its turn finished. Correct, since Claude Code also notifies at that point | none |
| app.js:1660 `checkCompletions` | `running` | no. The running→waiting transition fires the "finished" toast, which is the same moment Claude Code notifies | none |
| app.js:1952 chips, app.js:1963 legacy bg panel | `running` | no | none |
| ext_cr_dialogs.js:2907 `agentMapModel` counts | `state` | separate count | **add `counts.waiting`** |
| ext_cr_dialogs.js:2919/2926/2931 hide/showUp/dimmed | `state === 'running'` | **yes**: visible and not dimmed under "Hide finished" | treat `running` or `waiting` as live |
| ext_cr_dialogs.js:2955 `agentMapSubtitle` | counts | — | `"N agents · R running · W waiting · …"` (the waiting part only when W>0) |
| ext_cr_dialogs.js:3064-3078 `nodeEl` | `state` | hollow dot plus "waiting on shell <ids>" in the meta span | dot class `is-waiting` |
| ext_cr_dialogs.js:2967 pane facts / 2981 emptyText / 3005 paneNeedsFetch | `state` | "State: waiting" renders as-is; a waiting agent re-fetches like a done one | none |
| ext_cr_detail.js:2967-2988 `groupAgentReruns` / `renderAgentsPanel` | `running` | **yes**: in the top list, not behind "Show N finished" | `g.waiting`, hollow dot, tag |
| claude.py:1906 `agent_detail.running` (mtime) | — | — | none (known gap (a), still documented) |
| tests/test_working_glow_detail.py, test_cr_logic.py | `running` bool | — | none (semantics of `running` unchanged for pre-v2) |

### 3. Exact edits (shortest diff, no new abstractions)

**aitracker/providers/claude.py**
1. `_bg_acc` (1719-1720): add `"ret": set()`.
2. `_bg_line` (1723-1765):
   - In the tool_use arm, add `elif b.get("name") in ("Agent", "Task"): pend[b.get("id")] = ("agent", None)`.
   - In the tool_result arm, right after `kind, info = pend.pop(tuid)`, add:
     ```python
     tur = o.get("toolUseResult")
     if kind == "agent":
         if (tur.get("status") if isinstance(tur, dict) else None) != "async_launched":
             acc["ret"].add(tuid)
         continue
     ```
     Then delete the later duplicate `tur = o.get("toolUseResult")`.
   - **DBG fix (direction changed, see §6):** line 1759 `if kind == "bg" or not isinstance(tur, dict):` becomes `if kind == "bg" or tur is None:`. `BG_LINE_RE.search` stays as it is.
   - Update the docstring to say "+ spawn ids that returned".
3. `parse_agents` (1524):
   - New signature: `parse_agents(path, hb=None, cost=None, hs=None, open_by=None)`. The `live` param is removed. Its only caller is `parse_session`; the tests call it positionally with ≤2 args.
   - Before the `out` loop:
     ```python
     open_by = open_by or {}
     if hs:
         try:
             mb = file_pass("claude.shells", path, _shells_pass)   # fresh pickled copy, 0.04 ms warm on 82ce95d1
         except OSError:
             mb = _bg_acc()
         accs = [mb] + [e["bg"] for e in entries]
         done_u = set().union(*(a["done"] for a in accs))          # FRESH sets, never .update a cached one
         stopped_u = set().union(*(a["stopped"] for a in accs))
         ret_u = set().union(*(a["ret"] for a in accs))
     ```
   - In the loop, replace the `held`/`running` lines (1590-1593) with:
     ```python
     if hs:
         running = (aid not in done_u and aid not in stopped_u and e["tuid"] not in ret_u
                    and _ts_epoch(e["row"]["started"]) >= hs - 1)
         waiting = not running and aid in open_by
     else:
         running, waiting = (now - e["mt"]) < config.LIVE_WINDOW, False
     if hs and (running or waiting):
         done, ended = False, None
     elif e["stop_after"]: ...   # unchanged chain
     ```
   - Then:
     - `end_ep = e["last_msg_ep"] if done or waiting else now`
     - `"state": "waiting" if waiting else ("done" if done else "running")`
     - `"waiting_on": list(open_by.get(aid, ())) if waiting else []`
   - Update the docstring: replace the `live=` text with the three-way rule.
4. `parse_session` (2289-2295): replace the `live_aids` line with:
   ```python
   open_by = {}
   for t in bg_tasks:
       if t["running"] and t["agent"]:
           open_by.setdefault(t["agent"], []).append(t["id"])
   agents_bg, ... = parse_agents(path, hb_ag, agent_cost, hs, open_by)
   ```
   This is safe with hs None/0.0 because `parse_agents` ignores `open_by` unless `hs`.
5. Remove every v2 "hold" comment (1590 "owns an open background shell …").

**aitracker/web/ext_cr_dialogs.js**
- 2898: `counts = { total, running: 0, waiting: 0, byFamily }`.
- 2907: `if (a.state === 'running') counts.running++; else if (a.state === 'waiting') counts.waiting++;`.
- 2919: `hide` default becomes `counts.running + counts.waiting > 0`.
- 2926: `showUp` for `n.state === 'running' || n.state === 'waiting'`.
- 2931: `dimmed = hide && n.state !== 'running' && n.state !== 'waiting' && !forced[n.key]`.
- 2955: after the running part, `if (c.waiting) parts.push(c.waiting + ' waiting');`.
- 3064-3073 `nodeEl`:
  - `var wait = n.state === 'waiting';`
  - when `wait && n.waiting_on && n.waiting_on.length`, push `'waiting on shell' + (n.waiting_on.length > 1 ? 's ' : ' ') + n.waiting_on.join(', ')` into `meta`. This is a text node via `h()`, so no HTML.
  - dot class `run ? 'is-running' : wait ? 'is-waiting' : 'is-done'`.

**aitracker/web/ext_cr_dialogs.css** (after 642): `.cr .cr-amap-dot.is-waiting { background: transparent; box-shadow: inset 0 0 0 1.5px var(--state-working, #1c9163); }`.

**aitracker/web/ext_cr_detail.js**
- `groupAgentReruns` (2967-2981): add `var waitingItem = items.filter(function (x) { return x.state === "waiting"; })[0];`. Set `latest = runningItem || waitingItem || items[0]` and return `{ latest, count, running: !!runningItem, waiting: !runningItem && !!waitingItem }`.
- `renderAgentsPanel`:
  - 2987: `runningGroups = grouped.filter(g => g.running || g.waiting)`.
  - 2988: `finishedGroups = grouped.filter(g => !g.running && !g.waiting)`.
- `agentRow`:
  - 3016: dot `g.running ? "is-working" : g.waiting ? "is-waiting" : "is-done"`.
  - When `g.waiting`, append `'<span class="crd-agent-wf mono">waiting on shell ' + esc((a.waiting_on || []).join(", ")) + "</span>"` after `tag`.
- Doc comment line 36: `{id,aid,wf,task,last,ts,running,state,waiting_on,tools}`.

**aitracker/web/ext_cr_detail.css** (after 1308): `.cr .crd-state-dot.is-waiting { background: transparent; box-shadow: inset 0 0 0 1.5px var(--state-thinking); }`.

**Not touched:** `dist/tracker.py`, app.js, overview.py, `_tail_scan`, `_mtime_and_bg`, `_bg_tasks`, `parse_shells`, `shell_output`, `agent_detail`, Auggie.

### 4. Tests (all in existing files; name → fixture → red-before-fix)
New helper in `TestBackgroundHold`: `def notify(self, *ids): self.main_add([{"type": "queue-operation", "content": "".join("<task-notification><task-id>%s</task-id></task-notification>" % i for i in ids)}])`. The fixture agent from `side()` is unchanged (started -1900 s, stop row, mtime -1000 s; host procStart -3600 s).

| Test (tests/test_agent_map.py unless noted) | Fixture | Expected | Red before |
|---|---|---|---|
| **REWRITE** `test_open_sidecar_shell_holds_agent_after_stop_row` → `test_notified_owner_of_open_shell_is_waiting` (A-F1 a) | `side(extra=s1())`; `notify("a1")` | a1 `(state, running, ended, waiting_on) == ("waiting", False, None, ["bsh1"])`; `shells[0]["running"] is True` | on 9e686c8: state "running" (v2 hold). After the fix, revert `waiting = ...` → `False`: "done" |
| **NEW** `test_unanswered_foreground_bash_agent_is_running` (A-F1 b) | `side(extra=[_bash("u5", -1800, bg=False)])`: no result, stop row, old mtime, no notify | host -3600 → "running", `running` True; `self.host(None)` → "done" | on 9e686c8: "done" (no open shell, stale mtime). Revert the v3 `running` to the mtime rule: red |
| **NEW** `test_sync_spawn_result_ends_agent_async_does_not` | main gets Agent tool_use `tu1` (`_spawn("tu1")` in `_msg`) and `_result("tu1", -1000, "done", {"status": "completed", "agentId": "a1"})`; sidecar meta `{"toolUseId": "tu1"}` via `self.agent(..., meta=)` | "done"; then with `{"status": "async_launched"}` instead: "running" | drop `e["tuid"] not in ret_u` → first half red. Replace `!= "async_launched"` with `True` → second half red |
| **NEW** `test_notification_in_another_sidecar_counts` | `side("a1")` and `side("a0", extra=[{"type": "queue-operation", "content": "<task-notification><task-id>a1</task-id></task-notification>"}])` | a1 "done" | build `done_u` from main only → red |
| **CHANGE** `test_moved_to_background_shell_listed` | add `notify("a1")` | a1 `("waiting", ["bmv2"])`; (b) stays the positive guard for tur-None, sentence-after-output | the v2 assertion "running" is vacuous under v3; the `.match` variant of DBG turns (b) red |
| **CHANGE** `test_quoted_harness_text_is_not_a_shell` | add `notify("a1")` per loop | "done" (a phantom shell would make it "waiting") | unchanged reverts; without notify it would fail spuriously as "running" |
| **CHANGE** `test_refused_background_launch_is_not_a_shell`, `test_monitor_does_not_hold_agent` (rename `…_is_not_a_shell`) | add `notify("a1")` | "done" | as v2 (Monitor-as-shell → "waiting") |
| **CHANGE** `test_completion_in_main_closes_sidecar_shell` | `notify("a1")` → assert "waiting"; then `notify("bsh1")` → "done", shell not running | — | drop `info["id"] not in done` → stays "waiting" |
| **CHANGE** `test_failed_taskstop_keeps_hold_successful_closes` → `test_failed_taskstop_keeps_shell_open_successful_closes` | `notify("a1")` first | failed stop → "waiting"; successful stop → "done", shell closed | as v2, with "waiting" in place of "running" |
| unchanged `test_agent_taskstopped_from_main_releases_its_shells` | — | "done" | now also pins `aid not in stopped_u` (without it a1 is "running") |
| unchanged `test_host_gate_orphans` | — | "done" ×3 | "procStart after launch" now pins `started >= hs - 1` |
| unchanged `test_unknown_host_keeps_todays_rules`, `test_gate_keys_on_file_name` | — | "done"/"running" | `if hs` → `if hs is not None` turns unknown-host red ("running") |
| **EXTEND** `test_union_never_mutates_cached_agent_sets` | snapshot `done`, `stopped` and `ret` of the cached entry | all equal after re-parse | `done_u = accs[1]["done"]; done_u.update(...)` → red |
| **NEW** `test_shell_output_follows_host_gate` (B-F1) | `side(extra=s1())` | `shell_output(self.main, "bsh1")["running"]`: host None → False; -3600 → True; -600 → False | `shell_output` → `parse_shells(path)` → red |
| **NEW** `test_error_exit_quoting_harness_sentence_is_not_a_shell` (DBG) | `side(extra=[_bash("u6", -1800, bg=False), _result("u6", -1790, txt, txt, err=True)])` with `txt = "Exit code 1\nCommand running in background with ID: zzz9. Output is being written to: /tmp/t/zzz9.output"` (str tur) | `shells == []` | on 9e686c8: phantom zzz9 (str tur takes the text fallback) |
| tests/test_shells_running.py `ClaudeShellsRunningTailScanTests` (B-F2) | `setUp`: `p = mock.patch.object(config, "LIVE_SESSIONS_DIR", os.path.join(self.pdir, "no-live")); p.start(); self.addCleanup(p.stop)`. Docstrings of `test_agrees_with_parse_shells*` say "ungated parse_shells (host unknown); the live detail path is host-gated and may differ (documented)" | unchanged | none (docstring and precondition only) |
| tests/test_cr_agent_map_ui.py `_PURE_JS` + class | `agentMapModel(sess([row('r', {state: 'running'}), row('w', {state: 'waiting', waiting_on: ['b1']}), row('d')]), {})` | `counts.running == 1`, `counts.waiting == 1`; subtitle contains `"1 running · 1 waiting"`; `w` visible and not dimmed; a model with no waiting row has no "waiting" in its subtitle | before: `counts.waiting` undefined, no subtitle part, `w` dimmed |
| tests/test_cr_agent_map_ui.py renderAgentMap DOM harness (~349) | add `row('w', {state: 'waiting', waiting_on: ['bsh1']})` | node dot has `is-waiting`; text contains "waiting on shell bsh1" | before: `is-done`, no text |
| tests/test_cr_agent_map_entry.py `test_panel_waiting_agent_listed_not_finished` | `_panel({"agents_bg": [{"aid": "w1", "task": "t", "running": False, "state": "waiting", "waiting_on": ["bsh1"], "ts": 1}], "shells": []})` | html has `is-waiting` and "waiting on shell bsh1", and **no** "Show 1 finished" | before: the row is hidden behind "Show 1 finished" |
| tests/test_selfcheck.py ~232 (rule 9) | existing `_r0` | add `assert _r0["waiting_on"] == []` | the field is missing on 9e686c8 |

Prove each test red by reverting with a scoped Edit, never with git stash. Gate: `unset TRACKER_AUTH; make check` (one module per process if it is OOM-killed). Also run `node --check` on both JS files. CSS change only adds rules; per the gate-misses-load-time memory, keep it free of comment edits.

### 5. Sequencing, caches, risks
1. **Sequencing:**
   1. `_bg_acc`/`_bg_line` (`ret` plus the DBG fix) with the DBG test.
   2. `parse_agents`/`parse_session` with the TestBackgroundHold rewrites and new tests.
   3. B-F1/B-F2 tests.
   4. JS/CSS with JS tests.
   5. Gate, then the `v3live.py` re-run against the running worktree build (restart `make serve` on a test port; never kill 8787).

   Server first, because the SPA needs `state == "waiting"` to exist.
2. **Caches:**
   - `ret` lives in the per-file accumulator, so it is a pure function of that file's bytes. The `_AGENT_CACHE` key and `file_pass` key are unchanged.
   - Both caches are in-memory only, so a restart drops entries that lack `ret`. No persisted shape changes.
   - Unions are always `set().union(...)`, which creates fresh sets. No `.update`/`.add` ever touches `e["bg"][*]`.
   - `open_by` is built fresh per call from `bg_tasks` dicts that `_bg_tasks` already builds fresh.
3. **Risky spot: losing the notification.**
   - Possible causes:
     - Claude Code changes the `<task-notification>` format;
     - the notification is lost to a crash;
     - the Agent result is only in a blob row.
   - Effect: under a live host, an un-notified agent stays "running" indefinitely.
   - Bound: `hs` (a new host process makes it done), plus TaskStop and the sync `ret`.
   - **Fallback, if live checks ever show a stuck agent:** add `or (e["stop_after"] and (now - e["mt"]) > 6 * 3600)` to `done` in the `hs` branch. It is not added now, because 6/6 sessions match and the user chose no age cap for shells.
   - The second risk is `started` being empty, which gives `_ts_epoch` 0.0 and therefore "done". That is the safe direction.
4. **Must NOT change:**
   - shell running rule (`_bg_tasks`);
   - `parse_shells`/`shell_output` gating;
   - `_tail_scan`/`shells_running`;
   - `_mtime_and_bg`/board `bg`;
   - `hs` None/0.0 agent behaviour;
   - the `running` bool semantics for pre-v2 rows;
   - the `parse_agents` 5-tuple return;
   - `agent_detail`;
   - Auggie's empty shapes;
   - the selfcheck missing-dir patch;
   - `dist/tracker.py`;
   - the `BG_LINE_RE` `^`/`re.M` anchor and `.search`.
5. **Cost:** A-F2 is still accepted. v3 adds one warm `file_pass` load of the main accumulator (0.04 ms on 82ce95d1) and three small set unions.

### 6. Decisions / corrections the user may want to overrule
- **DBG direction is reversed (an evidence-based correction to the reconciliation).** `BG_LINE_RE.search` → `.match` would **lose real shells**. Across the 1500 newest transcripts there are 9 genuine harness "did not complete within its 120s timeout and was moved to the background" results with `toolUseResult` absent. In each, the sentence starts a line **after** interim output, and the text ends with the harness tail. The change would also break the existing positive test `test_moved_to_background_shell_listed` (b).
  - The only phantom observed is a **str** `toolUseResult` (an `is_error` "Exit code 1" result). All real background results have `toolUseResult` either None or a dict, and `is_error` false.
  - Fix: `not isinstance(tur, dict)` becomes `tur is None`.
  - Residual known gap: a sidecar foreground Bash with no `toolUseResult` that exits 0 and prints a line starting with the harness sentence would still create a phantom.
- **Waiting is not "working".** The session glow, the overview "now" line, the "N agents running" pill, app.js chips and the completion toast all treat waiting as not running. The toast fires on running→waiting, the same moment Claude Code notifies. The alternative is to count waiting as live in the glow.
- **Header wording:** "· W waiting" appears only when W>0 (for example "3 agents · 1 running · haiku…"). The alternative is to always show "0 waiting".
- **`dur_s` for a waiting agent freezes** at its last message rather than ticking.

## Re-review of Plan v3 (opus)

Brief: assume Plan v3 is wrong. Read-only; probes are in `~/.claude/jobs/16c95193/tmp/rr_*.py` (run with `python3 -I`, `TRACKER_AUTH` unset). No code edits, no git diff, no stash, no process control.

### Verdict
The v3 **running rule is wrong in one material way.** It treats an agent's notification as permanent, and it gates liveness on the agent's *first* row. Claude Code agents are **re-openable**: they wake after a SendMessage from the coordinator, or after their own background shell finishes. So any woken agent shows "done" while it works.

Everything else holds up:
- the three-way shape;
- the SPA consumers;
- the DBG reversal;
- decisions 2–4.

Fix that one rule (R1 below) and v3 ships.

### Findings

**R1 HIGH — a woken or resumed agent is shown "done" while it runs** (Plan v3 §1 / §3.3 `running = aid not in done_u … and started >= hs - 1`)
- **Live repro, caught by `rr_v31live.py` / `v3live.py` at 20:13:56 local, session 8b05c822.**
  - Agent adea15293a8528229 was spawned 2026-11-15T11:39Z.
  - It was notified many times. The last notification before the wake was at 2026-11-16T12:23:48Z.
  - The host restarted at 13:48:07Z (a resumed session: same sid, new pid).
  - The coordinator sent a SendMessage at 14:42:12Z. The sidecar wake row ("The coordinator sent a message while you were working") is at 14:42:22Z, and that equals fan `startedAt`.
  - **Fan said running; v3 said done**, failing both clauses: the aid was in `done_u`, and `started` 11-15 < hs.
  - v2 and pre-v2 (mtime) said running.
  - The agent re-notified at 14:47:08Z. Its last message was at 14:47:03Z.
- **Prevalence (`rr_wake.py`, 400 newest sessions).** 277 of 2726 agents (10%) woke after their first notification:
  - 301 wakes were coordinator SendMessages;
  - 201 were `[SYSTEM NOTIFICATION]` wakes, where the agent's own shell finished. This is exactly the **waiting → woken** path: v3 shows such an agent "done" because its shell closed and its aid is already in `done_u`;
  - 72 were other (hook re-prompts).
  - Since 2026-10, spawn results carry `canContinueAgent`.
- **Ordering is reliable (`rr_lastmsg2.py`, 2491 notified agents).** The notification always follows the agent's last message row:
  - the minimum gap is +7 ms and the median is +13 s;
  - no gap falls in (-5 s, 0);
  - only 5 gaps are negative, all of them real wakes on dead hosts (`hs` None, so harmless).
- **Fix direction.** Replace "ever notified" with "the agent's last message is newer than its last notification or sync return". Replace the `started` gate with `last_msg_ep`.
- **Must NOT change:**
  - the shell rule (`_bg_tasks` keeps the plain `done` set, counting every row, timestamped or not);
  - the `hs` None/0.0 branch;
  - `stopped_u`;
  - waiting = not running ∧ owns an open shell.
- **The way:**
  - `_bg_acc`: add `"nts": {}` (task-id → latest notification epoch) and make `"ret": {}` a dict (spawn tuid → result epoch), not a set.
  - `_bg_line`, at the top:
    ```python
    if "<task-notification>" in line:
        ids = TASKDONE_RE.findall(line)
        acc["done"].update(ids)
        ts = o.get("timestamp") if isinstance(o, dict) and o.get("operation") != "remove" else None
        ep = _ts_epoch(ts) if ts else 0.0
        if ep:
            for i in ids:
                if ep > acc["nts"].get(i, 0.0):
                    acc["nts"][i] = ep
    ```
    Why these exclusions:
    - Blob re-echoes have no timestamp. If they counted, an old notification would close a woken agent.
    - A queue `remove` row is written when the queue drains, which can be after the agent wakes.
  - In the agent arm:
    ```python
    acc["ret"].setdefault(tuid, _ts_epoch(o.get("timestamp") or "") or float("inf"))
    ```
    This replaces `.add`.
  - `parse_agents`, hs branch: build FRESH `nts_u`/`ret_u` dicts by max-merging every `accs` entry, never `.update` a cached one. Then:
    ```python
    fin = max(nts_u.get(aid, 0.0), ret_u.get(e["tuid"], 0.0) if e["tuid"] else 0.0)
    running = aid not in stopped_u and e["last_msg_ep"] > fin and e["last_msg_ep"] >= hs - 1
    ```
    `waiting`, `done`, `end_ep`, `state` and `waiting_on` stay as v3 wrote them.
  - Validation: re-running with this rule (`rr_v31live.py` / `rr_v31all.py`, 20:36 local) gave 6/6 fan agents matched, 0 extra live agents on the 7 job sessions, and 1 plausible running agent (idle 0 min) on the 4 non-job live sessions. By the timeline above, it also gives the right answer for the adea15293 window (running from 14:42:22 to 14:47:08).
- **Tests (tests/test_agent_map.py `TestBackgroundHold`):**
  - Change the plan's `notify(*ids)` helper to `notify(off, *ids)`, writing `{"type": "queue-operation", "operation": "enqueue", "timestamp": _iso(off), "content": …}`. Without a timestamp, under R1 it closes nothing.
  - **NEW `test_woken_agent_is_running_until_renotified`:**
    - Sidecar a1 rows: `_msg(_iso(-1900),"start")`, `_stop(_iso(-1600))`, then a user `_msg(_iso(-900), "The coordinator sent a message while you were working: go", role="user")`.
    - Call `notify(-1500, "a1")`.
    - Expect "running" (red on v3: "done").
    - Then `notify(-800, "a1")` → "done".
    - Variant b, in a fresh fixture: the wake is at -300, and main holds only `notify(-1500, "a1")` plus `{"type":"queue-operation","operation":"remove","timestamp":_iso(-100),"content":<the same notification>}`. Expect "running". It is red if `remove` rows count.
  - **NEW `test_resumed_host_agent_woken_after_restart_is_running`:**
    - `self.host(-600)`. Sidecar started at -1900, notified at -1500, woken at -300.
    - Expect "running" (red on v3: the `started` gate).
    - Then `host(-200)` → "done" (the `last_msg_ep >= hs - 1` gate).
  - **CHANGE** every v3 test that calls `notify` to pass an offset later than the agent's last row. `test_sync_spawn_result_ends_agent_async_does_not` keeps its halves: the completed result at -1000 is later than the last sidecar message at -1900, so "done"; async gives "running".
  - **EXTEND** `test_union_never_mutates_cached_agent_sets` so it also snapshots the `nts` and `ret` dicts.

**R2 LOW (subsumed by R1) — nested async spawns read as "returned" on older sidecars**
- **Repro (`rr_nest4.py`, 600 sessions):** a nested async spawn's result row in the parent sidecar had `toolUseResult` absent, with text "Async agent launched…". This occurs 49 times between 2026-07 and 2026-10, including 8 in the live session 985e4755. In 2026-11 it is a dict in all 9 cases.
- Under v3's set rule, `None != "async_launched"` puts the tuid into `ret`, and the agent is "done" from launch.
- **Direction:** no separate change. Under R1, `fin` is the spawn-result epoch, about 1 s after launch, and the agent's later messages exceed it, so it reads "running" until it notifies.
- **Test:** none beyond R1. Document in §0 that sidecars before 2026-11 omit `toolUseResult`.

**R3 LOW — a woken agent's empty pane says "(no output yet)"** (`ext_cr_dialogs.js:2981` `emptyText: node.state === 'done' && …`)
- For a waiting row, the agent's own turn is finished, yet it reads "(no output yet)".
- **Fix:** change it to `node.state !== 'running' && !(detail && detail.running)`.
- **Test:** in `tests/test_cr_agent_map_ui.py` next to `OUT.empty_done` (line 121), add `OUT.empty_waiting = agentPaneModel(row('a', { state: 'waiting' }), { tail: '' }).emptyText` and assert `'No text output'`. It is red before the fix.

**R4 LOW, no change — known gaps to document in the PR:**
- **(a)** A notification-shaped string *quoted* in a tool input or text (Plan v3 §0 itself quotes one with a real aid) is read by the raw-line check. Base already behaves this way for shells. Under R1 it closes an agent only if the quote is newer than the agent's last message.
- **(b)** `stopped_u` is not time-ordered, so an agent that is TaskStopped and later SendMessage-woken stays "done".
- **(c)** The "waiting" half of the 6/6 `v3live.py` match is self-referential. The expected state is computed from the tracker's own `open_by`, because fan shell rows carry no owner (`{id, kind, label, startedAt}`). Only running and done were checked against Claude Code.
- **(d)** In the classic UI (app.js:1952/1963 chips and the legacy panel), a waiting agent counts as finished, and the panel can say "all finished". Decision 2 accepts this.

### Attacks that held (v3 is right)
- **Sync and foreground agents mid-call:** there is no result yet, so the tuid is not in `ret`, so the agent is running. 130 top-level sync agents have a `completed` result and no notification, and `ret` covers them. All statuses on Agent results (`rr_status.py`, every transcript) are only `async_launched` or `completed`, plus str errors. There are no other variants. The tool name is always `Agent`.
- **Nested sync agents (84, spawnDepth 2):** the parent-sidecar result has no `toolUseResult`, so `ret` applies and they are done. Correct.
- **Agents with no `toolUseId` (11):** all date from May 2026 with dead hosts, so they are irrelevant.
- **Stuck "running" plausibility** (`rr_live.py hist 120`, hs = session start, now = transcript mtime): 2 of 1628 agents were idle for more than 60 min. Both had no notification, and their main transcript had **no rows after the agent ended**, so the host was dead and `hs` None makes them done in production. There are no stuck agents on the 11 live hosts.
- **DBG reversal:** confirmed by `rr_dbg.py` over the 1500 newest sessions plus sidecars, covering foreground Bash results whose text contains a harness sentence:
  - 655 have dict `toolUseResult` with `backgroundTaskId` (504 at line start, 151 mid-text, all unaffected);
  - **140 have `toolUseResult` None** (131 at line start and **9 mid-text after interim output**). `.match` would lose those 9;
  - **0 have str or list** `toolUseResult`.

  So `tur is None` keeps every real shell, and it changes behaviour only for the str-error phantom. The planner's 9-shell claim is exact.
- **Consumers:**
  - No SPA path switches exhaustively on agent `state`. The only `state` readers are `agentMapModel`/`nodeEl`/the pane (2907/2926/2931/3055/3064/2981; R3 covers 2981) and the boot cache key.
  - `ext_cr_board.js:422` `RANK[a.state]` is the *session* state.
  - overview.py:57, app.js `checkCompletions`/chips and ext_cr_detail.js 712/962/2466 read `running` only.
  - Auggie emits `agents_bg: []` (auggie.py:502/774, augment_ext.py:276).
- **Decisions 2–4:**
  - The toast fires on running→waiting. Under R1 it fires again on woken→done, mirroring Claude Code's second notification.
  - The freeze of `dur_s`/`end_ep` is fine.
  - The header text appears only when W>0.

  No regressions.
- **Overbuilding:** none found. The edits are bounded by the user's decision (`waiting_on`, two dot classes, counts). The 6 h fallback was correctly left out.

### Plan v3.1 amendments
1. **R1:** in `_bg_acc`/`_bg_line`, add the `nts` dict (timestamped, non-`remove` rows only) and turn `ret` into a dict of epochs. In `parse_agents`, the hs branch becomes `running = aid ∉ stopped_u ∧ last_msg_ep > max(nts_u[aid], ret_u[tuid]) ∧ last_msg_ep ≥ hs − 1`. Build fresh merged dicts. The `done` set and the shell rule stay unchanged.
2. **Tests for R1:**
   - give `notify` a timestamp offset;
   - add `test_woken_agent_is_running_until_renotified` (with the `remove`-row case);
   - add `test_resumed_host_agent_woken_after_restart_is_running`;
   - extend the cache-mutation test to `nts`/`ret`.
3. **R3:** change `emptyText` to `state !== 'running'` and add `OUT.empty_waiting`.
4. **Docs and PR:** record R2 (sidecar `toolUseResult` absent before 2026-11) and R4 (a)–(d) as known gaps. The §1 live-match table must say that "waiting" was not checked against Claude Code.
5. **Re-run after implementing:** run `rr_v31all.py` against the worktree build and include its output in the implementation log.

## Reconciliation of Plan v3 re-review (main thread, 2026-11-16)
| # | Finding | Verdict | Action |
|---|---|---|---|
| R1 | Woken or resumed agents show as done (notification treated as permanent) | **confirmed**: live repro adea15293 on 8b05c822; 277/2726 agents across 400 sessions | Apply the v3.1 rule: `running = aid ∉ stopped ∧ last_msg_ep > max(last notify, sync-return) ∧ last_msg_ep ≥ hs−1`. Notify times come only from timestamped rows that are not queue `remove` rows. |
| R2 | Pre-2026-11 nested async spawn with no `toolUseResult` | confirmed, low | Covered by R1; no separate change |
| R3 | Waiting agent's empty pane says "(no output yet)" (ext_cr_dialogs.js:2981) | **confirmed** | `state !== 'running'` plus `OUT.empty_waiting` |
| R4 | Doc-only items | accepted | Document in the report; no code |
| v3 decisions 1–4 | DBG `tur is None` (`.search` kept); waiting is not "working"; header shows waiting only when >0; dur_s freezes | **accepted**: the re-review verified DBG on 140 shells | — |

The plan of record is now **Plan v3 + the "Plan v3.1 amendments"**. The user-visible design is unchanged from the user's second-round decision.

## Implementation log v3 (sonnet)

Implemented Plan v3 + v3.1 amendments (R1 running rule, R3 empty-pane) on top of 9e686c8. Not a server restart concern here: aitracker/** and web/** changed, so a `make serve` restart is needed to see it.

**Code.** `claude.py`: `_bg_acc` gains `nts` (task-id -> latest notification epoch; only timestamped, non-queue-`remove` rows) and `ret` (spawn tool_use id -> epoch of a non-`async_launched` result); `_bg_line` tracks Agent/Task spawns, DBG `tur is None` (`.search` kept); `parse_agents(path, hb, cost, hs, open_by)` builds fresh merged `stopped_u/nts_u/ret_u` (main + every sidecar) and applies `running = aid not in stopped_u and last_msg_ep > max(nts, ret) and last_msg_ep >= hs-1`, `waiting = not running and aid in open_by`, `state` running|waiting|done, `waiting_on`; hs None/0.0 keeps the pre-v2 rules. `parse_session` builds `open_by`. JS/CSS: `ext_cr_dialogs.js` (counts.waiting, hide/dim, subtitle, `nodeEl` dot + "waiting on shell", `emptyText` `!== 'running'`), `ext_cr_detail.js` (`groupAgentReruns` waiting, panel top list, hollow dot + tag), two `.is-waiting` CSS rules. `node --check` OK on both JS files.

**Red proofs** (scoped edit of the guarded line, test alone, restore, green again; script `~/.claude/jobs/16c95193/tmp/redproof_v3.py`):
- `waiting = False` -> RED: test_notified_owner_of_open_shell_is_waiting, test_failed_taskstop_keeps_shell_open_successful_closes, test_completion_in_main_closes_sidecar_shell, test_moved_to_background_shell_listed
- hs branch -> mtime rule -> RED: test_unanswered_foreground_bash_agent_is_running
- drop `ret_u` term -> RED; ret on every spawn result (async too) -> RED: test_sync_spawn_result_ends_agent_async_does_not (fixture tuned so a2's last message precedes its async result, else timing masks the guard)
- main-only accumulators -> RED: test_notification_in_another_sidecar_counts
- notification permanent (v3 rule) -> RED: test_woken_agent_is_running_until_renotified, test_resumed_host_agent_woken_after_restart_is_running
- queue `remove` rows counted -> RED: test_woken_agent_is_running_until_renotified
- shell_output ungated -> RED: test_shell_output_follows_host_gate
- DBG `not isinstance(tur, dict)` -> RED: test_error_exit_quoting_harness_sentence_is_not_a_shell
- union aliases cached dicts -> RED: test_union_never_mutates_cached_agent_sets (now covers done/stopped/nts/ret)
- phantom shell on no-id result -> RED: test_quoted_harness_text_is_not_a_shell, test_refused_background_launch_is_not_a_shell; Monitor counted as shell -> RED: test_monitor_is_not_a_shell
- `waiting_on` key dropped -> RED: selfcheck `_r0["waiting_on"] == []`
- JS: counts.waiting / showUp / subtitle -> RED test_waiting_agent_is_live_in_model_and_subtitle; emptyText -> RED test_pane_empty_text_by_state; dot class + meta text -> RED test_j_waiting_agent_node; panel grouping -> RED test_panel_waiting_agent_listed_not_finished.
- Not red-provable: test_shells_running B-F2 change (setUp LIVE_SESSIONS_DIR + docstrings) is a precondition/docs change, as the plan says.

**Live parity** (`unset TRACKER_AUTH; python3 -I ~/.claude/jobs/16c95193/tmp/parity.py`, extended copy `parity3.py` prints per-fan-agent state; also `rr_v31all.py`): 6/6 fan agents match. 16c95193 a1be24b39 no doneAt -> running; 82ce95d1 ab4c7f336 no doneAt -> running; 57f66536 aadeb8f45 no doneAt -> running; 82ce95d1 a9ad361b4 and afd1ab11c have doneAt and own open shells bn4u12cbj / bsh4mgoq0 -> waiting (waiting_on matches); 5849622c a9a970c51 doneAt, no shell -> done. Shell DIFFs: 16c95193 (fan bo54i8p4x) and 57f66536 (fan buht9e14s) are fan-only open shells absent from every transcript = in-flight foreground Bash, the documented known gap; 82ce95d1 fan has 3 open shells vs tracker 2 (same gap). `rr_v31all.py`: v3 match on every session, no extra live agents, no "bad" rows. Per R4, "waiting" itself was not checked against Claude Code (no fan field for it); only the fan-derived done/running/owns-open-shell expectation was.

**Known gaps recorded (R2, R4).** R2: sidecar `toolUseResult` is absent before 2026-11, so a pre-Nov nested async spawn has no `ret`; covered by the last-message-vs-notification comparison. R4 (a)-(d) doc-only items from the re-review are accepted as known gaps, no code.

**Gate:** `unset TRACKER_AUTH; make check` green, `selfcheck ok`.

## Implementation review v3 B — UI & tests (opus)

Scope: ext_cr_dialogs.js/.css, ext_cr_detail.js/.css, and the five test files at aa2d8d2. The other reviewer covers claude.py logic. Method: grep and sed ranges only. Red proofs used a scoped single-match revert through `~/.claude/jobs/16c95193/tmp/revB/rp.py` (back up, replace, run one test, restore). `git status --short` was clean afterwards.

**Verified, no defect:**
- **Red proofs re-run independently (7). All went RED and are green again.**
  - Panel `runningGroups` filter reverted to `g.running`: `test_panel_waiting_agent_listed_not_finished` failed. The row vanished entirely.
  - `emptyText` reverted to `state === 'done'`: `test_pane_empty_text_by_state` failed with "(no output yet)".
  - The map's `dimmed` waiting exclusion dropped: `test_waiting_agent_is_live_in_model_and_subtitle` failed with `dimmed: True`.
  - The `nodeEl` waiting-on meta dropped: `test_j_waiting_agent_node` failed.
  - Notification made permanent (`aid not in nts_u`): `test_woken_agent_is_running_until_renotified` failed with waiting≠running. `test_resumed_host_agent_woken_after_restart_is_running` failed with done≠running.
  - `ret_u` term dropped: `test_sync_spawn_result_ends_agent_async_does_not` failed with running≠done.
- **`OUT.empty_waiting` is not a test-only value.** The harness calls the real `agentPaneModel` (test_cr_agent_map_ui.py:129), and the string comes from ext_cr_dialogs.js:2982.
- **innerHTML safety holds.**
  - Panel: shell ids pass through `esc()` (ext_cr_detail.js:3019).
  - Map: `meta.join(' · ')` is a string child of `h()`, which becomes `createTextNode` (ext_cr_dialogs.js:39-56).
  - `setPanelCount` still receives numbers and fixed words only.
- **Consumers that bucket by state.** All of them match the plan's consumer table (Plan v3 §3):
  - The glow, the "N agents running" pill and overview read `running`. So does `paneNeedsFetch`, whose `state !== 'running'` makes waiting re-fetch like done. Waiting is not "working" for any of them.
  - Auggie emits `agents_bg: []` (auggie.py:502,774), so the new shared-shape fields cost it nothing.
- **CSS is balanced.**
  - ext_cr_detail.css: 103 `/*` and 103 `*/`; 441 `{` and 441 `}`.
  - ext_cr_dialogs.css: 35 `/*` and 35 `*/`; 249 `{` and 249 `}`.
  - With comments stripped, no stray `*/` remains. `node --check` passes on both JS files.
- **Tests are hermetic.**
  - `TestBackgroundHold` patches `LIVE_SESSIONS_DIR` to a tmpdir (test_agent_map.py:312), and `test_shells_running` does the same.
  - Every time is relative to `time.time()` (`_iso`, `host`).
  - 103 tests across the five modules: OK.

**Findings (all four parts each):**

**B3-1 LOW: the "hide finished" default for waiting is untested.**
- **Defect:** the change at ext_cr_dialogs.js:2919 (`counts.running + counts.waiting > 0`) is not pinned by any test.
- **Repro:** revert it to `counts.running > 0` and run all of test_cr_agent_map_ui + test_cr_agent_map_entry. Both stay green (RC 0).
  - The only waiting fixture (`mw`) also has a running row, so `hide` is true either way.
  - Live effect of a regression: a session whose only live agents are waiting would show every finished agent, undimmed. Waiting rows would then not stand out.
- **Direction:** test only. No code change.
- **Way:** in `_PURE_JS` next to `mw`, add:
  ```
  var mwo = agentMapModel(sess([row('w', { state: 'waiting', waiting_on: ['b1'] }), row('d')]), {});
  OUT.wo = [mwo.flags.hideFinished, mwo.hiddenCount];
  ```
  In `test_waiting_agent_is_live_in_model_and_subtitle`, assert `O["wo"] == [True, 1]`.
- **Test:** RED with the revert above, which gives `[False, 0]`.

**B3-2 LOW: the R3 fix is bypassed for a freshly waiting agent.**
- **Defect:** ext_cr_dialogs.js:2982 keeps `&& !(detail && detail.running)`. `agent_detail.running` is still mtime-based (claude.py:1977, known gap (a)). The common waiting case is an agent that just finished its turn, and its sidecar mtime is within `LIVE_WINDOW`.
- **Repro:** `agentPaneModel(row('a', {state:'waiting'}), {tail:'', running:true}).emptyText` returns "(no output yet)", but "No text output" is expected. So for the first 300 s, exactly when R3 matters, the pane still says "(no output yet)".
  - The new test passes `{tail:''}` with no `running`, so it never reaches this path.
- **Direction:** the server's `state` is authoritative for waiting (rule 5).
  - Must NOT change: the `empty_done_but_running` behaviour (state 'done' with `detail.running` gives "(no output yet)"). It covers the no-host, mtime-based path.
- **Way:** change it to `emptyText: (node.state === 'waiting' || (node.state !== 'running' && !(detail && detail.running))) ? 'No text output' : '(no output yet)'`.
  - Alternative, server-side and owned by the claude.py reviewer: make `agent_detail.running` reuse the `parse_agents` state.
- **Test:** add `OUT.empty_waiting_live = agentPaneModel(row('a', { state: 'waiting' }), { tail: '', running: true }).emptyText;` and assert "No text output" in `test_pane_empty_text_by_state`. It is RED on aa2d8d2.

**B3-3 LOW (cosmetic): two renderers word the same field differently.**
- **Defect:** for more than one shell they disagree (conventions rule 4).
  - ext_cr_detail.js:3019 always says "waiting on shell a, b".
  - The map, ext_cr_dialogs.js:3071, says "waiting on shells a, b" and omits the tag when `waiting_on` is empty. The panel would then print a bare "waiting on shell ".
- **Repro:** `_panel({agents_bg:[{aid:'w1',task:'t',running:false,state:'waiting',waiting_on:['b1','b2'],ts:1}],shells:[]})` gives "waiting on shell b1, b2", but "waiting on shells b1, b2" is expected.
- **Direction:** the panel matches the map's wording and guard. Must NOT change: `esc()` and the tag position.
- **Way:** in `agentRow`, `var wo = a.waiting_on || [];` then `(g.waiting && wo.length ? '<span class="crd-agent-wf mono">waiting on shell' + (wo.length > 1 ? 's ' : ' ') + esc(wo.join(", ")) + "</span>" : "")`.
- **Test:** in test_cr_agent_map_entry.py, add `test_panel_waiting_on_two_shells_plural`, asserting "waiting on shells b1, b2". It is RED on aa2d8d2.

**B3-4 NOTE (no change; known gap, plan-accepted in the Plan v3 §3 table):** some surfaces still treat waiting as finished. Document this in the push note.
- The classic UI's app.js:1963-2000 bg panel files a waiting agent under "Show N finished" with a "done" label. Its header reads "all finished".
- The timeline marker (ext_cr_detail.js:712) labels it "finished".
- The completion toast fires on running→waiting.
- The user decision scoped "visible, not behind Show N finished" to the Evidence panel, and the plan marked these "none". No missed-by-both item here.

**Verdict:** the UI and tests match Plan v3 + v3.1. The implementer's red-proof claims hold for every one I re-ran. Three LOW fixes remain, B3-1 to B3-3: one test-only and two one-line code changes, each with a red test. None blocks.

## Implementation review v3 A — provider (opus)

Scope: `aitracker/providers/claude.py` at aa2d8d2 only (`_bg_acc`, `_bg_line`, `_bg_tasks`, `parse_agents`, `parse_session`, `shell_output`). I started from the assumption that the implementer's report was false. Probes are in `~/.claude/jobs/16c95193/tmp/rvA3/` and were run with `python3 -I` and `TRACKER_AUTH` unset. No code edits, no stash, no process control.

### Verdict
The rule is implemented as v3.1 states it. The pre-v2 branch is byte-identical to base, caches are never mutated, and live parity is 6/6 right now. **One LOW defect (A3-1)** can leave an agent "running" for the host's whole life. It is rare: 1 case in 1500 sessions.

### Findings

**A3-1 LOW: an interrupted sync spawn that later completes stays "running" while the host lives.** The defect is at claude.py:1783, `kind, info = pend.pop(tuid)`, together with 1791.
- **Mechanism.** `_bg_line` pops the spawn's `pend` entry at its first tool_result. Any later result for the same spawn id is therefore ignored, and `ret` keeps the epoch of the first result only.
- **Live repro: c2cb9d22, agent a6552f622 (`rvA3/insp.py c2cb9d22 a6552f622`).**
  - Main transcript:
    - Agent tool_use at 04:46:25.
    - Result with str `toolUseResult` "[Request interrupted by user for tool use]" at 04:47:38.
    - A second result with dict `toolUseResult` and `status: "completed"` at 04:56:06.
  - The sidecar keeps working until 04:56:02.956 and has no notification, because it is a sync agent.
  - So `ret` = 04:47:38 and `lm` > `ret`. Under a live host it is "running" forever (actual); expected "done" after 04:56:06.
  - The host is dead today, so production shows it done.
  - Prevalence (`rvA3/multiret.py 1500`, `retgap.py 1500`): it is the only spawn with more than one non-blob result, and the only one of 265 agents with a `ret` epoch whose last message is newer than both `ret` and its notifications.
- **Fix direction.**
  - What changes: every non-`async_launched` result of a spawn id updates `ret` by max.
  - What must NOT change:
    - Bash and TaskStop `pend` entries are still popped at their first result, so shells and stops are unchanged.
    - async results still never set `ret`.
    - `ret` stays a per-file pure dict.
- **The way.** At claude.py:1783:
  ```python
  kind, info = pend[tuid] if pend[tuid][0] == "agent" else pend.pop(tuid)
  ```
  - This keeps "agent" entries alive in `pend`, which `_agent_file_pass` and `_shells_pass` already drop before caching.
  - The 1791 max-merge then does the rest. No `parse_agents` change is needed.
  - Verified in memory with `rvA3/fix_f1.py`: the whole of `tests/test_agent_map.py` plus the repro gives 63 OK.
- **Test.** Add `test_interrupted_sync_spawn_that_later_completes_is_done` to `TestBackgroundHold`. The exact body is in `rvA3/repro_f1.py`:
  - sidecar a1 (meta `toolUseId` tu1) has messages at -1900 and -1500, then a stop at -1499;
  - main has `_spawn("tu1")` at -2000, a str/is_error interrupt result at -1800, and a `{"status":"completed"}` result at -1490;
  - expect "done".
  - It is RED on aa2d8d2 (`'running' != 'done'`) and green with the fix.

### Attacks that held (no change)
- **What bumps `last_msg_ep`.**
  - Census of 300 sessions (`rvA3/census.py`): sidecar rows with a dict `message` and a timestamp are only `user` and `assistant` (128061 and 80670).
  - `api-request-blob` rows carry a `message` but **no timestamp**, so they never bump it.
  - SubagentStop and other hook rows are attachments with no `message`, which the code `continue`s past.
  - `api-request` and `progress` rows have no `message`.
  - The incoming notification lands in the *parent's* file. In a parent sidecar it is an isMeta user row, which correctly marks the parent as woken (`rvA3/sidenotif.py`: 357 of 362 are answered).
  - The 4 unanswered rows are all one event: 37184523 at 11-05T05:17, `<status>killed</status>`, the shells killed at host exit. Its host is now dead, so they show done.
  - Queue rows never have a `message`.
- **Which rows set `nts`.**
  - Notification-bearing rows are: queue enqueue/remove, attachment, user, api-request-blob (no timestamp), and api-request-shape (timestamped, but carrying only the system-prompt mention and no `<task-id>`; `rvA3/shape.py`: 0 ids).
  - `remove` is the only other queue operation, and it is excluded.
  - Agent-id statuses are completed, killed, failed and stopped, plus 10 status-less "automatically restarted from its saved transcript" rows (`rvA3/agstatus.py`, `restart.py`). A restart notification precedes the restarted agent's first row by 2.5–10.7 s, so that agent reads "done" for those seconds and then "running". This is transient. No change.
  - The "messages arrived too late … being resumed" notification is followed by the wake row in 54 ms, so it reads correctly as running.
- **hs None / 0.0 is byte-identical to 9e686c8** (`rvA3/prev2.py`, run with `AITRACKER_NO_PASS_CACHE=1` because both modules share the `claude.shells` key). Every row matched field for field except the new `waiting_on == []`, and the tail tuple matched too: 169 sessions, 5484 rows, 0 diffs, checked for both hs None and hs 0.0.
- **Caches.**
  - `stopped_u`, `nts_u` and `ret_u` are fresh containers. `waiting_on` is `list(...)`, and `mb` is a fresh pickle copy.
  - Pickle snapshots of all 148 cached 82ce95d1 entries (`bg`, `row`, `last_msg_ep`) are unchanged after 13 hs-branch parses (`rvA3/perf.py`).
  - `nts`/`ret` come only from file bytes plus `_ts_epoch`, so the keys stay pure.
  - Restarts go through `os.execv`, so no old-shape accumulator survives an Update.
- **Exceptions and invariants** (`rvA3/exc.py`): `parse_session` plus `shell_output` on the 150 newest transcripts raised 0 exceptions. Every row has a list `waiting_on`, `state == "waiting"` ⇔ non-empty `waiting_on`, and `running` ⇔ `state == "running"`.
- **Perf.** Warm `parse_any` on 82ce95d1 is 36/38/43 ms (min/median/max over 12 runs), against the A-F2 baseline of 61–150 ms.
- **Live parity, re-run now** (`parity3.py`): **6/6 fan agents match.**
  - 16c95193: 2 running.
  - 82ce95d1: a173ac831 running; a9ad361b4 waiting on [bn4u12cbj]; afd1ab11c waiting on [bsh4mgoq0].
  - 5849622c: done.
  - The shell DIFFs are only fan-only in-flight foreground ids, the known gap.
- **Live sweep of all 10 live hosts** (`rvA3/livesweep.py`). Only 4 are non-job (985e4755, 2bda7c0d, 542952d8, 2e71f77c), so 20 were not available. Those 4 have 163 agents, all done, with no implausible running.
  - The only "waiting" rows are a9ad361b4 on bn4u12cbj (72 h, `.output` untouched for 72 h) and afd1ab11c on bsh4mgoq0 (32 h). Fan also lists both shells open, so this is the accepted Plan-v1 decision 1 (no age cap), not a defect.
  - As a substitute for the missing 20, I ran a simulated live host (hs = first row) over the 300 newest sessions (`rvA3/stuck.py`): 32 running, 16 of them idle for more than 30 min. Of those 16:
    - 1 is A3-1;
    - 11 are May-2026 sidecars with no `toolUseId` (the `hs` gate closes them on any resume);
    - 4 are the 37184523 host-exit kills above.
- **`shell_output` gate.** `_host_start(basename[:-6])` never raises. A None host still returns cmd/out with `running False`.

### Residuals (document, no change)
- `ret` uses epoch 0.0 for a timestamp-less result, where the re-review's text had `inf`. No such non-blob result was found, so this is immaterial.
- A woken agent whose own notification is re-delivered late reads "done" until its next message. Not observed.

## Reconciliation of implementation review v3 (main thread, 2026-11-16)
| # | Finding | Verdict | Action |
|---|---|---|---|
| A3-1 | Interrupted-then-completed sync spawn stays running (claude.py:1783) | **confirmed, low**: 1/1500 sessions | Keep `agent` pend entries and update `ret` by max; test `test_interrupted_sync_spawn_that_later_completes_is_done` (body in tmp/rvA3/repro_f1.py) |
| B3-1 | Hide-finished default for waiting is untested (ext_cr_dialogs.js:2919) | **confirmed** | Add a red test |
| B3-2 | A just-waiting pane says "(no output yet)" for about 5 min (ext_cr_dialogs.js:2982) | **confirmed** | `state === 'waiting'` decides; red test with `{tail:'', running:true}` |
| B3-3 | Panel "waiting on shell" wording and empty guard differ from the map (ext_cr_detail.js:3019) | **confirmed** | Match the map's wording and guard; red test |
| B3-4 | Classic UI, timeline marker and toast treat waiting as finished | known gap, accepted in the plan | Document in the commit message |
| — | Missed by both | none found | — |

## Fix pass log (sonnet)
Applied A3-1 (claude.py `_bg_line` keeps `agent` pend entries), B3-1 (test only), B3-2 (ext_cr_dialogs.js emptyText: waiting decides), B3-3 (ext_cr_detail.js panel wording plural + empty guard). `node --check` ok on both JS files. Red proofs by scoped one-line revert, then restored:
- test_interrupted_sync_spawn_that_later_completes_is_done: RED with `pend.pop(tuid)` restored.
- test_waiting_agent_is_live_in_model_and_subtitle (new `wo == [True, 1]`): RED with `counts.running > 0`.
- test_pane_empty_text_by_state (new `empty_waiting_live`): RED with the old emptyText condition.
- test_panel_waiting_on_two_shells_plural: RED with the old singular wording.
Known gap B3-4 unchanged (classic UI, timeline marker, toast treat waiting as finished).
