# Heartbeat panel — replaces the Progress spine

Branch `worktree-heartbeat-panel` (worktree `.claude/worktrees/heartbeat-panel`), based on `594ac65`.

## Contract (verbatim, 2026-10-29)

> I would like to replace this progress spin with a heartbeat type feature where we can monitor and
> analyse where the spends the computation and other parts/pieces went in majorly. Also make that a
> collapsible item in the screen

> read claude.md rule of spinning up multiple cheaper agents such that we dont burn much in this session

Plan-review answers (2026-10-29), verbatim:

> [cost $?] make it a config switch to flip between progress spine and the heartbeat. Also make sure
> that you have made the heartbeat as default
> [delete spine?] separate config to flip between spine and the heartbeat, both spine and heartbeat
> needs to be collapsible panel
> [approve?] once the plan is ready do an adversial review for the same with opus and then if you find
> any issues ask the same opus model to come up with a better plan and review it

| Clause | Verdict |
|---|---|
| Heartbeat replaces the spine **by default**; spine kept behind a Config switch | not discharged |
| Both spine and heartbeat are collapsible panels | not discharged |
| Opus adversarial review of the plan; if issues, same opus writes + reviews a better plan | not discharged |
| No $ cost (answer replaced it with the switch) — tokens + wall time only | assumed |
| Fix the inflated `tokens` totals everywhere (message.id dedup), not just in the heartbeat | not discharged |
| Opus review of plan + DESIGN (round 2) before implementing | discharged — FINAL plan + Design spec + Reconciliation below |
| Implement via `/tracker-gap` | not discharged |
| Opus adversarial review + design round after implementing; iterate until clean | not discharged |
| Push via `/tracker-push` once clean | not discharged |
| Work in a separate worktree branched from latest default (`main`) | discharged — `worktree-heartbeat-panel` from `594ac65` |
| Run `/branch-sync` in the worktree right before pushing | not discharged |
| Encode "worktree + branch-sync before push" in CLAUDE.md, `tracker-gap`, `gap` | discharged — CLAUDE.md rule 5; gap Step 0 (L25); tracker-gap Step 0 (L71) + Rules (L170) |

Second answers (2026-10-29), verbatim:
> [token fix] Fix everywhere (Recommended)
> [build?] review the plan + design with opus then implement it with /tracker-gap and then do another
> round of adversial review + design with opus and once clean push the changes using /tracker-push
| Heartbeat: monitor where computation went (tokens/time over time) | not discharged |
| Analyse the major parts: by tool, by subagent, by model | not discharged |
| Collapsible item | not discharged |
| Cheap agents (haiku/sonnet; opus only for review) | in progress |

## What exists (mapped by 2 haiku Explore agents)

- `providers/claude.py` `parse_session` reads `message.usage` per turn (L1253-1259) but only sums it
  into `tokens`; `message.model` latest only (L1261); tool_use names L1333-1345 (no per-tool counter);
  tool_result timing not read; `parse_agents` (L849-950) reads subagent files but not their `usage`.
- `providers/auggie.py` `parse_auggie` reads `token_usage` per exchange (L589-599), one timestamp per
  exchange (`finishedAt`), no per-tool timing.
- Spine: `web/ext_cr_detail.js` 327-~545, 1263-1281 (markup), 1470-1530 (pan), 1655-1674 (clicks),
  1962-1966, 1984, 2251-2420, exports 3353-3356; CSS `ext_cr_detail.css` 544-837, 1852-1856, 2060-2063.
  Keyframes 838-921 shared with the Now card (`.crd-seg-dot`) — keep.
- Collapsible chrome to reuse: `makePanel` 1095-1112, `setPanelCollapsed` 1114-1119, persistence
  `cr.detail.panel.<sid>.<key>` (277-286).

## Technical plan (v1 — SUPERSEDED by "Revised plan (opus)" below)

### Shape (shared detail dict, both providers) — `session["heartbeat"]`
```
{ "span": [t0, t1],                     # epoch s
  "beats": [{"t": s, "tok": n, "out": n, "calls": n}],   # <=60 equal time buckets
  "by_tool":  [{"name": "Bash", "calls": n, "ms": n|None}],   # sorted by ms then calls
  "by_agent": [{"label": "main"|desc, "model": m, "tok": n, "out": n}],
  "by_model": [{"model": m, "tok": n, "out": n}],
  "total": {"tok": n, "out": n, "calls": n} }
```
`tok` = input + cache_read + cache_creation + output (what the turn processed); `out` = output.

