# Agent map — plan, review, build log

Branch `worktree-agent-map` (worktree `.claude/worktrees/agent-map`), base `personal/main` @ `154147e`.
Pipeline (global CLAUDE.md rule 3): plan (opus agent) → user agreement → implement (sonnet/haiku agents) → adversarial review (opus agent) → reconcile → gate → branch-sync → push.

## Contract (verbatim)

1. > really love the agent-map in claude-code extension for the vs-code. [screenshot: VS Code "Agent map" modal — root session on the left (model · tokens in context), children on the right, each with status dot, title, elapsed, tokens] Can we get something for this app in our new control-room-UI, such that we get an entire agent map, also can we make a button or a default button for every session generated from this app, always follow 'claude.md rule of spinning up multiple agents with cheaper models such that we dont burn much in this session, name the models always', explore and tell me how can be achieve, say you are claude-code and you are building an application for yourself or your users to use it, think like that and suggest me how to do it, and how should we think
2. > I would like to have the agents and sessions and the agents tab in the screenshot to have the option to view it in the agent map like in vs code ? [screenshot: control-room detail view; "AGENTS & SHELLS" panel on the right] also make sure that you have open agent map button for the dialog box right below the main session name.
3. > tell me the correct design first and have all the open questions then lets implement the changes and run the adversial review

| # | Clause | Verdict |
|---|---|---|
| 1a | Entire agent map in the control-room UI | **discharged** — `agent-map` dialog; nested tree verified in browser (depth-2 indented with connector) |
| 1b | Button available on every session | **discharged** — header row on every session; board tiles + rail when the session has agent files |
| 1c | Cheaper models for agents, models always named | **discharged (process)** — haiku explore/gate/sweeper, sonnet build/fix/visual, opus plan/review only; model chip + model-mix header in the map |
| 2a | Agents + sessions + Agents tab can be viewed in the map | **discharged** — panel "View in agent map", per-row "map", Sessions group, Agent sessions in the map |
| 2b | "Open agent map" button right below the main session name | **discharged** — `.crd-id-row3`, verified in browser |
| 3a | Correct design + all open questions first | **discharged** — design + 11 questions asked and answered |
| 3b | Then implement | **discharged** — commit on `worktree-agent-map` |
| 3c | Then adversarial review | **discharged** — plan reviewed ×2 rounds, code reviewed (3 legs) + fix verification |

## Verified log shape (2026-10-01, probed on this machine)

- Every subagent at every depth: `~/.claude/projects/<proj>/<rootSessionId>/subagents/agent-<aid>.jsonl` + `agent-<aid>.meta.json` (flat — nested agents sit in the same folder as their parent).
- Sidecar keys: `agentType, description, model, spawnDepth, toolUseId` (2,274 sidecars; depth 1×345, 2×27, 3×7, missing×21 in a 400 sample).
- Parent link: sidecar `toolUseId` == `"id"` of an `Agent` tool_use in the spawner's transcript (root session jsonl, or another `agent-*.jsonl`). Traced a depth-2 agent this way.
- Done marker: `SubagentStop` hook attachment in the child transcript; else running if mtime within `LIVE_WINDOW`.
- Tokens: per-assistant `message.usage`; "tokens in context" = last assistant turn's input + cache_creation + cache_read + output.

## Existing code (from Explore/haiku legs)

- `aitracker/providers/claude.py:849-947` `parse_agents` → detail `agents_bg` rows `{id, aid, wf, task, last, ts, tools, running, model}`.
- `claude.py:522-555` `child_agent_sessions` → detail `agent_sessions` `{id, title, wt, running, mtime, runs}`.
- `claude.py:568-575` list dict `parentId`, `agent`.
- `server.py:401-408` `/api/agent?id=&agent=` → `agent_detail`.
- `web/ext_cr_detail.js:2634-2750` `renderAgentsPanel` ("Agents & shells"); action row `1177-1184`; Rename/Pin row `1188-1199`.
- `web/ext_cr_dialogs.js` modal system.

## Technical plan (Plan agent / opus, 2026-11-02; symbols spot-checked by main thread)

**Headline:** no new route, no new detail key. The 2s `/api/session` poll already re-parses every `agent-*.jsonl` in `parse_agents` (`claude.py:952`); add ~8 fields per row in that same pass + a sidecar read. The map is one new dialog in `ext_cr_dialogs.js`, fed live by the existing opt-in update seam (`wantsPoll` pattern, `ext_cr_dialogs.js:462/504`).

**Parent-link rule (verified on 16 roots / 646 sidecars):** depth-1 `toolUseId`s never appear in any agent file; all depth-2 (126) and depth-3 (8) resolve to an `Agent` tool_use in another agent file. ⇒ root transcript never needs scanning: "not found in an agent file" = root. 1679/1679 transcripts have a sidecar; 21 lack `spawnDepth`, 55 lack `model`; no `wf_` dirs.