### Server
1. `aitracker/overview.py`: `build_heartbeat(turns, tools, agents, n=60) -> dict` — pure, shared.
   `turns=[(t, model, tok, out, [tool names])]`, `tools={name: [calls, ms|None]}`,
   `agents=[(label, model, tok, out)]`. Bucketing lives here (server owns policy).
2. `providers/claude.py` `parse_session`: at L1253 append a turn tuple; in the tool_use loop record
   `id -> (name, t)`; on tool_result entries add `t_result - t_use` ms to that name. `parse_agents`:
   sum `usage` per subagent file onto the `agents_bg` entry (`tok`, `out`). Call `build_heartbeat`
   next to `result["overview"]`.
3. `providers/auggie.py` `parse_auggie`: per exchange turn tuple from L589; tool names from the
   exchange's tool nodes, `ms=None`; `sub-agent-*` calls as agents with no tokens. Degraded path → empty.
4. `tests/`: one assertion per provider on `heartbeat` (totals = `tokens`, bucket count, by_tool).

### Client (`web/ext_cr_detail.js` + `.css`)
5. **Keep the spine**, but give it panel chrome: a chevron header (`data-act="toggle-panel"`,
   key `spine`) with the existing head content, body = the existing scroll/bar/gutter/foot. Collapse
   persists via `getCollapsed/setCollapsed` (`cr.detail.panel.<sid>.spine`). Overrides the old
   "no `crd-spine-chevron`" pin in `test_cr_spine_window.py` (user ruling).
5b. **Switch:** localStorage `cr.progressView` = `"heartbeat"` (default, also when unset/garbage) |
   `"spine"`. `ext_cr_dialogs.js`: add `progressView` to `CFG_PREF_KEYS` (~L821, so Reset clears it)
   and a `segmented([['heartbeat','Heartbeat'],['spine','Progress spine']], …)` row next to "Cards
   start folded" (~L1250). `ext_cr_detail.js` `renderUpdate` reads it each render and toggles
   `hidden` on the two panels; only the visible one is rendered (skip `renderSpine` when hidden).
   Client-only view pref, same class as `cr.cardsFolded` — no server config key.
6. Next to it, `makePanel(..., "heartbeat", "HEARTBEAT", ...)` — same collapse/persist as other
   panels. Head count: `412k tok · 87 calls · 10m`. Body:
   - inline-SVG bar strip of `beats` (height = tok, live pulse on last bar when session is live);
   - three ranked lists with proportional bars: **Tools** (time, calls), **Agents** (tokens),
     **Models** (tokens). Top 6 each, "+N more".
7. Tests: spine tests stay (update the chevron-absent pin → chevron present); ordering test
   `test_cr_detail_latest_and_now.py:205-218` → Now, then heartbeat+spine, then columns; add a test
   for the `cr.progressView` default (unset → heartbeat) and the Config row; capability table: add a
   "Heartbeat panel (new)" row.

### Sequencing / agents
- A (sonnet): server 1-4. B (sonnet): client 5-6 against the shape above — parallel with A.
- C (haiku sweeper): test edits 7, after B.
- gate-runner (haiku): `unset TRACKER_AUTH; make check` + `node --check` on the JS (gate misses
  load-time JS errors). reviewer (opus): adversarial pass.

### Risk + fallback
- Per-tool time via result-timestamp minus use-timestamp includes parallel overlap (two tools at
  once both count). Fallback: label it "wall time", not "compute".
- Payload: buckets capped at 60, lists capped server-side at 12 → constant size on the 2s poll.
- Shared keyframes: keep `.crd-seg-dot` + `crd-now-pulse` for the Now card.

## Revised plan (opus round 1) — SUPERSEDED by "FINAL plan (opus round 2)" below

Opus review of v1: 3 HIGH / 4 MED / 3 LOW. HIGH: (1) usage double/triple-counted — Claude writes one
assistant message as several jsonl lines with the same `message.id` + usage; `tokens` today is 2-3x
inflated (9b047262: in 598M vs 280M deduped). (2) `tok` incl. cache_read is ~97% re-read context —
chart `out` + `fresh`, show `cache` separately. (3) tool_result−tool_use time ranks human waiting
(AskUserQuestion 44h) and double-counts parallel calls — merge intervals, split waits out.
MED: panels start folded (defaultFolded()); writePref JSON-quotes values; 4 providers not 2
(augment_ext `_parse`); subagent tokens must fold into by_model/total too.