### Design
- Entry points: (1) **Agent map** button in `.crd-id-row2` after `.crd-pin` (`ext_cr_detail.js:1372`), always shown, label "Agent map · N"; (2) "View in agent map" first line of the Agents & shells panel body (header is already a toggle — no nested button); (3) per-row "map" link next to "open ›" in `agentRow` → opens map focused + highlighted on that node.
- Modal `buildChrome('agent-map', …, wide)` ~1100px. Subtitle "29 agents · 3 running · 22 haiku · 6 sonnet · 1 opus · click an agent for details" (`CR.board.modelShort`). Left: root card — dot, title, "Opus 5.5 · 197.9k tokens in context" (`context.current`, `meta.model`). Right: nested `<ul>` tree, CSS-only connectors, depth ≥2 indented. Node: dot (running green / done grey / idle amber), `desc`, model chip always, "5m 38s · 85.6k tokens".
- `agent_sessions` = separate "Agent sessions" group under root (session icon, ×N runs, model, no tokens).
- Click subagent → existing `agent-transcript` drill stacked on top (`ext_cr_dialogs.js:2475`), Esc back. Click child session → close map, `ctx.go('detail', id)`.
- Empty: "No subagents in this session". Auggie: existing degraded card.
- Live: refresh every 2s while top dialog, scroll preserved; paused under a drill.

### Technical
1. `claude.py` `parse_agents` (952–1048): per file track `first_ts`, `last_usage`, `last_stop` (SubagentStop attachment ts), `last_msg_ts`, `spawned[tool_use.id]=aid` for `Agent`/`Task`. Read sidecar `af[:-6]+".meta.json"` (try/except → `{}`). Second pass adds: `parent` (str, "" = root), `depth` (int: spawnDepth → chain length, cycle-guarded → 1), `desc` (sidecar description → `task[:80]`), `type` (agentType), `model` (transcript → sidecar alias fallback), `ctx_tok` (int|None, last usage input+cache_creation+cache_read), `started`/`ended` (epoch|None; ended only if `last_stop >= last_msg_ts`), `dur_s`, `state` (done/running/idle). `running = state=="running"`. Sort + other fields unchanged.
2. `child_agent_sessions` (541–548): add `"model": sm["model"]`.
3. Auggie: `auggie.py:501,750`, `augment_ext.py:276` emit `[]` — stays valid, no code.
4. `ext_cr_dialogs.js`: `renderAgentMap(payload)` in `REGISTRY` (~2462) returning `{backdrop, panel, update, wantsSession:true}`; `open()` records `wantsSession`; `update()` gains `if (state.kind==='session' && !top.wantsSession) return;`; sid-mismatch payloads ignored. CSS in `ext_cr_dialogs.css`.
5. `ext_cr_boot.js` (~1028): after `CR.detail.update`, `CR.dialogs.update({kind:'session', sid, session:d})`. No new fetch.
6. `ext_cr_detail.js`: button markup (1372); `case "agent-map"` in click switch → `ctx.dialog("agent-map", {sessionId, session: ui.lastSession, focus, onOpenSession})`; panel top link + per-row link.

**Order:** parser + Python tests → dialogs seam + test → detail entry points → boot wiring. Restart (`make serve`) needed: parser + UI change.

**Tests:** new `tests/test_agent_map.py` (tempdir pattern of `test_agent_files.py:22–44`): root `Agent` tu_r; a1 sidecar {tu_r, depth 1, haiku} spawning tu_a1; a2 sidecar {tu_a1, depth 2} ending in SubagentStop; a3 no sidecar. Assert a2.parent=="a1", depth 2; a1.parent==""; a2.state=="done" despite fresh mtime; message after stop → running; a1.ctx_tok = last turn only; a3 parent "" depth 1 desc==task. `test_selfcheck.py` ~227: parent/depth present + Auggie `agents_bg==[]`. New `tests/test_cr_agent_map_ui.py` (node, brace-match pattern of `test_cr_dialogs_poll_broadcast_seam.py`): depth-2 under parent; `kind:'session'` refused by non-opt-in dialog, accepted by map; `data-act="agent-map"` inside `.crd-id-row2`.

**Risk:** largest session (132 agents, 170MB) → `parse_agents` already 3.88s per 2s poll today. New work is O(1)/line + 132 tiny sidecar reads. Fix = per-file memo keyed (mtime, size) incl. heartbeat contribution — separate change.

**Not verified:** foreground agents always write SubagentStop / resume appends to same file; VS Code's exact "tokens in context"; `wf_` subdirs; Auggie subagent transcripts. Out-of-scope gap: `claude.py:1541` matches only `name=="Task"`, so `Agent` dispatches miss the `agents` list.

## Open questions (plan's recommended default in [brackets])

1. Let `SubagentStop` tighten the existing `running` flag too (running pill, panel counts, completion toast fire on time)? [Yes]
2. Agent click → stacked transcript drill, or a VS Code-style details pane inside the map? [Stacked drill]
3. CR Agents & shells panel doesn't list `agent_sessions` today (only classic, `app.js:1730`) — add a "Sessions" group? [Yes]
4. Re-runs: one node per run in the map (panel keeps ×N)? [One node per run]
5. "Tokens in context" excludes output tokens, matching root `context.current`? [Exclude]
6. Big maps: show all, with a "Hide finished" toggle default off? [Yes]
7. Map button on board/rail tiles too, or detail header only? [Detail header only, always shown]
8. Auggie: degraded card, or its `agents` dispatches as status-less leaves? [Degraded card]
9. Per-file mtime cache (3.88s poll) in this branch or follow-up? [Follow-up]
10. (main thread) Fix the `claude.py:1541` Task-only gap here? [No — separate]

## Adversarial review of the plan (2026-11-02) — reviewer/opus ×2, reconciled by main thread

Both legs: **REFUTED as written**; design sound, defects below. Main thread re-checked every major claim with a short probe (settings.json hook, sidecar key counts, css/js line ranges) and confirmed `parse_agents` has no row cap (so the map is complete — examined by neither leg).

### Verdict table

| # | Finding (leg) | Verdict | Reconciled fix |
|---|---|---|---|
| A1 | `SubagentStop` row is the **user's own hook** (`~/.claude/settings.json` cc-status curl) — 539/1690 files lack it; plan's amber "idle" mis-states ~32% | **confirmed** | No marker + stale mtime ⇒ `done` (as today). `ended` = stop-group after last message, or no stop rows and sidecar `finished:true`. States: `running`/`done` only. Reviewer's extra `stopped` state **cut** (overbuilt). |
| A2 | Q1=Yes splits detail `running` vs list `bg` (`_mtime_and_bg`, contract comment `ext_cr_detail.js:950-956`) | **confirmed** | `running` unchanged (mtime only). New `state` field read only by the map. Q1 closed. |
| A3 | Stop row has no `message` key (skipped by `claude.py:987`); timestamps out of order | **confirmed** | Detect before the message check; use file order (`stop_after` flag), not timestamps. |
| A4 | Use sidecar `parentAgentId` | **overstated** — only 40/600 sampled sidecars carry it | Keep `toolUseId`→`spawned` lookup (works 100%) + guard: parent not in this session's aids ⇒ `""`. |
| A5 | `dur_s` counts resume gaps (up to ~21h) | **confirmed** | Sum active segments (first message after a stop group → next stop / now). |
| A6 | Mixed model formats; label decided in JS | **confirmed** | Server adds `model_req` (sidecar alias) + `model_label` via `util.model_label(model or model_req)`; `model` unchanged. |
| A7 | `child_agent_sessions` model stale on newer run | **confirmed** | Set `model` in create + newer-run branch. |
| A8 | Auggie `agents_bg==[]` assertion vacuous; ctx fixture weak; no broken-sidecar case | **confirmed** | Drop Auggie assertion; ctx fixture with trailing no-usage row + distinct values; bad-JSON sidecar case. |
| A9 | Root ctx uses `u.get(k,0)` (null-unsafe), drift risk | **confirmed** | One `_ctx_occupancy(u)` (`or 0`) for root + agents. |
| B1 | `.crd-id-row2` is a flex row ⇒ button beside the name, label hidden ≤900px (`ext_cr_detail.css:181,1787`) | **confirmed** | New `.crd-id-row3` between row2 and `.crd-goalline` (`ext_cr_detail.js:1373/1377`): icon + "Open agent map" + count span. |
| B2 | Panel top link makes `if (!html)` never true ⇒ Auggie degraded card lost | **confirmed** | Prepend link **after** the empty check, only if `agentsBg.length`; per-row `map` link in `agentRow`. |
| B3 | j/k switches session under an open map (no dialog guard); Auggie has no `meta.sessionId` | **confirmed** | One id source (`cur`) both sides. Reviewer's stale-banner **narrowed**: on sid mismatch the map just **closes itself** (fewer moving parts; user reopens from the header). |
| B4 | 2s repaint wipes focused node ⇒ Tab escapes trap | **confirmed** | **Narrowed** to the reviewer's minimum: remember focused `data-aid` + `scrollTop`, repaint, restore. Full keyed DOM diffing cut (overbuilt for ≤150 nodes). |
| B5 | JS model labels (`modelShort`) disagree with server label | **confirmed**, merged with A6 | Chip + header buckets read server `model_label`; bucket = its first word. No `modelShort` in the map. |
| B6 | No formatter named; plan's "85.6k" ≠ `fmtK` | **confirmed** | Export existing `fmtK`/`fmtDurMs` on `CR.detail.fmt`; no 4th formatter. Display follows `fmtK`. |
| B7 | `.cr-dialog-wide` caps 760px; colours | **confirmed** | `.cr-dialog-map` width `min(1100px, 100vw-32px)`, stack <720px, state tokens only. |
| B8 | `open()` focuses close button after builder ⇒ per-row focus lost | **confirmed** | Focus/scroll the target in `setTimeout(…,0)`. |
| B9 | `var` below REGISTRY ⇒ undefined at load; seam test brace-extracts first `function update(` | **confirmed** | Hoisted `function renderAgentMap`; inner closures named `applySession`/`paintMap`. |
| B10 | Re-open delivers detail payload shape (no `kind`) | **confirmed** | `applySession` accepts both shapes. |
| B11 | Map can't render in node harness | **confirmed** | Pure `agentMapModel(session)` + brace-extract; add `node --check` on the assembled `<script>` (closes the load-time-error gap in memory). |
| — | Pre-existing 3.3–3.9s `parse_agents` on 132-agent session | **missed by neither; deferred** | Follow-up: memo keyed by (agent mtime, size, sidecar mtime). |
| — | `claude.py:1541` matches only `Task` | out of scope | Separate change. |
| — | Classic UI (`app.js`) | out of scope (user said control room) | Note in commit. |

### Reconciled clean plan (replaces "Technical" above)