**Shape** — `session["heartbeat"]`, all 4 producers:
`{span:[t0,t1], beats:[{t,out,fresh,cache,calls}] (<=60), by_tool:[{name,calls,busy_ms|None}] (<=12,
calls desc then busy_ms), waiting_ms:n|None, by_agent:[{label,model,out,fresh,cache}] (<=12, "main"
first), by_model:[{model,out,fresh,cache}], total:{out,fresh,cache,calls}}`.
Rules: usage counted once per message.id; out=output; fresh=input+cache_creation; cache=cache_read.
Invariant: total == Σby_agent == Σby_model == Σbeats (out/fresh/cache).

**Server**
- S1 `overview.py` `build_heartbeat(turns, tool_iv, tool_calls, agents, n=60)` — pure; bucketing,
  interval merge, `WAIT_TOOLS={"AskUserQuestion","ExitPlanMode","TaskOutput"}` → waiting_ms, caps.
  `turns=[(t,model,out,fresh,cache,label)]`, `tool_iv={name:[(a,b)]}`, `tool_calls={name:n}`.
- S2 `claude.py` `parse_session`: `seen_mid` dedup at L1253 shared with tok_in/tok_out; append main
  turn; tool_use (~L1333) `use_t[id]=(name,epoch)`, tool_result → interval (skip if either ts missing).
- S2b `parse_agents`: per-file `seen_mid`, per-agent turns inside the existing loop (L882-930), no new
  file reads; carry turns as a 6th return element / popped key — never into the /api payload.
- S2c call next to `result["overview"]` (L1563).
- S3 `auggie.py`: per-exchange turn (model_id, finishedAt); tool calls counted, busy_ms=None;
  `_degraded_auggie_detail` → empty heartbeat. by_agent = main only.
- S4 `augment_ext.py` `_parse`: empty heartbeat.

**Client** (`ext_cr_detail.js/.css`, `ext_cr_dialogs.js`)
- C1 `_internal.progressView()` (JSON.parse, "spine" only on exact match, else "heartbeat") and
  `heartbeatModel(hb)` (formatting only).
- C2 Spine chrome hand-built in static markup: `<section class="crd-panel crd-progress"
  data-panel="spine">` + toggle-panel header, body keeps literal `<div class="crd-spine" role="group"`.
  Heartbeat `<section … data-panel="heartbeat">` beside it. Both in ui.panels; one
  `OPEN_BY_DEFAULT={timeline:1,heartbeat:1,spine:1}` used by makePanel and the rebind loop (~L1968).
- C3 renderUpdate: toggle `hidden` by progressView(); skip renderSpine when hidden; renderHeartbeat in
  its own try, after renderTimeline; guard `session.heartbeat||null`.
- C4 CSS `.crd-hb-*`, ≤600px tier, reduced-motion off-switch for `.crd-hb-live`; don't touch
  `.crd-seg-dot`/`crd-now-pulse`. SVG `role="img"` + summary aria-label.
- C5 `CFG_PREF_KEYS.progressView='cr.progressView'` (Reset clears); segmented row after "Cards start
  folded"; fix that row's sub-label.

**Tests** T1 message.id dedup; T2 build_heartbeat merge/wait/invariant/cap; T3 Claude (w/ subagent
dir) + Auggie assertion; T4 provider parity on heartbeat keys; T5 node progressView +
panelDefaultCollapsed; T6 capability 60→61 + row, reduced-motion list += `crd-hb-live`, ordering
Now < progress panels < columns.

**Sequencing** A (sonnet) S1-S4+T1-T4 ‖ B (sonnet) C1-C5+T5 against the frozen shape → C (haiku) T6 →
gate-runner (haiku) `unset TRACKER_AUTH; make check` → opus reviewer.

**Residual (self-review, non-blocking)** R1 turns must not leak into the payload; R2 multi-day
sessions → coarse bars; R3 dedup assumes unique message.id (held in all samples); R4 WAIT_TOOLS is a
hand list; R5 classic app.js view has no heartbeat (documented gap). Poll cost: parse_session already
~4s on a 25MB session — add no file reads.

## Reconciliation of opus round 2 (main thread, 2026-10-29)