**Server — `aitracker/providers/claude.py`**
1. `_ctx_occupancy(u)` = input+cache_creation+cache_read (each `or 0`); root `context.current` (~1385) switches to it.
2. `parse_agents` (952): per file read sidecar `af[:-6]+".meta.json"` (try → `{}`); in the loop, **before** the `message` check: SubagentStop attachment ⇒ `n_stop+=1; stop_after=True; seg close`; after a message row: `stop_after=False`, `first_ts`, segment open, last usage block, `spawned[tool_use.id]=aid` for `Agent`/`Task`. Row adds: `parent` (spawned lookup, guarded → ""), `depth` (spawnDepth → visited-set chain → 1), `desc` (sidecar description → `task[:80]`), `type`, `model_req`, `model_label`, `ctx_tok` (int|None), `started`, `ended`, `dur_s` (active segments), `state` ∈ {running, done}. `running`, `model`, sort, hb unchanged.
3. `child_agent_sessions`: `model` (+ `model_label`) in both branches.
4. Auggie: no code.

**UI — `aitracker/web/`**
5. `ext_cr_dialogs.js`: hoisted pure `agentMapModel(session)` → `{root, nodes(tree by parent), sessions, counts by model_label family, running}`; hoisted `renderAgentMap(payload)` = `buildChrome('agent-map','Agent map','agent',title,true)` + `.cr-dialog-map`; left root card (`meta.model_label`, `context.current`), right tree, "Agent sessions" group; click agent → `open('agent-transcript',{sessionId, agentId})`; click session → `onOpenSession(id)`+close; `applySession` (both payload shapes; sid mismatch ⇒ close; repaint preserving focused `data-aid` + scrollTop); "Hide finished" toggle; returns `{…, update: applySession, wantsSession:true}`. `open()` records `wantsSession`; `update()` refuses `kind:'session'` unless opted in. REGISTRY entry. CSS in `ext_cr_dialogs.css` (no globs in comments).
6. `ext_cr_boot.js` (~1028): separate try → `CR.dialogs.update({kind:'session', sid: cur, session: d})`.
7. `ext_cr_detail.js`: `.crd-id-row3` button under the title, painted in renderHeader (count span only); `CR.detail.fmt = {k: fmtK, durMs: fmtDurMs}`; `case "agent-map"` → `ctx.dialog('agent-map', {sessionId: cur||ui.sid, session: ui.lastSession, focus, onOpenSession})`; panel link after empty check + per-row `map` link.

**Tests**
- `tests/test_agent_map.py` (tempdir, pattern `test_agent_files.py:22–44`): depth-2 parent; orphan/missing-parent ⇒ root; stale + no marker ⇒ done; fresh + stop-after-last-msg ⇒ done; stop→msg fresh ⇒ running; sidecar `finished` ⇒ done; `dur_s` 360 across a resume gap; ctx = last usage block (trailing no-usage row); no-sidecar + bad-JSON sidecar ⇒ defaults; `model_label` from sidecar alias; child-session newest model.
- `tests/test_selfcheck.py` ~227: `parent`/`depth`/`state` present on the existing fixture.
- `tests/test_cr_agent_map_ui.py` (node): `agentMapModel` tree; seam refuse/accept + sid-mismatch close; SKELETON button between row2 and goalline; Auggie degraded card survives; `node --check` on assembled script. Red-proof: revert guard / gate and watch (b),(d) fail.

**Sequence:** server (1–4) + `test_agent_map.py` → dialogs (5) + UI test → detail + boot (6–7) → `make check` → restart (`make serve`) for a visual check.

### Open questions after review
Closed by review: Q1 (No — map-only `state`), Q5 (exclude output; matches root). Remaining: Q2, Q3, Q4, Q6, Q7, Q8, Q9, Q10, plus **Q11**: on session switch with the map open — close the map [default] or keep it with a stale banner?

### User answers (2026-11-02, verbatim choices)

| Q | Answer | Delta vs reconciled plan |
|---|---|---|
| Q2 agent click | **Details pane inside map** | NEW — replaces stacked drill |
| Q3 Sessions group in CR panel | Yes, add Sessions group | as planned |
| Q4 re-runs | One node per run | as planned |
| Q6 big maps | **Hide finished by default** | toggle default ON |
| Q7 button spots | **Header + board/rail tiles** | NEW — tile/rail entry points |
| Q8 Auggie | Honest 'not supported' card | as planned |
| Q11 session switch | Map closes | as planned |
| Q9 per-file parse cache | **In this branch** | NEW |
| Q10 `Agent`-name gap (`claude.py:1541`) | **In this branch** | NEW |

Contract additions: clauses 4a–4d below are now in scope.

| # | Clause | Verdict |
|---|---|---|
| 4a | Details pane inside the map | **discharged** — verified in browser (facts, prompt, last output, full transcript; Esc closes pane then map) |
| 4b | Map entry on board tiles + rail rows | **discharged** — verified in browser (tile button, rail chip/button → navigate + open map) |
| 4c | Per-file parse cache for `parse_agents` | **discharged** — 132-agent session 3.5s → 0.003s warm; 0 diffs vs base on 119 real sessions |
| 4d | `Agent` dispatches reach the `agents` list | **discharged** — `("Task","Agent")` + `tool` field + timeline verb |

## Plan addendum 4a–4d (Plan agent / opus, 2026-11-02) — builds on the reconciled plan

No new route for any delta.

**4a Details pane.** `.cr-amap` grid root | tree (+ `.has-pane` 340px third column; <720px stacks). Subagent pane: row data (desc, type, model_label, state, dur_s via `CR.detail.fmt.durMs`, ctx_tok via `fmt.k`, tools) + fetched prompt (`task`, pre-wrap, fold) and **Last output** (narration tail ≤2,000 chars, cut at paragraph) + "Full transcript" → existing `agent-transcript` drill (`ext_cr_dialogs.js:2475`). Session node: title, wt, model_label, running, ×N + **Open session** (`onOpenSession`+close). Root click clears selection. Data: existing `cr:drill-request` → `ext_cr_boot.js:544–571` → `/api/agent` → `agent_detail` (`claude.py:1248`); boot gains `payload.reply==='agent-map'` ⇒ `CR.dialogs.update({kind:'agent-detail', sid, aid, detail|error})`; `update()` accepts `agent-detail` under `wantsSession`. Refetch rule pure `paneNeedsFetch(sel,node,cache,nowMs)`: selection, not in-flight (10s timeout), and (no cache OR running ∧ row ts changed ∧ ≥6s since fetch). Esc: `onDocKeydown` (`:353`) calls `top.onEscape()` first; map's closes pane. Pure `agentPaneModel(node, detail)`. Tests: paneNeedsFetch cases, tail trim, agent-detail seam refuse/accept, first Esc keeps map.

**4b Tiles + rail.** List dict gains `agents_n` via `_mtime_bg_n(path)->(m,bg,n)` (same glob); `_mtime_and_bg` stays a 2-tuple wrapper (`test_selfcheck.py:145`); Auggie (`auggie.py:374`, `augment_ext.py:198`) `agents_n: 0`. `railRow` (`ext_cr_board.js:1909`, actions ~2087–2101) + `sessionTile` (~2815, append like Resume ~2840) get `glyph('agent')` button when `agents_n`, `stopPropagation` (tile click guard `tileBaseAttrs` 2628 already ignores buttons). Click: `openSession(s.id)` then `ctx.dialog('agent-map',{sessionId:s.id, session:null})` → "Loading agents…" until first EXT tick (`app.js:1476` drops stale). Tests: list `agents_n` 2 / Auggie 0; JS button only when >0, click fires go+dialog not tile activation.

**4c Parse cache.** Extract loop body (`claude.py:964–1043`) to `_agent_file_pass(af)->entry` {row_static, hb parts, files, prs, pr_states, spawned, segs, ctx_tok, sidecar}; `_AGENT_CACHE[af]=(key,entry)`, key `(st_mtime_ns, st_size, sidecar_mtime_ns|0)`. Merge in `sorted(af)` order replicating today's semantics (hb extend; files ops sum / created OR / last overwrite; prs OR+max t; pr_states merged-wins). Time-derived fields computed post-merge from `now`, never cached. Hand out `dict()` copies. `ThreadingHTTPServer` (`server.py:813`) ⇒ `_AGENT_CACHE_LOCK` around get/set only; cap 4,000, drop oldest half. Measure cmd recorded; baseline 3.88s, target <0.1s warm. Tests `tests/test_agent_cache.py`: warm call opens 0 files; touched file re-read once; cold==warm deep-equal incl. hb; returned-row mutation doesn't leak. Fallback: env kill-switch.

**4d Agent-name gap.** 150 newest roots: 1,597 `Agent`, 0 `Task` dispatches ⇒ `agents`, `counts.agents` (`claude.py:1697`), overview "dispatched N sub-agent(s)" (`overview.py:58`), CR timeline (`ext_cr_detail.js:794–797`) all empty today. Fix `claude.py:1541` `name in ("Task","Agent")`, row `"tool": name`, `model` stays ""; timeline `verb: a.tool || "Task"`. Only other site `overview.py:75` already has both. Test: root with an `Agent` tool_use ⇒ agents 1, counts 1, overview text.

**Q6 follow-on.** Hide-finished ON keeps ancestors of running nodes (dimmed); empty ⇒ "No agents running · N finished hidden · [Show finished]"; focus/selected finished node forced visible with ancestors; toggle per-open, resets ON. Tests in agentMapModel.

**Sub-decisions (defaults):** S1 Last output = narration tail only; S2 tile/rail button only when `agents_n>0`; S3 no cache for `agent_detail`.

**Sequence:** (1) claude.py: `_ctx_occupancy`, 4d, extract `_agent_file_pass` + cache, then new row fields inside it, child-session model, `agents_n` (+Auggie 0) → (2) Python tests, `make check` → (3) ext_cr_dialogs.js models + map + pane + seams + CSS + UI test → (4) ext_cr_boot.js → (5) ext_cr_detail.js → (6) ext_cr_board.js → (7) `make check`, re-measure, `make serve` look, code adversarial review.

## Adversarial review of the addendum (reviewer/opus ×2), reconciled by main thread

Main thread re-checked: `agent_detail` narration is `[:40000]` head (`claude.py:~1284`); boot drill handler has 5 `dialog(` calls (`ext_cr_boot.js:540–575`); rail chip `cr-rail-badge--bg` exists (`ext_cr_board.js:~1236`); `fe["last"]=last_ts` overwrites in file order (`claude.py:~1013`); `prs[url]=ae` aliases the agent PR object (`claude.py:~1608`).