Each finding judged against the code (spot-checked: test_tracker.py:251, test_selfcheck.py:138,
scripts/bundle.py HEADER/ORDER, ext_cr_detail.js:2286-2289, ext_cr_boot.js:982-983).

| # | Finding | Verdict | Action |
|---|---|---|---|
| F1 | dedup must gate only the usage add; id-less lines still sum | confirmed (L251 expects 165 from id-less turns) | keep |
| F2 | expanded panel starves `.crd-columns` | confirmed | keep (one CSS max-height) |
| F3 | Bash intervals include permission/sleep waits | confirmed (probe) | keep the 600s per-interval cap |
| F4 | top-N cap breaks invariant; ranking must be server-side | confirmed | keep `rest` rollup |
| F5 | 6th return value breaks `test_selfcheck.py:138` | confirmed | keep `hb=None` out-param |
| F6 | bundle strips imports (fixed HEADER) | confirmed | keep: builder in overview.py, no new imports |
| F7 | Config flip is a dead control | **overstated** — boot.js:983 re-renders detail on every 2s poll, so the flip lands in ≤2s | keep the 2-line `cr:pref` listener (board's existing pattern), LOW |
| F8 | spine loses its live-edge anchor after collapse | confirmed (key consumed at L2287 while hidden) | keep |
| F9 | tracker-gap checklist gaps | confirmed | keep T7 api + page assertions, restart + curl, timing |
| F9 | T7 `location.hostname` ±400-char grep | **overengineered fix** — the panel records nothing, so there is no host gating to protect | drop the grep assertion |
| F10 | heartbeat total incl. agents ≠ main-only `tokens` | confirmed | keep "incl. N agents" + main-row == tokens |
| — | `test_view_parity.py` "same info in both UIs" ruling vs. no classic heartbeat | **missed by both / unexamined** — nobody checked whether that test pins features | implementer B checks it; if it pins, add the classic gap to its allowlist with a reason, else document in the PR |

## FINAL plan (opus round 2, 2026-10-29) — THE PLAN OF RECORD (minus the dropped T7 hostname grep)

Round-2 verdict on round 1: refuted as written. Findings F1-F10 in the table above.

### Shape — `session.heartbeat`
Filled by Claude + Auggie; explicit on augment_ext + degraded Auggie; guarded by
`registry.parse_any` `d.setdefault("heartbeat", empty_heartbeat())` (precedent registry.py:181-189).
```
{span:[t0,t1]|null, bucket_s:int, beats:[{t,out,fresh,cache,calls}] (<=HB_BUCKETS=60),
 by_tool:{rows:[{name,calls,busy_ms|null}], rest:{n,calls}|null},
 waiting_ms:int|null,
 by_agent:{rows:[{label,aid,model,out,fresh,cache}], rest:{n,out,fresh,cache}|null},
 by_model:{rows:[{model,out,fresh,cache}], rest:…|null},
 total:{out,fresh,cache,calls}, agents_n:int, note:str|null}
```
out=output; fresh=input+cache_creation; cache=cache_read. Tools ranked busy_ms desc (nulls last),
calls desc, name. Agents: main first, then out+fresh+cache desc. Models: out+fresh+cache desc.
Invariant: total = Σrows+rest (agents, models) = Σbeats when span set; untimed turns → last bucket.

### Server (sonnet, agent A)
- S1 `overview.py` §heartbeat: `HB_BUCKETS=60, HB_TOP=8, HB_TOOL_CAP_S=600,
  HB_WAIT_TOOLS={"AskUserQuestion","ExitPlanMode","TaskOutput"}, HB_UNCAPPED={"Agent","Task"}`;
  `build_heartbeat(turns, calls, intervals=None, labels=None, note=None)` with
  `turns=[(t,model,out,fresh,cache,who)]` (who ""=main or aid), `calls=[(t,name,who)]`,
  `intervals={name:[(a,b)]}|None` (None → busy_ms/waiting_ms null), `labels={aid:(label,model)}`.
  `bucket_s=max(1,-(-(t1-t0)//HB_BUCKETS))`; merge overlapping intervals per tool; WAIT tools 100%
  waiting; other tools capped at 600s per interval except HB_UNCAPPED, excess → waiting.
  `empty_heartbeat(note=None)=build_heartbeat([],[],note=note)`. Pure, no new imports; all
  module-level names prefixed `HB_`/`_hb_` (bundle flattens one namespace).
- S2 `claude.py parse_session` ~L1253: `mid=msg.get("id")`;
  `if u and not (mid and mid in seen_mid): if mid: seen_mid.add(mid); tok_in+=…; tok_out+=…;
  hb_turns.append(…)` — never `continue` the line; `ctx_current` (L1257) untouched; `or 0` on every
  usage field. On lines with a content list compute `ep=_ts_epoch(ts)` once; tool_use → `hb_calls` +
  `use_t[bid]=(name,ep)`; tool_result → pop `use_t` into `hb_iv[name]` when both ends > 0.
- S2b `parse_agents(path, hb=None)`: inside the existing per-line loop (L862-930), per-file `seen`,
  append turns/calls/intervals with `who=aid`, each line's own `timestamp`;
  `labels[aid]=(" ".join(task.split())[:60] or "agent "+aid[:7], model)`. Return value UNCHANGED
  (test_selfcheck.py:138 unpacks 5). No new file reads.
- S2c next to `result["overview"]` (L1563): `result["heartbeat"]=build_heartbeat(hb_turns,hb_calls,
  hb_iv,hb_labels)`; extend the existing `from ..overview import` line.
- S3 `auggie.py` L588-600: one turn per token_usage exchange `(_ts_epoch(finishedAt),
  ex.model_id or "", out, in+cc, cr, "")`, one call per tool_use, `intervals=None`, note
  "Auggie logs no per-tool timing — tools ranked by calls."; `_degraded_auggie_detail` (L478) →
  `empty_heartbeat("Session file unreadable — nothing to chart.")`.
- S4 `augment_ext.py _parse` (~L286): `empty_heartbeat("Augment's VS Code extension keeps usage in
  its own store — nothing to chart.")`.
- S5 `registry.parse_any`: setdefault guard.

### Client (sonnet, agent B, parallel with A against the frozen shape)
- C1 `ext_cr_detail.js` pure helpers in `_internal`: `progressView()` (JSON.parse `cr.progressView`;
  "spine" only on exact match else "heartbeat"); `applyProgressView(node,view)` (toggle `hidden` on
  `[data-panel=heartbeat]`/`[data-panel=spine]` sections, null-safe); `panelDefaultCollapsed(key)`
  (`OPEN_BY_DEFAULT={timeline:1,heartbeat:1,spine:1}` else `defaultFolded()`, used by the rebind loop
  ~L1968); `fmtTokS(n)` (950→"950", 1234→"1.2k", 18234→"18k", 1234567→"1.2M", 18.2e6→"18M");
  `heartbeatSummaryHtml(hb)`, `heartbeatHtml(hb, live)` — string builders, everything via `esc()`.
- C2 SKELETON (L1263-1281): order Now, heartbeat, spine, columns (markup in Design spec). Keep the
  literal `<div class="crd-spine" role="group"`. Move "PROGRESS SPINE" into the panel header, delete
  `.crd-spine-label`; header count `class="crd-panel-count crd-spine-count mono"` so renderSpine
  (L2267) fills the collapsed summary. Register `ui.panels.heartbeat`/`ui.panels.spine` in mount.
- C3 `renderUpdate`: store `ui.lastState`; `applyProgressView`; renderSpine only when spine visible;
  `try{renderHeartbeat(…)}catch(e){}` after renderTimeline with `session.heartbeat||null`; skip when
  `JSON.stringify(hb)+live === wrap._hbSig` (stops the pulse restarting every poll);
  `live = detailIsWorking(session, nowSec-(session.mtime||0) < LIVE_WINDOW)`.
- C4 in mount: `if (ctx&&ctx.on) ctx.on('cr:pref', p => p&&p.key==='cr.progressView'&&ui.lastState&&
  renderUpdate(root,ctx,ui.lastState))`; in the toggle-panel case (~L1545) when key==='spine' and
  expanding: `ui._spineZoomKey=undefined; repaintSpine(node,ctx,ui)`; keydown Enter/Space on
  `[data-act=toggle-panel][role=button]` → click(); setPanelCollapsed sets `aria-expanded` only when
  role=button.
- C5 CSS per Design spec.
- C6 `ext_cr_dialogs.js`: `CFG_PREF_KEYS.progressView='cr.progressView'`; row after "Cards start
  folded"; fix that row's sub-label.
- C7 check `tests/test_view_parity.py` (reconciliation row "missed by both").

### Tests
- T1 `tests/test_tracker.py`: 3 lines share one id, each usage `{in 10, cr 100, cc 5, out 7}`, blocks
  thinking/text/tool_use(Bash) → `tokens=={"in":115,"out":7}` AND text narration + command still
  captured (red before fix: 345). Existing L251 (id-less) still 165.
- T2 new `tests/test_heartbeat.py` (build_heartbeat): merge [0,10]+[5,15]=15000ms; WAIT tool →
  waiting; Bash 0..1000s → busy 600000 + waiting 400000; intervals=None → nulls; empty → span None +
  zeros; untimed turn → last bucket; 132 agents → 8 rows + rest.n=124 with Σrows+rest = total;
  invariants.
- T3 selfcheck `_run()`: Claude L138 fixture + agent file with duplicate-id usage → main row ==
  `tokens`, agent row counted once. Auggie: total out=20, fresh+cache=110, busy_ms null, note set.
- T4 parity: claude/auggie/augment-vscode share the heartbeat key set; setdefault fires for a stub.
- T5 node on the real bundle `_internal`: progressView (unset, '"spine"', raw spine, garbage);
  applyProgressView hidden toggle; panelDefaultCollapsed; heartbeatHtml (note-only empty state, rest
  line, "—" for null busy, waiting line only when >0, `<img>` tool name escaped); fmtTokS table.
- T6 (haiku sweeper): capability 60→61 + `[61,'Heartbeat panel (new)','detail']`; `crd-hb-live` in
  the reduced-motion list (test_cr_spine_window.py:273); ordering (latest_and_now:205) Now <
  `data-panel="heartbeat"` < spine literal < columns; F2 CSS pin (`.crd-hb .crd-panel-body` has
  max-height + overflow-y:auto); Config row + key present. The `crd-spine-chevron` ban stays.
- T7 `test_integration.py TestServerEndToEnd`: `/api/session?id=auggie:ss` has `heartbeat.total`;
  page contains `data-panel="heartbeat"`. (hostname grep dropped — reconciliation.)

### Sequencing
A (S1-S5, T1-T4, T7-api) ‖ B (C1-C7, T5, T7-page), sonnet → C (haiku sweeper) T6 + README line →
gate-runner (haiku): `unset TRACKER_AUTH; make check` (per-module if OOM), `node --check` on the 3 JS
files, bundle smoke `make bundle && python3 -c "exec(open('dist/tracker.py').read().split('if
__name__')[0]); print(build_heartbeat([],[]))"` → proof (haiku): `PORT=8795 make serve` in bg (never
pkill; stop by PID), curl `/api/session?id=<claude sid>` and `?id=auggie:<uuid>` → `.heartbeat`, grep
`/` for `crd-hb`, time parse_session on the 25MB session (baseline 3.66s, budget ≤4.0s) → opus review.

### Risk + fallback
Parse cost >10% → memoize heartbeat inputs on (path, mtime). Multi-day → coarse bars, foot says
"each bar ≈ Xh". WAIT_TOOLS + 600s cap are hand rules — name both in the PR.

## Design spec (opus round 2)

Markup (static in SKELETON; `hidden` set by applyProgressView):
```
<section class="crd-panel crd-hb" data-panel="heartbeat">
 <header class="crd-panel-head" data-act="toggle-panel" data-panel="heartbeat" data-col="progress"
   role="button" tabindex="0" aria-expanded="true" aria-controls="crd-hb-body">
  <span class="crd-chevron">{chevron-down}</span><span class="crd-panel-label">Heartbeat</span>
  <span class="crd-panel-count mono"></span></header>
 <div class="crd-panel-body" id="crd-hb-body"></div></section>
<section class="crd-panel crd-progress" data-panel="spine">  (same header; id crd-spine-body;
  label "Progress spine"; count span class="crd-panel-count crd-spine-count mono")
 <div class="crd-panel-body" id="crd-spine-body"><div class="crd-spine" role="group"
   aria-label="Progress spine"> …existing sr/head(spans+hint, NO label)/scroll/foot unchanged…
 </div></div></section>
```
heartbeatHtml body: `<svg class="crd-hb-svg" viewBox="0 0 {nb*10} 40" preserveAspectRatio="none"
role="img" aria-label="{summary}" focusable="false">`, one `<g class="crd-hb-bin[ crd-hb-live]">`
per bucket with `<title>` + `<rect class="crd-hb-hit">` (w10 h40) + `<rect class="crd-hb-in">` +
`<rect class="crd-hb-out">` (w8, stacked from bottom, linear to max bucket out+fresh, min 1 unit when
non-zero) → `<div class="crd-hb-foot mono">` (first clock · "each bar ≈ 4m" · "now · live" or last
clock) → `<div class="crd-hb-legend mono">■ out ■ in · cached reads not drawn` →
`<div class="crd-hb-lists">` with three `<section class="crd-hb-list"><h4 class="crd-hb-h">Tools ·
busy time</h4><ol>` rows `<li class="crd-hb-row" title="exact">` = `.crd-hb-name mono`,
`.crd-hb-val mono`, `<span class="crd-hb-track" aria-hidden="true">` with
`.crd-hb-seg-out/-in/-cache` (or `-busy`) % widths; `</ol><p class="crd-hb-rest">+124 more · 3.1M</p>`
→ `<p class="crd-panel-footnote">` waiting line and/or `hb.note`.

Text: bin title `14:02–14:06 · 1.2k out · 8.4k in · 210k cached · 7 calls`. Header
`<span>18k out</span> · <span>394k in</span><span class="crd-hb-sum-cache"> · 18M cached</span> ·
<span>87 calls</span><span class="crd-hb-sum-span"> · 2h 14m</span>[ · incl. 12 agents]`. Tool value
`14m · 212×` (or `212×` when busy null → bar encodes calls, title "Tools · calls"). Agent/model value
`1.2M · 18k out`, stacked out/in/cache bar scaled to the largest row total; `main` row
font-weight:600; model via `shortModel()` 10px muted. Waiting: `Waiting on you or a prompt: 3h 12m
(not counted as busy)`. Empty (`!hb` or no beats): `<p class="crd-empty">{hb.note || "No model turns
recorded yet."}</p>`, lists omitted, header count `—`.

CSS (existing variables only; no new keyframes):
`.cr .crd-hb,.cr .crd-progress{margin:16px 24px 0;flex:0 0 auto}` (never set `display` — keeps
`hidden` working); `.cr .crd-progress .crd-spine{margin:0;padding:0;border:0;background:none;
box-shadow:none;border-radius:0}`; `.cr .crd-hb .crd-panel-body{max-height:min(300px,36vh);
overflow-y:auto}`; `.crd-hb-svg{display:block;width:100%;height:40px}`; fills `.crd-hb-out`/
`.crd-hb-seg-out`/`.crd-hb-seg-busy` → `--line-focus`, `.crd-hb-in`/`.crd-hb-seg-in` →
`--line-agent`, `.crd-hb-seg-cache` → `--line-strong`, `.crd-hb-hit` transparent →
`.crd-hb-bin:hover .crd-hb-hit` `--fill-row-hover`; `.crd-hb-live rect:not(.crd-hb-hit){animation:
crd-now-pulse var(--motion-pulse-duration,2.4s) ease-in-out infinite}`; `.crd-hb-lists{display:grid;
grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:10px}`; `.crd-hb-h`
eyebrow (10.5px/600/uppercase/.07em/`--text-eyebrow`); `.crd-hb-row` grid `1fr auto`, 3px pad, 12px;
`.crd-hb-name` ellipsis min-width:0; `.crd-hb-val` 11px `--text-muted` tabular-nums; `.crd-hb-track`
grid-column 1/-1, flex, 4px, radius 2px, `--surface-sunken`; foot/legend/rest 10px `--text-muted`;
`@media(max-width:480px)` margin `10px 12px 0`, svg 32px, hide `.crd-hb-sum-cache`/`.crd-hb-sum-span`;
`@media(prefers-reduced-motion:reduce){.cr .crd-hb-live rect{animation:none}}`.

Config row (Interface, after "Cards start folded"): label `Progress view`; sub-label `Which panel
sits under the Now card: Heartbeat (where tokens and tool time went) or Progress spine (the task plan
over time).`; `segmented([['heartbeat','Heartbeat'],['spine','Progress spine']],
readPref(CFG_PREF_KEYS.progressView,'heartbeat'), v=>writePref(…))`. "Cards start folded" sub-label →
`…except Conversation and the progress panel.`

States: live → last bin pulses; idle → no pulse, foot shows last clock; collapsed → header summary,
persisted `cr.detail.panel.<sid>.heartbeat`, open by default; hidden by switch → `hidden`, not rendered.

Mock:
```
┌ ▾ HEARTBEAT          18k out · 394k in · 18M cached · 87 calls · 2h 14m · incl. 3 agents ┐
│ ▁▁▃▇▅▂▁ ▁▂▆█▃▁▁▁▂▃▅▂▁    ▁▂▃▂▁▁▃▅▇▆▃▂▁ ▁▁▂▄▆▅▃▂▁▁▂▃▂▁ ▁▁▂▃▅▃                    ▂▅▓ │
│ 09:12 first turn               each bar ≈ 2m                                  now · live │
│ ■ out ■ in · cached reads not drawn                                                      │
│ TOOLS · BUSY TIME      │ AGENTS · TOKENS              │ MODELS · TOKENS                  │
│ Agent      41m · 9×    │ main        12M · 11k out    │ opus 4.7    15M · 14k out        │
│ Bash       14m · 212×  │ Opus plan review 4.1M · 5k   │ sonnet 4.6  3.1M · 4k out        │
│ Edit       38s · 40×   │ +1 more · 0.9M               │                                  │
│ Waiting on you or a prompt: 3h 12m (not counted as busy)                                 │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```
Residual (self-review): R1 spine count font becomes the 11px muted panel style (intentional);
R2 fmtAge floors; R3 classic app.js view has no heartbeat — see C7; R4 F8 needs the manual browser
check; R5 132-agent session only proven at the timing run.

## Post-implementation opus review (round 3) + reconciliation

Opus verdict: fix-then-ship. Verified clean: dedup on 2006 real id-groups (0 differ), invariant +
main==tokens on 6 real sessions, parse 3.43s vs 3.71s base, escaping, `hidden`, bundle smoke.

| # | Finding | Verdict | Fix (owner) |
|---|---|---|---|
| 1 HIGH | reduced-motion override (0,2,1) loses to `.cr .crd-hb-live rect:not(.crd-hb-hit)` (0,3,1) | confirmed (headless Chrome) | same selector in the media block + selector-equality test (haiku) |
| 2 MED | 600s cap applied to MERGED blocks → parallel busy reported as waiting | confirmed (spec F3 says per interval) | cap raw intervals, then union; wait = union(raw) − union(capped) (sonnet S) |
| 3 MED | renderUpdate wiring untested | confirmed | export renderHeartbeat + setPanelCollapsed; behaviour tests + ONE source pin for the renderHeartbeat call; wider pin set trimmed as overengineered (sonnet J) |
| 4 MED design | agent rows labelled with prompt text | confirmed | label = `toolUseResult.description` by agentId from parse_session tool_result lines (sonnet P) |
| 5 MED design | legend squares uncoloured; cache segment unexplained | confirmed | `crd-hb-key-out/in/cache` spans + "cached (lists only)" (JS: sonnet J; CSS: haiku) |
| 6 LOW | fmtTokS no billions | confirmed | `B` tier, 999.6M→"1B" (sonnet J) |
| 7 LOW | empty-model zero row "unknown 0" | confirmed | drop model=="" && total 0 (sonnet S) |
| 8 LOW | README stale (Now ABOVE spine; collapsed default); classic gap undocumented | confirmed | README edits (haiku) + PR note |
| 9a LOW | bar y<0 with min height | confirmed | clamp (sonnet J) |
| 9b | pulse restarts on hb change; waiting sums overlap | accepted | PR note |
| 9c | no date on multi-day foot | overengineered now | skip |
| — | mounted panel never seen in a real browser | not examined by any review | final report flags it |

## Gate status (2026-10-30)
All 4 round-3 fixes landed with red→green tests. Per-module gate: 93 modules, 91 OK, test_selfcheck
0 tests by design, test_folder_terminal SIGKILL flake (passes on rerun and on base 594ac65). The
pre-commit hook's single-process run gets killed at the forkpty warning (3/3); user chose "retry
the hook in background" (no --no-verify). Live proof on :8811: main row == tokens (Claude + Auggie).

## Log
- 2026-10-29: mapped; plan written; user answered (switch, both collapsible, opus plan review).
- 2026-10-29: plan revised for the switch; sent to opus adversarial plan review.
- 2026-10-29: opus review → revised plan (above) is the plan of record; user: fix tokens everywhere; pipeline = opus plan+design review → /tracker-gap → opus review → /tracker-push.
- 2026-10-29: opus plan+design review round 2 started.
- 2026-10-29: round 2 → FINAL plan + design spec; main thread reconciled (table); implementing via /tracker-gap.