| # | Finding | Verdict | Reconciled fix |
|---|---|---|---|
| C1 | cold==warm test is self-referential; `last` is overwrite-by-later-file, not max | **confirmed** | Golden test `test_agent_cache.py::test_golden_vs_base` written + green on base BEFORE refactor; preserve today's semantics exactly. |
| C2 | Cached nested objects mutated (`prs[url]=ae`, `prs_sorted` writes state, `fe["ops"]+=1`) | **confirmed** | Cached entries frozen; merge into fresh accumulators (`dict()` on first sight); hb lists only `extend`. Test: two `parse_session` calls identical; cached PR has no `state`. |
| C3 | `parent`/`depth` cross-file; hb gated on `hb is not None` | **confirmed** | `_agent_file_pass` always collects hb into a local dict; `row_static` excludes parent/depth/running/state/dur_s; resolve post-merge from all `spawned`. Test: `parse_agents(p)` without hb then `parse_session(p)` keeps hb; parent file sorting after child. |
| C4 | Eviction keeps original insertion position; cap | **confirmed** | `pop` before set; evict under lock on `list()` snapshot; cap 2,000. |
| C5 | Comment at `claude.py:~1544` becomes false | **confirmed** | Reword (Agent input carries the requested alias). |
| C6 | `agents_n` counts only agent files; name collides with hb `agents_n` (`overview.py:172`) | **confirmed** | Rename list field **`agent_files_n`**; document that SDK-only child sessions get no tile button. |
| — | Target scope | clarified | `<0.1s` warm is for `parse_agents`; `/api/session` ~0.5s warm (root transcript uncached). |
| D1 | "Last output" = tail of the first 40k chars (226/1,500 agents >40k) | **confirmed** | `agent_detail` adds `tail = j[-4000:]` (and `""` on not-found); pane reads `tail`. |
| D2 | Refetch rule misses the final report (running→done) | **confirmed** | `need = !c || (c.ts!==node.ts && (node.state!=='running' || now-c.at>=6000))`. |
| D3 | Global in-flight flag blocks other selections; out-of-order replies | **confirmed** | Per-aid `inflight{aid:{at,seq}}`; `seq` echoed via boot; keep reply only if `seq > cache[aid].seq`. |
| D4 | Drill handler has 3 exits (success / d.error / .catch) — error paths would pop a drill over the map | **confirmed** | One `toMap` gate; `out()` routes all three to `CR.dialogs.update({kind:'agent-detail',…})`; never `dialog()` when `toMap`. |
| D5 | 2s repaint wipes the pane | **confirmed** | Tick repaints the tree only; pane re-renders when `aid|seq|ts|state` key changes. |
| D6 | Hide-finished + tile button ⇒ empty map for idle sessions | **confirmed — deviates from user's Q6 literal** | Default `hideFinished = (running > 0)`; covers Agent-sessions group too; toggle per-open. Flagged to user as overridable. |
| D7 | Rail already has an agent chip ⇒ double glyph; no CSS for new buttons | **confirmed, fix narrowed** | Chip `cr-rail-badge--bg` retargeted to `openMap(s)`; new `cr-rail-map` button only when the chip isn't shown (`agent_files_n>0 && !bg`). Add to `ext_cr_board.css` selector lists (~1058–1084); tile button mirrors `.cr-tile-resume` (~1765–1784). |
| D8 | Esc seam specifics | **confirmed** | `open()` copies `onEscape`/`wantsSession` explicitly; `onEscape()===true` ⇒ handled; focus `[data-aid=sel]`. |
| D9 | j/k switch sessions under an open dialog | **confirmed** | Guard j/k in `ext_cr_detail.js:~2056` when a dialog layer is open. Map close-on-sid-mismatch kept as safety. |
| D10 | Session-node pane is overbuild | **confirmed** | Session node click opens the session directly (no pane). |
| — | Pane text rendering | checked fine | Plain text node `h('pre',{class:'cr-outputtext'},[text])` like `renderDiffPopout`; never `html:`. |

## FINAL BUILD SPEC (authoritative = Reconciled clean plan + Addendum + the two review tables above)

Where they conflict, the later table wins. Field names fixed: agent row `parent, depth, desc, type, model_req, model_label, ctx_tok, started, ended, dur_s, state` (+ unchanged `id, aid, wf, task, last, ts, tools, running, model`); `agent_sessions` row + `model, model_label`; list dict `agent_files_n`; `agent_detail` + `tail`; detail `agents` rows + `tool`. Dialog name `agent-map`; payload `{sessionId, session, focus, onOpenSession}`; update kinds `session` `{sid, session}` and `agent-detail` `{sid, aid, seq, detail|error}`; `CR.detail.fmt = {k, durMs}`.

## Build log

**Wave 1 (3× sonnet, parallel, disjoint files) — 2026-11-02**
- **S server** (`claude.py`, `auggie.py`, `augment_ext.py`): golden test frozen from base first (green before + after); `_ctx_occupancy`; 4d `("Task","Agent")` + `tool`; `_agent_file_pass` + `_AGENT_CACHE` (lock, pop-before-set, cap 2000, kill-switch `AITRACKER_NO_AGENT_CACHE=1`); new row fields (`started`/`ended` are ISO strings like `ts`; open segment ends at `now` if running else last message); `child_agent_sessions` model/model_label; `_mtime_bg_n` + `agent_files_n` (Auggie 0); `agent_detail.tail`. Tests: `test_agent_map.py` 22, `test_agent_cache.py` 8, selfcheck line. Red-proofs: aliasing, stop detection. **`parse_agents` 132-agent session: 3.554s cold → 0.002–0.003s warm.**
- **M dialog** (`ext_cr_dialogs.js/.css`): hoisted `agentMapModel`, `agentMapSubtitle`, `agentPaneModel`, `paneNeedsFetch`, `renderAgentMap`; seams `onDocKeydown`/`open`/`update`; REGISTRY `agent-map`; CSS. Test `test_cr_agent_map_ui.py` 12 (+ seam test 6 green), incl. `node --check` of the assembled script. Red-proof: update() guard. DOM rendering not exercised by tests.
- **E entry points** (`ext_cr_boot.js`, `ext_cr_detail.js/.css`, `ext_cr_board.js/.css`): drill `toMap` gate on all 3 exits; session broadcast (sid = `meta.sessionId || d.id`); `.crd-id-row3` "Open agent map · N"; `CR.detail.fmt`; `case agent-map`; panel link + per-row map; Sessions group; timeline verb; j/k guard; board `openMap`, chip retarget, `cr-rail-map`, `cr-tile-map`. Test `test_cr_agent_map_entry.py` 8. Red-proof: `.catch` gate.

**Wave 2 (parallel):** full gate (gate-runner/haiku, per module) + code review R1 server / R2 dialog / R3 entry+contract (reviewer/opus ×3).

- **Gate:** 91/92 modules green, `selfcheck ok`. FAIL `test_icons::test_no_icon_svg_rule_hardcodes_a_px_width_without_ico_scale` — new `.crd-mapbtn .crd-ico` rule (`ext_cr_detail.css:209-210`) hard-codes 14px; fails in isolation (not flaky).
- **R1 server — HOLDS.** Base vs new `parse_agents` on all 119 real sessions / 1,730 agent files, cold + warm: 0 diffs on old fields/files/PRs/hb. Golden literals == base output.
- **R2 dialog — REFUTED** (ran the real closure on a fake DOM). **R3 entry/contract — REFUTED narrowly** (Claude path works end-to-end; drill contract matches).

### Code-review verdict table (main thread)

| # | Finding | Verdict | Fix |
|---|---|---|---|
| R2-F1 | Cache stores reply-time `ts` ⇒ running→done during an in-flight fetch never refetches the final report (reproduced) | confirmed | `inflight[aid]={at,seq,ts:node.ts}`; store `ts: reqTs` from the matching inflight. |
| R2-F2 | Focus restore only by `data-aid` ⇒ toggle/session rows/pane buttons lose focus every tick, Tab escapes trap | confirmed | `focusKey(el)` = data-aid ‖ data-sid ‖ data-act; pane buttons get data-act; restore with `preventScroll`, else focus panel. |
| R2-F3 | Restore calls `scrollIntoView` ⇒ tree jumps back each tick | confirmed | `focusNode(aid, scroll)`; restore path passes false. |
| R2-F4 | Pane `<pre>` scroll resets on every key change | confirmed | Save/restore pane + `.cr-amap-text` scrollTop by index. |
| R2-F5 / R3-F3 | Error reply ⇒ "Loading…" forever + refetch every tick | confirmed (both) | Cache `{ts:reqTs, at, seq, error}`; `agentPaneModel` shows "Couldn't load: …", `loading:false`; 10s backoff holds. |
| R2-F6 / R3-F1 | Auggie/Augment detail has no id ⇒ map opens with previous Claude sid, close-on-switch never fires (spec B3 not done) | confirmed (both) | Boot: `sid = cur ‖ meta.sessionId ‖ d.id` for the dialog tick AND passed to `CR.detail.update({…, sid})`; `renderUpdate` prefers `state.sid`. |
| R2-F7 / R3-F4 | Tests stay green with key behaviour removed | confirmed | Fake-DOM harness test for the map (F1, F2, F5, sid-mismatch close, map onEscape); boot tick sid test; j/k guard test. |
| R2 gaps | Root click doesn't clear selection; `buildChrome(... wide=false)` | confirmed (trivial) | Fix both. |
| R3-F2 | Sessions-only panel has no map link; count omits sessions | confirmed | Gate link on `agentsBg.length ‖ aSess.length` (after `if(!html)`); count includes sessions. |
| R1-F2 | Cache key ignores sidecar size (Linux mtime granularity) | confirmed | Key uses `(sidecar mtime_ns, size)`; same-length rewrite test. |
| R1-F1 | Unreadable agent file drops out of `newest` | accepted known gap, **no change** | Broken files only; session mtime still from `_mtime_bg_n`. |
| R1-F3 | Two-agent parent cycle from corrupt sidecars | **false alarm for UI** | `agentMapModel` already puts cyclic parents at root. No change. |
| Gate | `test_icons` px rule | confirmed | Use the icon-scale var pattern the test requires. |

**Wave 3 fixers:** Fix-D (sonnet) dialog file + UI test; Fix-E (sonnet) boot/detail/css + entry test + test_icons; Fix-S (sweeper/haiku) cache key + test.
- Fix-S: reviewer's "same-length rewrite" test was untestable by any stat key (size and mtime both unchanged); replaced with `test_sidecar_growth_within_same_mtime_invalidates` (the real case: sidecar grows in place). Red under the old key. `ponytail:` comment records the same-length ceiling.
- Gate after fixes: 91/91 + selfcheck ok. **Fix verification (reviewer/opus): 11/13 HOLD**; 2 new — V-F1 panel fallback focus no-op (no tabindex) and V-F2 errored done agent never retries — fixed (`tabindex=-1`; error retry after 10s) with red-proven tests, plus a `renderUpdate` `state.sid` test.

**Wave 4 — ship**
- Commit `c3c93c0` (hook gate green). `personal/main` had moved 5 commits (session isolation); rebase conflicted in `ext_cr_boot.js`, `ext_cr_detail.js`, `ext_cr_dialogs.js` — resolved by sonnet keeping both sides (map drills go through upstream's stale-sid guard; upstream's `renderUpdate` sid order kept; entry test stubs moved to `sessJSON`). Post-sync gate: **92/92 + selfcheck ok**. Pushed `worktree-agent-map` to `personal`.
- Visual check (Chrome, sonnet, port 8797): button directly under the title; map, pane, Esc, panel links, tile/rail buttons, 132-agent map all PASS; depth-2 agent drawn indented with └─ connector; no console errors. A first re-check stalled on "Loading session…" only because the browser ran rebased JS against the pre-rebase server — restart fixed it.

**Known gaps / follow-ups (not in this branch)**
- Pane says "(no output yet)" for a finished agent that wrote no text (narration 0) — should read "No text output" when `state==done`.
- Upstream (on `personal/main`, untouched here): `dialogs.closeSession` throws `_layer` null `setAttribute` when switching sessions in the classic UI before any dialog opened; boot catches it.
- R1-F1: an unreadable agent file no longer contributes to `newest` (broken files only).
- `agent_files_n` counts agent files only — a session whose only agents are SDK child sessions gets no tile/rail button (header button + panel still work).
- Classic UI has no agent map (scope was the Control Room).

## Follow-up round via /tracker-gap (user: "implement the plan with /tracker-gap and then /tracker-push")

Plan (Plan agent / opus); integrator accepted as written; product call: tile/rail count includes grouped child sessions (matches header).
- **G1** no-text label — client only: `agentPaneModel` gains `emptyText` = "No text output" when `node.state==='done' && !(detail&&detail.running)`, else "(no output yet)"; `paintPaneBody` uses `pm.lastOutput || pm.emptyText`. Real case: aid a7e85fae652a1bb54 (only text block is the prompt). Tests: pure `test_pane_empty_text_by_state` + fake-DOM `test_i_done_agent_without_text_says_no_text_output`.
- **G2** SDK-child-only sessions get map entry — `parentId` exists only inside `fs[:limit]`, so count children in a `list_sessions` pre-pass over ALL `fs` (`_pick_parent` reused via `parent_of[f]`), keyed by new `_child_key(fid, sm)` shared with `child_agent_sessions` (re-runs collapse identically). Claude row `agent_sessions_n`; seam `registry.all_sessions` backfills `agent_files_n`/`agent_sessions_n` = 0 and sets `agent_map_n` = sum (Auggie inherits). Board gates/aria read `agent_map_n`. `ponytail:` ceiling: same-dir `_pick_parent` heuristic. Tests: selfcheck orchestrator fixture; new `tests/test_agent_map_children.py` (outside-window child, re-run collapse, registry sum/backfill, Auggie 0); entry-test strings flipped first. Risk: `/api/list` hot path — time before/after.
- **G3** unreadable file → `newest`: `_agent_entry` returns `(mt, entry|None)`; `parse_agents` advances `newest` before the None check. Test: directory named `agent-zzz.jsonl` newer than the real file; cold/warm/kill-switch. Eval: list row mtime == detail mtime.
- Out of scope noted: non-UTF-8 agent file raises (`UnicodeDecodeError` not caught at ~1084) — same as base.

**Result:** implemented by 2× sonnet (server G3+G2; client G1+G2 board), tests red-first. Gate (haiku): every module green + `selfcheck ok`. `/api/list` warm 0.16–0.24s vs 0.26s before; `parentId` byte-identical on 1,006 real sessions. Adversarial review (opus): **HOLDS** — 1 minor confirmed: same session id in two project dirs summed both dirs' children ⇒ fixed by keying `child_keys` on `(project dir, parent id)` (sweeper/haiku; `test_same_id_in_two_dirs_counts_per_dir` red 2≠1 → green). Evidence gap noted: no real parent with SDK children on this machine — G2 equality proven by synthetic tests + selfcheck fixture; 0 list/panel mismatches on the full real list.

| # | Clause | Verdict |
|---|---|---|
| G1 | "No text output" for a finished agent with no text | **discharged** |
| G2 | Tile/rail map entry for SDK-child-only sessions (`agent_map_n`, every provider) | **discharged** |
| G3 | Unreadable agent file still advances `newest` | **discharged** |
